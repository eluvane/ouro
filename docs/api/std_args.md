# std/args.ouro

Command-line grammar is small by design: long options, single-dash flags, and -- to end options. Boolean switches are passed in so --flag value cannot accidentally consume a positional word.

Declarations: 24.

## inductive Args

```
inductive Args : Type
```

## def args_positional

```
def args_positional (a : Args) : List String
```

## def args_opts

```
def args_opts (a : Args) : Map String
```

## def args_flags

```
def args_flags (a : Args) : List String
```

## def args_empty

```
def args_empty : Args
```

## def args_flag

```
def args_flag (a : Args) (name : String) : Bool
```

## def args_opt

```
def args_opt (a : Args) (name : String) : Maybe String
```

## def args_opt_or

```
def args_opt_or (a : Args) (name : String) (d : String) : String
```

## def args_at

```
def args_at (a : Args) (i : Nat) : String
```

Positional word i, "" when absent. args_cmd is the usual subcommand slot.

## def args_cmd

```
def args_cmd (a : Args) : String
```

## def args_add_pos

```
def args_add_pos (a : Args) (w : String) : Args
```

## def args_add_flag

```
def args_add_flag (a : Args) (name : String) : Args
```

## def args_add_opt

```
def args_add_opt (a : Args) (name : String) (v : String) : Args
```

## def is_dashed

```
def is_dashed (w : String) : Bool
```

## def long_name

```
def long_name (w : String) : Maybe String
```

A long option name without its leading dashes, Nothing for other words.

## def short_name

```
def short_name (w : String) : Maybe String
```

## def args_parse_go

```
def args_parse_go : Nat -> List String -> Args -> Bool -> List String -> Args
```

## def args_parse_bools

```
def args_parse_bools (bools : List String) (ws : List String) : Args
```

## def args_parse

```
def args_parse (ws : List String) : Args
```

## def args_of_argv

```
def args_of_argv (argv : List String) : Args
```

prim_argv keeps the program path in slot 0; tools want the rest.

## def args_of_argv_bools

```
def args_of_argv_bools (bools : List String) (argv : List String) : Args
```

## def args_argv_options_complete

```
def args_argv_options_complete (bools : List String) (argv : List String) : Bool
```

Strict command entry points can reject a non-boolean long option whose value is absent before using the intentionally forgiving Args parser.

## def opt_show

```
def opt_show (p : Pair String String) : String
```

## def args_show

```
def args_show (a : Args) : String
```
