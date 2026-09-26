#!/usr/bin/env python3
"""Python structural-quality owner with a frozen lex/extraction oracle.

The lex/extraction routines retain the pre-migration implementation compared by
scripts/structural_lex_parity.py. Dependency discovery shares the host collector.
The public entry scripts/structural_quality.py is a thin launcher plus
compatibility re-exports; scripts/structural_quality_suite.py exercises this
reference through those re-exports without modification.

Cross-file structural pass for the existing strict quality firewall.

Python bodies use the standard AST. Other languages use lossless lexical
regions, binding/operation fingerprints and a repository reference index; this
is deliberately not a second compiler. Exact evidence keeps globals, operators,
types and literals. Semantic candidates never assert program equivalence.
"""
from __future__ import annotations

import ast
import collections
import hashlib
import json
import posixpath
import re
import subprocess
import sys
import tokenize
import io
from dataclasses import dataclass, field
from pathlib import Path

from repo_support import write_json_atomic
from selfhost_module_cache import quoted_import_targets

KIND = "ouro.structural-quality.v1"
SOURCE_SUFFIXES = {".ouro", ".py", ".sh", ".c", ".h", ".ml", ".mli"}
CATEGORIES = {"independent-oracle", "trust-boundary", "bootstrap-seed",
              "public-compatibility", "platform-adapter", "generated-artifact",
              "performance-specialization"}
MARKER = "ouro-structural:"
IDENT = re.compile(r"[A-Za-z_][A-Za-z_0-9']*\Z")
WORD = re.compile(r"[A-Za-z_][A-Za-z_0-9']*")
OPERATORS = (":=", "=>", "->", "<-", "|>", "&&", "||", "==", "!=", "<=", ">=",
             "::", "++", "--", "<<", ">>", "+=", "-=", "...", "${", "$(")
CONTROL = {"match", "with", "end", "fix", "if", "then", "else", "elif", "fi",
           "case", "esac", "for", "while", "try", "except", "return", "raise",
           "switch", "do", "done", "break", "continue", "catch", "finally"}
RESERVED = CONTROL | {"let", "in", "fun", "rec", "def", "inductive", "record",
                      "axiom", "import", "as", "Type", "type", "and", "of",
                      "static", "const", "unsigned", "signed", "struct", "void"}
PURPOSES = {
    "path": ({"path", "canon", "canonical", "normalize", "confinement", "realpath"},
             {"path", "resolve", "realpath", "relative", "is_absolute", "normpath", "prim_fs_realpath", "path_normalize"}),
    "walk": ({"walk", "files", "sources", "collect", "traverse"},
             {"rglob", "glob", "listdir", "walk", "iterdir", "prim_fs_list_dir", "fs_list_dir", "readdir"}),
    "parser": ({"parse", "parser", "manifest", "seal", "semver", "grammar", "decode"},
               {"split", "loads", "parse", "lex_all", "token_tag", "parse_import_line", "str_split_lines", "str_trim"}),
    "graph": ({"dfs", "bfs", "cycle", "topological", "reachability", "reachable", "closure", "traversal", "collect"},
              {"seen", "visited", "pending", "edges", "stack", "queue", "work", "append", "add", "mem"}),
    "process": ({"run", "exec", "process", "spawn", "command", "timeout", "returncode"},
                {"run", "Popen", "returncode", "stdout", "stderr", "wait", "prim_proc_exec", "proc_exec"}),
    "config": ({"config", "option", "options", "env", "setting", "defaults", "knob"},
               {"environ", "getenv", "prim_env_get", "get", "add_argument", "default", "lookup", "config_get"}),
    "report": ({"report", "json", "sarif", "diagnostic", "envelope", "status"},
               {"dumps", "write_text", "write_json_atomic", "kind", "pass", "findings", "json_object", "json_string", "str_json_quote"}),
}
SPECIAL_RULES = {"path": "STRUCT_DUPLICATE_PATH_POLICY", "walk": "STRUCT_DUPLICATE_FS_WALK",
                 "parser": "STRUCT_DUPLICATE_PARSER", "graph": "STRUCT_DUPLICATE_GRAPH_ALGORITHM",
                 "process": "STRUCT_DUPLICATE_PROCESS_POLICY", "config": "STRUCT_DUPLICATE_CONFIG",
                 "report": "STRUCT_DUPLICATE_REPORT_MODEL"}
RULES = {
    "STRUCT_DUPLICATE_IMPLEMENTATION": "clone",
    "STRUCT_PARALLEL_SEMANTICS": "semantics",
    "STRUCT_PASS_THROUGH_WRAPPER": "wrapper",
    "STRUCT_WRAPPER_CHAIN": "wrapper",
    "STRUCT_REDUNDANT_ALIAS": "compatibility",
    "STRUCT_UNUSED_DEF": "dead-code", "STRUCT_UNUSED_TYPE": "dead-code",
    "STRUCT_UNUSED_MODULE": "dead-code", "STRUCT_UNUSED_SCRIPT": "dead-code",
    "STRUCT_UNUSED_MODE": "dead-code", "STRUCT_UNUSED_CONFIG": "dead-code",
    "STRUCT_UNREACHABLE_BRANCH": "dead-code",
    "STRUCT_LEGACY_FALLBACK": "fallback", "STRUCT_SILENT_FALLBACK": "fallback",
    "STRUCT_PARALLEL_BACKEND_FALLBACK": "fallback",
    "STRUCT_COMPAT_RESIDUE": "compatibility",
    "STRUCT_CONFIG_ALIAS_CHAIN": "configuration",
    "STRUCT_PARSER_DRIFT": "semantics",
    "STRUCT_DUPLICATE_DIAGNOSTIC_FORMAT": "semantics",
    "STRUCT_STDLIB_OVERLAP": "stdlib", "STRUCT_STDLIB_ALIAS": "stdlib",
    "STRUCT_UNUSED_RUNTIME_PRIMITIVE": "runtime",
    "STRUCT_REDUNDANT_RUNTIME_PRIMITIVE": "runtime", "STRUCT_POLICY_IN_RUNTIME": "runtime",
    "STRUCT_HOST_POLICY_DUPLICATION": "host", "STRUCT_SCRIPT_WRAPPER_CHAIN": "host",
    "STRUCT_SCRIPT_DUPLICATE_HELPER": "host",
    "STRUCT_CROSS_LANGUAGE_DUPLICATION": "semantics",
    "STRUCT_INVALID_CLASSIFICATION": "coverage", "STRUCT_SCAN_INCOMPLETE": "coverage",
    **{rule: purpose for purpose, rule in SPECIAL_RULES.items()},
}


@dataclass(frozen=True)
class Token:
    value: str
    start: int
    end: int
    line: int


@dataclass
class Symbol:
    path: str
    name: str
    line: int
    end: int
    language: str
    kind: str
    tokens: list[str]
    normalized: tuple
    refs: set[str]
    calls: tuple[str, ...]
    public: bool = False
    wrapper: str = ""
    controls: tuple[str, ...] = ()
    tree: ast.AST | None = None
    classifications: list[dict] = field(default_factory=list)
    bindings: tuple[str, ...] = ()
    token_lines: tuple[int, ...] = ()

    @property
    def key(self):
        return f"{self.path}#{self.name}"


