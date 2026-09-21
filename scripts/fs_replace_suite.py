#!/usr/bin/env python3
"""Independent observation of real filesystem replacement and Ouro recovery.

The supplied driver is either the runtime C self-test or the Ouro boundary
driver. No quality rule or publication decision is implemented here.
"""
from __future__ import annotations

import argparse
import ctypes as c
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

from repo_support import sha256_file as file_hash
from repo_support import checked_windows_result as checked

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DECLARATION = b"inductive Nat : Type := | Z : Nat | S : Nat -> Nat;\n"
ENTRY = "tests/quality_source_write_driver.ouro"
NATIVE_CASES = (
    "metadata-and-repeat", "source-stage-alias", "source-backup-alias", "stage-backup-alias",
    "empty-source", "empty-stage", "empty-backup", "missing-source", "missing-stage", "missing-backup",
    "directory-source", "directory-stage", "directory-backup", "occupied-backup", "large-binary-with-nul",
    "hardlink", "readonly", "locked-original", "unicode", "checked-publish",
    "documented-partial-state-restored", "concurrent-source-retained", "uncertain-source-retains-recovery",
    "corrupt-recovery-candidate-source", "corrupt-recovery-missing-source",
)


def source_snapshot():
    from frontend_regen import collect_units

    units = collect_units(ENTRY)
    if not units or units[-1] != ENTRY or len(set(units)) != len(units):
        raise ValueError("incomplete source replacement closure")
    if not all((ROOT / name).resolve().is_relative_to(ROOT) for name in units):
        raise ValueError("source replacement closure escapes repository")
    return dict(units=units, sources={name: file_hash(ROOT / name) for name in units})


def verify_native_report(report, image_hash):
    expected = [dict(name=name, status="pass") for name in NATIVE_CASES]
    if (report.get("kind") != "ouro.fs-replace.v1" or report.get("complete") is not True
            or report.get("driver_sha256") != image_hash or report.get("checks") != expected):
        raise ValueError("source replacement report is incomplete, stale or has unexpected cases")


def run_native_section(producer, work, run, build_timeout, verify_inputs):
    from frontend_native_process import inspect_image
    from repo_support import write_json_atomic

    if os.name != "nt":
        return dict(status="unavailable", reason="Windows x86-64 runtime required")
    directory = work / "native-fs-replace"
    directory.mkdir()
    before, producer_hash = source_snapshot(), file_hash(producer)
    report = dict(status="running", inputs=before, producer_sha256=producer_hash,
                  execution_backend="direct-windows-pe", external_supervisor="python")

    def unchanged():
        verify_inputs()
        if source_snapshot() != before or file_hash(producer) != producer_hash:
            raise ValueError("source replacement inputs changed")

    try:
        unchanged()
        output = directory / "quality-source-write.exe"
        logical = output.relative_to(ROOT).as_posix()
        result = run("native-build-source-replace", [str(producer), ENTRY, logical, *before["units"]], build_timeout)
        if not result.ok or result.stdout != logical + "\n":
            raise ValueError("source replacement native build failed")
        image = inspect_image(output, ("advapi32.dll", "bcrypt.dll", "kernel32.dll", "shell32.dll"),
                              {"kernel32.dll": ("ReplaceFileW", "FlushFileBuffers", "GetFileInformationByHandle"),
                               "advapi32.dll": ("GetFileSecurityW", "EqualSid")})
        report["image"] = image
        unchanged()
        observed = directory / "runtime"
        command = [sys.executable, "-B", str(Path(__file__).resolve()), "--driver", str(output),
                   "--recovery", "--unicode", "--out", str(observed)]
        result = run("native-source-replace-runtime", command, 300)
        expected = "".join(f"FS_REPLACE_OK {name}\n" for name in NATIVE_CASES)
        expected += f"FS_REPLACE_SUITE: PASS checks={len(NATIVE_CASES)}\n"
        if not result.ok or result.stdout != expected or result.stderr:
            raise ValueError("source replacement runtime protocol failed")
        report["runtime"] = json.loads((observed / "report.json").read_text(encoding="utf-8"))
        verify_native_report(report["runtime"], image["sha256"])
        unchanged()
        if file_hash(output) != image["sha256"]:
            raise ValueError("source replacement image changed")
        report["status"] = "passed"
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        write_json_atomic(directory / "report.json", report)
    return report


