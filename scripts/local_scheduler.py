"""Allocate CPU slots and memory to local tasks and their subprocesses."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from repo_support import available_memory_mb, hash_json, sha256_file

JOBS_ENV = "OURO_SCHEDULER_JOBS"
MEMORY_ENV = "OURO_SCHEDULER_MEMORY_MIB"
MAX_CPU_SLOTS = 20
DEFAULT_JOBS = MAX_CPU_SLOTS
MEMORY_HEADROOM_MIB = 1024


def positive_integer(value: str, name: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if number < 1:
        raise ValueError(f"{name} must be a positive integer")
    return number


def bounded_jobs(requested: int) -> int:
    requested = min(requested, MAX_CPU_SLOTS)
    ceiling = os.environ.get(JOBS_ENV)
    return min(requested, positive_integer(ceiling, JOBS_ENV)) if ceiling is not None else requested


def configured_jobs() -> int:
    value = os.environ.get("OURO_JOBS", str(DEFAULT_JOBS))
    return bounded_jobs((os.cpu_count() or 1) if value == "auto" else positive_integer(value, "OURO_JOBS"))


def available_memory_mib(*, minimum_mib: int = 1) -> int | None:
    ceiling = os.environ.get(MEMORY_ENV)
    if ceiling is not None:
        return positive_integer(ceiling, MEMORY_ENV)
    available = available_memory_mb()
    return max(minimum_mib, available - MEMORY_HEADROOM_MIB) if available is not None else None


@dataclass(frozen=True)
class Task:
    name: str
    dependencies: tuple[str, ...] = ()
    max_jobs: int | None = None
    memory_mib: int = 1024
    base_memory_mib: int = 0
    preferred_jobs: int = 1

    def memory_for(self, jobs: int) -> int:
        return self.base_memory_mib + jobs * self.memory_mib


@dataclass(frozen=True)
class Allocation:
    jobs: int
    memory_mib: int

    def environment(self) -> dict[str, str]:
        jobs = str(self.jobs)
        return {JOBS_ENV: jobs, MEMORY_ENV: str(self.memory_mib), "OURO_JOBS": jobs,
                "OURO_FRONTEND_JOBS": jobs, "RAYON_NUM_THREADS": jobs}


def run_tasks(tasks, *, jobs, memory_mib, run, stop=None, failed=None):
    """Run ready tasks under fixed allocations, then reclaim each allocation at exit."""
    tasks = tuple(tasks)
    pending = {task.name: task for task in tasks}
    if jobs < 1 or len(pending) != len(tasks):
        raise ValueError("scheduler requires a positive budget and unique task names")
    minimum_task_memory = float("inf")
    for task in tasks:
        if not all(name in pending for name in task.dependencies):
            raise ValueError(f"{task.name}: unknown scheduler dependency")
        task_memory = task.memory_for(1)
        if (task.memory_mib < 0 or task.base_memory_mib < 0 or task_memory < 1 or task.preferred_jobs < 1
                or (task.max_jobs is not None and task.max_jobs < 1)):
            raise ValueError(f"{task.name}: invalid CPU or memory request")
        if memory_mib is not None and task_memory > memory_mib:
            raise ValueError(f"{task.name}: needs at least {task_memory} MiB, budget is {memory_mib} MiB")
        minimum_task_memory = min(minimum_task_memory, task_memory)

    jobs = min(jobs, MAX_CPU_SLOTS)
    started = time.perf_counter()
    stats = {"jobs": jobs, "memory_mib": memory_mib, "peak_tasks": 0, "peak_jobs": 0, "peak_memory_mib": 0}
    results = {}
    active = {}
    stopped = False
    running = {}
    lock = Lock()

    def execute(task, allocation):
        with lock:
            running[task.name] = allocation
            stats["peak_tasks"] = max(stats["peak_tasks"], len(running))
            stats["peak_jobs"] = max(stats["peak_jobs"], sum(lease.jobs for lease in running.values()))
            stats["peak_memory_mib"] = max(stats["peak_memory_mib"], sum(lease.memory_mib for lease in running.values()))
        try:
            return run(task, allocation)
        finally:
            with lock:
                del running[task.name]

    with ThreadPoolExecutor(max_workers=min(jobs, max(1, len(tasks)))) as pool:
        while pending or active:
            free_jobs = jobs - sum(allocation.jobs for _, allocation in active.values())
            free_memory = (memory_mib - sum(allocation.memory_mib for _, allocation in active.values())
                           if memory_mib is not None else float("inf"))
            ready = {}
            if not stopped:
                for task in pending.values():
                    if (task.memory_for(1) <= free_memory
                            and all(name in results for name in task.dependencies)):
                        slots = min(free_jobs, task.max_jobs or jobs, task.preferred_jobs)
                        while task.memory_for(slots) > free_memory:
                            slots -= 1
                        ready[task] = slots
                        free_jobs -= slots
                        free_memory -= task.memory_for(slots)
                        if not free_jobs or free_memory < minimum_task_memory:
                            break
            while free_jobs and ready:
                previous = free_jobs
                for task, slots in ready.items():
                    if free_jobs and slots < (task.max_jobs or jobs) and task.memory_mib <= free_memory:
                        ready[task] += 1
                        free_jobs -= 1
                        free_memory -= task.memory_mib
                if free_jobs == previous:
                    break
            for task, slots in ready.items():
                allocation = Allocation(slots, task.memory_for(slots))
                future = pool.submit(execute, task, allocation)
                active[future] = task.name, allocation
                del pending[task.name]
            if not active:
                if pending and not stopped:
                    raise ValueError(f"scheduler dependency cycle: {', '.join(pending)}")
                break
            complete, _ = wait(active, return_when=FIRST_COMPLETED)
            blocked = set()
            for future in tuple(active):
                if future in complete:
                    name, _ = active.pop(future)
                    result = future.result()
                    results[name] = result
                    if failed is not None and failed(result):
                        blocked.add(name)
                    stopped = stopped or (stop is not None and stop(result))
            while blocked and (rejected := [task.name for task in pending.values()
                                            if blocked.intersection(task.dependencies)]):
                blocked.update(rejected)
                for name in rejected:
                    del pending[name]
    stats["elapsed_s"] = round(time.perf_counter() - started, 6)
    return results, stats


class CheckoutSnapshot:
    def __init__(self, source: Path):
        self.source = source
        self.paths = tuple(dict.fromkeys(Path(os.fsdecode(path)) for path in subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=source,
        ).split(b"\0") if path))

    def content_key(self, root: Path | None = None) -> str:
        root = self.source if root is None else root
        files = {}
        for path in self.paths:
            source = root / path
            if not source.resolve().is_relative_to(root):
                raise ValueError(f"{path}: source escapes the checkout")
            if source.is_symlink():
                files[path.as_posix()] = ("link", source.readlink().as_posix())
            elif source.is_file():
                files[path.as_posix()] = ("file", sha256_file(source))
        return hash_json(files)

    def copy_to(self, destination: Path, *, git_metadata: bool = False) -> None:
        if git_metadata:
            subprocess.run(["git", "clone", "--quiet", "--local", "--shared", "--no-checkout",
                            ".", destination.as_posix()], check=True, cwd=self.source)
            index = Path(os.fsdecode(subprocess.check_output(
                ["git", "rev-parse", "--path-format=absolute", "--git-path", "index"], cwd=self.source,
            ).rstrip(b"\r\n")))
            if index.is_file():
                for shared_index in index.parent.glob("sharedindex.*"):
                    shutil.copyfile(shared_index, destination / ".git" / shared_index.name)
                shutil.copyfile(index, destination / ".git/index")
        else:
            destination.mkdir(parents=True, exist_ok=False)
        # Each invocation owns its destination. Other checkouts have their own parents.
        prepared_parents: set[Path] = set()
        for path in self.paths:
            source = self.source / path
            target = destination / path
            if not source.resolve().is_relative_to(self.source):
                raise ValueError(f"{path}: source escapes the checkout")
            if source.is_symlink() or source.is_file():
                parent = target.parent
                if parent not in prepared_parents:
                    parent.mkdir(parents=True, exist_ok=True)
                    prepared_parents.add(parent)
                if source.is_symlink():
                    link = source.readlink()
                    if link.is_absolute():
                        raise ValueError(f"{path}: absolute symlink cannot be isolated")
                    target.symlink_to(link, target_is_directory=source.is_dir())
                else:
                    shutil.copy2(source, target)
            elif source.is_dir():
                raise ValueError(f"{path}: nested Git checkout cannot be isolated")
