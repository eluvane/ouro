"""Parameterized byte-level contracts transcribed from the maintained tool rules.

These exercise source rewrites, including incomplete editor inputs. Typed
check/runtime preservation belongs to the separate generated program property.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextCase:
    name: str
    tool: str
    source: str
    expected: str
    dependencies: tuple[tuple[str, str], ...] = ()


def cases(seed):
    name, n = f"value{seed}", seed % 7
    clean = f'''def {name} : Nat :=
  match Z with
| Z => Z
| S n => n
end;
-- comment {seed}
def text{seed} : String := "keep  --  spacing := inside {seed}";
'''
    yield TextCase("fmt-clean", "fmt", clean, clean)
    dirty = clean.replace("  match", "\tmatch").replace("| Z => Z", "|Z=>Z").replace("| S n => n", "|S n=>n   ").replace("-- comment", "--comment")
    yield TextCase("fmt-layout", "fmt", dirty.rstrip("\n") + "\r\n\r\n\r\n", clean)
    syntax = f'''record Point{seed} : Type where
  x : Nat;
  y : Nat;
end;
def {name} : Point{seed} := {{ x := {n}, y := Z }};
def items{seed} : List Nat := [ S Z, Z ];
def piped{seed} : Nat := x |> f;
def echo{seed} : IO Unit :=
  do let! line := readLine;
    println line
'''
    yield TextCase("fmt-syntax", "fmt", syntax.replace("  x", "\tx").replace("x |> f;", "x |> f;   "), syntax)
    ergo = f'''-- Canonical forms {seed}.

def {name} : Nat := Z |> S |> S;
def items{seed} : List Nat := [Z, S Z];
def echo{seed} : IO Unit :=
  do let! n := readNat;
     writeNat (n |> S)
'''
    yield TextCase("fmt-ergonomics", "fmt", ergo, ergo)

    def fix(label, before, after=None, *, dependencies=()):
        return TextCase(label, "fix", before + "\n", (before if after is None else after) + "\n", dependencies)

    yield fix("fix-unused-parameter", f"def {name} (x : Nat) (y : Nat) : Nat := x;", f"def {name} (x : Nat) (_y : Nat) : Nat := x;")
    yield fix("fix-dotted-use", f"def {name} (r : Rec) (q : Rec) : Nat := r.field;", f"def {name} (r : Rec) (_q : Rec) : Nat := r.field;")
    yield fix("fix-nonrecursive", f"def {name} : Nat -> Nat -> Nat := fix go (n : Nat) (m : Nat) : Nat := n;",
              f"def {name} : Nat -> Nat -> Nat := fun (n : Nat) (_m : Nat) => n;")
    before = f'''def {name} : Nat -> Nat -> Nat :=
  fix go (n : Nat) (acc : Nat) : Nat :=
    match n with
    | Z => Z
    | S k => go k Z
    end;'''
    yield fix("fix-recursive", before, before.replace("(acc : Nat)", "(_acc : Nat)"))
    yield fix("fix-callback-preserved", f"def {name} (xs : List Nat) : Nat := foldr Nat Nat (fix step (x : Nat) (acc : Nat) : Nat := add x acc) Z xs;")
    yield fix("fix-untyped-lambda", f"def {name} : Nat -> Nat := fun x => {n};", f"def {name} : Nat -> Nat := fun _x => {n};")
    yield fix("fix-typed-lambda", f"def {name} : Nat -> Nat -> Nat := fun (a : Nat) (b : Nat) => a;",
              f"def {name} : Nat -> Nat -> Nat := fun (a : Nat) (_b : Nat) => a;")
    yield fix("fix-binder-collision", f"def {name} (v : Nat) (_v : Nat) : Nat := _v;")
    before = f"def {name} (p : Pair Nat Nat) : Nat := match p with | MkPair a b => a end;"
    yield fix("fix-pattern-binder", before, before.replace("MkPair a b", "MkPair a _b"))
    yield fix("fix-dead-let", f"def {name} (x : Nat) : Nat := let unused : Nat := add x x in let kept : Nat := x in kept;",
              f"def {name} (x : Nat) : Nat := let kept : Nat := x in kept;")
    yield fix("fix-unused-bind", f"def {name} (x : Nat) : IO Nat := do let! r := io_pure Nat x; let! s := io_pure Nat x; io_pure Nat s;",
              f"def {name} (x : Nat) : IO Nat := do io_pure Nat x; let! s := io_pure Nat x; io_pure Nat s;")
    for label, expression in (("effect-let", "perform Tick"), ("hole-let", "?todo")):
        yield fix("fix-" + label, f"def {name} (x : Nat) : Nat := let noise : Nat := {expression} in x;",
                  f"def {name} (x : Nat) : Nat := let _noise : Nat := {expression} in x;")

    shape = "inductive Shape : Type := | Dot : Shape | Line : Nat -> Shape | Box : Nat -> Nat -> Shape;\n"
    before = shape + f'''def {name} (s : Shape) : Nat :=
  match s with
  | Dot => Z
  | Line n => n
  | Box w h => mul w h
  | Dot => {n}
  end;'''
    yield fix("fix-duplicate-arm", before, before.replace(f"  | Dot => {n}\n", ""))
    before = shape + f'''def {name} (s : Shape) : Nat :=
  match s with
  | Dot => Z
  | other => size other
  | Line n => n
  | Box _ _ => Z
  end;'''
    yield fix("fix-catchall-arm", before, before.replace("  | Line n => n\n  | Box _ _ => Z\n", ""))
    before = shape + f'''def {name} (s : Shape) (t : Shape) : Nat :=
  match s, t with
  | Dot, Dot => Z
  | Line _, _ => S Z
  | Line n, Dot => n
  | Box _ _, Box _ _ => {n}
  end;'''
    yield fix("fix-multi-arm", before, before.replace("  | Line n, Dot => n\n", ""))
    yield fix("fix-ordered-arms", shape + f"def {name} (s : Shape) : Nat := match s with | Line n => n | Box w h => add w h | _ => Z end;")

    tower = "Z"
    count = 3 + seed % 5
    for _ in range(count):
        tower = "S " + (tower if tower == "Z" else "(" + tower + ")")
    yield fix("fix-numeral", f"def {name} : Nat := {tower};", f"def {name} : Nat := {count};")
    yield fix("fix-small-numeral", f"def {name} : Nat := S (S Z);")
    yield fix("fix-pipeline", f"def {name} (n : Nat) : Nat := S (S (S n));", f"def {name} (n : Nat) : Nat := n |> S |> S |> S;")
    yield fix("fix-numeral-argument", f"def {name} (n : Nat) : Nat := add ({tower}) n;", f"def {name} (n : Nat) : Nat := add {count} n;")
    for label, typ, before, after in (
        ("list", "List Nat", "Cons Nat Z (Cons Nat (S Z) (Nil Nat))", "[Z, S Z]"),
        ("nested-list", "List (List Nat)", "Cons (List Nat) (Cons Nat Z (Nil Nat)) (Nil (List Nat))", "[[Z]]"),
        ("nested-empty", "List (List Nat)", "Cons (List Nat) (Nil Nat) (Nil (List Nat))", "[[]]"),
        ("nested-rows", "List (List Nat)", "Cons (List Nat) (Nil Nat) (Cons (List Nat) (Cons Nat Z (Nil Nat)) (Nil (List Nat)))", "[[], [Z]]"),
        ("empty", "List Nat", "Nil Nat", "[]"),
        ("string-list", "List String", f'Cons String "a{seed}" (Cons String "b{seed}" (Nil String))', f'["a{seed}", "b{seed}"]'),
    ):
        yield fix("fix-" + label, f"def {name} : {typ} := {before};", f"def {name} : {typ} := {after};")
    yield fix("fix-open-list", f"def {name} (x : Nat) (xs : List Nat) : List Nat := Cons Nat x xs;")
    yield fix("fix-list-element", f"def {name} : Nat := length (List Nat) [Nil Nat, Cons Nat Z (Nil Nat)];",
              f"def {name} : Nat := length (List Nat) [Nil Nat, [Z]];")
    yield fix("fix-list-ascription", f"def {name} (nm : String) : List (List String) := Cons (List String) ([nm] : List String) (Nil (List String));",
              f"def {name} (nm : String) : List (List String) := [[nm]];")
    yield fix("fix-list-argument", f"def {name} (x : Nat) : Nat := length Nat (Cons Nat x (Cons Nat x (Nil Nat)));",
              f"def {name} (x : Nat) : Nat := length Nat ([x, x] : List Nat);")
    imports = f'import "module{seed}.ouro" as A;\n'
    dependencies = ((f"module{seed}.ouro", "inductive Nat : Type := | Z : Nat | S : Nat -> Nat;\n"
                     "def count : Nat := Z;\ndef limit : Nat := S Z;\n"),)
    yield fix("fix-duplicate-import", imports + imports.rstrip("\n"), imports.rstrip("\n"), dependencies=dependencies)
    yield fix("fix-distinct-import", imports + f'import "module{seed}.ouro" as B;', dependencies=dependencies)
    yield fix("fix-import-alias", f'import "module{seed}.ouro" as util;\ndef {name} : Nat := open util in util.count;',
              f'import "module{seed}.ouro" as Util;\ndef {name} : Nat := open Util in Util.count;', dependencies=dependencies)
    yield fix("fix-separator", f"def {name} : Nat := Z;;", f"def {name} : Nat := Z;")
    yield fix("fix-legacy-bind", f"def {name} : IO Nat := do x <- io_pure Nat {n}; io_pure Nat x;",
              f"def {name} : IO Nat := do let! x := io_pure Nat {n}; io_pure Nat x;")
    for label, typ, value, canonical in (("strings", "String", f'["a{seed}", "b{seed}"]', f'["a{seed}", "b{seed}"]'),
                                        ("naturals", "Nat", "[1, 2, Z, S Z]", "[1, 2, Z, S Z]"),
                                        ("nil", "Nat", "Nil Nat", "[]"),
                                        ("cons", "Nat", "Cons Nat Z (Nil Nat)", "[Z]")):
        yield fix("fix-let-type-" + label, f"def {name} : Nat := let items := {value} in length {typ} items;",
                  f"def {name} : Nat := let items : List {typ} := {canonical} in length {typ} items;")
    yield fix("fix-opaque-elements", f"def {name} (x : Nat) : Nat := let m := [f x, g x] in length Nat m;")
    yield fix("fix-empty-untyped", f"def {name} : Nat := let e := [] in length Nat e;")
    yield fix("fix-comment-string", f'-- Cons Nat Z (Nil Nat) {seed}\ndef {name} : String := "x <- y;; Cons Nat {seed}";')
    yield fix("fix-shadow-preserved", f"def {name} (x : Nat) : Nat := let x : Nat := Z in x;")
    yield fix("fix-handler-preserved", f"def {name} : Eff Nat := handle perform Ask with | Ask (q) k => k q | pure v => v end;")
    yield fix("fix-alias-binder", f'import "module{seed}.ouro" as cfg;\ndef {name} (cfg : Nat) : Nat := add cfg cfg.limit;', dependencies=dependencies)
    yield fix("fix-alias-collision", f'import "module{seed}.ouro" as tree;\ninductive Tree : Type := | leaf : Tree;\ndef {name} : Nat := Tree.count;', dependencies=dependencies)


FEATURES = tuple(case.name for case in cases(1))

# The standalone mechanical fixer owns this smaller syntax-only contract.
# Binder, match, alias and inferred-type rewrites belong to the native fixer.
SYNTAX_CASES = {"fix-numeral", "fix-small-numeral", "fix-list", "fix-empty",
                "fix-string-list", "fix-open-list", "fix-list-element",
                "fix-duplicate-import", "fix-separator", "fix-legacy-bind", "fix-comment-string"}


def syntax_cases(seed):
    selected = [case for case in cases(seed) if case.name in SYNTAX_CASES]
    yield from selected
    yield TextCase("combined", "fix", "".join(case.source for case in selected),
                   "".join(case.expected for case in selected),
                   tuple(dict(dependency for case in selected for dependency in case.dependencies).items()))


def run_checks(run, directory, saved=None):
    from ourosmith.surface.run import StepFailure

    generated = cases(run.seed)
    if saved is not None and "source" in saved:
        generated = [TextCase(saved["case"], saved["tool"], saved["source"], saved["expected_source"],
                              tuple(tuple(item) for item in saved.get("dependencies", [])))]
    for case in generated:
        run.case_id = f"surface-{run.seed}-{case.name}"
        run.input = {"recipe": "text_tools", "case": case.name, "tool": case.tool,
                     "source": case.source, "expected_source": case.expected,
                     "dependencies": list(case.dependencies)}
        work = directory / case.name
        work.mkdir(parents=True, exist_ok=True)
        path = work / "input.ouro"
        path.write_text(case.source, encoding="utf-8", newline="")
        for filename, contents in case.dependencies:
            dependency = work / filename
            dependency.parent.mkdir(parents=True, exist_ok=True)
            dependency.write_text(contents, encoding="utf-8", newline="")
        prop = "text-" + case.name
        command = [run.tool("ouro-" + case.tool)]
        run.summary.cases += 1
        run.count("features", prop)
        try:
            actual = run.command([*command, path], work, prop)
            run.require(actual.ok and actual.stdout == case.expected, prop, case.expected, run.output(actual))
            checked = run.command([*command, "--check", path], work, prop + "-check")
            code = int(case.source != case.expected)
            run.require(checked.returncode == code, prop + "-check", code, run.output(checked))
            path.write_text(actual.stdout, encoding="utf-8", newline="")
            again = run.command([*command, path], work, prop + "-idempotent")
            run.require(again.ok and again.stdout == case.expected, prop + "-idempotent", case.expected, run.output(again))
            checked = run.command([*command, "--check", path], work, prop + "-clean")
            run.require(checked.ok, prop + "-clean", 0, run.output(checked))
        except StepFailure as failure:
            run.record(failure)
