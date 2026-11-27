#!/usr/bin/env python3
"""Deterministic split-frontend regeneration with cache/report support.

This is an operational build helper only. It invokes the existing Ouro seed and
`pack_frontend.py`; it does not reinterpret or change language semantics.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

import pack_frontend as packer
import compact_source

from local_scheduler import MEMORY_ENV, available_memory_mib, bounded_jobs
from repo_support import read_required_text
from repo_support import hash_json, Timer
from repo_support import bool_env
from scoped_host_export_consumers import current_packed_scoped_aliases, current_packed_scoped_original
from scoped_host_exports import ScopedExportIndex
from repo_support import (
    bind_relative_path,
    configure_native_stack,
    decode_source_text,
    memory_aware_jobs,
    sha256_bytes,
    sha256_file,
    write_json_atomic,
)

ROOT = Path(__file__).resolve().parents[1]


def _ouro1_python_script(ouro1: Path) -> bool:
    if not ouro1.is_file():
        return False
    if ouro1.suffix.lower() == ".py":
        return True
    try:
        with ouro1.open("rb") as handle:
            head = handle.read(80)
    except OSError:
        return False
    line = head.split(b"\n", 1)[0].lower()
    return line.startswith(b"#!") and b"python" in line


def ouro1_cmd(ouro1: Path) -> list[str]:
    # Cache/regen suites pass a Python fake-ouro1 (sometimes copied to
    # `_build/c/ouro1` with no suffix). Windows cannot CreateProcess a shebang.
    if _ouro1_python_script(ouro1):
        return [sys.executable, str(ouro1)]
    return [str(ouro1)]


def ouro1_usable(ouro1: Path) -> bool:
    if not ouro1.is_file():
        return False
    if _ouro1_python_script(ouro1):
        return True
    return bool(os.access(ouro1, os.X_OK))


rel = bind_relative_path(ROOT, resolve=False)

# The host module cache reuses generated work. The compiler owns acceptance.
import selfhost_module_cache as SMC  # noqa: E402

# tag, module suffix, root source, work filename.  Keep tag order identical to
# the packer call order used by the historical shell script.
FRONTEND_TUS: Tuple[Tuple[str, str, str, str], ...] = (
    ("lx", "_lx", "compiler/lexer.ouro", "lx.c"),
    ("pa", "_pa", "compiler/parse_a.ouro", "pa.c"),
    ("pb", "_pb", "compiler/parse_b.ouro", "pb.c"),
    ("pf", "_pf", "compiler/parser_file.ouro", "pf.c"),
    ("ds", "_ds", "compiler/desugar_match.ouro", "ds.c"),
    ("ir", "_ir", "compiler/import_resolve.ouro", "ir.c"),
    ("lr", "_lr", "compiler/lower_rewrite.ouro", "lr.c"),
    ("lo", "_lo", "compiler/lower.ouro", "lo.c"),
    ("el", "_el", "compiler/elab.ouro", "el.c"),
    ("co", "_co", "compiler/compiler.ouro", "co.c"),
    ("fc", "_fc", "compiler/file_elab.ouro", "fc.c"),
    ("pi", "_pi", "compiler/preprocess_import.ouro", "pi.c"),
    ("pr", "_pr", "compiler/preprocess_record.ouro", "pr.c"),
    ("pl", "_pl", "compiler/pipeline.ouro", "pl.c"),
)


LOWER_CTOR_LOOKUP_TU = ("lo", "_lo", "compiler/lower.ouro")
PACKED_ALIAS_TOOLS = ("scripts/scoped_host_exports.py", "scripts/scoped_host_export_routes.py",
                      "scripts/scoped_host_export_consumers.py", "scripts/structural_quality_legacy.py")
LOWER_CTOR_LOOKUP_SOURCE_SHAPES = (
    ("compiler/lower_env.ouro", r"(?m)^\s*def\s+ctor_nameId\b[\s\S]*?;", """
def ctor_nameId (c : CtorInfo) : Nat :=
    match c with
    | MkCtorInfo n _ _ _ _ _ => n
    end;
"""),
    ("compiler/lower_env.ouro", r"(?m)^\s*def\s+lookup_ctor\b[\s\S]*?;", """
def lookup_ctor (nameId : Nat) : List CtorInfo -> Maybe CtorInfo :=
    fix lookup_ctor (cs : List CtorInfo) : Maybe CtorInfo :=
      match cs with
      | Nil => Nothing CtorInfo
      | Cons c cs' =>
          match eqNat(ctor_nameId c, nameId) with
          | True => Just CtorInfo c
          | False => lookup_ctor cs'
          end
      end;
"""),
    ("compiler/pipeline_abi.ouro", r"(?m)^\s*inductive\s+CtorInfo\b[\s\S]*?;", """
inductive CtorInfo : Type :=
  | MkCtorInfo : Nat -> Nat -> Nat -> Nat -> Nat -> Nat -> CtorInfo;
