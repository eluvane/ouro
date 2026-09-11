# std/report.ouro

Small reporting and timing helpers for CLI/data tools.

Declarations: 23.

## inductive Duration

```
inductive Duration : Type
```

## def duration_ms

```
def duration_ms (d : Duration) : Nat
```

## def duration_zero

```
def duration_zero : Duration
```

## def duration_between

```
def duration_between (start_ms : Nat) (finish_ms : Nat) : Duration
```

## def duration_show_ms

```
def duration_show_ms (d : Duration) : String
```

## def time_now_string

```
def time_now_string : IO String
```

## def time_nat_or_zero

```
def time_nat_or_zero (m : Maybe Nat) : Nat
```

## def time_now_nat

```
def time_now_nat : IO (Maybe Nat)
```

## def time_elapsed

```
def time_elapsed (A : Type) (act : IO A) : IO (Pair Duration A)
```

## def Report

```
def Report : Type
```

## def report_empty

```
def report_empty : Report
```

## def report_pair

```
def report_pair (key : String) (value : String) : Pair String String
```

## def report_add

```
def report_add (key : String) (value : String) (r : Report) : Report
```

## def report_add_nat

```
def report_add_nat (key : String) (value : Nat) (r : Report) : Report
```

## def report_add_bool

```
def report_add_bool (key : String) (value : Bool) (r : Report) : Report
```

## def report_add_duration

```
def report_add_duration (key : String) (value : Duration) (r : Report) : Report
```

## def report_merge

```
def report_merge (a : Report) (b : Report) : Report
```

## def report_render_pair

```
def report_render_pair (p : Pair String String) : String
```

## def report_render

```
def report_render (r : Report) : String
```

## def report_section

```
def report_section (title : String) (body : String) : String
```

## def report_status

```
def report_status (ok : Bool) : String
```

## def report_summary

```
def report_summary (ok : Nat) (warn : Nat) (err : Nat) : Report
```

## def report_from_pairs

```
def report_from_pairs (pairs : List (Pair String String)) : Report
```
