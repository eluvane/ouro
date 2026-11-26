"""Run the complete compiler suite using the native inventory's shards."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from local_scheduler import (
    Allocation, CheckoutSnapshot, DEFAULT_JOBS, Task,
    available_memory_mib, bounded_jobs, positive_integer, run_tasks,
)
from repo_support import write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
COMPILER_SHARDS = 16
SHARD_MEMORY_MIB = 3072


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
    results, schedule = run_tasks(tasks, jobs=jobs, memory_mib=available_memory_mib(), run=run)
    shards = [results[task.name] for task in tasks]
    passed = all(shard["pass"] for shard in shards)
    report = out / "shards.json"
    write_json_atomic(report, {
        "kind": "ouro.compiler-shards.v1", "pass": passed, "schedule": schedule,
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--verify-with", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--jobs", default="")
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--suite-probe-failure", action="store_true")
    args = parser.parse_args()
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
        return run_shards(runner.resolve(strict=True), args.out.resolve(strict=True),
                          jobs=bounded_jobs(requested), native=args.native,
                          probe_failure=args.suite_probe_failure)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"COMPILER_CHECK_SUITE: FAIL {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
