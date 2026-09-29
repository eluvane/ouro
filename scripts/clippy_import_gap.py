#!/usr/bin/env python3
"""Report names that Clippy stubs but harvested sources still use.

The walker in tools/clippy/semantic_unit.ouro drops selected import cones so
one lint process stays inside its address-space cap. This command reads those
literal inventories and the import graph. It does not run the compiler. A
reported name is a declaration that lint would not harvest, named from a file
that lint does harvest.
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

from selfhost_module_cache import DECL_RE, quoted_import_targets

ROOT = Path(__file__).resolve().parents[1]
UNIT = ROOT / "tools/clippy/semantic_unit.ouro"
WORKER = ROOT / "tools/lint_worker.ouro"
PLATFORM_PREFIX = "runtime/platform/"
LIST_RE = re.compile(
    r"^def (?P<name>[A-Za-z_][A-Za-z0-9_']*) : List String :=\s*\[(?P<body>[^\]]*)\];",
    re.MULTILINE,
)
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_']*")


class GapError(ValueError):
    """The inventories or an import graph cannot be read."""


def string_list(source: str, name: str) -> tuple[str, ...]:
    found = [match for match in LIST_RE.finditer(source) if match.group("name") == name]
    if len(found) != 1:
        raise GapError(f"{name} is not a single literal String list")
    body = found[0].group("body")
    items = tuple(re.findall(r'"([^"\\\n]*)"', body))
    if not items or re.sub(r'"[^"\\\n]*"|[\s,]', "", body):
        raise GapError(f"{name} is not a single literal String list")
    return items


def load_rules(source: str) -> dict[str, tuple[str, ...]]:
    if f'prim_string_starts path "{PLATFORM_PREFIX}"' not in source:
        raise GapError("runtime platform prefix is not the Clippy stub rule")
    return {
        "keep": string_list(source, "cm_keep_import_paths"),
        "exact": string_list(source, "cm_skip_exact_paths"),
        "analyze": string_list(source, "cm_skip_analyze_paths"),
        "impl": string_list(source, "cm_skip_impl_paths"),
    }


def stubbed(path: str, root: str, direct: set[str], rules: dict[str, tuple[str, ...]]) -> bool:
    if path == root or path in direct or path in rules["keep"]:
        return False
    if root.startswith("runtime/") and path.startswith(PLATFORM_PREFIX):
        return False
    if path.startswith(PLATFORM_PREFIX) or path in rules["exact"] or path in rules["analyze"] or path in rules["impl"]:
        return True
    return False


def code_words(source: str) -> list[tuple[str, int, str | None]]:
    """Words outside comments and literals, with the preceding word."""
    words: list[tuple[str, int, str | None]] = []
    index = 0
    line = 1
    previous: str | None = None
    while index < len(source):
        if source[index] == "\n":
            line += 1
            index += 1
            continue
        if source[index].isspace():
            index += 1
            continue
        if source.startswith("--", index):
            end = source.find("\n", index)
            index = len(source) if end < 0 else end
            continue
        if source.startswith('"""', index) or source.startswith('r#"', index) or source[index] in "\"'":
            if source.startswith('"""', index):
                end = source.find('"""', index + 3)
                index = len(source) if end < 0 else end + 3
            elif source.startswith('r#"', index):
                end = source.find('"#', index + 3)
                index = len(source) if end < 0 else end + 2
            else:
                quote = source[index]
                index += 1
                while index < len(source) and source[index] != quote:
                    index += 2 if source[index] == "\\" else 1
                index += int(index < len(source))
            continue
        match = IDENT_RE.match(source, index)
        if match is None:
            index += 1
            continue
        word = match.group(0)
        words.append((word, line, previous))
        previous = word
        index = match.end()
    return words


def definitions(source: str) -> set[str]:
    return {match.group(2) for line in source.splitlines() if (match := DECL_RE.match(line))}


def read_source(root: Path, path: str) -> str:
    file = (root / path).resolve()
    if not file.is_relative_to(root.resolve()) or not file.is_file():
        raise GapError(f"import target is missing: {path}")
    return file.read_text(encoding="utf-8")


def production_roots(root: Path) -> list[str]:
    worker = (root / "tools/lint_worker.ouro").read_text(encoding="utf-8")
    directories = string_list(worker, "defaults")
    found: list[str] = []
    for directory in directories:
        base = root / directory
        if not base.is_dir():
            raise GapError(f"lint root is missing: {directory}")
        found.extend(sorted(path.relative_to(root).as_posix() for path in base.rglob("*.ouro")))
    if not found:
        raise GapError("lint roots contain no Ouro sources")
    return found


