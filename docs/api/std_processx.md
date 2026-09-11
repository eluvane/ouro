# std/processx.ouro

Typed command specs, checked execution helpers, and shell-free plan rendering.

Declarations: 22.

## inductive CommandSpec

```
inductive CommandSpec : Type
```

## inductive ProcessPlan

```
inductive ProcessPlan : Type
```

## def command_spec

```
def command_spec (program : String) (args : List String) : CommandSpec
```

## def command_program

```
def command_program (cmd : CommandSpec) : String
```

## def command_args

```
def command_args (cmd : CommandSpec) : List String
```

## def command_add_arg

```
def command_add_arg (cmd : CommandSpec) (arg : String) : CommandSpec
```

## def command_add_args

```
def command_add_args (cmd : CommandSpec) (args : List String) : CommandSpec
```

## def command_argv

```
def command_argv (cmd : CommandSpec) : List String
```

## def command_render

```
def command_render (cmd : CommandSpec) : String
```

## def command_dry_run

```
def command_dry_run (cmd : CommandSpec) : String
```

## def process_run_spec

```
def process_run_spec (cmd : CommandSpec) : IO ProcResult
```

## def process_run_spec_checked

```
def process_run_spec_checked (cmd : CommandSpec) : IO (Either ProcessError ProcResult)
```

## def process_run_expected

```
def process_run_expected (cmd : CommandSpec) (expected : Nat) : IO (Either ProcessError ProcResult)
```

## def process_stdout_checked

```
def process_stdout_checked (cmd : CommandSpec) : IO (Either ProcessError String)
```

## def process_require_empty_stderr

```
def process_require_empty_stderr (cmd : CommandSpec) (result : ProcResult) : Either ProcessError ProcResult
```

## def process_run_quiet_checked

```
def process_run_quiet_checked (cmd : CommandSpec) : IO (Either ProcessError ProcResult)
```

## def process_plan_empty

```
def process_plan_empty : ProcessPlan
```

## def process_plan_add

```
def process_plan_add (plan : ProcessPlan) (cmd : CommandSpec) : ProcessPlan
```

## def process_plan_commands

```
def process_plan_commands (plan : ProcessPlan) : List CommandSpec
```

## def process_plan_render

```
def process_plan_render (plan : ProcessPlan) : String
```

## def process_run_specs_checked

```
def process_run_specs_checked : List CommandSpec -> IO (Either ProcessError (List ProcResult))
```

## def process_run_plan_checked

```
def process_run_plan_checked (plan : ProcessPlan) : IO (Either ProcessError (List ProcResult))
```
