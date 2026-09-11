# std/map.ouro

Sorted maps make generated tool output byte-reproducible; traversal order is key order.

Declarations: 18.

## def Map

```
def Map (V : Type) : Type
```

## def map_empty

```
def map_empty (V : Type) : Map V
```

## def map_null

```
def map_null (V : Type) (m : Map V) : Bool
```

## def map_size

```
def map_size (V : Type) (m : Map V) : Nat
```

## def map_get

```
def map_get (V : Type) (k : String) (m : Map V) : Maybe V
```

## def map_has

```
def map_has (V : Type) (k : String) (m : Map V) : Bool
```

## def map_get_or

```
def map_get_or (V : Type) (d : V) (k : String) (m : Map V) : V
```

## def map_insert

```
def map_insert (V : Type) (k : String) (v : V) : Map V -> Map V
```

Replaces an existing key in place, otherwise inserts before the first larger key, so the list stays sorted.

## def map_delete

```
def map_delete (V : Type) (k : String) (m : Map V) : Map V
```

## def map_keys

```
def map_keys (V : Type) (m : Map V) : List String
```

## def map_values

```
def map_values (V : Type) (m : Map V) : List V
```

## def map_pairs

```
def map_pairs (V : Type) (m : Map V) : List (Pair String V)
```

## def map_union

```
def map_union (V : Type) (a : Map V) (b : Map V) : Map V
```

Later entries of the second map win, matching JSON-object override order.

## def map_from_pairs

```
def map_from_pairs (V : Type) (ps : List (Pair String V)) : Map V
```

## def map_map

```
def map_map (V : Type) (W : Type) (f : V -> W) (m : Map V) : Map W
```

## def map_filter

```
def map_filter (V : Type) (p : String -> V -> Bool) (m : Map V) : Map V
```

## def map_fold

```
def map_fold (V : Type) (B : Type) (f : String -> V -> B -> B) (z : B)
```

## def map_of_strings

```
def map_of_strings (ps : List (Pair String String)) : Map String
```
