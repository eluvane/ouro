"""Check the compiler shard scheduling and result protocol."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import contextlib
import io
import json
import os
from pathlib import Path
from stat import FILE_ATTRIBUTE_REPARSE_POINT, S_IFDIR
import subprocess
import sys
import tempfile
from threading import Barrier
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import compiler_shards
from compiler_shards import (
    COMPILER_SHARDS, SHARD_MEMORY_MIB, SHARD_PREWARM_ENV, SHARD_PREWARM_MEMORY_MIB, SHARD_PREWARM_TIMEOUT_S,
)
from local_scheduler import CheckoutSnapshot, JOBS_ENV, MEMORY_ENV
from native_tool_build import COMPILER_SHARD_C_WORKERS_ENV
from repo_support import hash_json


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

    def test_hosted_prewarm_reuses_build_protocol_and_keeps_the_native_verdict(self):
        rows = [(f"case{index}", f"tests/case{index}.ouro") for index in range(16)]
        rows.append(("source_spans", "tests/source_span_tests.ouro"))
        names = ("case0", "case15")

        def exercise(fault, expected_warmed):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                wrapper = (root / "scripts/build_tool.sh").as_posix()
                compiler_dir = (root / "_build/c").as_posix()
                state = {"locked": False}

                @contextlib.contextmanager
                def cache_access(_config):
                    state["locked"] = True
                    try:
                        yield
                    finally:
                        state["locked"] = False

                index = COMPILER_SHARDS if fault == "isolated-shard" else 1
                out = root / "_build" / f"compiler_check_suite_{index}"
                out.mkdir(parents=True, exist_ok=True)
                runner = out / "ouro-test-suite"
                shard = f"{index}/{COMPILER_SHARDS}"
                command = [str(runner), "--native-suite=compiler-checking", f"--out={out}", f"--shard={shard}"]
                cache = root.parent if fault == "outside-cache" else root / "_cache/ouro"
                config = Mock()
                config.get_bool.return_value = fault != "disabled"
                config.path.return_value = cache
                worker_started = Barrier(2)
                built = []
                env = {
                    SHARD_PREWARM_ENV: "1", COMPILER_SHARD_C_WORKERS_ENV: "2", JOBS_ENV: "2",
                    MEMORY_ENV: str(SHARD_PREWARM_MEMORY_MIB - (fault == "budget")),
                    "GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "pull_request",
                    "OURO_TEST_BUILD": wrapper, "OURO_C_BUILD_DIR": compiler_dir,
                    "OURO_JOBS": "1", "OURO_FRONTEND_JOBS": "1", "RAYON_NUM_THREADS": "1",
                }
                native_env = {key: value for key, value in env.items() if key != SHARD_PREWARM_ENV}

                def launch(argv, *, cwd, env, **options):
                    self.assertEqual(cwd, root)
                    self.assertEqual(env, native_env)
                    if argv[-1] == "--check":
                        self.assertTrue(state["locked"])
                        self.assertEqual(argv[1:], ["scripts/native_tool_build.py", "tools/test/main.ouro",
                                                    str(runner), "--compiler", str(Path(compiler_dir) / "ouro1"),
                                                    "--check"])
                        self.assertEqual(options["timeout"], 60)
                        return SimpleNamespace(returncode=int(fault == "stale-runner"))
                    if argv[-1] == "--list":
                        self.assertTrue(state["locked"])
                        self.assertEqual(argv, [*command, "--list"])
                        listing = b"tests/case0.ouro\ntests/case15.ouro\n"
                        return SimpleNamespace(returncode=0, stderr=b"",
                                               stdout=listing if fault != "inventory" else b"")
                    self.assertFalse(state["locked"])
                    self.assertEqual(argv, command)
                    self.assertCountEqual(built, names if expected_warmed else ())
                    return SimpleNamespace(returncode=0 if expected_warmed else -9)

                def build(argv, *, cwd, env, timeout_s, memory_mb):
                    self.assertTrue(state["locked"])
                    self.assertEqual(cwd, root)
                    name = Path(argv[3]).stem
                    self.assertIn(name, names)
                    self.assertEqual(argv, ["sh", wrapper, f"tests/{name}.ouro", str(out / f"{name}.exe")])
                    self.assertEqual((env[JOBS_ENV], env[MEMORY_ENV], env["OURO_JOBS"],
                                      env["OURO_FRONTEND_JOBS"], env["RAYON_NUM_THREADS"], memory_mb),
                                     ("1", "3072", "1", "1", "1", SHARD_MEMORY_MIB))
                    self.assertEqual(timeout_s, SHARD_PREWARM_TIMEOUT_S)
                    self.assertNotIn(COMPILER_SHARD_C_WORKERS_ENV, env)
                    self.assertNotIn(SHARD_PREWARM_ENV, env)
                    built.append(name)
                    worker_started.wait(timeout=5)
                    failed = fault == "worker" and name == names[0]
                    return SimpleNamespace(status="ok", returncode=int(failed),
                                           stdout=b"build output\n", stderr=b"build error\n")

                with (patch.dict(os.environ, env, clear=True), patch.object(compiler_shards, "ROOT", root),
                      patch.object(compiler_shards.sys, "platform", "linux"),
                      patch("ouro_build.load_config", return_value=config),
                      patch("ouro_build.cache_build_access", side_effect=cache_access),
                      patch("ouro_build.trim_cache") as trim,
                      patch("ci_gate.compiler_fixture_rows", return_value=rows),
                      patch.object(compiler_shards.subprocess, "run", side_effect=launch),
                      patch("ourosmith.limits.run_limited_bytes", side_effect=build)):
                    self.assertEqual(compiler_shards.run_hosted_shard(runner, out, shard),
                                     0 if expected_warmed else 137)
                if expected_warmed:
                    trim.assert_called_once_with(config)
                    report_path = next(out.glob("prewarm-*/prewarm.json"))
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                    self.assertEqual(report["failed"], [names[0]] if fault == "worker" else [])
                    self.assertEqual(report["schedule"]["peak_tasks"], 2)
                    self.assertEqual(report["schedule"]["peak_memory_mib"], SHARD_PREWARM_MEMORY_MIB)
                    self.assertEqual((report_path.parent / f"{names[0]}.stderr").read_bytes(), b"build error\n")

        for fault, expected_warmed in (
            ("none", True), ("worker", True), ("stale-runner", False), ("inventory", False), ("budget", False),
            ("disabled", False), ("outside-cache", False), ("isolated-shard", False),
        ):
            with self.subTest(fault=fault):
                exercise(fault, expected_warmed)

    def test_prewarm_cli_rejects_modes_that_own_the_runner_or_verdict(self):
        for extra in (["--verify-with", "ouro1"], ["--native"], ["--suite-probe-failure"], ["--jobs=2"]):
            with (self.subTest(extra=extra),
                  patch.object(sys, "argv", ["compiler_shards.py", "--runner", "runner", "--out", "out",
                                            "--prewarm-shard=1/16", *extra]),
                  contextlib.redirect_stderr(io.StringIO()) as stderr, self.assertRaises(SystemExit) as stopped):
                compiler_shards.main()
            self.assertEqual(stopped.exception.code, 2)
            self.assertIn("--prewarm-shard cannot be combined", stderr.getvalue())

    def test_timing_history_requires_matching_successful_shards(self):
        checks = {"1": ["first", "second"], "2": ["third"]}
        rows = [("first", "tests/first.ouro"), ("third", "tests/third.ouro"), ("second", "tests/second.ouro")]
        inventory_sha256 = hash_json(rows)
        shards = [{"shard": int(name), "pass": True, "returncode": 0, "elapsed_s": 90 if name == "1" else 2,
                   "fixture_rows": expected, "completed_rows": expected} for name, expected in checks.items()]
        report = {"kind": compiler_shards.SHARD_REPORT_KIND, "pass": True, "native": True,
                  "inventory_sha256": inventory_sha256, "shards": shards}
        first, second = shards
        invalid = (
            ("failed report", {**report, "pass": False}),
            ("runner mode", {**report, "native": False}),
            ("legacy report", {key: value for key, value in report.items() if key != "inventory_sha256"}),
            ("fixture path", {**report, "inventory_sha256": hash_json([("first", "tests/moved.ouro"), *rows[1:]])}),
            ("inventory order", {**report, "inventory_sha256": hash_json(rows[::-1])}),
            ("shard order", {**report, "shards": shards[::-1]}),
            ("missing shard", {**report, "shards": [first]}),
            ("boolean shard index", {**report, "shards": [{**first, "shard": True}, second]}),
            ("float shard index", {**report, "shards": [{**first, "shard": 1.0}, second]}),
            ("failed shard", {**report, "shards": [{**first, "pass": False}, second]}),
            ("failed process", {**report, "shards": [{**first, "returncode": 1}, second]}),
            ("boolean return code", {**report, "shards": [{**first, "returncode": False}, second]}),
            ("float return code", {**report, "shards": [{**first, "returncode": 0.0}, second]}),
            ("shard fixture order", {**report, "shards": [{**first, "fixture_rows": checks["1"][::-1]}, second]}),
            ("incomplete shard", {**report, "shards": [{**first, "completed_rows": ["first"]}, second]}),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def publish(name, raw, mtime):
                directory = root / name
                directory.mkdir(exist_ok=True)
                path = directory / "shards.json"
                path.write_bytes(raw)
                os.utime(path, (mtime, mtime))

            def timings(out):
                return compiler_shards.recent_shard_timings(out, checks, inventory_sha256, native=True)

            other = json.dumps(report).encode()
            publish("run.z-older", other, 100)
            publish("run.a-newer", json.dumps({**report, "shards": [{**first, "elapsed_s": 1}, second]}).encode(), 101)
            publish("run.current", other, 104)
            publish("other-directory", other, 105)
            out = root / "run.current"
            self.assertEqual(timings(out), {"1": 1, "2": 2})
            for label, bad in invalid:
                with self.subTest(label=label):
                    publish("run.invalid", json.dumps(bad).encode(), 102)
                    self.assertEqual(timings(out), {"1": 1, "2": 2})
            for elapsed in (False, 0, -1, "4", float("nan"), float("inf"), 10**400):
                with self.subTest(elapsed=elapsed):
                    bad = {**report, "shards": [{**first, "elapsed_s": elapsed}, second]}
                    publish("run.invalid", json.dumps(bad).encode(), 102)
                    self.assertEqual(timings(out), {"1": 1, "2": 2})
            for field, duplicate in (
                (b'"pass": true', b'"pass": false, "pass": true'),
                (b'"returncode": 0', b'"returncode": 1, "returncode": 0'),
            ):
                with self.subTest(duplicate=duplicate):
                    publish("run.invalid", other.replace(field, duplicate, 1), 102)
                    self.assertEqual(timings(out), {"1": 1, "2": 2})
            publish("run.invalid", b"{", 102)
            publish("run.oversize", other + b" " * compiler_shards.TIMING_REPORT_MAX_BYTES, 103)
            self.assertEqual(timings(out), {"1": 1, "2": 2})
            self.assertIsNone(timings(root / "direct-output"))

            junction = Mock(name="junction")
            junction.name = "run.junction"
            junction.path = str(root / "other-directory")
            junction.is_dir.return_value = True
            junction.stat.return_value = SimpleNamespace(
                st_mode=S_IFDIR, st_file_attributes=FILE_ATTRIBUTE_REPARSE_POINT,
            )
            with os.scandir(root) as entries:
                candidates = [junction, *entries]
            with patch.object(compiler_shards.os, "scandir") as scan:
                scan.return_value.__enter__.return_value = candidates
                self.assertEqual(timings(out), {"1": 1, "2": 2})

            for index in range(compiler_shards.TIMING_REPORT_LIMIT):
                publish(f"run.invalid-{index}", b"{", 106 + index)
            self.assertIsNone(timings(out))

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

            shard_order = list(range(1, COMPILER_SHARDS + 1))

            def exercise(jobs, *, inject_failure=False, memory=SHARD_MEMORY_MIB * COMPILER_SHARDS,
                         out=None, expected_order=shard_order):
                if out is None:
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
                    if barrier is not None and shard in expected_order[:active]:
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
                          patch.object(compiler_shards, "run_tasks", wraps=compiler_shards.run_tasks) as schedule,
                          patch.dict(os.environ, {MEMORY_ENV: str(memory)})):
                        snapshot.return_value.copy_to.side_effect = lambda path: path.mkdir()
                        status = compiler_shards.run_shards(root / "runner", out, jobs=jobs,
                                                            native=True, probe_failure=inject_failure)
                    stderr.flush()
                    report = json.loads((out / "shards.json").read_text(encoding="utf-8"))
                    self.assertEqual(status, int(inject_failure))
                    self.assertEqual(report["pass"], not inject_failure)
                    self.assertEqual([int(task.name) for task in schedule.call_args.args[0]], expected_order)
                    self.assertEqual([row["shard"] for row in report["shards"]], shard_order)
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

            prior = root / "run.prior"
            timed, _, _ = exercise(1, out=prior)
            for row in timed["shards"]:
                row["elapsed_s"] = {COMPILER_SHARDS: 30, 3: 20, 12: 20}.get(row["shard"], 10)
            (prior / "shards.json").write_text(json.dumps(timed), encoding="utf-8")
            longest_first = [COMPILER_SHARDS, 3, 12, *(shard for shard in shard_order
                                                     if shard not in {COMPILER_SHARDS, 3, 12})]
            timed_failure, lines, error = exercise(20, inject_failure=True, memory=2 * SHARD_MEMORY_MIB,
                                                   out=root / "run.timed-failure", expected_order=longest_first)
            self.assertEqual(timed_failure["schedule"]["peak_tasks"], 2)
            self.assertEqual(timed_failure["schedule"]["peak_memory_mib"], 2 * SHARD_MEMORY_MIB)
            self.assertEqual(lines, [expected[0], *expected[2:]])
            self.assertIn(b"COMPILER_CHECK_FAIL case_2-run", error)
            _, lines, error = exercise(2, out=root / "run.timed-success", expected_order=longest_first)
            self.assertEqual(lines[:-1], expected)
            self.assertEqual(error, b"")
            exercise(1, out=root / "run.serial")
            exercise(20, out=root / "run.serial-memory", memory=SHARD_MEMORY_MIB)
            exercise(20, out=root / "run.one-wave")


if __name__ == "__main__":
    unittest.main()
