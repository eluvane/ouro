# std/fs_replace.ouro

Declarations: 3.

## intrinsic prim_fs_replace_file

```ouro
intrinsic prim_fs_replace_file : String -> String -> String -> IO Nat
```

Zero denotes publication. A nonzero result carries the provider status.

## inductive FsReplaceResult

```ouro
inductive FsReplaceResult : Type
```

## def fs_replace_file

```ouro
def fs_replace_file (source : String) (stage : String) (backup : String) : IO FsReplaceResult
```

Replace `source` with `stage`. All three paths must name distinct ordinary files with one link each on the same volume. `backup` must be a private, empty reservation. An empty path returns `FsReplaceFailed 87`. Inspect all three paths after a failure before attempting recovery. Verify the installed bytes before removing the backup.
