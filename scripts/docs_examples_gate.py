#!/usr/bin/env python3
'''Compatibility wrapper for the Ouro-native documentation repository gate.

Documentation policy lives in tools/repo_gate. This entry point keeps the
legacy command name, work directory, report kind, and report path for callers
that have not migrated yet. It intentionally contains no documentation policy
logic.
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
REPORT_KIND = 'ouro.docs-examples-gate.v2'


def metric_lookup(native: dict[str, Any]) -> dict[str, str]:
    found: dict[str, str] = {}
    gates = native.get('gates', [])
    if not isinstance(gates, list):
        return found
    for gate in gates:
        if not isinstance(gate, dict):
            continue
        metrics = gate.get('metrics', [])
        if not isinstance(metrics, list):
            continue
        for metric in metrics:
            if not isinstance(metric, dict):
                continue
            name = metric.get('name')
            value = metric.get('value')
            if isinstance(name, str):
                found[name] = '' if value is None else str(value)
    return found


def maybe_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    cleaned = value.strip()
    if cleaned in {'', 'null'}:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def legacy_inventory(native: dict[str, Any]) -> dict[str, Any]:
    metrics = metric_lookup(native)
    return {
        'current_markdown': maybe_int(metrics.get('current_markdown')),
        'maintained_markdown': maybe_int(metrics.get('maintained_markdown')),
        'generated_api_markdown': maybe_int(metrics.get('generated_api_markdown')),
        'base_ref': metrics.get('base_ref') or None,
        'base_markdown': maybe_int(metrics.get('base_markdown')),
    }


def legacy_readme_status(native: dict[str, Any]) -> dict[str, Any]:
    issues = native.get('issues', [])
    status = 'synchronized'
    source: Optional[str] = None
    if isinstance(issues, list):
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            reason = str(issue.get('reason', ''))
            if 'no synchronized Ouro example marker' in reason or 'example block is missing' in reason:
                status = 'missing'
            elif 'example source does not exist:' in reason:
                status = 'missing-source'
                source = reason.split(':', 1)[-1].strip()
            elif 'example drifted from ' in reason:
                status = 'drift'
                source = reason.split('example drifted from ', 1)[-1].strip()
    result: dict[str, Any] = {'status': status}
    if source:
        result['source'] = source
    return result


def legacy_report(outcome: NativeGateOutcome) -> dict[str, Any]:
    native = outcome.report
    issues = native.get('issues', [])
    if not isinstance(issues, list):
        issues = []
    return {
        'kind': REPORT_KIND,
        'pass': outcome.returncode == 0,
        'issues': issues,
        'inventory': legacy_inventory(native),
        'readme_example': legacy_readme_status(native),
        'policy': {
            'native': 'repository-owned documentation policy is delegated to tools/repo_gate',
            'compatibility': 'this entry point maps a validated native report into the legacy report path',
            'failure': 'missing, malformed, stale, or inconsistent native evidence is blocking',
        },
        'execution': native_gate_compatibility_metadata(outcome, checkout_root=ROOT),
        'native_profile': 'docs-native',
        'native_report': rel(outcome.report_path),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    work, report_path, root = native_gate_options(
        argv, checkout_root=ROOT, description=__doc__,
        work_env="OURO_DOCS_EXAMPLES_GATE_WORK", default_work="_build/docs_examples_gate",
        report_name="docs-examples-gate.json",
    )
    native_out = work / 'native-docs'
    outcome = run_native_repo_gate(
        checkout_root=ROOT,
        scan_root=root,
        profile='docs-native',
        native_out=native_out,
    )

    try:
        write_json_atomic(report_path, legacy_report(outcome))
    except (OSError, UnicodeError) as exc:
        print(f'DOCS_EXAMPLES_GATE: FAIL cannot write report {report_path}: {exc}', file=sys.stderr)
        return 1

    issues = outcome.report.get('issues', [])
    issue_count = len(issues) if isinstance(issues, list) else 0
    print(
        f"DOCS_EXAMPLES_GATE: {'PASS' if outcome.returncode == 0 else 'FAIL'} "
        f'issues={issue_count} report={rel(report_path)} native={rel(outcome.report_path)} '
        f'backend=ouro-native-repo-gate native_report_valid={int(outcome.report_valid)}'
    )
    return outcome.returncode


if __name__ == '__main__':
    raise SystemExit(main())