def digest(value):
    return hashlib.sha256(json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def lex(source, language):
    """Retain every non-trivia byte, including preprocessor/shell syntax.

    No identifier/literal is inferred from comments. OCaml comments nest; shell
    here-documents are data regions. Unsupported/unclosed regions are errors.
    """
    result, comments, i, line, heredocs = [], [], 0, 1, []
    while i < len(source):
        start, first_line = i, line
        if source[i].isspace():
            line += source[i] == "\n"
            i += 1
            if source[i - 1] == "\n" and heredocs:
                for delimiter, tabs in heredocs:
                    begin, begin_line = i, line
                    while i < len(source):
                        end = source.find("\n", i)
                        end = len(source) if end < 0 else end
                        current = source[i:end].lstrip("\t") if tabs else source[i:end]
                        i = min(len(source), end + 1)
                        line += end < len(source)
                        if current == delimiter:
                            break
                    else:
                        raise ValueError(f"unclosed here-document at line {begin_line}")
                    result.append(Token('"' + source[begin:i] + '"', begin, i, begin_line))
                heredocs = []
            continue
        if language == "sh" and source.startswith("<<", i) and not source.startswith("<<<", i):
            match = re.match(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z_0-9]*)\2", source[i:])
            if match:
                heredocs.append((match[3], bool(match[1])))
                i += len(match[0])
                result.append(Token(match[0], start, i, first_line))
                continue
        opener = next((x for x in ({"ouro": ("--",), "sh": ("#",), "c": ("//",),
                                   "h": ("//",), "ml": (), "mli": ()}.get(language, ()))
                       if source.startswith(x, i)), None)
        if opener:
            i = source.find("\n", i)
            if i < 0:
                i = len(source)
            comments.append((first_line, source[start:i]))
            continue
        block = ("(*", "*)") if language in {"ml", "mli"} else ("/*", "*/")
        if language in {"ml", "mli", "c", "h"} and source.startswith(block[0], i):
            depth, i = 1, i + 2
            while i < len(source) and depth:
                if block[0] == "(*" and source.startswith(block[0], i):
                    depth, i = depth + 1, i + 2
                elif source.startswith(block[1], i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            if depth:
                raise ValueError(f"unclosed comment at line {line}")
            comments.append((line, source[start:i]))
            line += source[start:i].count("\n")
            continue
        char = source[i]
        # A quote inside an Ouro/OCaml identifier is not a string delimiter.
        is_quote = char == '"' or (char == "'" and language in {"c", "h", "sh"})
        if language in {"ml", "mli"} and char == "'":
            is_quote = bool(re.match(r"'(?:[^'\\\n]|\\.)'", source[i:]))
        if is_quote:
            i += 1
            while i < len(source):
                if source[i] == "\\" and not (language == "sh" and char == "'"):
                    i += 2
                elif source[i] == char:
                    i += 1
                    break
                else:
                    i += 1
            else:
                raise ValueError(f"unclosed string at line {line}")
        elif char.isalpha() or char == "_":
            i += 1
            while i < len(source) and (source[i].isalnum() or (source[i] in "_'" and language != "sh")):
                i += 1
        elif char.isdigit():
            i += 1
            while i < len(source) and (source[i].isalnum() or source[i] in "._"):
                i += 1
        else:
            op = next((x for x in OPERATORS if source.startswith(x, i)), char)
            i += len(op)
        result.append(Token(source[start:i], start, i, first_line))
        line += source[start:i].count("\n")
    return result, comments


def pairs(tokens):
    stack, links = [], {}
    for i, lexeme in enumerate(tokens):
        if lexeme in {"(", "[", "{"}:
            stack.append((lexeme, i))
        elif lexeme in {")", "]", "}"}:
            if not stack or stack[-1][0] != {")": "(", "]": "[", "}": "{"}[lexeme]:
                return {}
            _, start = stack.pop()
            links[start], links[i] = i, start
    return links if not stack else {}


def binders(tokens, language):
    bound = []
    if language in {'c', 'h'}:
        types = {'char', 'int', 'long', 'short', 'float', 'double', 'size_t', 'ouro_v', 'ouro_env'}
        for i, lexeme in enumerate(tokens):
            if lexeme not in types and not lexeme.endswith('_t'):
                continue
            j = i + 1
            while j < len(tokens) and tokens[j] in {'*', 'const', 'unsigned', 'signed', *types}:
                j += 1
            if j + 1 < len(tokens) and IDENT.fullmatch(tokens[j]) and tokens[j + 1] in {'=', ';', ',', ')', '['}:
                bound.append(tokens[j])
    for i, lexeme in enumerate(tokens):
        if lexeme in {"let", "fix", "fun"} and i + 1 < len(tokens):
            j = i + 1
            if tokens[j] in {"!", "rec"}:
                j += 1
            if j < len(tokens) and IDENT.fullmatch(tokens[j]) and tokens[j] not in RESERVED:
                bound.append(tokens[j])
        if lexeme == "(" and language == "ouro":
            j, group = i + 1, []
            while j < len(tokens) and IDENT.fullmatch(tokens[j]):
                group.append(tokens[j])
                j += 1
            if j < len(tokens) and tokens[j] == ":":
                bound.extend(group)
        if lexeme == "|" and language == "ouro":
            j = i + 2  # constructor identity is rigid
            while j < len(tokens) and tokens[j] != "=>":
                if tokens[j] in {"|", ";", "end"}:
                    break
                if IDENT.fullmatch(tokens[j]) and tokens[j][:1].islower():
                    bound.append(tokens[j])
                j += 1
    return [x for x in bound if x != '_']


def normalize(tokens, name, bound):
    # Repeated binder spellings may shadow in separate scopes. Keep them rigid
    # until the lexical adapter can prove their scope, rather than merge them.
    unique = list(dict.fromkeys(bound))
    mapping = {} if len(unique) != len(bound) else {x: f"$local{i}" for i, x in enumerate(unique)}
    mapping.setdefault(name, '$self')
    return tuple(mapping.get(x, x) for x in tokens)


def call_names(tokens, bound):
    return tuple(x for x in tokens if IDENT.fullmatch(x) and x not in RESERVED
                 and x not in bound and x != "_")


def lexical_symbols(path, source):
    language = Path(path).suffix[1:]
    tokens, comments = lex(source, language)
    values, regions = [x.value for x in tokens], []
    if language == "ouro":
        starts = [i for i, t in enumerate(values) if t in {"def", "axiom", "inductive", "record", "effect", "import"}]
        for start, end in zip(starts, [*starts[1:], len(tokens)] if starts else [], strict=True):
            if values[start] != "import" and start + 1 < end:
                regions.append((start, end, start + 1, values[start]))
    elif language in {"c", "h", "sh"}:
        links = pairs(values)
        if language in {'c', 'h'} and any(v in {'(', '{', '['} for v in values) and not links:
            raise ValueError('unbalanced C delimiter regions')
        if language == "sh":
            # `case` patterns have unmatched ')' and need not be C expressions.
            # Match function braces independently of test/substitution syntax.
            stack, links = [], {}
            for i, value in enumerate(values):
                if value in {"{", "${"}:
                    stack.append(i)
                elif value == "}" and stack:
                    opening = stack.pop()
                    links[opening] = i
                elif value == ")" and i and values[i - 1] == "(":
                    links[i] = i - 1
        for i, lexeme in enumerate(values):
            if lexeme != "{" or i not in links or i < 2 or values[i - 1] != ")":
                continue
            opening = links.get(i - 1, 0)
            name = opening - 1
            if name < 0 or not IDENT.fullmatch(values[name]) or values[name] in RESERVED:
                continue
            if any(a <= name < b for a, b, _, _ in regions):
                continue
            start = name
            while start and values[start - 1] not in {";", "}", "{"} and tokens[start - 1].line == tokens[name].line:
                start -= 1
            regions.append((start, links[i] + 1, name, "def"))
        if language == "sh":
            regions.append((0, len(tokens), -1, "script"))
    elif language in {"ml", "mli"}:
        starts = [i for i, t in enumerate(tokens) if t.value in {"let", "and", "type", "module", "val"}
                  and not source[source.rfind("\n", 0, t.start) + 1:t.start].strip()
                  and t.start == source.rfind("\n", 0, t.start) + 1]
        for start, end in zip(starts, [*starts[1:], len(tokens)] if starts else [], strict=True):
            name = start + 1 + (start + 1 < end and values[start + 1] == "rec")
            if name < end and IDENT.fullmatch(values[name]):
                regions.append((start, end, name, "def" if values[start] in {"let", "and"} else "type"))
    symbols = []
    for start, end, name_index, kind in regions:
        name = "<module>" if name_index < 0 else values[name_index]
        ts = values[start:end]
        if not ts:
            continue
        bound = binders(ts, language)
        body = ts
        wrapper = ""
        if language == "ouro" and ":=" in ts:
            at = ts.index(":=")
            body = ts[at + 1:]
            args = binders(ts[:at], language)
            if body[-1:] == [";"]:
                body = body[:-1]
            if body and IDENT.fullmatch(body[0]) and body[1:] == args and (args or "->" in ts[:at]):
                wrapper = body[0]
            # The outer declaration name is not part of the fingerprint.
            ts = ts[2:]
        elif language == 'sh' and kind == 'def':
            body = ts[ts.index('{') + 1:-1]
            if body[-1:] == [';']:
                body = body[:-1]
            if body[:1] == ['exec']:
                body = body[1:]
            if len(body) == 2 and IDENT.fullmatch(body[0]) and body[1] == '"$@"':
                wrapper = body[0]
        public = path.startswith("std/") or name == "main" or kind in {"axiom", "effect"}
        if language in {"c", "h"}:
            public = "static" not in ts[:ts.index("{")] if "{" in ts else True
        if language in {"ml", "mli"}:
            public = True  # .mli/embedding visibility needs module-aware proof
        preceding = [(ln, text) for ln, text in comments if ln < tokens[start].line]
        marks = []
        for ln, comment in preceding:
            exports = re.findall(r"@(?:entry|export|api)\s+([^;@]+)", comment)
            if any(name in WORD.findall(names) for names in exports):
                public = True
            if MARKER in comment and tokens[start].line == ln + 1:
                marks.append(json.loads(comment.split(MARKER, 1)[1].removesuffix("*/").removesuffix("*)").strip()))
        refs = set(x for x in ts if IDENT.fullmatch(x)) - set(bound) - {name}
        symbols.append(Symbol(path, name, tokens[start].line, tokens[end - 1].line,
                              language, kind, ts, normalize(ts, name, bound), refs,
                              call_names(body, bound), public, wrapper,
                              tuple(x for x in body if x in CONTROL), classifications=marks,
                              bindings=tuple(bound), token_lines=tuple(t.line for t in tokens[start:end])))
        if language in {'c', 'h'}:
            # Declarations and argument names are not call operations.
            symbols[-1].calls = tuple(value for i, value in enumerate(body[:-1])
                                     if IDENT.fullmatch(value) and body[i + 1] == '('
                                     and value not in RESERVED and value not in {name, 'sizeof'})
    # OCaml rebinding and C platform branches may define one spelling more than
    # once. They have distinct bodies and must never overwrite fingerprint keys.
    occurrences = collections.Counter(s.name for s in symbols)
    ordinal = collections.Counter()
    for s in symbols:
        original = s.name
        ordinal[original] += 1
        if occurrences[original] > 1:
            s.name += f"@{ordinal[original]}"
            s.public = True
    return symbols, tokens, comments


def ast_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return ast_name(node.value) + "." + node.attr
    return ""


def python_symbols(path, source):
    tree = ast.parse(source, filename=path)
    symbols = []
    lines = source.splitlines()
    for parent in [tree, *(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef))]:
        for node in parent.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            name = node.name if parent is tree else parent.name + "." + node.name
            local = [a.arg for a in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)]
            if node.args.vararg:
                local.append(node.args.vararg.arg)
            if node.args.kwarg:
                local.append(node.args.kwarg.arg)
            local += [n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)]
            local += [n.name for n in ast.walk(node) if isinstance(n, ast.ExceptHandler) and n.name]
            mapping = {n: f"$local{i}" for i, n in enumerate(dict.fromkeys(local))}
            mapping[node.name] = "$self"
            # Nested Python scopes, comprehensions, global/nonlocal statements
            # and declaration-time expressions require separate binding scopes.
            # Keep their identifiers rigid rather than infer a false alpha match.
            scope_nodes = (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp,
                           ast.GeneratorExp, ast.Global, ast.Nonlocal, ast.ClassDef)
            nested = any(isinstance(n, scope_nodes) or
                         (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n is not node)
                         for n in ast.walk(node))
            declaration_refs = {n.id for part in [node.args, node.returns, *node.decorator_list]
                                if part is not None for n in ast.walk(part) if isinstance(n, ast.Name)}
            if nested or declaration_refs & set(local):
                mapping = {node.name: "$self"}

            def canonical(value, mapping=mapping):
                if isinstance(value, list):
                    return tuple(canonical(x) for x in value if not (isinstance(x, ast.Expr) and isinstance(x.value, ast.Constant) and isinstance(x.value.value, str)))
                if not isinstance(value, ast.AST):
                    return (type(value).__name__, repr(value)) if isinstance(value, (bytes, complex)) or value is Ellipsis else value
                return (type(value).__name__, tuple((key, mapping.get(item, item) if key in {"id", "arg", "name"} and isinstance(item, str) else canonical(item))
                        for key, item in ast.iter_fields(value) if key not in {"type_comment"}))

            normalized = (canonical(node.args), canonical(node.returns), canonical(node.body), canonical(node.decorator_list))
            refs = {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)} - set(local) - {node.name}
            calls = tuple(ast_name(n.func) for n in ast.walk(node) if isinstance(n, ast.Call))
            body = [n for n in node.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))]
            wrapper = ""
            if len(body) == 1 and isinstance(body[0], ast.Return) and isinstance(body[0].value, ast.Call):
                call = body[0].value
                if not call.keywords and [ast_name(x) for x in call.args] == local:
                    wrapper = ast_name(call.func)
            marks = []
            if node.lineno > 1 and MARKER in lines[node.lineno - 2]:
                marks = [json.loads(lines[node.lineno - 2].split(MARKER, 1)[1].strip())]
            symbols.append(Symbol(path, name, node.lineno, node.end_lineno, "py", "def",
                                  [type(n).__name__ for n in ast.walk(node)], normalized,
                                  refs, calls, parent is not tree or not node.name.startswith("_") or bool(node.decorator_list),
                                  wrapper, tuple(type(n).__name__.lower() for n in ast.walk(node)
                                                 if isinstance(n, (ast.If, ast.For, ast.While, ast.Try, ast.Match))), node, marks))
            if isinstance(parent, ast.ClassDef) and node.name.startswith('test_') and any(ast_name(base).split('.')[-1] == 'TestCase' for base in parent.bases):
                symbols[-1].kind = 'test'
    top = ast.Module(body=[n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))], type_ignores=[])
    for node in top.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant):
            name = node.targets[0].id
            if name.startswith('_') and set(name.lower().split('_')) & {'mode', 'config', 'flag'}:
                kind = 'mode' if 'mode' in name.lower().split('_') else 'config'
                symbols.append(Symbol(path, name, node.lineno, node.end_lineno, 'py', kind, [], (), set(), ()))
    symbols.append(Symbol(path, '<module>', 1, len(lines), 'py', 'module', [], (),
                          {n.id for n in ast.walk(top) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)},
                          tuple(ast_name(n.func) for n in ast.walk(top) if isinstance(n, ast.Call)),
                          public=True, tree=top))
    return symbols, tree


