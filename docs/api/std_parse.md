# std/parse.ouro

Parser combinators spend input-length fuel so malformed input cannot loop forever.

Declarations: 28.

## inductive PRes

```ouro
inductive PRes (A : Type) : Type
```

## def pok

```ouro
def pok (A : Type) (x : A) (rest : List Nat) : PRes A
```

## def pfail

```ouro
def pfail (A : Type) (rest : List Nat) : PRes A
```

## def pmap

```ouro
def pmap (A : Type) (B : Type) (f : A -> B) (r : PRes A) : PRes B
```

## def pany

```ouro
def pany (cs : List Nat) : PRes Nat
```

## def psatisfy

```ouro
def psatisfy (p : Nat -> Bool) (cs : List Nat) : PRes Nat
```

## def pchar

```ouro
def pchar (c : Nat) (cs : List Nat) : PRes Nat
```

## def pdigit

```ouro
def pdigit (cs : List Nat) : PRes Nat
```

## def phex

```ouro
def phex (cs : List Nat) : PRes Nat
```

## def palpha

```ouro
def palpha (cs : List Nat) : PRes Nat
```

## def palnum

```ouro
def palnum (cs : List Nat) : PRes Nat
```

## def pws1

```ouro
def pws1 (cs : List Nat) : PRes Nat
```

## def pstring

```ouro
def pstring (pat : List Nat) : List Nat -> PRes (List Nat)
```

## def pstr

```ouro
def pstr (s : String) (cs : List Nat) : PRes String
```

## def pmany_fuel

```ouro
def pmany_fuel (A : Type) (p : List Nat -> PRes A)
    : Nat -> List Nat -> PRes (List A)
```

Fuel is the remaining input length, so the caller supplies it.

## def pmany

```ouro
def pmany (A : Type) (p : List Nat -> PRes A) (cs : List Nat)
    : PRes (List A)
```

## def pmany1

```ouro
def pmany1 (A : Type) (p : List Nat -> PRes A) (cs : List Nat) : PRes (List A)
```

## def popt

```ouro
def popt (A : Type) (p : List Nat -> PRes A) (cs : List Nat) : PRes (Maybe A)
```

## def pskip_ws

```ouro
def pskip_ws (cs : List Nat) : PRes Unit
```

## def pnat

```ouro
def pnat (cs : List Nat) : PRes Nat
```

## def pident

```ouro
def pident (cs : List Nat) : PRes (List Nat)
```

## def psep_by

```ouro
def psep_by (A : Type) (p : List Nat -> PRes A) (sep : List Nat -> PRes Nat) (cs : List Nat) : PRes (List A)
```

## def pchoice

```ouro
def pchoice (A : Type) (p : List Nat -> PRes A) (q : List Nat -> PRes A) (cs : List Nat) : PRes A
```

## def pbetween

```ouro
def pbetween (A : Type) (l : Nat) (r : Nat) (p : List Nat -> PRes A) (cs : List Nat) : PRes A
```

## def peof

```ouro
def peof (cs : List Nat) : PRes Unit
```

## def ptoken

```ouro
def ptoken (A : Type) (p : List Nat -> PRes A) (cs : List Nat) : PRes A
```

## def parse_nat

```ouro
def parse_nat (s : String) : Maybe Nat
```

## def parse_ident

```ouro
def parse_ident (s : String) : Maybe String
```
