#!/usr/bin/env python3
"""Deterministic generated-C sharding for Ouro bootstrap builds.

This helper is deliberately build-system-only: it consumes already generated C
artifacts and emits cacheable C translation-unit shards.  It does not interpret
Ouro source or rewrite compiler semantics.
"""
from __future__ import annotations

import argparse
import codecs
import hashlib
import json
import os
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from repo_support import filename_fragment
from repo_support import hash_json, sha256_bytes
from repo_support import bind_relative_path, sha256_file

ROOT = Path(__file__).resolve().parents[1]
rel = bind_relative_path(ROOT, resolve=False)

FRONTEND_MARK = re.compile(r"(?m)^/\* ---- frontend TU module=([A-Za-z0-9_]+) ---- \*/\n?")
BACKEND_PROTO = re.compile(r"^static ouro_v \*(ouro_g[0-9]+(?:_d[0-9]+)?)\(void\);\s*$")
BACKEND_G_DEF = re.compile(r"^static ouro_v \*(ouro_g[0-9]+(?:_d[0-9]+)?)\(void\)\{")
BACKEND_CACHE = re.compile(r"^static ouro_v \*(ouro_c[0-9]+);\s*$")
BACKEND_CLUSTER_PREFIXES = ("static ouro_v *ouro_g", "static ouro_v *ouro_c")
BACKEND_INCLUDE = re.compile(r'^#include "[A-Za-z0-9_./-]+\.h"$')
BACKEND_DECL = re.compile(r"^ouro_v \*ouro_[A-Za-z0-9_]+\([^;{}]*\);\s*$")
BACKEND_LOCAL_DEF = re.compile(r"^static ouro_v \*ouro_[ft][A-Za-z0-9_]+\([^;{}]*\)\{")
BACKEND_EXPORT_PREFIXES = ("int ", "const char *", "ouro_v *")
BACKEND_EXPORT_DEF = re.compile(r"(ouro_export_(?:count|name|value)[A-Za-z0-9_]*)\([^;\n]*\)\{")
FRONTEND_SPLIT_BYTES = 1024 * 1024
FRONTEND_PIECE_BYTES = 512 * 1024
C_LITERAL = re.compile(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'')


def file_digest(path: Path) -> dict:
    st = path.stat()
    return {"path": rel(path), "sha256": sha256_file(path), "bytes": st.st_size}




def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="surrogateescape")


def _read_normalized_source(path: Path, chunk_bytes: int, *, retain_text: bool) -> Tuple[str, dict]:
    if chunk_bytes <= 0:
        raise ValueError("generated C read size must be positive")
    digest = hashlib.sha256()
    byte_count = 0
    decoder = codecs.getincrementaldecoder("utf-8")(errors="surrogateescape") if retain_text else None
    parts: list[str] = []
    previous_cr = False
    with path.open("rb") as source:
        while data := source.read(chunk_bytes):
            # The prior chunk already emitted LF for a trailing CR.
            if previous_cr and data.startswith(b"\n"):
                data = data[1:]
            previous_cr = data.endswith(b"\r")
            if b"\r" in data:
                data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            digest.update(data)
            byte_count += len(data)
            if decoder is not None:
                parts.append(decoder.decode(data))
    if decoder is not None:
        parts.append(decoder.decode(b"", final=True))
    return "".join(parts), {
        "path": rel(path),
        "sha256": digest.hexdigest(),
        "bytes": byte_count,
    }


def read_source_text_digest(path: Path, *, chunk_bytes: int = 1024 * 1024) -> Tuple[str, dict]:
    return _read_normalized_source(path, chunk_bytes, retain_text=True)


def read_normalized_source_digest(path: Path, *, chunk_bytes: int = 1024 * 1024) -> dict:
    return _read_normalized_source(path, chunk_bytes, retain_text=False)[1]


def write_text_if_changed(path: Path, text: str) -> str:
    """Atomically install text.  Return updated/unchanged without touching mtime on hits."""
    return write_bytes_if_changed(path, text.encode("utf-8", errors="surrogateescape"))


def write_bytes_if_changed(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        chunk_size = 1024 * 1024
        try:
            with path.open("rb") as existing:
                for offset in range(0, len(data), chunk_size):
                    size = min(chunk_size, len(data) - offset)
                    chunk = existing.read(size)
                    if len(chunk) != size or not data.startswith(chunk, offset):
                        break
                else:
                    if not existing.read(1):
                        return "unchanged"
        except OSError:
            pass
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}.{time.time_ns()}")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return "updated"


def write_json_if_changed(path: Path, data: object) -> str:
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    return write_text_if_changed(path, text)


def read_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    try:
        n = int(raw, 10)
    except ValueError:
        return default
    return max(1, n)


