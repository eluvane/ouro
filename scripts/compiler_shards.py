"""Run the complete compiler suite using the native inventory's shards."""
from __future__ import annotations

import argparse
from contextlib import suppress
from heapq import nlargest
import json
import os
from pathlib import Path
import shutil
from stat import FILE_ATTRIBUTE_REPARSE_POINT, S_ISDIR, S_ISREG
import subprocess
import sys
import tempfile
import time
from typing import TYPE_CHECKING

from local_scheduler import (
    Allocation, CheckoutSnapshot, DEFAULT_JOBS, JOBS_ENV, MEMORY_ENV, Task,
    available_memory_mib, bounded_jobs, positive_integer, run_tasks,
)
from repo_support import finite_number, hash_json, write_json_atomic

if TYPE_CHECKING:
    from collections.abc import Iterator

ROOT = Path(__file__).resolve().parents[1]
COMPILER_SHARDS = 16
SHARD_MEMORY_MIB = 3072
SHARD_PREWARM_MEMORY_MIB = 2 * SHARD_MEMORY_MIB
SHARD_PREWARM_ENV = "OURO_CI_COMPILER_SHARD_PREWARM"
# Match the compiler fixture timeout in tools/test/process_model.ouro.
SHARD_PREWARM_TIMEOUT_S = 1800
SHARD_REPORT_KIND = "ouro.compiler-shards.v1"
TIMING_REPORT_LIMIT = 8
TIMING_REPORT_MAX_BYTES = 256 * 1024


