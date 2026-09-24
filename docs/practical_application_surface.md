# Practical application surface

`tools/app_surface.ouro` is a small CLI for JSON, CSV, config, filesystem scans,
and process commands. The [practical standard library](practical_stdlib.md)
owns the reusable APIs it composes.

## What it exercises

`tools/app_surface_lib.ouro` composes the modules imported by
`std/practical.ouro`, plus `std/fs_walk.ouro` for bounded deterministic scans.
It returns `AppSurfaceError` for JSON and CSV failures; the CLI renders those
errors with `app_surface_error_message`. See the [module guide](practical_stdlib.md#modules)
for API choices and limits.

## Build and run

```sh
sh scripts/build_tool.sh tools/app_surface.ouro _build/tools/ouro-app-surface
./_build/tools/ouro-app-surface --help
```

Useful command shapes:

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

The tool reports ordinary usage errors on stderr and exits nonzero. JSON report
commands write compact JSON to stdout so they can be consumed by scripts or
golden-file tests.

## Writing a similar tool

Use [`std/cli.ouro`](practical_stdlib.md#cli-arguments) for typed arguments,
[`std/fsx.ouro`](practical_stdlib.md#filesystem-workspace-and-config) for checked
file operations, and the [JSON/CSV helpers](practical_stdlib.md#json-csv-and-tables)
for parsed data. This tool writes human diagnostics to stderr and compact
machine reports to stdout.

## Safety model

The app-surface helper for workspace-relative paths normalizes host separators,
rejects absolute paths, and rejects normalized `..` escapes before joining with a
workspace root. Filesystem scans use `fs_walk_checked`, so truncation, unreadable
entries, and unsafe paths are represented explicitly.

Process execution uses the [command specification](practical_stdlib.md#process-runners-and-command-workflows).

## Data limits

`json minify` emits compact JSON; it does not pretty-print. CSV and config
follow the bounded [stdlib formats](practical_stdlib.md#json-csv-and-tables).

## Acceptance checks

The pure composition checks live in:

```sh
python3 scripts/ouro_smith.py replay --layer surface --seed 1 --case stdlib_application
sh scripts/ouro1.sh test tests/practical_application_surface_tests.ouro
```

The [build command](#build-and-run) above compiles the tool itself.
