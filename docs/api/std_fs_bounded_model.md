# std/fs_bounded_model.ouro

Declarations: 5.

## inductive FsBoundedReadError

```ouro
inductive FsBoundedReadError : Type
```

## def fs_bounded_read_error_code

```ouro
def fs_bounded_read_error_code (error : FsBoundedReadError) : String
```

## def fs_bounded_read_error_message

```ouro
def fs_bounded_read_error_message (error : FsBoundedReadError) : String
```

## def fs_bounded_read_path_length

```ouro
def fs_bounded_read_path_length (path : String) (capacity : Nat) : Either FsBoundedReadError Nat
```

## def fs_bounded_read_length

```ouro
def fs_bounded_read_length (cap : Nat) (size : Nat) : Either FsBoundedReadError Nat
```
