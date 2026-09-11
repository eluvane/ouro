#!/usr/bin/env python3
"""Regression tests for Ouro build cache invalidation and config precedence.

Runs against a temporary copy with a fake C compiler so the suite is fast and
checks build graph behavior rather than host compiler speed.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import ouro_build as build_driver

ROOT = Path(__file__).resolve().parents[1]


def copy_repo(dst: Path) -> None:
    ignore = shutil.ignore_patterns("_build", "_cache", ".git", "*.pyc", "__pycache__")
    shutil.copytree(ROOT, dst, ignore=ignore)





def shrink_stage0_generated_c(repo: Path) -> None:
    """Keep this generic cache suite focused on invalidation, not generated-C size."""
    stage0 = repo / "compiler/stage0"
    (stage0 / "driver_u.c").write_text(
        """#include \"ouro_rt.h\"\n/* ---- frontend TU module=lx ---- */\nint ouro_fake_frontend_lx(void){return 1;}\n/* ---- frontend TU module=pa ---- */\nint ouro_fake_frontend_pa(void){return 2;}\n""",
        encoding="utf-8",
    )
    (stage0 / "backend_u.c").write_text(
        """#include \"ouro_rt.h\"\nstatic ouro_v *ouro_g1(void);\nstatic ouro_v *ouro_g2(void);\nstatic ouro_v *ouro_g1(void){return ouro_mk_unit();}\nstatic ouro_v *ouro_g2(void){return ouro_g1();}\nint ouro_export_count_be(void){return 0;}\nconst char *ouro_export_name_be(int i){(void)i; return \"\";}\nouro_v *ouro_export_value_be(int i){(void)i; return ouro_g2();}\n""",
        encoding="utf-8",
    )

def write_fake_cc(path: Path) -> None:
    path.write_text(
        r'''#!/usr/bin/env python3
import hashlib, os, re, stat, sys
from pathlib import Path

log = Path(os.environ["FAKE_CC_LOG"])
args = sys.argv[1:]
if "--version" in args:
    print("fake-cc 1.0")
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
    raise SystemExit("fake-cc missing -o")
outp = Path(out)
outp.parent.mkdir(parents=True, exist_ok=True)

if "-c" in args:
    src = Path(args[args.index("-c") + 1])
    mf = arg_after("-MF")
    # Keep this fake compiler IO-cheap: the suite validates Ouro's object-cache
    # dependency behavior, so object identity only needs to move when source/deps
    # move.  Reading multi-megabyte generated shards here makes the regression
    # suite measure Python file IO instead of cache correctness.
    with src.open("r", encoding="utf-8", errors="replace") as sf:
        sample = sf.read(65536)
    deps = [src]
    for inc in re.findall(r'#\s*include\s+"([^"]+)"', sample):
        p = src.parent / inc
        if not p.exists():
            p = Path.cwd() / inc
        if not p.exists():
            p = Path.cwd() / "runtime" / inc
        if p.exists():
            deps.append(p)
    h = hashlib.sha256()
    for dep in deps:
        st = dep.stat()
        h.update(str(dep).encode())
        h.update(str(st.st_size).encode())
        h.update(str(st.st_mtime_ns).encode())
    outp.write_text("OBJ " + h.hexdigest() + "\n", encoding="utf-8")
    if mf:
        dep_line = str(outp) + ": " + " ".join(str(d) for d in deps) + "\n"
        # Also write -MP-style phony entries to guard parser behavior.
        dep_line += "\n".join(str(d) + ":" for d in deps[1:]) + "\n"
        Path(mf).write_text(dep_line, encoding="utf-8")
    with log.open("a", encoding="utf-8") as f:
        f.write("COMPILE " + str(src) + "\n")
    sys.exit(0)

payload = []
for a in args:
    p = Path(a)
    if p.suffix == ".o" and p.exists():
        payload.append(p.read_text(encoding="utf-8", errors="replace"))
outp.write_text("#!/bin/sh\n# fake linked executable\nexit 0\n" + "\n".join(payload), encoding="utf-8")
outp.chmod(outp.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
with log.open("a", encoding="utf-8") as f:
    f.write("LINK " + str(outp) + "\n")
''',
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def isolated_env() -> dict[str, str]:
    env = os.environ.copy()
    # This suite runs against temporary repository copies.  CI-level Ouro path
    # variables point at the outer checkout and must not leak into subprocesses
    # that are meant to prove config precedence inside the temp tree.
    for key in (
        "OURO_ROOT",
        "OURO_BUILD_DIR",
        "OURO_C_BUILD_DIR",
        "OURO_CACHE_DIR",
        "OURO_CI_GATE_NAME",
        "OURO_CI_GATE_OUT",
    ):
        env.pop(key, None)
    return env


def run(repo: Path, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "scripts/ouro_build.py", *args]
    capture = bool(args and args[0] == "config")
    return subprocess.run(
        cmd,
        cwd=repo,
        env=env,
        text=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.STDOUT if capture else subprocess.DEVNULL,
        check=True,
    )


def counts(log: Path) -> tuple[int, int]:
    text = log.read_text(encoding="utf-8") if log.exists() else ""
    return text.count("COMPILE "), text.count("LINK ")


def run_c_graph(repo: Path, options: list[str], env: dict[str, str]) -> None:
    # These fake-C fixtures exercise object/depfile invalidation. Compiler
    # acceptance and publication have separate bootstrap contract tests.
    source = ("import argparse, sys; sys.path.insert(0, 'scripts'); import ouro_build as build; "
              "parser = argparse.ArgumentParser(); build.add_common(parser); "
              "build.build_c(build.load_config(parser.parse_args()))")
    subprocess.run([sys.executable, "-B", "-c", source, *options], cwd=repo, env=env,
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, check=True)


def test_incremental_invalidation(tmp: Path) -> None:
    repo = tmp / "repo"
    copy_repo(repo)
    shrink_stage0_generated_c(repo)
    fakecc = tmp / "fake-cc.py"
    log = tmp / "fake-cc.log"
    write_fake_cc(fakecc)
    env = isolated_env()
    env.update({
        "CC": str(fakecc),
        "FAKE_CC_LOG": str(log),
        "OURO_CCACHE": "disabled",
        "OURO_CACHE": "0",
    })
    common = ["--build-dir", "_build_test", "--c-build-dir", "_build_test/c", "--cache-dir", "_cache_test", "--jobs", "1", "--verbosity", "quiet"]

    run_c_graph(repo, common, env)
    cold_compile, cold_link = counts(log)
    assert cold_compile >= 5, cold_compile
    assert cold_link == 1, cold_link

    run_c_graph(repo, common, env)
    assert counts(log) == (cold_compile, cold_link), "no-change build must not compile/link"

    header = repo / "runtime/ouro_rt.h"
    header.write_text(header.read_text(encoding="utf-8") + "\n/* invalidate header */\n", encoding="utf-8")
    run_c_graph(repo, common, env)
    after_header = counts(log)
    assert after_header[0] > cold_compile, "header change must recompile dependents"
    assert after_header[1] > cold_link, "header change must relink affected executable"
    assert after_header[0] - cold_compile < cold_compile, "header change must not rebuild every TU"

    source = repo / "runtime/bootstrap.c"
    source.write_text(source.read_text(encoding="utf-8") + "\n/* invalidate one c source */\n", encoding="utf-8")
    before_source = counts(log)
    run_c_graph(repo, common, env)
    after_source = counts(log)
    assert after_source[0] - before_source[0] == 1, after_source
    assert after_source[1] - before_source[1] == 1, after_source


def test_config_precedence(tmp: Path) -> None:
    repo = tmp / "repo_cfg"
    copy_repo(repo)
    (repo / "Ouro.seal").write_text(
        '''seal 1\n\nbuild {\n  profile = "release"\n  jobs = 1\n  cc = "config-cc"\n  verbosity = "quiet"\n}\n\ncache {\n  enabled = true\n  dir = "config-cache"\n}\n''',
        encoding="utf-8",
    )
    env = isolated_env()
    env.update({"OURO_PROFILE": "dev", "OURO_JOBS": "10", "OURO_CACHE_DIR": "env-cache"})
    result = run(repo, ["config", "show", "--profile", "release", "--cc", "cli-cc"], env)
    data = json.loads(result.stdout)
    assert data["profile"] == {"value": "release", "source": "CLI"}
    assert data["cc"] == {"value": "cli-cc", "source": "CLI"}
    assert data["jobs"]["value"] == 10 and data["jobs"]["source"] == "environment:OURO_JOBS"
    assert data["cache_dir"]["value"] == "env-cache" and data["cache_dir"]["source"] == "environment:OURO_CACHE_DIR"
    assert data["verbosity"]["value"] == "quiet" and data["verbosity"]["source"].startswith("project config:")
    assert not {"dune", "dune_cache"} & data.keys(), "retired toolchain settings must not remain in resolved config"


def test_retired_toolchain_contract(tmp: Path) -> None:
    import argparse
    import bootstrap_compiler
    import ouro_seal

    # A default build must enter the verified current-source bootstrap. This
    # dispatch test must not discover or start an unrelated toolchain.
    config = build_driver.ResolvedConfig({"verbosity": "quiet"}, {})
    with patch.object(build_driver, "load_config", return_value=config), \
         patch.object(bootstrap_compiler, "ensure_current_compiler") as current_stage, \
         patch.object(build_driver, "build_c", side_effect=AssertionError("unverified direct C build")), \
         patch.object(build_driver, "trim_cache") as cache, \
         patch.object(build_driver.shutil, "which", side_effect=AssertionError("unexpected toolchain discovery")):
        build_driver.run_build(argparse.Namespace())
    current_stage.assert_called_once_with(config, build_driver, build_driver.ROOT)
    cache.assert_called_once_with(config)

    for args in (["build", "--c-only"], ["rebuild", "--c-only"],
                 ["build", "--frontend"], ["rebuild", "--frontend"],
                 ["config", "show", "--dune", "disabled"],
                 ["cache", "status", "--dune-cache", "disabled"]):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/ouro_build.py"), *args],
                                cwd=tmp, env=isolated_env(), capture_output=True, text=True, check=False)
        assert result.returncode == 2 and "unrecognized arguments:" in result.stderr, (args, result)

    for block, key in (("build", "dune"), ("cache", "dune"), ("trust", "kernel")):
        source = f'seal 1\n{block} {{\n {key} = "required"\n}}\n'
        try:
            ouro_seal.parse_seal_text(source, tmp / "Ouro.seal")
        except SystemExit as error:
            assert f"unknown {block}.{key}" in str(error), str(error)
        else:
            raise AssertionError(f"retired {block}.{key} silently accepted")
    _, blocks = ouro_seal.parse_seal_text('seal 1\ntrust {\n compiler = "required"\n}\n', tmp / "Ouro.seal")
    assert blocks["trust"]["compiler"] == "required"


