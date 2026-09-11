#!/usr/bin/env python3
"""Local entry point used by GitHub Actions and maintainers.

Profiles are intentionally built from repository-local scripts so that CI never
owns a secret version of the trust policy.
"""
from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from repo_support import bind_relative_path, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
rel = bind_relative_path(ROOT, resolve=True)
REPORT_KIND = "ouro.ci-gate-report.v1"


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
        "parity",
        "fmt",
        "fix",
        "pkg",
        "doc",
        "docs-examples",
        "syntax-quality-firewall",
        "strict-quality-firewall",
        "structural-quality-suite",
        "structural-quality",
        "hygiene",
    ),
    "analysis": (
        "memory-budget",
        "kernel-hardening",
        "compiler-scale",
        "compiler-depth",
        "analyze-precision",
        "c-static-analysis",
        "lint",
        "lsp",
    ),
    "tests": (
        "ergonomics",
        "imports",
        "frontend-security",
        "runtime-io",
        "test",
        "compiler-checking",
        "compiler-boundary",
    ),
    "smith": ("ouro-smith",),
    "samples-1": ("samples-1",),
    "samples-2": ("samples-2",),
}

NIGHTLY_GROUPS: dict[str, tuple[str, ...]] = {
    "checks": tuple("cache-parity-full" if name == "cache-parity-module" else name
                    for name in PR_GROUPS["checks"]),
    "analysis": (*(name for name in PR_GROUPS["analysis"]
                   if name not in {"compiler-scale", "compiler-depth"}), "analyze-production"),
    "tests": (*PR_GROUPS["tests"], "quickstart-smoke"),
    "samples-1": PR_GROUPS["samples-1"],
    "samples-2": PR_GROUPS["samples-2"],
    "kernel": ("compiler-scale", "compiler-depth", "ouro-smith-kernel"),
    # Keep these in one checkout and preserve registry order. Smith must bind
    # its provenance to the tool binaries installed by the stage loop.
    "trust": ("stage-loop-fixpoint-and-generated-drift", "ouro-smith-nightly"),
}
PROFILE_GROUPS = {"pr": PR_GROUPS, "nightly": NIGHTLY_GROUPS}

SHA40 = re.compile(r"[0-9a-fA-F]{40}\Z")
EDITOR_PREFIX = "editors/vscode/"
SITE_PREFIX = "site/"
KERNEL_PREFIXES = (
    "compiler/", "runtime/", "std/", "tests/compiler_", "tests/string_nf_",
    "tests/constructor_", "quality/smith/", "scripts/ourosmith/",
)
KERNEL_PATHS = {
    ".github/workflows/ouro-pr.yml",
    "Ouro.seal",
    "docs/tcb.md",
    "docs/kernel_design.md",
    "quality/kernel_budgets.json",
    "scripts/ci_gate.py",
    "scripts/kernel_hardening_suite.py",
    "scripts/kernel_profile.py",
    "scripts/kernel_profile_test.py",
    "scripts/kernel_scale.py",
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


@dataclass(frozen=True)
class PathSelection:
    mode: str
    core: bool
    kernel: bool
    editor: bool
    dependency: bool
    paths: tuple[str, ...]
    reason: str = ""


def normalize_changed_path(value: str) -> str:
    path = value.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def is_editor_path(path: str) -> bool:
    return path.startswith(EDITOR_PREFIX)


def is_site_path(path: str) -> bool:
    return path.startswith(SITE_PREFIX)


def is_kernel_path(path: str) -> bool:
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
        kernel=True,
        editor=True,
        dependency=True,
        paths=(),
        reason=reason,
    )


def classify_paths(paths: Sequence[str]) -> PathSelection:
    normalized = tuple(normalize_changed_path(path) for path in paths if path)
    if not normalized:
        return full_path_selection("empty diff")
    return PathSelection(
        mode="changed",
        core=any(
            not is_editor_path(path) and not is_site_path(path)
            for path in normalized
        ),
        kernel=any(is_kernel_path(path) for path in normalized),
        editor=any(is_editor_path(path) for path in normalized),
        dependency=any(is_dependency_path(path) for path in normalized),
        paths=normalized,
    )