@dataclass(frozen=True)
class ShardPlan:
    label: str
    path: Path
    content: bytes
    role: str
    boundary: str
    provenance: str
    symbols: Tuple[str, ...] = ()
    deps: Tuple[str, ...] = ()
    compile: bool = True

    def meta(self) -> dict:
        return {
            "label": self.label,
            "path": rel(self.path),
            "role": self.role,
            "boundary": self.boundary,
            "provenance": self.provenance,
            "symbols": list(self.symbols),
            "deps": list(self.deps),
            "compile": self.compile,
            "sha256": sha256_bytes(self.content),
            "bytes": len(self.content),
        }


def generator_digest(settings: Mapping[str, object]) -> str:
    script = ROOT / "scripts/generated_c_shards.py"
    return hash_json(
        {
            "kind": "ouro.generated-c-sharder.v1",
            "script": file_digest(script) if script.exists() else {},
            "settings": dict(sorted(settings.items())),
        }
    )


def banner(*, role: str, label: str, generator_hash: str, content_hash: str, boundary: str, provenance: str) -> str:
    return (
        "/* Ouro generated-C shard.\n"
        "   Source artifact stays canonical; do not hand-edit this shard.\n"
        f"   role={role} label={label} boundary={boundary}\n"
        f"   provenance={provenance}\n"
        f"   generator_hash={generator_hash}\n"
        f"   content_hash={content_hash}\n"
        " */\n"
    )


def bannered_bytes(body: str, *, role: str, label: str, generator_hash: str, boundary: str, provenance: str) -> bytes:
    raw = body.encode("utf-8", errors="surrogateescape")
    header = banner(
        role=role,
        label=label,
        generator_hash=generator_hash,
        content_hash=sha256_bytes(raw),
        boundary=boundary,
        provenance=provenance,
    ).encode("utf-8", errors="surrogateescape")
    if len(body) > 1 and body.endswith("\n") and not body[-2].isspace():
        return header + raw
    for padding in ("\n\n", "\n\n\n"):
        padding_size = len(padding)
        if (len(body) > padding_size and body.endswith(padding)
                and not body[-padding_size - 1].isspace()):
            # Each trailing LF occupies one byte in raw.
            return b"".join((header, memoryview(raw)[:-padding_size], b"\n"))
    trimmed = body.rstrip()
    payload = raw if len(trimmed) == len(body) else trimmed.encode("utf-8", errors="surrogateescape")
    return b"".join((header, payload, b"\n"))


def frontend_lines(src: str, start: int, end: int) -> List[str]:
    # str.splitlines would also split inside C string literals at form feeds and similar separators.
    lines: List[str] = []
    position = start
    while position < end:
        newline = src.find("\n", position, end)
        stop = end if newline < 0 else newline + 1
        lines.append(src[position:stop])
        position = stop
    return lines


def braces_balanced(line: str) -> bool:
    code = C_LITERAL.sub("", line) if '"' in line or "'" in line else line
    return code.count("{") == code.count("}")


