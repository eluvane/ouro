#!/usr/bin/env python3
"""Observe complete reads and unreadable-input refusal in actual binaries."""
from __future__ import annotations

import argparse
import ctypes as c
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from fs_replace_suite import ROOT, WindowsMetadata, checked
from repo_support import decode_source_text, sha256_bytes, sha256_file

STDIN_C_SOURCES = ("runtime/ouro_rt.c", "runtime/ouro_io.c", "runtime/ouro_io_selftest.c")
STDIN_INPUTS = (*STDIN_C_SOURCES, "runtime/ouro_rt.h", "runtime/ouro_io.h", "runtime/ouro_fs_replace.h",
                "scripts/fs_read_suite.py", "scripts/fs_read_suite_test.py", "scripts/fs_replace_suite.py",
                "scripts/repo_support.py", "scripts/runtime_io_suite.sh")


def stdin_cases():
    reused = b"A\0BCDEFG12345678"
    return (("empty-eof", b""), ("short-eof", b"\0A\xff\r\n\x1aZ"),
            ("second-short-eof", b"12345678x\0\xff"), ("deferred-reuse", reused),
            ("all-nul", bytes(16)),
            ("binary-controls", bytes((0, 255, 128, 13, 10, 26, 0, 65, 66, 0, 67, 255, 13, 10, 128, 90))),
            ("bounded-prefix", reused + b"\0excess"),
            *((f"byte-values-{block:02d}", bytes(range(block * 16, block * 16 + 16))) for block in range(16)))


def stdin_inputs(producer, output):
    found = shutil.which(str(producer))
    if found is None:
        raise ValueError("stdin C producer is unavailable")
    compiler = Path(found).resolve(strict=True)
    command = [compiler.as_posix(), "-O1", "-std=c99", "-D_POSIX_C_SOURCE=200809L",
               "-Werror=implicit-function-declaration", "-I", (ROOT / "runtime").as_posix(),
               "-o", output.resolve().as_posix(), *((ROOT / name).as_posix() for name in STDIN_C_SOURCES)]
    return dict(kind="ouro.stdin-inputs.v1", output=output.resolve().as_posix(), compile_argv=command,
                producer=dict(path=compiler.as_posix(), sha256=sha256_file(compiler)),
                sources={name: sha256_file(ROOT / name) for name in STDIN_INPUTS})


def stdin_write_record(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, indent=2, sort_keys=True) + "\n")


def stdin_verify_inputs(record, producer, driver):
    if not isinstance(record, dict) or not isinstance(record.get("output"), str):
        raise ValueError("invalid stdin precompile inputs")
    output = Path(record["output"])
    if driver.resolve() not in (output.resolve(), Path(str(output) + ".exe").resolve()):
        raise ValueError("stdin driver differs from the precompile output")
    current = stdin_inputs(producer, output)
    if record != current:
        raise ValueError("stdin source or C producer changed")
    return current


def stdin_observation(name, payload, result):
    return dict(name=name, status="fail", input_hex=payload.hex(), expected_hex=payload[:16].hex(),
                returncode=result.returncode,
                stdout_hex=result.stdout.hex() if isinstance(result.stdout, bytes) else None,
                stderr_hex=result.stderr.hex() if isinstance(result.stderr, bytes) else None)


def stdin_verify_result(name, payload, result):
    expected = payload[:16]
    if (type(result.returncode) is not int or result.returncode != 0
            or not isinstance(result.stdout, bytes) or result.stdout != expected or result.stderr != b""):
        raise ValueError(f"stdin {name}: exact exit/byte output differs")
    return dict(stdin_observation(name, payload, result), status="pass")


def run_stdin_suite(driver, output, inputs_path, producer):
    if inputs_path.stat().st_size > 16384:
        raise ValueError("stdin precompile inputs exceed the receipt limit")
    input_bytes = inputs_path.read_bytes()
    before = stdin_verify_inputs(json.loads(input_bytes), producer, driver)
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "report.json"
    if report_path.exists():
        raise ValueError("stdin receipt already exists")
    image_hash = sha256_file(driver)
    report = dict(kind="ouro.stdin-bytes.v1", complete=False, execution_backend="c-runtime-selftest",
                  inputs_sha256=hashlib.sha256(input_bytes).hexdigest(), before=before,
                  driver=dict(path=driver.as_posix(), before_sha256=image_hash), checks=[],
                  argv=[str(driver), "--stdin-bytes"],
                  limits=dict(workers=1, timeout_s=10, maximum_input_bytes=23, maximum_output_bytes=16))
    observations_complete = False
    try:
        for name, payload in stdin_cases():
            try:
                result = subprocess.run(report["argv"], input=payload, cwd=ROOT,
                                        env=dict(os.environ, PATH=""), capture_output=True, timeout=10)
            except subprocess.TimeoutExpired as error:
                report["checks"].append(dict(name=name, status="timeout", input_hex=payload.hex(),
                    expected_hex=payload[:16].hex(), returncode=None,
                    stdout_hex=error.stdout.hex() if isinstance(error.stdout, bytes) else None,
                    stderr_hex=error.stderr.hex() if isinstance(error.stderr, bytes) else None))
                raise
            report["checks"].append(stdin_observation(name, payload, result))
            report["checks"][-1] = stdin_verify_result(name, payload, result)
            print(f"STDIN_BYTES_OK {name}", flush=True)
        observations_complete = True
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report["error"] = str(error)
        raise
    finally:
        try:
            report["after"] = stdin_inputs(producer, Path(before["output"]))
            report["driver"]["after_sha256"] = sha256_file(driver)
            report["inputs_sha256_after"] = sha256_file(inputs_path)
            if (report["after"] != before or report["inputs_sha256_after"] != report["inputs_sha256"]
                    or report["driver"]["after_sha256"] != image_hash):
                raise ValueError("stdin sources, producer, inputs or driver changed during observation")
            report["complete"] = observations_complete
        except (OSError, ValueError) as error:
            report["identity_error"] = str(error)
            raise
        finally:
            stdin_write_record(report_path, report)
    print(f"STDIN_BYTES_SUITE: PASS checks={len(report['checks'])}")


