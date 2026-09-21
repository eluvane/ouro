<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=QUALITY&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="QUALITY banner"
  />
</p>

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

```sh
sh scripts/ouro1.sh analyze --strict
sh scripts/ouro1.sh analyze --enable-style --scope path/to/project
sh scripts/ouro1.sh lint --deny --profile project std compiler tools samples
sh scripts/ouro1.sh lint --deny --family language tools/lint.ouro
python3 scripts/strict_quality_firewall.py --profile release
python3 scripts/clippy_grade_firewall.py --profile project --scope std
python3 scripts/clippy_grade_suite.py
sh scripts/analyze_precision_suite.sh
python3 scripts/analyze_production_suite.py --out _build/analyze_production
sh scripts/lint_suite.sh
sh scripts/ouro1.sh fmt --check path/to/file.ouro
sh scripts/fmt_suite.sh
sh scripts/ouro1.sh fix --check path/to/file.ouro
sh scripts/fix_suite.sh
sh scripts/ouro_repo_gate.sh --profile pr-native --out _build/ouro_repo_gate/pr-native
sh scripts/ouro_ci_gate.sh --profile pr-native --out _build/ouro_ci/pr-native
sh scripts/ouro_ci_gate.sh --profile host-bound --out _build/ouro_ci/host-bound
```

The precision suite warms the compiler and collector before running independent
core typechecks with up to `OURO_JOBS` workers on Windows (at most 10). Per-file commands,
statuses, and logs are recorded under `_build/analyze_precision/core/`. The
pool has a 3 GiB Windows Job limit; POSIX keeps sequential checks bounded by
`rlimit`. Analyzer cores that only need string primitives import
`std/string_prims.ouro` instead of `std/runtime.ouro` so the check
cone stays off the Windows platform modules. `std/json.ouro`, quality
text, and Clippy `core.ouro` / `scan.ouro` follow the same cut: they
name findings without importing `std/string.ouro` or registry file IO.
Integration fixtures can also
import stdlib IO: both paths share the same String declarations. Analyzer runs
and golden comparisons remain sequential.

`analyze` operates over repository facts and optional deeper families. `lint`
parses individual modules and applies compiler lint rules without a source-size
cutoff. Language children stay one file per process because the C bump arena
is process-lifetime and two heavy std units already sample ~6 GiB. Style and
semantic companions stay one inventory file per child except for
consecutive measured-light `std/` files, which share one two-file
worker. When a companion
already holds two `--scope` roots, the structural worker reuses one
intern table and the content-addressed harvest cache and emits the existing
batch protocol. A third root in the same worker is rejected. Child failures, including memory exhaustion, still fail the run. A directory walk skips intentional
fixture directories and the hole and unbound samples
`samples/tutorial/04_holes.ouro` and
`tests/bad_undeclared_perform.ouro`. Parser rejections are failures, including
unsupported `mutual` syntax. `lint_suite.sh` lints the live production trees after
preparing the package sample's local registry dependencies in a writable `_build`
snapshot, in addition to positive and negative fixtures. The strict quality
firewall validates policy, diagnostics, fixtures, suppressions, and migration
debt. Semantic Clippy proofs (checked APIs, must-observe, success-after-error,
identical arms, self-compare) run as the `semantic` family of `ouro1 lint`.

`fix` is the Ouro-native autofixer for the mechanical subset of lint findings:
duplicate imports, legacy `<-` binds, `;;`, closed `Cons`/`Nil` chains, Peano
towers, unused binders, dead `let`/`let!` bindings, and unreachable match arms.
It never runs as a gate over the tree; `sh scripts/fix_suite.sh` only checks the
fixer's own fixtures. See [Tooling](tooling.md#autofixer) for the rule table.

The Ouro-native repository gates are quality gates for the repository control
plane. They validate the supported docs, project-surface, and workflow subset
without Python composition, but the Python gates remain the reference path where
parity is still incomplete.

## Native input boundary and host adapter retirement

