#!/usr/bin/env python3
"""Run canonical Ouro checking, boundary policy and cache-mode hardening."""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

import kernel_profile as profile
import ouro_build
from ourosmith.host import environment
from repo_support import write_json_atomic

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', type=Path, help='default: configured c_build_dir/ouro1')
    parser.add_argument('--repo-gate', type=Path, help='existing executable with a current build receipt')
    parser.add_argument('--out', type=Path, default=ROOT / '_build/kernel')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = out / ('h-' + uuid.uuid4().hex[:8])
    work.mkdir()
    report = {'kind': 'ouro.kernel-hardening-report.v3', 'pass': False,
              'work': profile.relative(work), 'steps': []}
    try:
        compiler = args.compiler or ouro_build.load_config(argparse.Namespace()).path('c_build_dir') / 'ouro1'
        compiler = compiler.resolve()
        if sys.platform == 'win32' and compiler.suffix != '.exe' and Path(str(compiler) + '.exe').is_file():
            compiler = Path(str(compiler) + '.exe')
        if not compiler.is_file():
            raise ValueError(f'compiler unavailable: {compiler}; build the configured compiler or pass --compiler')
        budgets_path = ROOT / 'quality/kernel_budgets.json'
        budgets = profile.load_json(budgets_path)
        profile.validate_budgets(budgets)
        limits = budgets['orchestration']
        env = environment(jobs=1, build=True)
        env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8', OURO_CCACHE='disabled')

        def run(command: list[str], name: str, timeout: float = 120) -> None:
            result = profile.execute(command, work, name, env, timeout, limits['memory_limit_mib'])
            report['steps'].append({'name': name, **result})
            print(result['stdout'], end='', flush=True)
            print(result['stderr'], end='', file=sys.stderr, flush=True)
            if result['status'] != 'ok' or result['returncode'] != 0:
                raise ValueError(f'{name}: status={result["status"]} exit={result["returncode"]}')

        run([sys.executable, '-B', 'scripts/kernel_profile_test.py'], 'profile-policy-tests')

        repo_gate = args.repo_gate.resolve() if args.repo_gate else work / ('ouro-repo-gate.exe' if sys.platform == 'win32' else 'ouro-repo-gate')
        if args.repo_gate is None:
            run([sys.executable, '-B', 'scripts/native_tool_build.py', profile.BOUNDARY_ENTRY, str(repo_gate),
                 '--compiler', str(compiler), '--fuel', '16000', '--jobs', '1',
                 '--build-dir', str(work / 'build'), '--cache-dir', str(out / 'cache'), '--cache',
                 '--opt-level', 'O0', '--ccache', 'disabled'],
                'build-boundary', limits['build_timeout_s'])
        baseline_path = ROOT / 'quality/kernel_baseline.json'
        measured = profile.run_profile(compiler=compiler, boundary=repo_gate, out=work / 'profile',
                                       budget_path=budgets_path,
                                       baseline=profile.load_json(baseline_path) if baseline_path.is_file() else None)
        report['canonical_profile'] = profile.relative(work / 'profile/kernel-profile.json')
        report['canonical_checks'] = measured['budget_status']
        report['fixtures'] = measured['fixtures']
        report['pass'] = measured['pass'] is True
        if not report['pass']:
            raise ValueError('canonical compiler profile')
    except (OSError, ValueError, KeyError, TypeError) as error:
        report['error'] = str(error)
        print('KERNEL_HARDENING_SUITE: FAIL', error, file=sys.stderr, flush=True)
    finally:
        write_json_atomic(out / 'kernel-hardening.json', report)
    if report['pass']:
        print('KERNEL_HARDENING_SUITE: PASS', f'canonical_laws={report["fixtures"]}', flush=True)
    return 0 if report['pass'] else 1


if __name__ == "__main__":
    raise SystemExit(main())
