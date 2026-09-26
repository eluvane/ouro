# Continuous integration

Ouro keeps the authoritative validation commands in repository scripts. GitHub
Actions invokes the same profiles that contributors can run locally and uploads
reports from `_build/`.

## Validation matrix

Start with the suite for the changed layer. The PR profile is the broader local
check before review when feasible; a focused pass does not establish full PR
readiness. Missing host tools, timeouts, skipped probes, and incomplete reports
are not passes.

| Change | Focused command |
| --- | --- |
| Documentation and examples | `python3 scripts/docs_examples_gate.py` |
| Public repository metadata | `python3 scripts/github_project_gate.py` |
| Workflow policy | `python3 scripts/github_workflow_gate.py` |
| Formatter / fixer | `sh scripts/fmt_suite.sh` / `sh scripts/fix_suite.sh` |
| Linter / analyzer | `sh scripts/lint_suite.sh` / `sh scripts/analyze_precision_suite.sh` |
| Packages / LSP | `sh scripts/pkg_suite.sh` / `sh scripts/lsp_suite.sh` |
| Runtime and IO / samples | `sh scripts/runtime_io_suite.sh` / `sh scripts/samples_suite.sh` |
| User test runner | `sh scripts/test_suite.sh` |
| Compiler checking | `sh scripts/test_suite.sh --compiler-checking` and `python3 scripts/ci_gate.py --profile kernel --out _build/ci/kernel` |
| Generated API reference | Regenerate through [Build](build.md#generated-artifacts-and-stage-loop), then `sh scripts/doc_suite.sh` |
| Bootstrap or stage0 | [Stage-loop profile](#local-profiles); see [promotion](build.md#generated-artifacts-and-stage-loop) |

## Local profiles

[OuroSmith](ouro_smith.md) runs canonical Ouro Core laws and generated surface
checks in the aggregate's `smith` group. OCaml, opam, Dune, and independent
Python Core replay are retired from the required profiles. Nightly runs the
deeper generated profile after the stage-loop fixpoint gate; missing required
tools, incomplete results, and skipped checks cannot establish a passing run.

The normal pull-request profile is:

```sh
python3 scripts/ci_gate.py --profile pr --out _build/ci/pr
```

Other profiles are narrower or heavier:

```sh
python3 scripts/ci_gate.py --profile kernel --out _build/ci/kernel
python3 scripts/ci_gate.py --profile stage-loop --out _build/ci/stage-loop
python3 scripts/ci_gate.py --profile nightly --out _build/ci/nightly
```

List the gates in a profile without running them:

```sh
python3 scripts/ci_gate.py --profile pr --list
```

The complete local PR inventory has twenty-seven isolated groups. GitHub selects
affected groups and gates for reviewed tool paths; main-branch pushes, merge
queues and manual CI runs select the complete inventory except `lint`, which
runs in Nightly and on demand. Run one group with:

```sh
python3 scripts/ci_gate.py --profile pr --group checks
```

The group names are `checks`, `checks-parity`, `checks-quality`, `analysis`, `checker`, `analyzer`, `lint`,
`tests`, `smith`, `samples-1`, `samples-2`, and `compiler-1` through
`compiler-16`. Substitute the selected name after `--group`.

`--group` supports PR, nightly, manual, kernel, stage-loop, docs, and kernel-extra profiles.
`--list-groups` prints the selected profile's complete group list as JSON;
Manual and Release use that inventory to construct their hosted matrices.
Release metadata and assembly require every validation group to succeed.
Use isolated checkouts when running
groups concurrently: several suites own fixed fixture/output paths. The full
local command runs every gate in registry order. The runner rejects a group
inventory that omits, duplicates, or invents a gate; its self-test also checks
complete matrix coverage and the affected-path routing contracts. The
`analysis` group owns memory budgets, C analysis, and LSP; `checker` owns
hardening, scale, and depth; `analyzer` owns analyzer precision and
`lint-changed`. The complete Ouro lint suite runs in Nightly, the full
**Manual** workflow, and **Lint → Run workflow**; PR, push, merge-queue and
Release jobs exclude its group. A pull request instead runs `lint-changed`:
`ouro1 lint --deny` over the changed `.ouro` files that the complete suite's
production sweep would select from `std/`, `compiler/`, `tools/`, and
`samples/`. It reads the directory and file exclusions from
`tools/lint_worker.ouro` and `tools/quality/source.ouro`; the package sample
stays with the complete suite because it needs a vendored snapshot. Findings
that a change causes in unchanged files are left to Nightly. Without a routing
plan, as in local, Manual and Release runs, `lint-changed` is reported as
skipped and the complete `lint` group owns coverage. Local profiles and
`sh scripts/lint_suite.sh` retain the complete suite; Python/shell lint and the
other quality gates keep their existing schedules.
Execution removes the previous `ci-summary.json` before starting gates, so an
interrupted run leaves no old successful aggregate at the current report path.
The native CI runner also invalidates selected gate reports and the delegated
host-inventory report. Failure to remove a report stops execution; a directory
at a report path is never removed. Listing profiles does not change reports.
Manual and Release prepare the current compiler before running each validation
group, including when a restored compiler cache lacks its bootstrap evidence.
PR and Nightly validation jobs allow 120 minutes for the complete group;
per-program execution and memory limits remain separate. PR Linux jobs depend
on one `Host compiler` job, which restores or builds the compiler with its
complete bootstrap evidence and publishes a workflow-local artifact. Each
consumer checks the producer's SHA-256 and verifies the binary, current inputs,
host toolchain, and bootstrap evidence before running gates. Partial job retries
use the successful producer's artifact name, including its original attempt.
Release artifacts use the workflow run ID so branch names containing `/` remain
valid for uploads and downstream downloads.
OuroSmith compiler evidence requires all sixteen compiler gate commands and their
source-bound receipts. The shard runners must agree on the full inventory and
binary identity; their combined artifacts must cover every fixture exactly once.

Samples use two shards with separate output directories. The native selector
alternates native builds and check-only cases independently, preserving all
positive and negative cases. Each invocation checks that the shards cover the
full inventory exactly once, balance both kinds of case, and reject invalid
shard options. The standalone command still runs the full inventory:

```sh
sh scripts/samples_suite.sh
sh scripts/samples_suite.sh --shard=1/2
sh scripts/samples_suite.sh --shard=2/2
```

P6 native tool acceptance can run these retained assertions with explicitly
provisioned Windows x86-64 candidates. Put `coil.exe`, `ouro-fmt.exe`,
`ouro-lsp.exe`, `ouro-pkg.exe` and `ouro-test.exe` in one directory, following
[the standalone build commands](tooling.md#standalone-native-tools), and use
fresh output directories:

```sh
LSP_SUITE_OUT=_build/p6/lsp sh scripts/lsp_suite.sh --native-tools _build/native
PKG_SUITE_OUT=_build/p6/pkg sh scripts/pkg_suite.sh --native-tools _build/native
TEST_SUITE_OUT=_build/p6/test sh scripts/test_suite.sh --native-tools _build/native
SAMPLES_SUITE_OUT=_build/p6/samples sh scripts/samples_suite.sh --native-tools _build/native
```

Pass `--native-tools DIR` first; sample shard options and `--compiler-checking`
follow it. The separate `--native-build-collection` C harness rejects this
option. Each invocation checks the required sibling images, PE format and
system imports, records their SHA256 in `native-candidates.json`, and checks
that those images remain unchanged at completion. Missing or invalid native
candidates fail without a C fallback. Retain the direct-PE build receipts with
source and producer hashes beside this execution evidence; the candidate
snapshot alone does not establish how the images were built.

The launchers still use shell/Python for fixture preparation and observation.
The default C build selection remains available separately, and its results
must identify that backend. A generated-C candidate cannot exercise bounded
native capture. Hosted C-host suites set `OURO_TEST_CHECK` /
`OURO_HOSTED_COMPILER_WRAPPER` to `scripts/ouro1.sh` (and `OURO_TEST_BUILD` to
`scripts/build_tool.sh`) so test, LSP, package, sample, and Smith tool
processes invoke the current compiler without a Windows `coil.exe` sibling.
Existing suite assertions and required gates remain in place;
these explicit invocations do not establish native bootstrap or retire the
full PR profile.

Nightly uses `checks`, `analysis`, `analyzer`, `lint`, `tests`, `samples-1`, `samples-2`, `kernel`,
`trust`, and `compiler-1` through `compiler-16` groups. The `trust` job runs the stage-loop fixpoint/drift gate and
then the deeper OuroSmith profile in the same checkout. `Full` runs even after
a job failure and fails unless every matrix group succeeds. Reports are
uploaded separately as `nightly-<group>` artifacts. Hosted PR matrix jobs use static names `PR` and `Portable` so a skipped
matrix does not publish an unevaluated expression. When those jobs run,
GitHub appends the matrix value: `PR (checks)`, `PR (checks-parity)`,
`PR (checks-quality)`, `PR (analysis)`, `PR (checker)`,
`PR (analyzer)`, `PR (tests)`,
`PR (smith)`, `PR (samples-1)`, `PR (samples-2)`, `PR (compiler-1)` through
`PR (compiler-16)`, `Portable (ubuntu-latest)`,
and `Portable (macos-latest)`. Linux Portable uses the shared compiler;
macOS Portable restores its own cache and bootstrap evidence, then builds or
verifies `ouro1` before `kernel_hardening_suite.py`.
macOS keeps the inherited Python stack when the host CPython build rejects
`setrlimit(RLIMIT_STACK)`. Darwin also rejects finite `RLIMIT_AS` (EINVAL);
POSIX children on Linux still apply a sticky AS cap when the host allows it,
and fall back to a soft-only cap when a lowered hard value is rejected.
The hosted `Compiler kernel` job runs `--profile kernel-extra`: only the
kernel OuroSmith gate, which is absent from PR. The complete standalone
`--profile kernel` remains unchanged. A runner self-test requires the union
of PR and kernel-extra to cover every kernel gate, with no duplicated gates
in kernel-extra. All sixteen compiler shards run for compiler, runtime, standard
library, bootstrap, build infrastructure and unclassified changes.

The static `Kernel` check always runs and requires successful path selection,
compiler preparation, every selected PR or docs group, selected kernel checks,
Portable, and Editor. A failed, cancelled, or unexpectedly skipped selected
job fails this aggregate. Nightly prepares its compiler independently per group.
`scripts/apply_github_settings.py` recommends the stable required contexts
`Paths`, `Kernel`, `Editor`, and `Review`. When adopting the docs route, replace
required individual `PR (...)` and `Portable (...)` contexts in hosted branch
rules with `Kernel`; those matrix contexts do not exist when the matrix is
skipped. Editing the script does not apply hosted settings.

Changes confined to `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, or ordinary
Markdown under `docs/` use the `docs` profile: workflow/project policy, API
baseline drift, documentation suite, and documentation examples. Editor and
site changes keep their own checks when combined with docs. Generated API
pages, generated hashes, executable examples, trust/build/CI/release/design
documents and unknown paths retain full PR validation. Empty or unavailable
diffs select full validation. A docs-and-code change includes all docs gates.

```sh
python3 scripts/ci_gate.py --profile docs --out _build/ci/docs
```

### Affected PR checks

`Paths` first runs the CI runner's self-tests, before compiler builds. It then
compares the PR base with GitHub's tested merge commit. The NUL-delimited local
Git diff has no API file-list limit; rename detection is disabled so both the
old and new path contribute to selection. Missing revisions, Git errors,
timeouts, oversized output, or an empty diff select complete validation.

The explicit routing table in `scripts/ci_gate.py` currently covers these inputs:

| Changed area | Additional checks |
| --- | --- |
| Formatter, fixer, analyzer, analyzer fixtures and their suite launchers | Formatter, fixer, analyzer precision, memory budgets, LSP and language/tool integration |
| Package manager, scanner fixtures and package suite launcher | Package suite and applicable release packaging checks |
| LSP implementation and suite launcher | LSP protocol suite |
| Documentation generator and suite launcher | Documentation and LSP suites, which share the document model |

Every code route retains repository policy, Python/shell lint, API drift,
generated hashes, compiler boundary, strict and structural quality, documentation
examples, hygiene, and the test/Smith/sample integration suites. The local plan
also retains the complete lint gate, which the hosted matrix excludes; a route
that changes production `.ouro` sources selects `lint-changed`. The table
selects existing gates; it does not change their assertions or profiles.
Unlisted files select the complete PR inventory and portable checks. Changes
to compiler, runtime and standard library inputs also retain kernel-extra.

For narrowed routes, the planner follows transitive imports from the canonical
compiler fixture inventory, using the build system's import reader and checking
its import count against the existing source tokenizer. A tool
dependency of a compiler fixture adds that fixture's existing round-robin shard.
An unreadable dependency, unsupported import layout or inventory shape selects
full validation.
New tool families remain full-validation inputs until their consumers are mapped.

The job outputs contain the changed paths, a dynamic matrix and a digest of the
complete selection. Each consumer recomputes the decision from its checkout and
requires the same digest. Invalid JSON, an empty selected group, or disagreement
with the producer is an error. `Kernel` still requires every selected job to
succeed; a skipped required job or failed/cancelled matrix cannot satisfy it.
Do not require individual dynamic matrix names in branch protection.

The GitHub job summary lists selected groups and gates. Full runs enqueue the
three long check groups and compiler shards first. PR matrix jobs cancel remaining siblings after a
failure, and each group stops at its first blocking failure while recording
unexecuted gates as `not_run`. Nightly and ordinary local profiles still gather
all failures. Obsolete runs are cancelled by the existing concurrency group.
The already-compressed compiler archive uploads with `compression-level: 0`.

`merge_group` and manual dispatch use the complete inventory, as do pushes to
`main`/`master`; this also refreshes trusted caches after a merge. Supporting
the event does not enable a repository merge queue or change branch protection.

GitHub references: [dynamic matrices](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/run-job-variations),
[required checks and skipped workflows](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks),
and [artifact compression](https://github.com/actions/upload-artifact#altering-compressions-level-speed-v-size).

Focused suites remain the fastest way to iterate. The Python PR profile is still
the final local composition before review until `pr-native` parity is explicitly
declared sufficient for a narrower change. Its supported docs, project, and
workflow policy rows now invoke `sh scripts/ouro_repo_gate.sh --profile
docs-native`, `project-native`, and `workflow-native` directly instead of the
legacy Python compatibility wrappers.

The parity suite requires acceptance on both host and direct paths for its
positive programs, including `compiler/extract.ouro`. Equal rejection statuses
fail the suite. Generated negative compiler cases keep their separate exact
diagnostic contracts in OuroSmith.

The sixteen `compiler-checking-1` through `compiler-checking-16` gates are required
in PR, nightly, manual, and `kernel` profiles. Their Ouro-owned fixture inventory is in
`tools/test/suites.ouro`; it checks, builds, and executes the compiler laws,
constructor-closure laws, native x86-64 encoding, MIR, PE, lowering, GC metadata,
liveness assertions, and related runner regressions. Support-only fixture
modules are checked through their imports. These assertions currently execute
through the transitional C bootstrap; they do not run the emitted Windows
executables. A failed checker process cannot pass
by printing `CHECK_OK`. Missing C tools and any check, build, or assertion
failure block this suite; it does not require OCaml. The property executable
runs its scoped and typed domains in sequential children when both are
requested, using the existing native/hosted test-process boundary. The hosted
suite provides `OURO_TEST_CHECK` and an outer process-tree budget. The default
retains all 400 + 400 cases, 12 fixed shapes, every-reference mutations and its
six-line report. Child failure or incomplete coverage cannot produce the
combined success report. This isolates the transitional C host's arenas without
changing checker laws or memory budgets. Bounded capture adds
29 pure API laws alongside the 9 compiler binding and 4 primitive registry
laws. These check byte preservation, tagged failures, exact child status,
limit validation, and primitive identity; they do not prove Windows Job
enforcement or descendant cleanup.

```sh
sh scripts/test_suite.sh --compiler-checking
sh scripts/test_suite.sh --compiler-checking --list
sh scripts/test_suite.sh --compiler-checking --shard=1/16
```

The native-lowering fixture runs each assertion in a separate process to bound
the transitional C host's compiler heap. It retains the full case inventory,
rejects duplicate names, and requires each child's exact output and zero status.

Each invocation verifies that the sixteen round-robin shards cover every fixture
exactly once, have unique fixture names and paths, and differ in size by at
most one. Missing, duplicated, unknown, or malformed selections fail. Omitting
`--shard` runs the full inventory. Each hosted shard has its own output directory
and retains the same checker, build, execution, and failure requirements.
The inventory interleaves fixtures by measured native build cost so expensive
fixtures fall in different shards. Timing estimates affect ordering only;
they never select which assertions run or relax a timeout.

The command uses the configured bootstrap in `OURO_C_BUILD_DIR`, runs builds
with one worker, and writes logs under `_build/compiler_check_suite` (or
`TEST_SUITE_OUT`). The full unsharded gate remains registered in the Ouro-native `suite-native`
profile. User-test and stage-loop gates remain separate.

On Windows, the required frontend-security host suite also uses its freshly
built `n1-host` to emit the 29 bounded-process API laws, runtime fixture, and
denied-commit child as direct PE32+ images. All 32 host probes
remain required, including reachability/flow-round fuel, error-payload and nested
allocation and PE patch-plan lifetime checks. Default-quiet host progress and
unchanged failure diagnostics are checked separately. The native section requires all 29 API result lines in
order, including the two separate `capture cap` laws, 13 runtime cases, and
5 source-helper rejections after successful source checking and rechecking. The cases cover
exact captured bytes and binary stdin, deferred/reused actions, child status
73 and 259, invalid limits, launch failure, memory denial, output caps,
timeout, descendant completion, and parent termination.

The same fresh host also builds the exclusive-directory API laws and native
probe from their complete current source closures. The Windows path requires
all 19 law lines and all 14 runtime rows: new/existing directory, existing
file, missing parent, eight conversion/allocation/cleanup fault cases, and
two contenders released only after both observed absence. Exactly one may
create the directory and publish its marker. Existing bytes, fault outcomes
and the winner's marker are read back after the worker exits. The original
one-CPU, 768 MiB aggregate worker budget, 240-second total and 20-second case
deadlines remain in force. Source, producer, PE/import and output hashes stay
bound to this invocation; unavailable Windows support is reported explicitly
and cannot establish native acceptance. The existing runtime/IO suite remains
required separately.

The same Windows invocation builds the sleep probe and two source-fault variants
with this fresh host. Each variant has a copied current import closure and an
exact source/producer/input/PE receipt; the original image must import
`kernel32.dll!Sleep`. All 11 runtime rows are required: zero delay, one-second
delay, delayed action, repeated execution of one action, eight precision laws,
two wide-Nat waits, and both conversion-failure branches with zero and delayed
actions. The worker compares exact stdout/stderr bytes and exit codes. External
observation requires each one-second interval to last 0.85–12 seconds and action
construction and zero delay to take at most 0.80 seconds. Each wide value must
remain running for at least 1.30 seconds after construction, then the harness
terminates it; this is not evidence that the full large delay completed.
The worker inherits the suite's one-CPU limit and has a 768 MiB aggregate budget,
a 120-second deadline and 15-second case deadlines. Host descheduling can fail a
timing assertion. The source-fault copies leave repository sources unchanged.
These are direct-PE runtime checks with a Python observer and a C-hosted producer;
they do not establish native bootstrap or isolated-host acceptance.

The Python observer retains descendant handles before cancellation and
checks their signaled state before closing the outer supervising Job.
Memory events, timeouts, malformed verdicts, changed inputs, and missing
images fail; `ENFORCEMENT_GAP` cannot count as an expected child failure.
The source closures, producer, PE machine/imports, images, and byte reports
are recorded under `host-*/native-process/`. These checks use one CPU and
the configured outer memory limit (3 GiB by default). POSIX retains the
strict host probes and records the Windows runtime section as unavailable
with zero native rows. This transitional Python supervision and C producer
do not establish native bootstrap or an isolated-host release.

The `compiler-boundary` gate is required in the PR `tests` group, nightly,
manual, and kernel profiles, and in the Ouro `suite-native` and `pr-native`
profiles. It checks the documented pure-checker import allowlist, the owners
of checked-value representations, and their [trust-boundary documentation](tcb.md).
Unreadable or truncated source inventories fail the gate. The compiler suites
separately exercise typechecking behavior.

```sh
sh scripts/ouro_repo_gate.sh --profile compiler-boundary
```

The `kernel-hardening` gate also requires the canonical compiler profile and its
negative report-policy tests. The profile strictly checks the retained law
program, builds it without a cache, with a fresh cache, and from that cache,
then executes all 55 laws in each mode. Every complete executable run must
finish within 500 ms, including process startup and supervision. Checking and
compilation have separate bounded phases. The retained executable uses `O1`
in all three modes to reduce generated C code and cold startup cost. Receipts
verify the optimization flag and bind the exact sources, producer, and executable;
each mode still executes the laws without a warmup. The optimization level is
part of the baseline context, so previous `O0` timings are not compared as the
same build configuration.
The profile also requires all three blocking `compiler-boundary` checks.

```sh
python3 scripts/kernel_hardening_suite.py
```

This command uses the configured compiler in `OURO_C_BUILD_DIR`. `--compiler`
selects an explicit compiler, and `--repo-gate` can supply an existing boundary
executable with a current build receipt. Reports and fresh per-run logs are
written under `_build/kernel`, or `--out`. The old JSON replay timing is a
different measurement and is not reused as an executable baseline.
`kernel_profile.py --baseline-out` records an explicitly requested baseline;
it never updates the blocking budgets.

The required `compiler-scale` and `compiler-depth` gates preserve the former
large-input and public checked-API contracts through Ouro probes:

```sh
python3 scripts/kernel_scale.py --profile scale --out _build/kernel_scale/scale
python3 scripts/kernel_scale.py --profile depth --out _build/kernel_scale/depth
```

Scale covers all six 20,000-element cases with a 10-second limit per executable
run, including declaration IDs and dependency-edge coverage. Depth covers all
15 checked entry points at both 10,000 and 1,000,000 nodes. Deep-input resource
rejection must be the exact typed resource outcome; a crash, timeout, or host
memory termination cannot satisfy it. The host verifies complete ordered
protocols, current source and producer hashes, executable receipts, and limits.
These gates are blocking in PR analysis, nightly kernel, manual, and `kernel`
profiles. The `kernel` name is retained for command and hosted-job compatibility;
it runs the canonical compiler suites and the generated Core profile.

### Handwritten C host analysis

Run the strict C-host gate with:

```sh
python3 scripts/c_static_analysis_suite.py --out _build/c_static_analysis
```

The gate requires GCC `-fanalyzer`, Clang Static Analyzer, AddressSanitizer, and
UndefinedBehaviorSanitizer. Compiler warnings and analyzer findings are errors;
missing required tools fail the gate. Positive and intentionally unsafe
fixtures prove both false-positive behavior and nonzero deny behavior before
the gate scans every handwritten `runtime/*.c` file. The generated
`compiler/stage0/` tree remains under stage-loop and generated-artifact policy
and is not treated as handwritten analyzer input. Reports and per-check logs are
written under `_build/c_static_analysis/`. Clang's version-dependent
`unix.Stream` and `unix.Errno` state models are excluded when present because
they flag ordinary checked `fread`/`ftell` flows; compiler diagnostics and the
core, bounds, security, allocation, and lifetime checkers remain blocking.
On Windows, the gate also fault-injects the bounded capture reader's allocation:
empty output must succeed normally and return an OS error when allocation fails.

### Host Python lint

Run the deny Python gate with:

```sh
ruff check --config quality/ruff.toml scripts
```

`python3 scripts/ci_gate.py` includes this as `python-lint` on the `pr`,
`nightly`, and `manual` profiles. The gate requires Ruff 0.15.21. Missing Ruff
fails the gate. `quality/ruff.toml` selects every rule and then ignores
formatter, docstring, annotation-modernization, complexity-count, pytest,
pathlib-rewrite, and host subprocess rules; leftover findings are errors.
`python-syntax` (`python3 -m py_compile` on `scripts/*.py`) stays a separate
cheaper gate.

### Host shell lint

Run the deny shell gate with:

```sh
shellcheck --severity=style scripts/*.sh samples/bioinformatics/fixture_tool.sh
```

`python3 scripts/ci_gate.py` includes this as `shell-lint` on the `pr`,
`nightly`, and `manual` profiles. The gate requires ShellCheck. Missing
ShellCheck fails the gate. The command fixes `severity=style`;
`.shellcheckrc` enables `external-sources=true` and disables only
`SC3045` (`ulimit -s` is a best-effort host stack bump).
Leftover findings are errors.

## Ouro-native control-plane displacement

The preferred path for supported repository-owned checks is now Ouro-native:

```sh
sh scripts/ouro_repo_gate.sh --profile docs-native --out _build/ouro_repo_gate/docs-native
sh scripts/ouro_repo_gate.sh --profile project-native --out _build/ouro_repo_gate/project-native
sh scripts/ouro_repo_gate.sh --profile workflow-native --out _build/ouro_repo_gate/workflow-native
sh scripts/ouro_repo_gate.sh --profile control-plane-native --out _build/ouro_repo_gate/control-plane-native
sh scripts/ouro_repo_gate.sh --profile retirement --out _build/ouro_repo_gate/retirement
sh scripts/ouro_repo_gate.sh --profile pr-native --out _build/ouro_repo_gate/pr-native
```

The Python PR profile invokes those `*-native` names; the short names `docs`,
`project`, and `workflow` are aliases.

The Ouro-native CI runner can list or run grouped profiles without Python
composition:

```sh
sh scripts/ouro_ci_gate.sh --profile smoke --out _build/ouro_ci/smoke
sh scripts/ouro_ci_gate.sh --profile docs-native --out _build/ouro_ci/docs-native
sh scripts/ouro_ci_gate.sh --profile project-native --out _build/ouro_ci/project-native
sh scripts/ouro_ci_gate.sh --profile repo-native --out _build/ouro_ci/repo-native
sh scripts/ouro_ci_gate.sh --profile quickstart-native --out _build/ouro_ci/quickstart-native
sh scripts/ouro_ci_gate.sh --profile suite-native --out _build/ouro_ci/suite-native
sh scripts/ouro_ci_gate.sh --profile control-plane-native --out _build/ouro_ci/control-plane-native
sh scripts/ouro_ci_gate.sh --profile retirement --out _build/ouro_ci/retirement
sh scripts/ouro_ci_gate.sh --profile pr-native --list
sh scripts/ouro_ci_gate.sh --profile pr-native --out _build/ouro_ci/pr-native
sh scripts/ouro_ci_gate.sh --profile host-bound --out _build/ouro_ci/host-bound
```

[Native repository gates](native_repo_gates.md#explicit-execution-paths)
defines backend markers, strict CLI selection, report evidence, and retirement
conditions.

`pr-native` runs the Ouro-native docs, project-surface, and workflow gate subset.
It is useful for repository-control-plane changes, but it is not full parity
with `python3 scripts/ci_gate.py --profile pr`. The Python PR profile remains the
compatibility/reference full PR readiness path for broad suites, bootstrap
evidence, cache parity, release packaging, and specialized analyzer checks.

Repository suites for manifests, formatting, documentation, lines, native lint
fixtures, runtime IO, user tests, samples, and quickstart now keep their cases
and assertions in Ouro. Their documented shell commands are compiler/bootstrap
compatibility launchers; `lint_suite.sh` compiler-checks
`tools/clippy/core.ouro`, `tools/clippy/scan.ouro`,
`tools/clippy/structural_main.ouro`, and `tools/clippy/main.ouro`, then runs the
host-bound Python Clippy-grade fixture suite. `scripts/process_stdin.sh` is the
minimal
stdin adapter until `proc_exec` grows a typed stdin argument.

Host-script retirement follows the evidence rules in
[Native repository gates](native_repo_gates.md#compatibility-and-host-reference-boundaries).

## Hosted workflows

| Workflow | Role |
| --- | --- |
| `ouro-pr.yml` | Parallel PR, kernel, editor, and portable checks |
| `ouro-nightly-full.yml` | Scheduled full checks |
| `ouro-manual-trust.yml` | On-demand check profiles |
| `dependency-review.yml` | Changed dependency and workflow checks |
| `ouro-lint.yml` | Full Ouro lint suite, manual dispatch only |
| `ouro-release.yml` | Build host toolchains and publish tag drafts and snapshots every three days |
| `ouro-pages.yml` | Test, lint, and build `site/` on PRs and pushes; publish GitHub Pages from `main` |

The release workflow builds the host toolchains described in
[Releasing](releasing.md). Its build and assemble jobs stay read-only.

Hosted path selection is fail-closed for validation: missing revisions, a Git
error, or an empty diff runs every applicable job. An editor-only change runs
the VS Code test job while skipping unrelated compiler work.
A `site/`-only change is treated as a dependency/path change and does not start
the compiler suites. Pages runs `npm run lint`, `npm test`, and `npm run build`
for pull requests to and pushes on `main` or `master` that change `site/`,
`quality/biome.json`, or its workflow. Pull requests only restore the npm cache
and cannot deploy the site.
The hosted `Kernel` job builds `ouro1`, then runs
`python3 scripts/ci_gate.py --profile kernel` and uploads its compiler,
hardening, boundary, generated-law, scale, and depth reports. Its path
selector covers the checker and its compiler, runtime, standard-library, test,
and gate dependencies. Missing required probes fail the job.
The nightly and manual profiles also run `analyze-production`
(`python3 scripts/analyze_production_suite.py`), which sweeps the production
scopes with the structured analyzer and fails on any finding from the promoted
`--enable-strict` family set or on a frontend rejection that
`quality/analyze_production.json` does not list; the PR profile keeps the
fixture-based `analyze-precision` gate. Dependency review starts for every pull request so its required status is
stable, but the dependency action and workflow scan run only when their owned
paths changed.

Workflow permissions are explicit. Validation jobs are read-only; release
publication requests write access only in the tag-gated draft job and the
guarded snapshot job. The public
site workflow requests `pages` and `id-token` write only in the main-branch
publish job. External actions are pinned to a full commit SHA.

The public site source lives in `site/`. Hosted Pages use
`https://eluvane.github.io/ouro/`. After a custom domain is attached, rebuild
with `SITE_BASE=/` and add the hostname to `site/public/CNAME`. GitHub Pages
must be set to GitHub Actions as the source.

The site overrides `@jqhtml/core`'s Terser plugin to `1.0.0` so its serializer
can receive the security fixes in `serialize-javascript` 7. The plugin requires
Node 20, already covered by the site's Node 20.19 minimum. Keep the override
until upstream updates that dependency; verify lockfile changes with
`npm ci`, `npm audit`, `npm test`, `npm run lint`, and `npm run build` in `site/`.

Site controls use regular-weight SVGs from [Phosphor Icons](https://github.com/phosphor-icons/core),
revision `2b75f3ad12b420c9504ef05df8d2564a28f8500e`. The files in
`site/src/assets/phosphor/` come from upstream `assets/regular/`: `github-logo.svg`,
`magnifying-glass.svg`, `list.svg`, `x.svg`, `copy.svg`, and `link.svg`.
Only descriptive SVG titles were added; the paths are unchanged.
`site/src/icons.css` applies the theme color through CSS masks. The MIT
license and upstream attribution ship in `site/public/licenses/phosphor-LICENSE.txt`.

Hosted repository reachability is separate from local project-surface policy.
`scripts/github_project_hosted_probe.py` records `gh repo view` reachability for
manual or hosted contexts, but `scripts/github_project_gate.py` does not depend
on it and does not claim native hosted GitHub API parity.

Policy notes that must stay visible in this page: cache is not trusted;
`kernel_hardening_suite.py`; generated artifact drift; cache-on/cache-off parity;
`pull_request_target`; `workflow_dispatch`; nightly; local reproduction; release
candidate; `github_project_gate.py`; `release_package.py`;
`strict_quality_firewall.py`; Strict-quality SARIF policy.
`scripts/hygiene.sh` keeps presence, generated-shape, packer-selftest, and
stitch needles. It does not re-run those PR-owned gates;
`python3 scripts/ci_gate.py --profile pr` remains their required owner.

## Reports and failures

The strict firewall releases source-reading and scan temporaries per file through
the existing native quality arena adapter, and declaration checks release their
intermediates after each declaration. Configuration loading, registry checks,
and fixture validation also release their intermediates after returning results.
Memory limits remain blocking. Suppression directives are recognized in comments,
while quoted examples remain ordinary source data. On Linux, the memory monitor
terminates measured descendants even when a nested runner creates a new session.

The `structural-quality-suite` and `structural-quality` gates run in the PR
checks group, nightly, manual, and stage-loop profiles. Run
`python3 scripts/strict_quality_firewall.py --structural`; its report under
`_build/quality/structural-quality.json` must be complete, well formed, and
contain zero unclassified blocking findings. There is no existing-debt baseline.
See [structural quality](quality.md#repository-structural-gate) for precision,
generated boundaries, and intentional classifications.

Most gates write JSON, logs, text, SARIF, or Markdown under `_build/`. Workflows
upload these artifacts even when a job fails.

A report explains what ran and why it failed. It is not a trusted input for a
later job. Missing required tools or scripts fail the corresponding gate;
optional host-dependent checks are reported as unavailable.

Ouro-native repository reports write `repo-gate.json`. Ouro-native CI reports
write `ci-summary.json` and per-gate JSON files. Both report families keep
stable `kind`, `version`, `profile`, `execution_backend`, `execution_mode`,
`pass`, `gates`, `status`, `blocking`, `issues`, and `policy_note` fields.
Repository checks may also include deterministic `metrics`. CI gate entries
record exact `command_argv`, `required`, `blocking`, `elapsed_ms`, `returncode`,
`output_log`, and `gate_report`.

The `host-bound` profile writes `host-bound.json`, covering every current
repository-visible `.py` and `.sh` path plus explicit `remove` rows for retired
script paths. Every row has deterministic fields: `kind`, `migration_status`,
`path`, `role`, `native_replacement`, `parity_status`, `removal_eligibility`,
`blocker`, and `evidence`. The standalone `host-bound` profile runs native
inventory consistency before writing the report; missing, stale, duplicate, or
reappearing removed script paths set both the report and command status to
failure. The profile also requires a fresh, passing `control-plane-native`
report with the expected native backend and a nonempty gate list. A child status
of zero without that report, or with malformed/non-passing evidence, is a
failure.

Never summarize a timeout, out-of-memory termination, or skipped host tool as a
pass.

The Python PR runner keeps complete gate logs under the selected output
directory. Console tails are printed for failing gates; passing gate tails stay
on disk unless `OURO_CI_TAIL_PASS=1` is set. This keeps the console useful
without reading large successful logs back into memory.

## Caches

Hosted and local caches may accelerate C objects, native tool binaries,
frontend regeneration, self-hosted modules, and generated-C shards. Pull requests use restore-only
cache policy; trusted branch or scheduled workflows may save accelerator state.

The shared PR compiler cache is keyed by the bootstrap driver's full current
input identity, including the host C compiler and flags. It includes the
completion report, input manifest, and both generated C comparisons referenced
by `ouro1.bootstrap.json`; `_build/c` alone cannot establish a reusable compiler.
Suite caches remain separate. Kernel and Portable restores try their own cache
prefix first. Only trusted branch pushes save PR caches.

Restored data is followed by the relevant parity, hash, regeneration, or
compiler-checking validation. Cache state does not establish program acceptance
or generated-artifact integrity. Workflows have no OCaml setup, opam dependency
cache, or Dune invocation.

Native tool source manifests are startup accelerators, not correctness evidence.
`scripts/build_tool.sh` writes a `<tool>.sources` manifest beside supported
native binaries. Missing, empty, malformed, escaping, or stale manifests trigger
an explicit content check/build. `native_tool_build.py` validates source/import,
compiler, runtime, helper and flag hashes, plus the cached binary's hash. A
timestamp change alone can reuse a complete matching binary. Suite wrappers
building `tools/test/main.ouro` share the same cached runner, and tool builds
share runtime C objects. The launchers no longer fall back to a broad
freshness scan; a failed rebuild rejects any previously discovered executable
instead of running stale code.

The default build-tool backend is `OURO_BUILD_TOOL_MODE=native`. A retained host
adapter requires an explicit `OURO_BUILD_TOOL_MODE=host-wrapper`; unsupported
entries fail instead of switching to native. `OURO_BUILD_TOOL_MODE=auto` remains
only as a named compatibility mode and reports the selected backend and reason.

Manifest-only OuroSmith checks prepare `collect` and `test`; the full generated
profiles still prepare every required text and test tool.

## Performance evidence

Use the local timing runner for small command latency work:

```sh
sh scripts/perf_core_toolchain.sh --repeat 3 --out _build/perf/core-toolchain-current.json
```

To compare a current run with a saved baseline:

```sh
sh scripts/perf_core_toolchain.sh --repeat 3 --out _build/perf/core-toolchain-before.json
sh scripts/perf_core_toolchain.sh --repeat 3 \
  --baseline _build/perf/core-toolchain-before.json \
  --out _build/perf/core-toolchain-after.json
```

The runner records exact commands, wall-clock milliseconds, exit codes,
stdout/stderr byte counts, min/median/max timings, environment information, and
cache notes. Missing commands are reported as unavailable. A median greater than
twice the baseline is a warning by default and can become a local blocking check
with `--fail-on-regression`. Avoid absolute timing budgets in hosted CI unless
they are very conservative.

## Documentation and repository checks

The [validation matrix](#validation-matrix) lists the documentation, project,
and workflow compatibility entry points. Their wrappers delegate to native
profiles and require a fresh, passing native report.
[Native repository gates](native_repo_gates.md#compatibility-and-host-reference-boundaries)
defines the fail-closed report contract.

The Ouro-native `docs` profile covers canonical docs, Markdown inventory metrics
including base-ref comparison when available, docs index links, relative links,
documented repository paths, README example drift, active syntax docs, manifest
prefixes, sample companion pairs, and generated API presence.
`scripts/docs_examples_gate.py` preserves the legacy report kind and path while
delegating policy to this native profile.

The Ouro-native `project` profile covers required files, retired paths, required
public phrases, public wording, README shape, pull-request template shape, issue
form shape, and version-baseline parity. `scripts/github_project_gate.py`
preserves the legacy report kind and path while delegating local project policy
to this native profile. Hosted GitHub/API reachability remains host-bound and is
recorded by `scripts/github_project_hosted_probe.py` when explicitly run.

The Ouro-native `workflow` profile applies the structured, fail-closed YAML
policy in [Native repository gates](native_repo_gates.md#compatibility-and-host-reference-boundaries).
`scripts/github_workflow_gate.py` preserves the legacy CLI and report path.

`sh scripts/frontend_security_suite.sh` is a blocking PR check for malformed and
fuel-exhausted lexer results plus safe `--module` C-symbol suffix handling.

## Adding a gate

A blocking gate should be deterministic, locally runnable, scoped to a clear
contract, and registered in the appropriate `ci_gate.py` profile or
Ouro-native `tools/ci_gate/` profile. It should write a useful report when
diagnosis would otherwise be difficult.

A required gate must not use `continue-on-error` or silently downgrade because
a dependency is absent. New workflow permissions, external actions, privileged
triggers, or hosted-only services require an explicit security review.

A new Ouro-native gate can be added under `tools/repo_gate/` or
`tools/ci_gate/` when it has focused coverage, deterministic listing, stable
reports, and clear parity boundaries with the Python or shell reference path.
