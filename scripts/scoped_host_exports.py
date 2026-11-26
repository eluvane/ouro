#!/usr/bin/env python3
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING
from structural_quality_legacy import lex

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def _literal_prefix_matches(pattern: str, text: str, prefix: str) -> list[re.Match[str]]:
    expression = re.compile(pattern)
    matches = []
    start = text.find(prefix)
    while start >= 0:
        # The regex keeps its guards; the original text preserves Unicode word boundaries.
        match = expression.match(text, start)
        if match is not None:
            matches.append(match)
        start = text.find(prefix, match.end() if match is not None else start + 1)
    return matches


def _unique(pattern: str, text: str, label: str, *, prefix: str | None = None) -> re.Match[str]:
    matches = (list(re.finditer(pattern, text)) if prefix is None
               else _literal_prefix_matches(pattern, text, prefix))
    if len(matches) != 1:
        raise RuntimeError(f"missing or duplicate {label}")
    return matches[0]


def _cstring(raw: str) -> str:
    if raw.isascii() and "\\" not in raw:
        if "\0" in raw:
            raise RuntimeError("NUL in export label")
        return raw

    data = bytearray()
    index = 0
    escapes = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9,
               "v": 11, "\\": 92, '"': 34, "'": 39, "?": 63}
    while index < len(raw):
        if raw[index] != "\\":
            data.extend(raw[index].encode("utf-8"))
            index += 1
            continue
        index += 1
        if index == len(raw):
            raise RuntimeError("unterminated export label escape")
        word = raw[index]
        if word in escapes:
            data.append(escapes[word])
            index += 1
        else:
            pattern = r"[0-7]{1,3}" if word in "01234567" else r"x[0-9A-Fa-f]+"
            match = re.match(pattern, raw[index:])
            if match is None:
                raise RuntimeError("unsupported export label escape")
            token = match.group()
            value = int(token, 8) if word != "x" else int(token[1:], 16)
            if value > 255:
                raise RuntimeError("oversized export label escape")
            data.append(value)
            index += len(token)
    if 0 in data:
        raise RuntimeError("NUL in export label")
    return data.decode("utf-8", errors="surrogateescape")


def _paths(values: Sequence[str]) -> tuple[str, ...]:
    paths = tuple(value.replace("\\", "/") for value in values)
    if (not paths or len(set(paths)) != len(paths)
            or any(not path.endswith(".ouro") or ":" in path
                   or any(part in ("", ".", "..") for part in path.split("/"))
                   for path in paths)):
        raise RuntimeError("invalid ordered source closure")
    return paths


def _scoped_label(label: str) -> tuple[str, str] | None:
    if not label.startswith("_ouro_m_"):
        return None
    ordinal, separator, basename = label[len("_ouro_m_"):].partition("_")
    return (ordinal, basename) if separator else None


