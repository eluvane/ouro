# std/io.ouro

IO helpers wrap the checked primitives in `std/runtime.ouro`. That module imports the checked GC runtime for native `IO Unit` entries. See [Effects and IO](../effects_design.md#runtime-surface) for runtime behavior.

Declarations: 26.

## def io_unit

```ouro
def io_unit : IO Unit
```

## def print

```ouro
def print (s : String) : IO Unit
```

## def eprint

```ouro
def eprint (s : String) : IO Unit
```

## def println

```ouro
def println (s : String) : IO Unit
```

## def eprintln

```ouro
def eprintln (s : String) : IO Unit
```

## def readLine

```ouro
def readLine : IO String
```

## def concat

```ouro
def concat : String -> String -> String
```

## def exit

```ouro
def exit (n : Nat) : IO Unit
```

## def flush

```ouro
def flush : IO Unit
```

## def argv

```ouro
def argv : IO (List String)
```

## def env_get

```ouro
def env_get (k : String) : IO (Maybe String)
```

## def env_or

```ouro
def env_or (k : String) (fallback : String) : IO String
```

## def now

```ouro
def now : IO String
```

## def proc_exec

```ouro
def proc_exec (cmd : String) (args : List String) : IO ProcResult
```

## def proc_code

```ouro
def proc_code (r : ProcResult) : Nat
```

## def proc_stdout

```ouro
def proc_stdout (r : ProcResult) : String
```

## def proc_stderr

```ouro
def proc_stderr (r : ProcResult) : String
```

## def proc_ok

```ouro
def proc_ok (r : ProcResult) : Bool
```

## def io_when

```ouro
def io_when (b : Bool) (act : IO Unit) : IO Unit
```

## def io_unless

```ouro
def io_unless (b : Bool) (act : IO Unit) : IO Unit
```

## def io_foreach

```ouro
def io_foreach (A : Type) (f : A -> IO Unit) : List A -> IO Unit
```

Structural walk over the list, so no fuel argument is needed.

## def io_fold

```ouro
def io_fold (A : Type) (B : Type) (f : B -> A -> IO B)
    (acc : B) (xs : List A) : IO B
```

## def read_chunk

```ouro
def read_chunk : Nat
```

Nat literals are Peano chains the extractor walks step by step, so a big constant is written as a product of small ones.

## def read_all_fuel

```ouro
def read_all_fuel : Nat
```

The byte limit for `read_all` is `read_chunk * read_all_fuel`.

## def read_all_go

```ouro
def read_all_go : Nat -> String -> IO String
```

## def read_all

```ouro
def read_all : IO String
```

Read until the runtime returns an empty block or the read budget runs out. Budget exhaustion returns the collected bytes without a truncation flag.
