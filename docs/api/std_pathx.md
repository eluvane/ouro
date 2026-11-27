# std/pathx.ouro

Path helpers use POSIX spelling because package and doc artifacts store slash paths.

Declarations: 27.

## def path_sep

```ouro
def path_sep : Nat
```

## def path_dot

```ouro
def path_dot : Nat
```

## def path_from_host

```ouro
def path_from_host (p : String) : String
```

Host paths may use backslashes; package and doc artifacts store slashes.

## def path_split

```ouro
def path_split (p : String) : List String
```

## def path_join

```ouro
def path_join (parts : List String) : String
```

## def path_has_drive

```ouro
def path_has_drive (p : String) : Bool
```

## def path_is_abs

```ouro
def path_is_abs (p : String) : Bool
```

## def path_basename

```ouro
def path_basename (p : String) : String
```

## def path_dirname

```ouro
def path_dirname (p : String) : String
```

## def path_ext

```ouro
def path_ext (p : String) : String
```

The extension includes its dot ("lib.ouro" -> ".ouro"), which is what path_has_ext and std/gate/share.ouro compare against. A leading dot is a hidden file, not an extension, so ".gitignore" has none.

## def path_stem

```ouro
def path_stem (p : String) : String
```

## def path_has_ext

```ouro
def path_has_ext (p : String) (ext : String) : Bool
```

## def path_ends_ouro

```ouro
def path_ends_ouro (p : String) : Bool
```

## def path_ends_sh

```ouro
def path_ends_sh (p : String) : Bool
```

## def path_ends_py

```ouro
def path_ends_py (p : String) : Bool
```

## def path_ends_ml

```ouro
def path_ends_ml (p : String) : Bool
```

## def path_ends_js

```ouro
def path_ends_js (p : String) : Bool
```

## def path_is_code

```ouro
def path_is_code (p : String) : Bool
```

## def path_under

```ouro
def path_under (prefix : String) (p : String) : Bool
```

True when `p` is `prefix` itself or a descendant after a `/` boundary. `"a"` does not contain `"apple"`; a prefix that already ends in `/` is the boundary.

## def path_relative

```ouro
def path_relative (root : String) (p : String) : String
```

`p` with a leading `root` and the separator after it removed; `p` unchanged when it does not sit at or below root. Used to rebuild a tree under a new root.

## def path_skip_build

```ouro
def path_skip_build (p : String) : Bool
```

## def path_norm_pop

```ouro
def path_norm_pop (absolute : Bool) (acc : List String) : List String
```

## def path_norm_step

```ouro
def path_norm_step (absolute : Bool) (seg : String) (acc : List String) : List String
```

## def path_normalize_go

```ouro
def path_normalize_go (absolute : Bool) (parts : List String)
    (acc : List String) : List String
```

## def path_normalize

```ouro
def path_normalize (p : String) : String
```

Preserve a Windows drive prefix instead of rewriting `C:/...` as `/C:/...`.

## def path_join_normalized

```ouro
def path_join_normalized (parts : List String) : String
```

## def path_resolve_from_file

```ouro
def path_resolve_from_file (base : String) (spell : String) : String
```
