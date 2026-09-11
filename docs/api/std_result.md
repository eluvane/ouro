# std/result.ouro

Result-style helpers over Either; Right is success and Left is the typed error.

Declarations: 17.

## def result_ok

```
def result_ok (E : Type) (A : Type) (x : A) : Either E A
```

## def result_err

```
def result_err (E : Type) (A : Type) (e : E) : Either E A
```

## def result_fold

```
def result_fold (E : Type) (A : Type) (B : Type) (on_err : E -> B)
```

## def result_is_ok

```
def result_is_ok (E : Type) (A : Type) (r : Either E A) : Bool
```

## def result_is_err

```
def result_is_err (E : Type) (A : Type) (r : Either E A) : Bool
```

## def result_map

```
def result_map (E : Type) (A : Type) (B : Type) (f : A -> B)
```

## def result_map_err

```
def result_map_err (E : Type) (F : Type) (A : Type) (f : E -> F)
```

## def result_bind

```
def result_bind (E : Type) (A : Type) (B : Type) (r : Either E A)
```

## def result_and_then

```
def result_and_then (E : Type) (A : Type) (B : Type)
```

## def result_or

```
def result_or (E : Type) (A : Type) (fallback : A) (r : Either E A) : A
```

## def result_or_else

```
def result_or_else (E : Type) (A : Type) (r : Either E A)
```

## def result_unwrap_or

```
def result_unwrap_or (E : Type) (A : Type) (fallback : A)
```

## def result_to_maybe

```
def result_to_maybe (E : Type) (A : Type) (r : Either E A) : Maybe A
```

## def result_from_maybe

```
def result_from_maybe (E : Type) (A : Type) (e : E) (m : Maybe A)
```

## def result_map2

```
def result_map2 (E : Type) (A : Type) (B : Type) (C : Type)
```

## def result_require

```
def result_require (E : Type) (e : E) (b : Bool) : Either E Unit
```

## def result_to_unit

```
def result_to_unit (E : Type) (A : Type) (r : Either E A) : Either E Unit
```
