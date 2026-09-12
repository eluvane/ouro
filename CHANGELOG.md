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

- GitHub Releases now publish Lean-style host archives
  (`ouro-<version>-<platform>.tar.zst` and `.zip`) for `darwin`,
  `darwin_aarch64`, `linux`, `linux_aarch64`, and `windows`, instead of
  source-only `ouro-*-source` packs.

### Fixed

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
