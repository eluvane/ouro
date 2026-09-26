# Quality tools

Ouro has two complementary quality layers:

1. `ouro1 lint` — the only user-facing Ouro source linter. Language,
   proven style, and compiler-proved semantic families are internal to
   that driver;
2. repository analyzer and policy gates (`analyze`, the Python strict
   registry/debt firewall, and `--structural`). Those are not a second
   source linter.

These tools improve source quality and repository architecture. They do not
participate in kernel acceptance.

## Commands

Use `ouro1 lint` for Ouro source, `ouro1 analyze` for repository and
structured analysis, and the strict firewall for repository policy:

```sh
sh scripts/ouro1.sh lint --deny --profile project std compiler tools samples
python3 scripts/strict_quality_firewall.py --profile release
```

[Tooling](tooling.md#analyzer-and-linter) owns analyzer/lint CLI flags and behavior;
[Analyzer internals](../tools/analyze/README.md) own the family inventory;
[Clippy-grade rules](clippy_grade_firewall.md) own semantic rule evidence.
[CI](ci.md#local-profiles) owns focused suites, profiles, and gate commands.
Formatter and fixer usage is in [Tooling](tooling.md#formatter).

## Native input boundary and host adapter retirement

`tools/quality/source.ouro` provides checked source selection and reads for
native lint and analyzer runners. Canonical paths deduplicate lexical aliases,
while diagnostics retain the first supplied spelling. An unreadable, unsafe,
truncated, or empty inventory is an error; explicit source files remain
selectable beneath directories skipped by recursive discovery. A cache hit
requires canonical path and exact bytes, and never substitutes for checking.

Lint isolates language, style, and semantic companions in bounded processes.
A child failure, malformed result, or memory exhaustion fails the run. The
native shared diagnostic record carries code, owner, location, level, evidence,
hint, and edit applicability; text compatibility remains stable while Python
still owns parts of profile selection and JSON/SARIF reporting. The host
adapter retains bootstrap and reporting responsibilities until parity evidence
supports retirement. See [Analyzer internals](../tools/analyze/README.md#bounded-execution)
and [Clippy semantic boundary](clippy_grade_firewall.md#semantic-boundary)
for their distinct workers and resource limits.

## Precision and safe rewrites

Abstract-value facts are lexical: a lambda, telescope, recursive name, pattern,
or effect-clause binder masks an outer fact for the same name. An annotation or
`let` initializer still sees the preceding scope; sibling arms do not inherit
each other's bindings. Unknown bindings also mask constructor-name defaults.
A division finding requires the actual second argument of an unshadowed
configured division-like callee. Later arguments and locally shadowed names are
not evidence of division by zero.

The abstract interpreter joins match-arm results only when every arm agrees on
the zero-like or positive-like value. Mixed, unknown, and empty joins remain
unknown. This is intraprocedural value propagation, not whole-program range or
resource analysis. Lint separately tracks telescope shadowing when accounting
for unused binders and recursion, and follows type ascriptions without reporting
an over-applied constructor more than once per maximal application spine.

Formatter normalization distinguishes an arm bar from the `|>` token, treats
apostrophes as identifier characters, and preserves tabs inside quoted strings.
The production formatter uses `fmt_checked` in `tools/fmt_pipeline.ouro`: a
changed candidate must preserve the positional fixer's token kinds and raw token
text, and a second normalization must produce identical bytes. A candidate that
would change literal contents, including a raw CR or affected multiline string,
is refused with a nonzero status before output or writing. Refusal is not a claim
that the source itself is invalid. Comments and layout are not language tokens.

The production fixer uses `fx_prepare` in `tools/fix/pipeline.ouro`. It requires
a complete imported constructor inventory, a converged rewrite plan, checked
formatting, and no reopened rewrite after formatting. Missing imports and
exhausted import or rewrite budgets are errors, not partial success. A
formatting-only change is reported as such. Existing `FxEdit` rule intents drive
both rewriting and convergence checks; ambiguous diagnostics such as a zero
divisor do not acquire a guessed replacement. Root import discovery uses the same
syntax-normalized snapshot as compiler preflight, so identical duplicate aliases
can be repaired; imported files are read unchanged. `fmt_string` and `fx_fix` remain
raw candidate APIs for existing goldens, not permission for a CLI to write.

Formatter and fixer writes use `tools/quality/source_write.ouro`: reserve private stage and
recovery files, verify candidate bytes, recheck the original, perform a
metadata-preserving same-volume replacement, verify both installed and recovery
bytes, then clean up. A partial failure retains or restores recovery according
to the observed file state; an unexpected concurrent source is preserved.
Read-only and hard-linked sources and unsupported metadata modes are refused.
The exact metadata and concurrency limits are in the
[runtime contract](effects_design.md#runtime-surface). Artifact publication
retains its separate contract.

`fix --write` and `fmt --write` run `ouro-fix-check` before replacement. The
worker accepts candidate bytes on stdin or `SOURCE file PATH`. POSIX C-host
bounded capture returns OS status 120; the frontend then uses file mode and
`process_run_spec_checked` without changing the C runtime. The POSIX file-mode
path does not apply the bounded 120s/memory caps; a hanging worker is still
refused when the child exits, but timeout/memory events exist only on the
bounded-capture host. Formatter writes skip the gate only when the original
is already a compiler rejection; a compiling file cannot be replaced by a
rejected candidate. Token and fixpoint
checks still do not establish compiler acceptance by themselves. The syntax suite checks public fix/write/check/repeat behavior;
`scripts/fs_replace_suite.py` independently observes source bytes, metadata,
identity/refusal boundaries and Ouro recovery states. A simulated partial state
tests recovery policy, not the operating system's production of that failure.
The mandatory frontend-host suite builds the boundary driver as a direct PE,
checks its OS imports and source hashes, and runs the same contracts with Unicode
paths and an empty child PATH. Missing cases or a changed image fail the gate.

The native roots under `tests/analyze/precision/` cover bad, good, and
false-positive cases with exact issue identities, witnesses or line numbers,
expected bytes, and repeated-run checks. The precision gate typechecks, builds,
and executes all nine roots, retaining `precision_build_*` and
`precision_run_*` logs under `_build/analyze_precision/`. Empty case sets and
missing binaries or reports fail. Formatter and fixer selftests also exercise
actual refused writes and verify that the original file bytes survive. Existing
frontend/pipeline goldens and production sweeps remain separate requirements;
a core assertion is not a substitute for those gates or kernel checking.

Architecture cycle queries share an adjacency index and prune branches proven
unreachable. Regression cases retain the original edge-order witnesses and
depth-budget behavior, including shared acyclic subgraphs and duplicate edges.

`prim_process_capture_bounded` belongs to the same process capability,
unhandled-effect, and taint source/sink inventories as ordinary capture.
The host precision root asserts its exact CAP002, EFF003, and TAINT001
witnesses, including binary-input flow and owner-path lookalikes. Checked
bounded wrappers stay free of raw-primitive findings.

## Repository structural gate

```sh
python3 scripts/strict_quality_firewall.py --structural
python3 scripts/structural_quality_suite.py
```

The structural pass extends the existing strict firewall and runs in the PR,
nightly, manual, and stage-loop profiles. It has no existing-debt baseline and
accepts no scope exclusions. Python ASTs and lexical declaration/operation
regions for Ouro, shell, C, and OCaml feed one indexed ownership/reference model.
The native analyzer remains the owner of typed Ouro AST checks. The host pass
adds cross-language evidence without a second compiler or a backend fallback.

| Evidence | Gate behavior |
| --- | --- |
| Exact implementations after conservative binder/helper-owner normalization | Blocking `STRUCT_DUPLICATE_IMPLEMENTATION` clone groups |
| Internal argument-forwarding wrappers and chains | Blocking `STRUCT_PASS_THROUGH_WRAPPER`, `STRUCT_WRAPPER_CHAIN`, `STRUCT_SCRIPT_WRAPPER_CHAIN` |
| Internal declarations unreachable from public, protocol, top-level, or explicit repository roots | Blocking `STRUCT_UNUSED_DEF`, `STRUCT_UNUSED_TYPE`, `STRUCT_UNUSED_MODE`, `STRUCT_UNUSED_CONFIG` |
| Literal unreachable branches and recognized failure-to-legacy/backend switches | Blocking `STRUCT_UNREACHABLE_BRANCH`, `STRUCT_LEGACY_FALLBACK`, `STRUCT_SILENT_FALLBACK`, `STRUCT_PARALLEL_BACKEND_FALLBACK` |
| Similar operation shapes, responsibility overlap, compatibility names, config chains, orphan modules, public aliases, runtime exports | Informational candidates requiring contract review |

Clone evidence also names applicable path, filesystem walk, parser, graph,
process, configuration, report, diagnostic, stdlib, and host-policy rule families.
Candidates combine names, calls, fields, constants, control shape, and module
context; they do not assert cross-language equivalence. Types, global owners,
operators, and literals stay rigid for blocking clones. Ambiguous lexical binder
scopes stay unnormalized. Public APIs and explicit docs/config/dispatch references
are conservative roots. This may miss dead code; it must not invent proof.
Per-file native deadcode runs omit callers in other modules. Use this repository
graph to assess those candidates before deleting declarations.

The fallback family also blocks a failed directory inventory being replaced by
a different enumeration API, such as `scandir` followed by `glob` in an exception
handler. A failed scan must not become an apparently successful empty inventory.

The Git inventory includes tracked and nonignored new files. Missing/unsafe
inputs, extraction errors, malformed classifications, and inconsistent reports
fail the gate. Hash-verified generated artifacts and manifest-owned fixture inputs
have explicit boundary records. Fixture scopes cannot escape their harnesses.
Generated hashes do not replace the regeneration/stage-loop drift gate.
Clippy precision inputs come from `tests/clippy_semantic/cases.json`; only its
listed files receive fixture boundaries. Unlisted sources and law harnesses
remain in the ownership graph. Missing or escaping fixture paths fail the gate.

Native symbol names written as ASCII `List Nat` literals count as explicit
references, just like quoted names. Comments and malformed byte lists do not
create roots. The structural lexer corpus declares its negative inputs in
`quality/fixtures/structural_lex/manifest.json`; an unexpected successful parse,
missing input, or path outside that corpus fails validation.

The deterministic report is `_build/quality/structural-quality.json`, kind
`ouro.structural-quality.v1`. It records file/language coverage, symbols, clone
groups, actionable findings, intentional cases, and candidates. Every finding has
identity, location, related symbols, confidence, evidence, rationale, and a
consolidation direction. Console output shows blocking findings and totals;
candidates remain in JSON. Elapsed timestamps are excluded. Hash buckets,
operation posting lists, and convergent helper interning avoid a repository
all-pairs comparison.

Inspect types, callers, failure behavior, and trust boundaries before editing.
Select an existing owner, delete dead private tails, collapse an unnecessary
wrapper, or improve a false-positive rule. Independent oracles and confinement
checks at separate boundaries must retain their independence.

An intentional clone uses a declaration-adjacent comment naming its exact rule
and every other member (`path#symbol`):

```text
-- ouro-structural: {"rule":"STRUCT_DUPLICATE_IMPLEMENTATION","category":"independent-oracle","related":["compiler/source_text.ouro#source_bytes_equal"],"reason":"Compute expected byte equality independently for canonical-source differential checks."}
```

Use `--` in Ouro, `#` in shell, or a single-line C/OCaml block comment. Categories:
`independent-oracle`, `trust-boundary`, `bootstrap-seed`, `public-compatibility`,
`platform-adapter`, `generated-artifact`, `performance-specialization`.
Explain the concrete boundary. Unknown categories, wildcards, detached/stale
classifications, and changed clone membership fail. Broad ignores, filename
allowlists, and existing-debt counts are unsupported.

Fixtures cover renamed implementations/helpers, nominal types, differing
globals/operators/literals, private cycles and dynamic roots, meaningful wrappers,
legacy/platform paths, config aliases, generated drift, malformed reports, and
exact classifications. Historical fixtures model a second parser ABI, copied
native launchers, and three compatibility option handlers.

Lexical adapters are not full parsers or theorem provers. Arbitrary equivalence,
reflection, C macro expansion, OCaml module privacy, and every possible fallback
are not inferred. `complete` means the declared input inventory was processed,
not that every possible defect was proved absent. Candidates stay informational
until their precision and consolidation contract justify promotion.

`tools/structural/lex.ouro` has a native stdin JSON driver
(`tools/structural/lex_driver.ouro`) compared with
`structural_quality_legacy.lex` by `python3 scripts/structural_lex_parity.py`
on `quality/fixtures/structural_lex/`. Python still owns symbols, findings,
and reports. The driver does not replace `structural_quality.py`.
Token positions use Unicode character indices, matching the Python oracle.
Native region scanners keep byte offsets internally and convert the ordered
token stream once, including here-document bodies.

## Analyzer families

The base analyzer checks repository graph, public API, trust imports,
suppressions, and a strict format subset. Optional structured families parse
each source through the compiler frontend. The canonical
[family/flag inventory](../tools/analyze/README.md#analyzer-families) and
[bounded execution contract](../tools/analyze/README.md#bounded-execution)
live with the analyzer. `--enable-strict` selects promoted structured families;
ordinary `analyze --strict` remains the base runner. The
[nightly sweep](ci.md#local-profiles) checks the promoted set.

## Code-review profile

`--enable-style` selects the existing `dataflow`, `metrics`, `simplify`, `perf`,
and `naming` families. It is a union, not another linter: individual family
flags and repeated profile flags still run each selected family once, in the
canonical report order. Existing diagnostic IDs, hints, suppressions, and strict
promotion remain unchanged. The wrapper preserves quoted scopes and option
values when expanding the profile, and the standalone native drive accepts the
same alias.

The profile includes unused parameters, dead stores and aliases, simple Bool
matches, double negation, identical arms, forwarding lambdas, constructor
reconstruction, existing runtime-cost smells, and naming conventions. Metrics
retain their annotation-driven contracts; this does not introduce blanket
function-length or parameter-count limits for unannotated definitions.

An unused `unused : Nat` parameter receives `OURO-DF001`; `_unused : Nat` marks
an intentional discard. Reading `_value` receives `OURO-NAME001`. Recursive
parameter facts are counted per telescope position: a parameter is not in scope
in its own annotation, later annotations can read it, and a later rebinding
masks it in the return type and body. Naming and dataflow share these facts
rather than independently counting all occurrences of a spelling.

Simplification tracks local helper shadowing through parameters, lambdas,
lets, dependent binders, recursive names, match arms, and handler clauses.
Sibling arms retain their outer scope. A locally bound `notb` or `andb` is not
assumed to be the standard helper. This is lexical precision over shared AST
facts, not a proof of whole-program helper identity or arbitrary equivalence.

Recommendations must also preserve evaluation. Identical-arm elimination and
absorbing Bool constants do not recommend dropping an unknown call, `perform`,
or workflow. Identity matches and neutral operands retain their argument once.
Constructor sections and recursion-sensitive eta forms keep their existing
exemptions. A Bool identity uses its specific rule rather than a second generic
reconstruction diagnostic.

The existing fixer owns the safe mechanical subset. In particular, an unused
parameter can become `_unused`; the style profile does not make every
`OURO-SIMP*` hint an automatic rewrite. Public signatures, dependent types,
effects, and name collisions must not be changed by a guessed fix. Review the
remaining suggestions after running the normal tools:

```sh
sh scripts/ouro1.sh fix --write path/to/file.ouro
sh scripts/ouro1.sh fmt --write path/to/file.ouro
sh scripts/ouro1.sh analyze --enable-style --scope path/to/file.ouro
```

`tests/analyze/precision/style.ouro` adds exact-list binder, scope, evaluation,
and eta regressions. The precision launcher also checks profile/explicit-family
parity, duplicate flags, bad/good fixtures, and the native unused-binder
`fix -> fmt -> analyze` round trip with read-only convergence checks. Separate
stand-in-process tests exercise the actual shell launcher's argument and verdict
handling; they are not substitutes for native analyzer execution. Structured
runs cannot claim success on a diagnostic, rejected unit, missing report, or
inconsistent clean-count banner merely because a process returned zero.

## Diagnostic registry

`quality/diagnostics.json` is the canonical policy registry for repository
quality diagnostics. Each entry records a stable `OURO-*` code, its analyzer,
replacement guidance, fixture coverage, and level by profile. A `status` of
`retired` means the rule is not active: the emitter is gone. Retirement is
not an allow/warn hide and is recorded in `quality/lint_rule_audit.json`.

The Clippy-grade firewall keeps its rule inventory in
`quality/clippy_grade_rules.json` because it uses family-scoped rule ids such as
`OURO-CLIPPY-CHECKED-001`. Those ids are stable, documented, validated by
`scripts/clippy_grade_firewall.py --validate-rules`, and exercised by
`quality/fixtures/clippy_grade/manifest.json`.

Diagnostics should be:

- specific enough to identify a real problem;
- stable enough for fixtures and editor tooling;
- paired with a practical replacement when they block code;
- documented before they become release-blocking.

The complete code list belongs in the registry and generated reports, not in a
hand-maintained Markdown table.

## Levels and profiles

Levels are:

| Level | Meaning |
| --- | --- |
| `allow` | Disabled in the selected profile |
| `warn` | Reported without blocking the gate |
| `deny` | Blocks unless covered by explicit migration debt |
| `forbid` | Blocks and cannot be weakened by a source suppression |

The Clippy-grade firewall retains `allow`, `info`, `warn`, `deny`, and `fatal`.
`info` is nonblocking. In strict and release profiles, a narrow rule-id
suppression may cover `deny`; `fatal` cannot be locally suppressed and retains
the non-weakenable policy of `forbid`.
`--warn-only` exists only for migration discovery and CI reporting; it does not
change the rule inventory.

Profiles are:

| Profile | Intended use |
| --- | --- |
| `baseline` | External experiments with conservative defaults |
| `project` | Normal repository development |
| `strict` | New project-owned Ouro code |
| `compiler` | Compiler and trust-sensitive areas |
| `release` | Fail-closed release validation |

A rule without a clean replacement should remain advisory until its precision
and migration path are demonstrated.

## Repository-control-plane migration

[Native repository gates](native_repo_gates.md) own the Ouro policy and
migration inventory; [CI](ci.md#ouro-native-control-plane-displacement)
owns profile composition, parity evidence, and host-bound reports.
`pr-native` covers the supported docs/project/workflow subset and does not
replace the full Python PR profile.

## Suppressions

A source suppression must name one diagnostic, include a reason, and stay
narrowly scoped. Unknown, blanket, stale, file-wide, or reasonless suppressions
are errors in strict profiles. Trust-boundary diagnostics cannot be locally
disabled.

Clippy-grade suppressions use this form and apply only to the comment line and
the following line:

```ouro
-- ouro-clippy:disable=OURO-CLIPPY-REDUNDANT-001 reason=explicit local identity example
def retain (x : Nat) : Nat := let y := x in y;
```

The identifier must name an active rule in `quality/clippy_grade_rules.json`;
a retired identifier is reported as `OURO-CLIPPY-SUPPRESS-003`.

Suppressions are exceptions for a specific finding, not an alternative policy
system.

Architecture layer exceptions use a separate edge marker immediately before
the reviewed import. The marker applies to that import only:

```ouro
-- ouro-analyze:allow-layer-import reason=split-module-bridge
import "implementation.ouro";
```

Trust-boundary crossings use `ouro-analyze:allow-trust-import` under the same
next-import rule and require explicit trust review. Neither marker changes
kernel acceptance or makes analyzer output part of the logical TCB.

## Migration debt

Known legacy findings are recorded in
`quality/strict_debt_manifest.json`, not hidden by broad suppressions. A debt
entry identifies the code, path scope, permitted count, reason, replacement,
and tracking design record.

The gate fails when debt grows. When debt shrinks, the manifest is updated so
the improvement remains visible. New code should not reopen a retired
compatibility form merely because older source once used it.

The generated migration report is written under `_build/quality/`.

The Clippy-grade rules currently use project `warn` levels and strict/release
`deny` levels for most remaining semantic proofs. `ouro1 lint --deny` still
blocks every emitted finding, including project-warn rows. `tools/lint.ouro
--selftest` owns deterministic native lint fixture discovery, verdicts, and
artifacts. The compatibility lint suite compiler-checks the split Clippy
modules, then runs the Clippy fixture suite. Production discovery is
`ouro1 lint --deny` on the live trees; `--warn-only` is not the green path.
The split modules, `structural_main.ouro`, and `main.ouro` are required
`CHECK_OK` gates.

## Fixtures and reports

`quality/fixtures/manifest.json` connects diagnostics to accepted and rejected
fixtures. Good fixtures must remain clean; bad fixtures must produce the
expected stable code.

`quality/fixtures/clippy_grade/manifest.json` embeds the Clippy-grade
firewall fixtures. The suite materializes them under `_build` and covers bad and
good examples for redundant code, logic, checked APIs, imports, naming, error
handling, CLI workflows, and maintainability.

The strict firewall can write:

- a JSON report;
- SARIF for CI consumers;
- a Markdown migration report.

The Clippy-grade firewall writes JSON and SARIF. These artifacts explain a gate
result. They do not prove language soundness or replace compiler and kernel
tests.

Ouro-native repository reports keep a stable `repo-gate.json` shape. The
Ouro-native CI runner writes `ci-summary.json`, per-gate JSON files, and
`host-bound.json` for the host dependency inventory.

## Project style

The strict project surface generally prefers:

- records and projections over repeated manual field accessors;
- typed list literals over literal-shaped constructor chains;
- `do let!` over retired bind notation;
- local opens and explicit aliases over namespace leakage;
- small helpers and modules over large mixed-responsibility files;
- structured diagnostics over-ad-hoc panic text;
- documented public APIs over accidental exports;
- explicit discards over unused names;
- checked filesystem/process/config/CLI/CSV APIs over raw primitives in
  user-facing programs;
- usage-aware CLI mains and nonzero failure exits;
- named constants and typed error constructors over repeated strings and magic
  numbers.

Those preferences are not themselves deny proofs. Lexical accessor-name,
nested-application depth, wrapper, module/function size, public-docs, panic,
and TODO/FIXME greps are retired (`OURO-LINT022`, `OURO-LINT028`,
`OURO-LINT031`–`OURO-LINT036`). Style unused/shadow greps (`OURO-LINT038`,
`OURO-LINT039`) are deleted as duplicates of language lint. Proven style
remains duplicate imports, `;;`, `<-`/`let!`, typed Cons/Nil spans, and
alias/open. Language lint owns holes, unbound names, unused binders, and
shadowing.

Language lint parses qualified import references after compiler preprocessing
and reports their original dotted spelling. It compares qualified names and
constructors against names harvested from the alias's direct imported file;
unqualified names still use the flattened import inventory. This analysis
does not authorize source acceptance; the compiler module resolver and
declaration checker decide identity and validity.

The [syntax reference](syntax.md) is the source of truth for accepted language
forms. Quality policy may restrict project-owned style without claiming that
every restricted form is absent from the parser. See
[Clippy-grade firewall](clippy_grade_firewall.md) for the current high-signal
rule guide.

### Semantic proof and contract boundary

Semantic lint publishes a finding only with the required typed proof evidence.
Unknown, false, missing, duplicate, or contradictory evidence blocks
publication. [Clippy-grade rules](clippy_grade_firewall.md#semantic-boundary)
own contract inference, proof frames, scope, and resource limits;
[Tooling](tooling.md#autofixer) and [safe rewrites](#precision-and-safe-rewrites)
own edit applicability and source publication.