def api(lib, name, result, args):
    function = getattr(lib, name)
    function.restype, function.argtypes = result, args
    return function


class WindowsMetadata:
    def __init__(self):
        kernel = c.WinDLL("kernel32", use_last_error=True)
        security = c.WinDLL("advapi32", use_last_error=True)
        self.convert = api(security, "ConvertStringSecurityDescriptorToSecurityDescriptorW", c.c_int,
                           [c.c_wchar_p, c.c_uint32, c.POINTER(c.c_void_p), c.c_void_p])
        self.set_security = api(security, "SetFileSecurityW", c.c_int, [c.c_wchar_p, c.c_uint32, c.c_void_p])
        self.get_security = api(security, "GetFileSecurityW", c.c_int,
                               [c.c_wchar_p, c.c_uint32, c.c_void_p, c.c_uint32, c.POINTER(c.c_uint32)])
        self.owner = api(security, "GetSecurityDescriptorOwner", c.c_int,
                        [c.c_void_p, c.POINTER(c.c_void_p), c.POINTER(c.c_int)])
        self.group = api(security, "GetSecurityDescriptorGroup", c.c_int,
                        [c.c_void_p, c.POINTER(c.c_void_p), c.POINTER(c.c_int)])
        self.sid_size = api(security, "GetLengthSid", c.c_uint32, [c.c_void_p])
        self.dacl = api(security, "GetSecurityDescriptorDacl", c.c_int,
                       [c.c_void_p, c.POINTER(c.c_int), c.POINTER(c.c_void_p), c.POINTER(c.c_int)])
        self.control = api(security, "GetSecurityDescriptorControl", c.c_int,
                          [c.c_void_p, c.POINTER(c.c_uint16), c.POINTER(c.c_uint32)])
        self.free = api(kernel, "LocalFree", c.c_void_p, [c.c_void_p])
        self.attributes = api(kernel, "SetFileAttributesW", c.c_int, [c.c_wchar_p, c.c_uint32])
        self.open = api(kernel, "CreateFileW", c.c_void_p,
                       [c.c_wchar_p, c.c_uint32, c.c_uint32, c.c_void_p, c.c_uint32, c.c_uint32, c.c_void_p])
        self.close = api(kernel, "CloseHandle", c.c_int, [c.c_void_p])

    def decorate(self, path):
        descriptor = c.c_void_p()
        checked(self.convert("D:P(A;;GA;;;WD)", 1, c.byref(descriptor), None))
        try:
            checked(self.set_security(str(path), 0x80000004, descriptor))
        finally:
            self.free(descriptor)
        checked(self.attributes(str(path), 0x2020))
        Path(str(path) + ":quality-contract").write_bytes(b"retained named stream\x00\xff")

    def snapshot(self, path):
        size = c.c_uint32()
        self.get_security(str(path), 7, None, 0, c.byref(size))
        if c.get_last_error() != 122 or not size.value:
            raise c.WinError(c.get_last_error())
        descriptor = c.create_string_buffer(size.value)
        checked(self.get_security(str(path), 7, descriptor, len(descriptor), c.byref(size)))
        result = {}
        for name, function in (("owner", self.owner), ("group", self.group)):
            address, defaulted = c.c_void_p(), c.c_int()
            checked(function(descriptor, c.byref(address), c.byref(defaulted)))
            if not address.value:
                raise AssertionError("missing security identity")
            result[name] = c.string_at(address, self.sid_size(address)).hex()
        present, address, defaulted = c.c_int(), c.c_void_p(), c.c_int()
        checked(self.dacl(descriptor, c.byref(present), c.byref(address), c.byref(defaulted)))
        result["dacl_present"] = present.value
        result["dacl"] = c.string_at(address, c.c_uint16.from_address(address.value + 2).value).hex() if address.value else None
        flags, revision = c.c_uint16(), c.c_uint32()
        checked(self.control(descriptor, c.byref(flags), c.byref(revision)))
        # ReplaceFileW can add SE_DACL_AUTO_INHERITED while retaining the exact
        # protected DACL. Compare its bytes and inheritance protection directly.
        result["dacl_protected"] = bool(flags.value & 0x1000)
        result["attributes"] = path.stat().st_file_attributes
        result["created_ns"] = path.stat().st_birthtime_ns
        result["stream"] = Path(str(path) + ":quality-contract").read_bytes().hex()
        return result


