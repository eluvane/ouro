<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=CHANGELOG&amp;fontColor=E2E8F0&amp;fontSize=46&amp;fontAlignY=50"
    alt="CHANGELOG banner"
  />
</p>

# Changelog

Notable user-visible and project-wide changes are recorded here.

The project is pre-1.0. Entries describe the repository state; release tags and
dates are added when a release is published.

## [Unreleased]

### Added

- The hosted Release workflow publishes a dated `weekly-YYYYMMDD` snapshot of
  `main` when the tree changed, without bumping the project version.

- Standalone native LSP, package verification and user tests invoke sibling
  executables through bounded capture with explicit process failures. LSP
  workspace authorization, package integrity checks and retained suite
  assertions remain enforced. User tests discover directory inputs and
  preserve exact fixture stdin; the recursive runner row tests its loaded
  executable. Native `coil` tool dispatch remains separate work.

- Native bounded capture accepts exact binary stdin and applies explicit
  timeout, one-CPU, Job-memory and per-stream byte limits, with separate typed
  infrastructure failures and complete child exit codes.

- `executable_path_checked` queries the current Windows image path as UTF-8
  with typed query, conversion and cleanup errors, preserving loaded spelling.

- `process_run_inherited` and its command-spec/checked wrappers provide native
  foreground execution with inherited streams, typed process errors and an
  owned job for cancellation cleanup of the child and descendants.

- `ouro-native-build ROOT.ouro OUT.exe` resolves its import closure directly,
  including dependency paths with spaces; explicit unit lists remain supported.
- `fs_rename_checked` exposes same-volume file replacement with typed errors;
  `prim_fs_rename` retains the underlying OS status.
- `prim_process_capture` exposes checked status/stdout/stderr pairs while
  `prim_proc_exec` preserves the existing `ProcResult` API.
- `coil doctor` / `ouro1 doctor` reports
  `x86_64-windows` and `legacy-c: rejected`.
- Native `coil run FILE.ouro [PROGRAM_ARG ...]` builds and atomically publishes
  the program, forwards literal arguments and inherited streams, and preserves
  the child's exit code without printing a build-path line.
- `runtime/native_types.ouro` exposes checked `I32` plus the signed
  from-nat / compare / wrap-sub and U32 reinterpret conversions already
  used by native lowering.

### Fixed

- Native bounded capture keeps killed-child stdout/stderr: capture files are
  not `FILE_ATTRIBUTE_TEMPORARY`, and length queries flush before measuring.
  Cleanup waits for the process handle after job terminate and may stop the
  direct child with a finite `TerminateProcess`, so a wait-timeout stays
  `ProcessCaptureTimedOut` instead of OS status 258.

- Native `sleep_s` and `delay_then` use finite Windows waits, preserve full
  `Nat` durations, and report runtime conversion failure instead of ignoring
  an external `sleep` command's result.

- Native command parsing rejects unknown, repeated and incomplete options.
  The shared compiler driver separates closure checking from executable
  lowering and preserves positional bootstrap inputs and checked publication.
- PE fixup planning indexes symbols once, retaining target validation and
  diagnostic order while avoiding repeated full symbol-list scans.
- Native managed objects share a private Windows heap, avoiding one committed
  page for each small allocation. Collection releases unreachable blocks and
  destroys empty heaps while retaining exact roots and failure ownership.
- Declaration planning indexes definition names once, preserving core order
  and duplicate bodies while avoiding repeated full-list membership scans.
- Import collection handles multiline declarations, optional semicolons,
  quoted-path escapes, and UNC prefixes without treating strings or record
  projections as dependencies.
- Managed lowering shares one canonical lookup index for each checked program
  while retaining runtime helper body and signature checks.
- The N1 producer checks complete MIR before GC annotation and code emission.
  C-host callbacks retain the current program and flow budget on repeated calls.
- C-host lexer suffixes share retained immutable bytes instead of copying the
  rest of the source after every token.
- C-host compilation preserves caller contexts and earlier checked results;
  completed preflight and elaboration passes release their temporary storage.
- C-host PE byte checks release temporary storage after each checked chunk,
  preserving complete input bytes and the first typed validation error.
- Compiler fallback checks stop computing depth at the required threshold,
  retaining the full hole scan and existing acceptance and error conditions.
- Native-build output is staged, checked byte for byte, and renamed into place;
  failed publication reports an error and preserves the previous image.
- C-host String equality compares binary lengths and bytes after NUL, so
  artifact readback cannot accept a truncated or corrupted suffix.
- Capability, effect, and taint inventories cover native rename, process
  capture, and HTTP request primitives alongside retained legacy raw names;
  checked wrappers keep their existing policy boundary.
- Native PE images reserve a 2 GiB stack, matching the Windows producer
  link, so a self-hosted `ouro-native-build` does not die on the default
  1 MiB PE stack.
- C-hosted native-build reuses the frontend phase-discard seams for
  `compile_checked_units`, and OOM reports the failed size and live bytes.
