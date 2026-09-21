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

            def build(command, log, **kwargs):
                self.assertEqual(Path(command[2]), ROOT / "scripts/native_tool_build.py")
                self.assertEqual(command[command.index("--compiler") + 1], str(fixture.compiler))
                self.assertEqual(command[command.index("--jobs") + 1], "1")
                self.assertEqual(kwargs["timeout_s"], 900)
                target = Path(command[4])
                self.assertTrue(target.is_relative_to(fixture.directory / "smith-tools"))
                fixture.installed(next(tool for tool in host.TOOLS if host.tool_entry(tool) == command[3]), target)
                calls.append((target, log))

            with patch.object(host, "build_config", return_value=SimpleNamespace(path=lambda _key: fixture.directory)), \
                 patch.object(host, "build_command", side_effect=build):
                first = host.prepare_tools(fixture.directory / "first", fixture.compiler)
                second = host.prepare_tools(fixture.directory / "repeat", fixture.compiler)
            self.assertEqual(first, second)
            self.assertEqual(len(calls), 2 * len(host.TOOLS))
            self.assertNotEqual(calls[0][1], calls[len(host.TOOLS)][1])

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
