#!/usr/bin/env python3
"""Regression and false-positive contracts for strict-quality --structural."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

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

    def test_renamed_helpers_propagate(self):
        r = scan({'a.py': declaration('helper') + 'def first(x):\n    if x:\n        return helper(x)\n    return helper(3)\n',
                  'b.py': declaration('other') + 'def second(y):\n    if y:\n        return other(y)\n    return other(3)\n'})
        self.assertEqual(r['clone_groups'], 2)

    def test_python_scopes_and_defaults(self):
        for a, b in [('def a(x=x):\n    return x + 1\n', 'def b(y=y):\n    return y + 1\n'),
                     ('def a(x):\n    return [x for x in x]\n', 'def b(y):\n    return [y for x in y]\n')]:
            self.assertNotIn(DUP, rules(scan({'a.py': a, 'b.py': b})))

    def test_ouro_renaming_and_second_parser_abi(self):
        source = 'def first (x : Nat) : Nat := match x with | Z => 1 | S y => add y 2 end;\n'
        r = scan({'tools/a.ouro': '-- @entry first\n' + source,
                  'tools/b.ouro': '-- @entry second\n' + source.replace('first', 'second').replace('(x', '(input').replace('match x', 'match input')})
        self.assertIn(DUP, rules(r))
        nominal = scan({'a.ouro': 'inductive Item : Type := | One : Item;\n' + source.replace('Nat', 'Item').replace('Z', 'One'),
                        'b.ouro': 'inductive Item : Type := | One : Item;\n' + source.replace('Nat', 'Item').replace('Z', 'One')})
        self.assertNotIn(DUP, rules(nominal))

    def test_c_renamed_locals(self):
        source = 'int first(int x) { int y = x + 2; if (y < 3) return x; return y * 4; }'
        self.assertIn(DUP, rules(scan({'a.c': source, 'b.c': source.replace('first', 'second').replace('x', 'input').replace('y', 'result')})))

    def test_wrapper_chain_and_validation_boundary(self):
        source = 'def _a(x):\n    return _b(x)\ndef _b(x):\n    return work(x)\ndef work(x):\n    return x + 1\n_a(1)\n'
        self.assertIn('STRUCT_WRAPPER_CHAIN', rules(scan({'tools/a.py': source})))
        valid = source.replace('return _b(x)', 'if x < 0:\n        raise ValueError(x)\n    return _b(x)')
        self.assertNotIn('STRUCT_WRAPPER_CHAIN', rules(scan({'tools/a.py': valid})))
        self.assertNotIn('STRUCT_WRAPPER_CHAIN', rules(scan({'tools/a.py': source.replace('_a', 'public_a').replace('_b', 'public_b')})))
        shell = '_a() { _b "$@"; }\n_b() { work "$@"; }\nwork() { printf "%s" "$1"; }\n_a "$@"\n'
        self.assertIn('STRUCT_SCRIPT_WRAPPER_CHAIN', rules(scan({'scripts/a.sh': shell})))
        self.assertNotIn('STRUCT_SCRIPT_WRAPPER_CHAIN', rules(scan({'scripts/a.sh': shell.replace('_b "$@";', 'test -n "$1" || exit 1; _b "$@";')})))

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

    def test_literal_unreachable_branch(self):
        for expr, expected in [('False', True), ('enabled', False)]:
            self.assertEqual('STRUCT_UNREACHABLE_BRANCH' in rules(scan({'a.py': f'def run():\n    if {expr}:\n        work()\n'})), expected)

    def test_deterministic_order_and_identity(self):
        files = {'a.py': declaration('first'), 'b.py': declaration('second')}
        self.assertEqual(scan(files), scan(dict(reversed(list(files.items())))))
        one = next(f for f in scan(files)['findings'] if f['rule_id'] == DUP)
        files['a.py'] = '# comment\n' + files['a.py']
        two = next(f for f in scan(files)['findings'] if f['rule_id'] == DUP)
        self.assertEqual(one['id'], two['id'])

    def test_generated_boundaries_and_missing_inputs(self):
        with tempfile.TemporaryDirectory(prefix='ouro-structural-') as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            (root / 'docs').mkdir()
            (root / 'a.c').write_text('int algorithm(int x) { if (x < 0) return -x; return x + 3; }\n')
            (root / 'generated.c').write_bytes((root / 'a.c').read_bytes())
            hashes = root / 'docs/generated_artifact_hashes.sha256'
            hashes.write_text(hashlib.sha256((root / 'generated.c').read_bytes()).hexdigest() + '  generated.c\n')
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


if __name__ == '__main__':
    unittest.main()
