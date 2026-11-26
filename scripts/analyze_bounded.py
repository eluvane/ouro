#!/usr/bin/env python3
"""Run safe repository analyzer profiles in bounded native subprocesses."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, Sequence

from repo_support import configure_native_stack

if TYPE_CHECKING:
    from frontend_regen import ImportBytesParser


ROOT = Path(__file__).resolve().parents[1]
TRACE = os.environ.get("OURO_ANALYZE_BATCH_TRACE") == "1"
DEFAULT_API_BASELINE = ROOT / "quality" / "api_surface.tsv"
BASELINE_SENTINEL = "__ouro__/baseline.ouro\t__sentinel\t0\tinternal\tinternal"
MAX_GLOBAL_FILES = 8
MAX_GLOBAL_BYTES = 65536
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
DRIVE_REPORT_INPUT_LIMIT = 64 * 1024 * 1024
_DRIVE_REPORT_CACHE: dict[
    str, tuple[Path, Path, tuple[str, str, tuple[str, ...], dict[str, str]], ImportBytesParser]
] = {}
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
    files: dict[Path, str] = {}
    # Keep exact spellings for case-sensitive directories on Windows.
    walked_directories: set[str] = set()
    include_fixtures = "--include-fixtures" in passthrough
    for raw in roots:
        path = Path(raw)
        if not path.is_absolute():
            path = caller / path
        if path.is_dir():
            if str(path) in walked_directories:
                continue
            # Prune generated/dependency trees before enumerating their files.
            # An explicitly selected file or directory remains a valid scope.
            found = []
            for directory, children, names in os.walk(path, onerror=walk_error):
                current = Path(directory)
                walked_directories.add(directory)
                children[:] = sorted(name for name in children
                                     if name not in SKIP_DIR_NAMES and os.path.join(directory, name) not in walked_directories)
                found.extend(current / name for name in names if name.endswith(".ouro"))
            found.sort()
        elif path.is_file() and path.suffix == ".ouro":
            found = [path]
        else:
            return None
        for item in found:
            resolved = item.resolve()
            try:
                rel = resolved.relative_to(ROOT).as_posix()
            except ValueError:
                return None
            if not include_fixtures and is_fixture(rel):
                continue
            files.setdefault(resolved, rel)
    return passthrough, sorted(files, key=files.__getitem__)


def run_native(binary: Path, argv: Sequence[str], cwd: Path, *,
               env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        [str(binary), *argv],
        cwd=cwd,
        env=os.environ.copy() if env is None else env,
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


def _drive_report_binary() -> Path:
    from native_tool_build import cached_import_parser
    from ourosmith.host import compiler_path, prepare_entry
    from ourosmith.native import receipt_for

    entry = "tools/analyze/bounded_report_main.ouro"
    if entry not in _DRIVE_REPORT_CACHE:
        prepared = prepare_entry(entry, "ouro-analyze-report")
        compiler = compiler_path()
        parse_bytes = cached_import_parser()
        receipt, units, sources = receipt_for(prepared, entry, compiler, parse_bytes=parse_bytes)
        identity = (receipt["key"], receipt["binary_sha256"], tuple(units), dict(sources))
        _DRIVE_REPORT_CACHE[entry] = (prepared, compiler, identity, parse_bytes)
    else:
        # As in NativeProgram.unchanged, pin identity beyond current consistency.
        prepared, compiler, identity, parse_bytes = _DRIVE_REPORT_CACHE[entry]
        receipt, units, sources = receipt_for(prepared, entry, compiler, parse_bytes=parse_bytes)
        if (receipt["key"], receipt["binary_sha256"], tuple(units), sources) != identity:
            raise ValueError("report provider inputs changed since preparation")
    return _DRIVE_REPORT_CACHE[entry][0]


def _drive_count_text(digits: str) -> str:
    # Regex \d+ supplies nonempty Unicode decimal digits; never parse the whole count.
    ascii_digits = "".join(str(int(digit)) for digit in digits)
    return ascii_digits.lstrip("0") or "0"


def _drive_report_response(mode: str, stdout: str = "", stderr: str = "", *,
                           code: int = 0, files: int | None = None,
                           families: str | None = None, path: str | None = None,
                           metadata: str | None = None) -> dict:
    from ourosmith.limits import run_limited

    # Extraction preserves the existing regex/Unicode/CRLF grammar. Acceptance
    # and refusal priority belong exclusively to bounded_report.ouro.
    banners = [{**dict(zip(DRIVE_COUNT_ORDER, map(_drive_count_text, match.groups()[:3]), strict=True)),
                "families": match.group(4)} for match in DRIVE_BANNER_RE.finditer(stdout)]
    request = {
        "kind": "ouro.analyze-bounded-report-request.v1", "mode": mode,
        "expected": {"files": None if files is None else str(int(files)), "families": families, "path": path},
        "banners": banners,
        "finding_paths": [match.group(1) for match in DRIVE_FINDING_RE.finditer(stdout)],
        "rejection_paths": [match.group(1) for match in DRIVE_REJECT_RE.finditer(stderr)],
        "stdout_unreported": bool(DRIVE_RECORD_RE.sub("", DRIVE_BANNER_RE.sub("", stdout)).strip()),
        "stderr_unexpected": bool(stderr) if mode == "families" else bool(DRIVE_REJECT_RE.sub("", stderr).strip()),
        "exit": str(code), "family_metadata": metadata,
    }
    payload = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
    size = len(payload.encode("utf-8"))
    if size > DRIVE_REPORT_INPUT_LIMIT:
        raise ValueError("report provider input byte limit exceeded")
    result = run_limited(
        [str(_drive_report_binary()), "--input-bytes", str(size)], cwd=ROOT,
        env=os.environ.copy(), timeout_s=30, memory_mb=3072, stdin_text=payload,
    )
    _drive_report_binary()  # Compare against the initial source/producer/image, never repin.
    if result.status != "ok" or result.returncode not in {0, 1} or result.stderr:
        raise ValueError(f"report provider failed status={result.status} exit={result.returncode}: "
                         + result.stderr[:4096])
    if "\ufffd" in result.stdout:
        raise ValueError("report provider returned invalid UTF-8")
    if len(result.stdout.encode("utf-8")) > DRIVE_REPORT_INPUT_LIMIT:
        raise ValueError("report provider output byte limit exceeded")

    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("report provider response has a duplicate key")
            value[key] = item
        return value

    response = json.loads(result.stdout, object_pairs_hook=unique_object)
    if not isinstance(response, dict) or set(response) != {"kind", "banner", "families", "error"}:
        raise ValueError("report provider response schema mismatch")
    if response["kind"] != "ouro.analyze-bounded-report-response.v1" or not isinstance(response["error"], str):
        raise ValueError("report provider response kind/error mismatch")
    banner = response["banner"]
    if banner is not None:
        if not isinstance(banner, dict) or set(banner) != {*DRIVE_COUNT_ORDER, "families"}:
            raise ValueError("report provider banner schema mismatch")
        if any(not isinstance(banner[key], str) or re.fullmatch(r"0|[1-9][0-9]*", banner[key]) is None
               for key in DRIVE_COUNT_ORDER) or not isinstance(banner["families"], str):
            raise ValueError("report provider banner field type mismatch")
    selected = response["families"]
    if response["error"] and (banner is not None or selected is not None):
        raise ValueError("report provider returned a payload on failure")
    if selected is not None and not isinstance(selected, str):
        raise ValueError("report provider family field type mismatch")
    if result.returncode != int(bool(response["error"])):
        raise ValueError("report provider response/exit mismatch")
    if not response["error"] and ((mode == "families" and selected is None)
                                  or (mode != "families" and banner is None)):
        raise ValueError("report provider omitted its accepted payload")
    if (mode == "families" and banner is not None) or (mode != "families" and selected is not None):
        raise ValueError("report provider returned a payload for another mode")
    return response


def drive_banner(output: str) -> tuple[dict[str, int], str] | None:
    try:
        banner = _drive_report_response("banner", output)["banner"]
    except (OSError, ValueError, SystemExit):
        return None
    if banner is None:
        return None
    original = next(DRIVE_BANNER_RE.finditer(output))
    return dict(zip(DRIVE_COUNT_ORDER, map(int, original.groups()[:3]), strict=True)), banner["families"]


def requested_drive_families(binary: Path, passthrough: Sequence[str]) -> str | None:
    """Ask the native profile owner; do not duplicate its family unions here."""
    proc = run_native(binary, [*passthrough, "--print-families"], ROOT)
    match = DRIVE_FAMILIES_RE.fullmatch(proc.stdout)
    try:
        return _drive_report_response("families", stderr=proc.stderr, code=proc.returncode,
                                      metadata=match.group(1) if match is not None else None)["families"]
    except (OSError, ValueError, SystemExit):
        return None


def _verify_drive_result(proc: subprocess.CompletedProcess[str], *, files: int | None = None,
                         families: str | None = None, path: str | None = None) -> tuple[dict[str, str] | None, str]:
    try:
        result = _drive_report_response("verify", proc.stdout, proc.stderr, code=proc.returncode,
                                        files=files, families=families, path=path)
        return result["banner"], result["error"]
    except (OSError, ValueError, SystemExit) as error:
        return None, f"structured report verifier unavailable: {error}"


def drive_result_error(proc: subprocess.CompletedProcess[str], *, files: int | None = None,
                       families: str | None = None, path: str | None = None) -> str:
    _, error = _verify_drive_result(proc, files=files, families=families, path=path)
    return error


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
        banner, error = _verify_drive_result(proc, files=1, families=families, path=rel)
        if error or banner is None:
            sys.stdout.write(proc.stdout)
            print(f"ANALYZE_FAIL: {rel}: {error}", file=sys.stderr)
            return 2
        for key in DRIVE_COUNT_ORDER:
            totals[key] += int(banner[key])
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


class ApiBaselineRows(NamedTuple):
    comments: list[str]
    data: list[str]
    by_scope: dict[str, list[str]]


def load_baseline_rows(source: Path, cache: dict[Path, ApiBaselineRows]) -> ApiBaselineRows | None:
    try:
        key = source.resolve()
    except OSError:
        key = source
    cached = cache.get(key)
    if cached is not None:
        return cached
    if not source.is_file():
        return None
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None
    rows = ApiBaselineRows([], [], {})
    for line in lines:
        if line.startswith("#"):
            rows.comments.append(line)
        elif line:
            rows.data.append(line)
            scope, separator, _ = line.partition("\t")
            if separator:
                rows.by_scope.setdefault(scope, []).append(line)
    cache[key] = rows
    return rows


def filtered_baseline_flags(
    passthrough: Sequence[str], rel: str, scratch: Path, cache: dict[Path, ApiBaselineRows]
) -> list[str]:
    source = baseline_path(passthrough)
    loaded = load_baseline_rows(source, cache)
    if loaded is None:
        return list(passthrough)
    # A POSIX filename can contain a tab. Keep the full prefix match for that path.
    if "\t" in rel:
        prefix = f"{rel}\t"
        rows = [line for line in loaded.data if line.startswith(prefix)]
    else:
        rows = loaded.by_scope.get(rel, [])
    if loaded.data and not rows:
        rows = [BASELINE_SENTINEL]
    target = scratch / "api-baseline" / Path(rel).with_suffix(".tsv")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join([*loaded.comments, *rows, ""]), encoding="utf-8")
    return [*without_baseline_flag(passthrough), "--api-baseline", str(target)]


def skeleton_line(line: str) -> str:
    stripped = line.lstrip()
    keep = stripped.startswith("--") and ("ouro-analyze:" in stripped or "ouro-lint:" in stripped)
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
        r"(?:def|axiom|inductive|record|effect)(?:\s|$)|\|", stripped
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
    if "\r" in line or "\t" in line or line.endswith((" ", " \n")):
        return line
    return "\n" if line.endswith("\n") else ""


class SkeletonRegions(NamedTuple):
    imports: list[range]
    definitions: list[range]


class ArchitectureSkeletonInput(NamedTuple):
    # The architecture pass rereads the file before reusing these ranges.
    digest: bytes
    imports: list[range]


class SkeletonInput(NamedTuple):
    data: bytes
    regions: SkeletonRegions
    lines: list[str]

    def architecture_input(self) -> ArchitectureSkeletonInput:
        return ArchitectureSkeletonInput(hashlib.sha256(self.data).digest(), self.regions.imports)


def skeleton_regions(text: str, lines: list[str], line_filter) -> SkeletonRegions:
    regions = SkeletonRegions([], [])
    if line_filter in (skeleton_line, local_skeleton_line, format_skeleton_line):
        from api_baseline_regen import collect_signature
        from structural_quality import lex

        tokens, _comments = lex(text, "ouro")
        forms = {"import", "def", "axiom", "inductive", "record", "effect", "open"}
        starts = [index for index, token in enumerate(tokens)
                  if token.value in forms and (index == 0 or tokens[index - 1].value != ".")]
        ends = [*starts[1:], len(tokens)] if starts else []
        for start, past in zip(starts, ends, strict=True):
            first, last = tokens[start], tokens[past - 1]
            if first.value == "import":
                # Keep the entire declaration region, including comments and
                # malformed tails; the analyzer still owns its syntax errors.
                finish_line = first.line + text.count("\n", first.start, last.end)
                regions.imports.append(range(first.line, finish_line + 1))
            elif first.value == "def" and line_filter != skeleton_line:
                try:
                    _signature, finish_line = collect_signature(lines, first.line - 1,
                                                               "analyzer input")
                except ValueError:
                    # Preserve malformed headers for native diagnostics too.
                    finish_line = first.line + text.count("\n", first.start, last.end)
                regions.definitions.append(range(first.line, finish_line + 1))
    return regions


def render_skeleton(lines: list[str], line_filter, regions: SkeletonRegions) -> str:
    filtered = [line_filter(line) for line in lines]
    kept_lines: set[int] = set()
    if line_filter != format_skeleton_line:
        for region in regions.imports:
            kept_lines.update(region)
    for region in regions.definitions:
        if any(filtered[line - 1].rstrip("\r\n") for line in region):
            kept_lines.update(region)
    return "".join(line if index in kept_lines else filtered[index - 1]
                   for index, line in enumerate(lines, 1))


def source_skeleton(text: str, line_filter) -> str:
    lines = text.splitlines(keepends=True)
    return render_skeleton(lines, line_filter, skeleton_regions(text, lines, line_filter))


def write_skeleton_file(source: Path, target: Path, line_filter, *,
                        local_input: SkeletonInput | None = None,
                        architecture_input: ArchitectureSkeletonInput | None = None) -> SkeletonInput:
    target.parent.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes()
    if line_filter == format_skeleton_line and local_input is not None and data == local_input.data:
        snapshot = local_input
        del data
    else:
        snapshot = None
        text = data.decode("utf-8")
    with target.open("w", encoding="utf-8", newline="") as handle:
        if snapshot is None:
            lines = text.splitlines(keepends=True)
            if (line_filter == skeleton_line and architecture_input is not None
                    and hashlib.sha256(data).digest() == architecture_input.digest):
                regions = SkeletonRegions(architecture_input.imports, [])
            else:
                regions = skeleton_regions(text, lines, line_filter)
            snapshot = SkeletonInput(data, regions, lines)
        handle.write(render_skeleton(snapshot.lines, line_filter, snapshot.regions))
    return snapshot


def write_architecture_skeleton(root: Path, files: Sequence[Path],
                                inputs: dict[str, ArchitectureSkeletonInput]) -> list[str]:
    top_scopes: set[str] = set()
    for source in files:
        rel = repo_relative(source)
        if rel is None:
            raise ValueError(f"analyzer input escaped repository: {source}")
        target = root / Path(rel)
        write_skeleton_file(source, target, skeleton_line, architecture_input=inputs.get(rel))
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


def check_base_phase(proc: subprocess.CompletedProcess[str], phase: str) -> bool:
    if proc.returncode != 0 or "OURO-" in proc.stdout:
        return False
    try:
        report = banner_counts(proc.stdout)
    except ValueError:
        report = None
    if report is None:
        print(f"ANALYZE_FAIL: {phase}: missing or malformed completion report", file=sys.stderr)
    return report is not None


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
    use_local_skeleton = not any(flag in BASE_TEXT_FLAGS for flag in local_flags)
    baseline_cache: dict[Path, ApiBaselineRows] = {}
    architecture_inputs: dict[str, ArchitectureSkeletonInput] = {}
    shutil.rmtree(scratch, ignore_errors=True)
    try:
        for path in files:
            rel = repo_relative(path)
            if rel is None:
                return 2
            trace(f"phase=local file={rel}")
            file_flags = filtered_baseline_flags(local_flags, rel, scratch, baseline_cache)
            local_root = ROOT
            local_input = None
            if use_local_skeleton:
                trace(f"phase=local-skeleton file={rel}")
                target = scratch / Path(rel)
                local_input = write_skeleton_file(path, target, local_skeleton_line)
                if not strict_enabled:
                    architecture_inputs[rel] = local_input.architecture_input()
                    local_input = None
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
                formatted_input = write_skeleton_file(path, target, format_skeleton_line, local_input=local_input)
                architecture_inputs[rel] = formatted_input.architecture_input()
                local_input = None
                del formatted_input
                fmt = run_native(
                    binary,
                    [
                        *filtered_baseline_flags(["--strict"], rel, scratch, baseline_cache),
                        "--local-only",
                        "--scope",
                        rel,
                    ],
                    scratch,
                )
                if fmt.stderr:
                    sys.stderr.write(fmt.stderr)
                if not check_base_phase(fmt, f"strict-format file={rel}"):
                    failed = True
                    failed_outputs.append(fmt.stdout)

        scopes = write_architecture_skeleton(scratch, files, architecture_inputs)
        trace(f"phase=architecture files={len(files)}")
        arch_args = ["--architecture-only"]
        if "--strict" in passthrough:
            arch_args.append("--strict")
        for scope in scopes:
            arch_args.extend(("--scope", scope))
        arch = run_native(binary, arch_args, scratch)
        if arch.stderr:
            sys.stderr.write(arch.stderr)
        if not check_base_phase(arch, "architecture"):
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


def import_skeleton_self_test() -> None:
    imports = [
        'import "a.ouro";\n',
        'import "a.ouro", "b.ouro";\n',
        'import "a.ouro",\n  "b.ouro",\n;\n',
        'import\n  "a.ouro", -- keep both dependencies\n  "b\\"c--d.ouro",\n;\n',
        'import "a.ouro"\n  as Alias;\n',
        'import "a.ouro",\n  "b.ouro"\n',
        'import "a.ouro",\n  missing;\n',
    ]
    for prefix in imports:
        for newline in ("\n", "\r\n"):
            normalized_prefix = prefix.replace("\n", newline)
            definition = f"def result : Nat :={newline}  0;{newline}"
            source = normalized_prefix + definition
            assert source_skeleton(source, skeleton_line) == normalized_prefix + newline * 2
            assert source_skeleton(source, local_skeleton_line) == normalized_prefix + f"def result : Nat :={newline}{newline}"
            assert source_skeleton(source, format_skeleton_line) == "".join(
                format_skeleton_line(line) for line in source.splitlines(keepends=True))
    literal = 'def text : String := "\\\"import \\\"ghost.ouro\\\";";\n'
    fake = '-- import "comment.ouro";\n' + literal
    assert source_skeleton(fake, skeleton_line) == "\n\n"
    assert source_skeleton(fake, local_skeleton_line) == "\n" + literal
    assert source_skeleton("-- comment only\n", skeleton_line) == "\n"
    try:
        source_skeleton('import "unterminated', skeleton_line)
    except ValueError:
        pass
    else:
        raise AssertionError("skeleton accepted an unterminated import literal")


def header_skeleton_self_test() -> int:
    from api_baseline_regen import collect_signature, hash_text

    for line, expected in (
        ("", ""), ("body\n", "\n"), ("body ", "body "), ("body \n", "body \n"),
        ("body\r\n", "body\r\n"), ("body\r", "body\r"), ("\tbody\n", "\tbody\n"),
    ):
        assert format_skeleton_line(line) == expected

    headers = [
        "def abs_div_issue (ids : AbsIds) (env : List (Pair Nat Nat)) (f : Ast) (x : Ast)\n    : List AbsIssue :=\n",
        "def api_header_line (code : List Nat) (source : List Nat)\n    (brackets : List Nat) (rev : List Nat) : ApiHeaderStep :=\n",
        "def continued {A : Type} (x : A) -- keep header comments\n    : A\n    :=\n",
        "def defaulted (x : Nat := 30)\n    : Nat :=\n",
        'def quoted : Eq String r#"left\ndef hidden := text\nright"# :=\n',
        "def one_line : Nat := 0;\n",
    ]
    checked = 0
    for newline in ("\n", "\r\n"):
        prefix = "-- preserve original locations\n\n".replace("\n", newline)
        body = "    original_body;\n".replace("\n", newline)
        for header_template in headers:
            header = header_template.replace("\n", newline)
            source = prefix + header + body
            skeleton = source_skeleton(source, local_skeleton_line)
            assert skeleton == newline * 2 + header + newline
            assert skeleton.count("\n") == source.count("\n")
            original = collect_signature(source.splitlines(), 2, "fixtures/headers.ouro")
            retained = collect_signature(skeleton.splitlines(), 2, "fixtures/headers.ouro")
            assert retained == original
            assert hash_text(retained[0]) == hash_text(original[0])
            checked += 1
        for header_template in ("def\tcontinued (x : Nat)\n    : Nat :=\n",
                       "def continued (x : Nat)\n\t: Nat :=\n",
                       "def continued (x : Nat) \n    : Nat :=\n"):
            header = header_template.replace("\n", newline)
            source = prefix + header + body
            expected = source if newline == "\r\n" else newline * 2 + header + newline
            assert source_skeleton(source, format_skeleton_line) == expected
            checked += 1
        for malformed in ("def incomplete : Nat\n",
                          "def incomplete ]\n    : Nat := 0;\n",
                          "def incomplete (x : Nat)\n    : Nat;\ndef next : Nat := 0;\n"):
            source = prefix + malformed.replace("\n", newline)
            skeleton = source_skeleton(source, local_skeleton_line)
            assert skeleton == newline * 2 + malformed.replace("\n", newline)
            failures = []
            for text in (source, skeleton):
                try:
                    collect_signature(text.splitlines(), 2, "fixtures/headers.ouro")
                except ValueError as error:
                    failures.append(str(error))
            assert len(failures) == 2 and failures[0] == failures[1]
            assert "fixtures/headers.ouro:3:" in failures[0]
            checked += 1
    return checked


def skeleton_input_self_test(root: Path) -> None:
    import contextlib
    import io
    from unittest.mock import patch

    import structural_quality

    rel = "std/skeleton.ouro"
    source = root / rel
    source.parent.mkdir()
    before = b'import "a.ouro";\r\ndef original\t(x : Nat)\n  : Nat :=\n  x;\n'
    after = b'import "b.ouro";\r\ndef modified\t(x : Nat) : Nat :=\n    x;\n'
    last = after.replace(b'b.ouro', b'c.ouro')
    assert len(before) == len(after) == len(last)
    banner = aggregate_banner("baseline", dict.fromkeys(COUNT_ORDER, 0)) + "\n"
    module = sys.modules[__name__]
    read_bytes = Path.read_bytes

    def check(format_input: bytes, architecture_input: bytes, expected_lexes: int,
              flags: tuple[str, ...] = ("--strict",)) -> None:
        source.write_bytes(before)
        mtime = source.stat().st_mtime_ns
        strict = "--strict" in flags
        uses_local_skeleton = not BASE_TEXT_FLAGS.intersection(flags)
        local = source_skeleton(before.decode(), local_skeleton_line).encode() if uses_local_skeleton else before
        expected = {"local": local,
                    "format": source_skeleton(format_input.decode(), format_skeleton_line).encode(),
                    "architecture": source_skeleton(architecture_input.decode(), skeleton_line).encode()}
        calls: list[str] = []
        source_reads = 0
        source_decodes = 0

        class ObservedBytes(bytes):
            def decode(self, *args, **kwargs):
                nonlocal source_decodes
                source_decodes += 1
                return super().decode(*args, **kwargs)

        def observe(path):
            nonlocal source_reads
            data = read_bytes(path)
            if path == source:
                source_reads += 1
                return ObservedBytes(data)
            return data

        def run(_binary: Path, flags: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
            if "--architecture-only" in flags:
                phase = "architecture"
            else:
                phase = "format" if "--strict" in flags else "local"
            assert read_bytes(cwd / rel) == expected[phase]
            calls.append(phase)
            if phase != "architecture":
                source.write_bytes(format_input if phase == "local" and strict else architecture_input)
                os.utime(source, ns=(source.stat().st_atime_ns, mtime))
                assert source.stat().st_mtime_ns == mtime
            return subprocess.CompletedProcess(flags, 0, banner, "")

        with (patch.object(module, "ROOT", root),
              patch.object(module, "DEFAULT_API_BASELINE", root / "no-baseline.tsv"),
              patch.object(module, "run_native", side_effect=run),
              patch.object(Path, "read_bytes", autospec=True, side_effect=observe),
              patch.object(structural_quality, "lex", wraps=structural_quality.lex) as lex,
              contextlib.redirect_stdout(io.StringIO())):
            assert should_batch(flags, [source])
            assert run_bounded(root / "unused", flags, [source]) == 0
            assert calls == (["local", "format", "architecture"] if strict else ["local", "architecture"])
            assert lex.call_count == expected_lexes
            expected_reads = 1 + int(uses_local_skeleton) + int(strict)
            expected_reuse = strict and uses_local_skeleton and format_input == before
            assert source_reads == expected_reads
            assert source_decodes == expected_reads - int(expected_reuse)

    check(before, before, 1)
    check(after, after, 2)
    check(before, after, 2)
    check(after, last, 3)
    check(before, before, 1, ())
    check(before, after, 2, ())
    check(before, before, 1, ("--strict", "--enable-format"))

    counts = dict.fromkeys(COUNT_ORDER, 0)
    counts.update(files=1, modules=1)
    complete = [
        subprocess.CompletedProcess([], 0, aggregate_banner(profile, counts) + "\nANALYZE_FACTS architecture=graph\n", "")
        for profile in ("standard", "strict", "strict")
    ]
    malformed = "missing or malformed completion report"
    for index, result, diagnostic in (
        (1, subprocess.CompletedProcess([], 0, "", ""),
         f"ANALYZE_FAIL: strict-format file={rel}: {malformed}\n"),
        (2, subprocess.CompletedProcess([], 0, "ANALYZE_OK profile=strict files=1\n", ""),
         f"ANALYZE_FAIL: architecture: {malformed}\n"),
        (1, subprocess.CompletedProcess([], 17, "format failed\n", "worker diagnostic\n"), ""),
    ):
        results = complete.copy()
        results[index] = result
        with (patch.object(module, "ROOT", root),
              patch.object(module, "DEFAULT_API_BASELINE", root / "no-baseline.tsv"),
              patch.object(module, "run_native", side_effect=results),
              patch.object(module, "TRACE", False),
              contextlib.redirect_stdout(io.StringIO()) as stdout,
              contextlib.redirect_stderr(io.StringIO()) as stderr):
            assert run_bounded(root / "unused", ["--strict"], [source]) == 1
        assert stdout.getvalue() == result.stdout
        assert stderr.getvalue() == result.stderr + diagnostic


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
            with patch.object(Path, "resolve", autospec=True, side_effect=Path.resolve) as resolve:
                parsed = parse_analyzer_args(["--scope", ".", "--scope", sources[0]], root)
            assert resolve.call_count == len(sources) + len(fixtures) + 1
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
            for first_scope, second_scope in ((".", "src"), ("src", ".")):
                with patch.object(os, "scandir", wraps=os.scandir) as scans:
                    overlapping = parse_analyzer_args(["--scope", first_scope, "--scope", second_scope], root)
                assert overlapping == parsed
                assert [Path(call.args[0]) for call in scans.call_args_list].count(root / "src") == 1
            generated_explicitly = parse_analyzer_args(["--scope", ".", "--scope", "_build"], root)
            assert generated_explicitly is not None
            assert [repo_relative(p) for p in generated_explicitly[1]] == ["_build/ignored.ouro", *sources]
            assert parse_analyzer_args(["--scope", "missing"], root) is None
            with patch("os.walk", side_effect=PermissionError("unreadable source tree")):
                try:
                    parse_analyzer_args(["--scope", "."], root)
                except PermissionError:
                    pass
                else:
                    raise AssertionError("unreadable source tree was accepted")
        with patch.object(sys.modules[__name__], "ROOT", root / "src"):
            assert parse_analyzer_args(["--include-fixtures", "--scope", fixtures[0]], root) is None
        cache: dict[Path, ApiBaselineRows] = {}
        baseline = root / "baseline.tsv"
        baseline.write_bytes(b"\xff")
        assert load_baseline_rows(baseline, cache) is None and not cache
        contents = "# header\r\nsrc/main0.ouro\tfirst\r\ninvalid\r\n\r\n# notes\r\nsrc/main0.ouro\tβ\r\n"
        baseline.write_bytes(contents.encode("utf-8"))
        first = load_baseline_rows(baseline, cache)
        assert first is not None
        flags = ["--api-baseline", str(baseline)]
        result = filtered_baseline_flags(flags, sources[0], root, cache)
        assert result[:-1] == ["--api-baseline"]
        assert Path(result[-1]).read_text(encoding="utf-8") == (
            "# header\n# notes\nsrc/main0.ouro\tfirst\nsrc/main0.ouro\tβ\n"
        )
        absent = filtered_baseline_flags(flags, sources[1], root, cache)
        assert Path(absent[-1]).read_text(encoding="utf-8") == f"# header\n# notes\n{BASELINE_SENTINEL}\n"
        baseline.write_text("# next run\n", encoding="utf-8")
        assert load_baseline_rows(baseline, cache) is first and len(cache) == 1
        empty = filtered_baseline_flags(flags, sources[1], root, {})
        assert Path(empty[-1]).read_text(encoding="utf-8") == "# next run\n"
        skeleton_input_self_test(root)
    import_skeleton_self_test()
    header_cases = header_skeleton_self_test()
    print(f"ANALYZE_DISCOVERY_SUITE rows=6 import-skeletons=18 api-header-skeletons={header_cases}")
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
