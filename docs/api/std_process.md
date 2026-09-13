# std/process.ouro

Small process/CLI helpers are wrappers over std/io and std/args.

Declarations: 45.

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

## inductive ProcessRunError

```
inductive ProcessRunError : Type
```

Foreground execution inherits stdin/stdout/stderr, current directory and environment. A successful wait returns every child exit code unchanged. Setup/wait errors are separate from a nonzero child exit.

## def process_run_error_code

```
def process_run_error_code (error : ProcessRunError) : String
```

## def process_run_error_status

```
def process_run_error_status (error : ProcessRunError) : Nat
```

## def process_run_error_message

```
def process_run_error_message (error : ProcessRunError) : String
```

## def process_run_inherited

```
def process_run_inherited (command : String) (arguments : List String) : IO (Either ProcessRunError Nat)
```

## def process_run_inherited_checked

```
def process_run_inherited_checked (command : String) (arguments : List String) : IO (Either ProcessRunError Nat)
```

## inductive ProcessCaptureLimits

```
inductive ProcessCaptureLimits : Type
```

Captured execution with one contained process tree. Zero stream cap means that stream must remain empty. CPU count 1 is the supported initial policy.

## inductive ProcessCaptureLimitField

```
inductive ProcessCaptureLimitField : Type
```

## inductive ProcessCaptureStream

```
inductive ProcessCaptureStream : Type
```

## inductive ProcessCaptureResult

```
inductive ProcessCaptureResult : Type
```

## inductive ProcessCaptureError

```
inductive ProcessCaptureError : Type
```

## def process_capture_proc_result

```
def process_capture_proc_result (result : ProcessCaptureResult) : ProcResult
```

## def process_capture_peak_bytes

```
def process_capture_peak_bytes (result : ProcessCaptureResult) : Nat
```

## def process_capture_default_limits

```
def process_capture_default_limits (timeout_ms : Nat) (stdout_bytes : Nat) (stderr_bytes : Nat)
```

## def process_capture_limit_name

```
def process_capture_limit_name (field : ProcessCaptureLimitField) : String
```

## def process_capture_error_code

```
def process_capture_error_code (error : ProcessCaptureError) : String
```

## def process_capture_error_message

```
def process_capture_error_message (error : ProcessCaptureError) : String
```

## def process_capture_word_base

```
def process_capture_word_base : Nat
```

## def process_capture_u32_bound

```
def process_capture_u32_bound : Nat
```

## def process_capture_u64_bound

```
def process_capture_u64_bound : Nat
```

## def process_capture_limits_error

```
def process_capture_limits_error (limits : ProcessCaptureLimits) : Maybe ProcessCaptureLimitField
```

## def process_capture_limits_pair

```
def process_capture_limits_pair (limits : ProcessCaptureLimits) : Pair Nat (Pair Nat (Pair Nat (Pair Nat Nat)))
```

## def process_capture_request

```
def process_capture_request (limits : ProcessCaptureLimits) (input : String)
```

## def process_capture_invalid_field

```
def process_capture_invalid_field (field : Nat) : ProcessCaptureError
```

## def process_capture_decode

```
def process_capture_decode (limits : ProcessCaptureLimits)
```

## def process_capture_decode_checked

```
def process_capture_decode_checked (limits : ProcessCaptureLimits)
```

Keep malformed bridge results fail-closed as well. Stream lengths and peak are checked independently from the child's expected exit code.

## def process_run_captured_bounded_with_input

```
def process_run_captured_bounded_with_input (limits : ProcessCaptureLimits) (command : String)
```

## def process_run_captured_bounded

```
def process_run_captured_bounded (limits : ProcessCaptureLimits) (command : String) (arguments : List String)
```
