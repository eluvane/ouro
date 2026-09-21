<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=TCB&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="TCB banner"
  />
</p>

# Trusted computing base

Ouro's program-checking authority belongs to its compiler, written in Ouro.
The native transition removes the requirement for a second implementation to
authorize compilation. It does not remove type checking, negative tests, or
explicit failure. See [Architecture](architecture.md) and [Build](build.md) for
the current compiler and bootstrap paths.

## Compiler checking boundary

`compiler/file_elab.ouro` checks the complete ordered declaration set, including
imported bodies and effect roots. It checks declared types, body types,
inductive parameters and constructors, positivity, structural recursion, and
primitive contracts. Rejected, exhausted, cancelled, and malformed operations
remain errors. Parser success and a successful lowering traversal do not
establish declaration acceptance.

The declaration plan derives definition membership from its supplied name
list using the existing numeric-name index. Filtering retains core order,
duplicate bodies, and complete terms; the index does not replace checking.

The checker has a deliberately small, pure dependency closure:

| Responsibility | Modules |
| --- | --- |
| Data and terms | `std/types.ouro`, `std/prelude.ouro`, `std/data.ouro`, `compiler/base.ouro`, `compiler/core.ouro`, `compiler/file_check_model.ouro` |
| Primitive contracts | `compiler/primitive_model.ouro`, `compiler/primitive_contracts.ouro`, `compiler/primitive_registry_base.ouro`, `compiler/primitive_registry.ouro`, `compiler/primitive_check.ouro`, `compiler/primitive_roles.ouro` |
| String reduction | `compiler/string_nf_bytes.ouro`, `compiler/string_nf_values.ouro`, `compiler/string_nf_eval.ouro` |
| Environment and resource accounting | `compiler/file_check_environment.ouro`, `compiler/file_check_work.ouro` |
| Declaration checking | `compiler/file_elab_core.ouro`, `compiler/file_elab_lookup.ouro`, `compiler/file_check_result.ouro`, `compiler/file_elab_positive.ouro`, `compiler/file_elab_term.ouro`, `compiler/file_elab_infer.ouro`, `compiler/file_elab.ouro` |
| Dependent refinement and constructors | `compiler/file_refine_scope.ouro`, `compiler/file_refine_case.ouro`, `compiler/file_refine.ouro`, `compiler/constructor_closures.ouro` |

These modules may import only modules in this list. They contain no host
intrinsics, externs, axioms, or effect operations. Checked primitive declarations
are input data; the pure checker verifies their identities and signatures
without performing their runtime operations. Representation annotations on
the shared data types do not grant host access. `std/types.ouro` holds their
existing declarations separately from the executable helpers in `std/prelude.ouro`
and `std/data.ouro`; it is subject to the same pure-source checks.

The `compiler-boundary` repository profile checks these imports using the
shared positional tokenizer. Comments and string contents cannot add imports
or declarations. Missing, unreadable, unsafe, or truncated source inventories
are blocking errors. A new checker dependency requires an intentional update
to both the allowlist and this page.

## Checked values

`compiler/checked_program.ouro` owns the `CheckedProgram` representation.
`compiler/pipeline_support.ouro` materializes it only after declaration checking
succeeds. `compiler/checked_program_output.ouro` serializes its complete checked
declarations and emission metadata for diagnostic comparisons.
`compiler/native/lower_boundary.ouro` rechecks supplied declarations and
metadata before native lowering, including a publicly constructed wrapper.

The static gate restricts references to `CheckedProgramOf` in compiler sources
to those four modules. References to `DeclarationsOk` are restricted to
`compiler/file_check_model.ouro`, `compiler/file_elab.ouro`,
`compiler/pipeline_support.ouro`, and `compiler/native/lower_boundary.ouro`.
Ouro currently exposes constructors through its module model: this is an
ownership policy enforced by CI, not an unforgeable type-level seal. Callers
must use the checking entry points; a wrapper constructor alone is not evidence
that its contents were checked.

The diagnostic `ouro.checked-program.v1` dump contains types, bodies, binding
contracts, representation roles, and emission order. It is not a serialized
permission to skip checking. Caches, generated outputs, analyzer reports, and
build receipts remain outside compiler acceptance.

