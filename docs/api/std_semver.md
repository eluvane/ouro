# std/semver.ouro

Semver is intentionally partial: prerelease/build metadata is rejected rather than guessed. Range parsing is longest-operator-first so >= and <= are not split as single-character ops.

Declarations: 29.

## inductive Semver

```
inductive Semver : Type
```

## def sv_major

```
def sv_major (v : Semver) : Nat
```

## def sv_minor

```
def sv_minor (v : Semver) : Nat
```

## def sv_patch

```
def sv_patch (v : Semver) : Nat
```

## def sv_show

```
def sv_show (v : Semver) : String
```

## def sv_field

```
def sv_field (parts : List String) (i : Nat) : Maybe Nat
```

Field i of a dotted version; a missing or empty field reads as 0.

## def sv_parse

```
def sv_parse (s : String) : Maybe Semver
```

## def sv_cmp

```
def sv_cmp (a : Semver) (b : Semver) : Ordering
```

## def sv_eq

```
def sv_eq (a : Semver) (b : Semver) : Bool
```

## def sv_lt

```
def sv_lt (a : Semver) (b : Semver) : Bool
```

## def sv_le

```
def sv_le (a : Semver) (b : Semver) : Bool
```

## def sv_caret_limit

```
def sv_caret_limit (v : Semver) : Semver
```

Upper bound of a caret range: 1.2.3 -> 2.0.0, 0.2.3 -> 0.3.0, 0.0.3 -> 0.1.0.

## def sv_tilde_limit

```
def sv_tilde_limit (v : Semver) : Semver
```

## inductive SvRange

```
inductive SvRange : Type
```

## def sv_range_of

```
def sv_range_of (mk : Semver -> SvRange) (rest : String) : SvRange
```

Every wrapper is a named function rather than a bare constructor: a constructor passed as a value is not applicable at runtime.

## def sv_caret

```
def sv_caret (v : Semver) : SvRange
```

## def sv_tilde

```
def sv_tilde (v : Semver) : SvRange
```

## def sv_exact

```
def sv_exact (v : Semver) : SvRange
```

## def sv_at_least

```
def sv_at_least (v : Semver) : SvRange
```

## def sv_greater

```
def sv_greater (v : Semver) : SvRange
```

## def sv_at_most

```
def sv_at_most (v : Semver) : SvRange
```

## def sv_below

```
def sv_below (v : Semver) : SvRange
```

## def sv_range_parse

```
def sv_range_parse (s : String) : SvRange
```

Longest operator first, so ">=" is not read as ">".

## def sv_in_range

```
def sv_in_range (r : SvRange) (v : Semver) : Bool
```

## def sv_matches

```
def sv_matches (range : String) (version : String) : Bool
```

## def sv_sort

```
def sv_sort (vs : List Semver) : List Semver
```

## def sv_parse_all

```
def sv_parse_all (vs : List String) : List Semver
```

## def sv_best

```
def sv_best (range : String) (vs : List Semver) : Maybe Semver
```

Highest version satisfying the range, Nothing when none does.

## def sv_best_str

```
def sv_best_str (range : String) (vs : List String) : Maybe String
```
