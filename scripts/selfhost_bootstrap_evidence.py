#!/usr/bin/env python3
"""Write machine-readable evidence for Ouro selfhost/bootstrap convergence."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import platform
import re
import shlex
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

from repo_support import hash_json, read_json_value, sha256_file, write_json_atomic

try:
    import resource
except ImportError:  # pragma: no cover
    resource = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1
REPORT_KIND = "ouro.selfhost-bootstrap-evidence.v1"
DEFAULT_OUT = Path("_build/bootstrap/evidence.json")
DEFAULT_WORK_DIR = Path("_build/bootstrap")
DEFAULT_STAGE_LOOP_RESULT = Path("_build/stage_loop/result.json")
DEFAULT_STAGE_LOOP_COMMAND = "sh scripts/stage_loop.sh"
DEFAULT_LOG_BYTES = 16 * 1024
NATIVE_REPORT_KIND = "ouro.native-selfhost-evidence.v1"
NATIVE_RESULT_KIND = "ouro.native-selfhost-observation.v1"
NATIVE_ENTRY = "tools/native_build.ouro"
NATIVE_CONFIG = {"target": "x86_64-windows", "entry": "main", "fuel": 200000, "mir_limits": 16777216}
NATIVE_IMPORTS = {"advapi32.dll", "bcrypt.dll", "kernel32.dll", "shell32.dll", "winhttp.dll"}
NATIVE_WINDOWS_PATHS = sys.platform == "win32"
DEFAULT_NATIVE_OUT = Path("_build/bootstrap/native-evidence.json")
STAGE_RE = re.compile(r"(?<![A-Za-z0-9])stage([0-9]+)(?![A-Za-z0-9])")
PATH_KEYS = ("artifact", "compiler", "dir", "file", "generated", "log", "manifest", "output", "path", "stamp")


def now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def abs_path(root: Path, path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else root / p


def repo_path(root: Path, path: str | Path) -> str:
    raw = Path(path)
    candidate = raw if raw.is_absolute() else root / raw
    try:
        return candidate.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, RuntimeError, ValueError):
        return f"<outside-repo>/{raw.name}" if raw.is_absolute() else raw.as_posix().lstrip("./")


def sha256_dir(path: Path) -> tuple[str, int, int, bool]:
    digest = hashlib.sha256()
    files = sorted(p for p in path.rglob("*") if p.is_file())
    truncated = len(files) > 512
    total = 0
    for child in files[:512]:
        rel = child.relative_to(path).as_posix()
        size = child.stat().st_size
        total += size
        digest.update(rel.encode())
        digest.update(b"\0")
        digest.update(sha256_file(child).encode())
        digest.update(b"\0")
        digest.update(str(size).encode())
        digest.update(b"\0")
    digest.update(f"count={len(files)} truncated={int(truncated)}".encode())
    return digest.hexdigest(), len(files), total, truncated


def excerpt(path: Path, limit: int) -> tuple[str, bool, int]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        text = f"<unable to read log: {type(exc).__name__}: {exc}>".encode()
        return text[: max(0, limit)].decode(errors="replace"), False, 0
    if limit <= 0:
        return "", bool(data), len(data)
    if len(data) <= limit:
        return data.decode(errors="replace"), False, len(data)
    marker = b"\n...<truncated>...\n"
    if limit <= len(marker):
        clipped = marker[:limit]
    else:
        head = (limit - len(marker)) // 2
        tail = limit - len(marker) - head
        clipped = data[:head] + marker + data[-tail:]
    return clipped.decode(errors="replace"), True, len(data)


def safe_label(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-") or "command"


def resource_snapshot() -> Any:
    return None if resource is None else resource.getrusage(resource.RUSAGE_CHILDREN)


def resource_delta(before: Any, after: Any) -> dict[str, Any]:
    if before is None or after is None:
        return {"user_cpu_seconds": None, "system_cpu_seconds": None, "peak_rss_bytes": None, "note": "resource module unavailable"}
    return {
        "user_cpu_seconds": round(max(0.0, after.ru_utime - before.ru_utime), 6),
        "system_cpu_seconds": round(max(0.0, after.ru_stime - before.ru_stime), 6),
        "peak_rss_bytes": None,
        "note": "peak RSS is nullable: portable Python subprocess execution does not expose per-command high-water RSS",
    }


def run_command(
    label: str,
    cmd: Sequence[str],
    *,
    root: Path,
    log_dir: Path,
    timeout_seconds: Optional[float],
    log_bytes: int,
    env: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout = log_dir / f"{safe_label(label)}.stdout.log"
    stderr = log_dir / f"{safe_label(label)}.stderr.log"
    started_at, started, before = now(), time.perf_counter(), resource_snapshot()
    status, code, reason = "fail", None, None
    try:
        with stdout.open("wb") as out, stderr.open("wb") as err:
            proc = subprocess.run(list(cmd), cwd=root, env=dict(env) if env is not None else None, stdout=out, stderr=err, timeout=timeout_seconds, check=False)
        code = int(proc.returncode)
        status = "pass" if code == 0 else "fail"
        reason = None if code == 0 else f"command exited with status {code}"
    except FileNotFoundError:
        status, reason = "unavailable", f"missing executable: {cmd[0] if cmd else '<empty command>'}"
        stderr.write_text(reason + "\n", encoding="utf-8")
    except subprocess.TimeoutExpired:
        status, reason = "timeout", f"timeout after {timeout_seconds} seconds"
        stderr.write_text(reason + "\n", encoding="utf-8")
    except OSError as exc:
        status, reason = "unavailable", f"{type(exc).__name__}: {exc}"
        stderr.write_text(reason + "\n", encoding="utf-8")
    out_text, out_trunc, out_bytes = excerpt(stdout, log_bytes)
    err_text, err_trunc, err_bytes = excerpt(stderr, log_bytes)
    return {
        "label": label,
        "argv": list(cmd),
        "cwd": ".",
        "started_at": started_at,
        "ended_at": now(),
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "exit_code": code,
        "status": status,
        "reason": reason,
        "stdout_log": repo_path(root, stdout),
        "stderr_log": repo_path(root, stderr),
        "stdout_excerpt": out_text,
        "stderr_excerpt": err_text,
        "stdout_bytes": out_bytes,
        "stderr_bytes": err_bytes,
        "stdout_truncated": out_trunc,
        "stderr_truncated": err_trunc,
        "resources": resource_delta(before, resource_snapshot()),
    }


def probe(root: Path, cmd: Sequence[str]) -> dict[str, Any]:
    try:
        p = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=10, check=False)
    except FileNotFoundError:
        return {"available": False, "reason": f"missing executable: {cmd[0] if cmd else '<empty>'}"}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    return {"available": p.returncode == 0, "exit_code": p.returncode, "stdout": p.stdout.strip(), "stderr": p.stderr.strip()}


def repo_metadata(root: Path) -> dict[str, Any]:
    head = probe(root, ["git", "rev-parse", "HEAD"])
    branch = probe(root, ["git", "rev-parse", "--abbrev-ref", "HEAD"])
    status = probe(root, ["git", "status", "--porcelain", "--untracked-files=no"])
    return {
        "root": ".",
        "git_available": bool(head.get("available")),
        "git_head": head.get("stdout") if head.get("available") else None,
        "git_branch": branch.get("stdout") if branch.get("available") else None,
        "tracked_worktree_changes": status.get("stdout", "").splitlines() if status.get("available") else None,
        "git_probe_errors": [x.get("reason") or x.get("stderr") for x in (head, branch, status) if not x.get("available") and (x.get("reason") or x.get("stderr"))],
    }


def generated_changes(root: Path) -> dict[str, Any]:
    result = probe(root, ["git", "status", "--porcelain", "--untracked-files=no", "--", "compiler/stage0"])
    if not result.get("available"):
        return {"available": False, "changed": None, "paths": [], "reason": result.get("reason") or result.get("stderr")}
    paths = [line for line in result.get("stdout", "").splitlines() if line.strip()]
    return {"available": True, "changed": bool(paths), "paths": paths}


def environment_metadata() -> dict[str, Any]:
    return {
        "python": {"implementation": platform.python_implementation(), "version": platform.python_version(), "executable": Path(sys.executable).name},
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "resource_metrics": {"wall_clock": "measured", "cpu": "best-effort via resource module", "peak_rss": "nullable"},
    }


def empty_report(root: Path, *, out: Optional[Path] = None, work_dir: Optional[Path] = None) -> dict[str, Any]:
    out = out or DEFAULT_OUT
    work_dir = work_dir or DEFAULT_WORK_DIR
    return {
        "kind": REPORT_KIND,
        "schema_version": SCHEMA_VERSION,
        "repo": repo_metadata(root),
        "environment": environment_metadata(),
        "commands": [],
        "stages": [],
        "artifacts": [],
        "comparisons": [],
        "tests": [],
        "summary": {
            "status": "partial",
            "converged": None,
            "generated_artifacts_changed": None,
            "report": repo_path(root, abs_path(root, out)),
            "logs": repo_path(root, abs_path(root, work_dir) / "logs"),
        },
    }


def normalize_status(status: str) -> str:
    value = status.lower()
    return {"ok": "pass", "success": "pass", "succeeded": "pass", "passed": "pass", "error": "fail", "failed": "fail", "mismatch": "fail", "skip": "skipped"}.get(value, value)


def extract_status(value: Any) -> str:
    if isinstance(value, Mapping):
        summary = value.get("summary")
        if isinstance(summary, Mapping) and isinstance(summary.get("status"), str):
            return normalize_status(str(summary["status"]))
        for key in ("status", "result"):
            if isinstance(value.get(key), str):
                return normalize_status(str(value[key]))
        for key in ("pass", "passed", "ok", "success"):
            if isinstance(value.get(key), bool):
                return "pass" if value[key] else "fail"
        if value.get("skipped") is True:
            return "skipped"
        if value.get("available") is False:
            return "unavailable"
    if isinstance(value, bool):
        return "pass" if value else "fail"
    return "unknown"


def looks_like_path(value: str) -> bool:
    if not value or len(value) > 400 or "\n" in value or "://" in value or re.fullmatch(r"[0-9a-fA-F]{32,}", value):
        return False
    if value.startswith(("_build/", "compiler/", "scripts/", "test/", "tests/", "kernel/", "runtime/", "frontend/", "backend/", "./")):
        return True
    return "/" in value and value.endswith((".json", ".c", ".h", ".o", ".d", ".cmdhash", ".stamp", ".log", ".txt"))


def collect_paths(value: Any, parent_key: str = "") -> set[str]:
    paths: set[str] = set()
    if isinstance(value, Mapping):
        if parent_key.endswith("artifact_hashes"):
            paths.update(str(k) for k in value if isinstance(k, str) and looks_like_path(k))
        for key, child in value.items():
            key_text = str(key)
            if isinstance(child, str) and any(token in key_text.lower() for token in PATH_KEYS) and looks_like_path(child):
                paths.add(child)
            paths.update(collect_paths(child, f"{parent_key}.{key_text}" if parent_key else key_text))
    elif isinstance(value, list):
        for child in value:
            paths.update(collect_paths(child, parent_key))
    return paths


def classify(path: str) -> str:
    if path == DEFAULT_STAGE_LOOP_RESULT.as_posix() or path.endswith("/result.json"):
        return "stage-loop-result"
    if "generated" in path:
        return "generated"
    if "manifest" in path or path.endswith(".json"):
        return "manifest"
    if "stage" in path:
        return "stage"
    return "bootstrap"


def hash_artifact(root: Path, path: str | Path, *, group: str, required: bool) -> dict[str, Any]:
    rel = repo_path(root, path)
    actual = abs_path(root, rel)
    base = {"path": rel, "group": group, "required": required}
    if actual.is_file():
        return {**base, "kind": "file", "status": "present", "sha256": sha256_file(actual), "size_bytes": actual.stat().st_size}
    if actual.is_dir():
        digest, count, total, truncated = sha256_dir(actual)
        return {**base, "kind": "directory", "status": "present", "sha256": digest, "size_bytes": total, "file_count": count, "truncated": truncated, "max_files_hashed": 512}
    return {**base, "kind": "missing", "status": "missing", "sha256": None, "size_bytes": None, "reason": "required artifact missing" if required else "optional artifact absent"}


def discover_artifacts(root: Path, stage_loop_result: Optional[Mapping[str, Any]], result_path: Path, *, require_result: bool = True) -> list[dict[str, Any]]:
    result_rel = repo_path(root, abs_path(root, result_path))
    required = {result_rel} if require_result else set()
    optional = {result_rel} if not require_result and abs_path(root, result_path).exists() else set()
    if stage_loop_result is not None:
        required.update(repo_path(root, p) for p in collect_paths(stage_loop_result))
    for candidate in (
        "_build/selfhost/generated", "_build/selfhost/trace",
        "_build/selfhost/stage0.stamp", "_build/selfhost/stage1.stamp", "_build/selfhost/stage2.stamp", "_build/selfhost/stage3.stamp",
        "_build/compiler_stage0", "_build/compiler_stage1", "_build/compiler_stage2", "_build/compiler_stage3",
        "_build/compiler_stage0.exe", "_build/compiler_stage1.exe", "_build/compiler_stage2.exe", "_build/compiler_stage3.exe",
    ):
        if abs_path(root, candidate).exists():
            optional.add(candidate)
    artifacts = [hash_artifact(root, p, group=classify(p), required=True) for p in sorted(required)]
    artifacts += [hash_artifact(root, p, group=classify(p), required=False) for p in sorted(optional - required)]
    return sorted(artifacts, key=lambda item: item["path"])


def first_numeric(raw: Mapping[str, Any], keys: Iterable[str]) -> Optional[float]:
    for key in keys:
        if isinstance(raw.get(key), (int, float)):
            return float(raw[key])
    return None


def first_path(raw: Mapping[str, Any], tokens: Iterable[str]) -> Optional[str]:
    toks = tuple(tokens)
    for key, value in raw.items():
        if isinstance(value, str) and all(tok in str(key).lower() for tok in toks) and looks_like_path(value):
            return value
    return None


def normalize_stages(result: Optional[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if result is None:
        return []
    items: list[tuple[str, Any]] = []
    raw = result.get("stages")
    if not isinstance(raw, (Mapping, list)):
        raw = result.get("stage_reports")
    if isinstance(raw, Mapping):
        items += [(str(k), v) for k, v in raw.items()]
    elif isinstance(raw, list):
        items += [
            (
                str(v.get("name") or (f"stage{v.get('stage')}" if v.get("stage") is not None else f"stage{i}"))
                if isinstance(v, Mapping)
                else f"stage{i}",
                v,
            )
            for i, v in enumerate(raw)
        ]
    items += [(str(k), v) for k, v in result.items() if isinstance(k, str) and k.startswith("stage") and isinstance(v, Mapping)]
    seen, stages = set(), []
    for name, raw_value in sorted(items, key=lambda item: item[0]):
        if name in seen:
            continue
        seen.add(name)
        paths = sorted(collect_paths(raw_value))
        peak = first_numeric(raw_value, ("peak_rss_bytes", "peak_rss")) if isinstance(raw_value, Mapping) else None
        number_match = STAGE_RE.search(name)
        status = extract_status(raw_value)
        if status == "unknown" and isinstance(raw_value, Mapping):
            status = extract_status(raw_value.get("frontend"))
        stages.append({
            "name": name,
            "number": int(number_match.group(1)) if number_match else None,
            "status": status,
            "input_compiler_path": first_path(raw_value, ("input", "compiler")) if isinstance(raw_value, Mapping) else None,
            "output_compiler_path": first_path(raw_value, ("output", "compiler")) if isinstance(raw_value, Mapping) else None,
            "generated_source_paths": [p for p in paths if "generated" in p or p.endswith((".c", ".h"))],
            "artifact_paths": paths,
            "elapsed_seconds": first_numeric(raw_value, ("elapsed_s", "elapsed_seconds", "duration_s")) if isinstance(raw_value, Mapping) else None,
            "exit_code": first_numeric(raw_value, ("exit_code", "returncode", "return_code")) if isinstance(raw_value, Mapping) else None,
            "stdout_log": first_path(raw_value, ("stdout", "log")) if isinstance(raw_value, Mapping) else None,
            "stderr_log": first_path(raw_value, ("stderr", "log")) if isinstance(raw_value, Mapping) else None,
            "peak_rss_bytes": peak,
            "resource_note": None if peak is not None else "not reported by stage-loop result",
            "raw": raw_value,
        })
    return stages


def stable_sequence(value: Any) -> list[Any]:
    if not value:
        return []
    if isinstance(value, Mapping):
        values: Iterable[Any] = [{"key": k, "value": v} for k, v in value.items()]
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = [value]
    return sorted(values, key=lambda item: json.dumps(item, sort_keys=True, default=str))


def comparison_status(raw: Mapping[str, Any]) -> str:
    for key in ("status", "result"):
        if isinstance(raw.get(key), str):
            return normalize_status(str(raw[key]))
    for key in ("match", "matched", "equal", "converged", "same", "pass", "passed", "ok"):
        if isinstance(raw.get(key), bool):
            return "pass" if raw[key] else "fail"
    return "fail" if any(raw.get(k) for k in ("mismatches", "mismatched_paths", "missing_paths", "extra_paths", "missing", "extra")) else "unknown"


def normalize_existing_comparisons(result: Optional[Mapping[str, Any]]) -> list[dict[str, Any]]:
    raw = None if result is None else result.get("comparisons")
    out = []
    if raw is not None:
        items = list(raw.items()) if isinstance(raw, Mapping) else list(enumerate(raw if isinstance(raw, list) else [raw]))
        for name, value in sorted(((str(k), v) for k, v in items), key=lambda item: item[0]):
            if isinstance(value, Mapping):
                out.append({
                    "name": name,
                    "policy": "stage_loop",
                    "status": comparison_status(value),
                    "matched_count": value.get("matched_count"),
                    "mismatched_paths": stable_sequence(value.get("mismatched_paths", value.get("mismatches", []))),
                    "missing_paths": stable_sequence(value.get("missing_paths", value.get("missing", []))),
                    "extra_paths": stable_sequence(value.get("extra_paths", value.get("extra", []))),
                    "raw": value,
                })
            else:
                out.append({"name": name, "policy": "stage_loop", "status": extract_status(value), "matched_count": None, "mismatched_paths": [], "missing_paths": [], "extra_paths": [], "raw": value})
    if not out and result is not None:
        for key, name in (("backend_eq", "stage1-stage2-backend"), ("frontend_eq", "stage1-stage2-frontend")):
            value = result.get(key)
            if isinstance(value, bool):
                out.append({"name": name, "policy": "stage_loop", "status": "pass" if value else "fail", "matched_count": None, "mismatched_paths": [], "missing_paths": [], "extra_paths": [], "raw": value})
        if not out and isinstance(result.get("fixpoint"), bool):
            value = bool(result["fixpoint"])
            out.append({"name": "stage-loop-fixpoint", "policy": "stage_loop", "status": "pass" if value else "fail", "matched_count": None, "mismatched_paths": [], "missing_paths": [], "extra_paths": [], "raw": value})
    return out


def compare_hash_maps(name: str, left: Mapping[str, str], right: Mapping[str, str]) -> dict[str, Any]:
    common = sorted(set(left) & set(right))
    mismatches = [{"path": p, "left_sha256": left[p], "right_sha256": right[p]} for p in common if left[p] != right[p]]
    missing, extra = sorted(set(left) - set(right)), sorted(set(right) - set(left))
    matched = [p for p in common if left[p] == right[p]]
    return {"name": name, "policy": "content_hash", "status": "pass" if not mismatches and not missing and not extra else "fail", "matched_count": len(matched), "matched_paths": matched, "mismatched_paths": mismatches, "missing_paths": missing, "extra_paths": extra}


def comparable_key(path: str) -> Optional[tuple[int, str]]:
    if "generated" not in path and not path.endswith((".c", ".h", ".manifest", ".json", ".stamp")):
        return None
    match = STAGE_RE.search(path)
    return None if not match else (int(match.group(1)), STAGE_RE.sub("stage{n}", path))


def derived_stage_comparisons(artifacts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[int, dict[str, str]] = {}
    for artifact in artifacts:
        if artifact.get("status") != "present" or not artifact.get("sha256"):
            continue
        key = comparable_key(str(artifact.get("path", "")))
        if key:
            groups.setdefault(key[0], {})[key[1]] = str(artifact["sha256"])
    return [compare_hash_maps(f"stage{a}-stage{b}-generated-artifacts", groups[a], groups[b]) for a, b in ((1, 2), (2, 3)) if groups.get(a) and groups.get(b)]


def normalize_tests(result: Optional[Mapping[str, Any]], records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    tests = []
    if result is not None:
        for key in ("verification", "acceptance", "diagnostics", "tests"):
            if key in result:
                value = result[key]
                tests.append({"name": f"stage_loop.{key}", "status": extract_status(value), "command": None, "input_corpus": key, "expected_status": "pass", "actual_status": extract_status(value), "exit_code": first_numeric(value, ("exit_code", "returncode", "return_code")) if isinstance(value, Mapping) else None, "diagnostics_log": first_path(value, ("log",)) if isinstance(value, Mapping) else None, "raw": value})
    for record in records:
        tests.append({"name": record["label"], "status": record["status"], "command": record["argv"], "input_corpus": None, "expected_status": "pass", "actual_status": record["status"], "exit_code": record.get("exit_code"), "diagnostics_log": record.get("stderr_log"), "stdout_log": record.get("stdout_log")})
    return tests


def read_json(path: Path) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    if not path.is_file():
        return None, "result JSON was not written"
    value, error = read_json_value(path)
    if error is not None:
        return None, f"unable to read JSON: {error}"
    return (value, None) if isinstance(value, dict) else (None, "result JSON top-level value is not an object")


def parse_labelled_command(value: str, default: str) -> tuple[str, list[str]]:
    label, command = value.split("::", 1) if "::" in value else (default, value)
    return label.strip() or default, shlex.split(command)


def finalize_report(
    report: dict[str, Any],
    *,
    stage_loop_result: Optional[Mapping[str, Any]],
    run_stage_loop: bool,
    stage_loop_read_error: Optional[str],
    generated_changes: Mapping[str, Any],
) -> dict[str, Any]:
    hard, partial = [], []
    if not run_stage_loop:
        partial.append("stage-loop execution was explicitly skipped")
    for command in report["commands"]:
        status = command.get("status")
        if status in {"fail", "timeout", "unavailable"}:
            hard.append(f"command {command.get('label')} ended with status {status}")
        elif status in {"skip", "skipped"}:
            partial.append(f"command {command.get('label')} was skipped")
    if stage_loop_read_error:
        (hard if run_stage_loop else partial).append(stage_loop_read_error)
    loop_status = extract_status(stage_loop_result) if stage_loop_result is not None else "unknown"
    if stage_loop_result is not None and loop_status not in {"pass"}:
        (partial if loop_status in {"partial", "skipped", "skip", "unavailable", "unknown"} else hard).append(f"stage-loop result status is {loop_status}")
    missing = [a["path"] for a in report["artifacts"] if a.get("required") and a.get("status") == "missing"]
    if missing:
        hard.append(f"missing required artifacts: {len(missing)}")
    failed_cmp = [c for c in report["comparisons"] if c.get("status") == "fail"]
    unknown_cmp = [c for c in report["comparisons"] if c.get("status") == "unknown"]
    if failed_cmp:
        hard.append(f"convergence comparison failures: {len(failed_cmp)}")
    if unknown_cmp and loop_status == "pass":
        hard.append(f"unknown convergence comparison status: {len(unknown_cmp)}")
    if stage_loop_result is not None and loop_status == "pass" and not report["comparisons"]:
        hard.append("stage-loop completed without any convergence comparisons")
    failed_tests = [t for t in report["tests"] if t.get("status") in {"fail", "timeout", "unavailable"}]
    if failed_tests:
        hard.append(f"semantic/diagnostic evidence failures: {len(failed_tests)}")
    if failed_cmp or missing:
        converged: Optional[bool] = False
    elif report["comparisons"] and not unknown_cmp and not hard:
        converged = True
    else:
        converged = None
    report["summary"].update({
        "status": "fail" if hard else ("partial" if partial else "pass"),
        "converged": converged,
        "generated_artifacts_changed": generated_changes.get("changed"),
        "generated_artifact_change_paths": generated_changes.get("paths", []),
        "generated_artifact_change_probe_available": generated_changes.get("available"),
        "commands_total": len(report["commands"]),
        "stages_total": len(report["stages"]),
        "stages_completed": len([s for s in report["stages"] if s.get("status") == "pass"]),
        "tests_total": len(report["tests"]),
        "comparisons_total": len(report["comparisons"]),
        "mismatch_count": sum(len(c.get("mismatched_paths", [])) for c in report["comparisons"]),
        "missing_required_artifacts": missing,
        "hard_errors": hard,
        "partial_reasons": partial,
    })
    return report


def build_report(
    *,
    root: Path,
    out: Path,
    work_dir: Path,
    stage_loop_result_path: Path,
    run_stage_loop_flag: bool,
    stage_loop_command: Sequence[str],
    test_commands: Sequence[tuple[str, Sequence[str]]],
    timeout_seconds: Optional[float],
    log_bytes: int,
) -> tuple[dict[str, Any], int]:
    report = empty_report(root, out=out, work_dir=work_dir)
    logs = abs_path(root, work_dir) / "logs"
    test_records: list[dict[str, Any]] = []
    if run_stage_loop_flag:
        report["commands"].append(run_command("stage-loop", stage_loop_command, root=root, log_dir=logs, timeout_seconds=timeout_seconds, log_bytes=log_bytes))
    else:
        report["commands"].append({"label": "stage-loop", "argv": list(stage_loop_command), "cwd": ".", "started_at": None, "ended_at": None, "elapsed_seconds": 0.0, "exit_code": None, "status": "skipped", "reason": "explicit --no-stage-loop", "stdout_log": None, "stderr_log": None, "stdout_excerpt": "", "stderr_excerpt": "", "stdout_bytes": 0, "stderr_bytes": 0, "stdout_truncated": False, "stderr_truncated": False, "resources": {}})
    result, read_error = read_json(abs_path(root, stage_loop_result_path))
    for idx, (label, command) in enumerate(test_commands):
        record = run_command(label or f"test-{idx + 1}", command, root=root, log_dir=logs, timeout_seconds=timeout_seconds, log_bytes=log_bytes)
        report["commands"].append(record)
        test_records.append(record)
    report["artifacts"] = discover_artifacts(root, result, stage_loop_result_path, require_result=run_stage_loop_flag or result is not None)
    report["stages"] = normalize_stages(result)
    report["comparisons"] = normalize_existing_comparisons(result)
    if not report["comparisons"]:
        report["comparisons"] = derived_stage_comparisons(report["artifacts"])
    report["tests"] = normalize_tests(result, test_records)
    finalize_report(report, stage_loop_result=result, run_stage_loop=run_stage_loop_flag, stage_loop_read_error=read_error, generated_changes=generated_changes(root))
    return report, 0 if report["summary"]["status"] == "pass" else 1


def native_require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def native_path(root: Path, name: Any) -> Path:
    native_require(isinstance(name, str) and bool(name) and "\\" not in name
                   and ":" not in name and not name.startswith("/")
                   and all(part not in {"", ".", ".."} for part in name.split("/")),
                   "native evidence path must be repository-relative")
    path = (root / name).resolve(strict=True)
    native_require(path.is_relative_to(root.resolve()) and path.is_file(),
                   f"native evidence file escapes the repository or is missing: {name}")
    return path


def native_json(path: Path) -> dict[str, Any]:
    native_require(path.stat().st_size <= 16 * 1024 * 1024, "native evidence JSON exceeds 16 MiB")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, child in pairs:
            native_require(key not in value, f"duplicate native evidence field: {key}")
            value[key] = child
        return value

    def nonfinite(value: str) -> None:
        raise ValueError(f"non-finite native evidence value: {value}")

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique, parse_constant=nonfinite)
    native_require(isinstance(value, dict), "native evidence JSON must be an object")
    return value


def native_units(root: Path, entry: str) -> list[str]:
    from selfhost_module_cache import collect_units, quoted_import_targets

    def imports(name: str) -> list[str]:
        path = native_path(root, name)
        native_require(path.stat().st_size <= 16 * 1024 * 1024, "native source exceeds 16 MiB")
        return quoted_import_targets(path.read_text(encoding="utf-8"), name)

    try:
        return collect_units(entry, imports=imports,
                             cycle_error=lambda name: f"native evidence import cycle: {name}")
    except SystemExit as exc:
        raise ValueError(str(exc)) from exc


def native_output_guard(root: Path, out: Path, values: Any) -> None:
    root, target = root.resolve(), out.resolve()
    target_identity = None
    if target.is_file():
        metadata = target.stat()
        native_require(metadata.st_ino != 0, "native output file identity is unavailable")
        target_identity = metadata.st_dev, metadata.st_ino
    pending = [values]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            names = [value["path"]] if isinstance(value.get("path"), str) else []
            for field in ("sources", "stage0"):
                if isinstance(value.get(field), dict):
                    names.extend(value[field])
            for name in names:
                candidate = (root / name).resolve()
                if not candidate.is_relative_to(root):
                    continue
                native_require(candidate != target, "native output aliases an input artifact")
                if target_identity is not None and candidate.is_file():
                    metadata = candidate.stat()
                    native_require(metadata.st_ino != 0, "native input file identity is unavailable")
                    native_require((metadata.st_dev, metadata.st_ino) != target_identity,
                                   "native output aliases an input artifact")
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)


def build_native_report(*, root: Path, out: Path, result_path: Path) -> tuple[dict[str, Any], int]:
    """Validate host observations; never execute a stage or infer behavior from equality."""
    root = root.resolve()
    report = empty_report(root, out=out)
    report["kind"] = NATIVE_REPORT_KIND
    report["acceptance_scope"] = "native-stage-chain-and-declared-behavior"
    report["summary"].update(status="fail", converged=None, logs=None, hard_errors=[],
                             partial_reasons=[], provenance_accepted=False, behavior_accepted=False,
                             native_seed_promoted=False, isolated_host_accepted=False)
    pinned: dict[Path, str] = {}
    output_identities: set[tuple[int, int]] = set()
    image_identities: dict[tuple[int, int], Path] = {}

    def generated(path: Path) -> bool:
        owner = path.relative_to(root).parts[0]
        return (owner.casefold() if NATIVE_WINDOWS_PATHS else owner) in {"_build", "_cache"}

    def file_identity(path: Path) -> tuple[int, int]:
        metadata = path.stat()
        native_require(metadata.st_ino != 0, "native output file identity is unavailable")
        return metadata.st_dev, metadata.st_ino

    def mark_output(path: Path) -> Path:
        output_identities.add(file_identity(path))
        return path

    def distinct_image(path: Path, label: str) -> Path:
        identity = file_identity(path)
        native_require(identity not in image_identities,
                       f"native {label} image aliases another seed, producer, stage, or program")
        image_identities[identity] = path
        return mark_output(path)

    def pin(ref: Any) -> Path:
        native_require(isinstance(ref, dict) and set(ref) == {"path", "sha256"},
                       "native file reference requires path and sha256")
        path = native_path(root, ref["path"])
        size = path.stat().st_size
        artifact = None
        if path not in pinned:
            artifact = {**ref, "path": path.relative_to(root).as_posix(), "status": "unverified", "required": True, "bytes": size}
            report["artifacts"].append(artifact)
        native_require(size <= 256 * 1024 * 1024, "native evidence file exceeds 256 MiB")
        native_require(isinstance(ref["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", ref["sha256"]) is not None
                       and sha256_file(path) == ref["sha256"], f"stale native evidence file: {ref['path']}")
        native_require(path not in pinned or pinned[path] == ref["sha256"], "conflicting native file identities")
        if artifact is not None:
            pinned[path] = ref["sha256"]
            artifact["status"] = "present"
        if generated(path):
            mark_output(path)
        return path

    def sources(value: Any) -> None:
        native_require(isinstance(value, dict) and bool(value), "native source inventory is missing")
        for name, digest in value.items():
            pin({"path": name, "sha256": digest})

    def image(value: Any) -> Path:
        from frontend_native_process import inspect_image

        native_require(isinstance(value, dict) and set(value) == {"path", "sha256", "imports"},
                       "native image reference requires path, sha256, and imports")
        path = pin({key: value[key] for key in ("path", "sha256")})
        imports = value["imports"]
        native_require(isinstance(imports, list) and all(isinstance(name, str) for name in imports)
                       and len(imports) == len(set(imports)) and bool(imports) and set(imports) <= NATIVE_IMPORTS,
                       "native image has undeclared or legacy imports")
        native_require(64 <= path.stat().st_size <= 256 * 1024 * 1024, "native image exceeds 256 MiB")
        inspect_image(path, imports, required_symbols={})
        with path.open("rb") as stream:
            stream.seek(0x3C)
            pe, = struct.unpack("<I", stream.read(4))
            stream.seek(pe + 20)
            optional_size, = struct.unpack("<H", stream.read(2))
            stream.seek(pe + 24 + 108)
            count, = struct.unpack("<I", stream.read(4))
            native_require(optional_size >= 152 and count >= 5, "native PE has no certificate directory field")
            stream.seek(pe + 24 + 144)
            native_require(stream.read(8) == bytes(8), "native evidence requires complete unsigned PE images")
        return mark_output(path)

    def passed(row: Any, label: str) -> None:
        native_require(isinstance(row, dict) and row.get("status") == "pass" and row.get("process_status") == "ok"
                       and type(row.get("exit_code")) is int and row["exit_code"] == 0,
                       f"native {label} failed, skipped, or incomplete")
        for stream in ("stdout", "stderr"):
            mark_output(pin(row.get(stream)))

    def emission(row: Any, declared: dict[str, Any], producer_path: Path, label: str) -> Path:
        passed(row, label)
        native_require(row.get("backend") == "ouro-native" and row.get("runtime") == "ouro-native",
                       f"native {label} lacks native backend/runtime provenance")
        native_require(isinstance(declared, dict) and set(declared) == {"entry", "units", "sources", "config"}
                       and isinstance(declared["entry"], str) and declared["config"] == NATIVE_CONFIG
                       and all(type(declared["config"][name]) is type(value) for name, value in NATIVE_CONFIG.items()),
                       f"native {label} compiler inputs differ")
        ordered = native_units(root, declared["entry"])
        native_require(declared["units"] == ordered and isinstance(declared["sources"], dict)
                       and set(declared["sources"]) == set(ordered), f"native {label} source closure differs")
        sources(declared["sources"])
        digest = hash_json(declared)
        native_require(row.get("inputs_sha256") == digest == row.get("inputs_after_sha256"), f"native {label} input identity changed")
        native_require(pin(row.get("producer")) == producer_path
                       and row.get("producer_after_sha256") == pinned[producer_path], f"native {label} producer changed")
        output = image(row.get("image"))
        argv = row.get("argv")
        native_require(isinstance(argv, list) and all(isinstance(word, str) for word in argv)
                       and len(argv) == len(ordered) + 3 and abs_path(root, argv[0]).resolve() == producer_path
                       and argv[1:] == [declared["entry"], row["image"]["path"], *ordered]
                       and isinstance(row.get("cwd"), str) and abs_path(root, row["cwd"]).resolve() == root.resolve(),
                       f"native {label} command does not bind the exact source closure")
        stdout = pin(row["stdout"])
        expected_stdout = (row["image"]["path"] + "\n").encode("utf-8")
        native_require(stdout.stat().st_size == len(expected_stdout) and stdout.read_bytes() == expected_stdout,
                       f"native {label} stdout does not name the emitted image exactly")
        return output

    try:
        path = abs_path(root, result_path).resolve(strict=True)
        native_require(path.is_relative_to(root.resolve()), "native result escapes the repository")
        native_require(path.stat().st_size <= 16 * 1024 * 1024, "native evidence JSON exceeds 16 MiB")
        result = native_json(pin({"path": path.relative_to(root.resolve()).as_posix(), "sha256": sha256_file(path)}))
        native_require(result.get("kind") == NATIVE_RESULT_KIND and type(result.get("schema_version")) is int
                       and result["schema_version"] == 1, "unsupported native observation schema")
        native_require(report["repo"]["git_available"] and result.get("source_revision") == report["repo"]["git_head"],
                       "native source revision is missing or stale")
        inputs = result.get("inputs")
        native_require(isinstance(inputs, dict) and set(inputs) == {"entry", "units", "sources", "config"}
                       and inputs["entry"] == NATIVE_ENTRY and inputs["config"] == NATIVE_CONFIG
                       and all(type(inputs["config"][name]) is type(value) for name, value in NATIVE_CONFIG.items()),
                       "native compiler inputs or positional configuration differ")
        units = native_units(root, NATIVE_ENTRY)
        native_require(inputs["units"] == units and set(inputs["sources"]) == set(units),
                       "native ordered source closure is missing or stale")
        sources(inputs["sources"])
        key = hash_json(inputs)
        native_require(result.get("inputs_sha256") == key, "native input digest differs")
        report["inputs"] = inputs
        report["inputs_sha256"] = key

        from native_tool_build import BUILD_INPUTS, RUNTIME, tool_roots
        import bootstrap_compiler as bootstrap
        import bootstrap_inputs
        from frontend_regen import FRONTEND_TUS
        from ourosmith.native import INPUT_FIELDS

        producer = result.get("producer")
        native_require(isinstance(producer, dict) and producer.get("origin") == "c-hosted",
                       "initial P must retain its C-hosted origin")
        previous = distinct_image(pin(producer.get("image")), "P")
        receipt = native_json(pin(producer.get("receipt")))
        seed = distinct_image(pin(producer.get("seed")), "C seed")
        seed_receipt_path = pin(producer.get("seed_receipt"))
        seed_receipt = native_json(seed_receipt_path)
        selected = seed_receipt.get("selected")
        native_require(isinstance(selected, dict), "C seed input receipt is missing")
        seed_roots = [source for _tag, _module, source, _file in FRONTEND_TUS] + ["compiler/backend.ouro"]
        graph = {entry: native_units(root, entry) for entry in [*seed_roots, *bootstrap.ACCEPTANCE_ROOTS]}
        names = set(bootstrap.HELPERS) | set(bootstrap.RUNTIME) | {name for units in graph.values() for name in units}
        names.update(child.relative_to(root).as_posix() for child in (root / "runtime").glob("*.h"))
        native_require(selected.get("roots") == seed_roots and selected.get("unit_graph") == graph
                       and isinstance(selected.get("sources"), dict) and set(selected["sources"]) == names,
                       "C seed source inventory is incomplete")
        sources(selected.get("sources"))
        native_require(isinstance(selected.get("stage0"), dict) and set(selected["stage0"]) == set(bootstrap_inputs.STAGE0),
                       "C seed bootstrap input inventory is incomplete")
        sources(selected["stage0"])
        pin({"path": bootstrap_inputs.ARCHIVE, "sha256": selected.get("archive_sha256")})
        pin({"path": bootstrap_inputs.MANIFEST, "sha256": selected.get("manifest_sha256")})
        bridge2_paths = {bootstrap_inputs.BRIDGE2_ARCHIVE, bootstrap_inputs.BRIDGE2_MANIFEST}
        present_bridge2 = {name for name in bridge2_paths if (root / name).exists()}
        bridge2 = selected.get("bridge2", {})
        native_require(isinstance(bridge2, dict) and set(bridge2) == present_bridge2
                       and (not present_bridge2 or present_bridge2 == bridge2_paths),
                       "C seed second bridge inventory is incomplete")
        if bridge2:
            sources(bridge2)
        work = Path(seed_receipt.get("work", "")).resolve(strict=True)
        native_require(work.is_relative_to(root.resolve()), "C seed evidence work directory escapes the repository")
        seed_report_path = work / "report.json"
        seed_report = native_json(pin({"path": seed_report_path.relative_to(root).as_posix(), "sha256": seed_receipt.get("report_sha256")}))
        native_require(type(seed_report.get("pass")) is bool and seed_report["pass"] is True,
                       "C seed acceptance receipt requires boolean pass=true")
        pin({"path": (work / "inputs.json").relative_to(root).as_posix(), "sha256": seed_report.get("inputs_sha256")})
        comparison = seed_report.get("complete_generated_c_comparison")
        native_require(isinstance(comparison, dict) and set(comparison) == {"driver_u.c", "backend_u.c"},
                       "C seed comparison evidence is incomplete")
        for name, row in comparison.items():
            native_require(isinstance(row, dict), "C seed comparison row is invalid")
            for stage in ("p1", "p2"):
                pin({"path": (work / "out" / stage / name).relative_to(root).as_posix(), "sha256": row.get(stage + "_sha256")})
        native_require(bootstrap.installed_current(seed, seed_receipt_path, selected), "C seed acceptance receipt is stale or incomplete")
        tool_inputs = receipt.get("inputs")
        native_require(isinstance(tool_inputs, dict) and set(tool_inputs) == INPUT_FIELDS
                       and receipt.get("kind") == "ouro.native-tool-build.v1"
                       and tool_inputs.get("kind") == receipt["kind"] and tool_inputs.get("entry") == NATIVE_ENTRY
                       and receipt.get("key") == hash_json(tool_inputs)
                       and receipt.get("binary_sha256") == producer["image"]["sha256"]
                       and tool_inputs.get("compiler_sha256") == producer["seed"]["sha256"]
                       and type(tool_inputs.get("fuel")) is int and tool_inputs["fuel"] > 0
                       and receipt.get("cache") in {"miss", "hit", "installed-hit"}, "P build receipt differs or is incomplete")
        names = set(BUILD_INPUTS) | set(RUNTIME) | {name for entry in tool_roots(NATIVE_ENTRY) for name in native_units(root, entry)}
        names.update(child.relative_to(root).as_posix() for child in (root / "runtime").glob("*.h"))
        native_require(isinstance(tool_inputs.get("sources"), dict) and set(tool_inputs["sources"]) == names,
                       "P build source inventory is incomplete")
        sources(tool_inputs["sources"])
        ordered_sources = list(dict.fromkeys([*(name for entry in tool_roots(NATIVE_ENTRY) for name in native_units(root, entry)),
                                             *BUILD_INPUTS, *RUNTIME,
                                             *(child.relative_to(root).as_posix() for child in sorted((root / "runtime").glob("*.h")))]))
        native_require(pin(producer.get("manifest")).read_text(encoding="utf-8").splitlines() == ordered_sources,
                       "P source manifest order differs")
        report["producer"] = producer

        stages = result.get("stages")
        native_require(isinstance(stages, list) and [row.get("stage") for row in stages if isinstance(row, dict)] == ["N1", "N2", "N3"]
                       and len(stages) == 3, "native evidence requires ordered N1, N2, N3 stages")
        images: dict[str, Path] = {}
        for row in stages:
            label = row["stage"]
            output = distinct_image(emission(row, inputs, previous, label), label)
            report["commands"].append({"label": label, "argv": row["argv"], "status": "pass", "exit_code": 0})
            report["stages"].append(row)
            images[label] = previous = output

        with images["N2"].open("rb") as left, images["N3"].open("rb") as right:
            equal = True
            while True:
                a, b = left.read(1024 * 1024), right.read(1024 * 1024)
                if a != b:
                    equal = False
                    break
                if not a:
                    break
        report["summary"]["converged"] = equal
        report["comparisons"].append({"name": "N2-N3-complete-unsigned-images", "policy": "all-file-bytes", "status": "pass" if equal else "fail",
                                      "left": stages[1]["image"], "right": stages[2]["image"]})
        native_require(equal, "native N2/N3 complete images differ")

        behavior = result.get("behavior")
        required = {(stage, suite) for stage in ("N2", "N3") for suite in ("compiler", "runtime", "tools")}
        native_require(isinstance(behavior, list) and len(behavior) == len(required)
                       and {(row.get("stage"), row.get("suite")) for row in behavior if isinstance(row, dict)} == required,
                       "native N2/N3 compiler/runtime/tools behavior is missing or duplicated")
        # Pin all raw outputs before accepting any oracle, including later checks.
        for row in behavior:
            records = [row]
            for group in ("programs", "checks"):
                if isinstance(row.get(group), list):
                    records.extend(row[group])
            for record in records:
                native_require(isinstance(record, dict), "native behavior output record is invalid")
                for stream in ("stdout", "stderr"):
                    mark_output(pin(record.get(stream)))
                if "image" in record:
                    emitted = record["image"]
                    native_require(isinstance(emitted, dict) and set(emitted) == {"path", "sha256", "imports"},
                                   "native image reference requires path, sha256, and imports")
                    mark_output(pin({key: emitted[key] for key in ("path", "sha256")}))
        for row in behavior:
            label = f"{row['stage']}/{row['suite']}"
            passed(row, label)
            native_require(pin(row.get("compiler")) == images[row["stage"]]
                           and row.get("inputs_sha256") == key == row.get("inputs_after_sha256"), f"native {label} compiler or inputs changed")
            sources(row.get("sources"))
            roots = row.get("roots")
            native_require(isinstance(roots, list) and bool(roots) and all(isinstance(entry, str) for entry in roots)
                           and len(roots) == len(set(roots)), f"native {label} behavior source roots are missing")
            closure = {name for entry in roots for name in native_units(root, entry)}
            native_require(closure <= set(row["sources"]), f"native {label} behavior source closure is incomplete")
            programs = row.get("programs")
            native_require(isinstance(programs, list) and (row["suite"] == "compiler" or bool(programs)),
                           f"native {label} has no source-bound native programs")
            executed = set()
            for program in programs:
                native_require(isinstance(program, dict), f"native {label} program record is invalid")
                binary = distinct_image(emission(program, program.get("inputs"), images[row["stage"]], label + "/program"),
                                        label + "/program")
                native_require(set(program["inputs"]["sources"]) <= set(row["sources"]), f"native {label} program sources are missing")
                executed.add(binary)
            checks = row.get("checks")
            native_require(isinstance(checks, list) and bool(checks) and type(row.get("skipped")) is int and row["skipped"] == 0,
                           f"native {label} has no executed checks or skipped checks")
            names = set()
            for check in checks:
                native_require(isinstance(check, dict) and isinstance(check.get("name"), str) and bool(check["name"])
                               and check["name"] not in names and check.get("status") == "pass" and check.get("process_status") == "ok"
                               and type(check.get("exit_code")) is int and type(check.get("expected_exit_code")) is int
                               and 0 <= check["exit_code"] == check["expected_exit_code"] <= 0xFFFFFFFF,
                               f"native {label} has a failed, skipped, or duplicate check")
                names.add(check["name"])
                argv = check.get("argv")
                native_require(isinstance(argv, list) and bool(argv) and all(isinstance(word, str) for word in argv)
                               and (abs_path(root, argv[0]).resolve() in executed
                                    or (row["suite"] == "compiler" and abs_path(root, argv[0]).resolve() == images[row["stage"]])),
                               f"native {label} check did not execute a bound native image")
                for stream in ("stdout", "stderr"):
                    actual, expected = pin(check.get(stream)), pin(check.get("expected_" + stream))
                    native_require(check["expected_" + stream]["path"] in row["sources"], f"native {label} expectation is not source-bound")
                    native_require(not generated(expected),
                                   f"native {label} expectation is a build/cache output")
                    native_require(file_identity(expected) not in output_identities,
                                   f"native {label} expectation aliases an actual output")
                    native_require(pinned[actual] == pinned[expected], f"native {label}/{check['name']} {stream} differs")
            report["tests"].append(row)

        native_require(all(sha256_file(path) == digest for path, digest in pinned.items())
                       and native_units(root, NATIVE_ENTRY) == units and repo_metadata(root)["git_head"] == result["source_revision"],
                       "native evidence inputs changed during collection")
        current_headers = {child.relative_to(root).as_posix() for child in (root / "runtime").glob("*.h")}
        current_tool_names = set(BUILD_INPUTS) | set(RUNTIME) | current_headers
        current_tool_names.update(name for entry in tool_roots(NATIVE_ENTRY) for name in native_units(root, entry))
        current_graph = {entry: native_units(root, entry) for entry in [*seed_roots, *bootstrap.ACCEPTANCE_ROOTS]}
        native_require(current_tool_names == set(tool_inputs["sources"]) and current_graph == graph
                       and current_headers == {name for name in selected["sources"] if name.startswith("runtime/") and name.endswith(".h")},
                       "native producer dependency inventory changed during collection")
        native_require(bootstrap.installed_current(seed, seed_receipt_path, selected), "C seed evidence changed during collection")
        native_require(all(file_identity(path) == identity for identity, path in image_identities.items()),
                       "native image file identity changed during collection")
        report["summary"].update(status="pass", provenance_accepted=True, behavior_accepted=True)
    except (OSError, ValueError, TypeError, KeyError, struct.error, RecursionError, RuntimeError) as exc:
        report["summary"]["hard_errors"].append(f"native evidence: {exc}")
    report["summary"].update(commands_total=len(report["commands"]), stages_total=3,
                             stages_completed=len(report["stages"]), tests_total=len(report["tests"]),
                             comparisons_total=len(report["comparisons"]),
                             mismatch_count=int(report["summary"]["converged"] is False), missing_required_artifacts=[])
    return report, 0 if report["summary"]["status"] == "pass" else 1


def print_summary(report: Mapping[str, Any], out: Path, root: Path) -> None:
    s = report["summary"]
    convergence = "passed" if s["converged"] is True else ("failed" if s["converged"] is False else "unknown")
    print("Native selfhost evidence summary" if report["kind"] == NATIVE_REPORT_KIND else "Bootstrap evidence summary")
    print(f"status: {s['status']}")
    print(f"stages completed: {s['stages_completed']}/{s['stages_total']}")
    print(f"convergence: {convergence}")
    print(f"mismatches: {s['mismatch_count']}")
    print(f"missing artifacts: {len(s['missing_required_artifacts'])}")
    print(f"report: {repo_path(root, out)}")
    print(f"logs: {s['logs']}")
    for label, values in (("hard errors", s.get("hard_errors")), ("partial reasons", s.get("partial_reasons") if s["status"] == "partial" else None)):
        if values:
            print(f"{label}:")
            for value in values:
                print(f"- {value}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=None, help="path to write evidence JSON")
    parser.add_argument("--native-result", type=Path, help="validate native stage/behavior observations without executing commands")
    parser.add_argument("--work-dir", default=str(DEFAULT_WORK_DIR), help="directory for logs and support files")
    parser.add_argument("--stage-loop-result", default=str(DEFAULT_STAGE_LOOP_RESULT), help="stage-loop result JSON to read")
    parser.add_argument("--stage-loop-command", default=DEFAULT_STAGE_LOOP_COMMAND, help="command used to run the existing stage-loop")
    parser.add_argument("--test-command", action="append", default=[], help="optional semantic/diagnostic evidence command, optionally label::command")
    parser.add_argument("--timeout-seconds", type=float, default=None, help="optional timeout for each executed command")
    parser.add_argument("--log-bytes", type=int, default=DEFAULT_LOG_BYTES, help="bounded stdout/stderr excerpt bytes per stream")
    parser.add_argument("--no-stage-loop", action="store_true", help="do not run stage-loop; report partial evidence only")
    parser.add_argument("--allow-partial", action="store_true", help="return success for partial reports; JSON status remains partial")
    args = parser.parse_args(argv)
    out = abs_path(ROOT, args.out if args.out is not None else (DEFAULT_NATIVE_OUT if args.native_result is not None else DEFAULT_OUT))
    if args.native_result is not None:
        if (args.allow_partial or args.no_stage_loop or args.test_command
                or args.stage_loop_result != str(DEFAULT_STAGE_LOOP_RESULT)
                or args.stage_loop_command != DEFAULT_STAGE_LOOP_COMMAND):
            parser.error("--native-result cannot use C stage-loop execution or partial-success options")
        if not out.resolve().is_relative_to(ROOT.resolve()):
            parser.error("native evidence output must stay inside the repository")
        if out.exists():
            try:
                previous = native_json(out)
                native_require(previous.get("kind") == NATIVE_REPORT_KIND, "native output is an input artifact or unrelated file")
            except (OSError, ValueError, TypeError, RecursionError) as exc:
                parser.error(f"refusing to overwrite native evidence input: {exc}")
        try:
            observation_path = abs_path(ROOT, args.native_result).resolve(strict=True)
            native_require(observation_path.is_relative_to(ROOT.resolve()), "native result escapes the repository")
            native_output_guard(ROOT, out, {"path": observation_path.relative_to(ROOT.resolve()).as_posix()})
            native_require(observation_path.stat().st_size <= 16 * 1024 * 1024, "native evidence JSON exceeds 16 MiB")
            observation_sha256 = sha256_file(observation_path)
            native_output_guard(ROOT, out, native_json(observation_path))
            report, code = build_native_report(root=ROOT, out=out, result_path=args.native_result)
            native_output_guard(ROOT, out, report["artifacts"])
            native_require(sha256_file(observation_path) == observation_sha256,
                           "native observation changed before publication")
        except (OSError, ValueError, TypeError, RecursionError, RuntimeError) as exc:
            parser.error(f"refusing unsafe native evidence output: {exc}")
    else:
        report, code = build_report(
            root=ROOT,
            out=out,
            work_dir=Path(args.work_dir),
            stage_loop_result_path=Path(args.stage_loop_result),
            run_stage_loop_flag=not args.no_stage_loop,
            stage_loop_command=shlex.split(args.stage_loop_command),
            test_commands=[parse_labelled_command(value, f"test-{idx + 1}") for idx, value in enumerate(args.test_command)],
            timeout_seconds=args.timeout_seconds,
            log_bytes=max(0, args.log_bytes),
        )
    write_json_atomic(out, report)
    print_summary(report, out, ROOT)
    return 0 if report["summary"]["status"] == "partial" and args.allow_partial else code


if __name__ == "__main__":
    raise SystemExit(main())
