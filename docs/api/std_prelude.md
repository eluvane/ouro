# std/prelude.ouro

Prelude stays tiny so every tool cone can import it without widening the TCB surface.

Declarations: 12.

## def add

```
def add : Nat -> Nat -> Nat
```

## def mul

```
def mul : Nat -> Nat -> Nat
```

## def map

```
def map (A : Type) (B : Type) (f : A -> B) : List A -> List B
```

## def append

```
def append (A : Type) : List A -> List A -> List A
```

## def length

```
def length (A : Type) : List A -> Nat
```

## def foldr

```
def foldr (A : Type) (B : Type) (f : A -> B -> B) (z : B) : List A -> B
```

## def fst

```
def fst (A : Type) (B : Type) (p : Pair A B) : A
```

## def snd

```
def snd (A : Type) (B : Type) (p : Pair A B) : B
```

## def sub

```
def sub : Nat -> Nat -> Nat
```

## def andb

```
def andb (x : Bool) (y : Bool) : Bool
```

## def orb

```
def orb (x : Bool) (y : Bool) : Bool
```

## def notb

```
def notb (x : Bool) : Bool
```