def make_finding(rule, symbols, evidence, reason, suggestion, confidence="high", blocking=True):
    ordered = sorted(symbols, key=lambda s: (s.path, s.line, s.name))
    first = ordered[0]
    identity = digest([rule, sorted(s.key for s in ordered)])[:20]
    return {"id": identity, "rule_id": rule, "category": RULES[rule],
            "severity": "error" if blocking else "info", "confidence": confidence,
            "path": first.path, "line": first.line, "symbol": first.name,
            "related_paths": sorted({s.path for s in ordered[1:]}),
            "related_symbols": [s.key for s in ordered[1:]],
            "members": [s.key for s in ordered], "evidence": evidence,
            "reason": reason, "suggestion": suggestion, "classification": None}


def purposes(symbol):
    words = set(re.findall(r"[a-z]+", re.sub(r"([a-z])([A-Z])", r"\1_\2", symbol.name).lower()))
    operations = set(symbol.calls) | set(symbol.tokens)
    if symbol.tree is not None:
        for node in ast.walk(symbol.tree):
            if isinstance(node, ast.Name):
                operations.add(node.id)
            elif isinstance(node, ast.Attribute):
                operations.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                operations.update(WORD.findall(node.value))
    operations |= {part for call in symbol.calls for part in call.split(".")}
    # A small capability vocabulary bridges host and native spelling. These
    # landmarks are evidence for candidates, never a claim of equivalence.
    for operation in list(operations):
        parts = set(re.findall(r"[a-z]+", operation.lower()))
        operations.update(parts)
        if parts & {"realpath", "normalize", "normpath", "canonicalize"}:
            operations.add("resolve")
        if {'is', 'absolute'} <= parts:
            operations.add('is_absolute')
        if parts & {"listdir", "iterdir", "readdir", "rglob"} or {"list", "dir"} <= parts:
            operations.add("walk")
        if parts & {"visited", "seen"}:
            operations.add("seen")
        if parts & {"proc", "subprocess", "spawn", "exec"}:
            operations.add("run")
    result = {}
    for purpose, (names, primitives) in PURPOSES.items():
        evidence = operations & primitives
        if purpose == 'process' and not any(set(re.split(r'[._]', call)) & {'run', 'Popen', 'exec', 'spawn', 'execve', 'fork'} for call in symbol.calls):
            continue
        if words & names and evidence:
            result[purpose] = evidence
    return result


