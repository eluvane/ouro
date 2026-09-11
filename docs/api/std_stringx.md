# std/stringx.ouro

Tool-facing string helpers keep ordering and splitting deterministic across hosts.

Declarations: 20.

## def str_take

```
def str_take (s : String) (n : Nat) : String
```

## def str_drop

```
def str_drop (s : String) (n : Nat) : String
```

## def str_repeat

```
def str_repeat (s : String) : Nat -> String
```

## def codes_le

```
def codes_le : List Nat -> List Nat -> Bool
```

Byte-lexicographic order: shorter is smaller on a shared prefix.

## def str_le

```
def str_le (a : String) (b : String) : Bool
```

## def str_lt

```
def str_lt (a : String) (b : String) : Bool
```

## def str_index_from

```
def str_index_from (s : String) (pat : String) (i : Nat) : Maybe Nat
```

Index of the first pat occurrence at or after i.

## def str_split_first

```
def str_split_first (s : String) (sep : String) : Maybe (Pair String String)
```

Split at the first separator only: "a=b=c" on "=" gives ("a", "b=c").

## def str_before

```
def str_before (s : String) (pat : String) : String
```

## def str_after

```
def str_after (s : String) (pat : String) : String
```

## def str_split_str_go

```
def str_split_str_go : Nat -> String -> String -> List String
```

Split on a multi-character separator. An empty separator yields the whole string, matching str_replace's treatment of an empty pattern.

## def str_split_str

```
def str_split_str (s : String) (sep : String) : List String
```

## def str_strip_prefix

```
def str_strip_prefix (s : String) (pre : String) : Maybe String
```

## def str_strip_suffix

```
def str_strip_suffix (s : String) (suf : String) : Maybe String
```

## def str_unlines

```
def str_unlines (ls : List String) : String
```

## def str_unwords

```
def str_unwords (ws : List String) : String
```

## def str_indent

```
def str_indent (n : Nat) (s : String) : String
```

## def str_indent_lines

```
def str_indent_lines (n : Nat) (s : String) : String
```

## def str_sort

```
def str_sort (xs : List String) : List String
```

Sorted, duplicate-free string list; used wherever tool output has to be reproducible.

## def str_sort_uniq

```
def str_sort_uniq (xs : List String) : List String
```
