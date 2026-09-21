#!/usr/bin/env python3
"""Small shared helpers for repository-local Python gates and build tools.

Keep this module dependency-free: it is imported by trust, release, cache, and
workflow checks that must run on a plain Python installation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence


def configure_native_stack() -> None:
    """Match OuroSmith's native stack reserve without raising the hard cap.

    Homebrew and framework CPython on macOS pin the main-thread stack, so
    ``setrlimit(RLIMIT_STACK)`` raises even for the current values. Keep the
    inherited limit instead of aborting bootstrap on those hosts.
    """
    if os.name == "nt":
        return
    import resource

    soft, hard = resource.getrlimit(resource.RLIMIT_STACK)
    if soft == resource.RLIM_INFINITY:
        return
    target = max(soft, 128 * 1024 * 1024)
    if hard != resource.RLIM_INFINITY and hard >= 0:
        target = min(target, hard)
    if target == soft:
        return
    try:
        resource.setrlimit(resource.RLIMIT_STACK, (target, hard))
    except (OSError, ValueError):
        return


def relative_path(root: Path, path: Path, *, resolve: bool = True) -> str:
    """Return a deterministic POSIX path, relative to *root* when possible."""
    base = root.resolve() if resolve else root
    candidate = path.resolve() if resolve else path
    try:
        return candidate.relative_to(base).as_posix()
    except ValueError:
        return candidate.as_posix()


def bind_relative_path(root: Path, *, resolve: bool = True) -> Callable[[Path], str]:
    """Bind ``relative_path`` to a repository root for concise call sites."""
    return lambda path: relative_path(root, path, resolve=resolve)


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Hash a file without loading it into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: Path, data: Any) -> None:
    """Write sorted, newline-terminated JSON through an atomic replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def write_json_atomic_compact(path: Path, data: Any) -> None:
    """Write compact sorted JSON atomically for compact legacy report paths."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    tmp.write_text(
        json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def resolve_repo_path(root: Path, value: str) -> Path:
    """Return *value* as a path, resolving repo-relative spellings against *root*."""
    path = Path(value)
    if path.is_absolute():
        return path
    return root / path


def available_memory_mb() -> int | None:
    """Best-effort available physical memory in MiB, or None when unknown.

    Stdlib only: reads /proc/meminfo on Linux, GlobalMemoryStatusEx on Windows,
    and SC_AVPHYS_PAGES elsewhere. Returning None means "no information", and
    callers must then leave their configured concurrency untouched.
    """
    try:
        meminfo = Path("/proc/meminfo")
        if meminfo.is_file():
            for line in meminfo.read_text(encoding="utf-8").splitlines():
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    if os.name == "nt":
        try:
            import ctypes

            class _MemStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemStatus()
            status.dwLength = ctypes.sizeof(_MemStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullAvailPhys) // (1024 * 1024)
        except (OSError, AttributeError, ValueError):
            pass
    try:
        pages = os.sysconf("SC_AVPHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if pages > 0 and page_size > 0:
            return (pages * page_size) // (1024 * 1024)
    except (ValueError, OSError, AttributeError):
        pass
    return None


def memory_aware_jobs(
    requested: int,
    *,
    per_worker_mb: int,
    reserve_mb: int = 1024,
    enabled: bool = True,
) -> tuple[int, str | None]:
    """Clamp a worker count down to what free memory can hold.

    Returns ``(jobs, note)``. ``jobs`` never exceeds ``requested`` and never
    drops below 1, so a healthy machine keeps its full parallelism and only a
    memory-starved host is throttled -- this is a cap, not forced serial work.
    ``note`` is a short human string when the count was reduced, else None.
    """
    if requested <= 1 or per_worker_mb <= 0 or not enabled:
        return max(1, requested), None
    avail = available_memory_mb()
    if avail is None:
        return requested, None
    usable = avail - reserve_mb
    if usable <= 0:
        capped = 1
    else:
        capped = max(1, usable // per_worker_mb)
    capped = min(requested, capped)
    if capped >= requested:
        return requested, None
    note = (
        f"memory-aware jobs {requested}->{capped} "
        f"(avail={avail}MiB reserve={reserve_mb}MiB per_worker={per_worker_mb}MiB)"
    )
    return capped, note


def parse_json_value(text: str) -> tuple[Any, str | None]:
    """Return ``(value, None)`` or ``(None, error)`` for a JSON string."""
    try:
        return json.loads(text), None
    except (ValueError, TypeError) as exc:
        return None, str(exc)


def read_json_value(path: Path) -> tuple[Any, str | None]:
    """Return ``(value, None)`` or ``(None, error)`` for a UTF-8 JSON file."""
    try:
        return parse_json_value(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        return None, str(exc)


def read_json_object_or_none(path: Path) -> dict | None:
    """A missing, invalid or non-object cache file is a cache miss."""
    value, error = read_json_value(path)
    return value if error is None and isinstance(value, dict) else None


def bool_env(value: object, default: bool = True) -> bool:
    """Decode optional build toggles, retaining the caller's unknown default."""
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


