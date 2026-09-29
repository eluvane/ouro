#!/usr/bin/env python3
"""Report Clippy omissions that a long compiler or lint job would find later.

The walker in tools/clippy/semantic_unit.ouro drops selected import cones so
one lint process stays inside its address-space cap. This command reads those
literal inventories, the import graph, and match arms. It does not run the
compiler. A reported name is a declaration lint would not harvest, a bare name
whose only definition was never imported, a stub-list line that is missing or
repeated, or a match that dropped one or two constructors.
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
DECL_HEAD_RE = re.compile(
    r"^\s*(private\s+)?(def|inductive|record|axiom|theorem|lemma|effect|handler|intrinsic|extern)"
    r"\s+([A-Za-z_][A-Za-z0-9_']*)"
)
NEXT_DECL_RE = re.compile(
    r"^\s*(?:private\s+)?(?:def|inductive|record|axiom|theorem|lemma|effect|handler|intrinsic|extern|import)\b"
)
CTOR_RE = re.compile(r"\|\s*([A-Za-z_][A-Za-z0-9_']*)\b")
CONTRACT_CALL_RE = re.compile(
    r"cm_skip_import_(?P<kind>path|for)\s+\"(?P<a>[^\"\n]+)\"(?:\s+\"(?P<b>[^\"\n]+)\")?"
)
KEYWORDS = {
    "def", "inductive", "record", "axiom", "theorem", "lemma", "effect", "handler",
    "match", "with", "end", "let", "in", "if", "then", "else", "fix", "fun", "Type",
    "import", "do", "where", "private", "public", "module", "open", "as", "exposing",
    "intrinsic", "extern", "representation",
}
DECL_WORDS = {
    "def", "inductive", "record", "axiom", "theorem", "lemma", "effect", "handler",
    "intrinsic", "extern",
}


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

    full_of: dict[str, set[str]] = {}

    def full_closure(path: str) -> set[str]:
        cached = full_of.get(path)
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
        full_of[path] = seen
        return seen

    def reachable(entry: str) -> tuple[set[str], set[str]]:
        """Files the walker parses. Stubbed imports contribute no declarations."""
        load(entry)
        direct = set(imports[entry])
        harvested: set[str] = set()
        signatures: set[str] = set()
        seen: set[str] = set()
        pending = [entry]
        while pending:
            path = pending.pop()
            if path in seen:
                continue
            seen.add(path)
            load(path)
            if stubbed(path, entry, direct, rules):
                continue
            harvested.add(path)
            pending.extend(imports[path])
        return harvested, signatures

    reports: dict[tuple[str, str, str], str] = {}
    for entry in roots:
        harvested, signatures = reachable(entry)
        available: set[str] = set()
        for path in harvested | signatures:
            available.update(definitions(text[path]))
        beyond: dict[str, str] = {}
        for path in full_closure(entry):
            if path in harvested or path in signatures:
                continue
            for name in definitions(text[path]):
                beyond.setdefault(name, path)
        if not beyond:
            continue
        for path in harvested:
            reached = full_closure(path)
            binders = set(re.findall(r"\(\s*([A-Za-z_][A-Za-z0-9_']*)\s*:", text[path]))
            for word, line, previous in code_words(text[path]):
                if previous == "def" or word in available or word in binders or word not in beyond:
                    continue
                if beyond[word] not in reached:
                    continue
                key = (f"{path}:{line}", word, beyond[word])
                reports.setdefault(
                    key,
                    f"CLIPPY_IMPORT_GAP root={entry} use={path}:{line} name={word} stub={beyond[word]}",
                )
    return sorted(reports.values())


def inventory_problems(root: Path, rules: dict[str, tuple[str, ...]]) -> list[str]:
    seen: dict[str, str] = {}
    found: list[str] = []
    for key in ("keep", "exact", "analyze", "impl"):
        for path in rules[key]:
            previous = seen.get(path)
            if previous is not None:
                found.append(
                    f"CLIPPY_IMPORT_OMISSION kind=duplicate-path list={key} path={path} also={previous}"
                )
            else:
                seen[path] = key
            if not (root / path).is_file():
                found.append(f"CLIPPY_IMPORT_OMISSION kind=missing-file list={key} path={path}")
    return found


def function_body(source: str, name: str) -> str | None:
    marker = f"def {name} "
    start = source.find(marker)
    if start < 0:
        return None
    lines = source[start:].splitlines()
    body = [lines[0]]
    for line in lines[1:]:
        if line.startswith("def "):
            break
        body.append(line)
    return "\n".join(body)


def contract_problems(source: str, rules: dict[str, tuple[str, ...]]) -> list[str]:
    body = function_body(source, "cm_import_bound_contracts")
    if body is None:
        return ["CLIPPY_IMPORT_OMISSION kind=contract detail=missing"]
    found: list[str] = []
    calls = list(CONTRACT_CALL_RE.finditer(body))
    if not calls:
        return ["CLIPPY_IMPORT_OMISSION kind=contract detail=unreadable"]
    for call in calls:
        prefix = body[max(0, call.start() - 40):call.start()]
        expect_stub = re.search(r"notb\s*\(\s*$", prefix) is None
        if call.group("kind") == "path":
            path = call.group("a")
            entry = "compiler/root.ouro"
            label = f"cm_skip_import_path path={path}"
        else:
            entry = call.group("a")
            path = call.group("b")
            if path is None:
                return ["CLIPPY_IMPORT_OMISSION kind=contract detail=unreadable"]
            label = f"cm_skip_import_for entry={entry} path={path}"
        actual = stubbed(path, entry, set(), rules)
        if actual != expect_stub:
            found.append(f"CLIPPY_IMPORT_OMISSION kind=contract call={label} stub={actual}")
    return found


def source_tokens(source: str) -> list[tuple[str, str, int, bool]]:
    tokens: list[tuple[str, str, int, bool]] = []
    index = 0
    line = 1
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
                chunk = source[index:len(source) if end < 0 else end]
                line += chunk.count("\n")
                index = len(source) if end < 0 else end + 3
            elif source.startswith('r#"', index):
                end = source.find('"#', index + 3)
                chunk = source[index:len(source) if end < 0 else end]
                line += chunk.count("\n")
                index = len(source) if end < 0 else end + 2
            else:
                quote = source[index]
                index += 1
                while index < len(source) and source[index] != quote:
                    if source[index] == "\n":
                        line += 1
                    index += 2 if source[index] == "\\" else 1
                index += int(index < len(source))
            continue
        match = IDENT_RE.match(source, index)
        if match is not None:
            tokens.append(("w", match.group(0), line, index > 0 and source[index - 1] == "."))
            index = match.end()
            continue
        if source.startswith("=>", index):
            tokens.append(("s", "=>", line, False))
            index += 2
            continue
        if source.startswith(":=", index):
            tokens.append(("s", ":=", line, False))
            index += 2
            continue
        tokens.append(("s", source[index], line, False))
        index += 1
    return tokens


def module_facts(source: str) -> tuple[set[str], dict[str, tuple[str, ...]]]:
    public: set[str] = set()
    inductives: dict[str, tuple[str, ...]] = {}
    lines = source.splitlines()
    index = 0
    while index < len(lines):
        match = DECL_HEAD_RE.match(lines[index])
        if match is None:
            index += 1
            continue
        private = match.group(1) is not None
        kind = match.group(2)
        name = match.group(3)
        if not private:
            public.add(name)
        if kind != "inductive":
            index += 1
            continue
        body = [lines[index]]
        index += 1
        while index < len(lines) and NEXT_DECL_RE.match(lines[index]) is None:
            body.append(lines[index])
            index += 1
            if body[-1].rstrip().endswith(";") and not body[-1].lstrip().startswith("|"):
                break
        ctors = tuple(item.group(1) for item in CTOR_RE.finditer("\n".join(body)))
        if ctors:
            inductives[name] = ctors
            if not private:
                public.update(ctors)
    return public, inductives


def repo_sources(root: Path) -> list[str]:
    found: list[str] = []
    for path in root.rglob("*.ouro"):
        relative = path.relative_to(root).as_posix()
        if relative.startswith(("compiler/stage0/", "_build/", "_cache/")) or "/_build/" in relative:
            continue
        found.append(relative)
    if not found:
        raise GapError("repository contains no Ouro sources")
    return sorted(found)


def binder_and_matches(
    tokens: list[tuple[str, str, int, bool]], constructors: set[str]
) -> tuple[set[str], list[tuple[str, int]], list[tuple[int, list[str]]]]:
    binders: set[str] = set()
    matches: list[tuple[int, list[str]]] = []
    pattern_at: set[int] = set()
    index = 0
    count = len(tokens)
    while index < count:
        kind, text, line, dotted = tokens[index]
        if kind == "w" and text in DECL_WORDS and not dotted and index + 1 < count and tokens[index + 1][0] == "w":
            binders.add(tokens[index + 1][1])
        if kind == "w" and text == "let" and not dotted:
            cursor = index + 1
            if cursor < count and tokens[cursor][1] == "!":
                cursor += 1
            if cursor < count and tokens[cursor][0] == "w":
                binders.add(tokens[cursor][1])
        if kind == "w" and text in ("fix", "as") and not dotted and index + 1 < count and tokens[index + 1][0] == "w":
            binders.add(tokens[index + 1][1])
        if kind == "w" and text == "fun" and not dotted:
            cursor = index + 1
            if cursor < count and tokens[cursor][1] == "(":
                cursor += 1
            if cursor < count and tokens[cursor][0] == "w":
                binders.add(tokens[cursor][1])
        if kind == "s" and text == "(" and index + 2 < count and tokens[index + 1][0] == "w" and tokens[index + 2][1] == ":":
            binders.add(tokens[index + 1][1])
        if kind == "w" and text in ("match", "handle") and not dotted:
            cursor = index + 1
            nested = 0
            while cursor < count:
                token_kind, token_text, _token_line, _token_dotted = tokens[cursor]
                if token_kind == "w" and token_text == "match":
                    nested += 1
                elif token_kind == "w" and token_text == "with" and nested == 0:
                    break
                elif token_kind == "w" and token_text == "end" and nested:
                    nested -= 1
                cursor += 1
            else:
                index += 1
                continue
            arms: list[str] = []
            cursor += 1
            depth = 0
            while cursor < count:
                token_kind, token_text, _token_line, _token_dotted = tokens[cursor]
                if token_kind == "w" and token_text == "match":
                    depth += 1
                elif token_kind == "w" and token_text == "end":
                    if depth == 0:
                        break
                    depth -= 1
                elif depth == 0 and token_kind == "s" and token_text == "|":
                    if cursor + 1 < count and tokens[cursor + 1][0] == "w":
                        arms.append(tokens[cursor + 1][1])
                    elif cursor + 1 < count and tokens[cursor + 1][1] == "_":
                        arms.append("_")
                    else:
                        arms.append("?")
                    look = cursor + 1
                    parentheses = 0
                    expect_constructor = True
                    while look < count:
                        look_kind, look_text, _look_line, _look_dotted = tokens[look]
                        pattern_at.add(look)
                        if look_kind == "s" and look_text == "(":
                            parentheses += 1
                            expect_constructor = True
                        elif look_kind == "s" and look_text == ")":
                            parentheses = max(0, parentheses - 1)
                            expect_constructor = False
                        elif look_kind == "s" and look_text == "=>" and parentheses == 0:
                            break
                        elif look_kind == "w":
                            if not (expect_constructor and look_text in constructors):
                                binders.add(look_text)
                            expect_constructor = False
                        look += 1
                cursor += 1
            matches.append((line, arms))
        index += 1
    uses = []
    for index, (kind, text, line, dotted) in enumerate(tokens):
        if kind != "w" or dotted or index in pattern_at or text in KEYWORDS or text in DECL_WORDS:
            continue
        if index + 1 < count and tokens[index + 1][1] in (":", ":="):
            continue
        uses.append((text, line))
    return binders, uses, matches


def read_tree(root: Path, files: list[str]) -> tuple[dict[str, str], dict[str, list[str]]]:
    text: dict[str, str] = {}
    imports: dict[str, list[str]] = {}
    for path in files:
        source = read_source(root, path)
        text[path] = source
        imports[path] = quoted_import_targets(source, path)
    return text, imports


def omission_scan(root: Path, checked: list[str]) -> list[str]:
    files = repo_sources(root)
    text, imports = read_tree(root, files)
    public: dict[str, set[str]] = {}
    shapes: dict[str, set[tuple[str, ...]]] = {}
    ctor_owner: dict[str, str] = {}
    ambiguous: set[str] = set()
    for path in files:
        names, inductives = module_facts(text[path])
        for name in names:
            public.setdefault(name, set()).add(path)
        for inductive, ctors in inductives.items():
            shapes.setdefault(inductive, set()).add(ctors)
            for ctor in ctors:
                previous = ctor_owner.get(ctor)
                if previous is not None and previous != inductive:
                    ambiguous.add(ctor)
                ctor_owner[ctor] = inductive
    conflicts = {name for name, rows in shapes.items() if len(rows) != 1}
    constructors = set(ctor_owner)
    closures: dict[str, set[str]] = {}

    def closure(path: str) -> set[str]:
        cached = closures.get(path)
        if cached is not None:
            return cached
        seen: set[str] = set()
        pending = [path]
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            if current not in text:
                raise GapError(f"import target is missing: {current}")
            seen.add(current)
            pending.extend(imports[current])
        closures[path] = seen
        return seen

    reports: dict[tuple[str, str, str], str] = {}
    for path in checked:
        if path not in text:
            raise GapError(f"import target is missing: {path}")
        binders, uses, matches = binder_and_matches(source_tokens(text[path]), constructors)
        reached = closure(path)
        available = {name for name, owners in public.items() if owners & reached}
        seen_names: set[tuple[str, str]] = set()
        for name, line in uses:
            if name in binders or name in available:
                continue
            owners = public.get(name)
            if owners is None or len(owners) != 1:
                continue
            owner = next(iter(owners))
            if owner in reached:
                continue
            key = (path, name, owner)
            if key in seen_names:
                continue
            seen_names.add(key)
            reports[(f"{path}:{line}", name, owner)] = (
                f"CLIPPY_IMPORT_OMISSION kind=forgotten-import use={path}:{line} name={name} owner={owner}"
            )
        for line, arms in matches:
            if not arms or any(arm in ("_", "?") or arm in ambiguous or arm not in ctor_owner for arm in arms):
                continue
            owners = {ctor_owner[arm] for arm in arms}
            if len(owners) != 1:
                continue
            inductive = next(iter(owners))
            if inductive in conflicts:
                continue
            expected = set(next(iter(shapes[inductive])))
            if len(expected) < 4:
                continue
            have = set(arms)
            if not have <= expected:
                continue
            missing = expected - have
            if not missing or len(missing) > 2 or len(have) < len(expected) - 2:
                continue
            for ctor in sorted(missing):
                reports[(f"{path}:{line}", inductive, ctor)] = (
                    f"CLIPPY_IMPORT_OMISSION kind=match-arm use={path}:{line} inductive={inductive} missing={ctor}"
                )
    return sorted(reports.values())


def scan(root: Path) -> list[str]:
    unit = (root / "tools/clippy/semantic_unit.ouro").read_text(encoding="utf-8")
    rules = load_rules(unit)
    roots = production_roots(root)
    found = gaps_for(root, rules, roots)
    found.extend(inventory_problems(root, rules))
    found.extend(contract_problems(unit, rules))
    found.extend(omission_scan(root, roots))
    return sorted(set(found))


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
            "def main : Nat := add (process_spawn deeper_only) base_value;\n",
            encoding="utf-8",
        )
        (root / "std/deeper.ouro").write_text("def deeper_only : Nat := Z;\n", encoding="utf-8")
        (root / "std/hidden.ouro").write_text(
            'import "deeper.ouro";\ndef hidden_only : Nat := Z;\n',
            encoding="utf-8",
        )
        (root / "std/process.ouro").write_text(
            'import "hidden.ouro";\ndef process_spawn (n : Nat) : Nat := n;\n',
            encoding="utf-8",
        )
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
            "name=deeper_only stub=std/deeper.ouro",
            "CLIPPY_IMPORT_GAP root=compiler/root.ouro use=compiler/root.ouro:2 "
            "name=process_spawn stub=std/process.ouro",
        ]:
            failures.append("stubbed declarations were not reported exactly: " + repr(found))
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
        overlap = {
            "keep": ("compiler/base.ouro",),
            "exact": ("compiler/base.ouro", "compiler/missing.ouro"),
            "analyze": (),
            "impl": (),
        }
        listed = inventory_problems(root, overlap)
        if listed != [
            "CLIPPY_IMPORT_OMISSION kind=duplicate-path list=exact path=compiler/base.ouro also=keep",
            "CLIPPY_IMPORT_OMISSION kind=missing-file list=exact path=compiler/missing.ouro",
        ]:
            failures.append("stub list overlap was not reported exactly: " + repr(listed))
        wrong_contract = 'def cm_import_bound_contracts : Bool :=\n    notb (cm_skip_import_path "std/process.ouro");\n'
        contracts = contract_problems(wrong_contract, rules)
        if contracts != [
            "CLIPPY_IMPORT_OMISSION kind=contract call=cm_skip_import_path path=std/process.ouro stub=True"
        ]:
            failures.append("contract drift was not reported exactly: " + repr(contracts))
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "std").mkdir()
        (root / "compiler").mkdir()
        (root / "std/remote.ouro").write_text("def only_remote : Nat := Z;\ndef x : Nat := Z;\n", encoding="utf-8")
        (root / "compiler/forgot.ouro").write_text("def main : Nat := only_remote;\n", encoding="utf-8")
        (root / "compiler/bound.ouro").write_text(
            "def main : Nat :=\n  do let! only_remote := Z;\n     only_remote;\n",
            encoding="utf-8",
        )
        (root / "compiler/quoted.ouro").write_text(
            'def text : String := "only_remote";\n',
            encoding="utf-8",
        )
        (root / "compiler/imported.ouro").write_text(
            'import "../std/remote.ouro";\ndef main : Nat := only_remote;\n',
            encoding="utf-8",
        )
        (root / "compiler/gate.ouro").write_text(
            "inductive Gate : Type :=\n"
            "  | GateOpen : Gate\n"
            "  | GateClosed : Gate\n"
            "  | GateLocked : Gate\n"
            "  | GateBroken : Gate;\n"
            "inductive Bit : Type :=\n"
            "  | BitOn : Bit\n"
            "  | BitOff : Bit;\n"
            "def full (g : Gate) : Nat :=\n"
            "  match g with\n"
            "  | GateOpen => Z\n"
            "  | GateClosed => Z\n"
            "  | GateLocked => Z\n"
            "  | GateBroken => Z\n"
            "  end;\n"
            "def forgot (g : Gate) : Nat :=\n"
            "  match g with\n"
            "  | GateOpen => Z\n"
            "  | GateClosed => Z\n"
            "  | GateLocked => Z\n"
            "  end;\n"
            "def partial (g : Gate) : Nat :=\n"
            "  match g with\n"
            "  | GateOpen => Z\n"
            "  end;\n"
            "def caught (g : Gate) : Nat :=\n"
            "  match g with\n"
            "  | GateOpen => Z\n"
            "  | _ => Z\n"
            "  end;\n"
            "def bit (b : Bit) : Nat :=\n"
            "  match b with\n"
            "  | BitOn => Z\n"
            "  end;\n",
            encoding="utf-8",
        )
        (root / "compiler/labels.ouro").write_text(
            "record Point : Type where\n  x : Nat;\nend;\n"
            "def origin : Point := { x := Z };\n"
            "def run : Nat :=\n  handle perform read Z with\n"
            "  | read n k => k n\n"
            "  | pure x => x\n"
            "  end;\n",
            encoding="utf-8",
        )
        found = omission_scan(
            root,
            [
                "compiler/forgot.ouro",
                "compiler/bound.ouro",
                "compiler/quoted.ouro",
                "compiler/imported.ouro",
                "compiler/gate.ouro",
                "compiler/labels.ouro",
            ],
        )
        expected = [
            "CLIPPY_IMPORT_OMISSION kind=forgotten-import use=compiler/forgot.ouro:1 name=only_remote owner=std/remote.ouro",
            "CLIPPY_IMPORT_OMISSION kind=match-arm use=compiler/gate.ouro:17 inductive=Gate missing=GateBroken",
        ]
        if found != expected:
            failures.append("omissions were not reported exactly: " + repr(found))
    try:
        real_source = UNIT.read_text(encoding="utf-8")
        real_rules = load_rules(real_source)
    except GapError as error:
        failures.append(str(error))
    else:
        real_listed = inventory_problems(ROOT, real_rules) + contract_problems(real_source, real_rules)
        if real_listed:
            failures.append("checked inventories disagree: " + repr(real_listed[:8]))
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
        omissions = [line for line in found if line.startswith("CLIPPY_IMPORT_OMISSION ")]
        for line in omissions[:40]:
            print(line)
        if len(omissions) > 40:
            print(f"CLIPPY_IMPORT_OMISSION ... {len(omissions) - 40} more")
        grouped: dict[str, list[str]] = {}
        for line in found:
            if line.startswith("CLIPPY_IMPORT_OMISSION "):
                continue
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
            "CLIPPY_IMPORT_GAP: FAIL "
            f"omissions={len(omissions)} stubs={len(grouped)} uses={len(found) - len(omissions)} shown={shown}",
            file=sys.stderr,
        )
        return 1
    print("CLIPPY_IMPORT_GAP: PASS gaps=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
