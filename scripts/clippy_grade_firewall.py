#!/usr/bin/env python3
"""Deterministic Clippy-grade deny firewall for Ouro source."""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, NamedTuple, Optional, Sequence

from repo_support import read_json_value, relative_path, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
SEVERITY_RANK = {
    "allow": 0,
    "info": 1,
    "warn": 2,
    "deny": 3,
    "fatal": 4,
}
PROFILES = ("baseline", "project", "strict", "release")
DEFAULT_SCOPES = ("std", "compiler", "tools/analyze", "tools", "samples")
CHECKED_WRAPPER_PATHS = {
    "std/fs.ouro",
    "std/fsx.ouro",
    "std/runtime.ouro",
    "std/process.ouro",
    "std/processx.ouro",
    "std/args.ouro",
    "std/cli.ouro",
    "std/config.ouro",
    "std/configx.ouro",
    "std/csv.ouro",
    "std/table.ouro",
}
PURE_PREFIXES = (
    "str_",
    "list_",
    "nat_",
    "bool_",
    "csv_",
    "table_",
    "format_",
    "parse_",
    "text_",
)
ERRORISH_WORDS = (
    "error",
    "failed",
    "failure",
    "invalid",
    "missing",
    "bad",
    "malformed",
    "usage",
)
FORBIDDEN_SAMPLE_LAYERS = ("std/", "tools/")
FORBIDDEN_IMPORT_MARKERS = ("demo", "generated", "private")
TRUST_SENSITIVE_PREFIXES = (
    "compiler/kernel",
    "compiler/trust",
    "compiler/check",
)
LINE_RULE_PATTERNS = (
    (r"\blet\s+(\w+)\s*:=\s*(\w+)\s+in\s+\1\b", "OURO-CLIPPY-REDUNDANT-001"),
    (r"\b(if|match)\s+(True|False)\b", "OURO-CLIPPY-LOGIC-003"),
    (r"\bnot\s*\(\s*not\s+\w+\s*\)|!!\w+", "OURO-CLIPPY-LOGIC-004"),
    (r"\b(\w+)\s*(==|=)\s*\1\b", "OURO-CLIPPY-LOGIC-001"),
    (r"\b(\w+)\s*([<>])\s*\1\b", "OURO-CLIPPY-LOGIC-002"),
    (
        r"\bappend\s+(Nil|\[\])(?:\s|;|$)|"
        r"\bappend\b.*\s+(Nil|\[\])\s*;?$|"
        r"\bconcat\s+\[\s*\]",
        "OURO-CLIPPY-REDUNDANT-005",
    ),
    (
        r"\bmap\s+\((?:fun|lambda)\s+(\w+)\s*=>\s*\1\s*\)|"
        r"\bfilter\s+\((?:fun|lambda)\s+_?\w+\s*=>\s*True\s*\)|"
        r"\bfold(?:l|r)?\s+\((?:fun|lambda)\s+acc\s+\w+\s*=>\s*acc\s*\)",
        "OURO-CLIPPY-REDUNDANT-006",
    ),
)
RAW_FS_RULES = (
    ("fs_read", "OURO-CLIPPY-CHECKED-001"),
    ("fs_write", "OURO-CLIPPY-CHECKED-002"),
)
DISCARDED_CHECKED_RE = re.compile(
    r"(fs_.*checked|fsx_|process.*checked|processx_|cli_required|config_.*checked|validation_)"
)
NESTED_BOOL_MATCH_RE = re.compile(r"\bmatch\b.*\bBool\b|\bmatch\s+\w+\s+with")
RAW_PROCESS_RE = re.compile(r"\b(proc_exec|process_exec|shell_exec)\b")
RAW_ARGV_RE = re.compile(r"\b(argv|args_of_argv|raw_args)\b")
MANUAL_CSV_SPLIT_RE = re.compile(r'\bstr_split\s+","|\bsplit\s+","')
UNCHECKED_OVERWRITE_RE = re.compile(
    r"\b(fs_write|fsx_write|write_text)\b.*\b(True|Overwrite|overwrite)\b"
)
LEFT_SUCCESS_RE = re.compile(r"\bLeft\s+\w+\s+\w+\s+(Success|Ok|Done|Valid)\b")
PRINTLN_ERROR_RE = re.compile(r'\bprintln\b.*"(?:error|failed|failure|invalid|missing|usage)')
SUCCESS_EXIT_RE = re.compile(r"\b(exit|io_exit|process_exit|return)\s+0\b")
SHELL_STRING_CONCAT_RE = re.compile(r"\"[^\"]*\"\s*\+\s*\w|\w+\s*\+\s*\"[^\"]*\"")
REQUIRED_ARG_RE = re.compile(r"\b(cli_required|args_required|required_arg)\b")
MISSING_USAGE_RE = re.compile(r"\b(Left|CliMissing|Missing|CliUsage|usage)\b")
IMPORT_RE = re.compile(r'\s*import\s+"([^"]+)"')
DISABLE_RULE_RE = re.compile(r"disable=([A-Za-z0-9_-]+)")
DISCARDED_BINDING_RE = re.compile(r"\blet\s+_\s*:=\s*([A-Za-z_][A-Za-z0-9_']*)")
DEF_START_RE = re.compile(r"^\s*def\s+\w")
DEF_NAME_RE = re.compile(r"\s*def\s+([A-Za-z_][A-Za-z0-9_']*)")
PARAM_RE = re.compile(r"\((\w+)\s*:")
LET_BINDING_RE = re.compile(r"\blet\s+\w+\s*:=")
BOOL_IDENTITY_MATCH_RE = re.compile(
    r"\bmatch\s+\w+\s+with\s*\n?\s*\|\s*True\s*=>\s*True\s*\n?\s*\|\s*False\s*=>\s*False",
    re.S,
)
BOOL_NEGATION_MATCH_RE = re.compile(
    r"\bmatch\s+\w+\s+with\s*\n?\s*\|\s*True\s*=>\s*False\s*\n?\s*\|\s*False\s*=>\s*True",
    re.S,
)
IF_THEN_ELSE_RE = re.compile(r"\bif\s+(.+?)\s+then\s+(.+?)\s+else\s+(.+?)(?:;|$)", re.S)
TRIVIAL_ACCESSOR_RE = re.compile(r"^x x x \| (?:x )+x => x x;?$")
SUCCESS_ARM_RE = re.compile(r"\|\s*(Right|Ok|Valid)\b")
FAILURE_ARM_RE = re.compile(r"\|\s*(Left|Err|Invalid)\b")
STRING_LIT_RE = re.compile(r'"((?:\\.|[^"])*)"')
MAGIC_NUMBER_RE = re.compile(r"\b([1-9][0-9]{3,}|[2-9][0-9]{2})\b")
LOCAL_HELPER_RE = re.compile(r"\blet\s+(\w*(?:Helper|helper))\b")
RULE_ID_RE = re.compile(r"OURO-CLIPPY-[A-Z]+-[0-9]{3}")
CHECKED_STRING_RESULT_RE = re.compile(r":\s*String\b\s*$")
TRUST_UMBRELLA_IMPORT_RE = re.compile(r'"(?:std/)?(prelude|everything|all|workflow)\.ouro"')
SHELLISH_WORDS_RE = re.compile(r"\b(command|cmd|shell|exec|process)\b")
MATCH_OR_END_RE = re.compile(r"\bmatch\b|\bend\b")


