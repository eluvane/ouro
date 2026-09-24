#!/usr/bin/env python3
"""Manifest-driven fixture and exit-status suite for the Clippy-grade firewall."""
from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional, Sequence

from repo_support import bind_relative_path, read_json_value

ROOT = Path(__file__).resolve().parents[1]
rel = bind_relative_path(ROOT, resolve=True)
MANIFEST = ROOT / "quality" / "fixtures" / "clippy_grade" / "manifest.json"
FIREWALL = ROOT / "scripts" / "clippy_grade_firewall.py"


def materialize_fixtures(manifest: dict[str, Any], work: Path) -> tuple[Path, Path, dict[str, set[str]]]:
    if work.exists():
        shutil.rmtree(work)
    bad_root = work / "bad"
    good_root = work / "good"
    bad_root.mkdir(parents=True, exist_ok=True)
    good_root.mkdir(parents=True, exist_ok=True)
    for directory in ("std", "runtime"):
        for source in (ROOT / directory).rglob("*.ouro"):
            target = work / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    for name, content in manifest.get("support", {}).items():
        target = work / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def source_text(item: dict[str, Any], path: Path) -> str:
        headers = [f'import "{Path(os.path.relpath(work / name, path.parent)).as_posix()}";'
                   for name in item.get("imports", [])]
        return "\n".join(headers) + "\n" + str(item["content"])

    expected: dict[str, set[str]] = {}
    for item in manifest.get("bad", []):
        path = bad_root / item["name"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source_text(item, path), encoding="utf-8")
        expected[rel(path)] = set(map(str, item.get("codes", [])))
    for item in manifest.get("good", []):
        path = good_root / item["name"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source_text(item, path), encoding="utf-8")
    return bad_root, good_root, expected


def run_firewall(scope: Path, report: Path, *, profile: str = "strict", warn_only: bool = False,
                 source_root: Path = ROOT) -> subprocess.CompletedProcess[str]:
    # A failed invocation must not inherit successful evidence from an earlier run.
    report.unlink(missing_ok=True)
    report.with_suffix(".sarif").unlink(missing_ok=True)
    cmd = [
        sys.executable,
        str(FIREWALL),
        "--profile",
        profile,
        "--include-fixtures",
        "--source-root",
        str(source_root),
        "--scope",
        rel(scope),
        "--report",
        rel(report),
        "--sarif",
        rel(report.with_suffix(".sarif")),
    ]
    if warn_only:
        cmd.append("--warn-only")
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)


def load_report(report: Path) -> dict[str, Any]:
    data, error = read_json_value(report)
    if error is not None:
        raise ValueError(f"unreadable clippy-grade report {rel(report)}: {error}")
    if not isinstance(data, dict):
        raise ValueError(f"clippy-grade report {rel(report)} is not a JSON object")
    return data


def load_manifest(path: Path) -> dict[str, Any]:
    data, error = read_json_value(path)
    if error is not None:
        raise ValueError(f"unreadable clippy-grade manifest {rel(path)}: {error}")
    if not isinstance(data, dict):
        raise ValueError(f"clippy-grade manifest {rel(path)} is not a JSON object")
    return data


def codes_by_path(report: Path) -> dict[str, set[str]]:
    data = load_report(report)
    findings = data.get("findings", [])
    if not isinstance(findings, list):
        raise ValueError(f"clippy-grade report {rel(report)} findings is not an array")
    out: dict[str, set[str]] = defaultdict(set)
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError(f"clippy-grade report {rel(report)} has a non-object finding")
        if finding.get("suppressed_by"):
            continue
        out[str(finding.get("path", ""))].add(str(finding.get("rule_id", "")))
    return out


