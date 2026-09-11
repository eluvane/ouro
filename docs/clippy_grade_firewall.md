<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=FIREWALL&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="FIREWALL banner"
  />
</p>

# Clippy-grade deny firewall

The Clippy-grade firewall is a deterministic, source-level quality gate for Ouro code. It is intentionally conservative: it catches bad-code shapes that are visible without full type inference and leaves lower-confidence semantic questions to the existing analyzer suite.

## Run it

```sh
python3 scripts/clippy_grade_firewall.py --profile strict --scope std
python3 scripts/clippy_grade_firewall.py --profile strict --scope path/to/file.ouro
python3 scripts/clippy_grade_firewall.py --profile project --warn-only --scope std --scope tools
python3 scripts/clippy_grade_firewall.py --list-rules
python3 scripts/clippy_grade_firewall.py --validate-rules
python3 scripts/clippy_grade_suite.py
```

`strict` and `release` profiles return nonzero when an unsuppressed `deny` or `fatal` finding is emitted. `project --warn-only` is for migration discovery and CI visibility; it writes JSON/SARIF but does not fail the command.

## Severity model

| Level | Meaning |
| --- | --- |
| `allow` | Disabled in the selected profile |
| `info` | Informational report only |
| `warn` | Human-visible warning; does not block |
| `deny` | Blocks strict/release gates unless narrowly suppressed |
| `fatal` | Blocks strict/release gates and is reserved for policy failures such as invalid suppressions |

The output order is stable: files are sorted by repository path and findings are sorted by path, line, column, and rule id. Reports are written to `_build/quality/clippy-grade-firewall.json` and `_build/quality/clippy-grade-firewall.sarif` by default.

## Suppressions

Suppress only a specific rule and include a reason. The suppression applies to the comment line and the following line only.

```ouro
-- ouro-clippy:disable=OURO-CLIPPY-MAINT-005 reason=protocol constant from wire format
def protocol_magic : Nat := 1000;
```

Blanket, reasonless, and unknown-rule suppressions are themselves strict failures.

## Rule families

### api-naming

| Rule | Strict level | What it catches | Fix direction |
| --- | --- | --- | --- |
| `OURO-CLIPPY-NAMING-001` | `deny` | one-letter public name | Use a descriptive public name and reserve short names for local binders. |
| `OURO-CLIPPY-NAMING-002` | `deny` | checked helper returns raw string | Return a typed error/result and provide render/message helpers. |
| `OURO-CLIPPY-NAMING-003` | `deny` | error type without renderer | Add `domain_error_message` and/or `domain_error_code` helpers. |

### checked-api

| Rule | Strict level | What it catches | Fix direction |
| --- | --- | --- | --- |
| `OURO-CLIPPY-CHECKED-001` | `deny` | raw fs read | Use fs_read_checked, fsx_read_text, or another typed FsError-returning wrapper. |
| `OURO-CLIPPY-CHECKED-002` | `deny` | raw fs write | Use fs_write_checked, fsx_write_text, or a checked overwrite policy wrapper. |
| `OURO-CLIPPY-CHECKED-003` | `deny` | raw process execution | Use process_run_checked/processx helpers so failures become typed ProcessError values. |
| `OURO-CLIPPY-CHECKED-004` | `deny` | manual argv parsing | Parse arguments through std/args or std/cli and report missing/bad values. |
| `OURO-CLIPPY-CHECKED-005` | `deny` | manual csv splitting | Use std/csv or table helpers and surface typed parse errors. |
| `OURO-CLIPPY-CHECKED-006` | `deny` | ignored checked result | Match or bind the Either/Result/Validation and report or propagate failures. |
| `OURO-CLIPPY-CHECKED-007` | `deny` | unchecked overwrite | Use checked write options or require an explicit validated overwrite flag. |

### cli-workflow

| Rule | Strict level | What it catches | Fix direction |
| --- | --- | --- | --- |
| `OURO-CLIPPY-CLI-001` | `deny` | CLI main without usage path | Add usage text and show it for missing or malformed arguments. |
| `OURO-CLIPPY-CLI-002` | `deny` | required argument without missing report | Report CliMissing/CliUsage or propagate the typed CliError. |
| `OURO-CLIPPY-CLI-003` | `deny` | command string concatenation | Pass argv-style command parts to processx/process_run helpers. |

### error-handling

| Rule | Strict level | What it catches | Fix direction |
| --- | --- | --- | --- |
| `OURO-CLIPPY-ERROR-001` | `deny` | success exit after error | Return a nonzero exit status after printing or propagating the error. |
| `OURO-CLIPPY-ERROR-002` | `deny` | error printed to stdout | Print human-readable errors to stderr and reserve stdout for machine output. |
| `OURO-CLIPPY-ERROR-003` | `deny` | obvious Left success | Use Right for success and Left for typed errors. |

### import

| Rule | Strict level | What it catches | Fix direction |
| --- | --- | --- | --- |
| `OURO-CLIPPY-IMPORT-001` | `deny` | duplicate import | Keep a single import and put aliases at the use site. |
| `OURO-CLIPPY-IMPORT-002` | `deny` | wrong-layer import | Move shared code into std or a production support module. |
| `OURO-CLIPPY-IMPORT-003` | `deny` | TCB umbrella import | Import only the explicit small modules required by the kernel or checker. |
| `OURO-CLIPPY-IMPORT-004` | `deny` | private/generated/demo import | Depend on a stable public module or move the dependency behind a generated boundary. |

### logic

