# Trusted computing base

The Ouro compiler determines which declarations it accepts. This page
describes that checking boundary, the host it relies on, and the limits of
its assurance. See [Architecture](architecture.md) for data flow and
[Build and bootstrap](build.md) for host and seed requirements.

## Compiler checking boundary

`compiler/file_elab.ouro` checks the complete ordered declaration set, including
imported bodies and effect roots. It checks declared types, body types,
inductive parameters and constructors, positivity, structural recursion, and
primitive contracts. Rejected, exhausted, cancelled, and malformed operations
remain errors. Parser success and a successful lowering traversal do not
establish declaration acceptance.

Emission selects bodies through an index derived only from the accepted
definition entries. Requested order, first-definition lookup, and typed
missing/bodyless failures are preserved; the index adds no acceptance authority.
Positivity certificate invalidation uses the earlier environment's actual
entries; constructor reservations alone do not invalidate a certificate.

`compiler/module_registry.ouro` and `compiler/module_names.ouro` resolve
source-module names before the ordered declaration plan reaches the checker.
They cannot authorize an unchecked import: each reached declaration and body
still enters the same compiler-owned checking path. The module pass adds no
checker allowlist dependency or host IO authority.

The name cache lives within one rewrite batch and derives only from that batch's
immutable member list. It stores no declaration-checking results.

The transitional C frontend accelerates `module_lookup` only after the generator
binds its alias, `lookup`, and `eqNat` to their canonical source owners and checks
their complete source shapes and data layouts. It scans canonical packed keys
that fit the host word, preserving the first matching payload and leaving the
unvisited tail untouched. Unsupported key or list shapes call the captured
original function with the complete original list. This host walk adds no
declaration acceptance authority and does not establish native independence.

The parser records each private declaration and its generated members in the
owning source unit. Module resolution keeps owner-local access and removes
those members from external plain, selected, qualified, local-open, transitive,
and generated record-grant scopes. Visibility never removes a declaration from
the ordered checker input.

Record preprocessing uses canonical source paths and local import bindings to
select the shape of a qualified literal or projection. It preserves the
qualified type and base, and fails when the aliased file does not own the
record accessor. Generated constructor and accessor references carry exact
marker, owner, and member grants for atoms actually emitted by record sugar.
The module resolver validates those grants against the file's effective
import scope, so a selective edge cannot expose a hidden accessor through
record syntax. Raw source cannot spell the marker separator, and each
generated reference still passes through module resolution and the complete
declaration checker. The text-only record preprocessor rejects output that
would require this metadata. Dotted expression references left after import
preprocessing still undergo projection validation when the record registry is empty.
Comments and quoted literals cannot activate that path, and an unknown prefix
cannot establish a module owner.
When a qualified reference resolves to a global name also used by a lexical
binder, the module pass interns a distinct binder ID before lowering. It
rewrites bound uses with that ID and keeps the qualified reference attached to
the global declaration.
The direct declaration compiler rejects any residual expression-level `open`
before desugaring or lowering; only module resolution may erase that scope.

The declaration plan derives definition membership from its supplied name
list using the existing numeric-name index. Filtering retains core order,
duplicate bodies, and complete terms; the index does not replace checking.

### Diagnostic metadata

Frontend failure metadata adds no acceptance authority.
`compile_program_with_location` records the failing occurrence and resolved
name beside the existing future-slot, duplicate, future-global, surface or
core phase. `compile_program_with_owner` erases the occurrence;
`compile_program_result` and `compile_program_located_result` project the
original `CompResult`. The same traversal still uses the existing contexts,
seen names, future list, fuel and structural core checks.

