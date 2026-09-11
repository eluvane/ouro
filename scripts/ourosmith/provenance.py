"""Bind validation evidence to the source tree and binaries actually exercised."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from ourosmith import ROOT
from ourosmith.host import job_count

INPUTS = ("lib", "scripts", "compiler", "runtime", "tests", "std", "tools", "quality", "test", ".github",
          "docs", "README.md", "CHANGELOG.md", "CONTRIBUTING.md", "Ouro.seal", "dune", "dune-project", "ouro.opam")
EXTENSIONS = {".ouro", ".ml", ".mli", ".py", ".sh", ".c", ".h", ".json", ".toml", ".seal", ".opam",
              ".yml", ".yaml", ".tsv", ".txt", ".in", ".golden", ".md", ".sha256"}


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True,
                          timeout=15).stdout.decode("utf-8")


def source_state():
    paths = git("ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", *INPUTS)
    hashes = {}
    for name in sorted(set(paths.split("\0")) - {"", "quality/smith/migration_matrix.json"}):
        path = ROOT / name
        if path.suffix in EXTENSIONS or path.name in {"dune", "dune-project"}:
            hashes[name] = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() if path.is_file() else "missing"
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    return {"head": git("rev-parse", "HEAD").strip(), "source_sha256": digest, "files": len(hashes)}


def binary_state(paths):
    return {Path(path).relative_to(ROOT).as_posix(): hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else "missing"
            for path in sorted(paths)}


def begin():
    return {"source": source_state(), "binaries": {}, "python": sys.version.split()[0],
            "platform": sys.platform, "jobs": job_count()}


def finish(report):
    provenance = report.sections.get("provenance")
    if provenance is None:
        return
    if provenance["source"] != source_state():
        report.skip("provenance:source", "source changed during validation; rerun the stable tree")
    binaries = provenance["binaries"]
    if binaries != binary_state([ROOT / path for path in binaries]):
        report.skip("provenance:binaries", "tested binaries changed during validation")
    stage = report.sections.get("stage_parity", {})
    if stage.get("status") == "exercised":
        if binary_state([ROOT / stage["binary"]]) != {stage["binary"]: stage["sha256"]}:
            report.skip("provenance:stage", "tested stage binary changed during validation")
