"""Parameterized surface sugars with independent natural-number results."""
from __future__ import annotations

import json

from ourosmith.surface.gen import IDENTITY_IO, PRELUDE, nat_output


def programs(seed):
    n, m = seed % 7, (seed * 3) % 5
    values = [(seed + i) % 7 for i in range(seed % 6)]
    flag = "True" if seed % 2 else "False"
    yield "polymorphic-id", PRELUDE + f"""def identity (A : Type) (value : A) : A := value;
def result : Nat := match identity Bool {flag} with
  | True => identity Nat {n} | False => identity Nat {m} end;
""", n if seed % 2 else m, False
    text = f'handle perform ?goal{seed}\\"\n'
    yield "text-keywords", PRELUDE + f"""-- handle perform ?unresolved must remain comment text
def message : String := {json.dumps(text)};
def result : Nat := prim_string_length message;
""", len(text.encode()), False
    # The foreign declaration is checked and preserved through formatting.
    # Its unrelated Nat result exercises ordinary execution, not the FFI call.
    yield "extern-declaration", PRELUDE + f"""intrinsic NativeWord : Type := "ouro.u32";
intrinsic HostAction : Type -> Type := "ouro.runtime";
extern current_pid : HostAction NativeWord :=
  "windows-x86_64" "win64" "kernel32.dll" "GetCurrentProcessId" "nogc";
def result : Nat := {n};
""", n, False
    yield "applied-lambda-match", PRELUDE + f"""def result : Nat :=
  (fun (value : Nat) => add value (match {flag} with | True => {n} | False => {m} end)) {n};
""", n + (n if seed % 2 else m), False
    yield "applied-lambda-curried-match", PRELUDE + f"""def result : Nat :=
  (fun (left : Nat) => fun (right : Nat) =>
    add left (match {flag} with | True => right | False => S right end)) {n} {m};
""", n + m + (0 if seed % 2 else 1), False
    yield "large-elimination", PRELUDE + f"""def resultType (n : Nat) : Type :=
  match n with | Z => Nat | S _ => Nat end;
def value : resultType Z := {n};
def result : Nat := value;
""", n, False
    yield "long-type-reduction", PRELUDE + f"""def type_after : Nat -> Type :=
  fix go (count : Nat) : Type :=
    match count with | Z => Nat | S rest => go rest end;
def value : type_after 300 := {n};
def result : Nat := value;
""", n, False
    count, choice = 3 + seed % 4, seed % (3 + seed % 4)
    constructors = " | ".join(f"C{i} : Choice" for i in range(count))
    branches = " | ".join(f"C{i} => {i}" for i in range(count))
    yield "enum", PRELUDE + f"""inductive Choice : Type := | {constructors};
def value (c : Choice) : Nat := match c with | {branches} end;
def result : Nat := value C{choice};
""", choice, False
    yield "polymorphic-sum", PRELUDE + f"""inductive Either (A : Type) (B : Type) : Type :=
  | LeftE : A -> Either A B | RightE : B -> Either A B;
def value (e : Either Nat Bool) : Nat :=
  match e with | LeftE x => x | RightE b => match b with | True => {n} | False => {m} end end;
def result : Nat := add (value (LeftE Nat Bool {m})) (value (RightE Nat Bool True));
""", n + m, False
    yield "fallible-block", PRELUDE + f"""inductive Outcome (E : Type) (A : Type) : Type :=
  | Failed : E -> Outcome E A | Passed : A -> Outcome E A;
def success : Outcome Nat Nat :=
  let? (Failed, Passed) : Outcome Nat Nat do
    let value : Nat := (Passed Nat Nat {n})?;
    S value
  end;
def failure : Outcome Nat Nat :=
  let? (Failed, Passed) : Outcome Nat Nat do
    let value : Nat := (Failed Nat Nat {m})?;
    S value
  end;
def boundary : Outcome Nat Nat :=
  let? (Failed, Passed) : Outcome Nat Nat do
    let inner : Outcome Nat Nat := let? (Failed, Passed) : Outcome Nat Nat do
      let value : Nat := (Failed Nat Nat {m})?;
      S value
    end;
    match inner with | Failed error => S error | Passed value => value end
  end;
def score (outcome : Outcome Nat Nat) : Nat :=
  match outcome with | Failed error => add 100 error | Passed value => value end;
def result : Nat := add (add (score success) (score failure)) (score boundary);
""", n + 2 * m + 102, False
    phase = "Ready" if seed % 2 else "Raw"
    yield "indexed-phase-param", PRELUDE + f"""inductive Phase : Type := | Raw : Phase | Ready : Phase;
inductive Box (phase : Phase) : Type := | MkBox : Nat -> Box phase;
def unbox (phase : Phase) (box : Box phase) : Nat := match box with | MkBox value => value end;
def result : Nat := unbox {phase} (MkBox {phase} {n});
""", n, False
    yield "nested-descent", PRELUDE + f"""def outer : Nat -> Nat :=
  fix outer (n : Nat) : Nat :=
    match n with
    | Z => Z
    | S k => S ((fix walk (x : Nat) : Nat :=
        match x with | Z => outer x | S rest => S (walk rest) end) k)
    end;
def result : Nat := outer {n};
""", n, False
    leaves = ", ".join("Leaf" for _ in values)
    yield "nested-tree-fold", PRELUDE + f"""inductive List (A : Type) : Type := | Nil : List A | Cons : A -> List A -> List A;
inductive Tree : Type := | Leaf : Tree | Node : List Tree -> Tree;
def size : Tree -> Nat :=
  fix size (tree : Tree) : Nat :=
    match tree with
    | Leaf => S Z
    | Node items => S ((fix walk (xs : List Tree) : Nat :=
        match xs with | Nil => Z | Cons child rest => add (size child) (walk rest) end) items)
    end;
def children : List Tree := [{leaves}];
def result : Nat := size (Node (Cons Tree (Node children) (Cons Tree Leaf (Nil Tree))));
""", len(values) + 3, False
    yield "do-case-binding", PRELUDE + IDENTITY_IO + f"""def choose (flag : Bool) : IO Nat :=
  do let! value := match flag with
       | True => do io_pure Unit MkUnit; io_pure Nat {n}
       | False => io_pure Nat {m}
       end;
     io_pure Nat value
def result : Nat := add (choose True) (choose False);
""", n + m, False
    yield "list", PRELUDE + f"""inductive List (A : Type) : Type := | Nil : List A | Cons : A -> List A -> List A;
def length (A : Type) : List A -> Nat :=
  fix length (xs : List A) : Nat :=
    match xs with | Nil => Z | Cons _ tail => S (length tail) end;
def values : List Nat := [{', '.join(map(str, values))}];
def result : Nat := values |> length Nat;
""", len(values), False
    yield "record", PRELUDE + f"""record Point : Type where
  x : Nat;
  y : Nat;
end;
def point : Point := {{ y := {m}, x := {n} }};
def result : Nat := add (point.x) (point.y);
""", n + m, False
    yield "pair-match", PRELUDE + f"""inductive Pair (A : Type) (B : Type) : Type := | MkPair : A -> B -> Pair A B;
def select (pair : Pair Nat Bool) : Nat :=
  match pair with | MkPair value flag => match flag with | True => value | False => S value end end;
def result : Nat := select (MkPair Nat Bool {n} {'True' if m % 2 else 'False'});
""", n if m % 2 else n + 1, False
    yield "inferred-lambda", PRELUDE + f"""def identity : Nat -> Nat := fun n => n;
def result : Nat := identity {n};
""", n, False
    yield "bounded-callback", PRELUDE + f"""def apply (f : Nat -> Nat) (n : Nat) : Nat := f n;
def bounded : Nat -> Nat -> Nat :=
  fix bounded (fuel : Nat) (value : Nat) : Nat :=
    match fuel with
    | Z => value
    | S remaining => apply (fun (next : Nat) => bounded remaining next) (S value)
    end;
def result : Nat := bounded {n} {m};
""", n + m, False
    yield "multi-match", PRELUDE + f"""def combine (a : Nat) (b : Nat) : Nat :=
  match a, b with
  | Z, Z => Z
  | Z, S y => S y
  | S x, Z => S x
  | S x, S y => S (S (add x y))
  end;
def result : Nat := combine {n} {m};
""", n + m, False
    yield "handler", PRELUDE + f"""effect Counter where
  | increment : Nat -> Nat
def result : Nat :=
  handle perform increment ({n}) with
  | increment(value) resume => resume (S value)
  | pure value => value
  end;
""", n + 1, True
    yield "handler-two-ops", PRELUDE + f"""effect Console where
  | read : Nat -> Nat
  | write : Nat -> Nat
def result : Nat := handle perform write (perform read ({m})) with
  | write (value) resume => resume (S value)
  | read (_) resume => resume {n}
  | pure value => value
  end;
""", n + 1, True


