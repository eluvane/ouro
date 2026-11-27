# std/cli.ouro

Typed command-line helpers built on std/args and std/text.

Declarations: 18.

## inductive CliError

```ouro
inductive CliError : Type
```

## def cli_error_code

```ouro
def cli_error_code (e : CliError) : String
```

## def cli_error_message

```ouro
def cli_error_message (e : CliError) : String
```

## def cli_parse

```ouro
def cli_parse (bools : List String) (ws : List String) : Args
```

## def cli_from_argv

```ouro
def cli_from_argv (bools : List String) (av : List String) : Args
```

## def cli_flag

```ouro
def cli_flag (a : Args) (name : String) : Bool
```

## def cli_opt

```ouro
def cli_opt (a : Args) (name : String) : Maybe String
```

## def cli_has_opt

```ouro
def cli_has_opt (a : Args) (name : String) : Bool
```

## def cli_required

```ouro
def cli_required (a : Args) (name : String) : Either CliError String
```

## def cli_required_nat

```ouro
def cli_required_nat (a : Args) (name : String) : Either CliError Nat
```

## def cli_optional_nat

```ouro
def cli_optional_nat (a : Args) (name : String) (fallback : Nat)
    : Either CliError Nat
```

## def cli_required_bool

```ouro
def cli_required_bool (a : Args) (name : String) : Either CliError Bool
```

## def cli_optional_bool

```ouro
def cli_optional_bool (a : Args) (name : String) (fallback : Bool)
    : Either CliError Bool
```

## def cli_pos

```ouro
def cli_pos (a : Args) (i : Nat) : Maybe String
```

## def cli_pos_or

```ouro
def cli_pos_or (a : Args) (i : Nat) (fallback : String) : String
```

## def cli_required_pos

```ouro
def cli_required_pos (a : Args) (i : Nat) (name : String)
    : Either CliError String
```

## def cli_usage

```ouro
def cli_usage (program : String) (shape : String) : String
```

## def cli_error_block

```ouro
def cli_error_block (program : String) (shape : String) (e : CliError) : String
```
