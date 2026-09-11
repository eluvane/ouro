#!/usr/bin/env python3
"""Closed Ouro bootstrap stage-loop with deterministic fast paths.

The loop still uses the existing compiler seed to emit generated C; this helper
adds safe input signatures, per-stage stamps, timing reports and atomic writes so
reruns do less work without weakening bootstrap correctness.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from repo_support import bind_relative_path, sha256_file, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
rel = bind_relative_path(ROOT, resolve=False)

# Local helper module.  Keep this import source-backed so copied repos use their
# own frontend TU list and import collector.
sys.path.insert(0, str(ROOT / "scripts"))
import frontend_regen as freg  # noqa: E402
import generated_c_shards as GCS  # noqa: E402
import selfhost_module_cache as SMC  # noqa: E402

BACKEND_ROOT = "compiler/backend.ouro"
C_LINK_SOURCES = (
    "runtime/ouro_rt.c",
    "runtime/bootstrap.c",
    "runtime/frontend_link.c",
)


def load_ouro_build():
    spec = importlib.util.spec_from_file_location("ouro_build", ROOT / "scripts/ouro_build.py")
    if spec is None or spec.loader is None:
        raise SystemExit("STAGE_LOOP: FAIL cannot import scripts/ouro_build.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ouro_build"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


OB = load_ouro_build()


@dataclass
class StageConfig:
    promote: bool
    max_stages: int
    fuel: str
    pack_strict: str
    cc: str
    c_build_dir: Path
    build_dir: Path
    cache_root: Path
    cache_enabled: bool
    work: Path
    result: Path
    status_pub: Path
    env: Dict[str, str]
    build_cfg: object


def now() -> float:
    return time.perf_counter()


def hash_json(data: object) -> str:
    return freg.hash_json(data)


def file_digest(path: Path) -> dict:
    st = path.stat()
    return {"path": rel(path), "sha256": sha256_file(path), "bytes": st.st_size}


def copy_atomic(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + f".tmp.{os.getpid()}")
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def tail(path: Path, n: int = 1200) -> str:
    try:
        return path.read_bytes()[-n:].decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def build_config(args: argparse.Namespace) -> StageConfig:
    ns = argparse.Namespace(
        config=None,
        profile=None,
        jobs=None,
        cc=None,
        opt_level=None,
        build_dir=None,
        c_build_dir=None,
        cache_dir=None,
        cache_enabled=None,
        cache_size_mb=None,
        cache_cleanup_policy=None,
        ccache=None,
        verbosity=None,
        reproducible=None,
    )
    ob_cfg = OB.load_config(ns)
    env = OB.configured_env(ob_cfg)
    cc = OB.choose_cc(ob_cfg)
    env["CC"] = cc
    build_dir = ob_cfg.path("build_dir")
    work = build_dir / "stage_loop"
    status_pub = ROOT.parent / "public/bootstrap-status.json"
    if not (ROOT.parent / "public").is_dir():
        status_pub = work / "bootstrap-status.json"
    return StageConfig(
        promote=bool(args.promote),
        max_stages=int(os.environ.get("OURO_STAGE_MAX", "3")),
        fuel=str(os.environ.get("OURO1_CHECK_FUEL", "16000")),
        pack_strict=str(os.environ.get("OURO_PACK_STRICT", "1")),
        cc=cc,
        c_build_dir=ob_cfg.path("c_build_dir"),
        build_dir=build_dir,
        cache_root=ob_cfg.path("cache_dir"),
        cache_enabled=ob_cfg.get_bool("cache_enabled"),
        work=work,
        result=work / "result.json",
        status_pub=status_pub,
        env=env,
        build_cfg=ob_cfg,
    )


def ensure_seed(cfg: StageConfig) -> Path:
    seed = cfg.c_build_dir / "ouro1"
    if not freg.ouro1_usable(seed):
        subprocess.run(["sh", str(ROOT / "scripts/bootstrap.sh")], cwd=str(ROOT), env=cfg.env, check=True)
    if not freg.ouro1_usable(seed):
        raise SystemExit(f"STAGE_LOOP: FAIL missing seed {seed}")
    return seed


def all_stage_source_units() -> Tuple[List[str], Dict[str, List[str]]]:
    roots = [BACKEND_ROOT] + [root for _tag, _mod, root, _file in freg.FRONTEND_TUS]
    graph: Dict[str, List[str]] = {}
    all_units: List[str] = []
    for root in roots:
        units = freg.collect_units(root)
        graph[root] = units
        for u in units:
            if u not in all_units:
                all_units.append(u)
    return all_units, graph


def stage_signature(cfg: StageConfig, seed: Path) -> Tuple[str, dict]:
    units, graph = all_stage_source_units()
    files: Dict[str, Path] = {
        "seed_binary": seed,
        "stage_loop_py": ROOT / "scripts/stage_loop.py",
        "stage_loop_sh": ROOT / "scripts/stage_loop.sh",
        "frontend_regen_py": ROOT / "scripts/frontend_regen.py",
        "emit_frontend_sh": ROOT / "scripts/emit_frontend.sh",
        "pack_frontend_py": ROOT / "scripts/pack_frontend.py",
        "ouro_build_py": ROOT / "scripts/ouro_build.py",
        "generated_c_shards_py": ROOT / "scripts/generated_c_shards.py",
        "selfhost_module_cache_py": ROOT / "scripts/selfhost_module_cache.py",
        "stage0_driver": ROOT / "compiler/stage0/driver_u.c",
        "stage0_backend": ROOT / "compiler/stage0/backend_u.c",
    }
    for src in C_LINK_SOURCES:
        files[src] = ROOT / src
    for h in sorted((ROOT / "runtime").glob("*.h")):
        files[f"header:{rel(h)}"] = h
    for u in units:
        files[u] = ROOT / u
    digests = {name: file_digest(path) for name, path in sorted(files.items()) if path.exists()}
    meta = {
        "kind": "ouro.stage-loop.v5",
        "max_stages": cfg.max_stages,
        "fuel": cfg.fuel,
        "pack_strict": cfg.pack_strict,
        "cc": cfg.cc,
        "compiler_id": OB.compiler_id(cfg.cc),
        "cflags": OB.profile_cflags(cfg.build_cfg),
        "roots": graph,
        "digests": digests,
    }
    return hash_json(meta), meta


def load_json(path: Path) -> Optional[object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def write_status(cfg: StageConfig, data: dict) -> None:
    write_json_atomic(cfg.result, data)
    write_json_atomic(cfg.status_pub, data)
    print(f"STAGE_LOOP: wrote {cfg.result}")


STAGE_OP_ERRORS = (OSError, RuntimeError, ValueError, subprocess.SubprocessError)


def fail_stage(
    cfg: StageConfig,
    *,
    started: float,
    signature: str,
    stage: int,
    failed_at: str,
    message: str | None = None,
) -> int:
    if message is not None:
        print(message, file=sys.stderr)
    write_status(
        cfg,
        {
            "gate": "stage_loop",
            "pass": False,
            "failed_at": failed_at,
            "stages": stage,
            "input_signature": signature,
            "elapsed_s": round(now() - started, 6),
        },
    )
    return 1


def artifact_summary(stage_dir: Path, bin_path: Path) -> dict:
    be = stage_dir / "backend_u.c"
    fe = stage_dir / "driver_u.c"
    out = {
        "backend_sha256": sha256_file(be) if be.is_file() else "",
        "frontend_sha256": sha256_file(fe) if fe.is_file() else "",
        "binary_sha256": sha256_file(bin_path) if bin_path.is_file() else "",
        "backend_bytes": be.stat().st_size if be.is_file() else 0,
        "frontend_bytes": fe.stat().st_size if fe.is_file() else 0,
    }
    return out


def stage_stamp_ok(stamp: Path, *, signature: str, stage: int, prev_sha: str, stage_dir: Path, bin_path: Path) -> bool:
    data = load_json(stamp)
    if not isinstance(data, dict):
        return False
    if data.get("input_signature") != signature or data.get("stage") != stage or data.get("prev_sha256") != prev_sha:
        return False
    arts = artifact_summary(stage_dir, bin_path)
    expected = data.get("artifacts", {})
    for key in ("backend_sha256", "frontend_sha256", "binary_sha256"):
        if not arts.get(key) or arts.get(key) != expected.get(key):
            return False
    return True


def write_stage_stamp(stamp: Path, *, signature: str, stage: int, prev_sha: str, stage_dir: Path, bin_path: Path, report: dict) -> None:
    data = {
        "stage": stage,
        "input_signature": signature,
        "prev_sha256": prev_sha,
        "artifacts": artifact_summary(stage_dir, bin_path),
        "report": report,
    }
    write_json_atomic(stamp, data)


def maybe_fast_path(cfg: StageConfig, signature: str, started: float) -> bool:
    if cfg.promote or os.environ.get("OURO_STAGE_FAST_PATH", "1") in {"0", "false", "no", "disabled"}:
        return False
    data = load_json(cfg.result)
    if not isinstance(data, dict):
        return False
    if not (data.get("pass") and data.get("fixpoint") and data.get("input_signature") == signature):
        return False
    last = int(data.get("stages") or 0)
    if last < 2:
        return False
    stage_dir = cfg.work / f"stage{last}"
    bin_path = cfg.work / f"ouro1_stage{last}"
    arts = artifact_summary(stage_dir, bin_path)
    expected = data.get("artifacts", {})
    for key in ("backend_sha256", "frontend_sha256", "binary_sha256"):
        if not arts.get(key) or arts.get(key) != expected.get(key):
            return False
    out = dict(data)
    out["fast_path"] = True
    out["elapsed_s"] = round(now() - started, 6)
    out["cache"] = "stage-loop-input-hit"
    write_status(cfg, out)
    print(f"STAGE_LOOP: FAST_PATH input unchanged; fixpoint stage{last} reused")
    return True


def collect_flags(root: str) -> List[str]:
    flags: List[str] = []
    for u in freg.collect_units(root):
        flags.extend(["--unit", u])
    return flags


def backend_key(prev: Path, cfg: StageConfig, units: Sequence[str]) -> str:
    meta = {
        "kind": "ouro.backend-tu.v3",
        "seed": file_digest(prev),
        "fuel": cfg.fuel,
        "root": BACKEND_ROOT,
        "units": [file_digest(ROOT / u) for u in units],
        "tools": {
            "stage_loop": file_digest(ROOT / "scripts/stage_loop.py"),
            "module_cache": file_digest(ROOT / "scripts/selfhost_module_cache.py"),
            "packer": file_digest(ROOT / "scripts/pack_frontend.py"),
        },
    }
    return hash_json(meta)


def emit_backend(prev: Path, out: Path, err: Path, cfg: StageConfig, stage: int) -> dict:
    t0 = now()
    units = freg.collect_units(BACKEND_ROOT)
    module_cache = SMC.materialize_module_artifacts(
        roots=[BACKEND_ROOT],
        unit_graph={BACKEND_ROOT: units},
        work=out.parent / "module_artifacts_backend",
        cache_root=cfg.cache_root,
        cache_enabled=cfg.cache_enabled,
        report_path=out.parent / "backend_module_cache_report.json",
        label=f"stage{stage}/backend",
        seed=prev,
        fuel=cfg.fuel,
        tool_inputs=(
            ROOT / "scripts/stage_loop.py",
            ROOT / "scripts/pack_frontend.py",
        ),
    )
    key = backend_key(prev, cfg, units)
    cache_dir = cfg.cache_root / "gen/backend"
    cache_file = cache_dir / f"backend_{key}.c"
    if cfg.cache_enabled:
        cache_dir.mkdir(parents=True, exist_ok=True)
    if cfg.cache_enabled and cache_file.is_file() and cache_file.stat().st_size > 0:
        copy_atomic(cache_file, out)
        err.write_text("", encoding="utf-8")
        print(f"STAGE_LOOP: backend cache-hit units={len(units)} -> {out}")
        return {"cache": "hit", "units": len(units), "bytes": out.stat().st_size, "elapsed_s": round(now() - t0, 6), "key": key, "module_cache": module_cache}

    print(f"STAGE_LOOP: emit backend units={len(units)} -> {out}")
    tmp = out.with_name(out.name + f".tmp.{os.getpid()}")
    tmp_err = err.with_name(err.name + f".tmp.{os.getpid()}")
    tmp.unlink(missing_ok=True)
    tmp_err.unlink(missing_ok=True)
    cmd = freg.ouro1_cmd(prev) + ["--module", "_be", BACKEND_ROOT, cfg.fuel]
    for u in units:
        cmd.extend(["--unit", u])
    with tmp.open("wb") as stdout, tmp_err.open("wb") as stderr:
        p = subprocess.run(cmd, cwd=str(ROOT), stdout=stdout, stderr=stderr, env=cfg.env)
    if p.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
        err.parent.mkdir(parents=True, exist_ok=True)
        if tmp_err.exists():
            os.replace(tmp_err, err)
        print(f"STAGE_LOOP: FAIL backend emit status={p.returncode}", file=sys.stderr)
        print(tail(err, 1200), file=sys.stderr)
        raise RuntimeError("backend emit failed")
    up = subprocess.run([sys.executable, str(ROOT / "scripts/pack_frontend.py"), "--uniquify-only", str(tmp)], cwd=str(ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if up.returncode != 0:
        print(up.stdout[-1200:], file=sys.stderr)
        raise RuntimeError("backend uniquify failed")
    out.parent.mkdir(parents=True, exist_ok=True)
    os.replace(tmp, out)
    if tmp_err.exists():
        os.replace(tmp_err, err)
    if cfg.cache_enabled:
        copy_atomic(out, cache_file)
    return {"cache": "miss", "units": len(units), "bytes": out.stat().st_size, "elapsed_s": round(now() - t0, 6), "key": key, "module_cache": module_cache}


def emit_frontend(prev: Path, out: Path, err: Path, stage: int, cfg: StageConfig) -> dict:
    t0 = now()
    fe_work = cfg.work / f"fe_s{stage}"
    report = out.parent / "frontend_report.json"
    env = dict(cfg.env)
    env.update(
        {
            "OURO1": str(prev),
            "FRONTEND_OUT": str(out),
            "FRONTEND_WORK": str(fe_work),
            "FRONTEND_REPORT": str(report),
            "OURO1_CHECK_FUEL": cfg.fuel,
            "OURO_CACHE": "1" if cfg.cache_enabled else "0",
            "OURO_CACHE_DIR": str(cfg.cache_root),
        }
    )
    env["PYTHON"] = sys.executable
    print(f"STAGE_LOOP: emit frontend stage={stage} seed={prev} -> {out}")
    err.parent.mkdir(parents=True, exist_ok=True)
    with err.open("wb") as log:
        p = subprocess.run(
            [sys.executable, str(ROOT / "scripts/frontend_regen.py")],
            cwd=str(ROOT),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    if p.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        print(f"STAGE_LOOP: FAIL frontend emit status={p.returncode}", file=sys.stderr)
        print(tail(err, 1600), file=sys.stderr)
        raise RuntimeError("frontend emit failed")
    data = load_json(report)
    if not isinstance(data, dict):
        data = {"summary": {}, "fast_path": False}
    summary = data.get("summary", {})
    print(
        "STAGE_LOOP: frontend "
        f"stage={stage} fast={bool(data.get('fast_path'))} "
        f"tu_hits={summary.get('tu_hits', '?')} tu_misses={summary.get('tu_misses', '?')} "
        f"module_direct_misses={summary.get('module_direct_misses', '?')} "
        f"pack={summary.get('pack_cache', '?')} elapsed={now() - t0:.3f}s"
    )
    data["stage_elapsed_s"] = round(now() - t0, 6)
    return data


def build_stage_binary(frontend_c: Path, backend_c: Path, out: Path, stage: int, cfg: StageConfig) -> dict:
    """Incrementally build one generated stage executable.

    This is deliberately routed through scripts/ouro_build.py so stage-loop uses
    the same object depfiles, command hashes, ccache policy, link stamps and
    atomic-output discipline as the ordinary C bootstrap path.
    """
    shard_dir = cfg.work / "generated_c_shards" / f"stage{stage}"
    shard_sources, shard_report = GCS.materialize_generated_c_shards(
        frontend_c=frontend_c,
        backend_c=backend_c,
        out_dir=shard_dir,
        label_prefix=f"stage{stage}",
        cache_enabled=cfg.cache_enabled,
        report_path=frontend_c.parent / "generated_c_shards_report.json",
    )
    sources = list(shard_sources) + [
        ("static/ouro_rt", ROOT / "runtime/ouro_rt.c"),
        ("static/bootstrap", ROOT / "runtime/bootstrap.c"),
        ("static/fe_link", OB.ensure_fe_link()),
    ]
    report_path = frontend_c.parent / "c_build_report.json"
    report = OB.build_c_executable(
        cfg.build_cfg,
        name=f"stage_loop_ouro1_stage{stage}",
        sources=sources,
        output=out,
        object_dir=cfg.work / "c_objects",
        include_dirs=[ROOT / "runtime"],
        extra_cflags=["-Werror=implicit-function-declaration"],
        jobs=OB.jobs_value(cfg.build_cfg),
        report_path=report_path,
        generated_c_shards=shard_report,
    )
    ss = shard_report.get("summary", {}) if isinstance(shard_report, dict) else {}
    print(
        "STAGE_LOOP: c-build "
        f"stage={stage} compile_hits={report.get('compile_hits')} "
        f"compile_misses={report.get('compile_misses')} "
        f"shard_hits={ss.get('shard_hits', '?')} shard_misses={ss.get('shard_misses', '?')} "
        f"link={report.get('link_cache')} elapsed={report.get('elapsed_s')}s"
    )
    return report


def summarize_stage_c_builds(stage_reports: Sequence[dict]) -> dict:
    summaries: List[dict] = []
    all_sources: List[dict] = []
    compile_hits = 0
    compile_misses = 0
    link_hits = 0
    link_misses = 0
    shard_hits = 0
    shard_misses = 0
    shard_revalidated = 0
    emitted_bytes = 0
    skipped_bytes = 0
    slowest_shards: List[dict] = []
    for report in stage_reports:
        cbuild = report.get("c_build")
        if not isinstance(cbuild, dict):
            continue
        compile_hits += int(cbuild.get("compile_hits") or 0)
        compile_misses += int(cbuild.get("compile_misses") or 0)
        if cbuild.get("link_cache") == "hit":
            link_hits += 1
        elif cbuild.get("link_cache") == "miss":
            link_misses += 1
        shard = cbuild.get("generated_c_shards")
        if isinstance(shard, dict):
            ss = shard.get("summary", {}) if isinstance(shard.get("summary"), dict) else {}
            shard_hits += int(ss.get("shard_hits") or 0)
            shard_misses += int(ss.get("shard_misses") or 0)
            shard_revalidated += int(ss.get("shard_revalidated") or 0)
            emitted_bytes += int(ss.get("emitted_bytes") or 0)
            skipped_bytes += int(ss.get("skipped_bytes") or 0)
            for sh in shard.get("shards", []):
                if isinstance(sh, dict) and sh.get("compile"):
                    slowest_shards.append(dict(sh, stage=report.get("stage")))
        summaries.append(
            {
                "stage": report.get("stage"),
                "compile_hits": cbuild.get("compile_hits", 0),
                "compile_misses": cbuild.get("compile_misses", 0),
                "link_cache": cbuild.get("link_cache", "unknown"),
                "elapsed_s": cbuild.get("elapsed_s", 0),
            }
        )
        for src in cbuild.get("sources", []):
            if isinstance(src, dict):
                item = dict(src)
                item["stage"] = report.get("stage")
                all_sources.append(item)
    slowest = sorted(all_sources, key=lambda s: float(s.get("elapsed_s") or 0), reverse=True)[:10]
    return {
        "compile_hits": compile_hits,
        "compile_misses": compile_misses,
        "link_hits": link_hits,
        "link_misses": link_misses,
        "generated_c_shards": {
            "shard_hits": shard_hits,
            "shard_misses": shard_misses,
            "shard_revalidated": shard_revalidated,
            "emitted_bytes": emitted_bytes,
            "skipped_bytes": skipped_bytes,
            "slowest_shards": [
                {
                    "stage": s.get("stage"),
                    "label": s.get("label"),
                    "role": s.get("role"),
                    "boundary": s.get("boundary"),
                    "elapsed_s": s.get("elapsed_s", 0),
                    "cache": s.get("cache"),
                    "bytes": s.get("bytes", 0),
                }
                for s in sorted(slowest_shards, key=lambda x: float(x.get("elapsed_s") or 0), reverse=True)[:10]
            ],
        },
        "stages": summaries,
        "slowest_sources": [
            {
                "stage": s.get("stage"),
                "source": s.get("source"),
                "label": s.get("label"),
                "elapsed_s": s.get("elapsed_s", 0),
                "cache": s.get("cache"),
            }
            for s in slowest
        ],
    }


def summarize_module_caches(stage_reports: Sequence[dict]) -> dict:
    direct_hits = direct_misses = closure_hits = closure_misses = 0
    affected_modules: List[str] = []
    affected_roots: List[str] = []
    reports: List[dict] = []
    for report in stage_reports:
        for slot in ("backend", "frontend"):
            item = report.get(slot)
            if not isinstance(item, dict):
                continue
            mc = item.get("module_cache")
            if not isinstance(mc, dict):
                continue
            summary = mc.get("summary", {}) if isinstance(mc.get("summary"), dict) else {}
            direct_hits += int(summary.get("direct_hits") or 0)
            direct_misses += int(summary.get("direct_misses") or 0)
            closure_hits += int(summary.get("closure_hits") or 0)
            closure_misses += int(summary.get("closure_misses") or 0)
            affected_modules.extend(str(x) for x in summary.get("affected_modules", []) if isinstance(x, str))
            affected_roots.extend(str(x) for x in summary.get("affected_roots", []) if isinstance(x, str))
            reports.append(
                {
                    "stage": report.get("stage"),
                    "slot": slot,
                    "modules": summary.get("modules", 0),
                    "direct_hits": summary.get("direct_hits", 0),
                    "direct_misses": summary.get("direct_misses", 0),
                    "closure_hits": summary.get("closure_hits", 0),
                    "closure_misses": summary.get("closure_misses", 0),
                    "affected_roots": summary.get("affected_roots", []),
                    "elapsed_s": summary.get("elapsed_s", 0),
                }
            )
    return {
        "direct_hits": direct_hits,
        "direct_misses": direct_misses,
        "closure_hits": closure_hits,
        "closure_misses": closure_misses,
        "affected_modules": sorted(set(affected_modules)),
        "affected_roots": sorted(set(affected_roots)),
        "reports": reports,
    }

def files_eq(a: Path, b: Path) -> bool:
    return a.is_file() and b.is_file() and a.read_bytes() == b.read_bytes()


def promote(cfg: StageConfig, last: int) -> None:
    print(f"STAGE_LOOP: promote stage{last} -> compiler/stage0")
    stage_dir = cfg.work / f"stage{last}"
    # A Windows-native compiler writes CRLF through the C text stream, while
    # .gitattributes commits stage0 as LF. Install text through the binary
    # writer so the manifest hashes the bytes that a clean checkout retains.
    for name in ("driver_u.c", "backend_u.c"):
        src = stage_dir / name
        dst = ROOT / "compiler/stage0" / name
        GCS.write_text_if_changed(dst, GCS.read_text(src))
    hash_path = ROOT / "docs/generated_artifact_hashes.sha256"
    lines = []
    for p in (ROOT / "compiler/stage0/backend_u.c", ROOT / "compiler/stage0/driver_u.c"):
        lines.append(f"{sha256_file(p)}  {rel(p)}\n")
    # sha256sum -c rejects CRLF path names; always write LF.
    hash_path.write_bytes("".join(lines).encode("ascii"))
    print("STAGE_LOOP: hashes updated")
    subprocess.run(["sh", str(ROOT / "scripts/bootstrap.sh")], cwd=str(ROOT), env=cfg.env, check=True)


def run_loop(cfg: StageConfig) -> int:
    started = now()
    cfg.work.mkdir(parents=True, exist_ok=True)
    seed = ensure_seed(cfg)
    stage0 = cfg.work / "ouro1_stage0"
    copy_atomic(seed, stage0)
    (cfg.work / "stage0_driver_u.c").unlink(missing_ok=True)
    (cfg.work / "stage0_backend_u.c").unlink(missing_ok=True)
    try:
        (cfg.work / "stage0_driver_u.c").symlink_to(ROOT / "compiler/stage0/driver_u.c")
        (cfg.work / "stage0_backend_u.c").symlink_to(ROOT / "compiler/stage0/backend_u.c")
    except OSError:
        shutil.copyfile(ROOT / "compiler/stage0/driver_u.c", cfg.work / "stage0_driver_u.c")
        shutil.copyfile(ROOT / "compiler/stage0/backend_u.c", cfg.work / "stage0_backend_u.c")

    signature, sig_meta = stage_signature(cfg, seed)
    print(f"=== stage_loop max={cfg.max_stages} fuel={cfg.fuel} signature={signature[:16]} ===")
    if maybe_fast_path(cfg, signature, started):
        return 0

    prev = stage0
    fixpoint = False
    be_eq = False
    fe_eq = False
    last = 0
    stage_reports: List[dict] = []

    for i in range(1, cfg.max_stages + 1):
        sdir = cfg.work / f"stage{i}"
        sdir.mkdir(parents=True, exist_ok=True)
        be = sdir / "backend_u.c"
        fe = sdir / "driver_u.c"
        bin_path = cfg.work / f"ouro1_stage{i}"
        stamp = sdir / "stage.stamp.json"
        prev_sha = sha256_file(prev)
        report: dict = {"stage": i, "reused": False}
        if stage_stamp_ok(stamp, signature=signature, stage=i, prev_sha=prev_sha, stage_dir=sdir, bin_path=bin_path):
            report["reused"] = True
            report["artifacts"] = artifact_summary(sdir, bin_path)
            print(
                f"STAGE_LOOP: reuse stage{i} backend={be.stat().st_size} "
                f"frontend={fe.stat().st_size}"
            )
        else:
            try:
                report["backend"] = emit_backend(prev, be, sdir / "emit.err", cfg, i)
            except STAGE_OP_ERRORS:
                return fail_stage(
                    cfg,
                    started=started,
                    signature=signature,
                    stage=i,
                    failed_at=f"stage{i}_backend",
                )
            try:
                report["frontend"] = emit_frontend(prev, fe, sdir / "fe.err", i, cfg)
            except STAGE_OP_ERRORS:
                return fail_stage(
                    cfg,
                    started=started,
                    signature=signature,
                    stage=i,
                    failed_at=f"stage{i}_frontend",
                )
            try:
                report["c_build"] = build_stage_binary(fe, be, bin_path, i, cfg)
            except STAGE_OP_ERRORS as exc:
                return fail_stage(
                    cfg,
                    started=started,
                    signature=signature,
                    stage=i,
                    failed_at=f"stage{i}_c_build",
                    message=f"STAGE_LOOP: FAIL c-build stage{i}: {exc}",
                )
            report["artifacts"] = artifact_summary(sdir, bin_path)
            write_stage_stamp(stamp, signature=signature, stage=i, prev_sha=prev_sha, stage_dir=sdir, bin_path=bin_path, report=report)
        print(f"STAGE_LOOP: stage{i} backend={be.stat().st_size} frontend={fe.stat().st_size}")
        if i >= 2:
            prevdir = cfg.work / f"stage{i - 1}"
            be_eq = files_eq(prevdir / "backend_u.c", be)
            fe_eq = files_eq(prevdir / "driver_u.c", fe)
            print(
                f"STAGE_LOOP: stage{i-1}==stage{i} "
                f"backend={'yes' if be_eq else 'NO'} frontend={'yes' if fe_eq else 'NO'}"
            )
            report["eq_prev"] = {"backend": be_eq, "frontend": fe_eq}
            if be_eq and fe_eq:
                fixpoint = True
                last = i
                stage_reports.append(report)
                break
        stage_reports.append(report)
        prev = bin_path
        last = i

    pass_gate = bool(fixpoint)
    if pass_gate:
        print(f"STAGE_LOOP: PASS fixpoint at stage{last} (frontend == backend)")
    else:
        print(f"STAGE_LOOP: FAIL no fixpoint after {last} stages backend_eq={int(be_eq)} frontend_eq={int(fe_eq)}")
    last_dir = cfg.work / f"stage{last}"
    last_bin = cfg.work / f"ouro1_stage{last}"
    arts = artifact_summary(last_dir, last_bin) if last else {}
    data = {
        "gate": "stage_loop",
        "pass": pass_gate,
        "fixpoint": fixpoint,
        "fast_path": False,
        "input_signature": signature,
        "stages": last,
        "backend_eq": be_eq,
        "frontend_eq": fe_eq,
        "max": cfg.max_stages,
        "fuel": cfg.fuel,
        "backend_bytes": arts.get("backend_bytes", 0),
        "frontend_bytes": arts.get("frontend_bytes", 0),
        "artifacts": arts,
        "elapsed_s": round(now() - started, 6),
        "stage_reports": stage_reports,
        "c_build_summary": summarize_stage_c_builds(stage_reports),
        "module_cache_summary": summarize_module_caches(stage_reports),
        "signature_meta": {"kind": sig_meta.get("kind"), "digest_count": len(sig_meta.get("digests", {}))},
    }
    write_status(cfg, data)
    if cfg.promote and fixpoint:
        promote(cfg, last)
    return 0 if pass_gate else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="closed Ouro bootstrap stage loop")
    ap.add_argument("--promote", action="store_true", help="copy fixpoint stage into compiler/stage0 and update hashes")
    args = ap.parse_args(argv)
    try:
        cfg = build_config(args)
        return run_loop(cfg)
    except KeyboardInterrupt:
        print("STAGE_LOOP: interrupted; partial stage stamps were not promoted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
