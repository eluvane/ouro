# std/natx.ouro

Nat helpers are built from prelude primitives to avoid giant Peano literals.

Declarations: 35.

## def eq_nat

```
def eq_nat (n : Nat) (m : Nat) : Bool
```

## def leb_nat

```
def leb_nat (n : Nat) (m : Nat) : Bool
```

## def ltb_nat

```
def ltb_nat (n : Nat) (m : Nat) : Bool
```

## def geb_nat

```
def geb_nat (n : Nat) (m : Nat) : Bool
```

## def gtb_nat

```
def gtb_nat (n : Nat) (m : Nat) : Bool
```

## def neb_nat

```
def neb_nat (n : Nat) (m : Nat) : Bool
```

## def pred

```
def pred (n : Nat) : Nat
```

## def max3

```
def max3 (a : Nat) (b : Nat) (c : Nat) : Nat
```

## def min3

```
def min3 (a : Nat) (b : Nat) (c : Nat) : Nat
```

## def clamp_nat

```
def clamp_nat (lo : Nat) (hi : Nat) (x : Nat) : Nat
```

## def evenb

```
def evenb (n : Nat) : Bool
```

## def oddb

```
def oddb (n : Nat) : Bool
```

## def div_nat

```
def div_nat (n : Nat) (m : Nat) : Nat
```

Quotient by repeated subtraction. Fuel = dividend + 1.

## def mod_nat

```
def mod_nat (n : Nat) (m : Nat) : Nat
```

## def divmod_nat

```
def divmod_nat (n : Nat) (m : Nat) : Pair Nat Nat
```

## def pow_nat

```
def pow_nat (base : Nat) (exp : Nat) : Nat
```

## def gcd_nat

```
def gcd_nat (a : Nat) (b : Nat) : Nat
```

## def lcm_nat

```
def lcm_nat (a : Nat) (b : Nat) : Nat
```

## def isqrt_nat

```
def isqrt_nat (n : Nat) : Nat
```

## def log2_nat

```
def log2_nat (n : Nat) : Nat
```

## def fact_nat

```
def fact_nat (n : Nat) : Nat
```

## def fib_nat

```
def fib_nat (n : Nat) : Nat
```

## def sum_range

```
def sum_range (lo : Nat) (hi : Nat) : Nat
```

## def digit_count

```
def digit_count (n : Nat) : Nat
```

## def nth_digit

```
def nth_digit (n : Nat) (i : Nat) : Nat
```

## def from_digits

```
def from_digits : List Nat -> Nat
```

## def to_digits

```
def to_digits (n : Nat) : List Nat
```

## def abs_diff

```
def abs_diff (a : Nat) (b : Nat) : Nat
```

## def sat_sub

```
def sat_sub (a : Nat) (b : Nat) : Nat
```

## def inc

```
def inc (n : Nat) : Nat
```

## def dec

```
def dec (n : Nat) : Nat
```

## def twice

```
def twice (n : Nat) : Nat
```

## def half

```
def half (n : Nat) : Nat
```

## def between

```
def between (lo : Nat) (hi : Nat) (x : Nat) : Bool
```

## def coprime

```
def coprime (a : Nat) (b : Nat) : Bool
```
