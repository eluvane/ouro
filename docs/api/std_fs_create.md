# std/fs_create.ouro

Declarations: 1.

## def fs_create_dir_exclusive_checked

```ouro
def fs_create_dir_exclusive_checked (path : String) : IO (Either FsCreateDirError Unit)
```

Create only the final directory on the Windows native backend. The parent must exist and the target must be absent. The operation makes one creation attempt. A cleanup error records whether that attempt created the directory.