def suppression_policy_cases(out: Path) -> list[str]:
    """Exercise policy through the public CLI and all three existing reports."""
    work = out / "suppression-policy"
    work.mkdir(parents=True, exist_ok=True)
    cases = (
        ("reasonless", "OURO-CLIPPY-SUPPRESS-002", True,
         "-- ouro-clippy:disable=OURO-CLIPPY-SUPPRESS-002 reason=reviewed\n"
         "-- ouro-clippy:disable=OURO-CLIPPY-REDUNDANT-001\n"),
        ("unknown", "OURO-CLIPPY-SUPPRESS-003", True,
         "-- ouro-clippy:disable=OURO-CLIPPY-SUPPRESS-003 reason=reviewed\n"
         "-- ouro-clippy:disable=OURO-CLIPPY-NOT-A-RULE reason=reviewed\n"),
        ("ordinary", "OURO-CLIPPY-REDUNDANT-001", False,
         "-- ouro-clippy:disable=OURO-CLIPPY-REDUNDANT-001 reason=explicit local naming example\n"
         "def retain_value (value : Nat) : Nat := let local := value in local;\n"),
        ("empty-reason", "OURO-CLIPPY-SUPPRESS-002", True,
         "-- ordinary comment\n"
         "-- ouro-clippy:disable=OURO-CLIPPY-REDUNDANT-001 reason=\n"
         "def retain_value (value : Nat) : Nat := let local := value in local;\n"),
    )
    failures: list[str] = []
    for name, code, fatal, content in cases:
        source = work / (name + ".ouro")
        source.write_text("inductive Nat : Type := | Z : Nat | S : Nat -> Nat;\n" + content, encoding="utf-8")
        for profile in ("strict", "release"):
            label = name + "-" + profile
            report = work / (label + ".json")
            proc = run_firewall(source, report, profile=profile)
            (work / (label + ".stdout")).write_text(proc.stdout, encoding="utf-8")
            (work / (label + ".stderr")).write_text(proc.stderr, encoding="utf-8")
            try:
                findings = load_report(report)["findings"]
                diagnostics = [finding for finding in findings if finding["rule_id"] == code]
                sarif = load_report(report.with_suffix(".sarif"))["runs"][0]["results"]
                visible = [result for result in sarif if result["ruleId"] == code]
                valid = len(diagnostics) == 1 and diagnostics[0]["line"] == 3 and not proc.stderr
                if fatal:
                    valid = valid and proc.returncode == 1 and len(visible) == 1
                    valid = valid and diagnostics[0]["severity"] == "fatal" and diagnostics[0]["suppressed_by"] is None
                    valid = valid and f"fatal[{code}]" in proc.stdout
                else:
                    valid = valid and proc.returncode == 0 and not visible
                    valid = valid and diagnostics[0]["severity"] == "deny" and diagnostics[0]["suppressed_by"] == "line:3"
                    valid = valid and f"deny[{code}]" not in proc.stdout
                if name == "empty-reason":
                    valid = valid and any(f["rule_id"] == "OURO-CLIPPY-REDUNDANT-001"
                                          and f["suppressed_by"] is None for f in findings)
            except (OSError, ValueError, KeyError, TypeError, IndexError):
                valid = False
            if not valid:
                failures.append("suppression policy/report mismatch: " + label)
    return failures


