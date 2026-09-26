"""Known-class surface mutations. Codes come from runtime/frontend_link.c.

Each case declares its diagnostic independently of execution. Acceptance,
another error class, crashes, and exhausted process limits are all findings.
"""
from __future__ import annotations

from dataclasses import dataclass

from ourosmith.surface.gen import IDENTITY_IO, PRELUDE


@dataclass(frozen=True)
class Mutation:
    name: str
    source: str
    diagnostics: tuple[str, ...]
    tool: str = "check"
    fuel: int = 999999
    dependencies: tuple[tuple[str, str], ...] = ()


def mutations(seed: int) -> list[Mutation]:
    name, number = f"bad{seed}", seed % 5
    prefix = PRELUDE
    rows = [
        Mutation("lex-trailing-invalid", prefix + f"def {name} : Nat := {number};\n@", ("CErr code=11",)),
        Mutation("lex-unterminated-string", prefix + f'def {name} : String := "unfinished', ("CErr code=11",)),
        Mutation("lex-bare-operator", prefix + "-", ("CErr code=11",)),
        Mutation("lex-fuel", prefix + f"def {name} : Nat := {number};", ("CErr code=12",), fuel=0),
        Mutation("checker-fuel", """inductive Nat : Type := | Z : Nat | S : Nat -> Nat;
def type_after : Nat -> Type :=
  fix go (count : Nat) : Type :=
    match count with | Z => Nat | S rest => go rest end;
def value : type_after 300 := Z;
def result : Nat := value;
""", ("CErr code=44",), fuel=300),
        Mutation("parse-missing-colon", prefix + f"def {name} Nat := Z;", ("CErr code=1", "CErr code=10")),
        Mutation("type-mismatch", prefix + f"def {name} : Nat := True;", ("CErr code=41",)),
        Mutation("definition-self-reference", prefix + f"def {name} : Nat := {name};", ("CErr code=41",)),
        Mutation("effect-root-body-type", prefix + "effect Counter where\n  | step : Nat -> Nat\n"
                 + f"def {name} : Nat := True;", ("CErr code=41",)),
        Mutation("effect-root-assumption-type", prefix + "effect Counter where\n  | step : Nat -> Nat\n"
                 + f"axiom {name} : Z;", ("CErr code=42",)),
        Mutation("sort-expected", prefix + f"def {name} : Z := Z;", ("CErr code=42",)),
        Mutation("unknown-intrinsic", prefix + f'intrinsic {name} : Type := "ouro.unknown.{seed}";', ("CErr code=47",)),
        Mutation("duplicate-intrinsic-type", prefix + f'intrinsic {name} : Type := "ouro.string";', ("CErr code=45",)),
        Mutation("do-case-branch-type", prefix + IDENTITY_IO + f"""def {name} (flag : Bool) : IO Nat :=
  do let! value := match flag with
       | True => do io_pure Unit MkUnit; io_pure Bool True
       | False => io_pure Nat {number}
       end;
     io_pure Nat value
""", ("CErr code=41",)),
        Mutation("positivity", prefix + "inductive Bad : Type := | MkBad : (Bad -> Nat) -> Bad;", ("CErr code=43",)),
        Mutation("duplicate-declaration", prefix + f"def {name} : Nat := Z;\ndef {name} : Nat := S Z;", ("CErr code=3",)),
        Mutation("unbound", prefix + f"def {name} : Nat := missing{seed};", ("CErr code=2",)),
        Mutation("unknown-operation", prefix + f"def {name} : Nat := perform missing{seed} (Z);", ("CErr code=41",)),
        Mutation("non-function", prefix + f"def {name} : Nat := Z Z;", ("CErr code=41",)),
        Mutation("coverage", prefix + f"def {name} (n : Nat) : Nat := match n with | Z => Z end;", ("CErr code=2",)),
        Mutation("termination", prefix + f"def {name} : Nat -> Nat := fix loop (n : Nat) : Nat := loop n;", ("CErr code=41",)),
        Mutation("non-inductive", prefix + f"def {name} (f : Nat -> Nat) : Nat := match f with | Z => Z | S n => n end;", ("CErr code=41",)),
        Mutation("unknown-constructor", prefix + f"def {name} (n : Nat) : Nat := match n with | Z => Z | Missing k => k end;", ("CErr code=2",)),
        Mutation("constructor-pattern-arity", prefix + f"def {name} (n : Nat) : Nat := match n with | Z => Z | S a b => add a b end;", ("CErr code=2",)),
        Mutation("lambda-domain", prefix + f"def {name} : Nat -> Nat := fun (n : Bool) => n;", ("CErr code=41",)),
        Mutation("applied-lambda-domain", prefix + f"def {name} : Nat := (fun (flag : Bool) => match flag with | True => Z | False => S Z end) {number};", ("CErr code=41",)),
        Mutation("applied-lambda-branch", prefix + f"def {name} : Nat := (fun (value : Nat) => match False with | True => value | False => True end) {number};", ("CErr code=41",)),
        Mutation("lambda-argument-domain", prefix + "def apply (f : Nat -> Nat) : Nat := f Z;\n"
                 + f"def {name} : Nat := apply (fun (n : Bool) => n);", ("CErr code=41",)),
        Mutation("case-branch-type", prefix + f"def {name} (n : Nat) : Nat := match n with | Z => True | S k => k end;", ("CErr code=41",)),
        Mutation("case-lambda-domain", prefix + f"def {name} (n : Nat) : Nat -> Nat := match n with | Z => fun (b : Bool) => b | S k => fun (x : Nat) => add k x end;", ("CErr code=41",)),
        Mutation("termination-escape", prefix + "def call (f : Nat -> Nat) (n : Nat) : Nat := f n;\n"
                 + f"def {name} : Nat -> Nat := fix loop (n : Nat) : Nat := call loop n;", ("CErr code=41",)),
        Mutation("termination-unchanged", prefix + f"def {name} : Nat -> Nat := fix loop (n : Nat) : Nat := match n with | Z => Z | S k => add k (loop n) end;", ("CErr code=41",)),
        Mutation("anonymous-hole", prefix + f"def {name} : Nat := _;", ("CErr code=2",)),
        Mutation("named-hole", prefix + f"def {name} : Nat := ?goal{seed};", ("OURO-HOLE-001",)),
        Mutation("pipe-missing-rhs", prefix + f"def {name} : Nat := Z |>;", ("OURO-PIPE-001",)),
        Mutation("list-context", prefix + f"def {name} : Nat := [];", ("OURO-LIST-001",)),
        Mutation("list-trailing-comma", prefix + "inductive List (A : Type) : Type := | Nil : List A | Cons : A -> List A -> List A;\n"
                 + f"def {name} : List Nat := [Z,];", ("OURO-LIST-002",)),
        Mutation("do-outside", prefix + f"def {name} : Nat := let! x := Z; x;", ("OURO-DO-001",)),
        Mutation("record-malformed", prefix + "record Point : Type where x Nat; end;", ("OURO-REC-001",)),
        Mutation("record-duplicate", prefix + "record Point : Type where x : Nat; x : Nat; end;", ("OURO-REC-002",)),
        Mutation("record-no-context", prefix + "record Point : Type where x : Nat; end;\n" + f"def {name} : Nat := {{ x := Z }};", ("OURO-REC-003",)),
        Mutation("record-missing", prefix + "record Point : Type where x : Nat; y : Nat; end;\ndef p : Point := { x := Z };", ("OURO-REC-004",)),
        Mutation("record-unknown", prefix + "record Point : Type where x : Nat; end;\ndef p : Point := { x := Z, y := Z };", ("OURO-REC-005",)),
        Mutation("record-collision", prefix + "def Point_x : Nat := Z;\nrecord Point : Type where x : Nat; end;", ("OURO-REC-006",)),
        Mutation("record-projection", prefix + "record Point : Type where x : Nat; end;\ndef p : Point := { x := Z };\ndef bad : Nat := p.y;", ("OURO-REC-007",)),
    ]
    for kind, target, abi in (("target", "unsupported-host", "win64"),
                              ("abi", "windows-x86_64", "unsupported-abi")):
        rows.append(Mutation("extern-unsupported-" + kind, prefix + f'''intrinsic NativeWord : Type := "ouro.u32";
intrinsic HostAction : Type -> Type := "ouro.runtime";
extern {name} : HostAction NativeWord :=
  "{target}" "{abi}" "kernel32.dll" "GetCurrentProcessId" "nogc";
''', ("CErr code=47",)))
    for mode, binders, inner, arguments, escaped in (
        ("unchanged-initial", "(x : Nat)", "outer x", "n", False),
        ("growing-inner", "(x : Nat)", "walk x", "k", False),
        ("growing-other-parameter", "(x : Nat) (y : Nat)",
         "match x with | Z => outer y | S rest => walk rest (S (S n)) end", "k k", False),
        ("captured-unchanged", "(x : Nat)", "outer n", "k", False),
        ("partial-escape", "(x : Nat)",
         "match x with | Z => outer x | S rest => walk rest end", "k", True),
        ("argument-escape", "(x : Nat) (carry : Nat -> Nat)",
         "match x with | Z => outer x | S rest => walk rest carry end", "k outer", False),
    ):
        nested = f"(fix walk {binders} : Nat := {inner})"
        call = (f"let saved : Nat -> Nat := {nested} in saved {arguments}" if escaped
                else f"{nested} {arguments}")
        source = prefix + f"""def {name} : Nat -> Nat :=
  fix outer (n : Nat) : Nat :=
    match n with | Z => Z | S k => {call} end;
"""
        rows.append(Mutation("termination-nested-" + mode, source, ("CErr code=41",)))
    dep = (("dep.ouro", "inductive Nat : Type := | Z : Nat | S : Nat -> Nat;\ndef one : Nat := S Z;\n"),)
    for kind, declaration, diagnostic in (
        ("body-type", f"def {name} : Nat := True;", "CErr code=41"),
        ("assumption-type", f"axiom {name} : Z;", "CErr code=42"),
        ("positivity", "inductive Bad : Type := | MkBad : (Bad -> Nat) -> Bad;", "CErr code=43"),
    ):
        imported = PRELUDE + declaration + "\n"
        rows.append(Mutation("import-" + kind, 'import "dep.ouro";\ndef result : Nat := Z;',
                             (diagnostic,), dependencies=(("dep.ouro", imported),)))
        rows.append(Mutation("import-transitive-" + kind, 'import "middle.ouro";\ndef result : Nat := Z;',
                             (diagnostic,), dependencies=(("middle.ouro", 'import "dep.ouro";\n'),
                                                          ("dep.ouro", imported))))
    for kind, text, code in (
        ("import-malformed", 'import "dep.ouro" as;\ndef bad : Nat := Z;', "001"),
        ("import-duplicate", 'import "dep.ouro" as N;\nimport "dep.ouro" as N;\ndef bad : Nat := N.Z;', "002"),
        ("import-unknown", 'import "dep.ouro";\nopen Missing;\ndef bad : Nat := Z;', "003"),
        ("import-reserved", 'import "dep.ouro" as def;\ndef bad : Nat := Z;', "004"),
    ):
        rows.append(Mutation(kind, text, ("OURO-IMP-" + code,), dependencies=dep))
        if kind != "import-malformed":
            rows.append(Mutation("lint-" + kind, text, ("OURO-IMP-" + code,), tool="lint", dependencies=dep))
    rows.extend((
        Mutation("module-unknown-direct-member",
                 'import "dep.ouro" as D;\ndef bad : Type := D.Missing;',
                 ("CErr code=95",), dependencies=(("dep.ouro", "axiom Present : Type;"),)),
        Mutation("module-ambiguous-short-name",
                 'import "left.ouro" as L;\nimport "right.ouro" as R;\ndef bad : Type := Shared;',
                 ("CErr code=96",),
                 dependencies=(("left.ouro", "axiom Shared : Type;"),
                               ("right.ouro", "axiom Shared : Type;"))),
        Mutation("module-qualified-declaration-head",
                 'import "dep.ouro" as D;\ndef D.Forged : Type := Type;',
                 ("CErr code=98",), dependencies=(("dep.ouro", "axiom Present : Type;"),)),
    ))
    for kind, text, rule in (
        ("lint-import-malformed", f'import "missing{seed}.ouro" as;\ndef {name} : Nat := Z;', "OURO-IMP-001"),
        ("lint-hole", f"def {name} : Nat := _;", "hole:"),
        ("lint-unbound", f"def {name} : Nat := missing{seed};", "unbound:"),
        ("lint-unused", f"def {name} (unused : Nat) : Nat := Z;", "unused:"),
        ("lint-helper-unused", f"def {name} : Nat := let helper (unused : Nat) : Nat := Z in helper Z;", "OURO-LINT003"),
        ("lint-helper-shadow", f"def {name} (value : Nat) : Nat := let helper (value : Nat) : Nat := value in helper value;", "OURO-LINT004"),
        ("lint-shadow", f"def {name} (x : Nat) : Nat := let x : Nat := x in x;", "shadow:"),
        ("lint-arity", f"def {name} (n : Nat) : Nat := match n with | Z => Z | S => Z end;", "ctor-arity:"),
        ("lint-redundant", f"def {name} (n : Nat) : Nat := match n with | Z => Z | Z => Z | S k => k end;", "redundant-branch:"),
        ("lint-dup-binder", f"def {name} : Nat -> Nat := fix go (go : Nat) : Nat := go;", "dup-binder:"),
        ("lint-non-rec-fix", f"def {name} : Nat -> Nat := fix go (n : Nat) : Nat := n;", "non-rec-fix:"),
        ("lint-unknown-ctor", f"def {name} (n : Nat) : Nat := match n with | Z => Z | Suc k => k end;", "unknown-ctor:"),
        ("lint-mixed-ctors", f"def {name} (n : Nat) : Nat := match n with | Z => Z | True => Z end;", "mixed-ctors:"),
        ("lint-partial", f"def {name} (n : Nat) : Nat := match n with | Z => Z end;", "partial-match:"),
        ("lint-unreachable", f"def {name} (a : Nat) (b : Nat) : Nat := match a, b with | Z, Z => Z | Z, Z => Z | Z, S n => n | S n, Z => n | S n, S m => add n m end;", "unreachable-arm:"),
        ("lint-ctor-app-arity", f"def {name} : Nat := S Z Z;", "ctor-app-arity:"),
        ("lint-match-hole", f"def {name} : Nat := match _ with | Z => Z | S n => n end;", "match-on-hole:"),
        ("lint-match-literal", f"def {name} : Nat := match {number} with | Z => Z | S n => n end;", "match-on-lit:"),
        ("lint-match-sort", f"def {name} : Nat := match Type with | Z => Z | S n => n end;", "match-on-sort:"),
        ("lint-shadow-ctor", f"def {name} (Z : Nat) : Nat := Z;", "shadow-ctor:"),
    ):
        rows.append(Mutation(kind, prefix + text, (rule,), tool="lint"))
    return rows


def contract() -> dict:
    return {m.name: {"tool": m.tool, "diagnostics": list(m.diagnostics),
                     "source": "runtime/frontend_link.c" if m.tool == "check" else
                     "tools/lint_host.ouro" if m.name.startswith("lint-import-") else "compiler/lint.ouro"}
            for m in mutations(1)}
