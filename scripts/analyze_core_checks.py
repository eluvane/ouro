#!/usr/bin/env python3
"""Run analyzer core checks in order-preserving, bounded parallel processes.

Windows bounds up to ten workers with one 3 GiB Job Object. Linux reserves
2944 MiB per worker and parallelizes only after the shared tools are warm.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from local_scheduler import JOBS_ENV, available_memory_mib, bounded_jobs
from ourosmith import ROOT
from ourosmith.host import environment, job_count, shell
from ourosmith.limits import run_limited
from repo_support import write_json_atomic


POSIX_WORKER_MEMORY_MIB = 2944
POOL_CONTROLLER_MEMORY_MIB = 128


def pool_jobs(requested: int, remaining: int) -> int:
    jobs = min(bounded_jobs(max(1, requested)), max(1, remaining))
    if os.name == "nt":
        return min(10, jobs)
    if sys.platform == "linux" and jobs > 1:
        budget = available_memory_mib()
        if budget is not None and budget >= POOL_CONTROLLER_MEMORY_MIB + 2 * POSIX_WORKER_MEMORY_MIB:
            return 2
    return 1


def command_environment():
    env = environment(build=True)
    for key in ("OURO_C_BUILD_DIR", "OURO1_COMPILER"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def run_checks(files: list[str], out: Path, jobs: int) -> dict:
    started = time.perf_counter()
    out.mkdir(parents=True, exist_ok=True)
    jobs = pool_jobs(jobs, len(files) - 1)
    env, sh = command_environment(), shell().as_posix()
    worker_env = {**env, JOBS_ENV: "1", "OURO_JOBS": "1", "OURO_FRONTEND_JOBS": "1"}
    memory = 3072 if os.name == "nt" else POSIX_WORKER_MEMORY_MIB

    def check(item, *, child_env=env):
        index, path = item
        argv = [sh, "scripts/ouro1.sh", "check", path, "200000"]
        result = run_limited(argv, cwd=ROOT, env=child_env, timeout_s=300, memory_mb=memory)
        status = "PASS" if result.ok else "TIMEOUT" if result.status == "timeout" else "FAIL"
        log = out / f"{index:02}-{Path(path).stem}.log"
        row = {"file": path, "command": argv, "status": status,
               "exit_code": result.returncode, "resource": result.classify(),
               "seconds": round(result.elapsed_s, 3), "peak_mb": round(result.peak_rss_mb, 3),
               "log": log.as_posix()}
        log.write_text(json.dumps(row) + "\n" + result.stdout + result.stderr, encoding="utf-8")
        return row

    # The wrapper may bootstrap the compiler/collector. Finish that first;
    # subsequent check invocations only read them and own their output logs.
    rows = [check((0, files[0]))]
    if rows[0]["status"] == "PASS":
        if os.name != "nt" and jobs > 1:
            c_build = ROOT / env.get("OURO_C_BUILD_DIR", "_build/c")
            compiler = ROOT / env.get("OURO1_COMPILER", c_build / "ouro1")
            collector = c_build / "ouro-collect"
            if compiler.is_file() and collector.is_file():
                worker_env.update(OURO1_COMPILER=compiler.as_posix(), OURO_PREPARED_COLLECTOR=collector.as_posix())
            else:
                jobs = 1
        items = list(enumerate(files[1:], 1))
        exclusive = (ROOT / "tools/analyze/drive_main.ouro").resolve()
        # The complete analyzer/frontend closure needs dedicated CPU time.
        solo = [item for item in items if (os.name == "nt" or jobs > 1) and Path(item[1]).resolve() == exclusive]
        pooled = [item for item in items if item not in solo]
        completed = {0: rows[0]}
        for item in solo:
            completed[item[0]] = check(item)
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            for item, row in zip(pooled, pool.map(lambda item: check(item, child_env=worker_env), pooled), strict=True):
                completed[item[0]] = row
        rows = [completed[index] for index in range(len(files))]
    passed = len(rows) == len(files) and all(row["status"] == "PASS" for row in rows)
    report = {"kind": "ouro.analyzer-core-checks.v1", "pass": passed,
              "jobs": jobs, "requested_checks": len(files), "wrapper_launches": len(rows),
              "seconds": round(time.perf_counter() - started, 3), "checks": rows}
    write_json_atomic(out / "report.json", report)
    for row in rows:
        print(f"ANALYZE_CORE {row['status']} {row['file']} exit={row['exit_code']} log={row['log']}", flush=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("files", nargs="+")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    jobs = pool_jobs(job_count(), len(args.files) - 1)
    if args.worker:
        return int(not run_checks(args.files, out, jobs)["pass"])
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / "report.json"
    report_path.unlink(missing_ok=True)
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--out", out.as_posix(), *args.files]
    memory = 3072 if os.name == "nt" else POOL_CONTROLLER_MEMORY_MIB + jobs * POSIX_WORKER_MEMORY_MIB
    result = run_limited(command, cwd=ROOT, env=command_environment(), timeout_s=1800, memory_mb=memory)
    (out / "pool.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    print(result.stdout + result.stderr, end="")
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {"pass": False}
    report.update({"pool_resource": result.classify(), "pool_exit_code": result.returncode,
                   "pool_seconds": round(result.elapsed_s, 3), "pool_peak_mb": round(result.peak_rss_mb, 3)})
    report["pass"] = report["pass"] and result.ok
    write_json_atomic(report_path, report)
    print(f"ANALYZE_CORE_POOL {'PASS' if report['pass'] else 'FAIL'} jobs={report.get('jobs', jobs)} "
          f"launched={report.get('wrapper_launches', 0)} seconds={result.elapsed_s:.3f} peak_mb={result.peak_rss_mb:.3f}")
    return int(not report["pass"])


if __name__ == "__main__":
    raise SystemExit(main())
