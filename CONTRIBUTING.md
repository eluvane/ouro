# Contributing to Ouro

Ouro is a pre-1.0 language and toolchain. Contributions to the language,
tooling, runtime, and documentation are welcome.

## Set up the repository

Follow [Getting started](docs/getting_started.md) for prerequisites, clone and
bootstrap commands. Build configuration, caches, and bootstrap inputs are in
[Build](docs/build.md).

## Choose a change

Keep each change focused. Documentation corrections, diagnostic improvements,
fixtures, formatter cases, and small standard-library additions with tests are
good starting points.

Discuss changes to syntax, typechecking, the checker or trusted boundary,
`Ouro.seal`/`Ouro.lock`, package CLI behavior, core artifacts, compatibility
sensitive commands, or bootstrap policy before implementation. Substantial
language and trust decisions belong in an [RFC](docs/rfc/README.md).

## Build and test

Run the smallest relevant suite, then the PR profile when feasible before
opening a pull request. [CI](docs/ci.md#validation-matrix) owns focused
commands, profiles, and reporting rules. Report missing
host tools, timeouts, and resource limits as unavailable.

## Documentation and compatibility

A user-visible change updates its tests or fixtures, canonical documentation,
and the `[Unreleased]` section of `CHANGELOG.md` in the same pull request.
Released sections stay frozen except for factual corrections. Breaking changes
need migration guidance; see [Stability](docs/stability.md).

## Generated artifacts

Do not hand-edit generated C in `compiler/stage0/` or generated API pages in
`docs/api/`. [Build](docs/build.md#generated-artifacts-and-stage-loop) owns stage
promotion, hash updates, API regeneration, and the rule that `_build/` and
`_cache/` remain local outputs.

## Sensitive areas

Compiler checking, stage0, runtime, workflows, release packaging, and artifact
schemas need review against the applicable [architecture](docs/architecture.md),
[checker](docs/kernel_design.md), and [trusted-boundary](docs/tcb.md) contracts.

## Opening a pull request

Use the official [eluvane/ouro-dev repository](https://github.com/eluvane/ouro-dev).
Explain the change and reason, give concrete reproduction and validation
results, and identify material compatibility, trust, or release impact. Keep
unrelated cleanup and local build output out of the diff. [CI](docs/ci.md)
describes the required checks.

## License and contribution terms

Read [Sections 6, 9, and 10 of the Mother of Licenses 1.0](LICENSE) before
submitting. Technical forks, review branches, patches, and temporary test
artifacts for bona fide upstream review must identify their contribution-only
purpose and the official upstream project; they are not general-use releases or
independent products. Identify third-party material and its license terms.

Each pull request or accompanying submission message must include this
acknowledgment; submissions without it must not be merged:

> I have read and accept Sections 9 and 10 of the Mother of Licenses 1.0 for this
> contribution. I own the submitted material or am authorized to grant the
> required rights. I have identified any third-party material and its license
> terms.

Material that cannot be licensed under those terms needs a separate arrangement
with the licensor before incorporation. For licensing questions, contact
[keiko1337@proton.me](mailto:keiko1337@proton.me).
