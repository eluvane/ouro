# Native quality precision pass: delivery record

Date: 2026-09-17. Status: **useful partial WIP; not a production-green closure**.

This pass modifies the supplied archive only. The detailed rule-by-rule decisions
are in `clippy_rule_audit.json`; actual commands, outcomes and source-case hashes
are in `quality_precision_validation.json`. Native binaries were built with the
current bootstrap **p1** compiler. Final bootstrap/parity did not finish, so those
binaries must not be described as a verified release toolchain.

## Implemented changes

The active line/definition-guessing Clippy pipeline and its six implementation
modules were removed. The previous inventory had 45 registered rules: 30
unsupported heuristic rules were retired, and two already-present semantic PERF
rules were registered, leaving 17 active rules. The audit records every decision.
This is not a downgrade of retained strict/release levels. Naming guesses
including `OURO-CLIPPY-NAMING-002`, size/parameter/depth smells, filename/import
layer guesses, CLI message guesses and unproven overwrite/TOCTOU inferences no
longer drive those diagnostics. Analyze's one-character-name `OURO-NAME002` was
also removed, keeping the short-name example as a negative test.

The existing compiler-owned declaration/binder index, shared intern table and
semantic worker were retained and repaired. Reserved keyword binders, an
ill-typed index recursion, oversized Peano-shaped work constants and the clone
fingerprint's enormous integer modulus had prevented practical checking or
building. The index now has explicit decreasing structural fuel. The fingerprint
uses the compiler's bounded hash implementation and still compares the full
structural token sequence after bucketing; a hash match is not equivalence.

Result facts now distinguish a registered must-observe checked producer from an
arbitrary Either/Option and an IO action value from its execution. Required
lineage survives aliases. Checked retry success, nested lambdas and effects
invalidate inappropriate inherited failure proofs. A rendered message or a
numeric value is not assumed to be success. Same-work analysis compares the
resolved callee, all arguments including callbacks, branch, effect epoch, purity
and meaningful cost; different callbacks/callees/values and tiny known inputs do
not establish repeated work. Raw FS/process ownership uses canonical module and
registered declaration/intrinsic contracts, not basename or call spelling.

Semantic v2 protocol validation now rejects malformed/trailing frames,
noncanonical counts, lost source-byte binding, missing evidence and unknown
emitted IDs. Parse/resolution/input failures have no lexical diagnostic fallback.
Clippy simplifications/clones remain diagnostic-only where exact expression spans
and preservation certificates are absent. Public declarations are not deleted.

## Autofix publication boundary

`tools/fix/plan.ouro` distinguishes automatic, review-required and unknown/no-edit
proposals. The automatic subset is duplicate imports, do-bind syntax, redundant
separators, proven dead local values and immediate identity lets. Constructor
literal rewrites, unused-binder renaming, arm removal, import aliases, list-type
rewrites and nonrecursive-fix rewrites require review. Comments/directives block
an entire legacy compound rule cohort instead of allowing a half-applied edit.

Planning sorts deterministically, coalesces identical proposals, rejects invalid
spans/no-ops/unknown rules/conflicting overlaps and processes priority classes
separately. Exact bounded source history detects A -> B -> A cycles. Formatting
that reopens automatic fixes fails. The public path verifies candidate source
with the compiler for preview/check and each transformation class before staging
publication. The old raw rewrite helper remains for legacy goldens, not writes.
Post-fix cross-tool severity deltas and full identity certificates are still WIP.

## Actual validation

| Check | Observed result |
| --- | --- |
| Native semantic fact laws | **32 passed** |
| Native fix precision/convergence laws | **21 passed** |
| Native analyze style precision suite | **49 passed** |
| Native Clippy protocol/registry invariant suite | **passed** |
| Native public Clippy and semantic worker builds | **passed with p1** |
| Native lint build | **passed with p1** |
| Fix main source/compiler check | **passed**, not equivalent to public executable build |
| Public malformed-input/registry fail-closed suite | **passed**, 59 recorded CLI invocations |
| Strict/release expected positive, negative and unresolved-name outcomes | **6 passed** |
| Suppression-policy and canonical-source/owner policy suites | **passed** after fixture corrections |
| Semantic source fixtures | **19/33 passed across full run and focused rerun; 14 resource-blocked** |
| Python harness compilation and changed shell suite syntax | **passed** |
| Complete bootstrap | **failed at p2/frontend**, core emitter killed |
| Public fix executable/companion build | **timed out after 600 seconds** |
| Production Clippy strict | **timed out at 60 seconds**, no final report |
| Production lint deny | **timed out at 45 seconds**, not a completed clean scan |
| First production fix / second fix / whole-production fmt and analyze | **not run to completion** |
| Repository gate | **not run**, complete bootstrap prerequisite unmet |

The source-fixture failures are retained, not excluded. Eight large-import cases
failed in the full bounded run. Six initially malformed do fixtures were repaired
and retried, then reached the same memory/time boundary; they are not green. The
missing-import expectation was corrected to the actual checked-input error and
passed. Native laws exercising constructed facts do not substitute for those
blocked end-to-end checked-IO cases.

No production-zero result, measured 99% precision, completed first fix, second-fix
zero diff or release readiness is claimed. The actual production repairs in this
pass are the WIP frontend/index/fingerprint/registry and fixer integration defects
above, not a completed auto-cleanup of the whole repository. No production
suppressions, new baselines or blanket path exclusions were added for green CI.

## Remaining work

The next blocking dependency is bounded memory for semantic import closure and a
completed bootstrap/fix companion build. The semantic loader currently resolves
parsed declarations but is not a full compiler type-checking replacement. It
still reads/parses once per root/import unit, not once across an entire workspace;
workspace reuse and large-cone phase lifetime have not been proven by counters.

All existing Clippy inventory entries were audited, but the requested full lint
and analyze audit is not finished. Expensive clone/dataflow migration to analyze,
near/cross-definition clones, richer validation lineage, temporary-file workflows
and explicit policy contracts remain incomplete. Full production diagnostic
cleanup, class-by-class cross-tool validation, and actual whole-tree
`fix -> fmt -> check -> lint -> clippy -> analyze -> fix -> fmt` no-op verification
remain outstanding.

## External engineering references

The applicability distinction was cross-checked against the Rust Compiler
Development Guide, “Errors and lints” (Suggestions), and Clang Transformer Tutorial
(AST matching and source-edit boundaries). They are design references, not evidence
that Ouro's implementation or production convergence has been validated.

- https://rustc-dev-guide.rust-lang.org/diagnostics.html
- https://clang.llvm.org/docs/ClangTransformerTutorial.html

Build directories, caches, temporary harnesses and raw logs are not part of the
ZIP. Source changes, fixtures, tests, the audit and this delivery record remain.
