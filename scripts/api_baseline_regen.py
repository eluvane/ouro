#!/usr/bin/env python3
"""Regenerate or verify the analyzer public-API baseline from ``std/`` source.

The analyzer baseline stores ``path<TAB>name<TAB>fnv1a64(signature)`` plus
maintainer-owned namespace/use-intent metadata. Generated hashes are refreshed;
metadata and synthesized rows are preserved.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Optional, Sequence

from repo_support import bind_relative_path, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
rel = bind_relative_path(ROOT)
BASELINE = ROOT / "quality" / "api_surface.tsv"
BASELINE_FRAGMENT_DIR = BASELINE.parent / "api_surface"
REPORT_KIND = "ouro.api-baseline.v1"
HEADER = "# Ouro public API baseline v2. Columns: path<TAB>name<TAB>fnv1a64(sig)<TAB>namespace<TAB>use-intent"
DEF_RE = re.compile(r"^[ \t]*(def|axiom)[ \t]+([A-Za-z0-9_]+)")


def hash_text(text: str) -> int:
    value = 1469598103934665603
    for byte in text.encode("utf-8", "surrogateescape"):
        value ^= byte
        value = (value * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return value


def normalize_signature(line: str) -> str:
    line = line.lstrip(" \t")
    assignment = line.find(":=")
    if assignment >= 0:
        line = line[:assignment]
    comment = line.find("--")
    if comment >= 0:
        line = line[:comment]
    return " ".join(line.split())


def std_sources() -> list[Path]:
    return sorted((path for path in (ROOT / "std").rglob("*.ouro") if path.is_file()), key=lambda path: path.relative_to(ROOT).as_posix())


def baseline_paths() -> list[Path]:
    paths = [BASELINE]
    if BASELINE_FRAGMENT_DIR.is_dir():
        paths.extend(sorted(path for path in BASELINE_FRAGMENT_DIR.glob("*.tsv") if path.is_file()))
    return paths


def read_combined_baseline() -> str:
    lines = [HEADER]
    seen: set[tuple[str, str]] = set()
    for path in baseline_paths():
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            if raw.startswith("#") or not raw.strip():
                continue
            columns = raw.split("\t")
            if len(columns) < 2:
                continue
            key = (columns[0], columns[1])
            if key in seen:
                continue
            seen.add(key)
            lines.append(raw)
    return "\n".join(lines) + "\n"


def rows_for(path: Path) -> list[tuple[str, str, str, str]]:
    relative = path.relative_to(ROOT).as_posix()
    rows: list[tuple[str, str, str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = DEF_RE.match(line)
        if not match or match.group(1) == "axiom":
            continue
        signature = normalize_signature(line)
        rows.append((relative, match.group(2), f"{hash_text(signature):x}", signature))
    return rows


def existing_rows() -> list[tuple[str, str, str]]:
    if not BASELINE.is_file():
        return []
    rows: list[tuple[str, str, str]] = []
    for line in read_combined_baseline().splitlines():
        if line.startswith("#"):
            continue
        columns = line.split("\t")
        if len(columns) >= 3:
            rows.append((columns[0], columns[1], line))
    return rows


def render_baseline() -> tuple[str, int, int]:
    sources = std_sources()
    generated: dict[tuple[str, str], tuple[str, str, str, str]] = {}
    order: list[tuple[str, str]] = []
    for source in sources:
        for row in rows_for(source):
            key = (row[0], row[1])
            generated[key] = row
            order.append(key)

    existing = existing_rows()
    metadata: dict[tuple[str, str], tuple[str, str]] = {}
    for path, name, raw in existing:
        columns = raw.split("\t")
        if len(columns) >= 5:
            metadata[(path, name)] = (columns[3], columns[4].split("#", 1)[0].strip())

    def render(key: tuple[str, str]) -> str:
        path, name, digest, signature = generated[key]
        namespace, intent = metadata.get(key, ("std", "public"))
        return f"{path}\t{name}\t{digest}\t{namespace or 'std'}\t{intent or 'public'}\t# {signature}"

    lines = [HEADER]
    emitted: set[tuple[str, str]] = set()
    source_names = {path.relative_to(ROOT).as_posix() for path in sources}
    for path, name, raw in existing:
        key = (path, name)
        if key in generated:
            lines.append(render(key))
            emitted.add(key)
        elif path in source_names:
            # Keep frontend-synthesized rows (for example generated record accessors).
            lines.append(raw)
    for key in order:
        if key not in emitted:
            lines.append(render(key))
    return "\n".join(lines) + "\n", len(lines) - 1, len(sources)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail instead of updating when the baseline drifts")
    parser.add_argument("--report", default="_build/api_baseline/api-baseline.json")
    args = parser.parse_args(argv)

    if not BASELINE.is_file():
        raise SystemExit(f"API_BASELINE: missing {BASELINE.relative_to(ROOT).as_posix()}")
    rendered, rows, source_count = render_baseline()
    # Fragments are maintainer inputs; the analyzer loads only the generated
    # aggregate, so check that file itself rather than a virtual merged view.
    current = BASELINE.read_text(encoding="utf-8")
    drift = rendered != current
    wrote = False
    if drift and not args.check:
        BASELINE.write_text(rendered, encoding="utf-8", newline="\n")
        wrote = True
        drift = False

    report_path = Path(args.report)
    if not report_path.is_absolute():
        report_path = ROOT / report_path
    report = {
        "kind": REPORT_KIND,
        "pass": not drift,
        "check_only": args.check,
        "baseline": BASELINE.relative_to(ROOT).as_posix(),
        "baseline_fragments": [path.relative_to(ROOT).as_posix() for path in baseline_paths()[1:]],
        "rows": rows,
        "std_sources": source_count,
        "drift": drift,
        "wrote": wrote,
    }
    write_json_atomic(report_path, report)
    if drift:
        print(f"API_BASELINE: DRIFT rows={rows} sources={source_count} report={rel(report_path)}")
        return 1
    state = "WROTE" if wrote else "OK unchanged"
    print(f"API_BASELINE: {state} rows={rows} sources={source_count} report={rel(report_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
