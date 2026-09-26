# std/iter.ouro

Pure pull iterators with explicit failure and bounded materialization.

Declarations: 8.

## inductive IterStep

```
inductive IterStep (State : Type) (Error : Type) (Item : Type) : Type
```

## inductive Iterator

```
inductive Iterator (State : Type) (Error : Type) (Item : Type) : Type
```

## inductive IterCollectError

```
inductive IterCollectError (Error : Type) : Type
```

## def iter_from_list

```
def iter_from_list (Error : Type) (Item : Type) (xs : List Item)
```

## def iter_map

```
def iter_map (State : Type) (Error : Type) (Item : Type) (Mapped : Type)
```

## def iter_filter

```
def iter_filter (State : Type) (Error : Type) (Item : Type)
```

## def iter_take

```
def iter_take (State : Type) (Error : Type) (Item : Type)
```

## def collect_list

```
def collect_list (State : Type) (Error : Type) (Item : Type)
```
