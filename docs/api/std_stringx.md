# std/stringx.ouro

Tool-facing string helpers keep ordering and splitting deterministic across hosts.

Declarations: 20.

## def str_take

```ouro
def str_take (s : String) (n : Nat) : String
```

## def str_drop

```ouro
def str_drop (s : String) (n : Nat) : String
```

## def str_repeat

```ouro
def str_repeat (s : String) : Nat -> String
```

## def codes_le

```ouro
def codes_le : List Nat -> List Nat -> Bool
```

Byte-lexicographic order: shorter is smaller on a shared prefix.

## def str_le

```ouro
def str_le (a : String) (b : String) : Bool
```

## def str_lt

```ouro
def str_lt (a : String) (b : String) : Bool
```

## def str_index_from

```ouro
def str_index_from (s : String) (pat : String) (i : Nat) : Maybe Nat
```

Index of the first pat occurrence at or after i.

## def str_split_first

```ouro
def str_split_first (s : String) (sep : String) : Maybe (Pair String String)
```

Split at the first separator only: "a=b=c" on "=" gives ("a", "b=c").

## def str_before

```ouro
def str_before (s : String) (pat : String) : String
```

## def str_after

```ouro
def str_after (s : String) (pat : String) : String
```

## def str_split_str_go

```ouro
def str_split_str_go : Nat -> String -> String -> List String
```

Split at most `fuel` times. Return the rest as the last item.

## def str_split_str

```ouro
def str_split_str (s : String) (sep : String) : List String
```

Split on a byte sequence. An empty separator returns a list containing only the input string.

## def str_strip_prefix

```ouro
def str_strip_prefix (s : String) (pre : String) : Maybe String
```

## def str_strip_suffix

```ouro
def str_strip_suffix (s : String) (suf : String) : Maybe String
```

## def str_unlines

```ouro
def str_unlines (ls : List String) : String
```

## def str_unwords

```ouro
def str_unwords (ws : List String) : String
```

## def str_indent

```ouro
def str_indent (n : Nat) (s : String) : String
```

## def str_indent_lines

```ouro
def str_indent_lines (n : Nat) (s : String) : String
```

## def str_sort

```ouro
def str_sort (xs : List String) : List String
```

Sort strings by byte order, keeping duplicates.

## def str_sort_uniq

```ouro
def str_sort_uniq (xs : List String) : List String
```

Sort strings by byte order and remove duplicates.
