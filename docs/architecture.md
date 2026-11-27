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
