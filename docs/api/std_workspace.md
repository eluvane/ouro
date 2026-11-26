# std/workspace.ouro

Workspace, temp-path, backup, and file workflow helpers.

Declarations: 23.

## inductive Workspace

```ouro
inductive Workspace : Type
```

## def workspace_root

```ouro
def workspace_root (w : Workspace) : String
```

## def workspace_file

```ouro
def workspace_file (w : Workspace) (relative : String) : String
```

This lexical join preserves both path strings as given. Validate the result separately when it must stay under the workspace root.

## def workspace_dir

```ouro
def workspace_dir (w : Workspace) (relative : String) : String
```

## def workspace_make

```ouro
def workspace_make (root : String) : IO (Either FsError Workspace)
```

## def workspace_ensure_dir

```ouro
def workspace_ensure_dir (w : Workspace) (relative : String) : IO (Either FsError Unit)
```

## def workspace_read_text

```ouro
def workspace_read_text (w : Workspace) (relative : String) : IO (Either FsError String)
```

## def workspace_write_text

```ouro
def workspace_write_text (w : Workspace) (relative : String) (content : String) : IO (Either FsError Unit)
```

## def workspace_write_lines

```ouro
def workspace_write_lines (w : Workspace) (relative : String) (lines : List String) : IO (Either FsError Unit)
```

## def workspace_list

```ouro
def workspace_list (w : Workspace) (relative : String) : IO (Either FsError (List String))
```

## def workspace_temp_path

```ouro
def workspace_temp_path (w : Workspace) (name : String) : String
```

## def workspace_timestamped_temp_path

```ouro
def workspace_timestamped_temp_path (w : Workspace) (prefix : String) (suffix : String) : IO String
```

## def workspace_write_temp_text

```ouro
def workspace_write_temp_text (w : Workspace) (prefix : String) (suffix : String) (content : String) : IO (Either FsError String)
```

## def fsx_backup_path

```ouro
def fsx_backup_path (path : String) : String
```

## def fsx_backup_before_overwrite

```ouro
def fsx_backup_before_overwrite (path : String) : IO (Either FsError Unit)
```

## def fsx_write_backup_checked

```ouro
def fsx_write_backup_checked (path : String) (content : String) : IO (Either FsError Unit)
```

## def fsx_read_transform_write_checked

```ouro
def fsx_read_transform_write_checked (src : String) (dst : String) (f : String -> String) : IO (Either FsError Unit)
```

## def fsx_list_files_filtered

```ouro
def fsx_list_files_filtered (root : String) (p : String -> Bool) : IO (Either FsError (List String))
```

## def fsx_list_files_by_ext

```ouro
def fsx_list_files_by_ext (root : String) (ext : String) : IO (Either FsError (List String))
```

## def fsx_copy_one_under

```ouro
def fsx_copy_one_under (src_root : String) (dst_root : String) (state : Either FsError Unit) (path : String) : IO (Either FsError Unit)
```

## def fsx_copy_tree_checked

```ouro
def fsx_copy_tree_checked (src_root : String) (dst_root : String) : IO (Either FsError Unit)
```

## def fsx_remove_tree_checked

```ouro
def fsx_remove_tree_checked (root : String) : IO (Either FsError Unit)
```

Remove children before their parent directory. Return success without removing entries if the initial root check reports `FsPathUnavailable`. An unavailable entry during traversal returns an error. Exceeding the depth limit also returns an error. Earlier deletions remain in place.

## def workspace_report

```ouro
def workspace_report (w : Workspace) : Report
```