def test_destructive_path_policy(tmp: Path) -> None:
    repo = tmp / "repo_safe_paths"
    repo.mkdir()
    cases = [
        ("build_dir", "."),
        ("c_build_dir", ".."),
        ("cache_dir", str(Path.home())),
        ("cache_dir", repo.anchor),
    ]
    previous_root = build_driver.ROOT
    build_driver.ROOT = repo
    try:
        for key, value in cases:
            cfg = build_driver.ResolvedConfig({key: value}, {key: "test"})
            try:
                cfg.delete_path(key)
            except SystemExit as exc:
                assert "refusing unsafe deletion target" in str(exc), (key, value)
            else:
                raise AssertionError((key, value))

        external = tmp / "external-output"
        cfg = build_driver.ResolvedConfig({"build_dir": str(external)}, {"build_dir": "test"})
        assert cfg.delete_path("build_dir") == external.resolve()
    finally:
        build_driver.ROOT = previous_root


def test_seal_parse() -> None:
    import ouro_seal

    ouro_seal.self_check()


def test_native_tool_cache(tmp: Path) -> None:
    repo = tmp / "repo_tools"
    copy_repo(repo)
    fakecc = tmp / "tool-cc.py"
    cc_log = tmp / "tool-cc.log"
    emit_log = tmp / "tool-emit.log"
    write_fake_cc(fakecc)
    compiler = repo / "_build/c/ouro1.py"
    compiler.parent.mkdir(parents=True)
    compiler.write_text('''import hashlib, os, sys
from pathlib import Path
with Path(os.environ["FAKE_EMIT_LOG"]).open("a") as log:
    log.write("emit\\n")
if os.environ.get("FAKE_EMIT_FAIL") == "1":
    raise SystemExit(19)
source = "".join(Path(p).read_text() for p in sys.argv if p.endswith(".ouro"))
print('#include "ouro_rt.h"')
print("/* " + hashlib.sha256(source.encode()).hexdigest() + " */")
print("int main(void) { return 0; }")
''', encoding="utf-8")
    entry = repo / "tool-test.ouro"
    imported = repo / "tool-import.ouro"
    entry.write_text('import "tool-import.ouro";\ndef main : Nat := 1;\n', encoding="utf-8")
    imported.write_text("def value : Nat := 1;\n", encoding="utf-8")
    env = isolated_env()
    env.update(CC=str(fakecc), FAKE_CC_LOG=str(cc_log), FAKE_EMIT_LOG=str(emit_log),
               OURO_CACHE="1", OURO_CCACHE="disabled", OURO_JOBS="1")

    def invoke(output="_build/tool-test", *, options=(), failure=False):
        result = subprocess.run(
            [sys.executable, "scripts/native_tool_build.py", entry.name, output,
             "--compiler", str(compiler), "--verbosity", "quiet", *options],
            cwd=repo, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        assert (result.returncode != 0) == failure, result.stdout
        return result

    invoke()
    baseline = counts(cc_log)
    assert baseline == (4, 1), baseline
    binary = repo / ("_build/tool-test.exe" if os.name == "nt" else "_build/tool-test")
    baseline_bytes = binary.read_bytes()
    baseline_time = binary.stat().st_mtime_ns
    invoke()
    invoke(options=("--check",))
    assert counts(cc_log) == baseline and emit_log.read_text().count("emit") == 1
    assert binary.stat().st_mtime_ns == baseline_time
    architecture = {name: env.pop(name) for name in ("PROCESSOR_ARCHITECTURE", "PROCESSOR_ARCHITEW6432") if name in env}
    invoke()
    assert counts(cc_log) == baseline and emit_log.read_text().count("emit") == 1, "scrubbed host environments must share the same native cache"
    env.update(architecture)
    if os.name == "nt":
        shadow = repo / "_build/tool-test"
        shadow.write_text("#!/bin/sh\nexit 86\n", encoding="utf-8")
        invoke(options=("--check",), failure=True)
        invoke()
        assert not shadow.exists() and binary.is_file(), "a stale host wrapper must not shadow the native exe"
    invoke("_build/another-suite/tool-test")
    assert counts(cc_log) == baseline, "same entry in another suite must reuse the complete tool"

    old_time = imported.stat().st_mtime_ns
    os.utime(imported, ns=(old_time, old_time + 10_000_000_000))
    invoke()
    assert counts(cc_log) == baseline, "checkout timestamps must not invalidate content"
    imported.write_text("def value : Nat := 2;\n", encoding="utf-8")
    os.utime(imported, ns=(old_time, old_time))
    invoke(options=("--check",), failure=True)
    invoke()
    assert counts(cc_log) == (baseline[0] + 1, baseline[1] + 1), "only generated code should recompile"
    assert binary.read_bytes() != baseline_bytes, "changed import must affect the binary"

    before_header = counts(cc_log)
    header = repo / "runtime/ouro_rt.h"
    header.write_text(header.read_text() + "\n/* changed header */\n", encoding="utf-8")
    invoke()
    assert counts(cc_log)[0] > before_header[0] + 1, "runtime header changes must invalidate dependent objects"
    restored = binary.read_bytes()
    binary.write_text("corrupt", encoding="utf-8")
    (repo / "_build/tool-test.sources").write_text("../../outside\n", encoding="utf-8")
    invoke(options=("--check",), failure=True)
    invoke()
    assert binary.read_bytes() == restored
    assert "../../outside" not in (repo / "_build/tool-test.sources").read_text()

    receipt = json.loads((repo / "_build/tool-test.build.json").read_text())
    cache = repo / "_cache/ouro/native-tools" / receipt["key"]
    (cache / "tool.json").write_text("malformed", encoding="utf-8")
    binary.write_text("corrupt again", encoding="utf-8")
    before_emit = emit_log.read_text().count("emit")
    invoke()
    assert emit_log.read_text().count("emit") == before_emit + 1, "malformed cache must rebuild"

    before_seed = counts(cc_log)
    compiler.write_text(compiler.read_text() + "\n# changed seed binary\n", encoding="utf-8")
    invoke()
    assert counts(cc_log) == (before_seed[0] + 1, before_seed[1] + 1), "a changed seed must regenerate the tool"
    before_cc = counts(cc_log)
    fakecc.write_text(fakecc.read_text() + "\n# changed compiler, same version string\n", encoding="utf-8")
    invoke()
    assert counts(cc_log) == (before_cc[0] + 4, before_cc[1] + 1), "compiler content must invalidate common objects too"
    before_flags = counts(cc_log)
    invoke(options=("--opt", "O2"))
    assert counts(cc_log) == (before_flags[0] + 4, before_flags[1] + 1), "flags must invalidate the installed binary"
    invoke(options=("--opt", "O2"))
    invoke()
    assert counts(cc_log) == (before_flags[0] + 4, before_flags[1] + 1), "both flag variants should remain reusable"

    before_uncached = counts(cc_log)
    invoke(options=("--no-cache",))
    invoke(options=("--no-cache",))
    assert counts(cc_log) == (before_uncached[0] + 8, before_uncached[1] + 2)
    entry.write_text(entry.read_text() + "\n-- invalidate\n", encoding="utf-8")
    env["FAKE_EMIT_FAIL"] = "1"
    invoke(failure=True)
    invoke(options=("--check",), failure=True)


def test_frontend_native_fs_create_protocol(tmp: Path) -> None:
    """Native directory evidence requires every law, race result and byte readback."""
    import copy
    from dataclasses import replace
    import hashlib
    import struct

    import frontend_native_fs_create as native
    from ourosmith.limits import RunResult

    expected_names = (
        "empty-path", "path-nul-prefix", "path-nul-middle", "path-nul-suffix",
        "exact-input-capacity", "input-too-long", "unicode-byte-count", "wide-zero",
        "wide-last-terminated", "wide-at-capacity", "wide-over-capacity", "create-success-owns",
        "create-refusal-never-owns", "successful-release-keeps-success", "successful-release-keeps-refusal",
        "cleanup-retains-created-claim", "cleanup-retains-create-refusal", "cleanup-retains-conversion-failure",
        "cleanup-claim-survives-another-cleanup-error",
    )
    assert native.API_CASES == expected_names and len(expected_names) == 19
    expected_faults = ("nul", "utf8-overlong", "utf8-surrogate", "utf8-truncated", "allocation-failure",
                       "cleanup-created", "cleanup-refused", "cleanup-conversion")
    assert native.FAULTS == expected_faults
    expected_cases = ("positive", "duplicate-directory", "duplicate-file", "missing-parent-case",
                      *("fault-" + mode for mode in expected_faults), "race-A", "race-B")
    assert native.CASES == expected_cases and len(expected_cases) == 14

    def rejected(action):
        try:
            action()
        except (ValueError, OSError, KeyError, TypeError):
            return
        raise AssertionError("malformed exclusive-directory native evidence was accepted")

    api_output = "".join(f"PRECISION_OK fs-create-dir/{name}\n" for name in expected_names)
    api_output += "PRECISION_SUITE fs-create-dir rows=19\n"
    api = RunResult("ok", 0, api_output, "", 0, 0)
    native.verify_api_result(api)
    for changed in (replace(api, status="timeout"), replace(api, status="memory"), replace(api, returncode=1),
                    replace(api, returncode=False), replace(api, stderr="error\n"), replace(api, stdout=""),
                    replace(api, stdout=api_output.replace("PRECISION_OK fs-create-dir/path-nul-suffix\n", "")),
                    replace(api, stdout=api_output + "PRECISION_OK fs-create-dir/empty-path\n"),
                    replace(api, stdout=api_output.replace("rows=19", "rows=18"))):
        rejected(lambda candidate=changed: native.verify_api_result(candidate))

    def evidence(winner):
        rows = []
        for case in expected_cases:
            code, stdout = 3, b"FS_CREATE_REFUSED fs_create_dir_create created=0\n"
            if case == "positive":
                code, stdout = 0, b"FS_CREATE_CLAIM owner-A\n"
            elif case.startswith("fault-"):
                code, stdout = 0, f"FS_CREATE_FAULT_OK {case[6:]}\n".encode()
            elif case.startswith("race-"):
                code = 0 if case[-1] == winner else 3
                stdout = b"FS_CREATE_READY\n" + (f"FS_CREATE_CLAIM {winner}\n".encode() if code == 0 else stdout)
            rows.append({"case": case, "returncode": code, "stdout_hex": stdout.hex(), "stderr_hex": "",
                         "stdout_sha256": hashlib.sha256(stdout).hexdigest(), "stdout_exact": True,
                         "stderr_empty": True, "image_unchanged": True, "pass": True})
        return {"kind": native.KIND + ".runtime", "pass": True, "native_executed": True,
                "image_unchanged": True, "image_sha256": "fixture", "cases": rows, "race_winner": winner,
                "race_both_observed_absence": True,
                "readbacks": {"positive_owner_hex": b"owner-A".hex(), "existing_file_hex": b"existing\x00file\xff".hex(),
                    "missing_parent_exists": False,
                    "faults_exist": {mode: mode in {"cleanup-created", "cleanup-refused"} for mode in expected_faults},
                    "cleanup_refused_hex": b"prior-owner\x00\xff".hex(), "race_owner_hex": winner.encode().hex()}}

    good = evidence("A")
    native.verify_runtime_report(good, "fixture")
    native.verify_runtime_report(evidence("B"), "fixture")
    mutations = []
    for key, value in (("pass", False), ("native_executed", False), ("image_unchanged", False),
                       ("image_sha256", "stale"), ("cases", good["cases"][:-1]),
                       ("cases", good["cases"] + good["cases"][:1]),
                       ("cases", [good["cases"][1], good["cases"][0], *good["cases"][2:]]),
                       ("race_both_observed_absence", False), ("race_winner", "C")):
        changed = copy.deepcopy(good)
        changed[key] = value
        mutations.append(changed)
    for index, key, value in ((0, "returncode", False), (1, "returncode", 0), (4, "stdout_hex", ""),
                              (7, "stderr_hex", "0a"), (8, "pass", False), (9, "image_unchanged", False),
                              (12, "returncode", 3), (13, "returncode", 0), (13, "stdout_sha256", "stale")):
        changed = copy.deepcopy(good)
        changed["cases"][index][key] = value
        mutations.append(changed)
    for key, value in (("positive_owner_hex", b"owner-B".hex()), ("existing_file_hex", ""),
                       ("missing_parent_exists", True), ("missing_parent_exists", 0),
                       ("cleanup_refused_hex", ""), ("race_owner_hex", b"B".hex()),
                       ("faults_exist", {mode: True for mode in expected_faults})):
        changed = copy.deepcopy(good)
        changed["readbacks"][key] = value
        mutations.append(changed)
    for changed in mutations:
        rejected(lambda candidate=changed: native.verify_runtime_report(candidate, "fixture"))

    output = tmp / "directory-readbacks"
    marker = output / "created parent with spaces" / "Каталог 雪😀" / "claim.owner"
    marker.parent.mkdir(parents=True)
    marker.write_bytes(b"owner-A")
    (output / "existing-file").write_bytes(b"existing\x00file\xff")
    (output / "target-cleanup-created").mkdir()
    (output / "target-cleanup-refused").mkdir()
    (output / "target-cleanup-refused" / "existing.bin").write_bytes(b"prior-owner\x00\xff")
    (output / "race-target").mkdir()
    (output / "race-target" / "claim.owner").write_bytes(b"A")
    assert native.readbacks(output) == good["readbacks"]
    marker.write_bytes(b"owner-B")
    changed = copy.deepcopy(good)
    changed["readbacks"] = native.readbacks(output)
    rejected(lambda: native.verify_runtime_report(changed, "fixture"))
    large = output / "oversized-output.bin"
    large.write_bytes(b"x" * (1024 * 1024 + 1))
    rejected(lambda: native.read_small(large))
    with patch.object(native, "collect_units", return_value=[]):
        rejected(native.source_snapshot)
    with patch.object(native, "collect_units", side_effect=lambda entry: [entry, entry]):
        rejected(native.source_snapshot)
    with patch.object(native, "collect_units", side_effect=lambda entry: ["../outside.ouro", entry]):
        rejected(native.source_snapshot)

    policy = {"kind": native.KIND + ".supervisor", "pass": True, "cpu": [0], "workers": 1,
              "race_contenders": 2, "shared_memory_mib": 768, "suite_timeout_s": 240,
              "image": {"sha256": "fixture"}, "supervisor": {"status": "ok", "returncode": 0, "stdout": "", "stderr": ""}}
    native.verify_supervisor_report(policy, "fixture")
    for key, value in (("pass", False), ("cpu", [0, 1]), ("workers", True), ("race_contenders", 1),
                       ("shared_memory_mib", 3072), ("suite_timeout_s", 300), ("image", {"sha256": "stale"}),
                       ("supervisor", {"status": "timeout", "returncode": 0, "stdout": "", "stderr": ""})):
        changed = copy.deepcopy(policy)
        changed[key] = value
        rejected(lambda candidate=changed: native.verify_supervisor_report(candidate, "fixture"))

    # Independent PE wire fixture with named imports; never execute these bytes.
    image = bytearray(2048)
    image[:2] = b"MZ"
    struct.pack_into("<I", image, 0x3C, 128)
    image[128:132] = b"PE\0\0"
    struct.pack_into("<HH", image, 132, 0x8664, 1)
    struct.pack_into("<H", image, 148, 240)
    struct.pack_into("<H", image, 152, 0x20B)
    struct.pack_into("<I", image, 168, 0x1000)
    struct.pack_into("<I", image, 260, 16)
    struct.pack_into("<II", image, 272, 0x1100, 40)
    struct.pack_into("<IIII", image, 400, 1536, 0x1000, 1536, 512)
    struct.pack_into("<I", image, 428, 0x60000020)
    struct.pack_into("<IIIII", image, 768, 0x1180, 0, 0, 0x1150, 0x1180)
    image[848:861] = b"kernel32.dll\0"
    symbols = ("CreateDirectoryW", "MultiByteToWideChar", "VirtualAlloc", "VirtualFree")
    position = 1024
    for index, symbol in enumerate(symbols):
        struct.pack_into("<Q", image, 896 + index * 8, position + 0xE00)
        encoded = b"\0\0" + symbol.encode() + b"\0"
        image[position:position + len(encoded)] = encoded
        position += len(encoded)
    binary = tmp / "directory-import-wire.exe"
    binary.write_bytes(image)
    require_symbols = {"kernel32.dll": symbols}
    assert "import_symbols" not in native.inspect_image(binary, ["kernel32.dll"])
    inspected = native.inspect_image(binary, ["kernel32.dll"], require_symbols)
    assert inspected["import_symbols"] == {"kernel32.dll": list(symbols)}
    rejected(lambda: native.inspect_image(binary, ["kernel32.dll"], {"kernel32.dll": ["MissingSymbol"]}))
    for target in (1 << 63, 1 << 32, 0x3000):
        changed = bytearray(image)
        struct.pack_into("<Q", changed, 896, target)
        binary.write_bytes(changed)
        rejected(lambda: native.inspect_image(binary, ["kernel32.dll"], require_symbols))
    # The symbol string may be backed while its two-byte hint is not. A name
    # at the start of a section must not authorize an import RVA before it.
    changed = bytearray(image)
    symbol = b"CreateDirectoryW\0"
    changed[512:512 + len(symbol)] = symbol
    struct.pack_into("<Q", changed, 896, 0x0FFE)
    binary.write_bytes(changed)
    rejected(lambda: native.inspect_image(binary, ["kernel32.dll"], require_symbols))
def test_frontend_host_protocol(tmp: Path) -> None:
    """Host probes cannot pass on a timeout, partial verdict or changed binary."""
    from dataclasses import replace

    import frontend_host_suite as host
    from ourosmith.limits import RunResult

    cases = {case[1][0]: case for case in host.probe_cases()}
    expected = ("valid", "uninitialized", "bad-return", "mir-program-context", "mir-flow-context",
                "codegen-program-context", "mir-phase-errors", "mir-phase-nested", "mir-reachability-rounds", "lower-raw-order", "lower-raw-left", "lower-survivors",
                "pe-byte-large", "pe-byte-errors", "pe-byte-context", "lower-bad-result",
                "lower-bad-chunk", "lower-bad-contracts", "caller-output", "retained-result",
                "typed-failure", "nested-context", "allocation-context", "recheck-scale",
                "recheck-retained", "recheck-late-invalid", "recheck-missing-bodies", "recheck-zero-fuel")
    assert len(cases) == 28 and tuple(case[1][0] for case in host.probe_cases()) == expected
    raw = RunResult("ok", 0, "N1_HOST_LOWER: passed lower-raw-order\n", "", 0, 0)
    host.verify_probe(raw, cases["lower-raw-order"])
    malformed = RunResult("ok", 2, "", "n1-host: raw returned an invalid list\n", 0, 0)
    host.verify_probe(malformed, cases["lower-bad-chunk"])
    context = RunResult("ok", 0, "N1_HOST_CONTEXT: passed mir-flow-context\n", "", 0, 0)
    host.verify_probe(context, cases["mir-flow-context"])
    reachability = replace(context, stdout="N1_HOST_CONTEXT: passed mir-reachability-rounds\n")
    host.verify_probe(reachability, cases["mir-reachability-rounds"])
    pe = RunResult("ok", 0, "N1_HOST_PE: passed pe-byte-large\n", "", 0, 0)
    for mode in ("pe-byte-large", "pe-byte-errors", "pe-byte-context"):
        host.verify_probe(replace(pe, stdout=f"N1_HOST_PE: passed {mode}\n"), cases[mode])
    typed = RunResult("ok", 0, "FRONTEND_LINK_SELFTEST: passed typed-failure\n",
                      "probe.ouro: type mismatch in wrong\n", 0, 0)
    host.verify_probe(typed, cases["typed-failure"])
    rejected = RunResult("ok", 1, "", "n1-host: mir functions=1 live=600\n"
                         "n1-host: mir-check live=600\nn1-host: mir-check failed tag=0 n=1 live=31704\n"
                         "n1-host: mir:return\n", 0, 0)
    host.verify_probe(rejected, cases["bad-return"])
    invalid = [(replace(raw, stdout=""), "lower-raw-order"),
               (replace(raw, stderr="unexpected\n"), "lower-raw-order"),
               (replace(malformed, returncode=0), "lower-bad-chunk"),
               (replace(malformed, stderr=""), "lower-bad-chunk"),
               (replace(context, status="timeout"), "mir-flow-context"),
               (replace(context, returncode=1), "mir-flow-context"),
               (replace(context, stdout=context.stdout + "unexpected\n"), "mir-flow-context"),
               (replace(context, stderr="unexpected\n"), "mir-flow-context"),
               (replace(reachability, status="timeout"), "mir-reachability-rounds"),
               (replace(reachability, returncode=1), "mir-reachability-rounds"),
               (replace(reachability, stdout=""), "mir-reachability-rounds"),
               (replace(reachability, stderr="unexpected\n"), "mir-reachability-rounds"),
               (replace(pe, status="timeout"), "pe-byte-large"),
               (replace(pe, returncode=1), "pe-byte-large"),
               (replace(pe, stdout=""), "pe-byte-large"),
               (replace(pe, stdout=pe.stdout + "unexpected\n"), "pe-byte-large"),
               (replace(pe, stderr="unexpected\n"), "pe-byte-large"),
               (pe, "pe-byte-errors"),
               (pe, "pe-byte-context"),
               (replace(typed, stderr=""), "typed-failure"),
               (replace(rejected, returncode=0), "bad-return"),
               (replace(rejected, stdout="N1_HOST_MIR: emitted bad-return\n"), "bad-return"),
               (replace(rejected, stderr=rejected.stderr + "n1-host: gc-infer live=1\n"), "bad-return")]
    for result, mode in invalid:
        try:
            host.verify_probe(result, cases[mode])
        except ValueError:
            pass
        else:
            raise AssertionError("invalid host protocol accepted: " + mode)
    work = tmp / "host-artifacts"
    work.mkdir()
    generated = work / "backend.gen.c"
    generated.write_text("current generated fixture", encoding="utf-8")
    report = {"kind": host.KIND + ".build", "generated_sha256": host.sha256_file(generated), "binaries": {}}
    for name in host.HOST_MAINS:
        binary = host.executable(work, name)
        binary.write_bytes(b"current linked fixture")
        report["binaries"][name] = {"sha256": host.sha256_file(binary)}
    host.verify_artifacts(work, report)
    host.executable(work, "n1-host").write_bytes(b"stale producer")
    try:
        host.verify_artifacts(work, report)
    except ValueError:
        pass
    else:
        raise AssertionError("changed host executable accepted")
    before = {"inputs": {"compiler_sha256": "original"}}
    with patch.object(host, "snapshot", return_value={"inputs": {"compiler_sha256": "changed"}}):
        try:
            host.require_snapshot(None, None, before)
        except ValueError:
            pass
        else:
            raise AssertionError("changed producer accepted")


def test_frontend_native_process_protocol(tmp: Path) -> None:
    """Native runtime evidence must retain phase, bytes, resources, and held handles."""
    import copy
    from dataclasses import replace
    import struct

    import frontend_native_process as direct
    from ourosmith.limits import RunResult

    def rejected(operation):
        try:
            operation()
        except ValueError:
            return
        raise AssertionError("malformed native process evidence accepted")

    output = tmp / "rejected-helper.exe"
    stderr = ("n1-host: check units=4 live=100\n"
              "n1-host: CHECK_OK live=200 total=300\n"
              "n1-host: recheck live=200\nn1-host: RECHECK_OK live=200\n"
              "n1-host: TYPES_OK live=200\nn1-host: lower live=200\n"
              "n1-host: lower failed tag=0 n=1 live=200\nn1-host: lower:body:325\n")
    valid = RunResult("ok", 1, "", stderr, 0, 0)
    direct.verify_rejection(valid, r"body:[1-9][0-9]*", output)
    for changed in (replace(valid, status="memory"), replace(valid, status="timeout"),
                    replace(valid, returncode=73), replace(valid, returncode=0),
                    replace(valid, stdout="CHECK_OK\n"),
                    replace(valid, stderr=stderr.replace("n1-host: RECHECK_OK live=200\n", "")),
                    replace(valid, stderr=stderr.replace("lower:body:325", "lower:metadata:12")),
                    replace(valid, stderr=stderr + "n1-host: LOWER_OK live=200\n")):
        rejected(lambda candidate=changed: direct.verify_rejection(candidate, r"body:[1-9][0-9]*", output))
    fallback_stderr = stderr.replace("n1-host: lower failed", "n1-host: managed miss tag=7; scalar lower\n"
                                    "n1-host: lower failed").replace("lower:body:325", "lower:entry:326")
    fallback = replace(valid, stderr=fallback_stderr)
    assert direct.verify_rejection(fallback, r"entry:[1-9][0-9]*", output, True) == "lower:entry:326"
    for changed in (replace(fallback, status="memory"), replace(fallback, status="timeout"),
                    replace(fallback, stderr=fallback_stderr.replace("tag=7; scalar lower", "tag=4; scalar lower")),
                    replace(fallback, stderr=fallback_stderr.replace("n1-host: managed miss tag=7; scalar lower\n", "")),
                    replace(fallback, stderr=fallback_stderr.replace("lower:entry:326", "lower:global:0")),
                    replace(fallback, stderr=fallback_stderr.replace("lower:entry:326", "lower:metadata:326"))):
        rejected(lambda candidate=changed: direct.verify_rejection(candidate, r"entry:[1-9][0-9]*", output, True))
    rejected(lambda: direct.verify_rejection(fallback, r"entry:[1-9][0-9]*", output))
    rejected(lambda: direct.verify_rejection(valid, r"body:[1-9][0-9]*", output, True))
    output.write_bytes(b"unexpected output")
    rejected(lambda: direct.verify_rejection(valid, r"body:[1-9][0-9]*", output))

    # The source fixture owns these names; both overflow cases intentionally use
    # the same label. Keep their exact positions and multiplicity observable.
    api_names = (
        "child exit 0", "child exit 42", "child exit 73", "child exit 259", "child exit 4294967295",
        "OS code 259 stays OS error", "timeout is not child status", "cleanup timeout is not execution timeout",
        "invalid limits are explicit", "process memory event cannot pass expected73",
        "job memory event cannot pass expected73", "stdout overflow is not truncated success",
        "stderr overflow is not truncated success", "unknown outcome fails closed", "invalid exit width fails closed",
        "zero timeout", "INFINITE rejected", "zero memory", "memory scale overflow", "zero CPU",
        "multiple CPUs unsupported", "stdout allocation overflow", "stderr allocation overflow",
        "zero stream caps are valid", "capture cap", "capture cap", "binary stdin request remains exact",
        "default empty stdin request", "3GiB oneCPU policy remains explicit",
    )
    assert direct.API_CASES == api_names and len(api_names) == 29
    api_output = "".join(f"ok {name}\n" for name in api_names)
    api = RunResult("ok", 0, api_output, "", 0, 0)
    direct.verify_api_result(api)
    for changed in (replace(api, status="memory"), replace(api, status="timeout"),
                    replace(api, returncode=1), replace(api, returncode=73), replace(api, stderr="error\n"),
                    replace(api, stdout=api_output.replace("ok capture cap\n", "", 1)),
                    replace(api, stdout=api_output + "ok capture cap\n"),
                    replace(api, stdout=api_output.replace("ok child exit 259\n", "ok child exit 260\n")),
                    replace(api, stdout=api_output.replace("ok child exit 0\nok child exit 42\n",
                                                           "ok child exit 42\nok child exit 0\n"))):
        rejected(lambda candidate=changed: direct.verify_api_result(candidate))

    rows = [{"case": mode, "exit": 42, "stdout_hex": f"CAPTURE_OK {mode}\n".encode().hex(),
             "stderr_hex": ""} for mode in direct.MODES]
    rows[-1].update(exit=1, stdout_hex="")
    for row in rows[-2:]:
        row.update(parent_pid=101, descendant_pids=[102, 103], alive_before_observation=True,
                   held_handles_signaled=True)
    evidence = {"kind": direct.KIND + ".runtime", "status": "passed", "rows": rows,
                "binary_sha256": "fixture", "denied_sha256": "denied", "binaries_unchanged": True}
    direct.verify_runtime_report(evidence, "fixture", "denied")
    mutations = []
    for key, value in (("status", "failed"), ("binaries_unchanged", False),
                       ("binary_sha256", "stale"), ("denied_sha256", "stale"),
                       ("rows", rows[:-1]), ("rows", rows + rows[:1]),
                       ("rows", [rows[1], rows[0], *rows[2:]])):
        changed = copy.deepcopy(evidence)
        changed[key] = value
        mutations.append(changed)
    for index, key, value in ((0, "exit", 73), (0, "stdout_hex", ""), (0, "stderr_hex", "0a"),
                              (10, "exit", 74), (11, "held_handles_signaled", False),
                              (11, "alive_before_observation", False), (12, "descendant_pids", [102, 102]),
                              (12, "parent_pid", 102), (12, "exit", True)):
        changed = copy.deepcopy(evidence)
        changed["rows"][index][key] = value
        mutations.append(changed)
    for changed in mutations:
        rejected(lambda candidate=changed: direct.verify_runtime_report(candidate, "fixture", "denied"))

    # Independent tiny PE wire fixture: one executable section and one import.
    image = bytearray(1024)
    image[:2] = b"MZ"
    struct.pack_into("<I", image, 0x3C, 128)
    image[128:132] = b"PE\0\0"
    struct.pack_into("<HH", image, 132, 0x8664, 1)
    struct.pack_into("<H", image, 148, 240)
    struct.pack_into("<H", image, 152, 0x20B)
    struct.pack_into("<I", image, 168, 0x1000)
    struct.pack_into("<I", image, 260, 16)
    struct.pack_into("<II", image, 272, 0x1100, 40)
    struct.pack_into("<IIII", image, 400, 512, 0x1000, 512, 512)
    struct.pack_into("<I", image, 428, 0x60000020)
    struct.pack_into("<I", image, 780, 0x1150)
    image[848:861] = b"kernel32.dll\0"
    binary = tmp / "native-wire.exe"
    binary.write_bytes(image)
    direct.inspect_image(binary, ["kernel32.dll"])
    for offset, fmt, value in ((0x3C, "<I", 4096), (132, "<H", 0x14C), (152, "<H", 0x10B),
                               (168, "<I", 0x2000), (272, "<I", 0), (428, "<I", 0)):
        changed = bytearray(image)
        struct.pack_into(fmt, changed, offset, value)
        binary.write_bytes(changed)
        rejected(lambda: direct.inspect_image(binary, ["kernel32.dll"]))
    binary.write_bytes(image)
    rejected(lambda: direct.inspect_image(binary, ["ucrtbase.dll"]))
    binary.write_bytes(image[:800])
    rejected(lambda: direct.inspect_image(binary, ["kernel32.dll"]))

def test_native_suite_tools_protocol(tmp: Path) -> None:
    """Prebuilt mode fails closed and preserves the retained launcher contracts."""
    import struct
    import frontend_native_process
    import native_suite_tools as native

    work = tmp / "native-suite-protocol"
    work.mkdir()
    candidates = work / "candidate tools Ω"
    candidates.mkdir()

    # A PE wire fixture is never executed. Format alone must not become a
    # source-bound build claim in the observation snapshot.
    def pe(imports):
        image = bytearray(2048)
        image[:2] = b"MZ"
        struct.pack_into("<I", image, 0x3C, 128)
        image[128:132] = b"PE\0\0"
        struct.pack_into("<HH", image, 132, 0x8664, 1)
        struct.pack_into("<H", image, 148, 240)
        struct.pack_into("<H", image, 152, 0x20B)
        struct.pack_into("<I", image, 168, 0x1000)
        struct.pack_into("<I", image, 260, 16)
        struct.pack_into("<II", image, 272, 0x1100, 20 * (len(imports) + 1))
        struct.pack_into("<IIII", image, 400, 1536, 0x1000, 1536, 512)
        struct.pack_into("<I", image, 428, 0x60000020)
        position = 1024
        for index, name in enumerate(imports):
            struct.pack_into("<I", image, 780 + 20 * index, position + 0xE00)
            encoded = name.encode("ascii") + b"\0"
            image[position:position + len(encoded)] = encoded
            position += len(encoded)
        return image

    image = pe(native.IMPORTS)
    for name in {name for names in native.TOOLS.values() for name in names}:
        (candidates / name).write_bytes(image)
    receipt = work / "observed.json"

    def rejected(action):
        try:
            action()
        except (OSError, ValueError):
            return
        raise AssertionError("invalid native candidate observation was accepted")

    with patch.object(native.os, "name", "nt"):
        observed = native.observe(candidates, "lsp", receipt, False)
        assert observed["source_bound"] is False and observed["native_bootstrap"] is False
        assert tuple(observed["images"]) == ("coil.exe", "ouro-fmt.exe", "ouro-lsp.exe")
        assert native.observe(candidates, "lsp", receipt, True) == observed
        rejected(lambda: native.observe(candidates, "lsp", receipt, False))
        rejected(lambda: native.observe(candidates, "pkg", receipt, True))
        rejected(lambda: native.snapshot(work / "absent", "pkg"))
        (candidates / "coil.exe").write_bytes(image + b"changed")
        rejected(lambda: native.observe(candidates, "lsp", receipt, True))
        (candidates / "coil.exe").write_bytes(pe(["ucrtbase.dll", *native.IMPORTS[1:]]))
        rejected(lambda: native.snapshot(candidates, "pkg"))
        (candidates / "coil.exe").write_bytes(b"not a native image")
        rejected(lambda: native.snapshot(candidates, "pkg"))
        (candidates / "coil.exe").write_bytes(image)
        receipt.write_text("not-json", encoding="utf-8")
        rejected(lambda: native.observe(candidates, "lsp", receipt, True))
        (candidates / "ouro-fmt.exe").unlink()
        rejected(lambda: native.snapshot(candidates, "lsp"))
        assert tuple(native.snapshot(candidates, "pkg")["images"]) == ("coil.exe", "ouro-pkg.exe")
    with patch.object(native.os, "name", "posix"):
        rejected(lambda: native.snapshot(candidates, "pkg"))

    repo = work / "launcher-repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    for name in ("python.sh", "native_suite_tools.py", "lsp_suite.sh", "pkg_suite.sh",
                 "test_suite.sh", "samples_suite.sh"):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    (scripts / "build_tool.sh").write_text(
        '#!/bin/sh\nprintf attempted >"$2.attempted"\nexit 19\n', encoding="utf-8")
    empty = repo / "empty-candidates"
    empty.mkdir()
    env = isolated_env()
    env.update(PYTHON=sys.executable, CC="sh", PYTHONDONTWRITEBYTECODE="1",
               PYTHONPATH=str(Path(frontend_native_process.__file__).resolve().parent))
    shell = shutil.which("sh")
    assert shell, "native launcher protocol tests require the supported POSIX shell"

    def invoke(script, arguments, out, extra=None):
        # Every fixture path stays inside this test's fresh temporary tree.
        assert out.resolve().is_relative_to(work.resolve())
        options = dict(env, **{script.upper() + "_SUITE_OUT": out.as_posix()})
        options.update(extra or {})
        return subprocess.run([shell, str(scripts / (script + "_suite.sh")), *arguments],
                              cwd=repo, env=options, text=True, capture_output=True, timeout=15, check=False)

    for suite in ("lsp", "pkg", "test", "samples"):
        missing = invoke(suite, ["--native-tools"], work / (suite + "-args"))
        assert missing.returncode == 2 and "usage:" in missing.stderr, missing
        out = work / (suite + "-missing")
        failure = invoke(suite, ["--native-tools", str(empty)], out)
        assert failure.returncode == 1 and "NATIVE_SUITE_TOOLS: FAIL" in failure.stderr, failure
        assert "C compiler" not in failure.stderr and not list(out.glob("*.attempted")), failure
        # The default C selection still reaches its original build seam. This
        # fake build returns failure and does not claim C runtime acceptance.
        out = work / (suite + "-c-selection")
        assert not out.exists()
        legacy = invoke(suite, [], out)
        assert legacy.returncode == 1 and list(out.glob("*.attempted")), legacy

    existing = work / "protected-pkg-out"
    existing.mkdir()
    sentinel = existing / "keep"
    sentinel.write_text("candidate", encoding="utf-8")
    protected = invoke("pkg", ["--native-tools", str(empty)], existing)
    assert protected.returncode == 1 and "fresh PKG_SUITE_OUT" in protected.stderr, protected
    assert sentinel.read_text(encoding="utf-8") == "candidate"
    incompatible = invoke("test", ["--native-tools", str(empty), "--native-build-collection", "unused.exe"], work / "incompatible")
    assert incompatible.returncode == 2 and "separate C harness" in incompatible.stderr, incompatible

    # Exercise the actual shell completion seam with a fake observer. No PE
    # candidate is executed by this protocol test.
    observer = scripts / "native_suite_tools.py"
    observer.write_text('exit "${VERIFY_STATUS:-0}"\n', encoding="utf-8")
    for suite in ("test", "samples"):
        text = (scripts / (suite + "_suite.sh")).read_text(encoding="utf-8")
        start = text.index("run_suite() {")
        end = text.index("\n}\n", start) + 3
        harness = scripts / (suite + "-completion.sh")
        harness.write_text('set -eu\n' + text[start:end] +
                           '\nrun_suite sh -c \'printf child-output; exit 37\'\n', encoding="utf-8")
        options = dict(env, ROOT=repo.as_posix(), OUT=work.as_posix(),
                       PYTHON="sh", NATIVE_TOOLS=empty.as_posix())
        for verify_status, expected in (("0", 37), ("1", 1)):
            options["VERIFY_STATUS"] = verify_status
            result = subprocess.run([shell, str(harness)], cwd=repo, env=options, text=True,
                                    capture_output=True, timeout=15, check=False)
            assert (result.returncode, result.stdout, result.stderr) == (expected, "child-output", ""), result



