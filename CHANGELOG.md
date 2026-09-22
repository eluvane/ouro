<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=CHANGELOG&amp;fontColor=E2E8F0&amp;fontSize=46&amp;fontAlignY=50"
    alt="CHANGELOG banner"
  />
</p>

# Changelog

Notable user-visible and project-wide changes are recorded here. New work goes
under `[Unreleased]`. Cutting a version moves that section under `vX.Y.Z` and
leaves `[Unreleased]` empty.

The project is pre-1.0. Syntax, APIs, CLI behavior, package files, and editor
integration may change.

## [Unreleased]

### Changed

- Select affected PR suites and dependent compiler shards for mapped tool
  changes, retain complete validation for shared or unknown inputs, and expose
  the selected gates in the GitHub summary. Keep main pushes, merge queues and
  manual CI runs complete; stop PR jobs after blocking failures.
- Share verified Linux compiler bootstrap artifacts across PR jobs, retain
  kernel coverage without duplicate PR gates, balance compiler shards by
  measured build cost, and give documentation changes a focused CI route.
- Check site changes with tests, lint, and a production build on pull requests.
- Honor package-only release dispatches and bind weekly tags to the workflow's
  source commit.
- Build and verify all required lint companions, including the transitive
  structural worker, when preparing an isolated native tool installation;
  preserve quiet success when the launcher prepares a cached tool.
- Retain public kernel type signatures through transitive Clippy imports;
  unresolved signature types still fail semantic analysis.
- Release Clippy parser and registry temporaries between analysis phases,
  and cover production imports in memory-bounded session tests.
- Preserve rejected-file diagnostics from completed Clippy sessions while
  continuing to reject broken transport and inconsistent exit statuses.
- Use explicit callbacks in raw memory and Windows process helpers so the
  existing native scalar lowering can compile their runtime actions.
- Refresh generated stage0 and its matching C0 runtime bundle while preserving
  the historical bridge inputs and their recorded lineage.
- Split lint workers and the host inventory, and move the unchanged let-term
  view into the existing term-view module, to keep production analyzer inputs bounded.
- Bound strict-quality scan temporaries per file, recognize suppression directives
  only in comments, and retain encoded native symbol references in structural checks.
- Terminate measured Linux subprocesses across nested sessions when a memory
  budget fails, so an aborted check does not leave its workers running.
- Consolidate duplicate internal quality/native helpers and remove unreachable
  private implementations. Keep compiler type-global projection outside the checker.
- Recurse over the shrinking event list in Clippy's token eligibility scan, and
  preserve Unicode character offsets in the native structural lexer.
- Align fixer validation with certified automatic edits and review-required
  semantic suggestions; incomplete sources remain rejected by the public CLI.
- Remove a cyclic native-lowering import that prevented the native build driver
  and frontend security checks from collecting their source dependencies.
- Update the site's transitive Terser plugin and serializer to remove known
  dependency vulnerabilities.
- Return an allocation error instead of dereferencing null when Windows bounded
  process capture cannot allocate the terminator for an empty output stream.
- Use the GitHub favicon recolored to the site's accent on both site pages.
- Use local Phosphor SVGs for GitHub links, documentation search, navigation,
  close, code-copy, and section-link controls.
- Remove the documentation search focus outline while retaining its background
  highlight.
- Document rolling parallel agent development with live file locks, focused
  acceptance checks, review and merge handoffs, and immediate slot replenishment.
- Build `str_join` and `str_repeat` with one output-sized byte-list assembly;
  avoid whole-string byte-list copies in `str_head`, `str_cons`, and `str_snoc`.
  Remove unused pre-1.0 list helpers `break_list`, `partition`, `unzip`,
  `sort_nat`, `inits`, `tails`, `is_suffix`, and `update_nth`, plus
  `is_ws_or`, `text_split_ws_codes`, `nat_range_count_go`, and the public
  collections `_go` helpers. Use `span` with a negated predicate for
  `break_list`, `sort_insert Nat leb_nat` for `sort_nat`, and the existing
  `map_indexed`, `chunks_of`, `adjacent_pairs`, `dedup_adjacent`, and
  `nat_range_count` entry points instead of their internal helpers.
