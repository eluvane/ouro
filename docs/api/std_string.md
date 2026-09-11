# std/string.ouro

String operations delegate byte semantics to trusted runtime primitives.

Declarations: 37.

## def str_len

```
def str_len (s : String) : Nat
```

## def str_eq

```
def str_eq (a : String) (b : String) : Bool
```

## def str_concat

```
def str_concat (a : String) (b : String) : String
```

## def str_cat3

```
def str_cat3 (a : String) (b : String) (c : String) : String
```

## def str_cat4

```
def str_cat4 (a : String) (b : String) (c : String) (d : String) : String
```

## def str_slice

```
def str_slice (s : String) (i : Nat) (n : Nat) : String
```

## def str_codes

```
def str_codes (s : String) : List Nat
```

## def str_of_codes

```
def str_of_codes (cs : List Nat) : String
```

## def str_of_nat

```
def str_of_nat (n : Nat) : String
```

## def str_empty

```
def str_empty : String
```

## def str_null

```
def str_null (s : String) : Bool
```

## def str_head

```
def str_head (s : String) : Nat
```

## def str_tail

```
def str_tail (s : String) : String
```

## def str_cons

```
def str_cons (c : Nat) (s : String) : String
```

## def str_snoc

```
def str_snoc (s : String) (c : Nat) : String
```

## def str_rev

```
def str_rev (s : String) : String
```

## def str_starts

```
def str_starts (s : String) (pre : String) : Bool
```

## def str_ends

```
def str_ends (s : String) (suf : String) : Bool
```

## def str_contains

```
def str_contains (s : String) (pat : String) : Bool
```

## def str_index

```
def str_index (s : String) (pat : String) : Maybe Nat
```

## def str_count

```
def str_count (s : String) (pat : String) : Nat
```

## def str_map

```
def str_map (f : Nat -> Nat) (s : String) : String
```

## def str_filter

```
def str_filter (p : Nat -> Bool) (s : String) : String
```

## def str_lower

```
def str_lower (s : String) : String
```

## def str_upper

```
def str_upper (s : String) : String
```

## def is_ws_or

```
def is_ws_or (c : Nat) : Bool
```

## def str_ltrim

```
def str_ltrim (s : String) : String
```

## def str_rtrim

```
def str_rtrim (s : String) : String
```

## def str_trim

```
def str_trim (s : String) : String
```

## def str_pad_left

```
def str_pad_left (s : String) (w : Nat) (c : Nat) : String
```

## def str_pad_right

```
def str_pad_right (s : String) (w : Nat) (c : Nat) : String
```

## def split_on

```
def split_on (sep : Nat) : List Nat -> List (List Nat)
```

## def str_split

```
def str_split (s : String) (sep : Nat) : List String
```

## def str_lines

```
def str_lines (s : String) : List String
```

## def str_words

```
def str_words (s : String) : List String
```

## def str_join

```
def str_join (sep : String) : List String -> String
```

## def str_replace

```
def str_replace (s : String) (pat : String) (rep : String) : String
```