def _declarations(source: str) -> dict[str, str]:
    try:
        tokens, _comments = lex(source, "ouro")
    except ValueError as error:
        raise RuntimeError("unsupported source lexical region") from error
    declarations = {}
    for index, token in enumerate(tokens):
        if token.value == "private" and (index + 1 == len(tokens)
                or tokens[index + 1].value not in {"def", "axiom", "inductive", "record", "effect", "intrinsic", "extern"}):
            raise RuntimeError("unsupported private declaration head")
        if token.value != "def":
            continue
        private = index > 0 and tokens[index - 1].value == "private"
        start = index - int(private)
        if (index + 1 == len(tokens)
                or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*", tokens[index + 1].value) is None):
            raise RuntimeError("unsupported source declaration head")
        name = tokens[index + 1].value
        if name in declarations:
            raise RuntimeError(f"duplicate source declaration {name}")
        visibility = "private" if private else "public"
        if start > 0 and tokens[start - 1].value not in {";", "end"}:
            # Unsupported heads count as homonyms but cannot supply host aliases.
            visibility = "unsupported"
        declarations[name] = visibility
    return declarations


@dataclass(frozen=True)
class _ExportTables:
    count_match: re.Match[str]
    tables: list[re.Match[str]]
    labels: dict[str, int]
    values: list[tuple[int, str]]
    getters: dict[int, str]
    getter_declarations: Counter[str]

    @cached_property
    def scoped_ordinals(self) -> dict[str, list[str]]:
        ordinals: dict[str, list[str]] = {}
        for label in self.labels:
            scoped = _scoped_label(label)
            if scoped is not None:
                ordinal, basename = scoped
                ordinals.setdefault(basename, []).append(ordinal)
        return ordinals


def _read_export_tables(text: str, module: str) -> _ExportTables:
    _unique(rf"\bouro_export_count{re.escape(module)}\s*\(void\)\s*\{{",
            text, "count table declaration", prefix="ouro_export_count" + module)
    count_match = _unique(
        rf"int ouro_export_count{re.escape(module)}\(void\)\{{return (0|[1-9][0-9]*);\}}",
        text, "export count table")
    count = int(count_match.group(1))
    tables = []
    for kind, result, item, zero in (
        ("name", "const char *", r'"(?:[^"\\]|\\.)*"', '""'),
        ("value", "ouro_v *", r"ouro_g(?:0|[1-9][0-9]*)\(\)", "0"),
    ):
        header = f"{result}ouro_export_{kind}{module}(int i){{switch(i){{"
        _unique(rf"\bouro_export_{kind}{re.escape(module)}\s*\(int\s+i\)\s*\{{",
                text, f"{kind} table declaration", prefix=f"ouro_export_{kind}{module}")
        rows = rf"(?P<rows>(?:\s*case (?:0|[1-9][0-9]*):\s*return {item};)*)\s*"
        tail = rf"(?:\}}\s*return {re.escape(zero)};\s*\}}|default:\s*return {re.escape(zero)};\s*\}}\s*\}})"
        tables.append(_unique(re.escape(header) + rows + tail, text, f"{kind} table"))
    names = [(int(index), _cstring(label)) for index, label in re.findall(
        r'case (0|[1-9][0-9]*):\s*return "((?:[^"\\]|\\.)*)";', tables[0].group("rows"))]
    values = [(int(index), getter) for index, getter in re.findall(
        r"case (0|[1-9][0-9]*):\s*return (ouro_g(?:0|[1-9][0-9]*))\(\);", tables[1].group("rows"))]
    if (count != len(names) or count != len(values)
            or sorted(index for index, _ in names) != list(range(count))
            or sorted(index for index, _ in values) != list(range(count))
            or len({name for _, name in names}) != count):
        raise RuntimeError("noncanonical export inventory")
    labels = {name: index for index, name in names}
    # Check the word boundary after the literal prefix so re can skip to static.
    getter_declarations = Counter(re.findall(
        r"static(?<!\wstatic)\s+ouro_v\s*\*\s*(ouro_g[0-9]+)\s*\(void\)\s*\{", text))
    return _ExportTables(count_match, tables, labels, values, dict(values), getter_declarations)


class ScopedExportIndex:
    """Keep parsed tables and declarations for one scoped export pass."""

    def __init__(self) -> None:
        self._latest: tuple[str, str, _ExportTables] | None = None
        self._sources: dict[str, tuple[str, dict[str, str]]] = {}

    def tables_for(self, text: str, module: str) -> _ExportTables:
        if self._latest is not None and self._latest[0] is text and self._latest[1] == module:
            return self._latest[2]
        self._latest = None
        tables = _read_export_tables(text, module)
        self._latest = (text, module, tables)
        return tables

    def declarations_for(self, owner: str, source: str) -> dict[str, str]:
        latest = self._sources.get(owner)
        if latest is not None and latest[0] is source:
            return latest[1]
        declarations = _declarations(source)
        self._sources[owner] = (source, declarations)
        return declarations


def _scoped_host_export_plan(
    text: str,
    units: Sequence[str],
    canonical_units: Sequence[str],
    entry: str,
    sources: Mapping[str, str],
    routes: Sequence[tuple[str, str, tuple[str, ...]]],
    module: str = "",
    *,
    export_index: ScopedExportIndex | None = None,
):
    paths = _paths(units)
    if paths != _paths(canonical_units) or paths[-1] != entry or set(sources) != set(paths):
        raise RuntimeError("source closure or entry differs")
    if module and re.fullmatch(r"_[A-Za-z0-9_]+", module) is None:
        raise RuntimeError("invalid export table suffix")
    inventory = (_read_export_tables(text, module) if export_index is None
                 else export_index.tables_for(text, module))
    labels, getters = inventory.labels, inventory.getters
    ordinals = {path: index for index, path in enumerate(paths)}
    planned = {}
    seen_aliases = set()
    source_declarations = {}

    def declaration(owner: str, name: str) -> str | None:
        if owner not in source_declarations:
            try:
                source = sources[owner]
                source_declarations[owner] = (_declarations(source) if export_index is None
                                              else export_index.declarations_for(owner, source))
            except RuntimeError as error:
                raise RuntimeError(f"{owner}: {error}") from error
        return source_declarations[owner].get(name)

    for alias, source_name, owners in routes:
        if (re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias) is None
                or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", source_name) is None
                or not owners or owners != _paths(owners) or alias in seen_aliases):
            raise RuntimeError("invalid closed export route")
        seen_aliases.add(alias)
        present = [owner for owner in owners if owner in ordinals]
        if len(present) > 1:
            raise RuntimeError(f"ambiguous source owner {alias}")
        if not present:
            if alias in labels:
                raise RuntimeError(f"source owner is absent {alias}")
            continue
        owner = present[0]
        if declaration(owner, source_name) != "public":
            raise RuntimeError(f"missing, private or unsupported source declaration {alias} in {owner}")
        ordinal = ordinals[owner]
        qualified = f"_ouro_m_{ordinal}_{source_name}"
        related = inventory.scoped_ordinals.get(source_name, ())
        for ordinal_text in related:
            if re.fullmatch(r"0|[1-9][0-9]*", ordinal_text) is None:
                raise RuntimeError(f"malformed source ordinal {alias}")
            other = int(ordinal_text)
            if (other >= len(paths) or paths[other] == entry
                    or declaration(paths[other], source_name) is None):
                raise RuntimeError(f"wrong owner or ordinal {alias}")
        if owner == entry:
            original = source_name
        elif qualified in labels:
            original = qualified
        else:
            declarations = [path for path in paths if declaration(path, source_name) is not None]
            if len(declarations) != 1 or related:
                raise RuntimeError(f"ambiguous or malformed source export {alias}")
            original = source_name
        if original not in labels:
            raise RuntimeError(f"missing required export {alias}")
        getter = getters[labels[original]]
        if inventory.getter_declarations[getter] != 1:
            raise RuntimeError(f"missing or duplicate {alias} getter declaration")
        target = owner, source_name, original, getter
        planned[alias] = target

    return planned, inventory.count_match, inventory.tables, labels, inventory.values


