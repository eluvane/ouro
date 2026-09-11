"""Lint false-positive contracts, including editor-only refined patterns."""
from __future__ import annotations

from ourosmith.surface.gen import PRELUDE


def cases(seed):
    n = f'value{seed}'
    yield 'refined-slots', PRELUDE + f'''inductive Outcome : Type := | MkOutcome : Nat -> Bool -> Nat -> Outcome;
def score (o : Outcome) : Nat := match o with
| MkOutcome {n} True _ => {n} | MkOutcome _ False penalty => penalty end;
def pairScore (a : Outcome) (b : Outcome) : Nat := match a, b with
| MkOutcome {n} True _, MkOutcome _ True _ => {n}
| MkOutcome _ True _, MkOutcome m False _ => m
| MkOutcome _ False penalty, MkOutcome _ True _ => penalty
| MkOutcome _ False _, MkOutcome _ False _ => Z end;
''', []
    yield 'imported-refinement', '''import "types.ouro";
def firstIfFlag (p : Pair Nat Bool) : Nat := match p with
| MkPair n True => n | MkPair _ False => Z end;
def headOrZero (xs : List Nat) : Nat := match xs with
| Nil => Z | Cons x _ => x end;
''', [('types.ouro', PRELUDE + '''inductive Pair (A : Type) (B : Type) : Type := | MkPair : A -> B -> Pair A B;
inductive List (A : Type) : Type := | Nil : List A | Cons : A -> List A -> List A;
''')]
    yield 'import-alias-open', f'''import "numbers.ouro" as Numbers;
open Numbers;
def value{seed} : Nat := Numbers.one;
def locallyOpened{seed} : Nat := open Numbers in one;
''', [('numbers.ouro', 'inductive Nat : Type := | Z : Nat | S : Nat -> Nat;\ndef one : Nat := S Z;\n')]
    yield 'nullary-multi-match', PRELUDE + f'''def eq{seed} : Nat -> Nat -> Bool :=
fix eq{seed} (n : Nat) (m : Nat) : Bool := match n, m with
| Z, Z => True | Z, S _ => False | S _, Z => False
| S n', S m' => eq{seed} n' m' end;
''', []
    yield 'used-scopes', PRELUDE + f'''def identity (A : Type) (x : A) : A := x;
def result (n : Nat) : Nat := let {n} : Nat := identity Nat n in
(fun (next : Nat) => next) {n};
''', []
    yield 'handler-scopes', PRELUDE + f'''effect Counter where | tick : Nat -> Nat
def result : Nat := handle perform tick ({seed % 7}) with
| tick (input) resume => resume (S input) | pure output => output end;
''', []


FEATURES = tuple(name for name, *_ in cases(1))


def run_checks(run, directory, saved=None):
    from ourosmith.surface.run import StepFailure

    selected = [(saved["case"], saved["source"], saved.get("dependencies", []))] if saved is not None and "source" in saved else cases(run.seed)
    for name, source, dependencies in selected:
        run.case_id = f"surface-{run.seed}-lint-{name}"
        run.input = {"recipe": "lint_contracts", "seed": run.seed, "case": name,
                     "source": source, "dependencies": dependencies}
        work = directory / name
        work.mkdir(parents=True, exist_ok=True)
        for filename, text in dependencies:
            dependency = work / filename
            dependency.parent.mkdir(parents=True, exist_ok=True)
            dependency.write_text(text, encoding="utf-8", newline="\n")
        path = work / "main.ouro"
        path.write_text(source, encoding="utf-8", newline="\n")
        run.summary.cases += 1
        try:
            result = run.command([run.tool("ouro-lint"), path], work, "lint-" + name)
            run.require(result.ok and not result.stdout.strip() and not result.stderr.strip(),
                        "lint-clean-" + name, "no diagnostics", run.output(result))
            run.count("features", "lint-clean:" + name)
        except StepFailure as failure:
            run.record(failure)
