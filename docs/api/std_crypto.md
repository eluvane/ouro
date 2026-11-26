# std/crypto.ouro

SHA-256 digests and HMAC-SHA256 message authentication in Ouro. Both use the 32-bit operations in `std/word.ouro`.

Declarations: 43.

## def n64

```ouro
def n64 : Nat
```

## def n48

```ouro
def n48 : Nat
```

## def n56

```ouro
def n56 : Nat
```

## def b80

```ouro
def b80 : Nat
```

## def b36

```ouro
def b36 : Nat
```

## def b5c

```ouro
def b5c : Nat
```

## def sha256_h0_hex

```ouro
def sha256_h0_hex : String
```

## def sha256_k_hex

```ouro
def sha256_k_hex : String
```

## def pack_words

```ouro
def pack_words : List Nat -> List Nat
```

## def words_of_hex

```ouro
def words_of_hex (hex : String) : List Nat
```

## def sha256_k

```ouro
def sha256_k : List Nat
```

## def sha256_iv

```ouro
def sha256_iv : List Nat
```

## def take_fuel

```ouro
def take_fuel (A : Type) : Nat -> List A -> List A
```

## def drop_fuel

```ouro
def drop_fuel (A : Type) : Nat -> List A -> List A
```

## def be64_len

```ouro
def be64_len (bitlen : Nat) : List Nat
```

## def sha256_pad

```ouro
def sha256_pad (bs : List Nat) : List Nat
```

## def ch32

```ouro
def ch32 (e : Nat) (f : Nat) (g : Nat) : Nat
```

## def maj32

```ouro
def maj32 (a : Nat) (b : Nat) (c : Nat) : Nat
```

## def sig0

```ouro
def sig0 (x : Nat) : Nat
```

## def sig1

```ouro
def sig1 (x : Nat) : Nat
```

## def sum0

```ouro
def sum0 (x : Nat) : Nat
```

## def sum1

```ouro
def sum1 (x : Nat) : Nat
```

## inductive ShaSt

```ouro
inductive ShaSt : Type
```

## def sha_from_list

```ouro
def sha_from_list (xs : List Nat) : ShaSt
```

## def sha_to_bytes

```ouro
def sha_to_bytes (st : ShaSt) : List Nat
```

## def w_at

```ouro
def w_at (ws : List Nat) (i : Nat) : Nat
```

## def w_extend

```ouro
def w_extend (w0 : List Nat) : List Nat
```

## def sha_round

```ouro
def sha_round (k : Nat) (w : Nat) (st : ShaSt) : ShaSt
```

## def sha_compress

```ouro
def sha_compress (st : ShaSt) (block : List Nat) : ShaSt
```

## def sha_blocks

```ouro
def sha_blocks : Nat -> List Nat -> ShaSt -> ShaSt
```

## def sha256_bytes

```ouro
def sha256_bytes (bs : List Nat) : List Nat
```

## def sha256

```ouro
def sha256 (s : String) : String
```

## def key_block

```ouro
def key_block (key : List Nat) : List Nat
```

## def hmac_sha256_bytes

```ouro
def hmac_sha256_bytes (key : List Nat) (msg : List Nat) : List Nat
```

## def hmac_sha256

```ouro
def hmac_sha256 (key : String) (msg : String) : String
```

## inductive Sha256StreamError

```ouro
inductive Sha256StreamError : Type
```

Count failures retain the attempted total byte count.

## inductive Sha256Stream

```ouro
inductive Sha256Stream : Type
```

A stream state stores the total byte count, eight hash words, and a binary tail of at most 63 bytes. Update and finalization check the state shape. A directly constructed state relies on the caller to supply the correct hash history.

## def sha256_stream_byte_limit

```ouro
def sha256_stream_byte_limit : Nat
```

The existing length encoder retains only 32 bit-length bits.

## def sha256_stream_init

```ouro
def sha256_stream_init : Sha256Stream
```

## def sha256_stream_error_code

```ouro
def sha256_stream_error_code (cause : Sha256StreamError) : String
```

## def sha256_stream_error_message

```ouro
def sha256_stream_error_message (cause : Sha256StreamError) : String
```

## def sha256_stream_update

```ouro
def sha256_stream_update (state : Sha256Stream) (chunk : String)
    : Either Sha256StreamError Sha256Stream
```

Append exact binary bytes, including NUL; reject invalid state or total >= 512 MiB.

## def sha256_stream_final

```ouro
def sha256_stream_final (state : Sha256Stream) : Either Sha256StreamError String
```

Return lowercase hex without consuming the immutable state.