def _timing_candidates(out: Path) -> Iterator[tuple[int, str, Path]]:
    try:
        with os.scandir(out.parent) as entries:
            for entry in entries:
                if entry.name == out.name or not entry.name.startswith("run."):
                    continue
                try:
                    directory = entry.stat(follow_symlinks=False)
                    if (not S_ISDIR(directory.st_mode)
                            or getattr(directory, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT):
                        continue
                    path = Path(entry.path) / "shards.json"
                    info = path.lstat()
                except OSError:
                    continue
                if S_ISREG(info.st_mode) and info.st_size <= TIMING_REPORT_MAX_BYTES:
                    yield info.st_mtime_ns, entry.name, path
    except OSError:
        return


def _unique_timing_report_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError("duplicate shard timing report field")
    return fields


def _read_shard_timings(path: Path, checks: dict[str, list[str]], inventory_sha256: str,
                        *, native: bool) -> dict[str, float] | None:
    with path.open("rb") as stream:
        raw = stream.read(TIMING_REPORT_MAX_BYTES + 1)
    if len(raw) > TIMING_REPORT_MAX_BYTES:
        return None
    report = json.loads(raw, object_pairs_hook=_unique_timing_report_fields)
    if (not isinstance(report, dict) or report.get("kind") != SHARD_REPORT_KIND
            or report.get("pass") is not True or report.get("inventory_sha256") != inventory_sha256
            or report.get("native") is not native):
        return None
    shards = report.get("shards")
    if not isinstance(shards, list) or len(shards) != len(checks):
        return None
    timings = {}
    for (name, expected), shard in zip(checks.items(), shards, strict=True):
        if not isinstance(shard, dict):
            return None
        index = shard.get("shard")
        returncode = shard.get("returncode")
        elapsed = shard.get("elapsed_s")
        if (type(index) is not int or index != int(name) or shard.get("pass") is not True
                or type(returncode) is not int or returncode != 0
                or shard.get("fixture_rows") != expected or shard.get("completed_rows") != expected
                or not finite_number(elapsed) or elapsed == 0):
            return None
        timings[name] = elapsed
    return timings


def recent_shard_timings(out: Path, checks: dict[str, list[str]], inventory_sha256: str,
                         *, native: bool) -> dict[str, float] | None:
    if out.name.startswith("run."):
        for _, _, path in nlargest(TIMING_REPORT_LIMIT, _timing_candidates(out)):
            try:
                timings = _read_shard_timings(path, checks, inventory_sha256, native=native)
            except (OSError, ValueError, RecursionError, OverflowError):
                continue
            if timings is not None:
                return timings
    return None


def freeze_host_tools(out: Path) -> tuple[Path, ...]:
    source = ROOT / os.environ.get("OURO_C_BUILD_DIR", "_build/c")
    host = out / "host"
    host.mkdir()
    tools = tuple(host / name for name in ("ouro1.exe", "ouro1", "ouro-collect.exe",
                                           "ouro-collect", "ouro1.bootstrap.json")
                  if (source / name).is_file())
    if not any(path.name in {"ouro1.exe", "ouro1"} for path in tools):
        raise ValueError(f"compiler unavailable in {source}")
    for path in tools:
        shutil.copy2(source / path.name, path)
    return tools


def shard_environment(checkout: Path, out: Path, allocation: Allocation,
                      tools: tuple[Path, ...]) -> dict[str, str]:
    build = checkout / "_build"
    c_build = build / "c"
    c_build.mkdir(parents=True)
    env = {
        **os.environ, **allocation.environment(),
        "OURO_ROOT": checkout.as_posix(),
        "OURO_BUILD_DIR": build.as_posix(),
        "OURO_C_BUILD_DIR": c_build.as_posix(),
        "OURO_CACHE_DIR": (checkout / "_cache").as_posix(),
        "OURO_TEST_SUITE_DISPLAY_OUT": out.as_posix(),
    }
    if tools:
        for tool in tools:
            shutil.copy2(tool, c_build / tool.name)
        wrapper = (checkout / "scripts/ouro1.sh").as_posix()
        env.update(OURO_TEST_CHECK=wrapper, OURO_HOSTED_COMPILER_WRAPPER=wrapper,
                   OURO_TEST_BUILD=(checkout / "scripts/build_tool.sh").as_posix())
        if env.get("OURO1_COMPILER"):
            env["OURO1_COMPILER"] = (ROOT / env["OURO1_COMPILER"]).resolve().as_posix()
    return env


def run_shards(runner: Path, out: Path, *, jobs: int, native: bool, probe_failure: bool) -> int:
    from ci_gate import compiler_fixture_rows, compiler_shard_entries

    rows = compiler_fixture_rows(ROOT)
    inventory_sha256 = hash_json(rows)
    inventory = [path for _, path in rows]
    names = {path: name for name, path in rows}
    checks = {str(index): [f"COMPILER_CHECK_OK {names[path]}-run"
                          for path in compiler_shard_entries(inventory, index)]
              for index in range(1, COMPILER_SHARDS + 1)}
    snapshot = CheckoutSnapshot(ROOT)
    tools = () if native else freeze_host_tools(out)
    started = time.perf_counter()

    def run(task: Task, allocation: Allocation) -> dict:
        shard_started = time.perf_counter()
        directory = out / task.name
        directory.mkdir()
        checkout = directory / "src"
        artifacts = checkout / "_build" / "tests"
        stdout_path, stderr_path = directory / "stdout.log", directory / "stderr.log"
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            command = [str(runner), "--native-suite=compiler-checking", f"--out={artifacts.as_posix()}",
                       f"--shard={task.name}/{COMPILER_SHARDS}"]
            if probe_failure:
                command.append("--suite-probe-failure")
            try:
                snapshot.copy_to(checkout)
                env = shard_environment(checkout, artifacts, allocation, tools)
                result = subprocess.run(command, cwd=checkout, env=env, stdout=stdout, stderr=stderr)
            except (OSError, ValueError) as exc:
                stderr.write(f"COMPILER_CHECK_SUITE: shard {task.name}: {exc}\n".encode())
                returncode = 1
            else:
                returncode = result.returncode
        expected = checks[task.name]
        printed = stdout_path.read_text(encoding="utf-8", errors="replace").splitlines()
        terminal = f"COMPILER_CHECK_SUITE: PASS rows={len(expected)} out={artifacts.as_posix()}"
        passed = returncode == 0 and printed == [*expected, terminal]
        return {"shard": int(task.name), "returncode": returncode, "pass": passed,
                "jobs": allocation.jobs, "memory_mib": allocation.memory_mib,
                "start_s": round(shard_started - started, 6),
                "elapsed_s": round(time.perf_counter() - shard_started, 6),
                "stdout": str(stdout_path), "stderr": str(stderr_path), "artifacts": str(artifacts),
                "fixture_rows": expected, "completed_rows": [row for row in printed if row in expected]}

    tasks = [Task(name, max_jobs=1, memory_mib=SHARD_MEMORY_MIB) for name in checks]
    memory_mib = available_memory_mib()
    slots = jobs if memory_mib is None else min(jobs, memory_mib // SHARD_MEMORY_MIB)
    dispatch = tasks
    if 1 < slots < len(tasks):
        timings = recent_shard_timings(out, checks, inventory_sha256, native=native)
        if timings is not None:
            dispatch = sorted(tasks, key=lambda task: timings[task.name], reverse=True)
    results, schedule = run_tasks(dispatch, jobs=jobs, memory_mib=memory_mib, run=run)
    shards = [results[task.name] for task in tasks]
    passed = all(shard["pass"] for shard in shards)
    report = out / "shards.json"
    write_json_atomic(report, {
        "kind": SHARD_REPORT_KIND, "pass": passed, "schedule": schedule,
        "inventory_sha256": inventory_sha256, "native": native,
        "elapsed_s": round(time.perf_counter() - started, 6), "shards": shards,
    })
    completed = {line for shard in shards for line in shard["completed_rows"]}
    for name, _ in rows:
        line = f"COMPILER_CHECK_OK {name}-run"
        if line in completed:
            print(line)
    sys.stdout.flush()
    for shard in shards:
        with Path(shard["stderr"]).open("rb") as stderr:
            shutil.copyfileobj(stderr, sys.stderr.buffer)
        if not shard["pass"] and shard["returncode"] == 0:
            print(f"COMPILER_CHECK_SUITE: shard {shard['shard']} returned an incomplete result",
                  file=sys.stderr)
    if passed:
        print(f"COMPILER_CHECK_SUITE: PASS rows={len(rows)} out={out.as_posix()}")
    else:
        print(f"COMPILER_CHECK_SUITE: FAIL report={report.as_posix()}", file=sys.stderr)
    return int(not passed)


def verify_prepared_runner(logical: Path, runner: Path, compiler: Path) -> None:
    import native_tool_build
    import ouro_build
    from ourosmith.native import receipt_for
    from selfhost_module_cache import cached_import_parser

    entry = "tools/test/main.ouro"
    parse_bytes = cached_import_parser()
    receipt, _, _ = receipt_for(runner, entry, compiler, parse_bytes=parse_bytes)
    cfg = ouro_build.load_config(argparse.Namespace())
    _, inputs = native_tool_build.tool_inputs(entry, compiler, 60000, cfg, parse_bytes=parse_bytes)
    manifest = logical.with_name(logical.name + ".sources")
    if receipt["inputs"] != inputs or manifest.read_text(encoding="utf-8").splitlines() != list(inputs["sources"]):
        raise ValueError("prepared test runner inputs differ from the current build configuration")


def _prewarm_fixtures(command: list[str], out: Path, index: int, env: dict[str, str], logs: Path) -> None:
    from ci_gate import compiler_fixture_rows, compiler_shard_entries
    from native_tool_build import COMPILER_SHARD_C_WORKERS_ENV
    from ourosmith.limits import run_limited_bytes

    compiler = ROOT / env["OURO_C_BUILD_DIR"] / "ouro1"
    verify = [sys.executable, "scripts/native_tool_build.py", "tools/test/main.ouro", command[0],
              "--compiler", str(compiler), "--check"]
    with (logs / "runner-check.log").open("wb") as log:
        verified = subprocess.run(verify, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=60)
    if verified.returncode:
        raise ValueError("runner cache evidence differs")

    names = {path: name for name, path in compiler_fixture_rows(ROOT)}
    entries = compiler_shard_entries(list(names), index)
    listed = subprocess.run([*command, "--list"], cwd=ROOT, env=env, capture_output=True, timeout=30)
    if listed.returncode or listed.stderr or listed.stdout.decode("utf-8").splitlines() != entries:
        raise ValueError("runner fixture inventory differs")

    by_name = {names[path]: path for path in entries}

    def build_fixture(task: Task, allocation: Allocation) -> bool:
        worker_env = {**env, **allocation.environment()}
        worker_env.pop(COMPILER_SHARD_C_WORKERS_ENV, None)
        name = task.name
        result = run_limited_bytes(["sh", env["OURO_TEST_BUILD"], by_name[name], str(out / f"{name}.exe")],
                                   cwd=ROOT, env=worker_env, timeout_s=SHARD_PREWARM_TIMEOUT_S,
                                   memory_mb=allocation.memory_mib)
        (logs / f"{name}.stdout").write_bytes(result.stdout)
        (logs / f"{name}.stderr").write_bytes(result.stderr)
        return result.status != "ok" or result.returncode != 0

    tasks = [Task(name, max_jobs=1, memory_mib=SHARD_MEMORY_MIB) for name in by_name]
    results, stats = run_tasks(tasks, jobs=2, memory_mib=SHARD_PREWARM_MEMORY_MIB, run=build_fixture, stop=bool)
    write_json_atomic(logs / "prewarm.json", {
        "schedule": stats, "failed": [name for name in by_name if results.get(name) is True],
        "not_run": [name for name in by_name if name not in results],
    })


def run_hosted_shard(runner: Path, out: Path, shard: str) -> int:
    from ouro_build import cache_build_access, load_config, trim_cache

    env = os.environ.copy()
    warm = env.pop(SHARD_PREWARM_ENV, None) == "1"
    command = [str(runner), "--native-suite=compiler-checking", f"--out={out}", f"--shard={shard}"]
    allowed = {f"{index}/{COMPILER_SHARDS}": index for index in range(1, COMPILER_SHARDS)}
    index = allowed.get(shard)

    def run_native() -> int:
        status = subprocess.run(command, cwd=ROOT, env=env).returncode
        return status if status >= 0 else 128 - status

    if (not warm or index is None or sys.platform != "linux"
            or env.get("GITHUB_ACTIONS") != "true" or env.get("GITHUB_EVENT_NAME") != "pull_request"
            or env.get(JOBS_ENV) != "2" or MEMORY_ENV not in env
            or out != ROOT / "_build" / f"compiler_check_suite_{index}" or runner != out / "ouro-test-suite"
            or env.get("OURO_TEST_BUILD") != (ROOT / "scripts/build_tool.sh").as_posix()
            or env.get("OURO_BUILD_TOOL_MODE", "native") != "native"
            or not env.get("OURO_C_BUILD_DIR")):
        return run_native()

    logs = None
    try:
        memory = available_memory_mib()
        cfg = load_config(argparse.Namespace())
        if (memory is not None and memory >= SHARD_PREWARM_MEMORY_MIB and cfg.get_bool("cache_enabled")
                and cfg.path("cache_dir").resolve().is_relative_to(ROOT / "_cache")):
            logs = Path(tempfile.mkdtemp(prefix="prewarm-", dir=out))
            # The verified runner primes shared runtime objects. Hold the lease to prevent eviction.
            with cache_build_access(cfg):
                _prewarm_fixtures(command, out, index, env, logs)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        if logs is not None:
            with suppress(OSError):
                (logs / "fallback.log").write_text(f"{exc}\n", encoding="utf-8")

    try:
        return run_native()
    finally:
        if logs is not None:
            try:
                trim_cache(cfg)
            except OSError as exc:
                with suppress(OSError):
                    (logs / "cache-trim.log").write_text(f"{exc}\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--verify-with", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--prewarm-shard", help=argparse.SUPPRESS)
    parser.add_argument("--jobs", default="")
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--suite-probe-failure", action="store_true")
    args = parser.parse_args()
    if args.prewarm_shard is not None and (args.verify_with is not None or args.native or args.suite_probe_failure
                                          or args.jobs):
        parser.error("--prewarm-shard cannot be combined with --verify-with, --native, --suite-probe-failure, or --jobs")
    try:
        requested = DEFAULT_JOBS
        if args.jobs == "auto":
            requested = os.cpu_count() or 1
        elif args.jobs:
            requested = positive_integer(args.jobs, "OURO_JOBS")
        runner = args.runner.resolve()
        if os.name == "nt" and not runner.is_file():
            runner = Path(f"{runner}.exe")
        if args.verify_with is not None:
            verify_prepared_runner(args.runner.resolve(), runner, args.verify_with.resolve())
            return 0
        if args.out is None:
            parser.error("--out is required when running shards")
        if args.prewarm_shard is not None:
            return run_hosted_shard(runner.resolve(strict=True), args.out.resolve(strict=True), args.prewarm_shard)
        return run_shards(runner.resolve(strict=True), args.out.resolve(strict=True),
                          jobs=bounded_jobs(requested), native=args.native,
                          probe_failure=args.suite_probe_failure)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"COMPILER_CHECK_SUITE: FAIL {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