def finding_sort_key(finding: dict[str, Any]) -> tuple[str, int, int, str]:
    return (
        finding["path"],
        finding["line"],
        finding["column"],
        finding["rule_id"],
    )


class Definition(NamedTuple):
    name: str
    start_line: int
    header: str
    body: str
    body_lines: list[tuple[int, str]]
    is_public: bool


def relative_repo_path(path: Path) -> str:
    return relative_path(ROOT, path)


def code_without_comment(line: str) -> str:
    """Return *line* with a `--` comment removed, ignoring `--` inside strings."""
    in_string: Optional[str] = None
    escaped = False
    for index, char in enumerate(line):
        if in_string is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
            continue
        if char in {"'", '"'}:
            in_string = char
            continue
        if char == "-" and index + 1 < len(line) and line[index + 1] == "-":
            return line[:index]
    return line


def load_rules() -> dict[str, dict[str, Any]]:
    path = ROOT / "quality/clippy_grade_rules.json"
    inventory, error = read_json_value(path)
    if error is not None:
        raise SystemExit(
            f"CLIPPY_GRADE_FIREWALL: FAIL unreadable rule inventory "
            f"{relative_repo_path(path)}: {error}"
        )
    if not isinstance(inventory, dict):
        raise SystemExit(
            f"CLIPPY_GRADE_FIREWALL: FAIL rule inventory "
            f"{relative_repo_path(path)} is not a JSON object"
        )
    rules = inventory.get("rules", [])
    if not isinstance(rules, list):
        raise SystemExit(
            f"CLIPPY_GRADE_FIREWALL: FAIL rule inventory "
            f"{relative_repo_path(path)} rules is not an array"
        )
    loaded: dict[str, dict[str, Any]] = {}
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise SystemExit(
                f"CLIPPY_GRADE_FIREWALL: FAIL rule inventory "
                f"{relative_repo_path(path)} rules[{index}] is not an object"
            )
        rule_id = rule.get("id")
        if not isinstance(rule_id, str) or not rule_id:
            raise SystemExit(
                f"CLIPPY_GRADE_FIREWALL: FAIL rule inventory "
                f"{relative_repo_path(path)} rules[{index}] is missing id"
            )
        loaded[rule_id] = rule
    return loaded


