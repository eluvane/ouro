<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=CI&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="CI banner"
  />
</p>

# Continuous integration

Ouro keeps the authoritative validation commands in repository scripts. GitHub
Actions invokes the same profiles that contributors can run locally and uploads
reports from `_build/`.

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

GitHub runs the same PR inventory as six isolated groups so the slow suites do
not block one another on a single runner:

```sh
python3 scripts/ci_gate.py --profile pr --group checks
python3 scripts/ci_gate.py --profile pr --group analysis
python3 scripts/ci_gate.py --profile pr --group tests
python3 scripts/ci_gate.py --profile pr --group smith
python3 scripts/ci_gate.py --profile pr --group samples-1
python3 scripts/ci_gate.py --profile pr --group samples-2
```

`--group` supports PR and nightly profiles. Use isolated checkouts when running
groups concurrently: several suites own fixed fixture/output paths. The full
local command runs every gate in registry order. The runner rejects a group
inventory that omits, duplicates, or invents a gate; its self-test also checks
that each hosted matrix exactly matches its profile's group inventory.

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
native capture. Existing suite assertions and required gates remain in place;
these explicit invocations do not establish native bootstrap or retire the
full PR profile.

Nightly uses `checks`, `analysis`, `tests`, `samples-1`, `samples-2`, `kernel`,
and `trust` groups. The `trust` job runs the stage-loop fixpoint/drift gate and
then the deeper OuroSmith profile in the same checkout. `Full` runs even after
a job failure and fails unless every matrix group succeeds. Reports are
uploaded separately as `nightly-<group>` artifacts. Hosted PR matrix jobs use static names `PR` and `Portable` so a skipped
matrix does not publish an unevaluated expression. When those jobs run,
GitHub appends the matrix value: `PR (checks)`, `PR (analysis)`, `PR (tests)`,
`PR (smith)`, `PR (samples-1)`, `PR (samples-2)`, `Portable (ubuntu-latest)`,
and `Portable (macos-latest)`. Portable restores the compiler cache when
present, then builds `ouro1` before `kernel_hardening_suite.py`.
The `analysis`, `tests`, `smith`, `samples-1`, and `samples-2` jobs also
build `ouro1` after a cache miss; `checks` stays lint/quality-only.
`scripts/apply_github_settings.py` recommends
those running check names, plus `Paths`, `Kernel`, `Editor`, and `Review`.
Existing hosted branch rules need the same check-name update when adopting
the split workflow.

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

The `compiler-checking` gate is required in the PR `tests` group, nightly,
manual, and `kernel` profiles. Its Ouro-owned fixture inventory is in
`tools/test/suites.ouro`; it checks, builds, and executes the compiler laws,
constructor-closure laws, native x86-64 encoding, MIR, PE, lowering, GC metadata,
liveness assertions, and related runner regressions. Support-only fixture
modules are checked through their imports. These assertions currently execute
through the transitional C bootstrap; they do not run the emitted Windows
executables. A failed checker process cannot pass
by printing `CHECK_OK`. Missing C tools and any check, build, or assertion
failure block this suite; it does not require OCaml. Bounded capture adds
29 pure API laws alongside the 9 compiler binding and 4 primitive registry
laws. These check byte preservation, tagged failures, exact child status,
limit validation, and primitive identity; they do not prove Windows Job
enforcement or descendant cleanup.

```sh
sh scripts/test_suite.sh --compiler-checking
sh scripts/test_suite.sh --compiler-checking --list
```

The native-lowering fixture runs each assertion in a separate process to bound
the transitional C host's compiler heap. It retains the full case inventory,
rejects duplicate names, and requires each child's exact output and zero status.

The command uses the configured bootstrap in `OURO_C_BUILD_DIR`, runs builds
with one worker, and writes logs under `_build/compiler_check_suite` (or
`TEST_SUITE_OUT`). The same gate is registered in the Ouro-native `suite-native`
profile. User-test and stage-loop gates remain separate.

