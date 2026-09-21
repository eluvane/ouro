# std/io_hype_inline.ouro

Hype-surface demo: residual perform without a handler must still compile-fail.

Declarations: 2.

## effect Ask

```
effect Ask where
```

Distinct family and operation names so the semantic declaration index is strictly ordered. The compact `effect AskName : String` form interned the same name twice and rejected the unit as ambiguous.

## def main

```
def main : IO Unit
```
