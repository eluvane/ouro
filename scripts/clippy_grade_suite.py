#!/usr/bin/env python3
"""Manifest-driven fixture and exit-status suite for the Clippy-grade firewall."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional, Sequence

from repo_support import bind_relative_path, read_json_value

ROOT = Path(__file__).resolve().parents[1]
rel = bind_relative_path(ROOT, resolve=True)
MANIFEST = ROOT / "quality" / "fixtures" / "clippy_grade" / "manifest.json"
FIREWALL = ROOT / "scripts" / "clippy_grade_firewall.py"


def materialize_fixtures(manifest: dict[str, Any], work: Path) -> tuple[Path, Path, dict[str, set[str]]]:
    if work.exists():
        shutil.rmtree(work)
    bad_root = work / "bad"
    good_root = work / "good"
    bad_root.mkdir(parents=True, exist_ok=True)
    good_root.mkdir(parents=True, exist_ok=True)
    expected: dict[str, set[str]] = {}
    for item in manifest.get("bad", []):
        path = bad_root / item["name"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(item["content"]), encoding="utf-8")
        expected[rel(path)] = set(map(str, item.get("codes", [])))
    for item in manifest.get("good", []):
        path = good_root / item["name"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(item["content"]), encoding="utf-8")
    return bad_root, good_root, expected


def run_firewall(scope: Path, report: Path, *, profile: str = "strict", warn_only: bool = False) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(FIREWALL),
        "--profile",
        profile,
        "--include-fixtures",
        "--scope",
        rel(scope),
        "--report",
        rel(report),
        "--sarif",
        rel(report.with_suffix(".sarif")),
    ]
    if warn_only:
        cmd.append("--warn-only")
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)


def load_report(report: Path) -> dict[str, Any]:
    data, error = read_json_value(report)
    if error is not None:
        raise ValueError(f"unreadable clippy-grade report {rel(report)}: {error}")
    if not isinstance(data, dict):
        raise ValueError(f"clippy-grade report {rel(report)} is not a JSON object")
    return data


def load_manifest(path: Path) -> dict[str, Any]:
    data, error = read_json_value(path)
    if error is not None:
        raise ValueError(f"unreadable clippy-grade manifest {rel(path)}: {error}")
    if not isinstance(data, dict):
        raise ValueError(f"clippy-grade manifest {rel(path)} is not a JSON object")
    return data


def codes_by_path(report: Path) -> dict[str, set[str]]:
    data = load_report(report)
    findings = data.get("findings", [])
    if not isinstance(findings, list):
        raise ValueError(f"clippy-grade report {rel(report)} findings is not an array")
    out: dict[str, set[str]] = defaultdict(set)
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError(f"clippy-grade report {rel(report)} has a non-object finding")
        if finding.get("suppressed_by"):
            continue
        out[str(finding.get("path", ""))].add(str(finding.get("rule_id", "")))
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="_build/quality/clippy-grade-suite")
    args = ap.parse_args(argv)

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.mkdir(parents=True, exist_ok=True)

    try:
        manifest = load_manifest(MANIFEST)
    except ValueError as exc:
        print(f"CLIPPY_GRADE_SUITE: FAIL {exc}", file=sys.stderr)
        return 1
    bad_root, good_root, expected_bad = materialize_fixtures(manifest, out / "fixtures")
    failures: list[str] = []

    validate = subprocess.run([sys.executable, str(FIREWALL), "--validate-rules"], cwd=ROOT, text=True, capture_output=True, check=False)
    (out / "validate.stdout").write_text(validate.stdout, encoding="utf-8")
    (out / "validate.stderr").write_text(validate.stderr, encoding="utf-8")
    if validate.returncode != 0:
        failures.append("rule inventory validation failed")

    bad_report = out / "bad.json"
    bad_proc = run_firewall(bad_root, bad_report)
    (out / "bad.stdout").write_text(bad_proc.stdout, encoding="utf-8")
    (out / "bad.stderr").write_text(bad_proc.stderr, encoding="utf-8")
    if bad_proc.returncode == 0:
        failures.append("bad fixture directory unexpectedly passed")
    try:
        found_bad = codes_by_path(bad_report) if bad_report.is_file() else {}
    except ValueError as exc:
        failures.append(str(exc))
        found_bad = {}
    for path, expected in expected_bad.items():
        found = found_bad.get(path, set())
        missing = sorted(expected - found)
        if missing:
            failures.append(f"bad fixture missing {missing}: {path} found={sorted(found)}")

    good_report = out / "good.json"
    good_proc = run_firewall(good_root, good_report)
    (out / "good.stdout").write_text(good_proc.stdout, encoding="utf-8")
    (out / "good.stderr").write_text(good_proc.stderr, encoding="utf-8")
    if good_proc.returncode != 0:
        try:
            good_codes = codes_by_path(good_report) if good_report.is_file() else {}
        except ValueError as exc:
            good_codes = {"unreadable-report": {str(exc)}}
        failures.append(f"good fixture directory produced blocking diagnostics: {good_codes}")

    smoke_bad = next(iter(expected_bad))
    smoke_report = out / "warn_only_smoke.json"
    smoke = run_firewall(ROOT / smoke_bad, smoke_report, profile="strict", warn_only=True)
    (out / "warn_only_smoke.stdout").write_text(smoke.stdout, encoding="utf-8")
    (out / "warn_only_smoke.stderr").write_text(smoke.stderr, encoding="utf-8")
    if smoke.returncode != 0:
        failures.append("--warn-only strict smoke did not return success")

    suite_report = {
        "kind": "ouro.clippy-grade-suite-report.v1",
        "pass": not failures,
        "bad_count": len(manifest.get("bad", [])),
        "good_count": len(manifest.get("good", [])),
        "failures": failures,
    }
    (out / "suite.json").write_text(json.dumps(suite_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for failure in failures:
        print(f"CLIPPY_GRADE_SUITE_FAIL {failure}", file=sys.stderr)
    print(
        f"CLIPPY_GRADE_SUITE: {'OK' if not failures else 'FAIL'} "
        f"bad={suite_report['bad_count']} good={suite_report['good_count']} report={rel(out / 'suite.json')}"
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
