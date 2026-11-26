# Shared work across Ouro toolchain requests

This research note records observations and an experiment plan for
`main@06d648a`. The target was a 20× speedup for the same operation, result,
and resource budget. The candidate must take at most 5% of the baseline
time. Compare cold operations with cold operations and repeated requests
with repeated requests.

The recorded C emission run for `pipeline.ouro` spent about 51 of its
56 seconds before returning checked bodies. That leaves too little time in
the C backend for a 20× improvement from backend changes alone. Repeated
editor navigation offers a separate experiment. Bootstrap batches may
share work across roots when their contexts match.

The compiler now uses the first and last name positions described in
hypothesis A. The language server uses a bounded navigation cache that
implements part of hypothesis C. Both observations apply to the later
implementation. The measurements in this note still describe the earlier
baseline, and they establish no speedup for either change.
[Compiler preflight](../../compiler/compiler.ouro) · [LSP navigation](../tooling.md#language-server)

## 1. Fundamental bottlenecks

### Compiler path at the baseline revision

For `compiler/pipeline.ouro`, the measured operation is compilation of a
root and its import closure. It does not measure execution of functions in
that file. `scripts/frontend_regen.py:emit_one` passes `--module` and the
full ordered list of `--unit` arguments to the producer, then validates and
processes the generated C. In `runtime/bootstrap.c:main`, both `check`
and C emission call `compile_units` first. On success, `check` returns
`CHECK_OK`. Emission reads checked metadata, prepares Core for erasure,
extracts `JsIR`, and writes bodies and export tables. Measure those phases
directly to attribute backend cost.

`preprocess_file_list_observed` in `compiler/pipeline.ouro` threads
`RecReg` backward through the input list. `parse_units_observed` threads
`InternState` forward, then `stitch_units_observed` resolves modules and
collects declarations. The C host performs these steps through
`compile_units_source_impl`, `unit_prepass_incremental`, and
`parse_units_incremental` in `runtime/frontend_link.c`. Its incremental
functions preserve results across memory banks within one process.
`closed_parse_unit` already uses `parse_unit_indexed` and
`lex_go_carried_with` at this revision. The linear `intern_ident`
compatibility function gives no timing information about that path.

`module_resolve_units_with_metadata` and `resolve_imports_with_sources`
determine visibility and declaration order.
`compile_checked_decls_with_result` checks remaining imports and `open`
declarations, desugars, builds the environment from the closure, rewrites
and lowers declarations to `Surface`, runs preflight compilation, and
builds the plan for exact Core bodies. `check_indexed_declarations_go`
threads `CheckEnvironment` through accepted predecessors with the
remaining fuel at each step. Identical file bytes alone cannot establish
equal preprocessing, parsing, or checking contexts.

The checked environment already contains an ordered list of `Entry`
values and a balanced `EntryIndex`. Constructor names can be reserved
outside the ordinary global namespace. `check_ind_extension_indexed`
reads prior declarations for positivity, and primitive checks depend on
roles. An equivalent check must retain those dependencies as well as
exported signatures, names, and direct import edges.
[Checker contract](../kernel_design.md) · [Trust boundary](../tcb.md) · [Source bytes, tokens, and spans](../canonical_source.md)

### Direct measurements

The root `compiler/pipeline.ouro` contained 54,301 bytes, or 5.3% of the
1,016,184 bytes in its 56 ordered inputs. Line-prefix counts found 86
`def` and 6 `inductive` lines in the root, and 1,690 and 181 in the
closure. These counts do not measure per-declaration cost. The compiler
reported 1,690 Core bodies and 3,729 names during emission. The
measurements use the saved producer described under
[Baseline and reproduction](#baseline-and-reproduction).

| Direct invocation in a fresh process | Wall time (s) | Peak Windows Job commit (MiB) | Result |
| --- | ---: | ---: | --- |
| `check`, tracing off | 74.591 | 356.28 | Exit 0, exactly `CHECK_OK\n`, empty stderr |
| `--module _pl`, tracing off | 85.525 | 356.16 | Exit 0, 10,076,899 bytes of C on stdout |
| `--module _pl`, `OURO_MEM_TRACE=1` | 55.719 | 356.31 | Exit 0, same output size and SHA-256. The stream was not saved to disk. |

Each row records one run. The differences between rows cannot isolate
backend cost or tracing overhead. In the traced process, the parent
received the markers shown below.

| Marker | Elapsed time (s) |
| --- | ---: |
| Before reading the input list | 0.113 |
| After preprocessing | 5.512 |
| After parsing | 9.347 |
| After resolving imports | 9.363 |
| After checking declarations | 50.827 |
| Return from `compile_units` | 50.832 |
| After freeing phase data | 52.891 |
| After emitting backend output | 55.699 |

The 41.464-second interval from resolved imports to checked declarations
added 100,976,994,664 bytes to the allocation counter. At the end,
31,249,064 bytes were live (`runtime/ouro_rt.c:ouro_heap_report`). The
counter measures total allocation volume. The interval includes
environment construction, lowering, preflight compilation, plan
construction, and checking. It does not isolate kernel time.

### Per-declaration profile

`runtime/n1_host_main.c` and `bounded_check_item` in
`runtime/frontend_link.c` measure individual declaration checks. A
separate run on `compiler/lexer.ouro` with `--check-profile --timings`
reached `CHECK_PROFILE_ONLY complete-source-check no-image` in 7.492 s
wall time, with `check-end` at 7.325 s. Its 507 completed intervals
totaled 3.135 s and 5.166 GB of allocations. Checking the body of
`source_take_scalar` used 0.219 s and 273,615,328 bytes of allocations.
That measures checking the function's body.

On `pipeline.ouro`, the same host hit the 125 s limit. It started 1,621
intervals and finished 1,620, totaling 31.736 s and 33.765 GB in completed
intervals. The expensive checks included `primitive_key` (2.082 s),
`pipeline_standard_special_ids` (2.011 s), and
`pipeline_nominal_special_ids` (1.694 s). Matching uniquely spelled names
assigned 1,447 `def` and 161 `inductive` entries in the completed prefix
to other files. Twelve names were unassigned. This matching provides
approximate attribution. The timeout, different producer, and different
fuel prevent using this run to break down the direct run's 41.464 s.

### Archived bootstrap measurements

One completed four-worker run recorded 221.9 s for the P1 frontend step
in `_build/bootstrap/6499a5718a99-_ds3u_nw/report.json`. Its
`out/p1/frontend.json` reported 14 translation unit (TU) misses, 1.60 s
for input collection, 11.01 s for the module cache, 199.93 s for TU
emission, and 4.65 s for packing. The pipeline-root TU took 199.91 s.
Strict check `check-13` took 190.90 s and may have overlapped emission.

P2 frontend took 108.10 s and `abi-build` took 207.01 s. The latter's
`out/p2/abi-build.json` attributed 11.11 s of 205.56 s measured internally
to C compilation and linking. A different Windows run with the
regeneration cache disabled recorded 260.21 s for P1 frontend, 250.31 s
for the pipeline TU, 10,100,719 bytes after processing, and 7.03 s for
packing. It restored C0 and the historical bridge. Those observations
describe distinct runs.
[Second run report path](#baseline-and-reproduction)

### Repeated input paths

For `collect_units_many` in `scripts/frontend_regen.py`, a prefix ends
at the selected input and a suffix starts there. The table counts distinct
ordered path tuples. Register and abstract syntax tree (AST) values
were not compared.

| Requests on one source tree | File occurrences | Distinct files | Distinct prefixes | Distinct suffixes |
| --- | ---: | ---: | ---: | ---: |
| 14 frontend TUs | 239 | 87 | 152 | 239 |
| Frontend plus backend | 249 | 91 | 157 | 249 |
| Plus four acceptance roots | 457 | 159 | 340 | 457 |
| Same 19 closures for checking and first 15 for emission | 706 | 159 | 340 | 457 |

The 19 roots account for 5,543,742 bytes including repeats, with
2,276,665 bytes at distinct paths. The collector already reads each
import path once per call. The first observed preparation took 1,706 ms
and the next five had a median of 274.5 ms. Some build steps call
`collect_units(root)` again. For example, the argument to `setdefault`
in `scripts/selfhost_module_cache.py:materialize_module_artifacts` is
evaluated even when the key exists. Count reads across the entire build
to find that cost.

## 2. Architectural hypotheses

### A. Index declaration positions for a cold compilation

At the baseline revision, `compile_program_item_pure` scans prior names
for duplicates. `surface_has_future_global` collects referenced names by
a bounded walk of `Surface`, then scans future names if the reference
index is nonempty. A sequence of unique names whose bodies only refer
backward can repeatedly scan the remaining suffix.

The proposed first and last positions come from the same
`surface_names` sequence. At ordinal `i`, `x` is a duplicate when
`first(x) < i`. A visited reference `r` names a future declaration when
`last(r) > i`. A missing last position leaves the unknown-global checks
to their existing owners. In `[a, b, a]`, a reference to `a` at ordinal
0 can refer forward, and `a` at ordinal 2 is a duplicate.

The preflight must retain handling of `SCase`, `SConstruct`,
`SPerform`, and literal types, and the failure order
`FutureSlot → Duplicate → FutureGlobal → compile_stage_check`. Preserve
location, ordinal, and fallback in `compile_surfaces_with_location`.
The walk uses `fuel32`, which is `(10 + 10) + (12 + 10) = 42` at the
baseline revision. The fallback has its own `depth_gate = 32`.
The index cannot cause a later declaration's error to take precedence.

The active compiler implements these first and last position queries.
Its C host uses the indexed path when the export is available and keeps
the list walk for older exports. Compare the two preflight paths under the
same workload. A cheap original scan or an expensive index can erase the
benefit. A different rejection at a duplicate, forward reference, or fuel
boundary invalidates the candidate. The work in `bounded_check_item`
remains in either path.
[Position queries](../../compiler/compiler.ouro) · [C-host selection](../../runtime/frontend_link.c)

### B. Share equal operations across a batch of roots

Retain the 19 original input orders. Read the immutable bytes once and
group only calls to the same pure operation with equal arguments. For
preprocessing, compare bytes, owner path, aliases, incoming `RecReg`, and
origin mode. For parsing, compare expanded bytes, identifier and string
tables and next-ID counters, path, fuel, and position mode. Results with
source spans must also account for the origin map.

Each call returns its value and outgoing state. Split groups when the
arguments diverge and merge them when equality is reestablished. Keep
initial resolution and checking separate for each root. Sharing a
semantic prefix requires identical resolved plans and incoming states.

The hypothesis applies to a cold batch without restoring disk results.
Measure whether it reduces executed transitions and total CPU work.
Compare the cost of repeated operations with the cost of establishing
equality and retaining state. If the reverse `RecReg`, numbering,
producer, modes, and memory limit leave nearly every transition unique,
keep shared reads and independent compilations.

### C. Refresh only the representation a request needs

For editor navigation, cache local declarations and direct imports tied
to exact source bytes. The fuller hypothesis stores import order and
reverse edges, replaces changed facts after edits, and reconstructs the
answer in the original order. A file or edge deletion invalidates its
contribution. Position data may change even when semantics are stable.
The first request pays for the index, and freshness still requires disk
reads without a reliable snapshot.

At `06d648a`, the path from `on_sym` to `lsp_index` extracted symbols
on repeated queries. The server now retains a bounded cache of
declarations and import spellings keyed by path and exact bytes. It
reauthorizes and rereads disk imports for each request. This implements
local reuse, while the proposed reverse-edge updates and reuse of
analysis facts still need separate evaluation. Changes to local facts
can require a new decision over the full analysis graph.
[Language server reference](../tooling.md#language-server) · [Navigation implementation](../../tools/lsp.ouro)

Measure authorization, reading and hashing the imports, response lookup
and serialization, and queueing. Any unavoidable cost above 5% of the
baseline rules out 20× for that operation. A stale clean diagnostic fails
the correctness test independently of its latency.

### D. Reduce intermediate representations on the cold path

`compile_checked_decls_with_result` produces `LoweredDecl`, rewritten
`LoweredDecl`, pairs containing `Surface`, Core bodies, and `FileItem`.
Test combining adjacent pure transformations that can pass the rewritten
body with its owner and failure cause. Future names, the closure's
environment, error order, and coverage retain their phase boundaries.
Emit C only after successful checking.

Profile allocation at the phase boundaries first. If reductions account
for the churn, or origin maps and fallback require both representations,
this experiment would remove little of the observed cost.

## 3. Novelty assessment

| Prior work | Relevance to Ouro |
| --- | --- |
| [Build Systems à la Carte](https://www.microsoft.com/en-us/research/publication/build-systems-a-la-carte/) and [rustc incremental compilation](https://rustc-dev-guide.rust-lang.org/queries/incremental-compilation-in-detail.html) | Scheduling and deciding when to recompute are separate. rustc checks dependencies through `try-mark-green` in observation order and needs stable identifiers. Ouro keys must also account for `RecReg`, intern IDs, and reductions that read bodies. Compiler checking still owns program acceptance. |
| [Adapton](https://adapton.org/) and [Differential Dataflow](https://www.microsoft.com/en-us/research/publication/differential-dataflow/) | These approaches cover demand-driven work and propagation of changes, including deleted facts. Hypothesis C still needs evidence that specific Ouro observations can be updated cheaply without changing dependent conversion or the first failure. |
| [A Variability-Aware Module System by Kästner, Ostermann, and Erdweg](https://www.cs.cmu.edu/~ckaestne/pdf/oopsla12.pdf) | Shared checking of configuration families predates this proposal. The study covers BusyBox with 811 options. Ouro's variants are roots and requests on one tree. Hypothesis B measures equal transitions in the forward and reverse passes and the cost of separating their states again. |
| [Lean elaboration and compilation](https://lean-lang.org/doc/reference/latest/Elaboration-and-Compilation/) | Sequential elaboration, kernel checking, and editor metadata serve different roles. Ouro first establishes an ordered plan for the closure. Each file boundary would need separate evidence before it could serve as a checked interface. |
| [SQLite query planning](https://www.sqlite.org/queryplanner.html) and [A Short Cut to Deforestation by Gill, Launchbury, and Peyton Jones](https://www.microsoft.com/en-us/research/publication/a-short-cut-to-deforestation/) | Indexes and removal of intermediate lists are established techniques. A tests the specific sufficiency of first and last positions. D tests where phase fusion can preserve failure causes and order. |

All 457 path suffixes for the 19 roots in the measured batch are
distinct. A key containing the whole suffix would find no repeated
backward transition. Different suffixes can still reach equal
`RecReg` states. A later experiment could share individual record
lookups if successful results, missing names, and shadowing agree.
Each branch would still carry forward the untouched portion of its own
incoming state.

The proposed experiments test which transitions across roots and which
observations across revisions are equivalent under Ouro's contracts.
The baseline and models provide no estimate of a speedup from prior
work on other systems.

## 4. Proposed architecture

Measure the bounded navigation cache first for repeated requests. For a
cold compilation, profile the list and positional preflight paths on
the same inputs. Before implementing B, count transitions with equal
contexts. Revisit D if profiling shows material allocation between
phases. Each experiment uses a fixed set of inputs, one owner for each
result, and counters for work performed.

1. Track the authorized canonical path, source bytes, buffer generation,
   disk imports, configuration, and producer version. Freeze batch
   inputs and verify freshness for each editor response. Treat
   filesystem notifications as invalidation hints. If freshness is
   uncertain, reread and recompute or return the prescribed error.
2. Keep source bytes, imports, navigation rows, lint facts, semantic
   tokens, position maps, and checked Core with their current owners.
   Use a digest to locate potential cache matches, then compare bytes
   or identical immutable values. Bound cached derivative data and
   reauthorize each access, including access to a replacement file.
3. Preserve declaration order, required names, cancellation, and the
   first failure per branch. Publish each editor response only for its
   own request and version. Bound entry count and aggregate bytes, and
   release state at the end of the batch or session. Eviction causes
   recomputation. Keep the reference computation for comparison and
   recovery. The proposal does not give disk cache entries authority
   to accept a program.

### Two roots and one edit

At the baseline, `compiler/lexer.ouro` has 16 ordered inputs and
`compiler/pipeline.ouro` has 56. The two lists contain 72 occurrences
at 56 distinct paths. They share the first seven inputs, starting at
`std/types.ouro` and ending at `compiler/base.ouro`. The lexer list
continues with `compiler/ast.ouro` and the pipeline with
`compiler/core.ouro`.

- One snapshot can serve 56 content reads instead of 72 for consumers
  that would otherwise read separately. The import collector already
  avoids duplicate reads within one preparation. The suffixes for
  `base.ouro` differ. Hypothesis B would preprocess them independently
  unless their inputs are equal. Parsing can be shared when expanded
  bytes and incoming parser states agree. Each root retains its own IDs
  and `CheckEnvironment` after the divergence and checks its full plan.
- On a repeated navigation request, reuse local symbols only when the
  buffer version and authorized disk bytes permit it. Preserve traversal
  order and the first match. At the baseline `lsp_index_go` consumes one
  step even for a duplicate in the queue. With `lsp_index_fuel = 4096`,
  removing duplicates earlier can change which symbols reach an answer.
  The navigation cache has no role in authorizing `CHECK_OK` or issuing
  a new diagnostic.
- An edit to the lexer body with the same signature affects five of the
  historical roots by path. These are the lexer, `compiler/preprocess_import.ouro`,
  `compiler/pipeline.ouro`, `tools/collect.ouro`, and
  `tests/compiler_abi_tests.ouro`. This count assumes unchanged import
  edges and producer. Recheck the affected plans after updating bytes,
  coordinates, and the reverse `RecReg` and forward intern context. An
  invalid import body must prevent a clean diagnostic or executable.
  Navigation may retain an unchanged symbol set only with current spans.
- `compiler/backend.ouro` occurs in one of the 19 lists and
  `std/prelude.ouro` occurs in all of them. Reordering imports changes
  the plan even if the set of paths is unchanged. Changing the next
  stage's producer invalidates its old output keys, including those for
  paths outside the five directly affected roots.

## 5. Computational model

Let `T₀` be the baseline time for the operation, `p` the fraction of
baseline time attributable to the work being improved, `s` the speedup in that fraction, and `h`
the new overhead divided by `T₀`. Overhead includes freshness checks,
indexing, copying, and waiting. The model is
`T₁/T₀ = (1 − p) + p/s + h`. For 20×, the right side must be at most
`0.05`.

The 55.719 s traced emission run gives a budget of 2.79 s. Eliminating
all work after `compile_units` would leave 50.83 s, a speedup ceiling
of 1.10×. Eliminating the 41.464 s interval alone would leave 14.26 s,
or 3.91×, if everything else stayed constant. Eliminating all C compile
and link time in the archived ABI build yields at most 1.06×. Each
calculation applies to its observed run.

| Hypothesis | Cost model | Measurements |
| --- | --- | --- |
| A. One root | With `D` names, list scans can reach order `D²`. Logarithmic name access gives order `(D + R) log D` name operations for `R` extracted references, plus the same bounded walk of `V` nodes. Memory grows with distinct names. | Count `Nat` comparisons, visited nodes, and allocations. Measure the phase and full command. Name comparison can have variable cost. |
| B. One batch | Separate execution pays `c(q)` for every transition. Sharing pays once per group of equal arguments plus comparison, storage, and per-root output. Wall time is at least the critical path and total work divided by the worker count. | Count groups, splits, CPU and allocation cost, live memory, and throughput at 1, 2, and 4 workers within the same total budget. `457/159` measures path repetition. |
| C. Edit or request | Repeated navigation still pays for freshness, graph traversal, and response construction. Changed files require new facts. Separate first-request preparation from the remaining `N − 1` requests. | Count reads, bytes, symbol extractions, affected edges and URIs, queue delay, and time to the last byte. Hashing all imports retains a lower bound by volume. Editing the prelude can approach a full refresh. |
| D. Representations | Of total allocated bytes `Aₜ`, only a portion of the intermediate structures `Aᵢ` can be avoided by fusing two phases. | Count allocations at phase boundaries and in workers. Measure live bytes after release and peak process memory separately. |

Reading, verification, and writing required output impose a floor.
Running `k` processes alone cannot establish a `k`-fold improvement in
single-request latency. Sharing the common prefix of one check and one
emission on the same inputs can save at most half their combined work.
Their wall times may already overlap. For throughput, divide the number
of successfully processed files by total wall time with the same files,
rules, CPU, and memory. Report failed runs separately.

## 6. Integration with Ouro

The original estimates are for one developer familiar with the owning
component. Low means a few days. Medium means one to three weeks with
differential tests. High means several weeks and a separate trust-boundary
review. These estimates cover experiments.

### Language server

The baseline `workspace_symbols` called `lsp_index` for each open URI,
and the baseline `on_watched_files` rechecked open buffers. Measure the
implemented bounded cache on repeated hover and definition requests.
Treat reverse edges and narrower refresh as a separate, medium-cost
experiment. Preserve full text synchronization, open buffers as roots,
disk imports, the `OURO_ROOT` boundary, UTF-16 positions, limits, and the
existing checker and formatter calls. Measure edit-to-diagnostic latency
separately from navigation requests.
[Language server source](../../tools/lsp.ouro) · [Language server reference](../tooling.md#language-server)

### Compiler and bootstrap

Separate preprocessing, `parse_unit_indexed`, resolution, lowering,
preflight, planning, and `check_indexed_declaration`. At the baseline,
`LexerIntern` already contained two `SourceNameIndex` values. Isolate
conversion and reconstruction for positivity before considering another
cache. The existing mechanisms include `whnf_deferred`,
`conv_checked_worker`, and the derived `EntryIndex`. Measuring A has
medium cost. Sharing checker prefixes across edits has high cost.

Measure erasure, extraction, emission, export checks, TU processing,
packing, ABI construction, and C compile and link separately. The
baseline bootstrap and regeneration scripts already scheduled heavy
jobs first. Measure the critical path to a verified P2. Measurement or
scheduling has medium cost, and B past parsing has high cost.
[Compiler source](../../compiler/compiler.ouro) · [Bootstrap driver](../../scripts/bootstrap_compiler.py)

The baseline sequence was C0, historical bridge, P1, and P2. For the
current checkout, the documented sequence includes a separately checked
second historical bridge, bridge2, before P1. Measure its inputs and
receipt independently and separate fresh work from verified reuse. The
historical four-stage numbers do not include bridge2. Preserve the
original and compact source checks where applicable, ABI laws, full
P1/P2 frontend and backend C equality, and both the valid and the exact
invalid P2 closure cases. Improving P1 cannot speed up the historical
producer used to build it.
[Current bootstrap stages](../build.md#c-bootstrap)

Measure ordinary builds and verified no-ops separately. Count repeated
opens or hashes and miss reasons before changing a cache. Keep input
verification before reuse. Separate an empty cache, a verified no-op,
and changes to an input, header, runtime, producer, C compiler, or
flags. A hit from `phase_keys_for` does not establish that the checker
skipped a body. This experiment has low to medium cost.
[Build caches](../build.md#cache-model)

### Lint, analysis, and rewrites

- Lint. The baseline workers isolate families and files. Its semantic
  session policy bounds roots, cache, heap, and interning, with up to
  two roots per epoch. It retains intern data and import collections.
  Compare the baseline run with a small batch using the same families,
  severity, hints, applicable fixes, clean output, ordering, `--deny`,
  and first fatal finding. Startup savings must exceed added arena
  churn. This experiment has medium to high cost.
  [Session policy](../../tools/clippy/session_policy.ouro)
- Analysis. The base pass is required, and selected structural
  families already share `AnalysisUnit` from
  `tools/analyze/unit.ouro:unit_of_source`. Measure the supervisor, fact
  extraction, local rules, and global decisions separately before
  evaluating C on local facts. The baseline limited a global request
  to 8 files and 64 KiB, and a structural input to 40 KiB. Architecture
  and dead-code decisions still require the full selected graph. This
  experiment has medium cost.
  [Analyzer reference](../../tools/analyze/README.md)
- Formatting and fixes. Reuse source tokens, comments, directives, and
  positions only when their facts and byte ranges still apply.
  `fx_prepare` requires a complete plan and convergence.
  `source_write.ouro` checks the source before replacing it. Retain
  manual review, compiler checks, idempotence, explicit failures, and
  conflict recovery. Position mapping has medium cost. Changing
  checked rewrites has high cost.
  [Rewrite contracts](../quality.md#precision-and-safe-rewrites)

The reference `build FILE.ouro` invocation emits a Windows PE from a
checked closure. Evaluate that path against a PE baseline at the same
fuel. Measure checking, rechecking at native lowering, MIR, emission,
and image publication. The measurements for `--module _pl` cover
generated C only.
[Native program compile](../tooling.md#native-program-compile)

Keep pure work with Ouro. The C host and Python can measure and enforce
existing process bounds. Frontend observations may inform the direct
native path, while C sharding and packing belong to the C path.
[Native toolchain contract](../design.md#native-toolchain-contract) · [Roadmap](../roadmap.md)

## 7. Correctness and risks

- Equivalence requires the same owner, bytes, paths, import order,
  body, visibility and `open` state, other observed state,
  `CheckSourceCore` or `CheckExactCore` mode, remaining fuel, producer,
  and output settings. Include policy and tool version for derivative
  cache entries. Treat uncertain equivalence as a miss.
  `preprocess_records_reg_with_origin` may read the incoming registry
  even without a local `record`. Reusing intern numbers by spelling
  requires a sound remapping of references, diagnostics, and exports.
- Only compiler-owned checking of every reached body, including unused
  imports and effect roots, can produce `CheckedProgram`. A checked
  immutable value may stay inside its authorized computation.
  Serialized `passed=true` and `ouro.checked-program.v1` can support
  comparison but have no authority to accept a program. Preserve
  conversion, positivity, reserved constructors, primitive roles, and
  malformed, unsupported, and resource outcomes. At the baseline,
  `compile_surfaces_with_location` can fall back to
  `elaborate_surfaces` after code 2 at depth 32 with no holes.
  Preserve the original failure location and the distinct
  `check_expansion_guard` and reduction-exhaustion failures.
- Preserve the first failure, output, names, positions, and status
  even when independent work finishes out of order.
  `check_indexed_declarations_go` polls cancellation before and between
  items, consumes fuel, and checks required-name coverage at the end.
  Cancellation or exhaustion invalidates a partial prefix. Strict
  bootstrap checks require exactly `CHECK_OK\n` and empty stderr.
- Test unobserved disk changes, renames, deletion, import targets that
  change, and edits during computation. Keep authorization, protocol,
  child limits, recovery, and cleanup. Report scratch and read
  failures explicitly. Measure total peak memory and growth over
  repeated requests. Recompute on an identity conflict or return the
  specified failure. Cache, editor, watcher, and profiling output
  remain outside the compiler trust boundary.
  [Trusted computing base](../tcb.md)

## 8. Experimental validation

### Baseline and reproduction

The source revision was
`06d648a6dbedbf9b0c5c1b69c6f430ba18c1892a`. The host ran Windows 11
`10.0.26300` on an Intel Core i5-14600KF with 20 logical CPUs and
Python 3.12.10. The saved producer was
`_build/verify-9822874-win/c/ouro1`, with SHA-256
`8b1d222f9b362165b91e669b3b517e4eaed29f0085c66556317197c1f170a173`.
It matched its receipt. `compiler/lexer.ouro` differed between the
receipt's 196 inputs and the measured source tree. The measurements
therefore use the saved producer on the stated sources. They do not
compare two compilers built from the same bootstrap. The `_build/`
paths refer to local archives and are not included in an ordinary
checkout.

For the direct pair, use the saved producer and collect
`collect_units("compiler/pipeline.ouro")` from the repository root.
For each ordered input, concatenate the UTF-8 path, one zero byte,
and the binary SHA-256 of its contents. The aggregate SHA-256 was
`c48f2a9cf5eef5eaf5f073980567722732e2efed7dbda517ab498a2cf3102afc`.
[Ordered import collection](../../scripts/frontend_regen.py)

Pass either `check compiler/pipeline.ouro 16000` or
`--module _pl compiler/pipeline.ouro 16000`, followed by a separate
`--unit` and path argument for every input. Run sequentially through
`scripts/ourosmith/limits.py:run_limited_bytes` in a scrubbed environment
with a 100 s timeout and 1,536 MiB Windows Job limit. Set
`OURO_EMIT_SCOPED_ARITHMETIC=1` only for emission. The launcher was
inside the timer. Input collection was outside. The runs did not use
`ouro1.sh`, build or postprocessing steps, or the TU cache. The OS
cache was not reset.

Both C emission runs gave SHA-256
`7eaddc435e85918bb7e024fc93c64483fe505dcc19dd650b764f1323db3197b9`.
The run with `OURO_MEM_TRACE=1` used a 150 s limit and below-normal
process priority. The parent read the log and stdout while the
process ran.

With the same producer, fuel `16000`, and prepared inputs, the median
over five fresh processes after the first run was 158.4 ms for
`std/prelude.ouro` with 22.3 MiB peak Job commit and 4,356.5 ms for
`compiler/lexer.ouro` with 107.2 MiB peak Job commit. Both returned
`CHECK_OK`. One `std/args.ouro` attempt exceeded 12 s.
`tests/bad_undeclared_perform.ouro` was rejected once in 9,383.4 ms
with code 41 and detail 1135. Measurement stopped before repeat
runs, so this rejection has no median.

The declaration profile used `n1-host.exe` from
`_build/verify-9822874-win/frontend-host-retry/frontend-host.json`,
SHA-256
`a46a08d4561aab6fb5e039d291266c54bc5ad22ce0a430dcc86f81dc98ae4641`,
and fuel `200000`. It emitted no image. The second archived P1
frontend run is recorded in
`_build/verify-9822874-win/bootstrap/d2bcf6c46feb-_riu8omi/out/p1/frontend.json`.

### Controlled experiments

1. Compare navigation with the bounded cache enabled and disabled in
   the same language server. Use the same frames, visit order, path
   authorization, buffer versions, and disk bytes. Keep diagnostics,
   scheduling, and formatting fixed. Record open, repeated hover and
   definition, an invalid unsaved edit, its correction, a change to an
   unopened import, definition, and close. Also test a removed import
   and a disk change without notification. Compare responses,
   notification order, URIs, UTF-16 positions, scratch and process
   errors, and cleanup. Even zero fresh extractions on a hit can
   leave time above the target.
2. Measure cold preflight through `compile_checked_decls_with_result`
   and `compile_program_item_pure`. Count visits to Surface,
   scanned `seen` and suffix entries, fallback, and allocations.
   Separate lowering, planning, and `bounded_check_item` cost in the
   same process. Compare positional and list predicates at every
   ordinal before the timed comparison. Then measure the full command
   with predicate cross-checking and profiling disabled. The original
   combinatorial check covered all 364 lists of length 0–5 over three
   IDs, every ordinal, and 16 reference sets over four IDs. It made
   26,256 future-name comparisons without disagreement, and the
   duplicate predicates agreed. This checks the formulas. The Surface
   traversal and timing require their own experiments.
3. Before adding shared evaluation for B, record input sizes, exact
   matches between states, and transition costs for each phase of
   the 19 historical input lists. Start with the two roots in
   [Two roots and one edit](#two-roots-and-one-edit), one producer, and
   one worker. Compare separate runs, a batch sharing bytes only, and
   a batch sharing one preprocessor or parser transition with full
   keys. Record startup and reading separately from shared evaluation.
   Stop after counting if comparison is expensive or almost all
   states diverge. Keep these observations separate from bootstrap
   acceptance.

### Comparison and acceptance criteria

| Series | Cases and measurements | Required agreement |
| --- | --- | --- |
| Cold check and emission | Prelude, lexer, pipeline, `std/data.ouro`, `tools/collect.ouro`, and `tests/compiler_abi_tests.ouro`. Include valid, invalid, and fuel-boundary inputs, a local edit, an invalid imported body with the same signature, reordered imports, and a changed prelude. Count reads, parses, lowerings, checked declarations, output bytes, and peak memory. | First failure owner, phase, code, span, both streams, exit, complete checked snapshot in a separate check, and C bytes. Exercise reserved constructors, primitive roles, positivity, reduction failure, and cancellation. |
| Bootstrap and builds | Separate fresh stages, verified historical reuse, verified no-op, and changes to a dependency, prelude, header, runtime, producer, or flags. Include bridge2 for the current sequence. Record hit and miss reasons, verified bytes, object rebuilds, ABI work before C, waiting, and the critical path. | Required commands, complete P1/P2 comparison, ABI laws, and exact positive and negative P2 outcomes. Reject missing or damaged receipts. Compare cache disabled, empty cache, and verified hits. A fixpoint alone gives no evidence of toolchain independence. |
| LSP | Start one fresh process per session for each variant. Measure first response, repeated navigation, version changes, and edit-to-authoritative-diagnostic latency. Count reads and extractions, and run a long enough series to exercise eviction. | Same reference protocol and input. Detect stale results, omitted updates, and changes to the selected symbol when names coincide. |
| Lint, analysis, and fixes | Use the same family and complete profile on a small file and a fixed corpus. Record files per second, child launches, repeated import collection, `AnalysisUnit`, base, structured, and global pass times, and retained data. | Same order, IDs, severity, edits, witness ranges, directives, suppressions, strict and deny modes, first fatal, and exit status. Compare fix proposals and resulting bytes. Keep all global work, families, and limits. |

Use the repository's benchmark commands for comparable runs.
`scripts/perf_core_toolchain.sh` measures latency.
`scripts/bench_suite.py` with `quality/linter_bench.json` uses a fixed
corpus, with one warm-up and five fresh processes by default.
`scripts/kernel_profile.py` with `quality/kernel_baseline.json`
covers checking, building, and running laws.
[CI validation](../ci.md#validation-matrix) · [CI performance evidence](../ci.md#performance-evidence) · [Quality contracts](../quality.md)

The archived
`_build/verify-9822874-suites/final-analyze/core/report.json`
records 843.314 s of pool time for 61 sequential checks and 61 wrapper
launches. It cannot isolate process startup or measure analyzer
throughput. The archived LSP runs cover complete sessions. On the
Windows test host, the retained LSP and quality binaries for the
examined suites were ELF, and `_build/native/coil.exe` was absent.
The note has no comparable fresh series for those tools or for the
historical four-stage bootstrap.
[Archived LSP runs](../build.md#native-transition-baseline)

Record exact input and tool revisions and receipts, hardware, OS,
flags and fuel, OS and application cache state, output bytes, resource
budgets, and process priority. Alternate baseline and candidate on
the same host with equivalent process lifetimes. Repeat complete
series and retain each sample and status. Report client wall time,
CPU, allocations, and peak memory separately. Windows Job commit
and resident set size measure different quantities.

Five runs give an initial median. Measuring p95 or the 20× target
requires longer independent series and a measure of uncertainty.
Accept 20× for the named operation only if the upper bound for the
candidate-to-baseline time ratio is at most 0.05 with equivalent
results and resource limits. Count a timeout, memory exhaustion,
changed output, or unresolved startup or memory regression as a
failed comparison.

## 9. Final assessment

The direct C emission and the archived bootstrap runs both point to
frontend work as the first place to measure. Only 5.3% of the bytes in
the direct run came from the root file. The 41.464 s interval does not
identify one function, data structure, or checker rule as the cause.

Measure repeated hover and definition on an unchanged graph first.
For an edit with confirmed unchanged dependencies, count repeated
parses and declaration checks before drawing conclusions about
diagnostics. For cold compilation, profile the phases and measure
the positional index separately from the rest of checking. Before
adding shared work to bootstrap, measure equal contexts and their
weight on the critical path. For lint and analysis, separate
isolation cost from rule execution. Drop the 20× target for any
workload whose mandatory work already exceeds the 5% budget. The
study did not demonstrate 20× for any workload.
