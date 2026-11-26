"""Materialize native selftest inputs from the independent Smith specifications."""
from __future__ import annotations

import json
import os
import stat
import tempfile
from bisect import bisect_left
from pathlib import Path
from typing import TYPE_CHECKING

from ourosmith import ROOT
from ourosmith.surface.doc_contract import program as documentation
from ourosmith.surface.gen import generate, program
from ourosmith.surface.lint_contracts import cases as lint_programs
from ourosmith.surface.mutate import mutations
from ourosmith.surface.text_contracts import cases
from repo_support import hash_json, sha256_bytes, write_json_atomic

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

GROUPS = ("fmt", "fix", "doc", "lint", "manifest", "runtime", "test", "lsp", "security")
_MANIFEST_BATCH_ROWS = 29
# An IO import adds a large stdlib closure to each check.
_MANIFEST_IO_ROW_COST = 8
MANIFEST_BATCH_MEMORY_MIB = 3072


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")


def prepare(group, out, seed, *, stable=False, manifest_costs: dict[str, int] | None = None,
            manifest_prefixes: tuple[str, ...] | None = None):
    if group not in GROUPS or seed < 0:
        raise ValueError("known selftest group and nonnegative seed required")
    if stable and group not in {"runtime", "test"}:
        raise ValueError("stable fixture inputs require group runtime or test")
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if stable:
        return _stable_compiled_inputs(group, out, seed)
    root = Path(tempfile.mkdtemp(prefix=group + "-", dir=out))
    if group == "manifest":
        prepare_manifest(root, seed, row_costs=manifest_costs, prefixes=manifest_prefixes)
    else:
        _write_inputs(group, root, seed)
    return root


def _stable_compiled_inputs(group, out, seed):
    expected = {name: text.encode("utf-8") for name, text in _compiled_fixture_files(group, out, seed).items()}
    hashes = {name: sha256_bytes(data) for name, data in expected.items()}
    target = out / (group + "-" + hash_json([seed, hashes])[:16])
    if not os.path.lexists(target):
        with tempfile.TemporaryDirectory(prefix=group + "-", dir=out) as temporary:
            staging = Path(temporary)
            for name, data in expected.items():
                (staging / name).write_bytes(data)
            try:
                staging.rename(target)
            except OSError:
                # A concurrent publisher may have installed the same complete directory.
                if not os.path.lexists(target):
                    raise
    directory = target.lstat()
    if (not stat.S_ISDIR(directory.st_mode)
            or getattr(directory, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            or {file.name for file in target.iterdir()} != expected.keys()):
        raise ValueError(f"invalid stable fixture directory: {target}")
    for name, data in expected.items():
        file = target / name
        info = file.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                or info.st_size != len(data) or file.read_bytes() != data):
            raise ValueError(f"invalid stable fixture file: {file}")
    return target


def _write_inputs(group, root, seed):
    if group in {"fmt", "fix"}:
        names = {"fmt-clean": "clean", "fmt-layout": "messy", "fmt-syntax": "syntax_keep"}
        for case in cases(seed):
            if case.tool != group or (group == "fmt" and case.name not in names):
                continue
            name = names[case.name] if group == "fmt" else case.name
            write(root / (name + ".in"), case.source)
            write(root / (name + ".golden"), case.expected)
    elif group == "doc":
        dependency = os.path.relpath(ROOT / "std/prelude.ouro", root).replace("\\", "/")
        source, expected, _signature, _prose = documentation(seed, dependency)
        path = root / "sample.ouro"
        write(path, source)
        write(root / "sample.golden.md", "# " + path.as_posix() + "\n\n" + expected)
    elif group == "lint":
        for mutation in mutations(seed):
            if mutation.tool == "lint":
                write(root / "bad" / (mutation.name + ".ouro"), mutation.source)
        padding = "-- " + "x" * 15000 + "\n"
        declaration = "inductive Value : Type := | Keep : Value;\n"
        write(root / "bad" / "large-source.ouro", padding + declaration
              + "def main (value : Value) : Value := missing;\n")
        write(root / "good" / "large-source.ouro", padding + declaration
              + "def main (value : Value) : Value := value;\n")
        write(root / "bad" / "unsupported-mutual.ouro", "mutual\n" + declaration + "end\n")
        write(root / "good" / "_build" / "ignored.ouro", declaration
              + "def main (value : Value) : Value := missing;\n")
        for index in range(5):
            write(root / "good" / f"expression-{index}.ouro", program(generate(seed + index, 3)))
        for name, source, dependencies in lint_programs(seed):
            write(root / "good" / name / "main.ouro", source)
            for filename, text in dependencies:
                write(root / "good" / name / filename, text)
    elif group in {"runtime", "test"}:
        _write_fixture_files(root, _compiled_fixture_files(group, root.parent, seed))
    elif group == "lsp":
        dependency = os.path.relpath(ROOT / "std/prelude.ouro", root).replace("\\", "/")
        imports = f'import "{dependency}";\n'
        source = "-- @entry widget\n" + "\n" * (1 + seed % 5) + imports
        source += f'\n-- Doubles a natural.\ndef widget (n : Nat)\n    : Nat\n    := add n n;\n\ndef widget_zero : Nat := widget {seed % 5};\n'
        write(root / "sample.ouro", source)
        write(root / "messy.ouro", "-- @entry messy\n\n" + imports + "\ndef messy : Nat := add (S Z) Z;   \n")
    elif group == "security":
        write(root / "id.ouro", program(generate(seed, 2)))
        write(root / "other.ouro", program(generate(seed + 1, 2)))
        for mutation in mutations(seed):
            if ((mutation.name.startswith("lex-") and mutation.fuel != 0)
                    or mutation.name in {"parse-missing-colon", "record-malformed"}):
                write(root / (mutation.name + ".ouro"), mutation.source)


