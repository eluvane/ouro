"""Explicit capability mappings for retirement of the historical corpus.

These are category contracts, not claims that old diagnostic prose or every
historical program is still valid. Unknown categories remain blocking gaps.
Paths here identify archived evidence; they are never compiler inputs.
"""
from __future__ import annotations

from ourosmith.surface.mutate import contract

CONTRACT_KIND = "ouro.smith-native-migration.v2"
RETIRED_CORE = "external/retirement/legacy-core-owner"
# This is an exact inventory of the retired decoder and semantic owners. The
# external evidence adapter checks their removal separately from executed laws.
LEGACY_CORE_OWNER_PATHS = tuple(sorted([
    "lib/kernel/dune",
    *("lib/kernel/" + name + extension
      for name in ("env", "error", "inductive", "kernel", "pp", "recheck", "reduction", "term", "typecheck", "universe", "validate", "value")
      for extension in (".ml", ".mli")),
    "tests/kernel/dune", "tests/kernel/smith_kernel_error.ml", "tests/kernel/smith_kernel_error.mli",
    "tests/kernel/smith_kernel_laws.ml", "tests/kernel/smith_kernel_property.ml", "tests/kernel/smith_kernel_replay.ml",
    "scripts/core_artifact.py", "scripts/kernel_recheck.py", "scripts/kernel_differential_gate.py",
    *("scripts/ourosmith/core/" + name + ".py"
      for name in ("gen", "mutate", "nested", "oracles", "pyworker", "refnorm", "terms")),
]))


def compiler(*names):
    return ["external/compiler/" + name for name in names]


def retained(*names):
    return ["kernel-corpus/case_ids/" + name for name in names]


CURRENT_COMPILER_OWNERS = (
    "compiler_check_tests", "compiler_module_tests", "compiler_primitive_binding_tests",
    "compiler_primitive_registry_tests", "compiler_property_tests", "compiler_reduce_tests",
    "compiler_result_tests", "compiler_retained_tests", "compiler_string_auth_tests", "compiler_string_nf_tests",
)


def features(*names):
    return ["surface/features/" + name for name in names]


def properties(*names):
    return ["surface/properties/" + name for name in names]


def negatives(*names):
    return ["surface/negative_kinds/" + name for name in names]


TYPED = features("literal", "var", "succ", "add", "lambda", "let", "ascribe", "match", "if",
                 "form:polymorphic-id", "form:polymorphic-sum", "form:large-elimination",
                 "form:indexed-phase-param", "form:enum", "form:list", "form:pair-match",
                 "form:nested-descent", "form:nested-tree-fold", "form:bounded-callback",
                 "form:handler", "form:handler-two-ops")
IMPORTS = features("parity:imports", "parity:imports-open-decl", "parity:imports-open-local",
                   "parity:imports-plain-alias", "parity:imports-record")
LINT_CLEAN = properties("lint-clean", "lint-clean-used-scopes", "lint-clean-handler-scopes",
                        "lint-clean-imported-refinement", "lint-clean-nullary-multi-match",
                        "lint-clean-refined-slots")
OLD_DIAGNOSTICS = {
    "unknown identifier": "unbound", "type mismatch": "type-mismatch", "positivity": "positivity",
    "missing branch": "coverage", "function type": "non-function", "non-Pi": "non-function",
    "termination": "termination", "pattern variable": "constructor-pattern-arity",
    "duplicate declaration": "duplicate-declaration", "duplicate": "duplicate-declaration",
    "hole": "anonymous-hole", "non-inductive": "non-inductive", "non-inductive type": "non-inductive",
    "unknown constructor": "unknown-constructor", "expected a sort": "sort-expected",
    "expected domain": "lambda-argument-domain", "unknown effect operation": "unknown-operation",
}


