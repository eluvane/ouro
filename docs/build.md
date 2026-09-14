<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=BUILD&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="BUILD banner"
  />
</p>

# Build and bootstrap

Ouro has a Python build driver, a transitional C bootstrap path, and
content-addressed caches. The compiler-owned checker runs as an Ouro program;
OCaml, opam, and Dune are retired from active builds and validation. The normal user path starts with
`scripts/bootstrap.sh`; this page is for contributors who need to understand
configuration, generated artifacts, or incremental behavior.

## Entry points

```sh
sh scripts/bootstrap.sh
python3 scripts/ouro_build.py build
python3 scripts/ouro_build.py rebuild
python3 scripts/ouro_build.py clean
python3 scripts/ouro_build.py cache status
python3 scripts/ouro_build.py cache clean
python3 scripts/ouro_build.py config show
```

`scripts/ouro1.sh` remains the user-facing wrapper for language and tooling
commands. `scripts/coil.sh` is the project-facing name for the same toolchain.

macOS host executables reserve a 128 MiB main-thread stack at link time through
Mach-O's `-stack_size`, including historical bootstrap producers. This reserve
does not depend on changing the stack of the host Python interpreter.
The C IO host enables Darwin's extended declarations so no-follow file writes
retain `O_NOFOLLOW` under the POSIX feature flags. Release toolchain packaging
uses Python 3.12 and installs its dependency in a local virtual environment.
Clang C compilation allows bracket nesting up to 1024 for generated constructor
expressions; the selected flag participates in the object-cache command key.

The standalone Python frontend regenerator and bounded analyzer reserve a
128 MiB POSIX stack for native compiler processes, capped by the inherited hard
limit. An already larger or unlimited stack is preserved. Address-space and
memory-budget limits still apply; failure to configure the stack is an error.

## Native transition baseline

The recovery source for the transition is
`8ee4a175828f7eb803ca71f19bbd4c24de9b91b1`, observed on 2026-09-06.
The local `pre-native-pivot` tag pins this recovery revision; it is not a
native release seed. Reproduce
it in a separate checkout of that revision. Commands in this baseline section
belong to that historical checkout, including its now-retired checker tools and
build flags. They are not commands for the current worktree. The input is generated C
bootstrap, with these SHA-256 digests also recorded in that revision's
`docs/generated_artifact_hashes.sha256`:

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

