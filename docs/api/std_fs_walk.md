# std/fs_walk.ouro

Detailed checked-walk status for security-sensitive inventory callers.

Declarations: 7.

## inductive FsWalkResult

```
inductive FsWalkResult : Type
```

## def fs_walk_map

```
def fs_walk_map (f : List String -> List String) (r : FsWalkResult)
```

## def fs_walk_message

```
def fs_walk_message (r : FsWalkResult) : String
```

## def fs_walk_path_safe

```
def fs_walk_path_safe (root_real : String) (path : String) : IO Bool
```

## def fs_walk_checked_go

```
def fs_walk_checked_go : Nat -> String -> List String -> List String
```

The budget counts every visited entry. Children are sorted; links, reparse points, canonical escapes, unreadable directories, and exhaustion are explicit.

## def fs_walk_checked

```
def fs_walk_checked (root : String) : IO FsWalkResult
```

## def fs_walk_ouro_checked

```
def fs_walk_ouro_checked (root : String) : IO FsWalkResult
```
