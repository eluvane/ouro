# std/format.ouro

Formatting helpers avoid giant Nat literals so extraction stays within small fuel bounds.

Declarations: 22.

## def show_nat

```
def show_nat (n : Nat) : String
```

## def show_bool

```
def show_bool (b : Bool) : String
```

## def show_maybe

```
def show_maybe (A : Type) (sh : A -> String) (m : Maybe A) : String
```

## def show_list

```
def show_list (A : Type) (sh : A -> String) (xs : List A) : String
```

## def show_pair

```
def show_pair (A : Type) (B : Type) (sa : A -> String) (sb : B -> String) (p : Pair A B) : String
```

## def pad_nat

```
def pad_nat (n : Nat) (w : Nat) : String
```

## def show_nat_base

```
def show_nat_base (n : Nat) (base : Nat) : String
```

## def show_hex

```
def show_hex (n : Nat) : String
```

## def show_bin

```
def show_bin (n : Nat) : String
```

## def show_oct

```
def show_oct (n : Nat) : String
```

## def indent

```
def indent (n : Nat) (s : String) : String
```

## def unlines

```
def unlines (xs : List String) : String
```

## def lines_of

```
def lines_of (s : String) : List String
```

## def quote_str

```
def quote_str (s : String) : String
```

## def kv_line

```
def kv_line (k : String) (v : String) : String
```

## def show_assoc

```
def show_assoc (xs : List (Pair String String)) : String
```

## def parse_kv_line

```
def parse_kv_line (s : String) : Maybe (Pair String String)
```

## def parse_kv_table

```
def parse_kv_table (s : String) : List (Pair String String)
```

## def lookup_table

```
def lookup_table (table : String) (key : String) : Maybe String
```

## def count_lines

```
def count_lines (s : String) : Nat
```

## def ends_nl

```
def ends_nl (s : String) : Bool
```

## def ensure_nl

```
def ensure_nl (s : String) : String
```