def test_native_sleep_imports() -> None:
    """Complete native closures share one raw Sleep declaration, with no duplicate imports."""
    import frontend_regen as frontend
    from structural_quality import lex

    canonical = ("runtime/platform/windows_x64.ouro", "windows_capture_sleep")
    wrappers = {"runtime/platform/windows_sleep.ouro": "windows_sleep",
                "tests/native_managed/process_bounded.ouro": "capture_probe_sleep",
                "tests/native_managed/process_inherit.ouro": "inherit_test_sleep",
                "tests/native_process/child_sleep.ouro": "process_child_sleep",
                "tests/native_process/child_common.ouro": "process_child_sleep",
                "tests/native_process/campaign_common.ouro": "process_test_settle"}

    def declarations(unit):
        # Existing positional lexer keeps comments and string contents from
        # introducing declarations. Extern metadata consists of five strings.
        tokens = [token.value for token in lex((ROOT / unit).read_text(encoding="utf-8"), "ouro")[0]]
        found = []
        for index, lexeme in enumerate(tokens):
            if lexeme == "extern":
                statement = tokens[index:tokens.index(";", index)]
                assert len(statement) >= 9 and statement[-6] == ":=", (unit, statement)
                metadata = [json.loads(value) for value in statement[-5:]]
                assert all(isinstance(value, str) for value in metadata), (unit, statement)
                _target, _abi, library, symbol, _gc = metadata
                found.append(((library.lower(), symbol), (unit, statement[1])))
        return found

    roots = ("tests/process_capture_bounded_tests.ouro", "tests/native_managed/process_bounded.ouro",
             "tests/native_process/child_denied_job_commit.ouro", "tests/native_async_sleep_probe.ouro",
             "tests/native_managed/process_inherit.ouro", "tests/native_process/child_sleep.ouro",
             "tests/native_process/child_common.ouro", "tests/native_process/campaign_common.ouro")
    with patch.object(frontend, "ROOT", ROOT):
        for root in roots:
            imports = [row for unit in frontend.collect_units(root) for row in declarations(unit)]
            keys = [key for key, _owner in imports]
            assert len(keys) == len(set(keys)), (root, imports)
            assert [owner for key, owner in imports if key == ("kernel32.dll", "Sleep")] == [canonical], root
    for unit, wrapper in wrappers.items():
        assert wrapper not in [owner[1] for _key, owner in declarations(unit)], unit


