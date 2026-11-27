# Practical standard library surface

Use these modules to write small Ouro programs that parse data, read files,
validate arguments, or run commands. Expression snippets belong inside a
definition with the relevant modules imported and any input variables in scope.

## Modules

Choose a module by task. Look up exact signatures in the
[standard-library API reference](api/README.md).

| Task | Modules |
| --- | --- |
| Shared types and results | `std/types.ouro`, `std/prelude.ouro`, `std/data.ouro`, `std/result.ouro` |
| Lists and iterators | `std/collections.ouro`, `std/iter.ouro`, `std/range.ouro` |
| Text and numbers | `std/string.ouro`, `std/text.ouro`, `std/num.ouro`, `std/utf8_scalar.ouro` |
| SHA-256 and HMAC | `std/crypto.ouro` |
| CLI and configuration | `std/args.ouro`, `std/cli.ouro`, `std/config.ouro`, `std/configx.ouro` |
| IO and runtime actions | `std/io.ouro`, `std/runtime.ouro` |
| Files and workspace | `std/fs.ouro`, `std/fsx.ouro`, `std/fs_walk.ouro`, `std/fs_replace.ouro`, `std/workspace.ouro` |
| Data | `std/lines.ouro`, `std/json.ouro`, `std/jsonx.ouro`, `std/csv.ouro`, `std/table.ouro`, `std/tablex.ouro` |
| Process and reports | `std/process.ouro`, `std/processx.ouro`, `std/validation.ouro`, `std/report.ouro`, `std/workflow.ouro` |

`std/practical.ouro` imports the practical helpers as a convenience umbrella.
`std/string_prims.ouro` declares the `String` type and its pure primitives
without importing platform IO. `std/executable.ouro` supplies the current
image-path query.

`std/utf8_scalar.ouro` provides `utf8_scalar_checked` for a scalar-to-UTF-8
conversion that rejects surrogates and out-of-range values. Its
`utf8_scalar_bytes` encoder requires an already validated scalar.

`std/natx.ouro` provides `eq_nat_list` for elementwise equality of `List Nat`.
It stops at the first unequal element.

## Function composition

`std/logic.ouro` provides `compose A B C after before : A -> C`. It applies
`before` to the input, then `after` to the intermediate value:

```ouro
import "../std/logic.ouro";
import "../std/prelude.ouro";

def twice_then_increment : Nat -> Nat :=
  compose Nat Nat Nat (add 1) (mul 2);
```

## Callback sections

`std/logic.ouro` provides `flip A B C f right left`, which calls an ordinary
binary function as `f left right`. Partially applying `flip A B C f right`
produces a typed `A -> C` callback with the right argument fixed.

This uses ordinary partial application; the parameter types remain explicit
and no placeholder syntax is introduced.

## Fallible values

`std/data.ouro` provides `maybe_unwrap_or_else A fallback value` for a
`Maybe A`. The fallback has type `Unit -> A` and is called only for `Nothing`;
`Just x` returns `x`. Use `fromMaybe` when the default is already a value.

`std/result.ouro` treats `Either E A` as a result: `Left` carries the error
and `Right` carries the value. `result_unwrap_or_else E A fallback value`
returns the value on `Right`; on `Left` it calls `fallback : E -> A` with the
original error. The fallback is called only for `Left`. Use `result_bind` to
continue with another fallible operation and `result_map_err` to change an
error type while retaining the result.

`std/data.ouro` provides `maybe_bind A B value next` to continue a `Maybe`
computation. It calls `next : A -> Maybe B` only for `Just`; `Nothing` passes
through without calling it.

```ouro
import "../std/data.ouro";

def next_if_present (value : Nat) : Maybe Nat :=
    match value with
    | Z => Nothing Nat
    | S _ => Just Nat (S value)
    end;

def example : Maybe Nat :=
    maybe_bind Nat Nat (Just Nat 2) next_if_present;
```

`std/collections.ouro` provides `list_traverse_maybe A B f xs` for an ordered
list of fallible conversions. It returns `Just []` for an empty list, `Just`
with all converted values when every call succeeds, or `Nothing` at the first
failure. `list_traverse_result E A B f xs` preserves the first typed error and
does not call `f` on later elements. `list_try_fold_result E A S step initial xs`
and `list_try_fold_maybe A S step initial xs` likewise stop at the first failure;
an empty list returns `Right initial` or `Just initial`. `filter_map` drops
missing values when that is the intended behavior.

