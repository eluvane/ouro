"""Execute exact Ouro checker laws against isolated canonical source mutants."""
from __future__ import annotations

import json
import shutil
import sys
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from ourosmith import ROOT
from ourosmith.host import environment
from ourosmith.limits import run_limited
from repo_support import hash_json, sha256_path, write_json_atomic

digest = sha256_path

LAW_ENTRY = "tests/compiler_fault_tests.ouro"
LAW_EXPECTATIONS = {
    "CHK.sort-cumul": "90/body/type-mismatch", "CTL.sort-cumul": "accepted",
    "CHK.termination": "90/body/non-terminating", "CTL.termination": "accepted",
    "CHK.nested-other-parameter": "90/body/non-terminating", "CTL.nested-structural-parameter": "accepted",
    "CHK.application-arguments": "90/body/type-mismatch", "CTL.application-arguments": "accepted",
    "CHK.positivity": "60/inductive/non-positive", "CTL.positivity": "accepted",
    "CHK.iota-constructor": "nat=1", "CHK.iota-parameters": "nat=1",
    "CHK.string-concat": "bytes=65,0,66,255/type=18",
    "CHK.lambda-annotation": "90/body/type-mismatch", "CTL.lambda-annotation": "accepted",
    "CHK.duplicate-global": "80/plan/duplicate-name=80", "CTL.distinct-globals": "accepted",
    "CHK.case-coverage-missing": "90/body/case-metadata", "CHK.case-coverage-extra": "90/body/case-metadata",
    "CTL.case-coverage": "accepted", "CTL.opaque-neutral": "neutral=80",
}
BUILD_INPUTS = (
    "scripts/native_tool_build.py", "scripts/frontend_regen.py", "scripts/ouro_build.py",
    "scripts/pack_frontend.py", "scripts/repo_support.py", "scripts/selfhost_module_cache.py",
    "scripts/ouro_seal.py", "scripts/build_tool.sh", "scripts/python.sh", "Ouro.seal",
    "scripts/ourosmith/faults.py", "scripts/ourosmith/checker_faults.py",
    "scripts/ourosmith/host.py", "scripts/ourosmith/limits.py", "scripts/ourosmith/__init__.py",
    "scripts/ourosmith/exec_child.py", "scripts/ourosmith/windows_job.py",
)


def input_hashes(paths: list[Path]) -> dict[str, str]:
    return {path.relative_to(ROOT).as_posix(): sha256_path(path) if path.is_file() else "missing"
            for path in sorted(set(paths))}


def classify_run(result: dict, expected_fault: tuple[str, ...] | None) -> tuple[str, list[str], str]:
    """Require a complete exact law protocol before interpreting semantic failures."""
    if (result.get("status") != "ok" or type(result.get("returncode")) is not int
            or result["returncode"] not in (0, 1) or not isinstance(result.get("stdout"), str)
            or not isinstance(result.get("stderr"), str) or result["stderr"]):
        return "runtime-error", [], "runtime status, exit or stderr is outside the law protocol"
    lines = result["stdout"].splitlines()
    if len(lines) != len(LAW_EXPECTATIONS) + 1:
        return "invalid-report", [], "law count or terminal line missing"
    failed = []
    for line, (name, expected) in zip(lines[:-1], LAW_EXPECTATIONS.items(), strict=True):
        prefix, separator, actual = line.partition(" got=")
        if not separator or prefix not in {"PASS " + name, "FAIL " + name}:
            return "invalid-report", [], "unexpected or reordered law identifier"
        passed = actual == expected
        if prefix.startswith("PASS ") != passed:
            return "invalid-report", [], "law status disagrees with its exact expected value"
        if not passed:
            failed.append(name)
    terminal = "CHECKER_FAULTS: FAIL" if failed else "CHECKER_FAULTS: PASS"
    if lines[-1] != terminal or result["returncode"] != int(bool(failed)):
        return "invalid-report", failed, "exit and terminal do not match the exact law results"
    if expected_fault is None:
        return ("clean" if not failed else "baseline-dirty"), failed, ""
    if not expected_fault or not set(expected_fault).issubset(LAW_EXPECTATIONS):
        return "invalid-report", failed, "unknown or empty required law set"
    if any(name.startswith("CTL.") for name in failed):
        return "wrong-property", failed, "a valid or opacity control failed"
    if set(expected_fault).issubset(failed):
        return "killed", failed, ""
    return "survived", failed, "the intended exact semantic property did not fail"


