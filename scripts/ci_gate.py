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
import tempfile
import time
import zlib
from contextlib import ExitStack
from dataclasses import dataclass, replace
from functools import cache, lru_cache, partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Sequence

from ci_sample_paths import WORKFLOW_STDLIB_GOLDEN, sample_listing_contract_failures, sample_routes
from compiler_shards import COMPILER_SHARDS, SHARD_MEMORY_MIB
from local_scheduler import Allocation, CheckoutSnapshot, Task, available_memory_mib, bounded_jobs, configured_jobs, run_tasks
from repo_support import bind_relative_path, bool_env, hash_json, sha256_bytes, sha256_file, write_json_atomic
from selfhost_module_cache import cached_import_parser

if TYPE_CHECKING:
    from collections.abc import Callable

    from selfhost_module_cache import ImportBytesParser

ROOT = Path(__file__).resolve().parents[1]
rel = bind_relative_path(ROOT, resolve=True)
REPORT_KIND = "ouro.ci-gate-report.v1"
COMPILER_PREPARATION = "host-compiler-preparation"
COLLECTOR_PREPARATION = "host-collector-preparation"
TEST_RUNNER_PREPARATION = "host-test-runner-preparation"
LINT_PREPARATION = "host-lint-preparation"
PACKAGE_PREPARATION = "host-package-preparation"
HOST_TOOLS = {
    COLLECTOR_PREPARATION: ("tools/collect.ouro", "ouro-collect", "c"),
    TEST_RUNNER_PREPARATION: ("tools/test/main.ouro", "ouro-test-suite", "t"),
    LINT_PREPARATION: ("tools/lint.ouro", "ouro-lint", "l"),
    PACKAGE_PREPARATION: ("tools/pkg/main.ouro", "ouro-pkg", "p"),
}
LINT_PRODUCTION_SHARDS = 4
LINT_STAGE_ENV = "OURO_CI_LINT_STAGE"
LINT_SUBSHARD_ENV = "OURO_CI_LINT_SUBSHARD"
PATH_OUTPUT_BUDGET = 32768


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

MANUAL_GROUPS: dict[str, tuple[str, ...]] = {
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
NIGHTLY_ISOLATED_CHECKS = ("language-speed-simplicity", "fix")
NIGHTLY_GROUPS = {
    "checks": tuple(name for name in MANUAL_GROUPS["checks"] if name not in NIGHTLY_ISOLATED_CHECKS),
    **{name: (name,) for name in NIGHTLY_ISOLATED_CHECKS},
    **{name: gates for name, gates in MANUAL_GROUPS.items() if name != "checks"},
}
PR_LINT_PHASES = {name: NIGHTLY_GROUPS[name] for name in ("lint-fixtures", "lint-clippy")}
PR_FALLBACK_LINT_GROUPS = {
    **PR_LINT_PHASES,
    **{name: names for name, names in NIGHTLY_GROUPS.items() if name.startswith("lint-production-")},
}
# The selection key hashes gate order even when the matrix groups change.
ROUTED_PR_GROUPS = {**PR_GROUPS, **PR_FALLBACK_LINT_GROUPS}
PR_ISOLATED_TEST_GATES = ("runtime-io", "frontend-security")
PULL_REQUEST_GROUPS = {
    **ROUTED_PR_GROUPS,
    "tests": tuple(name for name in PR_GROUPS["tests"] if name not in PR_ISOLATED_TEST_GATES),
    **{name: (name,) for name in PR_ISOLATED_TEST_GATES},
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
    "pr": PR_GROUPS, "nightly": NIGHTLY_GROUPS, "manual": MANUAL_GROUPS,
    "kernel": KERNEL_GROUPS, "stage-loop": STAGE_LOOP_GROUPS,
    "docs": DOCS_GROUPS, "kernel-extra": KERNEL_EXTRA_GROUPS,
}

SHA40 = re.compile(r"[0-9a-fA-F]{40}\Z")
REPOSITORY_PATH_GATES = {
    ".shellcheckrc": ("shell-lint",),
    "quality/ruff.toml": ("python-lint",),
    "quality/kernel_budgets.json": ("kernel-hardening", "python-syntax", "host-bound-inventory"),
    "quality/kernel_baseline.json": ("kernel-hardening", "python-syntax"),
    "quality/memory_budgets.json": ("memory-budget",),
    "quality/memory_baseline.json": ("memory-budget", "host-bound-inventory"),
    "quality/rejected_syntax.json": ("syntax-quality-firewall",),
    "quality/fixtures/clippy_grade/manifest.json": ("lint-clippy", "host-bound-inventory"),
    "quality/fixtures/clippy_grade/structural.json": ("lint-clippy",),
    "quality/fixtures/manifest.json": (
        "strict-quality-firewall", "syntax-quality-firewall", "structural-quality", "github-project-gate", "host-bound-inventory",
    ),
    "LICENSE": ("github-project-gate", "release-package-check", "docs-examples"),
    ".github/ISSUE_TEMPLATE/config.yml": ("github-project-gate", "host-bound-inventory", "docs-examples"),
    **dict.fromkeys((
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/diagnostics_ice.yml",
        ".github/ISSUE_TEMPLATE/docs.yml",
        ".github/ISSUE_TEMPLATE/language_proposal.yml",
        ".github/ISSUE_TEMPLATE/performance.yml",
        ".github/dependabot.yml",
        ".github/pull_request_template.md",
        ".github/workflow-owners.md",
    ), ("github-project-gate", "docs-examples")),
    **dict.fromkeys((
        ".github/workflows/dependency-review.yml",
        ".github/workflows/ouro-lint.yml",
        ".github/workflows/ouro-nightly-full.yml",
        ".github/workflows/ouro-pages.yml",
    ), ("ci-runner-selftest", "github-workflow-gate", "docs-examples")),
}
EDITOR_PREFIX = "editors/vscode/"
SITE_PREFIX = "site/"
DOCS_PATHS = {"README.md", "CONTRIBUTING.md"}
FULL_DOCS_PATHS = {
    "docs/architecture.md", "docs/build.md", "docs/design.md",
    "docs/kernel_design.md", "docs/tcb.md",
}
KERNEL_PREFIXES = (
    "compiler/", "runtime/", "std/", "tests/compiler_", "tests/compiler/", "tests/string_nf_",
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
    "scripts/ouro_smith.py",
    "scripts/test_suite.sh",
    "tools/test/suites.ouro",
    "tools/repo_gate/compiler_boundary.ouro",
}
DEPENDENCY_PATHS = {
    "Ouro.seal",
    "editors/vscode/package.json",
    "editors/vscode/package-lock.json",
    "site/package.json",
    "site/package-lock.json",
}

# The syntax suite also requires zero allowed debt in the production scan.
PR_BASE_GATES = (
    "docs-examples", "syntax-quality-firewall", "strict-quality-firewall", "structural-quality",
)
TOOL_SMITH_GATES = ("smith-selftest", "ouro-smith")
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
    "language-speed-simplicity", "test", "lint", *TOOL_SMITH_GATES,
)
PR_PATH_GATES = {
    "tools/fmt.ouro": TEXT_TOOL_GATES,
    "tools/fmt_paths.ouro": TEXT_TOOL_GATES,
    "tools/fmt_pipeline.ouro": TEXT_TOOL_GATES,
    "tools/fix/": TEXT_TOOL_GATES,
    "tools/analyze/": TEXT_TOOL_GATES,
    "tools/pkg/": ("pkg", "release-package-check", "test", "lint", "memory-budget"),
    "tools/lsp.ouro": ("lsp", "memory-budget", "lint", *TOOL_SMITH_GATES),
    "tools/lsp_model.ouro": ("lsp", "memory-budget", "lint", *TOOL_SMITH_GATES),
    "tools/lsp_text_encoding.ouro": ("lsp", "memory-budget", "lint", *TOOL_SMITH_GATES),
    "tools/lsp_process_model.ouro": ("lsp", "memory-budget", "lint", *TOOL_SMITH_GATES),
    "tools/doc.ouro": ("doc", "memory-budget", "lint", *TOOL_SMITH_GATES),
    "tools/doc/model.ouro": ("doc", "lsp", "memory-budget", "lint", *TOOL_SMITH_GATES),
    "tools/doc/selftest.ouro": ("doc", "memory-budget", "lint", *TOOL_SMITH_GATES),
    "tools/lines.ouro": ("test", "memory-budget", "lint"),
}
FIXTURE_GATES = {
    "tests/fix_laws.ouro": ("fix",),
    "tests/fix_precision.ouro": ("fix",),
    "tests/fix_proofs.ouro": ("fix",),
    "tests/pkg_scanner_tests.ouro": ("pkg", "test"),
}
ISOLATED_COMPILER_FIXTURES = {
    "tests/native_live_tests.ouro", "tests/native_pe_tests.ouro", "tests/compiler_checked_program_tests.ouro",
    "tests/compiler_file_helper_tests.ouro", "tests/compiler_fs_predicate_binding_tests.ouro",
}
HOST_ONLY_GATES = frozenset(("python-syntax", "python-lint", "shell-lint", "ci-runner-selftest", "api-baseline-drift"))
LOCAL_LIGHTWEIGHT_GATES = HOST_ONLY_GATES | {"config-show", "generated-artifact-hashes", "hygiene", "release-package-check"}
LOCAL_PRIVATE_BUILDS = {"build-cache-config", "selfhost-module-cache", "generated-c-shard-cache",
                        "stage-loop-c-object-cache", "stage-loop-frontend-regeneration", "selfhost-bootstrap-evidence"}
LOCAL_SERIAL_BUILD_GATES = {"selfhost-module-cache", "stage-loop-c-object-cache"}
LOCAL_CHECK_LANES = {
    **{name: name for name in LOCAL_LIGHTWEIGHT_GATES | LOCAL_PRIVATE_BUILDS | {"pkg", "doc", "language-speed-simplicity"}},
    **dict.fromkeys(("github-workflow-gate", "github-project-gate", "host-bound-inventory", "docs-examples"), "repo-policy"),
    **dict.fromkeys(("fmt", "fix"), "format-fix"),
}
LOCAL_COMPILER_GATES = {name for groups in PROFILE_GROUPS.values() for names in groups.values() for name in names} \
    - LOCAL_LIGHTWEIGHT_GATES - LOCAL_PRIVATE_BUILDS
