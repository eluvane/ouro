# Native repository gates

Ouro-native repository gates own supported documentation, project metadata,
workflow policy, and host-script retirement checks. [CI](ci.md#ouro-native-control-plane-displacement)
lists their commands and profile coverage. These gates alone do not establish
full PR readiness or hosted GitHub API reachability.

## Explicit execution paths

The repository and CI launchers now select the native backend explicitly. Their stderr includes `EXECUTION_BACKEND=ouro-native-repo-gate` or `EXECUTION_BACKEND=ouro-native-ci-gate`, and their JSON reports include `execution_backend` plus `execution_mode`. A native profile never obtains a passing result from a Python compatibility implementation.

The [build cache contract](build.md#cache-model) owns `OURO_BUILD_TOOL_MODE`,
source manifests, rebuild receipts, and stale-binary refusal.

CLI selection is strict. Unknown options, unknown profiles, unknown gate names, missing option values, positional arguments, and zero selected gates exit with status 2. `--gate` is rejected for the special `host-bound` inventory profile because that profile has one fixed internal operation.

## Compatibility and host-reference boundaries

Python and shell entry points remain allowed as bootstrap, reference, suite, or compatibility layers until the host-bound report marks the path eligible for removal. The host-bound report is the source of truth for remaining migration blockers.

The `host-bound` profile writes a deterministic inventory covering every current repository-visible `.py` and `.sh` path and explicit `remove` rows retained as migration evidence. Each row records `migration_status` (`remove`, `migrate`, `thin-wrapper`, or `host-bound`), `kind`, `path`, `role`, `native_replacement`, `parity_status`, `removal_eligibility`, `blocker`, and `evidence`. The standalone profile runs native inventory consistency before emitting its report; missing, stale, duplicate, or reappearing removed paths make both the report and command fail. It also requires the delegated `control-plane-native` report to exist, parse, name the native backend, contain at least one gate, and report `pass=true`; a subprocess status of zero without that evidence is a failure. A path marked `wrapper-only` may preserve CLI compatibility, but must not contain duplicated policy logic. A path marked `not-removable` needs a concrete host capability or reviewed trust/parity blocker before deletion.

The `control-plane-native` profile runs native docs/project/workflow coverage, inventory consistency, host-bound reporting, and the Ouro-owned displacement, checker-regression, fail-closed inventory, and manifest-validation fixture suite. It also rejects unknown repository-gate profiles before any fallback and rejects host inventory, replacement, or evidence paths that normalize outside the repository, including Windows drive paths. `scripts/ouro_native_repo_ci_suite.sh` remains its bootstrap launcher and additionally exercises host-bound start/report/rebuild failure seams. The `retirement` profile is stricter: in addition to stale wrapper/reference/removal metadata, it rejects any remaining `migration_status=migrate` row.

The docs and project local policy sources live in `tools/repo_gate/`. `scripts/docs_examples_gate.py`, `scripts/github_project_gate.py`, and `scripts/github_workflow_gate.py` are explicit compatibility wrappers. Before delegation they remove the expected native report, then require a fresh, well-formed `ouro.repo-gate-report.v1` with the requested profile, native execution backend, nonempty gate list, and an exit-code-consistent `pass` field. A missing, malformed, stale, or contradictory native report makes the wrapper fail even when the child process returned zero. Wrapper reports record `mode=compatibility-wrapper`, delegated backend, native return code, effective return code, and report validity.

Hosted GitHub reachability remains a separate host-bound probe and is not claimed as native API parity.

The workflow scanner is conservative. It parses the supported two-space mapping
subset used by Ouro's owned workflows, not arbitrary YAML. Comments and block
scalar bodies cannot satisfy policy markers. Duplicate keys, tabs, quoted or
complex keys, anchors, aliases, merges, tags, and flow mappings are rejected
instead of being guessed. Structured checks reject privileged triggers, broad
write permissions, `continue-on-error`, mutable external action refs, missing
job timeouts, duplicate display names, unsafe cache save paths, and unsupported
`scripts/ci_gate.py` invocations. Release write access is accepted only in the
exact draft-publication job with its tag guard and draft-release command, or
the exact snapshot job with its main-branch schedule or dispatch guard.
`pages` and `id-token` write access is accepted only in the exact Pages publish
job with its main-branch push guard and official `deploy-pages` action.

Full PR readiness and profile composition are defined in [CI](ci.md#local-profiles).
