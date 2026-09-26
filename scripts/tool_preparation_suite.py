#!/usr/bin/env python3
"""Host preparation contracts; no native compiler or diagnostic-parity claims.

Run with python3 scripts/tool_preparation_suite.py. Compiler emission/linking
are mocked deliberately; native suites must still validate the built tools.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import frontend_regen as frontend
import native_tool_build as native


class SourceContracts(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.addCleanup(patch.stopall)
        patch.object(frontend, "ROOT", self.root).start()

    def source(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_shared_imports_read_once_with_identical_order(self):
        self.source("shared.ouro", "def x : Nat := 1;\n")
        self.source("left.ouro", 'import "shared.ouro" as Shared;\n')
        self.source("right.ouro", 'import "shared.ouro";\n')
        expected = {name: frontend.collect_units(name) for name in ("left.ouro", "right.ouro")}
        with patch.object(frontend, "import_targets", wraps=frontend.import_targets) as reads:
            actual = frontend.collect_units_many(["left.ouro", "right.ouro", "left.ouro"])
        self.assertEqual(actual, expected)
        self.assertEqual(Counter(call.args[0] for call in reads.call_args_list),
                         {"left.ouro": 1, "right.ouro": 1, "shared.ouro": 1})

    def test_diamond_preserves_postorder(self):
        for name, text in {"base.ouro": "", "a.ouro": 'import "base.ouro";\n',
                           "b.ouro": 'import "base.ouro";\n',
                           "root.ouro": 'import "a.ouro";\nimport "b.ouro";\n'}.items():
            self.source(name, text)
        self.assertEqual(frontend.collect_units("root.ouro"),
                         ["base.ouro", "a.ouro", "b.ouro", "root.ouro"])

    def test_grouped_imports_preserve_all_edges_and_order(self):
        for name, text in {"base.ouro": "", "left/a.ouro": 'import "../base.ouro";',
                           "right/a.ouro": 'import "../base.ouro";',
                           "root.ouro": 'import -- first\n "left/a.ouro", -- second\n'
                                        ' "right/a.ouro", "left/a.ouro",;\n'}.items():
            self.source(name, text)
        self.assertEqual(frontend.collect_units("root.ouro"),
                         ["base.ouro", "left/a.ouro", "right/a.ouro", "root.ouro"])

    def test_selective_imports_keep_the_full_dependency_closure(self):
        for name, text in {
            "leaf.ouro": "axiom Visible : Type; axiom Hidden : Type;",
            "middle.ouro": 'import "leaf.ouro" exposing (Visible as Pick);',
            "root.ouro": 'import "middle.ouro"; def value : Type := Pick;',
        }.items():
            self.source(name, text)
        self.assertEqual(frontend.collect_units("root.ouro"),
                         ["leaf.ouro", "middle.ouro", "root.ouro"])

    def test_grouped_second_edge_cycle_and_missing_file_fail(self):
        self.source("base.ouro", "")
        root = self.source("root.ouro", 'import "base.ouro", "missing.ouro";')
        with self.assertRaisesRegex(SystemExit, "missing missing.ouro"):
            frontend.collect_units("root.ouro")
        root.write_text('import "base.ouro", "cycle.ouro";', encoding="utf-8")
        self.source("cycle.ouro", 'import "root.ouro";')
        with self.assertRaisesRegex(SystemExit, "import cycle"):
            frontend.collect_units("root.ouro")

    def test_import_tokens_keep_literals_comments_aliases_and_escapes_distinct(self):
        source = ('-- import "comment.ouro";\n'
                  'def text := "import \\"literal.ouro\\";";\n'
                  'import "left.ouro" as Left; import "path\\\\part.ouro", "путь 漢字.ouro";\n'
                  'import "last.ouro"\nimport "next.ouro";')
        self.assertEqual(frontend.SMC.quoted_import_targets(source, "root.ouro"),
                         ["left.ouro", "path/part.ouro", "путь 漢字.ouro", "last.ouro", "next.ouro"])

    def test_braced_unicode_imports_match_literal_paths(self):
        source = r'import "caf\u{e9}.ouro", "\u{1F600}.ouro";'
        self.assertEqual(frontend.SMC.quoted_import_targets(source, "root.ouro"),
                         ["café.ouro", "😀.ouro"])

    def test_raw_imports_preserve_bytes_and_hide_multiline_code(self):
        source = ('def text : String := r#"import "fake.ouro";\n'
                  '-- @export fake\n"#;\n'
                  'import r#"dir\\leaf.ouro"#, r#"café.ouro"#;')
        self.assertEqual(frontend.SMC.quoted_import_targets(source, "root.ouro"),
                         ["dir/leaf.ouro", "café.ouro"])

    def test_unterminated_raw_import_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "malformed quoted import"):
            frontend.SMC.quoted_import_targets('import r#"unfinished.ouro";', "root.ouro")

    def test_malformed_braced_unicode_imports_fail_closed(self):
        for spelling in (r'\u{}', r'\u{12G}', r'\u{0000041}',
                         r'\u{D800}', r'\u{110000}', r'\u{41'):
            with self.subTest(spelling=spelling), self.assertRaisesRegex(
                    ValueError, "malformed Unicode escape"):
                frontend.SMC.quoted_import_targets(f'import "{spelling}.ouro";',
                                                     "root.ouro")

    def test_projection_named_import_does_not_add_dependencies(self):
        source = ('def field (p : Packet) : Nat := p.import "fake.ouro";\n'
                  'def call (p : Packet) : Nat := p.import("also-fake.ouro");\n'
                  'import "real.ouro";')
        self.assertEqual(frontend.SMC.quoted_import_targets(source, "root.ouro"), ["real.ouro"])

    def test_malformed_import_group_is_not_an_incomplete_closure(self):
        for source in ('import "first.ouro",', 'import "first.ouro",, "second.ouro";',
                       'import "first.ouro", missing;', 'import "first.ouro", "unfinished'):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, "malformed quoted import"):
                frontend.SMC.quoted_import_targets(source, "root.ouro")

    def test_later_call_observes_same_mtime_import_change(self):
        root = self.source("root.ouro", 'import "one.ouro";\n')
        self.source("one.ouro", "")
        self.source("two.ouro", "")
        self.assertEqual(frontend.collect_units("root.ouro"), ["one.ouro", "root.ouro"])
        saved = root.stat()
        root.write_text('import "two.ouro";\n', encoding="utf-8")
        os.utime(root, ns=(saved.st_atime_ns, saved.st_mtime_ns))
        self.assertEqual(frontend.collect_units("root.ouro"), ["two.ouro", "root.ouro"])

    def test_cycle_after_completed_root_is_not_hidden(self):
        self.source("good.ouro", "")
        self.source("a.ouro", 'import "b.ouro";\n')
        self.source("b.ouro", 'import "a.ouro";\n')
        with self.assertRaisesRegex(SystemExit, "import cycle while collecting a.ouro: a.ouro"):
            frontend.collect_units_many(["good.ouro", "a.ouro"])

    def test_missing_dependency_fails_and_is_not_memoized(self):
        self.source("root.ouro", 'import "missing.ouro";\n')
        with self.assertRaisesRegex(SystemExit, "missing missing.ouro"):
            frontend.collect_units("root.ouro")
        self.source("missing.ouro", "")
        self.assertEqual(frontend.collect_units("root.ouro"), ["missing.ouro", "root.ouro"])

    def test_single_file_never_walks_unrelated_tree(self):
        self.source("one.ouro", "")
        self.source("unrelated/broken.ouro", 'import "absent.ouro";\n')
        with patch.object(Path, "glob", side_effect=AssertionError("inventory scan")), \
                patch.object(Path, "rglob", side_effect=AssertionError("inventory scan")):
            self.assertEqual(frontend.collect_units("one.ouro"), ["one.ouro"])

    def test_compiler_probe_reads_only_header(self):
        class Tracked(io.BytesIO):
            def read(self, size=-1):
                self.requested = size
                return super().read(size)

        path = self.source("compiler", "unused")
        stream = Tracked(b"\x7fELF" + b"x" * 4096)
        with patch.object(Path, "open", return_value=stream), \
                patch.object(Path, "read_bytes", side_effect=AssertionError("whole binary read")):
            self.assertEqual(frontend.ouro1_cmd(path), [str(path)])
        self.assertEqual(stream.requested, 80)

    def test_compiler_probe_retains_shebang_contract(self):
        path = self.source("compiler", "#!/usr/bin/env python3\n")
        self.assertEqual(frontend.ouro1_cmd(path), [sys.executable, str(path)])
        path.write_bytes(b"\x7fELF\x00")
        self.assertEqual(frontend.ouro1_cmd(path), [str(path)])
        path.unlink()
        self.assertEqual(frontend.ouro1_cmd(path), [str(path)])
        script = self.source("fake.py", "")
        self.assertEqual(frontend.ouro1_cmd(script), [sys.executable, str(script)])


class BuildContracts(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(redirect_stderr(io.StringIO()))
        self.flags = ["-O1"]
        self.enabled = True
        self.emissions = []
        self.links = []
        for module in (frontend, native):
            self.stack.enter_context(patch.object(module, "ROOT", self.root))
        self.stack.enter_context(patch.object(native, "BUILD_INPUTS", ("build-policy.txt",)))
        self.stack.enter_context(patch.object(native, "RUNTIME", ()))
        self.write("build-policy.txt", b"policy")
        self.write("runtime/contract.h", b"header")
        self.write("lib/base.ouro", b"def x : Nat := 1;\n")
        self.write("tools/main.ouro", b'import "../lib/base.ouro";\n')
        self.write("tools/companion.ouro", b'import "../lib/base.ouro";\n')
        self.compiler = self.write("compiler-image", b"\x7fELF-compiler", executable=True)
        self.cc = self.write("cc-image", b"\x7fELF-cc", executable=True)
        self.cfg = Mock()
        self.cfg.get_bool.side_effect = lambda _key: self.enabled
        self.cfg.path.side_effect = lambda key: self.root / key
        operations = {
            "load_config": lambda _args: self.cfg,
            "choose_cc": lambda _cfg: str(self.cc),
            "compiler_id": lambda _cc: "fixture-cc",
            "profile_cflags": lambda _cfg: list(self.flags),
            "host_link_flags": lambda: [],
            "jobs_value": lambda _cfg: 64,
            "trim_cache": lambda _cfg: None,
            "write_text_atomic": lambda path, text: path.write_text(text, encoding="utf-8"),
            "build_c_executable": self.link,
        }
        for name, operation in operations.items():
            self.stack.enter_context(patch.object(native.build, name, side_effect=operation))
        self.stack.enter_context(patch.object(native, "emit", side_effect=self.emit))
        self.args = argparse.Namespace(entry="tools/main.ouro", output=self.root / "bin/tool",
                                       compiler=self.compiler, fuel=60000, check=False,
                                       tool=None, batch_report=None)

    def write(self, name, data, executable=False):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if executable:
            path.chmod(0o755)
        return path

    def mutate(self, path):
        saved = path.stat()
        path.write_bytes(path.read_bytes() + b"\n")
        os.utime(path, ns=(saved.st_atime_ns, saved.st_mtime_ns))

    def emit(self, _compiler, units, _fuel, generated):
        self.emissions.append(list(units))
        generated.write_text("\n".join(units), encoding="utf-8")

    def link(self, _cfg, **kwargs):
        self.links.append(kwargs)
        kwargs["output"].write_bytes(b"fixture-executable")
        kwargs["output"].chmod(0o755)
        return {"fixture": True}

    def run_build(self):
        return native.build_tool(self.args)

    def output(self):
        return Path(str(self.args.output) + ".exe") if os.name == "nt" else self.args.output

    def test_unchanged_does_not_emit_or_link(self):
        first = self.run_build()
        second = self.run_build()
        self.assertEqual(first["cache"], "miss")
        self.assertEqual(second["cache"], "installed-hit")
        self.assertEqual(first["key"], second["key"])
        self.assertEqual(len(self.emissions), 1)
        self.assertEqual(len(self.links), 1)
        self.assertEqual(self.links[0]["jobs"], 2)

    def test_removed_output_restores_verified_cache_without_emit(self):
        self.run_build()
        self.output().unlink()
        self.assertEqual(self.run_build()["cache"], "hit")
        self.assertEqual(len(self.emissions), 1)

    def test_content_inputs_invalidate_even_with_preserved_mtime(self):
        previous = self.run_build()["key"]
        for path in (self.root / "lib/base.ouro", self.compiler, self.cc,
                     self.root / "build-policy.txt", self.root / "runtime/contract.h"):
            with self.subTest(path=path.name):
                self.mutate(path)
                result = self.run_build()
                self.assertEqual(result["cache"], "miss")
                self.assertNotEqual(previous, result["key"])
                previous = result["key"]
        self.assertEqual(len(self.emissions), 6)

    def test_flags_environment_and_fuel_invalidate(self):
        previous = self.run_build()["key"]
        self.flags.append("-g")
        changed = self.run_build()["key"]
        self.assertNotEqual(previous, changed)
        with patch.dict(os.environ, {"CPATH": str(self.root / "include")}):
            environment = self.run_build()["key"]
            self.assertNotEqual(changed, environment)
            self.args.fuel += 1
            self.assertNotEqual(environment, self.run_build()["key"])

    def test_corrupt_installed_binary_is_replaced_from_verified_cache(self):
        self.run_build()
        self.output().write_bytes(b"corrupt")
        self.assertEqual(self.run_build()["cache"], "hit")
        self.assertEqual(self.output().read_bytes(), b"fixture-executable")
        self.assertEqual(len(self.emissions), 1)

    def test_corrupt_receipts_or_cache_never_count_as_hits(self):
        first = self.run_build()
        receipt = Path(str(self.args.output) + ".build.json")
        receipt.write_text("{", encoding="utf-8")
        self.assertEqual(self.run_build()["cache"], "hit")
        directory = self.cfg.path("cache_dir") / "native-tools" / first["key"]
        self.output().unlink()
        (directory / "tool.json").write_text("[]", encoding="utf-8")
        self.assertEqual(self.run_build()["cache"], "miss")
        self.output().unlink()
        (directory / ("tool.exe" if os.name == "nt" else "tool")).write_bytes(b"damaged")
        self.assertEqual(self.run_build()["cache"], "miss")
        self.assertEqual(len(self.emissions), 3)

    def test_check_missing_or_stale_never_builds(self):
        self.args.check = True
        self.assertFalse(self.run_build()["current"])
        self.assertEqual(self.emissions, [])
        self.args.check = False
        self.run_build()
        self.args.check = True
        self.assertTrue(self.run_build()["current"])
        self.mutate(self.root / "lib/base.ouro")
        self.assertFalse(self.run_build()["current"])
        self.assertEqual(len(self.emissions), 1)

    def test_incomplete_build_does_not_publish_receipt_or_replace_output(self):
        first = self.run_build()
        receipt = Path(str(self.args.output) + ".build.json")
        old_receipt, old_binary = receipt.read_bytes(), self.output().read_bytes()
        self.mutate(self.root / "lib/base.ouro")
        with patch.object(native, "emit", side_effect=RuntimeError("interrupted emit")):
            with self.assertRaisesRegex(RuntimeError, "interrupted emit"):
                self.run_build()
        self.assertEqual(receipt.read_bytes(), old_receipt)
        self.assertEqual(self.output().read_bytes(), old_binary)
        self.assertEqual(self.run_build()["cache"], "miss")
        self.assertNotEqual(first["key"], self.run_build()["key"])

    def test_failed_link_is_not_a_cache_hit(self):
        def interrupted(_cfg, **kwargs):
            kwargs["output"].write_bytes(b"partial")
            raise RuntimeError("interrupted link")
        with patch.object(native.build, "build_c_executable", side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, "interrupted link"):
                self.run_build()
        self.assertFalse(Path(str(self.args.output) + ".build.json").exists())
        self.assertEqual(self.run_build()["cache"], "miss")
        self.assertEqual(self.output().read_bytes(), b"fixture-executable")

    def test_disabled_cache_rebuilds(self):
        self.enabled = False
        self.run_build()
        self.run_build()
        self.assertEqual(len(self.emissions), 2)
        self.assertEqual(len(self.links), 2)

    def test_companion_existence_and_legacy_flag_do_not_bypass_receipt(self):
        def mapping(entry):
            return (("tools/companion.ouro", "companion"),) if entry == "tools/main.ouro" else ()
        companion = self.root / ("bin/companion.exe" if os.name == "nt" else "bin/companion")
        self.write(companion.relative_to(self.root), b"old-unverified", executable=True)
        with patch.object(native, "tool_companions", side_effect=mapping), \
                patch.dict(os.environ, {"OURO_REUSE_EXISTING_COMPANION": "1"}):
            self.run_build()
            self.assertEqual([units[-1] for units in self.emissions],
                             ["tools/companion.ouro", "tools/main.ouro"])
            companion.write_bytes(b"stale")
            self.args.check = True
            self.assertFalse(self.run_build()["current"])
            self.assertEqual(len(self.emissions), 2)

    def test_lint_companions_include_transitive_sources_and_validate_each_binary(self):
        self.stack.enter_context(patch.object(native, "embed_windows_manifest"))
        for entry in native.tool_roots("tools/lint.ouro"):
            self.write(entry, b'import "../lib/base.ouro";\n' if entry == "tools/lint.ouro"
                       else b"def value : Nat := 1;\n")
        self.args.entry = "tools/lint.ouro"
        built = self.run_build()
        self.assertEqual([units[-1] for units in self.emissions],
                         ["tools/lint_style.ouro", "tools/clippy/structural_main.ouro",
                          "tools/clippy/main.ouro", "tools/lint.ouro"])
        for entry in native.tool_roots("tools/lint.ouro"):
            self.assertIn(entry, built["inputs"]["sources"])
        for name in ("ouro-lint-style", "ouro-clippy-grade-firewall", "ouro-clippy-structural"):
            with self.subTest(name=name):
                path = self.args.output.parent / (name + (".exe" if os.name == "nt" else ""))
                saved = path.read_bytes()
                path.write_bytes(b"changed")
                self.args.check = True
                self.assertFalse(self.run_build()["current"])
                path.write_bytes(saved)
                self.assertTrue(self.run_build()["current"])


class BatchContracts(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.args = argparse.Namespace(entry=None, output=None, tool=[],
                                       batch_report=None, compiler=self.root / "compiler",
                                       fuel=60000, check=False)

    def pairs(self, *names):
        self.args.tool = [(name + ".ouro", str(self.root / name)) for name in names]
        return self.args

    def test_duplicate_requests_preserve_order_and_collapse(self):
        requests = native.build_requests(self.pairs("a", "b", "a"))
        self.assertEqual([r.entry for r in requests], ["a.ouro", "b.ouro"])

    def test_conflicting_outputs_and_receipts_are_rejected(self):
        for output in ("same", "same.sources", "same.build.json"):
            with self.subTest(output=output):
                self.args.tool = [("a.ouro", str(self.root / "same")),
                                  ("b.ouro", str(self.root / output))]
                with self.assertRaisesRegex(ValueError, "conflicting"):
                    native.build_requests(self.args)

    def test_companion_conflicts_are_rejected_before_build(self):
        self.args.tool = [("tools/fmt.ouro", str(self.root / "fmt")),
                          ("other.ouro", str(self.root / "ouro-fix-check"))]
        with self.assertRaisesRegex(ValueError, "conflicting"):
            native.build_requests(self.args)
        for name in ("ouro-lint-style", "ouro-clippy-grade-firewall", "ouro-clippy-structural"):
            with self.subTest(name=name):
                self.args.tool = [("tools/lint.ouro", str(self.root / "lint")),
                                  ("other.ouro", str(self.root / name))]
                with self.assertRaisesRegex(ValueError, "conflicting"):
                    native.build_requests(self.args)

    def test_report_cannot_replace_receipt_or_source(self):
        self.pairs("a")
        for target in (self.root / "a.sources", native.ROOT / "a.ouro"):
            self.args.batch_report = target
            with self.assertRaises(ValueError):
                native.build_requests(self.args)

    def test_mixed_or_incomplete_cli_rejected(self):
        with self.assertRaises(ValueError):
            native.build_requests(self.args)
        self.pairs("a")
        self.args.entry = "positional.ouro"
        with self.assertRaises(ValueError):
            native.build_requests(self.args)
        self.args.entry = None
        self.args.tool = [("a\0.ouro", "out")]
        with self.assertRaises(ValueError):
            native.build_requests(self.args)

    def call_main(self, results, check=False):
        report = self.root / "report.json"
        report.write_text('{"status":"PASS","pass":true}', encoding="utf-8")
        observed = []
        def operation(_args):
            observed.append(json.loads(report.read_text(encoding="utf-8"))["status"])
            value = results[len(observed) - 1]
            if isinstance(value, Exception):
                raise value
            return value
        argv = ["--compiler", str(self.args.compiler), "--batch-report", str(report)]
        for entry, output in self.pairs("a", "b").tool:
            argv.extend(["--tool", entry, output])
        if check:
            argv.append("--check")
        with patch.object(native.build, "add_common"), \
                patch.object(native, "configure_native_stack"), \
                patch.object(native, "build_tool", side_effect=operation) as build, \
                redirect_stderr(io.StringIO()):
            code = native.main(argv)
        return code, json.loads(report.read_text(encoding="utf-8")), observed, build.call_count

    def test_batch_success_reports_each_tool(self):
        code, report, observed, count = self.call_main([{"cache": "installed-hit"}, {"cache": "hit"}])
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["completed"], 2)
        self.assertEqual(observed, ["RUNNING", "RUNNING"])
        self.assertEqual(count, 2)

    def test_batch_failure_stops_and_replaces_old_success(self):
        code, report, observed, count = self.call_main([RuntimeError("failed"), {}])
        self.assertEqual(code, 1)
        self.assertFalse(report["pass"])
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["completed"], 0)
        self.assertEqual(observed, ["RUNNING"])
        self.assertEqual(count, 1)

    def test_check_batch_evaluates_all_and_reports_stale(self):
        code, report, observed, count = self.call_main([{"current": False}, {"current": True}], check=True)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "STALE")
        self.assertFalse(report["pass"])
        self.assertEqual(observed, ["RUNNING", "RUNNING"])
        self.assertEqual(count, 2)


if __name__ == "__main__":
    unittest.main()
