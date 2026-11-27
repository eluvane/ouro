# std/range.ouro

Finite Nat ranges as bounded pull sources.

Declarations: 12.

## inductive NatRangeBound

```ouro
inductive NatRangeBound : Type
```

## inductive NatRange

```ouro
inductive NatRange : Type
```

## inductive NatRangeError

```ouro
inductive NatRangeError : Type
```

## inductive NatRangeCursor

```ouro
inductive NatRangeCursor : Type
```

## def nat_range_exclusive

```ouro
def nat_range_exclusive (start : Nat) (stop : Nat) : NatRange
```

## def nat_range_inclusive

```ouro
def nat_range_inclusive (start : Nat) (stop : Nat) : NatRange
```

## def nat_range_by

```ouro
def nat_range_by (step : Nat) (range : NatRange)
    : Either NatRangeError NatRange
```

## def nat_range_at_stop

```ouro
def nat_range_at_stop (bound : NatRangeBound) : Bool
```

## def nat_range_in_bounds

```ouro
def nat_range_in_bounds (range : NatRange) (current : Nat) : Bool
```

## def nat_range_next

```ouro
def nat_range_next (range : NatRange) (current : Nat) : Maybe Nat
```

Ascending steps avoid copying the distance to a large endpoint. Descending steps check that distance before Nat's saturating subtraction.

## def nat_range_pull

```ouro
def nat_range_pull (cursor : NatRangeCursor)
    : IterStep NatRangeCursor NatRangeError Nat
```

## def iter_from_nat_range

```ouro
def iter_from_nat_range (range : NatRange)
    : Either NatRangeError
        (Iterator NatRangeCursor NatRangeError Nat)
```