def rule_level(rule: dict[str, Any], profile: str) -> str:
    levels = rule.get("levels", {})
    return levels.get(profile, levels.get("project", "warn"))


def append_finding(
    findings: list[dict[str, Any]],
    rules: dict[str, dict[str, Any]],
    profile: str,
    rule_id: str,
    path: Path,
    line: int,
    column: int,
    witness: str = "",
    suffix: str = "",
) -> None:
    rule = rules[rule_id]
    message = rule["message"]
    if suffix:
        message = f"{message} {suffix}"
    findings.append(
        {
            "rule_id": rule_id,
            "severity": rule_level(rule, profile),
            "path": relative_repo_path(path),
            "line": max(1, line),
            "column": max(1, column),
            "family": rule["family"],
            "title": rule["title"],
            "message": message,
            "fix": rule["fix"],
            "witness": witness.strip(),
            "suppressed_by": None,
        }
    )


def is_blocking(finding: dict[str, Any]) -> bool:
    if finding.get("suppressed_by"):
        return False
    return SEVERITY_RANK.get(finding["severity"], 3) >= 3


def is_checked_wrapper_module(repo_path: str) -> bool:
    if repo_path in CHECKED_WRAPPER_PATHS:
        return True
    if any(repo_path.endswith("/" + wrapper) for wrapper in CHECKED_WRAPPER_PATHS):
        return True
    if repo_path.startswith("runtime/"):
        return True
    if repo_path.startswith("compiler/runtime/"):
        return True
    return False


def should_skip_fixture_path(repo_path: str) -> bool:
    return (
        "_build/" in repo_path
        or "quality/fixtures/" in repo_path
        or "/bad/" in repo_path
        or "/good/" in repo_path
    )


def collect_sources(scopes: Iterable[str], include_fixtures: bool) -> list[Path]:
    found: list[Path] = []
    for scope in scopes:
        path = (ROOT / scope).resolve()
        if not path.exists():
            continue
        candidates = [path] if path.is_file() else list(path.rglob("*.ouro"))
        for candidate in candidates:
            repo_path = relative_repo_path(candidate)
            if not include_fixtures and should_skip_fixture_path(repo_path):
                continue
            found.append(candidate)
    return sorted(set(found), key=relative_repo_path)


def iter_definitions(lines: Sequence[str]) -> list[Definition]:
    starts = [
        index
        for index, line in enumerate(lines)
        if DEF_START_RE.match(code_without_comment(line))
    ]
    definitions: list[Definition] = []
    for offset, start in enumerate(starts):
        end = starts[offset + 1] if offset + 1 < len(starts) else len(lines)
        body = "\n".join(code_without_comment(lines[index]) for index in range(start, end))
        header_lines = [
            code_without_comment(lines[index]).strip()
            for index in range(start, min(end, start + 8))
        ]
        header = " ".join(header_lines).split(":=", 1)[0]
        match = DEF_NAME_RE.match(header)
        if match is None:
            continue
        leading = lines[max(0, start - 4) : start]
        is_public = any(
            "@export" in previous or "@api" in previous or "public-api" in previous
            for previous in leading
        )
        body_lines = [(index + 1, lines[index]) for index in range(start, end)]
        definitions.append(
            Definition(
                name=match.group(1),
                start_line=start + 1,
                header=header,
                body=body,
                body_lines=body_lines,
                is_public=is_public,
            )
        )
    return definitions


def normalize_for_duplicate(text: str) -> str:
    text = re.sub(r'"(?:\\.|[^"])*"', '"s"', text)
    text = re.sub(r"\b\d+\b", "n", text)
    text = re.sub(r"\b[A-Za-z_][A-Za-z0-9_']*\b", "x", text)
    return re.sub(r"\s+", " ", text).strip()


def collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _at_word(text: str, index: int, word: str) -> bool:
    end = index + len(word)
    if not text.startswith(word, index):
        return False
    if index > 0 and (text[index - 1].isalnum() or text[index - 1] == "_"):
        return False
    if end < len(text) and (text[end].isalnum() or text[end] == "_"):
        return False
    return True


def _skip_quoted(text: str, index: int) -> int:
    quote = text[index]
    index += 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == quote:
            return index + 1
        index += 1
    return index


def _without_strings(text: str) -> str:
    chars: list[str] = []
    index = 0
    while index < len(text):
        if text[index] in {'"', "'"}:
            index = _skip_quoted(text, index)
            chars.append('""')
            continue
        chars.append(text[index])
        index += 1
    return "".join(chars)


def nested_match_depth(body: str) -> int:
    depth = 0
    maximum = 0
    for keyword in MATCH_OR_END_RE.findall(_without_strings(body)):
        if keyword == "match":
            depth += 1
            maximum = max(maximum, depth)
        elif depth:
            depth -= 1
    return maximum


