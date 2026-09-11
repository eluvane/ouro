<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=DESIGN&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="DESIGN banner"
  />
</p>

# Design goals

This page records language direction and non-goals. Current syntax and
implemented behavior are in [Syntax](syntax.md) and [Tooling](tooling.md).

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
preserving this slice. Native memory reclamation is a required new capability;
the current phase/process allocation model is not its completed implementation.

## Non-goals

Ouro is not currently:

- a production-ready replacement for an established systems or application
  language;
- a proof assistant with a mature theorem-proving ecosystem;
- a formally verified compiler or runtime;
- a general workflow engine, container platform, or scientific framework;
- a language that treats generated code as trusted without ordinary typechecking.

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
