#!/usr/bin/env python3
"""Measure canonical retained laws and the current compiler boundary gate."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
import sys
import uuid

import frontend_regen
import native_tool_build
from ourosmith.host import environment
from ourosmith.limits import run_limited
from repo_support import finite_number, hash_json, read_json_object, sha256_path, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
REPORT_KIND = 'ouro.kernel-profile-report.v2'
BASELINE_KIND = 'ouro.kernel-baseline.v2'
BUDGET_KIND = 'ouro.kernel-budgets.v2'
TIMING_DOMAIN = 'canonical-retained-executable-process-wall.v1'
LAW_ENTRY = 'tests/compiler_retained_tests.ouro'
BOUNDARY_ENTRY = 'tools/repo_gate/main.ouro'
BOUNDARY_CHECKS = ('compiler-checker-dependencies', 'compiler-checked-value-owners', 'compiler-boundary-documentation')
LAW_NAMES = (
    'nat_id', 'bool_case', 'case_branch_lambda_lift_under_binder',
    'case_branch_lambda_lift_under_binder/check', 'nested_case_same_constructor_fields',
    'nested_case_same_constructor_fields/normalize', 'fix_binder_name_not_in_conversion',
    'fix_binder_name_not_in_conversion/constant-aliases', 'fix_binder_name_not_in_conversion/raw-fix',
    'copy preserves two successors', 'parameterized_box', 'parameterized_recursive_sequence',
    'string_literal_intrinsic', 'string_literal_axiom', 'wrong_body_type',
    'constructor_index_out_of_range', 'fix_recarg_out_of_range', 'forward_reference_constant',
    'substitution_name_capture_open_let', 'malformed_case_branch_count', 'invalid_eliminator_coverage',
    'malformed_environment_duplicate_global', 'constructor_universe_above_inductive',
    'nonpositive_constructor', 'nested_negative_inductive_argument', 'inductive_parameter_self_reference',
    'invalid_constructor_return', 'ML eta-short case branch rejects recursive escape',
    'ML case branch annotation cannot capture recursion', 'ML stuck fix spines distinguish arguments',
    'ML stuck case distinguishes parameter metadata', 'ML stuck case distinguishes constructor arity',
    'ML captured fix type participates in conversion', 'ML let-bound fix reifies its type environment',
    'ML non-function eta stays false', 'ML universe ceiling level 1', 'ML universe ceiling level 2',
    'ML universe ceiling admits level 1', 'ML universe ceiling admits level 2', 'ML universe ceiling admits level 3',
    'local type alias enters a checked lambda annotation', 'local type alias direct checking',
    'local type alias inference', 'nested strict descent', 'nested nonzero recursive argument',
    'nested eta-short identity body', 'nested strict computes identity',
    'nested nonzero argument computes identity', 'nested eta-short computes identity',
    'nested unchanged initial argument', 'nested growing inner recursion', 'nested growing other parameter',
    'nested captured unchanged argument', 'nested partial function escape', 'nested function argument escape',
)


def relative(path: Path) -> str:
    path = path.resolve()
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)


def process_ok(result: dict) -> bool:
    return (result.get('status') == 'ok' and type(result.get('returncode')) is int
            and result['returncode'] == 0 and isinstance(result.get('stdout'), str)
            and result.get('stderr') == '' and finite_number(result.get('elapsed_s'))
            and finite_number(result.get('peak_memory_mib')))


def retained_protocol(result: dict) -> bool:
    expected = ['PASS ' + name for name in LAW_NAMES] + ['COMPILER_RETAINED: PASS']
    return process_ok(result) and result['stdout'].splitlines() == expected


def boundary_protocol(result: dict, report: dict, report_path: str) -> bool:
    expected = [f'REPO_GATE_SUMMARY profile=compiler-boundary pass=true issues=0 report={report_path}',
                *(f'REPO_GATE_CHECK {name} status=pass issues=0' for name in BOUNDARY_CHECKS)]
    gates = report.get('gates')
    return (process_ok(result) and result['stdout'].rstrip('\r\n').splitlines() == expected
            and report.get('kind') == 'ouro.repo-gate-report.v1' and report.get('version') == '1'
            and report.get('profile') == 'compiler-boundary' and report.get('pass') is True
            and report.get('execution_backend') == 'ouro-native-repo-gate'
            and report.get('execution_mode') == 'native' and report.get('issues') == []
            and isinstance(gates, list) and len(gates) == len(BOUNDARY_CHECKS)
            and all(isinstance(gate, dict) and gate.get('name') == name and gate.get('status') == 'pass'
                    and gate.get('blocking') is True and gate.get('issues') == []
                    and isinstance(gate.get('metrics'), list)
                    for gate, name in zip(gates, BOUNDARY_CHECKS, strict=True)))


def validate_budgets(budgets: dict) -> None:
    if budgets.get('kind') != BUDGET_KIND or budgets.get('timing_domain') != TIMING_DOMAIN:
        raise ValueError('obsolete or unknown resource budget domain')
    execution = budgets['retained_execution']
    if (type(execution['min_fixtures']) is not int or execution['min_fixtures'] < 17
            or type(execution['max_unexpected_fixtures']) is not int or execution['max_unexpected_fixtures'] != 0
            or not finite_number(execution['max_elapsed_ms'], 0.001)):
        raise ValueError('retained execution budgets are invalid')
    limits = budgets['orchestration']
    if type(limits['workers']) is not int or limits['workers'] != 1:
        raise ValueError('the profile requires one bounded worker')
    if type(limits['memory_limit_mib']) is not int or limits['memory_limit_mib'] <= 0:
        raise ValueError('a positive process memory limit is required')
    if any(not finite_number(limits[name], 0.001)
           for name in ('check_timeout_s', 'build_timeout_s', 'run_timeout_s', 'boundary_timeout_s')):
        raise ValueError('positive finite process timeouts are required')
    if budgets['native_tool_cache']['required_modes'] != ['off', 'miss', 'hit']:
        raise ValueError('uncached, fresh cached and cache-hit executions are all required')
    if (budgets['compiler_boundary']['required_checks'] != list(BOUNDARY_CHECKS)
            or type(budgets['compiler_boundary']['max_issues']) is not int
            or budgets['compiler_boundary']['max_issues'] != 0):
        raise ValueError('the complete compiler boundary requires zero issues')


def receipt_valid(receipt: dict, executable: Path, expected_sources: dict, producer_sha: str,
                  entry: str, modes: set[str]) -> bool:
    try:
        inputs = receipt['inputs']
        return (receipt['kind'] == native_tool_build.KIND and inputs['kind'] == native_tool_build.KIND
                and receipt['cache'] in modes and receipt['binary_sha256'] == sha256_path(executable)
                and receipt['key'] == hash_json(inputs) and inputs['sources'] == expected_sources
                and inputs['entry'] == entry and inputs['compiler_sha256'] == producer_sha)
    except (KeyError, OSError, TypeError, ValueError):
        return False


def expected_sources(entry: str) -> dict:
    names = dict.fromkeys([*frontend_regen.collect_units(entry), *native_tool_build.BUILD_INPUTS,
                          *native_tool_build.RUNTIME,
                          *(path.relative_to(ROOT).as_posix() for path in sorted((ROOT / 'runtime').glob('*.h')))])
    if entry not in names:
        raise ValueError('missing law or boundary source entry')
    return {name: sha256_path(ROOT / name) for name in names}


def boundary_receipt_path(executable: Path) -> Path:
    receipt = Path(str(executable) + '.build.json')
    if not receipt.exists() and executable.suffix == '.exe':
        logical = executable.with_suffix('.build.json')
        if logical.is_file():
            return logical
    return receipt


def input_state(compiler: Path, boundary: Path, budget_path: Path) -> dict:
    paths = {compiler, boundary, boundary_receipt_path(boundary), budget_path,
             ROOT / 'docs/tcb.md', ROOT / 'Ouro.seal', Path(__file__),
             *(ROOT / name for entry in (LAW_ENTRY, BOUNDARY_ENTRY) for name in expected_sources(entry)),
             *(ROOT / 'scripts/ourosmith' / name for name in ('host.py', 'limits.py', 'windows_job.py', 'exec_child.py', '__init__.py'))}
    # Match the boundary's full source inventory, so additions cannot escape the hash guard.
    for directory in ('compiler', 'std'):
        paths.update((ROOT / directory).rglob('*.ouro'))
    return {relative(path): sha256_path(path) for path in sorted(paths)}


def execute(command: list[str], directory: Path, phase: str, env: dict, timeout: float, memory: int) -> dict:
    print('KERNEL_PROFILE:', phase, flush=True)
    result = asdict(run_limited(command, cwd=ROOT, env=env, timeout_s=timeout, memory_mb=memory))
    result['peak_memory_mib'] = result.pop('peak_rss_mb')
    result['memory_metric'] = 'windows-job-peak-commit' if sys.platform == 'win32' else 'process-tree-peak-rss'
    result['command'] = command
    result['timeout_s'] = timeout
    result['memory_limit_mib'] = memory
    for channel in ('stdout', 'stderr'):
        (directory / (phase + '.' + channel)).write_text(result[channel], encoding='utf-8', newline='\n')
    write_json_atomic(directory / (phase + '.json'), result)
    return result


def evaluate(variants: list[dict], boundary: dict, source_unchanged: bool, budgets: dict) -> dict:
    validate_budgets(budgets)
    modes = [row.get('mode') for row in variants]
    complete = modes == budgets['native_tool_cache']['required_modes']
    execution = complete and all(retained_protocol(row.get('run', {})) for row in variants)
    resource = execution and all(row['run']['elapsed_s'] * 1000 <= budgets['retained_execution']['max_elapsed_ms']
                                 and row['run']['peak_memory_mib'] <= budgets['orchestration']['memory_limit_mib']
                                 for row in variants)
    builds = complete and all(row.get('receipt_valid') is True and process_ok(row.get('build', {})) for row in variants)
    parity = (execution and builds and variants[0]['receipt']['inputs'] == variants[1]['receipt']['inputs']
              == variants[2]['receipt']['inputs']
              and variants[1]['receipt']['binary_sha256'] == variants[2]['receipt']['binary_sha256']
              and len({row['run']['stdout'] for row in variants}) == 1)
    inventory = len(LAW_NAMES) >= budgets['retained_execution']['min_fixtures']
    boundary_ok = boundary.get('receipt_valid') is True and boundary_protocol(
        boundary.get('run', {}), boundary.get('report', {}), boundary.get('report_path', ''))
    checks = {'retained_protocol': execution, 'retained_resource': resource, 'complete_inventory': inventory,
              'actual_builds': builds, 'build_cache_parity': parity, 'compiler_boundary': boundary_ok,
              'input_hashes_unchanged': source_unchanged is True}
    return {'pass': all(checks.values()), 'checks': checks,
            'failed': [name for name, passed in checks.items() if not passed]}


def compare_baseline(baseline: dict | None, report: dict) -> dict:
    if baseline is None:
        return {'comparable': False, 'reason': 'no baseline supplied'}
    if baseline.get('kind') != BASELINE_KIND or baseline.get('timing_domain') != TIMING_DOMAIN:
        return {'comparable': False, 'reason': 'legacy JSON replay timing is a different operation'}
    if baseline.get('context') != report.get('context'):
        return {'comparable': False, 'reason': 'producer, runtime or retained law inputs differ'}
    previous = baseline.get('max_elapsed_ms')
    current = report.get('max_elapsed_ms')
    if not finite_number(previous) or not finite_number(current):
        return {'comparable': False, 'reason': 'a complete actual execution measurement is unavailable'}
    return {'comparable': True, 'delta_ms': current - previous}


def run_profile(*, compiler: Path, boundary: Path, out: Path, budget_path: Path, baseline: dict | None) -> dict:
    budgets = read_json_object(budget_path)
    validate_budgets(budgets)
    limits = budgets['orchestration']
    out.mkdir(parents=True, exist_ok=True)
    work = out / ('p-' + uuid.uuid4().hex[:8])
    work.mkdir()
    before = input_state(compiler, boundary, budget_path)
    producer_sha = sha256_path(compiler)
    sources = expected_sources(LAW_ENTRY)
    boundary_sources = expected_sources(BOUNDARY_ENTRY)
    units = frontend_regen.collect_units(LAW_ENTRY)
    env = environment(jobs=1, build=True)
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8', OURO_CCACHE='disabled')
    boundary_receipt = read_json_object(boundary_receipt_path(boundary))
    boundary_valid = receipt_valid(boundary_receipt, boundary, boundary_sources, producer_sha,
                                   BOUNDARY_ENTRY, {'miss', 'hit', 'installed-hit'})
    gate_out = work / 'boundary'
    gate_out.mkdir()
    gate_path = (gate_out / 'repo-gate.json').as_posix()
    gate_run = execute([str(boundary), '--profile', 'compiler-boundary', '--root', ROOT.as_posix(),
                        '--out', gate_out.as_posix()], work, 'boundary', env,
                       limits['boundary_timeout_s'], limits['memory_limit_mib'])
    try:
        gate_report = read_json_object(gate_out / 'repo-gate.json')
    except (OSError, ValueError):
        gate_report = {}
    boundary_evidence = {'receipt_valid': boundary_valid, 'receipt': boundary_receipt, 'run': gate_run,
                         'report': gate_report, 'report_path': gate_path}
    check_command = [str(compiler), 'check', LAW_ENTRY, '999999']
    for name in units:
        check_command.extend(('--unit', name))
    checked = execute(check_command, work, 'strict-check', env, limits['check_timeout_s'], limits['memory_limit_mib'])
    check_ok = process_ok(checked) and checked['stdout'].splitlines() == ['CHECK_OK']
    variants = []
    if check_ok:
        for mode in budgets['native_tool_cache']['required_modes']:
            executable = work / (mode + ('.exe' if sys.platform == 'win32' else ''))
            command = [sys.executable, '-B', str(ROOT / 'scripts/native_tool_build.py'), LAW_ENTRY, str(executable),
                       '--compiler', str(compiler), '--fuel', '16000', '--jobs', '1', '--build-dir', str(work / 'b'),
                       '--cache-dir', str(work / 'c'), '--no-cache' if mode == 'off' else '--cache',
                       '--opt-level', 'O0', '--ccache', 'disabled']
            built = execute(command, work, mode + '-build', env, limits['build_timeout_s'], limits['memory_limit_mib'])
            try:
                receipt = read_json_object(Path(str(executable) + '.build.json'))
            except (OSError, ValueError):
                receipt = {}
            cache = 'hit' if mode == 'hit' else 'miss'
            valid = (process_ok(built) and 'BUILD_TOOL_CACHE: ' + cache + ' ' in built['stdout']
                     and receipt_valid(receipt, executable, sources, producer_sha, LAW_ENTRY, {cache}))
            row = {'mode': mode, 'build': built, 'receipt': receipt, 'receipt_valid': valid,
                   'binary_sha256': sha256_path(executable) if executable.is_file() else None}
            if valid:
                row['run'] = execute([str(executable)], work, mode + '-run', env,
                                      limits['run_timeout_s'], limits['memory_limit_mib'])
            variants.append(row)
    after = input_state(compiler, boundary, budget_path)
    status = evaluate(variants, boundary_evidence, before == after, budgets)
    runs = [row['run'] for row in variants if 'run' in row]
    maximum = max((row['elapsed_s'] * 1000 for row in runs), default=None)
    report = {'kind': REPORT_KIND, 'pass': check_ok and status['pass'], 'timing_domain': TIMING_DOMAIN,
              'timing_note': 'Full bounded process wall time including launch, output and supervision; strict checking and builds are separate phases.',
              'memory_note': 'Windows measures Job peak commit; POSIX measures process-tree RSS with an inherited per-process address-space limit.',
              'fixtures': len(LAW_NAMES), 'required_laws': list(LAW_NAMES), 'max_elapsed_ms': maximum,
              'context': {'producer_sha256': producer_sha, 'retained_law_sha256': sources[LAW_ENTRY],
                          'retained_fixture_sha256': sources['tests/compiler_retained_fixtures.ouro'],
                          'runtime': {name: value for name, value in sources.items() if name.startswith('runtime/')}},
              'budgets': budgets, 'budget_status': status, 'strict_check': checked,
              'variants': variants, 'compiler_boundary': boundary_evidence,
              'input_hashes_before': before, 'input_hashes_after': after, 'inputs_unchanged': before == after,
              'work': relative(work),
              'memo_policy': 'Canonical checking exposes no retired Python/OCaml memo toggle. Repeated and fresh-environment laws remain in retained/Smith suites. Native-tool cache parity is an additional build-cache contract.',
              'property_suite': 'The separate generated property suite is not included in the retained execution timing budget.'}
    report['baseline_comparison'] = compare_baseline(baseline, report)
    write_json_atomic(out / 'kernel-profile.json', report)
    print('KERNEL_PROFILE:', 'PASS' if report['pass'] else 'FAIL', f'fixtures={len(LAW_NAMES)}',
          f'max_elapsed_ms={maximum}', 'failed=' + ','.join(status['failed']), flush=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--repo-gate', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=ROOT / '_build/kernel')
    parser.add_argument('--budgets', type=Path, default=ROOT / 'quality/kernel_budgets.json')
    parser.add_argument('--baseline', type=Path, default=ROOT / 'quality/kernel_baseline.json')
    parser.add_argument('--baseline-out', type=Path)
    args = parser.parse_args()
    try:
        report = run_profile(compiler=args.compiler.resolve(), boundary=args.repo_gate.resolve(), out=args.out.resolve(),
                             budget_path=args.budgets.resolve(), baseline=read_json_object(args.baseline) if args.baseline.is_file() else None)
        if args.baseline_out:
            write_json_atomic(args.baseline_out, {'kind': BASELINE_KIND, 'timing_domain': TIMING_DOMAIN,
                                                 'pass': report['pass'], 'context': report['context'],
                                                 'fixtures': report['fixtures'], 'max_elapsed_ms': report['max_elapsed_ms'],
                                                 'budget_status': report['budget_status'],
                                                 'report_sha256': sha256_path(args.out / 'kernel-profile.json'),
                                                 'report': relative(args.out / 'kernel-profile.json')})
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('KERNEL_PROFILE: FAIL', error, file=sys.stderr)
        return 1
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