def source_policy_cases(out: Path) -> list[str]:
    """Spelling is not policy; only an explicit resolved intrinsic/owner is."""
    from frontend_regen import collect_units

    root = out / "source-policy"
    root.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    for entry in ("std/string_prims.ouro", "runtime/native_types.ouro"):
        for name in collect_units(entry):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
    targets = ("samples/examples/io.ouro", "demo/private/generated_demo.ouro", "workflow.ouro")
    for target in targets:
        path = root / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def surface_identity (T : Type) (x : T) : T := x;\n", encoding="utf-8")

    def imported(source: Path, target: str) -> str:
        return f'import "{Path(os.path.relpath(root / target, source.parent)).as_posix()}";\n'

    def verify(source: Path, expected: list[str]) -> None:
        report = source.with_suffix(".json")
        proc = run_firewall(source, report, source_root=root)
        try:
            data = load_report(report)
            codes = [finding["rule_id"] for finding in data["findings"]]
            sarif = load_report(report.with_suffix(".sarif"))["runs"][0]
            valid = proc.returncode == int(bool(expected)) and not proc.stderr and data["files_scanned"] == 1
            valid = valid and codes == expected and [f["ruleId"] for f in sarif["results"]] == expected
            valid = valid and data["source_root"] == rel(root) and sarif["properties"]["sourceRoot"] == rel(root)
        except (OSError, ValueError, KeyError, TypeError):
            valid = False
        if not valid:
            failures.append("resolved source policy mismatch: " + rel(source))

    # Folder names and imported basenames alone no longer establish a defect.
    for target in targets:
        for layer in ("std", "tools/moved", "compiler/kernel", "samples"):
            source = root / layer / (Path(target).stem + "_probe.ouro")
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(imported(source, target) +
                              "def keep (T : Type) (value : T) : T := value;\n", encoding="utf-8")
            verify(source, [])
    support = root / "std/runtime.ouro"
    support.write_text(imported(support, "std/string_prims.ouro") + imported(support, "runtime/native_types.ouro") +
                       "def IO (A : Type) : Type := Runtime A;\n"
                       "def io_pure (A : Type) (value : A) : IO A := runtime_pure A value;\n"
                       "def prim_proc_exec (command : String) (arguments : List String) : IO Nat :=\n"
                       "    io_pure Nat 0;\n"
                       'intrinsic renamed_read : String -> Runtime String := "ouro.fs.read_file";\n',
                       encoding="utf-8")
    # A loaded std/fs.ouro owner must still bind the registered identities.
    # The thin policy probe is not the production module; it only needs those
    # names so contract validation does not treat the owner as stale.
    fs_identity = (
        "def fs_read (path : String) : IO String := renamed_read path;\n"
        "def fs_write (path : String) (text : String) : IO Unit := io_pure Unit MkUnit;\n"
        "def fs_copy (source_path : String) (target : String) : IO Unit := io_pure Unit MkUnit;\n"
        "def fs_exists (path : String) : IO Bool := io_pure Bool True;\n"
        "def fs_append_checked (path : String) (text : String) : IO Unit := io_pure Unit MkUnit;\n"
        "def fs_mkdir_p_checked (path : String) : IO Unit := io_pure Unit MkUnit;\n"
        "def fs_list_checked (path : String) : IO (List String) := io_pure (List String) ([] : List String);\n"
        "def fs_copy_checked (source_path : String) (target : String) : IO Unit := io_pure Unit MkUnit;\n"
        "def fs_rename_checked (source_path : String) (target : String) : IO Unit := io_pure Unit MkUnit;\n"
        "def fs_read_checked (path : String) : IO String := renamed_read path;\n"
        "def fs_write_checked (path : String) (text : String) : IO Unit := io_pure Unit MkUnit;\n"
    )
    for name, expected in (("std/fs.ouro", []), ("tools/copied/std/fs.ouro", ["OURO-CLIPPY-CHECKED-001"])):
        source = root / name
        source.parent.mkdir(parents=True, exist_ok=True)
        extra = fs_identity if name == "std/fs.ouro" else ""
        source.write_text(imported(source, "std/runtime.ouro") + extra +
                          "def raw_boundary (path : String) : Runtime String := renamed_read path;\n", encoding="utf-8")
        verify(source, expected)
    # Same spelling, different declaration: not a filesystem operation.
    source = root / "tools/local_fs_read.ouro"
    source.write_text(imported(source, "std/string_prims.ouro") +
                      "def fs_read (path : String) : String := path;\n"
                      "def keep (path : String) : String := fs_read path;\n", encoding="utf-8")
    verify(source, [])
    report = out / "outside-source-root.json"
    proc = run_firewall(ROOT / "std/fs.ouro", report, source_root=root)
    if proc.returncode == 0 or "outside the declared source root" not in proc.stderr:
        failures.append("scope outside the declared source root was not rejected")
    empty = root / "empty"
    empty.mkdir(exist_ok=True)
    for scope in (root / "missing.ouro", empty):
        report = out / (scope.name + ".json")
        proc = run_firewall(scope, report, source_root=root, profile="project", warn_only=True)
        if proc.returncode == 0 or "native quality inventory failed" not in proc.stderr:
            failures.append("incomplete inventory passed --warn-only: " + rel(scope))
    return failures


