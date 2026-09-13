# std/fs_create.ouro

Declarations: 1.

## def fs_create_dir_exclusive_checked

```
def fs_create_dir_exclusive_checked (path : String) : IO (Either FsCreateDirError Unit)
```

Create only the final directory. Existing files/directories and missing parents are errors. No exists/mkdir-p fallback, retry, removal or rollback. A cleanup error retains whether the directory was already created.