def owned_fingerprints(symbols, sources):
    """Resolve Ouro's flat import scopes before claiming equality.

    Distinct nominal datatypes/constructors remain distinct even when their
    spellings agree. Equivalent helper groups are interned before their callers,
    allowing renamed helpers without erasing arbitrary global identities.
    """
    _by_name, by_path = symbol_index(symbols)
    imports, python_owners = {}, {}
    for path, source in sources.items():
        if path.endswith(".ouro"):
            imports[path] = quoted_import_targets(source, path)
        elif path.endswith('.py'):
            owners = {s.name: s.key for s in by_path.get(path, {}).values()}
            for node in ast.parse(source).body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        local = alias.asname or alias.name.split('.')[0]
                        module = (node.module or '') if isinstance(node, ast.ImportFrom) else alias.name
                        candidate = posixpath.join(posixpath.dirname(path), module.replace('.', '/') + '.py')
                        owners[local] = (candidate + '#' + alias.name if isinstance(node, ast.ImportFrom)
                                         and candidate in sources else 'import:' + module + ':' + alias.name)
                elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.ClassDef)):
                    names = [node.name] if isinstance(node, ast.ClassDef) else [n.id for n in ast.walk(node)
                             if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)]
                    owners.update({name: path + '#' + name for name in names})
            python_owners[path] = owners
    scopes = {}
    for path in imports:
        todo, seen = [path], set()
        while todo:
            p = todo.pop()
            if p not in seen:
                seen.add(p)
                todo.extend(imports.get(p, []))
        scope = collections.defaultdict(set)
        for p in sorted(seen):
            for s in by_path.get(p, {}).values():
                scope[s.name].add(s.key)
                if s.kind in {"inductive", "record"}:
                    for i, value in enumerate(s.tokens[:-1]):
                        if value == "|":
                            scope[s.tokens[i + 1]].add(s.key + "/" + s.tokens[i + 1])
        scopes[path] = scope
    representatives = {s.key: s.key for s in symbols}
    fingerprints = {}
    # Union only proven equivalent implementations. Each successful round
    # strictly decreases the number of owners; cycles never require unfolding.
    for _ in range(len(symbols) + 1):
        groups = collections.defaultdict(list)
        for s in symbols:
            normalized = s.normalized
            if s.language == 'py':
                def resolve(value, owners=python_owners[s.path]):
                    if not isinstance(value, tuple):
                        return value
                    if len(value) == 2 and value[0] == 'id' and isinstance(value[1], str):
                        owner = owners.get(value[1])
                        if owner:
                            return ('id', '@' + representatives.get(owner, owner))
                    return tuple(resolve(v) for v in value)
                normalized = resolve(normalized)
            elif s.language == 'ouro':
                normalized = []
                scope = scopes.get(s.path, {})
                for lexeme in s.normalized:
                    owners = scope.get(lexeme, set())
                    if len(owners) == 1:
                        owner = next(iter(owners))
                        normalized.append("@" + representatives.get(owner, owner))
                    elif owners:
                        normalized.append("@ambiguous:" + s.path + ":" + lexeme)
                    else:
                        normalized.append(lexeme)
            fingerprint = digest(normalized)
            fingerprints[s.key] = fingerprint
            if s.kind == "def":
                groups[(s.language, fingerprint)].append(s.key)
        changed = False
        for group in groups.values():
            owner = min(representatives[key] for key in group)
            for key in group:
                if representatives[key] != owner:
                    representatives[key] = owner
                    changed = True
        if not changed:
            break
    return fingerprints


def clone_findings(symbols, fingerprints):
    buckets = collections.defaultdict(list)
    for s in symbols:
        # Tiny adapters belong to the wrapper rules. Literal data tables do not
        # establish shared algorithms; stdlib requires a substantial body.
        limit = 60 if s.path.startswith("std/") else 16 if s.language == 'py' else 24
        algorithm = (set(s.controls) - {'return', 'raise'}) or len(s.calls) >= (1 if s.language == 'py' else 2 if s.language in {'c', 'h'} else 6)
        if s.kind == "def" and (len(s.tokens) >= limit or (s.language == 'py' and len(s.calls) >= 2)) and algorithm and not s.wrapper:
            buckets[(s.language, fingerprints[s.key])].append(s)
    findings = []
    for (_, fingerprint), group in sorted(buckets.items()):
        if len(group) < 2:
            continue
        shared = set.intersection(*(set(s.calls) for s in group))
        families = {SPECIAL_RULES[p] for s in group for p in purposes(s)}
        if any(s.path.startswith('std/') for s in group):
            families.add('STRUCT_STDLIB_OVERLAP')
        if group[0].language in {'py', 'sh'}:
            families.add('STRUCT_SCRIPT_DUPLICATE_HELPER')
            families.add('STRUCT_HOST_POLICY_DUPLICATION')
        if any('report' in purposes(s) and any(word in s.name for word in ['error', 'diagnostic', 'format']) for s in group):
            families.add('STRUCT_DUPLICATE_DIAGNOSTIC_FORMAT')
        findings.append(make_finding("STRUCT_DUPLICATE_IMPLEMENTATION", group,
            {"fingerprint": fingerprint, "similarity": 100, "shared_calls": sorted(shared)[:20],
             "rule_families": sorted(families),
             "representation": "python-ast" if group[0].language == "py" else "bound-token-operation-sequence",
             "structural_differences": [], "sizes": [len(s.tokens) for s in group]},
            "Bodies agree after local binding normalization and resolved helper ownership; types, literals and operations agree.",
            "Choose the existing owner with the smallest valid dependency cone; delegate or delete copies."))
    return findings


def near_findings(symbols, fingerprints):
    """Index equal operation shapes with changed literals; never assert equivalence."""
    groups = collections.defaultdict(list)
    for s in symbols:
        if s.kind != 'def' or len(s.tokens) < 24 or not s.controls:
            continue
        if s.language == 'ouro':
            shape = tuple('$literal' if t[:1] == '"' or t[:1].isdigit() else t for t in s.normalized)
        elif s.language == 'py':
            def loosen(value):
                if isinstance(value, tuple):
                    if value and value[0] == 'Constant':
                        return ('Constant',)
                    return tuple(loosen(x) for x in value)
                return value
            shape = loosen(s.normalized)
        else:
            continue
        groups[(s.language, digest(shape))].append(s)
    return [make_finding('STRUCT_PARSER_DRIFT' if any('parser' in purposes(s) for s in group)
                         else 'STRUCT_PARALLEL_SEMANTICS', group,
                {'similarity': 'same operation shape', 'structural_differences': 'literal values or global ownership'},
                'Operation shapes agree, but differing constants or owners may change the contract.',
                'Compare the concrete constants, helper owners and callers before sharing implementation.', 'medium', False)
            for _, group in sorted(groups.items()) if len(group) > 1 and len({fingerprints[s.key] for s in group}) > 1
            and len({digest(s.normalized) for s in group}) > 1]


