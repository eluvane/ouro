"""Build and execute native law drivers with current source and binary receipts."""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ourosmith import ROOT
from ourosmith.host import BUILD_MEMORY_MB, BUILD_TIMEOUT_S, environment
from ourosmith.limits import run_limited
from repo_support import hash_json, sha256_file

if TYPE_CHECKING:
    from frontend_regen import ImportBytesParser

SMITH_ENTRY = "tests/compiler_smith_runner.ouro"
RETAINED_ENTRY = "tests/compiler_retained_tests.ouro"
INPUT_FIELDS = {"kind", "entry", "fuel", "compiler_sha256", "cc", "cc_sha256", "platform", "machine",
                "cflags", "link_flags", "environment", "sources"}


def digest(path):
    return sha256_file(Path(path))


def source_inputs(entry, *, parse_bytes: ImportBytesParser | None = None):
    from frontend_regen import capture_unit_inputs
    from native_tool_build import BUILD_INPUTS, RUNTIME, tool_roots

    try:
        closures, captured = capture_unit_inputs(tool_roots(entry), parse_bytes=parse_bytes)
    except SystemExit as error:
        raise ValueError(str(error)) from error
    units = closures[entry]
    if not units or units[-1] != entry or len(set(units)) != len(units):
        raise ValueError("native driver source collection is empty, duplicated, or has the wrong entry")
    source_names = {name for closure in closures.values() for name in closure}
    names = source_names | set(BUILD_INPUTS) | set(RUNTIME)
    names.update(path.relative_to(ROOT).as_posix() for path in (ROOT / "runtime").glob("*.h"))
    if any(not (ROOT / name).resolve().is_relative_to(ROOT) for name in names):
        raise ValueError("native driver input escapes the repository")
    return units, {name: captured[name].sha256 if name in source_names else digest(ROOT / name)
                   for name in sorted(names)}


def receipt_for(executable, entry, compiler, *, parse_bytes: ImportBytesParser | None = None):
    """A cache hit is usable only when every required input and the binary agree."""
    executable, compiler = Path(executable).resolve(), Path(compiler).resolve()
    if not executable.is_relative_to(ROOT) or not compiler.is_relative_to(ROOT):
        raise ValueError("native driver and producer must be repository-local files")
    units, sources = source_inputs(entry, parse_bytes=parse_bytes)
    paths = [Path(str(executable) + ".build.json")]
    if executable.suffix == ".exe":
        paths.append(executable.with_suffix(".build.json"))
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            inputs = data["inputs"]
            if (set(inputs) == INPUT_FIELDS and type(inputs["fuel"]) is int and inputs["fuel"] > 0
                    and data["kind"] == "ouro.native-tool-build.v1"
                    and data["cache"] in {"miss", "hit", "installed-hit"}
                    and inputs["kind"] == "ouro.native-tool-build.v1"
                    and inputs["entry"] == entry and inputs["sources"] == sources
                    and inputs["compiler_sha256"] == digest(compiler)
                    and data["binary_sha256"] == digest(executable)
                and data["key"] == hash_json(inputs)):
                from native_tool_build import tool_companions

                for companion in tool_companions(entry):
                    filename = companion[1] + (".exe" if sys.platform == "win32" else "")
                    receipt_for(executable.parent / filename, companion[0], compiler, parse_bytes=parse_bytes)
                return data, units, sources
        except (OSError, ValueError, KeyError, TypeError):
            continue
    raise ValueError(f"native build receipt is missing, incomplete, or stale: {executable}")