NATIVE_ENTRY = "tests/native_managed/source_file_read_status.ouro"
NATIVE_REJECTIONS = (("helper_missing", r"entry:[1-9][0-9]*", True),
                     ("helper_axiom", r"body:[1-9][0-9]*", False),
                     ("count_pointee", r"metadata:[1-9][0-9]*", False))
NATIVE_CASES = ("empty-file", "complete-file", "missing-file", "empty-directory", "empty-path",
                "nul-path", "unicode-path", "malformed-utf8-path", "deferred-removal",
                "checked-missing-file", "locked-file", "checked-locked-file", "read-after-refusal", "reused-action")


BOUNDED_ENTRIES = {
    "pure": "tests/fs_bounded_tests.ouro",
    "order": "tests/native_fs_bounded_order_tests.ouro",
    "probe": "tests/native_fs_bounded_probe.ouro",
    "calls": "tests/native_fs_bounded_calls.ouro",
}
BOUNDED_PURE_LAWS = (
    "empty-with-zero-cap", "nonempty-with-zero-cap", "exact-cap", "cap-plus-one",
    "cap-above-usize", "large-error-not-truncated", "empty-path", "nul-path",
    "path-capacity", "path-too-long",
)
BOUNDED_ORDER_LAWS = (
    "cap-before-allocation-and-read", "large-cap-and-close-before-release",
    "empty-growth-never-allocates-payload", "positive-partials-preserve-all-binary-bytes",
    "eof-zero-final-size-change-refuses-prefix", "usize-size-high-limb-before-allocation",
)
BOUNDED_FAULTS = (("close-failure", "close"), ("release-failure", "release"),
                  ("close-payload-failure", "close-payload"))
BOUNDED_CASES = (
    "empty-zero", "binary-exact", "binary-high-cap", "binary-zero-cap", "binary-short-cap",
    "chunk-exact", "chunk-short-cap", "unicode-path", "missing-file", "directory",
    "final-reparse", "locked-file", "empty-path", "nul-path", "malformed-utf8-path",
    "deferred-action", "reused-action", "recovery", "read-after-refusal",
    "invalid-cap", "extra-argument", "unknown-source-mode",
)
BOUNDED_LARGE_BYTES = 31 * 1024 * 1024 + 1
BOUNDED_LARGE_CASES = ("large-short-cap", "large-exact")


def bounded_large_contract():
    owner = Path(__file__).resolve()
    return dict(kind="ouro.fs-bounded-large-contract.v1", bytes=BOUNDED_LARGE_BYTES,
                cases=list(BOUNDED_LARGE_CASES),
                owners={"scripts/fs_read_suite.py": sha256_file(owner),
                        "scripts/fs_read_suite_test.py": sha256_file(owner.with_name("fs_read_suite_test.py"))})


def native_source_snapshot(*, parse_bytes=None, read_source=None):
    from frontend_regen import capture_unit_inputs

    entries = (NATIVE_ENTRY, *(f"tests/native_managed/reject/source_file_read_status_{name}.ouro"
                              for name, _, _ in NATIVE_REJECTIONS), *BOUNDED_ENTRIES.values())
    closures, captured = capture_unit_inputs(entries, parse_bytes=parse_bytes, read_source=read_source)
    if any(not units or units[-1] != entry or len(units) != len(set(units)) for entry, units in closures.items()):
        raise ValueError("incomplete read status source closure")
    names = sorted({name for units in closures.values() for name in units})
    if not all((ROOT / name).resolve().is_relative_to(ROOT) for name in names):
        raise ValueError("read status source closure escapes repository")
    return dict(units=closures[NATIVE_ENTRY], closures=closures,
                sources={name: captured[name].sha256 for name in names})


