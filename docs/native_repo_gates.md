<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=GATES&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="GATES banner"
  />
</p>

# Native repository gates

Ouro-native repository gates are the preferred checks for supported repository-owned documentation, project metadata, GitHub Actions workflow policy, and control-plane retirement evidence.

Run the focused profiles with:

```sh
sh scripts/ouro_repo_gate.sh --profile docs-native --out _build/ouro_repo_gate/docs-native
sh scripts/ouro_repo_gate.sh --profile project-native --out _build/ouro_repo_gate/project-native
sh scripts/ouro_repo_gate.sh --profile workflow-native --out _build/ouro_repo_gate/workflow-native
sh scripts/ouro_repo_gate.sh --profile control-plane-native --out _build/ouro_repo_gate/control-plane-native
sh scripts/ouro_repo_gate.sh --profile retirement --out _build/ouro_repo_gate/retirement
sh scripts/ouro_ci_gate.sh --profile pr-native --out _build/ouro_ci/pr-native
sh scripts/ouro_ci_gate.sh --profile control-plane-native --out _build/ouro_ci/control-plane-native
sh scripts/ouro_ci_gate.sh --profile retirement --out _build/ouro_ci/retirement
sh scripts/ouro_ci_gate.sh --profile host-bound --out _build/ouro_ci/host-bound
```

The native repo gates validate repository-owned files and policies. They do not replace bootstrap, full hosted CI orchestration, release packaging, quality analyzer composition, or hosted GitHub API probes by themselves.

## Explicit execution paths

The repository and CI launchers now select the native backend explicitly. Their stderr includes `EXECUTION_BACKEND=ouro-native-repo-gate` or `EXECUTION_BACKEND=ouro-native-ci-gate`, and their JSON reports include `execution_backend` plus `execution_mode`. A native profile never obtains a passing result from a Python compatibility implementation.

`scripts/build_tool.sh` defaults to `OURO_BUILD_TOOL_MODE=native`. The remaining host adapter is available only through an explicit mode:

```sh
OURO_BUILD_TOOL_MODE=host-wrapper sh scripts/build_tool.sh tools/collect.ouro _build/compat/ouro-collect
OURO_BUILD_TOOL_MODE=auto sh scripts/build_tool.sh tools/collect.ouro _build/compat/ouro-collect
```

`host-wrapper` rejects unsupported entries instead of starting a native build. `auto` is retained only as a named compatibility mode and prints the selected backend and the reason for it. It is not the default. Bootstrap-required native builds print `BOOTSTRAP_BUILD_REQUIRED`; successful rebuilds print `NATIVE_TOOL_REBUILT`; failed rebuilds print `NATIVE_TOOL_REBUILD_FAILED`, and an older executable is reported as `STALE_BINARY_REJECTED` rather than executed.

Native tool source manifests are mandatory provenance for wrapper freshness checks. A missing, empty, escaping, or malformed `<tool>.sources` manifest causes an explicit rebuild. The launchers no longer hide a missing manifest by falling back to a broad directory scan. A failed rebuild cannot reuse the previously discovered executable.

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
exact guarded draft-publication job and the exact guarded weekly snapshot job.

Full PR readiness still uses `python3 scripts/ci_gate.py --profile pr` unless a workflow explicitly selects the native profile and its parity coverage is sufficient for that context. The Python PR profile routes the supported docs, project, and workflow policy rows through `sh scripts/ouro_repo_gate.sh --profile docs-native`, `project-native`, and `workflow-native`; the legacy Python entry points remain compatibility commands for direct callers.

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
