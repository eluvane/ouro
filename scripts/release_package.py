#!/usr/bin/env python3
"""Build deterministic Ouro release archives, metadata, and checksums.

Hosted releases publish Lean-style per-host toolchains:

  ouro-<version>-<platform>.tar.zst
  ouro-<version>-<platform>.zip

for darwin, darwin_aarch64, linux, linux_aarch64, and windows. Each archive
contains repository sources plus the host `ouro1` built on that runner. The
script must not invent a missing compiler, claim signed binaries, or claim
SLSA attestations.
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, Optional, Sequence
from unittest.mock import patch

import ouro_seal
from repo_support import (
    bind_relative_path,
    parse_json_value,
    resolve_repo_local_path,
    sha256_file,
    write_json_atomic,
)

ROOT = Path(__file__).resolve().parents[1]
rel = bind_relative_path(ROOT, resolve=True)
REPORT_KIND = "ouro.release-package.v1"
PACKAGE_NAME = "ouro"
FIXED_MTIME = 0
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
TOOLCHAIN_PLATFORMS = (
    "darwin",
    "darwin_aarch64",
    "linux",
    "linux_aarch64",
    "windows",
)
COMPILER_MIN_BYTES = 32768
ARCHIVE_MIN_BYTES = 32
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
ZSTD_MAX_RAW_BLOCK = 128 * 1024
MACHO_MAGICS = {
    b"\xcf\xfa\xed\xfe",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xfe\xed\xfa\xce",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
}
RESERVED_TOOLCHAIN_PATHS = {
    "bin/ouro",
    "bin/ouro.cmd",
    "bin/ouro1",
    "bin/ouro1.exe",
}

EXCLUDE_DIRS = {
    ".git",
    "_build",
    "_cache",
    "_opam",
    "_tools",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    "out",
    "dist",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".swp", ".tmp"}
EXCLUDE_NAMES = {".DS_Store", "Thumbs.db"}
REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def read(path: str) -> str:
    try:
        return (ROOT / path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SystemExit(f"release package: cannot read {path}: {exc}") from exc


def load_object(path: str) -> dict:
    data, error = parse_json_value(read(path))
    if error is not None:
        raise SystemExit(f"release package: invalid JSON {path}: {error}")
    if not isinstance(data, dict):
        raise SystemExit(f"release package: {path} is not a JSON object")
    return data


def parse_seal_version() -> str:
    return ouro_seal.load_project_version(ROOT / ouro_seal.SEAL_NAME)


def parse_vscode_version() -> str:
    data = load_object("editors/vscode/package.json")
    return str(data.get("version", ""))


def parse_package_lock_version() -> str:
    data = load_object("editors/vscode/package-lock.json")
    return str(data.get("version") or data.get("packages", {}).get("", {}).get("version", ""))


def validate_versions(expect_tag: Optional[str]) -> tuple[str, list[str]]:
    versions = {
        "Ouro.seal": parse_seal_version(),
        "editors/vscode/package.json": parse_vscode_version(),
        "editors/vscode/package-lock.json": parse_package_lock_version(),
    }
    unique = set(versions.values())
    if len(unique) != 1 or not all(versions.values()):
        raise SystemExit("release package: version drift: " + json.dumps(versions, sort_keys=True))
    version = next(iter(unique))
    if expect_tag:
        tag = expect_tag.strip()
        if tag.startswith("refs/tags/"):
            tag = tag[len("refs/tags/") :]
        expected = "v" + version
        if tag != expected:
            raise SystemExit(f"release package: tag {tag!r} does not match version {expected!r}")
    return version, [f"{k}={v}" for k, v in sorted(versions.items())]


def validate_generated_artifacts() -> list[dict[str, str]]:
    manifest = ROOT / "docs" / "generated_artifact_hashes.sha256"
    if not manifest.is_file():
        raise SystemExit("release package: missing docs/generated_artifact_hashes.sha256")
    rows: list[dict[str, str]] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) != 2:
            raise SystemExit(f"release package: malformed hash manifest line: {line!r}")
        expected, name = parts
        p = ROOT / name
        if not p.is_file():
            raise SystemExit(f"release package: generated artifact missing: {name}")
        actual = sha256_file(p)
        if actual != expected:
            raise SystemExit(f"release package: generated artifact hash drift: {name}")
        rows.append({"path": name, "sha256": actual})
    if not rows:
        raise SystemExit("release package: generated artifact hash manifest is empty")
    return rows


def git(
    args: list[str], *, root: Path = ROOT, check: bool = False
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git"] + args,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def git_commit() -> str:
    try:
        p = git(["rev-parse", "HEAD"])
        return p.stdout.strip() if p.returncode == 0 else "unknown"
    except OSError:
        return "unknown"


def git_dirty() -> bool:
    try:
        p = git(["status", "--porcelain"])
        return bool(p.stdout.strip()) if p.returncode == 0 else True
    except OSError:
        return True


def archive_rel(path: Path, *, root: Path = ROOT) -> str:
    try:
        parts = path.relative_to(root).parts
    except ValueError as exc:
        raise SystemExit(
            f"release package: selected path is outside repository root: {path}"
        ) from exc
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise SystemExit(f"release package: invalid repository path: {path}")
    return Path(*parts).as_posix()


def is_symlink_or_reparse(st: os.stat_result) -> bool:
    return stat.S_ISLNK(st.st_mode) or bool(
        getattr(st, "st_file_attributes", 0) & REPARSE_POINT
    )


def selected_file_stat(path: Path, *, root: Path = ROOT) -> os.stat_result | None:
    label = archive_rel(path, root=root)
    rel_parts = Path(label).parts
    if any(part in EXCLUDE_DIRS for part in rel_parts):
        return None
    if path.name in EXCLUDE_NAMES:
        return None
    if path.suffix in EXCLUDE_SUFFIXES:
        return None

    current = root
    current_stat: os.stat_result | None = None
    for part in rel_parts:
        current = current / part
        try:
            current_stat = current.lstat()
        except OSError as exc:
            raise SystemExit(
                f"release package: cannot inspect selected path {label}: {exc}"
            ) from exc
        if is_symlink_or_reparse(current_stat):
            raise SystemExit(
                f"release package: refusing symlink or reparse point: {label}"
            )

    try:
        resolve_repo_local_path(root, path, label=f"release input {label}")
    except ValueError as exc:
        raise SystemExit(
            f"release package: selected path escapes repository root: {label}"
        ) from exc
    if current_stat is None or not stat.S_ISREG(current_stat.st_mode):
        return None
    return current_stat


def allowed_file(path: Path, *, root: Path = ROOT) -> bool:
    return selected_file_stat(path, root=root) is not None


def tracked_candidates(root: Path) -> list[Path] | None:
    p = git(["ls-files", "--cached", "--stage", "-z"], root=root)
    if p.returncode != 0:
        return None
    return parse_tracked_candidates(p.stdout, root=root)


def parse_tracked_candidates(index_output: str, *, root: Path) -> list[Path]:
    candidates: list[Path] = []
    for record in index_output.split("\0"):
        if not record:
            continue
        try:
            metadata, name = record.split("\t", 1)
            mode = metadata.split(" ", 1)[0]
        except ValueError as exc:
            raise SystemExit("release package: malformed git index entry") from exc
        if mode == "120000":
            raise SystemExit(f"release package: refusing tracked symlink: {name}")
        candidates.append(root / name)
    return candidates


def list_files(*, root: Path = ROOT) -> list[Path]:
    # Include tracked files and not-yet-tracked files in local development. On a
    # tag checkout this collapses to tracked release source.
    try:
        candidates = tracked_candidates(root)
        if candidates is not None:
            p = git(["ls-files", "--others", "--exclude-standard", "-z"], root=root)
            if p.returncode == 0:
                candidates.extend(root / name for name in p.stdout.split("\0") if name)
                return sorted(
                    {p for p in candidates if allowed_file(p, root=root)},
                    key=lambda p: archive_rel(p, root=root),
                )
    except OSError:
        pass
    files: list[Path] = []
    for p in root.rglob("*"):
        if allowed_file(p, root=root):
            files.append(p)
    return sorted(files, key=lambda p: archive_rel(p, root=root))


def open_selected_file(path: Path, *, root: Path = ROOT) -> tuple[BinaryIO, os.stat_result]:
    before = selected_file_stat(path, root=root)
    label = archive_rel(path, root=root)
    if before is None:
        raise SystemExit(f"release package: refusing excluded archive input: {label}")
    handle: BinaryIO | None = None
    try:
        handle = path.open("rb")
        opened = os.fstat(handle.fileno())
    except OSError as exc:
        if handle is not None:
            handle.close()
        raise SystemExit(f"release package: cannot open selected path {label}: {exc}") from exc
    if not stat.S_ISREG(opened.st_mode) or file_identity(before) != file_identity(opened):
        handle.close()
        raise SystemExit(f"release package: selected path changed while packaging: {label}")
    return handle, opened


def file_identity(st: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        st.st_dev,
        st.st_ino,
        stat.S_IFMT(st.st_mode),
        st.st_size,
        st.st_mtime_ns,
    )


def archive_members(files: list[Path], *, root: Path = ROOT) -> list[tuple[Path, str]]:
    members: list[tuple[Path, str]] = []
    for path in files:
        if selected_file_stat(path, root=root) is None:
            raise SystemExit(
                f"release package: refusing excluded archive input: {archive_rel(path, root=root)}"
            )
        members.append((path, archive_rel(path, root=root)))
    return members


def tar_info(st: os.stat_result, arcname: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(arcname)
    mode = stat.S_IMODE(st.st_mode)
    info.mode = mode if mode & 0o111 else 0o644
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.size = st.st_size
    info.mtime = FIXED_MTIME
    return info


def open_extra_file(path: Path) -> tuple[BinaryIO, os.stat_result]:
    try:
        before = path.lstat()
    except OSError as exc:
        raise SystemExit(f"release package: cannot stat extra file {path}: {exc}") from exc
    if is_symlink_or_reparse(before):
        raise SystemExit(f"release package: refusing symlink or reparse point: {path}")
    if not stat.S_ISREG(before.st_mode):
        raise SystemExit(f"release package: extra file is not regular: {path}")
    handle: BinaryIO | None = None
    try:
        handle = path.open("rb")
        opened = os.fstat(handle.fileno())
    except OSError as exc:
        if handle is not None:
            handle.close()
        raise SystemExit(f"release package: cannot open extra file {path}: {exc}") from exc
    if not stat.S_ISREG(opened.st_mode) or file_identity(before) != file_identity(opened):
        handle.close()
        raise SystemExit(f"release package: extra file changed while packaging: {path}")
    return handle, opened


def add_tar_entry(
    tf: tarfile.TarFile,
    path: Path,
    arcname: str,
    *,
    root: Path,
    extra: bool,
    executable: bool,
) -> None:
    handle, st = open_extra_file(path) if extra else open_selected_file(path, root=root)
    info = tar_info(st, arcname)
    if executable:
        info.mode = 0o755
    with handle:
        tf.addfile(info, handle)


def add_zip_entry(
    zf: zipfile.ZipFile,
    path: Path,
    arcname: str,
    *,
    root: Path,
    extra: bool,
    executable: bool,
) -> None:
    handle, st = open_extra_file(path) if extra else open_selected_file(path, root=root)
    zi = zipfile.ZipInfo(arcname, ZIP_EPOCH)
    mode = 0o755 if executable else stat.S_IMODE(st.st_mode)
    if not (mode & 0o111):
        mode = 0o644
    zi.external_attr = (mode & 0xFFFF) << 16
    zi.compress_type = zipfile.ZIP_DEFLATED
    with handle:
        zf.writestr(zi, handle.read())


def write_archive_members(
    *,
    prefix: str,
    files: list[Path],
    extras: Sequence[tuple[Path, str, bool]] = (),
    root: Path = ROOT,
    add,
) -> None:
    for path, rp in archive_members(files, root=root):
        add(path, f"{prefix}/{rp}", extra=False, executable=False)
    for path, rp, executable in extras:
        add(path, f"{prefix}/{rp}", extra=True, executable=executable)


def build_tar_gz(
    out: Path,
    prefix: str,
    files: list[Path],
    *,
    root: Path = ROOT,
    extras: Sequence[tuple[Path, str, bool]] = (),
) -> None:
    with out.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=FIXED_MTIME) as gz:
            with tarfile.open(fileobj=gz, mode="w") as tf:
                write_archive_members(
                    prefix=prefix,
                    files=files,
                    extras=extras,
                    root=root,
                    add=lambda path, arcname, extra, executable: add_tar_entry(
                        tf, path, arcname, root=root, extra=extra, executable=executable
                    ),
                )


def build_zip(
    out: Path,
    prefix: str,
    files: list[Path],
    *,
    root: Path = ROOT,
    extras: Sequence[tuple[Path, str, bool]] = (),
) -> None:
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        write_archive_members(
            prefix=prefix,
            files=files,
            extras=extras,
            root=root,
            add=lambda path, arcname, extra, executable: add_zip_entry(
                zf, path, arcname, root=root, extra=extra, executable=executable
            ),
        )


def zstd_frame_uncompressed(data: bytes) -> bytes:
    header = bytearray(ZSTD_MAGIC)
    header.append(0xE0)
    header += len(data).to_bytes(8, "little")
    offset = 0
    empty = not data
    while offset < len(data) or empty:
        chunk = data[offset : offset + ZSTD_MAX_RAW_BLOCK]
        last = offset + len(chunk) >= len(data)
        block_header = (len(chunk) << 3) | int(last)
        header += block_header.to_bytes(3, "little")
        header += chunk
        offset += len(chunk)
        empty = False
        if last:
            break
    return bytes(header)


def zstd_frame_uncompressed_decode(frame: bytes) -> bytes:
    if len(frame) < 13 or frame[:4] != ZSTD_MAGIC or frame[4] != 0xE0:
        raise SystemExit("release package: unsupported uncompressed zstd frame")
    expected = int.from_bytes(frame[5:13], "little")
    offset = 13
    parts: list[bytes] = []
    while offset + 3 <= len(frame):
        header = int.from_bytes(frame[offset : offset + 3], "little")
        offset += 3
        last = header & 1
        if ((header >> 1) & 3) != 0:
            raise SystemExit("release package: expected raw zstd blocks")
        size = header >> 3
        parts.append(frame[offset : offset + size])
        offset += size
        if last:
            break
    data = b"".join(parts)
    if len(data) != expected:
        raise SystemExit("release package: zstd frame size mismatch")
    return data


def compress_file_zstd(src: Path, dest: Path) -> str:
    try:
        import zstandard
    except ImportError:
        zstandard = None
    if zstandard is not None:
        with src.open("rb") as inf, dest.open("wb") as outf:
            zstandard.ZstdCompressor(level=19, threads=1).copy_stream(inf, outf)
        return "zstandard"
    try:
        from compression import zstd as compression_zstd
    except ImportError:
        compression_zstd = None
    if compression_zstd is not None:
        dest.write_bytes(compression_zstd.compress(src.read_bytes(), level=19))
        return "compression.zstd"
    zstd = shutil.which("zstd")
    if zstd is not None:
        subprocess.run(
            [zstd, "-19", "-T1", "-f", "-o", str(dest), "--", str(src)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return "zstd-cli"
    dest.write_bytes(zstd_frame_uncompressed(src.read_bytes()))
    return "uncompressed-frame"


def decompress_zstd_bytes(data: bytes) -> bytes:
    try:
        import zstandard
    except ImportError:
        zstandard = None
    if zstandard is not None:
        return zstandard.ZstdDecompressor().decompress(data)
    try:
        from compression import zstd as compression_zstd
    except ImportError:
        compression_zstd = None
    if compression_zstd is not None:
        return compression_zstd.decompress(data)
    zstd = shutil.which("zstd")
    if zstd is not None:
        return subprocess.run(
            [zstd, "-d", "-c"],
            input=data,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    return zstd_frame_uncompressed_decode(data)


def build_tar_zst(
    out: Path,
    prefix: str,
    files: list[Path],
    *,
    root: Path = ROOT,
    extras: Sequence[tuple[Path, str, bool]] = (),
) -> None:
    tmp = out.with_name(out.name + ".tar.tmp")
    try:
        with tmp.open("wb") as raw:
            with tarfile.open(fileobj=raw, mode="w") as tf:
                write_archive_members(
                    prefix=prefix,
                    files=files,
                    extras=extras,
                    root=root,
                    add=lambda path, arcname, extra, executable: add_tar_entry(
                        tf, path, arcname, root=root, extra=extra, executable=executable
                    ),
                )
        compress_file_zstd(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)


def validate_platform(platform: Optional[str]) -> str:
    name = "" if platform is None else platform.strip()
    if name not in TOOLCHAIN_PLATFORMS:
        raise SystemExit(
            "release package: platform must be one of " + ", ".join(TOOLCHAIN_PLATFORMS)
        )
    return name


def compiler_arcname(platform: str) -> str:
    return "bin/ouro1.exe" if platform == "windows" else "bin/ouro1"


def compiler_magic_ok(head: bytes, platform: str) -> bool:
    if platform == "windows":
        return head.startswith(b"MZ")
    if platform.startswith("linux"):
        return head.startswith(b"\x7fELF")
    if platform.startswith("darwin"):
        return head[:4] in MACHO_MAGICS
    return False


def resolve_compiler(path: Path, platform: str) -> Path:
    candidate = path if path.is_absolute() else Path.cwd() / path
    if not candidate.is_file() and platform == "windows":
        exe = candidate.with_suffix(".exe") if candidate.suffix != ".exe" else candidate
        if exe.is_file():
            candidate = exe
    if not candidate.is_file():
        raise SystemExit(f"release package: compiler not found: {path}")
    try:
        st = candidate.lstat()
    except OSError as exc:
        raise SystemExit(f"release package: cannot stat compiler {candidate}: {exc}") from exc
    if is_symlink_or_reparse(st) or not stat.S_ISREG(st.st_mode):
        raise SystemExit(f"release package: compiler must be a regular file: {candidate}")
    if st.st_size < COMPILER_MIN_BYTES:
        raise SystemExit(
            f"release package: compiler is too small to be a host toolchain: {candidate}"
        )
    with candidate.open("rb") as handle:
        head = handle.read(4)
    if not compiler_magic_ok(head, platform):
        raise SystemExit(
            f"release package: compiler image does not match platform {platform}: {candidate}"
        )
    return candidate.resolve()


def posix_wrapper_text() -> str:
    return (
        "#!/bin/sh\n"
        "set -eu\n"
        'ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\n'
        'export OURO_ROOT="$ROOT"\n'
        'if [ -x "$ROOT/bin/ouro1.exe" ]; then\n'
        '  export OURO1_COMPILER="$ROOT/bin/ouro1.exe"\n'
        "else\n"
        '  export OURO1_COMPILER="$ROOT/bin/ouro1"\n'
        "fi\n"
        'if [ -f "$ROOT/scripts/ouro1.sh" ]; then\n'
        '  exec /bin/sh "$ROOT/scripts/ouro1.sh" "$@"\n'
        "fi\n"
        'exec "$OURO1_COMPILER" "$@"\n'
    )


def windows_wrapper_text() -> str:
    return (
        "@echo off\r\n"
        "setlocal\r\n"
        'set "OURO_ROOT=%~dp0.."\r\n'
        'set "OURO1_COMPILER=%~dp0ouro1.exe"\r\n'
        'if exist "%OURO_ROOT%\\scripts\\ouro1.sh" (\r\n'
        "  where bash >nul 2>&1 && (\r\n"
        '    bash "%OURO_ROOT%\\scripts\\ouro1.sh" %*\r\n'
        "    exit /b %ERRORLEVEL%\r\n"
        "  )\r\n"
        ")\r\n"
        '"%OURO1_COMPILER%" %*\r\n'
    )


def toolchain_prefix(version: str, platform: str) -> str:
    return f"{PACKAGE_NAME}-{version}-{platform}"


def toolchain_archive_names(version: str, platform: str) -> tuple[str, str]:
    prefix = toolchain_prefix(version, platform)
    return f"{prefix}.tar.zst", f"{prefix}.zip"


def required_published_names(version: str) -> list[str]:
    names: list[str] = []
    for platform in TOOLCHAIN_PLATFORMS:
        names.extend(toolchain_archive_names(version, platform))
    return names


def write_sha256sums(out: Path) -> list[tuple[str, str]]:
    sums: list[tuple[str, str]] = []
    for path in sorted(out.iterdir(), key=lambda p: p.name):
        if path.is_file() and path.name != "SHA256SUMS":
            sums.append((sha256_file(path), path.name))
    (out / "SHA256SUMS").write_text(
        "".join(f"{h}  {name}\n" for h, name in sums), encoding="utf-8"
    )
    return sums


def manifest_version_in(out: Path) -> str:
    matches = sorted(out.glob(f"{PACKAGE_NAME}-*-release-manifest.json"))
    if len(matches) != 1:
        raise SystemExit(
            f"release package: expected one release manifest in {out}, found {len(matches)}"
        )
    data, error = parse_json_value(matches[0].read_text(encoding="utf-8"))
    if error is not None or not isinstance(data, dict):
        raise SystemExit(f"release package: invalid release manifest: {matches[0].name}")
    version = str(data.get("version") or "")
    if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None:
        raise SystemExit(f"release package: release manifest has no version: {matches[0].name}")
    return version


def verify_published_archives(out: Path, version: str) -> list[str]:
    names = required_published_names(version)
    missing = [name for name in names if not (out / name).is_file()]
    if missing:
        raise SystemExit("release package: missing toolchain archives: " + ", ".join(missing))
    small = [
        name
        for name in names
        if (out / name).stat().st_size < ARCHIVE_MIN_BYTES
    ]
    if small:
        raise SystemExit("release package: toolchain archives are empty: " + ", ".join(small))
    leftovers = sorted(
        path.name
        for path in out.iterdir()
        if path.name.endswith("-source.tar.gz") or path.name.endswith("-source.zip")
    )
    if leftovers:
        raise SystemExit(
            "release package: source archives are not published toolchain assets: "
            + ", ".join(leftovers)
        )
    return names


def pack_toolchain(
    out: Path,
    version: str,
    platform: str,
    compiler: Path,
    files: list[Path],
    *,
    root: Path = ROOT,
) -> tuple[Path, Path]:
    for path in files:
        rp = archive_rel(path, root=root)
        if rp in RESERVED_TOOLCHAIN_PATHS:
            raise SystemExit(f"release package: repository already contains {rp}")
    prefix = toolchain_prefix(version, platform)
    tar_name, zip_name = toolchain_archive_names(version, platform)
    staging = out / f".toolchain-staging-{platform}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    extras: list[tuple[Path, str, bool]] = [
        (compiler, compiler_arcname(platform), True),
    ]
    posix_wrapper = staging / "ouro"
    posix_wrapper.write_text(posix_wrapper_text(), encoding="utf-8", newline="\n")
    extras.append((posix_wrapper, "bin/ouro", True))
    if platform == "windows":
        cmd_wrapper = staging / "ouro.cmd"
        cmd_wrapper.write_bytes(windows_wrapper_text().encode("ascii"))
        extras.append((cmd_wrapper, "bin/ouro.cmd", True))
    try:
        tar_path = out / tar_name
        zip_path = out / zip_name
        build_tar_zst(tar_path, prefix, files, root=root, extras=extras)
        build_zip(zip_path, prefix, files, root=root, extras=extras)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return tar_path, zip_path


def expect_rejected(action, expected: str) -> None:
    try:
        action()
    except SystemExit as exc:
        if expected not in str(exc):
            raise SystemExit(
                f"release package self-test: unexpected rejection: {exc}"
            ) from exc
        return
    raise SystemExit(f"release package self-test: expected rejection containing {expected!r}")


def version_self_tests() -> None:
    with (
        patch(__name__ + ".parse_seal_version", return_value="0.1.0") as seal,
        patch(__name__ + ".parse_vscode_version", return_value="0.1.0") as package,
        patch(__name__ + ".parse_package_lock_version", return_value="0.1.0") as lock,
    ):
        for tag in (None, "v0.1.0", "refs/tags/v0.1.0"):
            version, evidence = validate_versions(tag)
            if version != "0.1.0" or evidence != [
                "Ouro.seal=0.1.0", "editors/vscode/package-lock.json=0.1.0",
                "editors/vscode/package.json=0.1.0",
            ]:
                raise SystemExit("release package self-test: version baseline changed")
        expect_rejected(lambda: validate_versions("v9.0.0"), "does not match version")
        for owner in (seal, package, lock):
            for invalid in ("", "9.0.0"):
                owner.return_value = invalid
                expect_rejected(lambda: validate_versions(None), "version drift")
            owner.return_value = "0.1.0"
        seal.return_value = package.return_value = lock.return_value = ""
        expect_rejected(lambda: validate_versions(None), "version drift")


def run_self_tests() -> None:
    version_self_tests()
    self_test_root = ROOT / "_build"
    self_test_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="ouro-release-file-selftest-", dir=self_test_root
    ) as d:
        root = Path(d)
        (root / "regular.txt").write_bytes(b"regular\n")
        (root / "directory").mkdir()
        git(["init", "--quiet"], root=root, check=True)
        targets = {
            "external": "../../outside.txt",
            "excluded": "_build/secret.txt",
            "broken": "missing.txt",
            "file": "regular.txt",
            "directory": "directory",
        }
        for name in targets:
            link = f"link-{name}"
            index_output = f"120000 {'0' * 40} 0\t{link}\0"
            expect_rejected(
                lambda output=index_output: parse_tracked_candidates(output, root=root),
                f"tracked symlink: {link}",
            )

        tracked = root / "tracked.txt"
        untracked = root / "untracked.txt"
        tracked.write_bytes(b"tracked\n")
        untracked.write_bytes(b"untracked\n")
        git(["add", "--", tracked.name], root=root, check=True)
        labels = {archive_rel(path, root=root) for path in list_files(root=root)}
        if not {"tracked.txt", "untracked.txt"}.issubset(labels):
            raise SystemExit("release package self-test: regular files were not selected")
        expect_rejected(
            lambda: archive_rel(root / "nested" / ".." / "escape", root=root),
            "invalid repository path",
        )
        expect_rejected(
            lambda: archive_rel(root.parent / "escape", root=root),
            "outside repository root",
        )

        tar_path = root / "control.tar.gz"
        zip_path = root / "control.zip"
        build_tar_gz(tar_path, "control", [tracked, untracked], root=root)
        build_zip(zip_path, "control", [tracked, untracked], root=root)
        with tarfile.open(tar_path, "r:gz") as tf:
            tar_bytes = {
                member.name: tf.extractfile(member).read()
                for member in tf.getmembers()
                if member.isfile()
            }
        with zipfile.ZipFile(zip_path) as zf:
            zip_bytes = {name: zf.read(name) for name in zf.namelist()}
        expected = {
            "control/tracked.txt": b"tracked\n",
            "control/untracked.txt": b"untracked\n",
        }
        if tar_bytes != expected or zip_bytes != expected:
            raise SystemExit("release package self-test: regular archive contents changed")

    with tempfile.TemporaryDirectory(
        prefix="ouro-release-reparse-selftest-", dir=self_test_root
    ) as d:
        container = Path(d)
        root = container / "repo"
        outside = container / "outside"
        root.mkdir()
        outside.mkdir()
        (outside / "secret.txt").write_text("outside\n", encoding="utf-8")
        link = root / "linked"
        if os.name == "nt":
            junction_result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if junction_result.returncode != 0:
                raise SystemExit(
                    "release package self-test: cannot create Windows junction: "
                    + junction_result.stderr.strip()
                )
        else:
            link.symlink_to(outside, target_is_directory=True)
        try:
            unsafe = link / "secret.txt"
            expect_rejected(
                lambda: allowed_file(unsafe, root=root), "symlink or reparse point"
            )
            expect_rejected(
                lambda: build_tar_gz(root / "unsafe.tar.gz", "unsafe", [unsafe], root=root),
                "symlink or reparse point",
            )
            expect_rejected(
                lambda: build_zip(root / "unsafe.zip", "unsafe", [unsafe], root=root),
                "symlink or reparse point",
            )
        finally:
            if os.name == "nt":
                os.rmdir(link)
            else:
                link.unlink()

    changelog_cut_self_tests()
    toolchain_self_tests()
    print(
        "RELEASE_PACKAGE_SELF_TEST: PASS versions=11 tracked_links=5 "
        "archive_formats=2 reparse=1 changelog_cut=4 toolchains=6"
    )


def fake_compiler_bytes(platform: str) -> bytes:
    if platform == "windows":
        head = b"MZ"
    elif platform.startswith("linux"):
        head = b"\x7fELF"
    else:
        head = b"\xcf\xfa\xed\xfe"
    return head + (b"\0" * (COMPILER_MIN_BYTES - len(head)))


def toolchain_self_tests() -> None:
    expect_rejected(lambda: validate_platform("windows_aarch64"), "platform must be one of")
    expect_rejected(lambda: validate_platform(""), "platform must be one of")
    self_test_root = ROOT / "_build"
    self_test_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="ouro-release-toolchain-selftest-", dir=self_test_root
    ) as d:
        root = Path(d)
        out = root / "out"
        out.mkdir()
        source = root / "README.md"
        source.write_bytes(b"readme\n")
        compiler = root / "ouro1"
        compiler.write_bytes(fake_compiler_bytes("linux"))
        expect_rejected(
            lambda: resolve_compiler(root / "missing", "linux"),
            "compiler not found",
        )
        tiny = root / "tiny"
        tiny.write_bytes(b"\x7fELF" + b"\0" * 16)
        expect_rejected(lambda: resolve_compiler(tiny, "linux"), "too small")
        expect_rejected(
            lambda: resolve_compiler(compiler, "windows"),
            "does not match platform windows",
        )
        pack_toolchain(out, "0.1.0", "linux", compiler, [source], root=root)
        tar_path = out / "ouro-0.1.0-linux.tar.zst"
        zip_path = out / "ouro-0.1.0-linux.zip"
        raw = decompress_zstd_bytes(tar_path.read_bytes())
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r") as tf:
            tar_names = {member.name for member in tf.getmembers() if member.isfile()}
            ouro1 = tf.extractfile("ouro-0.1.0-linux/bin/ouro1")
            if ouro1 is None or ouro1.read()[:4] != b"\x7fELF":
                raise SystemExit("release package self-test: linux tar.zst missing compiler")
        with zipfile.ZipFile(zip_path) as zf:
            zip_names = set(zf.namelist())
            if zf.read("ouro-0.1.0-linux/bin/ouro1")[:4] != b"\x7fELF":
                raise SystemExit("release package self-test: linux zip missing compiler")
        expected = {
            "ouro-0.1.0-linux/README.md",
            "ouro-0.1.0-linux/bin/ouro1",
            "ouro-0.1.0-linux/bin/ouro",
        }
        if not expected.issubset(tar_names) or not expected.issubset(zip_names):
            raise SystemExit("release package self-test: toolchain archive layout changed")
        win_out = root / "win"
        win_out.mkdir()
        win_compiler = root / "ouro1.exe"
        win_compiler.write_bytes(fake_compiler_bytes("windows"))
        pack_toolchain(win_out, "0.1.0", "windows", win_compiler, [source], root=root)
        with zipfile.ZipFile(win_out / "ouro-0.1.0-windows.zip") as zf:
            if "ouro-0.1.0-windows/bin/ouro1.exe" not in zf.namelist():
                raise SystemExit("release package self-test: windows zip missing ouro1.exe")
            if "ouro-0.1.0-windows/bin/ouro.cmd" not in zf.namelist():
                raise SystemExit("release package self-test: windows zip missing ouro.cmd")
        reserved = root / "bin"
        reserved.mkdir()
        clash = reserved / "ouro1"
        clash.write_bytes(b"clash\n")
        expect_rejected(
            lambda: pack_toolchain(out, "0.1.0", "linux", compiler, [clash], root=root),
            "repository already contains bin/ouro1",
        )
        verify_dir = root / "published"
        verify_dir.mkdir()
        (verify_dir / "ouro-0.1.0-release-manifest.json").write_text(
            json.dumps({"version": "0.1.0"}), encoding="utf-8"
        )
        expect_rejected(
            lambda: verify_published_archives(verify_dir, "0.1.0"),
            "missing toolchain archives",
        )
        for name in required_published_names("0.1.0"):
            (verify_dir / name).write_bytes(b"archive-placeholder-bytes-enough\n")
        (verify_dir / "ouro-0.1.0-source.zip").write_bytes(b"old-source\n")
        expect_rejected(
            lambda: verify_published_archives(verify_dir, "0.1.0"),
            "source archives are not published",
        )
        (verify_dir / "ouro-0.1.0-source.zip").unlink()
        if verify_published_archives(verify_dir, "0.1.0") != required_published_names("0.1.0"):
            raise SystemExit("release package self-test: published archive inventory changed")
        if manifest_version_in(verify_dir) != "0.1.0":
            raise SystemExit("release package self-test: manifest version lookup failed")


CHANGELOG_REPO = "https://github.com/eluvane/ouro"
CHANGELOG_UNRELEASED = "## [Unreleased]"
CHANGELOG_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
CHANGELOG_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def changelog_span_end(text: str, start: int) -> int:
    rest = text[start:]
    ends = [len(text)]
    nxt = rest.find("\n## [", 1)
    if nxt != -1:
        ends.append(start + nxt)
    for mark in ("\n[Unreleased]:", "\n<p align="):
        pos = text.find(mark, start)
        if pos != -1:
            ends.append(pos)
    return min(ends)


def changelog_section(version: str) -> str:
    text = read("CHANGELOG.md")
    header = f"## [{version}]"
    start = text.find(header)
    if start < 0:
        raise SystemExit(f"release package: CHANGELOG.md has no {header} section")
    body = text[start:changelog_span_end(text, start)].strip()
    if not body:
        raise SystemExit(f"release package: CHANGELOG.md section {header} is empty")
    return body


def cut_unreleased_text(
    text: str,
    version: str,
    date: str,
    *,
    repo: str = CHANGELOG_REPO,
) -> str:
    if CHANGELOG_VERSION_RE.match(version) is None:
        raise SystemExit(f"release package: invalid changelog version {version!r}")
    if CHANGELOG_DATE_RE.match(date) is None:
        raise SystemExit(f"release package: invalid changelog date {date!r}")
    if f"## [{version}]" in text:
        raise SystemExit(f"release package: CHANGELOG.md already has ## [{version}]")
    idx = text.find(CHANGELOG_UNRELEASED)
    if idx < 0:
        raise SystemExit("release package: CHANGELOG.md has no ## [Unreleased] section")
    body_start = idx + len(CHANGELOG_UNRELEASED)
    while body_start < len(text) and text[body_start] in "\r\n":
        body_start += 1
    body_end = changelog_span_end(text, idx)
    body = text[body_start:body_end].strip()
    if not body:
        raise SystemExit("release package: [Unreleased] is empty; nothing to cut")
    previous = text[body_end:]
    older = re.findall(r"^## \[([0-9]+\.[0-9]+\.[0-9]+)\]", previous, flags=re.MULTILINE)
    version_part = previous
    for mark in ("\n[Unreleased]:", "\n<p align="):
        pos = version_part.find(mark)
        if pos != -1:
            version_part = version_part[:pos]
    version_part = version_part.rstrip()
    if version_part:
        version_part += "\n\n"
    footer = ""
    foot = text.find("\n<p align=")
    if foot != -1:
        footer = text[foot:]
    if not footer.endswith("\n"):
        footer += "\n"
    links = [f"[Unreleased]: {repo}/compare/v{version}...HEAD"]
    if older:
        links.append(f"[{version}]: {repo}/compare/v{older[0]}...v{version}")
        for i, ver in enumerate(older):
            nxt = older[i + 1] if i + 1 < len(older) else None
            if nxt is None:
                links.append(f"[{ver}]: {repo}/releases/tag/v{ver}")
            else:
                links.append(f"[{ver}]: {repo}/compare/v{nxt}...v{ver}")
    else:
        links.append(f"[{version}]: {repo}/releases/tag/v{version}")
    prelude = text[:idx] + CHANGELOG_UNRELEASED + "\n\n"
    released = f"## [{version}] - {date}\n\n{body}\n\n"
    return prelude + released + version_part + "\n".join(links) + "\n" + footer


def changelog_cut_self_tests() -> None:
    sample = (
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        "- New thing\n\n"
        "## [0.1.0] - 2026-09-12\n\n"
        "First release.\n\n"
        "[Unreleased]: https://github.com/eluvane/ouro/compare/v0.1.0...HEAD\n"
        "[0.1.0]: https://github.com/eluvane/ouro/releases/tag/v0.1.0\n"
        "\n<p align=\"center\">\nfooter\n</p>\n"
    )
    cut = cut_unreleased_text(sample, "0.1.1", "2026-09-19")
    if "## [Unreleased]\n\n## [0.1.1] - 2026-09-19\n\n- New thing\n" not in cut:
        raise SystemExit("release package self-test: cut did not reset Unreleased")
    if "- New thing" in cut.split("## [0.1.1]", 1)[0]:
        raise SystemExit("release package self-test: Unreleased still holds cut notes")
    if "[Unreleased]: https://github.com/eluvane/ouro/compare/v0.1.1...HEAD" not in cut:
        raise SystemExit("release package self-test: missing Unreleased compare link")
    if "[0.1.1]: https://github.com/eluvane/ouro/compare/v0.1.0...v0.1.1" not in cut:
        raise SystemExit("release package self-test: missing version compare link")
    if "First release." not in cut or "<p align=" not in cut:
        raise SystemExit("release package self-test: cut dropped earlier release or footer")
    empty = sample.replace("- New thing\n\n", "")
    expect_rejected(lambda: cut_unreleased_text(empty, "0.1.1", "2026-09-19"), "[Unreleased] is empty")
    expect_rejected(lambda: cut_unreleased_text(sample, "0.1.0", "2026-09-19"), "already has")
    expect_rejected(lambda: cut_unreleased_text(sample, "v0.1.1", "2026-09-19"), "invalid changelog version")


def write_release_notes(path: Path, version: str) -> None:
    path.write_text(f"# Ouro v{version}\n\n{changelog_section(version)}\n", encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="_build/release", help="release output directory")
    ap.add_argument("--expect-tag", default=None, help="require tag name to match v<version>")
    ap.add_argument("--allow-dirty", action="store_true", help="allow packaging from a dirty checkout")
    ap.add_argument("--check", action="store_true", help="validate release metadata without writing archives")
    ap.add_argument("--self-test", action="store_true", help="run release path and archive regression checks")
    ap.add_argument(
        "--toolchain",
        action="store_true",
        help="write ouro-<version>-<platform>.tar.zst and .zip for one host compiler",
    )
    ap.add_argument("--platform", default=None, help="host platform name, matching Lean 4 suffixes")
    ap.add_argument("--compiler", default=None, help="path to the built host ouro1 for --toolchain")
    ap.add_argument(
        "--source",
        action="store_true",
        help="also write source-only tar.gz/zip archives; not uploaded to GitHub Releases",
    )
    ap.add_argument(
        "--checksums-only",
        action="store_true",
        help="rewrite SHA256SUMS for files already in --out",
    )
    ap.add_argument(
        "--verify-dir",
        action="store_true",
        help="require the ten Lean-style toolchain archives in --out",
    )
    ap.add_argument(
        "--cut-changelog",
        action="store_true",
        help="move [Unreleased] under the seal version and reset [Unreleased]",
    )
    ap.add_argument("--date", default=None, help="YYYY-MM-DD for --cut-changelog; default is UTC today")
    args = ap.parse_args(argv)

    if args.self_test:
        run_self_tests()
        if not args.check and not args.cut_changelog and not args.checksums_only and not args.verify_dir:
            return 0

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out

    if args.checksums_only or args.verify_dir:
        out.mkdir(parents=True, exist_ok=True)
        version = None
        if args.verify_dir:
            version = manifest_version_in(out)
            verify_published_archives(out, version)
        sums = write_sha256sums(out)
        print(
            "RELEASE_PACKAGE: PASS "
            f"verify_dir={int(args.verify_dir)} version={version or '-'} "
            f"out={rel(out)} artifacts={len(sums)}"
        )
        for h, name in sums:
            print(f"RELEASE_SHA256 {h}  {name}")
        return 0

    if args.cut_changelog:
        version = parse_seal_version()
        date = args.date or datetime.now(UTC).date().isoformat()
        path = ROOT / "CHANGELOG.md"
        try:
            current = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise SystemExit(f"release package: cannot read CHANGELOG.md: {exc}") from exc
        path.write_text(cut_unreleased_text(current, version, date), encoding="utf-8")
        print(f"CHANGELOG_CUT: PASS version={version} date={date}")
        if not args.check:
            return 0

    version, version_evidence = validate_versions(args.expect_tag)
    generated = validate_generated_artifacts()
    dirty = git_dirty()
    if dirty and args.expect_tag and not args.allow_dirty:
        raise SystemExit("release package: refusing tagged release from dirty checkout")

    files = list_files()
    required = ["README.md", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md", "docs/stability.md", "docs/releasing.md"]
    missing = [p for p in required if not (ROOT / p).is_file()]
    if missing:
        raise SystemExit("release package: missing required release docs: " + ", ".join(missing))

    platform = None
    compiler = None
    if args.toolchain or args.platform or args.compiler:
        if not args.toolchain:
            raise SystemExit("release package: --platform and --compiler require --toolchain")
        platform = validate_platform(args.platform)
        if not args.compiler:
            raise SystemExit("release package: --toolchain requires --compiler")
        compiler = resolve_compiler(Path(args.compiler), platform)

    out.mkdir(parents=True, exist_ok=True)
    prefix = f"{PACKAGE_NAME}-{version}"
    manifest = {
        "kind": REPORT_KIND,
        "package": PACKAGE_NAME,
        "version": version,
        "tag": "v" + version,
        "git_commit": git_commit(),
        "dirty": dirty,
        "file_count": len(files),
        "source_epoch": FIXED_MTIME,
        "version_evidence": version_evidence,
        "generated_artifacts": generated,
        "published_artifacts": required_published_names(version),
        "policy": {
            "artifacts": (
                "host toolchain archives ouro-<version>-<platform>.{tar.zst,zip} "
                "plus checksums; no binary signing or SLSA claim"
            ),
            "platforms": list(TOOLCHAIN_PLATFORMS),
            "host_compiler": (
                "C-hosted ouro1 built on the named runner; program output remains "
                "Windows x86-64 PE"
            ),
            "generated_artifacts": "committed stage0 seeds must match docs/generated_artifact_hashes.sha256 before packaging",
            "reproducibility": "archive member metadata is normalized; package bytes are stable for the same source tree and compression implementation",
        },
        "files": [archive_rel(p) for p in files],
    }
    if platform is not None and compiler is not None:
        manifest["toolchain"] = {
            "platform": platform,
            "compiler": compiler_arcname(platform),
            "compiler_sha256": sha256_file(compiler),
            "compiler_bytes": compiler.stat().st_size,
        }
    write_json_atomic(out / f"{prefix}-release-manifest.json", manifest)
    write_release_notes(out / "release-notes.md", version)

    if not args.check:
        if args.source:
            build_tar_gz(out / f"{prefix}-source.tar.gz", prefix, files)
            build_zip(out / f"{prefix}-source.zip", prefix, files)
        if platform is not None and compiler is not None:
            pack_toolchain(out, version, platform, compiler, files)

    sums = write_sha256sums(out)

    report = {
        "kind": REPORT_KIND,
        "pass": True,
        "check_only": args.check,
        "out": rel(out),
        "version": version,
        "tag": "v" + version,
        "dirty": dirty,
        "file_count": len(files),
        "platform": platform,
        "artifacts": [name for _, name in sums],
    }
    write_json_atomic(out / "release-package-report.json", report)
    print(
        f"RELEASE_PACKAGE: PASS version={version} files={len(files)} "
        f"out={rel(out)} check_only={int(args.check)} platform={platform or '-'}"
    )
    for h, name in sums:
        print(f"RELEASE_SHA256 {h}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
