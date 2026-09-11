# std/assoc.ouro

Association lists preserve insertion order; callers supply equality.

Declarations: 22.

## def assoc_empty

```
def assoc_empty (A : Type) (B : Type) : List (Pair A B)
```

## def assoc_insert

```
def assoc_insert (A : Type) (B : Type) (eq : A -> A -> Bool) (k : A) (v : B) : List (Pair A B) -> List (Pair A B)
```

## def assoc_delete

```
def assoc_delete (A : Type) (B : Type) (eq : A -> A -> Bool) (k : A) : List (Pair A B) -> List (Pair A B)
```

## def assoc_get

```
def assoc_get (A : Type) (B : Type) (eq : A -> A -> Bool) (k : A) (xs : List (Pair A B)) : Maybe B
```

## def assoc_mem

```
def assoc_mem (A : Type) (B : Type) (eq : A -> A -> Bool) (k : A) (xs : List (Pair A B)) : Bool
```

## def assoc_keys

```
def assoc_keys (A : Type) (B : Type) (xs : List (Pair A B)) : List A
```

## def assoc_values

```
def assoc_values (A : Type) (B : Type) (xs : List (Pair A B)) : List B
```

## def assoc_size

```
def assoc_size (A : Type) (B : Type) (xs : List (Pair A B)) : Nat
```

## def assoc_union

```
def assoc_union (A : Type) (B : Type) (eq : A -> A -> Bool) (xs : List (Pair A B)) (ys : List (Pair A B)) : List (Pair A B)
```

## def assoc_from_lists

```
def assoc_from_lists (A : Type) (B : Type) (eq : A -> A -> Bool) (ks : List A) (vs : List B) : List (Pair A B)
```

## def set_empty

```
def set_empty (A : Type) : List A
```

## def set_insert

```
def set_insert (A : Type) (eq : A -> A -> Bool) (x : A) : List A -> List A
```

## def set_mem

```
def set_mem (A : Type) (eq : A -> A -> Bool) (x : A) (xs : List A) : Bool
```

## def set_delete

```
def set_delete (A : Type) (eq : A -> A -> Bool) (x : A) : List A -> List A
```

## def set_union

```
def set_union (A : Type) (eq : A -> A -> Bool) (xs : List A) (ys : List A) : List A
```

## def set_intersect

```
def set_intersect (A : Type) (eq : A -> A -> Bool) (xs : List A) (ys : List A) : List A
```

## def set_diff

```
def set_diff (A : Type) (eq : A -> A -> Bool) (xs : List A) (ys : List A) : List A
```

## def set_from_list

```
def set_from_list (A : Type) (eq : A -> A -> Bool) (xs : List A) : List A
```

## def str_assoc_get

```
def str_assoc_get (k : String) (xs : List (Pair String String)) : Maybe String
```

## def str_assoc_insert

```
def str_assoc_insert (k : String) (v : String) (xs : List (Pair String String)) : List (Pair String String)
```

## def str_set_insert

```
def str_set_insert (x : String) (xs : List String) : List String
```

## def str_set_mem

```
def str_set_mem (x : String) (xs : List String) : Bool
```
