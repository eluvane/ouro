# Automation instructions

This file is for coding agents and repository automation. Human contributors
should start with `CONTRIBUTING.md` and `docs/README.md`.

## Purpose and authority

`AGENTS.md` is the operating contract for automated work in this repository. It
does not replace the canonical documentation. It tells an agent what to read,
what not to touch, how to keep scope small, which validation to select, and how
to report results without overclaiming.

When this file conflicts with a task request, repository safety wins. When this
file conflicts with a more specific maintainer instruction in the current task,
follow the maintainer instruction only if it does not weaken trust, tests,
generated-artifact policy, or CI gates.

Human-facing project policy lives in `CONTRIBUTING.md`, `docs/README.md`,
`docs/ci.md`, and the area-specific documents under `docs/`.

## Accepted native transition

The current product direction is the standalone native Ouro toolchain described
in `docs/design.md` and `docs/roadmap.md`: a compiler-owned Ouro checker, direct
Windows x86-64 PE output, an Ouro runtime with working garbage collection, and
native bootstrap, CLI, build tooling, and mandatory repository checks. The
completed supported release must not require C/OCaml implementations, external
assembler/linker or CRT startup, Python, or shell for ordinary use and rebuilding
from its published native seed.

Program acceptance belongs to the compiler-owned Ouro checker. The independent
OCaml and Python Core replay owners are retired; their retained semantic
contracts run as Ouro laws, properties, source mutants, scale and depth probes.
This ownership change does not authorize accepting unchecked programs, silently
changing language semantics, or weakening strict validation.

Until a replacement satisfies the retained contract, keep the current checker,
runtime, bootstrap inputs, build driver, and their required gates. Retire old
gates only alongside working replacement coverage and migrated consumers.
Generated-artifact integrity, negative tests, explicit errors, and trust-impact
reporting continue to apply. Do not equate stage equality with behavioral
correctness or claim toolchain independence without isolated-host and artifact
evidence. The historical research proposal in `docs/ouro.md` does not override
this accepted direction.

## First steps for every agent

For each task:

1. Establish the requested task, repository, current branch, and scope from
   available context. Resolve a PR's base, target, and title only when a PR is
   requested; ask only for missing information that affects the work.
2. Read this file.
3. Read the canonical documentation for the affected area.
4. Inspect the existing code, tests, fixtures, and generated-artifact policy
   before changing behavior.
5. Identify the smallest focused validation command that can catch mistakes in
   the affected layer.
6. Make the smallest coherent change that solves the task.
7. Run focused validation when the environment can run it.
8. Run `python3 scripts/ci_gate.py --profile pr --out _build/ci/pr` when
   feasible before opening a PR.
9. Report exactly which commands ran, which did not run, and why.
10. Open a focused PR only when requested. Local edits do not require a PR.

If the user already gave a branch name, PR title, base revision, or scope,
preserve it exactly unless it is unsafe or impossible. Do not silently rename the
branch or broaden the work.

## Read before editing

Use the canonical documentation for the area being changed:

| Area | Read first |
| --- | --- |
| General contribution workflow | `CONTRIBUTING.md`, `docs/README.md` |
| User commands and examples | `README.md`, `docs/getting_started.md`, `docs/tooling.md` |
| Language syntax and style | `docs/syntax.md`, `docs/quality.md` |
| Practical standard library | `docs/practical_stdlib.md`, `docs/api/README.md` |
| Build, caches, and bootstrap | `docs/build.md`, `docs/ci.md` |
| Compiler architecture | `docs/architecture.md`, `docs/build.md` |
| Compiler checking and trust boundary | `docs/kernel_design.md`, `docs/tcb.md` |
| Generated API docs | `docs/build.md`, `docs/tooling.md` |
| GitHub and public project surface | `docs/ci.md`, `CONTRIBUTING.md` |

Do not invent a policy from filenames. If the canonical file does not exist on
the current branch, do not cite it as authority.

## Hard prohibitions

Do not:

- work from the wrong branch, wrong base revision, or wrong repository;
- change the requested scope without a concrete reason recorded in the PR;
- do repo-wide cleanup inside a feature, bug-fix, or docs PR;
- format the whole repository unless the task is explicitly a formatter task;
- delete tests, fixtures, manifests, or golden files because they fail;
- weaken checks, lints, analyzers, quality gates, workflow policy, or CI so the
  PR passes;
