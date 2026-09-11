# std/cli.ouro

Typed command-line helpers built on std/args and std/text.

Declarations: 18.

## inductive CliError

```
inductive CliError : Type
```

## def cli_error_code

```
def cli_error_code (e : CliError) : String
```

## def cli_error_message

```
def cli_error_message (e : CliError) : String
```

## def cli_parse

```
def cli_parse (bools : List String) (ws : List String) : Args
```

## def cli_from_argv

```
def cli_from_argv (bools : List String) (av : List String) : Args
```

## def cli_flag

```
def cli_flag (a : Args) (name : String) : Bool
```

## def cli_opt

```
def cli_opt (a : Args) (name : String) : Maybe String
```

## def cli_has_opt

```
def cli_has_opt (a : Args) (name : String) : Bool
```

## def cli_required

```
def cli_required (a : Args) (name : String) : Either CliError String
```

## def cli_required_nat

```
def cli_required_nat (a : Args) (name : String) : Either CliError Nat
```

## def cli_optional_nat

```
def cli_optional_nat (a : Args) (name : String) (fallback : Nat)
```

## def cli_required_bool

```
def cli_required_bool (a : Args) (name : String) : Either CliError Bool
```

## def cli_optional_bool

```
def cli_optional_bool (a : Args) (name : String) (fallback : Bool)
```

## def cli_pos

```
def cli_pos (a : Args) (i : Nat) : Maybe String
```

## def cli_pos_or

```
def cli_pos_or (a : Args) (i : Nat) (fallback : String) : String
```

## def cli_required_pos

```
def cli_required_pos (a : Args) (i : Nat) (name : String)
```

## def cli_usage

```
def cli_usage (program : String) (shape : String) : String
```

## def cli_error_block

```
def cli_error_block (program : String) (shape : String) (e : CliError) : String
```
