# std/configx.ouro

Schema-lite config validation and environment override helpers.

Declarations: 18.

## inductive ConfigKind

```
inductive ConfigKind : Type
```

## inductive ConfigField

```
inductive ConfigField : Type
```

## def configx_field

```
def configx_field (name : String) (kind : ConfigKind) : ConfigField
```

## def configx_field_name

```
def configx_field_name (field : ConfigField) : String
```

## def configx_field_kind

```
def configx_field_kind (field : ConfigField) : ConfigKind
```

## def configx_set

```
def configx_set (cfg : Config) (key : String) (value : String) : Config
```

## def configx_delete

```
def configx_delete (cfg : Config) (key : String) : Config
```

## def configx_with_default

```
def configx_with_default (cfg : Config) (key : String) (value : String) : Config
```

## def configx_overlay_pairs

```
def configx_overlay_pairs (cfg : Config) (pairs : List (Pair String String)) : Config
```

## def configx_validate_string

```
def configx_validate_string (cfg : Config) (key : String) : Validation ConfigError Unit
```

## def configx_validate_nat

```
def configx_validate_nat (cfg : Config) (key : String) : Validation ConfigError Unit
```

## def configx_validate_bool

```
def configx_validate_bool (cfg : Config) (key : String) : Validation ConfigError Unit
```

## def configx_validate_field

```
def configx_validate_field (cfg : Config) (field : ConfigField) : Validation ConfigError Unit
```

## def configx_validate_schema

```
def configx_validate_schema (cfg : Config) : List ConfigField -> Validation ConfigError Unit
```

## def configx_required_keys

```
def configx_required_keys (cfg : Config) (keys : List String) : Validation ConfigError Unit
```

## def configx_env_override

```
def configx_env_override (cfg : Config) (key : String) (env_name : String) : IO Config
```

## def configx_env_overrides

```
def configx_env_overrides (cfg : Config)
```

## def configx_render_errors

```
def configx_render_errors (errors : List ConfigError) : String
```
