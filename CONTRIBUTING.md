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

## Questions and planning

Use [Discussions](https://github.com/eluvane/ouro/discussions) for community
conversation:

- [Q&A](https://github.com/eluvane/ouro/discussions/categories/q-a) for questions
  about installing, using, or understanding Ouro; mark the answer that resolves
  the question.
- [Ideas](https://github.com/eluvane/ouro/discussions/categories/ideas) for early
  language and toolchain ideas. Link the discussion from a subsequent issue,
  RFC, or PR so reviewers can follow the design context.
- [Show and tell](https://github.com/eluvane/ouro/discussions/categories/show-and-tell)
  for programs, libraries, experiments, and tools built with Ouro.
- [Announcements](https://github.com/eluvane/ouro/discussions/categories/announcements)
  for maintainer updates.

Use the [issue forms](https://github.com/eluvane/ouro/issues/new/choose) for
reproducible bugs, diagnostic failures, performance reports, documentation
problems, and concrete language proposals. Follow the [security policy](SECURITY.md)
for private vulnerability reports. Implementation follows the maintainer and
RFC review process described above.

The [native milestones](docs/roadmap.md#github-milestones) group issues and PRs
that directly contribute to a native-transition stage. Link focused work to the
matching existing milestone and describe its contribution to that stage.

## Build and test

Run the smallest relevant suite, then the PR profile when feasible before
opening a pull request. [CI](docs/ci.md#validation-matrix) owns focused
commands, profiles, and reporting rules. Report missing
host tools, timeouts, and resource limits as unavailable.

## Documentation and compatibility

A user-visible change updates its tests or fixtures and canonical documentation
in the same pull request. Describe the resulting behavior in the PR so it can
appear in GitHub release notes. Breaking changes need migration guidance; see
[Stability](docs/stability.md).

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
Use a concrete action title and one or two short paragraphs explaining the
result and reason. Include material behavior limits, compatibility changes,
migration steps, or trust impact when needed; no sections or checklists are
required. Keep execution history and validation results in task reports and
[CI](docs/ci.md), not the PR description. Keep unrelated cleanup and local build
output out of the diff.

Maintainers apply [PR labels](https://github.com/eluvane/ouro/labels) manually:
`kind/` identifies the purpose, such as `kind/bug`, `kind/feature`,
`kind/dependency`, or `kind/docs`; `area/` identifies each affected part of the
project. Apply one `size/` label using the total added plus deleted lines in the
current PR diff, including generated and lock files: `size/XS` for 0-9,
`size/S` for 10-99, `size/M` for 100-499, `size/L` for 500-999, and `size/XL`
for 1000 or more. Update the size label when the diff changes.

Use `risk/tcb` for trust-sensitive work and `risk/breaking-change` for a
maintainer-confirmed incompatibility requiring migration guidance.
`needs/triage`, `needs/info`, and `needs/decision` identify the next maintainer
action; `status/blocked` records a concrete blocker. `ignore-for-release`
excludes a PR from generated release notes. Dependabot and issue forms apply
their configured labels automatically.

## License and contribution terms

Read [Sections 6, 9, and 10 of the Mother of Licenses 1.0](LICENSE) before
submitting. Technical forks, review branches, patches, and temporary test
artifacts for bona fide upstream review must identify their contribution-only
purpose and the official upstream project; they are not general-use releases or
independent products. Identify third-party material and its license terms.

By knowingly submitting a Contribution with notice of Section 9, you accept
its contribution terms. Contribution and patent grants remain governed by
Sections 9 and 10. The default workflow does not require a separate acceptance
statement or checkbox in the pull request or an accompanying message.
Keep PR descriptions as prose only, without license-acceptance footers.
Submit only material you own or are authorized to contribute.

Material that cannot be licensed under those terms needs a separate arrangement
with the licensor before incorporation. For licensing questions, contact
[keiko1337@proton.me](mailto:keiko1337@proton.me).
