# std/string_prims.ouro

Shared checked String identities, without IO or platform dependencies. Analyzer cores and the runtime import the same declarations so their cones can be combined without duplicate String or primitive declarations.

Declarations: 17.

## intrinsic String

```ouro
intrinsic String : Type
```

## intrinsic prim_string_concat

```ouro
intrinsic prim_string_concat : String -> String -> String
```

## intrinsic prim_string_length

```ouro
intrinsic prim_string_length : String -> Nat
```

## intrinsic prim_string_byte_at

```ouro
intrinsic prim_string_byte_at : String -> Nat -> Nat
```

O(1) byte lookup; out-of-range returns zero.

## intrinsic prim_string_slice

```ouro
intrinsic prim_string_slice : String -> Nat -> Nat -> String
```

## intrinsic prim_string_eq

```ouro
intrinsic prim_string_eq : String -> String -> Bool
```

## intrinsic prim_string_of_nat

```ouro
intrinsic prim_string_of_nat : Nat -> String
```

## intrinsic prim_string_to_char_codes

```ouro
intrinsic prim_string_to_char_codes : String -> List Nat
```

## intrinsic prim_string_of_char_codes

```ouro
intrinsic prim_string_of_char_codes : List Nat -> String
```

## intrinsic prim_string_starts

```ouro
intrinsic prim_string_starts : String -> String -> Bool
```

Host-fast byte scans keep process-lifetime CLI heaps bounded.

## intrinsic prim_string_ends

```ouro
intrinsic prim_string_ends : String -> String -> Bool
```

## intrinsic prim_string_contains

```ouro
intrinsic prim_string_contains : String -> String -> Bool
```

## intrinsic prim_string_index

```ouro
intrinsic prim_string_index : String -> String -> Maybe Nat
```

## intrinsic prim_string_split

```ouro
intrinsic prim_string_split : String -> Nat -> List String
```

## intrinsic prim_string_replace

```ouro
intrinsic prim_string_replace : String -> String -> String -> String
```

## intrinsic prim_string_le

```ouro
intrinsic prim_string_le : String -> String -> Bool
```

## intrinsic prim_string_tokens

```ouro
intrinsic prim_string_tokens : String -> List String
```
