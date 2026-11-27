# std/prelude.ouro

The prelude imports only shared types to limit the checker dependency closure.

Declarations: 12.

## def add

```ouro
def add : Nat -> Nat -> Nat
```

## def mul

```ouro
def mul : Nat -> Nat -> Nat
```

## def map

```ouro
def map (A : Type) (B : Type) (f : A -> B) : List A -> List B
```

## def append

```ouro
def append (A : Type) : List A -> List A -> List A
```

## def length

```ouro
def length (A : Type) : List A -> Nat
```

## def foldr

```ouro
def foldr (A : Type) (B : Type) (f : A -> B -> B) (z : B) : List A -> B
```

## def fst

```ouro
def fst (A : Type) (B : Type) (p : Pair A B) : A
```

## def snd

```ouro
def snd (A : Type) (B : Type) (p : Pair A B) : B
```

## def sub

```ouro
def sub : Nat -> Nat -> Nat
```

## def andb

```ouro
def andb (x : Bool) (y : Bool) : Bool
```

## def orb

```ouro
def orb (x : Bool) (y : Bool) : Bool
```

## def notb

```ouro
def notb (x : Bool) : Bool
```