def build_receipt(executable: Path, units: list[str], source_hashes: dict,
                  compiler_sha: str, stable_inputs: dict) -> dict | None:
    """Bind a fresh build receipt to the actual law sources, producer and binary."""
    import native_tool_build

    try:
        receipt = json.loads(Path(str(executable) + ".build.json").read_text(encoding="utf-8"))
        inputs = receipt["inputs"]
        required = {*units, *native_tool_build.BUILD_INPUTS, *native_tool_build.RUNTIME,
                    *(path.relative_to(ROOT).as_posix() for path in (ROOT / "runtime").glob("*.h"))}
        expected_sources = {name: source_hashes[name] if name in source_hashes else stable_inputs[name]
                            for name in required}
        valid = (bool(units) and len(set(units)) == len(units) and set(source_hashes) == set(units)
                 and receipt["kind"] == "ouro.native-tool-build.v1" and receipt["cache"] == "miss"
                 and inputs["kind"] == "ouro.native-tool-build.v1" and inputs["entry"] == units[-1]
                 and receipt["key"] == hash_json(inputs)
                 and receipt["binary_sha256"] == digest(executable)
                 and inputs["compiler_sha256"] == compiler_sha
                 and inputs["sources"] == expected_sources)
        valid_receipt = receipt if valid else None
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return None
    else:
        return valid_receipt



def run_variant(directory: Path, frozen: Path, unit_names: list[str], fault,
                compiler: Path, env: dict, timeout_s: float, memory_mb: int, stable_inputs: dict, log) -> dict:
    from ourosmith.faults import StaleFault, fault_texts, write_text

    started = time.perf_counter()
    source = directory / "source"
    shutil.copytree(frozen, source)
    name = "baseline" if fault is None else fault.id
    row = {"id": name, "status": "unbuildable", "failed_laws": [], "detail": "", "steps": []}
    path = directory / "report.json"
    try:
        changed = {} if fault is None else fault_texts(fault, source)
        if not set(changed).issubset(unit_names):
            raise StaleFault(name + ": mutation target is outside the compiled import cone")
        if any(filename.startswith("tests/") for filename in changed):
            raise StaleFault(name + ": law inputs cannot be mutation targets")
        for filename, text in changed.items():
            write_text(source / filename, text)
    except (OSError, StaleFault) as error:
        row.update(status="stale", detail=str(error), seconds=time.perf_counter() - started)
        write_json_atomic(path, row)
        return row
    before = {filename: digest(source / filename) for filename in unit_names}
    units = [(source / filename).relative_to(ROOT).as_posix() for filename in unit_names]
    entry = (source / LAW_ENTRY).relative_to(ROOT).as_posix()
    row.update(source_hashes_before=before, intended_changed_files=sorted(changed),
               law_source_sha256=before[LAW_ENTRY], compiler_sha256=digest(compiler))
    executable = directory / ("laws.exe" if sys.platform == "win32" else "laws")
    check = [str(compiler), "check", entry, "999999"]
    for unit in units:
        check.extend(("--unit", unit))
    build = [sys.executable, "-B", str(ROOT / "scripts/native_tool_build.py"), entry, str(executable),
             "--compiler", str(compiler), "--jobs", "1", "--fuel", "16000",
             "--build-dir", str(directory.parent / "b"), "--cache-dir", str(directory.parent / "c"),
             "--cache", "--opt-level", "O0", "--ccache", "disabled"]
    phases = (("strict-check", check, 900), ("build", build, 600), ("run", [str(executable)], timeout_s))
    for phase, command, timeout in phases:
        log(f"OURO_SMITH: checker fault {name} {phase}")
        try:
            result = run_limited(command, cwd=ROOT, env=env, timeout_s=timeout, memory_mb=memory_mb)
        except OSError as error:
            row["detail"] = f"{phase} could not start: {error}"
            break
        step = asdict(result)
        step.update(phase=phase, command=command)
        step["peak_commit_mib" if sys.platform == "win32" else "peak_rss_mib"] = step.pop("peak_rss_mb")
        row["steps"].append(step)
        write_text(directory / (phase + ".stdout"), result.stdout)
        write_text(directory / (phase + ".stderr"), result.stderr)
        if phase != "run":
            valid = result.status == "ok" and result.returncode == 0 and not result.stderr
            if phase == "strict-check":
                valid = valid and result.stdout.splitlines() == ["CHECK_OK"]
            else:
                actual_sources = {unit: before[name] for unit, name in zip(units, unit_names, strict=True)}
                receipt = build_receipt(executable, units, actual_sources, row["compiler_sha256"], stable_inputs) if valid else None
                valid = bool(receipt) and "BUILD_TOOL_CACHE: miss " in result.stdout
                if valid:
                    row["build_receipt_sha256"] = digest(Path(str(executable) + ".build.json"))
                    row["toolchain"] = {key: value for key, value in receipt["inputs"].items()
                                        if key not in {"entry", "sources"}}
            if not valid:
                row["detail"] = f"{phase} did not complete cleanly: {result.classify()} exit={result.returncode}"
                break
        else:
            row["binary_sha256"] = digest(executable)
            row["status"], row["failed_laws"], row["detail"] = classify_run(step, None if fault is None else fault.expect)
        write_json_atomic(path, row)
    after = {filename: digest(source / filename) if (source / filename).is_file() else "missing" for filename in unit_names}
    row.update(source_hashes_after=after, source_unchanged=before == after, seconds=time.perf_counter() - started)
    if before != after:
        row.update(status="input-drift", detail="an isolated law source changed during execution")
    write_json_atomic(path, row)
    log(f"OURO_SMITH: checker fault {name} {row['status']} failed={row['failed_laws']}")
    return row