- change expected or golden output without proving why the new output is the
  correct behavior;
- hand-edit generated C under `compiler/stage0/`;
- commit `_build`, `_cache`, local logs, temporary scratch files, editor backup
  files, or host-specific artifacts;
- broaden the trusted computing base without design documentation, focused
  tests, and an explicit PR section explaining the trust impact;
- change kernel semantics as a side effect of cleanup, docs, lint, formatting,
  or tooling work;
- change parser, typechecker, runtime, or package behavior for a docs-only,
  lint-only, or comment-only task;
- add unsafe shell invocation or network-dependent validation to local checks;
- hide required failures behind `warn-only`, `continue-on-error`, broad
  suppression, or optional reporting when the strict path must fail;
- write `tests pass`, `validated`, `fixed`, `no regressions`, or `CI clean`
  unless concrete commands ran and support that claim;
- claim a bug is fixed without reproduction or focused validation;
- add a new document when an existing canonical page should be updated;
- duplicate documentation in a new file instead of updating the canonical page;
- write long pass-history narratives in public docs;
- leave `TODO`, `FIXME`, `HACK`, or placeholder text as a substitute for the
  requested implementation;
- use broad suppressions, file-wide ignores, or undocumented migration debt;
- add generated artifacts without the regeneration command and evidence;
- make an AI-style unrelated rewrite of large files.

## Repository scope discipline

A good PR has one reason to exist.

Keep the change coherent:

- Do not perform "while I was here" cleanup.
- Do not refactor adjacent code unless the refactor is required by the fix.
- Do not change a public API for internal convenience.
- Do not move files without a clear repository-level reason.
- Do not combine a language change, docs rewrite, tooling rewrite, and fixture
  migration in one PR.
- Do not add demos instead of capabilities, regression tests, or acceptance
  fixtures.
- Do not fix only symptoms when the root cause is in another layer.
- Do not replace a failing test with a weaker assertion.
- Do not delete a flaky-looking test without an issue, evidence, or maintainer
  direction.
- Do not update generated output as the primary handwritten change.

If a task uncovers a larger unrelated problem, mention it in the PR limitations
or open a separate issue. Do not silently expand the diff.

## How to choose the right files

Start from the layer that owns the behavior:

- User-facing documentation belongs in the existing page linked from
  `docs/README.md`.
- User command behavior usually belongs under `tools/`, `std/`, `samples/`, or
  the wrapper scripts documented in `docs/tooling.md`.
- Standard-library behavior belongs under `std/`, with shape tests, examples,
  generated API docs when needed, and updates to `docs/practical_stdlib.md` for
  user-visible additions.
- Analyzer behavior belongs under `tools/analyze/`, `quality/`, and the
  analyzer fixture tree.
- Linter behavior belongs in the lint implementation and lint fixtures, not in
  unrelated formatter or analyzer paths.
- Runtime and IO behavior belongs under `runtime/`, runtime fixtures, and the
  runtime/IO suite.
- Program acceptance belongs to the checker under `compiler/`, with compiler
  fixtures and the hardening, scale/depth, and boundary suites. Keep its complete
  import/declaration checking and typed failures in every consumer.

Read nearby tests before editing source. Read source before editing tests. Read
the generated-artifact policy before touching any committed generated output.

## Bug-fix workflow

For a bug fix:

1. Reproduce the bug, or explain why reproduction is unavailable.
2. Identify the root cause and the layer that owns it.
3. Add or update a focused regression test or fixture.
4. Fix the smallest responsible layer.
5. Run the focused test or suite.
6. Run the adjacent suite if the behavior crosses a module boundary.
7. Document compatibility impact when user-visible behavior changes.
8. Report checks not run with a concrete reason.

Do not:

- patch output only;
- add a catch-all fallback that hides malformed input;
- turn an error into success to keep a tool green;
- delete a failing fixture;
- weaken diagnostics;
- change unrelated formatting;
- add broad suppressions;
- claim root cause without evidence.

For a bug-fix PR, briefly explain the incorrect behavior and how the change
corrects it. Use a concrete example when it helps the reviewer.

## Changing Ouro code

For `.ouro` files:

