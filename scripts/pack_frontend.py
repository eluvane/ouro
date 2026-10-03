#!/usr/bin/env python3
"""Prefix generated ouro_g/f/t/c symbols per frontend TU and concatenate.

Each --module SUFFIX blob has its own static ouro_gN table. Concatenating
without a prefix collides those statics. Sibling match-arm helpers can also
reuse the same ouro_f/t path name inside one TU; uniquify those like O8.

Type-app / ctor-field erasure belongs in extract.ouro normalize_ir.
This packer does not rewrite language IR: it only prefixes statics and
uniquifies colliding helper names. --strict dry-runs leftover detectors
and fails if extract left Type apps or extra ctor fields behind.

Runtime helpers (ouro_ctor, ouro_app, …) are left untouched. Export tables
stay ouro_export_*_SUFFIX so the C pipeline glue can look them up.

Usage:
  python3 scripts/pack_frontend.py -o compiler/stage0/driver_u.c \\
      lx:_build/fe/lx.c pa:_build/fe/pa.c ...
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SYM = re.compile(r"\bouro_([gftc]\d\w*)")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
STATIC_DEF = re.compile(
    r"static ouro_v \*([A-Za-z_][A-Za-z0-9_]*)\s*\([^;{]*\)\s*\{"
)
CASE_NAME = re.compile(r'case\s+(\d+)\s*:\s*return\s+"([^"]+)"\s*;')
CASE_VAL = re.compile(
    r"case\s+(\d+)\s*:\s*return\s+(ouro_g\d+)\s*\(\s*\)\s*;"
)

# Compiled value arity after Type binders are erased.
# Source shapes (Type binders dropped):
#   bindParseResult A B r f          -> r f
#   bindValue A f r cont             -> f r cont
#   map A B f xs / append A xs ys    -> f xs / xs ys
#   isJust A m / isNothing A m       -> m
POLY_VALUE_ARITY = {
    "bindParseResult": 2,
    "bindValue": 3,
    "map": 2,
    "append": 2,
    "length": 1,
    "foldr": 3,
    "fst": 1,
    "snd": 1,
    "maybe": 3,
    "fromMaybe": 2,
    "mapMaybe": 2,
    "either": 3,
    "mapLeft": 2,
    "mapRight": 2,
    "reverse": 1,
    "filter": 2,
    "zip": 2,
    "elem": 3,
    "take": 2,
    "drop": 2,
    "isJust": 1,
    "isNothing": 1,
    "nth": 2,
}


def _replace_spans(src: str, replacements: list[tuple[int, int, str]]) -> str:
    """Apply disjoint source spans once, retaining the first duplicate span."""
    if not replacements:
        return src
    pieces = []
    seen: set[tuple[int, int]] = set()
    cursor = len(src)
    for start, end, replacement in sorted(replacements, key=lambda item: item[0], reverse=True):
        if (start, end) in seen:
            continue
        if not 0 <= start <= end <= cursor:
            raise ValueError(f"pack_frontend: invalid or overlapping replacement span {start}:{end}")
        seen.add((start, end))
        pieces.extend((src[end:cursor], replacement))
        cursor = start
    pieces.append(src[:cursor])
    return "".join(reversed(pieces))


def uniquify(src: str) -> str:
    """Rename colliding static function bodies with scoped use-binding.

    Uses between def_i and def_{i+1} bind to version i. Uses after the last
    def are assigned to versions in order so a trailing ouro_case that names
    sibling arms does not collapse every slot onto _dN (print_c emits the
    arms, maybe some mid-parents, then a later case that lists them).
    """
    from collections import defaultdict

    defs = list(STATIC_DEF.finditer(src))
    by_name: dict[str, list[re.Match[str]]] = defaultdict(list)
    for m in defs:
        by_name[m.group(1)].append(m)
    dups = {n: ms for n, ms in by_name.items() if len(ms) > 1}
    if not dups:
        return spread_case_arms(src)
    uses_by_name: dict[str, list[re.Match[str]]] = {name: [] for name in dups}
    for match in IDENT.finditer(src):
        uses = uses_by_name.get(match.group(0))
        if uses is not None:
            uses.append(match)
    repls: list[tuple[int, int, str]] = []
    for name, ms in dups.items():
        for i, m in enumerate(ms):
            if i:
                repls.append((m.start(1), m.end(1), f"{name}_d{i + 1}"))
        bounds = [m.start(1) for m in ms] + [len(src)]
        def_spans = {(m.start(1), m.end(1)) for m in ms}
        nver = len(ms)
        uses = [
            m
            for m in uses_by_name[name]
            if (m.start(), m.end()) not in def_spans
        ]
        has_between = any(
            bounds[0] <= u.start() < bounds[nver - 1] for u in uses
        )
        later_i = 0
        for m in uses:
            pos = m.start()
            if has_between:
                ver = 0
                for i in range(nver):
                    if bounds[i] <= pos < bounds[i + 1]:
                        ver = i
                        break
            else:
                ver = later_i if later_i < nver else nver - 1
                later_i += 1
            if ver:
                repls.append((m.start(), m.end(), f"{name}_d{ver + 1}"))
    return spread_case_arms(_replace_spans(src, repls))


_ARM_REF = re.compile(
    r"ouro_(?:thunk|clos)\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,"
    r"|([A-Za-z_][A-Za-z0-9_]*)\s*(?=,|\})"
)
_D_SUFFIX = re.compile(r"_d(\d+)$")
_CASE_ARR_MARK = "(ouro_v *[]){"


def _base_ver(name: str) -> tuple[str, int]:
    m = _D_SUFFIX.search(name)
    if not m:
        return name, 1
    return name[: m.start()], int(m.group(1))


def _iter_case_arrays(src: str):
    """Yield (body_start, body_end, body) for each ouro_case arm array."""
    start = 0
    while True:
        j = src.find("ouro_case(", start)
        if j < 0:
            return
        k = src.find(_CASE_ARR_MARK, j)
        if k < 0:
            return
        if k - j > 4000:
            start = j + 10
            continue
        body_s = k + len(_CASE_ARR_MARK)
        depth = 1
        p = body_s
        while p < len(src) and depth:
            ch = src[p]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            p += 1
        if depth != 0:
            start = j + 10
            continue
        body_e = p - 1
        yield body_s, body_e, src[body_s:body_e]
        start = p


def spread_case_arms(src: str) -> str:
    """Give colliding ouro_case arm refs distinct uniquify versions.

    print_c can emit sibling thunks with the same path. After uniquify they
    become foo / foo_d2, but both case slots may still name foo_dN. Spread
    repeated base names across the versions that actually exist, skipping
    the enclosing function so a parent is never used as both of its arms.
    """
    defined: dict[str, set[int]] = {}
    for m in STATIC_DEF.finditer(src):
        base, ver = _base_ver(m.group(1))
        defined.setdefault(base, set()).add(ver)
    repls: list[tuple[int, int, str]] = []
    for body_s, _body_e, body in _iter_case_arrays(src):
        hits: dict[str, list[re.Match[str]]] = {}
        for am in _ARM_REF.finditer(body):
            name = am.group(1) or am.group(2)
            if not name or name in ("ouro_v",):
                continue
            # Runtime helpers are never match-arm bodies.
            if name in (
                "ouro_thunk",
                "ouro_clos",
                "ouro_app",
                "ouro_ctor",
                "ouro_get",
                "ouro_case",
                "ouro_err",
                "ouro_nat",
                "ouro_bytes",
                "ouro_packed",
            ):
                continue
            base, _ = _base_ver(name)
            hits.setdefault(base, []).append(am)
        for base, arms in hits.items():
            if len(arms) < 2:
                continue
            olds = [(am.group(1) or am.group(2)) for am in arms]
            if len(set(olds)) == len(olds):
                # Already distinct versions — do not reshuffle.
                continue
            # Both (or all) arms still name the same version. print_c reused
            # the path across nested False-arm matches, so uniquify parked
            # every after-last slot on _dN. The last version is the
            # continuation (next match / default); the previous version is
            # the True arm that was just defined.
            if len(set(olds)) == 1 and len(olds) == 2:
                old = olds[0]
                _b, ver = _base_ver(old)
                prev_ver = ver - 1
                if prev_ver >= 1 and prev_ver in defined.get(base, set()):
                    prev = base if prev_ver == 1 else f"{base}_d{prev_ver}"
                    am = arms[0]
                    if am.group(1):
                        s = am.start(1) + body_s
                        e = am.end(1) + body_s
                    else:
                        s = am.start(2) + body_s
                        e = am.end(2) + body_s
                    if prev != old:
                        repls.append((s, e, prev))
                continue
            # Mixed duplicates: leave unique arms, spread the rest onto
            # unused versions ending at the last def.
            vers = sorted(defined.get(base, {1}))
            if len(vers) < 2:
                continue
            taken = set()
            unique_vers = []
            for old in olds:
                _, v = _base_ver(old)
                if olds.count(old) == 1:
                    taken.add(v)
                    unique_vers.append(v)
                else:
                    unique_vers.append(None)
            unused = [v for v in vers if v not in taken]
            ui = 0
            for i, am in enumerate(arms):
                if unique_vers[i] is not None:
                    continue
                if ui < len(unused):
                    ver = unused[ui]
                    ui += 1
                else:
                    ver = vers[-1]
                new = base if ver == 1 else f"{base}_d{ver}"
                old = olds[i]
                if new == old:
                    continue
                if am.group(1):
                    s = am.start(1) + body_s
                    e = am.end(1) + body_s
                else:
                    s = am.start(2) + body_s
                    e = am.end(2) + body_s
                repls.append((s, e, new))
    return _replace_spans(src, repls)


def uniquify_file(path: str | Path) -> int:
    """In-place uniquify (backend emit / stage_loop). Returns 1 if rewritten."""
    p = Path(path)
    try:
        src = p.read_text(encoding="utf-8", errors="surrogateescape")
    except OSError as exc:
        raise SystemExit(f"pack_frontend: cannot read {p}: {exc}") from exc
    out = uniquify(src)
    if out == src:
        return 0
    try:
        p.write_text(out, encoding="utf-8", errors="surrogateescape")
    except OSError as exc:
        raise SystemExit(f"pack_frontend: cannot write {p}: {exc}") from exc
    return 1


def _match_paren(src: str, i: int) -> int:
    if i >= len(src) or src[i] != "(":
        return -1
    depth = 0
    j = i
    while j < len(src):
        ch = src[j]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return -1


def _export_gmap(src: str) -> dict[str, str]:
    names: dict[int, str] = {}
    vals: dict[int, str] = {}
    for m in CASE_NAME.finditer(src):
        names[int(m.group(1))] = m.group(2)
    for m in CASE_VAL.finditer(src):
        vals[int(m.group(1))] = m.group(2)
    out: dict[str, str] = {}
    for idx, name in names.items():
        g = vals.get(idx)
        if g:
            out[name] = g
    return out


def _collect_app_spine(src: str, gpos: int, gname: str) -> tuple[int, int, list[str]] | None:
    """Return (spine_start, spine_end, args) for ouro_app*(gname(), args...)."""
    if src[gpos : gpos + len(gname)] != gname:
        return None
    inner_end = gpos + len(gname)
    if src[inner_end : inner_end + 2] != "()":
        return None
    inner_end += 2
    args: list[str] = []
    pos = gpos
    spine_start = gpos
    end = inner_end
    while True:
        k = pos
        while k > 0 and src[k - 1] in " \t\n":
            k -= 1
        if k == 0 or src[k - 1] != "(":
            break
        open_paren = k - 1
        if src[max(0, open_paren - 8) : open_paren] != "ouro_app":
            break
        app_start = open_paren - 8
        close = _match_paren(src, open_paren)
        if close < 0:
            break
        # After the inner expr, the current ouro_app's comma sits just
        # after that inner expr, before the new argument.
        scan = end
        while scan < len(src) and src[scan] in " \t\n":
            scan += 1
        if scan >= len(src) or src[scan] != ",":
            break
        arg_s = scan + 1
        while arg_s < close and src[arg_s] in " \t":
            arg_s += 1
        arg = src[arg_s:close].rstrip()
        args.append(arg)
        end = close + 1
        pos = app_start
        spine_start = app_start
        inner_end = close
    if not args:
        return None
    return spine_start, end, args


def strip_poly_type_apps(src: str) -> tuple[str, int]:
    """Keep only the erased value arguments of known polymorphic helpers."""
    gmap = _export_gmap(src)
    targets: list[tuple[str, int]] = []
    for name, keep in POLY_VALUE_ARITY.items():
        g = gmap.get(name)
        if g:
            targets.append((g, keep))
    if not targets:
        return src, 0

    # Collect replacements from the back so offsets stay valid.
    hits: list[tuple[int, int, str]] = []
    stripped = 0
    for gname, keep in targets:
        start = 0
        while True:
            pos = src.find(gname + "()", start)
            if pos < 0:
                break
            spine = _collect_app_spine(src, pos, gname)
            start = pos + len(gname)
            if spine is None:
                continue
            s0, s1, args = spine
            if len(args) <= keep:
                continue
            kept = args[-keep:]
            rebuilt = gname + "()"
            for arg in kept:
                rebuilt = f"ouro_app({rebuilt},{arg})"
            hits.append((s0, s1, rebuilt))
            stripped += len(args) - keep

    hits.sort(key=lambda h: h[0], reverse=True)
    out = src
    for s0, s1, rebuilt in hits:
        out = out[:s0] + rebuilt + out[s1:]
    return out, stripped


def _is_err5_type(arg: str) -> bool:
    a = "".join(arg.split())
    return a == "ouro_err(5)" or a.startswith("ouro_err(5)") or a.startswith(
        "ouro_app(ouro_err(5)"
    )


def _is_dummy0(arg: str) -> bool:
    a = "".join(arg.split())
    return a in ("ouro_ctor(0,0,0)", "ouro_ctor(0, 0, 0)")


def _rebuild_ctor(tag: int, fields: list[str]) -> str:
    n = len(fields)
    if n == 0:
        return f"ouro_ctor({tag},0,0)"
    inner = ",".join(fields)
    return f"ouro_ctor({tag},{n},(ouro_v *[]){{{inner}}})"


_CTOR_DELIMITER = re.compile(r"[{}(),]")


def _ctor_array_spans(src: str) -> dict[int, tuple[int, list[int]]]:
    """Index balanced brace bodies and their direct commas in one source scan.

    Both this index and the field splitter treat punctuation mechanically,
    including punctuation in literals. Ambiguous delimiters use the splitter.
    """
    stack: list[tuple[str, int, list[int]]] = []
    arrays: dict[int, tuple[int, list[int]]] = {}
    for token in _CTOR_DELIMITER.finditer(src):
        char, pos = token.group(), token.start()
        if char in "({":
            stack.append((char, pos, []))
        elif char == ",":
            if stack and stack[-1][0] == "{":
                stack[-1][2].append(pos)
        else:
            if not stack or stack[-1][0] != ("(" if char == ")" else "{"):
                return {}
            opening, start, commas = stack.pop()
            if opening == "{":
                arrays[start] = (pos, commas)
    return {} if stack else arrays


def _trim_span(src: str, start: int, end: int) -> tuple[int, int]:
    while start < end and src[start].isspace():
        start += 1
    while end > start and src[end - 1].isspace():
        end -= 1
    return start, end


def _ctor_field_spans(
    src: str, start: int, limit: int, arrays: dict[int, tuple[int, list[int]]]
) -> tuple[list[tuple[int, int]], int] | None:
    indexed = arrays.get(start - 1)
    if indexed is not None and indexed[0] < limit:
        end, commas = indexed
    else:
        # Preserve the original splitter's behavior on malformed punctuation.
        commas = []
        depth = 0
        end = start
        while end < limit:
            char = src[end]
            if char in "{(":
                depth += 1
            elif char == "}":
                if depth == 0:
                    break
                depth -= 1
            elif char == ")":
                depth -= 1
            elif char == "," and depth == 0:
                commas.append(end)
            end += 1
        else:
            return None
    fields = []
    for comma in commas:
        fields.append(_trim_span(src, start, comma))
        start = comma + 1
    if start < end:
        fields.append(_trim_span(src, start, end))
    return fields, end + 1


def _compact_field_prefix(src: str, start: int, end: int) -> str:
    # Erasure predicates need a short prefix; one extra non-space character
    # distinguishes a complete dummy constructor from a longer expression.
    prefix: list[str] = []
    for index in range(start, end):
        char = src[index]
        if not char.isspace():
            prefix.append(char)
            if len(prefix) == len("ouro_app(ouro_err(5)") + 1:
                break
    return "".join(prefix)


def strip_ctor_type_fields(src: str, drop_pair_dummy: bool) -> tuple[str, int]:
    """Drop leftover Type fields, preserving the same constructor rewrite rules.

    `ouro_err(5)` is CInd extracted as a value, never a real field. Parser
    TUs retain the leading Unit in POk triples; only non-parser TUs drop a
    leading dummy from a tag-zero triple after erasing leading Type fields.

    Unchanged nested fields remain spans into the original source. Only a
    constructor with a dropped field materializes rewritten text; the usual
    strict-validation path does not copy or rescan whole nested subtrees.
    """
    arrays = _ctor_array_spans(src) if "ouro_ctor(" in src else {}

    def rewrite(low: int, high: int) -> tuple[str | None, int]:
        hits: list[tuple[int, int, str]] = []
        stripped = 0
        start = low
        while True:
            pos = src.find("ouro_ctor(", start, high)
            if pos < 0:
                break
            j = pos + len("ouro_ctor(")
            while j < high and src[j] in " \t":
                j += 1
            tag_s = j
            while j < high and src[j].isdigit():
                j += 1
            if tag_s == j:
                start = pos + 1
                continue
            tag = int(src[tag_s:j])
            while j < high and src[j] in " \t":
                j += 1
            if j >= high or src[j] != ",":
                start = pos + 1
                continue
            j += 1
            while j < high and src[j] in " \t":
                j += 1
            n_s = j
            while j < high and src[j].isdigit():
                j += 1
            if n_s == j:
                start = pos + 1
                continue
            n = int(src[n_s:j])
            while j < high and src[j] in " \t":
                j += 1
            if j >= high or src[j] != ",":
                start = pos + 1
                continue
            j += 1
            while j < high and src[j] in " \t":
                j += 1
            if n == 0 or not src.startswith("(ouro_v *[])", j, high):
                start = pos + 1
                continue
            j += 12
            while j < high and src[j] in " \t":
                j += 1
            if j >= high or src[j] != "{":
                start = pos + 1
                continue
            parsed = _ctor_field_spans(src, j + 1, high, arrays)
            if parsed is None:
                start = pos + 1
                continue
            fields, end = parsed
            while end < high and src[end] in " \t":
                end += 1
            if end < high and src[end] == ")":
                end += 1
            values: list[str | None] = []
            prefixes: list[str] = []
            dropped = 0
            for a, b in fields:
                value, count = rewrite(a, b)
                values.append(value)
                dropped += count
                prefixes.append(
                    _compact_field_prefix(src, a, b) if value is None
                    else _compact_field_prefix(value, 0, len(value))
                )
            keep = 0
            while keep < len(fields) and _is_err5_type(prefixes[keep]):
                keep += 1
                dropped += 1
            if (
                drop_pair_dummy and tag == 0 and len(fields) - keep == 3
                and _is_dummy0(prefixes[keep])
            ):
                keep += 1
                dropped += 1
            start = end
            if dropped == 0:
                continue
            new_fields = [
                value if value is not None else src[a:b]
                for (a, b), value in zip(fields[keep:], values[keep:], strict=True)
            ]
            hits.append((pos, end, _rebuild_ctor(tag, new_fields)))
            stripped += dropped
        if not hits:
            return None, 0
        chunks = []
        cursor = low
        for start, end, text in hits:
            chunks.extend((src[cursor:start], text))
            cursor = end
        chunks.append(src[cursor:high])
        return "".join(chunks), stripped

    result, count = rewrite(0, len(src))
    return (src if result is None else result), count


def prefix_blob(src: str, suf: str) -> str:
    return SYM.sub(lambda m: f"ouro_{suf}_{m.group(1)}", src)


def _ctor_span_checks() -> list[tuple[str, bool]]:
    from unittest.mock import patch

    unit = "ouro_ctor(0,0,0)"
    err = "ouro_err(5)"

    def ctor(tag: str, fields: list[str]) -> str:
        return f"ouro_ctor({tag},{len(fields)},(ouro_v *[]){{{','.join(fields)}}})"

    cascade = ctor("0", [ctor("0", [err]), "x", "y"])
    triple = ctor("0", [unit, "x", "y"])
    cases = [
        ("nested erasure then dummy", cascade, True, ctor("0", ["x", "y"]), 2),
        ("parser dummy retained", cascade, False, triple, 1),
        ("leading dummy", triple, True, ctor("0", ["x", "y"]), 1),
        ("nonleading error retained", ctor("1", ["x", err]), True,
         ctor("1", ["x", err]), 0),
        ("compact error spelling", ctor("1", ["ouro_ \t err(5 )", "x"]), True,
         ctor("1", ["x"]), 1),
        ("Unicode whitespace", ctor("0", ["ouro_ctor(0,\u20030,0)", "x", "y"]),
         True, ctor("0", ["x", "y"]), 1),
        ("Unicode decimal tag", ctor("\u0660", [err, "x"]), True,
         ctor("0", ["x"]), 1),
        ("declared arity does not replace field count", triple.replace(",3,", ",7,"),
         True, ctor("0", ["x", "y"]), 1),
        ("nested commas", ctor("1", [err, "f(x,y)", "{x,y}"]), True,
         ctor("1", ["f(x,y)", "{x,y}"]), 1),
        ("trailing empty field", triple[:-2] + ",})", True,
         ctor("0", ["x", "y"]), 1),
        ("trailing whitespace field", triple[:-2] + ", })", True,
         triple[:-2] + ", })", 0),
        ("unbalanced prefix", ")" + ctor("0", [err]), True, ")" + unit, 1),
        ("missing final parenthesis", triple[:-1], True, ctor("0", ["x", "y"]), 1),
        ("zero arity still scans nested calls", f"ouro_ctor(0,0,{ctor('0', [err])})",
         True, f"ouro_ctor(0,0,{unit})", 1),
        ("surrogate bytes", "\udcff" + ctor("0", [err]), True, "\udcff" + unit, 1),
    ]
    checks = [(name, strip_ctor_type_fields(src, flag) == (expected, count))
              for name, src, flag, expected, count in cases]
    clean = "ouro_nat(7)"
    for _ in range(96):
        clean = ctor("1", [unit, clean])
    with patch.object(sys.modules[__name__], "_ctor_array_spans", wraps=_ctor_array_spans) as scan:
        result, count = strip_ctor_type_fields(clean, True)
        checks.append(("one delimiter scan for nested fields",
                       scan.call_count == 1 and result is clean and count == 0))
    try:
        strip_ctor_type_fields("ouro_ctor(\u00b2,1,(ouro_v *[]){x})", True)
    except ValueError:
        checks.append(("invalid decimal remains an error", True))
    else:
        checks.append(("invalid decimal remains an error", False))
    return checks


def _selftest() -> int:
    """Tiny rewrite checks for 2/3/4-arg poly spines."""
    blob = """
