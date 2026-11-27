# std/process.ouro

Small process/CLI helpers are wrappers over std/io and std/args.

Declarations: 55.

## inductive ProcessError

```ouro
inductive ProcessError : Type
```

## def process_error_code

```ouro
def process_error_code (e : ProcessError) : String
```

## def process_error_command

```ouro
def process_error_command (e : ProcessError) : String
```

## def process_error_status

```ouro
def process_error_status (e : ProcessError) : Nat
```

## def process_error_stderr

```ouro
def process_error_stderr (e : ProcessError) : String
```

## def process_error_message

```ouro
def process_error_message (e : ProcessError) : String
```

## def process_argv

```ouro
def process_argv : IO (List String)
```

## def process_args

```ouro
def process_args : IO Args
```

## def process_env

```ouro
def process_env (name : String) : IO (Maybe String)
```

## def process_env_or

```ouro
def process_env_or (name : String) (fallback : String) : IO String
```

## def process_exit

```ouro
def process_exit (code : Nat) : IO Unit
```

## def process_stdout

```ouro
def process_stdout (s : String) : IO Unit
```

## def process_stderr

```ouro
def process_stderr (s : String) : IO Unit
```

## def process_out_line

```ouro
def process_out_line (s : String) : IO Unit
```

## def process_err_line

```ouro
def process_err_line (s : String) : IO Unit
```

## def process_run

```ouro
def process_run (cmd : String) (cmd_args : List String) : IO ProcResult
```

## def process_run_checked

```ouro
def process_run_checked (cmd : String) (cmd_args : List String) : IO (Either ProcessError ProcResult)
```

## inductive ProcessRunError

```ouro
inductive ProcessRunError : Type
```

Foreground execution inherits stdin/stdout/stderr, current directory and environment. A successful wait returns every child exit code unchanged. Setup/wait errors are separate from a nonzero child exit.

## def process_run_error_code

```ouro
def process_run_error_code (error : ProcessRunError) : String
```

## def process_run_error_status

```ouro
def process_run_error_status (error : ProcessRunError) : Nat
```

## def process_run_error_message

```ouro
def process_run_error_message (error : ProcessRunError) : String
```

## def process_run_inherited

```ouro
def process_run_inherited (command : String) (arguments : List String) : IO (Either ProcessRunError Nat)
```

## def process_run_inherited_checked

```ouro
def process_run_inherited_checked (command : String) (arguments : List String) : IO (Either ProcessRunError Nat)
```

## inductive ProcessCaptureLimits

```ouro
inductive ProcessCaptureLimits : Type
```

Captured execution with one contained process tree. Zero stream cap means that stream must remain empty. CPU count 1 is the supported initial policy.

## inductive ProcessCaptureLimitField

```ouro
inductive ProcessCaptureLimitField : Type
```

## inductive ProcessCaptureStream

```ouro
inductive ProcessCaptureStream : Type
```

## inductive ProcessCaptureResult

```ouro
inductive ProcessCaptureResult : Type
```

## inductive ProcessCaptureError

```ouro
inductive ProcessCaptureError : Type
```

## def process_capture_proc_result

```ouro
def process_capture_proc_result (result : ProcessCaptureResult) : ProcResult
```

## def process_capture_peak_bytes

```ouro
def process_capture_peak_bytes (result : ProcessCaptureResult) : Nat
```

## def process_capture_default_limits

```ouro
def process_capture_default_limits (timeout_ms : Nat) (stdout_bytes : Nat) (stderr_bytes : Nat)
    : ProcessCaptureLimits
```

## def process_capture_limit_name

```ouro
def process_capture_limit_name (field : ProcessCaptureLimitField) : String
```

## def process_capture_error_code

```ouro
def process_capture_error_code (error : ProcessCaptureError) : String
```

## def process_capture_error_message

```ouro
def process_capture_error_message (error : ProcessCaptureError) : String
```

## def process_capture_word_base

```ouro
def process_capture_word_base : Nat
```

## def process_capture_u32_bound

```ouro
def process_capture_u32_bound : Nat
```

## def process_capture_u64_bound

```ouro
def process_capture_u64_bound : Nat
```

## def process_capture_limits_error

```ouro
def process_capture_limits_error (limits : ProcessCaptureLimits) : Maybe ProcessCaptureLimitField
```

## def process_capture_limits_pair

```ouro
def process_capture_limits_pair (limits : ProcessCaptureLimits) : Pair Nat (Pair Nat (Pair Nat (Pair Nat Nat)))
```

## def process_capture_request

```ouro
def process_capture_request (limits : ProcessCaptureLimits) (input : String)
    : Pair String (Pair Nat (Pair Nat (Pair Nat (Pair Nat Nat))))
```

## def process_capture_invalid_field

```ouro
def process_capture_invalid_field (field : Nat) : ProcessCaptureError
```

## def process_capture_decode

```ouro
def process_capture_decode (limits : ProcessCaptureLimits)
    (reply : Pair Nat (Pair Nat (Pair Nat (Pair String String))))
    : Either ProcessCaptureError ProcessCaptureResult
```

## def process_capture_decode_checked

```ouro
def process_capture_decode_checked (limits : ProcessCaptureLimits)
    (reply : Pair Nat (Pair Nat (Pair Nat (Pair String String))))
    : Either ProcessCaptureError ProcessCaptureResult
```

Keep malformed bridge results fail-closed as well. Stream lengths and peak are checked independently from the child's expected exit code.

## def process_run_captured_bounded_with_input

```ouro
def process_run_captured_bounded_with_input (limits : ProcessCaptureLimits) (command : String)
    (arguments : List String) (input : String)
    : IO (Either ProcessCaptureError ProcessCaptureResult)
```

## def process_run_captured_bounded

```ouro
def process_run_captured_bounded (limits : ProcessCaptureLimits) (command : String) (arguments : List String)
    : IO (Either ProcessCaptureError ProcessCaptureResult)
```

## inductive ProcessDirectoryError

```ouro
inductive ProcessDirectoryError : Type
```

## def process_directory_continuation

```ouro
def process_directory_continuation (code : Nat) : Bool
```

## def process_directory_utf8_valid

```ouro
def process_directory_utf8_valid : List Nat -> Bool
```

## def process_directory_valid

```ouro
def process_directory_valid (directory : String) : Bool
```

## def process_directory_checked

```ouro
def process_directory_checked (directory : String) : Either ProcessDirectoryError String
```

## def process_directory_error_code

```ouro
def process_directory_error_code (error : ProcessDirectoryError) : String
```

## def process_directory_error_message

```ouro
def process_directory_error_message (error : ProcessDirectoryError) : String
```

## def process_directory_result

```ouro
def process_directory_result (result : Either ProcessCaptureError ProcessCaptureResult)
    : Either ProcessDirectoryError ProcessCaptureResult
```

## def process_run_captured_bounded_at_with_input

```ouro
def process_run_captured_bounded_at_with_input (limits : ProcessCaptureLimits) (directory : String)
    (command : String) (arguments : List String) (input : String)
    : IO (Either ProcessDirectoryError ProcessCaptureResult)
```

## def process_run_captured_bounded_at

```ouro
def process_run_captured_bounded_at (limits : ProcessCaptureLimits) (directory : String)
    (command : String) (arguments : List String)
    : IO (Either ProcessDirectoryError ProcessCaptureResult)
```