def semantic_findings(symbols, clones):
    exact = {frozenset(f["members"]) for f in clones}
    buckets = collections.defaultdict(list)
    for s in symbols:
        if s.kind != "def" or len(s.tokens) < (16 if s.language == 'py' else 24) or s.wrapper:
            continue
        for purpose, evidence in purposes(s).items():
            # Posting lists indexed by responsibility and operation signatures;
            # no all-pairs comparison of the repository.
            if len(evidence) >= 2:
                subject = ''
                if purpose == 'parser':
                    context = set(re.findall(r'[a-z]+', (s.path + ' ' + s.name).lower()))
                    subject = next((topic for topic in ['seal', 'semver', 'json', 'csv', 'http', 'workflow', 'manifest', 'args', 'source', 'unit', 'lexer'] if topic in context), 'syntax')
                buckets[(purpose, subject, tuple(sorted(evidence)))].append(s)
    findings = []
    for (purpose, subject, evidence), group in sorted(buckets.items()):
        if len(group) < 2 or len({s.path for s in group}) < 2 or frozenset(s.key for s in group) in exact:
            continue
        rule = "STRUCT_CROSS_LANGUAGE_DUPLICATION" if len({s.language for s in group}) > 1 else SPECIAL_RULES[purpose]
        findings.append(make_finding(rule, group,
            {"responsibility": purpose, "subject": subject, "shared_operations": list(evidence),
             "owners": sorted({s.path for s in group}), "control_shapes": [list(s.controls) for s in group]},
            "Responsibility vocabulary and multiple operation landmarks overlap; equivalence is not established.",
            "Compare error, ordering, trust and platform contracts before selecting a canonical owner.", "candidate", False))
    return findings


def symbol_index(symbols):
    by_name = collections.defaultdict(list)
    by_path = collections.defaultdict(dict)
    for s in symbols:
        by_name[s.name].append(s)
        by_path[s.path][s.name] = s
    return by_name, by_path


def wrapper_findings(symbols, by_name, by_path):
    findings, seen = [], set()
    for s in symbols:
        if not s.wrapper:
            continue
        chain, current = [s], s
        while current.wrapper:
            target = by_path[current.path].get(current.wrapper)
            if target is None and len(by_name.get(current.wrapper, [])) == 1:
                target = by_name[current.wrapper][0]
            if target is None or target in chain:
                break
            chain.append(target)
            current = target
        if len(chain) >= 3 and not any(x.public for x in chain[:-1]):
            key = tuple(x.key for x in chain)
            if key not in seen:
                rule = 'STRUCT_SCRIPT_WRAPPER_CHAIN' if s.language == 'sh' else 'STRUCT_WRAPPER_CHAIN'
                findings.append(make_finding(rule, chain,
                    {"chain": list(key)}, "Intermediate calls forward parameters unchanged without validation or conversion.",
                    "Call the implementation directly and retain only documented public or host boundaries."))
                seen.add(key)
        elif not s.public and s.wrapper in by_path[s.path] and len(s.tokens) > 1:
            findings.append(make_finding("STRUCT_PASS_THROUGH_WRAPPER", [s, by_path[s.path][s.wrapper]],
                {"target": s.wrapper}, "Internal definition only forwards its arguments to a local implementation.",
                "Replace internal calls with the canonical owner and delete the intermediate definition."))
    return findings


def fallback_findings(symbols):
    findings = []
    for s in symbols:
        if s.tree is not None:
            for node in ast.walk(s.tree):
                if not isinstance(node, ast.Try):
                    continue
                calls = sorted({ast_name(x.func) for n in node.body for x in ast.walk(n) if isinstance(x, ast.Call)})
                for handler in node.handlers:
                    alternatives = sorted({ast_name(x.func) for n in handler.body for x in ast.walk(n) if isinstance(x, ast.Call)})
                    legacy = [x for x in alternatives if set(re.split(r"[_.]", x.lower())) & {"legacy", "compat", "fallback", "old"}]
                    enumeration = {'scandir', 'listdir', 'walk', 'glob', 'rglob', 'iterdir'}
                    primary_walks = [x for x in calls if x.rsplit('.', 1)[-1] in enumeration]
                    retry_walks = [x for x in alternatives if x.rsplit('.', 1)[-1] in enumeration]
                    if calls and legacy:
                        findings.append(make_finding("STRUCT_LEGACY_FALLBACK", [s],
                            {"line": handler.lineno, "primary_calls": calls, "fallback_calls": legacy},
                            "Failure switches to an implementation explicitly named as legacy/compatibility.",
                            "Remove the alternate implementation or classify the exact platform/bootstrap boundary."))
                    elif primary_walks and retry_walks and primary_walks != retry_walks and not any(
                            isinstance(x, ast.Raise) for n in handler.body for x in ast.walk(n)):
                        findings.append(make_finding("STRUCT_PARALLEL_BACKEND_FALLBACK", [s],
                            {"line": handler.lineno, "primary_calls": primary_walks, "fallback_calls": retry_walks},
                            "A failed directory inventory is replaced by a different enumeration API; skipped inputs can look like an empty successful scan.",
                            "Keep one inventory owner and propagate enumeration failure, or classify the exact platform boundary."))
                    elif calls and handler.type is None and all(isinstance(x, ast.Pass) for x in handler.body):
                        findings.append(make_finding("STRUCT_SILENT_FALLBACK", [s],
                            {"line": handler.lineno, "primary_calls": calls}, "A bare exception handler silently discards every failure.",
                            "Catch the supported failure explicitly and preserve error semantics."))
        elif s.language == 'ouro':
            for i in range(len(s.tokens) - 3):
                if s.tokens[i] != '|' or s.tokens[i + 1] not in {'Left', 'Nothing', 'Error', 'False'}:
                    continue
                arm = s.tokens[i + 2:]
                stop = next((j for j, t in enumerate(arm) if t in {'|', 'end'}), len(arm))
                arm = arm[:stop]
                if '=>' not in arm:
                    continue
                body = arm[arm.index('=>') + 1:]
                if len(body) > 1 and body[0] not in s.bindings and set(body[0].lower().split('_')) & {'legacy', 'compat', 'fallback', 'old'}:
                    findings.append(make_finding('STRUCT_LEGACY_FALLBACK', [s],
                        {'failure_constructor': s.tokens[i + 1], 'alternate_call': body[0]},
                        'A failed result selects a named compatibility implementation.',
                        'Propagate the failure or classify this exact compatibility boundary.'))
        elif s.language in {'c', 'h'}:
            for i, lexeme in enumerate(s.tokens[:-2]):
                if lexeme != 'if' or s.tokens[i + 1] != '(':
                    continue
                depth, end = 1, i + 2
                while end < len(s.tokens) and depth:
                    depth += s.tokens[end] == '('
                    depth -= s.tokens[end] == ')'
                    end += 1
                condition = s.tokens[i + 2:end - 1]
                failure = '!' in condition or ('==' in condition and '0' in condition)
                if not failure or any(t in {'defined', 'platform', '_WIN32'} for t in condition):
                    continue
                stop = end
                if stop < len(s.tokens) and s.tokens[stop] == '{':
                    depth, stop = 1, stop + 1
                    while stop < len(s.tokens) and depth:
                        depth += s.tokens[stop] == '{'
                        depth -= s.tokens[stop] == '}'
                        stop += 1
                else:
                    while stop < len(s.tokens) and s.tokens[stop] != ';':
                        stop += 1
                calls = [s.tokens[j] for j in range(end, stop - 1) if s.tokens[j + 1] == '('
                         and set(s.tokens[j].lower().split('_')) & {'legacy', 'compat', 'fallback', 'old'}]
                if calls:
                    findings.append(make_finding('STRUCT_LEGACY_FALLBACK', [s],
                        {'failure_condition': condition, 'alternate_calls': calls},
                        'A failed native operation selects a named historical implementation.',
                        'Propagate the original typed error through the canonical owner.'))
        elif s.language == "sh" and s.kind == "script":
            values = s.tokens
            for i, lexeme in enumerate(values):
                if lexeme != "||":
                    continue
                # A shell newline ends the right-hand command. Do not mistake
                # unconditional cleanup/verification on the next line for a
                # backend selected by failure. Braced groups and explicit
                # continuations still belong to the same alternate.
                alternate, depth = [], 0
                for j in range(i + 1, len(values)):
                    value = values[j]
                    if alternate and depth == 0 and (
                            value in {";", "&&", "||", "}"}
                            or (s.token_lines[j] != s.token_lines[j - 1] and values[j - 1] != "\\")):
                        break
                    alternate.append(value)
                    depth += value in {"{", "${"}
                    depth -= value == "}"
                if any(re.search(r"(?:legacy|compat|fallback|\.py)", x) for x in alternate):
                    findings.append(make_finding("STRUCT_PARALLEL_BACKEND_FALLBACK", [s],
                        {"primary": values[max(0, i - 8):i], "alternate": alternate},
                        "Command failure selects a second named implementation/backend.",
                        "Propagate failure or classify the exact platform/bootstrap boundary."))
            for i, lexeme in enumerate(values[:-2]):
                if lexeme != 'if' or values[i + 1] in {'[', 'test'}:
                    continue
                then = next((j for j in range(i + 1, len(values)) if values[j] in {'then', 'fi'}), len(values))
                if then == len(values) or values[then] != 'then':
                    continue
                depth, alternate, stop = 1, None, len(values)
                for j in range(then + 1, len(values)):
                    depth += values[j] == 'if'
                    depth -= values[j] == 'fi'
                    if values[j] == 'else' and depth == 1:
                        alternate = j + 1
                    if depth == 0:
                        stop = j
                        break
                if values[i + 1] == '!':
                    start, stop = then + 1, alternate - 1 if alternate else stop
                elif alternate is not None:
                    start = alternate
                else:
                    continue
                arm = values[start:stop]
                if any(set(re.findall(r'[a-z]+', value.lower())) & {'legacy', 'compat', 'fallback'} for value in arm):
                    findings.append(make_finding('STRUCT_LEGACY_FALLBACK', [s],
                        {'primary_condition': values[i + 1:then], 'alternate': arm[:12]},
                        'A failed shell command selects a named historical implementation.',
                        'Propagate failure or classify this exact bootstrap/platform boundary.'))
    return findings