- Select generated `.exe` workers in the Clippy precision suite and the
  `ouro1 lint` companion environment on Windows, so native validation can
  find the freshly built tools.
- `ouro1 lint` semantic companions send two `--scope` files to one
  Clippy worker when both are measured-light `std/` modules. Files at
  or above the 800 MiB sampled worker class, and every `compiler/` or
  `tools/` path, stay one companion process. The 3072 MiB Clippy cap
  is unchanged.
- The Clippy structural worker accepts multiple roots in one process,
  reuses one intern table and the content-addressed harvest cache across
  those roots, and emits the existing `ouro.clippy-semantic.v2` batch
  protocol. Hits reuse harvest facts only; selected files are still
  parsed and proofs still run. A batch larger than 2 files is rejected
  so a directory scan cannot load the whole tree into one arena.
  `--lint-companion` with two `--scope` files uses that batch.
  Language lint children still recycle every file under the 8 GiB
  `prlimit` AS cap. The 3072 MiB Clippy `run_limited` cap is unchanged.
- `ouro1 lint` is the user-facing source linter and accepts
  `--profile project|strict|release` (default `project`) plus repeatable
  internal `--family language|style|semantic` (default all three). Language
  stays in the existing `ouro-lint` children. Proven style
  (`OURO-LINT029`/`030`/`037`/`041`/`042`/`043`/`044`) and compiler-proved
  Clippy semantics run as separate companions so one unit never imports both
  `std/json` and the compiler frontend. Missing companions fail closed.
  `--deny` remains the all-findings-block contract. LINT041 uses the last
  `:` before `:=` as the binding ascription, so a typed telescope such as
  `def f (x : Nat) : List Nat := [x]` stays clean. LINT042 searches only
  outside quotes, so scanner messages that mention `` `;;` `` are not hits.
  `scripts/clippy_grade_firewall.py --profile/--scope` without report or
  query flags execs that semantic family under the existing 3072 MiB cap.
  `lint_suite.sh` production discovery is the one `ouro1 lint --deny`
  command; Clippy fixture denial stays in `clippy_grade_suite.py`.
  Multi-file Clippy firewall scans isolate one root per child so a
  76-file tools shard cannot reassemble a 3 GiB parent cone.
  Semantic harvest skips transitive `compiler/` and `runtime/platform/`.
  Selected files and their direct imports still harvest signatures.
  Files that name `InternState` import `pipeline_abi.ouro` directly.
  Harvested signatures whose result type is outside the keep set are
  classified as ordinary instead of failing the selected file.
  `compiler/base.ouro` and other small type modules stay harvestable
  when an imported unit enqueues them.
  `PeImage` / `NativeImage` live in `compiler/native/image_types.ouro`
  so a consumer can keep those constructors without harvesting
  `pe_word32`. That stays inside the existing 3072 MiB worker instead of
  exiting 137 or assembling a 7 GiB frontend cone. Clang tool emit uses
  `-fbracket-depth=4096` so Clippy semantic resource-law codegen can
  compile; this is not a lint RSS or AS cap raise.
- Lint and Clippy share a content-addressed harvest cache keyed by canonical
  path, byte length, and FNV-1a 64 of the exact source bytes
  (`ouro.quality-facts.v1`). Hits reuse harvested names and parsed import
  facts only; they never skip lint rules, Clippy proofs, or typechecking.
  Path-only matches are stale. A worker recycles after 64 lint files or 16
  Clippy roots and drops the in-process cache. `QualityInputError` lives in
  `tools/quality/input_error.ouro` so compiler-frontend Clippy units no
  longer import the IO inventory just to name a failure.
- `std/json.ouro` and `tools/quality/text.ouro` import `string_prims` /
  `char` instead of `std/runtime.ouro` / `std/string.ouro`. Clippy
  `core.ouro` / `scan.ouro` load findings from `registry_model.ouro` and
  no longer pull Windows process/file modules just to name a diagnostic.
  File JSON IO stays in `registry.ouro` for the firewall entry.
- Bounded-process capture reports a failed stdout read with the `U32`
  status (`output_0`) instead of the stdout handle pointer, so IO tools
  typecheck again.
