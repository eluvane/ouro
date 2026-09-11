# std/io.ouro

Thin wrappers over trusted runtime prims; semantic failures belong in runtime.ouro/docs/tcb.md. Native IO/Unit lowering links the checked GC runtime through this import.

Declarations: 26.

## def io_unit

```
def io_unit : IO Unit
```

## def print

```
def print (s : String) : IO Unit
```

## def eprint

```
def eprint (s : String) : IO Unit
```

## def println

```
def println (s : String) : IO Unit
```

## def eprintln

```
def eprintln (s : String) : IO Unit
```

## def readLine

```
def readLine : IO String
```

## def concat

```
def concat : String -> String -> String
```

## def exit

```
def exit (n : Nat) : IO Unit
```

## def flush

```
def flush : IO Unit
```

## def argv

```
def argv : IO (List String)
```

## def env_get

```
def env_get (k : String) : IO (Maybe String)
```

## def env_or

```
def env_or (k : String) (fallback : String) : IO String
```

## def now

```
def now : IO String
```

## def proc_exec

```
def proc_exec (cmd : String) (args : List String) : IO ProcResult
```

## def proc_code

```
def proc_code (r : ProcResult) : Nat
```

## def proc_stdout

```
def proc_stdout (r : ProcResult) : String
```

## def proc_stderr

```
def proc_stderr (r : ProcResult) : String
```

## def proc_ok

```
def proc_ok (r : ProcResult) : Bool
```

## def io_when

```
def io_when (b : Bool) (act : IO Unit) : IO Unit
```

## def io_unless

```
def io_unless (b : Bool) (act : IO Unit) : IO Unit
```

## def io_foreach

```
def io_foreach (A : Type) (f : A -> IO Unit) : List A -> IO Unit
```

Structural walk over the list, so no fuel argument is needed.

## def io_fold

```
def io_fold (A : Type) (B : Type) (f : B -> A -> IO B)
```

## def read_chunk

```
def read_chunk : Nat
```

Nat literals are Peano chains the extractor walks step by step, so a big constant is written as a product of small ones.

## def read_all_fuel

```
def read_all_fuel : Nat
```

Reads until a short chunk shows end of input. Fuel bounds the total to read_chunk * read_all_fuel bytes.

## def read_all_go

```
def read_all_go : Nat -> String -> IO String
```

## def read_all

```
def read_all : IO String
```
