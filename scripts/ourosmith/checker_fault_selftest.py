"""Focused failure-boundary tests for canonical checker fault injection."""
from __future__ import annotations

import json
import shutil
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ourosmith import ROOT
from ourosmith.checker_faults import (
    LAW_ENTRY, LAW_EXPECTATIONS, build_receipt, classify_run, digest, fault_result, run_checker_campaign, run_variant,
)
from ourosmith.faults import FAULTS, OBSOLETE_CHECKER_CONTRACTS, FaultResult, StaleFault, apply_fault, fault_texts, run_faults


def law_report(failed=()):
    failed = set(failed)
    lines = [f"{'FAIL' if name in failed else 'PASS'} {name} got="
             + ('changed-value' if name in failed else expected)
             for name, expected in LAW_EXPECTATIONS.items()]
    lines.append('CHECKER_FAULTS: FAIL' if failed else 'CHECKER_FAULTS: PASS')
    return {'status': 'ok', 'returncode': int(bool(failed)),
            'stdout': '\n'.join(lines) + '\n', 'stderr': ''}


class CheckerFaultTests(unittest.TestCase):
    fault = next(fault for fault in FAULTS if fault.id == 'ouro-cumul-sort-any')

    def setUp(self):
        self.parent = ROOT / '_build/smith/selftest'
        self.parent.mkdir(parents=True, exist_ok=True)
        self.work = self.parent / ('checker-fault-' + uuid.uuid4().hex)
        self.work.mkdir()

    def tearDown(self):
        self.assertTrue(self.work.resolve().is_relative_to(self.parent.resolve()))
        shutil.rmtree(self.work)

    def test_clean_baseline_and_intended_kill(self):
        self.assertEqual(classify_run(law_report(), None)[0], 'clean')
        self.assertEqual(classify_run(law_report(self.fault.expect), None)[0], 'baseline-dirty')
        self.assertEqual(classify_run(law_report(self.fault.expect), self.fault.expect)[0], 'killed')

    def test_clean_or_unrelated_mutant_survives(self):
        for failed in ((), ('CHK.positivity',)):
            with self.subTest(failed=failed):
                self.assertEqual(classify_run(law_report(failed), self.fault.expect)[0], 'survived')

    def test_both_coverage_laws_are_required(self):
        fault = next(fault for fault in FAULTS if fault.id == 'ouro-coverage-off')
        self.assertEqual(classify_run(law_report(fault.expect[:1]), fault.expect)[0], 'survived')
        self.assertEqual(classify_run(law_report(fault.expect), fault.expect)[0], 'killed')

    def test_a_valid_control_failure_disqualifies_a_kill(self):
        for name in LAW_EXPECTATIONS:
            if name.startswith('CTL.'):
                with self.subTest(name=name):
                    self.assertEqual(classify_run(law_report([*self.fault.expect, name]), self.fault.expect)[0], 'wrong-property')

    def test_crashes_limits_and_stderr_cannot_kill(self):
        variants = [{'status': status} for status in ('crash', 'timeout', 'memory', 'spawn-error')]
        variants += [{'returncode': code} for code in (-1073741819, -9, 2, 137, None, True, '1')]
        variants += [{'stderr': 'unexpected diagnostic'}, {'stdout': None}, {'stderr': None}]
        for change in variants:
            with self.subTest(change=change):
                self.assertEqual(classify_run({**law_report(self.fault.expect), **change}, self.fault.expect)[0], 'runtime-error')

    def test_missing_repeated_reordered_and_extra_laws_cannot_kill(self):
        rows = law_report(self.fault.expect)['stdout'].splitlines()
        variants = [rows[1:], rows + ['extra'], [rows[1], rows[0]] + rows[2:], [rows[0], rows[0]] + rows[2:]]
        for rows in variants:
            evidence = {**law_report(self.fault.expect), 'stdout': '\n'.join(rows)}
            self.assertEqual(classify_run(evidence, self.fault.expect)[0], 'invalid-report')

    def test_pass_label_cannot_hide_a_wrong_value(self):
        evidence = law_report(self.fault.expect)
        evidence['stdout'] = evidence['stdout'].replace('FAIL CHK.sort-cumul', 'PASS CHK.sort-cumul')
        self.assertEqual(classify_run(evidence, self.fault.expect)[0], 'invalid-report')
        evidence = law_report(self.fault.expect)
        evidence['stdout'] = evidence['stdout'].replace('got=changed-value', 'got=' + LAW_EXPECTATIONS['CHK.sort-cumul'])
        self.assertEqual(classify_run(evidence, self.fault.expect)[0], 'invalid-report')

    def test_terminal_and_exit_must_agree(self):
        evidence = law_report(self.fault.expect)
        variants = [dict(evidence, returncode=0),
                    dict(evidence, stdout=evidence['stdout'].replace('CHECKER_FAULTS: FAIL', 'CHECKER_FAULTS: PASS')),
                    dict(law_report(), returncode=1)]
        for evidence in variants:
            self.assertEqual(classify_run(evidence, self.fault.expect)[0], 'invalid-report')

    def test_empty_or_unknown_required_laws_cannot_kill(self):
        for expected in ((), ('CHK.unknown',)):
            self.assertEqual(classify_run(law_report(self.fault.expect), expected)[0], 'invalid-report')

    def test_runtime_and_protocol_failures_do_not_become_semantic_findings(self):
        for status in ('runtime-error', 'invalid-report'):
            row = {'status': status, 'failed_laws': list(self.fault.expect), 'detail': status}
            result = fault_result(self.fault, row)
            self.assertEqual(result.status, 'survived')
            self.assertEqual(result.caught_by, [])

    def test_input_drift_and_build_failure_are_unbuildable(self):
        for status in ('input-drift', 'unbuildable'):
            result = fault_result(self.fault, {'status': status, 'failed_laws': [], 'detail': status})
            self.assertEqual(result.status, 'unbuildable')

    def test_stale_and_ineffective_patches_fail_closed(self):
        for source in ('absent', self.fault.old + self.fault.old):
            with self.assertRaises(StaleFault):
                apply_fault(source, self.fault)
        with self.assertRaises(StaleFault):
            apply_fault(self.fault.old, replace(self.fault, new=self.fault.old))

    def test_secondary_patch_must_also_match_exactly(self):
        source = self.work / self.fault.file
        source.parent.mkdir(parents=True)
        source.write_text(self.fault.old, encoding='utf-8')
        fault = replace(self.fault, extra_patches=((self.fault.file, 'missing secondary guard', 'changed'),))
        with self.assertRaises(StaleFault):
            fault_texts(fault, self.work)
        self.assertEqual(source.read_text(encoding='utf-8'), self.fault.old)

    def test_law_inputs_cannot_be_mutation_targets(self):
        frozen = self.work / 'frozen'
        source = frozen / LAW_ENTRY
        source.parent.mkdir(parents=True)
        source.write_text('law before', encoding='utf-8')
        fault = replace(self.fault, file=LAW_ENTRY, old='law before', new='law after')
        with patch('ourosmith.checker_faults.run_limited') as execute:
            row = run_variant(self.work / 'variant', frozen, [LAW_ENTRY], fault,
                              ROOT / '_build/c/ouro1.exe', {}, 1, 64, {}, lambda _message: None)
        self.assertEqual(row['status'], 'stale')
        execute.assert_not_called()
        self.assertEqual((self.work / 'variant/source' / LAW_ENTRY).read_text(encoding='utf-8'), 'law before')

    def test_incomplete_import_cone_cannot_establish_a_baseline(self):
        with patch('frontend_regen.collect_units', return_value=[]), \
             patch('ourosmith.checker_faults.run_variant') as execute:
            campaign = run_checker_campaign([self.fault], self.work, compiler=ROOT / '_build/c/ouro1.exe',
                                            timeout_s=1, memory_mb=64, log=lambda _message: None)
        self.assertEqual(campaign['baseline']['status'], 'unbuildable')
        self.assertEqual([result.status for result in campaign['faults']], ['baseline-dirty'])
        execute.assert_not_called()

    def test_live_checker_lineage_is_complete_and_metadata_is_explicit(self):
        checker = [fault for fault in FAULTS if fault.target == 'checker']
        self.assertEqual(len(checker), 11)
        lineage = [name for fault in checker for name in fault.legacy]
        self.assertEqual(len(lineage), 20)
        self.assertEqual(len(set(lineage)), 20)
        self.assertEqual({row['id'] for row in OBSOLETE_CHECKER_CONTRACTS},
                         {'py-axiom-tracking-off', 'ml-axiom-tracking-off'})
        self.assertTrue(all(row['status'] == 'obsolete-owner' and row['reason'] and
                            row['retained_control'] == 'CTL.opaque-neutral' for row in OBSOLETE_CHECKER_CONTRACTS))
        self.assertEqual({fault.target for fault in checker}, {'checker'})

    def test_surface_ids_cases_and_expected_properties_are_preserved(self):
        expected = {
            'fe-lambda-annotation-off': (('lambda-domain',), 'mutation:lambda-domain'),
            'fmt-trailing-space-off': (('fmt-roundtrip',), 'positive'),
            'lint-hole-off': (('lint-hole',), 'mutation:lint-hole'),
            'fix-rounds-off': (('fix-check-dirty', 'fix-dead-let'), 'recipe:fixer'),
            'doc-signature-off': (('doc-signature-comment',), 'recipe:documentation'),
            'lsp-line-shift': (('lsp-definition',), 'recipe:language_server'),
            'runtime-nat-successor': (('runtime-reference',), 'positive'),
            'manifest-crash-as-reject': (('manifest-status-139',), 'recipe:manifest_contract'),
            'eval-string-shims-off': (('eval-reference',), 'recipe:compiler_parity'),
            'analyzer-truncated-walk': (('analyzer-ast',), 'recipe:analyzer_ast'),
            'cache-source-digest-off': (('module-cache-dependency-invalidation',), 'recipe:module_cache'),
        }
        self.assertEqual({fault.id: (fault.expect, fault.case) for fault in FAULTS if fault.case}, expected)
        frontend = next(fault for fault in FAULTS if fault.target == 'frontend')
        self.assertEqual(frontend.file, 'compiler/file_elab_infer.ouro')
        self.assertIn(frontend.file, fault_texts(frontend, ROOT))

    def receipt_fixture(self):
        import native_tool_build
        from repo_support import hash_json

        executable = self.work / 'tool'
        executable.write_bytes(b'fixture binary')
        path = Path(str(executable) + '.build.json')
        required = {*native_tool_build.BUILD_INPUTS, *native_tool_build.RUNTIME,
                    *(path.relative_to(ROOT).as_posix() for path in (ROOT / 'runtime').glob('*.h'))}
        stable = {name: name + '-sha' for name in required}
        inputs = {'kind': 'ouro.native-tool-build.v1', 'entry': 'law.ouro',
                  'compiler_sha256': 'producer-sha', 'sources': {'law.ouro': 'law-sha', **stable}}
        receipt = {'kind': 'ouro.native-tool-build.v1', 'cache': 'miss',
                   'binary_sha256': digest(executable), 'key': hash_json(inputs), 'inputs': inputs}

        def check(value):
            path.write_text(json.dumps(value), encoding='utf-8')
            return build_receipt(executable, ['law.ouro'], {'law.ouro': 'law-sha'}, 'producer-sha', stable)

        return receipt, check

    def test_fresh_build_receipt_binds_sources_runtime_producer_and_binary(self):
        receipt, check = self.receipt_fixture()
        self.assertEqual(check(receipt), receipt)
        for field in ('cache', 'binary_sha256', 'kind', 'key'):
            self.assertIsNone(check({**receipt, field: 'wrong'}))
        changed = json.loads(json.dumps(receipt))
        changed['inputs']['compiler_sha256'] = 'stale producer'
        self.assertIsNone(check(changed))
        for name in ('law.ouro', 'runtime/ouro_rt.c'):
            changed = json.loads(json.dumps(receipt))
            changed['inputs']['sources'][name] = 'stale source'
            self.assertIsNone(check(changed))
        changed = json.loads(json.dumps(receipt))
        del changed['inputs']['sources']['law.ouro']
        self.assertIsNone(check(changed))
        self.assertIsNone(check({}))

    def test_receipt_requires_every_runtime_and_builder_source_even_with_a_new_key(self):
        from repo_support import hash_json

        receipt, check = self.receipt_fixture()
        for name in receipt['inputs']['sources']:
            changed = json.loads(json.dumps(receipt))
            del changed['inputs']['sources'][name]
            changed['key'] = hash_json(changed['inputs'])
            with self.subTest(name=name):
                self.assertIsNone(check(changed))
        changed = json.loads(json.dumps(receipt))
        changed['inputs']['sources']['unreviewed-source.ouro'] = 'extra-sha'
        changed['key'] = hash_json(changed['inputs'])
        self.assertIsNone(check(changed))

    def test_receipt_requires_exact_entry_even_when_its_source_is_present(self):
        from repo_support import hash_json

        receipt, check = self.receipt_fixture()
        for entry in ('runtime/ouro_rt.c', 'other-law.ouro', None):
            changed = json.loads(json.dumps(receipt))
            changed['inputs']['entry'] = entry
            changed['key'] = hash_json(changed['inputs'])
            self.assertIsNone(check(changed))

    def aggregate(self, results, *, baseline='clean', unchanged=True, selected=None, catalogue=()):
        selected = {self.fault.id} if selected is None else selected
        campaign = {'baseline': {'status': baseline, 'failed_laws': [], 'seconds': 0},
                    'faults': results, 'unchanged': unchanged}
        with patch('ourosmith.faults.check_catalogue', return_value=list(catalogue)), \
             patch('ourosmith.checker_faults.run_checker_campaign', return_value=campaign), \
             patch('ourosmith.provenance.begin', return_value={'source': 'source', 'binaries': {}}), \
             patch('ourosmith.provenance.source_state', return_value='source'), \
             patch('ourosmith.provenance.binary_state', return_value={'compiler': 'sha'}), \
             patch('ourosmith.provenance.git', return_value='status'), \
             patch('ourosmith.faults.generator_hash', return_value='generator'):
            return run_faults(config=SimpleNamespace(profile='pr', seeds=[1]), out=self.work,
                              compiler=ROOT / '_build/c/ouro1.exe', timeout_s=1, memory_mb=64,
                              only=selected, log=lambda _message: None)

    def test_aggregate_requires_every_result_to_be_killed(self):
        for status in ('killed', 'survived', 'stale', 'unbuildable', 'baseline-dirty', 'unknown-status'):
            result = self.aggregate([FaultResult(self.fault, status)])
            self.assertEqual(result['pass'], status == 'killed')

    def test_aggregate_rejects_dirty_baseline_catalogue_and_changed_inputs(self):
        killed = [FaultResult(self.fault, 'killed')]
        self.assertFalse(self.aggregate(killed, baseline='baseline-dirty')['pass'])
        self.assertFalse(self.aggregate(killed, unchanged=False)['pass'])
        self.assertFalse(self.aggregate(killed, catalogue=['stale source anchor'])['pass'])

    def test_aggregate_rejects_missing_duplicate_empty_or_unknown_selection(self):
        self.assertFalse(self.aggregate([])['pass'])
        other = next(fault for fault in FAULTS if fault.id == 'ouro-positivity-off')
        duplicated = [FaultResult(self.fault, 'killed'), FaultResult(self.fault, 'killed')]
        self.assertFalse(self.aggregate(duplicated, selected={self.fault.id, other.id})['pass'])
        self.assertFalse(self.aggregate([], selected=set())['pass'])
        self.assertFalse(self.aggregate([], selected={'unknown'})['pass'])

    def campaign_fixture(self):
        from ourosmith.checker_faults import BUILD_INPUTS

        # Variant execution is mocked; preflight still hashes and freezes real
        # fixture files. No uncommitted compiler or overlay module is required.
        fixture = self.work / 'campaign-inputs'
        for name in (LAW_ENTRY, *BUILD_INPUTS, 'runtime/unit-fixture.c', 'compiler-fixture.exe'):
            path = fixture / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'unit-test input; run_variant is mocked')
        return fixture, fixture / 'compiler-fixture.exe'

    def test_dirty_canonical_baseline_prevents_mutant_execution(self):
        baseline = {'id': 'baseline', 'status': 'baseline-dirty', 'failed_laws': ['CHK.sort-cumul'],
                    'detail': '', 'seconds': 0}
        fixture, compiler = self.campaign_fixture()
        with patch('ourosmith.checker_faults.ROOT', fixture), \
             patch('frontend_regen.collect_units', return_value=[LAW_ENTRY]), \
             patch('ourosmith.checker_faults.run_variant', return_value=baseline) as execute, \
             patch('ourosmith.checker_faults.environment', return_value={}):
            campaign = run_checker_campaign([self.fault], fixture / 'out', compiler=compiler,
                                            timeout_s=1, memory_mb=64, log=lambda _message: None)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual([result.status for result in campaign['faults']], ['baseline-dirty'])
        self.assertEqual(campaign['baseline']['status'], 'baseline-dirty')
        self.assertTrue(campaign['unchanged'])

    def test_missing_compiler_prevents_all_variant_execution(self):
        fixture, _compiler = self.campaign_fixture()
        with patch('ourosmith.checker_faults.ROOT', fixture), \
             patch('frontend_regen.collect_units', return_value=[LAW_ENTRY]), \
             patch('ourosmith.checker_faults.run_variant') as execute:
            campaign = run_checker_campaign([self.fault], fixture / 'out',
                                            compiler=fixture / 'missing-compiler.exe',
                                            timeout_s=1, memory_mb=64, log=lambda _message: None)
        execute.assert_not_called()
        self.assertEqual(campaign['baseline']['status'], 'unbuildable')
        self.assertEqual([result.status for result in campaign['faults']], ['baseline-dirty'])
        self.assertFalse(campaign['unchanged'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
