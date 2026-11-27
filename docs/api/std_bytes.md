# std/bytes.ouro

Encode bytes as hexadecimal or Base64. The hexadecimal decoder returns `Nothing` for invalid input. The Base64 helpers also look up individual alphabet symbols.

Declarations: 21.

## def n256

```ouro
def n256 : Nat
```

## def n65536

```ouro
def n65536 : Nat
```

## def n4096

```ouro
def n4096 : Nat
```

## def n262144

```ouro
def n262144 : Nat
```

## def hex_encode_byte

```ouro
def hex_encode_byte (b : Nat) : List Nat
```

## def hex_encode

```ouro
def hex_encode : List Nat -> List Nat
```

## def hex_encode_str

```ouro
def hex_encode_str (s : String) : String
```

## def hex_nibble

```ouro
def hex_nibble (c : Nat) : Maybe Nat
```

## def hex_decode

```ouro
def hex_decode : List Nat -> Maybe (List Nat)
```

## def hex_decode_str

```ouro
def hex_decode_str (s : String) : Maybe String
```

## def b64_alphabet

```ouro
def b64_alphabet : String
```

## def b64_char

```ouro
def b64_char (n : Nat) : Nat
```

## def b64_val

```ouro
def b64_val (c : Nat) : Maybe Nat
```

## def b64_pad

```ouro
def b64_pad : Nat
```

## def b64_quad

```ouro
def b64_quad (n : Nat) (c2 : Nat) (c3 : Nat) : List Nat
```

## def pack3

```ouro
def pack3 (a : Nat) (b : Nat) (c : Nat) : List Nat
```

## def b64_encode

```ouro
def b64_encode : List Nat -> List Nat
```

## def b64_encode_str

```ouro
def b64_encode_str (s : String) : String
```

## def xor_byte

```ouro
def xor_byte (a : Nat) (b : Nat) : Nat
```

## def xor_bytes

```ouro
def xor_bytes : List Nat -> List Nat -> List Nat
```

## def bytes_eq

```ouro
def bytes_eq : List Nat -> List Nat -> Bool
```
