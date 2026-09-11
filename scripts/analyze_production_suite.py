#!/usr/bin/env python3
"""Nightly production sweep of the structured analyzer families.

Runs ouro-analyze-drive over the production scopes named in
quality/analyze_production.json, one bounded native process per file through
scripts/analyze_bounded.py. Two sweeps:

- ``strict``: the strict family set (``--enable-strict``); any finding fails.
- ``all``: every family (``--enable-all``); findings are counted per family
  and per code for triage and never fail the gate on their own.

A source the frontend cannot build a unit for is a rejection. Rejections must
match the policy list exactly: an unlisted rejection fails (new breakage), and a
listed source that parses again fails (stale allowance).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from repo_support import bind_relative_path, read_json_value, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
rel = bind_relative_path(ROOT, resolve=True)
REPORT_KIND = "ouro.analyze-production-report.v1"
POLICY_KIND = "ouro.analyze-production-policy.v1"
DEFAULT_POLICY = ROOT / "quality" / "analyze_production.json"
DRIVE_ENTRY = "tools/analyze/drive_main.ouro"
DRIVE_SOURCE_DIRS = ("tools/analyze",)
FINDING_RE = re.compile(r"^(\S+?):(\d+):(\d+): (warning|error)\[(OURO-[A-Z]+\d+)\] ([a-z_]+)/", re.MULTILINE)
BANNER_RE = re.compile(r"^ANALYZE_DRIVE files=(\d+) findings=(\d+) rejected=(\d+) families=(\S*)", re.MULTILINE)
REJECT_RE = re.compile(r"^(\S+?): structured analyzer could not build the unit: (\S+)", re.MULTILINE)
SWEEPS = {"strict": "--enable-strict", "all": "--enable-all"}
# Rule labels printed as `label/rule` that belong to a drive family under a
# different flag name (drive.ouro fam_metrics covers three rule tables).
FAMILY_OF_LABEL = {"complexity": "metrics", "bounds": "metrics", "minimal": "metrics"}


def fail(message: str) -> int:
    print(f"ANALYZE_PRODUCTION_FAIL {message}", file=sys.stderr)
    return 1


def load_policy(path: Path) -> tuple[dict[str, Any] | None, str]:
    data, error = read_json_value(path)
    if error:
        return None, error
    if not isinstance(data, dict) or data.get("kind") != POLICY_KIND:
        return None, f"expected kind {POLICY_KIND}"
    scopes = data.get("scopes")
    rejects = data.get("frontend_rejects")
    if not isinstance(scopes, list) or not scopes or not all(isinstance(s, str) for s in scopes):
        return None, "scopes must be a non-empty list of paths"
    if not isinstance(rejects, list):
        return None, "frontend_rejects must be a list"
    for entry in rejects:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not isinstance(entry.get("reason"), str):
            return None, "every frontend_rejects entry needs string path and reason"
    return data, ""


def drive_binary() -> Path:
    c_build = Path(os.environ.get("OURO_C_BUILD_DIR", str(ROOT / "_build" / "c")))
    base = c_build / "ouro-analyze-drive"
    exe = base.with_suffix(".exe")
    if exe.is_file() and not base.is_file():
        return exe
    return base


def newest_source_mtime() -> float:
    newest = (ROOT / DRIVE_ENTRY).stat().st_mtime
    for directory in DRIVE_SOURCE_DIRS:
        for path in (ROOT / directory).rglob("*.ouro"):
            if "test" in path.relative_to(ROOT / directory).parts:
                continue
            newest = max(newest, path.stat().st_mtime)
    return newest


def ensure_drive(binary: Path) -> tuple[Path, str]:
    """Build the drive binary the way scripts/ouro1.sh does when it is missing
    or older than a core or its entry."""
    if binary.is_file() and binary.stat().st_mtime >= newest_source_mtime():
        return binary, ""
    env = os.environ.copy()
    env["OURO_BUILD_TOOL_MODE"] = "native"
    target = binary if binary.suffix != ".exe" else binary.with_suffix("")
    proc = subprocess.run(
        ["sh", "scripts/build_tool.sh", DRIVE_ENTRY, str(target)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if proc.returncode != 0:
        tail = "\n".join(proc.stdout.splitlines()[-20:])
        return binary, f"drive build failed rc={proc.returncode}\n{tail}"
    built = drive_binary()
    if not built.is_file():
        return binary, f"drive build produced no binary at {rel(built)}"
    return built, ""


def run_sweep(binary: Path, flag: str, scopes: Sequence[str]) -> tuple[subprocess.CompletedProcess[str], float]:
    cmd = [sys.executable, "scripts/analyze_bounded.py", "--drive", "--bin", str(binary), "--caller", str(ROOT), "--", flag]
    for scope in scopes:
        cmd.extend(("--scope", scope))
    started = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env=os.environ.copy(),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return proc, round(time.perf_counter() - started, 3)


def summarize(stdout: str, stderr: str) -> dict[str, Any] | None:
    banner = BANNER_RE.search(stdout)
    if banner is None:
        return None
    by_family: dict[str, int] = {}
    by_code: dict[str, int] = {}
    for match in FINDING_RE.finditer(stdout):
        code, label = match.group(5), match.group(6)
        family = FAMILY_OF_LABEL.get(label, label)
        by_family[family] = by_family.get(family, 0) + 1
        by_code[code] = by_code.get(code, 0) + 1
    rejects = {path.replace("\\", "/"): reason for path, reason in REJECT_RE.findall(stderr)}
    return {
        "files": int(banner.group(1)),
        "findings": int(banner.group(2)),
        "rejected": int(banner.group(3)),
        "families": [f for f in banner.group(4).split(",") if f],
        "by_family": dict(sorted(by_family.items())),
        "by_code": dict(sorted(by_code.items())),
        "rejections": dict(sorted(rejects.items())),
    }


def check_rejections(observed: dict[str, str], policy: Sequence[dict[str, Any]]) -> list[str]:
    expected = {entry["path"]: entry["reason"] for entry in policy}
    problems: list[str] = []
    for path, reason in sorted(observed.items()):
        if path not in expected:
            problems.append(f"unexpected rejection {path} ({reason}); fix the source or list it in the policy with a reason")
        elif expected[path] != reason:
            problems.append(f"rejection reason drift {path}: policy={expected[path]} observed={reason}")
    for path in sorted(set(expected) - set(observed)):
        problems.append(f"stale allowance {path}: the frontend builds the unit again; remove it from the policy")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="_build/analyze_production")
    ap.add_argument("--policy", default=str(DEFAULT_POLICY))
    ap.add_argument("--strict-only", action="store_true", help="skip the all-family report sweep")
    args = ap.parse_args(argv)

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    policy_path = Path(args.policy)
    if not policy_path.is_absolute():
        policy_path = ROOT / policy_path
    policy, error = load_policy(policy_path)
    if policy is None:
        return fail(f"policy {rel(policy_path)}: {error}")
    scopes = [str(s) for s in policy["scopes"]]
    for scope in scopes:
        if not (ROOT / scope).exists():
            return fail(f"policy scope does not exist: {scope}")

    binary, error = ensure_drive(drive_binary())
    if error:
        return fail(error)

    started = time.perf_counter()
    sweeps: dict[str, Any] = {}
    problems: list[str] = []
    order = ["strict"] if args.strict_only else ["strict", "all"]
    for name in order:
        flag = SWEEPS[name]
        print(f"ANALYZE_PRODUCTION_START sweep={name} flag={flag} scopes={','.join(scopes)}")
        proc, elapsed = run_sweep(binary, flag, scopes)
        (out / f"{name}.out").write_text(proc.stdout, encoding="utf-8", newline="\n")
        (out / f"{name}.err").write_text(proc.stderr, encoding="utf-8", newline="\n")
        summary = summarize(proc.stdout, proc.stderr)
        if summary is None:
            for line in (proc.stdout + proc.stderr).splitlines()[-20:]:
                print(line, file=sys.stderr)
            return fail(f"sweep {name} produced no ANALYZE_DRIVE banner (rc={proc.returncode})")
        summary["returncode"] = proc.returncode
        summary["elapsed_s"] = elapsed
        sweeps[name] = summary
        print(
            f"ANALYZE_PRODUCTION_SWEEP sweep={name} files={summary['files']} "
            f"findings={summary['findings']} rejected={summary['rejected']} elapsed_s={elapsed}"
        )
        gate = "strict" if name == "strict" else "report"
        for family in summary["families"]:
            count = summary["by_family"].get(family, 0)
            print(f"ANALYZE_PRODUCTION_FAMILY sweep={name} family={family} findings={count} gate={gate}")
        for label in sorted(set(summary["by_family"]) - set(summary["families"])):
            problems.append(
                f"sweep {name}: {summary['by_family'][label]} finding(s) labelled {label}/ belong to no "
                "enabled family; extend FAMILY_OF_LABEL in scripts/analyze_production_suite.py"
            )
        if sum(summary["by_family"].values()) != summary["findings"]:
            problems.append(
                f"sweep {name}: banner reports {summary['findings']} findings but "
                f"{sum(summary['by_family'].values())} finding lines were parsed"
            )
        rejection_problems = check_rejections(summary["rejections"], policy["frontend_rejects"])
        for path, reason in summary["rejections"].items():
            status = "known" if not any(path in p for p in rejection_problems) else "unexpected"
            print(f"ANALYZE_PRODUCTION_REJECT sweep={name} path={path} reason={reason} status={status}")
        problems.extend(f"sweep {name}: {p}" for p in rejection_problems)
        if name == "strict" and summary["findings"] != 0:
            for line in proc.stdout.splitlines():
                if FINDING_RE.match(line):
                    print(line)
            problems.append(f"sweep strict: {summary['findings']} finding(s) from the strict family set")

    report = {
        "kind": REPORT_KIND,
        "policy": rel(policy_path),
        "binary": rel(binary),
        "scopes": scopes,
        "sweeps": sweeps,
        "problems": problems,
        "pass": not problems,
        "elapsed_s": round(time.perf_counter() - started, 3),
    }
    report_path = out / "report.json"
    write_json_atomic(report_path, report)
    if problems:
        for problem in problems:
            print(f"ANALYZE_PRODUCTION_PROBLEM {problem}", file=sys.stderr)
        return fail(f"problems={len(problems)} report={rel(report_path)}")
    strict = sweeps["strict"]
    print(
        f"ANALYZE_PRODUCTION_OK files={strict['files']} strict_findings={strict['findings']} "
        f"rejected={strict['rejected']} sweeps={','.join(order)} report={rel(report_path)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
