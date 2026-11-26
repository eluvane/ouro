# std/workflow.ouro

Small command workflow abstraction: args, config, validation, action, report.

Declarations: 20.

## inductive CommandError

```ouro
inductive CommandError : Type
```

## inductive CommandContext

```ouro
inductive CommandContext : Type
```

## def CommandResult

```ouro
def CommandResult : Type
```

## def command_context_program

```ouro
def command_context_program (ctx : CommandContext) : String
```

## def command_context_args

```ouro
def command_context_args (ctx : CommandContext) : Args
```

## def command_context_config

```ouro
def command_context_config (ctx : CommandContext) : Config
```

## def command_context

```ouro
def command_context (program : String) (args : Args) (cfg : Config) : CommandContext
```

## def command_error_code

```ouro
def command_error_code (e : CommandError) : String
```

## def command_error_message

```ouro
def command_error_message (e : CommandError) : String
```

## def command_exit_code

```ouro
def command_exit_code (e : CommandError) : Nat
```

## def command_ok

```ouro
def command_ok (r : Report) : CommandResult
```

## def command_ok_message

```ouro
def command_ok_message (message : String) : CommandResult
```

## def command_fail

```ouro
def command_fail (e : CommandError) : CommandResult
```

## def command_usage

```ouro
def command_usage (program : String) (shape : String) : CommandResult
```

## def command_lift_fs

```ouro
def command_lift_fs (A : Type) (r : Either FsError A) : Either CommandError A
```

## def command_lift_config

```ouro
def command_lift_config (A : Type) (r : Either ConfigError A) : Either CommandError A
```

## def command_lift_process

```ouro
def command_lift_process (A : Type) (r : Either ProcessError A) : Either CommandError A
```

## def command_lift_validation

```ouro
def command_lift_validation (v : Validation String Unit) : Either CommandError Unit
```

## def command_report

```ouro
def command_report (ctx : CommandContext) (body : Report) : Report
```

## def command_run_result

```ouro
def command_run_result (result : CommandResult) : IO Unit
```
