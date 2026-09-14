<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=CHANGELOG&amp;fontColor=E2E8F0&amp;fontSize=46&amp;fontAlignY=50"
    alt="CHANGELOG banner"
  />
</p>

# Changelog

Notable user-visible and project-wide changes are recorded here. New work goes
under `[Unreleased]`. Cutting a version moves that section under `vX.Y.Z` and
leaves `[Unreleased]` empty.

The project is pre-1.0. Syntax, APIs, CLI behavior, package files, and editor
integration may change.

## [Unreleased]

### Changed

- Name native encoding and buffer constants, reuse list counts and simplify
  bounded definitions for the strict production analyzer. Process capability
  checks recognize the exact checked-wrapper owner at `std/process.ouro`.
- Preserve NUL and high-byte values when the C host concatenates, searches,
  and slices strings, including captured output, executable paths and PE images.
  N1 error diagnostics render packed, linked and concatenated strings exactly.
  The hosted test wrapper keeps successful
  build logs out of the test protocol and retains failed-build diagnostics.
- Release temporary PE fixup-planning storage before image serialization in
  the C host, preserving the complete patch list and typed failures.
- Run the complete compiler assertion inventory in eight mandatory CI shards.
  Kernel, Manual, and Release use complete profile partitions so cold compiler
  tests do not share one job deadline; full local commands retain every gate.
  Hosted test-suite execution reserves the same 128 MiB stack as OuroSmith,
  including large MIR laws launched after their build subprocess has exited.
- Regenerate the C bootstrap seed and pin its matching C0 runtime in the
  recovery bundle. The historical bridge and strict current-source, ABI,
  behavior, and complete P1/P2 C comparison checks remain required.
- Preserve arbitrary-size Nat arithmetic and decimal output in the C host,
  including bounded-process limits and exit codes across 32-bit and 64-bit
  boundaries. Host-size conversions reject overflow.
- OuroSmith law-driver preparation uses the compiler build memory budget while
  generated programs retain their configured execution limits. Stdlib and IO
  integration recipes separate compilation and execution deadlines.
- JSON string decoding uses a balanced byte builder to avoid C-host stack
  overflow on large LSP documents while retaining byte and error offsets.
- C boundary analysis keeps invalid applications fatal and avoids a signed
  underflow in empty-list reconstruction.
- The temporary C runtime binds the word conversions and Runtime loop used by
  zero-delay actions; invalid loop flags remain fatal.
- Analyzer and stdlib IO imports share `std/string_prims.ouro`, avoiding duplicate
  String declarations without adding platform imports to pure analyzer cores.
- Hosted sample/test processes receive their fixture stdin; test builds resolve
  relative source and output paths from the caller's directory. The C-host IO
  suite explicitly selects the same compiler and build wrappers. C-host process
  capture preserves arguments assembled with list concatenation and rejects
  malformed argument lists before launching a child.

- Import collection preserves the compiler's specific `OURO-IMP-001` through
  `OURO-IMP-004` diagnostics instead of replacing them with a generic error,
  and skips ordinary source spans without retaining per-byte scan temporaries.
- Memory checks prepare native tools under a separate bounded build phase
  before applying the existing formatter, analyzer, and compiler RSS limits,
  and require actual structured analysis of the largest production source.
  Primitive registry and host inventory definitions are split into smaller
  modules to keep that input within the analyzer's source-size limit.
- macOS host binaries reserve their compiler stack when linked; x86-64 release
  builds use the supported `macos-15-intel` runner.
- Structural shell checks distinguish saved exit status and unconditional
  artifact verification from a backend selected after command failure.

- GitHub Releases now publish Lean-style host archives
  (`ouro-<version>-<platform>.tar.zst` and `.zip`) for `darwin`,
  `darwin_aarch64`, `linux`, `linux_aarch64`, and `windows`, instead of
  source-only `ouro-*-source` packs.

### Fixed

- Prepare the current compiler before Manual and Release validation groups,
  including incomplete restored caches. PR and Nightly job deadlines cover
  cold bootstrap plus full compiler groups. Smith's large integration-source
  checks and compilation use the native preparation deadline while generated
  program execution retains its configured limit.
- Enable Darwin declarations for no-follow C-host writes and install release
  packaging dependencies in a Python 3.12 virtual environment on managed hosts.
- Set the Clang C parser's bracket-depth limit for generated constructor
  expressions, including historical bootstrap inputs on Intel macOS.
- Keep C-host native-lowering progress out of ordinary programs' stderr while
  preserving explicit N1 diagnostics and all failure messages.
- Release temporary C-host allocations after each complete MIR flow round,
  preserving shared facts, convergence fuel and typed errors when compiling
  large native process functions.
- Hosted C static analysis accepts the N1 selftest, IO selftest, heap live-byte
  walk, and empty frontend prepass.
- Analyzer cores that only need string primitives import
  `std/string_prims.ouro` instead of `std/runtime.ouro`, so
  `ANALYZE_CORE` does not load the Windows platform cone.
- Hosted `ouro1 check` keeps relative paths in the caller directory so
  `pkg verify` can typecheck `_ouro_pkgs/...` after the wrapper cds to the
  repository root.
- C-host `ouro1 test` sets `OURO_TEST_CHECK` and runs sample/test children
  through `prim_proc_exec`; dash `run_suite` keeps the child's exit status.
- Release packer decompresses zstd frames that omit a content-size header.
- Restored bootstrap input hashing so a clean host can freeze and build `ouro1`.
- Split oversized checker modules and cleared the release-quality findings that
  were failing the PR firewall.
- Hosted `PR (smith)` and the other non-`checks` PR groups now build `ouro1`
  on a cold cache instead of failing closed on a missing `_build/c/ouro1`.
- Hosted Portable macOS no longer aborts bootstrap when CPython pins
  `RLIMIT_STACK` or when Darwin rejects a finite address-space cap; POSIX
  children on Linux still apply a sticky AS cap when the host allows it.
- Hosted `Kernel` and nightly non-`checks` groups now build `ouro1` on a cold
  cache instead of failing closed on a missing `_build/c/ouro1`.
- Restore fixture identifiers after Core-descriptor sharing so retained and
  smith kernel checks name the shared `checker_test_*` declarations.
- Use the current typed term checker in constructor-closure and source-refinement
  laws, retaining successful type checks and rejection of invalid annotations.
- Run the canonical exact liveness solver in the C host and retain its edge and
  fuel errors before accelerated function emission.
- Write release reports before hashing all final artifacts, including when the
  same output directory is reused.
- Give `pe_relocation_block` the `List (List Nat)` encoding list so PE
  relocation emission typechecks.
- Hosted C-host test, LSP, package, sample, and Smith suites invoke
  `scripts/ouro1.sh` through `OURO_TEST_CHECK` / `OURO_HOSTED_COMPILER_WRAPPER`
  instead of forcing the Windows `coil.exe` sibling path.
- Bind the `primitive_roles` singleton list before passing it to `append` so the
  historical bridge parser can check `file_elab.ouro`.
- Restore the missing `emit` helper used by record expansion so the historical
  checker accepts `preprocess_record.ouro`.

## [0.1.0] - 2026-09-12

First public source release of the standalone native Ouro toolchain:
compiler-owned checker, Windows x86-64 PE output, runtime garbage collection,
standard library, and repository CLI/build tooling.

This tag is a source archive plus checksums. It does not claim signed binaries,
SLSA provenance, or a formal correctness proof.

[Unreleased]: https://github.com/eluvane/ouro/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/eluvane/ouro/releases/tag/v0.1.0

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
