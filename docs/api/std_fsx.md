# std/fsx.ouro

Higher-level checked filesystem helpers built from std/fs.

Declarations: 11.

## def fsx_read_text

```ouro
def fsx_read_text (path : String) : IO (Either FsError String)
```

## def fsx_write_text

```ouro
def fsx_write_text (path : String) (content : String) : IO (Either FsError Unit)
```

## def fsx_read_lines

```ouro
def fsx_read_lines (path : String) : IO (Either FsError (List String))
```

## def fsx_write_lines

```ouro
def fsx_write_lines (path : String) (lines : List String)
    : IO (Either FsError Unit)
```

## def fsx_append_line

```ouro
def fsx_append_line (path : String) (line : String) : IO (Either FsError Unit)
```

## def fsx_remove_if_exists

```ouro
def fsx_remove_if_exists (path : String) : IO (Either FsError Unit)
```

## def fsx_list_matching

```ouro
def fsx_list_matching (dir : String) (p : String -> Bool)
    : IO (Either FsError (List String))
```

## def fsx_list_full_matching

```ouro
def fsx_list_full_matching (dir : String) (p : String -> Bool)
    : IO (Either FsError (List String))
```

## def fsx_read_config

```ouro
def fsx_read_config (path : String) : IO (Either FsError Config)
```

## def fsx_write_config

```ouro
def fsx_write_config (path : String) (cfg : Config) : IO (Either FsError Unit)
```

## def fsx_read_nonempty

```ouro
def fsx_read_nonempty (path : String) : IO (Either FsError String)
```