# Control-plane changes do not alter language behavior. Their own native
# policy checks and source-bound receipts remain blocking on these routes.
CONTROL_BASE_GATES = (
    "python-syntax", "python-lint", "shell-lint", "ci-runner-selftest",
    "github-workflow-gate", "github-project-gate", "docs-examples", "structural-quality",
)
CONTROL_PATH_GATES = {
    ".github/workflows/ouro-manual-trust.yml": ("config-show", "build-cache-config", "api-baseline-drift", "doc"),
    ".github/workflows/ouro-release.yml": ("release-package-check",),
    ".github/release.yml": ("release-package-check",),
    "scripts/release_package.py": ("release-package-check",),
    "docs/releasing.md": ("release-package-check",),
    ".github/workflows/ouro-pr.yml": ("config-show", "build-cache-config"),
    "scripts/ci_gate.py": ("config-show", "build-cache-config"),
    "scripts/ci_sample_paths.py": ("host-bound-inventory", "samples-1", "samples-2"),
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
    paths: tuple[str, ...]
    reason: str = ""
    gates: tuple[str, ...] = ()
    portable: bool = False
    site: bool = False
    lint_sources: tuple[str, ...] = ()

    @property
    def host_compiler(self) -> bool:
        return self.docs or bool(set(self.gates) - HOST_ONLY_GATES)

    @property
    def dependency(self) -> bool:
        return self.mode == "full" or workflow_scan_required(self.paths)


def normalize_changed_path(value: str) -> str:
    path = value.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def is_editor_path(path: str) -> bool:
    return path.startswith(EDITOR_PREFIX)


def is_site_path(path: str) -> bool:
    return path.startswith(SITE_PREFIX)


def generated_api_pages(paths: Sequence[str]) -> set[str]:
    pages = {"docs/api/README.md"}.intersection(paths)
    pending = {path for path in paths if path.startswith("docs/api/std_") and path.endswith(".md")}
    if not pending:
        return pages
    try:
        for source in (ROOT / "std").rglob("*.ouro"):
            if not source.name.endswith(".ouro"):
                continue
            # Match doc_out_name in tools/doc/model.ouro, including nested modules.
            module = source.relative_to(ROOT).as_posix().partition(".ouro")[0]
            page = "docs/api/" + re.sub(r"[/\\:]", "_", module) + ".md"
            if page not in pending:
                continue
            try:
                if not source.is_file():
                    continue
            except OSError:
                pass
            else:
                pages.add(page)
            pending.remove(page)
            if not pending:
                break
    except OSError:
        pass
    return pages


def is_docs_path(path: str, api_pages: set[str]) -> bool:
    return ("/" not in path and path.endswith(".md")) or path in DOCS_PATHS or path in api_pages or (
        path.startswith("docs/") and path.endswith(".md")
        and not path.startswith("docs/api/") and path not in FULL_DOCS_PATHS
        and ".." not in path.split("/")
    )


def is_kernel_path(path: str) -> bool:
    if path in CONTROL_PATH_GATES:
        return False
    return path in KERNEL_PATHS or path.startswith(KERNEL_PREFIXES)


def is_smith_regression(path: str) -> bool:
    return bool(re.fullmatch(r"quality/smith/regressions/[^/]+\.json", path)) and (ROOT / path).is_file()


def workflow_scan_required(paths: Sequence[str]) -> bool:
    changed = set(paths)
    launchers = {
        "Ouro.seal", "scripts/ci_gate.py", "scripts/github_workflow_gate.py", "scripts/ouro_repo_gate.sh",
        "scripts/native_gate_launcher.sh", "scripts/bootstrap.sh",
    }
    if changed.intersection(launchers):
        return True
    if any(path.startswith((".github/workflows/", "tools/repo_gate/")) for path in changed):
        return True
    ouro_changed = any(path.endswith(".ouro") for path in changed)
    if not ouro_changed and not any(path.startswith(("scripts/", "runtime/")) for path in changed):
        return False
    try:
        import bootstrap_compiler
        import frontend_regen
        import native_tool_build

        if changed.intersection((*bootstrap_compiler.HELPERS, *native_tool_build.BUILD_INPUTS, *native_tool_build.RUNTIME)):
            return True
        if any(path.startswith("runtime/") and path.endswith(".h") and path.count("/") == 1 for path in changed):
            return True
        if not ouro_changed:
            return False
        roots = native_tool_build.tool_roots("tools/repo_gate/main.ouro")
        return any(not changed.isdisjoint(units) for units in frontend_regen.collect_units_many(roots).values())
    except (ImportError, OSError, ValueError, RuntimeError, SystemExit):
        return True


def full_path_selection(reason: str) -> PathSelection:
    return PathSelection(
        mode="full",
        core=True,
        docs=True,
        kernel=True,
        editor=True,
        paths=(),
        reason=reason,
        gates=tuple(name for names in PR_GROUPS.values() for name in names if name not in PATH_INPUT_GATES),
        portable=True,
        site=True,
    )


def valid_changed_path(path: str) -> bool:
    return not (":" in path or "\0" in path or {"", ".", ".."}.intersection(path.split("/")))


def file_gates(path: str, samples: dict[str, set[str]], compiler_fixtures: dict[str, str], *,
               documentation: bool,
               fixture_gates: Callable[[str], set[str] | None] | None = None) -> set[str] | None:
    if path in CONTROL_PATH_GATES:
        return {*CONTROL_BASE_GATES, *CONTROL_PATH_GATES[path]}
    if path in REPOSITORY_PATH_GATES:
        if path in {"quality/kernel_baseline.json", "quality/kernel_budgets.json"} and not (ROOT / path).is_file():
            return None
        return set(REPOSITORY_PATH_GATES[path])
    if is_smith_regression(path):
        return {"ouro-smith"}
    if re.fullmatch(r"quality/api_surface/[^/]+\.tsv", path) and (ROOT / path).is_file():
        return {"api-baseline-drift"}
    if path.startswith(("quality/fixtures/bad/", "quality/fixtures/good/")) and (ROOT / path).is_file():
        try:
            manifest = json.loads((ROOT / "quality/fixtures/manifest.json").read_text(encoding="utf-8"))
            if any(case["path"] == path for case in [*manifest["bad"], *manifest["good"]]):
                return {"syntax-quality-firewall", "strict-quality-firewall", "structural-quality"}
        except (KeyError, OSError, TypeError, ValueError):
            return None
    if is_site_path(path) or is_editor_path(path):
        gates = set()
        if path in {"editors/vscode/package.json", "editors/vscode/package-lock.json"}:
            gates.update(("release-package-check", "github-project-gate"))
        if path.endswith(".md") or (path in {"editors/vscode/package.json", "site/public/licenses/phosphor-LICENSE.txt"}
                                   and not (ROOT / path).is_file()):
            gates.add("docs-examples")
        return gates
    if path == "quality/biome.json" or documentation:
        return set()
    if path == "scripts/compiler_shards.py":
        return {"python-syntax", "python-lint", "host-bound-inventory", "ci-runner-selftest",
                *(f"compiler-checking-{index}" for index in range(1, COMPILER_SHARDS + 1))}
    if path in HOST_SUITE_GATES:
        lint = {"python-syntax", "python-lint"} if path.endswith(".py") else {"shell-lint"}
        return lint | {"structural-quality", "host-bound-inventory", *HOST_SUITE_GATES[path]}
    if path == WORKFLOW_STDLIB_GOLDEN and path in compiler_fixtures:
        return None
    if path in samples:
        policy = {"strict-quality-firewall", "structural-quality", "docs-examples"} if path.endswith(".ouro") else set()
        return samples[path] | policy
    fixture = (fixture_gates or analyzer_fixture_gates)(path)
    if fixture is not None:
        if path.endswith(".ouro") or path == "tests/analyze/manifest.json":
            fixture.add("structural-quality")
        return fixture
    if path in FIXTURE_GATES and (ROOT / path).is_file():
        return {"structural-quality", *FIXTURE_GATES[path]}
    if path in compiler_fixtures and (ROOT / path).is_file():
        if path.endswith(".golden"):
            return {compiler_fixtures[path]}
        if path in ISOLATED_COMPILER_FIXTURES:
            return {"structural-quality", compiler_fixtures[path]}
    if not path.endswith(".ouro") or path == "tools/fix/lex.ouro":
        return None
    for pattern, names in PR_PATH_GATES.items():
        if path == pattern or (pattern.endswith("/") and path.startswith(pattern)):
            source = ROOT / path
            try:
                if not source.is_file() or source.resolve(strict=True) != source:
                    return None
            except (OSError, RuntimeError):
                return None
            return {*PR_BASE_GATES, *names}
    return None


def classify_paths(paths: Sequence[str]) -> PathSelection:
    normalized = tuple(sorted({normalize_changed_path(path) for path in paths}))
    if not normalized:
        return full_path_selection("empty diff")
    if not all(valid_changed_path(path) for path in normalized):
        return full_path_selection("invalid changed path")
    samples = sample_routes(normalized, ROOT)
    fixtures = {}
    if any(path in ISOLATED_COMPILER_FIXTURES or (path.startswith("tests/") and path.endswith(".golden"))
           for path in normalized):
        try:
            fixtures = compiler_fixture_input_gates(ROOT)
        except (OSError, ValueError):
            pass
    selected: set[str] = set()
    full = False
    docs = False
    api_pages = generated_api_pages(normalized)
    clippy_gates = partial(clippy_fixture_gates, parse_imports=cached_import_parser(),
                           case_paths=lru_cache(maxsize=1)(_clippy_case_paths))
    fixture_gates = partial(analyzer_fixture_gates, clippy_gates=clippy_gates,
                            pipeline_paths=lru_cache(maxsize=1)(_analyzer_pipeline_paths))
    for path in normalized:
        documentation = is_docs_path(path, api_pages)
        docs = docs or documentation
        names = file_gates(path, samples, fixtures, documentation=documentation, fixture_gates=fixture_gates)
        if names is None:
            full = True
            if path.startswith(("tests/clippy_", "tools/clippy/")) or path in {
                    "scripts/lint_suite.sh", "tools/lint.ouro", "tools/lint_worker.ouro"}:
                selected.update(PR_LINT_PHASES)
            elif path in {"tests/quality_input_tests.ouro", "tests/quality_diagnostic_tests.ouro",
                          "scripts/bench_suite.py", "scripts/ouro1.sh", "scripts/tool_preparation_suite.py"}:
                selected.add("lint-fixtures")
            elif path == "quality/clippy_grade_rules.json":
                selected.add("lint-clippy")
        else:
            selected.update(names)
    if full:
        selected.update(name for names in PR_GROUPS.values() for name in names if name not in PATH_INPUT_GATES)
    elif selected and docs:
        selected.update(DOCS_GROUPS["docs"])
    return PathSelection(
        mode="changed",
        core=bool(selected),
        docs=docs,
        kernel=any(is_kernel_path(path) and (full or (path not in fixtures and not is_smith_regression(path)))
                   for path in normalized),
        editor=any(is_editor_path(path) or path in {"quality/biome.json", ".github/workflows/ouro-pr.yml"} for path in normalized),
        site=any(is_site_path(path) or path in {"quality/biome.json", ".github/workflows/ouro-pages.yml",
                                                ".github/workflows/ouro-pr.yml"} for path in normalized),
        paths=normalized,
        gates=tuple(name for names in ROUTED_PR_GROUPS.values() for name in names if name in selected),
        portable="kernel-hardening" in selected,
        reason="full PR: shared or unclassified input" if full else "affected suites and policy gates",
    )


def compiler_fixture_rows(root: Path) -> list[tuple[str, str]]:
    """Read the literal inventory; refuse a shape we cannot prove complete."""
    source = (root / "tools/test/suites.ouro").read_text(encoding="utf-8")
    marker = "def compiler_check_suite_fixtures : List SuiteFixture :="
    if source.count(marker) != 1:
        raise ValueError("compiler fixture inventory marker changed")
    body = source.split(marker)[1].strip()
    pattern = r'MkSuiteFixture "([a-z0-9_]+)" "(tests/[^"\n]+\.ouro)" Z SuiteGolden(?:None|Required)'
    rows = re.findall(pattern, body)
    remainder = re.sub(pattern, "", body)
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


def compiler_fixture_input_gates(root: Path = ROOT) -> dict[str, str]:
    inventory = compiler_fixture_roots(root)
    compiler_shard_entries(inventory, COMPILER_SHARDS)
    owners = {}
    for index, fixture in enumerate(inventory):
        shard = COMPILER_SHARDS if index == len(inventory) - 1 else index % (COMPILER_SHARDS - 1) + 1
        gate = f"compiler-checking-{shard}"
        owners[fixture] = gate
        # The runner compares an existing sibling golden even for SuiteGoldenNone.
        owners[Path(fixture).with_suffix(".golden").as_posix()] = gate
    return owners


def affected_compiler_gates(paths: Sequence[str], root: Path = ROOT) -> set[str]:
    from graphlib import TopologicalSorter

    from selfhost_module_cache import normalize_path, quoted_import_targets
    from structural_quality_legacy import lex

    root = root.resolve()
    owners = compiler_fixture_input_gates(root)
    changed = set(paths)
    if any(path.startswith(("tests/compiler_", "tests/compiler/")) and path.endswith("_tests.ouro")
           and path not in owners for path in paths):
        contract = "tests/compiler_suite_contract_tests.ouro"
        if contract not in owners:
            raise ValueError("compiler suite directory inventory has no registered owner")
        changed.add(contract)

    imports: dict[str, list[str]] = {}
    runner = "tools/test/main.ouro"
    pending = [runner, *(path for path in reversed(owners) if path.endswith(".ouro"))]
    while pending:
        path = pending.pop()
        if path in imports:
            continue
        source_path = (root / path).resolve()
        if not source_path.is_relative_to(root):
            raise ValueError("compiler fixture import escapes the repository")
        source = source_path.read_text(encoding="utf-8")
        dependencies = [normalize_path(target) for target in quoted_import_targets(source, path)]
        import_tokens, _comments = lex(source, "ouro", only_lexeme="import", collect_comments=False)
        if len(import_tokens) > len(dependencies):
            raise ValueError(f"unsupported import layout in {path}")
        imports[path] = dependencies
        pending.extend(reversed(dependencies))
        if path == "tests/source_span_tests.ouro":
            # This fixture also reads repository sources as runtime data.
            for item in ouro_string_list(source, "ss_files"):
                resolved = (root / item).resolve(strict=True).relative_to(root).as_posix()
                if item in changed or resolved in changed:
                    changed.add(path)

    for path in TopologicalSorter(imports).static_order():
        if not changed.isdisjoint(imports[path]):
            changed.add(path)
    if runner in changed:
        return {f"compiler-checking-{shard}" for shard in range(1, COMPILER_SHARDS + 1)}
    return {owners[path] for path in changed if path in owners}


def ouro_string_list(source: str, name: str) -> tuple[str, ...]:
    """Read one literal `def NAME : List String := [...]` inventory."""
    match = re.search(rf"^def {re.escape(name)} : List String :=\s*\[([^\]]*)\];", source, re.MULTILINE)
    body = match.group(1) if match else ""
    items = tuple(re.findall(r'"([^"\\\n]*)"', body))
    if source.count(f"def {name} ") != 1 or not items or re.sub(r'"[^"\\\n]*"|[\s,]', "", body):
        raise ValueError(f"{name} is not a single literal String list")
    return items


def _analyzer_pipeline_paths(text: str) -> tuple[set[str], set[str]]:
    pipeline = json.loads(text)["pipeline"]
    rows = pipeline["bad"] + pipeline["good"]
    scopes = {row["scope"] for row in rows}
    goldens = {row["golden"] for row in rows if "golden" in row}
    return scopes, goldens


def analyzer_fixture_gates(
    path: str, *,
    clippy_gates: Callable[[str], set[str] | None] | None = None,
    pipeline_paths: Callable[[str], tuple[set[str], set[str]]] = _analyzer_pipeline_paths,
) -> set[str] | None:
    if not path.startswith(("tests/analyze/", "tests/clippy_", "quality/fixtures/")):
        return None
    file = ROOT / path
    if not file.is_file() or file.resolve() != file:
        return None
    if path.startswith("tests/clippy_"):
        return (clippy_gates or clippy_fixture_gates)(path)
    if path in {"quality/fixtures/c_static_analysis/good.c", "quality/fixtures/c_static_analysis/bad_use_after_free.c"}:
        return {"c-static-analysis"}
    if re.fullmatch(r"quality/fixtures/memory/(?:tiny|medium|import_heavy/(?:root|mid_left|mid_right|[a-h]))\.ouro", path):
        return {"memory-budget"}
    if path.startswith("quality/fixtures/structural_lex/"):
        from structural_lex_parity import load_cases

        corpus = ROOT / "quality/fixtures/structural_lex"
        manifest = corpus / "manifest.json"
        try:
            if manifest.resolve() != manifest:
                return None
            cases = load_cases(corpus)
        except (KeyError, OSError, TypeError, ValueError):
            return None
        if file != manifest and not any(file == corpus / case["file"] for case in cases):
            return None
        gates = {"structural-quality-suite", "structural-quality"}
        if file == manifest or file.suffix in {".sh", ".py"}:
            gates.add("host-bound-inventory")
        return gates
    if not path.startswith("tests/analyze/"):
        return None
    relative = path.removeprefix("tests/analyze/")
    gates = {"analyze-precision"}
    if relative == "api_surface.tsv":
        return gates
    scope, _, name = relative.partition("/")
    manifest = ROOT / "tests/analyze/manifest.json"
    suite = ROOT / "scripts/analyze_precision_suite.sh"
    try:
        if manifest.resolve() != manifest or suite.resolve() != suite:
            return None
        commands = suite.read_text(encoding="utf-8")
        scopes, goldens = pipeline_paths(manifest.read_text(encoding="utf-8"))
    except (KeyError, OSError, TypeError, ValueError):
        return None
    if relative == "manifest.json":
        return gates
    if name != file.name:
        return None
    if scope == "precision":
        if name == "assertions.ouro" or file.suffix != ".ouro":
            # Other native suites import the shared assertions.
            return None
        cases = re.findall(r"^for precision_core in ([a-z_ ]+); do$", commands, re.MULTILINE)
        return gates if len(cases) == 1 and file.stem in cases[0].split() else None
    if scope == "golden":
        compared = re.findall(r"^golden_(?:ok|codes) ([a-z0-9_]+) ", commands, re.MULTILINE)
        return gates if relative in goldens and file.suffix == ".txt" and file.stem in compared else None
    if scope not in scopes | {"deadcode_good_patterns", "facts_good", "style_bad", "style_good"}:
        return None
    if file.suffix != ".ouro" or (
        f'--scope "$FIX/{scope}"' not in commands and relative != "format_bad/crlf.ouro"
    ):
        return None
    if scope in {"architecture_good", "deadcode_good"}:
        gates.add("memory-budget")
    if scope == "architecture_bad":
        gates.add("language-speed-simplicity")
    return gates


def _clippy_case_paths(text: str) -> set[str]:
    return {row["path"] for row in json.loads(text)["cases"]}


def clippy_fixture_gates(path: str, *, parse_imports: ImportBytesParser | None = None,
                         case_paths: Callable[[str], set[str]] = _clippy_case_paths) -> set[str] | None:
    from selfhost_module_cache import collect_units

    corpus = "tests/clippy_semantic/"
    if path in {"tests/clippy_grade_invariants.ouro", "tests/clippy_structural_facts.ouro"}:
        return {"lint-clippy"}
    if not path.startswith(corpus):
        return None
    relative = path.removeprefix(corpus)
    if relative == "session_protocol.py":
        return {"lint-fixtures", "host-bound-inventory", "structural-quality"}
    if relative == "cases.json":
        return {"lint-clippy", "structural-quality"}
    if not relative.endswith(".ouro"):
        return None

    parse_imports = parse_imports or cached_import_parser()

    @cache
    def local_imports(unit: str) -> list[str]:
        source = ROOT / unit
        if not valid_changed_path(unit) or source.resolve() != source:
            raise ValueError(f"unsafe Clippy fixture: {unit}")
        if not source.is_file():
            # A runtime fixture checks an absent transitive import.
            return []
        return [dep for dep in parse_imports(source.read_bytes(), unit)
                if dep.startswith(corpus)]

    try:
        if relative.startswith(("fixtures/", "quality_expansion/")):
            manifest = ROOT / corpus / "cases.json"
            if manifest.resolve() != manifest:
                return None
            cases = case_paths(manifest.read_text(encoding="utf-8"))
            if path in cases:
                return {"lint-clippy"}
            if relative != "fixtures/private-forward.ouro":
                return None
            entries = ("fixtures/private-public-counterpart.ouro", "fixtures/private-reexport.ouro")
            return {"lint-clippy"} if any(path in local_imports(corpus + name) for name in entries
                                          if corpus + name in cases) else None
        if relative.startswith("alias_scope/"):
            entries = ("qualified", "selected", "selected-hidden", "missing-member", "transitive", "unknown-alias")
            suites = {"lint-clippy": ["alias_scope/" + name for name in entries]}
        elif relative.startswith("runtime_imports/"):
            suites = {"lint-clippy": ["runtime_imports/runtime/" + name for name in ("valid", "unresolved", "missing")]}
        elif "/" not in relative:
            suites = {"lint-clippy": ["proofs", "contracts", "resources", "lifetime", "precision", "process_status"],
                      "lint-fixtures": ["performance", "session", "session_wire"]}
        else:
            return None
        return {gate for gate, names in suites.items()
                if any(path in collect_units(corpus + name + ".ouro", imports=local_imports) for name in names)} or None
    except (KeyError, OSError, RuntimeError, SystemExit, TypeError, ValueError):
        return None


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
    if not selection.paths:
        # Without changed paths, the production shards cover sources that lint-changed cannot identify.
        return replace(selection, gates=(*selection.gates, *PR_FALLBACK_LINT_GROUPS))
    if not selection.core:
        return selection
    affected: set[str] = set()
    if selection.host_compiler and any(f"compiler-checking-{shard}" not in selection.gates for shard in range(1, COMPILER_SHARDS + 1)):
        try:
            affected = affected_compiler_gates(selection.paths)
        except (OSError, ValueError, SystemExit, RecursionError) as exc:
            affected.update(set(selection.gates).intersection(PR_LINT_PHASES))
            selection = replace(full_path_selection(f"compiler dependency inventory unavailable: {exc}"), paths=selection.paths)
    lint_sources = ()
    if any(path.endswith(".ouro") for path in selection.paths):
        try:
            lint_sources = tuple(lint_changed_sources(selection.paths))
        except (OSError, ValueError) as exc:
            raise ValueError(f"cannot determine required changed-source lint: {exc}") from exc
    names = set(selection.gates) | affected | (set(PATH_INPUT_GATES) if lint_sources else set())
    return replace(selection, gates=tuple(name for group in ROUTED_PR_GROUPS.values() for name in group if name in names),
                   lint_sources=lint_sources)


def selection_matrix(
    selection: PathSelection, *, groups: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, list[dict[str, str]]]:
    selected = set(selection.gates)
    if selection.portable and (not selection.core or not {"python-syntax", "kernel-hardening"} <= selected):
        raise ValueError("portable validation requires the Linux syntax and kernel-hardening gates")
    if groups is None:
        groups = PULL_REQUEST_GROUPS
    priority = {"checks": 0, "tests": 0, "smith": 0, **dict.fromkeys(PR_ISOLATED_TEST_GATES, 0),
                "checks-parity": 1, "checks-quality": 1,
                f"compiler-{COMPILER_SHARDS}": 2}
    ordered = sorted(groups, key=lambda name: priority.get(name, 3 if name.startswith("compiler-") else 4))
    return {"include": [{"group": group} for group in ordered if selected.intersection(groups[group])]}


def selection_from_json(value: str, *, full: bool = False) -> PathSelection:
    paths = json.loads(value)
    if not isinstance(paths, list) or any(not isinstance(path, str) or not path for path in paths):
        raise ValueError("changed paths must be a JSON array of nonempty strings")
    if full:
        if paths:
            raise ValueError("a forced complete profile has no changed-path filter")
        return full_path_selection("complete validation requested")
    return plan_paths(paths)


def selection_key(selection: PathSelection) -> str:
    return hash_json({name: getattr(selection, name) for name in (
        "mode", "core", "docs", "kernel", "editor", "site", "portable", "paths", "gates", "lint_sources",
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
    if any("\\" in path or not valid_changed_path(path) for path in values):
        return None, "Git returned a noncanonical repository path"
    return values, ""


def bool_text(value: bool) -> str:
    return "true" if value else "false"


def write_github_output(path: Path, selection: PathSelection, matrix: dict[str, list[dict[str, str]]]) -> None:
    with path.open("a", encoding="utf-8") as output:
        for name in ("core", "docs", "kernel", "editor", "site", "host_compiler", "dependency", "portable"):
            output.write(f"{name}={bool_text(getattr(selection, name))}\n")
        for gate in ("python-lint", "shell-lint"):
            output.write(f"{gate.replace('-', '_')}={bool_text(gate in selection.gates)}\n")
        output.write(f"mode={selection.mode}\n")
        output.write("matrix=" + json.dumps(matrix, separators=(",", ":")) + "\n")
        output.write("changed_paths=" + json.dumps(selection.paths, separators=(",", ":")) + "\n")
        output.write(f"selection_key={selection_key(selection)}\n")


def run_path_selection(base: str, head: str, github_output: str, *, full: bool = False) -> int:
    paths, reason = (None, "complete validation requested") if full else changed_paths(base, head)
    # Set a conservative limit for GitHub's UTF-16 job output.
    # A larger path list selects the full plan to preserve coverage.
    if paths is not None and len(json.dumps(paths)) > PATH_OUTPUT_BUDGET:
        paths, reason = None, "changed path output would exceed the routing budget"
    groups = ROUTED_PR_GROUPS if full else PULL_REQUEST_GROUPS
    try:
        if full:
            selection = full_path_selection(reason)
        elif paths is None:
            selection = replace(plan_paths([]), reason=reason)
        else:
            selection = plan_paths(paths)
        matrix = selection_matrix(selection, groups=groups)
    except ValueError as exc:
        print(f"CI_PATHS: FAIL {exc}", file=sys.stderr)
        return 1
    hosted = [row["group"] for row in matrix["include"] if row["group"] != "lint"]
    hosted_gates = set(selection.gates) - {"lint"}
    details = (
        f"mode={selection.mode} core={bool_text(selection.core)} docs={bool_text(selection.docs)} "
        f"kernel={bool_text(selection.kernel)} editor={bool_text(selection.editor)} "
        f"site={bool_text(selection.site)} host_compiler={bool_text(selection.host_compiler)} paths={len(selection.paths)} "
        f"gates={len(hosted_gates)} groups={len(hosted)}"
    )
    if selection.reason:
        details += f" reason={selection.reason}"
    print(f"CI_PATHS {details}")
    if github_output:
        try:
            write_github_output(Path(github_output), selection, matrix)
        except OSError as exc:
            print(f"CI_PATHS: FAIL cannot write GitHub output: {exc}", file=sys.stderr)
            return 1
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as output:
            output.write("### CI selection\n\n")
            output.write(f"Selected {len(hosted_gates)} gates in {len(hosted)} hosted PR matrix groups.\n\n")
            for group in hosted:
                names = [name for name in groups[group] if name in hosted_gates]
                output.write(f"- **{group}**: {', '.join(names)}\n")
            output.write(f"\nDocs: {bool_text(selection.docs)}; portable: {bool_text(selection.portable)}; "
                         f"kernel extra: {bool_text(selection.kernel)}; editor: {bool_text(selection.editor)}; "
                         f"site: {bool_text(selection.site)}.\n")
    return 0


def run_dependency_selection(base: str, head: str, pr_head: str, github_output: str) -> int:
    """Scan the tested merge. The dependency action compares against the PR head."""
    diffs: dict[str, list[str]] = {}
    workflow = manifests = True
    for revision in dict.fromkeys((head, pr_head)):
        paths, reason = changed_paths(base, revision)
        oversized = paths is not None and len(json.dumps(paths)) > PATH_OUTPUT_BUDGET
        if not paths or oversized:
            if revision == head and oversized:
                workflow = False
            print("CI_DEPENDENCIES: complete review: " + (reason or "empty or oversized diff"))
            break
        normalized = [normalize_changed_path(path) for path in paths]
        if not all(valid_changed_path(path) for path in normalized):
            print("CI_DEPENDENCIES: complete review: invalid changed path")
            break
        diffs[revision] = normalized
    else:
        merged_paths = diffs[head]
        workflow = (workflow_scan_required(merged_paths)
                    and "github-workflow-gate" not in classify_paths(merged_paths).gates)
        manifests = any(not DEPENDENCY_PATHS.isdisjoint(paths) for paths in diffs.values())

    records = f"dependency={bool_text(workflow)}\ndependency_manifests={bool_text(manifests)}\n"
    print(records, end="")
    if github_output:
        try:
            with Path(github_output).open("a", encoding="utf-8") as output:
                output.write(records)
        except OSError as exc:
            print(f"CI_DEPENDENCIES: FAIL cannot write GitHub output: {exc}", file=sys.stderr)
            return 1
    return 0


def dependency_selection_contract_failures() -> list[str]:
    import contextlib
    import io
    import tempfile
    from unittest.mock import patch

    base, merged, source = (letter * 40 for letter in "abc")
    site = ["site/src/app.ts"]
    manifest = ["editors/vscode/package-lock.json"]
    cases = (
        ("site", site, site, False, False),
        ("unrelated script", ["scripts/kernel_scale.py"], site, False, False),
        ("merged workflow", [".github/workflows/ouro-pr.yml"], site, False, False),
        ("head-only workflow", site, [".github/workflows/ouro-pr.yml"], False, False),
        ("wrapper", ["scripts/github_workflow_gate.py"], site, False, False),
        ("build input", ["scripts/repo_support.py"], site, False, False),
        ("imported tool module", ["tools/fix/lex.ouro"], site, False, False),
        ("head-only manifest", site, manifest, False, True),
        ("merged manifest rename", [*manifest, "site/removed.json"], site, False, True),
        ("missing merge", None, site, True, True),
        ("missing head", site, None, True, True),
        ("empty", site, [], True, True),
        ("oversized merge", ["x" * PATH_OUTPUT_BUDGET], site, False, True),
        ("oversized head", site, ["x" * PATH_OUTPUT_BUDGET], True, True),
        ("invalid", site, ["../wrong"], True, True),
    )
    failures = []
    with tempfile.TemporaryDirectory() as temp:
        output = Path(temp) / "selection"
        for name, merged_paths, source_paths, workflow, manifests in cases:
            output.write_text("", encoding="utf-8")
            diffs = [(merged_paths, ""), (source_paths, "")]
            with patch(__name__ + ".changed_paths", side_effect=diffs) as diff, contextlib.redirect_stdout(io.StringIO()):
                status = run_dependency_selection(base, merged, source, str(output))
            expected = f"dependency={bool_text(workflow)}\ndependency_manifests={bool_text(manifests)}\n"
            comparisons = [call.args for call in diff.call_args_list]
            expected_refs = [(base, merged), (base, source)][:len(comparisons)]
            if status or output.read_text(encoding="utf-8") != expected or comparisons != expected_refs:
                failures.append("dependency review route mismatch: " + name)
    with patch("frontend_regen.collect_units_many", side_effect=ValueError("incomplete import closure")) as collect:
        if workflow_scan_required(site) or not workflow_scan_required(["std/json.ouro"]) or collect.call_count != 1:
            failures.append("unavailable workflow tool closure lost coverage or slowed a site-only change")
    with (patch(__name__ + ".changed_paths", return_value=(site, "")),
          patch(__name__ + ".workflow_scan_required", return_value=True),
          contextlib.redirect_stdout(io.StringIO()) as output):
        if run_dependency_selection(base, merged, source, "") or "dependency=true\n" not in output.getvalue():
            failures.append("Dependencies skipped a policy scan the main CI did not route")
    with patch(__name__ + ".changed_paths", return_value=(site, "")) as diff, contextlib.redirect_stdout(io.StringIO()):
        if run_dependency_selection(base, merged, merged, "") or diff.call_count != 1:
            failures.append("identical dependency review revisions did not share one diff")
    return failures


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


def export_compiler(root: Path, binary: Path, selected: dict, archive: Path, *, historical_key: str = "") -> str:
    import bootstrap_compiler as bootstrap

    receipt = binary.with_name("ouro1.bootstrap.json")
    receipt_data = receipt.read_bytes() if receipt.is_file() else b""
    if not bootstrap.installed_current(binary, receipt, selected) or receipt.read_bytes() != receipt_data:
        raise ValueError("compiler or bootstrap evidence does not match current inputs")
    checked = json.loads(receipt_data)
    paths = compiler_evidence_paths(root, binary, checked)
    report = (Path(checked["work"]) / "report.json").read_bytes()
    if sha256_bytes(report) != checked["report_sha256"]:
        raise ValueError("bootstrap report changed after compiler verification")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz", compresslevel=6) as bundle:
        for path in paths:
            bundle.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)
    history = json.loads(report).get("historical_cache")
    if historical_key and isinstance(history, dict) and history.get("key") == historical_key:
        digest = history.get("sha256")
        if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
            return digest
    return ""


_COMPILER_ARCHIVE_SPOOL_LIMIT = 16 * 1024 * 1024
_COMPILER_RECEIPT_CAPTURE_LIMIT = 1024 * 1024


def import_compiler(root: Path, binary: Path, selected: dict, archive: Path, expected_sha256: str) -> None:
    import bootstrap_compiler as bootstrap
    from bootstrap_historical import copy_hash

    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("compiler artifact SHA-256 differs from this workflow's producer output")
    with ExitStack() as stack:
        verified = stack.enter_context(tempfile.SpooledTemporaryFile(max_size=_COMPILER_ARCHIVE_SPOOL_LIMIT))
        with archive.open("rb") as source:
            archive_sha256 = copy_hash(source, verified)
        if archive_sha256 != expected_sha256:
            raise ValueError("compiler artifact SHA-256 differs from this workflow's producer output")
        verified.seek(0)
        bundle = stack.enter_context(tarfile.open(fileobj=verified, mode="r:gz"))
        try:
            receipt_name = binary.with_name("ouro1.bootstrap.json").relative_to(root).as_posix()
        except ValueError:
            bundle.getmembers()
            raise
        receipt_data = None
        try:
            for member in bundle:
                if member.name != receipt_name:
                    continue
                receipt_data = None
                if member.isfile() and not member.issparse() and 0 <= member.size <= _COMPILER_RECEIPT_CAPTURE_LIMIT:
                    with bundle.extractfile(member) as stream:
                        receipt_data = stream.read()
        except (OSError, EOFError, tarfile.TarError, zlib.error):
            # Preserve the original error order when receipt capture fails.
            bundle.close()
            verified.seek(0)
            bundle = stack.enter_context(tarfile.open(fileobj=verified, mode="r:gz"))
            receipt_data = None
        members = bundle.getmembers()
        receipt_member = bundle.getmember(receipt_name)
        if not receipt_member.isfile():
            raise ValueError("compiler receipt is not a regular file")
        if receipt_data is None:
            with bundle.extractfile(receipt_member) as stream:
                data = json.load(stream)
        else:
            data = json.loads(receipt_data)
        paths = compiler_evidence_paths(root, binary, data)
        expected = {path.relative_to(root).as_posix() for path in paths}
        if len(members) != len(expected) or {member.name for member in members} != expected or any(not member.isfile() for member in members):
            raise ValueError("compiler artifact has missing, duplicate or unexpected files")
        # Do not let tar interpret paths, links, ownership or special file modes.
        for member in members:
            target = root / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if member is receipt_member and receipt_data is not None:
                target.write_bytes(receipt_data)
            else:
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
        if action in {"key", "export"}:
            _requested, workers, _budget, _note = bootstrap.bootstrap_worker_plan(cfg.values, build)
            historical_key = bootstrap.historical_key(selected, workers)
            if action == "key":
                print("key=" + hash_json(selected))
                print("historical_key=" + historical_key)
            else:
                historical_sha256 = export_compiler(ROOT, binary, selected, archive, historical_key=historical_key)
                print("sha256=" + sha256_file(archive))
                print("historical_sha256=" + historical_sha256)
        else:
            import_compiler(ROOT, binary, selected, archive, expected_sha256)
            print("CI_COMPILER: PASS current source, host compiler, binary and bootstrap evidence")
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, tarfile.TarError) as exc:
        print(f"CI_COMPILER: FAIL {exc}", file=sys.stderr)
        return 1
    return 0


HOST_SUITE_GATES = {
    "scripts/analyze_core_checks.py": ("analyze-precision", "smith-selftest"),
    "scripts/analyze_precision_suite.sh": ("analyze-precision",),
    "scripts/bootstrap_compiler_test.py": ("build-cache-config",),
    "scripts/bootstrap_inputs_test.py": ("build-cache-config",),
    "scripts/build_cache_config_suite.py": (
        "build-cache-config", "stage-loop-c-object-cache", "stage-loop-frontend-regeneration", "smith-selftest",
    ),
    "scripts/c_static_analysis_suite.py": ("c-static-analysis", "smith-selftest"),
    "scripts/ci_historical_cache.py": ("build-cache-config",),
    "scripts/ci_historical_cache_test.py": ("build-cache-config",),
    "scripts/clippy_grade_firewall.py": ("lint-clippy", "fix"),
    "scripts/clippy_grade_suite.py": ("lint-clippy",),
    "scripts/compiler_shards_test.py": ("ci-runner-selftest",),
    "scripts/doc_suite.sh": ("doc",),
    "scripts/fix_check_suite.py": ("fix",),
    "scripts/fix_suite.sh": ("fix",),
    "scripts/fmt_suite.sh": ("fmt", "memory-budget"),
    "scripts/frontend_host_suite.py": ("frontend-security", "build-cache-config"),
    "scripts/frontend_lower_lookup_test.py": ("build-cache-config", "stage-loop-frontend-regeneration"),
    "scripts/frontend_native_async.py": ("frontend-security", "build-cache-config"),
    "scripts/frontend_native_fs_create.py": ("frontend-security", "build-cache-config"),
    "scripts/fs_read_suite.py": ("runtime-io", "analyze-precision", "frontend-security", "build-cache-config"),
    "scripts/fs_replace_suite.py": (
        "fmt", "fix", "runtime-io", "analyze-precision", "frontend-security", "build-cache-config", "memory-budget",
    ),
    "scripts/generated_c_shard_cache_suite.py": ("generated-c-shard-cache",),
    "scripts/hygiene.sh": ("hygiene",),
    "scripts/language_speed_simplicity_suite.py": ("language-speed-simplicity",),
    "scripts/lsp_suite.sh": ("lsp", "build-cache-config"),
    "scripts/memory_budget_suite.py": ("build-cache-config", "memory-budget"),
    "scripts/pkg_suite.sh": ("pkg", "build-cache-config"),
    "scripts/runtime_io_suite.sh": ("runtime-io", "build-cache-config"),
    "scripts/samples_suite.sh": ("samples-1", "samples-2", "build-cache-config"),
    "scripts/scoped_host_exports_test.py": ("build-cache-config", "stage-loop-frontend-regeneration"),
    "scripts/selfhost_module_cache_suite.py": ("selfhost-module-cache",),
    "scripts/stage_loop_frontend_regen_suite.py": ("stage-loop-frontend-regeneration",),
    "scripts/stage_loop_generated_c_object_cache_suite.py": ("stage-loop-c-object-cache",),
    "scripts/structural_quality_suite.py": ("structural-quality-suite",),
    "scripts/test_selfhost_bootstrap_evidence.py": ("build-cache-config",),
}


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
        Gate("test", ["sh", "scripts/test_suite.sh", "--require-cc"], ("pr", "nightly", "manual"), env=(("TEST_SUITE_OUT", "_build/test_suite"),)),
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
    names = ["lint-fixtures", *(f"lint-production-{index}" for index in range(1, 5)), "lint-clippy"]
    matrix = re.findall(r"^          - group: ([a-z0-9-]+)$", content, re.MULTILINE)
    if matrix != names:
        failures.append("standalone Lint must schedule every required lint group once in order")
    for required in (
        "    timeout-minutes: 120\n", "      fail-fast: false\n",
        "run: python3 scripts/ouro_build.py build --verbosity quiet",
        'run: python3 scripts/ci_gate.py --profile manual --group "${{ matrix.group }}" --out "_build/ci/${{ matrix.group }}"',
        "name: lint-${{ matrix.group }}",
    ):
        if required not in content:
            failures.append("standalone Lint lost required command or isolation: " + required.strip())
    return failures


def workflow_job(content: str, name: str) -> str:
    section = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  [a-z0-9-]+:|\Z)", content, re.MULTILINE | re.DOTALL)
    return section[1] if section else ""


def pr_matrix_contract_failures(section: str) -> list[str]:
    failures = []
    matrix = re.search(r"^      matrix:\n((?:^        [^\n]*\n)+)", section, re.MULTILINE)
    if matrix is None or matrix[1] != (
        "        group: ${{ fromJSON(needs.paths.outputs.matrix).include.*.group }}\n"
        "        exclude:\n"
        "          - group: lint\n"
    ):
        failures.append("Linux PR matrix must consume every routed group except the standalone lint group")
    run_checks = re.findall(r"^      - name: Run checks\n(.*?)(?=^      - |\Z)", section, re.MULTILINE | re.DOTALL)
    if [step.rstrip() for step in run_checks] != [(
        "        env:\n"
        "          CHANGED_PATHS: ${{ needs.paths.outputs.changed_paths }}\n"
        "          SELECTION_KEY: ${{ needs.paths.outputs.selection_key }}\n"
        "          CI_GROUP: ${{ matrix.group }}\n"
        "        run: |\n"
        "          selection_options=()\n"
        '          if [ "$GITHUB_EVENT_NAME" != pull_request ]; then\n'
        "            selection_options=(--full)\n"
        "          fi\n"
        '          python3 scripts/ci_gate.py --profile pr --group "$CI_GROUP" --changed-paths-json "$CHANGED_PATHS"'
        ' --selection-key "$SELECTION_KEY" "${selection_options[@]}" --fail-fast --out "_build/ci/pr-$CI_GROUP"'
    )]:
        failures.append("Every Linux PR matrix job must recompute its route and run its blocking gates")
    return failures


def site_workflow_contract_failures(content: str, job: str) -> list[str]:
    section = workflow_job(content, job)
    before_jobs = content.split("\njobs:\n", 1)[0]
    steps = re.findall(r"^      - name: Check and build site\n(.*?)(?=^      - |\Z)",
                       section, re.MULTILINE | re.DOTALL)
    if ([step.rstrip() for step in steps] != ["        run: npm --prefix site run build:ci"]
            or re.search(r"^ {4,8}working-directory:", before_jobs, re.MULTILINE)
            or re.search(r"^        working-directory:", section.split("\n    steps:\n", 1)[0], re.MULTILINE)):
        return [f"{job} must run the shared Site entry point from the checkout root"]
    return []


def dependency_workflow_contract_failures(content: str) -> list[str]:
    failures = []
    events = re.search(r"^on:\n((?:^ +[^\n]*\n)+)", content, re.MULTILINE)
    if not events or not re.search(r"^  merge_group:\n    types: \[ checks_requested \]\n", events[1], re.MULTILINE):
        failures.append("Dependencies must run on merge queue check requests")
    review = workflow_job(content, "dependency-review")
    selector = re.search(r"^      - name: Select checks\n(.*?)(?=^      - |\Z)", review, re.MULTILINE | re.DOTALL)
    if ("    name: Review\n" not in review or re.search(r"^    if:", review, re.MULTILINE)
            or not selector or re.search(r"^        if:", selector[1], re.MULTILINE)
            or any(required not in selector[1] for required in (
                "          BASE_SHA: ${{ github.event.pull_request.base.sha || github.event.merge_group.base_sha }}\n",
                "          HEAD_SHA: ${{ github.sha }}\n",
                "          PR_HEAD_SHA: ${{ github.event.pull_request.head.sha || github.event.merge_group.head_sha }}\n",
                '        run: python3 scripts/ci_gate.py --select-dependencies '
                '--base "$BASE_SHA" --head "$HEAD_SHA" --pr-head "$PR_HEAD_SHA"\n',
            ))):
        failures.append("Dependencies Review must select checks from the PR or merge group SHAs")
    return failures


def nightly_workflow_contract_failures(content: str) -> list[str]:
    producer = workflow_job(content, "host-compiler")
    validation = workflow_job(content, "validation")
    full = workflow_job(content, "full-validation")
    failures = []
    if any(required not in producer for required in (
        "run: python3 scripts/ouro_build.py build --verbosity quiet\n",
        'python3 scripts/ci_gate.py --compiler-artifact export >> "$GITHUB_OUTPUT"\n',
        "name: ${{ steps.bundle.outputs.artifact }}\n",
        "path: _build/ci/host-compiler.tar.gz\n",
        "if-no-files-found: error\n",
    )):
        failures.append("Nightly must build, verify, and upload its host compiler")
    if ("    needs: host-compiler\n" not in validation
            or "name: ${{ needs.host-compiler.outputs.artifact }}\n" not in validation
            or "scripts/ouro_build.py build" in validation
            or "      - name: Verify and install host compiler\n"
               "        env:\n"
               "          COMPILER_SHA256: ${{ needs.host-compiler.outputs.sha256 }}\n"
               '        run: python3 scripts/ci_gate.py --compiler-artifact import --compiler-sha256 "$COMPILER_SHA256"\n\n'
               "      - name: Run checks\n" not in validation):
        failures.append("Nightly validation must verify the shared compiler before running gates")
    if any(required not in full for required in (
        "    needs: [host-compiler, validation]\n",
        "    if: always()\n",
        "COMPILER_RESULT: ${{ needs.host-compiler.result }}\n",
        "VALIDATION_RESULT: ${{ needs.validation.result }}\n",
        'run: test "$COMPILER_RESULT" = success && test "$VALIDATION_RESULT" = success\n',
    )) or "continue-on-error:" in producer + validation + full:
        failures.append("Nightly Full must require the compiler producer and every validation group")
    return failures


def manual_workflow_contract_failures(content: str) -> list[str]:
    failures: list[str] = []
    events = re.search(r"^on:\n((?:  [^\n]*\n|\n)*)", content, re.MULTILINE)
    if not events or re.findall(r"^  (\S.*)$", events[1], re.MULTILINE) != ["workflow_dispatch:"]:
        failures.append("Manual control-plane routing requires a dispatch-only workflow")
    required = {
        "groups": (
            "PROFILE: ${{ inputs.profile }}",
            "TASK: ${{ inputs.task }}",
            """matrix='["frontend-security"]'""",
            'matrix=$(python3 scripts/ci_gate.py --profile "$PROFILE" --list-groups)',
            'echo "matrix=$matrix" >> "$GITHUB_OUTPUT"',
        ),
        "manual-validation": (
            "needs: [groups, host-compiler]",
            "if: ${{ always() && needs.groups.result == 'success' && (inputs.disable_cache || needs.host-compiler.result == 'success') }}",
            "group: ${{ fromJSON(needs.groups.outputs.matrix) }}",
            "os: [ubuntu-latest, windows-latest]",
            'run: python scripts/ci_gate.py --compiler-artifact import --compiler-sha256 "$COMPILER_SHA256"',
            "run: python scripts/ouro_build.py build --verbosity quiet",
            "if: ${{ inputs.task == 'validate' || inputs.task == '' }}",
            'run: python scripts/ci_gate.py --profile "${{ inputs.profile }}" --group "${{ matrix.group }}" --out "_build/ci/${{ inputs.profile }}-${{ matrix.group }}"',
            "if: ${{ inputs.task == 'frontend-security' && matrix.group == 'frontend-security' }}",
            "run: sh scripts/frontend_security_suite.sh",
        ),
    }
    for name, commands in required.items():
        job = workflow_job(content, name)
        lines = {line.strip() for line in job.splitlines()}
        soft_failure = any(line.startswith("continue-on-error:") and line != "continue-on-error: false" for line in lines)
        if not set(commands) <= lines or soft_failure or re.search(r"^        exclude:", job, re.MULTILINE):
            failures.append("Manual lost required profile dispatch or failure propagation in " + name)
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
        ):
            if not lint_workflow_contract_failures(content.replace(before, after, 1)):
                failures.append("standalone Lint scheduling regression was accepted: " + before)
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


