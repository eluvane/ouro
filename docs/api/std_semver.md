# std/semver.ouro

Semver is intentionally partial: prerelease/build metadata is rejected rather than guessed. Range parsing is longest-operator-first so >= and <= are not split as single-character ops.

Declarations: 29.

## inductive Semver

```ouro
inductive Semver : Type
```

## def sv_major

```ouro
def sv_major (v : Semver) : Nat
```

## def sv_minor

```ouro
def sv_minor (v : Semver) : Nat
```

## def sv_patch

```ouro
def sv_patch (v : Semver) : Nat
```

## def sv_show

```ouro
def sv_show (v : Semver) : String
```

## def sv_field

```ouro
def sv_field (parts : List String) (i : Nat) : Maybe Nat
```

Field i of a dotted version; a missing or empty field reads as 0.

## def sv_parse

```ouro
def sv_parse (s : String) : Maybe Semver
```

## def sv_cmp

```ouro
def sv_cmp (a : Semver) (b : Semver) : Ordering
```

## def sv_eq

```ouro
def sv_eq (a : Semver) (b : Semver) : Bool
```

## def sv_lt

```ouro
def sv_lt (a : Semver) (b : Semver) : Bool
```

## def sv_le

```ouro
def sv_le (a : Semver) (b : Semver) : Bool
```

## def sv_caret_limit

```ouro
def sv_caret_limit (v : Semver) : Semver
```

Upper bound of a caret range: 1.2.3 -> 2.0.0, 0.2.3 -> 0.3.0, 0.0.3 -> 0.1.0.

## def sv_tilde_limit

```ouro
def sv_tilde_limit (v : Semver) : Semver
```

## inductive SvRange

```ouro
inductive SvRange : Type
```

## def sv_range_of

```ouro
def sv_range_of (mk : Semver -> SvRange) (rest : String) : SvRange
```

Parse the range operand and apply `mk`. Return `SvBad` for an empty or invalid operand.

## def sv_caret

```ouro
def sv_caret (v : Semver) : SvRange
```

## def sv_tilde

```ouro
def sv_tilde (v : Semver) : SvRange
```

## def sv_exact

```ouro
def sv_exact (v : Semver) : SvRange
```

## def sv_at_least

```ouro
def sv_at_least (v : Semver) : SvRange
```

## def sv_greater

```ouro
def sv_greater (v : Semver) : SvRange
```

## def sv_at_most

```ouro
def sv_at_most (v : Semver) : SvRange
```

## def sv_below

```ouro
def sv_below (v : Semver) : SvRange
```

## def sv_range_parse

```ouro
def sv_range_parse (s : String) : SvRange
```

Longest operator first, so ">=" is not read as ">".

## def sv_in_range

```ouro
def sv_in_range (r : SvRange) (v : Semver) : Bool
```

## def sv_matches

```ouro
def sv_matches (range : String) (version : String) : Bool
```

## def sv_sort

```ouro
def sv_sort (vs : List Semver) : List Semver
```

## def sv_parse_all

```ouro
def sv_parse_all (vs : List String) : List Semver
```

## def sv_best

```ouro
def sv_best (range : String) (vs : List Semver) : Maybe Semver
```

Highest version satisfying the range, Nothing when none does.

## def sv_best_str

```ouro
def sv_best_str (range : String) (vs : List String) : Maybe String
```
