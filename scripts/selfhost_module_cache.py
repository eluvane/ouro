#!/usr/bin/env python3
"""Fail-closed incremental module artifact cache for Ouro source modules.

This helper is a build-system sidecar.  It records deterministic, content-addressed
artifacts for .ouro modules and their import closures so frontend regeneration and
stage-loop code can invalidate by module/closure instead of treating all source as
one opaque blob.  It does not interpret terms, change the kernel boundary, or make
cached artifacts trusted. These artifacts are not canonical compiler output.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from itertools import chain
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

from repo_support import decode_source_text, read_required_text
from repo_support import filename_fragment
from repo_support import hash_json, sha256_bytes, Timer
from repo_support import read_json_object_or_none
from repo_support import bool_env
from repo_support import bind_relative_path, relative_path, sha256_file

ROOT = Path(__file__).resolve().parents[1]
rel = bind_relative_path(ROOT, resolve=True)

DECL_RE = re.compile(r"^\s*(def|inductive|record|axiom|theorem|lemma|effect|handler)\s+([A-Za-z_][A-Za-z0-9_']*)")
_IMPORT_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_']*")


@dataclass(frozen=True)
class FileDigest:
    path: str
    sha256: str
    bytes: int


@dataclass(frozen=True)
class ModulePlan:
    path: str
    source: FileDigest
    imports: Tuple[str, ...]
    decls: Tuple[str, ...]
    direct_key: str


def normalize_path(path: str | Path) -> str:
    p = Path(path)
    if not p.is_absolute():
        return str(p).replace("\\", "/")
    return relative_path(ROOT, p, resolve=True)


def file_digest(path: Path) -> FileDigest:
    p = path if path.is_absolute() else ROOT / path
    st = p.stat()
    return FileDigest(rel(p), sha256_file(p), st.st_size)


def write_text_if_changed(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == text:
                return "unchanged"
        except (OSError, UnicodeError):
            pass
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}.{time.time_ns()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return "updated"


def write_json_if_changed(path: Path, data: object) -> str:
    return write_text_if_changed(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def canon_import(base: str, spelling: str) -> str:
    """Resolve a quoted import spelling against the importing file path."""
    base_path = Path(base.replace("\\", "/"))
    parts = list(base_path.parent.parts)
    for segment in Path(spelling).parts:
        if segment in ("", "."):
            continue
        if segment == "..":
            if parts:
                parts.pop()
            continue
        parts.append(segment)
    if not parts:
        return spelling
    return str(Path(*parts)).replace("\\", "/")


def skip_import_alias(after: str) -> str:
    """Skip `as Name` after a quoted import, leaving the trailing `;` if present.

    `async` and similar identifiers must not be treated as the `as` keyword.
    """
    if not after.startswith("as"):
        return after
    if len(after) != 2 and (after[2].isalnum() or after[2] in "_'"):
        return after
    ident = after[2:].lstrip()
    index = 0
    if index >= len(ident) or not (ident[index].isalpha() or ident[index] == "_"):
        return after
    index += 1
    while index < len(ident) and (ident[index].isalnum() or ident[index] in "_'"):
        index += 1
    return ident[index:].lstrip()


def _multiline_end(source: str, start: int) -> int | None:
    body = start + 3
    if source.startswith("\r\n", body):
        line = body + 2
    elif source.startswith("\n", body):
        line = body + 1
    else:
        return None
    while line < len(source):
        quote = line
        while quote < len(source) and source[quote] in " \t":
            quote += 1
        if source.startswith('"""', quote):
            return quote + 3
        next_line = source.find("\n", line)
        if next_line < 0:
            break
        line = next_line + 1
    return None