## CLI arguments

Use `cli_from_argv` when a native program reads `argv`. Pass the option names
that should behave as boolean flags. Strict command entry points can call
`args_argv_options_complete` before parsing to reject non-boolean long options
whose value is absent.

Obtain the argument list by running the `argv` action from `std/io.ouro`
before passing it to this helper.

```ouro
import "../std/cli.ouro";

def render_limit (av : List String) : String :=
    let parsed : Args := cli_from_argv ["verbose"] av in
    match cli_required_nat parsed "limit" with
    | Left e => cli_error_message e
    | Right n => str_of_nat n
    end;
```

`cli_required`, `cli_required_nat`, `cli_required_bool`, and
`cli_required_pos` return `Either CliError A`. Handle the error branch
before using the value.

## Line/data processors

`std/lines.ouro` reads input into memory before operating on a `List String`.
The stdin helpers use `read_all` from `std/io.ouro`. It appends each nonempty
byte chunk, including a short chunk, and stops on an empty read or after
65,536 calls requesting up to 4,096 bytes each. At the limit it returns
the accumulated bytes, up to 256 MiB, without a truncation status. The file
helpers use the checked file-read path.

This expression filters comment and blank lines from `input : String` and
sums the parsed natural numbers.

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

`std/string_prims.ouro` declares `String` and its pure operations as checked
intrinsics. `std/runtime.ouro` imports those declarations and the checked
Ouro GC runtime required by native `IO Unit` entries. Programs with a
standalone prelude must use the registered `ouro.string` identity. Import
`std/string.ouro` for standard text operations. String lengths and offsets
count bytes. See the [syntax contract for literals](syntax.md#numbers-and-strings).
`str_index_from` returns `Nothing` when its starting offset exceeds the byte
length; an empty pattern can match exactly at the end of the string.

The experimental Windows native backend implements these pure String
intrinsics with byte-preserving managed storage, including embedded NUL.
Byte access outside the string returns zero; slicing clamps the requested
range. Search and ordering compare unsigned bytes. Splitting uses a byte-valued
separator; a Nat above 255 matches no byte. Tokens split on space, tab, CR, and
LF. Byte-list construction takes each Nat modulo 256. Decimal rendering
preserves the complete Nat value, including values beyond machine-word range.

`std/text.ouro` is the preferred module for small text-processing tools. It covers whitespace tokenization (`str_tokens`), trimmed lines (`str_lines_trimmed`), nonblank lines (`str_nonblank_lines`), split-last (`str_split_last`), safe prefix/suffix removal, simple delimited extraction (`str_between`), and typed parsing (`str_parse_nat`, `str_parse_bool`).

`std/bytes.ouro` provides hex and Base64 helpers. `hex_decode_str` accepts an
even number of hexadecimal digits, in either case, and preserves decoded zero
bytes. Empty input returns `Just ""`. Invalid characters, including whitespace,
and odd-length input return `Nothing`; they are not removed before decoding.

## Incremental SHA-256

`std/crypto.ouro` provides a pure incremental digest over binary `String`
chunks, preserving every byte including NUL. Start with `sha256_stream_init`,
pass each chunk to `sha256_stream_update`, then call `sha256_stream_final` for
lowercase hexadecimal output:

```ouro
import "../std/crypto.ouro";

def chunked_digest : Either Sha256StreamError String :=
    let? (Left, Right) : Either Sha256StreamError String do
      let first : Sha256Stream := (sha256_stream_update sha256_stream_init "ab")?;
      let complete : Sha256Stream := (sha256_stream_update first "c")?;
      let digest : String := (sha256_stream_final complete)?;
      digest
    end;
```

`Sha256StreamOf` stores the exact total byte count, eight Word32 hash lanes
and a packed tail of at most 63 bytes. Because its constructor is public,
update and finalization recheck the count, word ranges and tail shape;
these checks do not establish the history of a caller-constructed state.
Finalization leaves the immutable state reusable.

The total must stay below `sha256_stream_byte_limit` (512 MiB). The shared
length encoder retains only the low 32 bit-length bits, so reaching the limit
returns `Sha256StreamByteLimitExceeded` with the attempted total. Invalid
state shape returns `Sha256StreamInvalidState`; use
`sha256_stream_error_code` or `sha256_stream_error_message` to report it.

Only each 64-byte block and the bounded final padding become byte lists.
This API does not read files or bound the caller's chunk allocation, cumulative
allocations or runtime heap. Existing `sha256` and `hmac_sha256` retain their
whole-input APIs.

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

`iter_fold State Error Item Acc step initial max_pulls source` consumes the
same bounded pull sequence without building a list. A skip keeps the
accumulator; a yield applies the pure `step` in source order. The accumulator
is returned only after an end step, while source failure and budget exhaustion
return `IterSourceFailure` and `IterPullLimit` rather than a partial success.
For example, folding `add` over `[1, 2, 3]` with four pulls returns `Right 6`:

```ouro
iter_fold (List Nat) String Nat Nat add Z 4
  (iter_from_list String Nat ([1, 2, 3] : List Nat))
```

Adapters do not build intermediate lists. Materialization builds a reversed
list and allocates another list when reversing it at completion; iterator
wrappers and step results also allocate. Pull traversal is bounded by
`max_pulls`, with callback and source-step costs in addition. No
constant-allocation or automatically fused pipeline is promised.

## Finite Nat ranges

`std/range.ouro` builds finite `Nat` range values for the pull iterator API.
The literal `0..10` calls the represented four-field `NatRange` constructor
with step one and `RangeExclusive`; `0..=10` uses `RangeInclusive`. Literal
endpoints are required in this syntax. These are values, not eagerly
materialized lists; consuming them requires `iter_from_nat_range` and an
explicit pull budget. The compiler validates the nominal Nat, bound, and
range representation roles before checked construction. An alias to the
registered `NatRange` keeps that identity; an unrelated same-shaped type
does not. Use the functions below when endpoints are computed or a different
step is needed.
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

`nat_min_list` and `nat_max_list` use `fallback` only for an empty list. On a
nonempty list, the result is an element of that list, regardless of `fallback`.
The lower-level `minimum_nat` and `maximum_nat` helpers retain their seeded-fold
behavior.

`std/format.ouro` renders bases 2 through 36 with `show_nat_base`, using lowercase
letters for digits above 9. Other bases use decimal rendering. `show_hex`,
`show_oct`, and `show_bin` add their respective prefixes. `fib_nat` in
`std/natx.ouro` uses one addition per index step and retains the full `Nat` range.

## Filesystem, workspace, and config

Use `std/fsx.ouro` for checked text/config reads and writes, filtered listings,
and remove-if-exists. Use `std/fs.ouro` when the lower-level checked operation
is needed. The [runtime contract](effects_design.md#runtime-surface) owns native
path, reparse-point, byte, failure, and host differences.

`fs_read_checked path` returns `IO (Either FsError String)`. It runs path
and type checks first. Subsequent OS open, length, and read errors yield
`FsOperationFailed` with the path and numeric OS status. A successful read
contains every byte of the captured length. Malformed path text, allocation
or compiler guard failures, and failed raw cleanup remain terminal. See the
[runtime contract](effects_design.md#runtime-surface) for status namespaces.

The experimental `std/fs_bounded.ouro` API
`fs_read_bounded_checked byte_cap path` returns
`IO (Either FsBoundedReadError String)` on Windows x86-64 native Runtime.
It sizes the opened handle and rejects an excessive length before allocating
payload storage. Empty files are accepted with cap zero; all returned bytes,
including NUL, are preserved. The cap is a `Nat` and is not narrowed to a word.
It is a content-byte bound, not a process-memory budget: fixed path/scratch
storage, page rounding and the managed byte list/String also consume memory.

This adapter rejects the final reparse point and directories, uses read-only
sharing, and checks the same handle for early EOF, later growth and a changed
final length. Such changes fail without returning a prefix; a one-byte EOF
probe uses fixed scratch. This is not an atomic snapshot and cannot detect
every rewrite that leaves the size unchanged. Ancestor traversal is not a
confinement guarantee. OS errors retain their numeric Win32 status; invalid
paths and excessive sizes have typed errors. Raw buffer exhaustion,
adapter-detected storage/progress guards and failed cleanup terminate with status 73 after
attempting all remaining owned cleanup. Shared managed-heap exhaustion remains
process-terminal and is not intercepted by this scope. There is no C-host or
other-platform fallback for this API.

```ouro
import "../std/fs_bounded.ouro";

def read_manifest : IO (Either FsBoundedReadError String) :=
    fs_read_bounded_checked 1048576 "manifest.json";
```

`fs_rename_checked source target` returns `IO (Either FsError Unit)` for
same-volume replacement. It requires an existing source and target parent
and rejects a directory target. `std/fs_replace.ouro` provides
`fs_replace_file source stage backup`, an `IO FsReplaceResult` action.
The result is `FsReplaced` or `FsReplaceFailed os_status`. Retain the backup
until the result and installed bytes are verified. See the
[replacement contract](effects_design.md#runtime-surface) for metadata,
refusal, and recovery conditions.

`fs_kind_checked path` returns `IO (Either FsError FsPathKind)` and classifies
the final path entry without following links. Empty paths yield `FsEmptyPath`.
Regular files, directories, and unsafe entries have distinct constructors.
`FsPathUnavailable` means the OS query could not classify the path. Such
a path can still exist.

```ouro
import "../std/fs.ouro";

def inspect_input : IO (Either FsError FsPathKind) :=
    fs_kind_checked "input.txt";
```

For security-sensitive inventory, use `fs_walk_checked` from `std/fs_walk.ouro`.
It sorts children and distinguishes complete, truncated, unreadable, and unsafe
walks. The compatibility `fs_walk` returns an empty list for every non-complete
result and must not be used to infer that a directory is empty.

The workspace helpers `fsx_list_files_filtered` and `fsx_copy_tree_checked`
return `FsOperationFailed` when the checked walk is incomplete or unsafe.
Copying starts only after a complete inventory. `fsx_remove_tree_checked`
rejects empty paths with `FsEmptyPath`. Links and reparse points are rejected
before enumerating their children. A later error can leave earlier entries
removed. These helpers do not provide an atomic filesystem snapshot.

```ouro
import "../std/fsx.ouro";

def read_tool_config : IO (Either FsError Config) :=
    fsx_read_config "tool.conf";
```

`std/config.ouro` parses line-based `key=value` entries. It strips text
from the first `#` in each line, skips blank lines and lines without `=`,
and trims keys and values. Later duplicate keys win. `config_get_nat`
and `config_get_bool` return typed errors for missing or malformed values.

Use `std/configx.ouro` to collect field errors from `cfg : Config` in one pass.

```ouro
configx_validate_schema cfg
  [ configx_field "input" ConfigAsString
  , configx_field "limit" ConfigAsNat
  , configx_field "enabled" ConfigAsBool
  ]
```

`std/workspace.ouro` pairs a root path with helpers for joining paths and
performing checked file operations. `workspace_file` joins the root and the
supplied path with `path_join`. A joined path can still resolve outside the
root, so callers that need confinement must validate paths separately.

`workspace_make` returns an `IO (Either FsError Workspace)` action that
ensures the root directory exists when it runs. The registered example runs
that action with `let!`, checks the result, and writes and copies files
using fixed relative paths.
[Workspace tool example](../samples/examples/workflow_workspace_tool.ouro)

Temp and backup helpers supply paths for callers to manage. Their names can
be predictable, and publication guarantees depend on the operation used.

## JSON, CSV, and tables

`std/csv.ouro` parses one record per input line, skips blank lines, and
handles commas and doubled quotes in quoted fields. A quoted field
cannot span input lines. `std/table.ouro` adds header-aware operations for
selecting columns by name. The examples use `text : String` for CSV or JSON
input.

```ouro
let rows : List (List String) := table_from_csv text in
table_col_named rows "status"
```

`std/jsonx.ouro` adds typed accessors for small JSON documents.

```ouro
let doc : Json := jsonx_parse_or_null text in
jsonx_get_string doc "name"
```

The base JSON parser caps recursive structure at 128 levels. JSON string
decoding uses an Ouro byte scanner and a balanced byte builder: work is linear
and call depth is logarithmic in the string length, including on the C host.

`json_print` escapes every control byte from 0 through 31 in string values and
object keys. It uses the short JSON escapes where available and `\u00xx` for
the remaining control bytes.

`std/tablex.ouro` validates required columns and projects them in the requested
order.

```ouro
tablex_csv_project_required text ["name", "status"]
```

A header-only table is accepted when it contains every required column.
An empty table provides no header. `table_cell` returns `Nothing` when a data
row is shorter than the named column.

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

Use `std/processx.ouro` for program-plus-argv command specs. On the POSIX
C host, this example requires an external `echo` executable on `PATH`.

```ouro
let cmd : CommandSpec := command_spec "echo" ["ouro"] in
process_stdout_checked cmd
```

`command_render` and `process_plan_render` produce display text, not shell
commands. `process_run_inherited` and `process_run_spec_inherited` preserve a
completed child's exit code in `IO (Either ProcessRunError Nat)`. Their
`_checked` variants turn a nonzero exit into `ProcessExited`. Use the
captured-bounded variants to set explicit timeout, memory, and stream limits.
Their `_with_input` forms provide exact binary stdin. A nonzero child exit is still a completed
capture. Timeout, stream overflow, observed memory violation, OS refusal, and
incomplete cleanup are typed errors. The [runtime contract](effects_design.md#runtime-surface)
owns process containment and host limitations.

`process_run_captured_bounded_at limits directory program arguments` and
`process_run_captured_bounded_at_with_input limits directory program arguments input`
set an explicit child cwd. The `process_run_spec_captured_bounded_at` and
`process_run_spec_captured_bounded_at_with_input` wrappers take the same limits
and directory followed by a `CommandSpec`. They return
`IO (Either ProcessDirectoryError ProcessCaptureResult)`.
`ProcessInvalidDirectory` identifies an invalid path, and
`ProcessDirectoryCapture` retains a capture failure.
`process_directory_error_code` and `process_directory_error_message`
render either case. Directory validation requires a drive-rooted path or a
double-backslash Windows prefix (including UNC), with strict UTF-8 and no NUL.
Relative and drive-relative paths are refused before limits or launch. The path and argv stay literal,
and the parent's cwd is preserved. These actions initially support native
Windows and the Windows C adapter; POSIX C reports unsupported execution.

`std/workflow.ouro` composes parsed arguments, config, validation, execution,
and report/error rendering with conventional exit codes. It does not implement
a scheduler or streaming pipeline.

## HTTP messages and requests

`std/http.ouro` provides HTTP message parsing and `http_post url headers body`.
The [runtime contract](effects_design.md#networking) defines Windows transport,
response/error fields, and C-host behavior.

## Validation and reports

Use `std/validation.ouro` to collect user-facing errors. Each check passed to
`validation_collect_unit` must produce `Validation String Unit` when the
error type is `String`. Map the successful value from
`validation_require_nonempty` to `Unit`, as in this definition from the
[validation report example](../samples/examples/workflow_validation_report.ouro).

```ouro
import "../std/validation.ouro";

def workflow_validation_errors : Validation String Unit :=
    validation_collect_unit String
      ([ validation_require String "missing --input" False
      , validation_map String String Unit (fun (_ : String) => MkUnit)
      (validation_require_nonempty "empty --name" "")
      , validation_require String "ok" True
      ] : List (Validation String Unit));
```

Use `std/report.ouro` for deterministic key/value summaries. This expression
uses `row_count : Nat` from the caller.

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

Find focused standard-library and sample checks in the
[CI validation matrix](ci.md#validation-matrix). [OuroSmith](ouro_smith.md)
covers generated workflow and runtime compositions.

## Current limits

Line processing holds input in memory. Config, JSON, CSV, and table helpers
target small tools. Process helpers support captured or inherited streams
with the backend limits documented above.
The [runtime contract](effects_design.md#runtime-surface) and
[stability policy](stability.md#experimental-areas) describe host and pre-1.0
limits.
