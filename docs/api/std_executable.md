# std/executable.ouro

Declarations: 1.

## def executable_path_checked

```
def executable_path_checked : IO (Either ExecutablePathError String)
```

Query the fully qualified current Windows image path as UTF-8 when run. Preserve loaded spelling; truncation, conversion and cleanup failures are typed. This path does not establish file identity or executable byte integrity.
