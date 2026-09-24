# Practical Ouro programs

These small CLI and file programs exercise stdin, checked files, config,
CSV/JSON, typed arguments, validation, and process commands. For reusable APIs,
see the [practical standard library](practical_stdlib.md#modules).

## Runnable examples

Build and run a stdin word-count style tool:

```sh
sh scripts/build_tool.sh samples/examples/io_word_count.ouro _build/tools/io_word_count
./_build/tools/io_word_count < samples/examples/io_word_count.stdin
```

Expected output:

```text
bytes=37
lines=2
words=7
```

Build and run a checked file/config lookup tool:

```sh
sh scripts/build_tool.sh samples/examples/file_kv_lookup.ouro _build/tools/file_kv_lookup
./_build/tools/file_kv_lookup
```

Expected output:

```text
mode=release
threads=4
missing=missing
```

The runnable programs in `samples/examples/` are:

| Program | Task |
| --- | --- |
| `practical_cli_file.ouro` | Checked file read and text transform from CLI arguments |
| `practical_stdin_aggregate.ouro` | Parse stdin lines and report a numeric aggregate |
| `practical_config_report.ouro` | Read config and render typed values |
| `workflow_stdin_report.ouro` | Filter comments and blanks, parse `Nat` fields, render a report |
| `workflow_json_table_transform.ouro` | Select table data from bounded JSON/CSV inputs |
| `workflow_process_runner.ouro` | Run a command spec and report stdout or error |
| `workflow_validation_report.ouro` | Accumulate validation failures |
| `workflow_workspace_tool.ouro` | Create a workspace, write and copy files |
| `workflow_config_transform.ouro` | Read config and transform a workspace file |

The [example gallery](../samples/examples/README.md) indexes the other
samples. For one JSON/CSV/config/filesystem/process CLI, see
[Practical application surface](practical_application_surface.md).

## Test path

The [sample suite](ci.md#local-profiles) compares committed `.golden` output
where present.

For generated properties and API documentation checks, see
[OuroSmith](ouro_smith.md) and [CI](ci.md#local-profiles).

## Current limits

These examples process small, bounded inputs. The
[standard-library limits](practical_stdlib.md#current-limits) and
[runtime contract](effects_design.md#runtime-surface) define the underlying
behavior.