`tools/quality/source.ouro` owns the checked source inventory used by native
lint and both analyzer runners. It does not parse source or introduce a
second semantic authority. It shares path normalization, deterministic source
selection, regular-file reads, and typed inventory failures without importing
`std/char` into the compiler lexer cone. A walk that runs out of budget, cannot
list a directory, encounters an unsafe input, or selects no source files does
not return an apparently clean partial inventory. Explicit file arguments remain
available even beneath a directory excluded from recursive discovery.
Canonical host paths deduplicate lexical aliases such as `file.ouro` and
`./file.ouro`; diagnostics retain the first sorted supplied spelling.

The base analyzer retains every repeated `--scope` value, including
`--scope=PATH`, alongside positional scopes. Its defaults remain `std`,
`compiler`, `tools/analyze`, and `samples`; lint additionally scans all of
`tools`. Fixture inclusion remains a caller policy. Failed reads do not create
empty file facts, and an empty or entirely excluded inventory is an error.
The C-host read primitive exits 73 on open, size, seek, allocation, incomplete
read or close failure. `scripts/fs_read_suite.py` observes real binaries: an
unreadable file must not produce a successful structured completion report;
an ordinary empty file remains valid. The runtime and precision suites run
these checks independently of launcher stand-ins.

Lint owns directory selection and process isolation in Ouro. The lint sources
share one in-process content-addressed import harvest cache across a batch
and retry file by file after a crash. A hit is canonical path plus exact
bytes; a path-only match is stale and is harvested again. The shell launcher retains host preparation and the optional
POSIX memory cap, not a second file inventory. Missing imported files and exhausted import traversal are errors.
A successful lint child must return zero with empty output on both streams;
findings and fatal child statuses remain blocking. `lint --deny` names that
existing all-findings-block contract explicitly. The same driver can also
dispatch internal style and semantic companions after the shared inventory;
those processes stay split from the compiler-frontend language child. It is
**not** a new public linter product, a replacement for registry/debt/SARIF
firewall launchers, or proof of whole-program semantic correctness. Import name harvesting is not imported-module typechecking.
Import syntax is preprocessed before dependency collection, preserving
`OURO-IMP-001` through `OURO-IMP-004` even when the referenced file is absent.
The resulting preprocessed source is reused for lint parsing.

The standalone structured drive rejects unknown options, unknown `--enable-*`
families, and missing `--scope` or `--api-baseline` values. Values are consumed
literally, including names beginning with `--`. It continues to use the existing
compiler frontend and analyzer family implementations.
Its `--print-families` query returns the canonical selected family list without
scanning sources. The bounded runner uses that native selection to validate each
worker's coverage and report. Missing or repeated banners, zero or duplicate
file counts, mismatched families, damaged diagnostic records, unexpected errors,
and inconsistent exit codes fail the run. The production sweep checks the full
build receipt and discards stale success reports before starting.

`scripts/host_tools.py` now provides only the explicit bootstrap collector and
its wrapper installer. Python formatting, synthetic fixture-path diagnostics,
truncated analyzer facts, and the alternative strict-quality dispatch have been
removed from that adapter. Attempts to install fmt/analyze host wrappers return
status 3 before modifying the output; direct retired commands return status 2.
The public formatter forces the existing native formatter. This retirement does
not claim output parity with the deleted synthetic analyzer behavior.

`tests/quality_input_tests.ouro` contains 22 input-boundary cases and is invoked
by the lint suite. Native lint selftests also check child-status aggregation.
The lint suite exercises deny bad/good inputs, an import-looking comment near
miss, a missing import, an empty scope, and an unknown option. Host-only adapter
and launcher protocol checks can run without building Ouro:

```sh
python3 scripts/language_speed_simplicity_suite.py --host-quality-only
```

These host checks use stand-in processes for argv/status contracts; they do not
validate native parsing, findings, precision, or performance. The native suites,
production scans, formatter/fixer goldens, and full PR profile remain required.

