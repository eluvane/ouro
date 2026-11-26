# std/string.ouro

String operations delegate byte semantics to trusted runtime primitives.

Declarations: 36.

## def str_len

```ouro
def str_len (s : String) : Nat
```

## def str_eq

```ouro
def str_eq (a : String) (b : String) : Bool
```

## def str_concat

```ouro
def str_concat (a : String) (b : String) : String
```

## def str_cat3

```ouro
def str_cat3 (a : String) (b : String) (c : String) : String
```

## def str_cat4

```ouro
def str_cat4 (a : String) (b : String) (c : String) (d : String) : String
```

## def str_slice

```ouro
def str_slice (s : String) (i : Nat) (n : Nat) : String
```

## def str_codes

```ouro
def str_codes (s : String) : List Nat
```

## def str_of_codes

```ouro
def str_of_codes (cs : List Nat) : String
```

## def str_of_nat

```ouro
def str_of_nat (n : Nat) : String
```

## def str_empty

```ouro
def str_empty : String
```

## def str_null

```ouro
def str_null (s : String) : Bool
```

## def str_head

```ouro
def str_head (s : String) : Nat
```

## def str_tail

```ouro
def str_tail (s : String) : String
```

## def str_cons

```ouro
def str_cons (c : Nat) (s : String) : String
```

## def str_snoc

```ouro
def str_snoc (s : String) (c : Nat) : String
```

## def str_rev

```ouro
def str_rev (s : String) : String
```

## def str_starts

```ouro
def str_starts (s : String) (pre : String) : Bool
```

## def str_ends

```ouro
def str_ends (s : String) (suf : String) : Bool
```

## def str_contains

```ouro
def str_contains (s : String) (pat : String) : Bool
```

## def str_index

```ouro
def str_index (s : String) (pat : String) : Maybe Nat
```

## def str_count

```ouro
def str_count (s : String) (pat : String) : Nat
```

## def str_map

```ouro
def str_map (f : Nat -> Nat) (s : String) : String
```

## def str_filter

```ouro
def str_filter (p : Nat -> Bool) (s : String) : String
```

## def str_lower

```ouro
def str_lower (s : String) : String
```

## def str_upper

```ouro
def str_upper (s : String) : String
```

## def str_ltrim

```ouro
def str_ltrim (s : String) : String
```

## def str_rtrim

```ouro
def str_rtrim (s : String) : String
```

## def str_trim

```ouro
def str_trim (s : String) : String
```

## def str_pad_left

```ouro
def str_pad_left (s : String) (w : Nat) (c : Nat) : String
```

## def str_pad_right

```ouro
def str_pad_right (s : String) (w : Nat) (c : Nat) : String
```

## def split_on

```ouro
def split_on (sep : Nat) : List Nat -> List (List Nat)
```

## def str_split

```ouro
def str_split (s : String) (sep : Nat) : List String
```

## def str_lines

```ouro
def str_lines (s : String) : List String
```

## def str_words

```ouro
def str_words (s : String) : List String
```

## def str_join

```ouro
def str_join (sep : String) : List String -> String
```

## def str_replace

```ouro
def str_replace (s : String) (pat : String) (rep : String) : String
```