def scoped_host_export_getters(text, units, canonical_units, entry, sources, routes, module="", *,
                               export_index: ScopedExportIndex | None = None):
    planned, _count, _tables, _labels, values = _scoped_host_export_plan(
        text, units, canonical_units, entry, sources, routes, module, export_index=export_index)
    if len({getter for _index, getter in values}) != len(values):
        raise RuntimeError("aliased original export getter")
    return {alias: target[3] for alias, target in planned.items()}


def _edit_export_table_spans(text: str, edits: list[tuple[int, int, str]]) -> str:
    ordered = sorted(edits, reverse=True)
    parts = []
    cursor = len(text)
    for low, high, replacement in ordered:
        if high > cursor:
            # Overlapping matches retain the original reverse splice order.
            for start, stop, value in ordered:
                text = text[:start] + value + text[stop:]
            return text
        parts.extend((text[high:cursor], replacement))
        cursor = low
    parts.append(text[:cursor])
    return "".join(reversed(parts))


def _apply_scoped_host_export_plan(text, plan, *, installed):
    planned, count_match, tables, labels, values = plan
    count = int(count_match.group(1))
    getters = dict(values)
    additions = [(alias, target) for alias, target in planned.items() if alias != target[2]]
    existing = [(alias, target) for alias, target in additions if alias in labels]
    if existing and not installed:
        raise RuntimeError("source is already aliased or has a conflicting bare export")
    if installed and len(existing) != len(additions):
        raise RuntimeError("missing installed export alias")
    removed = {labels[alias] for alias, _ in existing}
    original_getters = [getter for index, getter in values if index not in removed]
    if len(set(original_getters)) != len(original_getters):
        raise RuntimeError("aliased original export getter")
    if installed:
        base = count - len(existing)
        if [labels[alias] for alias, _ in existing] != list(range(base, count)):
            raise RuntimeError("noncanonical installed alias extension")
        if any(getters[labels[alias]] != target[3] for alias, target in existing):
            raise RuntimeError("conflicting installed alias getter")
        return text

    if not additions:
        return text

    edits = [(count_match.start(1), count_match.end(1), str(count + len(additions)))]
    for table, kind in zip(tables, ("name", "value"), strict=True):
        rows = "".join(f'case {count + offset}:return "{alias}";' if kind == "name"
                       else f"case {count + offset}:return {target[3]}();"
                       for offset, (alias, target) in enumerate(additions))
        edits.append((table.end("rows"), table.end("rows"), rows))
    return _edit_export_table_spans(text, edits)


def scoped_host_export_aliases(
    text: str,
    units: Sequence[str],
    canonical_units: Sequence[str],
    entry: str,
    sources: Mapping[str, str],
    routes: Sequence[tuple[str, str, tuple[str, ...]]],
    module: str = "",
    *,
    installed: bool = False,
    export_index: ScopedExportIndex | None = None,
) -> str:
    plan = _scoped_host_export_plan(text, units, canonical_units, entry, sources, routes, module,
                                    export_index=export_index)
    return _apply_scoped_host_export_plan(text, plan, installed=installed)


def scoped_host_export_original(text, units, canonical_units, entry, sources, routes, module="", *,
                                export_index: ScopedExportIndex | None = None):
    """Project original exports after checking the closed installed alias extension."""
    plan = _scoped_host_export_plan(text, units, canonical_units, entry, sources, routes, module,
                                    export_index=export_index)
    _apply_scoped_host_export_plan(text, plan, installed=True)
    planned, count_match, tables, labels, _values = plan
    aliases = {labels[alias] for alias, target in planned.items() if alias != target[2]}
    if not aliases:
        return text
    base = int(count_match.group(1)) - len(aliases)
    edits = [(count_match.start(1), count_match.end(1), str(base))]
    for table, item in zip(tables, (r'"(?:[^"\\]|\\.)*"',
                                   r"ouro_g(?:0|[1-9][0-9]*)\(\)"), strict=True):
        for row in re.finditer(rf"case (0|[1-9][0-9]*):\s*return {item};", table.group("rows")):
            if int(row.group(1)) in aliases:
                edits.append((table.start("rows") + row.start(), table.start("rows") + row.end(), ""))
    return _edit_export_table_spans(text, edits)
