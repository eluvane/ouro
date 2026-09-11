# std/fsx.ouro

Higher-level checked filesystem helpers built from std/fs.

Declarations: 11.

## def fsx_read_text

```
def fsx_read_text (path : String) : IO (Either FsError String)
```

## def fsx_write_text

```
def fsx_write_text (path : String) (content : String) : IO (Either FsError Unit)
```

## def fsx_read_lines

```
def fsx_read_lines (path : String) : IO (Either FsError (List String))
```

## def fsx_write_lines

```
def fsx_write_lines (path : String) (lines : List String)
```

## def fsx_append_line

```
def fsx_append_line (path : String) (line : String) : IO (Either FsError Unit)
```

## def fsx_remove_if_exists

```
def fsx_remove_if_exists (path : String) : IO (Either FsError Unit)
```

## def fsx_list_matching

```
def fsx_list_matching (dir : String) (p : String -> Bool)
```

## def fsx_list_full_matching

```
def fsx_list_full_matching (dir : String) (p : String -> Bool)
```

## def fsx_read_config

```
def fsx_read_config (path : String) : IO (Either FsError Config)
```

## def fsx_write_config

```
def fsx_write_config (path : String) (cfg : Config) : IO (Either FsError Unit)
```

## def fsx_read_nonempty

```
def fsx_read_nonempty (path : String) : IO (Either FsError String)
```
