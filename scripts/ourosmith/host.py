"""Locate installed tools and build native entry points through repository scripts."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from ourosmith import ROOT
from ourosmith.limits import clean_env, run_limited

TOOLS = ("collect", "fmt", "fix", "lint", "doc", "lsp", "test")
BUILD_MEMORY_MB = 3072
BUILD_TIMEOUT_S = 900


def build_config():
    from types import SimpleNamespace
    import ouro_build

    return ouro_build.load_config(SimpleNamespace())


def tool_entry(tool: str) -> str:
    if tool not in TOOLS:
        raise ValueError(f"unknown native tool: {tool}")
    return f"tools/{tool}/main.ouro" if tool in {"fix", "test"} else f"tools/{tool}.ouro"


def shell() -> Path:
    configured = os.environ.get("OURO_SH")
    if configured:
        path = Path(configured)
        if not path.is_file():
            raise FileNotFoundError(f"OURO_SH does not exist: {path}")
        return path.resolve()
    found = shutil.which("sh")
    if found:
        return Path(found).resolve()
    if os.name == "nt":
        for candidate in ("C:/msys64/usr/bin/sh.exe", "C:/Program Files/Git/usr/bin/sh.exe"):
            if Path(candidate).is_file():
                return Path(candidate)
    raise FileNotFoundError("POSIX sh unavailable; set OURO_SH to an installed shell")


def job_count() -> int:
    jobs = int(os.environ.get("OURO_JOBS", "10"))
    if jobs < 1:
        raise ValueError("OURO_JOBS must be a positive integer")
    # These workers run CPU-bound checks with individual wall-clock deadlines.
    # OURO_JOBS is a ceiling, not permission to oversubscribe a hosted runner.
    available = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count() or 1
    return min(jobs, max(1, available))


def environment(*, jobs: int | None = None, build: bool = False) -> dict[str, str]:
    jobs = job_count() if jobs is None else jobs
    env = clean_env()
    env.update({"OURO_ROOT": ROOT.as_posix(), "OURO_JOBS": str(jobs),
                "OURO_FRONTEND_JOBS": str(jobs), "OURO_REPRODUCIBLE": "1",
                "OURO_TEST_CHECK": (ROOT / "scripts/ouro1.sh").as_posix(),
                "OURO_TEST_BUILD": (ROOT / "scripts/build_tool.sh").as_posix(),
                "OURO_HOSTED_COMPILER_WRAPPER": (ROOT / "scripts/ouro1.sh").as_posix(),
                "OURO_HOSTED_FMT": (build_config().path("c_build_dir") / "ouro-fmt").as_posix()})
    sh = shell()
    env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), str(sh.parent), env.get("PATH", "")])
    env["OURO_POSIX_SH"] = sh.as_posix()
    if build:
        env["PYTHON"] = Path(sys.executable).as_posix()
        for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA",
                    "CC", "OURO_CACHE", "OURO_CCACHE"):
            if key in os.environ:
                env[key] = os.environ[key]
        cfg = build_config()
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


def compiler_path(value: Path | str | None = None) -> Path:
    path = Path(value).resolve() if value is not None else binary("ouro1")
    if not path.is_relative_to(ROOT) or not path.is_file() or path.stat().st_size <= 4096:
        raise ValueError(f"native compiler must be an existing repository-local binary: {path}")
    return path


def toolchain_evidence(compiler: Path, overrides: dict[str, Path]) -> dict:
    from ourosmith.native import digest, receipt_for

    compiler = compiler_path(compiler)
    if set(overrides) != {"ouro1", *("ouro-" + tool for tool in TOOLS)} or overrides["ouro1"] != compiler:
        raise ValueError("the complete native tool map must use the selected compiler")
    entries = {}
    for tool in TOOLS:
        path = Path(overrides["ouro-" + tool]).resolve()
        receipt, _units, _sources = receipt_for(path, tool_entry(tool), compiler)
        entries[tool] = {"entry": tool_entry(tool), "binary": path.relative_to(ROOT).as_posix(),
                         "sha256": receipt["binary_sha256"], "build_key": receipt["key"]}
    return {"kind": "ouro.smith-toolchain.v1", "compiler": compiler.relative_to(ROOT).as_posix(),
            "compiler_sha256": digest(compiler), "tools": entries}


def toolchain_paths(evidence: dict, *, compiler: Path | None = None) -> dict[str, Path]:
    """Recover an exact tool map only from complete current build receipts."""
    if (not isinstance(evidence, dict) or set(evidence) != {"kind", "compiler", "compiler_sha256", "tools"}
            or evidence["kind"] != "ouro.smith-toolchain.v1" or not isinstance(evidence["tools"], dict)
            or set(evidence["tools"]) != set(TOOLS)):
        raise ValueError("native toolchain evidence is incomplete or malformed")
    selected = compiler_path(ROOT / evidence["compiler"])
    if compiler is not None and selected != Path(compiler).resolve():
        raise ValueError("surface toolchain uses a different compiler")
    overrides = {"ouro1": selected}
    for tool in TOOLS:
        entry = evidence["tools"][tool]
        if not isinstance(entry, dict) or set(entry) != {"entry", "binary", "sha256", "build_key"}:
            raise ValueError("native tool evidence fields are incomplete or unknown")
        overrides["ouro-" + tool] = (ROOT / entry["binary"]).resolve()
    if toolchain_evidence(selected, overrides) != evidence:
        raise ValueError("native toolchain evidence differs from current source or binaries")
    return overrides


def prepare_tools(out: Path, compiler: Path) -> tuple[dict[str, Path], dict]:
    """Use one explicit producer and source-bound tools without rebuilding a seed."""
    from ourosmith.native import digest

    compiler = compiler_path(compiler)
    producer_hash = digest(compiler)
    cfg = build_config()
    # Stable paths preserve report fingerprints across repeated output directories.
    # Complete digests remain in receipts; short paths fit native Windows builds.
    directory = (cfg.path("build_dir") / "smith-tools" / producer_hash[:16]).resolve()
    if not directory.is_relative_to(ROOT):
        raise ValueError("Smith native tool outputs must stay inside the repository")
    overrides = {"ouro1": compiler}
    for tool in TOOLS:
        target = directory / ("ouro-" + tool + (".exe" if os.name == "nt" else ""))
        command = [sys.executable, "-B", str(ROOT / "scripts/native_tool_build.py"), tool_entry(tool), str(target),
                   "--compiler", str(compiler), "--jobs", "1", "--ccache", "disabled",
                   "--build-dir", str(directory / "build"), "--cache-dir", str(cfg.path("cache_dir"))]
        reason = build_command(command, Path(out) / (tool + "-build.log"), timeout_s=BUILD_TIMEOUT_S)
        if reason:
            raise ValueError(reason)
        overrides["ouro-" + tool] = binary("ouro-" + tool, directory=directory)
    evidence = toolchain_evidence(compiler, overrides)
    if digest(compiler) != producer_hash:
        raise ValueError("native producer changed during tool preparation")
    return overrides, evidence


def build_command(argv: list[str], log: Path, *, timeout_s: float = 600) -> str | None:
    try:
        proc = run_limited(argv, cwd=ROOT, env=environment(build=True), timeout_s=timeout_s, memory_mb=BUILD_MEMORY_MB)
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
    return build_command(
        [sys.executable, str(ROOT / "scripts/ouro_build.py"), "build", "--jobs", str(job_count())],
        path,
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
        reason = build_command([str(shell()), str(ROOT / "scripts/build_tool.sh"),
                                tool_entry(tool), target.as_posix()], out / f"{tool}-build.log")
        if reason:
            return reason
        binary("ouro-" + tool)
    return None
