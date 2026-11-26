#!/usr/bin/env python3
"""Select sample shards from the native case inventory and its import graph."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from selfhost_module_cache import quoted_import_targets

INVENTORY = "tools/test/sample_cases.ouro"
WORKFLOW_STDLIB_FIXTURE = Path("tests/workflow_stdlib_tests")
WORKFLOW_STDLIB_SOURCE = WORKFLOW_STDLIB_FIXTURE.with_suffix(".ouro").as_posix()
WORKFLOW_STDLIB_GOLDEN = WORKFLOW_STDLIB_FIXTURE.with_suffix(".golden").as_posix()
CASE_MARKER = "def sample_suite_cases : List SampleCase :="
CASE_PATH = r"(?:samples|tests)/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+"
CASE_ROW = re.compile(
    rf'MkSampleCase\s+"(?P<slug>[a-z0-9_]+)"\s+"(?P<source>{CASE_PATH}\.ouro)"'
    r'\s+(?:True|False)\s+"[^"\\\n]*"\s+(?P<run>True|False)'
    rf'\s+\((?:Nothing\s+String|Just\s+String\s+"(?P<stdin>{CASE_PATH}\.stdin)")\)'
    rf'\s+Z\s+\((?:Nothing\s+String|Just\s+String\s+"(?P<golden>{CASE_PATH}\.golden)")\)'
    r'\s+"[^"\\\n]*"'
)
SIDECAR_NAME = re.compile(r"(?<![\w-])([A-Za-z0-9_-]+\.(?:stdin|golden))\b")
SAMPLE_SOURCE = re.compile(r"samples/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.ouro\b")
# These consumers name source files as data. Import discovery cannot see those reads.
SOURCE_READERS = {
    "tools/test/suites.ouro": "test",
    "tools/ci_gate/gates.ouro": "test",
    "tools/ci_gate/host_inventory.ouro": "host-bound-inventory",
    "tests/source_span_tests.ouro": None,
    "scripts/parity_suite.sh": None,
}


def _file(root: Path, path: str) -> Path:
    local = root / path
    if (Path(path).anchor or ":" in path or "\\" in path or not local.is_relative_to(root)
            or local.resolve(strict=True) != local or not local.is_file()):
        raise ValueError(f"sample input is not a regular repository file: {path}")
    return local


def _inventory(root: Path) -> tuple[dict[str, str], dict[str, set[str]], dict[str, set[str]]]:
    source = _file(root, INVENTORY).read_text(encoding="utf-8")
    if source.count(CASE_MARKER) != 1:
        raise ValueError("missing sample inventory")
    body = re.fullmatch(r"\s*\(\[\s*(.+?)\s*\]\s*:\s*List\s+SampleCase\s*\)\s*;\s*",
                        source.split(CASE_MARKER)[1], re.DOTALL)
    if not body:
        raise ValueError("unsupported sample inventory")
    sources: dict[str, str] = {}
    sidecars: dict[str, set[str]] = {}
    listings: dict[str, set[str]] = {"samples-1": set(), "samples-2": set()}
    workflow_golden_owners: list[str] = []
    slugs: set[str] = set()
    # Mirror the separate native and check-only shard counters in sample_suite_alternate.
    next_shard = {True: 1, False: 1}
    for line in body[1].split(","):
        row = CASE_ROW.fullmatch(line.strip())
        if not row or row["slug"] in slugs or row["source"] in sources:
            raise ValueError("unsupported or duplicate sample case")
        slugs.add(row["slug"])
        _file(root, row["source"])
        run = row["run"] == "True"
        gate = f"samples-{next_shard[run]}"
        next_shard[run] = 3 - next_shard[run]
        sources[row["source"]] = gate
        kind = "native" if run else "check"
        listings[gate].add(f'{row["slug"]} {kind}')
        for sidecar in (row["stdin"], row["golden"]):
            if sidecar:
                if not run:
                    raise ValueError("sidecar on a check-only sample")
                _file(root, sidecar)
                sidecars.setdefault(sidecar, set()).add(gate)
                if sidecar == WORKFLOW_STDLIB_GOLDEN:
                    workflow_golden_owners.append(row["source"])
    if workflow_golden_owners != [WORKFLOW_STDLIB_SOURCE]:
        sidecars.pop(WORKFLOW_STDLIB_GOLDEN, None)
    return sources, sidecars, listings


def sample_routes(paths: Sequence[str], root: Path) -> dict[str, set[str]]:
    """Return gates for registered, present sample inputs. Missing keys require a full PR."""
    changed = {path for path in paths if path.startswith("samples/") or path == WORKFLOW_STDLIB_GOLDEN}
    if not changed:
        return {}
    try:
        root = root.resolve(strict=True)
        sources, sidecars, _listings = _inventory(root)
        routes = {path: sidecars[path] for path in changed.intersection(sidecars)}
        # The docs gate also checks companion existence in these sample trees.
        for path in routes:
            if path.startswith(("samples/demo/", "samples/examples/", "samples/tutorial/")):
                _file(root, Path(path).with_suffix(".ouro").as_posix())
        changed_sources = changed.intersection(sources)
        if not changed_sources and not routes:
            return {}
        # A reader can construct a sidecar path from its directory and basename.
        data_names: dict[str, set[str]] = {}
        for path in routes:
            data_names.setdefault(Path(path).name, set()).add(path)
        workflow_golden = WORKFLOW_STDLIB_GOLDEN in routes
        workflow_source_name = Path(WORKFLOW_STDLIB_SOURCE).name

        source_gates: dict[str, set[str]] = {}
        outside: set[str] = set()
        unsafe: set[str] = set()
        data_readers: dict[str, set[str]] = {}
        areas = {area: {".ouro"} for area in ("samples", "std", "tests", "tools", "compiler", "quality", "runtime")}
        areas["scripts"] = {".py", ".sh"}
        excluded = {INVENTORY, "scripts/ci_gate.py"}

        def scan_references(path: str, source: str, area: str) -> list[str] | None:
            # Another runner can derive the golden path from the fixture source.
            if workflow_golden and workflow_source_name in source:
                unsafe.add(WORKFLOW_STDLIB_GOLDEN)
            if "samples/" in source:
                names = sources.keys() & SAMPLE_SOURCE.findall(source)
                if path in SOURCE_READERS:
                    gate = SOURCE_READERS[path]
                    if gate is None:
                        outside.update(names)
                    else:
                        for name in names:
                            source_gates.setdefault(name, set()).add(gate)
                elif path in sources:
                    if data_inputs := changed_sources.intersection(names):
                        data_readers.setdefault(path, set()).update(data_inputs)
                else:
                    outside.update(names)
            if data_names and (".stdin" in source or ".golden" in source):
                for name in data_names.keys() & SIDECAR_NAME.findall(source):
                    for sidecar in data_names[name]:
                        if area == "samples" and path in sources and sidecar != WORKFLOW_STDLIB_GOLDEN:
                            data_readers.setdefault(path, set()).add(sidecar)
                        else:
                            unsafe.add(sidecar)
            if area == "scripts" or (area == "samples" and path in sources):
                return None
            if area != "samples" and "samples" not in source.casefold() and "\\u{" not in source:
                return None
            dependencies = quoted_import_targets(source, path)
            outside.update(sources.keys() & dependencies)
            return dependencies

        affected_inputs: dict[str, set[str]] = {}
        visiting: set[str] = set()

        def collect_affected(path: str) -> set[str]:
            if path in affected_inputs:
                return affected_inputs[path]
            if path in visiting:
                raise ValueError(f"sample import cycle at {path}")
            visiting.add(path)
            source = _file(root, path).read_text(encoding="utf-8")
            dependencies = None
            if changed_sources:
                area = path.partition("/")[0]
                if path not in excluded and Path(path).suffix in areas.get(area, ()):
                    dependencies = scan_references(path, source, area)
            if dependencies is None:
                dependencies = quoted_import_targets(source, path)
            del source
            hits = set(data_readers.get(path, ()))
            if path in changed_sources:
                hits.add(path)
            for dependency in dependencies:
                hits.update(collect_affected(dependency))
            visiting.remove(path)
            affected_inputs[path] = hits
            return hits

        if changed_sources:
            # Both scans must use the same source for the import cone.
            for path in sources:
                collect_affected(path)
        for area, extensions in areas.items():
            for file in (root / area).rglob("*"):
                if file.suffix not in extensions:
                    continue
                path = file.relative_to(root).as_posix()
                if path in excluded or path in affected_inputs:
                    continue
                source = _file(root, path).read_text(encoding="utf-8")
                scan_references(path, source, area)

        if changed_sources or data_readers:
            routes.update({path: {"fmt"} for path in changed_sources})
            for path, shard in sources.items():
                hits = collect_affected(path)
                if path in outside:
                    unsafe.update(hits)
                for entry in hits:
                    routes[entry].add(shard)
                    routes[entry].update(source_gates.get(path, ()))
        return {path: gates for path, gates in routes.items() if path not in unsafe}
    except (OSError, ValueError, SystemExit, RecursionError):
        return {}


def verify_shard_listings(root: Path, files: Sequence[Path]) -> bool:
    """Return False if this inventory requires the complete PR profile."""
    if len(files) != 2:
        raise ValueError("expected both native sample shard listings")
    observed_shards = []
    for file in files:
        rows = file.read_text(encoding="utf-8").splitlines()
        if not rows or any(not re.fullmatch(r"\S+ (?:native|check)", row) for row in rows):
            raise ValueError(f"{file}: malformed native sample listing")
        observed = set(rows)
        if len(observed) != len(rows):
            raise ValueError(f"{file}: duplicate row in native sample listing")
        observed_shards.append(observed)
    try:
        _sources, _sidecars, listings = _inventory(root.resolve(strict=True))
    except (OSError, ValueError):
        return False
    for shard, observed in enumerate(observed_shards, start=1):
        expected = listings[f"samples-{shard}"]
        if observed != expected:
            raise ValueError(f"{files[shard - 1]}: samples-{shard} disagrees with PR routing, "
                             f"missing={sorted(expected - observed)} extra={sorted(observed - expected)}")
    return True


def sample_listing_contract_failures() -> list[str]:
    from collections import Counter
    from tempfile import TemporaryDirectory
    from unittest.mock import patch

    with TemporaryDirectory() as temp:
        root = Path(temp).resolve()
        (root / "samples").mkdir()
        inventory = root / INVENTORY
        inventory.parent.mkdir(parents=True)
        rows = []
        for name, run in (("alpha", "True"), ("left", "False"), ("beta", "True"), ("right", "False")):
            entry = f"samples/{name}.ouro"
            (root / entry).touch()
            stdin = 'Just String "samples/alpha.stdin"' if name == "alpha" else "Nothing String"
            rows.append(f'MkSampleCase "{name}" "{entry}" True "" {run} '
                        f'({stdin}) Z (Nothing String) ""')
        literal = CASE_MARKER + "\n ([" + ", ".join(rows) + "] : List SampleCase);\n"
        inventory.write_text(literal, encoding="utf-8")
        (root / "samples/alpha.stdin").touch()
        beta = root / "samples/beta.ouro"
        left = root / "samples/left.ouro"
        right = root / "samples/right.ouro"
        shared = root / "std/shared.ouro"
        shared.parent.mkdir()
        shared.write_text("-- Used by samples.\n", encoding="utf-8")
        beta_source = 'import "alpha.ouro";\nimport "../std/shared.ouro";\n-- Reads alpha.stdin.\n'
        beta.write_text(beta_source, encoding="utf-8")
        left.write_text('import "beta.ouro";\n', encoding="utf-8")
        right.write_text('import "beta.ouro";\n', encoding="utf-8")
        sample_paths = ["samples/alpha.ouro", "samples/beta.ouro", "samples/alpha.stdin"]
        expected = {path: {"samples-1", "samples-2", "fmt"} for path in sample_paths[:2]}
        expected[sample_paths[2]] = {"samples-1", "samples-2"}
        with patch.object(Path, "open", autospec=True, side_effect=Path.open) as reads:
            selected = sample_routes(sample_paths, root)
        if selected != expected:
            return ["shared sample imports lost source or sidecar coverage"]
        inputs = {root / name for name in ("samples/alpha.ouro", "samples/beta.ouro", "samples/left.ouro",
                                          "samples/right.ouro", "std/shared.ouro")}
        if Counter(call.args[0] for call in reads.call_args_list if call.args[0] in inputs) != Counter(inputs):
            return ["sample routing must read each source in the import cone once"]
        if sample_routes([sample_paths[2]], root) != {sample_paths[2]: expected[sample_paths[2]]}:
            return ["a sidecar-only change lost its indirect sample consumers"]
        beta.write_text('import "left.ouro";\n', encoding="utf-8")
        if sample_routes(sample_paths, root):
            return ["cyclic sample imports must use the complete PR profile"]
        beta.write_text(beta_source, encoding="utf-8")
        right.write_text('import "absent.ouro";\n', encoding="utf-8")
        if sample_routes(sample_paths, root):
            return ["missing sample imports must use the complete PR profile"]
        right.write_text('import "beta.ouro";\n', encoding="utf-8")
        external = root / "std/external.ouro"
        external.write_text('import "../\\u{73}amples/alpha.ouro";\n', encoding="utf-8")
        if sample_routes(["samples/alpha.ouro"], root):
            return ["an escaped external import must use the complete PR profile"]
        external.write_text("-- No sample import.\n", encoding="utf-8")
        scripts = root / "scripts"
        scripts.mkdir()
        (scripts / "reader.py").write_text('sample = "samples/alpha.ouro"\n', encoding="utf-8")
        if "samples/alpha.ouro" in sample_routes(["samples/alpha.ouro"], root):
            return ["an external source reader lost complete sample coverage"]
        files = (root / "cases-1.txt", root / "cases-2.txt")
        files[0].write_text("alpha native\nleft check\n", encoding="utf-8")
        files[1].write_text("beta native\nright check\n", encoding="utf-8")
        try:
            if not verify_shard_listings(root, files):
                return ["valid sample inventory did not enable shard routing"]
        except ValueError as exc:
            return [f"valid native sample listings rejected: {exc}"]
        files[0].write_text("beta native\nleft check\n", encoding="utf-8")
        files[1].write_text("alpha native\nright check\n", encoding="utf-8")
        try:
            verify_shard_listings(root, files)
        except ValueError:
            pass
        else:
            return ["native sample listings swapped cases without a routing failure"]
        workflow_source = root / WORKFLOW_STDLIB_SOURCE
        workflow_source.parent.mkdir()
        workflow_source.touch()
        workflow_golden = root / WORKFLOW_STDLIB_GOLDEN
        workflow_golden.touch()
        golden_option = f'(Just String "{WORKFLOW_STDLIB_GOLDEN}")'
        workflow_row = (f'MkSampleCase "workflow_stdlib" "{WORKFLOW_STDLIB_SOURCE}" True "" True '
                        f'(Nothing String) Z {golden_option} ""')
        suffix = "] : List SampleCase);"
        workflow_inventory = literal.replace(suffix, f", {workflow_row}{suffix}")
        inventory.write_text(workflow_inventory, encoding="utf-8")
        workflow_paths = [WORKFLOW_STDLIB_GOLDEN]
        if sample_routes(workflow_paths, root) != {WORKFLOW_STDLIB_GOLDEN: {"samples-1"}}:
            return ["registered workflow golden lost its sample shard"]
        shared_owner = rows[0].replace("Z (Nothing String)", f"Z {golden_option}")
        inventory.write_text(workflow_inventory.replace(rows[0], shared_owner), encoding="utf-8")
        if sample_routes(workflow_paths, root):
            return ["workflow golden with another owner in the same shard narrowed validation"]
        inventory.write_text(workflow_inventory, encoding="utf-8")
        reader = scripts / "reader.py"
        for name in (WORKFLOW_STDLIB_SOURCE, workflow_golden.name):
            reader.write_text(f'fixture = "{name}"\n', encoding="utf-8")
            if sample_routes(workflow_paths, root):
                return ["an external workflow fixture reader narrowed validation"]
        reader.unlink()
        beta.write_text(f"{beta_source}-- Reads {workflow_golden.name}.\n", encoding="utf-8")
        if sample_routes(workflow_paths, root):
            return ["another sample reading the workflow golden narrowed validation"]
        beta.write_text(beta_source, encoding="utf-8")
        workflow_golden.unlink()
        if sample_routes(workflow_paths, root):
            return ["a missing workflow golden narrowed validation"]
        inventory.write_text(literal.replace(" Z ", " (S Z) ", 1), encoding="utf-8")
        if sample_routes(["samples/alpha.ouro"], root) or verify_shard_listings(root, files):
            return ["unrecognized sample inventory must use the complete PR profile"]
        try:
            verify_shard_listings(root, (files[0], root / "absent-list.txt"))
        except FileNotFoundError:
            return []
        return ["an unrecognized sample inventory hid a missing native shard listing"]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Verify PR routing against native sample shard listings.")
    parser.add_argument("listings", nargs=2, type=Path)
    try:
        if not verify_shard_listings(Path(__file__).resolve().parents[1], parser.parse_args().listings):
            print("SAMPLES_SUITE: sample inventory requires full PR routing", file=sys.stderr)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"SAMPLES_SUITE: FAIL {exc}\n")
