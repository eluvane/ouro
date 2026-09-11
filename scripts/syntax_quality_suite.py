#!/usr/bin/env python3
"""Focused syntax-quality firewall and canonical-fixer suite."""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from repo_support import bind_relative_path, read_json_value, write_json_atomic
from ourosmith.surface.text_contracts import syntax_cases
import strict_quality_firewall as strict_quality

ROOT = Path(__file__).resolve().parents[1]
rel = bind_relative_path(ROOT, resolve=True)
OUT = ROOT / "_build" / "syntax_quality_suite"
EXPECTED_SYNTAX_CODES = {
    "OURO-LINT037",
    "OURO-LINT038",
    "OURO-LINT039",
    "OURO-LINT040",
    "OURO-LINT041",
    "OURO-LINT042",
    "OURO-LINT043",
    "OURO-LINT044",
}


@dataclass
class Check:
    name: str
    status: str
    detail: str


def run(cmd: Sequence[str], *, expect: int | None = 0, stdout: Path | None = None) -> subprocess.CompletedProcess[str]:
    if stdout is not None:
        stdout.parent.mkdir(parents=True, exist_ok=True)
        with stdout.open("w", encoding="utf-8") as f:
            proc = subprocess.run(cmd, cwd=ROOT, text=True, stdout=f, stderr=subprocess.STDOUT)
    else:
        proc = subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if expect is not None and proc.returncode != expect:
        output = "" if stdout is not None else (proc.stdout or "")
        raise AssertionError(f"{rel(Path(cmd[1])) if len(cmd) > 1 and cmd[1].endswith('.py') else cmd[0]} returned {proc.returncode}, expected {expect}\n{output[-4000:]}")
    return proc


def load_json_object(path: Path) -> dict[str, Any]:
    data, error = read_json_value(path)
    if error is not None:
        raise AssertionError(f"unreadable JSON {rel(path)}: {error}")
    if not isinstance(data, dict):
        raise AssertionError(f"{rel(path)} is not a JSON object")
    return data


def check_rejected_manifest() -> Check:
    path = ROOT / "quality" / "rejected_syntax.json"
    manifest = load_json_object(path)
    diagnostics = load_json_object(ROOT / "quality" / "diagnostics.json").get("diagnostics", [])
    if not isinstance(diagnostics, list):
        raise AssertionError("quality/diagnostics.json diagnostics is not an array")
    registry = {
        item["code"]
        for item in diagnostics
        if isinstance(item, dict) and isinstance(item.get("code"), str)
    }
    codes = {rule["code"] for rule in manifest.get("rules", [])}
    missing = sorted(EXPECTED_SYNTAX_CODES - codes)
    unknown = sorted(codes - registry)
    if missing or unknown:
        raise AssertionError(f"rejected syntax manifest mismatch missing={missing} unknown={unknown}")
    return Check("rejected-syntax-manifest", "pass", f"{len(codes)} rejected forms registered")


def check_fix_cases() -> list[Check]:
    checks: list[Check] = []
    generated = [(seed, case) for seed in (1, 6) for case in syntax_cases(seed)]
    for seed, case in generated:
        inp = OUT / f"{seed}-{case.name}.in"
        golden = inp.with_suffix(".golden")
        inp.write_text(case.source, encoding="utf-8")
        golden.write_text(case.expected, encoding="utf-8")
        out = OUT / (inp.stem + ".out")
        run([sys.executable, "scripts/syntax_quality_fix.py", rel(inp)], stdout=out)
        if out.read_text(encoding="utf-8").splitlines() != golden.read_text(encoding="utf-8").splitlines():
            raise AssertionError(f"fixer output differs from {rel(golden)}")
        twice = OUT / (inp.stem + ".twice")
        run([sys.executable, "scripts/syntax_quality_fix.py", rel(golden)], stdout=twice)
        if twice.read_text(encoding="utf-8").splitlines() != golden.read_text(encoding="utf-8").splitlines():
            raise AssertionError(f"fixer is not idempotent on {rel(golden)}")
        run([sys.executable, "scripts/syntax_quality_fix.py", "--check", rel(golden)])
        run([sys.executable, "scripts/syntax_quality_fix.py", "--check", rel(inp)],
            expect=int(case.source != case.expected))
        checks.append(Check("fixer-" + inp.stem, "pass", f"{rel(inp)} -> {rel(golden)}"))
    return checks


