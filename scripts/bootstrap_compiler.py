#!/usr/bin/env python3
"""Build a current C-hosted compiler from separately pinned historical inputs.

This host driver freezes bytes, invokes Ouro, compares complete generated C and
publishes the checked successor. It does not interpret or accept Ouro programs.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import sysconfig
import tempfile
import threading
import time

import bootstrap_historical
import bootstrap_inputs
import compact_source
import frontend_regen as frontend
import repo_support
from local_scheduler import MEMORY_ENV, Allocation, positive_integer
from ourosmith.limits import clean_env, run_limited
from repo_support import configure_native_stack, hash_json, memory_aware_jobs, read_json_object_or_none, sha256_file, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
KIND = "ouro.current-c-bootstrap.v1"
FUEL = "999999"
MEMORY_MIB = 3072
WORKER_MEMORY_MIB = 1024
COMPILE_WORKER_MEMORY_MIB = 512
MEMORY_RESERVE_MIB = 1024
TIMEOUT_S = 900
SINGLE_COMMAND = Allocation(1, MEMORY_MIB)
LOCAL_CACHE_ENV = "OURO_CI_BOOTSTRAP_CACHE"
C_TOOLCHAIN_ENV_KEYS = ("CPATH", "C_INCLUDE_PATH", "LIBRARY_PATH", "SDKROOT",
                        "MACOSX_DEPLOYMENT_TARGET", "SOURCE_DATE_EPOCH")
CURRENT_EVIDENCE = ("report.json", "inputs.json",
                    *(f"out/{phase}/{name}" for phase in ("p1", "p2") for name in ("driver_u.c", "backend_u.c")))
HISTORICAL_HELPERS = (
    "scripts/bootstrap_compiler.py", "scripts/bootstrap_historical.py", "scripts/bootstrap_inputs.py", "scripts/compact_source.py", "scripts/ouro_build.py",
    "scripts/generated_c_shards.py", "scripts/frontend_regen.py", "scripts/selfhost_module_cache.py",
    "scripts/scoped_host_exports.py", "scripts/scoped_host_export_routes.py",
    "scripts/scoped_host_export_consumers.py", "scripts/structural_quality_legacy.py",
    "scripts/pack_frontend.py", "scripts/emit_frontend.sh", "scripts/stage_loop.py", "scripts/stage_loop.sh",
    "scripts/repo_support.py", "scripts/local_scheduler.py", "scripts/ouro_seal.py", "scripts/build_tool.sh",
    "scripts/python.sh", "scripts/ourosmith/__init__.py", "scripts/ourosmith/limits.py",
    "scripts/ourosmith/windows_job.py", "scripts/ourosmith/exec_child.py", "Ouro.seal",
)
HELPERS = (*HISTORICAL_HELPERS, "scripts/native_tool_build.py")
RUNTIME = (
    "runtime/bootstrap.c", "runtime/frontend_link.c", "runtime/ouro_rt.c", "runtime/ouro_rt.h",
    "runtime/ouro_host_values.h", "runtime/ouro_io.c", "runtime/ouro_io.h", "runtime/ouro_prog_main.c",
)
ACCEPTANCE_ROOTS = ("std/prelude.ouro", "std/data.ouro", "tools/collect.ouro", "tests/compiler_abi_tests.ouro")
ABI_STDOUT = """PASS lexer/parser/resolver share declarations and intern state
PASS closed checked parser retains private metadata and AST projection
PASS private declaration metadata keeps its parsed member identity
PASS private effect metadata includes its operation
PASS lexer malformed result crosses parser callback
PASS lexer exhaustion crosses parser callback
PASS parser error crosses unit callback
PASS resolver error retains code and missing path
PASS 255 ordinary declarations retain the complete closure
PASS 256 ordinary declarations use only graph fuel
PASS large root and imported unit use only graph fuel
PASS interleaved imports retain dependency order and diamond deduplication
PASS zero graph fuel retains the entry path
PASS exhausted graph fuel retains the next import path
PASS exhausted nested graph retains the next import path
PASS graph cycle retains code and repeated path
PASS missing graph unit retains code and missing path
PASS compiler result retains named core
PASS checked emission retains exact bodies and requested order
PASS checked emission retains first definitions and ignores metadata
PASS checked emission rejects missing and bodyless declarations
PASS compiler error retains code and detail
PASS lower environment preserves constructor and hint fields
PASS import preprocessing retains registry values
PASS alias masking preserves byte offsets and qualified markers
PASS raw import alias preserves bytes and decoded module path
PASS record callback retains nested record model values
PASS record callback carries compiler-owned alias metadata
PASS text-only record wrapper cannot drop required alias metadata
PASS preprocessors share successful source value
PASS preprocessor error crosses pipeline callback
PASS checked erasure resolves a global universe alias
PASS checked erasure resolves a local universe alias
PASS checked erasure keeps Nat alias data binders
PASS checked erasure respects local universe alias shadowing
PASS checked erasure drops beta computed type arguments
PASS checked erasure drops let computed type arguments
PASS checked erasure drops closed case computed type arguments
PASS checked erasure retains beta computed data arguments
PASS checked erasure retains let computed data arguments
PASS checked erasure retains polymorphic functions as values
PASS checked erasure reports exhausted preparation
PASS checked erasure reports an unsupported residual type computation
PASS checked erasure resolves type cases controlled by local data
PASS checked erasure keeps repeated runtime lets without expansion
PASS checked erasure drops repeated type lets without expansion
PASS checked erasure bounds deferred type expansion
PASS path-only DFS matches full closure order across diamond and duplicate edges
PASS path-only DFS keeps first duplicate unit lookup
PASS path-only DFS does not visit unreachable missing or cyclic units
PASS path-only DFS retains missing entry and dependency details
PASS path-only DFS retains self and nested cycle details
PASS path-only DFS preserves the first missing or cyclic sibling failure
PASS path-only DFS retains exact graph fuel transitions
PASS path-only visit checks fuel then imported paths before stack and lookup
PASS path-only import mode preserves nonimport and empty-mode fuel
PASS path-only DFS spends no extra graph fuel on 256 local declarations
PASS path-only DFS keeps root foreign and unreachable owner closures separate
PASS plain parsed import retains full-resolver path projection
PASS qualified parsed import retains full-resolver path projection
PASS selected imports and local opens retain full-resolver path projection
PASS successful path projection does not authorize a private selected member
COMPILER_ABI: PASS
"""
PROBE = '''import "std/data.ouro";
intrinsic String : Type := "ouro.string";
intrinsic prim_string_index : String -> String -> Maybe Nat := "ouro.string.index";
inductive IndexTag (value : Maybe Nat) : Type :=
  | IndexProof : IndexTag value;

def exact_index : IndexTag (prim_string_index "abc" "b") := IndexProof (Just Nat INDEX);
'''


def fail(message: str):
    raise RuntimeError("BOOTSTRAP: FAIL " + message)


def c_toolchain_environment() -> dict[str, str]:
    return {name: value for name in C_TOOLCHAIN_ENV_KEYS if (value := os.environ.get(name)) is not None}


def current_inputs(root: Path, cfg, build, *, compact_sources: bool = False) -> dict:
    roots = [source for _tag, _module, source, _file in frontend.FRONTEND_TUS] + ["compiler/backend.ouro"]
    graph, captured = frontend.capture_unit_inputs([*roots, *ACCEPTANCE_ROOTS], source_root=root)
    if len(roots) != 15 or any(not units or units[-1] != source for source, units in graph.items()):
        fail("incomplete current source graph")
    paths = {*HELPERS, *RUNTIME, *(name for units in graph.values() for name in units),
             *(path.relative_to(root).as_posix() for path in (root / "runtime").glob("*.h"))}
    cc, location = build.locate_cc(cfg)
    cc_path = Path(location or cc).resolve()
    sources = {name: captured[name].sha256 if name in captured else sha256_file(root / name)
               for name in sorted(paths)}
    bridge2 = bootstrap_inputs.bridge2_inputs(root)
    return {"kind": KIND, "roots": roots, "unit_graph": graph, "sources": sources,
        **({"bridge2": bridge2} if bridge2 else {}),
        "source_form": compact_source.KIND if compact_sources else "original",
        "archive_sha256": sha256_file(root / bootstrap_inputs.ARCHIVE),
        "manifest_sha256": sha256_file(root / bootstrap_inputs.MANIFEST),
        "stage0": {name: sha256_file(root / name) for name in bootstrap_inputs.STAGE0},
        "cc": cc, "cc_executable": str(cc_path),
        "cc_id": build.compiler_id(cc, location=location or str(cc_path)), "cc_sha256": sha256_file(cc_path),
        "platform": sys.platform, "machine": sysconfig.get_platform(),
        "cflags": build.profile_cflags(cfg), "link_flags": build.host_link_flags(),
        "environment": c_toolchain_environment()}


def historical_key(selected: dict, workers: int, *, host: dict | None = None) -> str:
    fields = ("kind", "archive_sha256", "manifest_sha256", "stage0", "roots", "cc", "cc_executable", "cc_id",
              "cc_sha256", "platform", "machine", "cflags", "link_flags", "environment")
    return hash_json({**{field: selected[field] for field in fields}, "format": bootstrap_historical.KIND,
                      **({"bridge2": selected["bridge2"]} if "bridge2" in selected else {}),
                      "workers": workers, "host": bootstrap_historical.host_identity() if host is None else host, "fuel": FUEL,
                      "helpers": {name: selected["sources"][name] for name in HISTORICAL_HELPERS}})


def copy_input(source: Path, destination: Path, expected: str) -> None:
    data = source.read_bytes()
    if bootstrap_inputs.digest(data) != expected or sha256_file(source) != expected:
        fail("source changed while freezing " + str(source))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as stream:
        stream.write(data)


def changed_inputs(work: Path, snapshot: dict) -> list[str]:
    return [name for name, digest in snapshot["inputs"].items()
            if not (work / name).is_file() or sha256_file(work / name) != digest]


def current_unchanged(root: Path, selected: dict) -> bool:
    names = {**selected["sources"], **selected["stage0"],
             bootstrap_inputs.ARCHIVE: selected["archive_sha256"], bootstrap_inputs.MANIFEST: selected["manifest_sha256"]}
    return (bootstrap_inputs.bridge2_inputs(root) == selected.get("bridge2", {})
            and all((root / name).is_file() and sha256_file(root / name) == digest for name, digest in names.items()))


def stage_graph(snapshot: dict, phase: str) -> dict:
    if phase == "bridge":
        return snapshot["bridge_graph"]
    if phase == "bridge2":
        return snapshot["bridge2_graph"]
    return snapshot["selected"]["unit_graph"]


def freeze(root: Path, work: Path, selected: dict, cfg) -> dict:
    import ouro_build as build

    requested, workers, budget, throttle_note = bootstrap_worker_plan(cfg.values, build)
    if throttle_note:
        build.log(cfg, "BOOTSTRAP: " + throttle_note)
    config = {**cfg.values, "jobs": workers}
    manifest = bootstrap_inputs.unpack(work / "historical", root)
    historical_roots = {"c0": "historical/c0", "bridge": "historical/bridge"}
    extra = {}
    if "bridge2" in selected:
        next_manifest = bootstrap_inputs.unpack(work / "historical/next", root, bridge2=True)
        if next_manifest["stage0"] != manifest["stage0"] or next_manifest["ordered_roots"] != selected["roots"]:
            fail("second bridge stage0 or ordered roots changed")
        historical_roots["bridge2"] = "historical/next/bridge2"
        extra["bridge2_graph"] = next_manifest["ordered_unit_graph"]
    original = work / "o"
    for name, digest in selected["sources"].items():
        copy_input(root / name, original / name, digest)
    for role in historical_roots.values():
        destination = work / role
        for name in HISTORICAL_HELPERS:
            copy_input(root / name, destination / name, selected["sources"][name])
    for name, digest in selected["stage0"].items():
        copy_input(root / name, work / "historical/c0" / name, digest)
    # The historical source archive is never copied over the current sources.
    if (original / "compiler/stage0").exists() or not current_unchanged(root, selected):
        fail("current source changed or historical stage0 entered current O")
    for name, value in (("good", "1"), ("bad", "2")):
        (original / ("bootstrap-" + name + ".ouro")).write_text(PROBE.replace("INDEX", value), encoding="utf-8", newline="\n")
    directories = [work / "historical", original]
    compaction = None
    if selected.get("source_form") == compact_source.KIND:
        compact = work / "compact"
        rows = {}
        for name, digest in selected["sources"].items():
            if not name.endswith(".ouro"):
                copy_input(original / name, compact / name, digest)
                continue
            source = (original / name).read_bytes()
            if bootstrap_inputs.digest(source) != digest:
                fail("original source changed before compaction: " + name)
            try:
                data = compact_source.compact_source(source)
            except ValueError as error:
                fail(name + ": " + str(error))
            destination = compact / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(data)
            rows[name] = {"original_sha256": digest, "compact_sha256": bootstrap_inputs.digest(data),
                          "original_bytes": len(source), "compact_bytes": len(data)}
        directories.append(compact)
        compaction = {"kind": compact_source.KIND, "files": rows,
                      "original_bytes": sum(row["original_bytes"] for row in rows.values()),
                      "compact_bytes": sum(row["compact_bytes"] for row in rows.values())}
    files = {path.relative_to(work).as_posix(): sha256_file(path)
             for directory in directories for path in sorted(directory.rglob("*")) if path.is_file()}
    snapshot = {"kind": KIND + ".inputs", "key": hash_json(selected), "selected": selected,
        "inputs": files, "config": config, "requested_workers": requested, "memory_budget_mib": budget,
        "bridge_graph": manifest["ordered_unit_graph"],
        "roots": {**historical_roots, "p1": "o", "p2": "compact" if compaction else "o"},
        **extra,
        "compaction": compaction,
        "current_o_projection": "None; every current source is copied byte for byte."}
    if config["cache_enabled"]:
        snapshot["historical_host"] = bootstrap_historical.host_identity()
    write_json_atomic(work / "inputs.json", snapshot)
    return snapshot


def source_checks(producer: Path, root: Path, roots: list[str], graph: dict, *, label: str = "check") -> list:
    tasks = []
    for index, source in enumerate(roots):
        units = [part for unit in graph[source] for part in ("--unit", unit)]
        name = "accept-" + Path(source).stem if label == "accept" else f"{label}-{index:02}"
        tasks.append((name, [str(producer), "check", source, FUEL, *units], root, source))
    return tasks


def strict_roots(tasks: list, jobs: int, memory_mib: int, execute, record) -> None:
    group_job = None
    if os.name == "nt" and jobs > 1:
        from ourosmith.windows_job import Job
        group_job = Job(memory_mib)
    try:
        scheduled = list(enumerate(tasks))
        if jobs > 1:
            scheduled.sort(key=lambda task:
                sum((task[1][2] / path).stat().st_size for path in task[1][1][5::2]), reverse=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            futures = {index: pool.submit(execute, label, argv, root,
                allocation=SINGLE_COMMAND, shared_job=group_job.name if group_job else None)
                for index, (label, argv, root, _source) in scheduled}
            try:
                # Source order keeps the first reported failure independent of completion order.
                for index, (_label, _argv, _root, source) in enumerate(tasks):
                    result, row = futures[index].result()
                    row["shared_memory_mib"] = memory_mib if group_job else None
                    record(result, row)
                    if not result.ok or result.stdout != "CHECK_OK\n" or result.stderr:
                        fail("strict check did not return clean CHECK_OK for " + source)
                if group_job and group_job.memory()[0]:
                    fail("parallel source checks exceeded their shared memory limit")
            except BaseException:
                for future in futures.values():
                    future.cancel()
                if group_job:
                    group_job.terminate()
                raise
    finally:
        if group_job:
            group_job.close()


def compare_generated(first: Path, second: Path) -> dict:
    result = {name: {"p1_sha256": sha256_file(first / name), "p2_sha256": sha256_file(second / name)}
              for name in ("driver_u.c", "backend_u.c")}
    if any(row["p1_sha256"] != row["p2_sha256"] for row in result.values()):
        fail("complete generated frontend/backend C differs between current P1 and P2")
    return result


def bootstrap_workers(config: dict, build) -> int:
    jobs = config["jobs"]
    if jobs != "auto" and (type(jobs) is not int or jobs < 1):
        fail("bootstrap jobs must be auto or a positive integer")
    return build.jobs_value(build.ResolvedConfig(config, {}))


def allocated_memory() -> int | None:
    value = os.environ.get(MEMORY_ENV)
    if value is None:
        return None
    memory = positive_integer(value, MEMORY_ENV)
    if memory < MEMORY_MIB:
        fail(f"{MEMORY_ENV} must allow at least {MEMORY_MIB} MiB")
    return memory


def bootstrap_resources(requested: int, *, worker_memory_mib: int = WORKER_MEMORY_MIB,
                        memory_budget_mib: int | None = None) -> tuple[int, int, str | None]:
    if type(requested) is not int or requested < 1:
        fail("frozen worker request must be a positive integer")
    if type(worker_memory_mib) is not int or not 1 <= worker_memory_mib <= MEMORY_MIB:
        fail("worker memory estimate must be within the command memory limit")
    if memory_budget_mib is None:
        workers, note = memory_aware_jobs(requested, per_worker_mb=worker_memory_mib,
            reserve_mb=MEMORY_RESERVE_MIB + MEMORY_MIB - worker_memory_mib)
    else:
        if type(memory_budget_mib) is not int or memory_budget_mib < MEMORY_MIB:
            fail(f"worker memory budget must allow at least {MEMORY_MIB} MiB")
        workers = min(requested, 1 + (memory_budget_mib - MEMORY_MIB) // worker_memory_mib)
        note = (f"allocated memory caps jobs {requested}->{workers} (budget={memory_budget_mib}MiB)"
                if workers < requested else None)
    memory = MEMORY_MIB + (workers - 1) * worker_memory_mib
    return workers, memory, note


def bootstrap_worker_plan(config: dict, build) -> tuple[int, int, int | None, str | None]:
    requested = bootstrap_workers(config, build)
    budget = allocated_memory()
    workers, _memory, note = bootstrap_resources(requested, memory_budget_mib=budget)
    return requested, workers, budget, note


def stage_lanes(requested: int, budget: int | None) -> tuple[Allocation, Allocation] | None:
    if requested <= 1:
        return None
    available = repo_support.available_memory_mb()
    if available is not None:
        available -= MEMORY_RESERVE_MIB
        budget = available if budget is None else min(available, budget)
    if budget is None:
        budget = 2 * MEMORY_MIB + (requested - 2) * WORKER_MEMORY_MIB
    if budget < 2 * MEMORY_MIB:
        return None
    abi_workers = requested // 2
    produce_workers = requested - abi_workers
    spare = budget - 2 * MEMORY_MIB
    abi_memory = MEMORY_MIB + min(spare // 2, (abi_workers - 1) * COMPILE_WORKER_MEMORY_MIB)
    produce_memory = budget - abi_memory
    return Allocation(abi_workers, abi_memory), Allocation(produce_workers, produce_memory)


def command_concurrency(phases: list[dict]) -> dict[str, int]:
    events = []
    for phase in phases:
        for row in phase["commands"] + phase.get("discarded_commands", []):
            if "started_s" in row and row["finished_s"] > row["started_s"]:
                events.extend(((row["started_s"], 1, row["workers"]),
                               (row["finished_s"], -1, -row["workers"])))
    peak_commands = peak_workers = active_commands = active_workers = 0
    for _when, commands, workers in sorted(events):
        active_commands += commands
        active_workers += workers
        peak_commands = max(peak_commands, active_commands)
        peak_workers = max(peak_workers, active_workers)
    return {"peak_commands": peak_commands, "peak_allocated_workers": peak_workers}


def chain(work: Path, snapshot: dict, build, *, historical_cache: Path | None = None, historical_sha256: str | None = None) -> dict:
    workers = bootstrap_workers(snapshot["config"], build)
    requested = snapshot.get("requested_workers", workers)
    budget = snapshot["memory_budget_mib"] if "memory_budget_mib" in snapshot else allocated_memory()
    started = time.perf_counter()
    parallel_memory_mib = (MEMORY_MIB + (workers - 1) * WORKER_MEMORY_MIB) if os.name == "nt" else MEMORY_MIB
    report = {"kind": KIND, "key": snapshot["key"], "inputs_sha256": sha256_file(work / "inputs.json"),
        "workers": workers, "requested_workers": requested,
        "memory_mib": MEMORY_MIB, "parallel_memory_mib": parallel_memory_mib, "memory_budget_mib": budget,
        "timeout_s": TIMEOUT_S, "phases": [], "pass": False}
    selected, producers = snapshot["selected"], {}
    phase, out = "prepare", work

    def save():
        report["elapsed_s"] = time.perf_counter() - started
        report.update(command_concurrency(report["phases"]))
        write_json_atomic(work / "report.json", report)

    def finish(result, row, *, negative=False):
        report["phases"][-1]["commands"].append(row)
        save()
        if not result.ok and not (negative and result.status == "ok" and result.returncode == 1):
            for stream in (result.stdout, result.stderr):
                if stream:
                    print(stream, end="" if stream.endswith("\n") else "\n", file=sys.stderr, flush=True)
            fail(f"{phase}/{row['label']}: {result.classify()} exit={result.returncode}; see {out}")
        return result

    def say(message):
        if snapshot["config"]["verbosity"] != "quiet":
            # One write per line keeps concurrent lane progress readable.
            print(message + "\n", end="", flush=True)

    def resources(workers, worker_memory_mib, memory_budget):
        count, memory, note = bootstrap_resources(workers, worker_memory_mib=worker_memory_mib,
                                                   memory_budget_mib=memory_budget)
        if note:
            say("BOOTSTRAP: " + note)
        return Allocation(count, memory)

    def execute(label, argv, root, *, allocation=SINGLE_COMMAND, shared_job=None):
        if changed_inputs(work, snapshot):
            fail("frozen bootstrap inputs changed before " + label)
        if sha256_file(Path(selected["cc_executable"])) != selected["cc_sha256"]:
            fail("selected C compiler changed before " + label)
        if c_toolchain_environment() != selected["environment"]:
            fail("selected C toolchain environment changed before " + label)
        env = clean_env()
        for name in ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
            if name in os.environ:
                env[name] = os.environ[name]
        for name in C_TOOLCHAIN_ENV_KEYS:
            env.pop(name, None)
        env.update(selected["environment"])
        command_workers = allocation.jobs
        memory_mib = allocation.memory_mib if os.name == "nt" else MEMORY_MIB
        values = {**snapshot["config"], "cc": selected["cc_executable"], "jobs": command_workers, "cache_enabled": False, "ccache": "disabled",
                  "build_dir": str(out / "b"), "c_build_dir": str(out / "c"), "cache_dir": str(out / "k")}
        for key, name in build.ENV_MAP.items():
            value = values[key]
            env[name] = ("1" if value else "0") if isinstance(value, bool) else str(value)
        env.update(allocation.environment(), PYTHONDONTWRITEBYTECODE="1", OURO1_CHECK_FUEL=FUEL)
        options = {"shared_job": shared_job} if shared_job is not None else {}
        command_started = time.perf_counter() - started
        result = run_limited(argv, cwd=root, env=env, timeout_s=TIMEOUT_S, memory_mb=memory_mib, **options)
        row = {"label": label, "cwd": str(root), "workers": command_workers, "started_s": command_started,
               "finished_s": time.perf_counter() - started,
               "memory_mib": memory_mib, **dataclasses.asdict(result)}
        for stream in ("stdout", "stderr"):
            path = out / (label + "." + stream)
            path.write_text(getattr(result, stream), encoding="utf-8", newline="\n")
            row[stream], row[stream + "_sha256"] = path.relative_to(work).as_posix(), sha256_file(path)
        return result, row

    def run(label, argv, root, *, negative=False, shared_job=None):
        say(f"BOOTSTRAP: {phase}/{label}")
        return finish(*execute(label, argv, root, shared_job=shared_job), negative=negative)

    def worker(action, root, producer=None, *, allocation=None, shared_job=None):
        jobs, memory = (requested, budget) if allocation is None else (allocation.jobs, allocation.memory_mib)
        limits = resources(jobs, WORKER_MEMORY_MIB if action == "frontend" else COMPILE_WORKER_MEMORY_MIB,
                           memory)
        argv = [sys.executable, "-B", str(root / "scripts/bootstrap_compiler.py"), "worker",
                "--snapshot", str(work / "inputs.json"), "--phase", phase, "--action", action,
                "--jobs", str(limits.jobs)]
        if producer is not None:
            argv.extend(["--producer", str(producer)])
        say(f"BOOTSTRAP: {phase}/{action}")
        return execute(action, argv, root, allocation=limits, shared_job=shared_job)

    def build_stage(root, producer, graph, checks):
        phase_row = report["phases"][-1]
        if checks:
            # POSIX has no shared job to enforce the sum of concurrent checks.
            estimate = COMPILE_WORKER_MEMORY_MIB if os.name == "nt" else MEMORY_MIB
            limits = resources(min(requested, len(checks)), estimate, budget)
            say(f"BOOTSTRAP: {phase}/checks count={len(checks)} jobs={limits.jobs}")
            strict_roots(checks, limits.jobs, limits.memory_mib, execute, finish)
            phase_row["all_current_roots_strictly_checked_before_use"] = True
            if root != work / "o":
                phase_row["all_compact_roots_strictly_checked_before_use"] = True

        allocations = stage_lanes(requested, budget) if phase == "p2" else None
        phase_row["overlap"] = allocations is not None
        parallel_memory = sum(lease.memory_mib for lease in allocations) if allocations else 0
        if allocations is not None:
            phase_row["concurrent_builds_memory_mib"] = parallel_memory
        stop, abi_done = threading.Event(), threading.Event()
        group = None
        if allocations is not None and os.name == "nt":
            from ourosmith.windows_job import Job
            group = Job(parallel_memory)
        shared = group.name if group else None

        def produce_allocation():
            if allocations is None:
                return None
            if abi_done.is_set():
                return Allocation(requested, parallel_memory)
            return allocations[1]

        def produce():
            if stop.is_set():
                return [], False
            steps = [worker("frontend", root, producer, allocation=produce_allocation(), shared_job=shared)]
            if not steps[-1][0].ok or stop.is_set():
                return steps, False
            args = [part for unit in graph["compiler/backend.ouro"] for part in ("--unit", unit)]
            say(f"BOOTSTRAP: {phase}/backend")
            steps.append(execute("backend", [str(producer), "--module", "_be", "compiler/backend.ouro", FUEL, *args],
                                 root, shared_job=shared))
            result = steps[-1][0]
            exported = result.stdout.startswith('#include "ouro_rt.h"') and "ouro_export_count_be" in result.stdout
            if not result.ok or not exported or stop.is_set():
                return steps, exported
            (out / "backend_u.c").write_text(result.stdout, encoding="utf-8", newline="\n")
            steps.append(worker("link", root, allocation=produce_allocation(), shared_job=shared))
            return steps, exported

        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1) if allocations is not None else None
        production = pool.submit(produce) if pool is not None else None
        production_consumed = False
        try:
            if phase == "p2":
                finish(*worker("abi-build", root, producer,
                               allocation=allocations[0] if allocations else None, shared_job=shared))
                law = out / ("abi.exe" if os.name == "nt" else "abi")
                result = run("abi-laws", [str(law)], root, shared_job=shared)
                if result.stderr or result.stdout != ABI_STDOUT:
                    fail("current P1 compiler ABI laws did not return the exact expected protocol")
                abi_done.set()
            production_consumed = True
            steps, exported = production.result() if production else produce()
            for index, step in enumerate(steps):
                finish(*step)
                if index == 1 and not exported:
                    fail("backend emission lacks its declared export table")
            if group and group.memory()[0]:
                fail("concurrent stage builds exceeded their shared memory limit")
        except BaseException:
            stop.set()
            if group:
                group.terminate()
            raise
        finally:
            if pool is not None and production is not None:
                pool.shutdown(wait=True, cancel_futures=True)
                if not production_consumed and not production.cancelled() and production.exception() is None:
                    phase_row["discarded_commands"] = [row for _result, row in production.result()[0]]
            if group:
                group.close()

    try:
        configure_native_stack()
        packet = None
        historical = None
        if historical_cache is not None and snapshot["config"]["cache_enabled"]:
            host = bootstrap_historical.host_identity()
            if snapshot.get("historical_host", host) != host:
                fail("historical C toolchain changed after freezing")
            packet = historical_cache / (historical_key(selected, workers, host=host) + ".zip")
            historical = bootstrap_historical.restore(packet, work, snapshot, historical_key, expected_sha256=historical_sha256)
            if historical:
                report["historical_cache"] = historical
        historical_phases = bootstrap_historical.historical_phases(snapshot)
        for phase in (*historical_phases, "p1", "p2"):
            out = work / "out" / phase
            root = work / snapshot["roots"][phase]
            row = {"phase": phase, "source_root": snapshot["roots"][phase], "commands": [], "pass": False}
            report["phases"].append(row)
            if historical and phase in historical_phases:
                original = historical["phases"][len(report["phases"]) - 1]
                row.update(binary=original["binary"], binary_sha256=original["binary_sha256"], cache="hit", **{"pass": True})
                producers[phase] = work / original["binary"]
                if phase != "c0":
                    previous = report["phases"][-2]["phase"]
                    row.update(producer=str(producers[previous]), producer_sha256=original["producer_sha256"],
                               frontend_sha256=original["frontend_sha256"], backend_sha256=original["backend_sha256"])
                    if phase == "bridge2":
                        row["all_current_roots_strictly_checked_before_use"] = True
                save()
                continue
            out.mkdir(parents=True, exist_ok=False)
            if phase == "c0":
                finish(*worker("c0", root))
                binary = out / "c/ouro1"
            else:
                producer = producers[report["phases"][-2]["phase"]]
                producer_hash = sha256_file(producer)
                if producer_hash != report["phases"][-2]["binary_sha256"]:
                    fail("producer changed before " + phase)
                row.update(producer=str(producer), producer_sha256=producer_hash)
                graph = stage_graph(snapshot, phase)
                checks = []
                if phase == "bridge2":
                    checks = source_checks(producer, root, selected["roots"], graph)
                if phase in {"p1", "p2"}:
                    checks = source_checks(producer, work / "o", selected["roots"], graph)
                    if root != work / "o":
                        checks.extend(source_checks(producer, root, selected["roots"], graph, label="check-compact"))
                    if phase == "p2":
                        if root != work / "o":
                            checks.extend(source_checks(producer, work / "o", ACCEPTANCE_ROOTS, graph, label="accept-original"))
                        checks.extend(source_checks(producer, root, ACCEPTANCE_ROOTS, graph, label="accept"))
                build_stage(root, producer, graph, checks)
                binary = out / "ouro1"
                if sha256_file(producer) != producer_hash:
                    fail("producer changed during " + phase)
                row.update(frontend_sha256=sha256_file(out / "driver_u.c"), backend_sha256=sha256_file(out / "backend_u.c"))
            if not binary.is_file() or binary.stat().st_size <= 4096:
                fail("missing complete compiler output for " + phase)
            producers[phase] = binary
            row.update(binary=binary.relative_to(work).as_posix(), binary_sha256=sha256_file(binary), **{"pass": True})
            save()
        comparison = compare_generated(work / "out/p1", work / "out/p2")
        for stage_row in report["phases"][-2:]:
            stage = stage_row["phase"]
            for name, field in (("driver_u.c", "frontend_sha256"), ("backend_u.c", "backend_sha256")):
                if comparison[name][f"{stage}_sha256"] != stage_row[field]:
                    fail(f"complete generated C changed after {stage}: {name}")
        report["complete_generated_c_comparison"] = comparison
        producer = producers["p2"]
        p2_sha256 = report["phases"][-1]["binary_sha256"]
        if sha256_file(producer) != p2_sha256:
            fail("current P2 compiler changed before behavior probes")
        root = work / "o"
        for variant in ("good", "bad"):
            source = "bootstrap-" + variant + ".ouro"
            units = [*selected["unit_graph"]["std/data.ouro"], source]
            argv = [str(producer), "check", source, FUEL, *[part for unit in units for part in ("--unit", unit)]]
            result = run("behavior-" + variant, argv, root, negative=variant == "bad")
            if variant == "good" and (result.stdout != "CHECK_OK\n" or result.stderr):
                fail("current P2 positive behavior was not accepted")
            expected = ("bootstrap-bad.ouro: type mismatch in exact_index\nCHECK_FAIL: front end rejected the input\n"
                        "ouro1: CErr tag=0 n=1\nouro1: CErr code=41 det=82\n")
            if variant == "bad" and (result.returncode != 1 or result.stdout or result.stderr != expected):
                fail("current P2 negative behavior did not preserve the exact rejection")
            if sha256_file(producer) != p2_sha256:
                fail(f"current P2 compiler changed after behavior-{variant}")
        report.update(binary=producer.relative_to(work).as_posix(), binary_sha256=p2_sha256, **{"pass": True})
    except (OSError, RuntimeError, ValueError) as error:
        report["failure"] = str(error)
        raise
    finally:
        report["changed_inputs"] = changed_inputs(work, snapshot)
        report["pass"] = bool(report["pass"] and not report["changed_inputs"])
        save()
    if not report["pass"]:
        fail("frozen inputs changed during bootstrap")
    if packet is not None and historical is None:
        try:
            if (historical_key(selected, workers) != packet.stem
                    or sha256_file(Path(selected["cc_executable"])) != selected["cc_sha256"]
                    or c_toolchain_environment() != selected["environment"]):
                fail("historical C toolchain changed before publication")
            digest = bootstrap_historical.publish(packet, work, report)
            report["historical_cache"] = {"key": packet.stem, "sha256": digest}
            save()
        except OSError as error:
            report["historical_cache"] = {"error": str(error)}
            save()
        except (RuntimeError, ValueError) as error:
            report.update(failure=str(error), **{"pass": False})
            save()
            raise
    return report


def _installed_compiler_digest(binary: Path, data: dict | None, selected: dict) -> str | None:
    if data is None or data.get("kind") != KIND or data.get("key") != hash_json(selected) or data.get("selected") != selected:
        return None
    try:
        work = Path(data["work"])
        report_bytes = (work / "report.json").read_bytes()
        report = json.loads(report_bytes.decode("utf-8"))
        comparison = report.get("complete_generated_c_comparison") if isinstance(report, dict) else None
        if (binary.is_file() and binary.stat().st_size > 4096 and sha256_file(binary) == data["binary_sha256"]
                and isinstance(report, dict) and report.get("kind") == KIND
                and report.get("pass") is True and report.get("key") == data["key"]
                and report.get("binary_sha256") == data["binary_sha256"]
                and repo_support.sha256_bytes(report_bytes) == data["report_sha256"]
                and sha256_file(work / "inputs.json") == report["inputs_sha256"]
                and isinstance(comparison, dict) and comparison.keys() == {"driver_u.c", "backend_u.c"}
                and all(sha256_file(work / "out/p1" / name) == row["p1_sha256"] == row["p2_sha256"] == sha256_file(work / "out/p2" / name)
                        for name, row in comparison.items())):
            return data["binary_sha256"]
    except (OSError, KeyError, TypeError, ValueError):
        return None
    return None


def installed_current(binary: Path, receipt: Path, selected: dict) -> bool:
    return _installed_compiler_digest(binary, read_json_object_or_none(receipt), selected) is not None


def local_bootstrap_cache(root: Path) -> Path | None:
    if os.environ.get(LOCAL_CACHE_ENV) != "1" or os.environ.get("GITHUB_ACTIONS") == "true":
        return None
    lane = root.parent
    build_dir = lane.parent
    if (build_dir.name != "_build"
            or not (lane.name == "ci-host" or (lane.name.startswith("ci-") and root.name == "source"))):
        fail("shared local bootstrap cache requires an isolated CI checkout")
    cache = build_dir / "ci-bootstrap"
    if cache.resolve() != cache:
        fail("shared local bootstrap cache must use its regular checkout path")
    return cache


def verify_current_inputs(root: Path, selected: dict) -> None:
    if not current_unchanged(root, selected) or sha256_file(Path(selected["cc_executable"])) != selected["cc_sha256"]:
        fail("current source changed before publication; preserving the existing compiler")
    if c_toolchain_environment() != selected["environment"]:
        fail("selected C toolchain environment changed before publication; preserving the existing compiler")


def copy_verified_compiler(root: Path, selected: dict, *, source: Path, source_build: Path,
                           output: Path, output_build: Path, optional_source: bool = False) -> dict | None:
    source_receipt = source.with_name("ouro1.bootstrap.json")
    try:
        if source.resolve() != source or source_receipt.resolve() != source_receipt:
            return None
        record = read_json_object_or_none(source_receipt)
        if record is None or not isinstance(record.get("work"), str):
            return None
        work = Path(record["work"])
        if work.parent != source_build / "bootstrap" or any(
                (work / name).resolve() != work / name for name in CURRENT_EVIDENCE):
            return None
    except (OSError, RuntimeError, ValueError):
        return None
    if _installed_compiler_digest(source, record, selected) is None:
        return None
    evidence = output_build / "bootstrap"
    if evidence.resolve() != evidence or output.parent.resolve() != output.parent:
        fail("shared bootstrap copy requires regular output directories")
    evidence.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    copied = Path(tempfile.mkdtemp(prefix=record["key"][:12] + "-", dir=evidence))
    published = False
    try:
        result = {**record, "work": str(copied)}
        with tempfile.TemporaryDirectory(prefix=".compiler-", dir=output.parent) as temporary:
            staging = Path(temporary)
            binary = staging / output.name
            receipt = staging / source_receipt.name
            files = [(work / name, copied / name) for name in CURRENT_EVIDENCE]
            files.append((source, binary))
            for original, target in files:
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(original, target)
                except FileNotFoundError:
                    return None
                except PermissionError as error:
                    # A Windows sharing error can omit the source path.
                    if not optional_source or error.filename == str(target):
                        raise
                    return None
            write_json_atomic(receipt, result)
            # The default checkout can replace its compiler or evidence during the copy.
            if not installed_current(binary, receipt, selected):
                return None
            verify_current_inputs(root, selected)
            # The receipt is the publication point. A partial copy cannot certify another binary.
            os.replace(binary, output)
            os.replace(receipt, output.with_name(source_receipt.name))
            published = True
    finally:
        if not published:
            if copied.resolve() != copied:
                fail(f"bootstrap copy evidence path changed before cleanup: {copied}")

            def retry_unlink(remove, path, error_info):
                error = error_info[1]
                if isinstance(error, FileNotFoundError):
                    return
                if os.name != "nt" or remove is not os.unlink or not isinstance(error, PermissionError):
                    raise error
                # copy2 preserves the read-only attribute on Windows.
                os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
                remove(path)

            shutil.rmtree(copied, onerror=retry_unlink)
    return result


def build_current_compiler(cfg, build, root: Path, selected: dict, *, historical_cache: Path | None,
                           historical_sha256: str | None) -> dict:
    output = cfg.path("c_build_dir") / "ouro1"
    receipt = output.with_name("ouro1.bootstrap.json")
    directory = cfg.path("build_dir") / "bootstrap"
    directory.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=hash_json(selected)[:12] + "-", dir=directory))
    snapshot = freeze(root, work, selected, cfg)
    report = chain(work, snapshot, build, historical_cache=historical_cache, historical_sha256=historical_sha256)
    verify_current_inputs(root, selected)
    binary = work / report["binary"]
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".compiler-", dir=output.parent) as staging:
        temporary = Path(staging) / output.name
        shutil.copy2(binary, temporary)
        if sha256_file(temporary) != report["binary_sha256"]:
            fail("successor changed before publication")
        report_bytes = (work / "report.json").read_bytes()
        if hash_json(json.loads(report_bytes.decode("utf-8"))) != hash_json(report):
            fail("current bootstrap report changed before publication")
        result = {"kind": KIND, "key": hash_json(selected), "selected": selected, "work": str(work),
            "report_sha256": repo_support.sha256_bytes(report_bytes), "binary_sha256": report["binary_sha256"]}
        os.replace(temporary, output)
        write_json_atomic(receipt, result)
    build.log(cfg, "BOOTSTRAP: current P2 published after strict source checks, behavior checks and complete C equality")
    return result


def ensure_current_compiler(cfg, build, root: Path = ROOT, *, compact_sources: bool = False) -> dict:
    manifest, _contents = bootstrap_inputs.read_bundle(root)
    bootstrap_inputs.verify_stage0(root, manifest)
    selected = current_inputs(root, cfg, build, compact_sources=compact_sources)
    build_dir = cfg.path("build_dir")
    output = cfg.path("c_build_dir") / "ouro1"
    receipt = output.with_name("ouro1.bootstrap.json")
    cache_enabled = cfg.get_bool("cache_enabled")
    installed_digest = (_installed_compiler_digest(output, read_json_object_or_none(receipt), selected)
                        if cache_enabled else None)
    if installed_digest is not None:
        build.log(cfg, "BOOTSTRAP: current compiler unchanged; checked successor reused")
        return {"cache": "hit", "binary": str(output), "binary_sha256": installed_digest}
    shared = local_bootstrap_cache(root) if cache_enabled else None
    if shared is not None:
        if build_dir != root / "_build" or output.parent != build_dir / "c":
            fail("shared local bootstrap cache requires the isolated CI build directories")
        # Keep Windows paths short. The installed receipt still carries the full key and inputs.
        entry = shared / "current" / hash_json(selected)[:16]
        historical_cache = shared / "bootstrap-historical"
        if entry.resolve() != entry or historical_cache.resolve() != historical_cache:
            fail("shared bootstrap cache entries must use regular checkout paths")
        cached = entry / "c/ouro1"
        with build.cache_access(entry, exclusive=True):
            restored = copy_verified_compiler(root, selected, source=cached, source_build=entry,
                                              output=output, output_build=build_dir)
            if restored is not None:
                build.log(cfg, "BOOTSTRAP: checked successor restored from shared local cache")
                return {"cache": "hit", "binary": str(output), "binary_sha256": restored["binary_sha256"]}
            checkout_build = shared.parent
            restored = copy_verified_compiler(root, selected, source=checkout_build / "c/ouro1",
                                              source_build=checkout_build, output=output, output_build=build_dir,
                                              optional_source=True)
            if restored is None:
                result = build_current_compiler(cfg, build, root, selected,
                                                historical_cache=historical_cache, historical_sha256=None)
            else:
                build.log(cfg, "BOOTSTRAP: checked successor restored from the default checkout build")
                result = {"cache": "hit", "binary": str(output), "binary_sha256": restored["binary_sha256"]}
            try:
                if copy_verified_compiler(root, selected, source=output, source_build=build_dir,
                                          output=cached, output_build=entry) is None:
                    fail("new compiler evidence differs before shared cache publication")
            except OSError as error:
                build.log(cfg, f"BOOTSTRAP: shared local cache publication failed: {error}")
            return result
    historical_cache = None
    historical_sha256 = None
    if cache_enabled:
        if os.environ.get("GITHUB_ACTIONS") != "true":
            historical_cache = build_dir / "bootstrap-historical"
        elif os.environ.get("RUNNER_TEMP"):
            runner_temp = Path(os.environ["RUNNER_TEMP"])
            if runner_temp.is_absolute() and not runner_temp.resolve().is_relative_to(root.resolve()):
                historical_cache = runner_temp / "bootstrap-historical"
                historical_sha256 = os.environ.get("OURO_BOOTSTRAP_HISTORY_SHA256", "")
    return build_current_compiler(cfg, build, root, selected, historical_cache=historical_cache,
                                  historical_sha256=historical_sha256)


def worker(args) -> None:
    work = args.snapshot.resolve().parent
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    if ROOT != work / snapshot["roots"][args.phase] or changed_inputs(work, snapshot):
        fail("worker source root or frozen input mismatch")
    import ouro_build as build
    import stage_loop
    out = work / "out" / args.phase
    selected_jobs = getattr(args, "jobs", None)
    workers = bootstrap_workers({**snapshot["config"], "jobs": selected_jobs if selected_jobs is not None else snapshot["config"]["jobs"]}, build)
    ceiling = snapshot.get("requested_workers", bootstrap_workers(snapshot["config"], build))
    if type(ceiling) is not int or ceiling < 1:
        fail("frozen worker request must be a positive integer")
    if workers > ceiling:
        fail("worker count exceeds the frozen request")
    if sys.platform == "linux" and workers > 1:
        # Linux can inherit the launcher's native stack reserve as the pthread default.
        # Only the Python pool needs a smaller reservation.
        threading.stack_size(8 * 1024 * 1024)
    values = {**snapshot["config"], "cc": snapshot["selected"]["cc_executable"], "jobs": workers, "cache_enabled": False, "ccache": "disabled",
              "build_dir": str(out / "b"), "c_build_dir": str(out / "c"), "cache_dir": str(out / "k")}
    cfg = build.ResolvedConfig(values, {key: "frozen bootstrap invocation" for key in values})
    graph = stage_graph(snapshot, args.phase)
    if args.action == "c0":
        if args.phase != "c0":
            fail("historical C build requested for a current stage")
        build.build_c(cfg)
    elif args.action == "frontend":
        for source, units in frontend.iter_unit_closures(snapshot["selected"]["roots"]):
            if units != graph[source]:
                fail("worker ordered source closure changed")
        # Only the pinned historical bridge uses its archived arithmetic bindings.
        frontend.regenerate(ouro1=args.producer, fuel=FUEL, out_c=out / "driver_u.c", work=out / "fe",
            cache_root=out / "k", cache_enabled=False, report_path=out / "frontend.json", jobs=workers,
            historical_bridge=args.phase == "bridge")
    elif args.action == "link":
        config = stage_loop.build_config(argparse.Namespace(promote=False))
        config.build_cfg = cfg
        config.work, config.cache_enabled = out / "b/stage_loop", False
        result = stage_loop.build_stage_binary(out / "driver_u.c", out / "backend_u.c", out / "ouro1", 1, config)
        write_json_atomic(out / "link.json", result)
    elif args.action == "abi-build":
        if args.phase != "p2":
            fail("ABI build requires current P2")
        import native_tool_build
        law_args = argparse.Namespace(entry="tests/compiler_abi_tests.ouro", output=out / "abi", compiler=args.producer,
            fuel=int(FUEL), check=False, config=None, profile=None, opt_level="O0", jobs=workers, cc=values["cc"],
            ccache="disabled", cache_enabled=False, build_dir=str(out / "ab"), c_build_dir=str(out / "ac"),
            cache_dir=str(out / "ak"), reproducible=values["reproducible"], verbosity=values["verbosity"])
        result = native_tool_build.build_tool(law_args)
        write_json_atomic(out / "abi-build.json", result)
    else:
        fail("unknown bootstrap worker action")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    internal = sub.add_parser("worker", help=argparse.SUPPRESS)
    internal.add_argument("--snapshot", type=Path, required=True)
    internal.add_argument("--phase", choices=("c0", "bridge", "bridge2", "p1", "p2"), required=True)
    internal.add_argument("--action", choices=("c0", "frontend", "link", "abi-build"), required=True)
    internal.add_argument("--producer", type=Path)
    internal.add_argument("--jobs", type=int)
    args = parser.parse_args()
    try:
        worker(args)
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, str(error) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
