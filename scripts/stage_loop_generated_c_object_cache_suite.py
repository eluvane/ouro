#!/usr/bin/env python3
"""Fake-compiler regressions for stage-loop generated-C object caching.

The fixtures use temporary paths and fake compiler outputs to check cache
behavior without a bootstrap build.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import stat
import sys
import tempfile
from collections import Counter
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
    deps = [src]
    header = src.with_suffix(".h")
    if src.name == "ouro_rt.c" and header.is_file():
        h.update(header.read_bytes())
        deps.append(header)
    # Include selected command-shape input in the fake object so flag changes are visible.
    h.update("\0".join(a for a in args if a.startswith("-O") or a.startswith("-D")).encode())
    outp.write_text("OBJ " + str(src) + " " + h.hexdigest() + "\n", encoding="utf-8")
    if mf:
        Path(mf).write_text(str(outp) + ": " + " ".join(map(str, deps)) + "\n", encoding="utf-8")
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


def test_adjacent_stage_object_reuse(tmp: Path) -> None:
    repo = tmp / "a"
    copy_repo(repo)
    fake_cc = tmp / "fake-adjacent-cc.py"
    write_fake_cc(fake_cc)
    seed = tmp / "adjacent-seed"
    seed.write_bytes(b"fixture seed\n")
    mod = import_stage_loop(repo)
    signature = ("fixture-inputs", {"digests": {"seed_binary": mod.file_digest(seed)}})
    static = {"static/ouro_rt", "static/bootstrap", "static/fe_link"}

    def run_case(index: int, case: str, expected: set[str]) -> None:
        build = repo / f"b{index}"
        log = build / "cc.log"
        env = {"CC": str(fake_cc), "FAKE_CC_LOG": str(log), "OURO_CCACHE": "disabled",
               "OURO_CACHE": str(int(case != "cache-off")), "OURO_STAGE_MAX": "2", "OURO_STAGE_FAST_PATH": "0",
               "OURO_BUILD_DIR": str(build), "OURO_C_BUILD_DIR": str(build / "c"),
               "OURO_CACHE_DIR": str(repo / "_cache_test"), "OURO_JOBS": "1"}

        def emit_backend(_prev, out, _err, _cfg, _stage):
            out.write_text("int backend_symbol(void){return 2;}\n", encoding="utf-8")
            return {}

        def emit_frontend(_prev, out, _err, stage, cfg):
            value = 2 if stage == 2 and case == "different-c" else 1
            out.write_text(f"int frontend_symbol(void){{return {value};}}\n", encoding="utf-8")
            if stage == 2:
                if case == "changed-compiler":
                    with fake_cc.open("a", encoding="utf-8") as stream:
                        stream.write("\n# same reported version\n")
                elif case == "changed-flags":
                    cfg.build_cfg.values["opt_level"] = "O2"
                elif case == "changed-dependency":
                    with (repo / "runtime/ouro_rt.h").open("a", encoding="utf-8") as stream:
                        stream.write("\n/* changed dependency */\n")
                elif case == "corrupt-object":
                    stamp = mod.load_json(cfg.work / "stage1/c_build_report.json")
                    obj = next(row["object"] for row in stamp["sources"] if row["label"] == "static/bootstrap")
                    (repo / obj).write_bytes(b"corrupt previous object")
            return {}

        with patch.dict(os.environ, env), patch.object(mod, "ensure_seed", return_value=seed), \
             patch.object(mod, "stage_signature", return_value=signature), \
             patch.object(mod, "emit_backend", side_effect=emit_backend) as backend, \
             patch.object(mod, "emit_frontend", side_effect=emit_frontend) as frontend:
            cfg = make_cfg(mod, repo)
            assert mod.run_loop(cfg) == int(case == "different-c")

        result = mod.load_json(cfg.result)
        assert result["fixpoint"] is (case != "different-c"), result
        assert len(backend.call_args_list) == len(frontend.call_args_list) == 2
        assert frontend.call_args_list[1].args[0] == cfg.work / "ouro1_stage1"
        assert counts(log) == (10 - len(expected), 2), result
        report = mod.load_json(cfg.work / "stage2/c_build_report.json")
        assert report["target"] == "stage_loop_ouro1_stage2", report
        assert {row["label"] for row in report["sources"] if row.get("object_reused_from")} == expected, report
        assert [row["label"] for row in report["sources"][:2]] == ["stage2/frontend", "stage2/backend"]
        assert all("stage2" in row["source"] for row in report["sources"][:2]), report
        assert report["link_cache"] == "miss", report
        stamp = mod.load_json(cfg.work / "stage2/stage.stamp.json")
        assert stamp["artifacts"]["binary_sha256"] == mod.sha256_file(cfg.work / "ouro1_stage2")
        if case == "corrupt-object":
            stamp = mod.load_json(cfg.work / "stage1/c_build_report.json")
            obj = next(row["object"] for row in stamp["sources"] if row["label"] == "static/bootstrap")
            assert (repo / obj).read_bytes() == b"corrupt previous object"

    for index, (case, expected) in enumerate((
        ("equal", static),
        ("different-c", set()),
        ("cache-off", set()),
        ("changed-compiler", set()),
        ("changed-flags", set()),
        ("changed-dependency", static - {"static/ouro_rt"}),
        ("corrupt-object", static - {"static/bootstrap"}),
    )):
        run_case(index, case, expected)


def test_stage_configuration_selects_c_compiler_once(tmp: Path) -> None:
    import stage_loop as mod

    compiler = str(tmp / "gcc-fixture")
    values = {**mod.OB.DEFAULTS, "cc": "cc", "ccache": "disabled", "jobs": 1}
    with (patch.object(mod.OB, "load_config", return_value=mod.OB.ResolvedConfig(values, {})),
          patch.object(shutil, "which", side_effect={"cc": None, "gcc": compiler}.__getitem__) as discover):
        cfg = mod.build_config(argparse.Namespace(promote=False))
    assert cfg.cc == cfg.env["CC"] == "gcc"
    assert [call.args for call in discover.call_args_list] == [("cc",), ("gcc",)]


def test_stage_c_identity_resolves_each_command_once(tmp: Path) -> None:
    import stage_loop as mod

    cc = tmp / "gcc-fixture"
    cc.write_bytes(b"version one")
    values = {**mod.OB.DEFAULTS, "cc": "cc", "ccache": "disabled"}
    cfg = SimpleNamespace(build_cfg=mod.OB.ResolvedConfig(values, {}))

    def expected(commands, paths):
        return mod.hash_json({"commands": commands, "compiler": [mod.file_digest(p.resolve()) for p in paths],
                              "flags": mod.OB.profile_cflags(cfg.build_cfg), "ccache": "disabled",
                              "environment": dict(os.environ)})

    candidates = {"cc": None, "gcc": str(cc)}
    with patch.object(shutil, "which", side_effect=candidates.__getitem__) as discover:
        baseline = mod.c_compile_identity(cfg)
        assert baseline == expected(["gcc"], [cc])
        assert [call.args for call in discover.call_args_list] == [("cc",), ("gcc",)]

        saved = cc.stat()
        cc.write_bytes(b"version two")
        os.utime(cc, ns=(saved.st_atime_ns, saved.st_mtime_ns))
        discover.reset_mock()
        changed = mod.c_compile_identity(cfg)
        assert changed == expected(["gcc"], [cc]) and changed != baseline
        assert [call.args for call in discover.call_args_list] == [("cc",), ("gcc",)]

    values["ccache"] = "auto"
    with (patch.object(shutil, "which", side_effect={**candidates, "ccache": str(tmp / "ccache")}.__getitem__),
          patch.object(mod, "file_digest", side_effect=AssertionError("ccache bypassed the reuse guard"))):
        assert mod.c_compile_identity(cfg) is None

    shim = (tmp / "compiler.py").resolve()
    shim.write_bytes(b"# compiler fixture\n")
    values.update(cc=str(shim), ccache="disabled")
    with patch.object(shutil, "which", side_effect={str(shim): None, sys.executable: str(cc)}.__getitem__) as discover:
        assert mod.c_compile_identity(cfg) == expected([sys.executable, str(shim)], [cc, shim])
        assert [call.args for call in discover.call_args_list] == [(str(shim),), (sys.executable,)]


def test_stage_artifact_comparison(tmp: Path) -> None:
    import stage_loop as mod

    tmp.mkdir()
    left, right = tmp / "left.c", tmp / "right.c"
    prefix = b"\0" * (1024 * 1024)
    left.write_bytes(prefix + b"\xff")
    right.write_bytes(prefix + b"\xff")
    assert mod.files_eq(left, right)
    saved = right.stat()
    right.write_bytes(prefix + b"\0")
    os.utime(right, ns=(saved.st_atime_ns, saved.st_mtime_ns))
    assert right.stat().st_mtime_ns == saved.st_mtime_ns
    assert not mod.files_eq(left, right)
    right.write_bytes(prefix)
    assert not mod.files_eq(left, right) and not mod.files_eq(right, left)
    assert not mod.files_eq(tmp, right) and not mod.files_eq(left, tmp / "missing.c")

    class FailingRead(BytesIO):
        def __init__(self, data: bytes, fail_at: int, failure: OSError | None):
            super().__init__(data)
            self.fail_at = fail_at
            self.failure = failure

        def read(self, size: int = -1) -> bytes:
            if self.failure is not None and self.tell() >= self.fail_at:
                raise self.failure
            return super().read(size)

    left_error = OSError("left read failed")
    right_error = OSError("right read failed")
    for first_failure, expected in ((None, right_error), (left_error, left_error)):
        left_stream = FailingRead(prefix + prefix + b"\0", 2 * len(prefix), first_failure)
        right_stream = FailingRead(b"\xff" + prefix, len(prefix), right_error)
        with patch.object(Path, "open", side_effect=[left_stream, right_stream]):
            try:
                mod.files_eq(left, right)
            except OSError as error:
                assert error is expected
            else:
                raise AssertionError("comparison hid a read error after a mismatch")
        assert left_stream.closed and right_stream.closed

    with patch.object(Path, "open", side_effect=[FailingRead(prefix, len(prefix), left_error), right_error]):
        try:
            mod.files_eq(left, right)
        except OSError as error:
            assert error is left_error
        else:
            raise AssertionError("right open error hid a left read error")


def test_stage_stamp_artifacts(tmp: Path) -> None:
    import stage_loop as mod

    seed_dir = tmp / "compiler" / "stage0"
    frontend, backend = write_generated_sources(seed_dir)
    seed = tmp / "seed"
    seed.write_bytes(b"seed")
    signature = ("fixture-inputs", {"digests": {"seed_binary": mod.file_digest(seed)}})
    work = tmp / "work"
    cfg = SimpleNamespace(work=work, cache_root=tmp / "cache", cache_enabled=False,
                          result=work / "result.json", status_pub=work / "status.json",
                          max_stages=2, fuel="16000", promote=False)
    hashes = Counter({work / "ouro1_stage0": 1, work / "ouro1_stage1": 2, work / "ouro1_stage2": 2})
    for name in ("driver_u.c", "backend_u.c"):
        hashes[work / "stage1" / name] = 1
        hashes[work / "stage2" / name] = 2

    def emit_backend(_prev, out, _err, _cfg, _stage):
        shutil.copyfile(backend, out)
        return {}

    def emit_frontend(_prev, out, _err, _stage, _cfg):
        shutil.copyfile(frontend, out)
        return {}

    def build(_frontend, _backend, out, _stage, _cfg):
        out.write_bytes(b"binary")
        return {}

    with patch.dict(os.environ, {"OURO_STAGE_FAST_PATH": "0"}), patch.object(mod, "ROOT", tmp), \
         patch.object(mod, "ensure_seed", return_value=seed), \
         patch.object(mod, "stage_signature", return_value=signature), \
         patch.object(mod, "emit_backend", side_effect=emit_backend), \
         patch.object(mod, "emit_frontend", side_effect=emit_frontend), \
         patch.object(mod, "build_stage_binary", side_effect=build) as builder:
        for reused, damaged in (([False, False], False), ([True, True], False), ([True, False], True)):
            if damaged:
                (work / "ouro1_stage2").write_bytes(b"damage")
            builder.reset_mock()
            with patch.object(mod, "sha256_file", wraps=mod.sha256_file) as digest, \
                 patch.object(mod, "files_eq", wraps=mod.files_eq) as compare:
                assert mod.run_loop(cfg) == 0
            expected_hashes = hashes.copy()
            if damaged:
                for path in (work / "stage2/backend_u.c", work / "stage2/driver_u.c", work / "ouro1_stage2"):
                    expected_hashes[path] += 1
            assert Counter(call.args[0] for call in digest.call_args_list) == expected_hashes
            assert compare.call_count == 2
            assert [call.args[3] for call in builder.call_args_list] == [
                stage for stage, hit in enumerate(reused, start=1) if not hit
            ]
            result = mod.load_json(cfg.result)
            assert [report["reused"] for report in result["stage_reports"]] == reused
            for report in result["stage_reports"]:
                stamp = mod.load_json(work / f"stage{report['stage']}" / "stage.stamp.json")
                assert stamp["artifacts"] == stamp["report"]["artifacts"] == report["artifacts"]
            assert result["artifacts"] == result["stage_reports"][-1]["artifacts"]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ouro-stage-cobj-suite-") as d:
        tmp = Path(d)
        test_stage_configuration_selects_c_compiler_once(tmp)
        test_stage_c_identity_resolves_each_command_once(tmp)
        test_stage_artifact_comparison(tmp / "comparison")
        test_stage_stamp_artifacts(tmp / "stamp")
        test_generated_c_object_cache(tmp)
        test_promote_normalizes_generated_c_to_lf(tmp)
        test_adjacent_stage_object_reuse(tmp)
    print("STAGE_LOOP_GENERATED_C_OBJECT_CACHE_SUITE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