def split_frontend_module(
    frontend_c: Path,
    src: str,
    span: Tuple[int, int],
    module: str,
    index: int,
    out_dir: Path,
    label_prefix: str,
    generator_hash: str,
    piece_bytes: int,
) -> Tuple[List[ShardPlan], str]:
    """Split one module chunk into compile pieces, or return no plans and the reason to keep it whole.

    Every line must be a recognized top-level item. Getters become external and
    are declared in a module header; a helper or cache stays static unless
    another piece references it.
    """
    escaped = re.escape(module)
    getter = rf"ouro_{escaped}_g[0-9][A-Za-z0-9_]*"
    getter_proto = re.compile(rf"static ouro_v \*({getter})\(void\);")
    cache_decl = re.compile(rf"static ouro_v \*(ouro_{escaped}_c[0-9][A-Za-z0-9_]*);")
    getter_def = re.compile(rf"static ouro_v \*({getter})\(void\)\{{")
    helper_def = re.compile(rf"static ouro_v \*(ouro_{escaped}_[ft][0-9][A-Za-z0-9_]*)\(([^;{{}}()]*)\)\{{")
    # Matching inside a longer identifier or a literal can only add a promotion or force the fallback.
    symbol = re.compile(rf"ouro_{escaped}_[gftc][0-9][A-Za-z0-9_]*")
    name_case = r'case [0-9]+: return "(?:[^"\\]|\\.)*";'
    value_case = rf"case [0-9]+: return {getter}\(\);"
    export_forms = (
        ("C", re.compile(rf"int ouro_export_count_{escaped}\(void\)\{{return [0-9]+;\}}")),
        ("N", re.compile(rf"const char \*ouro_export_name_{escaped}\(int i\)\{{switch\(i\)\{{(?:{name_case})?")),
        ("n", re.compile(name_case)),
        ("E", re.compile(r'\}return "(?:[^"\\]|\\.)*";\}')),
        ("V", re.compile(rf"ouro_v \*ouro_export_value_{escaped}\(int i\)\{{switch\(i\)\{{(?:{value_case})?")),
        ("v", re.compile(value_case)),
        ("F", re.compile(r"\}return 0;\}")),
        ("b", re.compile("")),
    )
    lines = frontend_lines(src, *span)

    def where(position: int) -> int:
        return src.count("\n", 0, span[0]) + position + 1

    prelude: List[str] = []
    getters: Dict[str, None] = {}
    position = 1
    while position < len(lines):
        text = lines[position].rstrip("\n")
        proto = getter_proto.fullmatch(text)
        if proto is not None:
            getters[proto.group(1)] = None
        elif BACKEND_INCLUDE.fullmatch(text) or BACKEND_DECL.fullmatch(text):
            prelude.append(text + "\n")
        elif text:
            break
        position += 1
    body_start = position
    roles: List[str] = []
    names: List[str] = []
    helper_lines: Dict[str, int] = {}
    helper_params: Dict[str, str] = {}
    cache_lines: Dict[str, int] = {}
    defined: set[str] = set()
    while position < len(lines):
        text = lines[position].rstrip("\n")
        if export_forms[0][1].fullmatch(text):
            break
        cache = cache_decl.fullmatch(text)
        if cache is not None:
            role, name = "cache", cache.group(1)
            cache_lines.setdefault(name, position)
        else:
            definition = getter_def.match(text) or helper_def.match(text)
            if definition is None or not text.endswith("}") or not braces_balanced(text):
                return [], f"unrecognized line {where(position)}"
            name = definition.group(1)
            if name in defined:
                return [], f"duplicate definition {name} at line {where(position)}"
            defined.add(name)
            if definition.re is getter_def:
                role = "getter"
                getters[name] = None
            else:
                role = "helper"
                helper_lines[name] = position
                helper_params[name] = definition.group(2)
        roles.append(role)
        names.append(name)
        position += 1
    tail_start = position
    if tail_start == len(lines):
        return [], "missing export table"
    shape = []
    for position in range(tail_start, len(lines)):
        text = lines[position].rstrip("\n")
        letter = next((letter for letter, form in export_forms if form.fullmatch(text)), None)
        if letter is None:
            return [], f"unrecognized export line {where(position)}"
        shape.append(letter)
    if re.fullmatch("CNn*EVv*Fb*", "".join(shape)) is None:
        return [], "unexpected export table layout"

    # A cluster ends at a getter; clusters larger than a piece are split between lines.
    ranges: List[Tuple[int, int]] = []
    piece_start, piece_size = body_start, 0
    cluster_start, cluster_size = body_start, 0
    for position in range(body_start, tail_start):
        cluster_size += len(lines[position])
        if roles[position - body_start] != "getter" and position + 1 < tail_start:
            continue
        units = ([(cluster_start, cluster_size)] if cluster_size <= piece_bytes
                 else [(line, len(lines[line])) for line in range(cluster_start, position + 1)])
        for unit_start, unit_size in units:
            if piece_size and piece_size + unit_size > piece_bytes:
                ranges.append((piece_start, unit_start))
                piece_start, piece_size = unit_start, 0
            piece_size += unit_size
        cluster_start, cluster_size = position + 1, 0
    if piece_start < tail_start:
        ranges.append((piece_start, tail_start))
    if len(ranges) < 2:
        return [], "fewer than two pieces"

    piece_of: List[int] = []
    for number, (first, stop) in enumerate(ranges):
        piece_of.extend([number] * (stop - first))
    helper_piece = {name: piece_of[line - body_start] for name, line in helper_lines.items()}
    cache_pieces: Dict[str, set[int]] = {name: set() for name in cache_lines}
    promoted: set[str] = set()
    for position in range(body_start, len(lines)):
        piece = piece_of[position - body_start] if position < tail_start else len(ranges)
        for name in symbol.findall(lines[position]):
            if name in helper_piece:
                if helper_piece[name] != piece:
                    promoted.add(name)
            elif name in cache_pieces:
                cache_pieces[name].add(piece)
            elif name not in getters:
                return [], f"unresolved reference {name} at line {where(position)}"
    # With -fno-common a shared cache needs exactly one non-static definition.
    shared = {name for name, pieces in cache_pieces.items() if len(pieces) > 1}

    stem = f"frontend__{index:03d}_{filename_fragment(module, 120, 'shard')}"
    header_name = f"{stem}__shards.h"
    guard = f"OURO_GENERATED_FRONTEND_{module.upper()}_SHARDS_H"
    header = [
        "/* Ouro generated frontend shard header. Do not hand-edit. */\n",
        f"/* module={module} generator_hash={generator_hash} */\n",
        f"#ifndef {guard}\n",
        f"#define {guard}\n",
    ]
    if '#include "ouro_rt.h"\n' not in prelude:
        header.append('#include "ouro_rt.h"\n')
    header.extend(prelude)
    header.extend(f"extern ouro_v *{name};\n" for name in cache_lines if name in shared)
    header.extend(f"ouro_v *{name}({helper_params[name]});\n" for name in helper_lines if name in promoted)
    header.extend(f"ouro_v *{name}(void);\n" for name in getters)
    header.append("#endif\n")
    module_label = f"{label_prefix}/frontend/{module}"
    provenance = f"{rel(frontend_c)}#module={module}"
    plans = [
        ShardPlan(
            label=f"{module_label}/header",
            path=out_dir / header_name,
            content="".join(header).encode("utf-8", errors="surrogateescape"),
            role="frontend",
            boundary=f"frontend-module-header:{module}",
            provenance=provenance,
            symbols=(module,),
            compile=False,
        )
    ]
    include = f'#include "{header_name}"\n'
    for number, (first, stop) in enumerate(ranges):
        raw = [include]
        external: List[str] = []
        for position in range(first, stop):
            line = lines[position]
            role, name = roles[position - body_start], names[position - body_start]
            if role == "getter" or name in promoted or (name in shared and cache_lines[name] == position):
                raw.append(line[len("static "):])
                external.append(name)
            elif name in shared:
                raw.append(f"/* shared generated cache declared in header: {name} */\n")
            else:
                raw.append(line)
        items = f"{names[first - body_start]}..{names[stop - 1 - body_start]}"
        label = f"{module_label}/p{number:02d}"
        boundary = f"frontend-module-items:{module}:{items}"
        piece_provenance = f"{provenance}&items={items}"
        plans.append(
            ShardPlan(
                label=label,
                path=out_dir / f"{stem}__p{number:02d}.c",
                content=bannered_bytes(
                    "".join(raw),
                    role="frontend",
                    label=label,
                    generator_hash=generator_hash,
                    boundary=boundary,
                    provenance=piece_provenance,
                ),
                role="frontend",
                boundary=boundary,
                provenance=piece_provenance,
                symbols=tuple(external),
                deps=(header_name,),
            )
        )
    label = f"{module_label}/exports"
    boundary = f"frontend-module-exports:{module}"
    export_provenance = f"{provenance}&exports"
    plans.append(
        ShardPlan(
            label=label,
            path=out_dir / f"{stem}__exports.c",
            content=bannered_bytes(
                include + "".join(lines[tail_start:]),
                role="frontend",
                label=label,
                generator_hash=generator_hash,
                boundary=boundary,
                provenance=export_provenance,
            ),
            role="frontend",
            boundary=boundary,
            provenance=export_provenance,
            symbols=tuple(f"ouro_export_{kind}_{module}" for kind in ("count", "name", "value")),
            deps=(header_name,),
        )
    )
    return plans, "split"


