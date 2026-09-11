# std/record_demo.ouro

Record demo is restricted to forms the direct packaged frontend already accepts.

Declarations: 6.

## inductive Nat

```
inductive Nat : Type
```

## record Point

```
record Point : Type where
```

## def origin

```
def origin : Point
```

## def get_x

```
def get_x (p : Point) : Nat
```

## def get_y

```
def get_y (p : Point) : Nat
```

## def swap

```
def swap (p : Point) : Point
```
