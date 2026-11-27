# std/jsonx.ouro

Practical JSON object/array getters and schema-lite decoders.

Declarations: 29.

## def jsonx_null

```ouro
def jsonx_null : Json
```

## def jsonx_bool

```ouro
def jsonx_bool (b : Bool) : Json
```

## def jsonx_num_string

```ouro
def jsonx_num_string (n : String) : Json
```

## def jsonx_num_nat

```ouro
def jsonx_num_nat (n : Nat) : Json
```

## def jsonx_string

```ouro
def jsonx_string (s : String) : Json
```

## def jsonx_array

```ouro
def jsonx_array (xs : List Json) : Json
```

## def jsonx_object

```ouro
def jsonx_object (xs : List (Pair String Json)) : Json
```

## def jsonx_as_string

```ouro
def jsonx_as_string (j : Json) : Maybe String
```

## def jsonx_as_nat

```ouro
def jsonx_as_nat (j : Json) : Maybe Nat
```

## def jsonx_as_bool

```ouro
def jsonx_as_bool (j : Json) : Maybe Bool
```

## def jsonx_as_array

```ouro
def jsonx_as_array (j : Json) : Maybe (List Json)
```

## def jsonx_as_object

```ouro
def jsonx_as_object (j : Json) : Maybe (List (Pair String Json))
```

## def jsonx_obj_get_pairs

```ouro
def jsonx_obj_get_pairs (key : String) : List (Pair String Json) -> Maybe Json
```

## def jsonx_get

```ouro
def jsonx_get (j : Json) (key : String) : Maybe Json
```

## def jsonx_get_string

```ouro
def jsonx_get_string (j : Json) (key : String) : Maybe String
```

## def jsonx_get_nat

```ouro
def jsonx_get_nat (j : Json) (key : String) : Maybe Nat
```

## def jsonx_get_bool

```ouro
def jsonx_get_bool (j : Json) (key : String) : Maybe Bool
```

## def jsonx_get_array

```ouro
def jsonx_get_array (j : Json) (key : String) : Maybe (List Json)
```

## def jsonx_get_object

```ouro
def jsonx_get_object (j : Json) (key : String) : Maybe (List (Pair String Json))
```

## def jsonx_array_at

```ouro
def jsonx_array_at (j : Json) (index : Nat) : Maybe Json
```

## def jsonx_path

```ouro
def jsonx_path (j : Json) (path : List String) : Maybe Json
```

## def jsonx_path_string

```ouro
def jsonx_path_string (j : Json) (path : List String) : Maybe String
```

## def jsonx_path_bool

```ouro
def jsonx_path_bool (j : Json) (path : List String) : Maybe Bool
```

## def jsonx_path_nat

```ouro
def jsonx_path_nat (j : Json) (path : List String) : Maybe Nat
```

## def jsonx_object_keys

```ouro
def jsonx_object_keys (j : Json) : List String
```

## def jsonx_string_pair

```ouro
def jsonx_string_pair (p : Pair String String) : Pair String Json
```

## def jsonx_object_from_strings

```ouro
def jsonx_object_from_strings (pairs : List (Pair String String)) : Json
```

## def jsonx_parse_or_null

```ouro
def jsonx_parse_or_null (text : String) : Json
```

## def jsonx_render

```ouro
def jsonx_render (j : Json) : String
```
