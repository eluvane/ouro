#!/usr/bin/env python3
"""Host preparation contracts; no native compiler or diagnostic-parity claims.

Run with python3 scripts/tool_preparation_suite.py. Compiler emission/linking
are mocked deliberately; native suites must still validate the built tools.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

import frontend_regen as frontend
import native_tool_build as native


class CacheAccessContracts(unittest.TestCase):
    def test_pruning_waits_until_builders_release_the_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "cache"
            cache.mkdir()
            output = cache / "emit.active.c"
            output.write_bytes(b"x" * (2 * 1024 * 1024))
            build = native.build
            cfg = build.ResolvedConfig({**build.DEFAULTS, "cache_dir": str(cache), "cache_size_mb": 1}, {})
            trim = [sys.executable, "-B", "-c", """
import sys
import ouro_build as build
cfg = build.ResolvedConfig({**build.DEFAULTS, "cache_dir": sys.argv[1], "cache_size_mb": 1}, {})
if sys.argv[2] == "reader":
    with build.cache_build_access(cfg):
        build.trim_cache(cfg)
else:
    build.trim_cache(cfg)
""", str(cache)]
            scripts = build.ROOT / "scripts"

            with build.cache_build_access(cfg):
                subprocess.run([*trim, "reader"], cwd=scripts, check=True, timeout=20)
                self.assertTrue(output.is_file())

            subprocess.run([*trim, "idle"], cwd=scripts, check=True, timeout=20)
            self.assertFalse(output.exists())

    def test_pruning_continues_past_a_protected_entry_after_preparation(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary).resolve() / "cache"
            cache.mkdir()
            retained, evicted, current = (cache / name for name in ("old.gen.c", "older.o", "current.o"))
            for index, path in enumerate((retained, evicted, current), start=1):
                path.write_bytes(b"x" * (512 * 1024))
                os.utime(path, (index, index))
            build = native.build
            cfg = build.ResolvedConfig({**build.DEFAULTS, "cache_dir": str(cache), "cache_size_mb": 1}, {})
            report = {"cache": "miss"}
            stderr = io.StringIO()
            unlink = Path.unlink

            def remove(path):
                if path == retained:
                    raise PermissionError("entry is in use")
                unlink(path)

            with (patch.object(build, "load_config", return_value=cfg),
                  patch.object(native, "_build_tool", return_value=(report, True)),
                  patch.object(Path, "unlink", autospec=True, side_effect=remove),
                  redirect_stderr(stderr)):
                self.assertIs(native.build_tool(argparse.Namespace()), report)

            self.assertIn(retained.name, stderr.getvalue())
            self.assertIn("entry is in use", stderr.getvalue())
            self.assertEqual(set(cache.iterdir()), {retained, current})
            self.assertEqual(build.dir_size(cache), 1024 * 1024)


class GateLaunchContracts(unittest.TestCase):
    def test_shell_gate_searches_path_once_and_preserves_launch(self):
        import ci_gate
        from ourosmith import host

        gate = ci_gate.Gate("shell-fixture", ["sh", "fixture.sh"], ("pr",))
        fallback = Path("C:/Program Files/Git/usr/bin/sh.exe")
        parent = {"PATH": "configured-bin"}
        fallback_env = {"PATH": os.pathsep.join([str(fallback.parent), parent["PATH"]])}
        windows = SimpleNamespace(name="nt", environ={})
        process = SimpleNamespace(poll=lambda: 0, returncode=0)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for found, command, environment in (
                (str(fallback), gate.cmd, parent),
                (None, [str(fallback), *gate.cmd[1:]], fallback_env),
            ):
                with (self.subTest(found=found), patch.object(host, "os", windows),
                      patch.object(Path, "is_file", autospec=True, side_effect=lambda path: path == fallback),
                      patch.object(ci_gate, "env_for", return_value=dict(parent)),
                      patch.object(ci_gate.shutil, "which", return_value=found) as discover,
                      patch.object(ci_gate.subprocess, "Popen", return_value=process) as launch,
                      redirect_stdout(io.StringIO())):
                    result = ci_gate.run_gate(gate, out=root, workspace=root, allocation=ci_gate.Allocation(1, 512))
                    discover.assert_called_once_with("sh")
                    launch.assert_called_once()
                    self.assertEqual(launch.call_args.args[0], command)
                    self.assertEqual(launch.call_args.kwargs["env"], environment)
                    self.assertEqual(result["command"], gate.cmd)
                    self.assertEqual(result["status"], "pass")


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

    def test_capture_binds_imports_and_hashes_to_one_read(self):
        data = b'-- line before import\rimport "shared.ouro";\r\n'
        entries = ["left.ouro", "right.ouro"]
        files = [self.source(name, "") for name in [*entries, "shared.ouro"]]
        for path in files[:2]:
            path.write_bytes(data)
        read_bytes = Path.read_bytes
        with patch.object(Path, "read_bytes", autospec=True, side_effect=read_bytes) as reads:
            closures, digests = frontend.capture_unit_inputs(entries)
        self.assertEqual(closures, {name: ["shared.ouro", name] for name in entries})
        self.assertEqual(Counter(call.args[0] for call in reads.call_args_list), Counter(files))
        for entry in entries:
            self.assertEqual(digests[entry].sha256, frontend.sha256_bytes(data))
            self.assertEqual(digests[entry].bytes, len(data))

    def test_shared_import_cache_reuses_digest_after_fresh_byte_comparison(self):
        modules = frontend.SMC
        source = self.source("root.ouro", "")
        leaf = self.source("leaf.ouro", "")
        original = b'import "leaf.ouro";\ndef main : Nat := 0;'
        changed = original[:-2] + b"1;"
        source.write_bytes(original)
        saved = source.stat()
        parse_bytes = modules.cached_import_parser()
        with (patch.object(modules, "ROOT", self.root),
              patch.object(modules, "sha256_bytes", wraps=modules.sha256_bytes) as hashes,
              patch.object(Path, "read_bytes", autospec=True, side_effect=Path.read_bytes) as reads):
            graph, initial = frontend.capture_unit_inputs([source.name], parse_bytes=parse_bytes)
            self.assertEqual(frontend.capture_unit_inputs([source.name], parse_bytes=parse_bytes), (graph, initial))
            plans = modules.make_module_plans(graph[source.name], "fixture", parse_bytes=parse_bytes)
            self.assertEqual(plans[source.name].source.sha256, initial[source.name].sha256)

            source.write_bytes(changed)
            os.utime(source, ns=(saved.st_atime_ns, saved.st_mtime_ns))
            after, updated = frontend.capture_unit_inputs([source.name], parse_bytes=parse_bytes)
            self.assertEqual(after, graph)
            self.assertEqual(updated[source.name].sha256, frontend.sha256_bytes(changed))
            self.assertNotEqual(updated[source.name].sha256, initial[source.name].sha256)
            self.assertEqual([call.args[0] for call in hashes.call_args_list], [original, b"", changed])
            self.assertEqual(Counter(call.args[0] for call in reads.call_args_list), {source: 4, leaf: 4})

    def test_import_digest_stays_bound_to_its_snapshot_during_replacement(self):
        modules = frontend.SMC
        parse_bytes = modules.cached_import_parser()
        first = b'import "first.ouro";'
        second = b'import "second.ouro";'
        source = "root.ouro"

        def replace_while_hashing(data):
            self.assertEqual(parse_bytes(second, source), ["second.ouro"])
            return frontend.sha256_bytes(data)

        with patch.object(modules, "sha256_bytes", side_effect=replace_while_hashing):
            self.assertEqual(parse_bytes.parse_and_digest(first, source), (["first.ouro"], frontend.sha256_bytes(first)))
        self.assertEqual(parse_bytes.parse_and_digest(second, source), (["second.ouro"], frontend.sha256_bytes(second)))

    def test_custom_import_parser_does_not_supply_source_digest(self):
        source = self.source("root.ouro", "")
        parse_bytes = Mock(spec=frontend.SMC.CachedImportParser, return_value=[])
        parse_bytes.parse_and_digest.return_value = ([], "incorrect digest")
        graph, digests = frontend.capture_unit_inputs([source.name], parse_bytes=parse_bytes)
        self.assertEqual(graph, {source.name: [source.name]})
        self.assertEqual(digests[source.name].sha256, frontend.sha256_bytes(b""))
        parse_bytes.parse_and_digest.assert_not_called()

    def test_frontend_install_rechecks_bytes_at_unchanged_size_and_mtime(self):
        payload = b"C" * (1024 * 1024) + b"\0\xff"
        candidate, installed = self.root / "candidate.c", self.root / "installed.c"
        candidate.write_bytes(payload)
        installed.write_bytes(payload)
        candidate_stamp, installed_stamp = candidate.stat(), installed.stat()
        self.assertEqual(frontend.install_if_changed(candidate, installed), "unchanged")
        self.assertFalse(candidate.exists())
        self.assertEqual(installed.stat().st_mtime_ns, installed_stamp.st_mtime_ns)

        candidate.write_bytes(payload)
        os.utime(candidate, ns=(candidate_stamp.st_atime_ns, candidate_stamp.st_mtime_ns))
        changed = payload[:-1] + b"\x01"
        installed.write_bytes(changed)
        os.utime(installed, ns=(installed_stamp.st_atime_ns, installed_stamp.st_mtime_ns))
        self.assertEqual(installed.stat().st_mtime_ns, installed_stamp.st_mtime_ns)
        self.assertEqual(installed.stat().st_size, installed_stamp.st_size)
        with patch.object(frontend.os, "replace", side_effect=PermissionError("fixture replacement refused")):
            with self.assertRaisesRegex(PermissionError, "fixture replacement refused"):
                frontend.install_if_changed(candidate, installed)
        self.assertEqual(installed.read_bytes(), changed)
        self.assertEqual(candidate.read_bytes(), payload)
        self.assertEqual(frontend.install_if_changed(candidate, installed), "updated")
        self.assertEqual(installed.read_bytes(), payload)
        self.assertFalse(candidate.exists())

    def test_module_cache_rereads_sources_without_reparsing_matching_bytes(self):
        modules = frontend.SMC
        source = self.source("root.ouro", 'import "left.ouro", "right.ouro";')
        leaves = [self.source("left.ouro", ""), self.source("right.ouro", "")]
        paths = [source, *leaves]
        parse_bytes = modules.cached_import_parser()
        with patch.object(modules, "ROOT", self.root), \
             patch.object(modules, "quoted_import_targets", wraps=modules.quoted_import_targets) as parse, \
             patch.object(Path, "read_bytes", autospec=True, side_effect=Path.read_bytes) as reads:
            graph, inputs = frontend.capture_unit_inputs(["root.ouro"], parse_bytes=parse_bytes)
            options = dict(roots=["root.ouro"], unit_graph=graph, work=self.root / "work",
                           cache_root=self.root / "cache", cache_enabled=False, parse_bytes=parse_bytes)
            report = modules.materialize_module_artifacts(**options)
            self.assertEqual(Counter(call.args[0] for call in reads.call_args_list if call.args[0] in paths),
                             {path: 2 for path in paths})
            self.assertEqual(Counter(call.args[1] for call in parse.call_args_list),
                             {path.name: 1 for path in paths})
            self.assertEqual([row["path"] for row in report["modules"]], graph["root.ouro"])

            saved = source.stat()
            source.write_bytes(b'import "right.ouro", "left.ouro";')
            os.utime(source, ns=(saved.st_atime_ns, saved.st_mtime_ns))
            with self.assertRaisesRegex(SystemExit, "ordered import closure changed for root.ouro"):
                modules.materialize_module_artifacts(**options)
            updated_graph, updated_inputs = frontend.capture_unit_inputs(["root.ouro"], parse_bytes=parse_bytes)
            self.assertEqual(updated_graph["root.ouro"], ["right.ouro", "left.ouro", "root.ouro"])
            self.assertNotEqual(inputs["root.ouro"].sha256, updated_inputs["root.ouro"].sha256)
            self.assertEqual([call.args[1] for call in parse.call_args_list].count("root.ouro"), 2)

    def test_frontend_bindings_recheck_canonical_imports_with_a_shared_parser(self):
        source = self.source("root.ouro", 'import "left.ouro", "right.ouro";')
        self.source("left.ouro", "")
        self.source("right.ouro", "")
        units = frontend.collect_units("root.ouro")
        parse_bytes = frontend.SMC.cached_import_parser()
        with (patch.object(frontend, "module_lookup_contract", return_value={"capability": True}),
              patch.object(frontend, "lower_local_lookup_contract", return_value={"capability": True}),
              patch.object(frontend.packer, "MODULE_LOOKUP_OWNER", "root.ouro"),
              patch.object(frontend.packer, "LOWER_LOCAL_LOOKUP_OWNER", "root.ouro"),
              patch.object(frontend.packer, "MODULE_LOOKUP_SOURCE_PATHS", ("root.ouro",)),
              patch.object(frontend.packer, "LOWER_LOCAL_LOOKUP_SOURCE_PATHS", ("root.ouro",)),
              patch.object(frontend.SMC, "quoted_import_targets", wraps=frontend.SMC.quoted_import_targets) as parse,
              patch.object(frontend, "import_targets", wraps=frontend.import_targets) as read):
            self.assertTrue(frontend.module_lookup_binding("root.ouro", units, {}, parse_bytes=parse_bytes)["selected"])
            self.assertTrue(frontend.lower_local_lookup_binding(
                "root.ouro", units, {}, parse_bytes=parse_bytes)["selected"])
            self.assertEqual(Counter(call.args[0] for call in read.call_args_list), {path: 2 for path in units})
            self.assertEqual(Counter(call.args[1] for call in parse.call_args_list), {path: 1 for path in units})

            saved = source.stat()
            source.write_bytes(b'import "right.ouro", "left.ouro";')
            os.utime(source, ns=(saved.st_atime_ns, saved.st_mtime_ns))
            with self.assertRaisesRegex(RuntimeError, "^lower local lookup canonical source closure changed$"):
                frontend.lower_local_lookup_binding("root.ouro", units, {}, parse_bytes=parse_bytes)
            self.assertEqual([call.args[1] for call in parse.call_args_list].count("root.ouro"), 2)

    def test_tool_source_verification_reuses_imports_and_rechecks_source_bytes(self):
        entry, owner, runtime = "root.ouro", "lookup.ouro", "runtime/frontend_link.c"
        root = self.source(entry, 'import "lookup.ouro";\n')
        lookup = self.source(owner, "def value : Nat := 1;\n")
        runtime_path = self.source(runtime, "")
        generated = self.source("tool.gen.c", "/* fixture */\n")
        _, digest = native.build.GCS.read_source_text_digest(generated)
        expected_sources = {"backend": digest}
        parse_bytes = native.cached_import_parser()
        _, captured = frontend.capture_unit_inputs([entry], parse_bytes=parse_bytes)
        source_hashes = {name: value.sha256 for name, value in captured.items()}
        source_hashes[runtime] = native.sha256_file(runtime_path)
        inputs = {"entry": entry, "sources": source_hashes}
        saved = lookup.stat()

        def change_after_closure(_text):
            lookup.write_bytes(lookup.read_bytes().replace(b"1", b"2"))
            os.utime(lookup, ns=(saved.st_atime_ns, saved.st_mtime_ns))
            return True

        with (patch.object(native, "ROOT", self.root),
              patch.object(native.packer, "LOWER_LOCAL_LOOKUP_OWNER", owner),
              patch.object(frontend, "module_lookup_capability", return_value=True) as capable,
              patch.object(native, "current_native_scoped_original", return_value="original"),
              patch.object(native.packer, "hook_lower_local_lookup") as verify_hook,
              patch.object(frontend.SMC, "quoted_import_targets", wraps=frontend.SMC.quoted_import_targets) as parse,
              patch.object(Path, "read_bytes", autospec=True, side_effect=Path.read_bytes) as reads):
            native.verify_generated_tool_source(generated, inputs, expected_sources, parse_bytes=parse_bytes)
            self.assertEqual(Counter(call.args[0] for call in reads.call_args_list),
                             {root: 2, lookup: 2, runtime_path: 1})
            parse.assert_not_called()
            capable.side_effect = change_after_closure
            with self.assertRaisesRegex(RuntimeError, "^lower local lookup source changed$"):
                native.verify_generated_tool_source(generated, inputs, expected_sources, parse_bytes=parse_bytes)
            parse.assert_not_called()
            self.assertEqual(lookup.stat().st_mtime_ns, saved.st_mtime_ns)
            self.assertEqual(lookup.stat().st_size, saved.st_size)
            capable.side_effect = None
            with self.assertRaisesRegex(RuntimeError, "^lower local lookup source changed$"):
                native.verify_generated_tool_source(generated, inputs, expected_sources, parse_bytes=parse_bytes)
            self.assertEqual([call.args[1] for call in parse.call_args_list], [owner])
            verify_hook.assert_called_once()

    def test_tool_source_verification_streams_digest_without_lookup_owner(self):
        generated = self.root / "tool.gen.c"
        prefix = b"a" * (256 * 1024 - 1)
        original = prefix + b"\r\n\xf0\x9f\xa7\xad\r\xff\0\r"
        normalized = prefix + b"\n\xf0\x9f\xa7\xad\n\xff\0\n"
        generated.write_bytes(original)
        saved = generated.stat()
        expected = {"backend": {"path": native.build.GCS.rel(generated),
                               "sha256": native.sha256_bytes(normalized), "bytes": len(normalized)}}
        inputs = {"entry": "root.ouro", "sources": {}}
        with patch.object(native.build.GCS, "read_source_text_digest", side_effect=AssertionError("full read")):
            native.verify_generated_tool_source(generated, inputs, expected)
            generated.write_bytes(original[:-2] + b"\x01\r")
            os.utime(generated, ns=(saved.st_atime_ns, saved.st_mtime_ns))
            with self.assertRaisesRegex(RuntimeError, "^generated tool source digest changed$"):
                native.verify_generated_tool_source(generated, inputs, expected)

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

    def test_import_token_dispatch_tests_only_matching_prefixes(self):
        mismatches = []

        class TrackedSource(str):
            __slots__ = ()

            def startswith(self, prefix, start=0, end=None):
                if prefix in ('--', '"""', 'r#"') and self[start] != prefix[0]:
                    mismatches.append((prefix, self[start]))
                return super().startswith(prefix, start, end)

        source = TrackedSource('-- import "ignored.ouro";\n'
                               'def value := 42;\n'
                               'def literal := r#"import "unchecked.ouro";"#;\n'
                               'import "real.ouro";')
        self.assertEqual(frontend.SMC.quoted_import_targets(source, "src/root.ouro"), ["src/real.ouro"])
        self.assertEqual(mismatches, [])

    def test_braced_unicode_imports_match_literal_paths(self):
        source = r'import "caf\u{e9}.ouro", "\u{1F600}.ouro";'
        self.assertEqual(frontend.SMC.quoted_import_targets(source, "root.ouro"),
                         ["café.ouro", "😀.ouro"])

    def test_import_scan_skips_plain_string_runs_without_slicing_unrelated_literals(self):
        length_reads = 0
        slices = []

        class TrackedSource(str):
            __slots__ = ()

            def __len__(self):
                nonlocal length_reads
                length_reads += 1
                return super().__len__()

            def __getitem__(self, index):
                value = super().__getitem__(index)
                if isinstance(index, slice):
                    slices.append(value)
                return value

        source = TrackedSource('def text := "not an import";\n'
                               r'import "branch/leaf.ouro", "escaped-\u{e9}.ouro";')
        self.assertEqual(frontend.SMC.quoted_import_targets(source, "src/root.ouro"),
                         ["src/branch/leaf.ouro", "src/escaped-é.ouro"])
        self.assertEqual(length_reads, 1)
        self.assertEqual(slices, ["branch/leaf.ouro", "escaped-", "e9"])

    def test_raw_imports_preserve_bytes_and_hide_multiline_code(self):
        source = ('def text : String := r#"import "fake.ouro";\n'
                  '-- @export fake\n"#;\n'
                  'import r#"dir\\leaf.ouro"#, r#"café.ouro"#;')
        self.assertEqual(frontend.SMC.quoted_import_targets(source, "root.ouro"),
                         ["dir/leaf.ouro", "café.ouro"])

    def test_dedented_multiline_hides_imports_and_rejects_import_path(self):
        source = ('def text : String := """\r\n'
                  '  import "fake.ouro";\r\n'
                  '  """; import "real.ouro";')
        self.assertEqual(frontend.SMC.quoted_import_targets(source, "root.ouro"),
                         ["real.ouro"])
        with self.assertRaisesRegex(ValueError, "malformed quoted import"):
            frontend.SMC.quoted_import_targets('import """\n  path.ouro\n  """;', "root.ouro")
    def test_byte_literal_does_not_add_import_edges(self):
        source = (r'def bytes : List Nat := b"import \"fake.ouro\"; -- \x00";'
                  '\nimport "real.ouro";')
        self.assertEqual(frontend.SMC.quoted_import_targets(source, "root.ouro"),
                         ["real.ouro"])
        with self.assertRaisesRegex(ValueError, "malformed quoted import"):
            frontend.SMC.quoted_import_targets('import b"invalid.ouro";', "root.ouro")

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

    def test_import_scan_preserves_lexical_error_priority(self):
        for tail in ('";', ""):
            with self.subTest(tail=tail), self.assertRaisesRegex(ValueError, "^malformed Unicode escape in root.ouro$"):
                frontend.SMC.quoted_import_targets(
                    'import malformed;\ndef unrelated := "plain text \\u{D800}' + tail, "root.ouro")

    def test_import_scan_resumes_after_trailing_comma_and_semicolon(self):
        source = ('import "first.ouro", -- keep reading the group\n'
                  ' "second.ouro",;\n'
                  'def access := record_value. -- still a projection\n'
                  '  import "ignored.ouro";\n'
                  'import r#"third.ouro"#;')
        self.assertEqual(frontend.SMC.quoted_import_targets(source, "src/root.ouro"),
                         ["src/first.ouro", "src/second.ouro", "src/third.ouro"])

    def test_later_call_observes_same_mtime_import_change(self):
        root = self.source("root.ouro", 'import "one.ouro";\n')
        self.source("one.ouro", "")
        self.source("two.ouro", "")
        self.assertEqual(frontend.collect_units("root.ouro"), ["one.ouro", "root.ouro"])
        saved = root.stat()
        root.write_text('import "two.ouro";\n', encoding="utf-8")
        os.utime(root, ns=(saved.st_atime_ns, saved.st_mtime_ns))
        self.assertEqual(frontend.collect_units("root.ouro"), ["two.ouro", "root.ouro"])

    def test_cached_imports_bind_exact_bytes_and_importer_path(self):
        first = self.source("left/root.ouro", "")
        second = self.source("right/root.ouro", "")
        data = b'-- first line\rimport "dep.ouro";\r\n'
        first.write_bytes(data)
        second.write_bytes(data)
        parse_bytes = native.cached_import_parser()
        with patch.object(frontend.SMC, "quoted_import_targets",
                          wraps=frontend.SMC.quoted_import_targets) as parse:
            for directory in ("left", "right"):
                self.assertEqual(frontend.import_targets(f"{directory}/root.ouro", parse_bytes=parse_bytes),
                                 [f"{directory}/dep.ouro"])
            first.write_bytes(data.replace(b"\r\n", b"\n"))
            self.assertEqual(frontend.import_targets("left/root.ouro", parse_bytes=parse_bytes), ["left/dep.ouro"])
        self.assertEqual(Counter(call.args[1] for call in parse.call_args_list),
                         {"left/root.ouro": 2, "right/root.ouro": 1})
        for invalid, error in ((b'\xff', SystemExit), (b'import "bad', ValueError)):
            first.write_bytes(invalid)
            with self.subTest(invalid=invalid):
                with self.assertRaises(error) as expected:
                    frontend.import_targets("left/root.ouro")
                with self.assertRaises(error) as actual:
                    frontend.import_targets("left/root.ouro", parse_bytes=parse_bytes)
                self.assertEqual(str(actual.exception), str(expected.exception))

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


