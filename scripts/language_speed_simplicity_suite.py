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
import contextlib
import io
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], *, env: dict[str, str] | None = None, stdout: int | None = subprocess.PIPE) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd, cwd=ROOT, env=env, text=True, stdout=stdout,
            stderr=subprocess.STDOUT, check=True,
        )
    except subprocess.CalledProcessError as error:
        if error.stdout:
            print(error.stdout, end="", file=sys.stderr)
        raise


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


def check_host_quality_retirement(tmp: Path, *, source_root: Path = ROOT) -> None:
    """Host bootstrap may collect sources but must not decide source quality."""
    adapter = source_root / "scripts/host_tools.py"
    for entry in ("tools/fmt.ouro", "tools/analyze/main.ouro"):
        for spelling in (entry, str(source_root / entry)):
            for exists in (False, True):
                out = tmp / "quality-wrapper"
                out.unlink(missing_ok=True)
                if exists:
                    out.write_bytes(b"preserve existing executable\n")
                result = subprocess.run(
                    [sys.executable, str(adapter), "install-wrapper", spelling, str(out)],
                    cwd=source_root, capture_output=True, text=True, timeout=10, check=False,
                )
                if result.returncode != 3 or result.stdout or result.stderr:
                    raise AssertionError(f"quality wrapper was not rejected: {spelling}: {result}")
                if exists:
                    if out.read_bytes() != b"preserve existing executable\n":
                        raise AssertionError("rejected quality wrapper replaced an existing executable")
                elif out.exists():
                    raise AssertionError("rejected quality wrapper published an executable")
    for command in ("fmt", "analyze"):
        result = subprocess.run(
            [sys.executable, str(adapter), command], cwd=source_root,
            capture_output=True, text=True, timeout=10, check=False,
        )
        if result.returncode != 2 or result.stdout or "unknown command" not in result.stderr:
            raise AssertionError(f"retired Python quality command remained executable: {command}")
    collector = tmp / "ouro-collect"
    result = subprocess.run(
        [sys.executable, str(adapter), "install-wrapper", "tools/collect.ouro", str(collector)],
        cwd=source_root, capture_output=True, text=True, timeout=10, check=False,
    )
    if result.returncode != 0 or not collector.is_file():
        raise AssertionError(f"bootstrap collector wrapper was lost: {result}")
    if "scripts/python.sh" not in collector.read_text(encoding="utf-8"):
        raise AssertionError("collector wrapper lost the working-Python resolver")


def check_lint_launcher_protocol(tmp: Path, *, source_root: Path = ROOT) -> None:
    """Exercise host argv/status plumbing; the child is not an analysis oracle."""
    root = tmp / "quality launcher"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    shutil.copyfile(source_root / "scripts/ouro1.sh", scripts / "ouro1.sh")
    bindir = root / "bin"
    bindir.mkdir()
    compiler = bindir / "ouro1"
    compiler.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    compiler.chmod(0o755)
    (scripts / "build_tool.sh").write_text("#!/bin/sh\nexit 98\n", encoding="utf-8")
    binary = bindir / "ouro-lint"
    binary.write_text('''#!/bin/sh
set -eu
printf '%s\\0' "$@" > "$PROTOCOL_ARGS"
pwd > "$PROTOCOL_CWD"
printf '%s' "$PROTOCOL_STDOUT"
printf '%s' "$PROTOCOL_STDERR" >&2
exit "$PROTOCOL_STATUS"
''', encoding="utf-8")
    binary.chmod(0o755)
    cases = [(0, "", "", 0), (1, "finding\n", "", 1),
             (137, "", "crashed\n", 137), (0, "finding\n", "", 1),
             (0, "", "failed\n", 1), (2, "", "bad option\n", 2)]
    arguments = ["--deny", "directory with spaces", "", "line\nbreak.ouro",
                 "каталог/source.ouro", "$(not-a-shell-command).ouro"]
    # Python's Windows argv quoting leaves a lone LF unquoted, and MSYS splits
    # it before our launcher starts. Construct the exact test argv in the shell;
    # only fixed environment variable names enter this command, never values.
    argument_env = {f"PROTOCOL_ARG_{index}": value for index, value in enumerate(arguments)}
    forwarded = " ".join(f'"$PROTOCOL_ARG_{index}"' for index in range(len(arguments)))
    command = ["sh", "-c", f'exec sh "$1" lint {forwarded}',
               "lint-launcher-protocol", str(scripts / "ouro1.sh")]
    for status, stdout, stderr, expected_status in cases:
        env = {**os.environ, **argument_env, "OURO_ROOT": str(root), "OURO_C_BUILD_DIR": str(bindir),
               "OURO1_COMPILER": str(compiler), "PROTOCOL_ARGS": str(root / "argv"),
               "PROTOCOL_CWD": str(root / "cwd"), "PROTOCOL_STATUS": str(status),
               "PROTOCOL_STDOUT": stdout, "PROTOCOL_STDERR": stderr}
        result = subprocess.run(
            command, cwd=tmp, env=env,
            capture_output=True, text=True, timeout=10, check=False,
        )
        if result.returncode != expected_status or result.stdout != stdout:
            raise AssertionError(f"lint launcher changed status/output: {result}")
        expected_error = stderr
        if status == 0 and (stdout or stderr):
            expected_error += "LINT_FAIL: native runner returned success with diagnostic output\n"
        if result.stderr != expected_error:
            raise AssertionError(f"lint launcher changed failure protocol: {result.stderr!r}")
        if (root / "argv").read_bytes() != b"\0".join(a.encode() for a in arguments) + b"\0":
            raise AssertionError(f"lint launcher split or interpreted an argument: {(root / 'argv').read_bytes()!r}")
        shell_cwd = subprocess.run(["sh", "-c", "pwd"], cwd=tmp,
                                   capture_output=True, text=True, check=True).stdout
        if (root / "cwd").read_text(encoding="utf-8") != shell_cwd:
            raise AssertionError("lint launcher lost the caller's working directory")


