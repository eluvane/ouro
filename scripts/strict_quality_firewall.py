#!/usr/bin/env python3
"""Fail-closed strict-quality firewall for Ouro source.

This is a repository-local gate for policy that should not depend on GitHub
settings or external services: diagnostic registry consistency, level/profile
semantics, source suppression discipline, modern-syntax migration debt caps, and
fixture coverage for strict lints.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from repo_support import bind_relative_path, read_json_value, write_json_atomic
from syntax_quality_fix import find_closed_cons_spans

ROOT = Path(__file__).resolve().parents[1]
rel = bind_relative_path(ROOT, resolve=True)
CONFIG = ROOT / "quality" / "diagnostics.json"
DEBT = ROOT / "quality" / "strict_debt_manifest.json"
FIXTURE_MANIFEST = ROOT / "quality" / "fixtures" / "manifest.json"
REPORT_KIND = "ouro.strict-quality-firewall-report.v1"
SARIF_VERSION = "2.1.0"
LEVEL_ORDER = {"allow": 0, "warn": 1, "deny": 2, "forbid": 3}
CODE_RE = re.compile(r"OURO-[A-Z]+[0-9]{3}")
SUPPRESS_RE = re.compile(r"ouro-lint:disable=([^\s]+)")
BROAD_SUPPRESS_RE = re.compile(r"ouro-lint:disable-all|ouro-lint:disable=\*")
DEF_RE = re.compile(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_']*)\b")
TOP_RE = re.compile(r"^\s*(def|inductive|record|axiom|import)\b")
EXPORT_RE = re.compile(r"^\s*(?:--\s*)?(?:@export\b|@api\b|public-api)", re.IGNORECASE)
DOC_TRACE_RE = re.compile(r"@doc\b|@since\b|@spec\b|RFC-|docs/api/|docs/", re.IGNORECASE)
ACCESSOR_RE = re.compile(r"^\s*def\s+([A-Z][A-Za-z0-9]*)_([a-z][A-Za-z0-9_]*)\b.*:=.*\bmatch\b.*\|\s*Mk\1\b")
NIL_LITERAL_RE = re.compile(r":=\s*Nil\s+[A-Za-z_][A-Za-z0-9_']*\s*;?\s*(?:--.*)?$")
TODO_RE = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")
HOLE_RE = re.compile(r":=\s*(?:_|\?[A-Za-z_][A-Za-z0-9_]*)\s*(?:[;)]|$)")
OLD_DO_RE = re.compile(r"\bdo\b[^\n;]*\b([A-Za-z_][A-Za-z0-9_']*)\s*<-")
PANIC_RE = re.compile(r"\b(panic|ICE|assert false)\b", re.IGNORECASE)
WRAPPER_RE = re.compile(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_']*)\b[^:=]*:=\s*([A-Za-z_][A-Za-z0-9_']*)\s*;?\s*(?:--.*)?$")
IMPORT_RE = re.compile(r"^\s*import\s+\"([^\"]+)\"(?:\s+as\s+([A-Za-z_][A-Za-z0-9_']*))?\s*;?\s*$")
TOP_OPEN_RE = re.compile(r"^\s*open\s+([A-Za-z_][A-Za-z0-9_']*)\s*;?\s*$")
DEF_HEAD_RE = re.compile(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_']*)\b")
BINDER_RE = re.compile(r"\(([A-Za-z_][A-Za-z0-9_']*)\s*:")
LET_BIND_RE = re.compile(r"\blet\s+([A-Za-z_][A-Za-z0-9_']*)\b(?:\s*:[^:=]+)?\s*:=")
UNTYPED_LIST_DEF_RE = re.compile(r"^\s*def\s+[A-Za-z_][A-Za-z0-9_']*\b(?:(?!:=).)*:=\s*\[")
UNTYPED_LIST_LET_RE = re.compile(r"\blet\s+[A-Za-z_][A-Za-z0-9_']*\s*:=\s*\[")
PUBLIC_WILDCARD_BRANCH_RE = re.compile(r"\|\s+[A-Z][A-Za-z0-9_']*\b(?=.*\b_\b).*=>")
RESERVED_ALIASES = {"Type", "Nat", "String", "List", "IO", "Unit", "Bool", "True", "False", "Nil", "Cons"}


DEFAULT_SKIP_DIRS = {
    ".git", "_build", "_cache", "node_modules", "dist", "build", ".mypy_cache", ".pytest_cache"
}
FIXTURE_PREFIXES = (
    "quality/fixtures/",
    "tests/analyze/",
    "samples/examples/future/",
    "samples/bench/synthesis/",
)
FIXTURE_INFIXES = ("/bad/",)
FIXTURE_NAME_PREFIXES = ("bad_",)
# Registry fixtures under this prefix belong to the native analyzer suite.
ANALYZER_FIXTURE_PREFIX = "tests/analyze/"
FIXTURE_EXACT = ("samples/tutorial/04_holes.ouro",)
GENERATED_MARKERS = ("compiler/stage0/", "/generated/", ".generated.")


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


def code_prefix(code: str) -> str:
    m = re.match(r"OURO-([A-Z]+)", code)
    return m.group(1) if m else "QUALITY"


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


def profile_level(registry: dict[str, dict[str, Any]], code: str, profile: str) -> str:
    item = registry.get(code)
    if not item:
        return "deny"
    levels = item.get("levels", {})
    level = levels.get(profile, levels.get("project", "warn"))
    if level not in LEVEL_ORDER:
        return "deny"
    return str(level)


def mk_finding(registry: dict[str, dict[str, Any]], profile: str, code: str, path: Path,
               line: int, column: int, message: str, witness: str = "") -> Finding:
    item = registry.get(code, {})
    return Finding(
        code=code,
        level=profile_level(registry, code, profile),
        path=rel(path),
        line=max(1, line),
        column=max(1, column),
        message=message,
        replacement=str(item.get("replacement") or "Apply the documented replacement."),
        analyzer=str(item.get("analyzer") or "quality"),
        rule=str(item.get("rule") or code.lower()),
        witness=witness,
    )


def iter_files(scopes: Sequence[str], *, include_fixtures: bool = False) -> list[Path]:
    out: list[Path] = []
    for scope in scopes:
        root = (ROOT / scope).resolve()
        if not root.exists():
            continue
        if root.is_file():
            candidates = [root]
        else:
            candidates = []
            for p in root.rglob("*"):
                if path_has_skip_dir(p):
                    continue
                if p.is_file() and p.suffix == ".ouro":
                    candidates.append(p)
        for p in candidates:
            r = rel(p)
            if not include_fixtures and is_fixture_like(r):
                continue
            if is_generated_like(r):
                continue
            out.append(p)
    return sorted(set(out), key=rel)


def path_has_skip_dir(path: Path) -> bool:
    for part in path.parts:
        if part in DEFAULT_SKIP_DIRS:
            return True
    return False


def is_fixture_like(path: str) -> bool:
    if path in FIXTURE_EXACT:
        return True
    if path.startswith(FIXTURE_PREFIXES):
        return True
    if any(marker in path for marker in FIXTURE_INFIXES):
        return True
    return Path(path).name.startswith(FIXTURE_NAME_PREFIXES)


def is_generated_like(path: str) -> bool:
    return any(marker in path for marker in GENERATED_MARKERS)


def line_col_of_index(text: str, index: int) -> tuple[int, int]:
    prefix = text[:index]
    line = prefix.count("\n") + 1
    bol = prefix.rfind("\n")
    column = index + 1 if bol < 0 else index - bol
    return line, column


def scan_suppressions(path: Path, text: str, registry: dict[str, dict[str, Any]], profile: str) -> list[Finding]:
    findings: list[Finding] = []
    lines = text.splitlines()
    for i, line in enumerate(lines, start=1):
        if "ouro-lint:disable" not in line:
            continue
        col = line.find("ouro-lint:disable") + 1
        if BROAD_SUPPRESS_RE.search(line):
            findings.append(mk_finding(registry, profile, "OURO-SUP001", path, i, col,
                "blanket diagnostic suppression is forbidden", line.strip()))
        m = SUPPRESS_RE.search(line)
        if not m:
            continue
        code = m.group(1).strip().rstrip(",;)")
        if code not in registry:
            findings.append(mk_finding(registry, profile, "OURO-SUP003", path, i, col,
                f"suppression references unknown diagnostic {code}", code))
        if "reason=" not in line:
            findings.append(mk_finding(registry, profile, "OURO-SUP002", path, i, col,
                f"suppression for {code} has no reason", line.strip()))
        if re.search(r"scope\s*=\s*(file|all|global)", line):
            findings.append(mk_finding(registry, profile, "OURO-SUP006", path, i, col,
                f"suppression for {code} uses too-wide scope", line.strip()))
        if code.startswith("OURO-TRUST") or code == "OURO-ARCH005":
            findings.append(mk_finding(registry, profile, "OURO-SUP005", path, i, col,
                f"{code} is forbid-level and cannot be source-suppressed", code))
    return findings


def scan_public_trace(path: Path, text: str, registry: dict[str, dict[str, Any]], profile: str) -> list[Finding]:
    findings: list[Finding] = []
    lines = text.splitlines()
    for i, line in enumerate(lines, start=1):
        if not EXPORT_RE.search(line):
            continue
        window = "\n".join(lines[max(0, i - 4):min(len(lines), i + 3)])
        if DOC_TRACE_RE.search(window):
            continue
        findings.append(mk_finding(registry, profile, "OURO-LINT035", path, i, 1,
            "public/exported definition lacks nearby docs/spec/RFC trace", line.strip()))
    return findings



def code_before_comment_py(line: str) -> str:
    quote: Optional[str] = None
    esc = False
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                quote = None
            i += 1
            continue
        if ch in {'"', "'"}:
            quote = ch
            i += 1
            continue
        if ch == "-" and i + 1 < len(line) and line[i + 1] == "-":
            return line[:i]
        i += 1
    return line


def is_discard_name(name: str) -> bool:
    return name == "_" or name.startswith("_")


def has_list_expected_type(prefix: str) -> bool:
    return bool(re.search(r":\s*List\b", prefix))


def scan_import_surface(path: Path, lines: list[str], registry: dict[str, dict[str, Any]], profile: str) -> list[Finding]:
    findings: list[Finding] = []
    seen_imports: dict[str, int] = {}
    seen_aliases: dict[str, int] = {}
    for i, raw in enumerate(lines, start=1):
        code = code_before_comment_py(raw).strip()
        if not code:
            continue
        m = IMPORT_RE.match(code)
        if m:
            target = m.group(1)
            alias = m.group(2)
            if target in seen_imports:
                findings.append(mk_finding(registry, profile, "OURO-LINT037", path, i, raw.find("import") + 1,
                    f"duplicate import of {target!r} repeats line {seen_imports[target]}", raw.strip()))
            else:
                seen_imports[target] = i
            if alias:
                col = raw.find(alias) + 1
                if alias in RESERVED_ALIASES or not re.fullmatch(r"[A-Z][A-Za-z0-9_']*", alias):
                    findings.append(mk_finding(registry, profile, "OURO-LINT043", path, i, col,
                        f"import alias {alias!r} is not canonical PascalCase or shadows a built-in name", raw.strip()))
                if alias in seen_aliases:
                    findings.append(mk_finding(registry, profile, "OURO-LINT043", path, i, col,
                        f"import alias {alias!r} repeats earlier alias on line {seen_aliases[alias]}", raw.strip()))
                else:
                    seen_aliases[alias] = i
            continue
        om = TOP_OPEN_RE.match(code)
        if om:
            findings.append(mk_finding(registry, profile, "OURO-LINT044", path, i, raw.find("open") + 1,
                f"top-level open of alias {om.group(1)!r} leaks names across the file", raw.strip()))
    return findings


def def_spans(lines: list[str]) -> list[tuple[int, int]]:
    starts: list[int] = []
    for i, line in enumerate(lines):
        if TOP_RE.match(line):
            starts.append(i)
    spans: list[tuple[int, int]] = []
    for ix, start in enumerate(starts):
        if not DEF_HEAD_RE.match(lines[start]):
            continue
        end = starts[ix + 1] if ix + 1 < len(starts) else len(lines)
        spans.append((start, end))
    return spans




def direct_def_binders(header: str) -> list[str]:
    m = DEF_HEAD_RE.match(header)
    if not m:
        return []
    pos = m.end()
    out: list[str] = []
    while pos < len(header):
        while pos < len(header) and header[pos].isspace():
            pos += 1
        if pos >= len(header) or header[pos] != "(":
            break
        depth = 0
        end = pos
        while end < len(header):
            ch = header[end]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            end += 1
        if end >= len(header):
            break
        inner = header[pos + 1:end].strip()
        bm = re.match(r"([A-Za-z_][A-Za-z0-9_']*)\s*:", inner)
        if bm:
            out.append(bm.group(1))
        pos = end + 1
    return out

def scan_definition_surface(path: Path, lines: list[str], registry: dict[str, dict[str, Any]], profile: str) -> list[Finding]:
    findings: list[Finding] = []
    for start, end in def_spans(lines):
        header_window = " ".join(code_before_comment_py(lines[j]).strip() for j in range(start, min(end, start + 6)))
        header = header_window.split(":=", 1)[0]
        params = [name for name in direct_def_binders(header) if not is_discard_name(name)]
        seen_params: dict[str, int] = {}
        for name in params:
            if name in seen_params:
                findings.append(mk_finding(registry, profile, "OURO-LINT038", path, start + 1, max(1, lines[start].find(name) + 1),
                    f"binder {name!r} shadows an earlier binder in the same definition", lines[start].strip()))
            else:
                seen_params[name] = start + 1

        public_window_lines = lines[max(0, start - 4):start + 1]
        public_def = any(EXPORT_RE.search(line) for line in public_window_lines)
        for line_ix in range(start, end):
            line_locals: set[str] = set()
            raw = lines[line_ix]
            code = code_before_comment_py(raw)
            if ";;" in code:
                findings.append(mk_finding(registry, profile, "OURO-LINT042", path, line_ix + 1, code.find(";;") + 1,
                    "redundant separator `;;` is rejected; one declaration separator is canonical", raw.strip()))
            if ":=" in code:
                before, after = code.split(":=", 1)
                starts_binding = bool(re.search(r"^\s*def\b|\blet\s+[A-Za-z_][A-Za-z0-9_']*\b", before))
                if starts_binding and not has_list_expected_type(before):
                    literal_line_ix = line_ix if after.lstrip().startswith("[") else -1
                    if literal_line_ix < 0 and re.match(r"^\s*def\b", before) and not after.strip():
                        for look_ix in range(line_ix + 1, end):
                            look_code = code_before_comment_py(lines[look_ix]).strip()
                            if not look_code:
                                continue
                            if look_code.startswith("["):
                                literal_line_ix = look_ix
                            break
                    if literal_line_ix >= 0:
                        literal_raw = lines[literal_line_ix]
                        findings.append(mk_finding(registry, profile, "OURO-LINT041", path, literal_line_ix + 1, max(1, literal_raw.find("[") + 1),
                            "list literal has no explicit expected `List` type at the binding boundary", literal_raw.strip()))
            if public_def and PUBLIC_WILDCARD_BRANCH_RE.search(code):
                findings.append(mk_finding(registry, profile, "OURO-LINT040", path, line_ix + 1, PUBLIC_WILDCARD_BRANCH_RE.search(code).start() + 1,
                    "public definition discards constructor payloads with `_` in a branch", raw.strip()))
            for m in LET_BIND_RE.finditer(code):
                name = m.group(1)
                if is_discard_name(name):
                    continue
                if name in seen_params or name in line_locals:
                    findings.append(mk_finding(registry, profile, "OURO-LINT038", path, line_ix + 1, m.start(1) + 1,
                        f"local binding {name!r} shadows an existing binder", raw.strip()))
                line_locals.add(name)
                marker = code.find(" in ", m.end())
                if marker >= 0:
                    body = code[marker + 4:]
                    if not re.search(rf"\b{re.escape(name)}\b", body):
                        findings.append(mk_finding(registry, profile, "OURO-LINT039", path, line_ix + 1, m.start(1) + 1,
                            f"local binding {name!r} is unused and must be removed or renamed to an explicit discard", raw.strip()))
    return findings

def offset_line_col(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    last_nl = text.rfind("\n", 0, offset)
    col = offset - last_nl
    return line, col


def scan_source(path: Path, text: str, registry: dict[str, dict[str, Any]], profile: str) -> list[Finding]:
    findings: list[Finding] = []
    lines = text.splitlines()
    for hit in find_closed_cons_spans(text):
        line_no, col = offset_line_col(text, hit.start)
        witness = lines[line_no - 1].strip() if 0 < line_no <= len(lines) else ""
        findings.append(mk_finding(registry, profile, "OURO-LINT029", path, line_no, col,
            "verbose literal-style list construction is legacy where list literals are available", witness))
    for i, line in enumerate(lines, start=1):
        if TODO_RE.search(line):
            findings.append(mk_finding(registry, profile, "OURO-LINT022", path, i, TODO_RE.search(line).start() + 1,
                "release profile does not allow TODO/FIXME/HACK markers in source", line.strip()))
        if HOLE_RE.search(line):
            findings.append(mk_finding(registry, profile, "OURO-LINT001", path, i, HOLE_RE.search(line).start() + 1,
                "definition body contains a placeholder term hole", line.strip()))
        if ACCESSOR_RE.search(line):
            findings.append(mk_finding(registry, profile, "OURO-LINT028", path, i, ACCESSOR_RE.search(line).start() + 1,
                "manual record accessor boilerplate has a cleaner record/projection replacement", line.strip()))
        if NIL_LITERAL_RE.search(line) and not find_closed_cons_spans(line):
            findings.append(mk_finding(registry, profile, "OURO-LINT029", path, i, NIL_LITERAL_RE.search(line).start() + 1,
                "verbose literal-style list construction is legacy where list literals are available", line.strip()))
        if OLD_DO_RE.search(line):
            findings.append(mk_finding(registry, profile, "OURO-LINT030", path, i, OLD_DO_RE.search(line).start() + 1,
                "legacy do-bind should use let! notation", line.strip()))
        if nested_application_depth(line) >= 3:
            findings.append(mk_finding(registry, profile, "OURO-LINT031", path, i, max(1, line.find(":=") + 1),
                "deep nested application obscures data flow", line.strip()))
        if PANIC_RE.search(line) and not line.lstrip().startswith("--") and not allowed_panic_path(rel(path)):
            findings.append(mk_finding(registry, profile, "OURO-LINT036", path, i, PANIC_RE.search(line).start() + 1,
                "panic/ICE-like text appears outside explicit diagnostic handling", line.strip()))
        m = WRAPPER_RE.search(line)
        if m and m.group(1) != m.group(2) and not line.strip().startswith("--"):
            findings.append(mk_finding(registry, profile, "OURO-LINT032", path, i, 1,
                "definition appears to be a pointless wrapper/alias", line.strip()))
    findings.extend(scan_import_surface(path, lines, registry, profile))
    findings.extend(scan_definition_surface(path, lines, registry, profile))
    findings.extend(scan_suppressions(path, text, registry, profile))
    findings.extend(scan_public_trace(path, text, registry, profile))
    findings.extend(scan_sizes(path, lines, registry, profile))
    return findings


def nested_application_depth(line: str) -> int:
    if ":=" not in line:
        return 0
    body = line.split(":=", 1)[1]
    depth = max_depth = 0
    for ch in body:
        if ch == "(":
            depth += 1
            max_depth = max(max_depth, depth)
        elif ch == ")" and depth:
            depth -= 1
    # Avoid penalizing ordinary constructor type signatures; only expressions with repeated S/f application.
    if max_depth >= 3 and re.search(r"[A-Za-z_][A-Za-z0-9_']*\s*\(", body):
        return max_depth
    return 0


def allowed_panic_path(path: str) -> bool:
    return path.startswith("compiler/lint") or path.startswith("compiler/compile") or "diagnostic" in path


def scan_sizes(path: Path, lines: list[str], registry: dict[str, dict[str, Any]], profile: str) -> list[Finding]:
    findings: list[Finding] = []
    nonblank = sum(1 for ln in lines if ln.strip())
    if nonblank > 800:
        findings.append(mk_finding(registry, profile, "OURO-LINT033", path, 1, 1,
            f"module has {nonblank} nonblank lines", f"nonblank-lines={nonblank}"))
    # crude top-level span metric, deterministic and intentionally conservative.
    starts: list[tuple[int, str]] = []
    for i, line in enumerate(lines, start=1):
        if TOP_RE.match(line):
            starts.append((i, line.strip()))
    for ix, (line_no, first_line) in enumerate(starts):
        if not first_line.startswith("def "):
            continue
        end = starts[ix + 1][0] - 1 if ix + 1 < len(starts) else len(lines)
        span = end - line_no + 1
        if span > 160:
            findings.append(mk_finding(registry, profile, "OURO-LINT034", path, line_no, 1,
                f"definition spans {span} lines", first_line[:160]))
    return findings


def scan_paths(paths: Sequence[Path], registry: dict[str, dict[str, Any]], profile: str) -> list[Finding]:
    out: list[Finding] = []
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise SystemExit(f"STRICT_QUALITY: FAIL unreadable {rel(p)}: {exc}") from exc
        out.extend(scan_source(p, text, registry, profile))
    return sorted(out, key=lambda f: (f.path, f.line, f.column, f.code))


def validate_registry(cfg: dict[str, Any], registry: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    profiles = cfg.get("profiles", [])
    levels = cfg.get("levels", [])
    if profiles != ["baseline", "project", "strict", "compiler", "release"]:
        issues.append({"reason": "quality profiles must be baseline/project/strict/compiler/release", "path": rel(CONFIG)})
    if levels != ["allow", "warn", "deny", "forbid"]:
        issues.append({"reason": "lint levels must be allow/warn/deny/forbid", "path": rel(CONFIG)})
    seen: set[str] = set()
    for item in cfg.get("diagnostics", []):
        code = item.get("code")
        if not isinstance(code, str) or not CODE_RE.fullmatch(code):
            issues.append({"reason": f"invalid diagnostic code {code!r}", "path": rel(CONFIG)})
            continue
        if code in seen:
            issues.append({"reason": f"duplicate diagnostic code {code}", "path": rel(CONFIG)})
        seen.add(code)
        for profile in profiles:
            lvl = item.get("levels", {}).get(profile)
            if lvl not in LEVEL_ORDER:
                issues.append({"reason": f"{code} missing/invalid level for {profile}", "path": rel(CONFIG)})
        if item.get("levels", {}).get("forbid") == "allow":
            issues.append({"reason": f"{code} has malformed forbid level", "path": rel(CONFIG)})
        if any(v == "forbid" for v in item.get("levels", {}).values()) and item.get("suppressible") is True:
            # Forbid diagnostics are globally non-suppressible in this gate.
            if code.startswith("OURO-SUP") or code.startswith("OURO-TRUST") or code == "OURO-ARCH005":
                issues.append({"reason": f"{code} is forbid-level but marked suppressible", "path": rel(CONFIG)})
        for field in ("title", "rationale", "replacement"):
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                issues.append({"reason": f"{code} missing diagnostic metadata {field}", "path": rel(CONFIG)})
        docs = item.get("docs")
        if not isinstance(docs, list) or not docs or not all(isinstance(doc, str) and doc for doc in docs):
            issues.append({"reason": f"{code} missing canonical docs", "path": rel(CONFIG)})
            docs = []
        for doc in docs:
            dp = ROOT / doc
            if not dp.is_file():
                issues.append({"reason": f"{code} references missing doc {doc}", "path": rel(CONFIG)})
    issues.extend(validate_known_codes(registry))
    issues.extend(validate_docs_mentions(registry))
    return issues


def validate_known_codes(registry: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    model = ROOT / "tools" / "analyze" / "model.ouro"
    if model.is_file():
        try:
            model_text = model.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            issues.append({"reason": f"unreadable analyzer model: {exc}", "path": rel(model)})
            return issues
        known = set(CODE_RE.findall(model_text))
        missing = sorted(known - set(registry))
        extra_quality = sorted(c for c in registry if c.startswith("OURO-LINT0") and c not in known)
        for code in missing:
            issues.append({"reason": f"known_codes entry lacks diagnostics registry row: {code}", "path": rel(model)})
        for code in extra_quality:
            issues.append({"reason": f"quality diagnostic not registered in tools/analyze/model.ouro known_codes: {code}", "path": rel(model)})
    return issues


def validate_docs_mentions(registry: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    docs = [ROOT / "docs" / name for name in ("quality.md", "clippy_grade_firewall.md", "stability.md", "syntax.md")]
    texts: list[str] = []
    for p in docs:
        if not p.is_file():
            continue
        try:
            texts.append(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as exc:
            issues.append({"reason": f"unreadable quality doc: {exc}", "path": rel(p)})
    combined = "\n".join(texts)
    canonical_docs = {rel(path) for path in docs}
    required_tokens = ["allow", "warn", "deny", "forbid", "baseline", "project", "strict", "compiler", "release"]
    for token in required_tokens:
        if token not in combined:
            issues.append({"reason": f"quality docs missing token {token}", "path": "docs/quality.md"})
    for code, item in registry.items():
        if LEVEL_ORDER.get(item.get("levels", {}).get("strict", "allow"), 0) >= LEVEL_ORDER["deny"]:
            if not canonical_docs.intersection(item.get("docs", [])):
                issues.append({"reason": f"strict diagnostic {code} lacks canonical quality documentation", "path": rel(CONFIG)})
    return issues


def load_debt() -> dict[str, Any]:
    if not DEBT.is_file():
        return {"kind": "ouro.strict-quality-debt.v1", "entries": []}
    return read_json_object(DEBT)


def apply_debt(findings: list[Finding], debt: dict[str, Any], *, profile: str) -> tuple[list[Finding], list[dict[str, Any]]]:
    entries = debt.get("entries", [])
    usage = [0 for _ in entries]
    issues: list[dict[str, Any]] = []
    out: list[Finding] = []
    for f in findings:
        allowed: Optional[str] = None
        for idx, ent in enumerate(entries):
            if f.code != ent.get("code"):
                continue
            glob = str(ent.get("path_glob", ""))
            if not fnmatch.fnmatch(f.path, glob):
                continue
            if profile not in ent.get("profiles", ["project", "strict", "compiler", "release"]):
                continue
            usage[idx] += 1
            allowed = str(ent.get("id", f"debt[{idx}]"))
            break
        if allowed:
            out.append(Finding(**{**f.__dict__, "allowed_by_debt": allowed}))
        else:
            out.append(f)
    for idx, ent in enumerate(entries):
        actual = usage[idx]
        max_count = ent.get("max_count")
        min_count = ent.get("min_count", max_count)
        eid = ent.get("id", f"debt[{idx}]")
        if max_count is None:
            issues.append({"reason": f"debt entry {eid} lacks max_count", "path": rel(DEBT)})
            continue
        if actual > int(max_count):
            issues.append({"reason": f"debt entry {eid} exceeded cap actual={actual} max={max_count}", "path": rel(DEBT)})
        if min_count is not None and actual < int(min_count):
            issues.append({"reason": f"debt entry {eid} is stale actual={actual} expected={min_count}", "path": rel(DEBT)})
        for key in ("reason", "replacement", "tracking"):
            if not ent.get(key):
                issues.append({"reason": f"debt entry {eid} missing {key}", "path": rel(DEBT)})
    return out, issues


def validate_fixtures(registry: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if not FIXTURE_MANIFEST.is_file():
        return [{"reason": "missing quality fixture manifest", "path": rel(FIXTURE_MANIFEST)}]
    manifest = read_json_object(FIXTURE_MANIFEST)
    issues: list[dict[str, Any]] = []
    for g in manifest.get("good", []):
        path = ROOT / g["path"]
        if not path.is_file():
            issues.append({"reason": "missing good fixture", "path": g["path"]})
            continue
        profile = g.get("profile", "strict")
        found = [f for f in scan_paths([path], registry, profile) if f.blocking]
        if found:
            issues.append({"reason": "good fixture produced blocking strict-quality diagnostics", "path": g["path"], "codes": [f.code for f in found]})
    covered: set[str] = set()
    for b in manifest.get("bad", []):
        path = ROOT / b["path"]
        if not path.is_file():
            issues.append({"reason": "missing bad fixture", "path": b["path"]})
            continue
        profile = b.get("profile", "strict")
        found_codes = {f.code for f in scan_paths([path], registry, profile)}
        expected = set(b.get("codes", []))
        covered |= expected
        missing = sorted(expected - found_codes)
        if missing:
            issues.append({"reason": "bad fixture missing expected diagnostic codes", "path": b["path"], "codes": missing})
    for code, item in registry.items():
        fixtures = [str(f) for f in item.get("fixtures", [])]
        # Analyzer families are exercised by scripts/analyze_precision_suite.sh
        # against goldens; the registry row only has to point at real files.
        analyzer_fixtures = [f for f in fixtures if f.startswith(ANALYZER_FIXTURE_PREFIX)]
        for fixture in analyzer_fixtures:
            if not (ROOT / fixture).is_file():
                issues.append({"reason": f"missing analyzer fixture for {code}", "path": fixture})
        firewall_fixtures = [f for f in fixtures if not f.startswith(ANALYZER_FIXTURE_PREFIX)]
        if firewall_fixtures and code not in covered:
            issues.append({"reason": f"registered fixture diagnostic {code} missing from fixture manifest coverage", "path": rel(FIXTURE_MANIFEST)})
    return issues


def to_json_findings(findings: Iterable[Finding]) -> list[dict[str, Any]]:
    return [
        {
            "code": f.code,
            "level": f.level,
            "path": f.path,
            "line": f.line,
            "column": f.column,
            "message": f.message,
            "replacement": f.replacement,
            "analyzer": f.analyzer,
            "rule": f.rule,
            "witness": f.witness,
            "blocking": f.blocking,
            "allowed_by_debt": f.allowed_by_debt,
        }
        for f in findings
    ]


def write_migration_report(path: Path, findings: list[Finding]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Ouro strict-quality migration report", "", "This report is deterministic: path, line, code, current level, replacement.", ""]
    for f in findings:
        status = "debt" if f.allowed_by_debt else ("blocking" if f.blocking else "nonblocking")
        lines.append(f"- `{f.path}:{f.line}:{f.column}` `{f.code}` `{f.level}` {status}: {f.message}")
        lines.append(f"  - replacement: {f.replacement}")
        if f.allowed_by_debt:
            lines.append(f"  - debt: `{f.allowed_by_debt}`")
    if len(lines) == 4:
        lines.append("No strict-quality findings in the selected production scope.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_sarif(path: Path, registry: dict[str, dict[str, Any]], findings: list[Finding]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rules = []
    for code in sorted({f.code for f in findings} | {c for c, i in registry.items() if i.get("fixtures")}):
        item = registry.get(code, {})
        rules.append({
            "id": code,
            "name": item.get("rule", code),
            "shortDescription": {"text": item.get("title", code)},
            "help": {"text": item.get("replacement", "Apply the documented replacement.")},
        })
    results = []
    for f in findings:
        if f.allowed_by_debt:
            continue
        results.append({
            "ruleId": f.code,
            "level": "error" if f.blocking else "warning",
            "message": {"text": f"{f.message} Replacement: {f.replacement}"},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": f.path},
                    "region": {"startLine": f.line, "startColumn": f.column},
                }
            }],
        })
    sarif = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": SARIF_VERSION,
        "runs": [{
            "tool": {
                "driver": {
                    "name": "ouro-strict-quality-firewall",
                    "informationUri": "docs/quality.md",
                    "rules": rules,
                }
            },
            "results": results,
        }],
    }
    path.write_text(json.dumps(sarif, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def print_findings(findings: list[Finding]) -> None:
    for f in findings:
        if f.allowed_by_debt:
            continue
        print(f"{f.path}:{f.line}:{f.column}: {f.level}[{f.code}] {f.analyzer}/{f.rule}: {f.message}")
        print(f"  replacement: {f.replacement}")
        if f.witness:
            print(f"  witness: {f.witness}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--structural", action="store_true", help="Full repository structural consolidation gate; no debt baseline or scope exclusions.")
    ap.add_argument("--profile", choices=["baseline", "project", "strict", "compiler", "release"], default="project")
    ap.add_argument("--scope", action="append", default=None, help="Source root/file to scan; may be repeated.")
    ap.add_argument("--include-fixtures", action="store_true")
    ap.add_argument("--skip-fixture-check", action="store_true")
    ap.add_argument("--report", default="_build/quality/strict-quality-firewall.json")
    ap.add_argument("--sarif", default="_build/quality/strict-quality-firewall.sarif")
    ap.add_argument("--migration-report", default="_build/quality/migration-report.md")
    ap.add_argument("--list-diagnostics", action="store_true")
    args = ap.parse_args(argv)

    if args.structural:
        from structural_quality import run
        if args.scope or args.include_fixtures or args.skip_fixture_check or args.list_diagnostics:
            ap.error("--structural requires the complete repository inventory")
        report = Path(args.report)
        if args.report == "_build/quality/strict-quality-firewall.json":
            report = Path("_build/quality/structural-quality.json")
        return run(ROOT, report if report.is_absolute() else ROOT / report)

    try:
        cfg, registry = load_registry()
    except ValueError as exc:
        print(f"STRICT_QUALITY_FIREWALL: FAIL {exc}", file=sys.stderr)
        return 1
    if args.list_diagnostics:
        for code in sorted(registry):
            item = registry[code]
            print(f"{code}\t{item.get('analyzer')}\t{item.get('levels', {}).get(args.profile, 'warn')}\t{item.get('title')}")
        return 0

    scopes = args.scope or cfg.get("project_scopes", ["std", "compiler", "tools/analyze", "tools", "samples"])
    paths = iter_files(scopes, include_fixtures=args.include_fixtures)
    findings0 = scan_paths(paths, registry, args.profile)
    try:
        findings, debt_issues = apply_debt(findings0, load_debt(), profile=args.profile)
        registry_issues = validate_registry(cfg, registry)
        fixture_issues = [] if args.skip_fixture_check else validate_fixtures(registry)
    except ValueError as exc:
        print(f"STRICT_QUALITY_FIREWALL: FAIL {exc}", file=sys.stderr)
        return 1
    blocking = [f for f in findings if f.blocking]
    all_issues = registry_issues + debt_issues + fixture_issues

    report_path = Path(args.report)
    if not report_path.is_absolute():
        report_path = ROOT / report_path
    sarif_path = Path(args.sarif)
    if not sarif_path.is_absolute():
        sarif_path = ROOT / sarif_path
    migration_path = Path(args.migration_report)
    if not migration_path.is_absolute():
        migration_path = ROOT / migration_path

    write_migration_report(migration_path, findings)
    write_sarif(sarif_path, registry, findings)
    report = {
        "kind": REPORT_KIND,
        "profile": args.profile,
        "pass": not blocking and not all_issues,
        "scopes": scopes,
        "files_scanned": len(paths),
        "diagnostics_total": len(findings),
        "diagnostics_blocking": len(blocking),
        "diagnostics_debt_allowed": sum(1 for f in findings if f.allowed_by_debt),
        "findings": to_json_findings(findings),
        "issues": all_issues,
        "reports": {"sarif": rel(sarif_path), "migration": rel(migration_path)},
        "policy": {
            "levels": cfg.get("profile_semantics"),
            "debt": "strict legacy debt is allowed only through capped manifest entries with reason/replacement/tracking",
            "fixtures": "bad fixtures must emit expected stable codes; good fixtures must stay clean",
        },
    }
    write_json_atomic(report_path, report)

    print_findings(findings)
    for issue in all_issues:
        print(f"STRICT_QUALITY_FIREWALL_ISSUE {issue.get('reason')} {issue.get('path', '')}", file=sys.stderr)
    status = "PASS" if report["pass"] else "FAIL"
    print(f"STRICT_QUALITY_FIREWALL: {status} profile={args.profile} files={len(paths)} blocking={len(blocking)} debt={report['diagnostics_debt_allowed']} report={rel(report_path)}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
