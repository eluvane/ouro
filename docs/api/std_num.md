# std/num.ouro

Numeric helpers for small data-processing programs.

Declarations: 21.

## def nat_eq

```
def nat_eq (a : Nat) (b : Nat) : Bool
```

## def nat_ne

```
def nat_ne (a : Nat) (b : Nat) : Bool
```

## def nat_lt

```
def nat_lt (a : Nat) (b : Nat) : Bool
```

## def nat_le

```
def nat_le (a : Nat) (b : Nat) : Bool
```

## def nat_gt

```
def nat_gt (a : Nat) (b : Nat) : Bool
```

## def nat_ge

```
def nat_ge (a : Nat) (b : Nat) : Bool
```

## def nat_compare

```
def nat_compare (a : Nat) (b : Nat) : Ordering
```

## def nat_min

```
def nat_min (a : Nat) (b : Nat) : Nat
```

## def nat_max

```
def nat_max (a : Nat) (b : Nat) : Nat
```

## def nat_clamp

```
def nat_clamp (lo : Nat) (hi : Nat) (x : Nat) : Nat
```

## def nat_nonzero

```
def nat_nonzero (n : Nat) : Bool
```

## def nat_div_checked

```
def nat_div_checked (n : Nat) (m : Nat) : Either String Nat
```

## def nat_mod_checked

```
def nat_mod_checked (n : Nat) (m : Nat) : Either String Nat
```

## def nat_range_count

```
def nat_range_count (start : Nat) (count : Nat) : List Nat
```

## def nat_range_closed

```
def nat_range_closed (lo : Nat) (hi : Nat) : List Nat
```

## def nat_sum

```
def nat_sum (xs : List Nat) : Nat
```

## def nat_product

```
def nat_product (xs : List Nat) : Nat
```

## def nat_min_list

```
def nat_min_list (fallback : Nat) (xs : List Nat) : Nat
```

## def nat_max_list

```
def nat_max_list (fallback : Nat) (xs : List Nat) : Nat
```

## def nat_count

```
def nat_count (p : Nat -> Bool) (xs : List Nat) : Nat
```

## def nat_mean_floor

```
def nat_mean_floor (xs : List Nat) : Nat
```
