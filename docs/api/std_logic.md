# std/logic.ouro

Empty has no constructors; branchless matches are the kernel coverage case for contradiction.

Declarations: 13.

## inductive Empty

```
inductive Empty : Type
```

## def Not

```
def Not (A : Type) : Type
```

## def ex_falso

```
def ex_falso (A : Type) (e : Empty) : A
```

Branchless match on Empty (no ctors).

## inductive And

```
inductive And (A : Type) (B : Type) : Type
```

## def and_comm

```
def and_comm (A : Type) (B : Type) (h : And A B) : And B A
```

## def and_assoc

```
def and_assoc (A : Type) (B : Type) (C : Type) (h : And A (And B C)) : And (And A B) C
```

## inductive Or

```
inductive Or (A : Type) (B : Type) : Type
```

## def or_comm

```
def or_comm (A : Type) (B : Type) (h : Or A B) : Or B A
```

## def or_assoc

```
def or_assoc (A : Type) (B : Type) (C : Type) (h : Or A (Or B C)) : Or (Or A B) C
```

## def modus_ponens

```
def modus_ponens (A : Type) (B : Type) (a : A) (f : A -> B) : B
```

## def curry

```
def curry (A : Type) (B : Type) (C : Type) (f : And A B -> C) (a : A) (b : B) : C
```

## def uncurry

```
def uncurry (A : Type) (B : Type) (C : Type) (f : A -> B -> C) (h : And A B) : C
```

## inductive Exists

```
inductive Exists (A : Type) (P : A -> Type) : Type
```

Dependent Sigma: parameter types may mention earlier params.