def strict_scan(scope: str, name: str, *, expect_rc: int, include_fixtures: bool = True) -> dict[str, Any]:
    report = OUT / f"{name}.json"
    sarif = OUT / f"{name}.sarif"
    migration = OUT / f"{name}.md"
    cmd = [
        sys.executable,
        "scripts/strict_quality_firewall.py",
        "--profile",
        "release",
        "--scope",
        scope,
        "--skip-fixture-check",
        "--report",
        rel(report),
        "--sarif",
        rel(sarif),
        "--migration-report",
        rel(migration),
    ]
    if include_fixtures:
        cmd.append("--include-fixtures")
    run(cmd, expect=expect_rc, stdout=OUT / f"{name}.log")
    return load_json_object(report)


def check_syntax_fixtures() -> list[Check]:
    _cfg, registry = strict_quality.load_registry()
    bad_path = ROOT / "quality" / "fixtures" / "bad" / "syntax_surface.ouro"
    good_path = ROOT / "quality" / "fixtures" / "good" / "syntax_surface.ouro"
    bad_findings = strict_quality.scan_source(bad_path, bad_path.read_text(encoding="utf-8"), registry, "release")
    good_findings = strict_quality.scan_source(good_path, good_path.read_text(encoding="utf-8"), registry, "release")
    bad_codes = {finding.code for finding in bad_findings}
    missing = sorted(EXPECTED_SYNTAX_CODES - bad_codes)
    if missing:
        raise AssertionError(f"bad syntax fixture did not emit {missing}")
    if good_findings:
        rendered = [f"{f.code}:{f.line}" for f in good_findings]
        raise AssertionError(f"good syntax fixture emitted findings: {rendered}")
    return [
        Check("bad-syntax-surface", "pass", ", ".join(sorted(bad_codes))),
        Check("good-syntax-surface", "pass", "no findings"),
    ]


def check_release_firewall() -> Check:
    report = OUT / "release.json"
    sarif = OUT / "release.sarif"
    migration = OUT / "release.md"
    run([
        sys.executable,
        "scripts/strict_quality_firewall.py",
        "--profile",
        "release",
        "--report",
        rel(report),
        "--sarif",
        rel(sarif),
        "--migration-report",
        rel(migration),
    ], stdout=OUT / "release.log")
    data = load_json_object(report)
    debt = data.get("diagnostics_debt_allowed")
    blocking = data.get("diagnostics_blocking")
    if debt != 0 or blocking != 0:
        raise AssertionError(f"unexpected release firewall counts debt={debt} blocking={blocking}")
    return Check("release-firewall", "pass", f"debt={debt} blocking={blocking}")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    checks: list[Check] = []
    try:
        checks.append(check_rejected_manifest())
        checks.extend(check_fix_cases())
        checks.extend(check_syntax_fixtures())
        checks.append(check_release_firewall())
    except (AssertionError, OSError, UnicodeError, ValueError) as exc:
        report = {
            "kind": "ouro.syntax-quality-suite-report.v1",
            "pass": False,
            "checks": [c.__dict__ for c in checks],
            "error": str(exc),
        }
        write_json_atomic(OUT / "syntax-quality-firewall.json", report)
        print(f"SYNTAX_QUALITY_SUITE: FAIL {exc}", file=sys.stderr)
        return 1
    report = {
        "kind": "ouro.syntax-quality-suite-report.v1",
        "pass": True,
        "checks": [c.__dict__ for c in checks],
    }
    write_json_atomic(OUT / "syntax-quality-firewall.json", report)
    for c in checks:
        print(f"SYNTAX_QUALITY_CHECK {c.status} {c.name} {c.detail}")
    print(f"SYNTAX_QUALITY_SUITE: PASS report={rel(OUT / 'syntax-quality-firewall.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
