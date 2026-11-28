# Design goals

The project aims to build a standalone native toolchain for a language with
dependent types and checked generation. See [Syntax](syntax.md) and
[Tooling](tooling.md) for the supported forms and commands.

## Language direction

Ouro is being developed as a standalone programming language and native
toolchain. Dependent types, metaprogramming, and checked generation support
writing programs; an independent proof-assistant kernel is not a permanent
product requirement.

The language direction includes:

- dependent functions and inductive data as the core programming model;
- explicit, bounded elaboration rather than opaque inference;
- generated development whose output passes the ordinary compiler checker;
- a clear boundary between pure type computation and runtime effects;
- a runtime and useful standard library implemented in Ouro;
- clear compatibility and package conventions before 1.0.

Features are added only when the implementation, diagnostics, formatter,
examples, and trust story can move together. The [roadmap](roadmap.md) records
the current priorities.

## Native toolchain contract

The target compilation path is:

```text
Ouro source and imports
  -> Ouro frontend and compiler-owned checker
  -> checked Core
  -> erasure and Native MIR
  -> machine code and executable image
  -> runtime and platform adapters written in Ouro
```

The same checker must serve checking, building, running, LSP, and compiler
self-compilation. It validates all supported declarations and imported bodies
before they enter a checked environment. Generators, caches, effect lowering,
and tooling cannot bypass that boundary. Unsupported input, exhausted resources,
and cancellation are errors, never successful checks.

The first native target is Windows x86-64 with a direct PE32+ writer. Machine
code, symbols, fixups, imports, and relocations are owned by Ouro. The standard
path must not generate C, LLVM IR, or Wasm, invoke an external assembler/linker,
or embed a foreign code-generation library. Windows APIs remain platform
dependencies; calling a system ABI does not require a C implementation.

The initial managed heap is an exact, single-threaded, non-moving mark-and-sweep
collector, with roots maintained by code generation through a shadow stack.
The collector must reclaim unreachable objects in long-running workloads.
Process-lifetime allocation is only an intermediate smoke-test mechanism.
Typed machine operations, raw pointers, layouts, and extern calls form an
explicit unsafe systems area of Ouro with defined runtime contracts.

The supported release must build its successor using a published native seed
and current Ouro sources. Normal use, native rebuilding, CLI, package/build
tools, and required repository gates must work without C/OCaml implementations,
CRT startup, Python, Bash, or Node. Seed provenance, unsigned stage comparison,
behavioral tests, and clean-host acceptance provide separate evidence. Git,
the CI runner, signing tools, the website, and editor extensions remain external
environment or integration components.

Linux x86-64 follows the Windows vertical slice with its own ABI, executable
writer, and platform adapter. Each retained target requires its own acceptance
evidence; unsupported targets must be identified explicitly.

## Semantic and migration boundaries

The transition preserves the supported syntax, ADTs, pattern matching,
dependent functions, universes, structural recursion, IO slice, and negative
corpus. General recursion or other language changes need their own semantic
contract. Runtime loops, IO, and raw memory operations must not become arbitrary
computation inside type conversion. A resource limit cannot establish equality.
Unsafe or partial execution must not silently create trusted proofs.

Program acceptance now belongs to the Ouro compiler checker; independent
OCaml and Python Core replay are retired. Generated C, the C runtime, and host
build scripts remain, as described in [Architecture](architecture.md),
[Build](build.md), and [TCB](tcb.md). Retained semantic laws, source mutants,
scale, and depth probes cover compiler checking. Each remaining legacy
component is removed only after its required behavior has a working replacement.
Strict, cache, and generated-artifact gates remain in force until replacements cover
their retained contracts.

## Retained slice and experimental limits

The transition starts from the documented C-hosted language/runtime slice at
`8ee4a175828f7eb803ca71f19bbd4c24de9b91b1`. The disposition below constrains
migration; it does not claim broader support than the linked references and
their fixtures establish.

