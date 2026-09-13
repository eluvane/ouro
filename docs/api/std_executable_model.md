# std/executable_model.ouro

Declarations: 7.

## inductive ExecutablePathError

```
inductive ExecutablePathError : Type
```

Current-image query and ownership errors without a numeric Windows last-error. Cleanup failure retains the prior typed error when one occurred.

## def executable_path_error_code

```
def executable_path_error_code (error : ExecutablePathError) : String
```

Stable diagnostic category for an executable-path failure.

## def executable_path_error_message

```
def executable_path_error_message (error : ExecutablePathError) : String
```

Render an executable-path diagnostic, including a prior cleanup cause.

## def executable_path_query_length

```
def executable_path_query_length (actual : Nat) (capacity : Nat) : Either ExecutablePathError Nat
```

The returned length excludes the terminator; nSize includes its storage.

## def executable_path_byte_length

```
def executable_path_byte_length (actual : Nat) (capacity : Nat) : Either ExecutablePathError Nat
```

## def executable_path_value

```
def executable_path_value (value : String) : Either ExecutablePathError String
```

Preserve loaded spelling and every byte; only empty/NUL paths are rejected.

## def executable_path_released

```
def executable_path_released (result : Either ExecutablePathError String) (released : Bool)
```

A release failure never becomes Right, even after a successful query.
