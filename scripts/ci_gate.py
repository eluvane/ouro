#!/usr/bin/env python3
"""Local entry point used by GitHub Actions and maintainers.

Profiles are intentionally built from repository-local scripts so that CI never
owns a secret version of the trust policy.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Optional, Sequence

from repo_support import bind_relative_path, hash_json, sha256_file, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
rel = bind_relative_path(ROOT, resolve=True)
REPORT_KIND = "ouro.ci-gate-report.v1"
COMPILER_SHARDS = 16
LINT_PRODUCTION_SHARDS = 4


@dataclass(frozen=True)
class Gate:
    name: str
    cmd: list[str]
    profiles: tuple[str, ...]
    blocking: bool = True
    env: tuple[tuple[str, str], ...] = ()


PR_GROUPS: dict[str, tuple[str, ...]] = {
    "checks": (
        "python-syntax",
        "python-lint",
        "shell-lint",
        "ci-runner-selftest",
        "github-workflow-gate",
        "github-project-gate",
        "host-bound-inventory",
        "api-baseline-drift",
        "release-package-check",
        "config-show",
        "build-cache-config",
        "generated-artifact-hashes",
        "cache-parity-module",
        "selfhost-module-cache",
        "generated-c-shard-cache",
        "stage-loop-c-object-cache",
        "stage-loop-frontend-regeneration",
        "language-speed-simplicity",
        "fmt",
        "fix",
        "pkg",
        "doc",
        "docs-examples",
        "strict-quality-firewall",
        "structural-quality-suite",
        "structural-quality",
        "hygiene",
    ),
    "checks-parity": ("parity",),
    "checks-quality": ("syntax-quality-firewall",),
    "analysis": (
        "memory-budget",
        "c-static-analysis",
        "lsp",
    ),
    "checker": (
        "kernel-hardening",
        "compiler-scale",
        "compiler-depth",
    ),
    "analyzer": ("analyze-precision",),
    "analyzer-lint": ("lint-changed",),
    "lint": ("lint",),
    "tests": (
        "ergonomics",
        "imports",
        "frontend-security",
        "runtime-io",
        "test",
        "compiler-boundary",
    ),
    "smith": ("smith-selftest", "ouro-smith"),
    "samples-1": ("samples-1",),
    "samples-2": ("samples-2",),
    **{f"compiler-{index}": (f"compiler-checking-{index}",) for index in range(1, COMPILER_SHARDS + 1)},
}

NIGHTLY_GROUPS: dict[str, tuple[str, ...]] = {
    "checks": tuple("cache-parity-full" if name == "cache-parity-module" else name
                    for name in PR_GROUPS["checks"]),
    "checks-parity": PR_GROUPS["checks-parity"],
    "checks-quality": PR_GROUPS["checks-quality"],
    "analysis": PR_GROUPS["analysis"],
    "analyzer": ("analyze-precision", "analyze-production"),
    "lint-fixtures": ("lint-fixtures",),
    **{f"lint-production-{index}": (f"lint-production-{index}",)
       for index in range(1, LINT_PRODUCTION_SHARDS + 1)},
    "lint-clippy": ("lint-clippy",),
    "tests": (*PR_GROUPS["tests"], "quickstart-smoke"),
    "samples-1": PR_GROUPS["samples-1"],
    "samples-2": PR_GROUPS["samples-2"],
    "kernel": (*PR_GROUPS["checker"], "ouro-smith-kernel"),
    "smith-selftest": ("smith-selftest",),
    # Keep these in one checkout and preserve registry order. Smith must bind
    # its provenance to the tool binaries installed by the stage loop.
    "trust": ("stage-loop-fixpoint-and-generated-drift", "ouro-smith-nightly"),
    **{name: gates for name, gates in PR_GROUPS.items() if name.startswith("compiler-")},
}
KERNEL_GROUPS: dict[str, tuple[str, ...]] = {
    "checks": (
        "python-syntax", "kernel-hardening", "compiler-scale", "compiler-depth",
        "generated-artifact-hashes", "cache-parity-module", "compiler-boundary",
        "syntax-quality-firewall", "strict-quality-firewall", "hygiene", "ouro-smith-kernel",
    ),
    **{name: gates for name, gates in PR_GROUPS.items() if name.startswith("compiler-")},
}
STAGE_LOOP_GROUPS = {
    "checks-parity": ("parity",),
    "checks-quality": ("syntax-quality-firewall",),
    "trust": (
        "python-syntax", "strict-quality-firewall", "structural-quality-suite",
        "structural-quality", "stage-loop-fixpoint-and-generated-drift",
    ),
}
DOCS_GROUPS = {"docs": (
    "github-workflow-gate", "github-project-gate", "api-baseline-drift", "doc", "docs-examples",
)}
# The hosted PR runs the common gates once. Standalone kernel stays complete.
KERNEL_EXTRA_GROUPS = {"checks": ("ouro-smith-kernel",)}
PROFILE_GROUPS = {
    "pr": PR_GROUPS, "nightly": NIGHTLY_GROUPS, "manual": NIGHTLY_GROUPS,
    "kernel": KERNEL_GROUPS, "stage-loop": STAGE_LOOP_GROUPS,
    "docs": DOCS_GROUPS, "kernel-extra": KERNEL_EXTRA_GROUPS,
}

SHA40 = re.compile(r"[0-9a-fA-F]{40}\Z")
EDITOR_PREFIX = "editors/vscode/"
SITE_PREFIX = "site/"
DOCS_PATHS = {"README.md", "CONTRIBUTING.md"}
FULL_DOCS_PATHS = {
    "docs/architecture.md", "docs/build.md", "docs/design.md",
    "docs/kernel_design.md", "docs/tcb.md",
}
KERNEL_PREFIXES = (
    "compiler/", "runtime/", "std/", "tests/compiler_", "tests/string_nf_",
    "tests/constructor_", "quality/smith/", "scripts/ourosmith/",
)
KERNEL_PATHS = {
    "Ouro.seal",
    "docs/tcb.md",
    "docs/kernel_design.md",
    "quality/kernel_budgets.json",
    "scripts/kernel_hardening_suite.py",
    "scripts/kernel_profile.py",
    "scripts/kernel_profile_test.py",
    "scripts/kernel_scale.py",
    "scripts/kernel_scale_test.py",
    "scripts/test_suite.sh",
    "tools/test/suites.ouro",
    "tools/repo_gate/compiler_boundary.ouro",
}
DEPENDENCY_PREFIXES = (".github/workflows/", "scripts/")
DEPENDENCY_PATHS = {
    "Ouro.seal",
    "editors/vscode/package.json",
    "editors/vscode/package-lock.json",
    "site/package.json",
    "site/package-lock.json",
}

# These gates inspect repository-wide policy, not just a tool's own fixtures.
# Keep them on every code route. Unlisted inputs deliberately select the full PR.
PR_BASE_GATES = (
    "python-syntax", "python-lint", "shell-lint", "ci-runner-selftest",
    "github-workflow-gate", "github-project-gate", "api-baseline-drift",
    "generated-artifact-hashes", "docs-examples", "compiler-boundary",
    "syntax-quality-firewall", "strict-quality-firewall",
    "structural-quality-suite", "structural-quality", "hygiene",
)
TOOL_INTEGRATION_GATES = ("test", "smith-selftest", "ouro-smith", "samples-1", "samples-2", "lint")
# These gates take the changed paths as input. A selection without a routing
# plan cannot run them; the complete lint gate owns those runs.
PATH_INPUT_GATES = ("lint-changed",)
# Mirrors the production sweep in scripts/lint_suite.sh. The package sample
# needs the vendored snapshot that suite prepares, so only the complete lint
# covers it.
LINT_CHANGED_EXCLUDED_PREFIXES = ("samples/pkg/",)
LINT_CHANGED_EXPLICIT = frozenset({"samples/bench/core_suite.ouro"})
TEXT_TOOL_GATES = (
    "fmt", "fix", "analyze-precision", "memory-budget", "lsp",
    "language-speed-simplicity",
)
PR_PATH_GATES = {
    "tools/fmt.ouro": TEXT_TOOL_GATES,
    "tools/fmt_pipeline.ouro": TEXT_TOOL_GATES,
    "tools/fix/": TEXT_TOOL_GATES,
    "tools/analyze/": TEXT_TOOL_GATES,
    "tests/analyze/": TEXT_TOOL_GATES,
    "tests/fix_precision.ouro": TEXT_TOOL_GATES,
    "tests/fix_proofs.ouro": TEXT_TOOL_GATES,
    "tests/quality_diagnostic_tests.ouro": TEXT_TOOL_GATES,
    "tools/pkg/": ("pkg", "release-package-check"),
    "tests/pkg_scanner_tests.ouro": ("pkg",),
    "tools/lsp.ouro": ("lsp",),
    "tools/lsp_model.ouro": ("lsp",),
    "tools/lsp_text_encoding.ouro": ("lsp",),
    "tools/lsp_process_model.ouro": ("lsp",),
    "tools/doc.ouro": ("doc", "lsp"),
    "tools/doc_model.ouro": ("doc", "lsp"),
    "scripts/fmt_suite.sh": TEXT_TOOL_GATES,
    "scripts/fix_suite.sh": TEXT_TOOL_GATES,
    "scripts/analyze_precision_suite.sh": TEXT_TOOL_GATES,
    "scripts/pkg_suite.sh": ("pkg", "release-package-check"),
    "scripts/lsp_suite.sh": ("lsp",),
    "scripts/doc_suite.sh": ("doc", "lsp"),
}
# Control-plane changes do not alter language behavior. Their own native
# policy checks and source-bound receipts remain blocking on these routes.
CONTROL_BASE_GATES = (
    "python-syntax", "python-lint", "shell-lint", "ci-runner-selftest",
    "github-workflow-gate", "github-project-gate", "docs-examples", "structural-quality",
)
CONTROL_PATH_GATES = {
    ".github/workflows/ouro-release.yml": ("release-package-check",),
    ".github/release.yml": ("release-package-check",),
    "scripts/release_package.py": ("release-package-check",),
    "docs/releasing.md": ("release-package-check",),
    ".github/workflows/ouro-pr.yml": ("config-show", "build-cache-config"),
    "scripts/ci_gate.py": ("config-show", "build-cache-config"),
    "docs/ci.md": ("config-show", "build-cache-config"),
    "scripts/ourosmith/provenance.py": (),
    "tools/ci_gate/host_inventory.ouro": ("host-bound-inventory",),
    "tools/ci_gate/host_inventory_python.ouro": ("host-bound-inventory",),
    "tools/repo_gate/checks.ouro": ("host-bound-inventory", "compiler-boundary", "test"),
    "tools/repo_gate/policy.ouro": ("host-bound-inventory", "compiler-boundary", "test"),
    "quality/strict_debt_manifest.json": (
        "strict-quality-firewall", "structural-quality-suite", "structural-quality",
    ),
}


@dataclass(frozen=True)
class PathSelection:
    mode: str
    core: bool
    docs: bool
    kernel: bool
    editor: bool
    dependency: bool
    paths: tuple[str, ...]
    reason: str = ""
    gates: tuple[str, ...] = ()
    portable: bool = False


def normalize_changed_path(value: str) -> str:
    path = value.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def is_editor_path(path: str) -> bool:
    return path.startswith(EDITOR_PREFIX)


def is_site_path(path: str) -> bool:
    return path.startswith(SITE_PREFIX)


def is_docs_path(path: str) -> bool:
    return ("/" not in path and path.endswith(".md")) or path in DOCS_PATHS or (
        path.startswith("docs/") and path.endswith(".md")
        and not path.startswith("docs/api/") and path not in FULL_DOCS_PATHS
        and ".." not in path.split("/")
    )


def is_kernel_path(path: str) -> bool:
    if path in CONTROL_PATH_GATES:
        return False
    return path in KERNEL_PATHS or path.startswith(KERNEL_PREFIXES)


def is_dependency_path(path: str) -> bool:
    return (
        path in DEPENDENCY_PATHS
        or path.startswith(DEPENDENCY_PREFIXES)
        or path.startswith(SITE_PREFIX)
    )


def full_path_selection(reason: str) -> PathSelection:
    return PathSelection(
        mode="full",
        core=True,
        docs=True,
        kernel=True,
        editor=True,
        dependency=True,
        paths=(),
        reason=reason,
        gates=tuple(name for names in PR_GROUPS.values() for name in names if name not in PATH_INPUT_GATES),
        portable=True,
    )


def classify_paths(paths: Sequence[str]) -> PathSelection:
    normalized = tuple(normalize_changed_path(path) for path in paths if path)
    if not normalized:
        return full_path_selection("empty diff")
    selected: set[str] = set()
    full = False
    for path in normalized:
        if path.startswith("/") or ":" in path or ".." in path.split("/"):
            return full_path_selection("invalid changed path")
        if path in CONTROL_PATH_GATES:
            selected.update(CONTROL_BASE_GATES)
            selected.update(CONTROL_PATH_GATES[path])
            continue
        if is_editor_path(path) or is_site_path(path) or is_docs_path(path):
            continue
        matches = [names for pattern, names in PR_PATH_GATES.items()
                   if path == pattern or (pattern.endswith("/") and path.startswith(pattern))]
        if not matches:
            full = True
            break
        selected.update(PR_BASE_GATES)
        selected.update(TOOL_INTEGRATION_GATES)
        for names in matches:
            selected.update(names)
    if full:
        selected = {name for names in PR_GROUPS.values() for name in names if name not in PATH_INPUT_GATES}
    elif selected and any(is_docs_path(path) for path in normalized):
        selected.update(DOCS_GROUPS["docs"])
    return PathSelection(
        mode="changed",
        core=bool(selected),
        docs=any(is_docs_path(path) for path in normalized),
        kernel=any(is_kernel_path(path) for path in normalized),
        editor=any(is_editor_path(path) for path in normalized),
        dependency=any(is_dependency_path(path) for path in normalized),
        paths=normalized,
        gates=tuple(name for names in PR_GROUPS.values() for name in names if name in selected),
        portable=full,
        reason="full PR: shared or unclassified input" if full else "affected suites and policy gates",
    )


def compiler_fixture_rows(root: Path) -> list[tuple[str, str]]:
    """Read the literal inventory; refuse a shape we cannot prove complete."""
    source = (root / "tools/test/suites.ouro").read_text(encoding="utf-8")
    marker = "def compiler_check_suite_fixtures : List SuiteFixture :="
    if source.count(marker) != 1:
        raise ValueError("compiler fixture inventory marker changed")
    body = source.split(marker)[1].strip()
    rows = re.findall(r'MkSuiteFixture "([a-z0-9_]+)" "(tests/[^"\n]+\.ouro)" Z SuiteGoldenNone', body)
    remainder = re.sub(r'MkSuiteFixture "[a-z0-9_]+" "tests/[^"\n]+\.ouro" Z SuiteGoldenNone', "", body)
    if (not rows or len({name for name, _ in rows}) != len(rows)
            or len({path for _, path in rows}) != len(rows)
            or re.sub(r"[\s\[\],;]", "", remainder)):
        raise ValueError("compiler fixture inventory is not a complete literal list")
    return rows


def compiler_fixture_roots(root: Path) -> list[str]:
    return [path for _, path in compiler_fixture_rows(root)]


def compiler_shard_entries(inventory: Sequence[str], shard: int) -> list[str]:
    if (not inventory or inventory[-1] != "tests/source_span_tests.ouro"
            or inventory.count("tests/source_span_tests.ouro") != 1):
        raise ValueError("source-spans fixture must be last in the compiler inventory")
    if shard == COMPILER_SHARDS:
        return [inventory[-1]]
    if 1 <= shard < COMPILER_SHARDS:
        return list(inventory[:-1][shard - 1::COMPILER_SHARDS - 1])
    raise ValueError("unknown compiler shard")


def affected_compiler_gates(paths: Sequence[str], root: Path = ROOT) -> set[str]:
    # Reuse the build system's import reader, including aliases and relative paths.
    # Cache file reads across the 94 roots, not across revisions or invocations.
    from selfhost_module_cache import collect_units, quoted_import_targets
    from structural_quality_legacy import lex

    imports: dict[str, list[str]] = {}

    def read_imports(path: str) -> list[str]:
        if path not in imports:
            source_path = (root / path).resolve()
            if not source_path.is_relative_to(root.resolve()):
                raise ValueError("compiler fixture import escapes the repository")
            source = source_path.read_text(encoding="utf-8")
            imports[path] = quoted_import_targets(source, path)
            tokens, _comments = lex(source, "ouro")
            # Groups have several dependencies per import; the reader rejects
            # missing/malformed members before this declaration-coverage check.
            if sum(token.value == "import" for token in tokens) > len(imports[path]):
                raise ValueError(f"unsupported import layout in {path}")
        return imports[path]

    changed = set(paths)
    selected: set[str] = set()
    inventory = compiler_fixture_roots(root)
    compiler_shard_entries(inventory, COMPILER_SHARDS)
    for index, fixture in enumerate(inventory):
        if changed.intersection(collect_units(fixture, imports=read_imports)):
            shard = COMPILER_SHARDS if index == len(inventory) - 1 else index % (COMPILER_SHARDS - 1) + 1
            selected.add(f"compiler-checking-{shard}")
    return selected


def ouro_string_list(source: str, name: str) -> tuple[str, ...]:
    """Read one literal `def NAME : List String := [...]` inventory."""
    match = re.search(rf"^def {re.escape(name)} : List String :=\s*\[([^\]]*)\];", source, re.MULTILINE)
    body = match.group(1) if match else ""
    items = tuple(re.findall(r'"([^"\\\n]*)"', body))
    if source.count(f"def {name} ") != 1 or not items or re.sub(r'"[^"\\\n]*"|[\s,]', "", body):
        raise ValueError(f"{name} is not a single literal String list")
    return items


def lint_changed_sources(paths: Sequence[str], root: Path = ROOT) -> list[str]:
    """Changed files that the complete production lint would select."""
    worker = (root / "tools/lint_worker.ouro").read_text(encoding="utf-8")
    source = (root / "tools/quality/source.ouro").read_text(encoding="utf-8")
    roots = ouro_string_list(worker, "defaults")
    skipped = {*ouro_string_list(source, "quality_skip_names"), *ouro_string_list(worker, "lint_fixture_dirs")}
    fixture_names = set(ouro_string_list(worker, "lint_fixture_names"))
    selected: set[str] = set()
    for path in paths:
        parts = path.split("/")
        if not path.endswith(".ouro") or not (root / path).is_file():
            continue
        if path in LINT_CHANGED_EXPLICIT or (
            len(parts) > 1 and parts[0] in roots
            and not path.startswith(LINT_CHANGED_EXCLUDED_PREFIXES)
            and not skipped.intersection(parts[1:-1])
            and parts[-1] not in fixture_names
        ):
            selected.add(path)
    return sorted(selected)


def plan_paths(paths: Sequence[str]) -> PathSelection:
    selection = classify_paths(paths)
    if not selection.core:
        return selection
    affected: set[str] = set()
    if not selection.portable:
        try:
            affected = affected_compiler_gates(selection.paths)
        except (OSError, ValueError, SystemExit, RecursionError) as exc:
            return full_path_selection(f"compiler dependency inventory unavailable: {exc}")
    try:
        lint_sources = lint_changed_sources(selection.paths)
    except (OSError, ValueError) as exc:
        return full_path_selection(f"lint source inventory unavailable: {exc}")
    names = set(selection.gates) | affected | (set(PATH_INPUT_GATES) if lint_sources else set())
    return replace(selection, gates=tuple(name for group in PR_GROUPS.values() for name in group if name in names))


def selection_matrix(selection: PathSelection) -> dict[str, list[dict[str, str]]]:
    selected = set(selection.gates)
    # Start critical-path checks and the isolated source-spans shard before runner slots fill.
    priority = {"checks": 0, "checks-parity": 0, "checks-quality": 0}
    groups = sorted(PR_GROUPS, key=lambda name: (
        priority.get(name, 1 if name.startswith("compiler-") else 2),
        0 if name == f"compiler-{COMPILER_SHARDS}" else 1,
    ))
    return {"include": [{"group": group} for group in groups if selected.intersection(PR_GROUPS[group])]}


def selection_from_json(value: str) -> PathSelection:
    paths = json.loads(value)
    if not isinstance(paths, list) or any(not isinstance(path, str) or not path for path in paths):
        raise ValueError("changed paths must be a JSON array of nonempty strings")
    return plan_paths(paths)


def selection_key(selection: PathSelection) -> str:
    return hash_json({name: getattr(selection, name) for name in (
        "core", "docs", "kernel", "editor", "portable", "gates",
    )})


def changed_paths(base: str, head: str) -> tuple[Optional[list[str]], str]:
    if not SHA40.fullmatch(base) or not SHA40.fullmatch(head):
        return None, "base or head is not a full commit SHA"
    if base == "0" * 40:
        return None, "base SHA is unavailable"
    try:
        proc = subprocess.run(
            ["git", "diff", "--no-renames", "--name-only", "-z", base, head, "--"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"git diff unavailable: {exc}"
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip().splitlines()
        return None, detail[-1] if detail else f"git diff exited {proc.returncode}"
    values = [
        item.decode("utf-8", errors="surrogateescape")
        for item in proc.stdout.split(b"\0")
        if item
    ]
    return values, ""


def bool_text(value: bool) -> str:
    return "true" if value else "false"


def write_github_output(path: Path, selection: PathSelection) -> None:
    with path.open("a", encoding="utf-8") as output:
        for name in ("core", "docs", "kernel", "editor", "dependency", "portable"):
            output.write(f"{name}={bool_text(getattr(selection, name))}\n")
        output.write(f"mode={selection.mode}\n")
        output.write("matrix=" + json.dumps(selection_matrix(selection), separators=(",", ":")) + "\n")
        output.write("changed_paths=" + json.dumps(selection.paths, separators=(",", ":")) + "\n")
        output.write(f"selection_key={selection_key(selection)}\n")


def run_path_selection(base: str, head: str, github_output: str, *, full: bool = False) -> int:
    paths, reason = (None, "complete validation requested") if full else changed_paths(base, head)
    # Stay comfortably below GitHub's UTF-16 job-output budget. Never truncate a diff.
    if paths is not None and len(json.dumps(paths)) > 32768:
        paths, reason = None, "changed path output would exceed the routing budget"
    selection = full_path_selection(reason) if paths is None else plan_paths(paths)
    details = (
        f"mode={selection.mode} core={bool_text(selection.core)} docs={bool_text(selection.docs)} "
        f"kernel={bool_text(selection.kernel)} editor={bool_text(selection.editor)} "
        f"dependency={bool_text(selection.dependency)} paths={len(selection.paths)} "
        f"gates={len(selection.gates)} groups={len(selection_matrix(selection)['include'])}"
    )
    if selection.reason:
        details += f" reason={selection.reason}"
    print(f"CI_PATHS {details}")
    if github_output:
        try:
            write_github_output(Path(github_output), selection)
        except OSError as exc:
            print(f"CI_PATHS: FAIL cannot write GitHub output: {exc}", file=sys.stderr)
            return 1
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as output:
            output.write("### CI selection\n\n")
            output.write(f"Selected {len(selection.gates)} PR gates in {len(selection_matrix(selection)['include'])} groups.\n\n")
            for item in selection_matrix(selection)["include"]:
                names = [name for name in PR_GROUPS[item["group"]] if name in selection.gates]
                output.write(f"- **{item['group']}**: {', '.join(names)}\n")
            output.write(f"\nDocs: {bool_text(selection.docs)}; portable: {bool_text(selection.portable)}; "
                         f"kernel extra: {bool_text(selection.kernel)}; editor: {bool_text(selection.editor)}.\n")
    return 0


def compiler_evidence_paths(root: Path, binary: Path, receipt: dict) -> list[Path]:
    """Only the installed compiler and the evidence its verifier consumes travel."""
    work = Path(receipt["work"])
    if work.parent != root / "_build/bootstrap":
        raise ValueError("compiler evidence must be in this checkout's _build/bootstrap")
    paths = [binary, binary.with_name("ouro1.bootstrap.json"), work / "report.json", work / "inputs.json",
             *(work / "out" / phase / name for phase in ("p1", "p2") for name in ("driver_u.c", "backend_u.c"))]
    for path in paths:
        relative = path.relative_to(root)
        if ".." in relative.parts or any(parent.is_symlink() for parent in (path, *path.parents) if parent != root):
            raise ValueError("compiler evidence must use regular checkout paths")
    return paths


def export_compiler(root: Path, binary: Path, selected: dict, archive: Path) -> None:
    import bootstrap_compiler as bootstrap

    receipt = binary.with_name("ouro1.bootstrap.json")
    if not bootstrap.installed_current(binary, receipt, selected):
        raise ValueError("compiler or bootstrap evidence does not match current inputs")
    paths = compiler_evidence_paths(root, binary, json.loads(receipt.read_text(encoding="utf-8")))
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz") as bundle:
        for path in paths:
            bundle.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)


def import_compiler(root: Path, binary: Path, selected: dict, archive: Path, expected_sha256: str) -> None:
    import bootstrap_compiler as bootstrap

    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256) or sha256_file(archive) != expected_sha256:
        raise ValueError("compiler artifact SHA-256 differs from this workflow's producer output")
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        receipt_name = binary.with_name("ouro1.bootstrap.json").relative_to(root).as_posix()
        receipt_member = bundle.getmember(receipt_name)
        if not receipt_member.isfile():
            raise ValueError("compiler receipt is not a regular file")
        with bundle.extractfile(receipt_member) as stream:
            data = json.load(stream)
        paths = compiler_evidence_paths(root, binary, data)
        expected = {path.relative_to(root).as_posix() for path in paths}
        if len(members) != len(expected) or {member.name for member in members} != expected or any(not member.isfile() for member in members):
            raise ValueError("compiler artifact has missing, duplicate or unexpected files")
        # Do not let tar interpret paths, links, ownership or special file modes.
        for member in members:
            target = root / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.extractfile(member) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            target.chmod(member.mode & 0o777)
    if not bootstrap.installed_current(binary, binary.with_name("ouro1.bootstrap.json"), selected):
        raise ValueError("downloaded compiler or bootstrap evidence does not match current inputs")


def run_compiler_artifact(action: str, archive: Path, expected_sha256: str) -> int:
    import bootstrap_compiler as bootstrap
    import bootstrap_inputs
    import ouro_build as build

    try:
        cfg = build.load_config(argparse.Namespace())
        manifest, _contents = bootstrap_inputs.read_bundle(ROOT)
        bootstrap_inputs.verify_stage0(ROOT, manifest)
        selected = bootstrap.current_inputs(ROOT, cfg, build)
        binary = cfg.path("c_build_dir") / "ouro1"
        if action == "key":
            print("key=" + hash_json(selected))
        elif action == "export":
            export_compiler(ROOT, binary, selected, archive)
            print("sha256=" + sha256_file(archive))
        else:
            import_compiler(ROOT, binary, selected, archive, expected_sha256)
            print("CI_COMPILER: PASS current source, host compiler, binary and bootstrap evidence")
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, tarfile.TarError) as exc:
        print(f"CI_COMPILER: FAIL {exc}", file=sys.stderr)
        return 1
    return 0


def _script_paths(suffix: str) -> list[str]:
    """Inventory owned host entry points; enumeration errors must fail closed."""
    with os.scandir(ROOT / "scripts") as entries:
        return sorted(f"scripts/{entry.name}" for entry in entries
                      if entry.is_file() and entry.name.endswith(suffix))


def all_shell_scripts() -> list[str]:
    """Return repo-relative shell script paths owned by the ShellCheck gate."""
    paths = _script_paths(".sh")
    extra = ROOT / "samples" / "bioinformatics" / "fixture_tool.sh"
    if extra.is_file():
        paths.append(rel(extra))
    return paths


def shellcheck_command() -> list[str]:
    """Fail-closed ShellCheck; a missing binary is a nonzero missing command."""
    shellcheck = shutil.which("shellcheck")
    if not (ROOT / ".shellcheckrc").is_file():
        raise FileNotFoundError("required repository .shellcheckrc is missing")
    args = ["--severity=style", *all_shell_scripts()]
    if shellcheck is not None:
        return [shellcheck, *args]
    return ["shellcheck", *args]


def ruff_check_command() -> list[str]:
    """Fail-closed Ruff invocation; missing ruff becomes a nonzero module run."""
    ruff = shutil.which("ruff")
    if ruff is not None:
        return [ruff, "check", "--config", "quality/ruff.toml", "scripts"]
    return [sys.executable, "-m", "ruff", "check", "--config", "quality/ruff.toml", "scripts"]


def read_log_tail(path: Path, *, max_lines: int = 80, max_bytes: int = 64 * 1024) -> list[str]:
    """Read a bounded UTF-8 tail without loading large successful logs."""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(-max_bytes, os.SEEK_END)
            data = handle.read()
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").splitlines()
    if size > max_bytes and lines:
        lines[0] = "...<log tail truncated>..."
    return lines[-max_lines:]


def gates() -> list[Gate]:
    py_compile = [sys.executable, "-m", "py_compile"] + _script_paths(".py")
    return [
        Gate("python-syntax", py_compile, ("pr", "nightly", "manual", "kernel", "stage-loop", "bootstrap")),
        Gate("python-lint", ruff_check_command(), ("pr", "nightly", "manual")),
        Gate("shell-lint", shellcheck_command(), ("pr", "nightly", "manual")),
        Gate("ci-runner-selftest", [sys.executable, "scripts/ci_gate.py", "--self-test"], ("pr", "nightly", "manual")),
        Gate("github-workflow-gate", ["sh", "scripts/ouro_repo_gate.sh", "--profile", "workflow-native", "--out", "_build/github_workflow_gate/native-workflow"], ("pr", "nightly", "manual", "docs")),
        Gate("github-project-gate", ["sh", "scripts/ouro_repo_gate.sh", "--profile", "project-native", "--out", "_build/github_project_gate/native-project"], ("pr", "nightly", "manual", "docs")),
        Gate("host-bound-inventory", ["sh", "scripts/ouro_ci_gate.sh", "--profile", "host-bound", "--out", "_build/ci/host-bound"], ("pr", "nightly", "manual")),
        Gate("api-baseline-drift", [sys.executable, "scripts/api_baseline_regen.py", "--check", "--report", "_build/api_baseline/api-baseline.json"], ("pr", "nightly", "manual", "docs")),
        Gate("release-package-check", [sys.executable, "scripts/release_package.py", "--self-test", "--check", "--out", "_build/release_check"], ("pr", "nightly", "manual")),
        Gate("config-show", [sys.executable, "scripts/ouro_build.py", "config", "show"], ("pr", "nightly", "manual")),
        Gate("build-cache-config", [sys.executable, "scripts/build_cache_config_suite.py"], ("pr", "nightly", "manual")),
        Gate("memory-budget", [sys.executable, "scripts/memory_budget_suite.py", "--out", "_build/memory"], ("pr", "nightly", "manual"), env=(("OURO_BUILD_TOOL_MODE", "auto"),)),
        Gate("kernel-hardening", [sys.executable, "scripts/kernel_hardening_suite.py"], ("pr", "nightly", "manual", "kernel")),
        Gate("compiler-scale", [sys.executable, "scripts/kernel_scale.py", "--profile", "scale", "--out", "_build/kernel_scale/scale"], ("pr", "nightly", "manual", "kernel")),
        Gate("compiler-depth", [sys.executable, "scripts/kernel_scale.py", "--profile", "depth", "--out", "_build/kernel_scale/depth"], ("pr", "nightly", "manual", "kernel")),
        Gate("generated-artifact-hashes", [sys.executable, "scripts/generated_artifact_drift_check.py", "--mode", "hashes"], ("pr", "nightly", "manual", "kernel")),
        Gate("cache-parity-module", [sys.executable, "scripts/cache_parity_suite.py", "--scope", "module"], ("pr", "kernel")),
        Gate("cache-parity-full", [sys.executable, "scripts/cache_parity_suite.py", "--scope", "all"], ("nightly", "manual")),
        Gate("selfhost-module-cache", [sys.executable, "scripts/selfhost_module_cache_suite.py"], ("pr", "nightly", "manual")),
        Gate("generated-c-shard-cache", [sys.executable, "scripts/generated_c_shard_cache_suite.py"], ("pr", "nightly", "manual")),
        Gate("stage-loop-c-object-cache", [sys.executable, "scripts/stage_loop_generated_c_object_cache_suite.py"], ("pr", "nightly", "manual")),
        Gate("stage-loop-frontend-regeneration", [sys.executable, "scripts/stage_loop_frontend_regen_suite.py"], ("pr", "nightly", "manual")),
        Gate("language-speed-simplicity", [sys.executable, "scripts/language_speed_simplicity_suite.py"], ("pr", "nightly", "manual")),
        Gate("ergonomics", [sys.executable, "scripts/ouro_smith.py", "manifest", "--prefix=ERGO.,REC.", "--out=_build/ergonomics_suite", "--label=ERGONOMICS_SUITE"], ("pr", "nightly", "manual")),
        Gate("imports", [sys.executable, "scripts/ouro_smith.py", "manifest", "--prefix=IMP.", "--out=_build/imports_suite", "--label=IMPORTS_SUITE"], ("pr", "nightly", "manual")),
        Gate("frontend-security", ["sh", "scripts/frontend_security_suite.sh"], ("pr", "nightly", "manual"), env=(("FRONTEND_SECURITY_OUT", "_build/frontend_security"),)),
        Gate("analyze-precision", ["sh", "scripts/analyze_precision_suite.sh"], ("pr", "nightly", "manual"), env=(("OUT_DIR", "_build/analyze_precision"),)),
        Gate("analyze-production", [sys.executable, "scripts/analyze_production_suite.py", "--out", "_build/analyze_production"], ("nightly", "manual")),
        Gate("c-static-analysis", [sys.executable, "scripts/c_static_analysis_suite.py", "--out", "_build/c_static_analysis"], ("pr", "nightly", "manual")),
        Gate("parity", ["sh", "scripts/parity_suite.sh"], ("pr", "nightly", "manual", "stage-loop"), env=(("PARITY_OUT", "_build/parity"),)),
        Gate("runtime-io", ["sh", "scripts/runtime_io_suite.sh"], ("pr", "nightly", "manual"), env=(("RUNTIME_IO_OUT", "_build/runtime_io"),)),
        Gate("fmt", ["sh", "scripts/fmt_suite.sh"], ("pr", "nightly", "manual"), env=(("FMT_SUITE_OUT", "_build/fmt_suite"),)),
        Gate("fix", ["sh", "scripts/fix_suite.sh"], ("pr", "nightly", "manual"), env=(("FIX_SUITE_OUT", "_build/fix_suite"),)),
        Gate("pkg", ["sh", "scripts/pkg_suite.sh"], ("pr", "nightly", "manual"), env=(("PKG_SUITE_OUT", "_build/pkg_suite"),)),
        Gate("doc", ["sh", "scripts/doc_suite.sh"], ("pr", "nightly", "manual", "docs"), env=(("DOC_SUITE_OUT", "_build/doc_suite"),)),
        Gate("lint", ["sh", "scripts/lint_suite.sh"], ("pr",), env=(("LINT_SUITE_OUT", "_build/lint_suite"),)),
        Gate("lint-fixtures", ["sh", "scripts/lint_suite.sh", "--phase=fixtures"],
             ("nightly", "manual"), env=(("LINT_SUITE_OUT", "_build/lint_suite-fixtures"),)),
        *(Gate(f"lint-production-{index}",
               ["sh", "scripts/lint_suite.sh", "--phase=production",
                f"--shard={index}/{LINT_PRODUCTION_SHARDS}"],
               ("nightly", "manual"),
               env=(("LINT_SUITE_OUT", f"_build/lint_suite-production-{index}"),))
          for index in range(1, LINT_PRODUCTION_SHARDS + 1)),
        Gate("lint-clippy", ["sh", "scripts/lint_suite.sh", "--phase=clippy"],
             ("nightly", "manual"), env=(("LINT_SUITE_OUT", "_build/lint_suite-clippy"),)),
        # main() appends the changed production sources from the routing plan.
        Gate("lint-changed", ["sh", "scripts/ouro1.sh", "lint", "--deny", "--"], ("pr",)),
        Gate("lsp", ["sh", "scripts/lsp_suite.sh"], ("pr", "nightly", "manual"), env=(("LSP_SUITE_OUT", "_build/lsp_suite"),)),
        Gate("test", ["sh", "scripts/test_suite.sh"], ("pr", "nightly", "manual"), env=(("TEST_SUITE_OUT", "_build/test_suite"),)),
        *(Gate(f"compiler-checking-{index}", ["sh", "scripts/test_suite.sh", "--compiler-checking", f"--shard={index}/{COMPILER_SHARDS}"], ("pr", "nightly", "manual", "kernel"), env=(("TEST_SUITE_OUT", f"_build/compiler_check_suite_{index}"), ("OURO_JOBS", "1"), ("OURO_FRONTEND_JOBS", "1"))) for index in range(1, COMPILER_SHARDS + 1)),
        Gate("compiler-boundary", ["sh", "scripts/ouro_repo_gate.sh", "--profile", "compiler-boundary", "--out", "_build/compiler_boundary"], ("pr", "nightly", "manual", "kernel")),
        Gate("samples-1", ["sh", "scripts/samples_suite.sh", "--shard=1/2"], ("pr", "nightly", "manual"), env=(("SAMPLES_SUITE_OUT", "_build/samples_suite_1"),)),
        Gate("samples-2", ["sh", "scripts/samples_suite.sh", "--shard=2/2"], ("pr", "nightly", "manual"), env=(("SAMPLES_SUITE_OUT", "_build/samples_suite_2"),)),
        Gate("docs-examples", ["sh", "scripts/ouro_repo_gate.sh", "--profile", "docs-native", "--out", "_build/docs_examples_gate/native-docs"], ("pr", "nightly", "manual", "docs")),
        Gate("syntax-quality-firewall", [sys.executable, "scripts/syntax_quality_suite.py"], ("pr", "nightly", "manual", "kernel", "stage-loop")),
        Gate("strict-quality-firewall", [sys.executable, "scripts/strict_quality_firewall.py", "--profile", "release", "--report", "_build/quality/strict-quality-firewall.json", "--sarif", "_build/quality/strict-quality-firewall.sarif", "--migration-report", "_build/quality/migration-report.md"], ("pr", "nightly", "manual", "kernel", "stage-loop")),
        Gate("structural-quality-suite", [sys.executable, "scripts/structural_quality_suite.py"], ("pr", "nightly", "manual", "stage-loop")),
        Gate("structural-quality", [sys.executable, "scripts/strict_quality_firewall.py", "--structural"], ("pr", "nightly", "manual", "stage-loop")),
        Gate("hygiene", ["sh", "scripts/hygiene.sh"], ("pr", "nightly", "manual", "kernel")),
        Gate("quickstart-smoke", ["sh", "scripts/quickstart_smoke.sh"], ("nightly", "manual")),
        Gate("ouro-smith-kernel", [sys.executable, "scripts/ouro_smith.py", "--profile", "kernel", "--out", "_build/ci/smith-kernel"], ("nightly", "manual", "kernel", "kernel-extra")),
        Gate("stage-loop-fixpoint-and-generated-drift", [sys.executable, "scripts/generated_artifact_drift_check.py", "--mode", "stage-loop", "--work", "_build/generated_artifact_drift_stage_loop"], ("nightly", "manual", "stage-loop")),
        Gate("smith-selftest", [sys.executable, "scripts/ouro_smith.py", "--self-test"], ("pr", "nightly", "manual")),
        # Native suites above may rebuild tools. Bind Smith's report to the
        # final installed binaries so validation can reuse this complete run.
        Gate("ouro-smith", [sys.executable, "scripts/ouro_smith.py", "--profile", "pr", "--out", "_build/ci/smith-pr"], ("pr",)),
        Gate("ouro-smith-nightly", [sys.executable, "scripts/ouro_smith.py", "--profile", "nightly", "--out", "_build/ci/smith-nightly"], ("nightly", "manual")),
        Gate("selfhost-bootstrap-evidence", [sys.executable, "scripts/selfhost_bootstrap_evidence.py", "--out", "_build/bootstrap/evidence.json"], ("bootstrap",)),
    ]


def validate_groups(all_gates: Sequence[Gate], profile: str, groups: dict[str, tuple[str, ...]]) -> None:
    profile_names = [gate.name for gate in all_gates if profile in gate.profiles]
    owners: dict[str, str] = {}
    duplicates: list[str] = []
    for group, names in groups.items():
        if not names:
            raise ValueError(f"empty {profile} group: {group}")
        for name in names:
            if name in owners:
                duplicates.append(f"{name} ({owners[name]}, {group})")
            else:
                owners[name] = group
    unknown = sorted(set(owners) - set(profile_names))
    missing = sorted(set(profile_names) - set(owners))
    if len(set(profile_names)) != len(profile_names):
        raise ValueError(f"duplicate {profile} gate in registry")
    if duplicates or unknown or missing:
        details: list[str] = []
        if duplicates:
            details.append("duplicate=" + ",".join(duplicates))
        if unknown:
            details.append("unknown=" + ",".join(unknown))
        if missing:
            details.append("missing=" + ",".join(missing))
        raise ValueError(f"invalid {profile} group partition: " + "; ".join(details))
    if profile in {"nightly", "manual"}:
        failures = lint_phase_contract_failures(all_gates, groups)
        if failures:
            raise ValueError(f"invalid {profile} lint partition: " + "; ".join(failures))


def group_gate_names(profile: str, group: str) -> tuple[str, ...]:
    if profile in {"nightly", "manual"} and group == "lint":
        return tuple(gate for name, gates in PROFILE_GROUPS[profile].items()
                     if name.startswith("lint-") for gate in gates)
    if profile in {"nightly", "manual"} and group == "lint-production":
        return tuple(f"lint-production-{index}" for index in range(1, LINT_PRODUCTION_SHARDS + 1))
    return PROFILE_GROUPS[profile][group]


def select_group(all_gates: Sequence[Gate], profile: str, group: str) -> list[Gate]:
    names = set(group_gate_names(profile, group))
    return [gate for gate in all_gates if profile in gate.profiles and gate.name in names]


def windows_gcc_contract_failures(content: str, expected_steps: int) -> list[str]:
    failures: list[str] = []
    for name, required in (
        ("Install Windows gcc", (
            "if: ${{ runner.os == 'Windows' }}",
            "choco install mingw --version 16.1.0 --yes --no-progress",
            "gcc_bin=/c/ProgramData/mingw64/mingw64/bin",
            'if [ ! -x "$gcc_bin/gcc.exe" ]; then',
            'cygpath -w "$gcc_bin" >> "$GITHUB_PATH"',
            'echo "CC=gcc" >> "$GITHUB_ENV"',
        )),
        ("Verify Windows gcc", (
            "if: ${{ runner.os == 'Windows' }}",
            'Path("C:/ProgramData/mingw64/mingw64/bin/gcc.exe").resolve()',
            'shutil.which(os.environ["CC"])',
            "selected is None or Path(selected).resolve() != expected",
            'if version != "16.1.0":',
            "raise SystemExit",
        )),
    ):
        steps = re.findall(rf"^      - name: {name}\n(.*?)(?=^      - name: |\Z)",
                           content, re.MULTILINE | re.DOTALL)
        if len(steps) != expected_steps or any(item not in step for step in steps for item in required):
            failures.append("Windows workflows must retain pinned native gcc: " + name)
    return failures


def nightly_trust_contract_failures(groups: dict[str, tuple[str, ...]]) -> list[str]:
    failures: list[str] = []
    if groups.get("trust") != ("stage-loop-fixpoint-and-generated-drift", "ouro-smith-nightly"):
        failures.append("stage-loop and nightly Smith must remain ordered in one trust group")
    if groups.get("smith-selftest") != ("smith-selftest",):
        failures.append("Smith harness self-tests must have their own required group")
    return failures


def lint_phase_contract_failures(all_gates: Sequence[Gate], groups: dict[str, tuple[str, ...]]) -> list[str]:
    failures: list[str] = []
    names = ["lint-fixtures", *(f"lint-production-{index}" for index in range(1, 5)), "lint-clippy"]
    if LINT_PRODUCTION_SHARDS != 4:
        failures.append("production lint must retain four exhaustive shards")
    if [name for name in groups if name.startswith("lint")] != names:
        failures.append("lint phases must retain fixtures, four production shards and Clippy as ordered required groups")
    if [gate.name for gate in all_gates if gate.name in names] != names:
        failures.append("lint gates must retain fixture, production and Clippy order")
    for name in names:
        if name.startswith("lint-production-"):
            command = ["sh", "scripts/lint_suite.sh", "--phase=production", f"--shard={name.rsplit('-', 1)[1]}/4"]
        else:
            command = ["sh", "scripts/lint_suite.sh", f"--phase={name.removeprefix('lint-')}"]
        gate = next((gate for gate in all_gates if gate.name == name), None)
        if groups.get(name) != (name,) or gate is None or not gate.blocking \
                or gate.cmd != command \
                or gate.profiles != ("nightly", "manual"):
            failures.append("missing or changed blocking lint phase: " + name)
    return failures


def lint_workflow_contract_failures(content: str) -> list[str]:
    failures: list[str] = []
    jobs: dict[str, str] = {}
    for name in ("host-compiler", "lint"):
        section = re.search(rf"^  {name}:\n(.*?)(?=^  [a-z0-9-]+:|\Z)",
                            content, re.MULTILINE | re.DOTALL)
        jobs[name] = section.group(1) if section else ""
        if "    timeout-minutes: 120\n" not in jobs[name]:
            failures.append("standalone Lint job must retain its 120-minute limit: " + name)
    lint = jobs["lint"]
    names = ["lint-fixtures", *(f"lint-production-{index}" for index in range(1, 5)), "lint-clippy"]
    matrix = re.findall(r"^          - group: ([a-z0-9-]+)$", lint, re.MULTILINE)
    if matrix != names:
        failures.append("standalone Lint must schedule every required lint group once in order")
    for required in (
        "      fail-fast: false\n",
        'run: python3 scripts/ci_gate.py --profile manual --group "${{ matrix.group }}" --out "_build/ci/${{ matrix.group }}"',
        "name: lint-${{ matrix.group }}",
    ):
        if required not in lint:
            failures.append("standalone Lint lost required command or isolation: " + required.strip())
    if "run: python3 scripts/ouro_build.py build --verbosity quiet" not in jobs["host-compiler"]:
        failures.append("standalone Lint compiler producer lost its build and verification command")
    return failures


def release_workflow_contract_failures(content: str) -> list[str]:
    failures: list[str] = []
    profile_input = re.search(r"^      run_profile:\n(.*?)(?=^      [a-z_]+:|\Z)",
                              content, re.MULTILINE | re.DOTALL)
    if not profile_input or "        default: pr\n" not in profile_input.group(1) \
            or "          - pr\n" not in profile_input.group(1):
        failures.append("Release dispatch must default to the ordinary PR profile")
    if content.count("          PROFILE: ${{ inputs.run_profile || 'pr' }}") != 2:
        failures.append("Release inventory and validation must share the PR fallback")
    for required in (
        'if [ "$PROFILE" = pr ]; then',
        "python3 scripts/ci_gate.py --select-paths --full",
        '--base "$GITHUB_SHA" --head "$GITHUB_SHA" --github-output "$GITHUB_OUTPUT"',
        'python3 scripts/ci_gate.py --profile "$PROFILE" --list-groups',
        "group: ${{ fromJSON(needs.groups.outputs.matrix).include.*.group }}",
        "        exclude:\n          - group: lint\n",
    ):
        if required not in content:
            failures.append("Release lost complete profile routing: " + required)
    return failures


def lint_phase_selftest_failures(all_gates: Sequence[Gate]) -> list[str]:
    import contextlib
    import io

    failures: list[str] = []
    try:
        content = (ROOT / ".github/workflows/ouro-lint.yml").read_text(encoding="utf-8")
    except OSError as exc:
        failures.append("cannot read standalone Lint workflow: " + str(exc))
    else:
        for before, after in (
            ("          - group: lint-production-3\n", ""),
            ("          - group: lint-production-2", "          - group: lint-production-1"),
            ("--profile manual", "--profile pr"),
            ('--out "_build/ci/${{ matrix.group }}"', "--out _build/ci/lint"),
            ("      fail-fast: false", "      fail-fast: true"),
            ("    timeout-minutes: 120", "    timeout-minutes: 180"),
            ("name: lint-${{ matrix.group }}", "name: lint"),
            ("  host-compiler:\n", "  unrelated-compiler:\n"),
            ("  lint:\n", "  unrelated-lint:\n"),
        ):
            if not lint_workflow_contract_failures(content.replace(before, after, 1)):
                failures.append("standalone Lint scheduling regression was accepted: " + before)
        for name in ("host-compiler", "lint"):
            section = re.search(rf"^  {name}:\n(.*?)(?=^  [a-z0-9-]+:|\Z)",
                                content, re.MULTILINE | re.DOTALL)
            if section:
                mutated = (content[:section.start()] +
                           section.group(0).replace("    timeout-minutes: 120", "    timeout-minutes: 180", 1) +
                           content[section.end():])
                if not lint_workflow_contract_failures(mutated):
                    failures.append("standalone Lint accepted a changed job timeout: " + name)
    for profile in ("pr", "nightly", "manual"):
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            status = main(["--profile", profile, "--group", "lint", "--list"])
        expected_production = "".join(
            f"BLOCKING lint-production-{index} sh scripts/lint_suite.sh --phase=production --shard={index}/4\n"
            for index in range(1, 5))
        expected = ("BLOCKING lint sh scripts/lint_suite.sh\n" if profile == "pr" else
                    "BLOCKING lint-fixtures sh scripts/lint_suite.sh --phase=fixtures\n" +
                    expected_production + "BLOCKING lint-clippy sh scripts/lint_suite.sh --phase=clippy\n")
        if status != 0 or printed.getvalue() != expected:
            failures.append(profile + " lint alias lost complete ordered coverage")
        if profile != "pr":
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                status = main(["--profile", profile, "--group", "lint-production", "--list"])
            if status != 0 or printed.getvalue() != expected_production:
                failures.append(profile + " production alias lost exhaustive shard coverage")
    for mutated in (
        *({name: gates for name, gates in NIGHTLY_GROUPS.items() if name != f"lint-production-{index}"}
          for index in range(1, 5)),
        {**NIGHTLY_GROUPS, "lint-clippy": ("lint-fixtures",)},
        {**NIGHTLY_GROUPS, "lint": ("lint-fixtures", "lint-production", "lint-clippy")},
        {**NIGHTLY_GROUPS, "lint-production-1": ("lint-production-1", "lint-clippy")},
        {**NIGHTLY_GROUPS, "lint-production": ("lint-production-1",)},
        dict(reversed(list(NIGHTLY_GROUPS.items()))),
    ):
        if not lint_phase_contract_failures(all_gates, mutated):
            failures.append("incomplete or recombined lint phases were accepted")
    for changes in (
        {"blocking": False}, {"cmd": ["sh", "scripts/lint_suite.sh", "--phase=fixtures"]},
        {"cmd": ["sh", "scripts/lint_suite.sh", "--phase=production", "--shard=1/3"]},
        {"cmd": ["sh", "scripts/lint_suite.sh", "--phase=production", "--shard=2/4"]},
        {"profiles": ("nightly",)},
    ):
        mutated_gates = [replace(gate, **changes) if gate.name == "lint-production-1" else gate
                         for gate in all_gates]
        if not lint_phase_contract_failures(mutated_gates, NIGHTLY_GROUPS):
            failures.append("weakened production lint gate was accepted")
    if not lint_phase_contract_failures(list(reversed(all_gates)), NIGHTLY_GROUPS):
        failures.append("reordered lint gates were accepted")
    for arguments in (("--phase=unknown",), ("--phase=fixtures", "extra"), ("--phase=",),
                      ("--phase=production", "--shard=0/4"), ("--phase=production", "--shard=5/4"),
                      ("--phase=production", "--shard=1/3"), ("--phase=clippy", "--shard=1/4")):
        try:
            result = subprocess.run(["sh", str(ROOT / "scripts/lint_suite.sh"), *arguments], cwd=ROOT,
                                    capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            failures.append("cannot verify invalid lint phase: " + str(exc))
            continue
        if result.returncode != 2 or result.stdout or result.stderr.strip() != \
                "usage: lint_suite.sh [--phase=all|fixtures|production|clippy] [--shard=1/4|2/4|3/4|4/4]":
            failures.append("invalid lint phase did not fail before tool preparation")
    return failures


def check_tool_preparation_selftest_failures(all_gates: Sequence[Gate]) -> list[str]:
    import tempfile

    failures: list[str] = []
    lint_names = {"python-lint", "shell-lint"}
    for profile, groups in PROFILE_GROUPS.items():
        selected = {gate.name for gate in all_gates if profile in gate.profiles and gate.name in lint_names}
        expected = lint_names if profile in {"pr", "nightly", "manual"} else set()
        owners = {group for group, names in groups.items() if lint_names.intersection(names)}
        if selected != expected or owners != ({"checks"} if expected else set()):
            failures.append("host lint tools must remain owned only by pr/nightly/manual checks: " + profile)

    def workflow_step(content: str, job: str, name: str) -> str:
        section = re.search(rf"^  {job}:\n(.*?)(?=^  [a-z0-9-]+:|\Z)",
                            content, re.MULTILINE | re.DOTALL)
        step = re.search(rf"^      - name: {re.escape(name)}\n(.*?)(?=^      - |\Z)",
                         section.group(1) if section else "", re.MULTILINE | re.DOTALL)
        if not step:
            raise ValueError("missing workflow step: " + job + "/" + name)
        return step.group(1)

    try:
        manual = (ROOT / ".github/workflows/ouro-manual-trust.yml").read_text(encoding="utf-8")
        release = (ROOT / ".github/workflows/ouro-release.yml").read_text(encoding="utf-8")
        toolchain = workflow_step(manual, "manual-validation", "Show toolchain")
        installer = workflow_step(release, "release-validation", "Install check tools")
        metadata = workflow_step(release, "release-gates-and-package", "Show context")
    except (OSError, ValueError) as exc:
        return [*failures, "cannot inspect check tool preparation: " + str(exc)]
    if ("          INSTALL_CHECK_TOOLS: ${{ inputs.profile == 'manual' && "
            "matrix.group == 'checks' }}\n") not in toolchain:
        failures.append("Manual must prepare host lint tools only for manual/checks")
    if ("        if: ${{ matrix.group == 'checks' && (inputs.run_profile == 'manual' || "
            "inputs.run_profile == 'pr' || inputs.run_profile == '') }}\n") not in installer:
        failures.append("Release must prepare host lint tools only for empty/pr/manual checks")
    if re.search(r"\b(?:pip|ruff|shellcheck|sudo|choco|apt(?:-get)?)\b", metadata):
        failures.append("Release metadata must not repeat host lint tool installation")
    marker = "        run: |\n"
    if marker not in toolchain:
        return [*failures, "Manual toolchain must retain an executable literal run body"]
    body = "\n".join(line[10:] for line in toolchain.split(marker, 1)[1].splitlines())
    body = body.replace("${{ runner.os }}", "Linux")
    shell = shutil.which("sh")
    if shell is None:
        return [*failures, "check tool preparation self-test requires sh"]
    shell = str(Path(shell).resolve())
    pip_call = "python -m pip install --disable-pip-version-check --quiet ruff==0.15.21"
    versions = ["python --version", "gcc --version"]
    cases = (
        ("false", 19, 0, versions),
        ("true", 0, 0, [versions[0], pip_call, "shellcheck --version", versions[1]]),
        ("true", 19, 19, [versions[0], pip_call]),
    )
    # Every external command is a stub; PATH contains no host executable fallback.
    stub = (
        "#!/bin/sh\n"
        "printf '%s %s\\n' \"${0##*/}\" \"$*\"\n"
        "case \"${0##*/}:$*\" in\n"
        '  "python:--version"|"python3:--version"|"gcc:--version"|"shellcheck:--version") exit 0 ;;\n'
        '  "python:-m pip install "*|"python3:-m pip install "*) exit "$INSTALL_STATUS" ;;\n'
        "  *) exit 19 ;;\n"
        "esac\n"
    )
    try:
        with tempfile.TemporaryDirectory(prefix="ouro-check-tool-preparation-") as temporary:
            root = Path(temporary)
            for name in ("python", "python3", "gcc", "shellcheck", "sudo", "choco", "apt", "apt-get", "pip"):
                executable = root / name
                executable.write_text(stub, encoding="utf-8", newline="\n")
                executable.chmod(0o755)
            for enabled, install_status, status, expected in cases:
                env = {**os.environ, "PATH": str(root), "INSTALL_CHECK_TOOLS": enabled,
                       "INSTALL_STATUS": str(install_status)}
                try:
                    result = subprocess.run([shell, "-e", "-c", body], cwd=root, env=env,
                                            capture_output=True, text=True, timeout=5, check=False)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    failures.append("cannot run isolated tool preparation: " + str(exc))
                    continue
                if result.returncode != status or result.stdout.splitlines() != expected or result.stderr:
                    failures.append(f"Manual tool preparation lost call/failure order: {enabled}/{install_status}")
    except OSError as exc:
        failures.append("cannot prepare isolated check tool stubs: " + str(exc))
    return failures


def run_self_tests(all_gates: Sequence[Gate]) -> int:
    failures: list[str] = []
    failures.extend(summary_contract_failures())
    failures.extend(routing_contract_failures())
    failures.extend(provenance_contract_failures())
    failures.extend(lint_phase_selftest_failures(all_gates))
    failures.extend(check_tool_preparation_selftest_failures(all_gates))
    for workflow, expected_steps in (("ouro-manual-trust.yml", 2), ("ouro-release.yml", 1)):
        content = (ROOT / ".github/workflows" / workflow).read_text(encoding="utf-8")
        failures.extend(windows_gcc_contract_failures(content, expected_steps))
        for before, after in (
            ("--version 16.1.0 ", ""),
            ('cygpath -w "$gcc_bin"', 'echo "$gcc_bin"'),
            ('echo "CC=gcc"', 'echo "CC=cc"'),
            ("Verify Windows gcc", "Show Windows gcc"),
            ('if version != "16.1.0":', 'if version != "15.2.0":'),
        ):
            if not windows_gcc_contract_failures(content.replace(before, after, 1), expected_steps):
                failures.append("Windows toolchain regression accepted: " + workflow + ": " + before)
    for profile, groups in PROFILE_GROUPS.items():
        try:
            validate_groups(all_gates, profile, groups)
        except ValueError as exc:
            failures.append(str(exc))
        order = {gate.name: index for index, gate in enumerate(all_gates) if profile in gate.profiles}
        for group in groups:
            positions = [order[gate.name] for gate in select_group(all_gates, profile, group)]
            if positions != sorted(positions):
                failures.append(f"group {profile}/{group} does not preserve gate order")
        # A missing, duplicated or unknown gate must never become a green shard.
        first = next(iter(groups))
        invalid = (
            {**groups, first: groups[first][1:]},
            {**groups, "duplicate": groups[first]},
            {**groups, "unknown": ("nonexistent-gate",)},
            {**groups, "empty": ()},
        )
        for mutated in invalid:
            try:
                validate_groups(all_gates, profile, mutated)
            except ValueError:
                continue
            failures.append(f"invalid {profile} group partition was accepted")
        if profile not in {"pr", "nightly"}:
            continue
        workflow = ROOT / ".github/workflows" / ("ouro-nightly-full.yml" if profile == "nightly" else "ouro-pr.yml")
        job = {"pr": "quick-firewall", "nightly": "validation"}[profile]
        try:
            content = workflow.read_text(encoding="utf-8")
            section = re.search(rf"^  {job}:\n(.*?)(?=^  [a-z0-9-]+:|\Z)", content, re.MULTILINE | re.DOTALL)
            matrix = re.findall(r"^          - group: ([a-z0-9-]+)$", section.group(1) if section else "", re.MULTILINE)
        except OSError as exc:
            failures.append(f"cannot read {profile} workflow: {exc}")
        else:
            if profile == "pr":
                dynamic = "group: ${{ fromJSON(needs.paths.outputs.matrix).include.*.group }}"
                if not section or any(required not in section.group(1) for required in (
                    dynamic, "        exclude:\n          - group: lint\n",
                    "--changed-paths-json", "--selection-key",
                )):
                    failures.append("PR matrix must consume the routing plan and recompute affected gates")
                planned = [row["group"] for row in selection_matrix(plan_paths(["compiler/lexer.ouro"]))["include"]]
                if len(planned) != len(groups) or set(planned) != set(groups):
                    failures.append("full PR routing omits or duplicates a group")
                if planned[:3] != ["checks", "checks-parity", "checks-quality"]:
                    failures.append("long PR checks must start before compiler shards")
                if planned[3] != f"compiler-{COMPILER_SHARDS}":
                    failures.append("isolated source-spans shard must start before other compiler shards")
            elif matrix != list(groups):
                failures.append(f"hosted {profile} matrix differs from automatic group inventory: {matrix}")
    lint_workflow = (ROOT / ".github/workflows/ouro-lint.yml").read_text(encoding="utf-8")
    triggers = re.search(r"^on:\n(.*?)(?=^\S|\Z)", lint_workflow, re.MULTILINE | re.DOTALL)
    if not triggers or triggers.group(1).strip() != "workflow_dispatch:":
        failures.append("standalone lint workflow must only run manually")
    failures.extend(lint_workflow_contract_failures(lint_workflow))
    release_workflow = (ROOT / ".github/workflows/ouro-release.yml").read_text(encoding="utf-8")
    failures.extend(release_workflow_contract_failures(release_workflow))
    for before, after in (
        ("        default: pr\n", "        default: manual\n"),
        ("          - pr\n", ""),
        ("inputs.run_profile || 'pr'", "inputs.run_profile || 'manual'"),
        ("--select-paths --full", "--select-paths"),
        ("fromJSON(needs.groups.outputs.matrix).include.*.group",
         "fromJSON(needs.groups.outputs.matrix)"),
        ("        exclude:\n          - group: lint\n", ""),
    ):
        if not release_workflow_contract_failures(release_workflow.replace(before, after, 1)):
            failures.append("Release profile routing regression was accepted: " + before)
    for group in ("checks-parity", "checks-quality"):
        if NIGHTLY_GROUPS.get(group) != PR_GROUPS[group]:
            failures.append("nightly/manual must retain the isolated " + group + " group")
    smith_selftest = next((gate for gate in all_gates if gate.name == "smith-selftest"), None)
    if smith_selftest is None or not smith_selftest.blocking \
            or smith_selftest.cmd != [sys.executable, "scripts/ouro_smith.py", "--self-test"] \
            or smith_selftest.profiles != ("pr", "nightly", "manual"):
        failures.append("Smith harness self-tests must remain a blocking profile gate")
    if [gate.name for gate in select_group(all_gates, "pr", "smith")] != ["smith-selftest", "ouro-smith"]:
        failures.append("PR Smith must run harness self-tests before the generated profile")
    for profile in ("nightly", "manual"):
        failures.extend(profile + ": " + failure
                        for failure in nightly_trust_contract_failures(PROFILE_GROUPS[profile]))
    for mutated in (
        {**NIGHTLY_GROUPS, "trust": ("stage-loop-fixpoint-and-generated-drift",)},
        {**NIGHTLY_GROUPS, "trust": tuple(reversed(NIGHTLY_GROUPS["trust"]))},
        {**NIGHTLY_GROUPS, "trust": (*NIGHTLY_GROUPS["trust"], "smith-selftest")},
        {name: gates for name, gates in NIGHTLY_GROUPS.items() if name != "smith-selftest"},
        {**NIGHTLY_GROUPS, "smith-selftest": ("smith-selftest", "ouro-smith-nightly")},
    ):
        if not nightly_trust_contract_failures(mutated):
            failures.append("invalid nightly/manual trust partition was accepted")
    for group, expected in (("checks-parity", ["parity"]),
                            ("checks-quality", ["syntax-quality-firewall"])):
        selected = ([gate.name for gate in select_group(all_gates, "stage-loop", group)]
                    if group in STAGE_LOOP_GROUPS else [])
        if selected != expected:
            failures.append(f"stage-loop/{group} must isolate its long checks")
    profile_names = {profile: {gate.name for gate in all_gates if profile in gate.profiles}
                     for profile in ("pr", "kernel", "kernel-extra", "docs")}
    if profile_names["kernel-extra"] != profile_names["kernel"] - profile_names["pr"]:
        failures.append("hosted kernel extra must be exactly the kernel gates absent from PR")
    if not profile_names["docs"] <= profile_names["pr"]:
        failures.append("docs route must reuse canonical PR gates")

    cases = (
        (("editors/vscode/package-lock.json",), (False, False, True, True)),
        (("docs/ci.md",), (True, False, False, False)),
        (("compiler/file_elab.ouro",), (True, True, False, False)),
        (("tests/compiler_retained_tests.ouro",), (True, True, False, False)),
        (("compiler/lexer.ouro",), (True, True, False, False)),
        (("compiler/stage0/driver_u.c",), (True, True, False, False)),
        (("runtime/ouro_rt.c",), (True, True, False, False)),
        (("scripts/kernel_scale.py",), (True, True, False, True)),
        (("tools/repo_gate/compiler_boundary.ouro",), (True, True, False, False)),
        (("quality/smith/strategies.json",), (True, True, False, False)),
        (("tools/fmt.ouro",), (True, False, False, False)),
        (("tests/analyze/architecture_bad/a.ouro",), (True, False, False, False)),
        (("editors/vscode/src/extension.ts", "README.md"), (False, False, True, False)),
        ((".github/workflows/ouro-pr.yml",), (True, False, False, True)),
        ((), (True, True, True, True)),
    )
    for paths, expected in cases:
        selection = classify_paths(paths)
        actual = (selection.core, selection.kernel, selection.editor, selection.dependency)
        if actual != expected:
            failures.append(f"path selection mismatch for {paths}: expected={expected} actual={actual}")

    docs_cases = (
        (("README.md",), (False, True)),
        (("AGENTS.md", "RELEASE_HISTORY.md"), (False, True)),
        (("README.md", "CONTRIBUTING.md"), (False, True)),
        (("docs/getting_started.md",), (False, True)),
        (("docs/getting_started.md", "tools/fmt.ouro"), (True, True)),
        (("docs/getting_started.md", "editors/vscode/src/extension.ts", "site/src/main.ts"), (False, True)),
        (("docs/api/std.md",), (True, False)),
        (("docs/generated_artifact_hashes.sha256",), (True, False)),
        (("docs/examples/example.ouro",), (True, False)),
        (("unknown/path",), (True, False)),
        (("docs/../compiler/input.md",), (True, True)),
        (("site/src/main.ts",), (False, False)),
        (("./docs\\getting_started.md",), (False, True)),
        *((((path,), (True, False))) for path in sorted(FULL_DOCS_PATHS)),
        ((), (True, True)),
    )
    for paths, expected in docs_cases:
        selection = classify_paths(paths)
        if (selection.core, selection.docs) != expected:
            failures.append(f"docs selection mismatch for {paths}")

    if failures:
        for failure in failures:
            print(f"CI_GATE_SELFTEST: FAIL {failure}", file=sys.stderr)
        return 1
    print(
        f"CI_GATE_SELFTEST: PASS groups={len(PR_GROUPS)} "
        f"pr_gates={sum(len(names) for names in PR_GROUPS.values())} "
        f"nightly_groups={len(NIGHTLY_GROUPS)} "
        f"nightly_gates={sum(len(names) for names in NIGHTLY_GROUPS.values())} path_cases={len(cases) + len(docs_cases)}"
    )
    return 0


def routing_contract_failures() -> list[str]:
    import contextlib
    import io
    import tempfile
    from unittest.mock import patch

    failures: list[str] = []
    full = set(full_path_selection("selftest").gates)
    for path in ("scripts/ourosmith/producer_selftest.py", "scripts/ourosmith/surface/run.py", "tools/lsp.ouro"):
        if not {"smith-selftest", "ouro-smith"} <= set(classify_paths([path]).gates):
            failures.append("Smith route omitted harness regression coverage: " + path)
    for path, expected in CONTROL_PATH_GATES.items():
        selected = classify_paths([path])
        required = set(CONTROL_BASE_GATES) | set(expected)
        if not required <= set(selected.gates) < full or selected.portable or selected.kernel:
            failures.append(f"invalid control-plane route: {path}")
        for broad in ("compiler/new.ouro", "runtime/new.c", "std/new.ouro",
                      "scripts/unknown.py", "scripts/ourosmith/kernel.py",
                      "tools/repo_gate/compiler_boundary.ouro", "unknown/file"):
            mixed = classify_paths([path, broad])
            if set(mixed.gates) != full or not mixed.portable:
                failures.append(f"mixed control-plane route omitted full coverage: {path}, {broad}")
    for path in ("scripts/ci_gate.py", "scripts/release_package.py", "scripts/ourosmith/provenance.py",
                 "tools/repo_gate/checks.ouro", "tools/repo_gate/policy.ouro",
                 "tools/ci_gate/host_inventory.ouro", "tools/ci_gate/host_inventory_python.ouro"):
        if "structural-quality" not in classify_paths([path]).gates:
            failures.append(f"control-plane source lost structural policy: {path}")
    for path in ("tools/repo_gate/checks.ouro", "tools/repo_gate/policy.ouro"):
        if "test" not in classify_paths([path]).gates:
            failures.append(f"native policy route lost its user test fixtures: {path}")
    release = plan_paths([
        ".github/workflows/ouro-release.yml", "scripts/release_package.py",
        "scripts/ci_gate.py", "scripts/ourosmith/provenance.py",
        "tools/ci_gate/host_inventory.ouro", "tools/repo_gate/checks.ouro",
        "tools/repo_gate/policy.ouro", "quality/strict_debt_manifest.json",
        "AGENTS.md", "RELEASE_HISTORY.md", "docs/ci.md", "docs/releasing.md",
        "docs/roadmap.md", "docs/rfc/0000-template.md",
    ])
    expected = {
        "python-syntax", "python-lint", "shell-lint", "ci-runner-selftest",
        "github-workflow-gate", "github-project-gate", "host-bound-inventory",
        "api-baseline-drift", "release-package-check", "config-show", "build-cache-config",
        "doc", "docs-examples", "strict-quality-firewall", "structural-quality-suite",
        "structural-quality", "compiler-boundary", "test", "lint-changed",
    }
    if set(release.gates) != expected or release.kernel or release.portable:
        failures.append("release/control-plane change lost its focused policy checks")
    if any(name.startswith("compiler-checking-") for name in release.gates):
        failures.append("release/control-plane change selected unrelated compiler shards")
    if {row["group"] for row in selection_matrix(release)["include"]} != {"checks", "tests", "analyzer-lint"}:
        failures.append("release/control-plane change selected unrelated matrix groups")
    for pattern, expected in PR_PATH_GATES.items():
        path = pattern + "fixture.ouro" if pattern.endswith("/") else pattern
        selected = classify_paths([path])
        required = set(PR_BASE_GATES) | set(TOOL_INTEGRATION_GATES) | set(expected)
        if not required <= set(selected.gates) < full or selected.portable:
            failures.append(f"invalid affected route: {pattern}")
        if not set(selected.gates) <= full:
            failures.append(f"route names an unregistered gate: {pattern}")
        # Mixed changes must form a union, never let a narrow file mask a broad one.
        for broad in ("compiler/new.ouro", "runtime/new.c", "std/new.ouro", "scripts/unknown.py",
                      "tools/native_build_core.ouro", "tools/test/suites.ouro", "unknown/file"):
            mixed = classify_paths([path, broad])
            if set(mixed.gates) != full or not mixed.portable:
                failures.append(f"mixed route omitted full coverage: {path}, {broad}")
    combined = classify_paths(["tools/pkg/main.ouro", "tools/lsp.ouro", "README.md"])
    if not {"pkg", "lsp", *DOCS_GROUPS["docs"]} <= set(combined.gates):
        failures.append("mixed tools/docs route lost required gates")
    for invalid in ('{}', 'null', '"README.md"', '[false]', '[""]', '['):
        try:
            selection_from_json(invalid)
        except ValueError:
            continue
        failures.append(f"malformed changed paths accepted: {invalid}")
    if set(selection_from_json("[]").gates) != full:
        failures.append("empty diff does not select complete validation")
    with patch(__name__ + ".affected_compiler_gates", side_effect=OSError("missing import")):
        if set(plan_paths(["tools/lsp.ouro"]).gates) != full:
            failures.append("unreadable dependency graph skipped compiler coverage")
    with patch(__name__ + ".affected_compiler_gates", return_value={"compiler-checking-3"}):
        selected = plan_paths(["tools/lsp_model.ouro"])
        compiler = {name for name in selected.gates if name.startswith("compiler-checking-")}
        if compiler != {"compiler-checking-3"}:
            failures.append("dependent compiler shard was omitted or expanded incorrectly")
    selected = classify_paths(["tools/lsp.ouro"])
    arguments = ["--profile", "pr", "--group", "analysis", "--changed-paths-json", '["tools/lsp.ouro"]',
                 "--selection-key", selection_key(selected), "--list"]
    printed = io.StringIO()
    with (patch(__name__ + ".plan_paths", return_value=selected),
          contextlib.redirect_stdout(printed), contextlib.redirect_stderr(io.StringIO())):
        if main(arguments) != 0 or "BLOCKING lsp " not in printed.getvalue() or "memory-budget" in printed.getvalue():
            failures.append("affected group did not filter its unrelated gates")
        for mutated in (
            [*arguments[:-3], "--selection-key", "wrong-digest", "--list"],
            [*arguments[:3], "compiler-2", *arguments[4:]],
        ):
            try:
                main(mutated)
            except SystemExit as exc:
                if exc.code != 2:
                    failures.append("invalid selection did not report a usage error")
            else:
                failures.append("mismatched or empty selected group was accepted")
    with tempfile.TemporaryDirectory(prefix="ouro-ci-routing-") as temporary:
        root = Path(temporary)
        (root / "tools/test").mkdir(parents=True)
        (root / "tests").mkdir()
        (root / "tools/lsp_model.ouro").write_text("def value : Nat := 0;\n", encoding="utf-8")
        (root / "tests/shared.ouro").write_text('import "../tools/lsp_model.ouro" as Model;\n', encoding="utf-8")
        inventory = root / "tools/test/suites.ouro"
        rows = [f'MkSuiteFixture "case_{i}" "tests/case_{i}.ouro" Z SuiteGoldenNone'
                for i in range(COMPILER_SHARDS + 1)]
        rows.append('MkSuiteFixture "source_spans" "tests/source_span_tests.ouro" Z SuiteGoldenNone')
        inventory.write_text("def compiler_check_suite_fixtures : List SuiteFixture :=\n[" + ",\n".join(rows) + "];\n", encoding="utf-8")
        for i in range(COMPILER_SHARDS + 1):
            source = ('import "shared.ouro";\n' if i in {0, COMPILER_SHARDS - 1}
                      else "def value : Nat := 0;\n")
            (root / f"tests/case_{i}.ouro").write_text(source, encoding="utf-8")
        (root / "tools/isolated.ouro").write_text("def isolated : Nat := 0;\n", encoding="utf-8")
        (root / "tests/source_span_tests.ouro").write_text('import "../tools/isolated.ouro";\n', encoding="utf-8")
        if affected_compiler_gates(["tools/lsp_model.ouro"], root) != {"compiler-checking-1"}:
            failures.append("transitive alias import or round-robin shard ownership was lost")
        if affected_compiler_gates(["tools/isolated.ouro"], root) != {f"compiler-checking-{COMPILER_SHARDS}"}:
            failures.append("isolated compiler fixture lost its shard ownership")
        if affected_compiler_gates(["tools/unused.ouro"], root):
            failures.append("unrelated tool selected compiler shards")
        (root / "tests/shared.ouro").write_text('import\n "../tools/lsp_model.ouro";\n', encoding="utf-8")
        if affected_compiler_gates(["tools/lsp_model.ouro"], root) != {"compiler-checking-1"}:
            failures.append("multiline import lost its dependent compiler shard")
        (root / "tools/group_first.ouro").write_text("def first : Nat := 0;\n", encoding="utf-8")
        (root / "tests/shared.ouro").write_text(
            'import "../tools/group_first.ouro", -- second dependency\n "../tools/lsp_model.ouro",;\n',
            encoding="utf-8")
        for dependency in ("tools/group_first.ouro", "tools/lsp_model.ouro"):
            if affected_compiler_gates([dependency], root) != {"compiler-checking-1"}:
                failures.append("grouped import lost its dependent compiler shard: " + dependency)
        (root / "tests/shared.ouro").write_text('import "../tools/group_first.ouro", missing;\n', encoding="utf-8")
        try:
            affected_compiler_gates(["tools/lsp_model.ouro"], root)
        except ValueError:
            pass
        else:
            failures.append("malformed grouped import silently lost a dependency")
        inventory.write_text(inventory.read_text(encoding="utf-8") + "unknown_inventory_expression", encoding="utf-8")
        try:
            compiler_fixture_roots(root)
        except ValueError:
            pass
        else:
            failures.append("unsupported compiler inventory accepted")
        # A rename must expose both deletion and addition, including the old scope.
        diff = subprocess.CompletedProcess([], 0, b"compiler/old.ouro\0docs/new.md\0", b"")
        with patch(__name__ + ".subprocess.run", return_value=diff) as run:
            paths, reason = changed_paths("a" * 40, "b" * 40)
            if paths != ["compiler/old.ouro", "docs/new.md"] or reason or "--no-renames" not in run.call_args.args[0]:
                failures.append("rename diff lost the old path")
        with patch(__name__ + ".subprocess.run", side_effect=subprocess.TimeoutExpired("git", 60)):
            if changed_paths("a" * 40, "b" * 40)[0] is not None:
                failures.append("timed-out diff did not request full validation")
        output = root / "outputs"
        selected = classify_paths(['site/a\ncore=true.ts'])
        write_github_output(output, selected)
        values = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
        if values["core"] != "false" or json.loads(values["changed_paths"]) != list(selected.paths):
            failures.append("filename escaped the GitHub output record")
    failures.extend(lint_changed_contract_failures())
    return failures


def provenance_contract_failures() -> list[str]:
    import tempfile
    from unittest.mock import patch

    from ourosmith import provenance

    class Report:
        def __init__(self, binary: Path):
            self.sections = {"provenance": provenance.begin()}
            self.sections["provenance"]["binaries"] = provenance.binary_state([binary])
            self.skips: list[str] = []

        def skip(self, name: str, _reason: str) -> None:
            self.skips.append(name)

    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="ouro-provenance-") as temporary:
        root = Path(temporary)
        (root / "std").mkdir()
        (root / "_build").mkdir()
        (root / "empty-hooks").mkdir()
        source = root / "std/input.ouro"
        source.write_bytes(b"def value : Nat := 0;\n")
        binary = root / "_build/compiler"
        binary.write_bytes(b"tested compiler")
        for arguments in (
            ["init", "--quiet"], ["add", "std/input.ouro"],
            ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
             "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + str(root / "empty-hooks"),
             "commit", "--quiet", "-m", "provenance fixture"],
        ):
            subprocess.run(["git", *arguments], cwd=root, check=True, capture_output=True, timeout=15)
        with patch.object(provenance, "ROOT", root):
            stable = Report(binary)
            source.write_bytes(b"def value : Nat := 0;\r\n")
            provenance.finish(stable)
            if stable.skips:
                failures.append("provenance rejected stable inputs with normalized line endings")
            changed = Report(binary)
            source.write_bytes(b"def value : Nat := 1;\n")
            provenance.finish(changed)
            if changed.skips != ["provenance:source"]:
                failures.append("provenance accepted changed validation sources")
            untracked = Report(binary)
            (root / "std/new.ouro").write_text("def new : Nat := 0;\n", encoding="utf-8")
            provenance.finish(untracked)
            if untracked.skips != ["provenance:source"]:
                failures.append("provenance omitted new untracked production sources")
            removed = Report(binary)
            source.unlink()
            provenance.finish(removed)
            if removed.skips != ["provenance:source"]:
                failures.append("provenance omitted missing tracked inputs")
            stale = Report(binary)
            binary.write_bytes(b"replacement compiler")
            provenance.finish(stale)
            if stale.skips != ["provenance:binaries"]:
                failures.append("provenance accepted a changed tested binary")
            missing = Report(binary)
            binary.unlink()
            provenance.finish(missing)
            if missing.skips != ["provenance:binaries"]:
                failures.append("provenance accepted a missing tested binary")
            binary.write_bytes(b"replacement compiler")
            stage = Report(binary)
            stage.sections["stage_parity"] = {
                "status": "exercised", "binary": "_build/compiler", "sha256": sha256_file(binary),
            }
            provenance.finish(stage)
            if stage.skips:
                failures.append("provenance rejected a valid stage receipt")
            stage.sections["stage_parity"]["sha256"] = "0" * 64
            provenance.finish(stage)
            if stage.skips != ["provenance:stage"]:
                failures.append("provenance accepted a stale stage receipt")
    return failures


def lint_changed_contract_failures() -> list[str]:
    import contextlib
    import io
    import tempfile
    from unittest.mock import patch

    def listed(arguments: list[str]) -> tuple[object, str]:
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(io.StringIO()):
            try:
                status: object = main(arguments)
            except SystemExit as exc:
                status = exc.code
        return status, printed.getvalue()

    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="ouro-ci-lint-changed-") as temporary:
        root = Path(temporary)
        for policy in ("tools/lint_worker.ouro", "tools/quality/source.ouro"):
            (root / policy).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / policy, root / policy)
        production = ("samples/bench/core_suite.ouro", "samples/examples/demo.ouro", "std/io.ouro", "tools/lsp.ouro")
        excluded = ("samples/bench/synthesis/hole.ouro", "samples/pkg/app/main.ouro", "samples/tutorial/04_holes.ouro",
                    "tools/test/suites.ouro", "compiler/fixtures/case.ouro", "compiler/_build/case.ouro",
                    "tests/case.ouro", "runtime/managed.ouro", "std/notes.md")
        for name in (*production, *excluded):
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text("def value : Nat := 0;\n", encoding="utf-8")
        changed = [*reversed(production), *excluded, "compiler/deleted.ouro", "std/io.ouro"]
        if lint_changed_sources(changed, root) != list(production):
            failures.append("changed lint sources differ from the production lint inventory")
        worker = root / "tools/lint_worker.ouro"
        worker.write_text(worker.read_text(encoding="utf-8").replace('"future"', "future_names", 1), encoding="utf-8")
        try:
            lint_changed_sources(changed, root)
        except ValueError:
            pass
        else:
            failures.append("non-literal lint inventory was accepted")
    if "lint-changed" in full_path_selection("selftest").gates:
        failures.append("selection without changed paths requested lint-changed")
    with patch(__name__ + ".affected_compiler_gates", return_value=set()):
        route = plan_paths(["tools/lsp.ouro"])
        if "lint-changed" not in route.gates:
            failures.append("changed production source did not select lint-changed")
        if "lint-changed" in plan_paths(["tests/compiler_retained_tests.ouro", "docs/ci.md"]).gates:
            failures.append("fixture-only change selected lint-changed")
        if "lint-changed" not in plan_paths(["tools/lsp.ouro", "compiler/new.ouro"]).gates:
            failures.append("full route dropped changed production lint sources")
        with patch(__name__ + ".lint_changed_sources", side_effect=OSError("unreadable")):
            if set(plan_paths(["tools/lsp.ouro"]).gates) != set(full_path_selection("selftest").gates):
                failures.append("unreadable lint inventory did not select complete validation")
        groups = {row["group"] for row in selection_matrix(route)["include"]}
        if "analyzer-lint" not in groups or "analyzer" in groups:
            failures.append("changed LSP source did not isolate lint from analyzer precision")
        status, printed = listed(["--profile", "pr", "--group", "analyzer-lint", "--changed-paths-json",
                                  '["tools/lsp.ouro"]', "--selection-key", selection_key(route), "--list"])
        if status != 0 or printed != "BLOCKING lint-changed sh scripts/ouro1.sh lint --deny -- tools/lsp.ouro\n":
            failures.append("PR lint-changed did not receive only its changed production source")
        fixture = plan_paths(["tests/analyze/precision/absint.ouro"])
        groups = {row["group"] for row in selection_matrix(fixture)["include"]}
        if "analyzer" not in groups or "analyzer-lint" in groups:
            failures.append("analyzer fixture did not isolate precision from changed production lint")
        production = plan_paths(["tools/analyze/errors.ouro"])
        groups = {row["group"] for row in selection_matrix(production)["include"]}
        if not {"analyzer", "analyzer-lint"} <= groups:
            failures.append("analyzer source lost one of its independent validation groups")
        arguments = ["--profile", "pr", "--changed-paths-json", '["tools/analyze/errors.ouro"]',
                     "--selection-key", selection_key(production), "--list"]
        for group, expected in (
            ("analyzer", "BLOCKING analyze-precision sh scripts/analyze_precision_suite.sh\n"),
            ("analyzer-lint", "BLOCKING lint-changed sh scripts/ouro1.sh lint --deny -- tools/analyze/errors.ouro\n"),
        ):
            status, printed = listed([*arguments, "--group", group])
            if status != 0 or printed != expected:
                failures.append(f"PR {group} changed or duplicated the selected validation command")
    status, printed = listed(["--profile", "pr", "--list"])
    if status != 0 or "SKIP lint-changed requires --changed-paths-json\n" not in printed \
            or "BLOCKING lint-changed" in printed:
        failures.append("lint-changed without a routing plan was not reported as skipped")
    status, printed = listed(["--profile", "pr", "--group", "analyzer-lint", "--list"])
    if status != 2 or printed:
        failures.append("isolated lint-changed without a routing plan accepted an empty group")
    return failures


def summary_contract_failures() -> list[str]:
    """Exercise aggregate publication, independently of the gate implementations."""
    import contextlib
    import io
    import tempfile
    from unittest.mock import patch

    failures: list[str] = []
    parent = ROOT / "_build" / "ci"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="summary-contract-", dir=parent) as temporary:
        out = Path(temporary)
        summary = out / "ci-summary.json"
        gate = Gate("summary-protocol", ["unexecuted-protocol-command"], ("pr",))
        row = {"name": gate.name, "blocking": True, "status": "pass", "returncode": 0}
        args = ["--profile", "pr", "--out", str(out)]
        with (patch(__name__ + ".gates", return_value=[gate]),
              patch(__name__ + ".validate_groups"),
              contextlib.redirect_stdout(io.StringIO())):
            for interruption in (OSError("cannot start"), KeyboardInterrupt(),
                                 subprocess.TimeoutExpired(gate.cmd, 1)):
                summary.write_text('{"pass":true}\n', encoding="utf-8")
                with patch(__name__ + ".run_gate", side_effect=interruption):
                    try:
                        main(args)
                    except (OSError, KeyboardInterrupt, subprocess.TimeoutExpired):
                        pass
                    else:
                        failures.append("interrupted gate completed an aggregate")
                if summary.exists():
                    failures.append("interrupted gate retained a stale success summary")
                    summary.unlink()
            with patch(__name__ + ".run_gate", return_value=row):
                if main(args) != 0:
                    failures.append("completed positive gate failed")
            report = json.loads(summary.read_text(encoding="utf-8"))
            if report.get("pass") is not True or report.get("gates") != [row]:
                failures.append("completed gate omitted the current result")
            failed_row = dict(row, status="fail", returncode=1)
            with patch(__name__ + ".run_gate", return_value=failed_row):
                if main(args) != 1:
                    failures.append("blocking failure became a successful aggregate")
            report = json.loads(summary.read_text(encoding="utf-8"))
            if report.get("pass") is not False or report.get("gates") != [failed_row]:
                failures.append("failed aggregate did not replace previous success")
            with (patch(__name__ + ".gates", return_value=[gate, replace(gate, name="later")]),
                  patch(__name__ + ".run_gate", return_value=failed_row) as run):
                if main([*args, "--fail-fast"]) != 1 or run.call_count != 1:
                    failures.append("fail-fast ran later gates or returned success")
            report = json.loads(summary.read_text(encoding="utf-8"))
            if report.get("pass") is not False or report.get("not_run") != ["later"]:
                failures.append("fail-fast hid the unexecuted gate")
            previous = summary.read_bytes()
            with patch(__name__ + ".run_gate") as run:
                main([*args, "--list"])
                if run.called or summary.read_bytes() != previous:
                    failures.append("listing gates changed execution evidence")
            summary.unlink()
            summary.mkdir()
            with patch(__name__ + ".run_gate") as run:
                try:
                    main(args)
                except OSError:
                    pass
                else:
                    failures.append("unremovable prior summary did not fail")
                if run.called or not summary.is_dir():
                    failures.append("summary cleanup failure started gates or removed a directory")
    return failures


def env_for(gate: Gate, out: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("OURO_ROOT", ROOT.as_posix())
    env.setdefault("PYTHON", Path(sys.executable).as_posix())
    env.setdefault("OURO_CI", "1")
    env.setdefault("OURO_REPRODUCIBLE", "1")
    env.setdefault("OURO_PACK_STRICT", "1")
    env.setdefault("OURO_JOBS", "10")
    env.setdefault("OURO_CACHE_DIR", (ROOT / "_cache" / "ouro").as_posix())
    env.setdefault("OURO_BUILD_DIR", (ROOT / "_build").as_posix())
    env.setdefault("OURO_C_BUILD_DIR", (ROOT / "_build" / "c").as_posix())
    for k, v in gate.env:
        env[k] = (ROOT / v).as_posix() if v.startswith("_build/") else v
    env["OURO_CI_GATE_NAME"] = gate.name
    env["OURO_CI_GATE_OUT"] = out.as_posix()
    return env


def run_gate(gate: Gate, *, out: Path) -> dict[str, Any]:
    started = time.perf_counter()
    gate_dir = out / gate.name
    gate_dir.mkdir(parents=True, exist_ok=True)
    log = gate_dir / "gate.log"
    env = env_for(gate, out)
    print(f"CI_GATE_START {gate.name} cmd={shlex.join(gate.cmd)}", flush=True)
    with log.open("w", encoding="utf-8") as f:
        p = subprocess.Popen(gate.cmd, cwd=ROOT, env=env, text=True, stdout=f, stderr=subprocess.STDOUT)
        last_heartbeat = time.perf_counter()
        last_fixture_progress: tuple[tuple[str, ...], tuple[str, ...]] | None = None
        last_source_phase: str | None = None
        last_phase_check = started
        while p.poll() is None:
            now = time.perf_counter()
            if gate.name == f"compiler-checking-{COMPILER_SHARDS}" and now - last_phase_check >= 2.0:
                marker = ROOT / "_build/source_spans.progress"
                try:
                    phase = marker.read_text(encoding="utf-8").strip()
                except FileNotFoundError:
                    phase = ""
                if phase and phase != last_source_phase:
                    print(f"CI_GATE_SOURCE_SPANS_PHASE {phase}", flush=True)
                    last_source_phase = phase
                last_phase_check = now
            if now - last_heartbeat >= 30.0:
                print(f"CI_GATE_PROGRESS {gate.name} elapsed_s={now - started:.1f} log={rel(log)}", flush=True)
                if gate.name.startswith("compiler-checking-"):
                    suite_out = Path(env["TEST_SUITE_OUT"])
                    built = tuple(sorted(path.name.removesuffix(".exe.build.json")
                                         for path in suite_out.glob("*.exe.build.json")))
                    completed = tuple(sorted(path.stem for path in suite_out.glob("*.out")
                                             if not path.name.startswith("cli-")))
                    progress = (built, completed)
                    if progress != last_fixture_progress:
                        print(f"CI_GATE_FIXTURE_PROGRESS {gate.name} built={','.join(built)} completed={','.join(completed)}", flush=True)
                        last_fixture_progress = progress
                last_heartbeat = now
            time.sleep(0.25)
        rc = int(p.returncode or 0)
    status = "pass" if rc == 0 else "fail"
    show_tail = status == "fail" or os.environ.get("OURO_CI_TAIL_PASS") == "1"
    tail = read_log_tail(log) if show_tail else []
    if tail:
        print(f"CI_GATE_LOG_TAIL {gate.name} lines={len(tail)}")
        for line in tail:
            print(line)
    print(f"CI_GATE_DONE {gate.name} status={status} rc={rc} elapsed_s={time.perf_counter() - started:.3f} log={rel(log)}", flush=True)
    return {
        "name": gate.name,
        "blocking": gate.blocking,
        "status": status,
        "returncode": rc,
        "elapsed_s": round(time.perf_counter() - started, 6),
        "log": rel(log),
        "command": gate.cmd,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", choices=[*PROFILE_GROUPS, "bootstrap"], default="pr")
    ap.add_argument("--group", default=None, help="run one complete profile partition in an isolated checkout")
    ap.add_argument("--out", default=None)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--list-groups", action="store_true", help="print the complete profile group list as JSON")
    ap.add_argument("--self-test", action="store_true", help="check PR/nightly partitions and hosted path-selection invariants")
    ap.add_argument("--select-paths", action="store_true", help="write fail-closed hosted job selection from a commit diff")
    ap.add_argument("--full", action="store_true", help="select all jobs for push, merge queue, or manual validation")
    ap.add_argument("--changed-paths-json", default=None, help="recompute affected PR gates from the Paths job output")
    ap.add_argument("--selection-key", default=None, help="require exactly the producer's complete routing decision")
    ap.add_argument("--fail-fast", action="store_true", help="stop a group after its first blocking failure")
    ap.add_argument("--base", default=None, help="base commit SHA for --select-paths")
    ap.add_argument("--head", default=None, help="head commit SHA for --select-paths")
    ap.add_argument("--github-output", default=None, help="GitHub output file for --select-paths")
    ap.add_argument("--compiler-artifact", choices=("key", "export", "import"), help="transfer a verified compiler within one workflow")
    ap.add_argument("--artifact", type=Path, default=Path("_build/ci/host-compiler.tar.gz"))
    ap.add_argument("--compiler-sha256", default="", help="required producer digest for compiler import")
    ap.add_argument(
        "--with-bootstrap-evidence",
        action="store_true",
        help="append the selfhost bootstrap evidence gate to the selected profile",
    )
    args = ap.parse_args(argv)

    if args.compiler_artifact:
        if args.group or args.out or args.list or args.list_groups or args.self_test or args.select_paths or args.base or args.head or args.github_output or args.with_bootstrap_evidence or args.full or args.changed_paths_json is not None or args.selection_key or args.fail_fast:
            ap.error("--compiler-artifact cannot be combined with gate or path-selection options")
        if (args.compiler_artifact == "import") != bool(args.compiler_sha256):
            ap.error("--compiler-sha256 is required exactly for compiler import")
        return run_compiler_artifact(args.compiler_artifact, args.artifact, args.compiler_sha256)
    if args.compiler_sha256:
        ap.error("--compiler-sha256 requires --compiler-artifact import")
    all_gates = gates()
    if args.select_paths:
        if args.group is not None or args.out or args.list or args.list_groups or args.self_test or args.with_bootstrap_evidence or args.changed_paths_json is not None or args.selection_key or args.fail_fast:
            ap.error("--select-paths cannot be combined with execution options")
        if not args.base or not args.head:
            ap.error("--select-paths requires --base and --head")
        return run_path_selection(
            args.base,
            args.head,
            args.github_output or os.environ.get("GITHUB_OUTPUT", ""),
            full=args.full,
        )
    if args.base or args.head or args.github_output or args.full:
        ap.error("--base, --head, --full, and --github-output require --select-paths")
    if args.changed_paths_json is not None and (args.profile != "pr" or not args.group or args.self_test or args.list_groups or args.with_bootstrap_evidence):
        ap.error("--changed-paths-json requires --profile pr --group and cannot change other profiles")
    if (args.changed_paths_json is not None) != bool(args.selection_key):
        ap.error("--changed-paths-json and --selection-key must be supplied together")
    if args.self_test:
        if args.group is not None or args.out or args.list or args.list_groups or args.with_bootstrap_evidence:
            ap.error("--self-test cannot be combined with execution options")
        return run_self_tests(all_gates)
    try:
        for profile, groups in PROFILE_GROUPS.items():
            validate_groups(all_gates, profile, groups)
    except ValueError as exc:
        print(f"CI_GATE: FAIL {exc}", file=sys.stderr)
        return 2
    if args.list_groups:
        if args.group is not None or args.out or args.list or args.with_bootstrap_evidence:
            ap.error("--list-groups cannot be combined with execution options")
        if args.profile not in PROFILE_GROUPS:
            ap.error(f"profile {args.profile} has no group partition")
        print(json.dumps(list(PROFILE_GROUPS[args.profile])))
        return 0
    if args.group is not None and args.group not in PROFILE_GROUPS.get(args.profile, {}) \
            and not (args.profile in {"nightly", "manual"} and args.group in {"lint", "lint-production"}):
        ap.error(f"unknown group {args.group!r} for profile {args.profile}")
    if args.group and args.with_bootstrap_evidence:
        ap.error("--group cannot be combined with --with-bootstrap-evidence")
    selected = [g for g in all_gates if args.profile in g.profiles]
    if args.group:
        selected = select_group(all_gates, args.profile, args.group)
    if args.changed_paths_json is not None:
        try:
            selection = selection_from_json(args.changed_paths_json)
        except (ValueError, TypeError) as exc:
            ap.error(f"invalid changed paths: {exc}")
        if selection_key(selection) != args.selection_key:
            ap.error("routing decision differs from the Paths job; refusing incomplete matrix coverage")
        selected = [gate for gate in selected if gate.name in selection.gates]
        if not selected:
            ap.error("selected PR group has no affected gates; refusing an empty green job")
        if any(gate.name in PATH_INPUT_GATES for gate in selected):
            sources = lint_changed_sources(selection.paths)
            if not sources:
                ap.error("lint-changed was selected without changed production Ouro sources")
            selected = [replace(gate, cmd=[*gate.cmd, *sources]) if gate.name in PATH_INPUT_GATES else gate
                        for gate in selected]
        skipped: list[Gate] = []
    else:
        skipped = [gate for gate in selected if gate.name in PATH_INPUT_GATES]
        selected = [gate for gate in selected if gate.name not in PATH_INPUT_GATES]
        if skipped and not selected:
            ap.error("lint-changed requires --changed-paths-json; the lint group owns complete coverage")
    if args.with_bootstrap_evidence and not any(g.name == "selfhost-bootstrap-evidence" for g in selected):
        selected.extend(g for g in all_gates if g.name == "selfhost-bootstrap-evidence")
    if args.list:
        for g in selected:
            print(("BLOCKING" if g.blocking else "INFO") + " " + g.name + " " + shlex.join(g.cmd))
        for g in skipped:
            print(f"SKIP {g.name} requires --changed-paths-json")
        return 0

    default_out = ROOT / "_build" / "ci" / args.profile
    if args.group:
        default_out /= args.group
    out = Path(args.out) if args.out else default_out
    if not out.is_absolute():
        out = ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    # An interrupted or unstartable run must not leave a previous successful
    # aggregate at the public result path. Listing and validation above are read-only.
    summary_path = out / "ci-summary.json"
    summary_path.unlink(missing_ok=True)
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    skips = [{"name": gate.name, "blocking": gate.blocking, "status": "skip",
              "reason": "requires --changed-paths-json"} for gate in skipped]
    for skip in skips:
        print(f"CI_GATE_SKIP {skip['name']} reason={skip['reason']}")
    failed = False
    for gate in selected:
        result = run_gate(gate, out=out)
        results.append(result)
        if result["status"] == "fail" and gate.blocking:
            failed = True
            if args.fail_fast:
                break
            # Continue running remaining gates so the artifact bundle explains as
            # many independent regressions as possible.
    report = {
        "kind": REPORT_KIND,
        "profile": args.profile,
        "group": args.group or "all",
        "pass": not failed,
        "gates": results,
        "not_run": [gate.name for gate in selected[len(results):]],
        "blocking_failures": [r for r in results if r.get("blocking") and r.get("status") == "fail"],
        "informational_skips": [*skips, *(r for r in results if r.get("status") == "skip")],
        "elapsed_s": round(time.perf_counter() - started, 6),
        "policy": {
            "blocking": "every registered gate is required; missing tools and nonzero exits fail",
            "reports": "every gate writes a log under the CI output directory; underlying scripts write JSON reports under _build",
            "cache": "restored build/cache data is a speed hint only and is followed by regeneration/recheck/parity gates",
        },
    }
    write_json_atomic(summary_path, report)
    print(
        f"CI_GATE_SUMMARY profile={args.profile} group={args.group or 'all'} "
        f"pass={int(not failed)} gates={len(results)} report={rel(out / 'ci-summary.json')}"
    )
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