| Area | Migration disposition and boundary |
| --- | --- |
| Pure language | Retain dependent functions, universes, explicit assumptions, inductive data, constructor matching, structural recursion, and documented literal/record/pipe sugar from [Syntax](syntax.md). `Nat` must not silently acquire machine-integer overflow semantics. |
| Modules | Retain relative imports, bounded aliases, and local opens. The current flat namespace is not a mature module system. P1 must check imported declarations and bodies completely; root preflight is insufficient. |
| IO and data tools | Retain the documented `main : IO Unit`, sequencing/`let!`, console, arguments, environment, files/directories, time, and child-process capture used by [practical programs](practical_programs.md). Preserve checked-wrapper errors; process stdin and host behavior remain limited to their documented contracts. |
| One-shot handlers | Temporarily limit support to the existing [handler subset](effects_design.md#experimental-handlers) and cases that lower to checked Core. General effect rows, multi-shot continuations, and arbitrary composition remain unsupported. Effect declarations cannot exempt a module from checking. |
| Holes and generation | Retain goal reporting and checked candidate generation where implemented. Unresolved holes remain rejected by the packaged checking path. Synthesis or metaprograms cannot mutate acceptance rules. |
| Networking | Retain the HTTP message codec. Experimental native Windows POST transport uses WinHTTP through `std/http.ouro`; the C host has no request transport. Response/error tests and isolated native execution evidence remain required for P8 acceptance. |
| Async helpers | Retain the sequential `sleep_s` and `delay_then` helpers through Windows native `Sleep`. Finite one-second waits preserve full `Nat` inputs without an external command. This blocking helper does not provide concurrency or cancellation. |
| Packages and editor tooling | Retain local package resolution and the existing CLI/LSP functions, with their [pre-1.0 compatibility limits](stability.md#experimental-areas). Package-format changes, incremental behavior, and wider registry support require their own tests and migration decisions. |

No feature is removed solely because its implementation is in OCaml or C.
An intentional retirement requires a documented breaking change and updated
positive/negative expectations. Unrestricted recursion, a general effect
system, new foreign interfaces, and additional targets are not implied by
preserving this slice.

The retained C host manages allocations by phase and process. The
experimental native Windows runtime implements exact, non-moving mark-and-sweep
collection. Native release acceptance requires reclamation evidence from
sustained workloads. [Backends and runtime](architecture.md#backends-and-runtime)

## Proposed systems foundation

This draft proposes a resource-checked systems fragment alongside the pure
language and managed runtime. Stage E1 specifies the fragment and tests its
rules in bounded models under the working assumptions in D01–D06.
[Systems design decisions](rfc/README.md#systems-design-decisions)

### Motivation

The current compiler checks raw load, store and foreign-call signatures. The
caller supplies raw memory's lifetime and access conditions. Address equality
cannot establish liveness because an allocator may reuse a freed address.
Ownership also needs rules for the values that carry it. An unrestricted
closure or `Runtime` action could be copied and consume a captured owner twice.
[Experimental native declarations](syntax.md#experimental-native-declarations)

### Scope and checking

The pure fragment retains dependent functions, inductive data, structural
recursion and conversion over pure terms. Its term indices describe immutable
facts. A pure function can allocate managed memory when executed. Conversion
must leave allocations, raw memory operations, system actions, foreign calls
and potentially nonterminating loops unevaluated.

The systems fragment checks an operation against the ordinary typing context
and a resource context. The resource context records live permissions, active
loans and initialized places. Each operation yields its result type, effects
and the remaining resource context. Effects and resource state are tracked
independently of pure conversion. The compiler must establish dependent bounds
and other safety obligations through a proof over immutable facts or a checked
runtime witness. It rejects the operation if it cannot establish an obligation.
Budget exhaustion is a failure. Resize changes the owner's state version. A
proof about an earlier snapshot cannot authorize access under the new version.

E1 studies a single-threaded fragment with positive-sized owned allocations,
scoped loans, scalar storage and explicit resource transfer. The reference
machine uses immutable memory and permission state, an event trace, typed
results and a bounded step budget. The resource prototype works on a small
model AST. Both run as pure tests. [Native toolchain contract](#native-toolchain-contract)

### Memory and permissions

An allocation has an identity, size, alignment, storage class, bytes,
initialization state, liveness and owner domain. An external allocation also
has a named platform contract. A pointer records an offset and address bits,
with an allocation identity, an external domain, or no provenance. An
allocation's identity remains distinct when another allocation reuses its
address. Free invalidates all access through the previous identity. The
reference representation can store these fields explicitly. A native
representation may use address bits where checking and lowering preserve the
same access rules.

The E1 memory model checks the candidate pointer's identity, offset and
address against a live allocation. Access also requires an opaque credential
issued by the model. The credential must match the current ledger and the
allocation's address, target, allocator domain and layout.

Storage class determines lifetime and authority. Stack places are limited by
their frame and loan scope. An owned heap allocation belongs to its allocator
domain. Moving its owner leaves the allocation in place. Static immutable
storage permits reads for the life of the loaded image. Mutable static storage
requires an access protocol. Managed storage depends on the runtime's roots
and reachability rules. External storage depends on its named host, device or
FFI contract.

The following names describe the proposed permission model.

| Form | Authority |
| --- | --- |
| `Owner T` | Move ownership, start loans and destroy the initialized object. Ownership is affine. |
| `Ref r T` | Share read access to an initialized object up to the end of region `r`. |
| `Mut r T` | Read and write through an exclusive permission up to the end of region `r`. |
| `RawPtr T` | Hold or compute address bits under the raw contract. Access requires separate authority. |
| `Handle T` | Access through a checked runtime table. Reuse must reject stale generations. Generation exhaustion must fail, retire the slot or use a proven safe reuse protocol. |

Loans are lexical in the first slice. Shared loans can overlap other reads.
An exclusive loan suspends conflicting access, including through a copied raw
pointer. Destroying an owner requires all of its loans to have ended. Ending a
loan restores the suspended rights. Splitting an exclusive permission replaces
it with permissions for disjoint subranges of the same allocation. Together
they cover exactly the original range. Returning both restores the original
permission. A lexical loan cannot escape through a return, closure, action or
package. The E1 memory model suspends access through a parent permission
until all its children end. Interior mutability and non-lexical lifetime
inference require separate rules.

### Operations and failures

For an access of width `width` at byte offset `offset`, check
`0 <= offset <= size` before checking `width <= size - offset`. A checked offset
also requires a representable result and keeps its allocation identity. It may
produce a one-past pointer. Every positive-width read or write needs an
in-bounds range. Empty views permit no access. Support for zero-sized raw
storage would need separate identity, alignment and indexing rules.

| Operation | Conditions for success |
| --- | --- |
| Allocate | The requested size is positive and representable. The requested alignment and layout are supported. The allocator grants a fresh live identity in its domain and uninitialized storage. |
| Borrow, split or end a loan | The source has the required rights. The resulting permissions respect their scope and overlap rules. |
| Read | A live identity, readable range, correct alignment, initialized bytes and a valid representation. Returning an independent copy also requires `Dup T`. |
| Write or initialize | A live identity, writable range, correct alignment and a valid `T`. Replacing an initialized resource requires first disposing of the previous value by its protocol. |
| Move | The source has the unique right being transferred. Moving a value out of a place leaves the place uninitialized. Moving the owner invalidates the old handle. |
| Destroy or free | The original live allocation or place is owned by the caller and has no active loan. Heap deallocation uses the original allocator domain. Old permissions become invalid. |

Unaligned access needs an explicit operation whose result preserves validity
without creating an aligned reference. Byte copy and byte move have distinct
contracts for overlap, checked ranges and initialized source bytes. Copying a
resource's representation never copies ownership. Typed pointer storage
preserves provenance. An explicitly supported full copy may also preserve
provenance. Partial writes and arbitrary integers cannot establish it. The
initial safe serialization subset excludes pointer-containing types. Pointer
storage and general byte copy require models beyond the E1 scalar model.

A partially filled buffer can track an initialized prefix. A cleanup path
destroys only that prefix. Structured scope exit and supported recoverable
`Result` exits run the cleanup defined for the resources in scope. Abort,
hardware failure and divergence carry no cleanup guarantee. Affinity prevents
repeated consumption. It permits dropping a resource, so cleanup and explicit
transfer or leak protocols need their own rules. A fallible release returns a
defined ownership state. For example, a close whose failure may follow a
successful release cannot be retried without further evidence from the host
contract.

Checked operations return a typed failure for invalid identity, permission,
bounds, alignment, initialization or value representation. In the reference
machine a failed operation leaves memory and permissions unchanged. Future
operations with a partial externally visible result must specify that result
and the remaining permissions. Arithmetic overflow in checked operations,
allocation failure, invalid layout, unsupported target operations and limit
exhaustion have defined outcomes. An explicit trap terminates execution at its
specified point. In an unsafe program, accessing dead or out-of-bounds
storage, violating exclusivity or alignment, forming a value from invalid
bits, and violating a call or foreign memory contract are outside the
specified behavior. A raw cast without access has its own bit-level contract.

### Resource use and captures

An affine value can be consumed at most once. The resource context checks
moves and consumes at every use, including within aggregates, branch joins,
partial applications, handlers and foreign registration. Branches that meet
must agree on what resources remain live and initialized. A loop passes its
resources explicitly and checks the ownership, initialization and invariant at
the backedge. An exit returns the declared resource state. The loop provides
no termination evidence for pure conversion.

A `Sys A` action that captures an affine value is itself affine. A closure
with an affine capture has the proposed `OnceFn` type. Usage includes all
latent captures, even when hidden behind an existential or erased parameter.
A resource container inherits the usage of its fields. Unrestricted `List`,
`Pair`, `Runtime` and `IO` require unrestricted payloads without loan
dependencies. Ordinary closures have the same restriction on captures.

In the E1 resource model, every system action and every callable that
captures an affine value or a loan can run at most once. Actions and
callables holding a loan must remain within its scope. A callable with
neither kind of capture can be reused, including with a different owner on
each call. Multi-shot continuations require unrestricted captures without
loan dependencies. The model checks action and callable bodies that return
`Unit`.

### Layout, effects and later targets

Logical type, physical layout and the set of valid bits are separate contracts.
Equal size alone cannot justify a cast. A packed member requires a separate
unaligned access rule. Padding can be uninitialized and is excluded from
implicit bytewise comparison, hashing and serialization. `Dup`, storage,
byte-readable layout, validity for every bit pattern and C ABI suitability are
distinct compiler-checked properties. Layout and ABI support require an
explicit target and representation class.

The first slice is single-threaded. Transfer between threads and sharing across
threads require separate permissions. Volatile access denotes an observable
memory event at a defined width. Device memory also needs an approved mapping
and device contract. Atomics require a memory-order model, alignment and
lifetime rules. Each of these remains a later stage. Freestanding support will
require a check of transitive runtime and platform needs, including allocation,
startup, stack and trap behavior.

### Systems diagnostics

Each rejected obligation produces a stable typed error code and the phase
that owns the check. The code identifies the failure independently of the
rendered text. The prototypes can use private codes. A production integration
must define public codes and phases before adding source fixtures that depend
on them. A diagnostic identifies the failing use and, when known, the related
allocation, owner, loan or trust dependency. For a conflict, the attempted
access is the primary origin and the active loan is the related origin. For
a repeated consume, the second use is primary and the first is related. When
available, spans point to those occurrences, including their original unit
after preprocessing. Messages explain the failed condition and a way to meet
it where applicable.

Removing, corrupting or replacing the source sidecar may remove origins or
fail a map-required diagnostic projection. The typed verdict and error code
from the checker remain identical. Unknown origins stay unknown. The verdict
also retains its phase without the sidecar. Check fixtures with and without
spans and with invalid metadata, including a rejected case that carries a
plausible but forged marker. [Diagnostic metadata](tcb.md#diagnostic-metadata)

### Systems compatibility

Managed values, `Nat`, ordinary pure terms and the existing `Runtime` and `IO`
contracts are retained. E1 uses test-local models. Introducing the fragment in
the compiler requires a separate compatibility decision for new syntax or
changed verdicts.

Existing `ouro.raw.add.wrap` adds byte offsets modulo `2^64` on the current
64-bit path. `ouro.raw.cast`, `ouro.raw.to_bits` and `ouro.raw.from_bits`
preserve address bits. The runtime uses these contracts. A new checked offset
would preserve allocation bounds and identity. Raw integer round trips carry
no checked access authority. Future support for exposed addresses needs a
versioned unsafe contract for named flat-address targets. It must specify
construction, access, round trips, permitted optimizations and migration of
existing runtime users. The optimizer must allow current raw round trips and
needs an alias preservation argument beyond the spelling `Mut` before using
`noalias`. [Raw bindings](../runtime/native_types.ouro)

The direct native path, C producer and bootstrap gates follow the current
[native toolchain contract](#native-toolchain-contract) and
[stage-loop rules](build.md#generated-artifacts-and-stage-loop). Any new
backend path needs its own evidence for accepted declarations, lowering and
execution. Native value layout may vary by compiler and target. A stable C ABI
requires a published target, layout and calling-convention combination.

### Systems trust

Proofs can be copied in the pure fragment. Rights are checked in the resource
context even when they have no runtime representation. Erasure requires that
runtime values, control flow, allocation effects and external events be
independent of the erased contents. The backend must preserve access ordering
and cannot duplicate a consuming operation. A runtime length needed for a
check must remain available even when the corresponding proof is erased.

The proposed trust metadata records `checked-safe`, `trusted-assumption` and
`unsafe` obligations. Checked-safe operations discharge obligations through
allowed proofs and checks and enumerate unsafe dependencies. Trusted
assumptions make a result conditional on a named axiom or outside contract.
Unsafe operations assign stated preconditions to the caller. A strict safety
profile must trace transitive dependencies of safety obligations, including
erased proofs, and reject unapproved assumptions with their dependency chain.
Unrelated pure axioms follow their existing rules. The compiler must check
every reached import and declaration before accepting a program. Source
annotations and user-constructed wrappers cannot grant authority.

Foreign specifications must describe ownership, retention, mutation,
length/nullability, allocator domain, thread affinity, reentrancy, GC effects,
unwind and failure conventions separately from the machine signature. `NoGc`
speaks only to GC. A safe adapter validates returned bytes before creating an
Ouro value. Start with callbacks without captures or with a synchronous scope
and a no-retain contract. Longer registration needs a protocol that keeps the
context and roots live until all current and future invocations are ruled out.
The initial foreign slice must forbid unwind across the boundary.
[Compiler checking boundary](tcb.md#compiler-checking-boundary)

The eventual guarantee is conditional on the registered unsafe, foreign and
platform contracts and on the trusted implementation. Accepted safe programs
must preserve permitted accesses and defined failures through lowering and
execution. Each supported target needs defined allocation failure or abort and
a stack limit or guard policy. E1 model evidence covers only its stated rules.
Compiler and target conformance require separate checks.

### Alternatives

Global ownership or reference counting would replace the existing managed
runtime contract. The proposed fragment retains ordinary managed values and
limits resource rules to operations that need them.

General usage polymorphism or non-lexical lifetime inference would require
changes to more of Core, generic checking and closure conversion. E1 uses a
separate resource judgement with explicit scope and transfer.

One address model could either trust integer casts to recover authority or
forbid runtime round trips. The former loses the lifetime distinction and the
latter breaks existing runtime code. The proposal keeps bit operations and
checked permissions distinct while the exposed-address contract is reviewed.

### Systems validation

Record the baseline revision, OS and architecture, producer and tools,
commands, active target and backend, build inputs and artifact hashes. Record
checking, lowering and execution separately. Use distinct outcomes for pass,
fail, resource limit, unsupported and not run. Execution evidence requires
running the artifact on a suitable host and observing its result.
[Contract-first workflow](contract_first.md) ·
[Support inventory](architecture.md#systems-contract-support) ·
[CI validation matrix](ci.md#validation-matrix)

| Requirement | Contract | Positive and negative evidence |
| --- | --- | --- |
| `REQ-MEM-IDENTITY` | `CON-MEM-IDENTITY` | Read through a live loan. Reuse the address after free and reject the old identity. |
| `REQ-MEM-BOUNDS` | `CON-MEM-BOUNDS` | Access the last complete scalar. Reject `offset > size` and `width > size - offset`, including access at one-past. |
| `REQ-MEM-ALIGN` | `CON-MEM-ALIGN` | Access an aligned scalar. Reject the same typed access with a misaligned offset. |
| `REQ-MEM-INIT` | `CON-MEM-INIT` | Read a valid typed write. Reject reads of uninitialized or partly initialized scalars and invalid typed values. |
| `REQ-RES-UNIQUE` | `CON-RES-UNIQUE` | Move an owner and use the destination. Reject reuse of the original owner and duplicate ownership in an aggregate. |
| `REQ-ACTION-ONCE` | `CON-ACTION-ONCE` | Run a closure with an owner once. Reject copying or replaying it, including through a legacy action. |
| `REQ-PURE-BOUNDARY` | `CON-PURE-BOUNDARY` | Use immutable indices in a proof. Reject runtime memory or a systems loop as evidence in conversion. |
| `REQ-ERASE-RELEVANCE` | `CON-ERASE-RELEVANCE` | Erase a witness that leaves execution unchanged. Reject erasure when a branch on that witness changes a runtime result. |
| `REQ-TRUST-DEPENDENCY` | `CON-TRUST-DEPENDENCY` | Accept a permitted safety dependency. Reject a transitive unapproved axiom and show its dependency chain. |
| `REQ-LOWER-NO-UB` | `CON-LOWER-NO-UB` | Preserve a defined raw operation through lowering and execution. Reject unsupported target mappings with a typed error. |

Use independent expected results for the bounded memory model. Check stale
identities, exclusive permissions, split and restoration, failure atomicity,
validity and metadata binding to the layout, owner domain and target. A
smaller budget cannot yield a successful verdict for a rejected or unresolved
input. A completed step yields the same result with greater budget.
[Memory fixture](../tests/compiler/systems/memory_model_tests.ouro)

Use model terms to check capture and consumption. Include accepted shared and
sequential mutable loans and repeatable callables with distinct owners. Reject
a branch that moves an owner on one path, invalid legacy generic instantiation,
an escaped loan inside an action or package, an obsolete size snapshot, a
multi-shot capture and a forged checked wrapper. Pure-boundary, erasure, trust
and lowering obligations in the table need separate checks in the owning
compiler and backend paths. [Resource fixture](../tests/compiler/systems/resource_model_tests.ouro)

`CON-BASE-01` requires the inventory to connect each current operation to its
check, lowering, execution and evidence. Baseline reports, registered model
fixtures with exercised positive and negative cases, and maintainer decisions
needed for E2 and E3 are required at the E1 handoff. Native acceptance remains
open for any required execution that did not run.

### Documentation and review

Update the canonical syntax, architecture, compiler checking and trust pages
with each accepted implementation. Record artifact or gate changes in the
build and CI guides. Follow the contributor policy for user-facing changes.
[Syntax](syntax.md) · [Architecture](architecture.md) ·
[Compiler checking](kernel_design.md) · [TCB](tcb.md) · [Build](build.md) ·
[CI](ci.md) · [Documentation and compatibility](../CONTRIBUTING.md#documentation-and-compatibility)

## Non-goals

Ouro is not currently:

- a production-ready replacement for an established systems or application
  language;
- a proof assistant with a mature theorem-proving ecosystem;
- a formally verified compiler or runtime;
- a general workflow engine, container platform, or scientific framework;
- a language that treats generated code as trusted without ordinary typechecking.
