"""Canonical source inventory and exercised native Smith strategy accounting.

Separate compiler suites own new primitive and malformed/resource domains.
Their explicit owner mappings are not generated Smith coverage; retirement
must also carry the corresponding executed compiler-suite evidence.
"""
from __future__ import annotations

import json
import re

from ourosmith import ROOT
from ourosmith.core.run import CONTROLS, FORMS, NEGATIVES, OPERATIONS, RELATIONS
from ourosmith.surface import inventory as surface_inventory

STRATEGIES_PATH = ROOT / "quality/smith/strategies.json"
STRATEGIES_KIND = "ouro.smith-strategies.v2"
CONTRACT_PATH = STRATEGIES_PATH.with_name("diagnostic_contract.json")

TERM_FEATURES = {
    "CRel": ["form:let"], "CSort": ["domain:14"], "CPi": ["domain:12"],
    "CLam": ["form:beta"], "CApp": ["form:beta"], "CLetIn": ["form:let"],
    "CConst": ["domain:10"], "CInd": ["domain:13"],
    "CConstruct": ["domain:0"], "CCase": ["form:nat-case"],
    "CFix": ["form:structural-fold"], "CStrBytes": ["domain:11"],
}
NEGATIVE_FAULTS = {
    "CheckTypeMismatch": ["type-mismatch-def", "type-mismatch-argument", "type-mismatch-parameter", "lambda-annotation-mismatch", "sort-level-too-big"],
    "CheckExpectedSort": ["sort-expected"], "CheckExpectedFunction": ["not-pi"],
    "CheckCaseMotive": ["not-inductive"], "CheckNonPositive": ["positivity-negative", "positivity-nested-contravariant"],
    "CheckNonTerminating": [name for name in NEGATIVES if name == "termination" or name.startswith("termination-")],
    "CheckUniverseBound": ["universe"], "CheckUnboundVariable": ["rel-out-of-scope"],
    "CheckUnboundGlobal": ["unbound-global-constant"], "CheckUnknownInductive": ["unbound-global-inductive", "forward-reference"],
    "CheckUnknownConstructor": ["ctor-index"], "CheckConstructorParameters": ["ctor-nparams"],
    "CheckCaseMetadata": ["coverage", "case-arity", "case-wrong-inductive", "case-branch-count"],
    "CheckFixMetadata": ["fix-arity", "fix-rec-arg-range"],
    "CheckDuplicateName": ["duplicate-global-axiom", "duplicate-global-inductive"],
}
STRING_PROPERTIES = {
    "PrimitiveStringConcat": "string-concat-order", "PrimitiveStringLength": "string-length-bytes",
    "PrimitiveStringSlice": "string-slice-clamped", "PrimitiveStringEqual": "string-equality",
    "PrimitiveStringOfNat": "string-of-nat-decimal", "PrimitiveStringToCodes": "string-to-codes",
    "PrimitiveStringOfCodes": "string-of-codes",
}
EXTERNAL = {
    "CStrLit": "compiler_string_nf_tests", "FExtern": "compiler_primitive_binding_tests",
    "CheckLiteralType": "compiler_string_auth_tests", "CheckUnresolvedLiteral": "compiler_string_nf_tests",
    "CheckReductionFailure": "compiler_result_tests", "CheckResourceLimit": "compiler_result_tests",
    "CheckUnsupported": "compiler_module_tests", "CheckCancelled": "compiler_module_tests",
    "CheckInternalFailure": "compiler_module_tests", "CheckPrimitiveFailure": "compiler_primitive_binding_tests",
}
for _name in """PrimitiveU8Type PrimitiveU32Type PrimitiveU64Type PrimitiveI32Type PrimitiveUSizeType
PrimitiveRawPtrType PrimitiveRuntimeType PrimitiveRawFnType PrimitiveWordOperation PrimitiveWordConversion
PrimitiveWordFromNat PrimitiveWordToNat PrimitiveRuntimePure PrimitiveRuntimeBind PrimitiveRuntimeLoop
PrimitiveRawNull PrimitiveRawLoad PrimitiveRawStore PrimitiveRawAddWrap PrimitiveRawCast PrimitiveRawToBits
PrimitiveRawFromBits PrimitiveFnCall""".split():
    EXTERNAL[_name] = "compiler_primitive_registry_tests"
for _name in """PrimitiveStringByteAt PrimitiveStringStarts PrimitiveStringEnds PrimitiveStringContains
PrimitiveStringIndex PrimitiveStringSplit PrimitiveStringReplace PrimitiveStringLessEqual PrimitiveStringTokens""".split():
    EXTERNAL[_name] = "compiler_string_nf_tests"


def constructors(path, name):
    return surface_inventory.constructors(path, name)


def source_inventory():
    model = "compiler/file_check_model.ouro"
    return {
        "term_constructors": constructors("compiler/core.ouro", "CoreTerm"),
        "type_faults": constructors(model, "CheckTypeFault"),
        "core_faults": constructors(model, "CheckCoreFault"),
        "failure_kinds": constructors(model, "CheckFailure"),
        "declaration_kinds": constructors(model, "FileItem"),
        "primitives": constructors("compiler/primitive_model.ouro", "PrimitiveId"),
        "string_operations": constructors("compiler/primitive_model.ouro", "PrimitiveStringOp"),
        "surface": surface_inventory.inventory(),
    }