- C-hosted native lowering releases declaration-checking temporaries during
  exact replay while retaining metadata checks, body checks and caller values.
- Native-build MIR node/flow hard ceilings are `pe_byte3_place`, so a
  compiler-sized program can request a 16 Mi-node budget instead of failing
  as `lower:mir:resource` at 65536 nodes. Per-global lowering keeps
  already-permanent cells instead of deep-copying the checked program.
- `std/io` imports the checked GC runtime so `ouro1 build` can lower ordinary
  `IO Unit` programs such as `samples/demo/01_hello.ouro` to a native PE.
- Native-build managed lowering covers stdin line/byte reads, so echo-style
  `readLine` programs can emit a Windows PE.
- Native-build managed lowering covers `argv` and `env_get` for ordinary
  process-startup programs.
- Native-build managed lowering covers time, file read/write, filesystem
  predicates, mkdir/remove, copy, rename, directory listing, and realpath.
- The lexer and collector reuse shared character and import helpers, avoiding
  duplicate declarations in the flattened native-build closure.
- C host file read/write and string `of_char_codes` keep exact `0x00-0xFF`
  bytes by length, so native PE emission is not truncated at NUL.
- Gate launchers resolve physical `.exe` names under MSYS before checking
  source manifests, without bypassing stale primary binaries or failed rebuilds.
- Managed native lowering accepts checked String intrinsics as function values
  and partial applications through the existing closure conversion path.
- Native liveness reuses per-block transfer summaries without changing root
  results, convergence budgets or fail-closed diagnostics.
- Source-only and declaration compilation reject unresolved imports before
  lowering; importing inputs must use the complete units API. Missing imports
  cannot be hidden by unused declarations or effect roots.
- Bootstrap behavior probes use the complete frozen standard-library import
  closure instead of a partial handwritten unit list.
- Native directory creation and non-recursive removal support deferred, reused
  actions with Unicode paths and checked cleanup.
- Native file copying preserves binary contents, overwrites existing targets,
  and reports copy, conversion and cleanup failures with exit status 73.
- Native realpath actions resolve Unicode files and directories, follow links,
  normalize Windows prefixes and separators, and check resource cleanup.
- Native managed allocations share a collection budget based on live heap
  pressure and allocation size. Explicit collection still performs a full pass.
  Raw managed contexts now reserve a trailing budget word; heap validation runs
  at scheduled or explicit collections.
- Native existence and directory predicates query current Unicode path attributes
  on each action execution, preserve directory junction bits, and check cleanup.
- Native file-kind queries preserve Unicode paths, defer each lookup until the
  action runs, and distinguish reparse points from their targets.
- Native stdin supports deferred and repeated line/byte reads, preserves
  binary bytes and read positions, and reports input or cleanup failures
  with exit status 73.
- Native directory listing preserves Unicode names and host enumeration order,
  distinguishes empty directories from failed enumeration, and closes search handles.
- Native file read/write actions preserve binary contents, use strict Unicode
  paths, reject failed IO, and retain the final-component reparse write guard.
- Native argument and environment actions preserve Unicode, empty values,
  repeated reads, and captured values across garbage collection.
- Native specialization of checked Nat arithmetic preserves full values
  beyond machine-word boundaries and ordinary partial application.

- Native `now` uses a checked clock identity and returns Unix-epoch milliseconds
  when its action runs, including repeated execution of a stored action.

- Native stdout, stderr, flush, and exit use checked Runtime identities.
  Writes preserve exact bytes and release staging storage after failure;
  stored actions and first-class writers execute when invoked.
- Experimental native programs share standard-library data identities with the
  raw runtime. `IO` aliases `Runtime`, Unit entry actions complete with status
  zero, and runtime loops preserve deferred actions and their current state.
- Native Nat successor, predecessor, and checked word conversions preserve
  values beyond 64 bits. Native String operations preserve exact bytes through
  access, slicing, search, replacement, splitting, byte-list conversion, and
  decimal Nat rendering.
- Shared data declarations live in `std/types.ouro`, preserving their
  identities across the standard library and raw runtime. Importing the raw
  vocabulary no longer brings executable Nat/List helpers into scalar lowering.
- Native calls with up to four arguments reuse the current stack frame
  when their continuation only copies and returns the result. Tail jumps
  preserve shadow-root cleanup and Windows stack unwinding. GC marking
  avoids redundant intermediate-owner checks after full heap validation.
- Native code generation reuses encoded non-branch atoms, and PE function
  validation advances through ordered text. MIR membership and set checks
  avoid repeated full scans while preserving rejection and resource limits.
- Cold `ouro1 check` and `collect` keep successful collector build logs outside
  their output protocol; failed builds retain their diagnostics on stderr.
- Experimental native lowering supports checked Windows externs as reusable
  function values and partial applications. Constructing a `Runtime` action
  preserves deferred execution; each invocation performs its foreign call.
