#!/usr/bin/env python3
"""Reproduce the source-bound historical bridge refresh for compact Nat literals."""
from __future__ import annotations

import argparse
import difflib
import json
import os
from typing import TYPE_CHECKING
import re
import tempfile

from bootstrap_inputs import ARCHIVE, MANIFEST, ROOT, archive_bytes, read_bundle, verify_stage0
from repo_support import git_blob, sha256_bytes


if TYPE_CHECKING:
    from pathlib import Path

BASE_REVISION = "973c3a21342e9d6e029479fb33ed7207d010c1bd"
FEATURE_REVISION = "a9cfa54f09c3b02ffb22ff1b423c04a78d380764"
OLD_MANIFEST = "2ba02545a5fada2e88b4ed969b499a58568fd10dc7a2d5dcc52948a280fba145"
OLD_ARCHIVE = "36fafa7c3518f28a7da719b080046ed9835e5eaf8550f632360f02b46b8adf91"
MEMBER = "bridge/compiler/lower.ouro"
OLD_MEMBER = "2bd4c376f208f9fb8906d0cda27b176affea9029d75ae4617b5dd19d998af4e5"
OLD_FUNCTION = "001c3e449cec49f6e830c54536825c4557eb527951d98d2eaacbfc1e735bddc9"
NEW_MEMBER = "8ed2ab7dc45480c9b6be84af91735b1d2347c35833ef137873de5a16267231b8"
NEW_ARCHIVE = "863025d32d0a9c46b3d2e5cc5e8d8def1c636975685808bedcf0c4f22dea6aee"
NEW_MANIFEST = "7c150283d2316d6cbcf3450919975c2d55e17f64b63d398d9dae41128623f00b"
SOURCE_BLOBS = {
    "compiler/lower.ouro": "eba95f38d456969cd0550e65e2ff7aad1532e190",
    "compiler/lower_nat.ouro": "a106c758642f92c5329b81912a2f58b6582da411",
    "compiler/lower_fallible.ouro": "ac181c88253e532b7ea7e6938729dbbf8c280c05",
    "compiler/lower_named.ouro": "6d6a481c698fcc390a40bfa807441be8a6828878",
    "compiler/lower_spread.ouro": "ad0dcafb4fcc0eda264d4f8bc373dc91282cf41b",
}
SEED = {
    "compiler/stage0/driver_u.c": {"bytes": 12951042,
        "sha256": "471786555a20745e47aa8ff6ce6714269cd7454e6462e45958bf6957d991f193"},
    "compiler/stage0/backend_u.c": {"bytes": 2141122,
        "sha256": "921d54bc4c750fa987651dbb991d42f3f899a43773edcb3a586199860f769cb9"},
}
# Each slice is copied verbatim. Its imports are supplied by the historical lower_support cone.
COPIES = (
    ("fallible_max_var", "compiler/lower_fallible.ouro", b"def fallible_max_var",
     b"\n-- The shared motive uses fixed binder IDs.",
     "39c3f3cab99b4a457fe089a57328599f515cc6381a030f3ab6127f44ba96e2e1"),
    ("named_locals_max", "compiler/lower_named.ouro", b"def named_locals_max",
     b"\ndef named_values_max",
     "c25643a316eddf17e89cb144d121999ce953f3e3d87205e8feb9789d8f74d013"),
    ("spread_max_names", "compiler/lower_spread.ouro", b"def spread_max_names",
     b"\ndef spread_max_exprs",
     "fe9c4971dc87b43c31c443a3b8481178e75600b7281c5fae09ccadd8632b6935"),
    ("literal_nat_helpers", "compiler/lower_nat.ouro", b"def literal_nat_family", None,
     "6ae7063b0616120bd399400184eeecfaa39d12de4264f40654eb5815a07e0a9a"),
    ("lower_xvnat", "compiler/lower.ouro", b"def lower_xvnat\n", b"\ndef lower_xvrange",
     "80d20f220b11359ed1b2b47318d8a7ae4f5713de4d9fdb6889a9afa702ebf89d"),
)


def section(data: bytes, start: bytes, end: bytes | None) -> bytes:
    if data.count(start) != 1 or (end is not None and data.count(end) != 1):
        raise ValueError("source function boundaries changed")
    begin, stop = data.index(start), data.index(end) if end is not None else len(data)
    if begin >= stop:
        raise ValueError("source function order changed")
    return data[begin:stop]


def load_sources(root: Path) -> dict[str, bytes]:
    sources = {name: (root / name).read_bytes() for name in SOURCE_BLOBS}
    for name, expected in SOURCE_BLOBS.items():
        if git_blob(sources[name]) != expected or b"\r" in sources[name]:
            raise ValueError("product source blob changed: " + name)
    return sources


def source_copies(sources: dict[str, bytes]) -> tuple[bytes, list[dict]]:
    fragments, rows = [], []
    for name, source, start, end, expected in COPIES:
        data = section(sources[source], start, end)
        if sha256_bytes(data) != expected:
            raise ValueError("source function bytes changed: " + name)
        fragments.append(data)
        first_line = sources[source][:sources[source].index(start)].count(b"\n") + 1
        rows.append({"name": name, "source": source, "source_blob": SOURCE_BLOBS[source],
            "source_sha256": sha256_bytes(sources[source]), "first_line": first_line,
            "bytes": len(data), "sha256": expected})
    return b"\n".join(fragments), rows


