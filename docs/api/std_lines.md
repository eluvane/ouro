# std/lines.ouro

Bounded line-oriented data processing over in-memory text.

Declarations: 36.

## inductive LineRecord

```
inductive LineRecord : Type
```

## def line_record_number

```
def line_record_number (r : LineRecord) : Nat
```

## def line_record_text

```
def line_record_text (r : LineRecord) : String
```

## def lines_from_text

```
def lines_from_text (text : String) : List String
```

## def lines_to_text

```
def lines_to_text (lines : List String) : String
```

## def line_nonblank

```
def line_nonblank (line : String) : Bool
```

## def line_is_comment

```
def line_is_comment (prefix : String) (line : String) : Bool
```

## def line_without_comments

```
def line_without_comments (prefix : String) (lines : List String) : List String
```

## def line_nonblank_only

```
def line_nonblank_only (lines : List String) : List String
```

## def line_data_lines

```
def line_data_lines (comment_prefix : String) (lines : List String) : List String
```

## def line_number_from

```
def line_number_from (start : Nat) (lines : List String) : List LineRecord
```

## def line_number

```
def line_number (lines : List String) : List LineRecord
```

## def line_map

```
def line_map (f : String -> String) (lines : List String) : List String
```

## def line_filter

```
def line_filter (p : String -> Bool) (lines : List String) : List String
```

## def line_fold

```
def line_fold (A : Type) (f : A -> String -> A) (z : A) (lines : List String) : A
```

## def line_count

```
def line_count (lines : List String) : Nat
```

## def line_count_where

```
def line_count_where (p : String -> Bool) (lines : List String) : Nat
```

## def line_take

```
def line_take (n : Nat) (lines : List String) : List String
```

## def line_drop

```
def line_drop (n : Nat) (lines : List String) : List String
```

## def line_head

```
def line_head (n : Nat) (lines : List String) : List String
```

## def line_tail

```
def line_tail (n : Nat) (lines : List String) : List String
```

## def line_chunks

```
def line_chunks (n : Nat) (lines : List String) : List (List String)
```

## def line_fields_ws

```
def line_fields_ws (line : String) : List String
```

## def line_fields_char

```
def line_fields_char (sep : Nat) (line : String) : List String
```

## def line_field_ws_or

```
def line_field_ws_or (fallback : String) (index : Nat) (line : String) : String
```

## def line_field_csv_or

```
def line_field_csv_or (fallback : String) (index : Nat) (line : String) : String
```

## def line_parse_nat_fields

```
def line_parse_nat_fields (line : String) : List Nat
```

## def line_nat_values

```
def line_nat_values (lines : List String) : List Nat
```

## def line_transform_text

```
def line_transform_text (f : List String -> List String) (text : String) : String
```

## def line_read_stdin

```
def line_read_stdin : IO (List String)
```

## def line_process_stdin

```
def line_process_stdin (f : List String -> List String) : IO String
```

## def line_print_stdin

```
def line_print_stdin (f : List String -> List String) : IO Unit
```

## def line_read_file_checked

```
def line_read_file_checked (path : String) : IO (Either FsError (List String))
```

## def line_transform_file_checked

```
def line_transform_file_checked (src : String) (dst : String) (f : List String -> List String) : IO (Either FsError Unit)
```

## def line_report

```
def line_report (label : String) (lines : List String) : Report
```

## def line_transform_report

```
def line_transform_report (input_lines : List String) (output_lines : List String) : Report
```
