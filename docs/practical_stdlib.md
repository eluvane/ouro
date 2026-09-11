<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=STDLIB&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="STDLIB banner"
  />
</p>

# Practical standard library surface

This guide describes the reusable userland capabilities around the core standard library. The goal is to make small Ouro programs less dependent on one-off helpers in each source file.

## Modules

- `std/types.ouro` provides the shared `Nat`, `Bool`, `List`, `Pair`, `Maybe`, `Either`, `Ordering`, and `Unit` declarations and their representation identities. `std/prelude.ouro` and `std/data.ouro` retain these types through imports and provide the existing executable helpers.
- `std/result.ouro` adds Result-style combinators over `Either E A`. `Right` is the success value and `Left` carries a typed error.
- `std/collections.ouro` adds indexing, filter-map, indexed mapping, chunking, adjacent-pair helpers, deduplication, and collection helpers for `Either` results.
- `std/num.ouro` adds comparison aliases, checked division/modulo, range construction, and basic aggregations for `Nat` lists.
- `std/text.ouro` adds practical string/token helpers, line helpers, character predicates over strings, and typed parsing for natural numbers and booleans.
- `std/cli.ouro` adds typed command-line lookup over `std/args.ouro`, including required options, positional arguments, `Nat` parsing, boolean parsing, and usage/error text.
- `std/config.ouro` adds bounded `key=value` config parsing, typed getters, rendering, merge helpers, and `ConfigError` values.
- `std/fsx.ouro` adds higher-level checked filesystem helpers for text files, line files, config files, filtered listing, remove-if-exists, and non-empty reads.
- `std/table.ouro` adds header-aware helpers over the CSV parser: named cells, records, named columns, projections, and record maps.
- `std/lines.ouro` adds bounded line-oriented processing over in-memory stdin/file text: filtering, numbering, field extraction, chunks, transforms, and reports.
- `std/validation.ouro` adds accumulated validation over `Either (List E) A` for config/args/data checks that should report multiple errors together.
- `std/report.ouro` adds small report builders, duration wrappers, elapsed timing, and key/value or section rendering.
- `std/configx.ouro` adds schema-lite config validation and environment override helpers on top of `std/config.ouro`.
- `std/jsonx.ouro` adds practical JSON constructors, typed getters, object/array access, and path lookup on top of the bounded JSON parser.
- `std/tablex.ouro` adds table projection/selection helpers with validation for required columns.
- `std/processx.ouro` adds shell-free command specs, checked command execution, stdout capture helpers, and simple process-plan rendering/execution.
- `std/executable.ouro` queries the current Windows image path with typed allocation, query, conversion and cleanup errors.
- `std/workspace.ouro` adds workspace-root helpers, temp path helpers, backup-before-overwrite, transform-write, filtered listing, copy-tree, and checked cleanup wrappers.
- `std/workflow.ouro` adds a small command workflow abstraction: context, errors, result/report rendering, exit codes, and typed lifting from FS/config/process errors.
- `std/practical.ouro` imports the practical helper modules as a convenience umbrella.

The small language examples also use supported source syntax:
`std/module_demo.ouro` qualifies imported constructors through `as Util`, and
`std/mutual_demo.ouro` represents even/odd evidence with one indexed
`ParityEvidence` family. Its `Even` and `Odd` type aliases retain the example
value types; constructors are `EvenZero`, `EvenSucc`, and `OddSucc`.

## CLI arguments

Use `cli_from_argv` when a native program reads `argv`, and pass the option names that should behave as boolean flags.
Strict command entry points can call `args_argv_options_complete` before
parsing to reject non-boolean long options whose value is absent.

```ouro
import "../std/args.ouro";
import "../std/cli.ouro";

let parsed : Args := cli_from_argv ["verbose"] av in
match cli_required_nat parsed "limit" with
| Left e => cli_error_message e
| Right n => str_of_nat n
end
```

`cli_required`, `cli_required_nat`, `cli_required_bool`, and `cli_required_pos` return `Either CliError A`, so callers can keep error handling explicit instead of silently defaulting.

## Line/data processors

`std/lines.ouro` is a bounded line-processing layer over existing text IO. It does not claim true streaming: `line_read_stdin`, `line_process_stdin`, `line_read_file_checked`, and `line_transform_file_checked` read through the existing runtime path and then operate on `List String`.

Use it for `grep`/`cut`/`count`/`filter`/`report`-style tools:

