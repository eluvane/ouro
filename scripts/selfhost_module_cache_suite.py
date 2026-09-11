#!/usr/bin/env python3
"""Fast regressions for the Ouro selfhost incremental module cache."""
from __future__ import annotations

import json
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import cache_parity_suite as cache_parity

ROOT = Path(__file__).resolve().parents[1]


def copy_repo(dst: Path) -> None:
    ignore = shutil.ignore_patterns("_build", "_cache", ".git", "*.pyc", "__pycache__")
    shutil.copytree(ROOT, dst, ignore=ignore)


def write_fake_seed(path: Path) -> None:
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write_modules(repo: Path) -> None:
    mini = repo / "mini"
    mini.mkdir()
    (mini / "a.ouro").write_text("def a : Nat := Z;\n", encoding="utf-8")
    (mini / "b.ouro").write_text('import "a.ouro";\ndef b : Nat := a;\n', encoding="utf-8")
    (mini / "c.ouro").write_text('import "b.ouro";\ndef c : Nat := b;\n', encoding="utf-8")


def run_cache(repo: Path, seed: Path) -> dict:
    cmd = [
        sys.executable,
        "scripts/selfhost_module_cache.py",
        "--root",
        "mini/c.ouro",
        "--work",
        "_build/module_cache_test",
        "--cache-root",
        "_cache/module_cache_test",
        "--seed",
        str(seed),
        "--fuel",
        "1",
        "--label",
        "suite",
    ]
    p = subprocess.run(cmd, cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
    assert "MODULE_CACHE: OK" in p.stdout, p.stdout
    return json.loads((repo / "_build/module_cache_test/selfhost-module-cache.json").read_text(encoding="utf-8"))


def by_path(report: dict) -> dict[str, dict]:
    return {m["path"]: m for m in report["modules"]}


def test_module_cache_precision(tmp: Path) -> None:
    repo = tmp / "repo"
    copy_repo(repo)
    write_modules(repo)
    seed = tmp / "fake-seed"
    write_fake_seed(seed)

    first = run_cache(repo, seed)
    s = first["summary"]
    assert s["direct_misses"] == 3 and s["closure_misses"] == 3, s
    assert s["phase_misses"] == {"elab": 3, "extract": 3, "import": 3, "lower": 3, "parse": 3}, s

    second = run_cache(repo, seed)
    s = second["summary"]
    assert s["direct_hits"] == 3 and s["closure_hits"] == 3, s
    assert s["affected_roots"] == [] and s["affected_modules"] == [], s

    # Leaf dependency edit: only a.ouro is a direct miss, but all import closures
    # downstream of it are invalidated.
    a = repo / "mini/a.ouro"
    a.write_text(a.read_text(encoding="utf-8") + "def a2 : Nat := a;\n", encoding="utf-8")
    third = run_cache(repo, seed)
    s = third["summary"]
    assert s["direct_misses"] == 1, s
    assert s["closure_misses"] == 3, s
    assert s["direct_changed_modules"] == ["mini/a.ouro"], s
    assert s["affected_modules"] == ["mini/a.ouro", "mini/b.ouro", "mini/c.ouro"], s
    assert s["affected_roots"] == ["mini/c.ouro"], s

    # Root-only edit: dependency artifacts stay hot; only c.ouro closure moves.
    fourth_base = run_cache(repo, seed)
    assert fourth_base["summary"]["direct_hits"] == 3, fourth_base["summary"]
    c = repo / "mini/c.ouro"
    c.write_text(c.read_text(encoding="utf-8") + "def c2 : Nat := c;\n", encoding="utf-8")
    fourth = run_cache(repo, seed)
    s = fourth["summary"]
    assert s["direct_misses"] == 1 and s["closure_misses"] == 1, s
    assert s["direct_changed_modules"] == ["mini/c.ouro"], s
    assert s["affected_modules"] == ["mini/c.ouro"], s

    # Corrupted direct artifact is not trusted even when the key path exists.
    fifth_base = run_cache(repo, seed)
    c_report = by_path(fifth_base)["mini/c.ouro"]
    corrupt = repo / c_report["direct_cache_path"]
    corrupt.write_text('{"kind":"ouro.selfhost-module-direct-artifact.v1","artifact_sha256":"bad"}\n', encoding="utf-8")
    fifth = run_cache(repo, seed)
    c_report = by_path(fifth)["mini/c.ouro"]
    assert c_report["direct_cache"] == "miss" and c_report["direct_reason"] == "artifact-hash", c_report
    assert c_report["closure_cache"] == "hit", c_report

    # Tool hash changes deliberately invalidate every direct and closure artifact.
    tool = repo / "scripts/selfhost_module_cache.py"
    tool.write_text(tool.read_text(encoding="utf-8") + "\n# suite tool-hash invalidation\n", encoding="utf-8")
    sixth = run_cache(repo, seed)
    s = sixth["summary"]
    assert s["direct_misses"] == 3 and s["closure_misses"] == 3, s


def test_cache_parity_requires_artifacts(tmp: Path) -> None:
    original_run = cache_parity.run
    cache_parity.run = lambda *_args: 0
    try:
        frontend_issues, _ = cache_parity.frontend_parity({}, tmp / "missing-frontend", 1)
        module_issues, _ = cache_parity.module_cache_parity({}, tmp / "missing-module")
    finally:
        cache_parity.run = original_run
    assert [issue["reason"] for issue in frontend_issues] == ["frontend cache parity artifact missing"], frontend_issues
    assert len(frontend_issues[0]["paths"]) == 4, frontend_issues
    assert [issue["reason"] for issue in module_issues] == ["module cache parity artifact missing"], module_issues
    assert len(module_issues[0]["paths"]) == 2, module_issues


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ouro-module-cache-suite-") as d:
        tmp = Path(d)
        test_module_cache_precision(tmp)
        test_cache_parity_requires_artifacts(tmp)
    print("SELFHOST_MODULE_CACHE_SUITE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
