"""Source-derived frontend inventory and explicit oracle limitations."""
from __future__ import annotations

import re

from ourosmith import ROOT
from ourosmith.surface import forms, gen, mutate


def constructors(path, name):
    text = (ROOT / path).read_text(encoding="utf-8")
    text = re.sub(r'--[^\r\n]*|"(?:\\.|[^"\\])*"', " ", text)
    block = re.search(r"inductive " + name + r"\b[^;]+;", text)
    if block is None:
        raise ValueError(f"cannot extract {name} from {path}")
    return re.findall(r"\|\s*(\w+)\s*:", block[0])


def inventory():
    diagnostic = (ROOT / "runtime/frontend_link.c").read_text(encoding="utf-8")
    # compile_file.ouro uses code 1 for pipeline failure; compiler.ouro uses
    # codes 2/3 for lowering/duplicate named declarations before fe_link's
    # later declaration checker runs.
    codes = {1, 2, 3, 10, 11, 12}
    for start, end in re.findall(r"code >= (\d+) && code <= (\d+)", diagnostic):
        codes.update(range(int(start), int(end) + 1))
    lint = (ROOT / "tools/lint_host.ouro").read_text(encoding="utf-8")
    return {
        "expr": constructors("compiler/ast.ouro", "Expr"),
        "analyzer_ast": constructors("tools/analyze/ast.ouro", "Ast"),
        "decl": constructors("compiler/ast.ouro", "Decl"),
        "token": constructors("compiler/token.ouro", "Token"),
        "keyword": re.findall(r"^def (kw\w+) : Nat", (ROOT / "compiler/token.ouro").read_text(encoding="utf-8"), re.M),
        "diagnostic": sorted(set(re.findall(r'"(OURO-[A-Z]+-\d+)"', diagnostic)) | {f"CErr code={code}" for code in codes}),
        "lint": sorted(set(re.findall(r'MkWarnText "OURO-LINT\d+" "([a-z-]+)"', lint))),
    }


EXPR = {
    "EVar": "feature:var", "EHole": "negative:named-hole", "ESort": "feature:prelude",
    "ENat": "feature:literal", "EApp": "feature:add", "ELam": "feature:lambda",
    "EPi": "feature:prelude", "ELet": "feature:let", "EAscribe": "feature:ascribe",
    "EMatch": "feature:match", "EFix": "feature:prelude", "EPerform": "feature:form:handler",
    "EDo": "property:test-known-counts", "EHandle": "feature:form:handler",
    "EBranch": "feature:match", "ENoBranch": "feature:match", "EBinder": "feature:prelude",
    "ENoBinder": "feature:prelude", "EMultiMatch": "feature:form:multi-match",
    "EStr": "feature:string-length", "EDoBind": "property:test-known-counts", "EList": "feature:form:list",
    "ESpan": "feature:parser:abi-and-grammar", "EFallible": "feature:form:fallible-block",
}
DECL = {"DDef": "feature:prelude", "DAxiom": "negative:effect-root-assumption-type", "DInductive": "feature:prelude",
        "DEffect": "feature:form:handler", "DImport": "property:import-dependency-order",
        "DIntrinsic": "feature:prelude", "DRepresentation": "feature:prelude", "DExtern": "feature:form:extern-declaration"}
TOKEN = dict.fromkeys(("TIdent", "TNat", "TKeyword", "TType", "TColon", "TColonEq", "TArrow", "TFatArrow",
                       "TBar", "TLparen", "TRparen", "TSemi", "TEof"), "feature:prelude")
TOKEN.update({"THole": "negative:named-hole", "TString": "feature:string-length", "TComma": "feature:form:list",
              "TBraceL": "feature:form:record", "TBraceR": "feature:form:record", "TBind": "property:test-known-counts",
              "TPipe": "feature:pipe", "TBracketL": "feature:form:list", "TBracketR": "feature:form:list"})
KEYWORD = dict.fromkeys(("kwDef", "kwInductive", "kwFun", "kwMatch", "kwWith", "kwEnd", "kwLet", "kwIn", "kwFix",
                        "kwIntrinsic", "kwRepresentation"), "feature:prelude")
KEYWORD.update({"kwImport": "property:import-dependency-order", "kwEffect": "feature:form:handler",
                "kwWhere": "feature:form:handler", "kwDo": "property:test-known-counts",
                "kwPerform": "feature:form:handler", "kwHandle": "feature:form:handler", "kwRecord": "feature:form:record",
                "kwAxiom": "negative:effect-root-assumption-type", "kwExtern": "feature:form:extern-declaration"})