def run_self_tests(all_gates: Sequence[Gate]) -> int:
    failures: list[str] = []
    failures.extend(summary_contract_failures())
    failures.extend(scheduler_contract_failures())
    for gate in ("compiler-scale", *sorted(LOCAL_SERIAL_BUILD_GATES)):
        failures.extend(serial_gate_reservation_contract_failures(gate))
    failures.extend(preparation_contract_failures())
    failures.extend(routing_contract_failures())
    failures.extend(pr_test_group_contract_failures(all_gates))
    failures.extend(area_selection_contract_failures())
    failures.extend(dependency_selection_contract_failures())
    failures.extend(sample_listing_contract_failures())
    failures.extend(provenance_contract_failures())
    failures.extend(lint_phase_selftest_failures(all_gates))
    failures.extend(lint_execution_contract_failures(all_gates))
    failures.extend(lint_worker_contract_failures(all_gates))
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
        # Reject invalid inventories before a shard can omit required coverage.
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
            section = workflow_job(content, job)
            matrix = re.findall(r"^          - group: ([a-z0-9-]+)$", section, re.MULTILINE)
        except OSError as exc:
            failures.append(f"cannot read {profile} workflow: {exc}")
        else:
            if profile == "pr":
                failures.extend(pr_matrix_contract_failures(section))
                if "    runs-on: ubuntu-latest\n" not in section:
                    failures.append("PR matrix must run on Linux")
                for original, replacement in (
                    ("          - group: lint\n", "          - group: lint\n          - group: analyzer-lint\n"),
                    ("      - name: Run checks\n", "      - name: Run checks\n        if: ${{ false }}\n"),
                    ("          selection_options=()\n", "          exit 0\n          selection_options=()\n"),
                    ("          SELECTION_KEY: ${{ needs.paths.outputs.selection_key }}\n",
                     "          SELECTION_KEY: ${{ needs.paths.outputs.matrix }}\n"),
                ):
                    if not pr_matrix_contract_failures(section.replace(original, replacement, 1)):
                        failures.append("PR matrix regression was accepted: " + original.strip())
                selection = plan_paths(["compiler/lexer.ouro"])
                planned = [row["group"] for row in selection_matrix(selection)["include"]]
                expected_groups = {*groups, "runtime-io", "frontend-security"}
                if len(planned) != len(expected_groups) or set(planned) != expected_groups:
                    failures.append("full PR routing omits or duplicates a group")
                covered = [name for group in planned for name in PULL_REQUEST_GROUPS[group] if name in selection.gates]
                if sorted(covered) != sorted(selection.gates):
                    failures.append("full PR routing omits or duplicates a gate")
                if planned[:7] != ["checks", "tests", "smith", "runtime-io", "frontend-security",
                                    "checks-parity", "checks-quality"]:
                    failures.append("long PR groups must start before compiler shards")
                if planned[7:8] != [f"compiler-{COMPILER_SHARDS}"]:
                    failures.append("isolated source-spans shard must start before other compiler shards")
                for group, gate_name in (("checks", "python-syntax"), ("checker", "kernel-hardening")):
                    if not any(gate.name == gate_name and gate.blocking for gate in select_group(all_gates, "pr", group)):
                        failures.append("Linux portable validation lost its blocking " + gate_name + " gate in " + group)
                if ("        if: ${{ matrix.group == 'checker' && needs.paths.outputs.portable == 'true' }}\n"
                    "        run: python3 scripts/ouro_build.py build --verbosity quiet\n") not in section:
                    failures.append("Linux portable validation lost its compiler build in the checker group")
                aggregate = workflow_job(content, "native-kernel-regressions")
                for field in ("PR_RESULT: ${{ needs.quick-firewall.result }}", 'require_result "$CORE_REQUIRED" "$PR_RESULT"',
                              "PORTABLE_RESULT: ${{ needs.portable-kernel-smoke.result }}", 'require_result "$PORTABLE_REQUIRED" "$PORTABLE_RESULT"',
                              "COMPILER_RESULT: ${{ needs.host-compiler.result }}", 'require_result "$COMPILER_REQUIRED" "$COMPILER_RESULT"',
                              "SITE_RESULT: ${{ needs.site.result }}", 'require_result "$SITE_REQUIRED" "$SITE_RESULT"',
                              'require_result "$EDITOR_REQUIRED" "$EDITOR_RESULT"', 'require_result "$KERNEL_REQUIRED" "$VALIDATION_RESULT"',
                              'require_result "$DOCS_CHANGED" "$DOCS_RESULT"'):
                    if field not in aggregate:
                        failures.append("Kernel lost a required validation result: " + field)
            else:
                if matrix != list(groups):
                    failures.append(f"hosted {profile} matrix differs from automatic group inventory: {matrix}")
                failures.extend(nightly_workflow_contract_failures(content))
                for before, after in (
                    ("--compiler-artifact export", "--compiler-artifact key"),
                    ("--compiler-artifact import", "--compiler-artifact key"),
                    ("      - name: Verify and install host compiler\n",
                     "      - name: Verify and install host compiler\n        if: ${{ false }}\n"),
                    ("needs: [host-compiler, validation]", "needs: validation"),
                    ('test "$COMPILER_RESULT" = success && ', ""),
                    ("    needs: host-compiler\n", "    needs: host-compiler\n    continue-on-error: true\n"),
                ):
                    if not nightly_workflow_contract_failures(content.replace(before, after, 1)):
                        failures.append("Nightly compiler or aggregate regression was accepted: " + before)
    manual_workflow = (ROOT / ".github/workflows/ouro-manual-trust.yml").read_text(encoding="utf-8")
    failures.extend(manual_workflow_contract_failures(manual_workflow))
    for before, after in (
        ("on:\n", "on:\n  pull_request:\n"),
        ('--profile "$PROFILE" --list-groups', '--profile pr --list-groups'),
        ("needs.host-compiler.result == 'success'", "true"),
        ("fromJSON(needs.groups.outputs.matrix)", "inputs.profile"),
        ("        group: ${{ fromJSON", "        exclude:\n          - group: trust\n        group: ${{ fromJSON"),
        ("--compiler-sha256", "--skip-compiler-check"),
        ("    needs: [groups, host-compiler]", "    continue-on-error: true\n    needs: [groups, host-compiler]"),
    ):
        if not manual_workflow_contract_failures(manual_workflow.replace(before, after, 1)):
            failures.append("Manual profile routing regression was accepted: " + before)
    lint_workflow = (ROOT / ".github/workflows/ouro-lint.yml").read_text(encoding="utf-8")
    triggers = re.search(r"^on:\n(.*?)(?=^\S|\Z)", lint_workflow, re.MULTILINE | re.DOTALL)
    if not triggers or triggers.group(1).strip() != "workflow_dispatch:":
        failures.append("standalone lint workflow must only run manually")
    failures.extend(lint_workflow_contract_failures(lint_workflow))
    for workflow, job in (("ouro-pr.yml", "site"), ("ouro-pages.yml", "build-site")):
        site_workflow = (ROOT / ".github/workflows" / workflow).read_text(encoding="utf-8")
        failures.extend(site_workflow_contract_failures(site_workflow, job))
        for before, after in (
            ("      - name: Check and build site\n",
             "      - name: Check and build site\n        if: ${{ false }}\n"),
            ("        run: npm --prefix site run build:ci\n",
             "        run: |\n          true || npm --prefix site run build:ci\n"),
        ):
            if not site_workflow_contract_failures(site_workflow.replace(before, after, 1), job):
                failures.append(f"{workflow} accepted a skipped Site build")
    dependencies = (ROOT / ".github/workflows/dependency-review.yml").read_text(encoding="utf-8")
    failures.extend(dependency_workflow_contract_failures(dependencies))
    without_merge_head = dependencies.replace(" || github.event.merge_group.head_sha", "", 1)
    if not dependency_workflow_contract_failures(without_merge_head):
        failures.append("Dependencies accepted a missing merge group head")
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
    for name in ("language-speed-simplicity", "fix"):
        if NIGHTLY_GROUPS.get(name) != (name,) or name not in MANUAL_GROUPS["checks"]:
            failures.append("Nightly must isolate " + name + " without changing the Manual checks group")
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
        (("editors/vscode/package-lock.json",), (True, False, True, False)),
        (("docs/ci.md",), (True, False, False, False)),
        (("compiler/file_elab.ouro",), (True, True, False, False)),
        (("tests/compiler_retained_tests.ouro",), (True, True, False, False)),
        (("tests/compiler/diagnostics/compiler_fault_tests.ouro",), (True, True, False, False)),
        (("tests/compiler/diagnostics/unregistered_tests.ouro",), (True, True, False, False)),
        (("compiler/lexer.ouro",), (True, True, False, False)),
        (("compiler/stage0/driver_u.c",), (True, True, False, False)),
        (("runtime/ouro_rt.c",), (True, True, False, True)),
        (("scripts/kernel_scale.py",), (True, True, False, False)),
        (("tools/repo_gate/compiler_boundary.ouro",), (True, True, False, True)),
        (("quality/smith/strategies.json",), (True, True, False, False)),
        (("tools/fmt.ouro",), (True, False, False, False)),
        (("tests/analyze/architecture_bad/a.ouro",), (True, False, False, False)),
        (("editors/vscode/src/extension.ts", "README.md"), (False, False, True, False)),
        ((".github/workflows/ouro-pr.yml",), (True, False, True, True)),
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
        (("docs/api/std_io.md",), (False, True)),
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
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        std = root / "std"
        nested = std / "gate/share.ouro"
        nested.parent.mkdir(parents=True)
        nested.touch()
        (std / "share.ouro").touch()
        api_pages = ("docs/api/std_gate_share.md", "docs/api/std_share.md")
        with (patch(__name__ + ".ROOT", root),
              patch.object(Path, "rglob", autospec=True, side_effect=Path.rglob) as enumerate_modules):
            docs = plan_paths(api_pages)
            if docs.core or not docs.docs:
                failures.append("nested and top-level generated API pages must select docs only")
            if [call.args for call in enumerate_modules.call_args_list] != [(std, "*.ouro")]:
                failures.append("generated API routing must enumerate standard modules once per selection")
            nested.rename(nested.with_suffix(".txt"))
            mixed = plan_paths(api_pages)
            if not mixed.docs or set(mixed.gates) != full:
                failures.append("an API page without a current source must select the full PR profile")
    for paths in ((), ("compiler/lexer.ouro",), ("runtime/ouro_rt.c",), ("std/data.ouro",), ("unknown/file",)):
        routed = plan_paths(paths)
        expected = full if paths else full | PR_FALLBACK_LINT_GROUPS.keys()
        if not routed.core or not routed.portable or set(routed.gates) - set(PATH_INPUT_GATES) != expected:
            failures.append(f"full portable route lost PR coverage: {paths}")
    portable = full_path_selection("selftest")
    for invalid in (replace(portable, core=False),
                    *(replace(portable, gates=tuple(gate for gate in portable.gates if gate != omitted))
                      for omitted in ("python-syntax", "kernel-hardening"))):
        try:
            selection_matrix(invalid)
        except ValueError:
            pass
        else:
            failures.append("portable validation without Linux coverage was accepted")
    workflow_update = classify_paths([".github/workflows/ouro-manual-trust.yml", ".github/workflows/ouro-release.yml"])
    workflow_gates = {*CONTROL_BASE_GATES, "api-baseline-drift", "doc", "config-show", "build-cache-config", "release-package-check"}
    if (set(workflow_update.gates) != workflow_gates or not workflow_update.dependency
            or workflow_update.kernel or workflow_update.portable
            or selection_matrix(workflow_update)["include"] != [{"group": "checks"}]):
        failures.append("Manual and Release changes must run their complete control-plane checks")
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
    native_sibling_shard = compiler_fixture_input_gates(ROOT)["tests/native_sibling_process_tests.ouro"]
    expected = {
        "python-syntax", "python-lint", "shell-lint", "ci-runner-selftest",
        "github-workflow-gate", "github-project-gate", "host-bound-inventory",
        "api-baseline-drift", "release-package-check", "config-show", "build-cache-config",
        "doc", "docs-examples", "strict-quality-firewall", "structural-quality-suite",
        "structural-quality", "compiler-boundary", "test", "lint-changed", native_sibling_shard,
    }
    if set(release.gates) != expected or release.kernel or release.portable:
        failures.append("release/control-plane change lost its focused policy checks")
    if {name for name in release.gates if name.startswith("compiler-checking-")} != {native_sibling_shard}:
        failures.append("release/control-plane change selected unrelated compiler shards")
    if {row["group"] for row in selection_matrix(release)["include"]} != {
        "checks", "tests", "analyzer-lint", native_sibling_shard.replace("compiler-checking-", "compiler-")
    }:
        failures.append("release/control-plane change selected unrelated matrix groups")
    for pattern, expected in PR_PATH_GATES.items():
        path = {"tools/analyze/": "tools/analyze/ast.ouro", "tools/fix/": "tools/fix/main.ouro",
                "tools/pkg/": "tools/pkg/model.ouro"}.get(pattern, pattern)
        selected = classify_paths([path])
        required = set(PR_BASE_GATES) | set(expected)
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
    for path, tools in (("tools/doc/model.ouro", {"doc", "lsp"}), ("tools/doc/selftest.ouro", {"doc"})):
        if set(classify_paths([path]).gates) & {"doc", "lsp"} != tools:
            failures.append(f"documentation change lost its consumers: {path}")
    combined = classify_paths(["tools/pkg/main.ouro", "tools/lsp.ouro", "README.md"])
    if not {"pkg", "lsp", *DOCS_GROUPS["docs"]} <= set(combined.gates):
        failures.append("mixed tools/docs route lost required gates")
    for invalid in ('{}', 'null', '"README.md"', '[false]', '[""]', '['):
        try:
            selection_from_json(invalid)
        except ValueError:
            continue
        failures.append(f"malformed changed paths accepted: {invalid}")
    if (set(selection_from_json("[]").gates) != full | PR_FALLBACK_LINT_GROUPS.keys()
            or set(selection_from_json("[]", full=True).gates) != full):
        failures.append("empty diff does not select complete validation")
    with patch(__name__ + ".affected_compiler_gates", side_effect=OSError("missing import")):
        fallback = plan_paths(["tools/lsp.ouro"])
        if (set(fallback.gates) != full | {"lint-changed"} or fallback.lint_sources != ("tools/lsp.ouro",)
                or not fallback.portable):
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
        if (main(arguments) != 0 or "BLOCKING lsp " not in printed.getvalue()
                or "BLOCKING memory-budget " not in printed.getvalue() or "c-static-analysis" in printed.getvalue()):
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
        (root / "tools/test/main.ouro").write_text('import "../runner_shared.ouro";\n', encoding="utf-8")
        (root / "tools/runner_shared.ouro").write_text("def shared : Nat := 0;\n", encoding="utf-8")
        (root / "tools/lsp_model.ouro").write_text("def value : Nat := 0;\n", encoding="utf-8")
        (root / "tests/shared.ouro").write_text('import "../tools/lsp_model.ouro" as Model;\n', encoding="utf-8")
        inventory = root / "tools/test/suites.ouro"
        rows = [f'MkSuiteFixture "case_{i}" "tests/case_{i}.ouro" Z SuiteGoldenNone'
                for i in range(COMPILER_SHARDS + 1)]
        rows.append('MkSuiteFixture "source_spans" "tests/source_span_tests.ouro" Z SuiteGoldenNone')
        literal_inventory = "def compiler_check_suite_fixtures : List SuiteFixture :=\n[" + ",\n".join(rows) + "];\n"
        expected_rows = [(f"case_{i}", f"tests/case_{i}.ouro") for i in range(COMPILER_SHARDS + 1)]
        expected_rows.append(("source_spans", "tests/source_span_tests.ouro"))
        for policy in ("SuiteGoldenNone", "SuiteGoldenRequired"):
            inventory.write_text(literal_inventory.replace("SuiteGoldenNone", policy, 1), encoding="utf-8")
            if compiler_fixture_rows(root) != expected_rows:
                failures.append("compiler golden policy changed the complete literal inventory")
        for policy in ("SuiteGoldenOptional", "SuiteGoldenUnknown", "SuiteGoldenRequiredSuffix"):
            inventory.write_text(literal_inventory.replace("SuiteGoldenNone", policy, 1), encoding="utf-8")
            try:
                compiler_fixture_rows(root)
            except ValueError:
                pass
            else:
                failures.append("unsupported compiler golden policy accepted: " + policy)
        inventory.write_text(literal_inventory.replace("SuiteGoldenNone", "SuiteGoldenRequired", 1), encoding="utf-8")
        for i in range(COMPILER_SHARDS + 1):
            source = ('import "shared.ouro";\n' if i in {0, COMPILER_SHARDS - 1}
                      else "def value : Nat := 0;\n")
            (root / f"tests/case_{i}.ouro").write_text(source, encoding="utf-8")
        (root / "tools/isolated.ouro").write_text("def isolated : Nat := 0;\n", encoding="utf-8")
        (root / "sample.txt").write_text("runtime input\n", encoding="utf-8")
        (root / "tests/source_span_tests.ouro").write_text(
            'import "../tools/isolated.ouro";\ndef ss_files : List String := ["sample.txt"];\n', encoding="utf-8")
        if affected_compiler_gates(["sample.txt"], root) != {f"compiler-checking-{COMPILER_SHARDS}"}:
            failures.append("runtime source-span input lost its compiler shard")
        if affected_compiler_gates(["tests/case_0.golden"], root) != {"compiler-checking-1"}:
            failures.append("compiler golden lost its owning shard")
        if affected_compiler_gates(["tools/runner_shared.ouro"], root) != {
                f"compiler-checking-{index}" for index in range(1, COMPILER_SHARDS + 1)}:
            failures.append("test runner dependency lost compiler shards")
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
        (root / "tests/shared.ouro").write_text(
            'import "../tools/lsp_model.ouro"; -- import "comment.ouro";\n'
            'def text : String := r#"import "raw.ouro";"#;\n'
            'def quoted : String := "import";\n', encoding="utf-8")
        if affected_compiler_gates(["tools/lsp_model.ouro"], root) != {"compiler-checking-1"}:
            failures.append("import token projection lost quoted-import routing")
        for body, expected in (
            ('def qualified : Nat := Model.import;\n', "unsupported import layout in tests/shared.ouro"),
            ('def malformed : String := r#"unfinished\n', "unclosed raw string at line 2"),
        ):
            (root / "tests/shared.ouro").write_text(
                'import "../tools/lsp_model.ouro";\n' + body, encoding="utf-8")
            try:
                affected_compiler_gates(["tools/lsp_model.ouro"], root)
            except ValueError as exc:
                if str(exc) != expected:
                    failures.append(f"import token projection changed diagnostic: {exc}")
            else:
                failures.append(f"import token projection accepted unsupported source: {body}")
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
        write_github_output(output, selected, selection_matrix(selected))
        values = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
        if values["core"] != "false" or json.loads(values["changed_paths"]) != list(selected.paths):
            failures.append("filename escaped the GitHub output record")
        production_groups = {f"lint-production-{index}" for index in range(1, LINT_PRODUCTION_SHARDS + 1)}
        lint_command = ["--profile", "pr", "--group", "lint-production-1", "--list", "--changed-paths-json"]
        oversized = ["tools/lsp.ouro", *(f"docs/{index:03d}-{'a' * 100}.md" for index in range(400))]
        for paths in (None, oversized):
            output.write_text("", encoding="utf-8")
            with (patch(__name__ + ".changed_paths", return_value=(paths, "test diff")),
                  patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": ""}),
                  contextlib.redirect_stdout(io.StringIO())):
                status = run_path_selection("a" * 40, "b" * 40, str(output))
            values = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
            groups = {row["group"] for row in json.loads(values["matrix"])["include"]}
            if (status or values["changed_paths"] != "[]" or "analyzer-lint" in groups
                    or not {*PR_LINT_PHASES, *production_groups} <= groups):
                failures.append("unavailable or oversized PR diff lost complete lint coverage")
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                status = main([*lint_command, values["changed_paths"], "--selection-key", values["selection_key"]])
            if (status or printed.getvalue() != "BLOCKING lint-production-1 sh scripts/lint_suite.sh "
                                                f"--phase=production --shard=1/{LINT_PRODUCTION_SHARDS}\n"):
                failures.append("PR fallback consumer did not run the canonical production lint shard")
        with (contextlib.redirect_stderr(io.StringIO()),
              patch(__name__ + ".affected_compiler_gates", return_value=set())):
            for paths, full_mode in ((["tools/lsp.ouro"], False), ([], True)):
                changed = json.dumps(paths)
                selected = selection_from_json(changed, full=full_mode)
                if set(selected.gates) & production_groups:
                    failures.append("ordinary PR selection scheduled fallback production lint")
                try:
                    main([*lint_command, changed, "--selection-key", selection_key(selected),
                          *(["--full"] if full_mode else [])])
                except SystemExit as exc:
                    if exc.code != 2:
                        failures.append("unselected production lint did not report a usage error")
                else:
                    failures.append("PR consumer accepted an unselected production lint group")
    failures.extend(lint_changed_contract_failures())
    return failures