- Prefer small definitions with one clear responsibility.
- Prefer typed errors over raw `String` errors.
- Use existing standard-library helpers before adding new helpers.
- In user-facing tools, use checked filesystem, process, config, CLI, CSV, table,
  validation, and workflow APIs when they exist.
- Do not use raw primitives in user-facing tools when checked wrappers exist.
- Keep public API names clear and searchable.
- Avoid one-letter public names.
- Avoid broad imports and top-level namespace leakage.
- Prefer import aliases or local opens when they reduce ambiguity.
- Prefer explicit error branches over silent defaulting.
- Do not ignore `Result`, `Either`, or validation-style values.
- Do not return fake success after emitting diagnostics.
- Preserve deterministic output for tools, reports, tests, and fixtures.
- Add tests or fixtures for new behavior.
- Update user documentation and generated API docs for user-facing standard
  library changes.

Follow `docs/syntax.md` for accepted syntax. Follow `docs/quality.md` for the
repository's stricter project-owned style. Do not invent a new style guide that
conflicts with those documents.

## Changing Markdown docs

Documentation should be concise, task-oriented, and current-state focused.

Do:

- update canonical docs instead of creating duplicate docs;
- keep examples small and runnable when possible;
- put commands in fenced code blocks;
- include expected output only when it is stable;
- link to existing docs instead of copying whole sections;
- mark experimental and pre-1.0 behavior honestly;
- update `docs/README.md` when adding a new canonical page;
- update `CHANGELOG.md` for user-visible changes when repository policy
  requires it.

Do not:

- write pass history;
- write "AI did X" narratives;
- include private scratchpad reasoning;
- duplicate long explanations from another canonical page;
- add stale roadmap promises to task documentation;
- use marketing claims such as "production-ready", "perfect", "guaranteed
  safe", "world-class", or "enterprise-grade" unless the repository explicitly
  substantiates the claim;
- claim a feature is complete, fully safe, or verified beyond the evidence in
  the repo.

## Changing tests and fixtures

Tests and fixtures are repository evidence, not decoration.

- Add negative fixtures for rejected behavior.
- Add positive fixtures for valid behavior and false-positive protection.
- Keep golden output deterministic.
- Update a golden file only after confirming the implementation change is
  correct.
- Preserve stable diagnostic codes in bad fixtures.
- Keep fixture names specific to the behavior they cover.
- Do not delete a fixture because it exposes a bug.
- Do not replace a precise assertion with a looser one merely to pass a suite.
- Do not hide fixture failures behind broad skip logic.

When a fixture depends on a host capability, the suite must report unavailable
host support honestly. A skip is not a pass.

## Changing standard library

For `std/` work:

- Search existing modules before adding a helper.
- Prefer reusable capabilities over one-off sample code.
- Keep APIs small, typed, and deterministic.
- Return typed errors for filesystem, config, CLI, JSON, CSV, process, and
  workflow failures.
- Do not add shell-string process helpers when shell-free command specs are
  available.
- Add shape tests under the relevant test suite.
- Update examples only when they are acceptance evidence for the reusable API.
- Regenerate API docs through `sh scripts/doc_suite.sh --regen` when committed
  `docs/api/` output must change.
- Update `docs/practical_stdlib.md` for user-facing practical-surface changes.

Do not add demos as a substitute for a standard-library capability and its
tests.

## Changing tools

For `tools/` work:

- Keep CLI usage deterministic.
- Return nonzero on failure.
- Print diagnostics that identify the input and the failing rule or phase.
- Keep stdout stable when golden tests compare it.
- Keep stderr for errors and diagnostics where existing tool behavior expects
  that split.
- Prefer checked standard-library APIs for filesystem, args, config, process,
  line, table, and workflow behavior.
- Add focused runtime, samples, or tool fixtures for new behavior.

Do not add network access to local validation commands. Do not rely on a user
shell string where a structured process invocation is available.

## Changing analyzers, lints, and quality gates

Analyzer and lint changes must be precise enough to block bad code without
creating noisy gates.

Require:

- stable rule IDs;
- stable severity by profile;
- clear diagnostic messages;
- a suggested fix or migration path when blocking;
- negative fixtures that must report the rule;
- positive fixtures that must stay clean;
- deterministic output;
- nonzero exit in strict, deny, fatal, or release mode;
- low false-positive policy;
- rule inventory or registry updates when the rule is public;
- no broad suppressions.