def manifest_strategy(prefix, tool, expected, diagnostic):
    if prefix == "M.invert":
        if tool == "lint":
            return properties("manifest-unsupported", "lint-clean", "lint-unused"), (
                "The native manifest supports check only and explicitly rejects lint rows. "
                "Lint acceptance and violations are checked directly; the obsolete manifest lint mode is retired.")
        return properties("manifest-accept", "manifest-reject", "manifest-invert-accept", "manifest-invert-reject"), ""
    if prefix.startswith("RT."):
        mapping = {"RT.io_prims": properties("io-reference"),
                   "RT.std_crypto": properties("stdlib-crypto", "stdlib-protocols", "io-reference") + features("io:delay-action"),
                   "RT.stdlib_smoke": properties("stdlib-strings", "stdlib-data", "stdlib-paths")}
        return mapping.get(prefix, []), "Python values and exact output replace check-only runtime rows."
    if expected == "pass":
        if tool == "lint":
            return LINT_CLEAN, "Positive generated scopes protect against false lint findings."
        mapping = {"ERGO.G": features("pipe", "form:list", "form:do-case-binding", "form:text-keywords"),
                   "REC.G": features("form:record") + properties("form-format-core"),
                   "IMP.G": IMPORTS + properties("import-alias-open-equality", "import-dependency-order"),
                   "A3.G": features("form:polymorphic-id", "ascribe", "let", "add", "if"),
                   "G.parse": TYPED,
                   "G.check": TYPED + properties("stdlib-workflow", "stdlib-application", "stdlib-tables")}
        return mapping.get(prefix, []), "Typed construction, independent values, and complete checked-program equality cover the historical construct family."
    if diagnostic in OLD_DIAGNOSTICS:
        return negatives(OLD_DIAGNOSTICS[diagnostic]), "Historical prose is replaced by the current exact diagnostic-class contract."
    for name, row in contract().items():
        if diagnostic and diagnostic in row["diagnostics"]:
            return negatives(name), ""
    if tool == "parse" and not diagnostic:
        return negatives("parse-missing-colon"), "Grammar rejection with a parse diagnostic; no claim of historical diagnostic text parity."
    return [], "No equivalent generated contract has been identified."


GOLDENS = {
    "doc/sample.golden.md": properties("doc-layout", "doc-signature-comment", "doc-check", "doc-drift"),
    "fmt/clean.golden": features("text-fmt-clean"),
    "fmt/messy.golden": features("text-fmt-layout"),
    "fmt/syntax_keep.golden": features("text-fmt-syntax"),
    "ergonomics/golden/pipe_list_letbang.golden.ouro": features("text-fmt-ergonomics"),
    "fix/arms.golden": features(*("text-fix-" + name for name in
        ("duplicate-arm", "catchall-arm", "multi-arm", "ordered-arms"))),
    "fix/binders.golden": features(*("text-fix-" + name for name in
        ("unused-parameter", "dotted-use", "nonrecursive", "recursive", "callback-preserved", "untyped-lambda",
         "typed-lambda", "binder-collision", "pattern-binder", "dead-let", "unused-bind", "effect-let", "hole-let"))),
    "fix/literals.golden": features(*("text-fix-" + name for name in
        ("numeral", "small-numeral", "pipeline", "numeral-argument", "list", "open-list", "nested-list",
         "nested-empty", "nested-rows", "list-element", "list-ascription", "list-argument", "string-list"))),
    "fix/legacy.golden": features(*("text-fix-" + name for name in
        ("duplicate-import", "distinct-import", "import-alias", "separator", "legacy-bind", "let-type-strings",
         "let-type-naturals", "let-type-nil", "let-type-cons", "opaque-elements", "empty-untyped", "comment-string"))),
    "fix/clean.golden": features(*("text-fix-" + name for name in
        ("comment-string", "shadow-preserved", "handler-preserved", "alias-binder", "alias-collision"))),
    "runtime/helpers_test.golden": properties("stdlib-helpers", "test-known-counts"),
    "runtime/io_prims.golden": properties("io-reference"),
    "runtime/stdlib_io_result.golden": properties("io-reference", "io-filesystem-state", "stdlib-paths"),
    "runtime/stdlib_smoke.golden": properties("stdlib-strings", "stdlib-data", "stdlib-paths"),
    "runtime/std_crypto.golden": properties("stdlib-crypto", "stdlib-protocols", "io-reference") + features("io:delay-action"),
    "syntax_quality/inline_cons.golden": ["external/ci/syntax-quality-firewall"],
    "syntax_quality/legacy.golden": ["external/ci/syntax-quality-firewall"],
}

