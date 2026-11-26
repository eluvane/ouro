# std/configx.ouro

Check required configuration fields and apply environment overrides.

Declarations: 18.

## inductive ConfigKind

```ouro
inductive ConfigKind : Type
```

## inductive ConfigField

```ouro
inductive ConfigField : Type
```

## def configx_field

```ouro
def configx_field (name : String) (kind : ConfigKind) : ConfigField
```

## def configx_field_name

```ouro
def configx_field_name (field : ConfigField) : String
```

## def configx_field_kind

```ouro
def configx_field_kind (field : ConfigField) : ConfigKind
```

## def configx_set

```ouro
def configx_set (cfg : Config) (key : String) (value : String) : Config
```

## def configx_delete

```ouro
def configx_delete (cfg : Config) (key : String) : Config
```

## def configx_with_default

```ouro
def configx_with_default (cfg : Config) (key : String) (value : String) : Config
```

## def configx_overlay_pairs

```ouro
def configx_overlay_pairs (cfg : Config) (pairs : List (Pair String String)) : Config
```

## def configx_validate_string

```ouro
def configx_validate_string (cfg : Config) (key : String) : Validation ConfigError Unit
```

## def configx_validate_nat

```ouro
def configx_validate_nat (cfg : Config) (key : String) : Validation ConfigError Unit
```

## def configx_validate_bool

```ouro
def configx_validate_bool (cfg : Config) (key : String) : Validation ConfigError Unit
```

## def configx_validate_field

```ouro
def configx_validate_field (cfg : Config) (field : ConfigField) : Validation ConfigError Unit
```

## def configx_validate_schema

```ouro
def configx_validate_schema (cfg : Config) : List ConfigField -> Validation ConfigError Unit
```

## def configx_required_keys

```ouro
def configx_required_keys (cfg : Config) (keys : List String) : Validation ConfigError Unit
```

## def configx_env_override

```ouro
def configx_env_override (cfg : Config) (key : String) (env_name : String) : IO Config
```

## def configx_env_overrides

```ouro
def configx_env_overrides (cfg : Config)
    (pairs : List (Pair String String)) : IO Config
```

## def configx_render_errors

```ouro
def configx_render_errors (errors : List ConfigError) : String
```
