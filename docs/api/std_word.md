# std/word.ouro

Word32 bit ops. Standalone emit binds the same names through ouro_fast. Bodies below are total Peano fallbacks for check; they are not the execution path for SHA-256. Not a kernel change.

Declarations: 15.

## def n32

```
def n32 : Nat
```

## def xor32

```
def xor32 : Nat -> Nat -> Nat
```

## def and32

```
def and32 : Nat -> Nat -> Nat
```

## def or32

```
def or32 : Nat -> Nat -> Nat
```

## def add32

```
def add32 : Nat -> Nat -> Nat
```

## def shl32

```
def shl32 : Nat -> Nat -> Nat
```

## def shr32

```
def shr32 : Nat -> Nat -> Nat
```

## def rotr32

```
def rotr32 : Nat -> Nat -> Nat
```

## def not32

```
def not32 (n : Nat) : Nat
```

## def w32_mask8

```
def w32_mask8 : Nat
```

## def w32_of_bytes

```
def w32_of_bytes (a : Nat) (b : Nat) (c : Nat) (d : Nat) : Nat
```

## def w32_b0

```
def w32_b0 (w : Nat) : Nat
```

## def w32_b1

```
def w32_b1 (w : Nat) : Nat
```

## def w32_b2

```
def w32_b2 (w : Nat) : Nat
```

## def w32_b3

```
def w32_b3 (w : Nat) : Nat
```