def fault_result(fault, row):
    from ourosmith.faults import FaultResult

    status = row["status"]
    if status in {"input-drift", "unbuildable"}:
        status = "unbuildable"
    elif status not in {"killed", "stale", "baseline-dirty"}:
        status = "survived"
    semantic = row["status"] in {"killed", "survived", "wrong-property"}
    return FaultResult(fault, status, findings=len(row.get("failed_laws", [])),
                       caught_by=["checker:" + name for name in row.get("failed_laws", [])] if semantic else [],
                       detail=row["detail"], seconds=row.get("seconds", 0))


def run_checker_campaign(faults: list, out: Path, *, compiler: Path, timeout_s: float,
                         memory_mb: int, log=print) -> dict:
    """Freeze one law input, then build the clean baseline and every selected mutant."""
    import frontend_regen as frontend
    from ourosmith.faults import FaultResult

    if memory_mb < 1 or timeout_s <= 0:
        raise ValueError("checker fault memory and timeout limits must be positive")
    out.mkdir(parents=True, exist_ok=True)
    work = out / ("checker-" + uuid.uuid4().hex[:12])
    work.mkdir()
    compiler = compiler.resolve()
    try:
        unit_names = frontend.collect_units(LAW_ENTRY)
        if not unit_names or LAW_ENTRY not in unit_names:
            raise ValueError("checker law import cone is empty or incomplete")
        sources = [ROOT / name for name in unit_names]
        inputs = [*sources, compiler, *(ROOT / name for name in BUILD_INPUTS),
                  *(path for path in (ROOT / "runtime").iterdir() if path.suffix in {".c", ".h"})]
        before = input_hashes(inputs)
        if "missing" in before.values():
            raise FileNotFoundError("checker fault inputs are incomplete")
        frozen = work / "frozen"
        for name in unit_names:
            target = frozen / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
            if digest(target) != before[name]:
                raise RuntimeError("checker source changed while freezing: " + name)
        env = environment(jobs=1, build=True)
        env.update(OURO_CCACHE="disabled", PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    except (OSError, ValueError, RuntimeError) as error:
        baseline = {"id": "baseline", "status": "unbuildable", "detail": str(error),
                    "steps": [], "failed_laws": [], "seconds": 0}
        campaign = {"kind": "ouro.smith-checker-faults.v1", "baseline": baseline,
                    "directory": work.relative_to(ROOT).as_posix(), "variants": [], "unchanged": False}
        write_json_atomic(work / "campaign.json", campaign)
        log("OURO_SMITH: checker fault baseline unbuildable: " + str(error))
        return {**campaign, "faults": [FaultResult(fault, "baseline-dirty", detail=str(error)) for fault in faults]}
    baseline = run_variant(work / "baseline", frozen, unit_names, None, compiler, env, timeout_s, memory_mb, before, log)
    evidence, results = [], []
    for fault in faults:
        if baseline["status"] != "clean":
            results.append(FaultResult(fault, "baseline-dirty", detail="canonical law baseline did not pass"))
            continue
        row = run_variant(work / fault.id, frozen, unit_names, fault, compiler, env, timeout_s, memory_mb, before, log)
        if row.get("toolchain") and row["toolchain"] != baseline.get("toolchain"):
            row.update(status="input-drift", detail="the build toolchain differs from the clean baseline")
            write_json_atomic(work / fault.id / "report.json", row)
        evidence.append(row)
        results.append(fault_result(fault, row))
    after = input_hashes(inputs)
    unchanged = (before == after and all(digest(frozen / name) == before[name] for name in unit_names))
    if not unchanged:
        results = [FaultResult(result.fault, "unbuildable", detail="checker campaign inputs changed",
                               seconds=result.seconds) for result in results]
    campaign = {"kind": "ouro.smith-checker-faults.v1", "directory": work.relative_to(ROOT).as_posix(),
                "law_entry": LAW_ENTRY, "law_source_sha256": before[LAW_ENTRY],
                "compiler_sha256": before[compiler.relative_to(ROOT).as_posix()],
                "workers": 1, "memory_limit_mib": memory_mb, "input_hashes_before": before,
                "input_hashes_after": after, "unchanged": unchanged,
                "baseline": baseline, "variants": evidence}
    write_json_atomic(work / "campaign.json", campaign)
    return {**campaign, "faults": results}