def pr_test_group_contract_failures(all_gates: Sequence[Gate]) -> list[str]:
    import contextlib
    import io
    from unittest.mock import patch

    from ouro_build import ENV_MAP
    from ourosmith.host import shell

    def list_group(group: str, *route: str) -> tuple[object, list[list[str]]]:
        printed = io.StringIO()
        with (patch(__name__ + ".gates", return_value=all_gates), contextlib.redirect_stdout(printed),
              contextlib.redirect_stderr(io.StringIO())):
            try:
                status = main(["--profile", "pr", "--group", group, "--list", *route])
            except SystemExit as exc:
                status = exc.code
        return status, [line.split(" ", 2)[:2] for line in printed.getvalue().splitlines()]

    failures: list[str] = []
    test_command = next((gate.cmd for gate in all_gates if gate.name == "test" and gate.blocking), [])
    if test_command != ["sh", "scripts/test_suite.sh", "--require-cc"]:
        failures.append("blocking PR test must pass --require-cc to its launcher")
    runtime_gate = next((gate for gate in all_gates if gate.name == "runtime-io" and gate.blocking), None)
    if runtime_gate is None:
        failures.append("runtime-io must remain a blocking gate")

    shell_helpers = (
        "dirname() { printf '%s\\n' \"${1%/*}\"; }\n"
        "mkdir() { :; }\n"
    )
    probe = shell_helpers + 'export PATH=bin\n. "$0"\n'
    with tempfile.TemporaryDirectory(prefix="ouro-ci-test-compiler-") as temporary:
        root = Path(temporary).resolve()
        launcher = root / "scripts/test_suite.sh"
        launcher.parent.mkdir()
        for name in ("test_suite.sh", "ouro_build.py", "local_scheduler.py", "repo_support.py",
                     "generated_c_shards.py", "ouro_seal.py"):
            shutil.copyfile(ROOT / "scripts" / name, launcher.with_name(name))
        launcher.with_name("python.sh").write_text("", encoding="utf-8")
        launcher.with_name("compiler_shards.py").write_text(
            'import sys\nprint("configured compiler accepted", file=sys.stderr)\nraise SystemExit(23)\n', encoding="utf-8")
        clang = root / "bin" / ("clang.exe" if os.name == "nt" else "clang")
        clang.parent.mkdir()
        clang.write_bytes(b"")
        clang.chmod(0o755)
        env = {key: value for key, value in os.environ.items() if key not in ENV_MAP.values()}
        env.update(PYTHON=Path(sys.executable).as_posix(), PYTHONPATH="", PATHEXT=".EXE", OURO_CI_PREPARED_TEST="1")
        try:
            shell_executable = shutil.which("sh") or str(shell(search_path=False))
            command = [shell_executable, "-c", probe, launcher.as_posix()]
            for args, cc, code, diagnostic in (
                ((), "clang", 0, "TEST_SUITE: SKIP no system C compiler"),
                (("--require-cc",), "cc", 1, "TEST_SUITE: FAIL no system C compiler"),
                (("--require-cc",), "clang", 23, "configured compiler accepted"),
                (("--compiler-checking", "--shard=1/16"), "clang", 1, "COMPILER_CHECK_SUITE: FAIL no system C compiler"),
            ):
                (root / "Ouro.seal").write_text(f'seal 1\nbuild {{\n  cc = "{cc}"\n}}\n', encoding="utf-8")
                result = subprocess.run([*command, *args], cwd=root, env=env, capture_output=True, text=True,
                                        timeout=5, check=False)
                if result.returncode != code or diagnostic not in result.stderr.splitlines():
                    failures.append(f"test launcher has the wrong result for {args} with cc={cc}")
            if runtime_gate is not None:
                runtime_launcher = launcher.with_name("runtime_io_suite.sh")
                shutil.copyfile(ROOT / "scripts/runtime_io_suite.sh", runtime_launcher)
                runtime_probe = shell_helpers + 'export PATH=\nexport CC=missing-test-compiler\n. "$0"\n'
                runtime_command = [shell_executable, "-c", runtime_probe, runtime_launcher.as_posix()]
                required = env_for(runtime_gate, root, root, Allocation(1, 3072))
                standalone = required.copy()
                standalone.pop("OURO_CI_GATE_NAME", None)
                for runtime_env, code, verdict in ((required, 127, "FAIL"), (standalone, 0, "SKIP")):
                    result = subprocess.run(runtime_command, cwd=root, env=runtime_env, capture_output=True,
                                            text=True, timeout=5, check=False)
                    diagnostic = f"RUNTIME_IO_SUITE: {verdict} no system C compiler"
                    if result.returncode != code or diagnostic not in result.stderr.splitlines():
                        failures.append(f"runtime-io launcher has the wrong missing-compiler result for {verdict}")
        except (OSError, subprocess.TimeoutExpired) as error:
            failures.append("cannot verify launchers without a C compiler: " + str(error))

    full_tests = ("ergonomics", "imports", "frontend-security", "runtime-io", "test", "compiler-boundary")
    split_tests = {
        "tests": ("ergonomics", "imports", "test", "compiler-boundary"),
        "runtime-io": ("runtime-io",),
        "frontend-security": ("frontend-security",),
    }
    if list_group("tests") != (0, [["BLOCKING", name] for name in full_tests]):
        failures.append("local PR tests lost a blocking gate")
    for group in ("runtime-io", "frontend-security"):
        if list_group(group) != (2, []):
            failures.append("local PR accepted a hosted-only group: " + group)

    cases = (
        (["scripts/runtime_io_suite.sh"], False, {"runtime-io": ("runtime-io",)}),
        (["scripts/frontend_host_suite.py"], False, {"frontend-security": ("frontend-security",)}),
        (["tools/repo_gate/checks.ouro"], False, {"tests": ("test", "compiler-boundary")}),
        (None, False, split_tests),
        (None, True, {"tests": full_tests}),
    )
    with (tempfile.TemporaryDirectory(prefix="ouro-ci-tests-routing-") as temporary,
          patch(__name__ + ".affected_compiler_gates", return_value=set())):
        output = Path(temporary) / "outputs"
        summary = Path(temporary) / "summary"
        for paths, full, expected in cases:
            output.write_text("", encoding="utf-8")
            summary.write_text("", encoding="utf-8")
            with (patch(__name__ + ".changed_paths", return_value=(paths, "test diff")),
                  patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}),
                  contextlib.redirect_stdout(io.StringIO())):
                status = run_path_selection("a" * 40, "b" * 40, str(output), full=full)
            if status:
                failures.append(f"PR tests routing failed for {paths}, full={full}")
                continue
            values = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
            planned = [row["group"] for row in json.loads(values["matrix"])["include"] if row["group"] in split_tests]
            reported = [line for line in summary.read_text(encoding="utf-8").splitlines()
                        if any(line.startswith(f"- **{group}**") for group in split_tests)]
            expected_summary = [f"- **{group}**: {', '.join(names)}" for group, names in expected.items()]
            if planned != list(expected) or reported != expected_summary:
                failures.append(f"PR matrix or summary changed test coverage for {paths}, full={full}")
            options = ["--changed-paths-json", values["changed_paths"], "--selection-key", values["selection_key"]]
            if full:
                options.append("--full")
            for group, names in expected.items():
                if list_group(group, *options) != (0, [["BLOCKING", name] for name in names]):
                    failures.append(f"PR {group} changed blocking gates for {paths}, full={full}")
            for group in split_tests:
                if group not in expected and list_group(group, *options) != (2, []):
                    failures.append(f"PR accepted an unselected {group} for {paths}, full={full}")
    return failures


