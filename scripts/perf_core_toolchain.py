#!/usr/bin/env python3
"""Measure Ouro core toolchain latency for small developer commands.

The report is intentionally evidence, not a trusted cache. A missing command is
recorded as unavailable rather than success, and optional baseline comparison
emits conservative regression warnings instead of relying on machine-specific
absolute timing.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from repo_support import read_json_value

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "_build" / "perf" / "core-toolchain-current.json"

BASE_COMMANDS: list[tuple[str, list[str]]] = [
    ("ouro-binary-help", ["sh", "-c", "exec ./_build/c/ouro1 --help"]),
    ("ouro1-help", ["sh", "scripts/ouro1.sh", "--help"]),
    ("fmt-check-std-io", ["sh", "scripts/ouro1.sh", "fmt", "--check", "std/io.ouro"]),
    ("check-std-io", ["sh", "scripts/ouro1.sh", "check", "std/io.ouro"]),
    ("repo-docs-list", ["sh", "scripts/ouro_repo_gate.sh", "--profile", "docs-native", "--list"]),
    ("repo-project-list", ["sh", "scripts/ouro_repo_gate.sh", "--profile", "project-native", "--list"]),
    ("ci-pr-native-list", ["sh", "scripts/ouro_ci_gate.sh", "--profile", "pr-native", "--list"]),
    ("python-ci-pr-list", [sys.executable, "scripts/ci_gate.py", "--profile", "pr", "--list"]),
]

FULL_COMMANDS: list[tuple[str, list[str]]] = [
    ("ci-pr-run", [sys.executable, "scripts/ci_gate.py", "--profile", "pr", "--out", "_build/ci/pr"]),
    ("native-repo-ci-suite", ["sh", "scripts/ouro_native_repo_ci_suite.sh"]),
]


def command_available(cmd: Sequence[str]) -> tuple[bool, str]:
    exe = cmd[0]
    if "/" in exe or "\\" in exe:
        path = ROOT / exe if not Path(exe).is_absolute() else Path(exe)
        if path.exists():
            return True, ""
        return False, f"missing executable path: {exe}"
    from shutil import which

    if which(exe) is not None:
        return True, ""
    return False, f"missing executable on PATH: {exe}"


def run_once(cmd: Sequence[str], timeout: float) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            list(cmd),
            cwd=ROOT,
            capture_output=True,
            text=False,
            timeout=timeout,
            check=False,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "status": "measured",
            "exit_code": proc.returncode,
            "wall_ms": round(elapsed_ms, 3),
            "stdout_bytes": len(proc.stdout or b""),
            "stderr_bytes": len(proc.stderr or b""),
        }
    except subprocess.TimeoutExpired as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "status": "timeout",
            "exit_code": None,
            "wall_ms": round(elapsed_ms, 3),
            "stdout_bytes": len(exc.stdout or b""),
            "stderr_bytes": len(exc.stderr or b""),
            "reason": f"timeout after {timeout:g}s",
        }
    except OSError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "status": "unavailable",
            "exit_code": None,
            "wall_ms": round(elapsed_ms, 3),
            "stdout_bytes": 0,
            "stderr_bytes": 0,
            "reason": str(exc),
        }


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    measured = [r for r in runs if r.get("status") == "measured"]
    times = [float(r["wall_ms"]) for r in measured]
    if not times:
        first = runs[0] if runs else {"status": "unavailable", "reason": "not run"}
        return {
            "status": first.get("status", "unavailable"),
            "reason": first.get("reason", "no measurements"),
            "median_ms": None,
            "min_ms": None,
            "max_ms": None,
            "exit_codes": [],
            "stdout_bytes_max": 0,
            "stderr_bytes_max": 0,
        }
    return {
        "status": "measured",
        "median_ms": round(statistics.median(times), 3),
        "min_ms": round(min(times), 3),
        "max_ms": round(max(times), 3),
        "exit_codes": [r.get("exit_code") for r in runs],
        "stdout_bytes_max": max(int(r.get("stdout_bytes", 0)) for r in runs),
        "stderr_bytes_max": max(int(r.get("stderr_bytes", 0)) for r in runs),
    }


def measure_command(name: str, cmd: list[str], repeat: int, timeout: float) -> dict[str, Any]:
    available, reason = command_available(cmd)
    if not available:
        runs = [{"status": "unavailable", "reason": reason}]
    else:
        runs = [run_once(cmd, timeout) for _ in range(repeat)]
    summary = summarize_runs(runs)
    return {
        "name": name,
        "command": cmd,
        "repeat": repeat,
        "timeout_s": timeout,
        "cache_note": "as-is working tree/cache state; use a clean checkout for cold numbers",
        "summary": summary,
        "runs": runs,
    }


def load_baseline(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    data, error = read_json_value(path)
    if error is not None:
        raise SystemExit(f"PERF: FAIL cannot read baseline {path}: {error}")
    if not isinstance(data, dict):
        raise SystemExit(f"PERF: FAIL baseline {path} is not a JSON object")
    return data


def compare_to_baseline(current: list[dict[str, Any]], baseline: dict[str, Any] | None) -> list[str]:
    if not baseline:
        return []
    by_name = {item.get("name"): item for item in baseline.get("commands", [])}
    warnings: list[str] = []
    for item in current:
        name = item.get("name")
        old = by_name.get(name)
        if not old:
            continue
        cur_ms = item.get("summary", {}).get("median_ms")
        old_ms = old.get("summary", {}).get("median_ms")
        if not isinstance(cur_ms, (int, float)) or not isinstance(old_ms, (int, float)) or old_ms <= 0:
            continue
        ratio = float(cur_ms) / float(old_ms)
        if ratio > 2.0:
            warnings.append(f"{name}: median {cur_ms:.3f}ms is {ratio:.2f}x baseline {old_ms:.3f}ms")
    return warnings


def env_summary() -> dict[str, Any]:
    keys = [
        "OURO_ROOT",
        "OURO_C_BUILD_DIR",
        "OURO_BUILD_DIR",
        "OURO_CACHE_DIR",
        "OURO_BUILD_TOOL_MODE",
        "OURO_REPRODUCIBLE",
        "OURO_JOBS",
    ]
    return {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "cwd": str(ROOT),
        "env": {k: os.environ.get(k) for k in keys if os.environ.get(k) is not None},
    }


def print_table(commands: list[dict[str, Any]]) -> None:
    print("name                         status        median_ms  min_ms     max_ms     exit_codes")
    print("---------------------------  ------------  ---------  ---------  ---------  ----------")
    for item in commands:
        s = item["summary"]
        def fmt(value: Any) -> str:
            return "-" if value is None else str(value)
        print(
            f"{item['name']:<27}  {s.get('status', '-'):<12}  "
            f"{fmt(s.get('median_ms')):<9}  {fmt(s.get('min_ms')):<9}  "
            f"{fmt(s.get('max_ms')):<9}  {s.get('exit_codes', [])}"
        )


def selected_commands(names: set[str] | None, include_full: bool) -> list[tuple[str, list[str]]]:
    commands = list(BASE_COMMANDS)
    if include_full:
        commands.extend(FULL_COMMANDS)
    if names is None:
        return commands
    return [item for item in commands if item[0] in names]


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repeat", type=int, default=int(os.environ.get("OURO_PERF_REPEAT", "3")))
    ap.add_argument("--timeout", type=float, default=float(os.environ.get("OURO_PERF_TIMEOUT", "120")))
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--baseline", type=Path, default=None)
    ap.add_argument("--command", action="append", default=None, help="measure only this command name; may repeat")
    ap.add_argument("--include-full", action="store_true", default=os.environ.get("OURO_PERF_FULL") == "1")
    ap.add_argument("--fail-on-regression", action="store_true")
    args = ap.parse_args(argv)

    repeat = max(1, args.repeat)
    names = set(args.command) if args.command else None
    measured = [
        measure_command(name, cmd, repeat, args.timeout)
        for name, cmd in selected_commands(names, args.include_full)
    ]
    baseline = load_baseline(args.baseline)
    warnings = compare_to_baseline(measured, baseline)
    report = {
        "kind": "ouro.core-toolchain-perf.v1",
        "generated_at_unix_ns": time.time_ns(),
        "environment": env_summary(),
        "commands": measured,
        "baseline": str(args.baseline) if args.baseline else None,
        "warnings": warnings,
        "policy": {
            "missing_command": "reported as unavailable, never success",
            "comparison": "median greater than 2x baseline is a warning unless --fail-on-regression is set",
            "correctness": "timing runs execute the normal commands; no validation is skipped for measurement",
        },
    }
    out = args.out if args.out.is_absolute() else ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print_table(measured)
    if warnings:
        print("\nregression warnings:")
        for warning in warnings:
            print(f"  - {warning}")
    print(f"\nPERF_REPORT {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    return 1 if warnings and args.fail_on_regression else 0


if __name__ == "__main__":
    raise SystemExit(main())
