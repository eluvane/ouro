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
from pathlib import Path

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


def main() -> int:
    test_native_stack_limits()
    with tempfile.TemporaryDirectory(prefix="ouro-stage-loop-suite-") as d:
        tmp = Path(d)
        test_frontend_final_and_tu_cache(tmp)
        test_stage_loop_input_fast_path(tmp)
    print("STAGE_LOOP_FRONTEND_REGEN_SUITE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
