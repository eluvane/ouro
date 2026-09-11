# std/config.ouro

Bounded key=value config support for small tools.

Declarations: 23.

## inductive ConfigError

```
inductive ConfigError : Type
```

## def Config

```
def Config : Type
```

## def config_empty

```
def config_empty : Config
```

## def config_error_code

```
def config_error_code (e : ConfigError) : String
```

## def config_error_message

```
def config_error_message (e : ConfigError) : String
```

## def config_line_payload

```
def config_line_payload (line : String) : Maybe (Pair String String)
```

## def config_insert_line

```
def config_insert_line (line : String) (cfg : Config) : Config
```

## def config_parse

```
def config_parse (text : String) : Config
```

## def config_from_string

```
def config_from_string (text : String) : Config
```

## def config_get

```
def config_get (cfg : Config) (key : String) : Maybe String
```

## def config_has

```
def config_has (cfg : Config) (key : String) : Bool
```

## def config_get_or

```
def config_get_or (cfg : Config) (key : String) (fallback : String) : String
```

## def config_require

```
def config_require (cfg : Config) (key : String) : Either ConfigError String
```

## def config_get_nat

```
def config_get_nat (cfg : Config) (key : String) : Either ConfigError Nat
```

## def config_get_nat_or

```
def config_get_nat_or (cfg : Config) (key : String) (fallback : Nat) : Nat
```

## def config_get_bool

```
def config_get_bool (cfg : Config) (key : String) : Either ConfigError Bool
```

## def config_get_bool_or

```
def config_get_bool_or (cfg : Config) (key : String) (fallback : Bool) : Bool
```

## def config_keys

```
def config_keys (cfg : Config) : List String
```

## def config_has_all

```
def config_has_all (cfg : Config) (keys : List String) : Bool
```

## def config_render_pair

```
def config_render_pair (p : Pair String String) : String
```

## def config_render

```
def config_render (cfg : Config) : String
```

## def config_merge

```
def config_merge (base : Config) (override : Config) : Config
```

## def config_from_pairs

```
def config_from_pairs (pairs : List (Pair String String)) : Config
```
