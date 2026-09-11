# std/mutual_demo.ouro

Mutually dependent even/odd evidence encoded as one indexed family.

Declarations: 7.

## inductive Parity

```
inductive Parity : Type
```

## inductive ParityEvidence

```
inductive ParityEvidence : Parity -> Type
```

## def Even

```
def Even : Type
```

## def Odd

```
def Odd : Type
```

## def even0

```
def even0 : Even
```

## def odd1

```
def odd1 : Odd
```

## def even2

```
def even2 : Even
```
