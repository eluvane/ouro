# std/eq.ouro

Identity elimination is kernel-sensitive; dependent matches must specialize the motive before returning.

Declarations: 13.

## inductive Nat

```
inductive Nat : Type
```

## inductive Eq

```
inductive Eq (A : Type) (x : A) : A -> Type
```

## def cast

```
def cast (A : Type) (x : A) (y : A) (e : Eq A x y) : A
```

## def refl_of

```
def refl_of (A : Type) (x : A) : Eq A x x
```

## def sym

```
def sym (A : Type) (x : A) (y : A) (e : Eq A x y) : Eq A y x
```

## def trans

```
def trans (A : Type) (x : A) (y : A) (e : Eq A x y) : (z : A) -> Eq A y z -> Eq A x z
```

Match returns the residual function so the second equality is specialized.

## def cong

```
def cong (A : Type) (B : Type) (f : A -> B) (x : A) (y : A) (e : Eq A x y) : Eq B (f x) (f y)
```

## def transport

```
def transport (A : Type) (P : A -> Type) (x : A) (y : A) (e : Eq A x y) : P x -> P y
```

Based path induction / transport (match returns P-specialized function).

## def J

```
def J (A : Type) (x : A) (P : (_y : A) -> Type) (px : P x) (y : A) (e : Eq A x y) : P y
```

## def sym_zz

```
def sym_zz : Eq Nat Z Z
```

## def cong_s

```
def cong_s : Eq Nat (S Z) (S Z)
```

## def trans_zz

```
def trans_zz : Eq Nat Z Z
```

## def J_id

```
def J_id : Nat
```
