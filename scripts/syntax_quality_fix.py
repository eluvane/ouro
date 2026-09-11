#!/usr/bin/env python3
"""Mechanical canonical-syntax fixer for safe Ouro surface rewrites.

The fixer is intentionally conservative. It only rewrites forms with a local,
syntax-only replacement: duplicate imports, old do-bind spelling, redundant
separators, closed Cons/Nil chains, and pure Peano numeral towers.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
IMPORT_LINE_RE = re.compile(r'^(?P<indent>\s*)import\s+"(?P<path>[^"]+)"(?P<alias>\s+as\s+[A-Za-z_][A-Za-z0-9_\']*)?\s*;(?P<trail>\s*(?:--.*)?)$')
DEF_LIST_RE = re.compile(r'(?ms)^(?P<indent>[ \t]*)def\s+(?P<name>[A-Za-z_][A-Za-z0-9_\']*)\s*:\s*List\s+(?P<typ>[A-Za-z_][A-Za-z0-9_\']*)\s*:=\s*(?P<body>.*?);(?P<trail>[ \t]*(?:--[^\n]*)?)$')
OLD_DO_RE = re.compile(r'\bdo\s+([A-Za-z_][A-Za-z0-9_\']*)\s*<-\s*([^;\n]+);')
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_']*$")
NIL_BINDING_RE = re.compile(r":=\s*Nil\s+([A-Za-z_][A-Za-z0-9_']*)\s*(?P<semi>;?)(?P<trail>\s*(?:--.*)?)?$")


class ClosedCons(NamedTuple):
    start: int
    end: int
    typ: str
    elems: list[str]


def strip_outer_parens(s: str) -> str:
    s = s.strip()
    while s.startswith("(") and s.endswith(")"):
        depth = 0
        ok = True
        in_str: Optional[str] = None
        esc = False
        for i, ch in enumerate(s):
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == in_str:
                    in_str = None
                continue
            if ch in {'"', "'"}:
                in_str = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i != len(s) - 1:
                    ok = False
                    break
        if ok:
            s = s[1:-1].strip()
        else:
            break
    return s


def tokenize_expr_spans(s: str) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch.isspace():
            i += 1
            continue
        if s.startswith("--", i):
            while i < len(s) and s[i] != "\n":
                i += 1
            continue
        if ch in "()":
            out.append((ch, i, i + 1))
            i += 1
            continue
        if ch == '"':
            j = i + 1
            esc = False
            while j < len(s):
                cj = s[j]
                if esc:
                    esc = False
                elif cj == "\\":
                    esc = True
                elif cj == '"':
                    j += 1
                    break
                j += 1
            out.append((s[i:j], i, j))
            i = j
            continue
        j = i
        while j < len(s) and not s[j].isspace() and s[j] not in "()":
            j += 1
        out.append((s[i:j], i, j))
        i = j
    return out


def tokenize_expr(s: str) -> list[str]:
    return [tok for tok, _start, _end in tokenize_expr_spans(s)]


def untok(tokens: list[str]) -> str:
    s = " ".join(tokens)
    s = s.replace("( ", "(").replace(" )", ")")
    return s


def parse_one(tokens: list[str], i: int) -> tuple[list[str], int] | None:
    if i >= len(tokens):
        return None
    if tokens[i] != "(":
        return [tokens[i]], i + 1
    depth = 0
    j = i
    while j < len(tokens):
        if tokens[j] == "(":
            depth += 1
        elif tokens[j] == ")":
            depth -= 1
            if depth == 0:
                return tokens[i:j + 1], j + 1
        j += 1
    return None


def parse_one_span(tokens: list[tuple[str, int, int]], i: int) -> tuple[list[tuple[str, int, int]], int] | None:
    if i >= len(tokens):
        return None
    if tokens[i][0] != "(":
        return [tokens[i]], i + 1
    depth = 0
    j = i
    while j < len(tokens):
        if tokens[j][0] == "(":
            depth += 1
        elif tokens[j][0] == ")":
            depth -= 1
            if depth == 0:
                return tokens[i:j + 1], j + 1
        j += 1
    return None


def _elem_source(source: str, elem: list[tuple[str, int, int]]) -> str:
    raw = source[elem[0][1]:elem[-1][2]]
    return strip_outer_parens(raw)


def parse_closed_cons_from(
    source: str, tokens: list[tuple[str, int, int]], i: int, typ: str
) -> tuple[list[str], int] | None:
    if i >= len(tokens):
        return None
    if tokens[i][0] == "Nil" and i + 1 < len(tokens) and tokens[i + 1][0] == typ:
        return [], i + 2
    if tokens[i][0] != "Cons" or i + 1 >= len(tokens) or tokens[i + 1][0] != typ:
        return None
    elem = parse_one_span(tokens, i + 2)
    if elem is None:
        return None
    elem_toks, j = elem
    if j >= len(tokens):
        return None
    if tokens[j][0] == "(":
        inner = parse_one_span(tokens, j)
        if inner is None:
            return None
        inner_toks, k = inner
        body = inner_toks[1:-1]
        rec = parse_closed_cons_from(source, body, 0, typ)
        if rec is None:
            return None
        tail_elems, consumed = rec
        if consumed != len(body):
            return None
        return [_elem_source(source, elem_toks)] + tail_elems, k
    rec = parse_closed_cons_from(source, tokens, j, typ)
    if rec is None:
        return None
    tail_elems, k = rec
    return [_elem_source(source, elem_toks)] + tail_elems, k


def find_closed_cons_spans(line: str) -> list[ClosedCons]:
    """Find closed `Cons T e (Nil T)` chains. Algorithmic tails are ignored."""
    tokens = tokenize_expr_spans(line)
    hits: list[ClosedCons] = []
    i = 0
    while i < len(tokens):
        if tokens[i][0] == "Cons" and i + 1 < len(tokens) and IDENT_RE.match(tokens[i + 1][0]):
            typ = tokens[i + 1][0]
            parsed = parse_closed_cons_from(line, tokens, i, typ)
            if parsed is not None:
                elems, k = parsed
                start = tokens[i][1]
                end = tokens[k - 1][2]
                hits.append(ClosedCons(start, end, typ, elems))
                i = k
                continue
        i += 1
    return hits


def rewrite_closed_cons_line(line: str) -> str:
    hits = find_closed_cons_spans(line)
    if not hits:
        return NIL_BINDING_RE.sub(lambda m: f":= []{m.group('semi')}{m.group('trail') or ''}", line) if NIL_BINDING_RE.search(line) else line
    out = line
    for hit in reversed(hits):
        literal = "[" + ", ".join(hit.elems) + "]"
        out = out[:hit.start] + literal + out[hit.end:]
    return out


def rewrite_nil_bindings(text: str) -> str:
    parts: list[str] = []
    for raw in text.splitlines(keepends=True):
        newline = "\n" if raw.endswith("\n") else ""
        line = raw[:-1] if raw.endswith("\n") else raw
        if not find_closed_cons_spans(line):
            line = NIL_BINDING_RE.sub(lambda m: f":= []{m.group('semi')}{m.group('trail') or ''}", line)
        parts.append(line + newline)
    return "".join(parts)


def rewrite_closed_cons_text(text: str) -> str:
    hits = find_closed_cons_spans(text)
    out = text
    for hit in reversed(hits):
        literal = "[" + ", ".join(hit.elems) + "]"
        out = out[:hit.start] + literal + out[hit.end:]
    return rewrite_nil_bindings(out)


def _skip_ws(s: str, i: int) -> int:
    while i < len(s) and s[i].isspace():
        i += 1
    return i


def _at_ident(s: str, i: int, name: str) -> bool:
    if not s.startswith(name, i):
        return False
    end = i + len(name)
    if end < len(s) and (s[end].isalnum() or s[end] in "_'"):
        return False
    if i > 0 and (s[i - 1].isalnum() or s[i - 1] in "_'"):
        return False
    return True


def _parse_ident(s: str, i: int) -> tuple[str, int] | None:
    i = _skip_ws(s, i)
    if i >= len(s) or not (s[i].isalpha() or s[i] == "_"):
        return None
    j = i + 1
    while j < len(s) and (s[j].isalnum() or s[j] in "_'"):
        j += 1
    return s[i:j], j


def parse_peano_tower(s: str, i: int) -> tuple[int | str, int] | None:
    """Parse `S (S (... Z|ident))`. Does not consume surrounding parens."""
    i = _skip_ws(s, i)
    if not _at_ident(s, i, "S"):
        return None
    i += 1
    i = _skip_ws(s, i)
    if _at_ident(s, i, "Z"):
        return 1, i + 1
    ident = _parse_ident(s, i)
    if ident is not None and ident[0] not in {"S", "Z"}:
        return ident[0], ident[1]
    if i < len(s) and s[i] == "(":
        inner = parse_peano_tower(s, i + 1)
        if inner is None:
            return None
        value, j = inner
        j = _skip_ws(s, j)
        if j >= len(s) or s[j] != ")":
            return None
        if isinstance(value, int):
            return value + 1, j + 1
        return value, j + 1  # keep ident; count S via wrapper depth below
    return None


def parse_peano_var_tower(s: str, i: int) -> tuple[str, int, int] | None:
    """Parse `S (S (S x))` and return (var, s_count, end)."""
    depth = 0
    j = _skip_ws(s, i)
    while _at_ident(s, j, "S"):
        j += 1
        j = _skip_ws(s, j)
        if j >= len(s) or s[j] != "(":
            return None
        depth += 1
        j += 1
        j = _skip_ws(s, j)
    ident = _parse_ident(s, j)
    if ident is None or ident[0] in {"S", "Z"}:
        return None
    name, j = ident
    for _ in range(depth):
        j = _skip_ws(s, j)
        if j >= len(s) or s[j] != ")":
            return None
        j += 1
    if depth < 3:
        return None
    return name, depth, j


def rewrite_peano_line(line: str) -> str:
    code, sep, comment = line.partition("--")
    out: list[str] = []
    i = 0
    while i < len(code):
        if _at_ident(code, i, "S"):
            var = parse_peano_var_tower(code, i)
            if var is not None:
                name, depth, end = var
                out.append(name + " |> " + " |> ".join(["S"] * depth))
                i = end
                continue
            parsed = parse_peano_tower(code, i)
            if parsed is not None and isinstance(parsed[0], int) and parsed[0] >= 3:
                out.append(str(parsed[0]))
                i = parsed[1]
                continue
        out.append(code[i])
        i += 1
    return "".join(out) + sep + comment if sep else "".join(out)


def rewrite_peano_text(text: str) -> str:
    parts: list[str] = []
    for raw in text.splitlines(keepends=True):
        newline = "\n" if raw.endswith("\n") else ""
        line = raw[:-1] if raw.endswith("\n") else raw
        parts.append(rewrite_peano_line(line) + newline)
    return "".join(parts)


def parse_cons_tokens(tokens: list[str], typ: str) -> list[str] | None:
    if len(tokens) == 2 and tokens[0] == "Nil" and tokens[1] == typ:
        return []
    if len(tokens) < 4 or tokens[0] != "Cons" or tokens[1] != typ:
        return None
    elem = parse_one(tokens, 2)
    if elem is None:
        return None
    elem_tokens, next_i = elem
    tail_tokens = tokens[next_i:]
    if not tail_tokens:
        return None
    if tail_tokens[0] == "(" and tail_tokens[-1] == ")":
        tail_tokens = tail_tokens[1:-1]
    tail = parse_cons_tokens(tail_tokens, typ)
    if tail is None:
        return None
    return [strip_outer_parens(untok(elem_tokens))] + tail


def cons_chain_to_literal(body: str, typ: str) -> str | None:
    tokens = tokenize_expr(strip_outer_parens(body))
    elems = parse_cons_tokens(tokens, typ)
    if elems is None:
        return None
    return "[" + ", ".join(elems) + "]"


def rewrite_list_defs(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        literal = cons_chain_to_literal(m.group("body"), m.group("typ"))
        if literal is None:
            return m.group(0)
        return f'{m.group("indent")}def {m.group("name")} : List {m.group("typ")} := {literal};{m.group("trail")}'
    return DEF_LIST_RE.sub(repl, text)


def rewrite_do_bind(text: str) -> str:
    return OLD_DO_RE.sub(lambda m: f"do let! {m.group(1)} := {m.group(2).strip()};", text)


def rewrite_redundant_separators(text: str) -> str:
    return re.sub(r';;+(?=\s*(?:\n|$|--))', ';', text)


def rewrite_duplicate_imports(text: str) -> str:
    seen: set[str] = set()
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        body = line[:-1] if line.endswith("\n") else line
        newline = "\n" if line.endswith("\n") else ""
        m = IMPORT_LINE_RE.match(body)
        if m:
            key = m.group("path")
            if key in seen:
                continue
            seen.add(key)
        out.append(body + newline)
    return "".join(out)


def rewrite_text(text: str) -> str:
    out = rewrite_duplicate_imports(text)
    out = rewrite_redundant_separators(out)
    out = rewrite_do_bind(out)
    out = rewrite_list_defs(out)
    out = rewrite_closed_cons_text(out)
    out = rewrite_peano_text(out)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="fail if a file would change")
    ap.add_argument("--write", action="store_true", help="rewrite files in place")
    ap.add_argument("files", nargs="+")
    args = ap.parse_args(argv)
    if args.check and args.write:
        ap.error("--check and --write are mutually exclusive")
    changed = False
    for raw in args.files:
        path = Path(raw)
        text = path.read_text(encoding="utf-8")
        new = rewrite_text(text)
        if new != text:
            changed = True
            if args.write:
                path.write_text(new, encoding="utf-8")
                print(f"SYNTAX_FIX_WRITE {path}")
            elif args.check:
                print(f"SYNTAX_FIX_NEEDED {path}", file=sys.stderr)
            else:
                sys.stdout.write(new)
        elif not args.check and not args.write:
            sys.stdout.write(text)
    return 1 if args.check and changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