def _advance_match_depth(text: str, index: int, depth: int) -> tuple[int, int] | None:
    if _at_word(text, index, "match"):
        return index + 5, depth + 1
    if _at_word(text, index, "end"):
        return index + 3, depth - 1 if depth else 0
    return None


def sibling_match_arm_bodies(inner: str) -> list[str]:
    """Direct `| pat => expr` bodies of one match, ignoring nested matches."""
    depth = 0
    index = 0
    length = len(inner)
    arm_start: int | None = None
    arms: list[str] = []

    def flush(end: int) -> None:
        nonlocal arm_start
        if arm_start is None:
            return
        text = collapse_whitespace(inner[arm_start:end]).rstrip(";")
        if text:
            arms.append(text)
        arm_start = None

    while index < length:
        if inner[index] in {'"', "'"}:
            index = _skip_quoted(inner, index)
            continue
        stepped = _advance_match_depth(inner, index, depth)
        if stepped is not None:
            index, depth = stepped
            continue
        if depth == 0 and inner[index] == "|":
            flush(index)
            cursor = index + 1
            nest = 0
            while cursor < length:
                if inner[cursor] in {'"', "'"}:
                    cursor = _skip_quoted(inner, cursor)
                    continue
                nested = _advance_match_depth(inner, cursor, nest)
                if nested is not None:
                    cursor, nest = nested
                    continue
                if nest == 0 and inner.startswith("=>", cursor):
                    arm_start = cursor + 2
                    index = cursor + 2
                    break
                cursor += 1
            else:
                index += 1
            continue
        index += 1
    flush(length)
    return arms


def match_inners(body: str) -> list[str]:
    inners: list[str] = []
    index = 0
    length = len(body)
    while index < length:
        if body[index] in {'"', "'"}:
            index = _skip_quoted(body, index)
            continue
        if not _at_word(body, index, "match"):
            index += 1
            continue
        cursor = index + 5
        while cursor < length:
            if body[cursor] in {'"', "'"}:
                cursor = _skip_quoted(body, cursor)
                continue
            if _at_word(body, cursor, "with"):
                inner_start = cursor + 4
                depth = 1
                pos = inner_start
                while pos < length:
                    if body[pos] in {'"', "'"}:
                        pos = _skip_quoted(body, pos)
                        continue
                    stepped = _advance_match_depth(body, pos, depth)
                    if stepped is None:
                        pos += 1
                        continue
                    pos, depth = stepped
                    if depth == 0:
                        inners.append(body[inner_start : pos - 3])
                        index = inner_start
                        break
                else:
                    index = cursor + 4
                break
            if _at_word(body, cursor, "match") or _at_word(body, cursor, "end"):
                index = cursor
                break
            cursor += 1
        else:
            index += 5
    return inners


def has_same_sibling_match_branch(body: str) -> bool:
    for inner in match_inners(body):
        arms = sibling_match_arm_bodies(inner)
        if len(arms) >= 2 and len(set(arms)) == 1:
            return True
    return False


def is_trivial_accessor_body(normalized: str) -> bool:
    return TRIVIAL_ACCESSOR_RE.fullmatch(normalized) is not None


def apply_suppressions(
    findings: list[dict[str, Any]],
    suppressed: dict[int, set[str]],
) -> None:
    for finding in findings:
        line_rules = suppressed.get(finding["line"], set())
        if finding["rule_id"] in line_rules:
            finding["suppressed_by"] = f"line:{finding['line']}"


def scan_suppressions(
    path: Path,
    lines: Sequence[str],
    rules: dict[str, dict[str, Any]],
    profile: str,
    findings: list[dict[str, Any]],
) -> dict[int, set[str]]:
    suppressed: dict[int, set[str]] = defaultdict(set)
    for line_no, raw in enumerate(lines, 1):
        if "ouro-clippy:disable" not in raw:
            continue
        if "disable-all" in raw or "disable=*" in raw:
            append_finding(
                findings,
                rules,
                profile,
                "OURO-CLIPPY-SUPPRESS-001",
                path,
                line_no,
                raw.find("ouro-clippy") + 1,
                raw,
            )
            continue
        match = DISABLE_RULE_RE.search(raw)
        rule_id = match.group(1).rstrip(",;)") if match else ""
        if rule_id not in rules:
            append_finding(
                findings,
                rules,
                profile,
                "OURO-CLIPPY-SUPPRESS-003",
                path,
                line_no,
                raw.find(rule_id) + 1,
                raw,
                f"Unknown rule: {rule_id}.",
            )
            continue
        if "reason=" not in raw:
            append_finding(
                findings,
                rules,
                profile,
                "OURO-CLIPPY-SUPPRESS-002",
                path,
                line_no,
                raw.find("ouro-clippy") + 1,
                raw,
                f"Rule: {rule_id}.",
            )
        suppressed[line_no].add(rule_id)
        suppressed[line_no + 1].add(rule_id)
    return suppressed


