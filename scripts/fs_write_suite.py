#!/usr/bin/env python3
"""Observe the transitional C writer with exact bytes and bounded processes."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes as c
import errno
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from fs_replace_suite import ROOT, api
from ourosmith.limits import clean_env, run_limited_bytes
from repo_support import checked_windows_result, sha256_file, write_json_atomic

MEMORY_MIB = 3072
SUITE_TIMEOUT_S = 90
BUILD_TIMEOUT_S = 30
CASE_TIMEOUT_S = 10
PAYLOAD = bytes((65, 0, 255, 128, 13, 10, 90))
PRIOR = b"prior\0\xff\r\n"
C_SOURCES = ("runtime/ouro_rt.c", "runtime/ouro_io.c", "runtime/ouro_io_write_selftest.c")
INPUTS = (*C_SOURCES, "runtime/ouro_rt.h", "runtime/ouro_io.h", "runtime/ouro_fs_replace.h",
          "runtime/ouro_io_write_test.h", "scripts/fs_write_suite.py", "scripts/fs_write_suite_test.py",
          "scripts/fs_replace_suite.py", "scripts/repo_support.py", "scripts/runtime_io_suite.sh",
          "scripts/ourosmith/__init__.py", "scripts/ourosmith/limits.py",
          "scripts/ourosmith/exec_child.py", "scripts/ourosmith/windows_job.py")
TRANSFER_CASES = (
    ("raw-binary", "valid", 0, None, (1, 1, 1), None, PAYLOAD),
    ("empty-truncation", "empty", 0, None, (1, 1, 1), PRIOR, b""),
    ("full-ferror", "full-ferror", 73, "complete write", (1, 1, 1), None, PAYLOAD),
    ("empty-ferror", "empty-ferror", 73, "complete write", (1, 1, 1), b"", b""),
    ("write-zero", "write-zero", 73, "complete write", (1, 0, 1), None, b""),
    ("write-short", "write-short", 73, "complete write", (1, 0, 1), None, PAYLOAD[:-1]),
    ("close-error", "close-error", 73, "close", (1, 1, 1), None, PAYLOAD),
    ("empty-close-error", "empty-close-error", 73, "close", (1, 1, 1), b"", b""),
    ("write-close-error", "write-close-error", 73, "close", (1, 0, 1), None, b""),
)
MALFORMED_CASES = ("no-arguments", "unknown-mode", "missing-path", "extra-argument")


def input_snapshot(compiler):
    return dict(producer=dict(path=compiler.as_posix(), sha256=sha256_file(compiler)),
                sources={name: sha256_file(ROOT / name) for name in INPUTS})


def expected_stderr(phase, counts):
    if counts is None:
        return b""
    end = b"\r\n" if os.name == "nt" else b"\n"
    prefix = b"" if phase is None else b"ouro run: fs_write_file: " + phase.encode("ascii") + b" failed" + end
    writes, ferrors, closes = counts
    return prefix + f"WRITE_FAULT_COUNTS writes={writes} ferrors={ferrors} closes={closes}".encode("ascii") + end


def verify_result(name, result, code, phase, counts):
    if (result.status != "ok" or type(result.returncode) is not int or result.returncode != code
            or not isinstance(result.stdout, bytes) or result.stdout != b""
            or not isinstance(result.stderr, bytes) or result.stderr != expected_stderr(phase, counts)):
        raise ValueError(f"C write {name}: exact status or raw streams differ")


def read_target(path):
    with path.open("rb") as stream:
        return stream.read(65)


@contextmanager
def refused_target(directory, prior):
    target = directory / "ordinary.bin"
    target.write_bytes(prior)
    identity = (target.stat().st_dev, target.stat().st_ino)
    if os.name == "nt":
        kernel = c.WinDLL("kernel32", use_last_error=True)
        arguments = [c.c_wchar_p, c.c_uint32, c.c_uint32, c.c_void_p, c.c_uint32, c.c_uint32, c.c_void_p]
        open_wide = api(kernel, "CreateFileW", c.c_void_p, arguments)
        open_direct = api(kernel, "CreateFileA", c.c_void_p, [c.c_char_p, *arguments[1:]])
        close = api(kernel, "CloseHandle", c.c_int, [c.c_void_p])
        invalid = c.c_void_p(-1).value
        lock = open_wide(str(target), 0x80000000, 1, None, 3, 0x80, None)
        if lock == invalid:
            raise c.WinError(c.get_last_error())
        try:
            c.set_last_error(0)
            attempted = open_direct(str(target).encode("mbcs"), 0x40000000, 0, None, 4, 0x200080, None)
            status = c.get_last_error()
            if attempted != invalid:
                checked_windows_result(close(attempted))
                raise ValueError("Windows direct writer open did not refuse the held read-share handle")
            if status != 32:
                raise ValueError(f"Windows direct writer refusal status={status}, expected 32")
            yield target, dict(mechanism="windows-read-share-lock", direct_open_status=status)
            if read_target(target) != prior or (target.stat().st_dev, target.stat().st_ino) != identity:
                raise ValueError("Windows refused write changed the ordinary target")
        finally:
            checked_windows_result(close(lock))
    else:
        alias = directory / "writer-link"
        alias.symlink_to(target.name)
        try:
            try:
                descriptor = os.open(alias, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o666)
            except OSError as error:
                if error.errno != errno.ELOOP:
                    raise ValueError(f"POSIX direct no-follow refusal errno={error.errno}, expected ELOOP") from error
            else:
                os.close(descriptor)
                raise ValueError("POSIX direct no-follow writer open did not refuse the symlink")
            yield alias, dict(mechanism="posix-symlink-no-follow", direct_open_errno=errno.ELOOP)
            if read_target(target) != prior or (target.stat().st_dev, target.stat().st_ino) != identity:
                raise ValueError("POSIX refused write changed the ordinary symlink target")
        finally:
            alias.unlink()


def run_suite(producer, output):
    found = shutil.which(str(producer))
    if found is None:
        raise ValueError("configured C writer producer is unavailable")
    compiler = Path(found).resolve(strict=True)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("C writer output directory must be empty")
    before = input_snapshot(compiler)
    deadline = time.monotonic() + SUITE_TIMEOUT_S
    images = {}
    report = dict(kind="ouro.c-write.v1", complete=False, execution_backend="c-runtime-selftest",
                  before=before, limits=dict(memory_mib=MEMORY_MIB, timeout_s=SUITE_TIMEOUT_S, workers=1),
                  builds=[], checks=[])
    report_path = output / "report.json"
    observed = False

    def unchanged():
        if input_snapshot(compiler) != before:
            raise ValueError("C writer source or configured producer changed")
        if any(sha256_file(Path(name)) != digest for name, digest in images.items()):
            raise ValueError("C writer test object or driver changed")

    def invoke(name, argv, timeout, section):
        unchanged()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("C writer suite exceeded 90s")
        command = list(map(str, argv))
        environment = clean_env()
        if section == "checks":
            environment["PATH"] = ""
        result = run_limited_bytes(command, timeout_s=min(timeout, remaining), memory_mb=MEMORY_MIB,
                                   cwd=ROOT, env=environment)
        row = dict(name=name, status="fail", argv=command, transport_status=result.status,
                   returncode=result.returncode,
                   stdout_hex=result.stdout.hex() if isinstance(result.stdout, bytes) else None,
                   stderr_hex=result.stderr.hex() if isinstance(result.stderr, bytes) else None)
        report[section].append(row)
        unchanged()
        if result.argv != command:
            raise ValueError("C writer observed argv differs")
        return result, row

    try:
        flags = ["-O1", "-std=c99", "-D_POSIX_C_SOURCE=200809L", "-D_XOPEN_SOURCE=700",
                 "-Werror=implicit-function-declaration", "-I", str(ROOT / "runtime")]
        if sys.platform == "darwin":
            flags.append("-D_DARWIN_C_SOURCE=1")
        objects = []
        for index, source in enumerate(C_SOURCES):
            target = output / f"write-{index}.o"
            include = ["-include", str(ROOT / "runtime/ouro_io_write_test.h")] if source == "runtime/ouro_io.c" else []
            result, row = invoke(f"compile-{index}", [compiler, *flags, *include, "-c", ROOT / source, "-o", target],
                                 BUILD_TIMEOUT_S, "builds")
            if result.status != "ok" or type(result.returncode) is not int or result.returncode != 0:
                raise ValueError(f"C writer {source}: compilation failed")
            images[target.as_posix()] = sha256_file(target)
            objects.append(target)
            row["status"] = "pass"
        driver = output / ("ouro-io-write-selftest.exe" if os.name == "nt" else "ouro-io-write-selftest")
        result, row = invoke("link", [compiler, "-O1", *objects, "-o", driver], BUILD_TIMEOUT_S, "builds")
        if result.status != "ok" or type(result.returncode) is not int or result.returncode != 0:
            raise ValueError("C writer driver link failed")
        images[driver.as_posix()] = sha256_file(driver)
        report["images_before"] = dict(images)
        row["status"] = "pass"

        for name, mode, code, phase, counts, initial, expected in TRANSFER_CASES:
            target = output / (name + ".bin")
            if initial is not None:
                target.write_bytes(initial)
            result, row = invoke(name, [driver, mode, target], CASE_TIMEOUT_S, "checks")
            verify_result(name, result, code, phase, counts)
            row["target_hex"] = read_target(target).hex()
            if row["target_hex"] != expected.hex():
                raise ValueError(f"C write {name}: raw target bytes differ")
            row["status"] = "pass"
            print(f"FS_WRITE_OK {name}", flush=True)

        missing_parent = output / "absent-parent"
        target = missing_parent / "target.bin"
        if missing_parent.exists():
            raise ValueError("missing-parent fixture already exists")
        result, row = invoke("missing-parent", [driver, "valid", target], CASE_TIMEOUT_S, "checks")
        verify_result("missing-parent", result, 73, "open", (0, 0, 0))
        if missing_parent.exists() or target.exists():
            raise ValueError("failed fresh write created the missing-parent fixture")
        row.update(status="pass", target_absent=True)
        print("FS_WRITE_OK missing-parent", flush=True)

        mechanism = "windows-read-share-lock" if os.name == "nt" else "posix-symlink-no-follow"
        for label, mode, prior in (("empty", "empty", b""), ("nonempty", "valid", PRIOR)):
            name = mechanism + "-" + label
            directory = output / name
            directory.mkdir()
            with refused_target(directory, prior) as (target, proof):
                if not target.is_file() or read_target(target) != prior:
                    raise ValueError("refusal fixture is not the existing readable target")
                result, row = invoke(name, [driver, mode, target], CASE_TIMEOUT_S, "checks")
                verify_result(name, result, 73, "open", (0, 0, 0))
                row["target_hex"] = read_target(target).hex()
                if row["target_hex"] != prior.hex():
                    raise ValueError("refused direct writer changed prior raw bytes")
                row["direct_open"] = proof
            row["status"] = "pass"
            print(f"FS_WRITE_OK {name}", flush=True)

        target = output / "malformed.bin"
        target.write_bytes(PRIOR)
        commands = ([], ["unknown", str(target)], ["valid"], ["valid", str(target), "extra"])
        for name, arguments in zip(MALFORMED_CASES, commands, strict=True):
            result, row = invoke(name, [driver, *arguments], CASE_TIMEOUT_S, "checks")
            verify_result(name, result, 2, None, None)
            if read_target(target) != PRIOR:
                raise ValueError("malformed write-driver arguments changed target")
            row.update(status="pass", target_hex=PRIOR.hex())
            print(f"FS_WRITE_OK {name}", flush=True)
        expected_names = [case[0] for case in TRANSFER_CASES] + ["missing-parent"]
        expected_names += [mechanism + "-empty", mechanism + "-nonempty", *MALFORMED_CASES]
        if [row["name"] for row in report["checks"]] != expected_names:
            raise ValueError("C writer observations are missing, reordered or duplicated")
        if time.monotonic() > deadline:
            raise ValueError("C writer suite exceeded 90s")
        observed = True
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report["error"] = str(error)
        raise
    finally:
        try:
            report["after"] = input_snapshot(compiler)
            report["images_after"] = {name: sha256_file(Path(name)) for name in images}
            if report["after"] != before or report["images_after"] != images:
                raise ValueError("C writer sources, producer or images changed during observation")
            if observed and time.monotonic() > deadline:
                raise ValueError("C writer suite exceeded 90s")
            report["complete"] = observed
        except (OSError, ValueError) as error:
            report["identity_error"] = str(error)
            raise
        finally:
            write_json_atomic(report_path, report)
    print(f"FS_WRITE_SUITE: PASS checks={len(report['checks'])}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--producer", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run_suite(args.producer, args.out.resolve())


if __name__ == "__main__":
    main()
