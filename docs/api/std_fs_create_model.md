# std/fs_create_model.ouro

Declarations: 9.

## inductive FsCreateDirError

```ouro
inductive FsCreateDirError : Type
```

## def fs_create_dir_error_code

```ouro
def fs_create_dir_error_code (error : FsCreateDirError) : String
```

## def fs_create_dir_error_message

```ouro
def fs_create_dir_error_message (error : FsCreateDirError) : String
```

## def fs_create_dir_error_created

```ouro
def fs_create_dir_error_created (error : FsCreateDirError) : Bool
```

## def fs_create_dir_was_created

```ouro
def fs_create_dir_was_created (result : Either FsCreateDirError Unit) : Bool
```

Right and a cleanup failure after successful creation both retain the claim. This reports the operation's result, not an enduring handle to a path name.

## def fs_create_dir_path_length

```ouro
def fs_create_dir_path_length (path : String) (capacity : Nat) : Either FsCreateDirError Nat
```

Byte bounds and NUL rejection precede raw allocation. UTF-8 validity is checked by the strict platform converter before any directory call.

## def fs_create_dir_wide_count

```ouro
def fs_create_dir_wide_count (actual : Nat) (capacity : Nat) : Either FsCreateDirError Nat
```

Capacity includes the two-byte terminator, which is written separately.

## def fs_create_dir_result

```ouro
def fs_create_dir_result (created : Bool) : Either FsCreateDirError Unit
```

## def fs_create_dir_released

```ouro
def fs_create_dir_released (result : Either FsCreateDirError Unit) (released : Bool)
    : Either FsCreateDirError Unit
```

A release failure never becomes Right and never loses an earlier claim/error.
