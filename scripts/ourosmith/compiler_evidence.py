"""Bind the actual CI compiler suite to current sources and executable receipts.

The Ouro suite owns checking and assertions. This adapter validates its process
and build evidence; it neither interprets Core nor reimplements the laws.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

from ci_gate import COMPILER_SHARDS
from repo_support import sha256_file as sha
from ourosmith import ROOT
from ourosmith.native import receipt_for

SUITE_ENTRY = 'tools/test/main.ouro'
PROPERTY_ENTRY = 'tests/compiler_property_tests.ouro'


def property_protocol(text):
    """The complete default scoped/typed run, including non-first mutations."""
    lines = text.splitlines()
    if len(lines) != 6 or lines[:3] != [
            'ok scope shapes count=12 every-rel mutations=28',
            'ok scoped properties count=400 start=0', 'ok typed properties count=400 start=0']:
        return False
    mutations = re.fullmatch(r'ok out-of-scope mutations count=([1-9][0-9]*) nonfirst=([1-9][0-9]*)', lines[3])
    buckets = re.fullmatch(r'ok typed generation buckets=([0-9,]+)', lines[4])
    if not mutations or not buckets or lines[5] != 'ok compiler properties seed=2026 samples=800':
        return False
    values = [int(value) for value in buckets[1].split(',') if value]
    return (len(values) == 25 and ','.join(map(str, values)) == buckets[1]
            and all(value > 0 for value in values) and sum(values) == 400
            and 0 < int(mutations[2]) <= int(mutations[1]) <= 400)


def suite_receipt(log, compiler, shard='all'):
    """Read one complete suite log; all output paths must remain repository-local."""
    lines = log.read_text(encoding='utf-8').splitlines()
    if not lines:
        raise ValueError('compiler suite log is empty')
    terminal = re.fullmatch(r'COMPILER_CHECK_SUITE: PASS rows=([1-9][0-9]*) out=(.+)', lines[-1])
    if terminal is None:
        raise ValueError('compiler suite did not finish with its success protocol')
    names = []
    for line in lines[:-1]:
        match = re.fullmatch(r'COMPILER_CHECK_OK ([a-z][a-z0-9_]*)-run', line)
        if match is None:
            raise ValueError('compiler suite contains an incomplete, failed, or unknown row')
        names.append(match[1])
    if len(names) != int(terminal[1]) or len(names) != len(set(names)):
        raise ValueError('compiler suite rows are missing or duplicated')
    directory = (ROOT / terminal[2]).resolve()
    if not directory.is_relative_to(ROOT / '_build'):
        raise ValueError('compiler suite artifacts escape the local build directory')
    suffix = '.exe' if sys.platform == 'win32' else ''
    runner = directory / ('ouro-test-suite' + suffix)
    runner_receipt, _, _ = receipt_for(runner, SUITE_ENTRY, compiler)
    from ourosmith.host import environment
    from ourosmith.limits import run_limited

    if shard not in ('all', *(f'{index}/{COMPILER_SHARDS}' for index in range(1, COMPILER_SHARDS + 1))):
        raise ValueError('unknown compiler evidence shard')
    command = [str(runner), '--native-suite=compiler-checking', '--list']
    listed = run_limited(command,
                         cwd=ROOT, env=environment(jobs=1), timeout_s=30, memory_mb=3072)
    inventory = listed.stdout.splitlines()
    if (not listed.ok or listed.stderr or not inventory or len(inventory) != len(set(inventory))
            or any(not re.fullmatch(r'tests/[a-z][a-z0-9_]*_tests\.ouro', entry) for entry in inventory)):
        raise ValueError('current Ouro suite inventory is unavailable or malformed')
    entries = inventory
    if shard != 'all':
        selected = run_limited([*command, '--shard=' + shard], cwd=ROOT, env=environment(jobs=1),
                               timeout_s=30, memory_mb=3072)
        entries = selected.stdout.splitlines()
        if (not selected.ok or selected.stderr or not entries
                or entries != inventory[int(shard.split('/')[0]) - 1::COMPILER_SHARDS]):
            raise ValueError('compiler shard differs from its complete inventory partition')
    if names != [Path(entry).stem.removesuffix('_tests') for entry in entries]:
        raise ValueError('executed compiler rows differ from the current Ouro suite inventory')
    artifacts = []
    for name, entry in zip(names, entries, strict=True):
        executable = directory / (name + suffix)
        receipt, _, _ = receipt_for(executable, entry, compiler)
        check, output, error = (directory / (name + extension) for extension in ('.check', '.out', '.err'))
        if check.read_text(encoding='utf-8').splitlines() != ['CHECK_OK'] or error.read_bytes():
            raise ValueError(f'{entry}: unsuccessful strict check or runtime stderr')
        text = output.read_text(encoding='utf-8')
        if not text or any(line.startswith('FAIL ') for line in text.splitlines()):
            raise ValueError(f'{entry}: missing or failed law output')
        if entry == PROPERTY_ENTRY and not property_protocol(text):
            raise ValueError('default scoped and typed property protocol is incomplete')
        artifacts.append({'entry': entry, 'binary_sha256': receipt['binary_sha256'], 'build_key': receipt['key'],
                          'check_sha256': sha(check), 'stdout_sha256': sha(output), 'stderr_sha256': sha(error),
                          'default_properties': entry == PROPERTY_ENTRY and property_protocol(text)})
    if 'tests/compiler_suite_contract_tests.ouro' not in inventory:
        raise ValueError('compiler suite inventory contract was not executed')
    if receipt_for(runner, SUITE_ENTRY, compiler)[0] != runner_receipt:
        raise ValueError('compiler suite runner changed during evidence inspection')
    return {'log_sha256': sha(log), 'runner_sha256': runner_receipt['binary_sha256'],
            'inventory_stdout_sha256': hashlib.sha256(listed.stdout.encode()).hexdigest(),
            'runner_build_key': runner_receipt['key'], 'inventory': inventory, 'shard': shard,
            'artifacts': artifacts}


def ci_compiler_receipt(directory):
    """Only the required, successful CI command can supply compiler-law credit."""
    from ci_gate import REPORT_KIND, gates
    from ourosmith.host import binary
    from repo_support import read_json_value

    directory = Path(directory).resolve()
    summary_path = directory / 'ci/ci-summary.json'
    summary, error = read_json_value(summary_path)
    if (error is not None or not isinstance(summary, dict) or summary.get('kind') != REPORT_KIND
            or summary.get('profile') != 'pr' or summary.get('group') != 'all'):
        raise ValueError('full PR aggregate is missing from compiler evidence')
    expected = [next(gate for gate in gates() if gate.name == f'compiler-checking-{index}'
                     and 'pr' in gate.profiles) for index in range(1, COMPILER_SHARDS + 1)]
    rows = summary.get('gates')
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError('compiler CI gate rows are malformed')
    receipts = []
    for index, gate in enumerate(expected, 1):
        matches = [row for row in rows if row.get('name') == gate.name]
        if len(matches) != 1:
            raise ValueError('compiler CI gate is missing or duplicated')
        row = matches[0]
        if (row.get('blocking') is not True or row.get('status') != 'pass'
                or type(row.get('returncode')) is not int or row['returncode'] != 0 or row.get('command') != gate.cmd):
            raise ValueError('required compiler CI command did not pass')
        log = directory / 'ci' / gate.name / 'gate.log'
        if not isinstance(row.get('log'), str) or (ROOT / row['log']).resolve() != log:
            raise ValueError('compiler CI gate log path differs')
        receipts.append(suite_receipt(log, binary('ouro1'), shard=f'{index}/{COMPILER_SHARDS}'))
    inventory = receipts[0]['inventory']
    if any(receipt['inventory'] != inventory or receipt['runner_build_key'] != receipts[0]['runner_build_key']
           or receipt['runner_sha256'] != receipts[0]['runner_sha256'] for receipt in receipts):
        raise ValueError('compiler shard runners or inventories differ')
    artifacts = [row for receipt in receipts for row in receipt['artifacts']]
    entries = [row['entry'] for row in artifacts]
    if (len(entries) != len(set(entries)) or set(entries) != set(inventory)
            or 'tests/compiler_suite_contract_tests.ouro' not in entries):
        raise ValueError('compiler shard artifacts omit or duplicate current fixtures')
    by_entry = {row['entry']: row for row in artifacts}
    return {'ci_summary_sha256': sha(summary_path), 'shards': receipts,
            'artifacts': [by_entry[entry] for entry in inventory]}


def compiler_strategies(directory):
    receipt = ci_compiler_receipt(directory)
    strategies = {'external/compiler/' + Path(row['entry']).stem for row in receipt['artifacts']}
    if any(row['default_properties'] for row in receipt['artifacts']):
        strategies.add('external/property/scoped-and-typed-laws')
    return strategies
