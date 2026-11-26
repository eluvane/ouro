# std/record_demo.ouro

Record literals and field projections for a point with two `Nat` coordinates.

Declarations: 6.

## inductive Nat

```ouro
inductive Nat : Type
```

## record Point

```ouro
record Point : Type where
```

## def origin

```ouro
def origin : Point
```

## def get_x

```ouro
def get_x (p : Point) : Nat
```

## def get_y

```ouro
def get_y (p : Point) : Nat
```

## def swap

```ouro
def swap (p : Point) : Point
```
