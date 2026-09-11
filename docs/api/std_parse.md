# std/parse.ouro

Parser combinators spend input-length fuel so malformed input cannot loop forever.

Declarations: 28.

## inductive PRes

```
inductive PRes (A : Type) : Type
```

## def pok

```
def pok (A : Type) (x : A) (rest : List Nat) : PRes A
```

## def pfail

```
def pfail (A : Type) (rest : List Nat) : PRes A
```

## def pmap

```
def pmap (A : Type) (B : Type) (f : A -> B) (r : PRes A) : PRes B
```

## def pany

```
def pany (cs : List Nat) : PRes Nat
```

## def psatisfy

```
def psatisfy (p : Nat -> Bool) (cs : List Nat) : PRes Nat
```

## def pchar

```
def pchar (c : Nat) (cs : List Nat) : PRes Nat
```

## def pdigit

```
def pdigit (cs : List Nat) : PRes Nat
```

## def phex

```
def phex (cs : List Nat) : PRes Nat
```

## def palpha

```
def palpha (cs : List Nat) : PRes Nat
```

## def palnum

```
def palnum (cs : List Nat) : PRes Nat
```

## def pws1

```
def pws1 (cs : List Nat) : PRes Nat
```

## def pstring

```
def pstring (pat : List Nat) : List Nat -> PRes (List Nat)
```

## def pstr

```
def pstr (s : String) (cs : List Nat) : PRes String
```

## def pmany_fuel

```
def pmany_fuel (A : Type) (p : List Nat -> PRes A)
```

Fuel is the remaining input length, so the caller supplies it.

## def pmany

```
def pmany (A : Type) (p : List Nat -> PRes A) (cs : List Nat)
```

## def pmany1

```
def pmany1 (A : Type) (p : List Nat -> PRes A) (cs : List Nat) : PRes (List A)
```

## def popt

```
def popt (A : Type) (p : List Nat -> PRes A) (cs : List Nat) : PRes (Maybe A)
```

## def pskip_ws

```
def pskip_ws (cs : List Nat) : PRes Unit
```

## def pnat

```
def pnat (cs : List Nat) : PRes Nat
```

## def pident

```
def pident (cs : List Nat) : PRes (List Nat)
```

## def psep_by

```
def psep_by (A : Type) (p : List Nat -> PRes A) (sep : List Nat -> PRes Nat) (cs : List Nat) : PRes (List A)
```

## def pchoice

```
def pchoice (A : Type) (p : List Nat -> PRes A) (q : List Nat -> PRes A) (cs : List Nat) : PRes A
```

## def pbetween

```
def pbetween (A : Type) (l : Nat) (r : Nat) (p : List Nat -> PRes A) (cs : List Nat) : PRes A
```

## def peof

```
def peof (cs : List Nat) : PRes Unit
```

## def ptoken

```
def ptoken (A : Type) (p : List Nat -> PRes A) (cs : List Nat) : PRes A
```

## def parse_nat

```
def parse_nat (s : String) : Maybe Nat
```

## def parse_ident

```
def parse_ident (s : String) : Maybe String
```