def run_native_section(producer, work, run, build_timeout, verify_inputs, *, parse_bytes=None):
    from frontend_native_process import inspect_image, verify_rejection
    from repo_support import sha256_file, write_json_atomic

    if os.name != "nt":
        return dict(status="unavailable", reason="Windows x86-64 runtime required")
    directory = work / "native-fs-read"
    directory.mkdir()
    before, producer_hash = native_source_snapshot(parse_bytes=parse_bytes), sha256_file(producer)
    report = dict(status="running", inputs=before, producer_sha256=producer_hash,
                  execution_backend="direct-windows-pe", external_supervisor="python")

    def unchanged():
        verify_inputs()
        if native_source_snapshot(parse_bytes=parse_bytes) != before or sha256_file(producer) != producer_hash:
            raise ValueError("read status source or producer changed")

    try:
        rejections = []
        for name, diagnostic, fallback in NATIVE_REJECTIONS:
            unchanged()
            entry = f"tests/native_managed/reject/source_file_read_status_{name}.ouro"
            output = directory / ("reject-" + name + ".exe")
            result = run("native-read-status-reject-" + name,
                         [str(producer), entry, output.relative_to(ROOT).as_posix(), *before["closures"][entry]], build_timeout)
            rejections.append(dict(case=name, diagnostic=verify_rejection(result, diagnostic, output, fallback)))
        report["rejections"] = rejections
        unchanged()
        output = directory / "source-file-read-status.exe"
        logical = output.relative_to(ROOT).as_posix()
        result = run("native-build-read-status", [str(producer), NATIVE_ENTRY, logical, *before["units"]], build_timeout)
        if not result.ok or result.stdout != logical + "\n":
            raise ValueError("read status native build failed")
        image = inspect_image(output, ("advapi32.dll", "bcrypt.dll", "kernel32.dll", "shell32.dll"),
                              {"kernel32.dll": ("CreateFileW", "ReadFile", "GetFileSizeEx", "CloseHandle")})
        report["image"] = image
        unchanged()
        observed = directory / "runtime"
        result = run("native-read-status-runtime", [sys.executable, "-B", str(Path(__file__).resolve()),
            "--driver", str(output), "--mode", "status", "--checked", "--out", str(observed)], 300)
        expected = "".join(f"FS_READ_OK {name}\n" for name in NATIVE_CASES)
        expected += f"FS_READ_SUITE: PASS checks={len(NATIVE_CASES)}\n"
        if not result.ok or result.stdout != expected or result.stderr:
            raise ValueError("read status native observer protocol failed")
        evidence = json.loads((observed / "report.json").read_text(encoding="utf-8"))
        expected_rows = [dict(name=name, exit=0 if name in ("empty-file", "complete-file", "unicode-path",
            "read-after-refusal", "reused-action") else 73 if name in ("empty-path", "nul-path", "malformed-utf8-path")
            else 1, status="pass") for name in NATIVE_CASES]
        if (evidence.get("kind") != "ouro.fs-read.v1" or evidence.get("complete") is not True
                or evidence.get("mode") != "status" or evidence.get("driver_sha256") != image["sha256"]
                or evidence.get("checks") != expected_rows):
            raise ValueError("read status native report is incomplete or stale")
        report["runtime"] = evidence
        report["bounded"] = {}
        run_native_bounded_section(producer, directory, run, build_timeout, before, unchanged, report["bounded"])
        unchanged()
        if sha256_file(output) != image["sha256"]:
            raise ValueError("read status native image changed")
        report["status"] = "passed"
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        write_json_atomic(directory / "report.json", report)
    return report


def bounded_law_output(name, laws):
    return "".join(f"PRECISION_OK fs-bounded/{law}\n" for law in laws) + f"PRECISION_SUITE {name} rows={len(laws)}\n"


def bounded_verify_receipt(receipt, probe, calls):
    if (not isinstance(receipt, dict) or receipt.get("kind") != "ouro.fs-bounded-inputs.v1"
            or receipt.get("sources") != native_source_snapshot()
            or receipt.get("large_contract") != bounded_large_contract()):
        raise ValueError("bounded read source closure is missing or stale")
    producer, images = receipt.get("producer"), receipt.get("images")
    if (not isinstance(producer, dict) or not isinstance(images, dict)
            or set(images) != set(BOUNDED_ENTRIES)):
        raise ValueError("bounded read producer/image inventory differs")
    if sha256_file(Path(producer["path"])) != producer.get("sha256"):
        raise ValueError("bounded read producer changed")
    for name, image in images.items():
        if (not isinstance(image, dict) or sha256_file(Path(image["path"])) != image.get("sha256")
                or (name in ("probe", "calls") and Path(image["path"]) != (probe if name == "probe" else calls))):
            raise ValueError("bounded read image changed or driver differs")


def bounded_verify_law_records(section):
    images, source = section["images"], section["inputs"]["sources"]
    producer = section["inputs"]["producer"]["path"]
    for name, entry in BOUNDED_ENTRIES.items():
        logical = Path(images[name]["path"]).relative_to(ROOT).as_posix()
        result = section["emissions"][name]
        if (result.get("status") != "ok" or type(result.get("returncode")) is not int or result["returncode"] != 0
                or result.get("stdout") != logical + "\n"
                or result.get("argv") != [producer, entry, logical, *source["closures"][entry]]):
            raise ValueError("bounded read emission record differs: " + name)
    for name, laws in (("pure", BOUNDED_PURE_LAWS), ("order", BOUNDED_ORDER_LAWS)):
        result = section[name]
        expected = bounded_law_output("fs-bounded" if name == "pure" else "fs-bounded-order", laws)
        if (result.get("status") != "ok" or type(result.get("returncode")) is not int or result["returncode"] != 0
                or result.get("argv") != [images[name]["path"]] or result.get("stdout") != expected or result.get("stderr") != ""):
            raise ValueError("bounded read law record differs: " + name)
    faults = section.get("faults")
    if not isinstance(faults, list) or len(faults) != len(BOUNDED_FAULTS):
        raise ValueError("bounded read cleanup inventory differs")
    for row, (mode, marker) in zip(faults, BOUNDED_FAULTS, strict=True):
        result = row.get("result", {})
        if (row.get("mode") != mode or result.get("status") != "ok" or type(result.get("returncode")) is not int
                or result["returncode"] != 73 or result.get("argv") != [images["order"]["path"], mode]
                or result.get("stdout") != "FS_BOUNDED_CLEANUP_REACHED " + marker + "\n" or result.get("stderr") != ""):
            raise ValueError("bounded read cleanup record differs: " + mode)


def verify_native_bounded_artifacts(section):
    bounded_verify_law_records(section)
    receipt_path = Path(section["receipt_path"])
    receipt_bytes = receipt_path.read_bytes()
    if sha256_bytes(receipt_bytes) != section["receipt_sha256"]:
        raise ValueError("bounded read input receipt changed")
    receipt = json.loads(decode_source_text(receipt_bytes))
    if receipt != section["inputs"]:
        raise ValueError("bounded read input receipt differs")
    images = receipt["images"]
    bounded_verify_receipt(receipt, Path(images["probe"]["path"]), Path(images["calls"]["path"]))
    evidence_path = Path(section["runtime_path"])
    evidence_bytes = evidence_path.read_bytes()
    if sha256_bytes(evidence_bytes) != section["runtime_sha256"]:
        raise ValueError("bounded read runtime receipt changed")
    evidence = json.loads(decode_source_text(evidence_bytes))
    bounded_verify_report(evidence, receipt, evidence_path.parent, Path(images["probe"]["path"]),
                          Path(images["calls"]["path"]))
    for row in evidence["checks"]:
        if row["input_path"] is not None and sha256_file(Path(row["input_path"])) != row["input_sha256_after"]:
            raise ValueError("bounded read input bytes changed after observation")
    link = evidence_path.parent / "files" / "reparse.bin"
    if not link.is_symlink() or os.readlink(link) != str(evidence_path.parent / "files" / "reparse-target.bin"):
        raise ValueError("bounded read final reparse input changed")


