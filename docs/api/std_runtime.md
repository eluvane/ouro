# std/runtime.ouro

Runtime surface: checked String identities and composable Runtime actions. Streams, exit, startup, clock and binary files have checked native adapters.

Declarations: 32.

## axiom prim_json_string_parse

```
axiom prim_json_string_parse : String -> Nat -> Pair (Maybe String) Nat
```

Linear, non-recursive JSON string decode from an opening quote. The Nat is the first byte after the closing quote, or the failure position.

## inductive ProcResult

```
inductive ProcResult : Type
```

## def IO

```
def IO (A : Type) : Type
```

IO and raw system actions share one checked effect constructor.

## def io_pure

```
def io_pure (A : Type) (value : A) : IO A
```

## def io_bind

```
def io_bind (A : Type) (B : Type) (action : IO A) (next : A -> IO B) : IO B
```

## intrinsic prim_stdout_write

```
intrinsic prim_stdout_write : String -> IO Unit
```

## intrinsic prim_stderr_write

```
intrinsic prim_stderr_write : String -> IO Unit
```

## intrinsic prim_stdin_read_line

```
intrinsic prim_stdin_read_line : IO String
```

Native line input consumes at most 8191 bytes, removes LF and preserves CR.

## intrinsic prim_stdin_read_bytes

```
intrinsic prim_stdin_read_bytes : Nat -> IO String
```

Reads at most n bytes; a short result means end of input. Native input preserves NUL and runs only when the action is invoked. Conversion, allocation, read and cleanup failures terminate with status 73.

## intrinsic prim_stdout_flush

```
intrinsic prim_stdout_flush : IO Unit
```

## intrinsic prim_exit

```
intrinsic prim_exit : Nat -> IO Unit
```

## intrinsic prim_argv

```
intrinsic prim_argv : IO (List String)
```

Native argv retains argv[0] and empty arguments as strict UTF-8 strings.

## intrinsic prim_env_get

```
intrinsic prim_env_get : String -> IO (Maybe String)
```

A missing variable or empty name returns Nothing; an empty value is Just "". Native lookup rejects NUL in a name, malformed Unicode and size changes between the sizing call and read with the standard host failure exit 73.

## intrinsic prim_fs_read_file

```
intrinsic prim_fs_read_file : String -> IO String
```

Native files preserve all content bytes. Invalid paths and failed IO exit 73.

## intrinsic prim_fs_write_file

```
intrinsic prim_fs_write_file : String -> String -> IO Unit
```

## intrinsic prim_fs_exists

```
intrinsic prim_fs_exists : String -> IO Bool
```

Native predicates query current Win32 attributes when the action runs. Missing/ordinary query errors return False; invalid encoding and cleanup exit 73.

## intrinsic prim_fs_is_dir

```
intrinsic prim_fs_is_dir : String -> IO Bool
```

## intrinsic prim_fs_list_dir

```
intrinsic prim_fs_list_dir : String -> IO (List String)
```

## intrinsic prim_fs_listable

```
intrinsic prim_fs_listable : String -> IO Bool
```

## intrinsic prim_fs_kind

```
intrinsic prim_fs_kind : String -> IO Nat
```

No-follow kind: 0 missing/error, 1 regular file, 2 directory, 3 symlink/reparse/other. Native paths are strict UTF-8; invalid path storage/encoding and cleanup fail with 73.

## intrinsic prim_fs_realpath

```
intrinsic prim_fs_realpath : String -> IO String
```

Realpath follows links and returns normalized UTF-8 on each action execution. Empty paths and OS unavailability return empty. Native malformed text, raw allocation, incomplete conversion/fill and cleanup failures exit 73.

## intrinsic prim_fs_mkdir

```
intrinsic prim_fs_mkdir : String -> IO Unit
```

Directory create (parents included) and non-recursive path removal. Unit does not confirm the postcondition; use checked filesystem wrappers. Native paths use strict UTF-8. Empty paths do nothing; invalid parameters, encoding, raw allocation and cleanup failures exit 73. Other OS errors return Unit.

## intrinsic prim_fs_remove

```
intrinsic prim_fs_remove : String -> IO Unit
```

## intrinsic prim_fs_temp_file

```
intrinsic prim_fs_temp_file : IO String
```

Creates a private, unique empty file; caller owns removal. Empty = failure.

## intrinsic prim_fs_temp_file_in

```
intrinsic prim_fs_temp_file_in : String -> IO String
```

Same contract in an existing caller-authorized directory.

## intrinsic prim_fs_copy_file

```
intrinsic prim_fs_copy_file : String -> String -> IO Unit
```

Native copy uses strict UTF-8 paths and overwrites through CopyFileW. Invalid paths, failed copies and raw cleanup failures exit 73.

## intrinsic prim_fs_rename

```
intrinsic prim_fs_rename : String -> String -> IO Nat
```

Same-volume replacement: zero means success; nonzero is the OS error. Failure keeps the source and destination. No cross-volume copy is attempted.

## intrinsic prim_process_capture

```
intrinsic prim_process_capture : String -> List String -> IO (Pair Nat (Pair String String))
```

Capture keeps binary stdout/stderr separate and launches the explicit argv.

## intrinsic prim_process_inherit

```
intrinsic prim_process_inherit : String -> List String -> IO (Pair Nat Nat)
```

The pair is (OS error, child exit); OS error zero denotes a completed wait.

## intrinsic prim_process_capture_bounded

```
intrinsic prim_process_capture_bounded : String -> List String ->
```

Limits: timeout ms, memory MiB, CPU count, stdout bytes, stderr bytes. Reply: kind, detail, measured peak Job commit bytes, exact byte streams.

## def prim_proc_exec

```
def prim_proc_exec (command : String) (arguments : List String) : IO ProcResult
```

## intrinsic prim_time_now

```
intrinsic prim_time_now : IO String
```

UTC Unix-epoch milliseconds, rounded down and rendered as decimal. Reading occurs when the action runs; native platform failures exit 73.
