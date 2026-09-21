#!/usr/bin/env python3
"""Content-addressed native tool builds; acceptance still belongs to the suites."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
import sysconfig
import tempfile
import time
from contextlib import nullcontext
from pathlib import Path

import frontend_regen as frontend
import ouro_build as build
from repo_support import configure_native_stack, hash_json, read_json_object_or_none, sha256_file, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
KIND = "ouro.native-tool-build.v1"
RUNTIME = ("runtime/ouro_rt.c", "runtime/ouro_io.c", "runtime/ouro_prog_main.c",
           "runtime/frontend_link.c")
BUILD_INPUTS = (
    "scripts/build_tool.sh", "scripts/native_tool_build.py", "scripts/ouro_build.py",
    "scripts/frontend_regen.py", "scripts/selfhost_module_cache.py", "scripts/pack_frontend.py",
    "scripts/repo_support.py", "scripts/ouro_seal.py", "scripts/python.sh",
)

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
    ("cg_s_snapshot_request", "ouro_wrap_quality_io", ("tools/clippy/session.ouro",)),
    ("cg_s_emit_request", "ouro_wrap_quality_io", ("tools/clippy/session.ouro",)),
    ("cg_s_epoch_request", "ouro_wrap_quality_io", ("tools/clippy/session.ouro",)),
    ("cg_s_sample_heap", "ouro_wrap_quality_heap", ("tools/clippy/session.ouro",)),
    ("cm_load_file", "ouro_wrap_quality_parse", ("tools/clippy/semantic_unit.ouro",)),
    ("cm_parse", "ouro_wrap_quality_pure", ("tools/clippy/structural_frontend.ouro",)),
    ("cm_contract_for", "ouro_wrap_quality_pure", ("tools/clippy/semantic_registry.ouro",)),
    ("cm_validate_contract_bindings", "ouro_wrap_quality_pure", ("tools/clippy/semantic_registry.ouro",)),
    ("cm_build_apis", "ouro_wrap_quality_pure", ("tools/clippy/semantic_registry.ouro",)),
    ("cg_wire_scan_request", "ouro_wrap_quality_pure", ("tools/clippy/session_wire.ouro",)),
    ("cg_scan_chunk_request", "ouro_wrap_quality_io", ("tools/clippy/main.ouro",)),
    ("st_scan_request", "ouro_wrap_quality_io", ("tools/strict/fixtures.ouro",)),
    ("st_scan_def_span", "ouro_wrap_quality_pure", ("tools/strict/scan.ouro",)),
    ("st_load_cfg", "ouro_wrap_quality_io", ("tools/strict/main.ouro",)),
    ("st_registry_issues", "ouro_wrap_quality_io", ("tools/strict/fixtures.ouro",)),
    ("st_fixture_issues", "ouro_wrap_quality_io", ("tools/strict/fixtures.ouro",)),
    ("lower_recheck_program", "ouro_wrap_lower_recheck_program",
     ("compiler/native/lower_boundary.ouro",)),
    ("managed_global_function", "ouro_wrap_managed_global_function",
     ("compiler/native/managed_terms.ouro", "compiler/native/managed_terms_stdio.ouro")),
    ("mir_check_bounds", "ouro_wrap_mir_check_bounds", ("compiler/native/mir.ouro",)),
    ("mir_check_function", "ouro_wrap_mir_check_function", ("compiler/native/mir.ouro",)),
    ("mir_reachable", "ouro_wrap_mir_reachable", ("compiler/native/mir_flow.ouro",)),
    ("codegen_prepare_step", "ouro_wrap_codegen_prepare_step", ("compiler/native/codegen.ouro",)),
    ("x64_encode", "ouro_wrap_x64_encode", ("compiler/native/x64.ouro",)),
    ("codegen_assemble", "ouro_wrap_codegen_assemble", ("compiler/native/codegen_assembly.ouro",)),
    ("mir_live_facts", "ouro_wrap_mir_live_facts", ("compiler/native/mir_live.ouro",)),
    ("mir_live_summary_step", "ouro_wrap_mir_live_summary_step", ("compiler/native/mir_live.ouro",)),
    ("codegen_parts", "ouro_wrap_codegen_parts", ("compiler/native/codegen_model.ouro",)),
    ("codegen_live_instructions", "ouro_wrap_codegen_live_instructions", ("compiler/native/codegen_ops.ouro",)),
    ("codegen_instruction", "ouro_wrap_codegen_instruction", ("compiler/native/codegen_ops.ouro",)),
    ("codegen_block", "ouro_wrap_codegen_block", ("compiler/native/codegen_ops.ouro",)),
    ("codegen_body", "ouro_wrap_codegen_body", ("compiler/native/codegen.ouro",)),
    ("mir_gc_infer", "ouro_wrap_mir_gc_infer", ("compiler/native/mir_gc.ouro",)),
    ("mir_gc_annotate", "ouro_wrap_mir_gc_annotate", ("compiler/native/mir_gc.ouro",)),
    ("mir_gc_check", "ouro_wrap_mir_gc_check", ("compiler/native/mir_gc.ouro",)),
    ("pe_run_byte_check", "ouro_wrap_pe_run_byte_check", ("compiler/native/pe_model.ouro",)),
    ("pe_plan_fixups", "ouro_wrap_pe_plan_fixups", ("compiler/native/pe_fixups.ouro",)),
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


def tool_inputs(entry: str, compiler: Path, fuel: int, cfg: build.ResolvedConfig) -> tuple[list[str], dict]:
    # Shell callers resolve inputs against their own cwd. Repository inputs
    # keep one relative identity in content keys and portable source manifests.
    source = Path(os.path.normpath(entry.replace("\\", "/")))
    if source.is_absolute() and source.is_relative_to(ROOT):
        source = source.relative_to(ROOT)
    roots = tool_roots(source.as_posix())
    groups = frontend.collect_units_many(roots)
    units = groups[source.as_posix()]
    if not units:
        raise ValueError("empty source collection")
    companion_units = [unit for root in roots[1:] for unit in groups[root]]
    sources = dict.fromkeys([*units, *companion_units, *BUILD_INPUTS, *RUNTIME,
                            *(path.relative_to(ROOT).as_posix() for path in sorted((ROOT / "runtime").glob("*.h")))])
    cc = build.choose_cc(cfg)
    cc_path = Path(shutil.which(cc) or cc).resolve()
    inputs = {
        "kind": KIND, "entry": units[-1], "fuel": fuel,
        "compiler_sha256": sha256_file(compiler),
        "cc": build.compiler_id(cc), "cc_sha256": sha256_file(cc_path),
        # platform.machine() is empty on Windows when the harness scrubs
        # PROCESSOR_ARCHITECTURE; Python's build platform remains stable.
        "platform": sys.platform, "machine": sysconfig.get_platform(),
        "cflags": build.profile_cflags(cfg), "link_flags": build.host_link_flags(),
        "environment": {name: os.environ.get(name, "") for name in
                        ("CPATH", "C_INCLUDE_PATH", "LIBRARY_PATH", "SDKROOT", "MACOSX_DEPLOYMENT_TARGET", "SOURCE_DATE_EPOCH")},
        "sources": {name: sha256_file(ROOT / name) for name in sources},
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


def hook_named_getter(text: str, export_name: str, wrapper: str) -> str:
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
    text, n = re.subn(pattern, replacement, text, count=1)
    if n != 1:
        raise RuntimeError(f"could not hook {export_name} getter {getter}")
    # IO lifetimes must cover execution of the thunk, not its construction.
    # This header is already part of the builder's hashed runtime inputs.
    decl = ('#include "ouro_quality_scope.h"\n' if wrapper in {"ouro_wrap_quality_io", "ouro_wrap_quality_heap", "ouro_wrap_quality_pure"}
            else f"ouro_v *{wrapper}(ouro_v *raw);\n")
    if decl not in text:
        text = text.replace('#include "ouro_rt.h"\n', '#include "ouro_rt.h"\n' + decl, 1)
    return text


def hook_checked_units_getter(text: str) -> str:
    """Replace the checked-units entry while preserving its strict host path."""
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
    text, n = re.subn(pattern, replacement, text, count=1)
    if n != 1:
        raise RuntimeError(f"could not hook compile_checked_units getter {getter}")
    if 'ouro_fe_compile_checked_units_clos' not in text.split("static ouro_v *ouro_g", 1)[0]:
        text = text.replace(
            '#include "ouro_rt.h"\n',
            '#include "ouro_rt.h"\n'
            "ouro_v *ouro_fe_compile_checked_units_clos(void);\n",
            1,
        )
    return text


def hook_compile_checked_units(generated: Path, units: list[str] | tuple[str, ...] = ()) -> None:
    """Hook relevant host seams; malformed or missing required exports fail."""
    text = generated.read_text(encoding="utf-8")
    exports = set(re.findall(r'case\s+\d+:\s*return\s+"([^"]+)"', text))
    sources = {os.path.relpath(ROOT / unit, ROOT).replace("\\", "/") for unit in units}
    if "compile_checked_units" in exports or "compiler/driver.ouro" in sources:
        text = hook_checked_units_getter(text)
    for name, wrapper, owners in HOST_HOOKS:
        if name in exports or sources.intersection(owners):
            text = hook_named_getter(text, name, wrapper)
    generated.write_text(text, encoding="utf-8")


def complete_binary(binary: Path, metadata: Path, key: str) -> bool:
    data = read_json_object_or_none(metadata)
    if data is None or data.get("kind") != KIND or data.get("key") != key:
        return False
    try:
        return (binary.is_file() and binary.stat().st_size > 0
                and os.access(binary, os.X_OK)
                and data.get("binary_sha256") == sha256_file(binary))
    except OSError:
        return False


def emit(compiler: Path, units: list[str], fuel: int, generated: Path) -> None:
    token = f"{os.getpid()}.{time.time_ns()}"
    temporary = generated.with_name(f"emit.{token}.c")
    error_log = generated.with_name(f"emit.{token}.err")
    argv = [*frontend.ouro1_cmd(compiler), units[-1], str(fuel)]
    for unit in units:
        argv.extend(("--unit", unit))
    env = dict(os.environ, OURO_EMIT_IO_SHIMS="1")
    env["WSLENV"] = (env.get("WSLENV", "") + ":OURO_EMIT_IO_SHIMS").lstrip(":")
    try:
        with temporary.open("wb") as output, error_log.open("wb") as errors:
            result = subprocess.run(argv, cwd=ROOT, env=env, stdout=output, stderr=errors, check=False)
        if result.returncode != 0 or temporary.stat().st_size == 0:
            raise RuntimeError(f"emit failed rc={result.returncode}: {error_log.read_text(encoding='utf-8', errors='replace')}")
        subprocess.run([sys.executable, str(ROOT / "scripts/pack_frontend.py"), "--uniquify-only", str(temporary)],
                       cwd=ROOT, check=True)
        hook_compile_checked_units(temporary, units)
        os.replace(temporary, generated)
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


def build_tool(args: argparse.Namespace) -> dict:
    started = time.perf_counter()
    cfg = build.load_config(args)
    compiler = args.compiler.resolve()
    if os.name == "nt" and not compiler.is_file() and Path(str(compiler) + ".exe").is_file():
        compiler = Path(str(compiler) + ".exe")
    if not frontend.ouro1_usable(compiler):
        raise ValueError(f"compiler unavailable: {compiler}")
    units, inputs = tool_inputs(args.entry, compiler, args.fuel, cfg)
    process_manifest = WINDOWS_UTF8_MANIFEST if os.name == "nt" and units[-1] in WINDOWS_UTF8_ENTRIES else None
    if process_manifest and sys.getwindowsversion().build < 18362:
        raise ValueError("Windows quality tools require Windows 10 version 1903 or later for UTF-8 argv")
    key = hash_json(inputs)
    output = args.output.resolve()
    logical_output = output
    manifest = Path(str(output) + ".sources")
    receipt = Path(str(output) + ".build.json")
    if os.name == "nt" and output.suffix != ".exe":
        output = Path(str(output) + ".exe")
    manifest_text = "\n".join(inputs["sources"]) + "\n"
    enabled = cfg.get_bool("cache_enabled")
    current = enabled and complete_binary(output, receipt, key)
    if output != logical_output and logical_output.exists():
        current = False
    if current:
        try:
            current = manifest.read_text(encoding="utf-8") == manifest_text
        except (OSError, UnicodeError):
            current = False
    for companion in tool_companions(units[-1]):
        # Existence is not provenance. The legacy reuse environment flag must
        # not bypass source/compiler/config/binary validation for a companion.
        companion_args = argparse.Namespace(**{**vars(args), "entry": companion[0],
                                              "output": output.parent / companion[1]})
        companion_report = build_tool(companion_args)
        if args.check:
            current = current and companion_report["current"]
    if args.check:
        return {"current": current, "key": key}

    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"kind": KIND, "key": key, "inputs": inputs, "cache": "installed-hit"}
    if not current:
        cache_root = cfg.path("cache_dir") / "native-tools"
        work_root = cache_root if enabled else cfg.path("build_dir") / "native-tools-uncached"
        work_root.mkdir(parents=True, exist_ok=True)
        # Each uncached build owns fresh objects and cannot accidentally hit an
        # incremental object/link stamp. Cached entries are published atomically.
        workspace = nullcontext(None) if enabled else tempfile.TemporaryDirectory(prefix="build-", dir=work_root)
        with workspace as temporary:
            directory = cache_root / key if enabled else Path(temporary)
            directory.mkdir(parents=True, exist_ok=True)
            binary = directory / ("tool.exe" if os.name == "nt" else "tool")
            metadata = directory / "tool.json"
            report["cache"] = "hit" if enabled and complete_binary(binary, metadata, key) else "miss"
            if report["cache"] == "miss":
                generated = directory / "tool.gen.c"
                emit(compiler, units, args.fuel, generated)
                linked = directory / "tool.link.exe" if process_manifest else binary
                # Use one target identity for common runtime sources. The
                # existing driver checks compiler flags, depfiles and hashes.
                report["build"] = build.build_c_executable(
                    cfg, name="native-tool", sources=[("generated", generated),
                                                       *((name, ROOT / name) for name in RUNTIME)],
                    output=linked,
                    object_dir=(cache_root / "obj" / hash_json({name: inputs[name] for name in
                                ("cc", "cc_sha256", "platform", "machine", "cflags", "environment")})[:16])
                    if enabled else directory / "objects",
                    include_dirs=[ROOT / "runtime"], extra_cflags=[
                        "-Werror=implicit-function-declaration",
                        "-DOURO_FE_FLAT_EXPORTS",
                    ],
                    jobs=min(2, build.jobs_value(cfg)),
                )
                if process_manifest:
                    publish(linked, binary)
                    embed_windows_manifest(binary, process_manifest)
                write_json_atomic(metadata, {"kind": KIND, "key": key, "binary_sha256": sha256_file(binary)})
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
    report.update(binary_sha256=sha256_file(output), elapsed_s=round(time.perf_counter() - started, 6))
    write_json_atomic(receipt, report)
    if enabled and report["cache"] == "miss":
        build.trim_cache(cfg)
    print(f"BUILD_TOOL_CACHE: {report['cache']} key={key} elapsed_s={report['elapsed_s']}")
    print(f"BUILD_TOOL: OK {output}")
    return report


def build_requests(args: argparse.Namespace) -> list[argparse.Namespace]:
    """Validate the whole request list before building; never alias outputs.

    Batching amortizes the interpreter/shell startup, not content validation.
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

    def claim(entry: str, output: Path) -> tuple[str, str]:
        identity = (entry, os.path.normcase(str(output)))
        paths = [output, Path(str(output) + ".sources"), Path(str(output) + ".build.json")]
        if os.name == "nt" and output.suffix != ".exe":
            paths.append(Path(str(output) + ".exe"))
        for path in paths:
            key = os.path.normcase(str(path))
            if key in owners and owners[key] != identity:
                raise ValueError(f"conflicting tool output or receipt: {path}")
            owners[key] = identity
        for companion in tool_companions(entry):
            claim(companion[0], output.parent / companion[1])
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
    parser.add_argument("--check", action="store_true", help="check installed content without building")
    build.add_common(parser)
    args = parser.parse_args(argv)
    if args.fuel < 1:
        parser.error("--fuel must be positive")
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
                "pass": status == "PASS", "check_only": args.check,
                "elapsed_s": round(time.perf_counter() - started, 6),
                "requested": len(requests), "completed": len(results),
                "tools": results, "error": error,
            })

    try:
        # Invalidate an older successful report before any work can fail.
        report("RUNNING")
        configure_native_stack()
        for request in requests:
            result = build_tool(request)
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