- Windows compiler profiles reuse the build receipt published for a native
  repository gate with an `.exe` suffix, retaining strict artifact and input
  identity checks.
- Diagnostic hints preserve specific checker and lexer errors, including their
  details. A parse failure is classified using its failing source unit, so an
  unrelated list or hole cannot replace the original error.
- String literals require the registered `ouro.string` type or a transparent
  alias. The standard library declares String operations as checked intrinsics;
  standalone preludes must replace opaque String assumptions. API documentation
  recognizes `intrinsic` and `extern` declarations.
- Compiler diagnostics emit complete checked programs through
  `--emit-checked-program`, replacing the incomplete JSON export. Surface
  transformation checks compare declared types, exact string bytes, checked
  bindings, and representation metadata. The transitional C emitter uses checked
  types to identify erased type globals and resolved String intrinsic identities
  to choose runtime operations.
- Declaration checking retains exact string-literal bytes and evaluates checked
  pure String intrinsics during type conversion. Unresolved literal references
  and malformed byte sequences report explicit failures; literal bytes do not
  produce analyzer reference or branch facts.
- Experimental raw load/store declarations require checked scalar storage
  types. Intrinsic bindings retain normalized specialization metadata for
  native lowering, including type aliases and typed function signatures.
- Native lint and its launcher check sources above 12 KiB instead of silently
  skipping them. The launcher propagates child crashes and memory failures.
- Lint reports unsupported syntax consistently, including `mutual` blocks.
  Compiler and tool sources use bound imports, explicit recursive definitions,
  and distinct local binders. The compiler checker and standard-library examples
  use supported syntax, removing their analyzer rejection allowances.
- Root analyzer scans prune build and dependency trees before discovery and
  exclude diagnostic fixtures by default, preserving bounded execution.
- Deadcode honors every name in entry/export annotations and distinguishes
  all match scrutinees and constructor refinements when checking shadowed arms.
- CI reuses content-addressed native tools and common runtime objects, splits
  samples and OuroSmith into isolated PR jobs, and partitions nightly checks
  while preserving stage-loop/OuroSmith ordering and aggregate failure.
  Manifest checks build only their
  required collector and test runner.
- Analyzer binder masks and native precision fixtures supply explicit list
  element types, restoring compilation through the committed bootstrap frontend.
- Analyzer CLI validation rejects unknown options and missing values. Standalone
  bounded analysis and frontend regeneration reserve the same POSIX stack size
  as OuroSmith so native tools do not crash under the shell's smaller default.
- The VS Code launch-policy tests run against compiled JavaScript through
  Node's test runner.
- Compiler sort inspection is shared by checking and extraction; import-alias
  validation and constant-time list-shape checks keep production analysis within
  its declared complexity bounds. Analyzer CLI entry points are classified as
  host tools while pure analyzer modules retain their capability restrictions.
- OuroSmith text-tool cases materialize and preserve their imported module
  dependencies, including saved-input replay.
- Extractor recursion puts its decreasing fuel or argument spine first, allowing
  the compiler module to pass standalone checking. Parity checks require both
  paths to accept every positive input.
- Structured naming and dataflow share positional recursive-parameter use
  facts, distinguishing a binder's own annotation, dependent suffixes, and
  later same-name binders. Simplification masks locally shadowed helpers,
  requires unary double-negation calls, and avoids advice that would discard
  an unknown computation through identical arms or absorbing Bool constants.
- The analyzer launcher refuses a clean verdict when a structured process
  returns zero with diagnostics, rejected units, or an incomplete report.
- Abstract interpretation masks shadowed facts across binders, distinguishes
  the divisor from later application arguments, and joins agreeing match-arm
  values without treating mixed or unknown branches as proof.
- Lint accounts for telescope shadowing when checking unused binders and
  recursion, and follows ascribed constructor applications without duplicate
  reports for the same maximal application spine.
- Shared formatting preserves forward-pipe tokens, primed identifiers, and
  quoted tabs. The formatter refuses changed candidates that alter source
  tokens or fail a second-pass idempotence check.
- The autofixer refuses incomplete import-constructor inventories and
  unconverged rewrites, then applies checked canonical formatting. Formatting
  drift is reported even when no syntactic fix is needed; failed preparation
  does not write a partial result.
- Consolidated compiler source-byte operations, file parsing, internal AST
  queries, host value decoding and build-cache helpers; removed dead internal
  definitions, wrapper aliases and the unused linker generator.
- Added a blocking repository structural gate with normalized clone groups,
  private reachability, wrapper/fallback checks, semantic candidates and narrow
  typed classifications, through `strict_quality_firewall.py --structural`.

- Native builds normalize entry paths consistently with collected units, so
  default `ouro1 test` discovery can build relative `./*_test.ouro` inputs.
  Test binaries use the calling project's output directory when launched outside
  the Ouro repository root.
