#!/usr/bin/env python3
"""Observe explicitly provisioned P6 Windows candidates for retained shell suites.

The snapshot binds the observed images across one suite invocation. The caller
must retain separate direct-PE build receipts with their source and producer
hashes; this file does not infer a build backend from an executable's format.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from frontend_native_process import inspect_image, require

TOOLS = {
    "lsp": ("coil.exe", "ouro-fmt.exe", "ouro-lsp.exe"),
    "pkg": ("coil.exe", "ouro-pkg.exe"),
    "test": ("coil.exe", "ouro-test.exe"),
    "samples": ("coil.exe", "ouro-test.exe"),
}
IMPORTS = ("advapi32.dll", "bcrypt.dll", "kernel32.dll", "shell32.dll")


def snapshot(directory: Path, suite: str) -> dict:
    require(os.name == "nt", "prebuilt Windows candidates require a Windows host")
    directory = directory.resolve(strict=True)
    require(directory.is_dir(), "native candidate directory is not a directory")
    images = {}
    for name in TOOLS[suite]:
        binary = (directory / name).resolve(strict=True)
        require(binary.is_file() and binary.parent == directory,
                "native candidate is not a regular sibling image: " + name)
        images[name] = {"path": str(binary), "image": inspect_image(binary, IMPORTS)}
    return {"kind": "ouro.prebuilt-suite-candidates.v1", "suite": suite,
            "source_bound": False, "native_bootstrap": False, "images": images}


def observe(directory: Path, suite: str, receipt: Path, verify: bool) -> dict:
    observed = snapshot(directory, suite)
    if verify:
        previous = json.loads(receipt.read_text(encoding="utf-8"))
        require(previous == observed, "native candidates changed during the suite")
    else:
        # Each acceptance invocation owns a fresh snapshot. Do not overwrite
        # evidence from an earlier run or a candidate image by mistake.
        with receipt.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(observed, stream, indent=2, sort_keys=True)
            stream.write("\n")
    return observed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--suite", choices=TOOLS, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    try:
        observed = observe(args.directory, args.suite, args.receipt, args.verify)
    except (OSError, ValueError) as error:
        print(f"NATIVE_SUITE_TOOLS: FAIL {error}", file=sys.stderr)
        return 1
    phase = "unchanged" if args.verify else "prebuilt Windows candidates"
    print(f"NATIVE_SUITE_TOOLS: {phase} suite={args.suite}", file=sys.stderr)
    for name, row in observed["images"].items():
        print(f"NATIVE_SUITE_TOOLS: {name} sha256={row['image']['sha256']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
