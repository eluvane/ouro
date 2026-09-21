<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=FIREWALL&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="FIREWALL banner"
  />
</p>

# Clippy-grade deny firewall

Semantic proofs in this page are the `semantic` family of `ouro1 lint`.
They use the compiler lexer/parser, canonical import resolver and a
read-only declaration index. Language and proven style stay in the other
lint families. `analyze` retains repository-graph and heavy structured
cores. The Python command is an adapter for that family plus fixture and
query flags. The separation is not yet complete: expensive clone analysis
still lives in this family.

## Run it

```sh
sh scripts/ouro1.sh lint --deny --family semantic --profile project std
python3 scripts/clippy_grade_firewall.py --profile strict --scope std
python3 scripts/clippy_grade_firewall.py --print-files --scope compiler
python3 scripts/clippy_grade_firewall.py --list-rules
python3 scripts/clippy_grade_firewall.py --validate-rules
python3 scripts/clippy_grade_suite.py
python3 scripts/clippy_grade_suite.py --precision-only
```

The user-facing production command is `ouro1 lint`. The Python adapter still
builds the native Clippy worker, writes JSON/SARIF, and serves fixture/query
flags (`--list-rules`, `--validate-rules`, `--print-files`). `strict` and
`release` reject `--warn-only` and fail on deny/fatal findings.
`project --warn-only` may report ordinary debt without a failing exit, but cannot
hide a fatal error, malformed registry, missing rule, or incomplete inventory.
The existing narrow suppression language remains for compatibility. Routing
through the unified lint driver adds no production suppressions, baselines,
or path-based debt exceptions.

## Semantic boundary

`semantic_unit.ouro` reads imported sources for each requested root and shares
an intern table inside a worker. Its existing harvest cache uses canonical
relative path, source byte length and content hash; a hit avoids parsing and
harvesting that dependency again. It resolves the import graph and builds
`compiler/semantic_scope.ouro` identities. A multi-file worker invocation
reuses that intern table and cache across at most two roots and
emits the existing `ouro.clippy-semantic.v2` batch protocol. Hits never skip proofs. `semantic_registry.ouro` associates
contracts with canonical module/declaration or intrinsic ABI identity. A local
same-spelled function does not inherit a standard-library contract. Unknown
calls are effect barriers, not assumed pure. This is not a full compiler type
check of the analyzed program and does not replace `ouro check`.

The worker produces `ouro.clippy-semantic.v2`: exact byte-framed root source,
complete proof count, rule, owner, node ordinal, and explanation. The reporting
cone rejects incomplete/noncanonical frames and unknown emitted IDs. A node
ordinal is **not** an exact editable expression span. Semantic Clippy findings
remain manual suggestions, not automatic transformations.

Each definition is traversed once into shared call/value/binder/flow facts.
Repeated-work rules compare all argument identities, resolved callee, branch,
effect epoch, registered purity and relevant cost. Higher-order arguments are
part of the key. Constant inputs do not establish expensive repeated work.
Result obligations come only from explicitly registered checked APIs and only
when an IO action is executed. Aliases preserve producer identity; a match,
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

## Fix publication and convergence

`tools/fix/plan.ouro` distinguishes mechanical, review-required, and unsupported
proposals. Automatic classes are existing syntax repairs and narrow local
redundancy; literal/provider, binder renaming, unreachable-arm, import-alias,
list-type and nonrecursive-fix rewrites require review. Unsupported IDs fail.
Comments/directives in deletion spans prevent automatic application; compound
same-rule edits cannot be half-applied when one touches trivia.

The planner sorts deterministically, coalesces identical edits, rejects unequal
overlaps/same-point insertions, and applies one priority class before reparsing.
Bounded source history rejects cycles and unfinished fixed points. Formatting
must preserve tokens and must not reopen an automatic rewrite. The public CLI
checks the original and each candidate class with the compiler worker before a
final atomic source transaction; preview/check also require verification.
Review suggestions are printed but not silently applied. `fix --check` remains
nonzero while review-required proposals remain.

A successful type check alone is not equivalence proof. Full post-fix
lint/Clippy/analyze severity-delta verification and production-wide canonical
convergence remain unfinished. Raw `fx_fix` helpers are legacy golden-test
mechanisms, not publication authority.

## Regression coverage and current limits

The suite retains the original fixture names, uses actual dependency closures,
turns retired heuristic positives into negative cases, and tests malformed
registries, strict/release policy, source-root movement, intrinsic identity and
local shadowing. Native laws additionally cover alias flow, branch/effect
mutations, edit conflicts, trivia, cycles and second-pass no-ops. Added coverage
is not a claim that every test passed; see the pass-specific validation report.

