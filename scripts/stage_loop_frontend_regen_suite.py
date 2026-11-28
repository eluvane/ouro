#!/usr/bin/env python3
"""Fast regression checks for frontend regeneration and stage-loop caching.

Uses fake ouro1/cc tools so it locks build-graph behavior without requiring a
multi-minute real frontend regeneration.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import frontend_regen
import pack_frontend

from build_cache_config_suite import counts

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_FRONTEND_TUS = len(frontend_regen.FRONTEND_TUS)


def copy_repo(dst: Path) -> None:
    ignore = shutil.ignore_patterns("_build", "_cache", ".git", "*.pyc", "__pycache__")
    shutil.copytree(ROOT, dst, ignore=ignore)
    for dependency in ("runtime/frontend_link.c", "scripts/compact_source.py"):
        assert (dst / dependency).read_bytes() == (ROOT / dependency).read_bytes(), dependency


def write_fake_ouro1(path: Path) -> None:
    # Python, not a shebang-sh file named .py: Windows CreateProcess and
    # frontend_regen.ouro1_cmd both run *.py with the host interpreter.
    path.write_text(
        r'''#!/usr/bin/env python3
import os, sys
sys.path.insert(0, "scripts")
import pack_frontend as packer
from frontend_lower_lookup_test import append_helpers, elem_helpers
from scoped_host_export_routes import PACKED_FRONTEND_EXPORT_ROUTES
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
units = [args[i + 1].replace("\\", "/") for i, token in enumerate(args[:-1]) if token == "--unit"]
definitions = []
if "compiler/module_registry_base.ouro" in units:
    definitions.extend((("module_members", 7), ("module_owned_exports", 2),
                        ("module_shadow_exports", 2), ("module_unique_exports", 1)))
if "compiler/module_registry.ouro" in units:
    definitions.append(("module_maps_for", 9))
if "compiler/module_names.ouro" in units:
    definitions.extend((("module_rewrite_decls_with_opens_pure", 10), ("module_rewrite_decl_pure", 10)))
if "compiler/module_registry.ouro" in units:
    definitions.extend((("module_scope_maps", 4), ("module_bare_ctors", 5)))
if "compiler/module_names_base.ouro" in units:
    definitions.append(("module_invalid_maps", 3))
if "compiler/module_registry.ouro" in units:
    definitions.extend((("module_rewrite_unit_pure", 7),
                        ("module_maps_for_cached_pure", 9), ("module_rewrite_unit_cached_pure", 7)))
if packer.SOURCE_NAME_COMPARE_OWNER in units:
    definitions.append(("source_name_compare", 2))
if "compiler/module_names_base.ouro" in units:
    definitions.extend((("lookup", 3), ("eqNat", 2), ("module_lookup", 0)))
if mod == "_lo":
    if root != "compiler/lower.ouro" or any(unit not in units for unit in (
            "compiler/lower_env.ouro", "compiler/pipeline_abi.ouro")):
        raise SystemExit("fake ouro1: invalid lower ctor source closure")
    definitions.append(("lookup_ctor", 2))
if packer.LOWER_LOCAL_LOOKUP_OWNER in units:
    definitions.append(("lookup_local", 2))
value_routes = (*packer.PRELUDE_ARITHMETIC_ROUTES, packer.PRELUDE_LIST_LENGTH_ROUTE[:2],
                packer.PRELUDE_LIST_APPEND_ROUTE[:2],
                ("elem", packer.ELEM_OWNER), ("orb", packer.ELEM_ORB_OWNER))
value_owners = dict(value_routes)
value_owners["source_name_compare"] = packer.SOURCE_NAME_COMPARE_OWNER
value_owners["lookup_local"] = packer.LOWER_LOCAL_LOOKUP_OWNER
for name, owner in value_routes:
    if owner in units and not any(existing == name for existing, _arity in definitions):
        definitions.append((name, packer.PRELUDE_LIST_LENGTH_ROUTE[2] if name == "length"
                            else packer.ELEM_VALUE_ARITY if name == "elem" else 2))
scoped = mod in {"_lx", "_co", "_pi", "_pr", "_pl"}
if scoped:
    for suffix, _alias, name, owners in PACKED_FRONTEND_EXPORT_ROUTES:
        if suffix == mod:
            owner, = (path for path in owners if path in units)
            value_owners[name] = owner
            if not any(existing == name for existing, _arity in definitions):
                definitions.append((name, 1))
if definitions:
    print('#include "ouro_rt.h"')
    names, values = [], []
    gids = {name: 900 + index for index, (name, _arity) in enumerate(definitions)}
    for index, (name, arity) in enumerate(definitions):
        gid = 900 + index
        if name == "append":
            print(append_helpers(gid), end="")
        elif name == "elem":
            print(elem_helpers(gid, gids["orb"]), end="")
        else:
            for step in reversed(range(arity)):
                suffix = "0_" * step + f"{gid}_"
                result = f"ouro_clos(ouro_f0_{suffix},env)" if step + 1 < arity else "arg"
                print(f"static ouro_v *ouro_f{suffix}(ouro_env *env0,ouro_v *arg){{"
                      f"ouro_env *env=ouro_cons(arg,env0);(void)env;return {result};}}")
        print(f"static ouro_v *ouro_c{gid};")
        initializer = (f"ouro_app(ouro_g{gids['lookup']}(),ouro_g{gids['eqNat']}())"
                       if name == "module_lookup" else f"ouro_fix(ouro_f{gid}_,env)"
                       if name in ("append", "source_name_compare") else f"ouro_clos(ouro_f{gid}_,env)")
        print(f"static ouro_v *ouro_g{gid}(void){{ouro_env *env=0;(void)env;"
              f"if(ouro_c{gid}==0){{ouro_static_begin();"
              f"ouro_c{gid}={initializer};"
              f"ouro_static_end();}}return ouro_c{gid};}}")
        owner = value_owners.get(name)
        label = f"_ouro_m_{units.index(owner)}_{name}" if scoped and owner and owner != units[-1] else name
        names.append(f'case {index}: return "{label}";')
        values.append(f"case {index}: return ouro_g{gid}();")
    print(f"int ouro_export_count{mod}(void){{return {len(definitions)};}}")
    print(f"const char *ouro_export_name{mod}(int i){{switch(i){{" + "".join(names) + '}return "";}')
    print(f"ouro_v *ouro_export_value{mod}(int i){{switch(i){{" + "".join(values) + "}return 0;}")
    raise SystemExit(0)
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
    parallel = list(common)
    parallel[parallel.index("--out") + 1] = "_build/test_driver_parallel.c"
    parallel[parallel.index("--work") + 1] = "_build/test_fe_parallel"
    parallel[parallel.index("--jobs") + 1] = "2"
    parallel.append("--no-cache")
    parallel_env = {**env, "FAKE_OURO1_LOG": str(tmp / "parallel-ouro1.log")}
    parallel_result = run(repo, parallel, parallel_env)
    assert f"tu_misses={EXPECTED_FRONTEND_TUS}" in parallel_result.stdout, parallel_result.stdout
    assert (repo / "_build/test_driver_parallel.c").read_bytes() == expected
    parallel_report = json.loads((repo / "_build/test_fe_parallel/frontend-regeneration.json").read_text())
    assert [row["tag"] for row in parallel_report["units"]] == [spec[0] for spec in frontend_regen.FRONTEND_TUS]
    for index, arity in enumerate((7, 2, 2, 1)):
        gid = 900 + index
        assignment = f"ouro_pl_c{gid}=ouro_wrap_module_pure_scope(ouro_clos(ouro_pl_f{gid}_,env),{arity});"
        assert assignment.encode() in expected, "split pipeline scope was not packed"
    for gid, wrapper in ((904, "ouro_wrap_module_maps_for_scope"),
                         (905, "ouro_wrap_module_rewrite_decls_scope"),
                         (906, "ouro_wrap_module_rewrite_decls_scope"),
                         (907, "ouro_wrap_module_scope_maps_scope"),
                         (908, "ouro_wrap_module_bare_ctors_scope"),
                         (909, "ouro_wrap_module_invalid_maps_scope")):
        assignment = f"ouro_pl_c{gid}={wrapper}(ouro_clos(ouro_pl_f{gid}_,env));"
        assert assignment.encode() in expected, "split prefix scope was not packed"
    assignment = "ouro_pl_c910=ouro_wrap_module_pure_scope(ouro_clos(ouro_pl_f910_,env),7);"
    assert assignment.encode() in expected, "split module rewrite unit scope was not packed"
    for gid, wrapper in ((911, "ouro_wrap_module_maps_for_scope"),
                         (912, "ouro_wrap_module_pure_scope")):
        raw = f"ouro_clos(ouro_pl_f{gid}_,env)"
        wrapped = f"{wrapper}({raw},7)" if gid == 912 else f"{wrapper}({raw})"
        assert f"ouro_pl_c{gid}={wrapped};".encode() in expected, "cached module scope was not packed"
    lookup = "ouro_clos(ouro_lo_f900_,env)"
    if frontend_regen.lower_ctor_lookup_capability(
            (repo / "runtime/frontend_link.c").read_text(encoding="utf-8")):
        lookup = f"ouro_wrap_lower_ctor_lookup({lookup})"
    assert f"ouro_lo_c900={lookup};".encode() in expected, "split lower ctor lookup was not packed"
    local_lookup = "ouro_clos(ouro_lo_f901_,env)"
    if frontend_regen.module_lookup_capability(
            (repo / "runtime/frontend_link.c").read_text(encoding="utf-8")):
        local_lookup = f"ouro_wrap_module_lookup({local_lookup})"
    assert f"ouro_lo_c901={local_lookup};".encode() in expected, "split lower local lookup was not packed"
    second = run(repo, common, env)
    assert "final cache-hit" in second.stdout, second.stdout
    assert output.read_bytes() == expected
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


    packer = repo / "scripts/pack_frontend.py"
    saved = packer.stat()
    packer.write_text(packer.read_text(encoding="utf-8") + "\n# invalidate pure-scope installer\n", encoding="utf-8")
    os.utime(packer, ns=(saved.st_atime_ns, saved.st_mtime_ns))
    before = count_lines(log)
    run(repo, common, env)
    rebuilt = current_report()
    assert rebuilt["summary"]["tu_misses"] == EXPECTED_FRONTEND_TUS
    assert count_lines(log) == before + EXPECTED_FRONTEND_TUS
    assert output.read_bytes() == expected


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


def test_stage_loop_seed_staging(tmp: Path) -> None:
    import stage_loop

    stage0_dir = tmp / "compiler/stage0"
    stage0_dir.mkdir(parents=True)
    cdir = tmp / "c"
    cdir.mkdir()
    seed = cdir / "ouro1"
    write_fake_ouro1(seed)
    work = tmp / "stage_loop"
    stage0_seed = work / "ouro1_stage0"
    staged = {stage0_seed: seed}
    for name in ("driver_u.c", "backend_u.c"):
        source = stage0_dir / name
        source.write_text(f"/* {name} */\n", encoding="utf-8")
        staged[work / f"stage0_{name}"] = source
    cfg = stage_loop.StageConfig(
        promote=False, max_stages=2, fuel="16000", pack_strict="1", cc="fixture-cc",
        c_build_dir=cdir, build_dir=tmp, cache_root=tmp / "cache", cache_enabled=False,
        work=work, result=work / "result.json", status_pub=work / "status.json", env={},
        build_cfg=stage_loop.OB.ResolvedConfig({"opt_level": "O0", "reproducible": False}, {}),
    )

    def emit_backend(prev, out, _err, _cfg, stage):
        if stage == 1:
            assert prev == stage0_seed and prev.read_bytes() == seed.read_bytes()
        shutil.copyfile(stage0_dir / out.name, out)
        return {}

    def emit_frontend(_prev, out, _err, _stage, _cfg):
        shutil.copyfile(stage0_dir / out.name, out)
        return {}

    def build(_frontend, _backend, out, _stage, _cfg):
        out.write_bytes(b"stage binary")
        return {}

    samefile = os.path.samefile
    copy_atomic = stage_loop.copy_atomic

    def partial_symlink(dest, source):
        if source.name == "backend_u.c":
            raise OSError("backend symlink unavailable")
        dest.write_bytes(source.read_bytes())

    def samefile_with_driver_link(left, right):
        if left == stage0_dir / "driver_u.c" and right == work / "stage0_driver_u.c" and right.is_file():
            return True
        return samefile(left, right)

    def copy_changed_seed(source, dest):
        source.write_bytes(source.read_bytes() + b"\n# updated seed\n")
        copy_atomic(source, dest)

    log = StringIO()
    with (
        redirect_stdout(log),
        redirect_stderr(log),
        patch.dict(os.environ, {"OURO_STAGE_FAST_PATH": "1"}),
        patch.object(stage_loop, "ROOT", tmp),
        patch.object(stage_loop.freg, "capture_unit_inputs", return_value=({}, {})),
        patch.object(stage_loop.OB, "compiler_id", return_value="fixture cc"),
        patch.object(Path, "symlink_to", autospec=True, side_effect=partial_symlink),
        patch.object(os.path, "samefile", side_effect=samefile_with_driver_link),
        patch.object(stage_loop, "emit_backend", side_effect=emit_backend),
        patch.object(stage_loop, "emit_frontend", side_effect=emit_frontend),
        patch.object(stage_loop, "build_stage_binary", side_effect=build) as builder,
    ):
        assert stage_loop.run_loop(cfg) == 0
        first = stage_loop.load_json(cfg.result)
        assert first["fixpoint"] is True and first["fast_path"] is False
        assert [call.args[3] for call in builder.call_args_list] == [1, 2]
        for dest, source in staged.items():
            assert dest.read_bytes() == source.read_bytes()
            dest.unlink()

        builder.reset_mock()
        assert stage_loop.run_loop(cfg) == 0
        assert stage_loop.load_json(cfg.result)["fast_path"] is True
        builder.assert_not_called()
        assert all(not dest.exists() and not dest.is_symlink() for dest in staged), staged

        (work / "ouro1_stage2").write_bytes(b"damaged stage binary")
        assert stage_loop.run_loop(cfg) == 0
        repaired = stage_loop.load_json(cfg.result)
        assert repaired["fast_path"] is False and repaired["artifacts"] == first["artifacts"]
        assert [call.args[3] for call in builder.call_args_list] == [2]
        for dest, source in staged.items():
            assert dest.read_bytes() == source.read_bytes()

        shutil.copytree(work / "stage2", work / "stage3")
        shutil.copyfile(work / "ouro1_stage2", work / "ouro1_stage3")
        builder.reset_mock()
        for fields in (
            {"pass": "false"}, {"fixpoint": "false"}, {"stages": "2"},
            {"stages": "bad"}, {"stages": 3}, {"artifacts": []},
        ):
            stage_loop.write_json_atomic(cfg.result, {**first, **fields})
            assert stage_loop.run_loop(cfg) == 0, fields
            assert stage_loop.load_json(cfg.result)["fast_path"] is False, fields
        builder.assert_not_called()

        stamp = work / "stage2/stage.stamp.json"
        valid_stamp = stage_loop.load_json(stamp)
        for fields in ({"stage": 2.0}, {"artifacts": []}):
            stage_loop.write_json_atomic(stamp, {**valid_stamp, **fields})
            cfg.result.unlink()
            builder.reset_mock()
            assert stage_loop.run_loop(cfg) == 0, fields
            assert [call.args[3] for call in builder.call_args_list] == [2], fields

        builder.reset_mock()
        with (
            patch.dict(os.environ, {"OURO_STAGE_FAST_PATH": "0"}),
            patch.object(stage_loop, "copy_atomic", side_effect=copy_changed_seed),
        ):
            assert stage_loop.run_loop(cfg) == 1
        failure = stage_loop.load_json(cfg.result)
        assert failure["pass"] is False and failure["failed_at"] == "stage0_seed"
        builder.assert_not_called()
        assert "STAGE_LOOP: FAIL seed changed while staging" in log.getvalue()


def parser_unit_fixture() -> str:
    parts = []
    for gid, tokens, position in (("2338", "0", "2"), ("2352", "1", "3")):
        parts.extend((
            "static ouro_v *ouro_f0_0_" + gid + "_(ouro_env *env0,ouro_v *arg){"
            "ouro_env *env=ouro_cons(arg,env0);(void)env;"
            "return ouro_ctor(0,3,(ouro_v *[]){ouro_ctor(0,0,0),ouro_get(env," + tokens + "),"
            "ouro_ctor(1,1,(ouro_v *[]){ouro_get(env," + position + ")})});}\n",
            "static ouro_v *ouro_f0_" + gid + "_(ouro_env *env0,ouro_v *arg){"
            "ouro_env *env=ouro_cons(arg,env0);(void)env;"
            "return ouro_clos(ouro_f0_0_" + gid + "_,env);}\n",
            "static ouro_v *ouro_f" + gid + "_(ouro_env *env0,ouro_v *arg){"
            "ouro_env *env=ouro_cons(arg,env0);(void)env;"
            "return ouro_clos(ouro_f0_" + gid + "_,env);}\n",
            "static ouro_v *ouro_c" + gid + ";\n",
            "static ouro_v *ouro_g" + gid + "(void){ouro_env *env=0;(void)env;"
            "if(ouro_c" + gid + "==0){ouro_static_begin();ouro_c" + gid
            + "=ouro_clos(ouro_f" + gid + "_,env);ouro_static_end();}"
            "return ouro_c" + gid + ";}\n",
        ))
    parts.extend((
        "int ouro_export_count_x(void){return 2;}\n",
        'const char *ouro_export_name_x(int i){switch(i){case 0:return "expect_tag";'
        'case 1:return "expect_keyword";default:return "";}}\n',
        "ouro_v *ouro_export_value_x(int i){switch(i){case 0:return ouro_g2338();"
        "case 1:return ouro_g2352();default:return 0;}}\n",
    ))
    return "".join(parts)


def parser_unit_regressions() -> tuple[tuple[str, str, str, int], ...]:
    source = parser_unit_fixture()
    bad_pair = "ouro_ctor(0,3,(ouro_v *[]){ouro_ctor(0,0,0),x,y})"
    extra = "static ouro_v *other(ouro_env *env,ouro_v *arg){return " + bad_pair + ";}\n"
    return (
        ("pl-owned-POk-Unit", "pl", source, 0),
        ("pl-owned-POk-and-bad-pair", "pl", source + extra, 3),
        ("lx-owned-POk", "lx", source, 3),
        ("pl-wrong-capture", "pl", source.replace("ouro_get(env,2)", "ouro_get(env,1)"), 3),
        ("pl-missing-export", "pl", source.replace('"expect_tag"', '"other"'), 3),
        ("pl-duplicate-index", "pl", source.replace('case 1:return "expect_keyword";',
                                                   'case 0:return "expect_keyword";'), 3),
        ("pl-shared-getter", "pl", source.replace("case 1:return ouro_g2352();",
                                                 "case 1:return ouro_g2338();"), 3),
        ("pl-wrong-family", "pl", source.replace("ouro_f0_0_2338_", "ouro_f0_0_23380_"), 3),
        ("pl-missing-getter", "pl", source.replace("static ouro_v *ouro_g2338(void)",
                                                  "static ouro_v *other_getter(void)"), 3),
        ("pl-duplicate-getter-after-table", "pl", source + next(
            line for line in source.splitlines(keepends=True)
            if line.startswith("static ouro_v *ouro_g2338(void)")), 3),
        ("pl-two-candidates", "pl", source + source.splitlines(keepends=True)[0].replace(
            "ouro_f0_0_2338_", "ouro_f9_2338_"), 3),
        ("pl-wrong-getter-result", "pl", source.replace("return ouro_c2338;", "return ouro_c2352;"), 3),
        ("pl-other-capture-pair", "pl", source.replace("ouro_get(env,0)", "ouro_get(env,2)").replace("ouro_get(env,2)})", "ouro_get(env,4)})"), 3),
        ("pl-owned-POk-and-Err5", "pl", source +
         "ouro_ctor(0,1,(ouro_v *[]){ouro_err(5)})\n", 3),
    )


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
        *(("parser-unit-" + suffix, suffix, triple, 0)
          for suffix in ("pa", "pb", "pf")),
        ("pipeline-unowned-unit", "pl", triple, 3),
        *(("parser-type-" + suffix, suffix,
           "ouro_ctor(0,4,(ouro_v *[]){ouro_err(5)," + unit + ",x,y})", 3)
          for suffix in ("pa", "pb", "pf", "pl")),
        *parser_unit_regressions(),
        ("pipeline-poly-type", "pl",
         'const char *ouro_export_name_x(int i){switch(i){case 0:return "length";default:return "";}}\n'
         "ouro_v *ouro_export_value_x(int i){switch(i){case 0:return ouro_g1();default:return 0;}}\n"
         "ouro_app(ouro_app(ouro_g1(),ouro_err(5)),x)", 3),
        ("clean", "lx", "ouro_ctor(1,2,(ouro_v *[]){x,y})", 0),
        ("malformed-prefix", "lx", ")ouro_ctor(0,1,(ouro_v *[]){ouro_err(5)})", 3),
    )
    for name, suffix, body, status in cases:
        prefix = "" if "ouro_export_count_x" in body else header
        source.write_text(prefix + body + "\n", encoding="utf-8")
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
            assert pack_frontend.prefix_blob(body, suffix) in output.read_text(encoding="utf-8"), name
    output.unlink()
    rejected = subprocess.run(
        [sys.executable, "scripts/pack_frontend.py", "--strict", "-o", str(output),
         f"lx:{source}"],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    assert rejected.returncode == 3 and not output.exists(), rejected

    scoped = parser_unit_fixture().replace('"expect_', '"_ouro_m_17_expect_')
    command = [sys.executable, "scripts/pack_frontend.py", "--strict", "-o", str(output), f"pl:{source}"]
    mixed = scoped.replace('"_ouro_m_17_expect_tag"', '"expect_tag"')
    bad_pair = "ouro_ctor(0,3,(ouro_v *[]){ouro_ctor(0,0,0),x,y})"
    for body, ordinal, status in ((scoped, "17", 0), (scoped, "18", 3), (scoped, None, 3),
                                  (mixed, "17", 3), (scoped + bad_pair, "17", 3)):
        source.write_text(body, encoding="utf-8")
        output.write_bytes(b"previous output\n")
        options = ["--parser-min-ordinal", ordinal] if ordinal is not None else []
        result = subprocess.run(command + options, cwd=ROOT, capture_output=True, text=True, check=False)
        assert result.returncode == status, result
        if status:
            assert "STRICT FAIL leftover_type_apps=" in result.stderr, result
            assert output.read_bytes() == b"previous output\n"
        else:
            assert pack_frontend.prefix_blob(scoped, "pl") in output.read_text(encoding="utf-8")


def test_multi_piece_packer_output(tmp: Path) -> None:
    first = tmp / "first.c"
    second = tmp / "second.c"
    output = tmp / "multi-pack.c"
    first.write_bytes(b"int ouro_export_count_lx(void){return 0;}\r\n"
                      b"static ouro_v *ouro_g1(void){return 0;}\r\n/* \xc3\xa9\xff */\r\n")
    second.write_bytes(b"int ouro_export_count_pr(void){return 0;}\r"
                       b"static ouro_v *ouro_g2(void){return 0;}")
    expected = (
        b"/* Generated frontend pack: split O8 cones, prefixed statics.\n"
        b"   Do not hand-edit. Regenerate with scripts/emit_frontend.sh. */\n"
        b"\n/* ---- frontend TU module=lx ---- */\n"
        b"int ouro_export_count_lx(void){return 0;}\n"
        b"static ouro_v *ouro_lx_g1(void){return 0;}\n/* \xc3\xa9\xff */\n\n"
        b"\n/* ---- frontend TU module=pr ---- */\n"
        b"int ouro_export_count_pr(void){return 0;}\n"
        b"static ouro_v *ouro_pr_g2(void){return 0;}\n"
    ).replace(b"\n", os.linesep.encode("ascii"))
    command = [sys.executable, "scripts/pack_frontend.py", "--strict", "-o", str(output),
               f"lx:{first}", f"pr:{second}"]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0 and result.stderr == "", result
    assert output.read_bytes() == expected

    first.write_bytes(first.read_bytes() + b"ouro_ctor(0,1,(ouro_v *[]){ouro_err(5)})\n")
    rejected = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    assert rejected.returncode == 3 and "STRICT FAIL leftover_type_apps=1" in rejected.stderr, rejected
    assert output.read_bytes() == expected

    second.write_bytes(b"/* no export table */\n")
    invalid = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    assert invalid.returncode == 2 and invalid.stderr == f"pack_frontend: {second} has no export table\n", invalid
    assert output.read_bytes() == expected


def main() -> int:
    test_native_stack_limits()
    with tempfile.TemporaryDirectory(prefix="ouro-stage-loop-suite-") as d:
        tmp = Path(d)
        test_strict_packer(tmp)
        test_multi_piece_packer_output(tmp)
        test_frontend_final_and_tu_cache(tmp)
        test_stage_loop_input_fast_path(tmp)
        test_stage_loop_seed_staging(tmp / "stage_seed_fixture")
    print("STAGE_LOOP_FRONTEND_REGEN_SUITE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
