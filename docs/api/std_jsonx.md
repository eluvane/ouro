# std/jsonx.ouro

Practical JSON object/array getters and schema-lite decoders.

Declarations: 29.

## def jsonx_null

```
def jsonx_null : Json
```

## def jsonx_bool

```
def jsonx_bool (b : Bool) : Json
```

## def jsonx_num_string

```
def jsonx_num_string (n : String) : Json
```

## def jsonx_num_nat

```
def jsonx_num_nat (n : Nat) : Json
```

## def jsonx_string

```
def jsonx_string (s : String) : Json
```

## def jsonx_array

```
def jsonx_array (xs : List Json) : Json
```

## def jsonx_object

```
def jsonx_object (xs : List (Pair String Json)) : Json
```

## def jsonx_as_string

```
def jsonx_as_string (j : Json) : Maybe String
```

## def jsonx_as_nat

```
def jsonx_as_nat (j : Json) : Maybe Nat
```

## def jsonx_as_bool

```
def jsonx_as_bool (j : Json) : Maybe Bool
```

## def jsonx_as_array

```
def jsonx_as_array (j : Json) : Maybe (List Json)
```

## def jsonx_as_object

```
def jsonx_as_object (j : Json) : Maybe (List (Pair String Json))
```

## def jsonx_obj_get_pairs

```
def jsonx_obj_get_pairs (key : String) : List (Pair String Json) -> Maybe Json
```

## def jsonx_get

```
def jsonx_get (j : Json) (key : String) : Maybe Json
```

## def jsonx_get_string

```
def jsonx_get_string (j : Json) (key : String) : Maybe String
```

## def jsonx_get_nat

```
def jsonx_get_nat (j : Json) (key : String) : Maybe Nat
```

## def jsonx_get_bool

```
def jsonx_get_bool (j : Json) (key : String) : Maybe Bool
```

## def jsonx_get_array

```
def jsonx_get_array (j : Json) (key : String) : Maybe (List Json)
```

## def jsonx_get_object

```
def jsonx_get_object (j : Json) (key : String) : Maybe (List (Pair String Json))
```

## def jsonx_array_at

```
def jsonx_array_at (j : Json) (index : Nat) : Maybe Json
```

## def jsonx_path

```
def jsonx_path (j : Json) (path : List String) : Maybe Json
```

## def jsonx_path_string

```
def jsonx_path_string (j : Json) (path : List String) : Maybe String
```

## def jsonx_path_bool

```
def jsonx_path_bool (j : Json) (path : List String) : Maybe Bool
```

## def jsonx_path_nat

```
def jsonx_path_nat (j : Json) (path : List String) : Maybe Nat
```

## def jsonx_object_keys

```
def jsonx_object_keys (j : Json) : List String
```

## def jsonx_string_pair

```
def jsonx_string_pair (p : Pair String String) : Pair String Json
```

## def jsonx_object_from_strings

```
def jsonx_object_from_strings (pairs : List (Pair String String)) : Json
```

## def jsonx_parse_or_null

```
def jsonx_parse_or_null (text : String) : Json
```

## def jsonx_render

```
def jsonx_render (j : Json) : String
```
