# std/lines.ouro

Bounded line-oriented data processing over in-memory text.

Declarations: 36.

## inductive LineRecord

```ouro
inductive LineRecord : Type
```

## def line_record_number

```ouro
def line_record_number (r : LineRecord) : Nat
```

## def line_record_text

```ouro
def line_record_text (r : LineRecord) : String
```

## def lines_from_text

```ouro
def lines_from_text (text : String) : List String
```

## def lines_to_text

```ouro
def lines_to_text (lines : List String) : String
```

## def line_nonblank

```ouro
def line_nonblank (line : String) : Bool
```

## def line_is_comment

```ouro
def line_is_comment (prefix : String) (line : String) : Bool
```

## def line_without_comments

```ouro
def line_without_comments (prefix : String) (lines : List String) : List String
```

## def line_nonblank_only

```ouro
def line_nonblank_only (lines : List String) : List String
```

## def line_data_lines

```ouro
def line_data_lines (comment_prefix : String) (lines : List String) : List String
```

## def line_number_from

```ouro
def line_number_from (start : Nat) (lines : List String) : List LineRecord
```

## def line_number

```ouro
def line_number (lines : List String) : List LineRecord
```

## def line_map

```ouro
def line_map (f : String -> String) (lines : List String) : List String
```

## def line_filter

```ouro
def line_filter (p : String -> Bool) (lines : List String) : List String
```

## def line_fold

```ouro
def line_fold (A : Type) (f : A -> String -> A) (z : A) (lines : List String) : A
```

## def line_count

```ouro
def line_count (lines : List String) : Nat
```

## def line_count_where

```ouro
def line_count_where (p : String -> Bool) (lines : List String) : Nat
```

## def line_take

```ouro
def line_take (n : Nat) (lines : List String) : List String
```

## def line_drop

```ouro
def line_drop (n : Nat) (lines : List String) : List String
```

## def line_head

```ouro
def line_head (n : Nat) (lines : List String) : List String
```

## def line_tail

```ouro
def line_tail (n : Nat) (lines : List String) : List String
```

## def line_chunks

```ouro
def line_chunks (n : Nat) (lines : List String) : List (List String)
```

## def line_fields_ws

```ouro
def line_fields_ws (line : String) : List String
```

## def line_fields_char

```ouro
def line_fields_char (sep : Nat) (line : String) : List String
```

## def line_field_ws_or

```ouro
def line_field_ws_or (fallback : String) (index : Nat) (line : String) : String
```

## def line_field_csv_or

```ouro
def line_field_csv_or (fallback : String) (index : Nat) (line : String) : String
```

## def line_parse_nat_fields

```ouro
def line_parse_nat_fields (line : String) : List Nat
```

## def line_nat_values

```ouro
def line_nat_values (lines : List String) : List Nat
```

## def line_transform_text

```ouro
def line_transform_text (f : List String -> List String) (text : String) : String
```

## def line_read_stdin

```ouro
def line_read_stdin : IO (List String)
```

## def line_process_stdin

```ouro
def line_process_stdin (f : List String -> List String) : IO String
```

## def line_print_stdin

```ouro
def line_print_stdin (f : List String -> List String) : IO Unit
```

## def line_read_file_checked

```ouro
def line_read_file_checked (path : String) : IO (Either FsError (List String))
```

## def line_transform_file_checked

```ouro
def line_transform_file_checked (src : String) (dst : String) (f : List String -> List String) : IO (Either FsError Unit)
```

## def line_report

```ouro
def line_report (label : String) (lines : List String) : Report
```

## def line_transform_report

```ouro
def line_transform_report (input_lines : List String) (output_lines : List String) : Report
```
