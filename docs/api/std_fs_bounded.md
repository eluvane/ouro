# std/fs_bounded.ouro

Declarations: 1.

## def fs_read_bounded_checked

```ouro
def fs_read_bounded_checked (cap : Nat) (path : String) : IO (Either FsBoundedReadError String)
```

Read a regular file on native Windows x86-64. `cap` limits content bytes. The reader checks the size before allocating content storage. An empty file fits a zero cap. Success preserves all bytes, including NUL. A file over the cap, a directory, a final reparse point, a size change, or an OS read failure returns `FsBoundedReadError`. Same-size rewrites can go undetected. Raw allocation failures, adapter storage or progress guards, and cleanup failures exit with status 73.