# Each exception names an actual missing oracle, rather than accepting new
# source inventory items automatically. Migration checks treat these as gaps.
EXCEPTIONS = {
    "expr:EEffectRow": "The reference evaluator models closed handlers; effect-row typing and row polymorphism have no independent surface oracle yet.",
    "token:TExclam": "Effect-row annotations have no independent surface typing oracle yet.",
    "diagnostic:CErr code=46": "Malformed internal Core and plan states are checked by tests/compiler_result_tests.ouro and tests/compiler_plan_tests.ouro; no surface text is known to reach this internal diagnostic.",
    "diagnostic:CErr code=48": "Cancellation is an explicit CheckDirective API operation, with no source-text or public CLI cancellation syntax; tests/compiler_module_tests.ouro checks cancellation before and between declarations.",
    "diagnostic:CErr code=49": "Internal worker failures are injected through the module callback API in tests/compiler_module_tests.ouro; malformed host results fail closed and are not a generated source-text case.",
    "lint:empty-match": "compiler/lint.ouro intentionally does not emit WEmptyMatch: untyped syntax cannot distinguish valid empty-type elimination. Kernel coverage mutations test rejection.",
    "lint:unused-def": "lintModule is not called by tools/lint_host.ouro; this declared warning has no public CLI producer.",
    "lint:unused-ctor": "lintModule is not called by tools/lint_host.ouro; this declared warning has no public CLI producer.",
    "lint:unused-ind": "lintModule is not called by tools/lint_host.ouro; this declared warning has no public CLI producer.",
    "lint:empty-telescope": "The public parser rejects binder-free fix syntax before lint reaches WEmptyTelescope. The rule remains applicable to its internal AST API.",
}


def strategies():
    from ourosmith.surface.analyzer import AST_TAGS
    from ourosmith.surface.library import FAMILIES
    from ourosmith.surface.io import FEATURES as IO_FEATURES
    from ourosmith.surface.text_contracts import FEATURES as TEXT_FEATURES
    from ourosmith.surface.lint_contracts import FEATURES as LINT_FEATURES
    from ourosmith.surface.parity import inputs as parity_inputs

    contract = mutate.contract()
    diagnostics, lint = {}, {}
    numeric = {"HOLE": 60, "DO": 61, "PIPE": 62, "LIST": 63, "REC": 70, "IMP": 80}
    for name, entry in contract.items():
        for code in entry["diagnostics"]:
            if code.endswith(":"):
                lint[code[:-1]] = "negative:" + name
            else:
                diagnostics[code] = "negative:" + name
                match = re.fullmatch(r"OURO-([A-Z]+)-(\d+)", code)
                if match and match[1] in numeric:
                    diagnostics[f"CErr code={numeric[match[1]] + int(match[2])}"] = "negative:" + name
    return {"items": {"expr": EXPR, "analyzer_ast": {tag: "feature:analyzer:" + tag for tag in AST_TAGS},
                       "decl": DECL, "token": TOKEN, "keyword": KEYWORD,
                       "diagnostic": diagnostics, "lint": lint},
            "exceptions": EXCEPTIONS,
            "generator_features": ["prelude", *gen.FEATURES, *("form:" + name for name in forms.FEATURES),
                                   *("stdlib:" + name for name in FAMILIES), *("analyzer:" + tag for tag in AST_TAGS),
                                   *("io:" + name for name in IO_FEATURES), *("text-" + name for name in TEXT_FEATURES),
                                   *("lint-clean:" + name for name in LINT_FEATURES), "analyzer:line-splitting",
                                   *("parity:" + case["name"] for case in parity_inputs(1) if "expected" in case),
                                   "backend:non-tail-depth", "manifest:integrity"],
            "negative_strategies": contract}


def compare(source, declared, coverage=None):
    problems = []
    groups = {"feature": "features", "negative": "negative_kinds", "property": "properties"}
    for family, items in source.items():
        mapping = declared.get("items", {}).get(family, {})
        for item in items:
            strategy = mapping.get(item)
            if not strategy:
                if not declared.get("exceptions", {}).get(f"{family}:{item}"):
                    problems.append(f"surface {family}:{item} has no strategy or explicit exception")
            elif coverage is not None:
                group, key = strategy.split(":", 1)
                if not coverage.get(groups[group], {}).get(key, 0):
                    problems.append(f"surface {family}:{item} strategy {strategy} was not exercised")
    if coverage is not None:
        for feature in declared.get("generator_features", []):
            if not coverage.get("features", {}).get(feature):
                problems.append(f"surface generator feature {feature} was not exercised")
    return sorted(set(problems))
