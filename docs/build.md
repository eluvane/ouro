# Build and bootstrap

Use the Python build driver to build the transitional C bootstrap and manage
its content-addressed caches. The checker runs as an Ouro program.
[Getting started](getting_started.md#build-the-bootstrap-toolchain) covers the
first build. Active builds and validation no longer require OCaml, opam, or
Dune.

## Entry points

Run build and inspection commands from the repository root with the
[source-build prerequisites](getting_started.md#requirements). The build
installs the compiler in the configured C output directory and records
bootstrap evidence in the configured build directory. The other commands
report cache state and resolved configuration.

```sh
python3 scripts/ouro_build.py build
python3 scripts/ouro_build.py cache status
python3 scripts/ouro_build.py config show
```

Before cleaning, run `config show` with the same configuration and path
overrides as the intended command. Keep the cache outside both build output
directories and keep both build output directories outside the cache. Keep
files you need outside all cleanup targets.

| Command after `python3 scripts/ouro_build.py` | Effect |
| --- | --- |
| `rebuild` | Removes the configured C build directory, then builds with the existing cache. |
| `clean` | Removes the configured build directory and keeps the cache. |
| `cache clean` | Removes the configured cache directory. Later builds must recreate its contents. |

For artifact updates, follow the [stage-loop procedure](#generated-artifacts-and-stage-loop).

`scripts/ouro1.sh` remains the user-facing wrapper for language and tooling
commands. `scripts/coil.sh` is the project-facing name for the same toolchain.

On Windows, the C bootstrap and C-hosted tools read arguments from the wide
command line and convert them to UTF-8. Bootstrap file opens, checked file reads,
and file/directory probes convert UTF-8 paths to Windows wide paths, including
Unicode source filenames and imports. Invalid encoding is rejected; checked
path inputs also reject embedded NUL bytes. The compatibility wrapper forwards
each collected path as one literal argument, preserving spaces and wildcard
characters. POSIX retains byte paths and argv.

macOS host executables reserve a 256 MiB main-thread stack at link time through
Mach-O's `-stack_size`, including historical bootstrap producers. This reserve
does not depend on changing the stack of the host Python interpreter.
The C IO host enables Darwin's extended declarations so no-follow file writes
retain `O_NOFOLLOW` under the POSIX feature flags. Clang allows bracket nesting
up to 1024 for generated constructor expressions. The selected flag is part
of the object-cache command key.

The frontend regenerator, bounded analyzer, and fix-check observer try to
raise the POSIX soft stack limit to 128 MiB, up to the inherited hard limit.
Standalone C IO programs make the same adjustment at startup because ELF
provides no link-time stack reserve. They keep a larger or unlimited soft
limit and continue with the inherited limit if the operating system rejects
the adjustment. Address-space and memory-budget limits still apply.

## Native transition baseline

This historical record describes recovery revision
`8ee4a175828f7eb803ca71f19bbd4c24de9b91b1` on 2026-09-06. Use a checkout of
that revision to reproduce the baseline commands. They require the checker
tools and build flags from that revision. The native release seed is a
separate artifact. The revision records these C bootstrap input digests in
`docs/generated_artifact_hashes.sha256`.

| Bootstrap input | SHA-256 |
| --- | --- |
| `compiler/stage0/driver_u.c` | `200d75373e0b833dfdc22d3d73090e3cb32c897921a40486a55f4b157001a854` |
| `compiler/stage0/backend_u.c` | `c9a6c4b639ba6c5af7b2e611f1a50a2eb08d6b3753e864acc766c32e284169cf` |

The observed host was Windows 11 Pro 10.0.26200, x86-64, with an Intel
Core i5-14600KF (14 cores, 20 logical processors) and 34,187,538,432 bytes of
reported physical memory. Tools were Python 3.11.14, MinGW GCC 13.2.0,
opam 2.5.2, Dune 3.24.0, and OCaml 5.3.0. OCaml was selected through opam;
shell and differential commands used Git Bash's executable search path.
For the shell invocations, `PYTHON` selected that Python 3.11.14 executable.
Compilation used two workers and frontend generation one worker.

The cold C-bootstrap command uses fresh output directories and disables caches:

```sh
python scripts/ouro_build.py build --c-only --jobs 2 --no-cache \
  --c-build-dir _build/native-transition/baseline/c \
  --cache-dir _build/native-transition/baseline/cache \
  --build-dir _build/native-transition/baseline/build
```

The warm comparison enables caching and reuses the same directories:

```sh
OURO_JOBS=2 OURO_FRONTEND_JOBS=1 \
sh scripts/bootstrap.sh --jobs 2 \
  --c-build-dir _build/native-transition/baseline/c \
  --cache-dir _build/native-transition/baseline/cache \
  --build-dir _build/native-transition/baseline/build
```

The cold and warm samples each ran once. Their elapsed values are from the
driver's `BUILD: OK` log, not end-to-end process wall time:

| Observation | Result |
| --- | --- |
| Cold C bootstrap | Exit 0; 36 compiled objects, one link; reported elapsed time 16.944 seconds. |
| Warm C bootstrap | Exit 0; no compiled objects or links; reported elapsed time 0.413 seconds. |
| `sh ./scripts/dune.sh runtest` | Exit 0. |
| Kernel differential command below | PASS; 26 fixtures, 67 compared declarations, zero abstentions and issues. |
| Stage-loop command below, without promotion | Exit 0; PASS; stage1 and stage2 emit identical frontend and backend C artifacts. |
| Frozen compiler-source check | 51 roots: 36 accepted (exit 0), 15 rejected (exit 1). |
| Frozen surface regression check | 32 cases: 23 expected outcomes; nine invalid inputs incorrectly accepted. |

The source and surface counts above describe revision
`8ee4a175828f7eb803ca71f19bbd4c24de9b91b1`. Each of its 51 top-level
`compiler/*.ouro` roots received one `check` invocation with fuel `16000`, its
ordered `--unit` import closure, and a 3 GiB process-tree limit. Every process
completed with status `ok`; the 15 rejections were not skips or timeouts. The
frozen revision therefore does not pass checking of its entire compiler source.
The nine incorrect acceptances covered self-reference, effect declarations,
and direct or transitive imports with invalid bodies, assumptions, or positivity.
The local evidence is in `baseline/compiler-sources/report.json` and
`baseline/surface-regressions/report.json` under `_build/native-transition/`.

```sh
sh ./scripts/dune.sh runtest
python ./scripts/kernel_differential_gate.py \
  --work _build/native-transition/baseline/kernel-differential \
  --report _build/native-transition/baseline/kernel-differential.json
```

For the historical non-promoting
[stage-loop invocation](#generated-artifacts-and-stage-loop), set
`OURO_BUILD_DIR=_build/native-transition/baseline/build`,
`OURO_C_BUILD_DIR=_build/native-transition/baseline/c`,
`OURO_CACHE_DIR=_build/native-transition/baseline/cache`, `OURO_JOBS=2`, and
`OURO_FRONTEND_JOBS=1` in that archived checkout.

The stage-loop report is
`_build/native-transition/baseline/build/stage_loop/result.json`. The compared
frontend C output is 4,653,809 bytes with SHA-256
`c872566d86cd38496267eaf5fb961b31d525d698616a5318985a31a5a17b5e22`;
backend C output is 2,093,214 bytes with SHA-256
`aa61a7886c9c852bb2f809da6b3659a926f73d025de9e62332c12059395a0adf`.
This establishes a C-artifact fixpoint; native executable stage equality
requires separate evidence. No generated artifacts were promoted.

Small program and LSP measurements used the same frozen sources and runtime.
Each tool received one uncached build and three fresh process launches, with
one worker, affinity to one logical processor, and a 3 GiB process-tree limit.
The operating system's file cache was not cleared. Builds emitted C with the
frozen compiler at fuel `60000` and the ordered import closure from
`scripts/frontend_regen.py:collect_units`, ran
`scripts/pack_frontend.py --uniquify-only`, then linked the three runtime files
`ouro_rt.c`, `ouro_io.c`, and `ouro_prog_main.c`. GCC flags were `-O1 -std=c99
-D_POSIX_C_SOURCE=200809L -Werror=implicit-function-declaration`, with the runtime
include directory and `-Wl,--stack,134217728`.

These are end-to-end process-tree wall times, including the limit launcher's
startup. Peak RSS is the sum of sampled Windows working sets, requested every
10 ms; it excludes the Python limit launcher and includes compiler, linker,
shell, and checker children. Short peaks can escape sampling. The build column
covers emission, packing, and linking; it excludes building the bootstrap seed.

| Frozen entry | Generated C bytes | Build seconds / peak RSS MiB | Three-run range, seconds / peak RSS MiB | Result |
| --- | ---: | ---: | ---: | --- |
| `tools/collect.ouro` | 727,164 | 7.760 / 292.637 | 0.105–0.188 / 44.539 | 3/3 exact dependency lists |
| `tools/fmt.ouro` | 1,029,311 | 20.643 / 291.516 | 0.073–0.135 / 18.512 | 3/3 exact formatted outputs |
| `tools/lines.ouro` | 783,299 | 8.555 / 292.699 | 0.088–0.120 / 19.297 | 3/3 exact summaries |
| `tools/lsp.ouro` | 1,138,113 | 11.913 / 293.504 | 1.927–2.064 / 75.477 | 3/3 complete sessions |

The collector input was
[`samples/examples/workflow_json_table_transform.ouro`](../samples/examples/workflow_json_table_transform.ouro),
including its 25-unit closure. Formatter input and golden output came from
[`text_contracts.py`](../scripts/ourosmith/surface/text_contracts.py), case
`fmt-layout`, seed `0`. The lines command was `--summary --contains Ouro
README.md docs/tooling.md` against the frozen files: two files, 468 lines,
18,710 bytes, and 14 matching lines.

LSP used the seed-0 document recipe in
[`native_inputs.py`](../scripts/ourosmith/native_inputs.py) and the framed stdio
protocol in [`lsp_suite.sh`](../scripts/lsp_suite.sh). Each session initialized,
opened a valid buffer, changed it to an unknown-name error, restored it, closed
it, and shut down. Assertions required the full-sync capability, four ordered
diagnostic notifications (empty, `CHECK_FAIL`, empty, empty), matching URI,
shutdown response, empty stderr, exit 0, and scratch-file removal. Checking
used the frozen `scripts/ouro1.sh`, collector, and compiler with fuel `16000`.
Git Bash must be able to create its process pipes: three preceding sandboxed
sessions could not launch the driver and emitted empty diagnostics for the
invalid buffer; those failed runs are excluded from the successful range.

The measurement driver and raw reports were local artifacts. The reports
recorded command arguments, input and output hashes, file sizes, per-run
results, timeouts, and job committed-memory peaks. Reproducing the published
measurements requires reconstructing the workload from the revision,
fixtures, and build and process settings above.

These bounded samples do not establish sustained memory behavior, an extended
editor session, or a native seed. The retained language/runtime scope is listed in
[Design](design.md#retained-slice-and-experimental-limits). Record further
performance evidence with exact hardware, input, cache mode, and repetitions;
build-driver elapsed time and end-to-end wall time are different measurements.
Local reports under `_build/` remain uncommitted outputs.

## Host-bound build boundary

The build and bootstrap path is still host-bound. `scripts/bootstrap.sh`,
`scripts/build_tool.sh`, `scripts/ouro1.sh`, and `scripts/stage_loop.sh` are not
removable until an Ouro-native replacement can build the required binaries,
preserve the trust boundary, and pass the same focused parity checks.
Windows producer links reserve a 2 GiB PE stack (`-Wl,--stack,2147483648`) so
the native-build import cone can be checked and emitted. Native PE images write
the same 2 GiB `SizeOfStackReserve`; the previous 1 MiB default overflows on
that cone. On POSIX, the [host stack adjustments](#entry-points) aim for
128 MiB while respecting the inherited limits.

Native-build output publication stages the image in a private file beside its
destination, reads it back, compares every byte, and performs a same-volume
rename with replacement. A refused replacement returns an error and preserves
the previous output. The publisher checks staging cleanup on recoverable
failures; fatal runtime errors or interruption can leave the staging file.
Readback requires a full image buffer. This path does not provide power-loss
durability, native cache transactions, or isolated-host bootstrap evidence.
See [the runtime contract](effects_design.md#runtime-surface) for rename errors.

The [host-bound inventory](native_repo_gates.md#compatibility-and-host-reference-boundaries)
records each Python and shell path's migration status, replacement, blocker,
and evidence. Build, cache, stage-loop, compiler-measurement, hosted-network,
memory-observer, and release paths remain host-bound until their exact
capabilities and trust evidence exist natively. Do not delete a build script
merely because a downstream native gate exists.

### Native transition dependency owners

The [native transition](design.md#native-toolchain-contract) replaces the
functions below before removing their implementations. Daily use, CI, and
bootstrap have different dependency graphs; a dependency optional for ordinary
checking may still be required by release validation.

| Current owner and callers | Role today | Replacement and removal condition |
| --- | --- | --- |
| Compiler checker and typed semantic suites | Program acceptance, retained laws, generated cases, scale and depth checks | OCaml/Dune/opam and independent Python Core replay are retired. Host supervision of these Ouro tests remains until the native control plane implements its required contracts. |
| `compiler/backend.ouro`, `compiler/print_c.ouro`, `compiler/stage0/`; build/tool/stage drivers invoke a C compiler | Program builds, compiler bootstrap, and CI | Direct native code generation and executable writing for the retained slice, plus reproducible native successor stages, before C emission and generated C seed are removed in P9. |
| `runtime/ouro_rt.c/.h`, `ouro_io.c/.h`, `bootstrap.c`, `frontend_link.c`; generated programs and split frontend | Values, closures, primitive fast paths, allocation, process entry, IO, and frontend result lifetimes | Ouro runtime, working GC, platform/startup APIs, primitive implementations, and lifecycle tests before P5–P9 retirement. |
| `scripts/ouro_build.py`, frontend regeneration/packing, `stage_loop.py/.sh`, and build/CLI shell launchers | Daily build orchestration, cache handling, regeneration, bootstrap comparison | Native module/build driver and rebuild-and-compare command, with matching errors, determinism, and cache-independent behavior in P7–P9. C sharding need not survive when C output disappears. |
| Python/shell CI, quality, memory, and release scripts; native gate launchers still use host build machinery | Required repository and release validation | Implement the useful checks in Ouro, migrate every active caller, and preserve strict failures before P8–P9 removal. Existing native policy subsets do not establish full parity. |
| `ccache`; C build/cache driver | Optional compilation accelerator | Remove C-specific discovery, flags, and configuration after the native cache owns retained cache behavior and there are no C consumers. |
| WinHTTP from `std/http.ouro` | Experimental native Windows HTTP POST; the C host has no HTTP transport | Retained response/error behavior and isolated native execution evidence before P8 acceptance; `curl` and shell-body staging are no longer request owners. |
| Windows `Sleep` from `std/async.ouro` | Sequential native delays | Full `Nat` seconds are consumed as finite one-second OS waits; no host command is used. Native timing, sequencing and failure evidence remain required. |
| Git, CI runner, signing tools; Node for `site/` and editor extensions | Source/release environment and separate integrations | Remain external environment; they must not provide hidden compiler, runtime, or required native CLI/build semantics. |

## Configuration

Project defaults live in [Ouro.seal](../Ouro.seal) under the `build` and `cache` blocks.
See [Packages](pkg.md) for the seal syntax. Configuration precedence is:

```text
command line > environment > project configuration > built-in defaults
```

The parser accepts `project`, `build`, `cache`, `deps`, `registry`, and `trust`
blocks and rejects unknown blocks or keys. Remove the retired `build.dune`
and `cache.dune` keys from older projects. Trust-key migration and the meaning
of declared trust are covered by [TCB](tcb.md).

The build driver configures the profile, parallelism, C compiler, optimization,
build and cache directories, optional `ccache`, verbosity, and reproducibility
mode. `--c-only`, `--frontend`, `--dune`, and the Dune cache flags are retired; plain `build`
selects the current C producer without discovering OCaml tools. Run `config show` to see the effective values.
The repository and build-driver default is `auto`. Override it with
`--jobs` or `OURO_JOBS`; hosted PR jobs set `OURO_JOBS=2`.

Compiler and native tool builds can use the same cache concurrently. LRU
cleanup runs when that cache has no active build. If permissions prevent
eviction of an entry, automatic cleanup reports it and tries other entries.
`cache clean` waits for active builds to finish before removing the cache.

The transitional compiler bootstrap runs C0, bridge, bridge2, P1, and P2
in order. Inside each stage, C builds and split frontend generation use the
configured worker count. `--jobs 19` requests at most nineteen workers for
each parallel step. `auto` resolves the host CPU count once and freezes that
request. Before
each parallel step, bootstrap caps the request to currently available physical
memory and fits within any allocation from the local scheduler. It reserves
512 MiB per additional C worker and 1 GiB per additional frontend worker.
Concurrent source checks use a shared Windows job budget. On POSIX each check
reserves its full 3 GiB allowance. The frontend retains memory-aware pool
throttling. `--jobs 1` retains serial execution.

Independent source checks run in parallel, with one CPU slot per check. P2
combines compiler and acceptance source checks in one group. The coordinator
writes results in source order and waits for the checks before starting emission.
After that barrier, the P2 ABI build and successor generation can use concurrent
lanes when the shared CPU and memory budget can fit both. ABI laws run after the
checks and the ABI build. Report rows and the first reported failure keep the
serial order of checks, ABI build and laws, frontend, backend, and link. Stage
barriers remain serial. Frontend tasks start with
the largest source closures; C compilation starts with the largest input files.
Generated frontend modules over 1 MiB compile as pieces of about 512 KiB; a
module with an unrecognized generated layout compiles whole and is listed in
the shard report's `frontend_split_fallbacks`.
Packing, linker inputs and report rows keep their original order.

Every source check and serial command retains its 3 GiB memory limit and
900-second timeout. On Windows, each parallel step also has a shared
process-tree commit limit of 3 GiB plus the planning estimate for each
additional worker. Nested jobs retain the individual source-check limits
inside that shared budget. Concurrent emission and ABI build share the phase
allocation. The report's `requested_workers` field records the
frozen request; `workers` and `parallel_memory_mib` record the initial selection.
Command rows record `workers`, `memory_mib`, `started_s` and `finished_s`, with
`shared_memory_mib` for parallel source checks. The bootstrap report includes
elapsed time, peak concurrent commands and peak allocated worker slots.
POSIX retains the inherited 3 GiB address-space limit per process except on
Darwin, which rejects finite `RLIMIT_AS`; it has no shared Windows Job budget.
On Linux, parallel bootstrap reserves 8 MiB per Python worker thread stack.
The launcher still provides the native stack allowance to compiler subprocesses.
Standalone tool and stage-loop builds retain their configured worker counts.

## C bootstrap

Use `OURO_C_BUILD_DIR` for the compiler output directory. For wrapper and tool
commands, `OURO1_COMPILER` selects an existing compiler. The bootstrap driver
builds its producer chain from the pinned inputs described below.
The unreferenced `OURO1_OUT_DIR` and `OURO1_OUT` aliases
are retired. `ouro_build.ensure_fe_link` owns frontend-linker emission;
the standalone `gen_fe_link.py` copy is retired.

The C path compiles each source to an object and links the resulting objects:

```text
.c -> .o + dependency file + command hash -> executable
```

Object identity includes the source, dependencies, compiler identity, flags,
profile, and reproducibility mode. Missing or malformed dependency metadata is a
cache miss, not a successful build.

C build callers may append flags for an exact source label. Unknown labels fail
before compiler invocation. These flags remain in the object's command and
content key; the source report links to that command stamp. The frontend host
suite applies its required module-scope selftest define only to that main, so
the six targets can reuse unchanged common objects within their fresh build.

Use the [source-build prerequisites](getting_started.md#requirements) with
`scripts/bootstrap.sh` or `ouro_build.py build`. The source tree includes the
bootstrap inputs, so the build can run offline without Git history or an
installed Ouro compiler. The driver performs five stages.

1. Compile the committed `compiler/stage0/` C with its matching pinned
   runtime to obtain C0.
2. Use C0 to build the first historical Ouro bridge and its matching runtime
   from `compiler/bootstrap/c-bootstrap-v1.tar.gz`.
3. Use the first bridge to check all 15 roots from `bridge2-v1.tar.gz` and
   report the results in the recorded root order. Build the second historical
   bridge (bridge2) after those checks pass. It supports private declarations
   and their module scopes.
4. Copy the current compiler, stdlib, tool inputs, and runtime into a separate
   private snapshot, without source transformations. The second bridge must
   strictly check all 15 current compiler roots and their ordered import
   closures before building current P1.
5. P1 repeats those checks, checks `std/prelude.ouro`, `std/data.ouro`,
   `tools/collect.ouro`, and `tests/compiler_abi_tests.ouro` with their closures,
   builds and executes the ABI laws, and emits P2 from the same current
   snapshot. P2 is not executed before those checks and laws pass.
   Full frontend and backend C must match between P1 and P2. P2 must
   also pass the positive and exact negative String-index checks before it is
   published as the current compiler.

Release builds use `--compact-sources` to emit P2 from a separately checked
compact copy while retaining P1's original inputs. The transformation, equality
checks, and evidence are specified in [Canonical source](canonical_source.md#materialization).

The String-index probes use the frozen, ordered import closure of
`std/data.ouro`, including its transitive dependencies. They do not maintain a
second handwritten stdlib unit list; missing units remain bootstrap failures.

The [bootstrap input manifest](../compiler/bootstrap/c-bootstrap-v1.json) records
68 input files: 58 historical Ouro sources and two five-file runtime sets. It
pins every file's size and SHA-256, the archive, and the committed stage0 pair.
The C0 runtime matches that seed. The manifest's `syntax_refresh` records the
reviewed parser backport that lets the bridge read current
[ergonomic syntax](language/ergonomic_syntax.md), with its patch and member hashes.
Its `lowering_refresh` records the composed Nat/ascription lowerer update with
the exact source slices, original-to-Nat-to-ascription patches, and member hashes.
The historical checker, runtime, and stage0 pair retain their previous bytes.
The lineage also records earlier seed and compatibility changes. These pinned
inputs stay separate from the current source snapshot and its acceptance checks
until the native bootstrap can replace this C-hosted chain.

The lowerer refresh copies six verbatim current-source slices into only
`bridge/compiler/lower.ouro`: the compact Nat helpers and literal dispatch,
and the checked expression-ascription obligation. The other 67 members,
historical checker, runtime, stage0 pair, and import graph remain pinned.
The original independent `refresh_nat_bridge.py` and `refresh_ascription_bridge.py`
retain their exact source and predecessor guards. Inspect the composed
candidate and run its tests before installing it.

```sh
python3 -B scripts/refresh_lower_bridge.py
python3 -B scripts/refresh_lower_bridge_test.py
```

For an approved artifact update, `--write` installs the candidate archive and
manifest under `compiler/bootstrap/`. The generator rejects a changed source
owner or historical package. Running it again against the exact installed
output preserves the archive and manifest bytes.

```sh
python3 -B scripts/refresh_lower_bridge.py --write
```

Verify the installed package with the inventory and repack commands below.
Before publishing a current compiler from these inputs, obtain a fresh full
P1/P2 C comparison, passing ABI laws, and positive and negative behavior
checks. Those checks establish the bootstrap evidence beyond the source-copy
tests.

The [second bridge manifest](../compiler/bootstrap/bridge2-v1.json) pins a
separate source archive and binds it to the same C0 inputs. It records the hashes
of the checked source snapshot, bootstrap report, and compiler used to prepare
the archive. The build compiles this archive from source and retains the second
bridge checks and producer hashes in its bootstrap report. Both archives and
their manifests enter the compiler and historical cache keys.

To inspect a second-bridge candidate, replace `BOOTSTRAP_WORK` with the path
to a fully checked bootstrap work directory. The generator verifies the
recorded source and binary hashes and the complete P1/P2 C comparison.

```sh
python3 scripts/refresh_bridge2.py --bootstrap-work "BOOTSTRAP_WORK"
```

For an approved install, add `--write` to write the archive and manifest
under `compiler/bootstrap/`. The generator refuses to replace a different
second-bridge archive or manifest. Pass `--bridge2` before the
`bootstrap_inputs.py` subcommand to verify, unpack, or reproduce that bundle.

The consumer validates the entire archive inventory before extraction. It
rejects links, traversal, duplicate, extra, or missing members and size/hash
mismatches, and extracts only into a new private directory. To inspect the
lineage and reproduce the archive, use new output paths:

```sh
python3 scripts/bootstrap_inputs.py verify
python3 scripts/bootstrap_inputs.py lineage
mkdir -p _build
python3 scripts/bootstrap_inputs.py unpack --out _build/bootstrap-inputs-v1
python3 scripts/bootstrap_inputs.py repack --source _build/bootstrap-inputs-v1 \
  --out _build/c-bootstrap-v1.reproduced.tar.gz
```

Each attempt keeps its input manifest, commands, diagnostics, output hashes,
and complete C comparison under the configured build directory's `bootstrap/`
tree. Failed checks or code generation preserve the installed compiler;
`rebuild` explicitly removes the configured C output directory first. Neither command
updates committed stage0 artifacts.

The public compiler rejects a `--module` suffix unless it is empty or matches
`_[A-Za-z0-9_]+`; the suffix is C symbol metadata, not arbitrary source text.
Lexing also keeps genuine EOF, malformed input, and exhausted fuel as distinct
results. Malformed and over-budget source therefore fail before parsing or core
artifact emission instead of being accepted as a valid prefix.

## Frontend regeneration

`scripts/frontend_regen.py` regenerates frontend C from Ouro compiler sources.
Its cache keys cover the seed compiler, source and import contents, generator
and helper versions, fuel, and output packing inputs.
Each cached translation unit and packed frontend also requires a matching
input-key and output-hash receipt. Missing, malformed, or stale receipts cause
regeneration; a cached translation unit must retain its module export table.

A regeneration writes a JSON report under `_build/` with cache decisions,
timings, and output hashes. The split frontend includes the declaration-checker
translation unit; changing its semantics therefore requires a stage-loop
fixpoint before promotion. An unchanged generated file is not rewritten merely
because the generator ran. Regenerated frontend data is not canonical typed AST
data and is not declaration-acceptance evidence.

## Cache model

The repository currently caches:

- completed current compiler builds, their bootstrap evidence, and the
  historical C0, bridge, and bridge2 stages;
- C objects and links;
- native tools built by `scripts/build_tool.sh`, including the shared native
  test-suite runner and common runtime C objects;
- self-hosted module work;
- frontend regeneration units and packs;
- generated-C shards;
- stage-loop objects and links.

Caches are accelerators. They do not make a core declaration trusted and do not
replace artifact drift checks, cache-on/cache-off parity, or compiler checking.
A cache is not trusted: a hit may reuse work only with current input and output
identity. It cannot turn unchecked declarations into an accepted program.

A cache should be content-addressed, deterministic, interruption-safe,
fail-closed on malformed metadata, observable through reports, and tested
against a cache-disabled path.

Compiler reuse requires identical current source, runtime, helper, bootstrap
bundle, stage0, C compiler, flags, platform, and include/library environment
identities. The installed binary, completion report, input manifest, and both
complete C comparisons must still match their hashes. On a miss, the driver
can reuse verified C0, bridge, and bridge2 outputs built from the same pinned
historical inputs, build helpers, and host toolchain. A change confined to
current Ouro sources or runtime can reuse these stages. P1 and P2 still run
in a fresh snapshot, including both strict checks of the compiler roots,
the ABI laws, the full generated C comparison, and the positive and negative
behavior checks. `--no-cache` builds all five stages.

Hosted PR jobs share one Linux compiler build through a workflow artifact.
`scripts/ci_gate.py --compiler-artifact export` packages the installed binary,
its receipt, input manifest, completion report, and both complete generated C
comparisons. Consumers import the producer's archive with
`--compiler-artifact import --compiler-sha256 HASH`; they require its exact
SHA-256, file inventory, current source and host identity, and the existing
bootstrap verifier. Missing or changed evidence fails the job. This transport
retains the current C-hosted bootstrap contract and does not grant program
acceptance authority to an artifact or cache. macOS builds its own compiler.

`scripts/native_tool_build.py` keys a native tool by its transitive source
contents, seed compiler and C compiler hashes, runtime sources/headers, build
helpers, fuel, flags, platform, and compiler include/library environment. It
checks a completion record and the binary hash before reuse, including reuse
at another output path. Source timestamps are only launcher startup hints.
Changing content with a preserved timestamp invalidates the build-tool key;
changing only a timestamp does not require recompilation.
Successful C emission has a separate receipt that also binds the ordered unit
closure, build configuration, and emission modes. A later C compilation or link
failure can retain that emission. Reuse rechecks its complete hash and installed
host hooks before building shards, objects, and the final binary. This receipt
does not replace the completed tool receipt; `--check` still rejects an
unfinished build. The build report records this decision as `emission_cache`.
The lint suite always invokes this receipt check before running its binary,
including when only a build helper or a transitive import has changed.
The builder also prepares every required companion beside the parent tool.
Lint requires the style and Clippy workers, including Clippy's structural worker;
their transitive sources and individual binary receipts must all remain current.
The lint launcher keeps successful preparation output in its build log, preserving
the empty stdout/stderr contract for a clean invocation; build failures print that log.

Each installed tool has a `.sources` manifest and a `.build.json` receipt with
its cache decision, input hashes, and elapsed time. `OURO_CACHE=0` or the
driver's `--no-cache` forces fresh emission, compilation, and linking. Native
tool builds take the C worker count from `--jobs` or the resolved configuration.
The local scheduler bounds this count by the CPU and memory it assigns. An
automatic standalone build accounts for available memory, with 2560 MiB for
the build driver and 512 MiB per worker. When available memory is unknown, it
uses at most two workers. An explicit standalone `--jobs` sets the worker
count. External memory and timeout limits still apply.

On Windows, C-host builds of lint, both analyzers, fmt, fix, Clippy and the quality
inventory worker embed a process-local UTF-8 application manifest. They require Windows 10 version 1903
or later, so command-line paths and filesystem calls use the same UTF-8 bytes
as Ouro strings. The build driver uses Windows resource APIs; no SDK tool or
system code-page change is required. It preserves other linker resources and
rejects a conflicting executable manifest. The raw linked image and the final
manifested image have separate hashes, and a failed resource update cannot
publish an installed tool or success receipt. Compiler seeds, runtime sources,
and direct-PE output are outside this tool-specific build step.

Gate launchers select the physical executable name before locating its
`.sources` manifest, including `.exe` names under MSYS. An executable without
the suffix remains preferred when both names exist; an invalid primary manifest
cannot fall back to the other executable. Missing or stale manifests still
require a successful rebuild and a second freshness check before execution.

## Generated artifacts and stage loop

The stage loop checks whether successive stages produce identical frontend and
backend C. Run it from the repository root with the source-build prerequisites.
It writes `stage_loop/result.json` in the configured build directory. If a
sibling `public/` directory exists, it writes the status file to
`../public/bootstrap-status.json`. Otherwise, the status file is
`stage_loop/bootstrap-status.json` in the configured build directory.

```sh
sh scripts/stage_loop.sh
```

Check the exit status and `result.json` for the recorded fixpoint and cache
decision.

With caching enabled, a comparison without promotion can reuse static runtime
objects built directly by the C compiler in the preceding stage of the same
run. Both generated C files must match byte for byte, and the compiler, command,
source, dependency, and object checks must pass. Each stage has its own
generated shards, link target, and build report.

Promotion is the procedure for updating the committed generated C in
`compiler/stage0/`. Use it only for an approved artifact change, with stage-loop
evidence and a coordinated update to the pinned recovery inputs, matching runtime,
and bundle metadata. On a fixpoint, `--promote` writes the two C files and
`docs/generated_artifact_hashes.sha256` before it invokes the bootstrap in the
same command. If the recovery manifest still pins different stage0 bytes, that
bootstrap fails its input check after the files have been written. The recovery
bundle is updated separately.

```sh
sh scripts/stage_loop.sh --promote
```

The drift gate verifies the committed stage0 hash manifest and the historical
bootstrap inputs. Its regeneration reference is the current P2 frontend and
backend C, whose installed receipt must match the current source and host
toolchain and retain the complete P1/P2 equality evidence. Fresh frontend
regeneration and the stage-loop fixpoint must reproduce that verified pair.
The frontend runs with its cache disabled in a new work directory for each
invocation. The gate rejects manifest and other fast-path hits and checks the
fresh output against its regeneration report.
Missing, stale, or changed evidence fails the gate. The reference stays in the
configured bootstrap directory; regeneration does not update committed stage0.

Windows staging C may use CRLF. The promotion writer normalizes it to LF.
Drift checks compare promotion-normalized bytes for the regenerated output and
its P2 reference and record the raw staging hashes. Hand editing stage0 breaks
this reproducibility check.

[CI](ci.md#local-profiles) owns the heavier stage-loop profile for compiler,
frontend, extraction, backend, or promotion changes.

After changing a standard-library API or its generator, regenerate the
committed pages in `docs/api/`. This command builds the documentation tool,
writes the generated pages, and records suite output in `_build/doc_suite/`
by default.

```sh
sh scripts/doc_suite.sh --regen
```

Review the generated diff and check it with `sh scripts/doc_suite.sh`.
Keep changes to the API source or generator.

## Compiler checking

[Compiler checking](kernel_design.md) defines the declaration contract;
[CI](ci.md#local-profiles) owns its required commands and profiles. Missing
required tools or failed probes block the profile.

## Memory behavior

The C runtime uses a process-lifetime allocation model. Compiler and tool paths
therefore control peak memory through bounded processes, phase-local heaps,
smaller dependency cones, generated-C sharding, and explicit memory budgets.
Each value is one 24-byte cell (constructors keep up to two fields inline and
larger field lists directly after the cell), nullary constructors and small
nats are interned, and `ouro_app`/`ouro_case` hand a single-use closure or
thunk back to the phase allocator the moment it is consumed. Handwritten hosts
that keep a closure across calls use `ouro_apply`, which never reclaims. These
keep native check paths well under their former multi-GiB peaks.
Import lexing reclaims each token step's intern lookup. The retained token and
intern delta stay; the comparison spine of earlier names does not. Token and
span callbacks use nested allocation contexts and return into the caller's
allocator, so an enclosing phase reset cannot invalidate borrowed arguments.
The native frontend preserves the checked result in permanent storage and
releases compilation temporaries before scanning source for diagnostics. A
large rejected module therefore does not retain both phases' temporary heaps.
C-hosted `native-build` links the same `frontend_link` seams and routes
`compile_checked_units` through them, so a compiler-sized PE build does not
keep every parse and elaboration temporary in one bump arena.
The curried entry isolates compilation banks from the caller and copies its
result and diagnostic metadata back into the caller's restored allocation
context before freeing those banks. Caller closures and earlier results retain
their existing lifetimes across later compilations. The focused
[`frontend_link_selftest.c`](../runtime/frontend_link_selftest.c) probes cover
caller output arguments, retained results, typed failures, nested contexts,
allocation-context restoration, and exact declaration replay under the shared
memory limit; they do not replace the compiler or PR gates.
`sh scripts/frontend_security_suite.sh` builds and runs these C producer
probes and the MIR selftests against one fresh `tools/native_build.ouro` backend.
To select a diagnostic producer directly, run
`python scripts/frontend_host_suite.py --compiler PATH --out _build/frontend_host --jobs 1`.
The report records producer, source, generated-code and executable hashes;
this host evidence does not establish native N1/N2/N3 bootstrap.
Retained lexer suffixes share immutable byte storage that already belongs to
their permanent bank. Crossing a bank boundary still copies the bytes before
the source bank is released; parsing does not keep a full source copy per token.
The same producer may wrap `mir_gc_infer`, `mir_gc_annotate`, `mir_gc_check`,
`x64_encode`, `codegen_assemble`, `mir_live_facts`, `codegen_parts`,
`codegen_live_instructions`, `codegen_instruction`, `codegen_block`, and
`codegen_body` with equivalent host walks, including managed allocation and
managed-context instructions;
unknown shapes fall back to the generated closures. Those wraps are a
lifetime and time seam, not a second acceptance checker.
Per-global lowering clones only new phase cells onto the permanent bank;
a deep clone of the whole checked program on every declaration is a host
lifetime bug, not extra acceptance. Managed lowering also shares one canonical
lookup environment across runtime helper resolution, raw lowering, and global
checks. Each helper still checks its body and complete normalized signature.
Native lowering's declaration replay uses the same per-declaration lifetime
callback as initial checking. Each call isolates its work banks, then copies new
result cells into the restored caller allocator while sharing caller-owned terms
and the earlier signature. The public `lower_recheck_program` entry retains
the exact checker, complete metadata/body comparison, and typed failures.
The temporary N1 host releases prepare-phase storage and each raw contract's
lowering temporaries while retaining ordered results and the first typed error.
Phase checkpoints rebind the checked program, entry, and fuel used by scalar
fallback. The managed finish phase retains its own per-global allocation marks.
PE byte validation uses an Ouro callback that checks a chunk and returns its
unvisited suffix. Its partial application captures only that chunk's size and
remaining bytes. The C producer retains this capture before the allocation
mark, then retains each callback result and releases the chunk's checking and
suffix-traversal temporaries. Packed suffixes share the retained immutable
buffer; the original bytes, complete validation, and first typed error remain
unchanged.
MIR node and flow hard ceilings are
`pe_byte3_place` so the compiler-scale `native_compiler_limits` budget is
a legal request. Exhaustion of that budget is still `MirResourceExhausted`.
Lowering each expression also preserves its result before releasing that
call's temporary allocations; the surrounding declaration pipeline stays live.
Preflight compilation and elaboration use the same result-preserving boundary,
so completed attempts release their temporary graphs before the next pass.
The preflight fallback tests whether a surface reaches its required depth,
stopping at that threshold instead of computing every exact subtree depth.
Its complete hole scan and declaration checks still run.
Large analyzer profiles also run native file-local work in low-priority child
processes with a short inter-file pause; structured families use the same
bounded path instead of retaining every source unit in one runtime arena.
Global dead-code, duplication, trust, fact-dump, heavy, and all-family modes
fail before starting when a scope exceeds the local safety limit. Narrow the
scope for local work. Structured profiles also reject individual source files
larger than 40 KiB because the extracted frontend retains its arena for the
process lifetime. Split a larger source, or use
`OURO_ANALYZE_ALLOW_UNBOUNDED=1` only on a dedicated high-memory host.
The production sweep uses one native process per file and allows larger sources.
The memory suite uses the same opt-in to measure the largest production source
under the `analyzer-drive-largest-file` budget in `quality/memory_budgets.json`.
That case requires an `ANALYZE_DRIVE` result.
The bounded analyzer wrapper requires the repository Python runner; it fails
closed when Python is unavailable unless that same override is explicit.

Frontend regeneration emits its translation units in parallel, and each unit is
a full native process holding its own arena, so a low-memory host running the
default fan-out is the main remaining OOM risk. `scripts/frontend_regen.py`
caps the pool to what free RAM can hold: a healthy machine keeps its full
`OURO_FRONTEND_JOBS` count, and only a starved host is throttled toward one
worker (never below). Tune it with `OURO_FRONTEND_WORKER_MB` (per-worker
estimate) and `OURO_MEM_RESERVE_MB` (headroom to leave free), or set
`OURO_MEM_AWARE_JOBS=0` to disable the cap.

Memory regressions belong in measured reports with the exact command, input,
host, and peak RSS. Declaration-aware root checking adds a bounded second
frontend pass to native check cases; its budgets include that measured cost.
Raising a budget is not a substitute for fixing lifetime or growth bugs.
The memory suite first builds the selected native tools with the separate
3 GiB, 900-second preparation limit and records each build in
`preparation.json`. Compilation failure blocks the suite. Existing execution
RSS limits and wrapper-install cases then run unchanged; a cold native emitter
is not charged to a formatter or analyzer execution budget.
Preparation includes the measured formatter/analyzer install destinations and
the formatter suite's own images, warming the checked content cache even when
only installed tools were imported. Selecting one of those install cases still
prepares its actual destination; the report directory does not move that target.
Disabling the cache still forces fresh compilation and retains the same limits.

The import collector jumps between lexical candidates in ordinary source to
avoid retaining per-byte traversal temporaries across an entire dependency
tree. It keeps compiler string decoding and delegates alias/open handling to
the shared preprocessor. `native_build_collection_tests.ouro --collect-only`
checks the collection laws on hosted platforms without building a PE image.

Automatic source loading for `native-build` reads each normalized dependency
path once. The collector keeps the bytes alongside each path in dependency
order. Its private constructor binds the normalized root and ordered files
into a `CollectSnapshot`. Automatic checking and image generation accept
that type and run without a reader. Explicit-unit and freshness checks use
their own input paths.

Relevant checks include:

```sh
python3 scripts/memory_budget_suite.py
python3 scripts/cache_parity_suite.py
python3 scripts/selfhost_module_cache_suite.py
python3 scripts/generated_c_shard_cache_suite.py
python3 scripts/generated_artifact_drift_check.py --mode hashes
```

## Benchmarks

With the source-build prerequisites available, run a local wall-time sample of
`check`, `fmt --check`, and `help`. Run it from the repository root. Tool
provisioning can be part of the first invocation, so record the build and cache
state when interpreting the timings.

```sh
python3 scripts/bench_suite.py --out _build/bench
```

The harness writes `report.json` and `report.md` to the output directory. A
`PASS` result means the commands returned their expected exit codes. Use
[comparable measurements](code_optimization.md#measure-the-effect) for claims
about performance changes.
