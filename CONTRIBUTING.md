<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=CONTRIBUTING&amp;fontColor=E2E8F0&amp;fontSize=46&amp;fontAlignY=50"
    alt="CONTRIBUTING banner"
  />
</p>

# Contributing to Ouro

Ouro is a pre-1.0 language and toolchain. Contributions are welcome across the
language, standard library, tooling, documentation, runtime, compiler, and
tests.

## Set up the repository

You need Python 3, a POSIX-compatible shell, and a C compiler:

```sh
git clone https://github.com/eluvane/ouro.git
cd ouro
sh scripts/bootstrap.sh
sh scripts/quickstart_smoke.sh
```

Compiler-checker work uses the same Ouro toolchain and adds the semantic
suite and compiler-boundary policy:

```sh
sh scripts/test_suite.sh --compiler-checking
sh scripts/ouro_repo_gate.sh --profile compiler-boundary
```

The [getting-started guide](docs/getting_started.md) explains the normal command
path.

## Choose a change

Good first contributions include documentation corrections, focused examples,
diagnostic improvements, fixtures, formatter cases, and small standard-library
changes with tests.

Open an issue or design discussion before work that changes:

- user-facing syntax or typechecking behavior;
- compiler checking or the trusted computing base;
- `Ouro.seal`, `Ouro.lock`, or package/coil CLI behavior;
- generated core-artifact formats;
- compatibility-sensitive CLI behavior;
- bootstrap or generated-artifact policy.

A non-trivial language or trust-boundary proposal belongs in
[`docs/rfc/`](docs/rfc/README.md).

## Build and test

Use the smallest suite that covers the change, then run the broader PR profile
before opening a pull request.

| Area | Focused validation |
| --- | --- |
| Documentation and examples | `python3 scripts/docs_examples_gate.py` or `sh scripts/ouro_repo_gate.sh --profile docs` |
| Repository project surface | `sh scripts/ouro_repo_gate.sh --profile project` |
| Workflow policy subset | `sh scripts/ouro_repo_gate.sh --profile workflow` |
| Formatter | `sh scripts/fmt_suite.sh` |
| Autofixer | `sh scripts/fix_suite.sh` |
| Linter | `sh scripts/lint_suite.sh` |
| Analyzer | `sh scripts/analyze_precision_suite.sh` |
| Handwritten C host | `python3 scripts/c_static_analysis_suite.py` |
| Host Python | `ruff check --config quality/ruff.toml scripts` |
| Host shell | `shellcheck --rcfile quality/shellcheckrc --severity=style scripts/*.sh samples/bioinformatics/fixture_tool.sh` |
| Packages | `sh scripts/pkg_suite.sh` |
| LSP | `sh scripts/lsp_suite.sh` |
| Runtime and IO | `sh scripts/runtime_io_suite.sh` |
| Compiler checking | `sh scripts/test_suite.sh --compiler-checking` and `python3 scripts/ci_gate.py --profile kernel --out _build/ci/kernel` |
| Build/cache/bootstrap | the relevant suite listed in [Build and bootstrap](docs/build.md) |

The normal pull-request profile is:

```sh
python3 scripts/ci_gate.py --profile pr --out _build/ci/pr
```

The Ouro-native repository and CI gate subset is the preferred path for the
checks it supports:

```sh
sh scripts/ouro_repo_gate.sh --profile pr-native --out _build/ouro_repo_gate/pr-native
sh scripts/ouro_ci_gate.sh --profile pr-native --list
sh scripts/ouro_ci_gate.sh --profile pr-native --out _build/ouro_ci/pr-native
sh scripts/ouro_ci_gate.sh --profile host-bound --out _build/ouro_ci/host-bound
```

These commands are not a replacement for the Python PR profile. They cover a
focused repository/docs/project/workflow subset while the
compatibility/reference Python and shell gates continue to own full PR
readiness. Do not delete a Python or shell script unless parity evidence shows
the Ouro-native path covers the same behavior and the script is not needed for
bootstrap.

Some checks depend on host tools or resources. Report a missing tool, timeout,
or resource limit as unavailable; do not describe an unrun check as passing.

## Documentation and compatibility

A user-visible change should update the relevant test or fixture, canonical
documentation, and the `[Unreleased]` section of `CHANGELOG.md` in the same
pull request. Released version sections stay frozen except to fix a factual
error. Breaking changes also need a clear migration note, and substantial
changes need an RFC.

Use the existing canonical page rather than adding a second document for the
same topic. The [documentation index](docs/README.md) shows where each subject
lives.

## Generated artifacts

`compiler/stage0/` contains committed generated bootstrap artifacts. Do not edit
those C files directly.

A change that intentionally updates the generated compiler path uses:

```sh
sh scripts/stage_loop.sh --promote
```

The promotion must include the matching
`docs/generated_artifact_hashes.sha256` update and the validation appropriate to
the compiler change. Build caches and files under `_build/` or `_cache/` are not
committed.

Generated standard-library API pages under `docs/api/` are updated through the
documentation tool:

```sh
sh scripts/doc_suite.sh --regen
```

## Sensitive areas

Changes to compiler checking, `compiler/stage0/`, `runtime/`, workflow files,
release packaging, and artifact schemas receive extra review because errors can
affect program acceptance, bootstrap integrity, runtime behavior, or supply
chain security.

Read [Architecture](docs/architecture.md),
[Compiler checking](docs/kernel_design.md), and the
[trusted computing base](docs/tcb.md) before modifying those areas.

## Opening a pull request

Keep the change focused. The pull request should explain:

- what problem it solves;
- what user-visible or internal behavior changed;
- which commands were run;
- which checks were unavailable;
- whether compatibility, generated artifacts, or the trusted boundary changed.

Do not include generated build output, local benchmark numbers without a
reproduction command, or broad cleanup unrelated to the stated change.

By contributing, you agree that your contribution is licensed under the
project's [Apache License 2.0](LICENSE).

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
