# std/fs_replace.ouro

Declarations: 3.

## intrinsic prim_fs_replace_file

```
intrinsic prim_fs_replace_file : String -> String -> String -> IO Nat
```

Separate from std/runtime so the compiler's closed primitive catalog can bootstrap before a consumer declares this newly added operation.

## inductive FsReplaceResult

```
inductive FsReplaceResult : Type
```

## def fs_replace_file

```
def fs_replace_file (source : String) (stage : String) (backup : String) : IO FsReplaceResult
```