def surface_findings(symbols, source_refs):
    findings = []
    std_aliases = collections.defaultdict(list)
    for s in symbols:
        if s.path.startswith('std/') and s.wrapper:
            std_aliases[s.wrapper].append(s)
        legacy = set(s.name.lower().split('_')) & {'legacy', 'deprecated', 'compat', 'obsolete'}
        if legacy and s.kind == 'def':
            findings.append(make_finding('STRUCT_COMPAT_RESIDUE', [s],
                {'callers': sorted(source_refs.get(s.name, set()) - {s.path}), 'public': s.public},
                'The declaration advertises a retained historical compatibility surface.',
                'Check documented callers and migration requirements before retiring the surface.', 'candidate', False))
        if s.kind == 'axiom' and s.name.startswith('prim_') and not source_refs.get(s.name, set()) - {s.path}:
            findings.append(make_finding('STRUCT_UNUSED_RUNTIME_PRIMITIVE', [s],
                {'external_api': True, 'incoming_files': []},
                'No repository consumer names this exported host primitive.',
                'Audit runtime dispatch and external API compatibility before removal.', 'candidate', False))
        if s.wrapper and s.public and legacy:
            rule = 'STRUCT_STDLIB_ALIAS' if s.path.startswith('std/') else 'STRUCT_REDUNDANT_ALIAS'
            findings.append(make_finding(rule, [s], {'target': s.wrapper, 'external_api': True},
                'An externally visible adapter forwards arguments unchanged.',
                'Preserve stable API adapters; share their implementation and review undocumented aliases.', 'candidate', False))
        if s.tree is not None:
            for node in ast.walk(s.tree):
                if not isinstance(node, ast.Call) or ast_name(node.func) not in {'os.getenv', 'os.environ.get'}:
                    continue
                if len(node.args) < 2 or not isinstance(node.args[1], ast.Call):
                    continue
                other = node.args[1]
                if ast_name(other.func) not in {'os.getenv', 'os.environ.get'} or not other.args:
                    continue
                if all(isinstance(x, ast.Constant) and isinstance(x.value, str) for x in [node.args[0], other.args[0]]):
                    findings.append(make_finding('STRUCT_CONFIG_ALIAS_CHAIN', [s],
                        {'line': node.lineno, 'knobs': [node.args[0].value, other.args[0].value]},
                        'Two environment names participate in one default chain.',
                        'Check whether these are supported overrides or obsolete independent knobs.', 'candidate', False))
        elif s.language == 'sh' and s.kind == 'script':
            for lexeme in s.tokens:
                chain = re.findall(r'\$\{([A-Za-z_][A-Za-z_0-9]*):-\$\{([A-Za-z_][A-Za-z_0-9]*)', lexeme)
                for knobs in chain:
                    findings.append(make_finding('STRUCT_CONFIG_ALIAS_CHAIN', [s], {'knobs': list(knobs)},
                        'Two environment names participate in one shell default chain.',
                        'Keep documented overrides and remove stale aliases with a migration note.', 'candidate', False))
        if s.language == 'c':
            dispatch = collections.defaultdict(list)
            for i, lexeme in enumerate(s.tokens):
                if lexeme != 'strcmp' or i + 6 >= len(s.tokens) or s.tokens[i + 3] != ',':
                    continue
                label = s.tokens[i + 4]
                end = next((j for j in range(i + 5, len(s.tokens)) if s.tokens[j] in {'else', ';'}), len(s.tokens))
                arm = s.tokens[i + 5:end]
                if 'ouro_clos' in arm:
                    at = arm.index('ouro_clos')
                    if at + 2 < len(arm):
                        dispatch[arm[at + 2]].append(label)
            aliases = {target: names for target, names in sorted(dispatch.items()) if len(names) > 1}
            if aliases:
                findings.append(make_finding('STRUCT_REDUNDANT_RUNTIME_PRIMITIVE', [s], {'dispatch_aliases': aliases},
                    'Multiple exported runtime spellings select the same host implementation.',
                    'Check ABI users and preserve documented aliases; keep a single implementation.', 'candidate', False))
            policy = [t for t in s.tokens if t.startswith('"') and any(landmark in t for landmark in ['Ouro.seal', 'Ouro.lock', 'ouro.repo-gate', 'ouro.ci-gate'])]
            if policy and s.path.startswith('runtime/'):
                findings.append(make_finding('STRUCT_POLICY_IN_RUNTIME', [s], {'project_policy_literals': sorted(set(policy))},
                    'A host runtime operation depends on a repository or package policy format.',
                    'Keep host integration here and move package/gate interpretation to its Ouro owner.', 'candidate', False))
    for target, group in sorted(std_aliases.items()):
        if len(group) > 1:
            findings.append(make_finding('STRUCT_STDLIB_ALIAS', group, {'target': target},
                'Several public adapters forward to the same operation.',
                'Review API roles and retain documented compatibility names without copying implementation.', 'candidate', False))
    return findings


def dead_findings(symbols, source_refs):
    referrers = collections.defaultdict(set)
    for s in symbols:
        for ref in s.refs:
            referrers[ref].add(s.key)
    by_name, by_path = symbol_index(symbols)
    reachable = set()
    pending = [s for s in symbols if s.public or source_refs.get(s.name, set()) - {s.path}]
    while pending:
        current = pending.pop()
        if current.key in reachable:
            continue
        reachable.add(current.key)
        for ref in current.refs:
            local = by_path[current.path].get(ref)
            pending.extend([local] if local else by_name.get(ref, []))
    findings = []
    for s in symbols:
        if s.public or s.kind == "script" or s.language not in {"py", "ouro", "c"}:
            continue
        if s.key in reachable:
            continue
        if s.kind not in {"def", "inductive", "record", "type", 'mode', 'config'}:
            continue
        rule = {'def': 'STRUCT_UNUSED_DEF', 'mode': 'STRUCT_UNUSED_MODE', 'config': 'STRUCT_UNUSED_CONFIG'}.get(s.kind, 'STRUCT_UNUSED_TYPE')
        internal = s.language != "ouro" or s.path.startswith(("compiler/", "runtime/", "tools/")) or s.name.startswith("_")
        if not internal:
            continue  # externally checkable examples do not declare privacy
        findings.append(make_finding(rule, [s], {"incoming_references": sorted(referrers.get(s.name, set())), "visibility": "internal", "self_recursion_is_not_a_root": True},
            "No public, protocol, top-level or external repository reference reaches this internal declaration.",
            "Confirm no external protocol root is missing, then remove the definition and its private dependency tail.",
            "high" if internal else "candidate", internal))
    return findings


