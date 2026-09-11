#!/usr/bin/env python3
"""Run analyzer core checks in order-preserving, bounded parallel processes.

Windows bounds up to ten workers with one 3 GiB Job Object. POSIX remains
serial with a 2944 MiB per-process rlimit, leaving controller slack.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ourosmith import ROOT
from ourosmith.host import environment, job_count, shell
from ourosmith.limits import run_limited
from repo_support import write_json_atomic


def command_environment():
    env = environment(build=True)
    for key in ("OURO_C_BUILD_DIR", "OURO1_COMPILER"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def run_checks(files: list[str], out: Path, jobs: int) -> dict:
    started = time.perf_counter()
    out.mkdir(parents=True, exist_ok=True)
    jobs = min(10, max(1, jobs), max(1, len(files) - 1)) if os.name == "nt" else 1
    env, sh = command_environment(), shell().as_posix()
    memory = 3072 if os.name == "nt" else 2944

    def check(item):
        index, path = item
        argv = [sh, "scripts/ouro1.sh", "check", path, "200000"]
        result = run_limited(argv, cwd=ROOT, env=env, timeout_s=300, memory_mb=memory)
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
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            rows.extend(pool.map(check, enumerate(files[1:], 1)))
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
    jobs = min(job_count(), 10) if os.name == "nt" else 1
    if args.worker:
        return int(not run_checks(args.files, out, jobs)["pass"])
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / "report.json"
    report_path.unlink(missing_ok=True)
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--out", out.as_posix(), *args.files]
    result = run_limited(command, cwd=ROOT, env=command_environment(), timeout_s=1800, memory_mb=3072)
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
