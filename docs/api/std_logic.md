# std/logic.ouro

Empty has no constructors; branchless matches are the kernel coverage case for contradiction.

Declarations: 15.

## inductive Empty

```ouro
inductive Empty : Type
```

## def Not

```ouro
def Not (A : Type) : Type
```

## def ex_falso

```ouro
def ex_falso (A : Type) (e : Empty) : A
```

Branchless match on Empty (no ctors).

## inductive And

```ouro
inductive And (A : Type) (B : Type) : Type
```

## def and_comm

```ouro
def and_comm (A : Type) (B : Type) (h : And A B) : And B A
```

## def and_assoc

```ouro
def and_assoc (A : Type) (B : Type) (C : Type) (h : And A (And B C)) : And (And A B) C
```

## inductive Or

```ouro
inductive Or (A : Type) (B : Type) : Type
```

## def or_comm

```ouro
def or_comm (A : Type) (B : Type) (h : Or A B) : Or B A
```

## def or_assoc

```ouro
def or_assoc (A : Type) (B : Type) (C : Type) (h : Or A (Or B C)) : Or (Or A B) C
```

## def modus_ponens

```ouro
def modus_ponens (A : Type) (B : Type) (a : A) (f : A -> B) : B
```

## def curry

```ouro
def curry (A : Type) (B : Type) (C : Type) (f : And A B -> C) (a : A) (b : B) : C
```

## def uncurry

```ouro
def uncurry (A : Type) (B : Type) (C : Type) (f : A -> B -> C) (h : And A B) : C
```

## def compose

```ouro
def compose (A : Type) (B : Type) (C : Type) (after : B -> C) (before : A -> B) : A -> C
```

## def flip

```ouro
def flip (A : Type) (B : Type) (C : Type) (f : A -> B -> C) (right : B) (left : A) : C
```

## inductive Exists

```ouro
inductive Exists (A : Type) (P : A -> Type) : Type
```

Dependent Sigma: parameter types may mention earlier params.
