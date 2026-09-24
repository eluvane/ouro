#!/usr/bin/env python3
"""Host-only ordering, source ownership, publication and cache regressions."""
from __future__ import annotations

import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tarfile
import unittest
from unittest.mock import patch

import bootstrap_compiler as bootstrap
import bootstrap_inputs as inputs
import compact_source
import ci_gate
import ouro_build as build
from ourosmith.limits import RunResult
from repo_support import hash_json, sha256_file, write_json_atomic


class BootstrapCompilerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ouro-bootstrap-contract-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.work = self.root / "work"
        self.work.mkdir()
        self.events = []
        self.rejected_root = None
        self.rejected_source_form = None
        self.different_c = False
        self.abi_stdout = bootstrap.ABI_STDOUT

    def fixture(self, *, compact_sources=False):
        roots = [f"compiler/source-{index}.ouro" for index in range(14)] + ["compiler/backend.ouro"]
        graph = {name: [name] for name in [*roots, *bootstrap.ACCEPTANCE_ROOTS]}
        roles = ["historical/c0", "historical/bridge", "o"] + (["compact"] if compact_sources else [])
        for role in roles:
            for name in {*graph, "scripts/bootstrap_compiler.py"}:
                path = self.work / role / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("owned " + role + "/" + name, encoding="utf-8")
        cc = self.root / "host-compiler-fixture"
        cc.write_bytes(b"fixed host compiler fixture")
        selected = {"roots": roots, "unit_graph": graph, "environment": {}, "sources": {},
                    "source_form": compact_source.KIND if compact_sources else "original",
                    "cc_executable": str(cc), "cc_sha256": sha256_file(cc)}
        snapshot = {"kind": bootstrap.KIND + ".inputs", "key": hash_json(selected), "selected": selected,
            "config": {**build.DEFAULTS, "verbosity": "quiet"}, "bridge_graph": graph,
            "roots": {"c0": "historical/c0", "bridge": "historical/bridge", "p1": "o", "p2": "compact" if compact_sources else "o"},
            "inputs": {path.relative_to(self.work).as_posix(): sha256_file(path)
                       for path in self.work.rglob("*") if path.is_file()}}
        write_json_atomic(self.work / "inputs.json", snapshot)
        return snapshot

    def fake_run(self, argv, *, cwd, env, timeout_s, memory_mb):
        self.assertEqual(timeout_s, bootstrap.TIMEOUT_S)
        self.assertEqual(memory_mb, bootstrap.MEMORY_MIB)
        self.assertEqual(env["OURO_JOBS"], "1")
        self.events.append((list(argv), cwd))
        stdout, stderr, code = "", "", 0
        if "worker" in argv:
            phase = argv[argv.index("--phase") + 1]
            action = argv[argv.index("--action") + 1]
            out = self.work / "out" / phase
            if action in {"c0", "link"}:
                binary = out / ("c/ouro1" if action == "c0" else "ouro1")
                binary.parent.mkdir(parents=True, exist_ok=True)
                binary.write_bytes(b"MZ" + b"host fixture only; not a real compiler\n" * 150)
            elif action == "frontend":
                data = "current generated frontend\n"
                if self.different_c and phase == "p2":
                    data += "different output\n"
                (out / "driver_u.c").write_text(data)
            elif action == "abi-build":
                (out / ("abi.exe" if os.name == "nt" else "abi")).write_bytes(b"host law fixture")
        elif "--module" in argv:
            stdout = '#include "ouro_rt.h"\nint ouro_export_count_be(void) { return 0; }\n'
        elif len(argv) == 1:
            stdout = self.abi_stdout
        elif argv[1] == "check":
            source = argv[2]
            if source == "bootstrap-bad.ouro":
                code = 1
                stderr = ("bootstrap-bad.ouro: type mismatch in exact_index\nCHECK_FAIL: front end rejected the input\n"
                          "ouro1: CErr tag=0 n=1\nouro1: CErr code=41 det=78\n")
            elif source == self.rejected_root and (self.rejected_source_form is None or cwd.name == self.rejected_source_form):
                code, stderr = 1, "current root rejected\n"
            else:
                stdout = "CHECK_OK\n"
        else:
            self.fail(f"unexpected host fixture command: {argv}")
        return RunResult("ok", code, stdout, stderr, 0.01, 1.0, list(argv))

    def test_compaction_preserves_literal_bytes_directives_and_line_boundaries(self):
        literal = '"  -- @entry other\\n\\\"\\\\\t\r\nЮник\u043eд  "'.encode()
        source = (b'  -- ordinary comment with "\r\n\r\n  -- @entry main\r\n'
                  b"def foo'   :  String := " + literal + b'; -- trailing comment\r\n'
                  b"  -- \t@export foo'; @doc docs/build.md\n\n  def main : Nat :=  1;\n")
        expected = (b"-- @entry main\r\ndef foo' : String := " + literal + b";\n"
                    b"-- \t@export foo'; @doc docs/build.md\ndef main : Nat := 1;\n")
        result = compact_source.compact_source(source)
        self.assertEqual(result, expected)
        self.assertEqual(compact_source.compact_source(result), result)
        self.assertLess(len(result), len(source))

    def test_compaction_keeps_token_separators_and_does_not_repair_invalid_bytes(self):
        source = b"  f' -  - g'  : =  x; -- removed\n\tfoo\vbar\xc2\xa0baz\n"
        self.assertEqual(compact_source.compact_source(source), b"f' - - g' : = x;\nfoo\vbar\xc2\xa0baz\n")
        self.assertEqual(compact_source.compact_source(b' -- comment "\n\t'), b"")
        for invalid in (b'"missing', b'"trailing\\', b'"escaped\\"'):
            with self.subTest(source=invalid), self.assertRaisesRegex(ValueError, "unterminated string"):
                compact_source.compact_source(invalid)

    def test_compaction_preserves_grouped_and_aliased_imports(self):
        from selfhost_module_cache import quoted_import_targets
        source = (b'import  "../std/data.ouro", -- first import\n "../std/list.ouro", ;\n'
                  b'import "../std/text.ouro" as Text;\n'
                  b'def fake : String := "import \\\"not-a-module.ouro\\\";";\n')
        original = quoted_import_targets(source.decode(), "compiler/probe.ouro")
        self.assertEqual(original, ["std/data.ouro", "std/list.ouro", "std/text.ouro"])
        self.assertEqual(quoted_import_targets(compact_source.compact_source(source).decode(), "compiler/probe.ouro"), original)

    def test_current_o_snapshot_is_independent_of_historical_projection(self):
        root = self.root / "repo"
        (root / "compiler/bootstrap").mkdir(parents=True)
        for name in (inputs.MANIFEST, inputs.ARCHIVE):
            shutil.copyfile(inputs.ROOT / name, root / name)
        names = {*bootstrap.HELPERS, "std/prelude.ouro"}
        for name in names:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('representation Nat := "ouro.nat";\n-- current ' + name + "\n")
        stage0 = {}
        for name in inputs.STAGE0:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixed historical stage0 fixture")
            stage0[name] = sha256_file(path)
        selected = {"sources": {name: sha256_file(root / name) for name in names}, "stage0": stage0,
            "archive_sha256": sha256_file(root / inputs.ARCHIVE), "manifest_sha256": sha256_file(root / inputs.MANIFEST)}
        cfg = build.ResolvedConfig(dict(build.DEFAULTS), {})
        before = (root / "std/prelude.ouro").read_bytes()
        for form in ("original", compact_source.KIND):
            with self.subTest(source_form=form):
                selected["source_form"] = form
                work = self.work / form
                work.mkdir()
                snapshot = bootstrap.freeze(root, work, selected, cfg)
                self.assertEqual((work / "o/std/prelude.ouro").read_bytes(), before)
                self.assertEqual((root / "std/prelude.ouro").read_bytes(), before)
                self.assertNotEqual((work / "historical/bridge/std/prelude.ouro").read_bytes(), before)
                self.assertFalse((work / "o/compiler/stage0").exists())
                self.assertEqual(bootstrap.changed_inputs(work, snapshot), [])
                self.assertEqual(snapshot["roots"]["p1"], "o")
                if form == "original":
                    self.assertEqual(snapshot["roots"]["p2"], "o")
                    self.assertIsNone(snapshot["compaction"])
                else:
                    self.assertEqual(snapshot["roots"]["p2"], "compact")
                    compact = work / "compact/std/prelude.ouro"
                    self.assertEqual(compact.read_bytes(), compact_source.compact_source(before))
                    self.assertEqual(snapshot["compaction"]["files"]["std/prelude.ouro"]["compact_sha256"], sha256_file(compact))
                    self.assertEqual(snapshot["inputs"]["compact/std/prelude.ouro"], sha256_file(compact))
                    self.assertFalse((work / "compact/compiler/stage0").exists())
                    for name in bootstrap.HELPERS:
                        self.assertEqual((work / "compact" / name).read_bytes(), (root / name).read_bytes())

    def test_current_key_tracks_content_and_host_inputs_without_using_timestamps(self):
        root = self.root / "key-fixture"
        roots = [source for _tag, _module, source, _file in bootstrap.frontend.FRONTEND_TUS] + ["compiler/backend.ouro"]
        graph = {name: ([name] if name == "std/prelude.ouro" else ["std/prelude.ouro", name])
                 for name in [*roots, *bootstrap.ACCEPTANCE_ROOTS]}
        names = {*bootstrap.HELPERS, *bootstrap.RUNTIME, *inputs.STAGE0, inputs.MANIFEST, inputs.ARCHIVE,
                 "runtime/host-key-extra.h", *(name for units in graph.values() for name in units)}
        for name in names:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("owned key fixture " + name, encoding="utf-8")
        compiler = self.root / "selected-host-cc"
        compiler.write_bytes(b"fixed host C compiler")
        cfg = build.ResolvedConfig(dict(build.DEFAULTS), {})
        with patch.object(bootstrap.frontend, "collect_units", side_effect=lambda name: graph[name]), \
             patch.object(build, "choose_cc", return_value=str(compiler)), \
             patch.object(build, "compiler_id", return_value="fixed fixture version"):
            selected = bootstrap.current_inputs(root, cfg, build)
            key = hash_json(selected)
            compact = bootstrap.current_inputs(root, cfg, build, compact_sources=True)
            self.assertNotEqual(hash_json(compact), key)
            for name in ("std/prelude.ouro", "runtime/host-key-extra.h", "scripts/bootstrap_compiler.py",
                         "scripts/compact_source.py", inputs.STAGE0[0], inputs.MANIFEST, inputs.ARCHIVE):
                with self.subTest(input=name):
                    path = root / name
                    original, timestamp = path.read_bytes(), path.stat()
                    path.write_bytes(original + b" changed without a new timestamp")
                    os.utime(path, ns=(timestamp.st_atime_ns, timestamp.st_mtime_ns))
                    self.assertNotEqual(hash_json(bootstrap.current_inputs(root, cfg, build)), key)
                    path.write_bytes(original)
                    self.assertEqual(hash_json(bootstrap.current_inputs(root, cfg, build)), key)
            with patch.dict(os.environ, {"CPATH": "bootstrap fixture include environment"}):
                self.assertNotEqual(hash_json(bootstrap.current_inputs(root, cfg, build)), key)
            compiler.write_bytes(b"changed compiler with identical version output")
            self.assertNotEqual(hash_json(bootstrap.current_inputs(root, cfg, build)), key)

    def test_compact_stage_checks_both_forms_before_emitting_from_compact_sources(self):
        snapshot = self.fixture(compact_sources=True)
        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            report = bootstrap.chain(self.work, snapshot, build)
        expected = set(snapshot["selected"]["roots"]) | set(bootstrap.ACCEPTANCE_ROOTS)
        for form in ("o", "compact"):
            checked = {argv[2] for argv, root in self.events if len(argv) > 2 and argv[1] == "check"
                       and argv[0] == str(self.work / "out/p1/ouro1") and root == self.work / form}
            self.assertEqual(checked, expected)
        emitted = [(argv, root) for argv, root in self.events if "worker" in argv and "p2" in argv
                   and any(action in argv for action in ("frontend", "abi-build", "link"))]
        self.assertEqual(len(emitted), 3)
        self.assertTrue(all(root == self.work / "compact" for _argv, root in emitted))
        self.assertTrue(report["phases"][-1]["all_compact_roots_strictly_checked_before_emission"])
        self.assertEqual(set(report["complete_generated_c_comparison"]), {"driver_u.c", "backend_u.c"})
        self.assertTrue(report["pass"])

    def test_compact_source_rejection_stops_before_p2_emission(self):
        snapshot = self.fixture(compact_sources=True)
        self.rejected_root = snapshot["selected"]["roots"][-1]
        self.rejected_source_form = "compact"
        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            with self.assertRaisesRegex(RuntimeError, "p2/check-compact-14"):
                bootstrap.chain(self.work, snapshot, build)
        self.assertTrue((self.work / "out/p1/driver_u.c").exists())
        self.assertFalse((self.work / "out/p2/driver_u.c").exists())

    def test_compact_generated_c_mismatch_rejects_successor(self):
        snapshot = self.fixture(compact_sources=True)
        self.different_c = True
        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            with self.assertRaisesRegex(RuntimeError, "complete generated frontend/backend C differs"):
                bootstrap.chain(self.work, snapshot, build)
        self.assertFalse(json.loads((self.work / "report.json").read_text())["pass"])

    def test_compact_input_tampering_stops_before_any_subprocess(self):
        snapshot = self.fixture(compact_sources=True)
        (self.work / "compact/compiler/backend.ouro").write_text("changed after freeze")
        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            with self.assertRaisesRegex(RuntimeError, "frozen bootstrap inputs changed"):
                bootstrap.chain(self.work, snapshot, build)
        self.assertEqual(self.events, [])

    def test_build_flag_selects_compact_bootstrap(self):
        with patch.object(bootstrap, "ensure_current_compiler") as ensure, patch.object(build, "trim_cache"):
            build.main(["build", "--compact-sources", "--verbosity", "quiet"])
        self.assertEqual(ensure.call_args.kwargs, {"compact_sources": True})

    def test_last_current_root_rejection_stops_before_p1_emission(self):
        snapshot = self.fixture()
        self.rejected_root = snapshot["selected"]["roots"][-1]
        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            with self.assertRaisesRegex(RuntimeError, "p1/check-14"):
                bootstrap.chain(self.work, snapshot, build)
        p1_frontend = [argv for argv, _root in self.events if "worker" in argv and "p1" in argv and "frontend" in argv]
        self.assertEqual(p1_frontend, [])
        self.assertFalse((self.work / "out/p1/driver_u.c").exists())
        self.assertFalse(json.loads((self.work / "report.json").read_text())["pass"])

    def test_behavior_probes_use_the_complete_frozen_data_closure(self):
        snapshot = self.fixture()
        units = ["std/types.ouro", "std/prelude.ouro", "std/data.ouro"]
        snapshot["selected"]["unit_graph"]["std/data.ouro"] = units
        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            bootstrap.chain(self.work, snapshot, build)
        probes = [argv for argv, _root in self.events
                  if len(argv) > 2 and argv[1] == "check" and argv[2].startswith("bootstrap-")]
        self.assertEqual(len(probes), 2)
        for argv in probes:
            self.assertEqual(argv[4:], [part for unit in [*units, argv[2]] for part in ("--unit", unit)])

    def test_complete_frontend_mismatch_rejects_successor(self):
        snapshot = self.fixture()
        self.different_c = True
        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            with self.assertRaisesRegex(RuntimeError, "complete generated frontend/backend C differs"):
                bootstrap.chain(self.work, snapshot, build)
        self.assertTrue((self.work / "out/p1/driver_u.c").exists())
        self.assertTrue((self.work / "out/p2/driver_u.c").exists())
        self.assertFalse(json.loads((self.work / "report.json").read_text())["pass"])

    def test_abi_protocol_rejects_missing_extra_duplicate_and_reordered_laws(self):
        lines = bootstrap.ABI_STDOUT.splitlines(keepends=True)
        protocols = {
            "marker-only": lines[-1],
            "missing": "".join(lines[1:]),
            "extra": "".join([*lines[:-1], "PASS unexpected law\n", lines[-1]]),
            "duplicate": "".join([lines[0], *lines]),
            "reordered": "".join([lines[1], lines[0], *lines[2:]]),
        }
        for name, stdout in protocols.items():
            with self.subTest(protocol=name):
                self.work = self.root / ("abi-" + name)
                self.work.mkdir()
                self.abi_stdout = stdout
                snapshot = self.fixture()
                with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
                    with self.assertRaisesRegex(RuntimeError, "ABI laws did not return the exact expected protocol"):
                        bootstrap.chain(self.work, snapshot, build)
                self.assertFalse((self.work / "out/p2/driver_u.c").exists())
                self.assertFalse(json.loads((self.work / "report.json").read_text())["pass"])

    def test_frozen_input_change_stops_before_any_subprocess(self):
        snapshot = self.fixture()
        (self.work / "o/compiler/backend.ouro").write_text("changed after freeze")
        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            with self.assertRaisesRegex(RuntimeError, "frozen bootstrap inputs changed"):
                bootstrap.chain(self.work, snapshot, build)
        self.assertEqual(self.events, [])

    def test_unavailable_native_stack_reserve_stops_before_any_subprocess(self):
        snapshot = self.fixture()
        with patch.object(bootstrap, "configure_native_stack", side_effect=OSError("native stack reserve unavailable")), \
             patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            with self.assertRaisesRegex(OSError, "native stack reserve unavailable"):
                bootstrap.chain(self.work, snapshot, build)
        self.assertEqual(self.events, [])
        self.assertFalse(json.loads((self.work / "report.json").read_text())["pass"])

    def test_failed_chain_preserves_installed_compiler(self):
        output = self.root / "installed/ouro1"
        output.parent.mkdir()
        output.write_bytes(b"existing compiler must survive failed bootstrap")
        cfg = build.ResolvedConfig({**build.DEFAULTS, "build_dir": str(self.root / "b"),
                                   "c_build_dir": str(output.parent), "cache_enabled": False}, {})
        before = output.read_bytes()
        with patch.object(inputs, "read_bundle", return_value=({}, {})), \
             patch.object(inputs, "verify_stage0"), \
             patch.object(bootstrap, "current_inputs", return_value={"owned": "current inputs"}), \
             patch.object(bootstrap, "freeze", return_value={}), \
             patch.object(bootstrap, "chain", side_effect=RuntimeError("strict source rejected")):
            with self.assertRaisesRegex(RuntimeError, "strict source rejected"):
                bootstrap.ensure_current_compiler(cfg, build, self.root)
        self.assertEqual(output.read_bytes(), before)
        self.assertFalse(output.with_name("ouro1.bootstrap.json").exists())

    def test_cache_rejects_changed_binary_foreign_producer_and_partial_c_comparison(self):
        snapshot = self.fixture()
        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            report = bootstrap.chain(self.work, snapshot, build)
        output = self.root / "installed-compiler"
        shutil.copyfile(self.work / report["binary"], output)
        receipt = self.root / "receipt.json"
        data = {"kind": bootstrap.KIND, "key": snapshot["key"], "selected": snapshot["selected"],
                "work": str(self.work), "binary_sha256": sha256_file(output), "report_sha256": sha256_file(self.work / "report.json")}
        write_json_atomic(receipt, data)
        self.assertTrue(bootstrap.installed_current(output, receipt, snapshot["selected"]))
        valid_binary = output.read_bytes()
        output.write_bytes(b"foreign compiler" * 400)
        forged = {**data, "binary_sha256": sha256_file(output)}
        write_json_atomic(receipt, forged)
        self.assertFalse(bootstrap.installed_current(output, receipt, snapshot["selected"]))
        output.write_bytes(valid_binary)
        partial = copy.deepcopy(report)
        del partial["complete_generated_c_comparison"]["backend_u.c"]
        write_json_atomic(self.work / "report.json", partial)
        write_json_atomic(receipt, {**data, "report_sha256": sha256_file(self.work / "report.json")})
        self.assertFalse(bootstrap.installed_current(output, receipt, snapshot["selected"]))

    def test_frontend_flag_is_rejected_without_touching_stage0_or_entering_build(self):
        before = {name: (build.ROOT / name).read_bytes() for name in inputs.STAGE0}
        with patch.object(build, "run_build", side_effect=AssertionError("build entered before argument rejection")):
            for operation in ("build", "rebuild"):
                with self.subTest(operation=operation), self.assertRaises(SystemExit) as error:
                    build.main([operation, "--frontend"])
                self.assertEqual(error.exception.code, 2)
        self.assertEqual({name: (build.ROOT / name).read_bytes() for name in inputs.STAGE0}, before)

    def compiler_artifact_fixture(self):
        self.work = self.root / "_build/bootstrap/artifact-contract"
        self.work.mkdir(parents=True)
        snapshot = self.fixture()
        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            report = bootstrap.chain(self.work, snapshot, build)
        output = self.root / "_build/c/ouro1"
        output.parent.mkdir(parents=True)
        shutil.copyfile(self.work / report["binary"], output)
        output.chmod(0o755)
        receipt = {"kind": bootstrap.KIND, "key": snapshot["key"], "selected": snapshot["selected"],
                   "work": str(self.work), "binary_sha256": sha256_file(output), "report_sha256": sha256_file(self.work / "report.json")}
        write_json_atomic(output.with_name("ouro1.bootstrap.json"), receipt)
        archive = self.root / "compiler.tar.gz"
        ci_gate.export_compiler(self.root, output, snapshot["selected"], archive)
        return output, snapshot["selected"], archive

    def test_compiler_artifact_roundtrip_preserves_complete_verification(self):
        output, selected, archive = self.compiler_artifact_fixture()
        with tarfile.open(archive) as bundle:
            paths = [self.root / member.name for member in bundle.getmembers()]
        self.assertEqual(len(paths), 8)
        before = {path: path.read_bytes() for path in paths}
        for path in paths:
            path.unlink()
        ci_gate.import_compiler(self.root, output, selected, archive, sha256_file(archive))
        self.assertEqual({path: path.read_bytes() for path in paths}, before)
        self.assertTrue(bootstrap.installed_current(output, output.with_name("ouro1.bootstrap.json"), selected))
        if os.name != "nt":
            self.assertEqual(output.stat().st_mode & 0o777, 0o755)
        for path in paths:
            with self.subTest(missing=path):
                path.unlink()
                with self.assertRaisesRegex(ValueError, "does not match"):
                    ci_gate.export_compiler(self.root, output, selected, self.root / "invalid.tar.gz")
                path.write_bytes(before[path])

    def test_compiler_artifact_rejects_wrong_digest_inputs_and_binary(self):
        output, selected, archive = self.compiler_artifact_fixture()
        before = output.read_bytes()
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            ci_gate.import_compiler(self.root, output, selected, archive, "0" * 64)
        self.assertEqual(output.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, "does not match"):
            ci_gate.import_compiler(self.root, output, {**selected, "changed": True}, archive, sha256_file(archive))
        output.write_bytes(b"foreign binary" * 400)
        with self.assertRaisesRegex(ValueError, "does not match"):
            ci_gate.export_compiler(self.root, output, selected, self.root / "invalid.tar.gz")

    def test_compiler_artifact_rejects_missing_extra_duplicate_links_and_corruption(self):
        output, selected, archive = self.compiler_artifact_fixture()
        with tarfile.open(archive) as bundle:
            members = [(member, bundle.extractfile(member).read()) for member in bundle.getmembers()]
        for mutation in ("missing", "extra", "duplicate", "link", "binary", "outside"):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(members)
                if mutation == "missing":
                    changed.pop()
                elif mutation == "extra":
                    changed.append((tarfile.TarInfo("../outside"), b""))
                elif mutation == "duplicate":
                    changed.append(changed[0])
                elif mutation == "link":
                    changed[0][0].type = tarfile.SYMTYPE
                    changed[0][0].linkname = "../outside"
                    changed[0][0].size = 0
                    changed[0] = (changed[0][0], b"")
                elif mutation == "binary":
                    member, data = changed[0]
                    changed[0] = (member, b"x" * len(data))
                else:
                    member, data = changed[1]
                    receipt = json.loads(data)
                    receipt["work"] = str(self.root.parent / "outside")
                    data = json.dumps(receipt).encode()
                    member.size = len(data)
                    changed[1] = (member, data)
                invalid = self.root / "invalid.tar.gz"
                with tarfile.open(invalid, "w:gz") as bundle:
                    for member, data in changed:
                        bundle.addfile(member, io.BytesIO(data))
                with self.assertRaises(ValueError):
                    ci_gate.import_compiler(self.root, output, selected, invalid, sha256_file(invalid))

    def test_missing_python_stops_shell_bootstrap_before_compilation(self):
        shell = shutil.which("sh")
        if shell is None:
            self.skipTest("POSIX shell unavailable for the no-Python bootstrap fixture")
        root = self.root / "shell-fixture"
        (root / "scripts").mkdir(parents=True)
        shutil.copyfile(build.ROOT / "scripts/bootstrap.sh", root / "scripts/bootstrap.sh")
        (root / "scripts/python.sh").write_text('PYTHON=""\n', encoding="utf-8")
        process = subprocess.run([shell, str(root / "scripts/bootstrap.sh")], cwd=root,
                                 text=True, capture_output=True, check=False)
        self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
        self.assertIn("Python 3 is required for the verified current-source bootstrap", process.stderr)
        self.assertFalse((root / "_build").exists())


def run() -> None:
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(BootstrapCompilerTests))
    if not result.wasSuccessful():
        raise AssertionError("bootstrap compiler contract tests failed")


if __name__ == "__main__":
    unittest.main()
