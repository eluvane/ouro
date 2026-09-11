<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=ROADMAP&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="ROADMAP banner"
  />
</p>

# Roadmap

The current roadmap is the transition to a standalone native Ouro toolchain.
The stages below are completion criteria, not claims that the transition has
already happened. Detailed implementation work belongs in focused changes with
their own regression evidence.

## Current direction

Ouro will own its frontend, typechecker, direct machine-code generation,
executable writer, runtime, and build tools. Windows x86-64 is the first target;
ordinary use and rebuilding a release from its published native seed must
eventually work without C, OCaml, Dune, Python, Bash, or an external
assembler/linker. The [design contract](design.md#native-toolchain-contract)
defines this boundary.

The recorded starting baseline included a dependent core, an OCaml kernel, a
C bootstrap/runtime path, compiler and tools written partly in Ouro, a standard
library, local packages, editor tooling, analyzers, and typed scientific
workflow experiments. The implementation starting point is
`8ee4a175828f7eb803ca71f19bbd4c24de9b91b1`; the transition plan was prepared
against `366278d981313d4e0e86694d3aa4c724084aa412`. These identify source states,
not successful baseline measurements or a published recovery tag.

## Transition stages

| Stage | Required outcome before moving on |
| --- | --- |
| P0. Contract and baseline | Preserve a recoverable working revision; record commands, host/tool versions, bootstrap hashes, retained language/runtime slice, external dependency owners, and measured cold/warm build, checking, program, and LSP workloads. |
| P1. Complete Ouro checking | One checker validates every supported declaration and its import closure, including effect roots; malformed, unsupported, type, resource, cancellation, and internal failures remain distinguishable. Positive and negative tests cover the migrated rules. |
| P2. Remove the OCaml dependency | All consumers use authoritative Ouro checking and the retained semantic corpus passes before removing OCaml/Dune/opam, independent replay requirements, and unused kernel-protocol consumers. |
| P3. Native systems foundation | Define and implement typed machine operations, pointers, memory layouts, ABI calls, binary IO, and runtime contracts through a bootstrap-compatible compiler path. |
| P4. Direct Windows executable | Ouro emits a minimal x86-64 PE32+ image with tested instruction encodings, ABI calls, imports, fixups, and relocations, without external code generation or linking. |
| P5. Ouro runtime and platform layer | Object layout, closures, thunks, allocation, an exact non-moving collector, shadow-stack roots, startup, IO, and resource cleanup work in Ouro. GC and long-running workloads demonstrate reclamation. |
| P6. Native program coverage | Native lowering supports the retained runtime language slice, standard library, real programs, error paths, and diagnostics. Differential behavior tests remain separate from stage comparison. |
| P7. Native self-hosting | A native compiler builds its successor and the next stage from identical declared inputs; complete unsigned images compare deterministically, with seed provenance and a recovery path. |
| P8. Native build and tools | Native CLI, dependency/build orchestration, tests, formatting, analysis, LSP, and mandatory repository/release checks replace their required Python/shell implementations. All active intrinsics and platform APIs work. |
| P9. Retire the legacy path | Remove C emission, C runtime/host adapters, generated C seed, obsolete caches/configuration, and temporary fallbacks after their replacements and native rebuilding pass. Historical bootstrap remains recoverable from Git. |
| P10. Standalone distribution | A published seed and release bundle pass use, rebuild, dependency/artifact inspection, and behavior acceptance on an isolated Windows host without the removed toolchains. Documentation matches the supported surface. |
| P11. Next target | Add Linux x86-64 using the shared native compiler and target-specific ABI, ELF writer, and OS adapter; require independent target acceptance. |

The compiler-owned Ouro checker now replaces the independent replay owners.
The C bootstrap/runtime and host orchestration remain active while the native
backend, runtime, and self-hosting path develop. This does not establish the
remaining P3–P11 completion criteria.

P0 recovery commands belong to the archived revision and are recorded in
[the baseline section](build.md#native-transition-baseline).
See [Build](build.md), [CI](ci.md), and [Tooling](tooling.md) for current
commands and performance-reporting support. Baseline reports must record exact
inputs, cache mode, repeat count, hardware, output size, and peak memory along
with failures or unavailable tools. A source revision alone is not a baseline.

The current checker, runtime, seed, and build driver remain needed during P0.
Later stages replace functions before deleting their implementations; merely
renaming files, hiding dependencies in binaries, or turning a failing gate into
an optional check does not complete a stage.

## Acceptance and compatibility

Native acceptance has four separate obligations:

1. The release bundle checks, builds, runs, tests, formats, analyzes, and serves
   LSP on a clean supported host.
2. Native seed plus sources and declared inputs reproduce subsequent compiler
   stages without a legacy bootstrap fallback.
3. Shipped artifacts, executable imports, process execution, and file accesses
   show no hidden compiler, assembler/linker, C runtime, CRT, or downloaded
   toolchain dependency. OS API dependencies remain declared.
4. Compiler and negative tests, runtime/GC stress, stdlib, and tools meet their
   behavioral and resource contracts independently of stage equality.

Final isolation must use a VM or runner where the removed toolchains are absent;
changing `PATH` alone does not prove independence. Every supported target needs
its own evidence. Previously supported targets are ported or explicitly removed
from the release support set before legacy retirement.

Existing supported syntax, dependent types, structural recursion, and useful IO
remain the default compatibility target. Experimental capabilities are retained,
temporarily limited with explicit diagnostics, or removed by a documented
breaking change. General recursion, type computation, unsafe operations, and
effects need separate semantic decisions; the native transition does not
silently redefine them.

## Research directions

Longer-horizon research includes checked generation, bounded synthesis,
hole-driven development, self-applicable metaprogramming, richer effect models,
and formal study of checking and compilation. Maintaining an independent OCaml
kernel is no longer a research or release requirement.

These remain research directions rather than release promises. A negative result
is useful when it is reproducible and changes the project direction honestly.

## Major risks

- **Incomplete checking.** Root-only preflight or unchecked imported bodies
  cannot become authoritative merely by removing the independent checker.
- **Bootstrap closure.** A new primitive or syntax must be compilable by the
  preceding stage before it is required by the successor.
- **Runtime correctness.** Roots, closure capture, ABI boundaries, and resource
  cleanup need negative tests and sustained workloads, beyond toy executables.
- **Hidden dependencies.** Native binaries may still invoke or embed removed
  implementations; process and artifact inspection must test the actual path.
- **Performance and scope.** Direct code generation does not guarantee speed.
  Measure useful workloads and finish the Windows vertical slice before adding
  platforms or speculative backend frameworks.

Progress is reflected in releases and the changelog. Completed engineering
history remains in Git rather than accumulating in this document.

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
