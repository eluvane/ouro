# Releasing

Ouro releases provide toolchain archives for each supported host platform.
Each GitHub Release includes both `.tar.zst` and `.zip` archives for:

- `darwin` (macOS x86_64)
- `darwin_aarch64` (macOS ARM)
- `linux` (Linux x86_64)
- `linux_aarch64` (Linux ARM)
- `windows` (Windows x86_64)

The archive names are `ouro-<version>-<platform>.tar.zst` and
`ouro-<version>-<platform>.zip`. There is no `windows_aarch64` archive.

The packer writes its report before `SHA256SUMS`, which covers all final files
in the output directory, including the report. Reusing the directory recomputes
those hashes after replacing its artifacts.

The x86-64 macOS job uses `macos-15-intel`; ARM uses `macos-latest`.

Each archive is a relocatable prefix with repository sources plus the host
`ouro1` built on that runner (`bin/ouro1` or `bin/ouro1.exe`) and a `bin/ouro`
wrapper that sets `OURO_ROOT`. A missing compiler fails the platform job; the
packer does not invent a stub image.

Releases do not claim signed binaries, SLSA provenance, formal verification, or
1.0 compatibility. Host `ouro1` is the C-hosted compiler for that OS; program
`build` still targets Windows x86-64 PE.

## Version

Release tags use `v<version>`. The version is shared by:

- `Ouro.seal` (`project.version`);
- `editors/vscode/package.json`;
- `editors/vscode/package-lock.json`.

The release package check rejects missing versions, version drift, and, on a tag build, a tag that
does not match the project version.

## Release-candidate checks

Run the public project and workflow policy checks from the
[CI validation matrix](ci.md#validation-matrix). Before tagging, also run:

```sh
python3 scripts/release_package.py --check --out _build/release_check
python3 scripts/ci_gate.py --profile manual --out _build/ci/release-manual
```

Add the `kernel` compatibility profile for compiler-checking changes:

```sh
python3 scripts/ci_gate.py --profile kernel --out _build/ci/release-kernel
```

Add the stage-loop profile when generated compiler artifacts or bootstrap
behavior changed:

```sh
python3 scripts/ci_gate.py --profile stage-loop --out _build/ci/release-stage-loop
```

## Build release files

Metadata and version checks:

```sh
python3 scripts/release_package.py --out _build/release
```

One host toolchain, after the
[compact-source compiler build](canonical_source.md#materialization) used by CI:

```sh
python3 scripts/release_package.py \
  --toolchain \
  --platform linux \
  --compiler _build/c/ouro1 \
  --out _build/release
cat _build/release/SHA256SUMS
```

On Windows the compiler path is `_build/c/ouro1.exe` and `--platform windows`.
The optional `--source` flag still writes source-only `.tar.gz` / `.zip`
archives for local inspection; those names are not uploaded to GitHub Releases.

A complete hosted set is the ten toolchain archives, a release manifest,
generated release notes, and `SHA256SUMS`. Repository-local state such as
`.git/`, `_build/`, `_cache/`, editor outputs, Python bytecode, and
`node_modules/` is excluded from the source members.
Tracked symlinks and selected paths that traverse a symlink or Windows reparse
point are rejected; archive members are regular files only.

Archive timestamps and ownership metadata are normalized so two builds from the
same inputs can be compared.

## GitHub release

`.github/workflows/ouro-release.yml` runs on release tags, a daily schedule,
and manual dispatch. Scheduled runs check the date at 03:17 UTC and build a
snapshot every three days, counting UTC days from 1970-01-01. Other scheduled
runs skip validation, packaging, and publication. This cycle continues across
month and year boundaries. Push an annotated `v<version>` tag after the candidate
checks and package review. A tag run creates a draft GitHub Release and uploads
the ten host archives, manifest, notes, and checksums.

A maintainer reviews the draft, changelog, checksums, validation reports,
security status, and generated-artifact hashes before publication.

A scheduled snapshot on `main`, or a dispatch on `main` with
`snapshot=true` and `package_only=false`, publishes a dated
`snapshot-YYYYMMDD` GitHub Release when the checked-out commit has changes since
the last snapshot (or in the last three days if none exists). Existing
`weekly-*` releases remain valid comparison points during the transition.
`package_only=true`, the dispatch default, prevents publication even when
`snapshot` is selected. Manual dispatch is independent of the scheduled cycle.
The snapshot tag points to the workflow's source
commit, matching its built archives. The snapshot keeps the current project
version, uses commit subjects as notes, and does not mark the release as latest.
Intervals without new commits publish nothing. Dispatch callers must replace
the former `weekly_snapshot` input with `snapshot`.

Check whether a UTC date is scheduled without building or publishing:

```sh
python3 scripts/release_package.py --snapshot-due --date 2026-09-25
```

This prints `true`; the next two dates print `false`.

During development, write user-visible notes under `[Unreleased]`. Do not append
new work to a published version section. Scheduled snapshots do not cut the
changelog.

Before tagging a version, bump the shared version files, then cut the log:

```sh
python3 scripts/release_package.py --cut-changelog
```

That moves `[Unreleased]` under `## [<version>] - <date>`, leaves `[Unreleased]`
empty, and rewrites the compare links. An empty `[Unreleased]` section is a
hard error: there is nothing to publish in the notes.

A reproducible host package establishes a reviewable byte baseline for that
runner. It does not prove type-system soundness, compiler correctness, runtime
safety, or the truth of generated program intent.
