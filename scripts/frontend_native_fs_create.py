#!/usr/bin/env python3
"""Exclusive-directory native acceptance owned by the fresh frontend host suite.

The source-owned probe contains fault assertions. This observer retains the
atomic two-contender race, exact bytes and filesystem readbacks, and uses the
existing bounded process supervisor. It never constructs another producer.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from frontend_native_process import inspect_image, require
from frontend_regen import collect_units
from kernel_scale import pin_one_cpu
from ourosmith.limits import clean_env, run_limited
from repo_support import sha256_file, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
KIND = "ouro.frontend-native-fs-create.v1"
API = "tests/native_fs_create_dir_tests.ouro"
PROBE = "tests/native_fs_create_dir_probe.ouro"
API_CASES = (
    "empty-path", "path-nul-prefix", "path-nul-middle", "path-nul-suffix",
    "exact-input-capacity", "input-too-long", "unicode-byte-count", "wide-zero",
    "wide-last-terminated", "wide-at-capacity", "wide-over-capacity", "create-success-owns",
    "create-refusal-never-owns", "successful-release-keeps-success", "successful-release-keeps-refusal",
    "cleanup-retains-created-claim", "cleanup-retains-create-refusal", "cleanup-retains-conversion-failure",
    "cleanup-claim-survives-another-cleanup-error",
)
IMPORTS = ("advapi32.dll", "bcrypt.dll", "kernel32.dll", "shell32.dll")
KERNEL_SYMBOLS = {"kernel32.dll": ("CreateDirectoryW", "MultiByteToWideChar", "VirtualAlloc", "VirtualFree")}
REFUSED = b"FS_CREATE_REFUSED fs_create_dir_create created=0\n"
READY = b"FS_CREATE_READY\n"
FAULTS = ("nul", "utf8-overlong", "utf8-surrogate", "utf8-truncated", "allocation-failure",
          "cleanup-created", "cleanup-refused", "cleanup-conversion")
CASES = ("positive", "duplicate-directory", "duplicate-file", "missing-parent-case",
         *("fault-" + mode for mode in FAULTS), "race-A", "race-B")


def source_snapshot():
    closures = {entry: collect_units(entry) for entry in (API, PROBE)}
    for entry, units in closures.items():
        require(units and units[-1] == entry and len(units) == len(set(units)),
                "incomplete exclusive-directory source closure: " + entry)
    names = sorted({name for units in closures.values() for name in units})
    require(all((ROOT / name).resolve().is_relative_to(ROOT) for name in names),
            "exclusive-directory source escapes the repository")
    return {"closures": closures, "sources": {name: sha256_file(ROOT / name) for name in names}}


def inspect_entry(path, entry):
    return inspect_image(path, IMPORTS, KERNEL_SYMBOLS if entry == PROBE else None)


def verify_api_result(result):
    expected = "".join(f"PRECISION_OK fs-create-dir/{name}\n" for name in API_CASES)
    expected += "PRECISION_SUITE fs-create-dir rows=19\n"
    require(result.status == "ok" and type(result.returncode) is int and result.returncode == 0
            and result.stdout == expected and result.stderr == "",
            "exclusive-directory API laws have incomplete or incorrect output/status")


def read_small(path):
    with path.open("rb") as stream:
        data = stream.read(1024 * 1024 + 1)
    require(len(data) <= 1024 * 1024, "fixture output exceeds 1 MiB")
    return data


def readbacks(output):
    return {
        "positive_owner_hex": read_small(output / "created parent with spaces" / "Каталог 雪😀" / "claim.owner").hex(),
        "existing_file_hex": read_small(output / "existing-file").hex(),
        "missing_parent_exists": (output / "missing-parent").exists(),
        "faults_exist": {mode: (output / ("target-" + mode)).exists() for mode in FAULTS},
        "cleanup_refused_hex": read_small(output / "target-cleanup-refused" / "existing.bin").hex(),
        "race_owner_hex": read_small(output / "race-target" / "claim.owner").hex(),
    }


def verify_runtime_report(report, binary_sha256):
    require(report.get("kind") == KIND + ".runtime" and report.get("pass") is True
            and report.get("native_executed") is True and report.get("image_unchanged") is True
            and report.get("image_sha256") == binary_sha256,
            "exclusive-directory runtime receipt is incomplete or stale")
    rows = report.get("cases", [])
    require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows)
            and [row.get("case") for row in rows] == list(CASES),
            "exclusive-directory cases are missing, reordered, or duplicated")
    winner = report.get("race_winner")
    require(winner in {"A", "B"} and report.get("race_both_observed_absence") is True,
            "exclusive-directory race has no observed absence barrier or winner")
    for row in rows:
        case = row["case"]
        code, stdout = 3, REFUSED
        if case == "positive":
            code, stdout = 0, b"FS_CREATE_CLAIM owner-A\n"
        elif case.startswith("fault-"):
            code, stdout = 0, f"FS_CREATE_FAULT_OK {case[6:]}\n".encode("ascii")
        elif case.startswith("race-"):
            token = case[-1]
            code = 0 if token == winner else 3
            stdout = READY + (f"FS_CREATE_CLAIM {token}\n".encode("ascii") if code == 0 else REFUSED)
        require(type(row.get("returncode")) is int and row["returncode"] == code
                and row.get("stdout_hex") == stdout.hex() and row.get("stderr_hex") == ""
                and row.get("stdout_sha256") == hashlib.sha256(stdout).hexdigest()
                and row.get("stdout_exact") is True and row.get("stderr_empty") is True
                and row.get("image_unchanged") is True and row.get("pass") is True,
                "exclusive-directory byte/status protocol differs: " + case)
    expected = {"positive_owner_hex": b"owner-A".hex(), "existing_file_hex": b"existing\x00file\xff".hex(),
                "missing_parent_exists": False,
                "faults_exist": {mode: mode in {"cleanup-created", "cleanup-refused"} for mode in FAULTS},
                "cleanup_refused_hex": b"prior-owner\x00\xff".hex(), "race_owner_hex": winner.encode("ascii").hex()}
    require(json.dumps(report.get("readbacks"), sort_keys=True) == json.dumps(expected, sort_keys=True),
            "exclusive-directory filesystem readbacks differ")


def verify_supervisor_report(report, binary_sha256):
    cpu = report.get("cpu", [])
    result = report.get("supervisor", {})
    require(report.get("kind") == KIND + ".supervisor" and report.get("pass") is True
            and isinstance(cpu, list) and len(cpu) == 1 and type(cpu[0]) is int and cpu[0] >= 0
            and report.get("image", {}).get("sha256") == binary_sha256,
            "exclusive-directory supervisor identity or CPU evidence differs")
    for field, expected in (("workers", 1), ("race_contenders", 2), ("shared_memory_mib", 768), ("suite_timeout_s", 240)):
        require(type(report.get(field)) is int and report[field] == expected,
                "exclusive-directory worker policy differs: " + field)
    require(result.get("status") == "ok" and type(result.get("returncode")) is int and result["returncode"] == 0
            and result.get("stdout") == "" and result.get("stderr") == "",
            "exclusive-directory worker status or output differs")


def run_section(producer, work, run, build_timeout, probe_timeout, verify_inputs):
    if os.name != "nt":
        return {"kind": KIND, "status": "unavailable", "reason": "Windows x86-64 runtime required",
                "native_bootstrap": False}
    directory = work / "native-fs-create"
    directory.mkdir()
    before = source_snapshot()
    producer_sha256 = sha256_file(producer)
    binaries = {}
    report = {"kind": KIND, "status": "running", "execution_backend": "direct-windows-pe",
              "external_supervisor": "python", "native_bootstrap": False,
              "producer": str(producer), "producer_sha256": producer_sha256,
              "inputs": before, "binaries": binaries}

    def unchanged():
        verify_inputs()
        require(source_snapshot() == before and sha256_file(producer) == producer_sha256,
                "exclusive-directory sources or producer changed")
        for entry, row in binaries.items():
            require(inspect_entry(ROOT / row["path"], entry) == row["image"],
                    "exclusive-directory image changed: " + entry)

    try:
        for entry in (API, PROBE):
            unchanged()
            output = directory / (Path(entry).stem + ".exe")
            logical = output.relative_to(ROOT).as_posix()
            result = run("native-build-" + output.stem,
                         [str(producer), entry, logical, *before["closures"][entry]], build_timeout)
            require(result.ok and result.stdout == logical + "\n", "exclusive-directory native build failed: " + entry)
            binaries[entry] = {"path": logical, "image": inspect_entry(output, entry)}
            unchanged()
        result = run("native-fs-create-api-laws", [str(ROOT / binaries[API]["path"])], probe_timeout)
        verify_api_result(result)
        report["api_laws"] = {"status": "passed", "entry": API, "cases": list(API_CASES),
                              "binary_sha256": binaries[API]["image"]["sha256"], "exit": result.returncode,
                              "stdout": result.stdout, "stderr": result.stderr}
        unchanged()
        observed = directory / "runtime"
        command = [sys.executable, "-B", str(Path(__file__).resolve()), "--binary", binaries[PROBE]["path"],
                   "--binary-sha256", binaries[PROBE]["image"]["sha256"], "--out", str(observed)]
        result = run("native-fs-create-runtime", command, 300)
        require(result.ok and result.stdout == "FRONTEND_NATIVE_FS_CREATE: PASS cases=14\n" and not result.stderr,
                "exclusive-directory native runtime observer failed")
        evidence = json.loads((observed / "native-report.json").read_text(encoding="utf-8"))
        verify_runtime_report(evidence, binaries[PROBE]["image"]["sha256"])
        require(readbacks(observed) == evidence["readbacks"], "exclusive-directory readbacks changed after observation")
        report["runtime"] = evidence
        report["supervisor"] = json.loads((observed / "report.json").read_text(encoding="utf-8"))
        verify_supervisor_report(report["supervisor"], binaries[PROBE]["image"]["sha256"])
        unchanged()
        report["status"] = "passed"
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        write_json_atomic(directory / "report.json", report)
    return report

def worker(args):
    output = args.out.resolve(strict=True)
    image = args.binary
    expected_hash = args.binary_sha256
    report = {"kind": KIND + ".runtime", "pass": False, "native_executed": False,
              "native_bootstrap": False, "source_lineage_confirmed": False,
              "image_sha256": expected_hash, "cases": []}
    children = []

    def start(label, command, *, gated=False):
        if sha256_file(image) != expected_hash:
            raise ValueError("native image changed before a case")
        directory = output / label
        directory.mkdir()
        stdout = (directory / "stdout.bin").open("xb")
        stderr = (directory / "stderr.bin").open("xb")
        try:
            proc = subprocess.Popen([str(image), *command], executable=str(image), cwd=output,
                stdin=subprocess.PIPE if gated else subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        except BaseException:
            stdout.close()
            stderr.close()
            raise
        entry = {"label": label, "directory": directory, "proc": proc, "stdout": stdout, "stderr": stderr,
                 "started": time.perf_counter(), "command": [str(image), *command]}
        children.append(entry)
        report["native_executed"] = True
        return entry

    def wait(entries):
        deadline = time.perf_counter() + 20
        while any(entry["proc"].poll() is None for entry in entries):
            for entry in entries:
                read_small(entry["directory"] / "stdout.bin")
                read_small(entry["directory"] / "stderr.bin")
            if time.perf_counter() >= deadline:
                raise TimeoutError("native case did not finish within 20 seconds")
            time.sleep(0.01)

    def finish(entry, expected_code, expected_stdout):
        entry["stdout"].close()
        entry["stderr"].close()
        stdout = read_small(entry["directory"] / "stdout.bin")
        stderr = read_small(entry["directory"] / "stderr.bin")
        row = {"case": entry["label"], "command": entry["command"], "returncode": entry["proc"].returncode,
               "expected_returncode": expected_code, "stdout_exact": stdout == expected_stdout,
               "stderr_empty": stderr == b"", "image_unchanged": sha256_file(image) == expected_hash,
               "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
               "stdout_hex": stdout.hex(), "stderr_hex": stderr.hex(),
               "elapsed_s": time.perf_counter() - entry["started"]}
        row["pass"] = row["returncode"] == expected_code and row["stdout_exact"] and row["stderr_empty"] and row["image_unchanged"]
        report["cases"].append(row)
        write_json_atomic(output / "native-report.json", report)
        if not row["pass"]:
            raise ValueError("native case failed: " + entry["label"])
        return row

    def one(label, command, code, stdout):
        entry = start(label, command)
        wait([entry])
        return finish(entry, code, stdout)

    try:
        parent = output / "created parent with spaces"
        parent.mkdir()
        target = parent / "Каталог 雪😀"
        one("positive", ["create", str(target), "owner-A"], 0, b"FS_CREATE_CLAIM owner-A\n")
        marker = target / "claim.owner"
        if marker.read_bytes() != b"owner-A":
            raise ValueError("successful owner marker differs")
        one("duplicate-directory", ["create", str(target), "owner-B"], 3, REFUSED)
        if marker.read_bytes() != b"owner-A":
            raise ValueError("duplicate claimant changed the winner's marker")
        existing_file = output / "existing-file"
        existing_bytes = b"existing\x00file\xff"
        existing_file.write_bytes(existing_bytes)
        one("duplicate-file", ["create", str(existing_file), "owner-C"], 3, REFUSED)
        if existing_file.read_bytes() != existing_bytes:
            raise ValueError("existing file bytes changed")
        missing_parent = output / "missing-parent"
        one("missing-parent-case", ["create", str(missing_parent / "final"), "owner-D"], 3, REFUSED)
        if missing_parent.exists():
            raise ValueError("exclusive final create recursively created parents")
        for mode in FAULTS:
            target = output / ("target-" + mode)
            sentinel = target / "existing.bin"
            if mode == "cleanup-refused":
                target.mkdir()
                sentinel.write_bytes(b"prior-owner\x00\xff")
            one("fault-" + mode, ["fault", mode, str(target)], 0,
                ("FS_CREATE_FAULT_OK " + mode + "\n").encode("ascii"))
            expected_exists = mode in {"cleanup-created", "cleanup-refused"}
            if target.exists() != expected_exists:
                raise ValueError("fault changed the directory creation outcome: " + mode)
            if mode == "cleanup-refused" and sentinel.read_bytes() != b"prior-owner\x00\xff":
                raise ValueError("cleanup after refusal changed the previous owner's contents")
        target = output / "race-target"
        a = start("race-A", ["race", str(target), "A"], gated=True)
        b = start("race-B", ["race", str(target), "B"], gated=True)
        deadline = time.perf_counter() + 20
        while True:
            ready = [read_small(entry["directory"] / "stdout.bin") for entry in (a, b)]
            require(all(read_small(entry["directory"] / "stderr.bin") == b"" for entry in (a, b)),
                    "race contender wrote unexpected stderr before release")
            if ready == [READY, READY]:
                break
            if any(entry["proc"].poll() is not None for entry in (a, b)) or time.perf_counter() >= deadline:
                raise ValueError("both contenders did not observe absence and reach the barrier")
            time.sleep(0.01)
        if target.exists():
            raise ValueError("race target appeared before the barrier was released")
        for entry in (a, b):
            entry["proc"].stdin.write(b"GO\n")
            entry["proc"].stdin.flush()
            entry["proc"].stdin.close()
        wait([a, b])
        codes = [entry["proc"].returncode for entry in (a, b)]
        if sorted(codes) != [0, 3]:
            raise ValueError("race requires exactly one successful creator and one refusal: " + repr(codes))
        winner = "A" if codes[0] == 0 else "B"
        for entry, token in ((a, "A"), (b, "B")):
            code = 0 if token == winner else 3
            expected = READY + (("FS_CREATE_CLAIM " + token + "\n").encode("ascii") if code == 0 else REFUSED)
            finish(entry, code, expected)
        if (target / "claim.owner").read_bytes() != winner.encode("ascii"):
            raise ValueError("race loser published over the successful creator")
        report["race_winner"] = winner
        report["race_both_observed_absence"] = True
        report["readbacks"] = readbacks(output)
        report["pass"] = True
    except BaseException as error:
        report["error"] = type(error).__name__ + ": " + str(error)
        raise
    else:
        return 0
    finally:
        for entry in children:
            proc = entry["proc"]
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=2)
            entry["stdout"].close()
            entry["stderr"].close()
        report["image_unchanged"] = image.is_file() and sha256_file(image) == expected_hash
        write_json_atomic(output / "native-report.json", report)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--binary-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args(argv)
    require(os.name == "nt", "exclusive-directory native acceptance requires Windows")
    args.binary = args.binary.resolve(strict=True)
    args.out = args.out.resolve()
    require(args.binary.is_relative_to(ROOT) and args.out.is_relative_to(ROOT),
            "exclusive-directory acceptance paths must remain inside the repository")
    inspected = inspect_entry(args.binary, PROBE)
    require(inspected["sha256"] == args.binary_sha256, "exclusive-directory image hash differs")
    if args.worker:
        return worker(args)
    args.out.mkdir(parents=True, exist_ok=False)
    cpu = pin_one_cpu()
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "--binary", str(args.binary),
               "--binary-sha256", args.binary_sha256, "--out", str(args.out), "--worker"]
    result = run_limited(command, timeout_s=240, memory_mb=768, cwd=ROOT, env=clean_env())
    report = {"kind": KIND + ".supervisor", "pass": False, "cpu": cpu, "workers": 1,
              "race_contenders": 2, "shared_memory_mib": 768, "suite_timeout_s": 240,
              "image": inspected, "supervisor": asdict(result)}
    try:
        require(result.ok and result.stdout == "" and result.stderr == "", "exclusive-directory bounded worker failed")
        evidence = json.loads((args.out / "native-report.json").read_text(encoding="utf-8"))
        verify_runtime_report(evidence, args.binary_sha256)
        require(readbacks(args.out) == evidence["readbacks"], "exclusive-directory readbacks changed after worker exit")
        require(inspect_entry(args.binary, PROBE) == inspected, "exclusive-directory image changed after worker exit")
        report["pass"] = True
    except (OSError, ValueError, KeyError, TypeError) as error:
        report["error"] = str(error)
        raise
    else:
        print("FRONTEND_NATIVE_FS_CREATE: PASS cases=14")
        return 0
    finally:
        write_json_atomic(args.out / "report.json", report)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        print("FRONTEND_NATIVE_FS_CREATE: FAIL " + str(error), file=sys.stderr)
        raise SystemExit(1) from error
