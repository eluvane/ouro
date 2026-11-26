# std/word.ouro

Word32 bit ops. Standalone emit binds the same names through ouro_fast. The bodies also run in tools emitted without these bindings.

Declarations: 15.

## def n32

```ouro
def n32 : Nat
```

## def xor32

```ouro
def xor32 : Nat -> Nat -> Nat
```

## def and32

```ouro
def and32 : Nat -> Nat -> Nat
```

## def or32

```ouro
def or32 : Nat -> Nat -> Nat
```

## def add32

```ouro
def add32 : Nat -> Nat -> Nat
```

## def shl32

```ouro
def shl32 : Nat -> Nat -> Nat
```

## def shr32

```ouro
def shr32 : Nat -> Nat -> Nat
```

## def rotr32

```ouro
def rotr32 : Nat -> Nat -> Nat
```

## def not32

```ouro
def not32 (n : Nat) : Nat
```

## def w32_mask8

```ouro
def w32_mask8 : Nat
```

## def w32_of_bytes

```ouro
def w32_of_bytes (a : Nat) (b : Nat) (c : Nat) (d : Nat) : Nat
```

## def w32_b0

```ouro
def w32_b0 (w : Nat) : Nat
```

## def w32_b1

```ouro
def w32_b1 (w : Nat) : Nat
```

## def w32_b2

```ouro
def w32_b2 (w : Nat) : Nat
```

## def w32_b3

```ouro
def w32_b3 (w : Nat) : Nat
```
