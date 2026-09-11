# std/char.ouro

ASCII predicates only; Unicode stays a String/runtime concern.

Declarations: 64.

## def ch_nul

```
def ch_nul : Nat
```

## def ch_tab

```
def ch_tab : Nat
```

## def ch_lf

```
def ch_lf : Nat
```

## def ch_cr

```
def ch_cr : Nat
```

## def ch_space

```
def ch_space : Nat
```

## def ch_bang

```
def ch_bang : Nat
```

## def ch_quote

```
def ch_quote : Nat
```

## def ch_hash

```
def ch_hash : Nat
```

## def ch_dollar

```
def ch_dollar : Nat
```

## def ch_percent

```
def ch_percent : Nat
```

## def ch_amp

```
def ch_amp : Nat
```

## def ch_squote

```
def ch_squote : Nat
```

## def ch_lparen

```
def ch_lparen : Nat
```

## def ch_rparen

```
def ch_rparen : Nat
```

## def ch_star

```
def ch_star : Nat
```

## def ch_plus

```
def ch_plus : Nat
```

## def ch_comma

```
def ch_comma : Nat
```

## def ch_minus

```
def ch_minus : Nat
```

## def ch_dot

```
def ch_dot : Nat
```

## def ch_slash

```
def ch_slash : Nat
```

## def ch_zero

```
def ch_zero : Nat
```

## def ch_nine

```
def ch_nine : Nat
```

## def ch_colon

```
def ch_colon : Nat
```

## def ch_semi

```
def ch_semi : Nat
```

## def ch_lt

```
def ch_lt : Nat
```

## def ch_eq

```
def ch_eq : Nat
```

## def ch_gt

```
def ch_gt : Nat
```

## def ch_qmark

```
def ch_qmark : Nat
```

## def ch_at

```
def ch_at : Nat
```

## def ch_A

```
def ch_A : Nat
```

## def ch_Z

```
def ch_Z : Nat
```

## def ch_lbrack

```
def ch_lbrack : Nat
```

## def ch_bslash

```
def ch_bslash : Nat
```

## def ch_rbrack

```
def ch_rbrack : Nat
```

## def ch_caret

```
def ch_caret : Nat
```

## def ch_under

```
def ch_under : Nat
```

## def ch_tick

```
def ch_tick : Nat
```

## def ch_a

```
def ch_a : Nat
```

## def ch_z

```
def ch_z : Nat
```

## def ch_lbrace

```
def ch_lbrace : Nat
```

## def ch_pipe

```
def ch_pipe : Nat
```

## def ch_rbrace

```
def ch_rbrace : Nat
```

## def ch_tilde

```
def ch_tilde : Nat
```

## def ch_del

```
def ch_del : Nat
```

## def is_nul

```
def is_nul (c : Nat) : Bool
```

## def is_tab

```
def is_tab (c : Nat) : Bool
```

## def is_lf

```
def is_lf (c : Nat) : Bool
```

## def is_cr

```
def is_cr (c : Nat) : Bool
```

## def is_space

```
def is_space (c : Nat) : Bool
```

## def is_ws

```
def is_ws (c : Nat) : Bool
```

## def is_digit

```
def is_digit (c : Nat) : Bool
```

## def is_upper

```
def is_upper (c : Nat) : Bool
```

## def is_lower

```
def is_lower (c : Nat) : Bool
```

## def is_alpha

```
def is_alpha (c : Nat) : Bool
```

## def is_alnum

```
def is_alnum (c : Nat) : Bool
```

## def is_hex

```
def is_hex (c : Nat) : Bool
```

## def is_oct

```
def is_oct (c : Nat) : Bool
```

## def is_bin

```
def is_bin (c : Nat) : Bool
```

## def is_punct

```
def is_punct (c : Nat) : Bool
```

## def is_graph

```
def is_graph (c : Nat) : Bool
```

## def is_print

```
def is_print (c : Nat) : Bool
```

## def is_cntrl

```
def is_cntrl (c : Nat) : Bool
```

## def is_ascii

```
def is_ascii (c : Nat) : Bool
```

## def is_ident_start

```
def is_ident_start (c : Nat) : Bool
```

## def is_ident_cont

```
def is_ident_cont (c : Nat) : Bool
```

Letters, digits, `_`, and `'` — the same continuation set as the lexer.

## def is_snake

```
def is_snake (c : Nat) : Bool
```

## def to_lower

```
def to_lower (c : Nat) : Nat
```

## def to_upper

```
def to_upper (c : Nat) : Nat
```

## def digit_val

```
def digit_val (c : Nat) : Nat
```

## def hex_digit

```
def hex_digit (n : Nat) : Nat
```

## def hex_digit_upper

```
def hex_digit_upper (n : Nat) : Nat
```

## def eq_char_ci

```
def eq_char_ci (a : Nat) (b : Nat) : Bool
```