def area_selection_contract_failures() -> list[str]:
    import contextlib
    import io
    import tempfile
    from unittest.mock import patch

    failures: list[str] = []
    ruff = plan_paths(["quality/ruff.toml"])
    if set(ruff.gates) != {"python-lint"} or not ruff.core or ruff.host_compiler or ruff.portable:
        failures.append("Ruff configuration must run only host Python lint")
    biome = plan_paths(["quality/biome.json"])
    if not biome.editor or not biome.site or biome.core or biome.host_compiler or biome.gates:
        failures.append("Biome configuration must validate both JavaScript projects")
    site = plan_paths(["site/package.json"])
    if not site.site or site.editor or site.core or site.dependency or site.host_compiler:
        failures.append("site package changed its workflow-scan or host-compiler ownership")
    with patch(__name__ + ".affected_compiler_gates", return_value=set()):
        clippy_cases = (
            (["tests/clippy_semantic/session_wire.ouro"], {"lint-fixtures"}),
            (["tests/clippy_semantic/cases.json"], {"lint-clippy"}),
            (["tests/clippy_semantic/imported_contracts.ouro"], set(PR_LINT_PHASES)),
            (["tests/clippy_semantic/cases.json", "compiler/lexer.ouro"], {"lint-clippy"}),
            (["tests/clippy_semantic/unknown-file.ouro"], set(PR_LINT_PHASES)),
            (["scripts/lint_suite.sh"], set(PR_LINT_PHASES)),
            (["scripts/ouro1.sh"], {"lint-fixtures"}),
            (["scripts/clippy_grade_firewall.py"], {"lint-clippy"}),
        )
        for files, phases in clippy_cases:
            plan = plan_paths(files)
            if phases != set(plan.gates).intersection(PR_LINT_PHASES):
                failures.append(f"Clippy fixtures lost canonical lint phase ownership: {files}")
            for phase in phases:
                printed = io.StringIO()
                with contextlib.redirect_stdout(printed):
                    status = main(["--profile", "pr", "--group", phase, "--changed-paths-json", json.dumps(files),
                                   "--selection-key", selection_key(plan), "--list"])
                if status or printed.getvalue().strip() != f"BLOCKING {phase} sh scripts/lint_suite.sh --phase={phase[5:]}":
                    failures.append(f"Clippy path plan did not dispatch its canonical command: {phase}")
    fs_gates = {"fmt", "fix", "runtime-io", "analyze-precision", "frontend-security", "build-cache-config"}
    fs = classify_paths(["scripts/fs_replace_suite.py"])
    if not fs_gates <= set(fs.gates) or fs.portable or {"samples-1", "samples-2"} & set(fs.gates):
        failures.append("filesystem replacement suite lost a caller or added unrelated integration suites")

    fix_laws = classify_paths(["tests/fix_laws.ouro"])
    if set(fix_laws.gates) != {"fix", "structural-quality"} or not fix_laws.host_compiler:
        failures.append("fix law runner must select fix and structural quality")

    host_suite_policy = {"python-syntax", "python-lint", "structural-quality", "host-bound-inventory"}
    host_suite_cases = (
        ("scripts/frontend_lower_lookup_test.py", {"build-cache-config", "stage-loop-frontend-regeneration"}),
        ("scripts/fs_read_suite.py", {"runtime-io", "analyze-precision", "frontend-security", "build-cache-config"}),
        ("scripts/memory_budget_suite.py", {"build-cache-config", "memory-budget"}),
        ("scripts/scoped_host_exports_test.py", {"build-cache-config", "stage-loop-frontend-regeneration"}),
    )
    full_gates = set(full_path_selection("test").gates)
    for path, suites in host_suite_cases:
        selected = classify_paths([path])
        if (set(selected.gates) != host_suite_policy | suites or not selected.host_compiler
                or selected.kernel or selected.portable):
            failures.append("host suite change must select its consumers and policy gates: " + path)
        mixed_compiler = classify_paths([path, "compiler/lexer.ouro"])
        if set(mixed_compiler.gates) != full_gates or not mixed_compiler.kernel or not mixed_compiler.portable:
            failures.append("mixed compiler and host suite change must retain full validation: " + path)

    budgets = classify_paths(["quality/kernel_budgets.json"])
    if (not budgets.portable or not budgets.kernel or set(budgets.gates) != {
            "kernel-hardening", "python-syntax", "host-bound-inventory"}):
        failures.append("kernel budgets must retain Linux and macOS hardening")
    with patch(__name__ + ".affected_compiler_gates", return_value={"compiler-checking-3"}):
        shared = plan_paths(["quality/kernel_budgets.json", "tools/lsp.ouro"])
        if "compiler-checking-3" not in shared.gates or not shared.portable:
            failures.append("portable hardening masked an independently selected compiler shard")
    regressions = sorted((ROOT / "quality/smith/regressions").glob("*.json"))
    if regressions:
        smith = classify_paths([rel(regressions[0])])
        if set(smith.gates) != {"ouro-smith"} or smith.portable or smith.kernel:
            failures.append("saved surface regression must select the PR OuroSmith replay")
    smith_launcher = plan_paths(["scripts/ouro_smith.py"])
    if not smith_launcher.kernel or "ouro-smith" not in smith_launcher.gates:
        failures.append("OuroSmith launcher lost its PR and kernel-extra consumers")

    mixed = classify_paths(["quality/ruff.toml", "quality/biome.json", "scripts/fs_replace_suite.py", "README.md"])
    required = set(ruff.gates) | set(fs.gates) | set(DOCS_GROUPS["docs"])
    if (set(mixed.gates) != required or mixed.portable
            or not all((mixed.core, mixed.docs, mixed.editor, mixed.site, mixed.host_compiler))):
        failures.append("mixed host, JavaScript and docs changes must retain all owners")
    with tempfile.TemporaryDirectory(prefix="ouro-area-routing-") as temporary:
        root = Path(temporary).resolve()
        output = root / "outputs"
        write_github_output(output, mixed, selection_matrix(mixed))
        values = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
        if any(values.get(name) != "true" for name in ("site", "editor", "host_compiler")):
            failures.append("GitHub outputs lost a selected project or host compiler")

        fixture = "tests/native_pe_tests.ouro"
        golden = Path(fixture).with_suffix(".golden").as_posix()
        for name in ("tools/test/suites.ouro", fixture):
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, root / name)
        (root / golden).write_text("expected\n", encoding="utf-8")
        (root / "tests/unknown.golden").write_text("unexpected\n", encoding="utf-8")
        (root / WORKFLOW_STDLIB_GOLDEN).touch()
        with patch(__name__ + ".ROOT", root):
            owning_gate = compiler_fixture_input_gates(root)[fixture]
            added = classify_paths([golden])
            if {name for name in added.gates if name.startswith("compiler-checking-")} != {owning_gate} or added.portable:
                failures.append("present compiler golden lost its registered fixture owner")
            (root / golden).unlink()
            if not classify_paths([golden]).portable or not classify_paths(["tests/unknown.golden"]).portable:
                failures.append("deleted or unregistered compiler golden narrowed validation")
            workflow_compiler = {WORKFLOW_STDLIB_GOLDEN: owning_gate}
            for workflow_samples in ({}, {WORKFLOW_STDLIB_GOLDEN: {"samples-1"}}):
                if file_gates(WORKFLOW_STDLIB_GOLDEN, workflow_samples, workflow_compiler, documentation=False) is not None:
                    failures.append("workflow golden in the compiler inventory narrowed validation")

        corpus = root / "tests/clippy_semantic"
        expansion = corpus / "quality_expansion"
        expansion.mkdir(parents=True)
        entries = [expansion / name for name in ("left.ouro", "next.ouro")]
        for entry in entries:
            entry.touch()
        paths = [entry.relative_to(root).as_posix() for entry in entries]
        manifest = corpus / "cases.json"
        valid_manifest = json.dumps({"cases": [{"path": path} for path in paths]})
        manifest.write_text(valid_manifest, encoding="utf-8")
        with (patch(__name__ + ".ROOT", root),
              patch(__name__ + "._clippy_case_paths", wraps=_clippy_case_paths) as parse):
            selection = classify_paths(paths)
        if parse.call_count != 1 or set(selection.gates) != {"lint-clippy", "structural-quality"}:
            failures.append("current Clippy manifest reads must share one parse")

        read_text = Path.read_text
        versions = iter((valid_manifest, '{"cases":[]}'))

        def read_manifest(path, *args, **kwargs):
            return next(versions) if path == manifest else read_text(path, *args, **kwargs)

        with (patch(__name__ + ".ROOT", root),
              patch.object(Path, "read_text", autospec=True, side_effect=read_manifest)):
            if not classify_paths(paths).portable:
                failures.append("changed Clippy manifest must disable narrowed fixture routing")

        aliases = corpus / "alias_scope"
        aliases.mkdir()
        for name in ("left.ouro", "next.ouro"):
            (aliases / name).touch()
        qualified = aliases / "qualified.ouro"
        qualified.write_bytes(b'import "left.ouro";\r\n')
        alias_paths = [(aliases / name).relative_to(root).as_posix() for name in ("left.ouro", "next.ouro")]
        read_bytes = Path.read_bytes
        imports = iter((b'import "left.ouro";\r\n', b'import "next.ouro";\r\n'))

        def read_alias(path):
            return next(imports) if path == qualified else read_bytes(path)

        with (patch(__name__ + ".ROOT", root),
              patch.object(Path, "read_bytes", autospec=True, side_effect=read_alias)):
            if set(classify_paths(alias_paths).gates) != {"lint-clippy", "structural-quality"}:
                failures.append("renewed Clippy import bytes must update fixture routing")

        (aliases / "selected.ouro").write_bytes(b'import "left.ouro", "next.ouro";\r\n')
        with (patch(__name__ + ".ROOT", root),
              patch.object(Path, "read_bytes", autospec=True, side_effect=read_bytes) as reads):
            gated = clippy_fixture_gates(alias_paths[1])
        if gated != {"lint-clippy"} or [call.args[0] for call in reads.call_args_list].count(aliases / "left.ouro") != 1:
            failures.append("Clippy suite roots must share import reads for one changed fixture")

        analyzer = root / "tests/analyze"
        scope = analyzer / "format_bad"
        scope.mkdir(parents=True)
        analyzer_paths = []
        for name in ("first.ouro", "second.ouro"):
            entry = scope / name
            entry.touch()
            analyzer_paths.append(entry.relative_to(root).as_posix())
        (root / "scripts").mkdir()
        (root / "scripts/analyze_precision_suite.sh").write_text('--scope "$FIX/format_bad"\n', encoding="utf-8")
        analyzer_manifest = analyzer / "manifest.json"
        analyzer_manifest.write_text('{"pipeline":{"bad":[{"scope":"format_bad"}],"good":[]}}', encoding="utf-8")
        with (patch(__name__ + ".ROOT", root),
              patch(__name__ + "._analyzer_pipeline_paths", wraps=_analyzer_pipeline_paths) as parse):
            selection = classify_paths(analyzer_paths)
            if parse.call_count != 1 or set(selection.gates) != {"analyze-precision", "structural-quality"}:
                failures.append("current analyzer manifest reads must share one parse")
            analyzer_manifest.write_text('{"pipeline":{"bad":[],"good":[]}}', encoding="utf-8")
            if not classify_paths(analyzer_paths).portable:
                failures.append("changed analyzer manifest must disable narrowed fixture routing")

    full = full_path_selection("test")
    for paths in (["unclassified/file", "../invalid"], ["../invalid", "unclassified/file"], []):
        actual = classify_paths(paths)
        if actual.mode != "full" or actual.paths or actual.gates != full.gates or selection_key(actual) != selection_key(full):
            failures.append(f"incomplete full fallback for {paths!r}")
    with patch(__name__ + ".affected_compiler_gates", side_effect=ValueError("invalid dependency inventory")):
        fallback = plan_paths(["tools/lsp.ouro"])
    if (fallback.mode != "full" or fallback.paths != ("tools/lsp.ouro",) or fallback.lint_sources != fallback.paths
            or set(fallback.gates) != {*full.gates, "lint-changed"}):
        failures.append("compiler inventory failure dropped the known production lint inputs")
    production = plan_paths(["compiler/core.ouro"])
    for field in ("paths", "lint_sources"):
        different = replace(production, **{field: ("compiler/driver.ouro",)})
        if selection_key(production) == selection_key(different):
            failures.append("producer key did not bind " + field)

    inventory = compiler_fixture_roots(ROOT)
    owners = {path: f"compiler-checking-{shard}" for shard in range(1, COMPILER_SHARDS + 1)
              for path in compiler_shard_entries(inventory, shard)}
    cases = ("tests/native_live_tests.ouro", "tests/native_pe_tests.ouro", "tests/compiler_checked_program_tests.ouro",
             "tests/compiler_file_helper_tests.ouro", "tests/compiler_fs_predicate_binding_tests.ouro")
    for path in cases:
        route = classify_paths([path])
        shards = {name for name in route.gates if name.startswith("compiler-checking-")}
        if path not in owners or shards != {owners.get(path)} or route.portable or route.kernel:
            failures.append("isolated compiler fixture must run its inventory shard: " + path)

    sidecars = classify_paths(["samples/demo/01_hello.stdin", "samples/demo/01_hello.golden"])
    if {name for name in sidecars.gates if name.startswith("samples-")} != {"samples-1"} or sidecars.portable:
        failures.append("registered hello input and stdout must use the first sample shard")
    sample = classify_paths(["samples/demo/01_hello.ouro"])
    if not {"samples-1", "fmt"} <= set(sample.gates) or "samples-2" in sample.gates or sample.portable:
        failures.append("hello source lost formatting or its sample shard")
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
            try:
                plan_paths(["tools/lsp.ouro"])
            except ValueError:
                pass
            else:
                failures.append("unreadable lint inventory silently skipped changed production sources")
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
              patch(__name__ + ".available_memory_mib", return_value=6144),
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
            smith = replace(gate, name="ouro-smith")
            plan = full_path_selection("summary contract")
            routed = ["--group", "smith", "--changed-paths-json", "[]", "--selection-key", selection_key(plan)]
            annotation = "::error title=Blocking PR gate::ouro-smith"
            failed_smith = dict(failed_row, name=smith.name)
            cases = (
                ("true", "pull_request", routed, True, failed_smith, [annotation]),
                ("true", "pull_request", routed, True, dict(failed_smith, name="ouro-smith\n::error::injected"), []),
                ("true", "pull_request", routed, True, dict(row, name=smith.name), []),
                ("true", "pull_request", routed, False, failed_smith, []),
                ("true", "pull_request", [], True, failed_smith, []),
                ("true", "merge_group", [*routed, "--full"], True, failed_smith, []),
                ("false", "pull_request", routed, True, failed_smith, []),
            )
            with (patch(__name__ + ".gates", return_value=[smith]),
                  patch(__name__ + ".selection_from_json", return_value=plan)):
                for hosted, event, route, fail_fast, result_row, expected in cases:
                    printed = io.StringIO()
                    with (patch.dict(os.environ, {"GITHUB_ACTIONS": hosted, "GITHUB_EVENT_NAME": event}),
                          patch(__name__ + ".run_gate", return_value=result_row),
                          contextlib.redirect_stdout(printed)):
                        status = main([*args, *route, *(["--fail-fast"] if fail_fast else [])])
                    lines = printed.getvalue().splitlines()
                    report = json.loads(summary.read_text(encoding="utf-8"))
                    if (status != result_row["returncode"] or report.get("gates") != [result_row]
                            or report.get("pass") is not (status == 0)
                            or not lines or not lines[0].startswith("CI_GATE_SUMMARY ") or lines[1:] != expected):
                        failures.append(f"incorrect blocking PR annotation or summary on {hosted=}, {event=}, {fail_fast=}")
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


