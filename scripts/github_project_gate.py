#!/usr/bin/env python3
'''Compatibility wrapper for the Ouro-native project-surface repository gate.

Local repository project policy lives in tools/repo_gate. This entry point keeps
the legacy command name, work directory, report kind, and report path for callers
that have not migrated yet. Hosted repository probing is tracked separately as a
host-bound reference probe.
'''
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional, Sequence

from repo_support import (
    NativeGateOutcome,
    bind_relative_path,
    native_gate_compatibility_metadata,
    native_gate_options,
    run_native_repo_gate,
    write_json_atomic,
)

ROOT = Path(__file__).resolve().parents[1]
rel = bind_relative_path(ROOT, resolve=True)
REPORT_KIND = 'ouro.github-project-gate.v3'


def version_metrics(native: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    gates = native.get('gates', [])
    if not isinstance(gates, list):
        return result
    for gate in gates:
        if not isinstance(gate, dict) or gate.get('name') != 'version-baseline-parity':
            continue
        metrics = gate.get('metrics', [])
        if not isinstance(metrics, list):
            continue
        for metric in metrics:
            if isinstance(metric, dict) and isinstance(metric.get('name'), str):
                result[str(metric['name'])] = '' if metric.get('value') is None else str(metric['value'])
    return result


def legacy_report(outcome: NativeGateOutcome) -> dict[str, Any]:
    native = outcome.report
    issues = native.get('issues', [])
    if not isinstance(issues, list):
        issues = []
    return {
        'kind': REPORT_KIND,
        'pass': outcome.returncode == 0,
        'required_files': [],
        'retired_paths': [],
        'issues': issues,
        'hosted_github': {
            'status': 'host-bound',
            'reason': 'hosted repository reachability is outside this local compatibility wrapper',
        },
        'versions': version_metrics(native),
        'policy': {
            'native': 'repository-owned project-surface policy is delegated to tools/repo_gate',
            'compatibility': 'this entry point maps a validated native report into the legacy report path',
            'failure': 'missing, malformed, stale, or inconsistent native evidence is blocking',
        },
        'execution': native_gate_compatibility_metadata(outcome, checkout_root=ROOT),
        'native_profile': 'project-native',
        'native_report': rel(outcome.report_path),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    work, report_path, root = native_gate_options(
        argv, checkout_root=ROOT, description=__doc__,
        work_env="OURO_GITHUB_PROJECT_GATE_WORK", default_work="_build/github_project_gate",
        report_name="github-project-gate.json",
    )
    native_out = work / 'native-project'
    outcome = run_native_repo_gate(
        checkout_root=ROOT,
        scan_root=root,
        profile='project-native',
        native_out=native_out,
    )

    try:
        write_json_atomic(report_path, legacy_report(outcome))
    except (OSError, UnicodeError) as exc:
        print(f'GITHUB_PROJECT_GATE: FAIL cannot write report {report_path}: {exc}', file=sys.stderr)
        return 1

    issues = outcome.report.get('issues', [])
    issue_count = len(issues) if isinstance(issues, list) else 0
    print(
        f"GITHUB_PROJECT_GATE: {'PASS' if outcome.returncode == 0 else 'FAIL'} "
        f'issues={issue_count} hosted=host-bound report={rel(report_path)} '
        f'native={rel(outcome.report_path)} backend=ouro-native-repo-gate '
        f'native_report_valid={int(outcome.report_valid)}'
    )
    return outcome.returncode


if __name__ == '__main__':
    raise SystemExit(main())
