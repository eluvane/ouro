# Automation instructions

Repository-specific rules for coding agents. Human contributors start with
[CONTRIBUTING.md](CONTRIBUTING.md); topic owners are listed in the
[documentation index](docs/README.md).

## Purpose and authority

Follow the current maintainer request while preserving trust boundaries, tests,
generated-artifact integrity, and strict CI gates. This file defines automation
policy; the linked area documentation defines the product and its contracts.
Do not infer policy from filenames or cite files that do not exist.

## Accepted native transition

Follow the [native toolchain contract](docs/design.md#native-toolchain-contract)
and [roadmap](docs/roadmap.md). The historical proposal in `docs/ouro.md` does
not override them. Keep existing checker, runtime, bootstrap inputs, build
entry points, and required gates until working replacements satisfy the
retained contracts and their consumers are migrated. Stage equality and cache
success do not establish behavioral correctness; toolchain independence needs
isolated-host and artifact evidence.

## First steps for every agent

1. Establish the task, repository, branch, and scope; inspect `git status --short`.
   Resolve a PR's base and title only when a PR is requested. Preserve supplied
   names, revisions, and scope; ask only for missing information that matters.
2. Read the relevant canonical pages below, then source, callers, nearby tests,
   fixtures, and any generated-artifact rules before editing.
3. Reproduce a reported bug or establish its incorrect behavior. If blocked,
   explain the limitation rather than claiming reproduction.
4. Make the smallest coherent change at the layer that owns the behavior.
5. Add focused regression coverage where behavior changes, run the relevant
   checks from [CI](docs/ci.md#validation-matrix), and inspect the diff.
6. Before opening a requested PR, run the [PR profile](docs/ci.md#local-profiles)
   when feasible and report unavailable checks as described below.

## Read before editing

| Area | Canonical documentation |
| --- | --- |
| Contribution workflow | [Contributing](CONTRIBUTING.md) |
| Commands and examples | [Getting started](docs/getting_started.md), [Tooling](docs/tooling.md) |
| Language and project style | [Syntax](docs/syntax.md), [Quality](docs/quality.md) |
| Standard library | [Practical APIs](docs/practical_stdlib.md), [API reference](docs/api/README.md) |
| Build, caches, bootstrap, generated output | [Build](docs/build.md), [CI](docs/ci.md) |
| Compiler architecture | [Architecture](docs/architecture.md), [Build](docs/build.md) |
| Checker and trust-sensitive work | [Compiler checking](docs/kernel_design.md), [TCB](docs/tcb.md), [Architecture](docs/architecture.md) |
| Public GitHub surface and releases | [CI](docs/ci.md), [Contributing](CONTRIBUTING.md), [Releasing](docs/releasing.md) |

## Scope and implementation

- One change has one reason to exist. Do not add unrelated cleanup, formatting,
  file moves, adjacent refactors, speculative abstractions, or compatibility
  layers. Change public APIs only when required by the task.
- Preserve existing user work. Do not change the repository, branch, base, or
  requested scope silently. Record any necessary scope change in the PR.
- Fix causes in their owning layer, not generated output or displayed symptoms.
  Read source before changing tests; reuse existing helpers and dependencies.
- Do not change parser, checker, kernel, runtime, or package behavior during
  docs-only, lint-only, or comment-only work. Kernel semantics never change as
  an incidental cleanup.
- Do not add network-dependent local validation or unsafe shell invocation.
- Do not leave TODO, FIXME, HACK, placeholders, or demos in place of a requested
  capability, regression test, or acceptance fixture.
- Report larger unrelated problems as limitations or in a separately authorized
  issue; do not silently expand the diff.

## Ouro code and tools

Follow [syntax](docs/syntax.md) and [project style](docs/quality.md).

- Keep definitions focused and public names clear and searchable. Avoid
  one-letter public names, broad imports, and top-level namespace leakage;
  use aliases or local opens where they reduce ambiguity.
- Prefer typed errors and explicit failure branches. Never hide malformed input
  behind defaults, ignore Result/Either/validation values, or emit a diagnostic
  and return fake success.
- User-facing tools must use existing checked filesystem, process, config, CLI,
  CSV, line, table, validation, and workflow APIs. Use structured process specs,
  not shell strings, when those APIs exist.
- Keep CLI usage and output deterministic. Fail with a nonzero exit, identify
  the input and failing rule or phase, preserve golden stdout, and follow the
  tool's existing stdout/stderr split.
- Standard-library changes need reusable typed APIs, relevant shape tests,
  user-facing examples where they demonstrate acceptance, and updates to the
  practical reference and generated API documentation when their surface changes.
- Keep comments sparse: explain non-obvious decisions, invariants, proof
  strategy, assumptions, or trust boundaries. Preserve license notices and
  required annotations/suppression reasons; update comments with their code.
  Do not narrate operations, decorate files, or record edit history in comments.

## Tests, fixtures, and quality rules

- Preserve tests, fixtures, manifests, and golden files. Do not delete failures,
  weaken assertions, hide host failures behind broad skips, or label a flaky
  test disposable without evidence and maintainer direction.
- Behavior fixes need focused regression coverage; rejected behavior needs
  negative fixtures, accepted behavior and analyzer precision need positive
  fixtures. Preserve stable diagnostic IDs and deterministic expected output.
- Change a golden result only after establishing why the new behavior is correct.
- Run the adjacent suite when behavior crosses a module boundary. Do not claim
  root cause, a fix, or lack of regressions without the corresponding evidence.
- Quality rules live in their existing analyzer/linter owners and fixture trees.
  Read [Quality](docs/quality.md) before editing rules, registries, or fixtures.
  Require stable IDs and profile severity, precise messages, a suggested fix for
  blocking rules, inventory updates for public rules, and low false positives.
- Strict/deny/fatal/release paths must fail nonzero on violations. Never weaken
  gates, baselines, hashes, rechecks, or trust checks; broad suppressions,
  file-wide ignores, undocumented migration debt, warn-only decisions, optional
  reporting, and continue-on-error are not substitutes for required checks.
- Do not duplicate an analyzer or add noisy rules merely to increase rule count.

## Trust and generated artifacts

Trust-sensitive work includes checker/environment construction, runtime,
`compiler/stage0/`, core-artifact schemas and fixtures, stage tooling, and the
CI gates protecting them. Apply the [TCB contract](docs/tcb.md).

- Do not broaden authority into IO, network, processes, caches, generated C, or
  build tooling without design rationale, focused tests, and explicit trust
  impact in the PR. Preserve fail-closed acceptance and complete import and
  declaration checking with typed failures in every consumer.
- Frontend, analyzer, wrapper, or generated-artifact success never substitutes
  for compiler-owned acceptance. Checker changes need focused negative tests.
- Follow [generated-artifact procedures](docs/build.md#generated-artifacts-and-stage-loop).
  Never hand-edit generated C or API output, use generated output as the primary
  handwritten change, or promote stage0 without an explicit artifact task.
  Promotion needs matching hashes and stage-loop evidence; every generated diff
  needs its source/generator change, regeneration command, and supporting checks.
- Do not commit `_build/`, `_cache/`, logs, scratch files, editor backups, or
  host-specific artifacts.

## Markdown documentation

- Keep each topic in its existing canonical page and link to it from other
  pages or repeated sections. Do not add duplicate documents, banners,
  decorative separators, or copied instructions.
- Keep examples short and runnable, commands fenced, and expected output stable.
  Update the documentation index for a genuinely new canonical page.
- Mark experimental/pre-1.0 limits honestly. Do not write pass-history stories,
  AI work narratives, private reasoning, stale promises, or unsupported claims
  such as production-ready, fully safe, or guaranteed correct.
- Follow [compatibility and changelog policy](CONTRIBUTING.md#documentation-and-compatibility)
  for user-visible changes. Update existing API/module docs with their interfaces.

## Commands and validation policy

The [CI validation matrix](docs/ci.md#validation-matrix) is the single command
reference for selecting focused checks; [local profiles](docs/ci.md#local-profiles)
cover PR readiness. Start with the smallest applicable suite and broaden only
for missing coverage, new changes, failures, or unresolved risks.

Use `Ran`, `Not run`, `Changed`, and `Risk` fields for the exact commands and
observed outcomes, reasons for unavailable checks, changed behavior/docs/tests/
generated artifacts, and compatibility, trust, runtime, or performance risks.
A missing tool, timeout, memory limit, or SKIP is
not a pass. Follow [report interpretation](docs/ci.md#reports-and-failures).
Never claim tests pass, validated, fixed, no regressions, CI clean, fully
implemented, or production-ready beyond the evidence actually obtained.

## Pull request policy

- Create branches and PRs only when requested, one focused task branch per PR.
  Preserve the supplied branch, title, and base. Local edits do not require a PR.
- Do not merge your own PR without explicit instruction; do not close, reopen,
  relabel, or retarget unrelated PRs. Force-push only when necessary to fix your
  own branch.
- Follow the [submission workflow](CONTRIBUTING.md#opening-a-pull-request).
  Describe the concrete change and reason concisely, with applicable risks and
  limitations. Omit empty sections, checklists, validation inventories, and
  broad completion claims; keep execution evidence in task reports and CI.

## When to stop and ask for maintainer guidance

Ask before an action would broaden the TCB, change acceptance semantics,
change syntax/typechecker/package/runtime behavior outside scope, promote
stage0 without an artifact task, weaken strict gates, delete fixtures or change
golden output without a clear cause, add network-dependent local checks, make
an unrequested repository-wide rewrite, choose incompatible public APIs, or
commit large generated diffs with unclear source changes.

If guidance is unavailable, make the safe smaller change, document the
limitation, and do not describe the larger task as complete.
