# std/csv.ouro

CSV support is deliberately bounded: comma fields plus one quote pair, no full RFC state machine.

Declarations: 20.

## inductive CsvCell

```
inductive CsvCell : Type
```

## inductive CsvRow

```
inductive CsvRow : Type
```

## inductive CsvTable

```
inductive CsvTable : Type
```

## def csv_unescape

```
def csv_unescape (s : String) : String
```

## def csv_escape

```
def csv_escape (s : String) : String
```

## def csv_split_row

```
def csv_split_row (s : String) : List String
```

## def csv_parse

```
def csv_parse (s : String) : List (List String)
```

## def csv_join_row

```
def csv_join_row (cols : List String) : String
```

## def csv_print

```
def csv_print (rows : List (List String)) : String
```

## def csv_col

```
def csv_col (rows : List (List String)) (i : Nat) : List String
```

## def csv_header

```
def csv_header (rows : List (List String)) : List String
```

## def csv_lookup_col

```
def csv_lookup_col (header : List String) (name : String) : Maybe Nat
```

## def csv_get

```
def csv_get (rows : List (List String)) (row : Nat) (col : Nat) : String
```

## def csv_nrows

```
def csv_nrows (rows : List (List String)) : Nat
```

## def csv_ncols

```
def csv_ncols (rows : List (List String)) : Nat
```

## def tsv_split_row

```
def tsv_split_row (s : String) : List String
```

## def tsv_parse

```
def tsv_parse (s : String) : List (List String)
```

## def tsv_print

```
def tsv_print (rows : List (List String)) : String
```

## def pipe_parse

```
def pipe_parse (s : String) : List (List String)
```

## def pipe_lookup

```
def pipe_lookup (table : String) (key : String) : Maybe String
```
