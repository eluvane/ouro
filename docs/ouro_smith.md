# OuroSmith

OuroSmith generates reproducible programs and typed Core, checks construction
laws and independent surface/runtime expectations, and saves minimized failures
for replay. Core generation and checking run as Ouro programs through the
canonical compiler checker; Python supervises processes and verifies reports.
Run it from the repository root with the installed Python interpreter:

```sh
python3 scripts/ouro_smith.py --self-test
python3 scripts/ouro_smith.py --profile pr --out _build/smith/pr
python3 scripts/ouro_smith.py --profile kernel --out _build/smith/kernel
python3 scripts/ouro_smith.py --profile nightly --out _build/smith/nightly
python3 scripts/ouro_smith.py --faults --profile pr --out _build/smith/faults
python3 scripts/ouro_smith.py --list
```

The full profiles currently require a C compiler and POSIX shell. `OURO_SH`
selects an installed shell. On Windows, use a native Python interpreter;
generated programs and tools run as native executables. No profile invokes
OCaml, opam, Dune, or a Python Core interpreter. Missing tools, exhausted
resources, incomplete protocols, and stale build receipts prevent a passing
report.

## Profiles and expectations

`quality/smith/seeds.json` defines the seed ranges and generation budgets.
The PR profile uses 40 seeds; kernel uses 100; nightly uses 400 with deeper
terms. `--seed N` chooses the start of the range, `--seeds N` changes its size,
and `--seed-list 1,7,23` selects specific cases. A custom seed selection is a
focused run; it does not establish full-profile strategy coverage.

| Layer | Expectations |
| --- | --- |
| Core | Ouro typed generation, explicit expected terms, scope/substitution/reduction laws, and canonical checking; mutations require specific typed rejection classes. |
| Surface | Typed expressions and a Python evaluator; known invalid programs require registered diagnostic codes or lint prefixes. |
| Formatter | Python layout for the generated subset, idempotence, check-mode status, and unchanged emitted core after formatting or comments. |
| Runtime | Native C output compared with the Python evaluator, plus generated test-runner pass/fail counts and golden mismatch checks. |
| Imports and caches | Dependency order, alias equivalence, cold/warm/disabled cache results, dependency invalidation, and worker-count agreement. |
| Doc and LSP | Generated declaration signatures and comments, known definition positions, hover text, and protocol responses. |
| Library and IO | Python string, path, collection, JSON, CSV, hash, filesystem, and process contracts; native output and file bytes must match. |
| Analyzer traversal | Independent node counts for all analyzer AST constructors, adapter shapes, deep paths, binder shadowing, and byte-preserving line splitting. |

Kernel profiles keep their randomly generated definitions and add an explicit
nested-recursion witness. String signatures also exercise concatenation with
distinct, nonempty operands, independently of random term selection.

The source inventory is extracted from constructor tables, tokens, diagnostics,
and canonical checker error classes. Constructor extraction ignores comments and
string literals, including embedded declaration delimiters.
`quality/smith/strategies.json` maps these items to
generators, negative cases, properties, or explicit exceptions. A full-profile
run checks both the registry and executed coverage. Regenerate the registry
after implementing a strategy:

```sh
python3 scripts/ouro_smith.py inventory --write
```

`quality/smith/diagnostic_contract.json` records the exact accepted diagnostic
classes. A crash, timeout, or unrelated rejection does not satisfy a negative
case. Exceptions remain visible in the inventory; they are not executed
properties.