OURO_BUILD_DIR=_build/native-transition/baseline/build \
OURO_C_BUILD_DIR=_build/native-transition/baseline/c \
OURO_CACHE_DIR=_build/native-transition/baseline/cache \
OURO_JOBS=2 OURO_FRONTEND_JOBS=1 \
sh scripts/stage_loop.sh
```

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

The local measurement command is:

```sh
python -B _build/native-transition/baseline/programs/measure.py
```

Its `report.json` records complete argument arrays, input and output SHA-256
hashes, generated and executable sizes, timeouts, individual runs, and separate
job committed-memory peaks. `sandbox-report.json` and `lsp-diagnosis/report.json`
retain the failed host-startup evidence. All measured source hashes were
unchanged after execution; generated inputs and reports remain under the local
`baseline/` output tree.

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
that cone. POSIX child stacks stay at the documented 128 MiB cap unless the
inherited hard limit is lower.

Native-build output publication stages the image in a private file beside its
destination, reads it back, compares every byte, and performs a same-volume
rename with replacement. A refused replacement returns an error and preserves
the previous output. The publisher checks staging cleanup on recoverable
failures; fatal runtime errors or interruption can leave the staging file.
Readback requires a full image buffer. This path does not provide power-loss
durability, native cache transactions, or isolated-host bootstrap evidence.
See [the runtime contract](effects_design.md#runtime-surface) for rename errors.

Repository-control-plane and ordinary suite policy move first because they can
be displaced without changing bootstrap semantics:

```sh
sh scripts/ouro_ci_gate.sh --profile host-bound --out _build/ouro_ci/host-bound
```

That report covers every repository-visible Python and shell path, recording
its migration status, native replacement, concrete blocker, and evidence. Build,
cache, stage-loop, compiler-measurement, hosted-network, memory-observer, and release
paths remain host-bound until their exact capabilities and trust evidence exist
natively. Do not hand-delete a build script merely because a downstream native
gate exists.

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

Project defaults live in `Ouro.seal` under the `build` and `cache` blocks.
See [Packages](pkg.md) for the seal syntax. Configuration precedence is:

```text
command line > environment > project configuration > built-in defaults
```

The build driver configures the profile, parallelism, C compiler, optimization,
build and cache directories, optional `ccache`, verbosity, and reproducibility
mode. `--c-only`, `--frontend`, `--dune`, and the Dune cache flags are retired; plain `build`
selects the current C producer without discovering OCaml tools. Run `config show` to see the effective values.
The repository default is ten workers (`Ouro.seal` `build.jobs`, CI
`OURO_JOBS`, and the build-driver fallback). Override it with `--jobs` or
`OURO_JOBS`.

The transitional compiler bootstrap runs one worker per phase with a 3 GiB
memory limit and a 900-second timeout per command. Windows limits shared
process-tree commit; POSIX applies an inherited address-space limit per process
except on Darwin, which rejects finite `RLIMIT_AS`.
Tool and stage-loop builds retain their configured worker counts.

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

`scripts/bootstrap.sh` and plain `ouro_build.py build` require Python 3 and a C
compiler. A clean source checkout needs no Git history, network download, or
pre-existing Ouro executable. The driver performs four stages:

1. Compile the committed `compiler/stage0/` C with its matching pinned
   runtime to obtain C0.
2. Use C0 to build the historical Ouro bridge and its matching runtime from
   `compiler/bootstrap/c-bootstrap-v1.tar.gz`.
3. Copy the current compiler, stdlib, tool inputs, and runtime into a separate
   private snapshot, without source transformations. The bridge must strictly
   check all 15 current compiler roots and their ordered import closures before
   emitting current P1.
4. P1 repeats those checks, checks `std/prelude.ouro`, `std/data.ouro`,
   `tools/collect.ouro`, and `tests/compiler_abi_tests.ouro` with their closures,
   builds and executes the ABI laws, then emits P2 from the same current
   snapshot. Full frontend and backend C must match between P1 and P2. P2 must
   also pass the positive and exact negative String-index checks before it is
   published as the current compiler.

The String-index probes use the frozen, ordered import closure of
`std/data.ouro`, including its transitive dependencies. They do not maintain a
second handwritten stdlib unit list; missing units remain bootstrap failures.

The [bootstrap input manifest](../compiler/bootstrap/c-bootstrap-v1.json) records
68 input files: 58 historical Ouro sources and two five-file runtime sets. It
pins every file's size and SHA-256, the archive's 213,975 bytes, and the
committed stage0 pair. The C0 runtime matches that seed; the historical bridge
sources and runtime remain unchanged. The manifest's `seed_refresh` records the
previous seed hashes, changed C0 runtime members, and source and stage-loop
evidence. Its lineage retains the four historical representation omissions and
all reviewed compatibility edits. These pinned inputs stay separate from the
current source snapshot and its acceptance checks. They remain temporary inputs
until the native bootstrap can replace this C-hosted chain.

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

A regeneration writes a JSON report under `_build/` with cache decisions,
timings, and output hashes. The split frontend includes the declaration-checker
translation unit; changing its semantics therefore requires a stage-loop
fixpoint before promotion. An unchanged generated file is not rewritten merely
because the generator ran. Regenerated frontend data is not canonical typed AST
data and is not declaration-acceptance evidence.

## Cache model

The repository currently caches:

- completed current compiler builds and their bootstrap evidence;
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
complete C comparisons must still match their hashes. A miss or `--no-cache`
runs the complete bootstrap chain in fresh output directories; this transitional
path does not reuse individual stages after a source change.

`scripts/native_tool_build.py` keys a native tool by its transitive source
contents, seed compiler and C compiler hashes, runtime sources/headers, build
helpers, fuel, flags, platform, and compiler include/library environment. It
checks a completion record and the binary hash before reuse, including reuse
at another output path. Source timestamps are only launcher startup hints.
Changing content with a preserved timestamp invalidates the build-tool key;
changing only a timestamp does not require recompilation.

Each installed tool has a `.sources` manifest and a `.build.json` receipt with
its cache decision, input hashes, and elapsed time. `OURO_CACHE=0` or the
driver's `--no-cache` forces fresh emission, compilation, and linking. Native
tool builds use at most two C workers, bounded further by `OURO_JOBS`.

Gate launchers select the physical executable name before locating its
`.sources` manifest, including `.exe` names under MSYS. An executable without
the suffix remains preferred when both names exist; an invalid primary manifest
cannot fall back to the other executable. Missing or stale manifests still
require a successful rebuild and a second freshness check before execution.

## Generated artifacts and stage loop

`compiler/stage0/` contains committed generated C used for bootstrapping. These
files are updated only by the stage loop:

```sh
sh scripts/stage_loop.sh
sh scripts/stage_loop.sh --promote
```

While `c-bootstrap-v1` is active, promoting stage0 alone makes the next default
bootstrap fail its historical input check. A promotion therefore needs a
separately reviewed, coordinated recovery-input update with matching runtime
and bundle metadata. The stage-loop command does not regenerate that bundle.

Promotion updates the committed artifacts and
`docs/generated_artifact_hashes.sha256`. Windows staging C may use CRLF; the
promotion writer normalizes it to LF, so drift checks compare promotion-normalized
bytes as well as raw staging hashes. Hand editing a generated stage0 file breaks
the reproducibility model.

The heavier CI profile is:

```sh
python3 scripts/ci_gate.py --profile stage-loop --out _build/ci/stage-loop
```

Use it for compiler, frontend, extraction, backend, or promotion changes on a
host with sufficient resources.

## Compiler checking

The checker is built and tested through the current Ouro producer:

```sh
sh scripts/test_suite.sh --compiler-checking
python3 scripts/ci_gate.py --profile kernel --out _build/ci/kernel
```

The profile retains its command name and requires canonical compiler laws,
boundary policy, hardening, generated Core cases, and scale/depth probes.
Missing required tools or failed probes block the profile. See
[Compiler checking](kernel_design.md) and [CI](ci.md).

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
callback as initial checking. The public `lower_recheck_program` entry retains
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
process lifetime; the limit covers every production source. The memory suite selects the largest
current production input for the `analyzer-drive-largest-file` budget in
`quality/memory_budgets.json`, so a refactor cannot turn it into a tiny-shim test. Split a larger source, or use
`OURO_ANALYZE_ALLOW_UNBOUNDED=1` only on a dedicated high-memory host.
The largest-source case requires an `ANALYZE_DRIVE` result; a size rejection
before structured analysis cannot satisfy it.
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

The import collector jumps between lexical candidates in ordinary source to
avoid retaining per-byte traversal temporaries across an entire dependency
tree. It keeps compiler string decoding and delegates alias/open handling to
the shared preprocessor. `native_build_collection_tests.ouro --collect-only`
checks the collection laws on hosted platforms without building a PE image.

Relevant checks include:

```sh
python3 scripts/memory_budget_suite.py
python3 scripts/cache_parity_suite.py
python3 scripts/selfhost_module_cache_suite.py
python3 scripts/generated_c_shard_cache_suite.py
python3 scripts/generated_artifact_drift_check.py --mode hashes
```

## Benchmarks

```sh
python3 scripts/bench_suite.py --out _build/bench
```

The benchmark harness records local cold and warm timings. Results are evidence
for a specified host and command, not a repository-wide performance claim.

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
