# std/listx.ouro

Extra list algorithms stay outside prelude to keep bootstrap cones small.

Declarations: 34.

## def concat_map

```
def concat_map (A : Type) (B : Type) (f : A -> List B) : List A -> List B
```

## def flatten

```
def flatten (A : Type) : List (List A) -> List A
```

## def nth

```
def nth (A : Type) (d : A) : Nat -> List A -> A
```

## def foldl

```
def foldl (A : Type) (B : Type) (f : B -> A -> B)
```

Left fold. prelude has foldr only, and a scanner that carries state through a list of lines wants the accumulator threaded front to back.

## def rev_append

```
def rev_append (A : Type) : List A -> List A -> List A
```

## def reverse_lin

```
def reverse_lin (A : Type) (xs : List A) : List A
```

## def last

```
def last (A : Type) (d : A) : List A -> A
```

## def init

```
def init (A : Type) : List A -> List A
```

## def any

```
def any (A : Type) (p : A -> Bool) : List A -> Bool
```

## def all

```
def all (A : Type) (p : A -> Bool) : List A -> Bool
```

## def find

```
def find (A : Type) (p : A -> Bool) : List A -> Maybe A
```

## def lookup

```
def lookup (A : Type) (B : Type) (eq : A -> A -> Bool) (k : A) : List (Pair A B) -> Maybe B
```

## def span

```
def span (A : Type) (p : A -> Bool) : List A -> Pair (List A) (List A)
```

## def take_while

```
def take_while (A : Type) (p : A -> Bool) (xs : List A) : List A
```

## def drop_while

```
def drop_while (A : Type) (p : A -> Bool) (xs : List A) : List A
```

## def intersperse

```
def intersperse (A : Type) (sep : A) : List A -> List A
```

## def replicate

```
def replicate (A : Type) (x : A) : Nat -> List A
```

## def count_if

```
def count_if (A : Type) (p : A -> Bool) : List A -> Nat
```

## def nub

```
def nub (A : Type) (eq : A -> A -> Bool) (xs : List A) : List A
```

## def insert_sorted

```
def insert_sorted (A : Type) (le : A -> A -> Bool) (x : A) : List A -> List A
```

## def sort_insert

```
def sort_insert (A : Type) (le : A -> A -> Bool) : List A -> List A
```

## def is_prefix

```
def is_prefix (A : Type) (eq : A -> A -> Bool) : List A -> List A -> Bool
```

## def index_of

```
def index_of (A : Type) (eq : A -> A -> Bool) (x : A)
```

## def zip_with

```
def zip_with (A : Type) (B : Type) (C : Type) (f : A -> B -> C) : List A -> List B -> List C
```

## def sum_nats

```
def sum_nats : List Nat -> Nat
```

## def product_nats

```
def product_nats : List Nat -> Nat
```

## def maximum_nat

```
def maximum_nat (d : Nat) : List Nat -> Nat
```

## def minimum_nat

```
def minimum_nat (d : Nat) : List Nat -> Nat
```

## def mem

```
def mem (A : Type) (eq : A -> A -> Bool) (x : A) (xs : List A) : Bool
```

## def snoc

```
def snoc (A : Type) (xs : List A) (x : A) : List A
```

## def singleton

```
def singleton (A : Type) (x : A) : List A
```

## def nullb

```
def nullb (A : Type) (xs : List A) : Bool
```

## def head

```
def head (A : Type) (d : A) (xs : List A) : A
```

## def tail

```
def tail (A : Type) (xs : List A) : List A
```
