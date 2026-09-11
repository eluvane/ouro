#!/usr/bin/env python3
'''Record hosted GitHub project reachability as an explicit host-bound probe.

This script is intentionally separate from scripts/github_project_gate.py. The
local project gate is Ouro-native; hosted repository reachability remains a
reference observation until an Ouro-native hosted API boundary exists.
'''
from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path
from typing import Any, Optional, Sequence

from repo_support import bind_relative_path, parse_json_value, resolve_repo_path, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
rel = bind_relative_path(ROOT, resolve=True)
REPORT_KIND = 'ouro.github-project-hosted-probe.v1'


def probe_hosted_github() -> dict[str, Any]:
    hosted = os.environ.get('OURO_GITHUB_REPO', '').strip()
    command = (
        ['gh', 'repo', 'view', hosted, '--json', 'nameWithOwner,url,visibility']
        if hosted
        else ['gh', 'repo', 'view', '--json', 'nameWithOwner,url,visibility']
    )
    if not (ROOT / '.git').exists() and not hosted:
        return {
            'status': 'SKIP/BLOCKED',
            'command': ' '.join(command),
            'reason': 'not a git checkout and OURO_GITHUB_REPO is unset',
        }
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        return {
            'status': 'SKIP/BLOCKED',
            'command': ' '.join(command),
            'reason': str(exc),
        }
    if result.returncode != 0:
        message = (result.stderr or result.stdout or 'gh repo view failed').strip()
        return {
            'status': 'SKIP/BLOCKED',
            'command': ' '.join(command),
            'reason': message.splitlines()[-1] if message else 'gh repo view failed',
        }
    repository, error = parse_json_value(result.stdout) if result.stdout else ({}, None)
    if error is not None:
        return {
            'status': 'SKIP/BLOCKED',
            'command': ' '.join(command),
            'reason': f'gh returned invalid JSON: {error}',
        }
    if not isinstance(repository, dict):
        return {
            'status': 'SKIP/BLOCKED',
            'command': ' '.join(command),
            'reason': 'gh returned a non-object JSON payload',
        }
    return {
        'status': 'reachable',
        'command': ' '.join(command),
        'repository': repository,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--work',
        default=os.environ.get('OURO_GITHUB_PROJECT_HOSTED_PROBE_WORK', '_build/github_project_hosted_probe'),
    )
    parser.add_argument('--report', default=None)
    parser.add_argument('--require', action='store_true')
    args = parser.parse_args(argv)

    work = resolve_repo_path(ROOT, args.work)
    report_path = resolve_repo_path(ROOT, args.report) if args.report else work / 'github-project-hosted-probe.json'
    hosted = probe_hosted_github()
    ok = hosted.get('status') == 'reachable' or not args.require
    report = {
        'kind': REPORT_KIND,
        'pass': ok,
        'hosted_github': hosted,
        'policy': {
            'scope': 'hosted repository reachability is observed separately from local project-surface validation',
            'mutation': 'this probe does not change hosted settings',
        },
    }
    write_json_atomic(report_path, report)
    print(
        f"GITHUB_PROJECT_HOSTED_PROBE: {'PASS' if ok else 'FAIL'} "
        f"hosted={hosted.get('status')} report={rel(report_path)}"
    )
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
