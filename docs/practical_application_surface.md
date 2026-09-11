<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=APP%20SURFACE&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="APP SURFACE banner"
  />
</p>

# Practical application surface

This page shows the current end-to-end shape for small Ouro tools that read files,
parse data, validate inputs, emit reports, and run host commands through argv
lists. It complements the module-level [practical standard library](practical_stdlib.md)
guide with one concrete application surface.

The acceptance target is `tools/app_surface.ouro`. It is deliberately small:
its purpose is to prove that the reusable standard-library layers compose into
real command-line programs without copying Python behavior, shelling out for core
logic, or adding a broad runtime fallback.

## What it exercises

`tools/app_surface_lib.ouro` composes existing reusable modules:

- `std/practical.ouro` for CLI, config, text, filesystem, table, JSON, process,
  validation, report, and workspace helpers.
- `std/fs_walk.ouro` for deterministic checked scans that reject unsafe walk
  states instead of returning partial success.
- `std/json.ouro` and `std/jsonx.ouro` for bounded JSON parsing and compact
  machine-readable reports.
- `std/csv.ouro`, `std/table.ouro`, and `std/tablex.ouro` for header-aware CSV
  projection and TSV output.
- `std/processx.ouro` for command specs represented as program plus argv list.
- `AppSurfaceError` for typed JSON and CSV failures, rendered at the CLI
  boundary by `app_surface_error_message`.

These modules do not introduce a new runtime primitive.

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

A small Ouro CLI can follow the same pattern:

1. Parse argv with `cli_from_argv`, passing the names of boolean options.
2. Use `cli_required_pos`, `cli_required`, and typed option helpers instead of
   silently defaulting missing input.
3. Read and write through `fsx_read_text`, `fsx_write_text`, `workspace_*`, or
   checked lower-level `std/fs.ouro` helpers.
4. Parse data with `parse_json`, `jsonx_*`, `csv_parse`, `table_*`, and
   `tablex_*`.
5. Return human diagnostics through `process_err_line` and machine reports
   through `jsonx_render`.
6. Run host commands with `CommandSpec` and `process_run_spec`; never rebuild a
   shell command string from user input.

## Safety model

The app-surface helper for workspace-relative paths normalizes host separators,
rejects absolute paths, and rejects normalized `..` escapes before joining with a
workspace root. Filesystem scans use `fs_walk_checked`, so truncation, unreadable
entries, and unsafe paths are represented explicitly.

Process execution goes through `CommandSpec`, which stores a program and argv
list separately. `command_render` is only display text; it is not a shell escape
API.

## Data limits

JSON support uses the existing bounded parser and compact writer. It validates
and minifies JSON but does not add a pretty-printer here.

CSV support uses the existing bounded CSV layer. It handles quoted fields and
escaped quotes for the supported format, but it is intentionally not a full
spreadsheet or RFC-recovery framework.

Config support is the small line-based `key=value` format from `std/config.ouro`.
It is suitable for tool settings and reports, not for TOML/YAML replacement.

## Acceptance checks

The pure composition checks live in:

```sh
python3 scripts/ouro_smith.py replay --layer surface --seed 1 --case stdlib_application
sh scripts/ouro1.sh test tests/practical_application_surface_tests.ouro
```

The tool itself can be compiled with:

```sh
sh scripts/build_tool.sh tools/app_surface.ouro _build/tools/ouro-app-surface
```

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
