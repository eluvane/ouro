# std/fs_walk.ouro

Detailed checked-walk status for security-sensitive inventory callers.

Declarations: 7.

## inductive FsWalkResult

```ouro
inductive FsWalkResult : Type
```

## def fs_walk_map

```ouro
def fs_walk_map (f : List String -> List String) (r : FsWalkResult)
    : FsWalkResult
```

## def fs_walk_message

```ouro
def fs_walk_message (r : FsWalkResult) : String
```

## def fs_walk_path_safe

```ouro
def fs_walk_path_safe (root_real : String) (path : String) : IO Bool
```

## def fs_walk_checked_go

```ouro
def fs_walk_checked_go : Nat -> String -> List String -> List String
    -> IO FsWalkResult
```

The budget counts every visited entry. Children are sorted; links, reparse points, canonical escapes, unreadable directories, and exhaustion are explicit.

## def fs_walk_checked

```ouro
def fs_walk_checked (root : String) : IO FsWalkResult
```

## def fs_walk_ouro_checked

```ouro
def fs_walk_ouro_checked (root : String) : IO FsWalkResult
```