| Rule | Strict level | What it catches | Fix direction |
| --- | --- | --- | --- |
| `OURO-CLIPPY-LOGIC-001` | `deny` | self equality predicate | Remove the comparison or compare against the intended second value. |
| `OURO-CLIPPY-LOGIC-002` | `deny` | impossible self comparison | Remove the comparison or fix the bound variable. |
| `OURO-CLIPPY-LOGIC-003` | `deny` | literal condition | Delete the unreachable branch or replace the literal with the real predicate. |
| `OURO-CLIPPY-LOGIC-004` | `deny` | double negation | Use the original condition directly. |
| `OURO-CLIPPY-LOGIC-005` | `deny` | nested boolean match | Use and/or/not helpers or a single match with the meaningful cases. |
| `OURO-CLIPPY-LOGIC-006` | `deny` | missing error branch | Handle Left/Err/Invalid explicitly and render or propagate the typed error. |

### maintainability

| Rule | Strict level | What it catches | Fix direction |
| --- | --- | --- | --- |
| `OURO-CLIPPY-MAINT-001` | `deny` | too many parameters | Group related inputs in a record/config object or split the operation. |
| `OURO-CLIPPY-MAINT-002` | `deny` | too many local lets | Extract named helper functions or split the workflow into stages. |
| `OURO-CLIPPY-MAINT-003` | `deny` | deeply nested match | Flatten with small helpers, early returns, or staged validation. |
| `OURO-CLIPPY-MAINT-004` | `deny` | repeated string literal | Name the string once as a constant or typed error constructor. |
| `OURO-CLIPPY-MAINT-005` | `deny` | magic large Nat literal | Move it to a named constant with a domain-specific name. |
| `OURO-CLIPPY-MAINT-006` | `deny` | duplicated local helper name | Promote the helper or give each local helper a precise distinct role. |
| `OURO-CLIPPY-MAINT-007` | `deny` | near-duplicate function body | Extract the shared logic or justify why the variants must stay separate. Single-constructor field projections are not near-duplicates. |
| `OURO-CLIPPY-MAINT-008` | `deny` | large definition span | Split the function into smaller checked stages. |

### redundant

| Rule | Strict level | What it catches | Fix direction |
| --- | --- | --- | --- |
| `OURO-CLIPPY-REDUNDANT-001` | `deny` | pointless let binding | Inline the expression or give the binding a name that is used later. |
| `OURO-CLIPPY-REDUNDANT-002` | `deny` | manual bool identity match | Return the original Bool expression directly. |
| `OURO-CLIPPY-REDUNDANT-003` | `deny` | manual bool negation match | Use the bool negation helper or a direct if-not form. |
| `OURO-CLIPPY-REDUNDANT-004` | `deny` | same branch expression | Remove the conditional or make the distinct branch behavior explicit. A `match` is flagged only when every sibling arm of that `match` computes the same expression, including nested matches. |
| `OURO-CLIPPY-REDUNDANT-005` | `deny` | empty append/concat no-op | Return the non-empty operand directly. |
| `OURO-CLIPPY-REDUNDANT-006` | `deny` | identity collection transform | Remove the transform or replace it with the intended predicate/function. |
| `OURO-CLIPPY-REDUNDANT-007` | `deny` | discarded pure result | Remove the expression or use its result. |

### suppression

| Rule | Strict level | What it catches | Fix direction |
| --- | --- | --- | --- |
| `OURO-CLIPPY-SUPPRESS-001` | `fatal` | blanket suppression | Suppress one rule id on one line and include a concrete reason. |
| `OURO-CLIPPY-SUPPRESS-002` | `fatal` | reasonless suppression | Add reason=<why this exact finding is intentional> or remove the suppression. |
| `OURO-CLIPPY-SUPPRESS-003` | `fatal` | unknown suppression rule | Use a registered rule id from --list-rules or delete the stale suppression. |

## Examples

### Redundant code

Bad:

```ouro
def same (y : Nat) : Nat := let x := y in x;
```

Diagnostic:

```text
OURO-CLIPPY-REDUNDANT-001 deny: pointless let binding
```

Fixed:

```ouro
def same (y : Nat) : Nat := y;
```

### Checked API discipline

Bad:

```ouro
def load (p : String) : String := fs_read p;
```

Diagnostic:

```text
OURO-CLIPPY-CHECKED-001 deny: raw fs read
```

Fixed:

```ouro
def load (p : String) : Either FsError String :=
  match fs_read_checked p with
  | Left e => Left FsError String e
  | Right text => Right FsError String text
  end;
```

### CLI workflow

Bad:

```ouro
def main (args : Args) : Either CliError String := cli_required args "path";
```

Diagnostic:

```text
OURO-CLIPPY-CLI-002 deny: required argument without missing report
```

Fixed:

```ouro
def main (args : Args) : Either CliError String :=
  match cli_required args "path" with
  | Left e => Left CliError String (CliUsage (cli_error_message e))
  | Right p => Right CliError String p
  end;
```

## False-positive policy

A rule should become strict only when it is deterministic, low-noise, and has a clear fix. Low-level wrapper modules are exempted for checked-API primitive usage because those modules implement the safe surface. Production project discovery currently runs as `project --warn-only` from `scripts/lint_suite.sh`; fixture denial is blocking, so rule regressions fail CI without immediately converting every existing production finding into release debt.

## Limitations

This firewall is syntactic. It does not prove type soundness, effect safety, semantic equivalence, or full dataflow. It complements `ouro lint`, `ouro analyze`, `scripts/strict_quality_firewall.py`, and the existing architecture/dead-code/duplication/API analyzers.

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
