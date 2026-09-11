# std/workflow.ouro

Small command workflow abstraction: args, config, validation, action, report.

Declarations: 20.

## inductive CommandError

```
inductive CommandError : Type
```

## inductive CommandContext

```
inductive CommandContext : Type
```

## def CommandResult

```
def CommandResult : Type
```

## def command_context_program

```
def command_context_program (ctx : CommandContext) : String
```

## def command_context_args

```
def command_context_args (ctx : CommandContext) : Args
```

## def command_context_config

```
def command_context_config (ctx : CommandContext) : Config
```

## def command_context

```
def command_context (program : String) (args : Args) (cfg : Config) : CommandContext
```

## def command_error_code

```
def command_error_code (e : CommandError) : String
```

## def command_error_message

```
def command_error_message (e : CommandError) : String
```

## def command_exit_code

```
def command_exit_code (e : CommandError) : Nat
```

## def command_ok

```
def command_ok (r : Report) : CommandResult
```

## def command_ok_message

```
def command_ok_message (message : String) : CommandResult
```

## def command_fail

```
def command_fail (e : CommandError) : CommandResult
```

## def command_usage

```
def command_usage (program : String) (shape : String) : CommandResult
```

## def command_lift_fs

```
def command_lift_fs (A : Type) (r : Either FsError A) : Either CommandError A
```

## def command_lift_config

```
def command_lift_config (A : Type) (r : Either ConfigError A) : Either CommandError A
```

## def command_lift_process

```
def command_lift_process (A : Type) (r : Either ProcessError A) : Either CommandError A
```

## def command_lift_validation

```
def command_lift_validation (v : Validation String Unit) : Either CommandError Unit
```

## def command_report

```
def command_report (ctx : CommandContext) (body : Report) : Report
```

## def command_run_result

```
def command_run_result (result : CommandResult) : IO Unit
```
