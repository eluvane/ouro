# Semantic proof and bounded contract pass

Date: 2026-09-18. Input: the uploaded `ouro-dev-main-updated.zip`.

**Status: useful, tested WIP; not production acceptance.** No remote, branch or PR
was used. Earlier reports in this directory describe earlier passes, not results
of this one. `semantic_proof_validation.json` records this pass's commands,
per-case results, source hashes, resource limits and unsuccessful attempts.

## Implemented

`tools/clippy/semantic_proof.ouro` introduces eleven closed proof kinds with
owner/subject/region identities, required evidence and an optional exact byte
span. Missing, unknown, false, duplicate or contradictory evidence blocks
publication; the owner is checked again at rendering. The current semantic
traversal has node ordinals rather than edit-authorizing byte spans. It does not
claim a theorem-prover implementation or expose arbitrary semantic edits.

`semantic_contract_model.ouro` and `semantic_contracts.ouro` add snapshot-local
function summaries with explicit unknown/status/effect/result/return-origin/
argument-observation/cost/mutation fields. Summary composition follows resolved
identities through one exact ordered delegation, identity returns, literals and
harmless parameter aliases. Branches, argument transformations, reordering,
duplication, unknown callees and unsupported annotations do not get a stronger
contract. Pure/checked-result obligations can cross two supported helpers.
Returning or ignoring an argument is not evidence that its failure was handled.
This does **not** prove that the helper is removable.

Summary computation has a shared 4096-summary budget, 16-call depth bound,
256-step local origin bound, active-cycle detection, positive/negative
memoization and computed/cache-hit/expansion/unavailable counters. Exhaustion
cannot manufacture a program diagnostic. Imported summaries are demanded only
along relevant resolved delegations; roots share their one API index.

The registry now owns the summary seed facts. Missing/stale declaration-owner
bindings, duplicate contracts and contradictory purity/checked/fallback metadata
fail closed. Two stale API rows were removed: `validation_render_lines` from
`std/validation.ouro`, and `insertion_sort` from `std/listx.ouro`.

Logic, raw API, checked-result loss, failure-to-success, repeated-work/traversal
and duplicate findings now carry typed semantic evidence. Equality/performance
proofs reject unknown value identities. Repeated-work keys include all argument
identities, callback arguments and the existing branch/effect epoch; keys are
materialized once, not repeatedly inside the sort comparator. Exact delegates
can inherit known work/purity facts. Duplicate candidates still require complete
structural/alpha streams after hashing, plus known safe call contracts. Duplicate
findings remain diagnostic-only.

`tools/fix/proof.ouro` adds grammar-derived certificates for `dup-import`,
`do-bind` and `double-semi`. A transaction binds the exact source snapshot,
rule-specific spans/replacement, disjoint edits and preserved trivia; the syntax
repair count must decrease. A rule ID plus replacement text is not sufficient.
`dead-let` and `identity-let` were changed from automatic to review-required.
Other semantic proposal families were already review-required. Existing
compiler-companion checks and per-file atomic publication remain mandatory.
Workspace-wide atomicity and semantic graph equivalence are **not** implemented.

## Memory work

The semantic loader now projects import graphs to import declarations when it
needs graph validation, instead of materializing and immediately discarding a
flattened closure of all declarations. Compiler missing-import and cycle errors
are preserved. Binder lookup no longer copies a scope merely to search it again.

A larger blocker was measured before semantic rule execution: repeated parser
calls retained phase temporaries while traversing ordinary library imports. The
transitional native-tool builder now connects unchanged Ouro `cm_parse` to the
existing nested-arena lifetime seam. The small `runtime/frontend_link.c` wrapper
only preserves the complete result graph and releases parse temporaries. Parsing,
resolution, identities and semantic decisions remain in Ouro; no C analysis,
semantic fallback, path exception, import exclusion or raised limit was added.

An instrumented normalization probe that failed with the old worker passed at a
1 GiB process limit after the seam. A checked-read chain through two helpers
passed at the original 2 GiB source-suite limit. Approximately 44.1 MB retained
runtime heap was observed after that probe; this is **not** peak process RSS.
Temporary allocation traces and generated C are not included in the artifact.
Six native lifetime laws check retained AST/intern identities and typed errors.

## Validation and limitations

