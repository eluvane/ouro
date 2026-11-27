#!/usr/bin/env python3
"""Regression tests for selfhost bootstrap evidence reporting."""
from __future__ import annotations

import copy
import json
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import selfhost_bootstrap_evidence as evidence  # noqa: E402


def native_fixture(root: Path) -> dict:
    """Synthetic receipt/PE wire data for validation only; no image is executed."""
    import bootstrap_compiler as bootstrap
    import bootstrap_inputs
    from frontend_regen import FRONTEND_TUS
    from native_tool_build import BUILD_INPUTS, RUNTIME, tool_roots

    def write(name, data=b"fixture\n"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return {"path": name, "sha256": evidence.sha256_file(path)}

    def inventory(names):
        return {name: evidence.sha256_file(root / name) for name in sorted(names)}

    roots = [source for _tag, _module, source, _file in FRONTEND_TUS] + ["compiler/backend.ouro"]
    for name in {*roots, *bootstrap.ACCEPTANCE_ROOTS, *bootstrap.HELPERS, *bootstrap.RUNTIME,
                 *bootstrap_inputs.STAGE0, bootstrap_inputs.ARCHIVE, bootstrap_inputs.MANIFEST,
                 *BUILD_INPUTS, *RUNTIME}:
        write(name)
    write("compiler/native_wire.ouro")
    write(evidence.NATIVE_ENTRY, b'import "../compiler/native_wire.ouro";\n')
    units = evidence.native_units(root, evidence.NATIVE_ENTRY)
    inputs = {"entry": evidence.NATIVE_ENTRY, "units": units, "sources": inventory(units),
              "config": dict(evidence.NATIVE_CONFIG)}
    key = evidence.hash_json(inputs)
    seed = write("_build/seed", bytes(8192))
    graph = {entry: evidence.native_units(root, entry) for entry in [*roots, *bootstrap.ACCEPTANCE_ROOTS]}
    headers = {path.relative_to(root).as_posix() for path in (root / "runtime").glob("*.h")}
    selected = {"kind": bootstrap.KIND, "roots": roots, "unit_graph": graph,
                "sources": inventory(set(bootstrap.HELPERS) | set(bootstrap.RUNTIME) | headers
                                     | {name for entries in graph.values() for name in entries}),
                "stage0": inventory(bootstrap_inputs.STAGE0),
                "archive_sha256": evidence.sha256_file(root / bootstrap_inputs.ARCHIVE),
                "manifest_sha256": evidence.sha256_file(root / bootstrap_inputs.MANIFEST)}
    work = root / "_build/seed-work"
    comparison = {}
    for name in ("driver_u.c", "backend_u.c"):
        ref = write("_build/seed-work/out/p1/" + name)
        write("_build/seed-work/out/p2/" + name)
        comparison[name] = {"p1_sha256": ref["sha256"], "p2_sha256": ref["sha256"]}
    write("_build/seed-work/inputs.json", json.dumps(selected).encode())
    seed_report = {"kind": bootstrap.KIND, "pass": True, "key": evidence.hash_json(selected),
                   "binary_sha256": seed["sha256"], "complete_generated_c_comparison": comparison,
                   "inputs_sha256": evidence.sha256_file(work / "inputs.json")}
    seed_report_ref = write("_build/seed-work/report.json", json.dumps(seed_report).encode())
    seed_receipt = {"kind": bootstrap.KIND, "key": seed_report["key"], "selected": selected,
                    "binary_sha256": seed["sha256"], "work": str(work), "report_sha256": seed_report_ref["sha256"]}
    seed_receipt_ref = write("_build/seed.bootstrap.json", json.dumps(seed_receipt).encode())
    producer = write("_build/P.exe", b"C-hosted wire producer")
    names = set(BUILD_INPUTS) | set(RUNTIME) | headers
    names.update(name for entry in tool_roots(evidence.NATIVE_ENTRY) for name in evidence.native_units(root, entry))
    tool_inputs = {"kind": "ouro.native-tool-build.v1", "entry": evidence.NATIVE_ENTRY,
                   "compiler_sha256": seed["sha256"], "fuel": 200000, "sources": inventory(names),
                   "cc": "wire-cc", "cc_sha256": "0" * 64, "platform": "win32", "machine": "win-amd64",
                   "cflags": ["-O1"], "link_flags": [], "environment": {}}
    receipt = {"kind": tool_inputs["kind"], "key": evidence.hash_json(tool_inputs), "inputs": tool_inputs,
               "binary_sha256": producer["sha256"], "cache": "miss"}
    receipt_ref = write("_build/P.exe.build.json", json.dumps(receipt).encode())
    ordered_sources = list(dict.fromkeys([*(name for entry in tool_roots(evidence.NATIVE_ENTRY) for name in evidence.native_units(root, entry)),
                                         *BUILD_INPUTS, *RUNTIME,
                                         *(path.relative_to(root).as_posix() for path in sorted((root / "runtime").glob("*.h")))]))
    manifest_ref = write("_build/P.exe.sources", ("\n".join(ordered_sources) + "\n").encode())

    # Independent PE layout: one executable section and a terminated named import.
    image = bytearray(1024)
    image[:2] = b"MZ"
    struct.pack_into("<I", image, 0x3C, 128)
    image[128:132] = b"PE\0\0"
    struct.pack_into("<HH", image, 132, 0x8664, 1)
    struct.pack_into("<H", image, 148, 240)
    struct.pack_into("<H", image, 152, 0x20B)
    struct.pack_into("<I", image, 168, 0x1000)
    struct.pack_into("<I", image, 260, 16)
    struct.pack_into("<II", image, 272, 0x1100, 40)
    struct.pack_into("<IIII", image, 400, 512, 0x1000, 512, 512)
    struct.pack_into("<I", image, 428, 0x60000020)
    struct.pack_into("<I", image, 768, 0x1160)
    struct.pack_into("<I", image, 780, 0x1150)
    image[848:861] = b"kernel32.dll\0"
    stages = []
    previous = producer
    for stage in ("N1", "N2", "N3"):
        emitted = {**write("_build/" + stage + ".exe", bytes(image)), "imports": ["kernel32.dll"]}
        stages.append({"stage": stage, "status": "pass", "process_status": "ok", "exit_code": 0, "backend": "ouro-native",
                       "runtime": "ouro-native", "inputs_sha256": key, "inputs_after_sha256": key,
                       "producer": previous, "producer_after_sha256": previous["sha256"], "image": emitted,
                       "argv": [str(root / previous["path"]), evidence.NATIVE_ENTRY, emitted["path"], *units],
                       "cwd": str(root), "stdout": write("_build/" + stage + ".stdout", (emitted["path"] + "\n").encode()),
                       "stderr": write("_build/" + stage + ".stderr", b"")})
        previous = {name: emitted[name] for name in ("path", "sha256")}
    behavior = []
    for stage in ("N2", "N3"):
        compiler = {name: stages[int(stage[1]) - 1]["image"][name] for name in ("path", "sha256")}
        for suite in ("compiler", "runtime", "tools"):
            name = stage + "-" + suite
            stdout = write("_build/" + name + ".stdout", b"observed\n")
            stderr = write("_build/" + name + ".stderr", b"")
            expected_stdout = write("tests/" + suite + ".stdout.golden", b"observed\n")
            expected_stderr = write("tests/" + suite + ".stderr.golden", b"")
            source = write("tests/" + suite + ".ouro")
            program_inputs = {"entry": source["path"], "units": [source["path"]],
                              "sources": {source["path"]: source["sha256"]}, "config": dict(evidence.NATIVE_CONFIG)}
            program_key = evidence.hash_json(program_inputs)
            emitted = {**write("_build/" + name + ".exe", bytes(image)), "imports": ["kernel32.dll"]}
            program = {"status": "pass", "process_status": "ok", "exit_code": 0, "backend": "ouro-native", "runtime": "ouro-native",
                       "inputs": program_inputs, "inputs_sha256": program_key, "inputs_after_sha256": program_key,
                       "producer": compiler, "producer_after_sha256": compiler["sha256"], "image": emitted,
                       "argv": [str(root / compiler["path"]), source["path"], emitted["path"], source["path"]],
                       "cwd": str(root), "stdout": write("_build/" + name + ".build.stdout", (emitted["path"] + "\n").encode()),
                       "stderr": write("_build/" + name + ".build.stderr", b"")}
            checks = [{"name": "wire observation", "status": "pass", "process_status": "ok", "exit_code": 0, "expected_exit_code": 0,
                       "argv": [str(root / emitted["path"])],
                       "stdout": stdout, "stderr": stderr,
                       "expected_stdout": expected_stdout, "expected_stderr": expected_stderr}]
            behavior.append({"stage": stage, "suite": suite, "status": "pass", "process_status": "ok", "exit_code": 0,
                             "compiler": compiler, "inputs_sha256": key, "inputs_after_sha256": key,
                             "sources": {ref["path"]: ref["sha256"] for ref in (source, expected_stdout, expected_stderr)},
                             "roots": [source["path"]], "programs": [program],
                             "skipped": 0, "checks": checks, "stdout": stdout, "stderr": stderr})
    return {"kind": evidence.NATIVE_RESULT_KIND, "schema_version": 1, "source_revision": "1" * 40,
            "inputs": inputs, "inputs_sha256": key,
            "producer": {"origin": "c-hosted", "image": producer, "receipt": receipt_ref,
                         "manifest": manifest_ref, "seed": seed, "seed_receipt": seed_receipt_ref}, "stages": stages, "behavior": behavior}


class SelfhostBootstrapEvidenceTests(unittest.TestCase):
    def native_report(self, root: Path, result: dict):
        path = root / "_build/native-result.json"
        path.write_text(json.dumps(result), encoding="utf-8")
        metadata = {"git_available": True, "git_head": "1" * 40}
        with patch.object(evidence, "repo_metadata", return_value=metadata), patch.object(evidence, "run_command") as command:
            report, code = evidence.build_native_report(root=root, out=root / "evidence.json", result_path=path)
        command.assert_not_called()
        return report, code

    def assert_native_failure(self, root: Path, result: dict, message: str):
        report, code = self.native_report(root, result)
        self.assertEqual((report["summary"]["status"], code), ("fail", 1), report)
        self.assertIn(message, " ".join(report["summary"]["hard_errors"]))
        return report

    def test_native_wire_protocol_requires_separate_equality_behavior_and_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = native_fixture(root)
            shared = result["behavior"][0]["stderr"]
            for row in [*result["stages"], *result["behavior"]]:
                row["stderr"] = shared
                for record in row.get("programs", []) + row.get("checks", []):
                    record["stderr"] = shared
            report, code = self.native_report(root, result)
            self.assertEqual((report["summary"]["status"], code), ("pass", 0), report)
            self.assertEqual(report["kind"], evidence.NATIVE_REPORT_KIND)
            self.assertNotEqual(report["kind"], evidence.REPORT_KIND)
            self.assertEqual((len(report["stages"]), len(report["tests"])), (3, 6))
            self.assertTrue(report["summary"]["converged"])
            self.assertTrue(report["summary"]["behavior_accepted"])
            self.assertTrue(report["summary"]["provenance_accepted"])
            self.assertFalse(report["summary"]["native_seed_promoted"])
            self.assertFalse(report["summary"]["isolated_host_accepted"])

    def test_native_missing_or_skipped_behavior_cannot_use_stage_equality(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = native_fixture(root)
            mutations = [([], "behavior is missing"), (result["behavior"][:-1], "behavior is missing")]
            for behavior, message in mutations:
                changed = {**result, "behavior": behavior}
                report = self.assert_native_failure(root, changed, message)
                self.assertTrue(report["summary"]["converged"])
            for field, value, message in (("status", "skipped", "failed, skipped"), ("skipped", 1, "skipped checks"),
                                          ("checks", [], "no executed checks"), ("exit_code", False, "failed, skipped")):
                changed = copy.deepcopy(result)
                changed["behavior"][0][field] = value
                self.assert_native_failure(root, changed, message)

    def test_native_missing_failed_or_reordered_stages_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = native_fixture(root)
            for stages in ([], result["stages"][:-1], list(reversed(result["stages"])), [result["stages"][0]] * 3):
                with self.subTest(stages=[row["stage"] for row in stages]):
                    self.assert_native_failure(root, {**result, "stages": stages}, "ordered N1, N2, N3")
            for field, value, message in (("status", "timeout", "failed, skipped"), ("exit_code", 7, "failed, skipped"),
                                          ("backend", "legacy-c", "native backend/runtime"), ("runtime", "c", "native backend/runtime"),
                                          ("producer_after_sha256", "0" * 64, "producer changed"),
                                          ("inputs_after_sha256", "0" * 64, "input identity changed")):
                changed = copy.deepcopy(result)
                changed["stages"][1][field] = value
                self.assert_native_failure(root, changed, message)
            changed = copy.deepcopy(result)
            changed["stages"][1]["producer"] = result["producer"]["image"]
            self.assert_native_failure(root, changed, "producer changed")
            changed = copy.deepcopy(result)
            changed["stages"][0]["argv"] = changed["stages"][0]["argv"][:-1]
            self.assert_native_failure(root, changed, "exact source closure")

    def test_native_stale_source_producer_image_and_origin_are_rejected(self):
        for name, message in (("compiler/native_wire.ouro", "stale native evidence file"),
                              ("_build/P.exe", "stale native evidence file"), ("_build/N1.exe", "stale native evidence file"),
                              ("_build/seed", "stale native evidence file")):
            with self.subTest(path=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                result = native_fixture(root)
                with (root / name).open("ab") as stream:
                    stream.write(b"changed")
                self.assert_native_failure(root, result, message)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = native_fixture(root)
            self.assert_native_failure(root, {**result, "source_revision": "2" * 40}, "source revision")
            changed = copy.deepcopy(result)
            changed["producer"]["origin"] = "native-seed"
            self.assert_native_failure(root, changed, "C-hosted origin")
            changed = copy.deepcopy(result)
            changed["inputs"]["units"] = list(reversed(changed["inputs"]["units"]))
            self.assert_native_failure(root, changed, "ordered source closure")

    def test_native_incomplete_p_and_failed_seed_receipts_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = native_fixture(root)
            ref = result["producer"]["receipt"]
            path = root / ref["path"]
            receipt = json.loads(path.read_text(encoding="utf-8"))
            del receipt["inputs"]["sources"][evidence.NATIVE_ENTRY]
            receipt["key"] = evidence.hash_json(receipt["inputs"])
            path.write_text(json.dumps(receipt), encoding="utf-8")
            ref["sha256"] = evidence.sha256_file(path)
            self.assert_native_failure(root, result, "P build source inventory is incomplete")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = native_fixture(root)
            path = root / "_build/seed-work/report.json"
            seed_report = json.loads(path.read_text(encoding="utf-8"))
            seed_report["pass"] = False
            path.write_text(json.dumps(seed_report), encoding="utf-8")
            ref = result["producer"]["seed_receipt"]
            receipt_path = root / ref["path"]
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["report_sha256"] = evidence.sha256_file(path)
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            ref["sha256"] = evidence.sha256_file(receipt_path)
            self.assert_native_failure(root, result, "C seed acceptance receipt")

    def test_native_complete_image_comparison_rejects_changed_runtime_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = native_fixture(root)
            path = root / "_build/N3.exe"
            data = bytearray(path.read_bytes())
            data[-1] = 1
            path.write_bytes(data)
            result["stages"][2]["image"]["sha256"] = evidence.sha256_file(path)
            result["backend_eq"] = result["frontend_eq"] = result["fixpoint"] = True
            report = self.assert_native_failure(root, result, "complete images differ")
            self.assertFalse(report["summary"]["converged"])
            self.assertEqual(report["comparisons"][0]["policy"], "all-file-bytes")

    def test_native_seed_receipt_must_bind_the_second_bridge_package(self):
        import bootstrap_inputs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = native_fixture(root)
            for name in (bootstrap_inputs.BRIDGE2_ARCHIVE, bootstrap_inputs.BRIDGE2_MANIFEST):
                (root / name).write_bytes(b"second bridge fixture")
            self.assert_native_failure(root, result, "C seed second bridge inventory is incomplete")

    def test_native_seed_truthy_non_boolean_pass_is_rejected(self):
        for value in ("false", 1, None):
            with self.subTest(seed_pass=value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                result = native_fixture(root)
                path = root / "_build/seed-work/report.json"
                seed_report = json.loads(path.read_text(encoding="utf-8"))
                if value is None:
                    seed_report.pop("pass")
                else:
                    seed_report["pass"] = value
                path.write_text(json.dumps(seed_report), encoding="utf-8")
                ref = result["producer"]["seed_receipt"]
                receipt_path = root / ref["path"]
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                receipt["report_sha256"] = evidence.sha256_file(path)
                receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
                ref["sha256"] = evidence.sha256_file(receipt_path)
                self.assert_native_failure(root, result, "requires boolean pass=true")

    def test_native_stage_images_cannot_physically_alias_seeds_producers_or_stages(self):
        for kind in ("hardlink", "resolved"):
            for stage, target in ((1, 0), (2, 1), (2, 0)):
                with self.subTest(kind=kind, stage=stage, target=target), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    result = native_fixture(root)
                    name = result["stages"][stage]["image"]["path"]
                    other = result["stages"][target]["image"]["path"]
                    if kind == "hardlink":
                        output = root / name
                        output.unlink()
                        output.hardlink_to(root / other)
                        self.assert_native_failure(root, result, "image aliases another")
                    else:
                        original = evidence.native_path

                        def resolved_alias(repo, requested, original=original, other=other, name=name):
                            return original(repo, other if requested == name else requested)

                        with patch.object(evidence, "native_path", side_effect=resolved_alias):
                            self.assert_native_failure(root, result, "image aliases another")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = native_fixture(root)
            producer = result["producer"]
            output = root / producer["image"]["path"]
            output.unlink()
            output.hardlink_to(root / producer["seed"]["path"])
            producer["image"]["sha256"] = evidence.sha256_file(output)
            receipt_path = root / producer["receipt"]["path"]
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["binary_sha256"] = producer["image"]["sha256"]
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            producer["receipt"]["sha256"] = evidence.sha256_file(receipt_path)
            result["stages"][0]["producer_after_sha256"] = producer["image"]["sha256"]
            self.assert_native_failure(root, result, "image aliases another")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = native_fixture(root)
            original = evidence.native_units
            calls = 0

            def changed_identity(repo, entry):
                nonlocal calls
                ordered = original(repo, entry)
                if entry == "tests/tools.ouro":
                    calls += 1
                    if calls == 3:
                        output = root / result["stages"][2]["image"]["path"]
                        output.unlink()
                        output.hardlink_to(root / result["stages"][1]["image"]["path"])
                return ordered

            with patch.object(evidence, "native_units", side_effect=changed_identity):
                self.assert_native_failure(root, result, "image file identity changed during collection")

    def test_native_program_images_cannot_physically_alias_stages_or_other_programs(self):
        for kind in ("hardlink", "resolved"):
            for target in ("producer", "previous-stage", "other-stage", "program"):
                with self.subTest(kind=kind, target=target), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    result = native_fixture(root)
                    row = result["behavior"][1 if target == "program" else 0]
                    program = row["programs"][0]
                    targets = {"producer": row["compiler"], "previous-stage": result["stages"][0]["image"],
                               "other-stage": result["stages"][2]["image"],
                               "program": result["behavior"][0]["programs"][0]["image"]}
                    name, other = program["image"]["path"], targets[target]["path"]
                    if kind == "hardlink":
                        output = root / name
                        output.unlink()
                        output.hardlink_to(root / other)
                        self.assert_native_failure(root, result, "image aliases another")
                    else:
                        original = evidence.native_path

                        def resolved_alias(repo, requested, original=original, other=other, name=name):
                            return original(repo, other if requested == name else requested)

                        with patch.object(evidence, "native_path", side_effect=resolved_alias):
                            self.assert_native_failure(root, result, "image aliases another")

    def test_native_windows_case_and_resolved_oracle_alias_are_rejected(self):
        for directory in ("_BUILD", "_CACHE"):
            with self.subTest(directory=directory), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                result = native_fixture(root)
                name = directory + "/oracle.golden"
                path = root / name
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(b"observed\n")
                ref = {"path": name, "sha256": evidence.sha256_file(path)}
                result["behavior"][0]["sources"][name] = ref["sha256"]
                result["behavior"][0]["checks"][0]["expected_stdout"] = ref
                with patch.object(evidence, "NATIVE_WINDOWS_PATHS", True):
                    self.assert_native_failure(root, result, "expectation is a build/cache output")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = native_fixture(root)
            check = result["behavior"][0]["checks"][0]
            original = evidence.native_path

            # Model the resolved target of an internal file symlink without
            # requiring Windows' optional symlink-creation privilege.
            def resolved_alias(repo, name):
                if name == check["expected_stdout"]["path"]:
                    return original(repo, check["stdout"]["path"])
                return original(repo, name)

            with patch.object(evidence, "native_path", side_effect=resolved_alias):
                self.assert_native_failure(root, result, "expectation is a build/cache output")

    def test_native_source_owned_hardlink_oracle_cannot_alias_raw_output(self):
        for target in ("raw", "later-raw", "later-image", "build-manifest"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                result = native_fixture(root)
                row = result["behavior"][0]
                check = row["checks"][0]
                ref = check["expected_stdout"]
                aliases = {"raw": check["stdout"], "later-raw": result["behavior"][-1]["checks"][0]["stdout"],
                           "later-image": result["behavior"][-1]["programs"][0]["image"],
                           "build-manifest": result["producer"]["manifest"]}
                alias = root / aliases[target]["path"]
                expected = root / ref["path"]
                expected.unlink()
                expected.hardlink_to(alias)
                ref["sha256"] = evidence.sha256_file(expected)
                row["sources"][ref["path"]] = ref["sha256"]
                actual = root / check["stdout"]["path"]
                actual.write_bytes(expected.read_bytes())
                check["stdout"]["sha256"] = evidence.sha256_file(actual)
                self.assert_native_failure(root, result, "expectation aliases an actual output")

    def test_native_emission_requires_exact_stdout_and_preserves_diagnostic_stderr(self):
        for label in ("stage", "program"):
            for transcript in ("generic", "wrong-path", "empty", "truncated", "crlf"):
                with self.subTest(emission=label, transcript=transcript), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    result = native_fixture(root)
                    row = result["stages"][0] if label == "stage" else result["behavior"][0]["programs"][0]
                    path = root / row["stdout"]["path"]
                    transcripts = {"generic": b"EMIT_OK\n", "wrong-path": b"_build/wrong.exe\n", "empty": b"",
                                   "truncated": row["image"]["path"].encode(),
                                   "crlf": (row["image"]["path"] + "\r\n").encode()}
                    path.write_bytes(transcripts[transcript])
                    row["stdout"]["sha256"] = evidence.sha256_file(path)
                    self.assert_native_failure(root, result, "stdout does not name the emitted image exactly")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = native_fixture(root)
            ref = result["stages"][0]["stderr"]
            path = root / ref["path"]
            path.write_bytes(b"diagnostic: phase sample\n")
            ref["sha256"] = evidence.sha256_file(path)
            report, code = self.native_report(root, result)
            self.assertEqual((report["summary"]["status"], code), ("pass", 0), report)

    def test_native_dependency_addition_during_collection_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = native_fixture(root)
            original = evidence.native_units
            calls = 0

            def changing_units(repo, entry):
                nonlocal calls
                if entry == "tests/tools.ouro":
                    calls += 1
                    if calls == 3:
                        (root / "runtime/added.h").write_bytes(b"new dependency\n")
                return original(repo, entry)

            with patch.object(evidence, "native_units", side_effect=changing_units):
                self.assert_native_failure(root, result, "dependency inventory changed during collection")

    def test_native_behavior_assertions_reject_wrong_output_and_compiler(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = native_fixture(root)
            changed = copy.deepcopy(result)
            changed["behavior"][0]["compiler"] = result["producer"]["image"]
            self.assert_native_failure(root, changed, "compiler or inputs changed")
            changed = copy.deepcopy(result)
            changed["behavior"][1]["programs"] = []
            self.assert_native_failure(root, changed, "no source-bound native programs")
            changed = copy.deepcopy(result)
            changed["behavior"][0]["programs"][0]["producer"] = result["producer"]["image"]
            self.assert_native_failure(root, changed, "producer changed")
            changed = copy.deepcopy(result)
            changed["behavior"][0]["checks"][0]["argv"] = [result["producer"]["image"]["path"]]
            self.assert_native_failure(root, changed, "bound native image")
            changed = copy.deepcopy(result)
            ref = changed["behavior"][0]["stdout"]
            changed["behavior"][0]["sources"][ref["path"]] = ref["sha256"]
            changed["behavior"][0]["checks"][0]["expected_stdout"] = ref
            self.assert_native_failure(root, changed, "expectation is a build/cache output")
            changed = copy.deepcopy(result)
            changed["behavior"][0]["checks"][0]["exit_code"] = 7
            self.assert_native_failure(root, changed, "failed, skipped, or duplicate check")
            changed = copy.deepcopy(result)
            changed["behavior"][0]["checks"][0].update(exit_code=1, expected_exit_code=1, process_status="memory")
            self.assert_native_failure(root, changed, "failed, skipped, or duplicate check")
            changed = copy.deepcopy(result)
            changed["behavior"][0]["checks"][0].update(exit_code=-1, expected_exit_code=-1)
            self.assert_native_failure(root, changed, "failed, skipped, or duplicate check")
            path = root / "_build/N2-compiler.stdout"
            path.write_bytes(b"wrong\n")
            changed = copy.deepcopy(result)
            ref = {"path": "_build/N2-compiler.stdout", "sha256": evidence.sha256_file(path)}
            changed["behavior"][0]["stdout"] = ref
            changed["behavior"][0]["checks"][0]["stdout"] = ref
            self.assert_native_failure(root, changed, "stdout differs")

    def test_native_invalid_paths_schema_and_signed_images_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = native_fixture(root)
            self.assert_native_failure(root, {**result, "kind": evidence.REPORT_KIND}, "unsupported native observation schema")
            self.assert_native_failure(root, {**result, "schema_version": True}, "unsupported native observation schema")
            changed = copy.deepcopy(result)
            changed["producer"]["image"]["path"] = "../P.exe"
            self.assert_native_failure(root, changed, "repository-relative")
            changed = copy.deepcopy(result)
            changed["stages"][0]["image"]["imports"] = ["ucrtbase.dll"]
            self.assert_native_failure(root, changed, "legacy imports")
            path = root / "_build/N1.exe"
            data = bytearray(path.read_bytes())
            struct.pack_into("<II", data, 128 + 24 + 144, 1000, 8)
            path.write_bytes(data)
            result["stages"][0]["image"]["sha256"] = evidence.sha256_file(path)
            self.assert_native_failure(root, result, "complete unsigned PE images")
            path = root / "duplicate.json"
            path.write_text('{"status":"fail","status":"pass"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate native evidence field"):
                evidence.native_json(path)

    def test_native_mode_rejects_partial_success_and_never_runs_c_stage_loop(self):
        for option in ("--allow-partial", "--no-stage-loop", "--test-command=x"):
            with self.subTest(option=option), patch.object(evidence, "build_report") as legacy:
                with self.assertRaises(SystemExit) as exit_info:
                    evidence.main(["--native-result", "missing.json", option])
                self.assertEqual(exit_info.exception.code, 2)
                legacy.assert_not_called()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "observation.json"
            source.write_text(json.dumps({"kind": evidence.NATIVE_RESULT_KIND}), encoding="utf-8")
            with patch.object(evidence, "ROOT", root), patch.object(evidence, "build_native_report") as native:
                with self.assertRaises(SystemExit) as exit_info:
                    evidence.main(["--native-result", "observation.json", "--out", "observation.json"])
                self.assertEqual(exit_info.exception.code, 2)
                native.assert_not_called()
            self.assertEqual(json.loads(source.read_text(encoding="utf-8"))["kind"], evidence.NATIVE_RESULT_KIND)

    def test_native_output_cannot_overwrite_native_kind_inputs_on_success_or_failure(self):
        payload = (json.dumps({"kind": evidence.NATIVE_REPORT_KIND}) + "\n").encode()
        for role in ("golden", "raw"):
            for alias in ("direct", "hardlink"):
                for status in ("pass", "failed"):
                    with self.subTest(role=role, alias=alias, status=status), tempfile.TemporaryDirectory() as tmp:
                        root = Path(tmp)
                        result = native_fixture(root)
                        if role == "golden":
                            ref = result["behavior"][0]["checks"][0]["expected_stdout"]
                            source = root / ref["path"]
                            source.write_bytes(payload)
                            for row in result["behavior"]:
                                if row["suite"] == "compiler":
                                    row["checks"][0]["expected_stdout"]["sha256"] = evidence.sha256_file(source)
                                    row["sources"][ref["path"]] = evidence.sha256_file(source)
                                    actual = root / row["stdout"]["path"]
                                    actual.write_bytes(payload)
                                    row["stdout"]["sha256"] = evidence.sha256_file(actual)
                        else:
                            ref = result["stages"][0]["stderr"]
                            source = root / ref["path"]
                            source.write_bytes(payload)
                            ref["sha256"] = evidence.sha256_file(source)
                        result["stages"][0]["status"] = status
                        output = source if alias == "direct" else root / "_build/native-output.json"
                        if alias == "hardlink":
                            output.hardlink_to(source)
                        observation = root / "_build/native-result.json"
                        observation.write_text(json.dumps(result), encoding="utf-8")
                        with patch.object(evidence, "ROOT", root), patch.object(evidence, "run_command") as command:
                            with self.assertRaises(SystemExit) as exit_info:
                                evidence.main(["--native-result", "_build/native-result.json", "--out", output.relative_to(root).as_posix()])
                        self.assertEqual(exit_info.exception.code, 2)
                        command.assert_not_called()
                        self.assertEqual(source.read_bytes(), payload)
                        self.assertEqual(output.read_bytes(), payload)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "source.golden"
            output.write_bytes(payload)
            observation = root / "observation.json"
            observation.write_text(json.dumps({"kind": evidence.NATIVE_RESULT_KIND}), encoding="utf-8")
            failed = {"artifacts": [{"path": "source.golden", "sha256": evidence.sha256_file(output)}]}
            with patch.object(evidence, "ROOT", root), \
                    patch.object(evidence, "build_native_report", return_value=(failed, 1)) as collector:
                with self.assertRaises(SystemExit) as exit_info:
                    evidence.main(["--native-result", "observation.json", "--out", "source.golden"])
            self.assertEqual(exit_info.exception.code, 2)
            collector.assert_called_once()
            self.assertEqual(output.read_bytes(), payload)

    def test_native_output_cannot_overwrite_a_stale_derived_seed_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = native_fixture(root)
            name = "_build/seed-work/report.json"
            output = root / name
            payload = (json.dumps({"kind": evidence.NATIVE_REPORT_KIND}) + "\n").encode()
            output.write_bytes(payload)
            report = self.assert_native_failure(root, result, "stale native evidence file")
            attempted = [row for row in report["artifacts"] if row["path"] == name]
            self.assertEqual(len(attempted), 1)
            self.assertEqual(attempted[0]["status"], "unverified")
            with (
                patch.object(evidence, "ROOT", root),
                patch.object(evidence, "repo_metadata", return_value={"git_available": True, "git_head": "1" * 40}),
                patch.object(evidence, "run_command") as command,
            ):
                with self.assertRaises(SystemExit) as exit_info:
                    evidence.main(["--native-result", "_build/native-result.json", "--out", name])
            self.assertEqual(exit_info.exception.code, 2)
            command.assert_not_called()
            self.assertEqual(output.read_bytes(), payload)

    def test_native_output_refreshes_an_independent_existing_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = native_fixture(root)
            observation = root / "_build/native-result.json"
            observation.write_text(json.dumps(result), encoding="utf-8")
            output = root / "_build/native-output.json"
            output.write_text(json.dumps({"kind": evidence.NATIVE_REPORT_KIND, "old": True}), encoding="utf-8")
            golden = root / result["behavior"][0]["checks"][0]["expected_stdout"]["path"]
            before = golden.read_bytes()
            with (
                patch.object(evidence, "ROOT", root),
                patch.object(evidence, "repo_metadata", return_value={"git_available": True, "git_head": "1" * 40}),
                patch.object(evidence, "run_command") as command,
                patch("builtins.print"),
            ):
                code = evidence.main(["--native-result", "_build/native-result.json", "--out", "_build/native-output.json"])
            command.assert_not_called()
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual((report["kind"], report["summary"]["status"], code), (evidence.NATIVE_REPORT_KIND, "pass", 0))
            self.assertNotIn("old", report)
            self.assertEqual(golden.read_bytes(), before)

    def test_defaults_follow_the_canonical_stage_loop_wrapper(self) -> None:
        self.assertEqual(evidence.DEFAULT_STAGE_LOOP_RESULT, Path("_build/stage_loop/result.json"))
        self.assertEqual(evidence.DEFAULT_STAGE_LOOP_COMMAND, "sh scripts/stage_loop.sh")

    def test_report_schema_has_required_top_level_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = evidence.empty_report(root)
            for key in ("schema_version", "repo", "environment", "commands", "stages", "artifacts", "comparisons", "tests", "summary"):
                self.assertIn(key, report)
            self.assertEqual(report["schema_version"], 1)

    def test_command_failure_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = evidence.run_command(
                "failure",
                [sys.executable, "-c", "import sys; print('nope'); sys.exit(7)"],
                root=root,
                log_dir=root / "logs",
                timeout_seconds=None,
                log_bytes=1024,
            )
            self.assertEqual(record["status"], "fail")
            self.assertEqual(record["exit_code"], 7)
            self.assertIn("nope", record["stdout_excerpt"])

    def test_missing_artifact_is_recorded_as_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = evidence.hash_artifact(root, "_build/selfhost/missing.c", group="generated", required=True)
            self.assertEqual(artifact["status"], "missing")
            self.assertTrue(artifact["required"])
            report = evidence.empty_report(root)
            report["artifacts"] = [artifact]
            evidence.finalize_report(
                report,
                stage_loop_result={"summary": {"status": "pass"}, "comparisons": [{"match": True}]},
                run_stage_loop=True,
                stage_loop_read_error=None,
                generated_changes={"available": True, "changed": False, "paths": []},
            )
            self.assertEqual(report["summary"]["status"], "fail")
            self.assertIn("_build/selfhost/missing.c", report["summary"]["missing_required_artifacts"])

    def test_hash_mismatch_is_detected(self) -> None:
        comparison = evidence.compare_hash_maps("stage1-stage2", {"a.c": "111"}, {"a.c": "222"})
        self.assertEqual(comparison["status"], "fail")
        self.assertEqual(comparison["mismatched_paths"][0]["path"], "a.c")

    def test_matching_artifacts_converge(self) -> None:
        comparison = evidence.compare_hash_maps("stage1-stage2", {"a.c": "111"}, {"a.c": "111"})
        self.assertEqual(comparison["status"], "pass")
        self.assertEqual(comparison["matched_count"], 1)

    def test_current_stage_loop_result_uses_authoritative_fixpoint_fields(self) -> None:
        result = {
            "pass": True,
            "fixpoint": True,
            "backend_eq": True,
            "frontend_eq": True,
            "stages": 2,
            "stage_reports": [
                {"stage": 1, "frontend": {"pass": True}},
                {"stage": 2, "frontend": {"pass": True}, "eq_prev": {"backend": True, "frontend": True}},
            ],
        }
        comparisons = evidence.normalize_existing_comparisons(result)
        self.assertEqual([item["name"] for item in comparisons], ["stage1-stage2-backend", "stage1-stage2-frontend"])
        self.assertTrue(all(item["status"] == "pass" for item in comparisons))
        stages = evidence.normalize_stages(result)
        self.assertEqual([item["number"] for item in stages], [1, 2])
        self.assertTrue(all(item["status"] == "pass" for item in stages))

    def test_current_stage_loop_mismatch_remains_fail_closed(self) -> None:
        comparisons = evidence.normalize_existing_comparisons({"backend_eq": False, "frontend_eq": True})
        self.assertEqual([item["status"] for item in comparisons], ["fail", "pass"])

    def test_partial_mode_does_not_report_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report, exit_code = evidence.build_report(
                root=root,
                out=root / "_build/bootstrap/evidence.json",
                work_dir=Path("_build/bootstrap"),
                stage_loop_result_path=Path("_build/selfhost/result.json"),
                run_stage_loop_flag=False,
                stage_loop_command=[sys.executable, "-c", "raise SystemExit(0)"],
                test_commands=[],
                timeout_seconds=None,
                log_bytes=512,
            )
            self.assertEqual(exit_code, 1)
            self.assertEqual(report["summary"]["status"], "partial")
            self.assertIsNone(report["summary"]["converged"])

    def test_stable_path_ordering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "_build/selfhost").mkdir(parents=True)
            (root / "_build/selfhost/b.c").write_text("b", encoding="utf-8")
            (root / "_build/selfhost/a.c").write_text("a", encoding="utf-8")
            result = {"artifact_hashes": {"_build/selfhost/b.c": "old", "_build/selfhost/a.c": "old"}}
            artifacts = evidence.discover_artifacts(root, result, Path("_build/selfhost/result.json"))
            paths = [item["path"] for item in artifacts]
            self.assertEqual(paths, sorted(paths))

    def test_read_json_fails_closed_on_missing_invalid_and_non_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing, missing_err = evidence.read_json(root / "absent.json")
            self.assertIsNone(missing)
            self.assertEqual(missing_err, "result JSON was not written")

            array_path = root / "array.json"
            array_path.write_text("[1]", encoding="utf-8")
            array_value, array_err = evidence.read_json(array_path)
            self.assertIsNone(array_value)
            self.assertEqual(array_err, "result JSON top-level value is not an object")

            bad_path = root / "bad.json"
            bad_path.write_bytes(b"\xff\xfe{")
            bad_value, bad_err = evidence.read_json(bad_path)
            self.assertIsNone(bad_value)
            self.assertIsNotNone(bad_err)
            self.assertTrue(str(bad_err).startswith("unable to read JSON:"))

    def test_bounded_log_capture_does_not_explode_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            limit = 128
            record = evidence.run_command(
                "large-log",
                [sys.executable, "-c", "print('x' * 10000)"],
                root=root,
                log_dir=root / "logs",
                timeout_seconds=None,
                log_bytes=limit,
            )
            self.assertEqual(record["status"], "pass")
            self.assertTrue(record["stdout_truncated"])
            self.assertLessEqual(len(record["stdout_excerpt"].encode("utf-8", errors="replace")), limit)


def run() -> None:
    result = unittest.TextTestRunner(verbosity=1).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(SelfhostBootstrapEvidenceTests)
    )
    if not result.wasSuccessful():
        raise AssertionError("selfhost bootstrap evidence contract tests failed")


if __name__ == "__main__":
    raise SystemExit(unittest.main())
