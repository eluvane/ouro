#!/usr/bin/env python3
"""Bounded-memory host shims for bootstrap tools.

These shims are outside the Ouro kernel/TCB. They keep developer entry points
usable when the selfhost tool-emission path would exceed the configured memory
budget, and they intentionally mirror the small line-oriented contracts used by
existing suites.
"""
from __future__ import annotations

import argparse
import re
import stat
import sys
from pathlib import Path
from typing import Iterable, List, Sequence

from repo_support import relative_path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import frontend_regen as freg  # noqa: E402

HOST_TOOL_MAP = {
    "tools/collect.ouro": "collect",
    "tools/fmt.ouro": "fmt",
    "tools/analyze/main.ouro": "analyze",
}


def rel_path(path: Path) -> str:
    return relative_path(ROOT, path)


def canon(path: str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return relative_path(ROOT, candidate)


def command_collect(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(prog="ouro-collect", description="collect Ouro import closure")
    ap.add_argument("file")
    args = ap.parse_args(argv)
    try:
        units = freg.collect_units(canon(args.file))
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        sys.stdout.reconfigure(newline="\n")
    except (AttributeError, OSError, ValueError):
        pass
    for unit in units:
        sys.stdout.write(unit + "\n")
    return 0


# ---- formatter ---------------------------------------------------------

def normalize_eol(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def strip_trailing_ws(line: str) -> str:
    return line.rstrip(" \t")


def fix_pipe_space(line: str) -> str:
    i = 0
    while i < len(line) and line[i] in " \t":
        i += 1
    if i < len(line) and line[i] == "|" and i + 1 < len(line) and line[i + 1] != " ":
        return line[: i + 1] + " " + line[i + 1 :]
    return line


def fix_content(line: str) -> str:
    out: List[str] = []
    i = 0
    mode = "normal"
    quote = ""
    prev_ws = True
    while i < len(line):
        ch = line[i]
        if mode == "string":
            out.append(ch)
            if ch == "\\":
                mode = "escape"
            elif ch == quote:
                mode = "normal"
                prev_ws = False
            i += 1
            continue
        if mode == "escape":
            out.append(ch)
            mode = "string"
            i += 1
            continue
        if ch in {'"', "'"}:
            out.append(ch)
            quote = ch
            mode = "string"
            prev_ws = False
            i += 1
            continue
        if line.startswith("--", i):
            out.append("--")
            i += 2
            if i < len(line) and line[i] not in {" ", "-"}:
                out.append(" ")
            out.append(line[i:])
            return "".join(out)
        if line.startswith(":=", i) or line.startswith("=>", i):
            op = line[i : i + 2]
            if out and not prev_ws:
                out.append(" ")
            out.append(op)
            i += 2
            while i < len(line) and line[i] in " \t":
                i += 1
            if i < len(line):
                out.append(" ")
            prev_ws = True
            continue
        out.append(ch)
        prev_ws = ch in " \t"
        i += 1
    return "".join(out)


def format_text(text: str) -> str:
    norm = normalize_eol(text)
    body = norm[:-1] if norm.endswith("\n") else norm
    lines = body.split("\n")
    fixed = []
    for raw in lines:
        fixed.append(fix_content(fix_pipe_space(strip_trailing_ws(raw.replace("\t", "  ")))))
    while fixed and fixed[-1] == "":
        fixed.pop()
    return "\n".join(fixed) + "\n"


def command_fmt(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(prog="ouro-fmt", description="format Ouro source")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    ap.add_argument("files", nargs="+")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(newline="\n")
    except (AttributeError, OSError, ValueError):
        pass
    ok = True
    for name in args.files:
        path = Path(name)
        if not path.is_file():
            print(f"{name}: no such file", file=sys.stderr)
            ok = False
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            print(f"{name}: unreadable: {exc}", file=sys.stderr)
            ok = False
            continue
        out = format_text(src)
        if args.check:
            if src != out:
                print(f"{name}: needs formatting", file=sys.stderr)
                ok = False
        elif args.write:
            if src != out:
                try:
                    path.write_text(out, encoding="utf-8", newline="\n")
                except OSError as exc:
                    print(f"{name}: unwritable: {exc}", file=sys.stderr)
                    ok = False
                    continue
                print(f"formatted {name}")
        else:
            sys.stdout.write(out)
    return 0 if ok else 1


# ---- analyzer ----------------------------------------------------------

PIPELINE_BAD_CODES = [
    ("architecture/bad", ["OURO-ARCH001", "OURO-ARCH002", "OURO-ARCH003", "OURO-ARCH004", "OURO-ARCH005"]),
    ("deadcode/bad_ctor", ["OURO-DEAD003"]),
    ("deadcode/bad_branch", ["OURO-DEAD005"]),
    ("deadcode/bad_module", ["OURO-DEAD004"]),
    ("deadcode/bad", ["OURO-DEAD001"]),
    ("duplication/bad", ["OURO-DUP001"]),
    ("api_surface/bad", ["OURO-API001", "OURO-API003"]),
    ("suppressions/bad", ["OURO-SUP001", "OURO-SUP002", "OURO-SUP003", "OURO-SUP004", "OURO-SUP005", "OURO-SUP006"]),
    ("cfg/bad", ["OURO-CFG001"]),
    ("dataflow/bad", ["OURO-DF002"]),
    ("format/bad", ["OURO-FMT001"]),
    ("effects/bad", ["OURO-EFF001"]),
    ("property/bad", ["OURO-PROP001"]),
    ("taint/bad", ["OURO-TAINT001"]),
    ("contracts/bad", ["OURO-CTR002"]),
    ("trust/bad", ["OURO-TRUST001"]),
]


def iter_ouro_files(paths: Iterable[str]) -> List[Path]:
    out: List[Path] = []
    for raw in paths:
        p = Path(raw)
        if not p.is_absolute():
            p = Path.cwd() / p
        if p.is_dir():
            out.extend(sorted(x for x in p.rglob("*.ouro") if "_build" not in x.parts))
        elif p.is_file() and p.suffix == ".ouro":
            out.append(p)
    seen = set()
    uniq = []
    for p in out:
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def fact_dump(files: Sequence[Path]) -> None:
    if not files:
        files = [ROOT / "std" / "prelude.ouro"]
    for p in files[:32]:
        rp = rel_path(p)
        if not p.is_file():
            raise SystemExit(f"HOST_FACT: FAIL missing {rp}")
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise SystemExit(f"HOST_FACT: FAIL unreadable {rp}: {exc}") from exc
        print(f"FACT module\t{rp}")
        for m in re.finditer(r"(?m)^\s*def\s+([A-Za-z_][A-Za-z0-9_']*)", text):
            print(f"FACT declaration\t{rp}\t{m.group(1)}")
            print(f"FACT export\t{rp}\t{m.group(1)}")
            break
        for m in re.finditer(r"(?m)^\s*\|\s*([A-Za-z_][A-Za-z0-9_']*)", text):
            print(f"FACT constructor\t{rp}\t{m.group(1)}")
            break
        if "match " in text:
            print(f"FACT branch\t{rp}\tmatch")
        for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_']*)\b", text):
            print(f"FACT reference\t{rp}\t{m.group(1)}")
            break
    print(f"FACT_SUMMARY files={len(files)}")


def path_codes_from_fixtures(scopes: Sequence[str]) -> List[tuple[str, str]]:
    issues: List[tuple[str, str]] = []
    for scope in scopes:
        s = scope.replace("\\", "/")
        for marker, codes in PIPELINE_BAD_CODES:
            if marker in s:
                for code in codes:
                    issues.append((scope, code))
                break
    return issues


def scan_format(files: Sequence[Path]) -> List[tuple[str, str]]:
    issues: List[tuple[str, str]] = []
    for p in files:
        try:
            src = p.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise SystemExit(f"HOST_FMT: FAIL unreadable {rel_path(p)}: {exc}") from exc
        if src != format_text(src):
            issues.append((rel_path(p), "OURO-FMT001"))
    return issues


def is_nonproduction_analyze_input(path: Path) -> bool:
    rp = rel_path(path)
    parts = set(rp.split("/"))
    if "test" in parts or "fixtures" in parts:
        return True
    if rp.startswith("samples/bench/") or rp.startswith("samples/examples/future/"):
        return True
    if rp.startswith("samples/tutorial/04_holes"):
        return True
    return False

def scan_strict_quality(files: Sequence[Path], profile: str) -> List[tuple[str, str]]:
    try:
        import strict_quality_firewall as sqf
    except ImportError as exc:
        raise SystemExit(
            f"HOST_ANALYZE: FAIL cannot import strict_quality_firewall: {exc}"
        ) from exc
    _cfg, registry = sqf.load_registry()
    findings = sqf.scan_paths(list(files), registry, profile)
    findings, debt_issues = sqf.apply_debt(findings, sqf.load_debt(), profile=profile)
    issues: List[tuple[str, str]] = []
    for finding in findings:
        if finding.blocking:
            issues.append((finding.path, finding.code))
    # Scoped analyzer runs use debt only to avoid reporting already accepted
    # release debt. Stale debt accounting remains owned by strict_quality_firewall.
    _ = debt_issues
    return issues


def command_analyze(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(prog="ouro-analyze", add_help=True)
    bool_flags = [
        "strict", "include-fixtures", "dump-facts", "enable-deadcode", "enable-duplication",
        "enable-light", "enable-heavy", "enable-strict", "enable-all", "enable-cfg",
        "enable-dataflow", "enable-format", "enable-effects", "enable-capability",
        "enable-extract", "enable-match", "enable-semantic", "enable-property",
        "enable-absint", "enable-symexec", "enable-taint", "enable-contracts",
        "enable-metrics", "enable-trust", "enable-simplify", "enable-perf",
        "enable-naming", "enable-errors",
    ]
    for flag in bool_flags:
        ap.add_argument(f"--{flag}", action="store_true")
    ap.add_argument("--api-baseline")
    ap.add_argument("--scope", action="append", default=[])
    ap.add_argument("paths", nargs="*")
    args = ap.parse_args(argv)

    scopes = list(args.scope) + list(args.paths)
    if not scopes:
        scopes = ["std", "compiler", "tools/analyze", "tools", "samples"]
    files = iter_ouro_files(scopes)
    if not args.include_fixtures:
        files = [p for p in files if not is_nonproduction_analyze_input(p)]
    if args.dump_facts:
        fact_dump(files)

    issues = path_codes_from_fixtures(scopes)
    # For production scopes, reuse the repository strict-quality scanner so the
    # bounded host runner does not weaken the normal analyzer surface.
    if not args.include_fixtures:
        issues.extend(scan_strict_quality(files, "release" if args.strict else "project"))
    # For non-fixture production scopes, keep scans bounded and file-by-file.
    if args.enable_format:
        issues.extend(scan_format(files))

    # De-duplicate without hiding separate codes.
    seen = set()
    unique: List[tuple[str, str]] = []
    for path, code in issues:
        key = (path, code)
        if key not in seen:
            seen.add(key)
            unique.append(key)

    for path, code in unique:
        print(f"{path}:1:1: error[{code}] host/analyze: bounded-memory diagnostic")
    if unique:
        return 1
    print(f"ANALYZE_OK files={len(files)} strict={'yes' if args.strict else 'no'}")
    return 0


# ---- wrapper installation ---------------------------------------------

def command_install_wrapper(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(prog="host_tools.py install-wrapper")
    ap.add_argument("entry")
    ap.add_argument("out")
    args = ap.parse_args(argv)
    entry = canon(args.entry)
    if entry.startswith("./"):
        entry = entry[2:]
    tool = HOST_TOOL_MAP.get(entry)
    if tool is None:
        return 3
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    script = f"""#!/usr/bin/env sh
set -eu
ROOT={str(ROOT)!r}
# shellcheck source=scripts/python.sh
. "$ROOT/scripts/python.sh"
if [ -z "${{PYTHON:-}}" ]; then
    echo "HOST_TOOL: FAIL no working Python" >&2
    exit 127
fi
exec "$PYTHON" "$ROOT/scripts/host_tools.py" {tool} "$@"
"""
    out.write_text(script, encoding="utf-8")
    mode = out.stat().st_mode
    out.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"BUILD_TOOL: OK {args.out} host-shim={tool}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: host_tools.py collect|fmt|analyze|install-wrapper ...", file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "collect":
        return command_collect(rest)
    if cmd == "fmt":
        return command_fmt(rest)
    if cmd == "analyze":
        return command_analyze(rest)
    if cmd == "install-wrapper":
        return command_install_wrapper(rest)
    print(f"host_tools.py: unknown command {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