def run_native_bounded_section(producer, directory, run, build_timeout, before, unchanged, report):
    from frontend_native_process import inspect_image
    from repo_support import write_json_atomic

    report.update(status="running", images={}, emissions={})
    for name, entry in BOUNDED_ENTRIES.items():
        unchanged()
        output = directory / ("bounded-" + name + ".exe")
        logical = output.relative_to(ROOT).as_posix()
        result = run("native-build-bounded-read-" + name,
                     [str(producer), entry, logical, *before["closures"][entry]], build_timeout)
        report["emissions"][name] = asdict(result)
        if not result.ok or result.stdout != logical + "\n":
            raise ValueError("bounded read native build failed: " + name)
        symbols = ({"kernel32.dll": ("CreateFileW", "ReadFile", "GetFileSizeEx",
                                    "GetFileInformationByHandleEx", "CloseHandle")}
                   if name in ("probe", "calls") else None)
        report["images"][name] = dict(path=str(output), **inspect_image(
            output, ("advapi32.dll", "bcrypt.dll", "kernel32.dll", "shell32.dll"), symbols))
        unchanged()
        if name in ("pure", "order"):
            expected = bounded_law_output("fs-bounded" if name == "pure" else "fs-bounded-order",
                                          BOUNDED_PURE_LAWS if name == "pure" else BOUNDED_ORDER_LAWS)
            observed = run("native-bounded-read-" + name, [str(output)], 30)
            if not observed.ok or observed.stdout != expected or observed.stderr:
                raise ValueError("bounded read law output differs: " + name)
            report[name] = asdict(observed)
            if name == "order":
                report["faults"] = []
                for mode, marker in BOUNDED_FAULTS:
                    fault = run("native-bounded-read-" + mode, [str(output), mode], 30)
                    expected_fault = "FS_BOUNDED_CLEANUP_REACHED " + marker + "\n"
                    if (fault.status != "ok" or type(fault.returncode) is not int or fault.returncode != 73
                            or fault.stdout != expected_fault or fault.stderr):
                        raise ValueError("bounded read cleanup outcome differs: " + mode)
                    report["faults"].append(dict(mode=mode, result=asdict(fault)))
        unchanged()
    receipt = dict(kind="ouro.fs-bounded-inputs.v1", sources=before,
                   producer=dict(path=str(producer), sha256=sha256_file(producer)),
                   images=report["images"], large_contract=bounded_large_contract())
    receipt_path = directory / "bounded-inputs.json"
    write_json_atomic(receipt_path, receipt)
    report.update(inputs=receipt, receipt_path=str(receipt_path), receipt_sha256=sha256_file(receipt_path))
    runtime = directory / "bounded-runtime"
    images = report["images"]
    result = run("native-bounded-read-runtime", [sys.executable, "-B", str(Path(__file__).resolve()),
                 "--mode", "bounded", "--driver", images["probe"]["path"],
                 "--calls-driver", images["calls"]["path"], "--bounded-inputs", str(receipt_path),
                 "--out", str(runtime)], 300)
    expected = "".join(f"FS_BOUNDED_OK {name}\n" for name in BOUNDED_CASES)
    expected += f"FS_BOUNDED_SUITE: PASS checks={len(BOUNDED_CASES)}\n"
    if not result.ok or result.stdout != expected or result.stderr:
        raise ValueError("bounded read native observer protocol failed")
    evidence_path = runtime / "report.json"
    report.update(runtime_path=str(evidence_path), runtime_sha256=sha256_file(evidence_path))
    unchanged()
    verify_native_bounded_artifacts(report)
    report["status"] = "passed"


