#!/usr/bin/env python3
"""Check temporary C-producer seams against freshly generated current Ouro code."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

import native_tool_build as native
import frontend_native_process as direct_process
import frontend_native_fs_create as direct_fs_create
import frontend_native_async as direct_async
import fs_replace_suite as direct_fs_replace
import ouro_build as build
from kernel_scale import pin_one_cpu
from ourosmith.limits import run_limited
from repo_support import configure_native_stack, sha256_file, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
KIND = "ouro.frontend-host-suite.v1"
ENTRY = "tools/native_build.ouro"
HOST_MAINS = {
    "n1-host-selftest": "runtime/n1_host_selftest.c",
    "frontend-link-selftest": "runtime/frontend_link_selftest.c",
    "n1-host": "runtime/n1_host_main.c",
}
SUPERVISOR_INPUTS = (
    "scripts/frontend_host_suite.py", "scripts/frontend_native_process.py", "scripts/frontend_native_fs_create.py",
    "scripts/frontend_native_async.py", "scripts/fs_replace_suite.py", "scripts/frontend_security_suite.sh",
    "scripts/kernel_scale.py", "scripts/ourosmith/host.py", "scripts/ourosmith/limits.py",
    "scripts/ourosmith/exec_child.py", "scripts/ourosmith/windows_job.py",
    "scripts/ourosmith/__init__.py", *HOST_MAINS.values(),
)
MIR_START = r"n1-host: mir functions=1 live=\d+\nn1-host: mir-check live=\d+\n"
ASSEMBLE = r"n1-host: assemble 1 atoms=\d+ bytes=\d+\n"
MIR_VALID = (
    MIR_START + r"n1-host: gc-infer live=\d+\n"
    r"n1-host: gc-infer-c rounds=1 bodies=1\n"
    r"n1-host: annotate live=\d+\n"
    r"n1-host: gc-annotate-c functions=1\n"
    r"n1-host: gc-check-c functions=1\n"
    r"n1-host: codegen live=\d+\n" + ASSEMBLE +
    r"n1-host: body-c 1\nn1-host: finish-c functions=1 bytes=\d+\n"
)


def probe_cases():
    cases = [("n1-host-selftest", ["valid"], 0, "N1_HOST_MIR: emitted valid\n", MIR_VALID)]
    cases.append(("n1-host-selftest", ["diagnostic-strings"], 0, "N1_HOST_DIAGNOSTICS: passed\n",
                  re.escape("str: text\npacked: lower:entry:123\nlist: text\ncat: lower:body:456\n"
                            "empty: \nbinary: a\0z\ninvalid: <non-string tag=77 n=0>\n")))
    cases.append(("n1-host-selftest", ["valid-quiet"], 0, "N1_HOST_MIR: emitted valid-quiet\n",
                  MIR_START + r"n1-host: gc-infer live=\d+\nn1-host: annotate live=\d+\n"
                  r"n1-host: codegen live=\d+\n"))
    for mode, diagnostic in (("uninitialized", "uninitialized"), ("bad-return", "return")):
        cases.append(("n1-host-selftest", [mode], 1, "", MIR_START +
                      r"n1-host: mir-check failed tag=0 n=1 live=\d+\n" +
                      "n1-host: mir:" + diagnostic + "\n"))
    for mode in ("mir-program-context", "mir-flow-context", "codegen-program-context", "mir-phase-errors", "mir-phase-nested", "mir-reachability-rounds", "mir-flow-rounds"):
        stderr = ASSEMBLE + (r"n1-host: finish-c functions=0 bytes=0\n" * 4) if mode == "codegen-program-context" else ""
        cases.append(("n1-host-selftest", [mode], 0, f"N1_HOST_CONTEXT: passed {mode}\n", stderr))
    for mode in ("lower-raw-order", "lower-raw-left", "lower-survivors"):
        cases.append(("n1-host-selftest", [mode], 0, f"N1_HOST_LOWER: passed {mode}\n", ""))
    for mode in ("pe-byte-large", "pe-byte-errors", "pe-byte-context", "pe-patch-context"):
        cases.append(("n1-host-selftest", [mode], 0, f"N1_HOST_PE: passed {mode}\n", ""))
    for mode, diagnostic in (("lower-bad-result", "raw returned an invalid lowering result"),
                             ("lower-bad-result-quiet", "raw returned an invalid lowering result"),
                             ("lower-bad-chunk", "raw returned an invalid list"),
                             ("lower-bad-contracts", "contracts returned an invalid list")):
        cases.append(("n1-host-selftest", [mode], 2, "", re.escape(f"n1-host: {diagnostic}\n")))
    for mode in ("caller-output", "retained-result", "typed-failure", "nested-context", "allocation-context",
                 "shared-parent-spine",
                 "recheck-scale", "recheck-retained", "recheck-late-invalid", "recheck-missing-bodies", "recheck-zero-fuel"):
        argv = [mode, "retained output.exe"] if mode == "caller-output" else [mode]
        stderr = re.escape("probe.ouro: type mismatch in wrong\n") if mode == "typed-failure" else ""
        cases.append(("frontend-link-selftest", argv, 0, f"FRONTEND_LINK_SELFTEST: passed {mode}\n", stderr))
    return cases


def verify_probe(result, case) -> None:
    _binary, argv, code, stdout, stderr = case
    if (result.status != "ok" or result.returncode != code or result.stdout != stdout
            or re.fullmatch(stderr, result.stderr) is None):
        raise ValueError(f"{argv[0]}: unexpected protocol (status={result.status}, exit={result.returncode})")


def snapshot(args, cfg) -> dict:
    units, inputs = native.tool_inputs(ENTRY, args.compiler, args.fuel, cfg)
    for name in SUPERVISOR_INPUTS:
        inputs["sources"][name] = sha256_file(ROOT / name)
    config = (args.config or ROOT / "Ouro.seal").resolve()
    inputs["sources"][str(config)] = sha256_file(config)
    return {"units": units, "inputs": inputs, "native_process": direct_process.source_snapshot(),
            "native_fs_create": direct_fs_create.source_snapshot(), "native_async": direct_async.source_snapshot(),
            "native_fs_replace": direct_fs_replace.source_snapshot()}


def require_snapshot(args, cfg, before: dict) -> dict:
    after = snapshot(args, cfg)
    if after != before:
        raise ValueError("source, producer, C compiler or build configuration changed during the suite")
    return after


def executable(work: Path, name: str) -> Path:
    return work / (name + (".exe" if os.name == "nt" else ""))


def build_worker(args, cfg) -> None:
    work = args.out
    before = json.loads((work / "inputs-before.json").read_text(encoding="utf-8"))
    require_snapshot(args, cfg, before)
    generated = work / "backend.gen.c"
    native.emit(args.compiler, before["units"], args.fuel, generated)
    exports = set(re.findall(r'case\s+\d+:\s*return\s+"([^"]+)"', generated.read_text(encoding="utf-8")))
    required = set()
    for source in HOST_MAINS.values():
        required.update(re.findall(r'(?:find_export|export_value)\("([^"]+)"',
                                   (ROOT / source).read_text(encoding="utf-8")))
    missing = required - exports
    if missing:
        raise ValueError("fresh backend lacks required host exports: " + ", ".join(sorted(missing)))
    report = {"kind": KIND + ".build", "generated_sha256": sha256_file(generated), "binaries": {}}
    common = [("generated", generated), *((name, ROOT / name) for name in native.RUNTIME
                                          if name != "runtime/ouro_prog_main.c")]
    for name, main in HOST_MAINS.items():
        require_snapshot(args, cfg, before)
        # Identical common sources share only this fresh invocation's checked objects.
        result = build.build_c_executable(cfg, name="frontend-host", sources=[*common, (main, ROOT / main)],
            output=executable(work, name), object_dir=work / "objects", include_dirs=[ROOT / "runtime"],
            extra_cflags=["-Werror=implicit-function-declaration", "-DOURO_FE_FLAT_EXPORTS"], jobs=1)
        report["binaries"][name] = {"sha256": sha256_file(executable(work, name)), "build": result}
    require_snapshot(args, cfg, before)
    if report["generated_sha256"] != sha256_file(generated):
        raise ValueError("generated backend changed during linking")
    write_json_atomic(work / "build.json", report)
    print("FRONTEND_HOST_BUILD: PASS", flush=True)


def verify_artifacts(work: Path, report: dict) -> None:
    if report.get("kind") != KIND + ".build" or set(report.get("binaries", {})) != set(HOST_MAINS):
        raise ValueError("incomplete host build report")
    if report["generated_sha256"] != sha256_file(work / "backend.gen.c"):
        raise ValueError("generated backend changed after emission")
    for name, row in report["binaries"].items():
        binary = executable(work, name)
        if not binary.is_file() or binary.stat().st_size == 0 or sha256_file(binary) != row["sha256"]:
            raise ValueError("host executable missing or changed: " + name)


def run_suite(args, cfg, argv: list[str]) -> int:
    args.out.mkdir(parents=True, exist_ok=True)
    work = args.out / ("host-" + uuid.uuid4().hex)
    work.mkdir()
    report = {"kind": KIND, "pass": False, "execution_backend": "generated-c-host",
              "native_bootstrap": False, "entry": ENTRY, "work": str(work), "steps": [],
              "workers": 1, "memory_mib": args.memory_mib, "build_timeout_s": args.build_timeout,
              "probe_timeout_s": args.probe_timeout,
              "producer": {"path": str(args.compiler), "selection": "caller-supplied --compiler; lineage not attested"}}
    before = None
    built = None
    try:
        report["cpu"] = pin_one_cpu()
        before = snapshot(args, cfg)
        report["producer"]["sha256"] = before["inputs"]["compiler_sha256"]
        write_json_atomic(work / "inputs-before.json", before)
        env = dict(os.environ, OURO_JOBS="1", OURO_FRONTEND_JOBS="1", OURO_CACHE="0",
                   OURO_CCACHE="disabled", OURO_MEM_TRACE="0", PYTHONDONTWRITEBYTECODE="1")
        temporary = work / "tmp"
        temporary.mkdir()
        env.update(TEMP=str(temporary), TMP=str(temporary), TMPDIR=str(temporary))

        def run(label: str, command: list[str], timeout: float, *, cwd: Path = ROOT):
            print("FRONTEND_HOST_SUITE:", label, flush=True)
            result = run_limited(command, cwd=cwd, env=env, timeout_s=timeout, memory_mb=args.memory_mib)
            row = {"label": label, "cwd": str(cwd), **asdict(result)}
            for stream in ("stdout", "stderr"):
                path = work / (label + "." + stream)
                path.write_text(getattr(result, stream), encoding="utf-8", newline="\n")
                row[stream] = path.name
                row[stream + "_sha256"] = sha256_file(path)
            report["steps"].append(row)
            return result

        command = [sys.executable, "-B", str(Path(__file__).resolve()), *argv,
                   "--worker", "--compiler", str(args.compiler), "--out", str(work),
                   "--jobs", "1", "--no-cache", "--ccache", "disabled", "--opt-level", str(cfg.values["opt_level"])]
        if args.config is not None:
            command.extend(["--config", str(args.config.resolve())])
        result = run("build", command, args.build_timeout)
        if not result.ok or not result.stdout.endswith("FRONTEND_HOST_BUILD: PASS\n"):
            raise ValueError(f"host build failed (status={result.status}, exit={result.returncode}); see {work / 'build.stderr'}")
        built = json.loads((work / "build.json").read_text(encoding="utf-8"))
        verify_artifacts(work, built)
        report["build"] = built
        report["build_report_sha256"] = sha256_file(work / "build.json")
        for case in probe_cases():
            require_snapshot(args, cfg, before)
            verify_artifacts(work, built)
            name, arguments, _code, _stdout, _stderr = case
            result = run(arguments[0], [str(executable(work, name)), *arguments], args.probe_timeout)
            verify_probe(result, case)
        def verify_native_inputs():
            require_snapshot(args, cfg, before)
            verify_artifacts(work, built)

        report["native_process"] = direct_process.run_section(executable(work, "n1-host"), work, run,
            args.build_timeout, args.probe_timeout, verify_native_inputs)
        report["native_fs_create"] = direct_fs_create.run_section(executable(work, "n1-host"), work, run,
            args.build_timeout, args.probe_timeout, verify_native_inputs)
        report["native_async"] = direct_async.run_section(executable(work, "n1-host"), work, run,
            args.build_timeout, args.probe_timeout, verify_native_inputs)
        report["native_fs_replace"] = direct_fs_replace.run_native_section(executable(work, "n1-host"), work, run,
            args.build_timeout, verify_native_inputs)
        report["pass"] = True
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, SystemExit) as error:
        report["error"] = str(error)
    finally:
        if before is not None:
            try:
                after = snapshot(args, cfg)
                write_json_atomic(work / "inputs-after.json", after)
                report["inputs_unchanged"] = after == before
                report["producer"]["sha256_after"] = after["inputs"]["compiler_sha256"]
                if after != before:
                    raise ValueError("source, producer or C build inputs changed")
                if built is not None:
                    verify_artifacts(work, built)
                    report["generated_sha256_after"] = sha256_file(work / "backend.gen.c")
            except (OSError, ValueError, KeyError, TypeError, SystemExit) as error:
                report["pass"] = False
                report["integrity_error"] = str(error)
        write_json_atomic(work / "report.json", report)
        write_json_atomic(args.out / "frontend-host.json", report)
    if report["pass"]:
        native_status = report["native_process"]["status"]
        fs_status = report["native_fs_create"]["status"]
        async_status = report["native_async"]["status"]
        replace_status = report["native_fs_replace"]["status"]
        print(f"FRONTEND_HOST_SUITE: PASS cases={len(probe_cases())} native_process={native_status} "
              f"native_fs_create={fs_status} native_async={async_status} native_fs_replace={replace_status} out={work}", flush=True)
        return 0
    print(f"FRONTEND_HOST_SUITE: FAIL {report.get('error', report.get('integrity_error'))}; see {work}", file=sys.stderr, flush=True)
    return 1


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fuel", type=int, default=200000)
    parser.add_argument("--memory-mib", type=int, default=3072)
    parser.add_argument("--build-timeout", type=float, default=900)
    parser.add_argument("--probe-timeout", type=float, default=30)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    build.add_common(parser)
    args = parser.parse_args(argv)
    if (args.fuel < 1 or args.memory_mib < 1 or any(not math.isfinite(value) or value <= 0
                                                for value in (args.build_timeout, args.probe_timeout))):
        parser.error("fuel, memory and timeouts must be positive and finite")
    args.compiler, args.out = args.compiler.resolve(), args.out.resolve()
    if args.config is not None:
        args.config = (ROOT / args.config).resolve()
    if os.name == "nt" and not args.compiler.is_file() and Path(str(args.compiler) + ".exe").is_file():
        args.compiler = Path(str(args.compiler) + ".exe")
    args.jobs, args.cache_enabled, args.ccache = "1", False, "disabled"
    args.opt_level = args.opt_level or "O0"
    try:
        configure_native_stack()
        cfg = build.load_config(args)
        if args.worker:
            build_worker(args, cfg)
            return 0
        return run_suite(args, cfg, argv)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print("FRONTEND_HOST_SUITE: FAIL", error, file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
