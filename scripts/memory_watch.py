#!/usr/bin/env python3
"""Measure a command's peak RSS and compare it with an Ouro memory budget."""
from __future__ import annotations

import argparse
import os
import platform
import signal
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Optional, Sequence

try:
    import resource as resource_mod
except ImportError:  # Windows
    resource_mod = None

from repo_support import write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
REPORT_KIND = "ouro.memory-watch-report.v1"


def rusage_kb(value: int) -> int:
    # Linux reports ru_maxrss in KiB; Darwin/BSD report bytes.
    return int(value // 1024) if platform.system() == "Darwin" else int(value)


def read_rss_kb_win(pid: int) -> int:
    import ctypes
    from ctypes import wintypes

    class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_VM_READ = 0x0010
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, int(pid))
    if not handle:
        return 0
    try:
        counters = PROCESS_MEMORY_COUNTERS_EX()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return 0
        return int(counters.WorkingSetSize // 1024)
    finally:
        kernel32.CloseHandle(handle)


def read_rss_kb(pid: int) -> int:
    if os.name == "nt":
        return read_rss_kb_win(pid)
    try:
        with open(f"/proc/{pid}/statm", "r", encoding="utf-8") as handle:
            parts = handle.read().split()
    except OSError:
        return 0
    if len(parts) < 2:
        return 0
    try:
        pages = int(parts[1])
    except ValueError:
        return 0
    page_kb = max(1, int(os.sysconf("SC_PAGE_SIZE") // 1024))
    return pages * page_kb


def proc_parent_map_win() -> dict[int, int]:
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    TH32CS_SNAPPROCESS = 0x00000002
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return {}
    out: dict[int, int] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        if not kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            return {}
        while True:
            out[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                break
        return out
    finally:
        kernel32.CloseHandle(snap)


def process_create_time_win(pid: int) -> int:
    """100-nanosecond ticks since 1601, or 0 if the process cannot be queried."""
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_QUERY_INFORMATION, False, int(pid))
    if not handle:
        return 0
    try:
        created = FILETIME()
        exited = FILETIME()
        kernel = FILETIME()
        user = FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return 0
        return (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
    finally:
        kernel32.CloseHandle(handle)


def proc_parent_map() -> dict[int, int]:
    if os.name == "nt":
        return proc_parent_map_win()
    out: dict[int, int] = {}
    proc = Path("/proc")
    if not proc.is_dir():
        return out
    for child in proc.iterdir():
        name = child.name
        if not name.isdigit():
            continue
        pid = int(name)
        try:
            stat = (child / "stat").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        close = stat.rfind(")")
        if close < 0:
            continue
        rest = stat[close + 2 :].split()
        if len(rest) < 2:
            continue
        try:
            out[pid] = int(rest[1])
        except ValueError:
            continue
    return out


def process_tree(root_pid: int) -> list[int]:
    parents = proc_parent_map()
    children: dict[int, list[int]] = {}
    for pid, ppid in parents.items():
        children.setdefault(ppid, []).append(pid)
    seen: set[int] = set()
    queue = [root_pid]
    while queue:
        pid = queue.pop()
        if pid in seen:
            continue
        seen.add(pid)
        queue.extend(children.get(pid, []))
    if os.name == "nt" and seen:
        root_created = process_create_time_win(root_pid)
        if root_created > 0:
            # PID reuse can make a still-exiting previous child look like it
            # belongs to this sh. Keep only processes created with or after
            # the watched root.
            seen = {pid for pid in seen if pid == root_pid or process_create_time_win(pid) >= root_created}
    return sorted(seen)


def tree_rss_kb(root_pid: int) -> int:
    return sum(read_rss_kb(pid) for pid in process_tree(root_pid))


def terminate_pid_win(pid: int) -> None:
    import ctypes

    PROCESS_TERMINATE = 0x0001
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, int(pid))
    if not handle:
        return
    try:
        kernel32.TerminateProcess(handle, 1)
    finally:
        kernel32.CloseHandle(handle)


def terminate_process_tree(process: subprocess.Popen[Any]) -> None:
    if os.name == "nt":
        tree = process_tree(process.pid)
        for pid in reversed([pid for pid in tree if pid != process.pid]):
            terminate_pid_win(pid)
        terminate_pid_win(process.pid)
        return
    # Nested bounded runners start their own sessions. Killing only the outer
    # process group leaves those measured descendants running after a failure.
    for pid in reversed(process_tree(process.pid)):
        if pid != process.pid:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_measured(
    command: Sequence[str],
    *,
    cwd: Path,
    label: str,
    budget_kb: Optional[int],
    sample_interval_s: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    before = 0
    if resource_mod is not None:
        before = resource_mod.getrusage(resource_mod.RUSAGE_CHILDREN).ru_maxrss
    proc_available = Path("/proc").is_dir() or os.name == "nt"
    peak_tree_kb = 0
    popen_kwargs: dict[str, Any] = {}
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True
    p = subprocess.Popen(list(command), cwd=str(cwd), **popen_kwargs)
    terminated_for_budget = False
    try:
        while p.poll() is None:
            if proc_available:
                current_tree_kb = tree_rss_kb(p.pid)
                peak_tree_kb = max(peak_tree_kb, current_tree_kb)
                if budget_kb is not None and current_tree_kb > budget_kb:
                    terminated_for_budget = True
                    terminate_process_tree(p)
                    break
            time.sleep(sample_interval_s)
        if proc_available:
            peak_tree_kb = max(peak_tree_kb, tree_rss_kb(p.pid))
    finally:
        rc = int(p.wait())
    child_peak_kb = 0
    if resource_mod is not None:
        after = resource_mod.getrusage(resource_mod.RUSAGE_CHILDREN).ru_maxrss
        child_peak_kb = max(0, rusage_kb(after) - rusage_kb(before))
    # ru_maxrss is a high-water mark, so subtraction may be zero after a larger
    # earlier child.  In a one-command watch process it is still a useful
    # fallback, while /proc or Win32 sampling gives process-tree attribution.
    peak_kb = peak_tree_kb if proc_available and peak_tree_kb > 0 else child_peak_kb
    elapsed = time.perf_counter() - started
    budget_status = "unbudgeted"
    if budget_kb is not None:
        budget_status = "pass" if peak_kb <= budget_kb and rc == 0 else "fail"
    return {
        "kind": REPORT_KIND,
        "label": label,
        "command": list(command),
        "cwd": str(cwd),
        "returncode": rc,
        "elapsed_s": round(elapsed, 6),
        "peak_rss_kb": int(peak_kb),
        "peak_rss_mib": round(peak_kb / 1024.0, 3),
        "budget_kb": budget_kb,
        "budget_mib": None if budget_kb is None else round(budget_kb / 1024.0, 3),
        "budget_status": budget_status,
        "measurement": {
            "proc_tree_peak_kb": int(peak_tree_kb),
            "rusage_children_delta_kb": int(child_peak_kb),
            "sample_interval_s": sample_interval_s,
            "proc_tree_available": proc_available,
            "terminated_for_budget": terminated_for_budget,
            "note": "Linux /proc tree sampling is preferred; Windows uses WorkingSetSize; resource.getrusage is a best-effort fallback.",
        },
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    budget = report.get("budget_kb")
    lines = [
        f"# Memory watch: {report['label']}",
        "",
        f"- command: `{shlex.join(report['command'])}`",
        f"- returncode: `{report['returncode']}`",
        f"- elapsed: `{report['elapsed_s']}s`",
        f"- peak RSS: `{report['peak_rss_kb']} KiB` (`{report['peak_rss_mib']} MiB`)",
        f"- budget: `{'none' if budget is None else str(budget) + ' KiB'}`",
        f"- status: `{report['budget_status']}`",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--label", default=None)
    ap.add_argument("--budget-kb", type=int, default=None)
    ap.add_argument("--cwd", default=str(ROOT))
    ap.add_argument("--json", dest="json_path", default=None)
    ap.add_argument("--markdown", default=None)
    ap.add_argument("--sample-interval", type=float, default=0.05)
    ap.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        ap.error("missing command after --")
    label = args.label or Path(command[0]).name
    cwd = Path(args.cwd)
    if not cwd.is_absolute():
        cwd = ROOT / cwd
    report = run_measured(
        command,
        cwd=cwd,
        label=label,
        budget_kb=args.budget_kb,
        sample_interval_s=max(0.01, args.sample_interval),
    )
    if args.json_path:
        write_json_atomic(Path(args.json_path), report)
    if args.markdown:
        write_markdown(Path(args.markdown), report)
    print(
        "MEMORY_WATCH"
        f" label={label} rc={report['returncode']}"
        f" peak_rss_kb={report['peak_rss_kb']}"
        f" budget_kb={report['budget_kb']}"
        f" status={report['budget_status']}"
        f" elapsed_s={report['elapsed_s']}"
        f" cmd={shlex.join(command)}"
    )
    if report["returncode"] != 0:
        return int(report["returncode"])
    if report["budget_status"] == "fail":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
