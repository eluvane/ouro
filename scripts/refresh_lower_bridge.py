#!/usr/bin/env python3
"""Reproduce the source-bound Nat/ascription composition in one historical member."""
from __future__ import annotations

import argparse
import copy
import difflib
import json
from typing import TYPE_CHECKING

from bootstrap_inputs import ARCHIVE, MANIFEST, ROOT, archive_bytes, read_bundle, verify_stage0
from repo_support import sha256_bytes
import refresh_nat_bridge as nat
import refresh_ascription_bridge as ascribe


if TYPE_CHECKING:
    from pathlib import Path

BASE_REVISION = "b672d5620591fd37dc6e33992e1b13d403ba781e"
FEATURE_REVISIONS = {
    "compact_nat": ["7a44d92e04b1523e0c5bbcd0edb176fc47540a15", "ec3af4bb79c0ddd7fe1c81af1683f54df7c073d1"],
    "evar": ["eb2398df59458671fd060ccb80027fea75e570b7"],
    "ascription": ["61c1783c4c19a73e7d8e8039ac44fec585dc2187", "ce4ec74ead6ddb78922a092edf00995e45769a9f", "2bcf1035886e9a1e2cfa3ca6e9b8db23c2f490d2"],
}
SOURCE_BLOBS = {
    "compiler/lower.ouro": "bd40cebe82608c5a23042f1349aea9b5964d17c1",
    "compiler/lower_nat.ouro": "a106c758642f92c5329b81912a2f58b6582da411",
    "compiler/lower_fallible.ouro": "62703e9ae2537c0141cd636833bb5c420227ad14",
    "compiler/lower_named.ouro": "984d677262c5cb4806a4d130a1aceedc9e61f6ce",
    "compiler/lower_spread.ouro": "a3d1d57a730a239427b06d429ee453e5d0c64d38",
    "compiler/pipeline_support.ouro": "c4fe78b32e212903d6616133651fcf4c36ab463d"
}
MEMBER = nat.MEMBER
NEW_MEMBER = "6a15b160b72c81abed30cfae70d20da091b52ae7c88403082fadd5ca680a7d83"
NEW_ARCHIVE = "b704ba53dc81f481b0c22cf5566c382a061cbb2cc0850002d0cf0e1c2f955482"
PREVIOUS_MANIFEST = "7ca501f51940ab8e8c178aa2341ba00c56f2a4a69551287946baa9d11c154d9a"
NEW_MANIFEST = "54aff33a1cf0df8f90b1b80c3ee88b6e00d5391af560238062deafb1f59c40e8"
ASCRIPTION_FUNCTION = "c4a2be662f3835813576b4f2d9a34bd6c21cb8ef7917bf494e42d35bf2d0f0f7"
LEGACY_NAT = b"def lower_xvnat\n  (_lower_run : Nat -> LowerEnv -> Maybe Surface -> Maybe Nat -> List (Pair Nat Surface) -> LowerMode -> LowerVal)\n  (_fuel' : Nat)\n  (env : LowerEnv)\n  (_er : Maybe Surface)\n  (_fixSelf : Maybe Nat)\n  (_locals : List (Pair Nat Surface))\n  (n : Nat) : LowerVal :=\nVSurf (lower_nat_env env n);\n"
LEGACY_ASCRIPTION = b"def lower_xvascribe\n  (lower_run : Nat -> LowerEnv -> Maybe Surface -> Maybe Nat -> List (Pair Nat Surface) -> LowerMode -> LowerVal)\n  (fuel' : Nat)\n  (env : LowerEnv)\n  (er : Maybe Surface)\n  (fixSelf : Maybe Nat)\n  (locals : List (Pair Nat Surface))\n  (tm : Expr)\n  (ty : Expr) : LowerVal :=\n    let tyS : Surface :=\n      vsurf_or_hole\n        (lower_run fuel' env er fixSelf locals (LExpr ty)) in\n    lower_run fuel' env (Just Surface tyS) fixSelf locals (LExpr tm);\n\n"


