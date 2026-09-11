<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=PROGRAMS&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="PROGRAMS banner"
  />
</p>

# Practical Ouro programs

Ouro is still pre-1.0, but the current repository now has a broader runnable vertical slice for command-line, data, file, process, validation, and workspace-oriented tools. The goal of these examples is not to claim full general-purpose readiness; it is to show the practical path that works today.

## Capabilities shown here

The examples use the standard-library surface for:

- stdin/stdout/stderr and process exit codes through `std/io.ouro`;
- checked file reads, writes, copies, directories, and filesystem diagnostics through `std/fs.ouro`, `std/fsx.ouro`, and `std/workspace.ouro`;
- strings, splitting, replacement, containment, trimming, case conversion, whitespace tokenization, typed parsing, and bounded line workflows through `std/string.ouro`, `std/stringx.ouro`, `std/text.ouro`, and `std/lines.ouro`;
- simple formatting, key/value parsing, config files, schema-lite config validation, CSV, JSON, and header-aware table helpers through `std/format.ouro`, `std/config.ouro`, `std/configx.ouro`, `std/csv.ouro`, `std/json.ouro`, `std/jsonx.ouro`, `std/table.ouro`, and `std/tablex.ouro`;
- argument and environment access through `std/args.ouro`, typed argument validation through `std/cli.ouro`, and environment overrides through `std/configx.ouro`;
- shell-free command specs and checked process execution through `std/process.ouro` and `std/processx.ouro`;
- accumulated validation, command workflow errors, and report rendering through `std/validation.ouro`, `std/workflow.ouro`, and `std/report.ouro`;
- Result-style typed errors through `Either` helpers in `std/result.ouro`;
- reusable collection and `Nat` helpers through `std/collections.ouro` and `std/num.ouro`.

These APIs intentionally stay small. New functions should normally be justified by a runnable sample and a checked expected output.

For a reference-style guide to the reusable helper modules, see [Practical standard library](practical_stdlib.md).

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

Practical acceptance programs in `samples/examples/` cover reusable stdlib tests, CLI file transforms, stdin aggregation, and typed config reporting:

```sh
sh scripts/ouro1.sh test tests/practical_stdlib_tests.ouro
sh scripts/build_tool.sh samples/examples/practical_cli_file.ouro _build/tools/practical_cli_file
sh scripts/build_tool.sh samples/examples/practical_stdin_aggregate.ouro _build/tools/practical_stdin_aggregate
sh scripts/build_tool.sh samples/examples/practical_config_report.ouro _build/tools/practical_config_report
```

Workflow acceptance programs cover the larger practical surface:

```sh
sh scripts/ouro1.sh test tests/workflow_stdlib_tests.ouro
sh scripts/build_tool.sh samples/examples/workflow_stdin_report.ouro _build/tools/workflow_stdin_report
./_build/tools/workflow_stdin_report < samples/examples/workflow_stdin_report.stdin
sh scripts/build_tool.sh samples/examples/workflow_json_table_transform.ouro _build/tools/workflow_json_table_transform
sh scripts/build_tool.sh samples/examples/workflow_process_runner.ouro _build/tools/workflow_process_runner
sh scripts/build_tool.sh samples/examples/workflow_validation_report.ouro _build/tools/workflow_validation_report
sh scripts/build_tool.sh samples/examples/workflow_workspace_tool.ouro _build/tools/workflow_workspace_tool
sh scripts/build_tool.sh samples/examples/workflow_config_transform.ouro _build/tools/workflow_config_transform
```

Those programs are intentionally small, but they prove reusable capabilities:

- `workflow_stdin_report.ouro`: stdin text -> nonblank/comment filtering -> Nat field parsing -> aggregate report.
- `workflow_json_table_transform.ouro`: bounded JSON getters + table selection/counting + report.
- `workflow_process_runner.ouro`: command spec -> checked process run -> stdout/error report.
- `workflow_validation_report.ouro`: multiple validation checks -> accumulated user-facing errors.
- `workflow_workspace_tool.ouro`: workspace creation -> write/copy/report.
- `workflow_config_transform.ouro`: workspace + config + file read/transform/write + report.

Other practical examples in `samples/examples/` cover copy/read-back, line filtering, CSV, JSON, argv/env, and runtime IO.

## Test path

The sample suite checks these programs and compares stdout against committed `.golden` files where expected output is committed:

```sh
sh scripts/samples_suite.sh
```

The suite reports unavailable host support explicitly. OuroSmith's
`stdlib_workflow`, `stdlib_tables`, and `runtime_io` recipes generate typed
helper compositions and check values and failure paths against independent
contracts. Run these through the [OuroSmith replay command](ouro_smith.md).

API docs and the analyzer API surface are kept under:

```sh
sh scripts/doc_suite.sh
python3 scripts/api_baseline_regen.py --check
```

## Current limits

The standard-library surface is enough for small CLI/data/file/workflow tools, not a complete application platform. Line processing is bounded and in-memory. Process helpers intentionally do not use shell strings by default and do not yet provide subprocess stdin or real stdout-to-stdin pipelines. Workspace temp paths and backup helpers are checked convenience wrappers, not platform-grade atomicity or secure temp-file guarantees. Networking, package distribution, richer schema systems, true streaming abstractions, and large-data processing remain future passes.

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
