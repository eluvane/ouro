# std/bytes.ouro

Hex/Base64 helpers are total over Nat byte codes; invalid decode input returns Nothing.

Declarations: 21.

## def n256

```
def n256 : Nat
```

## def n65536

```
def n65536 : Nat
```

## def n4096

```
def n4096 : Nat
```

## def n262144

```
def n262144 : Nat
```

## def hex_encode_byte

```
def hex_encode_byte (b : Nat) : List Nat
```

## def hex_encode

```
def hex_encode : List Nat -> List Nat
```

## def hex_encode_str

```
def hex_encode_str (s : String) : String
```

## def hex_nibble

```
def hex_nibble (c : Nat) : Maybe Nat
```

## def hex_decode

```
def hex_decode : List Nat -> Maybe (List Nat)
```

## def hex_decode_str

```
def hex_decode_str (s : String) : Maybe String
```

## def b64_alphabet

```
def b64_alphabet : String
```

## def b64_char

```
def b64_char (n : Nat) : Nat
```

## def b64_val

```
def b64_val (c : Nat) : Maybe Nat
```

## def b64_pad

```
def b64_pad : Nat
```

## def b64_quad

```
def b64_quad (n : Nat) (c2 : Nat) (c3 : Nat) : List Nat
```

## def pack3

```
def pack3 (a : Nat) (b : Nat) (c : Nat) : List Nat
```

## def b64_encode

```
def b64_encode : List Nat -> List Nat
```

## def b64_encode_str

```
def b64_encode_str (s : String) : String
```

## def xor_byte

```
def xor_byte (a : Nat) (b : Nat) : Nat
```

## def xor_bytes

```
def xor_bytes : List Nat -> List Nat -> List Nat
```

## def bytes_eq

```
def bytes_eq : List Nat -> List Nat -> Bool
```