- Lint children recycle after each file under the existing 8 GiB
  `prlimit` AS cap. The process-lifetime bump arena retains
  `lint_lines` garbage; a two-file batch of `std/fs` plus
  `std/process` already samples ~6 GiB. Harvest facts still reuse
  inside an explicit `--batch-files` child. Large Clippy Nat budgets
  are `mul` of small literals so `core.ouro` / `scan.ouro` /
  `structural_model.ouro` check without fuel exhaustion and so native C
  emit stays under clang's compound-literal nest limit. A whole-body
  `4096` Peano tower is 4098 nested `(ouro_v *[]){` braces and refuses
  to compile the firewall parent or structural companion.
- Clippy production scans may run up to two memory-capped launcher shards
  (`OURO_CLIPPY_JOBS`) under the existing 3072 MiB `run_limited` cap
  (`OURO_CLIPPY_MEMORY_MB`) with a 7200s host timeout. The launcher lists
  the clippy inventory itself so sharding does not require a rebuilt native
  `--print-files` protocol. The structural companion still analyzes one file
  per child. Production project scans are not an advisory `--warn-only`
  path. A host may set `OURO_REUSE_EXISTING_COMPANION=1` when rebuilding
  the firewall parent if the compiler-cone companion cannot be rechecked.
  Import harvest skips transitive `runtime/platform/` files so a std/fs
  or std/process root does not rebuild the Windows implementation cone
  inside the 3072 MiB worker cap. Direct platform imports of the selected
  file still harvest signatures.
  Lint source batches files in-process with a shared import-harvest cache
  and falls back to one child per file after a crash.
- Split Clippy `scan.ouro` / `main.ouro` off the compiler-frontend structural
  cone so one compilation unit never imports both `std/json` and
  `compiler/pipeline_abi`. `main.ouro` remains the firewall entry and reads
  already-built proofs from the `ouro-clippy-structural` companion.
- Clippy identity-map detection requires `fun name => name`, so real maps
  such as `map (fun x => add x 1)` stay clean. The structural companion
  rewrites `let _ :=` discard binders before the compiler parser so
  discarded-pure and ignored-checked lexical rules can still fire.
- Document repository-gate profiles using the `docs-native`, `project-native`,
  and `workflow-native` names that `scripts/ci_gate.py` invokes. The short
  names `docs`, `project`, and `workflow` remain aliases.
- Host ShellCheck uses repository `.shellcheckrc`. The unused
  `quality/shellcheckrc` copy is removed.

### Removed

- Retire unproven tools/strict lexical style heuristics: `OURO-LINT022`
  (TODO/FIXME/HACK grep and self-scan), `OURO-LINT028` (accessor-name
  guess), `OURO-LINT031` (nested-application depth), `OURO-LINT032`
  (wrapper guess), `OURO-LINT033`/`OURO-LINT034` (module/function size),
  `OURO-LINT035` (public-docs guess), and `OURO-LINT036` (panic/ICE grep
  and self-scan). Delete style unused/shadow emitters `OURO-LINT038` and
  `OURO-LINT039`; language lint owns those smells. Audit:
  `quality/lint_rule_audit.json`. Old bad fixtures are negative cases.
- Delete unused leftover helpers with no callers: lint `cat3`/`cat4`,
  LSP `uri_to_path`, quality `qr_obj_item`/`qr_is_dir`/`qr_exists`/
  `qr_realpath`/`qt_nth_line`/`qr_debt_max`/`qr_debt_min`/`qr_debt_reason`/
  `qr_debt_fix`/`qr_debt_track`, strict `st_is_ident_char`/`st_relpath`/
  `st_debt_issues`, structural `st_is_ouro`, and the unused banner,
  skeleton, and drive-record text helpers in `bounded_text.ouro`.
  `bounded_run` is now the documented public scope/batch/keep root.
- Delete unused historical `std/gen` residue (`id`, `const`, `maybe_fold` and
  `ouro-hashes.txt`). Those modules had no importers and are no longer part of
  the generated standard-library API surface.

### Fixed

- Keep unsaved language-server diagnostics when another `.ouro` file changes
  on disk.
- Accept directory paths in `fmt` and `fix`, selecting sorted `.ouro` files
  while skipping build and dependency trees and rejecting empty scopes.
