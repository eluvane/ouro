# Repository automation policy

## Scope and sources

Follow the maintainer's request. Use this file for automation policy and the topic pages
indexed in docs/README.md for product contracts. Human contributors start with
CONTRIBUTING.md. Check that cited files exist. Do not infer policy from filenames.

Confirm the task and run git status --short. Keep the agreed repository, branch, base
and scope. Preserve user edits, supplied names and revisions. Ask only for missing
information that affects the task. Before editing, read the relevant docs, source,
callers, tests, fixtures and rules for generated artifacts.

Use docs/getting_started.md and docs/tooling.md for commands and examples. Use
docs/build.md and docs/ci.md for builds, caches, bootstrap and generated output. For
compiler work, read docs/architecture.md alongside the build guide.

Follow docs/design.md#native-toolchain-contract and docs/roadmap.md. Treat docs/ouro.md
as historical. Keep the checker, runtime, bootstrap inputs, build entry points and
required gates until replacements meet their contracts and consumers have migrated.
Matching stages and cache hits do not prove correct behavior. Require evidence from an
isolated host and from built artifacts before claiming toolchain independence.

## Implementation and compatibility

Reproduce the bug or show the incorrect behavior. If reproduction is blocked, say why.
Make the smallest fix in the layer that owns the behavior. Reuse existing helpers and
dependencies. Leave out unrelated cleanup, formatting, moves, refactors, speculative
abstractions and compatibility layers. Never substitute a TODO, FIXME, HACK, placeholder
or demo for a requested feature, regression test or acceptance fixture.

Change public APIs only as required. Ask before choosing between incompatible APIs. Get
approval for a repository-wide rewrite or out-of-scope changes to syntax, typechecking,
packages or runtime. In docs-only, lint-only or comment-only work, leave parser,
checker, kernel, runtime and package behavior unchanged. Never change kernel semantics
as cleanup. Report unrelated problems as limitations or in a separately authorized
issue.

Follow docs/syntax.md and docs/quality.md. Keep definitions focused and public names
clear and searchable. Avoid one-letter public names, broad imports and top-level
namespace leaks. Use aliases or local opens to remove ambiguity.

Prefer typed errors and explicit failure branches. Handle every Result, Either and
validation value. Do not hide malformed input with defaults or report an error and
return success.

Use the existing checked filesystem, process, config, CLI, CSV, line, table, validation
and workflow APIs in user-facing tools. Use structured process specs instead of shell
strings when available. Never invoke a shell unsafely. Keep CLI usage and output
deterministic. On failure, exit nonzero and name the input and failing rule or phase.
Preserve golden stdout and the tool's stdout/stderr split.

Read docs/practical_stdlib.md and docs/api/README.md for standard-library work. Provide
reusable typed APIs and relevant shape tests. Add user-facing examples where they
demonstrate acceptance. When the public API changes, update the practical reference and
regenerate the API docs.

Comment only on non-obvious decisions, invariants, proof strategy, assumptions or trust
boundaries. Keep comments current. Preserve license notices, required annotations and
suppression reasons. Omit narration, decoration and edit history.

## Tests and quality gates

Preserve tests, fixtures, manifests and golden files. Do not delete failing cases,
weaken assertions or hide host failures with broad skips. Do not dismiss a flaky test
without evidence and maintainer direction. Ask before deleting fixtures. Change golden
output only when you can show why the new result is correct. If the cause is unclear,
ask.

Add focused regression tests for behavior changes. Use negative fixtures for rejection
and positive fixtures for acceptance and analyzer precision. Keep diagnostic IDs stable
and expected output deterministic. Run the adjacent suite when behavior crosses a module
boundary.

Read docs/quality.md before changing rules, registries or fixtures. Keep each rule in
its existing analyzer or linter and its tests in the existing fixture tree. Keep rule
IDs and profile severity stable, messages precise and false positives low. Suggest a fix
for each blocking rule. Update the inventory when public rules change. Do not duplicate
analyzers or add noisy rules to increase the count.

