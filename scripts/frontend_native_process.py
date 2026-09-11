#!/usr/bin/env python3
"""Direct-PE process acceptance owned by frontend_host_suite, with Python supervision.

The native fixture owns API assertions. This observer preserves raw output bytes
and holds descendant process handles before cancellation. It never supplies a C
law receipt as evidence of a Windows image, and never builds a second producer.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time

from frontend_regen import collect_units
from repo_support import sha256_file, write_json_atomic

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
)
MODES = ("basic", "stdin", "reuse", "deferred", "timeout", "stdout-cap", "stderr-cap",
         "negative73", "missing", "invalid", "oversized", "tree-timeout", "hard-terminate")
IMPORTS = {API: ("advapi32.dll", "bcrypt.dll", "kernel32.dll", "shell32.dll"),
           CAPTURE: ("advapi32.dll", "bcrypt.dll", "kernel32.dll", "shell32.dll"),
           DENIED: ("kernel32.dll",)}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def rejection_entry(name):
    return f"tests/native_managed/reject/source_process_bounded_{name}.ouro"


def source_snapshot():
    entries = (API, CAPTURE, DENIED, *(rejection_entry(name) for name, _, _ in REJECTIONS))
    closures = {entry: collect_units(entry) for entry in entries}
    for entry, units in closures.items():
        require(units and units[-1] == entry and len(units) == len(set(units)),
                f"incomplete native process source closure: {entry}")
    names = sorted({name for units in closures.values() for name in units})
    require(all((ROOT / name).resolve().is_relative_to(ROOT) for name in names),
            "native process source escapes the repository")
    return {"closures": closures, "sources": {name: sha256_file(ROOT / name) for name in names}}


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


def verify_api_result(result):
    expected = "".join(f"ok {name}\n" for name in API_CASES)
    require(result.status == "ok" and result.returncode == 0
            and result.stdout == expected and result.stderr == "",
            "native process API laws have wrong status, count, order, output, or diagnostics")


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
    result = {"sha256": sha256_file(path), "bytes": len(image), "machine": "x86_64", "imports": sorted(imports)}
    if required_symbols is not None:
        require(all(set(names).issubset(symbols.get(library, [])) for library, names in required_symbols.items()),
                "native PE required import symbols are missing")
        result["import_symbols"] = symbols
    return result


def run_section(producer, work, run, build_timeout, probe_timeout, verify_inputs):
    if os.name != "nt":
        return {"kind": KIND, "status": "unavailable", "reason": "Windows x86-64 runtime required",
                "native_bootstrap": False, "rows": [], "helper_rejections": []}
    directory = work / "native-process"
    directory.mkdir()
    before = source_snapshot()
    pinned_producer = sha256_file(producer)
    binaries = {}
    report = {"kind": KIND, "status": "running", "execution_backend": "direct-windows-pe",
              "external_supervisor": "python", "native_bootstrap": False,
              "producer": str(producer), "producer_sha256": pinned_producer,
              "inputs": before, "binaries": binaries, "helper_rejections": []}

    def unchanged():
        verify_inputs()
        require(source_snapshot() == before and sha256_file(producer) == pinned_producer,
                "native process sources or producer changed")
        for entry, row in binaries.items():
            require(inspect_image(ROOT / row["path"], IMPORTS[entry]) == row["image"],
                    "native process image changed: " + entry)

    try:
        for entry in (API, CAPTURE, DENIED):
            unchanged()
            output = directory / (Path(entry).stem + ".exe")
            logical = output.relative_to(ROOT).as_posix()
            result = run("native-build-" + output.stem,
                         [str(producer), entry, logical, *before["closures"][entry]], build_timeout)
            require(result.ok and result.stdout == logical + "\n", "direct native process build failed: " + entry)
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
        result = run("native-process-runtime", command, max(300, 13 * probe_timeout))
        require(result.ok and result.stdout == "FRONTEND_NATIVE_PROCESS: PASS cases=13\n" and not result.stderr,
                "native process runtime observer failed")
        evidence = json.loads((observed / "report.json").read_text(encoding="utf-8"))
        verify_runtime_report(evidence, binaries[CAPTURE]["image"]["sha256"], binaries[DENIED]["image"]["sha256"])
        report["runtime"] = evidence
        unchanged()
        report["status"] = "passed"
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        write_json_atomic(directory / "report.json", report)
    return report


def verify_runtime_report(report, binary_sha256, denied_sha256):
    require(report.get("kind") == KIND + ".runtime" and report.get("status") == "passed"
            and report.get("binary_sha256") == binary_sha256 and report.get("denied_sha256") == denied_sha256
            and report.get("binaries_unchanged") is True, "native runtime receipt is incomplete or stale")
    rows = report.get("rows", [])
    require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows), "native runtime rows are malformed")
    require([row.get("case") for row in rows] == list(MODES), "native runtime cases missing, reordered, or duplicated")
    for row in rows:
        mode = row["case"]
        require(type(row.get("exit")) is int, "native runtime exit is not an integer")
        if mode == "hard-terminate":
            require(row.get("exit") == 1 and row.get("stdout_hex") == "", "native parent cancellation protocol differs")
        else:
            require(row.get("exit") == 42 and row.get("stdout_hex") == f"CAPTURE_OK {mode}\n".encode().hex(),
                    "native process byte protocol differs: " + mode)
        require(row.get("stderr_hex") == "", "native process stderr is not empty: " + mode)
        if mode in {"tree-timeout", "hard-terminate"}:
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


def observe_tree(binary, work, cancel):
    work.mkdir()
    api = kernel()
    owned = []
    child = None
    mode = "hard-terminate" if cancel else "tree-timeout"
    try:
        with (work / "stdout").open("wb") as output, (work / "stderr").open("wb") as error:
            markers = [work / "branch.pid", work / "leaf.pid"]
            child = subprocess.Popen([str(binary), "--tree" if cancel else "--tree-timeout", *map(str, markers)],
                                     cwd=work, stdin=subprocess.DEVNULL, stdout=output, stderr=error)
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
        expected = b"" if cancel else b"CAPTURE_OK tree-timeout\n"
        require(code == (1 if cancel else 42) and stdout == expected and stderr == b"", "native tree byte protocol differs")
        return {"case": mode, "exit": code, "stdout_hex": stdout.hex(), "stderr_hex": stderr.hex(),
                "parent_pid": child.pid, "descendant_pids": pids, "alive_before_observation": True,
                "held_handles_signaled": True}
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
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--binary-sha256", required=True)
    parser.add_argument("--denied", type=Path, required=True)
    parser.add_argument("--denied-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    require(os.name == "nt", "native process observer requires Windows")
    binary, denied, work = args.binary.resolve(strict=True), args.denied.resolve(strict=True), args.out.resolve()
    require(all(path.is_relative_to(ROOT) for path in (binary, denied, work)), "native probe path escapes repository")
    work.mkdir(parents=True, exist_ok=False)
    report = {"kind": KIND + ".runtime", "status": "running", "rows": [],
              "binary_sha256": args.binary_sha256, "denied_sha256": args.denied_sha256, "binaries_unchanged": False}

    def unchanged():
        require(sha256_file(binary) == args.binary_sha256 and sha256_file(denied) == args.denied_sha256,
                "native runtime input image changed")

    try:
        unchanged()
        for mode in MODES[:11]:
            report["rows"].append(checked_run(binary, work, mode, [denied] if mode == "oversized" else []))
            unchanged()
        for cancel in (False, True):
            report["rows"].append(observe_tree(binary, work / ("hard-terminate" if cancel else "tree-timeout"), cancel))
            unchanged()
        report["binaries_unchanged"] = True
        report["status"] = "passed"
        verify_runtime_report(report, args.binary_sha256, args.denied_sha256)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        write_json_atomic(work / "report.json", report)
    print("FRONTEND_NATIVE_PROCESS: PASS cases=13")


if __name__ == "__main__":
    main()
