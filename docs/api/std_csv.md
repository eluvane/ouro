# std/csv.ouro

Quoted fields can contain commas and use doubled quotes for literal quotes. `csv_parse` splits on line feeds before handling quotes, so input rows must fit on one line. `csv_print` encloses fields that contain line feeds in quotes.

Declarations: 20.

## inductive CsvCell

```ouro
inductive CsvCell : Type
```

## inductive CsvRow

```ouro
inductive CsvRow : Type
```

## inductive CsvTable

```ouro
inductive CsvTable : Type
```

## def csv_unescape

```ouro
def csv_unescape (s : String) : String
```

## def csv_escape

```ouro
def csv_escape (s : String) : String
```

## def csv_split_row

```ouro
def csv_split_row (s : String) : List String
```

## def csv_parse

```ouro
def csv_parse (s : String) : List (List String)
```

## def csv_join_row

```ouro
def csv_join_row (cols : List String) : String
```

## def csv_print

```ouro
def csv_print (rows : List (List String)) : String
```

## def csv_col

```ouro
def csv_col (rows : List (List String)) (i : Nat) : List String
```

## def csv_header

```ouro
def csv_header (rows : List (List String)) : List String
```

## def csv_lookup_col

```ouro
def csv_lookup_col (header : List String) (name : String) : Maybe Nat
```

## def csv_get

```ouro
def csv_get (rows : List (List String)) (row : Nat) (col : Nat) : String
```

## def csv_nrows

```ouro
def csv_nrows (rows : List (List String)) : Nat
```

## def csv_ncols

```ouro
def csv_ncols (rows : List (List String)) : Nat
```

## def tsv_split_row

```ouro
def tsv_split_row (s : String) : List String
```

## def tsv_parse

```ouro
def tsv_parse (s : String) : List (List String)
```

## def tsv_print

```ouro
def tsv_print (rows : List (List String)) : String
```

## def pipe_parse

```ouro
def pipe_parse (s : String) : List (List String)
```

## def pipe_lookup

```ouro
def pipe_lookup (table : String) (key : String) : Maybe String
```
