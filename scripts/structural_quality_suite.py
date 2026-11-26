#!/usr/bin/env python3
"""Regression and false-positive contracts for strict-quality --structural."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import structural_quality as sq

ROOT = Path(__file__).resolve().parents[1]
DUP = 'STRUCT_DUPLICATE_IMPLEMENTATION'


def scan(files):
    report = sq.analyze(ROOT, supplied=files)
    if json.loads(json.dumps(report)) != report:
        raise AssertionError('Every report field must survive the canonical JSON round trip')
    return report


def rules(report):
    return {f['rule_id'] for f in report['findings'] if not f['classification']}


def declaration(name, arg='x', value=1):
    return f'def {name}({arg}):\n    if {arg} < 0:\n        return -{arg} + {value}\n    return {arg} * 2 + {value}\n'


def mark(rule, related, category='independent-oracle'):
    return '# ouro-structural: ' + json.dumps(dict(rule=rule, category=category, related=related,
        reason='Independent expected-result computation for differential checking.')) + '\n'


class StructuralContracts(unittest.TestCase):
    def test_lex_corpus_accepts_canonical_children_and_checks_aliases_and_escapes(self):
        from structural_lex_parity import load_cases

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            corpus = directory / 'corpus'
            corpus.mkdir()
            first, second = (corpus / name for name in ('first.ouro', 'second.ouro'))
            first.write_text('import "leaf.ouro";', encoding='utf-8')
            second.write_text('def value : Nat := 0;', encoding='utf-8')
            cases = [{'name': path.stem, 'file': path.name, 'language': 'ouro'} for path in (first, second)]
            manifest = corpus / 'manifest.json'

            def write_manifest():
                manifest.write_text(json.dumps({'kind': 'ouro.structural-lex-corpus.v1', 'cases': cases}), encoding='utf-8')

            write_manifest()
            with patch.object(Path, 'resolve', autospec=True, side_effect=Path.resolve) as resolves:
                loaded = load_cases(corpus)
            self.assertEqual([call.args[0] for call in resolves.call_args_list], [first, second])
            self.assertEqual([row['source'] for row in loaded], [path.read_text(encoding='utf-8') for path in (first, second)])
            unresolved = corpus / '..' / corpus.name
            with patch.object(Path, 'resolve', autospec=True, side_effect=Path.resolve) as resolves:
                self.assertEqual(load_cases(unresolved), loaded)
            self.assertIn(unresolved, [call.args[0] for call in resolves.call_args_list])

            outside = directory / 'outside.ouro'
            outside.write_text('def value : Nat := 1;', encoding='utf-8')
            cases[1]['file'] = '../outside.ouro'
            write_manifest()
            with self.assertRaisesRegex(ValueError, r'^lex fixture escapes corpus or is missing: \.\./outside\.ouro$'):
                load_cases(corpus)

    def test_lex_preserves_operator_comment_precedence(self):
        common = ['<=', '<-', '<<', '>=', '>>', '...', '.', ':=', '::', '${', '$(']
        source = ' '.join(common) + ' -- tail\nnext'
        for language, tail, comments in (
            ('ouro', ['next'], [(1, '-- tail')]),
            ('c', ['--', 'tail', 'next'], []),
        ):
            with self.subTest(language=language):
                tokens, seen_comments = sq.lex(source, language)
                self.assertEqual([token.value for token in tokens], common + tail)
                self.assertEqual([source[token.start:token.end] for token in tokens], common + tail)
                self.assertEqual([token.line for token in tokens], [1] * (len(tokens) - 1) + [2])
                self.assertEqual(seen_comments, comments)

    def test_dedented_multiline_is_one_opaque_ouro_token(self):
        literal = '"""\r\n  import "fake.ouro"; -- @entry fake\r\n  mid"""line\r\n  """'
        tokens, comments = sq.lex('def text : String := ' + literal + ';', 'ouro')
        self.assertEqual([token.value for token in tokens if token.value == literal], [literal])
        self.assertEqual(comments, [])
        with self.assertRaisesRegex(ValueError, 'unclosed string'):
            sq.lex('"""\n  missing close', 'ouro')

    def test_ordinary_quote_spans_keep_positions_escapes_and_errors(self):
        offsets = []

        class TrackedSource(str):
            __slots__ = ()

            def __getitem__(self, index):
                if isinstance(index, int):
                    offsets.append(index)
                return super().__getitem__(index)

        plain = '"alpha\nbeta"'
        escaped = r'"before \" after"'
        source = TrackedSource(f'{plain} {escaped} import\nnext')
        tokens, comments = sq.lex(source, 'ouro')
        self.assertEqual([token.value for token in tokens], [plain, escaped, 'import', 'next'])
        self.assertEqual([token.line for token in tokens], [1, 2, 2, 3])
        self.assertEqual([source[token.start:token.end] for token in tokens], [plain, escaped, 'import', 'next'])
        self.assertEqual(comments, [])
        self.assertFalse(any(0 < offset < len(plain) - 1 for offset in offsets), offsets)

        shell_literal = "'ends with backslash\\'"
        tokens, _comments = sq.lex(shell_literal + ' tail', 'sh')
        self.assertEqual([token.value for token in tokens], [shell_literal, 'tail'])
        for unclosed in ('"missing', r'"escaped \"'):
            with self.subTest(unclosed=unclosed), self.assertRaisesRegex(ValueError, '^unclosed string at line 2$'):
                sq.lex('previous\n' + unclosed, 'ouro')

    def test_import_projection_only_slices_selected_tokens(self):
        class TrackedSource(str):
            __slots__ = ()

            def __getitem__(self, index):
                if isinstance(index, slice):
                    slices.append(index)
                return super().__getitem__(index)

        source = ('-- ignore import\r\ndef raw := r#"\nimport "raw.ouro";"#;\n'
                  'def multi := """\n  import "multi.ouro";\n  """;\n'
                  'def quoted := "\nimport";\nimport "a.ouro", "b.ouro"; Model.import;\n')
        tokens, comments = sq.lex(source, 'ouro')
        expected = [token for token in tokens if token.value == 'import']
        self.assertEqual([token.line for token in expected], [9, 9])
        self.assertEqual(sq.lex(source, 'ouro', only_lexeme='import'), (expected, comments))
        slices = []
        self.assertEqual(sq.lex(TrackedSource(source), 'ouro', only_lexeme='import', collect_comments=False),
                         (expected, []))
        self.assertEqual(slices, [slice(token.start, token.end) for token in expected])
        with self.assertRaisesRegex(ValueError, '^unclosed raw string at line 10$'):
            sq.lex(source + 'r#"unfinished', 'ouro', only_lexeme='import', collect_comments=False)

    def test_exact_and_renamed_clones(self):
        for arg in ['x', 'renamed']:
            with self.subTest(arg=arg):
                r = scan({'a.py': declaration('first'), 'b.py': declaration('second', arg)})
                self.assertTrue(r['complete'])
                self.assertIn(DUP, rules(r))
                self.assertEqual(r['clone_groups'], 1)

    def test_operators_and_literals_are_rigid(self):
        for other in [declaration('second', value=9), declaration('second').replace('x < 0', 'x > 0')]:
            with self.subTest(other=other):
                self.assertNotIn(DUP, rules(scan({'a.py': declaration('first'), 'b.py': other})))

    def test_python_global_owners(self):
        body = 'def compute(x):\n    if x:\n        return helper(x)\n    return helper(3)\n'
        r = scan({'a.py': body + 'def helper(x):\n    return x + 1\n',
                  'b.py': body + 'def helper(x):\n    return x - 1\n'})
        self.assertNotIn(DUP, rules(r))

    def test_python_owners_reuse_the_parsed_source_and_preserve_rebinding(self):
        body = 'def compute(x):\n    if x:\n        return helper(x)\n    return helper(3)\n'
        files = {'a.py': 'from left import leaf as helper\n' + body,
                 'b.py': 'from right import leaf as helper\n' + body,
                 'left.py': declaration('leaf'), 'right.py': declaration('leaf')}
        for suffix in ('', '\nhelper = external\n', '\nhelper: object = external\n', '\nclass helper:\n    pass\n'):
            with self.subTest(suffix=suffix):
                with patch.object(ast, 'parse', wraps=ast.parse) as parses:
                    report = scan(dict(files, **{'b.py': files['b.py'] + suffix}))
                self.assertTrue(report['complete'], report['issues'])
                groups = [finding['members'] for finding in report['findings'] if finding['rule_id'] == DUP]
                expected = [['left.py#leaf', 'right.py#leaf']]
                if not suffix:
                    expected.insert(0, ['a.py#compute', 'b.py#compute'])
                self.assertEqual(groups, expected)
                self.assertEqual(parses.call_count, len(files))

    def test_renamed_helpers_propagate(self):
        r = scan({'a.py': declaration('helper') + 'def first(x):\n    if x:\n        return helper(x)\n    return helper(3)\n',
                  'b.py': declaration('other') + 'def second(y):\n    if y:\n        return other(y)\n    return other(3)\n'})
        self.assertEqual(r['clone_groups'], 2)

    def test_owner_fingerprints_refresh_dependents_and_keep_duplicate_rows(self):
        import structural_quality_legacy as legacy

        def chain(side):
            return (f'def leaf_{side}(x):\n    return x + 1\n'
                    f'def middle_{side}(x):\n    return leaf_{side}(x) + 2\n'
                    f'def outer_{side}(x):\n    return middle_{side}(x) + 3\n')

        files = {'a.py': chain('left'), 'b.py': chain('right'),
                 'rebind.py': 'def repeated(x):\n    return x + 19\n\ndef repeated(x):\n    return x + 23\n'}
        symbols = [symbol for path, source in files.items() for symbol in legacy.python_symbols(path, source)[0]]
        repeated = [symbol for symbol in symbols if symbol.key == 'rebind.py#repeated']
        self.assertEqual(len(repeated), 2)
        with patch.object(legacy, 'digest', wraps=legacy.digest) as hashes:
            fingerprints = legacy.owned_fingerprints(symbols, files)

        for name in ('leaf', 'middle', 'outer'):
            self.assertEqual(fingerprints[f'a.py#{name}_left'], fingerprints[f'b.py#{name}_right'])
        self.assertEqual(fingerprints['rebind.py#repeated'], legacy.digest(repeated[-1].normalized))
        self.assertEqual(hashes.call_count, len(symbols) + 2)

    def test_python_scopes_and_defaults(self):
        for a, b in [('def a(x=x):\n    return x + 1\n', 'def b(y=y):\n    return y + 1\n'),
                     ('def a(x):\n    return [x for x in x]\n', 'def b(y):\n    return [y for x in y]\n')]:
            self.assertNotIn(DUP, rules(scan({'a.py': a, 'b.py': b})))

    def test_python_extraction_reuses_function_and_module_walks(self):
        import structural_quality_legacy as legacy

        source = """async def task(item, /, *, retry=default()):
    try:
        result = await client.fetch(item)
    except Failure as error:
        backup = report(error)
    if retry:
        return backup
    return result

notify(config.path, 'external')
"""
        with patch.object(ast, 'walk', wraps=ast.walk) as walks:
            (task, module), tree = legacy.python_symbols('worker.py', source)
        self.assertEqual(task.calls, ('default', 'client.fetch', 'report'))
        self.assertEqual(task.refs, {'default', 'client', 'Failure', 'report'})
        self.assertEqual(task.controls, ('try', 'if'))
        self.assertEqual(module.calls, ('notify',))
        self.assertEqual(module.refs, {'notify', 'config'})
        roots = [call.args[0] for call in walks.call_args_list]
        for node in (task.tree, module.tree, tree):
            self.assertEqual(roots.count(node), 1)

    def test_ouro_renaming_and_second_parser_abi(self):
        source = 'def first (x : Nat) : Nat := match x with | Z => 1 | S y => add y 2 end;\n'
        r = scan({'tools/a.ouro': '-- @entry first\n' + source,
                  'tools/b.ouro': '-- @entry second\n' + source.replace('first', 'second').replace('(x', '(input').replace('match x', 'match input')})
        self.assertIn(DUP, rules(r))
        nominal = scan({'a.ouro': 'inductive Item : Type := | One : Item;\n' + source.replace('Nat', 'Item').replace('Z', 'One'),
                        'b.ouro': 'inductive Item : Type := | One : Item;\n' + source.replace('Nat', 'Item').replace('Z', 'One')})
        self.assertNotIn(DUP, rules(nominal))

    def test_ouro_control_expression_keeps_called_definition_reachable(self):
        report = scan({'tools/bindings.ouro': """def check (value : Bool) : Bool := value;
def choose (value : Bool) : Nat :=
    (if check value then let answer : Nat := 1 in answer else 0);
-- @entry main
def main : Nat := choose True;
"""})
        self.assertTrue(report['pass'], report['findings'])

    def test_ouro_if_let_keeps_constructor_identity(self):
        report = scan({'tools/bindings.ouro': """inductive Choice : Type :=
    | One : Nat -> Choice | Two : Nat -> Choice;
-- @entry first
def first (item : Choice) : Nat := if let One field := item then add (add field 3) 2 else 0;
-- @entry second
def second (item : Choice) : Nat := if let One field := item then add (add field 3) 2 else 0;
-- @entry third
def third (item : Choice) : Nat := if let Two field := item then add (add field 3) 2 else 0;
"""})
        self.assertEqual([f['members'] for f in report['findings'] if f['rule_id'] == DUP],
                         [['tools/bindings.ouro#first', 'tools/bindings.ouro#second']])

    def test_c_wide_literals_preserve_bytes_and_delimiters(self):
        character_literals = [r"'/'", r"'\\'", "'x'"]
        wide_string = r'"{ not a body } \"quoted\" \\"'
        source = ("int scalar(int value) { if (value == L'/') value = L'\\\\'; return 'x'; }\n"
                  "const wchar_t *text = L" + wide_string + ";\n")
        for language in ("c", "h"):
            with self.subTest(language=language):
                tokens, comments = sq.lex(source, language)
                self.assertEqual(comments, [])
                self.assertEqual([t.value for t in tokens if t.value.startswith("'")],
                                 character_literals)
                self.assertEqual([t.value for t in tokens if t.value.startswith('"')], [wide_string])
                self.assertEqual([source[t.start:t.end] for t in tokens], [t.value for t in tokens])
                self.assertEqual([t.line for t in tokens if t.value in character_literals], [1, 1, 1])
                symbols, _, _ = sq.lexical_symbols("valid." + language, source)
                self.assertEqual([(s.name, s.line, s.end) for s in symbols], [("scalar", 1, 1)])
                report = scan({"valid." + language: source})
                self.assertTrue(report["complete"], report["issues"])

    def test_c_wide_literals_keep_malformed_inputs_blocking(self):
        for language in ("c", "h"):
            for source in (r"L'\\", "L'unterminated", 'L"unterminated', "name'"):
                with self.subTest(language=language, source=source):
                    with self.assertRaisesRegex(ValueError, "unclosed string at line 1"):
                        sq.lex(source, language)
                    self.assertFalse(scan({"bad." + language: source})["complete"])
            with self.assertRaisesRegex(ValueError, "unbalanced C delimiter regions"):
                sq.lexical_symbols("bad." + language, "int missing(void) { return L'\\\\';")

    def test_ouro_and_ocaml_apostrophe_identifiers_are_preserved(self):
        source = "name' other''"
        for language in ("ouro", "ml", "mli"):
            with self.subTest(language=language):
                tokens, comments = sq.lex(source, language)
                self.assertEqual([t.value for t in tokens], ["name'", "other''"])
                self.assertEqual(comments, [])

    def test_current_io_c_sources_extract_both_platform_branches(self):
        for path, expected in (
            ("runtime/ouro_io.c", {"proc_bounded_run_at@1", "proc_bounded_run_at@2"}),
            ("runtime/ouro_io_selftest.c", {"bounded_directory_child", "process_bounded_at_check"}),
        ):
            with self.subTest(path=path):
                symbols, _, _ = sq.lexical_symbols(path, (ROOT / path).read_text(encoding="utf-8"))
                self.assertTrue(expected <= {symbol.name for symbol in symbols})

    def test_c_renamed_locals(self):
        source = 'int first(int x) { int y = x + 2; if (y < 3) return x; return y * 4; }'
        self.assertIn(DUP, rules(scan({'a.c': source, 'b.c': source.replace('first', 'second').replace('x', 'input').replace('y', 'result')})))

    def test_grouped_import_nominal_owners(self):
        body = 'def choose (x : Item) : Item := match x with | One => One end;\n'
        common = 'def common : Type := Type;\n'
        nominal = 'inductive Item : Type := | One : Item;\n'
        layouts = [
            'import "common.ouro";\nimport "{owner}";\n',
            'import "common.ouro", "{owner}";\n',
            'import "common.ouro", -- the nominal dependency is second\n  "{owner}",\n;\n',
        ]
        for layout in layouts:
            with self.subTest(layout=layout):
                files = {'common.ouro': common, 'left.ouro': nominal, 'right.ouro': nominal,
                         'a.ouro': layout.format(owner='left.ouro') + body,
                         'b.ouro': layout.format(owner='right.ouro') + body}
                symbols = [symbol for path, text in files.items() for symbol in sq.lexical_symbols(path, text)[0]]
                fingerprints = sq.owned_fingerprints(symbols, files)
                self.assertNotEqual(fingerprints['a.ouro#choose'], fingerprints['b.ouro#choose'])
                files['b.ouro'] = layout.format(owner='left.ouro') + body
                symbols = [symbol for path, text in files.items() for symbol in sq.lexical_symbols(path, text)[0]]
                fingerprints = sq.owned_fingerprints(symbols, files)
                self.assertEqual(fingerprints['a.ouro#choose'], fingerprints['b.ouro#choose'])

    def test_grouped_import_escaped_owner_and_malformed_tail(self):
        nominal = 'inductive Item : Type := | One : Item;\n'
        body = 'def choose (x : Item) : Item := match x with | One => One end;\n'
        files = {'common.ouro': '', 'a"b.ouro': nominal,
                 'a.ouro': 'import "common.ouro", "a\\"b.ouro";\n' + body,
                 'b.ouro': 'import "a\\"b.ouro";\n' + body}
        symbols = [symbol for path, text in files.items() for symbol in sq.lexical_symbols(path, text)[0]]
        fingerprints = sq.owned_fingerprints(symbols, files)
        self.assertEqual(fingerprints['a.ouro#choose'], fingerprints['b.ouro#choose'])
        with self.assertRaisesRegex(ValueError, 'malformed quoted import'):
            sq.owned_fingerprints([], {'a.ouro': 'import "first.ouro", missing;\n'})

    def test_import_scopes_project_shared_nominal_constructors_once(self):
        class TrackedTokens(list):
            scans = 0

            def __iter__(self):
                self.scans += 1
                return super().__iter__()

            def __getitem__(self, index):
                if isinstance(index, slice):
                    self.scans += 1
                return super().__getitem__(index)

        body = 'def choose (x : Item) : Item := match x with | One => One end;\n'
        files = {'types.ouro': 'inductive Item : Type := | One : Item;\n',
                 'bridge.ouro': 'import "types.ouro";\n',
                 'a.ouro': 'import "bridge.ouro", "types.ouro";\n' + body,
                 'b.ouro': 'import "bridge.ouro";\n' + body}
        symbols = [symbol for path, source in files.items() for symbol in sq.lexical_symbols(path, source)[0]]
        nominal = next(symbol for symbol in symbols if symbol.kind == 'inductive')
        nominal.tokens = TrackedTokens(nominal.tokens)
        fingerprints = sq.owned_fingerprints(symbols, files)
        self.assertEqual(fingerprints['a.ouro#choose'], fingerprints['b.ouro#choose'])
        self.assertEqual(nominal.tokens.scans, 1)

    def test_wrapper_chain_and_validation_boundary(self):
        source = 'def _a(x):\n    return _b(x)\ndef _b(x):\n    return work(x)\ndef work(x):\n    return x + 1\n_a(1)\n'
        self.assertIn('STRUCT_WRAPPER_CHAIN', rules(scan({'tools/a.py': source})))
        valid = source.replace('return _b(x)', 'if x < 0:\n        raise ValueError(x)\n    return _b(x)')
        self.assertNotIn('STRUCT_WRAPPER_CHAIN', rules(scan({'tools/a.py': valid})))
        self.assertNotIn('STRUCT_WRAPPER_CHAIN', rules(scan({'tools/a.py': source.replace('_a', 'public_a').replace('_b', 'public_b')})))
        shell = '_a() { _b "$@"; }\n_b() { work "$@"; }\nwork() { printf "%s" "$1"; }\n_a "$@"\n'
        self.assertIn('STRUCT_SCRIPT_WRAPPER_CHAIN', rules(scan({'scripts/a.sh': shell})))
        self.assertNotIn('STRUCT_SCRIPT_WRAPPER_CHAIN', rules(scan({'scripts/a.sh': shell.replace('_b "$@";', 'test -n "$1" || exit 1; _b "$@";')})))

    def test_top_level_references_keep_macro_literal_and_declaration_line_rules(self):
        import structural_quality_legacy as legacy

        source = (
            'static int macro_target(void) { return 1; }\n'
            'static int internal_target(void) { return 2; }\n'
            'static int caller(void) { return internal_target(); }\n'
            'static int same_line(void) { return 3; } int (*same_line_ref)(void) = same_line;\n'
            'static int literal_target(void) { return 4; }\n'
            '#define ENTRY macro_target\n'
            'const char *dynamic_entries = "literal_target";\n'
        )
        iterations = 0
        extract = legacy.lexical_symbols

        class TrackedTokens(list):
            def __iter__(self):
                nonlocal iterations
                iterations += 1
                return super().__iter__()

        def tracked_extract(path, text):
            symbols, tokens, comments = extract(path, text)
            return symbols, TrackedTokens(tokens), comments

        with (patch.object(legacy, 'lexical_symbols', side_effect=tracked_extract),
              patch.object(legacy, 'dead_findings', wraps=legacy.dead_findings) as check):
            report = scan({'runtime/visibility.c': source})
        self.assertTrue(report['complete'], report['issues'])
        public = {symbol.name for symbol in check.call_args.args[0] if symbol.public}
        self.assertEqual(public, {'macro_target', 'literal_target'})
        self.assertEqual(iterations, 3)

    def test_dead_private_public_and_dynamic_roots(self):
        self.assertIn('STRUCT_UNUSED_DEF', rules(scan({'a.py': 'def _unused():\n    return 1\n'})))
        self.assertNotIn('STRUCT_UNUSED_DEF', rules(scan({'a.py': 'def api():\n    return 1\n'})))
        self.assertNotIn('STRUCT_UNUSED_DEF', rules(scan({'a.py': 'def _dispatch():\n    return 1\nregistry = {"_dispatch": _dispatch}\n'})))
        self.assertIn('STRUCT_UNUSED_DEF', rules(scan({'a.py': 'def _recursive(x):\n    return _recursive(x)\n'})))
        cycle = 'def _a(x):\n    return _b(x) + 1\ndef _b(x):\n    return _a(x) + 1\n'
        self.assertEqual(sum(f['rule_id'] == 'STRUCT_UNUSED_DEF' for f in scan({'a.py': cycle})['findings']), 2)
        self.assertNotIn('STRUCT_UNUSED_DEF', rules(scan({'a.py': cycle + '_a(1)\n'})))

    def test_orphan_module_and_private_configuration(self):
        self.assertIn('STRUCT_UNUSED_SCRIPT', rules(scan({'scripts/orphan.py': 'def _lost():\n    return 1\n'})))
        self.assertNotIn('STRUCT_UNUSED_SCRIPT', rules(scan({'scripts/public.py': 'def main():\n    return 1\n'})))
        for name, rule in [('_OLD_MODE', 'STRUCT_UNUSED_MODE'), ('_OLD_CONFIG', 'STRUCT_UNUSED_CONFIG')]:
            self.assertIn(rule, rules(scan({'a.py': name + ' = 1\n'})))
            self.assertNotIn(rule, rules(scan({'a.py': name + ' = 1\nprint(' + name + ')\n'})))

    def test_dead_ouro_type(self):
        self.assertIn('STRUCT_UNUSED_TYPE', rules(scan({'tools/a.ouro': 'inductive Unused : Type := | UnusedC : Unused;'})))
        self.assertNotIn('STRUCT_UNUSED_TYPE', rules(scan({'std/a.ouro': 'inductive Public : Type := | PublicC : Public;'})))

    def test_legacy_fallback_and_platform_boundary(self):
        source = 'def run(x):\n    try:\n        return native(x)\n    except OSError:\n        return legacy(x)\n'
        self.assertIn('STRUCT_LEGACY_FALLBACK', rules(scan({'a.py': source})))
        classified = mark('STRUCT_LEGACY_FALLBACK', [], 'platform-adapter') + source
        r = scan({'a.py': classified})
        self.assertTrue(r['pass'])
        self.assertEqual(r['intentional_cases'], 1)
        self.assertNotIn('STRUCT_LEGACY_FALLBACK', rules(scan({'a.py': source.replace('legacy(x)', 'posix_adapter(x)')})))
        self.assertIn('STRUCT_LEGACY_FALLBACK', rules(scan({'a.ouro': 'def run (x : Nat) : Nat := match native x with | Left e => legacy_parse x | Right v => v end;'})))
        self.assertNotIn('STRUCT_LEGACY_FALLBACK', rules(scan({'a.ouro': 'def run (x : Nat) (fallback : Nat) : Nat := match native x with | Left e => fallback | Right v => v end;'})))

    def test_ouro_fallback_reads_only_the_start_of_each_failure_arm(self):
        class TrackedTokens(list):
            copied = 0

            def __getitem__(self, index):
                if isinstance(index, slice):
                    self.copied += len(range(*index.indices(len(self))))
                return super().__getitem__(index)

        source = """def run (x : Nat) : Nat := match native x with
    | Left e => fallback_value
    | Error e => fallback_parse x
    | Right v => v
    end;
"""
        symbols, _, _ = sq.lexical_symbols('a.ouro', source)
        for symbol in symbols:
            symbol.tokens = TrackedTokens(symbol.tokens)
        findings = sq.fallback_findings(symbols)
        self.assertEqual([finding['evidence'] for finding in findings],
                         [{'failure_constructor': 'Error', 'alternate_call': 'fallback_parse'}])
        self.assertEqual(sum(symbol.tokens.copied for symbol in symbols), 0)

    def test_silent_and_shell_backend_fallback(self):
        self.assertIn('STRUCT_SILENT_FALLBACK', rules(scan({'a.py': 'def run():\n    try:\n        native()\n    except:\n        pass\n'})))
        self.assertIn('STRUCT_PARALLEL_BACKEND_FALLBACK', rules(scan({'a.sh': 'native "$@" || python3 legacy.py "$@"\n'})))
        self.assertNotIn('STRUCT_PARALLEL_BACKEND_FALLBACK', rules(scan({'a.sh': 'native "$@" || exit 1\n'})))
        self.assertIn('STRUCT_LEGACY_FALLBACK', rules(scan({'a.sh': 'if native "$@"; then exit 0; else legacy "$@"; fi\n'})))
        self.assertNotIn('STRUCT_LEGACY_FALLBACK', rules(scan({'a.sh': 'if [ "$platform" = old ]; then legacy "$@"; else native "$@"; fi\n'})))

    def test_native_error_does_not_restart_legacy_pipeline(self):
        source = 'int compile(int input) { if (!parse(input)) return compile_legacy(input); return check(input); }'
        self.assertIn('STRUCT_LEGACY_FALLBACK', rules(scan({'a.c': source})))
        for valid in [source.replace('compile_legacy(input)', 'parse_error(input)'),
                      source.replace('!parse(input)', 'platform == 0')]:
            self.assertNotIn('STRUCT_LEGACY_FALLBACK', rules(scan({'a.c': valid})))

    def test_shell_status_capture_preserves_unconditional_verification(self):
        rule = 'STRUCT_PARALLEL_BACKEND_FALLBACK'
        for separator in ['\n', '; ']:
            source = 'native "$@" || native_status=$?' + separator + 'python3 verify.py\nexit "$native_status"\n'
            with self.subTest(separator=separator):
                self.assertNotIn(rule, rules(scan({'a.sh': source})))
        for alternate in ['\npython3 legacy.py', '\\\npython3 legacy.py',
                          '{\npython3 legacy.py\n}', 'python3 --isolated --verbose legacy.py']:
            with self.subTest(alternate=alternate):
                self.assertIn(rule, rules(scan({'a.sh': 'native "$@" || ' + alternate + '\n'})))

    def test_inventory_fallback_cannot_hide_missing_inputs(self):
        source = 'def inventory(root):\n    try:\n        return list(os.scandir(root))\n    except OSError:\n        return list(root.glob("*"))\n'
        rule = 'STRUCT_PARALLEL_BACKEND_FALLBACK'
        self.assertIn(rule, rules(scan({'a.py': source})))
        self.assertNotIn(rule, rules(scan({'a.py': source.replace('return list(root.glob("*"))', 'raise')})))

    def test_historical_parser_launcher_and_options_copies(self):
        fixture_source = 'inductive Token : Type := | Name : Nat -> Token | Keyword : Nat -> Token | Eof : Token;\n'
        abi = 'import "../tokens.ouro";\ndef payload (x : Token) : Nat := match x with | Name n => n | Keyword k => k | Eof => 0 end;\ndef tag (x : Token) : Nat := match x with | Name n => 1 | Keyword k => 2 | Eof => 3 end;\n'
        parser = scan({'tokens.ouro': fixture_source, 'compiler/a.ouro': abi, 'compiler/b.ouro': abi.replace('payload', 'data').replace('tag', 'kind')})
        self.assertEqual(parser['clone_groups'], 2)
        launcher = 'start() { if [ -x "$compiler" ]; then "$compiler" "$@"; else rebuild "$compiler" || exit 1; "$compiler" "$@"; fi; }\nstart "$@"\n'
        self.assertIn(DUP, rules(scan({'scripts/a.sh': launcher, 'scripts/b.sh': launcher.replace('start', 'launch')})))
        options = 'def options(parser):\n    args = parser.parse_args()\n    out = (root / args.out).resolve()\n    if not out.is_relative_to(root):\n        raise ValueError("escape")\n    return args, out\n'
        r = scan({name + '.py': options.replace('options', name) for name in ['docs', 'project', 'workflow']})
        clone = next(f for f in r['findings'] if f['rule_id'] == DUP)
        self.assertEqual(len(clone['members']), 3)

    def test_path_graph_process_report_families(self):
        examples = {
            'path': 'def normalize_path(path):\n    return path.resolve().relative_to(root)\n',
            'graph': 'def graph_traversal(edges):\n    seen = set()\n    for node in edges:\n        seen.add(node)\n    return seen\n',
            'process': 'def run_process(argv):\n    result = subprocess.run(argv)\n    if result.returncode:\n        raise ValueError(result.stderr)\n    return result.stdout\n',
            'report': 'def json_report(data):\n    envelope = {"kind": "report", "findings": data}\n    return json.dumps(envelope)\n'}
        for family, source in examples.items():
            with self.subTest(family=family):
                r = scan({'a.py': source, 'b.py': source})
                self.assertIn(DUP, rules(r))
                f = next(f for f in r['findings'] if f['rule_id'] == DUP)
                self.assertIn(sq.SPECIAL_RULES[family], f['evidence']['rule_families'])

    def test_cross_language_responsibility_candidate(self):
        r = scan({'a.py': 'def normalize_path(path):\n    if path.is_absolute():\n        return path.resolve()\n    return root.resolve()\n',
                  'tools/b.ouro': 'def normalize_path (path : String) : String := match path_is_absolute path with | True => path_resolve path | False => path_resolve root end;'})
        self.assertIn('STRUCT_CROSS_LANGUAGE_DUPLICATION', rules(r))
        for f in r['findings']:
            if f['rule_id'] == 'STRUCT_CROSS_LANGUAGE_DUPLICATION':
                self.assertEqual(f['severity'], 'info')

    def test_lexical_comments_index_exports_and_keep_adjacent_mark_order(self):
        import structural_quality_legacy as legacy

        source = (
            'static int early(void) { return 0; }\n'
            '/* @export early, entry; @entry listed */\n'
            'static int entry(void) { return 0; }\n'
            '/* ouro-structural: detached invalid JSON */\n\n'
            'static int internal(void) { return 0; }\n'
            '/* ouro-structural: {"rule":"first"} */ /* ouro-structural: {"rule":"second"} */\n'
            'static int listed(void) { return 0; }\n'
            '/* @api internal */\n'
        )
        with patch.object(legacy.re, 'findall', wraps=legacy.re.findall) as patterns:
            symbols, _, _ = legacy.lexical_symbols('runtime/exports.c', source)
        self.assertEqual({symbol.name for symbol in symbols if symbol.public}, {'entry', 'listed'})
        self.assertEqual({symbol.name: symbol.classifications for symbol in symbols}, {
            'early': [], 'entry': [], 'internal': [], 'listed': [{'rule': 'first'}, {'rule': 'second'}],
        })
        checks = [call for call in patterns.call_args_list if call.args[0].startswith('@(?:entry|export|api)')]
        self.assertEqual(len(checks), 2)

    def test_oracle_and_trust_classification_is_exact(self):
        for category in ['independent-oracle', 'trust-boundary']:
            files = {'a.py': mark(DUP, ['b.py#second'], category) + declaration('first'), 'b.py': declaration('second')}
            r = scan(files)
            self.assertTrue(r['pass'])
            self.assertEqual(r['intentional_cases'], 1)
            files['c.py'] = declaration('third')
            self.assertFalse(scan(files)['pass'])

    def test_reject_broad_stale_unknown_detached_classifications(self):
        for annotation in [mark(DUP, ['scripts/*#second']), mark('UNKNOWN', []), mark(DUP, ['b.py#second'], 'existing'),
                           mark(DUP, ['b.py#second']), mark(DUP, []) + '\n']:
            r = scan({'a.py': annotation + declaration('first')})
            self.assertFalse(r['complete'])

    def test_comments_and_literals_are_not_suppression_or_callers(self):
        source = '# _unused is mentioned in a comment\ndef _unused():\n    return 2\n'
        self.assertIn('STRUCT_UNUSED_DEF', rules(scan({'a.py': source})))
        self.assertTrue(scan({'a.py': 'value = "ouro-structural: garbage"\n'})['complete'])

    def test_encoded_native_symbol_roots(self):
        helper = 'def raw_helper (value : Nat) : Nat := add value 1;'
        encoded = ','.join(str(ord(char)) for char in 'raw_helper')
        files = {'runtime/helper.ouro': helper,
                 'compiler/names.ouro': f'def selected : List Nat := [{encoded}];'}
        self.assertFalse(any(f['rule_id'] == 'STRUCT_UNUSED_DEF' and
                             f['symbol'] == 'raw_helper' for f in scan(files)['findings']))
        for source in (f'-- [{encoded}]', f'def text : String := "[{encoded}]";',
                       f'def broken : List Nat := [{encoded},999];',
                       f'def broken : List Nat := [{encoded}, other];'):
            files['compiler/names.ouro'] = source
            findings = scan(files)['findings']
            self.assertTrue(any(f['rule_id'] == 'STRUCT_UNUSED_DEF' and
                                f['symbol'] == 'raw_helper' for f in findings), source)

    def test_configuration_alias_and_compatibility(self):
        source = 'def config():\n    return os.getenv("BUILD_DIR", os.getenv("OLD_DIR", "out"))\n'
        self.assertIn('STRUCT_CONFIG_ALIAS_CHAIN', rules(scan({'a.py': source})))
        self.assertNotIn('STRUCT_CONFIG_ALIAS_CHAIN', rules(scan({'a.py': source.replace('os.getenv("OLD_DIR", "out")', 'config_field')})))
        self.assertIn('STRUCT_COMPAT_RESIDUE', rules(scan({'a.py': 'def legacy_api(x):\n    return current(x)\n'})))

    def test_runtime_inventory_and_policy(self):
        self.assertIn('STRUCT_UNUSED_RUNTIME_PRIMITIVE', rules(scan({'std/runtime.ouro': 'axiom prim_unused : Nat -> Nat;'})))
        self.assertNotIn('STRUCT_UNUSED_RUNTIME_PRIMITIVE', rules(scan({'std/runtime.ouro': 'axiom prim_used : Nat -> Nat;', 'tools/a.ouro': 'def main : Nat := prim_used 1;'})))
        aliases = 'void *dispatch(char *name) { if (strcmp(name, "old") == 0) v = ouro_clos(f, 0); else if (strcmp(name, "new") == 0) v = ouro_clos(f, 0); return v; }'
        self.assertIn('STRUCT_REDUNDANT_RUNTIME_PRIMITIVE', rules(scan({'runtime/runtime.c': aliases})))
        self.assertNotIn('STRUCT_REDUNDANT_RUNTIME_PRIMITIVE', rules(scan({'runtime/runtime.c': aliases.replace('"new") == 0) v = ouro_clos(f', '"new") == 0) v = ouro_clos(g')})))
        self.assertIn('STRUCT_POLICY_IN_RUNTIME', rules(scan({'runtime/runtime.c': 'void *read_manifest(void) { return parse("Ouro.seal"); }'})))
        self.assertNotIn('STRUCT_POLICY_IN_RUNTIME', rules(scan({'runtime/runtime.c': 'void *read_file(char *path) { return fopen(path, "r"); }'})))

    def test_classify_indexes_by_rule_and_members(self):
        finding = {
            'id': 'dup-1',
            'rule_id': DUP,
            'members': ['a.py#first', 'b.py#second'],
            'classification': None,
        }

        class Symbol:
            def __init__(self):
                self.key = 'a.py#first'
                self.classifications = [dict(rule=DUP, category='independent-oracle',
                    related=['b.py#second'],
                    reason='Independent expected-result computation for differential checking.')]

        issues = sq.classify([finding], [Symbol()])
        self.assertEqual(issues, [])
        self.assertEqual(finding['classification']['at'], 'a.py#first')
        stale = sq.classify(
            [{'id': 'other', 'rule_id': DUP, 'members': ['a.py#first'], 'classification': None}],
            [Symbol()],
        )
        self.assertEqual(stale, ['a.py#first: stale classification for STRUCT_DUPLICATE_IMPLEMENTATION'])

    def test_literal_unreachable_branch(self):
        for expr, expected in [('False', True), ('enabled', False)]:
            self.assertEqual('STRUCT_UNREACHABLE_BRANCH' in rules(scan({'a.py': f'def run():\n    if {expr}:\n        work()\n'})), expected)

    def test_ouro_literal_match_check_avoids_token_slices(self):
        class TrackedTokens(list):
            slices = 0

            def __getitem__(self, index):
                if isinstance(index, slice):
                    self.slices += 1
                return super().__getitem__(index)

        for expr in ('True', 'False', 'condition'):
            with self.subTest(expr=expr):
                source = f'def run : Nat := match {expr} with | True => 1 | False => 0 end;'
                symbols, _, _ = sq.lexical_symbols('a.ouro', source)
                for symbol in symbols:
                    symbol.tokens = TrackedTokens(symbol.tokens)
                findings = sq.unreachable_findings(symbols)
                expected = [] if expr == 'condition' else [{'condition': 'literal Boolean match'}]
                self.assertEqual([finding['evidence'] for finding in findings], expected)
                self.assertEqual(sum(symbol.tokens.slices for symbol in symbols), 0)

    def test_deterministic_order_and_identity(self):
        files = {'a.py': declaration('first'), 'b.py': declaration('second')}
        self.assertEqual(scan(files), scan(dict(reversed(list(files.items())))))
        one = next(f for f in scan(files)['findings'] if f['rule_id'] == DUP)
        files['a.py'] = '# comment\n' + files['a.py']
        two = next(f for f in scan(files)['findings'] if f['rule_id'] == DUP)
        self.assertEqual(one['id'], two['id'])

    def test_fixture_boundaries_check_paths_without_resolving_canonical_harness_again(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            harness = root / 'tests/analyze'
            paths = ['tests/analyze/group/b.ouro', 'tests/analyze/group/a.ouro',
                     'tests/analyze/group_other/neighbor.ouro', 'tests/analyze/explicit.ouro']
            for name in paths:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            manifest = harness / 'manifest.json'

            def write(data):
                manifest.write_text(json.dumps(data), encoding='utf-8')

            write({'scope': 'group', 'path': paths[-1]})
            with patch.object(Path, 'resolve', autospec=True, side_effect=Path.resolve) as resolve:
                records = sq.boundaries(root, paths)
            self.assertEqual(list(records), [paths[0], paths[1], paths[-1]])
            self.assertEqual([call.args[0] for call in resolve.call_args_list], [harness / 'group', root / paths[-1]])
            self.assertEqual(sq.boundaries(root / '..' / root.name, paths), records)

            write({'scope': '../outside', 'path': 17})
            with self.assertRaisesRegex(ValueError, r'^fixture scope escapes its harness: tests/analyze/manifest\.json$'):
                sq.boundaries(root, paths)
            write({'path': 'tests/outside.ouro'})
            with self.assertRaisesRegex(ValueError, r'^fixture path escapes its harness: tests/analyze/manifest\.json$'):
                sq.boundaries(root, paths)
            write({'path': 'tests/analyze/absent.ouro'})
            with self.assertRaisesRegex(ValueError, r'^required fixture missing from inventory: tests/analyze/absent\.ouro$'):
                sq.boundaries(root, paths)

    def test_generated_boundaries_and_missing_inputs(self):
        with tempfile.TemporaryDirectory(prefix='ouro-structural-') as directory:
            root = Path(directory).resolve()
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            (root / 'docs').mkdir()
            (root / 'a.c').write_text('int algorithm(int x) { if (x < 0) return -x; return x + 3; }\n')
            (root / 'generated.c').write_bytes((root / 'a.c').read_bytes())
            hashes = root / 'docs/generated_artifact_hashes.sha256'
            hashes.write_text(hashlib.sha256((root / 'generated.c').read_bytes()).hexdigest() + '  generated.c\n')
            with patch.object(Path, 'resolve', autospec=True, side_effect=Path.resolve) as resolve:
                paths = sq.inventory(root)
            self.assertEqual(paths, ['a.c', 'docs/generated_artifact_hashes.sha256', 'generated.c'])
            self.assertEqual([call.args[0] for call in resolve.call_args_list], [root / path for path in paths])
            self.assertEqual(sq.inventory(root / '..' / root.name), paths)

            def resolve_escape(path, *args, _resolve=Path.resolve, **kwargs):
                return root.parent / 'outside.c' if path == root / 'a.c' else _resolve(path, *args, **kwargs)

            with (patch.object(Path, 'resolve', autospec=True, side_effect=resolve_escape),
                  self.assertRaisesRegex(ValueError, r'^required tracked/source input missing or unsafe: a\.c$')):
                sq.inventory(root)
            self.assertEqual(sq.analyze(root)['clone_groups'], 0)
            (root / 'generated.c').write_text('stale')
            with self.assertRaisesRegex(ValueError, 'stale'):
                sq.analyze(root)
            subprocess.run(['git', '-C', str(root), 'add', 'a.c'], check=True)
            (root / 'a.c').unlink()
            with self.assertRaisesRegex(ValueError, 'missing'):
                sq.analyze(root)

    def test_incomplete_extraction_fails(self):
        for path, source in [('a.py', 'def broken('), ('a.c', 'int f(void) {'), ('a.ouro', 'def broken := "unterminated')]:
            self.assertFalse(scan({path: source})['complete'])

    def test_lex_fixture_boundary_checks_negative_contract_and_confinement(self):
        with tempfile.TemporaryDirectory(prefix='ouro-structural-') as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            corpus = root / 'quality/fixtures/structural_lex'
            corpus.mkdir(parents=True)
            fixture = corpus / 'negative.ouro'
            fixture.write_text('def broken := "unterminated')
            manifest = corpus / 'manifest.json'
            case = {'name': 'negative', 'file': fixture.name, 'language': 'ouro', 'error': True}
            manifest.write_text(json.dumps({'kind': 'ouro.structural-lex-corpus.v1', 'cases': [case]}))
            report = sq.analyze(root)
            self.assertTrue(report['pass'], report['issues'])
            self.assertEqual(report['files'][0]['boundary']['owner'], manifest.relative_to(root).as_posix())
            fixture.write_text('def accepted : Nat := 0;')
            self.assertIn('negative lex fixture unexpectedly accepted', '\n'.join(sq.analyze(root)['issues']))
            fixture.unlink()
            with self.assertRaisesRegex(ValueError, 'missing'):
                sq.analyze(root)
            (root / 'outside.ouro').write_text('def broken := "unterminated')
            case['file'] = '../../../outside.ouro'
            manifest.write_text(json.dumps({'kind': 'ouro.structural-lex-corpus.v1', 'cases': [case]}))
            with self.assertRaisesRegex(ValueError, 'escapes'):
                sq.analyze(root)

    def test_semantic_fixture_manifest_preserves_production_and_unlisted_checks(self):
        with tempfile.TemporaryDirectory(prefix='ouro-structural-') as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            corpus = root / 'tests/clippy_semantic'
            (corpus / 'fixtures').mkdir(parents=True)
            (root / 'tools').mkdir()
            selected = 'tests/clippy_semantic/fixtures/selected.ouro'
            others = ['tools/owner.ouro', 'tests/clippy_semantic/laws.ouro',
                      'tests/clippy_semantic/fixtures/unlisted.ouro']
            source = ('def compute (value : Nat) : Nat := match value with '
                      '| Z => 0 | S smaller => add smaller 4 end;\n')
            for path in [selected, *others]:
                (root / path).write_text(source)
            manifest = corpus / 'cases.json'
            data = {'kind': 'ouro.clippy-semantic-precision.v1',
                    'cases': [{'path': selected, 'codes': []}]}
            manifest.write_text(json.dumps(data))

            report = sq.analyze(root)
            self.assertTrue(report['complete'], report['issues'])
            rows = {row['path']: row for row in report['files']}
            self.assertEqual(rows[selected]['boundary'],
                             {'kind': 'fixture-input', 'owner': 'tests/clippy_semantic/cases.json'})
            self.assertGreater(rows[selected]['symbols'], 0)
            for path in others:
                self.assertIsNone(rows[path]['boundary'])
            clones = [finding for finding in report['findings'] if finding['rule_id'] == DUP]
            self.assertEqual(len(clones), 1)
            self.assertEqual(set(clones[0]['members']), {path + '#compute' for path in others})
            self.assertFalse(report['pass'])

            (root / selected).write_text('def broken := "unterminated')
            self.assertFalse(sq.analyze(root)['complete'])
            (root / selected).write_text(source)
            for path, error in [('tests/clippy_semantic/fixtures/missing.ouro', 'missing'),
                                ('tools/owner.ouro', 'escapes'), (None, 'invalid fixture path')]:
                with self.subTest(path=path):
                    data['cases'][0]['path'] = path
                    manifest.write_text(json.dumps(data))
                    with self.assertRaisesRegex(ValueError, error):
                        sq.analyze(root)

    def test_malformed_report_is_rejected(self):
        report = scan({'a.py': declaration('first')})
        sq.validate_report(report)
        for key, value in [('kind', 'other'), ('pass', 1), ('complete', None), ('files_scanned', 999), ('actionable_findings', -1), ('findings', {})]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                sq.validate_report({**report, key: value})
        bad = scan({'a.py': declaration('first'), 'b.py': declaration('second')})
        bad['actionable_findings'] = 0
        bad['pass'] = True
        with self.assertRaisesRegex(ValueError, 'count mismatch'):
            sq.validate_report(bad)


class StructuralLexParity(unittest.TestCase):
    def test_native_lex_driver_matches_legacy_oracle(self):
        script = ROOT / 'scripts' / 'structural_lex_parity.py'
        result = subprocess.run([sys.executable, '-B', str(script)], cwd=ROOT,
                                capture_output=True, text=True, timeout=600)
        if result.returncode == 77:
            self.skipTest(result.stderr.strip() or 'native lex driver unavailable')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
