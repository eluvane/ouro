"""A selected producer owns every executed layer and every source-bound tool."""
from __future__ import annotations

import argparse
import contextlib
import copy
import io
import itertools
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ourosmith import ROOT
from ourosmith import host
from ourosmith.native import digest, source_inputs
from repo_support import hash_json


class ProducerTests(unittest.TestCase):
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
        import subprocess

        with self.surface_native_fixture() as (native, args, log), \
             patch.object(native.subprocess, "run", wraps=subprocess.run) as execute:
            cold = native.build_native(args)
            args.generated.write_text("int sample(void) { return 2; }\n", encoding="utf-8")
            warm = native.build_native(args)
            self.assertEqual([row["cache"] for row in cold["runtime"]], ["miss"] * 3)
            self.assertEqual([row["cache"] for row in warm["runtime"]], ["hit"] * 3)
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

            def installed(tool, path, entry=None):
                from native_tool_build import tool_companions

                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((tool + " binary fixture\n").encode() * 400)
                entry = host.tool_entry(tool) if entry is None else entry
                for companion in tool_companions(entry):
                    companion_path = path.parent / (companion[1] + (".exe" if os.name == "nt" else ""))
                    installed(companion[1], companion_path, companion[0])
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
        with self.fixture() as fixture:
            calls = []

            scheduled = host.scheduled_tool_builds()

            def build(command, log, **kwargs):
                self.assertEqual(Path(command[2]), ROOT / "scripts/native_tool_build.py")
                self.assertEqual(command[command.index("--compiler") + 1], str(fixture.compiler))
                self.assertEqual(command[command.index("--jobs") + 1], "1")
                self.assertEqual(kwargs["timeout_s"], 900)
                target = Path(command[4])
                self.assertTrue(target.is_relative_to(fixture.directory / "smith-tools"))
                entry = command[3]
                matched = [item for item in scheduled if item[0] == entry]
                self.assertEqual(len(matched), 1)
                fixture.installed(matched[0][1], target, entry)
                calls.append((target, log))

            with patch.object(host, "build_config", return_value=SimpleNamespace(path=lambda _key: fixture.directory)), \
                 patch.object(host, "build_command", side_effect=build):
                first = host.prepare_tools(fixture.directory / "first", fixture.compiler)
                second = host.prepare_tools(fixture.directory / "repeat", fixture.compiler)
            self.assertEqual(first, second)
            self.assertEqual(len(calls), 2 * len(scheduled))
            self.assertGreater(len(scheduled), len(host.TOOLS))
            self.assertNotEqual(calls[0][1], calls[len(scheduled)][1])

    def test_invalid_explicit_producer_precedes_any_execution_or_tool_build(self):
        import ouro_smith

        with self.fixture() as fixture, patch.object(ouro_smith, "prepare") as native, \
             patch.object(ouro_smith, "prepare_tools") as surface, \
             patch.object(ouro_smith, "run_faults") as faults, \
             patch.object(ouro_smith, "load_cases", return_value=[]), \
             contextlib.redirect_stderr(io.StringIO()):
            for command in (["run", "--seeds", "1", "--no-inventory"], ["replay", "--layer", "surface", "--seed", "1"],
                            ["replay", "--layer", "kernel", "--seed", "1"], ["corpus"], ["faults"]):
                with self.subTest(command=command):
                    self.assertEqual(ouro_smith.main([*command, "--compiler", str(fixture.directory / "missing"),
                                                     "--out", str(fixture.directory / "run")]), 1)
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
            with patch.object(fe, "regenerate") as frontend, patch.object(fe, "collect_units", return_value=[]), \
                 patch.object(fe, "run_pack"), patch("ourosmith.surface_faults.subprocess.run") as emit, \
                 patch.object(sl, "emit_backend") as backend, patch.object(sl, "build_stage_binary") as link:
                build_frontend(scratch, fixture.compiler)
            self.assertEqual(frontend.call_args.kwargs["ouro1"], fixture.compiler)
            self.assertEqual(frontend.call_args.kwargs["jobs"], 1)
            self.assertEqual(emit.call_args.args[0][0], fixture.compiler.as_posix())
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
