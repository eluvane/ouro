"""Negative controls for source-bound compiler-suite evidence."""
from copy import deepcopy
import json
import shutil
import unittest
from unittest.mock import patch
import uuid

from ourosmith import compiler_evidence as evidence
from ourosmith.limits import RunResult


def property_output():
    return ('ok scope shapes count=12 every-rel mutations=28\n'
            'ok scoped properties count=400 start=0\n'
            'ok typed properties count=400 start=0\n'
            'ok out-of-scope mutations count=109 nonfirst=40\n'
            'ok typed generation buckets=' + ','.join(['16'] * 25) + '\n'
            'ok compiler properties seed=2026 samples=800\n')


class EvidenceTreeTests(unittest.TestCase):
    def tearDown(self):
        self.assertTrue(self.root.resolve().is_relative_to(self.parent.resolve()))
        shutil.rmtree(self.root)


class CompilerEvidenceTests(EvidenceTreeTests):
    def setUp(self):
        self.parent = evidence.ROOT / '_build/compiler-evidence-selftest'
        self.root = self.parent / uuid.uuid4().hex
        self.directory = self.root / '_build/suite'
        self.directory.mkdir(parents=True)
        self.enterContext(patch.object(evidence, 'ROOT', self.root))
        self.enterContext(patch('ourosmith.host.environment', return_value={}))
        self.native_receipt = {'binary_sha256': 'a' * 64, 'key': 'b' * 64}
        self.receipt = self.enterContext(patch.object(evidence, 'receipt_for',
            return_value=(self.native_receipt, [], {})))
        entries = ['tests/compiler_suite_contract_tests.ouro', 'tests/compiler_property_tests.ouro']
        self.listed = RunResult('ok', 0, '\n'.join(entries) + '\n', '', 0.1, 10)
        self.execute = self.enterContext(patch('ourosmith.limits.run_limited', return_value=self.listed))
        self.log = self.root / 'gate.log'
        self.log_text = ('COMPILER_CHECK_OK compiler_suite_contract-run\n'
                         'COMPILER_CHECK_OK compiler_property-run\n'
                         'COMPILER_CHECK_SUITE: PASS rows=2 out=' + self.directory.as_posix() + '\n')
        self.log.write_text(self.log_text, encoding='utf-8')
        for name in ('compiler_suite_contract', 'compiler_property'):
            (self.directory / (name + '.check')).write_text('CHECK_OK\n', encoding='utf-8')
            (self.directory / (name + '.err')).write_bytes(b'')
            (self.directory / (name + '.out')).write_text(
                property_output() if name == 'compiler_property' else 'ok inventory contract\n', encoding='utf-8')

    def read(self):
        return evidence.suite_receipt(self.log, self.root / 'compiler')

    def test_complete_protocol_binds_every_executed_entry(self):
        receipt = self.read()
        self.assertEqual([row['entry'] for row in receipt['artifacts']], self.listed.stdout.splitlines())
        self.assertTrue(receipt['artifacts'][1]['default_properties'])
        self.assertEqual(receipt['log_sha256'], evidence.sha(self.log))
        self.assertEqual(self.receipt.call_count, 4)
        self.assertEqual(self.execute.call_args.args[0][-2:], ['--native-suite=compiler-checking', '--list'])

    def test_partial_reordered_duplicate_unknown_and_failed_logs_reject(self):
        lines = self.log_text.splitlines()
        candidates = [[], lines[:-1], [*lines, 'extra'], [lines[1], lines[0], lines[2]],
                      [lines[0], lines[0], lines[2]], [lines[0], lines[2].replace('rows=2', 'rows=1')],
                      [lines[0], lines[1].replace('_OK', '_FAIL'), lines[2]],
                      [lines[0], lines[1].replace('compiler_property-run', 'unknown-run'), lines[2]]]
        for candidate in candidates:
            self.log.write_text('\n'.join(candidate) + '\n', encoding='utf-8')
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                self.read()

    def test_artifact_paths_cannot_escape_build_root(self):
        self.log.write_text(self.log_text.replace(self.directory.as_posix(), '../outside'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'escape'):
            self.read()

    def test_current_inventory_must_execute_and_be_complete(self):
        for field, value in [('status', 'timeout'), ('returncode', 1), ('stderr', 'failure'),
                             ('stdout', ''), ('stdout', self.listed.stdout * 2),
                             ('stdout', '../outside.ouro\n'),
                             ('stdout', 'tests/compiler_suite_contract_tests.ouro\n')]:
            result = deepcopy(self.listed)
            setattr(result, field, value)
            self.execute.return_value = result
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.read()

    def test_stale_receipts_and_runner_replacement_reject(self):
        self.receipt.side_effect = ValueError('stale receipt')
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.read()
        good = (self.native_receipt, [], {})
        self.receipt.side_effect = [good, good, good, ({**self.native_receipt, 'key': 'changed'}, [], {})]
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.read()

    def test_missing_strict_check_runtime_failure_and_missing_output_reject(self):
        for suffix, bad in [('.check', ''), ('.check', 'CHECK_PROCESS_FAIL exit=1\nCHECK_OK\n'),
                            ('.check', 'CHECK_OK\nextra\n'), ('.err', 'diagnostic'),
                            ('.out', ''), ('.out', 'FAIL property\n')]:
            path = self.directory / ('compiler_property' + suffix)
            original = path.read_bytes()
            path.write_text(bad, encoding='utf-8')
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                self.read()
            path.write_bytes(original)

    def test_default_property_protocol_requires_both_domains_and_mutations(self):
        original = property_output()
        self.assertTrue(evidence.property_protocol(original))
        bad = [original.replace('count=400', 'count=40'), original.replace('nonfirst=40', 'nonfirst=0'),
               original.replace('count=109', 'count=401'), original.replace('mutations=28', 'mutations=0'),
               original.replace('seed=2026', 'seed=2027'), original.replace('16,16', '0,32', 1),
               original.replace('16,16', '15,16', 1), original.replace('16,16', '016,16', 1),
               original.replace('16,16', '16,,16', 1), original + 'extra\n', '\n'.join(original.splitlines()[1:])]
        for text in bad:
            self.assertFalse(evidence.property_protocol(text))
            (self.directory / 'compiler_property.out').write_text(text, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'property protocol'):
                self.read()

    def test_ci_credit_requires_its_exact_required_command_and_log(self):
        from ci_gate import REPORT_KIND, gates

        required = [gate for gate in gates() if gate.name.startswith('compiler-checking-')]
        out = self.root / 'validation'
        summary_path = out / 'ci/ci-summary.json'
        summary_path.parent.mkdir(parents=True)
        rows = [{'name': gate.name, 'blocking': True, 'status': 'pass', 'returncode': 0,
                 'command': gate.cmd, 'log': str(out / 'ci' / gate.name / 'gate.log')} for gate in required]
        summary = {'kind': REPORT_KIND, 'profile': 'pr', 'group': 'all', 'gates': rows}
        inventory = ['tests/compiler_suite_contract_tests.ouro', 'tests/compiler_property_tests.ouro',
                     'tests/compiler_abi_tests.ouro', 'tests/compiler_check_tests.ouro',
                     'tests/compiler_driver_tests.ouro', 'tests/compiler_fault_tests.ouro',
                     'tests/compiler_module_tests.ouro', 'tests/compiler_positive_tests.ouro',
                     'tests/compiler_plan_tests.ouro', 'tests/compiler_refine_tests.ouro',
                     'tests/compiler_result_tests.ouro', 'tests/compiler_structural_tests.ouro']
        receipts = {f'{index}/12': {'inventory': inventory.copy(), 'runner_build_key': 'current',
                                  'runner_sha256': 'current', 'artifacts': [{'entry': entry}]}
                    for index, entry in enumerate(inventory, 1)}
        with patch('ourosmith.host.binary', return_value=self.root / 'compiler'), \
             patch.object(evidence, 'suite_receipt', side_effect=lambda _log, _compiler, shard: receipts[shard]) as observed:
            summary_path.write_text(json.dumps(summary), encoding='utf-8')
            self.assertEqual([row['entry'] for row in evidence.ci_compiler_receipt(out)['artifacts']], inventory)
            self.assertEqual([call.kwargs['shard'] for call in observed.call_args_list], [f'{index}/12' for index in range(1, 13)])
            for index in range(12):
                for key, value in [('blocking', False), ('status', 'skip'), ('returncode', True),
                                   ('returncode', 1), ('command', ['unrelated']), ('log', 'elsewhere'), ('log', None)]:
                    changed = deepcopy(summary)
                    changed['gates'][index][key] = value
                    summary_path.write_text(json.dumps(changed), encoding='utf-8')
                    with self.subTest(shard=index, key=key), self.assertRaises(ValueError):
                        evidence.ci_compiler_receipt(out)
            for changed_rows in ([], rows[:-1], [*rows, rows[0]], [None]):
                summary_path.write_text(json.dumps({**summary, 'gates': changed_rows}), encoding='utf-8')
                with self.assertRaises(ValueError):
                    evidence.ci_compiler_receipt(out)
            summary_path.write_text(json.dumps(summary), encoding='utf-8')
            for key, value in [('inventory', inventory[:-1]), ('runner_build_key', 'stale'),
                               ('runner_sha256', 'stale'), ('artifacts', []),
                               ('artifacts', [{'entry': inventory[0]}])]:
                original = receipts['12/12'][key]
                receipts['12/12'][key] = value
                with self.assertRaises(ValueError):
                    evidence.ci_compiler_receipt(out)
                receipts['12/12'][key] = original

    def test_shard_receipt_requires_exact_selection_from_full_current_inventory(self):
        selected = RunResult('ok', 0, 'tests/compiler_property_tests.ouro\n', '', 0.1, 10)
        self.log.write_text('COMPILER_CHECK_OK compiler_property-run\n'
                            'COMPILER_CHECK_SUITE: PASS rows=1 out=' + self.directory.as_posix() + '\n', encoding='utf-8')
        self.execute.side_effect = [self.listed, selected]
        receipt = evidence.suite_receipt(self.log, self.root / 'compiler', shard='2/12')
        self.assertEqual(receipt['inventory'], self.listed.stdout.splitlines())
        self.assertEqual([row['entry'] for row in receipt['artifacts']], selected.stdout.splitlines())
        self.assertEqual(self.execute.call_args.args[0][-1], '--shard=2/12')
        for field, value in [('status', 'timeout'), ('returncode', 1), ('stderr', 'failure'),
                             ('stdout', ''), ('stdout', self.listed.stdout), ('stdout', selected.stdout * 2)]:
            changed = deepcopy(selected)
            setattr(changed, field, value)
            self.execute.side_effect = [self.listed, changed]
            with self.subTest(field=field), self.assertRaises(ValueError):
                evidence.suite_receipt(self.log, self.root / 'compiler', shard='2/12')

    def test_tenth_shard_uses_the_complete_multidigit_index(self):
        inventory = [f'tests/compiler_fixture_{index}_tests.ouro' for index in range(9)]
        inventory[0] = 'tests/compiler_suite_contract_tests.ouro'
        inventory += ['tests/compiler_property_tests.ouro']
        inventory += [f'tests/compiler_fixture_{index}_tests.ouro' for index in range(10, 12)]
        listed = RunResult('ok', 0, '\n'.join(inventory) + '\n', '', 0.1, 10)
        selected = RunResult('ok', 0, 'tests/compiler_property_tests.ouro\n', '', 0.1, 10)
        self.log.write_text('COMPILER_CHECK_OK compiler_property-run\n'
                            'COMPILER_CHECK_SUITE: PASS rows=1 out=' + self.directory.as_posix() + '\n', encoding='utf-8')
        self.execute.side_effect = [listed, selected]
        receipt = evidence.suite_receipt(self.log, self.root / 'compiler', shard='10/12')
        self.assertEqual([row['entry'] for row in receipt['artifacts']], selected.stdout.splitlines())
        self.assertEqual(self.execute.call_args.args[0][-1], '--shard=10/12')


class ExternalEvidenceTests(EvidenceTreeTests):
    def setUp(self):
        from ci_gate import REPORT_KIND, gates
        from ourosmith import migration
        from ourosmith.validation import KIND

        self.migration = migration
        self.parent = evidence.ROOT / '_build/compiler-evidence-selftest'
        self.root = self.parent / uuid.uuid4().hex
        self.out = self.root / 'validation'
        self.out.mkdir(parents=True)
        self.enterContext(patch.object(migration, 'ROOT', self.root))
        self.enterContext(patch('ourosmith.provenance.source_state', return_value={'source': 'current'}))
        self.commands = [('ci', ['ci', '--required']), ('dune', ['dune', '--historical'])]
        self.enterContext(patch('ourosmith.validation.commands', return_value=self.commands))
        self.gates = [gate for gate in gates() if gate.name.startswith('compiler-checking-') or gate.name == 'compiler-boundary']
        self.enterContext(patch.object(migration, 'gates', return_value=self.gates))
        self.owners = {'external/compiler/' + name for name in migration.contracts.CURRENT_COMPILER_OWNERS}
        self.compiler = self.enterContext(patch.object(evidence, 'compiler_strategies', return_value=self.owners))
        self.journal = {'kind': KIND, 'complete': True, 'unchanged': True,
                        'provenance': {'source': {'source': 'current'}},
                        'commands': [{'name': name, 'command': command, 'status': 'PASS', 'exit_code': 0}
                                     for name, command in self.commands]}
        rows = []
        for gate in self.gates:
            log = self.out / 'ci' / gate.name / 'gate.log'
            log.parent.mkdir(parents=True)
            log.write_text('actual required command output\n', encoding='utf-8')
            rows.append({'name': gate.name, 'command': gate.cmd, 'blocking': True,
                         'status': 'pass', 'returncode': 0, 'log': str(log)})
        self.summary = {'kind': REPORT_KIND, 'profile': 'pr', 'group': 'all', 'gates': rows}
        for name, _ in self.commands:
            (self.out / (name + '.log')).write_text(
                'SMITH_KERNEL_LAW PASS scale: let-chain\n'
                'SMITH_KERNEL_PROPERTY: PASS seed=2026 scoped=400 typed=400\n', encoding='utf-8')
        self.write()

    def write(self):
        (self.out / 'commands.json').write_text(json.dumps(self.journal), encoding='utf-8')
        (self.out / 'ci/ci-summary.json').write_text(json.dumps(self.summary), encoding='utf-8')

    def read(self):
        return self.migration.external_evidence(self.out)

    def test_current_complete_owners_and_removal_are_separate_claims(self):
        result = self.read()
        self.assertTrue(self.owners <= result)
        self.assertIn(self.migration.contracts.RETIRED_CORE, result)
        self.compiler.assert_called_once_with(self.out.resolve())
        self.assertNotIn('external/law/scale: let-chain', result)
        self.assertNotIn('external/dune/scoped-and-typed-laws', result)
        path = self.root / self.migration.contracts.LEGACY_CORE_OWNER_PATHS[0]
        path.parent.mkdir(parents=True)
        path.write_text('legacy owner remains', encoding='utf-8')
        self.assertNotIn(self.migration.contracts.RETIRED_CORE, self.read())
        path.unlink()
        self.compiler.return_value = self.owners - {sorted(self.owners)[0]}
        self.assertNotIn(self.migration.contracts.RETIRED_CORE, self.read())

    def test_missing_stale_duplicate_or_malformed_journal_has_no_credit(self):
        original = deepcopy(self.journal)
        bad = [None, [], [None], self.journal['commands'] * 2,
               [{'name': ['ci'], 'status': 'PASS', 'exit_code': 0}]]
        changes = [('kind', 'foreign'), ('complete', False), ('unchanged', False),
                   ('provenance', {'source': {'source': 'old'}}), *[('commands', rows) for rows in bad]]
        for key, value in changes:
            self.journal = {**deepcopy(original), key: value}
            self.write()
            with self.subTest(key=key, value=value):
                self.assertEqual(self.read(), set())
        self.assertEqual(self.migration.external_evidence(None), set())

    def test_required_ci_command_exit_and_log_are_checked(self):
        original = deepcopy(self.journal)
        for key, value in [('command', ['wrong']), ('status', 'SKIP'), ('exit_code', True), ('exit_code', 1)]:
            self.journal = deepcopy(original)
            self.journal['commands'][0][key] = value
            self.write()
            with self.subTest(key=key):
                self.assertFalse(self.owners & self.read())
        self.journal = original
        self.write()
        (self.out / 'ci.log').unlink()
        self.assertFalse(self.owners & self.read())

    def test_each_required_gate_must_match_its_command_and_execution(self):
        original = deepcopy(self.summary)
        for index, gate in enumerate(self.gates):
            for key, value in [('command', ['wrong']), ('blocking', False), ('status', 'skip'),
                               ('returncode', True), ('returncode', 1), ('log', 'elsewhere')]:
                self.summary = deepcopy(original)
                self.summary['gates'][index][key] = value
                self.write()
                with self.subTest(gate=gate.name, key=key):
                    result = self.read()
                    self.assertNotIn('external/ci/' + gate.name, result)
                    self.assertNotIn(self.migration.contracts.RETIRED_CORE, result)
            self.summary = deepcopy(original)
            self.summary['gates'].append(deepcopy(self.summary['gates'][index]))
            self.write()
            self.assertNotIn('external/ci/' + gate.name, self.read())
        self.summary = original
        self.write()
        (self.out / 'ci/compiler-checking-1/gate.log').unlink()
        self.assertFalse(self.owners & self.read())

    def test_stale_compiler_receipt_cannot_supply_credits(self):
        self.compiler.side_effect = ValueError('compiler receipt is stale')
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.read()

    def add_resource_command(self, profile):
        command = ['kernel_scale.py', '--profile', profile, '--out', str(self.out / profile)]
        self.commands.append((profile, command))
        self.journal['commands'].append({'name': profile, 'command': command, 'status': 'PASS', 'exit_code': 0})
        (self.out / (profile + '.log')).write_text('supervisor completed\n', encoding='utf-8')
        self.write()

    def test_resource_laws_require_the_full_source_bound_report(self):
        operations = ('let-chain', 'lam-chain', 'app-spine', 'nested-app', 'domain-deep-pi', 'const-chain')
        for profile in ('scale', 'depth'):
            self.add_resource_command(profile)
        accepted = {
            'scale': {'pass': True, 'credits': ['external/law/scale:' + op for op in operations], 'failures': []},
            'depth': {'pass': True, 'credits': ['external/law/depth'], 'failures': []},
        }
        expected = {'external/law/scale: ' + op for op in operations}
        expected.add('external/law/depth: fail-closed on million-node terms')
        with patch('kernel_scale.report_evidence', side_effect=lambda _path, profile: accepted[profile]) as observed:
            self.assertTrue(expected <= self.read())
            self.assertEqual([call.args for call in observed.call_args_list],
                             [(self.out.resolve() / profile / 'report.json', profile) for profile in ('scale', 'depth')])
            for profile in ('scale', 'depth'):
                good = accepted[profile]
                bad = [None, {}, {'pass': True}, {**good, 'pass': 1}, {**good, 'pass': False},
                       {**good, 'credits': []}, {**good, 'credits': good['credits'] + ['foreign']},
                       {**good, 'credits': ' '.join(good['credits'])}, {**good, 'failures': ['stale source']},
                       {**good, 'failures': None}]
                if profile == 'scale':
                    bad.extend([{**good, 'credits': good['credits'][:-1]},
                                {**good, 'credits': list(reversed(good['credits']))}])
                for changed in bad:
                    accepted[profile] = changed
                    with self.subTest(profile=profile, changed=changed):
                        law_credits = {value for value in self.read() if value.startswith('external/law/' + profile)}
                        self.assertEqual(law_credits, set())
                accepted[profile] = good

    def test_resource_report_is_not_read_without_the_required_successful_command(self):
        self.add_resource_command('scale')
        original = deepcopy(self.journal)
        with patch('kernel_scale.report_evidence') as observed:
            for key, value in [('command', ['unrelated']), ('status', 'SKIP'), ('exit_code', True), ('exit_code', 1)]:
                self.journal = deepcopy(original)
                self.journal['commands'][-1][key] = value
                self.write()
                with self.subTest(key=key):
                    self.assertFalse(any(value.startswith('external/law/scale') for value in self.read()))
            self.journal = original
            self.write()
            (self.out / 'scale.log').unlink()
            self.read()
            observed.assert_not_called()

    def test_missing_malformed_or_unbound_resource_report_cannot_supply_laws(self):
        for profile in ('scale', 'depth'):
            self.add_resource_command(profile)
            output = self.out / profile / 'report.json'
            output.parent.mkdir()
            for value in (None, 'not json', '[]', '{"pass": true}'):
                if value is not None:
                    output.write_text(value, encoding='utf-8')
                with self.subTest(profile=profile, value=value):
                    self.assertFalse(any(credit.startswith('external/law/') for credit in self.read()))


if __name__ == '__main__':
    unittest.main(verbosity=2)