KERNEL_NEGATIVES = {
    "constructor_index_out_of_range": "ctor-index", "constructor_universe_above_inductive": "universe",
    "fix_recarg_out_of_range": "fix-rec-arg-range", "forward_reference_constant": "forward-reference",
    "inductive_parameter_self_reference": "forward-reference", "invalid_constructor_return": "type-mismatch-def",
    "invalid_eliminator_coverage": "coverage", "malformed_case_branch_count": "case-branch-count",
    "malformed_environment_duplicate_global": "duplicate-global-axiom",
    "nested_negative_inductive_argument": "positivity-nested-contravariant", "nonpositive_constructor": "positivity-negative",
    "substitution_name_capture_open_let": "rel-out-of-scope", "wrong_body_type": "type-mismatch-def",
}
JSON_ONLY = {
    "bad_binder": "Textual binder fields belonged to the JSON decoder; typed Core uses de Bruijn indices. Out-of-scope indices remain separately tested.",
    "wrong_schema_kind": "The removed JSON transport owned the version discriminator; no native acceptance claim follows from retiring its schema.",
    "unmarked_axiom": "The JSON decoder's admit flag is removed with that transport. Typed FAxiom is an explicit declaration and FDef always supplies a checked body.",
}


def kernel_case(name, negative):
    if name in JSON_ONLY:
        return [RETIRED_CORE], JSON_ONLY[name], {"retired_owner": "legacy-json-transport"}
    if name in {"prim_literal_results", "prim_string_slice_start_past_end"}:
        return compiler("compiler_string_nf_tests"), "Literal operations use authenticated primitive roles and exact independently written typed normal forms.", {}
    if name == "string_literal_axiom":
        return retained(name, "string_literal_intrinsic") + compiler("compiler_string_auth_tests"), (
            "The old arbitrary String axiom acceptance is deliberately superseded: an authenticated String intrinsic accepts the bytes, while the same literal under an opaque axiom is rejected with its exact typed fault."), {}
    from ourosmith.corpus import RETAINED_LAWS

    if name not in RETAINED_LAWS:
        return [], "No native retained law has this identity.", {}
    strategies = retained(name)
    extra = {
        "case_branch_lambda_lift_under_binder": [name + "/check"],
        "nested_case_same_constructor_fields": [name + "/normalize", "copy preserves two successors"],
        "fix_binder_name_not_in_conversion": [name + "/constant-aliases", name + "/raw-fix"],
    }
    strategies += retained(*extra.get(name, []))
    if negative:
        strategies.append("kernel/negative_kinds/" + KERNEL_NEGATIVES.get(name, "UNMAPPED"))
    return strategies, "Typed retained fixtures preserve the exact declaration verdict, first failing declaration/phase/fault, and listed independent operation results.", {}

REGRESSION_LAWS = (
    "termination: eta-short case branch depth", "termination: case branch annotation traversal",
    "conv: stuck fixpoint application spines", "conv: stuck fixpoint recursion metadata", "conv: stuck case metadata",
    "validate: structural limits", "inductive: universe ceiling including mutual blocks", "env: reject global replacement",
    "term: case branch metadata pairing is fail-closed", "reduction: undeclared primitive is rigid",
    "conv: fixpoint closure type environments", "reduction: let-bound fix type reification",
    "conv: lambda versus non-function", "case: motive parameter coherence", "env: constant memo boundary",
)
HOTPATH_LAWS = ("term: zero lift preserves physical sharing", "term: free globals include case metadata and annotations",
                "scale: let-chain", "scale: lam-chain", "scale: app-spine", "scale: nested-app", "scale: domain-deep-pi", "scale: const-chain")

