# std/processx.ouro

Typed command specs, checked execution helpers, and shell-free plan rendering.

Declarations: 29.

## inductive CommandSpec

```ouro
inductive CommandSpec : Type
```

## inductive ProcessPlan

```ouro
inductive ProcessPlan : Type
```

## def command_spec

```ouro
def command_spec (program : String) (args : List String) : CommandSpec
```

## def command_program

```ouro
def command_program (cmd : CommandSpec) : String
```

## def command_args

```ouro
def command_args (cmd : CommandSpec) : List String
```

## def command_add_arg

```ouro
def command_add_arg (cmd : CommandSpec) (arg : String) : CommandSpec
```

## def command_add_args

```ouro
def command_add_args (cmd : CommandSpec) (args : List String) : CommandSpec
```

## def command_argv

```ouro
def command_argv (cmd : CommandSpec) : List String
```

## def command_render

```ouro
def command_render (cmd : CommandSpec) : String
```

## def command_dry_run

```ouro
def command_dry_run (cmd : CommandSpec) : String
```

## def process_run_spec

```ouro
def process_run_spec (cmd : CommandSpec) : IO ProcResult
```

## def process_run_spec_checked

```ouro
def process_run_spec_checked (cmd : CommandSpec) : IO (Either ProcessError ProcResult)
```

## def process_run_expected_codes

```ouro
def process_run_expected_codes (cmd : CommandSpec) (expected : List Nat) : IO (Either ProcessError ProcResult)
```

Preserve both captured streams for any explicitly accepted exit status. An empty list rejects every result, including exit status zero.

## def process_stdout_checked

```ouro
def process_stdout_checked (cmd : CommandSpec) : IO (Either ProcessError String)
```

## def process_require_empty_stderr

```ouro
def process_require_empty_stderr (cmd : CommandSpec) (result : ProcResult) : Either ProcessError ProcResult
```

## def process_run_expected

```ouro
def process_run_expected (cmd : CommandSpec) (expected : Nat) : IO (Either ProcessError ProcResult)
```

## def process_run_quiet_checked

```ouro
def process_run_quiet_checked (cmd : CommandSpec) : IO (Either ProcessError ProcResult)
```

## def process_plan_empty

```ouro
def process_plan_empty : ProcessPlan
```

## def process_plan_add

```ouro
def process_plan_add (plan : ProcessPlan) (cmd : CommandSpec) : ProcessPlan
```

## def process_plan_commands

```ouro
def process_plan_commands (plan : ProcessPlan) : List CommandSpec
```

## def process_plan_render

```ouro
def process_plan_render (plan : ProcessPlan) : String
```

## def process_run_specs_checked

```ouro
def process_run_specs_checked : List CommandSpec -> IO (Either ProcessError (List ProcResult))
```

## def process_run_plan_checked

```ouro
def process_run_plan_checked (plan : ProcessPlan) : IO (Either ProcessError (List ProcResult))
```

## def process_run_spec_inherited

```ouro
def process_run_spec_inherited (command : CommandSpec) : IO (Either ProcessRunError Nat)
```

## def process_run_spec_inherited_checked

```ouro
def process_run_spec_inherited_checked (command : CommandSpec) : IO (Either ProcessRunError Nat)
```

## def process_run_spec_captured_bounded

```ouro
def process_run_spec_captured_bounded (limits : ProcessCaptureLimits) (command : CommandSpec)
    : IO (Either ProcessCaptureError ProcessCaptureResult)
```

## def process_run_spec_captured_bounded_with_input

```ouro
def process_run_spec_captured_bounded_with_input (limits : ProcessCaptureLimits) (command : CommandSpec) (input : String)
    : IO (Either ProcessCaptureError ProcessCaptureResult)
```

## def process_run_spec_captured_bounded_at

```ouro
def process_run_spec_captured_bounded_at (limits : ProcessCaptureLimits) (directory : String)
    (command : CommandSpec) : IO (Either ProcessDirectoryError ProcessCaptureResult)
```

## def process_run_spec_captured_bounded_at_with_input

```ouro
def process_run_spec_captured_bounded_at_with_input (limits : ProcessCaptureLimits) (directory : String)
    (command : CommandSpec) (input : String) : IO (Either ProcessDirectoryError ProcessCaptureResult)
```
