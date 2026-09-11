<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=RELEASING&amp;fontColor=E2E8F0&amp;fontSize=46&amp;fontAlignY=50"
    alt="RELEASING banner"
  />
</p>

# Releasing

Ouro currently produces deterministic source archives containing the repository
sources and committed bootstrap artifacts. Releases do not yet claim signed
binaries, SLSA provenance, formal verification, or 1.0 compatibility.

## Version

Release tags use `v<version>`. The version is shared by:

- `Ouro.seal` (`project.version`);
- `editors/vscode/package.json`;
- `editors/vscode/package-lock.json`.

The release package check rejects missing versions, version drift, and, on a tag build, a tag that
does not match the project version.

## Release-candidate checks

Before tagging:

```sh
python3 scripts/github_project_gate.py
python3 scripts/github_workflow_gate.py
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

```sh
python3 scripts/release_package.py --out _build/release
cat _build/release/SHA256SUMS
```

The package directory contains source `.tar.gz` and `.zip` archives, a release
manifest, a package report, generated release notes, and `SHA256SUMS`.
Repository-local state such as `.git/`, `_build/`, `_cache/`, editor outputs,
Python bytecode, and `node_modules/` is excluded.
Tracked symlinks and selected paths that traverse a symlink or Windows reparse
point are rejected; source archives contain regular repository files only.

Archive timestamps and ownership metadata are normalized so two builds from the
same inputs can be compared.

## GitHub release

`.github/workflows/ouro-release.yml` runs on release tags, Monday schedule,
and manual dispatch.
A tag run creates a draft GitHub Release and uploads the generated archives,
manifest, notes, and checksums.

A maintainer reviews the draft, changelog, checksums, validation reports,
security status, and generated-artifact hashes before publication.

A Monday schedule on `main`, or a dispatch with `weekly_snapshot`, publishes a
dated `weekly-YYYYMMDD` GitHub Release when `main` has commits since the last
weekly snapshot (or in the last eight days if none exists). The snapshot keeps
the current project version, uses commit subjects as notes, and does not mark
the release as latest. Empty weeks publish nothing.

## Checklist

1. Update `CHANGELOG.md` for the target version.
2. Confirm the shared version and `v<version>` tag.
3. Run the appropriate validation profiles.
4. Check `docs/generated_artifact_hashes.sha256`.
5. Build and inspect the source archives and `SHA256SUMS`.
6. Push an annotated tag.
7. Review the draft release before publishing.

A reproducible source package establishes a reviewable byte baseline. It does
not prove type-system soundness, compiler correctness, runtime safety, or the truth
of generated program intent.

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
