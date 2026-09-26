# Practical standard library surface

This guide describes the reusable userland capabilities around the core standard library. The goal is to make small Ouro programs less dependent on one-off helpers in each source file.

## Modules

Choose a module by task; the generated [API reference](api/README.md) owns declaration signatures.

| Task | Modules |
| --- | --- |
| Shared types and results | `std/types.ouro`, `std/prelude.ouro`, `std/data.ouro`, `std/result.ouro` |
| Lists and iterators | `std/collections.ouro`, `std/iter.ouro`, `std/range.ouro` |
| Text and numbers | `std/string.ouro`, `std/text.ouro`, `std/num.ouro` |
| CLI and configuration | `std/args.ouro`, `std/cli.ouro`, `std/config.ouro`, `std/configx.ouro` |
| Files and workspace | `std/fs.ouro`, `std/fsx.ouro`, `std/fs_walk.ouro`, `std/fs_replace.ouro`, `std/workspace.ouro` |
| Data | `std/lines.ouro`, `std/json.ouro`, `std/jsonx.ouro`, `std/csv.ouro`, `std/table.ouro`, `std/tablex.ouro` |
| Process and reports | `std/process.ouro`, `std/processx.ouro`, `std/validation.ouro`, `std/report.ouro`, `std/workflow.ouro` |

`std/practical.ouro` imports the practical helpers as a convenience umbrella.
`std/string_prims.ouro` shares String primitive declarations with the runtime
without importing platform IO; `std/executable.ouro` supplies the current
image-path query. The pre-1.0 collection names and removed `_go` helpers are
recorded in the [changelog](../CHANGELOG.md).

## Fallible values

`std/result.ouro` treats `Either E A` as a result: `Left` carries the error
and `Right` carries the value. `result_unwrap_or_else E A fallback value`
returns the value on `Right`; on `Left` it calls `fallback : E -> A` with the
original error. The fallback is called only for `Left`. Use `result_bind` to
continue with another fallible operation and `result_map_err` to change an
error type while retaining the result.