def frontend_shards(
    frontend_c: Path,
    src: str,
    out_dir: Path,
    label_prefix: str,
    generator_hash: str,
    *,
    split_bytes: int = FRONTEND_SPLIT_BYTES,
    piece_bytes: int = FRONTEND_PIECE_BYTES,
    fallbacks: Optional[List[dict]] = None,
) -> List[ShardPlan]:
    matches = list(FRONTEND_MARK.finditer(src))
    plans: List[ShardPlan] = []
    if not matches:
        label = f"{label_prefix}/frontend"
        body = src
        if '#include "ouro_rt.h"' not in body:
            body = '#include "ouro_rt.h"\n' + body
        content = bannered_bytes(
            body,
            role="frontend",
            label=label,
            generator_hash=generator_hash,
            boundary="whole-file-fallback",
            provenance=rel(frontend_c),
        )
        plans.append(
            ShardPlan(
                label=label,
                path=out_dir / "frontend__whole.c",
                content=content,
                role="frontend",
                boundary="whole-file-fallback",
                provenance=rel(frontend_c),
            )
        )
        return plans

    module_counts = Counter(m.group(1) for m in matches)
    for i, m in enumerate(matches):
        module = m.group(1)
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(src)
        if end - start > split_bytes:
            if module_counts[module] == 1:
                pieces, reason = split_frontend_module(frontend_c, src, (start, end), module, i, out_dir,
                                                       label_prefix, generator_hash, piece_bytes)
            else:
                pieces, reason = [], "duplicate module marker"
            if pieces:
                plans.extend(pieces)
                continue
            if fallbacks is not None:
                fallbacks.append({"module": module, "reason": reason})
        chunk = src[start:end].lstrip()
        if '#include "ouro_rt.h"' not in chunk:
            chunk = '#include "ouro_rt.h"\n' + chunk
        label = f"{label_prefix}/frontend/{module}"
        content = bannered_bytes(
            chunk,
            role="frontend",
            label=label,
            generator_hash=generator_hash,
            boundary=f"frontend-module:{module}",
            provenance=f"{rel(frontend_c)}#module={module}",
        )
        plans.append(
            ShardPlan(
                label=label,
                path=out_dir / f"frontend__{i:03d}_{filename_fragment(module, 120, 'shard')}.c",
                content=content,
                role="frontend",
                boundary=f"frontend-module:{module}",
                provenance=f"{rel(frontend_c)}#module={module}",
                symbols=(module,),
            )
        )
    return plans