def refreshed_member(contents: dict[str, bytes], sources: dict[str, bytes]) -> tuple[bytes, list[dict]]:
    previous = contents[MEMBER]
    if sha256_bytes(previous) != OLD_MEMBER:
        raise ValueError("historical bridge lower changed")
    original = section(previous, b"def lower_xvnat\n", b"\ndef lower_xvstr")
    if sha256_bytes(original) != OLD_FUNCTION:
        raise ValueError("historical Nat function changed")
    replacement, copies = source_copies(sources)
    added = re.findall(rb"^def\s+([^\s(:]+)", replacement, re.M)[:-1]
    existing = set()
    for name, data in contents.items():
        if name.startswith("bridge/") and name.endswith(".ouro"):
            existing.update(re.findall(rb"^def\s+([^\s(:]+)", data, re.M))
    if len(set(added)) != len(added) or any(name in existing for name in added):
        raise ValueError("Nat helper collides with a historical declaration")
    if previous.count(original) != 1:
        raise ValueError("historical Nat function not unique")
    updated = previous.replace(original, replacement)
    if sha256_bytes(updated) != NEW_MEMBER:
        raise ValueError("unexpected bridge member bytes")
    return updated, copies


def candidate(root: Path = ROOT) -> tuple[dict, dict[str, bytes], bytes, bytes]:
    if sha256_bytes((root / MANIFEST).read_bytes()) != OLD_MANIFEST:
        raise ValueError("historical manifest changed; regenerate from the pinned predecessor")
    manifest, contents = read_bundle(root)
    verify_stage0(root, manifest)
    if len(contents) != 68 or manifest["archive_sha256"] != OLD_ARCHIVE or manifest["stage0"] != SEED:
        raise ValueError("historical archive inventory or seed changed")
    sources = load_sources(root)
    updated, copies = refreshed_member(contents, sources)
    previous = contents[MEMBER]
    patch = "".join(difflib.unified_diff(previous.decode().splitlines(keepends=True),
        updated.decode().splitlines(keepends=True), fromfile="a/" + MEMBER, tofile="b/" + MEMBER))
    contents = {**contents, MEMBER: updated}
    archive = archive_bytes(contents)
    if len(archive) != 217061 or sha256_bytes(archive) != NEW_ARCHIVE:
        raise ValueError("unexpected canonical archive bytes")
    manifest["archive_bytes"], manifest["archive_sha256"] = len(archive), NEW_ARCHIVE
    manifest["source_bytes"] = sum(len(data) for data in contents.values())
    manifest["files"][MEMBER] = {"bytes": len(updated), "sha256": NEW_MEMBER}
    manifest["provenance"]["compact_nat_refresh"] = {
        "base_revision": BASE_REVISION, "feature_revisions": [FEATURE_REVISION],
        "scope": "Refresh only historical bridge Nat lowering from reviewed current sources; current roots remain independently checked before emission.",
        "previous_manifest_sha256": OLD_MANIFEST, "previous_archive_sha256": OLD_ARCHIVE,
        "source_blobs": SOURCE_BLOBS, "source_copies": copies,
        "files": {MEMBER: {"previous_sha256": OLD_MEMBER, "sha256": NEW_MEMBER}},
        "reviewed_patch_sha256": sha256_bytes(patch.encode()), "reviewed_patch": patch,
        "generator": "scripts/bootstrap_inputs.py:archive_bytes",
        "verification": [
            "python3 -B scripts/refresh_nat_bridge.py",
            "python3 -B scripts/bootstrap_inputs.py verify",
            "python3 -B scripts/bootstrap_inputs.py unpack --out _build/nat-bridge-inputs",
            "python3 -B scripts/bootstrap_inputs.py repack --source _build/nat-bridge-inputs --out _build/nat-bridge.reproduced.tar.gz",
            "python3 scripts/ouro_build.py build",
        ],
    }
    encoded = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode()
    if sha256_bytes(encoded) != NEW_MANIFEST:
        raise ValueError("unexpected manifest bytes")
    return manifest, contents, archive, encoded


def write_once(path: Path, data: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="install the regenerated archive and manifest")
    args = parser.parse_args()
    manifest, contents, archive, encoded = candidate()
    print(json.dumps({"archive_sha256": NEW_ARCHIVE, "archive_bytes": len(archive),
        "manifest_sha256": sha256_bytes(encoded), "member": MEMBER, "member_sha256": NEW_MEMBER,
        "source_copies": manifest["provenance"]["compact_nat_refresh"]["source_copies"],
        "stage0_unchanged": True, "historical_members_unchanged": 67}, indent=2))
    if args.write:
        load_sources(ROOT)
        if (sha256_bytes((ROOT / MANIFEST).read_bytes()) != OLD_MANIFEST
                or sha256_bytes((ROOT / ARCHIVE).read_bytes()) != OLD_ARCHIVE):
            raise ValueError("historical inputs changed before installation")
        verify_stage0(ROOT, manifest)
        # A torn pair fails read_bundle closed; the committed stage0 and runtime stay untouched.
        write_once(ROOT / ARCHIVE, archive)
        write_once(ROOT / MANIFEST, encoded)
        installed, installed_contents = read_bundle()
        verify_stage0(ROOT, installed)
        if installed != manifest or installed_contents != contents or sha256_bytes((ROOT / MANIFEST).read_bytes()) != sha256_bytes(encoded):
            raise ValueError("installed bundle differs from the generated candidate")


if __name__ == "__main__":
    main()
