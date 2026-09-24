# Architecture

Ouro has one compiler-owned declaration checker. Source compilation and
evaluation must pass it before extraction or execution. The current general
build path still uses C; the direct Windows native backend and Ouro runtime
are being developed toward the [native toolchain contract](design.md#native-toolchain-contract).

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

Both emission paths consume checked declarations. A successful parser,
generated file, cache lookup, or tool wrapper cannot establish acceptance.
Direct native lowering also validates supplied checked-program metadata before
using it. Backend and runtime behavior require execution tests in addition to
typechecking.

## Source and frontend

User programs, compiler modules, and tools are `.ouro` files. Source handling
lives in `lexer.ouro`, `parser.ouro`, `source_text.ouro`, and
`canonical_source.ouro`. Import resolution, elaboration, lowering, and
declaration checking live in `import_resolve.ouro`, `elab.ouro`, `lower.ouro`,
and `file_elab.ouro`. `driver.ouro` and `pipeline.ouro` compose the stages.

The production frontend preprocesses import aliases and records, then passes a
`CanonicalSourceUnit` token stream to the parser. [Canonical source](canonical_source.md)
owns trivia, directive metadata, source mapping, and hash contracts.

The parser uses the same `parse_a.ouro` / `parse_b.ouro` mode helpers and
`parser_min.ouro` ABI as split bootstrap compilation. Its dispatcher owns the
recursive fuel boundary. Imported modules currently flatten into a shared
namespace after dependency ordering. [Compiler checking](kernel_design.md)
defines the complete declaration plan and import-closure checks.

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

## Backends and runtime

`extract.ouro`, `backend.ouro`, and `print_c.ouro` implement the transitional C
path. `runtime/` contains its value, memory, IO, process-entry, and split
frontend adapters. Its allocation banks and phase lifetimes do not establish
a garbage-collected native heap.

`compiler/native/` implements checked lowering, MIR validation, x86-64
encoding, and PE32+ writing. Ouro modules under `runtime/` and
`runtime/platform/` provide the raw and managed runtime. The managed heap uses
exact, non-moving mark-and-sweep collection with typed object descriptors and
shadow roots. Each context lazily owns one growable Windows private heap.
`HeapAlloc` supplies zeroed blocks and `HeapFree` reclaims unreachable blocks;
small objects share OS pages. After the allocation list, object count and
requested-byte total are all empty, `HeapDestroy` returns the heap's pages.
The owner handle is cleared only after successful destruction. Raw buffers
and collector scratch retain their separate `VirtualAlloc` ownership.
Call-graph checks propagate allocation effects; backward liveness
clears dead managed slots before allocation and calls that may collect.
Liveness computes ordered per-block GEN/KILL and successor summaries once, then
iterates over previous-round facts. It preserves the exact fixed point, fact
ordering, unknown-edge errors and fuel exhaustion; incomplete facts cannot
authorize removing roots.
After validating the full heap, collection indexes its exact allocation bases
in bounded raw scratch storage. Marking uses that index and still validates
each found object and its mark state. Standalone inspection and the original
scratch-buffer entry point keep their list scans. Full checks before and after
collection and cleanup after failed release remain. Unrepresentable scratch
sizes or failed reservations report failure before changing the heap.
Allocation sites retain their MayGc effect and clear dead roots before
checking a runtime budget. A due allocation calls the existing collector and
requires exactly True before entering the allocator; direct `managed_collect`
calls always perform full collection. Successful collection grants the larger
of 1 MiB and the post-sweep live requested bytes plus a conservative 4 KiB
accounting charge per live object. Successful allocations consume their
requested bytes plus the same charge; it is not a per-object OS page size. A request exceeding the remaining budget collects first; a single large
request can exhaust that budget, making the following allocation collect again.
Accounting overflow and failed collection remain errors. The private context
keeps its existing prefix and descriptor offsets. The descriptor table is
followed by a zero budget word and a zero private-heap handle word; the first
allocation collects and acquires an owner lazily. Raw clients reserve both
footer words. Footer arithmetic checks the complete final word for overflow. Root and heap checks still run during
every collection; corruption introduced between collections can be diagnosed
at the next collection instead of the next allocation.
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
values beyond 64 bits. Machine-word arithmetic keeps its separate width and
overflow contracts. Strings store an explicit byte length, preserving NUL and
non-UTF-8 bytes through access, slicing, search, replacement, splitting, and
byte-list conversion. These operations preserve checked representation
identities and keep source objects rooted while allocating their results.

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
managed strings and containers, with explicit raw-storage cleanup. Exact
checked Nat addition, subtraction, equality, and comparison bodies can
select operations over complete limb values; other bodies keep ordinary
lowering. Display names do not authorize this specialization.
Exact checked multiplication, division and remainder bodies also have bounded
machine-word execution paths. Multiplication requires two U32 operands and
returns the full U64 product; division and remainder require U64 operands.
Zero divisors and values outside those ranges execute the original checked
source body. Recognition includes the exact addition, subtraction, comparison
and Boolean dependencies used by that body.
Remaining host operations require their own
native bridge and report unsupported when that bridge is absent.
Indexed MIR loads and stores read the object owner and unsigned byte offset
separately. Liveness retains the owner through preceding safepoints; the
temporary machine address exists only during the memory instruction.

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
