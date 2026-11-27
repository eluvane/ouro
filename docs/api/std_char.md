# std/char.ouro

ASCII predicates only; Unicode stays a String/runtime concern.

Declarations: 72.

## def ch_nul

```ouro
def ch_nul : Nat
```

## def ch_tab

```ouro
def ch_tab : Nat
```

## def ch_lf

```ouro
def ch_lf : Nat
```

## def ch_cr

```ouro
def ch_cr : Nat
```

## def ch_space

```ouro
def ch_space : Nat
```

## def ch_bang

```ouro
def ch_bang : Nat
```

## def ch_quote

```ouro
def ch_quote : Nat
```

## def ch_hash

```ouro
def ch_hash : Nat
```

## def ch_dollar

```ouro
def ch_dollar : Nat
```

## def ch_percent

```ouro
def ch_percent : Nat
```

## def ch_amp

```ouro
def ch_amp : Nat
```

## def ch_squote

```ouro
def ch_squote : Nat
```

## def ch_lparen

```ouro
def ch_lparen : Nat
```

## def ch_rparen

```ouro
def ch_rparen : Nat
```

## def ch_star

```ouro
def ch_star : Nat
```

## def ch_plus

```ouro
def ch_plus : Nat
```

## def ch_comma

```ouro
def ch_comma : Nat
```

## def ch_minus

```ouro
def ch_minus : Nat
```

## def ch_dot

```ouro
def ch_dot : Nat
```

## def ch_slash

```ouro
def ch_slash : Nat
```

## def ch_zero

```ouro
def ch_zero : Nat
```

## def ch_nine

```ouro
def ch_nine : Nat
```

## def ch_colon

```ouro
def ch_colon : Nat
```

## def ch_semi

```ouro
def ch_semi : Nat
```

## def ch_lt

```ouro
def ch_lt : Nat
```

## def ch_eq

```ouro
def ch_eq : Nat
```

## def ch_gt

```ouro
def ch_gt : Nat
```

## def ch_qmark

```ouro
def ch_qmark : Nat
```

## def ch_at

```ouro
def ch_at : Nat
```

## def ch_A

```ouro
def ch_A : Nat
```

## def ch_Z

```ouro
def ch_Z : Nat
```

## def ch_lbrack

```ouro
def ch_lbrack : Nat
```

## def ch_bslash

```ouro
def ch_bslash : Nat
```

## def ch_rbrack

```ouro
def ch_rbrack : Nat
```

## def ch_caret

```ouro
def ch_caret : Nat
```

## def ch_under

```ouro
def ch_under : Nat
```

## def ch_tick

```ouro
def ch_tick : Nat
```

## def ch_a

```ouro
def ch_a : Nat
```

## def ch_z

```ouro
def ch_z : Nat
```

## def ch_lbrace

```ouro
def ch_lbrace : Nat
```

## def ch_pipe

```ouro
def ch_pipe : Nat
```

## def ch_rbrace

```ouro
def ch_rbrace : Nat
```

## def ch_tilde

```ouro
def ch_tilde : Nat
```

## def ch_del

```ouro
def ch_del : Nat
```

## def is_nul

```ouro
def is_nul (c : Nat) : Bool
```

## def is_tab

```ouro
def is_tab (c : Nat) : Bool
```

## def is_lf

```ouro
def is_lf (c : Nat) : Bool
```

## def is_cr

```ouro
def is_cr (c : Nat) : Bool
```

## def is_space

```ouro
def is_space (c : Nat) : Bool
```

## def is_ws

```ouro
def is_ws (c : Nat) : Bool
```

## def is_digit

```ouro
def is_digit (c : Nat) : Bool
```

## def is_upper

```ouro
def is_upper (c : Nat) : Bool
```

## def is_lower

```ouro
def is_lower (c : Nat) : Bool
```

## def is_alpha

```ouro
def is_alpha (c : Nat) : Bool
```

## def is_alnum

```ouro
def is_alnum (c : Nat) : Bool
```

## def is_hex

```ouro
def is_hex (c : Nat) : Bool
```

## def is_oct

```ouro
def is_oct (c : Nat) : Bool
```

## def is_bin

```ouro
def is_bin (c : Nat) : Bool
```

## def is_punct

```ouro
def is_punct (c : Nat) : Bool
```

## def is_graph

```ouro
def is_graph (c : Nat) : Bool
```

## def is_print

```ouro
def is_print (c : Nat) : Bool
```

## def is_cntrl

```ouro
def is_cntrl (c : Nat) : Bool
```

## def is_ascii

```ouro
def is_ascii (c : Nat) : Bool
```

## def is_ident_start

```ouro
def is_ident_start (c : Nat) : Bool
```

## def is_ident_cont

```ouro
def is_ident_cont (c : Nat) : Bool
```

Letters, digits, `_`, and `'` — the same continuation set as the lexer.

## def is_snake

```ouro
def is_snake (c : Nat) : Bool
```

## def to_lower

```ouro
def to_lower (c : Nat) : Nat
```

## def to_upper

```ouro
def to_upper (c : Nat) : Nat
```

## def digit_val

```ouro
def digit_val (c : Nat) : Nat
```

## def hex_digit

```ouro
def hex_digit (n : Nat) : Nat
```

## def hex_digit_upper

```ouro
def hex_digit_upper (n : Nat) : Nat
```

## def eq_char_ci

```ouro
def eq_char_ci (a : Nat) (b : Nat) : Bool
```
