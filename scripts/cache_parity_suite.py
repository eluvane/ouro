#!/usr/bin/env python3
"""Cache-on/cache-off parity gates for non-TCB accelerator paths."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional, Sequence

from repo_support import bind_relative_path, read_json_value, sha256_file, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
rel = bind_relative_path(ROOT, resolve=True)
REPORT_KIND = "ouro.cache-parity-suite.v1"


def run(cmd: list[str], env: dict[str, str], log: Path) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(cmd, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log.write_text(p.stdout, encoding="utf-8")
    print(f"CACHE_PARITY: run {' '.join(cmd)} rc={p.returncode} log={rel(log)}")
    if p.stdout:
        print(p.stdout, end="")
    return p.returncode


def ensure_seed(env: dict[str, str], work: Path) -> list[dict[str, Any]]:
    seed = ROOT / "_build" / "c" / "ouro1"
    if seed.is_file() and os.access(seed, os.X_OK):
        return []
    rc = run(["sh", "scripts/bootstrap.sh"], env, work / "bootstrap.log")
    if rc != 0 or not seed.is_file() or not os.access(seed, os.X_OK):
        return [{"reason": "bootstrap failed or seed missing", "path": rel(seed), "log": rel(work / "bootstrap.log")}]
    return []


def comparable_module_report(report_path: Path) -> list[dict[str, Any]]:
    data, error = read_json_value(report_path)
    if error is not None:
        raise ValueError(f"unreadable module-cache report {report_path}: {error}")
    if not isinstance(data, dict):
        raise ValueError(f"module-cache report {report_path} is not a JSON object")
    modules = data.get("modules", [])
    if not isinstance(modules, list):
        raise ValueError(f"module-cache report {report_path} modules is not an array")
    rows = []
    for m in modules:
        if not isinstance(m, dict):
            raise ValueError(f"module-cache report {report_path} has a non-object module row")
        source = m.get("source")
        rows.append(
            {
                "path": m.get("path"),
                "source_sha256": source.get("sha256") if isinstance(source, dict) else None,
                "imports": m.get("imports", []),
                "decls": m.get("decls", []),
                "direct_key": m.get("direct_key"),
                "closure_key": m.get("closure_key"),
            }
        )
    return sorted(rows, key=lambda x: str(x.get("path")))


def frontend_parity(env: dict[str, str], work: Path, jobs: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seed = ROOT / "_build" / "c" / "ouro1"
    out_cache = work / "frontend-cache-on" / "driver_u.c"
    out_nocache = work / "frontend-cache-off" / "driver_u.c"
    report_cache = work / "frontend-cache-on" / "frontend-regeneration.json"
    report_nocache = work / "frontend-cache-off" / "frontend-regeneration.json"
    cache_root = work / "cache-root"
    commands = [
        ([sys.executable, "scripts/frontend_regen.py", "--ouro1", str(seed), "--out", str(out_cache), "--work", str(work / "frontend-cache-on" / "work"), "--cache-root", str(cache_root), "--report", str(report_cache), "--jobs", str(jobs), "--cache"], work / "frontend-cache-on.log"),
        ([sys.executable, "scripts/frontend_regen.py", "--ouro1", str(seed), "--out", str(out_nocache), "--work", str(work / "frontend-cache-off" / "work"), "--cache-root", str(cache_root), "--report", str(report_nocache), "--jobs", str(jobs), "--no-cache"], work / "frontend-cache-off.log"),
    ]
    for cmd, log in commands:
        rc = run(cmd, env, log)
        if rc != 0:
            issues.append({"reason": "frontend parity command failed", "command": cmd[:2], "log": rel(log)})
    details: dict[str, Any] = {"cache_report": rel(report_cache), "no_cache_report": rel(report_nocache)}
    missing = [rel(path) for path in (out_cache, out_nocache, report_cache, report_nocache) if not path.is_file()]
    if not issues and missing:
        issues.append({"reason": "frontend cache parity artifact missing", "paths": missing})
    if not issues:
        ch = sha256_file(out_cache)
        nh = sha256_file(out_nocache)
        details.update({"cache_sha256": ch, "no_cache_sha256": nh, "bytes": out_cache.stat().st_size})
        if ch != nh or out_cache.read_bytes() != out_nocache.read_bytes():
            issues.append({"reason": "frontend cache-on/cache-off output mismatch", "cache_sha256": ch, "no_cache_sha256": nh})
    return issues, details


def module_cache_parity(env: dict[str, str], work: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seed = ROOT / "_build" / "c" / "ouro1"
    cache_report = work / "module-cache-on" / "selfhost-module-cache.json"
    nocache_report = work / "module-cache-off" / "selfhost-module-cache.json"
    commands = [
        ([sys.executable, "scripts/selfhost_module_cache.py", "--root", "compiler/pipeline.ouro", "--work", str(work / "module-cache-on"), "--cache-root", str(work / "module-cache-root"), "--report", str(cache_report), "--seed", str(seed), "--cache"], work / "module-cache-on.log"),
        ([sys.executable, "scripts/selfhost_module_cache.py", "--root", "compiler/pipeline.ouro", "--work", str(work / "module-cache-off"), "--cache-root", str(work / "module-cache-root"), "--report", str(nocache_report), "--seed", str(seed), "--no-cache"], work / "module-cache-off.log"),
    ]
    for cmd, log in commands:
        rc = run(cmd, env, log)
        if rc != 0:
            issues.append({"reason": "module cache parity command failed", "command": cmd[:2], "log": rel(log)})
    details: dict[str, Any] = {"cache_report": rel(cache_report), "no_cache_report": rel(nocache_report)}
    missing = [rel(path) for path in (cache_report, nocache_report) if not path.is_file()]
    if not issues and missing:
        issues.append({"reason": "module cache parity artifact missing", "paths": missing})
    if not issues:
        try:
            cache_rows = comparable_module_report(cache_report)
            nocache_rows = comparable_module_report(nocache_report)
        except ValueError as exc:
            issues.append({"reason": "unreadable module cache report", "message": str(exc)})
            return issues, details
        details.update({"modules": len(cache_rows), "cache_rows_sha256": __import__("hashlib").sha256(json.dumps(cache_rows, sort_keys=True).encode()).hexdigest(), "no_cache_rows_sha256": __import__("hashlib").sha256(json.dumps(nocache_rows, sort_keys=True).encode()).hexdigest()})
        if cache_rows != nocache_rows:
            issues.append({"reason": "module cache-on/cache-off facts mismatch"})
    return issues, details


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--work", default=os.environ.get("OURO_CACHE_PARITY_WORK", "_build/cache_parity"))
    ap.add_argument("--report", default=None)
    ap.add_argument("--jobs", type=int, default=int(os.environ.get("OURO_JOBS", "10") if str(os.environ.get("OURO_JOBS", "10")).isdigit() else "10"))
    ap.add_argument("--scope", choices=["module", "frontend", "all"], default="all")
    args = ap.parse_args(argv)
    work = Path(args.work)
    if not work.is_absolute():
        work = ROOT / work
    report_path = Path(args.report) if args.report else work / "cache-parity.json"
    if not report_path.is_absolute():
        report_path = ROOT / report_path
    env = os.environ.copy()
    env.setdefault("OURO_ROOT", str(ROOT))
    env.setdefault("OURO_REPRODUCIBLE", "1")
    env.setdefault("OURO_PACK_STRICT", "1")
    work.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    issues = ensure_seed(env, work)
    details: dict[str, Any] = {"scope": args.scope}
    if not issues and args.scope in {"frontend", "all"}:
        fe_issues, fe_details = frontend_parity(env, work, max(1, args.jobs))
        issues.extend(fe_issues)
        details["frontend"] = fe_details
    if not issues and args.scope in {"module", "all"}:
        mod_issues, mod_details = module_cache_parity(env, work)
        issues.extend(mod_issues)
        details["module_cache"] = mod_details

    report = {
        "kind": REPORT_KIND,
        "pass": not issues,
        "issues": issues,
        "details": details,
        "policy": {
            "cache": "cache accelerators may alter timings and hit/miss reports, never accepted outputs or source-derived facts",
            "frontend": "driver_u.c generated with cache on must match cache off byte-for-byte",
            "module_cache": "source/import/declaration/closure facts must match with cache on and off",
        },
        "elapsed_s": round(time.perf_counter() - started, 6),
    }
    write_json_atomic(report_path, report)
    print(f"CACHE_PARITY_SUITE: {'PASS' if not issues else 'FAIL'} issues={len(issues)} report={rel(report_path)}")
    if issues:
        for issue in issues:
            print(f"CACHE_PARITY_ISSUE {issue['reason']}", file=sys.stderr)
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