def scheduler_contract_failures() -> list[str]:
    import contextlib
    import io
    from threading import Barrier, Event
    from unittest.mock import patch

    failures = []
    with tempfile.TemporaryDirectory(prefix="ci-scheduler-") as temporary:
        root = Path(temporary).resolve()
        subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
        (root / ".gitignore").write_text("_build/\n", encoding="utf-8")
        source = root / "input.txt"
        source.write_text("index", encoding="utf-8")
        subprocess.run(["git", "add", "input.txt", ".gitignore"], cwd=root, check=True)
        source.write_text("working tree", encoding="utf-8")
        build = ("from pathlib import Path; import os; "
                 "assert Path('input.txt').read_text() == 'working tree'; "
                 "out = Path(os.environ['OURO_BUILD_DIR']); out.mkdir(); "
                 "(out / 'fixed').write_text(os.environ['OURO_CI_GATE_NAME'])")
        successor = ("from pathlib import Path; import sys; "
                     "sys.exit(Path('_build/fixed').read_text() != 'first' or Path('fault').exists())")
        gates_under_test = [Gate(name, [sys.executable, "-c", code], ("pr",))
                            for name, code in (("first", build), ("dependent", successor), ("independent", build))]
        groups = {"pr": {"ordered": ("first", "dependent"), "separate": ("independent",)}}
        run = run_gate
        with (patch(__name__ + ".ROOT", root), patch(__name__ + ".rel", bind_relative_path(root, resolve=True)),
              patch(__name__ + ".PROFILE_GROUPS", groups), patch(__name__ + ".gates", return_value=gates_under_test),
              patch(__name__ + ".available_memory_mib", return_value=6144),
              patch.dict(os.environ, {"OURO_SCHEDULER_JOBS": "40"}), contextlib.redirect_stdout(io.StringIO())):
            for requested, jobs in ((1, 1), (20, 20), (40, 20)):
                barrier = Barrier(2)

                def synchronized(gate, *, parallel=jobs > 1, rendezvous=barrier, **kwargs):
                    if parallel and gate.name != "dependent":
                        rendezvous.wait(timeout=10)
                    return run(gate, **kwargs)

                with patch(__name__ + ".run_gate", side_effect=synchronized):
                    for fault in (False, True):
                        marker = root / "fault"
                        if fault:
                            marker.touch()
                        else:
                            marker.unlink(missing_ok=True)
                        args = ["--profile", "pr", "--jobs", str(requested), "--out", "_build/ci/results"]
                        result = main(args)
                        report = json.loads((root / "_build/ci/results/ci-summary.json").read_text(encoding="utf-8"))
                        rows = report["gates"]
                        if (result != int(fault) or report["not_run"] or [row["name"] for row in rows] !=
                                [gate.name for gate in gates_under_test] or [row["name"] for row in report["blocking_failures"]]
                                != (["dependent"] if fault else [])):
                            failures.append(f"scheduler changed coverage or fault verdict at --jobs {jobs}")
                        if (report["scheduler"]["jobs"] != jobs
                                or rows[0]["workspace"] != rows[1]["workspace"] or rows[0]["workspace"] == rows[2]["workspace"]
                                or report["scheduler"]["peak_tasks"] != (1 if jobs == 1 else 2)
                                or report["scheduler"]["peak_jobs"] > jobs
                                or report["scheduler"]["peak_memory_mib"] > 6144):
                            failures.append(f"scheduler violated workspace or resource allocation at --jobs {requested}")
            bad = replace(gates_under_test[-1], cmd=[sys.executable, "-c", "raise SystemExit(1)"])
            gates_under_test[-1] = bad
            independent_failed = Event()

            def finish_out_of_order(gate, **kwargs):
                if gate.name == "first" and not independent_failed.wait(timeout=10):
                    raise TimeoutError("independent gate did not finish")
                row = run(gate, **kwargs)
                if gate.name == "independent":
                    independent_failed.set()
                return row

            with patch(__name__ + ".run_gate", side_effect=finish_out_of_order):
                main([*args, "--fail-fast"])
            report = json.loads((root / "_build/ci/results/ci-summary.json").read_text(encoding="utf-8"))
            if report["not_run"] != ["dependent"] or [r["name"] for r in report["gates"]] != ["first", "independent"]:
                failures.append("parallel fail-fast reported the wrong unfinished gates")
    tasks = [Task("leaf", ("middle",)), Task("middle", ("producer",)), Task("producer"),
             Task("independent"), Task("successor", ("independent",))]
    for jobs, memory in ((1, 6144), (20, 6144), (20, 1024)):
        for fault in (False, True):
            results, stats = run_tasks(tasks, jobs=jobs, memory_mib=memory,
                                   run=lambda task, _lease, fault=fault: fault and task.name == "producer",
                                   failed=bool)
            expected = {task.name: fault and task.name == "producer" for task in tasks
                        if not fault or task.name not in {"middle", "leaf"}}
            if results != expected or stats["peak_memory_mib"] > memory:
                failures.append(f"scheduler changed transitive failure coverage or memory at {jobs} jobs, {memory} MiB")
    smith = Gate("ouro-smith", ["unexecuted-smith-command"], ("pr",))
    with (patch(__name__ + ".available_memory_mib") as budget,
          patch(__name__ + ".run_gate", return_value={"name": smith.name, "status": "pass", "blocking": True}) as run_smith):
        for hosted, event, jobs, memory, expected in (
            ("true", "pull_request", 2, 4096, Allocation(2, 4096)),
            ("true", "pull_request", 2, 4095, Allocation(2, 3584)),
            ("true", "pull_request", 2, 3500, Allocation(1, 3072)),
            ("true", "pull_request", 2, None, Allocation(2, 3584)),
            ("true", "pull_request", 1, 4096, Allocation(1, 3072)),
            ("true", "merge_group", 2, 4096, Allocation(2, 3584)),
            ("false", "pull_request", 2, 4096, Allocation(2, 3584)),
        ):
            budget.return_value = memory
            run_smith.reset_mock()
            with patch.dict(os.environ, {"GITHUB_ACTIONS": hosted, "GITHUB_EVENT_NAME": event}):
                schedule_gates([smith], out=ROOT, profile="pr", group="smith", jobs=jobs, fail_fast=False)
            if run_smith.call_count != 1 or run_smith.call_args.kwargs["allocation"] != expected:
                failures.append(f"incorrect Smith allocation on {hosted=}, {event=}, {jobs=}, {memory=}")
    return failures


def serial_gate_reservation_contract_failures(first: str) -> list[str]:
    from threading import Event
    from unittest.mock import patch

    failures = []
    probes = (first, "compiler-depth")
    gates_under_test = [Gate(name, ["probe"], ("pr",)) for name in (*probes, "config-show", "compiler-checking-1")]
    groups = {"pr": {"checker": probes, "separate": ("config-show", "compiler-checking-1")}}
    memory = 12800
    with tempfile.TemporaryDirectory(prefix="ci-scale-scheduler-") as temporary:
        root = Path(temporary).resolve()
        with (patch(__name__ + ".ROOT", root), patch(__name__ + ".PROFILE_GROUPS", groups),
              patch(__name__ + ".LOCAL_COMPILER_GATES", set()),
              patch(__name__ + ".available_memory_mib", return_value=memory),
              patch(__name__ + ".CheckoutSnapshot") as snapshot,
              patch.dict(os.environ, {"GITHUB_ACTIONS": "false"})):
            snapshot.return_value.copy_to.side_effect = lambda path, **_kwargs: path.mkdir()
            for jobs, fault in ((1, False), (1, True), (20, False), (20, True)):
                first_started = Event()
                shard_started = Event()
                first_finished = Event()
                overlaps = []

                def run(gate, *, allocation, workspace, jobs=jobs, fault=fault, first_started=first_started,
                        shard_started=shard_started, first_finished=first_finished, overlaps=overlaps, **_kwargs):
                    artifact = workspace / "probe-artifact"
                    if gate.name == first:
                        artifact.write_text(first, encoding="utf-8")
                        first_started.set()
                        overlaps.append(jobs > 1 and shard_started.wait(timeout=5))
                        first_finished.set()
                    elif gate.name == "config-show":
                        if jobs > 1 and not first_started.wait(timeout=5):
                            raise AssertionError(f"{first} did not start alongside the independent predecessor")
                        if artifact.exists():
                            raise AssertionError(f"{first} wrote into the independent checkout")
                        artifact.write_text(gate.name, encoding="utf-8")
                    elif gate.name == "compiler-checking-1":
                        if artifact.read_text(encoding="utf-8") != "config-show":
                            raise AssertionError(f"{first} changed the independent predecessor's output")
                        shard_started.set()
                    elif not first_finished.is_set() or artifact.read_text(encoding="utf-8") != first:
                        raise AssertionError(f"depth started without {first}'s output")
                    return {"name": gate.name, "status": "fail" if fault and gate.name == first else "pass", "blocking": True,
                            "jobs": allocation.jobs, "memory_mib": allocation.memory_mib}

                with patch(__name__ + ".run_gate", side_effect=run):
                    results, stats = schedule_gates(gates_under_test, out=root, profile="pr", group=None,
                                                    jobs=jobs, fail_fast=False)
                if results.keys() != {gate.name for gate in gates_under_test}:
                    failures.append(f"{first} and depth changed scheduler coverage at {jobs} jobs")
                    continue
                if {name for name, row in results.items() if row["status"] == "fail"} != ({first} if fault else set()):
                    failures.append(f"{first} changed the fault verdict at {jobs} jobs")
                if overlaps != [jobs > 1]:
                    failures.append(f"{first} reservation blocked the next independent gate at {jobs} jobs")
                if (any((results[name]["jobs"], results[name]["memory_mib"]) != (1, 3072) for name in probes)
                        or stats["peak_jobs"] > jobs or stats["peak_memory_mib"] > memory):
                    failures.append(f"{first} or depth used the wrong resource reservation at {jobs} jobs")
    return failures


