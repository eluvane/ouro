"""Check the compiler shard scheduling and result protocol."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch

import compiler_shards
from compiler_shards import COMPILER_SHARDS, SHARD_MEMORY_MIB
from local_scheduler import CheckoutSnapshot, MEMORY_ENV


class CompilerShardTests(unittest.TestCase):
    def test_isolated_copies_prepare_each_parent_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "source"
            paths = ("std/first.ouro", "tools/worker.ouro", "std/second.ouro")
            for relative in paths:
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(relative, encoding="utf-8")
            inventory = b"\0".join(path.encode() for path in paths) + b"\0"
            with patch("local_scheduler.subprocess.check_output", return_value=inventory):
                snapshot = CheckoutSnapshot(source)
            destinations = (root / "first", root / "second")
            with (patch.object(Path, "mkdir", autospec=True, side_effect=Path.mkdir) as mkdir,
                  ThreadPoolExecutor(max_workers=2) as pool):
                list(pool.map(snapshot.copy_to, destinations))
            for checkout in destinations:
                self.assertEqual([call.args[0] for call in mkdir.call_args_list
                                  if call.args[0].parent == checkout], [checkout / "std", checkout / "tools"])
                self.assertEqual([(checkout / path).read_text(encoding="utf-8") for path in paths], list(paths))

            (destinations[0] / paths[0]).write_text("private edit", encoding="utf-8")
            self.assertEqual((destinations[1] / paths[0]).read_text(encoding="utf-8"), paths[0])
            (source / paths[0]).write_text("current input", encoding="utf-8")

            interrupted = root / "interrupted"
            make_directory = Path.mkdir

            def fail_second_parent(path, *args, **kwargs):
                if path == interrupted / "tools":
                    raise PermissionError("cannot create tool directory")
                return make_directory(path, *args, **kwargs)

            with (patch.object(Path, "mkdir", autospec=True, side_effect=fail_second_parent),
                  self.assertRaisesRegex(PermissionError, "cannot create tool directory")):
                snapshot.copy_to(interrupted)
            self.assertEqual((interrupted / paths[0]).read_text(encoding="utf-8"), "current input")
            self.assertFalse((interrupted / paths[2]).exists())

            retry = root / "retry"
            snapshot.copy_to(retry)
            self.assertEqual((retry / paths[0]).read_text(encoding="utf-8"), "current input")
            self.assertEqual([(retry / path).read_text(encoding="utf-8") for path in paths[1:]], list(paths[1:]))

    def test_prepared_runner_requires_current_inputs_and_manifest(self):
        inputs = {"sources": {"tools/test/main.ouro": "digest"}, "fuel": 60000}
        with (tempfile.TemporaryDirectory() as temporary,
              patch("ourosmith.native.receipt_for", return_value=({"inputs": inputs}, [], {})) as receipt,
              patch("ouro_build.load_config") as config,
              patch("native_tool_build.tool_inputs", return_value=([], inputs)) as current):
            root = Path(temporary)
            runner = root / "ouro-test-suite"
            compiler = root / "ouro1"
            manifest = root / "ouro-test-suite.sources"
            manifest.write_text("tools/test/main.ouro\n", encoding="utf-8")
            compiler_shards.verify_prepared_runner(runner, runner, compiler)
            parse_bytes = receipt.call_args.kwargs["parse_bytes"]
            self.assertTrue(callable(parse_bytes))
            receipt.assert_called_once_with(runner, "tools/test/main.ouro", compiler, parse_bytes=parse_bytes)
            current.assert_called_once_with("tools/test/main.ouro", compiler, 60000, config.return_value,
                                            parse_bytes=parse_bytes)
            manifest.write_text("tests/other.ouro\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "prepared test runner inputs differ"):
                compiler_shards.verify_prepared_runner(runner, runner, compiler)
            manifest.write_text("tools/test/main.ouro\n", encoding="utf-8")
            current.return_value = ([], {**inputs, "fuel": 16000})
            with self.assertRaisesRegex(ValueError, "prepared test runner inputs differ"):
                compiler_shards.verify_prepared_runner(runner, runner, compiler)

    def test_budgets_preserve_inventory_and_detect_the_same_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            names = [*(f"case_{index}" for index in range(1, COMPILER_SHARDS)), "source_spans"]
            paths = [*(f"tests/{name}.ouro" for name in names[:-1]), "tests/source_span_tests.ouro"]
            suite = root / "tools/test/suites.ouro"
            suite.parent.mkdir(parents=True)
            suite.write_text("def compiler_check_suite_fixtures : List SuiteFixture :=\n["
                             + ",\n".join(f'MkSuiteFixture "{name}" "{path}" Z SuiteGoldenNone'
                                          for name, path in zip(names, paths, strict=True)) + "];\n",
                             encoding="utf-8")
            expected = [f"COMPILER_CHECK_OK {name}-run" for name in names]

            def exercise(jobs, *, inject_failure=False, memory=SHARD_MEMORY_MIB * COMPILER_SHARDS):
                out = root / f"result-{jobs}-{inject_failure}-{memory}"
                out.mkdir()
                active = min(jobs, memory // SHARD_MEMORY_MIB, COMPILER_SHARDS)
                barrier = Barrier(active) if active > 1 else None

                def run(command, *, cwd, env, stdout, stderr):
                    shard = int(command[3].split("=", 1)[1].split("/", 1)[0])
                    self.assertEqual(env["OURO_JOBS"], "1")
                    self.assertEqual(env["OURO_FRONTEND_JOBS"], "1")
                    self.assertEqual(env[MEMORY_ENV], str(SHARD_MEMORY_MIB))
                    self.assertEqual(Path(env["OURO_BUILD_DIR"]), cwd / "_build")
                    self.assertEqual(Path(env["OURO_C_BUILD_DIR"]), cwd / "_build/c")
                    self.assertEqual(Path(env["OURO_CACHE_DIR"]), cwd / "_cache")
                    self.assertEqual(command[4:] == ["--suite-probe-failure"], inject_failure)
                    marker = cwd / "_build/source_spans.progress"
                    with marker.open("x", encoding="utf-8") as stream:
                        stream.write(str(shard))
                    if barrier is not None and shard <= active:
                        barrier.wait(timeout=10)
                    if inject_failure and shard == 2:
                        stderr.write(b"COMPILER_CHECK_FAIL case_2-run exit=1 want=0\n")
                        return subprocess.CompletedProcess(command, 1)
                    stdout.write((expected[shard - 1] + "\nCOMPILER_CHECK_SUITE: PASS rows=1 out="
                                  + env["OURO_TEST_SUITE_DISPLAY_OUT"] + "\n").encode())
                    return subprocess.CompletedProcess(command, 0)

                stdout = io.StringIO()
                stderr_bytes = io.BytesIO()
                stderr = io.TextIOWrapper(stderr_bytes, encoding="utf-8")
                try:
                    with (contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr),
                          patch.object(compiler_shards, "ROOT", root),
                          patch.object(compiler_shards, "CheckoutSnapshot") as snapshot,
                          patch.object(compiler_shards.subprocess, "run", side_effect=run),
                          patch.dict(os.environ, {MEMORY_ENV: str(memory)})):
                        snapshot.return_value.copy_to.side_effect = lambda path: path.mkdir()
                        status = compiler_shards.run_shards(root / "runner", out, jobs=jobs,
                                                            native=True, probe_failure=inject_failure)
                    stderr.flush()
                    report = json.loads((out / "shards.json").read_text(encoding="utf-8"))
                    self.assertEqual(status, int(inject_failure))
                    self.assertEqual(report["pass"], not inject_failure)
                    self.assertEqual([row["shard"] for row in report["shards"]], list(range(1, COMPILER_SHARDS + 1)))
                    self.assertEqual([[line] for line in expected], [row["fixture_rows"] for row in report["shards"]])
                    self.assertEqual(len(list(out.glob("*/src/_build/source_spans.progress"))), COMPILER_SHARDS)
                    return report, stdout.getvalue().splitlines(), stderr_bytes.getvalue()
                finally:
                    stderr.close()

            for jobs in (1, 20):
                with self.subTest(jobs=jobs):
                    report, lines, error = exercise(jobs)
                    self.assertEqual(report["schedule"]["peak_tasks"], min(jobs, COMPILER_SHARDS))
                    self.assertEqual(lines[:-1], expected)
                    self.assertEqual(error, b"")
                    failed, lines, error = exercise(jobs, inject_failure=True)
                    self.assertEqual([row["shard"] for row in failed["shards"] if not row["pass"]], [2])
                    self.assertEqual(lines, [expected[0], *expected[2:]])
                    self.assertIn(b"COMPILER_CHECK_FAIL case_2-run", error)
            throttled, _, _ = exercise(20, memory=SHARD_MEMORY_MIB)
            self.assertEqual(throttled["schedule"]["peak_tasks"], 1)


if __name__ == "__main__":
    unittest.main()
