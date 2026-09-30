#!/usr/bin/env python3
"""Reproduce the scoped historical bridge ascription refresh."""
from __future__ import annotations

import argparse
import difflib
import json
import os
from typing import TYPE_CHECKING
import tempfile

from bootstrap_inputs import ARCHIVE, MANIFEST, ROOT, archive_bytes, read_bundle, verify_stage0
from repo_support import git_blob, sha256_bytes


if TYPE_CHECKING:
    from pathlib import Path

BASE_REVISION = "cdf16527513e18ab46ea3655743ca4d9ae9cf5e4"
OLD_MANIFEST = "2ba02545a5fada2e88b4ed969b499a58568fd10dc7a2d5dcc52948a280fba145"
OLD_ARCHIVE = "36fafa7c3518f28a7da719b080046ed9835e5eaf8550f632360f02b46b8adf91"
NEW_ARCHIVE = "5086966057bf39b50e94d6a8a159530053e494e1001645f6b2d3ce258a5d3c45"
NEW_MANIFEST = "c6dd132818bb6aa23f7a81db5297991ff5d78622f5e25a609aca7edae74ff0cf"
MEMBER = "bridge/compiler/lower.ouro"
OLD_MEMBER = "2bd4c376f208f9fb8906d0cda27b176affea9029d75ae4617b5dd19d998af4e5"
NEW_MEMBER = "1e20bcc326b1ab9baf7e0ca00873a3b14b9b9e4de842577ca3b7dc190189ec1f"
NEW_PATCH = "3bd4063db581bf93a17f4dd5ab4a90b92b961c21de141317a615a4a0a685d508"
SOURCE_BLOBS = {
    "compiler/lower.ouro": "112d10465bbcc43a7f00657bea49a4c9c343d657",
    "compiler/pipeline_support.ouro": "bcc16b56e7b672b24ab32022552168420f6d679f",
    "runtime/bootstrap.c": "5272a92d85d3f693407ec1f5d0e091fe461f8018",
    "runtime/ouro_rt.c": "5fa7a64f29ef9b25f23b9e322d111e7070516b36",
    "runtime/frontend_link.c": "f10104eb4bc30055dabb3163a82f181c6eae9f1a",
}
START = b"def lower_xvascribe\n"
END = b"def lower_xvmatch\n"


def function(data: bytes) -> bytes:
    if data.count(START) != 1 or data.count(END) != 1:
        raise ValueError("ascription function boundaries changed")
    start, end = data.index(START), data.index(END)
    if start >= end:
        raise ValueError("ascription function order changed")
    return data[start:end]


def write_once(path: Path, data: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".ascription-refresh-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="install the exact archive and manifest")
    args = parser.parse_args()

    for name, expected in SOURCE_BLOBS.items():
        if git_blob((ROOT / name).read_bytes()) != expected:
            raise ValueError(f"product source blob changed: {name}")
    manifest_path, archive_path = ROOT / MANIFEST, ROOT / ARCHIVE
    if sha256_bytes(manifest_path.read_bytes()) != OLD_MANIFEST:
        raise ValueError("historical manifest changed")
    manifest, contents = read_bundle()
    verify_stage0(ROOT, manifest)
    if len(contents) != 68 or manifest["archive_sha256"] != OLD_ARCHIVE:
        raise ValueError("historical archive changed")
    previous = contents[MEMBER]
    if sha256_bytes(previous) != OLD_MEMBER or b"\r\n" in previous:
        raise ValueError("historical bridge lower changed")

    current = (ROOT / "compiler/lower.ouro").read_bytes()
    replacement_lf = function(current)
    original_lf = function(previous)
    if b"lower_run fuel' env (Just Surface tyS) fixSelf locals (LExpr tm);" not in original_lf:
        raise ValueError("historical ascription behavior changed")
    if b"VSurf (SLet Z tmS tyS (SVar Z));" not in replacement_lf:
        raise ValueError("product ascription obligation changed")
    if previous.count(original_lf) != 1:
        raise ValueError("historical function not unique")
    updated = previous.replace(original_lf, replacement_lf)
    if sha256_bytes(updated) != NEW_MEMBER:
        raise ValueError("unexpected bridge member bytes")

    patch = "".join(difflib.unified_diff(
        original_lf.decode().splitlines(keepends=True),
        replacement_lf.decode().splitlines(keepends=True),
        fromfile="a/" + MEMBER, tofile="b/" + MEMBER))
    if sha256_bytes(patch.encode()) != NEW_PATCH:
        raise ValueError("unexpected bridge source patch")
    contents[MEMBER] = updated
    archive = archive_bytes(contents)
    if len(archive) != 215878 or sha256_bytes(archive) != NEW_ARCHIVE:
        raise ValueError("unexpected canonical archive bytes")
    manifest["archive_bytes"] = len(archive)
    manifest["archive_sha256"] = sha256_bytes(archive)
    manifest["source_bytes"] = sum(len(data) for data in contents.values())
    manifest["files"][MEMBER] = {"bytes": len(updated), "sha256": NEW_MEMBER}
    manifest["provenance"]["ascription_refresh"] = {
        "base_revision": BASE_REVISION,
        "feature_revisions": [
            "3778528cba3c9d4f90acc53272355b5226c1dd07",
            "5d2cc8754cb48aa3627980df2100f900c9ef02d3",
        ],
        "scope": "Refresh only the historical bridge ascription lowering; current sources remain independently checked before emission.",
        "previous_archive_sha256": OLD_ARCHIVE,
        "product_lower_blob": SOURCE_BLOBS["compiler/lower.ouro"],
        "files": {MEMBER: {"previous_sha256": OLD_MEMBER, "sha256": NEW_MEMBER}},
        "reviewed_patch_sha256": sha256_bytes(patch.encode()),
        "reviewed_patch": patch,
        "generator": "scripts/bootstrap_inputs.py:archive_bytes",
        "verification": [
            "python3 scripts/bootstrap_inputs.py verify",
            "python3 scripts/bootstrap_inputs.py unpack --out _build/bootstrap-inputs-v1",
            "python3 scripts/bootstrap_inputs.py repack --source _build/bootstrap-inputs-v1 --out _build/c-bootstrap-v1.reproduced.tar.gz",
            "python3 scripts/ouro_build.py build",
        ],
    }
    encoded = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode()
    if sha256_bytes(encoded) != NEW_MANIFEST:
        raise ValueError("unexpected manifest bytes")
    print(json.dumps({
        "member_sha256": NEW_MEMBER,
        "archive_sha256": sha256_bytes(archive),
        "manifest_sha256": sha256_bytes(encoded),
        "patch_sha256": sha256_bytes(patch.encode()),
        "source_bytes": manifest["source_bytes"],
        "write": args.write,
    }, indent=2))
    if args.write:
        # A torn pair fails read_bundle closed; stage0 and its hash manifest stay untouched.
        write_once(archive_path, archive)
        write_once(manifest_path, encoded)
        installed, installed_contents = read_bundle()
        verify_stage0(ROOT, installed)
        if (installed != manifest or installed_contents != contents
                or sha256_bytes(manifest_path.read_bytes()) != NEW_MANIFEST):
            raise ValueError("installed bundle differs from the generated candidate")


if __name__ == "__main__":
    main()