## Current host assumptions

The working producer still uses committed stage0 C, a system C compiler, the
repository C runtime and IO adapters, and Python/shell build orchestration.
Windows producer tools reserve a 2 GiB PE stack so the native-build cone can
be checked and emitted without `STATUS_STACK_OVERFLOW`; that reserve is a host
limit, not an acceptance judgment. The C printer walk budget (`print_c`
`big_fuel`) is the same kind of host emission limit and does not change
checker acceptance.
The Windows native backend and Ouro raw runtime have a separate, limited
execution path. A native PE fixture does not establish a native compiler
bootstrap or garbage collection; those require their own end-to-end checks.

Managed object storage uses `HeapCreate`, `HeapAlloc`, `HeapFree` and
`HeapDestroy` through typed NoGc Windows extern declarations. These APIs join
the platform allocation assumptions; checker acceptance, object headers,
descriptor checks and exact shadow-root tracing retain their existing owners.
The private heap is used only for published managed objects. Its allocation
path cannot collect or call user code between an OS allocation and publication.
Only exact owned allocation bases reach `HeapFree`; mappedness and
`HeapValidate` are not accepted as ownership proofs. Empty-owner destruction
requires an empty allocation list and zero object/requested-byte counters.
An OS release failure preserves the remaining objects or heap handle.
The private context gains one raw handle word after its allocation budget;
native images and raw context clients must be rebuilt for that footer.

The split frontend host bounds temporary allocations around the canonical
Ouro lexer, lowerer, preflight compiler, elaborator, and declaration checker.
Preflight and elaboration callbacks retain their results before releasing their
temporary storage; the Ouro pipeline still selects each pass and fallback.
The fallback depth predicate preserves the existing threshold condition;
it does not replace the complete hole scan or declaration checking.
The curried compilation entry
isolates its phase and permanent banks from the caller, then copies the checked
result and diagnostic metadata into the caller's restored allocation context
before freeing compiler storage. This lifetime machinery does not choose types,
declaration order, fuel outcomes, or acceptance judgments. The C-hosted
native-build driver uses the same `compile_checked_units` seam so a
compiler-sized program does not retain every parse and check temporary.
The `lower_recheck_program` host wrapper supplies that same bounded declaration
callback to Ouro's exact replay. The ordinary public entry still selects the
canonical checker; declaration order, metadata equality, complete body lists,
fuel failures, and rejection semantics remain Ouro-owned.
The temporary N1 host also checkpoints the managed preparation result and
lowers raw contracts through the existing Ouro step with per-contract storage.
It preserves contract order, typed failures, and all scalar fallback inputs;
malformed host result or list shapes fail explicitly. These lifetime boundaries
do not replace managed finish or the complete MIR check.
The PE byte-check callback retains its captured input before the allocation
mark and its typed error or unvisited suffix before releasing temporary storage.
Ouro computes the suffix inside that same callback. Byte validity and error
order remain with the same Ouro validator; the C callback does not inspect or
rewrite image bytes.
Bulk PE fixup planning derives a symbol index that retains the first original
symbol for each ID. The existing resolver still checks that symbol's section
and RVA; slot, target and ordering diagnostics keep their original precedence.
Complete image validation continues to reject duplicate and malformed symbols.
The temporary C host evaluates the complete canonical fixup plan in a nested
allocation context, retaining its full patch list or typed error before freeing
the symbol-index and traversal temporaries. Curried arguments and the caller
remain live. The wrapper does not resolve targets, inspect slots or change
patch bytes, ordering, validation or diagnostic precedence.
Raising the MIR node/flow hard ceiling to `pe_byte3_place` is a host
resource bound for compiler-sized images; it does not change typing,
declaration order, or which MIR errors are accepted. The C wrap around
`mir_check_bounds` only substitutes that same ceiling for an already
emitted producer until the next fat emit. The N1 producer host requires
`mir_check_program` to accept the complete lowered program before GC
inference, annotation, GC checking, and `codegen_checked`. Per-function
lifetime callbacks preserve the Ouro checker's result while reclaiming its
temporary allocations. Inside a function, the canonical type, reachability,
and initialized-use callbacks run in nested allocation contexts; their exact
typed results are copied back before those contexts are freed. The outer
function mark and captured program remain live. Phase order, declared-flow
facts, fuel, and error selection stay in the existing Ouro callbacks.
Within reachability, `mir_reachable_with` exposes the exact round's frontier
construction as a pure `run_ids` callback. Its public runner is identity;
the C host copies the complete reached-ID list before freeing a nested
round context. The original `foldr`, frozen `seen` set, convergence step,
fuel consumption and first unreachable-block error remain Ouro-owned.
This limits temporary lifetime to one round; it does not impose a new
graph algorithm or promise a fixed memory bound for an individual round.
Declared-flow analysis similarly runs each complete `mir_flow_step_with`
through a pure `run_facts` callback. The public runner is identity; the C
host copies the complete typed result before freeing that round's context,
preserving shared lists across its block facts. Predecessor intersection,
immediate fact publication, convergence comparison, fuel and error order
remain in Ouro. The caller retains prior facts until the comparison finishes.
Retained MIR and codegen contexts follow each supplied
argument and are cleared before frontend compilation resets permanent storage.
Neither successful GC annotation nor executable
encoding substitutes for MIR validation. The Ouro
`managed_validate_parts` / `native_emit_image` path retains the same check.
C wraps around `mir_gc_infer`, `mir_gc_annotate`, `mir_gc_check`,
`x64_encode`, `codegen_assemble`, `codegen_parts`,
`codegen_live_instructions`, `codegen_instruction`, `codegen_block`, and
`codegen_body` substitute
equivalent host walks for the same Ouro functions so a compiler-sized
image can finish on the C-hosted producer. Liveness facts are computed by the
canonical Ouro solver in a nested allocation context; its complete facts or
typed error are retained before temporary storage is released. Each
Jacobi round similarly retains its complete typed result before releasing
round-local storage; frozen input facts, summary order, convergence and fuel
remain in the canonical solver. Accelerated
function emission runs that same liveness check first for managed-root
functions, preserving unknown-edge and convergence-budget failures.
The live-instruction wrap
keeps every managed slot live instead of running the interpreted
intra-block transfer; that is sound and more conservative. Unrecognized
instruction shapes fall back to the generated closures. Managed
allocation and managed-context instructions are included in the
`codegen_instruction` wrap. The wraps do not change which MIR errors
are accepted; they are a host lifetime and time seam, not a second
checker. Progress messages from these wraps are disabled for ordinary generated
programs and explicitly enabled by the diagnostic N1 executable. Failure
diagnostics and exit status are independent of that progress setting.