The structural `cm_load_file` harvest shares the caller intern table and keeps
imported function bodies inside the nested parse arena. The selected file
still keeps its bodies; imports keep signatures only. A content-addressed
harvest cache reuses those facts across roots inside one worker; the worker
recycles after a bounded number of roots and drops the cache. A hit never
skips Clippy proofs. Large compiler and tool cones still need a rebuilt
structural companion before that harvest is live; do not treat an older
leftover scan as cleared without that binary.
The structural companion keeps crash/OOM isolation fail-closed by recycling
the process. The Python launcher lists the clippy inventory (same
keep/skip rules as `tools/strict/walk.ouro`) and may split a directory scan
across `OURO_CLIPPY_JOBS` workers (default 2, maximum 3) with the existing
3072 MiB `run_limited` cap and a 7200s host timeout; those limits are a safety envelope,
not a substitute for making the worker faster. `--print-files` prints that
launcher inventory and exits.
`build_tool.sh` validates the structural companion's source/compiler/config
receipt and binary digest even when the parent is current. The legacy
`OURO_REUSE_EXISTING_COMPANION` environment variable does not bypass those
checks. A valid installed companion is reused without emission/linking;
a stale, incomplete or corrupt companion must be rebuilt successfully.
A failed rebuild is an error, not permission to run an older image.

## Prepare tools together

After bootstrap, repeated `--tool ENTRY OUTPUT` arguments prepare tools in
one host process using the existing content-addressed builder:

```sh
python3 scripts/native_tool_build.py --compiler _build/c/ouro1 \
  --tool tools/lint.ouro _build/c/ouro-lint \
  --tool tools/clippy/main.ouro _build/c/ouro-clippy-grade-firewall \
  --batch-report _build/tool-preparation.json
```

Preparation is sequential; batching does not increase compiler workers or
reuse diagnostics. Each tool retains full content validation. Identical
requests are coalesced; conflicting outputs, receipts and companion targets
are rejected before building. `--check` checks every requested tool without
building and returns nonzero if any tool or companion is stale. The JSON
report records per-tool cache results and elapsed preparation time; it is
not a diagnostic-parity or native throughput benchmark.

The frontend preparation collector shares import adjacency only within one
collection call, then releases it. Later calls reread source contents; no
mtime-only import cache is introduced. Run host preparation contracts with
`python3 scripts/tool_preparation_suite.py`; these mock emission/linking and
do not replace native lint, Clippy, formatter, fixer or compiler suites.

## Experimental session lifetime boundary

The internal structural worker accepts `--session SOURCE_ROOT PATH...`.
It is not enabled in the production lint/grade/analyze launchers. Build the
worker through `native_tool_build.py`: plain C emission without its required
lifetime hooks is not a session-enabled tool build. The legacy single-root
and at-most-two-root v2 batch paths keep their existing dispatch and errors.

`tools/clippy/session.ouro` evaluates one root to its exact source/proof
snapshot before moving on. `cg_s_snapshot_request` returns that snapshot and
only the next intern/import-signature state, not a `ClippySemanticUnit`.
The C host enters an arena when the IO thunk executes, not when it is
constructed, and copies its result back through the existing runtime API.
Parsing, registry validation, dataflow, proofs and typed errors stay in Ouro.
The host does not implement an alternative analyzer or acceptance path.

A second IO lifetime surrounds an epoch of at most two roots, using the same
bound as the legacy batch. It emits completed frames inside that scope and
returns only completion status. This is intended to discard epoch-owned
intern deltas, cached signatures, snapshots and temporary graphs before the
next epoch while retaining the process and immutable compiled infrastructure.
A malformed oversized epoch fails explicitly. The limit has not been raised
without measurements, and allocation epochs are not an RSS watermark or an
OS process-recycling policy.

The source root, compiled frontend and semantic options are fixed for the
entire invocation. Mutable state is not serialized across processes or reused
with another source root. Root source and proofs are recomputed on every
request; dependency contents are still reread and checked against the existing
cache key. Cache state is dropped between epochs and after a root error.
Dependency parsing reuse therefore extends only across a compatible epoch,
not across the whole long-lived process. This does not establish a new
cross-run cache, dependency snapshot protocol or full semantic-unit reuse.

The `ouro.clippy-session.v1` wire format is separate from the legacy v2 batch:

```text
ouro.clippy-session.v1
REQUEST_COUNT
root
ZERO_BASED_REQUEST_ID
PATH_BYTE_LENGTH
EXACT_REQUESTED_PATH_BYTES followed by LF
one complete ouro.clippy-semantic.v2 ok/error frame
... remaining requests in input order ...
done
COMPLETED_COUNT
ok or error
```

Paths preserve the requested spelling; `SOURCE_ROOT` supplies their common
context and the loader still owns canonicalization. Repeated paths receive
different request IDs. A handled root error emits its frame, clears reusable
state and continues with the remaining requests. Failure is sticky: any error
requires the final `error` status and exit 1. An all-success session exits 0.
A crash, unexpected stderr, missing trailer, duplicate ID, wrong count,
identity mismatch or trailing output is not a clean session. Completed frames
may be retained for inspection, but no production retry/partial-report path
is implemented by this experiment.

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
establish that the experiment is production-ready.

Production integration, measured process/frontend/parse/registry counters,
long-run RSS and safe process recycling, dependency-change tests inside a
running session, registry reuse beyond the existing constant infrastructure,
full diagnostic/analyzer/fix parity and the mandatory native suites remain
rollout requirements. No repo-wide speedup or single-file latency claim is
made for this experimental path.
