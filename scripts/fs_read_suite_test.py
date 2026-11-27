#!/usr/bin/env python3
"""Exact byte and input identity checks for the C stdin observer; no native claims."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import fs_read_suite as observer


class StdinProtocol(unittest.TestCase):
    def test_exact_zero_short_binary_and_reused_input(self):
        cases = observer.stdin_cases()
        self.assertEqual(len(cases), 23)
        self.assertEqual(max(len(payload) for _, payload in cases), 23)
        self.assertEqual(b"".join(payload for name, payload in cases if name.startswith("byte-values-")),
                         bytes(range(256)))
        for name, payload in cases:
            with self.subTest(name=name):
                result = subprocess.CompletedProcess([], 0, payload[:16], b"")
                self.assertEqual(observer.stdin_verify_result(name, payload, result)["stdout_hex"], payload[:16].hex())

    def test_truncated_nul_excess_output_exit_and_stderr_are_rejected(self):
        payload = b"A\0BCDEFG12345678"
        invalid = ((0, b"A12345678", b""), (0, payload + b"\0", b""),
                   (0, payload[:-1], b""), (1, payload, b""), (False, payload, b""),
                   (0, payload, b"unexpected\n"), (0, payload.decode("ascii"), b""))
        for code, output, error in invalid:
            with self.subTest(code=code, output=output, error=error):
                with self.assertRaises(ValueError):
                    observer.stdin_verify_result("reuse", payload, subprocess.CompletedProcess([], code, output, error))

    def test_source_producer_output_and_record_identity(self):
        with tempfile.TemporaryDirectory(prefix="stdin-protocol-") as temporary:
            root = Path(temporary).resolve()
            source, producer, output = root / "input.c", root / "cc", root / "selftest"
            source.write_bytes(b"source-before")
            producer.write_bytes(b"compiler-before")
            with patch.object(observer, "ROOT", root), patch.object(observer, "STDIN_INPUTS", (source.name,)), \
                    patch.object(observer.shutil, "which", return_value=str(producer)):
                inputs = observer.stdin_inputs(producer, output)
                self.assertEqual(observer.stdin_verify_inputs(inputs, producer, output), inputs)
                self.assertEqual(observer.stdin_verify_inputs(inputs, producer, Path(str(output) + ".exe")), inputs)
                with self.assertRaises(ValueError):
                    observer.stdin_verify_inputs(inputs, producer, root / "other-selftest")
                source.write_bytes(b"source-after")
                with self.assertRaises(ValueError):
                    observer.stdin_verify_inputs(inputs, producer, output)
                source.write_bytes(b"source-before")
                producer.write_bytes(b"compiler-after")
                with self.assertRaises(ValueError):
                    observer.stdin_verify_inputs(inputs, producer, output)
                producer.write_bytes(b"compiler-before")
                with self.assertRaises(ValueError):
                    observer.stdin_verify_inputs(dict(inputs, kind="other"), producer, output)
                with self.assertRaises(ValueError):
                    observer.stdin_verify_inputs(dict(inputs, compile_argv=inputs["compile_argv"] + ["-O2"]),
                                                 producer, output)
            receipt = root / "receipt.json"
            observer.stdin_write_record(receipt, {"complete": True})
            saved = receipt.read_bytes()
            with self.assertRaises(FileExistsError):
                observer.stdin_write_record(receipt, {"complete": False})
            self.assertEqual(receipt.read_bytes(), saved)
            self.assertIs(json.loads(saved)["complete"], True)

    def _failed_observation(self, result, mutation=None):
        payload = b"A\0BCDEFG12345678"
        with tempfile.TemporaryDirectory(prefix="stdin-receipt-") as temporary:
            root = Path(temporary).resolve()
            source, producer, driver = root / "input.c", root / "cc", root / "selftest"
            for path in (source, producer, driver):
                path.write_bytes(path.name.encode("ascii"))
            inputs_path, output = root / "inputs.json", root / "receipts"
            with patch.object(observer, "ROOT", root), patch.object(observer, "STDIN_INPUTS", (source.name,)), \
                    patch.object(observer.shutil, "which", return_value=str(producer)), \
                    patch.object(observer, "stdin_cases", return_value=(("reuse", payload),)):
                observer.stdin_write_record(inputs_path, observer.stdin_inputs(producer, driver))

                def observed(argv, **options):
                    self.assertEqual(argv, [str(driver), "--stdin-bytes"])
                    self.assertEqual(options["input"], payload)
                    self.assertEqual(options["cwd"], root)
                    self.assertEqual(options["env"]["PATH"], "")
                    self.assertEqual(options["timeout"], 10)
                    self.assertIs(options["capture_output"], True)
                    if mutation is not None:
                        {"source": source, "producer": producer, "driver": driver, "inputs": inputs_path}[
                            mutation].write_bytes(b"changed")
                    if isinstance(result, subprocess.TimeoutExpired):
                        raise result
                    return result

                with patch.object(observer.subprocess, "run", side_effect=observed), \
                        self.assertRaises((ValueError, subprocess.TimeoutExpired)):
                    observer.run_stdin_suite(driver, output, inputs_path, producer)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertIs(report["complete"], False)
            return report

    def test_failure_receipt_keeps_exact_exit_bytes_and_after_inputs(self):
        payload = b"A\0BCDEFG12345678"
        for code, output, error in ((0, b"A12345678", b""), (0, payload + b"\0", b""),
                                    (73, payload, b"read error\n")):
            with self.subTest(code=code, output=output):
                report = self._failed_observation(subprocess.CompletedProcess([], code, output, error))
                row = report["checks"][0]
                self.assertEqual((row["status"], row["returncode"], row["stdout_hex"], row["stderr_hex"]),
                                 ("fail", code, output.hex(), error.hex()))
                self.assertEqual(report["before"], report["after"])
                self.assertEqual(report["inputs_sha256"], report["inputs_sha256_after"])
                self.assertEqual(report["driver"]["before_sha256"], report["driver"]["after_sha256"])

    def test_source_producer_image_and_manifest_drift_cannot_complete(self):
        result = subprocess.CompletedProcess([], 0, b"A\0BCDEFG12345678", b"")
        for mutation in ("source", "producer", "driver", "inputs"):
            with self.subTest(mutation=mutation):
                report = self._failed_observation(result, mutation)
                self.assertIn("identity_error", report)
                if mutation in ("source", "producer"):
                    self.assertNotEqual(report["before"], report["after"])
                elif mutation == "driver":
                    self.assertNotEqual(report["driver"]["before_sha256"], report["driver"]["after_sha256"])
                else:
                    self.assertNotEqual(report["inputs_sha256"], report["inputs_sha256_after"])

    def test_timeout_records_partial_binary_output_without_an_exit_status(self):
        report = self._failed_observation(subprocess.TimeoutExpired([], 10, output=b"A\0", stderr=b""))
        row = report["checks"][0]
        self.assertEqual((row["status"], row["returncode"], row["stdout_hex"]), ("timeout", None, "4100"))
        self.assertEqual(report["before"], report["after"])


class NativeStatusProtocol(unittest.TestCase):
    def _observe(self, overrides=None):
        overrides, locked = overrides or {}, set()
        with tempfile.TemporaryDirectory(prefix="read-observer-") as temporary:
            root = Path(temporary)
            driver, output = root / "driver", root / "observed"
            driver.write_bytes(b"observer protocol input; never executed")

            def open_handle(path, *_arguments):
                locked.add(path)
                return 1

            def close_handle(_handle):
                locked.clear()
                return 1

            def observed(argv, **options):
                self.assertEqual(argv[0], str(driver))
                self.assertEqual(options["cwd"], observer.ROOT)
                self.assertEqual(options["env"]["PATH"], "")
                self.assertIs(options["capture_output"], True)
                self.assertIn(options["timeout"], (30, 90))
                command, supplied = argv[1:]
                path = Path(supplied)
                if command in ("--read-status-nul-path", "--read-status-invalid-utf8-path"):
                    case = "nul-path" if command.endswith("nul-path") else "malformed-utf8-path"
                    result = (73, b"", b"")
                elif command == "--read-deferred-status":
                    case, result = "deferred-removal", (1, b"", b"read OS status=2\n")
                    path.unlink()
                elif command == "--read-checked":
                    case = "checked-locked-file" if supplied in locked else "checked-missing-file"
                    prefix = "filesystem read OS status=32 failed: " if supplied in locked else "path not found: "
                    result = (1, b"", (prefix + supplied + "\n").encode("utf-8"))
                elif command == "--read-reuse-status":
                    case = "reused-action"
                    body = bytes((65, 0, 255, 128, 10, 13, 90))
                    path.write_bytes(body)
                    result = (0, body, b"")
                else:
                    self.assertEqual(command, "--read-status")
                    if supplied == "":
                        case, result = "empty-path", (73, b"", b"")
                    elif supplied in locked:
                        case, result = "locked-file", (1, b"", b"read OS status=32\n")
                    elif not path.exists() or path.is_dir():
                        case = "empty-directory" if path.is_dir() else "missing-file"
                        result = (1, b"", b"read OS status=2\n")
                    else:
                        case, result = path.name, (0, path.read_bytes(), b"")
                return subprocess.CompletedProcess(argv, *overrides.get(case, result))

            platform = SimpleNamespace(name="nt", environ=observer.os.environ)
            windows = SimpleNamespace(open=open_handle, close=close_handle)
            with patch.object(observer, "os", platform), \
                    patch.object(observer, "WindowsMetadata", return_value=windows), \
                    patch.object(observer.subprocess, "run", side_effect=observed), patch("builtins.print"):
                observer.run_suite(driver, output, "status", checked_reader=True)
            return json.loads((output / "report.json").read_text(encoding="utf-8"))

    def test_silent_terminal_paths_preserve_complete_status_inventory(self):
        report = self._observe()
        self.assertIs(report["complete"], True)
        self.assertEqual([row["name"] for row in report["checks"]], list(observer.NATIVE_CASES))
        self.assertEqual([row["exit"] for row in report["checks"]
                          if row["name"] in ("empty-path", "nul-path", "malformed-utf8-path")], [73, 73, 73])
        self.assertTrue(all(row["status"] == "pass" for row in report["checks"]))
        self._observe({"empty-path": (73, b"", b"ouro run: fs_read_file: path failed\n")})

    def test_terminal_paths_reject_success_wrong_exit_and_output(self):
        for case in ("empty-path", "nul-path", "malformed-utf8-path"):
            for result in ((0, b"", b""), (1, b"", b""), (87, b"", b""), (73, b"partial", b"")):
                with self.subTest(case=case, result=result), self.assertRaises(AssertionError):
                    self._observe({case: result})

    def test_os_and_checked_refusals_keep_exact_diagnostics(self):
        for result in ((1, b"", b""), (1, b"", b"read OS status=0\n"),
                       (1, b"", b"other failure\n"), (73, b"", b"read OS status=2\n"),
                       (1, b"partial", b"read OS status=2\n")):
            with self.subTest(result=result), self.assertRaises(AssertionError):
                self._observe({"missing-file": result})
        for case in ("checked-missing-file", "checked-locked-file"):
            with self.subTest(case=case), self.assertRaises(AssertionError):
                self._observe({case: (1, b"", b"wrong checked diagnostic\n")})

class BoundedProtocol(unittest.TestCase):
    # Protocol doubles never execute PE files or establish native acceptance.
    def _receipt(self, root):
        producer = root / "producer"
        producer.write_bytes(b"unexecuted producer")
        sources = dict(units=["entry.ouro"], closures={"entry.ouro": ["entry.ouro"]}, sources={"entry.ouro": "source-sha"})
        images = {}
        for name in ("pure", "order", "probe", "calls"):
            path = root / (name + ".exe")
            path.write_bytes(("unexecuted " + name).encode())
            images[name] = dict(path=str(path), sha256=observer.sha256_file(path))
        return dict(kind="ouro.fs-bounded-inputs.v1", sources=sources,
                    producer=dict(path=str(producer), sha256=observer.sha256_file(producer)), images=images,
                    large_contract=observer.bounded_large_contract())

    def _report(self, receipt, directory, probe, calls):
        rows = []
        for spec in observer.bounded_case_specs(directory, probe, calls):
            rows.append(dict(name=spec["name"], argv=[str(spec["driver"]), *spec["arguments"]],
                             cwd=str(observer.ROOT), status="pass", exit=spec["code"],
                             expected_exit=spec["code"], expected_stdout_hex=spec["out"].hex(), expected_stderr_hex=spec["err"].hex(),
                             stdout_hex=spec["out"].hex(), stderr_hex=spec["err"].hex(),
                             input_path=str(spec["path"]) if spec["path"] is not None else None,
                             input_sha256_before=observer.hashlib.sha256(spec["before"]).hexdigest() if spec["before"] is not None else None,
                             input_sha256_after=observer.hashlib.sha256(spec["after"]).hexdigest() if spec["after"] is not None else None,
                             expected_input_sha256_after=observer.hashlib.sha256(spec["after"]).hexdigest() if spec["after"] is not None else None))
        large = []
        for spec in observer.bounded_large_case_specs(directory, probe):
            spec["path"].parent.mkdir(parents=True, exist_ok=True)
            spec["path"].write_bytes(spec["after"])
            result = subprocess.CompletedProcess([], spec["code"], spec["out"], spec["err"])
            row = observer.bounded_large_observation(spec, result, directory)
            for stream in ("stdout", "stderr"):
                path = Path(row[stream + "_path"])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(getattr(result, stream))
            large.append(dict(row, status="pass", input_sha256_after=observer.sha256_file(spec["path"])))
        return dict(kind="ouro.fs-bounded-runtime.v1", complete=True, inputs=receipt, checks=rows, large_checks=large)

    def test_catalog_keeps_binary_caps_chunk_boundary_and_source_controls(self):
        specs = {row["name"]: row for row in observer.bounded_case_specs(Path("/case"), Path("/probe"), Path("/calls"))}
        self.assertEqual(tuple(specs), observer.BOUNDED_CASES)
        self.assertEqual(len(specs), 22)
        self.assertEqual(specs["binary-exact"]["out"], b"A\0\xff")
        self.assertEqual(specs["binary-high-cap"]["arguments"][-1], "18446744073709551616")
        self.assertEqual(specs["binary-zero-cap"]["err"], b"bounded file read: size 3 exceeds byte cap 0\n")
        self.assertEqual(specs["chunk-exact"]["arguments"][-1], "65537")
        self.assertEqual(len(specs["chunk-exact"]["out"]), 65537)
        self.assertEqual(specs["chunk-exact"]["out"][:4], b"\0\1\2\3")
        self.assertEqual(specs["chunk-exact"]["out"][-2:], b"\xff\xff")
        self.assertEqual(specs["chunk-short-cap"]["err"], b"bounded file read: size 65537 exceeds byte cap 65536\n")
        self.assertEqual(specs["nul-path"]["arguments"][0], "nul")
        self.assertEqual(specs["malformed-utf8-path"]["arguments"][0], "utf8")
        self.assertEqual(specs["reused-action"]["before"], b"first")
        self.assertEqual(specs["recovery"]["after"], b"U\0\xfe")

    def test_whole_binary_output_and_typed_status_are_required(self):
        spec = next(row for row in observer.bounded_case_specs(Path("/case"), Path("/probe"), Path("/calls"))
                    if row["name"] == "binary-exact")
        self.assertEqual(observer.bounded_result_row(spec, subprocess.CompletedProcess([], 0, b"A\0\xff", b""))["stdout_hex"],
                         "4100ff")
        for code, out, err in ((False, b"A\0\xff", b""), (1, b"A\0\xff", b""), (0, b"A\xff", b""),
                               (0, b"A\0", b""), (0, b"A\0\xff\n", b""), (0, b"A\0\xff", b"warning"),
                               (0, "A\0ÿ", b"")):
            with self.subTest(code=code, out=out), self.assertRaises(ValueError):
                observer.bounded_result_row(spec, subprocess.CompletedProcess([], code, out, err))
        refusal = next(row for row in observer.bounded_case_specs(Path("/case"), Path("/probe"), Path("/calls"))
                       if row["name"] == "binary-zero-cap")
        for code, out, err in ((True, b"", refusal["err"]), (0, b"", refusal["err"]),
                               (1, b"A", refusal["err"]), (1, b"", b""),
                               (1, b"", b"bounded file read: size 3 exceeds byte cap 1\n")):
            with self.subTest(code=code, out=out), self.assertRaises(ValueError):
                observer.bounded_result_row(refusal, subprocess.CompletedProcess([], code, out, err))

    def test_missing_reordered_duplicate_bool_and_stale_runtime_rows_refuse(self):
        with tempfile.TemporaryDirectory(prefix="bounded-protocol-") as temporary:
            root = Path(temporary)
            receipt = self._receipt(root)
            probe, calls = root / "probe.exe", root / "calls.exe"
            original = self._report(receipt, root / "runtime", probe, calls)
            observer.bounded_verify_report(original, receipt, root / "runtime", probe, calls)
            def altered(mutate):
                value = json.loads(json.dumps(original))
                mutate(value)
                return value
            mutants = (
                altered(lambda value: value.pop("complete")),
                altered(lambda value: value.update(complete=1)),
                altered(lambda value: value["checks"].pop()),
                altered(lambda value: value["checks"].reverse()),
                altered(lambda value: value["checks"].append(value["checks"][0])),
                altered(lambda value: value["checks"][0].update(exit=False)),
                altered(lambda value: value["checks"][0].update(expected_exit=False)),
                altered(lambda value: value["checks"][1].update(stdout_hex="41ff")),
                altered(lambda value: value["checks"][8].update(exit=True)),
                altered(lambda value: value["checks"][0].update(argv=["wrong"])),
                altered(lambda value: value["inputs"]["producer"].update(sha256="stale")),
                altered(lambda value: value["checks"][1].update(input_sha256_after="stale")),
            )
            for value in mutants:
                with self.subTest(value=value["checks"][:1]), self.assertRaises(ValueError):
                    observer.bounded_verify_report(value, receipt, root / "runtime", probe, calls)

    def test_receipt_requires_complete_sources_actual_producer_and_all_four_images(self):
        with tempfile.TemporaryDirectory(prefix="bounded-inputs-") as temporary:
            root = Path(temporary)
            receipt = self._receipt(root)
            probe, calls = root / "probe.exe", root / "calls.exe"
            with patch.object(observer, "native_source_snapshot", return_value=receipt["sources"]):
                observer.bounded_verify_receipt(json.loads(json.dumps(receipt, sort_keys=True)), probe, calls)
                for key in ("large_contract", "owners", "scripts/fs_read_suite.py", "scripts/fs_read_suite_test.py"):
                    removed = json.loads(json.dumps(receipt))
                    if key == "large_contract":
                        removed.pop(key)
                    elif key == "owners":
                        removed["large_contract"].pop(key)
                    else:
                        removed["large_contract"]["owners"][key] = "changed"
                    with self.subTest(contract=key), self.assertRaises(ValueError):
                        observer.bounded_verify_receipt(removed, probe, calls)
                for key in ("pure", "order", "probe", "calls"):
                    removed = json.loads(json.dumps(receipt))
                    removed["images"].pop(key)
                    with self.subTest(missing=key), self.assertRaises(ValueError):
                        observer.bounded_verify_receipt(removed, probe, calls)
                    path = root / (key + ".exe")
                    before = path.read_bytes()
                    path.write_bytes(before + b"changed")
                    with self.subTest(changed=key), self.assertRaises(ValueError):
                        observer.bounded_verify_receipt(receipt, probe, calls)
                    path.write_bytes(before)
                with self.assertRaises(ValueError):
                    observer.bounded_verify_receipt(receipt, root / "wrong.exe", calls)
                Path(receipt["producer"]["path"]).write_bytes(b"changed producer")
                with self.assertRaises(ValueError):
                    observer.bounded_verify_receipt(receipt, probe, calls)
            with patch.object(observer, "native_source_snapshot", return_value={"sources": "changed"}), self.assertRaises(ValueError):
                observer.bounded_verify_receipt(receipt, probe, calls)

    def test_artifact_receipts_bind_parsed_bytes_to_hashes(self):
        with tempfile.TemporaryDirectory(prefix="bounded-receipt-bytes-") as temporary:
            root = Path(temporary)
            receipt = self._receipt(root)
            evidence = {"checks": []}
            receipt_path, evidence_path = root / "inputs.json", root / "runtime.json"
            receipt_path.write_bytes(json.dumps(receipt).encode("utf-8"))
            evidence_path.write_bytes(json.dumps(evidence).encode("utf-8"))
            section = dict(inputs=receipt, receipt_path=str(receipt_path), runtime_path=str(evidence_path),
                           receipt_sha256=observer.sha256_file(receipt_path), runtime_sha256=observer.sha256_file(evidence_path))
            read_bytes = Path.read_bytes

            with (patch.object(observer, "bounded_verify_law_records"),
                  patch.object(observer, "native_source_snapshot", return_value=receipt["sources"]),
                  patch.object(observer, "bounded_verify_report") as verify_report):
                for path, sha_key, label in ((receipt_path, "receipt_sha256", "input"),
                                             (evidence_path, "runtime_sha256", "runtime")):
                    original = path.read_bytes()

                    def read_then_change(candidate, *, _path=path):
                        data = read_bytes(candidate)
                        if candidate == _path:
                            candidate.write_bytes(b"\xff")
                        return data

                    with self.subTest(receipt=label):
                        try:
                            with patch.object(Path, "read_bytes", autospec=True, side_effect=read_then_change) as reads:
                                with self.assertRaisesRegex(ValueError, "^bounded read final reparse input changed$"):
                                    observer.verify_native_bounded_artifacts(section)
                            self.assertEqual([call.args[0] for call in reads.call_args_list], [receipt_path, evidence_path])
                            verify_report.assert_called_once_with(evidence, receipt, root, root / "probe.exe", root / "calls.exe")
                            verify_report.reset_mock()
                            self.assertEqual(path.read_bytes(), b"\xff")
                            with self.assertRaisesRegex(ValueError, f"^bounded read {label} receipt changed$"):
                                observer.verify_native_bounded_artifacts(section)
                            for encoding in ("utf-8-sig", "utf-16"):
                                path.write_bytes(original.decode("utf-8").encode(encoding))
                                matching_hash = {**section, sha_key: observer.sha256_file(path)}
                                with self.assertRaises((UnicodeDecodeError, json.JSONDecodeError)):
                                    observer.verify_native_bounded_artifacts(matching_hash)
                        finally:
                            path.write_bytes(original)

    def test_law_emission_and_cleanup_records_refuse_partial_or_abnormal_results(self):
        with tempfile.TemporaryDirectory(prefix="bounded-stages-") as temporary:
            root = Path(temporary)
            receipt = self._receipt(root)
            receipt["sources"]["closures"] = {entry: [entry] for entry in observer.BOUNDED_ENTRIES.values()}
            section = dict(inputs=receipt, images=receipt["images"], emissions={}, faults=[])
            for name, entry in observer.BOUNDED_ENTRIES.items():
                image = section["images"][name]["path"]
                logical = Path(image).relative_to(root).as_posix()
                section["emissions"][name] = dict(status="ok", returncode=0, stdout=logical + "\n",
                                                 argv=[receipt["producer"]["path"], entry, logical, entry])
            for name, laws in (("pure", observer.BOUNDED_PURE_LAWS), ("order", observer.BOUNDED_ORDER_LAWS)):
                section[name] = dict(status="ok", returncode=0, argv=[section["images"][name]["path"]],
                                     stdout=observer.bounded_law_output("fs-bounded" if name == "pure" else "fs-bounded-order", laws),
                                     stderr="")
            for mode, marker in (("close-failure", "close"), ("release-failure", "release"),
                                 ("close-payload-failure", "close-payload")):
                section["faults"].append(dict(mode=mode, result=dict(status="ok", returncode=73,
                    argv=[section["images"]["order"]["path"], mode],
                    stdout="FS_BOUNDED_CLEANUP_REACHED " + marker + "\n", stderr="")))
            with patch.object(observer, "ROOT", root):
                observer.bounded_verify_law_records(section)
                def altered(mutate):
                    value = json.loads(json.dumps(section))
                    mutate(value)
                    return value
                mutants = (
                    altered(lambda value: value["emissions"].pop("calls")),
                    altered(lambda value: value["emissions"]["pure"].update(returncode=False)),
                    altered(lambda value: value["pure"].update(stdout="")),
                    altered(lambda value: value["order"].update(stdout=value["order"]["stdout"][:-1])),
                    altered(lambda value: value["faults"].pop()),
                    altered(lambda value: value["faults"].reverse()),
                    altered(lambda value: value["faults"][0]["result"].update(status="timeout")),
                    altered(lambda value: value["faults"][0]["result"].update(returncode=73.0)),
                    altered(lambda value: value["faults"][0]["result"].update(stdout="FS_BOUNDED_CLEANUP_REACHED close")),
                )
                for value in mutants:
                    with self.subTest(faults=value["faults"][:1]), self.assertRaises((ValueError, KeyError)):
                        observer.bounded_verify_law_records(value)

    def _failing_public_observation(self, root, outcome):
        receipt = self._receipt(root)
        probe, calls = root / "probe.exe", root / "calls.exe"
        output, inputs = root / "runtime", root / "inputs.json"
        inputs.write_text(json.dumps(receipt), encoding="utf-8")
        spec = next(row for row in observer.bounded_case_specs(output, probe, calls)
                    if row["name"] == "binary-exact")
        platform = SimpleNamespace(name="nt", environ=observer.os.environ)
        with patch.object(observer, "os", platform), patch.object(observer, "WindowsMetadata", return_value=SimpleNamespace()), \
                patch.object(observer, "bounded_verify_receipt"), \
                patch.object(observer, "bounded_case_specs", return_value=(spec,)), \
                patch.object(observer.subprocess, "run", side_effect=outcome):
            with self.assertRaises((ValueError, subprocess.TimeoutExpired)):
                observer.run_bounded_suite(probe, calls, output, inputs)
        report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        self.assertIs(report["complete"], False)
        self.assertEqual(len(report["checks"]), 1)
        row = report["checks"][0]
        self.assertEqual(row["input_path"], str(spec["path"]))
        self.assertEqual(row["input_sha256_before"], observer.hashlib.sha256(b"A\0\xff").hexdigest())
        self.assertEqual(row["input_sha256_after"], observer.hashlib.sha256(b"A\0\xff").hexdigest())
        self.assertEqual(row["expected_input_sha256_after"], observer.hashlib.sha256(b"A\0\xff").hexdigest())
        self.assertEqual(row["expected_exit"], 0)
        self.assertEqual(row["expected_stdout_hex"], "4100ff")
        self.assertEqual(row["expected_stderr_hex"], "")
        with patch.object(observer, "bounded_case_specs", return_value=(spec,)), self.assertRaises(ValueError):
            observer.bounded_verify_report(dict(report, complete=True), receipt, output, probe, calls)
        return row

    def test_bounded_run_detects_receipt_replaced_after_initial_read(self):
        with tempfile.TemporaryDirectory(prefix="bounded-run-receipt-") as temporary:
            root = Path(temporary)
            receipt = self._receipt(root)
            probe, calls = root / "probe.exe", root / "calls.exe"
            output, inputs = root / "runtime", root / "inputs.json"
            inputs.write_bytes(json.dumps(receipt).encode("utf-8"))
            replacement = root / "replacement.json"
            replacement.write_bytes(json.dumps({**receipt, "kind": "changed"}).encode("utf-8"))
            read_bytes = Path.read_bytes

            def replace_after_read(path):
                data = read_bytes(path)
                if path == inputs:
                    replacement.replace(path)
                return data

            platform = SimpleNamespace(name="nt", environ=observer.os.environ)
            diagnostic = "bounded read input receipt changed during execution"
            with (patch.object(observer, "os", platform), patch.object(observer, "WindowsMetadata"),
                  patch.object(observer, "bounded_verify_receipt"),
                  patch.object(observer, "bounded_case_specs", return_value=()),
                  patch.object(observer, "bounded_large_case_specs", return_value=()),
                  patch.object(observer, "bounded_verify_report") as verify_report,
                  patch.object(Path, "read_bytes", autospec=True, side_effect=replace_after_read)):
                with self.assertRaisesRegex(ValueError, diagnostic):
                    observer.run_bounded_suite(probe, calls, output, inputs)
            verify_report.assert_not_called()
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertIs(report["complete"], False)
            self.assertEqual(report["inputs"], receipt)
            self.assertEqual(report["error"], diagnostic)

    def test_failed_public_child_keeps_actual_dword_streams_and_input_pins(self):
        with tempfile.TemporaryDirectory(prefix="bounded-failed-bytes-") as temporary:
            def failed(argv, **_options):
                return subprocess.CompletedProcess(argv, 0x80000005, b"A\0", b"\xfffailed\n")
            row = self._failing_public_observation(Path(temporary), failed)
            self.assertEqual(row["status"], "fail")
            self.assertEqual(row["exit"], 0x80000005)
            self.assertEqual(row["stdout_hex"], "4100")
            self.assertEqual(row["stderr_hex"], b"\xfffailed\n".hex())

    def test_timed_out_public_child_keeps_partial_binary_streams_without_fake_exit(self):
        with tempfile.TemporaryDirectory(prefix="bounded-timeout-bytes-") as temporary:
            def timeout(argv, **_options):
                raise subprocess.TimeoutExpired(argv, 30, output=b"A\0", stderr=b"\xfftimeout\n")
            row = self._failing_public_observation(Path(temporary), timeout)
            self.assertEqual(row["status"], "timeout")
            self.assertIsNone(row["exit"])
            self.assertEqual(row["timeout_s"], 30)
            self.assertEqual(row["stdout_hex"], "4100")
            self.assertEqual(row["stderr_hex"], b"\xfftimeout\n".hex())

    def test_large_catalog_preserves_full_binary_and_exact_refusal(self):
        specs = observer.bounded_large_case_specs(Path("/case"), Path("/probe"))
        self.assertEqual(tuple(spec["name"] for spec in specs), observer.BOUNDED_LARGE_CASES)
        self.assertEqual(observer.BOUNDED_LARGE_BYTES, 31 * 1024 * 1024 + 1)
        refusal, accepted = specs
        payload = accepted["out"]
        self.assertEqual(len(payload), observer.BOUNDED_LARGE_BYTES)
        self.assertEqual(payload[:256], bytes(range(256)))
        self.assertEqual(payload[65536:65792], bytes(range(256)))
        self.assertEqual(payload[-2:], b"\xff\xff")
        self.assertEqual(refusal["arguments"][-1], "32505856")
        self.assertEqual(accepted["arguments"][-1], "32505857")
        self.assertEqual(refusal["code"], 1)
        self.assertEqual(refusal["out"], b"")
        self.assertEqual(refusal["err"], b"bounded file read: size 32505857 exceeds byte cap 32505856\n")
        observer.bounded_large_validate_result(accepted, subprocess.CompletedProcess([], 0, payload, b""))
        for code, out, err in ((False, payload, b""), (0x80000005, payload, b""), (0, payload[:-1], b""),
                               (0, payload + b"\n", b""), (0, payload[1:], b""),
                               (0, payload[:13] + b"\r\n" + payload[14:], b""),
                               (0, payload[:255] + b"\xef\xbf\xbd" + payload[256:], b""),
                               (0, payload, b"warning"), (0, "", b"")):
            with self.subTest(code=code, size=len(out)), self.assertRaises(ValueError):
                observer.bounded_large_validate_result(accepted, subprocess.CompletedProcess([], code, out, err))
        with self.assertRaises(ValueError):
            observer.bounded_large_validate_result(refusal, subprocess.CompletedProcess([], 1, b"A", refusal["err"]))

    def test_large_rows_are_required_ordered_and_survive_sorted_json(self):
        with tempfile.TemporaryDirectory(prefix="bounded-large-protocol-") as temporary:
            root = Path(temporary)
            receipt = self._receipt(root)
            directory, probe, calls = root / "runtime", root / "probe.exe", root / "calls.exe"
            original = self._report(receipt, directory, probe, calls)
            observer.bounded_verify_report(json.loads(json.dumps(original, sort_keys=True)), receipt, directory, probe, calls)
            mutants = []
            for field, value in (("exit", False), ("expected_exit", True), ("stdout_bytes", False),
                                 ("status", "timeout"), ("argv", ["wrong"]), ("stdout_sha256", "stale"),
                                 ("input_sha256_after", "stale"), ("expected_stdout_sha256", "stale")):
                mutant = json.loads(json.dumps(original))
                mutant["large_checks"][0][field] = value
                mutants.append(mutant)
            for mutation in ("missing", "reordered", "duplicate"):
                mutant = json.loads(json.dumps(original))
                if mutation == "missing":
                    mutant.pop("large_checks")
                elif mutation == "reordered":
                    mutant["large_checks"].reverse()
                else:
                    mutant["large_checks"].append(mutant["large_checks"][0])
                mutants.append(mutant)
            for mutant in mutants:
                with self.subTest(rows=mutant.get("large_checks")), self.assertRaises(ValueError):
                    observer.bounded_verify_report(mutant, receipt, directory, probe, calls)
            row = original["large_checks"][1]
            for key, offset in (("stdout_path", 0), ("stdout_path", 255), ("input_path", 65536)):
                path = Path(row[key])
                with path.open("r+b") as handle:
                    handle.seek(offset)
                    previous = handle.read(1)
                    handle.seek(offset)
                    handle.write(bytes((previous[0] ^ 1,)))
                with self.subTest(path=key, offset=offset), self.assertRaises(ValueError):
                    observer.bounded_verify_report(original, receipt, directory, probe, calls)
                with path.open("r+b") as handle:
                    handle.seek(offset)
                    handle.write(previous)
            Path(row["stderr_path"]).write_bytes(b"warning")
            with self.assertRaises(ValueError):
                observer.bounded_verify_report(original, receipt, directory, probe, calls)

    def test_large_failure_and_timeout_preserve_raw_streams_and_input_pins(self):
        for timed_out in (False, True):
            with self.subTest(timeout=timed_out), tempfile.TemporaryDirectory(prefix="bounded-large-failure-") as temporary:
                root = Path(temporary)
                receipt = self._receipt(root)
                probe, calls, output, inputs = root / "probe.exe", root / "calls.exe", root / "runtime", root / "inputs.json"
                inputs.write_text(json.dumps(receipt), encoding="utf-8")
                spec = observer.bounded_large_case_specs(output, probe)[1]
                def result(argv, *, timeout_case=timed_out, **_options):
                    if timeout_case:
                        raise subprocess.TimeoutExpired(argv, 30, output=b"A\0", stderr=b"\xfftimeout\n")
                    return subprocess.CompletedProcess(argv, 0x80000005, b"A\0", b"\xfffailed\n")
                platform = SimpleNamespace(name="nt", environ=observer.os.environ)
                with patch.object(observer, "os", platform), patch.object(observer, "WindowsMetadata", return_value=SimpleNamespace()), \
                        patch.object(observer, "bounded_verify_receipt"), patch.object(observer, "bounded_case_specs", return_value=()), \
                        patch.object(observer, "bounded_large_case_specs", return_value=(spec,)), \
                        patch.object(observer.subprocess, "run", side_effect=result):
                    with self.assertRaises((ValueError, subprocess.TimeoutExpired)):
                        observer.run_bounded_suite(probe, calls, output, inputs)
                report = json.loads((output / "report.json").read_text(encoding="utf-8"))
                self.assertIs(report["complete"], False)
                row = report["large_checks"][0]
                self.assertEqual(row["status"], "timeout" if timed_out else "fail")
                if timed_out:
                    self.assertIsNone(row["exit"])
                else:
                    self.assertEqual(row["exit"], 0x80000005)
                self.assertEqual(Path(row["stdout_path"]).read_bytes(), b"A\0")
                self.assertEqual(Path(row["stderr_path"]).read_bytes(), b"\xfftimeout\n" if timed_out else b"\xfffailed\n")
                self.assertEqual(row["input_sha256_before"], observer.sha256_file(spec["path"]))
                self.assertEqual(row["input_sha256_after"], row["input_sha256_before"])
                self.assertEqual(row["stdout_sha256"], observer.sha256_file(Path(row["stdout_path"])))

    def test_existing_read_status_owner_cannot_complete_without_bounded_section(self):
        with tempfile.TemporaryDirectory(prefix="bounded-required-") as temporary:
            root = Path(temporary)
            producer = root / "producer"
            producer.write_bytes(b"unexecuted producer")
            entries = (observer.NATIVE_ENTRY, *(f"tests/native_managed/reject/source_file_read_status_{name}.ouro"
                                                for name, _, _ in observer.NATIVE_REJECTIONS))
            before = dict(units=[observer.NATIVE_ENTRY], closures={entry: [entry] for entry in entries}, sources={})
            def run(_name, argv, _timeout):
                if _name == "native-build-read-status":
                    (root / argv[2]).write_bytes(b"unexecuted image")
                    return SimpleNamespace(ok=True, stdout=argv[2] + "\n", stderr="", returncode=0)
                if _name.startswith("native-read-status-reject-"):
                    return SimpleNamespace(ok=False, stdout="", stderr="", returncode=2)
                runtime = root / "native-fs-read" / "runtime"
                runtime.mkdir()
                rows = [dict(name=name, exit=0 if name in ("empty-file", "complete-file", "unicode-path",
                            "read-after-refusal", "reused-action") else 73 if name in ("empty-path", "nul-path", "malformed-utf8-path")
                            else 1, status="pass") for name in observer.NATIVE_CASES]
                image_hash = observer.sha256_file(root / "native-fs-read" / "source-file-read-status.exe")
                (runtime / "report.json").write_text(json.dumps(dict(kind="ouro.fs-read.v1", complete=True, mode="status",
                                                                      driver_sha256=image_hash, checks=rows)))
                out = "".join(f"FS_READ_OK {name}\n" for name in observer.NATIVE_CASES) + "FS_READ_SUITE: PASS checks=14\n"
                return SimpleNamespace(ok=True, stdout=out, stderr="", returncode=0)
            platform = SimpleNamespace(name="nt")
            parse_bytes = object()
            with patch.object(observer, "ROOT", root), patch.object(observer, "os", platform), \
                    patch.object(observer, "native_source_snapshot", return_value=before) as snapshot, \
                    patch("frontend_native_process.verify_rejection", return_value="checked rejection"), \
                    patch("frontend_native_process.inspect_image", side_effect=lambda path, *_args:
                          dict(sha256=observer.sha256_file(path))), \
                    patch.object(observer, "run_native_bounded_section", side_effect=ValueError("bounded incomplete")) as required:
                with self.assertRaisesRegex(ValueError, "bounded incomplete"):
                    observer.run_native_section(producer, root, run, 900, lambda: None, parse_bytes=parse_bytes)
            required.assert_called_once()
            self.assertEqual(snapshot.call_count, len(observer.NATIVE_REJECTIONS) + 3)
            for call in snapshot.call_args_list:
                self.assertEqual(call.kwargs, {"parse_bytes": parse_bytes})
            report = json.loads((root / "native-fs-read" / "report.json").read_text())
            self.assertEqual(report["status"], "failed")
            self.assertEqual(len(report["runtime"]["checks"]), 14)
            self.assertEqual(len(report["rejections"]), 3)


if __name__ == "__main__":
    unittest.main()
