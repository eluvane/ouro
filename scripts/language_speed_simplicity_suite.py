#!/usr/bin/env python3
"""Regression checks for the hot Ouro edit/check path.

The suite intentionally avoids brittle wall-clock assertions.  Instead it locks
in the concrete speed win from the pass: once C bootstrap artifacts already
exist, `scripts/ouro1.sh check` and the small surface suites must not invoke
Python just to resolve project config.  Full config/build/cache behavior remains
tested by scripts/build_cache_config_suite.py.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from ourosmith.native_inputs import prepare
ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], *, env: dict[str, str] | None = None, stdout: int | None = subprocess.PIPE) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=stdout,
        stderr=subprocess.STDOUT,
        check=True,
    )


def fake_python(tmp: Path, log: Path) -> Path:
    fakebin = tmp / "fakebin"
    fakebin.mkdir()
    py = fakebin / "python3"
    log_rel = log.relative_to(ROOT).as_posix()
    py.write_text(
        f'#!/bin/sh\nprintf \'%s\\n\' "python3 $*" >>"{log_rel}"\nexit 86\n',
        encoding="utf-8",
    )
    py.chmod(py.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return fakebin


def assert_no_python(log: Path, label: str) -> None:
    if log.exists() and log.read_text(encoding="utf-8").strip():
        raise AssertionError(f"{label} unexpectedly invoked python3:\n{log.read_text(encoding='utf-8')}")


def assert_no_path_warning(output: str, label: str) -> None:
    if "tr: warning:" in output:
        raise AssertionError(f"{label} emitted a path-normalization warning:\n{output}")


def check_native_gate_launchers(tmp: Path, *, source_root: Path = ROOT) -> None:
    """The two public commands share startup policy, not gate semantics."""
    cases = [
        ("fresh", "src.ouro\n", "", "fail", False),
        ("exe-sidecar", "src.ouro\n", ".exe", "fail", False),
        ("exe-logical-sidecar", "src.ouro\n", ".exe", "fail", False),
        ("both-binaries", "src.ouro\n", "", "fail", False),
        ("stale-primary-with-fresh-exe", None, "", "fail", True),
        ("exe-missing-manifest", None, ".exe", "fail", True),
        ("exe-newer-source", "src.ouro\n", ".exe", "fail", True),
        ("exe-invalid-rebuild", None, ".exe", "noop", True),
        ("unterminated", "src.ouro", "", "fail", False),
        ("missing-manifest", None, "", "fail", True),
        ("empty-manifest", "", "", "fail", True),
        ("empty-line", "\n", "", "fail", True),
        ("absolute", "/src.ouro\n", "", "fail", True),
        ("drive", "C:/src.ouro\n", "", "fail", True),
        ("parent", "../src.ouro\n", "", "fail", True),
        ("nested-parent", "dir/../src.ouro\n", "", "fail", True),
        ("backslash", "dir\\src.ouro\n", "", "fail", True),
        ("missing-source", "missing.ouro\n", "", "fail", True),
        ("newer-source", "src.ouro\n", "", "fail", True),
        ("missing-binary", "src.ouro\n", "", "repair", True),
        ("repair", None, "", "repair", True),
        ("invalid-rebuild", None, "", "noop", True),
    ]
    for area in ("repo", "ci"):
        for name, manifest, suffix, rebuild, needs_build in cases:
            root = tmp / f"{area} {name}"
            scripts = root / "scripts"
            scripts.mkdir(parents=True)
            for filename in (f"ouro_{area}_gate.sh", "native_gate_launcher.sh"):
                if (source_root / "scripts" / filename).is_file():
                    shutil.copyfile(source_root / "scripts" / filename, scripts / filename)
            source = root / "src.ouro"
            source.write_text("source", encoding="utf-8")
            os.utime(source, (100, 100))
            template = root / "template"
            template.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\nexit 23\n', encoding="utf-8")
            template.chmod(0o755)
            logical = root / "bin" / f"ouro-{area}-gate"
            logical.parent.mkdir()
            binary = Path(str(logical) + suffix)
            if name != "missing-binary":
                shutil.copyfile(template, binary)
                binary.chmod(0o755)
                os.utime(binary, (200, 200))
            if manifest is not None:
                sidecar = logical if name == "exe-logical-sidecar" else binary
                Path(str(sidecar) + ".sources").write_text(manifest, encoding="utf-8")
            if name in {"both-binaries", "stale-primary-with-fresh-exe"}:
                alternate = Path(str(logical) + ".exe")
                alternate.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
                alternate.chmod(0o755)
                os.utime(alternate, (200, 200))
                Path(str(alternate) + ".sources").write_text("src.ouro\n", encoding="utf-8")
            if name in {"newer-source", "exe-newer-source"}:
                os.utime(source, (300, 300))
            (scripts / "build_tool.sh").write_text('''#!/bin/sh
set -eu
printf '%s\\n' "$OURO_BUILD_TOOL_MODE" "$1" "$2" > build.log
case "$TEST_REBUILD" in
  fail) exit 17 ;;
  repair) cp template "$2"; chmod +x "$2"; printf 'src.ouro\\n' > "$2.sources" ;;
  noop) exit 0 ;;
esac
''', encoding="utf-8")
            env = os.environ.copy()
            env.update(OURO_C_BUILD_DIR="bin", OURO_BUILD_TOOL_MODE="host-wrapper", TEST_REBUILD=rebuild)
            arguments = ["--space=a b", "", "$(not-a-shell-command)"]
            result = subprocess.run(["sh", str(scripts / f"ouro_{area}_gate.sh"), *arguments],
                                    cwd=tmp, env=env, capture_output=True, text=True, timeout=10, check=False)
            success = not needs_build or rebuild == "repair"
            if result.returncode != (23 if success else 1):
                raise AssertionError(f"{area}/{name}: unexpected exit {result.returncode}: {result.stderr}")
            if result.stdout != ("\n".join(arguments) + "\n" if success else ""):
                raise AssertionError(f"{area}/{name}: stale execution or changed argv: {result.stdout!r}")
            log = root / "build.log"
            if log.exists() != needs_build:
                raise AssertionError(f"{area}/{name}: incorrect rebuild decision")
            if needs_build:
                # Compare exact shell paths: MSYS represents a Windows drive
                # differently from pathlib, even though both name this root.
                shell_root = subprocess.run(
                    ["sh", "-c", 'cd "$1" && pwd', "launcher-contract", str(root)],
                    cwd=tmp, env=env, capture_output=True, text=True, timeout=10, check=True,
                ).stdout.rstrip("\n")
                expected = ["native", f"tools/{area}_gate/main.ouro", f"{shell_root}/bin/ouro-{area}-gate"]
                if log.read_text(encoding="utf-8").splitlines() != expected:
                    raise AssertionError(f"{area}/{name}: rebuild did not force the exact native entry")
            marker = (f"EXECUTION_BACKEND=ouro-native-{area}-gate" if success else "STALE_BINARY_REJECTED")
            if marker not in result.stderr:
                raise AssertionError(f"{area}/{name}: missing {marker}: {result.stderr}")


def main() -> int:
    if not shutil.which("cc") and not shutil.which("gcc"):
        raise SystemExit("LANG_SPEED_SUITE: SKIP no C compiler")

    with tempfile.TemporaryDirectory(prefix="ouro-launcher-contract-") as directory:
        check_native_gate_launchers(Path(directory))

    # Build the hot-path binaries before exercising host behavior.
    run([sys.executable, "scripts/ouro_build.py", "build", "--verbosity", "quiet"])
    collect_laws = ROOT / "_build/collect-source-laws"
    collect_env = {**os.environ, "OURO_BUILD_TOOL_MODE": "native"}
    run(["sh", "scripts/build_tool.sh", "tests/native_build_collection_tests.ouro",
         str(collect_laws)], env=collect_env)
    if os.name == "nt":
        collect_laws = collect_laws.with_suffix(".exe")
    collection = run([str(collect_laws), "--collect-only"])
    if "PRECISION_SUITE native-build-collection rows=" not in collection.stdout:
        raise AssertionError(collection.stdout)
    fixtures = prepare("manifest", ROOT / "_build/smith/speed-inputs", 1)
    fmt_inputs = prepare("fmt", ROOT / "_build/smith/speed-inputs", 1)
    ergo_cmd = [
        "sh", "scripts/ouro1.sh", "test",
        "--manifest=" + (fixtures / "manifest.tsv").as_posix(), "--prefix=ERGO.",
        "--root=" + fixtures.as_posix(), "--out=_build/ergonomics_suite",
        "--suite-label=ERGONOMICS_SUITE",
    ]
    warm_ergo = run(ergo_cmd)
    if "ERGONOMICS_SUITE: PASS" not in warm_ergo.stdout:
        raise AssertionError(warm_ergo.stdout)
    assert_no_path_warning(warm_ergo.stdout, "warm ergonomics suite")

    cycle = subprocess.run(
        ["sh", "scripts/ouro1.sh", "collect",
         "tests/analyze/architecture_bad/outer.ouro"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
    )
    if cycle.returncode != 1 or "collect_units: import cycle" not in cycle.stdout:
        raise AssertionError(f"collector did not reject import cycle cleanly: {cycle.returncode}\n{cycle.stdout}")
    assert_no_path_warning(cycle.stdout, "cycle collection")

    basename = subprocess.run(
        ["sh", str(ROOT / "scripts/ouro1.sh"), "collect", "args.ouro"],
        cwd=ROOT / "std",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
    )
    units = basename.stdout.splitlines()
    if basename.returncode != 0 or "map.ouro" not in units or not units or units[-1] != "args.ouro":
        raise AssertionError(f"collector lost basename root directory: {basename.returncode}\n{basename.stdout}")
    assert_no_path_warning(basename.stdout, "basename collection")

    (ROOT / "_build").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ouro-speed-suite-", dir=ROOT / "_build") as d:
        tmp = Path(d)
        log = tmp / "python.log"
        fakebin = fake_python(tmp, log)
        env = os.environ.copy()
        env["PATH"] = str(fakebin) + os.pathsep + env.get("PATH", "")

        check = run(["sh", "scripts/ouro1.sh", "check", "std/io.ouro"], env=env)
        if "CHECK_OK" not in check.stdout:
            raise AssertionError(check.stdout)
        assert_no_path_warning(check.stdout, "ouro1.sh check")
        assert_no_python(log, "ouro1.sh check")

        # Help is also a hot UX path and must not bootstrap/build just to print usage.
        help_run = subprocess.run(
            ["sh", "scripts/ouro1.sh", "help"],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if help_run.returncode != 2 or "usage:" not in help_run.stdout:
            raise AssertionError(help_run.stdout)
        assert_no_path_warning(help_run.stdout, "ouro1.sh help")
        assert_no_python(log, "ouro1.sh help")

        coil_help = subprocess.run(
            ["sh", "scripts/coil.sh", "help"],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if coil_help.returncode != 2 or "usage:" not in coil_help.stdout:
            raise AssertionError(coil_help.stdout)
        assert_no_path_warning(coil_help.stdout, "coil.sh help")
        assert_no_python(log, "coil.sh help")

        ergo = run(ergo_cmd, env=env)
        if "ERGONOMICS_SUITE: PASS" not in ergo.stdout:
            raise AssertionError(ergo.stdout)
        assert_no_path_warning(ergo.stdout, "ergonomics suite hot path")
        assert_no_python(log, "ergonomics_suite hot path")

        imp = run([
            "sh", "scripts/ouro1.sh", "test",
            "--manifest=" + (fixtures / "manifest.tsv").as_posix(), "--prefix=IMP.",
            "--root=" + fixtures.as_posix(), "--out=_build/imports_suite",
            "--suite-label=IMPORTS_SUITE",
        ], env=env)
        if "IMPORTS_SUITE: PASS" not in imp.stdout:
            raise AssertionError(imp.stdout)
        assert_no_path_warning(imp.stdout, "imports suite hot path")
        assert_no_python(log, "imports_suite hot path")

        wrapper = tmp / "ouro-fmt"
        run(
            [sys.executable, "scripts/host_tools.py", "install-wrapper", "tools/fmt.ouro", str(wrapper)],
            env=env,
        )
        wrapper_text = wrapper.read_text(encoding="utf-8")
        if "scripts/python.sh" not in wrapper_text:
            raise AssertionError("host tool wrapper does not use the working-Python resolver")
        if os.name == "nt":
            log.unlink(missing_ok=True)
            wrapped = run(["sh", str(wrapper), (fmt_inputs / "clean.golden").as_posix()], env=env)
            golden = (fmt_inputs / "clean.golden").read_text(encoding="utf-8")
            if wrapped.stdout != golden:
                raise AssertionError("host formatter wrapper changed clean fixture output")

    print("LANG_SPEED_SIMPLICITY_SUITE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