- Applied lambdas preserve the expected result type when lowering a match
  whose scrutinee has a different type; domain and branch mismatches still fail.
- Native `eval` links the string primitive implementations, and manifest
  rejection rows require the checker rejection status rather than any failure.
- Native tool suites consume generated inputs and independent expectations
  from OuroSmith. Surface samples run concurrently in deterministic seed order.
- Windows sanitizer checks discover installed Visual Studio toolchains,
  including Insiders, and initialize their compiler environment locally.
- The linter preserves the specific `OURO-IMP-001` through `OURO-IMP-004`
  diagnostic when import preprocessing fails.
- Code extraction derives its traversal budget from the core term size, so
  large natural-number literals no longer become runtime extraction errors.
- Nested structural recursion preserves strict descent through the structural
  parameter of an immediately applied inner fixpoint. Growing accumulators,
  unchanged inputs, and escaping recursive functions remain rejected by the
  canonical compiler checker.
- `std/json.ouro` rejects trailing commas in arrays and objects, including
  nested inputs, while preserving empty containers and ordinary separators.
- The self-hosted checker validates lambda annotations, match branch types
  and constructor arities, and structural recursion. Bootstrap dispatchers
  and source scanners carry explicit decreasing bounds under these checks.
- Nested `do`/`match` bindings preserve the inferred result type of their
  branches. Native checking releases temporary compilation data before
  constructing diagnostics for a rejected module.
- `ouro1 eval` prints natural numbers whose constructor spine ends in an
  unboxed literal, including results produced by multi-scrutinee matches.
- `std/test.ouro` prints `FAIL` for failed assertions as well as returning a
  failing process status.
- `ouro-doc` generates ordinary Markdown files for absolute Windows input
  paths, without interpreting a drive colon as an alternate-stream separator.
- The Python CI runner passes portable paths and its selected interpreter to
  shell suites on Windows.
- `ouro1` and `coil` no longer emit a GNU `tr` warning while normalizing
  Windows paths.
- Ouro-native repository and CI gates now reject options with missing values
  instead of silently selecting default profiles.
- The generated-C shard-cache regression records parallel fake-compiler calls
  without relying on lossy cross-process file appends on Windows.
- The practical application-surface CLI builds again, and its JSON/CSV helpers
  return typed `AppSurfaceError` values instead of bare string errors.
- `ouro1 lint` no longer reports an unbound `eqNat` in
  `compiler/canonical_hash.ouro`. Tree lint skips the intentional hole
  and unbound samples (`04_holes.ouro`, `bad_undeclared_perform.ouro`).
- Clippy-grade `REDUNDANT-004` compares sibling arms of one `match`, not
  every arm text in a definition. `MAINT-007` ignores single-constructor
  field projections. Biome deny now includes the VS Code launch-policy test
  and `site/vite.config.js`.

### Added

- `ouro1 build FILE.ouro` compiles a native Windows PE without a C fallback;
  `ouro1 run FILE.ouro` compiles then executes. The wrapper supplies the
  collected import closure. `IO Unit` programs retry managed lowering after
  the scalar lowerer rejects their type. Toolchain
  `ouro1 build --profile` is unchanged.
- Experimental Ouro Windows process adapters provide explicit executable,
  argv, environment and cwd inputs, restricted handle inheritance, file-backed
  capture, wait, direct-child cancellation, and ownership-preserving cleanup.
- `ouro1 analyze --enable-style` selects the existing dataflow, metrics,
  simplify, perf, and naming families without duplicating diagnostics. The
  precision suite gains 48 native style regressions, profile-parity checks,
  launcher argument/verdict tests, and an unused-binder fix/format/analyze
  round trip. Existing rule IDs and the mechanical autofix boundary remain.
- Native precision regressions under `tests/analyze/precision/`, executed by
  the existing analyzer precision gate: exact diagnostics, bad/good/false-positive
  cases, safe formatting, and fixpoint checks. Formatter and fixer selftests
  also verify refused writes leave the original bytes unchanged.
- OuroSmith provides generated kernel and source properties, independent
  oracles, bounded execution, saved-input replay, shrinking, source fault
  injection, and an explicit migration matrix for the manual corpus.

- Biome in deny-all on `editors/vscode/src`, `editors/vscode/test`,
  `site/src`, and `site/vite.config.js` (`preset: all`, every group error,
  `--error-on-warnings`).
- Ruff deny lint for `scripts/*.py` (`python-lint` in the PR CI profile).
- ShellCheck deny lint for repository `.sh` files (`shell-lint` in the PR CI
  profile).
- Biome, Ruff, and ShellCheck configs live under `quality/`, not the
  repository root.
- Typed external-tool execution evidence and provenance examples under
  `samples/scientific/`.
- Typed RNA-seq and GRCh38 variant-calling examples under
  `samples/bioinformatics/`, including negative fixtures for incompatible
  workflow states.
- Local package, documentation, test, formatter, analyzer, linter, LSP, and
  VS Code tooling for the current language slice.