Do not:

- detect a problem and return success in strict mode;
- change a baseline to hide new failures;
- weaken existing quality gates;
- duplicate an analyzer instead of improving the repo-native one;
- add noisy warnings just to increase rule count;
- make `--warn-only` the path that decides PR correctness.

Read `docs/quality.md` before changing `tools/analyze/`, lint rules,
`quality/diagnostics.json`, `quality/clippy_grade_rules.json`, or quality
fixtures.

## Changing kernel or trust-sensitive code

Kernel and trust-sensitive changes are special. Read `docs/architecture.md`,
`docs/kernel_design.md`, and `docs/tcb.md` before modifying these areas.

Trust-sensitive paths include:

- compiler-owned checking and construction of checked environments;
- `compiler/stage0/`;
- `runtime/`;
- core-artifact schemas and fixtures;
- stage-loop and generated-artifact tooling;
- CI gates that protect compiler checking, hashes, or trust boundaries.

Do not:

- broaden the trusted boundary casually;
- add IO, network, process, cache, generated-C, or build-system authority to
  trusted code without design rationale;
- change acceptance semantics as part of unrelated cleanup;
- weaken rechecks, hashes, generated-artifact drift checks, or
  trust-boundary gates;
- replace fail-closed behavior with best-effort behavior;
- treat a cache hit, analyzer report, generated artifact, or wrapper success as
  kernel acceptance.

Kernel and compiler-owned checker work need focused negative tests for rejected
cases. Describe trust-boundary impact in the PR when the change affects that
boundary.

## Generated artifacts policy

Generated output is reviewed as a consequence of source and generator changes,
not as primary handwritten code.

- `compiler/stage0/` is generated and bootstrap-sensitive.
- Do not hand-edit generated C under `compiler/stage0/`.
- Use `sh scripts/stage_loop.sh --promote` only when the task actually requires
  committed stage0 artifacts to change.
- Include generated artifact hashes and stage-loop evidence when promotion
  changes committed artifacts.
- Regenerate standard-library API pages through the documentation tooling.
- Use `sh scripts/doc_suite.sh --regen` for committed `docs/api/` regeneration.
- Treat `_build/` and `_cache/` as local outputs that must not be committed.
- Review generated diffs as outputs of the documented command.

Do not "fix" generated output directly to make tests pass.

## Commands and validation policy

Run the smallest relevant suite first. Run the PR gate when feasible. Never
claim unavailable checks passed.

Common commands:

```sh
python3 scripts/ci_gate.py --profile pr --out _build/ci/pr
python3 scripts/docs_examples_gate.py
python3 scripts/github_project_gate.py
sh scripts/fmt_suite.sh
sh scripts/fix_suite.sh
sh scripts/lint_suite.sh
sh scripts/analyze_precision_suite.sh
sh scripts/pkg_suite.sh
sh scripts/coil.sh config show
sh scripts/lsp_suite.sh
sh scripts/runtime_io_suite.sh
sh scripts/test_suite.sh
sh scripts/samples_suite.sh
sh scripts/doc_suite.sh
sh scripts/doc_suite.sh --regen
sh scripts/stage_loop.sh --promote
sh scripts/test_suite.sh --compiler-checking
python3 scripts/kernel_scale.py --profile scale --out _build/kernel_scale/scale
python3 scripts/kernel_scale.py --profile depth --out _build/kernel_scale/depth
python3 scripts/kernel_hardening_suite.py
```

Validation matrix:

