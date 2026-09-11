"""Fail-closed retirement evidence checks, including stale or partial runs."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from ourosmith import ROOT, generator_hash
from ourosmith.faults import FAULTS, FAULTS_KIND
from ourosmith.host import toolchain_paths
from ourosmith.provenance import binary_state, source_state
from ourosmith.report import REPORT_KIND


def read(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def required_binaries(surface, native_drivers=None, surface_toolchain=None):
    from ourosmith.native import RETAINED_ENTRY, SMITH_ENTRY

    if native_drivers is None:
        raise ValueError("source-bound native driver evidence is missing")
    if set(native_drivers) != {SMITH_ENTRY, RETAINED_ENTRY}:
        raise ValueError("required native driver set is incomplete")
    paths = []
    compilers = {(ROOT / row["compiler"]).resolve() for row in native_drivers.values()}
    if len(compilers) != 1:
        raise ValueError("native drivers use different compilers")
    for row in native_drivers.values():
        paths.extend(ROOT / row[key] for key in ("compiler", "binary"))
    if surface:
        paths.extend(toolchain_paths(surface_toolchain, compiler=next(iter(compilers))).values())
    return {path.relative_to(ROOT).as_posix() for path in paths}


def provenance_problems(provenance, current, *, surface, native_drivers=None, surface_toolchain=None, required=None):
    problems = []
    if provenance.get("source") != current:
        problems.append("source provenance is missing or stale")
    binaries = provenance.get("binaries", {})
    if not isinstance(binaries, dict):
        return problems + ["tested binary hashes are malformed"]
    try:
        if set(binaries) != (required_binaries(surface, native_drivers, surface_toolchain) if required is None else required):
            problems.append("required tested binary set is incomplete")
    except (OSError, ValueError, KeyError, TypeError):
        problems.append("required tested binary set is incomplete or unavailable")
    if not binaries or "missing" in binaries.values():
        problems.append("tested binary hashes are missing")
    else:
        paths = [ROOT / path for path in binaries]
        if any(not path.resolve().is_relative_to(ROOT) for path in paths) or binaries != binary_state(paths):
            problems.append("tested binaries differ from current binaries")
    return problems


def profile_problems(report, profile, current):
    from ourosmith.core.run import CONTROLS, FORMS, NEGATIVES, OPERATIONS, RELATIONS, definition_count
    from ourosmith.corpus import CORPUS_DIR, RETAINED_LAWS, RETAINED_REJECTIONS, check_case, load_cases
    from ourosmith.native import RETAINED_ENTRY, SMITH_ENTRY, evidence_problems

    problems = []
    if not isinstance(report, dict) or report.get("kind") != REPORT_KIND or report.get("pass") is not True:
        return ["successful Smith report is missing"]
    sections = report.get("sections", {})
    summary = report.get("summary", {})
    if not isinstance(sections, dict) or not isinstance(summary, dict):
        return ["Smith report sections or summary are malformed"]
    layers = summary.get("layers", {})
    if (not isinstance(layers, dict) or any(not isinstance(layer, dict) or not isinstance(layer.get("coverage", {}), dict)
                                          for layer in layers.values())
            or any(not isinstance(sections.get(name, {}), dict) for name in
                   ("native_drivers", "provenance", "surface_toolchain", "stage_parity", "completeness", "configuration"))):
        return ["Smith report layer or source evidence is malformed"]
    body = {key: value for key, value in report.items() if key not in {"fingerprint", "timing_s"}}
    fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if fingerprint != report.get("fingerprint"):
        problems.append("report fingerprint does not match its contents")
    config = read(ROOT / "quality/smith/seeds.json")["profiles"][profile]
    seeds = list(range(config["seed_base"], config["seed_base"] + config["seeds"]))
    if report.get("profile") != profile or report.get("seeds") != seeds:
        problems.append("profile or seed set is incomplete")
    if report.get("generator_hash") != generator_hash():
        problems.append("generator hash is stale")
    drivers = sections.get("native_drivers", {})
    if set(drivers) != {SMITH_ENTRY, RETAINED_ENTRY}:
        problems.append("required native source-bound drivers are missing")
    for entry, row in drivers.items():
        problems.extend(entry + ": " + problem for problem in evidence_problems(row, entry=entry))
    problems.extend(provenance_problems(sections.get("provenance", {}), current,
                                        surface=profile != "kernel", native_drivers=drivers,
                                        surface_toolchain=sections.get("surface_toolchain")))
    if profile != "kernel":
        stage = sections.get("stage_parity", {})
        proof = read(ROOT / "_build/stage_loop/result.json")
        if stage.get("status") == "unavailable" and profile == "pr" and not proof:
            pass
        elif stage.get("status") != "exercised" or not all(proof.get(key) is True for key in ("pass", "frontend_eq", "backend_eq")):
            problems.append("stage parity or fixpoint proof is missing")
        else:
            path = ROOT / stage.get("binary", "")
            digest = stage.get("sha256")
            if not path.resolve().is_relative_to(ROOT / "_build/stage_loop") or not path.is_file() or not digest:
                problems.append("stage parity binary is invalid")
            elif binary_state([path]) != {stage["binary"]: digest} or digest != proof.get("artifacts", {}).get("binary_sha256"):
                problems.append("stage parity binary differs from the recorded fixpoint")
    required = {"kernel"} if profile == "kernel" else {"kernel", "surface"}
    if set(layers) != required | {"kernel-corpus"}:
        problems.append("required layers or persistent kernel corpus are missing")
    for layer in required:
        coverage = sections.get("completeness", {}).get(layer, {})
        if not isinstance(coverage, dict) or coverage.get("checked_exercised") is not True or coverage.get("problems") != []:
            problems.append(f"{layer} strategy completeness was not checked")
    for layer in layers.values():
        if layer.get("abstentions") or layer.get("findings") or not layer.get("cases"):
            problems.append("empty layer, finding, or oracle abstention")
    if report.get("findings") or report.get("skips") or report.get("gaps"):
        problems.append("findings, skips, or gaps cannot authorize retirement")
    configuration = sections.get("configuration", {})
    for key in ("depth", "max_defs"):
        if configuration.get(key) is not None and configuration[key] != config[key]:
            problems.append(f"custom {key} does not establish the full profile")
    expected_definitions = sum(definition_count(seed, config["max_defs"]) for seed in seeds)
    kernel = layers.get("kernel", {})
    expected_counts = {"cases": len(seeds), "positive_checks": 48 * len(seeds) + expected_definitions,
                       "negative_checks": 32 * len(seeds), "property_checks": 92 * len(seeds) + 3 * expected_definitions}
    if any(type(kernel.get(key)) is not int or kernel[key] != count for key, count in expected_counts.items()):
        problems.append("native kernel case or property counts differ from the complete seed profile")
    coverage = kernel.get("coverage", {})
    expected_groups = {
        "domains": {str(family): len(seeds) for family in range(18)},
        "negative_kinds": {name: len(seeds) for name in NEGATIVES + ["rel-out-of-scope"]},
        "properties": {**{name: len(seeds) for name in OPERATIONS + RELATIONS + CONTROLS},
                       **{name: expected_definitions for name in ("generated-independent", "delta-independent", "cold-independent")}},
    }
    for group, expected in expected_groups.items():
        if coverage.get(group) != expected or any(type(value) is not int for value in coverage.get(group, {}).values()):
            problems.append("native kernel " + group + " coverage is incomplete")
    forms = coverage.get("forms", {})
    if not isinstance(forms, dict) or set(forms) != set(FORMS) or any(type(count) is not int or count <= 0 for count in forms.values()):
        problems.append("all eight native generation forms were not exercised")
    if coverage.get("definitions") != expected_definitions or any(type(coverage.get(key)) is not int or coverage[key] <= 0 for key in ("nonfirst_rel", "earlier_references")):
        problems.append("generated definitions, nonfirst Rel mutation or earlier-reference evidence is missing")
    retained = layers.get("kernel-corpus", {})
    if retained.get("coverage", {}).get("case_ids") != {name: 1 for name in RETAINED_LAWS}:
        problems.append("typed retained corpus law inventory is incomplete")
    try:
        cases = load_cases(CORPUS_DIR)
        if any(check_case(case) for case in cases):
            problems.append("saved native corpus recipe contracts are malformed or stale")
        if retained.get("cases") != len(RETAINED_LAWS) + len(cases) or retained.get("coverage", {}).get("recipes", {}) != {case.name: 1 for case in cases}:
            problems.append("persistent native recipe corpus is incomplete")
        expected_retained = {
            "positive_checks": len(RETAINED_LAWS) - len(RETAINED_REJECTIONS),
            "negative_checks": len(RETAINED_REJECTIONS),
            "property_checks": len(RETAINED_LAWS) + sum(92 + 3 * definition_count(
                case.data["recipe"]["seed"], case.data["recipe"]["max_defs"]) for case in cases),
        }
        if any(type(retained.get(key)) is not int or retained[key] != count for key, count in expected_retained.items()):
            problems.append("typed retained or saved recipe property counts are incomplete")
    except (OSError, ValueError, TypeError):
        problems.append("persistent native recipe corpus is unavailable")
    return problems


def checker_evidence_problems(campaign, selected_faults, *, compiler):
    """Recheck saved isolated checker campaigns, including every source delta."""
    from frontend_regen import collect_units
    from ourosmith.checker_faults import BUILD_INPUTS, LAW_ENTRY, classify_run
    from ourosmith.faults import fault_texts
    from ourosmith.native import digest, receipt_for

    problems = []
    try:
        compiler = Path(compiler).resolve()
        work = (ROOT / campaign["directory"]).resolve()
        if not work.is_relative_to(ROOT / "_build") or not compiler.is_relative_to(ROOT):
            return ["checker campaign or producer path escapes its repository owner"]
        units = collect_units(LAW_ENTRY)
        paths = {ROOT / name for name in [*units, *BUILD_INPUTS]}
        paths.update(path for path in (ROOT / "runtime").iterdir() if path.suffix in {".c", ".h"})
        paths.add(compiler)
        current = {path.relative_to(ROOT).as_posix(): digest(path) for path in sorted(paths)}
        if (campaign["kind"] != "ouro.smith-checker-faults.v1" or campaign["law_entry"] != LAW_ENTRY
                or campaign["unchanged"] is not True or campaign["workers"] != 1
                or campaign["input_hashes_before"] != current or campaign["input_hashes_after"] != current
                or campaign["law_source_sha256"] != current[LAW_ENTRY]
                or campaign["compiler_sha256"] != digest(compiler)):
            problems.append("checker campaign inputs are incomplete, changed or stale")
        frozen = work / "frozen"
        if {path.relative_to(frozen).as_posix() for path in frozen.rglob("*") if path.is_file()} != set(units):
            problems.append("frozen checker source cone is incomplete or contains extra files")
        if any(digest(frozen / name) != current[name] for name in units):
            problems.append("frozen checker source bytes differ from current canonical inputs")
        variants = campaign["variants"]
        if [row.get("id") for row in variants] != [fault.id for fault in selected_faults]:
            return problems + ["checker campaign did not execute the exact selected mutant IDs"]
        baseline_toolchain = None
        for row, fault in zip([campaign["baseline"], *variants], [None, *selected_faults], strict=True):
            identity = "baseline" if fault is None else fault.id
            directory = work / identity
            executable = directory / ("laws.exe" if sys.platform == "win32" else "laws")
            steps = row["steps"]
            if row["id"] != identity or len(steps) != 3 or [step.get("phase") for step in steps] != ["strict-check", "build", "run"]:
                problems.append(identity + ": exact strict-check/build/run phases are missing")
                continue
            actual_units = [(directory / "source" / name).relative_to(ROOT).as_posix() for name in units]
            strict_command = [str(compiler), "check", actual_units[-1], "999999"]
            for name in actual_units:
                strict_command.extend(("--unit", name))
            if (steps[0]["command"] != strict_command or steps[2]["command"] != [str(executable)]
                    or any(step.get("status") != "ok" or type(step.get("returncode")) is not int or step["returncode"] != 0 for step in steps[:2])
                    or steps[0]["stderr"] or steps[0]["stdout"].replace("\r\n", "\n") != "CHECK_OK\n"
                    or "BUILD_TOOL_CACHE: miss " not in steps[1]["stdout"]):
                problems.append(identity + ": successful exact build phases were not recorded")
            for step in steps:
                for stream in ("stdout", "stderr"):
                    actual = (directory / (step["phase"] + "." + stream)).read_text(encoding="utf-8")
                    if actual.replace("\r\n", "\n") != step[stream].replace("\r\n", "\n"):
                        problems.append(identity + ": recorded process output differs from its saved log")
            mutations = {} if fault is None else fault_texts(fault, frozen)
            if not set(mutations).issubset(units) or any(name.startswith("tests/") for name in mutations):
                problems.append(identity + ": mutation escaped checker implementation sources")
            expected_sources = {}
            for name in units:
                expected = mutations[name].encode("utf-8") if name in mutations else (frozen / name).read_bytes()
                expected_sources[name] = hashlib.sha256(expected).hexdigest()
                if (directory / "source" / name).read_bytes() != expected:
                    problems.append(identity + ": unexpected source delta at " + name)
            if (row["intended_changed_files"] != sorted(mutations) or row["source_hashes_before"] != expected_sources
                    or row["source_hashes_after"] != expected_sources or row["source_unchanged"] is not True
                    or row["law_source_sha256"] != current[LAW_ENTRY] or row["compiler_sha256"] != digest(compiler)):
                problems.append(identity + ": exact frozen law and mutation hashes are incomplete")
            receipt, receipt_units, _sources = receipt_for(executable, actual_units[-1], compiler)
            toolchain = {key: value for key, value in receipt["inputs"].items() if key not in {"entry", "sources"}}
            if (receipt["cache"] != "miss" or receipt_units != actual_units
                    or row["binary_sha256"] != receipt["binary_sha256"]
                    or row["build_receipt_sha256"] != digest(Path(str(executable) + ".build.json"))
                    or row["toolchain"] != toolchain):
                problems.append(identity + ": source-bound fresh native build receipt is incomplete")
            if fault is None:
                baseline_toolchain = toolchain
            elif toolchain != baseline_toolchain:
                problems.append(identity + ": compiler or build configuration differs from the baseline")
            status, failed, _detail = classify_run(steps[2], None if fault is None else fault.expect)
            if (status != ("clean" if fault is None else "killed") or row["status"] != status
                    or row["failed_laws"] != failed):
                problems.append(identity + ": exact independent laws do not establish a clean baseline or intended kill")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        problems.append("checker campaign evidence is missing or malformed: " + str(error))
    return problems


def fault_provenance_problems(faults, current):
    """Fault campaigns require the original producer and every surface tool."""
    try:
        campaign = {**faults["checker"], "baseline": faults["baseline"]["evidence"]}
        compiler = Path(campaign["baseline"]["steps"][0]["command"][0]).resolve()
        paths = list(toolchain_paths(faults["surface_toolchain"], compiler=compiler).values())
        required = {path.relative_to(ROOT).as_posix() for path in paths}
        problems = provenance_problems(faults.get("provenance", {}), current, surface=True, required=required)
        problems.extend(checker_evidence_problems(campaign, [fault for fault in FAULTS if fault.target == "checker"], compiler=compiler))
    except (OSError, ValueError, KeyError, TypeError):
        return ["fault producer, native campaign or full tested binary set is missing"]
    else:
        return problems


def ci_pr_receipt(out, current):
    """Verify the full PR experiment actually executed by this CI aggregate."""
    from ci_gate import REPORT_KIND as CI_KIND, gates

    out = Path(out).resolve()
    expected = next(gate for gate in gates() if gate.name == "ouro-smith" and "pr" in gate.profiles)
    summary_path = out / "ci/ci-summary.json"
    summary = read(summary_path)
    if summary.get("kind") != CI_KIND or summary.get("profile") != "pr" or summary.get("group") != "all":
        return None, ["full CI aggregate is missing"]
    entries = summary.get("gates", [])
    if not isinstance(entries, list):
        return None, ["CI gates are malformed"]
    matches = [row for row in entries if isinstance(row, dict) and row.get("name") == expected.name]
    if len(matches) != 1:
        return None, ["CI Smith gate is missing or duplicated"]
    gate = matches[0]
    if gate.get("status") != "pass" or gate.get("returncode") != 0 or gate.get("command") != expected.cmd:
        return None, ["CI Smith gate did not execute the required command successfully"]
    log = out / "ci" / expected.name / "gate.log"
    try:
        if (ROOT / gate.get("log", "")).resolve() != log:
            return None, ["CI Smith gate log path differs"]
        report_path = (ROOT / expected.cmd[expected.cmd.index("--out") + 1] / "report.json").resolve()
        report_bytes = report_path.read_bytes()
        report = json.loads(report_bytes)
        if not isinstance(report, dict):
            return None, ["CI Smith report is malformed"]
        problems = profile_problems(report, "pr", current)
        if problems:
            return None, problems
        receipt = {"kind": "ouro.smith-ci-pr-receipt.v1", "gate": expected.name,
                   "command": expected.cmd, "source": current,
                   "ci_summary": str(summary_path), "ci_summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
                   "gate_log": str(log), "gate_log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
                   "report": str(report_path), "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
                   "fingerprint": report["fingerprint"]}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return None, [f"CI Smith evidence is unavailable or malformed: {exc}"]
    return receipt, []


def validation_problems(out):
    from ci_gate import gates
    from ourosmith.compiler_evidence import ci_compiler_receipt
    from ourosmith.validation import KIND, commands

    out = Path(out).resolve()
    current = source_state()
    problems = []
    try:
        ci_compiler_receipt(out)
    except (OSError, ValueError, KeyError, TypeError) as error:
        problems.append("compiler CI receipt is unavailable, malformed or stale: " + str(error))
    journal = read(out / "commands.json")
    rows = journal.get("commands", [])
    if journal.get("kind") != KIND or journal.get("complete") is not True or journal.get("unchanged") is not True:
        problems.append("validation journal is missing, incomplete, or changed sources")
    if journal.get("provenance", {}).get("source") != current:
        problems.append("validation journal source is stale")
    expected = commands(out)
    if [row.get("name") for row in rows] != [name for name, _ in expected]:
        problems.append("required validation commands were not all executed")
    for row, (name, argv) in zip(rows, expected, strict=False):
        if row.get("execution") == "ci" and name == "pr":
            receipt, errors = ci_pr_receipt(out, current)
            problems.extend("pr CI receipt: " + error for error in errors)
            if receipt is None or row.get("receipt") != receipt or row.get("command") != receipt["command"]:
                problems.append("pr CI receipt does not match the executed gate")
            else:
                try:
                    copied = (out / "pr/report.json").read_bytes()
                    if hashlib.sha256(copied).hexdigest() != receipt["report_sha256"]:
                        problems.append("pr report differs from the CI report")
                    if read(out / "pr.log") != receipt:
                        problems.append("pr CI receipt log differs")
                except OSError:
                    problems.append("pr CI report copy or receipt log is missing")
        elif row.get("command") != argv or row.get("execution", "direct") != "direct" or "receipt" in row:
            problems.append("required validation commands were not all executed")
    if any(row.get("status") != "PASS" or row.get("exit_code") != 0 for row in rows):
        problems.append("required command failed, skipped, or timed out")
    if any(not (out / (name + ".log")).is_file() for name, _ in expected):
        problems.append("required command logs are missing")
    reports = {}
    for name, profile in (("pr", "pr"), ("pr2", "pr"), ("kernel", "kernel"), ("nightly", "nightly")):
        report = reports[name] = read(out / name / "report.json")
        problems.extend(name + ": " + problem for problem in profile_problems(report, profile, current))
    if not reports["pr"].get("fingerprint") or reports["pr"].get("fingerprint") != reports["pr2"].get("fingerprint"):
        problems.append("two complete PR reports are not identical modulo timing")
    faults = read(out / "faults/faults.json")
    problems.extend("faults: " + problem for problem in fault_provenance_problems(faults, current))
    if faults.get("kind") != FAULTS_KIND or faults.get("pass") is not True or faults.get("generator_hash") != generator_hash():
        problems.append("fault injection is missing, failed, or stale")
    from ouro_smith import FAULT_SEEDS, PROFILES

    first_seed = PROFILES["pr"]["seed_base"]
    if faults.get("profile") != "pr" or faults.get("seeds") != list(range(first_seed, first_seed + FAULT_SEEDS["pr"])):
        problems.append("fault profile or seed set is incomplete")
    baseline = faults.get("baseline", {})
    if baseline.get("clean") is not True or baseline.get("findings") != 0 or baseline.get("skips") != 0 or faults.get("catalogue_problems") != []:
        problems.append("fault injection did not establish a clean baseline and catalogue")
    if faults.get("working_tree", {}).get("unchanged") is not True:
        problems.append("fault injection did not preserve the working tree")
    catalogue = {fault.id: fault for fault in FAULTS}
    results = faults.get("faults", [])
    if {row.get("id") for row in results} != set(catalogue) or len(results) != len(catalogue):
        problems.append("fault injection did not execute the entire catalogue")
    if any(row.get("status") != "killed" for row in results):
        problems.append("a critical source mutant survived or was unbuildable")
    for row in results:
        fault = catalogue.get(row.get("id"))
        if fault is not None and (row.get("expect") != list(fault.expect) or
                                  not all(any(tag.endswith(":" + prop) for tag in row.get("caught_by", [])) for prop in fault.expect)):
            problems.append("mutant kill did not report its expected property")
    ci = read(out / "ci/ci-summary.json")
    ci_rows = ci.get("gates", [])
    required_gates = {gate.name for gate in gates() if "pr" in gate.profiles}
    if ci.get("profile") != "pr" or {row.get("name") for row in ci_rows} != required_gates or len(ci_rows) != len(required_gates):
        problems.append("full PR aggregate is missing")
    if not ci_rows or any(row.get("status") != "pass" or row.get("returncode") != 0 for row in ci_rows):
        problems.append("PR aggregate contains failed, skipped, or unavailable gates")
    return sorted(set(problems))
