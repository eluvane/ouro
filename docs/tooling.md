# Tooling

Use `scripts/ouro1.sh` to check, evaluate, build, and run source. The
`scripts/coil.sh` wrapper maps project commands to the same toolchain,
including `coil add`, `coil install`, and `coil lock`. `coil doctor`
prints the native target and rejects `legacy-c`.

Run the shell examples from the repository root in a POSIX-compatible shell
after [building the bootstrap toolchain](getting_started.md#build-the-bootstrap-toolchain).
The wrapper builds most programs under `tools/` on first use and rebuilds
them when their sources change. Provision the
[standalone PE tools](#standalone-native-tools) separately for native LSP,
package verification, and user tests.

## Check and evaluate

Replace `path/to/module.ouro` with a source file. Replace the declaration
name, expression, and type with forms valid in that module.

```sh
sh scripts/ouro1.sh check path/to/module.ouro
sh scripts/ouro1.sh eval path/to/module.ouro --print name --type TYPE
sh scripts/ouro1.sh eval path/to/module.ouro --eval 'expression' --type TYPE
```

`check` resolves imports and typechecks the complete module closure. It resolves
relative source paths from the caller's directory. `eval` resolves relative paths
from the repository root. It checks a declaration or expression in the module's
scope, emits C, and runs the resulting program with the C runtime. Evaluation
defaults to `Nat`. Use `--type TYPE` for another result type.

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
Replace `FILE.ouro` with the entry file. Without a source argument,
`ouro1 build --profile` builds the toolchain.

```sh
sh scripts/ouro1.sh build FILE.ouro --target x86_64-windows
sh scripts/ouro1.sh build FILE.ouro --backend native --out _build/native/app.exe
sh scripts/ouro1.sh build --profile dev
sh scripts/ouro1.sh build --profile release
```

`legacy-c` and non-`x86_64-windows` targets are rejected. The wrapper treats
`build` as program compile when any argument ends with `.ouro`; otherwise it
forwards to the toolchain driver. `ouro1 run FILE.ouro` compiles to
`_build/native/run/<stem>.exe` and executes that image. Run it on Windows x86-64.

[Build](build.md#host-bound-build-boundary) owns output publication and host
limits; [Design](design.md#native-toolchain-contract) owns the native target.

`tools/coil.ouro` provides the native CLI entry for `doctor`, `check`, program
`build`, `run FILE.ouro [PROGRAM_ARG ...]`, and `fmt [--check | --write] PATH...`.
Its check command collects the complete import closure and accepts library
modules without an executable entry point. Check fuel defaults to 16000; program
build and run retain the positional
producer's 200000 budget. Unknown, repeated, or incomplete check/build options
return nonzero before compilation.

Native `coil run` checks, builds and atomically publishes
`_build/native/run/<stem>.exe`, then runs it with inherited stdin, stdout, stderr,
current directory and environment. Every argument after the source is passed
literally, including `--out` and `--`; run has no build options. The child owns
stdout without a preceding build-path line. Build or process setup/wait errors
produce a `coil:` diagnostic and exit 1; completed child exit codes, including
259, are preserved. Process cancellation uses the inherited-process runtime's
owned-job cleanup contract.

`coil fmt` locates the fixed `ouro-fmt.exe` beside its loaded Windows image and
passes every following argument unchanged. The formatter owns option validation
and diagnostics. It inherits stdin, stdout, stderr, current directory and
environment; its completed exit code is preserved. Image-path or process errors
produce a `coil:` diagnostic and exit 1. The existing wrappers still own the
remaining tool commands during migration.

Native `coil analyze` forwards literal arguments to the fixed
`ouro-analyze.exe` beside its loaded image, with inherited streams and working
directory. The analyzer owns option validation and runs the separately named
raw base and drive siblings with a provisional per-worker policy. This SOURCE
route does not establish bundle provisioning, native IO acceptance or RSS
parity; retained analyzer gates and launchers remain required. See the
[native bounded entry](../tools/analyze/README.md#native-bounded-entry) for exact
provisioning and the policy metric.


`coil lsp` runs the fixed `ouro-lsp.exe` beside its loaded Windows image, passing
all following arguments unchanged with inherited stdin, stdout, stderr, cwd and
environment. The server owns framed stdout; the launcher prints no startup line
and preserves the completed child DWORD exit code. Image/process errors produce
a `coil:` diagnostic on stderr and exit 1. Before launch it refuses a hosted
override returned by `prim_env_get` for `OURO_TEST_CHECK`, `OURO_PKG_CHECK`,
`OURO_HOSTED_COMPILER_WRAPPER` or `OURO_HOSTED_FMT`, reporting the first key in
that order. `OURO_ROOT` keeps its authorization meaning; tools must be provisioned
explicitly. The standalone hosted LSP keeps its existing compatibility behavior.

For native `coil pkg [PACKAGE_ARG ...]`, provisioning, forwarding and hosted
checker refusal rules are in the [package guide](pkg.md#commands).


## Standalone native tools

On Windows x86-64, run the following PowerShell commands from the repository
root after placing a working native `coil.exe` in `_build/native`. The commands
build the native tools and the compiler worker required for formatter writes.

```powershell
.\_build\native\coil.exe build tools/fmt.ouro --out _build/native/ouro-fmt.exe
.\_build\native\coil.exe build tools/fix/check_main.ouro --out _build/native/ouro-fix-check.exe
.\_build\native\coil.exe build tools/lsp.ouro --out _build/native/ouro-lsp.exe
.\_build\native\coil.exe build tools/pkg/main.ouro --out _build/native/ouro-pkg.exe
.\_build\native\coil.exe build tools/test/main.ouro --out _build/native/ouro-test.exe
.\_build\native\coil.exe build tools/native_toolchain.ouro --out _build/native/ouro-toolchain.exe
```

Invoke the formatter through `coil fmt` or `ouro-fmt.exe`. Formatter writes that
change source require the `ouro-fix-check.exe` compiler worker beside the
formatter; a missing worker refuses the write. The worker checks the complete
import closure, and accepted original units require an accepted candidate before
publication. Editor snippets rejected by the compiler retain the formatter's
existing token and fixpoint checks.

Use `coil lsp`, `coil pkg`, `coil test` or the standalone executables. On the
native path, the language server, package verifier, and test runner locate
`coil.exe` beside their loaded Windows image. LSP formatting also requires
`ouro-fmt.exe` there. The subprocesses inherit the working directory and receive
literal arguments. A missing sibling, timeout, resource failure, or malformed
process result fails the operation.

Each child tree uses one CPU, 3072 MiB and 16 MiB per captured stream. The
provisional deadlines are 30 seconds for LSP checks, 10 seconds for formatting,
120 seconds per package source, 1800 seconds for a test check/build, 300 seconds
per test executable and 4000 seconds for the recursive runner probe. These
limits still need measurements with native tool workloads.
The native test policy laws check the exact deadlines and all resource fields.
Large deadlines use small Nat factors so C-host builds avoid deeply nested
constant constructors without changing those limits.

Native `coil` currently exposes `doctor`, `check`, `build`, `run`, `fmt`, `test`,
`lsp`, `pkg`, `analyze`, and `toolchain rebuild`.
Other tool dispatch and automatic tool builds are separate work. The retained
shell suites still own their fixture preparation and assertions; native acceptance
must provision direct-PE candidates and their siblings before running those
assertions. A C-host candidate cannot exercise the bounded native process API.
The hosted `ouro1 pkg` wrapper supplies `OURO_PKG_CHECK` when both that
variable and `OURO_TEST_CHECK` are empty or unset. The hosted `ouro1 test`
wrapper sets `OURO_TEST_CHECK` when it is empty or unset and also provides
defaults for `OURO_TEST_BUILD` and `OURO_HOSTED_COMPILER_WRAPPER` in that case.
With `OURO_TEST_CHECK` set, the runner uses the hosted C process interface for
test executables.
Use `--native-tools DIR` in the retained suites to test the provisioned native
tools. [Native tool acceptance](ci.md#local-profiles)

## Native successor rebuild

On Windows x86-64, run the following PowerShell commands from the repository
root with an accepted `ouro-native-build.exe` beside `ouro-toolchain.exe`.
Choose new output directories with existing parents. Keep source inputs and
their parent tree read-only, and prevent other processes from modifying the
command's snapshot, output, or parent paths while it runs.

```powershell
.\_build\native\ouro-toolchain.exe rebuild --source . --out _build/native-rebuild --stages 3 --no-cache
.\_build\native\coil.exe toolchain rebuild --source . --out _build/native-rebuild-next --stages 3 --no-cache
```

The command accepts exactly these options. It copies the complete ordered
import closure of `tools/native_build.ouro`, including that root and
`Ouro.seal`, into an owned snapshot. It refuses imports outside the declared
source root. Native handle-based resolution checks each source parent against
that root, and the bounded file reader refuses final reparse points. The
inventory retains logical relative paths and their order. The parent working
directory does not change. The command is subject to
time-of-check to time-of-use races if another process modifies these paths.

N1 is the fixed loaded-image sibling. N1 builds N2, then N2 builds N3 from the
same copied inputs and fixed native target, entry and fuel. Source, configuration
and producer bytes are checked before and after successful stages. The complete
unsigned N2/N3 images are compared, including padding and bytes after NUL; no
cache, prefix comparison or seed promotion is used. A successful comparison
prints only `NATIVE_REBUILD_COMPARE_OK`. Completed child streams, the ordered
inventory and policy are retained under the output directory. Failures leave
that owned directory for inspection and return nonzero.

The accepted snapshot is limited to 256 MiB in total; discovery separately
bounds each source file by 256 MiB and does not promise a total allocation bound.
Each complete image is limited to 512 MiB. Each child tree has its own
900-second deadline, 3072 MiB, one CPU and 16 MiB per captured stream, with empty
stdin. The pair therefore does not have a single 900-second deadline.
Malformed native path encoding and raw allocation or cleanup can still exit 73.
The four hosted overrides refused by native `coil test` are also refused here.
Provisioning and native N1 behavior remain prerequisites: image inspection and
stage equality do not establish the [native toolchain contract](design.md#native-toolchain-contract)
or isolated-host independence.

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
spacing, spaces around `|>`, and the final newline. It is intentionally a
conservative text formatter rather than a complete AST pretty-printer, so it
preserves comments and hand-aligned continuation lines.
Unknown options, conflicting write/check modes and mixed file/selftest modes
exit `2` before reading or changing source files.

`ouro-fmt --selftest --fixtures DIR --out DIR` runs the retained golden,
idempotence, multiline, write/refusal and tree-drift checks through Ouro-owned
worker orchestration. Each worker and each tree file runs in a separate process.
`--selftest-plan` keeps the shell orchestration used by `fmt_suite.sh`. That suite
retains its fixture preparation and host checks; it does not by itself exercise
the public `--selftest` orchestration.

For a flat comma call already spread across lines, with each argument and the
closing parenthesis on its own line, the formatter indents arguments two spaces
past the opening line and aligns the closing parenthesis. It preserves comments,
quoted text, line breaks, and the presence or absence of a trailing comma.
Nested groups and declaration parameter lists keep their existing layout.

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
| `dead-let`, `identity-let` | review required to preserve binding identity and evaluation |
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

`analyze --strict` runs the base repository policy checks for architecture,
suppressions, and the strict format subset. API surface checking uses its
baseline. Dead code and trust graph checks require their own flags. Structured
families parse source with the compiler frontend. Select individual families
such as `--enable-cfg` or `--enable-taint`, or select a family set such as
`--enable-strict`. The bounded driver runs structured checks per file. Global
base-runner modes can hold the selected files in one process and have separate
scope limits.
[Analyzer flags and family sets](../tools/analyze/README.md#flags-and-family-sets) ·
[Bounded execution](../tools/analyze/README.md#bounded-execution)

`lint` runs language, style, and semantic checks over Ouro source. Language
and style checks use per-file processes. The semantic worker handles batches
in bounded sessions. Directory discovery has no file-size cutoff, and a
failed child process or memory exhaustion fails the command.
[Semantic session lifetime](clippy_grade_firewall.md#session-lifetime-boundary)

`lint --shard N/M` partitions the completed, deduplicated native inventory
in its stable order: shard 1 receives the first file, shard 2 the second, and
so on cyclically. Run all shards over the same roots and source revision to
cover the complete inventory; each selected file retains all requested families.
Indices satisfy `1 <= N <= M <= 128`; invalid or empty shard selections fail.
Both tools prune build and dependency directories during discovery. The analyzer
defaults to `std`, `compiler`, `tools/analyze`, and `samples`. Give an explicit
scope and `--include-fixtures` to include analyzer diagnostic fixtures. The
precision suite verifies their expected findings.

The analyzer and linter are quality tools. They do not establish compiler
acceptance. See [Quality tools](quality.md).

The repository structural gate is
`python3 scripts/strict_quality_firewall.py --structural`. It extends the existing
firewall with clone groups, wrappers, dead-code checks, recognized legacy
fallbacks, and cross-language candidates. See
[the rule and classification contract](quality.md#repository-structural-gate).

## User tests

On Windows x86-64, provision `coil.exe`, its checked build backend, and the
standalone test runner before running these PowerShell examples.
[Standalone native tools](#standalone-native-tools)

```powershell
.\_build\native\coil.exe test samples/examples/test_demo.ouro
.\_build\native\coil.exe test --out _build/native/user-tests path/to/test-directory
.\_build\native\ouro-test.exe samples/examples/test_demo.ouro
.\_build\native\ouro-test.exe path/to/test-directory
```

`coil test` runs the fixed `ouro-test.exe` beside its loaded Windows image with
unchanged arguments and inherited stdin, stdout, stderr, cwd and environment.
Runner exit codes are preserved; image/process failures produce a `coil:`
diagnostic and exit 1. Option validation, discovery, manifests and retained
`--native-suite` inventories remain owned by the runner.

This public native command refuses a hosted override returned by `prim_env_get`
for `OURO_TEST_CHECK`, `OURO_TEST_BUILD`, `OURO_PKG_CHECK` or
`OURO_HOSTED_COMPILER_WRAPPER`, reporting the first key in that order and exiting
1 before launching the runner. The standalone hosted runner keeps its existing
compatibility behavior. `OURO_TEST_OUT` and the runner's output and report
settings retain their meanings.

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
An unreadable or exhausted native inventory fails explicitly. Native checks and
builds use sibling `coil.exe` and pass fixture stdin through bounded capture.
The hosted wrapper handles ordinary path discovery in the shell and passes a
list to the runner. Manifest and native-suite modes are forwarded directly.
Repository-owned check batches use the same native tool in strict manifest
mode, for example:

```sh
python3 scripts/ouro_smith.py manifest --prefix=IMP.,ERGO.,REC. \
  --out=_build/surface_suite --label=SURFACE_SUITE
```

Repository and compiler tests use additional suites documented in
[Contributing](../CONTRIBUTING.md). The retained `ouro1-test` suite row
restarts the loaded standalone runner on its success fixture and requires
`test: ok`. Public `coil test` dispatch needs its own loaded-image, argv,
hosted-override refusal and full runner execution probes; that standalone row
does not establish them.
For an explicit manifest, `--root` defaults to its containing directory.
The native formatter, fixer, documentation, lint, and test selftests receive
generated inputs from [OuroSmith](ouro_smith.md); the suite wrappers prepare
those inputs before invoking the native assertions.

## Documentation generator

Generate a preview under `_build/api` or check committed API pages with the
documentation suite.

```sh
sh scripts/ouro1.sh doc --out _build/api std/io.ouro
sh scripts/doc_suite.sh
```

`doc` extracts declaration-adjacent documentation comments and writes one
Markdown page per module plus an index. `docs/api/` is the committed generated
reference for the standard library. `--check` reports drift without modifying
files. A missing source or an unreadable `--files-from` list is an error.
The [CLI](../tools/doc.ouro) and LSP share the [declaration scanner](../tools/doc/model.ouro).
The suite runs the [generator self-tests](../tools/doc/selftest.ouro) and checks
the committed pages. If the shared scanner changes, also run
`sh scripts/lsp_suite.sh` for hover and symbol lookup.
[Build](build.md#generated-artifacts-and-stage-loop) owns committed API regeneration.

## Repository gates and CI runner

Use the [validation matrix](ci.md#validation-matrix) to select a focused check.
The [local profiles](ci.md#local-profiles) define the combined checks, and
[native repository gates](native_repo_gates.md) describe the native inventory
and migration boundary.

## Core toolchain performance evidence

The timing runner, before/after comparison, and report interpretation live in
[CI performance evidence](ci.md#performance-evidence). Build receipts and cache
freshness are documented in [Build and bootstrap](build.md#cache-model).

## Packages

Use the [package guide](pkg.md#commands) for `coil`/`ouro1 pkg` commands,
local registries, installation, locks, and verification.

## Language server

On Windows x86-64, provision `coil.exe`, `ouro-lsp.exe`, and `ouro-fmt.exe`
before starting the server. Run these commands from the workspace root, with
the tools at `_build/native` and an existing `_build` directory for scratch
files. [Standalone native tools](#standalone-native-tools)

```powershell
$env:OURO_ROOT = (Get-Location).Path
.\_build\native\coil.exe lsp
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

Positions use UTF-16 code units, including after Unicode string contents;
compiler byte columns are converted before publishing diagnostics. Definition
and symbol URIs percent-encode path bytes so spaces, `%`, `#`, `?`, and Unicode
retain their file identity. Malformed JSON-RPC request envelopes receive
`Invalid Request` (`-32600`); valid notifications receive no response.

Completion keeps name-prefix suggestions. In a direct top-level definition
with a simple explicit result type, such as `def value : Choice := Re`, it also
suggests matching nullary constructors from a local, non-parameterized
`inductive Choice` declaration. This editor hint does not infer types in nested
expressions or resolve constructors from imports. Complex constructor
signatures and families with more than 256 arms keep ordinary prefix completion.

The native server runs sibling `coil.exe` for checks and `ouro-fmt.exe` for
formatting through bounded captured processes. The protocol adapter consumes
child output before publishing responses. Missing checker tools or check
process failures produce diagnostics. A formatter failure returns a `null`
result. `OURO_LSP_OURO1` no longer selects a checker.

Hover, definition, and completion can reuse a file's declarations and import
spellings when the path and source bytes match a cached entry. A workspace
symbol request can share those entries across open documents within the
request. The server uses the open buffer for each document, authorizes import
paths again, and reads the imported files from disk. The cache retains at most
64 entries, with a cost limit per entry for text and rows.

The explicitly configured `OURO_ROOT` remains the authorization boundary
for file URIs,
imports, diagnostics, formatting, and symbol indexing. Absolute imports,
traversal, links/reparse points, non-file URIs, and canonical paths outside that
root are rejected. Protocol frames are limited to 1 MiB, one retained document
to 512 KiB, and all open document text to 2 MiB. Formatting and unsaved-buffer
checks use exclusive scratch files under the root's existing `_build` directory
and remove them after the child command completes. A failure to create or write
checker scratch publishes `TOOL_ERROR`. The same failure during formatting
returns a `null` result.

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