class RepositorySourceContracts(unittest.TestCase):
    def test_lint_style_cone_keeps_compiler_base_out(self):
        units = frontend.collect_units("tools/lint_style.ouro")
        self.assertIn("std/json.ouro", units)
        self.assertNotIn("compiler/base.ouro", units)

    def test_native_cli_check_closure_excludes_managed_backend(self):
        check_fixture = "tests/native_cli_check_tests.ouro"
        build_driver = "tools/native_build.ouro"
        host_probe = "tests/frontend_host_codegen.ouro"
        managed_backend = "compiler/native/managed_stdio_compile.ouro"
        closures = frontend.collect_units_many([check_fixture, build_driver, host_probe])
        self.assertNotIn(managed_backend, closures[check_fixture])
        self.assertIn(managed_backend, closures[build_driver])
        self.assertIn(managed_backend, closures[host_probe])

    def test_analyzer_closures_have_unique_declaration_names(self):
        from selfhost_module_cache import declaration_names

        for root in ("tools/analyze/main.ouro", "tools/analyze/drive_main.ouro"):
            with self.subTest(root=root):
                owners = {}
                for unit in frontend.collect_units(root):
                    for declaration in declaration_names(unit):
                        _kind, name = declaration.split(":", 1)
                        owners.setdefault(name, []).append(unit)
                self.assertEqual({}, {name: units for name, units in owners.items()
                                      if len(units) > 1})


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
        self.cfg.values = {"profile": "test", "jobs": 1, "cc": str(self.cc)}
        self.cfg.get_bool.side_effect = lambda _key: self.enabled
        self.cfg.path.side_effect = lambda key: self.root / key
        self.load_config = native.build.load_config
        operations = {
            "load_config": lambda _args: self.cfg,
            "output_or_empty": lambda _argv: "fixture-cc",
            "profile_cflags": lambda _cfg: list(self.flags),
            "host_link_flags": lambda: [],
            "trim_cache": lambda _cfg: None,
            "write_text_atomic": lambda path, text: path.write_text(text, encoding="utf-8"),
            "build_c_executable": self.link,
        }
        for name, operation in operations.items():
            self.stack.enter_context(patch.object(native.build, name, side_effect=operation))
        self.stack.enter_context(patch.object(native, "emit", side_effect=self.emit))
        # Emission/linking are mocked; the C-owner receipts share that boundary.
        self.stack.enter_context(patch.object(native, "build_artifacts_current", return_value=True))
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

    def emit(self, _compiler, units, _fuel, generated, **_kwargs):
        self.emissions.append(list(units))
        exports = ("cg_load_inventory", "cg_scan_chunk_request") if units[-1] == "tools/clippy/main.ouro" else ()
        getters = [
            f"static ouro_v *ouro_c{index};\n"
            f"static ouro_v *ouro_f{index}_(ouro_env *env,ouro_v *arg){{return arg;}}\n"
            f"static ouro_v *ouro_g{index}(void){{ouro_env *env=0;(void)env;"
            f"if(ouro_c{index}==0){{ouro_static_begin();"
            f"ouro_c{index}=ouro_clos(ouro_f{index}_,env);"
            f"ouro_static_end();}}return ouro_c{index};}}\n"
            for index in range(len(exports))
        ]
        names = "".join(f'case {index}:return "{name}";' for index, name in enumerate(exports))
        values = "".join(f"case {index}:return ouro_g{index}();" for index in range(len(exports)))
        generated.write_text(
            '#include "ouro_rt.h"\n' + "".join(getters)
            + f'int ouro_export_count(void){{return {len(exports)};}}\n'
            + f'const char *ouro_export_name(int i){{switch(i){{{names}default:return "";}}}}\n'
            + f'ouro_v *ouro_export_value(int i){{switch(i){{{values}default:return 0;}}}}\n',
            encoding="utf-8",
        )
        if exports:
            native.hook_compile_checked_units(generated, units)

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

    def test_installed_hit_requires_no_artifact_cache_writes(self):
        self.run_build()
        cache_dir = self.cfg.path("cache_dir").resolve()
        open_path = Path.open

        def open_read_only(path, mode="r", *args, **kwargs):
            if path.is_relative_to(cache_dir) and any(flag in mode for flag in "awx+"):
                raise PermissionError(f"read-only artifact cache: {path}")
            return open_path(path, mode, *args, **kwargs)

        with patch.object(Path, "open", open_read_only):
            self.assertEqual(self.run_build()["cache"], "installed-hit")
            self.output().write_bytes(b"corrupt")
            with self.assertRaisesRegex(PermissionError, "read-only artifact cache"):
                self.run_build()
        self.assertEqual((len(self.emissions), len(self.links)), (1, 1))

    def test_shared_cache_prepares_same_key_once(self):
        emitting, waiting, release = Event(), Event(), Event()
        cache_access = native.build.cache_access
        cache_dir = self.cfg.path("cache_dir")
        first_lock_root = None

        def observe_lock(path, *, exclusive=False, wait=True, **lock_options):
            nonlocal first_lock_root
            if exclusive and lock_options.get("lock_suffix", ".lock") == ".lock" and path.is_relative_to(cache_dir):
                if first_lock_root is None:
                    first_lock_root = path
                elif path == first_lock_root:
                    with cache_access(path, exclusive=True, wait=False) as acquired:
                        self.assertFalse(acquired)
                    waiting.set()
            return cache_access(path, exclusive=exclusive, wait=wait, **lock_options)

        def hold_emission(compiler, units, fuel, generated, **kwargs):
            if fuel == self.args.fuel:
                emitting.set()
                self.assertTrue(release.wait(60))
            return self.emit(compiler, units, fuel, generated, **kwargs)

        peer = argparse.Namespace(**{**vars(self.args), "output": self.root / "bin/peer"})
        other = argparse.Namespace(**{**vars(self.args), "output": self.root / "bin/other",
                                     "fuel": self.args.fuel + 1})
        with (patch.object(native, "emit", side_effect=hold_emission),
              patch.object(native.build, "cache_access", side_effect=observe_lock),
              ThreadPoolExecutor(max_workers=3) as pool):
            first = pool.submit(self.run_build)
            try:
                self.assertTrue(emitting.wait(20))
                same_key = pool.submit(native.build_tool, peer)
                self.assertTrue(waiting.wait(20))
                different_key = pool.submit(native.build_tool, other).result(timeout=20)
            finally:
                release.set()
            built = first.result(timeout=20)
            reused = same_key.result(timeout=20)
        self.assertEqual((built["cache"], reused["cache"], different_key["cache"]), ("miss", "hit", "miss"))
        self.assertEqual(built["key"], reused["key"])
        self.assertNotEqual(built["key"], different_key["key"])
        self.assertEqual((len(self.emissions), len(self.links)), (2, 2))

    def test_uncached_writers_share_executable_lock_through_receipt_publication(self):
        self.enabled = False
        finalizing, waiting, release = Event(), Event(), Event()
        cache_access = native.build.cache_access
        write_json = native.write_json_atomic
        receipt = Path(str(self.args.output.resolve()) + ".build.json")
        peer = argparse.Namespace(**{**vars(self.args), "output": self.output(), "fuel": self.args.fuel + 1})
        first_lock_root = None

        def observe_lock(path, *, exclusive=False, wait=True, **lock_options):
            nonlocal first_lock_root
            self.assertEqual(lock_options.get("lock_suffix"), native.OUTPUT_LOCK_SUFFIX)
            if first_lock_root is None:
                first_lock_root = path
            else:
                self.assertEqual(path, first_lock_root)
                with cache_access(path, exclusive=True, wait=False, **lock_options) as acquired:
                    waiting.set()
                    self.assertFalse(acquired)
            return cache_access(path, exclusive=exclusive, wait=wait, **lock_options)

        def link_binary(cfg, **kwargs):
            report = self.link(cfg, **kwargs)
            kwargs["output"].write_bytes(f"fixture executable {len(self.links)}".encode("ascii"))
            return report

        def write_receipt(path, data):
            if path == receipt and data["inputs"]["fuel"] == self.args.fuel:
                finalizing.set()
                self.assertTrue(release.wait(60))
            write_json(path, data)

        with (patch.object(native.build, "cache_access", side_effect=observe_lock),
              patch.object(native.build, "build_c_executable", side_effect=link_binary),
              patch.object(native, "write_json_atomic", side_effect=write_receipt),
              ThreadPoolExecutor(max_workers=2) as pool):
            first = pool.submit(self.run_build)
            try:
                self.assertTrue(finalizing.wait(20))
                second = pool.submit(native.build_tool, peer)
                self.assertTrue(waiting.wait(20))
            finally:
                release.set()
            before = first.result(timeout=20)
            after = second.result(timeout=20)
        installed = Path(str(peer.output.resolve()) + ".build.json")
        final_receipt = json.loads(installed.read_text(encoding="utf-8"))
        self.assertNotEqual(before["key"], after["key"])
        self.assertNotEqual(before["binary_sha256"], after["binary_sha256"])
        self.assertEqual(final_receipt["key"], after["key"])
        self.assertEqual(final_receipt["binary_sha256"], native.sha256_file(peer.output))

    def test_direct_writer_waits_for_parent_holding_transitive_companion(self):
        self.write("tools/leaf.ouro", b"def leaf : Nat := 1;\n")
        companions = {self.args.entry: (("tools/companion.ouro", "companion"),),
                      "tools/companion.ouro": (("tools/leaf.ouro", "leaf"),)}
        finalizing, waiting, release = Event(), Event(), Event()
        cache_access = native.build.cache_access
        write_json = native.write_json_atomic
        parent_receipt = Path(str(self.args.output.resolve()) + ".build.json")
        directory = self.args.output.resolve().parent
        suffix = ".exe" if os.name == "nt" else ""
        leaf_binary = directory / ("leaf" + suffix)
        leaf_receipt = directory / "leaf.build.json"
        peer = argparse.Namespace(**{**vars(self.args), "entry": "tools/leaf.ouro", "output": directory / "leaf",
                                     "fuel": self.args.fuel + 1})
        parent_locks = []

        def observe_lock(path, *, exclusive=False, wait=True, **lock_options):
            if lock_options.get("lock_suffix") == native.OUTPUT_LOCK_SUFFIX:
                self.assertTrue(exclusive)
                if finalizing.is_set():
                    self.assertEqual(path, leaf_binary)
                    with cache_access(path, exclusive=True, wait=False, **lock_options) as acquired:
                        waiting.set()
                        self.assertFalse(acquired)
                else:
                    parent_locks.append(path)
            return cache_access(path, exclusive=exclusive, wait=wait, **lock_options)

        def write_receipt(path, data):
            if path == parent_receipt:
                finalizing.set()
                self.assertTrue(release.wait(60))
            write_json(path, data)

        with (patch.object(native, "tool_companions", side_effect=lambda entry: companions.get(entry, ())),
              patch.object(native.build, "cache_access", side_effect=observe_lock),
              patch.object(native, "write_json_atomic", side_effect=write_receipt),
              ThreadPoolExecutor(max_workers=2) as pool):
            first = pool.submit(self.run_build)
            try:
                self.assertTrue(finalizing.wait(20))
                original_companion = json.loads(leaf_receipt.read_text(encoding="utf-8"))
                second = pool.submit(native.build_tool, peer)
                self.assertTrue(waiting.wait(20))
            finally:
                release.set()
            self.assertEqual(first.result(timeout=20)["cache"], "miss")
            rewritten_companion = second.result(timeout=20)
        self.assertEqual(parent_locks, [directory / (name + suffix) for name in ("companion", "leaf", "tool")])
        self.assertNotEqual(original_companion["key"], rewritten_companion["key"])
        self.assertEqual(rewritten_companion["inputs"]["fuel"], peer.fuel)

    def test_uncached_output_inside_cache_holds_the_shared_cache_lock(self):
        self.enabled = False
        cache_dir = self.cfg.path("cache_dir").resolve()
        self.args.output = cache_dir / "tool"
        with patch.object(native.build, "cache_access", wraps=native.build.cache_access) as access:
            self.run_build()
        self.assertEqual(access.call_args_list, [call(cache_dir),
            call(self.output().resolve(), exclusive=True, lock_suffix=native.OUTPUT_LOCK_SUFFIX,
                 resolve_target=False, lock_group=None)])

    def test_direct_build_rejects_a_companion_receipt_as_output(self):
        self.args.output = self.args.output.with_name("companion.build.json")

        def companions(entry):
            return (("tools/companion.ouro", "companion"),) if entry == self.args.entry else ()

        with (patch.object(native, "tool_companions", side_effect=companions),
              patch.object(native.build, "cache_access", wraps=native.build.cache_access) as access,
              self.assertRaisesRegex(ValueError, "conflicting tool output or receipt")):
            self.run_build()
        access.assert_called_once_with(self.cfg.path("cache_dir"))
        self.assertFalse(self.args.output.parent.exists())

    def test_case_variants_conflict_only_for_the_same_physical_output_lock(self):
        self.args.output = self.args.output.with_name("COMPANION")
        binary = self.output().resolve()
        marker = binary.with_name(f".{binary.name}{native.OUTPUT_LOCK_SUFFIX}")
        alias = binary.with_name(f".{binary.name.lower()}{native.OUTPUT_LOCK_SUFFIX}")
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
        open_path = Path.open
        cache_access = native.build.cache_access

        def companions(entry):
            return (("tools/companion.ouro", "companion"),) if entry == self.args.entry else ()

        def open_alias(path, *args, **kwargs):
            return open_path(marker if path == alias else path, *args, **kwargs)

        def probe_lock(path, *, exclusive=False, wait=True, **lock_options):
            if lock_options.get("lock_suffix") == native.OUTPUT_LOCK_SUFFIX:
                wait = False
            return cache_access(path, exclusive=exclusive, wait=wait, **lock_options)

        with (patch.object(native, "tool_companions", side_effect=companions),
              patch.object(Path, "open", open_alias),
              patch.object(native.build, "cache_access", side_effect=probe_lock),
              self.assertRaisesRegex(ValueError, "conflicting tool output")):
            self.run_build()
        self.assertEqual(self.emissions, [])
        if os.name != "nt" and not alias.exists():
            with patch.object(native, "tool_companions", side_effect=companions):
                self.assertEqual(self.run_build()["cache"], "miss")
            self.assertEqual(len(self.emissions), 2)

    def test_input_snapshot_locates_each_compiler_candidate_once(self):
        other_cc = self.write("other-cc-image", b"different C compiler", executable=True)
        self.cfg.values["cc"] = "cc"

        def snapshot(executable):
            with (patch.object(native.build.shutil, "which", side_effect={"cc": None, "gcc": str(executable)}.__getitem__) as locate,
                  patch.object(native.build, "output_or_empty", return_value="line one\nline two\nignored\n") as version):
                _, inputs = native.tool_inputs(self.args.entry, self.compiler, self.args.fuel, self.cfg)
            self.assertEqual(locate.call_args_list, [call("cc"), call("gcc")])
            version.assert_called_once_with(["gcc", "--version"])
            self.assertEqual(json.loads(inputs["cc"]), {
                "cc": "gcc", "path": str(executable), "version": ["line one", "line two"],
            })
            self.assertEqual(inputs["cc_sha256"], native.sha256_file(executable))
            return inputs

        self.assertNotEqual(snapshot(self.cc), snapshot(other_cc))

    def test_emission_rechecks_bytes_around_shared_hook_snapshot(self):
        generated = self.root / "fixture.gen.c"
        units, inputs = native.tool_inputs(self.args.entry, self.compiler, self.args.fuel, self.cfg)

        def prepare():
            return native.prepare_emission(self.compiler, units, self.args.fuel, generated,
                                           self.cfg, inputs, cache_enabled=True)

        opened = []

        def open_path(path, mode="r", *args, _open=Path.open, **kwargs):
            if path == generated:
                opened.append(mode)
            return _open(path, mode, *args, **kwargs)

        with patch.object(Path, "open", open_path):
            self.assertEqual(prepare(), "miss")
            self.assertEqual(opened, ["w", "rb", "r", "rb", "rb"])
            opened.clear()
            self.assertEqual(prepare(), "hit")
            self.assertEqual(opened, ["rb", "r", "rb"])

        baseline = generated.read_bytes()
        original_hook = native.hook_emission_scopes

        def change_after_scope_check(text, observed_units, *, installed, parse_bytes):
            result = original_hook(text, observed_units, installed=installed, parse_bytes=parse_bytes)
            self.mutate(generated)
            return result

        with patch.object(native, "hook_emission_scopes", side_effect=change_after_scope_check):
            with self.assertRaisesRegex(ValueError, "generated tool changed during emission validation"):
                prepare()
        self.assertEqual(len(self.emissions), 2)
        self.assertFalse(generated.with_suffix(".json").exists())
        self.assertEqual(prepare(), "miss")
        self.assertEqual(generated.read_bytes(), baseline)
        self.assertEqual(prepare(), "hit")

    def test_hook_install_and_check_share_parsing_only_for_exact_bytes(self):
        source = self.root / "lib/base.ouro"
        units, inputs = native.tool_inputs(self.args.entry, self.compiler, self.args.fuel, self.cfg)
        opener, scope = Path.open, native.hook_emission_scopes
        verify = native.verify_emission_hooks

        def check(change):
            generated = self.root / f"hook-test-{change}.gen.c"
            observed = []

            def scope_call(text, selected, *, installed=False, parse_bytes):
                reads = []

                def open_path(path, mode="r", *args, **kwargs):
                    if mode == "rb" and path.suffix == ".ouro":
                        reads.append(path.relative_to(self.root).as_posix())
                    return opener(path, mode, *args, **kwargs)

                with patch.object(Path, "open", open_path), \
                        patch.object(frontend.SMC, "quoted_import_targets",
                                     wraps=frontend.SMC.quoted_import_targets) as lex:
                    result = scope(text, selected, installed=installed, parse_bytes=parse_bytes)
                observed.append((installed, reads, [call.args[1] for call in lex.call_args_list]))
                return result

            def install(compiler, selected, fuel, path, *, parse_bytes):
                self.emit(compiler, selected, fuel, path, parse_bytes=parse_bytes)
                native.hook_emission_scopes(path.read_text(encoding="utf-8"), selected,
                                           parse_bytes=parse_bytes)

            def verify_installed(path, selected, *, parse_bytes):
                if change:
                    saved = source.stat()
                    source.write_bytes(source.read_bytes().replace(b"1;", b"2;"))
                    os.utime(source, ns=(saved.st_atime_ns, saved.st_mtime_ns))
                    self.assertEqual(source.stat().st_size, saved.st_size)
                    self.assertEqual(source.stat().st_mtime_ns, saved.st_mtime_ns)
                verify(path, selected, parse_bytes=parse_bytes)

            def prepare():
                return native.prepare_emission(self.compiler, units, self.args.fuel, generated,
                                               self.cfg, inputs, cache_enabled=True)

            with (patch.object(native, "emit", side_effect=install),
                  patch.object(native, "hook_emission_scopes", side_effect=scope_call),
                  patch.object(native, "verify_emission_hooks", side_effect=verify_installed)):
                if change:
                    with self.assertRaisesRegex(ValueError, "changed during emission"):
                        prepare()
                    self.assertFalse(generated.with_suffix(".json").exists())
                else:
                    self.assertEqual(prepare(), "miss")
            paths = ["tools/main.ouro", "lib/base.ouro"]
            self.assertEqual(observed, [(False, paths, paths),
                                        (True, paths, ["lib/base.ouro"] if change else [])])

        check(False)
        check(True)

    def test_native_compile_jobs_follow_config_and_memory_budget(self):
        self.enabled = False
        cases = (
            ("auto", None, {}, 16000, 20),
            ("7", None, {}, 16000, 7),
            ("7", None, {"OURO_JOBS": "12"}, 16000, 12),
            ("auto", None, {}, 5632, 4),
            ("auto", None, {}, 1024, 1),
            ("auto", None, {}, None, 2),
            ("auto", "8", {}, 1024, 8),
            ("auto", "1", {}, 16000, 1),
            ("auto", "8", {"OURO_SCHEDULER_JOBS": "4", "OURO_SCHEDULER_MEMORY_MIB": "4608"}, 1024, 4),
            ("auto", "8", {"OURO_SCHEDULER_JOBS": "4", "OURO_SCHEDULER_MEMORY_MIB": "3072"}, 16000, 1),
            ("auto", None, {"OURO_SCHEDULER_MEMORY_MIB": "3072"}, 16000, 1),
            ("auto", None, {"OURO_SCHEDULER_JOBS": "4"}, None, 4),
        )
        for project_jobs, cli_jobs, env, memory, expected in cases:
            with (self.subTest(project=project_jobs, cli=cli_jobs, env=env, memory=memory),
                  patch.dict(os.environ, env, clear=True),
                  patch.object(os, "cpu_count", return_value=20),
                  patch("local_scheduler.available_memory_mb", return_value=memory)):
                self.args.config = self.write("Ouro.seal", f"seal 1\nbuild {{\n  jobs = {project_jobs}\n}}\n".encode())
                self.args.jobs = cli_jobs
                self.cfg.values["jobs"] = self.load_config(self.args).values["jobs"]
                self.run_build()
                self.assertEqual(self.links[-1]["jobs"], expected)

    def test_removed_output_restores_verified_cache_without_emit(self):
        self.run_build()
        self.output().unlink()
        self.assertEqual(self.run_build()["cache"], "hit")
        self.assertEqual(len(self.emissions), 1)

    def test_invalid_installed_source_inventory_skips_artifact_checks_and_recovers(self):
        first = self.run_build()
        manifest = Path(str(self.args.output) + ".sources")
        expected = manifest.read_bytes()
        directory = self.cfg.path("cache_dir") / "native-tools" / first["key"]
        cached = directory / ("tool.exe" if os.name == "nt" else "tool")
        for contents in (None, b"wrong.ouro\n", b"\xff"):
            with self.subTest(contents=contents):
                if contents is None:
                    manifest.unlink()
                else:
                    manifest.write_bytes(contents)
                with patch.object(native, "build_artifacts_current", return_value=True) as verify:
                    self.args.check = True
                    self.assertFalse(self.run_build()["current"])
                    verify.assert_not_called()
                    self.args.check = False
                    self.assertEqual(self.run_build()["cache"], "hit")
                    self.assertEqual([call.args[4] for call in verify.call_args_list], [cached])
                self.assertEqual(manifest.read_bytes(), expected)
        self.assertEqual(len(self.emissions), 1)
        self.assertEqual(len(self.links), 1)

    def test_installed_source_inventory_is_rechecked_after_artifact_checks(self):
        self.run_build()
        manifest = Path(str(self.args.output) + ".sources")

        def change_inventory(*_args, **_kwargs):
            self.mutate(manifest)
            return True

        self.args.check = True
        with patch.object(native, "build_artifacts_current", side_effect=change_inventory) as verify:
            self.assertFalse(self.run_build()["current"])
            verify.assert_called_once()

    def test_check_rejects_output_evidence_removed_during_companion_checks(self):
        def companions(entry):
            return (("tools/companion.ouro", "companion"),) if entry == self.args.entry else ()

        binary = self.output().resolve()
        manifest = Path(str(self.args.output.resolve()) + ".sources")

        with patch.object(native, "tool_companions", side_effect=companions):
            for path in (binary, manifest):
                with self.subTest(path=path):
                    self.args.check = False
                    self.run_build()
                    self.args.check = True

                    def remove_evidence(_directory, _cfg, _inputs, _record, checked_binary, *, removed=path, **_kwargs):
                        if checked_binary != binary:
                            removed.unlink()
                        return True

                    with (patch.object(native, "build_artifacts_current", side_effect=remove_evidence) as verify,
                          patch.object(native.build, "cache_access", wraps=native.build.cache_access) as access):
                        self.assertFalse(self.run_build()["current"])
                    self.assertEqual(verify.call_count, 2)
                    access.assert_called_once_with(self.cfg.path("cache_dir"))

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

    def test_changed_binary_after_publish_leaves_receipt_unchanged(self):
        self.run_build()
        receipt = Path(str(self.args.output) + ".build.json")
        previous = receipt.read_bytes()
        self.output().unlink()
        publish = native.publish

        def replace_published_binary(binary, output):
            publish(binary, output)
            output.write_bytes(b"different fixture executable")

        with (patch.object(native, "publish", side_effect=replace_published_binary),
              self.assertRaisesRegex(ValueError, "published tool binary changed before completion")):
            self.run_build()
        self.assertEqual(receipt.read_bytes(), previous)

    def test_corrupt_receipts_or_cache_never_count_as_hits(self):
        first = self.run_build()
        receipt = Path(str(self.args.output) + ".build.json")
        receipt.write_text("{", encoding="utf-8")
        self.assertEqual(self.run_build()["cache"], "hit")
        directory = self.cfg.path("cache_dir") / "native-tools" / first["key"]
        self.output().unlink()
        (directory / "tool.json").write_text("[]", encoding="utf-8")
        rebuilt = self.run_build()
        self.assertEqual((rebuilt["cache"], rebuilt["emission_cache"]), ("miss", "hit"))
        self.output().unlink()
        (directory / ("tool.exe" if os.name == "nt" else "tool")).write_bytes(b"damaged")
        rebuilt = self.run_build()
        self.assertEqual((rebuilt["cache"], rebuilt["emission_cache"]), ("miss", "hit"))
        self.assertEqual(len(self.emissions), 1)
        self.assertEqual(len(self.links), 3)

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

    def test_shard_rejection_preserves_installed_output_and_receipt(self):
        self.run_build()
        receipt = Path(str(self.args.output) + ".build.json")
        old_receipt, old_binary = receipt.read_bytes(), self.output().read_bytes()
        self.mutate(self.root / "lib/base.ouro")
        links = len(self.links)
        with patch.object(native.build.GCS, "materialize_generated_c_shards", side_effect=ValueError("invalid flat backend")):
            with self.assertRaisesRegex(ValueError, "invalid flat backend"):
                self.run_build()
        self.assertEqual(len(self.links), links)
        self.assertEqual(receipt.read_bytes(), old_receipt)
        self.assertEqual(self.output().read_bytes(), old_binary)

    def test_shard_object_evidence_failure_is_not_published(self):
        self.run_build()
        receipt = Path(str(self.args.output) + ".build.json")
        old_receipt, old_binary = receipt.read_bytes(), self.output().read_bytes()
        self.mutate(self.root / "lib/base.ouro")
        with patch.object(native, "build_artifacts_current", return_value=False):
            with self.assertRaisesRegex(ValueError, "shard/object/dependency/link evidence"):
                self.run_build()
        self.assertEqual(receipt.read_bytes(), old_receipt)
        self.assertEqual(self.output().read_bytes(), old_binary)

    def test_source_change_during_compilation_is_not_published(self):
        self.run_build()
        receipt = Path(str(self.args.output) + ".build.json")
        old_receipt, old_binary = receipt.read_bytes(), self.output().read_bytes()
        self.mutate(self.root / "lib/base.ouro")
        def changing_link(cfg, **kwargs):
            result = self.link(cfg, **kwargs)
            self.mutate(self.root / "lib/base.ouro")
            return result
        with patch.object(native.build, "build_c_executable", side_effect=changing_link):
            with self.assertRaisesRegex(ValueError, "changed during preparation"):
                self.run_build()
        self.assertEqual(receipt.read_bytes(), old_receipt)
        self.assertEqual(self.output().read_bytes(), old_binary)

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
            with patch.object(frontend.SMC, "quoted_import_targets",
                              wraps=frontend.SMC.quoted_import_targets) as parse:
                self.assertFalse(self.run_build()["current"])
            self.assertEqual(Counter(call.args[1] for call in parse.call_args_list),
                             {"tools/main.ouro": 1, "tools/companion.ouro": 1, "lib/base.ouro": 1})
            self.assertEqual(len(self.emissions), 2)

    def test_companion_check_rereads_changed_import_at_same_mtime(self):
        shared = self.write("lib/base.ouro", b'import "leaf.ouro";')
        self.write("lib/leaf.ouro", b"")
        saved = shared.stat()

        def check(_directory, _cfg, _inputs, _record, binary, **_kwargs):
            if binary == self.output():
                shared.write_bytes(b'import "lost.ouro";')
                os.utime(shared, ns=(saved.st_atime_ns, saved.st_mtime_ns))
            return True

        def mapping(entry):
            return (("tools/companion.ouro", "companion"),) if entry == "tools/main.ouro" else ()

        with patch.object(native, "tool_companions", side_effect=mapping):
            self.run_build()
            self.args.check = True
            with patch.object(native, "build_artifacts_current", side_effect=check), \
                    self.assertRaisesRegex(SystemExit, r"missing lib/lost\.ouro"):
                self.run_build()

    def test_ci_copy_reuses_import_parsing_and_detects_drift_before_copying_companion(self):
        import ci_gate
        from ourosmith import native as receipts

        companions = {"tools/main.ouro": (("tools/companion.ouro", "companion"),)}
        suffix = ".exe" if os.name == "nt" else ""
        shared = self.root / "lib/base.ouro"
        original = shared.read_bytes()
        saved = shared.stat()
        copy = ci_gate.shutil.copy2

        def copy_with_drift(source, destination):
            copied = copy(source, destination)
            if source == self.output():
                shared.write_bytes(original.replace(b"1;", b"2;"))
                os.utime(shared, ns=(saved.st_atime_ns, saved.st_mtime_ns))
            return copied

        target = self.root / "installed/tool"
        companion = target.with_name("companion" + suffix)
        with (patch.object(native, "tool_companions", side_effect=lambda entry: companions.get(entry, ())),
              patch.object(ci_gate, "ROOT", self.root), patch.object(receipts, "ROOT", self.root)):
            self.run_build()
            with (patch.object(ci_gate.shutil, "copy2", side_effect=copy_with_drift),
                  self.assertRaisesRegex(ValueError, "receipt is missing, incomplete, or stale: .*companion")):
                ci_gate.copy_prepared_tool(self.args.output, target, entry=self.args.entry, compiler=self.compiler)
            self.assertFalse(companion.exists())
            shared.write_bytes(original)
            os.utime(shared, ns=(saved.st_atime_ns, saved.st_mtime_ns))
            with patch.object(frontend.SMC, "quoted_import_targets", wraps=frontend.SMC.quoted_import_targets) as lex:
                ci_gate.copy_prepared_tool(self.args.output, target, entry=self.args.entry, compiler=self.compiler)
            self.assertCountEqual([call.args[1] for call in lex.call_args_list],
                                  ["lib/base.ouro", "tools/main.ouro", "tools/companion.ouro"])
        for name in ("tool", "companion"):
            for extension in (suffix, ".build.json", ".sources"):
                filename = name + extension
                self.assertEqual(target.with_name(filename).read_bytes(),
                                 self.args.output.with_name(filename).read_bytes())

    def test_lint_companions_include_transitive_sources_and_validate_each_binary(self):
        self.stack.enter_context(patch.object(native, "embed_windows_manifest"))
        for entry in native.tool_roots("tools/lint.ouro"):
            if entry == "tools/lint.ouro":
                self.write(entry, b'import "../lib/base.ouro";\n')
            elif entry == "tools/clippy/main.ouro":
                self.write(entry, b"def cg_load_inventory : Nat := 1;\ndef cg_scan_chunk_request : Nat := 1;\n")
            else:
                self.write(entry, b"def value : Nat := 1;\n")
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
        Path(str(self.args.output) + ".sources").unlink()
        with patch.object(native, "build_artifacts_current", return_value=True) as verify:
            self.assertFalse(self.run_build()["current"])
            self.assertEqual([call.args[4].stem for call in verify.call_args_list],
                             ["ouro-lint-style", "ouro-clippy-grade-firewall", "ouro-clippy-structural"])


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
        executable = "same.exe" if os.name == "nt" else "same"
        lock = f".{executable}{native.OUTPUT_LOCK_SUFFIX}"
        for output in ("same", "same.sources", "same.build.json", lock):
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
        def operation(_args, *, parse_bytes):
            self.assertTrue(callable(parse_bytes))
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

    def test_batch_import_parser_reuses_matches_and_rereads_changed_inputs(self):
        shared = self.root / "shared.ouro"
        dependency = self.root / "leaf.ouro"
        for entry, _output in self.pairs("a", "b", "c").tool:
            (self.root / entry).write_bytes(b'import "shared.ouro";\n')
        dependency.write_bytes(b"")
        argv = ["--compiler", str(self.args.compiler)]
        for entry, output in self.args.tool:
            argv.extend(["--tool", entry, output])

        for verify_published in (False, True):
            with self.subTest(verify_published=verify_published):
                shared.write_bytes(b"-- comment 12345678\n")
                saved = shared.stat()
                observed = []

                def operation(request, *, parse_bytes, observed=observed, saved=saved):
                    graphs, _ = frontend.capture_unit_inputs([request.entry], parse_bytes=parse_bytes)
                    observed.append(graphs[request.entry])
                    if request.entry == "b.ouro":
                        shared.write_bytes(b'import "leaf.ouro";\n')
                        os.utime(shared, ns=(saved.st_atime_ns, saved.st_mtime_ns))
                    return {"current": True}

                with (patch.object(frontend, "ROOT", self.root),
                      patch.object(native, "configure_native_stack"),
                      patch.object(native, "verify_published_tool" if verify_published else "build_tool",
                                   side_effect=operation),
                      patch.object(frontend, "import_targets", wraps=frontend.import_targets) as reads,
                      patch.object(frontend.SMC, "quoted_import_targets",
                                   wraps=frontend.SMC.quoted_import_targets) as parses):
                    command = [*argv, "--verify-published"] if verify_published else argv
                    self.assertEqual(native.main(command), 0)
                self.assertEqual(observed, [["shared.ouro", "a.ouro"], ["shared.ouro", "b.ouro"],
                                            ["leaf.ouro", "shared.ouro", "c.ouro"]])
                self.assertEqual(shared.stat().st_mtime_ns, saved.st_mtime_ns)
                self.assertEqual(shared.stat().st_size, saved.st_size)
                self.assertEqual([call.args[0] for call in reads.call_args_list].count("shared.ouro"), 3)
                self.assertEqual([call.args[1] for call in parses.call_args_list].count("shared.ouro"), 2)

    def test_published_tool_verifies_companion_bytes_and_current_inputs(self):
        entry, companion = "tools/fmt.ouro", "tools/fix/check_main.ouro"
        self.args.entry, self.args.output = entry, self.root / "ouro-fmt"
        compiler_inputs = {source: {"entry": source, "sources": {source: "source-hash"}, "fuel": 60000}
                           for source in (entry, companion)}

        def install(source, name):
            output = self.root / name
            binary = output.with_name(output.name + ".exe") if os.name == "nt" else output
            binary.write_bytes(source.encode("utf-8"))
            binary.chmod(0o700)
            inputs = compiler_inputs[source]
            native.write_json_atomic(output.with_name(output.name + ".build.json"), {
                "kind": native.KIND, "inputs": inputs, "key": native.hash_json(inputs), "cache": "miss",
                "binary_sha256": native.sha256_file(binary),
            })
            output.with_name(output.name + ".sources").write_text(source + "\n", encoding="utf-8")
            return binary

        install(entry, "ouro-fmt")
        child = install(companion, "ouro-fix-check")
        with (patch.object(native.build, "load_config"), patch.object(frontend, "ouro1_usable", return_value=True),
              patch.object(native, "tool_inputs", side_effect=lambda source, *_a, **_kw: ([source], compiler_inputs[source]))):
            self.assertTrue(native.verify_published_tool(self.args)["current"])
            manifest = self.root / "ouro-fix-check.sources"
            manifest.write_text(companion, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "receipt differs from current tools/fix/check_main.ouro"):
                native.verify_published_tool(self.args)
            manifest.write_text(companion + "\n", encoding="utf-8")
            compiler_inputs[companion] = {**compiler_inputs[companion], "fuel": 16000}
            with self.assertRaisesRegex(ValueError, "receipt differs from current tools/fix/check_main.ouro"):
                native.verify_published_tool(self.args)
            compiler_inputs[companion]["fuel"] = 60000
            child.write_bytes(b"replacement")
            with self.assertRaisesRegex(ValueError, "receipt differs from current tools/fix/check_main.ouro"):
                native.verify_published_tool(self.args)


if __name__ == "__main__":
    unittest.main()
