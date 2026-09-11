#!/usr/bin/env python3
"""Generated artifact integrity and deterministic-regeneration drift checks."""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional, Sequence

from repo_support import bind_relative_path, read_json_value, sha256_file, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
rel = bind_relative_path(ROOT, resolve=True)
REPORT_KIND = "ouro.generated-artifact-drift-report.v1"
STAGE0 = (ROOT / "compiler/stage0" / "backend_u.c", ROOT / "compiler/stage0" / "driver_u.c")
MANIFEST = ROOT / "docs" / "generated_artifact_hashes.sha256"
STAGE0_SHAPE_MARKS = {
    "driver_u.c": ("Do not hand-edit", "Generated frontend pack", "static ouro_v *ouro_g"),
    "backend_u.c": ("ouro_export_count", "static ouro_v *ouro_g"),
}


def generated_shape_ok(name: str, text: str) -> bool:
    marks = STAGE0_SHAPE_MARKS.get(name)
    if marks is None:
        return False
    for mark in marks:
        if mark in text:
            return True
    return False


def run(cmd: list[str], *, env: dict[str, str], log: Path) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as f:
        p = subprocess.run(cmd, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        f.write(p.stdout)
    print(f"GENERATED_ARTIFACT_DRIFT: run {' '.join(cmd)} rc={p.returncode} log={rel(log)}")
    if p.stdout:
        print(p.stdout, end="")
    return p.returncode


def manifest_checks() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    if not MANIFEST.is_file():
        return ([{"reason": "missing manifest", "path": rel(MANIFEST)}], artifacts)
    try:
        manifest_text = MANIFEST.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return ([{"reason": "unreadable manifest", "path": rel(MANIFEST), "error": str(exc)}], artifacts)
    seen: set[str] = set()
    for lineno, raw in enumerate(manifest_text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2:
            issues.append({"reason": "malformed hash manifest line", "path": rel(MANIFEST), "line": lineno})
            continue
        expected, path_s = parts
        path = ROOT / path_s
        seen.add(Path(path_s).as_posix())
        if not path.is_file():
            issues.append({"reason": "manifest artifact missing", "path": path_s})
            continue
        actual = sha256_file(path)
        ok = actual == expected
        artifacts.append({"path": path_s, "expected_sha256": expected, "actual_sha256": actual, "bytes": path.stat().st_size, "pass": ok})
        if not ok:
            issues.append({"reason": "manifest hash drift", "path": path_s, "expected_sha256": expected, "actual_sha256": actual})
    for p in STAGE0:
        rp = rel(p)
        if rp not in seen:
            issues.append({"reason": "stage0 artifact missing from manifest", "path": rp})
    for p in STAGE0:
        if not p.is_file():
            issues.append({"reason": "stage0 artifact missing", "path": rel(p)})
            continue
        try:
            text = p.read_text(encoding="utf-8")[:2000]
        except (OSError, UnicodeError) as exc:
            issues.append({"reason": "unreadable generated artifact", "path": rel(p), "error": str(exc)})
            continue
        if not generated_shape_ok(p.name, text):
            issues.append({"reason": "unexpected generated artifact shape", "path": rel(p)})
    return issues, artifacts


def ensure_seed(env: dict[str, str], work: Path) -> bool:
    seed = ROOT / "_build" / "c" / "ouro1"
    if seed.is_file() and os.access(seed, os.X_OK):
        return True
    rc = run(["sh", "scripts/bootstrap.sh"], env=env, log=work / "bootstrap.log")
    return rc == 0 and seed.is_file() and os.access(seed, os.X_OK)


def frontend_regen_check(env: dict[str, str], work: Path, jobs: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    out = work / "frontend-regenerated" / "driver_u.c"
    fe_work = work / "frontend-regenerated" / "work"
    report = work / "frontend-regenerated" / "frontend-regeneration.json"
    if not ensure_seed(env, work):
        return ([{"reason": "bootstrap failed or seed missing", "path": "_build/c/ouro1"}], {})
    cmd = [
        "sh",
        "scripts/emit_frontend.sh",
        "--ouro1",
        str(ROOT / "_build" / "c" / "ouro1"),
        "--out",
        str(out),
        "--work",
        str(fe_work),
        "--report",
        str(report),
        "--jobs",
        str(max(1, jobs)),
        "--no-cache",
    ]
    rc = run(cmd, env=env, log=work / "frontend-regeneration.log")
    data: dict[str, Any] = {"out": rel(out), "report": rel(report), "command_rc": rc}
    if rc != 0:
        issues.append({"reason": "frontend regeneration failed", "log": rel(work / "frontend-regeneration.log")})
        return issues, data
    committed = ROOT / "compiler/stage0" / "driver_u.c"
    raw = out.read_bytes()
    promoted = out.read_text(
        encoding="utf-8", errors="surrogateescape"
    ).encode("utf-8", errors="surrogateescape")
    committed_bytes = committed.read_bytes()
    out_hash = hashlib.sha256(raw).hexdigest()
    promoted_hash = hashlib.sha256(promoted).hexdigest()
    committed_hash = hashlib.sha256(committed_bytes).hexdigest()
    data.update({
        "regenerated_sha256": out_hash,
        "promotion_normalized_sha256": promoted_hash,
        "committed_sha256": committed_hash,
        "bytes": len(raw),
        "promotion_normalized_bytes": len(promoted),
    })
    if promoted != committed_bytes:
        issues.append({
            "reason": "frontend generated artifact drift",
            "regenerated": rel(out),
            "committed": rel(committed),
            "regenerated_sha256": out_hash,
            "promotion_normalized_sha256": promoted_hash,
            "committed_sha256": committed_hash,
        })
    return issues, data


def stage_loop_check(env: dict[str, str], work: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    rc = run(["sh", "scripts/stage_loop.sh"], env=env, log=work / "stage-loop.log")
    result_path = ROOT / "_build" / "stage_loop" / "result.json"
    data: dict[str, Any] = {"command_rc": rc, "result": rel(result_path)}
    if rc != 0:
        issues.append({"reason": "stage-loop failed", "log": rel(work / "stage-loop.log")})
        return issues, data
    if not result_path.is_file():
        issues.append({"reason": "missing stage-loop result", "path": rel(result_path)})
        return issues, data
    result, read_error = read_json_value(result_path)
    if read_error is not None:
        issues.append({
            "reason": "unreadable stage-loop result",
            "path": rel(result_path),
            "message": read_error,
        })
        return issues, data
    if not isinstance(result, dict):
        issues.append({
            "reason": "stage-loop result is not a JSON object",
            "path": rel(result_path),
        })
        return issues, data
    data["stage_loop"] = result
    if not (result.get("pass") and result.get("frontend_eq") and result.get("backend_eq")):
        issues.append({"reason": "stage-loop did not prove frontend/backend fixpoint", "path": rel(result_path)})
        return issues, data
    try:
        last = int(result.get("stages") or 0)
    except (TypeError, ValueError):
        issues.append({"reason": "stage-loop result missing last stage", "path": rel(result_path)})
        return issues, data
    if last <= 0:
        issues.append({"reason": "stage-loop result missing last stage", "path": rel(result_path)})
        return issues, data
    stage_dir = ROOT / "_build" / "stage_loop" / f"stage{last}"
    comparisons: list[dict[str, Any]] = []
    for name in ("driver_u.c", "backend_u.c"):
        regenerated = stage_dir / name
        committed = ROOT / "compiler/stage0" / name
        if not regenerated.is_file():
            issues.append({"reason": "missing regenerated stage artifact", "path": rel(regenerated)})
            continue
        raw = regenerated.read_bytes()
        # Promotion uses universal-newline text reads and an LF binary writer.
        # Compare exactly those promoted bytes, not a Windows compiler's CRLF
        # staging bytes.
        promoted = regenerated.read_text(
            encoding="utf-8", errors="surrogateescape"
        ).encode("utf-8", errors="surrogateescape")
        committed_bytes = committed.read_bytes()
        rh = hashlib.sha256(raw).hexdigest()
        ph = hashlib.sha256(promoted).hexdigest()
        ch = hashlib.sha256(committed_bytes).hexdigest()
        same = promoted == committed_bytes
        comparisons.append({
            "artifact": name,
            "regenerated": rel(regenerated),
            "committed": rel(committed),
            "regenerated_sha256": rh,
            "promotion_normalized_sha256": ph,
            "committed_sha256": ch,
            "promotion_normalized": raw != promoted,
            "pass": same,
        })
        if not same:
            issues.append({
                "reason": "stage-loop generated artifact drift",
                "artifact": name,
                "regenerated_sha256": rh,
                "promotion_normalized_sha256": ph,
                "committed_sha256": ch,
            })
    data["committed_artifact_comparisons"] = comparisons
    return issues, data


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["hashes", "frontend", "stage-loop"], default="hashes")
    ap.add_argument("--work", default=os.environ.get("OURO_GENERATED_ARTIFACT_WORK", "_build/generated_artifact_drift"))
    ap.add_argument("--report", default=None)
    ap.add_argument("--jobs", type=int, default=int(os.environ.get("OURO_JOBS", "10") if str(os.environ.get("OURO_JOBS", "10")).isdigit() else "10"))
    args = ap.parse_args(argv)

    work = Path(args.work)
    if not work.is_absolute():
        work = ROOT / work
    report_path = Path(args.report) if args.report else work / "generated-artifact-drift.json"
    if not report_path.is_absolute():
        report_path = ROOT / report_path
    work.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("OURO_ROOT", str(ROOT))
    env.setdefault("OURO_REPRODUCIBLE", "1")

    started = time.perf_counter()
    issues, artifacts = manifest_checks()
    details: dict[str, Any] = {"manifest_artifacts": artifacts}
    if args.mode == "frontend":
        fe_issues, fe_details = frontend_regen_check(env, work, args.jobs)
        issues.extend(fe_issues)
        details["frontend_regeneration"] = fe_details
    elif args.mode == "stage-loop":
        fe_issues, fe_details = frontend_regen_check(env, work, args.jobs)
        issues.extend(fe_issues)
        details["frontend_regeneration"] = fe_details
        sl_issues, sl_details = stage_loop_check(env, work)
        issues.extend(sl_issues)
        details["stage_loop"] = sl_details

    report = {
        "kind": REPORT_KIND,
        "mode": args.mode,
        "pass": not issues,
        "issues": issues,
        "details": details,
        "policy": {
            "hash_manifest": "committed stage0 blobs must match docs/generated_artifact_hashes.sha256",
            "frontend": "frontend regeneration must reproduce committed driver_u.c after the promotion newline normalization",
            "stage_loop": "full mode must reach a frontend/backend fixpoint and reproduce committed stage0 blobs after promotion newline normalization",
        },
        "elapsed_s": round(time.perf_counter() - started, 6),
    }
    write_json_atomic(report_path, report)
    print(f"GENERATED_ARTIFACT_DRIFT: {'PASS' if not issues else 'FAIL'} mode={args.mode} issues={len(issues)} report={rel(report_path)}")
    if issues:
        for issue in issues:
            print(f"GENERATED_ARTIFACT_DRIFT_ISSUE {issue['reason']}", file=sys.stderr)
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
