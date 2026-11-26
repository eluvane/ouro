#!/usr/bin/env python3
"""Regression tests for Ouro build cache invalidation and config precedence.

Build graph tests use a fake C compiler in a temporary copy. Launcher tests
that need a native child compile a small fixture.
"""
from __future__ import annotations

import json
import concurrent.futures
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

import ouro_build as build_driver
from local_scheduler import JOBS_ENV, MEMORY_ENV

ROOT = Path(__file__).resolve().parents[1]


def copy_repo(dst: Path) -> None:
    ignore = shutil.ignore_patterns("_build", "_cache", ".git", "*.pyc", "__pycache__",
                                   "_tmp_ci_linux", "_tmp_portable_macos")
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
    config = build_driver.ResolvedConfig({**build_driver.DEFAULTS, "verbosity": "quiet",
                                          "cache_dir": str(tmp / "dispatch-cache")}, {})
    with patch.object(build_driver, "load_config", return_value=config), \
         patch.object(bootstrap_compiler, "ensure_current_compiler") as current_stage, \
         patch.object(build_driver, "build_c", side_effect=AssertionError("unverified direct C build")), \
         patch.object(build_driver, "trim_cache") as cache, \
         patch.object(build_driver.shutil, "which", side_effect=AssertionError("unexpected toolchain discovery")):
        build_driver.run_build(argparse.Namespace())
    current_stage.assert_called_once_with(config, build_driver, build_driver.ROOT, compact_sources=False)
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
    fixture_home = tmp / "home"
    fixture_home.mkdir()
    cases = [
        ("build_dir", "."),
        ("c_build_dir", ".."),
        ("cache_dir", str(fixture_home)),
        ("cache_dir", repo.anchor),
    ]
    previous_root = build_driver.ROOT
    build_driver.ROOT = repo
    try:
        with patch.object(Path, "home", return_value=fixture_home):
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


def test_host_stack_link_flags() -> None:
    for system, platform, expected in (
        ("nt", "win32", ["-Wl,--stack,2147483648"]),
        ("posix", "darwin", ["-Wl,-stack_size,0x8000000"]),
        ("posix", "linux", []),
    ):
        with patch.object(build_driver.os, "name", system), patch.object(build_driver.sys, "platform", platform):
            assert build_driver.host_link_flags() == expected, platform


def test_c_ccache_disabled_skips_discovery() -> None:
    cc = "fixture-cc"
    with patch.object(build_driver.shutil, "which", return_value=None) as discover:
        disabled = build_driver.ResolvedConfig({**build_driver.DEFAULTS, "ccache": "disabled"}, {})
        assert build_driver.ccache_prefix(disabled, cc) == ([cc], {}, "disabled")
        discover.assert_not_called()
        auto = build_driver.ResolvedConfig({**build_driver.DEFAULTS, "ccache": "auto"}, {})
        assert build_driver.ccache_prefix(auto, cc) == ([cc], {}, "auto-unavailable")
        discover.assert_called_once_with("ccache")


def test_c_ccache_discovery_is_per_build(tmp: Path) -> None:
    cc = tmp / "ccache-cc.py"
    write_fake_cc(cc)
    ccache = str(tmp / "ccache-fixture")
    sources = [(name, tmp / f"{name}.c") for name in ("ccache-left", "ccache-right")]
    for name, path in sources:
        path.write_text(f"/* {name} */\n", encoding="utf-8")
    cfg = build_driver.ResolvedConfig({**build_driver.DEFAULTS, "cc": str(cc), "verbosity": "quiet",
                                      "cache_dir": str(tmp / "test-cache")}, {})
    cc_log = tmp / "ccache-cc.log"
    cache_dir = cfg.path("cache_dir") / "ccache"
    discover, run = shutil.which, subprocess.run
    available = None
    probes = []
    wrapped = []
    overlap = Barrier(len(sources), timeout=5)

    def which(command):
        if command != "ccache":
            return discover(command)
        probes.append(command)
        return available

    def invoke(command, *args, **options):
        if command[0] == ccache:
            assert "-c" in command
            assert options["env"]["CCACHE_DIR"] == str(cache_dir)
            assert options["env"]["CCACHE_MAXSIZE"] == f"{cfg.get_int('cache_size_mb')}M"
            wrapped.append(Path(command[command.index("-c") + 1]))
            overlap.wait()
            command = command[1:]
        return run(command, *args, **options)

    def build(label, jobs):
        return build_driver.build_c_executable(cfg, name="ccache", sources=sources,
            output=tmp / f"{label}.exe", object_dir=tmp / f"{label}-obj", jobs=jobs)

    with (patch.dict(os.environ, {"FAKE_CC_LOG": str(cc_log), "OURO_SCHEDULER_JOBS": "20"}),
          patch.object(shutil, "which", side_effect=which), patch.object(subprocess, "run", side_effect=invoke)):
        cold = build("cold", 1)
        assert probes == ["ccache"], probes
        assert [row["ccache"] for row in cold["sources"]] == ["auto-unavailable"] * len(sources)

        cfg.values["ccache"] = "enabled"
        probes.clear()
        assert [row["ccache"] for row in build("cold", 20)["sources"]] == ["not-invoked"] * len(sources)
        assert not probes and counts(cc_log) == (len(sources), 1)

        try:
            build("retry", 1)
        except SystemExit as error:
            assert str(error) == "CONFIG: ccache=enabled but ccache is not installed"
        else:
            raise AssertionError("required ccache was not enforced on a miss")
        assert counts(cc_log) == (len(sources), 1)

        available = ccache
        probes.clear()
        retry = build("retry", 20)
        assert probes == ["ccache"], probes
        assert [row["ccache"] for row in retry["sources"]] == ["enabled"] * len(sources)
        assert sorted(wrapped) == sorted(path for _name, path in sources)
        assert counts(cc_log) == (2 * len(sources), 2)
        assert retry["link"]["output_sha256"] == cold["link"]["output_sha256"]


def test_clang_bracket_depth(tmp: Path) -> None:
    cc = tmp / "bracket-cc.py"
    write_fake_cc(cc)
    source = tmp / "bracket.c"
    source.write_text("int value(void) { return 1; }\n", encoding="utf-8")
    cfg = build_driver.ResolvedConfig({**build_driver.DEFAULTS, "ccache": "disabled", "verbosity": "quiet"}, {})
    for version, expected in (("Apple clang version 17.0.0", True), ("Ubuntu clang version 18.1.3", True),
                              ("gcc (GCC) 13.3.0", False)):
        identity = json.dumps({"cc": str(cc), "path": str(cc), "version": [version]})
        flags = build_driver.object_profile_cflags(build_driver.profile_cflags(cfg), [version])
        with patch.dict(os.environ, {"FAKE_CC_LOG": str(tmp / "bracket-cc.log")}):
            args = (cfg, str(cc), identity, "bracket", source, "bracket", flags, tmp / "bracket-obj")
            obj, report = build_driver.compile_c_object(*args)
            assert report["cache"] == "miss", version
            stamp = json.loads(obj.with_suffix(".cmdhash").read_text(encoding="utf-8"))
            assert ("-fbracket-depth=4096" in stamp["command"]) is expected, version
            assert build_driver.compile_c_object(*args)[1]["cache"] == "hit", version


def test_c_cache_hit_hashes(tmp: Path) -> None:
    cc = tmp / "digest-cc.py"
    write_fake_cc(cc)
    headers = [tmp / "digest-b.h", tmp / "digest-a.h"]
    for header in headers:
        header.write_bytes(b"/* 1 */\n")
    source = tmp / "digest.c"
    source.write_text('#include "digest-b.h"\n#include "digest-a.h"\nint main(void) { return 0; }\n', encoding="utf-8")
    output = tmp / "digest.exe"
    log = tmp / "digest-cc.log"
    cfg = build_driver.ResolvedConfig({**build_driver.DEFAULTS, "cc": str(cc), "ccache": "disabled",
                                      "verbosity": "quiet", "jobs": 1}, {})

    def build():
        return build_driver.build_c_executable(cfg, name="digest", sources=[("digest", source)],
            output=output, object_dir=tmp / "digest-obj", jobs=1)

    with patch.dict(os.environ, {"FAKE_CC_LOG": str(log)}):
        cold = build()
        with patch.object(build_driver, "sha256_file", wraps=build_driver.sha256_file) as digest, \
                patch.object(build_driver, "path_key", wraps=build_driver.path_key) as path_keys, \
                patch.object(Path, "open", autospec=True, side_effect=Path.open) as reads, \
                patch.object(Path, "resolve", autospec=True, side_effect=Path.resolve) as resolves:
            warm = build()
        obj = build_driver.ROOT / warm["objects"][0]
        dep = obj.with_suffix(".d")
        paths = [call.args[0] for call in digest.call_args_list]
        assert warm["sources"][0]["cache"] == warm["link"]["cache"] == "hit"
        assert warm["sources"][0]["object_sha256"] == cold["sources"][0]["object_sha256"]
        assert warm["link"]["output_sha256"] == cold["link"]["output_sha256"]
        assert paths.count(obj) == 2, paths
        assert paths.count(output) == 1, paths
        assert paths[:3] == [source, *headers], paths
        assert [call.args[0] for call in reads.call_args_list].count(dep) == 1
        assert sum(call.args[0] == source.resolve() for call in path_keys.call_args_list) == 3
        roots = [call.args[0] for call in resolves.call_args_list].count(build_driver.ROOT)
        assert roots == 4, roots
        assert counts(log) == (1, 1)

        saved_header = headers[0].stat()
        headers[0].write_bytes(b"/* 2 */\n")
        os.utime(headers[0], ns=(saved_header.st_atime_ns, saved_header.st_mtime_ns))
        assert build()["sources"][0]["reason"] == "dependency-hash"

        saved_dep = dep.stat()
        raw_dep = dep.read_bytes()
        rewritten = raw_dep.rstrip(b"\r\n").ljust(len(raw_dep), b" ")
        assert rewritten != raw_dep
        dependencies = build_driver.dep_digests_from_depfile(dep, source)
        dep.write_bytes(rewritten)
        os.utime(dep, ns=(saved_dep.st_atime_ns, saved_dep.st_mtime_ns))
        assert build_driver.dep_digests_from_depfile(dep, source) == dependencies
        assert build()["sources"][0]["reason"] == "depfile-hash"

        obj.write_bytes(b"bad object")
        rebuilt = build()
        assert rebuilt["sources"][0]["reason"] == "object-hash"
        output.write_bytes(b"bad executable")
        repaired = build()
        assert repaired["sources"][0]["cache"] == "hit"
        assert repaired["link"]["reason"] == "output-hash"
        assert repaired["link"]["output_sha256"] == warm["link"]["output_sha256"]

        stamp = obj.with_suffix(".cmdhash")
        expected = json.loads(stamp.read_text(encoding="utf-8"))["command_hash"]
        headers[1].unlink()
        assert build_driver.compile_stamp_digest(obj, dep, stamp, expected, source) == (None, "unreadable-dependency")


def test_link_stamp_resolves_root_once(tmp: Path) -> None:
    cc = tmp / "link-digest-cc.py"
    write_fake_cc(cc)
    log = tmp / "link-digest-cc.log"
    objects = [tmp / "link-b.o", tmp / "link-a.o"]
    for obj in objects:
        obj.write_bytes(obj.name.encode("ascii"))
    output = tmp / "link-digest.exe"
    stamp = output.with_suffix(".exe.cmdhash")
    cfg = build_driver.ResolvedConfig({**build_driver.DEFAULTS, "verbosity": "quiet"}, {})

    def link(expected_cache: str) -> str:
        with patch.object(Path, "resolve", autospec=True, side_effect=Path.resolve) as resolve:
            report = build_driver.link_c_objects(cfg, str(cc), "fake-cc", "link-digest", objects, output, [])
        resolved = [call.args[0] for call in resolve.call_args_list]
        assert resolved.count(build_driver.ROOT) == 1, resolved
        assert [path for path in resolved if path in objects] == objects, resolved
        assert report["cache"] == expected_cache
        return report["output_sha256"]

    with patch.dict(os.environ, {"FAKE_CC_LOG": str(log)}):
        cold_digest = link("miss")
        assert link("hit") == cold_digest
        assert counts(log) == (0, 1)

    receipt = json.loads(stamp.read_text(encoding="utf-8"))
    assert receipt["objects"] == {build_driver.path_key(obj): build_driver.sha256_file(obj) for obj in objects}
    saved = objects[0].stat()
    objects[0].write_bytes(b"edited.o")
    os.utime(objects[0], ns=(saved.st_atime_ns, saved.st_mtime_ns))
    assert build_driver.link_stamp_digest(output, stamp, receipt["command_hash"], objects) == (None, "object-hash")
    objects[1].unlink()
    assert build_driver.link_stamp_digest(output, stamp, receipt["command_hash"], objects) == (None, "missing-object-or-exe")


def test_fe_link_reuses_exact_installed_bytes(tmp: Path) -> None:
    root = tmp / "frontend-link"
    source = root / "runtime/frontend_link.c"
    source.parent.mkdir(parents=True)
    body = "/* café */\nint linker_fixture = 1;\n"
    source.write_bytes(body.replace("\n", "\r\n", 1).encode("utf-8"))
    with patch.object(build_driver, "ROOT", root):
        target = build_driver.ensure_fe_link()
        banner = "/* Generated frontend linker. Source: runtime/frontend_link.c. Do not hand-edit. */\n"
        expected = (banner + body).replace("\n", os.linesep).encode("utf-8")
        assert target.read_bytes() == expected
        installed = target.stat()
        with (patch.object(Path, "write_bytes", side_effect=AssertionError("identical frontend linker rewritten")),
              patch.object(Path, "write_text", side_effect=AssertionError("identical frontend linker rewritten"))):
            assert build_driver.ensure_fe_link() == target
        assert target.stat().st_mtime_ns == installed.st_mtime_ns
        target.write_bytes(expected.replace(b"= 1", b"= 2"))
        os.utime(target, ns=(installed.st_atime_ns, installed.st_mtime_ns))
        assert target.stat().st_size == installed.st_size
        assert build_driver.ensure_fe_link() == target
        assert target.read_bytes() == expected


@patch.dict(os.environ, {JOBS_ENV: "2"})
def test_c_compile_priority_preserves_link_order(tmp: Path) -> None:
    work = tmp / "compile-priority"
    work.mkdir()
    sources = []
    for label, size in (("small", 8), ("large", 128), ("medium", 32)):
        path = work / (label + ".c")
        path.write_bytes(b" " * size)
        sources.append((label, path))
    submitted, linked = [], []

    class Pool:
        def __init__(self, *, max_workers):
            assert max_workers == 2

        def __enter__(self):
            return self

        def __exit__(self, *unused):
            return False

        def submit(self, function, *arguments, **options):
            submitted.append(arguments[5])
            future = concurrent.futures.Future()
            future.set_result(function(*arguments, **options))
            return future

    def compile_object(_cfg, _cc, _identity, _target, path, label, *_options, **_kwargs):
        obj = work / (label + ".o")
        return obj, {"label": label, "source": str(path), "cache": "miss", "elapsed_s": 0}

    def link_objects(_cfg, _cc, _identity, _target, objects, *_options):
        linked.extend(path.stem for path in objects)
        return {"cache": "miss", "elapsed_s": 0}

    cfg = build_driver.ResolvedConfig({**build_driver.DEFAULTS, "jobs": 2}, {})
    with patch.object(build_driver, "locate_cc", return_value=("fixture-cc", "fixture-cc")), \
         patch.object(build_driver, "compiler_id", return_value='{"version": []}'), \
         patch.object(build_driver.concurrent.futures, "ThreadPoolExecutor", Pool), \
         patch.object(build_driver, "compile_c_object", side_effect=compile_object), \
         patch.object(build_driver, "link_c_objects", side_effect=link_objects):
        result = build_driver.build_c_executable(cfg, name="priority", sources=sources,
            output=work / "output", object_dir=work / "objects", jobs=2)
    assert submitted == ["large", "medium", "small"], submitted
    assert linked == ["small", "large", "medium"], linked
    assert [row["label"] for row in result["sources"]] == linked


def test_c_source_flags(tmp: Path) -> None:
    work = tmp / "source-flags"
    work.mkdir()
    cc = work / "fake-cc.py"
    cc_log = work / "fake-cc.log"
    write_fake_cc(cc)
    common = work / "common.c"
    first_main = work / "first-main.c"
    module_main = work / "module-main.c"
    common.write_text("int common(void) { return 1; }\n", encoding="utf-8")
    first_main.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    module_main.write_text("#ifndef MODULE_ONLY\n#error MODULE_ONLY is required\n#endif\n"
                           "int main(void) { return 0; }\n", encoding="utf-8")
    cfg = build_driver.ResolvedConfig({**build_driver.DEFAULTS, "cc": str(cc), "ccache": "disabled",
                                      "cache_enabled": False, "verbosity": "quiet", "jobs": 1}, {})
    object_dir = work / "objects"
    global_flags = ["-DGLOBAL_FLAG=1"]
    source_flags = {"module-main": ("-DMODULE_ONLY=1",)}

    def build(main, mapping=None, extra=global_flags):
        with (patch.object(shutil, "which", return_value=str(cc)) as discover,
              patch.object(build_driver, "profile_cflags", wraps=build_driver.profile_cflags) as profile,
              patch.object(build_driver, "compiler_id", wraps=build_driver.compiler_id) as identify):
            report = build_driver.build_c_executable(cfg, name="shared-host",
                sources=[("generated-common", common), (main.stem, main)], output=work / (main.stem + ".exe"),
                object_dir=object_dir, include_dirs=[work], extra_cflags=extra, source_cflags=mapping, jobs=1)
        assert profile.call_count == 2, profile.call_count
        discover.assert_called_once_with(str(cc))
        identify.assert_called_once_with(str(cc), location=str(cc))
        return report

    def check_commands(report, mapping, extra=global_flags):
        rows = {row["label"]: row for row in report["sources"]}
        for label, row in rows.items():
            stamp_path = Path(row["cmdhash"])
            if not stamp_path.is_absolute():
                stamp_path = build_driver.ROOT / stamp_path
            stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
            expected = build_driver.profile_cflags(cfg) + list(extra) + list(mapping.get(label, ())) + [f"-I{work}"]
            command = stamp["command"]
            assert command[1:command.index("-MMD")] == expected, (label, command)
            assert stamp["command_hash"] == build_driver.command_hash(command, report["compiler_id"])
        return rows

    with patch.dict(os.environ, {"FAKE_CC_LOG": str(cc_log)}):
        first = build(first_main)
        first_rows = check_commands(first, {})
        assert first["compile_misses"] == 2 and counts(cc_log) == (2, 1)

        second = build(module_main, source_flags)
        second_rows = check_commands(second, source_flags)
        assert second["compile_hits"] == 1 and second["compile_misses"] == 1 and counts(cc_log) == (3, 2)
        assert second_rows["generated-common"]["cache"] == "hit"
        assert second_rows["generated-common"]["object"] == first_rows["generated-common"]["object"]

        warm = build(module_main, source_flags)
        check_commands(warm, source_flags)
        assert warm["compile_hits"] == 2 and warm["compile_misses"] == 0 and warm["link_cache"] == "hit"
        assert counts(cc_log) == (3, 2)

        changed_flags = {"module-main": ("-DMODULE_ONLY=2",)}
        changed = build(module_main, changed_flags)
        changed_rows = check_commands(changed, changed_flags)
        assert changed["compile_hits"] == 1 and changed["compile_misses"] == 1 and counts(cc_log) == (4, 3)
        assert changed_rows["generated-common"]["object"] == second_rows["generated-common"]["object"]
        assert changed_rows["module-main"]["object"] != second_rows["module-main"]["object"]

        restored = build(module_main, source_flags)
        restored_rows = check_commands(restored, source_flags)
        assert restored["compile_hits"] == 2 and restored["compile_misses"] == 0 and counts(cc_log) == (4, 4)
        assert restored_rows["module-main"]["object"] == second_rows["module-main"]["object"]

        changed_global = build(module_main, source_flags, ["-DGLOBAL_FLAG=2"])
        check_commands(changed_global, source_flags, ["-DGLOBAL_FLAG=2"])
        assert changed_global["compile_hits"] == 0 and changed_global["compile_misses"] == 2
        assert counts(cc_log) == (6, 5)

        for label in ("unknown-label", str(module_main)):
            with patch.object(build_driver, "locate_cc") as choose, \
                    patch.object(build_driver, "compile_c_object") as compile_object, \
                    patch.object(build_driver, "link_c_objects") as link:
                try:
                    build_driver.build_c_executable(cfg, name="invalid-source-flags",
                        sources=[("module-main", module_main)], output=work / "invalid.exe",
                        object_dir=work / "invalid-objects", source_cflags={label: ("-DMODULE_ONLY=1",)})
                except ValueError as error:
                    assert str(error) == "unknown C source flag labels: " + label
                else:
                    raise AssertionError("unknown source flag label accepted: " + label)
                choose.assert_not_called()
                compile_object.assert_not_called()
                link.assert_not_called()
            assert not (work / "invalid-objects").exists() and counts(cc_log) == (6, 5)


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
print("int ouro_export_count(void){return 0;}")
print('const char *ouro_export_name(int i){switch(i){default:return "";}}')
print("ouro_v *ouro_export_value(int i){switch(i){default:return 0;}}")
print("int main(void) { return 0; }")
''', encoding="utf-8")
    entry = repo / "tool-test.ouro"
    imported = repo / "tool-import.ouro"
    entry.write_text('import "tool-import.ouro";\ndef main : Nat := 1;\n', encoding="utf-8")
    imported.write_text("def value : Nat := 1;\n", encoding="utf-8")
    env = isolated_env()
    env.update(CC=str(fakecc), FAKE_CC_LOG=str(cc_log), FAKE_EMIT_LOG=str(emit_log),
               OURO_CACHE="1", OURO_CCACHE="disabled", OURO_JOBS="1")

    def invoke(output="_build/tool-test", *, source=entry.name, options=(), failure=False):
        result = subprocess.run(
            [sys.executable, "scripts/native_tool_build.py", source, output,
             "--compiler", str(compiler), "--verbosity", "quiet", *options],
            cwd=repo, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        assert (result.returncode != 0) == failure, result.stdout
        return result

    invoke()
    from ourosmith.native import INPUT_FIELDS

    first_receipt = json.loads((repo / "_build/tool-test.build.json").read_text(encoding="utf-8"))
    assert set(first_receipt["inputs"]) == INPUT_FIELDS, "native tool build and its strict receipt consumer disagree"
    baseline = counts(cc_log)
    # Generated tool plus runtime, IO, entry point and frontend-link objects.
    assert baseline == (5, 1), baseline
    binary = repo / ("_build/tool-test.exe" if os.name == "nt" else "_build/tool-test")
    baseline_bytes = binary.read_bytes()
    baseline_time = binary.stat().st_mtime_ns
    invoke()
    invoke(options=("--check",))
    for spelling in (str(entry), str(repo) + "/./" + entry.name,
                     str(repo).replace("/", "\\") + "\\.\\" + entry.name):
        invoke(source=spelling, options=("--check",))
        invoke(source=spelling)
    manifest = (repo / "_build/tool-test.sources").read_text().splitlines()
    assert manifest[:2] == [imported.name, entry.name], manifest
    assert all(not Path(name).is_absolute() for name in manifest)
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

    cache = repo / "_cache/ouro/native-tools" / first_receipt["key"]
    (cache / ("tool.exe" if os.name == "nt" else "tool")).unlink()
    (cache / "tool.json").unlink()
    (cache / "tool.gen.json").unlink()
    installed = invoke()
    assert "installed-hit" in installed.stdout and counts(cc_log) == baseline
    # An imported installed image alone does not warm an absent content cache.
    before_prepare_emit = emit_log.read_text().count("emit")
    prepared = invoke("_build/memory/bin/tool-test")
    assert "miss" in prepared.stdout and counts(cc_log) == (baseline[0], baseline[1] + 1)
    assert emit_log.read_text().count("emit") == before_prepare_emit + 1
    baseline = counts(cc_log)
    env["FAKE_EMIT_FAIL"] = "1"
    invoke("_build/memory/fresh-suite/tool-test")
    env.pop("FAKE_EMIT_FAIL")
    assert counts(cc_log) == baseline, "prepared content cache must survive a missing measured image"

    if os.name == "nt":
        # A fake linker emits a shell script, not a PE resource image. Quality
        # publication must fail before replacing a previously installed tool.
        quality_entry = repo / "tools/fmt.ouro"
        quality_entry.write_text("def main : Nat := 1;\n", encoding="utf-8")
        installed_receipt = repo / "_build/tool-test.build.json"
        saved_receipt = installed_receipt.read_bytes()
        failed = invoke(source="tools/fmt.ouro", failure=True)
        assert "BUILD_TOOL: FAIL" in failed.stdout, failed.stdout
        assert binary.read_bytes() == baseline_bytes, "resource failure replaced the installed binary"
        assert installed_receipt.read_bytes() == saved_receipt, "resource failure published a success receipt"
        baseline = counts(cc_log)

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
    invoke(options=("--check",), failure=True)
    invoke()
    assert emit_log.read_text().count("emit") == before_emit, "valid emission must survive a malformed final tool receipt"
    rebuilt = json.loads((repo / "_build/tool-test.build.json").read_text(encoding="utf-8"))
    assert rebuilt["cache"] == "miss" and rebuilt["emission_cache"] == "hit"
    invoke(options=("--check",))

    before_seed = counts(cc_log)
    compiler.write_text(compiler.read_text() + "\n# changed seed binary\n", encoding="utf-8")
    invoke()
    assert counts(cc_log) == (before_seed[0] + 1, before_seed[1] + 1), "a changed seed must regenerate the tool"
    before_cc = counts(cc_log)
    fakecc.write_text(fakecc.read_text() + "\n# changed compiler, same version string\n", encoding="utf-8")
    invoke()
    assert counts(cc_log) == (before_cc[0] + 5, before_cc[1] + 1), "compiler content must invalidate common objects too"
    before_flags = counts(cc_log)
    invoke(options=("--opt", "O2"))
    assert counts(cc_log) == (before_flags[0] + 5, before_flags[1] + 1), "flags must invalidate the installed binary"
    invoke(options=("--opt", "O2"))
    invoke()
    assert counts(cc_log) == (before_flags[0] + 5, before_flags[1] + 1), "both flag variants should remain reusable"

    before_uncached = counts(cc_log)
    invoke(options=("--no-cache",))
    invoke(options=("--no-cache",))
    assert counts(cc_log) == (before_uncached[0] + 10, before_uncached[1] + 2)
    entry.write_text(entry.read_text() + "\n-- invalidate\n", encoding="utf-8")
    env["FAKE_EMIT_FAIL"] = "1"
    invoke(failure=True)
    invoke(options=("--check",), failure=True)


def test_native_tool_emission_resume(tmp: Path) -> None:
    repo = tmp / "repo_emission_resume"
    copy_repo(repo)
    fakecc = tmp / "resume-cc.py"
    cc_log, emit_log = tmp / "resume-cc.log", tmp / "resume-emit.log"
    write_fake_cc(fakecc)
    cc_text = fakecc.read_text(encoding="utf-8")
    rejection = '''if "-c" in args and os.environ.get("FAKE_CC_REJECT") == "1":
    raise SystemExit(23)

