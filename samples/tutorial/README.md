# Tutorial

These six small modules introduce one language feature at a time.

| File | Topic |
| --- | --- |
| `01_hello.ouro` | Definitions and functions |
| `02_nat.ouro` | Inductive natural numbers |
| `03_list.ouro` | Polymorphic lists |
| `04_holes.ouro` | Named holes and goal diagnostics |
| `05_fix.ouro` | Pattern matching and predecessor |
| `06_effects.ouro` | Experimental one-shot effects |

The sample suite checks all six modules without running them as native programs.
It expects `04_holes.ouro` to fail with `OURO-HOLE-001`; the other five must
pass. The final lesson returns a pure `String` value; see
[Effects and IO](../../docs/effects_design.md).

For build and evaluation commands, start with
[`docs/getting_started.md`](../../docs/getting_started.md). The complete syntax
reference is [`docs/syntax.md`](../../docs/syntax.md).
