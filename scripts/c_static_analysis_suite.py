#!/usr/bin/env python3
"""Fail-closed analysis for the handwritten C host boundary."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Sequence

from repo_support import bind_relative_path, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
rel = bind_relative_path(ROOT, resolve=True)
REPORT_KIND = "ouro.c-static-analysis-report.v1"
FIXTURES = ROOT / "quality" / "fixtures" / "c_static_analysis"
COMMON_FLAGS = [
    "-std=c99",
    "-D_POSIX_C_SOURCE=200809L",
    "-Iruntime",
    "-Wall",
    "-Wextra",
    "-Wpedantic",
    "-Werror",
]
CLANG_DISABLED_CHECKERS = ["unix.Stream", "unix.Errno"]


@dataclass(frozen=True)
class Check:
    name: str
    engine: str
    expectation: str
    status: str
    returncode: Optional[int]
    command: list[str]
    log: str
    detail: str


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", default="_build/c_static_analysis")
    p.add_argument("--gcc", default=os.environ.get("OURO_GCC", ""))
    p.add_argument("--clang", default=os.environ.get("OURO_CLANG", ""))
    p.add_argument("--timeout-seconds", type=float, default=180.0)
    return p


def resolve_out(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def find_tool(explicit: str, name: str, extra: Sequence[Path] = ()) -> Optional[str]:
    if explicit:
        found = shutil.which(explicit)
        if found is not None:
            return found
        path = Path(explicit)
        if path.is_file():
            return str(path)
        return None
    found = shutil.which(name)
    if found is not None:
        return found
    for path in extra:
        if path.is_file():
            return str(path)
    return None


def capture(cmd: Sequence[str] | str, *, env: Optional[dict[str, str]] = None, encoding: str = "utf-8") -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd if isinstance(cmd, str) else list(cmd),
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding=encoding,
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return proc.returncode, proc.stdout or ""


def tool_version(tool: str) -> str:
    rc, output = capture([tool, "--version"])
    if rc != 0:
        return f"unavailable (exit={rc})"
    return output.splitlines()[0] if output.splitlines() else "unknown"


def run_check(
    checks: list[Check],
    *,
    out: Path,
    name: str,
    engine: str,
    command: Sequence[str],
    expectation: str,
    timeout: float,
    markers: Sequence[str] = (),
    env: Optional[dict[str, str]] = None,
) -> bool:
    log = out / "logs" / f"{name}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    command_list = list(command)
    returncode: Optional[int]
    try:
        proc = subprocess.run(
            command_list,
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        returncode = proc.returncode
        output = proc.stdout or ""
    except subprocess.TimeoutExpired as exc:
        returncode = None
        captured = exc.stdout or ""
        if isinstance(captured, bytes):
            captured = captured.decode("utf-8", errors="replace")
        output = f"TIMEOUT after {timeout:.1f}s\n{captured}"
    except OSError as exc:
        returncode = None
        output = f"EXEC_ERROR {exc}\n"
    log.write_text(output, encoding="utf-8")

    marker_ok = not markers or any(marker.lower() in output.lower() for marker in markers)
    if expectation == "pass":
        passed = returncode == 0
        detail = "exit=0 required"
    elif expectation == "deny":
        passed = returncode not in (None, 0) and marker_ok
        detail = "finding must produce nonzero exit and a stable diagnostic marker"
    else:  # pragma: no cover - internal misuse
        raise ValueError(f"unknown expectation: {expectation}")
    checks.append(
        Check(
            name=name,
            engine=engine,
            expectation=expectation,
            status="pass" if passed else "fail",
            returncode=returncode,
            command=command_list,
            log=rel(log),
            detail=detail,
        )
    )
    return passed


def windows_clang_target(gcc: str) -> list[str]:
    if os.name != "nt":
        return []
    rc, output = capture([gcc, "-dumpmachine"])
    target = output.strip() if rc == 0 else ""
    if "mingw" not in target:
        return []
    toolchain = Path(gcc).resolve().parent.parent
    return [
        f"--target={target}",
        f"--gcc-toolchain={toolchain}",
        "-Wno-unused-command-line-argument",
    ]


def gcc_command(gcc: str, source: Path, obj: Path) -> list[str]:
    obj.parent.mkdir(parents=True, exist_ok=True)
    return [gcc, *COMMON_FLAGS, "-fanalyzer", "-c", rel(source), "-o", rel(obj)]


def available_clang_exclusions(clang: str) -> list[str]:
    rc, output = capture([clang, "-cc1", "-analyzer-checker-help"])
    if rc != 0:
        return []
    names = {line.split()[0] for line in output.splitlines() if line.startswith("  ") and line.split()}
    return [checker for checker in CLANG_DISABLED_CHECKERS if checker in names]


def clang_command(
    clang: str, target: Sequence[str], exclusions: Sequence[str], source: Path
) -> list[str]:
    analyzer_flags = (
        ["-Xanalyzer", "-analyzer-disable-checker=" + ",".join(exclusions)]
        if exclusions
        else []
    )
    return [
        clang,
        *target,
        "--analyze",
        *analyzer_flags,
        "-Xanalyzer",
        "-analyzer-werror",
        "-Xanalyzer",
        "-analyzer-output=text",
        *COMMON_FLAGS,
        rel(source),
    ]


def sanitizer_command(clang: str, sources: Sequence[Path], exe: Path) -> list[str]:
    exe.parent.mkdir(parents=True, exist_ok=True)
    platform_flags = ["-D_CRT_SECURE_NO_WARNINGS"] if os.name == "nt" else []
    return [
        clang,
        *COMMON_FLAGS,
        *platform_flags,
        "-O1",
        "-g",
        "-fno-omit-frame-pointer",
        "-fsanitize=address,undefined",
        *(rel(source) for source in sources),
        "-o",
        rel(exe),
    ]


def msvc_environment(env: dict[str, str]) -> dict[str, str]:
    """Use an installed MSVC toolchain, including VS versions newer than Clang."""
    if os.name != "nt" or env.get("VCToolsInstallDir"):
        return env
    installer = Path(env.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
    if not installer.is_file():
        return env
    rc, output = capture([str(installer), "-latest", "-prerelease", "-products", "*", "-requires",
                          "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath", "-utf8"], env=env)
    if rc != 0:
        raise RuntimeError(f"MSVC discovery failed with exit {rc}")
    installation = output.strip()
    if not installation:
        return env
    setup = Path(installation) / "VC/Auxiliary/Build/vcvars64.bat"
    if not setup.is_file() or any(c in str(setup) for c in '"%\r\n'):
        raise RuntimeError("MSVC discovery returned an unusable vcvars64.bat path")
    # Read only compiler-related variables, never the complete environment.
    command = f'call "{setup}" >nul && (set INCLUDE & set LIB & set PATH & set VCToolsInstallDir & set VCINSTALLDIR)'
    # cmd uses its own quoting, not the CRT backslash-quote convention applied
    # by subprocess to argv lists. This batch path was checked above.
    executable = subprocess.list2cmdline([env.get("COMSPEC", "cmd.exe")])
    rc, output = capture(f'{executable} /d /u /s /c "{command}"', env=env, encoding="utf-16le")
    if rc != 0:
        raise RuntimeError(f"MSVC environment setup failed with exit {rc}")
    keys = {"INCLUDE", "LIB", "LIBPATH", "PATH", "VCTOOLSINSTALLDIR", "VCINSTALLDIR"}
    updated = dict(env)
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if separator and key.upper() in keys:
            # Windows names are case-insensitive; avoid stale duplicate keys.
            for old in tuple(updated):
                if old.upper() == key.upper():
                    del updated[old]
            updated["PATH" if key.upper() == "PATH" else key] = value
    if not all(any(key.upper() == needed and value for key, value in updated.items()) for needed in ("INCLUDE", "LIB", "VCTOOLSINSTALLDIR")):
        raise RuntimeError("MSVC setup omitted a required compiler environment variable")
    return updated


def sanitizer_env(clang: str) -> dict[str, str]:
    env = msvc_environment(os.environ.copy())
    env["ASAN_OPTIONS"] = (
        "halt_on_error=1:abort_on_error=1:detect_leaks=1"
        if sys.platform.startswith("linux")
        else "halt_on_error=1:abort_on_error=1:detect_leaks=0"
    )
    env["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
    if os.name == "nt":
        rc, output = capture([clang, "--print-resource-dir"])
        if rc == 0 and output.strip():
            runtime = Path(output.strip()) / "lib" / "windows"
            env["PATH"] = str(runtime) + os.pathsep + env.get("PATH", "")
    return env


def run_suite(args: argparse.Namespace) -> tuple[dict[str, object], int]:
    out = resolve_out(args.out)
    out.mkdir(parents=True, exist_ok=True)
    checks: list[Check] = []
    issues: list[str] = []
    gcc = find_tool(args.gcc, "gcc")
    clang = find_tool(
        args.clang,
        "clang",
        (Path("C:/Program Files/LLVM/bin/clang.exe"),) if os.name == "nt" else (),
    )
    tools: dict[str, object] = {
        "gcc": None if gcc is None else {"path": gcc, "version": tool_version(gcc)},
        "clang": None if clang is None else {"path": clang, "version": tool_version(clang)},
    }
    clang_exclusions = available_clang_exclusions(clang) if clang is not None else []
    if gcc is None:
        issues.append("required GCC with -fanalyzer support was not found")
    if clang is None:
        issues.append("required Clang Static Analyzer and sanitizer runtime were not found")

    good = FIXTURES / "good.c"
    bad = FIXTURES / "bad_use_after_free.c"
    allocation_fixture = FIXTURES / "bounded_capture_allocation.c"
    fixtures = [good, bad, *([allocation_fixture] if os.name == "nt" else [])]
    sources = sorted((ROOT / "runtime").glob("*.c"), key=lambda path: path.name)
    for fixture in fixtures:
        if not fixture.is_file():
            issues.append(f"missing fixture: {rel(fixture)}")
    if not sources:
        issues.append("no handwritten C sources found under runtime")

    if gcc is not None and good.is_file() and bad.is_file():
        run_check(
            checks,
            out=out,
            name="gcc-fixture-good",
            engine="gcc-fanalyzer",
            command=gcc_command(gcc, good, out / "objects" / "gcc" / "fixture-good.o"),
            expectation="pass",
            timeout=args.timeout_seconds,
        )
        run_check(
            checks,
            out=out,
            name="gcc-fixture-bad",
            engine="gcc-fanalyzer",
            command=gcc_command(gcc, bad, out / "objects" / "gcc" / "fixture-bad.o"),
            expectation="deny",
            markers=("use-after-free", "use after 'free'"),
            timeout=args.timeout_seconds,
        )
        for source in sources:
            run_check(
                checks,
                out=out,
                name=f"gcc-{source.stem}",
                engine="gcc-fanalyzer",
                command=gcc_command(gcc, source, out / "objects" / "gcc" / f"{source.stem}.o"),
                expectation="pass",
                timeout=args.timeout_seconds,
            )

    if gcc is not None and os.name == "nt":
        allocation_exe = out / "bounded-capture-allocation.exe"
        allocation_built = run_check(
            checks, out=out, name="bounded-capture-allocation-build", engine="gcc-runtime",
            command=[gcc, *COMMON_FLAGS, "-O1", "runtime/ouro_rt.c",
                     rel(allocation_fixture), "-o", rel(allocation_exe)],
            expectation="pass", timeout=args.timeout_seconds,
        )
        if allocation_built:
            run_check(
                checks, out=out, name="bounded-capture-allocation-run", engine="gcc-runtime",
                command=[str(allocation_exe), str(out / "empty-capture")],
                expectation="pass", markers=("BOUNDED_CAPTURE_ALLOCATION: PASS",),
                timeout=args.timeout_seconds,
            )

    if clang is not None and good.is_file() and bad.is_file():
        target = windows_clang_target(gcc) if gcc is not None else []
        run_check(
            checks,
            out=out,
            name="clang-fixture-good",
            engine="clang-static-analyzer",
            command=clang_command(clang, target, clang_exclusions, good),
            expectation="pass",
            timeout=args.timeout_seconds,
        )
        run_check(
            checks,
            out=out,
            name="clang-fixture-bad",
            engine="clang-static-analyzer",
            command=clang_command(clang, target, clang_exclusions, bad),
            expectation="deny",
            markers=("[unix.Malloc]",),
            timeout=args.timeout_seconds,
        )
        for source in sources:
            run_check(
                checks,
                out=out,
                name=f"clang-{source.stem}",
                engine="clang-static-analyzer",
                command=clang_command(clang, target, clang_exclusions, source),
                expectation="pass",
                timeout=args.timeout_seconds,
            )

        san_env = sanitizer_env(clang)
        good_exe = out / "sanitizers" / ("fixture-good.exe" if os.name == "nt" else "fixture-good")
        bad_exe = out / "sanitizers" / ("fixture-bad.exe" if os.name == "nt" else "fixture-bad")
        good_built = run_check(
            checks,
            out=out,
            name="sanitizer-fixture-good-build",
            engine="asan-ubsan",
            command=sanitizer_command(clang, [good], good_exe),
            expectation="pass",
            timeout=args.timeout_seconds,
            env=san_env,
        )
        if good_built:
            run_check(
                checks,
                out=out,
                name="sanitizer-fixture-good-run",
                engine="asan-ubsan",
                command=[str(good_exe)],
                expectation="pass",
                timeout=args.timeout_seconds,
                env=san_env,
            )
        bad_built = run_check(
            checks,
            out=out,
            name="sanitizer-fixture-bad-build",
            engine="asan-ubsan",
            command=sanitizer_command(clang, [bad], bad_exe),
            expectation="pass",
            timeout=args.timeout_seconds,
            env=san_env,
        )
        if bad_built:
            run_check(
                checks,
                out=out,
                name="sanitizer-fixture-bad-run",
                engine="asan-ubsan",
                command=[str(bad_exe)],
                expectation="deny",
                markers=("AddressSanitizer", "runtime error:"),
                timeout=args.timeout_seconds,
                env=san_env,
            )

        runtime_exe = out / "sanitizers" / ("rt-selftest.exe" if os.name == "nt" else "rt-selftest")
        runtime_built = run_check(
            checks,
            out=out,
            name="sanitizer-runtime-build",
            engine="asan-ubsan",
            command=sanitizer_command(
                clang,
                [ROOT / "runtime/ouro_rt.c", ROOT / "runtime/rt_selftest.c"],
                runtime_exe,
            ),
            expectation="pass",
            timeout=args.timeout_seconds,
            env=san_env,
        )
        if runtime_built:
            run_check(
                checks,
                out=out,
                name="sanitizer-runtime-run",
                engine="asan-ubsan",
                command=[str(runtime_exe)],
                expectation="pass",
                timeout=args.timeout_seconds,
                env=san_env,
            )
            for invalid in ("app-null", "app-value", "apply-null", "apply-value"):
                run_check(
                    checks,
                    out=out,
                    name="sanitizer-runtime-" + invalid,
                    engine="asan-ubsan",
                    command=[str(runtime_exe), invalid],
                    expectation="deny",
                    markers=("ouro_rt: apply of non-function",),
                    timeout=args.timeout_seconds,
                    env=san_env,
                )

        if os.name != "nt":
            io_exe = out / "sanitizers" / "io-selftest"
            io_built = run_check(
                checks,
                out=out,
                name="sanitizer-io-build",
                engine="asan-ubsan",
                command=sanitizer_command(
                    clang,
                    [
                        ROOT / "runtime/ouro_rt.c",
                        ROOT / "runtime/ouro_io.c",
                        ROOT / "runtime/ouro_io_selftest.c",
                    ],
                    io_exe,
                ),
                expectation="pass",
                timeout=args.timeout_seconds,
            )
            if io_built:
                run_check(
                    checks,
                    out=out,
                    name="sanitizer-io-run",
                    engine="asan-ubsan",
                    command=[str(io_exe)],
                    expectation="pass",
                    timeout=args.timeout_seconds,
                    env=san_env,
                )
                for invalid in ("u8", "loop"):
                    run_check(
                        checks,
                        out=out,
                        name="sanitizer-io-invalid-" + invalid,
                        engine="asan-ubsan",
                        command=[str(io_exe), "--invalid-" + invalid],
                        expectation="deny",
                        markers=("ouro run: invalid U8 runtime value",),
                        timeout=args.timeout_seconds,
                        env=san_env,
                    )

    failed_checks = [check.name for check in checks if check.status != "pass"]
    passed = not issues and not failed_checks
    report: dict[str, object] = {
        "kind": REPORT_KIND,
        "pass": passed,
        "policy": {
            "severity": "deny",
            "missing_required_tool": "fail",
            "source_scope": "handwritten runtime/*.c; generated compiler/stage0 is excluded",
            "clang_disabled_checkers": clang_exclusions,
            "clang_disabled_checker_reason": "unstable stream/errno state modeling; core, security, allocation, bounds, and compiler warnings remain blocking",
            "sanitizers": ["address", "undefined"],
        },
        "tools": tools,
        "sources": [rel(source) for source in sources],
        "fixtures": [rel(fixture) for fixture in fixtures],
        "checks": [asdict(check) for check in checks],
        "issues": issues,
        "failed_checks": failed_checks,
    }
    write_json_atomic(out / "c-static-analysis.json", report)
    return report, 0 if passed else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parser().parse_args(argv)
    report, rc = run_suite(args)
    for check in report["checks"]:
        assert isinstance(check, dict)
        print(
            f"C_ANALYSIS_CHECK {check['status']} {check['engine']} {check['name']} "
            f"rc={check['returncode']} log={check['log']}"
        )
    for issue in report["issues"]:
        print(f"C_ANALYSIS_ISSUE {issue}", file=sys.stderr)
    print(
        f"C_STATIC_ANALYSIS: {'PASS' if rc == 0 else 'FAIL'} "
        f"checks={len(report['checks'])} failed={len(report['failed_checks'])} "
        f"report={rel(resolve_out(args.out) / 'c-static-analysis.json')}"
    )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