if "-c" in args:'''
    assert cc_text.count('if "-c" in args:') == 1
    fakecc.write_text(cc_text.replace('if "-c" in args:', rejection), encoding="utf-8")
    compiler = repo / "_build/c/resume-seed.py"
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
print("int ouro_export_count(void){return 0;}")
print('const char *ouro_export_name(int i){switch(i){default:return "";}}')
print("ouro_v *ouro_export_value(int i){switch(i){default:return 0;}}")
print("int main(void){return 0;}")
if os.environ.get("FAKE_EMIT_MUTATE"):
    path = Path(os.environ["FAKE_EMIT_MUTATE"])
    path.write_text(path.read_text() + "\\n-- mutation during emission\\n")
''', encoding="utf-8")
    dependencies = [repo / "resume-a.ouro", repo / "resume-b.ouro"]
    for index, dependency in enumerate(dependencies):
        dependency.write_text(f"def value_{index} : Nat := {index};\n", encoding="utf-8")
    entry = repo / "resume-tool.ouro"
    entry.write_text('import "resume-a.ouro"; import "resume-b.ouro"; def main : Nat := 1;\n', encoding="utf-8")
    driver = repo / "resume_driver.py"
    driver.write_text('''import os, sys
sys.path.insert(0, "scripts")
import native_tool_build as native
collect = native.frontend.collect_units_many
def units(roots, *, parse_bytes=None):
    groups = collect(roots, parse_bytes=parse_bytes)
    if os.environ.get("FAKE_EMIT_REORDER") == "1":
        return {root: [*reversed(paths[:-1]), paths[-1]] for root, paths in groups.items()}
    return groups
native.frontend.collect_units_many = units
if os.environ.get("FAKE_EMIT_MODE") == "1":
    native.EMIT_MODES["OURO_EMIT_IO_SHIMS"] = "0"
raise SystemExit(native.main())
''', encoding="utf-8")
    env = isolated_env()
    env.update(CC=str(fakecc), FAKE_CC_LOG=str(cc_log), FAKE_EMIT_LOG=str(emit_log),
               OURO_CACHE="1", OURO_CCACHE="disabled", OURO_JOBS="1", FAKE_CC_REJECT="1")
    output = "_build/resume-tool"
    binary = repo / (output + ".exe" if os.name == "nt" else output)
    receipt_path = repo / (output + ".build.json")
    cache_root = repo / "_cache/ouro/native-tools"

    def invoke(*options, failure=False):
        result = subprocess.run([sys.executable, str(driver), entry.name, output,
            "--compiler", str(compiler), "--verbosity", "quiet", *options], cwd=repo, env=env,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        assert (result.returncode != 0) == failure, result.stdout
        return result

    def emission_count():
        return emit_log.read_text(encoding="utf-8").count("emit")

    def expire_complete():
        receipt_path.unlink(missing_ok=True)
        for path in cache_root.glob("*/tool.json"):
            path.unlink()

    failed = invoke(failure=True)
    assert failed.returncode == 23 and counts(cc_log) == (0, 0), failed.stdout
    assert emission_count() == 1 and not receipt_path.exists() and not binary.exists()
    emissions = list(cache_root.glob("*/tool.gen.json"))
    assert len(emissions) == 1
    emission_path = emissions[0]
    directory, generated = emission_path.parent, emission_path.with_suffix(".c")
    from repo_support import sha256_file

    emission = json.loads(emission_path.read_text(encoding="utf-8"))
    assert emission["kind"] == "ouro.frontend-cache-output.v1"
    assert isinstance(emission["input_key"], str) and emission["output_sha256"] == sha256_file(generated)
    assert not (directory / "tool.json").exists()
    original_emission = emission_path.read_bytes()
    invoke("--check", failure=True)
    assert emission_path.read_bytes() == original_emission and emission_count() == 1 and counts(cc_log) == (0, 0)
    shards = json.loads((directory / "generated-c-shards-report.json").read_text(encoding="utf-8"))
    shard = repo / next(row["path"] for row in shards["shards"] if row["compile"])
    shard_bytes = shard.read_bytes()
    shard.write_bytes(shard_bytes + b"\ncorrupt fixture\n")
    env.pop("FAKE_CC_REJECT")
    invoke()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["cache"] == "miss" and receipt["emission_cache"] == "hit"
    assert emission_count() == 1 and counts(cc_log) == (5, 1)
    assert shard.read_bytes() == shard_bytes and emission_path.read_bytes() == original_emission
    assert receipt["generated_sha256"] == sha256_file(generated)
    assert receipt["build"]["generated_c_shards"]["manifest_cache"] == "miss"
    invoke("--check")
    checked = subprocess.run([sys.executable, "-c",
        "import sys; from pathlib import Path; sys.path.insert(0,'scripts'); "
        "from ourosmith.native import receipt_for; "
        "record,_,_=receipt_for(Path(sys.argv[1]),sys.argv[2],Path(sys.argv[3])); "
        "assert record['cache']=='miss' and record['emission_cache']=='hit'",
        str(binary), entry.name, str(compiler)], cwd=repo, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    assert checked.returncode == 0, checked.stdout

    damaged_metadata = ["{", "[]", "{}", json.dumps({**emission, "kind": "wrong"}),
                        json.dumps({**emission, "input_key": "0" * 64}),
                        json.dumps({**emission, "output_sha256": "0" * 64}),
                        json.dumps({**emission, "output_sha256": 1})]
    for damaged in damaged_metadata:
        expire_complete()
        emission_path.write_text(damaged, encoding="utf-8")
        before = emission_count()
        invoke()
        current = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert emission_count() == before + 1 and current["emission_cache"] == "miss"
        assert current["inputs"] == receipt["inputs"] and current["key"] == receipt["key"]
    for damage in (b"\nchanged generated fixture\n", None):
        expire_complete()
        if damage is None:
            generated.unlink()
        else:
            generated.write_bytes(generated.read_bytes() + damage)
        before = emission_count()
        invoke()
        assert emission_count() == before + 1

    expire_complete()
    valid = json.loads(emission_path.read_text(encoding="utf-8"))
    malformed = generated.read_text(encoding="utf-8").replace("return 0;}", "return 1;}", 1)
    generated.write_text(malformed, encoding="utf-8")
    emission_path.write_text(json.dumps({**valid, "output_sha256": sha256_file(generated)}), encoding="utf-8")
    before = emission_count()
    invoke()
    assert emission_count() == before + 1, "matching output hash cannot bypass installed export guards"

    probes = (("ordered units", (), {"FAKE_EMIT_REORDER": "1"}),
              ("fuel", ("--fuel", "60001"), {}),
              ("flags", ("--opt", "O2"), {}),
              ("configuration", (), {"OURO_JOBS": "2"}),
              ("include environment", (), {"CPATH": "resume-fixture-include"}),
              ("emission transport", (), {"WSLENV": "RESUME_FIXTURE"}),
              ("emission mode", (), {"FAKE_EMIT_MODE": "1"}))
    for label, options, environment in probes:
        expire_complete()
        before = emission_count()
        with patch.dict(env, environment):
            invoke(*options)
            current = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert emission_count() == before + 1 and current["emission_cache"] == "miss", label
        if label in {"ordered units", "configuration", "emission transport", "emission mode"}:
            assert current["key"] == receipt["key"], label
        expire_complete()
        invoke()

    for path in (dependencies[0], compiler, fakecc, repo / "scripts/pack_frontend.py",
                 repo / "runtime/frontend_link.c", repo / "runtime/ouro_rt.h"):
        original = path.read_bytes()
        suffix = b"\n/* changed emission input */\n" if path.suffix in {".c", ".h"} else b"\n# changed emission input\n" \
            if path.suffix == ".py" else b"\n-- changed emission input\n"
        try:
            path.write_bytes(original + suffix)
            expire_complete()
            before = emission_count()
            invoke()
            assert emission_count() == before + 1, path
        finally:
            path.write_bytes(original)
        expire_complete()
        invoke()

    old_receipt, old_binary = receipt_path.read_bytes(), binary.read_bytes()
    before_receipts = {str(path): path.read_bytes() for path in cache_root.glob("*/tool.gen.json")}
    with patch.dict(env, {"FAKE_EMIT_FAIL": "1"}):
        failed = invoke("--fuel", "60002", failure=True)
    assert "emit failed rc=19" in failed.stdout
    assert {str(path): path.read_bytes() for path in cache_root.glob("*/tool.gen.json")} == before_receipts
    assert receipt_path.read_bytes() == old_receipt and binary.read_bytes() == old_binary
    original = dependencies[0].read_bytes()
    before_compile = counts(cc_log)
    try:
        with patch.dict(env, {"FAKE_EMIT_MUTATE": dependencies[0].name}):
            failed = invoke("--fuel", "60003", failure=True)
        assert "configuration changed during emission" in failed.stdout
        assert counts(cc_log) == before_compile
        assert {str(path): path.read_bytes() for path in cache_root.glob("*/tool.gen.json")} == before_receipts
        assert receipt_path.read_bytes() == old_receipt and binary.read_bytes() == old_binary
    finally:
        dependencies[0].write_bytes(original)
    before = emission_count()
    invoke("--no-cache")
    invoke("--no-cache")
    assert emission_count() == before + 2
    assert {str(path): path.read_bytes() for path in cache_root.glob("*/tool.gen.json")} == before_receipts


def test_native_tool_shard_cache(tmp: Path) -> None:
    """The real shard/object owners must gate fake-compiler preparation reuse."""
    repo = tmp / "repo_tool_shards"
    copy_repo(repo)
    fakecc, cc_log = tmp / "shard-tool-cc.py", tmp / "shard-tool-cc.log"
    write_fake_cc(fakecc)
    compiler = repo / "_build/c/ouro1.py"
    compiler.parent.mkdir(parents=True)
    compiler.write_text('''import os, sys
print('#include "ouro_rt.h"')
if os.environ.get("FAKE_SHARD_BAD_PRELUDE") == "1":
    print("#define UNKNOWN_PRELUDE 1")
for n in range(1, 514):
    print("static ouro_v *ouro_g%d(void);" % n)
for n in range(1, 514):
    print("static ouro_v *ouro_f%d_(ouro_env *env,ouro_v *arg){(void)env;return arg;}" % n)
    print("static ouro_v *ouro_c%d;" % n)
    print("static ouro_v *ouro_g%d(void){if(ouro_c%d==0)ouro_c%d=ouro_clos(ouro_f%d_,0);return ouro_c%d;}" % (n,n,n,n,n))
print("int ouro_export_count(void){return 1;}")
print('const char *ouro_export_name(int i){switch(i){case 0:return "value";default:return "";}}')
print("ouro_v *ouro_export_value(int i){switch(i){case 0:return ouro_g513();default:return 0;}}")
''', encoding="utf-8")
    entry = repo / "shard-tool.ouro"
    (repo / "shard-dependency.ouro").write_text("def dependency : Nat := 1;\n", encoding="utf-8")
    entry.write_text('import "shard-dependency.ouro"; def main : Nat := 1;\n', encoding="utf-8")
    env = isolated_env()
    env.update(CC=str(fakecc), FAKE_CC_LOG=str(cc_log), OURO_CACHE="1", OURO_CCACHE="disabled", OURO_JOBS="1")
    output = "_build/shard-tool"
    binary = repo / (output + ".exe" if os.name == "nt" else output)
    receipt_path = repo / (output + ".build.json")

    def invoke(*options, failure=False):
        result = subprocess.run([sys.executable, "scripts/native_tool_build.py", entry.name, output,
            "--compiler", str(compiler), "--verbosity", "quiet", *options], cwd=repo, env=env,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        assert (result.returncode != 0) == failure, result.stdout
        return result

    invoke()
    first = json.loads(receipt_path.read_text(encoding="utf-8"))
    from ourosmith.native import INPUT_FIELDS
    assert set(first["inputs"]) == INPUT_FIELDS
    assert "scripts/generated_c_shards.py" in first["inputs"]["sources"]
    manifest = (repo / (output + ".sources")).read_text(encoding="utf-8").splitlines()
    assert manifest[:2] == ["shard-dependency.ouro", entry.name], manifest
    shards = first["build"]["generated_c_shards"]
    assert shards["settings"]["backend_group_size"] == 256 and shards["settings"]["backend_export_suffix"] == ""
    assert shards["summary"]["compile_shards"] == 4 and counts(cc_log) == (8, 1), first
    assert first["build"]["sources"][-4:][0]["source"] == "runtime/ouro_rt.c"
    baseline = counts(cc_log)
    invoke("--check")
    assert "installed-hit" in invoke().stdout and counts(cc_log) == baseline
    original_receipt = receipt_path.read_bytes()
    for cache_value in (True, 1, "unknown"):
        forged = json.loads(original_receipt)
        forged["cache"] = cache_value
        receipt_path.write_text(json.dumps(forged), encoding="utf-8")
        forged_bytes = receipt_path.read_bytes()
        invoke("--check", failure=True)
        assert counts(cc_log) == baseline and receipt_path.read_bytes() == forged_bytes
    forged = json.loads(original_receipt)
    forged["build"]["generated_c_shards"]["settings"]["backend_only"] = 1
    receipt_path.write_text(json.dumps(forged), encoding="utf-8")
    forged_bytes = receipt_path.read_bytes()
    invoke("--check", failure=True)
    assert counts(cc_log) == baseline and receipt_path.read_bytes() == forged_bytes
    receipt_path.write_bytes(original_receipt)
    invoke("--check")
    cache = repo / "_cache/ouro/native-tools" / first["key"]
    paths = [cache / "tool.gen.c", repo / shards["manifest_path"],
             *(repo / row["path"] for row in shards["shards"]),
             *(repo / first["build"]["sources"][0][name] for name in ("object", "depfile", "cmdhash")),
             repo / first["build"]["link"]["cmdhash"]]
    for path in paths:
        original = path.read_bytes()
        path.write_bytes(original + b"\ncorrupt\n")
        prior_receipt, prior_image = receipt_path.read_bytes(), binary.read_bytes()
        invoke("--check", failure=True)
        assert counts(cc_log) == baseline and path.read_bytes() == original + b"\ncorrupt\n"
        assert receipt_path.read_bytes() == prior_receipt and binary.read_bytes() == prior_image
        path.write_bytes(original)
        invoke("--check")
    binary.unlink()
    assert "hit" in invoke().stdout and counts(cc_log) == baseline
    corrupt = paths[2]
    corrupt.write_bytes(corrupt.read_bytes() + b"\ncorrupt\n")
    binary.unlink()
    rebuilt = invoke()
    assert "BUILD_TOOL_CACHE: miss " in rebuilt.stdout and "BUILD_TOOL: OK " in rebuilt.stdout
    assert binary.is_file() and receipt_path.is_file()
    invoke("--check")
    old_key = json.loads(receipt_path.read_text(encoding="utf-8"))["key"]
    generator = repo / "scripts/generated_c_shards.py"
    saved = generator.stat()
    generator.write_text(generator.read_text(encoding="utf-8") + "\n# source-hash regression\n", encoding="utf-8")
    os.utime(generator, ns=(saved.st_atime_ns, saved.st_mtime_ns))
    invoke("--check", failure=True)
    invoke()
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["key"] != old_key
    prior_receipt, prior_image = receipt_path.read_bytes(), binary.read_bytes()
    baseline = counts(cc_log)
    env["FAKE_SHARD_BAD_PRELUDE"] = "1"
    failed = invoke("--no-cache", failure=True)
    assert "unsupported generated backend prelude" in failed.stdout and counts(cc_log) == baseline
    assert receipt_path.read_bytes() == prior_receipt and binary.read_bytes() == prior_image


def test_native_tool_companion(tmp: Path) -> None:
    # Keep nested shard paths within the Windows path limit.
    repo = tmp / "comp"
    copy_repo(repo)
    fakecc = tmp / "companion-cc.py"
    write_fake_cc(fakecc)
    compiler = repo / "_build/c/ouro1.py"
    compiler.parent.mkdir(parents=True)
    # Export only declarations whose owners belong to this tool closure.
    compiler.write_text('''import hashlib, os, sys
sys.path.insert(0, "scripts")
import native_tool_build as native
from pathlib import Path
from scoped_host_export_routes import FLAT_HOST_EXPORT_ROUTES
from frontend_lower_lookup_test import append_helpers, elem_helpers
with Path(os.environ["FAKE_EMIT_LOG"]).open("a") as log:
    log.write("emit\\n")
source = "".join(Path(p).read_text() for p in sys.argv if p.endswith(".ouro"))
pure_arities = {"module_members": 7, "module_owned_exports": 2,
                "module_shadow_exports": 2, "module_unique_exports": 1,
                "module_maps_for": 9, "module_rewrite_decls_with_opens_pure": 10,
                "module_rewrite_decl_pure": 10, "module_scope_maps": 4, "module_bare_ctors": 5,
                "module_invalid_maps": 3}
units = [sys.argv[i + 1].replace("\\\\", "/")
         for i, token in enumerate(sys.argv[:-1]) if token == "--unit"]
if "compiler/source_name_index.ouro" in units:
    pure_arities["source_name_compare_scope"] = 2
if native.packer.ELEM_OWNER in units:
    pure_arities["elem_scope"] = 3
if "compiler/module_registry.ouro" in units:
    pure_arities.update(module_rewrite_unit_pure=7, module_maps_for_cached_pure=9,
                        module_rewrite_unit_cached_pure=7)
if "compiler/module_names_base.ouro" in units:
    pure_arities.update(lookup=3, eqNat=2, module_lookup=0)
if native.packer.LOWER_LOCAL_LOOKUP_OWNER in units:
    pure_arities["lookup_local"] = 2
value_routes = (*native.packer.PRELUDE_ARITHMETIC_ROUTES,
                native.packer.PRELUDE_LIST_LENGTH_ROUTE[:2],
                native.packer.PRELUDE_LIST_APPEND_ROUTE[:2],
                ("orb", native.packer.ELEM_ORB_OWNER),
                ("lookup_local", native.packer.LOWER_LOCAL_LOOKUP_OWNER))
for name, owner in value_routes:
    if owner in units:
        pure_arities[name] = native.packer.PRELUDE_LIST_LENGTH_ROUTE[2] if name == "length" else 2
names = []
labels = []
for alias, source_name, owners in FLAT_HOST_EXPORT_ROUTES:
    present = [owner for owner in owners if owner in units]
    if not present:
        continue
    assert len(present) == 1
    owner = present[0]
    names.append(alias)
    labels.append(source_name if owner == units[-1]
                  else f"_ouro_m_{units.index(owner)}_{source_name}")
if "compiler/module_names_base.ouro" in units:
    for name, owner in (("lookup", "std/listx.ouro"), ("eqNat", "compiler/base.ouro"),
                        ("module_lookup", "compiler/module_names_base.ouro")):
        names.append(name)
        labels.append(name if owner == units[-1] else f"_ouro_m_{units.index(owner)}_{name}")
for name, owner in value_routes:
    if owner in units and name not in names:
        names.append(name)
        labels.append(name if owner == units[-1] else f"_ouro_m_{units.index(owner)}_{name}")
prototypes = []
getters = []
exports = []
values = []
for index, name in enumerate(names):
    gid = index + 10
    prototypes.append(f"static ouro_v *ouro_g{gid}(void);")
    if name == "append":
        getters.append(append_helpers(gid))
    elif name == "elem_scope":
        getters.append(elem_helpers(gid, 10 + names.index("orb")))
    elif name in pure_arities:
        arity = pure_arities[name]
        for step in reversed(range(arity)):
            suffix = "0_" * step + f"{gid}_"
            result = f"ouro_clos(ouro_f0_{suffix},env)" if step + 1 < arity else "arg"
            getters.append(f"static ouro_v *ouro_f{suffix}(ouro_env *env0,ouro_v *arg){{"
                           f"ouro_env *env=ouro_cons(arg,env0);(void)env;return {result};}}")
    else:
        getters.append(f"static ouro_v *ouro_f{gid}_(ouro_env *env,ouro_v *arg){{(void)env;return arg;}}")
    initializer = (f"ouro_app(ouro_g{10 + names.index('lookup')}(),ouro_g{10 + names.index('eqNat')}())"
                   if name == "module_lookup" else f"ouro_fix(ouro_f{gid}_,env)"
                   if name in ("append", "source_name_compare_scope") else f"ouro_clos(ouro_f{gid}_,env)")
    getters.append(
        f"static ouro_v *ouro_c{gid};\\n"
        f"static ouro_v *ouro_g{gid}(void){{ouro_env *env=0;(void)env;"
        f"if(ouro_c{gid}==0){{ouro_static_begin();"
        f"ouro_c{gid}={initializer};"
        f"ouro_static_end();}}return ouro_c{gid};}}")
    exports.append(f'case {index}: return "{labels[index]}";')
    values.append(f"case {index}: return ouro_g{gid}();")
print('#include "ouro_rt.h"')
print("\\n".join([*prototypes, *getters,
      "/* " + hashlib.sha256(source.encode()).hexdigest() + " */",
      f"int ouro_export_count(void){{return {len(names)};}}",
      'const char *ouro_export_name(int i){switch(i){', *exports,
      'default: return "";}}',
      'ouro_v *ouro_export_value(int i){switch(i){', *values,
      'default: return 0;}}']))
''', encoding="utf-8")
    # Manifest embedding needs a real PE linker; the companion current/rebuild
    # logic is orthogonal and is covered here with plain binaries.
    driver = repo / "companion_driver.py"
    driver.write_text('''import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "scripts")
import ouro_build as build
import native_tool_build as native
from repo_support import configure_native_stack

native.WINDOWS_UTF8_ENTRIES = frozenset()
parser = argparse.ArgumentParser()
parser.add_argument("entry")
parser.add_argument("output", type=Path)
parser.add_argument("--compiler", type=Path, required=True)
parser.add_argument("--fuel", type=int, default=60000)
parser.add_argument("--check", action="store_true")
parser.add_argument("--prepared-companions", type=Path)
build.add_common(parser)
args = parser.parse_args()
try:
    configure_native_stack()
    report = native.build_tool(args)
except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
    print(f"BUILD_TOOL: FAIL {exc}", file=sys.stderr)
    raise SystemExit(1)
raise SystemExit(int(args.check and not report["current"]))
''', encoding="utf-8")
    env = isolated_env()
    env.update(CC=str(fakecc), FAKE_CC_LOG=str(tmp / "companion-cc.log"),
               FAKE_EMIT_LOG=str(tmp / "companion-emit.log"),
               OURO_CACHE="1", OURO_CACHE_DIR="c", OURO_CCACHE="disabled", OURO_JOBS="1")
    suffix = ".exe" if os.name == "nt" else ""
    parent_out = "_build/companion-fix"
    parent_bin = repo / (parent_out + suffix)
    # Receipts and manifests bind to the pre-suffix output spelling.
    parent_receipt = repo / (parent_out + ".build.json")
    companion_bin = repo / ("_build/ouro-fix-check" + suffix)
    companion_receipt = repo / "_build/ouro-fix-check.build.json"

    def invoke(*options, failure=False, entry="tools/fix/main.ouro", output=parent_out):
        result = subprocess.run(
            [sys.executable, "companion_driver.py", entry, str(output),
             "--compiler", str(compiler), "--verbosity", "quiet", *options],
            cwd=repo, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        assert (result.returncode != 0) == failure, result.stdout
        return result

    invoke()
    assert parent_bin.is_file() and companion_bin.is_file()
    assert parent_receipt.is_file() and companion_receipt.is_file()
    parent_inputs = json.loads(parent_receipt.read_text(encoding="utf-8"))["inputs"]
    assert "tools/fix/check_main.ouro" in parent_inputs["sources"], \
        "parent receipt must cover the companion closure"
    invoke("--check")

    def expect_rebuild():
        invoke("--check", failure=True)
        invoke()
        assert companion_bin.is_file() and companion_receipt.is_file()
        invoke("--check")

    companion_bin.unlink()
    expect_rebuild()
    companion_receipt.write_text("malformed", encoding="utf-8")
    expect_rebuild()
    companion_bin.write_bytes(b"corrupt companion")
    expect_rebuild()
    companion_receipt.unlink()
    expect_rebuild()

    worker = repo / "tools/fix/check_main.ouro"
    worker.write_text(worker.read_text(encoding="utf-8") + "\n-- companion change\n", encoding="utf-8")
    invoke("--check", failure=True)
    invoke()
    invoke("--check")

    for policy in ("--cache", "--no-cache"):
        isolated = repo / "_build" / policy.removeprefix("--")
        prepared = isolated / "proofs"
        fix, fmt, check = (isolated / name for name in ("ouro-fix", "ouro-fmt", "ouro-fix-check"))
        mode = (policy, "--prepared-companions", str(prepared))
        missing = invoke(*mode, output=fix, failure=True)
        assert "prepared companion evidence differs: tools/fix/check_main.ouro" in missing.stdout
        invoke(*mode, output=check, entry="tools/fix/check_main.ouro")
        receipt = Path(str(check) + ".build.json")
        saved = receipt.read_bytes(), receipt.stat().st_mtime_ns
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            fix_result = pool.submit(invoke, *mode, output=fix)
            fmt_result = pool.submit(invoke, *mode, output=fmt, entry="tools/fmt.ouro")
            fix_result.result()
            fmt_result.result()
        assert saved == (receipt.read_bytes(), receipt.stat().st_mtime_ns)
        manifest = json.loads(saved[0])["build"]["generated_c_shards"]["manifest_path"]
        (repo / manifest).parent.parent.joinpath("tool.gen.c").write_bytes(b"corrupt generated companion")
        rejected = invoke(*mode, output=fix, failure=True)
        assert "prepared companion evidence differs: tools/fix/check_main.ouro" in rejected.stdout
        assert saved == (receipt.read_bytes(), receipt.stat().st_mtime_ns)


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
    for invalid in ([], [native.API, native.API], ["../outside.ouro", native.API]):
        closure = {native.API: invalid, native.PROBE: [native.PROBE]}
        with patch.object(native, "capture_unit_inputs", return_value=(closure, {})):
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
    expected = ("valid", "diagnostic-strings", "valid-quiet", "uninitialized", "bad-return", "mir-program-context", "mir-flow-context",
                "codegen-program-context", "mir-phase-errors", "mir-phase-nested", "mir-reachability-rounds", "mir-flow-rounds", "lower-raw-order", "lower-raw-left", "lower-survivors",
                "pe-byte-large", "pe-byte-errors", "pe-byte-context", "pe-patch-context", "lower-bad-result", "lower-bad-result-quiet",
                "lower-bad-chunk", "lower-bad-contracts", "caller-output", "retained-result",
                "typed-failure", "prepass-failure-order", "nested-context", "allocation-context", "shared-parent-spine",
                "wrapped-context", "recheck-scale",
                "recheck-retained", "recheck-late-invalid", "recheck-missing-bodies", "recheck-zero-fuel",
                "metadata-parity", "fallback-forward", "root-parity", "root-clear-context",
                "lower-contract-context", "check-module-context", "pe-operation-context",
                "mir-bounds-outcomes", "mir-bounds-context", "mir-function-partial", "mir-function-context", "phase-timing",
                "all", "order", "survivors", "allocation", "extended", "thunk-cycle", "outer-mark", "perm0",
                "invalid-arity0", "invalid-arity4", "invalid-arity8", "prefix2", "prefix3")
    assert len(cases) == len(expected) and tuple(case[1][0] for case in host.probe_cases()) == expected
    assert host.HOST_MAINS["module-pure-scope-selftest"] == "runtime/module_pure_scope_selftest.c"
    assert "runtime/module_pure_scope_selftest.c" in host.SUPERVISOR_INPUTS
    for mode in ("all", "order", "survivors", "allocation", "extended", "thunk-cycle", "outer-mark", "perm0"):
        assert cases[mode] == ("module-pure-scope-selftest", [mode], 0,
                               f"MODULE_PURE_SCOPE_SELFTEST: passed {mode}\n", "")
        success = RunResult("ok", 0, f"MODULE_PURE_SCOPE_SELFTEST: passed {mode}\n", "", 0, 0)
        host.verify_probe(success, cases[mode])
        for invalid_probe in (replace(success, status="timeout"), replace(success, status="memory"),
                              replace(success, status="skipped"), replace(success, returncode=1),
                              replace(success, stdout=""), replace(success, stdout=success.stdout + "unexpected\n"),
                              replace(success, stderr="unexpected\n")):
            try:
                host.verify_probe(invalid_probe, cases[mode])
            except ValueError:
                pass
            else:
                raise AssertionError(f"{mode}: invalid module pure scope protocol accepted")
    for mode in ("invalid-arity0", "invalid-arity4", "invalid-arity8"):
        diagnostic = "ouro_rt: invalid module pure scope arity or callable\n"
        assert cases[mode] == ("module-pure-scope-selftest", [mode], 1, "", re.escape(diagnostic))
        refusal = RunResult("ok", 1, "", diagnostic, 0, 0)
        host.verify_probe(refusal, cases[mode])
        for invalid_probe in (replace(refusal, status="timeout"), replace(refusal, status="memory"),
                              replace(refusal, status="skipped"), replace(refusal, returncode=0),
                              replace(refusal, stdout="MODULE_PURE_SCOPE_SELFTEST: passed\n"),
                              replace(refusal, stderr=""), replace(refusal, stderr=diagnostic + "unexpected\n")):
            try:
                host.verify_probe(invalid_probe, cases[mode])
            except ValueError:
                pass
            else:
                raise AssertionError(f"{mode}: invalid module pure scope refusal accepted")
    for mode in ("prefix2", "prefix3"):
        assert cases[mode] == ("module-pure-scope-selftest", [mode], 0,
                               f"MODULE_PURE_SCOPE_SELFTEST: passed {mode}\n", "")
        success = RunResult("ok", 0, f"MODULE_PURE_SCOPE_SELFTEST: passed {mode}\n", "", 0, 0)
        host.verify_probe(success, cases[mode])
        for invalid_probe in (replace(success, status="timeout"), replace(success, status="memory"),
                              replace(success, status="skipped"), replace(success, returncode=1),
                              replace(success, stdout=""), replace(success, stdout=success.stdout + "unexpected\n"),
                              replace(success, stderr="unexpected\n")):
            try:
                host.verify_probe(invalid_probe, cases[mode])
            except ValueError:
                pass
            else:
                raise AssertionError(f"{mode}: invalid module pure scope protocol accepted")
    timing = RunResult("ok", 0, "N1_HOST_TIMING: passed phase-timing\n",
                       "n1-host: timing phase=sample elapsed_s=1.250\n"
                       "n1-host: timing phase=start-unavailable elapsed_s=unavailable\n"
                       "n1-host: timing phase=sample-unavailable elapsed_s=unavailable\n"
                       "n1-host: timing phase=backward elapsed_s=unavailable\n", 0, 0)
    host.verify_probe(timing, cases["phase-timing"])
    for invalid_timing in (replace(timing, status="timeout"), replace(timing, returncode=1),
                           replace(timing, stdout=""), replace(timing, stderr=""),
                           replace(timing, stderr=timing.stderr.replace("elapsed_s=unavailable", "elapsed_s=0.000")),
                           replace(timing, stderr=timing.stderr + "unexpected\n")):
        try:
            host.verify_probe(invalid_timing, cases["phase-timing"])
        except ValueError:
            pass
        else:
            raise AssertionError("invalid phase timing protocol accepted")
    for mode, prefix in (("metadata-parity", "FRONTEND_CODEGEN_META"),
                         ("fallback-forward", "FRONTEND_CODEGEN_SELFTEST"),
                         ("root-parity", "FRONTEND_CODEGEN_SELFTEST"),
                         ("root-clear-context", "FRONTEND_CODEGEN_SELFTEST"),
                         ("lower-contract-context", "FRONTEND_CODEGEN_SELFTEST"),
                         ("check-module-context", "FRONTEND_CODEGEN_SELFTEST"),
                         ("pe-operation-context", "FRONTEND_CODEGEN_SELFTEST"),
                         ("mir-bounds-outcomes", "FRONTEND_CODEGEN_SELFTEST"),
                         ("mir-bounds-context", "FRONTEND_CODEGEN_SELFTEST"),
                         ("mir-function-partial", "FRONTEND_CODEGEN_SELFTEST"),
                         ("mir-function-context", "FRONTEND_CODEGEN_SELFTEST")):
        success = RunResult("ok", 0, f"{prefix}: passed {mode}\n", "", 0, 0)
        host.verify_probe(success, cases[mode])
        for invalid_probe in (replace(success, status="timeout"), replace(success, returncode=1),
                              replace(success, stdout=""), replace(success, stderr="unexpected\n")):
            try:
                host.verify_probe(invalid_probe, cases[mode])
            except ValueError:
                pass
            else:
                raise AssertionError(f"{mode}: invalid host protocol accepted")
    quiet = RunResult("ok", 0, "N1_HOST_MIR: emitted valid-quiet\n",
                      "n1-host: mir functions=1 live=1\nn1-host: mir-check live=1\n"
                      "n1-host: gc-infer live=1\nn1-host: annotate live=1\n"
                      "n1-host: codegen live=1\n", 0, 0)
    host.verify_probe(quiet, cases["valid-quiet"])
    quiet_failure = RunResult("ok", 2, "", "n1-host: raw returned an invalid lowering result\n", 0, 0)
    host.verify_probe(quiet_failure, cases["lower-bad-result-quiet"])
    raw = RunResult("ok", 0, "N1_HOST_LOWER: passed lower-raw-order\n", "", 0, 0)
    host.verify_probe(raw, cases["lower-raw-order"])
    malformed = RunResult("ok", 2, "", "n1-host: raw returned an invalid list\n", 0, 0)
    host.verify_probe(malformed, cases["lower-bad-chunk"])
    context = RunResult("ok", 0, "N1_HOST_CONTEXT: passed mir-flow-context\n", "", 0, 0)
    host.verify_probe(context, cases["mir-flow-context"])
    reachability = replace(context, stdout="N1_HOST_CONTEXT: passed mir-reachability-rounds\n")
    host.verify_probe(reachability, cases["mir-reachability-rounds"])
    flow = replace(context, stdout="N1_HOST_CONTEXT: passed mir-flow-rounds\n")
    host.verify_probe(flow, cases["mir-flow-rounds"])
    pe = RunResult("ok", 0, "N1_HOST_PE: passed pe-byte-large\n", "", 0, 0)
    for mode in ("pe-byte-large", "pe-byte-errors", "pe-byte-context", "pe-patch-context"):
        host.verify_probe(replace(pe, stdout=f"N1_HOST_PE: passed {mode}\n"), cases[mode])
    typed = RunResult("ok", 0, "FRONTEND_LINK_SELFTEST: passed typed-failure\n",
                      "probe.ouro: type mismatch in wrong\n"
                      "probe.ouro: OURO-LIST-001: list literal without known List A context in wrong (surface)\n"
                      "  hint: Add a declaration/ascription such as : List Nat.\n", 0, 0)
    host.verify_probe(typed, cases["typed-failure"])
    shared = replace(typed, stdout="FRONTEND_LINK_SELFTEST: passed shared-parent-spine\n", stderr="")
    host.verify_probe(shared, cases["shared-parent-spine"])
    wrapped = replace(shared, stdout="FRONTEND_LINK_SELFTEST: passed wrapped-context\n")
    host.verify_probe(wrapped, cases["wrapped-context"])
    rejected = RunResult("ok", 1, "", "n1-host: mir functions=1 live=600\n"
                         "n1-host: mir-check live=600\nn1-host: mir-check failed tag=0 n=1 live=31704\n"
                         "n1-host: mir:return\n", 0, 0)
    host.verify_probe(rejected, cases["bad-return"])
    invalid = [(replace(quiet, stderr=quiet.stderr + "n1-host: gc-check-c functions=1\n"), "valid-quiet"),
               (replace(quiet, returncode=1), "valid-quiet"),
               (replace(quiet, stdout=""), "valid-quiet"),
               (replace(quiet_failure, stderr=""), "lower-bad-result-quiet"),
               (replace(quiet_failure, returncode=0), "lower-bad-result-quiet"),
               (replace(raw, stdout=""), "lower-raw-order"),
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
               (replace(flow, status="timeout"), "mir-flow-rounds"),
               (replace(flow, returncode=1), "mir-flow-rounds"),
               (replace(flow, stdout=""), "mir-flow-rounds"),
               (replace(flow, stderr="unexpected\n"), "mir-flow-rounds"),
               (replace(pe, status="timeout"), "pe-byte-large"),
               (replace(pe, returncode=1), "pe-byte-large"),
               (replace(pe, stdout=""), "pe-byte-large"),
               (replace(pe, stdout=pe.stdout + "unexpected\n"), "pe-byte-large"),
               (replace(pe, stderr="unexpected\n"), "pe-byte-large"),
               (pe, "pe-byte-errors"),
               (pe, "pe-byte-context"),
               (pe, "pe-patch-context"),
               (replace(pe, stdout="N1_HOST_PE: passed pe-patch-context\n", status="timeout"), "pe-patch-context"),
               (replace(pe, stdout="N1_HOST_PE: passed pe-patch-context\n", returncode=1), "pe-patch-context"),
               (replace(pe, stdout="N1_HOST_PE: passed pe-patch-context\n", stderr="unexpected\n"), "pe-patch-context"),
               (replace(typed, stderr=""), "typed-failure"),
               (replace(typed, stderr="probe.ouro: type mismatch in wrong\n"), "typed-failure"),
               (replace(shared, stdout=""), "shared-parent-spine"),
               (replace(shared, returncode=1), "shared-parent-spine"),
               (replace(shared, status="timeout"), "shared-parent-spine"),
               (replace(wrapped, stdout=""), "wrapped-context"),
               (replace(wrapped, returncode=1), "wrapped-context"),
               (replace(wrapped, status="timeout"), "wrapped-context"),
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
    generated.write_text('#include "ouro_rt.h"\nstatic ouro_v *ouro_g1(void);\n'
                         'static ouro_v *ouro_g1(void){return 0;}\n'
                         'int ouro_export_count(void){return 1;}\n'
                         'const char *ouro_export_name(int i){(void)i;return "fixture";}\n'
                         'ouro_v *ouro_export_value(int i){(void)i;return ouro_g1();}\n', encoding="utf-8")
    assert host.BACKEND_GROUP_SIZE == 256 and "scripts/generated_c_shards.py" in host.SUPERVISOR_INPUTS
    _sources, shards = host.build.GCS.materialize_generated_c_shards(
        frontend_c=None, backend_c=generated, out_dir=work / "generated-c-shards", label_prefix="host-fixture",
        backend_group_size=host.BACKEND_GROUP_SIZE, backend_export_suffix="")
    manifest = work / "generated-c-shards/generated-c-shards.manifest.json"
    report = {"kind": host.KIND + ".build", "generated_sha256": host.sha256_file(generated), "binaries": {},
              "generated_c_shards": shards, "shard_manifest_sha256": host.sha256_file(manifest)}
    for name in host.HOST_MAINS:
        binary = host.executable(work, name)
        binary.write_bytes(b"current linked fixture")
        report["binaries"][name] = {"sha256": host.sha256_file(binary)}
    host.verify_artifacts(work, report)
    incomplete = {**report, "binaries": {name: row for name, row in report["binaries"].items()
                                       if name != "module-pure-scope-selftest"}}
    try:
        host.verify_artifacts(work, incomplete)
    except ValueError:
        pass
    else:
        raise AssertionError("missing module pure scope executable accepted")
    for changed in (work / "generated-c-shards/backend_u__shards.h", manifest, generated):
        original = changed.read_bytes()
        changed.write_bytes(original + b"\n/* changed artifact */\n")
        try:
            host.verify_artifacts(work, report)
        except ValueError:
            pass
        else:
            raise AssertionError("changed generated host artifact accepted: " + str(changed))
        finally:
            changed.write_bytes(original)
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


def test_frontend_host_snapshot_reuses_imports(tmp: Path) -> None:
    import argparse
    from hashlib import sha256
    import io
    from pathlib import PureWindowsPath

    import frontend_host_suite as host
    import selfhost_module_cache as module_cache

    compiler = tmp / "snapshot-producer.exe"
    compiler.write_bytes(b"snapshot protocol producer")
    args = argparse.Namespace(compiler=compiler, config=None, fuel=200000)
    cfg = host.build.load_config(argparse.Namespace(cc=sys.executable))
    shared = "std/types.ouro"
    source = host.ROOT / shared
    data = source.read_bytes()
    changed = data.replace(b"Shared data declarations", b"Shared type declarations", 1)
    assert data != changed and len(data) == len(changed)
    original_mtime = source.stat().st_mtime_ns
    original_open = Path.open
    original_read_bytes = Path.read_bytes
    source_reads = []
    changed_bytes = None

    def open_source(path, mode="r", *args, **kwargs):
        if path.suffix == ".ouro":
            source_reads.append(os.fspath(path))
            if os.fspath(path) == os.fspath(source) and changed_bytes is not None:
                assert mode == "rb"
                return io.BytesIO(changed_bytes)
        return original_open(path, mode, *args, **kwargs)

    lower = PureWindowsPath("C:/snapshot/input.ouro")
    upper = lower.with_name("Input.ouro")
    assert lower == upper
    case_contents = {os.fspath(lower): b"lowercase source", os.fspath(upper): b"uppercase source"}
    case_reads = []

    def read_case_bytes(path):
        spelling = os.fspath(path)
        if spelling in case_contents:
            case_reads.append(spelling)
            return case_contents[spelling]
        return original_read_bytes(path)

    with (patch.object(Path, "read_bytes", read_case_bytes),
          patch.object(host.native, "tool_inputs", wraps=host.native.tool_inputs) as tool_inputs):
        before = host.snapshot(args, cfg)
        read_source = tool_inputs.call_args.kwargs["read_source"]
        for path in (lower, upper, lower):
            assert read_source(path) == case_contents[os.fspath(path)]
        assert case_reads == list(case_contents)
    assert shared in before["inputs"]["sources"] and shared in before["native_process"]["sources"]
    expected_reads = {os.fspath(host.ROOT / name) for section in before.values() if isinstance(section, dict)
                      for name in section["sources"] if name.endswith(".ouro")}
    parse_bytes = module_cache.cached_import_parser()
    with (patch.object(Path, "open", open_source),
          patch.object(module_cache, "quoted_import_targets", wraps=module_cache.quoted_import_targets) as parses,
          patch.object(module_cache, "sha256_bytes", wraps=module_cache.sha256_bytes) as digests):
        assert host.require_snapshot(args, cfg, before, parse_bytes=parse_bytes) == before
        assert set(source_reads) == expected_reads and len(source_reads) == len(expected_reads)
        assert digests.call_count == len(expected_reads)
        parsed_paths = [call.args[1] for call in parses.call_args_list]
        assert host.ENTRY in parsed_paths and len(parsed_paths) == len(set(parsed_paths))
        source_reads.clear()
        parses.reset_mock()
        digests.reset_mock()
        assert host.require_snapshot(args, cfg, before, parse_bytes=parse_bytes) == before
        assert set(source_reads) == expected_reads and len(source_reads) == len(expected_reads)
        parses.assert_not_called()
        digests.assert_not_called()
        changed_bytes = changed
        try:
            host.require_snapshot(args, cfg, before, parse_bytes=parse_bytes)
        except ValueError as error:
            assert str(error) == "source, producer, C compiler or build configuration changed during the suite"
        else:
            raise AssertionError("changed source bytes passed the host suite snapshot check")
        assert source.stat().st_mtime_ns == original_mtime
        assert [call.args[1] for call in parses.call_args_list] == [shared]
        digests.assert_called_once_with(changed)
        changed_bytes = None
        parses.reset_mock()
        assert host.require_snapshot(args, cfg, before, parse_bytes=parse_bytes) == before
        assert [call.args[1] for call in parses.call_args_list] == [shared]

        def version_changes_source(command):
            nonlocal changed_bytes
            assert command[-1] == "--version"
            changed_bytes = changed
            return "\n".join(json.loads(before["inputs"]["cc"])["version"])

        source_reads.clear()
        with patch.object(host.build, "output_or_empty", side_effect=version_changes_source) as version:
            after = host.snapshot(args, cfg, parse_bytes=parse_bytes)
        version.assert_called_once()
        assert source_reads.count(os.fspath(source)) == 1
        assert after["inputs"]["sources"][shared] == after["native_process"]["sources"][shared] == sha256(changed).hexdigest()
        assert after != before
        for field in ("compiler_sha256", "cc", "cc_sha256"):
            assert after["inputs"][field] == before["inputs"][field]

    def read_source_then_replace_compiler(path):
        contents = original_read_bytes(path)
        if os.fspath(path) == os.fspath(source):
            assert contents == data
            compiler.write_bytes(b"replacement snapshot producer")
        return contents

    with patch.object(Path, "read_bytes", read_source_then_replace_compiler):
        try:
            host.snapshot(args, cfg, parse_bytes=parse_bytes)
        except ValueError as error:
            assert str(error) == f"selected compiler changed during frontend host input capture: {compiler}"
        else:
            raise AssertionError("changed compiler passed the frontend host snapshot check")
    assert source.read_bytes() == data

    fake_cc = tmp / "snapshot-cc.exe"
    fake_cc.write_bytes(b"snapshot C compiler")

    def read_source_then_replace_cc(path):
        contents = original_read_bytes(path)
        if os.fspath(path) == os.fspath(source):
            fake_cc.write_bytes(b"replacement snapshot C compiler")
        return contents

    with (patch.object(host.build, "locate_cc", return_value=("fixture-cc", os.fspath(fake_cc))) as locate,
          patch.object(host.build, "output_or_empty", return_value="fixture C compiler\n") as version):
        stable = host.snapshot(args, cfg, parse_bytes=parse_bytes)
        assert stable["inputs"]["cc_sha256"] == sha256(fake_cc.read_bytes()).hexdigest()
        assert locate.call_count == 2
        version.assert_called_once_with(["fixture-cc", "--version"])
        locate.reset_mock()
        version.reset_mock()
        with patch.object(Path, "read_bytes", read_source_then_replace_cc):
            try:
                host.snapshot(args, cfg, parse_bytes=parse_bytes)
            except ValueError as error:
                assert str(error) == f"selected C compiler changed during frontend host input capture: {fake_cc.resolve()}"
            else:
                raise AssertionError("changed C compiler passed the frontend host snapshot check")
        assert locate.call_count == 2
        version.assert_called_once_with(["fixture-cc", "--version"])
    assert source.read_bytes() == data

    cc_alias = tmp / "cc-alias.py"
    original_target = tmp / "cc-first.py"
    replacement_target = tmp / "cc-second.py"
    for path in (cc_alias, original_target, replacement_target):
        path.write_bytes(b"fixture C compiler\n")
    target = original_target
    original_resolve = Path.resolve

    def resolve_cc_alias(path, *args, **kwargs):
        return original_resolve(target if path == cc_alias else path, *args, **kwargs)

    def read_source_then_retarget_cc(path):
        nonlocal target
        contents = original_read_bytes(path)
        if os.fspath(path) == os.fspath(source):
            target = replacement_target
        return contents

    with (patch.object(host.build, "locate_cc", return_value=(str(cc_alias), None)) as locate,
          patch.object(host.build, "output_or_empty", return_value="fixture C compiler\n") as version,
          patch.object(Path, "resolve", resolve_cc_alias),
          patch.object(Path, "read_bytes", read_source_then_retarget_cc)):
        try:
            host.snapshot(args, cfg, parse_bytes=parse_bytes)
        except ValueError as error:
            expected = f"selected C compiler changed during frontend host input capture: {replacement_target.resolve()}"
            assert str(error) == expected
        else:
            raise AssertionError("retargeted C compiler alias passed the frontend host snapshot check")
        assert locate.call_count == 2
        version.assert_called_once_with([sys.executable, str(original_target.resolve()), "--version"])

    with (patch.object(host.native.frontend, "capture_unit_inputs", return_value=({host.ENTRY: []}, {})),
          patch.object(host.build, "locate_cc") as locate):
        try:
            host.native.tool_inputs(host.ENTRY, compiler, args.fuel, cfg)
        except ValueError as error:
            assert str(error) == "empty source collection"
        else:
            raise AssertionError("empty tool source collection accepted")
        locate.assert_not_called()


@patch.dict(os.environ, {JOBS_ENV: "6"})
def test_frontend_host_worker_jobs(tmp: Path) -> None:
    """Resolved worker scheduling must agree with its bound configuration."""
    from dataclasses import replace

    import frontend_host_suite as host

    root = tmp / "frontend-host-worker-jobs"
    root.mkdir()
    compiler = root / "compiler.exe"
    compiler.write_bytes(b"protocol producer")
    common = ["--compiler", str(compiler), "--profile", "dev", "--reproducible"]
    configurations = {}
    for label, worker, words, expected_jobs, expected_opt in (
            ("default-worker", True, [], 1, "O0"),
            ("six-worker", True, ["--jobs", "6", "--opt-level", "O1"], 6, "O1"),
            ("public-suite", False, ["--jobs", "6", "--opt-level", "O1"], 1, "O1")):
        output = root / label
        command = [*common, "--out", str(output), *words, *(["--worker"] if worker else [])]
        with patch.object(host, "configure_native_stack"), \
                patch.object(host, "build_worker") as build_worker, \
                patch.object(host, "run_suite", return_value=0) as run_suite:
            assert host.main(command) == 0
            selected = build_worker if worker else run_suite
            unused = run_suite if worker else build_worker
            unused.assert_not_called()
            args, cfg = selected.call_args.args[:2]
            assert host.build.jobs_value(cfg) == expected_jobs and cfg.sources["jobs"] == "CLI"
            assert cfg.values["opt_level"] == expected_opt and cfg.values["profile"] == "dev"
            assert not cfg.get_bool("cache_enabled") and cfg.values["ccache"] == "disabled"
            assert cfg.get_bool("reproducible") and host.build.profile_cflags(cfg)[0] == "-" + expected_opt
            assert (args.fuel, args.memory_mib, args.build_timeout, args.probe_timeout) == (200000, 3072, 900, 30)
            configurations[label] = args, cfg

    for invalid in ("0", "-1", "invalid"):
        with patch.object(host, "configure_native_stack"), patch.object(host, "build_worker") as build_worker:
            try:
                host.main([*common, "--out", str(root / "invalid"), "--worker", "--jobs", invalid])
            except SystemExit as error:
                assert error.code != 0
            else:
                raise AssertionError("invalid explicit worker jobs accepted: " + invalid)
            build_worker.assert_not_called()

    args, cfg = configurations["six-worker"]
    args.out.mkdir()
    for name in host.HOST_MAINS.values():
        main = root / name
        main.parent.mkdir(parents=True, exist_ok=True)
        main.write_text("void worker_jobs_protocol(void) {}\n", encoding="utf-8")

    def configuration_snapshot(_args, current, **_kwargs):
        return {"units": [host.ENTRY], "values": current.values,
                "cflags": host.build.profile_cflags(current)}

    before = configuration_snapshot(args, cfg)
    (args.out / "inputs-before.json").write_text(json.dumps(before), encoding="utf-8")

    def emit(_compiler, _units, _fuel, output, **_kwargs):
        output.write_text("void worker_jobs_generated(void) {}\n", encoding="utf-8")

    def materialize(**options):
        manifest = options["out_dir"] / "generated-c-shards.manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("{}\n", encoding="utf-8")
        return [], {}

    def compile_fixture(_cfg, **options):
        options["output"].write_bytes(b"protocol image")
        return {"jobs": options["jobs"]}

    with patch.object(host, "ROOT", root), \
            patch.object(host, "snapshot", side_effect=configuration_snapshot) as snapshot, \
            patch.object(host.native, "emit", side_effect=emit) as emitted, \
            patch.object(host.build.GCS, "materialize_generated_c_shards", side_effect=materialize), \
            patch.object(host, "require_generated_shards") as shard_checks, \
            patch.object(host.build, "build_c_executable", side_effect=compile_fixture) as compiled:
        host.build_worker(args, cfg)
        worker_parser = snapshot.call_args.kwargs["parse_bytes"]
        assert callable(worker_parser)
        assert all(call.kwargs["parse_bytes"] is worker_parser for call in snapshot.call_args_list)
        assert emitted.call_args.kwargs["parse_bytes"] is worker_parser
        assert compiled.call_count == len(host.HOST_MAINS) == 6
        assert all(call.args[0] is cfg and call.kwargs["jobs"] == 6 for call in compiled.call_args_list)
        assert [call.kwargs["output"] for call in compiled.call_args_list] == [
            host.executable(args.out, name) for name in host.HOST_MAINS]
        for call, name in zip(compiled.call_args_list, host.HOST_MAINS, strict=True):
            expected_flags = ["-Werror=implicit-function-declaration", "-DOURO_FE_FLAT_EXPORTS"]
            expected_source_flags = {}
            if name == "module-pure-scope-selftest":
                expected_source_flags = {host.HOST_MAINS[name]: ("-DOURO_MODULE_PURE_SCOPES=1",)}
                assert [label for label, _path in call.kwargs["sources"]] == [
                    "runtime/ouro_rt.c", "runtime/ouro_io.c", "runtime/frontend_link.c",
                    "runtime/module_pure_scope_selftest.c"]
            assert call.kwargs["extra_cflags"] == expected_flags
            assert call.kwargs["source_cflags"] == expected_source_flags
        assert emitted.call_args.args[:3] == (args.compiler, before["units"], 200000)
        assert shard_checks.call_count >= len(host.HOST_MAINS)
        compiled.reset_mock()
        emitted.reset_mock()
        try:
            host.build_worker(args, replace(cfg, values={**cfg.values, "jobs": 1}))
        except ValueError:
            pass
        else:
            raise AssertionError("worker configuration differs from bound snapshot")
        compiled.assert_not_called()
        emitted.assert_not_called()


def test_frontend_native_live_protocol(tmp: Path) -> None:
    """Synthetic transport/receipts cannot stand in for native GC execution."""
    import copy
    from dataclasses import asdict, replace
    from types import SimpleNamespace

    import frontend_host_suite as host
    from ourosmith.limits import RunResult

    expected = ("live-reclaim", "live-calls", "live-high-descriptor", "escaping_collect", "pap_reuse_collect", "pap_plateau")
    assert host.NATIVE_LIVE_CASES == expected

    def rejected(operation):
        try:
            operation()
        except ValueError:
            return
        raise AssertionError("invalid native liveness evidence accepted")

    work = tmp / "native-live-transport"
    work.mkdir()
    producer = work / "frontend-codegen-selftest.exe"
    producer.write_bytes(b"synthetic fresh C-host adapter")
    generated = work / "backend.gen.c"
    generated.write_bytes(b"synthetic current Ouro backend")
    names = (host.ENTRY, "tests/native_live_runtime.ouro", "tests/native_managed_values.ouro",
             "tests/native_managed_fixtures.ouro", "runtime/frontend_codegen_selftest.c")
    before = {"inputs": {"compiler_sha256": "a" * 64,
                         "sources": {name: f"{index:064x}" for index, name in enumerate(names, 1)}},
              "native_live": {"units": ["tests/native_managed/runtime.ouro"],
                              "sources": {"tests/native_managed/runtime.ouro": "b" * 64}}}
    built = {"kind": host.KIND + ".build", "generated_sha256": host.sha256_file(generated),
             "binaries": {"frontend-codegen-selftest": {"sha256": host.sha256_file(producer)}}}
    host.write_json_atomic(work / "inputs-before.json", before)
    host.write_json_atomic(work / "build.json", built)
    calls = []

    def image(path, imports, required_symbols=None):
        assert tuple(imports) == ("kernel32.dll",)
        row = {"sha256": host.sha256_file(path), "bytes": path.stat().st_size,
               "machine": "x86_64", "imports": ["kernel32.dll"]}
        if required_symbols is not None:
            assert required_symbols == host.NATIVE_LIVE_SYMBOLS
            row["import_symbols"] = {name: list(symbols) for name, symbols in required_symbols.items()}
        return row

    def run(label, command, timeout):
        calls.append((label, command, timeout))
        if label.endswith("-emit"):
            mode = label.removesuffix("-emit")
            assert command == [str(producer), mode, str(work / (mode + ".exe"))]
            Path(command[-1]).write_bytes(("synthetic PE " + mode).encode().ljust(128, b"\0"))
            return RunResult("ok", 0, f"FRONTEND_CODEGEN_SELFTEST: passed {mode}\n", "", 0, 0, command)
        assert label.endswith("-pe")
        return RunResult("ok", 42, "", "", 0, 0, command)

    with patch.object(host, "os", SimpleNamespace(name="nt")), \
            patch.object(host.direct_process, "inspect_image", side_effect=image):
        report = host.run_native_live(work, run, 90, 3, lambda: None, before, built)
        assert tuple(report["cases"]) == expected and report["native_executed"] is True
        assert [(label, timeout) for label, _command, timeout in calls] == [
            item for mode in expected for item in ((mode + "-emit", 90), (mode + "-pe", 3))]
        lineage = host.native_live_lineage(work, before, built)
        host.verify_native_live_report(report, lineage)
        host.verify_native_live_artifacts(work, report)
        persisted = json.loads((work / "native-live.json").read_text(encoding="utf-8"))
        assert persisted == report
        host.verify_native_live_report(persisted, lineage)
        for mode in host.NATIVE_LIVE_GC_CASES:
            success = RunResult("ok", 42, "", "", 0, 0, [str(work / (mode + ".exe"))])
            for result in (replace(success, status="timeout"), replace(success, status="memory"),
                           replace(success, status="skipped"), replace(success, returncode=99),
                           replace(success, returncode=None), replace(success, stdout="\0"),
                           replace(success, stderr="unexpected\n"), replace(success, stdout=None)):
                rejected(lambda candidate=result, selected=mode: host.verify_native_live_result(asdict(candidate), selected))
        for field, value in (("status", "unavailable"), ("native_bootstrap", True),
                             ("native_executed", False), ("images_unchanged", False),
                             ("execution_backend", "generated-c-host")):
            changed = {**report, field: value}
            rejected(lambda candidate=changed: host.verify_native_live_report(candidate, lineage))
        changed = copy.deepcopy(report)
        changed["cases"].pop("pap_reuse_collect")
        rejected(lambda: host.verify_native_live_report(changed, lineage))
        changed = copy.deepcopy(report)
        changed["cases"].pop("pap_plateau")
        rejected(lambda: host.verify_native_live_report(changed, lineage))
        changed = {**report, "case_order": list(reversed(report["case_order"]))}
        rejected(lambda: host.verify_native_live_report(changed, lineage))
        changed = copy.deepcopy(report)
        changed["cases"]["extra"] = changed["cases"]["escaping_collect"]
        rejected(lambda: host.verify_native_live_report(changed, lineage))
        for field, value in (("path", str(work / "other.exe")), ("exit", True),
                             ("sha256", "c" * 64)):
            changed = copy.deepcopy(report)
            changed["cases"]["escaping_collect"][field] = value
            rejected(lambda candidate=changed: host.verify_native_live_report(candidate, lineage))
        for section, field, value in (("image", "imports", ["kernel32.dll", "ucrtbase.dll"]),
                                      ("image", "machine", "x86"),
                                      ("image", "import_symbols", {}),
                                      ("emission", "argv", [str(producer), "live-reclaim", "wrong.exe"]),
                                      ("emission", "stdout", ""), ("emission", "status", "timeout"),
                                      ("runtime", "argv", ["foreign.exe"]), ("runtime", "returncode", 98)):
            changed = copy.deepcopy(report)
            changed["cases"]["pap_reuse_collect"][section][field] = value
            rejected(lambda candidate=changed: host.verify_native_live_report(candidate, lineage))
        for field in ("producer_sha256", "generated_sha256", "seed_sha256"):
            changed = copy.deepcopy(report)
            changed["lineage"][field] = "d" * 64
            rejected(lambda candidate=changed: host.verify_native_live_report(candidate, lineage))
        changed = copy.deepcopy(report)
        changed["lineage"]["sources"]["tests/native_managed_values.ouro"] = "e" * 64
        rejected(lambda: host.verify_native_live_report(changed, lineage))
        for path in (producer, generated, work / "inputs-before.json", work / "build.json",
                     work / "escaping_collect.exe", work / "pap_reuse_collect.exe", work / "pap_plateau.exe"):
            original = path.read_bytes()
            try:
                path.write_bytes(original + b" changed")
                rejected(lambda: host.verify_native_live_artifacts(work, report))
            finally:
                path.write_bytes(original)
        (work / "pap_reuse_collect.exe").unlink()
        try:
            host.verify_native_live_artifacts(work, report)
        except OSError:
            pass
        else:
            raise AssertionError("missing native GC image accepted")
    with patch.object(host, "os", SimpleNamespace(name="posix")), patch.object(host, "verify_native_live_result") as checked:
        unavailable = host.run_native_live(None, None, 90, 3, None, None, None)
        assert unavailable["status"] == "unavailable" and unavailable["native_executed"] is False
        assert unavailable["cases"] == {} and unavailable["native_bootstrap"] is False
        checked.assert_not_called()


def capture_fixture_units(root, closures, entries):
    from frontend_regen import FileDigest
    from repo_support import sha256_bytes

    graph = {entry: list(closures[entry]) for entry in entries}
    captured = {}
    for name in {name for units in graph.values() for name in units}:
        data = (root / name).read_bytes()
        captured[name] = FileDigest(name, sha256_bytes(data), len(data))
    return graph, captured


def test_frontend_raw_fn_protocol(tmp: Path) -> None:
    """Synthetic transport/receipt checks are not RawFn runtime acceptance."""
    import copy
    from dataclasses import replace
    from types import SimpleNamespace

    import frontend_host_suite as host
    from ourosmith import limits
    from ourosmith.limits import RunBytesResult, RunResult

    assert [case for case, _entry, _text in host.RAW_FN_CASES] == ["deferred", "stdio"]

    def rejected(operation):
        try:
            operation()
        except ValueError:
            return
        raise AssertionError("invalid native RawFn evidence accepted")

    raw_stdout, raw_stderr = b"B\r\nA\0Z\xff\n", b"\xff\r\n"
    communication = []

    def communicate(**options):
        assert set(options) == {"input", "timeout"}
        communication.append((options["input"], options["timeout"]))
        return raw_stdout, raw_stderr

    def wait(timeout):
        assert timeout == 10
        return 42

    process = SimpleNamespace(returncode=42, communicate=communicate, wait=wait)
    with patch.object(limits, "os", SimpleNamespace(name="posix")), \
            patch.object(limits.shutil, "which", return_value="synthetic-raw-fixture"), \
            patch.object(limits.subprocess, "Popen", return_value=process) as spawn, \
            patch.object(limits, "kill_tree") as killed:
        raw = limits.run_limited_bytes(["synthetic-raw-fixture"], timeout_s=3, memory_mb=16, env={})
        text = limits.run_limited(["synthetic-raw-fixture"], timeout_s=3, memory_mb=16, env={})
        assert isinstance(raw, RunBytesResult) and raw.stdout == raw_stdout and raw.stderr == raw_stderr
        assert isinstance(text, RunResult) and text.stdout == "B\nA\0Z\ufffd\n" and text.stderr == "\ufffd\n"
        assert raw.status == text.status == "ok" and raw.returncode == text.returncode == 42
        assert communication == [(None, 3), (None, 3)] and killed.call_count == 2
        assert spawn.call_count == 2 and spawn.call_args.kwargs["stdout"] == subprocess.PIPE
        assert spawn.call_args.kwargs["stderr"] == subprocess.PIPE and spawn.call_args.kwargs.get("text", False) is False
        assert spawn.call_args.args[0][2] == "16"

    root = tmp / "raw-fn-protocol-root"
    root.mkdir()
    closures = {entry: [host.RAW_FN_VALUES, entry] for _case, entry, _text in host.RAW_FN_CASES}
    for name in {name for units in closures.values() for name in units}:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic source " + name + "\n", encoding="utf-8")
    calls, input_checks = [], []

    def image(path, imports, required_symbols=None):
        assert tuple(imports) == host.RAW_FN_IMPORTS and required_symbols
        assert {"GetModuleHandleA", "GetProcAddress", "VirtualAlloc", "VirtualFree",
                "HeapCreate", "HeapAlloc", "HeapFree", "HeapDestroy", "ExitProcess"} <= set(required_symbols["kernel32.dll"])
        return {"sha256": host.sha256_file(path), "bytes": path.stat().st_size,
                "machine": "x86_64", "imports": list(imports),
                "import_symbols": {name: list(symbols) for name, symbols in required_symbols.items()}}

    def phase_text(logical, count):
        return (f"n1-host: check units={count} live=1\n"
                "n1-host: CHECK_OK live=1 total=2\nn1-host: recheck live=1\n"
                "n1-host: RECHECK_OK live=1\nn1-host: TYPES_OK live=1\n"
                "n1-host: lower live=1\nn1-host: BUILD_OK live=1\n"
                "n1-host: mir functions=1 live=1\nn1-host: mir-check live=1\n"
                "n1-host: gc-infer live=1\nn1-host: annotate live=1\nn1-host: codegen live=1\n"
                f"n1-host: LOWER_OK live=1\nn1-host: WROTE {logical} live=1\n")

    def run(label, command, timeout, *, capture_bytes=False):
        calls.append((label, command, timeout))
        if label.endswith("-emit"):
            assert capture_bytes is False
            case = label.removeprefix("raw-fn-").removesuffix("-emit")
            entry = {name: source for name, source, _text in host.RAW_FN_CASES}[case]
            assert command[1:] == [entry, command[2], *closures[entry]]
            output = root / command[2]
            output.write_bytes(("synthetic PE " + case).encode().ljust(128, b"\0"))
            return RunResult("ok", 0, command[2] + "\n", phase_text(command[2], len(closures[entry])), 0, 0, command)
        assert label.endswith("-pe") and len(command) == 1 and capture_bytes is True
        case = label.removeprefix("raw-fn-").removesuffix("-pe")
        stdout = {name: text for name, _entry, text in host.RAW_FN_CASES}[case]
        stdout = stdout.encode("utf-8")
        work = Path(command[0]).parent.parent
        (work / (label + ".out")).write_bytes(stdout)
        (work / (label + ".err")).write_bytes(b"")
        return RunBytesResult("ok", 42, stdout, b"", 0, 0, command)

    def prepare(name, before, built):
        work = root / name
        work.mkdir()
        (work / "n1-host.exe").write_bytes(b"synthetic fresh C-host adapter")
        (work / "backend.gen.c").write_bytes(b"synthetic current Ouro backend")
        host.write_json_atomic(work / "inputs-before.json", before)
        host.write_json_atomic(work / "build.json", built)
        return work

    with patch.object(host, "ROOT", root), patch.object(host, "os", SimpleNamespace(name="nt")), \
            patch.object(host, "capture_unit_inputs",
                         side_effect=lambda entries, **_kwargs: capture_fixture_units(root, closures, entries)), \
            patch.object(host.direct_process, "inspect_image", side_effect=image):
        snapshot = host.raw_fn_source_snapshot()
        names = (host.ENTRY, "runtime/n1_host_main.c", "scripts/frontend_host_suite.py", "scripts/ourosmith/limits.py")
        before = {"inputs": {"compiler_sha256": "a" * 64,
                             "sources": {name: f"{index:064x}" for index, name in enumerate(names, 1)}},
                  "native_raw_fn": snapshot}
        hash_work = root / "hashes"
        hash_work.mkdir()
        (hash_work / "producer").write_bytes(b"synthetic fresh C-host adapter")
        (hash_work / "generated").write_bytes(b"synthetic current Ouro backend")
        built = {"kind": host.KIND + ".build", "generated_sha256": host.sha256_file(hash_work / "generated"),
                 "binaries": {"n1-host": {"sha256": host.sha256_file(hash_work / "producer")}}}
        work = prepare("success", before, built)
        report = host.run_native_raw_fn(work, run, 90, 3, lambda: input_checks.append(True), before, built)
        lineage = host.native_raw_fn_lineage(work, before, built)
        host.verify_native_raw_fn_report(report, lineage, work)
        host.verify_native_raw_fn_artifacts(work, report)
        receipts = [work / "inputs-before.json", work / "build.json"]
        read_bytes = Path.read_bytes
        for receipt in receipts:
            original = receipt.read_bytes()
            altered = original + b"\r\n"

            def read_then_change(path, *, _receipt=receipt, _altered=altered):
                data = read_bytes(path)
                if path == _receipt:
                    path.write_bytes(_altered)
                return data

            try:
                with patch.object(Path, "read_bytes", autospec=True, side_effect=read_then_change) as reads:
                    assert host.native_raw_fn_lineage(work, before, built) == lineage
                assert [call.args[0] for call in reads.call_args_list] == receipts
                assert receipt.read_bytes() == altered
                rejected(lambda: host.verify_native_raw_fn_artifacts(work, report))
                for invalid_encoding in (b"\xef\xbb\xbf" + original, original.decode("utf-8").encode("utf-16")):
                    receipt.write_bytes(invalid_encoding)
                    rejected(lambda: host.native_raw_fn_lineage(work, before, built))
            finally:
                receipt.write_bytes(original)
        persisted = json.loads((work / "native-raw-fn" / "report.json").read_text(encoding="utf-8"))
        assert persisted == report and input_checks
        host.verify_native_raw_fn_report(persisted, lineage, work)
        assert (work / "raw-fn-stdio-pe.out").read_bytes() == b"B\nA\0Z\nC\0Z\nD\n"
        assert persisted["cases"]["stdio"]["result"]["stdout_hex"] == "420a41005a0a43005a0a440a"
        assert [(label, timeout) for label, _command, timeout in calls] == [
            item for case, _entry, _text in host.RAW_FN_CASES
            for item in (("raw-fn-" + case + "-emit", 90), ("raw-fn-" + case + "-pe", 3))]
        for field, value in (("status", "unavailable"), ("native_bootstrap", True),
                             ("native_executed", False), ("images_unchanged", False),
                             ("execution_backend", "generated-c-host"), ("lineage", {})):
            changed = {**report, field: value}
            rejected(lambda candidate=changed: host.verify_native_raw_fn_report(candidate, lineage, work))
        for order in (["stdio", "deferred"], ["deferred", "deferred"], ["deferred"]):
            changed = {**report, "case_order": order}
            rejected(lambda candidate=changed: host.verify_native_raw_fn_report(candidate, lineage, work))
        for cases in ({}, {"deferred": report["cases"]["deferred"]},
                      {**report["cases"], "extra": report["cases"]["stdio"]}):
            changed = {**report, "cases": cases}
            rejected(lambda candidate=changed: host.verify_native_raw_fn_report(candidate, lineage, work))
        for case, _entry, stdout in host.RAW_FN_CASES:
            valid = RunBytesResult("ok", 42, stdout.encode("utf-8"), b"", 0, 0, [])
            for failed in (replace(valid, status="timeout"), replace(valid, status="memory"),
                           replace(valid, status="skipped"), replace(valid, returncode=0),
                           replace(valid, returncode=73), replace(valid, returncode=True),
                           replace(valid, returncode=None), replace(valid, stdout=valid.stdout + b"\0"),
                           replace(valid, stdout=valid.stdout + b"\xff"), replace(valid, stdout=None),
                           replace(valid, stderr=b"unexpected\n"), replace(valid, stderr=b"\xff")):
                rejected(lambda candidate=failed, selected=case: host.verify_native_raw_fn_result(host.bytes_run_record(candidate), selected))
            rejected(lambda text=stdout: host.bytes_run_record(RunResult("ok", 42, text, "", 0, 0)))
        stdio = RunBytesResult("ok", 42, b"B\nA\0Z\nC\0Z\nD\n", b"", 0, 0, [])
        host.verify_native_raw_fn_result(host.bytes_run_record(stdio), "stdio")
        for changed_bytes in (stdio.stdout.replace(b"\n", b"\r\n"), stdio.stdout.replace(b"\0", b""),
                              stdio.stdout.replace(b"\0", b"\xff")):
            changed_result = replace(stdio, stdout=changed_bytes)
            rejected(lambda candidate=changed_result: host.verify_native_raw_fn_result(host.bytes_run_record(candidate), "stdio"))
        for section, field, value in (("emission", "argv", [lineage["producer"], "wrong.ouro"]),
                                      ("emission", "stdout", ""), ("emission", "status", "timeout"),
                                      ("result", "argv", ["foreign.exe"]), ("result", "returncode", 91),
                                      ("image", "imports", [*host.RAW_FN_IMPORTS, "ucrtbase.dll"]),
                                      ("image", "import_symbols", {}), ("image", "machine", "x86")):
            changed = copy.deepcopy(report)
            changed["cases"]["stdio"][section][field] = value
            rejected(lambda candidate=changed: host.verify_native_raw_fn_report(candidate, lineage, work))
        changed = copy.deepcopy(report)
        changed["cases"]["stdio"]["result"]["stdout_hex"] = b"B\nC\0Z\nA\0Z\nD\n".hex()
        rejected(lambda: host.verify_native_raw_fn_report(changed, lineage, work))
        for field, value in (("capture", "text"), ("stdout_hex", None), ("stderr_hex", "ff")):
            changed = copy.deepcopy(report)
            changed["cases"]["stdio"]["result"][field] = value
            rejected(lambda candidate=changed: host.verify_native_raw_fn_report(candidate, lineage, work))
        for field, value in (("sha256", "b" * 64), ("bytes", 0), ("path", "foreign.out")):
            changed = copy.deepcopy(report)
            changed["cases"]["stdio"]["streams"]["stdout"][field] = value
            rejected(lambda candidate=changed: host.verify_native_raw_fn_report(candidate, lineage, work))
        changed = copy.deepcopy(report)
        changed["cases"]["deferred"]["emission"]["argv"] = list(reversed(changed["cases"]["deferred"]["emission"]["argv"]))
        rejected(lambda: host.verify_native_raw_fn_report(changed, lineage, work))
        emitted = report["cases"]["deferred"]["emission"]
        logical = emitted["stdout"].removesuffix("\n")
        for line in emitted["stderr"].splitlines():
            if not line.startswith("n1-host: lower "):
                changed = {**emitted, "stderr": emitted["stderr"].replace(line + "\n", "")}
                rejected(lambda candidate=changed: host.verify_native_raw_fn_emission(candidate, logical, 2))
        for text in (emitted["stderr"] + "n1-host: managed miss tag=7; scalar lower\n",
                     emitted["stderr"] + "n1-host: CHECK_OK live=1 total=2\n",
                     "\n".join(reversed(emitted["stderr"].splitlines())) + "\n"):
            changed = {**emitted, "stderr": text}
            rejected(lambda candidate=changed: host.verify_native_raw_fn_emission(candidate, logical, 2))
        for field in ("producer_sha256", "generated_sha256", "seed_sha256", "producer_backend"):
            changed = copy.deepcopy(report)
            changed["lineage"][field] = "b" * 64
            rejected(lambda candidate=changed: host.verify_native_raw_fn_artifacts(work, candidate))
        changed = copy.deepcopy(report)
        changed["lineage"]["sources"][host.ENTRY] = "c" * 64
        rejected(lambda: host.verify_native_raw_fn_artifacts(work, changed))
        for path in (work / "n1-host.exe", work / "backend.gen.c", work / "inputs-before.json",
                     work / "build.json", work / "native-raw-fn" / "deferred.exe",
                      work / "native-raw-fn" / "stdio.exe", root / host.RAW_FN_VALUES,
                      work / "raw-fn-stdio-pe.out", work / "raw-fn-stdio-pe.err",
                      work / "raw-fn-deferred-pe.out", work / "raw-fn-deferred-pe.err"):
            original = path.read_bytes()
            try:
                path.write_bytes(original + b" changed")
                rejected(lambda: host.verify_native_raw_fn_artifacts(work, report))
            finally:
                path.write_bytes(original)
        for invalid in (lambda entry: [entry], lambda entry: [entry, host.RAW_FN_VALUES],
                        lambda entry: [host.RAW_FN_VALUES, entry, entry]):
            graph = {entry: invalid(entry) for entry in closures}
            with patch.object(host, "capture_unit_inputs", return_value=(graph, {})):
                rejected(host.raw_fn_source_snapshot)
        for index, status in enumerate(("timeout", "memory", "skipped")):
            failed_work = prepare("child-failure-" + str(index), before, built)
            calls.clear()

            def failed_run(label, command, timeout, selected=status, *, capture_bytes=False):
                result = run(label, command, timeout, capture_bytes=capture_bytes)
                return replace(result, status=selected) if label.endswith("-pe") else result

            rejected(lambda destination=failed_work, operation=failed_run: host.run_native_raw_fn(
                destination, operation, 90, 3, lambda: None, before, built))
            failed_report = json.loads((failed_work / "native-raw-fn" / "report.json").read_text(encoding="utf-8"))
            assert failed_report["status"] == "failed" and failed_report["native_executed"] is False
            assert [label for label, _command, _timeout in calls] == ["raw-fn-deferred-emit", "raw-fn-deferred-pe"]
        producer_failed = prepare("producer-failure", before, built)
        calls.clear()

        def failed_emission(label, command, timeout):
            assert label.endswith("-emit")
            calls.append((label, command, timeout))
            return RunResult("ok", 1, "", "n1-host: compiler failed 64:1\n", 0, 0, command)

        rejected(lambda: host.run_native_raw_fn(producer_failed, failed_emission, 90, 3, lambda: None, before, built))
        failed_report = json.loads((producer_failed / "native-raw-fn" / "report.json").read_text(encoding="utf-8"))
        assert failed_report["status"] == "failed" and failed_report["native_executed"] is False
        assert failed_report["cases"] == {} and list((producer_failed / "native-raw-fn").glob("*.exe")) == []
        assert [label for label, _command, _timeout in calls] == ["raw-fn-deferred-emit"]
    with patch.object(host, "os", SimpleNamespace(name="posix")), patch.object(host, "native_raw_fn_lineage") as checked:
        unavailable = host.run_native_raw_fn(None, None, 90, 3, None, None, None)
        assert unavailable["status"] == "unavailable" and unavailable["native_executed"] is False
        assert unavailable["cases"] == {} and unavailable["native_bootstrap"] is False
        checked.assert_not_called()


def test_frontend_file_status_fault_protocol(tmp: Path) -> None:
    """Synthetic transport checks do not establish file-fault runtime acceptance."""
    import copy
    from dataclasses import asdict, replace
    from types import SimpleNamespace

    import frontend_host_suite as host
    from ourosmith.limits import RunResult

    expected = ((0, "0", 42), (8, "5", 42), (9, "5", 42), (10, "5", 42), (11, "38", 42),
                (12, "0", 73), (13, "0", 73), (14, "0", 73), (15, "5", 42), (16, "0", 42),
                (17, "0", 73), (18, "0", 73))
    assert host.FILE_STATUS_FAULT_CASES == expected

    def rejected(operation):
        try:
            operation()
        except ValueError:
            return
        raise AssertionError("invalid native file status fault evidence accepted")

    names = (host.ENTRY, "tests/native_live_runtime.ouro", "tests/native_managed_values.ouro",
             "tests/native_managed_fixtures.ouro", "runtime/frontend_codegen_selftest.c",
             "tests/native_file_fixtures.ouro", "tests/native_file_fault_calls.ouro",
             "tests/native_file_fault_values.ouro", "tests/native_startup_fault_values.ouro")
    fault = {"entry": host.FILE_STATUS_FAULT_ENTRY, "units": [host.FILE_STATUS_FAULT_ENTRY],
             "sources": {host.FILE_STATUS_FAULT_ENTRY: "a" * 64}}
    before = {"inputs": {"compiler_sha256": "b" * 64,
                         "sources": {name: f"{index:064x}" for index, name in enumerate(names, 1)}},
              "native_live": {"units": ["tests/native_managed/runtime.ouro"],
                              "sources": {"tests/native_managed/runtime.ouro": "c" * 64}},
              "native_file_status_fault": fault}

    def prepare(name):
        work = tmp / name
        work.mkdir()
        producer = work / "frontend-codegen-selftest.exe"
        producer.write_bytes(b"synthetic fresh C-host adapter")
        generated = work / "backend.gen.c"
        generated.write_bytes(b"synthetic current Ouro backend")
        built = {"generated_sha256": host.sha256_file(generated),
                 "binaries": {"frontend-codegen-selftest": {"sha256": host.sha256_file(producer)}}}
        host.write_json_atomic(work / "inputs-before.json", before)
        host.write_json_atomic(work / "build.json", built)
        return work, producer, built

    def image(path, imports, required_symbols):
        assert tuple(imports) == host.FILE_STATUS_FAULT_IMPORTS and required_symbols == host.FILE_STATUS_FAULT_SYMBOLS
        return {"sha256": host.sha256_file(path), "bytes": path.stat().st_size, "machine": "x86_64",
                "imports": list(imports), "import_symbols": {name: list(symbols) for name, symbols in required_symbols.items()}}

    work, producer, built = prepare("file-status-transport")
    calls = []

    def run(label, command, timeout, *, cwd=host.ROOT):
        calls.append((label, command, timeout, str(cwd)))
        if label.startswith("file-status-reject-"):
            return RunResult("ok", 2, "", "", 0, 0, command)
        if label.endswith("-emit"):
            mode = int(command[2])
            Path(command[-1]).write_bytes(("synthetic fault PE " + str(mode)).encode().ljust(128, b"\0"))
            return RunResult("ok", 0, f"FRONTEND_CODEGEN_SELFTEST: passed file-read-status {mode}\n", "", 0, 0, command)
        mode = int(Path(command[0]).stem.removeprefix("mode-"))
        _mode, status, code = next(row for row in expected if row[0] == mode)
        assert command[1] == status and (cwd / "files/fault-read.bin").read_bytes() == host.FILE_STATUS_FAULT_BYTES
        return RunResult("ok", code, "", "", 0, 0, command)

    with patch.object(host, "os", SimpleNamespace(name="nt")), \
            patch.object(host, "file_status_fault_snapshot", return_value=fault), \
            patch.object(host.direct_process, "inspect_image", side_effect=image):
        report = host.run_file_status_faults(work, run, 90, 3, lambda: None, before, built)
        lineage = {**host.native_live_lineage(work, before, built), "fault_inputs": fault}
        host.verify_file_status_fault_report(report, lineage)
        host.verify_file_status_fault_artifacts(work, report)
        persisted = json.loads((work / "native-file-status-fault/report.json").read_text(encoding="utf-8"))
        assert persisted == report
        host.verify_file_status_fault_report(persisted, lineage)
        planned = host.file_status_fault_rejections(work / "native-file-status-fault/reject.exe")
        assert [(label, timeout) for label, _command, timeout, _cwd in calls] == [
            ("file-status-reject-" + name, 3) for name, _arguments in planned] + [
            item for mode, _status, _code in expected for item in ((f"file-status-{mode}-emit", 90), (f"file-status-{mode}-pe", 3))]
        for mode, _status, code in expected:
            success = RunResult("ok", code, "", "", 0, 0, [])
            for result in (replace(success, status="timeout"), replace(success, status="memory"),
                           replace(success, status="skipped"), replace(success, returncode=73 if code == 42 else 42),
                           replace(success, returncode=None), replace(success, stdout="\0"), replace(success, stderr="failure\n")):
                rejected(lambda candidate=result, selected=mode: host.verify_file_status_fault_result(asdict(candidate), selected))
        rejected(lambda: host.verify_file_status_fault_result(asdict(success), 7))
        for field, value in (("status", "unavailable"), ("native_bootstrap", True), ("native_executed", False),
                             ("images_unchanged", False), ("fixture_level", "unchecked-mir")):
            rejected(lambda key=field, candidate=value: host.verify_file_status_fault_report({**report, key: candidate}, lineage))
        for rows in (report["cases"][:-1], list(reversed(report["cases"])), [*report["cases"], report["cases"][0]], [None] * 12):
            rejected(lambda candidate=rows: host.verify_file_status_fault_report({**report, "cases": candidate}, lineage))
        rejected(lambda: host.verify_file_status_fault_report({**report, "rejections": []}, lineage))
        for field, value in (("mode", False), ("status_argument", "5"), ("exit", 73), ("cwd", "foreign"),
                             ("input_path", "foreign.bin"), ("input_bytes", [65]), ("counter_verification", "unchecked")):
            changed = copy.deepcopy(report)
            changed["cases"][0][field] = value
            rejected(lambda candidate=changed: host.verify_file_status_fault_report(candidate, lineage))
        for section, field, value in (("image", "imports", ["kernel32.dll", "ucrtbase.dll"]),
                                      ("image", "import_symbols", {}), ("image", "machine", "x86"),
                                      ("emission", "argv", [str(producer), "file-read-status", "7", "wrong.exe"]),
                                      ("emission", "stdout", ""), ("runtime", "argv", ["foreign.exe", "0"])):
            changed = copy.deepcopy(report)
            changed["cases"][-1][section][field] = value
            rejected(lambda candidate=changed: host.verify_file_status_fault_report(candidate, lineage))
        changed = copy.deepcopy(report)
        changed["lineage"]["fault_inputs"]["sources"][host.FILE_STATUS_FAULT_ENTRY] = "d" * 64
        rejected(lambda: host.verify_file_status_fault_report(changed, lineage))
        for path in (producer, work / "backend.gen.c", work / "inputs-before.json", work / "build.json",
                     Path(report["cases"][0]["path"]), Path(report["cases"][-1]["path"]),
                     Path(report["cases"][0]["input_path"]), Path(report["cases"][-1]["input_path"])):
            original = path.read_bytes()
            try:
                path.write_bytes(original + b"changed")
                rejected(lambda: host.verify_file_status_fault_artifacts(work, report))
            finally:
                path.write_bytes(original)
        rejected_output = work / "native-file-status-fault/reject.exe"
        rejected_output.write_bytes(b"invalid mode output")
        rejected(lambda: host.verify_file_status_fault_artifacts(work, report))
        rejected_output.unlink()
        for phase in ("checked source lowering", "parts shape", "fault reconstruction", "MIR/GC validation", "image emission", "publication"):
            failure_work, _failure_producer, failure_built = prepare("file-status-failure-" + phase.replace("/", "-").replace(" ", "-"))

            def failed(label, command, _timeout, phase_name=phase):
                if label.startswith("file-status-reject-"):
                    return RunResult("ok", 2, "", "", 0, 0, command)
                assert label == "file-status-0-emit"
                return RunResult("ok", 1, "", "FRONTEND_CODEGEN_SELFTEST: " + phase_name + "\n", 0, 0, command)

            rejected(lambda work=failure_work, built=failure_built: host.run_file_status_faults(work, failed, 90, 3, lambda: None, before, built))
            failure_dir = failure_work / "native-file-status-fault"
            failed_report = json.loads((failure_dir / "report.json").read_text(encoding="utf-8"))
            assert failed_report["status"] == "failed" and failed_report["native_executed"] is False
            assert failed_report["cases"] == [] and not list(failure_dir.glob("*.exe"))
        bad_output = work / "failed-emission.exe"
        failed_result = RunResult("ok", 1, "", "malformed parts\n", 0, 0)
        rejected(lambda: host.verify_file_status_fault_emission(failed_result, 0, bad_output))
        assert not bad_output.exists()
        bad_output.write_bytes(b"forbidden failure output")
        rejected(lambda: host.verify_file_status_fault_emission(failed_result, 0, bad_output))
    with patch.object(host, "os", SimpleNamespace(name="posix")), patch.object(host, "verify_file_status_fault_result") as checked:
        unavailable = host.run_file_status_faults(None, None, 90, 3, None, None, None)
        assert unavailable["status"] == "unavailable" and unavailable["cases"] == [] and unavailable["rejections"] == []
        assert unavailable["native_executed"] is False and unavailable["native_bootstrap"] is False
        checked.assert_not_called()


def test_frontend_native_process_protocol(tmp: Path) -> None:
    """Native runtime evidence must retain phase, bytes, resources, and held handles."""
    import copy
    import hashlib
    from dataclasses import replace
    import struct
    from types import SimpleNamespace

    import frontend_native_process as direct
    import frontend_regen as frontend
    import selfhost_module_cache as module_cache
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
    prepare_phases = ("native-prepare-start", "native-prepare-return", "native-prepare-end")
    prepare_lines = [f"n1-host: lowering-phase={phase} live=200 total=300\n" for phase in prepare_phases]
    telemetry = "".join(prepare_lines)
    for original, diagnostic, scalar in ((valid, r"body:[1-9][0-9]*", False),
                                          (fallback, r"entry:[1-9][0-9]*", True)):
        leaked = replace(original, stderr=original.stderr.replace("n1-host: lower live=200\n",
                                                                 "n1-host: lower live=200\n" + telemetry))
        rejected(lambda candidate=leaked, expected=diagnostic, fallback_mode=scalar:
                 direct.verify_rejection(candidate, expected, output, fallback_mode))
    timed = RunResult("ok", 0, "output.exe\n", "n1-host: lower live=200\n" + telemetry, 0, 0)
    direct.verify_lowering_timings(timed)
    for changed in (replace(timed, status="timeout"), replace(timed, status="memory"),
                    replace(timed, returncode=1), replace(timed, returncode=False),
                    replace(timed, stderr=""), replace(timed, stderr=telemetry.replace(prepare_lines[1], "")),
                    replace(timed, stderr="".join((prepare_lines[1], prepare_lines[0], prepare_lines[2]))),
                    replace(timed, stderr=telemetry + prepare_lines[0]),
                    replace(timed, stderr=telemetry.replace("live=200", "live=invalid")),
                    replace(timed, stderr=telemetry + "n1-host: lowering-phase=native-prepare-unknown live=0 total=0\n")):
        rejected(lambda candidate=changed: direct.verify_lowering_timings(candidate))
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
        "cwd drive backslash absolute",
        "cwd drive slash absolute",
        "cwd UNC absolute",
        "cwd Unicode and spaces literal",
        "cwd four-byte scalar literal",
        "cwd short path rejected",
        "cwd relative path rejected",
        "cwd drive-relative path rejected",
        "cwd root-relative path rejected",
        "cwd NUL rejected",
        "cwd stray continuation rejected",
        "cwd overlong UTF8 rejected",
        "cwd truncated UTF8 rejected",
        "cwd UTF8 surrogate rejected",
        "cwd scalar beyond Unicode rejected",
        "cwd invalid UTF8 lead rejected",
        "cwd OS error wrapper",
        "cwd timeout wrapper",
        "cwd cleanup wrapper",
        "cwd invalid limits wrapper",
        "cwd resource wrapper",
        "cwd output cap wrapper",
        "cwd protocol wrapper",
        "cwd child binary and full exit retained",
    )
    assert direct.API_CASES == api_names and len(api_names) == 53
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
    for index in (-3, -1):
        rows[index].update(exit=1, stdout_hex="")
    for row in rows[-4:]:
        row.update(parent_pid=101, descendant_pids=[102, 103], alive_before_observation=True,
                   held_handles_signaled=True)
    parent = "I:\\repository\\probe"
    directory = parent + "\\cwd путь пробелы"
    inputs = {"parent_directory": parent, "child_directory": directory,
              "parent_sha256": hashlib.sha256(b"parent").hexdigest(),
              "child_sha256": hashlib.sha256(bytes((65, 0, 255, 128, 10, 13, 90))).hexdigest(),
              "not_directory_path": parent + "\\not-directory", "not_directory_kind": "regular",
              "not_directory_sha256": hashlib.sha256(b"file").hexdigest()}
    for row in rows:
        if row["case"] == "cwd" or row["case"].startswith("cwd-"):
            row["cwd"] = directory
    evidence = {"cwd_inputs_before": inputs, "cwd_inputs_after": copy.deepcopy(inputs),
                "kind": direct.KIND + ".runtime", "status": "passed", "rows": rows,
                "binary_sha256": "fixture", "denied_sha256": "denied", "binaries_unchanged": True}
    direct.verify_runtime_report(evidence, "fixture", "denied", parent)
    rejected(lambda: direct.verify_runtime_report(evidence, "fixture", "denied", "I:\\other\\probe"))
    mutations = []
    for key, value in (("status", "failed"), ("binaries_unchanged", False),
                       ("binary_sha256", "stale"), ("denied_sha256", "stale"),
                       ("rows", rows[:-1]), ("rows", rows + rows[:1]),
                       ("rows", [rows[1], rows[0], *rows[2:]])):
        changed = copy.deepcopy(evidence)
        changed[key] = value
        mutations.append(changed)
    for index, key, value in ((0, "exit", 73), (0, "stdout_hex", ""), (0, "stderr_hex", "0a"),
                              (10, "exit", 74), (len(rows) - 4, "held_handles_signaled", False),
                              (len(rows) - 4, "alive_before_observation", False),
                              (len(rows) - 3, "descendant_pids", [102, 102]),
                              (len(rows) - 3, "parent_pid", 102), (len(rows) - 3, "exit", True),
                              (11, "cwd", "C:\\stale"), (11, "stdout_hex", ""),
                              (len(rows) - 2, "held_handles_signaled", False),
                              (len(rows) - 1, "descendant_pids", [102, 102])):
        changed = copy.deepcopy(evidence)
        changed["rows"][index][key] = value
        mutations.append(changed)
    for key, value in (("cwd_inputs_before", None), ("cwd_inputs_after", {})):
        changed = copy.deepcopy(evidence)
        changed[key] = value
        mutations.append(changed)
    for key, value in (("child_directory", "C:\\stale"), ("parent_sha256", "stale"), ("child_sha256", "stale"),
                       ("not_directory_path", "C:\\missing"), ("not_directory_kind", "directory"),
                       ("not_directory_sha256", hashlib.sha256(b"tampered").hexdigest())):
        changed = copy.deepcopy(evidence)
        changed["cwd_inputs_before"][key] = value
        changed["cwd_inputs_after"][key] = value
        mutations.append(changed)
    for key in ("not_directory_path", "not_directory_kind", "not_directory_sha256"):
        changed = copy.deepcopy(evidence)
        for field in ("cwd_inputs_before", "cwd_inputs_after"):
            changed[field].pop(key)
        mutations.append(changed)
        changed = copy.deepcopy(evidence)
        changed["cwd_inputs_after"][key] = "changed"
        mutations.append(changed)
    for changed in mutations:
        rejected(lambda candidate=changed: direct.verify_runtime_report(candidate, "fixture", "denied", parent))

    cwd_work = tmp / "native-cwd-inputs"
    cwd_work.mkdir()
    cwd_child = cwd_work / "cwd путь пробелы"
    cwd_child.mkdir()
    (cwd_work / "cwd.bin").write_bytes(b"parent")
    (cwd_child / "cwd.bin").write_bytes(bytes((65, 0, 255, 128, 10, 13, 90)))
    negative_input = cwd_work / "not-directory"
    negative_input.write_bytes(b"file")
    pinned = direct.cwd_input_snapshot(cwd_work)
    assert pinned["not_directory_path"] == str(negative_input) and pinned["not_directory_kind"] == "regular"
    assert pinned["not_directory_sha256"] == hashlib.sha256(b"file").hexdigest()
    negative_input.unlink()
    rejected(lambda: direct.cwd_input_snapshot(cwd_work))
    negative_input.mkdir()
    rejected(lambda: direct.cwd_input_snapshot(cwd_work))
    negative_input.rmdir()
    negative_input.write_bytes(b"tampered")
    assert direct.cwd_input_snapshot(cwd_work) != pinned
    negative_input.write_bytes(b"file")
    assert direct.cwd_input_snapshot(cwd_work) == pinned

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
    changed_image = bytes(image[:-1]) + b"\x01"
    read_bytes = Path.read_bytes

    def read_then_change(path):
        data = read_bytes(path)
        path.write_bytes(changed_image)
        return data

    with patch.object(Path, "read_bytes", autospec=True, side_effect=read_then_change):
        inspected = direct.inspect_image(binary, ["kernel32.dll"])
    assert inspected == {"sha256": hashlib.sha256(image).hexdigest(), "bytes": len(image),
                         "machine": "x86_64", "imports": ["kernel32.dll"]}
    assert direct.inspect_image(binary, ["kernel32.dll"]) == {
        **inspected, "sha256": hashlib.sha256(changed_image).hexdigest(),
    }
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

    root = tmp / "process-snapshot"
    work = root / "work"
    work.mkdir(parents=True)
    entry = "probe.ouro"
    source = root / entry
    source.write_bytes(b'import "a.ouro";\n')
    for name in ("a.ouro", "b.ouro"):
        (root / name).write_text("-- import leaf\n", encoding="utf-8")
    producer = root / "producer.exe"
    producer.write_bytes(b"producer")
    checks = []
    original_time = source.stat().st_mtime_ns

    def change_import(_label, command, _timeout):
        assert command[4:] == ["a.ouro", entry]
        source.write_bytes(b'import "b.ouro";\n')
        os.utime(source, ns=(source.stat().st_atime_ns, original_time))
        assert source.stat().st_mtime_ns == original_time
        logical = command[3]
        (root / logical).write_bytes(image)
        return replace(timed, stdout=logical + "\n")

    with (patch.multiple(direct, ROOT=root, API=entry, CAPTURE=entry, DENIED=entry,
                         CLI_ENTRIES=(), TOOLCHAIN_ENTRIES=(), RELEASE_ENTRIES=(),
                         RELEASE_STREAM_ENTRY=entry, REJECTIONS=(), IMPORTS={entry: ("kernel32.dll",)},
                         os=SimpleNamespace(name="nt")),
          patch.object(frontend, "ROOT", root),
          patch.object(module_cache, "quoted_import_targets", wraps=module_cache.quoted_import_targets) as parses):
        try:
            direct.run_section(producer, work, change_import, 1, 1, lambda: checks.append(True))
        except ValueError as error:
            assert str(error) == "native process sources or producer changed"
        else:
            raise AssertionError("same-size import change was accepted after native emission")
        assert len(checks) == 2
        assert [call.args[1] for call in parses.call_args_list] == [entry, "a.ouro", entry, "b.ouro"]

def test_frontend_native_toolchain_protocol(tmp: Path) -> None:
    """Synthetic source and byte receipts are separate from native stage acceptance."""
    import copy
    from dataclasses import replace

    import frontend_native_process as direct
    from ourosmith.limits import RunBytesResult, RunResult

    def rejected(operation):
        try:
            operation()
        except (OSError, ValueError, KeyError, TypeError):
            return
        raise AssertionError("incomplete native toolchain fixture receipt accepted")

    names = direct.toolchain_law_names()
    assert [len(names[entry]) for entry, _label, _count in direct.TOOLCHAIN_LAWS] == [60, 18, 19]
    source_outputs = {}
    for entry, family, count in direct.TOOLCHAIN_LAWS:
        text = (ROOT / entry).read_text(encoding="utf-8")
        source_names = re.findall(
            r'MkPair String Bool "(native-toolchain(?:-reader|-io)?/[^"\n]+)"', text)
        assert source_names == names[entry] and len(source_names) == count, entry
        footers = re.findall(r'\bprecision_run\s+"([^"\n]+)"', text)
        assert footers == [family], (entry, footers, family)
        source_outputs[entry] = (
            "".join("PRECISION_OK " + name + "\n" for name in source_names).encode()
            + f"PRECISION_SUITE {footers[0]} rows={len(source_names)}\n".encode()
        )
    root = tmp / "toolchain-protocol-root"
    root.mkdir()
    producer = root / "producer.exe"
    producer.write_bytes(b"synthetic current producer")
    closures = {entry: ["std/io.ouro", entry] for entry in direct.TOOLCHAIN_ENTRIES}
    lineage = {"producer": str(producer), "runtime_inputs": {"closures": closures}}
    for entry, labels in names.items():
        output = root / entry
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("".join(f'MkPair String Bool "{label}"\n' for label in labels), encoding="utf-8")
    calls, input_checks = [], []

    def image(path, imports):
        assert tuple(imports) == direct.IMPORTS[direct.API]
        return {"sha256": direct.sha256_file(path), "bytes": path.stat().st_size,
                "machine": "x86_64", "imports": list(imports)}

    def run(label, command, timeout, *, cwd=None, capture_bytes=False, environment_overrides=None):
        calls.append((label, command, timeout, cwd, capture_bytes, environment_overrides))
        if label.startswith("toolchain-emit-"):
            assert timeout == 90 and cwd is None and not capture_bytes and environment_overrides is None
            entry, logical = command[1:3]
            assert command == [str(producer), entry, logical, *closures[entry]]
            (root / logical).write_bytes(("synthetic PE " + entry).encode())
            phase = (f"n1-host: check units={len(closures[entry])} live=1\n"
                     "n1-host: CHECK_OK live=1 total=2\nn1-host: recheck live=1\n"
                     "n1-host: RECHECK_OK live=1\nn1-host: TYPES_OK live=1\n"
                     "n1-host: lower live=1\nn1-host: BUILD_OK live=1\n"
                     "n1-host: mir functions=1 live=1\nn1-host: mir-check live=1\n"
                     "n1-host: gc-infer live=1\nn1-host: annotate live=1\nn1-host: codegen live=1\n"
                     f"n1-host: LOWER_OK live=1\nn1-host: WROTE {logical} live=1\n")
            return RunResult("ok", 0, logical + "\n", phase, 0, 0, command)
        entry, _family, _count = next(row for row in direct.TOOLCHAIN_LAWS if label == "toolchain-" + row[1])
        assert timeout == 3 and capture_bytes
        if entry == direct.TOOLCHAIN_LAWS[2][0]:
            assert environment_overrides == direct.TOOLCHAIN_ENV and len(command) == 3
            assert cwd == Path(command[0]).parent.parent / "unrelated cwd 雪"
            assert Path(command[1]).name == "toolchain_protocol_child.exe"
            assert Path(command[2]).name == "io inputs 雪" and not Path(command[2]).exists()
            Path(command[2]).mkdir()
        else:
            assert cwd == root and environment_overrides == {} and len(command) == 1
        stdout = source_outputs[entry]
        work = Path(command[0]).parents[3]
        (work / (label + ".out")).write_bytes(stdout)
        (work / (label + ".err")).write_bytes(b"")
        return RunBytesResult("ok", 0, stdout, b"", 0, 0, command)

    work = root / "host"
    (work / "native-process").mkdir(parents=True)
    with patch.object(direct, "ROOT", root), patch.object(direct, "cli_lineage", return_value=lineage) as check_lineage, \
            patch.object(direct, "inspect_image", side_effect=image):
        report = direct.run_toolchain_section(producer, work, run, 90, 3, lambda: input_checks.append(True))
        parse_bytes = check_lineage.call_args.kwargs["parse_bytes"]
        assert callable(parse_bytes) and check_lineage.call_count == 18
        assert all(call.kwargs["parse_bytes"] is parse_bytes for call in check_lineage.call_args_list)
        assert report["status"] == "passed" and report["transport_only"] is True and report["native_bootstrap"] is False
        assert len(calls) == 7 and len(input_checks) >= 14
        assert [call[1][1] for call in calls[:4]] == list(direct.TOOLCHAIN_ENTRIES)
        assert [row["entry"] for row in report["rows"]] == [entry for entry, _label, _count in direct.TOOLCHAIN_LAWS]
        direct.verify_toolchain_report(report, work)
        mutations = []
        for key, value in (("status", "failed"), ("native_bootstrap", True), ("transport_only", False),
                           ("rows", report["rows"][:-1]), ("rows", report["rows"] + report["rows"][:1]),
                           ("rows", [report["rows"][1], report["rows"][0], report["rows"][2]]),
                           ("law_names", {}), ("images", {}), ("lineage", {})):
            changed = copy.deepcopy(report)
            changed[key] = value
            mutations.append(changed)
        for key, value in (("status", "timeout"), ("status", "memory"), ("returncode", 73), ("returncode", 259),
                           ("returncode", False), ("stdout_hex", report["rows"][2]["stdout_hex"][:-2]),
                           ("stdout_hex", report["rows"][2]["stdout_hex"] + "00"), ("stderr_hex", "00"),
                           ("capture", "text"), ("environment_overrides", {}), ("cwd", str(root)),
                           ("argv", report["rows"][2]["argv"][:-1]), ("stdout_sha256", "stale")):
            changed = copy.deepcopy(report)
            changed["rows"][2][key] = value
            mutations.append(changed)
        changed = copy.deepcopy(report)
        emission = changed["images"][direct.TOOLCHAIN_CHILD]["emission"]
        emission["stderr"] = emission["stderr"].replace("n1-host: RECHECK_OK live=1\n", "")
        mutations.append(changed)
        for changed in mutations:
            rejected(lambda candidate=changed: direct.verify_toolchain_report(candidate, work))
        output = work / "toolchain-native-toolchain-io.out"
        saved = output.read_bytes()
        output.write_bytes(saved + b"\0")
        rejected(lambda: direct.verify_toolchain_report(report, work))
        output.write_bytes(saved)
        direct.verify_toolchain_report(report, work)
        law_source = root / direct.TOOLCHAIN_LAWS[1][0]
        original = law_source.read_bytes()
        law_source.write_bytes(original + original.splitlines(keepends=True)[0])
        rejected(direct.toolchain_law_names)
        law_source.write_bytes(original)
        child = root / report["images"][direct.TOOLCHAIN_CHILD]["path"]
        saved_child = child.read_bytes()
        child.write_bytes(b"changed child")
        rejected(lambda: direct.verify_toolchain_report(report, work))
        child.write_bytes(saved_child)
        def failed_case(failure):
            failed_work = root / ("failed-" + failure)
            (failed_work / "native-process").mkdir(parents=True)
            start = len(calls)

            def failing_run(label, command, timeout, **options):
                result = run(label, command, timeout, **options)
                if label == "toolchain-native-toolchain":
                    if failure == "timeout":
                        return replace(result, status="timeout")
                    if failure == "wrong-footer":
                        stdout = result.stdout.replace(
                            b"PRECISION_SUITE native-toolchain rows=60\n",
                            b"PRECISION_SUITE native-toolchain-model rows=60\n")
                    elif failure == "wrong-count":
                        stdout = result.stdout.replace(
                            b"PRECISION_SUITE native-toolchain rows=60\n",
                            b"PRECISION_SUITE native-toolchain rows=59\n")
                    elif failure == "reordered-laws":
                        lines = result.stdout.splitlines(keepends=True)
                        stdout = b"".join([lines[1], lines[0], *lines[2:]])
                    else:
                        stdout = result.stdout + b"\0"
                    (failed_work / (label + ".out")).write_bytes(stdout)
                    return replace(result, stdout=stdout)
                return result

            rejected(lambda: direct.run_toolchain_section(producer, failed_work, failing_run, 90, 3, lambda: None))
            failed = json.loads((failed_work / "native-process/toolchain/report.json").read_text(encoding="utf-8"))
            assert failed["status"] == "failed" and len(failed["rows"]) == 1 and len(calls) - start == 5
            assert not (failed_work / "native-process/toolchain/io inputs 雪").exists()

        for failure in ("timeout", "extra-byte", "wrong-footer", "wrong-count", "reordered-laws"):
            failed_case(failure)


def test_frontend_native_release_protocol(tmp: Path) -> None:
    """Synthetic receipt validation does not supply native release evidence."""
    import copy
    from dataclasses import replace

    import frontend_native_process as direct
    from ourosmith.limits import RunBytesResult, RunResult

    def rejected(operation):
        try:
            operation()
        except (OSError, ValueError, KeyError, TypeError):
            return
        raise AssertionError("incomplete native release fixture receipt accepted")

    names = direct.source_law_names("release-stage")
    assert [len(names[entry]) for entry, _label, _count in direct.RELEASE_LAWS] == [71, 12]
    assert tuple(names[direct.RELEASE_ENTRIES[0]]) == direct.RELEASE_MODEL_NAMES
    assert len(direct.RELEASE_MODEL_NAMES[:48]) == 48 and len(direct.RELEASE_MODEL_NAMES[48:]) == 23
    root = tmp / "release-protocol-root"
    root.mkdir()
    producer = root / "producer.exe"
    producer.write_bytes(b"synthetic current producer")
    closures = {entry: ["std/io.ouro", entry] for entry in direct.RELEASE_ENTRIES}
    lineage = {"producer": str(producer), "runtime_inputs": {"closures": closures}}
    for entry, labels in names.items():
        output = root / entry
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("".join(f'MkPair String Bool "{label}"\n' for label in labels), encoding="utf-8")
    calls, input_checks = [], []

    def image(path, imports, symbols):
        assert tuple(imports) == direct.IMPORTS[direct.API] and symbols == direct.RELEASE_SYMBOLS
        return {"sha256": direct.sha256_file(path), "bytes": path.stat().st_size,
                "machine": "x86_64", "imports": list(imports)}

    def fixture_files(fixture):
        expected = {"source 雪.bin": bytes((65, 0, 255, 13, 10, 66)), "empty.bin": b"",
                    "bundle 雪/bin/coil.exe": bytes((65, 0, 255, 13, 10, 66)), "bundle 雪/src/empty": b"",
                    "corrupt/bin/coil.exe": b"broken", "corrupt/src/empty": b"broken",
                    "changed-source/bin/coil.exe": bytes((65, 0, 255, 13, 10, 66)), "changed-source/src/empty": b"",
                    "extra-output/bin/coil.exe": bytes((65, 0, 255, 13, 10, 66)), "extra-output/src/empty": b"",
                    "extra-output/unexpected.bin": b"extra"}
        for name, data in expected.items():
            path = fixture / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def run(label, command, timeout, *, cwd=None, capture_bytes=False, environment_overrides=None):
        calls.append((label, command, timeout, cwd, capture_bytes, environment_overrides))
        if label.startswith("release-stage-emit-"):
            assert timeout == 90 and cwd is None and not capture_bytes and environment_overrides is None
            entry, logical = command[1:3]
            assert command == [str(producer), entry, logical, *closures[entry]]
            (root / logical).write_bytes(("synthetic PE " + entry).encode())
            phase = (f"n1-host: check units={len(closures[entry])} live=1\n"
                     "n1-host: CHECK_OK live=1 total=2\nn1-host: recheck live=1\n"
                     "n1-host: RECHECK_OK live=1\nn1-host: TYPES_OK live=1\n"
                     "n1-host: lower live=1\nn1-host: BUILD_OK live=1\n"
                     "n1-host: mir functions=1 live=1\nn1-host: mir-check live=1\n"
                     "n1-host: gc-infer live=1\nn1-host: annotate live=1\nn1-host: codegen live=1\n"
                     f"n1-host: LOWER_OK live=1\nn1-host: WROTE {logical} live=1\n")
            return RunResult("ok", 0, logical + "\n", phase, 0, 0, command)
        entry, family, count = next(row for row in direct.RELEASE_LAWS if label == "release-stage-" + row[1])
        assert timeout == 3 and capture_bytes and environment_overrides == direct.RELEASE_ENV
        assert cwd == Path(command[0]).parent.parent / "unrelated cwd 雪"
        if entry == direct.RELEASE_LAWS[1][0]:
            assert len(command) == 2 and Path(command[1]).is_absolute() and not Path(command[1]).exists()
            fixture_files(Path(command[1]))
        else:
            assert len(command) == 1
        stdout = ("".join("PRECISION_OK " + name + "\n" for name in names[entry])
                  + f"PRECISION_SUITE {family} rows={count}\n").encode()
        work = Path(command[0]).parents[3]
        (work / (label + ".out")).write_bytes(stdout)
        (work / (label + ".err")).write_bytes(b"")
        return RunBytesResult("ok", 0, stdout, b"", 0, 0, command)

    def runtime_steps(report):
        return [{**row, "label": "release-stage-" + label, "environment_policy": dict(direct.RELEASE_ENV),
                 "stdout": Path(row["stdout_path"]).name, "stderr": Path(row["stderr_path"]).name}
                for row, (_entry, label, _count) in zip(report["rows"], direct.RELEASE_LAWS, strict=True)]

    work = root / "host"
    (work / "native-process").mkdir(parents=True)
    with patch.object(direct, "ROOT", root), patch.object(direct, "cli_lineage", return_value=lineage), \
            patch.object(direct, "inspect_image", side_effect=image):
        report = direct.run_release_section(producer, work, run, 90, 3, lambda: input_checks.append(True))
        assert report["status"] == "passed" and report["transport_only"] is False and report["native_bootstrap"] is False
        assert len(calls) == 4 and len(input_checks) >= 8
        assert [call[1][1] for call in calls[:2]] == list(direct.RELEASE_ENTRIES)
        direct.verify_release_report(report, work, runtime_steps(report))
        for replacement in ({}, {**direct.RELEASE_ENV, "PATH": "hosted path"}):
            steps = runtime_steps(report)
            steps[1]["environment_policy"] = replacement
            rejected(lambda steps=steps: direct.verify_release_report(report, work, steps))
        steps = runtime_steps(report)
        steps[1]["returncode"] = False
        rejected(lambda: direct.verify_release_report(report, work, steps))
        rejected(lambda: direct.verify_release_report(report, work, runtime_steps(report)[:-1]))
        rejected(lambda: direct.verify_release_report(report, work, runtime_steps(report) * 2))
        mutations = []
        for key, value in (("status", "failed"), ("native_bootstrap", True), ("transport_only", True),
                           ("execution_backend", "generated-c-host"), ("rows", report["rows"][:-1]),
                           ("rows", list(reversed(report["rows"]))), ("rows", report["rows"] + report["rows"][:1]),
                           ("law_names", {}), ("images", {}), ("lineage", {}), ("fixture_before", {}),
                           ("fixture_after", {})):
            changed = copy.deepcopy(report)
            changed[key] = value
            mutations.append(changed)
        for key, value in (("status", "timeout"), ("status", "memory"), ("returncode", 73), ("returncode", 259),
                           ("returncode", 0xFFFFFFFF), ("returncode", 0x100000000), ("returncode", -1),
                           ("returncode", False), ("stdout_hex", report["rows"][1]["stdout_hex"][:-2]),
                           ("stdout_hex", report["rows"][1]["stdout_hex"] + "00"), ("stderr_hex", "00"),
                           ("capture", "text"), ("environment_overrides", {}),
                           ("environment_overrides", {**direct.RELEASE_ENV, "PATH": "hosted path"}),
                           ("cwd", str(root)), ("argv", report["rows"][1]["argv"][:-1]),
                           ("argv", report["rows"][1]["argv"] + ["extra"]), ("stdout_sha256", "stale")):
            changed = copy.deepcopy(report)
            changed["rows"][1][key] = value
            mutations.append(changed)
        changed = copy.deepcopy(report)
        changed["rows"][1]["environment_overrides"].pop("OURO_HOSTED_COMPILER_WRAPPER")
        mutations.append(changed)
        changed = copy.deepcopy(report)
        emission = changed["images"][direct.RELEASE_ENTRIES[1]]["emission"]
        emission["stderr"] = emission["stderr"].replace("n1-host: RECHECK_OK live=1\n", "")
        mutations.append(changed)
        for changed in mutations:
            rejected(lambda candidate=changed: direct.verify_release_report(candidate, work, runtime_steps(report)))
        with patch.object(direct, "cli_lineage", return_value={**lineage, "producer": "different producer"}):
            rejected(lambda: direct.verify_release_report(report, work, runtime_steps(report)))
        for entry in direct.RELEASE_ENTRIES:
            image_path = root / report["images"][entry]["path"]
            saved = image_path.read_bytes()
            image_path.write_bytes(saved + b"\0")
            rejected(lambda: direct.verify_release_report(report, work, runtime_steps(report)))
            image_path.write_bytes(saved)
        output = work / "release-stage-native-release-stage.out"
        saved = output.read_bytes()
        output.write_bytes(saved + b"\0")
        rejected(lambda: direct.verify_release_report(report, work, runtime_steps(report)))
        output.write_bytes(saved)
        fixture = work / "native-process/release-stage/io inputs 雪"
        for relative, replacement in (("source 雪.bin", b"broken"), ("empty.bin", b"\0"),
                                      ("bundle 雪/bin/coil.exe", b"broken"), ("bundle 雪/src/empty", b"\0")):
            path = fixture / relative
            saved = path.read_bytes()
            path.write_bytes(replacement)
            rejected(lambda: direct.verify_release_report(report, work, runtime_steps(report)))
            path.write_bytes(saved)
        (fixture / "unexpected").mkdir()
        rejected(lambda: direct.verify_release_report(report, work, runtime_steps(report)))
        (fixture / "unexpected").rmdir()
        (fixture / "unexpected.bin").write_bytes(b"unexpected")
        rejected(lambda: direct.verify_release_report(report, work, runtime_steps(report)))
        (fixture / "unexpected.bin").unlink()
        law_source = root / direct.RELEASE_ENTRIES[0]
        saved = law_source.read_bytes()
        law_source.write_bytes(saved + saved.splitlines(keepends=True)[0])
        rejected(lambda: direct.verify_release_report(report, work, runtime_steps(report)))
        law_source.write_bytes(saved)
        lines = saved.splitlines(keepends=True)
        for changed_source in (lines[1] + lines[0] + b"".join(lines[2:]), b"".join(lines[:-1]),
                               saved.replace(b"native-release/stream-closed-stage-describes-exact-bytes",
                                             b"native-release/stream-unregistered")):
            law_source.write_bytes(changed_source)
            rejected(lambda: direct.verify_release_report(report, work, runtime_steps(report)))
        law_source.write_bytes(saved)
        direct.verify_release_report(report, work, runtime_steps(report))
        with patch.object(direct.os, "walk",
                          side_effect=lambda _root, **options: options["onerror"](PermissionError("unreadable"))):
            rejected(lambda: direct.verify_release_report(report, work, runtime_steps(report)))

        def failed_case(failure):
            failed_work = root / ("failed-release-" + failure)
            (failed_work / "native-process").mkdir(parents=True)

            def failing_run(label, command, timeout, **options):
                result = run(label, command, timeout, **options)
                if label == "release-stage-native-release-stage":
                    stdout, stderr = (b"partial\0\xff", b"timeout\0") if failure == "timeout" else (result.stdout, b"failure\0")
                    (failed_work / (label + ".out")).write_bytes(stdout)
                    (failed_work / (label + ".err")).write_bytes(stderr)
                    return replace(result, status="timeout" if failure == "timeout" else "ok",
                                   returncode=73, stdout=stdout, stderr=stderr)
                return result

            rejected(lambda: direct.run_release_section(producer, failed_work, failing_run, 90, 3, lambda: None))
            failed = json.loads((failed_work / "native-process/release-stage/report.json").read_text(encoding="utf-8"))
            assert failed["status"] == "failed" and len(failed["rows"]) == 2 and "fixture_after" not in failed
            row = failed["rows"][1]
            assert row["returncode"] == 73 and row["capture"] == "bytes" and row["stderr_hex"]
            assert row["stdout_hex"] == (failed_work / "release-stage-native-release-stage.out").read_bytes().hex()
            assert row["stderr_hex"] == (failed_work / "release-stage-native-release-stage.err").read_bytes().hex()

        for failure in ("timeout", "nonzero"):
            failed_case(failure)


def test_frontend_native_release_stream_protocol(tmp: Path) -> None:
    """Synthetic transport receipts do not establish native stream-copy behavior."""
    import copy
    import hashlib
    from dataclasses import asdict, replace

    import frontend_native_process as direct
    from frontend_host_suite import bytes_run_record
    from ourosmith.limits import RunBytesResult, RunResult

    def rejected(operation):
        try:
            operation()
        except (OSError, ValueError, KeyError, TypeError):
            return
        raise AssertionError("incomplete or damaged native stream-copy receipt accepted")

    cases = direct.release_stream_cases()
    assert [case["case"] for case in cases] == [
        "empty", "boundary65535", "chunk65536", "boundary65537", "multichunk131073",
        "binary", "full-Nat-cap", "Unicode-paths", "existing-stage", "same-source", "reused-action",
        "declared-cap", "actual-size-cap", "declared-size", "first-error", "deferred",
        "cli-unknown-mode", "cli-missing-arg", "cli-extra-arg", "cli-negative-declared",
        "cli-invalid-cap", "cli-actual-cap-declared"]
    assert len(cases) == 22 and cases[6]["cap"] == "18446744073709551616"
    labels = {
        "copy": ("copy-closed",), "collision": ("existing-stage-refused",),
        "reuse": ("reused-first-copy", "reused-create-refused"), "cap": ("cap-before-stage",),
        "actual-cap": ("actual-cap-before-payload",), "length": ("source-length-before-stage",),
        "deferred": ("deferred-current-input", "deferred-binary-bytes"),
    }
    binary, kept, old = bytes((65, 0, 255, 128, 13, 10, 66)), bytes((75, 69, 80, 84, 0, 255)), bytes((79, 76, 68, 0, 13, 10, 88))
    assert direct.RELEASE_STREAM_LABELS == labels and direct.RELEASE_STREAM_BYTES == binary
    pattern = bytes((index + 37 * (index // 65536)) % 256 for index in range(131073))
    assert pattern[65536] == 37 and pattern[131072] == 74 and pattern[:65536] != pattern[65536:131072]
    assert direct.release_stream_expected_files(cases[4], False) == {"source.bin": pattern}
    assert direct.release_stream_expected_files(cases[8], True) == {"source.bin": binary, "stage.bin": kept}
    assert direct.release_stream_expected_files(cases[9], True) == {"source.bin": binary}
    assert direct.release_stream_expected_files(cases[15], False) == {"source.bin": old}
    assert direct.release_stream_expected_files(cases[15], True) == {"source.bin": binary, "stage.bin": binary}

    root = tmp / "release-stream-protocol-root"
    root.mkdir()
    producer = root / "producer.exe"
    producer.write_bytes(b"synthetic common producer; never executed")
    units = ["std/io.ouro", "tools/native_release_stream_model.ouro",
             "tools/native_release_stream_windows.ouro", direct.RELEASE_STREAM_ENTRY]
    for unit in units:
        path = root / unit
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic protocol input " + unit + "\n", encoding="utf-8")
    lineage = {"producer": str(producer), "producer_sha256": direct.sha256_file(producer),
               "runtime_inputs": {"closures": {direct.RELEASE_STREAM_ENTRY: units},
                                  "sources": {unit: direct.sha256_file(root / unit) for unit in units}}}
    inert_pe = b"synthetic stream PE; never executed"

    def current_lineage(_work, **_kwargs):
        direct.require(direct.sha256_file(producer) == lineage["producer_sha256"], "changed synthetic producer")
        direct.require(all(direct.sha256_file(root / unit) == digest
                           for unit, digest in lineage["runtime_inputs"]["sources"].items()), "changed synthetic source")
        return copy.deepcopy(lineage)

    def image(path, imports, symbols):
        assert tuple(imports) == direct.IMPORTS[direct.API] and symbols == direct.RELEASE_STREAM_SYMBOLS
        assert all(symbol in symbols["kernel32.dll"] for symbol in
                   ("CreateFileW", "ReadFile", "WriteFile", "FlushFileBuffers", "GetFileSizeEx",
                    "GetFileInformationByHandleEx", "CloseHandle"))
        direct.require(path.read_bytes() == inert_pe, "changed synthetic image")
        return {"sha256": direct.sha256_file(path), "bytes": path.stat().st_size,
                "machine": "x86_64", "imports": list(imports)}

    calls, steps, input_checks = [], [], []

    def run(label, command, timeout, *, cwd=None, capture_bytes=False, environment_overrides=None):
        calls.append((label, list(command), timeout, cwd, capture_bytes, environment_overrides))
        if label == "release-stream-emit-release_stream":
            assert timeout == 90 and cwd is None and not capture_bytes and environment_overrides is None
            entry, logical = command[1:3]
            assert command == [str(producer), direct.RELEASE_STREAM_ENTRY, logical, *units] and entry == direct.RELEASE_STREAM_ENTRY
            (root / logical).write_bytes(inert_pe)
            phase = (f"n1-host: check units={len(units)} live=1\n"
                     "n1-host: CHECK_OK live=1 total=2\nn1-host: recheck live=1\n"
                     "n1-host: RECHECK_OK live=1\nn1-host: TYPES_OK live=1\n"
                     "n1-host: lower live=1\nn1-host: BUILD_OK live=1\n"
                     "n1-host: mir functions=1 live=1\nn1-host: mir-check live=1\n"
                     "n1-host: gc-infer live=1\nn1-host: annotate live=1\nn1-host: codegen live=1\n"
                     f"n1-host: LOWER_OK live=1\nn1-host: WROTE {logical} live=1\n")
            result = RunResult("ok", 0, logical + "\n", phase, 0, 0, command)
            selected_work = root / logical
            selected_work = selected_work.parent.parent.parent.parent
            stdout, stderr = result.stdout.encode(), result.stderr.encode()
            step = {"label": label, "cwd": str(root), **asdict(result)}
        else:
            assert timeout == 3 and capture_bytes and environment_overrides == direct.RELEASE_ENV
            selected_work = Path(command[0]).parent.parent.parent.parent
            case = next(case for case in cases if label == "release-stream-" + case["case"])
            _fixture, expected_cwd, expected_command = direct.release_stream_plan(selected_work, case)
            assert command == expected_command and cwd == expected_cwd and cwd.name == "unrelated cwd 雪"
            source, stage = Path(command[2]), Path(command[3])
            if case.get("refusal"):
                code, stdout, stderr = 2, b"", b"usage: native-release-stream MODE SOURCE STAGE DECLARED_BYTES BYTE_CAP\n"
            else:
                if case["mode"] == "deferred":
                    source.write_bytes(binary)
                if case["mode"] in ("copy", "reuse", "deferred"):
                    assert not stage.exists()
                    stage.write_bytes(source.read_bytes())
                verdict = "".join("PRECISION_OK native-release-stream/" + name + "\n" for name in labels[case["mode"]])
                verdict += f"PRECISION_SUITE native-release-stream rows={len(labels[case['mode']])}\n"
                code, stdout, stderr = 0, verdict.encode(), b""
            result = RunBytesResult("ok", code, stdout, stderr, 0, 0, command)
            step = {"label": label, "cwd": str(cwd), "environment_overrides": dict(environment_overrides),
                    "environment_policy": dict(environment_overrides), **bytes_run_record(result)}
        for stream, data in (("stdout", stdout), ("stderr", stderr)):
            path = selected_work / (label + (".out" if stream == "stdout" else ".err"))
            path.write_bytes(data)
            step[stream] = path.name
            step[stream + "_sha256"] = direct.sha256_file(path)
        steps.append(step)
        return result

    work = root / "host"
    (work / "native-process").mkdir(parents=True)
    with patch.object(direct, "ROOT", root), \
            patch.object(direct, "cli_lineage", side_effect=current_lineage) as check_lineage, \
            patch.object(direct, "inspect_image", side_effect=image):
        report = direct.run_release_stream_section(producer, work, run, 90, 3, lambda: input_checks.append(True))
        parse_bytes = check_lineage.call_args.kwargs["parse_bytes"]
        assert callable(parse_bytes) and check_lineage.call_count == 50
        assert all(call.kwargs["parse_bytes"] is parse_bytes for call in check_lineage.call_args_list)
        persisted = json.loads((work / "native-process/release-stream/report.json").read_text(encoding="utf-8"))
        assert persisted == report and report["status"] == "passed" and len(calls) == 23 and len(input_checks) >= 46
        assert len(report["rows"]) == 22 and [row["returncode"] for row in report["rows"]] == [0] * 16 + [2] * 6
        direct.verify_release_stream_report(persisted, work, steps)
        for altered_steps in (steps[:-1], steps + steps[:1], [steps[1], steps[0], *steps[2:]]):
            rejected(lambda selected=altered_steps: direct.verify_release_stream_report(report, work, selected))
        for index, key, value in ((0, "returncode", False), (0, "argv", []), (0, "stdout_sha256", "stale"),
                                  (1, "environment_policy", {}), (1, "capture", "text"), (1, "cwd", str(root)),
                                  (17, "returncode", 0)):
            altered_steps = copy.deepcopy(steps)
            altered_steps[index][key] = value
            rejected(lambda selected=altered_steps: direct.verify_release_stream_report(report, work, selected))

        mutations = []
        for key, value in (("kind", "other"), ("status", "failed"), ("transport_only", True),
                           ("native_bootstrap", True), ("execution_backend", "generated-c-host"),
                           ("cases", cases[:-1]), ("cases", list(reversed(cases))), ("lineage", {}),
                           ("image", {}), ("fixture_before", {}), ("rows", report["rows"][:-1]),
                           ("rows", list(reversed(report["rows"]))), ("rows", report["rows"] + report["rows"][:1])):
            changed = copy.deepcopy(report)
            changed[key] = value
            mutations.append(changed)
        for index, key, value in ((0, "status", "timeout"), (0, "status", "memory"), (0, "status", "skip"),
            (0, "returncode", 1), (0, "returncode", 73), (0, "returncode", 93), (0, "returncode", 259),
            (0, "returncode", 0xFFFFFFFF), (0, "returncode", 0x100000000), (0, "returncode", -1),
            (0, "returncode", False), (0, "capture", "text"), (0, "stdout_hex", ""), (0, "stderr_hex", "0a"),
            (0, "before", {}), (0, "after", {}), (0, "environment_overrides", {}), (0, "cwd", str(root)),
            (0, "argv", []), (4, "case", "binary"), (16, "returncode", 0), (16, "returncode", True),
            (16, "stdout_hex", "0a"), (16, "stderr_hex", ""), (16, "after", {})):
            changed = copy.deepcopy(report)
            changed["rows"][index][key] = value
            mutations.append(changed)
        changed = copy.deepcopy(report)
        changed["rows"][6]["argv"][-1] = "0"
        mutations.append(changed)
        changed = copy.deepcopy(report)
        changed["image"]["emission"]["stderr"] = changed["image"]["emission"]["stderr"].replace(
            "n1-host: RECHECK_OK live=1\n", "")
        mutations.append(changed)
        for changed in mutations:
            rejected(lambda selected=changed: direct.verify_release_stream_report(selected, work, steps))

        for path in (producer, root / units[0], work / "native-process/release-stream/images/release_stream.exe",
                     work / "release-stream-emit-release_stream.err"):
            saved = path.read_bytes()
            path.write_bytes(saved + b"stale")
            rejected(lambda: direct.verify_release_stream_report(report, work, steps))
            path.write_bytes(saved)
        for case_index, name, replacement in (
            (4, "stage.bin", pattern[65536:131072] + pattern[:65536] + pattern[131072:]),
            (4, "stage.bin", pattern[:-1]), (4, "source.bin", pattern[:-1]),
            (5, "stage.bin", binary.replace(b"\0", b"x")), (8, "stage.bin", b"changed"),
            (9, "source.bin", b"changed"), (15, "source.bin", old)):
            fixture, _cwd, _command = direct.release_stream_plan(work, cases[case_index])
            path = fixture / name
            saved = path.read_bytes()
            path.write_bytes(replacement)
            rejected(lambda: direct.verify_release_stream_report(report, work, steps))
            path.write_bytes(saved)
        for index in (11, 12, 13, 16):
            fixture, _cwd, _command = direct.release_stream_plan(work, cases[index])
            extra = fixture / "stage.bin"
            extra.write_bytes(b"")
            rejected(lambda: direct.verify_release_stream_report(report, work, steps))
            extra.unlink()
        fixture, _cwd, _command = direct.release_stream_plan(work, cases[0])
        unexpected = fixture / "unexpected"
        unexpected.mkdir()
        rejected(lambda: direct.verify_release_stream_report(report, work, steps))
        unexpected.rmdir()
        for index, replacement in ((5, bytes.fromhex(report["rows"][5]["stdout_hex"]).replace(b"\n", b"\r\n")),
                                   (5, b"\xff"), (5, b"\0"),
                                   (16, b"usage: native-release-stream\n")):
            stream = "stderr" if index == 16 else "stdout"
            path = root / report["rows"][index][stream + "_path"]
            saved = path.read_bytes()
            path.write_bytes(replacement)
            changed, selected_steps = copy.deepcopy(report), copy.deepcopy(steps)
            changed["rows"][index][stream + "_hex"] = replacement.hex()
            changed["rows"][index][stream + "_sha256"] = hashlib.sha256(replacement).hexdigest()
            selected_steps[index + 1][stream + "_hex"] = replacement.hex()
            selected_steps[index + 1][stream + "_sha256"] = hashlib.sha256(replacement).hexdigest()
            rejected(lambda selected=changed, host_steps=selected_steps:
                     direct.verify_release_stream_report(selected, work, host_steps))
            path.write_bytes(saved)
        direct.verify_release_stream_report(report, work, steps)
        for build_timeout, probe_timeout in ((901, 3), (90, 31), (0, 3), (90, 0)):
            rejected(lambda build=build_timeout, probe=probe_timeout:
                     direct.run_release_stream_section(producer, work, run, build, probe, lambda: None))

        for failure in ("timeout", "nonzero"):
            failed_work = root / ("failed-stream-" + failure)
            (failed_work / "native-process").mkdir(parents=True)

            def failing_run(label, command, timeout, selected=failure, failed=failed_work, **options):
                result = run(label, command, timeout, **options)
                if label == "release-stream-empty":
                    stdout, stderr = b"partial\0\xff", b"failed\0"
                    (failed / (label + ".out")).write_bytes(stdout)
                    (failed / (label + ".err")).write_bytes(stderr)
                    return replace(result, status="timeout" if selected == "timeout" else "ok",
                                   returncode=73, stdout=stdout, stderr=stderr)
                return result

            rejected(lambda child_work=failed_work, runner=failing_run:
                     direct.run_release_stream_section(producer, child_work, runner, 90, 3, lambda: None))
            failed = json.loads((failed_work / "native-process/release-stream/report.json").read_text(encoding="utf-8"))
            assert failed["status"] == "failed" and len(failed["rows"]) == 1
            row = failed["rows"][0]
            assert row["returncode"] == 73 and row["capture"] == "bytes"
            assert row["stdout_hex"] == (failed_work / "release-stream-empty.out").read_bytes().hex()
            assert row["stderr_hex"] == (failed_work / "release-stream-empty.err").read_bytes().hex()
            assert row["before"] and row["after"]


def test_frontend_host_environment_overlay(tmp: Path) -> None:
    """One fixture's environment cannot change later host invocations."""
    from types import SimpleNamespace

    import frontend_host_suite as host
    from ourosmith.limits import RunBytesResult, RunResult

    root = tmp / "host-environment-overlay"
    root.mkdir()
    compiler = root / "compiler.exe"
    compiler.write_bytes(b"synthetic seed")
    args = SimpleNamespace(out=root / "out", compiler=compiler, memory_mib=3072, build_timeout=900,
                           probe_timeout=30, config=None)
    before = {"inputs": {"compiler_sha256": host.sha256_file(compiler)}}
    captured = []

    def text_run(command, **options):
        assert options["env"]["OURO_TOOLCHAIN_PROTOCOL"] == "parent value"
        work = Path(command[command.index("--out") + 1])
        host.write_json_atomic(work / "build.json", {})
        (work / "backend.gen.c").write_bytes(b"synthetic generated input")
        return RunResult("ok", 0, "FRONTEND_HOST_BUILD: PASS\n", "", 0, 0, command)

    def byte_run(command, **options):
        captured.append(dict(options["env"]))
        assert options["timeout_s"] == 30 and options["memory_mb"] == 3072
        assert options["cwd"] == root and host.os.environ["OURO_TOOLCHAIN_PROTOCOL"] == "parent value"
        return RunBytesResult("ok", 0, b"A\0\xff", b"", 0, 0, command)

    def process_section(_producer, _work, run, _build_timeout, _probe_timeout, _verify_inputs, *, parse_bytes):
        assert callable(parse_bytes)
        run("overlay-first", ["synthetic"], 30, cwd=root, capture_bytes=True,
            environment_overrides={"OURO_TOOLCHAIN_PROTOCOL": "owned 雪"})
        run("overlay-restored", ["synthetic"], 30, cwd=root, capture_bytes=True)
        run("overlay-denied", ["synthetic"], 30, cwd=root, capture_bytes=True,
            environment_overrides={"PATH": "", "OURO_TEST_CHECK": None, "OURO_TEST_BUILD": None,
                                   "OURO_PKG_CHECK": None, "OURO_HOSTED_COMPILER_WRAPPER": None, "OURO_HOSTED_FMT": None})
        run("overlay-after-denial", ["synthetic"], 30, cwd=root, capture_bytes=True)
        for overrides in ({"PATH": False}, {"PATH": "", "path": "conflict"}):
            before_calls = len(captured)
            try:
                run("overlay-invalid", ["synthetic"], 30, cwd=root, capture_bytes=True, environment_overrides=overrides)
            except ValueError:
                pass
            else:
                raise AssertionError("invalid child environment overlay accepted")
            assert len(captured) == before_calls
        return {"status": "unavailable"}

    hosted = ("OURO_TEST_CHECK", "OURO_TEST_BUILD", "OURO_PKG_CHECK", "OURO_HOSTED_COMPILER_WRAPPER", "OURO_HOSTED_FMT")
    with patch.dict(host.os.environ, {"OURO_TOOLCHAIN_PROTOCOL": "parent value", "PATH": "parent path",
                                     **dict.fromkeys(hosted, "parent hosted command")}), \
            patch.object(host, "pin_one_cpu", return_value=0), patch.object(host, "snapshot", return_value=before), \
            patch.object(host, "require_snapshot"), patch.object(host, "verify_artifacts"), \
            patch.object(host, "probe_cases", return_value=[]), patch.object(host, "run_limited", side_effect=text_run), \
            patch.object(host, "run_limited_bytes", side_effect=byte_run), \
            patch.object(host, "run_native_live", return_value={"status": "unavailable"}), \
            patch.object(host, "run_native_raw_fn", return_value={"status": "unavailable"}), \
            patch.object(host, "run_heap_observer", return_value={"status": "unavailable"}), \
            patch.object(host, "run_file_status_faults", return_value={"status": "unavailable"}), \
            patch.object(host.direct_process, "run_section", side_effect=process_section) as process, \
            patch.object(host.direct_fs_create, "run_section", return_value={"status": "unavailable"}) as fs_create, \
            patch.object(host.direct_async, "run_section", return_value={"status": "unavailable"}), \
            patch.object(host.direct_fs_replace, "run_native_section", return_value={"status": "unavailable"}), \
            patch.object(host.direct_fs_read, "run_native_section", return_value={"status": "unavailable"}):
        assert host.run_suite(args, SimpleNamespace(values={"opt_level": "O1"}), []) == 0
        assert fs_create.call_args.kwargs["parse_bytes"] is process.call_args.kwargs["parse_bytes"]
    assert captured[0]["OURO_TOOLCHAIN_PROTOCOL"] == "owned 雪" and captured[1]["OURO_TOOLCHAIN_PROTOCOL"] == "parent value"
    assert {key: value for key, value in captured[0].items() if key != "OURO_TOOLCHAIN_PROTOCOL"} == {
        key: value for key, value in captured[1].items() if key != "OURO_TOOLCHAIN_PROTOCOL"}
    assert captured[2]["PATH"] == "" and not set(hosted).intersection(key.upper() for key in captured[2])
    assert captured[3] == captured[1] and captured[3]["PATH"] == "parent path"
    report = json.loads((args.out / "frontend-host.json").read_text(encoding="utf-8"))
    rows = {row["label"]: row for row in report["steps"]}
    assert rows["overlay-denied"]["environment_policy"] == {"PATH": "", **dict.fromkeys(hosted)}
    assert rows["overlay-first"]["environment_overrides"] == {"OURO_TOOLCHAIN_PROTOCOL": "owned 雪"}
    assert "environment_overrides" not in rows["overlay-restored"]
    for label in ("overlay-first", "overlay-restored"):
        row = rows[label]
        assert row["capture"] == "bytes" and row["stdout_hex"] == "4100ff" and row["stderr_hex"] == ""
        assert (Path(report["work"]) / row["stdout"]).read_bytes() == b"A\0\xff"


def test_frontend_public_cli_protocol(tmp: Path) -> None:
    """A transport receipt cannot omit cases, raw bytes, inputs or source phases."""
    import copy
    from ctypes import wintypes as windows

    import frontend_native_process as direct

    def rejected(operation):
        try:
            operation()
        except (OSError, ValueError):
            return
        raise AssertionError("incomplete public CLI transport receipt accepted")

    directory = tmp / "cli-protocol-host/native-process/public-cli"
    (directory / "images").mkdir(parents=True)
    work = directory / "runtime"
    work.mkdir()
    lineage = {"producer": "synthetic producer", "runtime_inputs": {"closures": {entry: [entry] for entry in direct.CLI_ENTRIES}}}
    spec = {"kind": direct.KIND + ".cli-spec", "directory": str(directory), "lineage": lineage,
            "cases": direct.cli_cases(), "law_names": [f"synthetic-law-{index}" for index in range(127)], "images": {}}
    assert len(spec["cases"]) == 33 and len({case["case"] for case in spec["cases"]}) == 33
    for entry, name in zip(direct.CLI_ENTRIES, direct.CLI_NAMES, strict=True):
        output = directory / "images" / name
        output.write_bytes(("synthetic PE protocol bytes " + entry).encode())
        logical = output.relative_to(tmp).as_posix()
        phase = ("n1-host: check units=1 live=1\nn1-host: CHECK_OK live=1 total=2\n"
                 "n1-host: recheck live=1\nn1-host: RECHECK_OK live=1\nn1-host: TYPES_OK live=1\n"
                 "n1-host: BUILD_OK live=1\nn1-host: mir functions=1 live=1\nn1-host: mir-check live=1\n"
                 "n1-host: gc-infer live=1\nn1-host: annotate live=1\nn1-host: codegen live=1\n"
                 f"n1-host: LOWER_OK live=1\nn1-host: WROTE {logical} live=1\n")
        spec["images"][entry] = {"path": logical, "image": {"sha256": direct.sha256_file(output), "bytes": output.stat().st_size},
                                 "emission": {"status": "ok", "returncode": 0, "stdout": logical + "\n", "stderr": phase,
                                              "argv": [lineage["producer"], entry, logical, entry]}}

    report = {"kind": direct.KIND + ".cli-runtime", "status": "passed", "execution_backend": "direct-windows-pe",
              "native_bootstrap": False, "transport_only": True, "inputs_unchanged": True, "rows": []}
    with patch.object(direct, "ROOT", tmp), patch.object(direct, "cli_lineage", return_value=lineage), \
         patch.object(direct, "cli_law_names", return_value=spec["law_names"]), \
         patch.object(direct, "inspect_image", side_effect=lambda path, _imports: {"sha256": direct.sha256_file(path), "bytes": path.stat().st_size}):
        direct.verify_cli_spec(spec, directory)
        direct.write_json_atomic(directory / "spec.json", spec)
        report["spec_sha256"] = direct.sha256_file(directory / "spec.json")
        for case in spec["cases"]:
            cwd = work / case["case"]
            cwd.mkdir()
            (cwd / "input.bin").write_bytes(direct.CLI_INPUT)
            (cwd / "cwd-input.txt").write_bytes(b"owned cwd\n")
            for parent in (cwd, cwd / "loaded image 雪", cwd / "decoy", cwd / "decoy/path"):
                parent.mkdir(parents=True, exist_ok=True)
                for tool, name in direct.CLI_SIBLINGS.items():
                    if parent == cwd / "loaded image 雪" and (tool != case["tool"] or case.get("missing")):
                        continue
                    (parent / name).write_bytes((tmp / spec["images"][direct.CLI_ENTRIES[1]]["path"]).read_bytes())
            for parent in (cwd, cwd / "loaded image 雪", cwd / "decoy"):
                (parent / "coil.exe").write_bytes((tmp / spec["images"][direct.CLI_ENTRIES[0]]["path"]).read_bytes())
            target = cwd / "loaded image 雪" / direct.CLI_SIBLINGS[case["tool"]]
            absent = bool(case.get("refused") or case.get("missing"))
            out = b"" if absent else direct.CLI_OUT
            error = (f"coil: native {case['tool']} refuses hosted override: {case['refused']}\n".encode() if case.get("refused") else
                     ("coil: process unavailable: " + str(target) + " OS error=2\n").encode() if case.get("missing") else direct.CLI_ERR)
            if not absent:
                (cwd / "launched.txt").write_bytes(b"route child\n")
            row = {"case": case["case"], "status": "ok", "exit": case["exit"], "completion_signaled": True,
                   "application": str(cwd / "loaded image 雪/coil.exe"), "argv": [str(cwd / "decoy/coil.exe"), case["tool"], *case["words"]],
                   "cwd": str(cwd), "overrides": case["overrides"], "child_marker": not absent, "inputs": direct.cli_case_inputs(cwd, case, spec)}
            for stream, data in (("stdout", out), ("stderr", error)):
                path = cwd / (stream + ".bin")
                path.write_bytes(data)
                row.update({stream + "_hex": data.hex(), stream + "_bytes": len(data), stream + "_sha256": direct.sha256_file(path)})
            report["rows"].append(row)
        direct.verify_cli_report(report, spec, work)
        direct.write_json_atomic(work / "report.json", report)
        persisted = json.loads((work / "report.json").read_text(encoding="utf-8"))
        direct.verify_cli_report(persisted, spec, work)
        for field, value in (("status", "failed"), ("inputs_unchanged", False), ("transport_only", False),
                             ("native_bootstrap", True), ("spec_sha256", "stale"), ("rows", report["rows"][:-1]),
                             ("rows", report["rows"] + report["rows"][:1]), ("rows", list(reversed(report["rows"])))):
            changed = copy.deepcopy(report)
            changed[field] = value
            rejected(lambda candidate=changed: direct.verify_cli_report(candidate, spec, work))
        for field, value in (("status", "timeout"), ("status", "memory"), ("exit", True), ("exit", -1),
                             ("completion_signaled", False), ("stdout_hex", "410aff0a"), ("stderr_hex", ""),
                             ("application", str(work / "decoy/coil.exe")), ("argv", ["coil.exe", "lsp"]), ("inputs", {})):
            changed = copy.deepcopy(report)
            changed["rows"][0][field] = value
            rejected(lambda candidate=changed: direct.verify_cli_report(candidate, spec, work))
        refused = next(case for case in spec["cases"] if case.get("refused"))
        marker = work / refused["case"] / "launched.txt"
        marker.write_bytes(b"route child\n")
        rejected(lambda: direct.verify_cli_report(report, spec, work))
        marker.unlink()
        input_path = work / spec["cases"][0]["case"] / "input.bin"
        for mutate in (lambda: input_path.write_bytes(b"changed"), input_path.unlink):
            mutate()
            rejected(lambda: direct.verify_cli_report(report, spec, work))
            input_path.write_bytes(direct.CLI_INPUT)
        changed = copy.deepcopy(spec)
        changed["cases"][0]["exit"] = False
        rejected(lambda: direct.verify_cli_spec(changed, directory))
        for field, value in (("producer", "stale producer"), ("runtime_inputs", {"closures": {}})):
            changed = copy.deepcopy(spec)
            changed["lineage"][field] = value
            rejected(lambda candidate=changed: direct.verify_cli_spec(candidate, directory))
        changed = copy.deepcopy(spec)
        changed["images"].pop(direct.CLI_ENTRIES[0])
        rejected(lambda: direct.verify_cli_spec(changed, directory))
        binary = tmp / spec["images"][direct.CLI_ENTRIES[0]]["path"]
        original = binary.read_bytes()
        for mutate in (lambda: binary.write_bytes(b"changed"), binary.unlink):
            mutate()
            rejected(lambda: direct.verify_cli_report(report, spec, work))
            binary.write_bytes(original)
        changed = copy.deepcopy(spec)
        emission = changed["images"][direct.CLI_ENTRIES[0]]["emission"]
        emission["stderr"] = emission["stderr"].replace("n1-host: RECHECK_OK live=1\n", "")
        rejected(lambda: direct.verify_cli_spec(changed, directory))
        emission["stderr"] = spec["images"][direct.CLI_ENTRIES[0]]["emission"]["stderr"]
        emission["argv"] = emission["argv"][:-1]
        rejected(lambda: direct.verify_cli_spec(changed, directory))
        direct.verify_cli_report(report, spec, work)

        def failed_observation(label, deadline):
            closed, queried, killed = [], [], []
            output_bytes, error_bytes = (b"A\x00", b"E\x00") if deadline else (direct.CLI_OUT, direct.CLI_ERR)

            class Process:
                def __init__(self, _argv, **options):
                    self.pid, self.returncode, self.was_killed = 100, None, False
                    for stream, data in (("stdout", output_bytes), ("stderr", error_bytes)):
                        options[stream].write(data)
                        options[stream].flush()
                    (options["cwd"] / "launched.txt").write_bytes(b"route child\n")

                def poll(self):
                    return self.returncode

                def kill(self):
                    self.was_killed = True
                    killed.append(self.pid)

                def wait(self, timeout):
                    assert timeout == 2
                    self.returncode = -9 if self.was_killed else 7
                    return self.returncode

            class Api:
                def OpenProcess(self, access, inherit, pid):
                    assert access == 0x100000 | 0x1000 and inherit is False and pid == 100
                    return 1

                def WaitForSingleObject(self, handle, timeout):
                    assert handle == 1 and timeout == 0
                    return 258 if deadline else 0

                def GetExitCodeProcess(self, handle, pointer):
                    assert handle == 1 and not deadline
                    direct.ctypes.cast(pointer, direct.ctypes.POINTER(windows.DWORD)).contents.value = 7
                    queried.append(7)
                    return True

                def CloseHandle(self, handle):
                    closed.append(handle)
                    return True

            spec_path = directory / label / "spec.json"
            spec_path.parent.mkdir()
            direct.write_json_atomic(spec_path, spec)
            failed_work = spec_path.parent / "runtime"
            with patch.object(direct, "cli_cases", return_value=[spec["cases"][0]]), \
                 patch.object(direct, "verify_cli_spec", return_value=spec) as verify_spec, \
                 patch.object(direct, "kernel", return_value=Api()), \
                 patch.object(direct.subprocess, "Popen", Process), \
                 patch.object(direct.subprocess, "CREATE_NO_WINDOW", 0, create=True), \
                 patch.object(direct.subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0, create=True), \
                 patch.object(direct.time, "monotonic", side_effect=[0, 21] if deadline else [0]):
                rejected(lambda: direct.cli_worker(spec_path, direct.sha256_file(spec_path), failed_work))
            parse_bytes = verify_spec.call_args.kwargs["parse_bytes"]
            assert callable(parse_bytes) and verify_spec.call_count == 4
            assert all(call.kwargs["parse_bytes"] is parse_bytes for call in verify_spec.call_args_list)
            observed = json.loads((failed_work / "report.json").read_text(encoding="utf-8"))
            assert observed["status"] == "failed" and "final_error" not in observed and len(observed["rows"]) == 1
            failed_row = observed["rows"][0]
            assert failed_row["status"] == "failed" and failed_row["inputs_verified"] is True
            assert failed_row["completion_signaled"] is (not deadline)
            assert ("exit" not in failed_row) if deadline else failed_row["exit"] == 7
            assert ("deadline" if deadline else "DWORD") in failed_row["error"]
            assert closed == [1] and queried == ([] if deadline else [7]) and killed == ([100] if deadline else [])
            if deadline:
                assert failed_row["coil_cancelled"] is True and failed_row["popen_returncode"] == -9
            for stream, data in (("stdout", output_bytes), ("stderr", error_bytes)):
                path = failed_work / failed_row["case"] / (stream + ".bin")
                assert failed_row[stream + "_state"] == "captured" and failed_row[stream + "_hex"] == data.hex()
                assert failed_row[stream + "_bytes"] == len(data) and failed_row[stream + "_sha256"] == direct.sha256_file(path)

        failed_observation("bad-dword", False)
        failed_observation("deadline", True)


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
        # The fake builder records entry into the default C build path.
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



def test_native_runtime_gc_imports() -> None:
    """The retained IO sample needs one checked owner for each native runtime provider."""
    import frontend_regen as frontend
    from structural_quality import lex

    providers = {
        ("def", "managed_allocate_raw"): "runtime/managed.ouro",
        ("def", "managed_collect"): "runtime/managed_collect.ouro",
        ("def", "managed_release_all"): "runtime/managed.ouro",
        ("def", "managed_inspect_roots"): "runtime/managed_roots.ouro",
        ("extern", "windows_exit_process"): "runtime/platform/windows_x64.ouro",
    }

    def provider_owners(units):
        owners = {key: [] for key in providers}
        for unit in units:
            tokens = [token.value for token in lex((ROOT / unit).read_text(encoding="utf-8"), "ouro")[0]]
            for index, token in enumerate(tokens[:-1]):
                key = (token, tokens[index + 1])
                if key in owners:
                    owners[key].append(unit)
        return owners

    sample = "samples/examples/io_hello.ouro"
    with patch.object(frontend, "ROOT", ROOT):
        sample_units = frontend.collect_units(sample)
        runtime_units = frontend.collect_units("std/runtime.ouro")
        io_units = frontend.collect_units("std/io.ouro")
    assert "runtime/managed.ouro" in sample_units, (sample, sample_units)
    assert set(io_units) == set(runtime_units) | {"std/io.ouro"}, (runtime_units, io_units)
    for root, units in ((sample, sample_units), ("std/runtime.ouro", runtime_units), ("std/io.ouro", io_units)):
        assert units[-1] == root and len(units) == len(set(units)), (root, units)
        owners = provider_owners(units)
        for key, owner in providers.items():
            assert owners[key] == [owner], (root, key, owners[key])


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


@patch("frontend_regen.module_lookup_capability", return_value=False)
def test_native_tool_hooks(tmp: Path, _lookup_capability) -> None:
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
                f"static ouro_v *ouro_c{gid};\n"
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
    checker_names = ["compile_checked_units", "compile_checked_source",
                     "compile_checked_source_with_origin", "compile_checked_units_with_origin",
                     "compile_checked_units_with_source_packet"]
    checker = hook(source(checker_names), ["compiler/driver.ouro"])
    assert checker.count("ouro_fe_compile_checked_units_clos();") == 1
    assert checker.count("ouro_fe_compile_checked_units_with_source_packet_clos();") == 1
    assert checker.count("ouro_v *ouro_fe_compile_checked_units_with_source_packet_clos(void);") == 1
    assert sorted(re.findall(r"=(ouro_wrap_\w+)\(ouro_clos\(", checker)) == [
        "ouro_wrap_compile_checked_units_with_origin", "ouro_wrap_quality_parse", "ouro_wrap_quality_parse",
    ], "checker-only tools require only borrowed source/units lifetimes, never backend hooks"
    parser = hook(source(["cm_load_file", "cm_load_file_cached"]), ["tools/clippy/semantic_unit.ouro"])
    assert "ouro_wrap_quality_parse(ouro_clos(" in parser
    assert "ouro_wrap_settled3(ouro_clos(" in parser
    assert "ouro_fe_compile_checked_units_clos" not in parser
    assert "ouro_wrap_x64_encode" not in parser
    encoder = hook(source(["x64_encode"]), ["compiler/native/x64.ouro"])
    assert "ouro_wrap_x64_encode(ouro_clos(" in encoder
    assert "ouro_fe_compile_checked_units_clos" not in encoder
    reachability = hook(source(["mir_reachable"]), ["compiler/native/mir_flow.ouro"])
    assert "ouro_wrap_mir_reachable(ouro_clos(" in reachability
    assert "ouro_wrap_mir_check_function" not in reachability
    instruction_types = hook(source(["mir_check_instruction"]), ["compiler/native/mir_types.ouro"])
    assert "ouro_wrap_mir_check_instruction(ouro_clos(" in instruction_types
    assert "ouro_wrap_mir_check_function" not in instruction_types
    liveness = hook(source(["mir_live_facts", "mir_live_summary_step"]),
                    ["compiler/native/mir_live.ouro"])
    assert "ouro_wrap_mir_live_summary_step(ouro_clos(" in liveness
    assert "ouro_wrap_mir_live_facts(ouro_clos(" in liveness

    module_checker = hook(source(["check_module"]), ["compiler/file_elab.ouro"])
    assert "ouro_wrap_check_module(ouro_clos(" in module_checker
    assert "ouro_fe_compile_checked_units_clos" not in module_checker
    assert "ouro_wrap_lower_recheck_program" not in module_checker

    names = ["compile_checked_units", *(name for name, _, _ in native.HOST_HOOKS),
             "compile_checked_units_with_source_packet"]
    owners = ["compiler/driver.ouro", *(owner for _, _, paths in native.HOST_HOOKS for owner in paths)]
    complete = hook(source(names), owners)
    assert "ouro_fe_compile_checked_units_clos();" in complete
    assert complete.count("ouro_fe_compile_checked_units_with_source_packet_clos();") == 1
    for index, (name, wrapper, _) in enumerate(native.HOST_HOOKS, start=11):
        # Several exports share a lifetime wrapper; each getter is hooked once.
        assignment = f"ouro_c{index}={wrapper}(ouro_clos(ouro_f{index}_,env));"
        assert complete.count(assignment) == 1, name
    assert complete.count('#include "ouro_quality_scope.h"') == 1
    native.hook_compile_checked_units(generated, owners, installed=True)
    assert generated.read_text(encoding="utf-8") == complete
    view = native.installed_hook_view(complete)
    for name in names:
        indices = re.findall(rf'case\s+(\d+):\s*return\s+"{re.escape(name)}"', complete)
        expected = re.findall(rf'case\s+{indices[0]}:\s*return\s+(ouro_g\d+)\(\)', complete)
        assert native.installed_export_getter(complete, name, view) == expected[0]
    declaration = "ouro_v *ouro_fe_compile_checked_units_clos(void);\n"
    replacement = re.search(r"static ouro_v \*ouro_g10\(void\)\{[^\n]*\}", complete).group()

    def legacy_installed(text):
        indices = re.findall(r'case\s+(\d+):\s*return\s+"compile_checked_units"', text)
        values = re.findall(rf'case\s+{indices[0]}:\s*return\s+(ouro_g\d+)\(\)', text) if indices else []
        definitions = re.findall(r"\bstatic\s+ouro_v\s*\*\s*ouro_g10(?:_d[0-9]+)?\s*\([^;{]*\)\s*\{", text)
        caches = re.findall(r"\bstatic\s+ouro_v\s*\*\s*ouro_c10(?:_d[0-9]+)?\b", text)
        return (len(indices) == 1 and values == ["ouro_g10"] and len(definitions) == len(caches) == 1
                and text.count("static ouro_v *ouro_c10;") == text.count(replacement) == 1
                and text.split("static ouro_v *ouro_g", 1)[0].count(declaration) == 1)

    parity_inputs = (
        complete,
        complete.replace('case 0: return "compile_checked_units";', ""),
        complete + 'case 99:return "compile_checked_units";\n',
        complete + "case 0:return ouro_g11();\n",
        complete + "case 0:return ouro_g10();\n",
        complete.replace("static ouro_v *ouro_c10;", ""),
        complete + "static ouro_v *ouro_c10;\n",
        complete + "static ouro_v *ouro_c10_d" + "9" * 5000 + ";\n",
        complete + "static ouro_v *ouro_c10_extra;\n",
        complete + "static ouro_v *ouro_c10é;\n",
        complete + "notstatic ouro_v *ouro_c10;\n",
        complete + "not" + replacement,
        complete + "static ouro_v *ouro_g10_d0(void){return 0;}\n",
        complete + "static ouro_v *ouro_g10(int arg=static ouro_v *ouro_g10(void){return 0;}){return 1;}\n",
        complete.replace(replacement, replacement.replace("static ouro_v", "static  ouro_v", 1)),
        complete.replace(declaration, declaration * 2, 1),
        complete + 'case 99:return "noise case 0:return ouro_g10();";\n',
        complete + 'case 99:return "noise case 0:return "compile_checked_units";\n',
    )
    for text in parity_inputs:
        try:
            native.verify_installed_getter(text, "compile_checked_units", "ouro_g10", replacement, declaration)
            indexed = True
        except RuntimeError:
            indexed = False
        assert indexed == legacy_installed(text), text[-180:]
    unicode_checked = complete.replace("ouro_g10", "ouro_g\u0661\u0660").replace("ouro_c10", "ouro_c\u0661\u0660")
    assert native.hook_checked_units_getter(unicode_checked, installed=True) == unicode_checked
    different_text = complete.encode().decode()
    assert different_text == complete and different_text is not complete
    try:
        native.installed_export_getter(different_text, "compile_checked_units", view)
    except RuntimeError as error:
        assert "different text" in str(error)
    else:
        raise AssertionError("installed hook view reused across different C text")
    malformed_installed = (
        complete.replace("ouro_fe_compile_checked_units_clos();", "ouro_clos(ouro_f10_,0);"),
        complete.replace("ouro_wrap_quality_parse(ouro_clos(", "ouro_wrap_wrong(ouro_clos(", 1),
        complete.replace('#include "ouro_quality_scope.h"\n', ""),
        complete + "static ouro_v *ouro_g10_d1(void){return 0;}\n",
        complete + "static ouro_v *ouro_c10_d1;\n",
    )
    for malformed in malformed_installed:
        generated.write_text(malformed, encoding="utf-8")
        try:
            native.hook_compile_checked_units(generated, owners, installed=True)
        except RuntimeError:
            pass
        else:
            raise AssertionError("invalid installed native host hook accepted")
        assert generated.read_text(encoding="utf-8") == malformed

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
    rejected(source(["cm_load_file"]).replace("case 0: return ouro_g10();", ""), (),
             "cm_load_file export value")
    rejected(source(["cm_load_file"]).replace("ouro_c10=ouro_clos(ouro_f10_,env);", "ouro_c10=0;"), (),
             "could not hook cm_load_file getter")
    rejected(source(["cm_load_file"]), ["tools/clippy/semantic_unit.ouro"],
             "cm_load_file_cached export name")
    rejected(source(["cm_load_file_cached"]).replace("case 0: return ouro_g10();", ""), (),
             "cm_load_file_cached export value")
    rejected(source(["cm_load_file_cached"]).replace("ouro_c10=ouro_clos(ouro_f10_,env);", "ouro_c10=0;"), (),
             "could not hook cm_load_file_cached getter")
    rejected(source(["check_module"]).replace("case 0: return ouro_g10();", ""), (),
             "check_module export value")
    rejected(source(["check_module"]).replace("ouro_c10=ouro_clos(ouro_f10_,env);", "ouro_c10=0;"), (),
             "could not hook check_module getter")
    rejected(source(["mir_check_instruction"]).replace("case 0: return ouro_g10();", ""), (),
             "mir_check_instruction export value")
    rejected(source(["mir_check_instruction"]).replace("ouro_c10=ouro_clos(ouro_f10_,env);", "ouro_c10=0;"), (),
             "could not hook mir_check_instruction getter")
    rejected(source(["x64_encode"]).replace("case 0: return ouro_g10();", ""), (),
             "x64_encode export value")
    rejected(source(["x64_encode"]).replace("ouro_c10=ouro_clos(ouro_f10_,env);", "ouro_c10=0;"), (),
             "could not hook x64_encode getter")
    rejected(source(["compile_checked_units"]).replace("case 0: return ouro_g10();", ""), (),
             "compile_checked_units getter")
    rejected(source(["compile_checked_units"]).replace("ouro_c10=ouro_clos(ouro_f10_,env);", "ouro_c10=0;"), (),
             "could not hook compile_checked_units getter")

    # Every injected symbol must be provided by normal tool sources or headers,
    # not only by the separate N1 producer executable's main translation unit.
    runtime = "\n".join((ROOT / path).read_text(encoding="utf-8")
                        for path in (*native.RUNTIME, "runtime/ouro_quality_scope.h"))
    for _, wrapper, _ in native.HOST_HOOKS:
        assert re.search(rf"ouro_v\s*\*\s*{re.escape(wrapper)}\s*\(ouro_v\s*\*raw\)\s*\{{", runtime), wrapper
    assert re.search(r"ouro_v\s*\*\s*ouro_fe_compile_checked_units_with_source_packet_clos\s*\(void\)\s*\{", runtime)

    packet_only = hook(source(["compile_checked_units_with_source_packet"]))
    assert packet_only.count("ouro_fe_compile_checked_units_with_source_packet_clos();") == 1
    assert "ouro_fe_compile_checked_units_clos" not in packet_only
    rejected(source(["compile_checked_units_with_source_packet"]).replace("case 0: return ouro_g10();", ""), (),
             "compile_checked_units_with_source_packet getter")
    rejected(source(["compile_checked_units_with_source_packet"]).replace("ouro_c10=ouro_clos(ouro_f10_,env);", "ouro_c10=0;"), (),
             "could not hook compile_checked_units_with_source_packet getter")

    origin_only = hook(source(["compile_checked_units_with_origin"]))
    assert origin_only.count("ouro_wrap_compile_checked_units_with_origin(ouro_clos(") == 1
    assert "ouro_fe_compile_checked_units_with_source_packet_clos" not in origin_only
    native.hook_compile_checked_units(generated, installed=True)
    rejected(source(["compile_checked_units_with_origin"]).replace("ouro_c10=ouro_clos(ouro_f10_,env);", "ouro_c10=0;"), (),
             "could not hook compile_checked_units_with_origin getter")


    # These are synthetic generated-shape inputs, not typed/runtime acceptance.
    import frontend_regen as frontend
    import pack_frontend as packer

    guarded_inputs = {
        "source_compactor": frontend.digest(ROOT / "scripts/compact_source.py"),
        "frontend_runtime": frontend.digest(ROOT / "runtime/frontend_link.c"),
        "compiler/lower_env.ouro": frontend.digest(ROOT / "compiler/lower_env.ouro"),
        "compiler/pipeline_abi.ouro": frontend.digest(ROOT / "compiler/pipeline_abi.ouro"),
    }
    guarded_inputs.update({
        path: frontend.digest(ROOT / path)
        for path in (*frontend.PACKED_ALIAS_TOOLS,
                     *packer.SOURCE_NAME_COMPARE_SOURCE_PATHS, *packer.ELEM_SOURCE_PATHS)
    })

    module_owner = "compiler/module_registry_base.ouro"
    scope_definitions = (
        ("module_members", 7, "ouro_clos"),
        ("module_owned_exports", 2, "ouro_fix"),
        ("module_shadow_exports", 2, "ouro_clos"),
        ("module_unique_exports", 1, "ouro_clos"),
    )

    def scope_source(module="", offset=31, definitions=scope_definitions):
        parts = ['#include "ouro_rt.h"\n']
        names, values = [], []
        for index, (name, arity, constructor) in enumerate(definitions):
            gid = offset + index * 97
            for step in reversed(range(arity)):
                suffix = "0_" * step + f"{gid}_"
                result = (f"ouro_{'fix' if name in ('module_owned_exports', 'module_shadow_exports') else 'clos'}"
                          f"(ouro_f0_{suffix},env)" if step + 1 < arity else "arg")
                parts.append(f"static ouro_v *ouro_f{suffix}(ouro_env *env0,ouro_v *arg){{"
                             f"ouro_env *env=ouro_cons(arg,env0);(void)env;return {result};}}\n")
            parts.append(f"static ouro_v *ouro_c{gid};\n"
                         f"static ouro_v *ouro_g{gid}(void){{ouro_env *env=0;(void)env;"
                         f"if(ouro_c{gid}==0){{ouro_static_begin();"
                         f"ouro_c{gid}={constructor}(ouro_f{gid}_,env);"
                         f"ouro_static_end();}}return ouro_c{gid};}}\n")
            names.append(f'case {index}: return "{name}";')
            values.append(f"case {index}: return ouro_g{gid}();")
        parts.extend((f"int ouro_export_count{module}(void){{return {len(definitions)};}}\n",
                      f"const char *ouro_export_name{module}(int i){{switch(i){{"
                      + "".join(reversed(names)) + '}return "";}\n',
                      f"ouro_v *ouro_export_value{module}(int i){{switch(i){{"
                      + "".join(values) + "}return 0;}\n"))
        return "".join(parts)

    assert re.search(r"ouro_v\s*\*\s*ouro_wrap_module_pure_scope\s*\("
                     r"ouro_v\s*\*raw,\s*unsigned long arity\)\s*\{", runtime)
    declaration = "ouro_v *ouro_wrap_module_pure_scope(ouro_v *raw, unsigned long arity);\n"
    for module, offset in (("", 31), ("_pl", 701), ("_renumbered", 4093)):
        original = scope_source(module, offset)
        assert packer.hook_module_pure_scopes(original, ("tools/unrelated.ouro",), module) == original
        scoped = packer.hook_module_pure_scopes(original, (module_owner,), module)
        assert scoped.count(declaration) == 1
        projected = scoped.replace(declaration, "", 1)
        for index, (_, arity, constructor) in enumerate(scope_definitions):
            gid = offset + index * 97
            raw = f"{constructor}(ouro_f{gid}_,env)"
            assignment = f"ouro_c{gid}=ouro_wrap_module_pure_scope({raw},{arity});"
            assert scoped.count(assignment) == 1
            projected = projected.replace(assignment, f"ouro_c{gid}={raw};", 1)
        assert projected == original, "raw curry/fix/self/body bytes changed"
        assert packer.hook_module_pure_scopes(scoped, (module_owner,), module, installed=True) == scoped
    original = scope_source()
    generated.write_bytes(original.encode())
    native.hook_compile_checked_units(generated, (module_owner,))
    assert generated.read_text(encoding="utf-8") == packer.hook_module_pure_scopes(original, (module_owner,))
    invalid_inputs = tuple(
        original.replace(f'return "{name}";', 'return "unrelated";', 1)
        for name, _arity, _constructor in scope_definitions
    ) + (
        re.sub(r'return "module_(?:members|owned_exports|shadow_exports|unique_exports)";',
               'return "unrelated";', original),
        original + "int ouro_export_count(void){return 4;}\n",
        original.replace('case 0: return "module_members";', ""),
        original.replace('case 0: return "module_members";', 'case 0: return "module_unique_exports";'),
        original.replace("return 4;", "return 5;", 1),
        original.replace("case 0: return ouro_g31();", ""),
        original.replace("case 1: return ouro_g128();", "case 1: return ouro_g31();"),
        original.replace("static ouro_v *ouro_c31;", ""),
        original.replace("static ouro_v *ouro_c31;", "static ouro_v *ouro_c31;static ouro_v *ouro_c31;"),
        original.replace("ouro_c31=ouro_clos(ouro_f31_,env);", "ouro_c31=ouro_nat(0);"),
        original.replace("return ouro_clos(ouro_f0_31_,env);", "return arg;", 1),
        original.replace("return arg;}\nstatic ouro_v *ouro_c322;",
                         "return ouro_clos(ouro_f0_322_,env);}\nstatic ouro_v *ouro_c322;"),
        original.replace('#include "ouro_rt.h"\n', ""),
        packer.hook_module_pure_scopes(original, (module_owner,)),
    )
    for invalid in invalid_inputs:
        generated.write_bytes(invalid.encode())
        try:
            native.hook_compile_checked_units(generated, (module_owner,))
        except RuntimeError:
            pass
        else:
            raise AssertionError("invalid source-owned module scope published")
        assert generated.read_bytes() == invalid.encode()
    installed = packer.hook_module_pure_scopes(original, (module_owner,))
    for malformed in (installed.replace(",7);", ",2);", 1),
                      installed.replace(declaration, declaration * 2, 1)):
        try:
            packer.hook_module_pure_scopes(malformed, (module_owner,), installed=True)
        except RuntimeError:
            pass
        else:
            raise AssertionError("malformed installed module scope accepted")
    try:
        packer.hook_module_pure_scopes(installed.replace(declaration, ""), (module_owner,), installed=True)
    except RuntimeError:
        pass
    else:
        raise AssertionError("installed module scope without prototype accepted")

    work, tu_cache = tmp / "split-module-scopes", tmp / "split-module-scope-cache"
    work.mkdir()
    tu_cache.mkdir()
    units = [module_owner, "compiler/pipeline.ouro"]
    digests = {key: frontend.FileDigest(key, "a" * 64, 1)
               for key in ("seed", "frontend_regen", "module_cache", "packer", *units)}
    digests.update(guarded_inputs)
    arguments = dict(ouro1=tmp / "synthetic-seed", fuel="200000", work=work,
                     cache_enabled=True, tu_cache=tu_cache, tag="pl", mod="_pl",
                     root="compiler/pipeline.ouro", file_name="pl.c", units=units, digests=digests)
    emitted = scope_source("_pl").encode()
    calls = []

    def fake_emit(argv, **kwargs):
        assert argv[1:] == ["--module", "_pl", "compiler/pipeline.ouro", "200000",
                            "--unit", module_owner, "--unit", "compiler/pipeline.ouro"]
        calls.append(argv)
        kwargs["stdout"].write(emitted)
        return subprocess.CompletedProcess(argv, 0)

    with patch.object(frontend.subprocess, "run", side_effect=fake_emit):
        assert frontend.emit_one(**arguments).cache == "miss"
        accepted = (work / "pl.c").read_bytes()
        assert (work / "pl.c").read_text(encoding="utf-8") == packer.hook_module_pure_scopes(
            emitted.decode(), units, "_pl")
        assert frontend.emit_one(**arguments).cache == "hit" and len(calls) == 1
        assert (work / "pl.c").read_bytes() == accepted
        changed = dict(digests, packer=frontend.FileDigest("packer", "b" * 64, 1))
        assert frontend.tu_key("pl", "_pl", arguments["root"], units, digests, "200000") != frontend.tu_key(
            "pl", "_pl", arguments["root"], units, changed, "200000")
        emitted = scope_source("_pl").replace("return 4;", "return 5;", 1).encode()
        try:
            frontend.emit_one(**dict(arguments, digests=changed))
        except RuntimeError:
            pass
        else:
            raise AssertionError("invalid split module scope emitted")
        assert (work / "pl.c").read_bytes() == accepted and len(calls) == 2
        key = frontend.tu_key("pl", "_pl", arguments["root"], units, digests, "200000")
        cache_file = tu_cache / f"_pl_{key}.c"
        cache_file.write_bytes(scope_source("_pl").encode())
        frontend.record_cached_output(cache_file, key)
        try:
            frontend.emit_one(**arguments)
        except RuntimeError:
            pass
        else:
            raise AssertionError("unhooked cached module scope published")
        assert (work / "pl.c").read_bytes() == accepted and len(calls) == 2


    prefix_definitions = (
        ("module_maps_for", 9, "ouro_clos"),
        ("module_rewrite_decls_with_opens_pure", 10, "ouro_clos"),
        ("module_rewrite_decl_pure", 10, "ouro_clos"),
        ("module_scope_maps", 4, "ouro_clos"),
        ("module_bare_ctors", 5, "ouro_clos"),
        ("module_invalid_maps", 3, "ouro_clos"),
        ("module_maps_for_cached_pure", 9, "ouro_clos"),
    )
    prefix_owners = ("compiler/module_registry.ouro", "compiler/module_names.ouro",
                     "compiler/module_names.ouro", "compiler/module_registry.ouro",
                     "compiler/module_registry.ouro", "compiler/module_names_base.ouro",
                     "compiler/module_registry.ouro")
    prefix_wrappers = ("ouro_wrap_module_maps_for_scope", "ouro_wrap_module_rewrite_decls_scope",
                       "ouro_wrap_module_rewrite_decls_scope", "ouro_wrap_module_scope_maps_scope",
                       "ouro_wrap_module_bare_ctors_scope", "ouro_wrap_module_invalid_maps_scope",
                       "ouro_wrap_module_maps_for_scope")
    unit_definition = ("module_rewrite_unit_pure", 7, "ouro_clos")
    cached_unit_definition = ("module_rewrite_unit_cached_pure", 7, "ouro_clos")
    unit_scope_definitions = (unit_definition, cached_unit_definition)
    unit_owner = "compiler/module_registry.ouro"
    combined_definitions = (*scope_definitions, *prefix_definitions, *unit_scope_definitions)

    from scoped_host_exports import _scoped_host_export_plan
    from scoped_host_export_routes import FLAT_HOST_EXPORT_ROUTES

    cached_names = ("module_maps_for_cached_pure", "module_rewrite_unit_cached_pure")
    cached_routes = tuple(row for row in FLAT_HOST_EXPORT_ROUTES if row[0] in cached_names)
    assert tuple(row[0] for row in cached_routes) == cached_names
    ownership_units = (unit_owner, "tests/cached_scope_homonyms.ouro", "tools/cached_scope_entry.ouro")
    public_source = "".join(f"def {name} : Nat := Z;\n" for name in cached_names)
    ownership_sources = {unit_owner: public_source, ownership_units[1]: public_source,
                         ownership_units[2]: "def main : Nat := Z;\n"}
    ownership_definitions = ((cached_names[0], 9, "ouro_clos"),
                             (cached_names[1], 7, "ouro_clos"),
                             ("homonym_maps", 9, "ouro_clos"), ("homonym_unit", 7, "ouro_clos"))
    ownership_c = scope_source(definitions=ownership_definitions)
    for name, homonym in zip(cached_names, ("homonym_maps", "homonym_unit"), strict=True):
        ownership_c = ownership_c.replace(f'return "{name}";', f'return "_ouro_m_0_{name}";', 1)
        ownership_c = ownership_c.replace(f'return "{homonym}";', f'return "_ouro_m_1_{name}";', 1)
    planned, _count, _tables, _labels, _values = _scoped_host_export_plan(
        ownership_c, ownership_units, ownership_units, ownership_units[-1],
        ownership_sources, cached_routes)
    for index, name in enumerate(cached_names):
        assert planned[name] == (unit_owner, name, f"_ouro_m_0_{name}", f"ouro_g{31 + index * 97}")
        for replacement in (f"private def {name} : Nat := Z;\n", ""):
            wrong_sources = dict(ownership_sources)
            wrong_sources[unit_owner] = public_source.replace(f"def {name} : Nat := Z;\n", replacement, 1)
            try:
                _scoped_host_export_plan(ownership_c, ownership_units, ownership_units,
                                         ownership_units[-1], wrong_sources, cached_routes)
            except RuntimeError:
                pass
            else:
                raise AssertionError(f"private or foreign-only cached scope source accepted: {name}")
        for malformed in (
            ownership_c.replace(f'return "_ouro_m_0_{name}";', 'return "unrelated";', 1),
            ownership_c.replace(f'return "_ouro_m_1_{name}";', f'return "_ouro_m_0_{name}";', 1),
            ownership_c.replace("int ouro_export_count(void){return 4;}",
                                "int ouro_export_count(void){return 3;}", 1),
        ):
            assert malformed != ownership_c
            try:
                _scoped_host_export_plan(malformed, ownership_units, ownership_units,
                                         ownership_units[-1], ownership_sources, cached_routes)
            except RuntimeError:
                pass
            else:
                raise AssertionError(f"missing or malformed cached scope export accepted: {name}")
    try:
        _scoped_host_export_plan(ownership_c, ownership_units, ownership_units,
                                 ownership_units[-1], ownership_sources, (*cached_routes, cached_routes[0]))
    except RuntimeError:
        pass
    else:
        raise AssertionError("duplicate cached scope source route accepted")
    homonym_units = ownership_units[1:]
    homonym_c = scope_source(definitions=ownership_definitions[:2])
    for name in cached_names:
        homonym_c = homonym_c.replace(f'return "{name}";', f'return "_ouro_m_0_{name}";', 1)
    homonym_plan, _count, _tables, _labels, _values = _scoped_host_export_plan(
        homonym_c, homonym_units, homonym_units, homonym_units[-1],
        {unit: ownership_sources[unit] for unit in homonym_units}, cached_routes)
    assert not any(name in homonym_plan for name in cached_names)
    prefix_units = (module_owner, prefix_owners[0], prefix_owners[1], prefix_owners[5])
    for wrapper in prefix_wrappers:
        assert re.search(rf"ouro_v\s*\*\s*{wrapper}\s*\(ouro_v\s*\*raw\)\s*\{{", runtime), wrapper
    for module, offset in (("", 31), ("_pl", 701), ("_renumbered", 4093)):
        original = scope_source(module, offset, combined_definitions)
        scoped = packer.hook_module_pure_scopes(original, prefix_units, module)
        projected = scoped.replace(declaration, "", 1)
        for index, (_name, arity, constructor) in enumerate((*scope_definitions, *prefix_definitions)):
            gid = offset + index * 97
            raw = f"{constructor}(ouro_f{gid}_,env)"
            if index < 4:
                assignment = f"ouro_c{gid}=ouro_wrap_module_pure_scope({raw},{arity});"
            else:
                wrapper = prefix_wrappers[index - 4]
                prototype = f"ouro_v *{wrapper}(ouro_v *raw);\n"
                assert scoped.count(prototype) == 1
                projected = projected.replace(prototype, "", 1)
                assignment = f"ouro_c{gid}={wrapper}({raw});"
            assert scoped.count(assignment) == 1
            projected = projected.replace(assignment, f"ouro_c{gid}={raw};", 1)
        for unit_index, _definition in enumerate(unit_scope_definitions):
            gid = offset + (len(scope_definitions) + len(prefix_definitions) + unit_index) * 97
            raw = f"ouro_clos(ouro_f{gid}_,env)"
            assignment = f"ouro_c{gid}=ouro_wrap_module_pure_scope({raw},7);"
            assert scoped.count(assignment) == 1
            projected = projected.replace(assignment, f"ouro_c{gid}={raw};", 1)
        assert projected == original, "scope installer changed raw bodies or partial chains"
        assert scoped.count(prefix_wrappers[1]) == 3, "shared declaration bridge needs two getters and one prototype"
        assert packer.hook_module_pure_scopes(scoped, prefix_units, module, installed=True) == scoped
    original = scope_source(definitions=combined_definitions)
    generated.write_bytes(original.encode())
    native.hook_compile_checked_units(generated, prefix_units)
    assert generated.read_text(encoding="utf-8") == packer.hook_module_pure_scopes(original, prefix_units)

    for definition, owner, wrapper in zip(prefix_definitions, prefix_owners, prefix_wrappers, strict=True):
        name, arity, _constructor = definition
        owned_definitions = tuple(row for row, source in zip(prefix_definitions, prefix_owners, strict=True)
                                  if source == owner) + (unit_scope_definitions if owner == unit_owner else ())
        index = owned_definitions.index(definition)
        gid = 31 + index * 97
        original = scope_source(definitions=owned_definitions)
        assert packer.hook_module_pure_scopes(original, ("tools/unrelated.ouro",)) == original
        installed = packer.hook_module_pure_scopes(original, (owner,))
        prototype = f"ouro_v *{wrapper}(ouro_v *raw);\n"
        assert installed.count(prototype) == 1
        assert installed.count(declaration) == int(owner == unit_owner)
        assert installed.count(wrapper) == sum(
            source == owner and selected == wrapper
            for source, selected in zip(prefix_owners, prefix_wrappers, strict=True)) + 1
        assert f"ouro_c{gid}={wrapper}(ouro_clos(ouro_f{gid}_,env));" in installed
        assert packer.hook_module_pure_scopes(installed, (owner,), installed=True) == installed
        malformed_inputs = (
            scope_source(definitions=tuple((name, 7, "ouro_clos") if row == definition else row
                                           for row in owned_definitions)),
            scope_source(definitions=tuple((name, arity + 1, "ouro_clos") if row == definition else row
                                           for row in owned_definitions)),
            original.replace(f'return "{name}";', 'return "unrelated";', 1),
            original.replace(f"case {index}: return ouro_g{gid}();", "", 1),
            original.replace(f"ouro_c{gid}=ouro_clos(ouro_f{gid}_,env);", f"ouro_c{gid}=0;", 1),
        ) + tuple(
            original.replace(f"return ouro_clos(ouro_f{'0_' * (step + 1)}{gid}_,env);",
                             "return arg;", 1)
            for step in range(arity - 1)
        )
        for malformed in malformed_inputs:
            assert malformed != original
            generated.write_bytes(malformed.encode())
            try:
                native.hook_compile_checked_units(generated, (owner,))
            except RuntimeError:
                pass
            else:
                raise AssertionError(f"malformed prefix route published: {name}")
            assert generated.read_bytes() == malformed.encode()
        for malformed in (installed.replace(prototype, "", 1),
                          installed.replace(prototype, prototype * 2, 1),
                          installed.replace(f"{wrapper}(ouro_clos(ouro_f{gid}_,env))",
                                            f"ouro_wrap_module_pure_scope(ouro_clos(ouro_f{gid}_,env),7)", 1),
                          installed + f"/* unexpected {wrapper} */\n") + (
                              (installed.replace(f"{wrapper}(ouro_clos(ouro_f{gid}_,env))",
                                                 f"ouro_wrap_module_pure_scope(ouro_clos(ouro_f{gid}_,env),3)", 1),)
                              if name == "module_invalid_maps" else ()):
            try:
                packer.hook_module_pure_scopes(malformed, (owner,), installed=True)
            except RuntimeError:
                pass
            else:
                raise AssertionError(f"invalid installed prefix route accepted: {name}")
    prefix_contract = packer.MODULE_PURE_SCOPE_PREFIXES
    for invalid_contract in ((*prefix_contract[:4], *prefix_contract[5:]), tuple(reversed(prefix_contract)),
                             ((prefix_contract[0][0], 9, 3, *prefix_contract[0][3:]), *prefix_contract[1:]),
                             ((prefix_contract[0][0], 10, 2, *prefix_contract[0][3:]), *prefix_contract[1:]),
                             (*prefix_contract[:2], (prefix_contract[2][0], 10, 2, *prefix_contract[2][3:]),
                              *prefix_contract[3:]),
                             (*prefix_contract[:2], (*prefix_contract[2][:4], prefix_contract[0][4]),
                              *prefix_contract[3:]),
                             (*prefix_contract[:2], ("module_rewrite_expr_with_opens_pure", *prefix_contract[2][1:]),
                              *prefix_contract[3:]),
                             (*prefix_contract[:3], (prefix_contract[3][0], 9, 2, *prefix_contract[3][3:]),
                              *prefix_contract[4:]),
                             (*prefix_contract[:3], (prefix_contract[3][0], 4, 3, *prefix_contract[3][3:]),
                              *prefix_contract[4:]),
                             (*prefix_contract[:4], (prefix_contract[4][0], 5, 2, *prefix_contract[4][3:]),
                              *prefix_contract[5:]),
                             (*prefix_contract[:4], (*prefix_contract[4][:4], prefix_contract[3][4]),
                              *prefix_contract[5:]),
                             (*prefix_contract[:5], *prefix_contract[6:]),
                             prefix_contract[:-1],
                             (*prefix_contract[:5], (prefix_contract[5][0], 4, *prefix_contract[5][2:]),
                              *prefix_contract[6:]),
                             (*prefix_contract[:5], (prefix_contract[5][0], 3, 2, *prefix_contract[5][3:]),
                              *prefix_contract[6:]),
                             (*prefix_contract[:5], (*prefix_contract[5][:3], "compiler/module_names.ouro",
                                                    prefix_contract[5][4]), *prefix_contract[6:]),
                             (*prefix_contract[:5], (*prefix_contract[5][:4], prefix_contract[4][4]),
                              *prefix_contract[6:]),
                             (*prefix_contract, prefix_contract[5]),
                             (*prefix_contract, prefix_contract[-1]),
                             (*prefix_contract[:-1], (prefix_contract[-1][0], 8, *prefix_contract[-1][2:])),
                             (*prefix_contract[:-1], (prefix_contract[-1][0], 9, 3, *prefix_contract[-1][3:])),
                             (*prefix_contract[:-1], (*prefix_contract[-1][:3], "compiler/module_names.ouro",
                                                     prefix_contract[-1][4])),
                             (*prefix_contract[:-1], (*prefix_contract[-1][:4], prefix_contract[1][4]))):
        with patch.object(packer, "MODULE_PURE_SCOPE_PREFIXES", invalid_contract):
            try:
                packer.hook_module_pure_scopes(
                    scope_source(definitions=combined_definitions), prefix_units)
            except RuntimeError:
                pass
            else:
                raise AssertionError("invalid prefix contract accepted")

    for selected_unit in unit_scope_definitions:
        unit_name, unit_arity, _constructor = selected_unit
        unit_definitions = tuple(row for row, owner in zip(prefix_definitions, prefix_owners, strict=True)
                                 if owner == unit_owner) + unit_scope_definitions
        unit_index = unit_definitions.index(selected_unit)
        unit_gid = 31 + unit_index * 97
        unit_original = scope_source(definitions=unit_definitions)
        unit_installed = packer.hook_module_pure_scopes(unit_original, (unit_owner,))
        unit_assignment = f"ouro_c{unit_gid}=ouro_wrap_module_pure_scope(ouro_clos(ouro_f{unit_gid}_,env),7);"
        assert unit_installed.count(declaration) == 1 and unit_installed.count(unit_assignment) == 1
        assert packer.hook_module_pure_scopes(unit_installed, (unit_owner,), installed=True) == unit_installed
        assert packer.hook_module_pure_scopes(unit_original, ("tools/unrelated.ouro",)) == unit_original
        owner_original = scope_source(definitions=combined_definitions)
        owner_installed = packer.hook_module_pure_scopes(owner_original, (unit_owner,))
        assert owner_installed.count("ouro_wrap_module_pure_scope") == 3
        for index, (_name, _arity, constructor) in enumerate(scope_definitions):
            gid = 31 + index * 97
            assert f"ouro_c{gid}={constructor}(ouro_f{gid}_,env);" in owner_installed
        assert packer.hook_module_pure_scopes(owner_installed, (unit_owner,), installed=True) == owner_installed
        unit_headers = tuple(
            f"static ouro_v *ouro_f{'0_' * step}{unit_gid}_(ouro_env *env0,ouro_v *arg){{"
            for step in range(unit_arity)
        )
        unit_partials = tuple(
            f"return ouro_clos(ouro_f{'0_' * (step + 1)}{unit_gid}_,env);"
            for step in range(unit_arity - 1)
        )
        malformed_unit_inputs = tuple(
            scope_source(definitions=tuple((unit_name, arity, "ouro_clos") if row == selected_unit else row
                                          for row in unit_definitions))
            for arity in (6, 8)
        ) + (
            unit_original.replace(f'return "{unit_name}";', 'return "unrelated";', 1),
            unit_original.replace(f'case {unit_index}: return "{unit_name}";',
                                  f'case {unit_index}: return "{unit_name}";' * 2, 1),
            unit_original.replace(f"case {unit_index}: return ouro_g{unit_gid}();", "", 1),
            unit_original.replace(f"static ouro_v *ouro_c{unit_gid};", "", 1),
            unit_original.replace(f"static ouro_v *ouro_c{unit_gid};",
                                  f"static ouro_v *ouro_c{unit_gid};" * 2, 1),
            unit_original.replace(f"ouro_c{unit_gid}=ouro_clos(ouro_f{unit_gid}_,env);",
                                  f"ouro_c{unit_gid}=0;", 1),
        ) + tuple(unit_original.replace(header, header.replace("ouro_v *arg", "void"), 1)
                  for header in unit_headers) + tuple(
                      unit_original.replace(header, header * 2, 1) for header in unit_headers
                  ) + tuple(unit_original.replace(partial, "return arg;", 1) for partial in unit_partials)
        for malformed in malformed_unit_inputs:
            assert malformed != unit_original
            generated.write_bytes(malformed.encode())
            try:
                native.hook_compile_checked_units(generated, (unit_owner,))
            except RuntimeError:
                pass
            else:
                raise AssertionError("malformed module rewrite unit route published")
            assert generated.read_bytes() == malformed.encode()
        invalid_installed_units = (
            unit_installed.replace(declaration, "", 1),
            unit_installed.replace(declaration, declaration * 2, 1),
            unit_installed.replace(f'return "{unit_name}";', 'return "unrelated";', 1),
        ) + tuple(
            unit_installed.replace(unit_assignment, unit_assignment.replace(",7);", f",{arity});"), 1)
            for arity in (0, 1, 2, 3, 6, 8)
        ) + tuple(unit_installed.replace(partial, "return arg;", 1) for partial in unit_partials)
        for malformed in invalid_installed_units:
            assert malformed != unit_installed
            try:
                packer.hook_module_pure_scopes(malformed, (unit_owner,), installed=True)
            except RuntimeError:
                pass
            else:
                raise AssertionError("invalid installed module rewrite unit route accepted")
        contract_name = ("MODULE_REWRITE_UNIT_PURE_SCOPE" if selected_unit == unit_definition
                         else "MODULE_REWRITE_CACHED_UNIT_PURE_SCOPE")
        contract_error = ("invalid module rewrite unit pure scope contract" if selected_unit == unit_definition
                          else "invalid module rewrite cached unit pure scope contract")
        for invalid_contract in (
            (), (unit_name, 6, unit_owner), (unit_name, 8, unit_owner),
            (unit_name, 7, module_owner), (unit_name, 7, "compiler/module_names.ouro"),
            (unit_name, 7, "compiler/module_registry*.ouro"),
            ("module_rewrite_units_with_metadata", 7, unit_owner),
            (unit_name, 7, unit_owner, unit_owner),
        ):
            with patch.object(packer, contract_name, invalid_contract):
                try:
                    packer.hook_module_pure_scopes(unit_original, (unit_owner,))
                except RuntimeError as error:
                    assert str(error) == contract_error
                else:
                    raise AssertionError("invalid module rewrite unit contract accepted")

    work, tu_cache = tmp / "split-prefix-scopes", tmp / "split-prefix-cache"
    work.mkdir()
    tu_cache.mkdir()
    for definition, owner in (*zip(prefix_definitions, prefix_owners, strict=True),
                              *((row, unit_owner) for row in unit_scope_definitions)):
        entry = ("declaration.ouro" if definition[0] == "module_rewrite_decl_pure"
                 else ("scope-maps.ouro" if definition[0] == "module_scope_maps"
                       else ("bare-ctors.ouro" if definition[0] == "module_bare_ctors"
                             else ("invalid-maps.ouro" if definition[0] == "module_invalid_maps" else "entry.ouro"))))
        if definition in unit_scope_definitions:
            entry = "rewrite-unit.ouro" if definition == unit_definition else "rewrite-unit-cached.ouro"
        elif definition[0] == "module_maps_for_cached_pure":
            entry = "maps-for-cached.ouro"
        units = [owner, entry]
        owned_definitions = tuple(row for row, source in zip(prefix_definitions, prefix_owners, strict=True)
                                  if source == owner) + (unit_scope_definitions if owner == unit_owner else ())
        digests = {key: frontend.FileDigest(key, "a" * 64, 1)
                   for key in ("seed", "frontend_regen", "module_cache", "packer", *units)}
        digests.update(guarded_inputs)
        arguments = dict(ouro1=tmp / "synthetic-seed", fuel="200000", work=work,
                         cache_enabled=True, tu_cache=tu_cache, tag="prefix", mod="_prefix",
                         root=entry, file_name=f"{definition[0]}.c", units=units, digests=digests)
        emitted = scope_source("_prefix", definitions=owned_definitions).encode()
        calls = []
        emit_state = {"bytes": emitted}

        def fake_prefix_emit(argv, selected=owner, selected_entry=entry, observed=calls, state=emit_state, **kwargs):
            assert argv[1:] == ["--module", "_prefix", selected_entry, "200000",
                                "--unit", selected, "--unit", selected_entry]
            observed.append(argv)
            kwargs["stdout"].write(state["bytes"])
            return subprocess.CompletedProcess(argv, 0)

        with patch.object(frontend.subprocess, "run", side_effect=fake_prefix_emit):
            assert frontend.emit_one(**arguments).cache == "miss"
            output = work / arguments["file_name"]
            accepted = output.read_bytes()
            accepted_text = output.read_text(encoding="utf-8")
            assert accepted_text == packer.hook_module_pure_scopes(
                emitted.decode(), units, "_prefix")
            assert frontend.emit_one(**arguments).cache == "hit" and len(calls) == 1
            key = frontend.tu_key("prefix", "_prefix", entry, units, digests, "200000")
            cache_file = tu_cache / f"_prefix_{key}.c"
            cache_file.write_bytes(emitted)
            frontend.record_cached_output(cache_file, key)
            try:
                frontend.emit_one(**arguments)
            except RuntimeError:
                pass
            else:
                raise AssertionError("unhooked cached prefix route published")
            assert output.read_bytes() == accepted and len(calls) == 1
            if definition[0] == "module_rewrite_decl_pure":
                stale_decl = accepted_text
                bad_decl_inputs = (
                    stale_decl.replace('return "module_rewrite_decl_pure";', 'return "unrelated";', 1),
                    stale_decl.replace("ouro_wrap_module_rewrite_decls_scope(ouro_clos(ouro_f128_,env))",
                                       "ouro_wrap_module_pure_scope(ouro_clos(ouro_f128_,env),7)", 1),
                )
                for bad_decl in bad_decl_inputs:
                    assert bad_decl != stale_decl
                    assert bad_decl.encode() != accepted
                    cache_file.write_bytes(bad_decl.encode())
                    frontend.record_cached_output(cache_file, key)
                    try:
                        frontend.emit_one(**arguments)
                    except RuntimeError:
                        pass
                    else:
                        raise AssertionError("stale declaration prefix cache published")
                    assert output.read_bytes() == accepted and len(calls) == 1
            if definition[0] in ("module_scope_maps", "module_bare_ctors", "module_invalid_maps",
                                  "module_maps_for_cached_pure"):
                gid = 31 + owned_definitions.index(definition) * 97
                wrapper = prefix_wrappers[prefix_definitions.index(definition)]
                prototype = f"ouro_v *{wrapper}(ouro_v *raw);\n"
                stale_body2 = accepted_text
                bad_body2_inputs = (
                    stale_body2.replace(f'return "{definition[0]}";', 'return "unrelated";', 1),
                    stale_body2.replace(f"{wrapper}(ouro_clos(ouro_f{gid}_,env))",
                                        f"ouro_wrap_module_pure_scope(ouro_clos(ouro_f{gid}_,env),2)", 1),
                    stale_body2.replace(prototype, "", 1),
                    stale_body2.replace(prototype, prototype * 2, 1),
                ) + (
                    (stale_body2.replace(f"{wrapper}(ouro_clos(ouro_f{gid}_,env))",
                                         f"ouro_wrap_module_pure_scope(ouro_clos(ouro_f{gid}_,env),3)", 1),
                     *(stale_body2.replace(f"return ouro_clos(ouro_f{'0_' * (step + 1)}{gid}_,env);",
                                          "return arg;", 1)
                       for step in range(definition[1] - 1)))
                    if definition[0] in ("module_invalid_maps", "module_maps_for_cached_pure") else ()
                )
                for bad_body2 in bad_body2_inputs:
                    assert bad_body2 != stale_body2
                    assert bad_body2.encode() != accepted
                    cache_file.write_bytes(bad_body2.encode())
                    frontend.record_cached_output(cache_file, key)
                    try:
                        frontend.emit_one(**arguments)
                    except RuntimeError:
                        pass
                    else:
                        raise AssertionError("stale body2 prefix cache published")
                    assert output.read_bytes() == accepted and len(calls) == 1
            if definition in unit_scope_definitions:
                unit_name, unit_arity, _constructor = definition
                unit_index = owned_definitions.index(definition)
                gid = 31 + unit_index * 97
                stale_unit = accepted_text
                assignment = f"ouro_c{gid}=ouro_wrap_module_pure_scope(ouro_clos(ouro_f{gid}_,env),7);"
                cached_headers = tuple(
                    f"static ouro_v *ouro_f{'0_' * step}{gid}_(ouro_env *env0,ouro_v *arg){{"
                    for step in range(unit_arity)
                )
                bad_unit_inputs = (
                    stale_unit.replace(f'return "{unit_name}";', 'return "unrelated";', 1),
                    stale_unit.replace(f'case {unit_index}: return "{unit_name}";',
                                       f'case {unit_index}: return "{unit_name}";' * 2, 1),
                    stale_unit.replace(f"case {unit_index}: return ouro_g{gid}();", "", 1),
                    stale_unit.replace(declaration, "", 1),
                    stale_unit.replace(declaration, declaration * 2, 1),
                ) + tuple(
                    stale_unit.replace(assignment, assignment.replace(",7);", f",{arity});"), 1)
                    for arity in (0, 1, 2, 3, 6, 8)
                ) + tuple(
                    stale_unit.replace(header, header.replace("ouro_v *arg", "void"), 1)
                    for header in cached_headers
                ) + tuple(stale_unit.replace(header, header * 2, 1) for header in cached_headers) + tuple(
                    stale_unit.replace(f"return ouro_clos(ouro_f{'0_' * (step + 1)}{gid}_,env);",
                                       "return arg;", 1)
                    for step in range(unit_arity - 1)
                )
                for bad_unit in bad_unit_inputs:
                    assert bad_unit != stale_unit
                    assert bad_unit.encode() != accepted
                    cache_file.write_bytes(bad_unit.encode())
                    frontend.record_cached_output(cache_file, key)
                    try:
                        frontend.emit_one(**arguments)
                    except RuntimeError:
                        pass
                    else:
                        raise AssertionError("stale module rewrite unit cache published")
                    assert output.read_bytes() == accepted and len(calls) == 1
            emit_state["bytes"] = scope_source(
                "_prefix", definitions=tuple((row[0], 6 if row in unit_scope_definitions else 7, "ouro_clos")
                                             if row == definition else row
                                             for row in owned_definitions)).encode()
            changed = dict(digests, packer=frontend.FileDigest("packer", "b" * 64, 1))
            try:
                frontend.emit_one(**dict(arguments, digests=changed))
            except RuntimeError:
                pass
            else:
                raise AssertionError("raw6 accepted as unit raw7" if definition in unit_scope_definitions
                                     else "raw7 accepted as prefix raw9/raw10")
            assert output.read_bytes() == accepted and len(calls) == 2


def test_native_emit_phases(tmp: Path) -> None:
    """Phase completion follows acceptance; failed stages cannot publish a backend."""
    from contextlib import redirect_stderr, redirect_stdout
    from io import StringIO

    import native_tool_build as native

    units = ["dependency.ouro", "entry.ouro"]
    # Publication phases use a fake compiler and separate alias-policy controls.
    sources = {
        units[0]: "def dependency : Nat := Z;\n",
        units[1]: 'import "dependency.ouro";\ndef main : Nat := dependency;\n',
    }
    prior = b"previous backend\n"
    emitted = b"int fixture_main(void){return 0;}\n"
    packed = emitted + b"/* uniquified */\n"
    hooked = packed + b"/* hooked */\n"
    complete = [(name, state) for name in ("compiler", "uniquify", "hooks", "publish")
                for state in ("start", "done")]
    for mode, event_count in (("success", 8), ("quiet", 0), ("compiler", 1),
                              ("uniquify", 3), ("aliases", 5), ("hooks", 5)):
        work = tmp / ("native-emit-phases-" + mode)
        work.mkdir()
        source_root = work / "sources"
        source_root.mkdir()
        for unit, text in sources.items():
            newline = "\r" if unit == units[0] else "\r\n"
            (source_root / unit).write_bytes(text.replace("\n", newline).encode("utf-8"))
        parse_bytes = native.cached_import_parser() if mode == "success" else None
        if parse_bytes is not None:
            stale_entry = sources[units[-1]].replace(units[0], "stale-dependency.ouro")
            assert parse_bytes(stale_entry.encode("utf-8"), units[-1]) == ["stale-dependency.ouro"]
            parse_bytes((source_root / units[0]).read_bytes(), units[0])
        generated = work / "backend.c"
        generated.write_bytes(prior)
        events = []
        source_reads = []
        temporary_opens = []
        compiler_argv = ["fixture-compiler", units[-1], "321", "--unit", units[0], "--unit", units[1]]

        def open_path(path, mode="r", *args, _open=Path.open, _source_root=source_root,
                      _source_reads=source_reads, _work=work, _temporary_opens=temporary_opens, **kwargs):
            if path.parent == _source_root and path.name in sources:
                _source_reads.append(path.name)
            if path.parent == _work and path.name.startswith("emit.") and path.suffix == ".c":
                _temporary_opens.append(mode)
            return _open(path, mode, *args, **kwargs)

        def phase(name, elapsed, *, _events=events, _generated=generated):
            assert elapsed is None or (isinstance(elapsed, float) and elapsed >= 0), (name, elapsed)
            _events.append((name, "start" if elapsed is None else "done"))
            expected = hooked if name == "publish" and elapsed is not None else prior
            assert _generated.read_bytes() == expected, "phase callback preceded acceptance/publication"

        def process(argv, *, _mode=mode, _work=work, _compiler_argv=compiler_argv, **options):
            assert options["cwd"] == native.ROOT
            if "stdout" in options:
                assert argv == _compiler_argv and options["check"] is False
                assert options["env"]["OURO_EMIT_IO_SHIMS"] == "1"
                options["stdout"].write(emitted)
                if _mode == "compiler":
                    options["stderr"].write(b"fixture compiler failure\n")
                return subprocess.CompletedProcess(argv, 1 if _mode == "compiler" else 0)
            assert argv[:3] == [sys.executable, str(native.ROOT / "scripts/pack_frontend.py"),
                                "--uniquify-only"] and options["check"] is True
            temporary = Path(argv[3])
            assert temporary.parent == _work and temporary.read_bytes() == emitted
            temporary.write_bytes(packed)
            if _mode == "uniquify":
                raise subprocess.CalledProcessError(2, argv)
            return subprocess.CompletedProcess(argv, 0)

        def hook(temporary, observed_units, *, source_text, _generated=generated, _mode=mode):
            assert observed_units == units and source_text == packed.decode()
            assert _generated.read_bytes() == prior
            temporary.write_bytes(hooked)
            if _mode == "hooks":
                raise RuntimeError("fixture hook failure")

        def alias(text, observed_units, canonical_units, entry, observed_sources, *, export_index,
                  _mode=mode, _generated=generated):
            assert text == packed.decode() and observed_units == canonical_units == units
            assert entry == units[-1] and observed_sources == sources
            assert isinstance(export_index, native.ScopedExportIndex)
            assert _generated.read_bytes() == prior
            if _mode == "aliases":
                raise RuntimeError("fixture alias failure")
            return text

        stdout, stderr = StringIO(), StringIO()
        with patch.object(native, "ROOT", source_root), \
             patch.object(native.frontend, "ROOT", source_root), patch.object(Path, "open", open_path), \
             patch.object(native, "current_native_scoped_aliases", side_effect=alias) as aliases, \
             patch.object(native.frontend, "ouro1_cmd", return_value=["fixture-compiler"]), \
             patch.object(native.subprocess, "run", side_effect=process) as commands, \
             patch.object(native, "hook_compile_checked_units", side_effect=hook) as hooks, \
             patch.object(native.os, "replace", wraps=native.os.replace) as publish, \
             redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                if mode == "quiet":
                    native.emit(work / "compiler", units, 321, generated)
                else:
                    native.emit(work / "compiler", units, 321, generated, phase_callback=phase, parse_bytes=parse_bytes)
            except (RuntimeError, subprocess.CalledProcessError) as error:
                if mode == "compiler":
                    assert isinstance(error, RuntimeError) and "emit failed rc=1" in str(error)
                    assert "fixture compiler failure" in str(error)
                elif mode == "uniquify":
                    assert isinstance(error, subprocess.CalledProcessError) and error.returncode == 2
                elif mode == "aliases":
                    assert isinstance(error, RuntimeError) and str(error) == "fixture alias failure"
                else:
                    assert mode == "hooks" and str(error) == "fixture hook failure"
            else:
                assert mode in ("success", "quiet"), "failed emission stage was accepted"
            assert commands.call_count == (1 if mode == "compiler" else 2)
            if mode in ("compiler", "uniquify"):
                assert source_reads == [], source_reads
                aliases.assert_not_called()
            else:
                assert source_reads == list(reversed(units)), source_reads
                aliases.assert_called_once()
            assert hooks.call_count == (0 if mode in ("compiler", "uniquify", "aliases") else 1)
            assert publish.call_count == (1 if mode in ("success", "quiet") else 0)
        assert events == complete[:event_count]
        assert stdout.getvalue() == stderr.getvalue() == "", "native emit lost its default-quiet contract"
        assert generated.read_bytes() == (hooked if mode in ("success", "quiet") else prior)
        assert not list(work.glob("emit.*.c")), "failed or published emission retained a temporary backend"
        expected_opens = ["wb", "rb", "wb", "r", "wb"]
        assert temporary_opens == expected_opens[:{"compiler": 1, "uniquify": 3, "aliases": 4}.get(mode, 5)]


def test_windows_quality_manifest_protocol(tmp: Path) -> None:
    """Resource failure/cleanup protocol only; native suites test Unicode argv."""
    import ctypes
    from unittest.mock import Mock, call

    import native_tool_build as native

    manifest = native.WINDOWS_UTF8_MANIFEST
    data = ctypes.create_string_buffer(manifest.encode("utf-8"))
    api = Mock()
    api.LoadLibraryExW.return_value = 10
    api.FindResourceW.return_value = 0
    api.FreeLibrary.return_value = True
    api.BeginUpdateResourceW.return_value = 20
    api.UpdateResourceW.return_value = True
    api.EndUpdateResourceW.return_value = True
    binary = tmp / "candidate.exe"
    with patch.object(ctypes, "WinDLL", return_value=api, create=True), \
         patch.object(ctypes, "get_last_error", return_value=1813, create=True) as last_error, \
         patch.object(ctypes, "WinError", side_effect=lambda code: OSError(code, "resource failure"), create=True):
        native.embed_windows_manifest(binary, manifest)
        api.LoadLibraryExW.assert_called_once_with(str(binary.resolve()), None, 0x60)
        api.FreeLibrary.assert_called_once_with(10)
        api.BeginUpdateResourceW.assert_called_once_with(str(binary.resolve()), False)
        assert api.UpdateResourceW.call_args.args[1].value == 24
        assert api.UpdateResourceW.call_args.args[2].value == 1
        assert api.UpdateResourceW.call_args.args[3] == 0
        assert api.UpdateResourceW.call_args.args[5] == len(manifest.encode("utf-8"))
        api.EndUpdateResourceW.assert_called_once_with(20, False)

        def refused(expected):
            try:
                native.embed_windows_manifest(binary, manifest)
            except (OSError, RuntimeError) as error:
                assert expected in str(error), str(error)
            else:
                raise AssertionError("invalid resource transition accepted")

        api.reset_mock()
        api.FindResourceW.return_value = 30
        api.SizeofResource.return_value = len(manifest.encode("utf-8"))
        api.LoadResource.return_value = 40
        api.LockResource.return_value = ctypes.addressof(data)
        native.embed_windows_manifest(binary, manifest)
        api.BeginUpdateResourceW.assert_not_called()
        api.FreeLibrary.assert_called_once_with(10)
        api.SizeofResource.return_value = 1
        refused("conflicting executable manifest")
        api.BeginUpdateResourceW.assert_not_called()

        api.reset_mock()
        api.FindResourceW.return_value = 0
        last_error.return_value = 5
        refused("resource failure")
        api.BeginUpdateResourceW.assert_not_called()
        api.FreeLibrary.assert_called_once_with(10)
        last_error.return_value = 1813
        api.BeginUpdateResourceW.return_value = 0
        refused("resource failure")
        api.UpdateResourceW.assert_not_called()
        api.BeginUpdateResourceW.return_value = 20
        api.UpdateResourceW.return_value = False
        refused("resource failure")
        api.EndUpdateResourceW.assert_called_once_with(20, True)
        api.EndUpdateResourceW.return_value = False
        refused("discard also failed")
        api.UpdateResourceW.return_value = True
        refused("resource failure")
        assert api.EndUpdateResourceW.call_args_list[-1] == call(20, False)


def test_frontend_native_async_protocol(tmp: Path) -> None:
    """Synthetic receipts test rejection; they do not establish native execution."""
    import copy
    import hashlib

    import frontend_native_async as native
    import frontend_regen

    # The synthetic protocol fixture must track the live runtime mutation sites.
    live = native.source_snapshot()
    for variant in native.FAULTS:
        mutated = native.variant_bytes(live, variant)
        changed = [unit for unit, body in mutated.items()
                   if hashlib.sha256(body).hexdigest() != live["sources"][unit]]
        assert changed == [native.SLEEP], variant

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
    sleep.write_text("u32_from_nat windows_sleep_milliseconds_per_second\nu8_from_nat 1\n", encoding="utf-8")
    entry.write_text('import "../runtime/platform/windows_sleep.ouro";\n', encoding="utf-8")
    units = [native.SLEEP, native.ENTRY]
    with patch.object(native, "ROOT", root), patch.object(frontend_regen, "ROOT", root):
        parse_bytes = native.modules.cached_import_parser()
        before = native.source_snapshot(parse_bytes=parse_bytes)
        assert before["units"] == units
        builds = root / "builds"
        native.freeze_sources(builds, before, parse_bytes=parse_bytes)
        changed_inputs = native.read_json(builds / "milliseconds" / "inputs.json")
        copied_entry = Path(changed_inputs["source_root"]) / native.ENTRY
        copied_bytes = copied_entry.read_bytes()
        copied_stat = copied_entry.stat()
        changed_bytes = b"--" + copied_bytes[2:]
        changed_inputs["sources"][native.ENTRY] = hashlib.sha256(changed_bytes).hexdigest()
        try:
            copied_entry.write_bytes(changed_bytes)
            os.utime(copied_entry, ns=(copied_stat.st_atime_ns, copied_stat.st_mtime_ns))
            try:
                native.verify_source_root(changed_inputs, parse_bytes=parse_bytes)
            except ValueError as error:
                assert str(error) == "native async copied import order differs"
            else:
                raise AssertionError("changed copied imports accepted with a cached parser")
        finally:
            copied_entry.write_bytes(copied_bytes)
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
            images = native.verify_builds(builds, before, producer, producer_hash, receipts, parse_bytes=parse_bytes)
            assert set(images) == set(native.VARIANTS)
            rejected(lambda: native.verify_builds(builds, before, producer, producer_hash, {}))
            path = builds / "original/receipt.json"
            receipt_bytes = path.read_bytes()
            replacement = path.with_name("replacement.json")
            replacement.write_bytes(b"\xff")
            read_bytes = Path.read_bytes

            def replace_after_read(file):
                data = read_bytes(file)
                if file == path:
                    replacement.replace(path)
                return data

            try:
                with patch.object(Path, "read_bytes", autospec=True, side_effect=replace_after_read):
                    assert native.verify_builds(builds, before, producer, producer_hash, receipts) == images
                assert path.read_bytes() == b"\xff"
                try:
                    native.verify_builds(builds, before, producer, producer_hash, receipts)
                except ValueError as error:
                    assert str(error) == "native async build receipt changed"
                else:
                    raise AssertionError("changed async receipt accepted")
            finally:
                path.write_bytes(receipt_bytes)
            original = native.read_json(path)
            for key, value in (("status", "failed"), ("variant", "flag"), ("producer_sha256", "stale"),
                ("cwd", str(root)), ("argv", []), ("inputs_sha256", "stale"), ("image", {}),
                ("result_status", "timeout"), ("returncode", 1), ("returncode", False),
                ("stdout", ""), ("inputs_unchanged", False), ("producer_unchanged", 1)):
                native.write_json_atomic(path, {**original, key: value})
                changed = {**receipts, "original": native.sha256_file(path)}
                rejected(lambda candidate=changed: native.verify_builds(builds, before, producer, producer_hash, candidate))
            for invalid_receipt in (b"[]\n", b"null\n"):
                path.write_bytes(invalid_receipt)
                changed = {**receipts, "original": hashlib.sha256(invalid_receipt).hexdigest()}
                try:
                    native.verify_builds(builds, before, producer, producer_hash, changed)
                except ValueError as error:
                    assert str(error) == "native async build receipt for original must be a JSON object"
                else:
                    raise AssertionError("non-object async build receipt accepted")
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
        incomplete = "native async source closure is incomplete"
        for invalid, diagnostic in (([], incomplete), ([*units, native.ENTRY], incomplete),
                                    (["../outside.ouro", *units], "native async source escapes repository")):
            with patch.object(native, "capture_unit_inputs", return_value=({native.ENTRY: invalid}, {})):
                try:
                    native.source_snapshot()
                except ValueError as error:
                    assert str(error) == diagnostic
                else:
                    raise AssertionError("invalid native async source closure accepted")


def test_collect_build_protocol(tmp: Path) -> None:
    """Cold collector setup must preserve check output and expose build failures."""
    repo = tmp / "collect-protocol"
    (repo / "scripts").mkdir(parents=True)
    (repo / "tools").mkdir()
    shutil.copyfile(ROOT / "scripts/ouro1.sh", repo / "scripts/ouro1.sh")
    (repo / "tools/collect.ouro").write_text("-- collector input\n", encoding="utf-8")
    shared = repo / "tools/collect_core.ouro"
    shared.write_text("-- shared traversal\n", encoding="utf-8")
    (repo / "input.ouro").write_text("def value : Nat := 0;\n", encoding="utf-8")
    compiler = repo / "compiler"
    compiler.write_text("#!/bin/sh\nprintf 'CHECK_OK\\n'\n", encoding="utf-8")
    compiler.chmod(0o755)
    (repo / "scripts/build_tool.sh").write_text(
        "#!/bin/sh\nset -eu\nprintf 'build stdout\\n'\nprintf 'build stderr\\n' >&2\n"
        "[ \"${COLLECT_BUILD_FAIL:-0}\" = 0 ] || exit 23\n"
        "printf '%s\\n' '#!/bin/sh' \"printf '%s\\\\n' 'input.ouro'\" >\"$2\"\n"
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
    changed_time = (repo / "out/ouro-collect").stat().st_mtime_ns + 2_000_000_000
    os.utime(shared, ns=(changed_time, changed_time))
    stale = invoke()
    assert stale.returncode != 0 and stale.stdout == "", "shared collector change reused stale binary"
    assert stale.stderr == "build stdout\nbuild stderr\n", stale
    (repo / "out/ouro-collect").unlink()
    failure = invoke()
    assert failure.returncode != 0 and failure.stdout == "", failure
    assert failure.stderr == "build stdout\nbuild stderr\n", failure
    assert log.read_text(encoding="utf-8") == failure.stderr


def test_collected_unit_arguments(tmp: Path) -> None:
    """The public wrapper preserves each collector line as one literal argv."""
    repo = tmp / "collect-arguments"
    (repo / "scripts").mkdir(parents=True)
    (repo / "tools").mkdir()
    (repo / "out").mkdir()
    shutil.copyfile(ROOT / "scripts/ouro1.sh", repo / "scripts/ouro1.sh")
    for name in ("collect.ouro", "collect_core.ouro"):
        (repo / "tools" / name).write_text("-- fixture\n", encoding="utf-8")
    entry = "корень 漢字.ouro"
    (repo / entry).write_text("def value : Nat := 0;\n", encoding="utf-8")
    (repo / "literala.ouro").touch()
    collector = repo / "out/ouro-collect"
    collector.write_text('#!/bin/sh\nprintf "%s\\n" "$COLLECT_UNITS"\n#' + "x" * 4100 + "\n",
                         encoding="utf-8")
    collector.chmod(0o755)
    compiler = repo / "compiler"
    compiler.write_text(
        '#!/bin/sh\nprintf "%s\\0" "$@" >"$COLLECT_ARGV_LOG"\n'
        'if [ "$1" = check ]; then printf "CHECK_OK\\n"; exit 0; fi\n'
        'echo "argv observer stopped before emission" >&2\nexit 23\n', encoding="utf-8")
    compiler.chmod(0o755)
    log = repo / "compiler-argv"
    env = isolated_env()
    env.update(OURO_ROOT=repo.as_posix(), OURO1_COMPILER=compiler.as_posix(),
               OURO_C_BUILD_DIR=(repo / "out").as_posix(), COLLECT_ARGV_LOG=log.as_posix())
    shell = shutil.which("sh")
    assert shell, "collector argv tests require the supported POSIX shell"
    units = ["with space.ouro", "путь 漢字.ouro", "tab\tname.ouro", "literal[ab].ouro",
             "literal?.ouro", "literal*.ouro", "back\\slash.ouro", "  padded.ouro  ", entry]

    def invoke(command, selected):
        log.unlink(missing_ok=True)
        env["COLLECT_UNITS"] = "\n".join(selected)
        arguments = [shell, "scripts/ouro1.sh", command, entry]
        if command == "eval":
            arguments += ["--eval", "value"]
        result = subprocess.run(arguments, cwd=repo, env=env, capture_output=True,
                                text=True, encoding="utf-8", timeout=30, check=False)
        forwarded = log.read_bytes().decode("utf-8").split("\0")[:-1] if log.exists() else None
        return result, forwarded

    expected = [argument for unit in units for argument in ("--unit", unit)]
    result, forwarded = invoke("check", units)
    assert (result.returncode, result.stdout, result.stderr) == (0, "CHECK_OK\n", ""), result
    assert forwarded == ["check", entry, "16000", *expected], forwarded
    result, forwarded = invoke("eval", units)
    assert result.returncode == 1 and "argv observer stopped before emission" in result.stderr, result
    assert forwarded[0].endswith(".ouro") and ".ouro_eval_wrap_" in forwarded[0], forwarded
    assert forwarded[1:] == ["2000", *expected], forwarded
    result, forwarded = invoke("check", [entry])
    assert result.returncode == 0 and forwarded == ["check", entry, "16000"], (result, forwarded)
    result, forwarded = invoke("check", [])
    assert result.returncode == 1 and "empty source closure" in result.stderr and forwarded is None, result


def test_build_tool_caller_paths(tmp: Path) -> None:
    repo = tmp / "build-tool-cwd"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    for name in ("build_tool.sh", "python.sh"):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    compiler = repo / "_build/c/ouro1"
    compiler.parent.mkdir(parents=True)
    compiler.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    compiler.chmod(0o755)
    (scripts / "native_tool_build.py").write_text(
        "import json, os, sys\nfrom pathlib import Path\n"
        "Path(os.environ['BUILD_ARGV_LOG']).write_text(json.dumps(sys.argv[1:]))\n"
        "raise SystemExit(int(os.environ['BUILD_STATUS']))\n", encoding="utf-8")
    caller = repo / "caller space"
    caller.mkdir()
    log = tmp / "build-argv.json"
    env = isolated_env()
    env.update(PYTHON=sys.executable, BUILD_ARGV_LOG=str(log), OURO_BUILD_TOOL_MODE="native")
    for code in (0, 23):
        env["BUILD_STATUS"] = str(code)
        result = subprocess.run(["sh", str(scripts / "build_tool.sh"), "./source.ouro", "out dir/tool"],
                                cwd=caller, env=env, capture_output=True, text=True, check=False)
        assert result.returncode == code, result
        # MSYS converts shell paths before invoking the native Python receiver.
        # Both inputs must still bind to the caller, including the spaced output.
        forwarded = json.loads(log.read_text())[:2]
        assert all(Path(arg).is_absolute() for arg in forwarded), forwarded
        assert [Path(arg).resolve() for arg in forwarded] == [
            (caller / "source.ouro").resolve(), (caller / "out dir/tool").resolve()]


def test_tool_suite_keeps_installed_images_for_native_verification(tmp: Path, tool: str, entry: str) -> None:
    suite = f"{tool.upper()}_SUITE"
    launcher = f"{tool}_suite.sh"
    repo = tmp / f"{tool}-installed-images"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    for name in (launcher, "python.sh"):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    (scripts / "ouro_smith.py").write_text("print('.')\n", encoding="utf-8")
    (scripts / "build_tool.sh").write_text(
        '#!/bin/sh\nset -eu\n'
        'test "$OURO_BUILD_TOOL_MODE" = native\n'
        f'test "$1" = "{entry}"\n'
        'test -f "$2" && test -f "$2.exe" || exit 2\n'
        'echo "installed images reached the native builder"\nexit 23\n', encoding="utf-8")
    out = repo / f"{tool}-out"
    out.mkdir()
    images = (out / f"ouro-{tool}", out / f"ouro-{tool}.exe")
    for image in images:
        image.write_bytes(b"installed image")
    env = isolated_env()
    env.update(PYTHON=sys.executable, CC="sh")
    env[f"{suite}_OUT"] = str(out)
    result = subprocess.run(["sh", f"scripts/{launcher}"], cwd=repo, env=env,
                            text=True, capture_output=True, timeout=15, check=False)
    assert result.returncode == 1 and f"{suite}: FAIL build" in result.stderr, result
    assert (out / "build.log").read_text(encoding="utf-8") == "installed images reached the native builder\n"
    assert all(image.read_bytes() == b"installed image" for image in images)


def test_runtime_io_host_selection(tmp: Path) -> None:
    """The C launcher must select its existing wrappers before building tools."""
    repo = tmp / "runtime-host-selection"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    for name in ("runtime_io_suite.sh", "python.sh"):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    runtime = repo / "runtime"
    runtime.mkdir()
    for name in ("ouro_rt.c", "ouro_io.c"):
        (runtime / name).write_bytes(b"")
    (runtime / "ouro_io_selftest.c").write_text(
        '#include <stdio.h>\n#include <string.h>\n'
        'int main(int argc, char **argv) {\n'
        '    if (argc == 2 && strcmp(argv[1], "--text-stream-child") == 0) {\n'
        '        fputs("capture-out", stdout);\n'
        '        fputs("capture-err", stderr);\n'
        '        return 0;\n'
        '    }\n'
        '    if (argc != 1) return 1;\n'
        '    puts("OURO_IO_SELFTEST: PASS");\n'
        '    return 0;\n'
        '}\n', encoding="utf-8")
    log = repo / "wrapper-env.json"
    (scripts / "capture.py").write_text(
        'import json, os\nfrom pathlib import Path\n'
        'keys = ("OURO_TEST_CHECK", "OURO_TEST_BUILD", "OURO_HOSTED_COMPILER_WRAPPER")\n'
        'Path(os.environ["WRAPPER_ENV_LOG"]).write_text(json.dumps({key: os.environ.get(key) for key in keys}))\n',
        encoding="utf-8")
    (scripts / "build_tool.sh").write_text(
        '#!/bin/sh\n"$PYTHON" scripts/capture.py\nexit 23\n', encoding="utf-8")
    # This test observes launcher environment only; filesystem behavior is
    # exercised with real binaries by runtime_io_suite and frontend_host_suite.
    for name in ("fs_replace_suite.py", "fs_read_suite_test.py", "fs_write_suite.py", "fs_write_suite_test.py"):
        (scripts / name).write_text("pass\n", encoding="utf-8")
    (scripts / "fs_read_suite.py").write_text(
        'import sys\nfrom pathlib import Path\nif "--record-inputs" in sys.argv:\n'
        '    driver = Path(sys.argv[sys.argv.index("--driver") + 1])\n'
        '    out = Path(sys.argv[sys.argv.index("--out") + 1])\n'
        '    assert driver.parent.resolve() == out.resolve()\n'
        '    print(sys.argv[sys.argv.index("--producer") + 1])\n', encoding="utf-8")
    stale_driver = repo / "_build/runtime_io/ouro-io-selftest.exe"
    stale_driver.parent.mkdir(parents=True)
    stale_driver.write_bytes(b"stale driver")
    env = isolated_env()
    env.pop("RUNTIME_IO_OUT", None)
    env.update(PYTHON=sys.executable, WRAPPER_ENV_LOG=str(log), OURO_CI_PREPARED_TEST="0")
    result = subprocess.run(["sh", "scripts/runtime_io_suite.sh"], cwd=repo, env=env,
                            text=True, capture_output=True, timeout=15, check=False)
    assert result.returncode == 1 and "native suite build" in result.stderr, result
    assert stale_driver.read_bytes() == b"stale driver"
    forwarded = json.loads(log.read_text())
    assert all(Path(value).is_absolute() for value in forwarded.values()), forwarded
    assert {key: Path(value).resolve() for key, value in forwarded.items()} == {
        "OURO_TEST_CHECK": (repo / "scripts/ouro1.sh").resolve(),
        "OURO_TEST_BUILD": (repo / "scripts/build_tool.sh").resolve(),
        "OURO_HOSTED_COMPILER_WRAPPER": (repo / "scripts/ouro1.sh").resolve(),
    }
    log.unlink()
    verification = repo / "verification.json"
    execution = repo / "execution.json"
    (scripts / "compiler_shards.py").write_text(
        'import json, os, sys\nfrom pathlib import Path\n'
        'Path(os.environ["VERIFY_LOG"]).write_text(json.dumps(sys.argv[1:]))\n'
        'raise SystemExit(int(os.environ["VERIFY_STATUS"]))\n', encoding="utf-8")
    (scripts / "ouro_smith.py").write_text('print("mock-fixtures")\n', encoding="utf-8")
    (scripts / "execute_suite.py").write_text(
        'import json, os, sys\nfrom pathlib import Path\n'
        'Path(os.environ["EXECUTE_LOG"]).write_text(json.dumps(sys.argv[1:]))\n'
        'raise SystemExit(24)\n', encoding="utf-8")
    suite = repo / "_build/runtime_io/ouro-test-suite"
    suite.write_text('#!/bin/sh\n"$PYTHON" scripts/execute_suite.py "$@"\n', encoding="utf-8")
    suite.chmod(0o755)
    env.update(OURO_CI_PREPARED_TEST="1", VERIFY_LOG=str(verification), EXECUTE_LOG=str(execution))
    for verify_status, expected_exit in ((23, 23), (0, 24)):
        env["VERIFY_STATUS"] = str(verify_status)
        result = subprocess.run(["sh", "scripts/runtime_io_suite.sh", "--suite-probe-failure"], cwd=repo, env=env,
                                text=True, capture_output=True, timeout=15, check=False)
        assert result.returncode == expected_exit and not log.exists(), result
        options = json.loads(verification.read_text())
        assert options[::2] == ["--runner", "--verify-with"], options
        assert Path(options[1]).resolve() == suite, options
        assert (repo / options[3]).resolve() == repo / "_build/c/ouro1", options
        assert execution.exists() == (verify_status == 0), result
    arguments = json.loads(execution.read_text())
    assert arguments[0] == "--native-suite=runtime-io", arguments
    assert arguments[-2:] == ["--fixtures=mock-fixtures", "--suite-probe-failure"], arguments


def test_prepared_lint_host_selection(tmp: Path) -> None:
    repo = tmp / "prepared-lint-host-selection"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    for name in ("lint_suite.sh", "ouro1.sh", "python.sh"):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    (scripts / "build_tool.sh").write_text('#!/bin/sh\necho build-requested >&2\nexit 24\n', encoding="utf-8")
    (scripts / "native_tool_build.py").write_text(
        'import json, os, sys\nfrom pathlib import Path\n'
        'Path(os.environ["VERIFY_LOG"]).write_text(json.dumps(sys.argv[1:]))\n'
        'if os.environ["VERIFY_STATUS"] != "0":\n    print("stale prepared tool", file=sys.stderr)\n'
        'raise SystemExit(int(os.environ["VERIFY_STATUS"]))\n', encoding="utf-8")
    bin_dir = repo / "_build/c"
    bin_dir.mkdir(parents=True)
    for name in ("ouro1", "ouro-lint"):
        tool = bin_dir / name
        tool.write_text('#!/bin/sh\nexit 25\n', encoding="utf-8")
        tool.chmod(0o755)
    verification = repo / "verification.json"
    env = isolated_env()
    env.pop("LINT_SUITE_OUT", None)
    env.pop("OURO1_COMPILER", None)
    env.update(PYTHON=sys.executable, VERIFY_LOG=str(verification), VERIFY_STATUS="23", OURO_CI_PREPARED_LINT="0")
    suite = ["sh", "scripts/lint_suite.sh", "--phase=production", "--shard=1/4"]
    result = subprocess.run(suite, cwd=repo, env=env, text=True, capture_output=True, timeout=15, check=False)
    assert result.returncode == 24 and not verification.exists(), result
    env["OURO_CI_PREPARED_LINT"] = "1"
    result = subprocess.run(suite, cwd=repo, env=env, text=True, capture_output=True, timeout=15, check=False)
    assert result.returncode == 23 and "stale prepared tool" in result.stderr and "build-requested" not in result.stderr, result
    options = json.loads(verification.read_text())
    assert options[0] == "--compiler" and options[2] == "--batch-report", options
    out = repo / "_build/tmp/lint_suite"
    assert Path(options[3]).resolve() == out / "tool-preparation.json", options
    assert options[4:6] == ["--tool", "tools/pkg/main.ouro"], options
    assert Path(options[6]).resolve() == out / "ouro-pkg" and options[7:] == ["--verify-published"], options
    wrapper = ["sh", "scripts/ouro1.sh", "lint", "--deny", "src.ouro"]
    for verify_status, expected_exit in ((23, 23), (0, 25)):
        env["VERIFY_STATUS"] = str(verify_status)
        result = subprocess.run(wrapper, cwd=repo, env=env, text=True, capture_output=True, timeout=15, check=False)
        assert result.returncode == expected_exit and "build-requested" not in result.stderr, result
        options = json.loads(verification.read_text())
        assert options[0] == "tools/lint.ouro" and Path(options[1]).resolve() == bin_dir / "ouro-lint", options
        assert options[2] == "--compiler" and Path(options[3]).resolve() == bin_dir / "ouro1", options
        assert options[4:] == ["--verify-published"], options
    (scripts / "bootstrap.sh").write_text('#!/bin/sh\necho bootstrap-requested >&2\nexit 26\n', encoding="utf-8")
    (bin_dir / "ouro1").unlink()
    result = subprocess.run(wrapper, cwd=repo, env=env, text=True, capture_output=True, timeout=15, check=False)
    assert result.returncode == 1 and "prepared compiler unavailable" in result.stderr, result
    assert "bootstrap-requested" not in result.stderr, result


def test_memory_preparation_failure(tmp: Path) -> None:
    import memory_budget_suite as memory
    from ourosmith.limits import RunResult

    for status, code in (("ok", 1), ("timeout", None), ("oom", None)):
        out = tmp / ("memory-preparation-" + status)
        failure = RunResult(status, code, "", "build failed", 1, 1)
        with patch.object(memory, "run_limited", return_value=failure), \
             patch.object(memory, "run_case") as measure:
            try:
                memory.main(["--case", "native-check-fmt", "--out", str(out)])
            except SystemExit as error:
                assert "native tool preparation failed" in str(error)
            else:
                raise AssertionError("failed preparation reached memory measurements")
            measure.assert_not_called()
        preparation = json.loads((out / "preparation.json").read_text())
        assert preparation["pass"] is False
        assert preparation["tools"][0]["status"] == failure.classify()
        assert not (out / "memory-report.json").exists()


def test_memory_preparation_outputs(tmp: Path) -> None:
    import memory_budget_suite as memory
    from ourosmith.limits import RunResult

    selected = [case for case in memory.CASES if case.label in {
        "tool-emission-fmt", "tool-emission-analyze", "formatter-suite",
    }]
    configured = tmp / "configured-tools"
    report_out = tmp / "memory-preparation-reports"
    success = RunResult("ok", 0, "prepared", "", 1, 1)
    budget_mib = 2048
    with patch.object(memory, "ROOT", tmp), \
         patch.dict(os.environ, {"OURO_C_BUILD_DIR": str(configured),
                                 "OURO1_COMPILER": str(configured / "ouro1"),
                                 MEMORY_ENV: str(budget_mib)}), \
         patch.object(memory, "run_limited", return_value=success) as prepare:
        report_out.mkdir()
        reports = memory.prepare_tools(selected, report_out)
    commands = [call.args[0] for call in prepare.call_args_list]
    outputs = {(command[2], Path(command[3])) for command in commands}
    assert outputs == {
        ("tools/analyze/main.ouro", configured / "ouro-analyze"),
        ("tools/fmt.ouro", tmp / "_build/memory/bin/ouro-fmt"),
        ("tools/analyze/main.ouro", tmp / "_build/memory/bin/ouro-analyze"),
        ("tools/fmt.ouro", tmp / "_build/memory/fmt_suite/ouro-fmt"),
        ("tests/quality_source_write_driver.ouro", tmp / "_build/memory/fmt_suite/quality-source-write"),
    }
    assert all(command[4:] == ["--compiler", str(configured / "ouro1")] for command in commands)
    assert all(call.kwargs["timeout_s"] == 900 and call.kwargs["memory_mb"] == budget_mib
               and call.kwargs["env"][MEMORY_ENV] == str(budget_mib) for call in prepare.call_args_list)
    assert all(report["memory_mb"] == budget_mib for report in reports)
    assert len({report["log"] for report in reports}) == len(reports)
    for case in selected[:2]:
        with patch.object(memory, "ROOT", tmp), \
             patch.object(memory, "run_limited", return_value=success) as prepare:
            memory.prepare_tools([case], report_out)
        assert any(Path(call.args[0][3]) == tmp / case.cmd[3] for call in prepare.call_args_list)


def test_source_replace_report_protocol(tmp: Path) -> None:
    from types import SimpleNamespace

    import frontend_regen
    import fs_replace_suite as native
    from selfhost_module_cache import cached_import_parser

    image_hash = "a" * 64
    valid = dict(kind="ouro.fs-replace.v1", complete=True, driver_sha256=image_hash,
                 checks=[dict(name=name, status="pass") for name in native.NATIVE_CASES])
    native.verify_native_report(valid, image_hash)
    invalid = [dict(valid, complete=value) for value in (False, 1, "true", None)]
    invalid += [dict(valid, kind="other"), dict(valid, driver_sha256="b" * 64)]
    invalid += [dict(valid, checks=rows) for rows in ([], valid["checks"][:-1],
                list(reversed(valid["checks"])), valid["checks"] + valid["checks"][:1],
                [dict(row, status="skip") for row in valid["checks"]])]
    for report in invalid:
        try:
            native.verify_native_report(report, image_hash)
        except ValueError:
            pass
        else:
            raise AssertionError("accepted incomplete or damaged source replacement report")
    entry = tmp / "source-replace-probe.ouro"
    entry.write_text("-- closure protocol fixture\n", encoding="utf-8")
    with (patch.object(native, "ROOT", tmp), patch.object(native, "ENTRY", entry.name),
          patch.object(frontend_regen, "ROOT", tmp)):
        incomplete = "incomplete source replacement closure"
        for units, diagnostic in (([], incomplete), ([entry.name, entry.name], incomplete),
                                  (["../outside.ouro", entry.name], "source replacement closure escapes repository")):
            with patch.object(frontend_regen, "capture_unit_inputs", return_value=({entry.name: units}, {})):
                try:
                    native.source_snapshot()
                except ValueError as error:
                    assert str(error) == diagnostic
                else:
                    raise AssertionError("accepted incomplete or escaping source replacement closure")
        before = native.source_snapshot()
        assert before == {"units": [entry.name], "sources": {entry.name: native.file_hash(entry)}}
        entry.write_text("-- changed source\n", encoding="utf-8")
        assert native.source_snapshot() != before

        work = tmp / "source-replace-drift"
        work.mkdir()
        producer = work / "producer.exe"
        producer.write_bytes(b"unexecuted source replacement producer")
        current_source = entry.read_bytes()
        source_stat = entry.stat()
        updated_source = current_source.replace(b"changed", b"updated", 1)
        assert updated_source != current_source and len(updated_source) == source_stat.st_size
        parse_bytes = cached_import_parser()

        def replace_source():
            entry.write_bytes(updated_source)
            os.utime(entry, ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))
            assert entry.stat().st_mtime_ns == source_stat.st_mtime_ns

        def unexpected_run(_label, _command, _timeout):
            raise AssertionError("source replacement started after its source changed")

        with (patch.object(native, "os", SimpleNamespace(name="nt")),
              patch.object(native, "source_snapshot", wraps=native.source_snapshot) as snapshots):
            try:
                native.run_native_section(producer, work, unexpected_run, 900, replace_source, parse_bytes=parse_bytes)
            except ValueError as error:
                assert str(error) == "source replacement inputs changed"
            else:
                raise AssertionError("source replacement accepted changed source bytes")
        assert snapshots.call_count == 2
        assert all(call.kwargs["parse_bytes"] is parse_bytes for call in snapshots.call_args_list)


def test_frontend_heap_observer_protocol(tmp: Path) -> None:
    from dataclasses import asdict, replace
    from types import SimpleNamespace

    import frontend_host_suite as host
    from ourosmith.limits import RunBytesResult, RunResult

    root = tmp / "heap-observer-protocol"
    root.mkdir()
    closures = {entry: [host.HEAP_OBSERVER_RUNTIME, entry]
                for _case, entry, _code, _text in host.HEAP_OBSERVER_CASES}
    closures.update({host.heap_observer_rejection_entry(name): [host.heap_observer_rejection_entry(name)]
                     for name, _diagnostic, _fallback in host.HEAP_OBSERVER_REJECTIONS})
    for entry in {name for units in closures.values() for name in units}:
        source = root / entry
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(("source " + entry).encode())

    def prepare(name, before):
        work = root / name
        work.mkdir()
        (work / "n1-host.exe").write_bytes(b"synthetic checked producer")
        (work / "backend.gen.c").write_bytes(b"synthetic generated source")
        built = {"generated_sha256": host.sha256_file(work / "backend.gen.c"),
                 "binaries": {"n1-host": {"sha256": host.sha256_file(work / "n1-host.exe")}}}
        host.write_json_atomic(work / "inputs-before.json", before)
        host.write_json_atomic(work / "build.json", built)
        return work, built

    def image(path, _imports, _symbols):
        return {"sha256": host.sha256_file(path), "bytes": path.stat().st_size, "machine": "x86_64"}

    def run(label, command, _timeout, *, capture_bytes=False):
        if label.endswith("-emit"):
            assert capture_bytes is False
            (root / command[2]).write_bytes(b"synthetic PE")
            logical = command[2]
            phases = (f"n1-host: check units={len(command) - 3} live=1\n"
                      "n1-host: CHECK_OK live=1 total=2\nn1-host: recheck live=1\n"
                      "n1-host: RECHECK_OK live=1\nn1-host: TYPES_OK live=1\n"
                      "n1-host: BUILD_OK live=1\nn1-host: mir functions=1 live=1\n"
                      "n1-host: mir-check live=1\nn1-host: gc-infer live=1\nn1-host: annotate live=1\n"
                      "n1-host: codegen live=1\nn1-host: LOWER_OK live=1\n"
                      f"n1-host: WROTE {logical} live=1\n")
            return RunResult("ok", 0, logical + "\n", phases, 0, 0, command)
        if label.startswith("heap-observer-helper-"):
            name = label.removeprefix("heap-observer-helper-")
            diagnostic, fallback = next((diagnostic, fallback) for selected, diagnostic, fallback
                                         in host.HEAP_OBSERVER_REJECTIONS if selected == name)
            phases = (f"n1-host: check units={len(command) - 3} live=1\n"
                      "n1-host: CHECK_OK live=1 total=2\nn1-host: recheck live=1\n"
                      "n1-host: RECHECK_OK live=1\nn1-host: TYPES_OK live=1\nn1-host: lower live=1\n"
                      + ("n1-host: managed miss tag=7; scalar lower\n" if fallback else "")
                      + "n1-host: lower failed tag=0 n=1 live=1\nn1-host: lower:"
                      + diagnostic.split(":")[0] + ":77\n")
            return RunResult("ok", 1, "", phases, 0, 0, command)
        assert capture_bytes is True and label.endswith("-pe")
        case = label.removeprefix("heap-observer-").removesuffix("-pe")
        code, text = next((code, text) for selected, _entry, code, text in host.HEAP_OBSERVER_CASES if selected == case)
        stdout = text.encode()
        work = Path(command[0]).parent.parent
        (work / (label + ".out")).write_bytes(stdout)
        (work / (label + ".err")).write_bytes(b"")
        return RunBytesResult("ok", code, stdout, b"", 0, 0, command)

    def rejected(operation):
        try:
            operation()
        except ValueError:
            pass
        else:
            raise AssertionError("accepted damaged heap-observer evidence")

    original_resolve = Path.resolve

    def resolve_escaping(path, *args, **kwargs):
        if path == root / host.HEAP_OBSERVER_RUNTIME:
            return tmp
        return original_resolve(path, *args, **kwargs)

    with patch.object(host, "ROOT", root), patch.object(host, "os", SimpleNamespace(name="nt")), \
            patch.object(host, "capture_unit_inputs",
                         side_effect=lambda entries, **_kwargs: capture_fixture_units(root, closures, entries)), \
            patch.object(host.direct_process, "inspect_image", side_effect=image):
        with patch.object(Path, "resolve", autospec=True, side_effect=original_resolve) as resolves:
            snapshot = host.heap_observer_source_snapshot()
        assert resolves.call_count == len(snapshot["sources"])
        assert {call.args[0] for call in resolves.call_args_list} == {root / name for name in snapshot["sources"]}
        with patch.object(Path, "resolve", resolve_escaping):
            try:
                host.heap_observer_source_snapshot()
            except ValueError as error:
                assert str(error) == "heap observer source closure is incomplete or escapes: " + next(iter(closures))
            else:
                raise AssertionError("heap observer accepted a redirected source")
        names = (host.ENTRY, "runtime/n1_host_main.c", "scripts/frontend_host_suite.py", "scripts/ourosmith/limits.py")
        before = {"inputs": {"compiler_sha256": "a" * 64, "sources": {name: "b" * 64 for name in names}},
                  "native_raw_fn": {}, "native_heap_observer": snapshot}
        work, built = prepare("success", before)
        report = host.run_heap_observer(work, run, 90, 3, lambda: None, before, built)
        persisted = json.loads((work / "native-heap-observer/report.json").read_text())
        host.verify_heap_observer_artifacts(work, persisted)
        assert persisted == report and len(report["rows"]) == 8 and len(report["rejections"]) == 5
        for section in ("rows", "rejections"):
            missing = json.loads(json.dumps(report))
            missing[section].pop()
            rejected(lambda candidate=missing: host.verify_heap_observer_artifacts(work, candidate))
        reordered = json.loads(json.dumps(report))
        reordered["rows"][:2] = reversed(reordered["rows"][:2])
        rejected(lambda: host.verify_heap_observer_artifacts(work, reordered))
        wrong_metric = {**report, "metric": "C arena bytes"}
        rejected(lambda: host.verify_heap_observer_artifacts(work, wrong_metric))
        for row in report["rows"]:
            for status in ("timeout", "memory", "skipped"):
                rejected(lambda selected=row, state=status: host.verify_heap_observer_result(
                    {**selected["result"], "status": state}, selected["result"]["returncode"],
                    bytes.fromhex(selected["result"]["stdout_hex"]).decode()))
        pinned = root / host.HEAP_OBSERVER_RUNTIME
        original = pinned.read_bytes()
        try:
            pinned.write_bytes(original + b" changed")
            rejected(lambda: host.verify_heap_observer_artifacts(work, report))
        finally:
            pinned.write_bytes(original)
        for target in (work / "n1-host.exe", work / "backend.gen.c", work / "inputs-before.json",
                       work / "heap-observer-deferred-reused-pe.out",
                       work / "native-heap-observer/allocated-freed.exe"):
            original = target.read_bytes()
            try:
                target.write_bytes(original + (b" " if target.suffix == ".json" else b" changed"))
                rejected(lambda: host.verify_heap_observer_artifacts(work, report))
            finally:
                target.write_bytes(original)
        for index, state in enumerate(("timeout", "memory", "wrong-exit")):
            failed_work, failed_built = prepare("failed-" + str(index), before)

            def failing_run(label, command, timeout, selected=state, *, capture_bytes=False):
                observed = run(label, command, timeout, capture_bytes=capture_bytes)
                if not label.endswith("-pe"):
                    return observed
                return replace(observed, returncode=0) if selected == "wrong-exit" else replace(observed, status=selected)

            rejected(lambda destination=failed_work, metadata=failed_built: host.run_heap_observer(
                destination, failing_run, 90, 3, lambda: None, before, metadata))
            failed = json.loads((failed_work / "native-heap-observer/report.json").read_text())
            assert failed["status"] == "failed" and len(failed["rows"]) == 1
            assert failed["rows"][0]["result"] == host.bytes_run_record(
                failing_run("heap-observer-allocated-freed-pe", [str(failed_work / "native-heap-observer/allocated-freed.exe")],
                            3, capture_bytes=True))
        bad_stream = asdict(RunBytesResult("ok", 73, b"", b"not empty", 0, 0, []))
        bad_stream["stdout_hex"] = bad_stream.pop("stdout").hex()
        bad_stream["stderr_hex"] = bad_stream.pop("stderr").hex()
        bad_stream["capture"] = "bytes"
        rejected(lambda: host.verify_heap_observer_result(bad_stream, 73, ""))


def main() -> int:
    from io import StringIO
    import unittest

    import bootstrap_compiler_test
    import bootstrap_inputs_test
    import ci_historical_cache_test
    import frontend_arithmetic_test
    import frontend_lower_lookup_test
    import scoped_host_exports_test
    import test_selfhost_bootstrap_evidence

    contracts = unittest.TestSuite()
    for module in (frontend_arithmetic_test, frontend_lower_lookup_test, scoped_host_exports_test):
        contracts.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
    trace = StringIO()
    result = unittest.TextTestRunner(stream=trace).run(contracts)
    if not result.wasSuccessful() or result.skipped or result.testsRun == 0:
        raise AssertionError(trace.getvalue())
    bootstrap_inputs_test.run()
    bootstrap_compiler_test.run()
    ci_historical_cache_test.run()
    test_selfhost_bootstrap_evidence.run()
    test_seal_parse()
    test_host_stack_link_flags()
    test_c_ccache_disabled_skips_discovery()
    with tempfile.TemporaryDirectory(prefix="ouro-build-suite-") as d:
        tmp = Path(d).resolve()
        test_c_ccache_discovery_is_per_build(tmp)
        test_clang_bracket_depth(tmp)
        test_c_cache_hit_hashes(tmp)
        test_link_stamp_resolves_root_once(tmp)
        test_fe_link_reuses_exact_installed_bytes(tmp)
        test_c_source_flags(tmp)
        test_c_compile_priority_preserves_link_order(tmp)
        test_memory_preparation_failure(tmp)
        test_memory_preparation_outputs(tmp)
        test_collect_build_protocol(tmp)
        test_collected_unit_arguments(tmp)
        test_build_tool_caller_paths(tmp)
        test_tool_suite_keeps_installed_images_for_native_verification(tmp, "fmt", "tools/fmt.ouro")
        test_tool_suite_keeps_installed_images_for_native_verification(tmp, "fix", "tools/fix/main.ouro")
        test_runtime_io_host_selection(tmp)
        test_prepared_lint_host_selection(tmp)
        test_source_replace_report_protocol(tmp)
        test_frontend_native_async_protocol(tmp)
        test_retired_toolchain_contract(tmp)
        test_incremental_invalidation(tmp)
        test_config_precedence(tmp)
        test_frontend_native_fs_create_protocol(tmp)
        test_destructive_path_policy(tmp)
        test_native_tool_hooks(tmp)
        test_native_emit_phases(tmp)
        test_windows_quality_manifest_protocol(tmp)
        test_frontend_host_snapshot_reuses_imports(tmp)
        test_frontend_host_worker_jobs(tmp)
        test_frontend_host_protocol(tmp)
        test_frontend_native_live_protocol(tmp)
        test_frontend_raw_fn_protocol(tmp)
        test_frontend_heap_observer_protocol(tmp)
        test_frontend_file_status_fault_protocol(tmp)
        test_frontend_native_process_protocol(tmp)
        test_frontend_native_toolchain_protocol(tmp)
        test_frontend_native_release_protocol(tmp)
        test_frontend_native_release_stream_protocol(tmp)
        test_frontend_host_environment_overlay(tmp)
        test_frontend_public_cli_protocol(tmp)
        test_native_suite_tools_protocol(tmp)
        test_native_runtime_gc_imports()
        test_native_sleep_imports()
        test_native_tool_cache(tmp)
        test_native_tool_emission_resume(tmp)
        test_native_tool_shard_cache(tmp)
        test_native_tool_companion(tmp)
    print("BUILD_CACHE_CONFIG_SUITE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