- Incremental build and bootstrap caches with parity and drift checks.
- Typed Ouro regression laws preserve the useful semantics of the archived
  JSON Core corpus. Saved native generator recipes require their exact
  generator hash; the historical schema remains recovery data.
- `ouro1 fix [--check | --write] FILE...`, an Ouro-native autofixer under
  `tools/fix/` for the mechanical part of lint findings: duplicate imports,
  legacy `x <- action` binds, `;;`, closed `Cons`/`Nil` chains, Peano towers,
  unused binders (`_name`), dead `let`/`let!` bindings, and unreachable match
  arms. It rewrites the original bytes through a positional token stream, so
  comments and formatting survive; `sh scripts/fix_suite.sh` exercises these
  rules, and the `fix` gate joins the PR profile.
- Four structured analyzer families in `ouro1 analyze`, each part of
  `--enable-light` and `--enable-strict` after the production sweep reported
  nothing: `--enable-simplify` (`OURO-SIMP001`Р В Р’В Р вЂ™Р’В Р В Р’В Р Р†Р вЂљР’В Р В Р’В Р вЂ™Р’В Р В Р вЂ Р В РІР‚С™Р РЋРІвЂћСћР В Р’В Р В РІР‚В Р В Р’В Р Р†Р вЂљРЎв„ўР В Р Р‹Р РЋРІвЂћСћ`007`, rewrite smells
  such as a Bool match that returns or negates its scrutinee, identical arms,
  eta-expanded lambdas, double `notb`, constant `andb`/`orb` operands, and
  rewrap identities), `--enable-perf` (`OURO-PERF001`Р В Р’В Р вЂ™Р’В Р В Р’В Р Р†Р вЂљР’В Р В Р’В Р вЂ™Р’В Р В Р вЂ Р В РІР‚С™Р РЋРІвЂћСћР В Р’В Р В РІР‚В Р В Р’В Р Р†Р вЂљРЎв„ўР В Р Р‹Р РЋРІвЂћСћ`005`, literals rebuilt
  inside a fix, quadratic accumulator appends, `length` used for emptiness,
  repeated conversions, strict boolean operands), `--enable-naming`
  (`OURO-NAME001`Р В Р’В Р вЂ™Р’В Р В Р’В Р Р†Р вЂљР’В Р В Р’В Р вЂ™Р’В Р В Р вЂ Р В РІР‚С™Р РЋРІвЂћСћР В Р’В Р В РІР‚В Р В Р’В Р Р†Р вЂљРЎв„ўР В Р Р‹Р РЋРІвЂћСћ`004`, read discards, one-character and capitalised value
  definitions, lowercase constructors), and `--enable-errors`
  (`OURO-ERR001`Р В Р’В Р вЂ™Р’В Р В Р’В Р Р†Р вЂљР’В Р В Р’В Р вЂ™Р’В Р В Р вЂ Р В РІР‚С™Р РЋРІвЂћСћР В Р’В Р В РІР‚В Р В Р’В Р Р†Р вЂљРЎв„ўР В Р Р‹Р РЋРІвЂћСћ`003`, `Either String` results, failure arms answering with a
  success, `io_bind` over an `Either` bound to a discard). Each code has bad
  and good fixtures with goldens under `tests/analyze/`. Semantic,
  metrics, and duplication join the same promoted set.

### Changed

- The compiler-owned Ouro checker is the sole program-acceptance path.
  OCaml/Dune/opam and independent Python Core replay are retired. Retained
  semantic laws, generated properties, source fault injection, and bounded
  scale/depth probes run against the canonical checker.
- Build configuration rejects retired Dune options, `--c-only`, and `--frontend`; use plain
  `build`. Replace `trust.kernel` with `trust.compiler` and remove `build.dune`
  and `cache.dune` from project seals. The `kernel` CI profile keeps its name
  and runs the compiler-owned checks. C bootstrap and host scripts remain.
- A clean C bootstrap builds a historical bridge from versioned, hashed inputs,
  then strictly checks current sources before building P1 and P2. Publication
  requires compiler ABI laws, positive and negative behavior checks, and complete
  generated-C equality. Current sources are never projected for the old seed;
  committed stage0 inputs remain unchanged.

- Adopted the native Ouro transition contract: compiler-owned checking, direct
  Windows x86-64 executable generation, an Ouro runtime with garbage collection,
  and native bootstrap/build tooling. This records the target architecture;
  current C implementations and required validation remain until working
  replacements satisfy their contracts.
- The generated-C runtime uses less memory without giving up parallelism.
  Each value is one 24-byte cell (was 48): constructors keep up to two fields
  inline and larger field lists directly after the cell, nullary constructors
  and small nats are interned, and `ouro_app`/`ouro_case` reclaim a single-use
  closure or thunk the moment it is consumed. `native-check-fmt` peak RSS fell
  from about 2.0 GiB to 0.59 GiB and `native-check-analyze` from about 4.56 GiB
  to 1.23 GiB on the sampled host; their `quality/memory_budgets.json` rows drop
  to 1.1 GiB and 2.2 GiB. Handwritten hosts that reuse a closure call the new
  non-reclaiming `ouro_apply`. Stage-loop output is byte-identical.