The precision suite also invokes freshly prepared base and drive binaries
directly for scope coverage, profile unions, repeated flags, literal option
values, Unicode paths, and findings preserved across source renaming.
Windows C-host quality builds embed a process-local UTF-8 manifest so narrow
startup arguments and filesystem calls preserve Unicode paths. These builds
require Windows 10 version 1903 or later; see [build metadata](build.md#cache-model).
The native CLI checks compare findings and locations for spaces, Cyrillic,
and CJK paths without changing the host system code page.

The quality-engine migration is incomplete. Native owners hold Clippy, strict,
and fix rules; Python adapters remain the public CLI, process budget, and
JSON/SARIF launch path. `structural_quality.py` is the public launcher and
re-exports; `structural_quality_legacy.py` still owns symbols, findings,
and reports. `lint_suite.sh` compiler-checks the split Clippy modules
(`core`, `scan`, `structural_main`, `main`) so one unit never imports both
the core/json cone and the compiler frontend. `structural_model.ouro` names
`QualityInputError` through `tools/quality/input_error.ouro` and does not
import the IO inventory. `main.ouro` typechecks on the grade cone and
invokes the structural companion, which reuses harvest facts across a
bounded batch of roots and recycles the worker afterwards.
The checks do not claim byte-identical parity with the retired regex owner.
`syntax_quality_fix.py` keeps only checked transport (native preparation plus
literal/inventory wire validation) for the remaining Python owners and suites;
its CLI wrapper is removed and suites invoke `ouro-fix` directly. LINT029 uses the fixer's shared
Cons/Nil recognizer through the exact-length, checked
`ouro.fix-literal-spans.v2` JSON protocol. Ordered, disjoint `spans` include
closed Cons chains and same-line plain-type Nil assignments; `closed_lines`
retains the separate line-local Cons query. The old Python Nil regex is
removed: comments and strings containing `:= Nil T` produce no finding.
The consumer rejects v1 rather than silently omitting the added Nil coverage.
These are syntax facts, not compiler type or import-checking results. The
Python adapter still builds, launches and validates this worker, so its host
inventory row remains `migrate` along with the other owners. The bounded
Python runner also still owns source selection, skeleton construction, and
report aggregation. `tools/analyze/bounded_text.ouro` is the checked pure
scope/batch/keep policy core; `bounded_run` is its documented public root.
`bounded_run.ouro` / `bounded_main.ouro` (process supervisor) are not present yet. Rule/diagnostic models, profile levels, suppressions,
JSON/SARIF reporting, and fixer suggestions are not unified by the shared
input boundary.
No migration debt or baseline exception is added.

Native text renderers now consume `QualityDiagnostic` from
`tools/quality/diagnostic.ouro`. The existing compiler lint, structured
`Finding`, base `ADiag`, and `FxEdit` owners adapt their results at the report
boundary. The shared record carries the stable ID, owner/rule, location,
level, message, evidence, hint, applicability and related byte edits. Existing
text layouts and IDs remain compatibility contracts. Fix proposals retain
their legacy IDs and the input positions of their owning rewrite round;
they are marked suggested, not independently validated publication plans.

Canonical levels are `allow`, `warn`, `deny`, and `forbid`. The compatibility
mapping is `info`/`warning` to nonblocking `warn`, `error` to `deny`, and
`fatal` to `forbid`; legacy display labels are preserved. The base runner
retains its hidden-info policy. Forbid/fatal and invalid-level records cannot
be hidden by a suppression flag. This transport contract does not yet replace
the Python-owned profile selection, registry validation, or JSON/SARIF reports.
`lint_suite.sh` runs the native contract and base-adapter laws; the precision
suite checks the fix adapter against an actual rewrite plan.

Strict and Clippy source selection use `tools/quality/inventory.ouro` and the
shared checked inventory. Their fixture and generated-source policies remain
distinct. Missing roots, links, files outside the repository and empty final
selections fail before scanning. Explicit fixture directories under `_build`
can be scanned with `--include-fixtures`; build directories found beneath a
strict scope remain excluded. Canonical paths deduplicate overlapping scopes.
Successful inventory stdout is one complete `ouro.quality-inputs.v1` JSON
object containing the requested scopes and selected files. Failed inventory
produces no successful report and never falls back to Python traversal.
Directory and final-file ordering use stable merges; canonical paths are
grouped without scanning all previously seen paths. The first diagnostic
spelling and original order are retained when aliases refer to one file.
The inventory streams its JSON array after collection completes, using the
existing JSON string encoder. The consumer still requires a successful worker
exit and a complete, valid report. Input laws exhaust 1,093 small sort cases;
the syntax suite checks exact, repeatable coverage of 4,096 real files under
the existing process memory limit.

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
divisor do not acquire a guessed replacement. `fmt_string` and `fx_fix` remain
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

`ouro1 analyze` is two native programs. The base runner (`ouro-analyze`)
extracts repository facts and applies the policy cores: architecture and
dependency direction, dead-code reachability, public API surface, trust-boundary
imports, suppression correctness, and the strict formatting subset. The
structured drive (`ouro-analyze-drive`) parses each source with the compiler
frontend and runs the structured cores on the shared `Ast`: effects,
capabilities, extraction leaks, match coverage, control flow, dataflow, semantic
smells, property claims, abstract interpretation, symbolic execution, taint,
contracts, complexity/bounds/minimality metrics, duplication, trust policy,
rewrite smells (`simplify`), runtime cost smells (`perf`), naming conventions
the tooling relies on (`naming`), and error-handling hygiene (`errors`).

Not every family runs by default. `sh scripts/ouro1.sh analyze --strict` runs
the base runner alone. Structured families are enabled per family
(`--enable-cfg`, `--enable-taint`, ...) or as sets: `--enable-light`,
`--enable-heavy`, `--enable-all`, `--enable-style`, and `--enable-strict`
(the promoted structured families). The nightly gate
`python3 scripts/analyze_production_suite.py` sweeps the production scopes from
`quality/analyze_production.json` and fails on any finding from
`--enable-strict` (every structured family after the production tree went
to zero findings), on an unlisted frontend rejection, or on a stale rejection
allowance; the all-family sweep is counted per code for triage.
The current production policy has no frontend rejection allowances.
`tools/analyze/README.md` lists every family, flag, and status.

Directory discovery prunes `.git`, `_build`, `_cache`, `_opam`, `_tools`, and
`node_modules` before descent. Diagnostic fixtures under `test/`, `tests/`, and
`quality/fixtures/` are excluded by default; use `--include-fixtures` when
checking them. Explicit build-directory scopes remain available for focused
checks. The root style scan therefore uses the same production inventory as
the named source scopes and keeps one native process per file.

Deadcode entry annotations accept several names, for example
`-- @entry main helper`, including `/`, `,`, and `|` separators. An `@export`
annotation remains a promise to check, not a reachability root. Branch coverage
retains every match scrutinee and constructor refinement; a repeated constructor
head alone does not prove that an arm is unreachable.

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

The `tools/repo_gate/` and `tools/ci_gate/` checks are part of the quality
surface because they protect repository-owned documentation, project metadata,
workflow files, report schemas, and gate composition. Their current displacement
profiles are:

| Profile | Scope |
| --- | --- |
| `docs` | canonical docs, Markdown inventory metrics, links, README example drift, syntax docs, manifest prefixes, sample pairs, generated API presence |
| `project` | required files, retired paths, public phrases, public wording, README shape, PR template shape, issue-form shape |
| `workflow` | required workflows, dangerous patterns, permissions sanity, report-artifact presence |
| `pr-native` | the supported Ouro-native docs/project/workflow subset |
| `host-bound` | complete machine-readable Python/sh disposition, parity, blocker, and evidence inventory |

`pr-native` is not a replacement for `python3 scripts/ci_gate.py --profile pr`.
Every remaining Python/sh path must be a concrete host/bootstrap/reference
boundary or a thin compatibility adapter. Missing inventory rows and unresolved
`migrate` rows fail the control-plane and retirement checks respectively.

## Suppressions

A source suppression must name one diagnostic, include a reason, and stay
narrowly scoped. Unknown, blanket, stale, file-wide, or reasonless suppressions
are errors in strict profiles. Trust-boundary diagnostics cannot be locally
disabled.

Clippy-grade suppressions use this form and apply only to the comment line and
the following line:

```ouro
-- ouro-clippy:disable=OURO-CLIPPY-MAINT-005 reason=protocol constant from wire format
def protocol_magic : Nat := 1000;
```

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

The [syntax reference](syntax.md) is the source of truth for accepted language
forms. Quality policy may restrict project-owned style without claiming that
every restricted form is absent from the parser. See
[Clippy-grade firewall](clippy_grade_firewall.md) for the current high-signal
rule guide.

### Semantic proof and contract boundary

The semantic Clippy worker uses `tools/clippy/semantic_proof.ouro` for typed
proof kinds and required evidence. Missing, false, unknown, duplicate or
contradictory evidence blocks publication; the declaration owner is checked
again when rendering. Node ordinals are not byte spans and do not authorize
semantic source edits. The existing v2 worker protocol remains unchanged.

`semantic_contracts.ouro` composes snapshot-local declaration summaries through
resolved, arity-exact, ordered pass-through delegations. Identity/literal returns
and harmless parameter aliases are supported. Branches, transformed arguments,
annotations requiring adaptation, recursive cycles and unknown callees remain
unknown. This is not a whole-program CFG or a wrapper-removal proof. Required
checked-result lineage survives supported helper chains; returning or ignoring
an argument is not itself an observation of its failure.

Contract limits are 16 call levels, 4096 summaries shared by a unit, and 256 local
origin steps. Positive and unavailable summaries are memoized in the immutable
API index. Tests inspect computed summaries, cache hits, expansions and
unavailable demands, not wall-clock thresholds. A fresh semantic unit invalidates
the entire cache. The import resolver receives the same graph projected to
imports, avoiding an unused flattened declaration list without replacing the
compiler's missing-module/cycle decisions.

Automatic fixes currently require `FxSyntaxProof` certificates for duplicate
imports, legacy bind spelling, or redundant separators. The transaction binds
one source snapshot, exact replacement/spans, disjoint edits and retained trivia;
the remaining syntax-repair count must decrease. The public fixer still checks
candidates through its compiler companion before atomic per-file publication.
`dead-let` and `identity-let` are review-required until binder/effect/span
preservation can be proved. This does not establish workspace-wide atomicity or
semantic equivalence for arbitrary rewrites.

Smith's incomplete text fragments exercise the native fixer's byte-level
selftests. `syntax_quality_suite.py` separately checks complete programs through
the public preview/check/write boundary, including refusal to publish incomplete
sources and nonzero check status for review-required suggestions.

Run the native laws with `python3 scripts/clippy_grade_suite.py --laws-only` and
the source mutation matrix with `--precision-only`. `scripts/fix_suite.sh` also
runs `tests/fix_proofs.ouro`. Host launchers do not decide semantic outcomes.

The transitional C-host native-tool builder attaches the existing nested-arena
lifetime boundary to `cm_load_file`. The harvest keeps the selected file's
typed declarations and imported signatures; imported function bodies stay in
the nested arena and are released with lexer/parser temporaries. Imported
type-alias bodies are not retained.
Caller-owned intern identities are shared across that seam so a large import
cone does not recopy the growing table on every file.
The hook contains no parser, resolver, registry, fallback, or analysis logic;
all such decisions remain in Ouro. Missing required exports fail the build.
Do not remove that lifetime seam merely because small import-free fixtures pass.
Root parsing, contract lookup and validation, and API-index construction also use
the existing pure arena seam. Their temporary graphs are released before the
next phase; parsed declarations, typed errors, and API facts survive unchanged.
Session stress coverage repeats a production import cone under the same
3072 MiB limit and compares complete source/proof frames across epochs.

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
