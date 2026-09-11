#!/usr/bin/env python3
'''Compatibility wrapper for the Ouro-native workflow repository gate.

The supported workflow policy lives in tools/repo_gate. This file keeps the
legacy command name, work directory, and report path for callers that have not
migrated yet. It intentionally contains no workflow policy logic.
'''
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional, Sequence

from repo_support import (
    native_gate_compatibility_metadata,
    relative_path,
    native_gate_options,
    run_native_repo_gate,
    write_json_atomic_compact,
)

ROOT = Path(__file__).resolve().parents[1]


def compatibility_report(outcome: Any) -> dict[str, Any]:
    report = dict(outcome.report)
    report['pass'] = outcome.returncode == 0
    report['compatibility_wrapper'] = native_gate_compatibility_metadata(outcome, checkout_root=ROOT)
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    work, report_path, root = native_gate_options(
        argv, checkout_root=ROOT, description=__doc__,
        work_env="OURO_GITHUB_WORKFLOW_GATE_WORK", default_work="_build/github_workflow_gate",
        report_name="github-workflow-gate.json",
    )
    native_out = work / 'native-workflow'
    outcome = run_native_repo_gate(
        checkout_root=ROOT,
        scan_root=root,
        profile='workflow-native',
        native_out=native_out,
    )

    try:
        write_json_atomic_compact(report_path, compatibility_report(outcome))
    except (OSError, UnicodeError) as exc:
        print(f'GITHUB_WORKFLOW_GATE: FAIL cannot write report {report_path}: {exc}', file=sys.stderr)
        return 1

    print(
        'GITHUB_WORKFLOW_GATE: delegated to Ouro-native workflow gate '
        f'status={outcome.returncode} report={relative_path(ROOT, report_path)} '
        f'backend=ouro-native-repo-gate native_report_valid={int(outcome.report_valid)}'
    )
    return outcome.returncode


if __name__ == '__main__':
    raise SystemExit(main())