def orphan_findings(symbols, sources, source_refs):
    _, by_path = symbol_index(symbols)
    findings = []
    for path, declarations in sorted(by_path.items()):
        if not path.startswith(('scripts/', 'compiler/', 'runtime/', 'tools/')):
            continue
        stem = Path(path).stem
        # Inventories, CLI manifests and module imports are explicit external
        # roots. A public main/export is an externally consumable entry point.
        if source_refs.get(stem, set()) - {path} or any(s.public and s.kind not in {'module', 'script'} for s in declarations.values()):
            continue
        source = sources[path]
        if '__name__' in source or not declarations:
            continue
        representative = next(iter(declarations.values()))
        rule = 'STRUCT_UNUSED_SCRIPT' if path.endswith(('.py', '.sh')) else 'STRUCT_UNUSED_MODULE'
        findings.append(make_finding(rule, [representative], {'module': path, 'incoming_files': []},
            'The repository has no named file consumer or declared public entry point for this module.',
            'Check dynamic loading and CLI roots, then delete the orphan or declare its actual entry point.', 'candidate', False))
    return findings


def unreachable_findings(symbols):
    findings = []
    for s in symbols:
        if s.language == 'ouro' and any(s.tokens[i:i + 3] in (['match', 'True', 'with'], ['match', 'False', 'with'])
                                        for i in range(len(s.tokens) - 2)):
            findings.append(make_finding('STRUCT_UNREACHABLE_BRANCH', [s], {'condition': 'literal Boolean match'},
                'A literal Boolean scrutinee fixes the selected branch.',
                'Replace the match with its selected expression.'))
        if s.tree is None:
            continue
        for node in ast.walk(s.tree):
            if isinstance(node, ast.If) and isinstance(node.test, ast.Constant) and isinstance(node.test.value, bool):
                findings.append(make_finding("STRUCT_UNREACHABLE_BRANCH", [s],
                    {"line": node.lineno, "condition": node.test.value}, "A literal condition makes a branch unreachable.",
                    "Remove the unreachable branch after checking supported feature/platform modes."))
    return findings


def classify(findings, symbols):
    issues, used = [], set()
    by_members = {}
    for finding in findings:
        by_members.setdefault((finding["rule_id"], frozenset(finding["members"])), []).append(finding)
    for s in symbols:
        for index, mark in enumerate(s.classifications):
            if not isinstance(mark, dict) or set(mark) != {"rule", "category", "related", "reason"} or mark.get("rule") not in RULES or mark.get("category") not in CATEGORIES or not isinstance(mark.get("reason"), str) or len(mark["reason"].strip()) < 24 or not isinstance(mark.get("related"), list):
                issues.append(f"{s.key}: invalid local structural classification")
                continue
            if any(not isinstance(x, str) or "#" not in x or "*" in x for x in mark["related"]):
                issues.append(f"{s.key}: related members must be exact path#symbol names")
                continue
            matches = by_members.get((mark["rule"], frozenset({s.key, *mark["related"]})), ())
            for f in matches:
                if f["classification"] is not None:
                    issues.append(f"{s.key}: duplicate classification for {f['id']}")
                f["classification"] = {"category": mark["category"], "reason": mark["reason"], "at": s.key}
                used.add((s.key, index))
            if (s.key, index) not in used:
                issues.append(f"{s.key}: stale classification for {mark['rule']}")
    return issues


def inventory(root):
    result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise ValueError("git source inventory failed: " + result.stderr.decode(errors="replace"))
    paths = sorted(set(x for x in result.stdout.decode().split("\0") if x))
    if not paths:
        raise ValueError("empty repository inventory")
    for path in paths:
        full = root / path
        if full.is_symlink() or not full.is_file() or not full.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"required tracked/source input missing or unsafe: {path}")
    return paths


def boundaries(root, paths):
    result = {}
    generated = root / "docs/generated_artifact_hashes.sha256"
    if generated.is_file():
        for line in generated.read_text().splitlines():
            expected, path = line.split()
            if path not in paths or hashlib.sha256((root / path).read_bytes()).hexdigest() != expected:
                raise ValueError(f"generated source missing or stale: {path}")
            result[path] = {"kind": "generated-artifact", "owner": "docs/generated_artifact_hashes.sha256"}
    for manifest_path in ("tests/analyze/manifest.json", "quality/fixtures/manifest.json",
                          "tests/clippy_semantic/cases.json"):
        file = root / manifest_path
        if not file.is_file():
            continue
        def visit(value, file=file, manifest_path=manifest_path):
            if isinstance(value, dict):
                if "scope" in value:
                    local = (file.parent / value['scope']).resolve()
                    if not local.is_relative_to(file.parent.resolve()):
                        raise ValueError('fixture scope escapes its harness: ' + manifest_path)
                    scope = local.relative_to(root.resolve()).as_posix()
                    for path in paths:
                        if path == scope or path.startswith(scope + "/"):
                            result[path] = {"kind": "fixture-input", "owner": manifest_path}
                if "path" in value:
                    path = value["path"]
                    if not isinstance(path, str) or not path:
                        raise ValueError('invalid fixture path: ' + manifest_path)
                    if not (root / path).resolve().is_relative_to(file.parent.resolve()):
                        raise ValueError('fixture path escapes its harness: ' + manifest_path)
                    if path not in paths:
                        raise ValueError('required fixture missing from inventory: ' + path)
                    result[path] = {"kind": "fixture-input", "owner": manifest_path}
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(json.loads(file.read_text()))
    lex_manifest = "quality/fixtures/structural_lex/manifest.json"
    if (root / lex_manifest).is_file():
        from structural_lex_parity import load_cases

        for case in load_cases((root / lex_manifest).parent):
            path = (Path(lex_manifest).parent / case["file"]).as_posix()
            if path not in paths:
                raise ValueError("required lex fixture missing from inventory: " + path)
            result[path] = {"kind": "fixture-input", "owner": lex_manifest,
                            "expected_lex_error": case["error"]}
    return result


def encoded_symbol_names(tokens):
    """Ouro's interned symbol literals use ASCII Nat lists, like string roots."""
    names = set()
    for index, token in enumerate(tokens):
        if token.value != '[':
            continue
        codes = []
        cursor = index + 1
        while cursor < len(tokens) and tokens[cursor].value.isdecimal():
            code = int(tokens[cursor].value)
            if code > 127:
                break
            codes.append(code)
            cursor += 1
            if cursor >= len(tokens):
                break
            if tokens[cursor].value == ']':
                name = ''.join(chr(code) for code in codes)
                if IDENT.fullmatch(name):
                    names.add(name)
                break
            if tokens[cursor].value != ',':
                break
            cursor += 1
    return names