def gaps_for(root: Path, rules: dict[str, tuple[str, ...]], roots: list[str]) -> list[str]:
    text: dict[str, str] = {}
    imports: dict[str, list[str]] = {}

    def load(path: str) -> str:
        if path not in text:
            text[path] = read_source(root, path)
            imports[path] = quoted_import_targets(text[path], path)
        return text[path]

    closure_of: dict[str, set[str]] = {}

    def closure(path: str) -> set[str]:
        cached = closure_of.get(path)
        if cached is not None:
            return cached
        load(path)
        seen = {path}
        pending = list(imports[path])
        while pending:
            nxt = pending.pop()
            if nxt in seen:
                continue
            seen.add(nxt)
            load(nxt)
            pending.extend(imports[nxt])
        closure_of[path] = seen
        return seen

    reports: dict[tuple[str, str, str], str] = {}
    for entry in roots:
        seen = closure(entry)
        direct = set(imports[entry])
        defined: dict[str, str] = {}
        for path in seen:
            if not stubbed(path, entry, direct, rules):
                continue
            for name in definitions(text[path]):
                defined.setdefault(name, path)
        harvested = [path for path in seen if not stubbed(path, entry, direct, rules)]
        for path in harvested:
            for name in definitions(text[path]):
                defined.pop(name, None)
        if not defined:
            continue
        for path in harvested:
            reached = closure(path)
            for word, line, previous in code_words(text[path]):
                if previous == "def" or word not in defined or defined[word] not in reached:
                    continue
                key = (f"{path}:{line}", word, defined[word])
                reports.setdefault(
                    key,
                    f"CLIPPY_IMPORT_GAP root={entry} use={path}:{line} name={word} stub={defined[word]}",
                )
    return sorted(reports.values())


def scan(root: Path) -> list[str]:
    rules = load_rules((root / "tools/clippy/semantic_unit.ouro").read_text(encoding="utf-8"))
    return gaps_for(root, rules, production_roots(root))


def self_test() -> int:
    failures: list[str] = []
    rules = {
        "keep": ("compiler/base.ouro",),
        "exact": ("std/process.ouro",),
        "analyze": (),
        "impl": (),
    }
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "compiler").mkdir()
        (root / "std").mkdir()
        (root / "runtime/platform").mkdir(parents=True)
        (root / "compiler/middle.ouro").write_text(
            'import "../std/process.ouro";\ndef bridge : Nat := Z;\n',
            encoding="utf-8",
        )
        (root / "compiler/root.ouro").write_text(
            'import "middle.ouro", "base.ouro";\n'
            "def main : Nat := add (process_spawn Z) base_value;\n",
            encoding="utf-8",
        )
        (root / "std/process.ouro").write_text("def process_spawn (n : Nat) : Nat := n;\n", encoding="utf-8")
        (root / "compiler/base.ouro").write_text("def base_value : Nat := Z;\n", encoding="utf-8")
        (root / "runtime/platform/windows_fs.ouro").write_text("def platform_only : Nat := Z;\n", encoding="utf-8")
        (root / "std/direct.ouro").write_text(
            'import "process.ouro";\ndef use_direct : Nat := process_spawn Z;\n',
            encoding="utf-8",
        )
        (root / "compiler/quoted.ouro").write_text(
            'import "../std/process.ouro";\n'
            'def text : String := "process_spawn";\n',
            encoding="utf-8",
        )
        found = gaps_for(root, rules, ["compiler/root.ouro"])
        if found != [
            "CLIPPY_IMPORT_GAP root=compiler/root.ouro use=compiler/root.ouro:2 "
            "name=process_spawn stub=std/process.ouro"
        ]:
            failures.append("call of a stubbed declaration was not reported exactly: " + repr(found))
        if gaps_for(root, rules, ["std/direct.ouro"]):
            failures.append("a direct import of a stub path was treated as stubbed")
        if gaps_for(root, rules, ["compiler/quoted.ouro"]):
            failures.append("a quoted name was treated as a use")
        if not stubbed("runtime/platform/windows_fs.ouro", "std/io.ouro", set(), rules):
            failures.append("platform cone was harvested from outside runtime")
        if stubbed("runtime/platform/windows_fs.ouro", "runtime/managed.ouro", set(), rules):
            failures.append("runtime root lost its platform cone")
        if stubbed("compiler/base.ouro", "compiler/root.ouro", set(), rules):
            failures.append("keep-list module was stubbed")
    try:
        load_rules(UNIT.read_text(encoding="utf-8"))
    except GapError as error:
        failures.append(str(error))
    if failures:
        print("CLIPPY_IMPORT_GAP_SELFTEST: FAIL", *failures, sep="\n", file=sys.stderr)
        return 1
    print("CLIPPY_IMPORT_GAP_SELFTEST: PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["--self-test"]:
        return self_test()
    if arguments:
        print("CLIPPY_IMPORT_GAP: FAIL unknown arguments", file=sys.stderr)
        return 2
    try:
        found = scan(ROOT)
    except (GapError, OSError, UnicodeError, ValueError) as error:
        print(f"CLIPPY_IMPORT_GAP: FAIL {error}", file=sys.stderr)
        return 1
    if found:
        grouped: dict[str, list[str]] = {}
        for line in found:
            parts = dict(token.split("=", 1) for token in line.split()[1:])
            grouped.setdefault(parts["stub"], []).append(line)
        shown = 0
        for stub, rows in sorted(grouped.items()):
            print(f"CLIPPY_IMPORT_GAP stub={stub} uses={len(rows)}")
            for line in rows[:8]:
                parts = dict(token.split("=", 1) for token in line.split()[1:])
                print(f"  {parts['name']} {parts['use']} root={parts['root']}")
                shown += 1
            if len(rows) > 8:
                print(f"  ... {len(rows) - 8} more")
        print(
            f"CLIPPY_IMPORT_GAP: FAIL stubs={len(grouped)} uses={len(found)} shown={shown}",
            file=sys.stderr,
        )
        return 1
    print("CLIPPY_IMPORT_GAP: PASS gaps=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
