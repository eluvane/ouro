# std/crypto.ouro

SHA-256 and HMAC-SHA256 in Ouro. Word32 ops come from std/word.ouro (host-fast at emit). Not a TLS stack and not a C digest primitive.

Declarations: 35.

## def n64

```
def n64 : Nat
```

## def n48

```
def n48 : Nat
```

## def n56

```
def n56 : Nat
```

## def b80

```
def b80 : Nat
```

## def b36

```
def b36 : Nat
```

## def b5c

```
def b5c : Nat
```

## def sha256_h0_hex

```
def sha256_h0_hex : String
```

## def sha256_k_hex

```
def sha256_k_hex : String
```

## def pack_words

```
def pack_words : List Nat -> List Nat
```

## def words_of_hex

```
def words_of_hex (hex : String) : List Nat
```

## def sha256_k

```
def sha256_k : List Nat
```

## def sha256_iv

```
def sha256_iv : List Nat
```

## def take_fuel

```
def take_fuel (A : Type) : Nat -> List A -> List A
```

## def drop_fuel

```
def drop_fuel (A : Type) : Nat -> List A -> List A
```

## def be64_len

```
def be64_len (bitlen : Nat) : List Nat
```

## def sha256_pad

```
def sha256_pad (bs : List Nat) : List Nat
```

## def ch32

```
def ch32 (e : Nat) (f : Nat) (g : Nat) : Nat
```

## def maj32

```
def maj32 (a : Nat) (b : Nat) (c : Nat) : Nat
```

## def sig0

```
def sig0 (x : Nat) : Nat
```

## def sig1

```
def sig1 (x : Nat) : Nat
```

## def sum0

```
def sum0 (x : Nat) : Nat
```

## def sum1

```
def sum1 (x : Nat) : Nat
```

## inductive ShaSt

```
inductive ShaSt : Type
```

## def sha_from_list

```
def sha_from_list (xs : List Nat) : ShaSt
```

## def sha_to_bytes

```
def sha_to_bytes (st : ShaSt) : List Nat
```

## def w_at

```
def w_at (ws : List Nat) (i : Nat) : Nat
```

## def w_extend

```
def w_extend (w0 : List Nat) : List Nat
```

## def sha_round

```
def sha_round (k : Nat) (w : Nat) (st : ShaSt) : ShaSt
```

## def sha_compress

```
def sha_compress (st : ShaSt) (block : List Nat) : ShaSt
```

## def sha_blocks

```
def sha_blocks : Nat -> List Nat -> ShaSt -> ShaSt
```

## def sha256_bytes

```
def sha256_bytes (bs : List Nat) : List Nat
```

## def sha256

```
def sha256 (s : String) : String
```

## def key_block

```
def key_block (key : List Nat) : List Nat
```

## def hmac_sha256_bytes

```
def hmac_sha256_bytes (key : List Nat) (msg : List Nat) : List Nat
```

## def hmac_sha256

```
def hmac_sha256 (key : String) (msg : String) : String
```
