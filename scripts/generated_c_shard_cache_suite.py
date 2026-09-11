#!/usr/bin/env python3
"""Fake-compiler regressions for generated-C shard/cache behavior.

The suite drives scripts/stage_loop.py's C build seam with generated-like C so it
can prove shard-level invalidation without running the real bootstrap loop.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import stat
import sys
import tempfile
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def copy_repo(dst: Path) -> None:
    ignore = shutil.ignore_patterns("_build", "_cache", ".git", "*.pyc", "__pycache__")
    shutil.copytree(ROOT, dst, ignore=ignore)


def write_fake_cc(path: Path) -> None:
    path.write_text(
        r'''#!/usr/bin/env python3
import hashlib, os, stat, sys
from pathlib import Path

args = sys.argv[1:]
if "--version" in args:
    print(os.environ.get("FAKE_CC_VERSION", "fake-shard-cc 1.0"))
    sys.exit(0)

def arg_after(flag):
    if flag not in args:
        return None
    i = args.index(flag)
    if i + 1 >= len(args):
        raise SystemExit(f"missing {flag} value")
    return args[i + 1]

out = arg_after("-o")
if not out:
    raise SystemExit("missing -o")
outp = Path(out)
outp.parent.mkdir(parents=True, exist_ok=True)
log_base = Path(os.environ["FAKE_CC_LOG"])
# Compiler jobs run concurrently. A separate file per process avoids relying on
# cross-process append semantics, which can lose records on Windows.
log = log_base.with_name(log_base.name + "." + str(os.getpid()))

if "-c" in args:
    src = Path(args[args.index("-c") + 1])
    mf = arg_after("-MF")
    h = hashlib.sha256(src.read_bytes()).hexdigest()
    outp.write_text("OBJ " + str(src) + " " + h + "\n", encoding="utf-8")
    if mf:
        # Enough for ouro_build's dep parser; real compiler depfiles are covered
        # by the ordinary build cache suite.
        Path(mf).write_text(str(outp) + ": " + str(src) + "\n", encoding="utf-8")
    with log.open("a", encoding="utf-8") as f:
        f.write("COMPILE " + str(src) + "\n")
    sys.exit(0)

payload = ["#!/bin/sh", "# fake linked stage binary", "exit 0"]
for a in args:
    p = Path(a)
    if p.suffix == ".o" and p.exists():
        payload.append(p.read_text(encoding="utf-8", errors="replace"))
outp.write_text("\n".join(payload) + "\n", encoding="utf-8")
outp.chmod(outp.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
with log.open("a", encoding="utf-8") as f:
    f.write("LINK " + str(outp) + "\n")
''',
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def import_stage_loop(repo: Path):
    for name in ("stage_loop_under_test", "frontend_regen", "generated_c_shards", "ouro_build"):
        sys.modules.pop(name, None)
    sys.path.insert(0, str(repo / "scripts"))
    try:
        spec = importlib.util.spec_from_file_location("stage_loop_under_test", repo / "scripts/stage_loop.py")
        if spec is None or spec.loader is None:
            raise AssertionError("cannot import stage_loop.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["stage_loop_under_test"] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod
    finally:
        try:
            sys.path.remove(str(repo / "scripts"))
        except ValueError:
            pass


def counts(log: Path) -> tuple[int, int]:
    paths = [log, *sorted(log.parent.glob(log.name + ".*"))]
    text = "".join(path.read_text(encoding="utf-8") for path in paths if path.is_file())
    return text.count("COMPILE "), text.count("LINK ")


def make_cfg(mod):
    return mod.build_config(argparse.Namespace(promote=False))


def write_generated_sources(stage_dir: Path) -> tuple[Path, Path]:
    stage_dir.mkdir(parents=True, exist_ok=True)
    fe = stage_dir / "driver_u.c"
    be = stage_dir / "backend_u.c"
    fe.write_text(
        '''/* Generated frontend pack: fake */
/* ---- frontend TU module=lx ---- */
#include "ouro_rt.h"
static ouro_v *ouro_lx_g1(void){return 0;}
int ouro_export_count_lx(void){return 1;}
const char *ouro_export_name_lx(int i){return i == 0 ? "lx" : "";}
ouro_v *ouro_export_value_lx(int i){return i == 0 ? ouro_lx_g1() : 0;}
/* ---- frontend TU module=pa ---- */
#include "ouro_rt.h"
static ouro_v *ouro_pa_g1(void){return 0;}
int ouro_export_count_pa(void){return 1;}
const char *ouro_export_name_pa(int i){return i == 0 ? "pa" : "";}
ouro_v *ouro_export_value_pa(int i){return i == 0 ? ouro_pa_g1() : 0;}
''',
        encoding="utf-8",
    )
    be.write_text(
        '''#include "ouro_rt.h"
static ouro_v *ouro_g1(void);
static ouro_v *ouro_g2(void);
static ouro_v *ouro_g3(void);
static ouro_v *ouro_c1;
static ouro_v *ouro_g1(void){if(ouro_c1==0)ouro_c1=ouro_fast("one");return ouro_c1;}
static ouro_v *ouro_c2;
static ouro_v *ouro_g2(void){if(ouro_c2==0)ouro_c2=ouro_g1();return ouro_c2;}
static ouro_v *ouro_c3;
static ouro_v *ouro_g3(void){if(ouro_c3==0)ouro_c3=ouro_g2();return ouro_c3;}
int ouro_export_count_be(void){return 3;}
const char *ouro_export_name_be(int i){switch(i){case 0: return "one"; case 1: return "two"; case 2: return "three"; default: return "";}}
ouro_v *ouro_export_value_be(int i){switch(i){case 0: return ouro_g1(); case 1: return ouro_g2(); case 2: return ouro_g3(); default: return 0;}}
''',
        encoding="utf-8",
    )
    return fe, be


def shard_mtimes(repo: Path, report: dict) -> dict[str, int]:
    shards = report["generated_c_shards"]["shards"]
    return {s["label"]: (repo / s["path"]).stat().st_mtime_ns for s in shards if s.get("compile")}


def miss_labels(report: dict) -> list[str]:
    return [s["label"] for s in report["sources"] if s.get("cache") == "miss"]


def test_shard_invalidation(tmp: Path) -> None:
    repo = tmp / "repo"
    copy_repo(repo)
    fake_cc = tmp / "fake-shard-cc.py"
    cc_log = tmp / "fake-shard-cc.log"
    write_fake_cc(fake_cc)
    env = {
        "CC": str(fake_cc),
        "FAKE_CC_LOG": str(cc_log),
        "OURO_CCACHE": "disabled",
        "OURO_CACHE": "1",
        "OURO_BUILD_DIR": str(repo / "_build"),
        "OURO_C_BUILD_DIR": str(repo / "_build/c"),
        "OURO_CACHE_DIR": str(repo / "_cache_test"),
        "OURO_JOBS": "10",
        "OURO_GENERATED_C_SHARD_BACKEND_GROUPS": "1",
    }
    with patch.dict(os.environ, env):
        mod = import_stage_loop(repo)
        cfg = make_cfg(mod)
        stage_dir = repo / "_build/stage_loop/stage1"
        fe, be = write_generated_sources(stage_dir)
        out = repo / "_build/stage_loop/ouro1_stage1"

        first = mod.build_stage_binary(fe, be, out, 1, cfg)
        assert first["generated_c_shards"]["summary"]["compile_shards"] == 6, first
        assert counts(cc_log) == (9, 1), first
        mtimes_first = shard_mtimes(repo, first)
        manifest = repo / first["generated_c_shards"]["manifest_path"]
        manifest_stat_first = manifest.stat()
        gcs_module = sys.modules["generated_c_shards"]
        original_write = gcs_module.write_text_if_changed
        shard_compare_calls: list[str] = []

        def counted_write(path: Path, content: str) -> str:
            if path.suffix in {".c", ".h"}:
                shard_compare_calls.append(str(path))
            return original_write(path, content)

        gcs_module.write_text_if_changed = counted_write
        try:
            second = mod.build_stage_binary(fe, be, out, 1, cfg)
        finally:
            gcs_module.write_text_if_changed = original_write
        assert counts(cc_log) == (9, 1), second
        assert second["generated_c_shards"]["summary"]["shard_hits"] >= 6, second
        assert shard_mtimes(repo, second) == mtimes_first, "no-change run rewrote shard files"
        manifest_stat_second = manifest.stat()
        assert (manifest_stat_second.st_ino, manifest_stat_second.st_mtime_ns) == (
            manifest_stat_first.st_ino,
            manifest_stat_first.st_mtime_ns,
        ), "no-change run rewrote the stable shard manifest"
        assert shard_compare_calls == [], shard_compare_calls
        warm_summary = second["generated_c_shards"]["summary"]
        assert warm_summary["source_reads"] == 2, warm_summary
        assert warm_summary["plan_metadata_hashes"] == len(second["generated_c_shards"]["shards"]), warm_summary
        assert warm_summary["content_compare_calls"] == 0, warm_summary
        assert warm_summary["content_compare_calls_avoided"] == len(second["generated_c_shards"]["shards"]), warm_summary
        assert warm_summary["content_compare_bytes_avoided"] == warm_summary["total_bytes"], warm_summary

        fe.write_text(fe.read_text(encoding="utf-8").replace('return i == 0 ? "pa" : "";', 'return i == 0 ? "pa2" : "";'), encoding="utf-8")
        third = mod.build_stage_binary(fe, be, out, 1, cfg)
        assert counts(cc_log) == (10, 2), third
        assert miss_labels(third) == ["stage1/frontend/pa"], third

        be.write_text(be.read_text(encoding="utf-8").replace('ouro_g2(void){if(ouro_c2==0)ouro_c2=ouro_g1();return ouro_c2;}', 'ouro_g2(void){if(ouro_c2==0)ouro_c2=ouro_fast("two2");return ouro_c2;}'), encoding="utf-8")
        fourth = mod.build_stage_binary(fe, be, out, 1, cfg)
        assert counts(cc_log) == (11, 3), fourth
        assert miss_labels(fourth) == ["stage1/backend/g001-001"], fourth

        # A generator/tool hash change must flow into shard content and object
        # command/dependency hashes without changing canonical generated inputs.
        gcs = repo / "scripts/generated_c_shards.py"
        gcs.write_text(gcs.read_text(encoding="utf-8") + "\n# fake tool hash invalidation\n", encoding="utf-8")
        mod2 = import_stage_loop(repo)
        cfg2 = make_cfg(mod2)
        fifth = mod2.build_stage_binary(fe, be, out, 1, cfg2)
        assert counts(cc_log) == (17, 4), fifth
        assert len(miss_labels(fifth)) == 6, fifth

        manifest = repo / fifth["generated_c_shards"]["manifest_path"]
        manifest.write_text('{"kind":"ouro.generated-c-shards.v1"', encoding="utf-8")
        sixth = mod2.build_stage_binary(fe, be, out, 1, cfg2)
        assert counts(cc_log) == (17, 4), sixth
        assert sixth["generated_c_shards"]["manifest_cache"] == "miss", sixth
        assert sixth["generated_c_shards"]["summary"]["shard_revalidated"] > 0, sixth

        order1 = [s["label"] for s in fifth["generated_c_shards"]["shards"]]
        order2 = [s["label"] for s in sixth["generated_c_shards"]["shards"]]
        assert order1 == order2, "shard order changed across runs"


def test_backend_cluster_memory_shape() -> None:
    source = (ROOT / "scripts/generated_c_shards.py").read_text(encoding="utf-8")
    assert "for start in range(0, len(text), chunk_chars)" in source
    assert "clusters: List[Tuple[str, int, int]]" in source
    assert "clusters.append((g_name, list(lines[cluster_start" not in source
    assert "transform_backend_cluster(\n                    lines," in source


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ouro-generated-c-shard-suite-") as d:
        test_shard_invalidation(Path(d))
    test_backend_cluster_memory_shape()
    print("GENERATED_C_SHARD_CACHE_SUITE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
