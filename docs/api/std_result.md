# std/result.ouro

Result-style helpers over Either; Right is success and Left is the typed error.

Declarations: 18.

## def result_ok

```ouro
def result_ok (E : Type) (A : Type) (x : A) : Either E A
```

## def result_err

```ouro
def result_err (E : Type) (A : Type) (e : E) : Either E A
```

## def result_fold

```ouro
def result_fold (E : Type) (A : Type) (B : Type) (on_err : E -> B)
    (on_ok : A -> B) (r : Either E A) : B
```

## def result_is_ok

```ouro
def result_is_ok (E : Type) (A : Type) (r : Either E A) : Bool
```

## def result_is_err

```ouro
def result_is_err (E : Type) (A : Type) (r : Either E A) : Bool
```

## def result_map

```ouro
def result_map (E : Type) (A : Type) (B : Type) (f : A -> B)
    (r : Either E A) : Either E B
```

## def result_map_err

```ouro
def result_map_err (E : Type) (F : Type) (A : Type) (f : E -> F)
    (r : Either E A) : Either F A
```

## def result_bind

```ouro
def result_bind (E : Type) (A : Type) (B : Type) (r : Either E A)
    (k : A -> Either E B) : Either E B
```

## def result_and_then

```ouro
def result_and_then (E : Type) (A : Type) (B : Type)
    (k : A -> Either E B) (r : Either E A) : Either E B
```

## def result_or

```ouro
def result_or (E : Type) (A : Type) (fallback : A) (r : Either E A) : A
```

## def result_or_else

```ouro
def result_or_else (E : Type) (A : Type) (r : Either E A)
    (fallback : E -> Either E A) : Either E A
```

## def result_unwrap_or

```ouro
def result_unwrap_or (E : Type) (A : Type) (fallback : A)
    (r : Either E A) : A
```

## def result_to_maybe

```ouro
def result_to_maybe (E : Type) (A : Type) (r : Either E A) : Maybe A
```

## def result_from_maybe

```ouro
def result_from_maybe (E : Type) (A : Type) (e : E) (m : Maybe A)
    : Either E A
```

## def result_map2

```ouro
def result_map2 (E : Type) (A : Type) (B : Type) (C : Type)
    (f : A -> B -> C) (ra : Either E A) (rb : Either E B) : Either E C
```

## def result_require

```ouro
def result_require (E : Type) (e : E) (b : Bool) : Either E Unit
```

## def result_to_unit

```ouro
def result_to_unit (E : Type) (A : Type) (r : Either E A) : Either E Unit
```

## def result_unwrap_or_else

```ouro
def result_unwrap_or_else (E : Type) (A : Type) (fallback : E -> A) (r : Either E A) : A
```
