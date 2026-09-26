"""Source-parser ABI and grammar observations with construction-owned oracles."""
from __future__ import annotations

from ourosmith.surface.library import run_expressions

MODES = """MExpr MPipe MPipeTail MPi MApp MAppTail MAtom MParen MFun MLet MMatch MFix
MTypedBinder MTypedBinderGroup MTypedBinders MFunBinders MPattern MPatternVars
MPatterns MMultiBranches MScrutList MKeywordAtom MEffectAnnotation MEffectRow
MCommaList MListElems MListTail MIdentCommaList MDoExprs MPerform MDo MHandle
MHandleClauses MPiFromApp MDoStmt""".split()

# This is an observation schema, not a parser or a copy of its decision logic.
# The exercised expression payloads distinguish a changed AST from a success
# with the right token count. The existing inventory gate owns schema coverage.
EXPRS = {
    "EVar": ["Nat"], "EHole": ["Maybe Nat"], "ESort": ["Nat"], "ENat": ["Nat"],
    "EApp": ["Expr", "Expr"], "ELam": ["Nat", "Maybe Expr", "Expr"],
    "EPi": ["Nat", "Expr", "Expr"], "ELet": ["Nat", "Maybe Expr", "Expr", "Expr"],
    "EAscribe": ["Expr", "Expr"], "EMatch": ["Expr", "Expr"],
    "EFix": ["Nat", "Expr", "Expr", "Expr"], "EEffectRow": ["Expr", "List Nat"],
    "EPerform": ["Nat", "List Expr"], "EDo": ["List Expr"],
    "EHandle": ["Expr", "List (Pair Nat (Pair (List Nat) Expr))"],
    "EBranch": ["List Nat", "Expr", "Expr"], "ENoBranch": [],
    "EBinder": ["Nat", "Expr", "Expr"], "ENoBinder": [],
    "EMultiMatch": ["List Expr", "List (Pair (List (Pair Nat (List Nat))) Expr)"],
    "EStr": ["Nat"], "EDoBind": ["Nat", "Expr"], "EList": ["List Expr"],
    "ESpan": ["Nat", "Nat", "Expr"], "EOpen": ["Nat", "Expr"],
    "EFallible": ["Expr", "Nat", "Nat", "Expr"],
    "EListSpread": ["List Expr", "Expr"],
    "ERange": ["Nat", "Nat", "Bool"],
    "ENamedCall": ["Expr", "List (Pair Nat Expr)"],
}


def printer(type_name):
    if type_name == "Nat":
        return "show_nat"
    if type_name == "Bool":
        return "show_bool"
    if type_name == "Expr":
        return "(fun (child : Expr) => observe_expr remaining child)"
    # Compound payloads not constructed by this recipe still need exhaustive
    # matches, but their contents are irrelevant to its expected observations.
    if "Pair" in type_name:
        return f'(fun (unused : {type_name}) => "compound")'
    container, item = type_name.split(" ", 1)
    return f"(show_{container.lower()} ({item}) {printer(item)})"


def definitions():
    arms = []
    for constructor, fields in EXPRS.items():
        names = [f"field{i}" for i in range(len(fields))]
        pieces = [f'"{constructor}("']
        for index, (name, type_name) in enumerate(zip(names, fields, strict=True)):
            if index:
                pieces.append('","')
            pieces.append(f"({printer(type_name)} {name})")
        expression = '")"'
        for piece in reversed(pieces):
            expression = f"str_concat {piece} ({expression})"
        arms.append(f"| {constructor} {' '.join(names)} => {expression}")
    return ("def observe_expr : Nat -> Expr -> String :=\n"
            "fix observe_expr (fuel : Nat) (expr : Expr) : String := match fuel with\n"
            '| Z => "exhausted"\n| S remaining => match expr with\n'
            + "\n".join(arms) + "\nend end;\n" + '''
def observe_parse (result : ParseResult Value) : String :=
  match result with
  | PErr pos => str_concat "error:" (show_nat pos)
  | POk value rest pos =>
      match asExpr value with
      | Nothing => "wrong-value-kind"
      | Just expr => str_cat4 (observe_expr 40 expr) ":" (show_nat pos)
          (str_concat ":" (show_list Nat show_nat (map Token Nat token_tag rest)))
      end
  end;
''')