def line_offsets(lines: Sequence[str]) -> List[int]:
    offsets: List[int] = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line)
    return offsets


def scan_backend_prelude(lines: Sequence[str]) -> Tuple[int, List[str]]:
    declarations = []
    for index, line in enumerate(lines):
        text = line.strip()
        if not text or text == '#include "ouro_rt.h"' or BACKEND_PROTO.fullmatch(text):
            continue
        if not (BACKEND_INCLUDE.fullmatch(text) or BACKEND_DECL.fullmatch(text)):
            return index, declarations
        declarations.append(line)
    return len(lines), declarations


def transform_backend_cluster(
    lines: Sequence[str],
    shared_cache_lines: Mapping[int, str],
    getter_name: str,
    *,
    start: int,
    end: int,
    out: List[str],
) -> None:
    # The final line is the getter found when the cluster was indexed.
    for index in range(start, end - 1):
        shared = shared_cache_lines.get(index)
        if shared is None:
            out.append(lines[index])
        else:
            out.append(f"/* shared duplicate generated cache declared in header: {shared} */\n")
    definition = f"ouro_v *{getter_name}(void){{"
    out.append(lines[end - 1].replace("static " + definition, definition, 1))


def backend_header(g_names: Sequence[str], duplicate_caches: Sequence[str], generator_hash: str,
                   *, declarations: str = "", export_suffix: str = "_be") -> str:
    lines = [
        "/* Ouro generated backend shard header. Do not hand-edit. */\n",
        f"/* generator_hash={generator_hash} */\n",
        "#ifndef OURO_GENERATED_BACKEND_SHARDS_H\n",
        "#define OURO_GENERATED_BACKEND_SHARDS_H\n",
        "#include \"ouro_rt.h\"\n",
        declarations,
    ]
    for c in duplicate_caches:
        lines.append(f"extern ouro_v *{c};\n")
    for g in g_names:
        lines.append(f"ouro_v *{g}(void);\n")
    lines.extend(
        [
            f"int ouro_export_count{export_suffix}(void);\n",
            f"const char *ouro_export_name{export_suffix}(int i);\n",
            f"ouro_v *ouro_export_value{export_suffix}(int i);\n",
            "#endif\n",
        ]
    )
    return "".join(lines)


def _backend_export_names(src: str) -> list[str]:
    prefix_width = max(map(len, BACKEND_EXPORT_PREFIXES))
    exports = []
    # Only inspect the return-type prefix before each literal marker.
    for marker in re.finditer("ouro_export_", src):
        position = marker.start()
        start = src.rfind("\n", max(0, position - prefix_width - 1), position) + 1
        if position - start <= prefix_width and src[start:position] in BACKEND_EXPORT_PREFIXES:
            match = BACKEND_EXPORT_DEF.match(src, position)
            if match is not None:
                exports.append(match[1])
    return exports


