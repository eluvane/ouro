# std/gate/share.ouro

Share gate arithmetic is pure so shell and CI wrappers cannot disagree about thresholds.

Declarations: 25.

## inductive CodeBucket

```
inductive CodeBucket : Type
```

## def ext_of

```
def ext_of (path : String) : String
```

## def is_ouro_ext

```
def is_ouro_ext (path : String) : Bool
```

## def is_js_ext

```
def is_js_ext (path : String) : Bool
```

## def is_ml_ext

```
def is_ml_ext (path : String) : Bool
```

## def is_sh_ext

```
def is_sh_ext (path : String) : Bool
```

## def is_py_ext

```
def is_py_ext (path : String) : Bool
```

## def is_code_ext

```
def is_code_ext (path : String) : Bool
```

## def bucket_of

```
def bucket_of (path : String) : CodeBucket
```

## def bucket_name

```
def bucket_name (b : CodeBucket) : String
```

## inductive ShareAcc

```
inductive ShareAcc : Type
```

## def share_zero

```
def share_zero : ShareAcc
```

## def share_add

```
def share_add (a : ShareAcc) (b : CodeBucket) (n : Nat) : ShareAcc
```

## def share_total

```
def share_total (a : ShareAcc) : Nat
```

## def share_ouro

```
def share_ouro (a : ShareAcc) : Nat
```

## def share_non_ouro

```
def share_non_ouro (a : ShareAcc) : Nat
```

## def share_tenths

```
def share_tenths (ouro : Nat) (total : Nat) : Nat
```

ouro * 1000 / total, tenths of a percent. 10*10*10 avoids a 1000 numeral.

## def share_floor_49x_tenths

```
def share_floor_49x_tenths : Nat
```

98.0 percent = 980 tenths. Also ouro >= 49 * non_ouro.

## def times_49

```
def times_49 (n : Nat) : Nat
```

## def meets_49x

```
def meets_49x (ouro : Nat) (non : Nat) : Bool
```

## def meets_floor

```
def meets_floor (ouro : Nat) (total : Nat) (floor_tenths : Nat) : Bool
```

## def share_pass

```
def share_pass (a : ShareAcc) (floor_tenths : Nat) : Bool
```

## def classify_one

```
def classify_one (path : String) (bytes : Nat) (a : ShareAcc) : ShareAcc
```

## def classify_table

```
def classify_table (table : String) : ShareAcc
```

Fold a pre-parsed path|bytes table (one "path|n" line per file).

## def share_report

```
def share_report (a : ShareAcc) : String
```
