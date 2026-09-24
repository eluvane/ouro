# Example gallery

This directory contains small programs for the current language, standard library, and tooling surface.

## Core language

- `nat.ouro` — inductive natural numbers and structural addition.
- `list.ouro` — polymorphic lists.
- `string_demo.ouro` — string operations.
- `effect_*.ouro` — the experimental one-shot effect subset.

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

## Workflow acceptance programs

Programs with sibling `.golden` files are exercised by the sample suites. Examples that need stdin also include a sibling `.stdin` file.

See the [practical and workflow programs](../../docs/practical_programs.md#runnable-examples)
for `practical_*` and `workflow_*` inputs, and the [application walkthrough](../../docs/practical_application_surface.md)
for the combined JSON/CSV/config/filesystem/process tool.

## Libraries and tools

- `crypto_demo.ouro` — SHA-256 in Ouro using the word-operation runtime slice.
- `test_demo.ouro` — user-level tests through `ouro1 test`.

Regression-only programs live in `tests/`, including the practical and workflow
stdlib tests and rejected effect programs. Run them through the maintained test
and sample suites described in [CI](../../docs/ci.md).

`future/` contains sketches for syntax or synthesis work and is not part of the maintained runnable path. `net_client.ouro` depends on networking behavior that is not a one-command portable example.

For a linear introduction, follow the [tutorial](../tutorial/README.md).
[Tooling](../../docs/tooling.md) covers checking, evaluation, native execution, and user tests.
