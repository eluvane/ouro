# std/collections.ouro

Practical collection helpers layered over the small prelude/listx core.

Declarations: 19.

## def nth_maybe

```
def nth_maybe (A : Type) : Nat -> List A -> Maybe A
```

## def list_get_or

```
def list_get_or (A : Type) (fallback : A) (i : Nat) (xs : List A) : A
```

## def filter_map

```
def filter_map (A : Type) (B : Type) (f : A -> Maybe B) : List A -> List B
```

## def map_indexed

```
def map_indexed (A : Type) (B : Type) (f : Nat -> A -> B)
```

## def indexed

```
def indexed (A : Type) (xs : List A) : List (Pair Nat A)
```

## def find_index

```
def find_index (A : Type) (p : A -> Bool) (xs : List A) : Maybe Nat
```

## def split_at

```
def split_at (A : Type) (n : Nat) (xs : List A) : Pair (List A) (List A)
```

## def chunks_of

```
def chunks_of (A : Type) (n : Nat) (xs : List A) : List (List A)
```

## def list_eq

```
def list_eq (A : Type) (eq : A -> A -> Bool) : List A -> List A -> Bool
```

## def list_count

```
def list_count (A : Type) (eq : A -> A -> Bool) (x : A) (xs : List A) : Nat
```

## def list_remove

```
def list_remove (A : Type) (eq : A -> A -> Bool) (x : A) : List A -> List A
```

## def list_take_last

```
def list_take_last (A : Type) (n : Nat) (xs : List A) : List A
```

## def list_drop_last

```
def list_drop_last (A : Type) (n : Nat) (xs : List A) : List A
```

## def adjacent_pairs

```
def adjacent_pairs (A : Type) : List A -> List (Pair A A)
```

## def dedup_adjacent

```
def dedup_adjacent (A : Type) (eq : A -> A -> Bool) : List A -> List A
```

## def partition_map

```
def partition_map (A : Type) (L : Type) (R : Type) (f : A -> Either L R)
```

## def list_collect_results

```
def list_collect_results (E : Type) (A : Type)
```

## def list_traverse_result

```
def list_traverse_result (E : Type) (A : Type) (B : Type)
```

## def list_traverse_maybe

```
def list_traverse_maybe (A : Type) (B : Type) (f : A -> Maybe B) : List A -> Maybe (List B)
```