def check_structured_result_protocol(tmp: Path) -> None:
    """Corrupt process reports are transport tests, never analysis oracles."""
    from unittest.mock import patch

    import analyze_bounded as bounded
    import analyze_production_suite as production

    clean = "ANALYZE_DRIVE files=1 findings=0 rejected=0 families=dataflow\n"
    finding = ("каталог/漢字 file.ouro:2:1: warning[OURO-DF001] dataflow/unused-param: unused\n"
               "  hint: use it\n  witness: value\n")
    diagnostic = finding + clean.replace("findings=0", "findings=1")
    rejected = clean.replace("rejected=0", "rejected=1")
    rejection = "std/io.ouro: structured analyzer could not build the unit: parse-fail\n"
    cases = [
        (0, clean, "", True), (1, diagnostic, "", True), (1, rejected, rejection, True),
        (137, clean, "", False), (124, clean, "", False), (0, clean, "OOM\n", False),
        (0, clean.replace("files=1", "files=0"), "", False),
        (0, clean.replace("files=1", "files=2"), "", False),
        (0, clean.replace("dataflow", "effects"), "", False),
        (0, clean.replace("dataflow", "dataflow,dataflow"), "", False),
        (0, clean.replace("dataflow", ""), "", False),
        (0, clean + clean, "", False), (0, "", "", False),
        (0, "unreported\n" + clean, "", False),
        (0, diagnostic, "", False), (1, clean, "", False),
        (1, clean.replace("findings=0", "findings=1"), "", False),
        (1, rejected, "", False), (1, rejected, rejection + rejection, False),
        (1, diagnostic, "crashed\n", False), (1, diagnostic + "garbage\n", "", False),
    ]
    for code, stdout, stderr, valid in cases:
        proc = subprocess.CompletedProcess([], code, stdout, stderr)
        error = bounded.drive_result_error(proc, files=1, families="dataflow")
        if bool(error) == valid:
            raise AssertionError(f"structured process protocol: valid={valid} error={error}: {proc}")
    if not bounded.drive_result_error(subprocess.CompletedProcess([], 1, diagnostic, ""),
                                     files=1, families="dataflow", path="std/io.ouro"):
        raise AssertionError("structured worker accepted a diagnostic for another file")
    try:
        bounded.run_native(Path(sys.executable), ["-c", "import sys; sys.stdout.buffer.write(bytes([255]))"], tmp)
    except UnicodeDecodeError:
        pass
    else:
        raise AssertionError("structured transport replaced invalid UTF-8 instead of rejecting it")
    metadata = subprocess.CompletedProcess([], 0, "ANALYZE_FAMILIES families=dataflow\n", "")
    missing = subprocess.CompletedProcess([], 0, clean.replace("files=1", "files=0"), "")
    with patch.object(bounded, "run_native", side_effect=[metadata, missing]), \
            contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        if bounded.run_drive_bounded(tmp / "unused", ["--enable-dataflow"], [ROOT / "std/io.ouro"]) != 2:
            raise AssertionError("bounded aggregation hid a missing file")
    for code, stdout, stderr in [(137, clean, ""), (0, clean.replace("files=1", "files=0"), "")]:
        proc = subprocess.CompletedProcess([], code, stdout, stderr)
        stale = tmp / "production/report.json"
        stale.parent.mkdir(exist_ok=True)
        stale.write_text('{"pass":true}\n', encoding="utf-8")
        with patch.object(production, "ensure_drive", return_value=(tmp / "unused", "")), \
                patch.object(production, "requested_drive_families", return_value="dataflow"), \
                patch.object(production, "run_sweep", return_value=(proc, 0.0)), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            if production.main(["--out", str(tmp / "production")]) != 1:
                raise AssertionError("production accepted an incomplete process report")
            if stale.exists():
                raise AssertionError("production retained a stale success report after failure")
    # Even an existing future-dated executable must pass the content builder.
    binary = tmp / "stale-drive"
    binary.write_bytes(b"stale executable\n")
    future = binary.stat().st_mtime + 86400
    os.utime(binary, (future, future))
    failed_build = subprocess.CompletedProcess([], 17, "receipt rejected\n", "")
    with patch.object(production.subprocess, "run", return_value=failed_build) as build:
        _, error = production.ensure_drive(binary)
        if not error or build.call_count != 1 or "scripts/build_tool.sh" not in build.call_args.args[0]:
            raise AssertionError("production accepted a stale executable without checking its receipt")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ouro-quality-host-contract-") as directory:
        check_host_quality_retirement(Path(directory))
        check_lint_launcher_protocol(Path(directory))
        check_structured_result_protocol(Path(directory))
    if sys.argv[1:] == ["--host-quality-only"]:
        print("HOST_QUALITY_CONTRACTS: PASS")
        return 0
    from ourosmith.native_inputs import prepare

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
    # Warm the native formatter before the no-Python hot-path assertion.
    run(["sh", "scripts/ouro1.sh", "fmt", "--check",
         (fmt_inputs / "clean.golden").as_posix()], env=collect_env)
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

        formatted = run(["sh", "scripts/ouro1.sh", "fmt",
                         (fmt_inputs / "clean.golden").as_posix()], env=env)
        golden = (fmt_inputs / "clean.golden").read_text(encoding="utf-8")
        if formatted.stdout != golden:
            raise AssertionError("native formatter changed the clean golden")
        assert_no_python(log, "native formatter hot path")

    print("LANG_SPEED_SIMPLICITY_SUITE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