- `scripts/frontend_regen.py` caps its parallel emit pool to available RAM.
  A healthy host keeps its full `OURO_FRONTEND_JOBS` count; a memory-starved
  host is throttled toward one worker instead of being pushed into OOM.
  `OURO_FRONTEND_WORKER_MB`, `OURO_MEM_RESERVE_MB`, and `OURO_MEM_AWARE_JOBS`
  tune or disable the cap.
- Build parallelism defaults to 10 workers: `Ouro.seal` `build.jobs`, CI
  `OURO_JOBS`, `ci_gate.py`, and the frontend-regen fallback. Analyzer and
  lint walks stay one process per file.
- The public site lives in `site/` and is published by
  `.github/workflows/ouro-pages.yml` to `https://eluvane.github.io/ouro/`. A
  later custom domain should rebuild with `SITE_BASE=/`.
- Host-bound inventory now includes `scripts/frontend_security_suite.sh`, which
  was already a PR gate but missing from the script inventory.
- Release version parity requires nonempty matching versions in `Ouro.seal`
  and both VS Code package files. The project gate requires `Ouro.seal` and
  `scripts/coil.sh` and rejects retired project manifests.
- Project and package identity now live in `Ouro.seal`, a small `seal 1`
  block language. It replaces `ouro.toml` / `ouro.ourocfg` for build and cache
  defaults and `ouro.pkg.json` for package manifests. The resolved lockfile is
  `Ouro.lock`. `scripts/coil.sh` is the project-facing frontend for `ouro1`
  and `ouro1 pkg`; `trust {}` in the seal is declared intent, not compiler
  acceptance.
- `ex_falso` in `std/logic.ouro` names its `Empty` argument `e` instead of
  `_e`, because the binder is the match scrutinee.
- `path_under` and `path_relative` now require a `/` boundary after the root,
  so `"a"` is not treated as a parent of `"apple"` and `"/tmp"` is not a parent
  of `"/tmpfoo"`.
- `tablex_project_required` now validates required columns against an empty
  table instead of succeeding when no header row is present.
- `render_request` refuses methods or targets that contain CR or LF, so a
  request line cannot inject extra HTTP headers.
- The bounded JSON parser now rejects malformed numbers (`--1`, `1.2.3`, `01`,
  a trailing dot) and unknown string escapes instead of accepting them.
- `fsx_remove_tree_checked` now deletes nested files and directories instead of
  only attempting a single `remove` on the root.
- HTTP response header parsing no longer drops malformed lines; a bad header
  makes `parse_response` report `unparsed` instead of a partial 200-class
  message.
- Native lint now reports `preprocess-import` / `preprocess-record` and fails
  instead of silently linting the raw source after a preprocess error.
- Native lint treats a pattern slot that names a constructor in scope
  (`MkT n True _`) as a refinement instead of a binder, so such slots no longer
  report `unused`, `shadow`, or `dup-binder`, and a refined arm no longer makes
  a later general arm `unreachable-arm`. Constructors harvested from the import
  cone count as in scope.
- Native lint checks each column of a multi-scrutinee `match a, b with` for
  arity, coverage, and unknown constructors, and reports whole rows that are
  covered by an earlier row (`redundant-branch` / `unreachable-arm`).
- Native lint now lints handler clause bodies: holes, unbound names, unused
  clause binders (including an unused continuation), and shadowing inside
  `handle ... with | op (x) k => ...` are reported.
- `ouro1 lint` peak memory per file dropped by roughly an order of magnitude
  (a 4 KiB `std` file went from over 1.5 GiB to about 0.3 GiB; a 9 KiB file
  from several GiB to under 0.5 GiB). The import-cone harvest now splits and
  strips lines through host string primitives and no longer re-harvests the
  linted file once per known name, warning positions come from a host byte
  search instead of a per-warning code-list walk, `module` expansion is linear,
  and the lint core stops at the first hit when it tests binder use or
  membership. Output is unchanged; the frontend lexer and preprocessor now
  dominate what remains.
- `table_cell` now returns `Nothing` when a row is shorter than the named
  column instead of inventing an empty string.
- A trailing `--option` without a value is no longer recorded as a boolean
  flag; `cli_required` can report the missing option.
- Host-bound CI report validation parses the JSON object instead of accepting
  a substring match that could see `"pass":true` in an issue string.
- `parse_status_line` now returns `Nothing` when the status code is not a
  natural number, so `parse_response` reports `unparsed` instead of HTTP 0.
- `ouro pkg verify` treats checker output that contains `CHECK_FAIL` as a
  failed verification even if `CHECK_OK` also appears.
