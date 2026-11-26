# Contributing to Ouro

Use this workflow to propose changes to the language, runtime, tools, or
documentation.

## Set up the repository

Follow the [source setup and bootstrap procedure](docs/getting_started.md#build-the-bootstrap-toolchain).
See [Build and bootstrap](docs/build.md) for cache and build configuration.

## Choose a change

Keep each change focused. Documentation corrections, diagnostic improvements,
fixtures, formatter cases, and small standard-library additions with tests are
good starting points.

Discuss changes to syntax, typechecking, the checker or trusted boundary,
`Ouro.seal`/`Ouro.lock`, package CLI behavior, core artifacts, compatibility
sensitive commands, or bootstrap policy before implementation. Substantial
language and trust decisions belong in an [RFC](docs/rfc/README.md).

## Build and test

Run the smallest suite listed for the changed area in the
[validation matrix](docs/ci.md#validation-matrix). Before opening a pull
request, also run the [local PR profile](docs/ci.md#local-profiles) when
feasible. Report failures and incomplete checks with their cause, including
missing tools, timeouts, or resource limits.

## Documentation and compatibility

Update tests or fixtures and the canonical documentation in the same pull
request as a user-visible change. Describe the resulting behavior for the
release notes. Provide migration guidance for breaking changes under the
[compatibility policy](docs/stability.md).

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

Use the official [eluvane/ouro repository](https://github.com/eluvane/ouro).
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