- Reject unknown or incomplete `ouro-test` options, honor `--out DIR` on the
  everyday path, and report `test: no tests found` with exit 1 for empty discovery.
- Keep the later value when `map_from_pairs`, `config_from_pairs`, or
  `map_union` sees a repeated key, matching config-file parsing.
- Clippy's structural `cm_parse` seam no longer recopies the caller intern
  table on every imported file. `ouro_heap_context_leave` shares caller-owned
  nodes and copies only the nested lexer/parser graph.
- Clippy's structural load harvest (`cm_load_file`) keeps imported function
  bodies inside the nested parse arena. The selected file still keeps its
  bodies; imports keep signatures only so
  `OURO-CLIPPY-FRONTEND-001` out-of-memory on large compiler/tool cones is a
  heap-retention bug, not a source-pattern deny. Type-alias following on
  imported modules stays unknown when those bodies are not retained.
- Clippy-grade project `--warn-only` no longer rebuilds every definition
  body with per-character `prim_string_concat`. Match-depth walks skip
  quotes in place, string rebuilds use one `prim_string_of_char_codes`,
  and line scans keep a usage flag instead of joining the file. Identifier
  walks skip a whole name instead of retrying every interior byte, and
  multi-file scans reset the process-lifetime arena by isolating each
  file. The 3072 MiB `run_limited` cap is unchanged; `--warn-only` is
  still not the correctness owner.
- `ouro-fix-check` applies the documented 128 MiB POSIX stack reserve at
  startup so a legal large source no longer SIGSEGVs on the default 8 MiB
  Linux stack. The independent fix-check observer configures the same reserve
  before launching the worker. Arena and RSS budgets are unchanged.
- Language-server `textDocument/publishDiagnostics` now emits `CHECK_FAIL` when
  a checker run fails but no diagnostic attaches to the open URI. Unknown-name
  and imported-module projections no longer publish an empty list that looks
  like a clean document.
- Reject unknown active Clippy profiles, empty option values and strict/release
  advisory escapes. Validate raw and normalized registry rows before every
  inventory mode; reject lossy rows, duplicate keys/IDs, invalid levels and
  empty diagnostic metadata. Unregistered emitted IDs are fatal. Source policy
  uses the validated source root while diagnostics keep repository-relative paths.
- Preserve primed identifiers and literal values in shared quality text scans.
  Clippy clone keys retain signatures, binders, callees and literals through the
  existing positional lexer instead of erasing semantic distinctions. Empty
  suppression reasons do not grant an exception; directive-looking strings are
  not line-comment directives.
- Limit unused-let deletion to closed literal initializers and preserve opaque
  evaluation under an explicit discard. Propose unannotated identity-let
  simplification without substitution, retaining initializer evaluation and
  precedence while refusing typed annotations and ambiguous continuations.
  Existing whole-candidate compiler checking remains the publication boundary.
- Add native CLI regression cases for malformed registries, strict refusal,
  good/near-miss cleanliness, let-fix boundaries and quality-after-fix
  convergence. The fix suite fails instead of reporting a skipped pass when no
  C compiler is available. Native suite results remain a separate validation
  requirement; these changes do not establish production-wide strict cleanliness.
- Split Clippy `lines`/`defs` into helper and scanner modules so
  `lint_suite.sh` can compiler-check the cone in chunks instead of one
  15.6 GiB RSS unit. After the split, `tools/clippy/main.ouro` also
  typechecks and is a required `CHECK_OK` gate.
- Accept `ouro-fix-check SOURCE file PATH` in addition to stdin framing.
  POSIX C-host bounded capture still returns OS 120; `fix --write` and
  `fmt --write` then check the candidate through file mode and
  `process_run_spec_checked` without changing the C runtime. Formatter
  writes skip the gate only when the original is already a compiler
  rejection. POSIX file mode does not apply bounded 120s/memory caps.
  Clang tool emit uses `-fbracket-depth=2048` so the formatter cone
  can include the worker launch.
- Parse `tools/clippy/main.ouro` by lifting the nested `fix`-in-`do` finding
  printer and extracting the status line, matching the strict firewall.
  The Clippy Windows C-host build embeds the same UTF-8 manifest as the other
  quality tools. Python still launches rule JSON, profiles, suppressions, and
  reports; this is not byte-identical parity with the retired regex owner.
