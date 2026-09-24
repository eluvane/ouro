#!/usr/bin/env python3
"""Fail-closed strict-quality firewall for Ouro source.

Native owner: tools/strict/main.ouro. This launcher keeps the import surface
used by scripts/syntax_quality_suite.py and the --structural Python path.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from repo_support import bind_relative_path, read_json_value

ROOT = Path(__file__).resolve().parents[1]
rel = bind_relative_path(ROOT, resolve=True)
CONFIG = ROOT / "quality" / "diagnostics.json"
LEVEL_ORDER = {"allow": 0, "warn": 1, "deny": 2, "forbid": 3}


@dataclass(frozen=True)
class Finding:
    code: str
    level: str
    path: str
    line: int
    column: int
    message: str
    replacement: str
    analyzer: str = "quality"
    rule: str = "strict-quality"
    witness: str = ""
    allowed_by_debt: Optional[str] = None

    @property
    def blocking(self) -> bool:
        return LEVEL_ORDER[self.level] >= LEVEL_ORDER["deny"] and self.allowed_by_debt is None


def read_json(path: Path) -> Any:
    data, error = read_json_value(path)
    if error is not None:
        raise ValueError(f"unreadable JSON {rel(path)}: {error}")
    return data


def read_json_object(path: Path) -> dict[str, Any]:
    data = read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"{rel(path)} is not a JSON object")
    return data


def load_registry() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    cfg = read_json_object(CONFIG)
    diagnostics = cfg.get("diagnostics", [])
    if not isinstance(diagnostics, list):
        raise ValueError(f"{rel(CONFIG)} diagnostics is not an array")
    reg: dict[str, dict[str, Any]] = {}
    for item in diagnostics:
        if not isinstance(item, dict):
            raise ValueError(f"{rel(CONFIG)} diagnostics contains a non-object entry")
        code = item.get("code")
        if isinstance(code, str):
            reg[code] = item
    return cfg, reg


def native_env() -> dict[str, str]:
    env = dict(os.environ)
    env["OURO_ROOT"] = ROOT.as_posix()
    env["OURO_REPRODUCIBLE"] = "1"
    return env


def _strict_binary() -> Path:
    from ourosmith.host import prepare_entry

    return prepare_entry("tools/strict/main.ouro", "ouro-strict-quality-firewall")


def _finding_from_json(item: dict[str, Any]) -> Finding:
    mark = item.get("allowed_by_debt")
    return Finding(
        code=str(item.get("code") or ""),
        level=str(item.get("level") or "deny"),
        path=str(item.get("path") or ""),
        line=max(1, int(item.get("line") or 1)),
        column=max(1, int(item.get("column") or 1)),
        message=str(item.get("message") or ""),
        replacement=str(item.get("replacement") or "Apply the documented replacement."),
        analyzer=str(item.get("analyzer") or "quality"),
        rule=str(item.get("rule") or "strict-quality"),
        witness=str(item.get("witness") or ""),
        allowed_by_debt=None if mark in (None, "") else str(mark),
    )


def scan_source(path: Path, text: str, registry: dict[str, dict[str, Any]], profile: str,
                native_fix: Path | None = None) -> list[Finding]:
    del registry, native_fix
    from ourosmith.limits import run_limited

    result = run_limited(
        [str(_strict_binary()), "--scan-source", str(path), "--profile", profile],
        cwd=ROOT, env=native_env(), timeout_s=1800, memory_mb=3072, stdin_text=text,
    )
    if not result.ok:
        raise ValueError(
            f"native strict scan failed status={result.status} exit={result.returncode}: "
            + result.stderr
        )
    payload = json.loads(result.stdout)
    if not isinstance(payload, list):
        raise ValueError("native strict scan did not return a JSON array")
    return [_finding_from_json(item) for item in payload if isinstance(item, dict)]


def main(argv: Optional[Sequence[str]] = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if "--structural" in raw:
        ap = argparse.ArgumentParser(description=__doc__)
        ap.add_argument("--structural", action="store_true")
        ap.add_argument("--profile", default="project")
        ap.add_argument("--scope", action="append", default=None)
        ap.add_argument("--include-fixtures", action="store_true")
        ap.add_argument("--skip-fixture-check", action="store_true")
        ap.add_argument("--report", default="_build/quality/strict-quality-firewall.json")
        ap.add_argument("--sarif", default="_build/quality/strict-quality-firewall.sarif")
        ap.add_argument("--migration-report", default="_build/quality/migration-report.md")
        ap.add_argument("--list-diagnostics", action="store_true")
        args = ap.parse_args(raw)
        from structural_quality import run
        if args.scope or args.include_fixtures or args.skip_fixture_check or args.list_diagnostics:
            ap.error("--structural requires the complete repository inventory")
        report = Path(args.report)
        if args.report == "_build/quality/strict-quality-firewall.json":
            report = Path("_build/quality/structural-quality.json")
        return run(ROOT, report if report.is_absolute() else ROOT / report)

    from ourosmith.limits import run_limited

    result = run_limited(
        [str(_strict_binary()), *raw],
        cwd=ROOT, env=native_env(), timeout_s=1800, memory_mb=3072,
    )
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode is None:
        return 1
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