def bounded_case_specs(directory, probe, calls):
    files = directory / "files"
    binary, changed = b"A\0\xff", bytes((65, 0, 255, 128, 10, 13, 90))
    chunk = bytes(range(256)) * 256 + b"\xff"
    usage = b"usage: native-fs-bounded-probe PATH BYTE_CAP\n"
    # Each tuple fixes argv, whole result and the source-owned before/after bytes.
    def spec(name, driver, arguments, code, out=b"", err=b"", path=None, before=None, after=None):
        return dict(name=name, driver=driver, arguments=arguments, code=code, out=out, err=err,
                    path=path, before=before, after=before if after is None else after)
    tiny, large = files / "binary.bin", files / "chunk.bin"
    unicode_path = files / "каталог 漢字 🧪" / "путь пробелы.bin"
    missing, folder = files / "missing.bin", files / "directory"
    link, target = files / "reparse.bin", files / "reparse-target.bin"
    deferred, reused, recovery = (files / name for name in ("deferred.bin", "reuse.bin", "recovery.bin"))
    invalid = b"bounded file read: empty or NUL-containing path\n"
    return (
        spec("empty-zero", probe, [str(files / "empty.bin"), "0"], 0, path=files / "empty.bin", before=b""),
        spec("binary-exact", probe, [str(tiny), "3"], 0, binary, path=tiny, before=binary),
        spec("binary-high-cap", probe, [str(tiny), "18446744073709551616"], 0, binary, path=tiny, before=binary),
        spec("binary-zero-cap", probe, [str(tiny), "0"], 1, err=b"bounded file read: size 3 exceeds byte cap 0\n", path=tiny, before=binary),
        spec("binary-short-cap", probe, [str(tiny), "2"], 1, err=b"bounded file read: size 3 exceeds byte cap 2\n", path=tiny, before=binary),
        spec("chunk-exact", probe, [str(large), "65537"], 0, chunk, path=large, before=chunk),
        spec("chunk-short-cap", probe, [str(large), "65536"], 1, err=b"bounded file read: size 65537 exceeds byte cap 65536\n", path=large, before=chunk),
        spec("unicode-path", probe, [str(unicode_path), "7"], 0, changed, path=unicode_path, before=changed),
        spec("missing-file", probe, [str(missing), "3"], 1, err=b"bounded file read: open OS status=2\n"),
        spec("directory", probe, [str(folder), "3"], 1, err=b"bounded file read: open OS status=5\n"),
        spec("final-reparse", probe, [str(link), "3"], 1, err=b"bounded file read: directory or final reparse point\n", path=target, before=binary),
        spec("locked-file", probe, [str(tiny), "3"], 1, err=b"bounded file read: open OS status=32\n", path=tiny, before=binary),
        spec("empty-path", probe, ["", "0"], 1, err=invalid),
        spec("nul-path", calls, ["nul", str(tiny)], 0, path=tiny, before=binary),
        spec("malformed-utf8-path", calls, ["utf8", str(tiny)], 0, path=tiny, before=binary),
        spec("deferred-action", calls, ["deferred", str(deferred)], 0, changed, path=deferred, before=binary, after=changed),
        spec("reused-action", calls, ["reuse", str(reused)], 0, changed, path=reused, before=b"first", after=changed),
        spec("recovery", calls, ["recovery", str(recovery)], 0, b"U\0\xfe", path=recovery, before=binary, after=b"U\0\xfe"),
        spec("read-after-refusal", probe, [str(tiny), "3"], 0, binary, path=tiny, before=binary),
        spec("invalid-cap", probe, [str(tiny), "-1"], 2, err=usage, path=tiny, before=binary),
        spec("extra-argument", probe, [str(tiny), "3", "extra"], 2, err=usage, path=tiny, before=binary),
        spec("unknown-source-mode", calls, ["unknown", str(tiny)], 99, path=tiny, before=binary),
    )


def bounded_observation(spec, result):
    return dict(name=spec["name"], status="fail", argv=[str(spec["driver"]), *spec["arguments"]], cwd=str(ROOT),
                exit=result.returncode,
                stdout_hex=result.stdout.hex() if isinstance(result.stdout, bytes) else None,
                stderr_hex=result.stderr.hex() if isinstance(result.stderr, bytes) else None,
                expected_exit=spec["code"], expected_stdout_hex=spec["out"].hex(), expected_stderr_hex=spec["err"].hex(),
                input_path=str(spec["path"]) if spec["path"] is not None else None,
                input_sha256_before=hashlib.sha256(spec["before"]).hexdigest() if spec["before"] is not None else None,
                input_sha256_after=None,
                expected_input_sha256_after=hashlib.sha256(spec["after"]).hexdigest() if spec["after"] is not None else None)


def bounded_result_row(spec, result):
    if (type(result.returncode) is not int or result.returncode != spec["code"]
            or type(result.stdout) is not bytes or result.stdout != spec["out"]
            or type(result.stderr) is not bytes or result.stderr != spec["err"]):
        raise ValueError("bounded read whole result differs: " + spec["name"])
    row = bounded_observation(spec, result)
    return dict(row, status="pass", input_sha256_after=row["expected_input_sha256_after"])