def changed_paths(base: str, head: str) -> tuple[Optional[list[str]], str]:
    if not SHA40.fullmatch(base) or not SHA40.fullmatch(head):
        return None, "base or head is not a full commit SHA"
    if base == "0" * 40:
        return None, "base SHA is unavailable"
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", "-z", base, head, "--"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
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
        for name in ("core", "kernel", "editor", "dependency"):
            output.write(f"{name}={bool_text(getattr(selection, name))}\n")
        output.write(f"mode={selection.mode}\n")


def run_path_selection(base: str, head: str, github_output: str) -> int:
    paths, reason = changed_paths(base, head)
    selection = full_path_selection(reason) if paths is None else classify_paths(paths)
    details = (
        f"mode={selection.mode} core={bool_text(selection.core)} "
        f"kernel={bool_text(selection.kernel)} editor={bool_text(selection.editor)} "
        f"dependency={bool_text(selection.dependency)} paths={len(selection.paths)}"
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
        Gate("github-workflow-gate", ["sh", "scripts/ouro_repo_gate.sh", "--profile", "workflow-native", "--out", "_build/github_workflow_gate/native-workflow"], ("pr", "nightly", "manual")),
        Gate("github-project-gate", ["sh", "scripts/ouro_repo_gate.sh", "--profile", "project-native", "--out", "_build/github_project_gate/native-project"], ("pr", "nightly", "manual")),
        Gate("api-baseline-drift", [sys.executable, "scripts/api_baseline_regen.py", "--check", "--report", "_build/api_baseline/api-baseline.json"], ("pr", "nightly", "manual")),
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
        Gate("doc", ["sh", "scripts/doc_suite.sh"], ("pr", "nightly", "manual"), env=(("DOC_SUITE_OUT", "_build/doc_suite"),)),
        Gate("lint", ["sh", "scripts/lint_suite.sh"], ("pr", "nightly", "manual"), env=(("LINT_SUITE_OUT", "_build/lint_suite"),)),
        Gate("lsp", ["sh", "scripts/lsp_suite.sh"], ("pr", "nightly", "manual"), env=(("LSP_SUITE_OUT", "_build/lsp_suite"),)),
        Gate("test", ["sh", "scripts/test_suite.sh"], ("pr", "nightly", "manual"), env=(("TEST_SUITE_OUT", "_build/test_suite"),)),
        Gate("compiler-checking", ["sh", "scripts/test_suite.sh", "--compiler-checking"], ("pr", "nightly", "manual", "kernel"), env=(("TEST_SUITE_OUT", "_build/compiler_check_suite"), ("OURO_JOBS", "1"), ("OURO_FRONTEND_JOBS", "1"))),
        Gate("compiler-boundary", ["sh", "scripts/ouro_repo_gate.sh", "--profile", "compiler-boundary", "--out", "_build/compiler_boundary"], ("pr", "nightly", "manual", "kernel")),
        Gate("samples-1", ["sh", "scripts/samples_suite.sh", "--shard=1/2"], ("pr", "nightly", "manual"), env=(("SAMPLES_SUITE_OUT", "_build/samples_suite_1"),)),
        Gate("samples-2", ["sh", "scripts/samples_suite.sh", "--shard=2/2"], ("pr", "nightly", "manual"), env=(("SAMPLES_SUITE_OUT", "_build/samples_suite_2"),)),
        Gate("docs-examples", ["sh", "scripts/ouro_repo_gate.sh", "--profile", "docs-native", "--out", "_build/docs_examples_gate/native-docs"], ("pr", "nightly", "manual")),
        Gate("syntax-quality-firewall", [sys.executable, "scripts/syntax_quality_suite.py"], ("pr", "nightly", "manual", "kernel", "stage-loop")),
        Gate("strict-quality-firewall", [sys.executable, "scripts/strict_quality_firewall.py", "--profile", "release", "--report", "_build/quality/strict-quality-firewall.json", "--sarif", "_build/quality/strict-quality-firewall.sarif", "--migration-report", "_build/quality/migration-report.md"], ("pr", "nightly", "manual", "kernel", "stage-loop")),
        Gate("structural-quality-suite", [sys.executable, "scripts/structural_quality_suite.py"], ("pr", "nightly", "manual", "stage-loop")),
        Gate("structural-quality", [sys.executable, "scripts/strict_quality_firewall.py", "--structural"], ("pr", "nightly", "manual", "stage-loop")),
        Gate("hygiene", ["sh", "scripts/hygiene.sh"], ("pr", "nightly", "manual", "kernel")),
        # Native suites above may rebuild tools. Bind Smith's report to the
        # final installed binaries so validation can reuse this complete run.
        Gate("ouro-smith", [sys.executable, "scripts/ouro_smith.py", "--profile", "pr", "--out", "_build/ci/smith-pr"], ("pr",)),
        Gate("quickstart-smoke", ["sh", "scripts/quickstart_smoke.sh"], ("nightly", "manual")),
        Gate("ouro-smith-kernel", [sys.executable, "scripts/ouro_smith.py", "--profile", "kernel", "--out", "_build/ci/smith-kernel"], ("nightly", "manual", "kernel")),
        Gate("stage-loop-fixpoint-and-generated-drift", [sys.executable, "scripts/generated_artifact_drift_check.py", "--mode", "stage-loop", "--work", "_build/generated_artifact_drift_stage_loop"], ("nightly", "manual", "stage-loop")),
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


def select_group(all_gates: Sequence[Gate], profile: str, group: str) -> list[Gate]:
    names = set(PROFILE_GROUPS[profile][group])
    return [gate for gate in all_gates if profile in gate.profiles and gate.name in names]


def run_self_tests(all_gates: Sequence[Gate]) -> int:
    failures: list[str] = []
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
        workflow = ROOT / ".github/workflows" / ("ouro-pr.yml" if profile == "pr" else "ouro-nightly-full.yml")
        try:
            matrix = re.findall(r"^          - group: ([a-z0-9-]+)$", workflow.read_text(encoding="utf-8"), re.MULTILINE)
        except OSError as exc:
            failures.append(f"cannot read {profile} workflow: {exc}")
        else:
            if matrix != list(groups):
                failures.append(f"hosted {profile} matrix differs from complete group inventory: {matrix}")
    trust = [gate.name for gate in select_group(all_gates, "nightly", "trust")]
    if trust != ["stage-loop-fixpoint-and-generated-drift", "ouro-smith-nightly"]:
        failures.append("nightly must run stage-loop before OuroSmith in the same group")

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
        (("editors/vscode/src/extension.ts", "README.md"), (True, False, True, False)),
        ((".github/workflows/ouro-pr.yml",), (True, True, False, True)),
        ((), (True, True, True, True)),
    )
    for paths, expected in cases:
        selection = classify_paths(paths)
        actual = (selection.core, selection.kernel, selection.editor, selection.dependency)
        if actual != expected:
            failures.append(f"path selection mismatch for {paths}: expected={expected} actual={actual}")

    if failures:
        for failure in failures:
            print(f"CI_GATE_SELFTEST: FAIL {failure}", file=sys.stderr)
        return 1
    print(
        f"CI_GATE_SELFTEST: PASS groups={len(PR_GROUPS)} "
        f"pr_gates={sum(len(names) for names in PR_GROUPS.values())} "
        f"nightly_groups={len(NIGHTLY_GROUPS)} "
        f"nightly_gates={sum(len(names) for names in NIGHTLY_GROUPS.values())} path_cases={len(cases)}"
    )
    return 0


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
    print(f"CI_GATE_START {gate.name} cmd={shlex.join(gate.cmd)}")
    with log.open("w", encoding="utf-8") as f:
        p = subprocess.Popen(gate.cmd, cwd=ROOT, env=env, text=True, stdout=f, stderr=subprocess.STDOUT)
        last_heartbeat = time.perf_counter()
        while p.poll() is None:
            now = time.perf_counter()
            if now - last_heartbeat >= 30.0:
                print(f"CI_GATE_PROGRESS {gate.name} elapsed_s={now - started:.1f} log={rel(log)}")
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
    print(f"CI_GATE_DONE {gate.name} status={status} rc={rc} elapsed_s={time.perf_counter() - started:.3f} log={rel(log)}")
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
    ap.add_argument("--profile", choices=["pr", "nightly", "manual", "kernel", "stage-loop", "bootstrap"], default="pr")
    ap.add_argument("--group", default=None, help="run one complete PR or nightly partition in an isolated checkout")
    ap.add_argument("--out", default=None)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--self-test", action="store_true", help="check PR/nightly partitions and hosted path-selection invariants")
    ap.add_argument("--select-paths", action="store_true", help="write fail-closed hosted job selection from a commit diff")
    ap.add_argument("--base", default=None, help="base commit SHA for --select-paths")
    ap.add_argument("--head", default=None, help="head commit SHA for --select-paths")
    ap.add_argument("--github-output", default=None, help="GitHub output file for --select-paths")
    ap.add_argument(
        "--with-bootstrap-evidence",
        action="store_true",
        help="append the selfhost bootstrap evidence gate to the selected profile",
    )
    args = ap.parse_args(argv)

    all_gates = gates()
    if args.select_paths:
        if args.group is not None or args.out or args.list or args.self_test or args.with_bootstrap_evidence:
            ap.error("--select-paths cannot be combined with execution options")
        if not args.base or not args.head:
            ap.error("--select-paths requires --base and --head")
        return run_path_selection(
            args.base,
            args.head,
            args.github_output or os.environ.get("GITHUB_OUTPUT", ""),
        )
    if args.base or args.head or args.github_output:
        ap.error("--base, --head, and --github-output require --select-paths")
    if args.self_test:
        if args.group is not None or args.out or args.list or args.with_bootstrap_evidence:
            ap.error("--self-test cannot be combined with execution options")
        return run_self_tests(all_gates)
    try:
        for profile, groups in PROFILE_GROUPS.items():
            validate_groups(all_gates, profile, groups)
    except ValueError as exc:
        print(f"CI_GATE: FAIL {exc}", file=sys.stderr)
        return 2
    if args.group is not None and args.group not in PROFILE_GROUPS.get(args.profile, {}):
        ap.error(f"unknown group {args.group!r} for profile {args.profile}")
    if args.group and args.with_bootstrap_evidence:
        ap.error("--group cannot be combined with --with-bootstrap-evidence")
    selected = [g for g in all_gates if args.profile in g.profiles]
    if args.group:
        selected = select_group(all_gates, args.profile, args.group)
    if args.with_bootstrap_evidence and not any(g.name == "selfhost-bootstrap-evidence" for g in selected):
        selected.extend(g for g in all_gates if g.name == "selfhost-bootstrap-evidence")
    if args.list:
        for g in selected:
            print(("BLOCKING" if g.blocking else "INFO") + " " + g.name + " " + shlex.join(g.cmd))
        return 0

    default_out = ROOT / "_build" / "ci" / args.profile
    if args.group:
        default_out /= args.group
    out = Path(args.out) if args.out else default_out
    if not out.is_absolute():
        out = ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    failed = False
    for gate in selected:
        result = run_gate(gate, out=out)
        results.append(result)
        if result["status"] == "fail" and gate.blocking:
            failed = True
            # Continue running remaining gates so the artifact bundle explains as
            # many independent regressions as possible.
    report = {
        "kind": REPORT_KIND,
        "profile": args.profile,
        "group": args.group or "all",
        "pass": not failed,
        "gates": results,
        "blocking_failures": [r for r in results if r.get("blocking") and r.get("status") == "fail"],
        "informational_skips": [r for r in results if r.get("status") == "skip"],
        "elapsed_s": round(time.perf_counter() - started, 6),
        "policy": {
            "blocking": "every registered gate is required; missing tools and nonzero exits fail",
            "reports": "every gate writes a log under the CI output directory; underlying scripts write JSON reports under _build",
            "cache": "restored build/cache data is a speed hint only and is followed by regeneration/recheck/parity gates",
        },
    }
    write_json_atomic(out / "ci-summary.json", report)
    print(
        f"CI_GATE_SUMMARY profile={args.profile} group={args.group or 'all'} "
        f"pass={int(not failed)} gates={len(results)} report={rel(out / 'ci-summary.json')}"
    )
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
