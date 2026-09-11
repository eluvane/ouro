<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=TUTORIAL&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="TUTORIAL banner"
  />
</p>

# Tutorial

These six small modules introduce one language feature at a time.

| File | Topic |
| --- | --- |
| `01_hello.ouro` | Definitions and functions |
| `02_nat.ouro` | Inductive natural numbers |
| `03_list.ouro` | Polymorphic lists |
| `04_holes.ouro` | Named holes and goal diagnostics |
| `05_fix.ouro` | Structural recursion |
| `06_effects.ouro` | Experimental one-shot effects |

Check a lesson from the repository root:

```sh
sh scripts/ouro1.sh check samples/tutorial/02_nat.ouro
```

`04_holes.ouro` is intentionally incomplete and demonstrates the unresolved
hole diagnostic. The effect lesson exercises the current bounded handler
subset; it is not a general algebraic-effects tutorial.

For build and evaluation commands, start with
[`docs/getting_started.md`](../../docs/getting_started.md). The complete syntax
reference is [`docs/syntax.md`](../../docs/syntax.md).

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
