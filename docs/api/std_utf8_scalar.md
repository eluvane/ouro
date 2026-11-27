# std/utf8_scalar.ouro

Pure UTF-8 encoding shared by source literals and JSON decoding.

Declarations: 3.

## def utf8_scalar_valid

```ouro
def utf8_scalar_valid (value : Nat) : Bool
```

Unicode scalars exclude surrogate code points and values above U+10FFFF.

## def utf8_scalar_bytes

```ouro
def utf8_scalar_bytes (value : Nat) : List Nat
```

The caller must first establish utf8_scalar_valid value.

## def utf8_scalar_checked

```ouro
def utf8_scalar_checked (value : Nat) : Maybe (List Nat)
```

Reject invalid scalars instead of encoding an out-of-range byte sequence.
