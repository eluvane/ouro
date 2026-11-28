# Continuous integration

Choose a validation suite for the area you changed. Repository scripts run the
profiles locally. GitHub Actions runs those profiles and uploads reports from
`_build/`.

## Validation matrix

Run local commands from the repository root in a POSIX-compatible shell unless
the example specifies PowerShell. The Python profiles and the documentation,
project, and workflow wrappers can invoke `sh`. Use the
[build prerequisites](getting_started.md#requirements) and have Git available
for repository checks. A cold run can build the compiler and tools under
`_build/` and populate `_cache/`.

Run the focused command first. Before opening a PR, run the broader PR profile
when feasible. Record missing tools, timeouts, skipped probes, and incomplete
reports as incomplete validation.

| Change | Focused command |
| --- | --- |
| Documentation and examples | `python3 scripts/docs_examples_gate.py` |
| Public repository metadata | `python3 scripts/github_project_gate.py` |
| Workflow policy | `python3 scripts/github_workflow_gate.py` |
| Formatter / fixer | `sh scripts/fmt_suite.sh` / `sh scripts/fix_suite.sh` |
| Linter / analyzer | `sh scripts/lint_suite.sh` / `sh scripts/analyze_precision_suite.sh` |
| Public API fingerprints | `python3 scripts/api_baseline_regen_test.py` and `python3 scripts/api_baseline_regen.py --check` |
| Packages / LSP | `sh scripts/pkg_suite.sh` / `sh scripts/lsp_suite.sh` |
| Runtime and IO / samples | `sh scripts/runtime_io_suite.sh` / `sh scripts/samples_suite.sh` |
| User test runner | `sh scripts/test_suite.sh` |
| Compiler checking | `sh scripts/test_suite.sh --compiler-checking` and `python3 scripts/ci_gate.py --profile kernel --out _build/ci/kernel` |
| Prepared stage inputs | `python3 scripts/compiler_stage_contract_suite.py --compiler _build/c/ouro1` |
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
python3 scripts/ci_gate.py --profile pr --jobs 20 --out _build/ci/pr
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

GitHub selects affected checks from the PR diff. Main-branch pushes, merge
queues and manual CI use the regular complete PR selection. Nightly and manual
Lint runs cover the complete lint suite. Run one group with:

```sh
python3 scripts/ci_gate.py --profile pr --group checks
```

The group names are `checks`, `checks-parity`, `checks-quality`, `analysis`, `checker`, `analyzer`,
`analyzer-lint`, `lint`,
`tests`, `smith`, `samples-1`, `samples-2`, and `compiler-1` through
`compiler-16`. Substitute the selected name after `--group`. A routed PR can
also select the `lint-fixtures` and `lint-clippy` groups described below.

`--group` supports PR, nightly, manual, kernel, stage-loop, docs, and kernel-extra profiles.
`--list-groups` prints the selected profile's complete group list as JSON;
Manual and extended Release profiles use that inventory to construct their
hosted matrices. Release defaults to the same complete PR routing as ordinary
CI on `main`; changed-file lint groups require a diff and are not selected there.
Release metadata and assembly require every validation group to succeed.

The stage-loop profile separates `checks-parity` (`parity`) and `checks-quality`
(`syntax-quality-firewall`) from `trust`. `trust` retains Python syntax,
strict and structural quality, and the complete stage-loop/drift gate.
The ungrouped command retains the complete gate inventory and each group's
registry order.
Cold Manual validation bootstraps every group independently; job and process
limits stay unchanged.

The full release scan in `syntax-quality-firewall` uses the verified scanner
prepared by that suite. Separate strict quality gates run their own scans.

The generated-artifact drift gate retains the historical stage0 manifest checks
and compares fresh frontend regeneration and the full stage-loop fixpoint with
the verified current P2 generated C. The installed compiler receipt must bind
the current source, toolchain, binary, and complete P1/P2 equality evidence before
and after regeneration. Missing or changed evidence fails the gate; see
[Build](build.md#generated-artifacts-and-stage-loop) for the retained seed and
promotion contracts. Its `ouro.generated-artifact-drift-report.v2` report records
the current reference key and artifact paths, with raw and LF-normalized hashes
and the frozen binary, receipt, report, and input-evidence hashes.

The full local command runs independent groups in separate checkouts under
`_build`, with the current working tree as input. Each owns its own `_build`
and cache, and dependent gates share their group's checkout. `--jobs` sets the
total CPU slots for the run and its nested schedulers. It defaults to
`OURO_JOBS` or 20, with a ceiling of 20. The runner also reserves memory for
active tasks using available physical memory and headroom. Use `--jobs 1`
for a serial run.
With at least two assigned CPU slots, compiler preparation can reserve spare
memory to reach 6144 MiB and overlap eligible bootstrap phases. The reservation
counts toward the scheduler's memory budget. Per-process limits still apply.
Local `compiler-scale` and `compiler-depth` each reserve one CPU slot and
3072 MiB. Each runs its checks sequentially on one logical CPU.
The local `selfhost-module-cache` and `stage-loop-c-object-cache` suites also
reserve one CPU slot each for their sequential cache checks.
The full local profile prepares one compiler for its consumer groups. It
prepares `ouro-test` and `ouro-collect` once for the suites that share them,
including runtime IO. Production lint shards share one preparation of
`ouro-lint` with its companions and `ouro-pkg` when `OURO1_COMPILER` is unset.
Each consumer receives private copies of the binaries and their build evidence.
Local preparation uses `_build/ci-host` for the source snapshot and
`_build/ci-bootstrap` for checked compiler artifacts and historical stages.
The verified default build in `_build/c` can seed this locked cache. Reuse
requires the full bootstrap key, including matching reproducibility flags, and
verification of the binary and its complete bootstrap evidence. `OURO_CACHE=0`
selects fresh preparation. Independent checks in the `checks` group can use
separate local checkouts. The hosted group inventory and nightly stage-to-Smith
dependency retain their existing order.
The runner rejects a group
inventory that omits, duplicates, or invents a gate; its self-test also checks
complete matrix coverage and the affected-path routing contracts. The
`analysis` group owns memory budgets, C analysis, and LSP; `checker` owns
hardening, scale, and depth. In PR validation, `analyzer` owns analyzer
precision and `analyzer-lint` owns `lint-changed`. They run in separate jobs,
each with a 120-minute limit. On a PR, `lint-changed` runs
`ouro1 lint --deny` over the changed `.ouro` files that the complete suite's
production sweep would select from `std/`, `compiler/`, `tools/`, and
`samples/`. It reads the directory and file exclusions from
`tools/lint_worker.ouro` and `tools/quality/source.ouro`; the package sample
stays with the complete suite because it needs a vendored snapshot. Findings
that a change causes in unchanged files are left to Nightly. Without a routing
plan, `lint-changed` is reported as skipped.

Changes to mapped semantic fixtures, grade manifests and their launchers select
the `lint-fixtures` or `lint-clippy` group that consumes them. Shared fixtures,
the lint driver and Clippy implementation changes select both. Each group runs its
canonical `scripts/lint_suite.sh` phase. The same rule applies when other
changed paths require broad validation. An unclassified semantic fixture or
an unavailable PR diff selects both phases. Main-branch pushes, merge queues
and default Release validation use their ordinary full selection.

Nightly, full Manual and **Lint → Run workflow** schedule `lint-fixtures`, `lint-production-1`
through `lint-production-4`, and
`lint-clippy` as required groups. Each runs `lint_suite.sh --phase=...` with
the existing 120-minute job limit and checks the complete native tool receipts.
Fixtures retain the quality, launcher, semantic session, stress and import tests;
production shards retain the complete source inventory and deny verdicts. Each
uses `--phase=production --shard=N/4`; the native lint owner completes and
deduplicates the inventory before selecting every fourth file in its stable
order. All families run for each selected file, including the prepared package
snapshot and explicit bench source. Clippy
retains all four compiler checks and grade fixtures. The registry rejects missing,
duplicated, reordered or recombined phases and production shards. `--group lint`
on these profiles runs all required groups in order; `--group lint-production`
schedules the four production shards in isolated checkouts under the same CPU
and memory budget. For a local run with the shared prepared toolchain, each
shard installs its package snapshot once. Workers then process disjoint parts
of its inventory using private scratch directories. Each worker reserves one
CPU slot and 3072 MiB. The four gate reports include the worker results, and
the scheduler reports peak worker concurrency. Both aliases are excluded from
the hosted matrix inventory.
`lint_suite.sh` without arguments or with `--phase=production` retains the
complete unsharded production sweep.
The local PR `lint` group, standalone Lint workflow and `sh scripts/lint_suite.sh`
without arguments retain the complete suite.

Local `ergonomics` and `imports` use one CPU slot and 3072 MiB per manifest
batch. Invalid or missing reports fail the suite. Each batch uses its own
output directory and the same verified compiler and tools. The suite records
ordered batch results and peak concurrency in `manifest-batches.json`.
Execution removes the previous `ci-summary.json` before starting gates, so an
interrupted run leaves no old successful aggregate at the current report path.
The native CI runner also invalidates selected gate reports and the delegated
host-inventory report. Failure to remove a report stops execution; a directory
at a report path is never removed. Listing profiles does not change reports.
PR and Nightly validation jobs allow 120 minutes for the complete group;
per-program execution and memory limits remain separate. Independent PR matrix
groups finish when a sibling fails. Each group retains its fail-fast command,
and the aggregate requires every selected validation job to succeed. A plan
limited to Python syntax, Ruff, ShellCheck and CI runner self-tests runs
directly on the host. A plan that needs Ouro starts one Linux `Host compiler`
job. It restores or builds the compiler with its complete bootstrap evidence
and publishes a workflow-local artifact. Each
consumer checks the producer's SHA-256 and verifies the binary, current inputs,
host toolchain, and bootstrap evidence before running gates. Partial job retries
use the successful producer's artifact name, including its original attempt.
Release artifacts use the workflow run ID so branch names containing `/` remain
valid for uploads and downstream downloads.

On Linux pull requests, a routed regular compiler shard can use two C object
workers when the scheduler has two slots and at least 3584 MiB available.
Fixture execution and frontend work use one slot. A smaller or unknown memory
budget uses one C worker. The source-spans shard also uses one C worker.
With 6144 MiB available, two workers can prepare fixture binaries in the build
cache before the native runner checks, builds, and runs each fixture in order.

OuroSmith compiler evidence requires all sixteen compiler gate commands and their
source-bound receipts. The shard runners must agree on the full inventory and
binary identity; their combined artifacts must cover every fixture exactly once.
The standalone `sh scripts/test_suite.sh --compiler-checking` schedules all
sixteen shards with `OURO_JOBS` or 20 slots and one slot per shard. It writes
`shards.json` and separate logs under the suite output directory. In parallel
runs with multiple waves, a recent successful local report can put longer
shards first if it covers every shard and matches the fixture inventory and
backend. Reports list shards by number, and fixture results print in inventory
order. `--list` displays the selected fixtures. A numbered `--shard` runs one
shard.

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

### Native tool acceptance

Run these retained suites with explicitly provisioned Windows x86-64
candidates. Put `coil.exe`, `ouro-fmt.exe`,
`ouro-lsp.exe`, `ouro-pkg.exe` and `ouro-test.exe` in one directory, following
[the standalone build commands](tooling.md#standalone-native-tools).
Use a shell on Windows that can execute the PE images and choose fresh output
directories.

```sh
LSP_SUITE_OUT=_build/native-tool-tests/lsp sh scripts/lsp_suite.sh --native-tools _build/native
PKG_SUITE_OUT=_build/native-tool-tests/pkg sh scripts/pkg_suite.sh --native-tools _build/native
TEST_SUITE_OUT=_build/native-tool-tests/test sh scripts/test_suite.sh --native-tools _build/native
SAMPLES_SUITE_OUT=_build/native-tool-tests/samples sh scripts/samples_suite.sh --native-tools _build/native
```

Pass `--native-tools DIR` first; sample shard options and `--compiler-checking`
follow it. The separate `--native-build-collection` C harness rejects this
option. Each invocation checks the required sibling images, PE format and
system imports, records their SHA-256 hashes in `native-candidates.json`, and checks
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
These invocations supply evidence for the retained suites. Native bootstrap and
full PR validation have separate requirements.

Run the hash and binary String crypto regressions separately with the provisioned
direct-PE test runner and its `coil.exe` sibling:

```powershell
.\_build\native\ouro-test.exe --out _build/ci/crypto-native tests/quality_crypto_native_regressions.ouro
```

This root includes the hash laws from `tests/native_crypto_hash_laws.ouro` and
embedded NUL cases. The shared compiler fixture catalog registers the bounded
stream state and error laws. Runtime IO checks 159 SHA-256, HMAC and stream
observations against exact golden output on the C host. OuroSmith checks those
observations in three ordered runs of one checked executable, each with the
standard runtime timeout.

### Hosted profile composition

Nightly uses `checks`, `language-speed-simplicity`, `fix`, `checks-parity`,
`checks-quality`, `analysis`, `analyzer`,
`lint-fixtures`, `lint-production-1` through `lint-production-4`, `lint-clippy`,
`tests`, `samples-1`, `samples-2`, `kernel`, `smith-selftest`, `trust`, and `compiler-1` through `compiler-16`.
Nightly runs `language-speed-simplicity` and `fix` in separate jobs. The Manual
profile runs both in `checks`.
PR, Nightly and Manual isolate parity and syntax quality in their respective
checks groups, with the existing gate commands and per-program limits.
The `trust` job runs the stage-loop fixpoint/drift gate and then the deeper
OuroSmith profile in the same checkout. The required `smith-selftest` group
runs the harness self-tests separately, preserving all gates and per-program limits.
The PR `smith` group runs the same blocking self-tests before its generated
profile. In the hosted `PR (smith)` job for a pull request with exactly two
CPU slots, `ouro-smith` reserves 6144 MiB when that much memory is available
after headroom. This allows two native tool builds at 3072 MiB each. With
4096 to 6143 MiB available it reserves 4096 MiB. The hosted `kernel-extra`
OuroSmith gate reserves 4096 MiB with two slots and at least that much memory.
A smaller or unknown budget uses the ordinary scheduling policy. The one-slot
minimum is 3072 MiB. Child processes keep their existing limits.

`Full` runs even after a job failure and requires the compiler producer and
every matrix group to succeed. Reports are uploaded separately as
`nightly-<group>` artifacts. The hosted PR matrix has
the static name `PR`. Selected groups appear as `PR (checks)`, `PR (checker)`,
or `PR (compiler-1)`, for example.

When portable checks are selected, `PR (checks)` checks Python syntax on Linux.
`PR (checker)` verifies the imported compiler with the build driver and runs
`kernel_hardening_suite.py`. Its report is in the `checker-Linux` artifact.
`Portable (macos-latest)` starts after `Paths` and runs the same hardening suite
after building or verifying `ouro1` with its [macOS bootstrap cache](#caches).
macOS keeps the inherited Python stack when the host CPython build rejects
`setrlimit(RLIMIT_STACK)`. Darwin also rejects finite `RLIMIT_AS` (EINVAL);
POSIX children on Linux still apply a sticky AS cap when the host allows it,
and fall back to a soft-only cap when a lowered hard value is rejected.
The hosted `Compiler kernel` job runs `--profile kernel-extra`: only the
kernel OuroSmith gate, which is absent from PR. The complete standalone
`--profile kernel` remains unchanged. A runner self-test requires the union
of PR and kernel-extra to cover every kernel gate, with no duplicated gates
in kernel-extra. Shared compiler, runtime, standard library and bootstrap
inputs select all sixteen compiler shards, as do unclassified changes.

The static `Kernel` check always requires successful path selection. It
checks the expected result of `Host compiler`, every selected PR or docs
group, kernel checks, Portable, Editor and Site. A selected job that fails,
is cancelled or is skipped fails the aggregate.
`scripts/apply_github_settings.py` recommends the stable required contexts
`Paths`, `Kernel`, `Editor`, and `Review`. When adopting the docs route, replace
required individual `PR (...)` and `Portable (...)` contexts in hosted branch
rules with `Kernel`; those matrix contexts do not exist when the matrix is
skipped. Editing the script does not apply hosted settings.

Changes confined to root Markdown or ordinary Markdown under `docs/` use the
`docs` profile. This runs workflow and project policy, API baseline drift,
documentation generation checks and documentation examples. The same profile
covers the generated API index and pages matching a current standard-library
module. The documentation suite compares their contents with the generator's
output. Unknown API pages, the stage0 hash manifest and trust or build design
documents keep full PR validation. CI and release documents have the additional
checks below. Mixed changes combine the selected checks.

```sh
python3 scripts/ci_gate.py --profile docs --out _build/ci/docs
```

### Affected PR checks

`Paths` first runs the CI routing self-tests. It then compares the PR base
with GitHub's tested merge commit. It reads
a NUL-delimited local Git diff with rename detection disabled, so both names
of a renamed file contribute. Missing revisions, Git errors, timeouts,
oversized output and empty or invalid diffs select the complete pull request
matrix plus the four production lint shards, `lint-fixtures`, and `lint-clippy`.

The pull request matrix runs `runtime-io` and `frontend-security` in separate
jobs when selected, including when the diff requires the complete matrix.
The `tests` job runs the affected gates among `ergonomics`, `imports`, `test`,
and `compiler-boundary`. The six gates share `tests` in local
`--profile pr --group tests` and in complete Nightly, Manual, and Release
validation. Pushes to `main` or `master`, merge groups, and manual CI also
use that grouping through `--full`.

Before a selected host compiler build, `Paths` runs
`python3 scripts/pack_frontend.py --selftest`. A core plan that needs the
compiler also runs `python3 scripts/clippy_import_gap.py --self-test`.
The checks group installs Ruff and ShellCheck individually when it needs them.
The `compiler_groups` output lists matrix groups with a selected gate that needs
the host compiler. These groups restore the suite cache and download, verify,
and install the compiler artifact.

The following inputs have mapped consumers in `scripts/ci_gate.py`.

| Changed area | Additional checks |
| --- | --- |
| Formatter, fixer and analyzer implementations | Formatter, fixer, analyzer precision, memory budgets, LSP and integration tests |
| Package manager | Package suite, user tests, memory budgets and release packaging |
| LSP implementation | LSP protocol, memory budgets and OuroSmith |
| Documentation generator | Documentation, memory budgets and OuroSmith. The shared document model also selects LSP. |
| Registered suite fixtures and launchers | Their consuming suites, including analyzer precision, C static analysis, memory budgets or structural quality as applicable |
| GitHub issue forms, Dependabot configuration, PR template and review ownership | Project policy and documentation checks |
| License | Project policy, documentation and release packaging |
| Dependencies, Lint, Nightly and Pages workflows | CI runner self-tests, workflow policy and documentation checks |
| Release workflow, release categories, packaging script and release documentation | Release packaging self-tests and metadata validation |
| Manual workflow | Dispatch and matrix self-tests, compiler and build-cache configuration, API drift and documentation suite |
| PR workflow, CI runner and CI documentation | Routing/consumer self-tests, compiler configuration and build-cache configuration |
| OuroSmith provenance collector | Source, binary and stage-receipt regression tests in the CI runner self-test |
| OuroSmith surface regression records | Replay through the PR OuroSmith profile |
| Kernel hardening budgets and baseline | Kernel hardening on Linux and macOS. The budgets also select kernel-extra and the host-bound inventory. |
| Memory budgets and baseline | Memory budget suite. The baseline also selects the host-bound inventory. |
| API fingerprint fragments under `quality/api_surface/` | Regenerate and compare the public API baseline |
| Native host inventories | Host-bound inventory and delegated native repository policy checks |
| Native repository checks and policy | Host-bound inventory, native policy checks, user tests and compiler-boundary checks |
| Strict debt manifest | Strict firewall and structural quality checks |

Mapped tool implementations run the syntax and strict quality firewalls,
structural quality and documentation examples. Each implementation also runs
the integration suites that exercise it. Changed production Ouro sources select
`lint-changed`. A change confined to `.shellcheckrc` selects ShellCheck,
and a change confined to `quality/ruff.toml` selects Ruff.
For unclassified inputs the planner selects the complete PR inventory and
portable checks. Shared compiler, runtime and standard-library inputs also
select kernel-extra.

Edits to `README.md` in `samples/demo`, `samples/examples`, `samples/tutorial`,
`samples/scientific`, or `samples/bioinformatics` select `docs-examples` and
`structural-quality` in the `checks` group.

Sample shards derive from the runnable and check-only cases in
`tools/test/sample_cases.ouro`. A registered `.stdin` or `.golden` companion
selects every shard that consumes it. For a registered sample source the
planner follows transitive imports and includes other known suite consumers.
The sample launcher compares the router's expected cases and execution modes
with the native test runner's listing for each shard. A mismatch fails the suite.
Missing files, unsupported inventory entries or an unmapped consumer require
full validation.
`tests/workflow_stdlib_tests.golden` selects its assigned sample shard when
the registered workflow fixture is its sole owner. Ambiguous ownership or
another consumer requires full validation.

An explicitly mapped compiler fixture or support file selects its owning shard
and any additional consumers. For narrowed routes, the planner follows
transitive imports from the canonical compiler fixture inventory. It checks the
build system's import count against the existing source tokenizer and accounts
for sibling golden files and sources read as fixture data. An unreadable
dependency, unsupported import layout or inventory shape selects full validation.
New tool families remain full-validation inputs until their consumers are mapped.

The job outputs contain the changed paths, a dynamic matrix and a digest of the
complete selection. Each consumer recomputes the decision from its checkout and
requires the same digest. Invalid JSON, an empty selected group, or disagreement
with the producer is an error. `Kernel` still requires every selected job to
succeed; a skipped required job or failed/cancelled matrix cannot satisfy it.
Do not require individual dynamic matrix names in branch protection.

The GitHub job summary lists selected groups and gates. A pull request that
selects the complete matrix lists `checks`, `tests`, `smith`, `runtime-io`, and
`frontend-security` first, followed by `checks-parity`, `checks-quality`, and the
isolated `source_spans` shard. Runner availability determines start times.
Manual creates both operating-system jobs for each group before advancing to the
next group, so Windows jobs enter the queue alongside their Linux counterparts.
PR matrix jobs continue independently after a sibling failure. Each group
stops at its first blocking failure and records unexecuted gates as `not_run`.
On pull requests, routed `--fail-fast` runs emit GitHub error annotations for
blocking failures after writing `ci-summary.json`. Nightly and ordinary local
profiles still gather all failures. Obsolete runs are cancelled by the existing
concurrency group.
The already-compressed PR compiler archive uploads with `compression-level: 0`
and requests 30 days of retention, subject to repository policy.

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
53 pure API laws alongside the 18 compiler binding and 9 primitive registry
laws. These check byte preservation, tagged failures, exact child status,
limit validation, and primitive identity; they do not prove Windows Job
enforcement or descendant cleanup.

```sh
sh scripts/test_suite.sh --compiler-checking
sh scripts/test_suite.sh --compiler-checking --list
sh scripts/test_suite.sh --compiler-checking --shard=1/16
```

Register each `tests/compiler_*_tests.ouro` and each `*_tests.ouro` under
`tests/compiler/` in `compiler_check_suite_fixtures` in `tools/test/suites.ouro`.
The [checker diagnostic fixtures](../tests/compiler/diagnostics/) run through
this inventory, not a directory glob. `--list --shard=1/16` shows the paths
in that shard without running their assertions.

The native-lowering fixture runs each assertion in a separate process to bound
the transitional C host's compiler heap. It retains the full case inventory,
rejects duplicate names, and requires each child's exact output and zero status.

Each invocation verifies that the sixteen shards cover every fixture exactly
once and have unique fixture names and paths. The first fifteen shards contain
the remaining fixtures in round-robin order and differ in size by at most one;
the sixteenth runs `source_spans` alone so its cost is separate. Missing,
duplicated, unknown, or malformed selections fail. Omitting
`--shard` runs the full inventory. Each hosted shard has its own output directory
and retains the same checker, build, execution, and failure requirements.
The inventory interleaves fixtures by measured native build cost so expensive
fixtures fall in different shards. Timing estimates affect ordering only;
they never select which assertions run or relax a timeout.

The command uses the configured bootstrap in `OURO_C_BUILD_DIR`, runs builds
with one worker, and writes logs under `_build/compiler_check_suite` (or
`TEST_SUITE_OUT`). The full unsharded gate remains registered in the Ouro-native `suite-native`
profile. User-test and stage-loop gates remain separate.

The frontend-security host suite builds the fresh generated backend in shards
grouped by 256 generated getter clusters. It checks the original generated C,
shard manifest and shard contents for all six host images. Linux uses up to two C
build workers within the assigned CPU slots. Other hosts use one build worker.
The build uses `O0` and a 3 GiB/900-second limit. All host probes run on one CPU.
The host build records start and completion markers for compiler emission,
helper uniquification, hook installation, and publication, so a timeout can be
assigned to the last unfinished phase without inferring it from compiler trace.
The diagnostic `n1-host --timings ROOT.ouro OUT.exe UNIT.ouro ...` option records
monotonic elapsed wall seconds at source-checking, replay, type-normalization,
lowering, MIR, GC, codegen, and publication boundaries. The bounded-process API
build enables it to locate native-compilation timeouts. Unavailable or backward
clock samples are reported explicitly; timing never changes acceptance or a
deadline. A required host probe checks timing output. Ordinary host invocations
retain their existing diagnostic bytes.

On Windows, the required frontend-security host suite also uses its freshly
built `n1-host` to emit the 53 bounded-process API laws, runtime fixture, and
denied-commit child as direct PE32+ images. All 60 host probes
remain required, including reachability/flow-round fuel, error-payload and nested
allocation, root clearing, per-declaration source checking, per-contract result
retention, and PE operation
lifetime checks, descriptor renumbering, forced codegen fallback, and canonical
block/body byte parity. On Windows, the same
fresh backend also emits the existing reclamation and active-caller fixtures
as direct PE images, including a validated descriptor renumbering across 65536.
All six lifetime images (`live-reclaim`, `live-calls`, `live-high-descriptor`,
`escaping_collect`, `pap_reuse_collect`, `pap_plateau`) must return 42 after
their heap/root assertions with empty stdout and stderr. The plateau case keeps
an escaping PAP graph live across 4096 applications and requires at least 16
observed automatic budget resets with actual object-count reduction. Raw
observations do not force collection or clear dead slots; requested managed
bytes and object counts stay bounded, followed by checked empty-heap release.
These assertions do not measure OS peak commit or establish native bootstrap.
Default-quiet host progress and
unchanged failure diagnostics are checked separately. The native section requires all 53 API result lines in
order, including the two separate `capture cap` laws, 24 runtime cases, and
8 source-helper rejections after successful source checking and rechecking. The cases cover
exact captured bytes and binary stdin, deferred/reused actions, child status
73 and 259, invalid limits, launch failure, memory denial, output caps,
timeout, descendant completion, and parent termination. The explicit-cwd cases
retain literal Unicode/space paths, empty and quoted argv, unchanged parent cwd,
invalid UTF-8/NUL/relative path refusal, binary streams, and the same timeout,
resource, cap and descendant-cleanup failures. Source, producer, PE imports,
exact output and cwd input hashes remain bound to the invocation. Host receipt
protocol laws are separate from native execution acceptance.

The existing native file-read owner retains all 14 read-status cases and three
source-helper rejections. It also emits the bounded-reader's ten pure laws, six
order laws, all three cleanup fault modes, public binary probe and source-owned
call fixture as direct PE images. This section is required on Windows: it checks
exact NUL/FF bytes, zero/exact/excessive and large Nat caps, the 65537-byte chunk
boundary, Unicode paths, missing/directory/reparse/sharing refusals, source-owned
NUL/malformed UTF-8 paths, deferred/reused actions and recovery. Unknown source
modes and malformed/extra probe arguments must refuse. A host argv failure does
not replace a malformed String check inside the native helper.

The bounded observer pins complete source closures, the fresh producer, all four
PE images, input receipt and exact input/output bytes before and after execution.
All 22 runtime rows, ten/six law lines and three fault outcomes are required;
truncated or extra bytes, wrong status, stale inputs, timeout, missing reparse
support or incomplete observation cannot establish bounded native acceptance.
The existing one-CPU/3 GiB host budgets remain, with 30-second native invocations
and a 300-second observer deadline. Protocol regressions remain in
`scripts/fs_read_suite_test.py`, called by the existing runtime IO suite; the
frontend host suite runs the real native observer before declaring completion.
C stdin/read controls and all other host/lifetime/process gates remain required.

The runtime IO suite also runs the C writer observer and its protocol tests.
It compiles the writer harness as separate translation units; only the test
`ouro_io.c` object receives `ouro_io_write_test.h`. The configured C producer,
sources, objects and driver are pinned before and after observation. All 12
write cases and four malformed-driver cases require exact raw status, streams
and file bytes within a 90-second observer deadline. The existing backend
enforces the configured 3072 MiB cap for the Windows process tree and each
Linux process. Darwin inherits the host address-space limit. Windows cases
hold a readable ordinary file and verify direct-open sharing status 32. POSIX
cases verify direct no-follow refusal and retain ordinary symlink-target bytes.
These C controls do not establish native runtime acceptance.

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
The same required Windows owner also emits the current public `coil` entry,
all 127 CLI argument laws, and a source-owned sibling transport fixture. Its
33 public-route cases cover `lsp` and `pkg`, retained `fmt` and `test`, literal
arguments, inherited binary streams/cwd/environment, present-empty hosted
selectors, refusal priority, missing siblings and completed DWORD statuses.
Actual loaded-image paths are checked against cwd, PATH and argv0 decoys;
source, producer, images, inputs and raw byte receipts must stay unchanged.
The fixture aliases establish routing only. The retained standalone package
and LSP suites remain required for their real behavior; these observations do
not establish native bootstrap or isolated-host acceptance.

The same Windows process owner also emits the native toolchain model, reader,
IO fixture and source-owned protocol child from their complete current closures.
All 60 model, 18 paired-reader and 19 IO law lines are required in source order,
with exact raw output and empty stderr. The reader runs from the repository root;
the IO fixture uses a fresh owned directory, unrelated cwd, literal Unicode
environment and the checked bounded-process API. Source, producer, native
check/recheck/emission phases, exact PE imports and raw reports remain bound
before and after execution. These fixtures test source capture and transport;
the child publishes synthetic PE bytes and does not establish N2/N3 equality or
native independence. The pure model also remains in compiler-checking.

The same required Windows owner emits both internal release folder-staging
fixtures and requires all 48 model and 12 real-IO rows, exact raw bytes and empty
stderr. The IO image receives one absolute fresh directory and runs from an
unrelated cwd with empty PATH and hosted selectors removed. The observer also
checks the complete hand-expected binary file/directory inventory and retains
failed or timed-out child streams. This exercises experimental folder staging;
it does not authenticate native artifact origin, publish a release or replace
the existing archive, manifest and five-platform release checks.

The source closures, producer, PE machine/imports, images, and byte reports
are recorded under `host-*/native-process/`. These checks use one CPU and
the configured outer memory limit (3 GiB by default). POSIX retains the
strict host probes and records the Windows runtime section as unavailable
with zero native rows. This transitional Python supervision and C producer
do not establish native bootstrap or an isolated-host release.

The `compiler-boundary` gate is required in the Python runner's PR `tests`
group, nightly, manual, and kernel profiles, and in `ouro_ci_gate.sh` profiles
`suite-native` and `pr-native`. It checks the pure-checker import allowlist,
the owners of checked-value representations, and their
[trust-boundary documentation](tcb.md). Unreadable or truncated source
inventories fail the gate. The compiler suites exercise typechecking behavior.

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
executable with a current build receipt. Otherwise the suite prepares the
boundary executable through the configured native-tool cache. The builder checks
the complete matching cache entry before installing a copy for the run.
`OURO_CACHE=0` forces a cold boundary build. The retained-law modes use their
own per-run cache. Reports and fresh per-run logs are written under
`_build/kernel`, or `--out`. The old JSON replay timing is a
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
These gates are blocking in the PR `checker` group, the nightly and manual
`kernel` groups, and the standalone `kernel` profile. The standalone profile
runs the canonical compiler suites and the generated Core profile.

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
written under `_build/c_static_analysis/`. Checks have 180 seconds by default.
GCC gets 300 seconds for `frontend_codegen_selftest.c`, which includes
`frontend_link.c` and its test callers. Use `--timeout-seconds` to set one limit
for all checks. Clang's version-dependent
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

The Python PR profile invokes `docs-native`, `project-native`, and
`workflow-native` directly. The short names `docs`, `project`, and `workflow`
select the same repository checks. In `ouro_repo_gate.sh`, `pr-native` is an
alias for `repo`, which combines documentation, project-surface, and workflow
checks.

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

In `ouro_ci_gate.sh`, `pr-native` runs the documentation, project-surface,
workflow, and `compiler-boundary` gates. Use the Python PR profile for full
PR validation, including broad suites, bootstrap evidence, cache parity,
release packaging, and specialized analyzer checks.

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
| `ouro-pr.yml` | PR path selection, language checks, editor and site validation, and portable checks |
| `ouro-nightly-full.yml` | Scheduled full checks |
| `ouro-manual-trust.yml` | On-demand check profiles on Ubuntu and Windows |
| `dependency-review.yml` | Changed dependency and workflow checks |
| `ouro-lint.yml` | Full Ouro lint suite, manual dispatch only |
| `ouro-release.yml` | Build host toolchains and publish tag drafts and snapshots every three days |
| `ouro-pages.yml` | Build selected site changes on push or manual dispatch and publish GitHub Pages from `main` |

Release prepares one Linux compiler for validation. Each validation group and
the metadata job verify the producer's artifact SHA-256, current inputs, host
toolchain, binary, and bootstrap evidence. Partial job retries use the artifact
from the successful producer's attempt. The compiler, validation, toolchain,
metadata, and assembly jobs use read-only repository access. See
[Releasing](releasing.md).

Manual validates the complete selected profile on Ubuntu and Windows. With
caching enabled, one compiler producer per OS exports the bootstrap evidence;
each validation group verifies the artifact SHA, current source and toolchain
before using it. `disable_cache=true` keeps independent cold builds in every
group. Windows Manual and Release jobs pin MinGW 16.1.0 and select only
`C:\ProgramData\mingw64\mingw64\bin\gcc.exe`. They add its native directory to
the next steps' `PATH` and set `CC=gcc`; a native Python check requires that
exact compiler path and version before building or importing the compiler.
Compiler and bootstrap receipts retain their complete identity checks.
The `manual` profile sets up Ruff and ShellCheck in its `checks` group.

Select `task=frontend-security` in Manual for the canonical frontend-security
suite alone on Ubuntu and Windows. The diagnostic task reuses compiler
verification, toolchains, cache controls, and the 120-minute job limit; all
frontend host limits, all host probes, and Windows direct PE checks remain required.
Its result does not certify a complete profile. The default `validate` task
still selects every group in the chosen profile.

The `api` task runs the canonical API generators and checks, then uploads
a review patch without publishing source changes. This artifact task does not
run or certify a validation profile.

The `dependency-locks` task updates only the two `brace-expansion` lock entries,
verifies their registry tarball integrity and runs npm audit before uploading a
review patch. It does not publish changes or replace dependency review. The full
Manual profile also runs the site and editor checks in an immutable Docker image
with read-only source mounts and retains source hashes and execution logs.

`Editor` validates `editors/vscode/`. Its npm manifest and lockfile also select
the repository version and release packaging checks. `Site` validates `site/`
and uploads the Pages preview artifact. The shared `quality/biome.json` and
the PR workflow select both jobs. A change to the Pages workflow also selects
`Site`. Markdown in either tree selects `docs-examples`. Removing or renaming
the editor package manifest or the site's Phosphor license also runs this gate
to check references to the old path.

Both jobs start after `Paths`. Site and Pages use `npm --prefix site run build:ci`
to install dependencies with `npm ci` and run `npm run check` for linting, tests,
and the build. Merge-queue and manual CI validation also include the site.
PR jobs use read-only permissions.

For pushes to `main` and `master`, the separate Pages workflow uses GitHub's
path filter for `site/**`, `quality/biome.json`, and the Pages workflow itself.
The workflow also builds the site on `workflow_dispatch`. A successful build
can publish only on `main`, after a push or manual dispatch.

The stable `Dependencies / Review` job starts for pull requests and merge
groups. It selects dependency review for changes to `Ouro.seal` or either npm
project's manifest or lockfile. For pull requests, the selector checks the
tested merge and PR head diffs against the base for these changes. The pinned
dependency-review action compares the PR head with the base. The selector uses
the tested merge diff to determine whether workflow definitions, launchers, or
scanner inputs need the native workflow-policy scan. `Review` runs required
scans outside the main CI plan. The scanner reads the current checkout. For
merge groups, the selector and dependency-review action use the group base and
head. An empty, invalid or unavailable diff selects both `Review` checks, as
does an oversized PR head diff. An oversized tested merge diff selects
dependency review and uses the complete CI plan for workflow policy.

The nightly and manual profiles also run `analyze-production`
(`python3 scripts/analyze_production_suite.py`), which sweeps the production
scopes with the structured analyzer and fails on any finding from the promoted
`--enable-strict` family set or on a frontend rejection that
`quality/analyze_production.json` does not list; the PR profile keeps the
fixture-based `analyze-precision` gate.

Validation jobs have read-only permissions. Release publication requests write
access only in the tag-gated draft job and the guarded snapshot job. The Pages
publish job requests `pages` and `id-token` write on `main`. The workflow
policy rejects `pull_request_target` and requires full commit SHAs for external
actions.

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

`scripts/hygiene.sh` checks source presence, generated source shape, driver
wiring, and the packer self-tests. The Python PR profile owns the remaining
required gates. See the [release candidate checks](releasing.md#release-candidate-checks)
for `release_package.py` and [quality reports](quality.md#fixtures-and-reports)
for JSON and SARIF findings.

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
On pull requests that select `structural-quality`, Paths runs the scan before
compiler preparation.
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

The `host-bound` profile writes `host-bound.json`. Its
[inventory and validation contract](native_repo_gates.md#host-bound-inventory-and-validation)
defines the row fields, delegated report requirements, and failure conditions.

Never summarize a timeout, out-of-memory termination, or skipped host tool as a
pass.

The Python PR runner keeps complete gate logs under the selected output
directory. Console tails are printed for failing gates; passing gate tails stay
on disk unless `OURO_CI_TAIL_PASS=1` is set. This keeps the console useful
without reading large successful logs back into memory.
`ci-summary.json` records tool preparation, workspace setup, gate elapsed time,
and resource allocations. Its peak task, CPU-slot, and memory counts describe
scheduled work. Compiler shards reserve 3 GiB each and record sampled peak RSS
for the process tree when the host provides it.

For runs with isolated workspaces, the Python runner writes `ci-setup.json`
beside the summary. It records source freeze, preparation cache access and hashes,
workspace copies, and compiler and tool evidence installs. Each entry names the
workspace and, when applicable, the gate and evidence producer. A phase starts
with status `running` and gets a duration and status `completed` or `failed` at
its end. After an interruption, a `running` entry identifies unfinished setup.
Times are in seconds from the start of the scheduler. A new run clears the
previous journal in its output directory.

## Caches

Hosted and local caches may accelerate C objects, native tool binaries,
frontend regeneration, self-hosted modules, and generated-C shards.

CI, `Dependencies / Review`, Nightly, Release, and standalone Lint restore the
compiler cache by the same exact key. It includes the runner OS, architecture,
and the bootstrap driver's full current input identity, including the host C
compiler and flags.
The cache holds the compiler, `ouro1.bootstrap.json`, the completion report,
the input manifest, and the P1/P2 generated C referenced by the receipt. The
build driver verifies the evidence before reusing the compiler. It builds a
current compiler when reuse is unavailable. Portable uses the same input
identity in its macOS cache key and retains the suite cache prefix fallbacks.

`Host compiler exact cache lookup hit=true` and `Portable compiler exact cache
lookup hit=true` record cache action lookup results. The build driver's
`BOOTSTRAP: current compiler unchanged; checked successor reused` records
verified reuse.

On an exact miss, `Host compiler` and `Portable (macos-latest)` save verified
compiler evidence for pull requests and pushes to `main` or `master`. GitHub
scopes pull request cache writes to the PR's merge ref. Successful
compiler-consuming matrix jobs and `Compiler kernel` save suite caches on an
exact miss in those same scopes. Portable saves its suite cache with its
compiler evidence. The `runtime-io` and `frontend-security` groups try their
own keys first and can fall back to the `tests` suite cache. `Compiler kernel`
tries its own suite cache prefix first.

Nightly saves compiler evidence on a miss during scheduled runs or manual
dispatch on `main` or `master`. `Dependencies / Review` restores it for workflow
scans. Release restores it for the validation compiler job when an exact entry
is available in the run's cache scope. Standalone Lint uses a restore-only
policy.

Nightly prepares one compiler in `Host compiler` and publishes it in a
workflow-local artifact. Each matrix job downloads the artifact and verifies
its SHA-256, compiler, inputs, host toolchain, and bootstrap evidence before
running its group. Suite caches remain separate.

In public repositories, CI's `Host compiler` and `Portable` jobs and
`Dependencies / Review` can restore the historical cache into the runner's
temporary directory after an exact compiler cache miss. It covers C0 and both
historical bridges in the [bootstrap sequence](build.md#c-bootstrap). The driver
uses the verified second bridge to build current P1, which then builds P2.
Private and internal repositories build historical stages from pinned inputs
when they need a bootstrap.

Each historical cache entry is specific to the runner OS, architecture, full
historical input key, and producing run. The archive digest must match evidence
from a successful first CI attempt on a push to `main` or `master` in the same
repository. An unavailable digest or a mismatch triggers a build from the
pinned inputs.

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
The [wrapper report contract](native_repo_gates.md#compatibility-wrapper-reports)
defines the evidence each wrapper requires.

The Ouro-native repository `docs` profile checks canonical docs, the docs
index, relative link paths, documented repository paths, README example drift,
active syntax docs, manifest prefixes, sample companion pairs, and generated
API presence. Check heading fragments separately from link paths. The gate
reports Markdown inventory counts. When it can count the Markdown files at
the base ref, it fails if the current count exceeds that baseline.
`scripts/docs_examples_gate.py` preserves the legacy report kind and path while
delegating to this profile.

The Ouro-native `project` profile covers required files, retired paths, required
public phrases, public wording, README shape, pull-request template shape, issue
form shape, and version-baseline parity. `scripts/github_project_gate.py`
preserves the legacy report kind and path while delegating local project policy
to this native profile. Hosted GitHub/API reachability remains host-bound and is
recorded by `scripts/github_project_hosted_probe.py` when explicitly run.

The Ouro-native `workflow` profile applies the structured, fail-closed YAML
[workflow policy](native_repo_gates.md#workflow-policy).
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