- Pass the missing heredoc scalar position into `st_hd_all` so
  `tools/structural/lex.ouro` typechecks. Add a stdin JSON lex driver, fixture
  corpus, and `scripts/structural_lex_parity.py` against the frozen Python
  oracle. Python still owns symbols, findings, and reports.
- Remove unused `tools/analyze/zz_*.ouro` drafts and typecheck
  `tools/analyze/bounded_text.ouro` in the precision core list. The bounded
  supervisor and launcher remain Python-owned.
- Bound quality inventory sorting and canonical-path deduplication with stable
  merges, preserving the first path spelling and complete coverage. Stream the
  inventory JSON array to avoid quadratic report buffers on large scopes.
- Move standalone `Nil` detection for `OURO-LINT029` into the native fixer's
  tokenizer. Preserve code locations and reject strings/comments as candidates;
  the checked span protocol now requires v2 for complete list coverage.
- Share a diagnostic transport record across native lint, analyzer and fix
  text renderers, preserving their public text layouts and rule owners.
  Base analyzer forbid/fatal records remain visible even when marked suppressed;
  malformed severity records cannot become a successful hidden result.
- Reject C-host file read failures with status 73 instead of passing an empty
  source to quality tools. Independent runtime and analyzer CLI checks cover
  locked files, invalid paths and successful empty/binary reads.
- Run the two compiler property domains in sequential isolated workers,
  retaining seeds, ranges, laws and complete counters while releasing each
  process's allocation arena. Reject incomplete worker reports.
- Stage formatter and fixer writes through an Ouro-owned source replacement and recovery
  path. The filesystem operation preserves supported source metadata, refuses
  hard links and unsupported attributes, and retains recovery on an uncertain
  partial failure. Candidate compiler checking remains unfinished for formatter
  writes; fixer writes enforce it (see below).
- Reject unknown formatter options and conflicting modes before IO instead
  of ignoring flags on a write command or accepting a read-only write as done.
- Build the retained compiler laws with `O1` in every cache mode, retaining the
  500 ms full process budget and recording the optimization in receipt checks
  and baseline context.
- Preserve the MIR callback test's error payload while factoring its large Nat
  literal, avoiding host C compiler stack exhaustion during the test build.
- Make the shared quality input module and its tests build independently of
  compiler-only names. Native quality IO entries use accepted `do` syntax.
- Share checked inventory and reads with the base analyzer, retain repeated
  scopes, deduplicate path aliases, reject empty selections, and exclude
  build/cache/dependency trees.
- Reuse an architecture adjacency index and prune unreachable cycle searches,
  preserving ordered witnesses and depth budgets across shared import graphs.
- Preserve lint import syntax diagnostics before checking dependency files.
  The lint suite prepares the package sample's local dependencies in an isolated
  production-source snapshot instead of requiring installed files in the checkout.
  The full quality migration remains incomplete.
- Embed a process-local UTF-8 manifest in Windows C-host quality tools to
  preserve Unicode arguments and diagnostic paths. Builds reject resource
  failures before publishing; Windows 10 version 1903 or later is required.
  The lint suite checks the complete build receipt before running fixtures.
- Prevent local suppressions from hiding fatal Clippy diagnostics in strict
  and release profiles, keeping text, JSON, SARIF and exit status consistent.
- Route the legacy syntax-fix CLI through native `ouro-fix` and remove its
  Python rewrite and closed-list parser implementations. The strict firewall
  obtains LINT029 spans from the same native Cons/Nil recognizer, with checked
  byte lengths, complete reports and no fallback after worker failure.
- Move strict/Clippy source selection to the shared native inventory, preserving
  their production scopes and rejecting missing, unsafe or empty selections.
  Remove both Python traversal and exclusion implementations.
- Remove Clippy findings inferred from fixture names and wrapper-path suffixes.
  Import fixtures use explicit source roots; rename and near-miss checks cover
  the retained import-layer and checked-wrapper policies.
- Refuse literal fixes when a built-in constructor name is locally bound,
  preserving the source instead of erasing uses and renaming the binder.
