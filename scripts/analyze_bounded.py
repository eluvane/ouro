#!/usr/bin/env python3
"""Run safe repository analyzer profiles in bounded native subprocesses."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from repo_support import configure_native_stack


ROOT = Path(__file__).resolve().parents[1]
TRACE = os.environ.get("OURO_ANALYZE_BATCH_TRACE") == "1"
DEFAULT_API_BASELINE = ROOT / "quality" / "api_surface.tsv"
# Parsed (comments, data) rows keyed by resolved baseline path.
_BASELINE_ROWS: dict[Path, tuple[list[str], list[str]]] = {}
BASELINE_SENTINEL = "__ouro__/baseline.ouro\t__sentinel\t0\tinternal\tinternal"
MAX_GLOBAL_FILES = 8
MAX_GLOBAL_BYTES = 65536
# Covers production sources; memory_budget_suite selects the largest current
# input for the unchanged analyzer-drive-largest-file budget.
MAX_DRIVE_FILE_BYTES = 40960
ALLOW_UNBOUNDED = os.environ.get("OURO_ANALYZE_ALLOW_UNBOUNDED") == "1"
LOW_PRIORITY_FLAGS = (
    getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0) if os.name == "nt" else 0
)
DEFAULT_SCOPES = ("std", "compiler", "tools/analyze", "samples")
# Families of ouro-analyze-drive; one flag per family plus the unions.
DRIVE_FLAGS = {
    "--enable-effects",
    "--enable-capability",
    "--enable-extract",
    "--enable-match",
    "--enable-cfg",
    "--enable-dataflow",
    "--enable-semantic",
    "--enable-property",
    "--enable-absint",
    "--enable-symexec",
    "--enable-taint",
    "--enable-contracts",
    "--enable-metrics",
    "--enable-duplication",
    "--enable-trust",
    "--enable-simplify",
    "--enable-perf",
    "--enable-naming",
    "--enable-errors",
    "--enable-light",
    "--enable-heavy",
    "--enable-strict",
    "--enable-all",
}
BOOL_FLAGS = {
    "--strict",
    "--include-fixtures",
    "--dump-facts",
    "--enable-deadcode",
    "--enable-format",
    "--architecture-only",
} | DRIVE_FLAGS
GLOBAL_FLAGS = {
    "--dump-facts",
    "--enable-deadcode",
    "--enable-heavy",
    "--enable-all",
    "--enable-trust",
    "--architecture-only",
}
# Base-runner flags that need the full source text of each file; every other
# per-file base pass runs on the declaration skeleton.
BASE_TEXT_FLAGS = {"--enable-format", "--enable-light", "--enable-all"}
SUPPRESSION_RE = re.compile(r"(?m)^\s*--\s*ouro-lint:")
BANNER_RE = re.compile(r"^ANALYZE_OK\s+profile=(\S+)\s+(.*)$", re.MULTILINE)
DRIVE_BANNER_RE = re.compile(
    r"^ANALYZE_DRIVE files=(\d+) findings=(\d+) rejected=(\d+) families=([a-z_]+(?:,[a-z_]+)*)\r?$",
    re.MULTILINE,
)
DRIVE_FAMILIES_RE = re.compile(r"ANALYZE_FAMILIES families=([a-z_]+(?:,[a-z_]+)*)\r?\n?")
DRIVE_FINDING_RE = re.compile(
    r"^(.+?):(\d+):(\d+): (warning|error)\[(OURO-[A-Z]+\d+)\] ([a-z_]+)/", re.MULTILINE,
)
DRIVE_RECORD_RE = re.compile(
    DRIVE_FINDING_RE.pattern + r"[^\n]*\n"
    r"  hint: [^\n]*\n  witness: [^\n]*(?:\n|$)", re.MULTILINE,
)
DRIVE_REJECT_RE = re.compile(r"^(.+?): structured analyzer could not build the unit: (\S+)\r?$", re.MULTILINE)
DRIVE_COUNT_ORDER = ("files", "findings", "rejected")
COUNT_ORDER = (
    "files",
    "imports",
    "decls",
    "refs",
    "exports",
    "constructors",
    "modules",
    "branches",
    "suppressions",
    "strict-diagnostics",
)


def trace(message: str) -> None:
    if TRACE:
        print(f"ANALYZE_BOUNDED {message}", file=sys.stderr, flush=True)


FIXTURE_PREFIXES = (
    "test/",
    "tests/",
    "quality/fixtures/",
    "samples/bench/synthesis/",
    "samples/examples/future/",
    "samples/examples/bad_",
)
FIXTURE_INFIXES = ("/test/", "/tests/", "/quality/fixtures/")
FIXTURE_EXACT = ("samples/tutorial/04_holes.ouro",)
SKIP_DIR_NAMES = {".git", "_build", "_cache", "_opam", "_tools", "node_modules"}


def is_fixture(path: str) -> bool:
    p = path.replace("\\", "/")
    if p in FIXTURE_EXACT:
        return True
    if p.startswith(FIXTURE_PREFIXES):
        return True
    return any(marker in p for marker in FIXTURE_INFIXES)


def repo_relative(path: Path) -> str | None:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except (OSError, ValueError):
        return None


def walk_error(error: OSError) -> None:
    raise error


def parse_analyzer_args(argv: Sequence[str], caller: Path) -> tuple[list[str], list[Path]] | None:
    passthrough: list[str] = []
    scopes: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in BOOL_FLAGS:
            passthrough.append(arg)
            i += 1
            continue
        if arg == "--api-baseline":
            if i + 1 >= len(argv):
                return None
            baseline = Path(argv[i + 1])
            if not baseline.is_absolute():
                baseline = caller / baseline
            passthrough.extend((arg, str(baseline.resolve())))
            i += 2
            continue
        if arg == "--scope":
            if i + 1 >= len(argv):
                return None
            scopes.append(argv[i + 1])
            i += 2
            continue
        if arg.startswith("-"):
            return None
        scopes.append(arg)
        i += 1

    roots = scopes or list(DEFAULT_SCOPES)
    files: list[Path] = []
    seen: set[Path] = set()
    include_fixtures = "--include-fixtures" in passthrough
    for raw in roots:
        path = Path(raw)
        if not path.is_absolute():
            path = caller / path
        if path.is_dir():
            # Prune generated/dependency trees before enumerating their files.
            # An explicitly selected file or directory remains a valid scope.
            found = []
            for directory, children, names in os.walk(path, onerror=walk_error):
                children[:] = sorted(name for name in children if name not in SKIP_DIR_NAMES)
                found.extend(Path(directory) / name for name in names if name.endswith(".ouro"))
            found.sort()
        elif path.is_file() and path.suffix == ".ouro":
            found = [path]
        else:
            return None
        for item in found:
            resolved = item.resolve()
            rel = repo_relative(resolved)
            if rel is None:
                return None
            if not include_fixtures and is_fixture(rel):
                continue
            if resolved not in seen:
                seen.add(resolved)
                files.append(resolved)
    files.sort(key=lambda p: repo_relative(p) or str(p))
    return passthrough, files


def run_native(binary: Path, argv: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        [str(binary), *argv],
        cwd=cwd,
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        creationflags=LOW_PRIORITY_FLAGS,
    )
    # Windows subprocess text readers decode in background threads. Capture
    # bytes so invalid UTF-8 raises in the caller, never leaves a missing stream.
    def report_text(data: bytes) -> str:
        return data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")

    return subprocess.CompletedProcess(proc.args, proc.returncode,
                                       report_text(proc.stdout), report_text(proc.stderr))


def emit_process(proc: subprocess.CompletedProcess[str]) -> None:
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)


def run_direct(binary: Path, argv: Sequence[str], cwd: Path) -> int:
    proc = subprocess.run(
        [str(binary), *argv],
        cwd=cwd,
        env=os.environ.copy(),
        check=False,
        creationflags=LOW_PRIORITY_FLAGS,
    )
    return proc.returncode


def drive_banner(output: str) -> tuple[dict[str, int], str] | None:
    matches = list(DRIVE_BANNER_RE.finditer(output))
    if len(matches) != 1:
        return None
    match = matches[0]
    families = match.group(4)
    if len(families.split(",")) != len(set(families.split(","))):
        return None
    return dict(zip(DRIVE_COUNT_ORDER, map(int, match.groups()[:3]), strict=True)), families


def requested_drive_families(binary: Path, passthrough: Sequence[str]) -> str | None:
    """Ask the native profile owner; do not duplicate its family unions here."""
    proc = run_native(binary, [*passthrough, "--print-families"], ROOT)
    match = DRIVE_FAMILIES_RE.fullmatch(proc.stdout)
    if proc.returncode != 0 or proc.stderr or match is None:
        return None
    families = match.group(1)
    return families if len(families.split(",")) == len(set(families.split(","))) else None


def drive_result_error(proc: subprocess.CompletedProcess[str], *, files: int | None = None,
                       families: str | None = None, path: str | None = None) -> str:
    parsed = drive_banner(proc.stdout)
    if parsed is None:
        return "missing, malformed or repeated structured completion report"
    counts, actual_families = parsed
    if counts["files"] == 0 or (files is not None and counts["files"] != files):
        return "structured report omitted or duplicated requested files"
    if families is not None and actual_families != families:
        return "structured report did not run the requested families"
    findings = list(DRIVE_FINDING_RE.finditer(proc.stdout))
    rejections = list(DRIVE_REJECT_RE.finditer(proc.stderr))
    if len(findings) != counts["findings"] or len(rejections) != counts["rejected"]:
        return "structured diagnostic counts disagree with the completion report"
    if counts["rejected"] > counts["files"] or len({r.group(1) for r in rejections}) != len(rejections):
        return "structured report has duplicate or excess rejected files"
    if path is not None and any(m.group(1) != path for m in [*findings, *rejections]):
        return "structured diagnostic names an unrequested file"
    if DRIVE_REJECT_RE.sub("", proc.stderr).strip():
        return "structured worker emitted an unexpected error"
    body = DRIVE_RECORD_RE.sub("", DRIVE_BANNER_RE.sub("", proc.stdout))
    if body.strip():
        return "structured worker emitted unreported output"
    expected_exit = int(counts["findings"] != 0 or counts["rejected"] != 0)
    if proc.returncode != expected_exit:
        return "structured exit code disagrees with the completion report"
    return ""


def run_drive_bounded(
    binary: Path, passthrough: Sequence[str], files: Sequence[Path]
) -> int:
    """One native drive process per file; findings from every file are shown
    and a single aggregate banner replaces the per-process ones."""
    totals = {key: 0 for key in DRIVE_COUNT_ORDER}
    families = requested_drive_families(binary, passthrough)
    if not files or families is None:
        print("ANALYZE_FAIL: empty input or unavailable native family selection", file=sys.stderr)
        return 2
    failed = False
    for path in files:
        rel = repo_relative(path)
        if rel is None:
            return 2
        trace(f"phase=drive file={rel}")
        proc = run_native(binary, [*passthrough, "--scope", rel], ROOT)
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        parsed = drive_banner(proc.stdout)
        error = drive_result_error(proc, files=1, families=families, path=rel)
        if error or parsed is None:
            sys.stdout.write(proc.stdout)
            print(f"ANALYZE_FAIL: {rel}: {error}", file=sys.stderr)
            return 2
        counts, _ = parsed
        for key in DRIVE_COUNT_ORDER:
            totals[key] += counts[key]
        body = DRIVE_BANNER_RE.sub("", proc.stdout).strip("\r\n")
        if body:
            print(body)
        if proc.returncode != 0:
            failed = True
    fields = " ".join(f"{key}={totals[key]}" for key in DRIVE_COUNT_ORDER)
    print(f"ANALYZE_DRIVE {fields} families={families}")
    return 1 if failed else 0


def baseline_path(passthrough: Sequence[str]) -> Path:
    for index, flag in enumerate(passthrough):
        if flag == "--api-baseline" and index + 1 < len(passthrough):
            return Path(passthrough[index + 1])
    return DEFAULT_API_BASELINE


def without_baseline_flag(passthrough: Sequence[str]) -> list[str]:
    result: list[str] = []
    skip = False
    for flag in passthrough:
        if skip:
            skip = False
        elif flag == "--api-baseline":
            skip = True
        else:
            result.append(flag)
    return result


def load_baseline_rows(source: Path) -> tuple[list[str], list[str]] | None:
    try:
        key = source.resolve()
    except OSError:
        key = source
    cached = _BASELINE_ROWS.get(key)
    if cached is not None:
        return cached
    if not source.is_file():
        return None
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None
    comments = [line for line in lines if line.startswith("#")]
    data = [line for line in lines if line and not line.startswith("#")]
    rows = (comments, data)
    _BASELINE_ROWS[key] = rows
    return rows


def filtered_baseline_flags(
    passthrough: Sequence[str], rel: str, scratch: Path
) -> list[str]:
    source = baseline_path(passthrough)
    loaded = load_baseline_rows(source)
    if loaded is None:
        return list(passthrough)
    comments, data = loaded
    rows = [line for line in data if line.startswith(f"{rel}\t")]
    if data and not rows:
        rows.append(BASELINE_SENTINEL)
    target = scratch / "api-baseline" / Path(rel).with_suffix(".tsv")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join([*comments, *rows, ""]), encoding="utf-8")
    return [*without_baseline_flag(passthrough), "--api-baseline", str(target)]


def skeleton_line(line: str) -> str:
    stripped = line.lstrip()
    keep = stripped.startswith("import ") or (
        stripped.startswith("--")
        and ("ouro-analyze:" in stripped or "ouro-lint:" in stripped)
    )
    if keep:
        return line
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    if line.endswith("\r"):
        return "\r"
    return ""


def local_skeleton_line(line: str) -> str:
    stripped = line.lstrip()
    declaration = re.match(
        r"(?:import|def|axiom|inductive|record|effect)(?:\s|$)|\|", stripped
    )
    marker = stripped.startswith("--") and any(
        tag in stripped
        for tag in ("ouro-analyze:", "ouro-lint:", "@entry", "@export")
    )
    if declaration or marker:
        return line
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    if line.endswith("\r"):
        return "\r"
    return ""


def format_skeleton_line(line: str) -> str:
    body = line.removesuffix("\r\n").removesuffix("\n").removesuffix("\r")
    if "\r" in line or "\t" in line or body.endswith((" ", "\t")):
        return line
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    if line.endswith("\r"):
        return "\r"
    return ""


def write_skeleton_file(source: Path, target: Path, line_filter) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("r", encoding="utf-8", newline="") as handle:
        text = handle.read()
    with target.open("w", encoding="utf-8", newline="") as handle:
        handle.write("".join(line_filter(line) for line in text.splitlines(keepends=True)))


def write_architecture_skeleton(root: Path, files: Sequence[Path]) -> list[str]:
    top_scopes: set[str] = set()
    for source in files:
        rel = repo_relative(source)
        if rel is None:
            raise ValueError(f"analyzer input escaped repository: {source}")
        target = root / Path(rel)
        write_skeleton_file(source, target, skeleton_line)
        top_scopes.add(rel.split("/", 1)[0] if "/" in rel else rel)
    return sorted(top_scopes)


def banner_counts(output: str) -> tuple[str, dict[str, int]] | None:
    match = BANNER_RE.search(output)
    if match is None:
        return None
    counts: dict[str, int] = {}
    for key, raw in re.findall(r"([a-z][a-z-]*)=(\d+)", match.group(2)):
        counts[key] = int(raw)
    if any(key not in counts for key in COUNT_ORDER):
        return None
    return match.group(1), counts


def aggregate_banner(profile: str, counts: dict[str, int]) -> str:
    fields = " ".join(f"{key}={counts[key]}" for key in COUNT_ORDER)
    return f"ANALYZE_OK profile={profile} {fields}"


def should_batch(passthrough: Sequence[str], files: Sequence[Path]) -> bool:
    flags = set(passthrough)
    if flags & GLOBAL_FLAGS:
        return False
    shards_api_baseline = any(
        (repo_relative(path) or "").startswith("std/") for path in files
    )
    if len(files) < 2 and not shards_api_baseline:
        return False
    if (
        len(files) <= 8
        and sum(path.stat().st_size for path in files) <= 65536
        and not shards_api_baseline
    ):
        return False
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return False
        if SUPPRESSION_RE.search(text):
            return False
    return True


def global_scope_error(
    passthrough: Sequence[str], files: Sequence[Path]
) -> str | None:
    global_flags = sorted(set(passthrough) & GLOBAL_FLAGS)
    if not global_flags or ALLOW_UNBOUNDED:
        return None
    total_bytes = sum(path.stat().st_size for path in files)
    if len(files) <= MAX_GLOBAL_FILES and total_bytes <= MAX_GLOBAL_BYTES:
        return None
    return (
        "ANALYZE_FAIL: global analyzer flags require a bounded scope "
        f"(files={len(files)} bytes={total_bytes} "
        f"limit-files={MAX_GLOBAL_FILES} limit-bytes={MAX_GLOBAL_BYTES} "
        f"flags={','.join(global_flags)}); narrow --scope or set "
        "OURO_ANALYZE_ALLOW_UNBOUNDED=1 on a dedicated host"
    )


def drive_scope_error(
    passthrough: Sequence[str], files: Sequence[Path]
) -> str | None:
    drive_flags = sorted(set(passthrough) & DRIVE_FLAGS)
    if not drive_flags or ALLOW_UNBOUNDED:
        return None
    for path in files:
        size = path.stat().st_size
        if size <= MAX_DRIVE_FILE_BYTES:
            continue
        rel = repo_relative(path) or str(path)
        return (
            "ANALYZE_FAIL: structured analyzer file exceeds the local safety "
            f"limit (file={rel} bytes={size} "
            f"limit-bytes={MAX_DRIVE_FILE_BYTES} "
            f"flags={','.join(drive_flags)}); split the source or set "
            "OURO_ANALYZE_ALLOW_UNBOUNDED=1 on a dedicated host"
        )
    return None


def run_bounded(binary: Path, passthrough: Sequence[str], files: Sequence[Path]) -> int:
    totals = {key: 0 for key in COUNT_ORDER}
    profile = "strict" if "--strict" in passthrough else "baseline"
    facts_line = ""
    failed_outputs: list[str] = []
    failed = False
    scratch = ROOT / "_build" / "analyze-bounded" / f"run-{os.getpid()}"
    local_flags = [flag for flag in passthrough if flag != "--strict"]
    strict_enabled = "--strict" in passthrough
    shutil.rmtree(scratch, ignore_errors=True)
    try:
        for path in files:
            rel = repo_relative(path)
            if rel is None:
                return 2
            trace(f"phase=local file={rel}")
            file_flags = filtered_baseline_flags(local_flags, rel, scratch)
            local_root = ROOT
            if not any(flag in BASE_TEXT_FLAGS for flag in local_flags):
                trace(f"phase=local-skeleton file={rel}")
                target = scratch / Path(rel)
                write_skeleton_file(path, target, local_skeleton_line)
                local_root = scratch
            proc = run_native(
                binary,
                [*file_flags, "--local-only", "--scope", rel],
                local_root,
            )
            if proc.stderr:
                sys.stderr.write(proc.stderr)
            parsed = banner_counts(proc.stdout)
            if proc.returncode != 0 or "OURO-" in proc.stdout or parsed is None:
                failed = True
                failed_outputs.append(proc.stdout)
            else:
                _, counts = parsed
                for key in COUNT_ORDER:
                    totals[key] += counts[key]
                for line in proc.stdout.splitlines():
                    if line.startswith("ANALYZE_FACTS "):
                        if not facts_line or "api_surface=baseline " in line:
                            facts_line = line

            if strict_enabled:
                trace(f"phase=strict-format file={rel}")
                target = scratch / Path(rel)
                write_skeleton_file(path, target, format_skeleton_line)
                fmt = run_native(
                    binary,
                    [
                        *filtered_baseline_flags(["--strict"], rel, scratch),
                        "--local-only",
                        "--scope",
                        rel,
                    ],
                    scratch,
                )
                if fmt.stderr:
                    sys.stderr.write(fmt.stderr)
                if fmt.returncode != 0 or "OURO-" in fmt.stdout:
                    failed = True
                    failed_outputs.append(fmt.stdout)

        scopes = write_architecture_skeleton(scratch, files)
        trace(f"phase=architecture files={len(files)}")
        arch_args = ["--architecture-only"]
        if "--strict" in passthrough:
            arch_args.append("--strict")
        for scope in scopes:
            arch_args.extend(("--scope", scope))
        arch = run_native(binary, arch_args, scratch)
        if arch.stderr:
            sys.stderr.write(arch.stderr)
        if arch.returncode != 0 or "OURO-" in arch.stdout:
            failed = True
            failed_outputs.append(arch.stdout)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    if failed:
        for output in failed_outputs:
            sys.stdout.write(output)
        return 1
    print(aggregate_banner(profile, totals))
    if facts_line:
        if strict_enabled:
            facts_line = facts_line.replace(" format=facts-only", " format=strict-subset")
        print(facts_line)
    return 0


def self_test() -> int:
    import tempfile
    from unittest.mock import patch

    (ROOT / "_build").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="analyze-discovery-", dir=ROOT / "_build") as tmp:
        root = Path(tmp)
        sources = [f"src/main{i}.ouro" for i in range(9)]
        fixtures = ["quality/fixtures/bad.ouro", "tests/bad.ouro", "nested/tests/bad.ouro"]
        generated = [f"{name}/ignored.ouro" for name in sorted(SKIP_DIR_NAMES)]
        for name in [*sources, *fixtures, *generated]:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("-- ouro-lint:disable=OURO-FMT001\n" if name in fixtures
                            else "def value : Type := Type;\n", encoding="utf-8")
        with patch.object(sys.modules[__name__], "ROOT", root):
            parsed = parse_analyzer_args(["--scope", ".", "--scope", sources[0]], root)
            assert parsed is not None
            flags, files = parsed
            assert [repo_relative(p) for p in files] == sources
            assert should_batch(flags, files), "excluded fixture disabled bounded execution"
            included = parse_analyzer_args(["--include-fixtures", "--scope", "."], root)
            assert included is not None
            assert [repo_relative(p) for p in included[1]] == sorted([*sources, *fixtures])
            for scope in ("_build", "_build/ignored.ouro"):
                explicit = parse_analyzer_args(["--scope", scope], root)
                assert explicit is not None and [repo_relative(p) for p in explicit[1]] == ["_build/ignored.ouro"]
            assert parse_analyzer_args(["--scope", "missing"], root) is None
            with patch("os.walk", side_effect=PermissionError("unreadable source tree")):
                try:
                    parse_analyzer_args(["--scope", "."], root)
                except PermissionError:
                    pass
                else:
                    raise AssertionError("unreadable source tree was accepted")
    cache: dict[Path, tuple[list[str], list[str]]] = {}
    baseline = ROOT / "quality" / "api_surface.tsv"
    with patch.object(sys.modules[__name__], "_BASELINE_ROWS", cache):
        first = load_baseline_rows(baseline)
        second = load_baseline_rows(baseline)
        assert first is not None and first is second
        assert len(cache) == 1
    print("ANALYZE_DISCOVERY_SUITE rows=6")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["--self-test"]:
        return self_test()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bin", required=True)
    ap.add_argument("--caller", required=True)
    ap.add_argument("--drive", action="store_true")
    ap.add_argument("args", nargs=argparse.REMAINDER)
    ns = ap.parse_args(argv)
    try:
        configure_native_stack()
    except (OSError, ValueError) as exc:
        print(f"ANALYZE_FAIL: could not configure native stack: {exc}", file=sys.stderr)
        return 2
    binary = Path(ns.bin).resolve()
    caller = Path(ns.caller).resolve()
    analyzer_args = list(ns.args)
    if analyzer_args and analyzer_args[0] == "--":
        analyzer_args.pop(0)

    try:
        parsed = parse_analyzer_args(analyzer_args, caller)
    except OSError as exc:
        print(f"ANALYZE_FAIL: could not enumerate source scope: {exc}", file=sys.stderr)
        return 2
    if parsed is None:
        return run_direct(binary, analyzer_args, caller)
    passthrough, files = parsed
    # The global-scope guard protects the base runner, whose union modes hold
    # every file in one process; the drive always runs one process per file,
    # so only the per-file size guard applies to it.
    if not ns.drive:
        scope_error = global_scope_error(passthrough, files)
        if scope_error is not None:
            print(scope_error, file=sys.stderr)
            return 2
    scope_error = drive_scope_error(passthrough, files)
    if scope_error is not None:
        print(scope_error, file=sys.stderr)
        return 2
    if ns.drive:
        return run_drive_bounded(binary, passthrough, files)
    if not should_batch(passthrough, files):
        return run_direct(binary, analyzer_args, caller)
    return run_bounded(binary, passthrough, files)


if __name__ == "__main__":
    raise SystemExit(main())
