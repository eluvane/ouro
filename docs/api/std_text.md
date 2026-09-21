# std/text.ouro

Text-processing helpers for CLI and data programs.

Declarations: 18.

## def str_split_last

```
def str_split_last (s : String) (sep : String) : Maybe (Pair String String)
```

## def str_drop_prefix_or

```
def str_drop_prefix_or (s : String) (pre : String) : String
```

## def str_drop_suffix_or

```
def str_drop_suffix_or (s : String) (suf : String) : String
```

## def str_chomp

```
def str_chomp (s : String) : String
```

## def str_tokens

```
def str_tokens (s : String) : List String
```

## def str_lines_trimmed

```
def str_lines_trimmed (s : String) : List String
```

## def str_char_all

```
def str_char_all (p : Nat -> Bool) (s : String) : Bool
```

## def str_char_any

```
def str_char_any (p : Nat -> Bool) (s : String) : Bool
```

## def str_is_blank

```
def str_is_blank (s : String) : Bool
```

## def str_nonblank_lines

```
def str_nonblank_lines (s : String) : List String
```

## def str_is_digits

```
def str_is_digits (s : String) : Bool
```

## def str_is_alpha_text

```
def str_is_alpha_text (s : String) : Bool
```

## def str_is_alnum_text

```
def str_is_alnum_text (s : String) : Bool
```

## def str_is_lower_text

```
def str_is_lower_text (s : String) : Bool
```

## def str_is_upper_text

```
def str_is_upper_text (s : String) : Bool
```

## def str_between

```
def str_between (s : String) (left : String) (right : String) : Maybe String
```

## def str_parse_nat

```
def str_parse_nat (s : String) : Maybe Nat
```

## def str_parse_bool

```
def str_parse_bool (s : String) : Maybe Bool
```