FEATURES = tuple(name for name, *_ in programs(1))


def run_forms(run, only=None, saved=None):
    from ourosmith.surface.run import StepFailure

    selected = [(only, saved["source"], saved["expected"], saved.get("units_needed", False))] if saved is not None and "source" in saved else programs(run.seed)
    for name, source, expected, units_needed in selected:
        if only is not None and name != only:
            continue
        run.case_id = f"surface-{run.seed}-form-{name}"
        run.input = {"recipe": "form-" + name, "source": source, "expected": expected, "units_needed": units_needed}
        directory = run.work / "cases" / run.case_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "main.ouro"
        path.write_text(source, encoding="utf-8", newline="\n")
        units = [path] if units_needed else []
        try:
            before = run.accepts(path, units=units)
            run.summary.positive_checks += 1
            run.count("features", "form:" + name)
            formatted = run.command([run.tool("ouro-fmt"), path], directory, "form-format")
            run.require(formatted.ok, "form-format", "exit 0", run.output(formatted))
            path.write_text(formatted.stdout, encoding="utf-8", newline="\n")
            run.require(run.accepts(path, units=units) == before, "form-format-core", before, "artifact changed")
            again = run.command([run.tool("ouro-fmt"), path], directory, "form-format-idempotent")
            run.require(again.ok and again.stdout == formatted.stdout, "form-format-idempotent", formatted.stdout, run.output(again))
            actual = run.native(path, units=units)
            run.require(actual.ok and actual.stdout == nat_output(expected), "form-runtime-" + name, nat_output(expected), run.output(actual))
        except StepFailure as failure:
            run.record(failure)