def test_native_tool_hooks(tmp: Path) -> None:
    """Small tools need only their seams; required or malformed seams fail closed."""
    import native_tool_build as native

    generated = tmp / "host-hooks.c"

    def source(names):
        getters = []
        exports = []
        values = []
        for index, name in enumerate(names):
            gid = index + 10
            getters.append(
                f"static ouro_v *ouro_g{gid}(void){{ouro_env *env=0;(void)env;"
                f"if(ouro_c{gid}==0){{ouro_static_begin();"
                f"ouro_c{gid}=ouro_clos(ouro_f{gid}_,env);"
                f"ouro_static_end();}}return ouro_c{gid};}}")
            exports.append(f'case {index}: return "{name}";')
            values.append(f"case {index}: return ouro_g{gid}();")
        return '\n'.join(['#include "ouro_rt.h"', *getters,
                          'const char *ouro_export_name(int i){switch(i){', *exports,
                          'default: return "";}}',
                          'ouro_v *ouro_export_value(int i){switch(i){', *values,
                          'default: return 0;}}', ''])

    def hook(text, units=()):
        generated.write_text(text, encoding="utf-8")
        native.hook_compile_checked_units(generated, units)
        return generated.read_text(encoding="utf-8")

    plain = source(["main"])
    assert hook(plain, ["tools/minimal.ouro"]) == plain
    checker = hook(source(["compile_checked_units"]), ["compiler/driver.ouro"])
    assert "ouro_fe_compile_checked_units_clos();" in checker
    assert "ouro_wrap_" not in checker, "checker-only tools must not require a backend"
    encoder = hook(source(["x64_encode"]), ["compiler/native/x64.ouro"])
    assert "ouro_wrap_x64_encode(ouro_clos(" in encoder
    assert "ouro_fe_compile_checked_units_clos" not in encoder
    reachability = hook(source(["mir_reachable"]), ["compiler/native/mir_flow.ouro"])
    assert "ouro_wrap_mir_reachable(ouro_clos(" in reachability
    assert "ouro_wrap_mir_check_function" not in reachability

    names = ["compile_checked_units", *(name for name, _, _ in native.HOST_HOOKS)]
    owners = ["compiler/driver.ouro", *(owner for _, _, paths in native.HOST_HOOKS for owner in paths)]
    complete = hook(source(names), owners)
    assert "ouro_fe_compile_checked_units_clos();" in complete
    for _, wrapper, _ in native.HOST_HOOKS:
        assert complete.count(f"{wrapper}(ouro_clos(") == 1, wrapper

    def rejected(text, units, expected):
        generated.write_text(text, encoding="utf-8")
        try:
            native.hook_compile_checked_units(generated, units)
        except RuntimeError as error:
            assert expected in str(error), (expected, str(error))
        else:
            raise AssertionError(f"invalid generated host hook accepted: {expected}")
        assert generated.read_text(encoding="utf-8") == text, "failed hook published a partial rewrite"

    for name in names:
        rejected(source([item for item in names if item != name]), owners, name)
    rejected(source(["x64_encode"]).replace("case 0: return ouro_g10();", ""), (),
             "x64_encode export value")
    rejected(source(["x64_encode"]).replace("ouro_c10=ouro_clos(ouro_f10_,env);", "ouro_c10=0;"), (),
             "could not hook x64_encode getter")
    rejected(source(["compile_checked_units"]).replace("case 0: return ouro_g10();", ""), (),
             "compile_checked_units getter")
    rejected(source(["compile_checked_units"]).replace("ouro_c10=ouro_clos(ouro_f10_,env);", "ouro_c10=0;"), (),
             "could not hook compile_checked_units getter")

    # Every injected symbol must be provided by the normal tool link inputs,
    # not only by the separate N1 producer executable's main translation unit.
    runtime = "\n".join((ROOT / path).read_text(encoding="utf-8") for path in native.RUNTIME)
    for _, wrapper, _ in native.HOST_HOOKS:
        assert re.search(rf"ouro_v\s*\*\s*{re.escape(wrapper)}\s*\(ouro_v\s*\*raw\)\s*\{{", runtime), wrapper


