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

# Each seam is required only when its defining module belongs to this tool.
# A smaller tool may still export a seam; present exports are always checked.
HOST_HOOKS = (
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
    ("codegen_parts", "ouro_wrap_codegen_parts", ("compiler/native/codegen_model.ouro",)),
    ("codegen_live_instructions", "ouro_wrap_codegen_live_instructions", ("compiler/native/codegen_ops.ouro",)),
    ("codegen_instruction", "ouro_wrap_codegen_instruction", ("compiler/native/codegen_ops.ouro",)),
    ("codegen_block", "ouro_wrap_codegen_block", ("compiler/native/codegen_ops.ouro",)),
    ("codegen_body", "ouro_wrap_codegen_body", ("compiler/native/codegen.ouro",)),
    ("mir_gc_infer", "ouro_wrap_mir_gc_infer", ("compiler/native/mir_gc.ouro",)),
    ("mir_gc_annotate", "ouro_wrap_mir_gc_annotate", ("compiler/native/mir_gc.ouro",)),
    ("mir_gc_check", "ouro_wrap_mir_gc_check", ("compiler/native/mir_gc.ouro",)),
    ("pe_run_byte_check", "ouro_wrap_pe_run_byte_check", ("compiler/native/pe_model.ouro",)),
)


def tool_inputs(entry: str, compiler: Path, fuel: int, cfg: build.ResolvedConfig) -> tuple[list[str], dict]:
    units = frontend.collect_units(os.path.normpath(entry).replace("\\", "/"))
    if not units:
        raise ValueError("empty source collection")
    sources = dict.fromkeys([*units, *BUILD_INPUTS, *RUNTIME,
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
    decl = f"ouro_v *{wrapper}(ouro_v *raw);\n"
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
                # Use one target identity for common runtime sources. The
                # existing driver checks compiler flags, depfiles and hashes.
                report["build"] = build.build_c_executable(
                    cfg, name="native-tool", sources=[("generated", generated),
                                                       *((name, ROOT / name) for name in RUNTIME)],
                    output=binary,
                    object_dir=(cache_root / "obj" / hash_json({name: inputs[name] for name in
                                ("cc", "cc_sha256", "platform", "machine", "cflags", "environment")})[:16])
                    if enabled else directory / "objects",
                    include_dirs=[ROOT / "runtime"], extra_cflags=[
                        "-Werror=implicit-function-declaration",
                        "-DOURO_FE_FLAT_EXPORTS",
                    ],
                    jobs=min(2, build.jobs_value(cfg)),
                )
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("entry")
    parser.add_argument("output", type=Path)
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--fuel", type=int, default=60000)
    parser.add_argument("--check", action="store_true", help="check installed content without building")
    build.add_common(parser)
    args = parser.parse_args()
    if args.fuel < 1:
        parser.error("--fuel must be positive")
    try:
        configure_native_stack()
        report = build_tool(args)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"BUILD_TOOL: FAIL {exc}", file=sys.stderr)
        return 1
    return int(args.check and not report["current"])


if __name__ == "__main__":
    raise SystemExit(main())