Surface transformations compare the compiler's complete
[`CheckedProgram` snapshot](tooling.md#check-and-evaluate): declared types,
bodies, inductives, intrinsic and extern bindings, representation roles, and
emission order. The Ouro serializer resolves global IDs to names and preserves
de Bruijn binder identity, so local alpha-renaming remains comparable. The host
compares all emitted bytes after checking framing. Snapshot equality establishes
transformation consistency; compiler acceptance, typed Core laws, and independent
runtime expectations are checked separately. There is no second Core decoder or
normalizer in the Python harness.
Analyzer families and general autofix semantics also require separate gates;
the fixer property covers its generated rewrite, checking, linting, runtime
result, and idempotence. Separate parameterized text contracts preserve the
formatter and fixer rules previously recorded in goldens, including incomplete
editor inputs. These text contracts assert exact output and check-mode status;
they do not assert that incomplete input typechecks. Documentation compares a
complete generated page against known signatures and prose associations.
Lint contracts retain positive protection for imported constructors, refined
pattern slots, multi-match rows, and handler scopes. Refined-pattern lint
checks do not claim runtime support beyond the maintained pattern language.
Protocol generation bounds numeric values independently of the seed magnitude.

## Findings and replay

Reports and generated inputs stay under `_build/smith/`. A finding records
the seed, profile, generator hash, input, failed property, expected and actual
results, and failure classification. Supported classifications distinguish
wrong acceptance, wrong rejection, diagnostic disagreement, divergence,
crash, timeout, memory exhaustion, and unavailable oracles.

Replay the saved input directly, including a minimized input:

```sh
python3 scripts/ouro_smith.py --replay --finding _build/smith/pr/findings/ID.json
python3 scripts/ouro_smith.py replay --layer surface --seed 17 --case surface-17
python3 scripts/ouro_smith.py replay --layer kernel --seed 17 --case core-17
```

Seed replay uses the current generator. Saved surface inputs preserve their
source and dependencies. Saved Core cases contain an exact native seed recipe:
profile, seed, depth, definition bound, and generator hash. A changed generator
hash rejects replay; recover the matching generator sources or port the case to
an explicit typed Ouro regression. Shrinking must retain the exact failed law
and diagnostic class. Promote a reviewed finding with a unique descriptive name:

```sh
python3 scripts/ouro_smith.py --update-corpus _build/smith/pr/findings/ID.json --name regression_name
python3 scripts/ouro_smith.py corpus --check
python3 scripts/ouro_smith.py corpus --only regression_name
```

Typed retained Core laws live in `tests/compiler_retained_tests.ouro`; saved
native recipes live under `quality/smith/corpus/native/`. The former JSON cases
under `quality/smith/corpus/kernel/` are archived migration data. Every Core
profile executes all 55 retained laws; `corpus --only` still executes that full
typed runner and reports the actual count. Optional saved recipes add their
own complete law runs. Promotion refuses to overwrite an existing case.
Surface regressions remain in `quality/smith/regressions/` and run automatically.

The report fingerprint excludes timing measurements. Compare two full runs
with the same configuration and source state to check determinism. Skips,
empty runs, abstentions, and blocking completeness gaps cannot produce PASS.

## Process limits and fault injection

Each native command has a timeout, scrubbed environment, and private working
directory. Windows uses a Job Object to cap committed memory and terminate
descendants; POSIX uses inherited address-space limits and a process session.
Darwin does not enforce a finite `RLIMIT_AS`; the launcher leaves that limit
inherited there. The POSIX child launcher permits a recursive native stack up
to 128 MiB, matching the native PE reserve, within the address-space and
inherited hard stack limits.
These resource controls are not filesystem access controls. The generated
programs and recipes are repository-owned code.

Compiler preparation, including the complete strict check and build of native
law drivers, uses the same 3072 MiB limit as tool preparation. Generated program
execution retains the configured `--memory-mb` limit; preparation failures
remain fatal.

Build parallelism follows `OURO_JOBS` (default 10), capped by the runner's
available CPUs so independent deadlines do not depend on oversubscription.
Import/cache properties
also compare single-worker results with the configured worker count.
Surface expression samples and independent tool recipes use the same worker
count in separate pools. Each worker owns its files and report; results merge
in seed or recipe order. Recipes that invoke wrappers with shared build
outputs run serially after the independent recipes.
The analyzer line scanner also runs serially so its large dependency graph
does not compete with other compilation tasks. Its typecheck and compilation
phases, and those of the stdlib and IO integration recipes, use the same
900-second preparation deadline as native law drivers for their complete
dependency graphs. Small generated checker cases still use `--timeout`.
Generated programs retain the ordinary runtime deadline. Command logs record
each phase's deadline, duration, and peak memory.

The harness self-test exercises actual memory exhaustion and descendant
termination, protocol validation, saved-input replay, and failure reporting.
Checker fault injection patches temporary copies of the canonical Ouro
checker and builds the designated detector with exact input receipts. Each
mutant requires a clean unmodified baseline and the named semantic failure.
Stale source patches, unbuildable mutants, unrelated crashes, and survivors
fail the fault run. Retired OCaml facade and memo mechanisms receive no
semantic migration credit.

Surface fault injection rebuilds copies of the frontend, formatter, linter,
fixer, documentation generator, LSP, and test runner. It also changes copied eval-wrapper, runtime-printer
and module-cache sources, and compiles generated AST observations against a
copied analyzer module. Each has a clean baseline and a named property that
must detect that fault; an unrelated crash does not count as its detection.

The parity recipe compares generated inputs through the direct compiler,
host wrapper, native runtime, and `eval`, using Python results and exact
rejection contracts. A recorded stage fixpoint must match the exercised
binary hash. Nightly requires that fixpoint; PR reports its absence explicitly.
Saved parity and IO inputs include their source, dependencies, expected
results, process helper, arguments, environment value, and stdin as applicable.

Native suite wrappers materialize specifications into fresh directories:

```sh
python3 scripts/ouro_smith.py prepare --group fmt --out _build/smith/inputs
python3 scripts/ouro_smith.py manifest --prefix=ERGO.,REC.,IMP.
```

`prepare` supports formatter, fixer, documentation, lint, manifest, runtime,
user-test, LSP, and security inputs. Its output is the created directory;
native selftests take it through `--fixtures` (lint uses `--bad-root` and
`--good-root`). Expected text and runtime output come from Python contracts.
Manifest checks require `CHECK_OK` on acceptance and exit 1 on rejection;
crash exit codes cannot satisfy a negative row.

## Migration from the manual corpus

The legacy `test/` tree has been retired. The checked-in migration matrix
preserves the approval snapshot from before retirement, including the original
Git revision and file hashes. Run a fresh audit when generators, strategies,
or consumers change:

```sh
python3 scripts/ouro_smith.py validate --out _build/smith/validation
python3 scripts/ouro_smith.py migration --report _build/smith/validation/pr/report.json --validation _build/smith/validation --write
```

`quality/smith/migration_matrix.json` records covered categories and gaps.
Removing the old corpus requires complete category mappings, preserved unique
contracts, independent oracles, fault evidence for each critical layer,
deterministic PR runs, a complete nightly run, updated consumers, recovery
evidence, and passing aggregate gates. The migration command reports missing
evidence and does not delete files. `validate` records every required command,
its exit status and log, source and binary hashes, repeated PR fingerprints,
and the complete fault catalogue. A changed tree invalidates that evidence.
The matrix retains the original Git revision and tree, file hashes, and category
mappings. After retirement, the audit reconstructs these from local Git objects
before checking fresh validation results. Missing history, altered categories,
or incomplete archive data block the audit.
A failed audit writes its report under `--out` and preserves the verified
retirement archive.
The full PR run executes after CI's tool rebuilds and can supply the first deterministic report
when its source and binary hashes still match. The validation journal records
the actual CI command and hashes of its log and report. Missing or stale
evidence triggers a fresh PR run; the second PR run always executes separately.
See [CI](ci.md) for the existing aggregate
and [compiler checking](kernel_design.md) for the acceptance boundary.