def test_frontend_native_async_protocol(tmp: Path) -> None:
    """Synthetic receipts test rejection; they do not establish native execution."""
    import copy
    import hashlib

    import frontend_native_async as native

    def rejected(action):
        try:
            action()
        except (ValueError, OSError, KeyError, TypeError):
            return
        raise AssertionError("malformed native async evidence was accepted")

    cases = native.case_specs()
    assert [case["case"] for case in cases] == [
        "zero", "short", "delay", "reused", "values", "wide32", "wide64",
        "milliseconds-failure-zero", "milliseconds-failure-delay", "flag-failure-zero", "flag-failure-delay"]
    images = {variant: {"sha256": str(index) * 64} for index, variant in enumerate(native.VARIANTS)}
    rows = []
    for case in cases:
        times = [index / 100 for index in range(len(case["lines"]))]
        if case["case"] == "short":
            times = [0, 0.01, 1.01]
        elif case["case"] == "delay":
            times = [0, 0.01, 1.01, 1.02]
        elif case["case"] == "reused":
            times = [0, 0.01, 1.01, 2.02]
        rows.append({**{key: case[key] for key in ("case", "variant", "mode")},
            "stdout_hex": "".join(line + "\n" for line in case["lines"]).encode().hex(),
            "stderr_hex": case["stderr"].encode().hex(), "exit": 1 if case["held"] else case["exit"],
            "pid": 1, "elapsed_s": 3, "image_unchanged": True,
            "events": [{"line": line, "observed_s": at} for line, at in zip(case["lines"], times, strict=True)],
            "cancelled_by_harness": case["held"], "alive_before_cancel": case["held"],
            "held_after_construction_s": 1.30 if case["held"] else None})
    good = {"kind": native.KIND + ".runtime", "status": "passed", "native_bootstrap": False,
        "long_delays_completed": False, "source_lineage_confirmed": True, "images_unchanged": True,
        "image_hashes": {key: value["sha256"] for key, value in images.items()}, "rows": rows}
    directory = tmp / "async-byte-artifacts"
    for row in rows:
        work = directory / row["case"]
        work.mkdir(parents=True)
        for stream in ("stdout", "stderr"):
            (work / (stream + ".bin")).write_bytes(bytes.fromhex(row[stream + "_hex"]))
    native.verify_runtime_report(good, images, directory)
    mutations = []
    for key, value in (("status", "failed"), ("native_bootstrap", True), ("long_delays_completed", True),
                       ("source_lineage_confirmed", False), ("images_unchanged", False), ("image_hashes", {}),
                       ("rows", rows[:-1]), ("rows", rows + rows[:1]), ("rows", [rows[1], rows[0], *rows[2:]])):
        changed = copy.deepcopy(good)
        changed[key] = value
        mutations.append(changed)
    for index, key, value in ((0, "variant", "flag"), (0, "mode", "short"), (0, "exit", False),
        (0, "pid", 0), (0, "pid", True), (0, "pid", 0x100000000), (0, "elapsed_s", float("nan")),
        (0, "image_unchanged", False), (0, "cancelled_by_harness", True), (1, "stdout_hex", ""),
        (2, "stderr_hex", "0a"), (4, "stdout_hex", rows[4]["stdout_hex"] + "0a"),
        (5, "held_after_construction_s", 1.29), (5, "held_after_construction_s", 15),
        (5, "held_after_construction_s", float("inf")), (5, "cancelled_by_harness", False),
        (6, "alive_before_cancel", False), (6, "elapsed_s", 1.0), (7, "exit", 0),
        (8, "stdout_hex", rows[8]["stdout_hex"] + b"ASYNC_ACTION\n".hex()), (9, "stderr_hex", "")):
        changed = copy.deepcopy(good)
        changed["rows"][index][key] = value
        mutations.append(changed)
    for index, event, value in ((0, 1, 0.9), (0, 2, 0.9), (1, 2, 0.5),
                               (2, 2, float("nan")), (3, 3, 1.4), (4, 1, -1), (4, 8, 16)):
        changed = copy.deepcopy(good)
        changed["rows"][index]["events"][event]["observed_s"] = value
        mutations.append(changed)
    changed = copy.deepcopy(good)
    changed["rows"][2]["events"][2]["line"] = "ASYNC_AFTER"
    mutations.append(changed)
    for changed in mutations:
        rejected(lambda candidate=changed: native.verify_runtime_report(candidate, images))
    byte_path = directory / "zero/stdout.bin"
    byte_path.write_bytes(b"stale")
    rejected(lambda: native.verify_runtime_report(good, images, directory))
    byte_path.write_bytes(b"x" * (1024 * 1024 + 1))
    rejected(lambda: native.read_small(byte_path))

    observer = {"kind": native.KIND + ".observer", "status": "passed", "spec_sha256": "spec",
        "memory_mib": 768, "suite_timeout_s": 120, "case_timeout_s": 15,
        "supervisor": {"status": "ok", "returncode": 0,
                       "stdout": "FRONTEND_NATIVE_ASYNC_WORKER: PASS cases=11\n", "stderr": ""}}
    native.verify_observer_report(observer, "spec")
    for key, value in (("status", "failed"), ("spec_sha256", "stale"), ("memory_mib", 3072),
                       ("suite_timeout_s", 121), ("case_timeout_s", 16)):
        changed = copy.deepcopy(observer)
        changed[key] = value
        rejected(lambda candidate=changed: native.verify_observer_report(candidate, "spec"))
    for key, value in (("status", "memory"), ("status", "timeout"), ("returncode", 1),
                       ("returncode", False), ("stdout", ""), ("stderr", "unexpected\n")):
        changed = copy.deepcopy(observer)
        changed["supervisor"][key] = value
        rejected(lambda candidate=changed: native.verify_observer_report(candidate, "spec"))

    # Tiny source roots exercise real file hashes and import ordering. The fake
    # images below are inert bytes; the independent PE parser has its own tests.
    root = tmp / "async-source-root"
    sleep = root / native.SLEEP
    entry = root / native.ENTRY
    sleep.parent.mkdir(parents=True)
    entry.parent.mkdir(parents=True)
    sleep.write_text("u32_from_nat 1000\nu8_from_nat 1\n", encoding="utf-8")
    entry.write_text('import "../runtime/platform/windows_sleep.ouro";\n', encoding="utf-8")
    units = [native.SLEEP, native.ENTRY]
    with patch.object(native, "ROOT", root), patch.object(native, "collect_units", return_value=units):
        before = native.source_snapshot()
        builds = root / "builds"
        native.freeze_sources(builds, before)
        producer = root / "producer.exe"
        producer.write_bytes(b"synthetic common producer; never executed")
        producer_hash = native.sha256_file(producer)

        def fake_image(path, _variant):
            return {"sha256": native.sha256_file(path), "bytes": path.stat().st_size,
                    "machine": "x86_64", "imports": list(native.IMPORTS)}

        receipts = {}
        for variant in native.VARIANTS:
            inputs_path = builds / variant / "inputs.json"
            inputs = native.read_json(inputs_path)
            output = builds / variant / "probe.exe"
            output.write_bytes(("synthetic image " + variant).encode())
            receipt = {"kind": native.KIND + ".build", "status": "passed", "variant": variant,
                "producer": str(producer), "producer_sha256": producer_hash,
                "argv": [str(producer), native.ENTRY, output.as_posix(), *units], "cwd": inputs["source_root"],
                "inputs": str(inputs_path), "inputs_sha256": native.sha256_file(inputs_path),
                "output": str(output), "image": fake_image(output, variant), "result_status": "ok",
                "returncode": 0, "stdout": output.as_posix() + "\n", "inputs_unchanged": True, "producer_unchanged": True}
            path = builds / variant / "receipt.json"
            native.write_json_atomic(path, receipt)
            receipts[variant] = native.sha256_file(path)
        with patch.object(native, "image_info", side_effect=fake_image):
            assert set(native.verify_builds(builds, before, producer, producer_hash, receipts)) == set(native.VARIANTS)
            rejected(lambda: native.verify_builds(builds, before, producer, producer_hash, {}))
            path = builds / "original/receipt.json"
            original = native.read_json(path)
            for key, value in (("status", "failed"), ("variant", "flag"), ("producer_sha256", "stale"),
                ("cwd", str(root)), ("argv", []), ("inputs_sha256", "stale"), ("image", {}),
                ("result_status", "timeout"), ("returncode", 1), ("returncode", False),
                ("stdout", ""), ("inputs_unchanged", False), ("producer_unchanged", 1)):
                native.write_json_atomic(path, {**original, key: value})
                changed = {**receipts, "original": native.sha256_file(path)}
                rejected(lambda candidate=changed: native.verify_builds(builds, before, producer, producer_hash, candidate))
            native.write_json_atomic(path, original)
            assert native.sha256_file(path) == receipts["original"]
            input_path = builds / "milliseconds/inputs.json"
            source_input = native.read_json(input_path)
            copied_source = Path(source_input["source_root"]) / native.SLEEP
            copied_source.write_bytes(b"changed source with recomputed manifest\n")
            source_input["sources"][native.SLEEP] = hashlib.sha256(copied_source.read_bytes()).hexdigest()
            native.write_json_atomic(input_path, source_input)
            rejected(lambda: native.verify_builds(builds, before, producer, producer_hash, receipts))
            native.freeze_sources(builds, before)
            producer.write_bytes(b"changed producer")
            rejected(lambda: native.verify_builds(builds, before, producer, producer_hash, receipts))
        with patch.object(native, "collect_units", return_value=[]):
            rejected(native.source_snapshot)
        with patch.object(native, "collect_units", return_value=[native.SLEEP, native.ENTRY, native.ENTRY]):
            rejected(native.source_snapshot)
        with patch.object(native, "collect_units", return_value=["../outside.ouro", *units]):
            rejected(native.source_snapshot)


