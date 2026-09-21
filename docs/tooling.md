<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=TOOLING&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="TOOLING banner"
  />
</p>

# Tooling

The maintained command entry point is `scripts/ouro1.sh`. `scripts/coil.sh` is
the project-facing name for the same toolchain: `coil check`, `coil fmt`,
`coil build`, `coil doctor`, and the package verbs (`coil add`, `coil install`,
`coil lock`) map onto `ouro1` and `ouro1 pkg`. `doctor` prints the native
target and rejects `legacy-c`. Most user-facing tools are Ouro programs
under `tools/`; the wrapper builds them on first use and rebuilds them when
their sources change. Standalone native LSP, package verification and user
tests use the PE binaries described below; the transitional C-host tool
builder does not provision this group.

## Check and evaluate

Import collection preserves `OURO-IMP-001` through `OURO-IMP-004` for malformed,
duplicate, unknown and reserved aliases, with the source path and byte offset.

```sh
sh scripts/ouro1.sh check path/to/module.ouro
sh scripts/ouro1.sh eval path/to/module.ouro --print name --type TYPE
sh scripts/ouro1.sh eval path/to/module.ouro --eval 'expression' --type TYPE
```

`check` resolves imports and typechecks the complete module closure.
Relative `FILE` arguments stay in the caller's directory: the wrapper looks
up the compiler from the repository root, but `pkg verify` still typechecks
`_ouro_pkgs/...` inside the project that invoked it. `eval`
elaborates and evaluates a declaration or expression in the module's scope.
The evaluation wrapper defaults to `Nat`; use `--type TYPE` for another result
type. The declared type is checked before native extraction.

For compiler diagnostics and transformation tests, `check` can write its complete
checked program:

```sh
sh scripts/ouro1.sh check path/to/module.ouro --emit-checked-program _build/module.checked
```

The output begins with `ouro.checked-program.v1` and contains a deterministic
ASCII stream of tagged, length-prefixed natural-number tokens. It preserves
declaration types and bodies, inductive metadata, checked intrinsic and extern
bindings, representation roles, exact string bytes, and emission order. Global
references use names rather than allocation-dependent IDs; local binders keep
de Bruijn identity. `compiler/checked_program_output.ouro` owns the format.
Serialization errors return nonzero before opening the output file. This internal
pre-1.0 diagnostic format replaces the incomplete `--emit-core-artifact` export;
the [legacy JSON replay format](kernel_core_artifact.md) is archived.

`collect` exposes the dependency order used by `check`:

```sh
sh scripts/ouro1.sh collect path/to/module.ouro
```

## Native program compile

`ouro1 build FILE.ouro` compiles a Windows PE through the checked-source
native lowerer. The driver resolves and reads the import closure itself;
direct `ouro-native-build ROOT.ouro OUT.exe` uses the same path. Import
collection handles line breaks and optional semicolons, uses the compiler's
string and alias processing, and preserves Windows UNC path prefixes. Program
acceptance checks the complete closure before lowering. Managed lowering
runs first; scalar lowering is tried only for an unsupported type or unknown
global. `legacy-c` is rejected;
there is no C fallback. That is a different command from the toolchain cache
driver `ouro1 build --profile`:

```sh
# Program compile: native x86-64 Windows PE, no C fallback
sh scripts/ouro1.sh build FILE.ouro --target x86_64-windows
sh scripts/ouro1.sh build FILE.ouro --backend native --out _build/native/app.exe

# Toolchain/cache profile (Python build driver)
sh scripts/ouro1.sh build --profile dev
sh scripts/ouro1.sh build --profile release
```

`legacy-c` and non-`x86_64-windows` targets are rejected. The wrapper treats
`build` as program compile when any argument ends with `.ouro`; otherwise it
forwards to the toolchain driver. `ouro1 run FILE.ouro` compiles to
`_build/native/run/<stem>.exe` and executes that image.