LAW_OWNERS = {
    "termination: eta-short case branch depth": retained("ML eta-short case branch rejects recursive escape"),
    "termination: case branch annotation traversal": retained("ML case branch annotation cannot capture recursion"),
    "conv: stuck fixpoint application spines": retained("ML stuck fix spines distinguish arguments"),
    "conv: stuck fixpoint recursion metadata": compiler("compiler_check_tests"),
    "conv: stuck case metadata": retained("ML stuck case distinguishes parameter metadata", "ML stuck case distinguishes constructor arity"),
    "validate: structural limits": compiler("compiler_result_tests") + [RETIRED_CORE],
    "inductive: universe ceiling including mutual blocks": compiler("compiler_module_tests") + retained(
        "constructor_universe_above_inductive", "ML universe ceiling level 1", "ML universe ceiling level 2",
        "ML universe ceiling admits level 1", "ML universe ceiling admits level 2", "ML universe ceiling admits level 3") + [RETIRED_CORE],
    "env: reject global replacement": compiler("compiler_check_tests") + [
        "kernel/negative_kinds/duplicate-global-axiom", "kernel/negative_kinds/duplicate-global-inductive"],
    "term: case branch metadata pairing is fail-closed": compiler("compiler_reduce_tests") + retained("malformed_case_branch_count") + [RETIRED_CORE],
    "reduction: undeclared primitive is rigid": compiler("compiler_string_nf_tests", "compiler_primitive_binding_tests"),
    "conv: fixpoint closure type environments": retained("ML captured fix type participates in conversion"),
    "reduction: let-bound fix type reification": retained("ML let-bound fix reifies its type environment"),
    "conv: lambda versus non-function": retained("ML non-function eta stays false"),
    "case: motive parameter coherence": compiler("compiler_check_tests"),
    "env: constant memo boundary": compiler("compiler_property_tests", "compiler_string_nf_tests", "compiler_primitive_binding_tests")
        + ["kernel/properties/delta-independent", "kernel/properties/cold-independent", RETIRED_CORE],
    "term: zero lift preserves physical sharing": [RETIRED_CORE],
    "term: free globals include case metadata and annotations": compiler("compiler_property_tests"),
    **{name: ["external/law/" + name] for name in HOTPATH_LAWS if name.startswith("scale:")},
    "depth: fail-closed on million-node terms": ["external/law/depth: fail-closed on million-node terms"],
}
LAW_NOTES = {
    "validate: structural limits": "Zero fix arity still requires exact CheckFixMetadata. Negative depth and machine max_int overflow belonged to the removed private OCaml validator; typed Core uses Nat and has a separate resource-result contract.",
    "inductive: universe ceiling including mutual blocks": "All single declarations at levels 0..2 and ordered High/Low batches remain checked, including rejection of the later Low and a valid two-member control. The historical Mutual API grouped two independent declarations; its separate representation is retired.",
    "term: case branch metadata pairing is fail-closed": "Malformed branch metadata retains exact checked reduction/acceptance faults. The old unchecked Term.lift Invalid_argument policy belongs to the retired traversal API.",
    "env: constant memo boundary": "Independent delta and cold/repeated normal forms remain required. Primitive authenticity replaces the old name-based operation/Nat lookup; OCaml axiom_dependent memo eligibility has no current cache owner and is retired explicitly.",
    "term: zero lift preserves physical sharing": "OCaml pointer identity was an allocation-policy contract of Term. Ouro reconstructs non-leaf nodes; structural lift/substitution equations remain separate required property laws, without a physical-sharing claim.",
}
API_LAWS = {
    "kernel_depth_regression.ml": ("depth: fail-closed on million-node terms",),
    "kernel_hotpath_regression.ml": HOTPATH_LAWS,
    "kernel_regression.ml": REGRESSION_LAWS,
}
API = {
    "kernel_property.ml": compiler("compiler_property_tests") + [RETIRED_CORE],
    "kernel_positivity_regression.ml": ["kernel/negative_kinds/positivity-nested-contravariant", "kernel/features/domain:4"]
        + retained("parameterized_recursive_sequence", "nested_negative_inductive_argument"),
    "kernel_corpus_replay.ml": compiler("compiler_retained_tests", "compiler_string_nf_tests") + properties("core-protocol") + [RETIRED_CORE],
}
API_NOTES = {
    "kernel_property.ml": "The full default 400 scoped and 400 typed samples preserve syntactic/type/normalization laws and nonfirst Rel mutations. Pointer-sharing and the private untyped Validate API retire with their explicit old owner; they are not counted as semantic passes.",
    "kernel_corpus_replay.ml": "Every representable input has an independent native verdict/operation owner. OCaml-versus-Python comparison and JSON decoding retire with both old implementations; checked-program surface equality is a separate retained property.",
}

