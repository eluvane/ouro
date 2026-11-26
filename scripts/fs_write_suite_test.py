#!/usr/bin/env python3
"""Protocol regressions for the C writer observer; actual IO remains separate."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fs_write_suite as observer
from ourosmith.limits import RunBytesResult


class WriteProtocol(unittest.TestCase):
    def result(self, code, phase, counts):
        return RunBytesResult("ok", code, b"", observer.expected_stderr(phase, counts), 0.0, 0.0, [])

    def test_transfer_oracles_preserve_binary_empty_and_cleanup(self):
        self.assertEqual(len(observer.TRANSFER_CASES), 9)
        self.assertEqual(observer.PAYLOAD, b"A\0\xff\x80\r\nZ")
        for name, _mode, code, phase, counts, _prior, expected in observer.TRANSFER_CASES:
            with self.subTest(name=name):
                observer.verify_result(name, self.result(code, phase, counts), code, phase, counts)
                self.assertLessEqual(len(expected), 7)
        self.assertEqual(observer.TRANSFER_CASES[5][-1], observer.PAYLOAD[:-1])
        self.assertEqual(observer.TRANSFER_CASES[6][3:5], ("close", (1, 1, 1)))
        self.assertEqual(observer.TRANSFER_CASES[8][3:5], ("close", (1, 0, 1)))

    def test_old_unit_success_cannot_satisfy_ferror_or_open_failure(self):
        for name, counts in (("full-ferror", (1, 1, 1)), ("empty-ferror", (1, 1, 1)), ("open", (0, 0, 0))):
            with self.subTest(name=name):
                original = self.result(0, None, (counts[0], 0, counts[2]))
                with self.assertRaises(ValueError):
                    observer.verify_result(name, original, 73, "open" if name == "open" else "complete write", counts)

    def test_transport_exit_raw_stream_phase_and_counters_fail_closed(self):
        expected = self.result(73, "complete write", (1, 1, 1))
        variants = (
            ("status", "timeout"), ("status", "memory"), ("status", "spawn-error"), ("status", "skipped"),
            ("returncode", 0), ("returncode", False), ("stdout", b"\0"), ("stdout", ""),
            ("stderr", expected.stderr[:-1]), ("stderr", expected.stderr + b"\0"), ("stderr", ""),
            ("stderr", observer.expected_stderr("close", (1, 1, 1))),
            ("stderr", observer.expected_stderr("complete write", (1, 0, 1))),
            ("stderr", observer.expected_stderr("complete write", (1, 1, 2))),
        )
        for field, value in variants:
            with self.subTest(field=field, value=value):
                result = self.result(73, "complete write", (1, 1, 1))
                setattr(result, field, value)
                with self.assertRaises(ValueError):
                    observer.verify_result("ferror", result, 73, "complete write", (1, 1, 1))

    def test_malformed_driver_requires_exact2_and_empty_streams(self):
        self.assertEqual(len(observer.MALFORMED_CASES), 4)
        observer.verify_result("malformed", self.result(2, None, None), 2, None, None)
        for code, phase, counts in ((0, None, None), (73, "open", (0, 0, 0)), (2, None, (0, 0, 0))):
            with self.assertRaises(ValueError):
                observer.verify_result("malformed", self.result(code, phase, counts), 2, None, None)

    def test_host_crt_endings_remain_exact(self):
        with patch.object(observer.os, "name", "nt"):
            windows = observer.expected_stderr("open", (0, 0, 0))
            self.assertEqual(windows, b"ouro run: fs_write_file: open failed\r\n"
                             b"WRITE_FAULT_COUNTS writes=0 ferrors=0 closes=0\r\n")
            result = RunBytesResult("ok", 73, b"", windows.replace(b"\r\n", b"\n"), 0.0, 0.0, [])
            with self.assertRaises(ValueError):
                observer.verify_result("open", result, 73, "open", (0, 0, 0))

    def test_missing_configured_producer_has_no_fallback(self):
        with tempfile.TemporaryDirectory(prefix="write-missing-") as directory:
            output = Path(directory) / "output"
            with patch.object(observer.shutil, "which", return_value=None), self.assertRaises(ValueError):
                observer.run_suite(Path("missing-configured-cc"), output)
            self.assertFalse(output.exists())

    def _failing_observation(self, mutation=None):
        with tempfile.TemporaryDirectory(prefix="write-protocol-") as directory:
            root = Path(directory).resolve()
            source, compiler, output = root / "source.c", root / "cc", root / "output"
            source.write_bytes(b"source")
            compiler.write_bytes(b"compiler")
            calls = []

            def run(command, **options):
                calls.append((command, options))
                self.assertEqual(options["memory_mb"], 3072)
                self.assertEqual(options["cwd"], root)
                self.assertGreater(options["timeout_s"], 0)
                self.assertLessEqual(options["timeout_s"], 30)
                if command[0] == str(compiler):
                    Path(command[command.index("-o") + 1]).write_bytes(b"object-or-driver")
                    return RunBytesResult("ok", 0, b"", b"", 0.0, 0.0, command)
                self.assertEqual(options["env"]["PATH"], "")
                Path(command[2]).write_bytes(observer.PAYLOAD)
                if mutation is not None:
                    {"source": source, "producer": compiler, "driver": Path(command[0])}[mutation].write_bytes(b"changed")
                    result = self.result(0, None, (1, 1, 1))
                else:
                    result = self.result(0, None, (1, 0, 1))
                result.argv = command
                return result

            with patch.object(observer, "ROOT", root), patch.object(observer, "INPUTS", (source.name,)), \
                    patch.object(observer.shutil, "which", return_value=str(compiler)), \
                    patch.object(observer, "run_limited_bytes", side_effect=run), patch("builtins.print"), \
                    self.assertRaises(ValueError):
                observer.run_suite(compiler, output)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertIs(report["complete"], False)
            return report, calls

    def test_forced_header_is_confined_to_io_translation_unit(self):
        report, calls = self._failing_observation()
        self.assertEqual(len(report["builds"]), 4)
        self.assertEqual(len(calls), 5)
        for index, (command, _options) in enumerate(calls[:3]):
            self.assertEqual("-include" in command, index == 1)
            self.assertIn("-Werror=implicit-function-declaration", command)
        self.assertNotIn("-include", calls[3][0])
        self.assertEqual(report["checks"][0]["transport_status"], "ok")
        self.assertEqual(report["checks"][0]["returncode"], 0)
        self.assertEqual(report["checks"][0]["status"], "fail")
        self.assertIn("exact status or raw streams", report["error"])

    def test_source_producer_and_driver_drift_cannot_complete(self):
        for mutation in ("source", "producer", "driver"):
            with self.subTest(mutation=mutation):
                report, _calls = self._failing_observation(mutation)
                self.assertIn("identity_error", report)
                self.assertEqual(report["checks"][0]["status"], "fail")

    def test_suite_deadline_refuses_before_any_child(self):
        with tempfile.TemporaryDirectory(prefix="write-deadline-") as directory:
            root = Path(directory).resolve()
            source, compiler, output = root / "source.c", root / "cc", root / "output"
            source.write_bytes(b"source")
            compiler.write_bytes(b"compiler")
            with patch.object(observer, "ROOT", root), patch.object(observer, "INPUTS", (source.name,)), \
                    patch.object(observer.shutil, "which", return_value=str(compiler)), \
                    patch.object(observer.time, "monotonic", side_effect=(0.0, 91.0)), \
                    patch.object(observer, "run_limited_bytes") as child, self.assertRaises(ValueError):
                observer.run_suite(compiler, output)
            child.assert_not_called()
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertIs(report["complete"], False)
            self.assertEqual(report["builds"], [])
            self.assertIn("exceeded 90s", report["error"])

    def test_compile_transport_failure_preserves_raw_observation(self):
        with tempfile.TemporaryDirectory(prefix="write-build-") as directory:
            root = Path(directory).resolve()
            source, compiler, output = root / "source.c", root / "cc", root / "output"
            source.write_bytes(b"source")
            compiler.write_bytes(b"compiler")

            def failed(command, **_options):
                return RunBytesResult("memory", 0, b"\0partial\r\n", b"\xfffailed\r\n", 0.0, 0.0, command)

            with patch.object(observer, "ROOT", root), patch.object(observer, "INPUTS", (source.name,)), \
                    patch.object(observer.shutil, "which", return_value=str(compiler)), \
                    patch.object(observer, "run_limited_bytes", side_effect=failed), self.assertRaises(ValueError):
                observer.run_suite(compiler, output)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertIs(report["complete"], False)
            row = report["builds"][0]
            self.assertEqual((row["status"], row["transport_status"], row["returncode"]), ("fail", "memory", 0))
            self.assertEqual(row["stdout_hex"], b"\0partial\r\n".hex())
            self.assertEqual(row["stderr_hex"], b"\xfffailed\r\n".hex())

    def test_existing_output_is_retained_and_refused(self):
        with tempfile.TemporaryDirectory(prefix="write-output-") as directory:
            root = Path(directory)
            compiler, output = root / "cc", root / "output"
            compiler.write_bytes(b"compiler")
            output.mkdir()
            sentinel = output / "report.json"
            sentinel.write_bytes(b"retained")
            with patch.object(observer.shutil, "which", return_value=str(compiler)), self.assertRaises(ValueError):
                observer.run_suite(compiler, output)
            self.assertEqual(sentinel.read_bytes(), b"retained")


if __name__ == "__main__":
    unittest.main()