- Reject unknown fix options and conflicting check/write or selftest modes
  before reading or changing source files.
- Reject missing files, mismatched native family selections, damaged reports
  and inconsistent worker exit codes in bounded structured analysis and the
  production sweep. Production builds now check the full native build receipt.
- Invalidate previous CI summaries before running gates in both CI runners,
  preventing an interrupted run from retaining an old successful aggregate.
- Keep native test subprocess deadlines buildable by C-host compilers using
  small Nat factors, with unchanged timeout, memory, CPU and capture limits.
  Check build-tool caller paths after the host's path conversion.
- Set the GitHub repository explicitly for draft publication without a checkout
  and use the version tag as the release title.
- Check fixer `--write` candidates with the existing compiler before replacing
  source: a bounded worker verifies the preflight source and the rewritten
  candidate over an exact stdin frame, refusing unbound names, type errors,
  bad imports, and cycles without changing the file. Unit closures are
  budgeted at 512 with an exact count. The transitional Windows C host runs
  this bounded check through a narrow Job-contained adapter (no affinity
  pinning; POSIX still reports unimplemented); the foreground inherit API
  keeps its C-host stub.

## [0.1.0] - 2026-09-14

First public release of compiler-owned checking, Windows x86-64 PE program
output, runtime garbage collection, the standard library, and repository
CLI/build tooling.

Host toolchain archives contain the sources and a C-hosted `ouro1` for Linux
and macOS on x86-64 and ARM, and Windows x86-64. They do not claim signed
binaries, SLSA provenance, or a formal correctness proof.

### Changed

- Name native encoding and buffer constants, reuse list counts and simplify
  bounded definitions for the strict production analyzer. Process capability
  checks recognize the exact checked-wrapper owner at `std/process.ouro`.
- Preserve NUL and high-byte values when the C host concatenates, searches,
  and slices strings, including captured output, executable paths and PE images.
  The N1 error diagnostics render packed, linked and concatenated strings exactly.
  The hosted test wrapper keeps successful
  build logs out of the test protocol and retains failed-build diagnostics.
- Release temporary PE fixup-planning storage before image serialization in
  the C host, preserving the complete patch list and typed failures.
- Run the complete compiler assertion inventory in eight mandatory CI shards.
  Kernel, Manual, and Release use complete profile partitions so cold compiler
  tests do not share one job deadline; full local commands retain every gate.
  Hosted test-suite execution reserves the same 128 MiB stack as OuroSmith,
  including large MIR laws launched after their build subprocess has exited.
- Regenerate the C bootstrap seed and pin its matching C0 runtime in the
  recovery bundle. The historical bridge and strict current-source, ABI,
  behavior, and complete P1/P2 C comparison checks remain required.
- Preserve arbitrary-size Nat arithmetic and decimal output in the C host,
  including bounded-process limits and exit codes across 32-bit and 64-bit
  boundaries. Host-size conversions reject overflow.
- OuroSmith law-driver preparation uses the compiler build memory budget while
  generated programs retain their configured execution limits. Stdlib and IO
  integration recipes separate compilation and execution deadlines.
- JSON string decoding uses a balanced byte builder to avoid C-host stack
  overflow on large LSP documents while retaining byte and error offsets.
- C boundary analysis keeps invalid applications fatal and avoids a signed
  underflow in empty-list reconstruction.
- The temporary C runtime binds the word conversions and Runtime loop used by
  zero-delay actions; invalid loop flags remain fatal.
- Analyzer and stdlib IO imports share `std/string_prims.ouro`, avoiding duplicate
  String declarations without adding platform imports to pure analyzer cores.
- Hosted sample/test processes receive their fixture stdin; test builds resolve
  relative source and output paths from the caller's directory. The C-host IO
  suite explicitly selects the same compiler and build wrappers. C-host process
  capture preserves arguments assembled with list concatenation and rejects
  malformed argument lists before launching a child.

- Import collection preserves the compiler's specific `OURO-IMP-001` through
  `OURO-IMP-004` diagnostics instead of replacing them with a generic error,
  and skips ordinary source spans without retaining per-byte scan temporaries.
