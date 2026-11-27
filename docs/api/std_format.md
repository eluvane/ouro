# std/format.ouro

Formatting helpers avoid giant Nat literals so extraction stays within small fuel bounds.

Declarations: 22.

## def show_nat

```ouro
def show_nat (n : Nat) : String
```

## def show_bool

```ouro
def show_bool (b : Bool) : String
```

## def show_maybe

```ouro
def show_maybe (A : Type) (sh : A -> String) (m : Maybe A) : String
```

## def show_list

```ouro
def show_list (A : Type) (sh : A -> String) (xs : List A) : String
```

## def show_pair

```ouro
def show_pair (A : Type) (B : Type) (sa : A -> String) (sb : B -> String) (p : Pair A B) : String
```

## def pad_nat

```ouro
def pad_nat (n : Nat) (w : Nat) : String
```

## def show_nat_base

```ouro
def show_nat_base (n : Nat) (base : Nat) : String
```

## def show_hex

```ouro
def show_hex (n : Nat) : String
```

## def show_bin

```ouro
def show_bin (n : Nat) : String
```

## def show_oct

```ouro
def show_oct (n : Nat) : String
```

## def indent

```ouro
def indent (n : Nat) (s : String) : String
```

## def unlines

```ouro
def unlines (xs : List String) : String
```

## def lines_of

```ouro
def lines_of (s : String) : List String
```

## def quote_str

```ouro
def quote_str (s : String) : String
```

## def kv_line

```ouro
def kv_line (k : String) (v : String) : String
```

## def show_assoc

```ouro
def show_assoc (xs : List (Pair String String)) : String
```

## def parse_kv_line

```ouro
def parse_kv_line (s : String) : Maybe (Pair String String)
```

## def parse_kv_table

```ouro
def parse_kv_table (s : String) : List (Pair String String)
```

## def lookup_table

```ouro
def lookup_table (table : String) (key : String) : Maybe String
```

## def count_lines

```ouro
def count_lines (s : String) : Nat
```

## def ends_nl

```ouro
def ends_nl (s : String) : Bool
```

## def ensure_nl

```ouro
def ensure_nl (s : String) : String
```
