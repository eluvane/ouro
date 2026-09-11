#!/usr/bin/env python3
"""Ouro.seal v1: handwritten project manifest.

Not TOML and not a package-manager clone. The file is a seal of intent:
project identity, build/cache defaults, dependencies, registry, and declared
trust policy. This module parses the tiny v1 syntax used by the build driver.

Trust keys are recorded intent. They neither bypass the compiler's checks nor
establish program acceptance.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

SEAL_NAME = "Ouro.seal"
SEAL_VERSION = 1

KNOWN_BLOCKS = ("project", "build", "cache", "deps", "registry", "trust")
PROJECT_KEYS = ("name", "version", "root")
BUILD_KEY_MAP = {
    "profile": "profile",
    "jobs": "jobs",
    "cc": "cc",
    "opt": "opt_level",
    "opt_level": "opt_level",
    "out": "build_dir",
    "build_dir": "build_dir",
    "c_out": "c_build_dir",
    "c_build_dir": "c_build_dir",
    "verbosity": "verbosity",
    "reproducible": "reproducible",
    "backend": None,
}
CACHE_KEY_MAP = {
    "enabled": "cache_enabled",
    "dir": "cache_dir",
    "size": "cache_size_mb",
    "size_mb": "cache_size_mb",
    "cleanup": "cache_cleanup_policy",
    "ccache": "ccache",
}
REGISTRY_KEYS = ("source",)
TRUST_KEYS = ("compiler", "generated", "effects")

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
PKG_IDENT_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?$")
INT_RE = re.compile(r"^-?\d+$")
SIZE_RE = re.compile(r"^(\d+)mb$", re.IGNORECASE)


def _die(path: Path, lineno: int, msg: str) -> None:
    raise SystemExit(f"CONFIG: {path}:{lineno}: {msg}")


def strip_comment(line: str) -> str:
    """Cut `#` or `--` comments that are outside quoted strings. No escapes."""
    in_quote = ""
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch in {'"', "'"}:
            if not in_quote:
                in_quote = ch
            elif in_quote == ch:
                in_quote = ""
            i += 1
            continue
        if not in_quote:
            if ch == "#":
                return line[:i]
            if ch == "-" and i + 1 < n and line[i + 1] == "-":
                return line[:i]
        i += 1
    return line


def parse_scalar(raw: str, path: Path, lineno: int) -> object:
    s = raw.strip()
    if not s:
        _die(path, lineno, "empty value")
    if s[0] == '"' and s[-1:] == '"' and len(s) >= 2:
        inner = s[1:-1]
        if '"' in inner or "\n" in inner:
            _die(path, lineno, "string values cannot contain quotes or newlines")
        return inner
    if s in {"true", "false"}:
        return s == "true"
    if INT_RE.fullmatch(s):
        return int(s, 10)
    if SIZE_RE.fullmatch(s) or IDENT_RE.fullmatch(s):
        return s
    _die(path, lineno, f"unquoted value {s!r} is not a bool, integer, size, or ident")
    return s


def parse_seal_text(text: str, path: Path) -> Tuple[int, Dict[str, Dict[str, object]]]:
    """Return (format version, block -> key -> value). Missing file is not an error."""
    blocks: Dict[str, Dict[str, object]] = {}
    version: Optional[int] = None
    current = ""
    for lineno, raw_line in enumerate(text.splitlines(), 1):
        s = strip_comment(raw_line).strip()
        if not s:
            continue
        if version is None:
            parts = s.split()
            if len(parts) != 2 or parts[0] != "seal":
                _die(path, lineno, "first line must be `seal 1`")
            try:
                version = int(parts[1], 10)
            except ValueError:
                _die(path, lineno, "seal version must be an integer")
            if version != SEAL_VERSION:
                _die(path, lineno, f"unsupported seal version {version}")
            continue
        if current:
            if s == "}":
                current = ""
                continue
            if "=" not in s:
                _die(path, lineno, f"expected key = value inside `{current}`")
            key, raw = s.split("=", 1)
            key = key.strip()
            if not IDENT_RE.fullmatch(key) and not (current == "deps" and PKG_IDENT_RE.fullmatch(key)):
                _die(path, lineno, f"bad key {key!r}")
            if key in blocks[current]:
                _die(path, lineno, f"duplicate key {current}.{key}")
            blocks[current][key] = parse_scalar(raw, path, lineno)
            continue
        if s.endswith("{"):
            name = s[:-1].strip()
            if name not in KNOWN_BLOCKS:
                _die(path, lineno, f"unknown block {name!r}")
            if name in blocks:
                _die(path, lineno, f"duplicate block {name}")
            current = name
            blocks[name] = {}
            continue
        _die(path, lineno, "expected `block {` or `}`")
    if version is None:
        _die(path, 1, "missing `seal 1` header")
    if current:
        _die(path, lineno, f"unclosed block `{current}`")
    _validate_blocks(path, blocks)
    return version, blocks


def _as_str(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _validate_blocks(path: Path, blocks: Mapping[str, Mapping[str, object]]) -> None:
    if "project" in blocks:
        for key in blocks["project"]:
            if key not in PROJECT_KEYS:
                raise SystemExit(f"CONFIG: {path}: unknown project.{key}")
    if "build" in blocks:
        build = blocks["build"]
        for key in build:
            if key not in BUILD_KEY_MAP:
                raise SystemExit(f"CONFIG: {path}: unknown build.{key}")
        backend = build.get("backend")
        if backend is not None and _as_str(backend) != "c":
            raise SystemExit(f"CONFIG: {path}: build.backend must be \"c\"")
    if "cache" in blocks:
        for key in blocks["cache"]:
            if key not in CACHE_KEY_MAP:
                raise SystemExit(f"CONFIG: {path}: unknown cache.{key}")
    if "registry" in blocks:
        for key in blocks["registry"]:
            if key not in REGISTRY_KEYS:
                raise SystemExit(f"CONFIG: {path}: unknown registry.{key}")
    if "trust" in blocks:
        for key in blocks["trust"]:
            if key not in TRUST_KEYS:
                raise SystemExit(f"CONFIG: {path}: unknown trust.{key}")
    if "deps" in blocks:
        for key in blocks["deps"]:
            if not PKG_IDENT_RE.fullmatch(key):
                raise SystemExit(f"CONFIG: {path}: bad dependency name {key!r}")


def cache_size_mb(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("cache size cannot be a boolean")
    if isinstance(value, int):
        return value
    s = str(value).strip()
    m = SIZE_RE.fullmatch(s)
    if m:
        return int(m.group(1), 10)
    if INT_RE.fullmatch(s):
        return int(s, 10)
    raise ValueError(f"cache size must be an integer or <n>mb, got {value!r}")


def flatten_build_keys(blocks: Mapping[str, Mapping[str, object]]) -> Dict[str, object]:
    """Map build/cache fields onto the build-driver key set."""
    data: Dict[str, object] = {}
    build = blocks.get("build", {})
    for src, dest in BUILD_KEY_MAP.items():
        if dest is None or src not in build:
            continue
        data[dest] = build[src]
    cache = blocks.get("cache", {})
    for src, dest in CACHE_KEY_MAP.items():
        if src not in cache:
            continue
        value = cache[src]
        if dest == "cache_size_mb":
            value = cache_size_mb(value)
        data[dest] = value
    return data


def load_build_keys(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    _version, blocks = parse_seal_text(path.read_text(encoding="utf-8"), path)
    return flatten_build_keys(blocks)


def load_project_version(path: Path) -> str:
    _version, blocks = parse_seal_text(path.read_text(encoding="utf-8"), path)
    value = blocks.get("project", {}).get("version")
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"CONFIG: {path}: project.version is required")
    return value.strip()


def self_check() -> None:
    sample = """seal 1

project {
  name = "app"
  version = "0.1.0"
}

build {
  profile = "dev"
  jobs = 10
  opt = "O1"
  out = "_build"
  c_out = "_build/c"
  reproducible = false
}

cache {
  enabled = true
  size = "2048mb"
}

deps {
  greet = "^0.1.0"
}

trust {
  compiler = "required"
}
"""
    version, blocks = parse_seal_text(sample, Path("Ouro.seal"))
    assert version == 1
    flat = flatten_build_keys(blocks)
    assert flat["profile"] == "dev"
    assert flat["jobs"] == 10
    assert flat["opt_level"] == "O1"
    assert flat["build_dir"] == "_build"
    assert flat["c_build_dir"] == "_build/c"
    assert flat["reproducible"] is False
    assert flat["cache_enabled"] is True
    assert flat["cache_size_mb"] == 2048
    assert blocks["deps"]["greet"] == "^0.1.0"
    assert blocks["project"]["version"] == "0.1.0"
    assert blocks["trust"]["compiler"] == "required"
