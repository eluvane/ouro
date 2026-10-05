#!/usr/bin/env python3
"""Fast regressions for the Ouro selfhost incremental module cache."""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import cache_parity_suite as cache_parity
import selfhost_module_cache as module_cache

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


def test_module_cache_import_reads(tmp: Path) -> None:
    repo = tmp / "import_reads"
    repo.mkdir()
    write_modules(repo)
    mini = repo / "mini"
    dependency = mini / "d.ouro"
    dependency.write_text('import "a.ouro";\ndef d : Nat := a;\n', encoding="utf-8")
    (mini / "c.ouro").write_text('import "b.ouro", "d.ouro";\ndef c : Nat := b;\n', encoding="utf-8")
    (mini / "e.ouro").write_text('import "b.ouro";\ndef e : Nat := b;\n', encoding="utf-8")
    paths = {name: module_cache.normalize_path(mini / f"{name}.ouro") for name in "abcde"}
    graph = {
        paths["c"]: [paths[name] for name in "abdc"],
        paths["e"]: [paths[name] for name in "abe"],
    }
    kwargs = {
        "roots": [paths["c"], paths["e"]],
        "work": repo / "work",
        "cache_root": repo / "cache",
        "fuel": "1",
        "label": "suite-import-reads",
    }
    real_imports = module_cache.import_targets

    def prepare(*, cache_enabled: bool = True, supplied_graph: bool = True) -> dict:
        reads: dict[str, int] = {}

        def counted_imports(path: str) -> list[str]:
            reads[path] = reads.get(path, 0) + 1
            return real_imports(path)

        with patch.object(module_cache, "import_targets", side_effect=counted_imports):
            report = module_cache.materialize_module_artifacts(
                **kwargs, cache_enabled=cache_enabled,
                unit_graph=graph if supplied_graph else None,
            )
        assert reads == {path: 1 for path in paths.values()}, reads
        return report

    first = prepare()
    warm = prepare()
    assert warm["summary"]["direct_hits"] == 5, warm["summary"]
    assert warm["summary"]["closure_hits"] == 5, warm["summary"]
    uncached = prepare(cache_enabled=False, supplied_graph=False)
    first_rows = by_path(first)
    for report in (warm, uncached):
        for path, row in by_path(report).items():
            for key in ("source_sha256", "bytes", "imports", "decl_count", "closure",
                        "direct_key", "closure_key", "phase_keys"):
                assert row[key] == first_rows[path][key], (path, key, row, first_rows[path])
    assert first_rows[paths["d"]]["closure"] == [paths[name] for name in "ad"], first_rows
    assert first_rows[paths["c"]]["closure"] == graph[paths["c"]], first_rows

    timestamp = dependency.stat()
    original = dependency.read_bytes()
    dependency.write_bytes(original.replace(b'"a.ouro"', b'"b.ouro"'))
    assert dependency.stat().st_size == timestamp.st_size
    os.utime(dependency, ns=(timestamp.st_atime_ns, timestamp.st_mtime_ns))
    changed = prepare()
    changed_rows = by_path(changed)
    assert changed["summary"]["direct_misses"] == 1, changed["summary"]
    assert changed["summary"]["closure_misses"] == 2, changed["summary"]
    assert changed_rows[paths["d"]]["imports"] == [paths["b"]], changed_rows
    assert changed_rows[paths["d"]]["closure"] == [paths[name] for name in "abd"], changed_rows
    assert changed_rows[paths["e"]]["closure_cache"] == "hit", changed_rows

    for body, message in (
        ('import "missing.ouro";\n', "MODULE_CACHE: FAIL missing"),
        ('import "c.ouro";\n', "MODULE_CACHE: FAIL import cycle"),
    ):
        dependency.write_text(body, encoding="utf-8")
        try:
            module_cache.materialize_module_artifacts(**kwargs, unit_graph=graph)
        except SystemExit as exc:
            assert message in str(exc), str(exc)
        else:
            raise AssertionError(f"supplied graph hid source error: {message}")


def test_import_scan_offsets() -> None:
    source = (
        "def name' : Nat := 1;\n"
        'member.import "fake.ouro";\n'
        'def literal : String := "import \\"fake2.ouro\\";";\n'
        "def scalar : Nat := 'i';\n"
        'import "left.ouro", -- grouped import\n r#"right.ouro"# as Right;\n'
    )
    assert module_cache.quoted_import_targets(source, "mini/root.ouro") == [
        "mini/left.ouro", "mini/right.ouro",
    ]
    for source in ("import name';", 'import "left.ouro", malformed;'):
        try:
            module_cache.quoted_import_targets(source, "mini/root.ouro")
        except ValueError as exc:
            assert "malformed quoted import in mini/root.ouro" in str(exc), str(exc)
        else:
            raise AssertionError(f"malformed import accepted: {source}")


def test_module_cache_label_is_report_metadata(tmp: Path) -> None:
    import selfhost_module_cache as cache

    repo = tmp / "labels"
    repo.mkdir()
    write_modules(repo)
    kwargs = {
        "roots": [(repo / "mini/c.ouro").as_posix()],
        "work": repo / "work",
        "cache_root": repo / "cache",
    }
    first = cache.materialize_module_artifacts(**kwargs, label="stage1/backend")
    artifacts = {
        path: (cache.ROOT / path).read_bytes()
        for row in first["modules"]
        for path in (row["direct_cache_path"], row["closure_cache_path"])
    }
    second = cache.materialize_module_artifacts(**kwargs, label="stage2/backend")
    assert second["label"] == "stage2/backend", second
    assert second["summary"]["direct_hits"] == 3, second["summary"]
    assert second["summary"]["closure_hits"] == 3, second["summary"]
    assert second["summary"]["direct_changed_modules"] == [], second["summary"]
    assert second["summary"]["closure_changed_modules"] == [], second["summary"]
    assert by_path(first).keys() == by_path(second).keys()
    for path, before in artifacts.items():
        assert (cache.ROOT / path).read_bytes() == before, path


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
        test_module_cache_import_reads(tmp)
        test_import_scan_offsets()
        test_module_cache_label_is_report_metadata(tmp)
        test_cache_parity_requires_artifacts(tmp)
    print("SELFHOST_MODULE_CACHE_SUITE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
