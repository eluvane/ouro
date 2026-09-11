"""Reference counts for generated non-tail recursion deeper than 10,000."""
from ourosmith.surface.gen import PRELUDE, nat_output


def program(seed):
    offset = seed % 19
    source = PRELUDE + f"""inductive List (A : Type) : Type := | Nil : List A | Cons : A -> List A -> List A;
def mul : Nat -> Nat -> Nat :=
  fix mul (n : Nat) (m : Nat) : Nat := match n with | Z => Z | S k => add m (mul k m) end;
def repeat : Nat -> List Nat :=
  fix repeat (n : Nat) : List Nat := match n with | Z => Nil Nat | S k => Cons Nat {seed % 7} (repeat k) end;
def count : List Nat -> Nat :=
  fix count (items : List Nat) : Nat := match items with | Nil => Z | Cons _ rest => S (count rest) end;
def result : Nat := count (repeat (add (mul 10 (mul 10 (mul 10 10))) {offset}));
"""
    return source, 10000 + offset


def run_checks(run, directory, saved=None):
    source, value = (saved["source"], saved["expected"]) if saved is not None else program(run.seed)
    run.input = {"recipe": "backend_depth", "source": source, "expected": value}
    path = directory / "main.ouro"
    path.write_text(source, encoding="utf-8", newline="\n")
    run.accepts(path)
    actual = run.native(path)
    run.require(actual.ok and actual.stdout == nat_output(value), "backend-depth-reference", nat_output(value), run.output(actual))
    run.count("features", "backend:non-tail-depth")
