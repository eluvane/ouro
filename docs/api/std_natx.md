# std/natx.ouro

Nat helpers are built from prelude primitives to avoid giant Peano literals.

Declarations: 36.

## def eq_nat

```ouro
def eq_nat (n : Nat) (m : Nat) : Bool
```

## def leb_nat

```ouro
def leb_nat (n : Nat) (m : Nat) : Bool
```

## def ltb_nat

```ouro
def ltb_nat (n : Nat) (m : Nat) : Bool
```

## def geb_nat

```ouro
def geb_nat (n : Nat) (m : Nat) : Bool
```

## def gtb_nat

```ouro
def gtb_nat (n : Nat) (m : Nat) : Bool
```

## def neb_nat

```ouro
def neb_nat (n : Nat) (m : Nat) : Bool
```

## def pred

```ouro
def pred (n : Nat) : Nat
```

## def max3

```ouro
def max3 (a : Nat) (b : Nat) (c : Nat) : Nat
```

## def min3

```ouro
def min3 (a : Nat) (b : Nat) (c : Nat) : Nat
```

## def clamp_nat

```ouro
def clamp_nat (lo : Nat) (hi : Nat) (x : Nat) : Nat
```

## def evenb

```ouro
def evenb (n : Nat) : Bool
```

## def oddb

```ouro
def oddb (n : Nat) : Bool
```

## def divmod_nat

```ouro
def divmod_nat (n : Nat) (m : Nat) : Pair Nat Nat
```

Each level doubles the divisor; unwinding selects quotient bits. For positive divisors, n + 1 bounds the doubling depth and structural fuel.

## def div_nat

```ouro
def div_nat (n : Nat) (m : Nat) : Nat
```

## def mod_nat

```ouro
def mod_nat (n : Nat) (m : Nat) : Nat
```

## def pow_nat

```ouro
def pow_nat (base : Nat) (exp : Nat) : Nat
```

## def gcd_nat

```ouro
def gcd_nat (a : Nat) (b : Nat) : Nat
```

## def lcm_nat

```ouro
def lcm_nat (a : Nat) (b : Nat) : Nat
```

## def isqrt_nat

```ouro
def isqrt_nat (n : Nat) : Nat
```

## def log2_nat

```ouro
def log2_nat (n : Nat) : Nat
```

## def fact_nat

```ouro
def fact_nat (n : Nat) : Nat
```

## def fib_nat

```ouro
def fib_nat (n : Nat) : Nat
```

## def sum_range

```ouro
def sum_range (lo : Nat) (hi : Nat) : Nat
```

## def digit_count

```ouro
def digit_count (n : Nat) : Nat
```

## def nth_digit

```ouro
def nth_digit (n : Nat) (i : Nat) : Nat
```

## def from_digits

```ouro
def from_digits : List Nat -> Nat
```

## def to_digits

```ouro
def to_digits (n : Nat) : List Nat
```

## def abs_diff

```ouro
def abs_diff (a : Nat) (b : Nat) : Nat
```

## def sat_sub

```ouro
def sat_sub (a : Nat) (b : Nat) : Nat
```

## def inc

```ouro
def inc (n : Nat) : Nat
```

## def dec

```ouro
def dec (n : Nat) : Nat
```

## def twice

```ouro
def twice (n : Nat) : Nat
```

## def half

```ouro
def half (n : Nat) : Nat
```

## def between

```ouro
def between (lo : Nat) (hi : Nat) (x : Nat) : Bool
```

## def coprime

```ouro
def coprime (a : Nat) (b : Nat) : Bool
```

## def eq_nat_list

```ouro
def eq_nat_list : List Nat -> List Nat -> Bool
```