Build output is staged beside the destination and checked byte for byte
before replacement. The driver prints the output path only after publication
succeeds. A locked or otherwise refused destination produces a nonzero exit
and retains its previous contents. See [Build](build.md#host-bound-build-boundary)
for cleanup and durability limits.

The current native PE surface includes stdio, stdin, argv, env, time, files,
filesystem predicates, mkdir/remove, copy, rename, directory listing, and
realpath. Temp files, process capture, and HTTP use the shared managed
lowerer's runtime implementations. The `ouro-native-build` driver itself is
still produced by the C host; this wiring does not establish native
self-rebuilding or isolated-host acceptance.

`tools/coil.ouro` provides the native CLI entry for `doctor`, `check`, program
`build`, and `run FILE.ouro [PROGRAM_ARG ...]`. Its check command collects the
complete import closure and accepts library modules without an executable entry
point. Check fuel defaults to 16000; program build and run retain the positional
producer's 200000 budget. Unknown, repeated, or incomplete check/build options
return nonzero before compilation.

Native `coil run` checks, builds and atomically publishes
`_build/native/run/<stem>.exe`, then runs it with inherited stdin, stdout, stderr,
current directory and environment. Every argument after the source is passed
literally, including `--out` and `--`; run has no build options. The child owns
stdout without a preceding build-path line. Build or process setup/wait errors
produce a `coil:` diagnostic and exit 1; completed child exit codes, including
259, are preserved. Process cancellation uses the inherited-process runtime's
owned-job cleanup contract. The existing wrappers still own the remaining tool
commands during migration.


## Standalone native tools

With a native `coil.exe` already built in `_build/native`, build the formatter,
language server, package tool and test runner explicitly:

```powershell
.\_build\native\coil.exe build tools/fmt.ouro --out _build/native/ouro-fmt.exe
.\_build\native\coil.exe build tools/lsp.ouro --out _build/native/ouro-lsp.exe
.\_build\native\coil.exe build tools/pkg/main.ouro --out _build/native/ouro-pkg.exe
.\_build\native\coil.exe build tools/test/main.ouro --out _build/native/ouro-test.exe
```

Invoke these executables directly. `ouro-lsp.exe`, `ouro-pkg.exe` and
`ouro-test.exe` locate the fixed `coil.exe` beside their loaded Windows image;
LSP formatting also requires `ouro-fmt.exe` there. Their subprocesses preserve
literal arguments and the real working directory. A missing sibling, timeout,
resource failure or malformed process result is an explicit failure.

Each child tree uses one CPU, 3072 MiB and 16 MiB per captured stream. The
provisional deadlines are 30 seconds for LSP checks, 10 seconds for formatting,
120 seconds per package source, 1800 seconds for a test check/build, 300 seconds
per test executable and 4000 seconds for the recursive runner probe. These
limits still need measurements with native tool workloads.
The native test policy laws check the exact deadlines and all resource fields.
Large deadlines use small Nat factors so C-host builds avoid deeply nested
constant constructors without changing those limits.

Native `coil` currently exposes `doctor`, `check`, `build` and `run`. Tool
dispatch and automatic tool builds are separate work. The retained shell
suites still own their fixture preparation and assertions; native acceptance
must provision direct-PE candidates and their siblings before running those
assertions. A C-host candidate cannot exercise the bounded native process API.
Hosted C-host suites instead pass `OURO_TEST_CHECK` /
`OURO_HOSTED_COMPILER_WRAPPER` (`scripts/ouro1.sh`) and, for builds,
`OURO_TEST_BUILD` (`scripts/build_tool.sh`). `ouro1 test` and `ouro1 pkg`
set those variables when they are unset, and C-host test runs launch the
child with `prim_proc_exec` instead of bounded capture. Use the retained
suites' explicit `--native-tools DIR` option as described in
[native tool acceptance](ci.md#local-profiles).

## Formatter

```sh
sh scripts/ouro1.sh fmt path/to/module.ouro
sh scripts/ouro1.sh fmt --check path/to/module.ouro
sh scripts/ouro1.sh fmt --write path/to/module.ouro
```

The formatter normalizes line endings, tabs, trailing whitespace, match-arm
spacing, and the final newline. It is intentionally a conservative text
formatter rather than a complete AST pretty-printer, so it preserves comments
and hand-aligned continuation lines.
Unknown options, conflicting write/check modes and mixed file/selftest modes
exit `2` before reading or changing source files.

## Autofixer

```sh
sh scripts/ouro1.sh fix path/to/module.ouro
sh scripts/ouro1.sh fix --check path/to/module.ouro
sh scripts/ouro1.sh fix --write path/to/module.ouro
```

`fix` rewrites the mechanical part of what the linter reports. It works on a
positional token stream of the original text, so comments, string bodies, and
untouched formatting survive, and it reruns its rules until nothing changes.
Without a mode flag it prints the fixed text; `--check` exits `1` and lists the
pending edits on stderr as `path:line: rule: message`; `--write` saves the file
and prints the applied edits. Every rule is conservative: when a construct does
not match the expected shape exactly, the fixer leaves it alone.
Unknown options, conflicting `--check`/`--write`, and mixed selftest/file modes
exit `2` before reading or changing source files. Use `--` before a filename
that starts with a dash.

A prepared `ouro-fix` executable runs its rewrite rules directly.
There is no Python rewrite fallback and no Python CLI wrapper: the former
`scripts/syntax_quality_fix.py` command is removed, and suites invoke the
native binary with `--check`, `--write`, and file arguments.

The publication planner applies only machine-safe syntax and local-redundancy
classes. Every preview/check and each transformation class requires candidate
compiler verification; a successful token rewrite alone is not permission to
publish. Both `fmt --write` and `fix --write` use checked staging,
metadata-preserving replacement and explicit recovery. Candidate compiler
checking uses `ouro-fix-check` with stdin framing or `SOURCE file PATH`; POSIX
C-host bounded capture (OS status 120) uses the existing file transport. See
[safe-rewrite boundaries](quality.md#precision-and-safe-rewrites).
Read-only and hard-linked sources are refused without reporting a successful
write; an unchanged candidate remains a no-op.

| Rule | Publication applicability |
| --- | --- |
| `dup-import` | automatic only for the identical path and alias, with trivia preserved |
| `do-bind` | automatic syntax canonicalization to `do let! x := action;` |
| `double-semi` | automatic removal of a redundant separator |
| `dead-let` | automatic only for the rule's literal/dead-value proof or retention of the same executed IO action |
| `identity-let` | automatic only for an unannotated local immediately returned through the same binder |
| `list-literal`, `peano-literal` | review required; constructor/provider identity is not a textual proof |
| `unused-binder`, `unreachable-arm` | review required; no automatic renaming or arm removal |
| `import-alias`, `list-type`, `nonrec-fix` | review required; no automatic API/resolution-affecting rewrite |

Review proposals remain visible without changing source. Unknown rule IDs,
conflicting automatic edits, invalid spans, cycles and reopened formatting fail
instead of silently selecting a transformation. A comment-bearing edit cohort
is retained for review rather than partially applied. The legacy raw rewrite
helper remains a fixture oracle, not the publication path.

The native planner laws cover conflict ordering, trivia, cycles and fixture
idempotence. Whole-production `fix -> fmt -> fix` convergence is not yet
established; the compiler companion build and large import-cone memory pressure
remain validation blockers. See [Clippy and fix boundaries](clippy_grade_firewall.md).

## Analyzer and linter

```sh
sh scripts/ouro1.sh analyze --strict
sh scripts/ouro1.sh lint --deny --profile project std samples
sh scripts/ouro1.sh lint --family language path/to/file.ouro
```

`analyze` runs repository-wide analyzer families such as architecture, dead
code, API surface, trust policy, and suppressions, and on request the
structured families that parse each source with the compiler frontend (control
flow, dataflow, effects, taint, contracts, metrics, duplication, and others).
Enable them per family (`--enable-cfg`, `--enable-taint`, ...) or as sets
(`--enable-strict` for the families that are clean on the production tree,
`--enable-light`, `--enable-heavy`, `--enable-all`); run
`sh scripts/ouro1.sh analyze --help` for the current flags. Each source runs in
its own bounded process, and structured families refuse a single source larger
than 40 KiB; see [Build](build.md#memory-behavior).

`lint` is the only user-facing Ouro source linter. It parses individual
files and runs language, proven style, and compiler-proved semantic
families as separate processes. It is
separate from the repository analyzer so each tool keeps a smaller dependency
and memory footprint. Directory scans have no file-size cutoff. The launcher
runs each source in its own process and returns nonzero if a child fails;
memory exhaustion is not a successful skip.
Both tools prune build and dependency directories during root discovery.
Analyzer diagnostic fixtures are opt-in with `--include-fixtures`; their
expected findings are checked by the dedicated suites.

The analyzer and linter are quality tools. They do not establish compiler
acceptance. See [Quality tools](quality.md).

The repository structural gate is
`python3 scripts/strict_quality_firewall.py --structural`. It extends the existing
firewall with clone groups, wrappers, dead-code checks, recognized legacy
fallbacks, and cross-language candidates. See
[the rule and classification contract](quality.md#repository-structural-gate).

## User tests

```powershell
.\_build\native\ouro-test.exe samples/examples/test_demo.ouro
.\_build\native\ouro-test.exe path/to/test-directory
```

`std/test.ouro` provides the current assertion and test-runner helpers. A
sibling `.golden` file is compared with program output when present.
The hosted `ouro1 test` wrapper keeps successful tool-build logs in
`_build/c/ouro-test.build.log`; failed builds print their complete diagnostics.
An ordinary failing test reports `FAIL run <path>` and `test: failed`, with
exit status 1.
With no input, `ouro-test.exe` discovers `*_test.ouro` below the current
directory. Directory entries are sorted; input-root order, duplicate roots
and explicitly named files are preserved. Discovery excludes `_build`,
`_cache`, `_opam`, `_tools`, `.git`, `bad`, `future`, `fixtures` and `bench`.
An unreadable or exhausted inventory fails explicitly. Checks and native
builds use sibling `coil.exe`; fixture stdin is captured as exact bytes.
Repository-owned check batches use the same native tool in strict manifest
mode, for example:

```sh
python3 scripts/ouro_smith.py manifest --prefix=IMP.,ERGO.,REC. \
  --out=_build/surface_suite --label=SURFACE_SUITE
```

Repository and compiler tests use additional suites documented in
[Contributing](../CONTRIBUTING.md). The retained `ouro1-test` suite row
restarts the loaded standalone runner on its success fixture and requires
`test: ok`. This does not test future `coil test` dispatch, which needs a
separate execution probe when that command is added.
For an explicit manifest, `--root` defaults to its containing directory.
The native formatter, fixer, documentation, lint, and test selftests receive
generated inputs from [OuroSmith](ouro_smith.md); the suite wrappers prepare
those inputs before invoking the native assertions.

## Documentation generator

```sh
sh scripts/ouro1.sh doc --out _build/api std/io.ouro
sh scripts/ouro1.sh doc --check --out docs/api --files-from std.list
```

`doc` extracts declaration-adjacent documentation comments and writes one
Markdown page per module plus an index. `docs/api/` is the committed generated
reference for the standard library. `--check` reports drift without modifying
files. A missing source or an unreadable `--files-from` list is an error.

## Repository gates and CI runner

Ouro-native repository gates live under `tools/repo_gate/`; the data-driven
runner lives under `tools/ci_gate/`. The shell entry points are compatibility
wrappers: they build the Ouro binary and pass arguments through, while policy,
profiles, report schemas, and gate selection live in Ouro code.

```sh
sh scripts/ouro_repo_gate.sh --profile docs-native --out _build/ouro_repo_gate/docs-native
sh scripts/ouro_repo_gate.sh --profile project-native --out _build/ouro_repo_gate/project-native
sh scripts/ouro_repo_gate.sh --profile workflow-native --out _build/ouro_repo_gate/workflow-native
sh scripts/ouro_repo_gate.sh --profile pr-native --out _build/ouro_repo_gate/pr-native
```

The Python PR profile invokes those `*-native` names; the short names `docs`,
`project`, and `workflow` are aliases.

The CI runner supports grouped profiles, selected gate execution, deterministic
listing, required versus optional gates, blocking versus informational gates,
exact argv reporting, per-gate JSON, profile summary JSON, optional host-tool
unavailability reporting, and complete `.py`/`.sh` inventory coverage. Native
selftest modes own the formatter, documentation, lines, native lint fixtures,
runtime, user-test, sample, quickstart, and control-plane fixture policies. Their
shell commands retain bootstrap only, except that `lint_suite.sh` also
compiler-checks the split Clippy entry points listed in
[CI](ci.md#ouro-native-control-plane-displacement) and runs the Clippy-grade
fixture suite.

```sh
sh scripts/ouro_ci_gate.sh --profile pr-native --list
sh scripts/ouro_ci_gate.sh --profile quickstart-native --out _build/ouro_ci/quickstart-native
sh scripts/ouro_ci_gate.sh --profile pr-native --gate repo-gate-workflow --out _build/ouro_ci/workflow
sh scripts/ouro_ci_gate.sh --profile host-bound --out _build/ouro_ci/host-bound
```

Use `python3 scripts/ci_gate.py --profile pr --out _build/ci/pr` for full PR
readiness until the narrower `pr-native` profile is explicitly sufficient for
the change. Do not remove a Python or shell control-plane script without parity
evidence and an updated `host-bound` report.

## Core toolchain performance evidence

Use the core toolchain timing runner when changing startup, formatter, checker,
native gate, wrapper, cache, report, or process paths:

```sh
sh scripts/perf_core_toolchain.sh --repeat 3 --out _build/perf/core-toolchain-current.json
```

For before/after work, keep the first report and compare the next run against it:

```sh
sh scripts/perf_core_toolchain.sh --repeat 3 --out _build/perf/core-toolchain-before.json
sh scripts/perf_core_toolchain.sh --repeat 3 \
  --baseline _build/perf/core-toolchain-before.json \
  --out _build/perf/core-toolchain-after.json
```

The report records the exact command, wall-clock milliseconds, exit code,
stdout/stderr byte counts, repeat count, min/median/max timing, environment
summary, and cache note for commands such as help, single-file format-check,
single-file check, native gate listing, and the Python PR profile listing.
Missing commands are recorded as unavailable rather than success. Comparing to a
baseline prints a warning for command medians that exceed twice the baseline;
maintainers may opt into a blocking local check with `--fail-on-regression`.

Native tool wrappers also use source manifests emitted by `scripts/build_tool.sh`.
After a native binary has been built, the wrapper can check the manifest instead
of walking broad source trees on every `--list` or startup command. This is a
freshness accelerator only: a missing manifest, missing source, or newer source
falls back to rebuilding or the older directory scan, and the manifest is never
accepted as proof that a gate passed.

## Packages

```sh
sh scripts/coil.sh init
sh scripts/coil.sh add NAME --range '^0.1.0'
sh scripts/coil.sh install
sh scripts/coil.sh verify
```

`sh scripts/ouro1.sh pkg ...` is the same tool.

The package tool uses local registries and vendors ordinary source files into a
project. It does not use a public network registry. See [Packages](pkg.md).

## Language server

```powershell
$env:OURO_ROOT = (Get-Location).Path
.\_build\native\ouro-lsp.exe
```

The experimental language server communicates over standard input/output and
currently provides:

- diagnostics;
- hover and definition lookup;
- completion and document/workspace symbols;
- whole-buffer rename;
- document formatting;
- full-text document synchronization.

The server runs sibling `coil.exe` for checks and `ouro-fmt.exe` for
formatting through bounded captured processes. Child output is consumed by
the protocol adapter; it does not enter framed stdout directly. Missing
tools and process failures produce diagnostics, and a failed formatter
returns no edit. `OURO_LSP_OURO1` no longer selects a checker. Several
operations rebuild an index from open documents and imported files.

The explicitly configured `OURO_ROOT` remains the authorization boundary
for file URIs,
imports, diagnostics, formatting, and symbol indexing. Absolute imports,
traversal, links/reparse points, non-file URIs, and canonical paths outside that
root are rejected. Protocol frames are limited to 1 MiB, one retained document
to 512 KiB, and all open document text to 2 MiB. Formatting and unsaved-buffer
checks use exclusive scratch files under the root's existing `_build` directory
and remove them after the child command completes.

## VS Code

The extension under `editors/vscode/` contains a TextMate grammar and an LSP
client. Build it with:

```sh
cd editors/vscode
npm install
npm run lint
npm run compile
```

`npm run lint` runs Biome in deny-all (`preset: all`, every group error,
`--error-on-warnings`) on `editors/vscode/src` and `editors/vscode/test`
using `quality/biome.json`. The same linter covers `site/src` and
`site/vite.config.js` via `cd site && npm run lint`. Host
Python uses Ruff:

```sh
ruff check --config quality/ruff.toml scripts
shellcheck --severity=style scripts/*.sh samples/bioinformatics/fixture_tool.sh
```

The extension does not execute a workspace-provided script by default and stays
disabled in Restricted Mode. Configure a trusted, machine-scoped
`ouro.server.command` after building the server. Configuration and development
instructions are in
[`editors/vscode/README.md`](../editors/vscode/README.md).

## Building standalone tools

Repository contributors can run [OuroSmith](ouro_smith.md) to generate and replay
compiler, runtime, formatter, lint, fix, doc, LSP, import, and cache properties.
Its reports include concrete inputs and replay commands. The `ouro1 test`
command continues to run user-authored tests and the native repository suites.

A module that exports `main : IO Unit` can be emitted and linked as a native
program:

```sh
sh scripts/build_tool.sh tools/fmt.ouro _build/tools/ouro-fmt
```

The current runtime uses a process-lifetime allocator and is designed around
short-lived command-line programs. Long-running tool behavior, including LSP
memory growth, remains an experimental area.

## Text-file statistics

`tools/lines.ouro` reports line, byte, empty-line, and non-empty-line counts.
Build it with `sh scripts/build_tool.sh tools/lines.ouro _build/tools/ouro-lines`.
The command accepts `--summary`, `--ext EXT`, `--contains TEXT`, and input paths;
`sh scripts/lines_suite.sh` exercises its maintained behavior.

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