- HTTP POST uses the checked native WinHTTP intrinsic instead of `curl` and
  temporary body files. Responses retain status and binary body; transport
  failures have status zero and a reason, and response headers remain empty.
  The transitional C host has no HTTP transport implementation.
- The bootstrap and CLI file readers now close the `FILE` and free the
  buffer on size, allocation, and short-read failures instead of exiting
  while they are still open.
- Moved repository manifest, formatter, documentation, lines, native lint,
  runtime, test, sample, quickstart, and control-plane fixture policy into
  Ouro-native tools; retained shell only for bootstrap, compiler, stdin,
  bounded host-process sequencing, and compatibility edges.
- Removed obsolete manifest, environment, rebuild, quickstart-clone, parser
  split, and three uncalled selfhost hot-path helper scripts.
- Removed the shell byte-share metric script; it was not a blocking gate and
  had no caller besides its own self-checks.
- Removed the stale quality-bootstrap payload and branch-specific write workflow
  from the tracked public tree.
- Packaged checking validates the complete ordered declaration closure before
  extraction, including imported bodies and effect roots. Typed failures
  preserve type errors, malformed input, resource limits, unsupported
  features, cancellation, and internal failures.
- `std/char.ouro` `is_ident_cont` now treats `'` as an identifier character,
  matching the lexer and primed binders such as `x'`.
- `ouro pkg list` and `ouro pkg verify` now reject an unreadable lockfile
  instead of treating invalid JSON as an empty package list.
- `ouro doc` now exits nonzero when a source file or `--files-from` list
  cannot be read, instead of generating empty documentation pages.
- Reorganized the public documentation around user, contributor, maintainer,
  and automation audiences.
- Replaced the root README with a compact language overview, runnable example,
  current-status statement, quick start, and canonical navigation.
- Consolidated quality, diagnostic, lint, migration, repository-health,
  memory, and kernel-ownership material into their canonical documentation.
- Simplified issue forms and the pull-request template to request only
  actionable information.
- Kept the roadmap strategic rather than using it as a completed-task log.
- Moved common byte-string search, split, replace, comparison, and token
  operations to host primitives so Ouro-native tools stay within their enforced
  memory budgets.
- Runtime file writes now reject symlink and reparse-point destinations,
  preventing LSP scratch writes from being redirected to another file.
- Release packaging now rejects tracked symlinks and reparse-point paths before
  building source archives, preventing linked host bytes from entering assets.
- The compiler now rejects malformed or fuel-exhausted source before parsing
  and restricts `--module` to a C-identifier suffix grammar.
- Package installation now validates portable package identities, canonical
  registry containment, link/reparse safety, and complete typed source walks.
- The LSP now confines documents/imports to its canonical workspace root,
  bounds frames and retained text, and uses exclusive disposable scratch files;
  the VS Code client requires an explicit trusted machine command.
- Native process capture no longer uses predictable shared filenames, and JSON
  string decoding is linear and non-recursive.
- Workflow policy now parses a strict owned YAML subset, so comments, duplicate
  keys, flow syntax, aliases, and unrelated release markers cannot satisfy
  security requirements.
- The structured analyzer families (`--enable-effects`, `--enable-capability`,
  `--enable-extract`, `--enable-match`) run on the real compiler frontend
  (`tools/analyze/unit.ouro`: `preprocess_records`, `lex_all`, `parse_file`,
  then `expr_adapt` per definition) instead of the token walker
  `surface.ouro`. Drive diagnostics now use the main runner format
  (`path:line:col: severity[CODE] family/rule: message` with hint and witness),
  are sorted and deduplicated, and `ANALYZE_OK` is printed only when both the
  base runner and the drive are clean. The drive banner is
  `ANALYZE_DRIVE files=N findings=N rejected=N families=...`; a source the
  frontend cannot parse is reported as rejected, not as clean.
- The per-file limit for structured analyzer profiles rose from 12 KiB to
  40 KiB, which covers every production source; the memory budget suite
  measures the drive on the largest one (`analyzer-drive-largest-file`).
- `sh scripts/analyze_precision_suite.sh` compares every pipeline fixture run
  with its golden line by line and accepts `--regen`; capability, extract, and
  match fixtures gained goldens and manifest entries.
- The structured drive runs every analyzer core in `tools/analyze/` on the
  shared `ast.ouro`: `--enable-cfg`, `--enable-dataflow`, `--enable-semantic`,
  `--enable-property`, `--enable-absint`, `--enable-symexec`, `--enable-taint`,
  `--enable-contracts`, `--enable-metrics` (complexity, `@bound`, `@minimal`),
  `--enable-duplication`, and `--enable-trust` join the existing four, with
  `--enable-light`, `--enable-heavy`, and `--enable-all` as unions. Taint
  sources and sinks come from `-- ouro-analyze:source=`/`sink=` comments plus
  the fixed primitive list, contracts from `@requires`/`@ensures`/`@modifies`/
  `@pure` annotations, metric limits from `@bound(metric <= n)`. The codes
  `OURO-ABS002`, `OURO-ABS003`, `OURO-SYM001`, `OURO-SYM003`, `OURO-CTR001`,
  `OURO-CTR004`, and `OURO-CTR005` are registered, and every structured family
  has bad and good fixtures with goldens under
  `tests/analyze/`.
