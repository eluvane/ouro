# std/range.ouro

Finite Nat ranges as bounded pull sources.

Declarations: 12.

## inductive NatRangeBound

```
inductive NatRangeBound : Type
```

## inductive NatRange

```
inductive NatRange : Type
```

## inductive NatRangeError

```
inductive NatRangeError : Type
```

## inductive NatRangeCursor

```
inductive NatRangeCursor : Type
```

## def nat_range_exclusive

```
def nat_range_exclusive (start : Nat) (stop : Nat) : NatRange
```

## def nat_range_inclusive

```
def nat_range_inclusive (start : Nat) (stop : Nat) : NatRange
```

## def nat_range_by

```
def nat_range_by (step : Nat) (range : NatRange)
```

## def nat_range_at_stop

```
def nat_range_at_stop (bound : NatRangeBound) : Bool
```

## def nat_range_in_bounds

```
def nat_range_in_bounds (range : NatRange) (current : Nat) : Bool
```

## def nat_range_next

```
def nat_range_next (range : NatRange) (current : Nat) : Maybe Nat
```

Compare the step with the remaining distance before subtracting. This prevents Nat's saturating subtraction from creating a false zero item.

## def nat_range_pull

```
def nat_range_pull (cursor : NatRangeCursor)
```

## def iter_from_nat_range

```
def iter_from_nat_range (range : NatRange)
```
