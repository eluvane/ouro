#!/usr/bin/env python3
"""Fail-closed host protocol/receipt tests; these fixtures do not run a checker."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import kernel_scale as scale


class KernelScaleTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='ouro-kernel-scale-')
        self.addCleanup(temporary.cleanup)
        # Match production path resolution, including macOS /var -> /private/var.
        self.root = Path(temporary.name).resolve()
        self.addCleanup(patch.stopall)
        patch.object(scale, 'ROOT', self.root).start()
        patch.object(scale.frontend_regen, 'collect_units', side_effect=lambda entry: [entry]).start()
        names = {*scale.native_tool_build.BUILD_INPUTS, *scale.native_tool_build.RUNTIME,
                 *scale.ORCHESTRATION, *scale.ENTRIES.values(), 'runtime/ouro_rt.h',
                 'compiler/file_check_environment.ouro', 'compiler/file_check_work.ouro',
                 'std/data.ouro'}
        for name in names:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture ' + name + '\n', encoding='utf-8')
        self.compiler = self.root / '_build/tools/compiler.exe'
        self.compiler.parent.mkdir(parents=True)
        self.compiler.write_bytes(b'physical compiler fixture')

    def process(self, command, stdout='', timeout=30):
        return {'status': 'ok', 'returncode': 0, 'stdout': stdout, 'stderr': '',
                'elapsed_s': 0.25, 'peak_memory_mib': 16.0 if os.name == 'nt' else None,
                'memory_metric': 'windows-job-peak-commit' if os.name == 'nt' else 'unavailable-posix',
                'memory_limit_mib': scale.MEMORY_MIB, 'timeout_s': timeout,
                'command': command, 'argv': command}

    def operation(self, profile, name, depth, command, outcome='success'):
        factor, offset = scale.WORK[profile][name]
        required = factor * depth + offset
        prefix = 'KERNEL_' + profile.upper()
        stdout = (f'{prefix}_START operation={name} depth={depth}\n'
                  f'{prefix}_INPUT limit={scale.WORK_LIMIT} visited={min(scale.WORK_LIMIT, required)} '
                  f'exhausted={str(required > scale.WORK_LIMIT).lower()}\n'
                  f'{prefix}_RESULT operation={name} outcome={outcome} code={4 if outcome == "resource" else 0}\n')
        return self.process(command, stdout, scale.RUN_TIMEOUT[profile])

    def fixture(self, profile):
        entry = scale.ENTRIES[profile]
        directory = self.root / '_build' / ('proof-' + profile)
        directory.mkdir(exist_ok=True)
        executable = directory / 'probe.exe'
        executable.write_bytes(b'physical probe fixture')
        sources = scale.expected_sources(entry)
        inputs = {'kind': scale.native_tool_build.KIND, 'entry': entry, 'sources': sources,
                  'compiler_sha256': scale.sha256_path(self.compiler), 'fuel': 16000,
                  'cflags': ['-O0', '-std=c99', '-D_POSIX_C_SOURCE=200809L',
                             '-fdebug-prefix-map=.=/ouro', '-fmacro-prefix-map=.=/ouro']}
        receipt = {'kind': scale.native_tool_build.KIND, 'inputs': inputs, 'cache': 'miss',
                   'key': scale.hash_json(inputs), 'binary_sha256': scale.sha256_path(executable)}
        receipt_path = Path(str(executable) + '.build.json')
        receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
        state = scale.input_state(entry, self.compiler)
        command = [str(self.compiler), 'check', entry, '999999', '--unit', entry]
        build_command = scale.build_command(self.compiler, entry, executable, directory)
        report = {'kind': scale.REPORT_KIND, 'profile': profile, 'timing_domain': scale.TIMING_DOMAIN,
                  'entry': entry, 'compiler': scale.relative(self.compiler), 'run_directory': scale.relative(directory),
                  'workers': 1, 'memory_limit_mib': scale.MEMORY_MIB, 'work_limit': scale.WORK_LIMIT,
                  'scale_budget_s': scale.SCALE_BUDGET, 'cpu_affinity': [0],
                  'producer_sha256': scale.sha256_path(self.compiler), 'sources': sources,
                  'inputs_before': state, 'inputs_after': state, 'inputs_unchanged': True,
                  'check': self.process(command, 'CHECK_OK\n', scale.CHECK_TIMEOUT),
                  'build': {'executable': scale.relative(executable), 'receipt': receipt,
                            'receipt_sha256': scale.sha256_path(receipt_path),
                            'process': self.process(build_command, 'BUILD_TOOL: OK fixture\n', scale.BUILD_TIMEOUT)},
                  'rows': [], 'constant_inventory': None, 'pass': True}
        for name, depth in scale.expected_cases(profile):
            command = [str(executable), '--operation', name, '--depth', str(depth)]
            report['rows'].append({'operation': name, 'depth': depth,
                                  'process': self.operation(profile, name, depth, command,
                                      'resource' if depth == 1_000_000 else 'success'),
                                  'inputs_unchanged': True, 'receipt_valid': True})
        if profile == 'scale':
            lines = ['KERNEL_SCALE_INVENTORY_START count=20000']
            lines += [f'KERNEL_SCALE_ITEM name={name} predecessor={"zero" if name == 100 else name - 1}'
                      for name in range(100, 20_100)]
            lines += ['KERNEL_SCALE_INVENTORY_COMPLETE']
            report['constant_inventory'] = self.process(
                [str(executable), '--operation', 'inventory', '--depth', '20000'],
                '\n'.join(lines) + '\n', scale.INVENTORY_TIMEOUT)
        return report

    def evidence(self, report, profile):
        path = self.root / 'report.json'
        path.write_text(json.dumps(report), encoding='utf-8')
        return scale.report_evidence(path, profile)

    def test_complete_profiles_have_exact_owner_credits(self):
        for profile, count in (('scale', 6), ('depth', 1)):
            with self.subTest(profile=profile):
                report = self.fixture(profile)
                result = scale.evaluate(report, profile)
                self.assertTrue(result['pass'], result)
                evidence = self.evidence(report, profile)
                self.assertTrue(evidence['pass'], evidence)
                self.assertEqual(len(evidence['credits']), count)

    def test_every_missing_operation_withholds_all_credits(self):
        for profile in scale.ENTRIES:
            original = self.fixture(profile)
            for index in range(len(original['rows'])):
                report = copy.deepcopy(original)
                del report['rows'][index]
                with self.subTest(profile=profile, index=index):
                    self.assertFalse(scale.evaluate(report, profile)['pass'])
                    self.assertEqual(self.evidence(report, profile)['credits'], [])

    def test_duplicate_reordered_and_unknown_operations_fail(self):
        original = self.fixture('depth')
        for kind in ('duplicate', 'reorder', 'unknown', 'relabeled-depth', 'extra'):
            report = copy.deepcopy(original)
            if kind == 'duplicate':
                report['rows'][1] = report['rows'][0]
            elif kind == 'reorder':
                report['rows'].reverse()
            elif kind == 'unknown':
                report['rows'][0]['operation'] = 'other'
            elif kind == 'relabeled-depth':
                report['rows'][0]['process']['command'][-1] = '257'
            else:
                report['rows'].append(copy.deepcopy(report['rows'][0]))
            with self.subTest(kind=kind):
                self.assertFalse(scale.evaluate(report, 'depth')['pass'])

    def test_only_exact_resource_is_allowed_at_a_million(self):
        original = self.fixture('depth')
        row = original['rows'][len(scale.DEPTH)]
        name, depth = row['operation'], row['depth']
        for outcome in ('resource', 'success'):
            process = self.operation('depth', name, depth, row['process']['command'], outcome)
            self.assertTrue(scale.operation_protocol('depth', name, depth, process))
        for replacement in ('outcome=failure code=4', 'outcome=resource code=1', 'outcome=CheckResourceLimit code=4'):
            process = copy.deepcopy(row['process'])
            process['stdout'] = process['stdout'].replace('outcome=resource code=4', replacement)
            self.assertFalse(scale.operation_protocol('depth', name, depth, process))

    def test_shallow_and_scale_resource_are_failures(self):
        for profile, name, depth in (('depth', 'check-lam', 10_000), ('scale', 'let-chain', 20_000)):
            process = self.operation(profile, name, depth, ['probe'], 'resource')
            self.assertFalse(scale.operation_protocol(profile, name, depth, process))

    def test_process_failures_and_dirty_stdout_are_never_resources(self):
        original = self.fixture('depth')['rows'][-1]['process']
        changes = [('status', 'timeout'), ('status', 'memory'), ('status', 'spawn-error'),
                   ('returncode', -1), ('returncode', 0xFFFFFFFF), ('returncode', 139),
                   ('stderr', 'failure\n'), ('elapsed_s', float('nan')), ('elapsed_s', float('inf')),
                   ('memory_limit_mib', 4096), ('timeout_s', 31), ('argv', ['other'])]
        for key, value in changes:
            process = copy.deepcopy(original)
            process[key] = value
            with self.subTest(key=key, value=value):
                self.assertFalse(scale.operation_protocol('depth', 'recheck-axiom-domain', 1_000_000, process))
        for stdout in (original['stdout'] + 'extra\n', original['stdout'] + original['stdout'],
                       original['stdout'].splitlines()[0] + '\n', ''):
            process = copy.deepcopy(original)
            process['stdout'] = stdout
            self.assertFalse(scale.operation_protocol('depth', 'recheck-axiom-domain', 1_000_000, process))

    def test_exact_work_and_original_scale_budget_are_required(self):
        original = self.fixture('scale')['rows'][0]['process']
        for key, value in [('elapsed_s', 10.01), ('stdout', original['stdout'].replace('limit=500000', 'limit=257')),
                           ('stdout', original['stdout'].replace('visited=60003', 'visited=3')),
                           ('stdout', original['stdout'].replace('exhausted=false', 'exhausted=true'))]:
            process = copy.deepcopy(original)
            process[key] = value
            self.assertFalse(scale.operation_protocol('scale', 'let-chain', 20_000, process))

    def test_constant_inventory_requires_every_id_and_predecessor(self):
        original = self.fixture('scale')['constant_inventory']
        for mutate in (lambda lines: lines[:100] + lines[101:],
                       lambda lines: lines[:100] + [lines[99]] + lines[101:],
                       lambda lines: [line.replace('name=20099', 'name=20100') for line in lines],
                       lambda lines: [line.replace('name=20099 predecessor=20098', 'name=20099 predecessor=20097') for line in lines],
                       lambda lines: lines[:-1], lambda lines: lines + ['extra']):
            result = copy.deepcopy(original)
            result['stdout'] = '\n'.join(mutate(result['stdout'].splitlines())) + '\n'
            self.assertFalse(scale.inventory_protocol(result))

    def test_report_claims_and_limits_do_not_override_evidence(self):
        original = self.fixture('scale')
        for key, value in (('pass', False), ('workers', True), ('workers', 2), ('work_limit', 257),
                           ('cpu_affinity', [0, 1]), ('kind', 'legacy'), ('profile', 'depth'),
                           ('inputs_unchanged', False), ('error', 'late failure')):
            report = copy.deepcopy(original)
            report[key] = value
            self.assertFalse(self.evidence(report, 'scale')['pass'])

    def test_stale_current_source_or_missing_source_is_rejected(self):
        report = self.fixture('scale')
        for name in ('compiler/file_check_environment.ouro', 'compiler/file_check_work.ouro',
                     scale.ENTRIES['scale'], 'runtime/ouro_rt.h', 'scripts/kernel_scale.py'):
            path = self.root / name
            previous = path.read_bytes()
            path.write_bytes(previous + b'changed')
            self.assertFalse(self.evidence(report, 'scale')['pass'])
            path.write_bytes(previous)
        (self.root / 'compiler/new_checker.ouro').write_text('new', encoding='utf-8')
        self.assertFalse(self.evidence(report, 'scale')['pass'])

    def test_actual_binary_and_receipt_are_required(self):
        report = self.fixture('scale')
        executable = scale.resolve(report['build']['executable'])
        previous = executable.read_bytes()
        executable.write_bytes(previous + b'changed')
        self.assertFalse(self.evidence(report, 'scale')['pass'])
        executable.write_bytes(previous)
        receipt_path = Path(str(executable) + '.build.json')
        receipt_path.unlink()
        self.assertFalse(self.evidence(report, 'scale')['pass'])

    def test_rewritten_receipt_still_needs_exact_build_inputs(self):
        for field, value in (('compiler_sha256', '0' * 64), ('entry', scale.ENTRIES['depth']),
                             ('fuel', 1), ('cflags', ['-O1'])):
            report = self.fixture('scale')
            receipt = report['build']['receipt']
            receipt['inputs'][field] = value
            receipt['key'] = scale.hash_json(receipt['inputs'])
            path = Path(str(scale.resolve(report['build']['executable'])) + '.build.json')
            path.write_text(json.dumps(receipt), encoding='utf-8')
            report['build']['receipt_sha256'] = scale.sha256_path(path)
            self.assertFalse(self.evidence(report, 'scale')['pass'])

    def test_missing_producer_runs_no_child(self):
        self.compiler.unlink()
        with patch.object(scale, 'execute') as execute, patch.object(scale, 'pin_one_cpu', return_value=[0]):
            result = scale.run('scale', self.compiler, self.root / '_build/missing-producer')
        self.assertFalse(result['pass'])
        execute.assert_not_called()
        self.assertFalse(result['inputs_unchanged'])

    def test_cli_uses_configured_compiler_and_preserves_explicit_override(self):
        (self.root / 'Ouro.seal').write_text(
            'seal 1\nbuild {\n  c_out = "_build/from-project"\n}\n', encoding='utf-8')
        output = self.root / '_build/cli-output'
        for origin in ('project', 'environment'):
            directory = self.root / '_build' / ('from-' + origin)
            directory.mkdir()
            compiler = directory / ('ouro1.exe' if os.name == 'nt' else 'ouro1')
            compiler.write_bytes(b'configured compiler fixture')
            with self.subTest(origin=origin), patch.object(scale.ouro_build, 'ROOT', self.root), \
                    patch.dict(os.environ, {'OURO_C_BUILD_DIR': str(directory) if origin == 'environment' else ''}), \
                    patch.object(scale, 'run', return_value={'pass': True}) as run, patch('builtins.print'):
                self.assertEqual(scale.main(['--profile', 'scale', '--out', str(output)]), 0)
                run.assert_called_once_with('scale', compiler, output)
        with patch.object(scale.ouro_build, 'load_config', side_effect=AssertionError('explicit compiler must win')), \
                patch.object(scale, 'run', return_value={'pass': True}) as run, patch('builtins.print'):
            self.assertEqual(scale.main(['--profile', 'depth', '--out', str(output), '--compiler', str(self.compiler)]), 0)
            run.assert_called_once_with('depth', self.compiler, output)

    def test_dirty_source_after_check_stops_before_build(self):
        calls = []

        def execute(command, _directory, _label, _env, timeout):
            calls.append(command)
            (self.root / 'compiler/file_check_work.ouro').write_text('dirty source', encoding='utf-8')
            return self.process(command, 'CHECK_OK\n', timeout)

        with patch.object(scale, 'execute', side_effect=execute), patch.object(scale, 'pin_one_cpu', return_value=[0]), \
                patch.object(scale, 'environment', return_value={}):
            result = scale.run('scale', self.compiler, self.root / '_build/dirty-source')
        self.assertFalse(result['pass'])
        self.assertEqual(len(calls), 1)
        self.assertFalse(result['inputs_unchanged'])

    def test_successful_wrapper_without_real_build_is_not_evidence(self):
        calls = []

        def execute(command, _directory, label, _env, timeout):
            calls.append(command)
            return self.process(command, 'CHECK_OK\n' if label == 'check' else 'BUILD_TOOL: OK\n', timeout)

        with patch.object(scale, 'execute', side_effect=execute), patch.object(scale, 'pin_one_cpu', return_value=[0]), \
                patch.object(scale, 'environment', return_value={}):
            result = scale.run('depth', self.compiler, self.root / '_build/missing-build')
        self.assertFalse(result['pass'])
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['rows'], [])


if __name__ == '__main__':
    unittest.main()