```ouro
let rows : List String := line_data_lines "#" (lines_from_text input) in
let values : List Nat := line_nat_values rows in
report_render (report_add_nat "sum" (nat_sum values) report_empty)
```

Useful helpers include `line_number`, `line_nonblank_only`, `line_without_comments`, `line_fields_ws`, `line_field_csv_or`, `line_chunks`, `line_tail`, `line_transform_text`, and `line_transform_report`.

## Strings and text

The experimental Windows native console adapters preserve exact input and
output bytes. [Effects and IO](effects_design.md#runtime-surface) documents
line limits, EOF, failures, deferred actions, flush, exit, strict Unicode
arguments, and environment lookup behavior.

`std/runtime.ouro` declares `String` and its pure operations as checked
intrinsics. Existing imports and helper signatures stay the same. Programs
with a standalone prelude must use the registered `ouro.string` type instead
of an opaque `axiom String : Type;`; import `std/string.ouro` for the standard
declarations. String lengths and offsets count bytes. See
[the syntax contract](syntax.md#numbers-and-strings) for literal checking and
the transitional C runtime's embedded-NUL limitation.

The experimental Windows native backend implements these pure String
intrinsics with byte-preserving managed storage, including embedded NUL.
Byte access outside the string returns zero; slicing clamps the requested
range. Search and ordering compare unsigned bytes. Splitting uses a byte-valued
separator; a Nat above 255 matches no byte. Tokens split on space, tab, CR, and
LF. Byte-list construction takes each Nat modulo 256. Decimal rendering
preserves the complete Nat value, including values beyond machine-word range.

`std/text.ouro` is the preferred module for small text-processing tools. It covers whitespace tokenization (`str_tokens`), trimmed lines (`str_lines_trimmed`), nonblank lines (`str_nonblank_lines`), split-last (`str_split_last`), safe prefix/suffix removal, simple delimited extraction (`str_between`), and typed parsing (`str_parse_nat`, `str_parse_bool`).

## Lists and data

Use `std/collections.ouro` when a program needs common list operations that are intentionally outside the small prelude: `nth_maybe`, `filter_map`, `map_indexed`, `indexed`, `find_index`, `split_at`, `chunks_of`, `list_take_last`, `list_drop_last`, `adjacent_pairs`, `dedup_adjacent`, `partition_map`, and `list_collect_results`.

## Numbers

Use `std/num.ouro` for practical `Nat` helpers: `nat_eq`, `nat_lt`, `nat_le`, `nat_compare`, `nat_min`, `nat_max`, `nat_clamp`, checked division/modulo, `nat_range_count`, `nat_range_closed`, `nat_sum`, `nat_product`, `nat_min_list`, `nat_max_list`, `nat_count`, and `nat_mean_floor`.

## Filesystem, workspace, and config

`std/fs.ouro` remains the low-level checked filesystem layer. `std/fsx.ouro` adds convenience wrappers that compose those checked operations with common data shapes.

The experimental Windows native `fs_exists` and `fs_is_dir` actions use strict
Unicode path attributes and preserve directory bits on junctions. Empty paths
and ordinary query errors return `False`; the [runtime contract](effects_design.md#runtime-surface)
describes invalid encoding, cleanup and trailing-separator behavior.

The experimental Windows native backend supports `fs_read`, `fs_write`,
`fs_list`, and `prim_fs_listable`, with strict UTF-8 paths. File contents retain
all bytes. Listing returns Unicode entry names in the unspecified host order;
it drops `.` and `..` and does not sort. Stored actions reopen or enumerate
again when run. Listability returns False when its directory/access probe
fails; malformed arguments and resource/cleanup errors terminate with status
73. Listing failures also terminate with 73 instead of returning partial names.
Writing checks the opened final-component reparse point before truncation.
See [the IO contract](effects_design.md#runtime-surface) for concurrent changes,
cleanup and the transitional C differences.

Native `fs_mkdir_p` attempts parent creation; `fs_remove` removes files or
empty directories without recursive deletion. Their Unit result does not
confirm success, so use the checked wrappers when the postcondition matters.
Native `fs_copy` preserves binary contents and overwrites through Windows;
`fs_copy_checked` also creates missing target parents. Invalid paths and
copy/resource failures terminate with status 73. These actions defer work
until execution and may be reused. They provide no atomicity or rollback;
see [the runtime contract](effects_design.md#runtime-surface) for error and
reparse behavior.

`fs_rename_checked source target` replaces a file on the same volume and
returns `Either FsError Unit`. Both paths must be nonempty, the source must
exist, and the target must not be a directory. Target parents must already
exist. OS refusal is an error; the operation does not fall back to copying or
deleting files. `prim_fs_rename` exposes the underlying status (`0` for success).
See [the runtime contract](effects_design.md#runtime-surface) for host differences.

Native `prim_fs_realpath` resolves Unicode files and directories, follows
links, and returns normalized UTF-8 with forward slashes. Its stored action
resolves again on each execution. Empty paths and OS unavailability return
an empty String; malformed paths, conversion, raw storage and cleanup
failures exit 73. See [the runtime contract](effects_design.md#runtime-surface)
for resource ownership and concurrent changes.

In the experimental Windows native path, `prim_fs_kind` queries a strict UTF-8
path when its action runs. Reusing the action queries the path again. It returns
`0` for an empty path or OS query failure, `1` for a file, `2` for a directory,
and `3` for a reparse point, without following its target. Embedded NUL, invalid
UTF-8, allocation and cleanup failures terminate with status 73.

Security-sensitive inventory code should import `std/fs_walk.ouro` and use
`fs_walk_checked`. It returns
`FsWalkComplete`, `FsWalkTruncated`, `FsWalkUnreadable`, or `FsWalkUnsafe`, sorts
children deterministically, rejects links/reparse points and canonical escapes,
and bounds the total visited entries. The compatibility `fs_walk` helper returns
an empty list for every non-complete result; it never exposes a partial list as
success.

```ouro
import "../std/fsx.ouro";

fsx_read_config "tool.conf"
```

A config file is parsed as line-based `key=value`. Blank lines and `#` comments are ignored. `config_get_nat` and `config_get_bool` return typed errors when a value is missing or malformed.

`std/configx.ouro` adds schema-lite validation where multiple fields can be checked in one pass:

```ouro
configx_validate_schema cfg
  [ configx_field "input" ConfigAsString
  , configx_field "limit" ConfigAsNat
  , configx_field "enabled" ConfigAsBool
  ]
```

`std/workspace.ouro` gives file tools one root object and consistent path helpers:

```ouro
match workspace_make "_build/my_tool" with
| Left e => fs_error_message e
| Right w => workspace_file w "out/report.txt"
end
```

The backup/temp helpers are intentionally conservative: they provide checked userland behavior on top of the existing runtime, but they do not promise POSIX-grade atomic replacement or cryptographically unique temp files.

## JSON, CSV, and tables

`std/csv.ouro` provides bounded CSV parsing/printing. `std/table.ouro` adds header-aware operations, so programs can use column names instead of numeric column positions.

```ouro
let rows : List (List String) := table_from_csv text in
table_col_named rows "status"
```

`std/jsonx.ouro` adds small typed accessors for bounded JSON data:

```ouro
let doc : Json := jsonx_parse_or_null text in
jsonx_get_string doc "name"
```

The base JSON parser caps recursive structure at 128 levels. JSON string
decoding is a linear, non-recursive runtime primitive, so a large quoted value
does not build a quadratic chain of slices.

`std/tablex.ouro` adds column validation and reusable transforms:

```ouro
tablex_csv_project_required text ["name", "status"]
```

An empty or header-only table still has to contain every required column name.
`table_cell` returns `Nothing` when a data row is shorter than the named
column; it does not invent an empty string.

This is deliberately not a full serde framework; it is a small API for practical config/report/data utilities.

## Current executable path

Import `std/executable.ouro` and run `executable_path_checked` to obtain
`IO (Either ExecutablePathError String)` on the experimental Windows native
backend. The result is the fully qualified loaded image path in UTF-8,
queried from Windows when the action runs. Its spelling can retain short
names or an extended-length prefix; it is not a canonical file identity.

The query uses a 32768-unit UTF-16 buffer and rejects truncation. Empty,
malformed or embedded-NUL paths and invalid conversion counts are errors.
`executable_path_error_code` returns a stable category and
`executable_path_error_message` renders a diagnostic. Errors do not expose
a numeric Windows last-error value. A buffer-release failure remains an
error and retains any earlier query or conversion failure. Process-terminal
allocation exhaustion follows the runtime's existing behavior.

The API observes a loaded path; consumers must separately establish file
identity or verify executable bytes when those properties matter. See
[the platform assumptions](tcb.md#current-host-assumptions).

## Process runners and command workflows

Use `std/processx.ouro` to avoid shell strings by default. A command is represented as a program plus argv list:

```ouro
let cmd : CommandSpec := command_spec "echo" ["ouro"] in
process_stdout_checked cmd
```

`command_render` and `process_plan_render` are for display/dry-run output. They are not shell-escaping APIs and should not be fed back into a shell.

`prim_process_capture` returns `Pair Nat (Pair String String)`: exit status,
stdout, and stderr. `std/types.ouro` registers the required `ouro.pair`
representation. `prim_proc_exec` adapts this checked intrinsic to the
existing `ProcResult` shape, so `proc_exec`, `process_run`, and their checked
wrappers keep their result types. A stored action runs the command again each
time it is executed.

`process_run_inherited` and `process_run_spec_inherited` run a foreground
child with the caller's stdin, stdout, stderr, current directory and environment.
They return `Either ProcessRunError Nat`, preserving every completed child exit
code, including 259. The `_checked` variants report nonzero child exits as
`ProcessExited`; setup and wait failures use `ProcessUnavailable` with the OS
status. Arguments stay separate from the executable and are never shell text.

The native Windows adapter owns a job for the child and its descendants.
Closing the foreground scope or terminating its parent closes that job; the
adapter does not detach background descendants. Children share the console
and ordinary Ctrl+C handling. This API has no separate timeout/cancel token.
Job assignment occurs during creation, requires Windows 10 / Server 2016 or
newer, and fails explicitly when enclosing job restrictions prevent it.
The temporary C host reports OS status 120 (not implemented) for this API.

`process_run_captured_bounded` and `process_run_spec_captured_bounded`
return `Either ProcessCaptureError ProcessCaptureResult`. Their `_with_input`
variants take an exact binary stdin String; the default input is empty with
immediate EOF. `process_capture_proc_result` exposes the completed exit and
exact stdout/stderr bytes, while `process_capture_peak_bytes` exposes measured
peak Job commit. A nonzero child exit, including 259, remains a completed result.

`ProcessCaptureLimitsOf timeout_ms memory_mib cpu_count stdout_bytes stderr_bytes`
requires a positive finite timeout, positive memory cap, and CPU count 1.
Zero byte caps require empty streams. `process_capture_default_limits` supplies
one CPU and 3 GiB while keeping timeout and each stream cap explicit. Timeout,
OS failure, incomplete cleanup, observed memory violation, and stream overflow
are typed failures. Overflow never returns truncated success. The owner waits
for the contained tree to stop before reading either capture file, with a
separate 5-second cleanup budget. Cleanup waits for the process handle,
not only job accounting, and may stop the direct child with a finite
`TerminateProcess` when the job did not contain it. Capture files are
`DELETE_ON_CLOSE` and are flushed before their length is measured, so a
killed writer cannot hide bytes it already wrote. The execution timeout starts at launch;
argument/input preparation and filesystem IO are not separately time-bounded.

The memory cap is aggregate committed Job memory, not resident memory. Observed
Windows Job memory events always fail, including a child's expected exit 73.
Windows does not guarantee delivery of those events; a denied allocation can
therefore lack a resource attribution event. Consumers requiring complete
attribution must retain that limitation in their acceptance policy. This API
does not add a streaming pipeline. Its temporary C-host action returns typed
OS status 120 without launching a process.

The transitional C process host uses per-request private capture files. On
POSIX it executes the supplied argv directly; the Windows compatibility path
keeps command and capture files inside a unique private directory and removes
them after collection. Native process lowering uses the Windows runtime;
the bounded native API provides the separately documented timeout and tree
cleanup contract.

`std/workflow.ouro` provides a small layer for tools that parse args/config, validate, run actions, and print a report or error with a conventional exit code. It is not a task runner, scheduler, shell, or package-manager layer.

## HTTP messages and requests

`std/http.ouro` provides HTTP message parsing and `http_post url headers body`.
Its checked `prim_http_request` intrinsic uses WinHTTP on the experimental
native Windows path, with OS-owned TLS certificate verification. It does not
invoke `curl` or stage request bodies in temporary files.

`http_status` and `http_body` preserve server error responses as well as
successful ones. A transport failure has status `0` and an explicit
`http_reason`. `http_resp_headers` is currently empty for these requests.
The transitional C host has no HTTP transport. Its deferred action returns
status `0`, an empty body, and `HTTP transport unavailable in C host` as the
reason. Native execution and isolated-host acceptance remain separate checks.

## Validation and reports

Use `std/validation.ouro` when user-facing checks should accumulate instead of failing fast:

```ouro
validation_collect_unit String
  [ validation_require String "missing --input" has_input
  , validation_require_nonempty "empty --name" name
  ]
```

Use `std/report.ouro` for deterministic key/value summaries:

```ouro
report_render
  (report_add_nat "rows" row_count
    (report_add "status" "ok" report_empty))
```

`time_now_nat` and `time_elapsed` wrap the existing time primitive. They do not add timezone or calendar semantics.
In the experimental Windows native path, `now` is a deferred action returning
decimal Unix-epoch milliseconds, rounded down. It reads the clock again when
a stored action is reused; wall-clock changes can affect elapsed measurements.

`std/async.ouro` provides sequential Windows native delays. `sleep_s n`
blocks for `n` one-second `Sleep` intervals; `sleep_s 0` makes no OS wait call.
`delay_then A n act` runs `act` afterward and preserves its result. Constructing
or reusing an action does not consume its delay: each execution waits again.
The input stays a full `Nat`, including values beyond 32 or 64 bits; only the
fixed 1000-millisecond interval is converted to a Windows word. Timer precision
and scheduling can affect observed duration. A runtime constant-conversion
failure emits a diagnostic and exits with status 73 before a successor runs.
This helper is blocking and sequential, with no cancellation API or scheduler.
It requires the Windows native backend and launches no external `sleep` command.

## Acceptance programs

The acceptance programs exercise reusable APIs together rather than acting as standalone demos:

- `tests/practical_stdlib_tests.ouro` combines text, ranges, config, CLI parsing, table records, and user-level tests.
- `samples/examples/practical_cli_file.ouro` combines CLI args, checked file read, text transform, stdout/stderr, and exit codes.
- `samples/examples/practical_stdin_aggregate.ouro` combines stdin, line parsing, filtering, numeric aggregation, and formatted reports.
- `samples/examples/practical_config_report.ouro` combines CLI args, checked config-file read, typed config getters, and report rendering.
- `tests/workflow_stdlib_tests.ouro` checks the reusable workflow modules together.
- `samples/examples/workflow_stdin_report.ouro` reads stdin, filters comments/blanks, parses Nat fields, aggregates, and renders a report.
- `samples/examples/workflow_json_table_transform.ouro` combines bounded JSON getters, table selection, validation-shaped data, and report output.
- `samples/examples/workflow_process_runner.ouro` builds a shell-free command spec, runs it checked, captures stdout, and reports it.
- `samples/examples/workflow_validation_report.ouro` accumulates multiple validation failures and renders all errors.
- `samples/examples/workflow_workspace_tool.ouro` creates a workspace, writes/copies files, and reports outputs.
- `samples/examples/workflow_config_transform.ouro` combines checked workspace IO, config, line filtering, transform, write, and report.

## Running checks

Typical commands:

```sh
sh scripts/ouro1.sh check tests/workflow_stdlib_tests.ouro
sh scripts/build_tool.sh samples/examples/workflow_stdin_report.ouro _build/tools/workflow_stdin_report
sh scripts/build_tool.sh samples/examples/workflow_process_runner.ouro _build/tools/workflow_process_runner
sh scripts/samples_suite.sh
python3 scripts/api_baseline_regen.py --check
sh scripts/doc_suite.sh
```

OuroSmith generates typed helper compositions and compares their values and
error paths with Python contracts:

```sh
python3 scripts/ouro_smith.py replay --layer surface --seed 1 --case stdlib_workflow
python3 scripts/ouro_smith.py replay --layer surface --seed 1 --case stdlib_tables
python3 scripts/ouro_smith.py replay --layer surface --seed 1 --case runtime_io
```

## Current limits

The practical standard-library surface does not change kernel semantics, typechecker semantics, core syntax, generated C artifacts, package-manager architecture, formatter behavior, or the trust boundary. Filesystem operations still use the existing runtime primitives and therefore keep the same host/runtime limits. Line processing is bounded/in-memory. Bounded native capture can pass a complete binary stdin String; process helpers do not build streaming stdout-to-stdin pipelines. Config, JSON, CSV, and table helpers are intentionally small and bounded; they are meant for practical small tools, not full TOML/YAML/SQL/serde replacement.

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
