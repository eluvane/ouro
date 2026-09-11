# std/process.ouro

Small process/CLI helpers are wrappers over std/io and std/args.

Declarations: 17.

## inductive ProcessError

```
inductive ProcessError : Type
```

## def process_error_code

```
def process_error_code (e : ProcessError) : String
```

## def process_error_command

```
def process_error_command (e : ProcessError) : String
```

## def process_error_status

```
def process_error_status (e : ProcessError) : Nat
```

## def process_error_stderr

```
def process_error_stderr (e : ProcessError) : String
```

## def process_error_message

```
def process_error_message (e : ProcessError) : String
```

## def process_argv

```
def process_argv : IO (List String)
```

## def process_args

```
def process_args : IO Args
```

## def process_env

```
def process_env (name : String) : IO (Maybe String)
```

## def process_env_or

```
def process_env_or (name : String) (fallback : String) : IO String
```

## def process_exit

```
def process_exit (code : Nat) : IO Unit
```

## def process_stdout

```
def process_stdout (s : String) : IO Unit
```

## def process_stderr

```
def process_stderr (s : String) : IO Unit
```

## def process_out_line

```
def process_out_line (s : String) : IO Unit
```

## def process_err_line

```
def process_err_line (s : String) : IO Unit
```

## def process_run

```
def process_run (cmd : String) (cmd_args : List String) : IO ProcResult
```

## def process_run_checked

```
def process_run_checked (cmd : String) (cmd_args : List String) : IO (Either ProcessError ProcResult)
```
