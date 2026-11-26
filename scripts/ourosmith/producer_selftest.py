"""A selected producer owns every executed layer and every source-bound tool."""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import io
import itertools
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from subprocess import CompletedProcess
from threading import Barrier, Event
from types import SimpleNamespace
from unittest.mock import patch

from ourosmith import ROOT
from ourosmith import host
from ourosmith.native import digest, source_inputs
from ourosmith.provenance import binary_state
from repo_support import hash_json


class ProducerTests(unittest.TestCase):
    def test_binary_digest_reads_past_a_chunk_boundary_on_every_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / "fixture.exe"
            data = b"\0\xff" * (512 * 1024)
            binary.write_bytes(data + b"old")
            self.assertEqual(digest(binary), hashlib.sha256(data + b"old").hexdigest())
            missing = binary.with_name("unavailable.exe")
            with patch.object(Path, "read_bytes", side_effect=AssertionError("buffered binary read")):
                self.assertEqual(binary_state([missing, binary], root=binary.parent),
                                 {binary.name: digest(binary), missing.name: "missing"})
            saved = binary.stat()
            with binary.open("r+b") as stream:
                stream.seek(len(data))
                stream.write(b"new")
            os.utime(binary, ns=(saved.st_atime_ns, saved.st_mtime_ns))
            self.assertEqual(digest(binary), hashlib.sha256(data + b"new").hexdigest())
            self.assertEqual(binary_state([binary], root=binary.parent), {binary.name: digest(binary)})

    def test_source_provenance_normalizes_crlf_across_chunks(self):
        from ourosmith import provenance

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "compiler/stage0/driver_u.c"
            source.parent.mkdir(parents=True)
            data = b"a" * (1024 * 1024 - 1) + b"\r\n\x00\xff\r\r\nend\r"
            source.write_bytes(data)
            name = source.relative_to(root).as_posix()
            hashes = {name: hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()}
            expected = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
            with (patch.object(provenance, "ROOT", root),
                  patch.object(provenance, "git", side_effect=[name + "\0", "fixture\n"]),
                  patch.object(Path, "read_bytes", side_effect=AssertionError("buffered source read"))):
                self.assertEqual(provenance.source_state(),
                                 {"head": "fixture", "source_sha256": expected, "files": 1})

    def test_generator_fingerprint_shares_imports_within_one_fingerprint(self):
        import frontend_regen
        import ourosmith

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = {"tests/compiler_smith_runner.ouro": b'import "shared.ouro";\r\n',
                     "tests/compiler_retained_tests.ouro": b'import "shared.ouro";\n',
                     "tests/shared.ouro": b"-- original\r\n",
                     "scripts/ourosmith/fixture.py": b"# generator\n",
                     "scripts/ouro_smith.py": b"# launcher\n",
                     "quality/smith/seeds.json": b"{}\r\n"}
            for name, data in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)

            def expected():
                data = b"".join(name.encode("utf-8") + b"\0" + files[name].replace(b"\r\n", b"\n") + b"\0"
                                for name in sorted(files))
                return hashlib.sha256(data).hexdigest()[:16]

            with (patch.object(ourosmith, "ROOT", root),
                  patch.object(ourosmith, "PACKAGE_DIR", root / "scripts/ourosmith"),
                  patch.object(frontend_regen, "ROOT", root),
                  patch.object(frontend_regen, "import_targets", wraps=frontend_regen.import_targets) as reads):
                first = ourosmith.generator_hash()
                self.assertEqual(first, expected())
                self.assertEqual([call.args[0] for call in reads.call_args_list].count("tests/shared.ouro"), 1)
                reads.reset_mock()
                shared = root / "tests/shared.ouro"
                metadata = shared.stat()
                files["tests/shared.ouro"] = b"-- modified\r\n"
                shared.write_bytes(files["tests/shared.ouro"])
                os.utime(shared, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
                second = ourosmith.generator_hash()
                self.assertEqual(second, expected())
                self.assertNotEqual(first, second)
                self.assertEqual([call.args[0] for call in reads.call_args_list].count("tests/shared.ouro"), 1)

    def test_import_parser_returns_the_compared_version_when_another_thread_updates_it(self):
        from native_tool_build import cached_import_parser

        comparing, updated = Event(), Event()

        # Pause a cache hit while another reader installs a different version.
        class PausedBytes(bytes):
            __hash__ = bytes.__hash__

            def __eq__(self, other):
                comparing.set()
                if not updated.wait(timeout=5):
                    raise AssertionError("import parser comparison timed out")
                return bytes.__eq__(self, other)

            def __ne__(self, other):
                return not self == other

        parse = cached_import_parser()
        entry = "tools/main.ouro"
        first = b'import "first.ouro";\n'
        second = b'import "second.ouro";\n'
        self.assertEqual(parse(first, entry), ["tools/first.ouro"])
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(parse, PausedBytes(first), entry)
            try:
                self.assertTrue(comparing.wait(timeout=5))
                self.assertEqual(parse(second, entry), ["tools/second.ouro"])
            finally:
                updated.set()
            self.assertEqual(pending.result(timeout=5), ["tools/first.ouro"])
        self.assertEqual(parse(second, entry), ["tools/second.ouro"])

    @contextlib.contextmanager
    def verification_fixture(self, entry):
        import frontend_regen
        import native_tool_build
        from ourosmith import native
        from repo_support import bind_relative_path

        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            target = root / entry
            dependency = target.with_name("dependency.ouro")
            target.parent.mkdir(parents=True)
            target.write_bytes(b'import "dependency.ouro";\n')
            dependency.write_bytes(b"def fixture : Nat := 0;\n")
            compiler, executable = root / "compiler", root / "executable"
            compiler.write_bytes(b"producer fixture")
            executable.write_bytes(b"program fixture")
            with (patch.object(native, "ROOT", root), patch.object(frontend_regen, "ROOT", root),
                  patch.object(frontend_regen, "rel", bind_relative_path(root, resolve=False)),
                  patch.object(native_tool_build, "BUILD_INPUTS", ()), patch.object(native_tool_build, "RUNTIME", ())):
                _, sources = source_inputs(entry)
                kind = "ouro.native-tool-build.v1"
                inputs = {"kind": kind, "entry": entry, "fuel": 16000, "compiler_sha256": digest(compiler),
                          "sources": sources, "cc": "fixture", "cc_sha256": "d" * 64, "platform": "fixture",
                          "machine": "fixture", "cflags": [], "link_flags": [], "environment": {}}
                receipt = {"kind": kind, "cache": "miss", "inputs": inputs,
                           "key": hash_json(inputs), "binary_sha256": digest(executable)}
                executable.with_suffix(".build.json").write_text(json.dumps(receipt), encoding="utf-8")

                def change_dependency():
                    before = dependency.stat()
                    dependency.write_bytes(b"def fixture : Nat := 1;\n")
                    os.utime(dependency, ns=(before.st_atime_ns, before.st_mtime_ns))
                    after = dependency.stat()
                    self.assertEqual((after.st_size, after.st_mtime_ns), (before.st_size, before.st_mtime_ns))

                with patch.object(frontend_regen.SMC, "quoted_import_targets",
                                  wraps=frontend_regen.SMC.quoted_import_targets) as parse:
                    yield root, compiler, executable, change_dependency, parse

    def test_smith_reuses_import_parse_and_detects_same_metadata_drift_during_run(self):
        from ourosmith import native
        from ourosmith.limits import RunResult

        result = RunResult("ok", 0, "CHECK_OK\n", "", 0, 0)
        with (self.verification_fixture(native.SMITH_ENTRY) as (root, compiler, executable, drift, parse),
              patch.object(native, "environment", return_value={}),
              patch.object(native, "run_limited", return_value=result) as run):
            program = native.prepare(native.SMITH_ENTRY, root / "work", compiler, memory_mb=100,
                                     executable=executable, log=lambda _line: None)
            self.assertEqual(program.run([], "first", 1), result)
            self.assertEqual(program.run([], "second", 1), result)
            self.assertEqual(parse.call_count, 2)

            def change_during_run(*_args, **_kwargs):
                drift()
                return result

            run.side_effect = change_during_run
            with self.assertRaisesRegex(ValueError, "changed during execution"):
                program.run([], "drift", 1)
            self.assertEqual(parse.call_count, 3)
            with self.assertRaisesRegex(ValueError, "changed before execution"):
                program.run([], "stale", 1)
            self.assertEqual(run.call_count, 4)

    def test_native_build_reuses_import_parse_and_rechecks_inputs(self):
        import native_tool_build as tool_build
        from ouro_build import DEFAULTS, ResolvedConfig
        from ourosmith import native

        entry = native.SMITH_ENTRY
        with self.verification_fixture(entry) as (root, compiler, executable, drift, parse):
            output = executable.rename(executable.with_suffix(".exe")) if os.name == "nt" else executable
            args = argparse.Namespace(entry=entry, compiler=compiler, output=output, check=False, fuel=16000)
            cfg = ResolvedConfig({**DEFAULTS, "cache_enabled": True, "cache_dir": str(root / "cache")}, {})
            (root / (output.name + ".sources")).write_text(
                f"tests/dependency.ouro\n{entry}\n", encoding="utf-8")
            with (patch.object(tool_build, "ROOT", root),
                  patch.object(tool_build.frontend, "ouro1_usable", return_value=True),
                  patch.object(tool_build.build, "load_config", return_value=cfg),
                  patch.object(tool_build.build, "locate_cc", return_value=(str(compiler), None)),
                  patch.object(tool_build.build, "compiler_id", return_value="fixture"),
                  patch.object(tool_build, "complete_tool",
                               return_value={"binary_sha256": digest(output)}) as installed,
                  contextlib.redirect_stdout(io.StringIO())):
                report = tool_build.build_tool(args)
                self.assertEqual(report["cache"], "installed-hit")
                self.assertEqual(parse.call_count, 2)

                def change_after_capture(*_args, **_kwargs):
                    drift()
                    return {"binary_sha256": digest(output)}

                installed.side_effect = change_after_capture
                with self.assertRaisesRegex(ValueError, "changed before completion"):
                    tool_build.build_tool(args)
                self.assertEqual(parse.call_count, 5)

    def test_analyzer_provider_reuses_import_parse_and_detects_same_metadata_drift(self):
        import analyze_bounded
        from ourosmith import limits

        entry = "tools/analyze/bounded_report_main.ouro"
        output = "ANALYZE_DRIVE files=1 findings=0 rejected=0 families=effects\n"
        proc = CompletedProcess([], 0, output, "")
        response = {"kind": "ouro.analyze-bounded-report-response.v1", "families": None, "error": "",
                    "banner": {"files": "1", "findings": "0", "rejected": "0", "families": "effects"}}
        result = limits.RunResult("ok", 0, json.dumps(response), "", 0, 0)
        with (self.verification_fixture(entry) as (root, compiler, executable, drift, parse),
              patch.object(analyze_bounded, "ROOT", root), patch.object(analyze_bounded, "_DRIVE_REPORT_CACHE", {}),
              patch.object(host, "prepare_entry", return_value=executable) as prepare,
              patch.object(host, "compiler_path", return_value=compiler),
              patch.object(limits, "run_limited", return_value=result) as run):
            self.assertEqual(analyze_bounded.drive_result_error(proc), "")
            self.assertEqual(analyze_bounded.drive_result_error(proc), "")
            self.assertEqual(parse.call_count, 2)
            prepare.assert_called_once_with(entry, "ouro-analyze-report")

            def change_during_run(*_args, **_kwargs):
                drift()
                return result

            run.side_effect = change_during_run
            self.assertIn("receipt is missing, incomplete, or stale", analyze_bounded.drive_result_error(proc))
            self.assertEqual(parse.call_count, 3)
            self.assertIn("receipt is missing, incomplete, or stale", analyze_bounded.drive_result_error(proc))
            self.assertEqual(run.call_count, 3)

    def test_source_inputs_read_each_dependency_once_and_recheck_bytes(self):
        import frontend_regen
        import native_tool_build
        from ourosmith import native
        from repo_support import bind_relative_path

        entry = "tools/lint.ouro"
        shared = "tools/shared.ouro"
        inputs = {
            entry: b'import "extra.ouro", "shared.ouro";\n',
            "tools/extra.ouro": b'import "shared.ouro";\n',
            shared: b"def shared_value : Nat := 0;\r\n",
            "tools/lint_style.ouro": b'import "shared.ouro";\n',
            "tools/clippy/main.ouro": b'import "../shared.ouro";\n',
            "tools/clippy/structural_main.ouro": b'import "../shared.ouro";\n',
            "scripts/helper.py": b"# Build helper\n",
            "runtime/fixture.c": b'#include "fixture.h"\n',
            "runtime/fixture.h": b"#define FIXTURE 1\n",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for name, contents in inputs.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(contents)
            reads = []
            open_path = Path.open

            def record_open(path, mode="r", *args, **kwargs):
                if mode == "rb":
                    reads.append(path.relative_to(root).as_posix())
                return open_path(path, mode, *args, **kwargs)

            with (patch.object(native, "ROOT", root), patch.object(frontend_regen, "ROOT", root),
                  patch.object(frontend_regen, "rel", bind_relative_path(root, resolve=False)),
                  patch.object(native_tool_build, "BUILD_INPUTS", ("scripts/helper.py", shared)),
                  patch.object(native_tool_build, "RUNTIME", ("runtime/fixture.c",)),
                  patch.object(Path, "open", record_open)):
                units, sources = source_inputs(entry)
                self.assertEqual(units, [shared, "tools/extra.ouro", entry])
                self.assertEqual(sources, {name: hashlib.sha256(data).hexdigest() for name, data in inputs.items()})
                self.assertCountEqual(reads, list(inputs))

                path = root / shared
                before = path.stat()
                updated = inputs[shared].replace(b":= 0;", b":= 1;")
                path.write_bytes(updated)
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
                after = path.stat()
                self.assertEqual((after.st_size, after.st_mtime_ns), (before.st_size, before.st_mtime_ns))
                reads.clear()

                self.assertEqual(source_inputs(entry), (units, {**sources, shared: hashlib.sha256(updated).hexdigest()}))
                self.assertCountEqual(reads, list(inputs))

    @contextlib.contextmanager
    def surface_native_fixture(self):
        import ouro_build as build
        from build_cache_config_suite import write_fake_cc
        from ourosmith.surface import native_compile
        from repo_support import bind_relative_path

        work = ROOT / "_build/smith/selftest"
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as name:
            directory = Path(name)
            runtime = directory / "runtime"
            runtime.mkdir()
            (runtime / "ouro_rt.h").write_text("#define SURFACE_VALUE 1\n", encoding="utf-8")
            for source in ("ouro_rt.c", "ouro_io.c", "ouro_eval_main.c", "ouro_prog_main.c"):
                (runtime / source).write_text('#include "ouro_rt.h"\n', encoding="utf-8")
            generated = directory / "sample.c"
            generated.write_text("int sample(void) { return 1; }\n", encoding="utf-8")
            compiler = directory / "fake-cc.py"
            write_fake_cc(compiler)
            log = directory / "cc.log"
            args = argparse.Namespace(
                generated=generated, main=runtime / "ouro_eval_main.c", output=directory / "sample.exe",
                object_dir=directory / "objects", report=directory / "native-build.json",
                cc=str(compiler), cache=True)
            with patch.object(build, "ROOT", directory), patch.object(native_compile, "ROOT", directory), \
                 patch.object(build, "rel", bind_relative_path(directory, resolve=False)), \
                 patch.dict(os.environ, {"FAKE_CC_LOG": str(log)}):
                yield native_compile, args, log

    def test_surface_runtime_cache_keeps_every_generated_compile(self):
        import shutil
        import subprocess

        with self.surface_native_fixture() as (native, args, log), \
             patch.object(native.subprocess, "run", wraps=subprocess.run) as execute, \
             patch.object(shutil, "which", return_value=args.cc) as discover:
            cold = native.build_native(args)
            args.generated.write_text("int sample(void) { return 2; }\n", encoding="utf-8")
            warm = native.build_native(args)
            self.assertEqual([row["cache"] for row in cold["runtime"]], ["miss"] * 3)
            self.assertEqual([row["cache"] for row in warm["runtime"]], ["hit"] * 3)
            self.assertEqual([call.args for call in discover.call_args_list], [(args.cc,)] * 2)
            self.assertEqual(cold["compiler_id"], warm["compiler_id"])
            self.assertNotEqual(cold["inputs"][str(args.generated)], warm["inputs"][str(args.generated)])
            links = [call.args[0] for call in execute.call_args_list if "-o" in call.args[0] and "-c" not in call.args[0]]
            self.assertEqual(len(links), 2)
            for command in links:
                self.assertIn(str(args.generated), command)
                self.assertIn("-O1", command)
                self.assertIn("-Werror=implicit-function-declaration", command)
                self.assertNotIn(str(args.main), command)
                self.assertEqual([arg for arg in command if arg.startswith("-Wl,--stack,")],
                                 ["-Wl,--stack,134217728"] if os.name == "nt" else [])
            self.assertEqual(log.read_text(encoding="utf-8").count("COMPILE "), 3)
            self.assertEqual(log.read_text(encoding="utf-8").count("LINK "), 2)

    def test_surface_runtime_cache_rechecks_sources_headers_objects_and_compiler(self):
        with self.surface_native_fixture() as (native, args, _log):
            native.build_native(args)
            runtime = args.main.parent
            with (runtime / "ouro_rt.c").open("a", encoding="utf-8") as source:
                source.write("/* changed source */\n")
            changed = native.build_native(args)
            self.assertEqual([row["cache"] for row in changed["runtime"]], ["miss", "hit", "hit"])
            (runtime / "ouro_rt.h").write_text("#define SURFACE_VALUE 2\n", encoding="utf-8")
            changed = native.build_native(args)
            self.assertEqual([row["cache"] for row in changed["runtime"]], ["miss"] * 3)
            directory = args.generated.parent
            for field in ("object", "depfile", "cmdhash"):
                path = directory / changed["runtime"][0][field]
                path.write_text("corrupt\n", encoding="utf-8")
                changed = native.build_native(args)
                self.assertEqual([row["cache"] for row in changed["runtime"]], ["miss", "hit", "hit"], field)
            identity = changed["compiler_id"]
            with Path(args.cc).open("a", encoding="utf-8") as compiler:
                compiler.write("\n# same version, different compiler bytes\n")
            changed = native.build_native(args)
            self.assertEqual(changed["compiler_id"]["version"], identity["version"])
            self.assertNotEqual(changed["compiler_id"]["executable_sha256"], identity["executable_sha256"])
            self.assertEqual([row["cache"] for row in changed["runtime"]], ["miss"] * 3)

    def test_surface_runtime_cache_distinguishes_mains_and_disabled_invocations(self):
        with self.surface_native_fixture() as (native, args, _log):
            native.build_native(args)
            args.main = args.main.with_name("ouro_prog_main.c")
            io = native.build_native(args)
            self.assertEqual([row["cache"] for row in io["runtime"]], ["hit", "hit", "miss"])
            args.main = args.main.with_name("mutant_main.c")
            args.main.write_text('#include "ouro_rt.h"\n/* alternate printer */\n', encoding="utf-8")
            mutant = native.build_native(args)
            self.assertEqual([row["cache"] for row in mutant["runtime"]], ["hit", "hit", "miss"])
            args.cache = False
            first = native.build_native(args)
            second = native.build_native(args)
            self.assertEqual([row["cache"] for row in first["runtime"]], ["miss"] * 3)
            self.assertEqual([row["cache"] for row in second["runtime"]], ["miss"] * 3)
            self.assertNotEqual(first["runtime"][0]["object"], second["runtime"][0]["object"])

    def test_surface_runtime_compile_rejects_compiler_change_during_link(self):
        with self.surface_native_fixture() as (native, args, _log):
            original = native.subprocess.run

            def change_compiler(argv, **options):
                result = original(argv, **options)
                if "-o" in argv and "-c" not in argv:
                    with Path(args.cc).open("a", encoding="utf-8") as compiler:
                        compiler.write("\n# changed during linking\n")
                return result

            with patch.object(native.subprocess, "run", side_effect=change_compiler), \
                 self.assertRaisesRegex(ValueError, "input changed during compilation"):
                native.build_native(args)
            self.assertFalse(args.report.exists())

    def test_surface_native_child_keeps_limits_and_disabled_cache(self):
        import sys
        from ourosmith.limits import RunResult
        from ourosmith.report import Report
        from ourosmith.surface.run import StepFailure, SurfaceRunner

        with self.fixture() as fixture, \
             patch("ourosmith.surface.run.environment", return_value={}), \
             patch.object(host, "build_config", return_value=SimpleNamespace(get_bool=lambda _key: False)), \
             patch("ourosmith.surface.run.run_limited", return_value=RunResult("ok", 0, "", "", 0, 0)) as execute:
            report = Report(profile="pr", generator_hash="fixture", seeds=[1], command="native-child")
            runner = SurfaceRunner(report, fixture.directory / "surface", [1], timeout=20, memory_mb=2048,
                                   overrides=fixture.tools)
            runner.cc = "cc"
            runner.native(fixture.directory / "sample.ouro", compile_timeout=900)
            self.assertEqual([call.kwargs["timeout_s"] for call in execute.call_args_list], [900, 900, 20])
            self.assertTrue(all(call.kwargs["memory_mb"] == 2048 for call in execute.call_args_list))
            command = execute.call_args_list[1].args[0]
            self.assertEqual(command[0], sys.executable)
            self.assertIn("--no-cache", command)
            self.assertEqual(command[command.index("--object-dir") + 1], runner.native_work.as_posix())
            execute.reset_mock()
            execute.side_effect = [RunResult("ok", 0, "", "", 0, 0), RunResult("timeout", 1, "", "timeout", 21, 0)]
            with self.assertRaises(StepFailure) as failure:
                runner.native(fixture.directory / "sample.ouro")
            self.assertEqual((failure.exception.prop, failure.exception.classification), ("native-compile", "timeout"))
            self.assertEqual(execute.call_count, 2)
            self.assertTrue(all(call.kwargs["timeout_s"] == 20 for call in execute.call_args_list))

    @contextlib.contextmanager
    def fixture(self):
        work = ROOT / "_build/smith/selftest"
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as name:
            directory = Path(name)
            compiler = directory / ("ouro1.exe" if os.name == "nt" else "ouro1")
            compiler.write_bytes(b"producer fixture\n" * 400)
            tools = {"ouro1": compiler}

            def installed(tool, path, entry=None, *, companions=True):
                from native_tool_build import tool_companions

                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((tool + " binary fixture\n").encode() * 400)
                entry = host.tool_entry(tool) if entry is None else entry
                for companion in tool_companions(entry):
                    companion_path = path.parent / (companion[1] + (".exe" if os.name == "nt" else ""))
                    if companions:
                        installed(companion[1], companion_path, companion[0])
                    else:
                        self.assertTrue(companion_path.exists(), str(companion_path))
                _units, sources = source_inputs(entry)
                inputs = {"kind": "ouro.native-tool-build.v1", "entry": entry, "fuel": 16000,
                          "compiler_sha256": digest(compiler), "sources": sources, "cc": "fixture",
                          "cc_sha256": "d" * 64, "platform": "fixture", "machine": "fixture",
                          "cflags": [], "link_flags": [], "environment": {}}
                data = {"kind": "ouro.native-tool-build.v1", "cache": "miss", "inputs": inputs,
                        "key": hash_json(inputs), "binary_sha256": digest(path)}
                Path(str(path) + ".build.json").write_text(json.dumps(data), encoding="utf-8")
                return data

            for tool in host.TOOLS:
                path = directory / ("ouro-" + tool + ".exe")
                installed(tool, path)
                tools["ouro-" + tool] = path
            yield SimpleNamespace(directory=directory, compiler=compiler, tools=tools, installed=installed)

    def test_configured_default_is_selected_once_and_producer_drift_rejects(self):
        import ouro_smith

        with self.fixture() as fixture:
            config = SimpleNamespace(path=lambda _key: fixture.directory)
            args = argparse.Namespace(compiler=None)
            with patch.object(host, "build_config", return_value=config), \
                 patch.object(host, "ensure_compiler", side_effect=AssertionError("fixture must not bootstrap a compiler")):
                self.assertEqual(ouro_smith.compiler_for(args), fixture.compiler)
                config.path = lambda _key: fixture.directory / "changed-default"
                self.assertEqual(ouro_smith.compiler_for(args), fixture.compiler)
                explicit = argparse.Namespace(compiler=str(fixture.compiler))
                self.assertEqual(ouro_smith.compiler_for(explicit), fixture.compiler)
                fixture.compiler.write_bytes(b"changed producer\n" * 400)
                with self.assertRaisesRegex(ValueError, "changed"):
                    ouro_smith.compiler_for(args)

    def test_complete_receipts_reject_foreign_incomplete_or_rehashed_toolchains(self):
        with self.fixture() as fixture:
            evidence = host.toolchain_evidence(fixture.compiler, fixture.tools)
            self.assertEqual(host.toolchain_paths(evidence, compiler=fixture.compiler), fixture.tools)
            invalid = []
            for key in ("compiler_sha256", "kind"):
                changed = copy.deepcopy(evidence)
                changed[key] = "wrong"
                invalid.append(changed)
            changed = copy.deepcopy(evidence)
            del changed["tools"]["collect"]
            invalid.append(changed)
            for key, value in (("entry", "tools/wrong.ouro"), ("binary", "../outside.exe"), ("build_key", "0" * 64)):
                changed = copy.deepcopy(evidence)
                changed["tools"]["fmt"][key] = value
                invalid.append(changed)
            for changed in invalid:
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    host.toolchain_paths(changed, compiler=fixture.compiler)
            receipt = Path(str(fixture.tools["ouro-fmt"]) + ".build.json")
            saved = json.loads(receipt.read_text(encoding="utf-8"))
            saved["inputs"]["sources"].pop("scripts/native_tool_build.py")
            saved["key"] = hash_json(saved["inputs"])
            receipt.write_text(json.dumps(saved), encoding="utf-8")
            evidence["tools"]["fmt"]["build_key"] = saved["key"]
            with self.assertRaisesRegex(ValueError, "receipt"):
                host.toolchain_paths(evidence, compiler=fixture.compiler)

    def test_missing_or_changed_companion_rejects_complete_parent_receipt(self):
        names = ("ouro-fix-check", "ouro-lint-style", "ouro-clippy-grade-firewall", "ouro-clippy-structural")
        for name, mutation in itertools.product(names, ("missing-binary", "missing-receipt", "changed-binary")):
            with self.subTest(name=name, mutation=mutation), self.fixture() as fixture:
                evidence = host.toolchain_evidence(fixture.compiler, fixture.tools)
                companion = fixture.directory / (name + (".exe" if os.name == "nt" else ""))
                if mutation == "missing-binary":
                    companion.unlink()
                elif mutation == "missing-receipt":
                    Path(str(companion) + ".build.json").unlink()
                else:
                    companion.write_bytes(b"changed companion\n" * 400)
                with self.assertRaisesRegex(ValueError, "receipt"):
                    host.toolchain_paths(evidence, compiler=fixture.compiler)

    def test_tool_builds_use_explicit_producer_and_stable_scoped_paths(self):
        import ouro_build

        with self.fixture() as fixture:
            calls = []
            scheduled = host.scheduled_tool_builds()
            barrier = Barrier(sum(not task.dependencies for task, _, _ in scheduled), timeout=10)

            def build(command, log, **kwargs):
                self.assertEqual(Path(command[2]), ROOT / "scripts/native_tool_build.py")
                self.assertEqual(command[command.index("--compiler") + 1], str(fixture.compiler))
                allocation = kwargs["allocation"]
                self.assertEqual(command[command.index("--jobs") + 1], str(allocation.jobs))
                self.assertEqual(kwargs["timeout_s"], host.BUILD_TIMEOUT_S)
                target = Path(command[4] + (".exe" if os.name == "nt" else ""))
                self.assertTrue(target.is_relative_to(fixture.directory / "smith-tools"))
                entry = command[3]
                (task, name, _log_stem), = [item for item in scheduled if item[0].name == entry]
                calls.append((target, log, command[command.index("--build-dir") + 1]))
                if log.parent.name.startswith("failure-"):
                    return "injected companion failure" if name == "ouro-fix-check" else None
                if log.parent.name == "parallel" and not task.dependencies:
                    barrier.wait()
                fixture.installed(name, target, task.name, companions=False)
                return None

            cfg = ouro_build.ResolvedConfig(
                dict(ouro_build.DEFAULTS, build_dir=fixture.directory, cache_dir=fixture.directory / "cache"), {})
            with patch.object(host, "build_config", return_value=cfg), \
                 patch.object(host, "job_count", side_effect=(1, 20, 1, 20)), \
                 patch.object(host, "available_memory_mib", return_value=32768), \
                 patch.object(host, "build_command", side_effect=build):
                first = host.prepare_tools(fixture.directory / "first", fixture.compiler)
                second = host.prepare_tools(fixture.directory / "parallel", fixture.compiler)
                for workers in (1, 20):
                    with self.assertRaisesRegex(ValueError, "ouro-fix-check: injected companion failure"):
                        host.prepare_tools(fixture.directory / f"failure-{workers}", fixture.compiler)
            self.assertEqual(first, second)
            self.assertGreater(len(scheduled), len(host.TOOLS))
            for phase, workers in (("first", 1), ("parallel", 20)):
                report = json.loads((fixture.directory / phase / "tool-schedule.json").read_text(encoding="utf-8"))
                self.assertEqual([row["entry"] for row in report["builds"]], [task.name for task, _, _ in scheduled])
                self.assertEqual(report["peak_jobs"], workers)
                self.assertEqual(report["not_run"], [])
                self.assertEqual(len({work for _, log, work in calls if log.parent.name == phase}), len(scheduled))
            blocked = {"tools/fmt.ouro", "tools/fix/main.ouro"}
            expected = [task.name for task, _, _ in scheduled if task.name not in blocked]
            for workers in (1, 20):
                report = json.loads((fixture.directory / f"failure-{workers}/tool-schedule.json").read_text(encoding="utf-8"))
                self.assertEqual([row["entry"] for row in report["builds"]], expected)
                self.assertEqual(set(report["not_run"]), blocked)

    def test_invalid_explicit_producer_precedes_any_execution_or_tool_build(self):
        import ouro_smith

        with self.fixture() as fixture, patch.object(ouro_smith, "prepare") as native, \
             patch.object(ouro_smith, "prepare_tools") as surface, \
             patch.object(ouro_smith, "run_faults") as faults, \
             patch.object(ouro_smith, "load_cases", return_value=[]), \
             contextlib.redirect_stderr(io.StringIO()):
            out = fixture.directory / "run"
            out.mkdir()
            report = out / "report.json"
            previous = '{"kind": "ouro.smith-report.v1", "pass": true}\n'
            log = out / "gate.log"
            log.write_text("previous run\n", encoding="utf-8")
            for command in (["run", "--seeds", "1", "--no-inventory"], ["replay", "--layer", "surface", "--seed", "1"],
                            ["replay", "--layer", "kernel", "--seed", "1"], ["corpus"], ["faults"]):
                with self.subTest(command=command):
                    report.write_text(previous, encoding="utf-8")
                    self.assertEqual(ouro_smith.main([*command, "--compiler", str(fixture.directory / "missing"),
                                                      "--out", str(out)]), 1)
                    if command[0] == "run":
                        self.assertFalse(report.exists())
                    else:
                        self.assertEqual(report.read_text(encoding="utf-8"), previous)
                    self.assertEqual(log.read_text(encoding="utf-8"), "previous run\n")
            native.assert_not_called()
            surface.assert_not_called()
            faults.assert_not_called()

    def test_hosted_recipes_use_prepared_helpers_with_runtime_limits(self):
        from ourosmith.surface import manifest, tools
        from ourosmith.surface.run import SurfaceRunner
        from ourosmith.report import Report

        class CapturedCommand(Exception):
            pass

        with self.fixture() as fixture:
            evidence = host.toolchain_evidence(fixture.compiler, fixture.tools)
            selected = host.toolchain_paths(evidence, compiler=fixture.compiler)
            cold = fixture.directory / "cold"
            value = Report(profile="nightly", generator_hash="selftest", seeds=[100000], command="helpers")
            with patch.dict(os.environ, {"OURO1_COMPILER": "untrusted-wrapper", "SMITH_UNRELATED_ENV": "sentinel"}), \
                 patch.object(host, "build_config", return_value=SimpleNamespace(path=lambda _key: cold)), \
                 patch.object(host, "shell", return_value=Path(__file__)):
                runner = SurfaceRunner(value, fixture.directory / "recipes", [100000],
                                       timeout=20, memory_mb=2048, overrides=selected)
            runner.seed = 100000
            self.assertFalse(cold.exists())
            self.assertNotIn("SMITH_UNRELATED_ENV", runner.env)
            with patch("ourosmith.surface.run.run_limited", side_effect=CapturedCommand) as execute:
                for recipe, name in ((tools.language_server, "ouro-lsp"), (manifest.run_checks, "ouro-test")):
                    directory = fixture.directory / name
                    directory.mkdir()
                    with self.subTest(recipe=recipe.__name__), self.assertRaises(CapturedCommand):
                        recipe(runner, directory)
                    argv = execute.call_args.args[0]
                    options = execute.call_args.kwargs
                    self.assertEqual(argv[0], selected[name].as_posix())
                    self.assertEqual(options["env"]["OURO1_COMPILER"], fixture.compiler.as_posix())
                    self.assertEqual(options["env"]["OURO_C_BUILD_DIR"], selected["ouro-collect"].parent.as_posix())
                    self.assertEqual(options["env"]["OURO_HOSTED_FMT"], selected["ouro-fmt"].as_posix())
                    self.assertEqual(options["timeout_s"], 20)
                    self.assertEqual(options["memory_mb"], 2048)
                    self.assertEqual(options["cwd"], directory)
                    self.assertEqual(bool(options["stdin_text"]), name == "ouro-lsp")
            self.assertEqual(execute.call_count, 2)
            self.assertEqual(host.toolchain_evidence(fixture.compiler, fixture.tools), evidence)

    def test_helper_bindings_keep_partial_and_mutant_overrides(self):
        from ourosmith.surface.run import SurfaceRunner
        from ourosmith.report import Report

        with self.fixture() as fixture:
            default_env = {"OURO_C_BUILD_DIR": "configured-tools", "OURO_HOSTED_FMT": "configured-fmt"}
            value = Report(profile="faults", generator_hash="selftest", seeds=[1], command="overrides")
            with patch("ourosmith.surface.run.environment", return_value=default_env):
                partial = SurfaceRunner(value, fixture.directory, [1], overrides={"ouro1": fixture.compiler})
                changed_compiler = fixture.directory / "mutant" / "ouro1.exe"
                changed_fmt = fixture.directory / "mutant" / "ouro-fmt.exe"
                overrides = {**fixture.tools, "ouro1": changed_compiler, "ouro-fmt": changed_fmt}
                mutant = SurfaceRunner(value, fixture.directory, [1], overrides=overrides)
            self.assertEqual(partial.env["OURO1_COMPILER"], fixture.compiler.as_posix())
            self.assertEqual(partial.env["OURO_C_BUILD_DIR"], "configured-tools")
            self.assertEqual(partial.env["OURO_HOSTED_FMT"], "configured-fmt")
            self.assertEqual(mutant.env["OURO1_COMPILER"], changed_compiler.as_posix())
            self.assertEqual(mutant.env["OURO_C_BUILD_DIR"], fixture.tools["ouro-collect"].parent.as_posix())
            self.assertEqual(mutant.env["OURO_HOSTED_FMT"], changed_fmt.as_posix())
            self.assertEqual(mutant.overrides, overrides)
            self.assertEqual(default_env, {"OURO_C_BUILD_DIR": "configured-tools", "OURO_HOSTED_FMT": "configured-fmt"})

    def test_collector_receipt_rejects_missing_or_changed_prepared_helper(self):
        for mutation in ("missing-receipt", "changed-binary", "stale-source"):
            with self.subTest(mutation=mutation), self.fixture() as fixture:
                evidence = host.toolchain_evidence(fixture.compiler, fixture.tools)
                collector = fixture.tools["ouro-collect"]
                receipt = Path(str(collector) + ".build.json")
                if mutation == "missing-receipt":
                    receipt.unlink()
                elif mutation == "changed-binary":
                    collector.write_bytes(b"changed collector\n" * 400)
                else:
                    saved = json.loads(receipt.read_text(encoding="utf-8"))
                    saved["inputs"]["sources"]["tools/collect.ouro"] = "0" * 64
                    saved["key"] = hash_json(saved["inputs"])
                    receipt.write_text(json.dumps(saved), encoding="utf-8")
                    evidence["tools"]["collect"]["build_key"] = saved["key"]
                with self.assertRaisesRegex(ValueError, "receipt"):
                    host.toolchain_paths(evidence, compiler=fixture.compiler)

    def test_cli_uses_one_producer_for_core_retained_surface_replay_and_faults(self):
        import ouro_smith

        with self.fixture() as fixture:
            campaign = {"pass": True, "catalogue_problems": [], "baseline": {"clean": True}, "timing_s": {"total": 0},
                        "summary": dict(faults=0, killed=0, survived=0, stale=0, unbuildable=0)}
            with patch.object(ouro_smith, "prepare", return_value=object()) as native, \
                 patch.object(ouro_smith, "bind"), patch.object(ouro_smith, "CoreRunner"), \
                 patch.object(ouro_smith, "run_corpus"), patch.object(ouro_smith, "load_cases", return_value=[]), \
                 patch.object(ouro_smith, "finish_report", return_value=0), \
                 patch.object(ouro_smith, "prepare_tools", return_value=(fixture.tools, {"fixture": True})) as tools, \
                 patch.object(ouro_smith, "run_faults", return_value=campaign) as faults, \
                 patch("ourosmith.surface.run.SurfaceRunner") as surface, \
                 patch("ourosmith.provenance.begin", side_effect=lambda: {"source": {}, "binaries": {}}), \
                 contextlib.redirect_stdout(io.StringIO()):
                for index, command in enumerate((["run", "--seeds", "1", "--no-inventory"],
                        ["replay", "--layer", "surface", "--seed", "1"], ["replay", "--layer", "kernel", "--seed", "1"], ["corpus"], ["faults"])):
                    self.assertEqual(ouro_smith.main([*command, "--compiler", str(fixture.compiler),
                                                     "--out", str(fixture.directory / str(index))]), 0)
                self.assertEqual(native.call_count, 4)
                self.assertTrue(all(call.args[2] == fixture.compiler for call in native.call_args_list))
                self.assertEqual(tools.call_count, 2)
                self.assertTrue(all(call.args[1] == fixture.compiler for call in tools.call_args_list))
                self.assertTrue(all(call.kwargs["overrides"] == fixture.tools for call in surface.call_args_list))
                self.assertEqual(faults.call_args.kwargs["compiler"], fixture.compiler)

    def test_runtime_io_seed_replay_uses_only_the_selected_producer(self):
        import ouro_smith
        from ourosmith.evidence import profile_problems
        from ourosmith.surface import io as runtime_io
        from ourosmith.surface.run import StepFailure

        work = ROOT / "_build/smith/selftest"
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as scratch:
            directory = Path(scratch)
            compiler = directory / "ouro1"
            compiler.write_bytes(b"producer fixture\n" * 400)
            case = "surface-17-runtime_io"
            argv = ["replay", "--layer", "surface", "--seed", "17", "--case", case,
                    "--compiler", str(compiler), "--out", str(directory)]
            with patch("ourosmith.provenance.source_state", return_value={}), \
                 patch("ourosmith.surface.run.environment", return_value={}), \
                 patch.object(ouro_smith, "prepare_tools") as prepare, \
                 patch.object(runtime_io, "run_checks") as execute, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(ouro_smith.main(argv), 0)
                execute.assert_called_once()
                runner, case_dir = execute.call_args.args
                self.assertEqual((runner.seed, runner.case_id, case_dir.name), (17, case, case))
                self.assertEqual(runner.overrides, {"ouro1": compiler})
                with self.assertRaises(StepFailure) as unbound:
                    runner.tool("ouro-fmt")
                self.assertEqual(unbound.exception.classification, "oracle-unavailable")
                report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
                sections = report["sections"]
                self.assertEqual(sections["provenance"]["binaries"], {compiler.relative_to(ROOT).as_posix(): digest(compiler)})
                self.assertNotIn("surface_toolchain", sections)
                self.assertIn("required tested binary set is incomplete or unavailable", profile_problems(report, "pr", {}))

                execute.side_effect = lambda *_args: compiler.write_bytes(b"changed producer\n" * 400)
                self.assertEqual(ouro_smith.main(argv), 1)
                report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
                self.assertEqual([item["what"] for item in report["skips"]], ["provenance:binaries"])
                prepare.assert_not_called()

                saved = directory / "saved.json"
                saved.write_text(json.dumps({"layer": "surface", "case_id": case, "seed": 17,
                                             "minimal_input": {"recipe": "runtime_io"}}), encoding="utf-8")
                prepare.side_effect = ValueError("full toolchain fixture")
                self.assertEqual(ouro_smith.main([*argv, "--finding", str(saved)]), 1)
                prepare.assert_called_once_with(directory / "build", compiler)

    def test_runtime_io_seed_replay_requires_check_ok_before_emission(self):
        from ourosmith.limits import RunResult
        from ourosmith.report import Report
        from ourosmith.surface import io as runtime_io
        from ourosmith.surface.run import StepFailure, SurfaceRunner

        emitted_c = "/* checked source */\n"
        ok = RunResult("ok", 0, "", "", 0, 0)
        emitted = RunResult("ok", 0, emitted_c, "ouro1: compiled ok\n", 0, 0)
        runtime = RunResult("ok", 0, "clock=1\n", "", 0, 0)
        cases = (
            ("checked", RunResult("ok", 0, "CHECK_OK\n", "", 0, 0), True),
            ("missing-verdict", RunResult("ok", 0, "", "ouro1: compiled ok\n", 0, 0), False),
            ("rejected", RunResult("ok", 1, "", "CHECK_FAIL\n", 0, 0), False),
            ("rejected-with-verdict", RunResult("ok", 1, "CHECK_OK\n", "", 0, 0), False),
        )
        work = ROOT / "_build/smith/selftest"
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as scratch, \
             patch("ourosmith.surface.run.environment", return_value={}), \
             patch("ourosmith.surface.run.available_memory_mib", return_value=None), \
             patch.object(host, "build_config", return_value=SimpleNamespace(get_bool=lambda _key: False)), \
             patch.object(runtime_io, "program", return_value=("body\n", {"clock": None}, {})), \
             patch.object(runtime_io.time, "time_ns", return_value=1000000):
            compiler = Path(scratch) / "ouro1"
            dependency = ROOT / "std/workspace.ouro"
            for name, verdict, accepted in cases:
                with self.subTest(case=name):
                    directory = Path(scratch) / name
                    directory.mkdir()
                    source = directory / "main.ouro"
                    units = [dependency.as_posix(), source.as_posix()]
                    report = Report(profile="pr", generator_hash="fixture", seeds=[1], command="runtime-io")
                    runner = SurfaceRunner(report, directory / "surface", [1], overrides={"ouro1": compiler},
                                           bound_tools_only=True)
                    runner.cc = "cc"
                    binary = source.with_suffix(".exe").as_posix()

                    def run_command(argv, *, check_result=verdict, runtime_path=binary, **_options):
                        if argv[0] == compiler.as_posix():
                            return check_result if argv[1] == "check" else emitted
                        if argv[0] == runtime_path:
                            return runtime
                        return ok

                    with patch("frontend_regen.collect_units", return_value=units), \
                         patch("ourosmith.surface.run.run_limited", side_effect=run_command) as execute:
                        if accepted:
                            runtime_io.run_checks(runner, directory)
                            self.assertEqual(source.with_suffix(".c").read_text(encoding="utf-8"), emitted_c)
                            self.assertIn("--no-cache", execute.call_args_list[-2].args[0])
                        else:
                            with self.assertRaises(StepFailure) as error:
                                runtime_io.run_checks(runner, directory)
                            self.assertEqual((error.exception.prop, error.exception.classification),
                                             ("accepts-typed-source", "wrong-reject"))
                            self.assertEqual(error.exception.actual["exit_code"], verdict.returncode)
                            self.assertFalse(source.with_suffix(".c").exists())
                    self.assertEqual(runner.coverage["properties"]["accepts-typed-source"], 1)
                    self.assertEqual(execute.call_count, 5 if accepted else 2)
                    phases = ["check", "emit"] if accepted else ["check"]
                    for call, phase in zip(execute.call_args_list[1:1 + len(phases)], phases, strict=True):
                        mode = ["check"] if phase == "check" else []
                        args = [compiler.as_posix(), *mode, source.as_posix(), "999999",
                                "--unit", units[0], "--unit", units[1]]
                        env = {**runner.env, "OURO_EMIT_IO_SHIMS": "1"} if phase == "emit" else runner.env
                        self.assertEqual(call.args[0], args)
                        self.assertEqual(call.kwargs["env"], env)
                        self.assertEqual(call.kwargs["cwd"], directory)

    def test_fault_baseline_and_mutant_keep_the_selected_remaining_tools(self):
        from ourosmith.faults import FAULTS
        from ourosmith.report import Report
        from ourosmith.surface_faults import run_surface_fault

        with self.fixture() as fixture:
            fault = next(value for value in FAULTS if value.target == "fmt")
            report = Report(profile="pr", generator_hash="fixture", seeds=[1], command="fixture")
            report.layer("surface").cases = 1
            changed = {"ouro-fmt": fixture.directory / "mutant.exe"}
            with patch("ourosmith.surface_faults.probe", return_value=report) as probe, \
                 patch("ourosmith.surface_faults.build_mutant", return_value=changed) as build, \
                 patch("ourosmith.faults.remove_scratch"), patch.object(Report, "write"):
                run_surface_fault(fault, fixture.directory, timeout_s=1, memory_mb=64, overrides=fixture.tools)
            self.assertEqual(probe.call_args_list[0].kwargs["overrides"], fixture.tools)
            self.assertEqual(probe.call_args_list[1].kwargs["overrides"], {**fixture.tools, **changed})
            self.assertEqual(build.call_args.args[2], fixture.compiler)

    def test_frontend_mutant_regenerates_both_halves_with_selected_producer(self):
        import frontend_regen as fe
        import stage_loop as sl
        from ourosmith.surface_faults import build_frontend

        with self.fixture() as fixture:
            scratch = fixture.directory / "mutant"
            (scratch / "fe").mkdir(parents=True)
            with patch.object(fe, "regenerate") as frontend, \
                 patch.object(fe, "collect_units", side_effect=([], [fe.packer.PARSER_UNIT_OWNER])), \
                 patch.object(fe, "run_pack") as pack, patch("ourosmith.surface_faults.subprocess.run") as emit, \
                 patch.object(sl, "emit_backend") as backend, patch.object(sl, "build_stage_binary") as link:
                build_frontend(scratch, fixture.compiler)
            self.assertEqual(frontend.call_args.kwargs["ouro1"], fixture.compiler)
            self.assertEqual(frontend.call_args.kwargs["jobs"], 1)
            self.assertEqual(emit.call_args.args[0][0], fixture.compiler.as_posix())
            self.assertEqual(pack.call_args.kwargs["parser_min_ordinal"], 0)
            self.assertEqual(backend.call_args.args[:2], (fixture.compiler, scratch / "backend.c"))
            self.assertEqual(link.call_args.args[1], scratch / "backend.c")

    def test_retirement_binaries_require_one_driver_and_surface_producer(self):
        from ourosmith.evidence import required_binaries
        from ourosmith.native import RETAINED_ENTRY, SMITH_ENTRY

        with self.fixture() as fixture:
            compiler = fixture.compiler.relative_to(ROOT).as_posix()
            drivers = {entry: {"compiler": compiler, "binary": (fixture.directory / (str(index) + ".exe")).relative_to(ROOT).as_posix()}
                       for index, entry in enumerate((SMITH_ENTRY, RETAINED_ENTRY))}
            evidence = host.toolchain_evidence(fixture.compiler, fixture.tools)
            expected = {path.relative_to(ROOT).as_posix() for path in fixture.tools.values()}
            expected.update(row["binary"] for row in drivers.values())
            self.assertEqual(required_binaries(True, drivers, evidence), expected)
            with self.assertRaises(ValueError):
                required_binaries(True, drivers, None)
            drivers[RETAINED_ENTRY]["compiler"] = "_build/different-producer.exe"
            with self.assertRaisesRegex(ValueError, "different compilers"):
                required_binaries(True, drivers, evidence)
