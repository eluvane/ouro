# std/data.ouro

Small shared data types and list helpers that the compiler cones are allowed to import.

Declarations: 15.

## def maybe

```
def maybe (A : Type) (B : Type) (d : B) (f : A -> B) (m : Maybe A) : B
```

Fold Maybe: default d on Nothing, f on Just.

## def fromMaybe

```
def fromMaybe (A : Type) (d : A) (m : Maybe A) : A
```

## def mapMaybe

```
def mapMaybe (A : Type) (B : Type) (f : A -> B) (m : Maybe A) : Maybe B
```

## def either

```
def either (A : Type) (B : Type) (C : Type) (f : A -> C) (g : B -> C) (e : Either A B) : C
```

## def mapLeft

```
def mapLeft (A : Type) (B : Type) (C : Type) (f : A -> C) (e : Either A B) : Either C B
```

## def mapRight

```
def mapRight (A : Type) (B : Type) (C : Type) (f : B -> C) (e : Either A B) : Either A C
```

## def compareNat

```
def compareNat : Nat -> Nat -> Ordering
```

## def maxNat

```
def maxNat (n : Nat) (m : Nat) : Nat
```

## def minNat

```
def minNat (n : Nat) (m : Nat) : Nat
```

## def reverse

```
def reverse (A : Type) : List A -> List A
```

## def filter

```
def filter (A : Type) (p : A -> Bool) : List A -> List A
```

## def zip

```
def zip (A : Type) (B : Type) : List A -> List B -> List (Pair A B)
```

## def elem

```
def elem (A : Type) (eq : A -> A -> Bool) (x : A) : List A -> Bool
```

## def take

```
def take (A : Type) : Nat -> List A -> List A
```

## def drop

```
def drop (A : Type) : Nat -> List A -> List A
```
