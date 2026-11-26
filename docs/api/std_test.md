# std/test.ouro

User-level test helpers. A test program prints one line per case and exits nonzero on failure.

Declarations: 9.

## inductive Test

```ouro
inductive Test : Type
```

## def test_ok

```ouro
def test_ok (name : String) : Test
```

## def test_fail

```ouro
def test_fail (name : String) (reason : String) : Test
```

## def assert_true

```ouro
def assert_true (name : String) (b : Bool) : Test
```

## def assert_eq

```ouro
def assert_eq (name : String) (got : String) (want : String) : Test
```

## def test_line

```ouro
def test_line (t : Test) : String
```

## def test_failed

```ouro
def test_failed (t : Test) : Bool
```

## def test_report

```ouro
def test_report (t : Test) : IO Unit
```

## def test_run

```ouro
def test_run (ts : List Test) : IO Unit
```