def _fixture_import(root: Path, name: str) -> str:
    return os.path.relpath(ROOT / name, root).replace("\\", "/")


def _write_fixture_files(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        write(root / name, text)


def _compiled_fixture_files(group: str, parent: Path, seed: int) -> dict[str, str]:
    # Every fixture tree is a new child of parent. Its imports start one level up.
    def dependency(name: str) -> str:
        return "../" + _fixture_import(parent, name)

    if group == "test":
        return {**_library_files("helpers", seed, dependency), **_test_runner_files(seed, dependency)}
    files = {}
    for family in ("strings", "data", "crypto"):
        files.update(_library_files(family, seed, dependency))
    files["io_prims.ouro"] = f'''import "{dependency("std/processx.ouro")}";
-- @entry main
def main : IO Unit :=
  do let! good := proc_exec "printf" (["shell-{seed}"] : List String);
     let! bad := proc_exec "sh" (["-c", "exit 2"] : List String);
     println (proc_stdout good);
     println (show_nat (proc_code good));
     println (show_nat (proc_code bad));
     exit 0
'''
    files["io_prims.golden"] = f"shell-{seed}\n0\n2\n"
    return files


def prepare_manifest(root, seed, *, row_costs: dict[str, int] | None = None,
                     prefixes: tuple[str, ...] | None = None):
    from ourosmith.ergonomics_inputs import prepare_manifest as add_ergonomics
    from ourosmith.surface.forms import programs
    from ourosmith.surface.parity import inputs
    from selfhost_module_cache import quoted_import_targets

    rows = []
    io_module = (ROOT / "std/io.ouro").as_posix()

    def add(name, source, expected, diagnostic, dependencies=()):
        # The batch planner checks coverage against the full manifest.
        rows.append(f"{name}\t{name}/main.ouro\tcheck\t{expected}\t0\t{diagnostic}\n")
        if prefixes is not None and not name.startswith(prefixes):
            return
        main = root / name / "main.ouro"
        write(main, source)
        for filename, text in dependencies:
            write(root / name / filename, text)
        if row_costs is not None and "std/io.ouro" in source:
            try:
                imports = quoted_import_targets(source, main.as_posix())
            except ValueError:
                # The native runner diagnoses malformed fixtures.
                return
            if io_module in imports:
                row_costs[name] = _MANIFEST_IO_ROW_COST

    for name, source, _value, _units in programs(seed):
        add(("REC." if name == "record" else "ERGO.") + name, source, "pass", "CHECK_OK")
    for case in inputs(seed):
        if case["name"].startswith("imports"):
            name = "qualified" if case["name"] == "imports" else case["name"][8:]
            add("IMP." + name, case["source"], "pass", "CHECK_OK", case["dependencies"])
    for mutation in mutations(seed):
        if mutation.tool != "check" or mutation.fuel != 999999 or len(mutation.diagnostics) != 1:
            continue
        prefix = "IMP." if mutation.name.startswith("import-") else "REC." if mutation.name.startswith("record-") else "ERGO." if mutation.name.startswith(("pipe-", "list-", "do-", "named-hole")) else "CHECK."
        add(prefix + mutation.name, mutation.source, "fail", mutation.diagnostics[0], mutation.dependencies)
    add_ergonomics(root, add)
    write(root / "manifest.tsv", "".join(rows))
    # The native control-plane selftest retains malformed table contracts and
    # points their safe relative paths at generated programs.
    for filename, contents in {
        "valid.tsv": "SELF.G\tIMP.qualified/main.ouro\tcheck\tpass\t0\tCHECK_OK\nSELF.B\tIMP.import-malformed/main.ouro\tcheck\tfail\t0\tOURO-IMP-001\n",
        "malformed.tsv": "BAD\tmissing.ouro\tcheck\tpass\t0\n",
        "duplicate.tsv": "DUP\tIMP.qualified/main.ouro\tcheck\tpass\t0\t\n" * 2,
        "unsafe.tsv": "UNSAFE\t../outside.ouro\tcheck\tpass\t0\t\n",
        "unsupported.tsv": "UNSUPPORTED\tIMP.qualified/main.ouro\tlint\tpass\t0\t\n",
        "missing.tsv": "MISSING\tnot-present.ouro\tcheck\tpass\t0\t\n",
    }.items():
        write(root / filename, contents)


def _library_files(family: str, seed: int, dependency: Callable[[str], str]) -> dict[str, str]:
    from ourosmith.surface.library import FAMILIES

    generate_rows, modules = FAMILIES[family]
    rows = list(generate_rows(seed))
    imports = "".join(f'import "{dependency(name)}";\n'
                      for name in ("std/io.ouro", "std/format.ouro", *modules))
    if family == "crypto":
        declarations = "".join(f"def observed{i} : String := {expression};\n"
                               for i, (expression, _value) in enumerate(rows))
        actions = "".join(f"     println observed{i};\n" for i in range(len(rows)))
    else:
        declarations = ""
        actions = "".join(f"     println ({expression});\n" for expression, _value in rows)
    source = imports + declarations + "\n-- @entry main\ndef main : IO Unit :=\n  do\n"
    source += actions + "     exit 0\n"
    return {family + ".ouro": source,
            family + ".golden": "".join(value + "\n" for _expression, value in rows)}


def prepare_library(root, family, seed):
    _write_fixture_files(root, _library_files(family, seed, lambda name: _fixture_import(root, name)))


def _test_runner_files(seed: int, dependency: Callable[[str], str]) -> dict[str, str]:
    files = {}
    test_module = dependency("std/test.ouro")
    for failing in (False, True):
        names = [f"case{seed}-{i}" for i in range(2 + seed % 4)]
        entries = [f'test_ok "{name}"' for name in names]
        expected = "".join("ok " + name + "\n" for name in names)
        if failing:
            entries.append('test_fail "broken" "intentional"')
            expected += "FAIL broken intentional\n"
        name = "failure" if failing else "success"
        files[name + ".ouro"] = (f'import "{test_module}";\n-- @entry main\ndef main : IO Unit :=\n  test_run (['
                                 + ", ".join(entries) + "] : List Test)\n")
        files[name + ".golden"] = expected
    compiler = dependency("compiler/file_elab.ouro")
    io_module = dependency("std/io.ouro")
    present, absent = 1 + seed % 5, 10 + seed % 7
    source = f'''import "{compiler}";
import "{io_module}";
def selection_rejected : Bool :=
  match check_file_selected 32 ([{absent}] : List Nat)
    ([FAxiom {present} (CSort Z)] : List FileItem) with
  | FRErr code detail => andb (eqNat code 6) (eqNat detail {absent})
  | FROk _ => False
  end;
-- @entry main
def main : IO Unit :=
  match selection_rejected with | True => exit 0 | False => exit 1 end
'''
    files["selected_declaration.ouro"] = source
    files["selected_declaration.golden"] = ""
    return files


def prepare_test_runner(root, seed):
    _write_fixture_files(root, _test_runner_files(seed, lambda name: _fixture_import(root, name)))


def run(args):
    print(prepare(args.group, args.out, args.seed, stable=getattr(args, "stable", False)).as_posix())
    return 0


def _manifest_prefixes(prefix: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in prefix.split(",") if part.strip())


def manifest_batches(text, prefix, *, row_costs: Mapping[str, int] | None = None):
    prefixes = _manifest_prefixes(prefix)
    ids = sorted({line.split("\t", 1)[0].strip() for line in text.splitlines()
                  if line.strip() and not line.lstrip().startswith("#")})
    selected = [name for name in ids if name.startswith(prefixes)]
    if not selected:
        raise ValueError("manifest batch plan selects no rows")

    def matching_ids(selectors):
        actual = set()
        for selector in selectors:
            index = bisect_left(ids, selector)
            while index < len(ids) and ids[index].startswith(selector):
                actual.add(ids[index])
                index += 1
        return actual

    groups = {}
    marker = "ERGO.expansion-"
    for name in selected:
        key = name[:len(marker) + 1] if name.startswith(marker) else "original"
        groups.setdefault(key, []).append(name)
    batches, covered = [], set()
    for key, names in sorted(groups.items()):
        chunks = [names[index:index + _MANIFEST_BATCH_ROWS]
                  for index in range(0, len(names), _MANIFEST_BATCH_ROWS)]
        for chunk in chunks:
            selectors = [key] if key != "original" and len(names) <= _MANIFEST_BATCH_ROWS else chunk
            actual = matching_ids(selectors)
            if actual != set(chunk) or covered.intersection(actual):
                raise ValueError("manifest batch prefixes overlap or select unexpected rows")
            covered.update(actual)
            batches.append((selectors, chunk))
    if covered != set(selected):
        raise ValueError("manifest batch coverage differs from the original selection")
    if not row_costs:
        return batches

    balanced = []
    for selectors, names in batches:
        if any("," in name or "\0" in name for name in names):
            balanced.append((selectors, names))
            continue
        chunks = [[]]
        cost = 0
        for name in names:
            row_cost = row_costs.get(name, 1)
            if chunks[-1] and cost + row_cost > _MANIFEST_BATCH_ROWS:
                chunks.append([])
                cost = 0
            chunks[-1].append(name)
            cost += row_cost
        # The native selectors use prefixes, including when given full IDs.
        if len(chunks) > 1 and all(matching_ids(chunk) == set(chunk) for chunk in chunks):
            balanced.extend((chunk, chunk) for chunk in chunks)
        else:
            balanced.append((selectors, names))
    return balanced


def manifest_batch_report(directory, manifest, label, prefixes, ids):
    report = json.loads((directory / "manifest-report.json").read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError("native manifest report must be a JSON object")
    expected = {"kind": "ouro.test-manifest-report.v1", "version": "1", "suite": label,
                "manifest": manifest.as_posix(), "root": manifest.parent.as_posix(),
                "out": directory.as_posix(), "prefixes": prefixes, "rows": len(ids)}
    if any(report.get(key) != value for key, value in expected.items()):
        raise ValueError("native manifest report provenance or row count differs")
    results = report["results"]
    reported = [row["id"] for row in results]
    rows = [line.split("|", 1)[0] for line in
            (directory / "rows.tsv").read_text(encoding="utf-8").splitlines() if line]
    if len(reported) != len(ids) or set(reported) != set(ids) or rows != reported:
        raise ValueError("native manifest report has missing, duplicate or unexpected ids")
    if any(row["status"] not in {"pass", "fail"} for row in results):
        raise ValueError("native manifest report has an unknown result status")
    failures = sum(row["status"] == "fail" for row in results)
    if type(report.get("rows")) is not int or type(report.get("failures")) is not int:
        raise ValueError("native manifest report counts are not integers")
    if report["failures"] != failures or report["pass"] is not (failures == 0):
        raise ValueError("native manifest report status disagrees with its results")
    return reported, report["pass"]


def run_manifest(args):
    from local_scheduler import Task, available_memory_mib, run_tasks
    from ourosmith.host import binary, ensure_tools, environment, job_count, tool_entry
    from ourosmith.limits import run_limited
    from ourosmith.native import receipt_for
    from selfhost_module_cache import cached_import_parser

    if args.seed < 0:
        raise ValueError("nonnegative seed required")
    out = Path(args.out).resolve()
    report_path = out / "manifest-batches.json"

    def write_failed_report(*, selected_ids=(), scheduler=None, toolchain_error="") -> None:
        write_json_atomic(report_path, {
            "kind": "ouro.smith-manifest-batches.v1", "pass": False, "selected_ids": list(selected_ids),
            "reported_ids": [], "batches": [], "scheduler": {} if scheduler is None else scheduler,
            "toolchain_error": toolchain_error,
        })

    def unavailable(reason: str) -> int:
        print("OURO_SMITH: manifest unavailable: " + reason)
        write_failed_report(toolchain_error=reason)
        return 1

    try:
        reason = ensure_tools(out / "build", required=("collect", "test"))
    except OSError as error:
        write_failed_report(toolchain_error=str(error))
        raise
    if reason:
        return unavailable(reason)
    try:
        compiler, collector, runner = (binary(name) for name in ("ouro1", "ouro-collect", "ouro-test"))
        parse_bytes = cached_import_parser()

        def verify_tools():
            receipts = [receipt_for(path, tool_entry(tool), compiler, parse_bytes=parse_bytes)[0]
                        for tool, path in (("collect", collector), ("test", runner))]
            return [(receipt["key"], receipt["binary_sha256"]) for receipt in receipts]

        tools_before = verify_tools()
    except (OSError, ValueError) as error:
        return unavailable(str(error))
    row_costs: dict[str, int] = {}
    fixtures = prepare("manifest", out / "inputs", args.seed, manifest_costs=row_costs,
                       manifest_prefixes=_manifest_prefixes(args.prefix))
    manifest = fixtures / "manifest.tsv"
    master = manifest.read_bytes()
    batches = manifest_batches(master.decode("utf-8"), args.prefix, row_costs=row_costs)
    selected = [name for _prefixes, ids in batches for name in ids]
    pinned = dict(environment(jobs=1, build=True), OURO1_COMPILER=compiler.as_posix(),
                  OURO_PREPARED_COLLECTOR=collector.as_posix())
    tasks = [Task(str(index), max_jobs=1, memory_mib=MANIFEST_BATCH_MEMORY_MIB)
             for index in range(len(batches))]

    def run_batch(task, allocation):
        index = int(task.name)
        prefixes, ids = batches[index]
        directory = out / "native" / fixtures.name / f"batch-{index + 1:02d}"
        result = run_limited([runner.as_posix(), "--manifest=" + manifest.as_posix(),
                              "--prefix=" + ",".join(prefixes), "--out=" + directory.as_posix(),
                              "--suite-label=" + args.label], cwd=ROOT, env={**pinned, **allocation.environment()},
                             timeout_s=300, memory_mb=allocation.memory_mib)
        log = result.stdout + result.stderr
        write(directory / "gate.log", log)
        batch_ids, issue, native_pass = [], "", False
        try:
            batch_ids, native_pass = manifest_batch_report(directory, manifest, args.label, prefixes, ids)
        except (OSError, ValueError, KeyError, TypeError) as error:
            issue = str(error)
        try:
            if manifest.read_bytes() != master:
                issue = "master manifest bytes changed during native execution"
        except OSError as error:
            issue = "master manifest unavailable after native execution: " + str(error)
        record = {"prefixes": prefixes, "ids": ids, "report": (directory / "manifest-report.json").as_posix(),
                  "status": result.classify(), "returncode": result.returncode,
                  "elapsed_s": result.elapsed_s, "native_pass": native_pass,
                  "pass": result.ok and native_pass and not issue, "error": issue}
        return record, batch_ids, log

    launch_order = sorted(tasks,
                          key=lambda task: -sum(row_costs.get(name, 0) for name in batches[int(task.name)][1]))
    jobs = job_count()
    memory_mib = available_memory_mib(minimum_mib=MANIFEST_BATCH_MEMORY_MIB)
    try:
        results, scheduler = run_tasks(launch_order, jobs=jobs, memory_mib=memory_mib, run=run_batch)
    except ValueError as error:
        if memory_mib is not None and memory_mib < MANIFEST_BATCH_MEMORY_MIB:
            # The scheduler validates all reservations before a batch can start.
            write_failed_report(selected_ids=selected, scheduler={
                "jobs": jobs, "memory_mib": memory_mib, "peak_tasks": 0, "peak_jobs": 0, "peak_memory_mib": 0,
                "error": str(error),
            })
        raise
    records, reported, logs = [], [], []
    for index, task in enumerate(tasks, 1):
        record, batch_ids, log = results[task.name]
        records.append(record)
        reported.extend(batch_ids)
        logs.append(log)
        print(log, end="")
        if not record["pass"]:
            issue = record["error"]
            print(f"OURO_SMITH: manifest batch {index} {record['status']} exit={record['returncode']}"
                  + (": " + issue if issue else ""))
    toolchain_error = ""
    try:
        if verify_tools() != tools_before:
            raise ValueError("verified toolchain differs from preparation")
    except (OSError, ValueError) as error:
        toolchain_error = str(error)
        print("OURO_SMITH: manifest toolchain changed during execution: " + toolchain_error)
    passed = (not toolchain_error and all(record["pass"] for record in records)
              and len(reported) == len(selected) and set(reported) == set(selected))
    write(out / "gate.log", "".join(logs))
    write(report_path, json.dumps({"kind": "ouro.smith-manifest-batches.v1", "pass": passed,
          "selected_ids": selected, "reported_ids": reported, "batches": records, "scheduler": scheduler,
          "toolchain_error": toolchain_error}, indent=2) + "\n")
    print(args.label + (": PASS" if passed else ": FAIL") + " rows=" + str(len(reported))
          + " expected=" + str(len(selected)) + " out=" + (out / "native").as_posix())
    return 0 if passed else 1