def rows(seed):
    n = seed % 9 + 1
    tokens = [f"TIdent {n}", f"TNat {n}", f"TKeyword {n}", f"TType {n}",
              "TColon", "TColonEq", "TArrow", "TFatArrow", "TBar", "TLparen", "TRparen", "TSemi",
              "THole (Nothing Nat)", f"TString {n}", "TComma", "TBraceL", "TBraceR", "TExclam",
              "TEof", "TBind", "TPipe", "TBracketL", "TBracketR", "TDotDot", "TDotDotEq"]
    observations = []
    accessors = []
    expected_tokens = []
    for token in [*tokens, f"THole (Just Nat {n})"]:
        tag = 12 if token.startswith("THole") else tokens.index(token)
        observations.append((f"show_nat (token_tag ({token}))", str(tag)))
        for getter, expected_tag in (("Ident", 0), ("Nat", 1), ("Keyword", 2), ("Type", 3), ("String", 13)):
            observations.append((f"show_maybe Nat show_nat (tokenIs{getter} ({token}))",
                                 f"just({n})" if tag == expected_tag else "none"))
        hole = "none" if tag != 12 else ("just(none)" if "Nothing" in token else f"just(just({n}))")
        observations.append((f"show_maybe (Maybe Nat) (show_maybe Nat show_nat) (tokenIsHole ({token}))", hole))
        binder = f"just({n})" if tag == 0 else ("just(0)" if token == tokens[12] else "none")
        observations.append((f"show_maybe Nat show_nat (tokenIsBinderName ({token}))", binder))
        observations.append((f"show_bool (is_binder_name ({token}))", "false" if binder == "none" else "true"))
        token_rows = observations[-9:]
        expected_tokens.append(":".join(value for _, value in token_rows))
        if not accessors:
            accessors = [expression.replace(f"({token})", "token") for expression, _ in token_rows]
    token_source = "([" + ", ".join(f"({token})" for token in [*tokens, f"THole (Just Nat {n})"]) + "] : List Token)"
    observer = '(fun (token : Token) => str_join ":" ([' + ", ".join(accessors) + '] : List String))'
    observations = [(f"show_list Token {observer} {token_source}", "[" + ", ".join(expected_tokens) + "]")]
    modes = "([" + ", ".join(MODES) + "] : List Mode)"
    observations.append((f"show_list Mode (fun (mode : Mode) => observe_parse (parse 0 mode ([TNat {n}] : List Token) {n} (VNat 0))) {modes}",
                         "[" + ", ".join(f"error:{n}" for _ in MODES) + "]"))
    cases = [
        ([f"TNat {n}"], f"ENat({n})"), ([f"TIdent {n}"], f"EVar({n})"),
        (["TNat 1", "TDotDot", "TNat 2"], "ERange(1,2,false)"),
        (["TNat 1", "TDotDotEq", "TNat 2"], "ERange(1,2,true)"),
        (["TType 2"], "ESort(2)"), ([tokens[12]], "EHole(none)"),
        ([f"THole (Just Nat {n})"], f"EHole(just({n}))"), ([f"TString {n}"], f"EStr({n})"),
        ([f"TIdent {n}", "TNat 2"], f"EApp(EVar({n}),ENat(2))"),
        (["TNat 1", "TPipe", f"TIdent {n}"], f"EApp(EVar({n}),ENat(1))"),
        (["TType 0", "TArrow", "TType 1"], "EPi(0,ESort(0),ESort(1))"),
        (["TLparen", "TNat 1", "TRparen"], "ENat(1)"),
        (["TKeyword kwFun", f"TIdent {n}", "TFatArrow", f"TIdent {n}"], f"ELam({n},none,EVar({n}))"),
        (["TKeyword kwLet", f"TIdent {n}", "TColonEq", "TNat 2", "TKeyword kwIn", f"TIdent {n}"], f"ELet({n},none,ENat(2),EVar({n}))"),
        (["TKeyword kwOpen", f"TIdent {n}", "TKeyword kwIn", f"TIdent {n}"], f"EOpen({n},EVar({n}))"),
        (["TBracketL", "TNat 1", "TComma", "TNat 2", "TBracketR"], "EList([ENat(1), ENat(2)])"),
        (["TBracketL", "TNat 1", "TComma", "TDotDot", f"TIdent {n}", "TBracketR"],
         f"EListSpread([ENat(1)],EVar({n}))"),
        (["TBracketL", "TDotDot", f"TIdent {n}", "TComma", "TBracketR"],
         f"EListSpread([],EVar({n}))"),
    ]
    for body, expected in cases:
        token_list = "([" + ", ".join(f"({token})" for token in [*body, "TSemi"]) + "] : List Token)"
        observations.append((f"observe_parse (parse 300 MExpr {token_list} {n} (VNat 0))", f"{expected}:{n + len(body)}:[11]"))
    for body in ([], ["TNat 1", "TDotDot"], ["TNat 1", "TDotDotEq"],
                 ["TNat 1", "TArrow"], ["TLparen", "TNat 1"], ["TKeyword kwFun"]):
        token_list = "([" + ", ".join(f"({token})" for token in body) + "] : List Token)"
        observations.append((f"observe_parse (parse 300 MExpr {token_list} {n} (VNat 0))", f"error:{n + len(body)}"))
    observations.append((f"observe_expr 40 (ESpan {n} {n + 3} (ESpan {n + 1} {n + 2} (ENat {n})))",
                         f"ESpan({n},{n + 3},ESpan({n + 1},{n + 2},ENat({n})))"))
    # The public source fuel also bounds lexing. Exercise the resolver's own
    # exhaustion branch directly and map its result through the public error.
    observations.append((
        'match module_rewrite_decls 0 [] [] [] [] [] [] with '
        '| RErr code detail => match import_err Nat code detail with '
        '| CErr error => match error with | ErrCode mapped at => '
        'str_concat (show_nat mapped) (str_concat "/" (show_nat at)) end '
        '| COk _ => "accepted" end | ROk _ => "accepted" end',
        "97/0"))
    observations.append((f"observe_expr 40 (EFallible (EVar {n}) {n + 1} {n + 2} (ENat {n}))",
                         f"EFallible(EVar({n}),{n + 1},{n + 2},ENat({n}))"))
    return observations


def run_checks(run, directory, saved=None):
    run_expressions(run, directory, "parser_contract", rows(run.seed),
                    ("compiler/parser_parse.ouro", "compiler/pipeline.ouro"), "parser-contract",
                    saved=saved, definitions=definitions())
    run.count("features", "parser:abi-and-grammar")
    if saved is None or "module_rewrite_decls 0" in saved.get("source", ""):
        run.count("features", "module-resolution-fuel")
