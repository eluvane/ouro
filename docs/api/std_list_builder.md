# std/list_builder.ouro

Declarations: 4.

## inductive ListBuilder

```
inductive ListBuilder (A : Type) : Type
```

Persistent builder with reversed storage. Push is constant time; finish restores insertion order in linear time.

## def list_builder_empty

```
def list_builder_empty (A : Type) : ListBuilder A
```

## def list_builder_push

```
def list_builder_push (A : Type) (value : A)
```

## def list_builder_finish

```
def list_builder_finish (A : Type) (builder : ListBuilder A) : List A
```