Strict, deny, fatal and release paths must exit nonzero on violations. Preserve gates,
baselines, hashes, rechecks and trust checks. If a task would weaken a strict gate, stop
and ask. Never replace required checks with broad suppressions, file-wide ignores,
undocumented migration debt, warn-only decisions, optional reporting or
continue-on-error.

## Checker, trust, and generated artifacts

For checker and trust work, read the architecture guide, docs/kernel_design.md and
docs/tcb.md. Apply the trusted computing base (TCB) contract to checker and environment
construction, runtime, compiler/stage0/, core artifact schemas and fixtures, stage
tooling and their CI gates. Ask before broadening the TCB or changing the rules for
acceptance. To extend authority to IO, networks, processes, caches, generated C or build
tooling, give a design reason, add focused tests and state the trust impact in the PR.

Fail closed. Every consumer must check all imports and declarations and return typed
failures. Require compiler acceptance. Success in the frontend, analyzer, wrappers or
generated artifacts cannot replace it. Add focused negative tests for checker changes.

Follow docs/build.md#generated-artifacts-and-stage-loop. Never hand-edit generated C or
API output. Include the source or generator change, regeneration command and supporting
checks with every generated diff. Ask before committing a large generated diff whose
source changes are unclear. Promote stage0 only with matching hashes and stage-loop
evidence. If there is no explicit artifact task, ask for one first. Do not commit
_build/, _cache/, logs, scratch files, editor backups or host-specific artifacts.

## Documentation

Keep each topic on its existing canonical page. Link to it instead of copying
instructions. Add new canonical pages to docs/README.md. Use short runnable examples,
fenced commands and stable expected output. Omit banners, decorative separators, pass
histories, AI work narratives, private reasoning and stale promises. State experimental
and pre-1.0 limits. Do not make unsupported claims of safety, correctness or production
readiness. Follow CONTRIBUTING.md#documentation-and-compatibility for user-visible
changes. Update existing API and module docs when their interfaces change.

## Validation and reporting

Select focused checks from docs/ci.md#validation-matrix. Run the smallest applicable
suite first. Broaden only for coverage gaps, new changes, failures or unresolved risks.
Keep local checks offline. Ask before adding one that needs the network. Inspect the
diff. Before opening a requested PR, run the PR profile in docs/ci.md#local-profiles
when feasible.

Follow docs/ci.md#reports-and-failures in task reports. Use Ran for exact commands and
observed results. Use Not run for unavailable checks and reasons. Use Changed for
changes to behavior, docs, tests and generated artifacts. Use Risk for compatibility,
trust, runtime and performance risks. A missing tool, timeout, memory limit or SKIP is
not a pass. Claim a root cause, fix, passing checks, clean CI, lack of regressions,
completion or production readiness only when the evidence supports it.

## Collaboration and integration

Work in local main by default. A parallel task, probe or diagnostic run does not
authorize a branch, PR, commit, push or remote workflow run.

Give parallel writers non-overlapping files. Use detached worktrees from the agreed
revision when isolation is needed. The coordinator owns Git integration and publication.
Delegated writers must not change refs or remotes.

Integrate reviewed changes into local main. Before removing a task-owned worktree,
preserve its uncommitted files and any commits not retained in main. Remove temporary
worktrees once their results are retained. Do not remove another task's worktree or stop
its processes.

## Pull requests and releases

For public GitHub and release work, read CONTRIBUTING.md, docs/ci.md and
docs/releasing.md. Create branches and PRs only on request. Use one focused task branch
per PR. Resolve the base and title only for a requested PR. Preserve the supplied
branch, title and base. Record any agreed scope change in the PR.

Follow CONTRIBUTING.md#opening-a-pull-request. State what changed, why, and the risks
and limits. Omit empty sections, checklists, validation inventories and broad completion
claims. Keep execution evidence in task reports and CI. Merge your own PR only on
explicit instruction. Do not close, reopen, relabel or retarget unrelated PRs.
Force-push only when necessary to repair your own branch.

If maintainer guidance is unavailable, make the safe smaller change. Say what remains
undone.