def encoded_manifest(manifest: dict) -> bytes:
    return (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode()


def load_sources(root: Path) -> dict[str, bytes]:
    sources = {name: (root / name).read_bytes() for name in SOURCE_BLOBS}
    for name, expected in SOURCE_BLOBS.items():
        if nat.git_blob(sources[name]) != expected or b"\r" in sources[name]:
            raise ValueError("product source blob changed: " + name)
    return sources


def source_copies(sources: dict[str, bytes]) -> tuple[bytes, bytes, list[dict]]:
    replacement, rows = nat.source_copies(sources)
    rows = [{**row, "source_blob": SOURCE_BLOBS[row["source"]]} for row in rows]
    current = sources["compiler/lower.ouro"]
    typed = ascribe.function(current)
    if sha256_bytes(typed) != ASCRIPTION_FUNCTION:
        raise ValueError("ascription source function bytes changed")
    first_line = current[:current.index(ascribe.START)].count(b"\n") + 1
    rows.append({"name": "lower_xvascribe", "source": "compiler/lower.ouro",
        "source_blob": SOURCE_BLOBS["compiler/lower.ouro"], "source_sha256": sha256_bytes(current),
        "first_line": first_line, "bytes": len(typed), "sha256": ASCRIPTION_FUNCTION})
    return replacement, typed, rows


def predecessor(encoded: bytes, manifest: dict, contents: dict[str, bytes],
    sources: dict[str, bytes]) -> tuple[dict, dict[str, bytes]]:
    identity = sha256_bytes(encoded)
    if encoded_manifest(manifest) != encoded:
        raise ValueError("historical manifest encoding changed")
    if len(contents) != 68 or manifest["stage0"] != nat.SEED:
        raise ValueError("historical inventory or seed changed")
    if identity == nat.OLD_MANIFEST:
        if manifest["archive_sha256"] != nat.OLD_ARCHIVE:
            raise ValueError("historical archive changed")
        return copy.deepcopy(manifest), dict(contents)
    if identity not in {PREVIOUS_MANIFEST, NEW_MANIFEST} or manifest["archive_sha256"] != NEW_ARCHIVE:
        raise ValueError("historical manifest changed; use the pinned predecessor")
    previous = contents[MEMBER]
    if sha256_bytes(previous) != NEW_MEMBER:
        raise ValueError("installed bridge lower changed")
    replacement, typed, _rows = source_copies(sources)
    if previous.count(replacement) != 1 or previous.count(typed) != 1:
        raise ValueError("installed source copies not unique")
    previous = previous.replace(typed, LEGACY_ASCRIPTION, 1).replace(replacement, LEGACY_NAT, 1)
    if sha256_bytes(previous) != nat.OLD_MEMBER:
        raise ValueError("reconstructed predecessor member differs")
    restored_contents = {**contents, MEMBER: previous}
    restored = copy.deepcopy(manifest)
    del restored["provenance"]["lowering_refresh"]
    restored["files"][MEMBER] = {"bytes": len(previous), "sha256": nat.OLD_MEMBER}
    restored["archive_bytes"] = 215827
    restored["archive_sha256"] = nat.OLD_ARCHIVE
    restored["source_bytes"] = sum(len(data) for data in restored_contents.values())
    if (sha256_bytes(encoded_manifest(restored)) != nat.OLD_MANIFEST
            or sha256_bytes(archive_bytes(restored_contents)) != nat.OLD_ARCHIVE):
        raise ValueError("reconstructed predecessor package differs")
    return restored, restored_contents


def patch(before: bytes, after: bytes) -> str:
    return "".join(difflib.unified_diff(before.decode().splitlines(keepends=True),
        after.decode().splitlines(keepends=True), fromfile="a/" + MEMBER, tofile="b/" + MEMBER))


def compose(manifest: dict, contents: dict[str, bytes],
    sources: dict[str, bytes]) -> tuple[dict, dict[str, bytes], bytes, bytes]:
    previous = contents[MEMBER]
    intermediate, _original_rows = nat.refreshed_member(contents, sources)
    replacement, typed, copies = source_copies(sources)
    original_typed = ascribe.function(previous)
    if original_typed != LEGACY_ASCRIPTION or intermediate.count(original_typed) != 1:
        raise ValueError("historical ascription function changed")
    if previous.replace(original_typed, typed, 1).count(typed) != 1:
        raise ValueError("ascription source copy not unique")
    updated = intermediate.replace(original_typed, typed, 1)
    reverse_order = previous.replace(original_typed, typed, 1).replace(LEGACY_NAT, replacement, 1)
    if updated != reverse_order or sha256_bytes(updated) != NEW_MEMBER:
        raise ValueError("unexpected composed bridge member bytes")
    nat_contents = {**contents, MEMBER: intermediate}
    if sha256_bytes(archive_bytes(nat_contents)) != nat.NEW_ARCHIVE:
        raise ValueError("unexpected intermediate Nat archive")
    changed = {**contents, MEMBER: updated}
    archive = archive_bytes(changed)
    if len(archive) != 217115 or sha256_bytes(archive) != NEW_ARCHIVE:
        raise ValueError("unexpected canonical archive bytes")
    full_patch = patch(previous, updated)
    steps = []
    for name, before, after, old_archive, new_archive in (
        ("compact_nat", previous, intermediate, nat.OLD_ARCHIVE, nat.NEW_ARCHIVE),
        ("ascription", intermediate, updated, nat.NEW_ARCHIVE, NEW_ARCHIVE),
    ):
        delta = patch(before, after)
        steps.append({"name": name, "previous_member_sha256": sha256_bytes(before),
            "member_sha256": sha256_bytes(after), "previous_archive_sha256": old_archive,
            "archive_sha256": new_archive, "reviewed_patch_sha256": sha256_bytes(delta.encode()),
            "reviewed_patch": delta})
    generated = copy.deepcopy(manifest)
    generated["archive_bytes"], generated["archive_sha256"] = len(archive), NEW_ARCHIVE
    generated["source_bytes"] = sum(len(data) for data in changed.values())
    generated["files"][MEMBER] = {"bytes": len(updated), "sha256": NEW_MEMBER}
    generated["provenance"]["lowering_refresh"] = {
        "base_revision": BASE_REVISION, "feature_revisions": FEATURE_REVISIONS,
        "scope": "Copy only reviewed Nat and ascription source slices into one historical bridge member; current roots remain independently checked before emission.",
        "previous_manifest_sha256": nat.OLD_MANIFEST, "previous_archive_sha256": nat.OLD_ARCHIVE,
        "source_blobs": SOURCE_BLOBS, "source_copies": copies, "steps": steps,
        "files": {MEMBER: {"previous_sha256": nat.OLD_MEMBER, "sha256": NEW_MEMBER}},
        "reviewed_patch_sha256": sha256_bytes(full_patch.encode()), "reviewed_patch": full_patch,
        "generator": "scripts/refresh_lower_bridge.py; scripts/bootstrap_inputs.py:archive_bytes",
        "verification": [
            "python3 -B scripts/refresh_lower_bridge.py",
            "python3 -B scripts/refresh_lower_bridge_test.py",
            "python3 -B scripts/bootstrap_inputs.py verify",
            "python3 scripts/ouro_build.py build",
        ],
    }
    return generated, changed, archive, encoded_manifest(generated)


def candidate(root: Path = ROOT) -> tuple[dict, dict[str, bytes], bytes, bytes]:
    sources = load_sources(root)
    encoded = (root / MANIFEST).read_bytes()
    manifest, contents = read_bundle(root)
    verify_stage0(root, manifest)
    original, original_contents = predecessor(encoded, manifest, contents, sources)
    generated, changed, archive, encoded = compose(original, original_contents, sources)
    if sha256_bytes(encoded) != NEW_MANIFEST:
        raise ValueError("unexpected manifest bytes")
    return generated, changed, archive, encoded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="install the exact composed archive and manifest")
    args = parser.parse_args()
    before = ((ROOT / MANIFEST).read_bytes(), (ROOT / ARCHIVE).read_bytes())
    manifest, contents, archive, encoded = candidate()
    print(json.dumps({"member": MEMBER, "member_sha256": NEW_MEMBER,
        "archive_sha256": sha256_bytes(archive), "archive_bytes": len(archive),
        "manifest_sha256": sha256_bytes(encoded), "source_copies": manifest["provenance"]["lowering_refresh"]["source_copies"],
        "stage0_unchanged": True, "historical_members_unchanged": 67,
        "current_host_validation": "requires fresh P1/P2, ABI, and behavior evidence", "write": args.write}, indent=2))
    if args.write:
        load_sources(ROOT)
        if before != ((ROOT / MANIFEST).read_bytes(), (ROOT / ARCHIVE).read_bytes()):
            raise ValueError("historical inputs changed before installation")
        verify_stage0(ROOT, manifest)
        if before != (encoded, archive):
            # A torn pair fails read_bundle closed; stage0 and historical runtime stay untouched.
            nat.write_once(ROOT / ARCHIVE, archive)
            nat.write_once(ROOT / MANIFEST, encoded)
        installed, installed_contents = read_bundle()
        verify_stage0(ROOT, installed)
        if installed != manifest or installed_contents != contents or (ROOT / MANIFEST).read_bytes() != encoded:
            raise ValueError("installed bundle differs from generated composition")


if __name__ == "__main__":
    main()
