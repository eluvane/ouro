"""Bounded process trees with scrubbed environment and explicit failures.

Windows uses a Job Object with a shared commit limit. POSIX uses inherited
RLIMIT_AS per process and a session for tree termination. Neither is an access
control sandbox; generated programs must remain repository-controlled input.
"""
from __future__ import annotations

import math
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Sequence

ENV_KEYS = frozenset({"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR"})


def clean_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key.upper() in ENV_KEYS}
    env.update({"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONIOENCODING": "utf-8", "PYTHONHASHSEED": "0"})
    return env


@dataclass
class RunResult:
    status: str
    returncode: Optional[int]
    stdout: str
    stderr: str
    elapsed_s: float
    peak_rss_mb: float
    argv: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "ok" and self.returncode == 0

    def classify(self) -> str:
        if self.status != "ok":
            return self.status
        if self.returncode == 0:
            return "ok"
        if self.returncode is not None and (self.returncode < 0 or self.returncode >= 0xC0000000 or self.returncode in {134, 136, 139}):
            return "crash"
        return "nonzero"


def kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        if proc.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        # The leader may have exited while descendants still hold the pipes.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if proc.poll() is None:
        proc.kill()


def run_limited(
    argv: Sequence[str], *, timeout_s: float, memory_mb: int,
    cwd: Optional[Path] = None, env: Optional[Mapping[str, str]] = None,
    stdin_text: Optional[str] = None,
) -> RunResult:
    if not argv or not math.isfinite(timeout_s) or timeout_s <= 0 or memory_mb <= 0:
        raise ValueError("command, positive finite timeout, and positive memory limit are required")
    started = time.perf_counter()
    argv = list(map(str, argv))
    job = None
    proc = None
    peak_mb = 0.0
    status = "ok"
    child_env = clean_env() if env is None else dict(env)
    executable = shutil.which(argv[0], path=child_env.get("PATH"))
    if executable is None and Path(argv[0]).is_file():
        executable = str(Path(argv[0]).resolve())
    if executable is None:
        return RunResult("spawn-error", None, "", f"executable not found: {argv[0]}", 0.0, 0.0, argv)
    command = [executable, *argv[1:]]
    try:
        options = {}
        if os.name == "nt":
            from ourosmith.windows_job import Job

            job = Job(memory_mb)
            limit = job.name
            options["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
        else:
            limit = str(memory_mb)
            options["start_new_session"] = True
        # Windows venv redirectors own a kill-on-close job themselves. The
        # trusted stdlib-only launcher must not acquire that extra lifetime;
        # OuroSmith's job owns the command and all of its descendants.
        interpreter = getattr(sys, "_base_executable", sys.executable) if os.name == "nt" else sys.executable
        launcher = [interpreter, str(Path(__file__).with_name("exec_child.py")), limit, *command]
        proc = subprocess.Popen(launcher, cwd=cwd, env=child_env,
                                stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options)
        try:
            # Binary pipes preserve LSP Content-Length and CRLF exactly on
            # Windows; TextIOWrapper would translate existing CRLF twice.
            stdout, stderr = proc.communicate(input=stdin_text.encode("utf-8") if stdin_text is not None else None, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            status = "timeout"
            if job:
                job.terminate()
            kill_tree(proc)
            stdout, stderr = proc.communicate(timeout=10)
        stdout = stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")
        stderr = stderr.decode("utf-8", errors="replace").replace("\r\n", "\n")
        if job:
            exceeded, peak_mb = job.memory()
            if exceeded:
                status = "memory"
        if proc.returncode != 0 and ("MemoryError" in stderr or "Cannot allocate memory" in stderr):
            status = "memory"
        if stderr.startswith("OURO_SMITH_LIMIT_SETUP:"):
            status = "spawn-error"
        return RunResult(status, proc.returncode, stdout, stderr, time.perf_counter() - started, peak_mb, argv)
    except OSError as exc:
        return RunResult("spawn-error", None, "", str(exc), time.perf_counter() - started, peak_mb, argv)
    finally:
        if job:
            job.close()
        if proc:
            kill_tree(proc)
            proc.wait(timeout=10)
