<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=EXAMPLES&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="EXAMPLES banner"
  />
</p>

# Example gallery

This directory contains small programs for the current language, standard library, and tooling surface.

## Core language

- `nat.ouro` — inductive natural numbers and structural addition.
- `list.ouro` — polymorphic lists.
- `string_demo.ouro` — string operations.
- `effect_*.ouro` — the experimental one-shot effect subset.

```sh
sh scripts/ouro1.sh check samples/examples/nat.ouro
sh scripts/ouro1.sh eval samples/examples/nat.ouro --print four
```

## IO and data

- `io_hello.ouro` — console output.
- `io_echo.ouro` — stdin and stdout.
- `io_word_count.ouro` — stdin byte/line/word summary.
- `io_file_stats.ouro` — checked file read and simple text stats.
- `io_copy_file.ouro` — checked directory creation, file write, copy, and read-back.
- `io_grep_lines.ouro` — stdin line filtering.
- `file_kv_lookup.ouro` — checked file read plus key/value lookup.
- `csv_demo.ouro` — CSV parsing and output.
- `json_demo.ouro` — JSON parsing and output.
- `cli_argv_env.ouro` — arguments and environment variables.
- `practical_cli_file.ouro` — CLI args, checked file read, text transform, stdout/stderr, and exit code.
- `practical_stdin_aggregate.ouro` — stdin parsing and Nat aggregations.
- `practical_config_report.ouro` — checked config-file read and typed config report.

## Workflow acceptance programs

These programs are acceptance tests for reusable workflow APIs rather than standalone demos:

- `workflow_stdin_report.ouro` — stdin line processor: comment/blank filtering, Nat field parsing, aggregation, and report output.
- `workflow_json_table_transform.ouro` — JSON getters plus header-aware table counting and report output.
- `workflow_process_runner.ouro` — shell-free command spec, checked process run, stdout capture, and report output.
- `workflow_validation_report.ouro` — accumulated validation errors rendered together.
- `workflow_workspace_tool.ouro` — workspace creation, file write/copy, and path report.
- `workflow_config_transform.ouro` — config-driven file transform with checked workspace IO.

Programs with sibling `.golden` files are exercised by the sample suites. Examples that need stdin also include a sibling `.stdin` file.

```sh
sh scripts/build_tool.sh samples/examples/workflow_stdin_report.ouro _build/tools/workflow_stdin_report
./_build/tools/workflow_stdin_report < samples/examples/workflow_stdin_report.stdin
sh scripts/build_tool.sh samples/examples/workflow_process_runner.ouro _build/tools/workflow_process_runner
./_build/tools/workflow_process_runner
```

## Libraries and tools

- `crypto_demo.ouro` — SHA-256 in Ouro using the word-operation runtime slice.
- `test_demo.ouro` — user-level tests through `ouro1 test`.

```sh
sh scripts/ouro1.sh test samples/examples/test_demo.ouro
```

Regression-only programs live in `tests/`, including the practical and workflow
stdlib tests and rejected effect programs. Run them through the maintained test
and sample suites described in [CI](../../docs/ci.md).

`future/` contains sketches for syntax or synthesis work and is not part of the maintained runnable path. `net_client.ouro` depends on networking behavior that is not a one-command portable example.

See the [tutorial](../tutorial/README.md) for a linear introduction, [Practical programs](../../docs/practical_programs.md) for a short CLI/data walkthrough, [Practical standard library](../../docs/practical_stdlib.md) for the reusable helper modules, and [Practical application surface](../../docs/practical_application_surface.md) for an end-to-end JSON/CSV/config/filesystem/process tool. [Tooling](../../docs/tooling.md) covers command details.

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
