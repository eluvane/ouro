# std/validation.ouro

Accumulating validation helpers over Either (List E) A.

Declarations: 20.

## def Validation

```ouro
def Validation (E : Type) (A : Type) : Type
```

## def valid

```ouro
def valid (E : Type) (A : Type) (x : A) : Validation E A
```

## def invalid_many

```ouro
def invalid_many (E : Type) (A : Type) (errors : List E) : Validation E A
```

## def invalid

```ouro
def invalid (E : Type) (A : Type) (error : E) : Validation E A
```

## def validation_is_valid

```ouro
def validation_is_valid (E : Type) (A : Type) (v : Validation E A) : Bool
```

## def validation_errors

```ouro
def validation_errors (E : Type) (A : Type) (v : Validation E A) : List E
```

## def validation_map

```ouro
def validation_map (E : Type) (A : Type) (B : Type) (f : A -> B) (v : Validation E A) : Validation E B
```

## def validation_map_error

```ouro
def validation_map_error (E : Type) (F : Type) (A : Type) (f : E -> F) (v : Validation E A) : Validation F A
```

## def validation_apply

```ouro
def validation_apply (E : Type) (A : Type) (B : Type) (vf : Validation E (A -> B)) (vx : Validation E A) : Validation E B
```

## def validation_map2

```ouro
def validation_map2 (E : Type) (A : Type) (B : Type) (C : Type) (f : A -> B -> C) (va : Validation E A) (vb : Validation E B) : Validation E C
```

## def validation_and

```ouro
def validation_and (E : Type) (left : Validation E Unit) (right : Validation E Unit) : Validation E Unit
```

## def validation_collect

```ouro
def validation_collect (E : Type) (A : Type) : List (Validation E A) -> Validation E (List A)
```

## def validation_collect_unit

```ouro
def validation_collect_unit (E : Type) (xs : List (Validation E Unit)) : Validation E Unit
```

## def validation_require

```ouro
def validation_require (E : Type) (error : E) (condition : Bool) : Validation E Unit
```

## def validation_require_present

```ouro
def validation_require_present (E : Type) (A : Type) (error : E) (m : Maybe A) : Validation E A
```

## def validation_require_nonempty

```ouro
def validation_require_nonempty (error : String) (value : String) : Validation String String
```

## def validation_from_result

```ouro
def validation_from_result (E : Type) (A : Type) (r : Either E A) : Validation E A
```

## def validation_to_result

```ouro
def validation_to_result (E : Type) (A : Type) (v : Validation E A) : Either (List E) A
```

## def validation_render_errors

```ouro
def validation_render_errors (E : Type) (show : E -> String) (errors : List E) : String
```

## def validation_render

```ouro
def validation_render (E : Type) (A : Type) (show : E -> String) (ok : A -> String) (v : Validation E A) : String
```
