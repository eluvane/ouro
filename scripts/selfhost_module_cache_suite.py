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
from unittest.mock import call, patch

import cache_parity_suite as cache_parity
import selfhost_module_cache as module_cache

ROOT = Path(__file__).resolve().parents[1]


def copy_cache_tool(dst: Path) -> None:
    scripts = dst / "scripts"
    scripts.mkdir(parents=True)
    for name in ("selfhost_module_cache.py", "repo_support.py"):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)


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


def test_supplied_root_closures(tmp: Path) -> None:
    write_modules(tmp)
    leaf, middle, root = "mini/a.ouro", "mini/b.ouro", "mini/c.ouro"
    supplied = {root: [leaf, middle, root]}
    options = dict(roots=[root, middle, middle], unit_graph=supplied,
                   work=tmp / "work", cache_root=tmp / "cache")
    expected_reads = [call(middle), call(leaf)]
    expected_snapshots = [call(tmp / path) for path in (leaf, middle, root)]
    original_read_bytes = Path.read_bytes
    with patch.object(module_cache, "ROOT", tmp), \
         patch.object(module_cache, "import_targets", wraps=module_cache.import_targets) as read_imports, \
         patch.object(Path, "read_bytes", autospec=True, side_effect=original_read_bytes) as read_snapshot:
        first = module_cache.materialize_module_artifacts(**options)
        assert read_imports.call_args_list == expected_reads, read_imports.call_args_list
        assert read_snapshot.call_args_list == expected_snapshots, read_snapshot.call_args_list
        assert first["unit_graph"] == {root: [leaf, middle, root], middle: [leaf, middle]}
        assert supplied == {root: [leaf, middle, root]}

        uncached_options = {**options, "cache_enabled": False, "work": tmp / "uncached",
                            "cache_root": tmp / "unused-cache"}
        for invocation, hits in ((options, 3), (uncached_options, 0)):
            with patch.object(module_cache.json, "dumps", wraps=json.dumps) as dump:
                report = module_cache.materialize_module_artifacts(**invocation)
            assert report["summary"]["direct_hits"] == report["summary"]["closure_hits"] == hits
            assert report["unit_graph"] == first["unit_graph"]
            assert [row["phase_keys"] for row in report["modules"]] == [
                row["phase_keys"] for row in first["modules"]
            ]
            artifact_payloads = [
                args[0] for args, _ in dump.call_args_list
                if args[0].get("kind") in (
                    "ouro.selfhost-module-direct-artifact.v1",
                    "ouro.selfhost-module-closure-artifact.v1",
                )
            ]
            assert len(artifact_payloads) == 2 * hits, artifact_payloads
            assert all("artifact_sha256" not in payload for payload in artifact_payloads)
        assert not uncached_options["cache_root"].exists()

        (tmp / leaf).write_text("def a : Nat := S Z;\n", encoding="utf-8")
        read_imports.reset_mock()
        read_snapshot.reset_mock()
        second = module_cache.materialize_module_artifacts(**options)
        assert read_imports.call_args_list == expected_reads, read_imports.call_args_list
        assert read_snapshot.call_args_list == expected_snapshots, read_snapshot.call_args_list
    summary = second["summary"]
    assert summary["direct_changed_modules"] == [leaf], summary
    assert summary["closure_changed_modules"] == [leaf, middle, root], summary


def test_rejects_stale_root_closures(tmp: Path) -> None:
    repo = tmp / "stale-graph"
    repo.mkdir()
    write_modules(repo)
    leaf, middle, root = "mini/a.ouro", "mini/b.ouro", "mini/c.ouro"
    options = dict(roots=[root], unit_graph={root: [leaf, middle, root]},
                   work=repo / "work", cache_root=repo / "cache")
    cases = [
        ('import "missing.ouro";', "unplanned module mini/missing.ouro"),
        ('import "c.ouro";', f"import cycle while collecting {root}: {root} -> {root}"),
        ('import "a.ouro";', "ordered import closure changed"),
        ("import ;", "malformed quoted import"),
    ]
    with patch.object(module_cache, "ROOT", repo):
        for source, expected in cases:
            (repo / root).write_text(source + "\ndef c : Nat := Z;\n", encoding="utf-8")
            try:
                module_cache.materialize_module_artifacts(**options)
            except (SystemExit, ValueError) as exc:
                assert expected in str(exc), exc
            else:
                raise AssertionError(f"expected {expected} for {source}")
            assert not (repo / "work/selfhost-module-cache.json").exists()


def test_planned_closures_keep_each_import_order(tmp: Path) -> None:
    first, second = "mini/first.ouro", "mini/second.ouro"
    left, right = "mini/left.ouro", "mini/right.ouro"
    root, other = "mini/root.ouro", "mini/other.ouro"
    imports = {
        root: (left, right, left),
        other: (right, left),
        left: (first, second),
        right: (second, "mini\\first.ouro"),
        first: (),
        second: (),
    }

    plans = {
        path: module_cache.ModulePlan(path, module_cache.FileDigest(path, "", 0), edges, (), "")
        for path, edges in imports.items()
    }
    expected = {
        root: [first, second, left, right, root],
        other: [second, first, right, left, other],
        left: [first, second, left],
        right: [second, first, right],
        first: [first],
        second: [second],
    }
    with patch.object(module_cache, "make_module_plans", return_value=plans):
        report = module_cache.materialize_module_artifacts(
            roots=[root, other], unit_graph={root: expected[root], other: expected[other]},
            work=tmp / "diamond", cache_root=tmp / "cache", cache_enabled=False,
        )
    assert {row["path"]: row["closure"] for row in report["modules"]} == expected


def test_absolute_import_uses_regular_walk(tmp: Path) -> None:
    root, leaf = "root.ouro", "leaf.ouro"
    plans = {
        path: module_cache.ModulePlan(path, module_cache.FileDigest(path, "", 0), edges, (), "")
        for path, edges in ((root, (str(tmp / leaf),)), (leaf, ()))
    }
    with patch.object(module_cache, "ROOT", tmp), \
         patch.object(module_cache, "make_module_plans", return_value=plans), \
         patch.object(module_cache, "collect_units", wraps=module_cache.collect_units) as walk:
        report = module_cache.materialize_module_artifacts(
            roots=[root], unit_graph={root: [leaf, root]},
            work=tmp / "absolute", cache_root=tmp / "cache", cache_enabled=False,
        )
        assert [entry.args[0] for entry in walk.call_args_list] == [leaf, root]
    assert {row["path"]: row["closure"] for row in report["modules"]} == {
        root: [leaf, root], leaf: [leaf],
    }


def test_module_cache_precision(tmp: Path) -> None:
    repo = tmp / "repo"
    copy_cache_tool(repo)
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
        test_supplied_root_closures(tmp)
        test_rejects_stale_root_closures(tmp)
        test_planned_closures_keep_each_import_order(tmp)
        test_absolute_import_uses_regular_walk(tmp)
        test_module_cache_precision(tmp)
        test_cache_parity_requires_artifacts(tmp)
    print("SELFHOST_MODULE_CACHE_SUITE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
