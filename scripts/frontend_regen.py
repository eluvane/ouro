#!/usr/bin/env python3
"""Deterministic split-frontend regeneration with cache/report support.

This is an operational build helper only. It invokes the existing Ouro seed and
`pack_frontend.py`; it does not reinterpret or change language semantics.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import filecmp
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from repo_support import read_required_text
from repo_support import hash_json, Timer
from repo_support import bool_env
from repo_support import (
    bind_relative_path,
    configure_native_stack,
    memory_aware_jobs,
    sha256_file,
    write_json_atomic,
)

ROOT = Path(__file__).resolve().parents[1]


def _ouro1_python_script(ouro1: Path) -> bool:
    if not ouro1.is_file():
        return False
    if ouro1.suffix.lower() == ".py":
        return True
    try:
        with ouro1.open("rb") as handle:
            head = handle.read(80)
    except OSError:
        return False
    line = head.split(b"\n", 1)[0].lower()
    return line.startswith(b"#!") and b"python" in line


def ouro1_cmd(ouro1: Path) -> list[str]:
    # Cache/regen suites pass a Python fake-ouro1 (sometimes copied to
    # `_build/c/ouro1` with no suffix). Windows cannot CreateProcess a shebang.
    if _ouro1_python_script(ouro1):
        return [sys.executable, str(ouro1)]
    return [str(ouro1)]


def ouro1_usable(ouro1: Path) -> bool:
    if not ouro1.is_file():
        return False
    if _ouro1_python_script(ouro1):
        return True
    return bool(os.access(ouro1, os.X_OK))


rel = bind_relative_path(ROOT, resolve=False)

# Source-backed module cache sidecar.  Kept in Python so it never enters the TCB.
import selfhost_module_cache as SMC  # noqa: E402

# tag, module suffix, root source, work filename.  Keep tag order identical to
# the packer call order used by the historical shell script.
FRONTEND_TUS: Tuple[Tuple[str, str, str, str], ...] = (
    ("lx", "_lx", "compiler/lexer.ouro", "lx.c"),
    ("pa", "_pa", "compiler/parse_a.ouro", "pa.c"),
    ("pb", "_pb", "compiler/parse_b.ouro", "pb.c"),
    ("pf", "_pf", "compiler/parser_file.ouro", "pf.c"),
    ("ds", "_ds", "compiler/desugar_match.ouro", "ds.c"),
    ("ir", "_ir", "compiler/import_resolve.ouro", "ir.c"),
    ("lr", "_lr", "compiler/lower_rewrite.ouro", "lr.c"),
    ("lo", "_lo", "compiler/lower.ouro", "lo.c"),
    ("el", "_el", "compiler/elab.ouro", "el.c"),
    ("co", "_co", "compiler/compiler.ouro", "co.c"),
    ("fc", "_fc", "compiler/file_elab.ouro", "fc.c"),
    ("pi", "_pi", "compiler/preprocess_import.ouro", "pi.c"),
    ("pr", "_pr", "compiler/preprocess_record.ouro", "pr.c"),
    ("pl", "_pl", "compiler/pipeline.ouro", "pl.c"),
)


@dataclass(frozen=True)
class FileDigest:
    path: str
    sha256: str
    bytes: int


@dataclass
class TuReport:
    tag: str
    module: str
    root: str
    deps: int
    key: str
    cache: str
    bytes: int
    elapsed_s: float


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw, 10)
    except ValueError:
        return default
    return value if value > 0 else default


def jobs_from_env() -> int:
    raw = os.environ.get("OURO_FRONTEND_JOBS") or os.environ.get("OURO_JOBS") or "10"
    if raw == "auto":
        raw = str(os.cpu_count() or 1)
    try:
        n = int(raw, 10)
    except ValueError:
        n = 10
    return max(1, n)


def import_targets(path: str) -> List[str]:
    p = ROOT / path
    if not p.is_file():
        raise SystemExit(f"FRONTEND_REGEN: FAIL missing {path}")
    return SMC.quoted_import_targets(read_required_text(p, "FRONTEND_REGEN"), path)


def collect_units_many(roots: Sequence[str]) -> Dict[str, List[str]]:
    """Collect ordered closures with one import read per path in this call.

    This is preparation-local adjacency, not semantic facts or a persistent
    cache. It dies before a child runs; every later preparation rereads inputs.
    Keep root-local DFS state and errors owned by the existing collector.
    """
    imports: Dict[str, Tuple[str, ...]] = {}

    def read_imports(path: str) -> Tuple[str, ...]:
        if path not in imports:
            imports[path] = tuple(import_targets(path))
        return imports[path]

    groups: Dict[str, List[str]] = {}
    for root in roots:
        if root not in groups:
            groups[root] = SMC.collect_units(
                root, imports=read_imports,
                normalize=lambda path: path.replace("\\", "/"),
                cycle_error=lambda norm, root=root:
                    f"FRONTEND_REGEN: FAIL import cycle while collecting {root}: {norm}",
            )
    return groups


def collect_units(root: str) -> List[str]:
    return collect_units_many([root])[root]


def digest(path: Path) -> FileDigest:
    st = path.stat()
    return FileDigest(rel(path), sha256_file(path), st.st_size)


def all_frontend_inputs(ouro1: Path, fuel: str) -> Tuple[Dict[str, List[str]], Dict[str, FileDigest], str]:
    unit_graph = collect_units_many([root for _tag, _mod, root, _file in FRONTEND_TUS])
    paths: Dict[str, Path] = {
        "seed": ouro1,
        "frontend_regen": ROOT / "scripts/frontend_regen.py",
        "module_cache": ROOT / "scripts/selfhost_module_cache.py",
        "emit_wrapper": ROOT / "scripts/emit_frontend.sh",
        "packer": ROOT / "scripts/pack_frontend.py",
    }
    for _tag, _mod, root, _file in FRONTEND_TUS:
        for u in unit_graph[root]:
            paths.setdefault(u, ROOT / u)
    digests = {name: digest(path) for name, path in sorted(paths.items())}
    signature = hash_json(
        {
            "kind": "ouro.frontend.full.v4",
            "fuel": fuel,
            "tus": [
                {
                    "tag": tag,
                    "module": mod,
                    "root": root,
                    "units": unit_graph[root],
                }
                for tag, mod, root, _file in FRONTEND_TUS
            ],
            "digests": {k: asdict(v) for k, v in digests.items()},
        }
    )
    return unit_graph, digests, signature


def tu_key(tag: str, mod: str, root: str, units: Sequence[str], digests: Mapping[str, FileDigest], fuel: str) -> str:
    return hash_json(
        {
            "kind": "ouro.frontend-tu.v4",
            "tag": tag,
            "module": mod,
            "root": root,
            "fuel": fuel,
            "seed": asdict(digests["seed"]),
            "tool": asdict(digests["frontend_regen"]),
            "module_cache_tool": asdict(digests["module_cache"]),
            "units": [asdict(digests[u]) for u in units],
        }
    )


def install_if_changed(src: Path, dst: Path) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and filecmp.cmp(src, dst, shallow=False):
        src.unlink(missing_ok=True)
        return "unchanged"
    os.replace(src, dst)
    return "updated"


def copy_atomic(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + f".tmp.{os.getpid()}")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def read_manifest(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def emit_one(
    *,
    ouro1: Path,
    fuel: str,
    work: Path,
    cache_enabled: bool,
    tu_cache: Path,
    tag: str,
    mod: str,
    root: str,
    file_name: str,
    units: Sequence[str],
    digests: Mapping[str, FileDigest],
) -> TuReport:
    t = Timer()
    key = tu_key(tag, mod, root, units, digests, fuel)
    out = work / file_name
    err = work / f"{tag}.err"
    cache_file = tu_cache / f"{mod}_{key}.c"
    if cache_enabled and cache_file.is_file() and cache_file.stat().st_size > 0:
        copy_atomic(cache_file, out)
        err.write_text("", encoding="utf-8")
        return TuReport(tag, mod, root, len(units), key, "hit", out.stat().st_size, t.elapsed())

    tmp_out = out.with_name(out.name + f".tmp.{os.getpid()}.{tag}")
    tmp_err = err.with_name(err.name + f".tmp.{os.getpid()}.{tag}")
    for stale in (tmp_out, tmp_err):
        stale.unlink(missing_ok=True)
    cmd = ouro1_cmd(ouro1) + ["--module", mod, root, fuel]
    for unit in units:
        cmd.extend(["--unit", unit])
    with tmp_out.open("wb") as stdout, tmp_err.open("wb") as stderr:
        p = subprocess.run(cmd, cwd=str(ROOT), stdout=stdout, stderr=stderr)
    if p.returncode != 0 or not tmp_out.is_file() or tmp_out.stat().st_size == 0:
        tail = tmp_err.read_bytes()[-1200:].decode("utf-8", errors="replace") if tmp_err.exists() else ""
        raise RuntimeError(f"emit {root} module={mod} failed status={p.returncode}\n{tail}")
    text_head = tmp_out.read_text(encoding="utf-8", errors="replace")
    if f"ouro_export_count{mod}" not in text_head:
        raise RuntimeError(f"emit {root} module={mod} missing export table {mod}")
    os.replace(tmp_out, out)
    os.replace(tmp_err, err)
    if cache_enabled:
        copy_atomic(out, cache_file)
    return TuReport(tag, mod, root, len(units), key, "miss", out.stat().st_size, t.elapsed())


def pack_key(pieces: Sequence[Tuple[str, Path]], digests: Mapping[str, FileDigest]) -> str:
    piece_meta = []
    for tag, path in pieces:
        piece_meta.append({"tag": tag, "path": rel(path), "sha256": sha256_file(path), "bytes": path.stat().st_size})
    return hash_json(
        {
            "kind": "ouro.frontend-pack.v4",
            "packer": asdict(digests["packer"]),
            "pieces": piece_meta,
            "strict": True,
        }
    )


def run_pack(pieces: Sequence[Tuple[str, Path]], out_tmp: Path) -> None:
    cmd = [sys.executable, str(ROOT / "scripts/pack_frontend.py"), "--strict", "-o", str(out_tmp)]
    cmd.extend([f"{tag}:{path}" for tag, path in pieces])
    p = subprocess.run(cmd, cwd=str(ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if p.returncode != 0:
        raise RuntimeError(f"pack_frontend failed status={p.returncode}\n{p.stdout[-1600:]}")


def regenerate(
    *,
    ouro1: Path,
    fuel: str,
    out_c: Path,
    work: Path,
    cache_root: Path,
    cache_enabled: bool,
    report_path: Optional[Path],
    jobs: int,
) -> dict:
    total = Timer()
    work.mkdir(parents=True, exist_ok=True)
    # Each TU emit is a full native ouro1 process holding a frontend arena, so a
    # low-memory host running the default fan-out is the real OOM risk. Cap the
    # pool to what free RAM can hold; a healthy machine keeps its full job count.
    jobs, throttle_note = memory_aware_jobs(
        jobs,
        per_worker_mb=env_int("OURO_FRONTEND_WORKER_MB", 1024),
        reserve_mb=env_int("OURO_MEM_RESERVE_MB", 1024),
        enabled=bool_env(os.environ.get("OURO_MEM_AWARE_JOBS"), default=True),
    )
    if throttle_note:
        print(f"EMIT_FRONTEND: {throttle_note}")
    if cache_enabled:
        (cache_root / "gen/frontend-tu").mkdir(parents=True, exist_ok=True)
        (cache_root / "gen/frontend-pack").mkdir(parents=True, exist_ok=True)
        (cache_root / "gen/frontend-final").mkdir(parents=True, exist_ok=True)
    unit_graph, digests, signature = all_frontend_inputs(ouro1, fuel)
    phases: List[dict] = [
        {"name": "collect_inputs", "elapsed_s": round(total.elapsed(), 6)},
    ]
    module_timer = Timer()
    module_cache = SMC.materialize_module_artifacts(
        roots=[root for _tag, _mod, root, _file in FRONTEND_TUS],
        unit_graph=unit_graph,
        work=work / "module_artifacts",
        cache_root=cache_root,
        cache_enabled=cache_enabled,
        report_path=work / "selfhost-module-cache.json",
        label="frontend",
        seed=ouro1,
        fuel=fuel,
        tool_inputs=(
            ROOT / "scripts/frontend_regen.py",
            ROOT / "scripts/emit_frontend.sh",
            ROOT / "scripts/pack_frontend.py",
        ),
    )
    phases.append({"name": "module_cache", "elapsed_s": round(module_timer.elapsed(), 6)})
    manifest = work / "frontend-regeneration.json"
    final_cache = cache_root / "gen/frontend-final" / f"driver_{signature}.c"
    final_meta = cache_root / "gen/frontend-final" / f"driver_{signature}.json"

    affected_tus = []
    changed_modules = set(module_cache.get("summary", {}).get("direct_changed_modules", []))
    closure_changed_modules = set(module_cache.get("summary", {}).get("closure_changed_modules", []))
    for tag, mod, root, _file in FRONTEND_TUS:
        closure = unit_graph.get(root, [])
        direct_hits = [u for u in closure if u in changed_modules]
        closure_hits = [u for u in closure if u in closure_changed_modules]
        if direct_hits or closure_hits:
            affected_tus.append({"tag": tag, "module": mod, "root": root, "direct_changed_modules": direct_hits, "closure_changed_modules": closure_hits})

    print(
        f"EMIT_FRONTEND: signature={signature[:16]} jobs={jobs} cache={'enabled' if cache_enabled else 'disabled'} "
        f"module_direct_hits={module_cache['summary']['direct_hits']} module_direct_misses={module_cache['summary']['direct_misses']}"
    )

    cached_meta = read_manifest(final_meta) if cache_enabled else None
    cached_sha = cached_meta.get("output_sha256") if cached_meta else None
    if (
        cache_enabled
        and final_cache.is_file()
        and final_cache.stat().st_size > 0
        and cached_meta is not None
        and cached_meta.get("input_signature") == signature
        and isinstance(cached_sha, str)
        and sha256_file(final_cache) == cached_sha
    ):
        status = "unchanged"
        if not (out_c.exists() and filecmp.cmp(final_cache, out_c, shallow=False)):
            copy_atomic(final_cache, out_c)
            status = "updated"
        report = {
            "gate": "frontend_regen",
            "pass": True,
            "fast_path": True,
            "input_signature": signature,
            "seed": str(ouro1),
            "fuel": fuel,
            "out": str(out_c),
            "work": str(work),
            "cache_enabled": cache_enabled,
            "final_cache": "hit",
            "output": status,
            "summary": {
                "tu_hits": len(FRONTEND_TUS),
                "tu_misses": 0,
                "module_direct_hits": module_cache["summary"]["direct_hits"],
                "module_direct_misses": module_cache["summary"]["direct_misses"],
                "module_closure_hits": module_cache["summary"]["closure_hits"],
                "module_closure_misses": module_cache["summary"]["closure_misses"],
                "affected_tus": len(affected_tus),
                "pack_cache": "skip-final-hit",
                "elapsed_s": round(total.elapsed(), 6),
            },
            "units": [],
            "module_cache": module_cache,
            "affected_tus": affected_tus,
            "phases": phases,
        }
        report["output_sha256"] = sha256_file(out_c)
        write_json_atomic(manifest, report)
        if report_path:
            write_json_atomic(report_path, report)
        print(f"EMIT_FRONTEND: final cache-hit {status} {out_c}")
        print(f"EMIT_FRONTEND: report {manifest}")
        print(f"EMIT_FRONTEND: OK packed {out_c} elapsed={total.elapsed():.3f}s fast-path")
        return report

    old_manifest = read_manifest(manifest)
    if old_manifest and old_manifest.get("input_signature") == signature and out_c.is_file():
        expected_sha = old_manifest.get("output_sha256")
        if expected_sha and sha256_file(out_c) == expected_sha:
            report = dict(old_manifest)
            report["fast_path"] = True
            report["final_cache"] = "manifest-hit"
            report["summary"] = dict(report.get("summary", {}))
            report["summary"]["elapsed_s"] = round(total.elapsed(), 6)
            report["summary"]["module_direct_hits"] = module_cache["summary"]["direct_hits"]
            report["summary"]["module_direct_misses"] = module_cache["summary"]["direct_misses"]
            report["summary"]["module_closure_hits"] = module_cache["summary"]["closure_hits"]
            report["summary"]["module_closure_misses"] = module_cache["summary"]["closure_misses"]
            report["summary"]["affected_tus"] = len(affected_tus)
            report["module_cache"] = module_cache
            report["affected_tus"] = affected_tus
            report["phases"] = phases
            if cache_enabled:
                copy_atomic(out_c, final_cache)
                write_json_atomic(final_meta, report)
            write_json_atomic(manifest, report)
            if report_path:
                write_json_atomic(report_path, report)
            print(f"EMIT_FRONTEND: manifest fast-path unchanged {out_c}")
            print(f"EMIT_FRONTEND: report {manifest}")
            print(f"EMIT_FRONTEND: OK packed {out_c} elapsed={total.elapsed():.3f}s fast-path")
            return report

    tu_cache = cache_root / "gen/frontend-tu"
    specs = list(FRONTEND_TUS)
    reports_by_tag: Dict[str, TuReport] = {}
    emit_timer = Timer()
    if jobs <= 1:
        for tag, mod, root, file_name in specs:
            reports_by_tag[tag] = emit_one(
                ouro1=ouro1,
                fuel=fuel,
                work=work,
                cache_enabled=cache_enabled,
                tu_cache=tu_cache,
                tag=tag,
                mod=mod,
                root=root,
                file_name=file_name,
                units=unit_graph[root],
                digests=digests,
            )
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            futs = {
                pool.submit(
                    emit_one,
                    ouro1=ouro1,
                    fuel=fuel,
                    work=work,
                    cache_enabled=cache_enabled,
                    tu_cache=tu_cache,
                    tag=tag,
                    mod=mod,
                    root=root,
                    file_name=file_name,
                    units=unit_graph[root],
                    digests=digests,
                ): tag
                for tag, mod, root, file_name in specs
            }
            for fut in concurrent.futures.as_completed(futs):
                tag = futs[fut]
                reports_by_tag[tag] = fut.result()
    unit_reports = [reports_by_tag[tag] for tag, _mod, _root, _file in specs]
    phases.append({"name": "emit_tus", "elapsed_s": round(emit_timer.elapsed(), 6)})
    for r in unit_reports:
        print(
            f"EMIT_FRONTEND: TU {r.tag} {r.cache} module={r.module} deps={r.deps} "
            f"bytes={r.bytes} elapsed={r.elapsed_s:.3f}s"
        )

    pieces = [(tag, work / file_name) for tag, _mod, _root, file_name in specs]
    pkey = pack_key(pieces, digests)
    pack_cache = cache_root / "gen/frontend-pack" / f"driver_{pkey}.c"
    pack_timer = Timer()
    pack_status = "disabled"
    output_status = "updated"
    if cache_enabled and pack_cache.is_file() and pack_cache.stat().st_size > 0:
        pack_status = "hit"
        if out_c.exists() and filecmp.cmp(pack_cache, out_c, shallow=False):
            output_status = "unchanged"
        else:
            copy_atomic(pack_cache, out_c)
            output_status = "updated"
    else:
        pack_status = "miss" if cache_enabled else "disabled"
        tmp = out_c.with_name(out_c.name + f".tmp.{os.getpid()}")
        tmp.unlink(missing_ok=True)
        run_pack(pieces, tmp)
        output_status = install_if_changed(tmp, out_c)
        if cache_enabled:
            copy_atomic(out_c, pack_cache)
    phases.append({"name": "pack", "elapsed_s": round(pack_timer.elapsed(), 6)})

    if cache_enabled:
        copy_atomic(out_c, final_cache)

    hits = sum(1 for r in unit_reports if r.cache == "hit")
    misses = len(unit_reports) - hits
    report = {
        "gate": "frontend_regen",
        "pass": True,
        "fast_path": False,
        "input_signature": signature,
        "seed": str(ouro1),
        "fuel": fuel,
        "out": str(out_c),
        "work": str(work),
        "cache_enabled": cache_enabled,
        "final_cache": "miss" if cache_enabled else "disabled",
        "output": output_status,
        "summary": {
            "tu_hits": hits,
            "tu_misses": misses,
            "module_direct_hits": module_cache["summary"]["direct_hits"],
            "module_direct_misses": module_cache["summary"]["direct_misses"],
            "module_closure_hits": module_cache["summary"]["closure_hits"],
            "module_closure_misses": module_cache["summary"]["closure_misses"],
            "affected_tus": len(affected_tus),
            "pack_cache": pack_status,
            "elapsed_s": round(total.elapsed(), 6),
        },
        "units": [asdict(r) for r in unit_reports],
        "module_cache": module_cache,
        "affected_tus": affected_tus,
        "phases": phases,
        "pack_key": pkey,
        "output_sha256": sha256_file(out_c),
    }
    write_json_atomic(manifest, report)
    if cache_enabled:
        write_json_atomic(final_meta, report)
    if report_path:
        write_json_atomic(report_path, report)
    print(
        f"EMIT_FRONTEND: pack cache={pack_status} output={output_status} "
        f"tu_hits={hits} tu_misses={misses} "
        f"module_direct_misses={module_cache['summary']['direct_misses']} "
        f"module_closure_misses={module_cache['summary']['closure_misses']} "
        f"elapsed={total.elapsed():.3f}s"
    )
    print(f"EMIT_FRONTEND: report {manifest}")
    print(f"EMIT_FRONTEND: OK packed {out_c}")
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="regenerate split Ouro frontend with deterministic caches")
    ap.add_argument("--ouro1", default=os.environ.get("OURO1") or os.environ.get("OURO1_SEED") or str(ROOT / "_build/c/ouro1"))
    ap.add_argument("--fuel", default=os.environ.get("OURO1_CHECK_FUEL", "16000"))
    ap.add_argument("--out", default=os.environ.get("FRONTEND_OUT", str(ROOT / "compiler/stage0/driver_u.c")))
    ap.add_argument("--work", default=os.environ.get("FRONTEND_WORK", str(ROOT / "_build/fe")))
    ap.add_argument("--cache-root", default=os.environ.get("OURO_CACHE_DIR", str(ROOT / "_cache/ouro")))
    ap.add_argument("--report", default=os.environ.get("FRONTEND_REPORT"))
    ap.add_argument("--jobs", type=int, default=jobs_from_env())
    cache_group = ap.add_mutually_exclusive_group()
    cache_group.add_argument("--cache", dest="cache_enabled", action="store_true")
    cache_group.add_argument("--no-cache", dest="cache_enabled", action="store_false")
    ap.set_defaults(cache_enabled=bool_env(os.environ.get("OURO_CACHE"), True))
    args = ap.parse_args(argv)

    ouro1 = Path(args.ouro1)
    if not ouro1.is_absolute():
        ouro1 = ROOT / ouro1
    if not ouro1_usable(ouro1):
        print(f"EMIT_FRONTEND: FAIL missing executable ouro1 at {ouro1}", file=sys.stderr)
        return 1
    try:
        configure_native_stack()
        regenerate(
            ouro1=ouro1,
            fuel=str(args.fuel),
            out_c=Path(args.out) if Path(args.out).is_absolute() else ROOT / args.out,
            work=Path(args.work) if Path(args.work).is_absolute() else ROOT / args.work,
            cache_root=Path(args.cache_root) if Path(args.cache_root).is_absolute() else ROOT / args.cache_root,
            cache_enabled=bool(args.cache_enabled),
            report_path=(Path(args.report) if args.report else None),
            jobs=max(1, int(args.jobs)),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"EMIT_FRONTEND: FAIL {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