def structural_fact_cases(out: Path) -> list[str]:
    """Launch the native fixture oracle; Python does not build semantic facts."""
    from clippy_grade_firewall import _native_env
    from ourosmith.host import prepare_entry
    from ourosmith.limits import run_limited

    inventory = load_manifest(ROOT / "quality/fixtures/clippy_grade/structural.json")
    work = out / "structural-facts-cases"
    work.mkdir(parents=True, exist_ok=True)
    rows = []
    for row in inventory["cases"]:
        name = row["name"]
        (work / (name + ".ouro")).write_text(row["source"], encoding="utf-8")
        expect = ",".join(row.get("expect") or [])
        rows.append(name + "\t" + row["kind"] + "\t" + expect)
    (work / "inventory.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")

    failures: list[str] = []
    executable = prepare_entry("tests/clippy_structural_facts.ouro", "ouro-clippy-structural-facts")
    result = run_limited([str(executable), str(work)], cwd=ROOT, env=_native_env(),
                         timeout_s=1800, memory_mb=3072)
    (out / "structural-facts.stdout").write_text(result.stdout, encoding="utf-8")
    (out / "structural-facts.stderr").write_text(result.stderr, encoding="utf-8")
    if result.returncode != 0 or result.stderr or "CLIPPY_STRUCTURAL_FACTS: OK cases=" not in result.stdout:
        failures.append("native structural positive/near-miss/failure fixtures did not pass")

    grade = prepare_entry("tests/clippy_grade_invariants.ouro", "ouro-clippy-grade-invariants")
    grade_result = run_limited([str(grade)], cwd=ROOT, env=_native_env(),
                               timeout_s=1800, memory_mb=3072)
    (out / "grade-invariants.stdout").write_text(grade_result.stdout, encoding="utf-8")
    (out / "grade-invariants.stderr").write_text(grade_result.stderr, encoding="utf-8")
    if grade_result.returncode != 0 or grade_result.stderr or "CLIPPY_GRADE_INVARIANTS: OK" not in grade_result.stdout:
        failures.append("native clippy grade-cone invariants did not pass")
    return failures


def frontend_policy_cases(out: Path) -> list[str]:
    """An incomplete native frontend must not pass strict, release, or advisory."""
    inventory = load_manifest(ROOT / "quality/fixtures/clippy_grade/structural.json")
    work = out / "frontend-policy"
    work.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    cases = [row for row in inventory["cases"] if row["kind"] == "frontend-error"]
    if not cases:
        return ["no frontend-error fixtures were selected"]
    for row in cases:
        source = work / (row["name"] + ".ouro")
        source.write_text(row["source"], encoding="utf-8")
        for profile, advisory in (("strict", False), ("release", False), ("project", True)):
            label = row["name"] + "-" + profile
            report = work / (label + ".json")
            proc = run_firewall(source, report, profile=profile, warn_only=advisory)
            (work / (label + ".stdout")).write_text(proc.stdout, encoding="utf-8")
            (work / (label + ".stderr")).write_text(proc.stderr, encoding="utf-8")
            try:
                data = load_report(report)
                findings = data["findings"]
                valid = proc.returncode == 1 and data["pass"] is False and len(findings) == 1
                valid = valid and findings[0]["rule_id"] == "OURO-CLIPPY-FRONTEND-001"
                valid = valid and findings[0]["severity"] == "fatal" and findings[0]["suppressed_by"] is None
                valid = valid and data["diagnostics_blocking"] == 1
            except (OSError, ValueError, KeyError, TypeError, IndexError):
                valid = False
            if not valid:
                failures.append("frontend failure was not an explicit fatal result: " + label)
    return failures