Native Nat multiplication, division and remainder specialization requires
complete checked Core templates, exact source dependencies, and registered Nat
and Bool shapes. Machine conversions guard the optimized operand ranges;
zero divisors and wider values call the captured original body. This is an
execution optimization: checker reduction and program acceptance are unchanged.

The transitional C runtime's existing Nat arithmetic bindings use compact
small values and arbitrary-length 32-bit limbs for larger naturals. Addition,
multiplication, comparison, saturating subtraction, constructor matching and
decimal formatting preserve values beyond the host word width. Heap-context
copies retain the limbs. Host-size conversions reject overflow; only the
explicit Word32 operations and byte conversion discard high bits. These remain
runtime assumptions in the existing C host boundary, exercised by arithmetic,
conversion and lifetime regressions and the bounded-process API laws.

Native managed startup adapters resolve `ouro.runtime.argv` and
`ouro.runtime.env_get` through checked primitive identities and normalized
types. Their raw Windows helpers require a checked ordinary body with the
complete pointee types and a raw lowering contract for that same declaration
ID. Names, erased pointer shapes, or an extern/axiom replacement alone do
not authorize a call. Raw staging never casts a managed pointer into an OS
pointer. Windows buffer ownership and Unicode API behavior remain runtime
assumptions outside the pure checker. Stdin actions use the same checked
ordinary-body and complete-pointer-type boundary for their raw reader,
allocator, and release helpers; its Windows handle is process-owned.

