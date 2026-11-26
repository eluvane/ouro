# Native repository gates

The native repository gates check documentation, project metadata, workflow
policy, and host-script retirement. See [CI profiles and commands](ci.md#ouro-native-control-plane-displacement)
for the surrounding checks, including hosted GitHub reachability.

## Explicit execution paths

The repository and CI launchers select the native backend. On stderr they
identify it as `EXECUTION_BACKEND=ouro-native-repo-gate` or
`EXECUTION_BACKEND=ouro-native-ci-gate`. The JSON reports record
`execution_backend` and `execution_mode`. A native profile requires evidence
from the native backend.

The [build cache contract](build.md#cache-model) owns `OURO_BUILD_TOOL_MODE`,
source manifests, rebuild receipts, and stale-binary refusal.

Unknown options, profiles, and gate names exit with status 2. Missing option
values, positional arguments, and an empty gate selection use the same status.
The `host-bound` profile runs one fixed inventory operation and rejects
`--gate`.

## Standalone native host-bound worker

Use PowerShell from the repository root on native Windows. Provision an accepted
native `coil.exe` in `_build/native/` and make Git available on `PATH` for the
repository inventory. The commands build both images in `_build/native/` and
write reports under `_build/ouro_ci/host-bound-native/`.

```powershell
.\_build\native\coil.exe build tools/repo_gate/main.ouro --out _build/native/ouro-repo-gate.exe
.\_build\native\coil.exe build tools/ci_gate/native_host_bound_main.ouro --out _build/native/ouro-ci-host-bound.exe
.\_build\native\ouro-ci-host-bound.exe --profile host-bound --root . --out _build/ouro_ci/host-bound-native
```

The worker resolves the fixed `ouro-repo-gate.exe` beside its loaded Windows
image and preserves the literal root/output arguments and inherited working
directory. Missing siblings, loaded-image errors, capture failures and a zero
child status without the required current report fail. Its child tree uses one
CPU, 3072 MiB, a 900-second provisional deadline and 16 MiB per captured stream;
exceeding a limit fails instead of accepting a truncated result.

Both entries invalidate prior reports before starting the child, apply the same
report validation, and write the same inventory and summary. The reference
`tools/ci_gate/main.ouro` delegates through the shell. The hosted test suite
exercises the required failure injection cases. The standalone worker supplies
evidence for the host-bound profile. Full CI parity and isolated-host
acceptance require additional evidence.

## Compatibility and host-reference boundaries

Python and shell entry points remain available as bootstrap, reference, suite,
or compatibility layers until the host-bound report marks them eligible for
removal. Consult that report for remaining migration blockers.

### Host-bound inventory and validation

The `host-bound` profile writes a deterministic inventory to `host-bound.json`.
It covers current repository-visible `.py` and `.sh` files and explicit
`remove` rows retained for retired scripts. Each row records `kind`, `path`,
`role`, `native_replacement`, `parity_status`, `removal_eligibility`, `blocker`,
`evidence`, and `migration_status` (`remove`, `migrate`, `thin-wrapper`, or
`host-bound`).

The profile checks native inventory consistency before writing the report.
Missing, stale, duplicate, or reappearing retired paths make both the report
and the command fail. The delegated `control-plane-native` command must
succeed and write a current `ouro.repo-gate-report.v1` with all of the
following properties.

- Version `1`, profile `control-plane-native`, backend `ouro-native-repo-gate`,
  and execution mode `native`.
- Unique keys in the report, gate, and metric objects.
- A nonempty list of well-formed passing gates.
- Empty issue lists for the report and each gate, with `pass=true` in the report.

A missing, malformed, or non-passing report fails the profile even when the
child exits with status zero.

Keep `wrapper-only` paths limited to CLI compatibility and delegate policy
logic to its owner. Record the concrete host capability or reviewed trust or
parity blocker for every `not-removable` path before considering removal.

### Retirement checks

The `control-plane-native` profile covers docs, project, and workflow checks,
inventory consistency, and host-bound reporting. Its Ouro fixtures cover
native replacements, checker regressions, invalid inventory, and manifest
validation. Repository gates reject unknown profiles. Inventory validation
rejects script, replacement, and evidence paths that normalize outside the
repository, including Windows drive paths. Use
`scripts/ouro_native_repo_ci_suite.sh` to run the bootstrap suite, which also
exercises host-bound startup, report, and rebuild failures.

The `retirement` profile rejects stale wrapper, reference, or removal metadata
and any remaining `migration_status=migrate` row.

### Compatibility wrapper reports

The local docs, project, and workflow policy lives in `tools/repo_gate/`.
`scripts/docs_examples_gate.py`, `scripts/github_project_gate.py`, and
`scripts/github_workflow_gate.py` remove any previous native report before
delegating. They require a fresh, well-formed `ouro.repo-gate-report.v1`
with the requested profile, native backend, a nonempty gate list, and a
`pass` field consistent with the native exit code. A missing, malformed, stale,
or contradictory report fails the wrapper even when the child exits with
status zero. Wrapper reports record `mode=compatibility-wrapper`, the delegated
backend, the native and effective return codes, and report validity.

Hosted GitHub reachability uses a separate host-bound probe.

### Workflow policy

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
`pages` and `id-token` write access is restricted to the `publish-pages` job,
where the scanner checks the guard for pushes to `main` and the official
`actions/deploy-pages` action. The workflow also allows publication after a
manual dispatch on `main`.

Full PR readiness and profile composition are defined in [CI](ci.md#local-profiles).
