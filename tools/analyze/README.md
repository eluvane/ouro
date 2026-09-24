# tools/analyze

This directory contains project-owned analyzer cores written in Ouro. The analyzer sources are outside the logical kernel TCB; they may reject bad project code or guide cleanup, but they cannot change kernel checking rules.

Packaged `ouro1 analyze` is two native Ouro IO programs:

- `tools/analyze/main.ouro` (`_build/c/ouro-analyze`), the base runner: it extracts repository facts (files, imports, declarations, references, exports, constructors, branches, suppressions) and feeds them to the five policy cores `architecture.ouro`, `deadcode.ouro`, `suppressions.ouro`, `api_surface.ouro`, and `trust.ouro` through the adapters in `tools/analyze/policy.ouro`. The strict format subset is the only text pass left in `tools/analyze/families.ouro`.
- `tools/analyze/drive_main.ouro` (`_build/c/ouro-analyze-drive`), the structured drive: it parses each source with the real compiler frontend and runs the nineteen structured families listed below. The frontend and shared `Ast` cone are linked only into the drive, so editing a core rebuilds the drive and not `ouro-analyze`.

```sh
sh scripts/ouro1.sh analyze --strict --enable-strict
sh scripts/ouro1.sh analyze --strict --enable-cfg --scope tools/analyze/cfg.ouro
sh scripts/ouro1.sh analyze --strict --include-fixtures --enable-taint --scope tests/analyze/taint_bad
```

`scripts/ouro1.sh analyze` runs the base runner on every call and the drive only when a structured flag is present. `ANALYZE_OK` is printed only when both binaries are clean; any `OURO-*` line or rejected source makes the command exit `1`.

## Bounded execution

Both binaries run through `scripts/analyze_bounded.py`, one low-priority native process per file, because the extracted runtime keeps a process-lifetime arena. Scope, batch, and keep policy live in `bounded_text.ouro` (`bounded_run`) and are typechecked by the precision suite; the process supervisor is still the Python runner. Limits on a local host:

- global base-runner modes (`--enable-deadcode`, `--enable-trust`, `--dump-facts`, `--enable-heavy`, `--enable-all`, `--architecture-only`) need a scope of at most 8 files and 64 KiB in total;
- the drive rejects a single source larger than 40 KiB before starting; the limit covers every production source, and the memory suite selects the largest current source for the budget row `analyzer-drive-largest-file` in `quality/memory_budgets.json`;
- `OURO_ANALYZE_ALLOW_UNBOUNDED=1` lifts both guards and is meant for a dedicated high-memory host only.

The wrapper requires the repository Python runner and fails closed without it unless the same override is explicit. Dump the base runner's fact table with `sh scripts/ouro1.sh analyze --dump-facts --scope PATH`.

