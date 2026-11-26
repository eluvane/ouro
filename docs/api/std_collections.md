# std/collections.ouro

Practical collection helpers layered over the small prelude/listx core.

Declarations: 25.

## def nth_maybe

```ouro
def nth_maybe (A : Type) : Nat -> List A -> Maybe A
```

## def list_get_or

```ouro
def list_get_or (A : Type) (fallback : A) (i : Nat) (xs : List A) : A
```

## def filter_map

```ouro
def filter_map (A : Type) (B : Type) (f : A -> Maybe B) : List A -> List B
```

## def map_indexed

```ouro
def map_indexed (A : Type) (B : Type) (f : Nat -> A -> B)
    (xs : List A) : List B
```

## def indexed

```ouro
def indexed (A : Type) (xs : List A) : List (Pair Nat A)
```

## def find_index

```ouro
def find_index (A : Type) (p : A -> Bool) (xs : List A) : Maybe Nat
```

## def split_at

```ouro
def split_at (A : Type) (n : Nat) (xs : List A) : Pair (List A) (List A)
```

## def chunks_of

```ouro
def chunks_of (A : Type) (n : Nat) (xs : List A) : List (List A)
```

## def list_windows

```ouro
def list_windows (A : Type) (width : Nat) (xs : List A) : List (List A)
```

Complete overlapping windows; width zero has no windows.

## def list_scan

```ouro
def list_scan (A : Type) (S => State : Type) (step : State -> A -> State)
    (initial : State) (xs : List A) : List State
```

The initial state is the first result, even for an empty input.

## def list_map_accum

```ouro
def list_map_accum (A : Type) (S => State : Type) (B : Type)
    (step : State -> A -> Pair State B) (initial : State) (xs : List A)
    : Pair State (List B)
```

## def list_eq

```ouro
def list_eq (A : Type) (eq : A -> A -> Bool) : List A -> List A -> Bool
```

## def list_count

```ouro
def list_count (A : Type) (eq : A -> A -> Bool) (x : A) (xs : List A) : Nat
```

## def list_remove

```ouro
def list_remove (A : Type) (eq : A -> A -> Bool) (x : A) : List A -> List A
```

## def list_take_last

```ouro
def list_take_last (A : Type) (n : Nat) (xs : List A) : List A
```

## def list_drop_last

```ouro
def list_drop_last (A : Type) (n : Nat) (xs : List A) : List A
```

## def adjacent_pairs

```ouro
def adjacent_pairs (A : Type) : List A -> List (Pair A A)
```

## def dedup_adjacent

```ouro
def dedup_adjacent (A : Type) (eq : A -> A -> Bool) : List A -> List A
```

## def list_group_by

```ouro
def list_group_by (A : Type) (K : Type) (eq : K -> K -> Bool)
    (key : A -> K) (xs : List A) : List (Pair K (List A))
```

Keys and elements retain first-seen order; eq must identify equivalent keys.

## def partition_map

```ouro
def partition_map (A : Type) (L : Type) (R : Type) (f : A -> Either L R)
    : List A -> Pair (List L) (List R)
```

## def list_collect_results

```ouro
def list_collect_results (E : Type) (A : Type)
    : List (Either E A) -> Either E (List A)
```

## def list_traverse_result

```ouro
def list_traverse_result (E : Type) (A : Type) (B : Type)
    (f : A -> Either E B) (xs : List A) : Either E (List B)
```

## def list_try_fold_result

```ouro
def list_try_fold_result (E : Type) (A : Type) (S => State : Type)
    (step : State -> A -> Either E State) (initial : State) (xs : List A)
    : Either E State
```

## def list_try_fold_maybe

```ouro
def list_try_fold_maybe (A : Type) (S => State : Type)
    (step : State -> A -> Maybe State) (initial : State) (xs : List A) : Maybe State
```

## def list_traverse_maybe

```ouro
def list_traverse_maybe (A : Type) (B : Type) (f : A -> Maybe B) : List A -> Maybe (List B)
```
