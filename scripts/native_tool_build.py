#!/usr/bin/env python3
"""Content-addressed native tool builds; acceptance still belongs to the suites."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import sysconfig
import tempfile
import time
import unicodedata
from contextlib import ExitStack, nullcontext
from pathlib import Path
from typing import TYPE_CHECKING

import frontend_regen as frontend
import ouro_build as build
import pack_frontend as packer
from local_scheduler import JOBS_ENV, MEMORY_ENV, available_memory_mib
from pack_frontend import _static_symbol_matches
from repo_support import (
    configure_native_stack, decode_source_text, hash_json, read_json_object_or_none,
    sha256_bytes, sha256_file, write_json_atomic,
)
from scoped_host_export_consumers import current_native_scoped_aliases, current_native_scoped_original
from scoped_host_exports import ScopedExportIndex
from selfhost_module_cache import cached_import_parser, quoted_import_targets

if TYPE_CHECKING:
    from collections.abc import Callable

ROOT = Path(__file__).resolve().parents[1]
KIND = "ouro.native-tool-build.v1"
# Match the memory estimates in the CI and Smith native-tool allocations.
C_BUILD_BASE_MEMORY_MIB = 2560
C_WORKER_MEMORY_MIB = 512
RUNTIME = ("runtime/ouro_rt.c", "runtime/ouro_io.c", "runtime/ouro_prog_main.c",
           "runtime/frontend_link.c")
BUILD_INPUTS = (
    "scripts/build_tool.sh", "scripts/native_tool_build.py", "scripts/ouro_build.py",
    "scripts/generated_c_shards.py",
    "scripts/scoped_host_exports.py", "scripts/scoped_host_export_routes.py",
    "scripts/scoped_host_export_consumers.py", "scripts/structural_quality_legacy.py",
    "scripts/frontend_regen.py", "scripts/selfhost_module_cache.py", "scripts/pack_frontend.py",
    "scripts/repo_support.py", "scripts/ouro_seal.py", "scripts/python.sh",
)

# Fixed settings are bound by this builder's existing source hash in tool_inputs.
SHARD_GROUP_SIZE = 256
SHARD_SETTINGS = {"backend_group_size": SHARD_GROUP_SIZE, "schema": "v1",
                  "backend_export_suffix": "", "backend_only": True}
EXTRA_CFLAGS = ("-Werror=implicit-function-declaration", "-DOURO_FE_FLAT_EXPORTS")
EMIT_MODES = {"OURO_EMIT_IO_SHIMS": "1", "OURO_EMIT_SCOPED_ARITHMETIC": "1"}

# Transitional C-host quality commands accept UTF-8 paths, including argv.
# Keep this build metadata local to these tools, outside compiler/runtime seeds.
WINDOWS_UTF8_ENTRIES = frozenset((
    "tools/lint.ouro", "tools/lint_style.ouro", "tools/analyze/main.ouro", "tools/analyze/drive_main.ouro",
    "tools/fmt.ouro", "tools/fix/main.ouro", "tools/fix/check_main.ouro",
    "tools/clippy/main.ouro", "tools/clippy/structural_main.ouro",
    "tools/quality/inventory.ouro",
))
WINDOWS_UTF8_MANIFEST = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0"
          xmlns:asmv3="urn:schemas-microsoft-com:asm.v3">
  <assemblyIdentity type="win32" name="Ouro.Quality" version="1.0.0.0" processorArchitecture="amd64"/>
  <asmv3:application>
    <asmv3:windowsSettings xmlns="http://schemas.microsoft.com/SMI/2019/WindowsSettings">
      <activeCodePage>UTF-8</activeCodePage>
    </asmv3:windowsSettings>
  </asmv3:application>
</assembly>
'''

# Each seam is required only when its defining module belongs to this tool.
# A smaller tool may still export a seam; present exports are always checked.
HOST_HOOKS = (
    ("compile_checked_source", "ouro_wrap_quality_parse", ("compiler/driver.ouro",)),
    ("compile_checked_source_with_origin", "ouro_wrap_quality_parse", ("compiler/driver.ouro",)),
    ("compile_checked_units_with_origin", "ouro_wrap_compile_checked_units_with_origin", ("compiler/driver.ouro",)),
    ("cg_s_snapshot_request", "ouro_wrap_quality_io", ("tools/clippy/session.ouro",)),
    ("cg_s_emit_request", "ouro_wrap_quality_io", ("tools/clippy/session.ouro",)),
    ("cg_s_epoch_request", "ouro_wrap_quality_io", ("tools/clippy/session.ouro",)),
    ("cg_s_sample_heap", "ouro_wrap_quality_heap", ("tools/clippy/session.ouro",)),
    ("cm_load_file", "ouro_wrap_quality_parse", ("tools/clippy/semantic_unit.ouro",)),
    ("cm_load_file_cached", "ouro_wrap_settled3", ("tools/clippy/semantic_unit.ouro",)),
    ("cm_prepare_expanded", "ouro_wrap_quality_pure", ("tools/clippy/structural_frontend.ouro",)),
    ("cm_lex_expanded", "ouro_wrap_quality_pure", ("tools/clippy/structural_frontend.ouro",)),
    ("next_import_token", "ouro_wrap_import_token", ("compiler/lexer.ouro",)),
    ("next_import_token_indexed", "ouro_wrap_import_token", ("compiler/lexer.ouro",)),
    ("span_expr", "ouro_wrap_settled3", ("compiler/source_spans.ouro",)),
    # Import preprocessing rewrites the whole file. One lint cone keeps every
    # rewrite unless this entry returns only the selected names.
    ("lint_cone_facts", "ouro_wrap_quality_pure", ("tools/lint_worker.ouro",)),
    ("lint_select_rules", "ouro_wrap_quality_pure", ("tools/lint_worker.ouro",)),
    ("cm_parse", "ouro_wrap_quality_pure", ("tools/clippy/structural_frontend.ouro",)),
    ("cm_contract_for", "ouro_wrap_quality_pure", ("tools/clippy/semantic_registry.ouro",)),
    ("cm_validate_contract_bindings", "ouro_wrap_quality_pure", ("tools/clippy/semantic_registry.ouro",)),
    ("cm_build_apis", "ouro_wrap_quality_pure", ("tools/clippy/semantic_registry.ouro",)),
    ("cg_wire_scan_request", "ouro_wrap_quality_pure", ("tools/clippy/session_wire.ouro",)),
    ("cg_load_inventory", "ouro_wrap_quality_io", ("tools/clippy/main.ouro",)),
    ("cg_scan_chunk_request", "ouro_wrap_quality_io", ("tools/clippy/main.ouro",)),
    ("st_scan_request", "ouro_wrap_quality_io", ("tools/strict/fixtures.ouro",)),
    ("st_scan_def_span", "ouro_wrap_quality_pure", ("tools/strict/scan.ouro",)),
    ("st_load_cfg", "ouro_wrap_quality_io", ("tools/strict/main.ouro",)),
    ("st_registry_issues", "ouro_wrap_quality_io", ("tools/strict/fixtures.ouro",)),
    ("st_fixture_issues", "ouro_wrap_quality_io", ("tools/strict/fixtures.ouro",)),
    ("checked_program_type_globals_indexed", "ouro_wrap_settled3",
     ("compiler/checked_program_output.ouro",)),
    ("checked_type_former_using", "ouro_wrap_lower_normalize",
     ("compiler/checked_program_output.ouro",)),
    ("whnf_checked_indexed", "ouro_wrap_lower_normalize",
     ("compiler/file_elab_core.ouro",)),
    ("check_module", "ouro_wrap_check_module", ("compiler/file_elab.ouro",)),
    ("check_environment_from_entries", "ouro_wrap_check_environment_from_entries",
     ("compiler/file_check_environment.ouro",)),
    ("managed_source_symbol_using", "ouro_wrap_managed_source_symbol_using",
     ("compiler/native/managed_model.ouro",)),
    ("managed_source_spelling", "ouro_wrap_managed_source_spelling",
     ("compiler/native/managed_model.ouro",)),
    ("lower_recheck_program", "ouro_wrap_lower_recheck_program",
     ("compiler/native/lower_boundary.ouro",)),
    ("lower_normalize", "ouro_wrap_lower_normalize",
     ("compiler/native/lower_boundary.ouro",)),
    ("normalize_checked_indexed", "ouro_wrap_lower_normalize",
     ("compiler/file_elab_core.ouro",)),
    ("lower_make_contract_indexed", "ouro_wrap_lower_make_contract_indexed",
     ("compiler/native/lower_types.ouro",)),
    ("managed_prepare_rechecked", "ouro_wrap_managed_prepare_rechecked",
     ("compiler/native/managed_source.ouro",)),
    ("lower_function_indexed", "ouro_wrap_lower_function_indexed",
     ("compiler/native/lower.ouro",)),
    ("managed_finish_plan", "ouro_wrap_managed_finish_plan",
     ("compiler/native/managed_source.ouro",)),
    ("managed_global_function", "ouro_wrap_managed_global_function",
     ("compiler/native/managed_terms.ouro", "compiler/native/managed_terms_stdio.ouro")),
    ("mir_check_bounds", "ouro_wrap_mir_check_bounds", ("compiler/native/mir.ouro",)),
    ("mir_check_function", "ouro_wrap_mir_check_function", ("compiler/native/mir.ouro",)),
    ("mir_check_instruction", "ouro_wrap_mir_check_instruction", ("compiler/native/mir_types.ouro",)),
    ("mir_reachable", "ouro_wrap_mir_reachable", ("compiler/native/mir_flow.ouro",)),
    ("codegen_prepare_step", "ouro_wrap_codegen_prepare_step", ("compiler/native/codegen.ouro",)),
    ("x64_encode", "ouro_wrap_x64_encode", ("compiler/native/x64.ouro",)),
    ("codegen_assemble", "ouro_wrap_codegen_assemble", ("compiler/native/codegen_assembly.ouro",)),
    ("mir_live_facts", "ouro_wrap_mir_live_facts", ("compiler/native/mir_live.ouro",)),
    ("mir_live_summary_step", "ouro_wrap_mir_live_summary_step", ("compiler/native/mir_live.ouro",)),
    ("codegen_parts", "ouro_wrap_codegen_parts", ("compiler/native/codegen_model.ouro",)),
    ("codegen_live_instructions", "ouro_wrap_codegen_live_instructions", ("compiler/native/codegen_ops.ouro",)),
    ("codegen_clear_dead_roots", "ouro_wrap_codegen_clear_dead_roots", ("compiler/native/codegen_roots.ouro",)),
    ("codegen_instruction", "ouro_wrap_codegen_instruction", ("compiler/native/codegen_ops.ouro",)),
    ("codegen_block", "ouro_wrap_codegen_block", ("compiler/native/codegen_ops.ouro",)),
    ("codegen_body", "ouro_wrap_codegen_body", ("compiler/native/codegen.ouro",)),
    ("mir_gc_infer", "ouro_wrap_mir_gc_infer", ("compiler/native/mir_gc.ouro",)),
    ("mir_gc_annotate", "ouro_wrap_mir_gc_annotate", ("compiler/native/mir_gc.ouro",)),
    ("mir_gc_check", "ouro_wrap_mir_gc_check", ("compiler/native/mir_gc.ouro",)),
    ("pe_run_byte_check", "ouro_wrap_pe_run_byte_check", ("compiler/native/pe_model.ouro",)),
    ("pe_plan_fixups", "ouro_wrap_pe_plan_fixups", ("compiler/native/pe_fixups.ouro",)),
    ("pe_apply_patches", "ouro_wrap_pe_apply_patches", ("compiler/native/pe_fixups.ouro",)),
    ("pe_patch_prefix_step", "ouro_wrap_pe_patch_prefix_step", ("compiler/native/pe_fixups.ouro",)),
    ("pe_resolve_fixup_indexed_with", "ouro_wrap_pe_resolve_fixup_indexed", ("compiler/native/pe_fixups.ouro",)),
    ("pe_function_scan", "ouro_wrap_pe_function_scan", ("compiler/native/pe_unwind.ouro",)),
    ("pe_word32", "ouro_wrap_pe_word32", ("compiler/native/pe_model.ouro",)),
)


def tool_companions(entry: str) -> tuple[tuple[str, str], ...]:
    if entry in ("tools/fix/main.ouro", "tools/fmt.ouro"):
        return (("tools/fix/check_main.ouro", "ouro-fix-check"),)
    if entry == "tools/lint.ouro":
        return (("tools/lint_style.ouro", "ouro-lint-style"),
                ("tools/clippy/main.ouro", "ouro-clippy-grade-firewall"))
    if entry == "tools/clippy/main.ouro":
        return (("tools/clippy/structural_main.ouro", "ouro-clippy-structural"),)
    return ()


def tool_roots(entry: str) -> list[str]:
    roots = [entry]
    for root in roots:
        for companion, _name in tool_companions(root):
            if companion not in roots:
                roots.append(companion)
    return roots


def tool_inputs(entry: str, compiler: Path, fuel: int, cfg: build.ResolvedConfig, *,
                parse_bytes: frontend.ImportBytesParser | None = None,
                read_source: frontend.SourceBytesReader | None = None) -> tuple[list[str], dict]:
    # Shell callers resolve inputs against their own cwd. Repository inputs
    # keep one relative identity in content keys and portable source manifests.
    source = Path(os.path.normpath(entry.replace("\\", "/")))
    if source.is_absolute() and source.is_relative_to(ROOT):
        source = source.relative_to(ROOT)
    roots = tool_roots(source.as_posix())

    def read_compiler_inputs() -> dict:
        cc, location = build.locate_cc(cfg)
        cc_path = Path(location or cc).resolve()
        return {"compiler_sha256": sha256_file(compiler),
                "cc": build.compiler_id(cc, location=location or str(cc_path)),
                "cc_sha256": sha256_file(cc_path)}

    # The shared reader must capture source bytes after the C version query.
    compiler_inputs = read_compiler_inputs() if read_source is not None else None
    groups, captured = frontend.capture_unit_inputs(roots, parse_bytes=parse_bytes, read_source=read_source)
    units = groups[source.as_posix()]
    if not units:
        raise ValueError("empty source collection")
    companion_units = [unit for root in roots[1:] for unit in groups[root]]
    sources = dict.fromkeys([*units, *companion_units, *BUILD_INPUTS, *RUNTIME,
                            *(path.relative_to(ROOT).as_posix() for path in sorted((ROOT / "runtime").glob("*.h")))])
    if compiler_inputs is None:
        compiler_inputs = read_compiler_inputs()
    inputs = {
        "kind": KIND, "entry": units[-1], "fuel": fuel,
        **compiler_inputs,
        # platform.machine() is empty on Windows when the harness scrubs
        # PROCESSOR_ARCHITECTURE; Python's build platform remains stable.
        "platform": sys.platform, "machine": sysconfig.get_platform(),
        "cflags": build.profile_cflags(cfg), "link_flags": build.host_link_flags(),
        "environment": {name: os.environ.get(name, "") for name in
                        ("CPATH", "C_INCLUDE_PATH", "LIBRARY_PATH", "SDKROOT", "MACOSX_DEPLOYMENT_TARGET", "SOURCE_DATE_EPOCH")},
        "sources": {name: captured[name].sha256 if name in captured else sha256_file(ROOT / name)
                    for name in sources},
    }
    return units, inputs


def embed_windows_manifest(binary: Path, manifest: str) -> None:
    """Embed build-owned metadata before hashing or publishing the candidate.

    Resource mapping never executes the image. Other linker resources survive;
    a conflicting executable manifest is an error, not an implicit overwrite.
    """
    import ctypes
    from ctypes import wintypes as win

    api = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    signatures = (
        ("LoadLibraryExW", [win.LPCWSTR, win.HANDLE, win.DWORD], win.HANDLE),
        ("FindResourceW", [win.HANDLE, ctypes.c_void_p, ctypes.c_void_p], win.HANDLE),
        ("SizeofResource", [win.HANDLE, win.HANDLE], win.DWORD),
        ("LoadResource", [win.HANDLE, win.HANDLE], win.HANDLE),
        ("LockResource", [win.HANDLE], ctypes.c_void_p),
        ("FreeLibrary", [win.HANDLE], win.BOOL),
        ("BeginUpdateResourceW", [win.LPCWSTR, win.BOOL], win.HANDLE),
        ("UpdateResourceW", [win.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                             win.WORD, ctypes.c_void_p, win.DWORD], win.BOOL),
        ("EndUpdateResourceW", [win.HANDLE, win.BOOL], win.BOOL),
    )
    for name, arguments, result in signatures:
        function = getattr(api, name)
        function.argtypes, function.restype = arguments, result
    path = str(binary.resolve())
    data = manifest.encode("utf-8")
    # LOAD_LIBRARY_AS_DATAFILE_EXCLUSIVE | LOAD_LIBRARY_AS_IMAGE_RESOURCE.
    image = api.LoadLibraryExW(path, None, 0x60)
    if not image:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        resource = api.FindResourceW(image, ctypes.c_void_p(1), ctypes.c_void_p(24))
        if resource:
            size = api.SizeofResource(image, resource)
            loaded = api.LoadResource(image, resource)
            address = api.LockResource(loaded) if loaded else None
            if not size or not address:
                raise ctypes.WinError(ctypes.get_last_error())
            if ctypes.string_at(address, size) != data:
                raise RuntimeError("C linker provided a conflicting executable manifest")
            return
        # ERROR_RESOURCE_DATA/TYPE/NAME_NOT_FOUND are the only empty states.
        error = ctypes.get_last_error()
        if error not in (1812, 1813, 1814):
            raise ctypes.WinError(error)
    finally:
        if not api.FreeLibrary(image):
            raise ctypes.WinError(ctypes.get_last_error())

    handle = api.BeginUpdateResourceW(path, False)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_string_buffer(data)
    if not api.UpdateResourceW(handle, ctypes.c_void_p(24), ctypes.c_void_p(1),
                               0, buffer, len(data)):
        error = ctypes.get_last_error()
        if not api.EndUpdateResourceW(handle, True):
            raise RuntimeError(f"resource update failed ({error}); discard also failed ({ctypes.get_last_error()})")
        raise ctypes.WinError(error)
    if not api.EndUpdateResourceW(handle, False):
        raise ctypes.WinError(ctypes.get_last_error())


def _host_preamble_end(text: str) -> int:
    first_getter = text.find("static ouro_v *ouro_g")
    return len(text) if first_getter < 0 else first_getter


def installed_hook_view(text: str, *, include_presence: bool = False) -> dict:
    names, values = {}, {}
    present_names = set() if include_presence else None
    next_name_start = 0
    # Consume only the case prefix. Independent legacy searches also see rows
    # nested in malformed labels or comments.
    for row in re.finditer(r'case(?=\s+(?P<index>\d+):\s*return\s+(?:"(?P<name>[^"]+)"|(?P<getter>ouro_g\d+)\(\)))', text):
        name = row.group("name")
        if name is not None:
            names.setdefault(name, []).append(row.group("index"))
            # Presence checks consume the entire quoted match. Getter lookup keeps nested rows.
            if present_names is not None and row.start() >= next_name_start:
                present_names.add(name)
                next_name_start = row.end("name") + 1
        else:
            values.setdefault(row.group("index"), []).append(row.group("getter"))
    preamble_end = _host_preamble_end(text)
    return {"text": text, "names": names, "values": values, "present_names": present_names,
            "static_index": packer.StaticSymbolIndex(text),
            "preamble_end": preamble_end}


def installed_export_getter(text: str, export_name: str, view: dict) -> str:
    if view["text"] is not text:
        raise RuntimeError("installed hook view belongs to different text")
    names = (re.findall(rf'case\s+(\d+):\s*return\s+"{re.escape(export_name)}"', text)
             if '"' in export_name else view["names"].get(export_name, []))
    values = view["values"].get(names[0], []) if names else []
    if len(names) != 1 or len(values) != 1:
        raise RuntimeError(f"missing, malformed or duplicate installed {export_name} getter")
    return values[0]


def verify_installed_getter(text: str, export_name: str, getter: str, replacement: str,
                            declaration: str, *, _view: dict | None = None,
                            scoped: bool = False) -> None:
    if scoped and _view is None:
        view = {"static_index": packer.StaticSymbolIndex(text), "preamble_end": _host_preamble_end(text)}
    else:
        view = installed_hook_view(text) if _view is None else _view
    if not scoped and installed_export_getter(text, export_name, view) != getter:
        raise RuntimeError(f"missing, malformed or duplicate installed {export_name} getter")
    symbol = getter if re.fullmatch(r"ouro_g[0-9]+", getter) else None
    starts = view["static_index"].starts
    # The static index covers C identifiers. Retain full regex matching for
    # non-ASCII IDs accepted by the existing digit patterns.
    definitions = _static_symbol_matches(text,
        rf"\bstatic\s+ouro_v\s*\*\s*{re.escape(getter)}(?:_d[0-9]+)?\s*\([^;{{]*\)\s*\{{", starts, symbol)
    cache = "ouro_c" + getter[len("ouro_g"):]
    cache_symbol = cache if symbol is not None else None
    caches = _static_symbol_matches(text,
        rf"\bstatic\s+ouro_v\s*\*\s*{cache}(?:_d[0-9]+)?\b", starts, cache_symbol)
    if (len(definitions) != 1 or len(caches) != 1
            or len(_static_symbol_matches(text, re.escape(f"static ouro_v *{cache};"), starts, cache_symbol)) != 1
            or len(_static_symbol_matches(text, re.escape(replacement), starts, symbol)) != 1
            or text.count(declaration, 0, view["preamble_end"]) != 1):
        raise RuntimeError(f"missing, malformed or duplicate installed {export_name} getter")


def hook_named_getter(text: str, export_name: str, wrapper: str, *, installed: bool = False,
                      _view: dict | None = None, scoped_getter: str | None = None) -> str:
    getter = scoped_getter
    if getter is None and installed:
        _view = installed_hook_view(text) if _view is None else _view
        getter = installed_export_getter(text, export_name, _view)
    elif getter is None:
        name_match = re.search(
            rf'case\s+(\d+):\s*return\s+"{re.escape(export_name)}"', text)
        if name_match is None:
            raise RuntimeError(f"generated C has no {export_name} export name")
        idx = name_match.group(1)
        value_match = re.search(rf'case\s+{idx}:\s*return\s+(ouro_g\d+)\(\)', text)
        if value_match is None:
            raise RuntimeError(f"generated C has no {export_name} export value")
        getter = value_match.group(1)
    gid = getter[len("ouro_g"):]
    pattern = (
        rf"static ouro_v \*{getter}\(void\)\{{"
        rf"ouro_env \*env=0;\(void\)env;"
        rf"if\(ouro_c{gid}==0\)\{{"
        rf"ouro_static_begin\(\);ouro_c{gid}=ouro_clos\(ouro_f{gid}_,env\);"
        rf"ouro_static_end\(\);}}return ouro_c{gid};}}"
    )
    replacement = (
        f"static ouro_v *{getter}(void){{"
        f"ouro_env *env=0;(void)env;"
        f"if(ouro_c{gid}==0){{"
        f"ouro_static_begin();"
        f"ouro_c{gid}={wrapper}(ouro_clos(ouro_f{gid}_,env));"
        f"ouro_static_end();}}return ouro_c{gid};}}"
    )
    # IO lifetimes must cover execution of the thunk, not its construction.
    # This header is already part of the builder's hashed runtime inputs.
    decl = ('#include "ouro_quality_scope.h"\n' if wrapper in {"ouro_wrap_quality_io", "ouro_wrap_quality_heap", "ouro_wrap_quality_pure"}
            else f"ouro_v *{wrapper}(ouro_v *raw);\n")
    if installed:
        verify_installed_getter(text, export_name, getter, replacement, decl, _view=_view,
                                scoped=scoped_getter is not None)
        return text
    text, n = re.subn(pattern, replacement, text, count=1)
    if n != 1:
        raise RuntimeError(f"could not hook {export_name} getter {getter}")
    if decl not in text:
        text = text.replace('#include "ouro_rt.h"\n', '#include "ouro_rt.h"\n' + decl, 1)
    return text


def _rewrite_checked_getter(text: str, match: re.Match[str], replacement: str, wrapper: str) -> str:
    start, end = match.span()
    replacements = [(start, end, replacement)]
    # The replacement keeps the getter marker that ends the preamble.
    preamble_end = _host_preamble_end(text)
    if text.find(wrapper, 0, preamble_end) >= 0:
        return packer.replace_spans(text, replacements)

    include = '#include "ouro_rt.h"\n'
    declaration = f"ouro_v *{wrapper}(void);\n"
    include_start = text.find(include, 0, preamble_end)
    if include_start >= 0:
        position = include_start + len(include)
        replacements.append((position, position, declaration))
        return packer.replace_spans(text, replacements)

    return packer.replace_spans(text, replacements).replace(include, include + declaration, 1)


def hook_checked_units_getter(text: str, *, installed: bool = False, _view: dict | None = None) -> str:
    """Replace the checked-units entry while preserving its strict host path."""
    if installed:
        _view = installed_hook_view(text) if _view is None else _view
        getter = installed_export_getter(text, "compile_checked_units", _view)
    else:
        name_match = re.search(r'case\s+(\d+):\s*return\s+"compile_checked_units"', text)
        if name_match is None:
            raise RuntimeError("generated C has no compile_checked_units export")
        idx = name_match.group(1)
        value_match = re.search(rf'case\s+{idx}:\s*return\s+(ouro_g\d+)\(\)', text)
        if value_match is None:
            raise RuntimeError("generated C has no compile_checked_units getter")
        getter = value_match.group(1)
    gid = getter[len("ouro_g"):]
    pattern = (
        rf"static ouro_v \*{getter}\(void\)\{{"
        rf"ouro_env \*env=0;\(void\)env;"
        rf"if\(ouro_c{gid}==0\)\{{"
        rf"ouro_static_begin\(\);ouro_c{gid}=ouro_clos\(ouro_f{gid}_,env\);"
        rf"ouro_static_end\(\);}}return ouro_c{gid};}}"
    )
    replacement = (
        f"static ouro_v *{getter}(void){{"
        f"if(ouro_c{gid}==0)ouro_c{gid}=ouro_fe_compile_checked_units_clos();"
        f"return ouro_c{gid};}}"
    )
    if installed:
        verify_installed_getter(text, "compile_checked_units", getter, replacement,
                                "ouro_v *ouro_fe_compile_checked_units_clos(void);\n", _view=_view)
        return text
    match = re.search(pattern, text)
    if match is None:
        raise RuntimeError(f"could not hook compile_checked_units getter {getter}")
    return _rewrite_checked_getter(text, match, replacement, "ouro_fe_compile_checked_units_clos")


def hook_checked_source_packet_getter(text: str, *, installed: bool = False, _view: dict | None = None) -> str:
    """Retain the complete typed packet through the strict host compiler path."""
    if installed:
        _view = installed_hook_view(text) if _view is None else _view
        getter = installed_export_getter(text, "compile_checked_units_with_source_packet", _view)
    else:
        name_match = re.search(r'case\s+(\d+):\s*return\s+"compile_checked_units_with_source_packet"', text)
        if name_match is None:
            raise RuntimeError("generated C has no compile_checked_units_with_source_packet export")
        idx = name_match.group(1)
        value_match = re.search(rf'case\s+{idx}:\s*return\s+(ouro_g\d+)\(\)', text)
        if value_match is None:
            raise RuntimeError("generated C has no compile_checked_units_with_source_packet getter")
        getter = value_match.group(1)
    gid = getter[len("ouro_g"):]
    pattern = (
        rf"static ouro_v \*{getter}\(void\)\{{"
        rf"ouro_env \*env=0;\(void\)env;"
        rf"if\(ouro_c{gid}==0\)\{{"
        rf"ouro_static_begin\(\);ouro_c{gid}=ouro_clos\(ouro_f{gid}_,env\);"
        rf"ouro_static_end\(\);}}return ouro_c{gid};}}"
    )
    replacement = (
        f"static ouro_v *{getter}(void){{"
        f"if(ouro_c{gid}==0)ouro_c{gid}=ouro_fe_compile_checked_units_with_source_packet_clos();"
        f"return ouro_c{gid};}}"
    )
    if installed:
        verify_installed_getter(text, "compile_checked_units_with_source_packet", getter, replacement,
                                "ouro_v *ouro_fe_compile_checked_units_with_source_packet_clos(void);\n", _view=_view)
        return text
    match = re.search(pattern, text)
    if match is None:
        raise RuntimeError(f"could not hook compile_checked_units_with_source_packet getter {getter}")
    return _rewrite_checked_getter(text, match, replacement, "ouro_fe_compile_checked_units_with_source_packet_clos")


def hook_compile_checked_units(generated: Path, units: list[str] | tuple[str, ...] = (), *,
                               installed: bool = False, source_text: str | None = None) -> None:
    """Hook relevant host seams; malformed or missing required exports fail."""
    text = generated.read_text(encoding="utf-8") if source_text is None else source_text
    view = installed_hook_view(text, include_presence=True) if installed else None
    exports = (set(re.findall(r'case\s+\d+:\s*return\s+"([^"]+)"', text)) if view is None
               else view["present_names"])
    sources = {os.path.relpath(ROOT / unit, ROOT).replace("\\", "/") for unit in units}
    if "compile_checked_units" in exports or "compiler/driver.ouro" in sources:
        text = hook_checked_units_getter(text, installed=installed, _view=view)
    if "compile_checked_units_with_source_packet" in exports or "compiler/driver.ouro" in sources:
        text = hook_checked_source_packet_getter(text, installed=installed, _view=view)
    for name, wrapper, owners in HOST_HOOKS:
        if name in exports or sources.intersection(owners):
            text = hook_named_getter(text, name, wrapper, installed=installed, _view=view)
    static_index = view["static_index"] if view is not None else None
    text = packer.hook_module_pure_scopes(text, tuple(sources), installed=installed, static_index=static_index)
    if not installed:
        generated.write_text(text, encoding="utf-8")


def hook_sha_compress(text, units, canonical_units, entry, sources, *, installed=False, export_index=None):
    bindings = packer.scoped_host_export_getters(
        text, units, canonical_units, entry, sources,
        (("sha_compress", "sha_compress", ("std/crypto.ouro",)),), export_index=export_index)
    return hook_named_getter(text, "sha_compress", "ouro_wrap_quality_pure",
                             installed=installed, scoped_getter=bindings["sha_compress"])


def hook_emission_scopes(text: str, units: list[str], *, installed: bool = False,
                         parse_bytes: frontend.ImportBytesParser | None = None) -> str:
    entry = units[-1]
    captured = {}

    def capture_source(data: bytes, path: str) -> list[str]:
        source = decode_source_text(data)
        captured[path] = source
        return parse_bytes(data, path) if parse_bytes is not None else quoted_import_targets(source, path)

    canonical_units = frontend.collect_units_many([entry], parse_bytes=capture_source)[entry]
    sources = {unit: captured[unit] for unit in canonical_units}
    export_index = ScopedExportIndex()
    # Source-owned hooks use the original export view. The projection verifies
    # the installed closed aliases before removing them in memory.
    original = (current_native_scoped_original(text, units, canonical_units, entry, sources, export_index=export_index)
                if installed else text)
    installed_original = original
    static_index = packer.StaticSymbolIndex(original, export_index=export_index)
    for hook in (packer.hook_prelude_arithmetic, packer.hook_pe_fixup_step,
                 packer.hook_source_name_compare_scope, packer.hook_elem_scope):
        static_index = packer.StaticSymbolIndex.for_text(original, static_index)
        original = hook(original, units, canonical_units, entry, sources,
                        installed=installed, static_index=static_index)
    # Each compression block retains its hash state and releases its scratch values.
    if "std/crypto.ouro" in units:
        original = hook_sha_compress(original, units, canonical_units, entry, sources,
                                     installed=installed, export_index=export_index)
    capable = ((packer.MODULE_LOOKUP_OWNER in units or packer.LOWER_LOCAL_LOOKUP_OWNER in units)
               and frontend.module_lookup_capability((ROOT / "runtime/frontend_link.c").read_text(encoding="utf-8")))
    if packer.MODULE_LOOKUP_OWNER in units and capable:
        static_index = packer.StaticSymbolIndex.for_text(original, static_index)
        original = packer.hook_module_lookup(original, units, canonical_units, entry, sources,
                                             installed=installed, static_index=static_index)
    if packer.LOWER_LOCAL_LOOKUP_OWNER in units and capable:
        static_index = packer.StaticSymbolIndex.for_text(original, static_index)
        original = packer.hook_lower_local_lookup(original, units, canonical_units, entry, sources,
                                                  installed=installed, static_index=static_index)
    if installed:
        if original != installed_original:
            raise RuntimeError("installed source hooks changed the original export view")
        # The projection already checked these aliases on this exact text and
        # source context. Installed body guards leave both export views intact.
        return text
    return current_native_scoped_aliases(original, units, canonical_units, entry, sources,
                                         export_index=export_index)


def emission_environment() -> dict[str, str]:
    return {**EMIT_MODES, "WSLENV": (os.environ.get("WSLENV", "") + ":" + ":".join(EMIT_MODES)).lstrip(":")}


def verify_emission_hooks(generated: Path, units: list[str], *,
                          parse_bytes: frontend.ImportBytesParser | None = None) -> None:
    text = generated.read_text(encoding="utf-8")
    hook_emission_scopes(text, units, installed=True, parse_bytes=parse_bytes)
    hook_compile_checked_units(generated, units, installed=True, source_text=text)


def prepare_emission(compiler: Path, units: list[str], fuel: int, generated: Path,
                     cfg: build.ResolvedConfig, inputs: dict, *, cache_enabled: bool,
                     parse_bytes: frontend.ImportBytesParser | None = None) -> str:
    # Final tool inputs retain their public schema. Emission also binds closure
    # order, which a sorted input-map hash does not preserve.
    key = hash_json({"kind": "ouro.native-tool-emission.v1", "inputs": inputs, "units": units,
                     "config": cfg.values, "environment": emission_environment()})

    def unchanged() -> None:
        if (tool_inputs(inputs["entry"], compiler, fuel, cfg, parse_bytes=parse_bytes) != (units, inputs)
                or key != hash_json({"kind": "ouro.native-tool-emission.v1", "inputs": inputs, "units": units,
                                    "config": cfg.values, "environment": emission_environment()})):
            raise ValueError("tool source/compiler/runtime/build configuration changed during emission")

    unchanged()
    if cache_enabled and frontend.cached_output_matches(generated, key):
        try:
            verify_emission_hooks(generated, units)
        except (OSError, UnicodeError, RuntimeError):
            pass
        else:
            unchanged()
            if frontend.cached_output_matches(generated, key):
                return "hit"
    generated.with_suffix(".json").unlink(missing_ok=True)
    # Reuse import parsing between the installer and its check. Both still read
    # the source independently and the caller's input parser cannot supply it.
    canonical_imports = cached_import_parser()
    emit(compiler, units, fuel, generated, parse_bytes=canonical_imports)
    unchanged()
    generated_hash = sha256_file(generated)
    verify_emission_hooks(generated, units, parse_bytes=canonical_imports)
    del canonical_imports
    unchanged()
    if sha256_file(generated) != generated_hash:
        raise ValueError("generated tool changed during emission validation")
    if cache_enabled:
        # Only this successful emission may issue its receipt. Existing C is
        # never certified retrospectively after an interrupted C build.
        frontend.record_cached_output(generated, key)
    return "miss"


def complete_binary(binary: Path, metadata: Path, key: str, *, inputs: dict | None = None) -> bool:
    data = read_json_object_or_none(metadata)
    if data is None or data.get("kind") != KIND or data.get("key") != key:
        return False
    if inputs is not None and (data.get("inputs") != inputs or data.get("cache") not in ("miss", "hit", "installed-hit")):
        return False
    try:
        return (binary.is_file() and binary.stat().st_size > 0
                and os.access(binary, os.X_OK)
                and data.get("binary_sha256") == sha256_file(binary))
    except OSError:
        return False


def emit(compiler: Path, units: list[str], fuel: int, generated: Path, *,
         phase_callback: Callable[[str, float | None], None] | None = None,
         parse_bytes: frontend.ImportBytesParser | None = None) -> None:
    token = f"{os.getpid()}.{time.time_ns()}"
    temporary = generated.with_name(f"emit.{token}.c")
    error_log = generated.with_name(f"emit.{token}.err")
    argv = [*frontend.ouro1_cmd(compiler), units[-1], str(fuel)]
    for unit in units:
        argv.extend(("--unit", unit))
    env = dict(os.environ, **emission_environment())

    def start_phase(name: str) -> float:
        if phase_callback is not None:
            phase_callback(name, None)
        return time.perf_counter()

    def finish_phase(name: str, started: float) -> None:
        if phase_callback is not None:
            phase_callback(name, time.perf_counter() - started)

    try:
        started = start_phase("compiler")
        with temporary.open("wb") as output, error_log.open("wb") as errors:
            result = subprocess.run(argv, cwd=ROOT, env=env, stdout=output, stderr=errors, check=False)
        if result.returncode != 0 or temporary.stat().st_size == 0:
            raise RuntimeError(f"emit failed rc={result.returncode}: {error_log.read_text(encoding='utf-8', errors='replace')}")
        finish_phase("compiler", started)
        started = start_phase("uniquify")
        subprocess.run([sys.executable, str(ROOT / "scripts/pack_frontend.py"), "--uniquify-only", str(temporary)],
                       cwd=ROOT, check=True)
        finish_phase("uniquify", started)
        started = start_phase("hooks")
        aliased = hook_emission_scopes(temporary.read_text(encoding="utf-8"), units, parse_bytes=parse_bytes)
        hook_compile_checked_units(temporary, units, source_text=aliased)
        finish_phase("hooks", started)
        started = start_phase("publish")
        os.replace(temporary, generated)
        finish_phase("publish", started)
    finally:
        temporary.unlink(missing_ok=True)


def publish(binary: Path, output: Path) -> None:
    suffix = ".exe" if os.name == "nt" else ""
    temporary = output.with_name(f"{output.name}.tmp.{os.getpid()}.{time.time_ns()}{suffix}")
    try:
        shutil.copyfile(binary, temporary)
        temporary.chmod(temporary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        for attempt in range(10):
            try:
                os.replace(temporary, output)
                break
            except PermissionError:
                if os.name != "nt" or attempt == 9:
                    raise
                time.sleep(0.2)
    finally:
        temporary.unlink(missing_ok=True)


def tool_object_dir(cfg: build.ResolvedConfig, inputs: dict, directory: Path, *, isolated: bool = False) -> Path:
    if isolated:
        return directory.parent / "obj" / directory.name[:16]
    if not cfg.get_bool("cache_enabled"):
        return directory / "objects"
    return cfg.path("cache_dir") / "native-tools" / "obj" / hash_json({name: inputs[name] for name in
        ("cc", "cc_sha256", "platform", "machine", "cflags", "environment")})[:16]


def read_current_shard_manifest(path: Path, expected_hash: str) -> dict | None:
    # Bound memory while checking an oversized file against its receipt.
    chunk_size = 1024 * 1024
    with path.open("rb") as source:
        contents = source.read(chunk_size + 1)
        digest = hashlib.sha256(contents)
        if len(contents) > chunk_size:
            contents = None
            while chunk := source.read(chunk_size):
                digest.update(chunk)
    if digest.hexdigest() != expected_hash:
        return None
    if contents is None:
        return build.GCS.read_json(path)
    try:
        text = decode_source_text(contents)
        del contents
        data = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def verify_generated_tool_source(generated: Path, inputs: dict, expected_sources: dict, *,
                                 parse_bytes: frontend.ImportBytesParser | None = None) -> None:
    """Recheck the retained source and installed export view."""
    source_hashes = inputs["sources"]
    if packer.LOWER_LOCAL_LOOKUP_OWNER in source_hashes:
        text, digest = build.GCS.read_source_text_digest(generated)
    else:
        text = None
        digest = build.GCS.read_normalized_source_digest(generated, chunk_bytes=256 * 1024)
    if expected_sources != {"backend": digest}:
        raise RuntimeError("generated tool source digest changed")
    if text is None:
        return
    entry = inputs["entry"]
    units = (frontend.collect_units(entry) if parse_bytes is None
             else frontend.collect_units_many([entry], parse_bytes=parse_bytes)[entry])
    if packer.LOWER_LOCAL_LOOKUP_OWNER not in units:
        return
    runtime = ROOT / "runtime/frontend_link.c"
    runtime_bytes = runtime.read_bytes()
    if sha256_bytes(runtime_bytes) != source_hashes["runtime/frontend_link.c"]:
        raise RuntimeError("lower local lookup runtime changed")
    if not frontend.module_lookup_capability(decode_source_text(runtime_bytes)):
        return
    sources = {}
    for unit in units:
        data = (ROOT / unit).read_bytes()
        if sha256_bytes(data) != source_hashes[unit]:
            raise RuntimeError("lower local lookup source changed")
        sources[unit] = decode_source_text(data)
    export_index = ScopedExportIndex()
    text = current_native_scoped_original(text, units, units, entry, sources, export_index=export_index)
    static_index = packer.StaticSymbolIndex(text, export_index=export_index)
    packer.hook_lower_local_lookup(text, units, units, entry, sources, installed=True, static_index=static_index)


def build_artifacts_current(directory: Path, cfg: build.ResolvedConfig, inputs: dict,
                            record: dict, binary: Path, *, isolated: bool = False,
                            parse_bytes: frontend.ImportBytesParser | None = None) -> bool:
    """Recheck the retained generated shards and ordinary C-owner receipts."""
    try:
        generated = directory / "tool.gen.c"
        shard_dir = directory / "generated-c-shards"
        manifest = shard_dir / "generated-c-shards.manifest.json"
        built = record["build"]
        shards = built["generated_c_shards"]
        generated_hash = record["generated_sha256"]
        manifest_hash = record["shard_manifest_sha256"]
        if (sha256_file(generated) != generated_hash
                or shards["manifest_path"] != build.rel(manifest)
                or hash_json(shards["settings"]) != hash_json(SHARD_SETTINGS)
                or shards["generator_hash"] != build.GCS.generator_digest(SHARD_SETTINGS)):
            return False
        ok, _reason = build.GCS.manifest_valid(read_current_shard_manifest(manifest, manifest_hash),
            generator_hash=shards["generator_hash"], source_digests=shards["sources"], plan_meta=shards["shards"])
        if not ok:
            return False
        try:
            verify_generated_tool_source(generated, inputs, shards["sources"], parse_bytes=parse_bytes)
        except RuntimeError:
            return False
        sources = []
        for item in shards["shards"]:
            path = (ROOT / item["path"]).resolve()
            parent = path.parent
            if ((parent != shard_dir and parent != shard_dir.resolve()) or type(item["compile"]) is not bool
                    or item["role"] != "backend"):
                return False
            if item["compile"]:
                sources.append((item["label"], path))
        if not sources or len({path for _label, path in sources}) != len(sources):
            return False
        sources.extend((name, (ROOT / name).resolve()) for name in RUNTIME)
        cc = build.choose_cc(cfg)
        if (built["kind"] != "ouro.c-build-report.v2" or built["target"] != "native-tool"
                or built["cc"] != cc or built["compiler_id"] != inputs["cc"]
                or len(built["sources"]) != len(sources)):
            return False
        flags = build.object_profile_cflags(inputs["cflags"], json.loads(inputs["cc"])["version"])
        flags.extend([*EXTRA_CFLAGS, "-I" + str(ROOT / "runtime")])
        object_dir = tool_object_dir(cfg, inputs, directory, isolated=isolated)
        resolved_root = build.ROOT.resolve()
        objects = []
        for (label, src), item in zip(sources, built["sources"], strict=True):
            source_key = build.path_key(src, resolved_root=resolved_root)
            flags_key = hash_json({"flags": flags, "target": "native-tool", "source": source_key, "label": label})
            obj = object_dir / build.safe_obj_name("native-tool", label, flags_key)
            dep, stamp = obj.with_suffix(".d"), obj.with_suffix(".cmdhash")
            command = [cc, *flags, "-MMD", "-MP", "-MF", str(dep), "-c", source_key, "-o", str(obj)]
            expected = build.command_hash(command, inputs["cc"])
            if (item["label"] != label or item["source"] != source_key
                    or item["object"] != build.rel(obj) or item["depfile"] != build.rel(dep)
                    or item["cmdhash"] != build.rel(stamp)):
                return False
            object_hash, _reason = build.compile_stamp_digest(obj, dep, stamp, expected, src,
                expected_stamp_fields={"target": "native-tool", "compiler_id": inputs["cc"], "command": command})
            if object_hash is None or item["object_sha256"] != object_hash:
                return False
            objects.append(obj)
        cached_binary = directory / ("tool.exe" if os.name == "nt" else "tool")
        embedded = os.name == "nt" and inputs["entry"] in WINDOWS_UTF8_ENTRIES
        linked = directory / "tool.link.exe" if embedded else cached_binary
        link_stamp = Path(str(linked) + ".cmdhash")
        link = built["link"]
        command = [cc, *inputs["cflags"], *inputs["link_flags"], "-o", str(linked), *(str(obj) for obj in objects)]
        expected = build.command_hash(command, inputs["cc"])
        # An installed copy retains link proof even if its cached image was evicted.
        link_image = linked if embedded else binary
        if (built["objects"] != [build.rel(obj) for obj in objects] or link["output"] != build.rel(linked)
                or link["cmdhash"] != build.rel(link_stamp)):
            return False
        output_hash, _reason = build.link_stamp_digest(link_image, link_stamp, expected, objects,
            expected_stamp_fields={"target": "native-tool", "compiler_id": inputs["cc"], "command": command})
        if output_hash is None or link["output_sha256"] != output_hash:
            return False
        return sha256_file(generated) == generated_hash and sha256_file(manifest) == manifest_hash
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def complete_tool(binary: Path, metadata: Path, key: str, directory: Path,
                  cfg: build.ResolvedConfig, inputs: dict, *, isolated: bool = False,
                  parse_bytes: frontend.ImportBytesParser | None = None) -> dict | None:
    record = read_json_object_or_none(metadata)
    try:
        if (record is not None and record.get("kind") == KIND and record.get("key") == key
                and record.get("cache") in ("miss", "hit", "installed-hit")
                and record.get("inputs") == inputs and binary.is_file() and binary.stat().st_size > 0
                and os.access(binary, os.X_OK) and record.get("binary_sha256") == sha256_file(binary)
                and build_artifacts_current(directory, cfg, inputs, record, binary, isolated=isolated,
                                            parse_bytes=parse_bytes)):
            return record
    except OSError:
        pass
    return None


def _c_worker_count(cfg: build.ResolvedConfig, *, explicit_jobs: bool) -> int:
    jobs = build.jobs_value(cfg)
    if MEMORY_ENV not in os.environ and (explicit_jobs or jobs == 1):
        return jobs
    memory = available_memory_mib()
    if memory is None:
        return jobs if JOBS_ENV in os.environ else min(jobs, 2)
    memory_workers = max(1, (memory - C_BUILD_BASE_MEMORY_MIB) // C_WORKER_MEMORY_MIB)
    return min(jobs, memory_workers)


OUTPUT_LOCK_SUFFIX = ".native-tool-output-lock"


def _tool_output_paths(destination: Path) -> tuple[Path, Path]:
    logical = destination.resolve()
    if os.name == "nt" and logical.suffix != ".exe":
        return logical, Path(str(logical) + ".exe")
    return logical, logical


def _tool_output_files(logical: Path, executable: Path) -> tuple[Path, ...]:
    return (logical, executable, Path(str(logical) + ".sources"), Path(str(logical) + ".build.json"),
            executable.with_name(f".{executable.name}{OUTPUT_LOCK_SUFFIX}"))


def _tool_outputs(entry: str, destination: Path) -> list[tuple[str, Path, Path]]:
    logical, output = _tool_output_paths(destination)
    outputs = [(entry, logical, output)]
    for companion_entry, name in tool_companions(entry):
        outputs.extend(_tool_outputs(companion_entry, output.parent / name))
    return outputs


def _output_lock_order(path: Path) -> tuple[str, str]:
    spelling = str(path)
    return unicodedata.normalize("NFC", spelling).casefold(), spelling


def build_tool(args: argparse.Namespace, *, parse_bytes: frontend.ImportBytesParser | None = None) -> dict:
    cfg = build.load_config(args)
    with build.cache_build_access(cfg):
        report, cache_changed = _build_tool(args, cfg, parse_bytes=parse_bytes)
    if cache_changed:
        build.trim_cache(cfg)
    return report


def _build_tool(args: argparse.Namespace, cfg: build.ResolvedConfig, *,
                parse_bytes: frontend.ImportBytesParser | None = None,
                locked_outputs: set[Path] | None = None) -> tuple[dict, bool]:
    started = time.perf_counter()
    compiler = args.compiler.resolve()
    if os.name == "nt" and not compiler.is_file() and Path(str(compiler) + ".exe").is_file():
        compiler = Path(str(compiler) + ".exe")
    if not frontend.ouro1_usable(compiler):
        raise ValueError(f"compiler unavailable: {compiler}")
    companion_proofs = getattr(args, "prepared_companions", None)
    isolated = companion_proofs is not None
    if parse_bytes is None and (not args.check or tool_companions(args.entry)):
        parse_bytes = cached_import_parser()
    units, inputs = tool_inputs(args.entry, compiler, args.fuel, cfg, parse_bytes=parse_bytes)
    process_manifest = WINDOWS_UTF8_MANIFEST if os.name == "nt" and units[-1] in WINDOWS_UTF8_ENTRIES else None
    if process_manifest and sys.getwindowsversion().build < 18362:
        raise ValueError("Windows quality tools require Windows 10 version 1903 or later for UTF-8 argv")
    key = hash_json(inputs)
    logical_output, output = _tool_output_paths(args.output)
    manifest = Path(str(logical_output) + ".sources")
    receipt = Path(str(logical_output) + ".build.json")
    manifest_text = "\n".join(inputs["sources"]) + "\n"
    enabled = cfg.get_bool("cache_enabled")
    cache_root = cfg.path("cache_dir") / "native-tools"
    if isolated:
        # The scheduler owns the output directory and its cache namespace.
        cache_root /= "s-" + hash_json(os.path.normcase(str(output.parent)))[:16]
    artifact_root = cache_root if enabled else companion_proofs
    artifact_directory = artifact_root / key if artifact_root is not None else None

    def installed_sources_current() -> bool:
        if output != logical_output and logical_output.exists():
            return False
        try:
            return manifest.read_text(encoding="utf-8") == manifest_text
        except (OSError, UnicodeError):
            return False

    def installed_tool() -> dict | None:
        if artifact_directory is None or not (enabled or args.check) or not installed_sources_current():
            return None
        installed = complete_tool(output, receipt, key, artifact_directory, cfg, inputs, isolated=isolated,
                                  parse_bytes=parse_bytes)
        return installed if installed is not None and installed_sources_current() else None

    with ExitStack() as locks:
        if locked_outputs is None and not args.check:
            destinations = _tool_outputs(units[-1], logical_output)
            owners: dict[Path, tuple[str, Path]] = {}
            locked_outputs = set()
            for entry, logical, executable in destinations:
                identity = (entry, logical)
                for path in _tool_output_files(logical, executable):
                    if owners.setdefault(path, identity) != identity:
                        raise ValueError(f"conflicting tool output or receipt: {path}")
                locked_outputs.add(executable)
            if not enabled:
                cache_dir = cfg.path("cache_dir").resolve()
                work_dir = (companion_proofs if companion_proofs is not None else
                            cfg.path("build_dir") / "native-tools-uncached")
                if (work_dir.resolve().is_relative_to(cache_dir)
                        or any(logical.is_relative_to(cache_dir) or executable.is_relative_to(cache_dir)
                               for _entry, logical, executable in destinations)):
                    locks.enter_context(build.cache_access(cache_dir))
            # A shared order prevents deadlocks between requests with common companions.
            lock_group: set[tuple[int, int]] | None = set() if os.name != "nt" and len(locked_outputs) > 1 else None
            for executable in sorted(locked_outputs, key=_output_lock_order):
                locks.enter_context(build.cache_access(executable, exclusive=True,
                                                       lock_suffix=OUTPUT_LOCK_SUFFIX, resolve_target=False,
                                                       lock_group=lock_group))
        if locked_outputs is not None and output not in locked_outputs:
            raise ValueError(f"tool output path changed during preparation: {output}")

        installed = installed_tool() if args.check else None
        current = installed is not None
        cache_changed = False
        for companion in tool_companions(units[-1]):
            # Validate companion source, compiler, configuration, and binary identity
            # even when OURO_REUSE_EXISTING_COMPANION is set.
            companion_args = argparse.Namespace(**{**vars(args), "entry": companion[0],
                                                  "output": output.parent / companion[1],
                                                  "check": args.check or isolated})
            companion_report, companion_changed = _build_tool(companion_args, cfg, parse_bytes=parse_bytes,
                                                               locked_outputs=locked_outputs)
            cache_changed = cache_changed or companion_changed
            if args.check:
                current = current and companion_report["current"]
            elif isolated and not companion_report["current"]:
                raise ValueError(f"prepared companion evidence differs: {companion[0]}")
        if args.check:
            if current and installed is not None:
                try:
                    current = installed_sources_current() and sha256_file(output) == installed["binary_sha256"]
                except OSError:
                    current = False
            return {"current": current, "key": key}, False

        # Cache evidence can be read-only for an installed hit.
        installed = installed_tool()
        if installed is None and enabled and artifact_directory is not None:
            locks.enter_context(build.cache_access(artifact_directory / "build", exclusive=True))
            installed = installed_tool()
        output.parent.mkdir(parents=True, exist_ok=True)
        report = dict(installed) if installed is not None else {"kind": KIND, "key": key, "inputs": inputs}
        report["cache"] = "installed-hit"
        if installed is None:
            if artifact_directory is None:
                work_root = cfg.path("build_dir") / "native-tools-uncached"
                work_root.mkdir(parents=True, exist_ok=True)
                workspace = tempfile.TemporaryDirectory(prefix="build-", dir=work_root)
            else:
                workspace = nullcontext(artifact_directory)
            with workspace as temporary:
                directory = Path(temporary)
                directory.mkdir(parents=True, exist_ok=enabled or artifact_directory is None)
                binary = directory / ("tool.exe" if os.name == "nt" else "tool")
                metadata = directory / "tool.json"
                cached = (complete_tool(binary, metadata, key, directory, cfg, inputs, isolated=isolated,
                                        parse_bytes=parse_bytes) if enabled else None)
                if cached is not None:
                    report = dict(cached)
                report["cache"] = "hit" if cached is not None else "miss"
                if report["cache"] == "miss":
                    metadata.unlink(missing_ok=True)
                    generated = directory / "tool.gen.c"
                    report["emission_cache"] = prepare_emission(
                        compiler, units, args.fuel, generated, cfg, inputs, cache_enabled=enabled,
                        parse_bytes=parse_bytes)
                    generated_hash = sha256_file(generated)
                    shard_sources, shard_report = build.GCS.materialize_generated_c_shards(
                        frontend_c=None, backend_c=generated, out_dir=directory / "generated-c-shards",
                        label_prefix="native-tool", cache_enabled=enabled, backend_group_size=SHARD_GROUP_SIZE,
                        backend_export_suffix="", report_path=directory / "generated-c-shards-report.json")
                    if generated_hash != sha256_file(generated):
                        raise ValueError("generated tool changed during sharding")
                    linked = directory / "tool.link.exe" if process_manifest else binary
                    # Use one target identity for common runtime sources. The
                    # existing driver checks compiler flags, depfiles and hashes.
                    report["build"] = build.build_c_executable(
                        cfg, name="native-tool", sources=[*shard_sources,
                                                           *((name, ROOT / name) for name in RUNTIME)],
                        output=linked,
                        object_dir=tool_object_dir(cfg, inputs, directory, isolated=isolated),
                        include_dirs=[ROOT / "runtime"], extra_cflags=EXTRA_CFLAGS,
                        jobs=_c_worker_count(cfg, explicit_jobs=getattr(args, "jobs", None) is not None),
                        generated_c_shards=shard_report,
                    )
                    if process_manifest:
                        publish(linked, binary)
                        embed_windows_manifest(binary, process_manifest)
                    report.update(generated_sha256=generated_hash,
                        shard_manifest_sha256=sha256_file(directory / "generated-c-shards/generated-c-shards.manifest.json"),
                        binary_sha256=sha256_file(binary))
                    if not build_artifacts_current(directory, cfg, inputs, report, binary, isolated=isolated,
                                                   parse_bytes=parse_bytes):
                        raise ValueError("generated tool/shard/object/dependency/link evidence differs after build")
                if tool_inputs(args.entry, compiler, args.fuel, cfg, parse_bytes=parse_bytes)[1] != inputs:
                    raise ValueError("tool source/compiler/runtime/build configuration changed during preparation")
                if report["cache"] == "miss":
                    write_json_atomic(metadata, report)
                publish(binary, output)
            build.write_text_atomic(manifest, manifest_text)
        if output != logical_output:
            # An old extensionless host wrapper would shadow the native .exe in
            # Git Bash. Remove only that exact former output after native success.
            logical_output.unlink(missing_ok=True)
        # Legacy shell launchers use mtime only as a startup hint. Refresh that hint
        # after the full content check, without recompiling a restored identical tool.
        newest = max((ROOT / name).stat().st_mtime_ns for name in inputs["sources"])
        if output.stat().st_mtime_ns < newest:
            os.utime(output, ns=(output.stat().st_atime_ns, newest))
        if tool_inputs(args.entry, compiler, args.fuel, cfg, parse_bytes=parse_bytes)[1] != inputs:
            raise ValueError("tool source/compiler/runtime/build configuration changed before completion")
        if sha256_file(output) != report["binary_sha256"]:
            raise ValueError(f"published tool binary changed before completion: {output}")
        report["elapsed_s"] = round(time.perf_counter() - started, 6)
        write_json_atomic(receipt, report)
    print(f"BUILD_TOOL_CACHE: {report['cache']} key={key} elapsed_s={report['elapsed_s']}")
    print(f"BUILD_TOOL: OK {output}")
    return report, cache_changed or (enabled and report["cache"] == "miss")


def verify_published_tool(args: argparse.Namespace, *,
                          parse_bytes: frontend.ImportBytesParser | None = None) -> dict:
    cfg = build.load_config(args)
    compiler = args.compiler.resolve()
    if os.name == "nt" and not compiler.is_file():
        compiler = compiler.with_name(compiler.name + ".exe")
    if not frontend.ouro1_usable(compiler):
        raise ValueError(f"compiler unavailable: {compiler}")
    if parse_bytes is None:
        parse_bytes = cached_import_parser()

    def verify(entry: str, output: Path) -> str:
        _, inputs = tool_inputs(entry, compiler, args.fuel, cfg, parse_bytes=parse_bytes)
        key = hash_json(inputs)
        binary = output.with_name(output.name + ".exe") if os.name == "nt" and output.suffix != ".exe" else output
        if output != binary and output.exists():
            raise ValueError(f"prepared binary is shadowed: {output}")
        receipt, manifest = (output.with_name(output.name + suffix) for suffix in (".build.json", ".sources"))
        manifest_text = "\n".join(inputs["sources"]) + "\n"
        if (not complete_binary(binary, receipt, key, inputs=inputs)
                or manifest.read_text(encoding="utf-8") != manifest_text):
            raise ValueError(f"prepared tool receipt differs from current {entry}: {output}")
        for companion_entry, name in tool_companions(entry):
            verify(companion_entry, output.parent / name)
        return key

    return {"current": True, "key": verify(args.entry, args.output)}


def build_requests(args: argparse.Namespace) -> list[argparse.Namespace]:
    """Validate the whole request list before building; never alias outputs.

    Batching shares the interpreter and import parser. Each tool rereads its inputs.
    Tools remain sequential and each uses the ordinary fail-closed builder.
    """
    pairs = args.tool
    if pairs:
        if args.entry is not None or args.output is not None:
            raise ValueError("use either ENTRY OUTPUT or repeated --tool ENTRY OUTPUT")
    elif args.entry is not None and args.output is not None:
        pairs = [(args.entry, str(args.output))]
    else:
        raise ValueError("require ENTRY OUTPUT or at least one --tool ENTRY OUTPUT")
    requests: dict[tuple[str, str], argparse.Namespace] = {}
    owners: dict[str, tuple[str, str]] = {}

    def claim(entry: str, destination: Path) -> tuple[str, str]:
        output, executable = _tool_output_paths(destination)
        identity = (entry, os.path.normcase(str(output)))
        for path in _tool_output_files(output, executable):
            key = os.path.normcase(str(path))
            if key in owners and owners[key] != identity:
                raise ValueError(f"conflicting tool output or receipt: {path}")
            owners[key] = identity
        for companion in tool_companions(entry):
            claim(companion[0], executable.parent / companion[1])
        return identity

    for entry, output in pairs:
        if not entry or not output or "\0" in entry or "\0" in output:
            raise ValueError("tool entry and output must be nonempty paths without NUL")
        source = Path(os.path.normpath(entry.replace("\\", "/")))
        if source.is_absolute() and source.is_relative_to(ROOT):
            source = source.relative_to(ROOT)
        destination = Path(output).resolve()
        identity = claim(source.as_posix(), destination)
        requests.setdefault(identity, argparse.Namespace(**{
            **vars(args), "entry": source.as_posix(), "output": destination,
        }))
    if args.batch_report is not None:
        report = args.batch_report.resolve()
        if os.path.normcase(str(report)) in owners:
            raise ValueError("batch report conflicts with a tool output or receipt")
        if any(report == (ROOT / request.entry).resolve() for request in requests.values()):
            raise ValueError("batch report would overwrite a tool source")
    return list(requests.values())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("entry", nargs="?")
    parser.add_argument("output", nargs="?", type=Path)
    parser.add_argument("--tool", nargs=2, action="append", metavar=("ENTRY", "OUTPUT"),
                        help="prepare several tools in one process; repeat for each tool")
    parser.add_argument("--batch-report", type=Path, help="write preparation results as JSON")
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--fuel", type=int, default=60000)
    check = parser.add_mutually_exclusive_group()
    check.add_argument("--check", action="store_true", help="check installed content without building")
    check.add_argument("--verify-published", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--prepared-companions", type=Path, help=argparse.SUPPRESS)
    build.add_common(parser)
    args = parser.parse_args(argv)
    if args.fuel < 1:
        parser.error("--fuel must be positive")
    if args.verify_published and args.prepared_companions is not None:
        parser.error("--verify-published cannot be combined with --prepared-companions")
    try:
        requests = build_requests(args)
    except ValueError as exc:
        parser.error(str(exc))
    started = time.perf_counter()
    results: list[dict] = []

    def report(status: str, error: str | None = None) -> None:
        if args.batch_report is not None:
            write_json_atomic(args.batch_report, {
                "kind": "ouro.native-tool-prepare.v1", "status": status,
                "pass": status == "PASS", "check_only": args.check or args.verify_published,
                "elapsed_s": round(time.perf_counter() - started, 6),
                "requested": len(requests), "completed": len(results),
                "tools": results, "error": error,
            })

    try:
        # Invalidate an older successful report before any work can fail.
        report("RUNNING")
        configure_native_stack()
        operation = verify_published_tool if args.verify_published else build_tool
        parse_bytes = cached_import_parser() if len(requests) > 1 else None
        for request in requests:
            result = operation(request, parse_bytes=parse_bytes)
            results.append({"entry": request.entry, "output": str(request.output), "result": result})
        current = not args.check or all(row["result"]["current"] for row in results)
        report("PASS" if current else "STALE")
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        try:
            report("FAIL", str(exc))
        except OSError as report_error:
            print(f"BUILD_TOOL: FAIL report: {report_error}", file=sys.stderr)
        print(f"BUILD_TOOL: FAIL {exc}", file=sys.stderr)
        return 1
    return int(not current)


if __name__ == "__main__":
    raise SystemExit(main())
