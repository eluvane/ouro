# std/num.ouro

Numeric helpers for small data-processing programs.

Declarations: 21.

## def nat_eq

```ouro
def nat_eq (a : Nat) (b : Nat) : Bool
```

## def nat_ne

```ouro
def nat_ne (a : Nat) (b : Nat) : Bool
```

## def nat_lt

```ouro
def nat_lt (a : Nat) (b : Nat) : Bool
```

## def nat_le

```ouro
def nat_le (a : Nat) (b : Nat) : Bool
```

## def nat_gt

```ouro
def nat_gt (a : Nat) (b : Nat) : Bool
```

## def nat_ge

```ouro
def nat_ge (a : Nat) (b : Nat) : Bool
```

## def nat_compare

```ouro
def nat_compare (a : Nat) (b : Nat) : Ordering
```

## def nat_min

```ouro
def nat_min (a : Nat) (b : Nat) : Nat
```

## def nat_max

```ouro
def nat_max (a : Nat) (b : Nat) : Nat
```

## def nat_clamp

```ouro
def nat_clamp (lo : Nat) (hi : Nat) (x : Nat) : Nat
```

## def nat_nonzero

```ouro
def nat_nonzero (n : Nat) : Bool
```

## def nat_div_checked

```ouro
def nat_div_checked (n : Nat) (m : Nat) : Either String Nat
```

## def nat_mod_checked

```ouro
def nat_mod_checked (n : Nat) (m : Nat) : Either String Nat
```

## def nat_range_count

```ouro
def nat_range_count (start : Nat) (count : Nat) : List Nat
```

## def nat_range_closed

```ouro
def nat_range_closed (lo : Nat) (hi : Nat) : List Nat
```

## def nat_sum

```ouro
def nat_sum (xs : List Nat) : Nat
```

## def nat_product

```ouro
def nat_product (xs : List Nat) : Nat
```

## def nat_min_list

```ouro
def nat_min_list (fallback : Nat) (xs : List Nat) : Nat
```

## def nat_max_list

```ouro
def nat_max_list (fallback : Nat) (xs : List Nat) : Nat
```

## def nat_count

```ouro
def nat_count (p : Nat -> Bool) (xs : List Nat) : Nat
```

## def nat_mean_floor

```ouro
def nat_mean_floor (xs : List Nat) : Nat
```
