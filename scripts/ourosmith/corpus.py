"""Typed retained laws and saved native generation recipes; no Core JSON decoder."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ourosmith import ROOT
from ourosmith.core.run import CoreRunner, read_recipe
from ourosmith.report import Finding

LAYER = "kernel-corpus"
CORPUS_DIR = ROOT / "quality/smith/corpus/native"
CORPUS_KIND = "ouro.smith-native-corpus.v1"
NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
RETAINED_LAWS = """nat_id
bool_case
case_branch_lambda_lift_under_binder
case_branch_lambda_lift_under_binder/check
nested_case_same_constructor_fields
nested_case_same_constructor_fields/normalize
fix_binder_name_not_in_conversion
fix_binder_name_not_in_conversion/constant-aliases
fix_binder_name_not_in_conversion/raw-fix
copy preserves two successors
parameterized_box
parameterized_recursive_sequence
string_literal_intrinsic
string_literal_axiom
wrong_body_type
constructor_index_out_of_range
fix_recarg_out_of_range
forward_reference_constant
substitution_name_capture_open_let
malformed_case_branch_count
invalid_eliminator_coverage
malformed_environment_duplicate_global
constructor_universe_above_inductive
nonpositive_constructor
nested_negative_inductive_argument
inductive_parameter_self_reference
invalid_constructor_return
ML eta-short case branch rejects recursive escape
ML case branch annotation cannot capture recursion
ML stuck fix spines distinguish arguments
ML stuck case distinguishes parameter metadata
ML stuck case distinguishes constructor arity
ML captured fix type participates in conversion
ML let-bound fix reifies its type environment
ML non-function eta stays false
ML universe ceiling level 1
ML universe ceiling level 2
ML universe ceiling admits level 1
ML universe ceiling admits level 2
ML universe ceiling admits level 3
local type alias enters a checked lambda annotation
local type alias direct checking
local type alias inference
nested strict descent
nested nonzero recursive argument
nested eta-short identity body
nested strict computes identity
nested nonzero argument computes identity
nested eta-short computes identity
nested unchanged initial argument
nested growing inner recursion
nested growing other parameter
nested captured unchanged argument
nested partial function escape
nested function argument escape""".splitlines()
RETAINED_REJECTIONS = frozenset(RETAINED_LAWS[13:27] + RETAINED_LAWS[27:33]
                               + RETAINED_LAWS[34:37] + RETAINED_LAWS[49:55])


@dataclass
class CorpusCase:
    path: Path
    data: dict

    @property
    def name(self):
        return self.data.get("name", "")


def write_case(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def check_case(case, *, check_format=True):
    value = case.data
    problems = []
    if not isinstance(value, dict) or value.get("kind") != CORPUS_KIND:
        return ["legacy Core JSON transport is retired; port the case to a typed Ouro law or native seed recipe"]
    if set(value) != {"kind", "name", "recipe", "expect", "origin"}:
        problems.append("native corpus record fields are incomplete or unknown")
    if not isinstance(value.get("name"), str) or not NAME_RE.fullmatch(value["name"]) or case.path.stem != value["name"]:
        problems.append("native corpus name must match its safe filename")
    if value.get("expect") != "all-native-properties-hold":
        problems.append("native corpus requires every independent native property to hold")
    try:
        read_recipe(value.get("recipe"))
    except ValueError as error:
        problems.append(str(error))
    if not isinstance(value.get("origin"), dict) or not value["origin"].get("property"):
        problems.append("native corpus origin must identify the original property")
    if check_format and case.path.is_file() and case.path.read_text(encoding="utf-8") != json.dumps(value, indent=1, sort_keys=True) + "\n":
        problems.append("native corpus record is not canonically formatted")
    return problems


def load_cases(directory=CORPUS_DIR):
    directory = Path(directory)
    cases = [CorpusCase(path, json.loads(path.read_text(encoding="utf-8"))) for path in sorted(directory.glob("*.json"))]
    if len({case.name for case in cases}) != len(cases):
        raise ValueError("native corpus case IDs are duplicated")
    return cases


def finding_case(finding, name, *, note=""):
    if not NAME_RE.fullmatch(name):
        raise ValueError("corpus name must match [a-z0-9][a-z0-9_-]*")
    read_recipe(finding.get("minimal_input"))
    if finding.get("layer") != "kernel" or not finding.get("prop") or finding.get("generator_hash") != finding["minimal_input"]["generator_hash"]:
        raise ValueError("native finding identity or generator hash is inconsistent")
    return {"kind": CORPUS_KIND, "name": name, "recipe": finding["minimal_input"],
            "expect": "all-native-properties-hold",
            "origin": {"property": finding["prop"], "classification": finding.get("classification"),
                       "actual": finding.get("actual"), "note": note}}


def promote_finding(finding, name, *, directory=CORPUS_DIR, note=""):
    value = finding_case(finding, name, note=note)
    path = Path(directory) / (name + ".json")
    if path.exists():
        raise ValueError("corpus case already exists: " + name)
    write_case(path, value)
    return path


def inspect_retained(result):
    if result.status != "ok" or result.returncode not in (0, 1) or result.stderr:
        return [("native-process", result.classify(), result.stderr)]
    lines = result.stdout.splitlines()
    if len(lines) != len(RETAINED_LAWS) + 1:
        return [("native-protocol", "oracle-unavailable", "retained law count or terminal missing")]
    failures = []
    for name, line in zip(RETAINED_LAWS, lines[:-1], strict=True):
        if line == "PASS " + name:
            continue
        if line.startswith("FAIL " + name + ": "):
            failures.append((name, "property-violation", line.removeprefix("FAIL " + name + ": ")))
        else:
            return [("native-protocol", "oracle-unavailable", "retained law is missing, duplicated or reordered: " + name)]
    if lines[-1] != ("COMPILER_RETAINED: FAIL" if failures else "COMPILER_RETAINED: PASS") or result.returncode != int(bool(failures)):
        return [("native-protocol", "oracle-unavailable", "retained terminal and exit disagree with law results")]
    return failures


def run_corpus(report, program, *, timeout_s=20, directory=CORPUS_DIR, only=None, smith_program=None):
    cases = load_cases(directory)
    if Path(directory) != CORPUS_DIR and not cases:
        report.gap(LAYER, "corpus", "no native recipe cases under " + str(directory), blocking=True)
        return
    for case in cases:
        issues = check_case(case)
        if issues:
            report.gap(LAYER, "corpus", f"{case.name}: {'; '.join(issues)}", blocking=True)
    if report.blocking_gaps:
        return
    if only is not None and only not in RETAINED_LAWS and only not in {case.name for case in cases}:
        raise ValueError("unknown typed retained law or native recipe: " + only)
    # The current typed runner executes every retained law. --only selects the
    # requested regression while preserving this stronger, honestly counted run.
    result = program.run([], "retained", timeout_s)
    summary = report.layer(LAYER)
    summary.cases += len(RETAINED_LAWS)
    failures = inspect_retained(result)
    if failures:
        for name, category, detail in failures:
            if category not in {"crash", "timeout", "memory", "property-violation", "oracle-unavailable"}:
                category = "oracle-unavailable"
            report.add(Finding(LAYER, name, category, 0, report.profile, report.generator_hash, name,
                               "native-retained", "typed retained law holds", detail,
                               {"entry": program.entry, "law": name}, "python scripts/ouro_smith.py corpus"))
    else:
        summary.property_checks += len(RETAINED_LAWS)
        summary.positive_checks += len(RETAINED_LAWS) - len(RETAINED_REJECTIONS)
        summary.negative_checks += len(RETAINED_REJECTIONS)
        summary.coverage = {"case_ids": {name: 1 for name in RETAINED_LAWS}, "recipes": {}}
    report.timing["kernel.corpus_s"] = result.elapsed_s
    report.timing["kernel.corpus_peak_memory_mib"] = result.peak_rss_mb
    if only is not None:
        summary.notes.append("Requested " + only + "; native driver executed every retained law")
    selected = [case for case in cases if only is None or case.name == only]
    if selected and smith_program is None:
        report.skip("kernel-corpus:recipes", "native Smith driver unavailable for saved recipes")
        return
    for case in selected:
        config = read_recipe(case.data["recipe"])
        laws, failure = CoreRunner(config, report, smith_program, timeout_s=timeout_s).evaluate(config, config.seeds[0])
        summary.cases += 1
        if failure is not None:
            report.add(Finding(LAYER, failure.prop, failure.classification, config.seeds[0], report.profile,
                               report.generator_hash, case.name, "native-recipe", failure.expected, failure.detail,
                               case.data["recipe"], f"python scripts/ouro_smith.py corpus --only {case.name}"))
        else:
            summary.property_checks += 92 + 3 * laws["definitions"]
            summary.coverage.setdefault("recipes", {})[case.name] = 1
