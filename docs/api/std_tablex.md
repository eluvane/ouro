# std/tablex.ouro

Practical table transforms layered over header-aware CSV tables.

Declarations: 14.

## def tablex_filter_rows

```
def tablex_filter_rows (rows : List (List String)) (p : List String -> Bool) : List (List String)
```

## def tablex_map_rows

```
def tablex_map_rows (rows : List (List String)) (f : List String -> List String) : List (List String)
```

## def tablex_filter_records

```
def tablex_filter_records (rows : List (List String)) (p : Map String -> Bool) : List (Map String)
```

## def tablex_map_records

```
def tablex_map_records (A : Type) (rows : List (List String)) (f : Map String -> A) : List A
```

## def tablex_has_column

```
def tablex_has_column (header : List String) (name : String) : Bool
```

## def tablex_require_column

```
def tablex_require_column (header : List String) (name : String) : Validation String Unit
```

## def tablex_validate_columns

```
def tablex_validate_columns (header : List String) : List String -> Validation String Unit
```

## def tablex_project_required

```
def tablex_project_required (rows : List (List String)) (names : List String) : Validation String (List (List String))
```

## def tablex_record_get_or

```
def tablex_record_get_or (row : Map String) (name : String) (fallback : String) : String
```

## def tablex_row_matches

```
def tablex_row_matches (header : List String) (name : String) (want : String) (row : List String) : Bool
```

## def tablex_select_where_eq

```
def tablex_select_where_eq (rows : List (List String)) (name : String) (want : String) : List (List String)
```

## def tablex_count_where

```
def tablex_count_where (rows : List (List String)) (name : String) (want : String) : Nat
```

## def tablex_csv_project

```
def tablex_csv_project (text : String) (names : List String) : String
```

## def tablex_csv_project_required

```
def tablex_csv_project_required (text : String) (names : List String) : Validation String String
```