def fail_closed_cases(out: Path) -> list[str]:
    """Black-box native boundary tests; Python does not decide source semantics."""
    from clippy_grade_firewall import _native_env
    from ourosmith.host import prepare_entry
    from ourosmith.limits import run_limited

    executable = prepare_entry("tools/clippy/main.ouro", "ouro-clippy-grade-firewall")
    work = out / "fail-closed"
    work.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []

    def invoke(label: str, args: list[str], root: Path = ROOT):
        env = _native_env()
        env["OURO_ROOT"] = root.as_posix()
        result = run_limited([str(executable), *args], cwd=ROOT, env=env,
                             timeout_s=1800, memory_mb=3072)
        (work / (label + ".stdout")).write_text(result.stdout, encoding="utf-8")
        (work / (label + ".stderr")).write_text(result.stderr, encoding="utf-8")
        return result

    invalid_args = [
        ["--profile", "unknown"], ["--profile", ""], ["--source-root", ""],
        ["--list-rules", "--validate-rules"],
    ]
    for profile in ("strict", "release"):
        invalid_args.extend((["--profile", profile, "--warn-only"],
                             ["--warn-only", "--profile", profile]))
    for index, args in enumerate(invalid_args):
        result = invoke("arguments-" + str(index), args)
        if result.returncode != 1 or "CLIPPY_GRADE_FIREWALL: FAIL" not in result.stderr or result.stdout:
            failures.append("invalid native arguments were not rejected before analysis: " + repr(args))

    registry_root = work / "registry-root"
    registry_path = registry_root / "quality" / "clippy_grade_rules.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    (registry_root / "probe.ouro").write_text("inductive Value : Type := | MakeValue : Value;\n"
        "def retain (value : Value) : Value := let alias := value in alias;\n", encoding="utf-8")
    registry = load_report(ROOT / "quality" / "clippy_grade_rules.json")
    valid_text = json.dumps(registry)
    registry_path.write_text(valid_text, encoding="utf-8")
    for mode in ("--validate-rules", "--list-rules"):
        control = invoke("registry-control-" + mode[2:], [mode], registry_root)
        if control.returncode != 0 or control.stderr:
            failures.append("valid isolated native registry failed: " + mode)

    variants: dict[str, str] = {"invalid-json": "{", "wrong-root": "[]"}
    for name in ("dropped-row", "duplicate-id", "invalid-level", "missing-level", "unknown-profile", "empty-message",
                 "wrong-kind", "missing-profiles", "duplicate-profile", "invalid-vocabulary",
                 "release-weaker", "frontend-not-fatal"):
        value = copy.deepcopy(registry)
        if name == "dropped-row":
            value["rules"].append({"family": "logic"})
        elif name == "duplicate-id":
            value["rules"].append(copy.deepcopy(value["rules"][0]))
        elif name == "invalid-level":
            value["rules"][0]["levels"]["strict"] = "denny"
        elif name == "missing-level":
            del value["rules"][0]["levels"]["strict"]
        elif name == "unknown-profile":
            value["rules"][0]["levels"]["strcit"] = "deny"
        elif name == "empty-message":
            value["rules"][0]["message"] = "  "
        elif name == "wrong-kind":
            value["kind"] = "other.registry"
        elif name == "missing-profiles":
            del value["profiles"]
        elif name == "duplicate-profile":
            value["profiles"][-1] = "strict"
        elif name == "invalid-vocabulary":
            value["levels"][-1] = 7
        elif name == "release-weaker":
            rule = next(row for row in value["rules"] if row["id"] == "OURO-CLIPPY-REDUNDANT-001")
            rule["levels"]["release"] = "warn"
        elif name == "frontend-not-fatal":
            rule = next(row for row in value["rules"] if row["id"] == "OURO-CLIPPY-FRONTEND-001")
            rule["levels"]["project"] = "warn"
        variants[name] = json.dumps(value)
    variants["duplicate-json-key"] = valid_text.replace('"family":', '"family": "shadow", "family":', 1)
    variants["duplicate-level-key"] = valid_text.replace('"strict":', '"strict": "allow", "strict":', 1)
    modes = (["--validate-rules"], ["--list-rules"],
             ["--profile", "project", "--warn-only", "--scope", "probe.ouro", "--include-fixtures"])
    for name, text in variants.items():
        registry_path.write_text(text, encoding="utf-8")
        for index, args in enumerate(modes):
            result = invoke("registry-" + name + "-" + str(index), args, registry_root)
            if result.returncode != 1 or "rule inventory" not in result.stderr or "CLIPPY_GRADE_FIREWALL: PASS" in result.stdout:
                failures.append("malformed native registry escaped " + name + ": " + repr(args))

    # A native emitter whose ID is missing must be fatal, even in advisory mode.
    missing = copy.deepcopy(registry)
    missing["rules"] = [rule for rule in missing["rules"] if rule["id"] != "OURO-CLIPPY-REDUNDANT-001"]
    registry_path.write_text(json.dumps(missing), encoding="utf-8")
    report = registry_root / "missing-rule.json"
    report.unlink(missing_ok=True)
    result = invoke("unregistered-emission", ["--profile", "project", "--warn-only", "--include-fixtures",
                    "--scope", "probe.ouro", "--report", str(report),
                    "--sarif", str(report.with_suffix(".sarif"))], registry_root)
    try:
        findings = load_report(report)["findings"]
        valid = result.returncode == 1 and any(f["rule_id"] == "OURO-CLIPPY-REDUNDANT-001"
                                               and f["severity"] == "fatal" for f in findings)
    except (OSError, ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        failures.append("unregistered native emission was not a blocking fatal finding")
    return failures


def semantic_precision_cases(out: Path, worker: Optional[Path] = None, *,
                             cases: Optional[Sequence[dict[str, Any]]] = None,
                             source_root: Path = ROOT) -> list[str]:
    """Compare native proofs with identity-mutation fixtures, never infer them in Python."""
    work = out / "semantic-precision"
    work.mkdir(parents=True, exist_ok=True)
    default_name = "ouro-clippy-structural" + (".exe" if os.name == "nt" else "")
    executable = worker or ROOT / "_build/c" / default_name
    failures: list[str] = []
    if worker is None:
        with (work / "build.log").open("w", encoding="utf-8") as log:
            result = subprocess.run(["sh", "scripts/build_tool.sh", "tools/clippy/structural_main.ouro",
                                     str(executable)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode != 0:
            return ["semantic precision worker build failed"]
    if not executable.is_file():
        return ["semantic precision worker is unavailable: " + str(executable)]
    selected = cases if cases is not None else load_manifest(ROOT / "tests/clippy_semantic/cases.json")["cases"]
    active = {row["id"] for row in load_manifest(ROOT / "quality/clippy_grade_rules.json")["rules"]}
    rows: list[dict[str, Any]] = []
    for case in selected:
        source = source_root / case["path"]
        name = source.stem
        found: list[str] = []
        failure = ""
        try:
            from ourosmith.limits import run_limited
            result = run_limited([str(executable.resolve()), str(source_root), case["path"]], cwd=ROOT,
                                 timeout_s=60, memory_mb=2048)
            (work / (name + ".stdout")).write_text(result.stdout, encoding="utf-8")
            (work / (name + ".stderr")).write_text(result.stderr, encoding="utf-8")
            if not result.ok or result.stderr:
                raise ValueError("worker failed, status=" + result.classify() + ", exit=" + str(result.returncode))
            magic, status, payload = result.stdout.encode("utf-8").split(b"\n", 2)
            if magic != b"ouro.clippy-semantic.v3":
                raise ValueError("wrong protocol")
            if "error_contains" in case:
                if status != b"error" or not payload.strip():
                    raise ValueError("invalid input did not fail closed")
                if case["error_contains"].lower() not in payload.decode("utf-8").lower():
                    raise ValueError("unexpected failure: " + payload.decode("utf-8"))
            else:
                if status != b"ok":
                    raise ValueError("semantic analysis failed: " + payload.decode("utf-8"))
                size_raw, payload = payload.split(b"\n", 1)
                size = int(size_raw)
                if size_raw != str(size).encode() or size < 0:
                    raise ValueError("noncanonical source byte count")
                if payload[:size] != source.read_bytes() or payload[size:size + 1] != b"\n":
                    raise ValueError("source snapshot drift or truncation")
                count_raw, proof_text = payload[size + 1:].split(b"\n", 1)
                count = int(count_raw)
                if count_raw != str(count).encode() or not 0 <= count <= 500000:
                    raise ValueError("invalid proof count")
                fields = proof_text.decode("utf-8").splitlines()
                if len(fields) != count * 6:
                    raise ValueError("incomplete proof inventory")
                for i in range(count):
                    code, owner, ordinal, start, end, evidence = fields[i * 6:i * 6 + 6]
                    if code not in active or not owner.strip() or not evidence.strip():
                        raise ValueError("unregistered or evidence-free proof")
                    if str(int(ordinal)) != ordinal or not 0 <= int(ordinal) <= 500000:
                        raise ValueError("noncanonical proof ordinal")
                    if start == "-" or end == "-":
                        if start != "-" or end != "-":
                            raise ValueError("partial proof range")
                    elif (str(int(start)) != start or str(int(end)) != end
                          or int(start) > int(end) or int(end) > size):
                        raise ValueError("noncanonical proof range")
                    found.append(code)
                if sorted(found) != sorted(case["codes"]):
                    raise ValueError("expected=" + repr(case["codes"]) + " found=" + repr(found))
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
            failure = str(exc)
            failures.append(name + ": " + failure)
        rows.append({"path": case["path"], "pass": not failure, "codes": found, "failure": failure})
        print("SEMANTIC_PRECISION " + name + (": FAIL " + failure if failure else ": OK"), flush=True)
    (work / "results.json").write_text(json.dumps({"pass": not failures, "cases": rows}, indent=2) + "\n",
                                       encoding="utf-8")
    return failures


def semantic_runtime_import_cases(out: Path, worker: Optional[Path] = None) -> list[str]:
    """Exercise the runtime root's transitive platform harvest and fatal inputs."""
    work = out / "runtime-imports"
    failures = semantic_precision_cases(work / "actual", worker, cases=[
        {"path": "runtime/managed.ouro", "codes": []},
        {"path": "runtime/platform/windows_clock.ouro", "codes": []},
    ])
    executable = worker or ROOT / "_build/c" / ("ouro-clippy-structural" + (".exe" if os.name == "nt" else ""))
    failures.extend(semantic_precision_cases(work / "fixtures", executable,
        source_root=ROOT / "tests/clippy_semantic/runtime_imports", cases=[
            {"path": "runtime/valid.ouro", "codes": []},
            {"path": "runtime/unresolved.ouro", "codes": [],
             "error_contains": "unresolved executable declaration: missing_runtime_value"},
            {"path": "runtime/missing.ouro", "codes": [],
             "error_contains": "expected a regular quality source file"},
        ]))
    return failures


def semantic_law_cases(out: Path) -> list[str]:
    """Native proof/contract/resource laws; host code only launches and reports."""
    from clippy_grade_firewall import _native_env
    from ourosmith.host import prepare_entry
    from ourosmith.limits import run_limited

    failures: list[str] = []
    rows: list[dict[str, Any]] = []
    for name in ("proofs", "contracts", "resources", "lifetime", "precision", "process_status"):
        entry = "tests/clippy_semantic/" + name + ".ouro"
        executable = prepare_entry(entry, "ouro-clippy-laws-" + name)
        groups = [""]
        if name == "proofs":
            listing = run_limited([str(executable), "--list-groups"], cwd=ROOT, env=_native_env(),
                                  timeout_s=180, memory_mb=2048)
            (out / "proofs-groups.stdout").write_text(listing.stdout, encoding="utf-8")
            (out / "proofs-groups.stderr").write_text(listing.stderr, encoding="utf-8")
            groups = listing.stdout.splitlines()
            if (not listing.ok or listing.stderr or not groups or len(groups) != len(set(groups))
                    or any(not group or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in group)
                           for group in groups)):
                rows.append({"entry": entry, "pass": False, "exit_code": listing.returncode})
                failures.append("native semantic proof group inventory failed")
                continue
        for group in groups:
            label = name + ("-" + group if group else "")
            command = [str(executable), "--group", group] if group else [str(executable)]
            result = run_limited(command, cwd=ROOT, env=_native_env(), timeout_s=180, memory_mb=2048)
            (out / (label + "-laws.stdout")).write_text(result.stdout, encoding="utf-8")
            (out / (label + "-laws.stderr")).write_text(result.stderr, encoding="utf-8")
            passed = result.ok and not result.stderr and "PASS " in result.stdout and "FAIL " not in result.stdout
            rows.append({"entry": entry, "group": group, "pass": passed, "exit_code": result.returncode})
            if not passed:
                failures.append("native semantic laws failed: " + label)
    (out / "semantic-laws.json").write_text(json.dumps({"pass": not failures, "cases": rows}, indent=2) + "\n",
                                             encoding="utf-8")
    return failures


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="_build/quality/clippy-grade-suite")
    ap.add_argument("--precision-only", action="store_true", help="run native semantic identity-mutation fixtures only")
    ap.add_argument("--runtime-imports-only", action="store_true", help="run native runtime import-harvest regressions only")
    ap.add_argument("--laws-only", action="store_true", help="run native proof, contract, budget and precision laws")
    ap.add_argument("--worker", type=Path, help="use this already-built semantic worker for the focused suite")
    args = ap.parse_args(argv)

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.mkdir(parents=True, exist_ok=True)

    if args.laws_only:
        if args.precision_only or args.runtime_imports_only or args.worker is not None:
            ap.error("--laws-only cannot be combined with --precision-only, --runtime-imports-only or --worker")
        failures = semantic_law_cases(out)
        for failure in failures:
            print("CLIPPY_LAWS_FAIL " + failure, file=sys.stderr)
        return 1 if failures else 0
    if args.runtime_imports_only:
        if args.precision_only:
            ap.error("--runtime-imports-only cannot be combined with --precision-only")
        failures = semantic_runtime_import_cases(out, args.worker)
        for failure in failures:
            print("CLIPPY_RUNTIME_IMPORTS_FAIL " + failure, file=sys.stderr)
        return 1 if failures else 0
    if args.precision_only:
        failures = semantic_precision_cases(out, args.worker)
        for failure in failures:
            print("CLIPPY_PRECISION_FAIL " + failure, file=sys.stderr)
        return 1 if failures else 0
    if args.worker is not None:
        ap.error("--worker requires --precision-only or --runtime-imports-only")

    try:
        manifest = load_manifest(MANIFEST)
    except ValueError as exc:
        print(f"CLIPPY_GRADE_SUITE: FAIL {exc}", file=sys.stderr)
        return 1
    bad_root, good_root, expected_bad = materialize_fixtures(manifest, out / "fixtures")
    failures: list[str] = structural_fact_cases(out)
    failures.extend(semantic_law_cases(out))
    failures.extend(semantic_precision_cases(out))
    failures.extend(semantic_runtime_import_cases(out,
        ROOT / "_build/c" / ("ouro-clippy-structural" + (".exe" if os.name == "nt" else ""))))
    failures.extend(suppression_policy_cases(out))
    failures.extend(frontend_policy_cases(out))
    failures.extend(source_policy_cases(out))
    failures.extend(fail_closed_cases(out))

    validate = subprocess.run([sys.executable, str(FIREWALL), "--validate-rules"], cwd=ROOT, text=True, capture_output=True, check=False)
    (out / "validate.stdout").write_text(validate.stdout, encoding="utf-8")
    (out / "validate.stderr").write_text(validate.stderr, encoding="utf-8")
    if validate.returncode != 0:
        failures.append("rule inventory validation failed")

    bad_report = out / "bad.json"
    bad_proc = run_firewall(bad_root, bad_report, source_root=bad_root.parent)
    (out / "bad.stdout").write_text(bad_proc.stdout, encoding="utf-8")
    (out / "bad.stderr").write_text(bad_proc.stderr, encoding="utf-8")
    if bad_proc.returncode != 1 or bad_proc.stderr:
        failures.append("bad fixtures did not return blocking diagnostics without a transport failure")
    try:
        found_bad = codes_by_path(bad_report) if bad_report.is_file() else {}
    except ValueError as exc:
        failures.append(str(exc))
        found_bad = {}
    for path, expected in expected_bad.items():
        found = found_bad.get(path, set())
        missing = sorted(expected - found)
        if missing:
            failures.append(f"bad fixture missing {missing}: {path} found={sorted(found)}")

    good_report = out / "good.json"
    good_proc = run_firewall(good_root, good_report, source_root=good_root.parent)
    (out / "good.stdout").write_text(good_proc.stdout, encoding="utf-8")
    (out / "good.stderr").write_text(good_proc.stderr, encoding="utf-8")
    try:
        good_data = load_report(good_report)
        good_codes = codes_by_path(good_report)
        valid_good = good_proc.returncode == 0 and not good_proc.stderr and not good_codes
        valid_good = valid_good and good_data["files_scanned"] == len(manifest["good"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        good_codes = {"unreadable-report": {str(exc)}}
        valid_good = False
    if not valid_good:
        failures.append(f"good/near-miss fixtures were not completely analyzed without visible diagnostics: {good_codes}")

    smoke_bad = next(iter(expected_bad))
    smoke_report = out / "warn_only_smoke.json"
    smoke = run_firewall(ROOT / smoke_bad, smoke_report, profile="project", warn_only=True, source_root=bad_root.parent)
    (out / "warn_only_smoke.stdout").write_text(smoke.stdout, encoding="utf-8")
    (out / "warn_only_smoke.stderr").write_text(smoke.stderr, encoding="utf-8")
    try:
        advisory = load_report(smoke_report)
        valid_advisory = smoke.returncode == 0 and advisory["pass"] is False and advisory["diagnostics_blocking"] > 0
    except (OSError, ValueError, KeyError, TypeError):
        valid_advisory = False
    if not valid_advisory:
        failures.append("project advisory mode lost diagnostics or did not return success")

    suite_report = {
        "kind": "ouro.clippy-grade-suite-report.v1",
        "pass": not failures,
        "bad_count": len(manifest.get("bad", [])),
        "good_count": len(manifest.get("good", [])),
        "failures": failures,
    }
    (out / "suite.json").write_text(json.dumps(suite_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for failure in failures:
        print(f"CLIPPY_GRADE_SUITE_FAIL {failure}", file=sys.stderr)
    print(
        f"CLIPPY_GRADE_SUITE: {'OK' if not failures else 'FAIL'} "
        f"bad={suite_report['bad_count']} good={suite_report['good_count']} report={rel(out / 'suite.json')}"
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
