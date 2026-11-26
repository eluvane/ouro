# std/mutual_demo.ouro

Mutually dependent even/odd evidence encoded as one indexed family.

Declarations: 7.

## inductive Parity

```ouro
inductive Parity : Type
```

## inductive ParityEvidence

```ouro
inductive ParityEvidence : Parity -> Type
```

## def Even

```ouro
def Even : Type
```

## def Odd

```ouro
def Odd : Type
```

## def even0

```ouro
def even0 : Even
```

## def odd1

```ouro
def odd1 : Odd
```

## def even2

```ouro
def even2 : Even
```
