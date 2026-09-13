# std/string_prims.ouro

Shared checked String identities, without IO or platform dependencies. Analyzer cores and the runtime import the same declarations so their cones can be combined without duplicate String or primitive declarations.

Declarations: 17.

## intrinsic String

```
intrinsic String : Type
```

## intrinsic prim_string_concat

```
intrinsic prim_string_concat : String -> String -> String
```

## intrinsic prim_string_length

```
intrinsic prim_string_length : String -> Nat
```

## intrinsic prim_string_byte_at

```
intrinsic prim_string_byte_at : String -> Nat -> Nat
```

O(1) byte lookup; out-of-range returns zero.

## intrinsic prim_string_slice

```
intrinsic prim_string_slice : String -> Nat -> Nat -> String
```

## intrinsic prim_string_eq

```
intrinsic prim_string_eq : String -> String -> Bool
```

## intrinsic prim_string_of_nat

```
intrinsic prim_string_of_nat : Nat -> String
```

## intrinsic prim_string_to_char_codes

```
intrinsic prim_string_to_char_codes : String -> List Nat
```

## intrinsic prim_string_of_char_codes

```
intrinsic prim_string_of_char_codes : List Nat -> String
```

## intrinsic prim_string_starts

```
intrinsic prim_string_starts : String -> String -> Bool
```

Host-fast byte scans keep process-lifetime CLI heaps bounded.

## intrinsic prim_string_ends

```
intrinsic prim_string_ends : String -> String -> Bool
```

## intrinsic prim_string_contains

```
intrinsic prim_string_contains : String -> String -> Bool
```

## intrinsic prim_string_index

```
intrinsic prim_string_index : String -> String -> Maybe Nat
```

## intrinsic prim_string_split

```
intrinsic prim_string_split : String -> Nat -> List String
```

## intrinsic prim_string_replace

```
intrinsic prim_string_replace : String -> String -> String -> String
```

## intrinsic prim_string_le

```
intrinsic prim_string_le : String -> String -> Bool
```

## intrinsic prim_string_tokens

```
intrinsic prim_string_tokens : String -> List String
```