"""),
)


def lower_ctor_lookup_capability(text: str) -> bool:
    name = "ouro_wrap_lower_ctor_lookup"
    if name not in text:
        return False
    definition = ("ouro_v *ouro_wrap_lower_ctor_lookup(ouro_v *raw)\n{\n"
                  "\treturn ouro_clos(lower_ctor_lookup_name, ouro_cons(raw, 0));\n}")
    boundary = text.find("#ifndef OURO_FE_FLAT_EXPORTS")
    if text.count(name) != 1 or text.count(definition) != 1 or (
            boundary < 0 or text.index(definition) >= boundary):
        raise RuntimeError("malformed, duplicate or conditional lower ctor lookup runtime capability")
    return True


def lower_ctor_lookup_contract(digests: Mapping[str, "FileDigest"]) -> dict:
    runtime = ROOT / "runtime/frontend_link.c"
    current = digests.get("frontend_runtime")
    runtime_text = _read_bound_text(runtime, current, "selected lower ctor lookup runtime input changed or is missing",
                                    "frontend runtime")
    available = lower_ctor_lookup_capability(runtime_text)
    sources = []
    if available:
        compacted = {}
        for path, pattern, expected in LOWER_CTOR_LOOKUP_SOURCE_SHAPES:
            if path not in compacted:
                raw = _read_bound_bytes(ROOT / path, digests.get(path),
                                        "lower ctor lookup source input changed or is missing: " + path)
                compacted[path] = compact_source.compact_source(raw).decode("utf-8")
                sources.append(asdict(digests[path]))
            matches = re.findall(pattern, compacted[path])
            def tokens(value):
                return re.findall(r"[A-Za-z_][A-Za-z0-9_']*|:=|->|[^\s]", value)
            if len(matches) != 1 or tokens(matches[0]) != tokens(expected):
                raise RuntimeError("lower ctor lookup source shape changed: " + path)
    return {"capability": available, "runtime": asdict(current), "sources": sources}


def lower_ctor_lookup_binding(tag: str, mod: str, root: str, units: Sequence[str],
                              digests: Mapping[str, "FileDigest"]) -> dict:
    contract = lower_ctor_lookup_contract(digests)
    selected = (tag, mod, root) == LOWER_CTOR_LOOKUP_TU
    if contract["capability"]:
        if not selected and (tag == LOWER_CTOR_LOOKUP_TU[0]
                             or mod == LOWER_CTOR_LOOKUP_TU[1] or root == LOWER_CTOR_LOOKUP_TU[2]):
            raise RuntimeError("lower ctor lookup translation-unit route changed")
        if selected and (len(units) != len(set(units)) or not units or units[-1] != root
                         or any(units.count(path) != 1 for path, _pattern, _expected
                                in LOWER_CTOR_LOOKUP_SOURCE_SHAPES)):
            raise RuntimeError("lower ctor lookup canonical source closure changed")
    return {**contract, "selected": selected and contract["capability"]}


def module_lookup_capability(text: str) -> bool:
    name = "ouro_wrap_module_lookup"
    if name not in text:
        return False
    definition = ("ouro_v *ouro_wrap_module_lookup(ouro_v *raw)\n{\n"
                  "\treturn ouro_clos(module_lookup_name, ouro_cons(raw, 0));\n}")
    boundary = text.find("#ifndef OURO_FE_FLAT_EXPORTS")
    if text.count(name) != 1 or text.count(definition) != 1 or (
            boundary < 0 or text.index(definition) >= boundary):
        raise RuntimeError("malformed, duplicate or conditional module lookup runtime capability")
    return True


def module_lookup_contract(digests: Mapping[str, "FileDigest"], *, token_cache=None) -> dict:
    runtime = ROOT / "runtime/frontend_link.c"
    current = digests.get("frontend_runtime")
    runtime_text = _read_bound_text(runtime, current, "selected module lookup runtime input changed or is missing",
                                    "frontend runtime")
    available = module_lookup_capability(runtime_text)
    sources = {}
    helpers = []
    if available:
        for path in ("scripts/scoped_host_exports.py", "scripts/structural_quality_legacy.py"):
            helper = digests.get(path)
            if helper is None or helper != digest(ROOT / path):
                raise RuntimeError("module lookup installer input changed or is missing: " + path)
            helpers.append(asdict(helper))
        for path in packer.MODULE_LOOKUP_SOURCE_PATHS:
            sources[path] = _read_bound_text(ROOT / path, digests.get(path),
                                             "module lookup source input changed or is missing: " + path,
                                             "module lookup source")
        packer.module_lookup_source_contract(sources, token_cache=token_cache)
    return {"capability": available, "runtime": asdict(current), "helpers": helpers,
            "sources": [asdict(digests[path]) for path in sources]}


def _matches_binding_units(root: str, units: Sequence[str], required: Sequence[str],
                           parse_bytes: ImportBytesParser | None) -> bool:
    expected = list(units)
    current = (collect_units(root) if parse_bytes is None
               else collect_units_many([root], parse_bytes=parse_bytes)[root])
    return expected == current and all(units.count(path) == 1 for path in required)


def module_lookup_binding(root: str, units: Sequence[str], digests: Mapping[str, "FileDigest"], *,
                          parse_bytes: ImportBytesParser | None = None, token_cache=None) -> dict:
    contract = module_lookup_contract(digests, token_cache=token_cache)
    selected = contract["capability"] and packer.MODULE_LOOKUP_OWNER in units
    if selected and not _matches_binding_units(root, units, packer.MODULE_LOOKUP_SOURCE_PATHS, parse_bytes):
        raise RuntimeError("module lookup canonical source closure changed")
    return {**contract, "selected": selected}


def lower_local_lookup_contract(digests: Mapping[str, "FileDigest"], *, token_cache=None) -> dict:
    runtime = ROOT / "runtime/frontend_link.c"
    current = digests.get("frontend_runtime")
    runtime_text = _read_bound_text(runtime, current, "selected lower local lookup runtime input changed or is missing",
                                    "frontend runtime")
    available = module_lookup_capability(runtime_text)
    sources, helpers = {}, []
    if available:
        for path in ("scripts/scoped_host_exports.py", "scripts/structural_quality_legacy.py"):
            helper = digests.get(path)
            if helper is None or helper != digest(ROOT / path):
                raise RuntimeError("lower local lookup installer input changed or is missing: " + path)
            helpers.append(asdict(helper))
        for path in packer.LOWER_LOCAL_LOOKUP_SOURCE_PATHS:
            sources[path] = _read_bound_text(ROOT / path, digests.get(path),
                                             "lower local lookup source input changed or is missing: " + path,
                                             "lower local lookup source")
        packer.lower_local_lookup_source_contract(sources, token_cache=token_cache)
    return {"capability": available, "runtime": asdict(current), "helpers": helpers,
            "sources": [asdict(digests[path]) for path in sources]}


def lower_local_lookup_binding(root: str, units: Sequence[str], digests: Mapping[str, "FileDigest"], *,
                               parse_bytes: ImportBytesParser | None = None, token_cache=None) -> dict:
    contract = lower_local_lookup_contract(digests, token_cache=token_cache)
    selected = contract["capability"] and packer.LOWER_LOCAL_LOOKUP_OWNER in units
    if selected and not _matches_binding_units(root, units, packer.LOWER_LOCAL_LOOKUP_SOURCE_PATHS, parse_bytes):
        raise RuntimeError("lower local lookup canonical source closure changed")
    return {**contract, "selected": selected}


def elem_scope_capability(text: str) -> bool:
    name = "ouro_wrap_elem_scope"
    if name not in text:
        return False
    definition = ("ouro_v *ouro_wrap_elem_scope(ouro_v *raw)\n{\n"
                  "\treturn ouro_wrap_module_pure_scope(raw, 3);\n}")
    boundary = text.find("#ifndef OURO_FE_FLAT_EXPORTS")
    if text.count(name) != 1 or text.count(definition) != 1 or (
            boundary < 0 or text.index(definition) >= boundary):
        raise RuntimeError("malformed, duplicate or conditional elem scope runtime capability")
    return True


def elem_scope_contract(digests: Mapping[str, "FileDigest"], *, token_cache=None) -> dict:
    runtime = ROOT / "runtime/frontend_link.c"
    current = digests.get("frontend_runtime")
    runtime_text = _read_bound_text(runtime, current, "selected elem scope runtime input changed or is missing",
                                    "frontend runtime")
    available = elem_scope_capability(runtime_text)
    sources, helpers = {}, []
    if available:
        for path in ("scripts/scoped_host_exports.py", "scripts/structural_quality_legacy.py"):
            helper = digests.get(path)
            if helper is None or helper != digest(ROOT / path):
                raise RuntimeError("elem scope installer input changed or is missing: " + path)
            helpers.append(asdict(helper))
        for path in packer.ELEM_SOURCE_PATHS:
            sources[path] = _read_bound_text(ROOT / path, digests.get(path),
                                             "elem scope source input changed or is missing: " + path,
                                             "elem scope source")
        packer.elem_source_contract(sources, token_cache=token_cache)
    return {"capability": available, "runtime": asdict(current), "helpers": helpers,
            "sources": [asdict(digests[path]) for path in sources], "value_arity": packer.ELEM_VALUE_ARITY}


def elem_scope_binding(root: str, units: Sequence[str], digests: Mapping[str, "FileDigest"], *,
                       parse_bytes: ImportBytesParser | None = None, token_cache=None) -> dict:
    contract = elem_scope_contract(digests, token_cache=token_cache)
    selected = contract["capability"] and packer.ELEM_OWNER in units
    if selected and not _matches_binding_units(root, units, packer.ELEM_SOURCE_PATHS, parse_bytes):
        raise RuntimeError("elem scope canonical source closure changed")
    return {**contract, "selected": selected}


def source_name_compare_capability(text: str) -> bool:
    name = "ouro_wrap_source_name_compare_scope"
    if name not in text:
        return False
    definition = ("ouro_v *ouro_wrap_source_name_compare_scope(ouro_v *raw)\n{\n"
                  "\treturn ouro_wrap_module_pure_scope(raw, 2);\n}")
    boundary = text.find("#ifndef OURO_FE_FLAT_EXPORTS")
    if text.count(name) != 1 or text.count(definition) != 1 or (
            boundary < 0 or text.index(definition) >= boundary):
        raise RuntimeError("malformed, duplicate or conditional source name compare scope runtime capability")
    return True


def source_name_compare_contract(digests: Mapping[str, "FileDigest"], *, token_cache=None) -> dict:
    runtime = ROOT / "runtime/frontend_link.c"
    current = digests.get("frontend_runtime")
    runtime_text = _read_bound_text(runtime, current,
                                    "selected source name compare scope runtime input changed or is missing",
                                    "frontend runtime")
    available = source_name_compare_capability(runtime_text)
    sources, helpers = {}, []
    if available:
        for path in ("scripts/scoped_host_exports.py", "scripts/structural_quality_legacy.py"):
            helper = digests.get(path)
            if helper is None or helper != digest(ROOT / path):
                raise RuntimeError("source name compare scope installer input changed or is missing: " + path)
            helpers.append(asdict(helper))
        for path in packer.SOURCE_NAME_COMPARE_SOURCE_PATHS:
            sources[path] = _read_bound_text(ROOT / path, digests.get(path),
                                             "source name compare scope source input changed or is missing: " + path,
                                             "source name compare scope source")
        packer.source_name_compare_source_contract(sources, token_cache=token_cache)
    return {"capability": available, "runtime": asdict(current), "helpers": helpers,
            "sources": [asdict(digests[path]) for path in sources], "value_arity": 2}


def source_name_compare_binding(root: str, units: Sequence[str], digests: Mapping[str, "FileDigest"], *,
                                parse_bytes: ImportBytesParser | None = None, token_cache=None) -> dict:
    contract = source_name_compare_contract(digests, token_cache=token_cache)
    selected = contract["capability"] and packer.SOURCE_NAME_COMPARE_OWNER in units
    if selected and not _matches_binding_units(root, units, packer.SOURCE_NAME_COMPARE_SOURCE_PATHS, parse_bytes):
        raise RuntimeError("source name compare scope canonical source closure changed")
    return {**contract, "selected": selected}


def prelude_arithmetic_binding(root: str, units: Sequence[str], digests: Mapping[str, "FileDigest"], *,
                              parse_bytes: ImportBytesParser | None = None, token_cache=None) -> dict:
    if not any(owner in units for _name, owner in packer.PRELUDE_ARITHMETIC_ROUTES):
        return {"selected": False}
    source_paths = packer.prelude_arithmetic_source_paths(units)
    if not _matches_binding_units(root, units, source_paths, parse_bytes):
        raise RuntimeError("prelude arithmetic canonical source closure changed")
    names = (*source_paths,
             "scripts/scoped_host_exports.py", "scripts/structural_quality_legacy.py")
    source_bytes = {}
    for name in names:
        path = ROOT / name
        changed = "prelude arithmetic input changed or is missing: " + name
        if name not in digests or not path.is_file():
            raise RuntimeError(changed)
        if name in source_paths:
            source_bytes[name] = _read_bound_bytes(path, digests[name], changed)
        elif digests[name] != digest(path):
            raise RuntimeError(changed)
    sources = {name: _decode_bound_text(ROOT / name, data, "prelude arithmetic source")
               for name, data in source_bytes.items()}
    packer.prelude_arithmetic_source_contract(sources, token_cache=token_cache)
    return {"selected": True, "inputs": [asdict(digests[name]) for name in names],
            "prelude_list_length": {"owner": packer.PRELUDE_LIST_LENGTH_ROUTE[1],
                                    "value_arity": packer.PRELUDE_LIST_LENGTH_ROUTE[2]},
            "prelude_list_append": {"owner": packer.PRELUDE_LIST_APPEND_ROUTE[1],
                                    "value_arity": packer.PRELUDE_LIST_APPEND_ROUTE[2]}}


@dataclass(frozen=True)
class FileDigest:
    path: str
    sha256: str
    bytes: int


@dataclass
class TuReport:
    tag: str
    module: str
    root: str
    deps: int
    key: str
    cache: str
    bytes: int
    elapsed_s: float


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw, 10)
    except ValueError:
        return default
    return value if value > 0 else default


def jobs_from_env() -> int:
    raw = os.environ.get("OURO_FRONTEND_JOBS") or os.environ.get("OURO_JOBS") or "10"
    if raw == "auto":
        raw = str(os.cpu_count() or 1)
    try:
        n = int(raw, 10)
    except ValueError:
        n = 10
    return bounded_jobs(max(1, n))


ImportBytesParser = SMC.ImportBytesParser
SourceBytesReader = Callable[[Path], bytes]


def import_targets(path: str, *, parse_bytes: Optional[ImportBytesParser] = None,
                   source_root: Path | None = None, read_source: SourceBytesReader | None = None) -> List[str]:
    p = (ROOT if source_root is None else source_root) / path
    if not p.is_file():
        raise SystemExit(f"FRONTEND_REGEN: FAIL missing {path}")
    if parse_bytes is not None or read_source is not None:
        try:
            data = p.read_bytes() if read_source is None else read_source(p)
            return (parse_bytes(data, path) if parse_bytes is not None
                    else SMC.quoted_import_targets(decode_source_text(data), path))
        except (OSError, UnicodeError) as exc:
            raise SystemExit(f"FRONTEND_REGEN: FAIL unreadable {p}: {exc}") from exc
    return SMC.quoted_import_targets(read_required_text(p, "FRONTEND_REGEN"), path)


def iter_unit_closures(
    roots: Sequence[str], *, parse_bytes: Optional[ImportBytesParser] = None,
    source_root: Path | None = None, read_source: SourceBytesReader | None = None,
) -> Iterator[Tuple[str, List[str]]]:
    """Yield closures in root order with one import read per path.

    Keep adjacency in this iterator so each new preparation rereads inputs.
    Yield each closure before reading the next root so callers can reject it.
    """
    imports: Dict[str, Tuple[str, ...]] = {}
    read_options = {} if read_source is None else {"read_source": read_source}

    def read_imports(path: str) -> Tuple[str, ...]:
        if path not in imports:
            imports[path] = tuple(import_targets(path, parse_bytes=parse_bytes, source_root=source_root, **read_options))
        return imports[path]

    completed: set[str] = set()
    for root in roots:
        if root in completed:
            continue
        units = SMC.collect_units(
            root, imports=read_imports,
            normalize=lambda path: path.replace("\\", "/"),
            cycle_error=lambda norm, root=root:
                f"FRONTEND_REGEN: FAIL import cycle while collecting {root}: {norm}",
        )
        completed.add(root)
        yield root, units


def collect_units_many(roots: Sequence[str], *, parse_bytes: Optional[ImportBytesParser] = None,
                       source_root: Path | None = None,
                       read_source: SourceBytesReader | None = None) -> Dict[str, List[str]]:
    return dict(iter_unit_closures(roots, parse_bytes=parse_bytes, source_root=source_root, read_source=read_source))


def collect_units(root: str, *, parse_bytes: ImportBytesParser | None = None) -> List[str]:
    return collect_units_many([root], parse_bytes=parse_bytes)[root]


def capture_unit_inputs(roots: Sequence[str], *, parse_bytes: ImportBytesParser | None = None,
                        source_root: Path | None = None,
                        read_source: SourceBytesReader | None = None,
                        ) -> Tuple[Dict[str, List[str]], Dict[str, FileDigest]]:
    captured: Dict[str, FileDigest] = {}
    root = ROOT if source_root is None else source_root
    source_label = rel if source_root is None else bind_relative_path(root, resolve=False)

    def capture(data: bytes, path: str) -> List[str]:
        if type(parse_bytes) is SMC.CachedImportParser:
            targets, source_hash = parse_bytes.parse_and_digest(data, path)
        else:
            targets = (parse_bytes(data, path) if parse_bytes is not None
                       else SMC.quoted_import_targets(decode_source_text(data), path))
            source_hash = sha256_bytes(data)
        captured[path] = FileDigest(source_label(root / path), source_hash, len(data))
        return targets

    options = {} if source_root is None else {"source_root": source_root}
    if read_source is not None:
        options["read_source"] = read_source
    return collect_units_many(roots, parse_bytes=capture, **options), captured


def digest(path: Path) -> FileDigest:
    st = path.stat()
    return FileDigest(rel(path), sha256_file(path), st.st_size)


def _read_bound_bytes(path: Path, expected: FileDigest | None, changed: str) -> bytes:
    if expected is None:
        raise RuntimeError(changed)
    st = path.stat()
    data = path.read_bytes()
    if expected != FileDigest(rel(path), sha256_bytes(data), st.st_size):
        raise RuntimeError(changed)
    return data


def _decode_bound_text(path: Path, data: bytes, label: str) -> str:
    try:
        return decode_source_text(data)
    except UnicodeError as exc:
        raise SystemExit(f"{label}: FAIL unreadable {path}: {exc}") from exc


def _read_bound_text(path: Path, expected: FileDigest | None, changed: str, label: str) -> str:
    return _decode_bound_text(path, _read_bound_bytes(path, expected, changed), label)


def _source_scope_contracts(digests: Mapping[str, FileDigest]) -> dict:
    token_cache = {}
    return {
        "module_lookup": module_lookup_contract(digests, token_cache=token_cache),
        "lower_local_lookup": lower_local_lookup_contract(digests, token_cache=token_cache),
        "source_name_compare_scope": source_name_compare_contract(digests, token_cache=token_cache),
        "elem_scope": elem_scope_contract(digests, token_cache=token_cache),
    }


def all_frontend_inputs(ouro1: Path, fuel: str, *, historical_bridge: bool = False,
                        parse_bytes: ImportBytesParser | None = None
                        ) -> Tuple[Dict[str, List[str]], Dict[str, FileDigest], str]:
    unit_graph, captured = capture_unit_inputs([root for _tag, _mod, root, _file in FRONTEND_TUS],
                                                parse_bytes=parse_bytes)
    paths: Dict[str, Path] = {
        "seed": ouro1,
        "frontend_regen": ROOT / "scripts/frontend_regen.py",
        "module_cache": ROOT / "scripts/selfhost_module_cache.py",
        "emit_wrapper": ROOT / "scripts/emit_frontend.sh",
        "packer": ROOT / "scripts/pack_frontend.py",
        "source_compactor": ROOT / "scripts/compact_source.py",
        "frontend_runtime": ROOT / "runtime/frontend_link.c",
    }
    paths.update({name: ROOT / name for name in PACKED_ALIAS_TOOLS})
    runtime_path = paths["frontend_runtime"]
    try:
        runtime_bytes = runtime_path.read_bytes()
        runtime_text = decode_source_text(runtime_bytes)
    except (OSError, UnicodeError) as exc:
        raise SystemExit(f"frontend runtime: FAIL unreadable {runtime_path}: {exc}") from exc
    captured["frontend_runtime"] = FileDigest(rel(runtime_path), sha256_bytes(runtime_bytes), len(runtime_bytes))
    if lower_ctor_lookup_capability(runtime_text):
        for source, _pattern, _expected in LOWER_CTOR_LOOKUP_SOURCE_SHAPES:
            paths[source] = ROOT / source
    if module_lookup_capability(runtime_text):
        for source in (*packer.MODULE_LOOKUP_SOURCE_PATHS, *packer.LOWER_LOCAL_LOOKUP_SOURCE_PATHS,
                       "scripts/scoped_host_exports.py", "scripts/structural_quality_legacy.py"):
            paths[source] = ROOT / source
    if elem_scope_capability(runtime_text):
        for name in (*packer.ELEM_SOURCE_PATHS,
                     "scripts/scoped_host_exports.py", "scripts/structural_quality_legacy.py"):
            paths[name] = ROOT / name
    if source_name_compare_capability(runtime_text):
        for source in (*packer.SOURCE_NAME_COMPARE_SOURCE_PATHS,
                       "scripts/scoped_host_exports.py", "scripts/structural_quality_legacy.py"):
            paths[source] = ROOT / source
    for _tag, _mod, root, _file in FRONTEND_TUS:
        for u in unit_graph[root]:
            paths.setdefault(u, ROOT / u)
    if any(owner in units for units in unit_graph.values()
           for _name, owner in packer.PRELUDE_ARITHMETIC_ROUTES):
        for name in ("scripts/scoped_host_exports.py", "scripts/structural_quality_legacy.py"):
            paths[name] = ROOT / name
    digests = {name: captured[name] if name in captured else digest(path)
               for name, path in sorted(paths.items())}
    signature = hash_json(
        {
            "kind": "ouro.frontend.full.v5",
            "historical_bridge": historical_bridge,
            "fuel": fuel,
            "tus": [
                {
                    "tag": tag,
                    "module": mod,
                    "root": root,
                    "units": unit_graph[root],
                }
                for tag, mod, root, _file in FRONTEND_TUS
            ],
            "digests": {k: asdict(v) for k, v in digests.items()},
            "lower_ctor_lookup": lower_ctor_lookup_binding(
                *LOWER_CTOR_LOOKUP_TU, unit_graph[LOWER_CTOR_LOOKUP_TU[2]], digests),
            **_source_scope_contracts(digests),
        }
    )
    return unit_graph, digests, signature


def _tu_key_inputs(tag: str, mod: str, root: str, units: Sequence[str], digests: Mapping[str, FileDigest], fuel: str,
                   *, historical_bridge: bool, close_exports: bool = False) -> dict:
    return {
        "kind": "ouro.frontend-tu.v5",
        "historical_bridge": historical_bridge,
        "tag": tag,
        "module": mod,
        "root": root,
        "fuel": fuel,
        "seed": asdict(digests["seed"]),
        "tool": asdict(digests["frontend_regen"]),
        "module_cache_tool": asdict(digests["module_cache"]),
        "pure_scope_installer": asdict(digests["packer"]),
        "source_compactor": asdict(digests["source_compactor"]),
        **({"packed_alias_tools": {name: asdict(digests[name]) for name in PACKED_ALIAS_TOOLS}}
           if close_exports and not historical_bridge else {}),
        "units": [asdict(digests[u]) for u in units],
        "lower_ctor_lookup": lower_ctor_lookup_binding(tag, mod, root, units, digests),
    }


def _tu_scope_bindings(root: str, units: Sequence[str], digests: Mapping[str, FileDigest], *,
                       module_lookup: dict | None = None, historical_bridge: bool,
                       parse_bytes: ImportBytesParser | None) -> dict:
    token_cache = {}
    return {
        "module_lookup": (module_lookup_binding(root, units, digests, parse_bytes=parse_bytes, token_cache=token_cache)
                          if module_lookup is None else module_lookup),
        "lower_local_lookup": lower_local_lookup_binding(root, units, digests, parse_bytes=parse_bytes,
                                                        token_cache=token_cache),
        "source_name_compare_scope": source_name_compare_binding(root, units, digests, parse_bytes=parse_bytes,
                                                                token_cache=token_cache),
        "elem_scope": elem_scope_binding(root, units, digests, parse_bytes=parse_bytes, token_cache=token_cache),
        "prelude_arithmetic": (prelude_arithmetic_binding(root, units, digests, parse_bytes=parse_bytes,
                                                         token_cache=token_cache)
                               if not historical_bridge else {"selected": False}),
    }


def tu_key(tag: str, mod: str, root: str, units: Sequence[str], digests: Mapping[str, FileDigest], fuel: str,
           *, module_lookup: dict | None = None, historical_bridge: bool = False,
           parse_bytes: ImportBytesParser | None = None) -> str:
    inputs = _tu_key_inputs(tag, mod, root, units, digests, fuel, historical_bridge=historical_bridge)
    bindings = _tu_scope_bindings(root, units, digests, module_lookup=module_lookup,
                                  historical_bridge=historical_bridge, parse_bytes=parse_bytes)
    return hash_json({**inputs, **bindings})


def _same_output_bytes(src: Path, dst: Path) -> bool:
    source, target = src.stat(), dst.stat()
    if not stat.S_ISREG(source.st_mode) or not stat.S_ISREG(target.st_mode) or source.st_size != target.st_size:
        return False
    chunk_size = 1024 * 1024
    with src.open("rb") as left, dst.open("rb") as right:
        while True:
            chunk = left.read(chunk_size)
            if chunk != right.read(chunk_size):
                return False
            if not chunk:
                return True


def install_if_changed(src: Path, dst: Path) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and _same_output_bytes(src, dst):
        src.unlink(missing_ok=True)
        return "unchanged"
    os.replace(src, dst)
    return "updated"


def copy_atomic(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + f".tmp.{os.getpid()}")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def read_manifest(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def cached_output_digest(path: Path, key: str) -> str | None:
    metadata = read_manifest(path.with_suffix(".json"))
    if (
        metadata is not None
        and metadata.get("kind") == "ouro.frontend-cache-output.v1"
        and metadata.get("input_key") == key
        and isinstance(metadata.get("output_sha256"), str)
        and path.is_file()
        and path.stat().st_size > 0
    ):
        return metadata["output_sha256"]
    return None


def cached_output_matches(path: Path, key: str) -> bool:
    expected = cached_output_digest(path, key)
    return expected is not None and sha256_file(path) == expected


def record_cached_output(path: Path, key: str) -> None:
    write_json_atomic(path.with_suffix(".json"), {
        "kind": "ouro.frontend-cache-output.v1",
        "input_key": key,
        "output_sha256": sha256_file(path),
    })


def _has_export_marker(path: Path, marker: bytes) -> bool:
    overlap = len(marker) - 1
    chunk_size = 256 * 1024
    buffer = bytearray(chunk_size + overlap)
    view = memoryview(buffer)
    kept = 0
    found = False
    with path.open("rb") as source:
        # Read through EOF so a match cannot hide a later read failure.
        while size := source.readinto(view[kept:kept + chunk_size]):
            if found:
                continue
            end = kept + size
            found = buffer.find(marker, 0, end) >= 0
            kept = min(overlap, end)
            buffer[:kept] = buffer[end - kept:end]
    return found


def emit_one(
    *,
    ouro1: Path,
    fuel: str,
    work: Path,
    cache_enabled: bool,
    tu_cache: Path,
    tag: str,
    mod: str,
    root: str,
    file_name: str,
    units: Sequence[str],
    digests: Mapping[str, FileDigest],
    historical_bridge: bool = False,
    close_exports: bool = False,
) -> TuReport:
    t = Timer()
    bindings = _tu_scope_bindings(root, units, digests, historical_bridge=historical_bridge,
                                  parse_bytes=SMC.cached_import_parser())
    inputs = _tu_key_inputs(tag, mod, root, units, digests, fuel, historical_bridge=historical_bridge,
                            close_exports=close_exports)
    key = hash_json({**inputs, **bindings})
    lookup = inputs["lower_ctor_lookup"]
    module_lookup = bindings["module_lookup"]
    local_lookup = bindings["lower_local_lookup"]
    source_name_compare = bindings["source_name_compare_scope"]
    elem = bindings["elem_scope"]
    arithmetic = bindings["prelude_arithmetic"]
    lookup_sources = ({unit: read_required_text(ROOT / unit, "module lookup source") for unit in units}
                      if module_lookup["selected"] or arithmetic["selected"] or source_name_compare["selected"]
                      or elem["selected"] or local_lookup["selected"]
                      else {})
    canonical_units = list(units)

    def has_packed_scopes(text: str, index: ScopedExportIndex) -> bool:
        return (close_exports and not historical_bridge and 'return "_ouro_m_' in text
                and bool(index.tables_for(text, mod).scoped_ordinals))

    def packed_sources() -> dict[str, str]:
        return lookup_sources or {unit: read_required_text(ROOT / unit, "packed alias source") for unit in units}

    out = work / file_name
    err = work / f"{tag}.err"
    cache_file = tu_cache / f"{mod}_{key}.c"
    tmp_out = out.with_name(out.name + f".tmp.{os.getpid()}.{tag}")
    tmp_err = err.with_name(err.name + f".tmp.{os.getpid()}.{tag}")
    for stale in (tmp_out, tmp_err):
        stale.unlink(missing_ok=True)
    expected = cached_output_digest(cache_file, key) if cache_enabled else None
    cached_bytes = cache_file.read_bytes() if expected is not None else b""
    cached_text = ""
    if expected is not None and sha256_bytes(cached_bytes) == expected:
        try:
            cached_text = decode_source_text(cached_bytes)
        except UnicodeError as exc:
            raise SystemExit(f"cached frontend unit: FAIL unreadable {cache_file}: {exc}") from exc
    if f"ouro_export_count{mod}" in cached_text:
        export_index = ScopedExportIndex()
        scoped = has_packed_scopes(cached_text, export_index)
        original = (current_packed_scoped_original(cached_text, units, canonical_units, root, packed_sources(), mod,
                                                  export_index=export_index) if scoped else cached_text)
        static_index = packer.StaticSymbolIndex(original, export_index=export_index)
        if not historical_bridge:
            packer.hook_prelude_arithmetic(original,
                                          units, canonical_units, root, lookup_sources, mod, installed=True,
                                          static_index=static_index)
        packer.hook_module_pure_scopes(
            cached_text, tuple(units), mod, installed=True,
            static_index=packer.StaticSymbolIndex(cached_text) if scoped else static_index)
        if lookup["selected"]:
            packer.hook_lower_ctor_lookup(
                original, mod, installed=True, static_index=static_index)
        if module_lookup["selected"]:
            packer.hook_module_lookup(original,
                                      units, canonical_units, root, lookup_sources, mod, installed=True,
                                      static_index=static_index)
        if local_lookup["selected"]:
            packer.hook_lower_local_lookup(original,
                                          units, canonical_units, root, lookup_sources, mod, installed=True,
                                          static_index=static_index)
        if source_name_compare["selected"]:
            packer.hook_source_name_compare_scope(original,
                units, canonical_units, root, lookup_sources, mod, installed=True, static_index=static_index)
        if elem["selected"]:
            packer.hook_elem_scope(original,
                                   units, canonical_units, root, lookup_sources, mod, installed=True,
                                   static_index=static_index)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp_out.write_bytes(cached_bytes)
        os.replace(tmp_out, out)
        err.write_text("", encoding="utf-8")
        return TuReport(tag, mod, root, len(units), key, "hit", len(cached_bytes), t.elapsed())
    del cached_bytes, cached_text
    cmd = ouro1_cmd(ouro1) + ["--module", mod, root, fuel]
    for unit in units:
        cmd.extend(["--unit", unit])
    env = dict(os.environ)
    if historical_bridge:
        env.pop("OURO_EMIT_SCOPED_ARITHMETIC", None)
    else:
        env["OURO_EMIT_SCOPED_ARITHMETIC"] = "1"
        env["WSLENV"] = (env.get("WSLENV", "") + ":OURO_EMIT_SCOPED_ARITHMETIC").lstrip(":")
    with tmp_out.open("wb") as stdout, tmp_err.open("wb") as stderr:
        p = subprocess.run(cmd, cwd=str(ROOT), env=env, stdout=stdout, stderr=stderr)
    if p.returncode != 0 or not tmp_out.is_file() or tmp_out.stat().st_size == 0:
        tail = tmp_err.read_bytes()[-1200:].decode("utf-8", errors="replace") if tmp_err.exists() else ""
        raise RuntimeError(f"emit {root} module={mod} failed status={p.returncode}\n{tail}")
    pure_scopes = {unit.replace("\\", "/") for unit in units}.intersection(packer.MODULE_PURE_SCOPE_OWNERS)
    rewrite = not historical_bridge or bool(pure_scopes) or any(
        binding["selected"] for binding in (lookup, module_lookup, local_lookup, source_name_compare, elem))
    marker = f"ouro_export_count{mod}".encode()
    raw_output = tmp_out.read_bytes() if rewrite else None
    has_export_table = _has_export_marker(tmp_out, marker) if raw_output is None else marker in raw_output
    if not has_export_table:
        raise RuntimeError(f"emit {root} module={mod} missing export table {mod}")
    if raw_output is not None:
        text = decode_source_text(raw_output, errors="strict" if historical_bridge else "replace")
        del raw_output
        export_index = ScopedExportIndex()
        scoped = has_packed_scopes(text, export_index)
        if not historical_bridge:
            text = packer.hook_prelude_arithmetic(text, units, canonical_units, root, lookup_sources, mod)
        if pure_scopes and not scoped:
            text = packer.hook_module_pure_scopes(text, tuple(units), mod)
        if lookup["selected"]:
            text = packer.hook_lower_ctor_lookup(text, mod)
        if module_lookup["selected"]:
            text = packer.hook_module_lookup(text, units, canonical_units, root, lookup_sources, mod)
        if local_lookup["selected"]:
            text = packer.hook_lower_local_lookup(text, units, canonical_units, root, lookup_sources, mod)
        if source_name_compare["selected"]:
            text = packer.hook_source_name_compare_scope(text, units, canonical_units, root, lookup_sources, mod)
        if elem["selected"]:
            text = packer.hook_elem_scope(text, units, canonical_units, root, lookup_sources, mod)
        if scoped:
            text = current_packed_scoped_aliases(text, units, canonical_units, root, packed_sources(), mod,
                                                export_index=export_index)
            if pure_scopes:
                text = packer.hook_module_pure_scopes(text, tuple(units), mod)
        tmp_out.write_text(text, encoding="utf-8")
    os.replace(tmp_out, out)
    os.replace(tmp_err, err)
    if cache_enabled:
        copy_atomic(out, cache_file)
        record_cached_output(cache_file, key)
    return TuReport(tag, mod, root, len(units), key, "miss", out.stat().st_size, t.elapsed())


def pack_key(pieces: Sequence[Tuple[str, Path]], digests: Mapping[str, FileDigest], *,
             parser_min_ordinal: int | None = None) -> str:
    piece_meta = []
    for tag, path in pieces:
        piece_meta.append({"tag": tag, "path": rel(path), "sha256": sha256_file(path), "bytes": path.stat().st_size})
    return hash_json(
        {
            "kind": "ouro.frontend-pack.v5",
            "packer": asdict(digests["packer"]),
            "source_compactor": asdict(digests["source_compactor"]),
            "pieces": piece_meta,
            "strict": True,
            "parser_min_ordinal": parser_min_ordinal,
            "lower_ctor_lookup": lower_ctor_lookup_contract(digests),
            **_source_scope_contracts(digests),
        }
    )


def run_pack(pieces: Sequence[Tuple[str, Path]], out_tmp: Path, *,
             parser_min_ordinal: int | None) -> None:
    cmd = [sys.executable, str(ROOT / "scripts/pack_frontend.py"), "--strict", "-o", str(out_tmp)]
    if parser_min_ordinal is not None:
        cmd.extend(("--parser-min-ordinal", str(parser_min_ordinal)))
    cmd.extend([f"{tag}:{path}" for tag, path in pieces])
    p = subprocess.run(cmd, cwd=str(ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if p.returncode != 0:
        raise RuntimeError(f"pack_frontend failed status={p.returncode}\n{p.stdout[-1600:]}")


def regenerate(
    *,
    ouro1: Path,
    fuel: str,
    out_c: Path,
    work: Path,
    cache_root: Path,
    cache_enabled: bool,
    report_path: Optional[Path],
    jobs: int,
    historical_bridge: bool = False,
) -> dict:
    total = Timer()
    work.mkdir(parents=True, exist_ok=True)
    # Each emitter holds a frontend arena. Use its memory estimate for the
    # scheduler budget and for host throttling when enabled.
    worker_memory_mib = env_int("OURO_FRONTEND_WORKER_MB", 1024)
    jobs = bounded_jobs(jobs)
    if MEMORY_ENV in os.environ:
        jobs = min(jobs, max(1, available_memory_mib() // worker_memory_mib))
    jobs, throttle_note = memory_aware_jobs(
        jobs,
        per_worker_mb=worker_memory_mib,
        reserve_mb=env_int("OURO_MEM_RESERVE_MB", 1024),
        enabled=bool_env(os.environ.get("OURO_MEM_AWARE_JOBS"), default=True),
    )
    if throttle_note:
        print(f"EMIT_FRONTEND: {throttle_note}")
    if cache_enabled:
        (cache_root / "gen/frontend-tu").mkdir(parents=True, exist_ok=True)
        (cache_root / "gen/frontend-pack").mkdir(parents=True, exist_ok=True)
        (cache_root / "gen/frontend-final").mkdir(parents=True, exist_ok=True)
    parse_bytes = SMC.cached_import_parser()
    unit_graph, digests, signature = all_frontend_inputs(ouro1, fuel, historical_bridge=historical_bridge,
                                                         parse_bytes=parse_bytes)
    phases: List[dict] = [
        {"name": "collect_inputs", "elapsed_s": round(total.elapsed(), 6)},
    ]
    module_timer = Timer()
    module_cache = SMC.materialize_module_artifacts(
        roots=[root for _tag, _mod, root, _file in FRONTEND_TUS],
        unit_graph=unit_graph,
        work=work / "module_artifacts",
        cache_root=cache_root,
        cache_enabled=cache_enabled,
        report_path=work / "selfhost-module-cache.json",
        label="frontend",
        seed=ouro1,
        fuel=fuel,
        parse_bytes=parse_bytes,
        tool_inputs=(
            ROOT / "scripts/frontend_regen.py",
            ROOT / "scripts/emit_frontend.sh",
            ROOT / "scripts/pack_frontend.py",
        ),
    )
    del parse_bytes
    phases.append({"name": "module_cache", "elapsed_s": round(module_timer.elapsed(), 6)})
    manifest = work / "frontend-regeneration.json"
    final_cache = cache_root / "gen/frontend-final" / f"driver_{signature}.c"
    final_meta = cache_root / "gen/frontend-final" / f"driver_{signature}.json"

    affected_tus = []
    changed_modules = set(module_cache.get("summary", {}).get("direct_changed_modules", []))
    closure_changed_modules = set(module_cache.get("summary", {}).get("closure_changed_modules", []))
    for tag, mod, root, _file in FRONTEND_TUS:
        closure = unit_graph.get(root, [])
        direct_hits = [u for u in closure if u in changed_modules]
        closure_hits = [u for u in closure if u in closure_changed_modules]
        if direct_hits or closure_hits:
            affected_tus.append({"tag": tag, "module": mod, "root": root, "direct_changed_modules": direct_hits, "closure_changed_modules": closure_hits})

    print(
        f"EMIT_FRONTEND: signature={signature[:16]} jobs={jobs} cache={'enabled' if cache_enabled else 'disabled'} "
        f"module_direct_hits={module_cache['summary']['direct_hits']} module_direct_misses={module_cache['summary']['direct_misses']}"
    )

    cached_meta = read_manifest(final_meta) if cache_enabled else None
    cached_sha = cached_meta.get("output_sha256") if cached_meta else None
    if (
        cache_enabled
        and final_cache.is_file()
        and final_cache.stat().st_size > 0
        and cached_meta is not None
        and cached_meta.get("input_signature") == signature
        and isinstance(cached_sha, str)
        and sha256_file(final_cache) == cached_sha
    ):
        status = "unchanged"
        if not (out_c.exists() and _same_output_bytes(final_cache, out_c)):
            copy_atomic(final_cache, out_c)
            status = "updated"
        report = {
            "gate": "frontend_regen",
            "pass": True,
            "fast_path": True,
            "input_signature": signature,
            "seed": str(ouro1),
            "fuel": fuel,
            "out": str(out_c),
            "work": str(work),
            "cache_enabled": cache_enabled,
            "final_cache": "hit",
            "output": status,
            "summary": {
                "tu_hits": len(FRONTEND_TUS),
                "tu_misses": 0,
                "module_direct_hits": module_cache["summary"]["direct_hits"],
                "module_direct_misses": module_cache["summary"]["direct_misses"],
                "module_closure_hits": module_cache["summary"]["closure_hits"],
                "module_closure_misses": module_cache["summary"]["closure_misses"],
                "affected_tus": len(affected_tus),
                "pack_cache": "skip-final-hit",
                "elapsed_s": round(total.elapsed(), 6),
            },
            "units": [],
            "module_cache": module_cache,
            "affected_tus": affected_tus,
            "phases": phases,
        }
        report["output_sha256"] = sha256_file(out_c)
        write_json_atomic(manifest, report)
        if report_path:
            write_json_atomic(report_path, report)
        print(f"EMIT_FRONTEND: final cache-hit {status} {out_c}")
        print(f"EMIT_FRONTEND: report {manifest}")
        print(f"EMIT_FRONTEND: OK packed {out_c} elapsed={total.elapsed():.3f}s fast-path")
        return report

    old_manifest = read_manifest(manifest)
    if old_manifest and old_manifest.get("input_signature") == signature and out_c.is_file():
        expected_sha = old_manifest.get("output_sha256")
        if expected_sha and sha256_file(out_c) == expected_sha:
            report = dict(old_manifest)
            report["fast_path"] = True
            report["final_cache"] = "manifest-hit"
            report["summary"] = dict(report.get("summary", {}))
            report["summary"]["elapsed_s"] = round(total.elapsed(), 6)
            report["summary"]["module_direct_hits"] = module_cache["summary"]["direct_hits"]
            report["summary"]["module_direct_misses"] = module_cache["summary"]["direct_misses"]
            report["summary"]["module_closure_hits"] = module_cache["summary"]["closure_hits"]
            report["summary"]["module_closure_misses"] = module_cache["summary"]["closure_misses"]
            report["summary"]["affected_tus"] = len(affected_tus)
            report["module_cache"] = module_cache
            report["affected_tus"] = affected_tus
            report["phases"] = phases
            if cache_enabled:
                copy_atomic(out_c, final_cache)
                write_json_atomic(final_meta, report)
            write_json_atomic(manifest, report)
            if report_path:
                write_json_atomic(report_path, report)
            print(f"EMIT_FRONTEND: manifest fast-path unchanged {out_c}")
            print(f"EMIT_FRONTEND: report {manifest}")
            print(f"EMIT_FRONTEND: OK packed {out_c} elapsed={total.elapsed():.3f}s fast-path")
            return report

    tu_cache = cache_root / "gen/frontend-tu"
    specs = list(FRONTEND_TUS)
    reports_by_tag: Dict[str, TuReport] = {}
    emit_timer = Timer()
    if jobs <= 1:
        for tag, mod, root, file_name in specs:
            reports_by_tag[tag] = emit_one(
                ouro1=ouro1,
                fuel=fuel,
                work=work,
                cache_enabled=cache_enabled,
                tu_cache=tu_cache,
                tag=tag,
                mod=mod,
                root=root,
                file_name=file_name,
                units=unit_graph[root],
                digests=digests,
                historical_bridge=historical_bridge,
                close_exports=True,
            )
    else:
        scheduled = sorted(specs, key=lambda spec:
            sum(digests[path].bytes for path in unit_graph[spec[2]]), reverse=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            futs = {
                pool.submit(
                    emit_one,
                    ouro1=ouro1,
                    fuel=fuel,
                    work=work,
                    cache_enabled=cache_enabled,
                    tu_cache=tu_cache,
                    tag=tag,
                    mod=mod,
                    root=root,
                    file_name=file_name,
                    units=unit_graph[root],
                    digests=digests,
                    historical_bridge=historical_bridge,
                    close_exports=True,
                ): tag
                for tag, mod, root, file_name in scheduled
            }
            for fut in concurrent.futures.as_completed(futs):
                tag = futs[fut]
                reports_by_tag[tag] = fut.result()
    unit_reports = [reports_by_tag[tag] for tag, _mod, _root, _file in specs]
    phases.append({"name": "emit_tus", "elapsed_s": round(emit_timer.elapsed(), 6)})
    for r in unit_reports:
        print(
            f"EMIT_FRONTEND: TU {r.tag} {r.cache} module={r.module} deps={r.deps} "
            f"bytes={r.bytes} elapsed={r.elapsed_s:.3f}s"
        )

    pieces = [(tag, work / file_name) for tag, _mod, _root, file_name in specs]
    pipeline_units = unit_graph.get("compiler/pipeline.ouro", ())
    parser_min_ordinal = (pipeline_units.index(packer.PARSER_UNIT_OWNER)
                          if packer.PARSER_UNIT_OWNER in pipeline_units else None)
    pkey = pack_key(pieces, digests, parser_min_ordinal=parser_min_ordinal)
    pack_cache = cache_root / "gen/frontend-pack" / f"driver_{pkey}.c"
    pack_timer = Timer()
    pack_status = "disabled"
    output_status = "updated"
    if cache_enabled and cached_output_matches(pack_cache, pkey):
        pack_status = "hit"
        if out_c.exists() and _same_output_bytes(pack_cache, out_c):
            output_status = "unchanged"
        else:
            copy_atomic(pack_cache, out_c)
            output_status = "updated"
    else:
        pack_status = "miss" if cache_enabled else "disabled"
        tmp = out_c.with_name(out_c.name + f".tmp.{os.getpid()}")
        tmp.unlink(missing_ok=True)
        run_pack(pieces, tmp, parser_min_ordinal=parser_min_ordinal)
        output_status = install_if_changed(tmp, out_c)
        if cache_enabled:
            copy_atomic(out_c, pack_cache)
            record_cached_output(pack_cache, pkey)
    phases.append({"name": "pack", "elapsed_s": round(pack_timer.elapsed(), 6)})

    if cache_enabled:
        copy_atomic(out_c, final_cache)

    hits = sum(1 for r in unit_reports if r.cache == "hit")
    misses = len(unit_reports) - hits
    report = {
        "gate": "frontend_regen",
        "pass": True,
        "fast_path": False,
        "input_signature": signature,
        "seed": str(ouro1),
        "fuel": fuel,
        "out": str(out_c),
        "work": str(work),
        "cache_enabled": cache_enabled,
        "final_cache": "miss" if cache_enabled else "disabled",
        "output": output_status,
        "summary": {
            "tu_hits": hits,
            "tu_misses": misses,
            "module_direct_hits": module_cache["summary"]["direct_hits"],
            "module_direct_misses": module_cache["summary"]["direct_misses"],
            "module_closure_hits": module_cache["summary"]["closure_hits"],
            "module_closure_misses": module_cache["summary"]["closure_misses"],
            "affected_tus": len(affected_tus),
            "pack_cache": pack_status,
            "elapsed_s": round(total.elapsed(), 6),
        },
        "units": [asdict(r) for r in unit_reports],
        "module_cache": module_cache,
        "affected_tus": affected_tus,
        "phases": phases,
        "pack_key": pkey,
        "output_sha256": sha256_file(out_c),
    }
    write_json_atomic(manifest, report)
    if cache_enabled:
        write_json_atomic(final_meta, report)
    if report_path:
        write_json_atomic(report_path, report)
    print(
        f"EMIT_FRONTEND: pack cache={pack_status} output={output_status} "
        f"tu_hits={hits} tu_misses={misses} "
        f"module_direct_misses={module_cache['summary']['direct_misses']} "
        f"module_closure_misses={module_cache['summary']['closure_misses']} "
        f"elapsed={total.elapsed():.3f}s"
    )
    print(f"EMIT_FRONTEND: report {manifest}")
    print(f"EMIT_FRONTEND: OK packed {out_c}")
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="regenerate split Ouro frontend with deterministic caches")
    ap.add_argument("--ouro1", default=os.environ.get("OURO1") or os.environ.get("OURO1_SEED") or str(ROOT / "_build/c/ouro1"))
    ap.add_argument("--fuel", default=os.environ.get("OURO1_CHECK_FUEL", "16000"))
    ap.add_argument("--out", default=os.environ.get("FRONTEND_OUT", str(ROOT / "compiler/stage0/driver_u.c")))
    ap.add_argument("--work", default=os.environ.get("FRONTEND_WORK", str(ROOT / "_build/fe")))
    ap.add_argument("--cache-root", default=os.environ.get("OURO_CACHE_DIR", str(ROOT / "_cache/ouro")))
    ap.add_argument("--report", default=os.environ.get("FRONTEND_REPORT"))
    ap.add_argument("--jobs", type=int, default=jobs_from_env())
    cache_group = ap.add_mutually_exclusive_group()
    cache_group.add_argument("--cache", dest="cache_enabled", action="store_true")
    cache_group.add_argument("--no-cache", dest="cache_enabled", action="store_false")
    ap.set_defaults(cache_enabled=bool_env(os.environ.get("OURO_CACHE"), True))
    args = ap.parse_args(argv)

    ouro1 = Path(args.ouro1)
    if not ouro1.is_absolute():
        ouro1 = ROOT / ouro1
    if not ouro1_usable(ouro1):
        print(f"EMIT_FRONTEND: FAIL missing executable ouro1 at {ouro1}", file=sys.stderr)
        return 1
    try:
        configure_native_stack()
        regenerate(
            ouro1=ouro1,
            fuel=str(args.fuel),
            out_c=Path(args.out) if Path(args.out).is_absolute() else ROOT / args.out,
            work=Path(args.work) if Path(args.work).is_absolute() else ROOT / args.work,
            cache_root=Path(args.cache_root) if Path(args.cache_root).is_absolute() else ROOT / args.cache_root,
            cache_enabled=bool(args.cache_enabled),
            report_path=(Path(args.report) if args.report else None),
            jobs=max(1, int(args.jobs)),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"EMIT_FRONTEND: FAIL {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
