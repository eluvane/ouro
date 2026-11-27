"""Bind the actual CI compiler suite to current sources and executable receipts.

The Ouro suite owns checking and assertions. This adapter validates its process
and build evidence; it neither interprets Core nor reimplements the laws.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ci_gate import COMPILER_SHARDS, compiler_fixture_rows, compiler_shard_entries
from repo_support import decode_source_text, sha256_bytes
from repo_support import sha256_file as sha
from selfhost_module_cache import cached_import_parser
from ourosmith import ROOT
from ourosmith.native import receipt_for

if TYPE_CHECKING:
    from selfhost_module_cache import ImportBytesParser

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


def suite_receipt(log, compiler, shard='all', *, workspace=None, parse_bytes: ImportBytesParser | None = None):
    """Read one complete suite log; all output paths must remain repository-local."""
    if shard not in ('all', *(f'{index}/{COMPILER_SHARDS}' for index in range(1, COMPILER_SHARDS + 1))):
        raise ValueError('unknown compiler evidence shard')
    root = ROOT if workspace is None else workspace
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
    directory = (root / terminal[2]).resolve()
    if not directory.is_relative_to(root / '_build'):
        raise ValueError('compiler suite artifacts escape the local build directory')
    if workspace is not None and directory != root / '_build' / ('compiler_check_suite_' + shard.split('/')[0]):
        raise ValueError('compiler suite output path differs from its isolated gate')
    suffix = '.exe' if sys.platform == 'win32' else ''
    runner = directory / ('ouro-test-suite' + suffix)
    if workspace is not None and runner.resolve() != runner:
        raise ValueError('compiler suite runner is not an isolated artifact')
    if parse_bytes is None:
        parse_bytes = cached_import_parser()
    runner_receipt, _, runner_sources = receipt_for(runner, SUITE_ENTRY, compiler, parse_bytes=parse_bytes)
    inputs = dict(runner_sources)
    from ourosmith.host import environment
    from ourosmith.limits import run_limited

    env = environment(jobs=1)
    if workspace is not None:
        check = (root / 'scripts/ouro1.sh').as_posix()
        env.update(OURO_ROOT=root.as_posix(), OURO_C_BUILD_DIR=compiler.parent.as_posix(),
                   OURO_BUILD_DIR=(root / '_build').as_posix(), OURO_CACHE_DIR=(root / '_cache/ouro').as_posix(),
                   OURO_TEST_CHECK=check, OURO_HOSTED_COMPILER_WRAPPER=check,
                   OURO_TEST_BUILD=(root / 'scripts/build_tool.sh').as_posix(),
                   OURO_HOSTED_FMT=(compiler.parent / 'ouro-fmt').as_posix())
    command = [str(runner), '--native-suite=compiler-checking', '--list']
    listed = run_limited(command, cwd=root, env=env, timeout_s=30, memory_mb=3072)
    inventory = listed.stdout.splitlines()
    if (not listed.ok or listed.stderr or not inventory
            or len(inventory) != len(set(inventory))):
        raise ValueError('current Ouro suite inventory is unavailable or malformed')
    registered = compiler_fixture_rows(ROOT)
    if inventory != [entry for _, entry in registered]:
        raise ValueError('compiler suite inventory differs from the source registry')
    registered_names = {entry: name for name, entry in registered}
    entries = inventory
    if shard != 'all':
        selected = run_limited([*command, '--shard=' + shard], cwd=root, env=env, timeout_s=30, memory_mb=3072)
        entries = selected.stdout.splitlines()
        if (not selected.ok or selected.stderr or not entries
                or entries != compiler_shard_entries(inventory, int(shard.split('/')[0]))):
            raise ValueError('compiler shard differs from its complete inventory partition')
    if names != [registered_names[entry] for entry in entries]:
        raise ValueError('executed compiler rows differ from the current Ouro suite inventory')
    artifacts = []
    for name, entry in zip(names, entries, strict=True):
        executable = directory / (name + '.exe')
        check, output, error = (directory / (name + extension) for extension in ('.check', '.out', '.err'))
        if workspace is not None and any(path.resolve() != path for path in (executable, check, output, error)):
            raise ValueError(f'{entry}: compiler fixture is not an isolated artifact')
        receipt, _, sources = receipt_for(executable, entry, compiler, parse_bytes=parse_bytes)
        inputs.update(sources)
        check_data = check.read_bytes()
        if decode_source_text(check_data).splitlines() != ['CHECK_OK']:
            raise ValueError(f'{entry}: unsuccessful strict check')
        # The suite owns exit/golden verdicts; runtime streams remain byte evidence.
        default_properties = entry == PROPERTY_ENTRY
        if default_properties:
            output_data = output.read_bytes()
            if not property_protocol(decode_source_text(output_data)):
                raise ValueError('default scoped and typed property protocol is incomplete')
            output_digest = sha256_bytes(output_data)
            del output_data
        else:
            output_digest = sha(output)
        artifacts.append({'entry': entry, 'binary_sha256': receipt['binary_sha256'], 'build_key': receipt['key'],
                          'check_sha256': sha256_bytes(check_data), 'stdout_sha256': output_digest,
                          'stderr_sha256': sha(error),
                          'default_properties': default_properties})
    if 'tests/compiler_suite_contract_tests.ouro' not in inventory:
        raise ValueError('compiler suite inventory contract was not executed')
    if receipt_for(runner, SUITE_ENTRY, compiler, parse_bytes=parse_bytes)[0] != runner_receipt:
        raise ValueError('compiler suite runner changed during evidence inspection')
    if workspace is not None:
        for name, expected in inputs.items():
            source = workspace / name
            if not source.resolve().is_relative_to(workspace) or sha(source) != expected:
                raise ValueError(f'compiler shard source differs from the current receipt: {name}')
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
    registry = gates()
    expected = [next(gate for gate in registry if gate.name == f'compiler-checking-{index}'
                     and 'pr' in gate.profiles) for index in range(1, COMPILER_SHARDS + 1)]
    rows = summary.get('gates')
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError('compiler CI gate rows are malformed')
    receipts = []
    run_root = None
    parse_bytes = cached_import_parser()
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
        shard = f'{index}/{COMPILER_SHARDS}'
        if 'workspace' not in row or row['workspace'] == '.':
            workspace = ROOT
        else:
            value = row['workspace']
            if not isinstance(value, str):
                raise ValueError('compiler CI gate workspace is malformed')
            workspace = ROOT / value
            if (workspace.resolve() != workspace or not workspace.is_dir()
                    or workspace.parent.parent != ROOT / '_build'
                    or not workspace.parent.name.startswith('ci-') or workspace.name != f'compiler-{index}'):
                raise ValueError('compiler CI gate workspace differs from its isolated group')
        expected_root = ROOT if workspace == ROOT else workspace.parent
        if run_root is None:
            run_root = expected_root
        if expected_root != run_root:
            raise ValueError('compiler CI gate workspaces come from different runs')
        if workspace == ROOT:
            receipts.append(suite_receipt(log, binary('ouro1'), shard=shard, parse_bytes=parse_bytes))
        else:
            producer_dir = workspace / '_build/c'
            compiler = binary('ouro1', directory=producer_dir)
            if compiler.parent != producer_dir:
                raise ValueError('compiler CI gate producer escapes its isolated build directory')
            receipts.append(suite_receipt(log, compiler, shard=shard, workspace=workspace, parse_bytes=parse_bytes))
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
