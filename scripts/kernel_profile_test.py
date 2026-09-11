#!/usr/bin/env python3
"""Negative report and resource-policy tests for canonical compiler profiling."""
from copy import deepcopy
import json
import shutil
import unittest
import uuid

import kernel_profile as profile
from repo_support import hash_json


def process(stdout=''):
    return {'status': 'ok', 'returncode': 0, 'stdout': stdout, 'stderr': '',
            'elapsed_s': 0.3, 'peak_memory_mib': 30.0}


def retained():
    return process('\n'.join(['PASS ' + name for name in profile.LAW_NAMES] + ['COMPILER_RETAINED: PASS']) + '\n')


def boundary():
    path = '/fixture/repo-gate.json'
    report = {'kind': 'ouro.repo-gate-report.v1', 'version': '1', 'profile': 'compiler-boundary',
              'execution_backend': 'ouro-native-repo-gate', 'execution_mode': 'native',
              'pass': True, 'issues': [],
              'gates': [{'name': name, 'status': 'pass', 'blocking': True, 'issues': [], 'metrics': []}
                        for name in profile.BOUNDARY_CHECKS]}
    output = '\n'.join([f'REPO_GATE_SUMMARY profile=compiler-boundary pass=true issues=0 report={path}',
                        *(f'REPO_GATE_CHECK {name} status=pass issues=0' for name in profile.BOUNDARY_CHECKS)]) + '\n\n'
    return {'receipt_valid': True, 'report': report, 'run': process(output), 'report_path': path}


def variants():
    return [{'mode': mode, 'run': retained(), 'build': process('BUILD_TOOL_CACHE: ' + ('hit' if mode == 'hit' else 'miss')),
             'receipt_valid': True, 'receipt': {'inputs': {'source': 'sha'},
                                               'binary_sha256': 'cached-binary' if mode != 'off' else 'uncached-binary'}}
            for mode in ('off', 'miss', 'hit')]


