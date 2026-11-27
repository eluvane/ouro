# std/fs.ouro

Filesystem helpers expose raw runtime prims plus checked wrappers that return Either FsError A with stable error codes.

Declarations: 40.

## def fs_read

```ouro
def fs_read (path : String) : IO String
```

## def fs_write

```ouro
def fs_write (path : String) (content : String) : IO Unit
```

## def fs_exists

```ouro
def fs_exists (path : String) : IO Bool
```

## def fs_is_dir

```ouro
def fs_is_dir (path : String) : IO Bool
```

## def fs_list

```ouro
def fs_list (path : String) : IO (List String)
```

## def fs_mkdir_p

```ouro
def fs_mkdir_p (path : String) : IO Unit
```

## def fs_remove

```ouro
def fs_remove (path : String) : IO Unit
```

## def fs_copy

```ouro
def fs_copy (src : String) (dst : String) : IO Unit
```

## def fs_write_deep

```ouro
def fs_write_deep (path : String) (content : String) : IO Unit
```

Create the directory a file lives in before writing it.

## def fs_copy_deep

```ouro
def fs_copy_deep (src : String) (dst : String) : IO Unit
```

## def fs_append

```ouro
def fs_append (path : String) (extra : String) : IO Unit
```

## def fs_read_lines

```ouro
def fs_read_lines (path : String) : IO (List String)
```

## def fs_write_lines

```ouro
def fs_write_lines (path : String) (ls : List String) : IO Unit
```

## def fs_child

```ouro
def fs_child (dir : String) (name : String) : String
```

## def fs_list_paths

```ouro
def fs_list_paths (dir : String) : IO (List String)
```

Join the directory path with each entry name. Preserve the host entry order.

## def fs_walk_go

```ouro
def fs_walk_go : Nat -> List String -> List String
    -> IO (Maybe (List String))
```

The walk returns no partial list on budget exhaustion, unreadable paths, links, or reparse points.

## def fs_walk_fuel

```ouro
def fs_walk_fuel : Nat
```

## def fs_walk

```ouro
def fs_walk (root : String) : IO (List String)
```

## def fs_walk_ouro

```ouro
def fs_walk_ouro (root : String) : IO (List String)
```

Only the .ouro files under a root, sorted is not promised.

## inductive FsError

```ouro
inductive FsError : Type
```

## def fs_error_code

```ouro
def fs_error_code (e : FsError) : String
```

## def fs_error_path

```ouro
def fs_error_path (e : FsError) : String
```

## def fs_error_message

```ouro
def fs_error_message (e : FsError) : String
```

## def fs_ok

```ouro
def fs_ok (A : Type) (x : A) : IO (Either FsError A)
```

## def fs_err

```ouro
def fs_err (A : Type) (e : FsError) : IO (Either FsError A)
```

## def fs_nonempty_path

```ouro
def fs_nonempty_path (path : String) : Either FsError Unit
```

## inductive FsPathKind

```ouro
inductive FsPathKind : Type
```

No-follow classification; an OS query failure does not establish absence.

## def fs_kind_checked

```ouro
def fs_kind_checked (path : String) : IO (Either FsError FsPathKind)
```

Empty paths fail. Links, reparse points and unknown kinds remain unsafe.

## def fs_is_file

```ouro
def fs_is_file (path : String) : IO Bool
```

## def fs_file_exists

```ouro
def fs_file_exists (path : String) : IO Bool
```

## def fs_dir_exists

```ouro
def fs_dir_exists (path : String) : IO Bool
```

## def fs_check_file

```ouro
def fs_check_file (path : String) : IO (Either FsError Unit)
```

## def fs_check_dir

```ouro
def fs_check_dir (path : String) : IO (Either FsError Unit)
```

## def fs_read_checked

```ouro
def fs_read_checked (path : String) : IO (Either FsError String)
```

After the precheck, OS open/length/read errors become FsOperationFailed. Partial bytes are never success; malformed text, guards and cleanup exit 73.

## def fs_write_checked

```ouro
def fs_write_checked (path : String) (content : String) : IO (Either FsError Unit)
```

## def fs_append_checked

```ouro
def fs_append_checked (path : String) (extra : String) : IO (Either FsError Unit)
```

## def fs_mkdir_p_checked

```ouro
def fs_mkdir_p_checked (path : String) : IO (Either FsError Unit)
```

## def fs_list_checked

```ouro
def fs_list_checked (path : String) : IO (Either FsError (List String))
```

## def fs_copy_checked

```ouro
def fs_copy_checked (src : String) (dst : String) : IO (Either FsError Unit)
```

## def fs_rename_checked

```ouro
def fs_rename_checked (src : String) (dst : String) : IO (Either FsError Unit)
```

Replace a destination by a same-volume rename, preserving the OS verdict. Parents must already exist; failure never falls back to copy or delete.