def imports_wrong_layer(repo_path: str, import_target: str) -> bool:
    from_production = repo_path.startswith(FORBIDDEN_SAMPLE_LAYERS)
    from_sample_fixture = Path(repo_path).name.startswith("sample_import")
    imports_sample = import_target.startswith("samples/")
    std_imports_tools = repo_path.startswith("std/") and import_target.startswith("tools/")
    return ((from_production or from_sample_fixture) and imports_sample) or std_imports_tools


def imports_private_or_demo(repo_path: str, import_target: str) -> bool:
    marked = any(marker in import_target for marker in FORBIDDEN_IMPORT_MARKERS)
    production = repo_path.startswith(("std/", "tools/", "compiler/"))
    private_fixture = Path(repo_path).name.startswith("private_import")
    return marked and (production or private_fixture)


def imports_trust_umbrella(repo_path: str, code: str) -> bool:
    trust_path = repo_path.startswith(TRUST_SENSITIVE_PREFIXES)
    trust_fixture = Path(repo_path).name.startswith("tcb_")
    return (trust_path or trust_fixture) and TRUST_UMBRELLA_IMPORT_RE.search(code) is not None


def scan_line_rules(
    path: Path,
    repo_path: str,
    lines: Sequence[str],
    rules: dict[str, dict[str, Any]],
    profile: str,
    findings: list[dict[str, Any]],
) -> None:
    seen_imports: dict[str, int] = {}
    all_text = "\n".join(lines)
    saw_errorish_word = False
    wrapper_module = is_checked_wrapper_module(repo_path)

    for line_no, raw in enumerate(lines, 1):
        code = code_without_comment(raw)
        lowered = code.lower()
        import_match = IMPORT_RE.match(code)
        if import_match:
            target = import_match.group(1).replace("\\", "/").lstrip("./")
            if target in seen_imports:
                append_finding(
                    findings,
                    rules,
                    profile,
                    "OURO-CLIPPY-IMPORT-001",
                    path,
                    line_no,
                    raw.find("import") + 1,
                    raw,
                    f"First import on line {seen_imports[target]}.",
                )
            seen_imports.setdefault(target, line_no)
            if imports_wrong_layer(repo_path, target):
                append_finding(
                    findings, rules, profile, "OURO-CLIPPY-IMPORT-002", path, line_no, 1, raw
                )
            if imports_private_or_demo(repo_path, target):
                append_finding(
                    findings, rules, profile, "OURO-CLIPPY-IMPORT-004", path, line_no, 1, raw
                )
            if imports_trust_umbrella(repo_path, code):
                append_finding(
                    findings, rules, profile, "OURO-CLIPPY-IMPORT-003", path, line_no, 1, raw
                )

        for pattern, rule_id in LINE_RULE_PATTERNS:
            match = re.search(pattern, code)
            if match:
                append_finding(
                    findings, rules, profile, rule_id, path, line_no, match.start() + 1, raw
                )

        discarded = DISCARDED_BINDING_RE.search(code)
        if discarded:
            callee = discarded.group(1)
            if callee.startswith(PURE_PREFIXES):
                append_finding(
                    findings,
                    rules,
                    profile,
                    "OURO-CLIPPY-REDUNDANT-007",
                    path,
                    line_no,
                    discarded.start() + 1,
                    raw,
                    f"Discarded call: {callee}.",
                )
            if DISCARDED_CHECKED_RE.search(callee):
                append_finding(
                    findings,
                    rules,
                    profile,
                    "OURO-CLIPPY-CHECKED-006",
                    path,
                    line_no,
                    discarded.start() + 1,
                    raw,
                    f"Discarded checked result: {callee}.",
                )

        if (
            NESTED_BOOL_MATCH_RE.search(code)
            and "=> match" in code
            and ("True" in code or "False" in code)
        ):
            append_finding(
                findings,
                rules,
                profile,
                "OURO-CLIPPY-LOGIC-005",
                path,
                line_no,
                code.find("match") + 1,
                raw,
            )

        if not wrapper_module:
            for name, rule_id in RAW_FS_RULES:
                if re.search(rf"\b{name}\b", code):
                    append_finding(
                        findings,
                        rules,
                        profile,
                        rule_id,
                        path,
                        line_no,
                        max(1, code.find(name) + 1),
                        raw,
                    )
            process_match = RAW_PROCESS_RE.search(code)
            if process_match:
                append_finding(
                    findings,
                    rules,
                    profile,
                    "OURO-CLIPPY-CHECKED-003",
                    path,
                    line_no,
                    process_match.start() + 1,
                    raw,
                )
            if RAW_ARGV_RE.search(code) and not repo_path.startswith("tools/"):
                append_finding(
                    findings,
                    rules,
                    profile,
                    "OURO-CLIPPY-CHECKED-004",
                    path,
                    line_no,
                    max(1, code.find("argv") + 1),
                    raw,
                )
            if MANUAL_CSV_SPLIT_RE.search(code):
                append_finding(
                    findings, rules, profile, "OURO-CLIPPY-CHECKED-005", path, line_no, 1, raw
                )
            if UNCHECKED_OVERWRITE_RE.search(code):
                append_finding(
                    findings, rules, profile, "OURO-CLIPPY-CHECKED-007", path, line_no, 1, raw
                )

        if LEFT_SUCCESS_RE.search(code):
            append_finding(
                findings,
                rules,
                profile,
                "OURO-CLIPPY-ERROR-003",
                path,
                line_no,
                max(1, code.find("Left") + 1),
                raw,
            )
        if PRINTLN_ERROR_RE.search(lowered):
            append_finding(
                findings,
                rules,
                profile,
                "OURO-CLIPPY-ERROR-002",
                path,
                line_no,
                max(1, code.find("println") + 1),
                raw,
            )

        if any(word in lowered for word in ERRORISH_WORDS):
            saw_errorish_word = True
        success_exit = SUCCESS_EXIT_RE.search(code)
        if saw_errorish_word and success_exit:
            append_finding(
                findings,
                rules,
                profile,
                "OURO-CLIPPY-ERROR-001",
                path,
                line_no,
                success_exit.start() + 1,
                raw,
            )

        if SHELL_STRING_CONCAT_RE.search(code) and SHELLISH_WORDS_RE.search(lowered):
            append_finding(
                findings,
                rules,
                profile,
                "OURO-CLIPPY-CLI-003",
                path,
                line_no,
                max(1, code.find("+") + 1),
                raw,
            )
        required_arg = REQUIRED_ARG_RE.search(code)
        if required_arg and not MISSING_USAGE_RE.search(all_text):
            append_finding(
                findings,
                rules,
                profile,
                "OURO-CLIPPY-CLI-002",
                path,
                line_no,
                required_arg.start() + 1,
                raw,
            )