`std/collections.ouro` provides `list_traverse_maybe A B f xs` for an ordered
list of fallible conversions. It returns `Just []` for an empty list, `Just`
with all converted values when every call succeeds, or `Nothing` at the first
failure. `list_traverse_result E A B f xs` preserves the first typed error and
does not call `f` on later elements. `list_try_fold_result E A S step initial xs`
and `list_try_fold_maybe A S step initial xs` likewise stop at the first failure;
an empty list returns `Right initial` or `Just initial`. `filter_map` drops
missing values when that is the intended behavior.

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
[the syntax contract](syntax.md#numbers-and-strings) for literal checking.

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

`list_windows A width xs` returns overlapping, complete windows. Width zero,
an empty input, and a width larger than the input return `[]`; for example,
width two on `[1, 2, 3]` returns `[[1, 2], [2, 3]]`. `adjacent_pairs` returns
the successive pairs `(1, 2)` and `(2, 3)` for that input.

`list_scan A S step initial xs` includes the initial state and every successive
state, so an empty input returns `[initial]`. `list_map_accum A S B step initial xs`
calls `step : S -> A -> Pair S B` once per element in source order and returns
the final state with the output values in that order. On an empty input it
returns `(initial, [])`.

`list_group_by A K eq key xs` puts all equal keys in one group, including
nonadjacent occurrences. Groups follow the first appearance of each key, and
members retain input order. `eq` must be an equivalence relation. This list
implementation searches existing groups for each element, so worst-case work
is quadratic in the input length.

## Lazy iterators

`std/iter.ouro` provides a pure pull iterator with explicit state, item, and
error types. `iter_from_list` wraps an existing list without building another
list. `iter_map`, `iter_filter`, and `iter_take` defer work until a pull;
filtering a rejected item returns a skip step, so one pull never searches an
unbounded prefix. `iter_take` counts emitted items, not skipped source steps.

```ouro
let source : Iterator (List Nat) String Nat :=
  iter_from_list String Nat ([1, 2, 3] : List Nat) in
let selected : Iterator (List Nat) String Nat :=
  iter_filter (List Nat) String Nat
  (fun (value : Nat) => eq_nat value 2) source in
collect_list (List Nat) String Nat 4 selected
```

This returns `Right [2]`. `collect_list` requires an explicit maximum number
of pulls and returns `Either (IterCollectError E) (List A)`. Each yield, skip,
failure, or end observation costs one pull. Zero pulls always gives
`IterPullLimit`, even for an empty source; a list of `n` items needs `n + 1`
pulls to observe its end. A source failure returns `IterSourceFailure` and
stops; a pull limit returns `IterPullLimit`. Neither returns a partial list as
success. `iter_take 0` does not pull its upstream source, though collecting
its own end still costs one pull. Iterators built from lists are finite, while
a custom iterator need not be; the pull limit bounds calls to its step
function, not the work performed inside each step.

Adapters do not build intermediate lists. Materialization builds a reversed
list and allocates another list when reversing it at completion; iterator
wrappers and step results also allocate. Pull traversal is bounded by
`max_pulls`, with callback and source-step costs in addition. No
constant-allocation or automatically fused pipeline is promised.

## Finite Nat ranges

`std/range.ouro` builds finite `Nat` range values for the pull iterator API.
`nat_range_exclusive start stop` omits `stop`; `nat_range_inclusive start stop`
includes it when the step lands exactly on it. Both start with step one. The
original endpoints determine direction: `start < stop` ascends, `start > stop`
descends, equal endpoints give an empty exclusive range or one inclusive item.
`nat_range_by step range` replaces the step magnitude and returns
`Either NatRangeError NatRange`; step zero returns `RangeZeroStep`. The public
`MkNatRange` constructor is checked again by `iter_from_nat_range`, and a
forged zero-step cursor returns `IterFail RangeZeroStep` when pulled.
A directly constructed cursor holds a resume position: the pull checks both
interval bounds, but does not require the position to align with the step.
`iter_from_nat_range` starts its cursor at the declared `start`.

```ouro
import "../std/practical.ouro";

def descending_range_example : Bool :=
  match iter_from_nat_range (nat_range_inclusive 5 0) with
  | Left _ => False
  | Right source =>
      match collect_list NatRangeCursor NatRangeError Nat 7 source with
      | Left _ => False
      | Right values =>
          list_eq Nat eq_nat values ([5, 4, 3, 2, 1, 0] : List Nat)
      end
  end;
```

`nat_range_by 3 (nat_range_inclusive 10 0)` yields `10, 7, 4, 1`; it does not
fabricate zero when the step passes the endpoint. An exclusive range `0` to
`10` by `3` yields `0, 3, 6, 9`. The source itself does not materialize a
list. `collect_list` returns a typed pull-limit error when its budget is
exhausted: an empty range needs one pull to observe `IterDone`, and `n`
yields need `n + 1` pulls. Each pull does constant work apart from Nat
arithmetic on the values; collecting allocates the final list as described
above. This lazy, directional API is separate from the eager
`nat_range_count` and `nat_range_closed` helpers in `std/num.ouro`.

## Numbers

Use `std/num.ouro` for practical `Nat` helpers: `nat_eq`, `nat_lt`, `nat_le`, `nat_compare`, `nat_min`, `nat_max`, `nat_clamp`, checked division/modulo, `nat_range_count`, `nat_range_closed`, `nat_sum`, `nat_product`, `nat_min_list`, `nat_max_list`, `nat_count`, and `nat_mean_floor`.

## Filesystem, workspace, and config

Use `std/fsx.ouro` for checked text/config reads and writes, filtered listings,
and remove-if-exists. Use `std/fs.ouro` when the lower-level checked operation
is needed. The [runtime contract](effects_design.md#runtime-surface) owns native
path, reparse-point, byte, failure, and host differences.

`fs_rename_checked source target` returns `Either FsError Unit` for same-volume
replacement. It requires an existing source and target parent and rejects a
directory target. `std/fs_replace.ouro` provides
`fs_replace_file source stage backup`, returning `FsReplaced` or
`FsReplaceFailed os_status`; the caller retains the backup until the result
and installed bytes are verified. See the [replacement contract](effects_design.md#runtime-surface)
for metadata, refusal, and recovery conditions.

For security-sensitive inventory, use `fs_walk_checked` from `std/fs_walk.ouro`.
It sorts children and distinguishes complete, truncated, unreadable, and unsafe
walks. The compatibility `fs_walk` returns an empty list for every non-complete
result and must not be used to infer that a directory is empty.

```ouro
import "../std/fsx.ouro";

fsx_read_config "tool.conf"
```

`std/config.ouro` parses line-based `key=value`, ignoring blank lines and `#`
comments; later duplicate keys win. `config_get_nat` and `config_get_bool`
return typed errors for missing or malformed values. `std/configx.ouro` can
collect field errors in one pass:

```ouro
configx_validate_schema cfg
  [ configx_field "input" ConfigAsString
  , configx_field "limit" ConfigAsNat
  , configx_field "enabled" ConfigAsBool
  ]
```

`std/workspace.ouro` groups checked paths beneath one root:

```ouro
match workspace_make "_build/my_tool" with
| Left e => fs_error_message e
| Right w => workspace_file w "out/report.txt"
end
```

Temp and backup helpers do not promise atomic replacement or unpredictable
temporary names.

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
decoding uses an Ouro byte scanner and a balanced byte builder: work is linear
and call depth is logarithmic in the string length, including on the C host.

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

Use `std/processx.ouro` for program-plus-argv command specs:

```ouro
let cmd : CommandSpec := command_spec "echo" ["ouro"] in
process_stdout_checked cmd
```

`command_render` and `process_plan_render` produce display text, not shell
commands. `process_run_inherited` and `process_run_spec_inherited` preserve a
completed child's exit code in `Either ProcessRunError Nat`; their `_checked`
variants turn a nonzero exit into `ProcessExited`. Use the captured-bounded
variants to set explicit timeout, memory, and stream limits; their `_with_input`
forms provide exact binary stdin. A nonzero child exit is still a completed
capture. Timeout, stream overflow, observed memory violation, OS refusal, and
incomplete cleanup are typed errors. The [runtime contract](effects_design.md#runtime-surface)
owns process containment and host limitations.

`std/workflow.ouro` composes parsed arguments, config, validation, execution,
and report/error rendering with conventional exit codes. It does not implement
a scheduler or streaming pipeline.

## HTTP messages and requests

`std/http.ouro` provides HTTP message parsing and `http_post url headers body`.
The [runtime contract](effects_design.md#networking) defines Windows transport,
response/error fields, and C-host behavior.

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

The [practical programs](practical_programs.md) and
[application surface](practical_application_surface.md) show these modules in
small executable tools.

## Running checks

The focused standard-library and sample checks are listed in
[CI](ci.md#local-profiles); [OuroSmith](ouro_smith.md) owns generated workflow
and runtime compositions.

## Current limits

Line processing remains bounded and in memory. Config, JSON, CSV, and table
helpers target small tools; process helpers do not provide a streaming pipeline.
The [runtime contract](effects_design.md#runtime-surface) and
[stability policy](stability.md#experimental-areas) describe host and pre-1.0
limits.
