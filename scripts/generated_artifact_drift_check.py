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

from repo_support import bind_relative_path, hash_json, read_json_object_or_none, read_json_value, sha256_file, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
rel = bind_relative_path(ROOT, resolve=True)
REPORT_KIND = "ouro.generated-artifact-drift-report.v2"
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


def ensure_seed(env: dict[str, str], work: Path, seed: Path) -> bool:
    if seed.is_file() and os.access(seed, os.X_OK):
        return True
    rc = run(["sh", "scripts/bootstrap.sh"], env=env, log=work / "bootstrap.log")
    return rc == 0 and seed.is_file() and os.access(seed, os.X_OK)


def current_reference(seed: Path, cfg) -> tuple[dict[str, Path], dict[str, Any], dict[str, str], dict[str, str]]:
    import bootstrap_compiler as bootstrap
    import bootstrap_inputs
    import ouro_build as build

    manifest, _contents = bootstrap_inputs.read_bundle(ROOT)
    bootstrap_inputs.verify_stage0(ROOT, manifest)
    selected = bootstrap.current_inputs(ROOT, cfg, build)
    receipt = seed.with_name("ouro1.bootstrap.json")
    if not bootstrap.installed_current(seed, receipt, selected):
        raise ValueError("current compiler or complete P1/P2 evidence does not match current inputs")
    data = read_json_object_or_none(receipt)
    if data is None:
        raise ValueError("current compiler receipt became unreadable")
    work = Path(data["work"])
    if work.parent != cfg.path("build_dir") / "bootstrap":
        raise ValueError("current compiler evidence must be in the configured bootstrap directory")
    paths = [seed, receipt, work / "report.json", work / "inputs.json",
             *(work / "out" / phase / name for phase in ("p1", "p2") for name in ("driver_u.c", "backend_u.c"))]
    if any(parent.is_symlink() for path in paths for parent in (path, *path.parents) if parent != ROOT):
        raise ValueError("current compiler evidence must use regular configured paths")
    reference = work / "out/p2"
    paths = {name: reference / name for name in ("driver_u.c", "backend_u.c")}
    evidence = {"binary": seed, "receipt": receipt, "report": work / "report.json", "inputs": work / "inputs.json"}
    return (paths, selected, {name: sha256_file(path) for name, path in paths.items()},
            {name: sha256_file(path) for name, path in evidence.items()})


def promotion_bytes(path: Path) -> bytes:
    return path.read_text(encoding="utf-8", errors="surrogateescape").encode("utf-8", errors="surrogateescape")