- Memory checks prepare native tools under a separate bounded build phase
  before applying the existing formatter, analyzer, and compiler RSS limits,
  and require actual structured analysis of the largest production source.
  Primitive registry and host inventory definitions are split into smaller
  modules to keep that input within the analyzer's source-size limit.
- macOS host binaries reserve their compiler stack when linked; x86-64 release
  builds use the supported `macos-15-intel` runner.
- Structural shell checks distinguish saved exit status and unconditional
  artifact verification from a backend selected after command failure.

- GitHub Releases now publish Lean-style host archives
  (`ouro-<version>-<platform>.tar.zst` and `.zip`) for `darwin`,
  `darwin_aarch64`, `linux`, `linux_aarch64`, and `windows`, instead of
  source-only `ouro-*-source` packs.

### Fixed

- Prepare the current compiler before Manual and Release validation groups,
  including incomplete restored caches. PR and Nightly job deadlines cover
  cold bootstrap plus full compiler groups. Smith's large integration-source
  checks and compilation use the native preparation deadline while generated
  program execution retains its configured limit.
- Enable Darwin declarations for no-follow C-host writes and install release
  packaging dependencies in a Python 3.12 virtual environment on managed hosts.
- Set the Clang C parser's bracket-depth limit for generated constructor
  expressions, including historical bootstrap inputs on Intel macOS.
- Bind Release artifact names to the workflow run ID so uploads and downloads
  also work from branches containing a slash.
- Keep C-host native-lowering progress out of ordinary programs' stderr while
  preserving explicit N1 diagnostics and all failure messages.
- Release temporary C-host allocations after each complete MIR flow round,
  preserving shared facts, convergence fuel and typed errors when compiling
  large native process functions.
- Hosted C static analysis accepts the N1 selftest, IO selftest, heap live-byte
  walk, and empty frontend prepass.
- Analyzer cores that only need string primitives import
  `std/string_prims.ouro` instead of `std/runtime.ouro`, so
  `ANALYZE_CORE` does not load the Windows platform cone.
- Hosted `ouro1 check` keeps relative paths in the caller directory so
  `pkg verify` can typecheck `_ouro_pkgs/...` after the wrapper cds to the
  repository root.
- C-host `ouro1 test` sets `OURO_TEST_CHECK` and runs sample/test children
  through `prim_proc_exec`; dash `run_suite` keeps the child's exit status.
- Release packer decompresses zstd frames that omit a content-size header.
- Restored bootstrap input hashing so a clean host can freeze and build `ouro1`.
- Split oversized checker modules and cleared the release-quality findings that
  were failing the PR firewall.
- Hosted `PR (smith)` and the other non-`checks` PR groups now build `ouro1`
  on a cold cache instead of failing closed on a missing `_build/c/ouro1`.
- Hosted Portable macOS no longer aborts bootstrap when CPython pins
  `RLIMIT_STACK` or when Darwin rejects a finite address-space cap; POSIX
  children on Linux still apply a sticky AS cap when the host allows it.
- Hosted `Kernel` and nightly non-`checks` groups now build `ouro1` on a cold
  cache instead of failing closed on a missing `_build/c/ouro1`.
- Restore fixture identifiers after Core-descriptor sharing so retained and
  smith kernel checks name the shared `checker_test_*` declarations.
- Use the current typed term checker in constructor-closure and source-refinement
  laws, retaining successful type checks and rejection of invalid annotations.
- Run the canonical exact liveness solver in the C host and retain its edge and
  fuel errors before accelerated function emission.
- Write release reports before hashing all final artifacts, including when the
  same output directory is reused.
- Give `pe_relocation_block` the `List (List Nat)` encoding list so PE
  relocation emission typechecks.
- Hosted C-host test, LSP, package, sample, and Smith suites invoke
  `scripts/ouro1.sh` through `OURO_TEST_CHECK` / `OURO_HOSTED_COMPILER_WRAPPER`
  instead of forcing the Windows `coil.exe` sibling path.
- Bind the `primitive_roles` singleton list before passing it to `append` so the
  historical bridge parser can check `file_elab.ouro`.
- Restore the missing `emit` helper used by record expansion so the historical
  checker accepts `preprocess_record.ouro`.

[Unreleased]: https://github.com/eluvane/ouro/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/eluvane/ouro/releases/tag/v0.1.0

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