def analyze(root, *, supplied=None):
    paths = sorted(supplied) if supplied is not None else inventory(root)
    bounds = {} if supplied is not None else boundaries(root, paths)
    symbols, file_rows, source_refs, issues, sources = [], [], collections.defaultdict(set), [], {}
    for path in paths:
        suffix = Path(path).suffix
        data = supplied[path] if supplied is not None else (root / path).read_bytes()
        source = data if isinstance(data, str) else data.decode("utf-8", errors="strict") if suffix in SOURCE_SUFFIXES or suffix in {".json", ".md", ".yml", ".yaml", ".seal", ".tsv"} else ""
        if suffix not in SOURCE_SUFFIXES:
            # Explicit strings in configs/docs/generated inputs can be dynamic
            # command/ABI roots. Comments inside source are not callers.
            for word in set(WORD.findall(source)):
                source_refs[word].add(path)
            continue
        boundary = bounds.get(path)
        if boundary and boundary["kind"] == "generated-artifact":
            for word in set(WORD.findall(source)):
                source_refs[word].add(path)
            file_rows.append({"path": path, "language": suffix[1:], "symbols": 0, "boundary": boundary})
            continue
        try:
            sources[path] = source
            if suffix == ".py":
                found, tree = python_symbols(path, source)
                comments = [(t.start[0], t.string) for t in tokenize.generate_tokens(io.StringIO(source).readline)
                            if t.type == tokenize.COMMENT]
                strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
                refs = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
                refs |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
            else:
                found, tokens, comments = lexical_symbols(path, source)
                strings = [t.value for t in tokens if t.value.startswith(('"', "'"))]
                refs = set(t.value for t in tokens if IDENT.fullmatch(t.value))
                if suffix == '.ouro':
                    refs.update(encoded_symbol_names(tokens))
                # Macro tables and top-level dispatch glue are references too;
                # their identifiers must not be confused with declarations.
                for s in found:
                    if any(t.value == s.name and not any(d.line <= t.line <= d.end for d in found) for t in tokens):
                        s.public = True
            if boundary and boundary.get("expected_lex_error"):
                issues.append(f"{path}: negative lex fixture unexpectedly accepted")
            if sum(MARKER in comment for _, comment in comments) != sum(len(s.classifications) for s in found):
                issues.append(f'{path}: every structural classification must attach to exactly one declaration')
            literal_words = set(WORD.findall("\n".join(strings)))
            for s in found:
                if s.name in literal_words:
                    s.public = True
            for word in refs | set(WORD.findall("\n".join(strings))):
                source_refs[word].add(path)
            # Isolated fixture programs are data consumed by a named harness,
            # not competing production ownership. They still get lexed/parsed.
            file_rows.append({"path": path, "language": suffix[1:], "symbols": len(found), "boundary": boundary})
            if not boundary:
                symbols.extend(found)
        except (ValueError, SyntaxError, RecursionError, tokenize.TokenError) as exc:
            sources.pop(path, None)
            if boundary and boundary.get("expected_lex_error") and isinstance(exc, ValueError):
                file_rows.append({"path": path, "language": suffix[1:], "symbols": 0,
                                  "boundary": boundary})
            else:
                issues.append(f"{path}: incomplete structural extraction: {exc}")
    fingerprints = owned_fingerprints(symbols, sources)
    clones = clone_findings(symbols, fingerprints)
    by_name, by_path = symbol_index(symbols)
    findings = [*clones, *semantic_findings(symbols, clones),
                *wrapper_findings(symbols, by_name, by_path), *dead_findings(symbols, source_refs),
                *fallback_findings(symbols), *unreachable_findings(symbols),
                *near_findings(symbols, fingerprints), *surface_findings(symbols, source_refs),
                *orphan_findings(symbols, sources, source_refs)]
    unique = {}
    for finding in findings:
        if finding['id'] in unique:
            first = unique[finding['id']]
            first['evidence'].setdefault('additional_instances', []).append(finding['evidence'])
        else:
            unique[finding['id']] = finding
    findings = list(unique.values())
    issues.extend(classify(findings, symbols))
    findings.sort(key=lambda f: (f["path"], f["line"], f["rule_id"], f["id"]))
    blocking = sum(f["severity"] == "error" and f["classification"] is None for f in findings)
    return {"kind": KIND, "complete": not issues, "pass": not issues and not blocking,
            "files_scanned": len(file_rows), "symbols_scanned": len(symbols),
            "clone_groups": len(clones), "actionable_findings": blocking,
            "intentional_cases": sum(f["classification"] is not None for f in findings),
            "informational_candidates": sum(f["severity"] == "info" and f["classification"] is None for f in findings),
            "inventory_digest": digest(paths), "files": file_rows, "findings": findings,
            "issues": sorted(issues)}


def validate_report(report):
    """Reject malformed or internally inconsistent evidence before accepting it."""
    if not isinstance(report, dict) or report.get('kind') != KIND:
        raise ValueError('invalid structural report kind')
    for key in ['complete', 'pass']:
        if type(report.get(key)) is not bool:
            raise ValueError('invalid structural report flag: ' + key)
    for key in ['files_scanned', 'symbols_scanned', 'clone_groups', 'actionable_findings', 'intentional_cases', 'informational_candidates']:
        if type(report.get(key)) is not int or report[key] < 0:
            raise ValueError('invalid structural report count: ' + key)
    if not isinstance(report.get('files'), list) or not isinstance(report.get('findings'), list) or not isinstance(report.get('issues'), list):
        raise ValueError('invalid structural report collections')
    if report['files_scanned'] != len(report['files']):
        raise ValueError('structural source coverage count mismatch')
    paths = set()
    for row in report['files']:
        if not isinstance(row, dict) or not {'path', 'language', 'symbols', 'boundary'} <= row.keys():
            raise ValueError('malformed structural coverage row')
        path = row['path']
        if not isinstance(path, str) or path.startswith('/') or '..' in path.split('/') or path in paths:
            raise ValueError('unsafe or duplicate structural source path')
        if '.' + row['language'] not in SOURCE_SUFFIXES or type(row['symbols']) is not int or row['symbols'] < 0:
            raise ValueError('invalid structural language coverage')
        paths.add(path)
    if report['symbols_scanned'] != sum(row['symbols'] for row in report['files'] if not row['boundary']):
        raise ValueError('structural symbol coverage count mismatch')
    ids = set()
    for finding in report['findings']:
        required = {'id', 'rule_id', 'severity', 'confidence', 'path', 'line', 'symbol', 'related_paths', 'related_symbols',
                    'evidence', 'reason', 'suggestion', 'classification', 'members'}
        if not isinstance(finding, dict) or not required <= finding.keys():
            raise ValueError('malformed structural finding')
        if finding['rule_id'] not in RULES or finding['id'] in ids or finding['severity'] not in {'error', 'info'}:
            raise ValueError('unknown or duplicate structural finding')
        if finding['confidence'] not in {'high', 'medium', 'candidate'} or not isinstance(finding['evidence'], dict):
            raise ValueError('malformed structural evidence')
        if finding['path'] not in paths or type(finding['line']) is not int or finding['line'] < 1:
            raise ValueError('invalid structural finding location')
        for key in ['id', 'symbol', 'reason', 'suggestion']:
            if not isinstance(finding[key], str) or not finding[key]:
                raise ValueError('invalid structural finding text')
        for key in ['related_paths', 'related_symbols', 'members']:
            if not isinstance(finding[key], list) or any(not isinstance(value, str) for value in finding[key]):
                raise ValueError('invalid related structural symbols')
        classification = finding['classification']
        if classification is not None and (not isinstance(classification, dict) or classification.get('category') not in CATEGORIES
                                           or not isinstance(classification.get('reason'), str) or classification.get('at') not in finding['members']):
            raise ValueError('invalid structural classification evidence')
        ids.add(finding['id'])
    blocking = sum(f['severity'] == 'error' and f['classification'] is None for f in report['findings'])
    if report['actionable_findings'] != blocking or report['intentional_cases'] != sum(f['classification'] is not None for f in report['findings']):
        raise ValueError('structural finding count mismatch')
    if report['clone_groups'] != sum(f['rule_id'] == 'STRUCT_DUPLICATE_IMPLEMENTATION' for f in report['findings']):
        raise ValueError('structural clone group count mismatch')
    if report['informational_candidates'] != sum(f['severity'] == 'info' and f['classification'] is None for f in report['findings']):
        raise ValueError('structural candidate count mismatch')
    if report['pass'] != (report['complete'] and not report['issues'] and not blocking):
        raise ValueError('inconsistent structural gate verdict')


def run(root, report_path):
    try:
        report = analyze(root)
        validate_report(report)
    except (OSError, ValueError, RecursionError) as exc:
        report = {"kind": KIND, "complete": False, "pass": False, "actionable_findings": 0,
                  "files_scanned": 0, "symbols_scanned": 0, "clone_groups": 0, "intentional_cases": 0,
                  "informational_candidates": 0, "files": [], "findings": [], "issues": [str(exc)]}
    write_json_atomic(report_path, report)
    saved = json.loads(report_path.read_text(encoding='utf-8'))
    validate_report(saved)
    if saved != report:
        raise ValueError('structural report changed during publication')
    for finding in report["findings"]:
        if finding["severity"] != "error" or finding["classification"]:
            continue
        print(f"{finding['rule_id']} {finding['path']}:{finding['line']} {finding['symbol']}")
        print("  " + finding["reason"])
        print("  related: " + ", ".join(finding["related_symbols"][:8]))
        print("  " + finding["suggestion"])
    for issue in report["issues"]:
        print("STRUCT_SCAN_INCOMPLETE " + issue, file=sys.stderr)
    print(f"STRUCTURAL_QUALITY {'PASS' if report['pass'] else 'FAIL'} blocking={report['actionable_findings']} "
          f"intentional={report.get('intentional_cases', 0)} candidates={report.get('informational_candidates', 0)} report={report_path}")
    return 0 if report["pass"] else 1
