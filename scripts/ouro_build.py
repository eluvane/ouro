#!/usr/bin/env python3
"""Build, configure, and cache the current Ouro compiler.

The temporary host driver retains C build routines for the pinned bootstrap
and native tools. bootstrap_compiler orchestrates checked successor builds;
program acceptance belongs to the Ouro compiler.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import BinaryIO, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

from local_scheduler import bounded_jobs
from repo_support import filename_fragment
from repo_support import hash_json
from repo_support import read_json_object_or_none
from repo_support import bind_relative_path, decode_source_text, relative_path, sha256_bytes, sha256_file, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
rel = bind_relative_path(ROOT, resolve=False)

# Local helper module.  Keep source-backed imports so copied repos shard with
# their own generator-cache policy.
sys.path.insert(0, str(ROOT / "scripts"))
import generated_c_shards as GCS  # noqa: E402
import ouro_seal  # noqa: E402

DEFAULTS: Dict[str, object] = {
    "profile": "dev",
    "jobs": "auto",
    "cc": "cc",
    "opt_level": "O1",
    "build_dir": "_build",
    "c_build_dir": "_build/c",
    "cache_dir": "_cache/ouro",
    "cache_enabled": True,
    "cache_size_mb": 2048,
    "cache_cleanup_policy": "lru",
    "ccache": "auto",
    "verbosity": "normal",
    "reproducible": False,
}

ENV_MAP = {
    "profile": "OURO_PROFILE",
    "jobs": "OURO_JOBS",
    "cc": "CC",
    "opt_level": "OURO_OPT_LEVEL",
    "build_dir": "OURO_BUILD_DIR",
    "c_build_dir": "OURO_C_BUILD_DIR",
    "cache_dir": "OURO_CACHE_DIR",
    "cache_enabled": "OURO_CACHE",
    "cache_size_mb": "OURO_CACHE_SIZE_MB",
    "cache_cleanup_policy": "OURO_CACHE_CLEANUP_POLICY",
    "ccache": "OURO_CCACHE",
    "verbosity": "OURO_VERBOSITY",
    "reproducible": "OURO_REPRODUCIBLE",
}

TRUTHY = {"1", "true", "yes", "on", "enabled"}
FALSY = {"0", "false", "no", "off", "disabled"}


@dataclass(frozen=True)
class ResolvedConfig:
    values: Dict[str, object]
    sources: Dict[str, str]

    def get_bool(self, key: str) -> bool:
        return as_bool(self.values[key])

    def get_int(self, key: str) -> int:
        value = self.values[key]
        if isinstance(value, int):
            return value
        try:
            return int(str(value), 10)
        except ValueError as exc:
            raise SystemExit(f"CONFIG: {key} must be an integer, got {value!r}") from exc

    def path(self, key: str) -> Path:
        value = Path(str(self.values[key]))
        return value if value.is_absolute() else ROOT / value

    def delete_path(self, key: str) -> Path:
        target = self.path(key).resolve(strict=False)
        protected = (ROOT.resolve(), Path.cwd().resolve(), Path.home().resolve())
        if target == Path(target.anchor) or any(target == base or target in base.parents for base in protected):
            raise SystemExit(f"CONFIG: refusing unsafe deletion target for {key}: {target}")
        return target


def as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in TRUTHY:
        return True
    if s in FALSY:
        return False
    raise SystemExit(f"CONFIG: expected boolean, got {value!r}")


def parse_project_config(path: Path) -> Dict[str, object]:
    """Read build/cache keys from Ouro.seal. Other blocks are ignored here."""
    return ouro_seal.load_build_keys(path)


def coerce(key: str, value: object) -> object:
    if key in {"cache_enabled", "reproducible"}:
        return as_bool(value)
    if key in {"cache_size_mb"}:
        try:
            return int(str(value), 10)
        except ValueError as exc:
            raise SystemExit(f"CONFIG: {key} must be integer, got {value!r}") from exc
    if key == "jobs":
        if str(value) == "auto":
            return "auto"
        try:
            n = int(str(value), 10)
        except ValueError as exc:
            raise SystemExit(f"CONFIG: jobs must be auto or positive integer, got {value!r}") from exc
        if n < 1:
            raise SystemExit("CONFIG: jobs must be positive")
        return n
    return str(value)


def load_config(cli: argparse.Namespace) -> ResolvedConfig:
    values = dict(DEFAULTS)
    sources = {k: "defaults" for k in DEFAULTS}

    cfg_path = getattr(cli, "config", None) or ROOT / ouro_seal.SEAL_NAME
    cfg_path = Path(cfg_path)
    if not cfg_path.is_absolute():
        cfg_path = ROOT / cfg_path
    project = parse_project_config(cfg_path)
    for key, val in project.items():
        values[key] = coerce(key, val)
        sources[key] = f"project config:{cfg_path.relative_to(ROOT) if cfg_path.is_relative_to(ROOT) else cfg_path}"

    for key, env_key in ENV_MAP.items():
        if env_key in os.environ and os.environ[env_key] != "":
            values[key] = coerce(key, os.environ[env_key])
            sources[key] = f"environment:{env_key}"

    cli_overrides = {
        "profile": getattr(cli, "profile", None),
        "jobs": getattr(cli, "jobs", None),
        "cc": getattr(cli, "cc", None),
        "opt_level": getattr(cli, "opt_level", None),
        "build_dir": getattr(cli, "build_dir", None),
        "c_build_dir": getattr(cli, "c_build_dir", None),
        "cache_dir": getattr(cli, "cache_dir", None),
        "cache_enabled": getattr(cli, "cache_enabled", None),
        "cache_size_mb": getattr(cli, "cache_size_mb", None),
        "cache_cleanup_policy": getattr(cli, "cache_cleanup_policy", None),
        "ccache": getattr(cli, "ccache", None),
        "verbosity": getattr(cli, "verbosity", None),
        "reproducible": getattr(cli, "reproducible", None),
    }
    for key, val in cli_overrides.items():
        if val is not None:
            values[key] = coerce(key, val)
            sources[key] = "CLI"

    if values["profile"] not in {"dev", "release"}:
        raise SystemExit("CONFIG: profile must be dev or release")
    if str(values["ccache"]) not in {"auto", "enabled", "disabled"}:
        raise SystemExit("CONFIG: ccache must be auto, enabled, or disabled")
    if str(values["verbosity"]) not in {"quiet", "normal", "verbose"}:
        raise SystemExit("CONFIG: verbosity must be quiet, normal, or verbose")
    return ResolvedConfig(values, sources)


def jobs_value(cfg: ResolvedConfig) -> int:
    raw = cfg.values["jobs"]
    return bounded_jobs((os.cpu_count() or 1) if raw == "auto" else int(raw))


def log(cfg: ResolvedConfig, msg: str, *, verbose_only: bool = False) -> None:
    if cfg.values["verbosity"] == "quiet":
        return
    if verbose_only and cfg.values["verbosity"] != "verbose":
        return
    print(msg)


def run(cmd: Sequence[str], *, cwd: Path = ROOT, env: Optional[Mapping[str, str]] = None) -> None:
    p = subprocess.run(list(cmd), cwd=str(cwd), env=dict(env) if env else None)
    if p.returncode != 0:
        raise SystemExit(p.returncode)


def output_or_empty(cmd: Sequence[str]) -> str:
    try:
        return subprocess.check_output(list(cmd), cwd=str(ROOT), stderr=subprocess.STDOUT, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""


def locate_cc(cfg: ResolvedConfig) -> tuple[str, str | None]:
    cc = str(cfg.values["cc"])
    location = shutil.which(cc)
    if location or Path(cc).is_file():
        return cc, location
    if cc == "cc" and (location := shutil.which("gcc")):
        return "gcc", location
    raise SystemExit(f"BOOTSTRAP: FAIL no system C compiler ({cc!r})")


def choose_cc(cfg: ResolvedConfig) -> str:
    cc, _location = locate_cc(cfg)
    return cc


def cc_invocation(cc: str) -> list[str]:
    # Cache suites pass a Python fake-cc. Windows CreateProcess cannot run a
    # shebang .py, and shutil.which ignores those files.
    p = Path(cc)
    if p.suffix.lower() == ".py" and p.is_file():
        return [sys.executable, str(p.resolve())]
    return [cc]


def compiler_id(cc: str, *, location: str | None = None) -> str:
    if location is None:
        location = shutil.which(cc) or (str(Path(cc).resolve()) if Path(cc).is_file() else cc)
    version = output_or_empty(cc_invocation(cc) + ["--version"]).splitlines()[:2]
    return json.dumps({"cc": cc, "path": location, "version": version}, sort_keys=True)


def profile_cflags(cfg: ResolvedConfig) -> List[str]:
    opt = str(cfg.values["opt_level"])
    if not opt.startswith("O"):
        opt = "O" + opt
    flags = [f"-{opt}", "-std=c99", "-D_POSIX_C_SOURCE=200809L"]
    if cfg.get_bool("reproducible"):
        flags.extend(["-fdebug-prefix-map=.=/ouro", "-fmacro-prefix-map=.=/ouro"])
    return flags


def object_profile_cflags(cflags: Sequence[str], compiler_version: Sequence[str]) -> List[str]:
    flags = list(cflags)
    if any("clang" in line.lower() for line in compiler_version):
        # Generated constructors exceed Clang's default depth. Clippy resource laws need 4096.
        flags.append("-fbracket-depth=4096")
    return flags


@dataclass(frozen=True)
class Target:
    name: str
    sources: Tuple[str, ...]
    include_dirs: Tuple[str, ...] = ()
    extra_cflags: Tuple[str, ...] = ()


C_TARGETS: Tuple[Target, ...] = (
    Target(
        "ouro1",
        (
            "compiler/stage0/driver_u.c",
            "compiler/stage0/backend_u.c",
            "runtime/ouro_rt.c",
            "runtime/bootstrap.c",
        ),
        ("runtime",),
        ("-Werror=implicit-function-declaration",),
    ),
)


def safe_obj_name(target: str, source: str, flags_hash: str) -> str:
    stem = filename_fragment(source, 140, "source")
    return f"{filename_fragment(target, 140, 'source')}__{stem}__{flags_hash[:12]}.o"


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}.{time.time_ns()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def path_key(path: Path, *, resolved_root: Path | None = None) -> str:
    root = ROOT.resolve() if resolved_root is None else resolved_root
    return relative_path(root, path.resolve(), resolve=False)


def _object_digests(objects: Sequence[Path]) -> dict[str, str]:
    if not objects:
        return {}
    root = ROOT.resolve()
    return {path_key(obj, resolved_root=root): sha256_file(obj) for obj in objects}


def parse_depfile(path: Path) -> List[Path]:
    if not path.exists():
        return []
    return _parse_depfile_text(path.read_text(encoding="utf-8"))


def _parse_depfile_text(text: str) -> List[Path]:
    text = text.replace("\\\n", " ")
    # Makefile `target: deps`. Drive letters are `C:\`; only `: ` / end splits the rule.
    rule = re.search(r":(?:\s|$)", text)
    if rule:
        text = text[rule.end():]
    deps: List[Path] = []
    seen = set()
    # Do not use shlex: Windows `I:\path` backslashes are not shell escapes.
    for raw_tok in text.replace("\\ ", "__SPACE__").split():
        tok = raw_tok.replace("__SPACE__", " ").strip()
        if not tok or tok == "\\" or tok.endswith(":"):
            continue
        p = Path(tok)
        if not p.is_absolute():
            p = ROOT / p
        try:
            rp = p.resolve()
        except FileNotFoundError:
            rp = p.absolute()
        key = str(rp)
        if key in seen:
            continue
        seen.add(key)
        deps.append(rp)
    return deps


def dep_digests_from_depfile(dep: Path, src: Path, *, text: str | None = None) -> Dict[str, str]:
    deps = parse_depfile(dep) if text is None else _parse_depfile_text(text)
    src_resolved = src.resolve()
    if not deps:
        deps = [src_resolved]
    elif all(d != src_resolved for d in deps):
        deps.insert(0, src_resolved)
    digests: Dict[str, str] = {}
    root: Path | None = None
    for d in deps:
        if not d.exists():
            raise FileNotFoundError(str(d))
        digest = sha256_file(d)
        if root is None:
            root = ROOT.resolve()
        digests[path_key(d, resolved_root=root)] = digest
    return digests


def command_hash(parts: Sequence[str], cc_id: str) -> str:
    return hash_json({"cmd": list(parts), "compiler": cc_id})


def compile_stamp_digest(obj: Path, dep: Path, stamp: Path, expected_hash: str, src: Path, *,
                         expected_object_hash: str | None = None,
                         expected_stamp_fields: Mapping[str, object] | None = None) -> tuple[str | None, str]:
    if not obj.exists():
        return None, "missing-object"
    if not dep.exists():
        return None, "missing-depfile"
    data = read_json_object_or_none(stamp)
    if data is None:
        return None, "missing-or-invalid-stamp"
    if expected_stamp_fields is not None and any(data.get(key) != value for key, value in expected_stamp_fields.items()):
        return None, "stamp-command"
    if data.get("kind") != "ouro.c-object.v2":
        return None, "stamp-kind"
    if data.get("command_hash") != expected_hash:
        return None, "command-hash"
    if data.get("source") != path_key(src):
        return None, "source-path"
    try:
        dep_bytes = dep.read_bytes() if dep.exists() else None
        deps = dep_digests_from_depfile(dep, src, text=decode_source_text(dep_bytes) if dep_bytes is not None else "")
    except (FileNotFoundError, OSError, UnicodeError):
        return None, "unreadable-dependency"
    if data.get("dependencies") != deps:
        return None, "dependency-hash"
    try:
        obj_hash = sha256_file(obj)
    except FileNotFoundError:
        return None, "missing-output"
    if dep_bytes is None:
        return None, "missing-output"
    if data.get("object_sha256") != obj_hash or (expected_object_hash is not None and obj_hash != expected_object_hash):
        return None, "object-hash"
    if data.get("depfile_sha256") != sha256_bytes(dep_bytes):
        return None, "depfile-hash"
    return obj_hash, "hit"


def link_stamp_digest(exe: Path, stamp: Path, expected_hash: str, objects: Sequence[Path], *,
                      expected_stamp_fields: Mapping[str, object] | None = None) -> tuple[str | None, str]:
    if not exe.exists():
        return None, "missing-exe"
    data = read_json_object_or_none(stamp)
    if data is None:
        return None, "missing-or-invalid-stamp"
    if expected_stamp_fields is not None and any(data.get(key) != value for key, value in expected_stamp_fields.items()):
        return None, "stamp-command"
    if data.get("kind") != "ouro.c-link.v2":
        return None, "stamp-kind"
    if data.get("command_hash") != expected_hash:
        return None, "command-hash"
    try:
        obj_digests = _object_digests(objects)
        out_hash = sha256_file(exe)
    except FileNotFoundError:
        return None, "missing-object-or-exe"
    if data.get("objects") != obj_digests:
        return None, "object-hash"
    if data.get("output_sha256") != out_hash:
        return None, "output-hash"
    return out_hash, "hit"


def ccache_prefix(cfg: ResolvedConfig, cc: str, *,
                  find_ccache: Callable[[], str | None] | None = None) -> Tuple[List[str], Dict[str, str], str]:
    env: Dict[str, str] = {}
    if not cfg.get_bool("cache_enabled"):
        return cc_invocation(cc), env, "disabled-cache-off"
    mode = str(cfg.values["ccache"])
    if mode == "disabled":
        return cc_invocation(cc), env, "disabled"
    ccache = shutil.which("ccache") if find_ccache is None else find_ccache()
    if mode == "auto" and not ccache:
        return cc_invocation(cc), env, "auto-unavailable"
    if mode == "enabled" and not ccache:
        raise SystemExit("CONFIG: ccache=enabled but ccache is not installed")
    cache_root = cfg.path("cache_dir") / "ccache"
    cache_root.mkdir(parents=True, exist_ok=True)
    env["CCACHE_DIR"] = str(cache_root)
    env["CCACHE_MAXSIZE"] = f"{cfg.get_int('cache_size_mb')}M"
    # ccache caches single translation-unit compilation; linking is still done
    # with the real compiler so cache misses cannot hide link changes.
    return [str(ccache)] + cc_invocation(cc), env, "enabled"


def compile_c_object(
    cfg: ResolvedConfig,
    cc: str,
    cc_id: str,
    target_name: str,
    source_path: Path,
    source_label: str,
    flags: Sequence[str],
    obj_dir: Path,
    *,
    reuse_object: tuple[str, str] | None = None,
    find_ccache: Callable[[], str | None] | None = None,
) -> Tuple[Path, dict]:
    t0 = time.perf_counter()
    src = source_path if source_path.is_absolute() else ROOT / source_path
    src = src.resolve()
    if not src.exists():
        raise SystemExit(f"BOOTSTRAP: FAIL missing {source_path}")
    source_key = path_key(src)
    display = source_label or source_key
    candidates = [(target_name, None)] if reuse_object is None else [reuse_object, (target_name, None)]
    for candidate, expected_object_hash in candidates:
        flags_key = hash_json({"flags": flags, "target": candidate, "source": source_key, "label": display})
        obj = obj_dir / safe_obj_name(candidate, display, flags_key)
        dep = obj.with_suffix(".d")
        stamp = obj.with_suffix(".cmdhash")
        desired_cmd = [cc, *flags, "-MMD", "-MP", "-MF", str(dep), "-c", source_key, "-o", str(obj)]
        expected = command_hash(desired_cmd, cc_id)
        object_hash, reason = compile_stamp_digest(obj, dep, stamp, expected, src,
                                                   expected_object_hash=expected_object_hash)
        if object_hash is not None:
            elapsed = round(time.perf_counter() - t0, 6)
            log(cfg, f"CC-HIT {source_key}", verbose_only=True)
            report = {
                "source": source_key,
                "label": display,
                "object": rel(obj),
                "depfile": rel(dep),
                "cmdhash": rel(stamp),
                "cache": "hit",
                "reason": reason,
                "elapsed_s": elapsed,
                "object_sha256": object_hash,
                "ccache": "not-invoked",
            }
            if candidate != target_name:
                report["object_reused_from"] = candidate
            return obj, report
    obj.parent.mkdir(parents=True, exist_ok=True)

    prefix, cc_env, ccache_state = ccache_prefix(cfg, cc, find_ccache=find_ccache)
    env = os.environ.copy()
    env.update(cc_env)
    token = f"{os.getpid()}.{time.time_ns()}"
    tmp_obj = obj.with_name(obj.name + f".tmp.{token}")
    tmp_dep = dep.with_name(dep.name + f".tmp.{token}")
    tmp_obj.unlink(missing_ok=True)
    tmp_dep.unlink(missing_ok=True)
    cmd = [*prefix, *flags, "-MMD", "-MP", "-MF", str(tmp_dep), "-c", str(src), "-o", str(tmp_obj)]
    log(cfg, f"CC {source_key} -> {rel(obj)}")
    p = subprocess.run(cmd, cwd=str(ROOT), env=env)
    if p.returncode != 0:
        tmp_obj.unlink(missing_ok=True)
        tmp_dep.unlink(missing_ok=True)
        raise SystemExit(p.returncode)
    if not tmp_obj.exists():
        tmp_dep.unlink(missing_ok=True)
        raise SystemExit(f"BOOTSTRAP: FAIL compiler did not produce {tmp_obj}")
    if not tmp_dep.exists():
        # Some fake/minimal compilers ignore -MMD. Keep the cache safe by
        # recording at least the source dependency instead of accepting no deps.
        tmp_dep.write_text(f"{tmp_obj}: {src}\n", encoding="utf-8")
    os.replace(tmp_dep, dep)
    os.replace(tmp_obj, obj)
    dep_bytes = dep.read_bytes()
    deps = dep_digests_from_depfile(dep, src, text=decode_source_text(dep_bytes))
    source_key = path_key(src)
    stamp_data = {
        "kind": "ouro.c-object.v2",
        "target": target_name,
        "source": source_key,
        "label": display,
        "command_hash": expected,
        "command": desired_cmd,
        "compiler_id": cc_id,
        "dependencies": deps,
        "object": rel(obj),
        "object_sha256": sha256_file(obj),
        "depfile": rel(dep),
        "depfile_sha256": sha256_bytes(dep_bytes),
        "ccache": ccache_state,
        "updated_at_unix": time.time(),
    }
    write_json_atomic(stamp, stamp_data)
    elapsed = round(time.perf_counter() - t0, 6)
    return obj, {
        "source": source_key,
        "label": display,
        "object": rel(obj),
        "depfile": rel(dep),
        "cmdhash": rel(stamp),
        "cache": "miss",
        "reason": reason,
        "elapsed_s": elapsed,
        "object_sha256": stamp_data["object_sha256"],
        "dependency_count": len(deps),
        "ccache": ccache_state,
    }


def host_link_flags() -> List[str]:
    # PE default stack is 1MiB. ouro1 recursion hits STATUS_STACK_OVERFLOW (0xC00000FD).
    if os.name == "nt":
        return ["-Wl,--stack,2147483648"]
    if sys.platform == "darwin":
        # Mach-O owns the main-thread reserve; host Python may pin RLIMIT_STACK.
        return ["-Wl,-stack_size,0x8000000"]
    return []


def link_c_objects(
    cfg: ResolvedConfig,
    cc: str,
    cc_id: str,
    target_name: str,
    objects: Sequence[Path],
    output: Path,
    link_flags: Sequence[str],
) -> dict:
    t0 = time.perf_counter()
    exe = output if output.is_absolute() else ROOT / output
    exe.parent.mkdir(parents=True, exist_ok=True)
    flags = profile_cflags(cfg) + list(link_flags) + host_link_flags()
    desired_cmd = [cc] + flags + ["-o", str(exe)] + [str(o) for o in objects]
    expected = command_hash(desired_cmd, cc_id)
    stamp = Path(str(exe) + ".cmdhash")
    output_hash, reason = link_stamp_digest(exe, stamp, expected, objects)
    if output_hash is not None:
        elapsed = round(time.perf_counter() - t0, 6)
        log(cfg, f"LINK-HIT {rel(exe)}", verbose_only=True)
        return {
            "cache": "hit",
            "reason": reason,
            "elapsed_s": elapsed,
            "output": rel(exe),
            "cmdhash": rel(stamp),
            "bytes": exe.stat().st_size,
            "output_sha256": output_hash,
        }

    token = f"{os.getpid()}.{time.time_ns()}"
    tmp_exe = exe.with_name(exe.name + f".tmp.{token}" + (".exe" if os.name == "nt" else ""))
    tmp_exe.unlink(missing_ok=True)
    cmd = cc_invocation(cc) + flags + ["-o", str(tmp_exe)] + [str(o) for o in objects]
    log(cfg, f"LINK {rel(exe)}")
    p = subprocess.run(cmd, cwd=str(ROOT))
    if p.returncode != 0:
        tmp_exe.unlink(missing_ok=True)
        raise SystemExit(p.returncode)
    if not tmp_exe.exists():
        raise SystemExit(f"BOOTSTRAP: FAIL linker did not produce {tmp_exe}")
    try:
        mode = tmp_exe.stat().st_mode
        tmp_exe.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except FileNotFoundError:
        pass
    os.replace(tmp_exe, exe)
    obj_digests = _object_digests(objects)
    stamp_data = {
        "kind": "ouro.c-link.v2",
        "target": target_name,
        "output": rel(exe),
        "command_hash": expected,
        "command": desired_cmd,
        "compiler_id": cc_id,
        "objects": obj_digests,
        "output_sha256": sha256_file(exe),
        "bytes": exe.stat().st_size,
        "updated_at_unix": time.time(),
    }
    write_json_atomic(stamp, stamp_data)
    elapsed = round(time.perf_counter() - t0, 6)
    return {
        "cache": "miss",
        "reason": reason,
        "elapsed_s": elapsed,
        "output": rel(exe),
        "cmdhash": rel(stamp),
        "bytes": stamp_data["bytes"],
        "output_sha256": stamp_data["output_sha256"],
    }


def build_c_executable(
    cfg: ResolvedConfig,
    *,
    name: str,
    sources: Sequence[Tuple[str, Path]],
    output: Path,
    object_dir: Path,
    include_dirs: Sequence[Path] = (),
    extra_cflags: Sequence[str] = (),
    source_cflags: Optional[Mapping[str, Sequence[str]]] = None,
    object_reuse: Mapping[str, tuple[str, str]] | None = None,
    link_flags: Sequence[str] = (),
    jobs: Optional[int] = None,
    report_path: Optional[Path] = None,
    generated_c_shards: Optional[dict] = None,
) -> dict:
    started = time.perf_counter()
    indexed = list(enumerate(sources))
    flags_by_source = {label: tuple(flags) for label, flags in (source_cflags or {}).items()}
    source_labels = {label for _, (label, _path) in indexed}
    unknown_labels = flags_by_source.keys() - source_labels
    if unknown_labels:
        raise ValueError("unknown C source flag labels: " + ", ".join(sorted(unknown_labels)))
    reuse_by_source = object_reuse or {}
    unknown_labels = reuse_by_source.keys() - source_labels
    if unknown_labels:
        raise ValueError("unknown C object reuse labels: " + ", ".join(sorted(unknown_labels)))
    cc, location = locate_cc(cfg)
    cc_id = compiler_id(cc, location=location or str(Path(cc).resolve()))
    max_jobs = bounded_jobs(jobs or jobs_value(cfg))
    scheduled = indexed
    if max_jobs > 1:
        scheduled = sorted(indexed, key=lambda item:
            (item[1][1] if item[1][1].is_absolute() else ROOT / item[1][1]).stat().st_size, reverse=True)
    object_dir.mkdir(parents=True, exist_ok=True)
    base_flags = (*object_profile_cflags(profile_cflags(cfg), json.loads(cc_id)["version"]), *extra_cflags)
    includes = tuple(f"-I{path if path.is_absolute() else ROOT / path}" for path in include_dirs)
    common_flags = base_flags + includes
    compile_flags = {label: base_flags + flags + includes for label, flags in flags_by_source.items()}
    ccache_lock = Lock()
    ccache_checked = False
    ccache_location: str | None = None

    def find_ccache() -> str | None:
        nonlocal ccache_checked, ccache_location
        with ccache_lock:
            if not ccache_checked:
                ccache_location = shutil.which("ccache")
                ccache_checked = True
            return ccache_location

    objects: Dict[int, Path] = {}
    source_reports: Dict[int, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_jobs) as pool:
        futs = {
            pool.submit(
                compile_c_object,
                cfg,
                cc,
                cc_id,
                name,
                path,
                label,
                compile_flags.get(label, common_flags),
                object_dir,
                find_ccache=find_ccache,
                **({"reuse_object": reuse_by_source[label]} if label in reuse_by_source else {}),
            ): idx
            for idx, (label, path) in scheduled
        }
        for fut in concurrent.futures.as_completed(futs):
            idx = futs[fut]
            obj, report = fut.result()
            objects[idx] = obj
            source_reports[idx] = report
    ordered_objects = [objects[i] for i, _ in indexed]
    ordered_reports = [source_reports[i] for i, _ in indexed]
    link_report = link_c_objects(cfg, cc, cc_id, name, ordered_objects, output, link_flags)
    compile_hits = sum(1 for r in ordered_reports if r.get("cache") == "hit")
    compile_misses = sum(1 for r in ordered_reports if r.get("cache") == "miss")
    slowest = sorted(
        (
            {
                "source": r.get("source"),
                "label": r.get("label"),
                "elapsed_s": r.get("elapsed_s", 0),
                "cache": r.get("cache"),
            }
            for r in ordered_reports
        ),
        key=lambda r: float(r.get("elapsed_s") or 0),
        reverse=True,
    )[:8]
    report = {
        "kind": "ouro.c-build-report.v2",
        "target": name,
        "output": rel(output if output.is_absolute() else ROOT / output),
        "cc": cc,
        "compiler_id": cc_id,
        "compile_hits": compile_hits,
        "compile_misses": compile_misses,
        "link_cache": link_report.get("cache"),
        "link_hit": link_report.get("cache") == "hit",
        "link_miss": link_report.get("cache") == "miss",
        "sources": ordered_reports,
        "objects": [rel(o) for o in ordered_objects],
        "link": link_report,
        "slowest_sources": slowest,
        "elapsed_s": round(time.perf_counter() - started, 6),
    }
    if generated_c_shards is not None:
        report["generated_c_shards"] = generated_c_shards
    if report_path is not None:
        write_json_atomic(report_path, report)
    return report


def ensure_fe_link() -> Path:
    """Write the generated FIND+apply linker used by ouro1 / stage_loop."""
    src = ROOT / "runtime" / "frontend_link.c"
    dest = ROOT / "_build" / "gen" / "fe_link.c"
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = src.read_text(encoding="utf-8")
    banner = "/* Generated frontend linker. Source: runtime/frontend_link.c. Do not hand-edit. */\n"
    if not text.startswith("/* Generated frontend linker."):
        text = banner + text
    data = text.replace("\n", os.linesep).encode("utf-8")
    try:
        if dest.is_file():
            with dest.open("rb") as existing:
                if existing.read(len(data) + 1) == data:
                    return dest
    except OSError:
        pass
    dest.write_bytes(data)
    return dest


def generated_stage0_sources(cfg: ResolvedConfig) -> Tuple[List[Tuple[str, Path]], dict]:
    shard_dir = cfg.path("build_dir") / "generated_c_shards" / "stage0"
    sources, shard_report = GCS.materialize_generated_c_shards(
        frontend_c=ROOT / "compiler/stage0/driver_u.c",
        backend_c=ROOT / "compiler/stage0/backend_u.c",
        out_dir=shard_dir,
        label_prefix="stage0",
        cache_enabled=cfg.get_bool("cache_enabled"),
        report_path=shard_dir / "generated-c-shards.report.json",
    )
    sources.extend(
        [
            ("static/ouro_rt", ROOT / "runtime/ouro_rt.c"),
            ("static/bootstrap", ROOT / "runtime/bootstrap.c"),
            ("static/fe_link", ensure_fe_link()),
        ]
    )
    return sources, shard_report


def target_source_list(cfg: ResolvedConfig, target: Target) -> Tuple[List[Tuple[str, Path]], Optional[dict]]:
    if target.name == "ouro1":
        return generated_stage0_sources(cfg)
    return [(src, ROOT / src) for src in target.sources], None


def build_c(cfg: ResolvedConfig) -> Dict[str, int]:
    out_dir = cfg.path("c_build_dir")
    obj_dir = out_dir / "obj"
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs = jobs_value(cfg)
    compiled = 0
    linked = 0
    compile_reports: List[dict] = []
    link_reports: List[dict] = []
    target_reports: List[dict] = []
    shard_reports: Dict[str, dict] = {}
    for target in C_TARGETS:
        sources, shard_report = target_source_list(cfg, target)
        report = build_c_executable(
            cfg,
            name=target.name,
            sources=sources,
            output=out_dir / target.name,
            object_dir=obj_dir,
            include_dirs=[ROOT / d for d in target.include_dirs],
            extra_cflags=target.extra_cflags,
            jobs=jobs,
            report_path=out_dir / f"{target.name}-build-report.json",
            generated_c_shards=shard_report,
        )
        compiled += int(report.get("compile_misses") or 0)
        if report.get("link_cache") == "miss":
            linked += 1
        compile_reports.extend(r for r in report.get("sources", []) if isinstance(r, dict))
        if isinstance(report.get("link"), dict):
            link_reports.append(report["link"])
        target_item = {
            "target": target.name,
            "compile_hits": report.get("compile_hits", 0),
            "compile_misses": report.get("compile_misses", 0),
            "link_cache": report.get("link_cache"),
            "elapsed_s": report.get("elapsed_s", 0),
        }
        if shard_report is not None:
            target_item["generated_c_shards"] = shard_report.get("summary", {})
            shard_reports[target.name] = shard_report
        target_reports.append(target_item)
    build_report = {
        "kind": "ouro.bootstrap-c-build-report.v3",
        "compiled": compiled,
        "linked": linked,
        "compile_hits": len(compile_reports) - compiled,
        "compile_misses": compiled,
        "link_hits": len(link_reports) - linked,
        "link_misses": linked,
        "sources": sorted(compile_reports, key=lambda r: str(r.get("source"))),
        "links": link_reports,
        "targets": target_reports,
        "generated_c_shards": shard_reports,
        "slowest_sources": sorted(
            (
                {
                    "source": r.get("source"),
                    "label": r.get("label"),
                    "elapsed_s": r.get("elapsed_s", 0),
                    "cache": r.get("cache"),
                }
                for r in compile_reports
            ),
            key=lambda r: float(r.get("elapsed_s") or 0),
            reverse=True,
        )[:8],
        "jobs": jobs,
    }
    write_json_atomic(out_dir / "build-report.json", build_report)
    log(cfg, f"BOOTSTRAP: OK out={rel(out_dir)} compiled={compiled} linked={linked} jobs={jobs}")
    return {"compiled": compiled, "linked": linked}

def configured_env(cfg: ResolvedConfig) -> Dict[str, str]:
    env = os.environ.copy()
    env["OURO_ROOT"] = str(ROOT)
    env["OURO_BUILD_DIR"] = str(cfg.path("build_dir"))
    env["OURO_C_BUILD_DIR"] = str(cfg.path("c_build_dir"))
    env["OURO_CACHE_DIR"] = str(cfg.path("cache_dir"))
    env["OURO_CACHE"] = "1" if cfg.get_bool("cache_enabled") else "0"
    env["OURO_JOBS"] = str(jobs_value(cfg))
    env["CC"] = choose_cc(cfg)
    env["PYTHON"] = sys.executable
    return env


def run_build(args: argparse.Namespace) -> None:
    import bootstrap_compiler

    cfg = load_config(args)
    start = time.perf_counter()
    try:
        with cache_build_access(cfg):
            bootstrap_compiler.ensure_current_compiler(cfg, sys.modules[__name__], ROOT,
                                                      compact_sources=getattr(args, "compact_sources", False))
    except (OSError, RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error
    trim_cache(cfg)
    elapsed = time.perf_counter() - start
    log(cfg, f"BUILD: OK elapsed={elapsed:.3f}s")


def run_rebuild(args: argparse.Namespace) -> None:
    cfg = load_config(args)
    cdir = cfg.delete_path("c_build_dir")
    if cdir.exists():
        shutil.rmtree(cdir)
    log(cfg, f"REBUILD: removed {rel(cdir)}; cache kept at {rel(cfg.path('cache_dir'))}")
    run_build(args)


def run_clean(args: argparse.Namespace) -> None:
    cfg = load_config(args)
    build_dir = cfg.delete_path("build_dir")
    if build_dir.exists():
        shutil.rmtree(build_dir)
        log(cfg, f"CLEAN: removed {rel(build_dir)}")
    else:
        log(cfg, f"CLEAN: already clean {rel(build_dir)}")
    log(cfg, f"CLEAN: cache kept at {rel(cfg.path('cache_dir'))}; use 'cache clean' to remove it")


def dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for p in path.rglob("*"):
        try:
            if p.is_file() or p.is_symlink():
                total += p.stat().st_size
        except FileNotFoundError:
            pass
    return total


def cache_status(args: argparse.Namespace) -> None:
    cfg = load_config(args)
    cache = cfg.path("cache_dir")
    data = {
        "enabled": cfg.get_bool("cache_enabled"),
        "cache_dir": str(cache),
        "bytes": dir_size(cache),
        "policy": cfg.values["cache_cleanup_policy"],
        "max_bytes": cfg.get_int("cache_size_mb") * 1024 * 1024,
        "ccache_available": shutil.which("ccache") is not None,
        "selfhost_module_cache": {
            "direct_artifacts": len(list((cache / "selfhost-modules" / "direct").glob("*.json"))) if (cache / "selfhost-modules" / "direct").exists() else 0,
            "closure_artifacts": len(list((cache / "selfhost-modules" / "closure").glob("*.json"))) if (cache / "selfhost-modules" / "closure").exists() else 0,
            "bytes": dir_size(cache / "selfhost-modules"),
        },
    }
    print(json.dumps(data, indent=2, sort_keys=True))
    if shutil.which("ccache") and (cache / "ccache").exists():
        env = os.environ.copy()
        env["CCACHE_DIR"] = str(cache / "ccache")
        subprocess.run(["ccache", "-s"], env=env)


def _lock_windows_cache(file: BinaryIO, *, exclusive: bool, wait: bool) -> bool:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class Overlapped(ctypes.Structure):
        _fields_ = [("internal", ctypes.c_size_t), ("internal_high", ctypes.c_size_t),
                    ("offset", wintypes.DWORD), ("offset_high", wintypes.DWORD),
                    ("event", wintypes.HANDLE)]

    lock_file = ctypes.WinDLL("kernel32", use_last_error=True).LockFileEx
    lock_file.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                          wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped))
    lock_file.restype = wintypes.BOOL
    exclusive_flag = 2
    fail_immediately_flag = 1
    flags = (exclusive_flag if exclusive else 0) | (0 if wait else fail_immediately_flag)
    if lock_file(msvcrt.get_osfhandle(file.fileno()), flags, 0, 1, 0, ctypes.byref(Overlapped())):
        return True
    error = ctypes.get_last_error()
    lock_violation = 33
    if not wait and error == lock_violation:
        return False
    raise ctypes.WinError(error)


@contextmanager
def cache_access(root: Path, *, exclusive: bool = False, wait: bool = True,
                 lock_suffix: str = ".lock", resolve_target: bool = True,
                 lock_group: set[tuple[int, int]] | None = None) -> Iterator[bool]:
    # The lock must survive deletion of the cache it protects.
    # Output locks may protect a directory entry that publication replaces.
    root = root.resolve() if resolve_target else root.parent.resolve() / root.name
    lock_path = root.with_name(f".{root.name}{lock_suffix}")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock:
        identity = None
        if lock_group is not None:
            # Different names can open the same lock file on a case-insensitive volume.
            file_info = os.fstat(lock.fileno())
            identity = (file_info.st_dev, file_info.st_ino)
            if identity in lock_group:
                raise ValueError(f"conflicting tool output lock: {lock_path}")
            lock_group.add(identity)
        try:
            if os.name == "nt":
                acquired = _lock_windows_cache(lock, exclusive=exclusive, wait=wait)
            else:
                import fcntl

                mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
                if not wait:
                    mode |= fcntl.LOCK_NB
                try:
                    fcntl.flock(lock, mode)
                    acquired = True
                except BlockingIOError:
                    if wait:
                        raise
                    acquired = False
            yield acquired
        finally:
            if lock_group is not None and identity is not None:
                lock_group.remove(identity)


def cache_build_access(cfg: ResolvedConfig):
    if cfg.get_bool("cache_enabled"):
        return cache_access(cfg.path("cache_dir"))
    return nullcontext()


def cache_clean(args: argparse.Namespace) -> None:
    cfg = load_config(args)
    cache = cfg.delete_path("cache_dir")
    with cache_access(cache, exclusive=True):
        if cache.exists():
            shutil.rmtree(cache)
            log(cfg, f"CACHE: removed {rel(cache)}")
        else:
            log(cfg, f"CACHE: already clean {rel(cache)}")


def trim_cache(cfg: ResolvedConfig) -> None:
    if not cfg.get_bool("cache_enabled"):
        return
    if str(cfg.values["cache_cleanup_policy"]) != "lru":
        return
    root = cfg.delete_path("cache_dir")
    limit = cfg.get_int("cache_size_mb") * 1024 * 1024
    if limit <= 0 or not root.exists():
        return
    with cache_access(root, exclusive=True, wait=False) as acquired:
        if not acquired:
            return
        files: List[Tuple[float, Path, int]] = []
        total = 0
        for p in root.rglob("*"):
            try:
                try:
                    st = p.stat()
                except (OSError, ValueError):
                    st = None
                if st is None:
                    # Let pathlib decide which lookup errors to ignore.
                    if not (p.is_file() or p.is_symlink()):
                        continue
                    st = p.stat()
                elif not stat.S_ISREG(st.st_mode) and not p.is_symlink():
                    continue
                total += st.st_size
                files.append((st.st_atime, p, st.st_size))
            except FileNotFoundError:
                continue
        if total <= limit:
            return
        for _, p, size in sorted(files):
            try:
                p.unlink()
                total -= size
            except FileNotFoundError:
                pass
            except PermissionError as error:
                print(f"CACHE: cannot evict {rel(p)}: {error}", file=sys.stderr)
            if total <= limit:
                break


def config_show(args: argparse.Namespace) -> None:
    cfg = load_config(args)
    data = {k: {"value": cfg.values[k], "source": cfg.sources[k]} for k in sorted(cfg.values)}
    if getattr(args, "shell", False):
        env = configured_env(cfg)
        for k in sorted(env):
            if k.startswith("OURO_") or k == "CC":
                print(f"export {k}={shlex.quote(env[k])}")
        return
    print(json.dumps(data, indent=2, sort_keys=True))


def add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", type=Path, help="project config path (default: Ouro.seal)")
    p.add_argument("--profile", choices=["dev", "release"])
    p.add_argument("--jobs")
    p.add_argument("--cc")
    p.add_argument("--opt-level")
    p.add_argument("--build-dir")
    p.add_argument("--c-build-dir")
    p.add_argument("--cache-dir")
    cache_group = p.add_mutually_exclusive_group()
    cache_group.add_argument("--cache", dest="cache_enabled", action="store_true")
    cache_group.add_argument("--no-cache", dest="cache_enabled", action="store_false")
    p.set_defaults(cache_enabled=None)
    p.add_argument("--cache-size-mb")
    p.add_argument("--cache-cleanup-policy")
    p.add_argument("--ccache", choices=["auto", "enabled", "disabled"])
    p.add_argument("--verbosity", choices=["quiet", "normal", "verbose"])
    repro = p.add_mutually_exclusive_group()
    repro.add_argument("--reproducible", dest="reproducible", action="store_true")
    repro.add_argument("--no-reproducible", dest="reproducible", action="store_false")
    p.set_defaults(reproducible=None)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Ouro incremental build/cache/config driver")
    sub = ap.add_subparsers(dest="cmd", required=True)

    build = sub.add_parser("build", help="build the current compiler from verified bootstrap inputs")
    add_common(build)
    build.add_argument("--compact-sources", action="store_true", help="emit the final stage from a checked compact source copy")
    build.set_defaults(func=run_build)

    rebuild = sub.add_parser("rebuild", help="remove build artifacts, keep caches, then build")
    add_common(rebuild)
    rebuild.add_argument("--compact-sources", action="store_true", help="emit the final stage from a checked compact source copy")
    rebuild.set_defaults(func=run_rebuild)

    clean = sub.add_parser("clean", help="remove build directory only; caches are kept")
    add_common(clean)
    clean.set_defaults(func=run_clean)

    cache = sub.add_parser("cache", help="cache status/cleanup")
    cache_sub = cache.add_subparsers(dest="cache_cmd", required=True)
    cs = cache_sub.add_parser("status")
    add_common(cs)
    cs.set_defaults(func=cache_status)
    cc = cache_sub.add_parser("clean")
    add_common(cc)
    cc.set_defaults(func=cache_clean)

    config = sub.add_parser("config", help="resolved config")
    config_sub = config.add_subparsers(dest="config_cmd", required=True)
    show = config_sub.add_parser("show")
    add_common(show)
    show.add_argument("--shell", action="store_true", help="print shell exports for scripts")
    show.set_defaults(func=config_show)

    args = ap.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
