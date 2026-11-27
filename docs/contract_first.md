# Contract-first development

Define required behavior, select and validate the checks for it, then change
the implementation. Complete the task when the final revision satisfies the
applicable mandatory contracts and the recorded results show what was checked.

This standard applies to automated development in Ouro when the maintainer
directs its use, including subsequent development tasks in the repository.
It supplements the repository's automation policy, contributor workflow, and
product specifications. Follow the permissions and scope of the task. During
handoff or context recovery, carry forward this standard's location, the
agreed requirements and scope, and the state of their contracts.
[Repository automation policy](../AGENTS.md) ·
[Contributing to Ouro](../CONTRIBUTING.md)

`MUST` and `MUST NOT` express requirements. A departure from `SHOULD` requires
a recorded reason and an assessment of its consequences. `MAY` permits a
choice under the stated conditions.

## Contents

- [Find the governing requirements](#find-the-governing-requirements)
- [Record requirements and contracts](#record-requirements-and-contracts)
- [Development workflow](#development-workflow)
- [Protect and correct contracts](#protect-and-correct-contracts)
- [Get approval for scope and contract changes](#get-approval-for-scope-and-contract-changes)
- [Ouro subsystem contracts](#ouro-subsystem-contracts)
- [Trust, compatibility, and generated artifacts](#trust-compatibility-and-generated-artifacts)
- [Select checks and record results](#select-checks-and-record-results)
- [Example of an import regression](#example-of-an-import-regression)
- [Report the result](#report-the-result)
- [Enforce critical contracts](#enforce-critical-contracts)

## Find the governing requirements

Identify the owners and canonical specifications of the affected contracts.
Use the implementation to establish what the code does, the specification
or agreed decision to establish what it should do, and executed checks as
evidence for the cases they cover. A test expectation MUST have a basis in a
requirement, a governing contract, or an agreed decision.
[Ouro documentation index](README.md)

Use the native toolchain contract for current requirements. Treat the
historical proposal and roadmap goals according to their status. An accepted
request for comments (RFC) records a decision. Verify implementation status
before claiming the feature is available. Base public semantics on governing
specifications and accepted decisions.
[Native toolchain contract](design.md#native-toolchain-contract) ·
[Historical proposal](ouro.md) ·
[Roadmap](roadmap.md) ·
[RFC process](rfc/README.md)

When sources disagree, record the conflicting claims, references, affected
behavior, and evidence. Apply a documented priority or status when it
resolves the conflict. If the unresolved choice affects public behavior,
trust, compatibility, or architecture, get the maintainer's decision before
implementing that part.

## Record requirements and contracts

A requirement states observable behavior or a constraint. A contract defines
the conditions under which it holds. A test, fixture and runner, validator,
assertion, or analyzer checks the contract. Evidence records the actual
result for the inputs and source state tested.

Every material requirement MUST have a contract. Cover acceptance criteria,
behavior that changes or must be preserved, rejection cases, trust
boundaries, compatibility, and resource limits that apply to the task.
Assign each requirement and contract a unique ID. Preserve existing IDs
where possible. Link each requirement and its source to its contracts,
the artifacts and runners that check them, and the baseline and final results.
A single requirement can have several contracts. One parameterized test can
cover several contracts if the mapping is explicit.

Reuse existing test infrastructure and task records where they fit. Record
where the contracts live so another contributor can find them. Keep the
detail proportional to the work and the cost of failure. A small fix can
use one existing test and a short contract record. A documentation-only
change can use existing checks and a reproducible content review.

### Contract record template

Replace the bracketed fields with task-specific values. For an inapplicable
field, give the reason. Use a short traceability table for multiple
requirements where it helps readers find the checks and evidence.

```markdown
### CON-<area>-<task>-<number> <observable property>

- Requirement (REQ-<area>-<task>-<number>) and exact statement
- Source, section, requirement level, and conditions of applicability
- Preconditions, including inputs, state, platform, backend, and tools
- Action and expected result, with an independent basis for the expectation
- Postconditions, permitted effects, and invariants
- Invalid inputs, expected failure class or code, and state after failure
- Boundary cases, limits, determinism requirements, and non-goals
- Check command, execution mode, and pass criteria
- Artifact path, test or case name, and suite registration
- Manual protocol if needed, with reason, setup, steps, and expected evidence
- Baseline revision and working changes, with result before implementation
- Final result, command, environment, and log or report
```

## Development workflow

### A. Investigate the change

1. Establish the repository, branch, base revision, and scope. Run
   `git status --short` and inspect relevant diffs. Preserve existing work.
2. Read applicable instructions, specifications, and artifact generation
   rules. Inspect the implementation that owns the behavior, its callers,
   dependencies, and neighboring tests and fixtures. Find the runner that
   actually executes their assertions.
3. Identify affected public interfaces, invariants, regression risks, and
   environment requirements. For a defect, reproduce it or record the
   specific blocker.

### B. Define the requirements

Before editing the implementation, record what changes and what must stay
compatible. Include valid inputs and expected results, errors and state
after failure, boundary cases, invariants, permitted effects, and relevant
limits on resources, platforms, performance, security, or determinism.
Record scope, non-goals, sources, assumptions, and open decisions.

Derive each requirement from the task, a governing contract, or an agreed
decision. Define success criteria before implementation. Base numeric
thresholds and platform commitments on those sources. Reuse facts already
established by the project. A recorded, reversible assumption is acceptable
when it leaves public semantics, interfaces, architecture, and trust
boundaries intact. Resolve material uncertainties before changing the
affected behavior.

### C. Select executable checks

Create or select the checking artifacts before changing the implementation.
Use the mechanism that observes the affected boundary.

| Property | Check |
| --- | --- |
| Local behavior and errors | Unit test, assertion, or invariant check |
| Component interaction or a public entry point | Integration or end-to-end test |
| Compiler acceptance and rejection | Compile-pass and compile-fail fixtures or typed checker laws |
| A family of inputs or transformations | Property-based or metamorphic tests |
| A known defect | Focused regression that distinguishes the defect from the fix |
| Exact, stable output | Golden test whose expected output follows the specification |
| An interchange format | Schema validation and consumer behavior checks |
| Compatibility | Existing consumer, command, format, or migration cases |
| Performance or resource use | Reproducible benchmark or probe with agreed metrics and limits |
| Documentation | Link, path, example, and content checks |

Check the observable outcome. For a checker interface, that may be a typed
failure. For a command-line interface, inspect the exit status, stdout,
stderr, and file effects where relevant. Assert internal details only when
they form part of an agreed interface, invariant, resource bound, or trust
guarantee.

Derive expected results independently of the code under test. Validate golden
output against its contract. For a negative case, specify the failure class
and the diagnostic fields that matter. A crash, timeout, memory exhaustion,
missing tool, or fixture setup error cannot satisfy an expected rejection.
Include a nearby valid case when it can catch blanket rejection. For checker
changes, exercise both outcomes on each affected acceptance path.

The runner MUST expose a contract violation as a detectable failure. Verify
discovery or suite registration and actual execution of the case. Use
existing mechanisms when they fit. If a property cannot be checked
automatically, record why and define a reproducible manual protocol with
expected observations and evidence. Use the mandatory automated gate when
one exists. If its environment is unavailable, record the check as
`NOT RUN` or `BLOCKED` according to its effect on the task.

### D. Validate the checks against the baseline

Review preconditions, expected outcomes, errors, boundaries, and coverage
before the first implementation change. Resolve contradictions before
implementing the affected part.

| Change | Required baseline evidence |
| --- | --- |
| New behavior | The check detects the missing behavior. If it passes, determine whether the behavior already exists or the check fails to distinguish it. |
| Bug fix | The regression reproduces the reported violation on the original implementation. |
| Refactoring | The checks for the guarantees being preserved pass on the original implementation. |
| Documentation or a contract already met | The applicable checks and content review are identified. An artificial failing test is unnecessary. |

An absent API can be the expected baseline failure if the runner works and
the failure identifies that API. A minimal test harness may be
needed. Keep production behavior out of it. Save the baseline result before
editing the implementation. If required baseline evidence is unavailable,
record the blocker and continue only with independent work.

For critical checker or trust-boundary laws, prefer existing mutation or
fault-injection checks when applicable. First confirm a clean baseline,
then confirm the law detects the specified fault. Keep temporary mutations
out of the final diff. Obtain any required approval before implementation.

### E. Implement the change

Implement against the validated contracts after steps A–D. Change the layer
that owns the behavior. Support a root-cause claim with a test or observation
that links the cause to the violation. Use existing architecture and
dependencies where they fit. Keep the diff focused and preserve independent
checks, trust boundaries, and generated-artifact procedures.

### F. Verify the implementation

Run the selected checks, map failures to their contracts, and determine
whether the product, harness, or environment caused each failure. Fix
in-scope violations and rerun the affected checks. Include consumers and
neighboring regression cases when the change crosses a boundary. Continue
until applicable contracts pass or a missing tool, decision, or permission
blocks further work.

### G. Review the final revision

Run all applicable mandatory checks on the final revision. Rerun checks
whose evidence a later edit invalidates. Cover relevant negative and
boundary cases, compatibility, and trust boundaries. Verify that canonical
docs, examples, migrations, and generated artifacts reflect the change.
Review the full task diff and untracked files for unintended changes and
preservation of existing work. Confirm the trace from each material
requirement to the case run and its result, then report the outcome.

## Protect and correct contracts

Do not obtain a pass by removing required tests, fixtures, manifest entries,
or suite and CI routing. Preserve assertions, budgets, and covered cases.
Do not change specifications, schemas, goldens, baselines, hashes, or corpora
to match an implementation without establishing the reason. Keep mandatory
failures visible. Skips, expected failures, broad suppressions, warning-only
paths, `continue-on-error`, and empty or fabricated reports cannot satisfy a
mandatory check. Apply a narrow suppression only under the quality policy
and preserve all applicable fatal and trust checks. Keep the original
failure evidence when rerunning an unstable test.
[Quality suppression policy](quality.md#suppressions)

Use this procedure to correct a contract.

1. Identify its ID and the incorrect expectation or precondition.
2. Cite the controlling specification, reproducible evidence, or agreed
   decision that establishes the error.
3. Explain the effect on acceptance, compatibility, and trust. Propose
   the corrected expectation and related checks.
4. Obtain approval where required. An existing decision can authorize
   restoring behavior it already specifies.
5. Update the requirement, contract, checks, and affected documentation
   together. Preserve the rationale and evidence. Make the test correction
   identifiable in the diff and report.

## Get approval for scope and contract changes

Connect every changed component to a requirement, contract, or necessary
check. Keep unrelated refactors, renames, moves, dependency and configuration
updates, CI changes, and new features outside the task. When more work is
necessary, explain the contract it enables, why a smaller change is
insufficient, which files and consumers it affects, and how to verify it.
Get approval before materially expanding scope or editing outside an agreed
file list. Report dependencies blocked by scope and continue independent
authorized work.

Discuss changes to syntax, typechecking, acceptance, the checker or trusted
boundary, `Ouro.seal`, `Ouro.lock`, the package CLI, Core artifacts,
compatibility-sensitive commands, and bootstrap policy before implementation.
Use the RFC process for substantial decisions about the language, trust
boundary, compatibility, packages, runtime, or repository architecture.
Include the alternatives and migration consequences reviewers need.
Small bug fixes, internal refactors, documentation corrections, and work
that implements an accepted contract are exempt from the RFC process.
Follow the applicable scope and trust approval requirements in each case.
Record the chosen behavior and its material compatibility and trust effects
when seeking the maintainer's approval.
[Choose a change](../CONTRIBUTING.md#choose-a-change) ·
[Ouro RFC process](rfc/README.md)

## Ouro subsystem contracts

Use these cases to identify the affected boundary. The validation matrix
owns the command selection for that boundary.
[CI validation matrix](ci.md#validation-matrix)

### Language and compiler checking

- Syntax and preprocessing. Cover accepted and rejected forms, precedence,
  desugaring, literal bytes, directives, token boundaries, and mapped spans.
  [Syntax](syntax.md) ·
  [Canonical source](canonical_source.md) ·
  [Parser laws](../tests/language_ergonomics/parser_laws.ouro) ·
  [Source laws](../tests/compiler_native_source_tests.ouro) ·
  [Source span laws](../tests/source_span_tests.ouro)
- Elaboration, refinement, types, and recursion. Cover checked Core,
  scope and substitution, dependent refinements, universes, inductives,
  motives, the decreasing argument, and typed rejection. Exercise the
  affected positive and negative cases, including nested fixpoints, binder
  scope, arity, and positivity where relevant.
  [Compiler checking](kernel_design.md) ·
  [Structural laws](../tests/compiler_structural_tests.ouro) ·
  [Refinement laws](../tests/compiler_refine_tests.ouro) ·
  [Constructor laws](../tests/compiler_constructor_tests.ouro) ·
  [Checker laws](../tests/compiler_check_tests.ouro)
- Imports and evaluation. Cover the complete closure and all imported bodies,
  cycles, missing units, visibility, selectors and aliases, name collisions,
  conversion, observable values, typed errors, and budget exhaustion where
  relevant. Exercise primitive contracts when the change reaches them.
  [Modules and imports](syntax.md#modules-and-imports) ·
  [Module laws](../tests/compiler_module_tests.ouro) ·
  [Module name laws](../tests/compiler_module_names_tests.ouro) ·
  [Reduction laws](../tests/compiler_reduce_tests.ouro) ·
  [OuroSmith](ouro_smith.md)

### Native execution, effects, and the standard library

- Native compilation. Cover checked lowering, machine intermediate
  representation (MIR) validation, the application binary interface (ABI),
  PE encoding, garbage collection roots and liveness, and execution of
  the built target.
  [Lowering laws](../tests/native_lower_tests.ouro) ·
  [MIR laws](../tests/native_mir_tests.ouro) ·
  [PE laws](../tests/native_pe_tests.ouro) ·
  [GC laws](../tests/native_gc_tests.ouro)
- Effects and IO. Check lowering, effect order and timing, stdout and stderr,
  exit status, errors, ownership, and cleanup.
  [Effects and IO](effects_design.md) ·
  [Runtime IO suite](../scripts/runtime_io_suite.sh) ·
  [Sample cases](../tools/test/sample_cases.ouro)
- Standard library. Check public types and values, errors, edge cases,
  and representative consumers.
  [Practical standard library](practical_stdlib.md) ·
  [Practical library laws](../tests/practical_stdlib_tests.ouro) ·
  [Workflow laws](../tests/workflow_stdlib_tests.ouro)

Report C-hosted law runs, execution of a generated Windows PE, and compiler
bootstrap separately. A type check, byte comparison, or MIR test covers only
its own boundary. For direct native execution, identify the supported target,
host, and artifact provenance. Compare backends only within the documented
runtime surface. When a required native bridge is unavailable, report the
validation gap and identify the backend that actually ran.
[Runtime surface](effects_design.md#runtime-surface) ·
[CI local profiles](ci.md#local-profiles)

### Tools, formats, and builds

- Diagnostics and CLI. Check class, code, severity, position, required text,
  argument parsing, deterministic output, file effects, exit status, and
  output channels.
  [Diagnostic registry](../quality/diagnostics.json) ·
  [Diagnostic contracts](../quality/smith/diagnostic_contract.json) ·
  [Command reference](tooling.md)
- Language server, analyzer, and linter. Check message framing and order,
  capabilities, unsaved-buffer diagnostics, supported requests, true findings,
  false positives, witnesses, severity, and safe edits as applicable.
  [Language server suite](../scripts/lsp_suite.sh) ·
  [Quality policy](quality.md) ·
  [Analyzer fixtures](../tests/analyze/)
- Packages. Check resolution, vendoring, import inventory, identity, digests,
  malformed locks, verification, registry and path errors, and partial
  failures at the package consumer boundary.
  [Packages](pkg.md) ·
  [Package suite](../scripts/pkg_suite.sh) ·
  [Package scanner laws](../tests/pkg_scanner_tests.ouro)
- Core artifacts and bootstrap. Check format versions, completeness, framing,
  and rejection in the actual format consumer. For bootstrap, check provenance,
  source and producer identity, hashes, the stage loop, and relevant cache
  modes.
  [Core artifacts](kernel_core_artifact.md) ·
  [Checked output laws](../tests/compiler_checked_output_tests.ouro) ·
  [Checked program laws](../tests/compiler_checked_program_tests.ouro) ·
  [Build and bootstrap](build.md) ·
  [Bootstrap tests](../scripts/bootstrap_compiler_test.py) ·
  [Artifact drift check](../scripts/generated_artifact_drift_check.py)

With no input, the user runner discovers `*_test.ouro` files. Compiler laws
in `*_tests.ouro` run through explicit suite registration. An imported support
fixture can be checked as a dependency. Verify case execution separately from
a build or fixture listing.
[User test discovery](tooling.md#user-tests) ·
[Compiler suite inventory](../tools/test/suites.ouro)

## Trust, compatibility, and generated artifacts

### Compiler acceptance and trust

The declaration checker in `compiler/file_elab.ouro` owns compiler acceptance.
Independent OCaml and Python Core replay paths are historical. Before
changing the checker, environment construction, import closure, runtime, or
another trusted boundary, identify who accepts the program and checks each
input. Record new dependencies, authority, and assumptions. Identify the
checks that prevent bypass and the positive, negative, resource, and
cancellation cases that cover the change. State the limits of that evidence.
[Compiler checking](kernel_design.md) ·
[Compiler checking boundary](tcb.md#compiler-checking-boundary)

Preserve full checking of declarations, including imported bodies and effect
roots. Treat exhaustion, cancellation, and malformed input as failures. A
consumer may accept only the complete checked environment. Keep runtime IO
and platform calls out of type conversion. Obtain approval for additions
to the pure checker's dependency closure and follow the allowlist process.

Compiler acceptance remains mandatory even when frontend checks, analysis,
package metadata, caches, generated output, or build receipts indicate
success. Preserve constructor ownership and rechecking of declarations and
metadata in native lowering. Treat `CheckedProgram` as a value whose
contents must satisfy those checks. Describe test results within the
scenarios exercised and the project's assurance limits.
[Compiler boundary gate](../tools/repo_gate/compiler_boundary.ouro) ·
[Checked values](tcb.md#checked-values) ·
[Assurance limits](tcb.md#assurance-limits)

### Compatibility and format versions

Apply the pre-1.0 compatibility policy to changes in acceptance, evaluation,
imports, packages, CLI behavior, and diagnostics. An approved breaking change
requires tests or fixtures, canonical documentation, and migration guidance.
Preserve diagnostic codes within a release line where possible and document
approved replacements.
[Ouro stability policy](stability.md)

Use `ouro.checked-program.v1` as a diagnostic snapshot. Checker acceptance
still depends on the checked declarations. The JSON schema and corpus for
`ouro.kernel-core-artifact.v1` describe the archived replay format. Apply
each schema in its documented consumer and version. Give an incompatible
Core encoding a new version identifier under the applicable policy.
[Core artifact formats](kernel_core_artifact.md) ·
[Archived schema](spec/ouro.kernel-core-artifact.v1.schema.json) ·
[RFC 0002](rfc/0002-kernel-core-artifact.md)

### Regenerate from the source

Use the repository's generation procedure for committed C in
`compiler/stage0/` and API pages in `docs/api/`. Record the source or generator
change, exact regeneration command, reason, and checks. A regeneration-only
task needs an explicit basis. Stage0 promotion requires separate authority,
matching hashes, and full stage-loop evidence. While `c-bootstrap-v1` applies,
coordinate recovery inputs, runtime, and bundle metadata separately from
stage0 promotion. Keep build outputs, caches, logs, and host-specific files
out of the source diff.
[Generated artifacts and stage loop](build.md#generated-artifacts-and-stage-loop)

Use write-mode regeneration, corpus updates, and promotion only for their
approved purpose. Investigate drift before updating reference outputs.
Retain behavioral checks and the isolated-host and built-artifact evidence
required to establish native toolchain independence. Hash comparison, cache
hits, and matching stage bytes establish narrower properties.
[Native toolchain contract](design.md#native-toolchain-contract)

Update `Ouro.lock` through the package workflow and maintain `Ouro.seal` as
the handwritten manifest. To update vendored `_ouro_pkgs/`, change the
source package or registry and reinstall through the package workflow.
[Seal manifest](pkg.md#seal) ·
[Lockfile verification](pkg.md#lockfile-and-verification) ·
[Package installation](pkg.md#installation-and-imports)

## Select checks and record results

Choose the smallest applicable suite from the validation matrix. Cover
affected consumers and broaden checks when a boundary, change, failure,
coverage gap, or unresolved risk requires it. Use the local PR profile before
opening a requested PR when feasible. Verify command prerequisites and write
effects in the selected revision. Isolate parallel suites that share fixture
or output paths. Keep local validation offline unless network use has been
approved.
[CI validation matrix](ci.md#validation-matrix) ·
[CI local profiles](ci.md#local-profiles) ·
[Build requirements](getting_started.md#requirements)

| Status | Evidence |
| --- | --- |
| `PASS` | The expected cases and assertions ran with an acceptable exit status and a complete, current report where the runner provides one. |
| `FAIL` | A violation was observed. Report the cause supported by the evidence. |
| `NOT RUN` | The check was not executed. Record the reason. |
| `BLOCKED` | A specific missing condition prevented a mandatory check or further work. |

Report a skip, timeout, missing tool, memory limit, omitted case, or stale
receipt as incomplete or failed validation as applicable, regardless of a
wrapper's exit status. Record the exact command, source state, platform and
backend, material execution conditions, and result. For generated cases,
preserve the case or seed, applicable budgets, and replay details. A reduced
case must reproduce the same law violation or diagnostic class.
[CI reports and failures](ci.md#reports-and-failures)

Base claims about measured runtime effects on comparable before and after
runs. Use the same inputs and machine, control build and cache modes, and
record the metrics and repetitions.
[Performance measurements](code_optimization.md#measure-the-effect)

For Markdown, check relative link paths and heading fragments. The repository
link scanner strips fragments and checks the resulting paths. Verify heading
fragments separately for both same-page and cross-page links.
[Repository link scanner](../tools/repo_gate/checks.ouro)

## Example of an import regression

Consider a hypothetical bug in which the compiler accepts a module with an
invalid, unused imported body. The required behavior is full declaration
checking, including bodies the entry point never references.
[Core and declarations](kernel_design.md#core-and-declarations)

- `REQ-IMPORT-UNUSED-01` requires rejection of the invalid module and
  acceptance of its valid counterpart. Module semantics and diagnostic
  codes are outside the scope of the fix.
- `CON-IMPORT-UNUSED-01` supplies a complete ordered import closure, a valid
  entry point, an invalid unused body, and a sufficient budget. Expect a
  typed failure for that body and checker phase. At the pipeline boundary,
  also verify that no checked snapshot or emitted output is produced in a
  fresh output directory. The valid counterpart must return the complete
  accepted environment. A crash or timeout fails the regression.
- The law `bad earlier imported body cannot be skipped` checks declaration
  acceptance. Select and register an end-to-end import case to observe the
  snapshot and emission boundary. Record the exact typed expectation from
  the specification and fixture before editing.
  [Module laws](../tests/compiler_module_tests.ouro) ·
  [Compiler suite inventory](../tools/test/suites.ouro) ·
  [OuroSmith](ouro_smith.md)

Run the selected cases on the baseline. If the declaration law already
passes, find the failing boundary or revise the hypothesis. Once a case
reproduces the violation, fix the layer that drops the declaration or skips
the check. Rerun both the invalid and valid cases, then the relevant checker,
import, and boundary checks.

The compiler-checking suite and the kernel profile both apply to this
change. Run them in the order shown from the repository root in a
POSIX-compatible shell. Have the toolchain ready or satisfy its build
prerequisites. Both commands may build tools and write reports under
`_build/`. Check each command's exit status, the cases it ran, and its
reports.
[Build requirements](getting_started.md#requirements) ·
[Compiler checking validation](ci.md#validation-matrix)

```sh
sh scripts/test_suite.sh --compiler-checking
python3 scripts/ci_gate.py --profile kernel --out _build/ci/kernel
```

## Report the result

Report a task as complete only when the required baseline evidence has been
recorded, the final revision meets the applicable contracts, mandatory
checks pass, and the diff stays within scope. If a mandatory check is
unavailable, report the task as partial or blocked and identify the missing
condition. Explain why any planned or policy-listed check is inapplicable.
Use baseline evidence to identify a pre-existing unrelated failure.

Cover these fields in the task report. A small task can use a short entry
for each applicable field. The repository automation policy defines the
report labels.
[Validation and reporting](../AGENTS.md#validation-and-reporting)

1. Goal and status — complete, partial, or blocked.
2. Contracts — requirement and contract IDs, sources, artifacts, and baseline results.
3. Changed — affected behavior, documentation, tests, and generated artifacts.
4. Ran — exact commands, relevant environment, and evidence locations.
5. Results — observed outcomes, including failures and their established causes.
6. Not run — unavailable checks, reasons, and the contracts left unverified.
7. Deviations — assumptions, departures from recommendations, and approved changes with reasons.
8. Risk — remaining compatibility, trust, runtime, or performance risks.

## Enforce critical contracts

Use an executable check at the affected boundary for each critical property
that can be automated. Specify who runs the check, what a failure blocks,
and who can change the check or its required status. Keep scoped manual
evidence for properties that require human verification.

Prefer independent review, mandatory gates, and permission boundaries where
available to protect acceptance checks, fixtures, trust allowlists,
baseline and hash updates, and promotions. Verify which controls are
enforced before relying on them. Changes to enforcement require their own
authorization.