def test_collect_build_protocol(tmp: Path) -> None:
    """Cold collector setup must preserve check output and expose build failures."""
    repo = tmp / "collect-protocol"
    (repo / "scripts").mkdir(parents=True)
    (repo / "tools").mkdir()
    shutil.copyfile(ROOT / "scripts/ouro1.sh", repo / "scripts/ouro1.sh")
    (repo / "tools/collect.ouro").write_text("-- collector input\n", encoding="utf-8")
    (repo / "input.ouro").write_text("def value : Nat := 0;\n", encoding="utf-8")
    compiler = repo / "compiler"
    compiler.write_text("#!/bin/sh\nprintf 'CHECK_OK\\n'\n", encoding="utf-8")
    compiler.chmod(0o755)
    (repo / "scripts/build_tool.sh").write_text(
        "#!/bin/sh\nset -eu\nprintf 'build stdout\\n'\nprintf 'build stderr\\n' >&2\n"
        "[ \"${COLLECT_BUILD_FAIL:-0}\" = 0 ] || exit 23\n"
        "printf '#!/bin/sh\\nprintf \\\"input.ouro\\\\n\\\"\\n' >\"$2\"\n"
        "i=0; while [ \"$i\" -lt 4100 ]; do printf '#' >>\"$2\"; i=$((i + 1)); done\n"
        "printf '\\n' >>\"$2\"\nchmod +x \"$2\"\n", encoding="utf-8")
    env = isolated_env()
    env.update(OURO_ROOT=repo.as_posix(), OURO1_COMPILER=compiler.as_posix(),
               OURO_C_BUILD_DIR=(repo / "out").as_posix())
    shell = shutil.which("sh")
    assert shell, "collector wrapper tests require the supported POSIX shell"

    def invoke():
        return subprocess.run([shell, "scripts/ouro1.sh", "check", "input.ouro"],
                              cwd=repo, env=env, text=True, capture_output=True, timeout=30, check=False)

    cold = invoke()
    assert (cold.returncode, cold.stdout, cold.stderr) == (0, "CHECK_OK\n", ""), cold
    log = repo / "out/ouro-collect.build.log"
    assert log.read_text(encoding="utf-8") == "build stdout\nbuild stderr\n"
    original_time = log.stat().st_mtime_ns
    env["COLLECT_BUILD_FAIL"] = "1"
    warm = invoke()
    assert (warm.returncode, warm.stdout, warm.stderr) == (0, "CHECK_OK\n", ""), warm
    assert log.stat().st_mtime_ns == original_time, "warm check rebuilt the collector"
    (repo / "out/ouro-collect").unlink()
    failure = invoke()
    assert failure.returncode != 0 and failure.stdout == "", failure
    assert failure.stderr == "build stdout\nbuild stderr\n", failure
    assert log.read_text(encoding="utf-8") == failure.stderr


def main() -> int:
    import bootstrap_compiler_test
    import bootstrap_inputs_test

    bootstrap_inputs_test.run()
    bootstrap_compiler_test.run()
    test_seal_parse()
    with tempfile.TemporaryDirectory(prefix="ouro-build-suite-") as d:
        tmp = Path(d)
        test_collect_build_protocol(tmp)
        test_frontend_native_async_protocol(tmp)
        test_retired_toolchain_contract(tmp)
        test_incremental_invalidation(tmp)
        test_config_precedence(tmp)
        test_frontend_native_fs_create_protocol(tmp)
        test_destructive_path_policy(tmp)
        test_native_tool_hooks(tmp)
        test_frontend_host_protocol(tmp)
        test_frontend_native_process_protocol(tmp)
        test_native_suite_tools_protocol(tmp)
        test_native_sleep_imports()
        test_native_tool_cache(tmp)
    print("BUILD_CACHE_CONFIG_SUITE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
