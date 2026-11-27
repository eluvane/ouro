# std/json.ouro

Parse and print JSON. Prefixed helper names reduce collisions in plain imports.

Declarations: 33.

## inductive ParseR

```ouro
inductive ParseR : Type
```

## inductive ParseHead

```ouro
inductive ParseHead : Type
```

## def eqNat

```ouro
def eqNat (n : Nat) (m : Nat) : Bool
```

## def lebNat

```ouro
def lebNat (n : Nat) (m : Nat) : Bool
```

## def json_ch_at

```ouro
def json_ch_at (s : String) (i : Nat) : Nat
```

Host byte lookup is constant time on a compact string.  parse_json compacts once before walking, instead of restarting from a linked-list head for every indexed byte. Arithmetic increments keep offsets compact across repeated reads. Each read of an offset built with S must walk its constructor chain.

## def skip_ws

```ouro
def skip_ws : Nat -> String -> Nat -> Nat
```

## def starts_with_at

```ouro
def starts_with_at (s : String) (i : Nat) (pat : List Nat) : Bool
```

## def esc_codes

```ouro
def esc_codes : List Nat -> List Nat
```

## def json_escape_str

```ouro
def json_escape_str (s : String) : String
```

## def json_print_fuel

```ouro
def json_print_fuel : Nat -> Json -> String
```

## def ten

```ouro
def ten : Nat
```

## def json_print

```ouro
def json_print (j : Json) : String
```

## def json_unescape_char

```ouro
def json_unescape_char (c : Nat) : Maybe Nat
```

## def decode_esc

```ouro
def decode_esc (s : String) (i : Nat) : Maybe (Pair Nat Nat)
```

## def json_hex_quad

```ouro
def json_hex_quad (s : String) (start : Nat) : Pair (Maybe Nat) Nat
```

Four hex digits, with the first malformed or missing byte as the error.

## def json_scalar_utf8

```ouro
def json_scalar_utf8 (value : Nat) : List Nat
```

This encoder requires a validated Unicode scalar.

## def json_unicode_escape

```ouro
def json_unicode_escape (s : String) (i : Nat) : Pair (Maybe (List Nat)) Nat
```

Entry is the u after a backslash. A high surrogate requires an immediately adjacent low-surrogate escape; lone lows and non-low partners are errors.

## inductive JsonStringProgress

```ouro
inductive JsonStringProgress : Type
```

A balanced composition of byte builders keeps both scanning and final list construction linear without relying on C tail-call optimization.

## def json_string_step

```ouro
def json_string_step (fuel : Nat) (input : Pair String Nat) (i : Nat) : JsonStringProgress
```

## def json_string_join

```ouro
def json_string_join (prefix : List Nat -> List Nat) (result : JsonStringProgress) : JsonStringProgress
```

## def json_string_scan_tree

```ouro
def json_string_scan_tree : Nat -> Pair String Nat -> Nat -> Nat -> JsonStringProgress
```

## def json_string_scan_depth

```ouro
def json_string_scan_depth (fuel : Nat) : Nat
```

## def json_string_scan

```ouro
def json_string_scan : Nat -> Pair String Nat -> Nat -> List Nat -> Pair (Maybe String) Nat
```

## def json_string_parse

```ouro
def json_string_parse (s : String) (i : Nat) : Pair (Maybe String) Nat
```

Start at the opening quote. Success returns the offset after the close. Failure reports a byte offset. A missing close reports the last byte read. Raw bytes of 32 or more retain their values. Unicode escapes must encode valid scalars and can produce NUL.

## def parse_string_lit

```ouro
def parse_string_lit (fuel : Nat) (s : String) (i0 : Nat) : ParseR
```

## def json_is_digit

```ouro
def json_is_digit (c : Nat) : Bool
```

## def json_consume_digits

```ouro
def json_consume_digits (s : String) (start : Nat) : Nat
```

## def parse_num

```ouro
def parse_num (s : String) (i : Nat) : ParseR
```

## def parse_head

```ouro
def parse_head (fuel : Nat) (s : String) (i0 : Nat) : ParseHead
```

## def parse_val

```ouro
def parse_val : Nat -> Nat -> String -> Nat -> ParseR
```

## def json_max_depth

```ouro
def json_max_depth : Nat
```

Limit JSON nesting depth independently of string and array length.

## def parse_json

```ouro
def parse_json (s : String) : Maybe Json
```

## def json_roundtrip_ok

```ouro
def json_roundtrip_ok (s : String) : Bool
```
