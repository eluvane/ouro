#!/usr/bin/env python3
"""Diagnose a failed p1/check-07 using its unchanged historical bridge."""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
import shutil
import sys
import time

import bootstrap_compiler as bootstrap
import ouro_build as build
from ourosmith.limits import clean_env, run_limited
from repo_support import configure_native_stack, read_json_object_or_none, sha256_file, write_json_atomic

ROOT_UNIT = "compiler/lower.ouro"
BUDGET_S = 600
DECL_UNITS = {"compiler/lower_fallible.ouro", "compiler/lower_spread.ouro",
              "compiler/lower_named.ouro", "compiler/lower.ouro"}


def failed_check(work: Path):
    report = read_json_object_or_none(work / "report.json")
    if not report or report.get("pass") is not False:
        return None
    for phase in report.get("phases", []):
        if phase.get("phase") == "p1":
            for command in phase.get("commands", []):
                if command.get("label") == "check-07" and (command.get("status") != "ok" or command.get("returncode") != 0):
                    return report, command
    return None


def checked_path(work: Path, relative: str) -> Path:
    target = (work / relative).resolve()
    if not target.is_relative_to(work.resolve()):
        raise ValueError("bootstrap report path escapes work directory")
    return target


def declaration_probe(work: Path, source_root: Path, producer: Path,
                      env: dict[str, str], deadline: float, prefix: list[str],
                      first_stderr: str, out: Path, evidence: dict) -> None:
    unit = prefix[-1]
    if unit not in DECL_UNITS:
        evidence["declarations"] = {"unit": unit, "outcome": "unit-outside-target-set"}
        write_json_atomic(out / "report.json", evidence)
        return
    scratch = work / "out/diagnostic/source"
    scratch.mkdir(parents=True, exist_ok=False)
    for path in prefix:
        source = source_root / path
        destination = scratch / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        if sha256_file(source) != sha256_file(destination):
            raise ValueError("scratch copy differs from frozen source: " + path)
    target = scratch / unit
    original = target.read_bytes()
    entry = {"unit": unit, "outcome": "incomplete", "checks": [],
             "first_failing_declaration_prefix": None}
    evidence["declarations"] = entry
    write_json_atomic(out / "report.json", evidence)

    def run_stage(label: str, declaration: str, body: bytes):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            entry["outcome"] = "budget-exhausted"
            write_json_atomic(out / "report.json", evidence)
            return None
        target.write_bytes(body)
        argv = [str(producer), "check", unit, bootstrap.FUEL,
                *(part for path in prefix for part in ("--unit", path))]
        result = run_limited(argv, cwd=scratch, env=env,
                             timeout_s=min(bootstrap.TIMEOUT_S, remaining),
                             memory_mb=bootstrap.MEMORY_MIB)
        for stream in ("stdout", "stderr"):
            (out / (label + "." + stream)).write_text(getattr(result, stream),
                                                        encoding="utf-8", newline="\n")
        row = {"label": label, "last_declaration": declaration, "source_bytes": len(body),
               "status": result.status, "returncode": result.returncode,
               "elapsed_s": result.elapsed_s,
               "stdout": label + ".stdout", "stderr": label + ".stderr"}
        entry["checks"].append(row)
        write_json_atomic(out / "report.json", evidence)
        print(f"BOOTSTRAP_PROBE: {label} {declaration}: {result.classify()}", flush=True)
        return result

    full = run_stage("declaration-full", "<full-source>", original)
    if full is None or full.status != "ok":
        entry["outcome"] = "full-scratch-check-unavailable"
    else:
        observed = re.search(r"CErr code=\d+ det=\d+", full.stderr)
        expected = re.search(r"CErr code=\d+ det=\d+", first_stderr)
        if full.returncode == 0 or observed is None or expected is None or observed.group() != expected.group():
            entry["outcome"] = "full-scratch-failure-not-reproduced"
        else:
            starts = list(re.finditer(
                rb"(?m)^(?:def|inductive|axiom|intrinsic)[ \t]+([A-Za-z_][A-Za-z0-9_']*)\b",
                original))
            if not starts:
                entry["outcome"] = "no-top-level-declarations"
            else:
                entry["outcome"] = "prefixes-complete"
                for index, declaration in enumerate(starts):
                    end = starts[index + 1].start() if index + 1 < len(starts) else len(original)
                    name = declaration.group(1).decode("ascii")
                    result = run_stage(f"declaration-{index + 1:02}", name, original[:end])
                    if result is None or result.status != "ok":
                        entry["outcome"] = "prefix-check-unavailable"
                        break
                    if result.returncode != 0 and entry["first_failing_declaration_prefix"] is None:
                        entry["first_failing_declaration_prefix"] = entry["checks"][-1]
                if entry["outcome"] == "prefixes-complete" and unit == "compiler/lower_fallible.ouro":
                    newline = b"\r\n" if b"\r\n" in original else b"\n"
                    before = newline.join((b"        | XVFallible _ _ _ _ => finish term",
                                           b"        | XVUnsupported => finish term"))
                    after = newline.join((b"        | XVFallible _ _ _ _ => finish term",
                                          b"        | XVRange _ _ _ => finish term",
                                          b"        | XVListSpread _ _ => finish term",
                                          b"        | XVNamedCall _ _ => finish term",
                                          b"        | XVUnsupported => finish term"))
                    if original.count(before) != 1:
                        raise ValueError("scratch-only fallible control splice is not unique")
                    control = run_stage("declaration-control", "lower_fallible_body+3-arms",
                                        original.replace(before, after))
                    entry["control_accepts"] = bool(control and control.status == "ok"
                                                    and control.returncode == 0
                                                    and control.stdout == "CHECK_OK\n"
                                                    and not control.stderr)
    target.write_bytes(original)
    write_json_atomic(out / "report.json", evidence)