def frontend_regen_check(
    env: dict[str, str], work: Path, jobs: int, seed: Path, reference: dict[str, Path]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    out = work / "frontend-regenerated" / "driver_u.c"
    fe_work = work / "frontend-regenerated" / "work"
    report = work / "frontend-regenerated" / "frontend-regeneration.json"
    cmd = [
        "sh",
        "scripts/emit_frontend.sh",
        "--ouro1",
        str(seed),
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
    expected = reference["driver_u.c"]
    raw = out.read_bytes()
    promoted = promotion_bytes(out)
    reference_bytes = expected.read_bytes()
    normalized_reference = promotion_bytes(expected)
    out_hash = hashlib.sha256(raw).hexdigest()
    promoted_hash = hashlib.sha256(promoted).hexdigest()
    reference_hash = hashlib.sha256(reference_bytes).hexdigest()
    data.update({
        "regenerated_sha256": out_hash,
        "promotion_normalized_sha256": promoted_hash,
        "reference": rel(expected),
        "reference_sha256": reference_hash,
        "reference_promotion_normalized_sha256": hashlib.sha256(normalized_reference).hexdigest(),
        "bytes": len(raw),
        "promotion_normalized_bytes": len(promoted),
    })
    if promoted != normalized_reference:
        issues.append({
            "reason": "frontend generated artifact drift",
            "regenerated": rel(out),
            "reference": rel(expected),
            "regenerated_sha256": out_hash,
            "promotion_normalized_sha256": promoted_hash,
            "reference_sha256": reference_hash,
        })
    return issues, data


def stage_loop_check(
    env: dict[str, str], work: Path, stage_work: Path, reference: dict[str, Path]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    rc = run(["sh", "scripts/stage_loop.sh"], env=env, log=work / "stage-loop.log")
    result_path = stage_work / "result.json"
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
    stage_dir = stage_work / f"stage{last}"
    comparisons: list[dict[str, Any]] = []
    for name in ("driver_u.c", "backend_u.c"):
        regenerated = stage_dir / name
        expected = reference[name]
        if not regenerated.is_file():
            issues.append({"reason": "missing regenerated stage artifact", "path": rel(regenerated)})
            continue
        raw = regenerated.read_bytes()
        # Promotion uses universal-newline text reads and an LF binary writer.
        promoted = promotion_bytes(regenerated)
        reference_bytes = expected.read_bytes()
        normalized_reference = promotion_bytes(expected)
        rh = hashlib.sha256(raw).hexdigest()
        ph = hashlib.sha256(promoted).hexdigest()
        reference_hash = hashlib.sha256(reference_bytes).hexdigest()
        same = promoted == normalized_reference
        comparisons.append({
            "artifact": name,
            "regenerated": rel(regenerated),
            "reference": rel(expected),
            "regenerated_sha256": rh,
            "promotion_normalized_sha256": ph,
            "reference_sha256": reference_hash,
            "reference_promotion_normalized_sha256": hashlib.sha256(normalized_reference).hexdigest(),
            "promotion_normalized": raw != promoted,
            "pass": same,
        })
        if not same:
            issues.append({
                "reason": "stage-loop generated artifact drift",
                "artifact": name,
                "regenerated_sha256": rh,
                "promotion_normalized_sha256": ph,
                "reference_sha256": reference_hash,
            })
    data["reference_artifact_comparisons"] = comparisons
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
    if args.mode in {"frontend", "stage-loop"}:
        import ouro_build as build

        try:
            cfg = build.load_config(argparse.Namespace())
            seed = cfg.path("c_build_dir") / "ouro1"
            if not ensure_seed(env, work, seed):
                raise ValueError("bootstrap failed or seed missing: " + str(seed))
            reference, selected, reference_hashes, evidence_hashes = current_reference(seed, cfg)
            details["current_reference"] = {
                "seed": rel(seed), "key": hash_json(selected),
                "artifacts": {name: rel(path) for name, path in reference.items()},
                "sha256": reference_hashes,
                "evidence_sha256": evidence_hashes,
            }
            fe_issues, fe_details = frontend_regen_check(env, work, args.jobs, seed, reference)
            issues.extend(fe_issues)
            details["frontend_regeneration"] = fe_details
            if args.mode == "stage-loop":
                sl_issues, sl_details = stage_loop_check(env, work, cfg.path("build_dir") / "stage_loop", reference)
                issues.extend(sl_issues)
                details["stage_loop"] = sl_details
            if current_reference(seed, cfg) != (reference, selected, reference_hashes, evidence_hashes):
                raise ValueError("current compiler evidence changed during regeneration")
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
            issues.append({"reason": "unverified current generated-artifact reference", "error": str(exc)})

    report = {
        "kind": REPORT_KIND,
        "mode": args.mode,
        "pass": not issues,
        "issues": issues,
        "details": details,
        "policy": {
            "hash_manifest": "committed stage0 blobs must match docs/generated_artifact_hashes.sha256",
            "frontend": "fresh frontend regeneration must reproduce verified current P2 driver_u.c after promotion newline normalization",
            "stage_loop": "full mode must reach a frontend/backend fixpoint and reproduce both verified current P2 C artifacts after promotion newline normalization",
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
