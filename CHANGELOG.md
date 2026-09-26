# Changelog

Development changes; see the [compatibility policy](docs/stability.md).

## [Unreleased]

### Added

- Pure bounded pull iterators with lazy map/filter/take adapters and explicit
  typed failure or pull-limit results when collecting a list.
- Overlapping list windows, state scans, state-threading maps, stable grouping
  by key, and first-failure `Either`/`Maybe` folds in `std/collections.ouro`.
- Lazy error-aware fallback for `Either` and ordered `Maybe` list traversal in
  the practical standard library.
- Leading `{A : Type}` inductive parameters opt constructors in to bounded
  inference from a direct expected family or direct value-field type hints on
  saturated calls; explicit calls remain valid. See
  [Marked constructor parameters](docs/language/ergonomic-syntax.md#marked-constructor-parameters).
- Leading `{A : Type}` definition parameters opt calls in to bounded value
  and expected type inference, including nondependent callback and collection
  type shapes. Explicit full and partial calls remain valid. See
  [Marked definition parameters](docs/language/ergonomic-syntax.md#marked-definition-parameters).
- Typed `let?` blocks propagate `Either`- or `Maybe`-shaped failures through
  explicit constructor roles and lower to checked cases; see
  [Ergonomic syntax](docs/language/ergonomic-syntax.md#typed-fallible-blocks).
- Pure `let { ... }` expression blocks accept sequential local bindings and a
  mandatory final expression; see [Ergonomic syntax](docs/language/ergonomic-syntax.md#pure-expression-blocks).
- Nonempty list literals can infer an element type from their first element
  without an expected `List A` context; empty and ambiguous literals still
  require an annotation.
- Typed local helpers may omit the result annotation when their body type is
  inferable; see [Ergonomic syntax](docs/language/ergonomic-syntax.md#typed-local-helper-declarations).
- [Raw `String` literals and quoted imports](docs/syntax.md#numbers-and-strings)
  with `r#"..."#`, preserving backslashes and physical line breaks.
- [Braced Unicode scalar escapes in strings and quoted imports](docs/syntax.md#numbers-and-strings),
  decoded to UTF-8 bytes with malformed scalar rejection.
- [Decimal digit separators and hexadecimal/binary `Nat` literals](docs/syntax.md#numbers-and-strings)
  with strict malformed-token rejection and no implicit machine-integer conversion.
- Expression-scoped `open A in body` now selects `A`'s direct declarations in
  ambiguous import graphs. Nested opens use the innermost selection, while
  local binders and current-file declarations retain priority.
- Compiler-owned identities for declarations in aliased source modules.
  `A.member` selects a direct declaration of `A`'s canonical imported file;
  colliding short names require qualification. See [module syntax](docs/syntax.md#modules-and-imports).
- Review-only Clippy proofs for Result/Maybe error flow, collection and string
  composition, List producer/consumer laws, arithmetic, literal bounds, Boolean
  identities, and normalization. Rule contracts and exclusions live in the
  [Clippy reference](docs/clippy_grade_firewall.md).
- [Grouped imports, positional call groups, and typed local helpers](docs/language/ergonomic-syntax.md),
  including the migration from `f (a, b)` as one grouped expression to two arguments.
- Trailing commas in nonempty list literals, including multiline lists with comments.
- Record literal field punning with known nominal type and checked field coverage.
- Functional updates of annotated nominal records, including nested field paths, checked changed fields, once-bound base expressions, and typed local/record-field context.
- Local and pinned-Git package dependencies with deterministic manifests and
  locks, rejection fixtures, a reusable-library sample, and a consuming
  application; see [Packages](docs/pkg.md).
- A shared native diagnostic transport for lint, analyzer, and fix reports.
  Existing text layouts and rule ownership are retained; forbid/fatal findings
  and malformed severities cannot disappear as suppressed success.

### Changed

- Expected function domains now guide nested callbacks and parameterized
  matches inside short lambdas when the domain is unambiguous and complete.
- Qualified record literals and projections retain the aliased record owner;
  a projection through a transitive record type is rejected instead of
  selecting a same-named local value or accessor. Bare record sugar preserves
  its declaring record's constructor or accessor when an explicit call or
  local binder uses the same short name. Qualified module references likewise
  keep their global target under a same-named local binder.
- A qualified reference no longer borrows a same-named declaration from a
  different imported file. Add a direct import and use that file's alias.
  In an aliased import graph, a bare use made ambiguous by a new import now
  reports error 96; qualify it. Plain-only import graphs retain error 45 for
  duplicate declarations.
- Alias collisions involving `IO`, `io_bind`, or `pure` report error 96 until
  their lowering uses module-local operation metadata. `std/module_demo.ouro`
  imports its declaration owner directly.
- Run PR parity and syntax-quality gates in separate required jobs to shorten
  the serial `checks` group; nightly retains both gates in its `checks` group.
- Split compiler-checking fixtures across sixteen PR and nightly jobs, with
  `source_spans` isolated in one job and complete source-bound suite coverage;
  see [CI](docs/ci.md#local-profiles).
- Build release toolchains from a [checked compact source copy](docs/canonical_source.md#materialization),
  retaining original-source checks and full generated C equality.
- Publish automatic snapshots every three days instead of weekly, using
  `snapshot-YYYYMMDD` tags and the `snapshot` dispatch input; see
  [Releasing](docs/releasing.md#github-release).
- Read every grouped import in lint, strict quality, and analyzer dependency
  inventories; reject malformed import scans. Refresh the pinned bootstrap
  parser for [ergonomic syntax](docs/language/ergonomic-syntax.md) and adopt
  shorter spelling across maintained Ouro sources.
- Adopt [Mother of Licenses 1.0](LICENSE) for revisions covered by the
  [licensing notice](README.md#license).
- Unify the source linter under `ouro1 lint`, with separate language, style,
  and semantic workers. [Quality](docs/quality.md) owns profiles, process
  boundaries, inventory selection, and memory limits.
- Give repeated IO executions distinct Clippy identities and checked-result
  obligations while preserving aliases returned by `io_pure`.
- Preserve transparent `ESpan` wrappers during structural and semantic traversal.
- Share source harvest facts through a content-addressed cache, retain compact
  imported signatures/origins, and isolate compiler/platform implementation
  cones. [Build](docs/build.md#memory-behavior) describes allocation boundaries.
- Validate source-bound compiler and companion receipts before native-tool reuse;
  select generated `.exe` workers on Windows and preserve UTF-8 arguments.
- Stage formatter and fixer writes through the source replacement/recovery API.
  The [formatter and fixer reference](docs/tooling.md#formatter) defines their
  candidate-checking and platform limits.
- Assemble `str_join` and `str_repeat` into output-sized buffers; avoid repeated
  byte-list copies in `str_head`, `str_cons`, and `str_snoc`.
- Run the two compiler property domains in isolated sequential workers, retain
  complete counters, and reject incomplete reports. Build retained compiler laws
  with `O1` in every cache mode and record it in source-bound receipts.
- Name repository-gate profiles `docs-native`, `project-native`, and
  `workflow-native`, preserving their short aliases; see [CI](docs/ci.md).
- Use the repository `.shellcheckrc` for host ShellCheck.
- Document [rolling parallel development](docs/agent_parallel.md) with exact file
  reservations and integration handoffs.
- Replace Markdown banners, decorative separators, and repeated instructions
  with links to each topic's canonical page.
- Improve site navigation, search, and keyboard behavior; use local Phosphor
  controls and an accent-colored GitHub favicon on both pages. Search retains
  its background highlight without a focus outline.
- Update the site's transitive Terser plugin and serializer dependencies.

### Removed

- Retire unproven lexical rules `OURO-LINT022`, `028`, `031`–`036`, and duplicate
  unused/shadow emitters `038`/`039`; see the [rule audit](quality/lint_rule_audit.json).
- Remove unused pre-1.0 list helpers `break_list`, `partition`, `unzip`,
  `sort_nat`, `inits`, `tails`, `is_suffix`, and `update_nth`, plus `is_ws_or`,
  `text_split_ws_codes`, `nat_range_count_go`, and public collections `_go`
  helpers. Migrate `break_list` to `span` with a negated predicate and `sort_nat`
  to `sort_insert Nat leb_nat`; use `map_indexed`, `chunks_of`, `adjacent_pairs`,
  `dedup_adjacent`, and `nat_range_count` instead of their internal helpers.
- Delete uncalled lint `cat3`/`cat4`, LSP `uri_to_path`, quality inventory/debt
  helpers, strict `st_is_ident_char`/`st_relpath`/`st_debt_issues`, structural
  `st_is_ouro`, and bounded-text banner/skeleton/drive-record helpers.
  `bounded_run` remains the public scope/batch/keep root.
- Remove unimported `std/gen` residue (`id`, `const`, `maybe_fold`, and
  `ouro-hashes.txt`), unused analyzer `zz_*.ouro` drafts, and the duplicate
  `quality/shellcheckrc`.

### Fixed

- `adjacent_pairs` now advances its left element; `list_traverse_result` evaluates
  conversions in input order and stops when one returns `Left`.
- Recognize manifest-owned Clippy precision fixtures in the structural gate,
  retaining extraction, path confinement, and checks on unlisted sources.
- Cover `ESpan` in OuroSmith parser observations and keep comment delimiters
  from truncating the constructor inventory.
- Repair identical duplicate import aliases before collecting a fixer's root
  dependencies; retain compiler verification and reject conflicting aliases.
- Recompute composed Clippy contracts against each root's dependencies and
  retain imported-wrapper origins across cache hits.
- Resolve transitive runtime platform imports with explicit missing-file and
  unresolved-name failures.
- Bound shared Clippy intern vocabularies and resume remaining inputs in fresh
  workers before temporary memory grows beyond the worker budget.
- Keep imported parse bodies inside their allocation arena, share caller-owned
  intern nodes, and avoid quadratic text reconstruction during scans.
- Require literal identity-map bodies, preserve primed identifiers and literals,
  and distinguish discard binders from strings/comments in quality scans.
- Reject invalid profiles, incomplete options, advisory escapes, malformed or
  duplicate registry rows, unknown IDs, and empty suppression reasons.
- Keep source-relative diagnostics and original frontend errors on worker
  failure; preserve lint import-syntax errors before dependency checks.
- Preserve source coverage while sorting inventories, deduplicating aliases,
  streaming report arrays, rejecting empty scopes, and excluding output trees.
- Prune unreachable architecture-cycle searches with a shared adjacency index
  while preserving witness order and depth budgets.
- Restore strict-parser compatibility for the Clippy finding printer and shared
  quality IO entries; remove compiler-only names from the shared input module.
- Supply the missing heredoc scalar position in the structural lexer and add its
  stdin driver, corpus, and frozen-oracle parity observer.
- Bound large Nat literal construction and split quality compilation cones to
  avoid checker-fuel, host compiler stack, and compound-literal depth failures.
- Reuse replacement lengths in PE section patches; preserve the MIR callback
  test's error payload when factoring its large Nat literal.
- Decode Unicode paths and arguments in Windows bootstrap and C-hosted tools;
  reject invalid encoding and NUL paths, preserve spaces/wildcards, and fail
  before publication when UTF-8 manifest resources cannot be built.
- Report Windows bounded-capture allocation failures and use the status value
  for stdout read errors instead of the handle pointer. Reject C-host file-read
  errors with status 73 instead of returning empty source.
- Reject malformed package options/ranges and removal of unknown dependencies;
  make package `--help` exit successfully.
- Keep unsaved LSP diagnostics after unrelated disk edits and publish `CHECK_FAIL`
  when a checker failure cannot be attached to the open URI.
- Accept directory scopes in `fmt` and `fix`, reject empty scopes, and reject
  unknown or conflicting formatter options before IO.
- Limit unused-let deletion to closed literal initializers; preserve opaque
  evaluation, typed annotations, and ambiguous continuations during fixes.
- Support file framing in `ouro-fix-check` and reserve the documented POSIX stack
  for large inputs. Native quality CLI fixtures cover malformed registries,
  refusal paths, near misses, and quality-after-fix convergence.
- Reject incomplete `ouro-test` options, honor `--out`, and fail empty discovery.
- Retain the later value for duplicate keys in `map_from_pairs`,
  `config_from_pairs`, and `map_union`.
- Prepare package-sample dependencies in an isolated lint snapshot instead of
  requiring installed dependencies in the working checkout.

## [0.1.0] - 2026-09-14

First public release of compiler-owned checking, Windows x86-64 PE program
output, runtime garbage collection, the standard library, and repository
CLI/build tooling. See the [published release](https://github.com/eluvane/ouro/releases/tag/v0.1.0)
for the full notes and host archives.

[Unreleased]: https://github.com/eluvane/ouro/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/eluvane/ouro/releases/tag/v0.1.0
