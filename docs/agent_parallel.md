# Parallel agent lanes for language work

Use this page to run a **rolling queue of up to about ten focused engineering
PRs**, from task selection through review, merge, and immediate replenishment.
[AGENTS.md](../AGENTS.md) remains authoritative; this page allocates work, not
exceptions to repository policy. Live-lock lookup and admission apply only to
[`eluvane/ouro`](https://github.com/eluvane/ouro). A dated snapshot, including
historical `eluvane/ouro-dev` TAKEN rows, is evidence at that SHA. It is not
dispatch authority and does not authorize unrelated edits.

A good hour buys **one reason, one file lock, one measurable done, and an honest
T0 on a warm tree**. Ten agents editing one compiler cone, remapping the same
diagnostic IDs, or unifying the linter again are not ten language improvements.
Language work means the checker, existing syntax and approved syntax RFCs,
standard library, native lowering and runtime-in-Ouro, check/eval/run, packages,
tests, and diagnostics that help someone use those paths.

The ordinary-use destination is [native Ouro](design.md), not a better C/OCaml
host. Keep the currently required checks from [build](build.md), [CI](ci.md),
and [TCB](tcb.md) until their documented replacement is accepted. Running a
retained compatibility gate does not authorize extending its host implementation.

**Do not wait for the other nine PRs when one finishes integration.** Refresh
main and live locks, then admit the next useful, independent task. Ten is a
work-in-progress ceiling, not a quota, a promised speedup, or ten simultaneous
compiler builds. Keep fewer tasks active when ownership, review, or host
capacity is the constraint.

Navigation: [start/refill](#1-start-and-replenish-the-queue),
[lane catalog](#2-lane-catalog), [task briefs](#3-task-briefs),
[time and resources](#4-how-to-burn-fewer-hours),
[review/merge/recovery](#5-review-merge-and-replenish),
[anti-patterns](#6-anti-patterns-seen-in-this-repository).

## 1. Start and replenish the queue

### Count unfinished work, not running chat sessions

A **lane** is a bounded responsibility and exact write set. A **slot** is capacity
for one admitted task, normally one PR. The same task keeps its slot through
implementation, validation, review, metadata preparation, and integration. An
agent saying "done", a draft PR opening, or a green focused test does not release
its files. Replacing a stalled agent on the same PR is a writer handoff, not a
second slot or a second PR.

Count distinct admitted engineering tasks, including existing relevant open PRs
and reservations that have no PR yet. Do not count catalog rows as PRs: one PR
that touches several areas still occupies one slot. Dependency bots have a
separate maintenance queue; their file locks, CI load, and review cost still
constrain admissions. Do not hide blocked drafts outside the count to start ten
more writers. Sibling reservations apply even before their PR appears.

| Task state | Slot / file reservation | Maintainer action |
| --- | --- | --- |
| BACKLOG | Neither held. | Refine a useful outcome; no implementation writer yet. |
| RESERVED / RUNNING | Both held. | Record exact files, owner, base, test host, and next checkpoint before writing. |
| VALIDATING / REVIEW / READY | Both held. | Finish evidence and review; READY is not MERGED. |
| BLOCKED | Both still held. | Record the blocker, responsible owner, and unblock condition; stop wasteful editing. |
| INTEGRATED | Release only after the merge/refetch and affected-path smoke described below. | Recheck every remaining lock, then refill immediately. |
| CANCELLED | Release after all writers stop and the maintainer closes the unmerged PR or withdraws an unpublished reservation. | Preserve the useful reproduction; cancellation is not delivered work. |

These are scheduling terms, not new GitHub labels, repository files, or an
implemented scheduler. Keep one coordinator-owned task board in the existing
issue/PR discussion workflow. PR bodies carry each task's current reservation
and evidence; this canonical page carries procedure, not a log of every event.
The coordinator need not write implementation code or consume a new PR slot
for every queue update.

### Refill on events, not a global wave barrier

On a merge, a completed review, a new failure, a changed file set, or an explicit
cancellation, the coordinator performs this loop:

```text
Refresh main, open PR heads/files, and reservations not yet represented by PRs.
Finish reviews and unblock existing work before admitting more work.
For a merged task: verify integration and release only its no-longer-held paths.
For an abandoned task: stop its writers and explicitly record cancellation.
While unfinished engineering tasks < the chosen ceiling (normally about 10):
    Select the highest-value ready task whose files and interfaces are available.
    Require an execution host, review capacity, and a feasible validation plan.
    Reserve its current write set and record later shared-metadata dependencies.
    Start one owner on a new branch from refreshed main.
    Stop admitting when no useful eligible task remains; do not invent filler.
```

Prefer the next task in the same area when it remains the best ready task, but a
free directory is not a reason to keep polishing it forever. Capacity can move
to a more valuable free area. A blocked head of one area's backlog does not block
an unrelated area. Conversely, different filenames do not make two tasks
independent when one changes the checker contract, ABI, primitive identities,
package format, or diagnostic schema the other consumes.

A necessary interface change is an explicit dependency: agree on its contract,
merge its small provider PR, then adapt consumers. Do not give two agents the
same schema/ID migration. By default, do not start the next writer on top of an
unmerged PR in the same area. A maintainer-authorized stack is an exception with
recorded base/head dependencies; it cannot waive the no-overlapping-path rule.
All unfinished PRs and inherited locks remain counted; an overlapping child
waits, and every child must be rechecked after its parent lands.

### Keep a small ready backlog per area

Prepare the next one or two credible tasks for each useful area, not ten copies
of "improve Ouro". Order ready work by its concrete language-user benefit,
retained native-transition requirement, and the work it unlocks. Fix acceptance,
data-loss, and runtime-safety regressions before optional speed or convenience
work. Tie larger work to the existing [roadmap](roadmap.md), never invented stages.

At least half the admitted tasks should improve compiler/language/stdlib/native
runtime or the actual check/eval/run/package/test/editor user path. Performance
and diagnostics are work on those paths, not separate product quotas. Keep at
most one quality-engine task. While any live `eluvane/ouro` PR owns analyzer,
Clippy, lint-unification, or rule-ID work, admit no second quality product.
Historical `ouro-dev` #35 is not a current lock here. A sample task needs
execution/error acceptance evidence, not another demo instead of an underlying
capability.

Use this task card in the existing issue or PR body; fill it before dispatch:

```text
Task / lane / owner / state:
One reason and observable user/compiler outcome:
Repository / base SHA / branch / PR (once opened):
Exact write set (source, tests, new files, generated outputs if authorized):
Read-only dependencies / forbidden paths:
Interface, RFC, prerequisite PR, and metadata dependencies:
Focused win command and exact expected status/output/coverage:
Adjacent and final required validation / execution host / resource limits:
T0 and T1 plan for performance; reproduction for correctness:
Reviewer / next checkpoint / bounded investigation allowance:
Blocker, responsible owner, and explicit unblock or cancellation condition:
Proposed changelog or other shared metadata text:
```

A task without a runnable acceptance plan is not ready for a long implementation
allocation. Use a short read-only investigation first. If it already passes,
retain a meaningful missing regression or retire the task; do not manufacture a
bug. At each checkpoint require new evidence: a reproduction, responsible code
path, added assertion, measured result, or narrower blocker. Repeated attempts
with the same failure and no new evidence need re-scoping or a stopped task,
not unlimited agent hours. The investigation allowance never changes runtime,
checker, fixture, or CI budgets.

### Refresh authority and capture live locks

Run from a clean checkout of `eluvane/ouro`, with authenticated GitHub CLI.
Scope every live-lock lookup to this repository. Historical PR numbers from
`eluvane/ouro-dev` are not current locks here; the same number in this
repository is a different pull request.

```sh
set -eu
git fetch origin main
gh repo view --json nameWithOwner,defaultBranchRef
git rev-parse origin/main
gh pr list --state open --json number,title,headRefName,files
gh pr list --state merged --limit 20 --json number,title,mergedAt,files
```

Verify `nameWithOwner` is `eluvane/ouro` and the default branch is `main`
before creating branches from `origin/main`. A cloud workspace's initial
commit is not authority. Read
[contributing](../CONTRIBUTING.md), the [index](README.md), [design](design.md),
[roadmap](roadmap.md), [architecture](architecture.md), [TCB](tcb.md),
[syntax](syntax.md), [tooling](tooling.md), [build](build.md), [CI](ci.md),
[getting started](getting_started.md), [practical stdlib](practical_stdlib.md),
and [packages](pkg.md), then inspect each proposed implementation and its tests.
An old PR description is evidence, not proof that its commands still exist.

The initial PR listing is for orientation. Do not treat a truncated embedded
`files` field as an exhaustive lock list. The following task-local recipe
captures paginated REST file lists, checks their counts and head identities,
and prints a directory summary. Its outputs are ignored working evidence under
`_build/`, not a new repository tool or gate.

```sh
set -eu
mkdir -p _build/parallel
rm -f _build/parallel/locks.tsv
git rev-parse origin/main > _build/parallel/base.txt
gh pr list --state open --limit 1000 \
  --json number,title,headRefName,headRefOid > _build/parallel/open.json
python3 - <<'PY'
import collections
import json
import pathlib
import subprocess

out = pathlib.Path('_build/parallel')
# A failed refresh must not leave yesterday's successful lock table usable.
(out / 'locks.tsv').unlink(missing_ok=True)
base = (out / 'base.txt').read_text().strip()
prs = json.loads((out / 'open.json').read_text())
if len(prs) >= 1000:
    raise SystemExit('PR listing may be incomplete; paginate before launching')
repo = 'repos/eluvane/ouro'
def api(endpoint, *flags):
    return json.loads(subprocess.check_output(['gh', 'api', *flags, endpoint], text=True))
locks = collections.defaultdict(set)
heads = {}
for pr in prs:
    endpoint = f"{repo}/pulls/{pr['number']}"
    before = api(endpoint)
    pages = api(endpoint + '/files?per_page=100', '--paginate', '--slurp')
    files = [item for page in pages for item in page]
    after = api(endpoint)
    if (before['state'] != 'open' or after['state'] != 'open'
            or before['head']['sha'] != pr['headRefOid']
            or after['head']['sha'] != pr['headRefOid']
            or before['base']['sha'] != after['base']['sha']
            or len(files) != after['changed_files']
            or len({f['filename'] for f in files}) != len(files)):
        raise SystemExit('PR changed or file list incomplete; restart snapshot')
    heads[pr['number']] = (after['head']['sha'], after['base']['sha'])
    (out / f"pr-{pr['number']}.json").write_text(json.dumps(after, indent=2) + '\n')
    (out / f"pr-{pr['number']}-files.json").write_text(json.dumps(files, indent=2) + '\n')
    for item in files:
        for path in {item['filename'], item.get('previous_filename', item['filename'])}:
            locks[path].add(pr['number'])
latest = api(repo + '/pulls?state=open&per_page=100', '--paginate', '--slurp')
if {p['number']: (p['head']['sha'], p['base']['sha'])
        for page in latest for p in page} != heads:
    raise SystemExit('Open PR set or base changed; restart snapshot')
if api(repo + '/branches/main')['commit']['sha'] != base:
    raise SystemExit('Main changed; fetch and restart snapshot')
rows = ['path\tPRs'] + [f"{p}\t{','.join(map(str, sorted(ns)))}" for p, ns in sorted(locks.items())]
(out / 'locks.tsv').write_text('\n'.join(rows) + '\n')
directories = collections.defaultdict(set)
for path, owners in locks.items():
    directories[str(pathlib.PurePosixPath(path).parent)].update(owners)
print('directory\tPRs')
for directory, owners in sorted(directories.items()):
    print(directory + '\t' + ','.join(map(str, sorted(owners))))
PY
```

Use `locks.tsv` for exact-path decisions, including both sides of renames and
files deleted or added by a PR. The directory table is an overview, not a claim
that every file in a directory is changed. No snapshot is a server-side mutex:
recheck open heads immediately before dispatch, before expanding scope, and
before merge. Abort on API failure, missing pages, stale heads, or uncertainty.

Add each new lane's exact write set to the rolling task board **before**
launching its writer, including planned new files not yet in a PR. Put that
reservation, the base SHA, the win command, and dependencies in the PR body.
Expand globs against current tracked paths; list any new path explicitly.

**If two PRs would edit the same path, one waits.** Different functions or
non-overlapping hunks do not waive that rule. A handoff requires the first owner
to stop writing and the maintainer to record who owns the path next. An open
PR's changed paths remain locks even after its agent stops; remove the overlap
through a reviewed split, merge, or explicit abandonment before reassignment.
A handoff within the same PR keeps one branch and one task. Read-only review
and reproductions on unchanged source can continue while a lane waits.

### Dated snapshots are not dispatch authority

A dated lock table is working evidence at a recorded SHA. It is **not**
dispatch authority. Refresh the `eluvane/ouro` commands above before every
admission, scope expansion, or merge. Do not treat an embedded 2026-09-19
`ouro-dev` TAKEN row, an old PR body, or a copied table as a live reservation.

### Current admissions

Snapshot checked **2026-09-21** on `eluvane/ouro`, main
`0d07dd5e61b3c283f7039a1c6b4c428fe5b65152`. Dispatch preflight had zero open
PRs. The ten reservations below were admitted from that empty board; sibling
reservations apply even before a PR appears. Recheck paginated file lists and
heads before writing. This overview does not replace `locks.tsv`. Live
`eluvane/ouro` numbers such as #35 and #36 are this wave's checked-native and
LSP PRs; they are not the historical `ouro-dev` owners with the same digits.

| Surface | Current owner | Scheduling consequence |
| --- | --- | --- |
| `std/collections.ouro`, `tests/practical_stdlib_tests.ouro` | `stdlib-collections` reservation | RESERVED. No second collections writer; do not hand-edit generated API pages or baselines. |
| `tools/test/discovery.ouro`, `tests/native_test_discovery_tests.ouro` | reservation; live [#29](https://github.com/eluvane/ouro/pull/29) | RESERVED. The discovery source remains reserved even if a live PR has edited only the test. |
| `runtime/platform/windows_process_bounded.ouro`, `tests/native_managed/process_bounded.ouro` | reservation; live [#30](https://github.com/eluvane/ouro/pull/30) | RESERVED. The runtime owner remains reserved even if a live PR has edited only the test. |
| `tests/compiler_native_syntax_tests.ouro` | reservation; live [#31](https://github.com/eluvane/ouro/pull/31) | RESERVED. Parser and lexer files are not in this write set. |
| `tests/compiler_module_tests.ouro` | reservation; live [#35](https://github.com/eluvane/ouro/pull/35) | RESERVED. This is the current `eluvane/ouro` #35, not historical `ouro-dev` #35. Compiler and native source are not reserved by this task. |
| `tools/fmt.ouro`, `tools/fmt_pipeline.ouro`, `tests/analyze/precision/format_fix.ouro` | reservation; live [#34](https://github.com/eluvane/ouro/pull/34) | RESERVED. No second formatter or shared-quality writer. |
| `tools/pkg/main.ouro`, `tools/pkg/model.ouro`, `tools/pkg/security.ouro`, `scripts/pkg_suite.sh`, `docs/pkg.md` | reservation; live [#32](https://github.com/eluvane/ouro/pull/32) | RESERVED. `tools/pkg/model.ouro` remains reserved even if a live PR has not edited it yet. |
| `tools/lsp_model.ouro`, `tools/lsp_process_model.ouro`, `scripts/lsp_suite.sh` | reservation; live [#36](https://github.com/eluvane/ouro/pull/36) | RESERVED. This is the current `eluvane/ouro` #36, not historical `ouro-dev` #36. Editor dependency manifests stay outside this write set. The LSP model files remain reserved even if a live PR has edited only the suite. |
| `samples/examples/practical_cli_file.ouro`, `samples/examples/README.md` | reservation; live [#33](https://github.com/eluvane/ouro/pull/33) | RESERVED. The sample source remains reserved even if a live PR has edited only the recipe. |
| `docs/agent_parallel.md`, `docs/README.md`, `CHANGELOG.md` | `wave-docs` reservation | RESERVED by this docs coordinator. Other wave writers supply proposed changelog text and leave shared metadata unedited. |

This wave has no quality-engine reservation and no live analyzer, Clippy,
lint-unification, or rule-ID owner. Do not add a second quality product while
finishing these ten tasks. Compiler, parser, PE, and managed-backend source are
not reserved here; that is not pre-authorization to start a broad cone. Admit
those files only with a new exact write set after a refreshed live-lock check.
No open dependency-bot PRs were present in this snapshot; their locks still
constrain admissions when they appear.

Older package branches used nested collector and self-hosted paths. The current
[architecture](architecture.md) has flattened tool entry points, including
`tools/collect.ouro`. Do not restore retired paths during a blind rebase.
Re-establish the current owner and supported package contract first.

### Historical evidence, not current locks

The 2026-09-19 snapshot below was taken on `eluvane/ouro-dev` at
`d7c3e1a1f9892da6420d266d4c558d1f08a82994`. Its #35/#36/#37 TAKEN rows
describe historical work in that other repository. They do not lock files in
`eluvane/ouro`. The same numbers here are unrelated pull requests. Do not
dispatch, wait, or refuse work from this table.

| Surface | Historical `ouro-dev` owner | Historical note only |
| --- | --- | --- |
| `compiler/file_elab*.ouro`, refinement/checking/lowering, `compiler/native/managed_*`, MIR/codegen | [ouro-dev #35](https://github.com/eluvane/ouro-dev/pull/35) | Historical checker/lowering cone in `ouro-dev`, not a current `eluvane/ouro` lock. |
| `compiler/parse_a.ouro`, `parse_b.ouro`, `parser_file.ouro`, `parser_parse.ouro` | ouro-dev #35 | Historical parser ownership in `ouro-dev`. |
| `compiler/native/pe.ouro`, `pe_fixups.ouro`, `pe_imports.ouro`, `pe_model.ouro`, `pe_unwind.ouro` | ouro-dev #35 | Historical PE ownership in `ouro-dev`. |
| `tools/fmt.ouro`, `tools/fix/`, analyzer/Clippy/lint/shared-quality files; `docs/quality.md`, `docs/tooling.md`, `docs/clippy_grade_firewall.md` | ouro-dev #35 | Historical quality owner in `ouro-dev`. |
| `tools/pkg/main.ouro`, `tools/pkg/model.ouro`, `scripts/coil.sh`, root `README.md` | [ouro-dev #11](https://github.com/eluvane/ouro-dev/pull/11), ouro-dev #35 | Historical overlap in `ouro-dev`. |
| `tools/lsp_model.ouro` | [ouro-dev #23](https://github.com/eluvane/ouro-dev/pull/23), ouro-dev #35 | Historical overlap in `ouro-dev`. |
| `docs/agent_parallel.md`, `docs/README.md` | [ouro-dev #37](https://github.com/eluvane/ouro-dev/pull/37) | Historical docs owner in `ouro-dev`. |
| `CHANGELOG.md` | ouro-dev #35 | Historical metadata lock in `ouro-dev`. |
| Selected `std/` and `samples/` files | ouro-dev #35 | Historical partial-tree locks in `ouro-dev`. |
| `std/collections.ouro`, `std/listx.ouro`, `std/string.ouro`, `std/stringx.ouro`, `std/lines.ouro`, `std/num.ouro`, `std/text.ouro`, `tests/practical_stdlib_tests.ouro`, and their generated API pages | [ouro-dev #36](https://github.com/eluvane/ouro-dev/pull/36) | Historical collections owner in `ouro-dev`. |
| `site/package.json`, `site/package-lock.json` | ouro-dev #6, #25, #26, #27 | Historical dependency-bot locks in `ouro-dev`. |
| `editors/vscode/package.json`, `editors/vscode/package-lock.json` | ouro-dev #1, #5, #19, #20, #21 | Historical editor-manifest locks in `ouro-dev`. |
| `.github/workflows/ouro-pages.yml` | ouro-dev #18 | Historical workflow lock in `ouro-dev`. |

## 2. Lane catalog

These are **ten reserved area slots on current `eluvane/ouro`**, not ten new
writable PRs and not leftover `ouro-dev` TAKEN rows. Count distinct admitted
tasks rather than held rows against the concurrency cap. When locks clear,
split the released cone into smaller exact write sets before using the rest of
the capacity. Do not meet a concurrency target by weakening ownership.

`RESERVED` means the exact write set is held by this wave, whether or not a PR
exists yet. `FREE` would mean reservable after a refreshed live snapshot, not
pre-authorized, known-broken, or already validated. Historical `TAKEN` labels
from `ouro-dev` are not instructions to start or block an agent here. All rows
must preserve [AGENTS.md](../AGENTS.md), existing failures, generated policy,
and final review requirements. Commands are to run from repository root and
are not recorded passes.

| id / status | Goal in one line | Owns (exact reserved files) | Must not touch | Done when (exact commands) | Depends on |
| --- | --- | --- | --- | --- | --- |
| `checked-native` **RESERVED [#35](https://github.com/eluvane/ouro/pull/35)** | Close one checked-program-to-native acceptance or diagnostic gap, with positive and rejection evidence. | `tests/compiler_module_tests.ouro`. | Compiler/native source, lexer/parser, C hosts, stage0, other tools, broad cleanup. | `sh scripts/test_suite.sh --compiler-checking`; `sh scripts/frontend_security_suite.sh`; `sh scripts/ouro_repo_gate.sh --profile compiler-boundary`; reproduce the selected check/eval/run case as well. | Trust/RFC review when required. Missing Windows PE execution is not a pass. Do not expand into compiler/native without a new exact write set. Current `eluvane/ouro` #35 is this test reservation, not historical `ouro-dev` #35. |
| `source-syntax` **RESERVED [#31](https://github.com/eluvane/ouro/pull/31)** | Improve one existing-syntax parse/rejection location without inventing syntax. | `tests/compiler_native_syntax_tests.ouro`. | Lexer/parser source, `file_elab*`, `compiler/native/`, formatter/fixer, diagnostic ID remaps. | `sh scripts/ouro1.sh test tests/compiler_native_syntax_tests.ouro`; `sh scripts/frontend_security_suite.sh`; `sh scripts/test_suite.sh --compiler-checking`. | An accepted RFC before any syntax/acceptance-contract change. Parser files are not reserved here. |
| `stdlib-collections` **RESERVED** | Make `split_at` one traversal while preserving its existing API and results. | `std/collections.ouro`, `tests/practical_stdlib_tests.ouro`. | All other `std/`, compiler/runtime/tools, shared docs/API baselines, generated API pages. | `sh scripts/ouro1.sh check std/collections.ouro`; `sh scripts/ouro1.sh test tests/practical_stdlib_tests.ouro`; `python3 scripts/api_baseline_regen.py --check`; warm T0/T1 below. | Freeze the current public API; reserve generated outputs separately if they must change. |
| `native-capture` **RESERVED [#30](https://github.com/eluvane/ouro/pull/30)** | Prove a reused bounded capture cannot leak a previous failure's state into the next result. | `runtime/platform/windows_process_bounded.ouro`, `tests/native_managed/process_bounded.ouro`. | `compiler/native/managed_*`, other platform helpers, `std/process*.ouro`, C/H, limits or ABI layouts. | `sh scripts/ouro1.sh build tests/native_managed/process_bounded.ouro`; run the exact native-capture acceptance block below; `sh scripts/runtime_io_suite.sh`. | Working native Windows x86-64 slice and frozen capture ABI. A compiler failure is a blocker, not a C workaround. Linux cannot execute the PE probe. |
| `test-discovery` **RESERVED [#29](https://github.com/eluvane/ouro/pull/29)** | Exercise late discovery failure and exact-budget completion without partial successful inventories. | `tools/test/discovery.ouro`, `tests/native_test_discovery_tests.ouro`. | `tools/test/suites.ouro`, `tools/test/sample_cases.ouro`, shared assertion helpers, quality tools, discovery policy changes. | `sh scripts/ouro1.sh test tests/native_test_discovery_tests.ouro`; `sh scripts/test_suite.sh`; `sh scripts/test_suite.sh --native-tools _build/native` on Windows. | Preserve explicit literal paths, ordered roots, repeated roots, and existing fixture selection. |
| `format` **RESERVED [#34](https://github.com/eluvane/ouro/pull/34)** | Preserve source bytes and checked write refusal for one concrete formatting case. | `tools/fmt.ouro`, `tools/fmt_pipeline.ouro`, `tests/analyze/precision/format_fix.ouro`. | Parser, checker, shared fixer paths, new formatting policy or lint IDs. | `sh scripts/fmt_suite.sh`; `sh scripts/fix_suite.sh`; original/candidate rejection and repeat-write evidence for the chosen case. | Syntax RFC first if formatting a new construct. |
| `packages` **RESERVED [#32](https://github.com/eluvane/ouro/pull/32)** | Make one existing local-registry/vendor/verify workflow reliably usable. | `tools/pkg/main.ouro`, `tools/pkg/model.ouro`, `tools/pkg/security.ouro`, `scripts/pkg_suite.sh`, `docs/pkg.md`. | LSP/import compiler ownership, `scripts/coil.sh`, other package docs/samples, legacy paths, invented `pkg:` imports. | `sh scripts/pkg_suite.sh`; `sh scripts/pkg_suite.sh --native-tools _build/native` on Windows. | Use current package docs, not unmerged distribution promises. |
| `lsp` **RESERVED [#36](https://github.com/eluvane/ouro/pull/36)** | Fix one user-visible diagnostic or request-state contract through the existing server. | `tools/lsp_model.ouro`, `tools/lsp_process_model.ouro`, `scripts/lsp_suite.sh`. | Checker, formatter, package resolver, `tools/lsp.ouro` unless later reserved, editor dependency manifests, a second server. | `sh scripts/lsp_suite.sh`; `sh scripts/lsp_suite.sh --native-tools _build/native` on Windows. | Compiler/formatter dependencies must be merged before their consumer changes. Current `eluvane/ouro` #36 is this LSP reservation, not historical `ouro-dev` #36. |
| `native-samples` **RESERVED [#33](https://github.com/eluvane/ouro/pull/33)** | Turn the existing CLI/file sample into an explicitly demonstrated native success/error recipe. | `samples/examples/practical_cli_file.ouro`, `samples/examples/README.md`. | Other samples, sample/test inventories, stdlib/compiler/runtime, unsupported sample-harness options. | `sh scripts/ouro1.sh check samples/examples/practical_cli_file.ouro`; run the exact native-sample block below; `sh scripts/samples_suite.sh --native-tools _build/native`. | Working native Windows toolchain; fix only a reproduced sample-local defect, otherwise improve the verified recipe. Linux PE execution is unavailable. |
| `wave-docs` **RESERVED** | Keep one operable playbook and index aligned with current `eluvane/ouro` locks. | `docs/agent_parallel.md`, `docs/README.md`, `CHANGELOG.md`. | Other docs, AGENTS policy, all implementation files, generated reference, shared inventories. | `python3 scripts/docs_examples_gate.py`; `python3 scripts/github_project_gate.py`; required Unreleased bullet included before readiness. | Singleton docs coordinator for this wave. Other lanes propose changelog text and remain draft until serialized metadata is applied. Do not launch another writer when this page already has an open PR. |

The code paths above come from the current tree, not a proposed directory
layout: formatter and LSP owners are files, while package and test-discovery
owners are the exact reserved files in those directories. There is **no
additional analyzer/Clippy/lint lane** in this wave. Nine slots address a
language or language-user path; one coordinates docs. Existing quality checks
constrain every slot without becoming its product.

### Focused native acceptance

Run these blocks on Windows x86-64 with a supported shell and a validated
native toolchain. Use the [documented build](build.md) and standalone tool
preparation; do not copy an arbitrary stale executable into `_build/native`.
A hosted `ouro1.sh test` or compatibility-suite pass is not PE execution evidence.
Reports below are task-local output; do not commit them.

For `native-capture`, extend the existing `--reuse` case to include a failed
capture followed by a valid capture, keeping its current successful-repeat
assertions. The probe has a deliberate success exit **42**, not zero; preserve
that contract. The focused acceptance also exercises other existing modes:

```sh
set -eu
mkdir -p _build/parallel/capture
sh scripts/ouro1.sh build tests/native_managed/process_bounded.ouro
for mode in basic stdin reuse deferred timeout stdout-cap stderr-cap negative73 missing invalid; do
  status=0
  ./_build/native/process_bounded.exe "--$mode" \
    > "_build/parallel/capture/$mode.out" \
    2> "_build/parallel/capture/$mode.err" || status=$?
  test "$status" -eq 42
  printf 'CAPTURE_OK %s\n' "$mode" > _build/parallel/capture/expected
  cmp _build/parallel/capture/expected "_build/parallel/capture/$mode.out"
  test ! -s "_build/parallel/capture/$mode.err"
done
```

This does not replace the existing process-tree, hard-limit, compiler-binding,
or IO suite coverage. An `ENFORCEMENT_GAP`, timeout in the harness, or missing
Windows execution is not success. Do not run the probe's destructive-lifecycle
modes without their existing harness and cleanup contract.

For `native-samples`, retain the sample's exit/status/stream contract: success
is zero, missing arguments are 2, and a failed file read is 1. Its current
sample-suite inventory is check-only; a green aggregate alone does not establish
these runtime cases. Do not invent an argv field in that inventory.

```sh
set -eu
mkdir -p _build/parallel/sample
sh scripts/ouro1.sh build samples/examples/practical_cli_file.ouro
printf 'ouro\n' > _build/parallel/sample/input.txt
printf 'OURO\n' > _build/parallel/sample/expected
./_build/native/practical_cli_file.exe --upper _build/parallel/sample/input.txt \
  > _build/parallel/sample/out 2> _build/parallel/sample/err
cmp _build/parallel/sample/expected _build/parallel/sample/out
test ! -s _build/parallel/sample/err
status=0
./_build/native/practical_cli_file.exe > _build/parallel/sample/out \
  2> _build/parallel/sample/err || status=$?
test "$status" -eq 2
test ! -s _build/parallel/sample/out
test -s _build/parallel/sample/err
test ! -e _build/parallel/sample/must-not-exist
status=0
./_build/native/practical_cli_file.exe _build/parallel/sample/must-not-exist \
  > _build/parallel/sample/out 2> _build/parallel/sample/err || status=$?
test "$status" -eq 1
test ! -s _build/parallel/sample/out
test -s _build/parallel/sample/err
```

## 3. Task briefs

Paste only the selected reserved lane's brief, together with its completed
task card, refreshed `eluvane/ouro` lock table, and base SHA. Do not dispatch
a second writer onto a reserved row; reuse the current owner and PR. Each
brief is a bounded assignment, not permission to claim a defect before
reproducing one. Shared metadata is supplied to the `wave-docs` coordinator as
proposed text, not edited by every lane. The coordinator adds required
entries to each owning PR sequentially once that path is available; omission
remains a readiness blocker.

The branch names below identify the first task in each lane. For a later task,
choose a new descriptive lane/task name under `cursor/` ending in `-40de`;
never reset or reuse a completed branch to start unrelated work. Preserve an
explicit maintainer-provided branch name. Every writer finishes with evidence
and stops; it must not self-merge, release its own lock, or silently launch a
successor. The coordinator admits the successor after integration.

### stdlib-collections

```text
Work only in eluvane/ouro; follow AGENTS.md and docs/agent_parallel.md.
Fetch origin/main and recheck paginated eluvane/ouro locks; sibling reservations apply before a PR exists.
Create branch cursor/stdlib-collections-20260921-40de from the recorded origin/main SHA, or reuse the reserved owner.
Reason: make split_at one traversal while preserving its existing API and results.
Write lock: std/collections.ouro.
Write lock: tests/practical_stdlib_tests.ouro; no other tracked files.
Read the current take/drop composition and existing collection tests first.
Fix only a reproduced owner defect or add the missing one-traversal coverage; do not invent a bug.
Win: sh scripts/ouro1.sh check std/collections.ouro
Win: sh scripts/ouro1.sh test tests/practical_stdlib_tests.ouro
Also run python3 scripts/api_baseline_regen.py --check; do not hand-edit generated API pages.
Warm T0/T1 is a measurement recipe, not a speed claim from a failed bootstrap.
Do not touch other std modules, compiler, runtime, tools, or shared inventories.
C is out: no C/H, stage0, clang flags, or host replacement.
Send proposed changelog text to wave-docs; leave CHANGELOG.md unedited.
Open one focused PR, or continue the reserved owner if it already exists.
```

### test-discovery

```text
Work only in eluvane/ouro; follow AGENTS.md and docs/agent_parallel.md.
Fetch origin/main and recheck live eluvane/ouro PR file locks before writing.
Reuse the reserved owner and current PR when present; otherwise create cursor/test-discovery-20260921-40de.
Reason: prove exact-budget completion and refusal after a late inventory error.
Write lock: tools/test/discovery.ouro.
Write lock: tests/native_test_discovery_tests.ouro; no other tracked files.
Read both owners and the existing discovery assertions before changing behavior.
Preserve root order, repeated roots, literal explicit paths, and current pruning.
Test a failure after earlier files were collected; require error, not partial success.
Test completion exactly at the walk budget without increasing that budget.
Fix the owner only if the new regression demonstrates a defect; retain every old case.
Win: sh scripts/ouro1.sh test tests/native_test_discovery_tests.ouro
Then run sh scripts/test_suite.sh.
On Windows also run sh scripts/test_suite.sh --native-tools _build/native.
Do not touch tools/test/suites.ouro, tools/test/sample_cases.ouro, shared assertions, policies, or compiler files.
C is out: no C/H, stage0, host traversal replacement, clang flags, or arena work.
Keep the existing runner; do not add a new gate, linter, or parallel discovery product.
Send proposed changelog text to wave-docs; stop on any new path collision.
```

### native-capture

```text
Work only in eluvane/ouro; follow AGENTS.md and docs/agent_parallel.md.
Fetch origin/main and recheck live eluvane/ouro locks; do not treat historical ouro-dev numbers as owners.
Reuse the reserved owner and current PR when present; otherwise create cursor/native-capture-20260921-40de.
Reason: failure-then-success reuse must not retain stale capture state or output.
Write lock: runtime/platform/windows_process_bounded.ouro.
Write lock: tests/native_managed/process_bounded.ouro; no other tracked files.
Read capture cleanup/result ownership and the existing --reuse probe first.
Extend --reuse with failure-then-success assertions, retaining successful-repeat coverage.
Fix only a reproduced defect in the locked Ouro runtime owner; preserve the capture ABI.
Win: sh scripts/ouro1.sh build tests/native_managed/process_bounded.ouro
Win: run the native-capture acceptance block in docs/agent_parallel.md on Windows.
Require exit 42, exact CAPTURE_OK markers, empty stderr, and unchanged existing caps.
Also run sh scripts/runtime_io_suite.sh; keep broader required process coverage.
A missing Windows run or compiler failure is a blocker, never native acceptance.
Linux hosts cannot execute the PE probe; that absence is Not run, not a pass.
Do not touch compiler/native/managed_*, other platform helpers, std/process*, or budgets.
C is out: no runtime C/H, stage0, clang flags, C arenas, or alternate host path.
Send proposed changelog text to wave-docs; leave CHANGELOG.md unedited.
```

### source-syntax

```text
Work only in eluvane/ouro; follow AGENTS.md and docs/agent_parallel.md.
Fetch origin/main and recheck paginated eluvane/ouro locks before writing.
Reuse the reserved owner and current PR when present; otherwise create cursor/source-syntax-20260921-40de.
Reason: add or tighten one existing-syntax parse/rejection regression without inventing syntax.
Write lock: tests/compiler_native_syntax_tests.ouro; no other tracked files.
Read the existing native syntax tests and nearby parser contract first.
Do not edit lexer/parser source, file_elab*, compiler/native, formatter, or diagnostic IDs.
Fix only a reproduced test-local gap; an accepted RFC is required before any syntax change.
Win: sh scripts/ouro1.sh test tests/compiler_native_syntax_tests.ouro
Also run sh scripts/frontend_security_suite.sh and sh scripts/test_suite.sh --compiler-checking.
C is out: no C/H, stage0, clang flags, or host parser replacement.
Send proposed changelog text to wave-docs; leave shared metadata unedited.
```

### checked-native

```text
Work only in eluvane/ouro; follow AGENTS.md and docs/agent_parallel.md.
Fetch origin/main and recheck paginated eluvane/ouro locks; compiler source is not reserved here.
Create branch cursor/checked-native-20260921-40de from the recorded origin/main SHA, or reuse the reserved owner.
Reason: close one checked-program-to-native acceptance or diagnostic gap with positive and rejection evidence.
Write lock: tests/compiler_module_tests.ouro; no other tracked files.
Read the existing module tests and the selected check/eval/run contract first.
Do not edit compiler/native source, lexer/parser, stage0, or C hosts.
If the gap requires a compiler-source change, stop and report that blocker.
Win: sh scripts/test_suite.sh --compiler-checking
Also run sh scripts/frontend_security_suite.sh and sh scripts/ouro_repo_gate.sh --profile compiler-boundary.
Reproduce the selected case; Windows PE execution unavailable on Linux is Not run, not a pass.
Send proposed changelog text to wave-docs; leave CHANGELOG.md unedited.
```

### format

```text
Work only in eluvane/ouro; follow AGENTS.md and docs/agent_parallel.md.
Fetch origin/main and recheck live eluvane/ouro locks before writing.
Reuse the reserved owner and current PR when present; otherwise create cursor/format-20260921-40de.
Reason: preserve source bytes and checked write refusal for one concrete formatting case.
Write lock: tools/fmt.ouro.
Write lock: tools/fmt_pipeline.ouro.
Write lock: tests/analyze/precision/format_fix.ouro; no other tracked files.
Read the formatter, pipeline, and precision fixture before changing behavior.
Do not touch parser, checker, shared fixer paths, lint IDs, or formatting policy.
Win: sh scripts/fmt_suite.sh
Also run sh scripts/fix_suite.sh and keep original/candidate rejection plus repeat-write evidence.
C is out: no C/H, stage0, clang flags, or host formatter replacement.
Send proposed changelog text to wave-docs; leave CHANGELOG.md unedited.
```

### packages

```text
Work only in eluvane/ouro; follow AGENTS.md and docs/agent_parallel.md.
Fetch origin/main and recheck paginated eluvane/ouro locks; historical ouro-dev package PRs are not owners here.
Reuse the reserved owner and current PR when present; otherwise create cursor/packages-20260921-40de.
Reason: make one existing local-registry/vendor/verify workflow reliably usable.
Write lock: tools/pkg/main.ouro.
Write lock: tools/pkg/model.ouro.
Write lock: tools/pkg/security.ouro.
Write lock: scripts/pkg_suite.sh.
Write lock: docs/pkg.md; no other tracked files.
Read the current package contract and suite first; do not restore retired collector or selfhost paths.
Win: sh scripts/pkg_suite.sh
On Windows also run sh scripts/pkg_suite.sh --native-tools _build/native.
Do not touch LSP, compiler imports, scripts/coil.sh, other docs, or invented pkg: imports.
C is out: no C/H, stage0, clang flags, or host package replacement.
Send proposed changelog text to wave-docs; leave CHANGELOG.md unedited.
```

### lsp

```text
Work only in eluvane/ouro; follow AGENTS.md and docs/agent_parallel.md.
Fetch origin/main and recheck paginated eluvane/ouro locks; sibling reservations apply before a PR exists.
Create branch cursor/lsp-20260921-40de from the recorded origin/main SHA, or reuse the reserved owner.
Reason: fix one user-visible diagnostic or request-state contract through the existing server.
Write lock: tools/lsp_model.ouro.
Write lock: tools/lsp_process_model.ouro.
Write lock: scripts/lsp_suite.sh; no other tracked files.
Read the model, process model, and suite first; do not add a second server.
Do not touch checker, formatter, package resolver, tools/lsp.ouro, or editor manifests.
Win: sh scripts/lsp_suite.sh
On Windows also run sh scripts/lsp_suite.sh --native-tools _build/native.
C is out: no C/H, stage0, clang flags, or host language-server replacement.
Send proposed changelog text to wave-docs; leave CHANGELOG.md unedited.
```

### native-samples

```text
Work only in eluvane/ouro; follow AGENTS.md and docs/agent_parallel.md.
Fetch origin/main and refresh eluvane/ouro locks; do not reserve all of samples/.
Reuse the reserved owner and current PR when present; otherwise create cursor/native-samples-20260921-40de.
Reason: make the existing CLI/file example reproducible as a native user workflow.
Write lock: samples/examples/practical_cli_file.ouro.
Write lock: samples/examples/README.md; no other tracked files.
Read the sample and its check-only row in tools/test/sample_cases.ouro.
Run success, missing-argument, and missing-file cases through the emitted PE.
Preserve exit 0/2/1 and stdout/stderr separation; do not invent new syntax or APIs.
Win: sh scripts/ouro1.sh check samples/examples/practical_cli_file.ouro
Win: run the native-sample acceptance block in docs/agent_parallel.md on Windows.
Also run sh scripts/samples_suite.sh --native-tools _build/native.
Document only commands actually observed; a check-only inventory is not a runtime pass.
Linux PE execution is unavailable and is Not run, not a pass.
Change sample code only for a reproduced sample-local problem, not cosmetic churn.
Do not touch other samples, sample/test inventories, std, compiler, runtime, or docs/README.md.
C is out: no C/H, stage0, clang flags, host executable fallback, or C arenas.
If the native backend fails, stop rather than repair an unreserved compiler path.
Send proposed changelog text to wave-docs and keep shared metadata read-only.
```

### wave-docs

```text
Work only in eluvane/ouro; follow AGENTS.md and docs/agent_parallel.md.
Fetch origin/main, capture paginated live locks scoped to eluvane/ouro, and inspect recent merges.
Reuse the current docs PR when this page is already owned; do not open a duplicate.
Otherwise create branch cursor/wave-docs-20260921-40de from the recorded origin/main SHA.
Reason: keep one current, operable language-work allocation page for this repository.
Write lock: docs/agent_parallel.md, docs/README.md, and CHANGELOG.md.
Read current architecture, native direction, actual commands, and live eluvane/ouro owners.
Maintain rolling refill, WIP limits, review/merge/handoff, and current locks; no pass history.
Separate dated evidence from current admissions; stale snapshots are not dispatch authority.
Keep reserved lanes unavailable, with exact narrow write sets and measurable outcomes.
Keep shared docs/quality.md, AGENTS policy, generated docs, and other lane files read-only.
Win: python3 scripts/docs_examples_gate.py
Win: python3 scripts/github_project_gate.py
Add the required short Unreleased docs bullet in this wave; other lanes propose text only.
Do not touch compiler, runtime, tools, scripts, tests, or additional documentation files.
C is out: do not recommend C hosts, stage0 edits, clang tuning, or C-arena investment.
Do not claim validation or performance that was not executed on the reported tree.
Open one docs PR explaining what changed and why; mention remaining blockers
only when they affect the change. Keep exact base/head in the coordination handoff.
```

## 4. How to burn fewer hours

### Choose a bounded reason before assigning a model

[AGENTS.md](../AGENTS.md) says: **“A good PR has one reason to exist.”** Write that
reason as an observable difference: one wrong rejection fixed, one native
operation completing with the right error/cleanup behavior, one stdlib traversal
removed without changed results, or one runnable package/example workflow.
Do not send ten agents the same broad assignment and ask them to discover ownership
while editing. Read the imports and existing regression owner before choosing a
file lock. A dependency cone is relevant to testing; it is not an automatic
write reservation for all dependencies.

`split_at` in [std/collections.ouro](../std/collections.ouro) currently composes
`take` and `drop`; that is a
concrete optimization experiment. The discovery tests explicitly retain repeated
roots; removing duplicates there is not automatically a bug fix. The native
capture probe checks real exit/status/bytes, not a synthetic success banner.
Use these distinctions to reject vague “polish the entire language” assignments.

### Make metadata a serialized resource

Give the rolling coordinator scheduling ownership of `CHANGELOG.md`,
`docs/quality.md`, and `docs/README.md`. During this wave, `wave-docs` is the
only writer of shared `CHANGELOG.md`; other lanes return proposed text and
leave that path unedited. The coordinator owns the *right to schedule* those
writes, not a simultaneous exception to live PR locks. Add required metadata
to the owning PR only after its predecessor merges or a recorded handoff
releases the path. Rebase before adding it. A missing required changelog entry
keeps the PR draft; it does not become an allowed omission because the code
lane is otherwise done.

Generated API pages, API baselines, diagnostic registries, fixture manifests,
and shared test inventories need the same single-owner treatment when a change
requires them. Reserve planned fixture registrations as well as fixture files: two
agents adding separate tests can still collide in `tools/test/suites.ouro` or
`tools/test/sample_cases.ouro`. A test not executed by its intended acceptance
path is not completed coverage. Prefer API-preserving work while metadata is held.
Never hand-edit `docs/api/` or bootstrap artifacts to avoid coordination; use the documented
generator only in its authorized lane, and retain drift checks.

### Establish a warm, successful T0

Use a separate worktree and private `_build` for each writer. For performance
work, complete required preparation first and verify the focused command
succeeds on unchanged main; correctness reproductions are distinguished below. Reuse validated warm build outputs through the existing freshness/receipt
checks, not arbitrary installed binaries. Do not symlink different worktrees to
one writable `_build` or copy a result receipt to label a new source tree green.
Existing content-addressed caches may accelerate work only through their actual
validation protocol. Never let two processes publish to the same output path.
Schedule heavy tests by actual host RAM and CPU, not the number of agents.

Maintain separate queues for writing, expensive execution, and maintainer review.
Start with one heavy build/test job per shared host until measured aggregate RAM
and CPU headroom justify more. Ten PRs do not imply ten bootstrap chains, ten
full PR profiles, or ten Windows native suites at once. Keep suite processes
isolated: [CI](ci.md) documents fixed output paths and explicit native candidate
provisioning. A free editing slot is not permission to overcommit test workers.
If review or Windows execution is backing up, finish that work or lower admission
rather than fill the board with more unvalidated diffs.

Do **not** await `python3 scripts/ci_gate.py --profile pr` at T0. Inspect its
inventory with `python3 scripts/ci_gate.py --profile pr --list`, then establish
the lane's focused behavior and resource baseline. Listing gates is not running
them. This changes the order of work, not the mandatory checks before readiness.
For a correctness fix, the target regression is expected to fail at T0; capture
its exact failure and run healthy adjacent controls. That is a valid bug
reproduction, not a successful performance baseline. Do not claim a speedup from
a failed T0, even when the failed command is the bug being fixed.

For a performance change, freeze workload bytes, argv, compiler configuration,
resource limits, environment, concurrency, and cache state. Record producer and
candidate executable identities: a compiler optimization may change the
candidate binary, so compare source-bound base/head builds with the same declared
build inputs except the intended change. Do not demand identical compiler bytes
while claiming to measure a changed compiler. Run at least three
successful warm samples at T0 and T1. The existing measurement wrapper can record
a focused stdlib run; this is a measurement recipe, not a second writer on
the reserved `stdlib-collections` slot. Use separate
directories for baseline and candidate:

```sh
mkdir -p _build/parallel/T0
for n in 1 2 3; do
  python3 scripts/memory_watch.py --label stdlib-collections-T0 \
    --json "_build/parallel/T0/stdlib-$n.json" -- \
    sh scripts/ouro1.sh test tests/practical_stdlib_tests.ouro
done
```

Repeat with `T1` only after warming the candidate. For a meaningful speed claim,
run the **same** workload on both trees: new candidate assertions cannot silently
replace the T0 workload. Keep the benchmark input separately fixed while adding
regressions. Report correctness results independently from timing. A small test
may be dominated by process launch; in that case report the traversal reduction
without claiming a measured speedup.

A cold bootstrap failure lasting ten minutes is **not T0 for successful lint or
native execution**. Record it as setup failure, retain the error, and stop or
move execution to a suitable host. Do not divide that duration by a warm success.
Record wall time, peak RSS and its measurement scope, status, and selected-file
or test counts. Tree RSS for two workers is not a single worker's peak. Preserve
all budgets; no `ALLOW_UNBOUNDED`, higher caps, smaller fixtures, or warn-only
conversion to manufacture an improvement.

### Bound sub-agent writing and stop early

Use at most about **three writers inside a lane**, each with different files;
more read-only reviewers need no write leases. This is not permission for three
writers to share one source file. Reserve tests separately from production code,
and keep one integrator for the branch. Terminate a sub-agent's writing task as
soon as it tries to add suppressions, baseline debt, allowlists, warn-only
success, or severity downgrades to clear a gate.

Stop a lane when it needs a reserved path, a public/API/ABI or syntax change beyond
its agreement, an OOM “fix” that raises a budget, a fixture deletion, a stale or
mixed-binary baseline, a new Python/C semantic owner, or unavailable mandatory
execution. Save the reproduction and exact blocker; do not spend the remaining
hours rewriting adjacent systems. A regression that already passes may justify
focused coverage, not an invented production bug or unrelated refactor.

No lane may become repo-wide cleanup, another Clippy product, hand-edited stage0,
“delete C this week,” C-arena work, clang-flag tuning, or Linux ELF development
before the locked Windows-native slice is accepted. Follow the actual
[roadmap](roadmap.md); this page does not create new stages or syntax approval.

## 5. Review, merge, and replenish

### Follow dependencies, not completion order or a wave barrier

The sequence below is a **partial order**, not "finish every row, then begin the
next wave". An independent ready PR can proceed while a slower area stays held.
Never merge an unverified broad PR merely to release its file locks.

| Area | What can proceed independently | What must wait |
| --- | --- | --- |
| Test discovery, native sample recipe | Their exact reserved files and unchanged interfaces. | Their own required checks and serialized metadata; a compiler-source failure is a blocker, not a C workaround. |
| Native capture | Its reserved runtime/fixture pair with unchanged capture ABI and real Windows execution. | Managed-lowering or helper-contract changes outside this write set; Linux PE execution is Not run. |
| Collections | Its reserved collections/test pair and unchanged public API. | Generated API pages and shared baselines if they must change; those stay separately reserved. |
| Checker/native/PE and parser | Only a later exact write set after a refreshed live-lock check. | Shared checker/representation/ID contracts before dependent consumers. This wave reserves tests, not those source cones. |
| Formatter and LSP | Their reserved files when interfaces stay unchanged. | Formatter contract before an LSP task relying on changed edits. |
| Packages | The reserved package files for a local workflow that does not require an unmerged compiler change. | Current paths and docs; no resurrection of retired `selfhost` owners. |
| This docs page | Continue the reserved `wave-docs` owner; keep the procedure usable while other tasks run. | Its required changelog entry and docs gates; no second playbook PR. |
| New syntax or acceptance semantics | Read-only investigation and the required design discussion. | Accepted RFC/maintainer decision and coordinated parser, checker, formatter, and editor ownership. |

### Prepare one reviewable candidate

Keep one branch and one PR for the admitted reason. Before requesting review,
stop adding unrelated improvements and prepare a handoff containing the task
card, exact base/head, diff inventory, reproduction, focused results, adjacent
results, remaining required checks, compatibility/TCB impact, and proposed
shared metadata. Link small relevant logs; do not paste megabytes of successful
output. A command name without its result and source identity is not evidence.

The reviewer starts from the code and regression, not the author's summary.
Require every changed file to serve the stated reason and every claimed fix to
have an observed reproduction or a clearly stated execution limitation. Review
negative assertions and golden changes separately: unchanged counts alone do not
prove retained coverage. Check new imports for shared-interface and memory
impact, not only textual merge conflicts. Record exactly which head was reviewed.

Use a fresh read-only reviewer when useful; the maintainer retains semantic,
trust-boundary, merge, and cancellation decisions. Review feedback goes back to
the current owner on the same branch. After any code or relevant metadata change,
refresh the head, rerun affected validation, and renew affected review. Do not
carry an old approval or green run forward as evidence for new bytes.

A compact reviewer brief:

```text
Review only the supplied Ouro PR and exact head; follow AGENTS.md.
Read its task card, current main, live locks, actual diff, and nearby contracts.
Do not edit files, merge, change labels, or launch another implementation PR.
Check that every changed file serves the single stated outcome and reservation.
Inspect the original reproduction and positive/negative regression expectations.
Reject fixture deletion, weakened assertions, allow/debt/warn-only green paths.
Check compiler acceptance, raw/managed ABI, error, and cleanup boundaries if touched.
Check cross-file consumers even when the diff has no textual conflicts.
Verify that new tests are exercised by the intended suite, not just present.
Match results to the reported head, producer, backend, host, and resource limits.
Separate hosted checker passes from Windows PE execution and bootstrap evidence.
Check required docs/changelog and generated-output provenance without editing them.
For performance, require comparable warm inputs and correct result/coverage first.
Report blockers with exact path, behavior, evidence, and focused reproduction command.
Return a reviewed head and unresolved risks; lack of findings is not a test pass.
```

### Serialize final metadata and integration

The coordinator services shared metadata **one PR at a time**. After the previous
holder releases `CHANGELOG.md`, fetch main, add the next candidate's required
Unreleased bullet to that same PR, run affected docs checks, and complete its
review/merge before granting the path to another PR. Do not create ten competing
changelog diffs or put all features' required documentation in a later umbrella
PR. Apply the same rule to a shared API index, fixture registry, or diagnostic
schema when it must change. Necessary documentation stays with its behavior.

Before merging, inspect the candidate in a clean review checkout. In this
maintainer command block, set `PR` to the candidate's actual number:

```sh
set -eu
: "${PR:?Set PR to the candidate pull request number}"
git fetch origin main
gh pr view "$PR" --json number,state,isDraft,headRefOid,baseRefName,url
gh pr diff "$PR" --name-only
gh pr checks "$PR"
```

Reconcile those files with the complete lock snapshot from section 1 and the
reserved write set; the name-only view is a review convenience, not the
rename-aware lock authority. Confirm the exact reviewed head and intended base,
all prerequisites merged, no outstanding blocking review, required metadata
present, and applicable checks complete on the final candidate/integration
state. A successful `gh pr checks` query is not proof that every repository-
required check exists; compare with [CI](ci.md) and the selected gate inventory.
Skipped, absent, pending, timed-out, OOM, and infrastructure-failed jobs are not
passing checks. Do not infer billing causes from a job with no executed steps.

Run the lane's focused commands first, then its adjacent contracts and the
required readiness validation from [AGENTS](../AGENTS.md) and [CI](ci.md). Use
the full PR profile when feasible before opening a PR, and complete the required
review-time validation on a suitable host when it was unavailable. No new
"parallel mode" replaces existing requirements. Compiler/checker work retains
the kernel profile, relevant boundary tests, and bootstrap/drift obligations;
PE/runtime work additionally needs actual target execution. The lane's win
command is necessary but never substitutes for those obligations.

If the relevant base or shared contract advanced, stop the branch's writers,
fetch, and rebase that owned branch onto current main. Review conflict resolutions
and rerun affected checks; a rebase is not a validation result. Do not rebase all
ten PRs for every unrelated docs merge. The maintainer decides which unchanged
results remain applicable, while final integration checks still follow repository
policy. Never resolve with blanket "ours/theirs", restore retired paths, or
force-push another owner's branch. A necessary rewrite of your own branch uses
an expected remote head/lease and coordinated stopped writers, not blind force.

The maintainer merges using the repository's allowed method after these checks.
Automation must not self-merge unless explicitly authorized. A changed head
invalidates the recorded merge decision; recheck rather than merge whichever
commit happened to arrive last. Keep integration decisions sequential even while
implementation and tests run in parallel. Do not add a merge bot or weaken
branch/CI protection to make this procedure convenient.

### Release and immediately admit the successor

After a merge, fetch `origin/main`, record its SHA and the actual merged result,
and verify the focused affected-path smoke on that tree. This is not another
mandatory full ten-PR bootstrap cycle. For squash/rebase merges, compare the
resulting diff and behavior; the old feature head need not be a main ancestor.
When that integration is sound, stop the old writer, retain its evidence, refresh
open PR locks plus unpublished reservations, and release only paths with no
remaining owner. Then reserve the next eligible task immediately. Do not wait
for the other nine to merge.

Use a new branch from that refreshed main, a new task-specific write set, and a
new baseline. Do not append the next task to the just-merged branch, inherit its
old executable receipts, or reuse its performance numbers as the next task's T0.
The successor may reuse validated caches through normal tooling; it cannot reuse
a predecessor's acceptance verdict. Reopen no closed PR merely to recycle a name.

The following is an illustrative sequence, **not a claim that these PRs exist**:

```text
Nine other tasks remain unfinished; discovery-A finishes review and merges.
Fetch main; discovery-A's affected-path smoke passes; refresh all reservations.
Discovery-B has a useful ready outcome and no file/interface collision.
Reserve B, start its new branch from main, and keep the other nine unchanged.
If B needs an unmerged checker contract, leave B in backlog instead.
Admit a ready task in another free area, or leave the capacity unused.
If A's integration fails, repair that area before starting its next feature.
```

### Handle collisions, stalls, and regressions

For a file collision, freeze the later writer and choose one owner. Merge the
reviewed predecessor, remove an accidental overlap, or explicitly abandon/split
work with maintainer approval; never race two PRs to main. A changed PR title,
sleeping agent, or removed board row does not remove its live diff's lock.
A stale owner must acknowledge stopping before another agent inherits its branch.
Do not automatically steal a lease because a timer expired.

For a design or shared-interface dependency, pause implementation before writing
speculative consumers. Keep the task BLOCKED with a concrete unblock condition;
read-only review or reproduction can continue. If prolonged blocking makes it
unworthwhile, preserve the reproduction and ask the maintainer to cancel the task
explicitly. Do not close/relabel someone else's PR without authorization. An
open parked draft keeps its file locks; moving it off a board cannot free them.

For resource or infrastructure failure, distinguish preparation, execution,
coverage, and hosting failures. Assign one root-cause investigation instead of
ten identical failed rebuilds. A shared bootstrap/checker regression pauses only
the tasks depending on it; independent docs or already runnable areas need not
stop. If it is unclear which paths are affected, stop admissions until scoped.
Keep mandatory failures visible; no cap increase, fixture shrink, suppression,
or C fallback buys a release of the slot.

For a regression after merge, quarantine dependent work, preserve the failing
input and offending revision, and let the maintainer choose a focused fix or
reviewed revert. Do not stack the next feature onto a known-broken base. Retain
tests when reverting; a revert that conflicts with subsequent work needs its own
review. Restart affected lanes only after the repaired main passes their relevant
checks. A closed-unmerged task frees capacity after explicit cleanup, but counts
as cancelled or investigated, never as a delivered capability.

### Maintainer handoff and throughput check

At each operating session, first reconcile actual heads and reservations, then
look for ready reviews/merges, stuck validation, scope growth, and available
execution capacity. Refill only after servicing those queues. At the end, record
each active task's owner, head, state, last evidence, next action, and blocker in
the existing task board/PRs. A replacement coordinator should not need old chat
history to discover who may edit a file. Keep one or two next tasks ready per
useful area, without starting their writers prematurely.

Use this coordinator brief for one scheduling iteration; it does not establish
an autonomous background service:

```text
Coordinate the current Ouro queue; follow AGENTS.md and docs/agent_parallel.md.
Scope every live-lock lookup to eluvane/ouro. Historical ouro-dev PR numbers are not current locks.
Read current main, every open PR file list, and unpublished task reservations.
Do not trust the previous chat's locks, completion claims, or cached green reports.
Count unfinished engineering tasks from reservation through integration, normally <=10.
Treat blocked, draft, review, and ready tasks as unfinished; bot locks still apply.
Service existing reviews, validation blockers, and metadata handoffs before admission.
Do not edit implementations or grant two writers the same path or changing interface.
For each integrated task, verify refreshed-main smoke and absence of remaining owners.
Release only that task's cleared paths; do not wait for the other nine tasks.
Select the most useful eligible backlog item, not filler for an empty directory.
Require a filled task card, exact files, win command, host, reviewer, and dependencies.
Preserve native-Ouro direction, RFC decisions, existing caps, tests, and generated policy.
No second quality-engine lane while the current quality owner remains active.
Reserve new work before dispatch; a blocked same-area successor can wait in backlog.
Use a new branch and baseline for each successor; never recycle a merged branch.
Return current state, evidence, blockers, and the next concrete action for each task.
Do not merge, close, cancel, or relabel PRs without the maintainer's authorization.
Stop when no useful task fits available ownership, execution, and review capacity.
```

Judge the queue over a rolling set of completed tasks, not a synchronized batch:
record delivered user/compiler outcomes, elapsed time from reservation to
integration, time blocked in review/validation, rebase work, resource use, and
post-merge regressions/reverts. Record investigation-only and cancelled tasks
separately. Do not rank progress by PR count, deleted lines, lint rule count, or
hours that agents appeared busy. If unfinished work keeps growing while merges
and validated capabilities do not, reduce admissions and finish existing work.
A healthy queue keeps useful independent work moving; it does not keep ten
writers occupied at any cost.

## 6. Anti-patterns seen in this repository

Use the linked evidence to recognize scheduling and measurement failures, not
to assign blame. The pull-request numbers in this table are historical
`eluvane/ouro-dev` observations at their stated revisions. They are not
current `eluvane/ouro` pull requests and do not lock files here.

| Do not do this | Historical `ouro-dev` evidence to inspect | Use this instead |
| --- | --- | --- |
| Launch another “unify/harden quality” pass over the same core and remap the same IDs. | [ouro-dev #28](https://github.com/eluvane/ouro-dev/pull/28), [ouro-dev #30](https://github.com/eluvane/ouro-dev/pull/30), [ouro-dev #31](https://github.com/eluvane/ouro-dev/pull/31), and historical ouro-dev #35 repeatedly address shared quality/frontend owners. That #35 also collided with ouro-dev #11 and #23 on exact files. | One existing quality owner; spend free hours on the disjoint language/user paths above. |
| Treat `--warn-only` project output as a deny-profile success. | [ouro-dev #32](https://github.com/eluvane/ouro-dev/pull/32) describes advisory scans and OOM; [ouro-dev #34](https://github.com/eluvane/ouro-dev/pull/34) distinguishes real `warn_only=false` evidence from failing wider scans. | Correct source or the responsible rule without suppressions; require the intended complete blocking profile and counts. |
| Build a 15 GiB Clippy cone, then buy apparent progress with larger limits or wider host flags. | [ouro-dev #29](https://github.com/eluvane/ouro-dev/pull/29) records approximately 15.6 GiB for the old monolithic cone. | Measure a bounded warm cone, reduce unnecessary dependencies in the existing owner, and preserve limits. No new C-host investment. |
| Describe recycle-after-1 as an in-process reset or sustained-memory solution. | [ouro-dev #34](https://github.com/eluvane/ouro-dev/pull/34) explicitly recycles lint children after each file; its per-child cache dies too. | Call it containment. Prove bounded lifetime/reset in the authorized native-Ouro owner before claiming reuse or removing isolation. |
| Report a speedup from T0 bootstrap failure to T1 warm lint. | Historical ouro-dev #34's table labels T0 as failed cold parallel bootstrap and T1 as warm; the broader lint path still has failures. | Same successful command, same input/caps, warm T0/T1, status and RSS scope reported separately. |
| Let one PR consume the entire native backend, then pretend its PE or managed subtrees are free. | Historical ouro-dev #35's file list includes elaboration, lowering, managed operations, MIR/codegen, and PE writers. | Mark the live owner reserved, finish or explicitly narrow it, then dispatch disjoint follow-ups after a new `eluvane/ouro` snapshot. |
| Call a mixed installed-binary/source run full-tree validation. | [ouro-dev #33](https://github.com/eluvane/ouro-dev/pull/33) records existing binaries plus a local relink and explicitly unconfirmed full post-change strict coverage. | Tie every result to one source/build identity. Missing or pre-step CI execution remains Not run, never green. |

The rolling queue must also avoid a batch barrier, a successor launched when
its predecessor is merely "agent done", ten blocked drafts hidden outside the
WIP count, and an eleventh task started instead of reviewing the first ten.
These are scheduling guardrails, not claims about a specific historical PR.

For this page itself, preserve the docs-only scope and run:

```sh
python3 scripts/docs_examples_gate.py
python3 scripts/github_project_gate.py
```

These wrappers execute the repository's native gate path. Text inspection,
Markdown formatting, or a file-list audit cannot substitute for their execution.