def quoted_import_targets(source_text: str, source_path: str) -> list[str]:
    """Discover quoted dependencies; source acceptance remains compiler-owned."""
    paths: list[str] = []
    state = "scan"
    previous_dot = False
    index = 0
    source_length = len(source_text)
    while index < source_length:
        char = source_text[index]
        if char.isspace():
            index += 1
            continue
        if char == "-" and source_text.startswith("--", index):
            end = source_text.find("\n", index)
            index = source_length if end < 0 else end + 1
            continue
        word = ""
        path = None
        wants_path = state in ("path", "group")
        if char == '"' and source_text.startswith('"""', index):
            close = _multiline_end(source_text, index)
            index = close if close is not None else source_length
        elif char == "r" and source_text.startswith('r#"', index):
            close = source_text.find('"#', index + 3)
            if close < 0:
                index = source_length
            else:
                if wants_path:
                    path = source_text[index + 3:close]
                index = close + 2
        elif char == "'":
            # Identifier words consume their primes; this delimiter begins an opaque scalar.
            index += 1
            while index < source_length and source_text[index] != "'":
                index += 2 if source_text[index] == "\\" else 1
            if index < source_length:
                index += 1
        elif char == '"':
            index += 1
            close = source_text.find('"', index)
            plain_end = close if close >= 0 else source_length
            escape = source_text.find("\\", index, plain_end)
            if escape >= 0:
                plain_end = escape
            value: list[str] | None = [source_text[index:plain_end]] if wants_path else None
            index = plain_end
            while index < source_length and source_text[index] != '"':
                char = source_text[index]
                index += 1
                if char == "\\" and index < source_length:
                    escaped = source_text[index]
                    index += 1
                    if escaped == "u" and index < source_length and source_text[index] == "{":
                        close = source_text.find("}", index + 1)
                        digits = source_text[index + 1:close] if close >= 0 else ""
                        if (not 1 <= len(digits) <= 6
                                or any(digit not in "0123456789abcdefABCDEF" for digit in digits)):
                            raise ValueError(f"malformed Unicode escape in {source_path}")
                        scalar = int(digits, 16)
                        if scalar > 0x10FFFF or 0xD800 <= scalar <= 0xDFFF:
                            raise ValueError(f"malformed Unicode escape in {source_path}")
                        if value is not None:
                            value.append(chr(scalar))
                        index = close + 1
                    elif value is not None:
                        value.append({"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}
                                     .get(escaped, "\\" + escaped))
                elif value is not None:
                    value.append(char)
            closed = index < source_length
            if closed and value is not None:
                path = "".join(value)
            index += int(closed)
        else:
            ident = _IMPORT_IDENTIFIER_RE.match(source_text, index)
            if ident:
                end = ident.end()
                if end - index == 6 and source_text.startswith("import", index):
                    word = "import"
                index = end
            else:
                word = char
                index += 1

        if wants_path:
            if path is not None:
                paths.append(path)
                state = "after-path"
            elif state == "group" and word == ";":
                state = "scan"
            else:
                state = "malformed"
        elif state == "after-path" and word == ",":
            state = "group"
        elif state != "malformed":
            state = "path" if word == "import" and not previous_dot else "scan"
        previous_dot = word == "."

    # Finish lexical checks before reporting an invalid import group.
    if state in ("path", "group", "malformed"):
        raise ValueError(f"malformed quoted import in {source_path}")
    return [canon_import(source_path, path) for path in paths]


ImportBytesParser = Callable[[bytes, str], list[str]]


@dataclass(slots=True)
class _ParsedImportSource:
    data: bytes
    targets: list[str]
    sha256: str | None = None


class CachedImportParser:
    """Keep one source version per importer for a verification scope."""

    def __init__(self) -> None:
        self._parsed: dict[str, _ParsedImportSource] = {}

    def _source(self, data: bytes, path: str) -> _ParsedImportSource:
        previous = self._parsed.get(path)
        if previous is not None and previous.data == data:
            return previous
        source = _ParsedImportSource(data, quoted_import_targets(decode_source_text(data), path))
        self._parsed[path] = source
        return source

    def __call__(self, data: bytes, path: str) -> list[str]:
        return self._source(data, path).targets

    def parse_and_digest(self, data: bytes, path: str) -> tuple[list[str], str]:
        source = self._source(data, path)
        # Another reader may replace the path entry while this snapshot is being hashed.
        if source.sha256 is None:
            source.sha256 = sha256_bytes(source.data)
        return source.targets, source.sha256


def cached_import_parser() -> CachedImportParser:
    return CachedImportParser()


def import_targets(path: str) -> List[str]:
    p = ROOT / path if not Path(path).is_absolute() else Path(path)
    if not p.is_file():
        raise SystemExit(f"MODULE_CACHE: FAIL missing {path}")
    return quoted_import_targets(read_required_text(p, "MODULE_CACHE"), path)


def declarations_in_source(source: str) -> Tuple[str, ...]:
    names: List[str] = []
    for line in source.splitlines():
        m = DECL_RE.match(line)
        if m:
            names.append(f"{m.group(1)}:{m.group(2)}")
    return tuple(names)


def declaration_names(path: str) -> Tuple[str, ...]:
    p = ROOT / path if not Path(path).is_absolute() else Path(path)
    return declarations_in_source(read_required_text(p, "MODULE_CACHE"))


def _import_cycle(root: str, visiting: set[str], path: str) -> SystemExit:
    cycle = " -> ".join([*sorted(visiting), path])
    return SystemExit(f"MODULE_CACHE: FAIL import cycle while collecting {root}: {cycle}")


def collect_units(root: str, *, imports=None, cycle_error=None, normalize=normalize_path) -> List[str]:
    seen: List[str] = []
    complete: set[str] = set()
    visiting: set[str] = set()
    read_imports = imports or import_targets

    def walk(path: str) -> None:
        norm = normalize(path)
        if norm in complete:
            return
        if norm in visiting:
            if cycle_error is not None:
                raise SystemExit(cycle_error(norm))
            raise _import_cycle(root, visiting, norm)
        visiting.add(norm)
        for imp in read_imports(norm):
            walk(imp)
        visiting.remove(norm)
        seen.append(norm)
        complete.add(norm)

    walk(root)
    return seen


def _iter_planned_closures(
    modules: Sequence[str], plans: Mapping[str, ModulePlan]
) -> Iterator[Tuple[str, List[str]]]:
    def planned_imports(path: str) -> Tuple[str, ...]:
        if path not in plans:
            raise SystemExit(f"MODULE_CACHE: FAIL import closure references unplanned module {path}")
        return plans[path].imports

    # Absolute paths can resolve through links afresh on each walk.
    if any(Path(path).is_absolute() or any(Path(imp).is_absolute() for imp in plan.imports)
           for path, plan in plans.items()):
        for mod in modules:
            yield mod, collect_units(mod, imports=planned_imports)
        return

    closures: Dict[str, List[str]] = {}
    visiting: set[str] = set()

    def walk(path: str, root: str) -> List[str]:
        norm = normalize_path(path)
        if norm in closures:
            return closures[norm]
        if norm in visiting:
            raise _import_cycle(root, visiting, norm)
        visiting.add(norm)
        children = []
        for imp in planned_imports(norm):
            children.append(walk(imp, root))
        visiting.remove(norm)
        # A previously emitted module also has all its dependencies emitted.
        closures[norm] = [*dict.fromkeys(chain.from_iterable(children)), norm]
        return closures[norm]

    for mod in modules:
        yield mod, walk(mod, mod)


def ordered_union(seqs: Iterable[Sequence[str]]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for seq in seqs:
        for item in seq:
            norm = normalize_path(item)
            if norm not in seen:
                seen.add(norm)
                out.append(norm)
    return out


def tool_digest(tool_inputs: Sequence[Path], *, schema: str) -> Tuple[str, dict]:
    script = ROOT / "scripts/selfhost_module_cache.py"
    paths = [script]
    for p in tool_inputs:
        pp = p if p.is_absolute() else ROOT / p
        if pp not in paths:
            paths.append(pp)
    digests: Dict[str, dict] = {}
    for p in paths:
        if p.exists():
            digests[rel(p)] = asdict(file_digest(p))
    meta = {"kind": "ouro.selfhost-module-cache-tool.v1", "schema": schema, "tools": digests}
    return hash_json(meta), meta


def make_module_plans(modules: Sequence[str], tool_hash: str, *,
                      parse_bytes: ImportBytesParser | None = None) -> Dict[str, ModulePlan]:
    plans: Dict[str, ModulePlan] = {}
    for path in modules:
        p = ROOT / path if not Path(path).is_absolute() else Path(path)
        try:
            data = p.read_bytes()
            text = decode_source_text(data)
        except (OSError, UnicodeError) as exc:
            raise SystemExit(f"MODULE_CACHE: FAIL unreadable {p}: {exc}") from exc
        source_path = rel(p)
        if type(parse_bytes) is CachedImportParser:
            targets, source_hash = parse_bytes.parse_and_digest(data, path)
        else:
            source_hash = sha256_bytes(data)
            targets = quoted_import_targets(text, path) if parse_bytes is None else parse_bytes(data, path)
        src = FileDigest(source_path, source_hash, len(data))
        imports = tuple(targets)
        decls = declarations_in_source(text)
        direct_key = hash_json(
            {
                "kind": "ouro.selfhost-module.direct.v1",
                "path": path,
                "source": asdict(src),
                "imports": list(imports),
                "decls": list(decls),
                "tool_hash": tool_hash,
            }
        )
        plans[path] = ModulePlan(path=path, source=src, imports=imports, decls=decls, direct_key=direct_key)
    return plans


def artifact_cache_state(path: Path, expected_hash: str, expected_kind: str) -> Tuple[bool, str]:
    data = read_json_object_or_none(path)
    if data is None:
        return False, "missing-or-invalid-artifact"
    if data.get("kind") != expected_kind:
        return False, "artifact-kind"
    if data.get("artifact_sha256") != expected_hash:
        return False, "artifact-hash"
    return True, "hit"


def artifact_digest(payload: Dict[str, object]) -> str:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    return sha256_bytes(text.encode("utf-8"))


def closure_key_for(
    *,
    path: str,
    closure: Sequence[str],
    plans: Mapping[str, ModulePlan],
    tool_hash: str,
    seed_digest: Optional[FileDigest],
    fuel: str,
) -> str:
    return hash_json(
        {
            "kind": "ouro.selfhost-module.closure.v1",
            "path": path,
            "closure": [{"path": u, "direct_key": plans[u].direct_key} for u in closure],
            "tool_hash": tool_hash,
            "seed": asdict(seed_digest) if seed_digest else None,
            "fuel": fuel,
        }
    )


def reverse_dependency_closure(changed: Sequence[str], modules: Sequence[str], plans: Mapping[str, ModulePlan]) -> List[str]:
    rev: Dict[str, List[str]] = {m: [] for m in modules}
    for mod in modules:
        for imp in plans[mod].imports:
            rev.setdefault(imp, []).append(mod)
    seen = set(changed)
    stack = list(changed)
    while stack:
        cur = stack.pop()
        for user in rev.get(cur, ()):
            if user in seen:
                continue
            seen.add(user)
            stack.append(user)
    return [mod for mod in modules if mod in seen]


def phase_keys_for(path: str, direct_key: str, closure_key: str) -> dict:
    return {
        "parse": hash_json({"phase": "parse", "path": path, "direct_key": direct_key}),
        "import": hash_json({"phase": "import", "path": path, "direct_key": direct_key}),
        "elab": hash_json({"phase": "elab", "path": path, "closure_key": closure_key}),
        "lower": hash_json({"phase": "lower", "path": path, "closure_key": closure_key}),
        "extract": hash_json({"phase": "extract", "path": path, "closure_key": closure_key}),
    }


def materialize_module_artifacts(
    *,
    roots: Sequence[str],
    work: Path,
    cache_root: Path,
    cache_enabled: bool = True,
    report_path: Optional[Path] = None,
    unit_graph: Optional[Mapping[str, Sequence[str]]] = None,
    label: str = "selfhost",
    seed: Optional[Path] = None,
    fuel: str = "",
    tool_inputs: Sequence[Path] = (),
    parse_bytes: ImportBytesParser | None = None,
) -> dict:
    started = Timer()
    roots_norm = [normalize_path(r) for r in roots]
    if not roots_norm:
        raise SystemExit("MODULE_CACHE: FAIL no roots")
    graph: Dict[str, List[str]] = {}
    if unit_graph is not None:
        for k, v in unit_graph.items():
            graph[normalize_path(k)] = [normalize_path(x) for x in v]
    for root in roots_norm:
        if root not in graph:
            graph[root] = collect_units(root)
    modules = ordered_union(graph[root] for root in roots_norm)
    work.mkdir(parents=True, exist_ok=True)
    schema = "v1"
    tool_hash, tool_meta = tool_digest(tool_inputs, schema=schema)
    seed_digest = file_digest(seed) if seed is not None and seed.exists() else None
    plans = make_module_plans(modules, tool_hash, parse_bytes=parse_bytes)

    for root in roots_norm:
        if root not in plans:
            raise SystemExit(f"MODULE_CACHE: FAIL import closure omits root {root}")
    old_manifest = read_json_object_or_none(work / "selfhost-module-cache.json")
    old_modules = old_manifest.get("modules", []) if isinstance(old_manifest, dict) else []
    old_by_path: Dict[str, dict] = {m.get("path"): m for m in old_modules if isinstance(m, dict) and isinstance(m.get("path"), str)}

    cache_dir = cache_root / "selfhost-modules"
    direct_dir = cache_dir / "direct"
    closure_dir = cache_dir / "closure"
    if cache_enabled:
        direct_dir.mkdir(parents=True, exist_ok=True)
        closure_dir.mkdir(parents=True, exist_ok=True)

    direct_hits = 0
    direct_misses = 0
    closure_hits = 0
    closure_misses = 0
    direct_changed: List[str] = []
    closure_changed: List[str] = []
    module_reports: List[dict] = []
    phase_totals: Dict[str, Dict[str, int]] = {p: {"hits": 0, "misses": 0} for p in ("parse", "import", "elab", "lower", "extract")}

    closure_keys: Dict[str, str] = {}
    closure_lists: Dict[str, List[str]] = {}
    for mod, closure in _iter_planned_closures(modules, plans):
        if mod in graph and closure != graph[mod]:
            raise SystemExit(f"MODULE_CACHE: FAIL ordered import closure changed for {mod}")
        closure_lists[mod] = closure
        closure_keys[mod] = closure_key_for(path=mod, closure=closure, plans=plans, tool_hash=tool_hash, seed_digest=seed_digest, fuel=fuel)

    closure_entries = {}
    if cache_enabled:
        closure_entries = {
            mod: {"path": mod, "direct_key": plan.direct_key, "source": asdict(plan.source)}
            for mod, plan in plans.items()
        }
    seed_entry = asdict(seed_digest) if seed_digest else None
    for mod in modules:
        t0 = Timer()
        plan = plans[mod]
        old = old_by_path.get(mod, {})
        direct_cache_path = direct_dir / f"{filename_fragment(mod, 24, 'module')}__{plan.direct_key}.json"
        direct_cache = "disabled"
        direct_reason = "cache-disabled"
        if cache_enabled:
            direct_payload: Dict[str, object] = {
                "kind": "ouro.selfhost-module-direct-artifact.v1",
                "label": label,
                "path": mod,
                "source": closure_entries[mod]["source"],
                "imports": list(plan.imports),
                "decls": list(plan.decls),
                "direct_key": plan.direct_key,
                "tool_hash": tool_hash,
            }
            direct_artifact_hash = artifact_digest(direct_payload)
            ok, reason = artifact_cache_state(direct_cache_path, direct_artifact_hash, "ouro.selfhost-module-direct-artifact.v1")
            if ok:
                direct_cache = "hit"
                direct_reason = reason
                direct_hits += 1
            else:
                direct_cache = "miss"
                direct_reason = "source-or-import-changed" if old.get("direct_key") and old.get("direct_key") != plan.direct_key else reason
                write_json_if_changed(direct_cache_path, {**direct_payload, "artifact_sha256": direct_artifact_hash})
                direct_misses += 1
        else:
            direct_misses += 1
        if old.get("direct_key") != plan.direct_key:
            direct_changed.append(mod)

        ckey = closure_keys[mod]
        phase_keys = phase_keys_for(mod, plan.direct_key, ckey)
        closure_cache_path = closure_dir / f"{filename_fragment(mod, 24, 'module')}__{ckey}.json"
        closure_cache = "disabled"
        closure_reason = "cache-disabled"
        if cache_enabled:
            closure_payload: Dict[str, object] = {
                "kind": "ouro.selfhost-module-closure-artifact.v1",
                "label": label,
                "path": mod,
                "root": mod,
                "closure": [closure_entries[u] for u in closure_lists[mod]],
                "closure_key": ckey,
                "phase_keys": phase_keys,
                "tool_hash": tool_hash,
                "seed": seed_entry,
                "fuel": fuel,
            }
            closure_artifact_hash = artifact_digest(closure_payload)
            ok, reason = artifact_cache_state(closure_cache_path, closure_artifact_hash, "ouro.selfhost-module-closure-artifact.v1")
            if ok:
                closure_cache = "hit"
                closure_reason = reason
                closure_hits += 1
            else:
                closure_cache = "miss"
                closure_reason = "import-closure-changed" if old.get("closure_key") and old.get("closure_key") != ckey else reason
                write_json_if_changed(closure_cache_path, {**closure_payload, "artifact_sha256": closure_artifact_hash})
                closure_misses += 1
        else:
            closure_misses += 1
        if old.get("closure_key") != ckey:
            closure_changed.append(mod)

        for phase in ("parse", "import"):
            phase_totals[phase]["hits" if direct_cache == "hit" else "misses"] += 1
        for phase in ("elab", "lower", "extract"):
            phase_totals[phase]["hits" if closure_cache == "hit" else "misses"] += 1

        module_reports.append(
            {
                "path": mod,
                "source_sha256": plan.source.sha256,
                "bytes": plan.source.bytes,
                "imports": list(plan.imports),
                "decl_count": len(plan.decls),
                "closure": closure_lists[mod],
                "closure_size": len(closure_lists[mod]),
                "direct_key": plan.direct_key,
                "closure_key": ckey,
                "direct_cache": direct_cache,
                "direct_reason": direct_reason,
                "closure_cache": closure_cache,
                "closure_reason": closure_reason,
                "phase_keys": phase_keys,
                "direct_cache_path": rel(direct_cache_path) if cache_enabled else "",
                "closure_cache_path": rel(closure_cache_path) if cache_enabled else "",
                "elapsed_s": round(t0.elapsed(), 6),
            }
        )

    impacted = reverse_dependency_closure(direct_changed, modules, plans) if direct_changed else []
    direct_changed_paths = set(direct_changed)
    closure_changed_paths = set(closure_changed)
    root_reports: List[dict] = []
    affected_roots: List[str] = []
    for root in roots_norm:
        closure = graph[root]
        direct_changes = [m for m in closure if m in direct_changed_paths]
        closure_changes = [m for m in closure if m in closure_changed_paths]
        affected = bool(direct_changes or closure_changes)
        if affected:
            affected_roots.append(root)
        root_reports.append(
            {
                "root": root,
                "closure_size": len(closure),
                "direct_changed_modules": direct_changes,
                "closure_changed_modules": closure_changes,
                "affected": affected,
                "root_closure_key": closure_keys[root] if root in closure_keys else "",
            }
        )

    manifest = {
        "kind": "ouro.selfhost-module-cache-report.v1",
        "label": label,
        "roots": roots_norm,
        "unit_graph": graph,
        "cache_enabled": cache_enabled,
        "cache_root": rel(cache_dir),
        "tool_hash": tool_hash,
        "tool_meta": tool_meta,
        "seed": seed_entry,
        "fuel": fuel,
        "summary": {
            "modules": len(modules),
            "roots": len(roots_norm),
            "direct_hits": direct_hits,
            "direct_misses": direct_misses,
            "closure_hits": closure_hits,
            "closure_misses": closure_misses,
            "phase_hits": {k: v["hits"] for k, v in phase_totals.items()},
            "phase_misses": {k: v["misses"] for k, v in phase_totals.items()},
            "direct_changed_modules": direct_changed,
            "closure_changed_modules": closure_changed,
            "affected_modules": impacted,
            "affected_roots": affected_roots,
            "elapsed_s": round(started.elapsed(), 6),
        },
        "roots_report": root_reports,
        "modules": module_reports,
    }
    manifest_path = work / "selfhost-module-cache.json"
    manifest_write = write_json_if_changed(manifest_path, manifest)
    manifest["manifest_path"] = rel(manifest_path)
    manifest["manifest_write"] = manifest_write
    if report_path is not None:
        write_json_if_changed(report_path, manifest)
    return manifest


def discover_default_roots() -> List[str]:
    roots = [
        "compiler/lexer.ouro",
        "compiler/parse_a.ouro",
        "compiler/parse_b.ouro",
        "compiler/parser_file.ouro",
        "compiler/desugar_match.ouro",
        "compiler/import_resolve.ouro",
        "compiler/lower_rewrite.ouro",
        "compiler/lower.ouro",
        "compiler/elab.ouro",
        "compiler/compiler.ouro",
        "compiler/preprocess_import.ouro",
        "compiler/preprocess_record.ouro",
        "compiler/pipeline.ouro",
        "compiler/backend.ouro",
    ]
    return [r for r in roots if (ROOT / r).is_file()]


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="materialize deterministic Ouro selfhost module cache artifacts")
    ap.add_argument("--root", action="append", dest="roots", help="root .ouro module; may be repeated")
    ap.add_argument("--work", type=Path, default=Path(os.environ.get("OURO_MODULE_CACHE_WORK", "_build/selfhost_module_cache")))
    ap.add_argument("--cache-root", type=Path, default=Path(os.environ.get("OURO_CACHE_DIR", "_cache/ouro")))
    ap.add_argument("--report", type=Path, default=None)
    ap.add_argument("--label", default="selfhost")
    ap.add_argument("--seed", type=Path, default=None)
    ap.add_argument("--fuel", default=os.environ.get("OURO1_CHECK_FUEL", "16000"))
    cache_group = ap.add_mutually_exclusive_group()
    cache_group.add_argument("--cache", dest="cache_enabled", action="store_true")
    cache_group.add_argument("--no-cache", dest="cache_enabled", action="store_false")
    ap.set_defaults(cache_enabled=bool_env(os.environ.get("OURO_CACHE"), True))
    args = ap.parse_args(argv)
    roots = args.roots or discover_default_roots()
    if not roots:
        print("MODULE_CACHE: FAIL no roots", file=sys.stderr)
        return 1
    work = args.work if args.work.is_absolute() else ROOT / args.work
    cache_root = args.cache_root if args.cache_root.is_absolute() else ROOT / args.cache_root
    seed = args.seed if args.seed is not None and args.seed.is_absolute() else (ROOT / args.seed if args.seed is not None else None)
    try:
        report = materialize_module_artifacts(
            roots=roots,
            work=work,
            cache_root=cache_root,
            cache_enabled=bool(args.cache_enabled),
            report_path=args.report if args.report is None or args.report.is_absolute() else ROOT / args.report,
            label=args.label,
            seed=seed,
            fuel=str(args.fuel),
            tool_inputs=(),
        )
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"MODULE_CACHE: FAIL {exc}", file=sys.stderr)
        return 1
    summary = report["summary"]
    print(
        "MODULE_CACHE: OK "
        f"modules={summary['modules']} direct_hits={summary['direct_hits']} direct_misses={summary['direct_misses']} "
        f"closure_hits={summary['closure_hits']} closure_misses={summary['closure_misses']} "
        f"affected_roots={len(summary['affected_roots'])} elapsed={summary['elapsed_s']}s"
    )
    print(json.dumps({"summary": summary, "manifest_path": report.get("manifest_path")}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
