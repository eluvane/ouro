# std/listx.ouro

Extra list algorithms stay outside prelude to keep bootstrap cones small.

Declarations: 34.

## def concat_map

```ouro
def concat_map (A : Type) (B : Type) (f : A -> List B) : List A -> List B
```

## def flatten

```ouro
def flatten (A : Type) : List (List A) -> List A
```

## def nth

```ouro
def nth (A : Type) (d : A) : Nat -> List A -> A
```

## def foldl

```ouro
def foldl (A : Type) (B : Type) (f : B -> A -> B)
    (acc : B) (xs : List A) : B
```

Left fold. prelude has foldr only, and a scanner that carries state through a list of lines wants the accumulator threaded front to back.

## def rev_append

```ouro
def rev_append (A : Type) : List A -> List A -> List A
```

## def reverse_lin

```ouro
def reverse_lin (A : Type) (xs : List A) : List A
```

## def last

```ouro
def last (A : Type) (d : A) : List A -> A
```

## def init

```ouro
def init (A : Type) : List A -> List A
```

## def any

```ouro
def any (A : Type) (p : A -> Bool) : List A -> Bool
```

## def all

```ouro
def all (A : Type) (p : A -> Bool) : List A -> Bool
```

## def find

```ouro
def find (A : Type) (p : A -> Bool) : List A -> Maybe A
```

## def lookup

```ouro
def lookup (A : Type) (B : Type) (eq : A -> A -> Bool) (k : A) : List (Pair A B) -> Maybe B
```

## def span

```ouro
def span (A : Type) (p : A -> Bool) : List A -> Pair (List A) (List A)
```

## def take_while

```ouro
def take_while (A : Type) (p : A -> Bool) (xs : List A) : List A
```

## def drop_while

```ouro
def drop_while (A : Type) (p : A -> Bool) (xs : List A) : List A
```

## def intersperse

```ouro
def intersperse (A : Type) (sep : A) : List A -> List A
```

## def replicate

```ouro
def replicate (A : Type) (x : A) : Nat -> List A
```

## def count_if

```ouro
def count_if (A : Type) (p : A -> Bool) : List A -> Nat
```

## def nub

```ouro
def nub (A : Type) (eq : A -> A -> Bool) (xs : List A) : List A
```

## def insert_sorted

```ouro
def insert_sorted (A : Type) (le : A -> A -> Bool) (x : A) : List A -> List A
```

## def sort_insert

```ouro
def sort_insert (A : Type) (le : A -> A -> Bool) : List A -> List A
```

## def is_prefix

```ouro
def is_prefix (A : Type) (eq : A -> A -> Bool) : List A -> List A -> Bool
```

## def index_of

```ouro
def index_of (A : Type) (eq : A -> A -> Bool) (x : A)
    (xs : List A) : Maybe Nat
```

## def zip_with

```ouro
def zip_with (A : Type) (B : Type) (C : Type) (f : A -> B -> C) : List A -> List B -> List C
```

## def sum_nats

```ouro
def sum_nats : List Nat -> Nat
```

## def product_nats

```ouro
def product_nats : List Nat -> Nat
```

## def maximum_nat

```ouro
def maximum_nat (d : Nat) : List Nat -> Nat
```

## def minimum_nat

```ouro
def minimum_nat (d : Nat) : List Nat -> Nat
```

## def mem

```ouro
def mem (A : Type) (eq : A -> A -> Bool) (x : A) (xs : List A) : Bool
```

## def snoc

```ouro
def snoc (A : Type) (xs : List A) (x : A) : List A
```

## def singleton

```ouro
def singleton (A : Type) (x : A) : List A
```

## def nullb

```ouro
def nullb (A : Type) (xs : List A) : Bool
```

## def head

```ouro
def head (A : Type) (d : A) (xs : List A) : A
```

## def tail

```ouro
def tail (A : Type) (xs : List A) : List A
```