def lint_execution_contract_failures(all_gates: Sequence[Gate]) -> list[str]:
    from unittest.mock import patch

    failures = []
    shards = tuple(f"lint-production-{index}" for index in range(1, 5))
    ordered = ("lint-fixtures", *shards, "lint-clippy")
    preparation = (COMPILER_PREPARATION, LINT_PREPARATION, PACKAGE_PREPARATION)
    preparation_plan = [(COMPILER_PREPARATION, ()), (LINT_PREPARATION, (COMPILER_PREPARATION,)),
                        (PACKAGE_PREPARATION, (COMPILER_PREPARATION,))]
    production_plan = [*preparation_plan, *(task for shard in shards for task in
                       [(shard + "-setup", preparation),
                        *((f"{shard}-worker-{index}", (shard + "-setup",)) for index in range(1, 11))])]
    expected_plans = {
        "lint-production": production_plan,
        "lint-production-1": [(shards[0], ())],
        "lint": [(name, ordered[max(0, index - 1):index]) for index, name in enumerate(ordered)],
    }
    with tempfile.TemporaryDirectory(prefix="ci-lint-plan-") as temporary:
        root = Path(temporary)
        with (patch(__name__ + ".ROOT", root),
              patch.dict(os.environ, {"OURO1_COMPILER": "", "GITHUB_ACTIONS": "false"}),
              patch(__name__ + ".CheckoutSnapshot") as snapshot,
              patch(__name__ + ".preparation_workspace", return_value=root),
              patch(__name__ + ".available_memory_mib", return_value=61440),
              patch(__name__ + ".run_tasks", return_value=({}, {})) as run):
            for profile in ("nightly", "manual"):
                for group, expected in expected_plans.items():
                    snapshot.reset_mock()
                    selected = select_group(all_gates, profile, group)
                    schedule_gates(selected, out=root, profile=profile, group=group, jobs=20, fail_fast=False)
                    actual = [(task.name, task.dependencies) for task in run.call_args.args[0]]
                    if (actual != expected or snapshot.called != (group == "lint-production")
                            or run.call_args.kwargs["jobs"] != 20):
                        failures.append(f"{profile} {group} changed its lint execution plan")
                    for task in run.call_args.args[0]:
                        if "-worker-" in task.name and (task.max_jobs != 1 or task.memory_for(1) != 3072):
                            failures.append(f"{task.name} did not reserve one CPU slot and 3072 MiB")
            with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
                selected = select_group(all_gates, "manual", "lint-production")
                schedule_gates(selected, out=root, profile="manual", group="lint-production", jobs=20, fail_fast=False)
                if [(task.name, task.dependencies) for task in run.call_args.args[0]] != [
                        *preparation_plan, *((shard, preparation) for shard in shards)]:
                    failures.append("hosted lint changed its four production shards")
            manifest_gates = [gate for gate in all_gates if gate.name in {"ergonomics", "imports"}]
            for hosted, expected in (("false", 6144), ("true", 3584)):
                with patch.dict(os.environ, {"GITHUB_ACTIONS": hosted}):
                    schedule_gates(manifest_gates, out=root, profile="manual", group="tests", jobs=20, fail_fast=False)
                    if any(task.memory_for(2) != expected for task in run.call_args.args[0]):
                        failures.append(f"Smith manifest gates reserved incorrect two-worker memory on hosted={hosted}")
    return failures


def lint_worker_contract_failures(all_gates: Sequence[Gate]) -> list[str]:
    import contextlib
    import io
    from collections import Counter
    from itertools import count
    from threading import Barrier
    from unittest.mock import patch

    failures = []
    group = "lint-production"
    selected = select_group(all_gates, "manual", group)
    names = [gate.name for gate in selected]
    sources = [f"sample-{index}.ouro" for index in range(67)]
    with tempfile.TemporaryDirectory(prefix="ci-lint-workers-") as temporary:
        root = Path(temporary).resolve()
        with (patch(__name__ + ".ROOT", root), patch(__name__ + ".rel", bind_relative_path(root)),
              patch.dict(os.environ, {"OURO1_COMPILER": "", "GITHUB_ACTIONS": "false"}),
              patch(__name__ + ".CheckoutSnapshot") as snapshot,
              patch(__name__ + ".preparation_workspace", return_value=root),
              patch(__name__ + ".copy_prepared_compiler"), patch(__name__ + ".copy_prepared_tool"),
              patch(__name__ + ".available_memory_mib", return_value=9216),
              patch("ouro_build.cache_access", side_effect=lambda *_args, **_kwargs: contextlib.nullcontext()),
              contextlib.redirect_stdout(io.StringIO())):
            snapshot.return_value.copy_to.side_effect = lambda path, **_kwargs: path.mkdir()
            for jobs, fault in ((1, False), (20, False), (1, True), (20, True)):
                out = root / f"out-{jobs}-{int(fault)}"
                rendezvous = Barrier(3)
                arrivals = count()
                visits: dict[str, list[str]] = {}
                sandboxes: dict[str, tuple[str, str, str]] = {}

                def mock_gate(gate, *, out, workspace, allocation, visits=visits, sandboxes=sandboxes,
                              jobs=jobs, arrivals=arrivals, rendezvous=rendezvous, fault=fault):
                    started = time.perf_counter()
                    env = env_for(gate, out, workspace, allocation)
                    stage = env.get(LINT_STAGE_ENV)
                    status = 0
                    if stage:
                        ready = Path(env["LINT_SUITE_OUT"]) / "production/.ready"
                        if stage == "setup":
                            ready.parent.mkdir(parents=True)
                            ready.touch()
                        else:
                            if not ready.is_file() or allocation.jobs != 1 or allocation.memory_mib != 3072:
                                raise AssertionError("lint worker lost its preparation or resource lease")
                            parent, parents = map(int, gate.cmd[-1].partition("=")[2].split("/"))
                            part, parts = map(int, env[LINT_SUBSHARD_ENV].split("/"))
                            files = sources[parent - 1::parents][part - 1::parts]
                            visits[gate.name] = files
                            sandboxes[gate.name] = (env["OURO_BUILD_DIR"], env["OURO_CACHE_DIR"], env["TMPDIR"])
                            (Path(env["TMPDIR"]) / "worker.out").write_text(gate.name, encoding="utf-8")
                            if jobs == 20 and next(arrivals) < 3:
                                rendezvous.wait(timeout=5)
                            status = int(fault and sources[13] in files)
                    log = out / gate.name / "gate.log"
                    log.parent.mkdir(parents=True)
                    diagnostic = f"denied {sources[13]}\n" if status else ""
                    log.write_text(f"mock gate {gate.name}\n{diagnostic}", encoding="utf-8")
                    return {"name": gate.name, "returncode": status, "blocking": True, "elapsed_s": 0,
                            "status": "fail" if status else "pass", "jobs": allocation.jobs,
                            "memory_mib": allocation.memory_mib, "workspace": rel(workspace), "log": rel(log),
                            "process_started_s": started, "process_finished_s": time.perf_counter()}

                with patch(__name__ + ".run_gate", side_effect=mock_gate):
                    completed, stats = schedule_gates(selected, out=out, profile="manual", group=group,
                                                        jobs=jobs, fail_fast=False)
                if ([name for name in completed if name in names] != names
                        or Counter(path for files in visits.values() for path in files) != Counter(sources)
                        or [name for name in names if completed[name]["returncode"]] != ([names[1]] if fault else [])):
                    failures.append(f"local lint changed production coverage, order, or verdict at {jobs} jobs")
                    continue
                if (stats.get("peak_lint_workers") != (1 if jobs == 1 else 3)
                        or stats["peak_jobs"] > jobs or stats["peak_memory_mib"] > 9216):
                    failures.append(f"local lint ignored the shared worker budget at {jobs} jobs")
                if (len({completed[name]["workspace"] for name in names}) != len(names)
                        or any(len(set(paths)) != len(visits) for paths in zip(*sandboxes.values(), strict=True))):
                    failures.append(f"local lint shared a writable path at {jobs} jobs")
                for name in names:
                    row = completed[name]
                    expected_workers = [f"{name}-worker-{part}" for part in range(1, (1 if jobs == 1 else 2) + 1)]
                    log = (out / name / "gate.log").read_text(encoding="utf-8")
                    if (row["lint_workers_not_run"] or [worker["name"] for worker in row["lint_workers"]] != expected_workers
                            or any(worker["workspace"] != row["workspace"] for worker in row["lint_workers"])
                            or log.count(f"denied {sources[13]}\n") != int(fault and name == names[1])):
                        failures.append(f"{name} lost ordered worker evidence at {jobs} jobs")
    return failures


def preparation_contract_failures() -> list[str]:
    from unittest.mock import patch

    failures = []
    with tempfile.TemporaryDirectory(prefix="ci-prepare-") as temporary:
        root = Path(temporary).resolve()
        source = root / "frozen"
        source.mkdir()
        tracked = source / "input.txt"
        tracked.write_text("first", encoding="utf-8")
        with (patch("local_scheduler.subprocess.check_output", return_value=b"input.txt\0"),
              patch(__name__ + ".ROOT", root), patch.dict(os.environ, {"OURO_CACHE": "1"})):
            snapshot = CheckoutSnapshot(source)
            initial = preparation_workspace(snapshot)
            if initial == source or preparation_workspace(snapshot) != initial:
                failures.append("unchanged inputs did not reuse local preparation")
            (initial / "input.txt").write_text("corrupt", encoding="utf-8")
            if preparation_workspace(snapshot) != source:
                failures.append("local preparation reused corrupted source inputs")
            tracked.write_text("updated", encoding="utf-8")
            updated = preparation_workspace(snapshot)
            if updated in {initial, source} or (updated / "input.txt").read_text(encoding="utf-8") != "updated":
                failures.append("changed inputs did not get a new local preparation")
            with patch.dict(os.environ, {"OURO_CACHE": "0"}):
                if preparation_workspace(snapshot) != source:
                    failures.append("disabled cache still reused local preparation")
    tasks = [Task("producer", max_jobs=6, memory_mib=1024, preferred_jobs=4),
             Task("independent", max_jobs=1, memory_mib=1024)]
    for jobs, memory, expected in ((1, 5120, 1), (20, 5120, 4), (20, 3072, 3)):
        result, stats = run_tasks(tasks, jobs=jobs, memory_mib=memory, run=lambda _task, lease: lease)
        if result["producer"].jobs != expected or result["independent"].jobs != 1 or stats["peak_memory_mib"] > memory:
            failures.append("host preparation lost its available workers or exceeded the memory budget")
    if local_gate_lane("fmt", "checks") != local_gate_lane("fix", "checks") or any(
            local_gate_lane(name, "trust") != "trust" for name in NIGHTLY_GROUPS["trust"]):
        failures.append("local execution lanes broke an existing group dependency")
    return failures


def env_for(gate: Gate, out: Path, workspace: Path, allocation: Allocation) -> dict[str, str]:
    env = os.environ.copy()
    env.pop(LINT_STAGE_ENV, None)
    env.pop(LINT_SUBSHARD_ENV, None)
    env.update(allocation.environment())
    env.setdefault("PYTHON", Path(sys.executable).as_posix())
    env.setdefault("OURO_CI", "1")
    env.setdefault("OURO_REPRODUCIBLE", "1")
    env.setdefault("OURO_PACK_STRICT", "1")
    if workspace != ROOT:
        env.setdefault("SOURCE_DATE_EPOCH", "0")
        if gate.name.startswith("compiler-checking-"):
            env.pop("OURO1_COMPILER", None)
    for key, path in (("OURO_ROOT", ""), ("OURO_CACHE_DIR", "_cache/ouro"),
                      ("OURO_BUILD_DIR", "_build"), ("OURO_C_BUILD_DIR", "_build/c")):
        value = (workspace / path).as_posix()
        if workspace == ROOT:
            env.setdefault(key, value)
        else:
            env[key] = value
    for k, v in gate.env:
        env[k] = (workspace / v).as_posix() if v.startswith("_build/") else v
    env["OURO_CI_GATE_NAME"] = gate.name
    env["OURO_CI_GATE_OUT"] = out.as_posix()
    return env


def run_gate(gate: Gate, *, out: Path, workspace: Path, allocation: Allocation) -> dict[str, Any]:
    started = time.perf_counter()
    gate_dir = out / gate.name
    gate_dir.mkdir(parents=True, exist_ok=True)
    log = gate_dir / "gate.log"
    env = env_for(gate, out, workspace, allocation)
    measure_shard = gate.name.startswith("compiler-checking-")
    peak_rss_kib = 0
    command = gate.cmd
    if command[0] == "sh" and shutil.which("sh") is None:
        from ourosmith.host import shell

        executable = shell(search_path=False)
        command = [str(executable), *command[1:]]
        env["PATH"] = os.pathsep.join([str(executable.parent), env.get("PATH", "")])
    print(f"CI_GATE_START {gate.name} cmd={shlex.join(gate.cmd)}", flush=True)
    with log.open("w", encoding="utf-8") as f:
        p = subprocess.Popen(command, cwd=workspace, env=env, text=True, stdout=f, stderr=subprocess.STDOUT)
        process_started = time.perf_counter()
        last_heartbeat = time.perf_counter()
        last_fixture_progress: tuple[tuple[str, ...], tuple[str, ...]] | None = None
        last_source_phase: str | None = None
        last_phase_check = started
        next_memory_sample = started
        while p.poll() is None:
            now = time.perf_counter()
            if measure_shard and now >= next_memory_sample:
                from memory_watch import tree_rss_kb

                try:
                    peak_rss_kib = max(peak_rss_kib, tree_rss_kb(p.pid))
                except OSError:
                    pass
                next_memory_sample = now + 2.0
            if gate.name == f"compiler-checking-{COMPILER_SHARDS}" and now - last_phase_check >= 2.0:
                marker = workspace / "_build/source_spans.progress"
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
        process_finished = time.perf_counter()
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
        "workspace": rel(workspace),
        "jobs": allocation.jobs,
        "memory_mib": allocation.memory_mib,
        **({"process_started_s": process_started, "process_finished_s": process_finished} if LINT_STAGE_ENV in env else {}),
        **({"sampled_peak_rss_mib": round(peak_rss_kib / 1024, 3) if peak_rss_kib else None}
           if measure_shard else {}),
        "log": rel(log),
        "command": gate.cmd,
    }


def copy_prepared_compiler(source: Path, destination: Path) -> None:
    import bootstrap_compiler as bootstrap

    binary = source / "_build/c/ouro1"
    relative_receipt = Path("_build/c/ouro1.bootstrap.json")
    receipt = json.loads((source / relative_receipt).read_text(encoding="utf-8"))
    if not bootstrap.installed_current(binary, source / relative_receipt, receipt["selected"]):
        raise ValueError("shared compiler preparation did not publish complete bootstrap evidence")
    for path in compiler_evidence_paths(source, binary, receipt):
        relative = path.relative_to(source)
        if relative != relative_receipt:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    receipt["work"] = str(destination / Path(receipt["work"]).relative_to(source))
    write_json_atomic(destination / relative_receipt, receipt)
    if not bootstrap.installed_current(destination / binary.relative_to(source),
                                       destination / relative_receipt, receipt["selected"]):
        raise ValueError("isolated compiler copy did not preserve bootstrap evidence")


def compiler_preparation_gate(profile: str) -> Gate:
    from bootstrap_compiler import LOCAL_CACHE_ENV

    return Gate(COMPILER_PREPARATION, [sys.executable, "scripts/ouro_build.py", "build"], (profile,),
                env=((LOCAL_CACHE_ENV, "1"),))


def preparation_workspace(snapshot: CheckoutSnapshot) -> Path:
    from ouro_build import cache_access

    if not bool_env(os.environ.get("OURO_CACHE")):
        return snapshot.source
    key = snapshot.content_key()
    workspace = ROOT / "_build" / "ci-host" / key[:16]
    with cache_access(workspace, exclusive=True):
        if not workspace.exists():
            snapshot.copy_to(workspace)
            (workspace / ".source-key").write_text(key, encoding="ascii")
        if ((workspace / ".source-key").is_file()
                and (workspace / ".source-key").read_text(encoding="ascii") == key
                and snapshot.content_key(workspace) == key):
            return workspace
    return snapshot.source


def copy_prepared_tool(source: Path, target: Path, *, entry: str, compiler: Path,
                       parse_bytes: ImportBytesParser | None = None) -> None:
    from native_tool_build import tool_companions
    from ourosmith.native import receipt_for

    suffix = ".exe" if os.name == "nt" else ""
    binary = source.with_name(source.name + suffix)
    if parse_bytes is None:
        parse_bytes = cached_import_parser()
    receipt, _, sources = receipt_for(binary, entry, compiler, parse_bytes=parse_bytes)
    target.parent.mkdir(parents=True, exist_ok=True)
    for extension in (suffix, ".build.json", ".sources"):
        shutil.copy2(source.with_name(source.name + extension), target.with_name(target.name + extension))
    installed = target.with_name(target.name + suffix)
    if sha256_file(installed) != receipt["binary_sha256"]:
        raise ValueError(f"prepared tool changed during copy: {entry}")
    info = installed.stat()
    newest = max((ROOT / name).stat().st_mtime_ns for name in sources)
    if info.st_mtime_ns < newest:
        os.utime(installed, ns=(info.st_atime_ns, newest))
    for companion, name in tool_companions(entry):
        copy_prepared_tool(source.parent / name, target.parent / name,
                           entry=companion, compiler=compiler, parse_bytes=parse_bytes)


def local_gate_lane(name: str, owner: str) -> str:
    if owner == "checks" and name in LOCAL_CHECK_LANES:
        return "checks-" + LOCAL_CHECK_LANES[name]
    return owner


def peak_lint_workers(workers: Sequence[dict]) -> int:
    events = [(row[edge], delta) for row in workers
              if row["finished_s"] > row["started_s"]
              for edge, delta in (("started_s", 1), ("finished_s", -1))]
    peak = active = 0
    for _, delta in sorted(events):
        active += delta
        peak = max(peak, active)
    return peak


def lint_gate_result(gate: Gate, workers: Sequence[str], results: dict, out: Path) -> dict | None:
    setup = results.get(gate.name + "-setup")
    if setup is None:
        return None
    completed = [results[name] for name in workers if name in results]
    missing = [name for name in workers if name not in results]
    codes = [setup["returncode"], *(row["returncode"] for row in completed)]
    returncode = next((code for code in codes if code not in (0, 1)), int(any(codes)))
    if not returncode and missing:
        return None
    log = out / gate.name / "gate.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("wb") as stream:
        for row in [setup, *completed]:
            stream.write(f"\n=== {row['name']} ===\n".encode())
            with (out / row["name"] / "gate.log").open("rb") as source:
                shutil.copyfileobj(source, stream)
    finished = max(row["finished_s"] for row in [setup, *completed])
    elapsed = finished - setup["started_s"]
    peak = peak_lint_workers(completed)
    row = {
        **setup,
        "name": gate.name,
        "command": gate.cmd,
        "log": rel(log),
        "status": "fail" if returncode else "pass",
        "returncode": returncode,
        "elapsed_s": round(elapsed, 6),
        "finished_s": finished,
        "jobs": max(setup["jobs"], peak),
        "memory_mib": max(setup["memory_mib"], peak * SHARD_MEMORY_MIB),
        "lint_workers": completed,
        "lint_workers_not_run": missing,
    }
    print(f"CI_GATE_DONE {gate.name} status={row['status']} rc={returncode} elapsed_s={elapsed:.3f} log={rel(log)}",
          flush=True)
    return row