The managed compiler retains a canonical lookup environment derived from the
same ordered declarations after the program recheck. Raw-contract updates keep
that environment; helper body, normalization, and signature comparisons still
run for every requested binding. The lookup index carries no separate acceptance
authority.

Native file adapters use checked `ouro.fs.read_file` and `ouro.fs.write_file`
identities with the existing String/Runtime/Unit types. Their raw helpers use
the same checked-body, complete-pointee and matching-contract requirements.
C host filesystem read/write and string `of_char_codes` are length-based
temporary adapters for native PE emission.
The temporary C host also executes the checked Runtime pure, bind and loop
operations, checked Nat-to-U8/U32 conversion and wrapping U8 subtraction.
These adapters preserve deferred, reusable actions and reject malformed loop
flags; they do not implement Windows extern calls or authorize programs.
Windows handle validity, size queries, binary transfers, reparse attributes,
truncation and close results remain runtime assumptions. The write guard
inspects the opened final component before truncation. File scopes track raw
pages and handles separately from managed roots; process-terminal managed
heap exhaustion is handled by the shared allocator, outside local cleanup.

Native directory identities `ouro.fs.list_dir` and `ouro.fs.listable` use
checked String, List and Bool roles with ordinary Runtime actions. Helper
selection retains complete pointee types, checked bodies and matching raw
contracts. The literal access probe, handle metadata, search results and
FindClose behavior rely on Windows. Search names are bounded by the actual
WIN32_FIND_DATAW filename storage and decoded strictly before managed copying.
Raw pages, probe handles and search handles have explicit lifetimes; managed
paths, names and list tails stay rooted across calls. The separate probe and
search do not establish a snapshot or a no-follow property.

Source publication adds the closed `ouro.fs.replace_file` identity with three
String arguments and a deferred Runtime Nat status. Existing primitive codes
are unchanged. Its native helper uses the same checked-body, signature,
complete-pointee and GC-root contracts as rename. Windows file identities,
link counts, security descriptors, flush/close and `ReplaceFileW` are additional
runtime IO assumptions; none can authorize a declaration. The temporary C
host mirrors this filesystem operation for bootstrap-built tools. Ouro owns
staging, content verification, recovery and cleanup. An IO success is not a
compiler acceptance result, an atomic snapshot against concurrent editors, or
a power-loss durability guarantee.

Native `ouro.fs.realpath` retains String/Runtime identity and the same checked
ordinary-body and complete-pointer-type helper boundary. Windows
GetFinalPathNameByHandleW resolves the opened target with a bounded sizing
query and fill. Empty paths and OS unavailability return an empty String;
invalid storage, malformed text, incomplete fills and cleanup failures exit
with 73. One file scope owns the handle and all conversion pages, and retains
the final managed String during cleanup. Resolution follows links; the query
and fill do not provide an atomic filesystem snapshot.

## Outside the checker

`Ouro.seal` and `Ouro.lock`, including `trust {}`, express project intent and
resolved inputs. They cannot enlarge the checker or authorize unchecked
declarations. `trust.compiler = "required"` names the active authority;
the retired `trust.kernel` key is rejected by the build configuration parser.

Source buffers, display paths, analyzer facts, cache manifests, executable
bytes, and host reports remain outside the pure declaration checker. The
runtime, code generator, C compiler, and bootstrap seed remain part of the
current execution and compilation assumptions. A correct declaration judgment
alone cannot prove their implementation correct.

OuroSmith generates typed Core and exercises the canonical checker. Its
construction laws, known rejections, source mutants, and independent
surface/runtime expectations are regression evidence. It contains no required
second Core interpreter. The former OCaml and Python replay owners are retired;
their historical schema and corpus are documented in
[Core artifacts](kernel_core_artifact.md).

The checked current-executable path API calls `GetModuleFileNameW` through
an ordinary typed Win64 extern and existing raw allocation, UTF-16 validation
and UTF-8 conversion capabilities. Windows supplies the loaded image path;
this query does not establish canonical identity, source provenance or byte
integrity. The source owns one disjoint buffer allocation until the complete
managed String exists, then releases its base once. A failed release returns
a typed cleanup error with any earlier error retained; the reservation may
remain live until termination. Error categories do not assume numeric
`GetLastError` preservation across managed foreign-call return boxing. No
new primitive identity, compiler raw-helper root or checker reduction rule
authorizes this API. OS path-query, conversion and release behavior remain
runtime assumptions.

