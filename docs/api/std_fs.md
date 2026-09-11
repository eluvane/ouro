# std/fs.ouro

Filesystem helpers expose raw runtime prims plus checked wrappers that return Either FsError A with stable error codes.

Declarations: 38.

## def fs_read

```
def fs_read (path : String) : IO String
```

## def fs_write

```
def fs_write (path : String) (content : String) : IO Unit
```

## def fs_exists

```
def fs_exists (path : String) : IO Bool
```

## def fs_is_dir

```
def fs_is_dir (path : String) : IO Bool
```

## def fs_list

```
def fs_list (path : String) : IO (List String)
```

## def fs_mkdir_p

```
def fs_mkdir_p (path : String) : IO Unit
```

## def fs_remove

```
def fs_remove (path : String) : IO Unit
```

## def fs_copy

```
def fs_copy (src : String) (dst : String) : IO Unit
```

## def fs_write_deep

```
def fs_write_deep (path : String) (content : String) : IO Unit
```

Create the directory a file lives in before writing it.

## def fs_copy_deep

```
def fs_copy_deep (src : String) (dst : String) : IO Unit
```

## def fs_append

```
def fs_append (path : String) (extra : String) : IO Unit
```

## def fs_read_lines

```
def fs_read_lines (path : String) : IO (List String)
```

## def fs_write_lines

```
def fs_write_lines (path : String) (ls : List String) : IO Unit
```

## def fs_child

```
def fs_child (dir : String) (name : String) : String
```

Directory entries as full paths, in the order the host reported them.

## def fs_list_paths

```
def fs_list_paths (dir : String) : IO (List String)
```

## def fs_walk_go

```
def fs_walk_go : Nat -> List String -> List String
```

Recursive inventory remains compact for common tools while failing closed: exhaustion, unreadable entries, and links/reparse points return no partial list.

## def fs_walk_fuel

```
def fs_walk_fuel : Nat
```

## def fs_walk

```
def fs_walk (root : String) : IO (List String)
```

## def fs_walk_ouro

```
def fs_walk_ouro (root : String) : IO (List String)
```

Only the .ouro files under a root, sorted is not promised.

## inductive FsError

```
inductive FsError : Type
```

## def fs_error_code

```
def fs_error_code (e : FsError) : String
```

## def fs_error_path

```
def fs_error_path (e : FsError) : String
```

## def fs_error_message

```
def fs_error_message (e : FsError) : String
```

## def fs_ok

```
def fs_ok (A : Type) (x : A) : IO (Either FsError A)
```

## def fs_err

```
def fs_err (A : Type) (e : FsError) : IO (Either FsError A)
```

## def fs_nonempty_path

```
def fs_nonempty_path (path : String) : Either FsError Unit
```

## def fs_is_file

```
def fs_is_file (path : String) : IO Bool
```

## def fs_file_exists

```
def fs_file_exists (path : String) : IO Bool
```

## def fs_dir_exists

```
def fs_dir_exists (path : String) : IO Bool
```

## def fs_check_file

```
def fs_check_file (path : String) : IO (Either FsError Unit)
```

## def fs_check_dir

```
def fs_check_dir (path : String) : IO (Either FsError Unit)
```

## def fs_read_checked

```
def fs_read_checked (path : String) : IO (Either FsError String)
```

## def fs_write_checked

```
def fs_write_checked (path : String) (content : String) : IO (Either FsError Unit)
```

## def fs_append_checked

```
def fs_append_checked (path : String) (extra : String) : IO (Either FsError Unit)
```

## def fs_mkdir_p_checked

```
def fs_mkdir_p_checked (path : String) : IO (Either FsError Unit)
```

## def fs_list_checked

```
def fs_list_checked (path : String) : IO (Either FsError (List String))
```

## def fs_copy_checked

```
def fs_copy_checked (src : String) (dst : String) : IO (Either FsError Unit)
```

## def fs_rename_checked

```
def fs_rename_checked (src : String) (dst : String) : IO (Either FsError Unit)
```

Replace a destination by a same-volume rename, preserving the OS verdict. Parents must already exist; failure never falls back to copy or delete.
