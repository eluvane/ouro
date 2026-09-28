# std/iter.ouro

Pure pull iterators with explicit failure and bounded materialization.

Declarations: 9.

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
    : Iterator (List Item) Error Item
```

## def iter_map

```
def iter_map (State : Type) (Error : Type) (Item : Type) (Mapped : Type)
    (convert : Item -> Mapped) (source : Iterator State Error Item)
    : Iterator State Error Mapped
```

## def iter_filter

```
def iter_filter (State : Type) (Error : Type) (Item : Type)
    (accept : Item -> Bool) (source : Iterator State Error Item)
    : Iterator State Error Item
```

## def iter_take

```
def iter_take (State : Type) (Error : Type) (Item : Type)
    (count : Nat) (source : Iterator State Error Item)
    : Iterator (Pair Nat State) Error Item
```

## def collect_list

```
def collect_list (State : Type) (Error : Type) (Item : Type)
    (max_pulls : Nat) (source : Iterator State Error Item)
    : Either (IterCollectError Error) (List Item)
```

## def iter_fold

```
def iter_fold (State : Type) (Error : Type) (Item : Type) (Acc : Type)
    (step : Acc -> Item -> Acc) (initial : Acc) (max_pulls : Nat)
    (source : Iterator State Error Item)
    : Either (IterCollectError Error) Acc
```
