#!/usr/bin/env python3
"""Fake-compiler regressions for stage-loop generated-C object caching.

This suite imports scripts/stage_loop.py from a temporary repo copy and drives
only the C build seam with fake generated frontend/backend C. It proves the
stage-loop no longer needs a monolithic direct C compile/link to validate cache
behavior.
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

from build_cache_config_suite import counts

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
    print(os.environ.get("FAKE_CC_VERSION", "fake-stage-cc 1.0"))
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
log = Path(os.environ["FAKE_CC_LOG"])

if "-c" in args:
    src = Path(args[args.index("-c") + 1])
    mf = arg_after("-MF")
    h = hashlib.sha256()
    h.update(src.read_bytes())
    # Include selected command-shape input in the fake object so flag changes are visible.
    h.update("\0".join(a for a in args if a.startswith("-O") or a.startswith("-D")).encode())
    outp.write_text("OBJ " + str(src) + " " + h.hexdigest() + "\n", encoding="utf-8")
    if mf:
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
    for name in ("stage_loop_under_test", "frontend_regen", "ouro_build"):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location("stage_loop_under_test", repo / "scripts/stage_loop.py")
    if spec is None or spec.loader is None:
        raise AssertionError("cannot import stage_loop.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["stage_loop_under_test"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod




def write_generated_sources(stage_dir: Path, *, frontend: str = "frontend v1", backend: str = "backend v1") -> tuple[Path, Path]:
    stage_dir.mkdir(parents=True, exist_ok=True)
    fe = stage_dir / "driver_u.c"
    be = stage_dir / "backend_u.c"
    fe.write_text("/* " + frontend + " */\nint frontend_symbol(void){return 1;}\n", encoding="utf-8")
    be.write_text("/* " + backend + " */\nint backend_symbol(void){return 2;}\n", encoding="utf-8")
    return fe, be


def make_cfg(mod, _repo: Path):
    return mod.build_config(argparse.Namespace(promote=False))


def test_generated_c_object_cache(tmp: Path) -> None:
    repo = tmp / "repo"
    copy_repo(repo)
    fake_cc = tmp / "fake-stage-cc.py"
    cc_log = tmp / "fake-stage-cc.log"
    write_fake_cc(fake_cc)
    env = {
        "CC": str(fake_cc),
        "FAKE_CC_LOG": str(cc_log),
        "OURO_CCACHE": "disabled",
        "OURO_CACHE": "1",
        "OURO_BUILD_DIR": str(repo / "_build"),
        "OURO_C_BUILD_DIR": str(repo / "_build/c"),
        "OURO_CACHE_DIR": str(repo / "_cache_test"),
        # jobs=1: the fake-cc log is a single file; parallel Windows
        # appends drop COMPILE lines and trip the counts() asserts
        # even when the c-build report is correct.
        "OURO_JOBS": "1",
    }
    with patch.dict(os.environ, env):
        mod = import_stage_loop(repo)
        cfg = make_cfg(mod, repo)
        stage_dir = repo / "_build/stage_loop/stage1"
        fe, be = write_generated_sources(stage_dir)
        out = repo / "_build/stage_loop/ouro1_stage1"

        first = mod.build_stage_binary(fe, be, out, 1, cfg)
        assert counts(cc_log) == (5, 1), first
        assert first["compile_misses"] == 5 and first["link_cache"] == "miss", first

        second = mod.build_stage_binary(fe, be, out, 1, cfg)
        assert counts(cc_log) == (5, 1), second
        assert second["compile_hits"] == 5 and second["link_cache"] == "hit", second

        be.write_text(be.read_text(encoding="utf-8") + "\n/* backend edit */\n", encoding="utf-8")
        third = mod.build_stage_binary(fe, be, out, 1, cfg)
        assert counts(cc_log) == (6, 2), third
        assert third["compile_misses"] == 1 and third["link_cache"] == "miss", third
        assert [s for s in third["sources"] if s["cache"] == "miss"][0]["label"] == "stage1/backend"

        fe.write_text(fe.read_text(encoding="utf-8") + "\n/* frontend edit */\n", encoding="utf-8")
        fourth = mod.build_stage_binary(fe, be, out, 1, cfg)
        assert counts(cc_log) == (7, 3), fourth
        assert fourth["compile_misses"] == 1 and fourth["link_cache"] == "miss", fourth
        assert [s for s in fourth["sources"] if s["cache"] == "miss"][0]["label"] == "stage1/frontend"

        # A partial/interrupted stamp must not be accepted as a valid object hit.
        backend_obj = next(Path(repo, s["object"]) for s in fourth["sources"] if s["label"] == "stage1/backend")
        backend_obj.with_suffix(".cmdhash").write_text('{"kind":"ouro.c-object.v2"', encoding="utf-8")
        fifth = mod.build_stage_binary(fe, be, out, 1, cfg)
        assert counts(cc_log) == (8, 3), fifth
        assert fifth["compile_misses"] == 1 and fifth["link_cache"] == "hit", fifth

    # Changed C flags/tool command invalidate objects and link stamps.
    with patch.dict(os.environ, {**env, "OURO_OPT_LEVEL": "O2"}):
        mod = import_stage_loop(repo)
        cfg_o2 = make_cfg(mod, repo)
        sixth = mod.build_stage_binary(fe, be, out, 1, cfg_o2)
        assert counts(cc_log) == (13, 4), sixth
        assert sixth["compile_misses"] == 5 and sixth["link_cache"] == "miss", sixth

    with patch.dict(os.environ, {**env, "FAKE_CC_VERSION": "fake-stage-cc 2.0"}):
        mod = import_stage_loop(repo)
        cfg_cc2 = make_cfg(mod, repo)
        seventh = mod.build_stage_binary(fe, be, out, 1, cfg_cc2)
        assert counts(cc_log) == (18, 5), seventh
        assert seventh["compile_misses"] == 5 and seventh["link_cache"] == "miss", seventh


def test_promote_normalizes_generated_c_to_lf(tmp: Path) -> None:
    repo = tmp / "repo-promote"
    copy_repo(repo)
    env = {
        "OURO_BUILD_DIR": str(repo / "_build"),
        "OURO_C_BUILD_DIR": str(repo / "_build/c"),
        "OURO_CACHE_DIR": str(repo / "_cache_test"),
    }
    with patch.dict(os.environ, env):
        mod = import_stage_loop(repo)
        cfg = make_cfg(mod, repo)
        stage_dir = cfg.work / "stage2"
        stage_dir.mkdir(parents=True, exist_ok=True)
        (stage_dir / "driver_u.c").write_bytes(b"driver\r\nline\r\n")
        (stage_dir / "backend_u.c").write_bytes(b"backend\r\nline\r\n")

        original_run = mod.subprocess.run
        mod.subprocess.run = lambda *_args, **_kwargs: None
        try:
            mod.promote(cfg, 2)
        finally:
            mod.subprocess.run = original_run

        driver = repo / "compiler/stage0/driver_u.c"
        backend = repo / "compiler/stage0/backend_u.c"
        assert driver.read_bytes() == b"driver\nline\n"
        assert backend.read_bytes() == b"backend\nline\n"
        manifest = (repo / "docs/generated_artifact_hashes.sha256").read_text(encoding="ascii")
        assert manifest == (
            f"{mod.sha256_file(backend)}  compiler/stage0/backend_u.c\n"
            f"{mod.sha256_file(driver)}  compiler/stage0/driver_u.c\n"
        )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ouro-stage-cobj-suite-") as d:
        tmp = Path(d)
        test_generated_c_object_cache(tmp)
        test_promote_normalizes_generated_c_to_lf(tmp)
    print("STAGE_LOOP_GENERATED_C_OBJECT_CACHE_SUITE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
