#!/usr/bin/env python3
"""Checked transport for native Ouro quality executables.

Rewrites, recognition and selection belong to tools/fix and tools/quality.
This module only prepares the native executables and validates their wire
protocols for the remaining Python owners and suites.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple, Sequence

ROOT = Path(__file__).resolve().parents[1]


def prepare_native_fix() -> Path:
    """Validate/build the existing native entry; no quality fallback exists."""
    from ourosmith.host import prepare_entry

    return prepare_entry("tools/fix/main.ouro", "ouro-fix")


class NativeLiteralFacts(NamedTuple):
    spans: list[tuple[int, int]]
    closed_lines: set[int]


def validate_literal_report(report: object, text: str) -> NativeLiteralFacts:
    """Validate the closed numeric wire schema and convert byte locations."""
    raw = text.encode("utf-8")
    fields = {"kind", "input_bytes", "spans", "closed_lines", "complete"}
    if (not isinstance(report, dict) or set(report) != fields
            or report["kind"] != "ouro.fix-literal-spans.v2" or report["complete"] is not True
            or type(report["input_bytes"]) is not int or report["input_bytes"] != len(raw)
            or not isinstance(report["spans"], list) or not isinstance(report["closed_lines"], list)):
        raise ValueError("invalid or incomplete native literal report")
    spans = []
    previous = 0
    for span in report["spans"]:
        if (not isinstance(span, list) or len(span) != 2 or any(type(n) is not int for n in span)
                or not previous <= span[0] < span[1] <= len(raw)):
            raise ValueError("invalid, overlapping or unordered native literal span")
        start, end = span
        # A range ending inside a UTF-8 character is a damaged report, never a
        # replacement character or a guessed source position.
        spans.append((len(raw[:start].decode("utf-8")), len(raw[:end].decode("utf-8"))))
        previous = end
    lines = report["closed_lines"]
    if (any(type(n) is not int or not 1 <= n <= text.count("\n") + 1 for n in lines)
            or lines != sorted(set(lines))):
        raise ValueError("invalid, duplicated or unordered native literal lines")
    return NativeLiteralFacts(spans, set(lines))


def native_literal_facts(text: str, binary: Path) -> NativeLiteralFacts:
    from ourosmith.limits import run_limited

    result = run_limited(
        [str(binary), "--literal-spans", str(len(text.encode("utf-8")))],
        cwd=ROOT, timeout_s=120, memory_mb=3072, stdin_text=text,
    )
    if not result.ok or result.stderr:
        raise ValueError(f"native literal worker failed status={result.status} exit={result.returncode}: "
                         + result.stderr)
    return validate_literal_report(json.loads(result.stdout, object_pairs_hook=native_report_fields), text)


def native_report_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    fields: dict[str, object] = {}
    for key, value in pairs:
        if key in fields:
            raise ValueError("duplicated native quality report field: " + key)
        fields[key] = value
    return fields


def native_quality_inventory(mode: str, scopes: Sequence[str], include_fixtures: bool) -> list[Path]:
    """Checked transport only: selection and exclusions belong to Ouro."""
    from ourosmith.host import prepare_entry
    from ourosmith.limits import run_limited

    executable = prepare_entry("tools/quality/inventory.ouro", "ouro-quality-inputs")
    # Do not resolve before invoking the owner: that would hide symlink roots.
    requested = [str(ROOT / scope) for scope in scopes]
    result = run_limited(
        [str(executable), mode, "include" if include_fixtures else "exclude", str(ROOT), *requested],
        cwd=ROOT, timeout_s=120, memory_mb=3072,
    )
    if not result.ok or result.stderr:
        raise ValueError(f"native quality inventory failed status={result.status} exit={result.returncode}: "
                         + result.stderr)
    report = json.loads(result.stdout, object_pairs_hook=native_report_fields)
    fields = {"kind", "mode", "include_fixtures", "root", "scopes", "files", "complete"}
    if (not isinstance(report, dict) or set(report) != fields or report["kind"] != "ouro.quality-inputs.v1"
            or report["mode"] != mode or report["include_fixtures"] is not include_fixtures
            or report["root"] != ROOT.as_posix() or report["scopes"] != requested
            or report["complete"] is not True or not isinstance(report["files"], list)
            or not report["files"] or any(not isinstance(path, str) for path in report["files"])):
        raise ValueError("invalid or incomplete native quality inventory")
    files = report["files"]
    if files != sorted(set(files)):
        raise ValueError("duplicated or unordered native quality inventory")
    paths = [Path(path) for path in files]
    roots = [Path(path).resolve() for path in requested]
    if any(not path.is_absolute() or path.suffix != ".ouro" or not path.is_relative_to(ROOT)
           or path.is_symlink() or not path.is_file() or path.resolve().as_posix() != path.as_posix()
           or not any(path == scope or path.is_relative_to(scope) for scope in roots) for path in paths):
        raise ValueError("unsafe or missing native quality inventory file")
    return paths
