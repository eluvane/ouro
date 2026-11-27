# Example gallery

Choose a small program by task. The
[command reference](../../docs/tooling.md) covers checking, evaluation, and
execution. Follow the [tutorial](../tutorial/README.md) for a guided sequence.

## Core language

- [`nat.ouro`](nat.ouro) — inductive natural numbers and structural addition.
- [`list.ouro`](list.ouro) — polymorphic lists.
- [`string_demo.ouro`](string_demo.ouro) — string operations.
- `effect_*.ouro` — the experimental one-shot effect subset.

## IO and data

- [`io_hello.ouro`](io_hello.ouro) — console output.
- [`io_echo.ouro`](io_echo.ouro) — stdin and stdout.
- [`io_word_count.ouro`](io_word_count.ouro) — bytes, lines, and words from stdin.
- [`io_file_stats.ouro`](io_file_stats.ouro) — checked file reads and text statistics.
- [`io_copy_file.ouro`](io_copy_file.ouro) — directory creation, write, copy, and read-back.
- [`io_grep_lines.ouro`](io_grep_lines.ouro) — stdin line filtering.
- [`file_kv_lookup.ouro`](file_kv_lookup.ouro) — checked file reads and key lookup.
- [`csv_demo.ouro`](csv_demo.ouro) — CSV parsing and output.
- [`json_demo.ouro`](json_demo.ouro) — JSON parsing and output.
- [`cli_argv_env.ouro`](cli_argv_env.ouro) — arguments and environment variables.

## Workflow acceptance programs

Programs with sibling `.golden` files are exercised by the sample suites. Examples that need stdin also include a sibling `.stdin` file.

See the [practical and workflow programs](../../docs/practical_programs.md#runnable-examples)
for `practical_*` and `workflow_*` inputs, and the [application walkthrough](../../docs/practical_application_surface.md)
for the combined JSON/CSV/config/filesystem/process tool.

## Libraries and tools

- [`crypto_demo.ouro`](crypto_demo.ouro) — SHA-256 using runtime word operations.
- [`test_demo.ouro`](test_demo.ouro) — user tests through `ouro1 test`.

Regression-only programs live in `tests/`, including the practical and workflow
stdlib tests and rejected effect programs. Run them through the maintained test
and sample suites described in [CI](../../docs/ci.md).

`future/` contains sketches for syntax and synthesis. The maintained sample
suites exercise the runnable examples. `net_client.ouro` needs a runtime
with the required networking operations.
