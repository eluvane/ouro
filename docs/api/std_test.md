# std/test.ouro

User-level test helpers. A test program prints one line per case and exits nonzero on failure.

Declarations: 9.

## inductive Test

```
inductive Test : Type
```

## def test_ok

```
def test_ok (name : String) : Test
```

## def test_fail

```
def test_fail (name : String) (reason : String) : Test
```

## def assert_true

```
def assert_true (name : String) (b : Bool) : Test
```

## def assert_eq

```
def assert_eq (name : String) (got : String) (want : String) : Test
```

## def test_line

```
def test_line (t : Test) : String
```

## def test_failed

```
def test_failed (t : Test) : Bool
```

## def test_report

```
def test_report (t : Test) : IO Unit
```

## def test_run

```
def test_run (ts : List Test) : IO Unit
```
