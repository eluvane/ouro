#!/usr/bin/env python3
"""Check temporary C-producer seams against freshly generated current Ouro code."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from functools import cache
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace
import uuid

import native_tool_build as native
import frontend_native_process as direct_process
import frontend_native_fs_create as direct_fs_create
import frontend_native_async as direct_async
import fs_replace_suite as direct_fs_replace
import fs_read_suite as direct_fs_read
import ouro_build as build
from frontend_regen import ImportBytesParser, SourceBytesReader, capture_unit_inputs
from kernel_scale import pin_one_cpu
from ourosmith.limits import run_limited, run_limited_bytes
from repo_support import configure_native_stack, decode_source_text, sha256_bytes, sha256_file, write_json_atomic
from selfhost_module_cache import cached_import_parser

ROOT = Path(__file__).resolve().parents[1]
KIND = "ouro.frontend-host-suite.v1"
ENTRY = "tests/frontend_host_codegen.ouro"
BACKEND_GROUP_SIZE = 256
HOST_MAINS = {
    "n1-host-selftest": "runtime/n1_host_selftest.c",
    "frontend-link-selftest": "runtime/frontend_link_selftest.c",
    "frontend-codegen-meta-selftest": "runtime/frontend_codegen_meta_selftest.c",
    "frontend-codegen-selftest": "runtime/frontend_codegen_selftest.c",
    "n1-host": "runtime/n1_host_main.c",
    "module-pure-scope-selftest": "runtime/module_pure_scope_selftest.c",
}
NATIVE_LIVE_GC_CASES = ("escaping_collect", "pap_reuse_collect", "pap_plateau")
NATIVE_LIVE_CASES = ("live-reclaim", "live-calls", "live-high-descriptor", *NATIVE_LIVE_GC_CASES)
NATIVE_LIVE_SYMBOLS = {"kernel32.dll": ("HeapCreate", "HeapAlloc", "HeapFree", "HeapDestroy")}
HEAP_OBSERVER_CASES = (
    ("allocated-freed", "tests/native_gc/heap_requested_bytes.ouro", 42, ""),
    ("deferred-reused", "tests/native_managed/source_heap_observer_reused.ouro", 42, "HEAP_OBSERVER_REUSED\n"),
    *(("reject-" + name, "tests/native_gc/heap_requested_reject_" + name + ".ouro", 73, "")
      for name in ("empty_bytes", "count_without_head", "small_byte_sum", "missing_owner", "null_context", "unaligned_context")),
)
HEAP_OBSERVER_REJECTIONS = (("missing", r"entry:[1-9][0-9]*", True),
                            ("axiom", r"body:[1-9][0-9]*", False),
                            ("extern", r"body:[1-9][0-9]*", False),
                            ("pointee", r"metadata:[1-9][0-9]*", False),
                            ("result", r"metadata:[1-9][0-9]*", False))
HEAP_OBSERVER_RUNTIME = "runtime/managed_heap_observer.ouro"
HEAP_OBSERVER_METRIC = "currently-allocated-managed-requested-bytes"
RAW_FN_VALUES = "tests/native_managed/source_raw_fn_values.ouro"
RAW_FN_CASES = (("deferred", "tests/native_managed/source_raw_fn_deferred.ouro", ""),
                ("stdio", "tests/native_managed/source_raw_fn_stdio.ouro", "B\nA\0Z\nC\0Z\nD\n"))
RAW_FN_IMPORTS = ("advapi32.dll", "bcrypt.dll", "kernel32.dll", "shell32.dll")
FILE_STATUS_FAULT_ENTRY = "tests/native_managed/source_file_read_status_fault.ouro"
FILE_STATUS_FAULT_CASES = ((0, "0", 42), (8, "5", 42), (9, "5", 42), (10, "5", 42),
                           (11, "38", 42), (12, "0", 73), (13, "0", 73), (14, "0", 73),
                           (15, "5", 42), (16, "0", 42), (17, "0", 73), (18, "0", 73))
FILE_STATUS_FAULT_IMPORTS = ("advapi32.dll", "bcrypt.dll", "kernel32.dll", "shell32.dll")
FILE_STATUS_FAULT_SYMBOLS = {
    "kernel32.dll": ("VirtualAlloc", "VirtualFree", "HeapCreate", "HeapAlloc", "HeapFree", "HeapDestroy",
                     "CreateFileW", "ReadFile", "GetFileSizeEx", "CloseHandle", "MultiByteToWideChar",
                     "GetLastError", "FlushFileBuffers", "ExitProcess", "GetCommandLineW", "LocalFree",
                     "WideCharToMultiByte", "GetStdHandle", "WriteFile"),
    "shell32.dll": ("CommandLineToArgvW",),
}
FILE_STATUS_FAULT_BYTES = bytes((65, 0, 255, 128, 10, 13, 90))
SUPERVISOR_INPUTS = (
    "scripts/frontend_host_suite.py", "scripts/frontend_native_process.py", "scripts/frontend_native_fs_create.py",
    "scripts/generated_c_shards.py",
    "scripts/frontend_native_async.py", "scripts/fs_replace_suite.py", "scripts/fs_read_suite.py", "scripts/frontend_security_suite.sh",
    "scripts/kernel_scale.py", "scripts/ourosmith/host.py", "scripts/ourosmith/limits.py",
    "scripts/ourosmith/exec_child.py", "scripts/ourosmith/windows_job.py",
    "scripts/ourosmith/__init__.py", "runtime/ouro_host_selftest.h", *HOST_MAINS.values(),
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
    for mode in ("caller-output", "retained-result", "typed-failure", "prepass-failure-order",
                 "nested-context", "allocation-context",
                 "shared-parent-spine", "wrapped-context",
                 "recheck-scale", "recheck-retained", "recheck-late-invalid", "recheck-missing-bodies", "recheck-zero-fuel"):
        argv = [mode, "retained output.exe"] if mode == "caller-output" else [mode]
        stderr = re.escape(
            "probe.ouro: type mismatch in wrong\n"
            "probe.ouro: OURO-LIST-001: list literal without known List A context in wrong (surface)\n"
            "  hint: Add a declaration/ascription such as : List Nat.\n"
        ) if mode == "typed-failure" else ""
        if mode == "prepass-failure-order":
            stderr = re.escape("OURO-IMP-002 error probe.ouro:1:1 duplicate import alias\n"
                               "hint: Each import alias name may appear only once in a file.\n")
        cases.append(("frontend-link-selftest", argv, 0, f"FRONTEND_LINK_SELFTEST: passed {mode}\n", stderr))
    cases.append(("frontend-codegen-meta-selftest", ["metadata-parity"], 0,
                  "FRONTEND_CODEGEN_META: passed metadata-parity\n", ""))
    for mode in ("fallback-forward", "root-parity", "root-clear-context",
                 "lower-contract-context", "check-module-context", "pe-operation-context",
                 "mir-bounds-outcomes", "mir-bounds-context",
                 "mir-function-partial", "mir-function-context"):
        cases.append(("frontend-codegen-selftest", [mode], 0,
                      f"FRONTEND_CODEGEN_SELFTEST: passed {mode}\n", ""))
    cases.append(("n1-host-selftest", ["phase-timing"], 0,
                  "N1_HOST_TIMING: passed phase-timing\n",
                  re.escape("n1-host: timing phase=sample elapsed_s=1.250\n"
                            "n1-host: timing phase=start-unavailable elapsed_s=unavailable\n"
                            "n1-host: timing phase=sample-unavailable elapsed_s=unavailable\n"
                            "n1-host: timing phase=backward elapsed_s=unavailable\n")))
    for mode in ("all", "order", "survivors", "allocation", "extended", "thunk-cycle", "outer-mark", "perm0"):
        cases.append(("module-pure-scope-selftest", [mode], 0,
                      f"MODULE_PURE_SCOPE_SELFTEST: passed {mode}\n", ""))
    for mode in ("invalid-arity0", "invalid-arity4", "invalid-arity8"):
        cases.append(("module-pure-scope-selftest", [mode], 1, "",
                      re.escape("ouro_rt: invalid module pure scope arity or callable\n")))
    for mode in ("prefix2", "prefix3"):
        cases.append(("module-pure-scope-selftest", [mode], 0,
                      f"MODULE_PURE_SCOPE_SELFTEST: passed {mode}\n", ""))
    return cases


def verify_probe(result, case) -> None:
    _binary, argv, code, stdout, stderr = case
    if (result.status != "ok" or result.returncode != code or result.stdout != stdout
            or re.fullmatch(stderr, result.stderr) is None):
        raise ValueError(f"{argv[0]}: unexpected protocol (status={result.status}, exit={result.returncode})")


def snapshot(args, cfg, *, parse_bytes: ImportBytesParser | None = None) -> dict:
    if parse_bytes is None:
        parse_bytes = cached_import_parser()

    # WindowsPath equality folds case even in case-sensitive directories.
    @cache
    def read_source_bytes(spelling: str) -> bytes:
        return Path(spelling).read_bytes()

    source_options = {"parse_bytes": parse_bytes, "read_source": lambda path: read_source_bytes(os.fspath(path))}
    units, inputs = native.tool_inputs(ENTRY, args.compiler, args.fuel, cfg, **source_options)
    for name in SUPERVISOR_INPUTS:
        inputs["sources"][name] = sha256_file(ROOT / name)
    config = (args.config or ROOT / "Ouro.seal").resolve()
    inputs["sources"][str(config)] = sha256_file(config)
    runtime_entry = "tests/native_managed/runtime.ouro"
    runtime_closures, runtime_sources = capture_unit_inputs((runtime_entry,), **source_options)
    runtime_units = runtime_closures[runtime_entry]
    captured = {"units": units, "inputs": inputs, "selected_compiler": str(args.compiler.resolve()),
                "native_file_status_fault": file_status_fault_snapshot(**source_options),
                "native_heap_observer": heap_observer_source_snapshot(**source_options),
                "native_process": direct_process.source_snapshot(**source_options),
                "native_fs_create": direct_fs_create.source_snapshot(**source_options),
                "native_async": direct_async.source_snapshot(**source_options),
                "native_fs_replace": direct_fs_replace.source_snapshot(**source_options),
                "native_fs_read": direct_fs_read.native_source_snapshot(**source_options),
                "native_raw_fn": raw_fn_source_snapshot(**source_options),
                "native_live": {"units": runtime_units,
                                "sources": {name: runtime_sources[name].sha256 for name in runtime_units}}}
    if sha256_file(args.compiler) != inputs["compiler_sha256"]:
        raise ValueError(f"selected compiler changed during frontend host input capture: {args.compiler}")
    initial_cc = json.loads(inputs["cc"])
    cc, location = build.locate_cc(cfg)
    cc_path = Path(location or cc).resolve()
    if (cc != initial_cc["cc"] or (location or str(cc_path)) != initial_cc["path"]
            or sha256_file(cc_path) != inputs["cc_sha256"]):
        raise ValueError(f"selected C compiler changed during frontend host input capture: {cc_path}")
    return captured


def require_snapshot(args, cfg, before: dict, *, parse_bytes: ImportBytesParser | None = None) -> dict:
    after = snapshot(args, cfg, parse_bytes=parse_bytes)
    if after != before:
        raise ValueError("source, producer, C compiler or build configuration changed during the suite")
    return after


def executable(work: Path, name: str) -> Path:
    return work / (name + (".exe" if os.name == "nt" else ""))


def require_generated_shards(work: Path, report: dict) -> None:
    shards = report["generated_c_shards"]
    manifest = work / "generated-c-shards/generated-c-shards.manifest.json"
    if shards["manifest_path"] != build.rel(manifest) or sha256_file(manifest) != report["shard_manifest_sha256"]:
        raise ValueError("generated shard manifest changed")
    ok, reason = build.GCS.manifest_valid(build.GCS.read_json(manifest),
        generator_hash=shards["generator_hash"], source_digests=shards["sources"], plan_meta=shards["shards"])
    if not ok:
        raise ValueError("generated host shards changed: " + reason)


def build_worker(args, cfg) -> None:
    work = args.out
    before = json.loads((work / "inputs-before.json").read_text(encoding="utf-8"))
    parse_bytes = cached_import_parser()
    require_snapshot(args, cfg, before, parse_bytes=parse_bytes)
    generated = work / "backend.gen.c"
    print("FRONTEND_HOST_BUILD: emit current backend", flush=True)

    def emit_phase(name: str, elapsed: float | None) -> None:
        event = "start" if elapsed is None else f"done elapsed_s={elapsed:.3f}"
        print(f"FRONTEND_HOST_EMIT: phase={name} {event}", flush=True)

    native.emit(args.compiler, before["units"], args.fuel, generated, phase_callback=emit_phase, parse_bytes=parse_bytes)
    print("FRONTEND_HOST_BUILD: backend emitted", flush=True)
    exports = set(re.findall(r'case\s+\d+:\s*return\s+"([^"]+)"', generated.read_text(encoding="utf-8")))
    required = set()
    for source in HOST_MAINS.values():
        required.update(re.findall(r'(?:find_export|export_value)\("([^"]+)"',
                                   (ROOT / source).read_text(encoding="utf-8")))
        required.update(re.findall(r'FIND\(lo,\s*"([^"]+)"',
                                   (ROOT / source).read_text(encoding="utf-8")))
    missing = required - exports
    if missing:
        raise ValueError("fresh backend lacks required host exports: " + ", ".join(sorted(missing)))
    generated_hash = sha256_file(generated)
    shard_sources, shard_report = build.GCS.materialize_generated_c_shards(
        frontend_c=None, backend_c=generated, out_dir=work / "generated-c-shards",
        label_prefix="frontend-host", cache_enabled=False, backend_group_size=BACKEND_GROUP_SIZE,
        backend_export_suffix="", report_path=work / "generated-c-shards-report.json")
    if generated_hash != sha256_file(generated):
        raise ValueError("generated backend changed during sharding")
    report = {"kind": KIND + ".build", "generated_sha256": generated_hash, "binaries": {},
              "generated_c_shards": shard_report,
              "shard_manifest_sha256": sha256_file(work / "generated-c-shards/generated-c-shards.manifest.json")}
    common = [*shard_sources, *((name, ROOT / name) for name in native.RUNTIME
                               if name != "runtime/ouro_prog_main.c")]
    for name, main in HOST_MAINS.items():
        require_snapshot(args, cfg, before, parse_bytes=parse_bytes)
        require_generated_shards(work, report)
        # Identical common sources share only this fresh invocation's checked objects.
        print(f"FRONTEND_HOST_BUILD: link {name}", flush=True)
        sources = [source for source in common if source[0] != "runtime/frontend_link.c"
                   or name not in ("frontend-codegen-meta-selftest", "frontend-codegen-selftest")]
        extra_cflags = ["-Werror=implicit-function-declaration", "-DOURO_FE_FLAT_EXPORTS"]
        source_cflags = ({main: ("-DOURO_MODULE_PURE_SCOPES=1",)}
                         if name == "module-pure-scope-selftest" else {})
        result = build.build_c_executable(cfg, name="frontend-host", sources=[*sources, (main, ROOT / main)],
            output=executable(work, name), object_dir=work / "objects", include_dirs=[ROOT / "runtime"],
            extra_cflags=extra_cflags, source_cflags=source_cflags, jobs=build.jobs_value(cfg),
            generated_c_shards=shard_report)
        report["binaries"][name] = {"sha256": sha256_file(executable(work, name)), "build": result}
    require_snapshot(args, cfg, before, parse_bytes=parse_bytes)
    if report["generated_sha256"] != sha256_file(generated):
        raise ValueError("generated backend changed during linking")
    require_generated_shards(work, report)
    write_json_atomic(work / "build.json", report)
    print("FRONTEND_HOST_BUILD: PASS", flush=True)


def verify_artifacts(work: Path, report: dict) -> None:
    if report.get("kind") != KIND + ".build" or set(report.get("binaries", {})) != set(HOST_MAINS):
        raise ValueError("incomplete host build report")
    if report["generated_sha256"] != sha256_file(work / "backend.gen.c"):
        raise ValueError("generated backend changed after emission")
    require_generated_shards(work, report)
    for name, row in report["binaries"].items():
        binary = executable(work, name)
        if not binary.is_file() or binary.stat().st_size == 0 or sha256_file(binary) != row["sha256"]:
            raise ValueError("host executable missing or changed: " + name)


def native_live_image(path, mode):
    return direct_process.inspect_image(path, ("kernel32.dll",),
                                        NATIVE_LIVE_SYMBOLS if mode in NATIVE_LIVE_GC_CASES else None)


def lineage_receipt_sha256(path: Path, expected: dict, diagnostic: str) -> str:
    contents = path.read_bytes()
    direct_process.require(json.loads(decode_source_text(contents)) == expected, diagnostic)
    return sha256_bytes(contents)


def native_live_lineage(work, before, built):
    diagnostic = "native liveness source/build receipt changed"
    inputs_sha256 = lineage_receipt_sha256(work / "inputs-before.json", before, diagnostic)
    build_sha256 = lineage_receipt_sha256(work / "build.json", built, diagnostic)
    sources = before["inputs"]["sources"]
    direct_process.require(all(name in sources for name in
        (ENTRY, "tests/native_live_runtime.ouro", "tests/native_managed_values.ouro",
         "tests/native_managed_fixtures.ouro", "runtime/frontend_codegen_selftest.c")),
        "native liveness producer source closure omits a fixture owner")
    return {"producer": str(executable(work, "frontend-codegen-selftest")),
            "producer_backend": "generated-c-host",
            "producer_sha256": built["binaries"]["frontend-codegen-selftest"]["sha256"],
            "generated_sha256": built["generated_sha256"],
            "seed_sha256": before["inputs"]["compiler_sha256"],
            "sources": sources, "runtime_inputs": before["native_live"],
            "inputs_report_sha256": inputs_sha256, "build_report_sha256": build_sha256}


def verify_native_live_result(result, mode):
    direct_process.require(result.get("status") == "ok" and type(result.get("returncode")) is int
                           and result["returncode"] == 42 and result.get("stdout") == ""
                           and result.get("stderr") == "",
                           f"{mode}: direct PE reclamation assertions failed")


def verify_native_live_report(report, lineage):
    direct_process.require(report.get("kind") == KIND + ".native-live" and report.get("status") == "pass"
                           and report.get("execution_backend") == "direct-windows-pe"
                           and report.get("external_supervisor") == "python"
                           and report.get("fixture_level") == "typed-mir"
                           and report.get("native_bootstrap") is False
                           and report.get("native_executed") is True and report.get("images_unchanged") is True
                           and report.get("lineage") == lineage,
                           "native liveness receipt is incomplete or stale")
    cases = report.get("cases", {})
    direct_process.require(isinstance(cases, dict) and set(cases) == set(NATIVE_LIVE_CASES)
                           and report.get("case_order") == list(NATIVE_LIVE_CASES),
                           "native liveness cases are missing, reordered, or unexpected")
    for mode, row in cases.items():
        direct_process.require(isinstance(row, dict), "native liveness row is malformed")
        output = str(Path(lineage["producer"]).with_name(mode + ".exe"))
        image, emission, result = row.get("image", {}), row.get("emission", {}), row.get("runtime", {})
        direct_process.require(isinstance(image, dict) and isinstance(emission, dict) and isinstance(result, dict),
                               "native liveness evidence is malformed")
        verify_native_live_result(result, mode)
        direct_process.require(row.get("path") == output and type(row.get("exit")) is int and row["exit"] == 42
                               and row.get("sha256") == image.get("sha256")
                               and re.fullmatch(r"[0-9a-f]{64}", str(image.get("sha256"))) is not None
                               and image.get("machine") == "x86_64" and image.get("imports") == ["kernel32.dll"]
                               and type(image.get("bytes")) is int and 0 < image["bytes"] <= 256 * 1024 * 1024
                               and emission.get("status") == "ok" and type(emission.get("returncode")) is int
                               and emission["returncode"] == 0
                               and emission.get("stdout") == f"FRONTEND_CODEGEN_SELFTEST: passed {mode}\n"
                               and emission.get("stderr") == ""
                               and emission.get("argv") == [lineage["producer"], mode, output]
                               and result.get("argv") == [output] and row.get("cwd") == str(ROOT),
                               "native liveness source/image/transport protocol differs: " + mode)
        if mode in NATIVE_LIVE_GC_CASES:
            symbols = image.get("import_symbols", {})
            direct_process.require(isinstance(symbols, dict)
                                   and set(NATIVE_LIVE_SYMBOLS["kernel32.dll"]).issubset(symbols.get("kernel32.dll", [])),
                                   "native GC PE required heap import symbols are missing: " + mode)


def verify_native_fixture_artifacts(work, lineage):
    for path, expected in ((work / "inputs-before.json", lineage["inputs_report_sha256"]),
                           (work / "build.json", lineage["build_report_sha256"]),
                           (work / "backend.gen.c", lineage["generated_sha256"]),
                           (executable(work, "frontend-codegen-selftest"), lineage["producer_sha256"])):
        direct_process.require(sha256_file(path) == expected, "native liveness lineage artifact changed: " + str(path))


def verify_native_live_artifacts(work, report):
    verify_native_fixture_artifacts(work, report["lineage"])
    for mode, row in report["cases"].items():
        direct_process.require(native_live_image(work / (mode + ".exe"), mode) == row["image"],
                               "native liveness PE changed: " + mode)


def heap_observer_rejection_entry(name):
    return "tests/native_managed/reject/source_heap_observer_" + name + ".ouro"


def heap_observer_source_snapshot(*, parse_bytes: ImportBytesParser | None = None,
                                  read_source: SourceBytesReader | None = None):
    entries = [entry for _case, entry, _code, _stdout in HEAP_OBSERVER_CASES]
    entries += [heap_observer_rejection_entry(name) for name, _diagnostic, _fallback in HEAP_OBSERVER_REJECTIONS]
    closures, captured = capture_unit_inputs(entries, parse_bytes=parse_bytes, read_source=read_source)
    checked_paths: set[str] = set()
    for entry, units in closures.items():
        direct_process.require(units and units[-1] == entry and len(units) == len(set(units))
                               and all((ROOT / name).resolve().is_relative_to(ROOT)
                                       for name in units if name not in checked_paths),
                               "heap observer source closure is incomplete or escapes: " + entry)
        direct_process.require((HEAP_OBSERVER_RUNTIME in units) == (entry in entries[:len(HEAP_OBSERVER_CASES)]),
                               "heap observer fixture has the wrong runtime owner: " + entry)
        checked_paths.update(units)
    return {"closures": closures, "sources": {name: captured[name].sha256 for name in sorted(checked_paths)}}


def heap_observer_lineage(work, before, built):
    lineage = native_raw_fn_lineage(work, before, built)
    direct_process.require(sha256_file(executable(work, "n1-host")) == lineage["producer_sha256"]
                           and sha256_file(work / "backend.gen.c") == lineage["generated_sha256"],
                           "heap observer producer or generated source changed")
    lineage["runtime_inputs"] = before["native_heap_observer"]
    return lineage


def heap_observer_image(path, case):
    imports = RAW_FN_IMPORTS if case == "deferred-reused" else ("kernel32.dll",)
    return direct_process.inspect_image(path, imports, NATIVE_LIVE_SYMBOLS)


def heap_observer_streams(work, case, result):
    streams = {}
    for stream, suffix in (("stdout", ".out"), ("stderr", ".err")):
        path = work / ("heap-observer-" + case + "-pe" + suffix)
        data = path.read_bytes()
        direct_process.require(data.hex() == result.get(stream + "_hex"), "heap observer stream changed: " + str(path))
        streams[stream] = {"path": path.name, "bytes": len(data), "sha256": sha256_file(path)}
    return streams


def verify_heap_observer_result(result, code, stdout):
    direct_process.require(result.get("status") == "ok" and type(result.get("returncode")) is int
                           and result["returncode"] == code and result.get("capture") == "bytes"
                           and result.get("stdout_hex") == stdout.encode("utf-8").hex()
                           and result.get("stderr_hex") == "", "heap observer runtime result differs")


def verify_heap_observer_artifacts(work, report):
    before = json.loads((work / "inputs-before.json").read_text(encoding="utf-8"))
    built = json.loads((work / "build.json").read_text(encoding="utf-8"))
    lineage = report["lineage"]
    direct_process.require(report.get("kind") == KIND + ".native-heap-observer" and report.get("status") == "pass"
                           and report.get("execution_backend") == "direct-windows-pe"
                           and report.get("native_bootstrap") is False and report.get("native_executed") is True
                           and report.get("metric") == HEAP_OBSERVER_METRIC
                           and lineage == heap_observer_lineage(work, before, built)
                           and lineage["runtime_inputs"] == heap_observer_source_snapshot(),
                           "heap observer report/source/producer is incomplete or stale")
    rows = report.get("rows", [])
    direct_process.require([row.get("case") for row in rows] == [case for case, _entry, _code, _text in HEAP_OBSERVER_CASES],
                           "heap observer runtime cases are missing or reordered")
    for row, (case, entry, code, stdout) in zip(rows, HEAP_OBSERVER_CASES, strict=True):
        output = work / "native-heap-observer" / (case + ".exe")
        units = lineage["runtime_inputs"]["closures"][entry]
        logical = output.relative_to(ROOT).as_posix()
        direct_process.require(row.get("entry") == entry and row.get("cwd") == str(ROOT)
                               and row.get("image") == heap_observer_image(output, case)
                               and row["emission"].get("argv") == [lineage["producer"], entry, logical, *units]
                               and row["result"].get("argv") == [str(output)]
                               and row.get("streams") == heap_observer_streams(work, case, row["result"]),
                               "heap observer image/source/byte protocol differs: " + case)
        verify_native_raw_fn_emission(row["emission"], logical, len(units))
        verify_heap_observer_result(row["result"], code, stdout)
    rejections = report.get("rejections", [])
    direct_process.require([row.get("case") for row in rejections] == [name for name, _diagnostic, _fallback in HEAP_OBSERVER_REJECTIONS],
                           "heap observer binding rejection cases are missing or reordered")
    for row, (name, diagnostic, fallback) in zip(rejections, HEAP_OBSERVER_REJECTIONS, strict=True):
        entry = heap_observer_rejection_entry(name)
        output = work / "native-heap-observer" / ("helper-" + name + ".exe")
        units = lineage["runtime_inputs"]["closures"][entry]
        result = row["result"]
        direct_process.require(row.get("entry") == entry and row.get("cwd") == str(ROOT)
                               and result.get("argv") == [lineage["producer"], entry, output.relative_to(ROOT).as_posix(), *units],
                               "heap observer rejection source protocol differs: " + name)
        direct_process.verify_rejection(SimpleNamespace(**result), diagnostic, output, fallback)


def run_heap_observer(work, run, build_timeout, probe_timeout, verify_inputs, before, built):
    if os.name != "nt":
        return {"kind": KIND + ".native-heap-observer", "status": "unavailable", "native_executed": False,
                "native_bootstrap": False, "reason": "direct PE execution requires Windows"}
    directory = work / "native-heap-observer"
    directory.mkdir()
    lineage = heap_observer_lineage(work, before, built)
    report = {"kind": KIND + ".native-heap-observer", "status": "running", "execution_backend": "direct-windows-pe",
              "native_bootstrap": False, "native_executed": False, "metric": HEAP_OBSERVER_METRIC,
              "lineage": lineage, "rows": [], "rejections": []}
    failure = None

    def unchanged():
        verify_inputs()
        direct_process.require(lineage == heap_observer_lineage(work, before, built)
                               and lineage["runtime_inputs"] == heap_observer_source_snapshot(),
                               "heap observer source or producer changed")
        for row in report["rows"]:
            case = row["case"]
            if "image" in row:
                direct_process.require(row["image"] == heap_observer_image(directory / (case + ".exe"), case),
                                       "heap observer image changed: " + case)
            if "streams" in row:
                direct_process.require(row["streams"] == heap_observer_streams(work, case, row["result"]),
                                       "heap observer streams changed: " + case)
        for row in report["rejections"]:
            direct_process.require(not (directory / ("helper-" + row["case"] + ".exe")).exists(),
                                   "heap observer rejected helper published an image")

    try:
        for case, entry, code, stdout in HEAP_OBSERVER_CASES:
            unchanged()
            output = directory / (case + ".exe")
            logical = output.relative_to(ROOT).as_posix()
            units = lineage["runtime_inputs"]["closures"][entry]
            row = {"case": case, "entry": entry, "cwd": str(ROOT)}
            report["rows"].append(row)
            write_json_atomic(directory / "report.json", report)
            row["emission"] = asdict(run("heap-observer-" + case + "-emit",
                [lineage["producer"], entry, logical, *units], build_timeout))
            write_json_atomic(directory / "report.json", report)
            verify_native_raw_fn_emission(row["emission"], logical, len(units))
            row["image"] = heap_observer_image(output, case)
            unchanged()
            row["result"] = bytes_run_record(run("heap-observer-" + case + "-pe", [str(output)], probe_timeout, capture_bytes=True))
            write_json_atomic(directory / "report.json", report)
            row["streams"] = heap_observer_streams(work, case, row["result"])
            verify_heap_observer_result(row["result"], code, stdout)
        for name, diagnostic, fallback in HEAP_OBSERVER_REJECTIONS:
            unchanged()
            entry = heap_observer_rejection_entry(name)
            output = directory / ("helper-" + name + ".exe")
            row = {"case": name, "entry": entry, "cwd": str(ROOT)}
            report["rejections"].append(row)
            write_json_atomic(directory / "report.json", report)
            result = run("heap-observer-helper-" + name,
                         [lineage["producer"], entry, output.relative_to(ROOT).as_posix(),
                          *lineage["runtime_inputs"]["closures"][entry]], build_timeout)
            row["result"] = asdict(result)
            write_json_atomic(directory / "report.json", report)
            direct_process.verify_rejection(result, diagnostic, output, fallback)
        unchanged()
        report.update(status="pass", native_executed=True)
        verify_heap_observer_artifacts(work, report)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        report.update(status="failed", error=str(error))
        failure = error
    finally:
        try:
            unchanged()
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            report.update(status="failed", integrity_error=str(error))
            if failure is None:
                failure = error
        write_json_atomic(directory / "report.json", report)
    if failure is not None:
        raise failure
    verify_heap_observer_artifacts(work, json.loads((directory / "report.json").read_text(encoding="utf-8")))
    return report


def raw_fn_source_snapshot(*, parse_bytes: ImportBytesParser | None = None,
                           read_source: SourceBytesReader | None = None):
    entries = [entry for _case, entry, _stdout in RAW_FN_CASES]
    closures, captured = capture_unit_inputs(entries, parse_bytes=parse_bytes, read_source=read_source)
    for entry, units in closures.items():
        direct_process.require(units and units[-1] == entry and len(units) == len(set(units))
                               and RAW_FN_VALUES in units, "incomplete RawFn source closure: " + entry)
    names = sorted({name for units in closures.values() for name in units})
    direct_process.require(all((ROOT / name).resolve().is_relative_to(ROOT) for name in names),
                           "RawFn source escapes the repository")
    return {"closures": closures, "sources": {name: captured[name].sha256 for name in names}}


def native_raw_fn_image(path, case):
    symbols = {"kernel32.dll": ("GetModuleHandleA", "GetProcAddress", "VirtualAlloc", "VirtualFree",
                               "HeapCreate", "HeapAlloc", "HeapFree", "HeapDestroy", "ExitProcess",
                               *({"deferred": ("TlsAlloc", "TlsSetValue", "TlsGetValue", "TlsFree"), "stdio": ("GetStdHandle", "WriteFile")}[case]))}
    return direct_process.inspect_image(path, RAW_FN_IMPORTS, symbols)


def native_raw_fn_lineage(work, before, built):
    diagnostic = "RawFn source/build receipt changed"
    inputs_sha256 = lineage_receipt_sha256(work / "inputs-before.json", before, diagnostic)
    build_sha256 = lineage_receipt_sha256(work / "build.json", built, diagnostic)
    direct_process.require(all(name in before["inputs"]["sources"] for name in
                           (ENTRY, "runtime/n1_host_main.c", "scripts/frontend_host_suite.py", "scripts/ourosmith/limits.py")),
                           "RawFn producer source closure omits its owner")
    return {"producer": str(executable(work, "n1-host")), "producer_backend": "generated-c-host",
            "producer_sha256": built["binaries"]["n1-host"]["sha256"],
            "generated_sha256": built["generated_sha256"], "seed_sha256": before["inputs"]["compiler_sha256"],
            "sources": before["inputs"]["sources"], "runtime_inputs": before["native_raw_fn"],
            "inputs_report_sha256": inputs_sha256, "build_report_sha256": build_sha256}


def verify_native_raw_fn_emission(result, output, units):
    direct_process.require(result.get("status") == "ok" and type(result.get("returncode")) is int
                           and result["returncode"] == 0 and result.get("stdout") == output + "\n",
                           "RawFn producer failed or published a different path")
    text = result.get("stderr")
    direct_process.require(isinstance(text, str) and " failed " not in text and "managed miss" not in text,
                           "RawFn producer skipped the managed path")
    patterns = (rf"n1-host: check units={units} live=[0-9]+", r"n1-host: CHECK_OK live=[0-9]+ total=[0-9]+",
                r"n1-host: recheck live=[0-9]+", r"n1-host: RECHECK_OK live=[0-9]+",
                r"n1-host: TYPES_OK live=[0-9]+", r"n1-host: BUILD_OK live=[0-9]+",
                r"n1-host: mir functions=[1-9][0-9]* live=[0-9]+", r"n1-host: mir-check live=[0-9]+",
                r"n1-host: gc-infer live=[0-9]+", r"n1-host: annotate live=[0-9]+",
                r"n1-host: codegen live=[0-9]+", r"n1-host: LOWER_OK live=[0-9]+",
                "n1-host: WROTE " + re.escape(output) + r" live=[0-9]+")
    previous = -1
    for pattern in patterns:
        matches = list(re.finditer("^" + pattern + "$", text, re.MULTILINE))
        direct_process.require(len(matches) == 1 and matches[0].start() > previous,
                               "RawFn check/recheck/managed/MIR/GC/publish phases differ")
        previous = matches[0].start()


def bytes_run_record(result):
    direct_process.require(isinstance(result.stdout, bytes) and isinstance(result.stderr, bytes),
                           "RawFn execution requires original byte streams")
    row = asdict(result)
    row["stdout_hex"] = row.pop("stdout").hex()
    row["stderr_hex"] = row.pop("stderr").hex()
    row["capture"] = "bytes"
    return row


def verify_native_raw_fn_result(result, case):
    stdout = {name: text.encode("utf-8").hex() for name, _entry, text in RAW_FN_CASES}[case]
    direct_process.require(isinstance(result, dict) and result.get("status") == "ok"
                           and type(result.get("returncode")) is int and result["returncode"] == 42
                           and result.get("capture") == "bytes"
                           and result.get("stdout_hex") == stdout and result.get("stderr_hex") == "",
                           "RawFn child execution differs: " + case)


def native_raw_fn_streams(work, case, result):
    streams = {}
    for stream in ("stdout", "stderr"):
        path = work / ("raw-fn-" + case + "-pe" + (".out" if stream == "stdout" else ".err"))
        data = path.read_bytes()
        direct_process.require(data.hex() == result.get(stream + "_hex"), "RawFn stream changed: " + str(path))
        streams[stream] = {"path": path.name, "bytes": len(data), "sha256": sha256_file(path)}
    return streams


def verify_native_raw_fn_report(report, lineage, work):
    direct_process.require(report.get("kind") == KIND + ".native-raw-fn" and report.get("status") == "pass"
                           and report.get("execution_backend") == "direct-windows-pe"
                           and report.get("native_bootstrap") is False and report.get("native_executed") is True
                           and report.get("images_unchanged") is True and report.get("lineage") == lineage,
                           "RawFn receipt is incomplete or stale")
    cases = report.get("cases")
    direct_process.require(isinstance(cases, dict) and set(cases) == {case for case, _entry, _text in RAW_FN_CASES}
                           and report.get("case_order") == [case for case, _entry, _text in RAW_FN_CASES],
                           "RawFn cases are missing, reordered, or unexpected")
    for case, entry, _stdout in RAW_FN_CASES:
        row = cases[case]
        direct_process.require(isinstance(row, dict), "RawFn row is malformed")
        output = work / "native-raw-fn" / (case + ".exe")
        logical = output.relative_to(ROOT).as_posix()
        emission, result, image = row.get("emission", {}), row.get("result", {}), row.get("image", {})
        units = lineage["runtime_inputs"]["closures"][entry]
        direct_process.require(isinstance(emission, dict) and isinstance(result, dict) and isinstance(image, dict),
                               "RawFn execution row is malformed")
        verify_native_raw_fn_result(result, case)
        direct_process.require(row.get("streams") == native_raw_fn_streams(work, case, result),
                               "RawFn stream receipt differs: " + case)
        direct_process.require(row.get("entry") == entry and row.get("cwd") == str(ROOT)
                               and emission.get("argv") == [lineage["producer"], entry, logical, *units]
                               and result.get("argv") == [str(output)]
                               and image == native_raw_fn_image(output, case), "RawFn runtime/PE protocol differs: " + case)
        verify_native_raw_fn_emission(emission, logical, len(units))


def verify_native_raw_fn_artifacts(work, report):
    lineage = report["lineage"]
    before = json.loads((work / "inputs-before.json").read_text(encoding="utf-8"))
    built = json.loads((work / "build.json").read_text(encoding="utf-8"))
    direct_process.require(lineage == native_raw_fn_lineage(work, before, built), "RawFn provenance differs")
    for path, expected in ((work / "inputs-before.json", lineage["inputs_report_sha256"]),
                           (work / "build.json", lineage["build_report_sha256"]),
                           (work / "backend.gen.c", lineage["generated_sha256"]),
                           (executable(work, "n1-host"), lineage["producer_sha256"])):
        direct_process.require(sha256_file(path) == expected, "RawFn lineage artifact changed: " + str(path))
    direct_process.require(raw_fn_source_snapshot() == lineage["runtime_inputs"], "RawFn source changed")
    verify_native_raw_fn_report(report, lineage, work)


def run_native_raw_fn(work, run, build_timeout, probe_timeout, verify_inputs, before, built):
    if os.name != "nt":
        return {"kind": KIND + ".native-raw-fn", "status": "unavailable", "native_bootstrap": False,
                "native_executed": False, "cases": {}, "reason": "direct PE execution requires Windows"}
    directory = work / "native-raw-fn"
    directory.mkdir()
    lineage = native_raw_fn_lineage(work, before, built)
    report = {"kind": KIND + ".native-raw-fn", "status": "running", "execution_backend": "direct-windows-pe",
              "native_bootstrap": False, "native_executed": False, "cases": {}, "case_order": [], "lineage": lineage}

    def unchanged():
        verify_inputs()
        direct_process.require(raw_fn_source_snapshot() == lineage["runtime_inputs"]
                               and sha256_file(executable(work, "n1-host")) == lineage["producer_sha256"],
                               "RawFn sources or producer changed")
        for case, row in report["cases"].items():
            direct_process.require(native_raw_fn_image(directory / (case + ".exe"), case) == row["image"],
                                   "RawFn image changed: " + case)
            direct_process.require(native_raw_fn_streams(work, case, row["result"]) == row["streams"],
                                   "RawFn captured streams changed: " + case)

    try:
        for case, entry, _stdout in RAW_FN_CASES:
            unchanged()
            output = directory / (case + ".exe")
            logical = output.relative_to(ROOT).as_posix()
            units = lineage["runtime_inputs"]["closures"][entry]
            emitted = run("raw-fn-" + case + "-emit", [lineage["producer"], entry, logical, *units], build_timeout)
            verify_native_raw_fn_emission(asdict(emitted), logical, len(units))
            image = native_raw_fn_image(output, case)
            unchanged()
            direct_process.require(native_raw_fn_image(output, case) == image, "RawFn image changed before execution")
            result = run("raw-fn-" + case + "-pe", [str(output)], probe_timeout, capture_bytes=True)
            result_record = bytes_run_record(result)
            verify_native_raw_fn_result(result_record, case)
            report["cases"][case] = {"entry": entry, "cwd": str(ROOT), "image": image,
                                      "emission": asdict(emitted), "result": result_record,
                                      "streams": native_raw_fn_streams(work, case, result_record)}
            report["case_order"].append(case)
            unchanged()
        report.update(status="pass", native_executed=True, images_unchanged=True)
        verify_native_raw_fn_artifacts(work, report)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        write_json_atomic(directory / "report.json", report)
    return report


def run_native_live(work, run, build_timeout, probe_timeout, verify_inputs, before, built):
    if os.name != "nt":
        return {"kind": KIND + ".native-live", "status": "unavailable", "cases": {},
                "native_bootstrap": False, "native_executed": False,
                "reason": "direct PE execution requires Windows"}
    report = {"kind": KIND + ".native-live", "status": "running", "cases": {}, "case_order": [],
              "execution_backend": "direct-windows-pe", "external_supervisor": "python",
              "fixture_level": "typed-mir", "native_bootstrap": False,
              "native_executed": False, "images_unchanged": False}
    try:
        verify_inputs()
        lineage = native_live_lineage(work, before, built)
        report["lineage"] = lineage

        def unchanged():
            verify_inputs()
            verify_native_live_artifacts(work, report)

        for mode in NATIVE_LIVE_CASES:
            unchanged()
            output = work / (mode + ".exe")
            direct_process.require(not output.exists(), "native liveness output already exists: " + mode)
            emission = run(mode + "-emit", [lineage["producer"], mode, str(output)], build_timeout)
            verify_probe(emission, ("frontend-codegen-selftest", [mode], 0,
                                    f"FRONTEND_CODEGEN_SELFTEST: passed {mode}\n", ""))
            image = native_live_image(output, mode)
            row = {"path": str(output), "sha256": image["sha256"], "image": image,
                   "cwd": str(ROOT), "emission": asdict(emission)}
            report["cases"][mode] = row
            report["case_order"].append(mode)
            unchanged()
            result = run(mode + "-pe", [str(output)], probe_timeout)
            row["runtime"] = asdict(result)
            verify_native_live_result(row["runtime"], mode)
            row["exit"] = result.returncode
            unchanged()
        report.update(status="pass", native_executed=True, images_unchanged=True)
        verify_native_live_report(report, lineage)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        write_json_atomic(work / "native-live.json", report)
    return report


def file_status_fault_snapshot(*, parse_bytes: ImportBytesParser | None = None,
                               read_source: SourceBytesReader | None = None):
    closures, captured = capture_unit_inputs((FILE_STATUS_FAULT_ENTRY,), parse_bytes=parse_bytes,
                                              read_source=read_source)
    units = closures[FILE_STATUS_FAULT_ENTRY]
    direct_process.require(units and units[-1] == FILE_STATUS_FAULT_ENTRY and len(units) == len(set(units))
                           and all((ROOT / name).resolve().is_relative_to(ROOT) for name in units),
                           "file status fault source closure is incomplete or escapes the repository")
    return {"entry": FILE_STATUS_FAULT_ENTRY, "units": units,
            "sources": {name: captured[name].sha256 for name in units}}


def file_status_fault_rejections(output):
    return [("leading-zero", ["file-read-status", "00", str(output)]),
            ("unknown", ["file-read-status", "7", str(output)]),
            ("upper-bound", ["file-read-status", "19", str(output)]),
            ("empty", ["file-read-status", "", str(output)]),
            ("signed", ["file-read-status", "+8", str(output)]),
            ("space", ["file-read-status", " 8", str(output)]),
            ("trailing", ["file-read-status", "8x", str(output)]),
            ("missing-mode", ["file-read-status", str(output)]),
            ("missing-output", ["file-read-status", "0"]),
            ("extra", ["file-read-status", "0", str(output), "extra"])]


def verify_file_status_fault_result(result, mode):
    expected = next((code for candidate, _status, code in FILE_STATUS_FAULT_CASES if candidate == mode), None)
    direct_process.require(type(mode) is int and expected is not None and result.get("status") == "ok"
                           and type(result.get("returncode")) is int and result["returncode"] == expected
                           and result.get("stdout") == "" and result.get("stderr") == "",
                           f"file status fault {mode}: result/body/owner counter assertions failed")


def verify_file_status_fault_emission(result, mode, output):
    if (result.status != "ok" or type(result.returncode) is not int or result.returncode != 0
            or result.stdout != f"FRONTEND_CODEGEN_SELFTEST: passed file-read-status {mode}\n"
            or result.stderr != ""):
        direct_process.require(not output.exists(), "failed file status emission published an image")
        raise ValueError("file status fault emission failed: " + str(mode))


def verify_file_status_fault_report(report, lineage):
    direct_process.require(report.get("kind") == KIND + ".file-status-fault" and report.get("status") == "pass"
                           and report.get("execution_backend") == "direct-windows-pe"
                           and report.get("external_supervisor") == "python"
                           and report.get("fixture_level") == "checked-source-with-typed-mir-faults"
                           and report.get("native_bootstrap") is False and report.get("native_executed") is True
                           and report.get("images_unchanged") is True and report.get("lineage") == lineage,
                           "file status fault receipt is incomplete or stale")
    directory = Path(lineage["producer"]).parent / "native-file-status-fault"
    rejections = report.get("rejections", [])
    planned = file_status_fault_rejections(directory / "reject.exe")
    direct_process.require(isinstance(rejections, list) and len(rejections) == len(planned),
                           "file status fault argument rejection inventory differs")
    for row, (name, arguments) in zip(rejections, planned, strict=True):
        direct_process.require(isinstance(row, dict) and isinstance(row.get("result"), dict),
                               "file status fault rejection row is malformed")
        result = row.get("result", {})
        direct_process.require(row.get("name") == name and row.get("output_absent") is True
                               and result.get("status") == "ok" and type(result.get("returncode")) is int
                               and result["returncode"] == 2 and result.get("stdout") == ""
                               and result.get("stderr") == "" and result.get("argv") == [lineage["producer"], *arguments],
                               "file status fault argument rejection protocol differs")
    cases = report.get("cases", [])
    direct_process.require(isinstance(cases, list) and len(cases) == len(FILE_STATUS_FAULT_CASES),
                           "file status fault case inventory differs")
    for row, (mode, status, code) in zip(cases, FILE_STATUS_FAULT_CASES, strict=True):
        direct_process.require(isinstance(row, dict)
                               and all(isinstance(row.get(section), dict) for section in ("image", "emission", "runtime")),
                               "file status fault case row is malformed")
        output = directory / (f"mode-{mode}.exe")
        cwd = directory / f"mode-{mode}"
        image, emission, result = row.get("image", {}), row.get("emission", {}), row.get("runtime", {})
        verify_file_status_fault_result(result, mode)
        symbols = image.get("import_symbols", {})
        direct_process.require(type(row.get("mode")) is int and row["mode"] == mode
                               and row.get("status_argument") == status and type(row.get("exit")) is int and row["exit"] == code
                               and row.get("path") == str(output) and row.get("cwd") == str(cwd)
                               and row.get("input_path") == str(cwd / "files/fault-read.bin")
                               and row.get("input_bytes") == list(FILE_STATUS_FAULT_BYTES)
                               and re.fullmatch(r"[0-9a-f]{64}", str(row.get("input_sha256"))) is not None
                               and row.get("counter_verification") == "file_fault_exit_checks_expected"
                               and image.get("machine") == "x86_64" and image.get("imports") == list(FILE_STATUS_FAULT_IMPORTS)
                               and type(image.get("bytes")) is int and 64 <= image["bytes"] <= 256 * 1024 * 1024
                               and re.fullmatch(r"[0-9a-f]{64}", str(image.get("sha256"))) is not None
                               and isinstance(symbols, dict)
                               and all(set(names).issubset(symbols.get(library, []))
                                       for library, names in FILE_STATUS_FAULT_SYMBOLS.items())
                               and emission.get("status") == "ok" and type(emission.get("returncode")) is int
                               and emission["returncode"] == 0 and emission.get("stderr") == ""
                               and emission.get("stdout") == f"FRONTEND_CODEGEN_SELFTEST: passed file-read-status {mode}\n"
                               and emission.get("argv") == [lineage["producer"], "file-read-status", str(mode), str(output)]
                               and result.get("argv") == [str(output), status],
                               "file status fault source/image/input protocol differs: " + str(mode))


def verify_file_status_fault_artifacts(work, report):
    verify_native_fixture_artifacts(work, report["lineage"])
    directory = work / "native-file-status-fault"
    direct_process.require(not (directory / "reject.exe").exists(), "rejected file status mode published an image")
    for row in report["cases"]:
        path = Path(row["input_path"])
        direct_process.require(path.stat().st_size == len(FILE_STATUS_FAULT_BYTES)
                               and path.read_bytes() == FILE_STATUS_FAULT_BYTES and sha256_file(path) == row["input_sha256"],
                               "file status fault input bytes changed")
        direct_process.require(direct_process.inspect_image(Path(row["path"]), FILE_STATUS_FAULT_IMPORTS,
                               FILE_STATUS_FAULT_SYMBOLS) == row["image"], "file status fault PE changed")


def run_file_status_faults(work, run, build_timeout, probe_timeout, verify_inputs, before, built):
    if os.name != "nt":
        return {"kind": KIND + ".file-status-fault", "status": "unavailable", "cases": [], "rejections": [],
                "native_bootstrap": False, "native_executed": False, "reason": "direct PE execution requires Windows"}
    directory = work / "native-file-status-fault"
    directory.mkdir()
    report = {"kind": KIND + ".file-status-fault", "status": "running", "cases": [], "rejections": [],
              "execution_backend": "direct-windows-pe", "external_supervisor": "python",
              "fixture_level": "checked-source-with-typed-mir-faults", "native_bootstrap": False,
              "native_executed": False, "images_unchanged": False}
    try:
        verify_inputs()
        sources = before["inputs"]["sources"]
        direct_process.require(all(name in sources for name in ("tests/native_file_fixtures.ouro",
                               "tests/native_file_fault_calls.ouro", "tests/native_file_fault_values.ouro",
                               "tests/native_startup_fault_values.ouro")), "file status fault producer omits an owner")
        inputs = before["native_file_status_fault"]
        direct_process.require(inputs["entry"] == FILE_STATUS_FAULT_ENTRY
                               and inputs == file_status_fault_snapshot(), "file status fault source closure changed")
        lineage = {**native_live_lineage(work, before, built), "fault_inputs": inputs}
        report["lineage"] = lineage

        def unchanged():
            verify_inputs()
            verify_file_status_fault_artifacts(work, report)

        rejected = directory / "reject.exe"
        for name, arguments in file_status_fault_rejections(rejected):
            unchanged()
            result = run("file-status-reject-" + name, [lineage["producer"], *arguments], probe_timeout)
            direct_process.require(result.status == "ok" and type(result.returncode) is int and result.returncode == 2
                                   and result.stdout == "" and result.stderr == "" and not rejected.exists(),
                                   "invalid file status mode/argc was accepted or published an image: " + name)
            report["rejections"].append({"name": name, "output_absent": True, "result": asdict(result)})
            unchanged()
        for mode, status, _code in FILE_STATUS_FAULT_CASES:
            unchanged()
            cwd = directory / f"mode-{mode}"
            (cwd / "files").mkdir(parents=True)
            input_path = cwd / "files/fault-read.bin"
            input_path.write_bytes(FILE_STATUS_FAULT_BYTES)
            digest = sha256_file(input_path)
            output = directory / (f"mode-{mode}.exe")
            direct_process.require(not output.exists(), "file status fault output already exists")
            emission = run(f"file-status-{mode}-emit", [lineage["producer"], "file-read-status", str(mode), str(output)], build_timeout)
            verify_file_status_fault_emission(emission, mode, output)
            image = direct_process.inspect_image(output, FILE_STATUS_FAULT_IMPORTS, FILE_STATUS_FAULT_SYMBOLS)
            row = {"mode": mode, "status_argument": status, "path": str(output), "image": image,
                   "cwd": str(cwd), "input_path": str(input_path), "input_sha256": digest,
                   "input_bytes": list(FILE_STATUS_FAULT_BYTES), "counter_verification": "file_fault_exit_checks_expected",
                   "emission": asdict(emission)}
            report["cases"].append(row)
            unchanged()
            result = run(f"file-status-{mode}-pe", [str(output), status], probe_timeout, cwd=cwd)
            row["runtime"] = asdict(result)
            verify_file_status_fault_result(row["runtime"], mode)
            row["exit"] = result.returncode
            unchanged()
        report.update(status="pass", native_executed=True, images_unchanged=True)
        verify_file_status_fault_report(report, lineage)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        write_json_atomic(directory / "report.json", report)
    return report


def run_suite(args, cfg, argv: list[str]) -> int:
    build_workers = min(2, build.jobs_value(cfg)) if sys.platform == "linux" else 1
    args.out.mkdir(parents=True, exist_ok=True)
    work = args.out / ("host-" + uuid.uuid4().hex)
    work.mkdir()
    report = {"kind": KIND, "pass": False, "execution_backend": "generated-c-host",
              "native_bootstrap": False, "entry": ENTRY, "work": str(work), "steps": [],
              "workers": 1, "build_workers": build_workers,
              "memory_mib": args.memory_mib, "build_timeout_s": args.build_timeout,
              "backend_group_size": BACKEND_GROUP_SIZE,
              "probe_timeout_s": args.probe_timeout,
              "producer": {"path": str(args.compiler), "selection": "caller-supplied --compiler; lineage not attested"}}
    before = None
    built = None
    parse_bytes = cached_import_parser()
    try:
        if build_workers == 1:
            report["cpu"] = pin_one_cpu()
        before = snapshot(args, cfg, parse_bytes=parse_bytes)
        report["producer"]["sha256"] = before["inputs"]["compiler_sha256"]
        write_json_atomic(work / "inputs-before.json", before)
        env = dict(os.environ, OURO_JOBS="1", OURO_FRONTEND_JOBS="1", OURO_CACHE="0",
                   OURO_CCACHE="disabled", OURO_MEM_TRACE="0", PYTHONDONTWRITEBYTECODE="1")
        temporary = work / "tmp"
        temporary.mkdir()
        env.update(TEMP=str(temporary), TMP=str(temporary), TMPDIR=str(temporary))

        def run(label: str, command: list[str], timeout: float, *, cwd: Path = ROOT, capture_bytes: bool = False,
                environment_overrides: dict[str, str | None] | None = None):
            print("FRONTEND_HOST_SUITE:", label, flush=True)
            runner = run_limited_bytes if capture_bytes else run_limited
            selected_env = env
            if environment_overrides is not None:
                if not all(isinstance(key, str) and key and (value is None or isinstance(value, str))
                           for key, value in environment_overrides.items()):
                    raise ValueError("child environment overrides require names and string or absent values")
                keys = [key.upper() for key in environment_overrides]
                if len(keys) != len(set(keys)):
                    raise ValueError("child environment override names overlap")
                selected_env = {key: value for key, value in env.items() if key.upper() not in keys}
                selected_env.update({key: value for key, value in environment_overrides.items() if value is not None})
            result = runner(command, cwd=cwd, env=selected_env, timeout_s=timeout, memory_mb=args.memory_mib)
            row = {"label": label, "cwd": str(cwd), **(bytes_run_record(result) if capture_bytes else asdict(result))}
            if environment_overrides is not None:
                row["environment_overrides"] = dict(environment_overrides)
                row["environment_policy"] = {key: selected_env.get(key) for key in environment_overrides}
            for stream in ("stdout", "stderr"):
                path = work / (label + (".out" if stream == "stdout" else ".err"))
                if capture_bytes:
                    path.write_bytes(getattr(result, stream))
                else:
                    path.write_text(getattr(result, stream), encoding="utf-8", newline="\n")
                row[stream] = path.name
                row[stream + "_sha256"] = sha256_file(path)
            report["steps"].append(row)
            return result

        command = [sys.executable, "-B", str(Path(__file__).resolve()), *argv,
                   "--worker", "--compiler", str(args.compiler), "--out", str(work),
                   "--jobs", str(build_workers), "--no-cache", "--ccache", "disabled",
                   "--opt-level", str(cfg.values["opt_level"])]
        if args.config is not None:
            command.extend(["--config", str(args.config.resolve())])
        result = run("build", command, args.build_timeout)
        if not result.ok or not result.stdout.endswith("FRONTEND_HOST_BUILD: PASS\n"):
            raise ValueError(f"host build failed (status={result.status}, exit={result.returncode}); see {work / 'build.err'}")
        if build_workers > 1:
            report["cpu"] = pin_one_cpu()
        built = json.loads((work / "build.json").read_text(encoding="utf-8"))
        verify_artifacts(work, built)
        report["build"] = built
        report["build_report_sha256"] = sha256_file(work / "build.json")
        for case in probe_cases():
            require_snapshot(args, cfg, before, parse_bytes=parse_bytes)
            verify_artifacts(work, built)
            name, arguments, _code, _stdout, _stderr = case
            result = run(arguments[0], [str(executable(work, name)), *arguments], args.probe_timeout)
            verify_probe(result, case)
        def verify_native_inputs():
            require_snapshot(args, cfg, before, parse_bytes=parse_bytes)
            verify_artifacts(work, built)

        report["native_live"] = run_native_live(work, run, args.build_timeout,
                                               args.probe_timeout, verify_native_inputs, before, built)
        report["native_raw_fn"] = run_native_raw_fn(work, run, args.build_timeout,
            args.probe_timeout, verify_native_inputs, before, built)
        report["native_heap_observer"] = run_heap_observer(work, run, args.build_timeout,
            args.probe_timeout, verify_native_inputs, before, built)
        report["native_file_status_fault"] = run_file_status_faults(work, run, args.build_timeout,
            args.probe_timeout, verify_native_inputs, before, built)
        report["native_process"] = direct_process.run_section(executable(work, "n1-host"), work, run,
            args.build_timeout, args.probe_timeout, verify_native_inputs, parse_bytes=parse_bytes)
        report["native_fs_create"] = direct_fs_create.run_section(executable(work, "n1-host"), work, run,
            args.build_timeout, args.probe_timeout, verify_native_inputs, parse_bytes=parse_bytes)
        report["native_async"] = direct_async.run_section(executable(work, "n1-host"), work, run,
            args.build_timeout, args.probe_timeout, verify_native_inputs, parse_bytes=parse_bytes)
        report["native_fs_replace"] = direct_fs_replace.run_native_section(executable(work, "n1-host"), work, run,
            args.build_timeout, verify_native_inputs, parse_bytes=parse_bytes)
        report["native_fs_read"] = direct_fs_read.run_native_section(executable(work, "n1-host"), work, run,
            args.build_timeout, verify_native_inputs, parse_bytes=parse_bytes)
        report["pass"] = True
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, SystemExit) as error:
        report["error"] = str(error)
    finally:
        if before is not None:
            try:
                after = snapshot(args, cfg, parse_bytes=parse_bytes)
                write_json_atomic(work / "inputs-after.json", after)
                report["inputs_unchanged"] = after == before
                report["producer"]["sha256_after"] = after["inputs"]["compiler_sha256"]
                if after != before:
                    raise ValueError("source, producer or C build inputs changed")
                if built is not None:
                    verify_artifacts(work, built)
                    report["generated_sha256_after"] = sha256_file(work / "backend.gen.c")
                    if report.get("native_live", {}).get("status") == "pass":
                        verify_native_live_artifacts(work, report["native_live"])
                    if report.get("native_raw_fn", {}).get("status") == "pass":
                        verify_native_raw_fn_artifacts(work, report["native_raw_fn"])
                    if report.get("native_heap_observer", {}).get("status") == "pass":
                        verify_heap_observer_artifacts(work, report["native_heap_observer"])
                    if report.get("native_file_status_fault", {}).get("status") == "pass":
                        verify_file_status_fault_artifacts(work, report["native_file_status_fault"])
                    if report.get("native_process", {}).get("status") == "passed":
                        direct_process.verify_toolchain_report(report["native_process"]["toolchain"], work,
                                                               parse_bytes=parse_bytes)
                        direct_process.verify_release_report(report["native_process"]["release_stage"], work, report["steps"],
                                                             parse_bytes=parse_bytes)
                        direct_process.verify_release_stream_report(report["native_process"]["release_stream"], work,
                                                                    report["steps"], parse_bytes=parse_bytes)
                    if report.get("native_fs_read", {}).get("status") == "passed":
                        bounded = report["native_fs_read"].get("bounded", {})
                        if bounded.get("status") != "passed":
                            raise ValueError("required bounded read section did not complete")
                        direct_fs_read.verify_native_bounded_artifacts(bounded)
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
        read_status = report["native_fs_read"]["status"]
        live_status = report["native_live"]["status"]
        raw_fn_status = report["native_raw_fn"]["status"]
        heap_observer_status = report["native_heap_observer"]["status"]
        print(f"FRONTEND_HOST_SUITE: PASS cases={len(probe_cases())} native_process={native_status} "
              f"native_fs_create={fs_status} native_async={async_status} native_fs_replace={replace_status} native_fs_read={read_status} "
              f"native_live={live_status} native_raw_fn={raw_fn_status} native_heap_observer={heap_observer_status} out={work}", flush=True)
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
    args.jobs = args.jobs or "1"
    args.cache_enabled, args.ccache = False, "disabled"
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
