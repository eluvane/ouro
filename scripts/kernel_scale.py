#!/usr/bin/env python3
"""Supervise source-bound canonical Core scale/depth probes; no semantic fallback."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import os
from pathlib import Path
import sys
import uuid

import frontend_regen
import native_tool_build
import ouro_build
from ourosmith.host import environment
from ourosmith.limits import run_limited
from repo_support import finite_number, hash_json, read_json_object, sha256_path, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
REPORT_KIND = 'ouro.kernel-scale-report.v1'
TIMING_DOMAIN = 'canonical-core-executable-process-wall.v1'
ENTRIES = {'scale': 'tests/compiler_scale_probe.ouro', 'depth': 'tests/compiler_depth_probe.ouro'}
SCALE = ('let-chain', 'lam-chain', 'app-spine', 'nested-app', 'domain-deep-pi', 'const-chain')
DEPTH = ('check-lam', 'infer-pi-sort', 'infer-domain-sort', 'check-let', 'infer-app',
         'normalize-let', 'normalize-app', 'whnf-lam', 'normalize-lam', 'convert-lam',
         'recheck-lam', 'recheck-let', 'recheck-app', 'recheck-axiom-pi', 'recheck-axiom-domain')
DEPTHS = {'scale': (20_000,), 'depth': (10_000, 1_000_000)}
WORK_LIMIT = 500_000
MEMORY_MIB = 3072
CHECK_TIMEOUT = 600
BUILD_TIMEOUT = 600
RUN_TIMEOUT = {'scale': 15, 'depth': 30}
INVENTORY_TIMEOUT = 60
SCALE_BUDGET = 10
CFLAGS = ['-O0', '-std=c99', '-D_POSIX_C_SOURCE=200809L',
          '-fdebug-prefix-map=.=/ouro', '-fmacro-prefix-map=.=/ouro']
ORCHESTRATION = ('scripts/kernel_scale.py', 'scripts/repo_support.py',
                 'scripts/ourosmith/host.py', 'scripts/ourosmith/limits.py',
                 'scripts/ourosmith/exec_child.py', 'scripts/ourosmith/windows_job.py',
                 'scripts/ourosmith/__init__.py', 'docs/tcb.md', 'Ouro.seal')

# These are construction-owned input-work counts, not checker outcomes. Scale
# groups the roots of its checked calls; depth records the one entry's roots.
WORK = {
    'scale': {'let-chain': (3, 3), 'lam-chain': (4, 3), 'app-spine': (4, 4),
              'nested-app': (4, 4), 'domain-deep-pi': (2, 2), 'const-chain': (3, 2)},
    'depth': {'check-lam': (4, 3), 'infer-pi-sort': (2, 2), 'infer-domain-sort': (2, 2),
              'check-let': (3, 3), 'infer-app': (2, 2), 'normalize-let': (3, 1),
              'normalize-app': (2, 1), 'whnf-lam': (2, 1), 'normalize-lam': (2, 1),
              'convert-lam': (4, 2), 'recheck-lam': (4, 3), 'recheck-let': (3, 3),
              'recheck-app': (2, 3), 'recheck-axiom-pi': (2, 2), 'recheck-axiom-domain': (2, 2)},
}


def relative(path: Path) -> str:
    path = path.resolve()
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)


def resolve(name: str) -> Path:
    path = Path(name)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def expected_sources(entry: str) -> dict[str, str]:
    names = {*frontend_regen.collect_units(entry), *native_tool_build.BUILD_INPUTS,
             *native_tool_build.RUNTIME,
             *(path.relative_to(ROOT).as_posix() for path in (ROOT / 'runtime').glob('*.h'))}
    if entry not in names:
        raise ValueError('the actual native-tool source inventory omits the probe')
    return {name: sha256_path(ROOT / name) for name in sorted(names)}


def input_state(entry: str, compiler: Path) -> dict[str, str]:
    paths = {compiler, *(ROOT / name for name in expected_sources(entry)),
             *(ROOT / name for name in ORCHESTRATION)}
    for directory in ('compiler', 'std'):
        paths.update((ROOT / directory).rglob('*.ouro'))
    return {relative(path): sha256_path(path) for path in sorted(paths)}


def process_ok(result: dict, timeout: int) -> bool:
    metric = result.get('memory_metric')
    peak = result.get('peak_memory_mib')
    memory_ok = ((metric == 'windows-job-peak-commit' and finite_number(peak) and peak <= MEMORY_MIB)
                 if os.name == 'nt' else (metric == 'unavailable-posix' and peak is None))
    return (result.get('status') == 'ok' and type(result.get('returncode')) is int
            and result['returncode'] == 0 and isinstance(result.get('stdout'), str)
            and result.get('stderr') == '' and finite_number(result.get('elapsed_s'))
            and result['elapsed_s'] <= timeout and type(result.get('timeout_s')) is int and result['timeout_s'] == timeout
            and type(result.get('memory_limit_mib')) is int and result['memory_limit_mib'] == MEMORY_MIB
            and result.get('argv') == result.get('command') and memory_ok)


def expected_cases(profile: str) -> list[tuple[str, int]]:
    operations = SCALE if profile == 'scale' else DEPTH
    return [(operation, depth) for depth in DEPTHS[profile] for operation in operations]


def operation_protocol(profile: str, operation: str, depth: int, result: dict) -> bool:
    if not process_ok(result, RUN_TIMEOUT[profile]):
        return False
    factor, offset = WORK[profile][operation]
    required = factor * depth + offset
    visited = min(WORK_LIMIT, required)
    exhausted = 'true' if required > WORK_LIMIT else 'false'
    prefix = 'KERNEL_' + profile.upper()
    start = f'{prefix}_START operation={operation} depth={depth}'
    audit = f'{prefix}_INPUT limit={WORK_LIMIT} visited={visited} exhausted={exhausted}'
    success = f'{prefix}_RESULT operation={operation} outcome=success code=0'
    resource = f'{prefix}_RESULT operation={operation} outcome=resource code=4'
    lines = result['stdout'].splitlines()
    allowed = {success, resource} if profile == 'depth' and depth == 1_000_000 else {success}
    return (len(lines) == 3 and lines[0] == start and lines[1] == audit and lines[2] in allowed
            and (profile != 'scale' or result['elapsed_s'] <= SCALE_BUDGET))


def inventory_protocol(result: dict) -> bool:
    if not process_ok(result, INVENTORY_TIMEOUT):
        return False
    expected = ['KERNEL_SCALE_INVENTORY_START count=20000']
    expected.extend(f'KERNEL_SCALE_ITEM name={name} predecessor={"zero" if name == 100 else name - 1}'
                    for name in range(100, 20_100))
    expected.append('KERNEL_SCALE_INVENTORY_COMPLETE')
    return result['stdout'].splitlines() == expected


def receipt_valid(build: dict, entry: str, sources: dict, producer_sha: str) -> bool:
    try:
        executable = resolve(build['executable'])
        receipt_path = Path(str(executable) + '.build.json')
        receipt = read_json_object(receipt_path)
        inputs = receipt['inputs']
        return (receipt == build['receipt'] and sha256_path(receipt_path) == build['receipt_sha256']
                and receipt['kind'] == native_tool_build.KIND and inputs['kind'] == native_tool_build.KIND
                and receipt['cache'] == 'miss' and receipt['binary_sha256'] == sha256_path(executable)
                and receipt['key'] == hash_json(inputs) and inputs['sources'] == sources
                and inputs['entry'] == entry and inputs['compiler_sha256'] == producer_sha
                and inputs['fuel'] == 16000 and inputs['cflags'] == CFLAGS)
    except (KeyError, OSError, TypeError, ValueError):
        return False


def build_command(compiler: Path, entry: str, executable: Path, directory: Path) -> list[str]:
    return [sys.executable, str(ROOT / 'scripts/native_tool_build.py'), entry, str(executable),
            '--compiler', str(compiler), '--fuel', '16000', '--jobs', '1',
            '--build-dir', str(directory / 'build'), '--cache-dir', str(directory / 'cache'), '--cache',
            '--opt-level', 'O0', '--ccache', 'disabled']


def evaluate(report: dict, profile: str) -> dict:
    """Recheck complete protocols, current source pins and actual build artifacts."""
    checks = {}
    try:
        entry = ENTRIES[profile]
        compiler = resolve(report['compiler'])
        sources = expected_sources(entry)
        state = input_state(entry, compiler)
        executable = resolve(report['build']['executable'])
        directory = resolve(report['run_directory'])
        check_command = [str(compiler), 'check', entry, '999999',
                         *(value for unit in frontend_regen.collect_units(entry) for value in ('--unit', unit))]
        checks['report_domain'] = (report.get('kind') == REPORT_KIND and report.get('profile') == profile
            and report.get('timing_domain') == TIMING_DOMAIN and report.get('entry') == entry
            and type(report.get('workers')) is int and report['workers'] == 1
            and type(report.get('work_limit')) is int and report['work_limit'] == WORK_LIMIT
            and type(report.get('memory_limit_mib')) is int and report['memory_limit_mib'] == MEMORY_MIB
            and type(report.get('scale_budget_s')) is int and report['scale_budget_s'] == SCALE_BUDGET
            and 'error' not in report
            and isinstance(report.get('cpu_affinity'), list) and len(report['cpu_affinity']) == 1
            and type(report['cpu_affinity'][0]) is int and report['cpu_affinity'][0] >= 0)
        checks['current_inputs'] = (report['sources'] == sources and report['producer_sha256'] == sha256_path(compiler)
            and report.get('inputs_before') == state and report.get('inputs_after') == state
            and report.get('inputs_unchanged') is True)
        checks['source_check'] = (process_ok(report['check'], CHECK_TIMEOUT)
            and report['check']['stdout'] == 'CHECK_OK\n' and report['check']['command'] == check_command)
        checks['actual_build'] = (process_ok(report['build']['process'], BUILD_TIMEOUT)
            and report['build']['process']['command'] == build_command(compiler, entry, executable, directory)
            and receipt_valid(report['build'], entry, sources, report['producer_sha256']))
        rows = report['rows']
        inventory = [(row.get('operation'), row.get('depth')) for row in rows]
        checks['complete_inventory'] = inventory == expected_cases(profile)
        checks['operations'] = (checks['complete_inventory'] and all(
            row.get('inputs_unchanged') is True and row.get('receipt_valid') is True
            and row['process']['command'] == [str(executable), '--operation', operation, '--depth', str(depth)]
            and operation_protocol(profile, operation, depth, row['process'])
            for row, (operation, depth) in zip(rows, expected_cases(profile), strict=True)))
        if profile == 'scale':
            inventory_run = report['constant_inventory']
            checks['constant_shape_inventory'] = (isinstance(inventory_run, dict) and inventory_run['command'] ==
                [str(executable), '--operation', 'inventory', '--depth', '20000'] and inventory_protocol(inventory_run))
        else:
            checks['no_scale_inventory_substitute'] = report.get('constant_inventory') is None
    except (KeyError, OSError, TypeError, ValueError) as error:
        checks['report_readable'] = False
        return {'pass': False, 'checks': checks, 'failures': [str(error)]}
    return {'pass': all(checks.values()), 'checks': checks,
            'failures': [name for name, passed in checks.items() if not passed]}


def report_evidence(report_path: Path, profile: str) -> dict:
    """Outer Smith/CI adapter: a stale, partial or failed report earns no credits."""
    try:
        report = read_json_object(report_path)
        result = evaluate(report, profile)
        passed = result['pass'] and report.get('pass') is True
        failures = result['failures'] + ([] if report.get('pass') is True else ['reported_failure'])
        law_credits = (['external/law/scale:' + operation for operation in SCALE]
                   if profile == 'scale' else ['external/law/depth'])
    except (KeyError, OSError, TypeError, ValueError) as error:
        return {'pass': False, 'credits': [], 'failures': [str(error)]}
    else:
        return {'pass': passed, 'credits': law_credits if passed else [], 'failures': failures}


def pin_one_cpu() -> list[int]:
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.GetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
        kernel.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
        process_mask, system_mask = ctypes.c_size_t(), ctypes.c_size_t()
        current = kernel.GetCurrentProcess()
        if not kernel.GetProcessAffinityMask(current, ctypes.byref(process_mask), ctypes.byref(system_mask)) or not process_mask.value:
            raise OSError('could not read the process CPU affinity')
        mask = process_mask.value & -process_mask.value
        if not kernel.SetProcessAffinityMask(current, mask):
            raise OSError('could not bound the probe to one CPU')
        return [mask.bit_length() - 1]
    if hasattr(os, 'sched_getaffinity') and hasattr(os, 'sched_setaffinity'):
        cpu = min(os.sched_getaffinity(0))
        os.sched_setaffinity(0, {cpu})
        return [cpu]
    raise OSError('single-CPU affinity is unavailable on this host')


def execute(command: list[str], directory: Path, label: str, env: dict, timeout: int) -> dict:
    print('KERNEL_SCALE:', label, flush=True)
    result = asdict(run_limited(command, cwd=ROOT, env=env, timeout_s=timeout, memory_mb=MEMORY_MIB))
    peak = result.pop('peak_rss_mb')
    result.update(command=command, timeout_s=timeout, memory_limit_mib=MEMORY_MIB,
                  peak_memory_mib=peak if os.name == 'nt' else None,
                  memory_metric='windows-job-peak-commit' if os.name == 'nt' else 'unavailable-posix')
    for channel in ('stdout', 'stderr'):
        (directory / (label + '.' + channel)).write_text(result[channel], encoding='utf-8', newline='\n')
    write_json_atomic(directory / (label + '.json'), result)
    print('KERNEL_SCALE_RESULT:', label, result['status'], result['returncode'],
          round(result['elapsed_s'], 3), result['peak_memory_mib'], flush=True)
    return result


def run(profile: str, compiler: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    directory = output / ('run-' + uuid.uuid4().hex[:10])
    directory.mkdir(exist_ok=False)
    report = {'kind': REPORT_KIND, 'profile': profile, 'timing_domain': TIMING_DOMAIN,
              'entry': ENTRIES[profile], 'compiler': relative(compiler), 'run_directory': relative(directory),
              'workers': 1, 'memory_limit_mib': MEMORY_MIB, 'work_limit': WORK_LIMIT,
              'scale_budget_s': SCALE_BUDGET, 'rows': [], 'constant_inventory': None, 'pass': False}
    before = None
    try:
        report['cpu_affinity'] = pin_one_cpu()
        entry = ENTRIES[profile]
        sources = expected_sources(entry)
        before = input_state(entry, compiler)
        report.update(sources=sources, producer_sha256=sha256_path(compiler), inputs_before=before)
        env = environment(jobs=1, build=True)
        env.update(OURO_JOBS='1', OURO_FRONTEND_JOBS='1', OURO_CCACHE='disabled')
        command = [str(compiler), 'check', entry, '999999',
                   *(value for unit in frontend_regen.collect_units(entry) for value in ('--unit', unit))]
        report['check'] = execute(command, directory, 'check', env, CHECK_TIMEOUT)
        if not process_ok(report['check'], CHECK_TIMEOUT) or report['check']['stdout'] != 'CHECK_OK\n':
            raise ValueError('the canonical strict source check failed')
        if input_state(entry, compiler) != before:
            raise ValueError('inputs changed during the source check')
        executable = directory / ('probe.exe' if os.name == 'nt' else 'probe')
        build = {'executable': relative(executable)}
        report['build'] = build
        build['process'] = execute(build_command(compiler, entry, executable, directory), directory, 'build', env, BUILD_TIMEOUT)
        receipt_path = Path(str(executable) + '.build.json')
        build.update(receipt=read_json_object(receipt_path), receipt_sha256=sha256_path(receipt_path))
        if not process_ok(build['process'], BUILD_TIMEOUT) or not receipt_valid(build, entry, sources, report['producer_sha256']):
            raise ValueError('the actual fresh native build/receipt failed')
        if profile == 'scale':
            if input_state(entry, compiler) != before:
                raise ValueError('inputs changed before constant inventory')
            report['constant_inventory'] = execute(
                [str(executable), '--operation', 'inventory', '--depth', '20000'], directory,
                'constant-inventory', env, INVENTORY_TIMEOUT)
        for operation, depth in expected_cases(profile):
            if input_state(entry, compiler) != before or not receipt_valid(build, entry, sources, report['producer_sha256']):
                raise ValueError('inputs or executable receipt changed before an operation')
            result = execute([str(executable), '--operation', operation, '--depth', str(depth)], directory,
                             operation + '-' + str(depth), env, RUN_TIMEOUT[profile])
            report['rows'].append({'operation': operation, 'depth': depth, 'process': result,
                                  'inputs_unchanged': input_state(entry, compiler) == before,
                                  'receipt_valid': receipt_valid(build, entry, sources, report['producer_sha256'])})
    except (OSError, ValueError, KeyError, TypeError) as error:
        report['error'] = str(error)
    try:
        report['inputs_after'] = input_state(ENTRIES[profile], compiler)
        report['inputs_unchanged'] = before is not None and report['inputs_after'] == before
    except (OSError, ValueError) as error:
        report.update(inputs_unchanged=False, input_error=str(error))
    report['evaluation'] = evaluate(report, profile)
    report['pass'] = report['evaluation']['pass']
    write_json_atomic(directory / 'report.json', report)
    write_json_atomic(output / 'report.json', report)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=tuple(ENTRIES), required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--compiler', type=Path, help='default: configured c_build_dir/ouro1')
    args = parser.parse_args(argv)
    compiler = args.compiler or ouro_build.load_config(argparse.Namespace()).path('c_build_dir') / 'ouro1'
    compiler = compiler.resolve()
    if os.name == 'nt' and compiler.suffix != '.exe' and Path(str(compiler) + '.exe').is_file():
        compiler = Path(str(compiler) + '.exe')
    report = run(args.profile, compiler, args.out.resolve())
    print(f'KERNEL_SCALE_SUMMARY profile={args.profile} pass={str(report["pass"]).lower()} report={args.out / "report.json"}')
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