On Windows, the required frontend-security host suite also uses its freshly
built `n1-host` to emit the 29 bounded-process API laws, runtime fixture, and
denied-commit child as direct PE32+ images. All 28 host probes
remain required, including reachability-round fuel, error-payload and nested
allocation checks. The native section requires all 29 API result lines in
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
compilation have separate bounded phases. The native-tool cache receipts bind
the exact sources, producer, and executable; each mode still executes the laws.
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
sh scripts/ouro_repo_gate.sh --profile docs --out _build/ouro_repo_gate/docs
sh scripts/ouro_repo_gate.sh --profile project --out _build/ouro_repo_gate/project
sh scripts/ouro_repo_gate.sh --profile workflow --out _build/ouro_repo_gate/workflow
sh scripts/ouro_repo_gate.sh --profile control-plane-native --out _build/ouro_repo_gate/control-plane-native
sh scripts/ouro_repo_gate.sh --profile retirement --out _build/ouro_repo_gate/retirement
sh scripts/ouro_repo_gate.sh --profile pr-native --out _build/ouro_repo_gate/pr-native
```

The Ouro-native CI runner can list or run grouped profiles without Python
composition:

```sh
sh scripts/ouro_ci_gate.sh --profile smoke --out _build/ouro_ci/smoke
sh scripts/ouro_ci_gate.sh --profile docs --out _build/ouro_ci/docs
sh scripts/ouro_ci_gate.sh --profile project --out _build/ouro_ci/project
sh scripts/ouro_ci_gate.sh --profile repo --out _build/ouro_ci/repo
sh scripts/ouro_ci_gate.sh --profile quickstart-native --out _build/ouro_ci/quickstart-native
sh scripts/ouro_ci_gate.sh --profile suite-native --out _build/ouro_ci/suite-native
sh scripts/ouro_ci_gate.sh --profile control-plane-native --out _build/ouro_ci/control-plane-native
sh scripts/ouro_ci_gate.sh --profile retirement --out _build/ouro_ci/retirement
sh scripts/ouro_ci_gate.sh --profile pr-native --list
sh scripts/ouro_ci_gate.sh --profile pr-native --out _build/ouro_ci/pr-native
sh scripts/ouro_ci_gate.sh --profile host-bound --out _build/ouro_ci/host-bound
```

The native launchers select their backend explicitly and print
`EXECUTION_BACKEND=ouro-native-repo-gate` or
`EXECUTION_BACKEND=ouro-native-ci-gate`. Unknown options, profiles, and gate
names, missing option values, positional arguments, and zero selected gates are
usage errors with exit status 2. The special `host-bound` profile rejects
`--gate` because it has one fixed inventory operation.

`pr-native` runs the Ouro-native docs, project-surface, and workflow gate subset.
It is useful for repository-control-plane changes, but it is not full parity
with `python3 scripts/ci_gate.py --profile pr`. The Python PR profile remains the
compatibility/reference full PR readiness path for broad suites, bootstrap
evidence, cache parity, release packaging, and specialized analyzer checks.

`control-plane-native` adds complete Python/shell inventory coverage,
wrapper/reference consistency checks, host-bound report generation, and the
Ouro-owned 64-row displacement, checker-regression, fail-closed inventory, and
manifest-validation fixture suite. `retirement` adds stricter failure behavior
for stale metadata and rejects any remaining `migration_status=migrate` row.

Repository suites for manifests, formatting, documentation, lines, native lint
fixtures, runtime IO, user tests, samples, and quickstart now keep their cases
and assertions in Ouro. Their documented shell commands are compiler/bootstrap
compatibility launchers; `lint_suite.sh` additionally sequences the host-bound
regex/SARIF Clippy-grade reference, and `scripts/process_stdin.sh` is the minimal
stdin adapter until `proc_exec` grows a typed stdin argument.

Python and shell scripts remain only as bootstrap, reference, suite, or
compatibility layers where parity is incomplete. Do not delete a host script
unless the Ouro-native replacement has matching behavior, focused parity
evidence, updated docs, no active references, and no bootstrap dependency.

## Hosted workflows

| Workflow | Role |
| --- | --- |
| `ouro-pr.yml` | Parallel PR, kernel, editor, and portable checks |
| `ouro-nightly-full.yml` | Scheduled full checks |
| `ouro-manual-trust.yml` | On-demand check profiles |
| `dependency-review.yml` | Changed dependency and workflow checks |
| `ouro-release.yml` | Build and publish tag drafts and weekly snapshots |
| `ouro-pages.yml` | Build `site/` and publish GitHub Pages |

Hosted path selection is fail-closed for validation: missing revisions, a Git
error, or an empty diff runs every applicable job. An editor-only change runs
the VS Code test job while skipping unrelated compiler work.
A `site/`-only change is treated as a dependency/path change and does not start
the compiler suites.
The hosted `Kernel` job runs `python3 scripts/ci_gate.py --profile kernel` and
uploads its compiler, hardening, boundary, generated-law, scale, and depth
reports. Its path selector covers the checker and its compiler, runtime,
standard-library, test, and gate dependencies. Missing required probes fail
the job.
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
guarded weekly snapshot job. The public
site workflow requests `pages` and `id-token` write only in the main-branch
publish job. External actions are pinned to a full commit SHA.

The public site source lives in `site/`. Hosted Pages use
`https://eluvane.github.io/ouro/`. After a custom domain is attached, rebuild
with `SITE_BASE=/` and add the hostname to `site/public/CNAME`. GitHub Pages
must be set to GitHub Actions as the source.

Hosted repository reachability is separate from local project-surface policy.
`scripts/github_project_hosted_probe.py` records `gh repo view` reachability for
manual or hosted contexts, but `scripts/github_project_gate.py` does not depend
on it and does not claim native hosted GitHub API parity.

Policy notes that must stay visible in this page: cache is not trusted;
`kernel_hardening_suite.py`; generated artifact drift; cache-on/cache-off parity;
`pull_request_target`; `workflow_dispatch`; nightly; local reproduction; release
candidate; `github_project_gate.py`; `release_package.py`;
`strict_quality_firewall.py`; Strict-quality SARIF policy.

## Reports and failures

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

The public repository surface keeps compatibility entry points for callers that
still use the old command names:

```sh
python3 scripts/docs_examples_gate.py
python3 scripts/github_project_gate.py
python3 scripts/github_workflow_gate.py
```

These wrappers remove any previous native report before delegation and require a
fresh `ouro.repo-gate-report.v1` for the requested profile. Missing, malformed,
stale, empty-gate, backend-mismatched, or return-code-inconsistent evidence is
blocking. Their legacy reports record `mode=compatibility-wrapper`, the delegated
backend, native and effective return codes, and native report validity.

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

The Ouro-native `workflow` profile parses the supported repository-owned YAML
mapping structure instead of searching raw text. Comments and block-scalar text
cannot satisfy required triggers, permissions, concurrency, jobs, or artifact
steps. Duplicate keys and unsupported anchors, aliases, merge keys, tags, flow
mappings, quoted/complex keys, or tab indentation fail closed. Privileged
triggers, `continue-on-error`, broad write permissions, and mutable external
action refs are rejected structurally. Write exceptions are the exact
draft-publish job with its tag guard and draft release command, the exact
weekly snapshot job with its main-branch schedule or dispatch guard, and the
exact pages publish job with its main-branch push guard and official
deploy-pages action. `scripts/github_workflow_gate.py` preserves the legacy CLI/report path while
delegating policy to this native profile.

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

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
