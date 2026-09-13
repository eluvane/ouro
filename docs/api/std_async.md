# std/async.ouro

Sequential Windows native timing helpers. They block the current thread; they do not provide a scheduler, concurrency, or an async/network runtime.

Declarations: 2.

## def sleep_s

```
def sleep_s (n : Nat) : IO Unit
```

Wait for n one-second Windows intervals when the action runs. Zero makes no OS wait call. The full Nat is retained, including values beyond U32/U64. Windows timer precision and scheduling apply. Runtime conversion failure emits a diagnostic and terminates with status 73, without running a successor.

## def delay_then

```
def delay_then (A : Type) (n : Nat) (act : IO A) : IO A
```

Run act after the sequential delay, preserving its result. Reusing this action performs the delay again on each execution.
