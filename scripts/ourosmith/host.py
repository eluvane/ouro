"""Locate installed tools and build native entry points through repository scripts."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from local_scheduler import (
    JOBS_ENV, MEMORY_ENV, Allocation, Task, available_memory_mib, bounded_jobs, configured_jobs, positive_integer,
    run_tasks,
)
from ourosmith import ROOT
from ourosmith.limits import clean_env, run_limited
from repo_support import write_json_atomic

TOOLS = ("collect", "fmt", "fix", "lint", "doc", "lsp", "test")
BUILD_MEMORY_MB = 3072
BUILD_WORKER_MEMORY_MB = 512
BUILD_TIMEOUT_S = 900


def build_memory_mib() -> int:
    ceiling = os.environ.get(MEMORY_ENV, str(BUILD_MEMORY_MB))
    return min(BUILD_MEMORY_MB, positive_integer(ceiling, MEMORY_ENV))


def build_config():
    from types import SimpleNamespace
    import ouro_build

    return ouro_build.load_config(SimpleNamespace())


def tool_entry(tool: str) -> str:
    if tool not in TOOLS:
        raise ValueError(f"unknown native tool: {tool}")
    return f"tools/{tool}/main.ouro" if tool in {"fix", "test"} else f"tools/{tool}.ouro"


def shell(*, search_path: bool = True) -> Path:
    configured = os.environ.get("OURO_SH")
    if configured:
        path = Path(configured)
        if not path.is_file():
            raise FileNotFoundError(f"OURO_SH does not exist: {path}")
        return path.resolve()
    found = shutil.which("sh") if search_path else None
    if found:
        return Path(found).resolve()
    if os.name == "nt":
        for candidate in ("C:/msys64/usr/bin/sh.exe", "C:/Program Files/Git/usr/bin/sh.exe"):
            if Path(candidate).is_file():
                return Path(candidate)
    raise FileNotFoundError("POSIX sh unavailable; set OURO_SH to an installed shell")


def job_count() -> int:
    available = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count() or 1
    return min(configured_jobs(), max(1, available))


def environment(*, jobs: int | None = None, build: bool = False, shell_path: Path | None = None) -> dict[str, str]:
    jobs = job_count() if jobs is None else bounded_jobs(jobs)
    env = clean_env()
    cfg = build_config()
    env.update({"OURO_ROOT": ROOT.as_posix(), "OURO_JOBS": str(jobs),
                "OURO_FRONTEND_JOBS": str(jobs), "OURO_REPRODUCIBLE": "1",
                "OURO_TEST_CHECK": (ROOT / "scripts/ouro1.sh").as_posix(),
                "OURO_TEST_BUILD": (ROOT / "scripts/build_tool.sh").as_posix(),
                "OURO_HOSTED_COMPILER_WRAPPER": (ROOT / "scripts/ouro1.sh").as_posix(),
                "OURO_HOSTED_FMT": (cfg.path("c_build_dir") / "ouro-fmt").as_posix()})
    if JOBS_ENV in os.environ:
        env[JOBS_ENV] = str(jobs)
    if MEMORY_ENV in os.environ:
        env[MEMORY_ENV] = os.environ[MEMORY_ENV]
    sh = shell() if shell_path is None else shell_path
    env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), str(sh.parent), env.get("PATH", "")])
    env["OURO_POSIX_SH"] = sh.as_posix()
    if build:
        env["PYTHON"] = Path(sys.executable).as_posix()
        for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA",
                    "CC", "OURO_CACHE", "OURO_CCACHE"):
            if key in os.environ:
                env[key] = os.environ[key]
        for key, variable in (("build_dir", "OURO_BUILD_DIR"), ("c_build_dir", "OURO_C_BUILD_DIR"),
                              ("cache_dir", "OURO_CACHE_DIR")):
            env[variable] = cfg.path(key).as_posix()
    return env


def binary(name: str, *, directory: Path | None = None) -> Path:
    directory = Path(directory) if directory is not None else build_config().path("c_build_dir")
    candidates = [directory / (name + ".exe"), directory / name] if os.name == "nt" else [directory / name]
    for path in candidates:
        if path.is_file() and path.stat().st_size > 4096:
            return path.resolve()
    raise FileNotFoundError(f"native binary unavailable: {directory / name}")


def prepare_entry(entry: str, name: str) -> Path:
    """Prepare a source-bound native entry through the existing build boundary."""
    target_dir = build_config().path("c_build_dir")
    env = dict(os.environ, OURO_BUILD_TOOL_MODE="native", PYTHON=sys.executable)
    memory_mib = build_memory_mib()
    env[MEMORY_ENV] = str(memory_mib)
    prepared = run_limited(
        [str(shell()), str(ROOT / "scripts/build_tool.sh"), entry, str(target_dir / name)],
        cwd=ROOT, env=env, timeout_s=BUILD_TIMEOUT_S, memory_mb=memory_mib,
    )
    if not prepared.ok:
        raise ValueError(f"native build failed status={prepared.status} exit={prepared.returncode}\n"
                         + prepared.stdout + prepared.stderr)
    return binary(name, directory=target_dir)


def compiler_path(value: Path | str | None = None) -> Path:
    path = Path(value).resolve() if value is not None else binary("ouro1")
    if not path.is_relative_to(ROOT) or not path.is_file() or path.stat().st_size <= 4096:
        raise ValueError(f"native compiler must be an existing repository-local binary: {path}")
    return path


def toolchain_evidence(compiler: Path, overrides: dict[str, Path], *, root: Path | None = None) -> dict:
    from native_tool_build import cached_import_parser
    from ourosmith.native import digest, receipt_for

    root = ROOT if root is None else root
    compiler = compiler_path(compiler)
    if not compiler.is_relative_to(root):
        raise ValueError("compiler escapes its toolchain checkout")
    if set(overrides) != {"ouro1", *("ouro-" + tool for tool in TOOLS)} or overrides["ouro1"] != compiler:
        raise ValueError("the complete native tool map must use the selected compiler")
    entries = {}
    parse_bytes = cached_import_parser()
    for tool in TOOLS:
        path = Path(overrides["ouro-" + tool]).resolve()
        relative = path.relative_to(root).as_posix()
        receipt, _units, _sources = receipt_for(path, tool_entry(tool), compiler, parse_bytes=parse_bytes)
        entries[tool] = {"entry": tool_entry(tool), "binary": relative,
                         "sha256": receipt["binary_sha256"], "build_key": receipt["key"]}
    return {"kind": "ouro.smith-toolchain.v1", "compiler": compiler.relative_to(root).as_posix(),
            "compiler_sha256": digest(compiler), "tools": entries}


def toolchain_paths(evidence: dict, *, compiler: Path | None = None, root: Path | None = None) -> dict[str, Path]:
    """Recover an exact tool map only from complete current build receipts."""
    if (not isinstance(evidence, dict) or set(evidence) != {"kind", "compiler", "compiler_sha256", "tools"}
            or evidence["kind"] != "ouro.smith-toolchain.v1" or not isinstance(evidence["tools"], dict)
            or set(evidence["tools"]) != set(TOOLS)):
        raise ValueError("native toolchain evidence is incomplete or malformed")
    root = ROOT if root is None else root
    selected = compiler_path(root / evidence["compiler"])
    if compiler is not None and selected != Path(compiler).resolve():
        raise ValueError("surface toolchain uses a different compiler")
    overrides = {"ouro1": selected}
    for tool in TOOLS:
        entry = evidence["tools"][tool]
        if not isinstance(entry, dict) or set(entry) != {"entry", "binary", "sha256", "build_key"}:
            raise ValueError("native tool evidence fields are incomplete or unknown")
        overrides["ouro-" + tool] = (root / entry["binary"]).resolve()
    if toolchain_evidence(selected, overrides, root=root) != evidence:
        raise ValueError("native toolchain evidence differs from current source or binaries")
    return overrides


def scheduled_tool_builds() -> list[tuple[Task, str, str]]:
    from native_tool_build import tool_companions

    builds: dict[str, tuple[Task, str, str]] = {}

    def add(entry: str, name: str, log_stem: str) -> None:
        if entry in builds:
            return
        companions = tool_companions(entry)
        for companion_entry, companion_name in companions:
            add(companion_entry, companion_name, companion_name)
        task = Task(entry, tuple(path for path, _ in companions),
                    memory_mib=BUILD_WORKER_MEMORY_MB, base_memory_mib=BUILD_MEMORY_MB - BUILD_WORKER_MEMORY_MB)
        builds[entry] = (task, name, log_stem)

    for tool in TOOLS:
        add(tool_entry(tool), "ouro-" + tool, tool)
    return list(builds.values())


def prepare_tools(out: Path, compiler: Path) -> tuple[dict[str, Path], dict]:
    """Use one explicit producer and source-bound tools without rebuilding a seed."""
    from ouro_build import cache_access, cache_build_access, trim_cache
    from ourosmith.native import digest

    compiler = compiler_path(compiler)
    producer_hash = digest(compiler)
    cfg = build_config()
    # Stable paths preserve report fingerprints across repeated output directories.
    # Complete digests remain in receipts; short paths fit native Windows builds.
    directory = (cfg.path("build_dir") / "smith-tools" / producer_hash[:16]).resolve()
    if not directory.is_relative_to(ROOT):
        raise ValueError("Smith native tool outputs must stay inside the repository")
    out = Path(out)
    schedule_path = out / "tool-schedule.json"
    jobs = job_count()
    memory = available_memory_mib()
    builds = {task: (name, log_stem) for task, name, log_stem in scheduled_tool_builds()}
    with cache_access(directory, exclusive=True):
        schedule_path.unlink(missing_ok=True)
        directory.mkdir(parents=True, exist_ok=True)
        # Keep companion evidence available until its last consumer exits.
        with cache_build_access(cfg), tempfile.TemporaryDirectory(prefix="p-", dir=directory) as proofs:
            def compile_tool(task: Task, allocation: Allocation) -> dict:
                name, log_stem = builds[task]
                started = time.perf_counter()
                log = out / (log_stem + "-build.log")
                command = [sys.executable, "-B", str(ROOT / "scripts/native_tool_build.py"), task.name,
                           str(directory / name), "--compiler", str(compiler), "--jobs", str(allocation.jobs),
                           "--ccache", "disabled", "--build-dir", str(directory / "b" / log_stem),
                           "--cache-dir", str(cfg.path("cache_dir")), "--prepared-companions", proofs]
                reason = build_command(command, log, timeout_s=BUILD_TIMEOUT_S, allocation=allocation)
                return {"entry": task.name, "binary": name, "dependencies": task.dependencies,
                        "jobs": allocation.jobs, "memory_mib": allocation.memory_mib,
                        "elapsed_s": round(time.perf_counter() - started, 6), "error": reason}

            results, concurrency = run_tasks(builds, jobs=jobs, memory_mib=memory, run=compile_tool,
                                             failed=lambda row: row["error"] is not None)
        trim_cache(cfg)
        rows = [results[task.name] for task in builds if task.name in results]
        write_json_atomic(schedule_path, {**concurrency, "builds": rows,
                                         "not_run": [task.name for task in builds if task.name not in results]})
        for row in rows:
            if row["error"] is not None:
                raise ValueError(f"{row['binary']}: {row['error']}")
        overrides = {"ouro1": compiler, **{
            "ouro-" + tool: binary("ouro-" + tool, directory=directory) for tool in TOOLS
        }}
        evidence = toolchain_evidence(compiler, overrides)
        if digest(compiler) != producer_hash:
            raise ValueError("native producer changed during tool preparation")
    return overrides, evidence


def build_command(argv: list[str], log: Path, *, timeout_s: float = 600,
                  allocation: Allocation | None = None, shell_path: Path | None = None) -> str | None:
    try:
        env = environment(jobs=allocation.jobs if allocation else None, build=True, shell_path=shell_path)
        if allocation is None:
            memory_mib = build_memory_mib()
            env[MEMORY_ENV] = str(memory_mib)
        else:
            memory_mib = allocation.memory_mib
            env.update(allocation.environment())
        proc = run_limited(argv, cwd=ROOT, env=env, timeout_s=timeout_s, memory_mb=memory_mib)
    except OSError as exc:
        return str(exc)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if not proc.ok:
        return f"{proc.classify()} exit={proc.returncode}; see {log}"
    return None


def ensure_compiler(log: Path | None = None) -> str | None:
    path = ROOT / "_build/smith/compiler-build.log" if log is None else log
    path.parent.mkdir(parents=True, exist_ok=True)
    jobs = job_count()
    memory = available_memory_mib() if MEMORY_ENV in os.environ else None
    return build_command(
        [sys.executable, str(ROOT / "scripts/ouro_build.py"), "build", "--jobs", str(jobs)],
        path, allocation=Allocation(jobs, memory) if memory is not None else None,
    )


def ensure_tools(out: Path, required: tuple[str, ...] = TOOLS) -> str | None:
    if not required or len(set(required)) != len(required):
        raise ValueError("native tool selection must be nonempty and unique")
    for tool in required:
        tool_entry(tool)
    reason = ensure_compiler(out / "compiler-build.log")
    if reason:
        return reason
    for tool in required:
        target = build_config().path("c_build_dir") / ("ouro-" + tool)
        sh = shell()
        reason = build_command([str(sh), str(ROOT / "scripts/build_tool.sh"),
                                tool_entry(tool), target.as_posix()], out / f"{tool}-build.log", shell_path=sh)
        if reason:
            return reason
        binary("ouro-" + tool)
    return None