def schedule_gates(selected: Sequence[Gate], *, out: Path, profile: str, group: str | None,
                   jobs: int, fail_fast: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    if profile in {"nightly", "manual"} and group == "lint-production":
        # The aggregate selects shards that each own a checkout.
        group = None
    owners = {name: owner for owner, names in PROFILE_GROUPS.get(profile, {}).items() for name in names}
    groups = {gate.name: group or local_gate_lane(gate.name, owners.get(gate.name, "bootstrap")) for gate in selected}
    workspaces = dict.fromkeys(groups.values(), ROOT)
    snapshot = None
    if len(workspaces) > 1:
        build_dir = ROOT / "_build"
        build_dir.mkdir(exist_ok=True)
        workspace_root = Path(tempfile.mkdtemp(prefix="ci-", dir=build_dir))
        frozen = workspace_root / "source"
        CheckoutSnapshot(ROOT).copy_to(frozen, git_metadata=True)
        snapshot = CheckoutSnapshot(frozen)
        workspaces = {name: workspace_root / name for name in workspaces}

    tasks = []
    previous = {}
    by_name = {gate.name: gate for gate in selected}
    shard_names = {gate.name for gate in selected if gate.name.startswith("compiler-checking-")}
    compiler_users = {gate.name for gate in selected if gate.name in LOCAL_COMPILER_GATES} if snapshot else set()
    runner_users = compiler_users & (shard_names | {"test", "runtime-io", "samples-1", "samples-2"})
    collector_users = runner_users | (compiler_users & {"parity"})
    lint_users = set()
    if not os.environ.get("OURO1_COMPILER"):
        lint_users = {name for name in compiler_users if name.startswith("lint-production-")}
    hosted = os.environ.get("GITHUB_ACTIONS") == "true"
    memory_mib = available_memory_mib()
    lint_parts: dict[str, tuple[str, ...]] = {}
    if lint_users and not hosted:
        capacity = jobs if memory_mib is None else min(jobs, memory_mib // SHARD_MEMORY_MIB)
        # A second wave can fill slots as faster workers finish.
        parts = (1 if capacity <= 1 else
                 min(128, (2 * capacity + len(lint_users) - 1) // len(lint_users)))
        lint_parts = {gate.name: tuple(f"{gate.name}-worker-{index}" for index in range(1, parts + 1))
                      for gate in selected if gate.name in lint_users}
    lint_setups = {name + "-setup": name for name in lint_parts}
    lint_workers = {worker: (name, index, len(workers)) for name, workers in lint_parts.items()
                    for index, worker in enumerate(workers, 1)}
    tool_users = {COLLECTOR_PREPARATION: collector_users, TEST_RUNNER_PREPARATION: runner_users,
                  LINT_PREPARATION: lint_users, PACKAGE_PREPARATION: lint_users}
    preparations = {}
    if compiler_users:
        prepared = preparation_workspace(snapshot)
        build_gate = compiler_preparation_gate(profile)
        preparations[build_gate.name] = build_gate
        tasks.append(Task(build_gate.name, base_memory_mib=2560, memory_mib=512, preferred_jobs=6))
        for key, users in tool_users.items():
            if users:
                entry, binary, cache_name = HOST_TOOLS[key]
                preparations[key] = Gate(key, [sys.executable, "scripts/native_tool_build.py", entry,
                                              f"_build/c/{binary}", "--compiler", str(frozen / "_build/c/ouro1")],
                                         (profile,), env=(("OURO_CACHE_DIR", f"_cache/{cache_name}"),))
                tasks.append(Task(key, (COMPILER_PREPARATION,), base_memory_mib=2560, memory_mib=512, preferred_jobs=4))
    for gate in selected:
        owner = groups[gate.name]
        dependencies = previous.get(owner, ())
        if gate.name in compiler_users:
            dependencies = (*dependencies, COMPILER_PREPARATION)
        dependencies = (*dependencies, *(key for key, users in tool_users.items() if gate.name in users))
        if gate.name in lint_parts:
            setup = gate.name + "-setup"
            tasks.append(Task(setup, dependencies, max_jobs=1, memory_mib=SHARD_MEMORY_MIB))
            tasks.extend(Task(worker, (setup,), max_jobs=1, memory_mib=SHARD_MEMORY_MIB)
                         for worker in lint_parts[gate.name])
            previous[owner] = lint_parts[gate.name]
            continue
        if gate.name in LOCAL_LIGHTWEIGHT_GATES:
            task = Task(gate.name, dependencies, max_jobs=1, memory_mib=256)
        elif gate.name in shard_names:
            task = Task(gate.name, dependencies, max_jobs=1, memory_mib=SHARD_MEMORY_MIB)
        elif not hosted and gate.name in {"compiler-scale", "compiler-depth"}:
            # The probe driver pins the process tree to one CPU.
            from kernel_scale import MEMORY_MIB

            task = Task(gate.name, dependencies, max_jobs=1, memory_mib=MEMORY_MIB)
        elif not hosted and gate.name in {"ergonomics", "imports"}:
            from ourosmith.native_inputs import MANIFEST_BATCH_MEMORY_MIB

            task = Task(gate.name, dependencies, memory_mib=MANIFEST_BATCH_MEMORY_MIB)
        elif sys.platform == "linux" and gate.name == "analyze-precision":
            from analyze_core_checks import POOL_CONTROLLER_MEMORY_MIB, POSIX_WORKER_MEMORY_MIB

            task = Task(gate.name, dependencies, max_jobs=2,
                        base_memory_mib=POOL_CONTROLLER_MEMORY_MIB, memory_mib=POSIX_WORKER_MEMORY_MIB)
        elif (hosted and profile == "pr" and group == "smith" and gate.name == "ouro-smith"
              and os.environ.get("GITHUB_EVENT_NAME") == "pull_request"
              and jobs == 2 and memory_mib is not None and memory_mib >= 4096):
            # Each Smith worker reserves 2048 MiB. One slot must still fit 3072 MiB preparation.
            task = Task(gate.name, dependencies, base_memory_mib=2048, memory_mib=1024)
        else:
            serial = not hosted and gate.name in LOCAL_SERIAL_BUILD_GATES
            task = Task(gate.name, dependencies, max_jobs=1 if serial else None,
                        base_memory_mib=2560, memory_mib=512)
        tasks.append(task)
        previous[owner] = (gate.name,)

    schedule_started = time.perf_counter()

    def run_lint_stage(gate: Gate, workspace: Path, allocation: Allocation) -> dict[str, Any]:
        row = run_gate(gate, out=out, workspace=workspace, allocation=allocation)
        row["started_s"] = row.pop("process_started_s") - schedule_started
        row["finished_s"] = row.pop("process_finished_s") - schedule_started
        return row

    def run(task: Task, allocation: Allocation) -> dict[str, Any]:
        if task.name in preparations:
            from ouro_build import cache_access

            with cache_access(prepared / "_build" / task.name, exclusive=True):
                row = run_gate(preparations[task.name], out=out, workspace=prepared, allocation=allocation)
                if row["status"] == "pass" and prepared != frozen:
                    if task.name == COMPILER_PREPARATION:
                        copy_prepared_compiler(prepared, frozen)
                    else:
                        entry, binary, _ = HOST_TOOLS[task.name]
                        copy_prepared_tool(prepared / "_build/c" / binary, frozen / "_build/c" / binary,
                                           entry=entry, compiler=frozen / "_build/c/ouro1")
            return row
        if task.name in lint_workers:
            name, index, count = lint_workers[task.name]
            gate = by_name[name]
            workspace = workspaces[groups[name]]
            worker_path = f"{dict(gate.env)['LINT_SUITE_OUT']}/workers/{index}"
            temp_path = f"{worker_path}/scratch"
            (workspace / temp_path).mkdir(parents=True)
            gate = replace(gate, name=task.name,
                           env=(*gate.env, ("OURO_CI_PREPARED_LINT", "1"), (LINT_STAGE_ENV, "worker"),
                                (LINT_SUBSHARD_ENV, f"{index}/{count}"),
                                ("OURO_BUILD_DIR", f"{worker_path}/build"),
                                ("OURO_CACHE_DIR", f"{worker_path}/cache"),
                                ("TMPDIR", temp_path), ("TMP", temp_path), ("TEMP", temp_path)))
            return run_lint_stage(gate, workspace, allocation)
        setup_started = time.perf_counter()
        source_gate = lint_setups.get(task.name, task.name)
        workspace = workspaces[groups[source_gate]]
        if snapshot is not None and not workspace.exists():
            snapshot.copy_to(workspace, git_metadata=True)
        gate = by_name[source_gate]
        if source_gate in compiler_users and not (workspace / "_build/c/ouro1").is_file():
            copy_prepared_compiler(frozen, workspace)
        gate_environment = dict(gate.env)
        destinations = {COLLECTOR_PREPARATION: "_build/c", LINT_PREPARATION: "_build/c"}
        if source_gate in runner_users:
            destinations[TEST_RUNNER_PREPARATION] = (gate_environment.get("TEST_SUITE_OUT")
                                                      or gate_environment.get("SAMPLES_SUITE_OUT")
                                                      or gate_environment["RUNTIME_IO_OUT"])
            gate = replace(gate, env=(*gate.env, ("OURO_CI_PREPARED_TEST", "1")))
        if source_gate in lint_users:
            destinations[PACKAGE_PREPARATION] = gate_environment["LINT_SUITE_OUT"]
            gate = replace(gate, env=(*gate.env, ("OURO_CI_PREPARED_LINT", "1")))
        for key, users in tool_users.items():
            if source_gate in users:
                entry, binary, _ = HOST_TOOLS[key]
                target = workspace / destinations[key] / binary
                suffix = ".exe" if os.name == "nt" else ""
                if key != COLLECTOR_PREPARATION or not target.with_name(binary + suffix).is_file():
                    copy_prepared_tool(frozen / "_build/c" / binary, target,
                                       entry=entry, compiler=workspace / "_build/c/ouro1")
        setup_s = round(time.perf_counter() - setup_started, 6)
        if task.name in lint_setups:
            gate = replace(gate, name=task.name, env=(*gate.env, (LINT_STAGE_ENV, "setup")))
            row = run_lint_stage(gate, workspace, allocation)
        else:
            row = run_gate(gate, out=out, workspace=workspace, allocation=allocation)
        if snapshot is not None:
            row["workspace_setup_s"] = setup_s
        return row

    def blocking_failure(result: dict[str, Any]) -> bool:
        return result["blocking"] and result["status"] == "fail"

    completed, stats = run_tasks(tasks, jobs=jobs, memory_mib=memory_mib,
                                 run=run, stop=blocking_failure if fail_fast else None,
                                 failed=lambda row: (row["name"] in preparations or row["name"] in lint_setups)
                                 and blocking_failure(row))
    if lint_parts:
        stats["peak_lint_workers"] = peak_lint_workers([completed[name] for name in lint_workers if name in completed])
        for name, workers in lint_parts.items():
            row = lint_gate_result(by_name[name], workers, completed, out)
            if row is not None:
                completed[name] = row
    return completed, stats


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", choices=[*PROFILE_GROUPS, "bootstrap"], default="pr")
    ap.add_argument("--group", default=None, help="run one complete profile partition in an isolated checkout")
    ap.add_argument("--out", default=None)
    ap.add_argument("--jobs", type=int, help="total local CPU slots (default: OURO_JOBS or 20)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--list-groups", action="store_true", help="print the complete profile group list as JSON")
    ap.add_argument("--self-test", action="store_true", help="check PR/nightly partitions and hosted path-selection invariants")
    ap.add_argument("--select-paths", action="store_true", help="write fail-closed hosted job selection from a commit diff")
    ap.add_argument("--select-dependencies", action="store_true", help="select workflow policy and dependency manifest checks")
    ap.add_argument("--full", action="store_true", help="select all jobs for push, merge queue, or manual validation")
    ap.add_argument("--changed-paths-json", default=None, help="recompute affected PR gates from the Paths job output")
    ap.add_argument("--selection-key", default=None, help="require exactly the producer's complete routing decision")
    ap.add_argument("--fail-fast", action="store_true", help="stop a group after its first blocking failure")
    ap.add_argument("--base", default=None, help="base commit SHA for --select-paths")
    ap.add_argument("--head", default=None, help="head commit SHA for --select-paths")
    ap.add_argument("--pr-head", help="source commit SHA for dependency review")
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
    if args.jobs is not None and args.jobs < 1:
        ap.error("--jobs must be a positive integer")

    if args.select_dependencies:
        if (args.select_paths or args.compiler_artifact or args.compiler_sha256 or args.full or args.group
                or args.out or args.jobs is not None or args.list or args.list_groups or args.self_test or args.with_bootstrap_evidence
                or args.changed_paths_json is not None or args.selection_key or args.fail_fast or args.profile != "pr"):
            ap.error("--select-dependencies cannot be combined with execution or path-selection options")
        if args.base is None or args.head is None or args.pr_head is None:
            ap.error("--select-dependencies requires --base, --head, and --pr-head")
        return run_dependency_selection(args.base, args.head, args.pr_head, args.github_output or os.environ.get("GITHUB_OUTPUT", ""))
    if args.pr_head is not None:
        ap.error("--pr-head requires --select-dependencies")
    if args.compiler_artifact:
        if args.group or args.out or args.jobs is not None or args.list or args.list_groups or args.self_test or args.select_paths or args.base or args.head or args.github_output or args.with_bootstrap_evidence or args.full or args.changed_paths_json is not None or args.selection_key or args.fail_fast:
            ap.error("--compiler-artifact cannot be combined with gate or path-selection options")
        if (args.compiler_artifact == "import") != bool(args.compiler_sha256):
            ap.error("--compiler-sha256 is required exactly for compiler import")
        return run_compiler_artifact(args.compiler_artifact, args.artifact, args.compiler_sha256)
    if args.compiler_sha256:
        ap.error("--compiler-sha256 requires --compiler-artifact import")
    if args.select_paths:
        if args.group is not None or args.out or args.jobs is not None or args.list or args.list_groups or args.self_test or args.with_bootstrap_evidence or args.changed_paths_json is not None or args.selection_key or args.fail_fast:
            ap.error("--select-paths cannot be combined with execution options")
        if args.base is None or args.head is None:
            ap.error("--select-paths requires --base and --head")
        return run_path_selection(
            args.base,
            args.head,
            args.github_output or os.environ.get("GITHUB_OUTPUT", ""),
            full=args.full,
        )
    if args.base or args.head or args.github_output or (args.full and args.changed_paths_json is None):
        ap.error("diff options require --select-paths; --full can also verify a complete PR selection")
    if args.changed_paths_json is not None and (args.profile != "pr" or not args.group or args.self_test or args.list_groups or args.with_bootstrap_evidence):
        ap.error("--changed-paths-json requires --profile pr --group and cannot change other profiles")
    if (args.changed_paths_json is not None) != bool(args.selection_key):
        ap.error("--changed-paths-json and --selection-key must be supplied together")
    all_gates = gates()
    if args.self_test:
        if args.group is not None or args.out or args.jobs is not None or args.list or args.list_groups or args.with_bootstrap_evidence:
            ap.error("--self-test cannot be combined with execution options")
        return run_self_tests(all_gates)
    try:
        for profile, groups in PROFILE_GROUPS.items():
            validate_groups(all_gates, profile, groups)
    except ValueError as exc:
        print(f"CI_GATE: FAIL {exc}", file=sys.stderr)
        return 2
    if args.list_groups:
        if args.group is not None or args.out or args.jobs is not None or args.list or args.with_bootstrap_evidence:
            ap.error("--list-groups cannot be combined with execution options")
        if args.profile not in PROFILE_GROUPS:
            ap.error(f"profile {args.profile} has no group partition")
        print(json.dumps(list(PROFILE_GROUPS[args.profile])))
        return 0
    if args.group and args.with_bootstrap_evidence:
        ap.error("--group cannot be combined with --with-bootstrap-evidence")
    if args.changed_paths_json is not None:
        groups = ROUTED_PR_GROUPS if args.full else PULL_REQUEST_GROUPS
        if args.group not in groups:
            ap.error(f"unknown group {args.group!r} for profile {args.profile}")
        try:
            selection = selection_from_json(args.changed_paths_json, full=args.full)
        except (ValueError, TypeError) as exc:
            ap.error(f"invalid changed paths: {exc}")
        if selection_key(selection) != args.selection_key:
            ap.error("routing decision differs from the Paths job; refusing incomplete matrix coverage")
        names = set(groups[args.group]).intersection(selection.gates)
        profile = "nightly" if args.group in PR_FALLBACK_LINT_GROUPS else args.profile
        selected = [gate for gate in all_gates if profile in gate.profiles and gate.name in names]
        if not selected:
            ap.error("selected PR group has no affected gates; refusing an empty green job")
        if any(gate.name in PATH_INPUT_GATES for gate in selected):
            sources = selection.lint_sources
            if not sources:
                ap.error("lint-changed was selected without changed production Ouro sources")
            selected = [replace(gate, cmd=[*gate.cmd, *sources]) if gate.name in PATH_INPUT_GATES else gate
                        for gate in selected]
        skipped: list[Gate] = []
    else:
        if args.group is not None:
            if args.group not in PROFILE_GROUPS.get(args.profile, {}) and not (
                args.profile in {"nightly", "manual"} and args.group in {"lint", "lint-production"}
            ):
                ap.error(f"unknown group {args.group!r} for profile {args.profile}")
            selected = select_group(all_gates, args.profile, args.group)
        else:
            selected = [gate for gate in all_gates if args.profile in gate.profiles]
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

    try:
        jobs = bounded_jobs(args.jobs) if args.jobs is not None else configured_jobs()
    except ValueError as exc:
        ap.error(str(exc))
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
    skips = [{"name": gate.name, "blocking": gate.blocking, "status": "skip",
              "reason": "requires --changed-paths-json"} for gate in skipped]
    for skip in skips:
        print(f"CI_GATE_SKIP {skip['name']} reason={skip['reason']}")
    completed, scheduler = schedule_gates(selected, out=out, profile=args.profile, group=args.group,
                                          jobs=jobs, fail_fast=args.fail_fast)
    results = [completed[gate.name] for gate in selected if gate.name in completed]
    preparation = [completed[name] for name in (COMPILER_PREPARATION, *HOST_TOOLS) if name in completed]
    failures = [row for row in [*preparation, *results] if row["blocking"] and row["status"] == "fail"]
    failed = bool(failures)
    report = {
        "kind": REPORT_KIND,
        "profile": args.profile,
        "group": args.group or "all",
        "pass": not failed,
        "preparation": preparation,
        "gates": results,
        "not_run": [gate.name for gate in selected if gate.name not in completed],
        "blocking_failures": failures,
        "informational_skips": [*skips, *(r for r in results if r.get("status") == "skip")],
        "elapsed_s": round(time.perf_counter() - started, 6),
        "scheduler": scheduler,
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
    if (failed and args.fail_fast and args.changed_paths_json is not None
            and os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("GITHUB_EVENT_NAME") == "pull_request"):
        for failure in failures:
            name = failure["name"]
            if re.fullmatch(r"[a-z0-9-]+", name):
                print(f"::error title=Blocking PR gate::{name}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
