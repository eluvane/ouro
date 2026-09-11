"""Small typed AST, source printer, and reference interpreter.

The interpreter uses Python values and lexical environments; it does not
call the compiler, inspect emitted core, or share the compiler's evaluator.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace

from ourosmith.rng import Rng

PRELUDE = """inductive Nat : Type :=
  | Z : Nat
  | S : Nat -> Nat;

representation Nat := "ouro.nat";

inductive Bool : Type :=
  | True : Bool
  | False : Bool;

intrinsic String : Type := "ouro.string";
intrinsic prim_string_length : String -> Nat := "ouro.string.length";

def add : Nat -> Nat -> Nat :=
  fix add (n : Nat) (m : Nat) : Nat :=
    match n with | Z => m | S k => S (add k m) end;

"""

FEATURES = ("literal", "var", "succ", "add", "let", "lambda", "match", "if", "ascribe", "pipe", "string-length")

# A pure identity monad exercises do lowering without granting the generated
# program host IO. Its result is independently just the final supplied value.
IDENTITY_IO = """inductive Unit : Type := | MkUnit : Unit;
def IO (A : Type) : Type := A;
def io_pure (A : Type) (value : A) : IO A := value;
def io_bind (A : Type) (B : Type) (value : IO A) (next : A -> IO B) : IO B := next value;
"""


@dataclass(frozen=True)
class Expr:
    tag: str
    args: tuple[Expr, ...] = ()
    value: int | str | bool = 0
    name: str = ""
    ty: str = "Nat"

    def json(self):
        return asdict(self)

    @classmethod
    def from_json(cls, data):
        return cls(data["tag"], tuple(cls.from_json(arg) for arg in data.get("args", [])),
                   data.get("value", 0), data.get("name", ""), data.get("ty", "Nat"))


def evaluate(expr: Expr, env: dict | None = None):
    env = {} if env is None else env
    tag, args = expr.tag, expr.args
    if tag == "literal":
        return expr.value
    if tag == "var":
        return env[expr.name]
    if tag in {"succ", "pipe"}:
        return evaluate(args[0], env) + 1
    if tag == "add":
        return evaluate(args[0], env) + evaluate(args[1], env)
    if tag in {"let", "lambda"}:
        return evaluate(args[1], {**env, expr.name: evaluate(args[0], env)})
    if tag == "match":
        value = evaluate(args[0], env)
        return evaluate(args[1], env) if value == 0 else evaluate(args[2], {**env, expr.name: value - 1})
    if tag == "if":
        return evaluate(args[1] if evaluate(args[0], env) else args[2], env)
    if tag == "ascribe":
        return evaluate(args[0], env)
    if tag == "string-length":
        return len(evaluate(args[0], env).encode("utf-8"))
    raise ValueError(f"unknown surface expression {tag}")


def print_expr(expr: Expr) -> str:
    tag, args = expr.tag, expr.args
    printed = [print_expr(arg) for arg in args]
    if tag == "literal":
        if expr.ty == "Bool":
            return "True" if expr.value else "False"
        if expr.ty == "String":
            return json.dumps(expr.value, ensure_ascii=True)
        return str(expr.value)
    if tag == "var":
        return expr.name
    if tag == "succ":
        return f"(S {printed[0]})"
    if tag == "add":
        return f"(add {printed[0]} {printed[1]})"
    if tag == "let":
        return f"(let {expr.name} : Nat := {printed[0]} in {printed[1]})"
    if tag == "lambda":
        return f"((fun ({expr.name} : Nat) => {printed[1]}) {printed[0]})"
    if tag == "match":
        return f"(match {printed[0]} with | Z => {printed[1]} | S {expr.name} => {printed[2]} end)"
    if tag == "if":
        return f"(match {printed[0]} with | True => {printed[1]} | False => {printed[2]} end)"
    if tag == "ascribe":
        return f"({printed[0]} : Nat)"
    if tag == "pipe":
        return f"({printed[0]} |> S)"
    if tag == "string-length":
        return f"(prim_string_length {printed[0]})"
    raise ValueError(f"unknown surface expression {tag}")


def validate(expr: Expr, env: dict[str, str] | None = None) -> str:
    """Check generator invariants without consulting compiler acceptance."""
    env = {} if env is None else env
    if expr.tag == "literal":
        expected = {"Nat": int, "Bool": bool, "String": str}.get(expr.ty)
        if expected is None or type(expr.value) is not expected or (expr.ty == "Nat" and expr.value < 0):
            raise ValueError("invalid typed literal")
    elif expr.tag == "var":
        if env.get(expr.name) != expr.ty:
            raise ValueError("ill-scoped variable")
    else:
        arities = {"succ": 1, "pipe": 1, "add": 2, "let": 2, "lambda": 2,
                   "match": 3, "if": 3, "ascribe": 1, "string-length": 1}
        if len(expr.args) != arities.get(expr.tag) or expr.ty != "Nat":
            raise ValueError("invalid typed expression")
        for index, arg in enumerate(expr.args):
            local = env
            if (expr.tag in {"let", "lambda"} and index == 1) or (expr.tag == "match" and index == 2):
                if not expr.name or expr.name in env:
                    raise ValueError("invalid binder")
                local = {**env, expr.name: "Nat"}
            want = "Bool" if expr.tag == "if" and index == 0 else "String" if expr.tag == "string-length" else "Nat"
            if validate(arg, local) != want:
                raise ValueError("argument type mismatch")
    return expr.ty


def features(expr: Expr) -> set[str]:
    return {expr.tag}.union(*(features(arg) for arg in expr.args))


def generate(seed: int, depth: int = 4) -> Expr:
    rng = Rng(seed)
    counter = 0

    def term(fuel):
        nonlocal counter
        if fuel <= 0:
            return Expr("literal", value=rng.below(5))
        tag = rng.choice([f for f in FEATURES if f not in {"var", "literal"}])
        if tag == "string-length":
            return Expr(tag, (Expr("literal", value=rng.choice(["", "ouro", "a\nb", 'a"b', "a\\b"]), ty="String"),))
        if tag in {"succ", "pipe", "ascribe"}:
            return Expr(tag, (term(fuel - 1),))
        if tag == "add":
            return Expr(tag, (term(fuel - 1), term(fuel - 1)))
        if tag == "if":
            return Expr(tag, (Expr("literal", value=bool(rng.below(2)), ty="Bool"), term(fuel - 1), term(fuel - 1)))
        name = f"v{counter}"
        counter += 1
        used = Expr("add", (Expr("var", name=name), term(fuel - 1)))
        if tag == "match":
            scrutinee = term(fuel - 1)
            # Literal scrutinees deliberately trigger match-on-lit. The clean
            # generator supplies a computed value; that lint has its own
            # negative strategy.
            if scrutinee.tag == "literal":
                scrutinee = Expr("add", (Expr("literal", value=0), scrutinee))
            return Expr(tag, (scrutinee, term(fuel - 1), used), name=name)
        return Expr(tag, (term(fuel - 1), used), name=name)

    expr = term(depth)
    validate(expr)
    return expr


def program(expr: Expr, name: str = "result") -> str:
    validate(expr)
    return PRELUDE + f"-- Computed natural used by the runtime oracle.\ndef {name} : Nat := {print_expr(expr)};\n"


def nat_output(value: int) -> str:
    if not value:
        return "Z : Nat\n"
    return "S " + "(S " * (value - 1) + "Z" + ")" * (value - 1) + " : Nat\n"


def alpha_rename(expr: Expr) -> Expr:
    return Expr(expr.tag, tuple(alpha_rename(arg) for arg in expr.args), expr.value,
                "renamed_" + expr.name if expr.name else "", expr.ty)


def shrink_candidates(expr: Expr, env: dict[str, str] | None = None):
    """Typed, closed candidates; the runner must recheck the same failure."""
    env = {} if env is None else env
    yield Expr("literal", value={"Nat": 0, "Bool": False, "String": ""}[expr.ty], ty=expr.ty)
    if expr.tag == "literal" and expr.ty == "Nat" and expr.value:
        yield Expr("literal", value=expr.value // 2)
    for child in expr.args:
        if child.ty == expr.ty:
            try:
                validate(child, env)
            except ValueError:
                continue
            yield child
    for index, child in enumerate(expr.args):
        local = env
        if (expr.tag in {"let", "lambda"} and index == 1) or (expr.tag == "match" and index == 2):
            local = {**env, expr.name: "Nat"}
        for smaller in shrink_candidates(child, local):
            candidate = replace(expr, args=expr.args[:index] + (smaller,) + expr.args[index + 1:])
            try:
                validate(candidate, env)
            except ValueError:
                continue
            yield candidate


def shrink(expr: Expr, still_fails, budget: int):
    """Minimize a closed typed expression while preserving the exact finding."""
    attempts = 0
    while attempts < budget:
        size = len(json.dumps(expr.json(), sort_keys=True))
        for candidate in shrink_candidates(expr):
            if not lint_clean(candidate):
                continue
            if len(json.dumps(candidate.json(), sort_keys=True)) >= size:
                continue
            attempts += 1
            if still_fails(candidate):
                expr = candidate
                break
            if attempts >= budget:
                return expr, attempts
        else:
            break
    return expr, attempts


def lint_clean(expr: Expr) -> bool:
    """Preserve the clean-generator contract while shrinking another property."""
    def uses(term, name):
        return (term.tag == "var" and term.name == name) or any(uses(arg, name) for arg in term.args)

    if expr.tag in {"lambda", "let"} and not uses(expr.args[1], expr.name):
        return False
    if expr.tag == "match" and expr.args[0].tag == "literal":
        return False
    if expr.tag == "match" and not uses(expr.args[2], expr.name):
        return False
    return all(lint_clean(arg) for arg in expr.args)
