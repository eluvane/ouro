#!/usr/bin/env python3
"""Fast regression checks for frontend regeneration and stage-loop caching.

Uses fake ouro1/cc tools so it locks build-graph behavior without requiring a
multi-minute real frontend regeneration.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import frontend_regen

from build_cache_config_suite import counts

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_FRONTEND_TUS = len(frontend_regen.FRONTEND_TUS)


def copy_repo(dst: Path) -> None:
    ignore = shutil.ignore_patterns("_build", "_cache", ".git", "*.pyc", "__pycache__")
    shutil.copytree(ROOT, dst, ignore=ignore)


def write_fake_ouro1(path: Path) -> None:
    # Python, not a shebang-sh file named .py: Windows CreateProcess and
    # frontend_regen.ouro1_cmd both run *.py with the host interpreter.
    path.write_text(
        r'''#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
mod = ""
root = ""
if "--module" in args:
    i = args.index("--module")
    if i + 2 < len(args):
        mod, root = args[i + 1], args[i + 2]
if not mod:
    sys.stderr.write("fake ouro1: missing --module\n")
    sys.exit(2)
log = os.environ.get("FAKE_OURO1_LOG", "fake_ouro1.log")
with open(log, "a", encoding="utf-8") as f:
    f.write(f"{mod} {root}\n")
sys.stdout.write("typedef struct ouro_v ouro_v;\n")
sys.stdout.write("typedef struct ouro_env ouro_env;\n")
sys.stdout.write("static ouro_v *fake_generated(void){return 0;}\n")
sys.stdout.write(f"int ouro_export_count{mod} = 0;\n")
sys.stdout.write(f'const char *ouro_export_name{mod}(int i){{return "";}}\n')
sys.stdout.write(f"ouro_v *ouro_export_value{mod}(int i){{return 0;}}\n")
''',
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write_fake_cc(path: Path, template: Path) -> None:
    script = f'''#!/usr/bin/env python3
import hashlib, os, shutil, stat, sys
from pathlib import Path

args = sys.argv[1:]
if "--version" in args:
    print(os.environ.get("FAKE_CC_VERSION", "fake-cc 1.0"))
    sys.exit(0)

def arg_after(flag):
    if flag not in args:
        return None
    i = args.index(flag)
    if i + 1 >= len(args):
        raise SystemExit(f"missing {{flag}} value")
    return args[i + 1]

out = arg_after("-o")
if not out:
    raise SystemExit("fake cc missing -o")
outp = Path(out)
outp.parent.mkdir(parents=True, exist_ok=True)
log = Path(os.environ["FAKE_CC_LOG"])

if "-c" in args:
    src = Path(args[args.index("-c") + 1])
    mf = arg_after("-MF")
    h = hashlib.sha256(src.read_bytes()).hexdigest() if src.exists() else "missing"
    outp.write_text("OBJ " + h + "\\n", encoding="utf-8")
    if mf:
        Path(mf).write_text(str(outp) + ": " + str(src) + "\\n", encoding="utf-8")
    with log.open("a", encoding="utf-8") as f:
        f.write("COMPILE " + str(src) + "\\n")
    sys.exit(0)

shutil.copyfile({str(template)!r}, outp)
outp.chmod(outp.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
with log.open("a", encoding="utf-8") as f:
    f.write("LINK " + str(outp) + "\\n")
'''
    path.write_text(script, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)



def run(repo: Path, cmd: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    p = subprocess.run(cmd, cwd=repo, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if p.returncode != 0:
        raise AssertionError(f"cmd={cmd!r} rc={p.returncode}\n{p.stdout}")
    return p


def count_lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0


def test_native_stack_limits() -> None:
    if os.name == "nt":
        return
    import resource

    from repo_support import configure_native_stack

    inherited = resource.getrlimit(resource.RLIMIT_STACK)
    try:
        resource.setrlimit(resource.RLIMIT_STACK, inherited)
    except (OSError, ValueError):
        before = resource.getrlimit(resource.RLIMIT_STACK)
        address_space = resource.getrlimit(resource.RLIMIT_AS)
        configure_native_stack()
        assert resource.getrlimit(resource.RLIMIT_STACK) == before
        assert resource.getrlimit(resource.RLIMIT_AS) == address_space
        return
    # Isolate hard-limit changes from the suite. Native entry points need more
    # than the usual 8 MiB stack, but must preserve stricter host limits and AS.
    code = """
