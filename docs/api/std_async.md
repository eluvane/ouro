# std/async.ouro

Sequential timing helpers over existing IO. Not a scheduler, not concurrent race, and not an async/network runtime (roadmap Arc 12).

Declarations: 2.

## def sleep_s

```
def sleep_s (n : Nat) : IO Unit
```

## def delay_then

```
def delay_then (A : Type) (n : Nat) (act : IO A) : IO A
```
