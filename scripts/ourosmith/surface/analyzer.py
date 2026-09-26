"""Independent node counts for generated analyzer and adapter constructor trees."""
from __future__ import annotations

from dataclasses import dataclass

from ourosmith.surface.library import run_expressions


@dataclass(frozen=True)
class Node:
    tag: str
    arguments: tuple = ()

    def source(self):
        def emit(value):
            if isinstance(value, Node):
                return "(" + value.source() + ")"
            if isinstance(value, tuple):
                return "([" + ", ".join(emit(item) for item in value) + "] : List Ast)"
            return str(value)

        if self.tag == "ANamedCall":
            head, rows = self.arguments
            rendered = ", ".join(
                f"MkPair Nat Ast {label} {emit(value)}" for label, value in rows
            )
            return f"ANamedCall {emit(head)} ([{rendered}] : List (Pair Nat Ast))"
        return " ".join([self.tag, *(emit(arg) for arg in self.arguments)])

    def nodes(self):
        if self.tag == "ARange":
            return 4  # The analyzer exposes both endpoints and the bound as literal children.
        def count(value):
            if isinstance(value, Node):
                return value.nodes()
            if isinstance(value, tuple):
                return sum(count(item) for item in value)
            return 0

        return 1 + sum(count(arg) for arg in self.arguments)


def ast_trees(seed):
    leaf = Node("AVar", (seed % 17 + 1,))
    pair = Node("AApp", (leaf, Node("ANatLit", (seed % 9,))))
    many = tuple(pair for _ in range(seed % 4 + 1))
    ids = "([2, 3] : List Nat)"
    for tag in ("AVar", "AHole", "ASort", "ANatLit", "AStr"):
        yield Node(tag, (seed % 9,))
    for tag in ("ANoBinder", "ANoBranch", "ANoClause"):
        yield Node(tag)
    for tag in ("AApp", "AAscribe", "AMatch", "AHandle"):
        yield Node(tag, (pair, leaf))
    for tag in ("ALam", "APi", "ABinder"):
        yield Node(tag, (1, pair, leaf))
    for tag in ("ALet", "AFix"):
        yield Node(tag, (1, pair, leaf, pair))
    for tag in ("ABranch", "AClause"):
        yield Node(tag, (1, ids, pair, leaf))
    yield Node("APerform", (1, many))
    yield Node("ADo", (many,))
    yield Node("AList", (many,))
    yield Node("AListSpread", (many, leaf))
    yield Node("ARange", (seed % 7, seed % 11, "True"))
    yield Node("ANamedCall", (leaf, ((seed % 7 + 1, pair), (seed % 7 + 2, leaf))))


AST_TAGS = tuple(node.tag for node in ast_trees(1))


def definitions(seed):
    # Share each tree across its observations. Repeating deep literals in
    # every definition needlessly inflates elaboration and extraction work.
    source = "".join(f"def sampleAst{i} : Ast := {tree.source()};\n" for i, tree in enumerate(ast_trees(seed)))
    depth = 257 + seed % 19
    return source + f"""def sampleChain : Ast :=
      (fix chain (n : Nat) : Ast := match n with
        | Z => AVar 7 | S rest => AList ([chain rest] : List Ast) end) {depth};
"""


def rows(seed):
    for i, tree in enumerate(ast_trees(seed)):
        source, size = f"sampleAst{i}", tree.nodes()
        yield f"show_nat (ast_size ({source}))", str(size)
        yield f"show_nat (min_score_nodes (minimal_score ({source})))", str(size)
        yield f'show_nat (fromMaybe Nat 0 (bnd_metric (bounds_metrics ({source})) "nodes"))', str(size)
        yield f"show_bool (alpha_eq ({source}) ({source}))", "true"
    # A path longer than common fixed traversal fuel, built at runtime.
    depth = 257 + seed % 19
    yield "show_nat (ast_size sampleChain)", str(depth + 1)
    yield "show_bool (ast_occurs 7 sampleChain)", "true"
    yield "show_bool (ast_occurs 8 sampleChain)", "false"
    yield "show_nat (df_count_uses 7 sampleChain)", "1"
    for binder, expected in ((7, "0"), (8, "1")):
        yield f"show_nat (df_count_uses 7 (ALam {binder} ANoBinder sampleChain))", expected
    # Empty and populated list payloads, optional annotations, do-bind scope,
    # clauses and multi-match rows exercise the adapter's callback boundaries.
    for expression, size, adapted_size in (
        ("EList (Nil Expr)", 1, 1),
        ("EList ([EVar 7, ENat 1] : List Expr)", 3, 3),
        ("EListSpread (Nil Expr) (EList (Nil Expr))", 2, 2),
        ("EListSpread ([EVar 7] : List Expr) (EVar 8)", 3, 3),
        ("ERange 2 5 True", 1, 4),
        ("ELam 1 (Nothing Expr) (EVar 1)", 2, 3),
        ("ELam 1 (Just Expr (ESort 0)) (EVar 1)", 3, 3),
        ("EDo ([EDoBind 1 (ENat 2), EVar 1] : List Expr)", 4, 6),
        ("EHandle (EVar 1) ([MkPair Nat (Pair (List Nat) Expr) 2 (MkPair (List Nat) Expr (Nil Nat) (EVar 3))] : List (Pair Nat (Pair (List Nat) Expr)))", 3, 5),
        ("EMultiMatch ([EVar 1, EVar 2] : List Expr) ([MkPair (List (Pair Nat (List Nat))) Expr ([MkPair Nat (List Nat) 3 (Nil Nat)] : List (Pair Nat (List Nat))) (EVar 4)] : List (Pair (List (Pair Nat (List Nat))) Expr))", 4, 7),
        ("ENamedCall (EVar 1) ([MkPair Nat Expr 5 (ENat 2)] : List (Pair Nat Expr))", 3, 3),
    ):
        yield f"show_nat (adapt_size ({expression}))", str(size)
        yield f"show_nat (ast_size (adapt ({expression})))", str(adapted_size)
    yield "show_bool (alpha_eq (ANamedCall (AVar 1) ([MkPair Nat Ast 2 (ANatLit 3)] : List (Pair Nat Ast))) (ANamedCall (AVar 1) ([MkPair Nat Ast 4 (ANatLit 3)] : List (Pair Nat Ast))))", "false"


def run_checks(run, directory, saved=None):
    modules = ["tools/analyze/" + name + ".ouro" for name in
               ("ast", "expr_adapt", "minimal", "bounds", "duplication", "dataflow")]
    replay = saved is not None and "source" in saved
    run_expressions(run, directory, "analyzer_ast", [] if replay else list(rows(run.seed)), modules, "analyzer-ast",
                    saved=saved, definitions="" if replay else definitions(run.seed))
    for tag in AST_TAGS:
        run.count("features", "analyzer:" + tag)
