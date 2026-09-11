#!/usr/bin/env python3
"""Deterministic generated-C sharding for Ouro bootstrap builds.

This helper is deliberately build-system-only: it consumes already generated C
artifacts and emits cacheable C translation-unit shards.  It does not interpret
Ouro source or rewrite compiler semantics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
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


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8", errors="surrogateescape"))


def file_digest(path: Path) -> dict:
    st = path.stat()
    return {"path": rel(path), "sha256": sha256_file(path), "bytes": st.st_size}




def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="surrogateescape")


def read_source_text_digest(path: Path, *, chunk_chars: int = 1024 * 1024) -> Tuple[str, dict]:
    text = read_text(path)
    digest = hashlib.sha256()
    byte_count = 0
    for start in range(0, len(text), chunk_chars):
        data = text[start : start + chunk_chars].encode("utf-8", errors="surrogateescape")
        digest.update(data)
        byte_count += len(data)
    return text, {
        "path": rel(path),
        "sha256": digest.hexdigest(),
        "bytes": byte_count,
    }


def write_text_if_changed(path: Path, text: str) -> str:
    """Atomically install text.  Return updated/unchanged without touching mtime on hits."""
    # Windows text mode would turn LF into CRLF and break sha256 vs plan.content.
    data = text.encode("utf-8", errors="surrogateescape")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            if path.read_bytes() == data:
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
    content: str
    role: str
    boundary: str
    provenance: str
    symbols: Tuple[str, ...] = ()
    deps: Tuple[str, ...] = ()
    compile: bool = True

    def meta(self) -> dict:
        b = self.content.encode("utf-8", errors="surrogateescape")
        return {
            "label": self.label,
            "path": rel(self.path),
            "role": self.role,
            "boundary": self.boundary,
            "provenance": self.provenance,
            "symbols": list(self.symbols),
            "deps": list(self.deps),
            "compile": self.compile,
            "sha256": sha256_bytes(b),
            "bytes": len(b),
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


def with_banner(body: str, *, role: str, label: str, generator_hash: str, boundary: str, provenance: str) -> str:
    local_hash = sha256_text(body)
    return banner(
        role=role,
        label=label,
        generator_hash=generator_hash,
        content_hash=local_hash,
        boundary=boundary,
        provenance=provenance,
    ) + body.rstrip() + "\n"


def frontend_shards(
    frontend_c: Path,
    src: str,
    out_dir: Path,
    label_prefix: str,
    generator_hash: str,
) -> List[ShardPlan]:
    matches = list(FRONTEND_MARK.finditer(src))
    plans: List[ShardPlan] = []
    if not matches:
        label = f"{label_prefix}/frontend"
        body = src
        if '#include "ouro_rt.h"' not in body:
            body = '#include "ouro_rt.h"\n' + body
        content = with_banner(
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

    for i, m in enumerate(matches):
        module = m.group(1)
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(src)
        chunk = src[start:end].lstrip()
        if '#include "ouro_rt.h"' not in chunk:
            chunk = '#include "ouro_rt.h"\n' + chunk
        label = f"{label_prefix}/frontend/{module}"
        content = with_banner(
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


def backend_body_start(lines: Sequence[str]) -> int:
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        if s == '#include "ouro_rt.h"':
            i += 1
            continue
        if BACKEND_PROTO.match(s):
            i += 1
            continue
        break
    return i


def transform_backend_cluster(
    lines: Sequence[str],
    duplicate_caches: set[str],
    *,
    start: int = 0,
    end: Optional[int] = None,
) -> str:
    out: List[str] = []
    stop = len(lines) if end is None else end
    for index in range(start, stop):
        line = lines[index]
        stripped = line.strip()
        cm = BACKEND_CACHE.match(stripped)
        if cm and cm.group(1) in duplicate_caches:
            out.append(f"/* shared duplicate generated cache declared in header: {cm.group(1)} */\n")
            continue
        dm = BACKEND_G_DEF.match(stripped)
        if dm:
            # The generated definitions are one-line, but keep leading spacing if any.
            out.append(line.replace("static ouro_v *" + dm.group(1) + "(void){", "ouro_v *" + dm.group(1) + "(void){", 1))
            continue
        out.append(line)
    return "".join(out)


def backend_header(g_names: Sequence[str], duplicate_caches: Sequence[str], generator_hash: str) -> str:
    lines = [
        "/* Ouro generated backend shard header. Do not hand-edit. */\n",
        f"/* generator_hash={generator_hash} */\n",
        "#ifndef OURO_GENERATED_BACKEND_SHARDS_H\n",
        "#define OURO_GENERATED_BACKEND_SHARDS_H\n",
        "#include \"ouro_rt.h\"\n",
    ]
    for c in duplicate_caches:
        lines.append(f"extern ouro_v *{c};\n")
    for g in g_names:
        lines.append(f"ouro_v *{g}(void);\n")
    lines.extend(
        [
            "int ouro_export_count_be(void);\n",
            "const char *ouro_export_name_be(int i);\n",
            "ouro_v *ouro_export_value_be(int i);\n",
            "#endif\n",
        ]
    )
    return "".join(lines)


def backend_shards(
    backend_c: Path,
    src: str,
    out_dir: Path,
    label_prefix: str,
    generator_hash: str,
    group_size: int,
) -> List[ShardPlan]:
    lines = src.splitlines(keepends=True)
    if not lines:
        return []
    start_idx = backend_body_start(lines)
    g_lines: List[Tuple[int, str]] = []
    cache_counts: Dict[str, int] = {}
    for idx, line in enumerate(lines[start_idx:], start_idx):
        s = line.strip()
        gm = BACKEND_G_DEF.match(s)
        if gm:
            g_lines.append((idx, gm.group(1)))
        cm = BACKEND_CACHE.match(s)
        if cm:
            cache_counts[cm.group(1)] = cache_counts.get(cm.group(1), 0) + 1
    if not g_lines:
        label = f"{label_prefix}/backend"
        body = src
        if '#include "ouro_rt.h"' not in body:
            body = '#include "ouro_rt.h"\n' + body
        content = with_banner(
            body,
            role="backend",
            label=label,
            generator_hash=generator_hash,
            boundary="whole-file-fallback",
            provenance=rel(backend_c),
        )
        return [
            ShardPlan(
                label=label,
                path=out_dir / "backend__whole.c",
                content=content,
                role="backend",
                boundary="whole-file-fallback",
                provenance=rel(backend_c),
            )
        ]

    duplicate_caches = {name for name, count in cache_counts.items() if count > 1}
    g_names = []
    seen_g: set[str] = set()
    for _idx, name in g_lines:
        if name not in seen_g:
            seen_g.add(name)
            g_names.append(name)
    dup_sorted = sorted(duplicate_caches)
    header_name = "backend_u__shards.h"
    header_body = backend_header(g_names, dup_sorted, generator_hash)
    plans: List[ShardPlan] = [
        ShardPlan(
            label=f"{label_prefix}/backend/header",
            path=out_dir / header_name,
            content=header_body,
            role="backend",
            boundary="backend-header",
            provenance=rel(backend_c),
            symbols=tuple(g_names),
            compile=False,
        )
    ]
    if dup_sorted:
        state_lines = [f'#include "{header_name}"\n']
        for c in dup_sorted:
            state_lines.append(f"ouro_v *{c};\n")
        content = with_banner(
            "".join(state_lines),
            role="backend",
            label=f"{label_prefix}/backend/state",
            generator_hash=generator_hash,
            boundary="backend-duplicate-cache-state",
            provenance=rel(backend_c),
        )
        plans.append(
            ShardPlan(
                label=f"{label_prefix}/backend/state",
                path=out_dir / "backend__000_state.c",
                content=content,
                role="backend",
                boundary="backend-duplicate-cache-state",
                provenance=rel(backend_c),
                symbols=tuple(dup_sorted),
                deps=(header_name,),
            )
        )

    clusters: List[Tuple[str, int, int]] = []
    cluster_start = start_idx
    for line_idx, g_name in g_lines:
        clusters.append((g_name, cluster_start, line_idx + 1))
        cluster_start = line_idx + 1
    export_start = cluster_start

    shard_no = 1 if dup_sorted else 0
    for chunk_start in range(0, len(clusters), group_size):
        chunk = clusters[chunk_start : chunk_start + group_size]
        names = [name for name, _start, _end in chunk]
        raw = [f'#include "{header_name}"\n']
        for _name, body_start, body_end in chunk:
            raw.append(
                transform_backend_cluster(
                    lines,
                    duplicate_caches,
                    start=body_start,
                    end=body_end,
                )
            )
        boundary = f"backend-functions:{names[0]}..{names[-1]}"
        label = f"{label_prefix}/backend/g{chunk_start:03d}-{chunk_start + len(chunk) - 1:03d}"
        content = with_banner(
            "".join(raw),
            role="backend",
            label=label,
            generator_hash=generator_hash,
            boundary=boundary,
            provenance=f"{rel(backend_c)}#functions={names[0]}..{names[-1]}",
        )
        plans.append(
            ShardPlan(
                label=label,
                path=out_dir / f"backend__{shard_no:03d}_{filename_fragment(names[0], 120, 'shard')}_{filename_fragment(names[-1], 120, 'shard')}.c",
                content=content,
                role="backend",
                boundary=boundary,
                provenance=f"{rel(backend_c)}#functions={names[0]}..{names[-1]}",
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
        content = with_banner(
            raw,
            role="backend",
            label=label,
            generator_hash=generator_hash,
            boundary="backend-export-table",
            provenance=f"{rel(backend_c)}#exports",
        )
        plans.append(
            ShardPlan(
                label=label,
                path=out_dir / f"backend__{shard_no:03d}_exports.c",
                content=content,
                role="backend",
                boundary="backend-export-table",
                provenance=f"{rel(backend_c)}#exports",
                symbols=("ouro_export_count_be", "ouro_export_name_be", "ouro_export_value_be"),
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
    frontend_c: Path,
    backend_c: Path,
    out_dir: Path,
    label_prefix: str,
    cache_enabled: bool = True,  # public call contract; writes always go through write_text_if_changed
    backend_group_size: Optional[int] = None,
    report_path: Optional[Path] = None,
) -> Tuple[List[Tuple[str, Path]], dict]:
    started = time.perf_counter()
    frontend_c = frontend_c if frontend_c.is_absolute() else ROOT / frontend_c
    backend_c = backend_c if backend_c.is_absolute() else ROOT / backend_c
    if not frontend_c.is_file():
        raise SystemExit(f"GENERATED_C_SHARDS: FAIL missing frontend {frontend_c}")
    if not backend_c.is_file():
        raise SystemExit(f"GENERATED_C_SHARDS: FAIL missing backend {backend_c}")
    out_dir.mkdir(parents=True, exist_ok=True)
    group_size = backend_group_size or int_env("OURO_GENERATED_C_SHARD_BACKEND_GROUPS", 8)
    settings = {"backend_group_size": group_size, "schema": "v1"}
    gen_hash = generator_digest(settings)
    frontend_text, frontend_digest = read_source_text_digest(frontend_c)
    plans = frontend_shards(frontend_c, frontend_text, out_dir, label_prefix, gen_hash)
    del frontend_text
    backend_text, backend_digest = read_source_text_digest(backend_c)
    plans.extend(backend_shards(backend_c, backend_text, out_dir, label_prefix, gen_hash, group_size))
    del backend_text
    source_digests = {
        "frontend": frontend_digest,
        "backend": backend_digest,
    }
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
            state = write_text_if_changed(plan.path, plan.content)
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
            "backend_shards": sum(1 for p in plans if p.role == "backend" and p.compile),
            "emitted_bytes": emitted_bytes,
            "skipped_bytes": skipped_bytes,
            "total_bytes": emitted_bytes + skipped_bytes,
            "source_reads": 2,
            "source_bytes_read": int(frontend_digest["bytes"]) + int(backend_digest["bytes"]),
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