122 native checks passed with the provisional P1 compiler: proof 9, contract 27,
resource/registry 11, semantic precision 32, fix precision 21, fix proof 16,
parser lifetime 6. These include old regression checks as well as new ones.
The full 48-case source matrix passed at its unchanged 2 GiB per-process limit.
It extends the original 33 cases with 15 helper/identity/branch mutations.
Four additional public-CLI checks passed: strict and release report the proven
two-helper repeated-work case, but report nothing for reordered forwarding.
The native rule-registry validator also passed. Per-case results are recorded
in `semantic_proof_validation.json`.
The existing host-hook regression was extended and passed, including required
exports, malformed getters and no partially published generated-C rewrite.

The initial full bootstrap reached P1, P2 root checks and early acceptance, then
hit the 900-second validation limit. Independent frontend re-emission completed
and produced identical frontend C. A manual ABI continuation was not accepted;
stack sensitivity and aggregate memory pressure remain unresolved. This initial
bootstrap predates the final parser lifetime seam. There is no final release
seal, successful final ABI acceptance or full repository-gate result.

Production strict/release runs were attempted over `std`, `compiler`, `tools`
and `runtime`. Both strict/release Clippy runs, including a repeat with the scoped parser
companion, exceeded their 90-second outer validation limit. Partial reports are
not zero diagnostics. Lint exceeded its 75-second outer limit;
the provisional analyze host exhausted its imposed memory budget. The full
compiler-check companion for fix/fmt was not built. Provisional root-only tools
were linked from actual P1-generated C only to exercise failure behavior; no
companion or seal was forged.

Both fix and fmt were invoked twice with all 450 production `.ouro` paths in
an isolated tree. Both fix rounds refused the missing compiler-check companion
and then reached the imposed 1300 MiB process memory limit; both fmt rounds also
exhausted that limit. None completed the requested file set. All four commands
returned 1 and changed zero files. Their exact results are in the JSON report.
Missing compiler verification is a failure, not a successful no-op. Failed staging was not
promoted. Accepted production diagnostic repairs: **0**. Production `fix + fmt`
convergence, strict/release zero-actionable output and full compiler/repository
smokes are **not established**.

## Rule changes and residual WIP

No active Clippy IDs were deleted, transferred between tools, or severity-
downgraded in this pass. The previous archive had already reduced its inventory
to 17 active rules; those earlier deletions are not counted here. See
`semantic_proof_rule_audit.json` for current ownership, proof requirements,
complexity class and applicability. Newly narrowed cases are unknown-value
comparisons/repeated work and unknown/effectful duplicate callees. The two
fix-applicability downgrades and two stale registry-row removals are listed above.

Residual semantic textual heuristics are **not zero**. Analyze still has path
layer classification and name/annotation-based analyses. Fix retains textual
review-only proposals; its three automatic syntax classes require grammar
certificates. No claim is made that the two existing structural Clippy rules
have been migrated to the new semantic proof object.

Remaining work includes rich Result mapping/recovery/log/render/exit-status
contracts and validation-replacement lineage; annotation/public/policy boundary
proofs for wrapper/dead-abstraction removal; exact semantic edit spans and
before/after compiler-fact preservation; workspace transactions and complete
cross-tool monotonicity/dominance/interaction handling; richer collection/loop/
recursion reasoning; and sealed bootstrap/production convergence. Unknown facts
must not be replaced with textual guessing to finish these tasks.

## Reproduction

Use the repository's normal bootstrap/sealing procedure first. The normal native
suites include the new sources:

```sh
python3 scripts/clippy_grade_suite.py --laws-only
python3 scripts/clippy_grade_suite.py --precision-only
sh scripts/fix_suite.sh
python3 scripts/build_cache_config_suite.py
```

The focused source suite also accepts `--worker PATH` for an explicitly
already-built worker. That override is not a compiler seal. The JSON report
records provisional P1 evidence separately from release acceptance. Source
fixture timeouts are bounded; native resource laws assert work/caching bounds,
not machine-dependent elapsed times.

Design references reviewed: Clang's *Data flow analysis: an informal
introduction* (unknown/top and bounded analysis), and the Rust Compiler
Development Guide's *Errors and lints* (diagnostic applicability). Their URLs
are preserved in the JSON report; they are background, not test evidence.
