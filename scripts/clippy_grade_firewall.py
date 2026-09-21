#!/usr/bin/env python3
"""Clippy-grade adapter for Ouro source.

Production scans without report/query flags exec `ouro-lint --family semantic`
under the existing 3072 MiB `run_limited` cap. JSON/SARIF, `--print-files`,
`--list-rules`, `--validate-rules`, and fixture `--warn-only` still launch
`ouro-clippy-grade-firewall` directly. The 7200s timeout is a host safety
envelope, not a substitute for making the worker faster.
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]


def _native_env() -> dict[str, str]:
    env = dict(os.environ)
    env["OURO_ROOT"] = ROOT.as_posix()
    env["OURO_REPRODUCIBLE"] = "1"
    return env


def _int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    value = int(raw)
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be in {minimum}..{maximum}")
    return value


def _flag_values(argv: Sequence[str], name: str) -> list[str]:
    values: list[str] = []
    pending = False
    for item in argv:
        if pending:
            values.append(item)
            pending = False
            continue
        if item == name:
            pending = True
            continue
        prefix = name + "="
        if item.startswith(prefix):
            values.append(item[len(prefix):])
    return values


def _has_flag(argv: Sequence[str], name: str) -> bool:
    return name in argv


def _scope_looks_like_tree(argv: Sequence[str]) -> bool:
    scopes = _flag_values(argv, "--scope")
    if len(scopes) != 1:
        return True
    path = Path(scopes[0])
    if not path.is_absolute():
        path = ROOT / path
    return path.is_dir()


def _query_mode(argv: Sequence[str]) -> bool:
    return any(_has_flag(argv, name) for name in
               ("--list-rules", "--validate-rules"))


# Mirrors tools/strict/walk.ouro clippy keep/skip. Explicit files still pass
# through inventory; directory names are not an extra exclusion list.
_CLIPPY_SEMANTIC_FIXTURES = frozenset((
    "samples/bench/synthesis/s01_id.ouro",
    "samples/bench/synthesis/s02_const.ouro",
    "samples/bench/synthesis/s03_const_body.ouro",
    "samples/bench/synthesis/s04_bool.ouro",
    "samples/bench/synthesis/s05_nat.ouro",
    "samples/bench/synthesis/s06_nil.ouro",
    "samples/bench/synthesis/s07_cons.ouro",
    "samples/bench/synthesis/s08_apply.ouro",
    "samples/bench/synthesis/s09_intro3.ouro",
    "samples/bench/synthesis/s10_pair.ouro",
    "samples/bench/synthesis/s11_deep_assumption.ouro",
    "samples/bench/synthesis/s12_global.ouro",
    "samples/bench/synthesis/s13_flip.ouro",
    "samples/bench/synthesis/s14_maybe.ouro",
    "samples/bench/synthesis/s15_intro_ctor.ouro",
    "samples/bench/synthesis/s16_impossible.ouro",
    "samples/bench/synthesis/s17_need_arg.ouro",
    "samples/bench/synthesis/s18_poly2.ouro",
    "samples/bench/synthesis/s19_ho_impossible.ouro",
    "samples/bench/synthesis/s20_mixed.ouro",
    "samples/demo/04_pure_handler.ouro",
    "samples/demo/05_effect_handler.ouro",
    "samples/examples/effect_ask_handler.ouro",
    "samples/examples/effect_ask_io.ouro",
    "samples/examples/effect_demo.ouro",
    "samples/examples/effect_nested_ask.ouro",
    "samples/examples/future/holes_demo.ouro",
    "samples/examples/future/metaprog.ouro",
    "samples/examples/future/synthesis.ouro",
    "samples/examples/handler_demo.ouro",
    "samples/examples/io_handler_do_bind.ouro",
    "samples/tutorial/04_holes.ouro",
    "samples/tutorial/06_effects.ouro",
))
_CLIPPY_EXCLUDE_MARKERS = ("_build/", "quality/fixtures/", "/bad/", "/good/")
_DEFAULT_SCOPES = ["std", "compiler", "tools/analyze", "tools", "samples"]


def _posix_rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _clippy_keep(rel: str, fixtures: bool) -> bool:
    posix = rel.replace("\\", "/")
    if fixtures:
        return True
    if any(marker in posix for marker in _CLIPPY_EXCLUDE_MARKERS):
        return False
    return posix not in _CLIPPY_SEMANTIC_FIXTURES


def _collect_scope(root: Path, scope: Path, fixtures: bool) -> list[str]:
    scope = scope.resolve()
    if scope.is_file():
        if scope.suffix != ".ouro":
            return []
        rel = _posix_rel(root, scope)
        return [rel] if _clippy_keep(rel, fixtures) else []
    if not scope.is_dir():
        raise ValueError(f"scope is not a file or directory: {scope}")
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(scope):
        dirnames[:] = sorted(name for name in dirnames if name not in {".", ".."})
        for name in sorted(filenames):
            if not name.endswith(".ouro"):
                continue
            rel = _posix_rel(root, Path(dirpath) / name)
            if _clippy_keep(rel, fixtures):
                found.append(rel)
    return found


def _collect_clippy_files(argv: Sequence[str]) -> list[str]:
    fixtures = _has_flag(argv, "--include-fixtures")
    scopes = _flag_values(argv, "--scope") or list(_DEFAULT_SCOPES)
    source_root = _option_or(argv, "--source-root", ".")
    root = ROOT.resolve()
    source = Path(source_root)
    if not source.is_absolute():
        source = (root / source).resolve()
    files: list[str] = []
    for scope in scopes:
        path = Path(scope)
        if not path.is_absolute():
            path = root / path
        files.extend(_collect_scope(root, path, fixtures))
    unique = sorted(dict.fromkeys(files))
    kept = [item for item in unique if (root / item).resolve().is_relative_to(source)]
    if not kept:
        raise ValueError("native quality inventory failed: selected no source files")
    return kept


def _option_or(argv: Sequence[str], name: str, fallback: str) -> str:
    values = _flag_values(argv, name)
    return values[-1] if values else fallback


def _without_outputs(argv: Sequence[str]) -> list[str]:
    skip = {"--report", "--sarif"}
    out: list[str] = []
    pending = False
    for item in argv:
        if pending:
            pending = False
            continue
        if item in skip:
            pending = True
            continue
        if item.startswith("--report=") or item.startswith("--sarif="):
            continue
        out.append(item)
    return out


def _finding_sort_key(finding: dict[str, Any]) -> tuple[str, int, int, str]:
    return (str(finding.get("path", "")), int(finding.get("line", 1) or 1),
            int(finding.get("column", 1) or 1), str(finding.get("rule_id", "")))


def _merge_reports(parts: list[dict[str, Any]], *, report: Path, sarif: Path,
                   profile: str, warn_only: bool, source_root: str,
                   scopes: list[str]) -> tuple[dict[str, Any], int]:
    findings: list[dict[str, Any]] = []
    issues: list[str] = []
    files = 0
    family_count = 0
    rule_count = 0
    for part in parts:
        part_findings = part.get("findings", [])
        part_issues = part.get("validation_issues", [])
        if not isinstance(part_findings, list) or not isinstance(part_issues, list):
            raise ValueError("shard report is missing findings or validation_issues")
        findings.extend(item for item in part_findings if isinstance(item, dict))
        issues.extend(str(item) for item in part_issues)
        files += int(part.get("files_scanned", 0) or 0)
        family_count = max(family_count, int(part.get("family_count", 0) or 0))
        rule_count = max(rule_count, int(part.get("rule_count", 0) or 0))
    findings.sort(key=_finding_sort_key)
    visible = [item for item in findings if not item.get("suppressed_by")]
    blocking = [item for item in findings
                if str(item.get("severity", "")) in {"deny", "fatal"}
                and not item.get("suppressed_by")]
    fatal = any(str(item.get("severity", "")) == "fatal"
                or str(item.get("severity", "")) not in
                {"allow", "info", "warn", "deny", "fatal"}
                for item in findings)
    passed = not blocking and not issues
    advisory = warn_only and not fatal and not issues
    payload = {
        "diagnostics_blocking": len(blocking),
        "diagnostics_total": len(visible),
        "family_count": family_count,
        "findings": findings,
        "files_scanned": files,
        "kind": "ouro.clippy-grade-firewall-report.v1",
        "pass": passed,
        "profile": profile,
        "rule_count": rule_count,
        "scopes": scopes,
        "source_root": source_root,
        "validation_issues": issues,
        "warn_only": warn_only,
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    sarif_results = []
    for finding in visible:
        sarif_results.append({
            "ruleId": finding.get("rule_id", ""),
            "level": "error" if finding.get("severity") in {"deny", "fatal"} else "warning",
            "message": {"text": str(finding.get("message", ""))},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": str(finding.get("path", ""))},
                    "region": {
                        "startLine": int(finding.get("line", 1) or 1),
                        "startColumn": int(finding.get("column", 1) or 1),
                    },
                }
            }],
        })
    sarif.write_text(json.dumps({
        "version": "2.1.0",
        "runs": [{
            "properties": {"sourceRoot": source_root},
            "results": sarif_results,
            "tool": {"driver": {"name": "ouro-clippy-grade-firewall"}},
        }],
    }, indent=2) + "\n", encoding="utf-8")
    print(
        "CLIPPY_GRADE_FIREWALL: "
        + ("PASS" if passed else "FAIL")
        + f" profile={profile} files={files} blocking={len(blocking)}"
        + f" rules={rule_count} report={report.as_posix() if report.is_absolute() else Path(os.path.relpath(report, ROOT)).as_posix()}",
        flush=True,
    )
    return payload, 0 if passed or advisory else 1


def _print_findings(findings: list[dict[str, Any]]) -> None:
    for finding in findings:
        if finding.get("suppressed_by"):
            continue
        path = finding.get("path", "")
        line = finding.get("line", 1)
        column = finding.get("column", 1)
        code = finding.get("rule_id", "")
        message = finding.get("message", "")
        fix = finding.get("fix", "")
        print(f"{path}:{line}:{column}: {code}: {message}")
        if fix:
            print(f"  fix: {fix}")


def _partition(files: list[str], jobs: int) -> list[list[str]]:
    jobs = max(1, min(jobs, len(files)))
    size = (len(files) + jobs - 1) // jobs
    return [files[index:index + size] for index in range(0, len(files), size)]


def _run_native(executable: Path, argv: Sequence[str], *, timeout_s: float,
                memory_mb: int):
    from ourosmith.limits import run_limited

    return run_limited(
        [str(executable), *argv],
        cwd=ROOT, env=_native_env(), timeout_s=timeout_s, memory_mb=memory_mb,
    )


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def _uses_native_clippy_surface(argv: Sequence[str]) -> bool:
    if _query_mode(argv) or _has_flag(argv, "--print-files"):
        return True
    if _has_flag(argv, "--warn-only") or _has_flag(argv, "--include-fixtures"):
        return True
    if _has_flag(argv, "--lint-companion"):
        return True
    if _flag_values(argv, "--report") or _flag_values(argv, "--sarif"):
        return True
    if _flag_values(argv, "--source-root"):
        return True
    return False


def _run_lint_semantic(argv: Sequence[str], *, timeout_s: float,
                       memory_mb: int) -> int:
    from ourosmith.host import prepare_entry
    from ourosmith.limits import run_limited

    scopes = _flag_values(argv, "--scope")
    if not scopes:
        scopes = ["std", "compiler", "tools", "samples"]
    profile = _option_or(argv, "--profile", "project")
    lint = prepare_entry("tools/lint.ouro", "ouro-lint")
    semantic = _firewall_executable()
    env = _native_env()
    env["OURO_LINT_SEMANTIC_EXE"] = str(semantic)
    result = run_limited(
        [str(lint), "--deny", "--family", "semantic", "--profile", profile,
         *scopes],
        cwd=ROOT, env=env, timeout_s=timeout_s, memory_mb=memory_mb,
    )
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode is None:
        return 1
    return int(result.returncode)


def _firewall_executable() -> Path:
    from ourosmith.host import binary, prepare_entry

    try:
        return binary("ouro-clippy-grade-firewall")
    except FileNotFoundError:
        env_was = os.environ.get("OURO_REUSE_EXISTING_COMPANION")
        os.environ["OURO_REUSE_EXISTING_COMPANION"] = "1"
        try:
            return prepare_entry("tools/clippy/main.ouro", "ouro-clippy-grade-firewall")
        finally:
            if env_was is None:
                os.environ.pop("OURO_REUSE_EXISTING_COMPANION", None)
            else:
                os.environ["OURO_REUSE_EXISTING_COMPANION"] = env_was


def main(argv: Optional[Sequence[str]] = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    timeout_s = _int_env("OURO_CLIPPY_TIMEOUT_S", 7200, minimum=1, maximum=86400)
    memory_mb = _int_env("OURO_CLIPPY_MEMORY_MB", 3072, minimum=512, maximum=12288)
    jobs = _int_env("OURO_CLIPPY_JOBS", 2, minimum=1, maximum=3)
    if not _uses_native_clippy_surface(raw):
        return _run_lint_semantic(raw, timeout_s=timeout_s, memory_mb=memory_mb)
    if _has_flag(raw, "--print-files"):
        if _query_mode(raw):
            sys.stderr.write(
                "CLIPPY_GRADE_FIREWALL: FAIL --print-files cannot be combined "
                "with --list-rules or --validate-rules\n")
            return 1
        try:
            files = _collect_clippy_files(raw)
        except ValueError as exc:
            sys.stderr.write(f"CLIPPY_GRADE_FIREWALL: FAIL {exc}\n")
            return 1
        sys.stdout.write("\n".join(files) + ("\n" if files else ""))
        return 0
    executable = _firewall_executable()
    if _query_mode(raw) or jobs <= 1 or not _scope_looks_like_tree(raw):
        result = _run_native(executable, raw, timeout_s=timeout_s, memory_mb=memory_mb)
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        if result.returncode is None:
            return 1
        return int(result.returncode)

    try:
        files = _collect_clippy_files(raw)
    except ValueError as exc:
        sys.stderr.write(f"CLIPPY_GRADE_FIREWALL: FAIL {exc}\n")
        return 1
    if len(files) <= 1:
        result = _run_native(executable, raw, timeout_s=timeout_s, memory_mb=memory_mb)
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        if result.returncode is None:
            return 1
        return int(result.returncode)

    report = Path(_option_or(raw, "--report", "_build/quality/clippy-grade-firewall.json"))
    sarif = Path(_option_or(raw, "--sarif", "_build/quality/clippy-grade-firewall.sarif"))
    if not report.is_absolute():
        report = ROOT / report
    if not sarif.is_absolute():
        sarif = ROOT / sarif
    profile = _option_or(raw, "--profile", "project")
    warn_only = _has_flag(raw, "--warn-only")
    source_root = _option_or(raw, "--source-root", ".")
    scopes = _flag_values(raw, "--scope") or ["std", "compiler", "tools/analyze", "tools", "samples"]
    shards = _partition(files, jobs)
    base = _without_outputs(raw)
    # Drop original directory scopes so shard file scopes are the inventory.
    cleaned: list[str] = []
    skip_value = False
    for item in base:
        if skip_value:
            skip_value = False
            continue
        if item == "--scope":
            skip_value = True
            continue
        if item.startswith("--scope="):
            continue
        cleaned.append(item)

    def run_shard(index: int, chunk: list[str]):
        part_report = Path(str(report) + f".part-{index}")
        part_sarif = Path(str(sarif) + f".part-{index}")
        part_report.unlink(missing_ok=True)
        part_sarif.unlink(missing_ok=True)
        shard_argv = list(cleaned)
        for path in chunk:
            shard_argv.extend(["--scope", path])
        shard_argv.extend(["--report", str(part_report), "--sarif", str(part_sarif)])
        result = _run_native(executable, shard_argv, timeout_s=timeout_s, memory_mb=memory_mb)
        return index, chunk, result, part_report

    merged_parts: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    failed = False
    with ThreadPoolExecutor(max_workers=len(shards)) as pool:
        futures = [pool.submit(run_shard, index, chunk)
                   for index, chunk in enumerate(shards)]
        for future in as_completed(futures):
            index, chunk, result, part_report = future.result()
            sys.stderr.write(result.stderr)
            if result.returncode is None or not part_report.is_file():
                sys.stderr.write(
                    "CLIPPY_GRADE_FIREWALL: FAIL shard "
                    + str(index)
                    + " did not publish a report for "
                    + str(len(chunk))
                    + " files\n"
                )
                failed = True
                continue
            part = _load_json(part_report)
            merged_parts.append(part)
            part_findings = part.get("findings", [])
            if isinstance(part_findings, list):
                findings.extend(item for item in part_findings if isinstance(item, dict))
            if result.returncode not in {0, 1}:
                failed = True
    if failed or len(merged_parts) != len(shards):
        return 1
    findings.sort(key=_finding_sort_key)
    _print_findings(findings)
    _payload, status = _merge_reports(
        merged_parts, report=report, sarif=sarif, profile=profile,
        warn_only=warn_only, source_root=source_root, scopes=scopes,
    )
    return status


if __name__ == "__main__":
    raise SystemExit(main())
