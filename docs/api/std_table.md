# std/table.ouro

Header-aware table helpers over the bounded CSV parser.

Declarations: 13.

## def table_from_csv

```
def table_from_csv (text : String) : List (List String)
```

## def table_to_csv

```
def table_to_csv (rows : List (List String)) : String
```

## def table_header

```
def table_header (rows : List (List String)) : List String
```

## def table_rows

```
def table_rows (rows : List (List String)) : List (List String)
```

## def table_cell

```
def table_cell (header : List String) (row : List String) (name : String)
```

## def table_record

```
def table_record (header : List String) (row : List String) : Map String
```

## def table_records

```
def table_records (rows : List (List String)) : List (Map String)
```

## def table_lookup

```
def table_lookup (row : Map String) (name : String) : Maybe String
```

## def table_col_named

```
def table_col_named (rows : List (List String)) (name : String) : List String
```

## def table_require_col

```
def table_require_col (header : List String) (name : String) : Either String Nat
```

## def table_project_row

```
def table_project_row (header : List String) (names : List String)
```

## def table_project

```
def table_project (rows : List (List String)) (names : List String)
```

## def table_count_rows

```
def table_count_rows (rows : List (List String)) : Nat
```
