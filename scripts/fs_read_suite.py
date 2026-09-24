#!/usr/bin/env python3
"""Observe complete reads and unreadable-input refusal in actual binaries."""
from __future__ import annotations

import argparse
import ctypes as c
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from fs_replace_suite import ROOT, WindowsMetadata, checked


def run_suite(driver: Path, output: Path, mode: str):
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "report.json"
    report_path.unlink(missing_ok=True)
    original_hash = hashlib.sha256(driver.read_bytes()).hexdigest()
    rows = []
    environment = dict(os.environ, PATH="")
    families = b""
    if mode == "drive":
        metadata = subprocess.run([str(driver), "--strict", "--enable-all", "--print-families"],
                                  cwd=ROOT, env=environment, capture_output=True, timeout=30)
        matched = re.fullmatch(rb"ANALYZE_FAMILIES families=([a-z_]+(?:,[a-z_]+)*)\r?\n", metadata.stdout)
        assert metadata.returncode == 0 and not metadata.stderr and matched, metadata
        families = matched.group(1)
        assert len(families.split(b",")) == len(set(families.split(b","))), "duplicate families"

    def run(name, path, *, content=None, invalid_nul=False, invalid_utf8=False):
        command = "--read-invalid-utf8-path" if invalid_utf8 else "--read-nul-path" if invalid_nul else "--read-file"
        arguments = ([command, str(path)] if mode == "raw"
                     else ["--strict", "--enable-all", "--scope", str(path)])
        result = subprocess.run([str(driver), *arguments], cwd=ROOT, env=environment,
                                capture_output=True, timeout=90)
        if content is None:
            assert result.returncode != 0, (name, "unreadable input accepted", result.stdout, result.stderr)
            assert b"ANALYZE_DRIVE " not in result.stdout and result.stderr, (name, "false completion", result)
            if mode == "raw":
                assert result.returncode == 73 and not result.stdout, (name, result)
        else:
            assert result.returncode == 0 and not result.stderr, (name, result)
            if mode == "raw":
                assert result.stdout == content, (name, "bytes differ")
            else:
                expected = b"ANALYZE_DRIVE files=1 findings=0 rejected=0 families=" + families + b"\n"
                assert result.stdout.replace(b"\r\n", b"\n") == expected, (name, result.stdout)
        rows.append(dict(name=name, exit=result.returncode, status="pass"))
        print(f"FS_READ_OK {name}", flush=True)

    with tempfile.TemporaryDirectory(prefix="read-", dir=output) as temporary:
        directory = Path(temporary)
        source = directory / "input.ouro"
        source.write_bytes(b"")
        run("empty-file", source, content=b"")
        content = (bytes(range(256)) * 32768 if mode == "raw" else
                   b"inductive Nat : Type := | Z : Nat;\ndef retained_value : Nat := Z;\n")
        source.write_bytes(content)
        run("complete-file", source, content=content)
        run("missing-file", directory / "missing.ouro")
        empty_directory = directory / "empty"
        empty_directory.mkdir()
        run("empty-directory", empty_directory)
        run("empty-path", "")
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
            finally:
                checked(windows.close(lock))
        else:
            print("FS_READ_UNAVAILABLE locked-file: Windows sharing-mode contract", flush=True)
        assert source.read_bytes() == content, "read attempt changed input"
        run("read-after-refusal", source, content=content)
    if hashlib.sha256(driver.read_bytes()).hexdigest() != original_hash:
        raise ValueError("read driver changed during execution")
    report_path.write_text(json.dumps(dict(kind="ouro.fs-read.v1", complete=True, mode=mode,
        driver_sha256=original_hash, checks=rows), indent=2) + "\n", encoding="utf-8")
    print(f"FS_READ_SUITE: PASS checks={len(rows)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--driver", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mode", choices=("raw", "drive"), required=True)
    args = parser.parse_args()
    run_suite(args.driver.resolve(), args.out.resolve(), args.mode)


if __name__ == "__main__":
    main()