def save_result(path, result):
    """Keep raw host/process evidence outside the deterministic report body."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = asdict(result)
    row["peak_commit_mib" if sys.platform == "win32" else "peak_rss_mib"] = row.pop("peak_rss_mb")
    path.with_suffix(".json").write_text(json.dumps(row, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    path.with_suffix(".stdout").write_text(result.stdout, encoding="utf-8")
    path.with_suffix(".stderr").write_text(result.stderr, encoding="utf-8")


def evidence_problems(row, *, entry=None, root=None):
    """Recheck a deterministic NativeProgram evidence object against current files."""
    root = ROOT if root is None else root
    try:
        if not isinstance(row, dict) or set(row) != {"entry", "binary", "sha256", "compiler", "compiler_sha256", "build_key", "sources", "strict_check"}:
            return ["native driver evidence fields are incomplete or unknown"]
        if entry is not None and row["entry"] != entry:
            return ["native driver evidence names the wrong entry"]
        binary, compiler = ((root / row[key]).resolve() for key in ("binary", "compiler"))
        if not binary.is_relative_to(root) or not compiler.is_relative_to(root):
            return ["native driver evidence escapes its checkout"]
        receipt, _units, sources = receipt_for(binary, row["entry"], compiler)
        if (row["sources"] != sources or row["sha256"] != receipt["binary_sha256"]
                or row["compiler_sha256"] != receipt["inputs"]["compiler_sha256"]
                or row["build_key"] != receipt["key"]):
            return ["native driver evidence differs from the complete current build receipt"]
        if (row["strict_check"] != {"exit_code": 0, "stdout_sha256": hashlib.sha256(b"CHECK_OK\n").hexdigest()}
                or type(row["strict_check"].get("exit_code")) is not int):
            return ["native driver evidence lacks an exact successful strict source check"]
    except (OSError, ValueError, KeyError, TypeError):
        return ["native driver evidence or its current source inputs are unavailable"]
    else:
        return []


@dataclass
class NativeProgram:
    entry: str
    executable: Path
    compiler: Path
    receipt: dict
    units: list[str]
    sources: dict[str, str]
    work: Path
    memory_mb: int
    strict_stdout_sha256: str
    parse_bytes: ImportBytesParser | None = None

    def evidence(self):
        return {"entry": self.entry, "binary": self.executable.relative_to(ROOT).as_posix(),
                "sha256": self.receipt["binary_sha256"],
                "compiler": self.compiler.relative_to(ROOT).as_posix(),
                "compiler_sha256": self.receipt["inputs"]["compiler_sha256"],
                "build_key": self.receipt["key"], "sources": self.sources,
                "strict_check": {"exit_code": 0, "stdout_sha256": self.strict_stdout_sha256}}

    def unchanged(self):
        data, units, sources = receipt_for(self.executable, self.entry, self.compiler, parse_bytes=self.parse_bytes)
        return (sources == self.sources and units == self.units
                and data["key"] == self.receipt["key"]
                and data["binary_sha256"] == self.receipt["binary_sha256"])

    def _check_unchanged(self, phase):
        message = f"native driver inputs changed {phase} execution"
        try:
            unchanged = self.unchanged()
        except (OSError, ValueError) as error:
            raise ValueError(f"{message}: {error}") from error
        if not unchanged:
            raise ValueError(message)

    def run(self, arguments, label, timeout_s):
        self._check_unchanged("before")
        result = run_limited([str(self.executable), *arguments], cwd=ROOT,
                             env=environment(jobs=1), timeout_s=timeout_s, memory_mb=self.memory_mb)
        save_result(self.work / label, result)
        self._check_unchanged("during")
        return result


def prepare(entry, work, compiler, *, memory_mb, executable=None, log=print):
    """Check the actual source cone before running a freshly built or reused driver."""
    from native_tool_build import cached_import_parser

    work, compiler = Path(work).resolve(), Path(compiler).resolve()
    if not work.is_relative_to(ROOT) or not compiler.is_relative_to(ROOT):
        raise ValueError("native work and producer paths must stay inside the repository")
    work.mkdir(parents=True, exist_ok=True)
    parse_bytes = cached_import_parser()
    units, before = source_inputs(entry, parse_bytes=parse_bytes)
    producer_before = digest(compiler)
    supplied = executable is not None
    name = "compiler-smith" if entry == SMITH_ENTRY else "compiler-retained" if entry == RETAINED_ENTRY else Path(entry).stem
    executable = Path(executable).resolve() if supplied else ROOT / "_build/smith/native" / (name + (".exe" if sys.platform == "win32" else ""))
    env = environment(jobs=1, build=True)
    env.update(OURO_CCACHE="disabled", PYTHONDONTWRITEBYTECODE="1")
    check = [str(compiler), "check", entry, "999999"]
    for unit in units:
        check.extend(("--unit", unit))
    log(f"OURO_SMITH: native strict check {entry}")
    result = run_limited(check, cwd=ROOT, env=env, timeout_s=BUILD_TIMEOUT_S, memory_mb=BUILD_MEMORY_MB)
    save_result(work / "strict-check", result)
    if not result.ok or result.stderr or result.stdout.replace("\r\n", "\n") != "CHECK_OK\n":
        raise ValueError(f"native strict check failed: {result.classify()} exit={result.returncode}; {work / 'strict-check.json'}")
    try:
        receipt, _units, _sources = receipt_for(executable, entry, compiler, parse_bytes=parse_bytes)
    except (OSError, ValueError):
        if supplied:
            raise
        command = [sys.executable, "-B", str(ROOT / "scripts/native_tool_build.py"), entry, str(executable),
                   "--compiler", str(compiler), "--jobs", "1", "--fuel", "16000", "--opt-level", "O0",
                   "--ccache", "disabled"]
        log(f"OURO_SMITH: native build {entry}")
        built = run_limited(command, cwd=ROOT, env=env, timeout_s=BUILD_TIMEOUT_S, memory_mb=BUILD_MEMORY_MB)
        save_result(work / "build", built)
        if not built.ok:
            raise ValueError(f"native build failed: {built.classify()} exit={built.returncode}; {work / 'build.json'}") from None
        receipt, _units, _sources = receipt_for(executable, entry, compiler, parse_bytes=parse_bytes)
    if source_inputs(entry, parse_bytes=parse_bytes) != (units, before) or digest(compiler) != producer_before:
        raise ValueError("native driver source or producer changed while preparing")
    return NativeProgram(entry, executable, compiler, receipt, units, before, work, memory_mb,
                         hashlib.sha256(result.stdout.replace("\r\n", "\n").encode()).hexdigest(), parse_bytes=parse_bytes)


def bind(report, program):
    from ourosmith.provenance import binary_state

    report.sections.setdefault("native_drivers", {})[program.entry] = program.evidence()
    report.sections["provenance"]["binaries"].update(binary_state([program.compiler, program.executable]))
