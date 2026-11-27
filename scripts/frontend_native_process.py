#!/usr/bin/env python3
"""Direct-PE process acceptance owned by frontend_host_suite, with Python supervision.

The native fixture owns API assertions. This observer preserves raw output bytes
and holds descendant process handles before cancellation. It never supplies a C
law receipt as evidence of a Windows image, and never builds a second producer.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import struct
import subprocess
import sys
import time

from frontend_regen import ImportBytesParser, SourceBytesReader, capture_unit_inputs
from repo_support import sha256_file, write_json_atomic
from selfhost_module_cache import cached_import_parser

ROOT = Path(__file__).resolve().parents[1]
KIND = "ouro.frontend-native-process.v1"
API = "tests/process_capture_bounded_tests.ouro"
API_CASES = (
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
CAPTURE = "tests/native_managed/process_bounded.ouro"
DENIED = "tests/native_process/child_denied_job_commit.ouro"
# Missing names trigger the existing scalar fallback, which rejects Runtime
# Unit as an entry. Body and metadata failures must not enter that fallback.
REJECTIONS = (
    ("missing_run", r"entry:[1-9][0-9]*", True),
    ("axiom_run", r"body:[1-9][0-9]*", False),
    ("close_pointee", r"metadata:[1-9][0-9]*", False),
    ("missing_input", r"entry:[1-9][0-9]*", True),
    ("input_pointee", r"metadata:[1-9][0-9]*", False),
    ("at_missing_run", r"entry:[1-9][0-9]*", True),
    ("at_axiom_run", r"body:[1-9][0-9]*", False),
    ("at_run_pointee", r"metadata:[1-9][0-9]*", False),
)
MODES = ("basic", "stdin", "reuse", "deferred", "timeout", "stdout-cap", "stderr-cap",
         "negative73", "missing", "invalid", "oversized",
         "cwd", "cwd-reuse", "cwd-deferred", "cwd-invalid", "cwd-missing", "cwd-timeout",
         "cwd-stdout-cap", "cwd-stderr-cap", "cwd-oversized",
         "tree-timeout", "hard-terminate", "cwd-tree-timeout", "cwd-hard-terminate")
IMPORTS = {API: ("advapi32.dll", "bcrypt.dll", "kernel32.dll", "shell32.dll"),
           CAPTURE: ("advapi32.dll", "bcrypt.dll", "kernel32.dll", "shell32.dll"),
           DENIED: ("kernel32.dll",)}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def rejection_entry(name):
    return f"tests/native_managed/reject/source_process_bounded_{name}.ouro"


def source_snapshot(*, parse_bytes: ImportBytesParser | None = None, read_source: SourceBytesReader | None = None):
    entries = (API, CAPTURE, DENIED, *CLI_ENTRIES, *TOOLCHAIN_ENTRIES, *RELEASE_ENTRIES, RELEASE_STREAM_ENTRY,
               *(rejection_entry(name) for name, _, _ in REJECTIONS))
    closures, captured = capture_unit_inputs(entries, parse_bytes=parse_bytes, read_source=read_source)
    for entry, units in closures.items():
        require(units and units[-1] == entry and len(units) == len(set(units)),
                f"incomplete native process source closure: {entry}")
    names = sorted({name for units in closures.values() for name in units})
    require(all((ROOT / name).resolve().is_relative_to(ROOT) for name in names),
            "native process source escapes the repository")
    return {"closures": closures, "sources": {name: captured[name].sha256 for name in names}}


def verify_rejection(result, diagnostic, output, scalar_fallback=False):
    pattern = (r"n1-host: check units=[1-9][0-9]* live=[0-9]+\n"
               r"n1-host: CHECK_OK live=[0-9]+ total=[0-9]+\n"
               r"n1-host: recheck live=[0-9]+\n"
               r"n1-host: RECHECK_OK live=[0-9]+\n"
               r"n1-host: TYPES_OK live=[0-9]+\n"
               r"n1-host: lower live=[0-9]+\n"
               + (r"n1-host: managed miss tag=7; scalar lower\n" if scalar_fallback else "") +
               r"n1-host: lower failed tag=0 n=1 live=[0-9]+\n"
               "n1-host: lower:" + diagnostic + r"\n")
    require(result.status == "ok" and result.returncode == 1 and result.stdout == ""
            and re.fullmatch(pattern, result.stderr) is not None and not output.exists(),
            f"helper rejection has wrong phase, diagnostic, process status, or output: {output.stem}")
    return result.stderr.splitlines()[-1].removeprefix("n1-host: ")


def verify_lowering_timings(result):
    phases = ("native-prepare-start", "native-prepare-return", "native-prepare-end")
    lines = [line for line in result.stderr.splitlines(keepends=True)
             if line.startswith("n1-host: lowering-phase=native-prepare-")]
    require(result.status == "ok" and type(result.returncode) is int and result.returncode == 0
            and len(lines) == len(phases)
            and all(re.fullmatch("n1-host: lowering-phase=" + phase + r" live=[0-9]+ total=[0-9]+\n", line)
                    for phase, line in zip(phases, lines, strict=True)),
            "timed native process emission lacks complete ordered prepare telemetry")


def verify_api_result(result):
    expected = "".join(f"ok {name}\n" for name in API_CASES)
    require(result.status == "ok" and result.returncode == 0
            and result.stdout == expected and result.stderr == "",
            "native process API laws have wrong status, count, order, output, or diagnostics")


CLI_ENTRIES = ("tools/coil.ouro", "tests/native_managed/cli_route_child.ouro", "tests/native_cli_args_tests.ouro")
CLI_NAMES = ("coil.exe", "cli-route-child.exe", "native_cli_args_tests.exe")
CLI_SIBLINGS = {"lsp": "ouro-lsp.exe", "pkg": "ouro-pkg.exe", "fmt": "ouro-fmt.exe", "test": "ouro-test.exe"}
CLI_OVERRIDES = {"lsp": ("OURO_TEST_CHECK", "OURO_PKG_CHECK", "OURO_HOSTED_COMPILER_WRAPPER", "OURO_HOSTED_FMT"),
                 "pkg": ("OURO_TEST_CHECK", "OURO_PKG_CHECK", "OURO_HOSTED_COMPILER_WRAPPER")}
CLI_WORDS = ("", "space name", "雪😀", 'quote"here', "trailing\\", 'many\\\\"quote',
             "--", "--out", "elsewhere.exe", "&|<>", "lsp", "pkg", "test", "fmt")
CLI_INPUT = bytes((65, 0, 255, 128, 10, 13, 90))
CLI_OUT, CLI_ERR = bytes((65, 0, 255, 13, 10)), bytes((69, 0, 255, 13, 10))
TOOLCHAIN_LAWS = (("tests/native_toolchain_model_tests.ouro", "native-toolchain", 60),
                  ("tests/native_toolchain_reader_tests.ouro", "native-toolchain-reader", 18),
                  ("tests/native_toolchain_io_tests.ouro", "native-toolchain-io", 19))
TOOLCHAIN_CHILD = "tests/native_managed/toolchain_protocol_child.ouro"
TOOLCHAIN_ENTRIES = (*(entry for entry, _label, _count in TOOLCHAIN_LAWS), TOOLCHAIN_CHILD)
TOOLCHAIN_ENV = {"OURO_TOOLCHAIN_PROTOCOL": "owned 雪"}
RELEASE_LAWS = (("tests/native_release_tests.ouro", "native-release-model", 71),
                ("tests/native_managed/release_stage.ouro", "native-release-stage", 12))
RELEASE_ENTRIES = tuple(entry for entry, _label, _count in RELEASE_LAWS)
RELEASE_ENV = {"PATH": "", "OURO_TEST_CHECK": None, "OURO_TEST_BUILD": None,
               "OURO_PKG_CHECK": None, "OURO_HOSTED_COMPILER_WRAPPER": None, "OURO_HOSTED_FMT": None}
RELEASE_BYTES = bytes((65, 0, 255, 13, 10, 66))
RELEASE_SYMBOLS = {"kernel32.dll": ("VirtualAlloc", "VirtualFree", "HeapCreate", "HeapAlloc",
                                  "HeapFree", "HeapDestroy", "ExitProcess", "WriteFile")}

RELEASE_MODEL_NAMES = (
    "native-release/exact-inventory-and-budget",
    "native-release/empty-file-zero-budget",
    "native-release/empty-inventory-refused",
    "native-release/missing-input-refused",
    "native-release/extra-input-refused",
    "native-release/reordered-input-refused",
    "native-release/unsorted-inventory-refused",
    "native-release/duplicate-refused",
    "native-release/ASCII-case-alias-refused",
    "native-release/file-directory-prefix-refused",
    "native-release/prefix-boundary-accepted",
    "native-release/Unicode-space-dotfile-path",
    "native-release/empty-path-refused",
    "native-release/dot-parent-refused",
    "native-release/dot-component-refused",
    "native-release/absolute-path-refused",
    "native-release/UNC-path-refused",
    "native-release/backslash-refused",
    "native-release/empty-component-refused",
    "native-release/trailing-slash-refused",
    "native-release/trailing-dot-space-refused",
    "native-release/device-name-refused",
    "native-release/ADS-and-wildcards-refused",
    "native-release/NUL-refused",
    "native-release/invalid-UTF8-refused",
    "native-release/overlong-UTF8-refused",
    "native-release/relative-source-refused",
    "native-release/NUL-source-refused",
    "native-release/short-digest-refused",
    "native-release/uppercase-digest-refused",
    "native-release/budget-plus-one-refused",
    "native-release/aggregate-budget-refused",
    "native-release/SHA-length-bound-refused",
    "native-release/SHA-length-bound-before-content",
    "native-release/SHA256-empty-vector",
    "native-release/SHA256-abc-vector",
    "native-release/SHA256-binary-vector",
    "native-release/length-mismatch-refused",
    "native-release/same-size-content-change-refused",
    "native-release/exact-output-inventory",
    "native-release/output-missing-refused",
    "native-release/output-extra-refused",
    "native-release/output-alias-collision-refused",
    "native-release/truncated-walk-refused",
    "native-release/unreadable-walk-refused",
    "native-release/unsafe-walk-refused",
    "native-release/created-root-claim-retained",
    "native-release/precreate-failure-has-no-claim",
    "native-release/stream-empty-zero-cap",
    "native-release/stream-exact-cap",
    "native-release/stream-cap-before-creation",
    "native-release/stream-source-error-before-stage-and-cap",
    "native-release/stream-stage-path-before-content-cap",
    "native-release/stream-relative-source-refused",
    "native-release/stream-nul-stage-refused",
    "native-release/stream-full-Nat-cap",
    "native-release/stream-high-size-error-not-truncated",
    "native-release/stream-actual-size-cap-before-declared-match",
    "native-release/stream-declared-size-refused-before-stage",
    "native-release/stream-positive-partial-read",
    "native-release/stream-positive-partial-write",
    "native-release/stream-early-zero-read-refused",
    "native-release/stream-zero-write-terminal-guard",
    "native-release/stream-oversized-progress-terminal-guard",
    "native-release/stream-no-zero-request-progress",
    "native-release/stream-final-stage-length",
    "native-release/stream-short-stage-refused",
    "native-release/stream-write-error-and-created-claim",
    "native-release/stream-precreate-error-without-claim",
    "native-release/stream-guard-separated-from-operational-error",
    "native-release/stream-closed-stage-describes-exact-bytes",
)
RELEASE_STREAM_ENTRY = "tests/native_managed/release_stream.ouro"
RELEASE_STREAM_SYMBOLS = {"kernel32.dll": (*RELEASE_SYMBOLS["kernel32.dll"], "CreateFileW", "ReadFile",
                                         "FlushFileBuffers", "GetFileSizeEx", "GetFileInformationByHandleEx",
                                         "CloseHandle")}
RELEASE_STREAM_BYTES = bytes((65, 0, 255, 128, 13, 10, 66))
RELEASE_STREAM_KEPT = bytes((75, 69, 80, 84, 0, 255))
RELEASE_STREAM_OLD = bytes((79, 76, 68, 0, 13, 10, 88))
RELEASE_STREAM_LABELS = {
    "copy": ("copy-closed",), "collision": ("existing-stage-refused",),
    "reuse": ("reused-first-copy", "reused-create-refused"), "cap": ("cap-before-stage",),
    "actual-cap": ("actual-cap-before-payload",), "length": ("source-length-before-stage",),
    "deferred": ("deferred-current-input", "deferred-binary-bytes"),
}
RELEASE_STREAM_USAGE = b"usage: native-release-stream MODE SOURCE STAGE DECLARED_BYTES BYTE_CAP\n"


def cli_cases():
    rows = []
    for tool in ("lsp", "pkg"):
        for word, code in (("0", 0), ("1", 1), ("259", 259), ("max", 0xFFFFFFFF)):
            rows.append(dict(case=tool + "-" + word, tool=tool, words=[word, *CLI_WORDS], exit=code, overrides={}))
        rows.append(dict(case=tool + "-empty", tool=tool, words=[], exit=42, overrides={}))
        rows.append(dict(case=tool + "-build-override", tool=tool, words=["0", *CLI_WORDS], exit=0,
                         overrides={"OURO_TEST_BUILD": "unused hosted build"}))
        for key in CLI_OVERRIDES[tool]:
            for label, value in (("empty", ""), ("nonempty", "unused hosted command")):
                rows.append(dict(case=tool + "-" + key + "-" + label, tool=tool, words=["0", *CLI_WORDS],
                                 exit=1, overrides={key: value}, refused=key))
        rows.append(dict(case=tool + "-priority", tool=tool, words=["0", *CLI_WORDS], exit=1,
                         overrides={key: "" for key in reversed(CLI_OVERRIDES[tool])}, refused=CLI_OVERRIDES[tool][0]))
        rows.append(dict(case=tool + "-missing", tool=tool, words=["0", *CLI_WORDS], exit=1, overrides={}, missing=True))
    rows.append(dict(case="pkg-formatter-override", tool="pkg", words=["0", *CLI_WORDS], exit=0,
                     overrides={"OURO_HOSTED_FMT": "unused hosted formatter"}))
    for tool in ("fmt", "test"):
        rows.append(dict(case=tool + "-retained", tool=tool, words=["0", *CLI_WORDS], exit=0, overrides={}))
    return rows


def cli_law_names():
    text = (ROOT / CLI_ENTRIES[2]).read_text(encoding="utf-8")
    names = re.findall(r'MkPair String Bool "(native-cli-args/[^"\n]+)"', text)
    require(len(names) == 127 and len(set(names)) == 127, "public CLI must retain all 127 ordered laws")
    return names


def cli_lineage(work, *, parse_bytes: ImportBytesParser | None = None):
    # Reuse the current host's producer/seed/generated/source binding. This is
    # a generated-C producer receipt, not native bootstrap evidence.
    from frontend_host_suite import native_raw_fn_lineage, verify_artifacts

    before = json.loads((work / "inputs-before.json").read_text(encoding="utf-8"))
    built = json.loads((work / "build.json").read_text(encoding="utf-8"))
    verify_artifacts(work, built)
    result = native_raw_fn_lineage(work, before, built)
    result["runtime_inputs"] = before["native_process"]
    compiler = Path(before["selected_compiler"]).resolve(strict=True)
    cc = Path(json.loads(before["inputs"]["cc"])["path"]).resolve(strict=True)
    for path, digest in ((compiler, before["inputs"]["compiler_sha256"]), (cc, before["inputs"]["cc_sha256"])):
        require(path.is_file() and not path.is_symlink() and sha256_file(path) == digest,
                "public CLI selected seed or C producer tool changed: " + str(path))
    result["seed_image"] = {"path": str(compiler), "sha256": before["inputs"]["compiler_sha256"]}
    result["cc_image"] = {"path": str(cc), "sha256": before["inputs"]["cc_sha256"]}
    require(result["runtime_inputs"] == source_snapshot(parse_bytes=parse_bytes), "public CLI source snapshot changed")
    require(result["producer_sha256"] == sha256_file(Path(result["producer"])), "public CLI producer changed")
    for name, digest in result["sources"].items():
        require(sha256_file(ROOT / name) == digest, "public CLI producer input changed: " + name)
    return result


def verify_cli_spec(spec, directory, *, parse_bytes: ImportBytesParser | None = None):
    from frontend_host_suite import verify_native_raw_fn_emission

    require(spec.get("kind") == KIND + ".cli-spec" and spec.get("directory") == str(directory)
            and spec.get("cases") == cli_cases() and spec.get("law_names") == cli_law_names(), "public CLI specification differs")
    require(all(type(case.get("exit")) is int for case in spec["cases"]), "public CLI specification status is not an integer")
    lineage = cli_lineage(directory.parent.parent, parse_bytes=parse_bytes)
    require(spec.get("lineage") == lineage, "public CLI producer lineage differs")
    images = spec.get("images", {})
    require(set(images) == set(CLI_ENTRIES), "public CLI image inventory differs")
    for entry, name in zip(CLI_ENTRIES, CLI_NAMES, strict=True):
        output = directory / "images" / name
        row = images[entry]
        logical = output.relative_to(ROOT).as_posix()
        units = lineage["runtime_inputs"]["closures"][entry]
        require(row.get("path") == logical and row.get("image") == inspect_image(output, IMPORTS[API])
                and row.get("emission", {}).get("argv") == [lineage["producer"], entry, logical, *units],
                "public CLI emission or image differs: " + entry)
        verify_native_raw_fn_emission(row["emission"], logical, len(units))
    return spec


def cli_read_bytes(path):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 16 * 1024 * 1024,
            "public CLI byte stream is absent, redirected, or oversized")
    with path.open("rb") as stream:
        data = stream.read(16 * 1024 * 1024 + 1)
    require(len(data) <= 16 * 1024 * 1024, "public CLI byte stream exceeds the observer cap")
    return data


def cli_capture_streams(row, work):
    for stream in ("stdout", "stderr"):
        path = work / (stream + ".bin")
        if path.is_symlink() or not path.is_file():
            receipt = {"state": "absent-or-redirected"}
        elif path.stat().st_size > 16 * 1024 * 1024:
            receipt = {"state": "oversized", "bytes": path.stat().st_size}
        else:
            data = cli_read_bytes(path)
            receipt = {"state": "captured", "hex": data.hex(), "bytes": len(data),
                       "sha256": hashlib.sha256(data).hexdigest()}
        for name, value in receipt.items():
            field = stream + "_" + name
            require(field not in row or row[field] == value, "public CLI observed stream changed: " + stream)
            row[field] = value


def cli_case_inputs(work, case, spec):
    child = ROOT / spec["images"][CLI_ENTRIES[1]]["path"]
    expected = {work / "input.bin": {"bytes": len(CLI_INPUT), "sha256": hashlib.sha256(CLI_INPUT).hexdigest()},
                work / "cwd-input.txt": {"bytes": len(b"owned cwd\n"), "sha256": hashlib.sha256(b"owned cwd\n").hexdigest()}}
    child_image = spec["images"][CLI_ENTRIES[1]]["image"]
    child_identity = {"bytes": child_image["bytes"], "sha256": child_image["sha256"]}
    for parent in (work, work / "loaded image 雪", work / "decoy", work / "decoy" / "path"):
        for tool, name in CLI_SIBLINGS.items():
            if parent == work / "loaded image 雪" and (tool != case["tool"] or case.get("missing")):
                continue
            expected[parent / name] = child_identity
    coil_image = spec["images"][CLI_ENTRIES[0]]["image"]
    coil_identity = {"bytes": coil_image["bytes"], "sha256": coil_image["sha256"]}
    for parent in (work, work / "loaded image 雪", work / "decoy"):
        expected[parent / "coil.exe"] = coil_identity
    require(child.is_file(), "public CLI transport child is absent")
    require(all(path.is_file() and not path.is_symlink() and path.stat().st_size == value["bytes"]
                and sha256_file(path) == value["sha256"]
                and path.resolve().is_relative_to(work.resolve()) for path, value in expected.items()),
            "public CLI owned input or alias changed")
    actual = {path for path in work.rglob("*.exe")}
    require(actual == {path for path in expected if path.suffix == ".exe"}, "public CLI alias inventory changed")
    return {str(path.relative_to(work)): value for path, value in expected.items()}


def verify_cli_row(row, case, work, spec):
    refused, missing = case.get("refused"), case.get("missing", False)
    target = work / "loaded image 雪" / CLI_SIBLINGS[case["tool"]]
    expected_error = (f"coil: native {case['tool']} refuses hosted override: {refused}\n".encode() if refused else
                      ("coil: process unavailable: " + str(target) + " OS error=2\n").encode() if missing else CLI_ERR)
    marker = work / "launched.txt"
    require(row.get("case") == case["case"] and row.get("status") == "ok" and type(row.get("exit")) is int
            and row["exit"] == case["exit"] and row.get("completion_signaled") is True
            and row.get("stdout_hex") == (b"" if refused or missing else CLI_OUT).hex()
            and row.get("stderr_hex") == expected_error.hex(), "public CLI DWORD/byte/refusal protocol differs: " + case["case"])
    require(row.get("cwd") == str(work) and row.get("application") == str(work / "loaded image 雪" / "coil.exe")
            and row.get("argv") == [str(work / "decoy" / "coil.exe"), case["tool"], *case["words"]]
            and row.get("overrides") == case["overrides"] and row.get("inputs") == cli_case_inputs(work, case, spec),
            "public CLI path/argument/input protocol differs")
    require((not marker.exists() and row.get("child_marker") is False) if refused or missing else
            (cli_read_bytes(marker) == b"route child\n" and row.get("child_marker") is True), "public CLI child marker differs")
    for stream in ("stdout", "stderr"):
        data = cli_read_bytes(work / (stream + ".bin"))
        require(data.hex() == row.get(stream + "_hex") and type(row.get(stream + "_bytes")) is int
                and row.get(stream + "_bytes") == len(data)
                and row.get(stream + "_sha256") == hashlib.sha256(data).hexdigest(), "public CLI stream receipt changed")


def verify_cli_report(report, spec, work, *, parse_bytes: ImportBytesParser | None = None):
    require(json.loads((work.parent / "spec.json").read_text(encoding="utf-8")) == spec,
            "public CLI persisted specification differs")
    verify_cli_spec(spec, work.parent, parse_bytes=parse_bytes)
    require(report.get("kind") == KIND + ".cli-runtime" and report.get("status") == "passed"
            and report.get("execution_backend") == "direct-windows-pe" and report.get("native_bootstrap") is False
            and report.get("transport_only") is True and report.get("inputs_unchanged") is True
            and report.get("spec_sha256") == sha256_file(work.parent / "spec.json"), "public CLI runtime receipt is incomplete")
    rows = report.get("rows", [])
    require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows)
            and [row.get("case") for row in rows] == [case["case"] for case in cli_cases()], "public CLI cases missing, reordered, or duplicated")
    for row, case in zip(rows, cli_cases(), strict=True):
        verify_cli_row(row, case, work / case["case"], spec)


def observe_cli_case(spec, work, case, unchanged, row):
    api, handle, proc, pinned, failure = None, None, None, None, None

    def cancel():
        if proc is not None and proc.poll() is None:
            row["cancellation_attempted"] = True
            proc.kill()
            proc.wait(timeout=2)
            row.update(coil_cancelled=True, popen_returncode=proc.returncode)

    def close():
        if handle:
            require(api.CloseHandle(handle), "public CLI held process handle close failed")

    def capture():
        cli_capture_streams(row, work)
        row["child_marker"] = (work / "launched.txt").exists()

    def inputs():
        if pinned is not None:
            require(cli_case_inputs(work, case, spec) == pinned, "public CLI input changed during execution")
            row["inputs_verified"] = True

    try:
        work.mkdir()
        for name, data in (("input.bin", CLI_INPUT), ("cwd-input.txt", b"owned cwd\n")):
            (work / name).write_bytes(data)
        for parent in (work, work / "loaded image 雪", work / "decoy", work / "decoy" / "path"):
            parent.mkdir(parents=True, exist_ok=True)
            for tool, name in CLI_SIBLINGS.items():
                if parent == work / "loaded image 雪" and (tool != case["tool"] or case.get("missing")):
                    continue
                shutil.copyfile(ROOT / spec["images"][CLI_ENTRIES[1]]["path"], parent / name)
        for parent in (work, work / "loaded image 雪", work / "decoy"):
            shutil.copyfile(ROOT / spec["images"][CLI_ENTRIES[0]]["path"], parent / "coil.exe")
        pinned = cli_case_inputs(work, case, spec)
        application = work / "loaded image 雪" / "coil.exe"
        command = [str(work / "decoy" / "coil.exe"), case["tool"], *case["words"]]
        env = {key: value for key, value in os.environ.items()
               if key.upper() not in {*CLI_OVERRIDES["lsp"], "OURO_TEST_BUILD", "OURO_CLI_ROUTE_IMAGE", "OURO_CLI_ROUTE_TEST", "OURO_CLI_ROUTE_EMPTY"}}
        env.update(PATH=str(work / "decoy" / "path"), OURO_CLI_ROUTE_IMAGE=str(application.parent / CLI_SIBLINGS[case["tool"]]),
                   OURO_CLI_ROUTE_TEST="雪 value", OURO_CLI_ROUTE_EMPTY="", **case["overrides"])
        row.update(application=str(application), argv=command, cwd=str(work), overrides=case["overrides"],
                   inputs=pinned, completion_signaled=False, inputs_verified=False)
        api = kernel()
        started = time.monotonic()
        unchanged()
        with (work / "input.bin").open("rb") as input_stream, (work / "stdout.bin").open("xb") as output, (work / "stderr.bin").open("xb") as errors:
            proc = subprocess.Popen(command, executable=str(application), cwd=work, env=env,
                                    stdin=input_stream, stdout=output, stderr=errors,
                                    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
            handle = api.OpenProcess(0x100000 | 0x1000, False, proc.pid)
            require(handle, "public CLI process handle could not be held")
            while api.WaitForSingleObject(handle, 0) == 258:
                require(time.monotonic() - started < 20, "public CLI case exceeded its observation deadline")
                cli_read_bytes(work / "stdout.bin")
                cli_read_bytes(work / "stderr.bin")
                time.sleep(0.01)
            require(api.WaitForSingleObject(handle, 0) == 0, "public CLI process completion is not signaled")
            from ctypes import wintypes as windows

            code = windows.DWORD()
            require(api.GetExitCodeProcess(handle, ctypes.byref(code)), "public CLI completed DWORD query failed")
            proc.wait(timeout=2)
            row.update(status="ok", exit=code.value, completion_signaled=True, popen_returncode=proc.returncode)
        capture()
        verify_cli_row(row, case, work, spec)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as error:
        failure = error
        row.update(status="failed", error=str(error))
        raise
    else:
        return row
    finally:
        final_errors = []
        for phase, action in (("cancel", cancel), ("close", close), ("streams", capture), ("inputs", inputs), ("source", unchanged)):
            try:
                action()
            except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as error:
                final_errors.append({"phase": phase, "error": str(error)})
        if final_errors:
            row.update(status="failed", final_errors=final_errors)
            if failure is None:
                row["error"] = str(final_errors)
                raise ValueError("public CLI final observation failed: " + str(final_errors))


def cli_worker(spec_path, expected_hash, work):
    directory = spec_path.parent
    require(directory.resolve().is_relative_to(ROOT) and work == directory / "runtime" and not work.exists(), "public CLI observer output differs or exists")
    work.mkdir()
    report = {"kind": KIND + ".cli-runtime", "status": "running", "execution_backend": "direct-windows-pe",
              "native_bootstrap": False, "transport_only": True, "spec_sha256": expected_hash, "inputs_unchanged": False, "rows": []}
    spec, failure = None, None
    parse_bytes = cached_import_parser()

    def unchanged():
        require(spec_path.is_file() and not spec_path.is_symlink() and sha256_file(spec_path) == expected_hash, "public CLI specification changed")
        verify_cli_spec(spec, directory, parse_bytes=parse_bytes)

    try:
        require(sha256_file(spec_path) == expected_hash, "public CLI initial specification differs")
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        unchanged()
        for case in cli_cases():
            row = {"case": case["case"], "status": "running"}
            report["rows"].append(row)
            observe_cli_case(spec, work / case["case"], case, unchanged, row)
        unchanged()
        report.update(status="passed", inputs_unchanged=True)
        verify_cli_report(report, spec, work, parse_bytes=parse_bytes)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as error:
        failure = error
        report.update(status="failed", error=str(error))
        raise
    finally:
        if spec is not None:
            try:
                unchanged()
                for row, case in zip(report["rows"], cli_cases(), strict=False):
                    case_work = work / case["case"]
                    if row["status"] == "ok":
                        verify_cli_row(row, case, case_work, spec)
                    else:
                        if "inputs" in row:
                            require(cli_case_inputs(case_work, case, spec) == row["inputs"], "public CLI failed-case input changed")
                        cli_capture_streams(row, case_work)
            except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
                report.update(status="failed", inputs_unchanged=False, final_error=str(error))
                if failure is None:
                    report["error"] = str(error)
                    write_json_atomic(work / "report.json", report)
                    raise
        write_json_atomic(work / "report.json", report)
    print(f"FRONTEND_PUBLIC_CLI: PASS cases={len(cli_cases())}")


def run_cli_section(producer, work, run, build_timeout, probe_timeout, verify_inputs, *,
                    parse_bytes: ImportBytesParser | None = None):
    from dataclasses import asdict
    from frontend_host_suite import verify_native_raw_fn_emission

    directory = work / "native-process" / "public-cli"
    (directory / "images").mkdir(parents=True)
    if parse_bytes is None:
        parse_bytes = cached_import_parser()
    lineage = cli_lineage(work, parse_bytes=parse_bytes)
    require(lineage["producer"] == str(producer), "public CLI producer is not the current owned host")
    spec = {"kind": KIND + ".cli-spec", "directory": str(directory), "lineage": lineage,
            "cases": cli_cases(), "law_names": cli_law_names(), "images": {}}
    report = {"kind": KIND + ".cli", "status": "running", "transport_only": True, "native_bootstrap": False,
              "spec": spec, "runtime": None, "laws": None}

    def unchanged():
        verify_inputs()
        require(cli_lineage(work, parse_bytes=parse_bytes) == lineage, "public CLI producer/source lineage changed")
        for entry, row in spec["images"].items():
            require(inspect_image(ROOT / row["path"], IMPORTS[API]) == row["image"], "public CLI image changed: " + entry)

    try:
        for entry, name in zip(CLI_ENTRIES, CLI_NAMES, strict=True):
            unchanged()
            output = directory / "images" / name
            logical = output.relative_to(ROOT).as_posix()
            result = run("public-cli-emit-" + output.stem,
                         [str(producer), entry, logical, *lineage["runtime_inputs"]["closures"][entry]], build_timeout)
            emission = asdict(result)
            verify_native_raw_fn_emission(emission, logical, len(lineage["runtime_inputs"]["closures"][entry]))
            spec["images"][entry] = {"path": logical, "image": inspect_image(output, IMPORTS[API]), "emission": emission}
            unchanged()
        laws = run("public-cli-laws", [str(ROOT / spec["images"][CLI_ENTRIES[2]]["path"])], probe_timeout)
        expected = "".join("PRECISION_OK " + name + "\n" for name in spec["law_names"]) + "PRECISION_SUITE native-cli-args rows=127\n"
        require(laws.ok and laws.stdout == expected and laws.stderr == "", "public CLI retained/new laws differ")
        report["laws"] = asdict(laws)
        spec_path = directory / "spec.json"
        write_json_atomic(spec_path, spec)
        pinned = sha256_file(spec_path)
        verify_cli_spec(spec, directory, parse_bytes=parse_bytes)
        unchanged()
        result = run("public-cli-runtime", [sys.executable, "-B", str(Path(__file__).resolve()), "--cli-spec", str(spec_path),
                     "--cli-spec-sha256", pinned, "--out", str(directory / "runtime")], max(300, len(MODES) * probe_timeout))
        require(result.ok and result.stdout == f"FRONTEND_PUBLIC_CLI: PASS cases={len(cli_cases())}\n" and result.stderr == "", "public CLI observer failed")
        report["runtime"] = json.loads((directory / "runtime" / "report.json").read_text(encoding="utf-8"))
        require(sha256_file(spec_path) == pinned, "public CLI specification changed after execution")
        verify_cli_report(report["runtime"], spec, directory / "runtime", parse_bytes=parse_bytes)
        report["status"] = "passed"
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        try:
            unchanged()
            if report["runtime"] is not None:
                verify_cli_report(report["runtime"], spec, directory / "runtime", parse_bytes=parse_bytes)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            report.update(status="failed", error=str(error))
            write_json_atomic(directory / "report.json", report)
            raise
        write_json_atomic(directory / "report.json", report)
    return report


def source_law_config(section):
    if section == "toolchain":
        return TOOLCHAIN_LAWS, TOOLCHAIN_ENTRIES
    require(section == "release-stage", "unknown native source-law section")
    return RELEASE_LAWS, RELEASE_ENTRIES


def source_law_names(section):
    laws, _entries = source_law_config(section)
    result = {}
    for entry, label, count in laws:
        prefix = "native-release" if entry == RELEASE_LAWS[0][0] else label
        text = (ROOT / entry).read_text(encoding="utf-8")
        names = re.findall(r'MkPair String Bool "(' + re.escape(prefix) + r'/[^"\n]+)"', text)
        require(len(names) == count and len(set(names)) == count,
                f"{section} must retain all {count} ordered {label} laws")
        if entry == RELEASE_LAWS[0][0]:
            require(names == list(RELEASE_MODEL_NAMES), "native release must retain the exact 48 + 23 ordered laws")
        result[entry] = names
    return result


def toolchain_law_names():
    return source_law_names("toolchain")


def source_law_image(path, section):
    if section == "release-stage":
        return inspect_image(path, IMPORTS[API], RELEASE_SYMBOLS)
    return inspect_image(path, IMPORTS[API])


def source_law_plan(section, images, work, entry):
    directory = work / "native-process" / section
    is_toolchain_io = section == "toolchain" and entry == TOOLCHAIN_LAWS[2][0]
    cwd = directory / "unrelated cwd 雪" if is_toolchain_io or section == "release-stage" else ROOT
    arguments = [str(ROOT / images[entry]["path"])]
    if is_toolchain_io:
        arguments.extend([str(ROOT / images[TOOLCHAIN_CHILD]["path"]), str(directory / "io inputs 雪")])
    elif entry == RELEASE_LAWS[1][0]:
        arguments.append(str(directory / "io inputs 雪"))
    environment = dict(RELEASE_ENV) if section == "release-stage" else TOOLCHAIN_ENV if is_toolchain_io else {}
    return cwd, arguments, environment


def release_stage_files(work):
    fixture = work / "native-process" / "release-stage" / "io inputs 雪"
    # Literal bytes also cover the deliberately retained failed roots.
    expected = {"source 雪.bin": RELEASE_BYTES, "empty.bin": b"",
                "bundle 雪/bin/coil.exe": RELEASE_BYTES, "bundle 雪/src/empty": b"",
                "corrupt/bin/coil.exe": b"broken", "corrupt/src/empty": b"broken",
                "changed-source/bin/coil.exe": RELEASE_BYTES, "changed-source/src/empty": b"",
                "extra-output/bin/coil.exe": RELEASE_BYTES, "extra-output/src/empty": b"",
                "extra-output/unexpected.bin": b"extra"}
    directories = sorted({parent.as_posix() for name in expected for parent in Path(name).parents
                          if parent != Path(".")})
    require(fixture.is_dir() and not fixture.is_symlink()
            and not (getattr(fixture.lstat(), "st_file_attributes", 0) & 0x400),
            "native release fixture root is absent or redirected")

    def unreadable(error):
        raise error

    actual_files, actual_directories = [], []
    for parent, children, files in os.walk(fixture, onerror=unreadable, followlinks=False):
        for name in [*children, *files]:
            path = Path(parent) / name
            require(not path.is_symlink() and not (getattr(path.lstat(), "st_file_attributes", 0) & 0x400),
                    "native release fixture contains a redirected path")
            relative = path.relative_to(fixture).as_posix()
            if path.is_file():
                actual_files.append(relative)
            else:
                require(path.is_dir(), "native release fixture contains a non-file entry")
                actual_directories.append(relative)
            require(len(actual_files) <= len(expected) and len(actual_directories) <= len(directories),
                    "native release fixture inventory exceeds its bound")
    require(sorted(actual_files) == sorted(expected) and sorted(actual_directories) == directories,
            "native release fixture file or directory inventory differs")
    files = {}
    for name, expected_bytes in expected.items():
        data = cli_read_bytes(fixture / name)
        require(data == expected_bytes, "native release fixture bytes differ: " + name)
        files[name] = {"bytes": len(data), "hex": data.hex(), "sha256": hashlib.sha256(data).hexdigest()}
    return {"path": fixture.relative_to(ROOT).as_posix(), "files": files, "directories": directories}


def verify_source_law_row(row, report, work, entry, label, count, section):
    cwd, arguments, environment = source_law_plan(section, report["images"], work, entry)
    expected = "".join("PRECISION_OK " + name + "\n" for name in report["law_names"][entry])
    expected += f"PRECISION_SUITE {label} rows={count}\n"
    stream_label = section + "-" + label
    stdout, stderr = work / (stream_label + ".out"), work / (stream_label + ".err")
    require(row.get("entry") == entry and row.get("argv") == arguments and row.get("cwd") == str(cwd)
            and row.get("environment_overrides") == environment
            and row.get("status") == "ok" and type(row.get("returncode")) is int and row["returncode"] == 0
            and row.get("capture") == "bytes" and row.get("stdout_hex") == expected.encode().hex()
            and row.get("stderr_hex") == "", section + " complete law verdict differs: " + entry)
    require(row.get("stdout_path") == stdout.relative_to(ROOT).as_posix()
            and row.get("stderr_path") == stderr.relative_to(ROOT).as_posix()
            and row.get("stdout_sha256") == sha256_file(stdout) and row.get("stderr_sha256") == sha256_file(stderr)
            and cli_read_bytes(stdout) == expected.encode() and cli_read_bytes(stderr) == b"",
            section + " raw byte receipt differs: " + entry)


def verify_source_law_report(report, work, section, *, parse_bytes: ImportBytesParser | None = None):
    from frontend_host_suite import verify_native_raw_fn_emission

    laws, entries = source_law_config(section)
    require(report.get("kind") == KIND + "." + section and report.get("status") == "passed"
            and report.get("execution_backend") == "direct-windows-pe"
            and report.get("transport_only") is (section == "toolchain") and report.get("native_bootstrap") is False,
            section + " fixture section did not complete")
    lineage = cli_lineage(work, parse_bytes=parse_bytes)
    require(report.get("lineage") == lineage and report.get("law_names") == source_law_names(section),
            section + " source or producer lineage differs")
    directory = work / "native-process" / section
    images = report.get("images", {})
    require(set(images) == set(entries), section + " image inventory differs")
    for entry in entries:
        logical = (directory / "images" / (Path(entry).stem + ".exe")).relative_to(ROOT).as_posix()
        row = images[entry]
        units = lineage["runtime_inputs"]["closures"][entry]
        require(row.get("path") == logical and row.get("image") == source_law_image(ROOT / logical, section)
                and row.get("emission", {}).get("argv") == [lineage["producer"], entry, logical, *units],
                section + " emission or image differs: " + entry)
        verify_native_raw_fn_emission(row["emission"], logical, len(units))
    rows = report.get("rows", [])
    require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows)
            and [row.get("entry") for row in rows] == [entry for entry, _label, _count in laws],
            section + " law execution inventory or order differs")
    for row, (entry, label, count) in zip(rows, laws, strict=True):
        verify_source_law_row(row, report, work, entry, label, count, section)
    if section == "release-stage":
        fixture = directory / "io inputs 雪"
        require(report.get("fixture_before") == {"path": fixture.relative_to(ROOT).as_posix(), "state": "absent"}
                and report.get("fixture_after") == release_stage_files(work),
                "native release fixture input/output receipt differs")
    return report


def verify_toolchain_law_row(row, report, work, entry, label, count):
    return verify_source_law_row(row, report, work, entry, label, count, "toolchain")


def verify_toolchain_report(report, work, *, parse_bytes: ImportBytesParser | None = None):
    return verify_source_law_report(report, work, "toolchain", parse_bytes=parse_bytes)


def verify_release_report(report, work, steps, *, parse_bytes: ImportBytesParser | None = None):
    verify_source_law_report(report, work, "release-stage", parse_bytes=parse_bytes)
    labels = ["release-stage-" + label for _entry, label, _count in RELEASE_LAWS]
    observed = [row for row in steps if row.get("label") in labels]
    require([row.get("label") for row in observed] == labels, "native release host steps are missing or duplicated")
    for step, row in zip(observed, report["rows"], strict=True):
        require(step.get("environment_policy") == RELEASE_ENV and type(step.get("returncode")) is int
                and all(step.get(field) == row.get(field) for field in
                        ("argv", "cwd", "environment_overrides", "status", "returncode", "capture",
                         "stdout_hex", "stderr_hex", "stdout_sha256", "stderr_sha256"))
                and step.get("stdout") == Path(row["stdout_path"]).name
                and step.get("stderr") == Path(row["stderr_path"]).name,
                "native release selected environment or host byte receipt differs")
    return report


def run_source_law_section(section, producer, work, run, build_timeout, probe_timeout, verify_inputs, *,
                           parse_bytes: ImportBytesParser | None = None):
    from dataclasses import asdict
    from frontend_host_suite import bytes_run_record, verify_native_raw_fn_emission

    laws, entries = source_law_config(section)
    directory = work / "native-process" / section
    (directory / "images").mkdir(parents=True)
    if parse_bytes is None:
        parse_bytes = cached_import_parser()
    lineage = cli_lineage(work, parse_bytes=parse_bytes)
    require(lineage["producer"] == str(producer), section + " producer is not the current owned host")
    names = source_law_names(section)
    report = {"kind": KIND + "." + section, "status": "running", "execution_backend": "direct-windows-pe",
              "transport_only": section == "toolchain", "native_bootstrap": False,
              "lineage": lineage, "law_names": names, "images": {}, "rows": []}

    def unchanged():
        verify_inputs()
        require(cli_lineage(work, parse_bytes=parse_bytes) == lineage, section + " producer/source lineage changed")
        for entry, row in report["images"].items():
            require(source_law_image(ROOT / row["path"], section) == row["image"],
                    section + " image changed: " + entry)

    try:
        for entry in entries:
            unchanged()
            output = directory / "images" / (Path(entry).stem + ".exe")
            logical = output.relative_to(ROOT).as_posix()
            units = lineage["runtime_inputs"]["closures"][entry]
            result = run(section + "-emit-" + output.stem, [str(producer), entry, logical, *units], build_timeout)
            emission = asdict(result)
            verify_native_raw_fn_emission(emission, logical, len(units))
            report["images"][entry] = {"path": logical, "image": source_law_image(output, section), "emission": emission}
            unchanged()
        (directory / "unrelated cwd 雪").mkdir()
        fixture = directory / "io inputs 雪"
        require(not fixture.exists(), section + " IO inputs must be fresh")
        if section == "release-stage":
            report["fixture_before"] = {"path": fixture.relative_to(ROOT).as_posix(), "state": "absent"}
        for entry, label, count in laws:
            unchanged()
            if section == "release-stage":
                require(not fixture.exists(), "native release IO fixture was created before its execution")
            cwd, command, environment = source_law_plan(section, report["images"], work, entry)
            result = run(section + "-" + label, command, probe_timeout, cwd=cwd,
                         capture_bytes=True, environment_overrides=environment)
            row = {"entry": entry, "cwd": str(cwd), "environment_overrides": dict(environment)}
            report["rows"].append(row)
            row.update(bytes_run_record(result))
            for stream in ("stdout", "stderr"):
                path = work / (section + "-" + label + (".out" if stream == "stdout" else ".err"))
                row[stream + "_path"] = path.relative_to(ROOT).as_posix()
                row[stream + "_sha256"] = sha256_file(path)
            verify_source_law_row(row, report, work, entry, label, count, section)
            unchanged()
        if section == "release-stage":
            report["fixture_after"] = release_stage_files(work)
        report["status"] = "passed"
        verify_source_law_report(report, work, section, parse_bytes=parse_bytes)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        try:
            unchanged()
            if report["status"] == "passed":
                verify_source_law_report(report, work, section, parse_bytes=parse_bytes)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            report.update(status="failed", error=str(error))
            write_json_atomic(directory / "report.json", report)
            raise
        write_json_atomic(directory / "report.json", report)
    return report


def run_toolchain_section(producer, work, run, build_timeout, probe_timeout, verify_inputs, *,
                          parse_bytes: ImportBytesParser | None = None):
    return run_source_law_section("toolchain", producer, work, run, build_timeout, probe_timeout, verify_inputs,
                                  parse_bytes=parse_bytes)


def run_release_section(producer, work, run, build_timeout, probe_timeout, verify_inputs, *,
                        parse_bytes: ImportBytesParser | None = None):
    return run_source_law_section("release-stage", producer, work, run, build_timeout, probe_timeout, verify_inputs,
                                  parse_bytes=parse_bytes)


def release_stream_cases():
    rows = [
        ("empty", "copy", "0", "0", "empty", 0, "absent"),
        ("boundary65535", "copy", "65535", "65535", "pattern", 65535, "absent"),
        ("chunk65536", "copy", "65536", "65536", "pattern", 65536, "absent"),
        ("boundary65537", "copy", "65537", "65537", "pattern", 65537, "absent"),
        ("multichunk131073", "copy", "131073", "131073", "pattern", 131073, "absent"),
        ("binary", "copy", "7", "7", "binary", 7, "absent"),
        ("full-Nat-cap", "copy", "7", "18446744073709551616", "binary", 7, "absent"),
        ("Unicode-paths", "copy", "7", "7", "binary", 7, "absent"),
        ("existing-stage", "collision", "7", "7", "binary", 7, "kept"),
        ("same-source", "collision", "7", "7", "binary", 7, "source"),
        ("reused-action", "reuse", "7", "7", "binary", 7, "absent"),
        ("declared-cap", "cap", "3", "2", "three", 3, "absent"),
        ("actual-size-cap", "actual-cap", "2", "2", "three", 3, "absent"),
        ("declared-size", "length", "4", "4", "three", 3, "absent"),
        ("first-error", "length", "4", "4", "three", 3, "kept"),
        ("deferred", "deferred", "7", "7", "old", 7, "absent"),
    ]
    result = [dict(case=name, mode=mode, declared=declared, cap=cap, source=source, size=size, stage=stage)
              for name, mode, declared, cap, source, size, stage in rows]
    for name, mode, declared, cap in (
        ("unknown-mode", "unknown", "7", "7"), ("missing-arg", "copy", "7", "7"),
        ("extra-arg", "copy", "7", "7"), ("negative-declared", "copy", "-1", "7"),
        ("invalid-cap", "copy", "7", "invalid"), ("actual-cap-declared", "actual-cap", "3", "2"),
    ):
        result.append(dict(case="cli-" + name, mode=mode, declared=declared, cap=cap,
                           source="binary", size=7, stage="absent", refusal=name))
    return result


def release_stream_plan(work, case):
    directory = work / "native-process" / "release-stream"
    fixture = directory / "inputs 雪" / case["case"]
    source_name, stage_name = ("source 雪 spaced.bin", "stage 雪 spaced.bin") if case["case"] == "Unicode-paths" else (
        "source.bin", "stage.bin")
    source = fixture / source_name
    stage = source if case["stage"] == "source" else fixture / stage_name
    command = [str(directory / "images" / "release_stream.exe"), case["mode"], str(source), str(stage),
               case["declared"], case["cap"]]
    if case.get("refusal") == "missing-arg":
        command.pop()
    elif case.get("refusal") == "extra-arg":
        command.append("unexpected")
    return fixture, directory / "unrelated cwd 雪", command


def release_stream_expected_files(case, after):
    if case["source"] == "pattern":
        data = bytes((index + 37 * (index // 65536)) % 256 for index in range(case["size"]))
    else:
        data = {"empty": b"", "binary": RELEASE_STREAM_BYTES, "three": RELEASE_STREAM_BYTES[:3],
                "old": RELEASE_STREAM_OLD}[case["source"]]
    source = RELEASE_STREAM_BYTES if after and case["mode"] == "deferred" else data
    names = ("source 雪 spaced.bin", "stage 雪 spaced.bin") if case["case"] == "Unicode-paths" else (
        "source.bin", "stage.bin")
    expected = {names[0]: source}
    if case["stage"] == "kept":
        expected[names[1]] = RELEASE_STREAM_KEPT
    elif after and not case.get("refusal") and case["mode"] in ("copy", "reuse", "deferred"):
        expected[names[1]] = source
    return expected


def release_stream_expected_snapshot(work, case, after):
    fixture, _cwd, _command = release_stream_plan(work, case)
    return {"path": fixture.relative_to(ROOT).as_posix(), "files": {
        name: {"bytes": len(data), "hex": data.hex(), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in release_stream_expected_files(case, after).items()}}


def release_stream_files(work, case, after):
    fixture, _cwd, _command = release_stream_plan(work, case)
    require(fixture.is_dir() and not fixture.is_symlink()
            and not (getattr(fixture.lstat(), "st_file_attributes", 0) & 0x400),
            "native release stream fixture root is absent or redirected")
    expected = release_stream_expected_files(case, after)
    children = list(fixture.iterdir())
    require(sorted(path.name for path in children) == sorted(expected),
            "native release stream file inventory differs: " + case["case"])
    for path in children:
        require(path.is_file() and not path.is_symlink()
                and not (getattr(path.lstat(), "st_file_attributes", 0) & 0x400),
                "native release stream fixture contains a redirected or non-file entry")
        require(cli_read_bytes(path) == expected[path.name],
                "native release stream full binary bytes differ: " + case["case"] + "/" + path.name)
    return release_stream_expected_snapshot(work, case, after)


def release_stream_expected_output(case):
    if case.get("refusal"):
        return 2, b"", RELEASE_STREAM_USAGE
    names = RELEASE_STREAM_LABELS[case["mode"]]
    stdout = "".join("PRECISION_OK native-release-stream/" + name + "\n" for name in names)
    stdout += f"PRECISION_SUITE native-release-stream rows={len(names)}\n"
    return 0, stdout.encode(), b""


def release_stream_image(path):
    require(path.is_file() and not path.is_symlink()
            and not (getattr(path.lstat(), "st_file_attributes", 0) & 0x400),
            "native release stream PE is absent or redirected")
    return inspect_image(path, IMPORTS[API], RELEASE_STREAM_SYMBOLS)


def verify_release_stream_row(row, work, case):
    _fixture, cwd, command = release_stream_plan(work, case)
    code, stdout, stderr = release_stream_expected_output(case)
    require(row.get("case") == case["case"] and row.get("argv") == command and row.get("cwd") == str(cwd)
            and row.get("environment_overrides") == RELEASE_ENV
            and row.get("status") == "ok" and type(row.get("returncode")) is int and row["returncode"] == code
            and row.get("capture") == "bytes" and row.get("stdout_hex") == stdout.hex()
            and row.get("stderr_hex") == stderr.hex(),
            "native release stream exact verdict differs: " + case["case"])
    label = "release-stream-" + case["case"]
    for stream, data in (("stdout", stdout), ("stderr", stderr)):
        path = work / (label + (".out" if stream == "stdout" else ".err"))
        require(row.get(stream + "_path") == path.relative_to(ROOT).as_posix()
                and row.get(stream + "_sha256") == sha256_file(path) and cli_read_bytes(path) == data,
                "native release stream raw byte receipt differs: " + case["case"])
    require(row.get("before") == release_stream_expected_snapshot(work, case, False)
            and row.get("after") == release_stream_files(work, case, True),
            "native release stream source/stage state receipt differs: " + case["case"])


def verify_release_stream_report(report, work, steps=None, *, parse_bytes: ImportBytesParser | None = None):
    from frontend_host_suite import verify_native_raw_fn_emission

    cases = release_stream_cases()
    require(report.get("kind") == KIND + ".release-stream" and report.get("status") == "passed"
            and report.get("execution_backend") == "direct-windows-pe"
            and report.get("transport_only") is False and report.get("native_bootstrap") is False
            and report.get("cases") == cases,
            "required native release stream section did not complete")
    lineage = cli_lineage(work, parse_bytes=parse_bytes)
    require(report.get("lineage") == lineage, "native release stream source/producer lineage differs")
    directory = work / "native-process" / "release-stream"
    logical = (directory / "images" / "release_stream.exe").relative_to(ROOT).as_posix()
    image = report.get("image", {})
    units = lineage["runtime_inputs"]["closures"][RELEASE_STREAM_ENTRY]
    require(image.get("path") == logical
            and image.get("image") == release_stream_image(ROOT / logical)
            and image.get("emission", {}).get("argv") == [lineage["producer"], RELEASE_STREAM_ENTRY, logical, *units],
            "native release stream emission, PE, or image differs")
    verify_native_raw_fn_emission(image["emission"], logical, len(units))
    emit_label = "release-stream-emit-release_stream"
    for stream in ("stdout", "stderr"):
        path = work / (emit_label + (".out" if stream == "stdout" else ".err"))
        require(image.get(stream + "_path") == path.relative_to(ROOT).as_posix()
                and image.get(stream + "_sha256") == sha256_file(path)
                and cli_read_bytes(path) == image["emission"][stream].encode(),
                "native release stream emission byte receipt differs")
    for path in (directory, directory / "images", directory / "inputs 雪", directory / "unrelated cwd 雪"):
        require(path.is_dir() and not path.is_symlink()
                and not (getattr(path.lstat(), "st_file_attributes", 0) & 0x400),
                "native release stream owning directory is absent or redirected")
    require(sorted(path.name for path in (directory / "images").iterdir()) == ["release_stream.exe"]
            and not list((directory / "unrelated cwd 雪").iterdir())
            and sorted(path.name for path in (directory / "inputs 雪").iterdir())
            == sorted(case["case"] for case in cases),
            "native release stream owned input/image/cwd inventory differs")
    require(report.get("fixture_before") == {
        "path": (directory / "inputs 雪").relative_to(ROOT).as_posix(), "state": "absent"},
        "native release stream input root was not fresh")
    rows = report.get("rows", [])
    require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows)
            and [row.get("case") for row in rows] == [case["case"] for case in cases],
            "native release stream row inventory/order differs")
    for row, case in zip(rows, cases, strict=True):
        verify_release_stream_row(row, work, case)
    if steps is not None:
        labels = [emit_label, *("release-stream-" + case["case"] for case in cases)]
        observed = [step for step in steps if step.get("label") in labels]
        require([step.get("label") for step in observed] == labels,
                "native release stream required host steps are missing, reordered, or duplicated")
        emitted = observed[0]
        require(emitted.get("argv") == image["emission"]["argv"] and emitted.get("cwd") == str(ROOT)
                and emitted.get("status") == "ok" and type(emitted.get("returncode")) is int
                and emitted["returncode"] == 0 and emitted.get("capture") is None,
                "native release stream host emission step differs")
        for stream in ("stdout", "stderr"):
            require(emitted.get(stream) == Path(image[stream + "_path"]).name
                    and emitted.get(stream + "_sha256") == image[stream + "_sha256"],
                    "native release stream host emission raw receipt differs")
        for step, row in zip(observed[1:], rows, strict=True):
            require(step.get("environment_policy") == RELEASE_ENV and type(step.get("returncode")) is int
                    and all(step.get(field) == row.get(field) for field in
                            ("argv", "cwd", "environment_overrides", "status", "returncode", "capture",
                             "stdout_hex", "stderr_hex", "stdout_sha256", "stderr_sha256"))
                    and step.get("stdout") == Path(row["stdout_path"]).name
                    and step.get("stderr") == Path(row["stderr_path"]).name,
                    "native release stream selected environment or host byte receipt differs")
    return report


def run_release_stream_section(producer, work, run, build_timeout, probe_timeout, verify_inputs, *,
                               parse_bytes: ImportBytesParser | None = None):
    from dataclasses import asdict
    from frontend_host_suite import bytes_run_record, verify_native_raw_fn_emission

    require(0 < build_timeout <= 900 and 0 < probe_timeout <= 30, "native release stream deadlines exceed their caps")
    directory = work / "native-process" / "release-stream"
    (directory / "images").mkdir(parents=True)
    if parse_bytes is None:
        parse_bytes = cached_import_parser()
    lineage = cli_lineage(work, parse_bytes=parse_bytes)
    require(lineage["producer"] == str(producer), "native release stream producer is not the current owned host")
    report = {"kind": KIND + ".release-stream", "status": "running", "execution_backend": "direct-windows-pe",
              "transport_only": False, "native_bootstrap": False, "lineage": lineage,
              "cases": release_stream_cases(), "rows": []}

    def unchanged():
        verify_inputs()
        require(cli_lineage(work, parse_bytes=parse_bytes) == lineage, "native release stream producer/source lineage changed")
        if "image" in report:
            image = report["image"]
            require(release_stream_image(ROOT / image["path"]) == image["image"],
                    "native release stream image changed")

    try:
        unchanged()
        output = directory / "images" / "release_stream.exe"
        logical = output.relative_to(ROOT).as_posix()
        units = lineage["runtime_inputs"]["closures"][RELEASE_STREAM_ENTRY]
        result = run("release-stream-emit-release_stream",
                     [str(producer), RELEASE_STREAM_ENTRY, logical, *units], build_timeout)
        emission = asdict(result)
        verify_native_raw_fn_emission(emission, logical, len(units))
        image = {"path": logical, "image": release_stream_image(output), "emission": emission}
        report["image"] = image
        for stream in ("stdout", "stderr"):
            path = work / ("release-stream-emit-release_stream" + (".out" if stream == "stdout" else ".err"))
            image[stream + "_path"] = path.relative_to(ROOT).as_posix()
            image[stream + "_sha256"] = sha256_file(path)
        unchanged()
        (directory / "unrelated cwd 雪").mkdir()
        inputs = directory / "inputs 雪"
        require(not inputs.exists(), "native release stream inputs must be fresh")
        report["fixture_before"] = {"path": inputs.relative_to(ROOT).as_posix(), "state": "absent"}
        inputs.mkdir()
        for case in report["cases"]:
            unchanged()
            fixture, cwd, command = release_stream_plan(work, case)
            fixture.mkdir()
            for name, data in release_stream_expected_files(case, False).items():
                (fixture / name).write_bytes(data)
            row = {"case": case["case"], "cwd": str(cwd), "environment_overrides": dict(RELEASE_ENV),
                   "before": release_stream_files(work, case, False)}
            report["rows"].append(row)
            result = run("release-stream-" + case["case"], command, probe_timeout, cwd=cwd,
                         capture_bytes=True, environment_overrides=dict(RELEASE_ENV))
            row.update(bytes_run_record(result))
            for stream in ("stdout", "stderr"):
                path = work / ("release-stream-" + case["case"] + (".out" if stream == "stdout" else ".err"))
                row[stream + "_path"] = path.relative_to(ROOT).as_posix()
                row[stream + "_sha256"] = sha256_file(path)
            row["after"] = release_stream_files(work, case, True)
            verify_release_stream_row(row, work, case)
            unchanged()
        report["status"] = "passed"
        verify_release_stream_report(report, work, parse_bytes=parse_bytes)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        try:
            unchanged()
            if report["status"] == "passed":
                verify_release_stream_report(report, work, parse_bytes=parse_bytes)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            report.update(status="failed", error=str(error))
            write_json_atomic(directory / "report.json", report)
            raise
        write_json_atomic(directory / "report.json", report)
    return report


def inspect_image(path, expected_imports, required_symbols=None):
    if required_symbols is not None:
        require(64 <= path.stat().st_size <= 256 * 1024 * 1024, "native PE exceeds the symbol inspection bound")
    image = path.read_bytes()

    def read(fmt, offset):
        require(0 <= offset <= len(image) - struct.calcsize(fmt), "truncated native PE field")
        return struct.unpack_from(fmt, image, offset)

    require(image[:2] == b"MZ", "native process image lacks DOS header")
    pe, = read("<I", 0x3C)
    require(image[pe:pe + 4] == b"PE\0\0", "native process image lacks PE signature")
    machine, sections = read("<HH", pe + 4)
    optional_size, = read("<H", pe + 20)
    optional = pe + 24
    magic, = read("<H", optional)
    require(machine == 0x8664 and magic == 0x20B and optional_size >= 128 and sections > 0,
            "native process image is not a Windows x86-64 PE32+ image")
    if required_symbols is not None:
        require(sections <= 96, "native PE exceeds the symbol inspection section bound")
    table = optional + optional_size
    section_rows = []
    for index in range(sections):
        row = table + index * 40
        virtual, address, raw, start = read("<IIII", row + 8)
        flags, = read("<I", row + 36)
        require(start + raw <= len(image), "native PE section extends beyond image")
        section_rows.append((address, virtual, start, raw, flags))

    def offset(rva, size=1):
        matches = [start + rva - address for address, virtual, start, raw, _ in section_rows
                   if address <= rva and rva + size <= address + min(virtual, raw)]
        require(len(matches) == 1, "native PE RVA is unmapped, overlapping, or not file-backed")
        return matches[0]

    entry, = read("<I", optional + 16)
    offset(entry)
    require(any(address <= entry < address + min(virtual, raw) and flags & 0x20000000
                for address, virtual, _start, raw, flags in section_rows), "native PE entry is not executable")
    count, = read("<I", optional + 108)
    imports_rva, imports_size = read("<II", optional + 120)
    require(count >= 2 and imports_size >= 20, "native PE import directory is missing")
    if required_symbols is not None:
        require(imports_size <= 1024 * 1024, "native PE exceeds the import directory inspection bound")
    directory = offset(imports_rva, imports_size)
    imports = []
    symbols = {}
    terminated = False
    for position in range(directory, directory + imports_size - 19, 20):
        descriptor = image[position:position + 20]
        if descriptor == bytes(20):
            terminated = True
            break
        name_rva, = read("<I", position + 12)
        start = offset(name_rva)
        end = image.find(b"\0", start, start + 256)
        require(end > start, "native PE import name is empty or unterminated")
        offset(name_rva, end - start + 1)
        library = image[start:end].decode("ascii").lower()
        imports.append(library)
        if required_symbols is not None:
            original, = read("<I", position)
            first, = read("<I", position + 16)
            thunk = original or first
            names = []
            for index in range(8192):
                target, = read("<Q", offset(thunk + index * 8, 8))
                if target == 0:
                    break
                require(target <= 0xFFFFFFFF, "native PE has an ordinal or oversized import RVA")
                offset(target, 2)
                start = offset(target + 2)
                end = image.find(b"\0", start, start + 4096)
                require(end > start, "native PE import symbol is empty or unterminated")
                offset(target + 2, end - start + 1)
                names.append(image[start:end].decode("ascii"))
            else:
                raise ValueError("native PE import thunk table is unterminated")
            symbols[library] = names
    require(terminated and sorted(imports) == sorted(expected_imports),
            f"native PE import set differs: {imports}")
    result = {"sha256": hashlib.sha256(image).hexdigest(), "bytes": len(image), "machine": "x86_64",
              "imports": sorted(imports)}
    if required_symbols is not None:
        require(all(set(names).issubset(symbols.get(library, [])) for library, names in required_symbols.items()),
                "native PE required import symbols are missing")
        result["import_symbols"] = symbols
    return result


def run_section(producer, work, run, build_timeout, probe_timeout, verify_inputs, *,
                parse_bytes: ImportBytesParser | None = None):
    if os.name != "nt":
        return {"kind": KIND, "status": "unavailable", "reason": "Windows x86-64 runtime required",
                "native_bootstrap": False, "rows": [], "helper_rejections": []}
    directory = work / "native-process"
    directory.mkdir()
    if parse_bytes is None:
        parse_bytes = cached_import_parser()
    before = source_snapshot(parse_bytes=parse_bytes)
    pinned_producer = sha256_file(producer)
    binaries = {}
    report = {"kind": KIND, "status": "running", "execution_backend": "direct-windows-pe",
              "external_supervisor": "python", "native_bootstrap": False,
              "producer": str(producer), "producer_sha256": pinned_producer,
              "inputs": before, "binaries": binaries, "helper_rejections": []}

    def unchanged():
        verify_inputs()
        require(source_snapshot(parse_bytes=parse_bytes) == before and sha256_file(producer) == pinned_producer,
                "native process sources or producer changed")
        for entry, row in binaries.items():
            require(inspect_image(ROOT / row["path"], IMPORTS[entry]) == row["image"],
                    "native process image changed: " + entry)

    try:
        for entry in (API, CAPTURE, DENIED):
            unchanged()
            output = directory / (Path(entry).stem + ".exe")
            logical = output.relative_to(ROOT).as_posix()
            timing_args = ["--timings"] if entry == API else []
            result = run("native-build-" + output.stem,
                         [str(producer), *timing_args, entry, logical, *before["closures"][entry]], build_timeout)
            require(result.ok and result.stdout == logical + "\n", "direct native process build failed: " + entry)
            if entry == API:
                verify_lowering_timings(result)
            binaries[entry] = {"path": logical, "image": inspect_image(output, IMPORTS[entry])}
            unchanged()
        result = run("native-process-api-laws", [str(ROOT / binaries[API]["path"])], probe_timeout)
        verify_api_result(result)
        report["api_laws"] = {"status": "passed", "entry": API, "cases": list(API_CASES),
                              "binary_sha256": binaries[API]["image"]["sha256"], "exit": result.returncode,
                              "stdout": result.stdout, "stderr": result.stderr}
        unchanged()
        for name, diagnostic, scalar_fallback in REJECTIONS:
            unchanged()
            entry = rejection_entry(name)
            output = directory / (name + ".exe")
            result = run("native-helper-" + name,
                         [str(producer), entry, output.relative_to(ROOT).as_posix(), *before["closures"][entry]],
                         build_timeout)
            observed = verify_rejection(result, diagnostic, output, scalar_fallback)
            report["helper_rejections"].append({"case": name, "diagnostic": observed,
                                                  "expected_diagnostic": diagnostic,
                                                  "scalar_fallback": scalar_fallback,
                                                  "status": "rejected-after-recheck", "output_absent": True})
            unchanged()
        observed = directory / "runtime"
        command = [sys.executable, "-B", str(Path(__file__).resolve()), "--binary", binaries[CAPTURE]["path"],
                   "--binary-sha256", binaries[CAPTURE]["image"]["sha256"],
                   "--denied", binaries[DENIED]["path"], "--denied-sha256", binaries[DENIED]["image"]["sha256"],
                   "--out", str(observed)]
        result = run("native-process-runtime", command, max(300, len(MODES) * probe_timeout))
        require(result.ok and result.stdout == f"FRONTEND_NATIVE_PROCESS: PASS cases={len(MODES)}\n" and not result.stderr,
                "native process runtime observer failed")
        evidence = json.loads((observed / "report.json").read_text(encoding="utf-8"))
        verify_runtime_report(evidence, binaries[CAPTURE]["image"]["sha256"], binaries[DENIED]["image"]["sha256"],
                              observed)
        report["runtime"] = evidence
        unchanged()
        report["public_cli"] = run_cli_section(producer, work, run, build_timeout, probe_timeout, verify_inputs,
                                               parse_bytes=parse_bytes)
        unchanged()
        report["toolchain"] = run_toolchain_section(producer, work, run, build_timeout, probe_timeout, verify_inputs,
                                                    parse_bytes=parse_bytes)
        unchanged()
        report["release_stage"] = run_release_section(producer, work, run, build_timeout, probe_timeout, verify_inputs,
                                                      parse_bytes=parse_bytes)
        unchanged()
        report["release_stream"] = run_release_stream_section(producer, work, run, build_timeout, probe_timeout, verify_inputs,
                                                              parse_bytes=parse_bytes)
        unchanged()
        report["status"] = "passed"
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        write_json_atomic(directory / "report.json", report)
    return report


def cwd_input_snapshot(work):
    directory = work / "cwd путь пробелы"
    regular_file = work / "not-directory"
    require(regular_file.is_file() and not regular_file.is_symlink(),
            "native file-as-directory input is missing or not a regular file")
    return {"parent_directory": str(work), "child_directory": str(directory),
            "parent_sha256": sha256_file(work / "cwd.bin"), "child_sha256": sha256_file(directory / "cwd.bin"),
            "not_directory_path": str(regular_file), "not_directory_kind": "regular",
            "not_directory_sha256": sha256_file(regular_file)}


def verify_runtime_report(report, binary_sha256, denied_sha256, work):
    require(report.get("kind") == KIND + ".runtime" and report.get("status") == "passed"
            and report.get("binary_sha256") == binary_sha256 and report.get("denied_sha256") == denied_sha256
            and report.get("binaries_unchanged") is True, "native runtime receipt is incomplete or stale")
    inputs = report.get("cwd_inputs_before")
    require(isinstance(inputs, dict) and report.get("cwd_inputs_after") == inputs,
            "native cwd inputs are absent or changed")
    parent, directory = inputs.get("parent_directory"), inputs.get("child_directory")
    require(isinstance(parent, str) and isinstance(directory, str) and "\0" not in parent + directory
            and PureWindowsPath(parent).is_absolute() and parent == str(PureWindowsPath(work))
            and directory == str(PureWindowsPath(parent) / "cwd путь пробелы")
            and inputs.get("parent_sha256") == hashlib.sha256(b"parent").hexdigest()
            and inputs.get("child_sha256") == hashlib.sha256(bytes((65, 0, 255, 128, 10, 13, 90))).hexdigest()
            and inputs.get("not_directory_path") == str(PureWindowsPath(work) / "not-directory")
            and inputs.get("not_directory_kind") == "regular"
            and inputs.get("not_directory_sha256") == hashlib.sha256(b"file").hexdigest(),
            "native cwd fixture path or exact binary inputs differ")
    rows = report.get("rows", [])
    require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows), "native runtime rows are malformed")
    require([row.get("case") for row in rows] == list(MODES), "native runtime cases missing, reordered, or duplicated")
    for row in rows:
        mode = row["case"]
        require(type(row.get("exit")) is int, "native runtime exit is not an integer")
        if mode in {"hard-terminate", "cwd-hard-terminate"}:
            require(row.get("exit") == 1 and row.get("stdout_hex") == "", "native parent cancellation protocol differs")
        else:
            require(row.get("exit") == 42 and row.get("stdout_hex") == f"CAPTURE_OK {mode}\n".encode().hex(),
                    "native process byte protocol differs: " + mode)
        require(row.get("stderr_hex") == "", "native process stderr is not empty: " + mode)
        if mode == "cwd" or mode.startswith("cwd-"):
            require(row.get("cwd") == directory, "native cwd argument is missing or stale: " + mode)
        if mode in {"tree-timeout", "hard-terminate", "cwd-tree-timeout", "cwd-hard-terminate"}:
            ids = row.get("descendant_pids", [])
            require(isinstance(ids, list) and len(ids) == 2
                    and type(row.get("parent_pid")) is int and 0 < row["parent_pid"] <= 0xFFFFFFFF
                    and len(set(ids + [row["parent_pid"]])) == 3
                    and all(type(pid) is int and 0 < pid <= 0xFFFFFFFF for pid in ids)
                    and row.get("alive_before_observation") is True and row.get("held_handles_signaled") is True,
                    "native process tree evidence is incomplete")


def checked_run(binary, work, mode, extra=()):
    started = time.monotonic()
    result = subprocess.run([str(binary), "--" + mode, *map(str, extra)], cwd=work,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    require(result.returncode == 42 and result.stdout == f"CAPTURE_OK {mode}\n".encode() and result.stderr == b"",
            f"{mode}: exit={result.returncode}, stdout={result.stdout!r}, stderr={result.stderr!r}")
    return {"case": mode, "exit": result.returncode, "stdout_hex": result.stdout.hex(),
            "stderr_hex": result.stderr.hex(), "seconds": time.monotonic() - started}


def kernel():
    from ctypes import wintypes as windows

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    for name, result, arguments in (
        ("OpenProcess", windows.HANDLE, [windows.DWORD, windows.BOOL, windows.DWORD]),
        ("WaitForSingleObject", windows.DWORD, [windows.HANDLE, windows.DWORD]),
        ("TerminateProcess", windows.BOOL, [windows.HANDLE, windows.UINT]),
        ("CloseHandle", windows.BOOL, [windows.HANDLE]),
        ("GetExitCodeProcess", windows.BOOL, [windows.HANDLE, ctypes.POINTER(windows.DWORD)]),
    ):
        function = getattr(api, name)
        function.restype, function.argtypes = result, arguments
    return api


def wait_pid(path, child):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        require(child.poll() is None, "native tree parent exited before ready markers")
        try:
            value = path.read_bytes()
        except (FileNotFoundError, PermissionError):
            value = b""
        if value.isdigit():
            pid = int(value)
            require(0 < pid <= 0xFFFFFFFF, "invalid native descendant PID")
            return pid
        time.sleep(0.025)
    raise ValueError("missing native descendant ready marker: " + str(path))


def observe_tree(binary, work, cancel, directory=None):
    work.mkdir()
    api = kernel()
    owned = []
    child = None
    mode = ("cwd-" if directory is not None else "") + ("hard-terminate" if cancel else "tree-timeout")
    try:
        with (work / "stdout").open("wb") as output, (work / "stderr").open("wb") as error:
            markers = [work / "branch.pid", work / "leaf.pid"]
            arguments = [str(binary), ("--cwd-tree" if cancel else "--cwd-tree-timeout")
                         if directory is not None else ("--tree" if cancel else "--tree-timeout"), *map(str, markers)]
            if directory is not None:
                arguments.append(str(directory))
            child = subprocess.Popen(arguments, cwd=work, stdin=subprocess.DEVNULL, stdout=output, stderr=error)
            pids = []
            for marker in markers:
                pid = wait_pid(marker, child)
                require(pid not in [os.getpid(), child.pid, *pids], "native tree PID identities overlap")
                pids.append(pid)
                handle = api.OpenProcess(0x100000 | 0x1000 | 1, False, pid)
                require(handle, f"cannot hold native descendant handle: {ctypes.get_last_error()}")
                owned.append(handle)
                require(api.WaitForSingleObject(handle, 0) == 258, "native descendant was not alive before observation")
            if cancel:
                # Kill only the fixture parent. The outer supervising Job stays open.
                child.terminate()
            code = child.wait(timeout=15)
            for handle in owned:
                require(api.WaitForSingleObject(handle, 10000 if cancel else 0) == 0,
                        "native API left a live descendant after parent completion")
        stdout, stderr = (work / "stdout").read_bytes(), (work / "stderr").read_bytes()
        expected = b"" if cancel else f"CAPTURE_OK {mode}\n".encode()
        require(code == (1 if cancel else 42) and stdout == expected and stderr == b"", "native tree byte protocol differs")
        return {"case": mode, "exit": code, "stdout_hex": stdout.hex(), "stderr_hex": stderr.hex(),
                "parent_pid": child.pid, "descendant_pids": pids, "alive_before_observation": True,
                "held_handles_signaled": True, **({"cwd": str(directory)} if directory is not None else {})}
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            child.wait(timeout=10)
        for handle in owned:
            try:
                if api.WaitForSingleObject(handle, 0) == 258:
                    require(api.TerminateProcess(handle, 91), "native observer failure cleanup could not stop child")
                    require(api.WaitForSingleObject(handle, 10000) == 0, "native observer failure cleanup timed out")
            finally:
                require(api.CloseHandle(handle), "native observer could not close descendant handle")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--binary-sha256")
    parser.add_argument("--denied", type=Path)
    parser.add_argument("--denied-sha256")
    parser.add_argument("--cli-spec", type=Path)
    parser.add_argument("--cli-spec-sha256")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.cli_spec is not None:
        if not args.cli_spec_sha256 or any(value is not None for value in
                (args.binary, args.binary_sha256, args.denied, args.denied_sha256)):
            parser.error("public CLI specification and bounded-process image selectors are mutually exclusive")
        require(os.name == "nt", "native process observer requires Windows")
        cli_worker(args.cli_spec.resolve(strict=True), args.cli_spec_sha256, args.out.resolve())
        return
    if args.cli_spec_sha256 is not None or any(value is None for value in
            (args.binary, args.binary_sha256, args.denied, args.denied_sha256)):
        parser.error("--binary, --binary-sha256, --denied and --denied-sha256 are required")
    require(os.name == "nt", "native process observer requires Windows")
    binary, denied, work = args.binary.resolve(strict=True), args.denied.resolve(strict=True), args.out.resolve()
    require(all(path.is_relative_to(ROOT) for path in (binary, denied, work)), "native probe path escapes repository")
    work.mkdir(parents=True, exist_ok=False)
    directory = work / "cwd путь пробелы"
    directory.mkdir()
    parent_file, child_file = work / "cwd.bin", directory / "cwd.bin"
    parent_file.write_bytes(b"parent")
    child_file.write_bytes(bytes((65, 0, 255, 128, 10, 13, 90)))
    regular_file = work / "not-directory"
    regular_file.write_bytes(b"file")
    inputs = cwd_input_snapshot(work)
    report = {"kind": KIND + ".runtime", "status": "running", "rows": [],
              "cwd_inputs_before": inputs,
              "binary_sha256": args.binary_sha256, "denied_sha256": args.denied_sha256, "binaries_unchanged": False}

    def unchanged():
        require(sha256_file(binary) == args.binary_sha256 and sha256_file(denied) == args.denied_sha256,
                "native runtime input image changed")
        require(cwd_input_snapshot(work) == inputs, "native cwd input files changed")

    try:
        unchanged()
        for mode in MODES[:-4]:
            extra = [denied] if mode == "oversized" else []
            if mode == "cwd" or mode.startswith("cwd-"):
                extra = [directory]
                if mode == "cwd-missing":
                    extra.extend((work / "absent cwd", regular_file))
                elif mode == "cwd-oversized":
                    extra.append(denied)
            unchanged()
            row = checked_run(binary, work, mode, extra)
            if mode == "cwd" or mode.startswith("cwd-"):
                row["cwd"] = str(directory)
            report["rows"].append(row)
            unchanged()
        for located in (None, directory):
            for cancel in (False, True):
                name = ("cwd-" if located is not None else "") + ("hard-terminate" if cancel else "tree-timeout")
                unchanged()
                report["rows"].append(observe_tree(binary, work / name, cancel, located))
                unchanged()
        unchanged()
        report["cwd_inputs_after"] = cwd_input_snapshot(work)
        report["binaries_unchanged"] = True
        report["status"] = "passed"
        verify_runtime_report(report, args.binary_sha256, args.denied_sha256, work)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        write_json_atomic(work / "report.json", report)
    print(f"FRONTEND_NATIVE_PROCESS: PASS cases={len(MODES)}")


if __name__ == "__main__":
    main()