NATIVE_REPO_GATE_REPORT_KIND = "ouro.repo-gate-report.v1"
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")


@dataclass(frozen=True)
class NativeGateOutcome:
    """Observed native invocation plus a validated, fail-closed report view."""

    returncode: int
    native_returncode: int | None
    command: tuple[str, ...]
    report_path: Path
    report: dict[str, Any]
    report_valid: bool
    error: str | None


def resolve_repo_local_path(root: Path, value: str | Path, *, label: str) -> Path:
    """Resolve a control-plane path and reject repo escapes on every host."""
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} is empty")
    if os.name != "nt" and _WINDOWS_ABSOLUTE.match(text):
        raise ValueError(
            f"{label} is a Windows absolute path on a non-Windows host: {text}"
        )
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = root / candidate
    base = root.resolve()
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"{label} escapes repository root: {text}") from exc
    return resolved



def native_gate_options(
    argv: Sequence[str] | None, *, checkout_root: Path, description: str | None,
    work_env: str, default_work: str, report_name: str,
) -> tuple[Path, Path, Path]:
    """Parse compatibility options without moving gate policy into the host."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--work", default=os.environ.get(work_env, default_work))
    parser.add_argument("--report", default=None)
    args = parser.parse_args(argv)

    def checked(value: str, label: str) -> Path:
        try:
            return resolve_repo_local_path(checkout_root, value, label=label)
        except ValueError as exc:
            parser.error(str(exc))
        raise AssertionError("argparse.error must exit")

    # Preserve validation order and the legacy empty --report/root behavior.
    work = checked(args.work, "--work")
    report = checked(args.report, "--report") if args.report else work / report_name
    override = os.environ.get("OURO_REPO_GATE_ROOT", "").strip()
    scan_root = checked(override, "OURO_REPO_GATE_ROOT") if override else checkout_root
    return work, report, scan_root


def _synthetic_native_gate_failure(
    *, profile: str, report_path: Path, reason: str, path_label: str | None = None
) -> dict[str, Any]:
    return {
        "kind": NATIVE_REPO_GATE_REPORT_KIND,
        "version": "1",
        "profile": profile,
        "execution_backend": "ouro-native-repo-gate",
        "execution_mode": "native",
        "pass": False,
        "gates": [],
        "issues": [{"reason": reason, "path": path_label or report_path.name}],
        "report_state": "synthetic-failure",
    }


def _native_gate_report_errors(
    data: Any, *, profile: str, native_returncode: int
) -> list[str]:
    if not isinstance(data, dict):
        return ["native report is not a JSON object"]
    errors: list[str] = []
    if data.get("kind") != NATIVE_REPO_GATE_REPORT_KIND:
        errors.append(f"native report kind is not {NATIVE_REPO_GATE_REPORT_KIND}")
    if data.get("version") != "1":
        errors.append("native report version is not 1")
    if data.get("profile") != profile:
        errors.append(f"native report profile is not {profile}")
    if data.get("execution_backend") != "ouro-native-repo-gate":
        errors.append("native report execution_backend is not ouro-native-repo-gate")
    if data.get("execution_mode") != "native":
        errors.append("native report execution_mode is not native")
    passed = data.get("pass")
    if not isinstance(passed, bool):
        errors.append("native report pass field is not boolean")
    gates = data.get("gates")
    if not isinstance(gates, list) or not gates:
        errors.append("native report has no selected gates")
    if not isinstance(data.get("issues"), list):
        errors.append("native report issues field is not an array")
    if native_returncode == 0 and passed is not True:
        errors.append("native command returned 0 but report did not pass")
    if native_returncode != 0 and passed is True:
        errors.append(
            f"native command returned {native_returncode} but report claims pass"
        )
    return errors


def _rejected_native_gate_report(
    data: Any,
    *,
    profile: str,
    report_path: Path,
    errors: Sequence[str],
    path_label: str,
) -> dict[str, Any]:
    if isinstance(data, dict):
        report = dict(data)
        raw_issues = report.get("issues")
        issues = list(raw_issues) if isinstance(raw_issues, list) else []
        issues.extend(
            {"reason": f"native report rejected: {error}", "path": path_label}
            for error in errors
        )
        report.update(
            {
                "kind": NATIVE_REPO_GATE_REPORT_KIND,
                "version": "1",
                "profile": profile,
                "execution_backend": "ouro-native-repo-gate",
                "execution_mode": "native",
                "pass": False,
                "issues": issues,
                "report_state": "rejected",
            }
        )
        if not isinstance(report.get("gates"), list):
            report["gates"] = []
        return report
    return _synthetic_native_gate_failure(
        profile=profile,
        report_path=report_path,
        reason="; ".join(errors),
        path_label=path_label,
    )


def run_native_repo_gate(
    *,
    checkout_root: Path,
    scan_root: Path,
    profile: str,
    native_out: Path,
) -> NativeGateOutcome:
    """Run the native gate without reusing stale or malformed report evidence."""
    report_path = native_out / "repo-gate.json"
    report_label = relative_path(checkout_root, report_path, resolve=False)
    command = (
        "sh",
        "scripts/ouro_repo_gate.sh",
        "--profile",
        profile,
        "--root",
        str(scan_root),
        "--out",
        str(native_out),
    )
    try:
        report_path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        reason = f"cannot remove stale native report before delegation: {exc}"
        return NativeGateOutcome(
            returncode=1,
            native_returncode=None,
            command=command,
            report_path=report_path,
            report=_synthetic_native_gate_failure(
                profile=profile,
                report_path=report_path,
                reason=reason,
                path_label=report_label,
            ),
            report_valid=False,
            error=reason,
        )

    try:
        completed = subprocess.run(list(command), cwd=checkout_root, check=False)
    except OSError as exc:
        reason = f"native repository gate could not start: {exc}"
        return NativeGateOutcome(
            returncode=127,
            native_returncode=None,
            command=command,
            report_path=report_path,
            report=_synthetic_native_gate_failure(
                profile=profile,
                report_path=report_path,
                reason=reason,
                path_label=report_label,
            ),
            report_valid=False,
            error=reason,
        )

    native_returncode = int(completed.returncode)
    data, read_error = read_json_value(report_path)
    if read_error is not None:
        errors = [f"native report unavailable or malformed: {read_error}"]
    else:
        errors = _native_gate_report_errors(
            data, profile=profile, native_returncode=native_returncode
        )

    if errors:
        effective = native_returncode if native_returncode != 0 else 1
        return NativeGateOutcome(
            returncode=effective,
            native_returncode=native_returncode,
            command=command,
            report_path=report_path,
            report=_rejected_native_gate_report(
                data,
                profile=profile,
                report_path=report_path,
                errors=errors,
                path_label=report_label,
            ),
            report_valid=False,
            error="; ".join(errors),
        )

    assert isinstance(data, dict)
    return NativeGateOutcome(
        returncode=native_returncode,
        native_returncode=native_returncode,
        command=command,
        report_path=report_path,
        report=data,
        report_valid=True,
        error=None,
    )


def native_gate_compatibility_metadata(
    outcome: NativeGateOutcome, *, checkout_root: Path
) -> dict[str, Any]:
    """Describe an explicit compatibility delegation without leaking host paths."""

    def display_arg(arg: str) -> str:
        path = Path(arg)
        if path.is_absolute():
            return relative_path(checkout_root, path, resolve=False)
        return arg

    return {
        "mode": "compatibility-wrapper",
        "execution_backend": "python-compatibility-wrapper",
        "delegated_backend": "ouro-native-repo-gate",
        "command": [display_arg(arg) for arg in outcome.command],
        "native_returncode": outcome.native_returncode,
        "effective_returncode": outcome.returncode,
        "native_report": relative_path(
            checkout_root, outcome.report_path, resolve=False
        ),
        "native_report_valid": outcome.report_valid,
        "error": outcome.error,
    }


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_json_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def finite_number(value, minimum=0) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= minimum


def hash_json(data: object) -> str:
    return sha256_bytes(json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8"))


class Timer:
    def __init__(self) -> None:
        self.t0 = time.perf_counter()

    def elapsed(self) -> float:
        return time.perf_counter() - self.t0


def filename_fragment(text: str, limit: int, empty: str) -> str:
    """Readable cache label only; callers retain their length and empty policy."""
    fragment = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in text)
    return fragment.strip("_")[:limit] or empty


def read_required_text(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SystemExit(f"{label}: FAIL unreadable {path}: {exc}") from exc


def checked_windows_result(value):
    """Preserve the thread-local Win32 error before another host API call."""
    import ctypes

    if not value:
        raise ctypes.WinError(ctypes.get_last_error())
    return value
