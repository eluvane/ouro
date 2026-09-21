"""Windows job limits, including descendants; no third-party process library.

The parent owns the job. A trusted Python launcher joins it before starting
the tested executable, so generated code cannot run before assignment.
See https://learn.microsoft.com/windows/win32/procthread/job-objects .
"""
from __future__ import annotations

import ctypes
import uuid
from ctypes import wintypes as W

from repo_support import checked_windows_result as checked


class BasicLimits(ctypes.Structure):
    _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                ("flags", W.DWORD), ("min_working_set", ctypes.c_size_t),
                ("max_working_set", ctypes.c_size_t), ("active_processes", W.DWORD),
                ("affinity", ctypes.c_size_t), ("priority", W.DWORD),
                ("scheduling", W.DWORD)]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", BasicLimits), ("io", ctypes.c_uint64 * 6),
                ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]


class CompletionPort(ctypes.Structure):
    _fields_ = [("key", ctypes.c_void_p), ("port", W.HANDLE)]


def api(name, result, args):
    fn = getattr(ctypes.WinDLL("kernel32", use_last_error=True), name)
    fn.restype, fn.argtypes = result, args
    return fn


close_handle = api("CloseHandle", W.BOOL, [W.HANDLE])
set_information = api("SetInformationJobObject", W.BOOL, [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD])


class Job:
    def __init__(self, memory_mb: int):
        self.name = "Local\\OuroSmith-" + uuid.uuid4().hex
        self.handle = checked(api("CreateJobObjectW", W.HANDLE, [ctypes.c_void_p, W.LPCWSTR])(None, self.name))
        self.port = None
        try:
            limits = ExtendedLimits()
            # JOB_MEMORY | KILL_ON_JOB_CLOSE | DIE_ON_UNHANDLED_EXCEPTION.
            limits.basic.flags = 0x200 | 0x2000 | 0x400
            limits.job_memory = memory_mb * 1024 * 1024
            checked(set_information(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
            self.port = checked(api("CreateIoCompletionPort", W.HANDLE,
                                    [W.HANDLE, W.HANDLE, ctypes.c_size_t, W.DWORD])(
                                        W.HANDLE(-1), None, 0, 1))
            association = CompletionPort(1, self.port)
            checked(set_information(self.handle, 7, ctypes.byref(association), ctypes.sizeof(association)))
        except OSError:
            self.close()
            raise

    def memory(self) -> tuple[bool, float]:
        """Drain memory-limit notifications and query committed job memory."""
        event, key, overlapped = W.DWORD(), ctypes.c_size_t(), ctypes.c_void_p()
        get = api("GetQueuedCompletionStatus", W.BOOL,
                  [W.HANDLE, ctypes.POINTER(W.DWORD), ctypes.POINTER(ctypes.c_size_t),
                   ctypes.POINTER(ctypes.c_void_p), W.DWORD])
        exceeded = False
        while get(self.port, ctypes.byref(event), ctypes.byref(key), ctypes.byref(overlapped), 0):
            exceeded |= event.value in {9, 10}
        limits = ExtendedLimits()
        checked(api("QueryInformationJobObject", W.BOOL,
                    [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD, ctypes.c_void_p])(
                        self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits), None))
        return exceeded, limits.peak_job / (1024 * 1024)

    def terminate(self):
        checked(api("TerminateJobObject", W.BOOL, [W.HANDLE, W.UINT])(self.handle, 1))

    def close(self):
        if self.handle:
            close_handle(self.handle)
            self.handle = None
        if self.port:
            close_handle(self.port)
            self.port = None


def join(name: str):
    job = checked(api("OpenJobObjectW", W.HANDLE, [W.DWORD, W.BOOL, W.LPCWSTR])(1, False, name))
    try:
        current = api("GetCurrentProcess", W.HANDLE, [])()
        checked(api("AssignProcessToJobObject", W.BOOL, [W.HANDLE, W.HANDLE])(job, current))
    finally:
        checked(close_handle(job))