def bounded_large_case_specs(directory, probe):
    payload = bytes(range(256)) * ((BOUNDED_LARGE_BYTES - 1) // 256) + b"\xff"
    path = directory / "files" / "large-binary.bin"
    return tuple(dict(name=name, driver=probe, arguments=[str(path), str(cap)], code=code,
                      out=out, err=err, path=path, before=payload, after=payload)
                 for name, cap, code, out, err in (
                     ("large-short-cap", BOUNDED_LARGE_BYTES - 1, 1, b"",
                      f"bounded file read: size {BOUNDED_LARGE_BYTES} exceeds byte cap {BOUNDED_LARGE_BYTES - 1}\n".encode()),
                     ("large-exact", BOUNDED_LARGE_BYTES, 0, payload, b"")))


def bounded_large_observation(spec, result, directory):
    raw = directory / "large-raw" / spec["name"]
    row = dict(name=spec["name"], status="fail", argv=[str(spec["driver"]), *spec["arguments"]], cwd=str(ROOT),
               exit=result.returncode, expected_exit=spec["code"], input_path=str(spec["path"]),
               input_sha256_before=hashlib.sha256(spec["before"]).hexdigest(), input_sha256_after=None,
               expected_input_sha256_after=hashlib.sha256(spec["after"]).hexdigest())
    for stream, expected in (("stdout", spec["out"]), ("stderr", spec["err"])):
        value = getattr(result, stream)
        row.update({stream + "_path": str(raw / (stream + ".bin")),
                    stream + "_bytes": len(value) if type(value) is bytes else None,
                    stream + "_sha256": hashlib.sha256(value).hexdigest() if type(value) is bytes else None,
                    "expected_" + stream + "_bytes": len(expected),
                    "expected_" + stream + "_sha256": hashlib.sha256(expected).hexdigest()})
    return row


def bounded_large_validate_result(spec, result):
    if (type(result.returncode) is not int or result.returncode != spec["code"]
            or type(result.stdout) is not bytes or result.stdout != spec["out"]
            or type(result.stderr) is not bytes or result.stderr != spec["err"]):
        raise ValueError("bounded large read whole result differs: " + spec["name"])


def bounded_verify_large_report(report, directory, probe):
    specs = bounded_large_case_specs(directory, probe)
    expected = [dict(bounded_large_observation(spec, subprocess.CompletedProcess([], spec["code"], spec["out"], spec["err"]),
                                               directory), status="pass",
                     input_sha256_after=hashlib.sha256(spec["after"]).hexdigest()) for spec in specs]
    rows = report.get("large_checks")
    integer_fields = ("exit", "expected_exit", "stdout_bytes", "stderr_bytes", "expected_stdout_bytes", "expected_stderr_bytes")
    if (not isinstance(rows, list) or any(not isinstance(row, dict)
            or any(type(row.get(key)) is not int for key in integer_fields) or not 0 <= row["exit"] <= 0xFFFFFFFF for row in rows)
            or rows != expected):
        raise ValueError("bounded large read runtime inventory or results differ")
    for row, spec in zip(rows, specs, strict=True):
        for stream in ("stdout", "stderr"):
            path = Path(row[stream + "_path"])
            if (path.read_bytes() != spec["out" if stream == "stdout" else "err"]
                    or sha256_file(path) != row[stream + "_sha256"]):
                raise ValueError("bounded large read raw bytes changed: " + spec["name"])
        if (spec["path"].read_bytes() != spec["after"]
                or sha256_file(spec["path"]) != row["input_sha256_after"]):
            raise ValueError("bounded large read input bytes changed: " + spec["name"])


def bounded_verify_report(report, receipt, directory, probe, calls):
    expected = [bounded_result_row(spec, subprocess.CompletedProcess([], spec["code"], spec["out"], spec["err"]))
                for spec in bounded_case_specs(directory, probe, calls)]
    checks = report.get("checks") if isinstance(report, dict) else None
    if (not isinstance(checks, list) or any(not isinstance(row, dict) or type(row.get("exit")) is not int
            or type(row.get("expected_exit")) is not int or not 0 <= row["exit"] <= 0xFFFFFFFF for row in checks)):
        raise ValueError("bounded read runtime rows have invalid status types")
    if (not isinstance(report, dict) or report.get("kind") != "ouro.fs-bounded-runtime.v1"
            or report.get("complete") is not True or report.get("inputs") != receipt
            or report.get("checks") != expected):
        raise ValueError("bounded read runtime inventory or results differ")
    bounded_verify_large_report(report, directory, probe)


def run_bounded_suite(probe, calls, output, inputs_path):
    from repo_support import write_json_atomic

    if os.name != "nt":
        raise ValueError("bounded public read requires actual Windows native images")
    receipt_bytes = inputs_path.read_bytes()
    receipt = json.loads(decode_source_text(receipt_bytes))
    receipt_hash = sha256_bytes(receipt_bytes)
    bounded_verify_receipt(receipt, probe, calls)
    output.mkdir()
    files = output / "files"
    files.mkdir()
    (files / "directory").mkdir()
    (files / "каталог 漢字 🧪").mkdir()
    report = dict(kind="ouro.fs-bounded-runtime.v1", complete=False, inputs=receipt, checks=[], large_checks=[])
    environment = dict(os.environ, PATH="")
    windows = WindowsMetadata()
    lock = None

    def record_large(spec, result, before_hash):
        raw = output / "large-raw" / spec["name"]
        raw.mkdir(parents=True)
        for stream in ("stdout", "stderr"):
            value = getattr(result, stream)
            if type(value) is bytes:
                (raw / (stream + ".bin")).write_bytes(value)
        row = bounded_large_observation(spec, result, output)
        row.update(input_sha256_before=before_hash, input_sha256_after=sha256_file(spec["path"]))
        report["large_checks"].append(row)
        return row

    try:
        for spec in bounded_case_specs(output, probe, calls):
            bounded_verify_receipt(receipt, probe, calls)
            if spec["path"] is not None:
                spec["path"].write_bytes(spec["before"])
            if spec["name"] == "final-reparse":
                os.symlink(spec["path"], files / "reparse.bin")
            if spec["name"] == "locked-file":
                lock = windows.open(str(spec["path"]), 0x80000000, 0, None, 3, 0x80, None)
                if lock == c.c_void_p(-1).value:
                    raise c.WinError(c.get_last_error())
            try:
                try:
                    result = subprocess.run([str(spec["driver"]), *spec["arguments"]], cwd=ROOT, env=environment,
                                            capture_output=True, timeout=30)
                except subprocess.TimeoutExpired as error:
                    partial = subprocess.CompletedProcess(error.cmd, None, error.stdout, error.stderr)
                    report["checks"].append(dict(bounded_observation(spec, partial), status="timeout", timeout_s=30))
                    if spec["path"] is not None:
                        report["checks"][-1]["input_sha256_after"] = sha256_file(spec["path"])
                    raise
                report["checks"].append(bounded_observation(spec, result))
                if spec["path"] is not None:
                    report["checks"][-1]["input_sha256_after"] = sha256_file(spec["path"])
            finally:
                if lock is not None:
                    checked(windows.close(lock))
                    lock = None
            row = bounded_result_row(spec, result)
            if spec["path"] is not None and spec["path"].read_bytes() != spec["after"]:
                raise ValueError("bounded read input bytes changed unexpectedly: " + spec["name"])
            row["input_sha256_after"] = report["checks"][-1]["input_sha256_after"]
            report["checks"][-1] = row
            print("FS_BOUNDED_OK " + spec["name"], flush=True)
        for spec in bounded_large_case_specs(output, probe):
            bounded_verify_receipt(receipt, probe, calls)
            spec["path"].write_bytes(spec["before"])
            before_hash = sha256_file(spec["path"])
            if before_hash != hashlib.sha256(spec["before"]).hexdigest():
                raise ValueError("bounded large read input changed before execution")
            try:
                result = subprocess.run([str(spec["driver"]), *spec["arguments"]], cwd=ROOT, env=environment,
                                        capture_output=True, timeout=30)
            except subprocess.TimeoutExpired as error:
                partial = subprocess.CompletedProcess(error.cmd, None, error.stdout, error.stderr)
                record_large(spec, partial, before_hash).update(status="timeout", timeout_s=30)
                raise
            row = record_large(spec, result, before_hash)
            bounded_large_validate_result(spec, result)
            if spec["path"].read_bytes() != spec["after"]:
                raise ValueError("bounded large read input bytes changed unexpectedly: " + spec["name"])
            row["status"] = "pass"
        bounded_verify_receipt(receipt, probe, calls)
        if sha256_file(inputs_path) != receipt_hash:
            raise ValueError("bounded read input receipt changed during execution")
        bounded_verify_report(dict(report, complete=True), receipt, output, probe, calls)
        report["complete"] = True
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        report["error"] = str(error)
        raise
    finally:
        write_json_atomic(output / "report.json", report)
    print(f"FS_BOUNDED_SUITE: PASS checks={len(report['checks'])}", flush=True)


def run_suite(driver: Path, output: Path, mode: str, *, checked_reader=False):
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "report.json"
    report_path.unlink(missing_ok=True)
    original_hash = hashlib.sha256(driver.read_bytes()).hexdigest()
    rows = []
    environment = dict(os.environ, PATH="")
    families = b""
    if checked_reader and (mode != "status" or os.name != "nt"):
        raise ValueError("checked read observation requires native Windows status mode")
    if mode == "drive":
        metadata = subprocess.run([str(driver), "--strict", "--enable-all", "--print-families"],
                                  cwd=ROOT, env=environment, capture_output=True, timeout=30)
        matched = re.fullmatch(rb"ANALYZE_FAMILIES families=([a-z_]+(?:,[a-z_]+)*)\r?\n", metadata.stdout)
        assert metadata.returncode == 0 and not metadata.stderr and matched, metadata
        families = matched.group(1)
        assert len(families.split(b",")) == len(set(families.split(b","))), "duplicate families"

    def run(name, path, *, content=None, invalid_nul=False, invalid_utf8=False):
        command = "--read-invalid-utf8-path" if invalid_utf8 else "--read-nul-path" if invalid_nul else "--read-file"
        if mode == "status":
            command = "--read-status-invalid-utf8-path" if invalid_utf8 else "--read-status-nul-path" if invalid_nul else "--read-status"
        arguments = ([command, str(path)] if mode in ("raw", "status")
                     else ["--strict", "--enable-all", "--scope", str(path)])
        result = subprocess.run([str(driver), *arguments], cwd=ROOT, env=environment,
                                capture_output=True, timeout=90)
        if content is None:
            terminal = mode == "status" and (invalid_nul or invalid_utf8 or str(path) == "")
            assert result.returncode != 0, (name, "unreadable input accepted", result.stdout, result.stderr)
            assert b"ANALYZE_DRIVE " not in result.stdout and (terminal or result.stderr), (name, "false completion", result)
            if mode == "raw":
                assert result.returncode == 73 and not result.stdout, (name, result)
            if mode == "status":
                assert result.returncode == (73 if terminal else 1) and not result.stdout, (name, result)
                if not terminal:
                    assert re.fullmatch(rb"read OS status=[1-9][0-9]*\r?\n", result.stderr), (name, result)
        else:
            assert result.returncode == 0 and not result.stderr, (name, result)
            if mode in ("raw", "status"):
                assert result.stdout == content, (name, "bytes differ")
            else:
                expected = b"ANALYZE_DRIVE files=1 findings=0 rejected=0 families=" + families + b"\n"
                assert result.stdout.replace(b"\r\n", b"\n") == expected, (name, result.stdout)
        rows.append(dict(name=name, exit=result.returncode, status="pass"))
        print(f"FS_READ_OK {name}", flush=True)

    def checked_read(name, path, expected):
        result = subprocess.run([str(driver), "--read-checked", str(path)], cwd=ROOT, env=environment,
                                capture_output=True, timeout=30)
        assert result.returncode == 1 and not result.stdout and result.stderr.replace(b"\r\n", b"\n") == expected, (name, result)
        rows.append(dict(name=name, exit=1, status="pass"))
        print(f"FS_READ_OK {name}", flush=True)

    with tempfile.TemporaryDirectory(prefix="read-", dir=output) as temporary:
        directory = Path(temporary)
        source = directory / "input.ouro"
        source.write_bytes(b"")
        run("empty-file", source, content=b"")
        content = (bytes(range(256)) * 32768 if mode in ("raw", "status") else
                   b"inductive Nat : Type := | Z : Nat;\ndef retained_value : Nat := Z;\n")
        source.write_bytes(content)
        run("complete-file", source, content=content)
        run("missing-file", directory / "missing.ouro")
        empty_directory = directory / "empty"
        empty_directory.mkdir()
        run("empty-directory", empty_directory)
        run("empty-path", "")
        if mode == "status":
            run("nul-path", source, invalid_nul=True)
            unicode_directory = directory / "каталог 漢字 🧪"
            unicode_directory.mkdir()
            unicode_source = unicode_directory / "путь пробелы.ouro"
            unicode_source.write_bytes(b"unicode source\0bytes\xff\n")
            run("unicode-path", unicode_source, content=unicode_source.read_bytes())
            if os.name == "nt":
                run("malformed-utf8-path", unicode_source, invalid_utf8=True)
            removed = directory / "deferred.bin"
            removed.write_bytes(b"constructed before removal\0\xff")
            result = subprocess.run([str(driver), "--read-deferred-status", str(removed)], cwd=ROOT,
                                    env=environment, capture_output=True, timeout=30)
            assert result.returncode == 1 and not result.stdout and not removed.exists(), result
            assert re.fullmatch(rb"read OS status=[1-9][0-9]*\r?\n", result.stderr), result
            rows.append(dict(name="deferred-removal", exit=1, status="pass"))
            print("FS_READ_OK deferred-removal", flush=True)
        if checked_reader:
            missing = directory / "missing.ouro"
            checked_read("checked-missing-file", missing, b"path not found: " + str(missing).encode("utf-8") + b"\n")
        if mode == "raw":
            run("nul-path", source, invalid_nul=True)
            arguments = ["", "plain", "two words", 'quote"inside', "back\\slash", "ends\\", "путь 漢字 🧪"]
            result = subprocess.run([str(driver), "--host-arguments", *arguments], cwd=ROOT,
                                    env=environment, capture_output=True, timeout=30)
            assert result.returncode == 0 and not result.stderr, result
            assert result.stdout == b"".join(value.encode("utf-8") + b"\0" for value in arguments), result
            rows.append(dict(name="host-arguments", exit=0, status="pass"))
            unicode_directory = directory / "каталог 漢字 🧪"
            unicode_directory.mkdir()
            unicode_source = unicode_directory / "путь \u0441 пробелами.ouro"
            unicode_content = b"unicode source\0bytes\xff\n"
            unicode_source.write_bytes(unicode_content)
            run("unicode-path", unicode_source, content=unicode_content)
            if os.name == "nt":
                run("malformed-utf8-path", unicode_source, invalid_utf8=True)
                for name, path, command, expected in (
                    ("unicode-file-info", unicode_source, "--path-info", b"exists=1 directory=0\n"),
                    ("unicode-directory-info", unicode_directory, "--path-info", b"exists=1 directory=1\n"),
                    ("unicode-missing-info", unicode_directory / "absent", "--path-info", b"exists=0 directory=0\n"),
                    ("nul-path-info", unicode_source, "--path-info-nul", b"exists=0 directory=0\n"),
                    ("malformed-utf8-info", unicode_source, "--path-info-invalid-utf8", b"exists=0 directory=0\n"),
                ):
                    result = subprocess.run([str(driver), command, str(path)], cwd=ROOT, env=environment,
                                            capture_output=True, timeout=30)
                    assert result.returncode == 0 and not result.stderr, (name, result)
                    assert result.stdout.replace(b"\r\n", b"\n") == expected, (name, result)
                    rows.append(dict(name=name, exit=0, status="pass"))
        if os.name == "nt":
            windows = WindowsMetadata()
            lock = windows.open(str(source), 0x80000000, 0, None, 3, 0x80, None)
            if lock == c.c_void_p(-1).value:
                raise c.WinError(c.get_last_error())
            try:
                run("locked-file", source)
                if checked_reader:
                    checked_read("checked-locked-file", source,
                                 b"filesystem read OS status=32 failed: " + str(source).encode("utf-8") + b"\n")
            finally:
                checked(windows.close(lock))
        else:
            print("FS_READ_UNAVAILABLE locked-file: Windows sharing-mode contract", flush=True)
        assert source.read_bytes() == content, "read attempt changed input"
        run("read-after-refusal", source, content=content)
        if checked_reader:
            source.write_bytes(b"first")
            result = subprocess.run([str(driver), "--read-reuse-status", str(source)], cwd=ROOT,
                                    env=environment, capture_output=True, timeout=30)
            expected = bytes((65, 0, 255, 128, 10, 13, 90))
            assert result.returncode == 0 and result.stdout == expected and not result.stderr, result
            assert source.read_bytes() == expected, "reused action did not read current bytes"
            rows.append(dict(name="reused-action", exit=0, status="pass"))
            print("FS_READ_OK reused-action", flush=True)
    if hashlib.sha256(driver.read_bytes()).hexdigest() != original_hash:
        raise ValueError("read driver changed during execution")
    report_path.write_text(json.dumps(dict(kind="ouro.fs-read.v1", complete=True, mode=mode,
        driver_sha256=original_hash, checks=rows), indent=2) + "\n", encoding="utf-8")
    print(f"FS_READ_SUITE: PASS checks={len(rows)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--driver", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mode", choices=("raw", "status", "drive", "stdin", "bounded"), required=True)
    parser.add_argument("--checked", action="store_true")
    parser.add_argument("--calls-driver", type=Path)
    parser.add_argument("--bounded-inputs", type=Path)
    parser.add_argument("--producer", type=Path)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--record-inputs", action="store_true")
    args = parser.parse_args()
    if args.mode == "bounded":
        if (args.calls_driver is None or args.bounded_inputs is None or args.checked
                or args.producer is not None or args.inputs is not None or args.record_inputs):
            parser.error("bounded requires --calls-driver and --bounded-inputs without other mode options")
        run_bounded_suite(args.driver.resolve(), args.calls_driver.resolve(), args.out.resolve(),
                          args.bounded_inputs.resolve())
        return
    if args.calls_driver is not None or args.bounded_inputs is not None:
        parser.error("bounded input options require --mode bounded")
    if args.mode == "stdin":
        if args.producer is None or args.inputs is None or args.checked:
            parser.error("stdin requires --producer and --inputs, without --checked")
        if args.record_inputs:
            record = stdin_inputs(args.producer, args.driver)
            stdin_write_record(args.inputs, record)
            sys.stdout.reconfigure(encoding="utf-8", newline="\n")
            print(record["producer"]["path"])
        else:
            run_stdin_suite(args.driver.resolve(), args.out.resolve(), args.inputs.resolve(), args.producer)
        return
    if args.producer is not None or args.inputs is not None or args.record_inputs:
        parser.error("stdin input options require --mode stdin")
    run_suite(args.driver.resolve(), args.out.resolve(), args.mode, checked_reader=args.checked)


if __name__ == "__main__":
    main()