def generator_features():
    return [*("domain:" + str(number) for number in range(18)), *("form:" + name for name in FORMS),
            "mutation:nonfirst-rel", "definition:earlier-reference"]


def code_strategies():
    negatives = {name: {"family": "typed", "faults": sorted(fault for fault, names in NEGATIVE_FAULTS.items() if name in names)}
                 for name in sorted(NEGATIVES + ["rel-out-of-scope"])}
    return {"kind": STRATEGIES_KIND, "layers": {"kernel": {
        "owner": "tests/compiler_smith_runner.ouro", "generator_features": generator_features(),
        "term_tag_features": TERM_FEATURES, "negative_strategies": negatives,
        "properties": sorted(OPERATIONS + RELATIONS + CONTROLS + ["generated-independent", "delta-independent", "cold-independent"]),
        "declaration_kinds": ["FDef", "FAxiom", "FInd", "FIntrinsic", "FRepresentation"],
        "failure_kinds": ["CheckTypeFailure", "CheckMalformedCore"],
        "primitives": {"PrimitiveStringType": ["domain:11"], "PrimitiveStringOperation": list(STRING_PROPERTIES.values())},
        "string_operations": STRING_PROPERTIES,
        "external_owners": {name: "tests/" + owner + ".ouro" for name, owner in sorted(EXTERNAL.items())},
    }, "surface": surface_inventory.strategies()}}


def load_strategies(path=None):
    path = STRATEGIES_PATH if path is None else path
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def write_strategies(data, path=None):
    path = STRATEGIES_PATH if path is None else path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    if path == STRATEGIES_PATH:
        CONTRACT_PATH.write_text(json.dumps({"kind": "ouro.smith-diagnostic-contract.v1", "mutations": data["layers"]["surface"]["negative_strategies"]}, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def compare(inventory, strategies, *, coverage=None):
    problems = []
    kernel = strategies.get("layers", {}).get("kernel", {})
    external = kernel.get("external_owners", {})
    features = set(kernel.get("generator_features", []))
    for name, path in external.items():
        if path != "tests/" + EXTERNAL.get(name, "UNMAPPED") + ".ouro" or not (ROOT / path).is_file():
            problems.append(f"external canonical owner is missing or changed for {name}")
    domains = {
        "term_constructors": kernel.get("term_tag_features", {}),
        "declaration_kinds": kernel.get("declaration_kinds", []),
        "failure_kinds": kernel.get("failure_kinds", []),
        "primitives": kernel.get("primitives", {}),
        "string_operations": kernel.get("string_operations", {}),
    }
    targeted = {fault for row in kernel.get("negative_strategies", {}).values() for fault in row.get("faults", [])}
    domains.update(type_faults=targeted, core_faults=targeted)
    for group, registered in domains.items():
        for name in inventory[group]:
            if name not in registered and name not in external:
                problems.append(f"{group} {name} has no native strategy or explicit canonical suite owner")
        for name in set(registered) - set(inventory[group]):
            if group not in {"type_faults", "core_faults"}:
                problems.append(f"stale {group} strategy {name}")
    for name, names in kernel.get("term_tag_features", {}).items():
        if not names or set(names) - features:
            problems.append(f"term constructor {name} references missing generator features")
    expected_negatives = set(NEGATIVES + ["rel-out-of-scope"])
    negatives = kernel.get("negative_strategies", {})
    if set(negatives) != expected_negatives or any(not value.get("faults") for value in negatives.values()):
        problems.append("native negative strategy names or exact typed fault mappings are incomplete")
    # Labels come from actual native law inputs; a changed label cannot silently
    # retain a formerly recorded strategy under the host protocol.
    source = (ROOT / "tests/compiler_smith_negative.ouro").read_text(encoding="utf-8")
    labels = set(re.findall(r'(?:smith_negative_(?:body|one|nested)|SmithNegativeOf)\s+"([a-z0-9-]+)"', source))
    if not set(NEGATIVES).issubset(labels):
        problems.append("native negative protocol differs from the typed source fixtures")
    if coverage is not None:
        for name in sorted(features - set(coverage.get("features", {}))):
            problems.append(f"declared generator feature {name} was not exercised")
        for name in sorted(expected_negatives - set(coverage.get("negative_kinds", {}))):
            problems.append(f"declared negative strategy {name} was not exercised")
        for name in sorted(set(kernel.get("properties", [])) - set(coverage.get("properties", {}))):
            problems.append(f"declared native property {name} was not exercised")
    problems.extend(surface_inventory.compare(inventory["surface"], strategies.get("layers", {}).get("surface", {})))
    return problems


def stale(strategies):
    current = code_strategies()
    problems = []
    if strategies.get("kind") != STRATEGIES_KIND or strategies.get("layers", {}).get("kernel") != current["layers"]["kernel"]:
        problems.append("strategies.json native kernel contracts differ from current sources (run inventory --write)")
    if strategies.get("layers", {}).get("surface") != current["layers"]["surface"]:
        problems.append("strategies.json surface contracts differ from current sources (run inventory --write)")
    if not CONTRACT_PATH.is_file() or json.loads(CONTRACT_PATH.read_text(encoding="utf-8")).get("mutations") != current["layers"]["surface"]["negative_strategies"]:
        problems.append("diagnostic_contract.json differs from registered surface mutation contracts")
    return problems
