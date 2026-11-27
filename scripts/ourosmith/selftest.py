"""Harness regressions. These checks require no compiler or downloaded packages."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ourosmith import ROOT, generator_hash
from ourosmith.limits import RunResult, clean_env, run_limited
from ourosmith.report import Report


def report():
    value = Report(profile="pr", generator_hash="selftest", seeds=[1], command="selftest")
    value.layer("kernel").cases = 1
    return value


def migration_archive():
    import hashlib
    from ourosmith.migration import KIND, contracts, legacy_categories, refresh

    legacy = "test"
    manifest = ("B.check.1\tbad.ouro\tcheck\tfail\t1\texpected domain\n"
                "REC.B.check.ambiguous_literal\trecords/bad/ambiguous_literal.ouro\tcheck\tfail\t1\tOURO-REC-003\n"
                "REC.B.check.update_pending\trecords/bad/update_pending.ouro\tcheck\tfail\t1\tOURO-REC-003\n")
    paths = sorted(f"{legacy}/suite/{name}" for name in (
        "manifest.tsv", "bad.ouro", "lsp/messy.ouro",
        "records/bad/ambiguous_literal.ouro", "records/bad/update_pending.ouro"))
    snapshot = {"revision": "a" * 40, "tree": "b" * 40,
                "git_blobs": {path: "c" * 40 for path in paths}, "files_sha256": {path: "d" * 64 for path in paths}}
    source = {"head": snapshot["revision"], "source_sha256": "e" * 64, "files": len(paths)}
    categories, count = legacy_categories(paths, manifest)
    value = {"fingerprint": "f" * 64, "sections": {"provenance": {"source": source}}, "summary": {"layers": {}}}
    external = set()
    for row in categories:
        for strategy in row["strategies"]:
            if strategy.startswith("external/"):
                external.add(strategy)
            else:
                layer, group, name = strategy.split("/", 2)
                value["summary"]["layers"].setdefault(layer, {}).setdefault("coverage", {}).setdefault(group, {})[name] = 1
    coverage = value["summary"]["layers"]["surface"]["coverage"]
    coverage.setdefault("features", {})["form:record"] = 1
    external.add("external/ci/ergonomics")
    matrix = {"kind": KIND, "contracts": contracts.CONTRACT_KIND, "source_manifest_sha256": hashlib.sha256(manifest.encode()).hexdigest(),
              "recoverability": {**snapshot, "status": [], "tracked": len(paths)}, "pre_retirement_source": source,
              "legacy_files": paths, "manifest_rows": count, "categories": categories, "retired": False,
              "deletion_ready": True, "evidence_problems": []}
    with patch("ourosmith.migration.external_evidence", return_value=external), \
         patch("ourosmith.migration.references", return_value=([], [])), patch("ourosmith.migration.gates", return_value=[]):
        refresh(matrix, value, None)
    return matrix, snapshot, manifest, value, external


class HarnessTests(unittest.TestCase):
    def test_checked_snapshot_preserves_all_tokens_and_rejects_bad_framing(self):
        from ourosmith.surface.run import checked_program_snapshot

        work = ROOT / "_build/smith/selftest"
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as directory:
            path = Path(directory) / "program.checked"
            first = "ouro.checked-program.v1\n1 6 83 116 114 105 110 103 0 255 \n"
            second = first.replace("0 255", "0 254")
            for value in (first, second):
                path.write_bytes(value.encode("ascii"))
                self.assertEqual(checked_program_snapshot(path), value)
            self.assertNotEqual(first, second)
            for value in (b"{}", b"ouro.checked-program.v2\n0 0 \n",
                          b"ouro.checked-program.v1\n0 0 ",
                          b"ouro.checked-program.v1\n0 01 \n",
                          b"ouro.checked-program.v1\n-1 0 \n",
                          b"ouro.checked-program.v1\n0 \xff \n"):
                path.write_bytes(value)
                with self.assertRaises((UnicodeError, ValueError)):
                    checked_program_snapshot(path)

    def test_native_tool_selection_is_exact_and_fail_closed(self):
        from ourosmith.host import TOOLS, ensure_tools

        with patch("ourosmith.host.build_command", return_value=None) as build, \
             patch("ourosmith.host.binary") as binary:
            self.assertIsNone(ensure_tools(Path("_build/smith-selection"), required=("collect", "test")))
            self.assertEqual(build.call_count, 3)
            self.assertEqual([call.args[0][2] for call in build.call_args_list[1:]],
                             ["tools/collect.ouro", "tools/test/main.ouro"])
            self.assertEqual([call.args[0] for call in binary.call_args_list], ["ouro-collect", "ouro-test"])
            build.reset_mock()
            binary.reset_mock()
            self.assertIsNone(ensure_tools(Path("_build/smith-selection")))
            self.assertEqual(binary.call_count, len(TOOLS))
            build.reset_mock()
            for required in ((), ("unknown",), ("collect", "unknown"), ("test", "test")):
                with self.subTest(required=required), self.assertRaises(ValueError):
                    ensure_tools(Path("_build/smith-selection"), required=required)
            build.assert_not_called()
        with patch("ourosmith.host.build_command", return_value="compiler failed") as build, \
             patch("ourosmith.host.binary") as binary:
            self.assertEqual(ensure_tools(Path("_build/smith-selection")), "compiler failed")
            self.assertEqual(build.call_count, 1)
            binary.assert_not_called()

    def test_manifest_prepares_only_its_native_dependencies(self):
        from ourosmith.native_inputs import run_manifest

        with patch("ourosmith.host.ensure_tools", return_value="build failed") as ensure, \
             patch("ourosmith.native_inputs.prepare") as prepare, contextlib.redirect_stdout(io.StringIO()):
            out = ROOT / "_build/manifest-selection"
            self.assertEqual(run_manifest(SimpleNamespace(seed=1, out=out)), 1)
            ensure.assert_called_once_with(out / "build", required=("collect", "test"))
            prepare.assert_not_called()

    def test_manifest_tool_build_reuses_shell_for_environment(self):
        from ourosmith import host

        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            shells = [out / name / "sh" for name in ("first", "second")]
            result = SimpleNamespace(ok=True, stdout="", stderr="")
            with (patch.object(host, "ensure_compiler", return_value=None), patch.object(host, "binary"),
                  patch.object(host, "shell", side_effect=[*shells, *shells]) as discover,
                  patch.object(host, "run_limited", return_value=result) as launch):
                self.assertIsNone(host.ensure_tools(out, required=("collect", "test")))

            self.assertEqual(discover.call_count, 2)
            self.assertEqual(launch.call_count, 2)
            for call, sh in zip(launch.call_args_list, shells, strict=True):
                self.assertEqual(call.args[0][0], str(sh))
                child = call.kwargs["env"]
                self.assertEqual(child["OURO_POSIX_SH"], sh.as_posix())
                self.assertEqual(child["PATH"].split(os.pathsep)[1], str(sh.parent))

    def test_native_builds_honor_cache_disable(self):
        from ourosmith.host import environment

        with patch.dict(os.environ, {"OURO_CACHE": "0", "OURO_CCACHE": "disabled"}):
            env = environment(jobs=1, build=True)
            self.assertEqual(env["OURO_CACHE"], "0")
            self.assertEqual(env["OURO_CCACHE"], "disabled")

    def test_native_build_passes_process_memory_limit_to_workers(self):
        from local_scheduler import MEMORY_ENV, Allocation
        from ourosmith.host import BUILD_MEMORY_MB, build_command

        with tempfile.TemporaryDirectory() as directory, \
             patch("ourosmith.host.environment", side_effect=lambda **_kwargs: {}), \
             patch("ourosmith.host.run_limited", return_value=SimpleNamespace(ok=True, stdout="", stderr="")) as run:
            log = Path(directory) / "build.log"
            for inherited, allocation, expected in (
                    ({}, None, BUILD_MEMORY_MB),
                    ({MEMORY_ENV: "2560"}, None, 2560),
                    ({MEMORY_ENV: "8192"}, Allocation(4, 4608), 4608)):
                with self.subTest(inherited=inherited, allocation=allocation), \
                     patch.dict(os.environ, inherited, clear=True):
                    self.assertIsNone(build_command(["compiler"], log, allocation=allocation))
                self.assertEqual(run.call_args.kwargs["memory_mb"], expected)
                self.assertEqual(run.call_args.kwargs["env"].get(MEMORY_ENV), str(expected))

    def test_native_tool_entries_follow_owned_layout(self):
        from ourosmith.host import TOOLS, tool_entry

        for tool in TOOLS:
            with self.subTest(tool=tool):
                entry = tool_entry(tool)
                self.assertTrue((ROOT / entry).is_file(), entry)
                self.assertEqual(entry.count("/"), 2 if tool in {"fix", "test"} else 1)
        with self.assertRaises(ValueError):
            tool_entry("unknown")

    def test_collector_preserves_unit_paths_across_recipe_cwd_changes(self):
        from frontend_regen import collect_units

        with tempfile.TemporaryDirectory(dir=ROOT / "_build") as directory:
            entry = Path(directory) / "main.ouro"
            dependency = entry.with_name("dependency.ouro")
            entry.write_text('import "dependency.ouro";\ndef main : Nat := value;\n')
            dependency.write_text('def value : Nat := 1;\n')
            units = collect_units(entry.as_posix())
            self.assertEqual(units, [dependency.as_posix(), entry.as_posix()])
            self.assertTrue(all((entry.parent / unit).is_file() for unit in units))
            self.assertEqual(collect_units(entry.relative_to(ROOT).as_posix()),
                             [dependency.relative_to(ROOT).as_posix(), entry.relative_to(ROOT).as_posix()])

    def test_constructor_inventory_ignores_comment_and_string_delimiters(self):
        from ourosmith.surface import inventory

        source = ('-- inductive Expr : Type := | CommentFake : Expr;\n'
                  'def text : String := "inductive Expr : Type := | StringFake : Expr;";\n'
                  'inductive Expr : Type :=\n'
                  '  | EVar : Nat -> Expr\n'
                  '  -- a delimiter inside a comment; | Fake : Expr;\n'
                  '  | ESpan : Nat -> Nat -> Expr -> Expr;\n'
                  'inductive Other : Type := | OtherValue : Other;\n')
        with tempfile.TemporaryDirectory(dir=ROOT / "_build") as directory:
            root = Path(directory)
            path = root / "ast.ouro"
            path.write_text(source, encoding="utf-8")
            with patch.object(inventory, "ROOT", root):
                read = inventory.constructor_reader("ast.ouro")
                self.assertEqual(read("Expr"), ["EVar", "ESpan"])
                self.assertEqual(read("Other"), ["OtherValue"])
                with self.assertRaisesRegex(ValueError, "cannot extract Missing"):
                    read("Missing")
                saved = path.stat()
                path.write_text(source.replace("EVar", "EUse"), encoding="utf-8")
                os.utime(path, ns=(saved.st_atime_ns, saved.st_mtime_ns))
                self.assertEqual(inventory.constructors("ast.ouro", "Expr"), ["EUse", "ESpan"])

    def test_inventory_check_generates_strategy_contract_once(self):
        import ouro_smith as smith
        from ourosmith import inventory

        contracts = inventory.code_strategies()
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            for write, registered, exit_code, generations in (
                (False, contracts, 0, (0, 1)), (False, None, 1, (1, 0)), (True, contracts, 0, (1, 1)),
            ):
                args = SimpleNamespace(out=directory, write=write, report=None, verbose=False)
                with (self.subTest(write=write, registered=registered is not None),
                      patch.object(smith, "load_strategies", return_value=registered),
                      patch.object(smith, "write_strategies") as publish,
                      patch.object(smith, "code_strategies", return_value=contracts) as fallback,
                      patch.object(inventory, "code_strategies", return_value=contracts) as checked):
                    self.assertEqual(smith.cmd_inventory(args), exit_code)
                    self.assertEqual((fallback.call_count, checked.call_count), generations)
                    if write:
                        publish.assert_called_once_with(contracts)
                    else:
                        publish.assert_not_called()

    def test_source_parser_uses_bootstrap_components(self):
        from frontend_regen import collect_units
        from ourosmith.surface.inventory import constructors
        from ourosmith.surface.parser import EXPRS, MODES

        units = collect_units("compiler/parser.ouro")
        for path in ("parser_min.ouro", "parse_a.ouro", "parse_b.ouro"):
            self.assertEqual(sum(Path(unit).name == path for unit in units), 1)
        self.assertFalse((ROOT / "compiler/parser_abi.ouro").exists())
        self.assertEqual(list(EXPRS), constructors("compiler/ast.ouro", "Expr"))
        self.assertEqual(MODES, constructors("compiler/parser_min.ouro", "Mode"))

    def test_gate_compatibility_paths(self):
        import docs_examples_gate as docs
        import github_project_gate as project
        import github_workflow_gate as workflow
        from repo_support import NativeGateOutcome

        wrappers = ((docs, "OURO_DOCS_EXAMPLES_GATE_WORK", "docs", "docs-examples-gate.json"),
                    (project, "OURO_GITHUB_PROJECT_GATE_WORK", "project", "github-project-gate.json"),
                    (workflow, "OURO_GITHUB_WORKFLOW_GATE_WORK", "workflow", "github-workflow-gate.json"))
        for module, variable, profile, filename in wrappers:
            for argv, environ, work, report_path, scan in (
                ([], {}, None, None, None),
                (["--work=chosen", "--report=reports/custom.json"], {variable: "ignored"}, "chosen", "reports/custom.json", None),
                ([], {variable: "from-env", "OURO_REPO_GATE_ROOT": " subtree "}, "from-env", None, "subtree"),
                (["--report="], {"OURO_REPO_GATE_ROOT": "   "}, None, None, None),
            ):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory).resolve()
                    chosen_work = root / (work or {"docs": "_build/docs_examples_gate", "project": "_build/github_project_gate", "workflow": "_build/github_workflow_gate"}[profile])
                    outcome = NativeGateOutcome(0, 0, (), chosen_work / "report.json", {"issues": []}, True, None)
                    writer = "write_json_atomic_compact" if module is workflow else "write_json_atomic"
                    with patch.object(module, "ROOT", root), patch.dict(os.environ, environ, clear=True), \
                         patch.object(module, "run_native_repo_gate", return_value=outcome) as delegate, \
                         patch.object(module, writer) as write, contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(module.main(argv), 0)
                        delegate.assert_called_once_with(checkout_root=root, scan_root=root / scan if scan else root,
                                                         profile=profile + "-native", native_out=chosen_work / ("native-" + profile))
                        self.assertEqual(write.call_args.args[0], root / report_path if report_path else chosen_work / filename)
            for argv, environ in ((["--work=../escape"], {}), (["--report=../escape"], {}),
                                  ([], {"OURO_REPO_GATE_ROOT": "../escape"}), (["--work="], {}),
                                  (["--unknown"], {}), (["--report"], {})):
                with patch.dict(os.environ, environ, clear=True), \
                     patch.object(module, "run_native_repo_gate") as delegate, \
                     contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    module.main(argv)
                self.assertEqual(error.exception.code, 2)
                delegate.assert_not_called()

    def test_large_recipe_keeps_runtime_deadline(self):
        from ourosmith.surface.analyzer_lines import program, run_checks as analyzer_checks
        from ourosmith.surface.library import run_expressions
        from ourosmith.surface.run import StepFailure, SurfaceRunner

        recipes = ((program(1)[1], analyzer_checks),
                   ("saved\n", lambda run, directory: run_expressions(
                       run, directory, "stdlib_protocols", [('"saved"', "saved")], ["std/json.ouro"], "stdlib-protocols")))
        expected = ""
        hanging = False
        preparation_hanging = False
        calls = []

        def execute(argv, *, timeout_s, **_kwargs):
            phase = ("check" if "check" in argv else "emit-c" if argv[0] == "compiler" else
                     "native-compile" if any(arg.endswith("/surface/native_compile.py") for arg in argv) else "native-run")
            calls.append((phase, timeout_s))
            duration = (901 if preparation_hanging else 61) if phase != "native-run" else 21 if hanging else 1
            status = "timeout" if duration > timeout_s else "ok"
            stdout = "CHECK_OK\n" if phase == "check" else expected if phase == "native-run" else ""
            return RunResult(status, 0 if status == "ok" else 1, stdout, "", duration, 64)

        work = ROOT / "_build/smith/selftest"
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as directory, \
             patch.object(SurfaceRunner, "tool", return_value=Path("compiler")), \
             patch("frontend_regen.collect_units", return_value=[]), \
             patch("ourosmith.surface.run.run_limited", side_effect=execute):
            runner = SurfaceRunner(report(), Path(directory), [1], timeout=20)
            runner.seed, runner.cc = 1, "cc"
            for recipe_expected, run_checks in recipes:
                expected = recipe_expected
                calls.clear()
                hanging = False
                run_checks(runner, Path(directory))
                self.assertEqual(calls, [("check", 900), ("emit-c", 900), ("native-compile", 900), ("native-run", 20)])
                self.assertEqual(runner.timeout, 20)
                with self.assertRaises(StepFailure) as ordinary:
                    runner.check(Path(directory) / "main.ouro", artifact=False)
                self.assertEqual(ordinary.exception.classification, "timeout")
                hanging = True
                with self.assertRaises(StepFailure) as runtime:
                    run_checks(runner, Path(directory))
                self.assertEqual((runtime.exception.prop, runtime.exception.classification), ("native-run", "timeout"))
                preparation_hanging = True
                with self.assertRaises(StepFailure) as preparation:
                    run_checks(runner, Path(directory))
                self.assertEqual((preparation.exception.prop, preparation.exception.classification), ("check", "timeout"))
                preparation_hanging = False

    def test_analyzer_core_pool_uses_platform_memory_policy(self):
        import analyze_core_checks as checks

        for platform, ceiling, budget, jobs, memory in (
            ("nt", 20, 3072, 10, 3072), ("nt", 2, 3072, 2, 3072),
            ("posix", 2, 6015, 1, 2944), ("posix", 2, 6016, 2, 2944),
        ):
            with tempfile.TemporaryDirectory() as directory, \
                 patch.dict(os.environ, {checks.JOBS_ENV: str(ceiling)}), \
                 patch.object(checks, "os", SimpleNamespace(name=platform)), \
                 patch.object(checks, "sys", SimpleNamespace(platform="linux")), \
                 patch.object(checks, "available_memory_mib", return_value=budget), \
                 patch.object(checks, "command_environment", return_value={"OURO_C_BUILD_DIR": directory}), \
                 patch.object(checks, "shell", return_value=Path("sh")), \
                 patch.object(checks, "run_limited", return_value=RunResult("ok", 0, "CHECK_OK\n", "", 0, 0)) as execute, \
                 contextlib.redirect_stdout(io.StringIO()):
                for name in ("ouro1", "ouro-collect"):
                    (Path(directory) / name).touch()
                report = checks.run_checks([f"file-{n}.ouro" for n in range(12)], Path(directory), 99)
                self.assertTrue(report["pass"])
                self.assertEqual(report["jobs"], jobs)
                self.assertEqual(report["wrapper_launches"], 12)
                self.assertTrue(all(call.kwargs["memory_mb"] == memory for call in execute.call_args_list))
                if platform == "posix" and jobs == 2:
                    self.assertNotIn("OURO_PREPARED_COLLECTOR", execute.call_args_list[0].kwargs["env"])
                    for call in execute.call_args_list[1:]:
                        self.assertEqual(call.kwargs["env"]["OURO_PREPARED_COLLECTOR"],
                                         (Path(directory) / "ouro-collect").as_posix())

    def test_analyzer_core_pool_orders_results_and_preserves_failures(self):
        import threading
        import analyze_core_checks as checks

        files = ["warm.ouro", "slow.ouro", "bad.ouro", "later.ouro"]
        for failure in (RunResult("ok", 1, "", "rejected", 1, 2),
                        RunResult("timeout", 1, "", "timeout", 1, 2),
                        RunResult("ok", 0xC0000005, "", "crash", 1, 2)):
            warmed, overtaken = threading.Event(), threading.Event()
            commands = []

            def execute(argv, commands=commands, warmed=warmed, overtaken=overtaken, failure=failure, **kwargs):
                commands.append(argv)
                path = argv[3]
                self.assertEqual(argv[1:3], ["scripts/ouro1.sh", "check"])
                self.assertEqual(argv[4], "200000")
                self.assertEqual(kwargs["timeout_s"], 300)
                if path == files[0]:
                    self.assertEqual(len(commands), 1)
                    warmed.set()
                else:
                    self.assertTrue(warmed.is_set())
                    if path == files[1]:
                        self.assertTrue(overtaken.wait(timeout=5))
                    elif path == files[2]:
                        overtaken.set()
                        return failure
                return RunResult("ok", 0, "CHECK_OK\n", "", 1, 2)

            with tempfile.TemporaryDirectory() as directory, \
                 patch.object(checks, "os", SimpleNamespace(name="nt", environ={})), \
                 patch.object(checks, "environment", return_value={}), \
                 patch.object(checks, "shell", return_value=Path("sh")), \
                 patch.object(checks, "run_limited", side_effect=execute), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                report = checks.run_checks(files, Path(directory), 10)
                self.assertEqual([row["file"] for row in report["checks"]], files)
                self.assertEqual(report["wrapper_launches"], len(files))
                self.assertEqual(sorted(command[3] for command in commands), sorted(files))
                self.assertFalse(report["pass"])
                self.assertEqual(report["checks"][2]["resource"], failure.classify())
                self.assertTrue(all(Path(row["log"]).is_file() for row in report["checks"]))
                self.assertEqual([line.split()[2] for line in output.getvalue().splitlines()], files)
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(checks, "environment", return_value={}), \
             patch.object(checks, "shell", return_value=Path("sh")), \
             patch.object(checks, "run_limited", return_value=RunResult("ok", 1, "", "warm-up failed", 1, 2)) as execute, \
             patch.object(checks, "ThreadPoolExecutor") as pool, \
             contextlib.redirect_stdout(io.StringIO()):
            report = checks.run_checks(files, Path(directory), 10)
            self.assertFalse(report["pass"])
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(report["wrapper_launches"], 1)
            pool.assert_not_called()

    def test_analyzer_core_pool_isolates_windows_driver_and_preserves_failures(self):
        import threading
        import analyze_core_checks as checks

        files = ["warm.ouro", "slow.ouro", "tools/analyze/drive_main.ouro", "later.ouro"]
        for result in (RunResult("ok", 0, "CHECK_OK\n", "", 1, 2),
                       RunResult("ok", 1, "", "rejected", 1, 2),
                       RunResult("timeout", 1, "", "timeout", 1, 2),
                       RunResult("ok", 0xC0000005, "", "crash", 1, 2)):
            commands, overtaken = [], threading.Event()

            def execute(argv, result=result, commands=commands, overtaken=overtaken, **kwargs):
                commands.append(argv[3])
                self.assertEqual(kwargs["timeout_s"], 300)
                self.assertEqual(kwargs["memory_mb"], 3072)
                if argv[3] == files[2]:
                    self.assertEqual(commands, [files[0], files[2]])
                    return result
                if argv[3] == files[1]:
                    self.assertTrue(overtaken.wait(timeout=5))
                elif argv[3] == files[3]:
                    overtaken.set()
                return RunResult("ok", 0, "CHECK_OK\n", "", 1, 2)

            with tempfile.TemporaryDirectory() as directory, \
                 patch.object(checks, "os", SimpleNamespace(name="nt", environ={})), \
                 patch.object(checks, "environment", return_value={}), \
                 patch.object(checks, "shell", return_value=Path("sh")), \
                 patch.object(checks, "run_limited", side_effect=execute), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                value = checks.run_checks(files, Path(directory), 2)
                self.assertEqual(value["pass"], result.ok)
                self.assertEqual(value["wrapper_launches"], len(files))
                self.assertEqual(sorted(commands), sorted(files))
                self.assertEqual([row["file"] for row in value["checks"]], files)
                self.assertEqual(value["checks"][2]["resource"], result.classify())
                self.assertEqual([line.split()[2] for line in output.getvalue().splitlines()], files)
                self.assertTrue(all(Path(row["log"]).is_file() for row in value["checks"]))

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(checks, "os", SimpleNamespace(name="posix")), \
             patch.object(checks, "command_environment", return_value={}), \
             patch.object(checks, "shell", return_value=Path("sh")), \
             patch.object(checks, "run_limited", return_value=RunResult("ok", 0, "CHECK_OK\n", "", 0, 0)) as execute, \
             contextlib.redirect_stdout(io.StringIO()):
            value = checks.run_checks(files, Path(directory), 2)
            self.assertTrue(value["pass"])
            self.assertEqual([call.args[0][3] for call in execute.call_args_list], files)
            self.assertEqual(value["jobs"], 1)

    def test_native_inputs_are_isolated_and_invalid_requests_do_not_write(self):
        import csv
        from ourosmith.native_inputs import GROUPS, prepare, run_manifest

        scratch = ROOT / "_build/smith/selftest"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            out = Path(directory)
            outputs = [prepare(group, out, 1) for group in GROUPS]
            self.assertEqual(len(set(outputs)), len(GROUPS))
            self.assertTrue(all(path.is_dir() and any(path.iterdir()) for path in outputs))
            first = prepare("test", out, 6)
            second = prepare("test", out, 6)
            self.assertNotEqual(first, second)
            self.assertEqual((first / "success.golden").read_text().splitlines(),
                             ["ok case6-0", "ok case6-1", "ok case6-2", "ok case6-3"])
            self.assertEqual((first / "failure.golden").read_bytes(),
                             (first / "success.golden").read_bytes() + b"FAIL broken intentional\n")
            manifest = outputs[GROUPS.index("manifest")]
            rows = list(csv.reader((manifest / "manifest.tsv").read_text().splitlines(), delimiter="\t"))
            self.assertTrue(rows)
            self.assertEqual(len({row[0] for row in rows}), len(rows))
            self.assertTrue(all(len(row) == 6 and (manifest / row[1]).is_file() and
                                (manifest / row[1]).resolve().is_relative_to(manifest) for row in rows))
            before = sorted(path.relative_to(out).as_posix() for path in out.rglob("*"))
            for group, seed in (("unknown", 1), ("fmt", -1)):
                with self.assertRaises(ValueError):
                    prepare(group, out, seed)
            with patch("ourosmith.host.ensure_tools", side_effect=AssertionError("must not build invalid request")), self.assertRaises(ValueError):
                run_manifest(SimpleNamespace(seed=-1, out=out))
            self.assertEqual(before, sorted(path.relative_to(out).as_posix() for path in out.rglob("*")))

    def test_stable_compiled_fixtures_share_only_matching_native_inputs(self):
        from concurrent.futures import ThreadPoolExecutor
        from frontend_regen import collect_units_many
        from ourosmith.native_inputs import prepare
        from repo_support import hash_json, sha256_bytes

        scratch = ROOT / "_build/smith/selftest"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            out = Path(directory)
            for group in ("runtime", "test"):
                fresh = prepare(group, out, 1)
                with ThreadPoolExecutor(max_workers=4) as pool:
                    copies = list(pool.map(lambda _index, group=group: prepare(group, out, 1, stable=True), range(4)))
                stable = copies[0]
                self.assertEqual(copies, [stable] * 4)
                self.assertNotEqual(stable, fresh)
                expected = {file.name: file.read_bytes() for file in fresh.iterdir()}
                self.assertEqual({file.name: file.read_bytes() for file in stable.iterdir()}, expected)
                self.assertEqual(stable.name, group + "-" + hash_json([
                    1, {name: sha256_bytes(data) for name, data in expected.items()},
                ])[:16])
                with patch("ourosmith.native_inputs.tempfile.TemporaryDirectory",
                           side_effect=AssertionError("warm fixtures must reuse the published tree")):
                    self.assertEqual(prepare(group, out, 1, stable=True), stable)
                entries = [file.relative_to(ROOT).as_posix() for file in stable.glob("*.ouro")]
                self.assertEqual(len(entries), 4)
                closures = collect_units_many(entries)
                self.assertTrue(all(units[-1] == entry and "std/io.ouro" in units for entry, units in closures.items()))
                seed_two = prepare(group, out, 2, stable=True)
                self.assertNotEqual(stable, seed_two)
                self.assertEqual(set(out.glob(group + "-*")), {fresh, stable, seed_two})
                golden = next(fresh.glob("*.golden"))
                golden.write_bytes(b"deliberately wrong golden")
                self.assertNotEqual((stable / golden.name).read_bytes(), golden.read_bytes())

    def test_stable_compiled_fixtures_reject_incomplete_or_modified_trees(self):
        from ourosmith.native_inputs import prepare

        scratch = ROOT / "_build/smith/selftest"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            out = Path(directory)
            rejected = out / "unsupported"
            with self.assertRaisesRegex(ValueError, "group runtime or test"):
                prepare("fix", rejected, 1, stable=True)
            self.assertFalse(rejected.exists())
            physical_lstat = Path.lstat
            for damage in ("changed", "missing", "extra", "linked"):
                with self.subTest(damage=damage):
                    destination = out / damage
                    stable = prepare("test", destination, 6, stable=True)
                    file = stable / "success.golden"
                    metadata = contextlib.nullcontext()
                    if damage == "changed":
                        file.write_bytes(bytes(file.stat().st_size))
                    elif damage == "missing":
                        file.unlink()
                    elif damage == "extra":
                        (stable / "unexpected").write_bytes(b"")
                    else:
                        linked = SimpleNamespace(st_mode=file.stat().st_mode, st_nlink=2)
                        metadata = patch.object(Path, "lstat", lambda path, target=file, info=linked:
                                                info if path == target else physical_lstat(path))
                    with metadata, self.assertRaisesRegex(ValueError, "invalid stable fixture"):
                        prepare("test", destination, 6, stable=True)

    def test_stable_compiled_fixture_write_failure_leaves_nothing_to_reuse(self):
        from ourosmith.native_inputs import prepare

        scratch = ROOT / "_build/smith/selftest"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            out = Path(directory)
            physical_open = Path.open

            def fail_second(path, mode="r", *args, **kwargs):
                if path.name == "helpers.golden" and mode.startswith("w"):
                    raise OSError("fixture write failed")
                return physical_open(path, mode, *args, **kwargs)

            with patch.object(Path, "open", fail_second), self.assertRaisesRegex(OSError, "fixture write failed"):
                prepare("test", out, 1, stable=True)
            self.assertEqual(list(out.iterdir()), [])
            self.assertTrue((prepare("test", out, 1, stable=True) / "helpers.golden").is_file())

    def test_ergonomics_setup_comment_cannot_consume_candidate_or_lint_variant(self):
        from ourosmith.ergonomics_inputs import render

        case = {"type": "ErgNat", "sugar": "ErgZero", "canonical": "ErgZero",
                "setup": "def setup : ErgNat := ErgZero; -- final comment"}
        regular = render(case, Path("fixture"))
        lint = render(dict(case, source="def ergo_expansion_candidate : ErgNat := ErgZero;"),
                      Path("fixture"))
        self.assertIn("-- final comment\ndef ergo_expansion_candidate", regular)
        self.assertIn("\ndef ergo_expansion_reference", regular)
        self.assertIn("-- final comment\ndef ergo_expansion_candidate", lint)
        self.assertEqual(lint.count("def setup : ErgNat"), 1)

    def test_inline_character_equivalence_retains_both_values_and_equality(self):
        from ourosmith.ergonomics_inputs import load_cases, render

        cases = load_cases()["positive"]
        selected = {case["name"]: case for case in cases if case.get("inline_equivalence")}
        self.assertEqual(set(selected), {"character-four-byte", "character-scalar-boundary"})
        expected = {"character-four-byte": ("'😀'", "128512"),
                    "character-scalar-boundary": ("'\\u{10FFFF}'", "1114111")}
        for name, (sugar, canonical) in expected.items():
            case = selected[name]
            self.assertEqual((case["type"], case["sugar"], case["canonical"]),
                             ("Nat", sugar, canonical))
            source = render(case, Path("fixture"))
            self.assertIn(f"def ergo_expansion_candidate : (Nat) := {sugar};\n", source)
            self.assertIn(f"def ergo_expansion_reference : (Nat) := {canonical};\n", source)
            self.assertIn(f"def ergo_expansion_law : ErgEq (Nat) ({sugar}) ({canonical}) "
                          f":= ErgRefl (Nat) ({canonical});\n", source)
        ordinary = render({"type": "Nat", "sugar": "1", "canonical": "1"}, Path("fixture"))
        self.assertIn("ErgEq (Nat) ergo_expansion_candidate ergo_expansion_reference "
                      ":= ErgRefl (Nat) ergo_expansion_reference;", ordinary)

    def test_inline_equivalence_rejects_invalid_flags_and_pointwise_cases(self):
        from ourosmith.ergonomics_inputs import load_cases, render

        positive = {"name": "positive", "type": "Nat", "sugar": "1", "canonical": "1"}
        negative = {"name": "negative", "source": "def invalid : Nat := missing;"}
        invalid = [dict(positive, inline_equivalence=flag) for flag in (None, 0, 1, "true")]
        invalid.append(dict(positive, inline_equivalence=True, law_type="Nat", law_args="0"))
        for case in invalid:
            with self.subTest(case=case), self.assertRaises(ValueError):
                render(case, Path("fixture"))
            with patch("ourosmith.ergonomics_inputs.json.loads",
                       return_value={"positive": [case], "negative": [negative]}), self.assertRaises(ValueError):
                load_cases()
        with patch("ourosmith.ergonomics_inputs.json.loads",
                   return_value={"positive": [positive],
                                 "negative": [dict(negative, inline_equivalence=False)]}), self.assertRaises(ValueError):
            load_cases()
        self.assertEqual(render(positive, Path("fixture")),
                         render(dict(positive, inline_equivalence=False), Path("fixture")))

    def test_character_runtime_oracle_uses_the_same_wide_values(self):
        from ourosmith.ergonomics_inputs import load_cases

        source = (ROOT / "tests/character_equivalence_runtime.ouro").read_text(encoding="utf-8")
        names = {"character-four-byte": "four_byte", "character-scalar-boundary": "maximum"}
        for case in load_cases()["positive"]:
            if case["name"] in names:
                name = names[case["name"]]
                self.assertIn(f"def character_runtime_{name}_candidate : Nat := {case['sugar']};", source)
                self.assertIn(f"def character_runtime_{name}_reference : Nat := {case['canonical']};", source)

    def test_current_record_update_mapping_keeps_archived_rejection(self):
        from ourosmith.migration import current_record_update_categories, legacy_categories

        manifest = ("REC.B.check.ambiguous_literal\trecords/bad/ambiguous_literal.ouro\tcheck\tfail\t1\tOURO-REC-003\n"
                    "REC.B.check.update_pending\trecords/bad/update_pending.ouro\tcheck\tfail\t1\tOURO-REC-003\n")
        archived, count = legacy_categories([], manifest)
        self.assertEqual(count, 2)
        archived_record = next(row for row in archived if row["id"] ==
                               "manifest:REC.B:check:fail:OURO-REC-003")
        self.assertEqual(len(archived_record["rows"]), 2)
        current = current_record_update_categories(legacy_categories([], manifest)[0])
        current_record = next(row for row in current if row["id"] ==
                              "manifest:REC.B:check:fail:OURO-REC-003")
        accepted = next(row for row in current if row["id"] ==
                        "current:REC.B.check.update_pending")
        self.assertEqual(len(archived_record["rows"]), 2)
        self.assertEqual([row["id"] for row in current_record["rows"]],
                         ["REC.B.check.ambiguous_literal"])
        self.assertEqual(current_record["strategies"], ["surface/negative_kinds/record-no-context"])
        self.assertEqual([row["id"] for row in accepted["rows"]],
                         ["REC.B.check.update_pending"])
        self.assertEqual(accepted["expect"], "pass")
        self.assertIn("external/ci/ergonomics", accepted["strategies"])

    def test_migration_requires_exact_executed_categories(self):
        from ourosmith import migration_contracts as mapping
        from ourosmith.migration import exercised, refresh

        self.assertEqual(mapping.manifest_strategy("FUTURE.G", "check", "pass", "")[0], [])
        self.assertEqual(mapping.manifest_strategy("B.check", "check", "fail", "unknown new rejection")[0], [])
        strategies, _ = mapping.manifest_strategy("B.check", "check", "fail", "expected domain")
        self.assertEqual(strategies, ["surface/negative_kinds/lambda-argument-domain"])
        value = {"summary": {"layers": {"surface": {"coverage": {"features": {"literal": 3}}}}}}
        self.assertTrue(exercised(value, "surface/features/literal"))
        self.assertFalse(exercised(value, "surface/negative_kinds/literal"))
        self.assertFalse(exercised(value, "external/ci/test"))
        matrix = {"legacy_files": ["input"], "categories": [
            {"strategies": ["surface/features/literal"]},
            {"strategies": ["surface/features/literal", "surface/features/missing"]},
            {"strategies": [], "note": "Unmapped executable"}]}
        with patch("ourosmith.migration.references", return_value=([], [])):
            refresh(matrix, value, None)
        self.assertEqual([row["status"] for row in matrix["categories"]], ["covered", "gap", "gap"])

    def test_migration_archive_reconstructs_canonical_accounting(self):
        from copy import deepcopy
        from ourosmith import migration

        matrix, snapshot, manifest, value, external = migration_archive()
        changed_fields = [
            (("categories",), []), (("categories",), matrix["categories"][:-1]),
            (("categories", 0, "strategies"), []), (("categories", 0, "rows"), []),
            (("legacy_files",), matrix["legacy_files"][:-1]),
            (("recoverability", "git_blobs", matrix["legacy_files"][0]), "0" * 40),
            (("recoverability", "files_sha256", matrix["legacy_files"][0]), "0" * 64),
            (("recoverability", "tree"), "0" * 40), (("recoverability", "revision"), "0" * 40),
            (("pre_retirement_source", "head"), "0" * 40), (("pre_retirement_source", "files"), 0),
            (("source_manifest_sha256",), "0" * 64), (("manifest_rows",), 0),
            (("summary", "categories"), 0), (("evidence_fingerprint",), None),
            (("evidence_problems",), ["stale"]), (("deletion_ready",), False),
            (("recoverability", "status"), ["modified"]), (("recoverability",), None), (("categories",), None)]
        with patch.object(migration, "legacy_snapshot", return_value=(snapshot, manifest)) as recovered:
            migration.validate_archive(matrix)
            recovered.assert_called_once_with(snapshot["revision"])
            for path, replacement in changed_fields:
                changed = deepcopy(matrix)
                target = changed
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = replacement
                with self.subTest(path=path), self.assertRaises(ValueError):
                    migration.validate_archive(changed)
            with self.assertRaises(ValueError):
                migration.validate_archive({"kind": migration.KIND, "deletion_ready": True,
                    "recoverability": {"status": []}, "legacy_files": [], "categories": [], "manifest_rows": 0})
        with patch.object(migration, "legacy_snapshot", return_value=(snapshot, manifest)), \
             patch.object(migration, "tracked_legacy", return_value=[]), \
             patch.object(migration, "MATRIX", SimpleNamespace(is_file=lambda: True, read_text=lambda **_: json.dumps(matrix))), \
             patch.object(migration, "references", return_value=([], [])), \
             patch.object(migration, "external_evidence", return_value=external):
            retired = migration.build_matrix(value)
            self.assertTrue(retired["retired"])
            self.assertEqual(retired["summary"]["gaps"], 0)
            self.assertEqual(retired["pre_retirement_source"], matrix["pre_retirement_source"])
            value["summary"]["layers"] = {}
            self.assertGreater(migration.build_matrix(value)["summary"]["gaps"], 0)
        with self.assertRaisesRegex(ValueError, "full Git commit"):
            migration.legacy_snapshot("HEAD")
        with patch("ourosmith.provenance.git", return_value="tree\n"), self.assertRaisesRegex(ValueError, "not a Git commit"):
            migration.legacy_snapshot("a" * 40)

    def test_failed_retired_migration_preserves_verified_archive(self):
        from ourosmith import migration

        matrix, snapshot, manifest, value, external = migration_archive()
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "archive.json"
            original = json.dumps(matrix).encode()
            archive.write_bytes(original)
            args = SimpleNamespace(report="executed.json", validation=directory, out=Path(directory) / "out", write=True)
            value["fingerprint"] = "1" * 64
            with patch.object(migration, "MATRIX", archive), \
                 patch.object(migration, "legacy_snapshot", return_value=(snapshot, manifest)), \
                 patch.object(migration, "tracked_legacy", return_value=[]), \
                 patch.object(migration, "load_report", return_value=value), \
                 patch.object(migration, "references", return_value=([], [])), \
                 patch.object(migration, "external_evidence", return_value=external), \
                 patch("ourosmith.provenance.source_state", return_value={"head": "2" * 40}), \
                 patch("ourosmith.evidence.validation_problems", return_value=[]), \
                 patch("ourosmith.evidence.profile_problems", return_value=["stale current evidence"]) as checked, \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(migration.run(args), 1)
                self.assertEqual(archive.read_bytes(), original)
                failed = json.loads((args.out / "migration_matrix.json").read_text())
                self.assertFalse(failed["deletion_ready"])
                self.assertEqual(failed["evidence_problems"], ["stale current evidence"])
                checked.return_value = []
                self.assertEqual(migration.run(args), 0)
            updated = json.loads(archive.read_text())
            self.assertTrue(updated["retired"])
            self.assertEqual(updated["evidence_fingerprint"], value["fingerprint"])
            self.assertEqual(updated["pre_retirement_source"], matrix["pre_retirement_source"])

    def test_recipe_only_replay_generates_current_inputs(self):
        from types import SimpleNamespace
        from ourosmith.surface.tools import run_tools

        with tempfile.TemporaryDirectory() as directory:
            run = SimpleNamespace(seed=1, work=Path(directory))
            for recipe, module in (("compiler_parity", "parity"), ("backend_depth", "backend"),
                                   ("manifest_contract", "manifest"), ("runtime_io", "io")):
                with patch("ourosmith.surface." + module + ".run_checks") as check:
                    run_tools(run, only=recipe, saved={"recipe": recipe, "seed": 1})
                    self.assertEqual(check.call_count, 1)
                    self.assertNotIn("saved", check.call_args.kwargs)

    def test_parallel_surface_results_preserve_order_and_failures(self):
        import threading
        from ourosmith.surface.run import StepFailure, SurfaceRunner

        barrier = threading.Barrier(2)
        seeds = [3, 1, 2]
        value = Report(profile="pr", generator_hash="selftest", seeds=seeds, command="parallel")

        def sample(worker, index, seed):
            if index:
                barrier.wait(timeout=5)
            worker.seed, worker.case_id = seed, f"sample-{seed}"
            worker.input = {"source": str(seed)}
            worker.summary.cases += 1
            worker.summary.property_checks += seed
            worker.count("features", "sample")
            worker.summary.abstain("unavailable")
            worker.report.skip(str(seed), "simulated unavailable tool")
            worker.report.gap("surface", str(seed), "simulated gap", blocking=True)
            worker.record(StepFailure("sample", "expected", seed))

        with patch("ourosmith.surface.run.binary", return_value=Path("unused")), \
             patch("ourosmith.surface.run.environment", return_value={}), \
             patch("ourosmith.surface.run.job_count", return_value=2), \
             patch("ourosmith.surface.run.available_memory_mib", return_value=2048), \
             patch("ourosmith.surface.forms.run_forms"), patch.object(SurfaceRunner, "run_recipes"), \
             patch("ourosmith.surface.corpus.load", return_value=[]), \
             patch.object(SurfaceRunner, "run_seed", sample):
            runner = SurfaceRunner(value, ROOT / "_build/smith/selftest/parallel", seeds,
                                   overrides={"ouro1": Path("unused")})
            runner.run()
        self.assertEqual([finding.seed for finding in value.findings], seeds)
        self.assertEqual([int(skip["what"]) for skip in value.skips], seeds)
        self.assertEqual([int(gap["what"]) for gap in value.gaps], seeds)
        self.assertEqual(runner.summary.cases, 3)
        self.assertEqual(runner.summary.property_checks, sum(seeds))
        self.assertEqual(runner.summary.abstentions, {"unavailable": 3})
        self.assertEqual(runner.coverage["features"], {"sample": 3})
        self.assertFalse(value.passed)
        with patch.object(SurfaceRunner, "run_seed", side_effect=RuntimeError("worker failed")), \
             patch("ourosmith.surface.run.binary", side_effect=AssertionError("unexpected default binary lookup")):
            with self.assertRaisesRegex(RuntimeError, "worker failed"):
                runner.seed_report((1, 1))

    def test_parallel_recipes_isolate_work_and_preserve_failures(self):
        import threading
        from ourosmith.surface.run import StepFailure, SurfaceRunner
        from selfhost_module_cache import CachedImportParser

        barrier = threading.Barrier(2)
        active = set()
        started = threading.Event()
        paths = []
        import_parsers = []
        lock = threading.Lock()
        names = ["alpha", "analyzer_lines", "user_test_runner", "beta", "compiler_parity"]

        def recipe(worker, *, only):
            if only == "analyzer_lines":
                self.assertTrue(started.wait(timeout=5))
            with lock:
                paths.append(worker.work)
                import_parsers.append(worker.import_parser)
                if only in {"alpha", "beta"}:
                    active.add(only)
                    started.set()
                    self.assertEqual(worker.env["OURO_JOBS"], "1")
                else:
                    self.assertEqual(active, set())
                    self.assertEqual(worker.timeout, 20)
            if only in {"alpha", "beta"}:
                barrier.wait(timeout=5)
                with lock:
                    active.remove(only)
            worker.case_id, worker.input = only, {"recipe": only}
            worker.summary.cases += 1
            worker.count("features", only)
            worker.summary.abstain("unavailable")
            worker.report.skip(only, "simulated missing tool")
            worker.record(StepFailure(only, "expected", "injected failure"))
            if only == "compiler_parity":
                worker.report.sections["stage_parity"] = {"status": "exercised"}

        def failed_recipe(worker, **_kwargs):
            self.assertIsNot(worker.import_parser, import_parsers[0])
            raise RuntimeError("recipe failed")

        value = Report(profile="pr", generator_hash="selftest", seeds=[6], command="recipes")
        with patch("ourosmith.surface.run.binary", return_value=Path("unused")), \
             patch("ourosmith.surface.run.environment", return_value={}), \
             patch("ourosmith.surface.run.job_count", return_value=2), \
             patch("ourosmith.surface.run.available_memory_mib", return_value=2048), \
             patch("ourosmith.surface.tools.PROPERTIES", [SimpleNamespace(__name__=name) for name in names]), \
             patch("ourosmith.surface.tools.run_tools", side_effect=recipe):
            runner = SurfaceRunner(value, ROOT / "_build/smith/selftest/recipes", [6])
            runner.seed = 6
            runner.run_recipes()
            with patch("ourosmith.surface.tools.run_tools", side_effect=failed_recipe), \
                 self.assertRaisesRegex(RuntimeError, "recipe failed"):
                runner.run_recipes()
        self.assertEqual(len(set(paths)), len(names))
        self.assertIsNone(runner.import_parser)
        self.assertIsInstance(import_parsers[0], CachedImportParser)
        self.assertTrue(all(parser is import_parsers[0] for parser in import_parsers))
        self.assertEqual([finding.prop for finding in value.findings], names)
        self.assertEqual([finding.seed for finding in value.findings], [6] * len(names))
        self.assertEqual([skip["what"] for skip in value.skips], names)
        self.assertEqual(runner.coverage["features"], dict.fromkeys(names, 1))
        self.assertEqual(runner.summary.abstentions, {"unavailable": len(names)})
        self.assertEqual(value.sections["stage_parity"], {"status": "exercised"})
        self.assertFalse(value.passed)
        conflict = Report(profile="pr", generator_hash="selftest", seeds=[6], command="recipes")
        conflict.sections["stage_parity"] = {"status": "unavailable"}
        with self.assertRaisesRegex(ValueError, "conflicting surface report section"):
            runner.merge_seed(conflict)

    def test_eval_pair_keeps_child_budgets_and_detects_same_wrong_output(self):
        from threading import Barrier
        from ourosmith.surface import parity
        from ourosmith.surface.run import StepFailure, SurfaceRunner

        expected = {"expected": 2, "successor": "S", "type_name": "Nat"}
        for jobs in (1, 20):
            with self.subTest(jobs=jobs), tempfile.TemporaryDirectory() as directory:
                work = Path(directory)
                barrier = Barrier(2) if jobs == 20 else None

                def execute(argv, *, cwd, env, timeout_s, memory_mb, barrier=barrier, work=work):
                    self.assertEqual(env["OURO_JOBS"], "1")
                    self.assertEqual(env["OURO_SCHEDULER_JOBS"], "1")
                    self.assertEqual(env["OURO_SCHEDULER_MEMORY_MIB"], "64")
                    self.assertEqual((cwd, timeout_s, memory_mb), (work, 60, 64))
                    if barrier is not None:
                        barrier.wait(timeout=5)
                    stdout = parity.nat_output(2 if "--print" in argv else 4)
                    return RunResult("ok", 0, stdout, "", 0, 0)

                with patch("ourosmith.surface.run.environment", return_value={}), \
                     patch("ourosmith.surface.run.available_memory_mib", return_value=128), \
                     patch.object(parity, "environment", return_value={}) as environment, \
                     patch.object(parity, "job_count", return_value=jobs), \
                     patch.object(parity, "run_limited", side_effect=execute) as commands:
                    runner = SurfaceRunner(report(), work, [1], memory_mb=64, overrides={"ouro1": work / "compiler"})
                    with self.assertRaises(StepFailure) as error:
                        parity.eval_pair(runner, work, [work / "shell", work / "ouro1.sh"], work / "main.ouro", expected)
                self.assertEqual((error.exception.prop, error.exception.classification), ("eval-parallel", "property-violation"))
                environment.assert_called_once_with(jobs=1, build=True, shell_path=work / "shell")
                self.assertEqual(commands.call_count, 2)
                self.assertEqual(runner.report.timing["surface.eval-pair.scheduler.peak_jobs"], 1 if jobs == 1 else 2)
                self.assertEqual((work / "parallel-print.stdout").read_text(encoding="utf-8"), parity.nat_output(2))
                self.assertEqual((work / "parallel-expr.stdout").read_text(encoding="utf-8"), parity.nat_output(4))

    def test_parity_evals_use_the_selected_shell(self):
        from ourosmith import host
        from ourosmith.surface import parity

        core = "ouro.checked-program.v1\n1 0 \n"
        saved = {"cases": [{"name": "fixture", "source": "fixture source\n", "expected": 2,
                            "type_name": "Nat", "successor": "S", "dependencies": []}]}
        eval_results = iter([
            RunResult("ok", 0, parity.nat_output(2), "", 0, 0),
            RunResult("ok", 0, parity.nat_output(3), "", 0, 0),
            RunResult("ok", 2, "", "EVAL_FAIL: require exactly one of --eval / --print", 0, 0),
            RunResult("ok", 2, "", "EVAL_FAIL: require exactly one of --eval / --print", 0, 0),
            RunResult("ok", 2, "", "EVAL_FAIL: missing", 0, 0),
            RunResult("ok", 1, "", "CErr code=2", 0, 0),
        ])
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            sh = directory / "wrapper" / "sh"
            steps = []

            def command(argv, _cwd, step, **options):
                if step == "parity-host":
                    argv[-1].write_text(core, encoding="utf-8")
                    return RunResult("ok", 0, "CHECK_OK\n", "", 0, 0)
                steps.append(step)
                self.assertEqual(argv[0], sh)
                self.assertEqual(options["env"]["OURO_POSIX_SH"], sh.as_posix())
                self.assertEqual(options["timeout"], 60)
                return next(eval_results)

            run = SimpleNamespace(overrides={}, input=None, command=command, count=Mock(),
                                  accepts=Mock(return_value=core), native=Mock(return_value=RunResult("ok", 0, parity.nat_output(2), "", 0, 0)),
                                  output=lambda result: result.stdout + result.stderr,
                                  require=lambda ok, step, *_details: self.assertTrue(ok, step))
            with (patch.object(parity, "stage", return_value=None), patch.object(parity, "shell", return_value=sh) as locate,
                  patch.object(host, "shell", return_value=directory / "rediscovered" / "sh") as redundant,
                  patch.object(parity, "eval_pair")):
                parity.run_checks(run, directory, saved=saved)
            locate.assert_called_once_with()
            redundant.assert_not_called()
            self.assertEqual(steps, ["eval-reference"] * 2 + ["eval-negative"] * 4)

    def test_recursive_surface_shrinking_keeps_scope_and_cleanliness(self):
        from ourosmith.surface import gen

        original = gen.generate(100248, 6)
        observed = []

        def property_fails(candidate):
            self.assertEqual(gen.validate(candidate), "Nat")
            self.assertTrue(gen.lint_clean(candidate))
            observed.append(candidate)
            return "lambda" in gen.features(candidate) and "if" in gen.features(candidate)

        reduced, attempts = gen.shrink(original, property_fails, 60)
        self.assertGreater(attempts, 0)
        self.assertLessEqual(attempts, 60)
        self.assertTrue(observed)
        self.assertLess(len(json.dumps(reduced.json())), len(json.dumps(original.json())))
        self.assertTrue(property_fails(reduced))

    def test_saved_parity_uses_frozen_inputs(self):
        from ourosmith.surface.run import StepFailure, SurfaceRunner

        value = {"recipe": "compiler_parity", "cases": [{"name": "frozen", "source": "frozen source\n",
                 "expected": 9, "type_name": "Nat", "successor": "S", "dependencies": []}]}
        observed = []

        def accept(path, **_kwargs):
            observed.append(path.read_text(encoding="utf-8"))
            raise StepFailure("stop", "stop", "stop")

        with patch("ourosmith.surface.run.binary", return_value=Path("unused")), \
             patch("ourosmith.surface.run.environment", return_value={}), \
             patch("ourosmith.surface.parity.inputs", side_effect=AssertionError("regenerated")), \
             patch("ourosmith.surface.parity.stage", return_value=None):
            runner = SurfaceRunner(report(), ROOT / "_build/smith/selftest/parity-saved", [1], shrink_budget=0)
            with patch.object(runner, "accepts", side_effect=accept):
                runner.replay_input(value)
        self.assertEqual(observed, ["frozen source\n"])
        self.assertEqual(runner.report.findings[0].minimal_input, value)

    def test_parity_reads_each_checked_snapshot_once(self):
        from ourosmith.surface import parity
        from ourosmith.surface.run import StepFailure, SurfaceRunner
        from repo_support import sha256_bytes

        core = "ouro.checked-program.v1\n1 0 \n"
        changed = "ouro.checked-program.v1\n1 1 \n"
        saved = {"cases": [{"name": "frozen", "source": "frozen source\n", "expected": 9,
                            "type_name": "Nat", "successor": "S", "dependencies": []}]}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staged = root / "_build/stage_loop/ouro1_stage2"
            staged.parent.mkdir(parents=True)
            image = b"s" * (1024 * 1024) + b"1"
            staged.write_bytes(image)
            staged.with_name("result.json").write_text(json.dumps({
                "stages": 2, "pass": True, "frontend_eq": True, "backend_eq": True,
                "artifacts": {"binary_sha256": sha256_bytes(image)},
            }), encoding="utf-8")

            def command(argv, _work, prop):
                path = Path(argv[-1])
                path.write_text(changed if prop == failure else core, encoding="ascii")
                return RunResult("ok", 0, "CHECK_OK", "", 0, 0)

            with (patch.object(parity, "ROOT", root), patch.object(parity, "shell", return_value=root / "shell"),
                  patch("ourosmith.surface.run.environment", return_value={}),
                  patch("ourosmith.surface.run.available_memory_mib", return_value=128),
                  patch.object(Path, "read_bytes", side_effect=AssertionError("whole binary read")),
                  patch.object(parity, "checked_program_snapshot", wraps=parity.checked_program_snapshot) as reads):
                runner = SurfaceRunner(report(), root, [1], memory_mb=64, overrides={"ouro1": root / "compiler"})
                with (patch.object(runner, "accepts", return_value=core), patch.object(runner, "command", command),
                      patch.object(runner, "native", side_effect=StepFailure("fixture-stop", None, None))):
                    for failure, expected, paths in (
                        (None, "fixture-stop", ["host.checked", "stage.checked"]),
                        ("parity-host", "parity-host-core", ["host.checked"]),
                        ("parity-stage", "parity-stage-core", ["host.checked", "stage.checked"]),
                    ):
                        with self.subTest(failure=failure):
                            reads.reset_mock()
                            with self.assertRaises(StepFailure) as error:
                                parity.run_checks(runner, root, saved=saved)
                            self.assertEqual(error.exception.prop, expected)
                            if failure is not None:
                                self.assertEqual((error.exception.expected, error.exception.actual), (core, changed))
                            self.assertEqual([call.args[0].name for call in reads.call_args_list], paths)

                timestamp = staged.stat()
                staged.write_bytes(image[:-1] + b"2")
                os.utime(staged, ns=(timestamp.st_atime_ns, timestamp.st_mtime_ns))
                with self.assertRaises(StepFailure) as error:
                    parity.stage(runner)
                self.assertEqual(error.exception.prop, "stage-fixpoint-proof")

    def test_saved_io_freezes_source_helper_and_process_inputs(self):
        from ourosmith.surface.run import SurfaceRunner

        saved = {"recipe": "runtime_io", "source": "frozen body\n", "child_source": "frozen helper\n",
                 "expected_values": {"clock": None}, "expected_files": {},
                 "env_value": "frozen env", "stdin": "frozen input", "arguments": ["frozen arg", ""]}
        with patch("ourosmith.surface.run.binary", return_value=Path("unused")), \
             patch("ourosmith.surface.run.environment", return_value={}), \
             patch("ourosmith.surface.io.program", side_effect=AssertionError("regenerated")), \
             patch("frontend_regen.collect_units", return_value=[]), \
             patch("ourosmith.surface.io.time.time_ns", return_value=1000000):
            runner = SurfaceRunner(report(), ROOT / "_build/smith/selftest/io-saved", [1], shrink_budget=0)
            runner.cc = "unused"
            with patch.object(runner, "accepts") as checked, \
                 patch.object(runner, "command", return_value=RunResult("ok", 0, "", "", 0, 0)), \
                 patch.object(runner, "native", return_value=RunResult("ok", 0, "clock=1\n", "", 0, 0)) as native:
                runner.replay_input(saved)
        self.assertFalse(runner.report.findings)
        path = checked.call_args.args[0]
        self.assertTrue(path.read_text().endswith(saved["source"]))
        self.assertEqual((path.parent / "child.c").read_text(), saved["child_source"])
        self.assertEqual(native.call_args.kwargs["stdin"], saved["stdin"])
        self.assertEqual(native.call_args.kwargs["arguments"], saved["arguments"])
        self.assertEqual(native.call_args.kwargs["env"]["OURO_SMITH_VALUE"], saved["env_value"])
        self.assertEqual(checked.call_args.kwargs["timeout"], 900)
        self.assertEqual(native.call_args.kwargs["compile_timeout"], 900)

    def test_c_static_commands_apply_only_required_module_scope_flags(self):
        import c_static_analysis_suite as gate

        flag = "-DOURO_MODULE_PURE_SCOPES=1"
        target = ["--target=x86_64-w64-windows-gnu"]
        exclusions = ["unix.Stream", "unix.Errno"]
        sources = (
            (gate.ROOT / "runtime/module_pure_scope_selftest.c", 1),
            (gate.ROOT / "runtime/../runtime/module_pure_scope_selftest.c", 1),
            (gate.ROOT / "runtime/ouro_rt.c", 0),
            (gate.ROOT / "runtime/frontend_link.c", 0),
            (gate.FIXTURES / "good.c", 0),
            (gate.FIXTURES / "bad_use_after_free.c", 0),
            (gate.FIXTURES / "module_pure_scope_selftest.c", 0),
        )
        with tempfile.TemporaryDirectory() as directory:
            obj = Path(directory) / "objects" / "fixture.o"
            for source, count in sources:
                with self.subTest(source=source):
                    gcc = gate.gcc_command("gcc", source, obj)
                    clang = gate.clang_command("clang", target, exclusions, source)
                    for command in (gcc, clang):
                        self.assertEqual(command.count(flag), count)
                        self.assertIn(gate.rel(source), command)
                        self.assertIn("-Werror", command)
                        for common in gate.COMMON_FLAGS:
                            self.assertIn(common, command)
                    self.assertIn("-fanalyzer", gcc)
                    self.assertIn("-c", gcc)
                    self.assertIn("--analyze", clang)
                    self.assertIn("-analyzer-werror", clang)
                    self.assertIn(target[0], clang)
                    self.assertIn("-analyzer-disable-checker=unix.Stream,unix.Errno", clang)

    def test_msvc_environment_is_local_and_fail_closed(self):
        import c_static_analysis_suite as gate

        original = {"PATH": "old", "LIB": "old-lib"}
        setup = "C:/Installed Toolchain"
        values = "INCLUDE=headers\nLIB=libraries\nPath=compiler-bin\nVCToolsInstallDir=tools\nPYTHONPATH=untrusted\n"
        with patch.object(gate, "os", SimpleNamespace(name="nt")), \
             patch.object(gate.Path, "is_file", return_value=True), \
             patch.object(gate, "capture", side_effect=[(0, setup), (0, values)]) as capture:
            actual = gate.msvc_environment(original)
        self.assertEqual(original, {"PATH": "old", "LIB": "old-lib"})
        self.assertEqual(actual["PATH"], "compiler-bin")
        self.assertEqual(actual["LIB"], "libraries")
        self.assertNotIn("PYTHONPATH", actual)
        self.assertIn("-prerelease", capture.call_args_list[0].args[0])
        self.assertIsInstance(capture.call_args_list[1].args[0], str)
        for response in ((1, "setup failed"), (0, "INCLUDE=headers\n")):
            with patch.object(gate, "os", SimpleNamespace(name="nt")), \
                 patch.object(gate.Path, "is_file", return_value=True), \
                 patch.object(gate, "capture", side_effect=[(0, setup), response]), \
                 self.assertRaises(RuntimeError):
                gate.msvc_environment(original)

    def test_protocol_seed_does_not_become_a_large_literal(self):
        import re
        from ourosmith.surface.library import protocols

        for seed in (0, 1, 100000, 2**63 - 1):
            expressions = "\n".join(expression for expression, _ in protocols(seed))
            literals = [int(value) for value in re.findall(r"json_num (\d+)", expressions)]
            self.assertTrue(literals)
            self.assertTrue(all(value < 100 for value in literals))


    def test_saved_text_contract_replays_exact_input(self):
        from ourosmith.surface.corpus import validate_input
        from ourosmith.surface.run import SurfaceRunner

        with patch("ourosmith.surface.run.binary", return_value=Path("unused")), \
             patch("ourosmith.surface.run.environment", return_value={}):
            runner = SurfaceRunner(report(), ROOT / "_build/smith/selftest/saved-text", [1], shrink_budget=0,
                                   overrides={"ouro1": Path("unused-compiler"), "ouro-fmt": Path("unused-fmt")})
        value = {"recipe": "text_tools", "case": "fmt-clean", "tool": "fmt",
                 "source": "-- saved source\n", "expected_source": "-- saved source\n",
                 "dependencies": [["nested/module.ouro", "-- saved module\n"]]}
        validate_input(value)
        observed = []

        def command(argv, *_args):
            self.assertEqual(argv[0], runner.overrides["ouro-fmt"])
            observed.append(argv[-1].read_text())
            self.assertEqual((argv[-1].parent / "nested/module.ouro").read_text(), "-- saved module\n")
            return RunResult("ok", 0, value["expected_source"], "", 0, 0)

        with patch.object(runner, "command", side_effect=command), \
             patch("ourosmith.surface.run.binary", side_effect=AssertionError("unexpected default binary lookup")):
            runner.replay_input(value)
        self.assertEqual(observed, [value["source"]] * 4)
        self.assertFalse(runner.report.findings)
        for filename in ("../outside.ouro", "/outside.ouro", "C:/outside.ouro", "nested\\outside.ouro"):
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                validate_input({**value, "dependencies": [[filename, "source"]]})

    def test_retirement_refuses_partial_or_stale_evidence(self):
        from ourosmith.evidence import profile_problems, validation_problems

        # A historical PASS, a report with disabled inventories, or just the
        # expected number of seeds must never authorize deleting the corpus.
        value = report().body()
        value["pass"] = True
        problems = profile_problems(value, "pr", {"source_sha256": "current"})
        self.assertTrue(any("fingerprint" in problem for problem in problems))
        self.assertTrue(any("seed set" in problem for problem in problems))
        self.assertTrue(any("completeness" in problem for problem in problems))
        with tempfile.TemporaryDirectory() as tmp:
            problems = validation_problems(Path(tmp))
        self.assertTrue(any("journal" in problem for problem in problems))
        self.assertTrue(any("entire catalogue" in problem for problem in problems))
        self.assertTrue(any("aggregate" in problem for problem in problems))

    def test_ci_pr_reuse_requires_current_executed_evidence(self):
        from ci_gate import REPORT_KIND as CI_KIND
        from ourosmith.evidence import ci_pr_receipt
        from ourosmith.validation import commands, reuse_ci_pr

        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory).resolve()
            produced = out / "ci-smith/report.json"
            produced.parent.mkdir()
            produced.write_text('{"fingerprint":"fixture"}\n', encoding="utf-8")
            gate_log = out / "ci/ouro-smith/gate.log"
            gate_log.parent.mkdir(parents=True)
            gate_log.write_text("executed\n", encoding="utf-8")
            expected = SimpleNamespace(name="ouro-smith", profiles=("pr",), cmd=[
                sys.executable, "scripts/ouro_smith.py", "--profile", "pr", "--out", str(produced.parent)])
            gate = {"name": expected.name, "status": "pass", "returncode": 0,
                    "command": expected.cmd, "log": str(gate_log)}
            summary = {"kind": CI_KIND, "profile": "pr", "group": "all", "gates": [gate]}
            summary_path = out / "ci/ci-summary.json"
            current = {"source_sha256": "current"}

            def write_summary():
                summary_path.write_text(json.dumps(summary), encoding="utf-8")

            with patch("ci_gate.gates", return_value=[expected]), \
                 patch("ourosmith.validation.source_state", return_value=current), \
                 patch("ourosmith.evidence.profile_problems", return_value=[]) as checked:
                write_summary()
                receipt, problems = ci_pr_receipt(out, current)
                self.assertEqual(problems, [])
                checked.assert_called_with({"fingerprint": "fixture"}, "pr", current)
                rows = [{"name": "ci", "command": dict(commands(out))["ci"], "status": "PASS", "exit_code": 0}]
                with contextlib.redirect_stdout(io.StringIO()):
                    reused = reuse_ci_pr(out, rows)
                self.assertEqual(reused["execution"], "ci")
                self.assertEqual(reused["command"], expected.cmd)
                self.assertEqual(reused["receipt"], receipt)
                self.assertEqual(produced.read_bytes(), (out / "pr/report.json").read_bytes())
                self.assertEqual(json.loads((out / "pr.log").read_text()), receipt)
                self.assertIsNone(reuse_ci_pr(out, []))
                rows[0]["exit_code"] = 1
                self.assertIsNone(reuse_ci_pr(out, rows))
                rows[0]["exit_code"] = 0
                checked.return_value = ["tested binaries differ from current binaries"]
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertIsNone(reuse_ci_pr(out, rows))
                checked.return_value = []
                for field, bad in (("status", "skip"), ("returncode", 1), ("command", []), ("log", "elsewhere")):
                    original = gate[field]
                    gate[field] = bad
                    write_summary()
                    self.assertIsNone(ci_pr_receipt(out, current)[0], field)
                    gate[field] = original
                summary["gates"] = [gate, gate]
                write_summary()
                self.assertIsNone(ci_pr_receipt(out, current)[0])
                summary["gates"] = [gate]
                write_summary()
                gate_log.write_text("changed log\n", encoding="utf-8")
                changed, _ = ci_pr_receipt(out, current)
                self.assertNotEqual(changed, receipt)
                produced.write_text("{malformed", encoding="utf-8")
                self.assertIsNone(ci_pr_receipt(out, current)[0])
                produced.unlink()
                self.assertIsNone(ci_pr_receipt(out, current)[0])

                from ourosmith.validation import ci_pr_repeat

                workspace = out / "_build/ci-fixture/smith"
                expected.cmd[-1] = "_build/ci/smith-pr"
                isolated_report = workspace / expected.cmd[-1] / "report.json"
                isolated_report.parent.mkdir(parents=True)
                isolated_report.write_text('{"fingerprint":"isolated"}\n', encoding="utf-8")
                gate.update(workspace=workspace.relative_to(out).as_posix(), jobs=4, memory_mib=4608)
                write_summary()
                with patch("ourosmith.evidence.ROOT", out), patch("ourosmith.validation.ROOT", out):
                    isolated, errors = ci_pr_receipt(out, current)
                    self.assertEqual(errors, [])
                    self.assertEqual(Path(isolated["report"]), isolated_report)
                    checked.assert_called_with({"fingerprint": "isolated"}, "pr", current, root=workspace)
                    repeated_root, _, repeated_argv, lease = ci_pr_repeat(isolated)
                    self.assertEqual(repeated_root, workspace)
                    self.assertEqual(repeated_argv[-1], "_build/ci/smith-pr-repeat")
                    self.assertEqual((lease.jobs, lease.memory_mib), (4, 4608))
                    gate["workspace"] = "../smith"
                    write_summary()
                    self.assertIsNone(ci_pr_receipt(out, current)[0])

    def test_validation_passes_the_same_aggregate_budget_to_child_and_supervisor(self):
        from ourosmith import validation
        from local_scheduler import JOBS_ENV, MEMORY_ENV

        source = {"source_sha256": "current"}
        success = SimpleNamespace(ok=True, returncode=0, stdout="", stderr="", elapsed_s=0,
                                  classify=lambda: "ok")
        with (tempfile.TemporaryDirectory() as directory,
              patch.object(validation, "commands", return_value=[("ci", ["unused-command"])]),
              patch.object(validation, "begin", return_value={"source": source}),
              patch.object(validation, "source_state", return_value=source),
              patch.object(validation, "environment", return_value={}),
              patch.object(validation, "job_count", return_value=8),
              patch.object(validation, "available_memory_mib", return_value=6144),
              patch.object(validation, "run_limited", return_value=success) as launch,
              patch("ourosmith.evidence.validation_problems", return_value=[]),
              contextlib.redirect_stdout(io.StringIO())):
            self.assertEqual(validation.run(SimpleNamespace(out=directory)), 0)
        self.assertEqual(launch.call_args.kwargs["memory_mb"], 6144)
        self.assertEqual(launch.call_args.kwargs["env"][MEMORY_ENV], "6144")
        self.assertEqual(launch.call_args.kwargs["env"][JOBS_ENV], "8")

    def test_legacy_consumer_path_boundaries(self):
        from ourosmith.migration import LEGACY_REFERENCE

        for line in ('test/suite/manifest.tsv', 'Path("test")', '${ROOT}/test/kernel', '${1:-test}', 'runtest test'):
            self.assertIsNotNone(LEGACY_REFERENCE.search(line), line)
        for line in ('tools/test/main.ouro', 'tests/analyze', 'scripts/test/suite.py', '["ouro1", "test", "input.ouro"]'):
            self.assertIsNone(LEGACY_REFERENCE.search(line), line)

    def test_partial_binary_provenance_is_not_evidence(self):
        from ourosmith.evidence import provenance_problems

        current = {"source_sha256": "current"}
        partial = {"compiler": "hash"}
        with patch("ourosmith.evidence.required_binaries", return_value={"compiler", "replayer"}), \
             patch("ourosmith.evidence.binary_state", return_value=partial):
            problems = provenance_problems({"source": current, "binaries": partial}, current, surface=True)
        self.assertIn("required tested binary set is incomplete", problems)

    def test_crypto_stream_fixture_runs_preserve_binary_boundaries(self):
        from ourosmith.surface.library import _crypto_stream_bytes

        for value, expected in (
            (bytes(range(256)), "str_of_codes (nat_range_count 0 256)"),
            (bytes(range(63, 129)), "str_of_codes (nat_range_count 63 66)"),
            (bytes(range(250, 256)), "str_of_codes (nat_range_count 250 6)"),
            (b"a" * 62, "str_of_codes (replicate Nat 97 62)"),
            (b"\xff" * 64, "str_of_codes (replicate Nat 255 64)"),
        ):
            with self.subTest(value=value):
                self.assertEqual(_crypto_stream_bytes(value), expected)
        for value in (b"", b"\0", b"\xff", bytes((0, 2, 3)), bytes((3, 2, 1)),
                      bytes((254, 255, 0)), bytes((65, 0, 255, 13, 10, 128)),
                      b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"):
            with self.subTest(value=value):
                expected = f'str_of_codes ([{", ".join(map(str, value))}] : List Nat)'
                self.assertEqual(_crypto_stream_bytes(value), expected)

    def test_crypto_stream_fixture_preserves_all_159_oracle_rows(self):
        import hashlib
        from ourosmith.surface.library import FAMILIES, crypto

        rows = list(crypto(1))
        expected = "".join(value + "\n" for _expression, value in rows).encode("utf-8")
        self.assertEqual(len(rows), 159)
        self.assertEqual(len(expected), 7215)
        self.assertEqual(hashlib.sha256(expected).hexdigest(),
                         "be964b6b7c71183821c3522c3d9ab61f6ff789b0a07030a99dd34b236bc03aba")
        self.assertEqual(FAMILIES["crypto"][1], ("std/crypto.ouro", "std/num.ouro"))

    def test_native_crypto_fixture_checks_all_rows_in_one_ordered_main(self):
        from ourosmith.native_inputs import prepare_library
        from ourosmith.surface.library import FAMILIES, _crypto_stream_bytes

        rows = list(FAMILIES["crypto"][0](1))
        self.assertEqual(len(rows), 159)
        comparisons = [index for index, (expression, _value) in enumerate(rows)
                       if expression.startswith("show_bool (str_eq observed")]
        self.assertEqual(comparisons, list(range(16, 60, 3)))
        lengths = (0, 1, 55, 56, 57, 63, 64, 65, 119, 120, 121, 127, 128, 129, 256)
        for comparison, size in zip(comparisons, lengths, strict=True):
            digest_index = comparison - 1
            message = _crypto_stream_bytes(bytes(range(size)))
            self.assertIn("sha256_stream_final", rows[digest_index][0])
            self.assertEqual(rows[comparison],
                             (f"show_bool (str_eq observed{digest_index} (sha256 ({message})))", "true"))
        scratch = ROOT / "_build/smith/selftest"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            root = Path(directory)
            prepare_library(root, "crypto", 1)
            source = (root / "crypto.ouro").read_text(encoding="utf-8")
            definitions, main = source.split("\n-- @entry main\ndef main : IO Unit :=\n  do\n")
            imports = "".join(f'import "{os.path.relpath(ROOT / name, root).replace(chr(92), "/")}";\n'
                              for name in ("std/io.ouro", "std/format.ouro", *FAMILIES["crypto"][1]))
            self.assertEqual(definitions, imports + "".join(
                f"def observed{i} : String := {expression};\n"
                for i, (expression, _value) in enumerate(rows)))
            self.assertEqual(main, "".join(f"     println observed{i};\n" for i in range(159))
                             + "     exit 0\n")
            expected = "".join(value + "\n" for _expression, value in rows).encode("utf-8")
            self.assertEqual((root / "crypto.golden").read_bytes(), expected)
            self.assertEqual(len(expected), 7215)

    def test_native_other_library_fixture_source_shape_is_unchanged(self):
        from ourosmith.native_inputs import prepare_library
        from ourosmith.surface.library import FAMILIES

        scratch = ROOT / "_build/smith/selftest"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            root = Path(directory)
            for family in ("strings", "data", "helpers"):
                with self.subTest(family=family):
                    rows = list(FAMILIES[family][0](1))
                    prepare_library(root, family, 1)
                    imports = "".join(f'import "{os.path.relpath(ROOT / name, root).replace(chr(92), "/")}";\n'
                                      for name in ("std/io.ouro", "std/format.ouro", *FAMILIES[family][1]))
                    source = imports + "\n-- @entry main\ndef main : IO Unit :=\n  do\n"
                    source += "".join(f"     println ({expression});\n" for expression, _value in rows)
                    source += "     exit 0\n"
                    self.assertEqual((root / (family + ".ouro")).read_text(encoding="utf-8"), source)
                    self.assertEqual((root / (family + ".golden")).read_bytes(),
                                     "".join(value + "\n" for _expression, value in rows).encode("utf-8"))

    def test_saved_stdlib_replays_exact_oracle(self):
        from ourosmith.surface.run import SurfaceRunner

        with patch("ourosmith.surface.run.binary", return_value=Path("unused")), \
             patch("ourosmith.surface.run.environment", return_value={}):
            runner = SurfaceRunner(report(), ROOT / "_build/smith/selftest/saved-stdlib", [1], shrink_budget=0)
        value = {"recipe": "stdlib_strings", "seed": 1, "source": 'def main : IO Unit := println "saved";\n', "expected_stdout": "saved\n"}
        observed = []
        with patch.object(runner, "accepts", side_effect=lambda path, **_kw: observed.append(path.read_text())), \
             patch.object(runner, "native", return_value=RunResult("ok", 0, "saved\n", "", 0, 0)), \
             patch.dict("ourosmith.surface.library.FAMILIES", {"strings": (lambda _seed: self.fail("saved replay invoked the generator"), ("std/text.ouro",))}):
            runner.replay_input(value)
        self.assertTrue(observed[0].endswith(value["source"]))
        self.assertFalse(runner.report.findings)
        with patch.object(runner, "accepts"), \
             patch.object(runner, "native", return_value=RunResult("ok", 0, "regenerated\n", "", 0, 0)):
            runner.replay_input(value)
        self.assertEqual(runner.report.findings[-1].expected, "saved\n")

    def test_changed_sources_or_binaries_invalidate_evidence(self):
        from ourosmith.provenance import finish

        for source, binaries in (({"hash": "changed"}, {}), ({"hash": "original"}, {"compiler": "changed"})):
            value = report()
            value.sections["provenance"] = {"source": {"hash": "original"}, "binaries": {}}
            with patch("ourosmith.provenance.source_state", return_value=source), \
                 patch("ourosmith.provenance.binary_state", return_value=binaries):
                finish(value)
            self.assertFalse(value.passed)

    def test_long_module_cache_paths_keep_content_identity(self):
        import selfhost_module_cache as cache

        base = ROOT / "_build/smith/selftest"
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as tmp:
            directory = Path(tmp)
            source = directory / ("source_name_with_the_same_prefix_" * 2)
            source.mkdir()
            files = [source / f"module_{i}.ouro" for i in range(2)]
            for path in files:
                path.write_text("def value : Nat := 1;\n", encoding="utf-8")
            kwargs = {"roots": [p.as_posix() for p in files], "work": directory / "work",
                      "cache_root": directory / "cache"}
            cold = cache.materialize_module_artifacts(**kwargs)
            warm = cache.materialize_module_artifacts(**kwargs)
            self.assertEqual(cold["summary"]["direct_misses"], 2)
            self.assertEqual(warm["summary"]["direct_hits"], 2)
            paths = [row["direct_cache_path"] for row in warm["modules"]]
            self.assertEqual(len(set(paths)), 2)
            self.assertTrue(all(len((ROOT / path).name) <= 95 for path in paths))
            files[0].write_text("def value : Nat := 2;\n", encoding="utf-8")
            changed = cache.materialize_module_artifacts(**kwargs)
            self.assertEqual(changed["summary"]["direct_misses"], 1)
            self.assertEqual(changed["summary"]["direct_hits"], 1)

    def test_module_cache_recipe_repeated_work_starts_cold(self):
        import selfhost_module_cache as cache
        from ourosmith.host import job_count
        from ourosmith.surface.tools import module_cache

        base = ROOT / "_build/smith/selftest"
        base.mkdir(parents=True, exist_ok=True)
        observed = []

        def command(argv, _directory, phase, **kwargs):
            def option(name):
                return argv[argv.index(name) + 1]
            data = cache.materialize_module_artifacts(
                roots=[option("--root").as_posix()], work=option("--work"),
                cache_root=Path(option("--cache-root")), report_path=option("--report"),
                cache_enabled="--no-cache" not in argv)
            observed.append((phase, Path(option("--cache-root")), data["summary"]))
            if phase != "module-cache-invalidate":
                expected_jobs = job_count() if phase == "module-cache-warm" else 1
                self.assertEqual(kwargs["env"]["OURO_JOBS"], str(expected_jobs))
            return RunResult("ok", 0, "", "", 0, 0)

        def require(condition, prop, expected, actual):
            self.assertTrue(condition, f"{prop}: expected {expected}, actual {actual}")

        with tempfile.TemporaryDirectory(dir=base) as tmp:
            work = Path(tmp)
            directory = work / "case"
            directory.mkdir()
            prior = work / "cache" / "preserved.txt"
            prior.parent.mkdir()
            prior.write_text("prior output", encoding="utf-8")
            run = SimpleNamespace(work=work, seed=1, module_cache=ROOT / "scripts/selfhost_module_cache.py",
                                  command=command, require=require, output=lambda result: result.stderr,
                                  accepts=lambda path, **_kwargs: (path.parent / "leaf.ouro").read_text())
            module_cache(run, directory)
            module_cache(run, directory)
            self.assertEqual(prior.read_text(), "prior output")
            self.assertEqual(len(observed), 8)
            self.assertNotEqual(observed[0][1], observed[4][1])
            for offset in (0, 4):
                rows = observed[offset:offset + 4]
                self.assertEqual([phase for phase, _cache, _summary in rows],
                                 ["module-cache-cold", "module-cache-warm", "module-cache-disabled", "module-cache-invalidate"])
                self.assertEqual(len({path for _phase, path, _summary in rows}), 1)
                self.assertEqual([summary["direct_misses"] for _phase, _path, summary in rows], [2, 0, 2, 1])
                self.assertEqual([summary["direct_hits"] for _phase, _path, summary in rows], [0, 2, 0, 1])
                self.assertEqual([summary["closure_misses"] for _phase, _path, summary in rows], [2, 0, 2, 2])

    def test_surface_fault_requires_its_expected_property(self):
        from ourosmith.faults import FAULTS
        from ourosmith.report import Finding
        from ourosmith.surface_faults import run_surface_fault

        fault = next(f for f in FAULTS if f.target == "fmt")
        baseline, mutated = report(), report()
        finding = Finding("surface", "unrelated", "property-violation", 1, "pr", "test", "case", "phase", "good", "bad", {}, "replay")
        mutated.add(finding)
        with patch("ourosmith.surface_faults.probe", side_effect=[baseline, mutated] * 3), \
             patch("ourosmith.surface_faults.build_mutant", return_value={}), \
             patch("ourosmith.faults.remove_scratch"), patch.object(Report, "write"):
            tools = {"ouro1": Path("fixture-compiler")}
            self.assertEqual(run_surface_fault(fault, ROOT / "_build/smith/selftest", timeout_s=1, memory_mb=64, overrides=tools).status, "survived")
            finding.prop, finding.classification = fault.expect[0], "crash"
            self.assertEqual(run_surface_fault(fault, ROOT / "_build/smith/selftest", timeout_s=1, memory_mb=64, overrides=tools).status, "survived")
            finding.classification = "property-violation"
            self.assertEqual(run_surface_fault(fault, ROOT / "_build/smith/selftest", timeout_s=1, memory_mb=64, overrides=tools).status, "killed")

    def test_saved_form_replays_exact_source_and_expectation(self):
        from ourosmith.surface.run import StepFailure, SurfaceRunner

        with patch("ourosmith.surface.run.binary", return_value=Path("unused")), \
             patch("ourosmith.surface.run.environment", return_value={}):
            runner = SurfaceRunner(report(), ROOT / "_build/smith/selftest/saved-form", [1], shrink_budget=0)
        source = "def original : Nat := 987;\n"
        value = {"recipe": "form-list", "source": source, "expected": 987, "units_needed": False}
        observed = []

        def accept(path, **_kwargs):
            observed.append(path.read_text(encoding="utf-8"))
            raise StepFailure("saved", "stop", "stop")

        with patch.object(runner, "accepts", side_effect=accept), \
             patch("ourosmith.surface.forms.programs", side_effect=AssertionError("regenerated")):
            runner.replay_input(value)
        self.assertEqual(observed, [source])
        self.assertEqual(runner.report.findings[0].minimal_input["expected"], 987)

    def test_character_form_keeps_wide_values_and_independent_mismatch(self):
        from ourosmith.surface.forms import programs

        for seed, scalar in enumerate(("A", "é", "€", "😀")):
            with self.subTest(seed=seed):
                selected = [case for case in programs(seed) if case[0] == "character-scalar"]
                self.assertEqual(len(selected), 1)
                _name, source, expected, units_needed = selected[0]
                ordinal = ord(scalar)
                escaped = "'\\u{" + format(ordinal, "X") + "}'"
                self.assertIn(f"def value' : Nat := '{scalar}';", source)
                self.assertIn(f"same_nat value' {ordinal}", source)
                self.assertIn(f"same_nat {escaped} {ordinal}", source)
                self.assertIn(f"same_nat (add value' {escaped}) {2 * ordinal}", source)
                self.assertIn(f"match same_nat {ordinal} {ordinal + 1} with | True => 1 | False => 0 end", source)
                self.assertEqual(expected, 0)
                self.assertFalse(units_needed)

    def test_character_form_runtime_rejects_wrong_and_truncated_values(self):
        from ourosmith.surface.forms import run_forms
        from ourosmith.surface.gen import nat_output
        from ourosmith.surface.run import SurfaceRunner

        work = ROOT / "_build/smith/selftest"
        work.mkdir(parents=True, exist_ok=True)
        controls = [(0, nat_output(0), True), (0, nat_output(1), False),
                    (0, "<nat-too-large> : Nat\n", False), (0, nat_output(0) + "extra\n", False),
                    (1, nat_output(0), False)]
        for code, stdout, passed in controls:
            with self.subTest(code=code, stdout=stdout), tempfile.TemporaryDirectory(dir=work) as directory:
                with patch("ourosmith.surface.run.environment", return_value={}):
                    runner = SurfaceRunner(report(), Path(directory), [3], shrink_budget=0,
                                           overrides={"ouro1": Path("unused"), "ouro-fmt": Path("unused")})
                runner.seed = 3

                def formatted(_argv, directory, _prop):
                    return RunResult("ok", 0, (directory / "main.ouro").read_text(encoding="utf-8"), "", 0, 0)

                with patch.object(runner, "accepts", return_value="checked"), \
                     patch.object(runner, "command", side_effect=formatted), \
                     patch.object(runner, "native", return_value=RunResult("ok", code, stdout, "", 0, 0)):
                    run_forms(runner, only="character-scalar")
                self.assertEqual(not runner.report.findings, passed)
                if not passed:
                    self.assertEqual(len(runner.report.findings), 1)
                    self.assertEqual(runner.report.findings[0].prop, "form-runtime-character-scalar")
                    self.assertEqual(runner.report.findings[0].expected, nat_output(0))

    def test_abstention_and_empty_are_not_passes(self):
        value = report()
        self.assertTrue(value.passed)
        value.layer("kernel").abstain("python:unsupported-core")
        self.assertFalse(value.passed)
        value = report()
        value.layer("kernel").cases = 0
        self.assertFalse(value.passed)

    def test_skip_and_gap_fail(self):
        value = report()
        value.skip("compiler", "unavailable")
        self.assertFalse(value.passed)
        value = report()
        value.gap("kernel", "constructor", "no strategy", blocking=True)
        self.assertFalse(value.passed)

    def test_timing_is_not_in_fingerprint(self):
        a, b = report(), report()
        a.timing["total"] = 1
        b.timing["total"] = 90
        self.assertEqual(a.fingerprint(), b.fingerprint())

    def test_invalid_cli_fails_before_running(self):
        import ouro_smith

        cases = (["run", "--layer", "nonexistent"], ["run", "--layer", ""], ["run", "--seeds", "0"],
                 ["run", "--layer", "kernel,kernel"], ["run", "--seed-list", ""],
                 ["run", "--seed-list", "1,1"], ["run", "--timeout", "nan"],
                 ["run", "--memory-mb", "0"], ["run", "--depth", "-1"])
        with patch.object(ouro_smith, "native_program", side_effect=AssertionError("must not execute")):
            for argv in cases:
                with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as failure:
                        ouro_smith.main(argv)
                    self.assertEqual(failure.exception.code, 2)

    def test_environment_is_scrubbed(self):
        with patch.dict(os.environ, {"SMITH_FAKE_SECRET": "sentinel", "PYTHONPATH": "untrusted", "OURO1_COMPILER": "untrusted"}):
            env = clean_env()
            for key in ("SMITH_FAKE_SECRET", "PYTHONPATH", "OURO1_COMPILER"):
                self.assertNotIn(key, env)

    def test_build_environment_preserves_visual_studio_discovery(self):
        from ourosmith import host

        with (patch.dict(os.environ, {"PROGRAMDATA": "smith-program-data", "SMITH_FAKE_SECRET": "sentinel",
                                      "OURO_C_BUILD_DIR": "smith-first"}),
              patch.object(host, "shell", return_value=Path(sys.executable)),
              patch.object(host, "build_config", wraps=host.build_config) as load):
            build = host.environment(build=True)
            with patch.dict(os.environ, {"OURO_C_BUILD_DIR": "smith-second"}):
                next_build = host.environment(build=True)
                runtime = host.environment()
        self.assertEqual(load.call_count, 3)
        for child, name in ((build, "smith-first"), (next_build, "smith-second")):
            target = ROOT / name
            self.assertEqual(child["OURO_C_BUILD_DIR"], target.as_posix())
            self.assertEqual(child["OURO_HOSTED_FMT"], (target / "ouro-fmt").as_posix())
        self.assertEqual(build["PROGRAMDATA"], "smith-program-data")
        self.assertNotIn("PROGRAMDATA", runtime)
        self.assertNotIn("SMITH_FAKE_SECRET", build)
        self.assertNotIn("SMITH_FAKE_SECRET", runtime)

    def test_user_test_runner_resolves_one_shell_per_launch(self):
        from ourosmith import host
        from ourosmith.surface import tools

        def result(code=0, stdout="", stderr=""):
            return SimpleNamespace(ok=code == 0, returncode=code, stdout=stdout, stderr=stderr)

        clean = "seed4\nok case0\nok case1\n"
        command = Mock(side_effect=[
            result(),
            result(stdout=clean),
            result(),
            result(1, clean + "FAIL broken intentional\n"),
            result(stdout="test: ok\n"),
            result(1, stderr="test: failed\n"),
            result(1, "ok run ./success_test.ouro\n", "FAIL run ./failure_test.ouro\ntest: failed\n"),
            result(1, stderr="FAIL golden\n"),
        ])
        run = SimpleNamespace(seed=4, command=command, require=lambda ok, step, *_details: self.assertTrue(ok, step),
                              tool=lambda name: name, output=lambda child: child.stdout + child.stderr)
        work = (ROOT / "_build").resolve()
        self.assertEqual(work.parent, ROOT)
        work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work, prefix="smith-launch-") as temporary:
            directory = Path(temporary)
            discover = Mock(side_effect=[directory / f"shell-{i}" / "sh" for i in range(7)])
            with patch.object(host, "shell", discover), patch.object(tools, "shell", discover):
                tools.user_test_runner(run, directory)
        self.assertEqual(discover.call_count, 4)
        shell_calls = [call for call in command.call_args_list if call.args[2] in ("test-program-build", "test-runner-discovery")]
        self.assertEqual([call.kwargs["timeout"] for call in shell_calls], [120, 120, 180])
        for call in shell_calls:
            sh = call.args[0][0]
            child = call.kwargs["env"]
            self.assertEqual(child["OURO_POSIX_SH"], sh.as_posix())
            self.assertEqual(child["PATH"].split(os.pathsep)[1], str(sh.parent))

    def test_surface_evaluator_and_shrink(self):
        from ourosmith.surface import gen

        for seed in range(40):
            ast = gen.generate(seed, 4)
            self.assertEqual(ast.json(), gen.generate(seed, 4).json())
            self.assertEqual(gen.validate(ast), "Nat")
            self.assertEqual(gen.evaluate(ast), gen.evaluate(gen.alpha_rename(ast)))
            self.assertGreaterEqual(gen.evaluate(ast), 0)
        ast = gen.Expr("add", (gen.Expr("literal", value=3), gen.Expr("literal", value=9)))
        small, attempts = gen.shrink(ast, lambda candidate: gen.evaluate(candidate) >= 3, 6)
        self.assertGreaterEqual(gen.evaluate(small), 3)
        self.assertLessEqual(attempts, 6)
        self.assertLess(len(json.dumps(small.json())), len(json.dumps(ast.json())))

    def test_clean_surface_conditionals_have_distinct_results(self):
        from ourosmith.surface import gen

        pending = [gen.generate(seed, 4) for seed in range(200)]
        conditionals = 0
        while pending:
            expr = pending.pop()
            pending.extend(expr.args)
            if expr.tag == "if":
                conditionals += 1
                self.assertNotEqual(gen.evaluate(expr.args[1]), gen.evaluate(expr.args[2]))
        self.assertGreater(conditionals, 100)

    def test_ci_shell_environment_uses_portable_paths(self):
        from ci_gate import Gate, env_for
        from local_scheduler import Allocation

        with patch.dict(os.environ, {}, clear=True):
            env = env_for(Gate("probe", [], ("pr",), env=(("PROBE_OUT", "_build/probe"),)),
                          ROOT / "_build/ci", ROOT, Allocation(1, 3072))
        for key in ("OURO_ROOT", "OURO_CACHE_DIR", "OURO_BUILD_DIR", "OURO_C_BUILD_DIR", "OURO_CI_GATE_OUT", "PROBE_OUT", "PYTHON"):
            self.assertNotIn("\\", env[key])
        self.assertEqual(env["PYTHON"], Path(sys.executable).as_posix())
        self.assertEqual(env["OURO_JOBS"], "1")
        self.assertEqual(env["OURO_SCHEDULER_MEMORY_MIB"], "3072")


    def test_surface_promotion_and_cli_alias_preserve_input(self):
        import ouro_smith
        from ourosmith.surface.corpus import validate_input
        from ourosmith.surface.mutate import mutations

        mutation = mutations(73)[0]
        source = {"mutation": mutation.name, "source": mutation.source, "diagnostics": mutation.diagnostics}
        finding = {"layer": "surface", "seed": 73, "profile": "pr", "prop": mutation.name,
                   "generator_hash": "saved", "failing_phase": mutation.name, "actual": "CHECK_OK",
                   "expected": mutation.diagnostics, "minimal_input": source, "replay": "saved replay"}
        work = ROOT / "_build/smith/selftest"
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as scratch:
            path = Path(scratch) / "finding.json"
            path.write_text(json.dumps(finding), encoding="utf-8")
            output = Path(scratch) / "corpus"
            with contextlib.redirect_stdout(io.StringIO()):
                result = ouro_smith.main(["--profile", "pr", "--update-corpus", str(path), "--name", "saved", "--dir", str(output)])
            self.assertEqual(result, 0)
            self.assertEqual(json.loads((output / "saved.json").read_text())["input"]["source"], mutation.source)
        for invalid in ({**source, "diagnostics": []}, {**source, "tool": "shell"},
                        {**source, "dependencies": [["../outside.ouro", "x"]]},
                        {**source, "dependencies": [["C:/outside.ouro", "x"]]}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_input(invalid)


class LimitTests(unittest.TestCase):
    def execute(self, source, **limits):
        return run_limited([sys.executable, "-c", source], timeout_s=limits.get("timeout", 10), memory_mb=limits.get("memory", 256))

    def assert_posix_process_exited(self, pid):
        try:
            state = Path(f"/proc/{pid}/status").read_text()
        except (FileNotFoundError, ProcessLookupError):
            return
        self.assertRegex(state, r"(?m)^State:[ \t]+[XZ](?:[ \t]|$)")

    def test_posix_process_observation_handles_reaping(self):
        for error in (FileNotFoundError(), ProcessLookupError()):
            with self.subTest(error=type(error).__name__), patch.object(Path, "read_text", autospec=True, side_effect=error) as read:
                self.assert_posix_process_exited(123)
                read.assert_called_once_with(Path("/proc/123/status"))
        for state in ("Z (zombie)", "X (dead)"):
            with self.subTest(state=state), patch.object(
                Path, "read_text", autospec=True, return_value=f"State:\t{state}\n"
            ) as read:
                self.assert_posix_process_exited(123)
                read.assert_called_once_with(Path("/proc/123/status"))
        with patch.object(Path, "read_text", autospec=True, return_value="State:\tS (sleeping)\n"), self.assertRaises(AssertionError):
            self.assert_posix_process_exited(123)
        with patch.object(Path, "read_text", autospec=True, side_effect=PermissionError()), self.assertRaises(PermissionError):
            self.assert_posix_process_exited(123)

    def test_success_and_nonzero(self):
        result = self.execute("import sys; print(sys.stdin.read()); print('err',file=sys.stderr)")
        self.assertTrue(result.ok, result)
        self.assertEqual(result.stderr, "err\n")
        result = self.execute("raise SystemExit(7)")
        self.assertEqual((result.classify(), result.returncode), ("nonzero", 7))

    def test_missing_executable(self):
        result = run_limited([str(ROOT / "_build/smith/absent-executable")], timeout_s=1, memory_mb=64)
        self.assertEqual(result.classify(), "spawn-error")

    @unittest.skipUnless(os.name == "nt", "Windows shared job limits")
    def test_shared_job_keeps_command_limit_and_aggregate_limit(self):
        from ourosmith.windows_job import Job

        for shared_memory, child_memory in ((256, 64), (64, 256)):
            with self.subTest(shared_memory=shared_memory, child_memory=child_memory):
                group = Job(shared_memory)
                try:
                    small = run_limited([sys.executable, "-c", "print('joined')"], timeout_s=10,
                        memory_mb=child_memory, shared_job=group.name)
                    self.assertTrue(small.ok, small)
                    self.assertEqual(small.stdout, "joined\n")
                    large = run_limited([sys.executable, "-c", "data = bytearray(96 * 1024 * 1024)"],
                        timeout_s=10, memory_mb=child_memory, shared_job=group.name)
                    self.assertEqual(large.classify(), "memory", large)
                finally:
                    group.close()

    @unittest.skipUnless(os.name == "nt", "Windows shared job limits")
    def test_shared_job_bounds_combined_memory_of_peer_commands(self):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from ourosmith.windows_job import Job

        with tempfile.TemporaryDirectory(prefix="ouro-shared-memory-") as folder:
            group = Job(160)
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = []
                    for index in range(2):
                        code = ("import pathlib,time\n"
                                f"root=pathlib.Path({folder!r})\n"
                                f"(root / '{index}').write_text('ready')\n"
                                "deadline=time.monotonic()+5\n"
                                "while not all((root / str(i)).exists() for i in range(2)):\n"
                                " if time.monotonic()>deadline: raise RuntimeError('peer did not start')\n"
                                " time.sleep(0.01)\n"
                                "data=bytearray(64*1024*1024)\n"
                                "time.sleep(30)\n")
                        futures.append(pool.submit(run_limited, [sys.executable, "-c", code],
                            timeout_s=10, memory_mb=128, shared_job=group.name))
                    first = next(as_completed(futures, timeout=8)).result()
                    self.assertEqual(first.classify(), "memory", first)
                    group.terminate()
                    results = [future.result(timeout=5) for future in futures]
                    self.assertTrue(all(not result.ok for result in results), results)
            finally:
                group.close()

    @unittest.skipUnless(os.name == "nt", "Windows shared job limits")
    def test_shared_job_termination_stops_all_running_commands(self):
        from concurrent.futures import ThreadPoolExecutor
        import time
        from ourosmith.windows_job import Job

        with tempfile.TemporaryDirectory(prefix="ouro-shared-job-") as folder:
            group = Job(256)
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = []
                    for index in range(2):
                        marker = Path(folder) / str(index)
                        code = f"import pathlib,time; pathlib.Path({str(marker)!r}).write_text('ready'); time.sleep(30)"
                        futures.append(pool.submit(run_limited, [sys.executable, "-c", code],
                            timeout_s=10, memory_mb=128, shared_job=group.name))
                    deadline = time.monotonic() + 5
                    while not all((Path(folder) / str(index)).exists() for index in range(2)):
                        if time.monotonic() >= deadline:
                            self.fail("shared commands did not start")
                        time.sleep(0.01)
                    group.terminate()
                    results = [future.result(timeout=5) for future in futures]
                    self.assertTrue(all(not result.ok for result in results), results)
                    self.assertTrue(all(result.status == "ok" and result.returncode != 0 for result in results), results)
            finally:
                group.close()

    def test_stdin_preserves_protocol_bytes(self):
        body = "Content-Length: 2\r\n\r\n{}"
        result = run_limited([sys.executable, "-c", "import sys; print(repr(sys.stdin.buffer.read()))"],
                             timeout_s=5, memory_mb=128, stdin_text=body)
        self.assertEqual(result.stdout.strip(), repr(body.encode()))

    def test_memory(self):
        result = self.execute("x = bytearray(256 * 1024 * 1024)", memory=64)
        self.assertEqual(result.classify(), "memory", result)

    def test_posix_rlimit_falls_back_when_sticky_hard_cap_is_rejected(self):
        from ourosmith import exec_child

        calls = []

        class Fake:
            @staticmethod
            def setrlimit(_which, pair):
                calls.append(pair)
                if pair[0] == pair[1]:
                    raise ValueError("current limit exceeds maximum limit")

        self.assertEqual(exec_child.apply_rlimit(Fake, 1, ((64, 64), (64, -1))), (64, -1))
        self.assertEqual(calls, [(64, 64), (64, -1)])
        with self.assertRaises(ValueError):
            exec_child.apply_rlimit(Fake, 1, ((8, 8),))

    @unittest.skipIf(os.name == "nt", "POSIX resource limits")
    def test_native_stack_stays_inside_address_space_budget(self):
        result = self.execute("import json,resource; print(json.dumps([resource.getrlimit(k) for k in (resource.RLIMIT_AS, resource.RLIMIT_STACK, resource.RLIMIT_CORE)]))", memory=64)
        self.assertTrue(result.ok, result)
        address, stack, core = json.loads(result.stdout)
        self.assertEqual(core[0], 0)
        if sys.platform == "darwin":
            return
        self.assertEqual(address[0], 64 * 1024 * 1024)
        self.assertTrue(address[1] == address[0] or address[1] == -1)
        expected_stack = address[0] if stack[1] == -1 else min(address[0], stack[1])
        if stack[0] != expected_stack:
            # Hosts that pin the main-thread stack keep the inherited soft limit.
            self.assertLessEqual(stack[0], address[0])

    def test_worker_count_respects_runner_cpu_capacity(self):
        from ourosmith.host import job_count

        with patch.dict(os.environ, {"OURO_JOBS": "10"}), \
             patch("ourosmith.host.os.sched_getaffinity", return_value={0, 1}, create=True):
            self.assertEqual(job_count(), 2)
            with patch.dict(os.environ, {"OURO_JOBS": "1"}):
                self.assertEqual(job_count(), 1)

    def test_limited_build_process_can_create_a_worker(self):
        result = self.execute("import threading; t = threading.Thread(target=lambda: print('thread-ok')); t.start(); t.join()", memory=256)
        self.assertTrue(result.ok, result)
        self.assertEqual(result.stdout.strip(), "thread-ok")

    def test_timeout_kills_descendant_after_parent_exits(self):
        work = ROOT / "_build/smith/selftest"
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as scratch:
            pidfile = Path(scratch) / "child.pid"
            child = f"import os,time,pathlib; pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid())); time.sleep(60)"
            # Explicit handles keep the pipe open across Windows venv launchers
            # as well as direct Python binaries; implicit inheritance differs.
            parent = f"import subprocess,sys; subprocess.Popen([sys.executable,'-c',{child!r}], stdout=sys.stdout, stderr=sys.stderr)"
            # The tested parent must outlive no implicit venv redirector job.
            # Exercise OuroSmith's own ownership using the base interpreter.
            result = run_limited([getattr(sys, "_base_executable", sys.executable), "-c", parent], timeout_s=1, memory_mb=256)
            self.assertEqual(result.classify(), "timeout", result)
            self.assertTrue(pidfile.is_file())
            pid = int(pidfile.read_text())
            if os.name == "nt":
                from ourosmith.windows_job import W, api, close_handle, ctypes

                handle = api("OpenProcess", W.HANDLE, [W.DWORD, W.BOOL, W.DWORD])(0x1000, False, pid)
                if handle:
                    code = W.DWORD()
                    try:
                        self.assertTrue(api("GetExitCodeProcess", W.BOOL, [W.HANDLE, ctypes.POINTER(W.DWORD)])(handle, ctypes.byref(code)))
                        self.assertNotEqual(code.value, 259)
                    finally:
                        close_handle(handle)
            else:
                # A just-orphaned killed process can briefly be a zombie.
                self.assert_posix_process_exited(pid)


def run() -> int:
    from ourosmith.native_selftest import NativeHarnessTests
    from ourosmith.checker_fault_selftest import CheckerFaultTests
    from ourosmith.native_inputs_test import ManifestBatchesTests
    from ourosmith.producer_selftest import ProducerTests
    from ourosmith import compiler_evidence_test

    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(NativeHarnessTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(CheckerFaultTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(ManifestBatchesTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(ProducerTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(compiler_evidence_test))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    path = ROOT / "_build/smith/selftest/report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"kind": "ouro.smith-selftest.v1", "pass": result.wasSuccessful(),
                               "generator_hash": generator_hash(), "tests": result.testsRun,
                               "failures": len(result.failures), "errors": len(result.errors),
                               "skips": len(result.skipped)}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if result.wasSuccessful() else 1