def posix_snapshot(path):
    info = path.stat()
    return dict(mode=stat.S_IMODE(info.st_mode), owner=info.st_uid, group=info.st_gid,
                xattrs={name: os.getxattr(path, name).hex() for name in sorted(os.listxattr(path))})


def run_suite(driver: Path, output: Path, *, recovery: bool, unicode: bool, fix: Path | None,
              fmt: Path | None = None):
    windows = WindowsMetadata() if os.name == "nt" else None
    rows = []
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").unlink(missing_ok=True)
    driver_hash = file_hash(driver)
    child_env = dict(os.environ, PATH="")

    def invoke(arguments, *, success):
        result = subprocess.run([str(driver), *map(str, arguments)], cwd=ROOT, env=child_env,
                                capture_output=True, timeout=30)
        status = result.stdout.decode("ascii").strip()
        if not status.isdigit() or (result.returncode == 0) != (status == "0") or (result.returncode == 0) != success:
            raise AssertionError((arguments, result.returncode, result.stdout, result.stderr))
        return int(status)

    def snapshot(path):
        return windows.snapshot(path) if windows else posix_snapshot(path)

    def decorate(path):
        if windows:
            windows.decorate(path)
        else:
            path.chmod(0o640)
            os.setxattr(path, "user.quality-contract", b"retained metadata\x00\xff")

    def case(name, action):
        with tempfile.TemporaryDirectory(prefix=name + "-", dir=output) as directory:
            base = Path(directory)
            source, stage, backup = (base / name for name in ("original.ouro", "stage.ouro", "backup.ouro"))
            source.write_bytes(b"original\n")
            stage.write_bytes(b"candidate\n")
            backup.write_bytes(b"")
            action(source, stage, backup)
        rows.append(dict(name=name, status="pass"))
        print("FS_REPLACE_OK", name, flush=True)

    def publication(source, stage, backup):
        decorate(source)
        before = snapshot(source)
        invoke(["--replace-files", source, stage, backup], success=True)
        assert source.read_bytes() == b"candidate\n" and backup.read_bytes() == b"original\n" and not stage.exists()
        assert snapshot(source) == before and snapshot(backup) == before
        invoke(["--replace-files", source, stage, backup], success=False)
        assert source.read_bytes() == b"candidate\n" and backup.read_bytes() == b"original\n"

    def refusal(source, stage, backup, transform):
        arguments = transform(source, stage, backup)
        before = {path: path.read_bytes() for path in (source, stage, backup) if path.is_file()}
        invoke(["--replace-files", *arguments], success=False)
        assert all(path.read_bytes() == contents for path, contents in before.items())

    case("metadata-and-repeat", publication)
    for label, change in (
        ("source-stage-alias", lambda s, _t, b: (s, s, b)),
        ("source-backup-alias", lambda s, t, _b: (s, t, s)),
        ("stage-backup-alias", lambda s, t, _b: (s, t, t)),
        ("empty-source", lambda _s, t, b: ("", t, b)),
        ("empty-stage", lambda s, _t, b: (s, "", b)),
        ("empty-backup", lambda s, t, _b: (s, t, "")),
        ("missing-source", lambda s, t, b: (s.with_name("missing"), t, b)),
        ("missing-stage", lambda s, t, b: (s, t.with_name("missing"), b)),
        ("missing-backup", lambda s, t, b: (s, t, b.with_name("missing"))),
        ("directory-source", lambda s, t, b: (s.parent, t, b)),
        ("directory-stage", lambda s, t, b: (s, t.parent, b)),
        ("directory-backup", lambda s, t, b: (s, t, b.parent)),
    ):
        case(label, lambda s, t, b, change=change: refusal(s, t, b, change))

    def occupied(s, t, b):
        b.write_bytes(b"somebody else's recovery")
        refusal(s, t, b, lambda s, t, b: (s, t, b))

    case("occupied-backup", occupied)

    def binary_large(s, t, b):
        original = bytes(range(256)) * 32768
        candidate = original[:-1] + b"changed\x00\xff"
        s.write_bytes(original)
        t.write_bytes(candidate)
        invoke(["--replace-files", s, t, b], success=True)
        assert s.read_bytes() == candidate and b.read_bytes() == original and not t.exists()
    case("large-binary-with-nul", binary_large)

    def hardlink(s, t, b):
        link = s.with_name("alias")
        os.link(s, link)
        refusal(s, t, b, lambda s, t, b: (s, t, b))
        assert link.read_bytes() == b"original\n"

    case("hardlink", hardlink)
    if windows:
        def readonly(s, t, b):
            checked(windows.attributes(str(s), 0x21))
            try:
                refusal(s, t, b, lambda s, t, b: (s, t, b))
            finally:
                checked(windows.attributes(str(s), 0x20))
        case("readonly", readonly)

        def locked(s, t, b):
            lock = windows.open(str(s), 0x80000000, 1, None, 3, 0x80, None)
            if lock == c.c_void_p(-1).value:
                raise c.WinError(c.get_last_error())
            try:
                refusal(s, t, b, lambda s, t, b: (s, t, b))
            finally:
                checked(windows.close(lock))
        case("locked-original", locked)

    if unicode:
        def unicode_case(s, t, b):
            target = s.with_name("漢字 файл \u0441 пробелами.ouro")
            s.rename(target)
            publication(target, t, b)
        case("unicode", unicode_case)

    if recovery:
        def publish(s, t, b):
            decorate(s)
            before = snapshot(s)
            invoke(["--publish", s, t, b], success=True)
            assert s.read_bytes() == b"candidate\n" and snapshot(s) == before
            invoke(["--publish", s, t, b], success=False)
            assert s.read_bytes() == b"candidate\n" and snapshot(s) == before
            assert sorted(p.name for p in s.parent.iterdir()) == ["backup.ouro", "original.ouro", "stage.ouro"]
        case("checked-publish", publish)

        def partial(s, t, b):
            decorate(s)
            before = snapshot(s)
            b.unlink()
            s.rename(b)
            invoke(["--recover-partial", s, t, b], success=False)
            assert s.read_bytes() == b"original\n" and snapshot(s) == before
            assert not t.exists() and not b.exists()
        case("documented-partial-state-restored", partial)

        def concurrent(s, t, b):
            b.write_bytes(s.read_bytes())
            s.write_bytes(b"concurrent editor\n")
            invoke(["--recover-partial", s, t, b], success=False)
            assert s.read_bytes() == b"concurrent editor\n" and t.read_bytes() == b"candidate\n" and b.read_bytes() == b"original\n"
        case("concurrent-source-retained", concurrent)

        def corrupt_candidate(s, t, b):
            s.write_bytes(b"corrupted or external bytes\n")
            b.write_bytes(b"original\n")
            invoke(["--recover-partial", s, t, b], success=False)
            assert s.read_bytes() == b"corrupted or external bytes\n"
            assert b.read_bytes() == b"original\n" and t.read_bytes() == b"candidate\n"
        case("uncertain-source-retains-recovery", corrupt_candidate)

        def corrupt_backup(s, t, b, *, missing):
            if missing:
                s.unlink()
            else:
                s.write_bytes(b"candidate\n")
            b.write_bytes(b"damaged recovery\n")
            invoke(["--recover-partial", s, t, b], success=False)
            if missing:
                assert not s.exists()
            else:
                assert s.read_bytes() == b"candidate\n"
            assert b.read_bytes() == b"damaged recovery\n" and t.read_bytes() == b"candidate\n"
        for missing in (False, True):
            case("corrupt-recovery-" + ("missing-source" if missing else "candidate-source"),
                 lambda s, t, b, missing=missing: corrupt_backup(s, t, b, missing=missing))

    writer_hashes = {}
    for label, writer in (("fix", fix), ("fmt", fmt)):
        if writer is None:
            continue
        writer_hashes[label] = file_hash(writer)

        def public_write(s, _t, _b, writer=writer):
            declaration = SOURCE_DECLARATION
            s.write_bytes(declaration + b"def retained_value : Nat :=0;\n")
            decorate(s)
            before = snapshot(s)
            for mode in ("--write", "--check", "--write"):
                result = subprocess.run([str(writer), mode, str(s)], cwd=ROOT, env=child_env,
                                        capture_output=True, timeout=60)
                assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
                assert s.read_bytes() == declaration + b"def retained_value : Nat := 0;\n" and snapshot(s) == before
            assert not result.stdout and not result.stderr
        case(f"public-{label}-metadata-convergence", public_write)
        if windows:
            def unreadable_write(s, _t, _b, writer=writer):
                original = SOURCE_DECLARATION + b"def retained_value : Nat :=0;\n"
                s.write_bytes(original)
                lock = windows.open(str(s), 0x80000000, 0, None, 3, 0x80, None)
                if lock == c.c_void_p(-1).value:
                    raise c.WinError(c.get_last_error())
                try:
                    result = subprocess.run([str(writer), "--write", str(s)], cwd=ROOT, env=child_env,
                                            capture_output=True, timeout=60)
                finally:
                    checked(windows.close(lock))
                assert result.returncode != 0, ("unreadable input reported success", result.stdout, result.stderr)
                assert s.read_bytes() == original
            case(f"public-{label}-unreadable-refusal", unreadable_write)

            def readonly_write(s, _t, _b, writer=writer):
                original = SOURCE_DECLARATION + b"def retained_value : Nat :=0;\n"
                s.write_bytes(original)
                checked(windows.attributes(str(s), 0x21))
                try:
                    result = subprocess.run([str(writer), "--write", str(s)], cwd=ROOT, env=child_env,
                                            capture_output=True, timeout=60)
                    assert result.returncode != 0 and not result.stdout and result.stderr, result
                    assert s.read_bytes() == original and s.stat().st_file_attributes == 0x21
                finally:
                    checked(windows.attributes(str(s), 0x20))
            case(f"public-{label}-readonly-refusal", readonly_write)

        def hardlink_write(s, _t, _b, writer=writer):
            original = SOURCE_DECLARATION + b"def retained_value : Nat :=0;\n"
            s.write_bytes(original)
            alias = s.with_name("alias.ouro")
            os.link(s, alias)
            result = subprocess.run([str(writer), "--write", str(s)], cwd=ROOT, env=child_env,
                                    capture_output=True, timeout=60)
            assert result.returncode != 0 and not result.stdout and result.stderr, result
            assert s.read_bytes() == alias.read_bytes() == original and os.path.samefile(s, alias)
        case(f"public-{label}-hardlink-refusal", hardlink_write)
        if file_hash(writer) != writer_hashes[label]:
            raise ValueError("public writer changed during execution")
    if file_hash(driver) != driver_hash:
        raise ValueError("source replacement driver changed during execution")
    (output / "report.json").write_text(json.dumps(dict(kind="ouro.fs-replace.v1", complete=True,
        driver_sha256=driver_hash, writer_sha256=writer_hashes, checks=rows), indent=2) + "\n", encoding="utf-8")
    print(f"FS_REPLACE_SUITE: PASS checks={len(rows)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--driver", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "_build/fs_replace_suite")
    parser.add_argument("--recovery", action="store_true")
    parser.add_argument("--unicode", action="store_true")
    parser.add_argument("--fix", type=Path)
    parser.add_argument("--fmt", type=Path)
    args = parser.parse_args()
    run_suite(args.driver.resolve(), args.out.resolve(), recovery=args.recovery,
              unicode=args.unicode, fix=args.fix.resolve() if args.fix else None,
              fmt=args.fmt.resolve() if args.fmt else None)


if __name__ == "__main__":
    main()
