# std/vec_demo.ouro

Declarations: 4.

## inductive Nat

```ouro
inductive Nat : Type
```

## inductive Vec

```ouro
inductive Vec (A : Type) : Nat -> Type
```

## def empty_nat_vec

```ouro
def empty_nat_vec : Vec Nat Z
```

## def singleton

```ouro
def singleton (x : Nat) : Vec Nat (S Z)
```