def backend_shards(
    backend_c: Path,
    src: str,
    out_dir: Path,
    label_prefix: str,
    generator_hash: str,
    group_size: int,
    *,
    export_suffix: str = "_be",
) -> List[ShardPlan]:
    if re.fullmatch(r"(?:_[A-Za-z0-9_]+)?", export_suffix) is None:
        raise ValueError("unsupported generated backend export suffix")
    lines = src.splitlines(keepends=True)
    if not lines:
        return []
    start_idx, declarations = scan_backend_prelude(lines)
    clusters: List[Tuple[str, int, int]] = []
    cluster_start = start_idx
    g_names: List[str] = []
    seen_g: set[str] = set()
    first_cache_indices: Dict[str, int] = {}
    duplicate_caches: set[str] = set()
    shared_cache_lines: Dict[int, str] = {}
    for idx in range(start_idx, len(lines)):
        line = lines[idx].lstrip()
        if not line.startswith(BACKEND_CLUSTER_PREFIXES):
            continue
        gm = BACKEND_G_DEF.match(line)
        if gm:
            name = gm.group(1)
            clusters.append((name, cluster_start, idx + 1))
            cluster_start = idx + 1
            if name not in seen_g:
                seen_g.add(name)
                g_names.append(name)
            continue
        cm = BACKEND_CACHE.match(line)
        if cm:
            name = cm.group(1)
            first = first_cache_indices.setdefault(name, idx)
            if first != idx:
                duplicate_caches.add(name)
                shared_cache_lines[first] = shared_cache_lines[idx] = name
    del first_cache_indices
    if not clusters:
        label = f"{label_prefix}/backend"
        provenance = rel(backend_c)
        body = src
        if '#include "ouro_rt.h"' not in body:
            body = '#include "ouro_rt.h"\n' + body
        content = bannered_bytes(
            body,
            role="backend",
            label=label,
            generator_hash=generator_hash,
            boundary="whole-file-fallback",
            provenance=provenance,
        )
        return [
            ShardPlan(
                label=label,
                path=out_dir / "backend__whole.c",
                content=content,
                role="backend",
                boundary="whole-file-fallback",
                provenance=provenance,
            )
        ]

    first = lines[start_idx].strip()
    if not (BACKEND_CACHE.fullmatch(first) or BACKEND_G_DEF.match(first) or BACKEND_LOCAL_DEF.match(first)):
        raise ValueError("unsupported generated backend prelude: " + first[:120])
    export_symbols = tuple(f"ouro_export_{kind}{export_suffix}" for kind in ("count", "name", "value"))
    found_exports = _backend_export_names(src)
    if sorted(found_exports) != sorted(export_symbols):
        raise ValueError("generated backend export table does not match its suffix")
    source_label = rel(backend_c)
    dup_sorted = sorted(duplicate_caches)
    header_name = "backend_u__shards.h"
    header_body = backend_header(g_names, dup_sorted, generator_hash,
                                 declarations="".join(declarations), export_suffix=export_suffix)
    plans: List[ShardPlan] = [
        ShardPlan(
            label=f"{label_prefix}/backend/header",
            path=out_dir / header_name,
            content=header_body.encode("utf-8", errors="surrogateescape"),
            role="backend",
            boundary="backend-header",
            provenance=source_label,
            symbols=tuple(g_names),
            compile=False,
        )
    ]
    if dup_sorted:
        state_lines = [f'#include "{header_name}"\n']
        for c in dup_sorted:
            state_lines.append(f"ouro_v *{c};\n")
        content = bannered_bytes(
            "".join(state_lines),
            role="backend",
            label=f"{label_prefix}/backend/state",
            generator_hash=generator_hash,
            boundary="backend-duplicate-cache-state",
            provenance=source_label,
        )
        plans.append(
            ShardPlan(
                label=f"{label_prefix}/backend/state",
                path=out_dir / "backend__000_state.c",
                content=content,
                role="backend",
                boundary="backend-duplicate-cache-state",
                provenance=source_label,
                symbols=tuple(dup_sorted),
                deps=(header_name,),
            )
        )

    export_start = cluster_start

    shard_no = 1 if dup_sorted else 0
    for chunk_start in range(0, len(clusters), group_size):
        chunk = clusters[chunk_start : chunk_start + group_size]
        names = [name for name, _start, _end in chunk]
        raw = [f'#include "{header_name}"\n']
        for getter_name, body_start, body_end in chunk:
            transform_backend_cluster(
                lines,
                shared_cache_lines,
                getter_name,
                start=body_start,
                end=body_end,
                out=raw,
            )
        boundary = f"backend-functions:{names[0]}..{names[-1]}"
        label = f"{label_prefix}/backend/g{chunk_start:03d}-{chunk_start + len(chunk) - 1:03d}"
        provenance = f"{source_label}#functions={names[0]}..{names[-1]}"
        content = bannered_bytes(
            "".join(raw),
            role="backend",
            label=label,
            generator_hash=generator_hash,
            boundary=boundary,
            provenance=provenance,
        )
        plans.append(
            ShardPlan(
                label=label,
                path=out_dir / f"backend__{shard_no:03d}_{filename_fragment(names[0], 120, 'shard')}_{filename_fragment(names[-1], 120, 'shard')}.c",
                content=content,
                role="backend",
                boundary=boundary,
                provenance=provenance,
                symbols=tuple(names),
                deps=(header_name,),
            )
        )
        shard_no += 1

    if export_start < len(lines):
        raw = f'#include "{header_name}"\n' + "".join(
            lines[index] for index in range(export_start, len(lines))
        )
        label = f"{label_prefix}/backend/exports"
        provenance = f"{source_label}#exports"
        content = bannered_bytes(
            raw,
            role="backend",
            label=label,
            generator_hash=generator_hash,
            boundary="backend-export-table",
            provenance=provenance,
        )
        plans.append(
            ShardPlan(
                label=label,
                path=out_dir / f"backend__{shard_no:03d}_exports.c",
                content=content,
                role="backend",
                boundary="backend-export-table",
                provenance=provenance,
                symbols=export_symbols,
                deps=(header_name,),
            )
        )
    return plans


