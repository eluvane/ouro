# Architecture

The declaration checker validates source compilation and evaluation before
either can extract executable code. The bootstrap path emits C. The direct
Windows backend and Ouro runtime implement parts of the
[target native toolchain](design.md#native-toolchain-contract).

## Main layers

```text
Ouro source and complete import closure
  -> canonical source, parsing, elaboration, and lowering
  -> ordered Core declarations
  -> compiler-owned declaration checking
  -> CheckedProgram
  -> extraction and C emission -> C compiler + repository runtime
  -> or direct native lowering -> MIR -> x86-64 + PE32+
```

The C and Windows paths consume checked declarations. A successful parser,
generated file, cache lookup, or tool wrapper cannot establish acceptance.
Direct native lowering also validates supplied checked-program metadata before
using it. Backend and runtime behavior require execution tests in addition to
typechecking.

## Source and frontend

User programs, compiler modules, and tools are `.ouro` files. Source handling
lives in `lexer.ouro`, `parser.ouro`, `source_text.ouro`, and
`canonical_source.ouro`. Import collection and declaration ownership live in
`import_resolve.ouro` and `module_registry.ouro`; `module_names.ouro` resolves
references with lexical binder scope. Elaboration, lowering, and declaration
checking live in `elab.ouro`, `lower.ouro`, and `file_elab.ouro`.
`driver.ouro` and `pipeline.ouro` compose the stages.

The frontend preprocesses import aliases, exposing clauses, and records
before lexing and parsing. The module resolver binds internal qualification
markers to directly imported units. The frontend rejects those markers in
raw source. See [canonical source](canonical_source.md) for directive
metadata, source mapping, and hash inputs.

The C-hosted multi-file frontend carries two spelling indexes across the units
in one compilation. Identifiers, string literals, source paths, and resolved
import paths extend the indexes and their ordered intern tables together.
Lexer callers that pass an `InternState` derive their indexes from its ordered
tables on each call. Both interfaces preserve assigned IDs and the first entry
for duplicate keys.

The parser uses the same `parse_a.ouro` / `parse_b.ouro` mode helpers and
`parser_min.ouro` ABI as split bootstrap compilation. Its dispatcher owns the
recursive fuel boundary. The module resolver gives colliding declarations
distinct identities, and isolates all imported declarations when a selective
edge is reached. It computes visible names from each file's import edges;
selective edges filter direct declarations while plain edges inherit the
target's visible names. This scope does not shrink the ordered import closure.
The checker still receives every reached imported declaration and body.
Import resolution bounds graph traversal with `resolve_imports_fuel`; the
default budget is 256. Ordinary declarations are collected structurally and do
not consume this graph budget. Exhaustion reports the next unit path rather
than returning a partial closure.
The resolver's `resolve_imports_with_sources` result attaches the owning
canonical unit ID while that same DFS appends each local declaration. Its
declaration projection and `resolve_imports_fuel` retain the existing order,
cycle, missing-unit and exhaustion results.
[Compiler checking](kernel_design.md) defines the complete declaration plan
and import-closure checks.

The split frontend consumes the typed source failure envelope from
`compile_checked_from_decls_with_origin`. The compiler records the actual
failing resolved declaration, its occurrence and the preflight phase without
compiling it again. The envelope retains the original `CompError`; successful
depth fallback removes the preliminary failure before full declaration
checking. A valid list earlier in the closure cannot classify an unrelated
generic lowering refusal as `OURO-LIST-001`. That refusal keeps code 2 and its
original detail. A producer-known root list refusal still renders
`OURO-LIST-001`; a direct named hole retains `OURO-HOLE-001`.

Root causes currently cover the four list-context refusals and direct named
holes. Nested causes, inference results that are discarded, and failures from
later declaration checking carry no invented lower cause. The compatibility
failure producers leave their span `Nothing`; the renderer prints the known unit and declaration without a
line/column guess. `driver.compile_checked_units_with_origin` returns the
envelope beside its intern table. `driver.compile_checked_source_with_origin`
serves the byte-only source caller; that caller has no file-path argument, so
its ordinary unit is `Nothing` and the renderer labels it `<input>`.
The legacy source drivers and ergonomic
remap APIs retain their compatibility diagnostics; they do not provide this
source-origin contract. Propagating nested lower traces remains separate work.

The opt-in `driver.compile_checked_units_with_source_origins` uses the same
record emission, visibility parsing, import resolution and complete checking
loops, and returns the unchanged source result and intern table beside a typed
origin sidecar. Sparse regions come from actual record and body-rewrite
boundaries; parser occurrences cover whole declarations, including visibility
prefixes. Record-generated accessors retain the original record envelope.
An original-byte interval is exposed only for a unique existing unit/slot
relation. Ambiguity stays `Nothing`; malformed metadata is a separate
`SourceOriginError`, leaving the original compiler result available. Lexing,
parsing and resolution failures without a declaration owner still have no
invented span. This sidecar does not publish native function addresses or
establish closure parentage, and current tool renderers retain their existing
span behavior.

`scripts/ouro1.sh` is the maintained command wrapper; `scripts/coil.sh` exposes
the project-facing verbs. Project defaults and package identity live in
`Ouro.seal`. These launchers still use the transitional host build machinery.

## Checking and checked data

`compiler/file_elab.ouro` checks ordered declarations into an environment built
from accepted predecessors. [Compiler checking](kernel_design.md) owns the rules
and typed failures; [TCB](tcb.md#compiler-checking-boundary) owns its pure
dependency boundary.

`CheckedProgram` carries declarations and emission metadata to both backends.
[Core artifacts](kernel_core_artifact.md) defines its diagnostic snapshot and
the archived JSON replay format.

Prepared tool stages bind reusable data to the inputs that produced it. The
source collector owns the [build snapshot](build.md#memory-behavior), the
analyzer prepares its global and file-local reference indexes together, and
the fixer shares the tokens for each source version across its planner and
certificate checks. Their public input types hide the constructors, so callers
have to use the producer before passing a value to a later stage.

## Backends and runtime

### Transitional C path

`extract.ouro`, `backend.ouro`, and `print_c.ouro` implement the transitional C
path. `runtime/` contains its value, memory, IO, process-entry, and split
frontend adapters. Its allocation banks and phase lifetimes do not establish
a garbage-collected native heap.

### Direct Windows backend

`compiler/native/` implements checked lowering, MIR validation, x86-64
encoding, and PE32+ writing. Ouro modules under `runtime/` and
`runtime/platform/` provide the raw and managed runtime.

### Windows heap and liveness

The managed heap uses exact, non-moving mark-and-sweep collection with typed
object descriptors and shadow roots. Each context lazily owns one growable
Windows private heap. `HeapAlloc` supplies zeroed blocks, and `HeapFree`
reclaims unreachable blocks. Small objects share OS pages. `HeapDestroy`
returns the heap's pages when the allocation list is empty and the object
count and requested-byte total are both zero.
The owner handle is cleared only after successful destruction. Raw buffers
and collector scratch retain their separate `VirtualAlloc` ownership.

Call-graph checks propagate allocation effects; backward liveness
clears dead managed slots before allocation and calls that may collect.
Liveness computes ordered per-block GEN/KILL and successor summaries once, then
iterates over previous-round facts. It preserves the exact fixed point, fact
ordering, unknown-edge errors and fuel exhaustion; incomplete facts cannot
authorize removing roots. Indexed MIR loads and stores read the object owner
and unsigned byte offset separately. Liveness retains the owner through
preceding safepoints. The temporary machine address exists only during the
memory instruction.

After validating the full heap, collection indexes its exact allocation bases
in bounded raw scratch storage. Marking uses that index and still validates
each found object and its mark state. Standalone inspection and the original
scratch-buffer entry point keep their list scans. Full checks before and after
collection and cleanup after failed release remain. Unrepresentable scratch
sizes or failed reservations report failure before changing the heap.

Allocation sites retain their `MayGc` effect and clear dead roots before
checking a runtime budget. A due allocation calls the existing collector and
requires exactly `True` before entering the allocator. Direct `managed_collect`
calls always perform full collection. Successful collection grants the larger
of 1 MiB and the post-sweep live requested bytes plus a conservative 4 KiB
accounting charge per live object. Successful allocations consume their
requested bytes plus the same charge. The charge accounts for allocations
independently of OS page size. A request exceeding the remaining budget
collects first. A single large request can exhaust that budget, making the
following allocation collect again.

Accounting overflow and failed collection remain errors. The private context
keeps its existing prefix and descriptor offsets. The descriptor table is
followed by a zero budget word and a zero private-heap handle word; the first
allocation collects and acquires an owner lazily. Raw clients reserve both
footer words. Footer arithmetic checks the complete final word for overflow.
The collector checks roots and heap state on each collection. It can detect
corruption introduced between collections on the next collection.

### Windows calls and value representations

A call with up to four arguments can reuse the current frame when its
continuation only copies and returns its result. This path unlinks the
shadow frame and uses a Windows-recognized tail-jump epilog; calls with
stack arguments or further computation retain ordinary call/return.
Constructors, closures, partial application, and deferred `Runtime` actions use
this heap, including checked Windows externs passed as function values.
String intrinsics used as values are eta-expanded from their normalized checked
signatures, rechecked, and passed through ordinary managed closure conversion.
Partial applications use those closures; saturated calls keep direct intrinsic
lowering. Selection follows registered identities, not source spelling.
The registered `Nat` representation stores variable-length unsigned limbs;
successor, predecessor, machine-word conversions, and decimal rendering retain
values beyond 64 bits. Native addition with either operand zero and subtraction
of zero reuse the unchanged immutable operand after validating both inputs.
Machine-word arithmetic keeps its separate width and overflow contracts.
Exact checked Nat addition, subtraction, equality, and comparison bodies can
select operations over complete limb values. Other bodies keep ordinary
lowering. Display names do not authorize this specialization.
Exact checked multiplication, division and remainder bodies also have bounded
machine-word execution paths. Multiplication requires two U32 operands and
returns the full U64 product. Division and remainder require U64 operands.
Zero divisors and values outside those ranges execute the original checked
source body. Recognition includes the exact addition, subtraction, comparison
and Boolean dependencies used by that body.

Strings store an explicit byte length, preserving NUL and
non-UTF-8 bytes through access, slicing, search, replacement, splitting, and
byte-list conversion. These operations preserve checked representation
identities and keep source objects rooted while allocating their results.
Native byte equality compares complete eight-byte blocks, then the remaining
bytes. The loads retain their owners and stay within the checked byte range,
including unaligned search positions.

### Windows IO and platform adapters

See the [runtime surface](effects_design.md#runtime-surface) for user-facing
behavior and the [trusted boundary](tcb.md#current-host-assumptions) for host
assumptions.

`IO A` is a transparent alias of `Runtime A`; ordinary `io_pure` and `io_bind`
wrappers retain their public types. The standard library and raw runtime share
the same data-type identities through the declarations in `std/types.ouro`.
The raw vocabulary imports that module without executable standard-library
helpers. Managed entry accepts `U32`, `Runtime U32`, or
`Runtime Unit`; completing a Unit action returns status zero after cleanup.
`runtime_loop` evaluates its test and step actions at each iteration and keeps
the current managed state rooted. Standard output, error output, flush, and
process exit have checked action identities. The native stream adapter copies
bounded chunks into raw staging storage, preserving source roots until the
synchronous write completes and releasing staging storage after failure.
Standard input actions allocate their managed result before acquiring one
bounded raw staging page. They copy only initialized input bytes, retain
the result as a GC root, and release staging after success or failure.
The checked clock action reads Windows UTC when executed, releases its raw
buffer, and converts FILETIME to decimal Unix-epoch milliseconds in Ouro.
Realpath actions open the current target when executed, resolve its final
Unicode path, remove the exact Windows extended prefix, and normalize path
separators to `/`. The result remains a GC root through handle and raw-page
cleanup. Missing paths and other OS unavailability return an empty String;
failed raw contracts, text conversion and incomplete reads exit with 73.
Argument and environment actions copy strictly converted Windows text into
managed strings and containers, with explicit raw-storage cleanup. Remaining
host operations require their own native bridge and report unsupported when
that bridge is absent.

The raw Windows adapters provide page ownership, UTF-8/UTF-16 conversion,
files, directory enumeration, command-line arguments, environment, current
directory, and clocks. They return explicit status codes and use caller-owned
storage. Their unsafe pointer and handle lifetime contracts remain explicit
at each API; range checks cannot prove ownership of arbitrary addresses.
Process creation takes an explicit executable, argument vector, environment,
working directory, and standard handles. It uses an explicit inheritance list;
capture uses temporary files, with wait, direct-child cancellation, and close
operations that retain ownership when closing fails.

Native fixtures exercise these operations through the Windows loader,
including collector reclamation across calls and loops. Coverage remains
narrower than the general compiler and toolchain surface. Native compiler
bootstrap and sustained compiler workloads require separate completion
evidence.

### Experimental Linux backend

`compiler/native/elf.ouro` provides a bounded, freestanding Linux x86-64 ELF64
text writer. `codegen_linux.ouro` accepts checked raw scalar MIR with concrete
System V calls and image-local data through `elf_data.ouro`. Read-only and
writable objects have separate non-executable segments. The backend rejects
imports, managed operations, and frames of 4096 bytes or more. The dedicated
`native_compile_linux_units` entry point compiles this subset. CLI target
dispatch, the Linux runtime, and a native seed remain outside the slice.
[Linux source lowering](../compiler/native/lower_linux_source.ouro)

## Systems contract support

This inventory describes the experimental pre-1.0 systems slice. `CON-BASE-01`
ties each checked identity to its lowering and the evidence needed at execution.
The proposed resource and memory rules have their own acceptance criteria.
[Systems proposal](design.md#proposed-systems-foundation) ·
[Decision record](rfc/README.md#systems-design-decisions)

### Checked identities

The declaration checker resolves an `intrinsic` by registry key, checks its
signature against registered primitive types and representation roles, and
retains any normalized specialization with the checked binding. An `extern`
retains the checked target, ABI, library, symbol, GC policy, and concrete scalar
signature. Native lowering replays the ordered declarations and binding metadata
before deriving MIR. A matching source name confers no binding authority.
[Source syntax](syntax.md#experimental-native-declarations) ·
[Declaration checker](../compiler/file_elab.ouro) ·
[Primitive checking](../compiler/primitive_check.ouro) ·
[Native replay](../compiler/native/lower_boundary.ouro)

Machine-word computations and typed null are `PrimitivePureValue`. Type
conversion treats these values, externs, and `PrimitiveRuntimeAction` terms as
opaque. `PrimitiveNoGc` describes the scalar operation. Managed boxing and
action construction can allocate, so the backend derives safepoints from MIR.
[Primitive contracts](../compiler/primitive_contracts.ouro) ·
[Primitive model](../compiler/primitive_model.ouro) ·
[MIR call effects](../compiler/native/mir_gc.ouro)

### Machine words

The `PrimitiveTypeOnly` keys `ouro.u8`, `ouro.u32`, `ouro.u64`, `ouro.i32`, and
`ouro.usize` select 8, 32, 64, 32, and 64 bits in the current x86-64 slice. Only
`I32` is signed. `W` below is one of these registered types, and `w` is its
registry spelling. Source numeric literals produce mathematical `Nat` values.
[Shared vocabulary](../runtime/native_types.ouro) ·
[Signature templates](../compiler/primitive_registry_base.ouro) ·
[Number syntax](syntax.md#numbers-and-strings)

| Registry key and checked signature | Result and failure | Lowering and MIR |
| --- | --- | --- |
| `ouro.w.add.wrap`, `sub.wrap`, `mul.wrap`, `and`, `or`, `xor` use `W -> W -> W`. `shl`, `shr` use `W -> U32 -> W`. `eq`, `lt` use `W -> W -> Bool`. | Wrapping arithmetic keeps the low bits. Shifts mask their count by the width minus one. Right shift and less-than use signed semantics for `I32`. These keys have `PrimitiveNoGc` metadata. | `lower_binary` emits `MirBinaryOp` or `MirCompare`. Managed `managed_word_operation` unboxes inputs and represents the result as a managed value. The x64 encoder selects operand width, shift kind, and comparison condition. [Scalar lowering](../compiler/native/lower_ops.ouro) · [Managed words](../compiler/native/managed_word.ouro) · [x64 emission](../compiler/native/codegen_ops.ouro) |
| `ouro.w.add.checked`, `sub.checked`, `mul.checked`, `div.checked`, `rem.checked` use `W -> W -> Maybe W`. | The registry checks the `Maybe` role and assigns `PrimitiveMayGc`. The checked contract calls for `Nothing` on overflow, a zero divisor, or `I32` minimum divided by `-1`. | Managed Windows implements checked `USize` addition with `MirBinaryOp MirAdd`, an unsigned comparison, and a `MirBranch` to build the registered `Maybe`. The remaining managed identities and all scalar checked arithmetic keys return `LowerUnsupportedPrimitive`. MIR `MirDiv` and `MirRem` have separate x64 trap guards. [Managed words](../compiler/native/managed_word.ouro) · [Scalar lowering](../compiler/native/lower_ops.ouro) · [Division trap cases](../tests/native_mir_tests.ouro) |
| `ouro.convert.src.dst.narrow.wrap`, `zext`, `sext`, `reinterpret` use `Src -> Dst`. `ouro.convert.src.dst.checked` uses `Src -> Maybe Dst`. | The registry checks widths and signedness for truncation, extension, and equal-width reinterpretation. Checked conversions between distinct word types have `PrimitiveMayGc` metadata. The other modes have `PrimitiveNoGc` metadata. | `lower_conversion` emits `MirConvert` for unchecked modes. Managed Windows also implements checked `USize -> Maybe U32` with the `U32` upper bound and a branch to the registered `Maybe`. Remaining managed checked conversions and all scalar checked word conversions return `LowerUnsupportedPrimitive`. [Conversion rules](../compiler/primitive_contracts.ouro) · [Scalar lowering](../compiler/native/lower_ops.ouro) · [Managed words](../compiler/native/managed_word.ouro) |
| `ouro.w.from_nat.checked` uses `Nat -> Maybe W`. `ouro.w.to_nat.bits` uses `W -> Nat`. | Out-of-range `Nat` gives `Nothing`. Conversion back interprets `I32` as unsigned bits. Both keys have `PrimitiveMayGc` metadata. | `lower_from_nat` reduces a bounded constant `Nat` for local `Maybe` elimination with a typed `MirBits` payload. The scalar path supports only this constant conversion. Managed Windows supports both keys for dynamic values, using guards and a branch for `Maybe` and preserving all word bits on return to `Nat`. [Scalar constants](../compiler/native/lower_constants.ouro) · [Managed words](../compiler/native/managed_word.ouro) · [Managed `Nat`](../compiler/native/managed_nat.ouro) |

### Raw pointers, calls, and actions

`ouro.raw_ptr`, `ouro.raw_fn`, and `ouro.runtime` are `PrimitiveTypeOnly` keys
for constructors of kind `Type -> Type`. Scalar lowering classifies `Runtime`
as an action and retains normalized pointee and function signature types when
selecting `MirRawPtr` for raw values.
Storage specialization uses the same classifier as the scalar ABI. `RawPtr A`
describes an address with pointee type `A`. The caller must justify access to
the complete width of the storage, its required alignment, lifetime and
read or write permission. Reads require initialized storage. Raw instructions
provide no typed address-failure result.
[ABI and storage registry](../compiler/primitive_registry.ouro) ·
[Native scalar types](../compiler/native/lower_types.ouro)

| Registry key or declaration | Checked signature and effect | Lowering and representation |
| --- | --- | --- |
| `ouro.raw.null` | `(A : Type) -> RawPtr A`. Pure typed zero address with `PrimitiveNoGc` metadata. | `lower_raw_null` emits `MirBits MirRawPtr` zero. The managed path boxes zero as a raw pointer payload. [Scalar raw lowering](../compiler/native/lower_raw.ouro) · [Managed pointer boxing](../compiler/native/managed_actions.ouro) |
| `ouro.raw.add.wrap` | `(A : Type) -> RawPtr A -> USize -> Runtime (RawPtr A)`. Adds bytes modulo 2^64. | `lower_raw_add` and `managed_raw_add` emit `MirPointerAdd`; x64 adds the offset to the base. [Scalar raw lowering](../compiler/native/lower_raw.ouro) · [Managed raw lowering](../compiler/native/managed_raw.ouro) · [x64 emission](../compiler/native/codegen_ops.ouro) |
| `ouro.raw.cast` | `(A : Type) -> (B : Type) -> RawPtr A -> Runtime (RawPtr B)`. Preserves the address bits. | `lower_raw_cast` retains the scalar value under the checked result type. `managed_raw_cast` wraps the existing pointer value in a deferred action. [Scalar raw lowering](../compiler/native/lower_raw.ouro) · [Managed raw lowering](../compiler/native/managed_raw.ouro) |
| `ouro.raw.to_bits`, `ouro.raw.from_bits` | `(A : Type) -> RawPtr A -> Runtime USize` and `(A : Type) -> USize -> Runtime (RawPtr A)`. Preserves bits without an allocation identity or permission. | `lower_raw_bits` and `managed_raw_bits` emit `MirConvert MirRawToBits` or `MirRawFromBits`. x64 transfers the bits without changing them. [Scalar raw lowering](../compiler/native/lower_raw.ouro) · [Managed actions](../compiler/native/managed_actions.ouro) · [x64 emission](../compiler/native/codegen_ops.ouro) |
| `ouro.raw.load`, `ouro.raw.store` with specialization `T` | `RawPtr T -> Runtime T` and `RawPtr T -> T -> Runtime Unit`. `T` resolves to a word, raw pointer, or concrete `RawFn`. | `lower_raw_load`, `lower_raw_store`, and `managed_raw_storage` emit `MirLoad` or `MirStore` at displacement zero. Operand types select 1, 4, or 8 bytes for ordinary x64 loads and stores. [Scalar raw lowering](../compiler/native/lower_raw.ouro) · [Managed raw lowering](../compiler/native/managed_raw.ouro) · [x64 emission](../compiler/native/codegen_ops.ouro) |
| `ouro.fn.call` with specialization `S` | `RawFn S -> S` for a concrete nondependent telescope `S` of scalar arguments ending in `Runtime R`. `R` is a scalar or the registered `Unit`. The address must designate a live callable with the selected ABI and signature. Calls are `PrimitiveMayGc`. | `lower_fn_call` and `managed_fn_call` derive a concrete `MirSignature` and a `MirCall` with `MirIndirect`. The ABI backends select the argument and result locations. The managed path defers invocation in an action. [Scalar raw lowering](../compiler/native/lower_raw.ouro) · [Managed raw lowering](../compiler/native/managed_raw.ouro) · [Win64 calls](../compiler/native/codegen_ops.ouro) · [System V calls](../compiler/native/sysv_call.ouro) |
| `ouro.runtime.pure`, `ouro.runtime.bind`, `ouro.runtime.loop` | `(A : Type) -> A -> Runtime A`, `(A : Type) -> (B : Type) -> Runtime A -> (A -> Runtime B) -> Runtime B`, and `(A : Type) -> A -> (A -> Runtime U8) -> (A -> Runtime A) -> Runtime A`. All have `PrimitiveMayGc` metadata. | Scalar `pure` keeps the returned value, `bind` sequences a saturated action with a lambda, and `loop` initializes state and emits a `MirBranch` before each step. A zero condition returns the current state. Managed actions capture values and invoke the action bodies when run. The loop carries no termination or single-use guarantee. [Scalar sequencing](../compiler/native/lower_ops.ouro) · [Scalar loops](../compiler/native/lower_loop.ouro) · [Managed actions](../compiler/native/managed_actions.ouro) · [IO surface](effects_design.md#runtime-surface) |
| `extern` with `windows-x86_64`, `win64` | Concrete nondependent scalar arguments and a scalar or registered `Unit` inside `Runtime`. The registry requires bounded nonempty ASCII library and symbol fields and a nonvariadic signature. `nogc` is a foreign contract and `maygc` permits collection. | `lower_libraries` retains `MirExtern` signatures and mappings. Raw calls are direct. Managed `managed_external` defers the call until invocation and adapts boxed arguments and results. x64 emits Win64 argument placement and a PE import call. A correct foreign implementation and its declared policy are caller obligations. [Extern registry](../compiler/primitive_registry.ouro) · [Import lowering](../compiler/native/lower.ouro) · [Managed extern lowering](../compiler/native/managed_extern.ouro) · [PE imports](../compiler/native/pe_imports.ouro) |

Raw add, cast, bit conversion, load, and store have metadata
`PrimitiveRuntimeAction` and `PrimitiveNoGc`. For a live byte buffer,
`raw_buffer_range` checks that the range fits the supplied capacity. For a
nonempty range, it rejects a null base or an address calculation that wraps.
The caller owns the allocation and supplies its true capacity.
[Raw buffer helpers](../runtime/raw_buffer.ouro) ·
[Primitive effects](../compiler/primitive_contracts.ouro)

### Layout and managed roots

`primitive_validate_layout` checks a supplied `PrimitiveRawLayout` and returns
`Either PrimitiveError PrimitiveCheckedLayout`. It requires a positive size at
most 2^31 minus one, a power-of-two alignment through 4096, and a size divisible
by that alignment. Fields have unique IDs and ordered nonoverlapping ranges.
Bounds use `offset <= size` and `width <= size - offset` before calculating the
end. Unpacked fields require offsets divisible by the scalar width and aggregate
alignment at least that width. Packed fields bypass just those field alignment
checks. Invalid sizes, alignments and field ranges yield `PrimitiveInvalidLayout`.
The validator also rechecks normalized ABI field types. Production source
declarations and MIR currently have no raw aggregate layout consumer.
[Layout validator](../compiler/primitive_registry.ouro) ·
[Alignment rules](../compiler/primitive_contracts.ouro) ·
[Layout cases](../tests/compiler_primitive_registry_tests.ouro)

In the Windows managed heap, a raw pointer box is a managed object whose address
payload is untraced. The box can be rooted and gives no ownership of the storage
the payload points to. `MirRawToBits`, `MirRawFromBits`, and `MirPointerAdd` use raw
pointers. Managed indexed access keeps the `MirManagedPtr` owner and `MirUSize`
offset as separate operands of `MirLoadAt` or `MirStoreAt`. Liveness keeps a
needed owner rooted across a preceding safepoint. Code generation computes the
effective address inside the memory instruction. The collector uses typed
descriptors and shadow roots. It traces only owned managed objects. The Windows
private heap stores managed objects, and the collector uses a separate raw page
reservation for its worklist.
[MIR types](../compiler/native/mir_types.ouro) ·
[Liveness](../compiler/native/mir_live.ouro) ·
[Shadow roots](../compiler/native/codegen_roots.ouro) ·
[Runtime roots](../runtime/managed_roots.ouro) ·
[Mark worklist](../runtime/managed_mark.ouro) ·
[Managed heap trust](tcb.md#native-windows-managed-heap)

### Verification and expected rejection

Case names and fixture paths identify intended assertions. Execution evidence
identifies the revision, host, producer, target, command and observed outcome.
Record `pass`, `fail`, `not-run`, `unsupported`, and `resource-limit` separately.
A resource limit, timeout, or skipped probe leaves the obligation open. A
negative case passes when it reports the expected failure at its owning phase.
[Validation matrix](ci.md#validation-matrix) ·
[Reports and failures](ci.md#reports-and-failures)

| Verifier | Positive and negative assertions | Evidence boundary |
| --- | --- | --- |
| Source checker and binding replay | `compiler_primitive_registry` checks canonical roles, ABI and layout. `compiler_primitive_binding` checks integration with declaration checking. `native_lower` exercises concrete adapters and rejects generic raw storage, wrong pointees or widths, dependent call signatures, and attempts to use an action as a pure result. Forged primitive metadata fails replay. Invalid primitive metadata yields `CheckPrimitiveFailure`, signature conversion can yield a type failure, and exhausted registry fuel yields `CheckResourceLimit`. [Registry cases](../tests/compiler_primitive_registry_tests.ouro) · [Binding cases](../tests/compiler_primitive_binding_tests.ouro) · [Lowering cases](../tests/native_lower_tests.ouro) | Complete import checking, normalized binding identities and typed rejections. |
| Native lowering and MIR | Checked-word fixtures in `native_managed_phase` inspect the guarded `Maybe` control flow, payload roots and `LowerUnsupportedPrimitive`. `native_mir`, `native_gc`, and `native_live` cover operand types, call shape, initialized MIR locals, and safepoints. The verifiers reject examples of `MirTypeMismatch`, `MirInvalidCall`, `MirUninitialized`, and false `NoGc` claims. MIR local initialization concerns compiler temporaries. [Checked words](../tests/native_word_checked_fixtures.ouro) · [MIR validator](../compiler/native/mir.ouro) · [Indexed memory cases](../tests/native_indexed_memory_tests.ouro) · [GC cases](../tests/native_gc_tests.ouro) · [Live roots](../tests/native_live_tests.ouro) | MIR and GC metadata, including a replay before code generation. Heap initialization and foreign ABI behavior require separate evidence. |
| Machine code and image validation | `native_mir` checks x64 byte vectors and generated PE images. `native_pe` exercises import, fixup, frame and layout checks. `native_linux_source`, `native_sysv`, and `native_elf_data` cover source-to-ELF, the scalar ABI and ELF segments. The Linux source fixture requires `LinuxImportsUnsupported` for even an unused Win64 extern, and checks rejection of unsupported source operations. [PE cases](../tests/native_pe_tests.ouro) · [Linux source cases](../tests/native_linux_source_tests.ouro) · [System V cases](../tests/native_sysv_tests.ouro) · [ELF data cases](../tests/native_elf_data_tests.ouro) | Image emission and validation. Observe generated executables on the corresponding target for behavior. |
| Runtime, GC and FFI | The Windows frontend host suite emits and runs native RawFn, heap observation and liveness cases. The probes check deferred effect ordering, process status and streams, and exercised allocation and collection behavior. The C host has separate runtime selftests for its bound word operations and action sequencing. [Windows host probes](../scripts/frontend_host_suite.py) · [C runtime selftests](../runtime/ouro_io_selftest.c) | Target behavior on exercised paths. Keep evidence of faults and sustained reclamation alongside successful paths. |

The [compiler suite catalog](../tools/test/suites.ouro) registers the named
compiler cases. The [systems validation plan](design.md#systems-validation)
owns the proposed positive and negative scenarios. Their current owners are
as follows.

| Requirement and contract | Current owner and model obligation |
| --- | --- |
| `REQ-MEM-IDENTITY` / `CON-MEM-IDENTITY` | The memory model tracks allocation identity across free and address reuse. Managed collector exact-base tracking applies to its own heap and current allocation list. Raw pointer bits have no allocation identity. [Memory model cases](../tests/compiler/systems/memory_model_tests.ouro) |
| `REQ-MEM-BOUNDS` / `CON-MEM-BOUNDS` | `raw_buffer_range` checks capacity for byte-buffer callers. The layout validator checks static field extents. The memory model requires the full scalar access to fit a live allocation. [Raw buffer helpers](../runtime/raw_buffer.ouro) · [Memory model cases](../tests/compiler/systems/memory_model_tests.ouro) |
| `REQ-MEM-ALIGN` / `CON-MEM-ALIGN` | The layout validator checks field offsets. The memory model rejects a misaligned typed access. Raw loads and stores rely on their caller's storage contract. [Layout checks](#layout-and-managed-roots) · [Memory model cases](../tests/compiler/systems/memory_model_tests.ouro) |
| `REQ-MEM-INIT` / `CON-MEM-INIT` | `mir_flow` checks local definitions before use. The memory model tracks initialized bytes and a typed load's complete width. [MIR flow](../compiler/native/mir_flow.ouro) · [Memory model cases](../tests/compiler/systems/memory_model_tests.ouro) |
| `REQ-RES-UNIQUE` / `CON-RES-UNIQUE` | `RawPtr` carries no ownership. The resource model tracks unique ownership, moves and loans with explicit state. [Resource model cases](../tests/compiler/systems/resource_model_tests.ouro) |
| `REQ-ACTION-ONCE` / `CON-ACTION-ONCE` | Managed and hosted `Runtime` actions can run repeatedly. The resource model checks single consumption for actions with owning captures. [Resource model cases](../tests/compiler/systems/resource_model_tests.ouro) · [Managed reuse case](../tests/native_managed/source_loop_reuse.ouro) |
| `REQ-PURE-BOUNDARY` / `CON-PURE-BOUNDARY` | The pure checker keeps runtime operations and loops opaque. The proposed checker must apply that boundary to systems obligations over immutable indices. [Pure closure](tcb.md#pure-dependency-closure) · [Systems checking](design.md#scope-and-checking) |
| `REQ-ERASE-RELEVANCE` / `CON-ERASE-RELEVANCE` | Checked erasure prepares normalized type arguments for emission. The proposal also requires a relevance check and a simulation showing that witness erasure preserves runtime results and effects. [Checked erasure](../compiler/erasure_checked.ouro) · [Systems validation](design.md#systems-validation) |
| `REQ-TRUST-DEPENDENCY` / `CON-TRUST-DEPENDENCY` | Compiler checking accepts explicitly declared axioms as assumptions. The proposed systems trust policy must reject a disallowed transitive axiom at a strict safety root and identify the dependency chain. [Current assurance limits](tcb.md#assurance-limits) · [Systems trust](design.md#systems-trust) |
| `REQ-LOWER-NO-UB` / `CON-LOWER-NO-UB` | Scalar and managed lowering and target emitters already reject unsupported mappings. The proposed contract requires a simulation from defined model steps through MIR and the target, including rejection before any unsupported operation executes. [Native replay](../compiler/native/lower_boundary.ouro) · [Systems validation](design.md#systems-validation) |

### Stages and targets

| Stage or target | Implemented slice | Required evidence |
| --- | --- | --- |
| Source checking on a C host or with native `coil` | The Ouro checker accepts or rejects the complete import closure and checks registry keys, signatures, and metadata. Check mode also serves modules without executable entries. | Preserve acceptance and rejection in the compiler-checking suites and kernel profile. Check results cover the declaration phase. [Checking entry points](kernel_design.md#entry-points-and-results) · [Local profiles](ci.md#local-profiles) |
| C bootstrap and transitional C execution | The pinned generated C and handwritten runtime build the host producer. C execution implements `Runtime` pure, bind and loop, checked `Nat` construction of `U8`, `U32`, and `U64`, and `U8` wrapping subtraction in this inventory. The C host reports unwired raw operations, `RawFn` calls and Win64 externs on stderr and exits with status 70. | Record the producer, pinned inputs and artifact hashes. The stage loop compares generated frontend and backend C. The C runtime suite checks executable behavior separately. [Build and stage loop](build.md#generated-artifacts-and-stage-loop) · [Checked C binding keys](../compiler/checked_program_output.ouro) · [C bindings](../runtime/ouro_io.c) · [Runtime IO suite](../scripts/runtime_io_suite.sh) |
| Windows x86-64 scalar PE | `native_compile_units` lowers directly to x64 and PE with Win64 imports. It supports raw scalar operations, concrete indirect calls, and the bounded scalar `Runtime` slice. The raw user entry returns a `U32` representation from `U32` or `Runtime U32`. | Require checker and MIR verification, instruction and PE assertions, and the observed exit status and effects of the emitted PE on Windows x86-64. [Scalar source entry](../compiler/native/lower_source.ouro) |
| Windows x86-64 managed PE | The managed path supports closures, deferred actions, checked boxed word cases, native roots, and platform adapters. `coil build` and `ouro1 build FILE.ouro` use the Windows target. | Require isolated native tool acceptance and target behavior separately from compiler build and PE emission. Include GC stress, foreign outcomes, and retained checked IO behavior. [Managed lowering](../compiler/native/managed_source.ouro) · [Compile commands](tooling.md#native-program-compile) · [Native tool acceptance](ci.md#native-tool-acceptance) |
| Experimental Linux x86-64 ELF | `native_compile_linux_units` lowers the checked scalar source slice to freestanding ELF with concrete System V calls. The MIR writer supports image-local data. Managed values, imports, and large frames are rejected. CLI target dispatch, a Linux runtime and a published seed are outside this slice. | Check the ELF and call bytes, then run a matching emitted image on Linux x86-64 for target behavior. `native_linux_source` can emit the byte vector for `--image exit42`. Record target execution separately from that vector. [Linux backend](#experimental-linux-backend) · [Linux source cases](../tests/native_linux_source_tests.ouro) |
| Native seed and release transition | Seed provenance, successor builds, and compatibility with retained stages remain separate obligations. | Require isolated-host rebuilds, unsigned stage comparison, artifact inspection and behavior tests for every retained target. Matching stages or valid images alone leave execution obligations open. [Native toolchain contract](design.md#native-toolchain-contract) · [Release acceptance criteria](roadmap.md#acceptance-and-compatibility) |

## Bootstrap and generated artifacts

[Build and bootstrap](build.md#generated-artifacts-and-stage-loop) owns the
current generated C seed, regeneration, stage comparison, and promotion. The
native seed acceptance criteria are in [Roadmap](roadmap.md#acceptance-and-compatibility).

## Tools and validation

Formatter, analyzer, linter, test runner, package, documentation, collector, and
LSP implementations live under `tools/`. Shared source and checking APIs own
language behavior; each tool adds its own presentation or workflow policy.
Build and CI orchestration still includes Python and shell until the native
control plane covers their required contracts.

Handwritten behavioral fixtures live in `tests/`. Analyzer and manifest fixture
directories retain their input boundaries. `quality/` owns rule registries,
baselines, and generated-test contracts. OuroSmith's Core generators and laws
are Ouro programs; its Python harness supplies process supervision,
source-bound receipts, and independent surface/runtime expectations. C runtime
selftests remain beside the runtime they exercise.

[CI](ci.md#validation-matrix) owns the required checks for these layers.

## Repository map

| Path | Purpose |
| --- | --- |
| `compiler/` | Ouro frontend, checking, and backends |
| `compiler/native/` | MIR, x86-64 encoding, and PE writing |
| `runtime/` | Transitional C host and Ouro runtime implementations |
| `compiler/stage0/` | Committed generated bootstrap artifacts |
| `std/` | Standard library |
| `tools/` | User and repository tools |
| `samples/` | User-facing examples and input/output companions |
| `tests/` | Handwritten behavioral and acceptance fixtures |
| `quality/` | Policy, baselines, generated-test laws, and historical corpora |
| `scripts/` | Transitional host build, validation, and release orchestration |
| `docs/` | Canonical documentation and generated `api/` reference |
| `site/` and `editors/` | Website and editor integrations |
| `.github/` | Hosted workflows and contribution forms |
| `_build/` and `_cache/` | Ignored local outputs |

### From a feature to its tests

Run the checks from the repository root in a POSIX-compatible shell after
setting up the [build requirements](getting_started.md#requirements).

- **Non-positive inductive declarations.** The declaration checker emits
  `CheckNonPositive` when the positivity check rejects a declaration. Run the
  compiler-checking suite and look for `compiler_fault`, which pairs
  `CHK.positivity` with `CTL.positivity`, and `compiler_positive`, which tests
  the rule directly. The suite report should show both fixtures passed.
  [Declaration checker](../compiler/file_elab.ouro) ·
  [Positivity check](../compiler/file_elab_positive.ouro) ·
  [Diagnostic tests](../tests/compiler/diagnostics/compiler_fault_tests.ouro) ·
  [Direct rule tests](../tests/compiler/diagnostics/compiler_positive_tests.ouro) ·
  [Compiler-checking commands](ci.md#validation-matrix)
- **Generated API pages.** `tools/doc.ouro` calls `doc_module` and `doc_render`.
  The `doc_selftest_fixture` and `doc_selftest_api` cases compare generated
  pages with an independent expectation and the committed reference. Run
  `sh scripts/doc_suite.sh` to verify both comparisons.
  [Doc tool](../tools/doc.ouro) · [Doc model](../tools/doc/model.ouro) ·
  [Doc selftests](../tools/doc/selftest.ouro) ·
  [Independent expectation](../scripts/ourosmith/surface/doc_contract.py) ·
  [API regeneration](build.md#generated-artifacts-and-stage-loop)
