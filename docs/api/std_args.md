# std/args.ouro

Parse long options and single-dash flags. `--` ends option parsing. A bare long option listed in `bools` is a flag and leaves the next word for separate parsing.

Declarations: 24.

## inductive Args

```ouro
inductive Args : Type
```

## def args_positional

```ouro
def args_positional (a : Args) : List String
```

## def args_opts

```ouro
def args_opts (a : Args) : Map String
```

## def args_flags

```ouro
def args_flags (a : Args) : List String
```

## def args_empty

```ouro
def args_empty : Args
```

## def args_flag

```ouro
def args_flag (a : Args) (name : String) : Bool
```

## def args_opt

```ouro
def args_opt (a : Args) (name : String) : Maybe String
```

## def args_opt_or

```ouro
def args_opt_or (a : Args) (name : String) (d : String) : String
```

## def args_at

```ouro
def args_at (a : Args) (i : Nat) : String
```

Positional word i, "" when absent. args_cmd is the usual subcommand slot.

## def args_cmd

```ouro
def args_cmd (a : Args) : String
```

## def args_add_pos

```ouro
def args_add_pos (a : Args) (w : String) : Args
```

## def args_add_flag

```ouro
def args_add_flag (a : Args) (name : String) : Args
```

## def args_add_opt

```ouro
def args_add_opt (a : Args) (name : String) (v : String) : Args
```

## def is_dashed

```ouro
def is_dashed (w : String) : Bool
```

## def long_name

```ouro
def long_name (w : String) : Maybe String
```

A long option name without its leading dashes, Nothing for other words.

## def short_name

```ouro
def short_name (w : String) : Maybe String
```

## def args_parse_go

```ouro
def args_parse_go : Nat -> List String -> Args -> Bool -> List String -> Args
```

## def args_parse_bools

```ouro
def args_parse_bools (bools : List String) (ws : List String) : Args
```

## def args_parse

```ouro
def args_parse (ws : List String) : Args
```

## def args_of_argv

```ouro
def args_of_argv (argv : List String) : Args
```

Skip argument zero, which contains the program path.

## def args_of_argv_bools

```ouro
def args_of_argv_bools (bools : List String) (argv : List String) : Args
```

## def args_argv_options_complete

```ouro
def args_argv_options_complete (bools : List String) (argv : List String) : Bool
```

Check before parsing that each non-boolean long option has a value. The value can follow `=` or be the next word if it does not start with `-`.

## def opt_show

```ouro
def opt_show (p : Pair String String) : String
```

## def args_show

```ouro
def args_show (a : Args) : String
```