COMPILER = {
    "const.ouro": features("literal"), "id.ouro": features("lambda", "var"),
    "let_ex.ouro": features("let"), "nat_mini.ouro": features("succ", "add", "match"),
    "selfcontained.ouro": features("literal", "lambda", "succ"),
    "imp_a.ouro": IMPORTS, "imp_b.ouro": IMPORTS,
    "lex_input.ouro": negatives("lex-trailing-invalid", "lex-unterminated-string", "lex-bare-operator", "lex-fuel")
                        + properties("module-suffix-reject", "module-suffix-valid"),
    "deep_recursion.ouro": features("backend:non-tail-depth"),
    "c_backend.ouro": features("lambda", "let", "form:list", "form:pair-match", "form:nested-tree-fold",
                               "form:applied-lambda-curried-match") + properties("runtime-reference"),
}

EXTRA = {
    "test/eval_contract.ouro": properties("eval-reference", "eval-negative", "parity-host-core"),
    "test/suite/lsp/sample.ouro": properties("lsp-definition", "lsp-hover", "lsp-symbol") + ["external/ci/lsp"],
    "test/suite/lsp/messy.ouro": ["external/ci/lsp"],
    "test/suite/runtime/fail_test.ouro": properties("test-runner-fail", "test-known-counts"),
    "test/suite/runtime/selected_declaration.ouro": ["external/ci/test"],
    "test/suite/imports/lib/nat_lib.ouro": IMPORTS,
    "test/suite/security/bad/lex_bare_operator.ouro": negatives("lex-bare-operator"),
    "test/suite/security/bad/lex_trailing_invalid.ouro": negatives("lex-trailing-invalid"),
    "test/suite/security/bad/lex_unterminated_string.ouro": negatives("lex-unterminated-string"),
    "test/suite/bad/lint/921_preprocess_import.ouro": negatives("lint-import-malformed"),
    "test/suite/good/lint/910_multi_match_eq.ouro": properties("lint-clean-nullary-multi-match"),
    "test/suite/good/check/900_practical_stdlib_shape.ouro": properties("stdlib-workflow", "stdlib-data", "stdlib-strings", "stdlib-tables"),
    "test/suite/good/check/901_practical_error_paths.ouro": properties("stdlib-workflow", "stdlib-tables"),
    "test/suite/good/check/902_practical_workflow_shape.ouro": properties("stdlib-workflow", "stdlib-tables"),
    "test/suite/good/check/903_practical_application_surface_shape.ouro": properties("stdlib-application"),
}

SUPPORT = {
    "test/kernel/README.md": "Kernel execution and corpus documentation is maintained in docs/kernel_design.md and docs/ouro_smith.md.",
    "test/kernel/dune": "The native compiler suite registry executes the typed successors; source-bound compiler evidence is mandatory.",
    "test/kernel/kernel_regression.mli": "Empty OCaml test executable interface; no acceptance contract beyond the associated laws.",
    "test/suite/manifest.tsv": "Every manifest category is inventoried separately, including intentional inverted expectations.",
    "test/suite/ergonomics/README.md": "Generated ergonomics contracts and replay replace the historical invocation documentation.",
}