import resource, sys
sys.path.insert(0, "scripts")
from repo_support import configure_native_stack
soft, hard, expected = map(int, sys.argv[1:])
resource.setrlimit(resource.RLIMIT_STACK, (soft, hard))
address_space = resource.getrlimit(resource.RLIMIT_AS)
configure_native_stack()
assert resource.getrlimit(resource.RLIMIT_STACK) == (expected, hard)
assert resource.getrlimit(resource.RLIMIT_AS) == address_space
"""

    mib = 1024 * 1024
    _, inherited_hard = inherited
    hard = 256 * mib if inherited_hard == resource.RLIM_INFINITY else min(256 * mib, inherited_hard)
    for soft, cap, expected in (
        (min(8 * mib, hard), hard, min(128 * mib, hard)),
        (min(4 * mib, hard), min(16 * mib, hard), min(16 * mib, hard)),
        (hard, hard, hard),
    ):
        run(ROOT, [sys.executable, "-c", code, str(soft), str(cap), str(expected)], os.environ.copy())


def test_frontend_final_and_tu_cache(tmp: Path) -> None:
    repo = tmp / "frontend_repo"
    copy_repo(repo)
    fake = tmp / "fake-ouro1.py"
    log = tmp / "frontend_ouro1.log"
    write_fake_ouro1(fake)
    env = os.environ.copy()
    env.update({"FAKE_OURO1_LOG": str(log), "OURO_CACHE": "1", "OURO_FRONTEND_JOBS": "1"})
    common = [
        sys.executable,
        "scripts/frontend_regen.py",
        "--ouro1",
        str(fake),
        "--out",
        "_build/test_driver.c",
        "--work",
        "_build/test_fe",
        "--cache-root",
        "_cache_test",
        "--jobs",
        "1",
    ]
    first = run(repo, common, env)
    assert f"tu_misses={EXPECTED_FRONTEND_TUS}" in first.stdout, first.stdout
    assert count_lines(log) == EXPECTED_FRONTEND_TUS

    output = repo / "_build/test_driver.c"
    expected = output.read_bytes()
    second = run(repo, common, env)
    assert "final cache-hit" in second.stdout, second.stdout
    assert count_lines(log) == EXPECTED_FRONTEND_TUS, "final fast-path must not invoke ouro1"

    final_cache, = (repo / "_cache_test/gen/frontend-final").glob("driver_*.c")
    final_cache.write_text("CORRUPT\n", encoding="utf-8")
    repaired = run(repo, common, env)
    assert "manifest fast-path" in repaired.stdout, repaired.stdout
    assert output.read_bytes() == expected
    assert final_cache.read_bytes() == expected
    assert count_lines(log) == EXPECTED_FRONTEND_TUS, "cache repair must not invoke ouro1"

    target = repo / "compiler/import_resolve.ouro"
    target.write_text(target.read_text(encoding="utf-8") + "\n-- cache invalidation smoke\n", encoding="utf-8")
    before = count_lines(log)
    third = run(repo, common, env)
    after = count_lines(log)
    delta = after - before
    assert 0 < delta < EXPECTED_FRONTEND_TUS, (
        f"small source change rebuilt {delta}/{EXPECTED_FRONTEND_TUS} TUs; output:\n{third.stdout}"
    )
    report = json.loads((repo / "_build/test_fe/frontend-regeneration.json").read_text(encoding="utf-8"))
    assert report["summary"]["tu_hits"] > 0 and report["summary"]["tu_misses"] == delta

    expected = output.read_bytes()

    def invalidate_outer_results() -> None:
        for cached in (repo / "_cache_test/gen/frontend-final").glob("driver_*"):
            cached.unlink()
        (repo / "_build/test_fe/frontend-regeneration.json").unlink()
        output.unlink()

    def current_report() -> dict:
        return json.loads((repo / "_build/test_fe/frontend-regeneration.json").read_text(encoding="utf-8"))

    unit = report["units"][0]
    tu_cache = repo / "_cache_test/gen/frontend-tu" / f"{unit['module']}_{unit['key']}.c"
    for damage in ("bytes", "missing", "malformed", "wrong-key", "invalid-export"):
        metadata = tu_cache.with_suffix(".json")
        if damage == "bytes":
            tu_cache.write_text("CORRUPT TU\n", encoding="utf-8")
        elif damage == "missing":
            metadata.unlink()
        elif damage == "malformed":
            metadata.write_text("{broken", encoding="utf-8")
        elif damage == "wrong-key":
            receipt = json.loads(metadata.read_text(encoding="utf-8"))
            receipt["input_key"] = "wrong"
            metadata.write_text(json.dumps(receipt), encoding="utf-8")
        else:
            tu_cache.write_text("no export table\n", encoding="utf-8")
            frontend_regen.record_cached_output(tu_cache, unit["key"])
        invalidate_outer_results()
        before = count_lines(log)
        run(repo, common, env)
        repaired = current_report()
        assert repaired["summary"]["tu_misses"] == 1, (damage, repaired)
        assert count_lines(log) == before + 1, damage
        assert output.read_bytes() == expected, damage
        assert frontend_regen.cached_output_matches(tu_cache, unit["key"]), damage

    pack_key = current_report()["pack_key"]
    pack_cache = repo / "_cache_test/gen/frontend-pack" / f"driver_{pack_key}.c"
    for damage in ("bytes", "missing", "malformed", "wrong-key"):
        metadata = pack_cache.with_suffix(".json")
        if damage == "bytes":
            pack_cache.write_text("CORRUPT PACK\n", encoding="utf-8")
        elif damage == "missing":
            metadata.unlink()
        elif damage == "malformed":
            metadata.write_text("[]", encoding="utf-8")
        else:
            receipt = json.loads(metadata.read_text(encoding="utf-8"))
            receipt["input_key"] = "wrong"
            metadata.write_text(json.dumps(receipt), encoding="utf-8")
        invalidate_outer_results()
        before = count_lines(log)
        run(repo, common, env)
        repaired = current_report()
        assert repaired["summary"]["tu_hits"] == EXPECTED_FRONTEND_TUS, (damage, repaired)
        assert repaired["summary"]["pack_cache"] == "miss", (damage, repaired)
        assert count_lines(log) == before, damage
        assert output.read_bytes() == expected and pack_cache.read_bytes() == expected, damage
        assert frontend_regen.cached_output_matches(pack_cache, pack_key), damage


def test_stage_source_unit_preparation(tmp: Path) -> None:
    import stage_loop as loop

    repo = tmp / "stage-source-units"
    repo.mkdir()
    sources = {
        "base.ouro": "",
        "shared.ouro": 'import "base.ouro";\n',
        "backend_leaf.ouro": "",
        "extra.ouro": "",
        "backend.ouro": 'import "shared.ouro";\nimport "backend_leaf.ouro";\n',
        "left.ouro": 'import "shared.ouro";\nimport "extra.ouro";\n',
        "right.ouro": 'import "shared.ouro", "extra.ouro", "shared.ouro";\n',
    }
    for name, text in sources.items():
        (repo / name).write_text(text, encoding="utf-8")
    tus = (
        ("left", "_left", "left.ouro", "left.c"),
        ("right", "_right", "right.ouro", "right.c"),
    )
    expected_graph = {
        "backend.ouro": ["base.ouro", "shared.ouro", "backend_leaf.ouro", "backend.ouro"],
        "left.ouro": ["base.ouro", "shared.ouro", "extra.ouro", "left.ouro"],
        "right.ouro": ["base.ouro", "shared.ouro", "extra.ouro", "right.ouro"],
    }
    expected_units = ["base.ouro", "shared.ouro", "backend_leaf.ouro", "backend.ouro",
                      "extra.ouro", "left.ouro", "right.ouro"]
    expected_reads = ["backend.ouro", "shared.ouro", "base.ouro", "backend_leaf.ouro",
                      "left.ouro", "extra.ouro", "right.ouro"]
    with patch.object(loop, "BACKEND_ROOT", "backend.ouro"), \
         patch.object(loop.freg, "ROOT", repo), \
         patch.object(loop.freg, "FRONTEND_TUS", tus), \
         patch.object(loop.freg, "import_targets", wraps=loop.freg.import_targets) as reads:
        for _attempt in range(2):
            reads.reset_mock()
            assert loop.all_stage_source_units() == (expected_units, expected_graph)
            assert [call.args[0] for call in reads.call_args_list] == expected_reads

        shared = repo / "shared.ouro"
        saved = shared.stat()
        shared.write_text('import "extra.ouro";\n', encoding="utf-8")
        os.utime(shared, ns=(saved.st_atime_ns, saved.st_mtime_ns))
        reads.reset_mock()
        units, graph = loop.all_stage_source_units()
        assert units == ["extra.ouro", "shared.ouro", "backend_leaf.ouro", "backend.ouro",
                         "left.ouro", "right.ouro"], units
        assert graph == {
            "backend.ouro": ["extra.ouro", "shared.ouro", "backend_leaf.ouro", "backend.ouro"],
            "left.ouro": ["extra.ouro", "shared.ouro", "left.ouro"],
            "right.ouro": ["extra.ouro", "shared.ouro", "right.ouro"],
        }, graph
        assert [call.args[0] for call in reads.call_args_list] == [
            "backend.ouro", "shared.ouro", "extra.ouro", "backend_leaf.ouro",
            "left.ouro", "right.ouro",
        ]
        shared.write_text(sources["shared.ouro"], encoding="utf-8")
        for text, diagnostic in (
            ('import "shared.ouro";\nimport "right.ouro";\n',
             "FRONTEND_REGEN: FAIL import cycle while collecting right.ouro: right.ouro"),
            ('import "shared.ouro";\nimport "missing.ouro";\n',
             "FRONTEND_REGEN: FAIL missing missing.ouro"),
        ):
            (repo / "right.ouro").write_text(text, encoding="utf-8")
            try:
                loop.all_stage_source_units()
            except SystemExit as exc:
                assert exc.code == diagnostic, exc.code
            else:
                raise AssertionError(f"stage source collection accepted {diagnostic}")


def test_stage_loop_backend_output_receipt(tmp: Path) -> None:
    import stage_loop as loop

    work = tmp / "backend-output-receipt"
    work.mkdir()
    fake_ouro1 = work / "fake-ouro1.py"
    fake_cc = work / "fake-cc.py"
    ouro_log = work / "ouro1.log"
    write_fake_ouro1(fake_ouro1)
    write_fake_cc(fake_cc, fake_ouro1)
    env = {
        "CC": str(fake_cc),
        "FAKE_CC_LOG": str(work / "cc.log"),
        "FAKE_OURO1_LOG": str(ouro_log),
        "OURO_CCACHE": "disabled",
        "OURO_CACHE": "1",
        "OURO_BUILD_DIR": str(work / "build"),
        "OURO_C_BUILD_DIR": str(work / "c"),
        "OURO_CACHE_DIR": str(work / "cache"),
    }
    with patch.dict(os.environ, env):
        cfg = loop.build_config(argparse.Namespace(promote=False))
        stage_dir = cfg.work / "stage1"
        stage_dir.mkdir(parents=True)
        out = stage_dir / "backend_u.c"
        err = stage_dir / "emit.err"

        first = loop.emit_backend(fake_ouro1, out, err, cfg, 1)
        assert first["cache"] == "miss" and count_lines(ouro_log) == 1, first
        expected = out.read_bytes()
        cache_file = cfg.cache_root / "gen/backend" / f"backend_{first['key']}.c"
        metadata = cache_file.with_suffix(".json")
        receipt = json.loads(metadata.read_text(encoding="utf-8"))
        assert receipt["input_key"] == first["key"]
        assert receipt["output_sha256"] == loop.sha256_file(out)
        assert loop.freg.cached_output_matches(cache_file, first["key"])

        err.write_bytes(b"previous diagnostics\n")
        warm = loop.emit_backend(fake_ouro1, out, err, cfg, 1)
        assert warm["cache"] == "hit" and warm["key"] == first["key"], warm
        assert count_lines(ouro_log) == 1 and out.read_bytes() == expected
        assert err.read_bytes() == b""

        for damage in (
            "missing-metadata", "partial-metadata", "malformed-metadata", "wrong-kind",
            "wrong-key", "wrong-hash", "corrupt-output", "missing-output",
        ):
            receipt = json.loads(metadata.read_text(encoding="utf-8"))
            if damage == "missing-metadata":
                metadata.unlink()
            elif damage == "partial-metadata":
                receipt.pop("output_sha256")
                metadata.write_text(json.dumps(receipt), encoding="utf-8")
            elif damage == "malformed-metadata":
                metadata.write_text('{"kind":', encoding="utf-8")
            elif damage == "wrong-kind":
                receipt["kind"] = "stale"
                metadata.write_text(json.dumps(receipt), encoding="utf-8")
            elif damage == "wrong-key":
                receipt["input_key"] = "stale"
                metadata.write_text(json.dumps(receipt), encoding="utf-8")
            elif damage == "wrong-hash":
                receipt["output_sha256"] = "0" * 64
                metadata.write_text(json.dumps(receipt), encoding="utf-8")
            elif damage == "corrupt-output":
                cache_file.write_bytes(b"nonempty corrupted generated C\n")
            else:
                cache_file.unlink()
            assert not loop.freg.cached_output_matches(cache_file, first["key"]), damage
            before = count_lines(ouro_log)
            repaired = loop.emit_backend(fake_ouro1, out, err, cfg, 1)
            assert repaired["cache"] == "miss" and repaired["key"] == first["key"], (damage, repaired)
            assert count_lines(ouro_log) == before + 1, damage
            assert out.read_bytes() == expected and cache_file.read_bytes() == expected, damage
            assert loop.freg.cached_output_matches(cache_file, first["key"]), damage

        with patch.dict(os.environ, {"OURO_CACHE": "0"}):
            cfg_off = loop.build_config(argparse.Namespace(promote=False))
            assert cfg_off.cache_enabled is False
            for attempt in range(2):
                if attempt:
                    cache_file.write_bytes(b"cache-off must ignore corrupted generated C\n")
                cached_bytes = cache_file.read_bytes()
                metadata_bytes = metadata.read_bytes()
                before = count_lines(ouro_log)
                cold = loop.emit_backend(fake_ouro1, out, err, cfg_off, 1)
                assert cold["cache"] == "miss" and cold["key"] == first["key"], cold
                assert count_lines(ouro_log) == before + 1 and out.read_bytes() == expected
                assert cache_file.read_bytes() == cached_bytes
                assert metadata.read_bytes() == metadata_bytes


def test_stage_loop_input_fast_path(tmp: Path) -> None:
    repo = tmp / "stage_repo"
    copy_repo(repo)
    cdir = repo / "_build/c"
    cdir.mkdir(parents=True)
    fake_ouro1 = tmp / "stage-fake-ouro1.py"
    fake_cc = tmp / "fake-cc.py"
    ouro_log = tmp / "stage_ouro1.log"
    cc_log = tmp / "stage_cc.log"
    write_fake_ouro1(fake_ouro1)
    shutil.copyfile(fake_ouro1, cdir / "ouro1")
    (cdir / "ouro1").chmod((cdir / "ouro1").stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    write_fake_cc(fake_cc, fake_ouro1)
    env = os.environ.copy()
    env.update(
        {
            "CC": str(fake_cc),
            "FAKE_OURO1_LOG": str(ouro_log),
            "FAKE_CC_LOG": str(cc_log),
            "OURO_C_BUILD_DIR": str(cdir),
            "OURO_BUILD_DIR": str(repo / "_build"),
            "OURO_CACHE_DIR": str(repo / "_cache_test"),
            "OURO_CACHE": "1",
            "OURO_STAGE_MAX": "2",
            "OURO_JOBS": "1",
            "OURO_FRONTEND_JOBS": "1",
            "PYTHON": sys.executable,
        }
    )
    first = run(repo, ["sh", "scripts/stage_loop.sh"], env)
    assert "PASS fixpoint at stage2" in first.stdout, first.stdout
    ouro_calls = count_lines(ouro_log)
    cc_compile, cc_link = counts(cc_log)
    assert ouro_calls > 0 and cc_compile >= 10 and cc_link == 2, first.stdout

    second = run(repo, ["sh", "scripts/stage_loop.sh"], env)
    assert "FAST_PATH input unchanged" in second.stdout, second.stdout
    assert count_lines(ouro_log) == ouro_calls, "stage-loop fast path must not invoke ouro1"
    assert counts(cc_log) == (cc_compile, cc_link), "stage-loop fast path must not invoke fake cc"
    result = json.loads((repo / "_build/stage_loop/result.json").read_text(encoding="utf-8"))
    assert result["fast_path"] is True and result["pass"] is True

    cache_off_env = dict(env)
    cache_off_env["OURO_CACHE"] = "0"
    expected_artifacts = {
        (stage, name): (repo / f"_build/stage_loop/stage{stage}" / name).read_bytes()
        for stage in (1, 2) for name in ("driver_u.c", "backend_u.c")
    }
    for _attempt in range(2):
        before_ouro = count_lines(ouro_log)
        before_compile, before_link = counts(cc_log)
        cold_run = run(repo, ["sh", "scripts/stage_loop.sh"], cache_off_env)
        assert "FAST_PATH" not in cold_run.stdout and "reuse stage" not in cold_run.stdout, cold_run.stdout
        cold = json.loads((repo / "_build/stage_loop/result.json").read_text(encoding="utf-8"))
        assert cold["pass"] is True and cold["fast_path"] is False and cold["stages"] == 2, cold
        assert cold["frontend_eq"] is True and cold["backend_eq"] is True, cold
        stages = cold["stage_reports"]
        assert len(stages) == 2 and all(stage["reused"] is False for stage in stages), cold
        for stage in stages:
            assert stage["backend"]["cache"] == "miss", stage
            assert stage["frontend"]["summary"]["tu_misses"] == EXPECTED_FRONTEND_TUS, stage
            cbuild = stage["c_build"]
            assert cbuild["compile_hits"] == 0 and cbuild["compile_misses"] == len(cbuild["sources"]), cbuild
            assert cbuild["link_cache"] == "miss", cbuild
        cold_compiles = sum(len(stage["c_build"]["sources"]) for stage in stages)
        assert counts(cc_log) == (before_compile + cold_compiles, before_link + 2), cold
        assert count_lines(ouro_log) == before_ouro + 2 * (EXPECTED_FRONTEND_TUS + 1), cold
        for (stage, name), expected in expected_artifacts.items():
            assert (repo / f"_build/stage_loop/stage{stage}" / name).read_bytes() == expected


def test_strict_packer(tmp: Path) -> None:
    run(ROOT, [sys.executable, "scripts/pack_frontend.py", "--selftest"], os.environ.copy())
    source = tmp / "pack-input.c"
    output = tmp / "pack-output.c"
    header = "int ouro_export_count_x(void){return 0;}\n"
    unit = "ouro_ctor(0,0,0)"
    triple = "ouro_ctor(0,3,(ouro_v *[]){" + unit + ",x,y})"
    cases = (
        ("nested-type", "lx", "ouro_ctor(1,1,(ouro_v *[]){ouro_ctor(0,1,(ouro_v *[]){ouro_err(5)})})", 3),
        ("dummy-triple", "lx", triple, 3),
        ("parser-unit", "pa", triple, 0),
        ("clean", "lx", "ouro_ctor(1,2,(ouro_v *[]){x,y})", 0),
        ("malformed-prefix", "lx", ")ouro_ctor(0,1,(ouro_v *[]){ouro_err(5)})", 3),
    )
    for name, suffix, body, status in cases:
        source.write_text(header + body + "\n", encoding="utf-8")
        output.write_bytes(b"previous output\n")
        result = subprocess.run(
            [sys.executable, "scripts/pack_frontend.py", "--strict", "-o", str(output),
             f"{suffix}:{source}"],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        assert result.returncode == status, (name, result)
        if status:
            assert "STRICT FAIL leftover_type_apps=" in result.stderr, (name, result)
            assert output.read_bytes() == b"previous output\n", name
        else:
            assert not result.stderr and "mode=strict" in result.stdout, (name, result)
            assert body in output.read_text(encoding="utf-8"), name
    output.unlink()
    rejected = subprocess.run(
        [sys.executable, "scripts/pack_frontend.py", "--strict", "-o", str(output),
         f"lx:{source}"],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    assert rejected.returncode == 3 and not output.exists(), rejected


def main() -> int:
    test_native_stack_limits()
    with tempfile.TemporaryDirectory(prefix="ouro-stage-loop-suite-") as d:
        tmp = Path(d)
        test_stage_source_unit_preparation(tmp)
        test_strict_packer(tmp)
        test_frontend_final_and_tu_cache(tmp)
        test_stage_loop_backend_output_receipt(tmp)
        test_stage_loop_input_fast_path(tmp)
    print("STAGE_LOOP_FRONTEND_REGEN_SUITE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
