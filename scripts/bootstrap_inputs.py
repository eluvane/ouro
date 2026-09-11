#!/usr/bin/env python3
"""Read and reproduce the versioned historical C-bootstrap inputs.

The archive is build provenance. Its historical Ouro sources never replace the
current compiler sources or decide acceptance of a current source program.
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
from pathlib import Path, PurePosixPath
import tarfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "compiler/bootstrap/c-bootstrap-v1.json"
ARCHIVE = "compiler/bootstrap/c-bootstrap-v1.tar.gz"
from repo_support import sha256_bytes

KIND = "ouro.c-bootstrap-inputs.v1"
STAGE0 = ("compiler/stage0/driver_u.c", "compiler/stage0/backend_u.c")


def member_name(name: str) -> str:
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or path.as_posix() != name or "\\" in name or ":" in name
            or any(part in {"", ".", ".."} or part.rstrip(" .") != part for part in name.split("/"))
            or any(ord(char) < 32 for char in name)):
        raise ValueError(f"BOOTSTRAP_INPUTS: unsafe member path {name!r}")
    if len(path.parts) < 3 or path.parts[0] not in {"c0", "bridge"}:
        raise ValueError(f"BOOTSTRAP_INPUTS: unknown member role {name!r}")
    return name


def load_manifest(root: Path = ROOT) -> dict:
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("kind") != KIND or manifest.get("archive") != ARCHIVE:
        raise ValueError("BOOTSTRAP_INPUTS: unsupported manifest")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("BOOTSTRAP_INPUTS: missing member inventory")
    for name, row in files.items():
        member_name(name)
        if not isinstance(row, dict) or type(row.get("bytes")) is not int or row["bytes"] < 1:
            raise ValueError(f"BOOTSTRAP_INPUTS: invalid member size {name!r}")
        value = row.get("sha256")
        if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError(f"BOOTSTRAP_INPUTS: invalid member hash {name!r}")
    if manifest.get("file_count") != len(files) or manifest.get("source_bytes") != sum(row["bytes"] for row in files.values()):
        raise ValueError("BOOTSTRAP_INPUTS: inconsistent inventory totals")
    if set(manifest.get("stage0", {})) != set(STAGE0):
        raise ValueError("BOOTSTRAP_INPUTS: incomplete historical stage0 inventory")
    roots, graph = manifest.get("ordered_roots"), manifest.get("ordered_unit_graph")
    if not isinstance(roots, list) or len(roots) != 15 or len(set(roots)) != 15 or not isinstance(graph, dict) or set(graph) != set(roots):
        raise ValueError("BOOTSTRAP_INPUTS: incomplete bridge root graph")
    for source, units in graph.items():
        if (not isinstance(units, list) or not units or units[-1] != source or len(set(units)) != len(units)
                or any("bridge/" + unit not in files for unit in units)):
            raise ValueError(f"BOOTSTRAP_INPUTS: incomplete ordered closure for {source}")
    return manifest


def read_bundle(root: Path = ROOT) -> tuple[dict, dict[str, bytes]]:
    manifest = load_manifest(root)
    archive = (root / ARCHIVE).read_bytes()
    if len(archive) != manifest.get("archive_bytes") or sha256_bytes(archive) != manifest.get("archive_sha256"):
        raise ValueError("BOOTSTRAP_INPUTS: archive hash or size mismatch")
    expected = manifest["files"]
    contents: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as package:
        for entry in package:
            name = member_name(entry.name)
            if name in contents:
                raise ValueError(f"BOOTSTRAP_INPUTS: duplicate archive member {name}")
            if not entry.isfile() or entry.issym() or entry.islnk():
                raise ValueError(f"BOOTSTRAP_INPUTS: non-file archive member {name}")
            row = expected.get(name)
            if row is None:
                raise ValueError(f"BOOTSTRAP_INPUTS: unexpected archive member {name}")
            if entry.size != row["bytes"]:
                raise ValueError(f"BOOTSTRAP_INPUTS: member size mismatch {name}")
            stream = package.extractfile(entry)
            if stream is None:
                raise ValueError(f"BOOTSTRAP_INPUTS: unreadable archive member {name}")
            data = stream.read(row["bytes"] + 1)
            if len(data) != row["bytes"] or sha256_bytes(data) != row["sha256"]:
                raise ValueError(f"BOOTSTRAP_INPUTS: member hash or size mismatch {name}")
            contents[name] = data
    if set(contents) != set(expected):
        missing = sorted(set(expected) - set(contents))
        raise ValueError(f"BOOTSTRAP_INPUTS: missing archive members {missing}")
    return manifest, contents


def verify_stage0(root: Path, manifest: dict) -> None:
    for name in STAGE0:
        row = manifest["stage0"][name]
        data = (root / name).read_bytes()
        if len(data) != row["bytes"] or sha256_bytes(data) != row["sha256"]:
            raise ValueError(f"BOOTSTRAP_INPUTS: historical stage0 mismatch {name}")


def unpack(destination: Path, root: Path = ROOT) -> dict:
    manifest, contents = read_bundle(root)
    # Validate every member before creating or writing the private destination.
    destination = destination.resolve()
    destination.mkdir(parents=False, exist_ok=False)
    for name, data in contents.items():
        path = destination / name
        if not path.resolve().is_relative_to(destination):
            raise ValueError(f"BOOTSTRAP_INPUTS: member escapes destination {name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
    return manifest


def archive_bytes(contents: dict[str, bytes]) -> bytes:
    result = io.BytesIO()
    with gzip.GzipFile(filename="", fileobj=result, mode="wb", compresslevel=9, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as package:
            for name, data in sorted(contents.items()):
                member_name(name)
                entry = tarfile.TarInfo(name)
                entry.size, entry.mode, entry.mtime = len(data), 0o644, 0
                entry.uid, entry.gid, entry.uname, entry.gname = 0, 0, "", ""
                package.addfile(entry, io.BytesIO(data))
    return result.getvalue()


def repack(source: Path, output: Path, root: Path = ROOT) -> None:
    manifest = load_manifest(root)
    expected = manifest["files"]
    paths = [path for path in source.rglob("*") if path.is_file() or path.is_symlink()]
    if any(path.is_symlink() for path in paths) or {path.relative_to(source).as_posix() for path in paths} != set(expected):
        raise ValueError("BOOTSTRAP_INPUTS: reproduction source inventory mismatch")
    contents = {name: (source / name).read_bytes() for name in expected}
    if any(len(data) != expected[name]["bytes"] or sha256_bytes(data) != expected[name]["sha256"] for name, data in contents.items()):
        raise ValueError("BOOTSTRAP_INPUTS: reproduction source hash or size mismatch")
    data = archive_bytes(contents)
    if len(data) != manifest["archive_bytes"] or sha256_bytes(data) != manifest["archive_sha256"]:
        raise ValueError("BOOTSTRAP_INPUTS: reproduced archive differs from the pinned artifact")
    with output.open("xb") as stream:
        stream.write(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify", help="verify the exact archive inventory, hashes and historical stage0 pair")
    sub.add_parser("lineage", help="print reviewed source origins and transformations before unpacking")
    extract = sub.add_parser("unpack", help="write verified inputs into a new private directory")
    extract.add_argument("--out", required=True, type=Path)
    reproduce = sub.add_parser("repack", help="reproduce the exact archive from verified unpacked source bytes")
    reproduce.add_argument("--source", required=True, type=Path)
    reproduce.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "verify":
            manifest, _contents = read_bundle()
            verify_stage0(ROOT, manifest)
        elif args.command == "lineage":
            print(json.dumps(load_manifest()["provenance"], indent=2))
        elif args.command == "unpack":
            unpack(args.out)
        else:
            repack(args.source, args.out)
    except (OSError, ValueError, tarfile.TarError) as error:
        parser.exit(1, f"{error}\n")
    print("BOOTSTRAP_INPUTS: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