def manifest_valid(
    manifest: Optional[dict],
    *,
    generator_hash: str,
    source_digests: Mapping[str, dict],
    plan_meta: Sequence[dict],
) -> Tuple[bool, str]:
    if manifest is None:
        return False, "missing-or-invalid-manifest"
    if manifest.get("kind") != "ouro.generated-c-shards.v1":
        return False, "manifest-kind"
    if manifest.get("generator_hash") != generator_hash:
        return False, "generator-hash"
    if manifest.get("sources") != dict(source_digests):
        return False, "source-digests"
    old_shards = manifest.get("shards")
    if not isinstance(old_shards, list):
        return False, "manifest-shards"
    expected = list(plan_meta)
    comparable = [
        {k: item.get(k) for k in ("label", "path", "role", "boundary", "provenance", "symbols", "deps", "compile", "sha256", "bytes")}
        for item in old_shards
    ]
    wanted = [
        {k: item.get(k) for k in ("label", "path", "role", "boundary", "provenance", "symbols", "deps", "compile", "sha256", "bytes")}
        for item in expected
    ]
    if comparable != wanted:
        return False, "shard-metadata"
    for item in expected:
        path = ROOT / str(item["path"]) if not Path(str(item["path"])).is_absolute() else Path(str(item["path"]))
        if not path.is_file():
            return False, "missing-shard"
        try:
            if sha256_file(path) != item["sha256"]:
                return False, "shard-hash"
        except FileNotFoundError:
            return False, "missing-shard"
    return True, "hit"

