# std/fs_create_model.ouro

Declarations: 9.

## inductive FsCreateDirError

```
inductive FsCreateDirError : Type
```

## def fs_create_dir_error_code

```
def fs_create_dir_error_code (error : FsCreateDirError) : String
```

## def fs_create_dir_error_message

```
def fs_create_dir_error_message (error : FsCreateDirError) : String
```

## def fs_create_dir_error_created

```
def fs_create_dir_error_created (error : FsCreateDirError) : Bool
```

## def fs_create_dir_was_created

```
def fs_create_dir_was_created (result : Either FsCreateDirError Unit) : Bool
```

Right and a cleanup failure after successful creation both retain the claim. This reports the operation's result, not an enduring handle to a path name.

## def fs_create_dir_path_length

```
def fs_create_dir_path_length (path : String) (capacity : Nat) : Either FsCreateDirError Nat
```

Byte bounds and NUL rejection precede raw allocation. UTF-8 validity is checked by the strict platform converter before any directory call.

## def fs_create_dir_wide_count

```
def fs_create_dir_wide_count (actual : Nat) (capacity : Nat) : Either FsCreateDirError Nat
```

Capacity includes the two-byte terminator, which is written separately.

## def fs_create_dir_result

```
def fs_create_dir_result (created : Bool) : Either FsCreateDirError Unit
```

## def fs_create_dir_released

```
def fs_create_dir_released (result : Either FsCreateDirError Unit) (released : Bool)
```

A release failure never becomes Right and never loses an earlier claim/error.
