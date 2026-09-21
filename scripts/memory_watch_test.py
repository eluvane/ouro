#!/usr/bin/env python3
"""Process-tree enforcement across nested POSIX sessions."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import memory_watch


@unittest.skipUnless(os.name == "posix" and Path("/proc").is_dir(), "Linux process inventory required")
class MemoryWatchTerminationTests(unittest.TestCase):
    def test_nested_session_is_terminated_with_measured_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "child.pid"
            child = ("import os,time; from pathlib import Path; "
                     f"p=Path({str(marker)!r}); temporary=p.with_suffix('.tmp'); "
                     "temporary.write_text(str(os.getpid())); temporary.replace(p); time.sleep(60)")
            parent = ("import subprocess,sys,time; "
                      f"subprocess.Popen([sys.executable,'-c',{child!r}],start_new_session=True); "
                      "time.sleep(60)")
            process = subprocess.Popen([sys.executable, "-c", parent], start_new_session=True)
            child_pid = None
            try:
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(marker.exists(), "nested child did not start")
                child_pid = int(marker.read_text())
                self.assertIn(child_pid, memory_watch.process_tree(process.pid))
                self.assertNotEqual(os.getpgid(child_pid), os.getpgid(process.pid))
                memory_watch.terminate_process_tree(process)
                process.wait(timeout=5)
                status = Path("/proc") / str(child_pid) / "stat"
                deadline = time.monotonic() + 5
                while status.exists() and time.monotonic() < deadline:
                    try:
                        state = status.read_text().split(") ", 1)[1].split()[0]
                    except FileNotFoundError:
                        break
                    if state == "Z":
                        break
                    time.sleep(0.01)
                else:
                    if status.exists():
                        self.fail("measured descendant survived in its separate session")
            finally:
                for pid in (child_pid, process.pid):
                    if pid is not None:
                        try:
                            os.kill(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