def materialize_generated_c_shards(
    *,
    frontend_c: Optional[Path],
    backend_c: Path,
    out_dir: Path,
    label_prefix: str,
    cache_enabled: bool = True,  # Retained for callers.
    backend_group_size: Optional[int] = None,
    backend_export_suffix: str = "_be",
    report_path: Optional[Path] = None,
    frontend_split_bytes: Optional[int] = None,
    frontend_piece_bytes: Optional[int] = None,
) -> Tuple[List[Tuple[str, Path]], dict]:
    started = time.perf_counter()
    if frontend_c is not None:
        frontend_c = frontend_c if frontend_c.is_absolute() else ROOT / frontend_c
    backend_c = backend_c if backend_c.is_absolute() else ROOT / backend_c
    if frontend_c is not None and not frontend_c.is_file():
        raise SystemExit(f"GENERATED_C_SHARDS: FAIL missing frontend {frontend_c}")
    if not backend_c.is_file():
        raise SystemExit(f"GENERATED_C_SHARDS: FAIL missing backend {backend_c}")
    out_dir.mkdir(parents=True, exist_ok=True)
    group_size = backend_group_size or int_env("OURO_GENERATED_C_SHARD_BACKEND_GROUPS", 8)
    settings = {"backend_group_size": group_size, "schema": "v1"}
    if backend_export_suffix != "_be":
        settings["backend_export_suffix"] = backend_export_suffix
    split_bytes = frontend_split_bytes or FRONTEND_SPLIT_BYTES
    piece_bytes = frontend_piece_bytes or FRONTEND_PIECE_BYTES
    if frontend_c is None:
        settings["backend_only"] = True
    else:
        settings["frontend_split_bytes"] = split_bytes
        settings["frontend_piece_bytes"] = piece_bytes
    gen_hash = generator_digest(settings)
    plans: List[ShardPlan] = []
    source_digests = {}
    split_fallbacks: List[dict] = []
    if frontend_c is not None:
        frontend_text, frontend_digest = read_source_text_digest(frontend_c)
        plans = frontend_shards(frontend_c, frontend_text, out_dir, label_prefix, gen_hash,
                                split_bytes=split_bytes, piece_bytes=piece_bytes, fallbacks=split_fallbacks)
        source_digests["frontend"] = frontend_digest
        del frontend_text
    backend_text, backend_digest = read_source_text_digest(backend_c)
    plans.extend(backend_shards(backend_c, backend_text, out_dir, label_prefix, gen_hash, group_size,
                                export_suffix=backend_export_suffix))
    del backend_text
    source_digests["backend"] = backend_digest
    plan_meta = [plan.meta() for plan in plans]
    manifest_path = out_dir / "generated-c-shards.manifest.json"
    old_manifest = read_json(manifest_path)
    old_ok, old_reason = manifest_valid(
        old_manifest,
        generator_hash=gen_hash,
        source_digests=source_digests,
        plan_meta=plan_meta,
    )

    shard_reports: List[dict] = []
    emitted_bytes = 0
    skipped_bytes = 0
    hits = 0
    misses = 0
    revalidated = 0
    content_compare_calls = 0
    content_compare_bytes = 0
    content_compare_calls_avoided = 0
    content_compare_bytes_avoided = 0
    _ = cache_enabled
    expected_paths = {p.path.resolve() for p in plans}
    for plan, cached_meta in zip(plans, plan_meta, strict=True):
        t0 = time.perf_counter()
        meta = dict(cached_meta)
        if old_ok:
            state = "unchanged"
            content_compare_calls_avoided += 1
            content_compare_bytes_avoided += int(meta["bytes"])
        else:
            content_compare_calls += 1
            content_compare_bytes += int(meta["bytes"])
            state = write_bytes_if_changed(plan.path, plan.content)
        meta["elapsed_s"] = round(time.perf_counter() - t0, 6)
        if state == "updated":
            meta["cache"] = "miss"
            meta["reason"] = "content-changed" if old_ok else old_reason
            emitted_bytes += int(meta["bytes"])
            misses += 1
        elif old_ok:
            meta["cache"] = "hit"
            meta["reason"] = "manifest-hit"
            skipped_bytes += int(meta["bytes"])
            hits += 1
        else:
            meta["cache"] = "revalidated"
            meta["reason"] = old_reason
            skipped_bytes += int(meta["bytes"])
            revalidated += 1
        shard_reports.append(meta)

    stale_files: List[str] = []
    for p in sorted(out_dir.glob("*.c")) + sorted(out_dir.glob("*.h")):
        try:
            rp = p.resolve()
        except FileNotFoundError:
            continue
        if rp not in expected_paths:
            stale_files.append(rel(p))

    manifest = {
        "kind": "ouro.generated-c-shards.v1",
        "generator_hash": gen_hash,
        "settings": settings,
        "label_prefix": label_prefix,
        "sources": source_digests,
        "manifest_cache": "hit" if old_ok else "miss",
        "manifest_reason": old_reason,
        "shards": shard_reports,
        "summary": {
            "shard_hits": hits,
            "shard_misses": misses,
            "shard_revalidated": revalidated,
            "compile_shards": sum(1 for p in plans if p.compile),
            "header_shards": sum(1 for p in plans if not p.compile),
            "frontend_shards": sum(1 for p in plans if p.role == "frontend" and p.compile),
            "frontend_split_fallbacks": split_fallbacks,
            "backend_shards": sum(1 for p in plans if p.role == "backend" and p.compile),
            "emitted_bytes": emitted_bytes,
            "skipped_bytes": skipped_bytes,
            "total_bytes": emitted_bytes + skipped_bytes,
            "source_reads": len(source_digests),
            "source_bytes_read": sum(int(source["bytes"]) for source in source_digests.values()),
            "plan_metadata_hashes": len(plan_meta),
            "content_compare_calls": content_compare_calls,
            "content_compare_bytes": content_compare_bytes,
            "content_compare_calls_avoided": content_compare_calls_avoided,
            "content_compare_bytes_avoided": content_compare_bytes_avoided,
            "stale_unreferenced_files": stale_files,
            "elapsed_s": round(time.perf_counter() - started, 6),
        },
    }
    manifest_write = "unchanged" if old_ok else write_json_if_changed(manifest_path, manifest)
    manifest["manifest_path"] = rel(manifest_path)
    manifest["manifest_write"] = manifest_write
    if report_path is not None and report_path.resolve() != manifest_path.resolve():
        write_json_if_changed(report_path, manifest)
    compile_sources = [(p.label, p.path) for p in plans if p.compile]
    return compile_sources, manifest


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="materialize deterministic generated C shards")
    ap.add_argument("--frontend", required=True, type=Path)
    ap.add_argument("--backend", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--label-prefix", default="generated")
    ap.add_argument("--backend-group-size", type=int)
    ap.add_argument("--report", type=Path)
    args = ap.parse_args(argv)
    sources, report = materialize_generated_c_shards(
        frontend_c=args.frontend,
        backend_c=args.backend,
        out_dir=args.out_dir,
        label_prefix=args.label_prefix,
        backend_group_size=args.backend_group_size,
        report_path=args.report,
    )
    print(json.dumps({"sources": [(label, rel(path)) for label, path in sources], "summary": report["summary"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