| Change area | Focused validation |
| --- | --- |
| Docs-only change | `python3 scripts/docs_examples_gate.py` and `python3 scripts/github_project_gate.py` |
| Markdown links or examples | `python3 scripts/docs_examples_gate.py` |
| Formatter change | `sh scripts/fmt_suite.sh` |
| Autofixer change | `sh scripts/fix_suite.sh` |
| Linter change | `sh scripts/lint_suite.sh` |
| Analyzer change | `sh scripts/analyze_precision_suite.sh` |
| Package change | `sh scripts/pkg_suite.sh` (project-facing frontend: `sh scripts/coil.sh` / `ouro1 pkg`) |
| LSP change | `sh scripts/lsp_suite.sh` |
| Runtime or IO change | `sh scripts/runtime_io_suite.sh` |
| Samples change | `sh scripts/samples_suite.sh` |
| User test runner change | `sh scripts/test_suite.sh` |
| Standard-library generated API docs | `sh scripts/doc_suite.sh --regen` then `sh scripts/doc_suite.sh` |
| Compiler or checker change | `sh scripts/test_suite.sh --compiler-checking`, `python3 scripts/ci_gate.py --profile kernel --out _build/ci/kernel`, and relevant CI gates |
| Stage0 or generated compiler artifact change | `sh scripts/stage_loop.sh --promote` and generated-artifact drift checks |
| General PR readiness | `python3 scripts/ci_gate.py --profile pr --out _build/ci/pr` |

Some suites require a C compiler, POSIX shell behavior, or sufficient
resources. If a suite reports `SKIP`, times out, runs out of memory, or cannot
find a host tool, report that exact result. Do not convert it to a pass.

## Reporting validation honestly

Use this format in task reports:

```text
Ran:
- command -> result

Not run:
- command -> reason

Changed:
- behavior/docs/tests/generated artifacts

Risk:
- compatibility/trust/runtime/performance impact
```

Forbidden unless backed by concrete command output:

- `tests pass`;
- `validated`;
- `fixed`;
- `no regressions`;
- `CI clean`;
- `fully implemented`;
- `production-ready`.

Prefer precise statements such as `Ran sh scripts/lint_suite.sh -> passed` or
`Not run: sh scripts/test_suite.sh --compiler-checking -> C compiler unavailable in this environment`.

## Pull request policy

- Create branches and PRs only when requested; use one task branch for a PR.
- Use the branch name exactly as requested when one is provided.
- When requested, open one coherent PR.
- Use the PR title exactly as requested when one is provided.
- Do not merge your own PR unless explicitly asked.
- Do not close, reopen, relabel, or retarget unrelated PRs.
- Do not force-push unless fixing your own branch and necessary.
- Do not claim broad completion beyond the implemented diff.
- Do not hide limitations.

Keep the PR description short: explain what changed and why. Mention material
risks, compatibility or trust impact, and remaining limitations only when they
apply. Do not add empty sections, `None` entries, checklists, or validation
inventories. Keep validation evidence in task reports and CI results.

## Things agents must never claim

Never claim:

- a command passed when it did not run;
- a skipped command passed;
- a timeout is harmless without evidence;
- generated output is correct because it was edited directly;
- kernel acceptance follows from frontend success;
- cache success proves source correctness;
- a warning-only analyzer protects strict mode;
- a docs-only PR changed runtime, parser, typechecker, or kernel behavior;
- a broad refactor is safe without tests;
- a bug is fixed without reproduction, focused validation, or a reason
  reproduction is unavailable.

## AI-specific failure modes

Avoid these common automation failures:

- inventing files, commands, tools, or policies;
- changing code based only on filenames;
- rewriting large files without reading nearby tests;
- adding a new abstraction instead of using existing stdlib or tooling;
- silencing tests;
- fixing generated output directly;
- adding stale docs;
- creating duplicate docs;
- overclaiming validation;
- mixing unrelated tasks;
- changing public API accidentally;
- forgetting `CHANGELOG.md` or canonical docs for user-visible changes;
- forgetting negative tests;
- forgetting positive false-positive tests;
- using network-dependent validation;
- assuming cache success means source correctness;
- turning fail-closed behavior into best-effort behavior;
- replacing typed errors with ad-hoc strings;
- hiding malformed input behind defaults.

## When to stop and ask for maintainer guidance

Stop and ask before proceeding when the task would require:

- broadening the trusted computing base;
- changing kernel acceptance semantics;
- changing syntax, typechecker behavior, package format, or runtime semantics
  outside the requested scope;
- promoting stage0 artifacts without an explicit generated-artifact task;
- weakening a deny/fatal gate or strict CI path;
- deleting fixtures or changing golden output without a clear root cause;
- adding network dependence to local validation;
- making a repo-wide rewrite;
- choosing between incompatible public APIs;
- committing large generated diffs whose source change is unclear.

If maintainer guidance is unavailable, make the safest smaller change, document
the limitation, and do not pretend the larger task was completed.
