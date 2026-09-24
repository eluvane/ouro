# Clippy-grade deny firewall

Semantic proofs in this page are the `semantic` family of `ouro1 lint`.
They use the compiler lexer/parser, canonical import resolver and a
read-only declaration index. Language and proven style stay in the other
lint families. `analyze` retains repository-graph and heavy structured
cores. The Python command is an adapter for that family plus fixture and
query flags. The separation is not yet complete: expensive clone analysis
still lives in this family.

## Run it

The user-facing command is `ouro1 lint`. The Python adapter adds rule,
fixture, and file-inventory queries and JSON/SARIF reports:

```sh
sh scripts/ouro1.sh lint --deny --family semantic --profile project std
python3 scripts/clippy_grade_firewall.py --profile strict --scope std
python3 scripts/clippy_grade_firewall.py --list-rules
```

`strict` and `release` reject `--warn-only` and fail on deny/fatal findings.
`project --warn-only` can report ordinary debt but cannot hide a fatal error,
malformed registry, missing rule, or incomplete inventory. See
[CI](ci.md#local-profiles) for focused validation commands.

## Semantic boundary

`semantic_unit.ouro` reads imported sources for each requested root and shares
an intern table inside a worker. Its existing harvest cache uses canonical
relative path, source byte length and content hash; a hit avoids parsing and
harvesting that dependency again. Imported harvests retain signatures and compact
source origins bound to module/declaration identity, never function bodies or
completed contracts. Each root resolves those origins against its current import
graph and recomputes summaries within the existing inference limits. It builds
`compiler/semantic_scope.ouro` identities. A multi-file worker invocation
reuses the intern table and cache across bounded allocation epochs and
emits `ouro.clippy-semantic.v3`. Hits never skip proofs. `semantic_registry.ouro` associates
contracts with canonical module/declaration or intrinsic ABI identity. A local
same-spelled function does not inherit a standard-library contract. Unknown
calls are effect barriers, not assumed pure. This is not a full compiler type
check of the analyzed program and does not replace `ouro check`.

The worker produces `ouro.clippy-semantic.v3`: exact byte-framed root source,
complete proof count, then rule, owner, node ordinal, optional byte range, and
explanation. The range is two lines, `-` when absent and canonical byte offsets
otherwise. It is absent when import-alias or record preprocessing rewrote the
file, because those token indexes no longer address the snapshot. When present,
the reported line and column are the expression's first byte, so a suppression
on the previous line applies to that expression. The reporting cone rejects
incomplete, noncanonical, or out-of-range frames and unknown emitted IDs. A
range is a position, not an automatic edit. Semantic Clippy findings remain
manual suggestions.

Each definition is traversed once into shared call/value/binder/flow facts.
Repeated-work rules compare all argument identities, resolved callee, branch,
effect epoch, registered purity and relevant cost. Higher-order arguments are
part of the key. Constant inputs do not establish expensive repeated work.
Result obligations come only from explicitly registered checked APIs and only
when an IO action is executed. Each execution of an opaque action has a fresh
value identity and effect boundary, including repeated executions of an alias.
Proven `io_pure` preserves its exact payload without executing nested actions.
Aliases of an executed result preserve producer identity; a match,
return or escape can discharge observation. Generic Either/Maybe values do not
acquire a must-observe contract from their type or spelling alone.

Failure-to-success diagnostics require a checked failure arm and no intervening
effect/recovery boundary. Literal error codes and rendering are not success
constructors. Explicit registered default policies and successful checked retry
branches invalidate the unrecovered-failure proof. This is conservative local
reasoning, not path-complete validation or interprocedural error tracking.

Clone detection uses bounded compiler hashing, sorted buckets, then full
structural token comparison. Hash equality alone never proves a clone. Only
local binders may be alpha-renamed; global identities, literals and constructors
remain significant. Small, unknown-purity, effectful and registered-boundary
implementations are excluded. There is no general near-clone or wrapper-removal
proof, and no automatic public API deletion.

## Active rules

`quality/clippy_grade_rules.json` is authoritative. Retired rules and reasons
are recorded in `quality/clippy_rule_audit.json`; retirement is not a severity
downgrade. Name length, `_checked` spelling, function size, parameter counts,
stdout text, basename/layer guesses and apparent overwrite intent no longer
produce Clippy diagnostics. Existing lint duplicate-import checks remain.

| Rule | Strict | Evidence |
| --- | --- | --- |
| `OURO-CLIPPY-FRONTEND-001` | `fatal` | The compiler frontend or structural fact build did not complete; Clippy cannot publish a successful analysis. |
| `OURO-CLIPPY-SUPPRESS-001` | `fatal` | Blanket clippy-grade suppressions hide quality debt across unrelated findings. |
| `OURO-CLIPPY-SUPPRESS-002` | `fatal` | A clippy-grade suppression without a reason is not reviewable. |
| `OURO-CLIPPY-SUPPRESS-003` | `fatal` | A suppression references a rule id that is not in the clippy-grade inventory. |
| `OURO-CLIPPY-REDUNDANT-001` | `deny` | An unannotated local is immediately returned through the same lexical binder, with no intervening expression. |
| `OURO-CLIPPY-REDUNDANT-004` | `deny` | Every distinct arm of a complete closed local enum match returns the same proven value; the scrutinee is a value and the arms contain no calls. |
| `OURO-CLIPPY-CHECKED-001` | `deny` | User-facing code bypasses checked filesystem reading. |
| `OURO-CLIPPY-CHECKED-002` | `deny` | User-facing code bypasses checked filesystem writing. |
| `OURO-CLIPPY-CHECKED-003` | `deny` | User-facing code invokes a process through an unchecked primitive. |
| `OURO-CLIPPY-CHECKED-006` | `deny` | An executed, registered must-observe checked result has no observation or escape through any alias. |
| `OURO-CLIPPY-ERROR-001` | `deny` | A known error branch exits or returns success status. |
| `OURO-CLIPPY-ERROR-003` | `deny` | A failure arm of a registered must-observe checked result returns the resolved success constructor. |
| `OURO-CLIPPY-MAINT-007` | `deny` | Two nontrivial declarations have identical tokens apart from their own names and trivia, retaining signatures, binders, callees and literal values. |
| `OURO-CLIPPY-PERF-001` | `deny` | Repeated registered pure conversion, parse or normalization with identical value identities. |
| `OURO-CLIPPY-PERF-002` | `deny` | Repeated identical registered pure traversal, including callback and all argument identities. |
| `OURO-CLIPPY-LOGIC-001` | `deny` | Registered reflexive Nat/String equality compares one semantic value with itself. |
| `OURO-CLIPPY-LOGIC-002` | `deny` | Registered strict Nat ordering compares one semantic value with itself. |
| `OURO-CLIPPY-REDUNDANT-008` | `deny` | A resolved Nat arithmetic operation has a proven neutral operand and returns its other argument unchanged. |
| `OURO-CLIPPY-LOGIC-010` | `deny` | Resolved Nat multiplication by zero, saturating subtraction from zero or itself, or remainder by one is proven to return zero. |
| `OURO-CLIPPY-LOGIC-007` | `deny` | A resolved Nat division or remainder API receives a literal zero divisor through its semantic value identity. |
| `OURO-CLIPPY-LOGIC-008` | `deny` | A resolved Nat comparison is constant because no Nat is less than zero, zero is at most every Nat, or a Nat is at most itself. |
| `OURO-CLIPPY-LOGIC-009` | `deny` | A resolved clamp_nat or between call has literal lower and upper bounds with lower greater than upper. |
| `OURO-CLIPPY-REDUNDANT-009` | `deny` | A resolved binary string concatenation receives an explicitly present empty-string literal from the compiler intern pool. |
| `OURO-CLIPPY-REDUNDANT-010` | `deny` | A resolved conjunction or disjunction is redundant by a registered Boolean identity or by identical known value identities. |
| `OURO-CLIPPY-LOGIC-011` | `deny` | A resolved conjunction with False or disjunction with True has a proven constant result. |
| `OURO-CLIPPY-REDUNDANT-011` | `deny` | A resolved list take or drop call receives a proven zero count. |
| `OURO-CLIPPY-REDUNDANT-012` | `deny` | The same resolved Boolean negation consumes its own result in the same branch and effect epoch. |
| `OURO-CLIPPY-PERF-003` | `deny` | The same registered idempotent string normalization consumes its own result in one effect-free execution region. A registered traversal cost and nonconstant original input are required. |
| `OURO-CLIPPY-PERF-004` | `deny` | The same resolved list reversal consumes its own result with identical element-type identity in one effect-free execution region. A registered traversal cost and nonconstant original input are required. |
| `OURO-CLIPPY-LOGIC-012` | `deny` | A resolved Nat clamp has identical lower and upper value identities and always returns that bound. |
| `OURO-CLIPPY-REDUNDANT-013` | `deny` | Resolved Nat minimum/maximum has identical operands or a proven zero operand. |
| `OURO-CLIPPY-REDUNDANT-014` | `deny` | Resolved Nat power has exponent zero or one, or base one; zero to exponent zero is one in this API. |
| `OURO-CLIPPY-REDUNDANT-015` | `deny` | Resolved text replacement has the same known needle and replacement value. |
| `OURO-CLIPPY-LOGIC-013` | `deny` | Resolved starts/ends/contains searches for an explicitly present empty-string literal and is always true. |
| `OURO-CLIPPY-LOGIC-014` | `deny` | A literal byte index is at or beyond the proven literal byte length; byte lookup returns sentinel zero, not a panic. |
| `OURO-CLIPPY-REDUNDANT-016` | `deny` | A resolved byte slice has a proven zero count and returns empty text. |
| `OURO-CLIPPY-LOGIC-015` | `deny` | A resolved byte slice starts at or beyond a literal's byte length with a positive literal count and returns empty text. |
| `OURO-CLIPPY-LOGIC-019` | `deny` | Resolved starts/ends/contains searches a string for the same semantic value and is always true. |
| `OURO-CLIPPY-REDUNDANT-017` | `deny` | A resolved Result predicate consumes a known Left/Right producer with matching error and payload type identities in the same branch and effect epoch. |
| `OURO-CLIPPY-REDUNDANT-018` | `deny` | A resolved Result default consumes a known Right producer with matching types, so its fallback cannot be selected. |
| `OURO-CLIPPY-REDUNDANT-019` | `deny` | Opposite resolved Nat extrema share the outer operand: min x (max x y) or max x (min x y). |
| `OURO-CLIPPY-REDUNDANT-020` | `deny` | A resolved Maybe default consumes a known Just producer with the same payload type. |
| `OURO-CLIPPY-PERF-005` | `deny` | List length consumes an unbound reversal of a nonconstant list with matching element type and registered traversal costs. |
| `OURO-CLIPPY-PERF-006` | `deny` | List length consumes an unbound list append with nonconstant left input, matching element type and registered traversal costs. |
| `OURO-CLIPPY-PERF-007` | `deny` | An outer take has a positive literal count at least as large as its producer take's positive bound, with matching type and execution region. |
| `OURO-CLIPPY-LOGIC-016` | `deny` | A drop count is at least its producer take's positive literal bound, so the result is empty. |
| `OURO-CLIPPY-REDUNDANT-021` | `deny` | An outer clamp contains its producer clamp's entire ordered literal interval and cannot change that result. |
| `OURO-CLIPPY-LOGIC-017` | `deny` | A range predicate contains or is disjoint from its producer clamp's ordered literal interval, fixing the Boolean result. |
| `OURO-CLIPPY-LOGIC-018` | `deny` | A resolved conjunction/disjunction combines a Boolean value with its proven negation through producer lineage in one execution region. |

Operation laws require resolved registered APIs, exact arity, known values,
and the rule-specific proof premise. Transparent ordered pass-through
summaries retain operation roles; changing or unknown wrappers do not.
An absent string-pool entry is not an empty literal. Nested negation,
normalization and reversal join producer identities with calls in the
same branch and effect epoch, without another expression traversal.
Those same-operation laws require the same resolved callee; composition
laws instead require their explicitly registered compatible operation roles.
These are review-required suggestions; evaluation and source spans are not
edit proofs. All twenty scalar/composition additions use `warn` in baseline
and project and `deny` in strict and release.

Composition proofs use the existing sorted producer/consumer join, not source
spelling or ordinal ordering. Result/Maybe tests and defaults require known
constructors and matching type arguments; generic or checked results without
that constructor proof remain unreported. An unused fallback is not permission
to remove its eager evaluation. Count dominance and interval containment use
ordered literal facts; unknown counts, inverted bounds and partial interval
overlap do not establish those proofs.

Length-of-reversal/append findings require an unbound temporary producer.
Existing binder facts conservatively exclude any locally bound producer,
including aliases, because another consumer may need the collection. An append
with constant left input does not establish an avoidable-allocation finding.
Literal text bounds use the byte length reconstructed from a present intern
entry, not a character count; valid UTF-8 continuation-byte indexes stay clean.
The zero-count slice and empty-needle search rules take precedence at their
intersections with out-of-bounds slicing and reflexive search.

## Fix publication and convergence

The [autofixer](tooling.md#autofixer) owns CLI modes and rule applicability;
[safe rewrites](quality.md#precision-and-safe-rewrites) own compiler checking,
source staging, and recovery. Semantic Clippy findings are review suggestions:
a proof of a finding is not an edit certificate. `fix --check` remains nonzero
while review-required proposals remain. Whole-production fix/format convergence
and post-fix cross-tool severity checks are not established.

## Regression coverage and current limits

`tests/clippy_semantic/cases.json` contains positive and negative source
fixtures for registered rules, including shadowed names, changed wrappers,
branch/effect differences, malformed registries, and byte-boundary cases.
Native proof laws independently mutate required evidence. A fixture or proof
law is not evidence that a production run completed; [CI](ci.md#local-profiles)
owns that result.

The semantic worker is diagnostic-only where exact expression spans or
preservation certificates are absent. It analyzes the selected source and
supported imported contracts; it does not typecheck the entire program or
prove whole-program equivalence.

## Prepare tools together

[Build and bootstrap](build.md#cache-model) owns content-addressed native tool
preparation, companion validation, cache receipts, and batch reports. An older
companion is never used after a failed freshness check.

## Session lifetime boundary

The structural worker accepts `--session SOURCE_ROOT PATH...`; the production
lint and Clippy-grade reporter supervise these sessions. Build the worker
through `native_tool_build.py`: plain C emission without its required
lifetime hooks is not a session-enabled tool build. The legacy single-root
and at-most-two-root batch paths keep their existing dispatch and errors.
Each proof frame is `ouro.clippy-semantic.v3`.

`tools/clippy/session.ouro` evaluates one root to its exact source/proof
snapshot before moving on. `cg_s_snapshot_request` returns that snapshot and
only the next intern/import-harvest state, including compact source origins,
not a `ClippySemanticUnit` or inferred contracts.
The C host enters an arena when the IO thunk executes, not when it is
constructed, and copies its result back through the existing runtime API.
Parsing, registry validation, dataflow, proofs and typed errors stay in Ouro.
The host does not implement an alternative analyzer or acceptance path.

The reporter's `cg_load_inventory` uses the same IO arena boundary for reading
and validating the rule registry. Only the compact rule map and validation
issues survive before a worker starts; the parsed JSON and validation
temporaries are released. Its required native hook changes allocation lifetime,
not registry decisions or errors.

A second IO lifetime surrounds an epoch of at most two roots, using the same
bound as the legacy batch. It emits completed frames inside that scope and
returns the current intern/cache pair and completion state. Intermediate
versions, source snapshots and temporary graphs are released; current intern
identities and harvested signatures/origins survive into the next epoch.
A malformed oversized epoch fails explicitly. Allocation epochs are distinct
from the heap watermark and process-recycling policy.

The reuse budget is 1024 combined name and string entries in the intern table.
It is checked after each completed root, including the first root in an epoch;
an oversized table ends the session with a completed prefix rather than starting
another root with accumulated identities. The existing root-count, cache-size,
large-source and heap limits remain additional recycling conditions. These
limits do not reject a source or skip any requested root.

The source root, compiled frontend and semantic options are fixed for the
entire invocation. Mutable state is not serialized across processes or reused
with another source root. Root source and proofs are recomputed on every
request; dependency contents are still reread and checked against the existing
cache key. Successful requests replace the intern/cache pair together. A root
error keeps the last valid pair and does not publish partial harvests. State
is dropped when the worker exits. This does not establish a cross-run cache,
dependency snapshot protocol or full semantic-unit reuse.

The `ouro.clippy-session.v2` wire format is separate from the semantic proof frame:

```text
ouro.clippy-session.v2
REQUEST_COUNT
root
ZERO_BASED_REQUEST_ID
PATH_BYTE_LENGTH
EXACT_REQUESTED_PATH_BYTES followed by LF
one complete ouro.clippy-semantic.v3 ok/error frame
... remaining requests in input order ...
done
COMPLETED_COUNT
ok or error or recycle
```

Paths preserve the requested spelling; `SOURCE_ROOT` supplies their common
context and the loader still owns canonicalization. Repeated paths receive
different request IDs. A handled root error emits its frame, retains the last
valid reusable state and continues within the resource limits. Failure is
sticky: any error requires the final `error` status and exit 1. A successful
completed prefix ends with `recycle`; a prefix containing handled errors ends
with `error` and exit 1. The supervisor verifies either prefix and sends every
remaining request to a fresh worker, retaining all fatal findings from the
prefix. All-success sessions exit 0, including a validated recycle boundary.
A crash, unexpected stderr, missing trailer, duplicate ID, wrong count,
identity mismatch or trailing output is not a clean session. Completed frames
may be retained for inspection, but a crash or malformed worker response
cannot be treated as a resumable prefix.

`tests/clippy_semantic/session_protocol.py --selftest` checks synthetic
transport boundaries without Ouro. The lint suite also builds the native
scheduling laws and captures six roots, including shared imports, duplicate
paths and a parse failure, in ten sessions under the existing 3072 MiB tree
limit. It compares every source/proof/error frame byte-for-byte against legacy
single-root responses and writes `ouro.clippy-session-parity.v1` JSON. The
observer redirects bytes before the host limiter's text normalization; it
does not parse Ouro or approve findings. This is snapshot transport parity,
not complete reporter fields, fix applicability or analyzer-report parity.

`tests/clippy_semantic/session_scope.c` is a standalone real-runtime fixture
for deferred IO, surviving closures/errors, ancestor identity sharing and
100 nested epoch resets. Its allocation workload is synthetic, not a native
Clippy RSS or throughput benchmark. Native compilation and execution are
required before any memory-bound claim. Source/protocol tests alone do not
establish native memory usage, throughput, or full diagnostic/analyzer/fix parity.

## Collection composition laws

`OURO-CLIPPY-COLLECTION-001` through `020` extend the same producer join.
`semantic_quality_kinds.ouro` supplies closed cases of `CmQualityProof`;
`semantic_quality.ouro` consumes only `ClippyCallFact` values through
`cm_nested_laws_with_bindings`. There is no second AST traversal, source-text
matcher, parallel registry or change to the existing repeated-work rules.
The canonical policy remains `quality/clippy_grade_rules.json`: all twenty
use baseline/project `warn` and strict/release `deny`.

Every row below requires resolved registered contracts, exact arities, known
non-IO arguments, pure calls, matching element-type identities, a List producer
edge, and the same branch and effect epoch. All twenty conservatively require
an unbound producer and nonconstant relevant data. A bound producer, including
an alias, may be needed by another consumer and is not diagnosed here.
The eight added `std/listx.ouro` roles (55–62) are direct contracts only;
lexical callee aliases preserve declaration identity, but these new roles are
not inferred through function wrappers. Changing and unknown wrappers stay
silent. Existing summary behavior for older roles is unchanged.

The table gives value laws, not text rewrites. Type arguments are omitted for
readability; `replicate x n` means payload `x` followed by count `n`, and
`head d`, `last d`, and `nth d i` retain the explicit default. `sub` saturates
at zero. Inputs/defaults/payloads must still be evaluated as required by the
original program; ownership and evaluation order need manual review.

| Rule suffix | Reported composition | Replacement direction and additional premise |
| --- | --- | --- |
| `COLLECTION-001` | `nullb (reverse xs)` | `nullb xs`; reversal cost and nonconstant input. |
| `COLLECTION-002` | `head d (reverse xs)` or `last d (reverse xs)` | Query the opposite endpoint of `xs` with the same default. |
| `COLLECTION-003` | `nullb (append xs ys)` | `andb (nullb xs) (nullb ys)`; the left input must be nonconstant. |
| `COLLECTION-004` | `length (replicate x n)` | Use `n`, retaining payload evaluation. |
| `COLLECTION-005` | `nullb (replicate x n)` | Test `n` against zero. |
| `COLLECTION-006` | `head/last d (replicate x n)` | Select `d` at zero count and `x` otherwise. |
| `COLLECTION-007` | `reverse (replicate x n)` | Retain the replicate; both operation costs must be known. |
| `COLLECTION-008` | `take/drop k (replicate x n)` | Replicate at `minNat n k` / `sub n k`; proven zero `k` belongs to the existing zero-count rule. |
| `COLLECTION-009` | `nth d i (replicate x n)` | Select `x` when `i < n`, otherwise `d`. |
| `COLLECTION-010` | `length (intersperse s xs)` | Measure `xs` once and use `sub (mul 2 n) 1`. |
| `COLLECTION-011` | `nullb (intersperse s xs)` | Test `xs` directly. |
| `COLLECTION-012` | `head/last d (intersperse s xs)` | Query the same endpoint of `xs`. |
| `COLLECTION-013` | `nullb (take k xs)` | Test `xs`; `k` must be a positive literal fact. |
| `COLLECTION-014` | `head d (take k xs)` | Query `head d xs`; `k` must be a positive literal fact. |
| `COLLECTION-015` | `take k (take n xs)` | Use `take k xs`; literal facts must prove `0 < k < n`. |
| `COLLECTION-016` | `drop k (drop n xs)` | One drop at `add n k`; both offsets must be positive literal facts. No allocation or asymptotic saving is claimed. |
| `COLLECTION-017` | `length/nullb (singleton x)` | One / False, retaining payload evaluation. |
| `COLLECTION-018` | `head/last d (singleton x)` or `nth d 0 (singleton x)` | Use `x`, retaining eager default evaluation. Nonzero/unknown indices do not qualify. |
| `COLLECTION-019` | `tail (singleton x)` | An empty list of the same element type. |
| `COLLECTION-020` | `reverse (singleton x)` | Retain the singleton without reversal. |

The first fifteen require the producer's registered traversal/allocation cost.
The last five are redundancy laws, not claims of expensive work. A dynamic
type argument or intersperse separator alone never proves useful traversal
work; known constant input collections remain excluded. Replication with a
proven zero count is excluded even when its payload is dynamic. The strict
smaller-prefix law `015` is disjoint from existing `OURO-CLIPPY-PERF-007`,
which owns the greater-or-equal outer count. Endpoint variants share one rule
rather than increasing the rule count.

When the same producer/consumer pair also establishes `OURO-CLIPPY-PERF-016`,
that proof owns the smaller-prefix diagnostic. `COLLECTION-015` remains
available for proven transparent wrappers outside the direct canonical API
contract required by `PERF-016`; one pair emits only one of these findings.

`tests/clippy_semantic/quality_expansion/` contains paired bad/good fixtures
for every rule and alias, shadowing, same-spelled global, changed-wrapper,
branch/effect, unknown and constant-input counterexamples. They are appended
to the existing `cases.json` precision inventory and retain exact expected
code lists. `quality_laws.ouro` calls the production producer join, checks
one expected rule (not merely membership), and mutates types, purity, arities,
lineage, costs, branch, epoch and producer binding independently. Its finite
value checks call the actual stdlib on empty, singleton and longer lists;
they are regression tests, not a universal equivalence theorem or benchmark.
`proofs.ouro` also applies its missing/unknown/false/duplicate-evidence matrix
to all twenty new proof kinds. None of these additions authorizes an autofix.

[CI](ci.md#local-profiles) owns the required Clippy suite. Authored fixtures
and laws do not imply a completed production run.
