# std/runtime.ouro

Runtime surface: checked String identities and composable Runtime actions. Streams, exit, startup, clock and binary files have checked native adapters.

Declarations: 34.

## axiom prim_json_string_parse

```ouro
axiom prim_json_string_parse : String -> Nat -> Pair (Maybe String) Nat
```

Linear, non-recursive JSON string decode from an opening quote. The Nat is the first byte after the closing quote, or the failure position.

## inductive ProcResult

```ouro
inductive ProcResult : Type
```

## def IO

```ouro
def IO (A : Type) : Type
```

IO and raw system actions share one checked effect constructor.

## def io_pure

```ouro
def io_pure (A : Type) (value : A) : IO A
```

## def io_bind

```ouro
def io_bind (A : Type) (B : Type) (action : IO A) (next : A -> IO B) : IO B
```

## intrinsic prim_stdout_write

```ouro
intrinsic prim_stdout_write : String -> IO Unit
```

## intrinsic prim_stderr_write

```ouro
intrinsic prim_stderr_write : String -> IO Unit
```

## intrinsic prim_stdin_read_line

```ouro
intrinsic prim_stdin_read_line : IO String
```

Native line input consumes at most 8191 bytes, removes LF and preserves CR.

## intrinsic prim_stdin_read_bytes

```ouro
intrinsic prim_stdin_read_bytes : Nat -> IO String
```

Reads at most n bytes; a short result means end of input. Native input preserves NUL and runs only when the action is invoked. Conversion, allocation, read and cleanup failures terminate with status 73.

## intrinsic prim_stdout_flush

```ouro
intrinsic prim_stdout_flush : IO Unit
```

## intrinsic prim_exit

```ouro
intrinsic prim_exit : Nat -> IO Unit
```

## intrinsic prim_argv

```ouro
intrinsic prim_argv : IO (List String)
```

Native argv retains argv[0] and empty arguments as strict UTF-8 strings.

## intrinsic prim_env_get

```ouro
intrinsic prim_env_get : String -> IO (Maybe String)
```

A missing variable or empty name returns Nothing; an empty value is Just "". Native lookup rejects NUL in a name, malformed Unicode and size changes between the sizing call and read with the standard host failure exit 73.

## intrinsic prim_fs_read_file

```ouro
intrinsic prim_fs_read_file : String -> IO String
```

Native files preserve all content bytes. Invalid paths and failed IO exit 73.

## intrinsic prim_fs_read_file_status

```ouro
intrinsic prim_fs_read_file_status : String -> IO (Pair Nat String)
```

Status zero carries the complete bytes; OS read errors carry an empty body. Native raw status is Win32 (including provider validation codes); C uses errno. Malformed path text, compiler guards, allocation and cleanup still exit 73.

## intrinsic prim_fs_write_file

```ouro
intrinsic prim_fs_write_file : String -> String -> IO Unit
```

## intrinsic prim_fs_exists

```ouro
intrinsic prim_fs_exists : String -> IO Bool
```

Native predicates query current Win32 attributes when the action runs. Missing/ordinary query errors return False; invalid encoding and cleanup exit 73.

## intrinsic prim_fs_is_dir

```ouro
intrinsic prim_fs_is_dir : String -> IO Bool
```

## intrinsic prim_fs_list_dir

```ouro
intrinsic prim_fs_list_dir : String -> IO (List String)
```

## intrinsic prim_fs_listable

```ouro
intrinsic prim_fs_listable : String -> IO Bool
```

## intrinsic prim_fs_kind

```ouro
intrinsic prim_fs_kind : String -> IO Nat
```

No-follow kind: 0 missing/error, 1 regular file, 2 directory, 3 symlink/reparse/other. Native paths are strict UTF-8; invalid path storage/encoding and cleanup fail with 73.

## intrinsic prim_fs_realpath

```ouro
intrinsic prim_fs_realpath : String -> IO String
```

Realpath follows links and returns normalized UTF-8 on each action execution. Empty paths and OS unavailability return empty. Native malformed text, raw allocation, incomplete conversion/fill and cleanup failures exit 73.

## intrinsic prim_fs_mkdir

```ouro
intrinsic prim_fs_mkdir : String -> IO Unit
```

Directory create (parents included) and non-recursive path removal. Unit does not confirm the postcondition; use checked filesystem wrappers. Native paths use strict UTF-8. Empty paths do nothing; invalid parameters, encoding, raw allocation and cleanup failures exit 73. Other OS errors return Unit.

## intrinsic prim_fs_remove

```ouro
intrinsic prim_fs_remove : String -> IO Unit
```

## intrinsic prim_fs_temp_file

```ouro
intrinsic prim_fs_temp_file : IO String
```

Creates a private, unique empty file; caller owns removal. Empty = failure.

## intrinsic prim_fs_temp_file_in

```ouro
intrinsic prim_fs_temp_file_in : String -> IO String
```

Same contract in an existing caller-authorized directory.

## intrinsic prim_fs_copy_file

```ouro
intrinsic prim_fs_copy_file : String -> String -> IO Unit
```

Native copy uses strict UTF-8 paths and overwrites through CopyFileW. Invalid paths, failed copies and raw cleanup failures exit 73.

## intrinsic prim_fs_rename

```ouro
intrinsic prim_fs_rename : String -> String -> IO Nat
```

Same-volume replacement: zero means success; nonzero is the OS error. Failure keeps the source and destination. No cross-volume copy is attempted.

## intrinsic prim_process_capture

```ouro
intrinsic prim_process_capture : String -> List String -> IO (Pair Nat (Pair String String))
```

Capture keeps binary stdout/stderr separate and launches the explicit argv.

## intrinsic prim_process_inherit

```ouro
intrinsic prim_process_inherit : String -> List String -> IO (Pair Nat Nat)
```

The pair is (OS error, child exit); OS error zero denotes a completed wait.

## intrinsic prim_process_capture_bounded

```ouro
intrinsic prim_process_capture_bounded : String -> List String ->
    Pair String (Pair Nat (Pair Nat (Pair Nat (Pair Nat Nat)))) ->
    IO (Pair Nat (Pair Nat (Pair Nat (Pair String String))))
```

Limits: timeout ms, memory MiB, CPU count, stdout bytes, stderr bytes. Reply: kind, detail, measured peak Job commit bytes, exact byte streams.

## intrinsic prim_process_capture_bounded_at

```ouro
intrinsic prim_process_capture_bounded_at : String -> List String -> String ->
    Pair String (Pair Nat (Pair Nat (Pair Nat (Pair Nat Nat)))) ->
    IO (Pair Nat (Pair Nat (Pair Nat (Pair String String))))
```

Separate cwd identity retains the inherited-cwd request and reply contract.

## def prim_proc_exec

```ouro
def prim_proc_exec (command : String) (arguments : List String) : IO ProcResult
```

## intrinsic prim_time_now

```ouro
intrinsic prim_time_now : IO String
```

UTC Unix-epoch milliseconds, rounded down and rendered as decimal. Reading occurs when the action runs; native platform failures exit 73.
