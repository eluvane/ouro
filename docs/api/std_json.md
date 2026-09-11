# std/json.ouro

JSON helpers are prefixed because imports flatten into one namespace.

Declarations: 29.

## inductive Json

```
inductive Json : Type
```

## inductive ParseR

```
inductive ParseR : Type
```

## inductive ParseHead

```
inductive ParseHead : Type
```

## def eqNat

```
def eqNat (n : Nat) (m : Nat) : Bool
```

## def lebNat

```
def lebNat (n : Nat) (m : Nat) : Bool
```

## def json_ch_at

```
def json_ch_at (s : String) (i : Nat) : Nat
```

Host byte lookup is constant time on a compact string.  parse_json compacts once before walking, instead of restarting from a linked-list head for every indexed byte.

## def skip_ws

```
def skip_ws : Nat -> String -> Nat -> Nat
```

## def starts_with_at

```
def starts_with_at (s : String) (i : Nat) (pat : List Nat) : Bool
```

## def esc_codes

```
def esc_codes : List Nat -> List Nat
```

## def json_escape_str

```
def json_escape_str (s : String) : String
```

## def json_print_fuel

```
def json_print_fuel : Nat -> Json -> String
```

## def ten

```
def ten : Nat
```

## def json_print

```
def json_print (j : Json) : String
```

## def json_unescape_char

```
def json_unescape_char (c : Nat) : Maybe Nat
```

## def decode_esc

```
def decode_esc (s : String) (i : Nat) : Maybe (Pair Nat Nat)
```

## def json_hex_quad

```
def json_hex_quad (s : String) (start : Nat) : Pair (Maybe Nat) Nat
```

Four hex digits, with the first malformed or missing byte as the error.

## def json_scalar_utf8

```
def json_scalar_utf8 (value : Nat) : List Nat
```

Only valid Unicode scalars reach this encoder. Split the high groups first so repeated-subtraction division stays bounded by 63, even for U+10FFFF.

## def json_unicode_escape

```
def json_unicode_escape (s : String) (i : Nat) : Pair (Maybe (List Nat)) Nat
```

Entry is the u after a backslash. A high surrogate requires an immediately adjacent low-surrogate escape; lone lows and non-low partners are errors.

## def json_string_scan

```
def json_string_scan : Nat -> Pair String Nat -> Nat -> List Nat -> Pair (Maybe String) Nat
```

Reverse byte accumulation plus one final conversion is linear: no growing concatenations or repeated suffix slicing. Four explicit scanner arguments keep native tail calls eligible even for very large compiler/tool strings.

## def json_string_parse

```
def json_string_parse (s : String) (i : Nat) : Pair (Maybe String) Nat
```

Entry must point at the opening quote. Success points past the closing quote. Existing errors retain their byte offsets, including the last consumed byte for a missing close. Raw bytes >= 32 retain their byte values; escaped Unicode is strictly decoded, including an escaped NUL.

## def parse_string_lit

```
def parse_string_lit (fuel : Nat) (s : String) (i0 : Nat) : ParseR
```

## def json_is_digit

```
def json_is_digit (c : Nat) : Bool
```

## def json_consume_digits

```
def json_consume_digits (s : String) (start : Nat) : Nat
```

## def parse_num

```
def parse_num (s : String) (i : Nat) : ParseR
```

## def parse_head

```
def parse_head (fuel : Nat) (s : String) (i0 : Nat) : ParseHead
```

## def parse_val

```
def parse_val : Nat -> Nat -> String -> Nat -> ParseR
```

## def json_max_depth

```
def json_max_depth : Nat
```

Large strings and arrays may be valid, but recursive JSON structure is capped independently so a tiny deeply nested frame cannot exhaust the host.

## def parse_json

```
def parse_json (s : String) : Maybe Json
```

## def json_roundtrip_ok

```
def json_roundtrip_ok (s : String) : Bool
```
