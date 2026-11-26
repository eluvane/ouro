# std/gate/share.ouro

Count source bytes by file category and compute the Ouro byte share.

Declarations: 25.

## inductive CodeBucket

```ouro
inductive CodeBucket : Type
```

## def ext_of

```ouro
def ext_of (path : String) : String
```

## def is_ouro_ext

```ouro
def is_ouro_ext (path : String) : Bool
```

## def is_js_ext

```ouro
def is_js_ext (path : String) : Bool
```

## def is_ml_ext

```ouro
def is_ml_ext (path : String) : Bool
```

## def is_sh_ext

```ouro
def is_sh_ext (path : String) : Bool
```

## def is_py_ext

```ouro
def is_py_ext (path : String) : Bool
```

## def is_code_ext

```ouro
def is_code_ext (path : String) : Bool
```

## def bucket_of

```ouro
def bucket_of (path : String) : CodeBucket
```

## def bucket_name

```ouro
def bucket_name (b : CodeBucket) : String
```

## inductive ShareAcc

```ouro
inductive ShareAcc : Type
```

## def share_zero

```ouro
def share_zero : ShareAcc
```

## def share_add

```ouro
def share_add (a : ShareAcc) (b : CodeBucket) (n : Nat) : ShareAcc
```

## def share_total

```ouro
def share_total (a : ShareAcc) : Nat
```

## def share_ouro

```ouro
def share_ouro (a : ShareAcc) : Nat
```

## def share_non_ouro

```ouro
def share_non_ouro (a : ShareAcc) : Nat
```

## def share_tenths

```ouro
def share_tenths (ouro : Nat) (total : Nat) : Nat
```

Return the Ouro share in whole tenths of a percent, rounded down. Return zero when `total` is zero.

## def share_floor_49x_tenths

```ouro
def share_floor_49x_tenths : Nat
```

The 98 percent threshold in tenths of a percent.

## def times_49

```ouro
def times_49 (n : Nat) : Nat
```

## def meets_49x

```ouro
def meets_49x (ouro : Nat) (non : Nat) : Bool
```

## def meets_floor

```ouro
def meets_floor (ouro : Nat) (total : Nat) (floor_tenths : Nat) : Bool
```

## def share_pass

```ouro
def share_pass (a : ShareAcc) (floor_tenths : Nat) : Bool
```

## def classify_one

```ouro
def classify_one (path : String) (bytes : Nat) (a : ShareAcc) : ShareAcc
```

## def classify_table

```ouro
def classify_table (table : String) : ShareAcc
```

Count bytes from one `path|bytes` row per file.

## def share_report

```ouro
def share_report (a : ShareAcc) : String
```
