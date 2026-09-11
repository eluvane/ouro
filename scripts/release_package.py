#!/usr/bin/env python3
"""Build deterministic Ouro source release artifacts and checksums.

The current project can reliably package source + committed bootstrap seeds. It
must not pretend to publish signed binaries or SLSA attestations. This script
therefore creates source tar/zip archives, a release manifest, release notes, and
SHA256SUMS after validating the version baseline and generated-artifact hashes.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import stat
import subprocess
import tarfile
import tempfile
import zipfile
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


def build_tar_gz(
    out: Path, prefix: str, files: list[Path], *, root: Path = ROOT
) -> None:
    members = archive_members(files, root=root)
    with out.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=FIXED_MTIME) as gz:
            with tarfile.open(fileobj=gz, mode="w") as tf:
                for path, rp in members:
                    f, st = open_selected_file(path, root=root)
                    info = tar_info(st, f"{prefix}/{rp}")
                    with f:
                        tf.addfile(info, f)


def build_zip(out: Path, prefix: str, files: list[Path], *, root: Path = ROOT) -> None:
    members = archive_members(files, root=root)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path, rp in members:
            zi = zipfile.ZipInfo(f"{prefix}/{rp}", ZIP_EPOCH)
            f, st = open_selected_file(path, root=root)
            mode = stat.S_IMODE(st.st_mode)
            if not (mode & 0o111):
                mode = 0o644
            zi.external_attr = (mode & 0xFFFF) << 16
            zi.compress_type = zipfile.ZIP_DEFLATED
            with f:
                zf.writestr(zi, f.read())


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

    print("RELEASE_PACKAGE_SELF_TEST: PASS versions=11 tracked_links=5 archive_formats=2 reparse=1")


def changelog_section(version: str) -> str:
    text = read("CHANGELOG.md")
    header = f"## [{version}]"
    start = text.find(header)
    if start < 0:
        raise SystemExit(f"release package: CHANGELOG.md has no {header} section")
    rest = text[start:]
    next_heading = rest.find("\n## [", 1)
    footer = rest.find("\n<p align=")
    end = len(rest)
    if next_heading != -1:
        end = min(end, next_heading)
    if footer != -1:
        end = min(end, footer)
    body = rest[:end].strip()
    if not body:
        raise SystemExit(f"release package: CHANGELOG.md section {header} is empty")
    return body


def write_release_notes(path: Path, version: str) -> None:
    text = (
        f"# Ouro v{version}\n\n"
        f"{changelog_section(version)}\n\n"
        "This is a source archive plus checksums. It does not claim signed "
        "binaries, SLSA provenance, or a stable 1.0 language surface.\n"
    )
    path.write_text(text, encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="_build/release", help="release output directory")
    ap.add_argument("--expect-tag", default=None, help="require tag name to match v<version>")
    ap.add_argument("--allow-dirty", action="store_true", help="allow packaging from a dirty checkout")
    ap.add_argument("--check", action="store_true", help="validate release metadata without writing archives")
    ap.add_argument("--self-test", action="store_true", help="run release path and archive regression checks")
    args = ap.parse_args(argv)

    if args.self_test:
        run_self_tests()
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

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
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
        "policy": {
            "artifacts": "source archives plus checksums; no binary/signing/SLSA claim",
            "generated_artifacts": "committed stage0 seeds must match docs/generated_artifact_hashes.sha256 before packaging",
            "reproducibility": "archive member metadata is normalized; package bytes are stable for the same source tree and compression implementation",
        },
        "files": [archive_rel(p) for p in files],
    }
    write_json_atomic(out / f"{prefix}-release-manifest.json", manifest)
    write_release_notes(out / "release-notes.md", version)

    if not args.check:
        tar_path = out / f"{prefix}-source.tar.gz"
        zip_path = out / f"{prefix}-source.zip"
        build_tar_gz(tar_path, prefix, files)
        build_zip(zip_path, prefix, files)

    sums: list[tuple[str, str]] = []
    for path in sorted(out.iterdir(), key=lambda p: p.name):
        if path.is_file() and path.name != "SHA256SUMS":
            sums.append((sha256_file(path), path.name))
    (out / "SHA256SUMS").write_text("".join(f"{h}  {name}\n" for h, name in sums), encoding="utf-8")

    report = {
        "kind": REPORT_KIND,
        "pass": True,
        "check_only": args.check,
        "out": rel(out),
        "version": version,
        "tag": "v" + version,
        "dirty": dirty,
        "file_count": len(files),
        "artifacts": [name for _, name in sums],
    }
    write_json_atomic(out / "release-package-report.json", report)
    print(f"RELEASE_PACKAGE: PASS version={version} files={len(files)} out={rel(out)} check_only={int(args.check)}")
    for h, name in sums:
        print(f"RELEASE_SHA256 {h}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
