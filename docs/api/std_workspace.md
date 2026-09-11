# std/workspace.ouro

Workspace, temp-path, backup, and file workflow helpers.

Declarations: 23.

## inductive Workspace

```
inductive Workspace : Type
```

## def workspace_root

```
def workspace_root (w : Workspace) : String
```

## def workspace_file

```
def workspace_file (w : Workspace) (relative : String) : String
```

## def workspace_dir

```
def workspace_dir (w : Workspace) (relative : String) : String
```

## def workspace_make

```
def workspace_make (root : String) : IO (Either FsError Workspace)
```

## def workspace_ensure_dir

```
def workspace_ensure_dir (w : Workspace) (relative : String) : IO (Either FsError Unit)
```

## def workspace_read_text

```
def workspace_read_text (w : Workspace) (relative : String) : IO (Either FsError String)
```

## def workspace_write_text

```
def workspace_write_text (w : Workspace) (relative : String) (content : String) : IO (Either FsError Unit)
```

## def workspace_write_lines

```
def workspace_write_lines (w : Workspace) (relative : String) (lines : List String) : IO (Either FsError Unit)
```

## def workspace_list

```
def workspace_list (w : Workspace) (relative : String) : IO (Either FsError (List String))
```

## def workspace_temp_path

```
def workspace_temp_path (w : Workspace) (name : String) : String
```

## def workspace_timestamped_temp_path

```
def workspace_timestamped_temp_path (w : Workspace) (prefix : String) (suffix : String) : IO String
```

## def workspace_write_temp_text

```
def workspace_write_temp_text (w : Workspace) (prefix : String) (suffix : String) (content : String) : IO (Either FsError String)
```

## def fsx_backup_path

```
def fsx_backup_path (path : String) : String
```

## def fsx_backup_before_overwrite

```
def fsx_backup_before_overwrite (path : String) : IO (Either FsError Unit)
```

## def fsx_write_backup_checked

```
def fsx_write_backup_checked (path : String) (content : String) : IO (Either FsError Unit)
```

## def fsx_read_transform_write_checked

```
def fsx_read_transform_write_checked (src : String) (dst : String) (f : String -> String) : IO (Either FsError Unit)
```

## def fsx_list_files_filtered

```
def fsx_list_files_filtered (root : String) (p : String -> Bool) : IO (Either FsError (List String))
```

## def fsx_list_files_by_ext

```
def fsx_list_files_by_ext (root : String) (ext : String) : IO (Either FsError (List String))
```

## def fsx_copy_one_under

```
def fsx_copy_one_under (src_root : String) (dst_root : String) (state : Either FsError Unit) (path : String) : IO (Either FsError Unit)
```

## def fsx_copy_tree_checked

```
def fsx_copy_tree_checked (src_root : String) (dst_root : String) : IO (Either FsError Unit)
```

## def fsx_remove_tree_checked

```
def fsx_remove_tree_checked (root : String) : IO (Either FsError Unit)
```

Delete files first, then directories, then the root. Fuel bounds directory depth; exhaustion is an error instead of a silent leftover tree.

## def workspace_report

```
def workspace_report (w : Workspace) : Report
```