Both native runners use `tools/quality/source.ouro` for checked source discovery
and reads. The base runner preserves repeated `--scope` and `--scope=PATH`
values, deduplicates canonical path aliases, rejects an empty final selection,
and prunes build, cache, Git, and
dependency directories. Explicit source files beneath those directories remain
selectable. Fixture opt-in and the default `std`, `compiler`, `tools/analyze`,
and `samples` scopes remain unchanged. These native checks do not replace the
Python wrapper's inventory, skeleton, or budget responsibilities. See
[quality input boundaries](../../docs/quality.md#native-input-boundary-and-host-adapter-retirement)
for Unicode path checks and the Windows C-host UTF-8 process manifest.

## Structured drive

`unit.ouro` builds one `AnalysisUnit` per source with the compiler frontend (`preprocess_records` → `lex_all` → `parse_file`, then `expr_adapt.ouro` per definition). The unit carries definition names and lines, constructor/owner pairs plus the constructors of indexed families and the uninhabited inductives (`UnitTypes`), interned capability ids, layer marks, and the comment annotations parsed by `runtime_contracts.ouro`. Cores never see raw tokens.

`std/process.ouro` belongs to the stdlib IO layer: it owns the checked process
wrappers over the runtime intrinsics. This exact path classification leaves
other stdlib modules subject to the pure-layer capability and effect checks.

The exact entry points `tools/analyze/main.ouro` and
`tools/analyze/drive_main.ouro` use the host-tool layer for filesystem and process
IO. Other files under `tools/analyze/` keep the pure analyzer layer; a matching
basename in another directory does not grant host capabilities.

Every core returns issues that `drive.ouro` turns into `Finding` values (`finding.ouro`: code, definition line and name, witness). `drive_main.ouro` prints them in the base runner's format, sorted by file/line/column/code and deduplicated, followed by one banner:

```text
ANALYZE_DRIVE files=N findings=N rejected=N families=effects,capability
```

`rejected` counts sources the frontend could not build a unit for; each one is reported on stderr as `PATH: structured analyzer could not build the unit: WHY` and is never counted as clean. The drive exits `1` on any finding or rejection.

`--print-families` prints `ANALYZE_FAMILIES families=...` for the selected flags
without reading sources. It is profile metadata, not an analysis completion
report. The bounded runner queries this native owner once per sweep, then
requires one processed file per worker and matching family lists, diagnostic
counts, source locations and exit codes. A malformed or incomplete report fails
the run, including in the advisory production sweep.

### Flags and family sets

One flag per family: `--enable-effects`, `--enable-capability`, `--enable-extract`, `--enable-match`, `--enable-cfg`, `--enable-dataflow`, `--enable-semantic`, `--enable-property`, `--enable-absint`, `--enable-symexec`, `--enable-taint`, `--enable-contracts`, `--enable-metrics` (complexity, bounds, minimal), `--enable-duplication`, `--enable-trust`, `--enable-simplify`, `--enable-perf`, `--enable-naming`, `--enable-errors`. The unions are:

| Flag | Families |
| --- | --- |
| `--enable-light` | effects, match, cfg, dataflow, semantic, property, metrics, simplify, perf, naming, errors |
| `--enable-heavy` | capability, extract, taint, contracts, absint, symexec, duplication, trust |
| `--enable-strict` | the promoted set below |
| `--enable-all` | every family |

`--enable-trust`, `--enable-heavy`, and `--enable-all` also switch on the base runner's import-graph trust pass (`OURO-TRUST001`) over the same scope, and `--enable-all` its dead-code pass, which is why those flags are bounded like the other global modes.

## Strict quality-gate status

`analyze --strict` runs the base policy cores over the production source
scope. Architecture, suppressions, and the strict format subset are blocking;
API surface uses the explicit baseline `quality/api_surface.tsv`. Dead code
remains an opt-in bounded pass because host-wired helpers may appear unreachable.
The structured families are selected with `--enable-strict` and checked by the
nightly production sweep. Intentionally bad fixtures require
`--include-fixtures` and an explicit scope.

The nightly sweep reads `quality/analyze_production.json`, rejects unlisted
frontend failures and stale allowances, and counts the all-family sweep for
triage. Default `analyze --strict` stays on the smaller base runner because
the structured drive needs a larger memory budget. [CI](../../docs/ci.md#local-profiles)
owns the current gate schedule and result.

A clean base run prints `ANALYZE_OK` with coverage counts. Any finding, rejected
source, missing worker result, or inconsistent count fails the bounded runner.

## Analyzer families

| Source | Entry | Diagnostics | Input |
| --- | --- | --- | --- |
| `ast.ouro` | `ast_children`, `ast_any`, `ast_exists`, `ast_arms`, `ast_core_body` | shared surface `Ast` | One 22-constructor inductive shared by every structured core, with the spine, binder, arm (`AstArm`), scrutinee, and declared-type helpers they need. |
| `expr_adapt.ouro` | `adapt` | Expr → Ast | Total adapter from `compiler/ast.ouro`; the drive runs it per definition. |
| `string_prims.ouro` | string host primitives | shared by analyzer cores | `String` and `prim_string_*` without `std/runtime.ouro`'s Windows platform cone. |
| `unit.ouro` | `unit_of_source` | `AnalysisUnit` | Frontend pipeline into defs with name/line, `UnitTypes`, `CapIds`, layer marks. |
| `finding.ouro` | `show_finding`, `rule_of_code`, `sort_findings`, `dedupe_findings` | `Finding` | Structured diagnostic plus the code → family/rule/message/hint table. |
| `drive_env.ouro` | `DriveEnv`, `DefInfo`, `finding_at`, `fam_on` | shared by the drive modules | Family names, the per-unit environment, the per-definition record, and the finding constructor the wiring modules share. |
| `drive_smells.ouro` | `simplify_findings`, `perf_findings`, `naming_findings`, `errors_findings`, `ctor_name_findings` | simplify, perf, naming, errors | Resolves the names those cores key on and maps their issues to codes. |
| `drive.ouro` | `drive_findings`, `all_families` | structured families | Runs the enabled families over one unit and maps issues to codes. Light/heavy cores are wired through `drive_light.ouro` and `drive_heavy.ouro` so no single selected file keep-imports every family implementation. |
| `effects.ouro` | `analyze_effects` | `OURO-EFF001`–`006` | Pure holes, constant rebinding, unhandled `perform`, handle missing an op, discarded continuation, effect under `@pure`. |
| `capability.ouro` | `analyze_capability` | `OURO-CAP001`–`004` | Call-site policy for `prim_fs_*` (including rename), process capture, HTTP request, their retained legacy raw names, and host-fast Peano bodies. |
| `extract_leak.ouro` | `analyze_extract_leak` | `OURO-XTR001`–`003` | Type-as-value, proof/Sort in IO, kernel names from std. |
| `match_cover.ouro` | `analyze_match_ast` | `OURO-MATCH001`–`002` | Partial match and dead branch using the unit's constructor signatures; refined arms (`MkBox n On`) are not dead. |
| `cfg.ouro` | `analyze_cfg` | `OURO-CFG001`–`004` | Empty match, trivial single arm, recursion without a matched parameter, repeated arm constructor; dependent eliminations and uninhabited scrutinees are exempt. |
| `dataflow.ouro` | `analyze_dataflow` | `OURO-DF001`–`004` | Unused parameter (declared type counts as a read), dead `let`, alias `let`, hole in value position. |
| `semantic.ouro` | `analyze_semantic` | `OURO-SEM001`–`005` | Magic numbers, complex scrutinee, lambda nesting, one-arm Bool match, odd identity (discard parameters excluded). |
| `property.ouro` | `analyze_property` | `OURO-PROP001`–`004` | `@property no-holes`, `exhaustive`, `terminates` claims. |
| `absint.ouro` | `analyze_absint` | `OURO-ABS001`–`003` | Constant-zero divisor, arm that cannot fire, body definitely zero, on a sign/zero domain. |
| `symexec.ouro` | `analyze_symexec` | `OURO-SYM001`–`003` | Path conditions over nested matches: contradiction, unsatisfiable arm, self-call with every argument unchanged. |
| `taint.ouro` | `analyze_taint` | `OURO-TAINT001`–`003` | Sources and sinks from `-- ouro-analyze:source=`/`sink=` comments plus the fixed prim list; tainted or hole value into a sink, secret in a public definition. |
| `contracts.ouro` / `runtime_contracts.ouro` | `analyze_contracts`, `ctr_parse_anno` | `OURO-CTR001`–`008` | `@requires`/`@ensures`/`@modifies`/`@pure` and the other comment tags: orphan, empty, duplicate, unknown, missing on public, `@pure` that performs. |
| `complexity.ouro` / `bounds.ouro` / `minimal.ouro` | `complexity_metrics`, `bounds_metrics`, `minimal_issues` | `OURO-CX001`–`002`, `OURO-BND001`, `OURO-MIN001` | Cyclomatic and cognitive limits, `@bound(metric <= n)` claims, `@minimal` scoring. |
| `duplication.ouro` | `analyze_duplication`, `alpha_eq`, `near_eq` | `OURO-DUP001`–`002` | Structural clone detection over all definitions of a unit with binder alpha-renaming and global-id preservation. |
| `simplify.ouro` | `analyze_simplify` | `OURO-SIMP001`–`007` | Rewrite smells with the replacement in the finding: Bool match that returns or negates its scrutinee, arms sharing one body, eta-expanded lambda, `notb (notb e)`, `andb`/`orb` with a constant operand, arms that rebuild their own constructor. The definition of `notb` and lambdas that forward to the enclosing fix are exempt. |
| `perf.ouro` | `analyze_perf` | `OURO-PERF001`–`005` | Cost smells of the extracted runtime: literal at or above `perf_literal_threshold` inside a fix body, `append`/`snoc`/`concat` on an accumulator parameter fed back into the recursion, `length` compared with 0/1 or scrutinised without reading the count, the same conversion of the same parameter twice on one path, `andb`/`orb` operand that nests control flow or a recursive call. |
| `naming.ouro` | `analyze_naming`, `nm_ctor_misspelt` | `OURO-NAME001`–`004` | Conventions the other cores depend on: a `_`-spelt binder that is read (shadowing-aware), one-character definition names, a capital initial on a value definition (type-level results are exempt), and lowercase or underscore constructors, anchored at the owning `inductive` line. |
| `errors.ouro` | `analyze_errors` | `OURO-ERR001`–`003` | Declared `Either String` result (also under `IO`), a failure arm (`Left`, `Fail`) that drops its payload and returns the paired success constructor through lets, `do`, or `io_pure`, and `io_bind` over an `Either` whose result is bound to a discard. |
| `format.ouro` | `analyze`, `format` | `OURO-FMT*` | Local text formatter/checker shared with `tools/fmt.ouro`. |
| `policy_ids.ouro`, `host.ouro` | layer predicates, exit codes | — | Layer policy shared by the cores; profile and exit-code names for the base runner. |

## Themes shared with Clippy

`OURO-SIMP003`, `OURO-PERF004`, `OURO-ERR002`, `OURO-ERR003`, `OURO-DUP001`,
and `OURO-DUP002` stay in this analyzer. The matching Clippy proofs
(`OURO-CLIPPY-REDUNDANT-004`, `OURO-CLIPPY-PERF-001`, `OURO-CLIPPY-ERROR-003`,
`OURO-CLIPPY-CHECKED-006`, `OURO-CLIPPY-MAINT-007`) require registered
contracts, closed enums, or token identity, and they leave the syntactic
cases above to these warnings. The two IDs use different suppression syntax.
See [Quality](../../docs/quality.md).

## Diagnostic contract

Every diagnostic emitted by either binary has:

- stable `OURO-*` code;
- severity;
- analyzer name;
- rule id;
- file/line/column span;
- short message;
- actionable hint;
- witness/proof data;
- deterministic ordering by file, line, column, code.

Example:

```text
path/to/file.ouro:3:8: error[OURO-ARCH002] architecture/forbidden-dependency-direction: import points from an inner layer to an outer layer
  hint: Move the dependency behind an allowed lower-layer interface or add a versioned architecture-policy exception.
  witness: edge path/to/file.ouro(layer=0) -> path/to/outer.ouro(layer=3)
```

## Current policy diagnostic families

### Architecture

- `OURO-ARCH001`: cycle in the module/import graph.
- `OURO-ARCH002`: forbidden dependency direction, using the convention that lower layer numbers are more trusted/inner.
- `OURO-ARCH003`: std/runtime code imports compiler-internal source.
- `OURO-ARCH004`: wider layer-boundary escape.
- `OURO-ARCH005`: non-TCB source crosses into trusted/kernel source without explicit policy allowance.

The native extractor classifies production source by explicit versioned policy: `std/` is lower shared/runtime layer, `compiler/` is compiler-internal, `compiler/kernel.ouro` is trusted, `tools/analyze/` is analyzer policy, and samples are outer users. Fixtures may override this with `-- ouro-analyze:layer=N trusted=true compiler-internal=true std-runtime=true` policy comments.

### Dead code

- `OURO-DEAD001`: unreachable definition.
- `OURO-DEAD002`: unreachable export.
- `OURO-DEAD003`: unreachable constructor.
- `OURO-DEAD004`: unreachable module.
- `OURO-DEAD005`: unreachable branch.

The pure core and native opt-in runner root reachability from real entry facts plus explicit public/API roots. Public API is not dead only because it lacks an internal repository caller. Branch diagnostics remain non-strict until typed control-flow facts prove unreachability.

### Duplication

- `OURO-DUP001`: exact structural clone modulo alpha-renamed binders.
- `OURO-DUP002`: near structural clone where only literal/hole leaves drift.

Bound variables are compared by binding depth; unbound/global `AVar` ids must match, so two unrelated globals with the same tree shape do not become duplicates just because the source text looks similar. The drive compares every pair of definitions in one unit.

### API surface

- `OURO-API001`: unexpected new export.
- `OURO-API002`: duplicate public API.
- `OURO-API003`: API/ABI signature hash changed relative to baseline.
- `OURO-API004`: public definition appears internal-only.
- `OURO-API005`: unnecessary public surface growth.

The explicit production baseline is `quality/api_surface.tsv`. It is reproducible: each row is `path<TAB>name<TAB>fnv1a64(normalized_signature)`. The native runner uses it by default for `std/` public definitions.

### Trust

- `OURO-TRUST001`: untrusted definition influences kernel/checking/proof path.
- `OURO-TRUST002`: effect crosses a trust boundary without policy allowance.
- `OURO-TRUST003`: untrusted component reaches a trusted runtime primitive.
- `OURO-TRUST004`: tainted value reaches proof/trusted path.
- `OURO-TRUST005`: component violates declared TCB policy.

`trust.ouro` consumes the effect and taint facts of the drive unit and the import facts of the base runner. It intentionally does not reimplement taint propagation.

### Suppressions

- `OURO-SUP001`: broad/all-rules suppression.
- `OURO-SUP002`: missing reason.
- `OURO-SUP003`: unknown lint id.
- `OURO-SUP004`: unused suppression.
- `OURO-SUP005`: forbidden suppression for this rule.
- `OURO-SUP006`: suppression scope is wider than the configured maximum.

The native parser recognizes source suppressions in comments of the form `-- ouro-lint:disable=OURO-CODE reason=...`. The directive must begin the line comment after `--` and optional whitespace; later mentions in explanatory prose are not suppressions. Valid suppressions are narrow next-line suppressions only. `OURO-TRUST*` and `OURO-ARCH005` are forbidden to suppress in source.

## Fixture contract

`tests/analyze/` holds one directory per family with `bad` sources (one per code) and `good` sources that guard against false positives, each parsed by the real frontend. `tests/analyze/golden/` holds the expected output of every scope (`cfg_bad.txt`, `cfg_good.txt`, ...), and `tests/analyze/manifest.json` lists every scope with its codes and golden. `sh scripts/analyze_precision_suite.sh` typechecks every core, runs every scope, and compares the output with its golden line by line; `--regen` rewrites the goldens after a reviewed behavior change. `quality/diagnostics.json` points each structured code at its fixture, and `scripts/strict_quality_firewall.py` checks that those files exist.

The production tree is an expectation, not a golden: `project_no_fp` requires `ANALYZE_OK` from `sh scripts/ouro1.sh analyze --strict`, and the nightly production suite requires zero findings from `--enable-strict`.

## Removed surfaces

The former `--enable-lint` flag is retired; use `ouro1 lint` for source lint.
The old PCC certificate surface has no active generator. The current structured
families parse compiler `Ast` through `unit.ouro`; they do not use the retired
text-token walker. `OURO-NAME002` is retired because a one-character name alone
is not evidence of a defect.

## Useful validation commands

[CI](../../docs/ci.md#local-profiles) owns analyzer precision, production,
resource-budget, and strict policy validation commands.
