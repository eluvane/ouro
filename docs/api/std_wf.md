# std/wf.ouro

Accessibility stays projection-only until the termination checker accepts nested Acc recursion.

Declarations: 7.

## inductive Unit

```
inductive Unit : Type
```

## inductive Nat

```
inductive Nat : Type
```

## inductive Acc

```
inductive Acc (A : Type) (R : A -> A -> Type) : A -> Type
```

## def acc_point

```
def acc_point (A : Type) (R : A -> A -> Type) (x : A) (a : Acc A R x) : A
```

## def acc_step

```
def acc_step (A : Type) (R : A -> A -> Type) (x : A) (a : Acc A R x) : ((y : A) -> R y x -> Acc A R y)
```

## def acc_map

```
def acc_map (A : Type) (R : A -> A -> Type) (B : Type) (f : A -> B) (x : A) (a : Acc A R x) : B
```

## def acc_elim_const

```
def acc_elim_const (A : Type) (R : A -> A -> Type) (P : A -> Type) (step : (x : A) -> ((y : A) -> R y x -> Acc A R y) -> P x) (x : A) (a : Acc A R x) : P x
```

Non-recursive dependent elimination into P : A -> Type.