- The base runner (`ouro-analyze`) reports architecture, dead code,
  suppressions, API surface, and trust through the `tools/analyze/` cores
  only; `tools/analyze/policy.ouro` adapts facts and no longer carries a second
  implementation. `OURO-API002` (duplicate public API), `OURO-API004`
  (internal-only public definition), `OURO-DUP001`/`002` (through
  `duplication.ouro`), and `OURO-TRUST002`Р В Р’В Р вЂ™Р’В Р В Р’В Р Р†Р вЂљР’В Р В Р’В Р вЂ™Р’В Р В Р вЂ Р В РІР‚С™Р РЋРІвЂћСћР В Р’В Р В РІР‚В Р В Р’В Р Р†Р вЂљРЎв„ўР В Р Р‹Р РЋРІвЂћСћ`005` (through the drive's effect
  and taint facts) are emitted for the first time. Dead-code roots are entry
  and public-API declarations; an `@export` alone is no longer a root, so
  `--enable-deadcode` reports an export nothing in the scope reaches as
  `OURO-DEAD002` instead of treating it as live.
- `--enable-strict` enables the structured families that report nothing on the
  production tree (effects, capability, extract, match, cfg, dataflow,
  property, absint, symexec, taint, contracts, trust). The nightly and manual
  CI profiles run the new `analyze-production` gate
  (`scripts/analyze_production_suite.py`, policy in
  `quality/analyze_production.json`): it sweeps `std/`, `compiler/`,
  `tools/analyze/`, `tools/`, and `samples/`, fails on any finding from that
  set or on a frontend rejection the policy does not list, and counts the
  findings of every other family per code for triage. Default `--strict` still
  runs only the base runner.
- Triage of the production sweep removed these false positives from the cores:
  `OURO-CFG003`/`004` on multi-scrutinee matches and on recursion guarded
  through a `let`-bound scrutinee, `OURO-CFG002` on the `refl` arm of an indexed
  family, `OURO-CFG001` on a branchless match over an uninhabited type,
  `OURO-SYM003` when a pattern-bound name shadows a parameter, `OURO-BND001`
  when several `@bound` claims share one comment line, `OURO-CTR001` on a
  `@tag` written inside a comment sentence, `OURO-DF001` on a type
  parameter read only by the declared return type, and `OURO-SEM005` on
  parameters whose source name starts with `_`. Each has a `good` fixture.
- `ouro1 lint` no longer treats a multi-scrutinee arm body as an application
  of the next row, so `OURO-LINT021` does not fire on `True`/`False` returns
  and later arms do not look like they shadow earlier binders.
- The C runtime's `list_reverse` reverses packed byte lists (the representation
  `prim_string_to_char_codes` returns) instead of returning an empty list;
  `runtime/ouro_io_selftest.c` covers it. The runtime stays outside the pure
  compiler checker.

### Removed

- `--enable-lint` from `ouro1 analyze`; `OURO-LINT001` is reported by
  `ouro1 lint`. The `ANALYZE_FACTS` banner no longer carries `lint=` or `pcc=`
  tokens.
- From `tools/analyze/`: the `surface.ouro` token walker, `abi.ouro`
  (duplicate of `OURO-API003`), `pcc.ouro`, `demo/`, every `*.ouro.pcc.json`
  certificate, the `OURO-PCC001` registry row, and the analyzer README PCC
  contract. The certificate generator was already gone and the certificates
  were stale.
- The analyzer fact-smoke fixtures under `tests/analyze/` (the old
  `fixtures` tree and the `hole.txt` golden), which no suite executed, together
  with the `Fact`/`Norm` emitters `emit_facts.ouro`, `match_facts.ouro`, and
  `fact_model.ouro` they were written for; every family is covered by a
  pipeline fixture with a golden. The twelve per-core copies of `Ast`, the text
  heuristics for cfg, dataflow, effects, property, taint, and contracts in
  `tools/analyze/families.ouro`, the `families_holes.ouro` hole scan, and the
  host implementations of the policy families in `tools/analyze/policy.ouro`
  are gone as well.

### Current compatibility

- Ouro remains pre-1.0; syntax, standard-library APIs, CLI behavior, package
  files, and editor integration may change.
- The compiler-owned Ouro checker decides program acceptance; no complete
  formal correctness proof is claimed.
- The C producer/runtime and host build scripts remain transitional
  dependencies. Caches, analyzers, and generated artifacts do not authorize
  unchecked declarations.

## [0.1.0]

- Initial development baseline for the Ouro language, kernel, bootstrap path,
  standard library, samples, and repository tooling.

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
