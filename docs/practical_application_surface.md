# Practical application surface

`tools/app_surface.ouro` validates JSON, reports on CSV and configuration,
scans directories, and runs commands. It composes checked APIs from the
[practical standard library](practical_stdlib.md).

## What it exercises

`tools/app_surface_lib.ouro` composes the modules imported by
`std/practical.ouro`, plus `std/fs_walk.ouro` for bounded deterministic scans.
JSON minification and CSV column selection return a typed `AppSurfaceError`
when input cannot produce the requested output. The CLI renders these errors
with `app_surface_error_message`. See the [module guide](practical_stdlib.md#modules)
for API choices and limits.

## Build and run

Use a POSIX-compatible shell in the repository root with the
[bootstrap toolchain available](getting_started.md#build-the-bootstrap-toolchain).

```sh
sh scripts/build_tool.sh tools/app_surface.ouro _build/tools/ouro-app-surface
./_build/tools/ouro-app-surface --help
```

The help command prints the command list and exits with status 0.

Substitute the paths to your own small JSON, CSV, and config input files.
The CSV examples expect header columns named `name` and `status`. For
`run echo`, a POSIX C host looks up an external `echo` on `PATH`. The
Windows C host uses a POSIX shell, such as the one installed with Git for
Windows. Set `OURO_POSIX_SH` to its executable path if needed.

```sh
./_build/tools/ouro-app-surface json validate data/report.json
./_build/tools/ouro-app-surface json minify data/report.json
./_build/tools/ouro-app-surface csv report data/table.csv
./_build/tools/ouro-app-surface csv select data/table.csv status
./_build/tools/ouro-app-surface csv tsv data/table.csv name,status
./_build/tools/ouro-app-surface config normalize tool.conf
./_build/tools/ouro-app-surface config report tool.conf
./_build/tools/ouro-app-surface fs scan std
./_build/tools/ouro-app-surface run echo ouro
```

Usage errors and typed file-read errors go to stderr with exit status 1.
`json validate` emits compact JSON on stdout and exits 0 for accepted input
or 1 for invalid JSON. `fs scan` emits its report on stdout and exits 0 for
a complete walk or 1 for a returned incomplete walk. `run echo` writes a
JSON process report and exits with the status in that report.

## Writing a similar tool

Use [`std/cli.ouro`](practical_stdlib.md#cli-arguments) for typed arguments,
[`std/fsx.ouro`](practical_stdlib.md#filesystem-workspace-and-config) for checked
file operations, and the [JSON and CSV helpers](practical_stdlib.md#json-csv-and-tables)
for parsed data.

## Safety model

The CLI reads the paths supplied to its JSON, CSV, and config commands
through `fsx_read_text`. `fs scan` uses `fs_walk_checked` from the supplied
root and reports truncation, unreadable entries, and unsafe paths. The caller
controls the file paths and scan root. Each command uses its supplied path
directly.

The application tests exercise `app_path_within_workspace` separately from
the CLI. That helper rejects absolute paths and lexical `..` escapes before
joining a path to a workspace root.

Process execution uses a program and an argument list through the
[command specification](practical_stdlib.md#process-runners-and-command-workflows).

## Data limits

`json minify` emits compact JSON. Each CSV record occupies one input line.
Configuration uses line-based `key=value` entries. See the supported
[JSON and CSV formats](practical_stdlib.md#json-csv-and-tables) and
[config format](practical_stdlib.md#filesystem-workspace-and-config).

## Acceptance checks

From the repository root, run the generated standard-library application
case and the application helper tests with the bootstrap toolchain.

```sh
python3 scripts/ouro_smith.py replay --layer surface --seed 1 --case stdlib_application
sh scripts/ouro1.sh test tests/practical_application_surface_tests.ouro
```

The [build command](#build-and-run) above compiles the tool itself.
