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

The internal `ouro.checked-program.v1` output is a deterministic, byte-preserving
diagnostic stream; serialization errors fail before opening the file.
`compiler/checked_program_output.ouro` owns its format. The
[legacy JSON replay format](kernel_core_artifact.md) is archived.

`collect` exposes the dependency order used by `check`:

```sh
sh scripts/ouro1.sh collect path/to/module.ouro
```

## Native program compile

`ouro1 build FILE.ouro` compiles the checked import closure to a Windows PE.
`ouro1 build --profile` invokes the toolchain cache driver instead:

```sh
sh scripts/ouro1.sh build FILE.ouro --target x86_64-windows
sh scripts/ouro1.sh build FILE.ouro --backend native --out _build/native/app.exe
sh scripts/ouro1.sh build --profile dev
sh scripts/ouro1.sh build --profile release
```

`legacy-c` and non-`x86_64-windows` targets are rejected. The wrapper treats
`build` as program compile when any argument ends with `.ouro`; otherwise it
forwards to the toolchain driver. `ouro1 run FILE.ouro` compiles to
`_build/native/run/<stem>.exe` and executes that image.

[Build](build.md#host-bound-build-boundary) owns output publication and host
limits; [Design](design.md#native-toolchain-contract) owns the native target.

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

For both `fmt` and `fix`, a directory argument selects the sorted `.ouro`
files beneath it. Discovery skips `_build`, `_cache`, `_opam`, `_tools`,
`.git`, and `node_modules`. Explicit files remain accepted regardless of
extension or skipped directory names. A directory with no selected sources
exits 1 with `path: no .ouro files` and does not write. Missing paths report
`path: no such file`; other valid roots are processed and the command exits 1.

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

Directory selection follows the [formatter](#formatter) rules above.

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

Every preview/check and each automatic transformation class requires compiler
verification. [Safe rewrites](quality.md#precision-and-safe-rewrites) own
staging, replacement, recovery, and refusal conditions.

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

Review proposals remain visible without changing source. Unknown rules,
conflicting edits, cycles, and reopened formatting fail. The
[Clippy boundary](clippy_grade_firewall.md#fix-publication-and-convergence)
records remaining convergence limits.

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
Unknown or incomplete long options, including `--out` without a directory,
print usage and exit 2. `--out DIR` selects the native binary directory;
`OURO_TEST_OUT` remains the default when `--out` is omitted. An empty discovery
result prints `test: no tests found` and exits 1.
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
[Build](build.md#generated-artifacts-and-stage-loop) owns committed API
regeneration.

## Repository gates and CI runner

[CI](ci.md#local-profiles) owns the repository gate commands, profiles,
required checks, and report contracts. The native gate inventory and migration
boundary are documented in [native repository gates](native_repo_gates.md).

## Core toolchain performance evidence

The timing runner, before/after comparison, and report interpretation live in
[CI performance evidence](ci.md#performance-evidence). Build receipts and cache
freshness are documented in [Build and bootstrap](build.md#cache-model).

## Packages

Use the [package guide](pkg.md#commands) for `coil`/`ouro1 pkg` commands,
local registries, installation, locks, and verification.

## Language server

```powershell
$env:OURO_ROOT = (Get-Location).Path
.\_build\native\ouro-lsp.exe
```

The experimental language server communicates over standard input/output and
currently provides:

- diagnostics;
- watched-file refresh of open buffers, preserving unsaved text while imports
  continue to come from disk;
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

The extension's installation, build, and settings are in the
[VS Code guide](../editors/vscode/README.md). The server protocol and
capabilities are described [above](#language-server).

## Building standalone tools

[Build and bootstrap](build.md#entry-points) owns tool emission and host
requirements. [OuroSmith](ouro_smith.md) owns generated tool properties and
replay commands.

## Text-file statistics

`tools/lines.ouro` reports line, byte, empty-line, and non-empty-line counts.
Build it with `sh scripts/build_tool.sh tools/lines.ouro _build/tools/ouro-lines`.
The command accepts `--summary`, `--ext EXT`, `--contains TEXT`, and input paths;
`sh scripts/lines_suite.sh` exercises its maintained behavior.