class KernelProfileTests(unittest.TestCase):
    def setUp(self):
        self.budgets = profile.load_json(profile.ROOT / 'quality/kernel_budgets.json')

    def evaluate(self, rows=None, gate=None, unchanged=True):
        return profile.evaluate(variants() if rows is None else rows,
                                boundary() if gate is None else gate, unchanged, self.budgets)

    def test_complete_observed_protocol_can_pass(self):
        self.assertTrue(self.evaluate()['pass'])

    def test_old_budgets_and_memo_domain_cannot_be_reused(self):
        for change in ({'kind': 'ouro.kernel-budgets.v1'}, {'timing_domain': 'python-json-replay'}):
            with self.assertRaises(ValueError):
                profile.validate_budgets({**self.budgets, **change})

    def test_invalid_budget_numbers_are_rejected(self):
        for value in (None, True, -1, 0, float('nan'), float('inf'), '500'):
            budgets = deepcopy(self.budgets)
            budgets['retained_execution']['max_elapsed_ms'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                profile.validate_budgets(budgets)

    def test_required_contracts_cannot_be_omitted(self):
        changes = [('retained_execution', 'min_fixtures', 16),
                   ('retained_execution', 'max_unexpected_fixtures', 1),
                   ('orchestration', 'workers', 2), ('orchestration', 'memory_limit_mib', False),
                   ('orchestration', 'run_timeout_s', float('inf')),
                   ('native_tool_cache', 'required_modes', ['miss', 'hit']),
                   ('compiler_boundary', 'required_checks', []), ('compiler_boundary', 'max_issues', 1)]
        for section, name, value in changes:
            budgets = deepcopy(self.budgets)
            budgets[section][name] = value
            with self.subTest(name=name), self.assertRaises(ValueError):
                profile.validate_budgets(budgets)

    def test_crashes_timeouts_exit_and_stderr_cannot_pass(self):
        changes = [{'status': status} for status in ('timeout', 'memory', 'crash', 'spawn-error')]
        changes += [{'returncode': value} for value in (None, True, '0', 1, 2, 139, -9)]
        changes += [{'stderr': None}, {'stderr': 'diagnostic'}, {'stdout': None}]
        for change in changes:
            with self.subTest(change=change):
                self.assertFalse(profile.retained_protocol({**retained(), **change}))

    def test_clock_and_memory_values_must_be_real_measurements(self):
        for field in ('elapsed_s', 'peak_memory_mib'):
            for value in (None, True, -1, float('nan'), float('inf'), '0.3'):
                with self.subTest(field=field, value=value):
                    self.assertFalse(profile.retained_protocol({**retained(), field: value}))

    def test_full_retained_inventory_and_terminal_are_required(self):
        lines = retained()['stdout'].splitlines()
        bad = [lines[1:], lines[:-1], lines + ['extra'],
               [lines[0], lines[0], *lines[2:]], [lines[1], lines[0], *lines[2:]],
               ['PASS arbitrary-law', *lines[1:]], [*lines[:-1], 'COMPILER_RETAINED: FAIL']]
        for rows in bad:
            self.assertFalse(profile.retained_protocol(process('\n'.join(rows) + '\n')))

    def test_wrong_typed_failure_cannot_be_a_success(self):
        output = retained()['stdout'].replace('PASS wrong_body_type', 'FAIL wrong_body_type: resource-limit; expected type-mismatch')
        self.assertFalse(profile.retained_protocol(process(output)))

    def test_500ms_is_an_execution_budget_and_not_rounded_down(self):
        for seconds, expected in ((0.5, True), (0.500001, False), (1.0, False)):
            rows = variants()
            rows[0]['run']['elapsed_s'] = seconds
            # An actual build may take seconds. It does not occupy the replay domain.
            rows[0]['build']['elapsed_s'] = 30.0
            self.assertEqual(self.evaluate(rows)['pass'], expected)

    def test_each_cache_mode_must_meet_the_resource_budget(self):
        for index in range(3):
            rows = variants()
            rows[index]['run']['elapsed_s'] = 0.501
            self.assertFalse(self.evaluate(rows)['pass'])
            rows = variants()
            rows[index]['run']['peak_memory_mib'] = 3073.0
            self.assertFalse(self.evaluate(rows)['pass'])

    def test_missing_duplicate_and_reordered_cache_modes_fail(self):
        rows = variants()
        for bad in ([], rows[1:], [rows[0], rows[0], rows[2]], list(reversed(rows))):
            self.assertFalse(self.evaluate(bad)['pass'])

    def test_build_failure_or_invalid_receipt_cannot_pass(self):
        for index in range(3):
            rows = variants()
            rows[index]['receipt_valid'] = False
            self.assertFalse(self.evaluate(rows)['pass'])
            rows = variants()
            rows[index]['build']['status'] = 'timeout'
            self.assertFalse(self.evaluate(rows)['pass'])

    def test_cache_hit_binds_its_binary_and_all_build_inputs(self):
        rows = variants()
        rows[2]['receipt']['binary_sha256'] = 'different-binary'
        self.assertFalse(self.evaluate(rows)['pass'])
        for index in range(3):
            rows = variants()
            rows[index]['receipt']['inputs'] = {'source': 'different-source'}
            self.assertFalse(self.evaluate(rows)['pass'])

    def test_changed_inputs_fail_even_with_complete_reports(self):
        self.assertFalse(self.evaluate(unchanged=False)['pass'])
        self.assertFalse(self.evaluate(unchanged=1)['pass'])

    def test_boundary_requires_current_kind_profile_backend_and_true_pass(self):
        for key, value in (('kind', 'ouro.kernel-trust-boundary.v1'), ('version', 1),
                           ('profile', 'repo'), ('pass', 1), ('pass', False),
                           ('execution_backend', 'python'), ('execution_mode', 'cached'),
                           ('issues', [{'reason': 'dependency escaped'}])):
            gate = boundary()
            gate['report'][key] = value
            with self.subTest(key=key):
                self.assertFalse(self.evaluate(gate=gate)['pass'])

    def test_all_three_boundary_checks_must_be_present_and_blocking(self):
        for index in range(3):
            for change in ({'blocking': False}, {'blocking': 1}, {'status': 'skip'},
                           {'issues': [{'reason': 'unreadable'}]}, {'name': 'unrelated'}, {'metrics': None}):
                gate = boundary()
                gate['report']['gates'][index].update(change)
                self.assertFalse(self.evaluate(gate=gate)['pass'])
        for indices in ([], [0, 1], [0, 1, 1], [2, 1, 0], [0, 1, 2, 2]):
            gate = boundary()
            gate['report']['gates'] = [gate['report']['gates'][index] for index in indices]
            self.assertFalse(self.evaluate(gate=gate)['pass'])

    def test_boundary_report_needs_its_actual_process_and_receipt(self):
        gate = boundary()
        gate['receipt_valid'] = False
        self.assertFalse(self.evaluate(gate=gate)['pass'])
        for change in ({'status': 'timeout'}, {'returncode': 1}, {'stderr': 'issue'},
                       {'stdout': ''}, {'stdout': boundary()['run']['stdout'] + 'extra\n'}):
            gate = boundary()
            gate['run'].update(change)
            self.assertFalse(self.evaluate(gate=gate)['pass'])

    def test_receipt_validates_exact_sources_entry_cache_key_producer_and_binary(self):
        parent = profile.ROOT / '_build/profile-selftest'
        parent.mkdir(parents=True, exist_ok=True)
        work = parent / uuid.uuid4().hex
        work.mkdir()
        try:
            executable = work / 'binary'
            executable.write_bytes(b'controlled test binary')
            sources = {'law.ouro': 'law-sha', 'runtime/ouro_rt.c': 'runtime-sha'}
            inputs = {'kind': 'ouro.native-tool-build.v1', 'sources': sources,
                      'entry': 'law.ouro', 'compiler_sha256': 'producer-sha'}
            receipt = {'kind': 'ouro.native-tool-build.v1', 'cache': 'miss', 'key': hash_json(inputs),
                       'inputs': inputs, 'binary_sha256': profile.sha(executable)}

            def check(value):
                return profile.receipt_valid(value, executable, sources, 'producer-sha', 'law.ouro', {'miss'})

            self.assertTrue(check(receipt))
            for key in ('kind', 'cache', 'key', 'binary_sha256'):
                self.assertFalse(check({**receipt, key: 'wrong'}))
            for key in ('kind', 'entry', 'compiler_sha256'):
                changed = deepcopy(receipt)
                changed['inputs'][key] = 'wrong'
                changed['key'] = hash_json(changed['inputs'])
                self.assertFalse(check(changed))
            for key in sources:
                changed = deepcopy(receipt)
                del changed['inputs']['sources'][key]
                changed['key'] = hash_json(changed['inputs'])
                self.assertFalse(check(changed))
            self.assertFalse(check({}))
        finally:
            self.assertTrue(work.resolve().is_relative_to(parent.resolve()))
            shutil.rmtree(work)

    def test_windows_wrapper_receipt_keeps_exact_validation_and_primary_precedence(self):
        parent = profile.ROOT / '_build/profile-selftest'
        parent.mkdir(parents=True, exist_ok=True)
        work = parent / uuid.uuid4().hex
        work.mkdir()
        try:
            executable = work / 'boundary.exe'
            executable.write_bytes(b'controlled boundary binary')
            logical = executable.with_suffix('.build.json')
            exact = work / 'boundary.exe.build.json'
            inputs = {'kind': 'ouro.native-tool-build.v1', 'sources': {'boundary.ouro': 'source-sha'},
                      'entry': 'boundary.ouro', 'compiler_sha256': 'producer-sha'}
            receipt = {'kind': 'ouro.native-tool-build.v1', 'cache': 'miss', 'key': hash_json(inputs),
                       'inputs': inputs, 'binary_sha256': profile.sha(executable)}
            logical.write_text(json.dumps(receipt), encoding='utf-8')
            selected = profile.boundary_receipt_path(executable)
            self.assertEqual(selected, logical)
            self.assertTrue(profile.receipt_valid(profile.load_json(selected), executable,
                inputs['sources'], 'producer-sha', 'boundary.ouro', {'miss'}))
            exact.write_text('{}', encoding='utf-8')
            self.assertEqual(profile.boundary_receipt_path(executable), exact)
            self.assertFalse(profile.receipt_valid(profile.load_json(exact), executable,
                inputs['sources'], 'producer-sha', 'boundary.ouro', {'miss'}))
            self.assertEqual(profile.boundary_receipt_path(work / 'boundary'), logical)
            with self.assertRaises(FileNotFoundError):
                profile.load_json(profile.boundary_receipt_path(work / 'missing.exe'))
        finally:
            self.assertTrue(work.resolve().is_relative_to(parent.resolve()))
            shutil.rmtree(work)

    def test_old_pass_baseline_is_not_a_current_measurement(self):
        current = {'context': {'producer_sha256': 'new'}, 'max_elapsed_ms': 300.0}
        old = {'kind': 'ouro.kernel-baseline.v1', 'pass': True,
               'native_kernel_recheck': {'fixtures': 17, 'elapsed_ms': 2.481}}
        self.assertFalse(profile.compare_baseline(old, current)['comparable'])
        self.assertFalse(profile.compare_baseline(None, current)['comparable'])

    def test_current_baseline_requires_same_context_and_finite_measurement(self):
        current = {'context': {'producer_sha256': 'producer'}, 'max_elapsed_ms': 300.0}
        baseline = {'kind': profile.BASELINE_KIND, 'timing_domain': profile.TIMING_DOMAIN,
                    'context': current['context'], 'max_elapsed_ms': 290.0}
        self.assertEqual(profile.compare_baseline(baseline, current), {'comparable': True, 'delta_ms': 10.0})
        self.assertFalse(profile.compare_baseline({**baseline, 'context': {}}, current)['comparable'])
        for value in (None, True, float('nan'), float('inf')):
            self.assertFalse(profile.compare_baseline({**baseline, 'max_elapsed_ms': value}, current)['comparable'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