def scan_definitions(
    path: Path,
    lines: Sequence[str],
    rules: dict[str, dict[str, Any]],
    profile: str,
    findings: list[dict[str, Any]],
) -> None:
    signatures: dict[str, tuple[str, int]] = {}
    helper_counts: Counter[str] = Counter()
    defined_names: set[str] = set()
    error_types: list[tuple[str, int]] = []

    for definition in iter_definitions(lines):
        defined_names.add(definition.name)
        params = [name for name in PARAM_RE.findall(definition.header) if not name.startswith("_")]
        witness_line = definition.body_lines[0][1]

        if definition.is_public and re.fullmatch(r"[A-Za-z]", definition.name):
            append_finding(
                findings,
                rules,
                profile,
                "OURO-CLIPPY-NAMING-001",
                path,
                definition.start_line,
                1,
                witness_line,
                f"Public name: {definition.name}.",
            )
        if definition.name.endswith("_checked") and CHECKED_STRING_RESULT_RE.search(definition.header):
            append_finding(
                findings,
                rules,
                profile,
                "OURO-CLIPPY-NAMING-002",
                path,
                definition.start_line,
                1,
                witness_line,
            )
        if len(params) > 7:
            append_finding(
                findings,
                rules,
                profile,
                "OURO-CLIPPY-MAINT-001",
                path,
                definition.start_line,
                1,
                witness_line,
                f"Parameter count: {len(params)}.",
            )

        let_count = len(LET_BINDING_RE.findall(definition.body))
        if let_count > 18:
            append_finding(
                findings,
                rules,
                profile,
                "OURO-CLIPPY-MAINT-002",
                path,
                definition.start_line,
                1,
                witness_line,
                f"Local let count: {let_count}.",
            )

        match_depth = nested_match_depth(definition.body)
        if match_depth > 4:
            append_finding(
                findings,
                rules,
                profile,
                "OURO-CLIPPY-MAINT-003",
                path,
                definition.start_line,
                1,
                witness_line,
                f"Nested match depth: {match_depth}.",
            )

        nonempty_lines = [text for _, text in definition.body_lines if text.strip()]
        if len(nonempty_lines) > 160:
            append_finding(
                findings,
                rules,
                profile,
                "OURO-CLIPPY-MAINT-008",
                path,
                definition.start_line,
                1,
                witness_line,
            )

        if BOOL_IDENTITY_MATCH_RE.search(definition.body):
            append_finding(
                findings,
                rules,
                profile,
                "OURO-CLIPPY-REDUNDANT-002",
                path,
                definition.start_line,
                1,
                witness_line,
            )
        if BOOL_NEGATION_MATCH_RE.search(definition.body):
            append_finding(
                findings,
                rules,
                profile,
                "OURO-CLIPPY-REDUNDANT-003",
                path,
                definition.start_line,
                1,
                witness_line,
            )

        if_match = IF_THEN_ELSE_RE.search(definition.body)
        if if_match and collapse_whitespace(if_match.group(2)) == collapse_whitespace(if_match.group(3)):
            append_finding(
                findings,
                rules,
                profile,
                "OURO-CLIPPY-REDUNDANT-004",
                path,
                definition.start_line,
                1,
                witness_line,
            )

        if has_same_sibling_match_branch(definition.body):
            append_finding(
                findings,
                rules,
                profile,
                "OURO-CLIPPY-REDUNDANT-004",
                path,
                definition.start_line,
                1,
                witness_line,
            )

        returns_result = any(token in definition.header for token in ("Either", "Result", "Validation"))
        if returns_result and SUCCESS_ARM_RE.search(definition.body) and not FAILURE_ARM_RE.search(definition.body):
            append_finding(
                findings,
                rules,
                profile,
                "OURO-CLIPPY-LOGIC-006",
                path,
                definition.start_line,
                1,
                witness_line,
            )

        if definition.name == "main" and "cli_" in definition.body and "usage" not in definition.body.lower():
            append_finding(
                findings,
                rules,
                profile,
                "OURO-CLIPPY-CLI-001",
                path,
                definition.start_line,
                1,
                witness_line,
            )

        literals: Counter[str] = Counter()
        first_line: dict[str, int] = {}
        for line_no, raw in definition.body_lines:
            code = code_without_comment(raw)
            for literal in STRING_LIT_RE.findall(code):
                if len(literal) >= 3:
                    literals[literal] += 1
                    first_line.setdefault(literal, line_no)
            for number in MAGIC_NUMBER_RE.finditer(code):
                if "const" in raw:
                    continue
                if "limit" in raw.lower() or "threshold" in raw.lower():
                    continue
                append_finding(
                    findings,
                    rules,
                    profile,
                    "OURO-CLIPPY-MAINT-005",
                    path,
                    line_no,
                    number.start(1) + 1,
                    raw,
                    f"Literal: {number.group(1)}.",
                )
        for literal, count in literals.items():
            if count >= 4:
                append_finding(
                    findings,
                    rules,
                    profile,
                    "OURO-CLIPPY-MAINT-004",
                    path,
                    first_line[literal],
                    1,
                    literal,
                    f"String literal appears {count} times in {definition.name}.",
                )

        helper_counts.update(LOCAL_HELPER_RE.findall(definition.body))
        normalized_body = normalize_for_duplicate(definition.body.split(":=", 1)[-1])
        if len(normalized_body) >= 18 and not is_trivial_accessor_body(normalized_body):
            previous = signatures.get(normalized_body)
            if previous is not None and previous[0] != definition.name:
                append_finding(
                    findings,
                    rules,
                    profile,
                    "OURO-CLIPPY-MAINT-007",
                    path,
                    definition.start_line,
                    1,
                    witness_line,
                    f"Near-duplicate of {previous[0]} at line {previous[1]}.",
                )
            else:
                signatures[normalized_body] = (definition.name, definition.start_line)

        if definition.name.endswith("Error") or definition.name.endswith("Err"):
            error_types.append((definition.name, definition.start_line))

    for helper_name, count in helper_counts.items():
        if count > 1:
            append_finding(
                findings,
                rules,
                profile,
                "OURO-CLIPPY-MAINT-006",
                path,
                1,
                1,
                helper_name,
                f"Local helper {helper_name} appears {count} times.",
            )

    for error_name, line_no in error_types:
        base = error_name[:-5] if error_name.endswith("Error") else error_name
        candidates = {
            f"{base.lower()}_error_message",
            f"{base.lower()}_message",
            f"{error_name.lower()}_message",
            f"{base.lower()}_error_code",
        }
        if not any(name in defined_names for name in candidates):
            append_finding(
                findings,
                rules,
                profile,
                "OURO-CLIPPY-NAMING-003",
                path,
                line_no,
                1,
                error_name,
                f"Expected one of: {', '.join(sorted(candidates))}.",
            )