`lower_expr_env2_with_cause` and `lower_run_with_cause` produce root-only
diagnostic metadata at the actual list and named-hole owners. The ordinary
lowering APIs erase that metadata without changing `LowerVal`, `Surface` or
hole IDs. `compile_checked_from_decls_with_origin`,
`stitch_checked_source_with_origin`, `stitch_checked_units_with_origin`, and
the corresponding `driver.compile_checked_*_with_origin` APIs transport those results through
the existing complete declaration plan. `source_result_comp` retains the
original error or checked payload; `source_failure_diagnostic` exposes the
known owner to the split C renderer. The renderer neither scans source for a
possible cause nor uses absent spans as offsets. Source-unit association
comes from the resolver's ordered declarations, rather than the root path or
a first name match. Publicly constructed envelopes remain diagnostic data,
not a substitute for compiler-owned acceptance. See
[Architecture](architecture.md#source-and-frontend) for the root-cause and
span limits.

The additive original-origin factory retains the same checked source packet
and intern table. Its sparse preprocessing regions and parser occurrences
are diagnostic data; the typed sidecar cannot replace import, body, effect or
declaration checking. Invalid regions refuse the map-required projection
without replacing the original `SourceResult`; valid ambiguous ownership
remains unknown. Public constructors remain forgeable and do not authenticate
a native address map or admit a program. The opt-in path materializes source
boundaries and validates region composition; it adds no IO, intrinsic or
checker authority. Boundary materialization remeasures retained suffixes and
output prefixes; composition and occurrence joins also revisit lists. This
nonlinear path requires separate retained-budget measurement before a large
source consumer uses it.

### Pure dependency closure

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
The Ouro automatic lowering path gives the managed and scalar branches the
same privately constructed `NativeRecheckedProgram`. It binds the replayed
program to the fuel used to check it. Direct lowering entries run their own replay.

`compiler/erasure_checked.ouro` derives emission bodies with normalized sort
annotations and computed type arguments using the canonical checker operations.
This view never replaces checked declarations or diagnostic snapshots. Resource,
reduction and unsupported residual type-computation failures stop emission.
The C adapter isolates preparation temporaries per accepted body and retains
the typed result before releasing that body's temporary arena.

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

Character literals are decoded by `compiler/source_text.ouro` and the lexer
into existing `TNat`/`ENat` values. The decoder rejects noncanonical UTF-8,
surrogates, out-of-range scalars, and multi-scalar payloads before normal Nat
checking. Preprocessors and tooling only preserve or skip the original quoted
bytes at an identifier boundary; they do not authenticate a literal or bypass
checking. This syntax adds no Core form, primitive type, runtime role, or
bootstrap ABI.

## Current host assumptions

### C producer and Windows paths

The transitional C codegen preserves the full six-argument `codegen_block`
fallback contract, including canonical liveness facts. Safepoint root clearing
uses the Ouro liveness and clearing operations; incomplete facts remain errors.
Descriptor metadata deduplicates complete host-representable symbol IDs without
a 16-bit cutoff. Unrepresentable or malformed metadata declines the fast path
before publishing a registry. The frontend-host suite compares these paths with
canonical metadata and emitted bytes, including forced fallback. This is
regression evidence within the existing execution assumptions, not a new
program-acceptance authority.

The working producer still uses committed stage0 C, a system C compiler, the
repository C runtime and IO adapters, and Python/shell build orchestration.
Windows producer tools reserve a 2 GiB PE stack so the native-build cone can
be checked and emitted without `STATUS_STACK_OVERFLOW`; that reserve is a host
limit, not an acceptance judgment. The C printer walk budget (`print_c`
`big_fuel`) is the same kind of host emission limit and does not change
checker acceptance.

The Windows C host converts the wide command line to strict UTF-8. Bootstrap
file opens, checked reads, and path probes convert UTF-8 paths to UTF-16 and
reject invalid encoding. Legacy C directory mutations and file copies use
narrow paths. These conversions take place outside declaration checking.
[Build entry points](build.md#entry-points) and
[filesystem mutations and path resolution](effects_design.md#filesystem-mutations-and-path-resolution)

### Native Windows managed heap

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

### Frontend allocation lifetimes

The split frontend host bounds temporary allocations around the canonical
Ouro lexer, lowerer, preflight compiler, elaborator, and declaration checker.
Preflight and elaboration callbacks retain their results before releasing their
temporary storage; the Ouro pipeline still selects each pass and fallback.
The indexed preflight derives first and last name positions from the
ordered surface declarations. An earlier first position identifies a duplicate.
A later last position identifies a future reference for the same fuel-bounded
surface traversal. For multi-file compilation, the split frontend supplies an
item scope to `compile_program_with_location_indexed_with`. Each item borrows
the prepared indexes and the ordered traversal's arguments. Older export tables
use the same item scope with the list-based callback. The lifetime adapter
retains the failure phase and error, or the future suffix and Core term, in the
caller before releasing the isolated context. Both routes preserve declaration
order, fuel, first-error metadata and context advancement.
Downstream declaration checking determines compiler acceptance.
The fallback depth predicate preserves the existing threshold condition;
it does not replace the complete hole scan or declaration checking.
The curried compilation entry
isolates its phase and permanent banks from the caller, then copies the checked
result and diagnostic metadata into the caller's restored allocation context
before freeing compiler storage. This lifetime machinery does not choose types,
declaration order, fuel outcomes, or acceptance judgments. The C-hosted
native-build driver uses the same `compile_checked_units` seam so a
compiler-sized program does not retain every parse and check temporary.

Temporary contexts use a 64 KiB minimum for the first block of each phase and
permanent bank. Subsequent blocks grow by two up to the existing 1 MiB block
size; larger requests retain their aligned size. This policy follows the
exchanged banks, so survivor copies use the restored caller's policy. Root and
static banks keep their 1 MiB minimum, including static allocation inside a
context. Released blocks of the standard 64 KiB to 1 MiB sizes are kept for
reuse by any bank, newest first, up to 64 MiB in total; other blocks, blocks
beyond that bound, and every block in AddressSanitizer builds return to the C
heap. Alignment overflow fails before allocation. Clone
ownership, allocation counters, checker authority and native acceptance remain
separate from this reserved-block policy.

Static cells are immutable and never released, so the runtime remembers the
packed value of a successor chain rooted in the static bank. At most 1 MiB of
such values is built in the static bank; past that bound, a result that needs
allocation is rebuilt in the current bank on each use. Chains rooted in other
banks are packed on every use.

The `lower_recheck_program` host wrapper supplies that same bounded declaration
callback to Ouro's exact replay. The callback resolves and captures the canonical
checker once when constructed. Each declaration uses isolated allocation banks;
the result returns to the caller's restored allocator and shares caller-owned
terms and earlier accepted entries. The ordinary public entry still selects the
canonical checker; declaration order, metadata equality, complete body lists,
fuel failures, and rejection semantics remain Ouro-owned.
Indexed normalization, type-former classification, managed preparation, and
per-function lowering use nested temporary allocation contexts. Each wrapper
returns the complete canonical result, including typed failures, to the restored
caller; immutable arguments and captured lookup environments remain borrowed
from that caller. These boundaries do not cache callback results or implement
normalization, classification, checking, or MIR decisions in C. Managed finish
stays outside them because its compiler and generated-getter state retain
allocator pins. This temporary C-host lifetime mechanism is not evidence of
native toolchain independence.

### C-hosted pure calls

The canonical `compiler/source_name_index.ouro::source_name_compare` also uses
the existing pure binary scope. The wrapper borrows its raw closure and both
arguments before entering the context. Both raw curry applications run inside
that context. Its complete Ordering returns to the caller before comparison
temporaries are freed. The Ouro body still compares full canonical Nat values
and chooses the lexicographic result; C does not compare names or narrow bytes.
The installer requires the exact public body, imports, Nat/List/Ordering shapes,
original source owner and getter, binary curry, cache and installed wrapper.
It retains every generated helper body. The internal `source_name_compare_scope`
export alias leaves user homonyms intact. Source, installer and runtime hashes
bind the frontend caches. Selected TU hits replay the installed-form guard;
full and packed hits verify signatures and output hashes.
This boundary limits retained work across comparisons. It does not limit the
cost or peak storage of one comparison or establish native acceptance.
The canonical `std/data.ouro::elem` uses the same scope at erased arity three.
The predicate, target and list remain borrowed from the caller. All three raw
curry applications run inside one context after the third argument arrives.
The complete Bool returns before that context is freed. The Ouro body keeps
both eager `orb` operands, full list traversal and the supplied predicate;
the wrapper does not implement membership or change callback evaluation order.
The installer checks the exact public `elem` and `orb` bodies, sole imports,
Bool/List declarations and representations, original owners and unique getters,
all six generated helpers, cache and installed form. The `orb` dependency is
resolved locally; only the internal `elem_scope` alias enters the closed route
inventory. Generic name hooks and user homonyms keep their existing behavior.
Source, installer and runtime hashes bind the frontend caches. Selected TU
hits replay the installed-body guard; full and packed hits verify signatures
and output hashes. This boundary limits retained work between
saturated calls. It does not bound the peak storage of one traversal, reclaim
caller recursion frames or establish native acceptance.

The C-host tool builder places the canonical `std/crypto.ouro::sha_compress`
in the existing pure binary allocation scope. Each call returns the complete
hash state before releasing the temporary message schedule and round values.
The builder resolves the original source-owned getter and verifies the wrapper
after emission. The SHA-256 algorithm and its inputs stay in Ouro.

### Native lowering and PE validation

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
Inside that plan, a pure Ouro step checks one fixup and returns its complete
patch and next cursor, or the first typed error. Its unary host runner enters
a nested allocation context after the thunk captures its lookup, symbol index,
imports and cursor. It copies new result cells into the caller context and
shares immutable caller-owned inputs before releasing step temporaries.
Bounds, original zero-slot checks, relative origin, target resolution, ordering
and cursor traversal remain in the same Ouro order. The public planner keeps
its signature and patch-list construction. This limits temporary lifetime to
one fixup; it does not bound the cost of an individual fixup.
The current native builder binds this runner to its canonical source closure,
exact step and state declarations, and generated unary body, getter, cache and
export inventory. Changed bodies, owners, layouts or declarations fail before
publication. Source, installer, route and runtime hashes remain in the existing
content-addressed build key.
Patch application, indexed fixup resolution, function scanning and 32-bit field
encoding also run in nested allocation contexts. These boundaries preserve
their complete canonical result and caller-owned inputs while releasing
operation-local temporaries; the host does not implement the PE decisions.

### MIR budgets and validation order

The MIR node, byte, and flow budget ceilings are `pe_byte3_place`. They admit
`native_compiler_limits`. The Ouro checker returns `MirResourceExhausted`
when a requested budget exceeds its ceiling or validation exhausts an active
budget. The C-hosted `mir_check_bounds` adapter checks the same ceilings for
host-representable budgets and calls the canonical Ouro counting and budget
operations. Converting a budget wider than the host integer fails in the C
adapter. [MIR budget definitions](../compiler/native/mir_model.ouro) and
[C host bounds adapter](../runtime/frontend_link.c)

The N1 producer host requires `mir_check_program` to accept the complete
lowered program before GC inference, annotation, GC checking, and
`codegen_checked`. Per-function lifetime callbacks preserve the Ouro checker's
result while reclaiming its temporary allocations. Inside a function, the
canonical type, reachability, and initialized-use callbacks run in nested
allocation contexts. Each callback copies its complete typed result back
before freeing its context. Each instruction's
canonical type judgment also runs in a nested context after its program,
locals and function arguments are supplied. It returns the complete typed
result and borrows those caller-owned inputs. The outer
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
Inside that round, the C host scopes each canonical `mir_predecessor_declared`
call after target, facts, blocks and locals are supplied. It retains the complete
typed list or error in the active round before releasing predecessor temporaries;
all four captures remain live. This changes allocation lifetime, not predecessor
selection, intersection, fact publication, convergence, fuel or error order.
Retained MIR and codegen contexts follow each supplied
argument and are cleared before frontend compilation resets permanent storage.
Neither successful GC annotation nor executable
encoding substitutes for MIR validation. The Ouro
`managed_validate_parts` / `native_emit_image` path retains the same check.
C wraps around `mir_gc_infer`, `mir_gc_annotate`, `mir_gc_check`,
`x64_encode`, `codegen_assemble`, `codegen_parts`,
`codegen_instruction`, `codegen_block`, and `codegen_body` substitute
equivalent host walks for the same Ouro functions so a compiler-sized
image can finish on the C-hosted producer. Liveness facts are computed by the
canonical Ouro solver in a nested allocation context; its complete facts or
typed error are retained before temporary storage is released. Each
Jacobi round similarly retains its complete typed result before releasing
round-local storage; frozen input facts, summary order, convergence and fuel
remain in the canonical solver. Accelerated
function emission runs that same liveness check first for managed-root
functions, preserving unknown-edge and convergence-budget failures.
The wraps around `codegen_live_instructions` and `codegen_clear_dead_roots`
retain each canonical operation's complete result in a nested allocation
context and release its temporary work. Unrecognized instruction shapes
fall back to the generated closures. Managed
allocation and managed-context instructions are included in the
`codegen_instruction` wrap. The wraps do not change which MIR errors
are accepted; they are a host lifetime and time seam, not a second
checker. Progress messages from these wraps are disabled for ordinary generated
programs and explicitly enabled by the diagnostic N1 executable. Failure
diagnostics and exit status are independent of that progress setting.

### Arithmetic and collection bindings

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

Transitional flat tools and split frontend units bind the existing C `add`,
`mul` and saturating `sub` fast paths to the canonical `std/prelude.ouro`
declarations. The subtraction contract requires the complete typed recursive
body and both value curry parameters. Runtime regressions must cover full Nat
values, Peano and packed inputs, saturation and retained partial applications. If
`std/data.ouro` belongs to the ordered source closure, the same installer binds
its exact `compareNat` declaration to the existing C comparison. It checks the
Nat layout and the unrepresented, nullary Ordering constructors `LT`, `EQ`,
`GT` in declaration order. Closures without `std/data.ouro` retain the existing
add/mul/sub contract and do not require that owner.
If `compiler/base.ouro` belongs to the closure, its exact public `eqNat`
body and sole `std/data.ouro` import also bind the existing C equality.
The installer requires the canonical Nat shape and representation and Bool
constructors `True`, `False` in that order with the `ouro.bool` representation.
Closures without that source owner do not receive this equality binding.
The same producer entry point also binds the canonical `std/prelude.ouro`
`length` declaration to the existing C List length operation. This separate
List contract requires the exact body and sole `std/types.ouro` import, the
canonical Nat layout, and List constructors `Nil`, `Cons` in that order with
the `ouro.list` representation. Its Type binder is erased; one value curry
parameter remains. User homonyms retain their bodies. The existing C host
must count compact Lists, concatenation nodes and packed bytes without losing
branches or narrowing the Nat result. The source and generated-family guards
do not establish those runtime properties; focused runtime regressions are
required before this binding is accepted.
The canonical `append` declaration also binds the existing C concatenation
operation under the same Nat and List layout contract. Its Type binder is
erased. The generated fix captures `xs`, then matches `Nil` and `Cons` before
capturing `ys` in each branch. The installer requires that exact getter and
all five helper bodies, including the constructor tag, field order, recursive
self and tail arguments. This binding preserves user homonyms and introduces
no new runtime operation. Concatenation nodes must preserve List element order
and values when unfolded; their runtime laws require behavioral regressions.
The installer checks exact source bodies and imports, ordered source owners,
distinct getters, caches, the required value curry parameters, and complete generated helper
families before publication. Imported private scopes retain the same Nat/List
binding; user definitions with the same names retain their own bodies.
The installer removes the replaced canonical function bodies only when no
remaining generated code refers to them. Raw and already-bound producer forms
must satisfy the same contract. Cache keys bind the selected source owners and
binding helpers; installed cache readback requires the exact bound form.
An unbound fast Nat, List length or append call is rejected. This does not
change checker acceptance or establish native toolchain independence.
The separately pinned historical bootstrap bridge retains its archived
arithmetic bindings. Its regeneration mode has distinct cache keys and is not
exposed by the current tool or frontend CLI.

### Runtime calls and filesystem operations

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

Helper lookup selects a unique checked declaration by exact ordinary spelling
or one canonical `_ouro_m_<decimal>_<name>` spelling. Lexical-only intern names
are ignored; ambiguous candidates and duplicate IDs in identifier or declaration
rows are rejected. A module envelope does not authenticate source ownership;
checked bodies, complete normalized Core types and raw contracts for the same
declaration ID remain required.

Native file adapters use checked `ouro.fs.read_file` and `ouro.fs.write_file`
identities with the existing String/Runtime/Unit types. Their raw helpers use
the same checked-body, complete-pointee and matching-contract requirements.
C host filesystem read/write and string `of_char_codes` are length-based
temporary adapters for native PE emission.
The temporary C host also executes the checked Runtime pure, bind and loop
operations, checked Nat-to-U8/U32/U64 conversion and wrapping U8 subtraction.
These adapters preserve deferred, reusable actions and reject malformed loop
flags; they do not implement Windows extern calls or authorize programs.
Windows handle validity, size queries, binary transfers, reparse attributes,
truncation and close results remain runtime assumptions. The write guard
inspects the opened final component before truncation. File scopes track raw
pages and handles separately from managed roots; process-terminal managed
heap exhaustion is handled by the shared allocator, outside local cleanup.

The additional closed `ouro.fs.read_file_status` identity uses the existing
String, Runtime, Nat and Pair roles; it adds no Core reduction rule or raw
foreign authority. Its entire `String -> Runtime (Pair Nat String)` signature
and the existing raw helper bodies and pointee contracts are checked before
lowering. Native OS status propagation, binary length and cleanup remain
runtime assumptions. Returning a read error requires successful local raw
cleanup; failed close or release remains terminal rather than discarding an
unconsumed owner. Existing primitive equality codes and the archived bridge
are retained. Current P1 compiler roots do not import this stdlib intrinsic;
P2 uses the current registry when checking the stdlib consumers. A new
source-bound bootstrap receipt is still required for a changed registry.

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

### Analyzer execution

The native bounded analyzer entry selects explicit, provisional worker limits:
120 seconds, one CPU and 16 MiB per captured stream. Base and drive workers use
500 MiB and 3072 MiB Windows Job committed-memory caps respectively. Job commit
is a different metric from the retained RSS budgets; these caps do not establish
their parity or native IO acceptance. The existing analyzer precision, memory
and launcher gates remain required. The separate raw base sibling is bound to
`tools/analyze/main.ouro` as `ouro-analyze-base.exe`; the scheduler owns
`ouro-analyze.exe`, avoiding self-dispatch. Exact native analyzer IO owner paths
receive the host-tool layer, while pure policy and basename homonyms retain
their existing restrictions. No primitive identity or checker authority is
added. [Analyzer internals](../tools/analyze/README.md#native-bounded-entry)
own provisioning, policy rationale and the complete host-path inventory.

### Project metadata and evidence

The `trust {}` block in `Ouro.seal` records project intent.
`trust.compiler = "required"` names the active authority. The build
configuration parser rejects the retired `trust.kernel` key. `Ouro.lock`
records resolved package inputs and vendored source digests. The compiler still
checks every declaration and imported body before accepting the program.
[Package seal](pkg.md#seal) and [lockfile verification](pkg.md#lockfile-and-verification)

Source buffers, display paths, analyzer facts, cache manifests, executable
bytes, and host reports remain outside the pure declaration checker. The
runtime, code generator, C compiler, and bootstrap seed remain part of the
current execution and compilation assumptions. A correct declaration judgment
alone cannot prove their implementation correct.

OuroSmith generates typed Core and exercises the canonical checker. Its
construction laws, known rejections, source mutants, and independent
surface/runtime expectations are regression evidence. It contains no required
second Core interpreter. Surface runtime object reuse goes through the existing
checked C object cache; source/dependency, command, compiler executable, object,
and depfile hashes bind reuse. Each generated sample still compiles, links, and
runs under the same bounded process-tree limits. This preparation does not
authorize generated C or replace compiler-owned acceptance. The former OCaml
and Python replay owners are retired;
their historical schema and corpus are documented in
[Core artifacts](kernel_core_artifact.md).

### Executable path and timed actions

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

### Child process guarantees

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

The additional closed `ouro.process.capture_bounded_at` identity has code 275;
existing codes and the three-argument bounded-capture ABI stay unchanged. Its
four-argument signature and ordinary Runtime helper body require the same full
declaration, pointee, GC and lowering checks. The child cwd uses existing owned
argument storage and the accepted `CreateProcessW` directory parameter with
existing process authority. It adds no OS import, shell or parent cwd mutation.
This is a runtime/primitive contract addition; it supplies neither compiler
acceptance nor whole-analyzer evidence. The runtime contract covers checked
directory validation and terminal cleanup limits.
[Bounded capture with a child directory](effects_design.md#bounded-capture-with-a-child-directory)

### Managed heap observations

The closed `ouro.managed.allocated_requested_bytes` identity has append-only
code 276 and exact type `Runtime (Maybe Nat)`. It is an effectful, allocating
action; ordinary source receives no context pointer or mutable metadata.
Compiler-owned lowering obtains the current context through `MirManagedContext`
when the deferred action runs. Its ordinary raw helper must have a checked
body, complete `RawPtr U8 -> Runtime USize` type and the corresponding raw
lowering contract. Full import/declaration checking, replay, role validation,
fuel limits and MIR/GC validation remain required. A name, axiom or foreign
binding alone cannot authorize that helper. The maintained native allocator,
sweeper and readonly helper are runtime correctness assumptions; type checking
does not prove the accounting invariant or a substituted helper's semantics.

The native helper captures context word 3 (byte offset 24) before boxing the
result with exact USize-to-Nat conversion. It performs no allocation, mutation,
collection, heap traversal or callback. Its constant-time ownership/accounting
sanity checks use the existing terminal runtime invariant failure 73. They do
not independently recompute the complete allocation list. `Just bytes` counts
currently allocated managed-object requested bytes, including headers and
unswept objects. OS heap overhead, raw storage, frames, context/descriptor
storage and static data are excluded; reachability, RSS, process peak commit
and cumulative allocation are different quantities.

The transitional C adapter returns typed `Nothing`, never a zero measurement.
The C structural-worker hook continues to report its existing arena bytes;
that lifetime owner and all numerical budgets remain unchanged. The two
metrics have no claimed parity. [Session lifetime](clippy_grade_firewall.md#session-lifetime-boundary)
owns their consumer and acceptance limits. This primitive adds a readonly
runtime observation contract, not compiler program-acceptance authority,
native-stage evidence or a replacement for the C lifetime owner.

## Guardrails

Hardening requires all retained laws across uncached, fresh cached, and reused
cached executables, with source and producer receipts and a per-run budget.
The scale and depth profiles require complete probe protocols, current inputs,
and exact typed results. Crashes, timeouts, missing rows, and stale receipts
cannot satisfy these contracts. [CI](ci.md#local-profiles) owns their commands
and required profiles.

## Assurance limits

Accepted declarations are well-typed under the implemented rules and explicit
assumptions. This does not establish an axiom's truth, the user's intended
behavior, foreign-code safety, GC correctness, or a formal proof of the
compiler's metatheory. Native self-hosting and matching stage bytes establish
rebuild behavior only when those stages actually run; they do not prove
compiler correctness.
