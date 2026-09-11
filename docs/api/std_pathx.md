# std/pathx.ouro

Path helpers use POSIX spelling because package and doc artifacts store slash paths.

Declarations: 27.

## def path_sep

```
def path_sep : Nat
```

## def path_dot

```
def path_dot : Nat
```

## def path_from_host

```
def path_from_host (p : String) : String
```

Host paths may use backslashes; package and doc artifacts store slashes.

## def path_split

```
def path_split (p : String) : List String
```

## def path_join

```
def path_join (parts : List String) : String
```

## def path_has_drive

```
def path_has_drive (p : String) : Bool
```

## def path_is_abs

```
def path_is_abs (p : String) : Bool
```

## def path_basename

```
def path_basename (p : String) : String
```

## def path_dirname

```
def path_dirname (p : String) : String
```

## def path_ext

```
def path_ext (p : String) : String
```

The extension includes its dot ("lib.ouro" -> ".ouro"), which is what path_has_ext and std/gate/share.ouro compare against. A leading dot is a hidden file, not an extension, so ".gitignore" has none.

## def path_stem

```
def path_stem (p : String) : String
```

## def path_has_ext

```
def path_has_ext (p : String) (ext : String) : Bool
```

## def path_ends_ouro

```
def path_ends_ouro (p : String) : Bool
```

## def path_ends_sh

```
def path_ends_sh (p : String) : Bool
```

## def path_ends_py

```
def path_ends_py (p : String) : Bool
```

## def path_ends_ml

```
def path_ends_ml (p : String) : Bool
```

## def path_ends_js

```
def path_ends_js (p : String) : Bool
```

## def path_is_code

```
def path_is_code (p : String) : Bool
```

## def path_under

```
def path_under (prefix : String) (p : String) : Bool
```

True when `p` is `prefix` itself or a descendant after a `/` boundary. `"a"` does not contain `"apple"`; a prefix that already ends in `/` is the boundary.

## def path_relative

```
def path_relative (root : String) (p : String) : String
```

`p` with a leading `root` and the separator after it removed; `p` unchanged when it does not sit at or below root. Used to rebuild a tree under a new root.

## def path_skip_build

```
def path_skip_build (p : String) : Bool
```

## def path_norm_pop

```
def path_norm_pop (absolute : Bool) (acc : List String) : List String
```

## def path_norm_step

```
def path_norm_step (absolute : Bool) (seg : String) (acc : List String) : List String
```

## def path_normalize_go

```
def path_normalize_go (absolute : Bool) (parts : List String)
```

## def path_normalize

```
def path_normalize (p : String) : String
```

Preserve a Windows drive prefix instead of rewriting `C:/...` as `/C:/...`.

## def path_join_normalized

```
def path_join_normalized (parts : List String) : String
```

## def path_resolve_from_file

```
def path_resolve_from_file (base : String) (spell : String) : String
```
