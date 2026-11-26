# Releasing

The release workflow builds toolchain archives in `.tar.zst` and `.zip`
formats for these hosts.

- `darwin` (macOS x86_64)
- `darwin_aarch64` (macOS ARM)
- `linux` (Linux x86_64)
- `linux_aarch64` (Linux ARM)
- `windows` (Windows x86_64)

The archive names are `ouro-<version>-<platform>.tar.zst` and
`ouro-<version>-<platform>.zip`.

The x86-64 macOS job uses `macos-15-intel`. The ARM job uses `macos-latest`.

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

Bump the shared files before tagging. The packer checks that the versions
are present and agree. The hosted tag build requires the matching tag name
and a clean checkout.

## Release-candidate checks

Before pushing a release tag, run the public project and workflow policy
checks in the [validation matrix](ci.md#validation-matrix). Run the commands
below from the repository root with the
[source-build prerequisites](getting_started.md#requirements), a Git checkout,
and Python 3.12. See the [CI profiles](ci.md#local-profiles) for the validation
commands and their coverage.

The package check writes a manifest, report, and `SHA256SUMS` under
`_build/release_check/` without creating archives. The PR profile writes its
reports under `_build/ci/release-pr/`. Require `RELEASE_PACKAGE: PASS` and
passing CI results before continuing.

```sh
python3 scripts/release_package.py --check --out _build/release_check
python3 scripts/ci_gate.py --profile pr --out _build/ci/release-pr
```

Add the `kernel` compatibility profile for compiler-checking changes.

```sh
python3 scripts/ci_gate.py --profile kernel --out _build/ci/release-kernel
```

Add the stage-loop profile when generated compiler artifacts or bootstrap
behavior changed.

```sh
python3 scripts/ci_gate.py --profile stage-loop --out _build/ci/release-stage-loop
```

## Build release files

Run these commands from the repository root with the release-candidate
prerequisites. This example builds and packages the Linux x86-64 host
compiler using the default build directories and
[compact source materialization](canonical_source.md#materialization).
For another host, use its platform name and compiler path. The default
Windows x86-64 values are `--platform windows` and `_build/c/ouro1.exe`.

Use a dedicated package output directory. The packer replaces matching
artifacts and writes `release-package-report.json` before computing
`SHA256SUMS`. The checksums cover the artifacts, report, and any other files
already in the output directory.

```sh
python3 scripts/ouro_build.py build --compact-sources
python3 scripts/release_package.py \
  --toolchain \
  --platform linux \
  --compiler _build/c/ouro1 \
  --out _build/release
cat _build/release/SHA256SUMS
```

On success, the packer reports `RELEASE_PACKAGE: PASS` and writes the
toolchain archives, manifest, and checksums. Use `--source` to produce
source-only `.tar.gz` and `.zip` archives for local inspection. The hosted
release publishes toolchain archives.

A complete hosted set is the ten toolchain archives, a release manifest,
and `SHA256SUMS`. Repository-local state such as
`.git/`, `_build/`, `_cache/`, editor outputs, Python bytecode, and
`node_modules/` is excluded from the source members.
Tracked symlinks and selected paths that traverse a symlink or Windows reparse
point are rejected; archive members are regular files only.

The packer normalizes archive timestamps and ownership metadata. For byte
comparisons, use the same inputs and compression implementation. Hosted
toolchain jobs create a Python 3.12 virtual environment for packaging and
install `zstandard==0.23.0` into it. The local packer can fall back to other
compression implementations.

## GitHub release

Release validation defaults to the complete `pr` profile used by ordinary CI
on `main`, with the same manual-only lint exclusion. It does not select only
checks affected by the latest commit. Extended `manual`, `kernel`, and
`stage-loop` profiles remain available through the dispatch `run_profile` input.
Toolchain archive builds run independently of validation. After validation
succeeds, the metadata job runs the project gate and writes the release
manifest. Assembly waits for both the metadata job and the toolchain matrix,
verifies the archive inventory, and writes `SHA256SUMS` before uploading the
release files. Draft and snapshot publication depend on successful assembly.

The [release workflow](../.github/workflows/ouro-release.yml) runs on release
tags, a daily schedule, and manual dispatch. Scheduled runs check the date
at 03:17 UTC and build a snapshot every three days, counting UTC days from
1970-01-01. Other scheduled runs skip validation, packaging, and publication.
The cadence continues across month and year boundaries. A pushed `v<version>` tag triggers archive builds
and a draft release with ten archives, the manifest, and checksums. Push an
annotated tag after the candidate checks and package review. GitHub generates
the draft's notes from merged pull requests using `.github/release.yml`, starting
at the highest
canonical `vX.Y.Z` ancestor other than the current tag. Snapshot and weekly
tags do not select that starting point. Without a previous version tag,
GitHub chooses the first draft's comparison automatically.

A maintainer reviews the draft's notes, checksums, validation reports,
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
version and does not mark the release as latest. Its title is `Snapshot YYYY-MM-DD`;
the notes contain one comparison link, or a commit-history link for the first snapshot.
Intervals without new commits publish nothing. Dispatch callers must replace
the former `weekly_snapshot` input with `snapshot`.

Check whether a UTC date is scheduled without building or publishing:

```sh
python3 scripts/release_package.py --snapshot-due --date 2026-09-25
```

This prints `true`. The next two dates print `false`.

Describe user-visible changes in pull requests and keep canonical
documentation and migration guidance current. Git history and GitHub releases
carry the change history.

A reproducible host package establishes a reviewable byte baseline for that
runner. It does not prove type-system soundness, compiler correctness, runtime
safety, or the truth of generated program intent.