Sequential sleep uses an ordinary typed Win64 `Sleep` extern and the existing
managed `runtime_loop` and checked word conversions. The remaining seconds
stay a full `Nat`; only 1000 milliseconds and loop flag 1 are converted to
machine words. Zero performs no OS wait; no call passes `INFINITE`. The source
introduces no primitive identity, raw-helper root, checker reduction rule or
raw storage owner. Windows timer resolution and thread scheduling remain
runtime assumptions. `Sleep` returns no status; failed runtime constants are
reported explicitly instead of consulting `GetLastError` or skipping the delay.

Native foreground processes use the closed `ouro.process.inherit` identity
and existing String/List/Nat/Pair/Runtime representations. Raw helper selection
still requires checked ordinary bodies, complete pointee types and matching
lowering contracts. The runtime assumes Win64 structure layout, strict UTF
conversion, handle duplication, `CreateProcessW` job-list attachment, nested
job restrictions and kill-on-close semantics. The job is unnamed and its only
handle is not inherited. This prevents a create-then-assign interval in which
parent termination could abandon an uncontained child. Windows 10 / Server
2016 is the documented floor for job-list creation; enclosing job restrictions
return their OS error without an uncontained retry. These are runtime OS
assumptions, not proofs of checker or GC correctness.

Bounded capture adds the closed `ouro.process.capture_bounded` identity and
checked helper bodies. It reuses creation-time Job assignment and capture-file
ownership. Additional runtime assumptions cover Win64 Job limit/accounting
layout, process affinity, completion-port messages, monotonic ticks and finite
process waits. The runtime checks ActiveProcesses=0 before capture reads;
waiting on the Job handle itself is not an active-zero completion barrier.
Stream lengths are checked before raw and managed capture allocation. Ordinary
capture retains its prior behavior; it does not acquire an implicit timeout.

The memory policy matches the current Python supervisor's hard Job cap plus
events 9/10 and peak observation. Windows does not guarantee all hard-limit
completion messages. Peak commit is not a history of denied allocation attempts,
so a missing event does not prove that no resource denial occurred. Observed
resource violations cannot become expected-negative child success. This
limitation is retained explicitly; the API does not claim stronger attribution
or change the runtime's terminal allocation-failure semantics. No compiler
program-acceptance rule, external replay owner, or C production process engine
is added by this primitive.

The transitional C host mirrors this bounded identity on Windows only, with the
same typed reply contract: creation-time Job assignment with kill-on-close,
completion-port termination events, private capture files, and peak-commit
observation. It validates CPU count 1 without affinity pinning, reports
resource events only from observed port events, and keeps the POSIX stub
returning OS status 120. Windows Job behavior, event delivery, and capture-file
IO remain runtime assumptions; the adapter cannot authorize a declaration and
does not change checker acceptance. The C IO selftest and the fix compiler-check
suite cover this adapter boundary.

## Guardrails

```sh
sh scripts/ouro_repo_gate.sh --profile compiler-boundary --out _build/compiler_boundary
sh scripts/test_suite.sh --compiler-checking
python3 scripts/kernel_hardening_suite.py
python3 scripts/kernel_scale.py --profile scale --out _build/kernel_scale/scale
python3 scripts/kernel_scale.py --profile depth --out _build/kernel_scale/depth
```

Hardening requires all retained laws across uncached, fresh cached, and reused
cached executables, with source and producer receipts and a per-run budget.
The scale and depth profiles require complete probe protocols, current inputs,
and exact typed results. Crashes, timeouts, missing rows, and stale receipts
cannot satisfy these contracts. [CI](ci.md) describes the required gates.

## Assurance limits

Accepted declarations are well-typed under the implemented rules and explicit
assumptions. This does not establish an axiom's truth, the user's intended
behavior, foreign-code safety, GC correctness, or a formal proof of the
compiler's metatheory. Native self-hosting and matching stage bytes establish
rebuild behavior only when those stages actually run; they do not prove
compiler correctness.

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