def probe(work: Path, out: Path, report: dict, failed: dict) -> None:
    snapshot_path = work / "inputs.json"
    snapshot = read_json_object_or_none(snapshot_path)
    if not snapshot or sha256_file(snapshot_path) != report.get("inputs_sha256"):
        raise ValueError("bootstrap input snapshot does not match failed report")
    if bootstrap.changed_inputs(work, snapshot):
        raise ValueError("frozen bootstrap inputs changed")
    graph = snapshot["selected"]["unit_graph"]
    units = graph[ROOT_UNIT]
    if not units or units[-1] != ROOT_UNIT or snapshot["selected"]["roots"].index(ROOT_UNIT) != 7:
        raise ValueError("unexpected check-07 unit graph")
    for unit in units:
        path = Path(unit)
        if path.is_absolute() or ".." in path.parts or path.suffix != ".ouro":
            raise ValueError("unsafe unit path in frozen graph")
    bridge = next(phase for phase in report["phases"] if phase.get("phase") == "bridge")
    if bridge.get("pass") is not True:
        raise ValueError("historical bridge did not complete")
    producer = checked_path(work, bridge["binary"])
    if sha256_file(producer) != bridge["binary_sha256"]:
        raise ValueError("historical bridge producer changed")
    source_root = checked_path(work, snapshot["roots"]["p1"])
    for unit in units:
        if not (source_root / unit).is_file():
            raise ValueError("frozen unit missing: " + unit)

    out.mkdir(parents=True, exist_ok=True)
    for stream in ("stdout", "stderr"):
        shutil.copyfile(checked_path(work, failed[stream]), out / ("original." + stream))
    evidence = {"kind": "ouro.bootstrap-prefix-probe.v1", "source_report": str(work / "report.json"),
                "producer_sha256": bridge["binary_sha256"], "root": ROOT_UNIT,
                "original": {"label": failed["label"], "status": failed["status"],
                             "returncode": failed["returncode"]},
                "commands": [], "first_failing_prefix": None, "outcome": "incomplete"}
    write_json_atomic(out / "report.json", evidence)

    env = clean_env()
    for name in ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
                 *snapshot["selected"]["environment"]):
        if name in os.environ:
            env[name] = os.environ[name]
    values = {**snapshot["config"], "cc": snapshot["selected"]["cc_executable"],
              "jobs": 1, "cache_enabled": False, "ccache": "disabled",
              "build_dir": str(work / "out/p1/b"), "c_build_dir": str(work / "out/p1/c"),
              "cache_dir": str(work / "out/p1/k")}
    for key, name in build.ENV_MAP.items():
        value = values[key]
        env[name] = ("1" if value else "0") if isinstance(value, bool) else str(value)
    env.update(PYTHONDONTWRITEBYTECODE="1", OURO_FRONTEND_JOBS="1", OURO1_CHECK_FUEL=bootstrap.FUEL)
    configure_native_stack()
    deadline = time.monotonic() + BUDGET_S

    first_failure_stderr = None
    for index, unit in enumerate(units):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            evidence["outcome"] = "budget-exhausted"
            break
        prefix = units[:index + 1]
        argv = [str(producer), "check", unit, bootstrap.FUEL,
                *(part for path in prefix for part in ("--unit", path))]
        result = run_limited(argv, cwd=source_root, env=env,
                             timeout_s=min(bootstrap.TIMEOUT_S, remaining), memory_mb=bootstrap.MEMORY_MIB)
        label = f"unit-{index:02}"
        for stream in ("stdout", "stderr"):
            (out / (label + "." + stream)).write_text(getattr(result, stream), encoding="utf-8", newline="\n")
        row = {"index": index, "unit": unit, "prefix_count": len(prefix),
               "status": result.status, "returncode": result.returncode,
               "elapsed_s": result.elapsed_s,
               "stdout": label + ".stdout", "stderr": label + ".stderr"}
        evidence["commands"].append(row)
        if result.status != "ok":
            evidence["outcome"] = "probe-limited-or-unavailable"
        elif result.returncode != 0:
            evidence["outcome"] = "first-failing-prefix"
            evidence["first_failing_prefix"] = row
            first_failure_stderr = result.stderr
        elif result.stdout != "CHECK_OK\n" or result.stderr:
            evidence["outcome"] = "unexpected-check-protocol"
        write_json_atomic(out / "report.json", evidence)
        print(f"BOOTSTRAP_PROBE: {label} {unit}: {result.classify()}", flush=True)
        if evidence["outcome"] != "incomplete":
            if evidence["outcome"] == "first-failing-prefix":
                for stream in (result.stdout, result.stderr):
                    if stream:
                        print(stream, end="" if stream.endswith("\n") else "\n", file=sys.stderr, flush=True)
            break
    else:
        evidence["outcome"] = "all-prefixes-pass"
    write_json_atomic(out / "report.json", evidence)
    if first_failure_stderr is not None:
        declaration_probe(work, source_root, producer, env, deadline,
                          units[:evidence["first_failing_prefix"]["index"] + 1],
                          first_failure_stderr, out, evidence)
    if sha256_file(producer) != bridge["binary_sha256"] or bootstrap.changed_inputs(work, snapshot):
        evidence["outcome"] = "frozen-producer-or-inputs-changed"
        write_json_atomic(out / "report.json", evidence)
        raise ValueError("bridge producer or frozen bootstrap inputs changed during probe")
    print("BOOTSTRAP_PROBE: " + evidence["outcome"], flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    candidates = [(work, found) for work in args.bootstrap_dir.glob("*/")
                  if (found := failed_check(work)) is not None]
    if len(candidates) != 1:
        print(f"BOOTSTRAP_PROBE: expected one failed p1/check-07, found {len(candidates)}", flush=True)
        return 0
    work, (report, failed) = candidates[0]
    probe(work, args.out, report, failed)
    return 0


if __name__ == "__main__":
    sys.exit(main())