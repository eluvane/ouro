# std/vec_demo.ouro

Declarations: 4.

## inductive Nat

```
inductive Nat : Type
```

## inductive Vec

```
inductive Vec (A : Type) : Nat -> Type
```

## def empty_nat_vec

```
def empty_nat_vec : Vec Nat Z
```

## def singleton

```
def singleton (x : Nat) : Vec Nat (S Z)
```