int ouro_export_count_x(void){return 4;}
const char *ouro_export_name_x(int i){
  switch(i){
    case 0: return "bindParseResult";
    case 1: return "bindValue";
    case 2: return "isJust";
    case 3: return "isNothing";
    default: return "";
  }
}
ouro_v *ouro_export_value_x(int i){
  switch(i){
    case 0: return ouro_g280();
    case 1: return ouro_g332();
    case 2: return ouro_g244();
    case 3: return ouro_g245();
    default: return 0;
  }
}
static ouro_v *ouro_g280(void){return 0;}
static ouro_v *ouro_g332(void){return 0;}
static ouro_v *ouro_g244(void){return 0;}
static ouro_v *ouro_g245(void){return 0;}
static ouro_v *use(void){
  return ouro_app(ouro_app(ouro_app(ouro_app(ouro_g280(),ouro_err(5)),ouro_ctor(0,0,0)),r),f);
}
static ouro_v *use2(void){
  return ouro_app(ouro_app(ouro_app(ouro_app(ouro_g332(),ouro_err(5)),pred),r),k);
}
static ouro_v *use3(void){
  return ouro_app(ouro_app(ouro_g244(),ouro_ctor(0,0,0)),m);
}
static ouro_v *use4(void){
  return ouro_app(ouro_app(ouro_g245(),ouro_ctor(0,0,0)),m);
}
"""
    out, n = strip_poly_type_apps(blob)
    checks = [
        ("bindParseResult 4->2", "ouro_app(ouro_app(ouro_g280(),r),f)" in out),
        ("bindValue 4->3", "ouro_app(ouro_app(ouro_app(ouro_g332(),pred),r),k)" in out),
        ("isJust 2->1", "ouro_app(ouro_g244(),m)" in out),
        ("isNothing 2->1", "ouro_app(ouro_g245(),m)" in out),
        ("dropped leftover Type", "ouro_err(5)" not in out and "ouro_ctor(0,0,0)" not in out),
        ("stripped count", n == 5),
    ]
    ctor_in = "ouro_ctor(0,3,(ouro_v *[]){ouro_ctor(0,0,0),ouro_get(env,2),ouro_get(env,1)})"
    ctor_out, cn = strip_ctor_type_fields(ctor_in, drop_pair_dummy=True)
    checks.append(("MkPair dummy0 drop", ctor_out == "ouro_ctor(0,2,(ouro_v *[]){ouro_get(env,2),ouro_get(env,1)})" and cn == 1))
    pok = "ouro_ctor(0,3,(ouro_v *[]){ouro_ctor(0,0,0),toks,pos})"
    pok_out, pn = strip_ctor_type_fields(pok, drop_pair_dummy=False)
    checks.append(("POk Unit kept", pok_out == pok and pn == 0))
    errf = "ouro_ctor(0,3,(ouro_v *[]){ouro_app(ouro_err(5),ouro_ctor(0,0,0)),ouro_ctor(0,0,0),x})"
    err_out, en = strip_ctor_type_fields(errf, drop_pair_dummy=False)
    checks.append(("ERR5 field drop", err_out == "ouro_ctor(0,2,(ouro_v *[]){ouro_ctor(0,0,0),x})" and en == 1))
    arms = (
        "static ouro_v *foo(ouro_env *e,ouro_v *a){return a;}\n"
        "static ouro_v *foo(ouro_env *e,ouro_v *a){return e->v;}\n"
        "static ouro_v *use(void){return ouro_case(s,2,(ouro_v *[]){foo,foo});}\n"
    )
    uout = uniquify(arms)
    checks.append(
        (
            "uniquify after-last arms",
            "foo_d2" in uout
            and "ouro_case(s,2,(ouro_v *[]){foo,foo_d2})" in uout,
        )
    )
    # Mid-use plus a later nested-arg ouro_case that named both arms _d3.
    mixed = (
        "static ouro_v *ouro_t1_1_(ouro_env *e,ouro_v *a){return ouro_ctor(8,0,0);}\n"
        "static ouro_v *mid(void){return ouro_thunk(ouro_t1_1_,0);}\n"
        "static ouro_v *ouro_t1_1_(ouro_env *e,ouro_v *a){return ouro_ctor(11,0,0);}\n"
        "static ouro_v *ouro_t1_1_(ouro_env *e,ouro_v *a){"
        "return ouro_case(ouro_app(ouro_g76(),x),2,(ouro_v *[]){"
        "ouro_thunk(ouro_t1_1_,e),ouro_thunk(ouro_t1_1_,e)});}\n"
    )
    mout = uniquify(mixed)
    checks.append(
        (
            "uniquify mid+after-last TSemi",
            "ouro_t1_1__d2" in mout
            and "ouro_t1_1__d3" in mout
            and "ouro_thunk(ouro_t1_1__d2,e),ouro_thunk(ouro_t1_1__d3,e)" in mout
            and "ouro_ctor(11,0,0)" in mout,
        )
    )
    # Live tok_simple1 shape: a *different* parent case names both arms as
    # the last version of a 3-def path (TBar, TSemi, next-match).
    live = (
        "static ouro_v *ouro_t1_1_(ouro_env *e,ouro_v *a){return ouro_ctor(8,0,0);}\n"
        "static ouro_v *mid(void){return ouro_thunk(ouro_t1_1_,0);}\n"
        "static ouro_v *ouro_t1_1_(ouro_env *e,ouro_v *a){return ouro_ctor(11,0,0);}\n"
        "static ouro_v *ouro_t1_1_(ouro_env *e,ouro_v *a){return ouro_ctor(14,0,0);}\n"
        "static ouro_v *parent(ouro_env *e,ouro_v *a){"
        "return ouro_case(ouro_app(ouro_g76(),x),2,(ouro_v *[]){"
        "ouro_thunk(ouro_t1_1_,e),ouro_thunk(ouro_t1_1_,e)});}\n"
    )
    lout = uniquify(live)
    checks.append(
        (
            "spread last-version pair = prev, last",
            "ouro_thunk(ouro_t1_1__d2,e),ouro_thunk(ouro_t1_1__d3,e)" in lout
            and "ouro_ctor(11,0,0)" in lout,
        )
    )
    nested = (
        "static ouro_v *foo(ouro_env *e,ouro_v *a){return a;}\n"
        "static ouro_v *foo_d2(ouro_env *e,ouro_v *a){return e->v;}\n"
        "static ouro_v *use(void){return ouro_case(ouro_app(g(),x),2,"
        "(ouro_v *[]){ouro_thunk(foo_d2,e),ouro_thunk(foo_d2,e)});}\n"
    )
    nout = spread_case_arms(nested)
    checks.append(
        (
            "spread nested ouro_case first-arg",
            "ouro_thunk(foo,e),ouro_thunk(foo_d2,e)" in nout,
        )
    )
    interleaved = (
        "static ouro_v *before(void){return ouro_thunk(alpha,0);}\n"
        "static ouro_v *alpha(ouro_env *e,ouro_v *a){return ouro_ctor(1,0,0);}\n"
        "static ouro_v *beta(ouro_env *e,ouro_v *a){return ouro_ctor(2,0,0);}\n"
        "static ouro_v *mid(void){return ouro_thunk(alpha,0);}\n"
        "static ouro_v *alpha(ouro_env *e,ouro_v *a){return ouro_ctor(3,0,0);}\n"
        "static ouro_v *mid2(void){return ouro_thunk(alpha,0);}\n"
        "static ouro_v *beta(ouro_env *e,ouro_v *a){return ouro_ctor(4,0,0);}\n"
        "static ouro_v *alpha(ouro_env *e,ouro_v *a){return ouro_ctor(5,0,0);}\n"
        "static ouro_v *beta(ouro_env *e,ouro_v *a){return ouro_ctor(6,0,0);}\n"
        "static ouro_v *after(void){return ouro_case(ouro_app(g(),x),3,"
        "(ouro_v *[]){ouro_thunk(alpha,e),ouro_thunk(alpha,e),"
        "ouro_ctor(0,1,(ouro_v *[]){ouro_thunk(beta,e)})});}\n"
        "static ouro_v *tail(void){return ouro_case(s,3,"
        "(ouro_v *[]){beta,ouro_thunk(beta,e),beta});}\n"
        "static ouro_v *prefix(ouro_env *e,ouro_v *a){return ouro_thunk(alpha_extra,e);}\n"
    )
    interleaved_expected = (
        "static ouro_v *before(void){return ouro_thunk(alpha,0);}\n"
        "static ouro_v *alpha(ouro_env *e,ouro_v *a){return ouro_ctor(1,0,0);}\n"
        "static ouro_v *beta(ouro_env *e,ouro_v *a){return ouro_ctor(2,0,0);}\n"
        "static ouro_v *mid(void){return ouro_thunk(alpha,0);}\n"
        "static ouro_v *alpha_d2(ouro_env *e,ouro_v *a){return ouro_ctor(3,0,0);}\n"
        "static ouro_v *mid2(void){return ouro_thunk(alpha_d2,0);}\n"
        "static ouro_v *beta_d2(ouro_env *e,ouro_v *a){return ouro_ctor(4,0,0);}\n"
        "static ouro_v *alpha_d3(ouro_env *e,ouro_v *a){return ouro_ctor(5,0,0);}\n"
        "static ouro_v *beta_d3(ouro_env *e,ouro_v *a){return ouro_ctor(6,0,0);}\n"
        "static ouro_v *after(void){return ouro_case(ouro_app(g(),x),3,"
        "(ouro_v *[]){ouro_thunk(alpha_d2,e),ouro_thunk(alpha_d3,e),"
        "ouro_ctor(0,1,(ouro_v *[]){ouro_thunk(beta,e)})});}\n"
        "static ouro_v *tail(void){return ouro_case(s,3,"
        "(ouro_v *[]){beta_d2,ouro_thunk(beta_d3,e),beta_d3});}\n"
        "static ouro_v *prefix(ouro_env *e,ouro_v *a){return ouro_thunk(alpha_extra,e);}\n"
    )
    interleaved_out = uniquify(interleaved)
    checks.append(("uniquify interleaved scoped names and mixed nested arms",
                   interleaved_out == interleaved_expected))
    checks.extend(_ctor_span_checks())
    bad = [name for name, ok in checks if not ok]
    if bad:
        print("pack_frontend selftest FAIL", bad, file=sys.stderr)
        if interleaved_out != interleaved_expected:
            print("--- interleaved expected ---", file=sys.stderr)
            print(interleaved_expected, file=sys.stderr)
            print("--- interleaved actual ---", file=sys.stderr)
            print(interleaved_out, file=sys.stderr)
        print("--- mixed ---", file=sys.stderr)
        print(mout, file=sys.stderr)
        print("--- nested ---", file=sys.stderr)
        print(nout, file=sys.stderr)
        print(out, file=sys.stderr)
        return 1
    print(f"pack_frontend selftest OK stripped={n}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", required=False)
    ap.add_argument(
        "pieces",
        nargs="*",
        help="SUFFIX:path pairs, e.g. lx:_build/fe/lx.c",
    )
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument(
        "--uniquify-only",
        metavar="FILE",
        help="In-place uniquify + spread_case_arms (backend emit).",
    )
    ap.add_argument(
        "--mechanical",
        action="store_true",
        help="Prefix + uniquify only (default). Do not run leftover detectors.",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Fail if any leftover Type app would need stripping.",
    )
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if args.uniquify_only:
        uniquify_file(args.uniquify_only)
        return 0
    if not args.output or not args.pieces:
        ap.error("output and SUFFIX:path pieces are required")
    out_path = Path(args.output)
    chunks: list[str] = [
        "/* Generated frontend pack: split O8 cones, prefixed statics.\n"
        "   Do not hand-edit. Regenerate with scripts/emit_frontend.sh. */\n"
    ]
    dropped_total = 0
    for spec in args.pieces:
        if ":" not in spec:
            print(f"pack_frontend: expected SUFFIX:path, got {spec}", file=sys.stderr)
            return 2
        suf, path = spec.split(":", 1)
        try:
            text = Path(path).read_text(encoding="utf-8", errors="surrogateescape")
        except OSError as exc:
            print(f"pack_frontend: cannot read {path}: {exc}", file=sys.stderr)
            return 2
        if "ouro_export_count_" not in text:
            print(f"pack_frontend: {path} has no export table", file=sys.stderr)
            return 2
        text = uniquify(text)
        if args.strict:
            _, dropped = strip_poly_type_apps(text)
            drop_pair = suf not in ("pa", "pb", "pf")
            _, dropped_c = strip_ctor_type_fields(text, drop_pair_dummy=drop_pair)
            dropped_total += dropped + dropped_c
        chunks.append(f"\n/* ---- frontend TU module={suf} ---- */\n")
        chunks.append(prefix_blob(text, suf))
        chunks.append("\n")
    if args.strict and dropped_total > 0:
        print(
            f"pack_frontend: STRICT FAIL leftover_type_apps={dropped_total} "
            "(extract.ouro should have dropped these)",
            file=sys.stderr,
        )
        return 3
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("".join(chunks), encoding="utf-8", errors="surrogateescape")
    except OSError as exc:
        print(f"pack_frontend: cannot write {out_path}: {exc}", file=sys.stderr)
        return 2
    mode = "strict" if args.strict else "mechanical"
    print(
        f"pack_frontend: wrote {out_path} bytes={out_path.stat().st_size} "
        f"leftover_type_apps={dropped_total} mode={mode}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
