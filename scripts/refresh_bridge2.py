#!/usr/bin/env python3
"""Package the source snapshot of a checked compiler as the second bridge."""
from __future__ import annotations

import argparse
from itertools import pairwise
import json
from pathlib import Path

import bootstrap_inputs as inputs
from generated_c_shards import write_bytes_if_changed
from repo_support import hash_json, sha256_bytes, sha256_file


def candidate(work: Path, root: Path) -> tuple[dict, bytes]:
    frozen = (work / "inputs.json").read_bytes()
    snapshot = json.loads(frozen)
    selected = snapshot["selected"]
    recorded = (work / "report.json").read_bytes()
    report = json.loads(recorded)
    base, _contents = inputs.read_bundle(root)
    inputs.verify_stage0(root, base)
    stage0 = {name: row["sha256"] for name, row in base["stage0"].items()}
    phases = report["phases"]
    if (report["pass"] is not True or report["kind"] != selected["kind"]
            or report["changed_inputs"] != [] or report["inputs_sha256"] != sha256_bytes(frozen)
            or report["key"] != snapshot["key"] or snapshot["key"] != hash_json(selected)
            or [row["phase"] for row in phases] != ["c0", "bridge", "p1", "p2"]
            or [row["binary"] for row in phases] != ["out/c0/c/ouro1", "out/bridge/ouro1", "out/p1/ouro1", "out/p2/ouro1"]
            or any(row["pass"] is not True for row in phases)
            or any(prev["binary_sha256"] != following["producer_sha256"] for prev, following in pairwise(phases))
            or any(row["all_current_roots_strictly_checked_before_use"] is not True for row in phases[-2:])
            or selected["archive_sha256"] != base["archive_sha256"] or selected["stage0"] != stage0
            or selected["manifest_sha256"] != sha256_file(root / inputs.MANIFEST)
            or snapshot["bridge_graph"] != base["ordered_unit_graph"]
            or selected["source_form"] != "original" or snapshot["roots"]["p2"] != "o"):
        raise ValueError("unchecked or incompatible source snapshot")
    for row in phases:
        if sha256_file(work / row["binary"]) != row["binary_sha256"]:
            raise ValueError(f"compiler image changed in phase {row['phase']}")
    comparison = report["complete_generated_c_comparison"]
    if (set(comparison) != {"driver_u.c", "backend_u.c"}
            or any(sha256_file(work / "out/p1" / name) != hashes["p1_sha256"]
                   or sha256_file(work / "out/p2" / name) != hashes["p2_sha256"]
                   or hashes["p1_sha256"] != hashes["p2_sha256"] for name, hashes in comparison.items())):
        raise ValueError("generated C no longer matches the checked comparison")

    roots = selected["roots"]
    graph = {name: selected["unit_graph"][name] for name in roots}
    names = {unit for units in graph.values() for unit in units}
    names.update(name for name in selected["sources"] if name.startswith("runtime/"))
    contents = {}
    for name in sorted(names):
        member = inputs.member_name("bridge2/" + name)
        data = (work / "o" / name).read_bytes()
        digest = sha256_bytes(data)
        if digest != selected["sources"][name] or digest != snapshot["inputs"]["o/" + name]:
            raise ValueError(f"checked source changed: {name}")
        contents[member] = data
    archive = inputs.archive_bytes(contents)
    manifest = {
        "kind": inputs.KIND,
        "archive": inputs.BRIDGE2_ARCHIVE,
        "archive_sha256": sha256_bytes(archive),
        "archive_bytes": len(archive),
        "file_count": len(contents),
        "source_bytes": sum(map(len, contents.values())),
        "files": {name: {"bytes": len(data), "sha256": sha256_bytes(data)} for name, data in contents.items()},
        "stage0": base["stage0"],
        "ordered_roots": roots,
        "ordered_unit_graph": graph,
        "provenance": {
            "previous_archive_sha256": selected["archive_sha256"],
            "source_snapshot_sha256": sha256_bytes(frozen),
            "bootstrap_report_sha256": sha256_bytes(recorded),
            "checked_compiler_sha256": phases[-1]["binary_sha256"],
            "generator": "scripts/refresh_bridge2.py",
        },
    }
    return manifest, archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-work", required=True, type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    try:
        manifest, archive = candidate(args.bootstrap_work.resolve(), inputs.ROOT)
        if args.write:
            outputs = {inputs.BRIDGE2_ARCHIVE: archive,
                       inputs.BRIDGE2_MANIFEST: (json.dumps(manifest, indent=2) + "\n").encode()}
            for name, data in outputs.items():
                path = inputs.ROOT / name
                if path.exists() and path.read_bytes() != data:
                    raise ValueError(f"refusing to replace a different second bridge: {name}")
            for name, data in outputs.items():
                write_bytes_if_changed(inputs.ROOT / name, data)
            inputs.read_bundle(bridge2=True)
        print(f"BRIDGE2: {manifest['file_count']} files sha256={manifest['archive_sha256']}")
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(1, f"BRIDGE2: FAIL {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