def scan_file(
    path: Path,
    rules: dict[str, dict[str, Any]],
    profile: str,
) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise SystemExit(
            f"CLIPPY_GRADE_FIREWALL: FAIL unreadable {relative_repo_path(path)}: {exc}"
        ) from exc
    findings: list[dict[str, Any]] = []
    suppressed = scan_suppressions(path, lines, rules, profile, findings)
    scan_line_rules(path, relative_repo_path(path), lines, rules, profile, findings)
    scan_definitions(path, lines, rules, profile, findings)
    apply_suppressions(findings, suppressed)
    return sorted(findings, key=finding_sort_key)


def validate_rules(rules: dict[str, dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    families = {rule.get("family") for rule in rules.values()}
    if len(rules) < 30:
        issues.append(f"expected at least 30 clippy-grade rules, got {len(rules)}")
    if len(families) < 8:
        issues.append(f"expected at least 8 rule families, got {len(families)}")
    for rule_id, rule in rules.items():
        if not RULE_ID_RE.fullmatch(rule_id):
            issues.append(f"{rule_id}: invalid rule id")
        levels = rule.get("levels", {})
        for profile in PROFILES:
            if levels.get(profile) not in SEVERITY_RANK:
                issues.append(f"{rule_id}: missing/invalid {profile} level")
        if not rule.get("message") or not rule.get("fix"):
            issues.append(f"{rule_id}: missing message or fix")
    return sorted(issues)


def resolve_under_root(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def print_findings(findings: Sequence[dict[str, Any]]) -> None:
    for finding in findings:
        if finding.get("suppressed_by"):
            continue
        location = f"{finding['path']}:{finding['line']}:{finding['column']}"
        print(
            f"{location}: {finding['severity']}[{finding['rule_id']}] "
            f"{finding['family']}/{finding['title']}: {finding['message']}"
        )
        print("  fix: " + finding["fix"])
        if finding.get("witness"):
            print("  witness: " + finding["witness"])


def print_inventory_issues(issues: Sequence[str]) -> None:
    for issue in issues:
        print("RULE_INVENTORY_ISSUE " + issue, file=sys.stderr)


def write_reports(
    report_path: Path,
    sarif_path: Path,
    *,
    profile: str,
    warn_only: bool,
    scopes: Sequence[str],
    files_scanned: int,
    rules: dict[str, dict[str, Any]],
    findings: Sequence[dict[str, Any]],
    blocking: Sequence[dict[str, Any]],
    inventory_issues: Sequence[str],
) -> None:
    visible = [finding for finding in findings if not finding.get("suppressed_by")]
    write_json_atomic(
        report_path,
        {
            "kind": "ouro.clippy-grade-firewall-report.v1",
            "profile": profile,
            "pass": not blocking and not inventory_issues,
            "warn_only": warn_only,
            "scopes": list(scopes),
            "files_scanned": files_scanned,
            "rule_count": len(rules),
            "family_count": len({rule["family"] for rule in rules.values()}),
            "diagnostics_total": len(visible),
            "diagnostics_blocking": len(blocking),
            "validation_issues": list(inventory_issues),
            "findings": list(findings),
        },
    )
    sarif_results = [
        {
            "ruleId": finding["rule_id"],
            "level": "error" if is_blocking(finding) else "warning",
            "message": {"text": finding["message"] + " Fix: " + finding["fix"]},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": finding["path"]},
                        "region": {
                            "startLine": finding["line"],
                            "startColumn": finding["column"],
                        },
                    }
                }
            ],
        }
        for finding in visible
    ]
    write_json_atomic(
        sarif_path,
        {
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {"driver": {"name": "ouro-clippy-grade-firewall"}},
                    "results": sarif_results,
                }
            ],
        },
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=PROFILES,
        default="project",
    )
    parser.add_argument("--scope", action="append")
    parser.add_argument("--include-fixtures", action="store_true")
    parser.add_argument("--report", default="_build/quality/clippy-grade-firewall.json")
    parser.add_argument("--sarif", default="_build/quality/clippy-grade-firewall.sarif")
    parser.add_argument("--warn-only", action="store_true")
    parser.add_argument("--list-rules", action="store_true")
    parser.add_argument("--validate-rules", action="store_true")
    args = parser.parse_args(argv)

    rules = load_rules()
    inventory_issues = validate_rules(rules)

    if args.list_rules:
        for rule_id, rule in sorted(rules.items()):
            print(f"{rule_id}\t{rule['family']}\t{rule_level(rule, args.profile)}\t{rule['title']}")
        return 0

    if args.validate_rules:
        print_inventory_issues(inventory_issues)
        return 0 if not inventory_issues else 1

    scopes = args.scope or list(DEFAULT_SCOPES)
    sources = collect_sources(scopes, args.include_fixtures)
    findings: list[dict[str, Any]] = []
    for source in sources:
        findings.extend(scan_file(source, rules, args.profile))
    findings = sorted(findings, key=finding_sort_key)
    blocking = [finding for finding in findings if is_blocking(finding)]

    report_path = resolve_under_root(args.report)
    sarif_path = resolve_under_root(args.sarif)
    write_reports(
        report_path,
        sarif_path,
        profile=args.profile,
        warn_only=args.warn_only,
        scopes=scopes,
        files_scanned=len(sources),
        rules=rules,
        findings=findings,
        blocking=blocking,
        inventory_issues=inventory_issues,
    )
    print_findings(findings)
    print_inventory_issues(inventory_issues)
    passed = not blocking and not inventory_issues
    print(
        f"CLIPPY_GRADE_FIREWALL: {'PASS' if passed else 'FAIL'} "
        f"profile={args.profile} files={len(sources)} blocking={len(blocking)} "
        f"rules={len(rules)} report={relative_repo_path(report_path)}"
    )
    if args.warn_only or passed:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
