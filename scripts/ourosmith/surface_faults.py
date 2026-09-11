"""Build source mutants outside the tree and require specific surface failures."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

from ourosmith import ROOT, generator_hash
from ourosmith.host import build_command, compiler_path, tool_entry
from ourosmith.report import Report
from ourosmith.surface import gen
from ourosmith.surface.mutate import mutations
from ourosmith.surface.run import SurfaceRunner


def probe(fault, work, *, timeout_s, memory_mb, overrides=None):
    report = Report(profile="faults", generator_hash=generator_hash(), seeds=[1], command=f"fault {fault.id}")
    runner = SurfaceRunner(report, work, [1], timeout=timeout_s, memory_mb=memory_mb,
                           shrink_budget=0, overrides=overrides)
    runner.seed, runner.case_id = 1, "surface-1"
    if fault.case == "positive":
        value = {"ast": gen.generate(1, 3).json()}
    elif fault.case.startswith("mutation:"):
        name = fault.case.split(":", 1)[1]
        mutation = next(m for m in mutations(1) if m.name == name)
        value = {**asdict(mutation), "mutation": name}
    else:
        value = {"recipe": fault.case.split(":", 1)[1]}
    runner.replay_input(value)
    report.write(work / "report.json")
    return report


def copy_cone(entry, scratch):
    from frontend_regen import collect_units

    units = collect_units(entry)
    for filename in {entry, *units}:
        destination = scratch / "source" / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / filename, destination)
    return scratch / "source" / entry, [scratch / "source" / unit for unit in units]


def build_frontend(scratch, compiler):
    """Executed in a bounded child: regenerate only source, then mechanically pack."""
    import frontend_regen as fe
    import stage_loop as sl
    from ourosmith.native import digest

    scratch = Path(scratch)
    compiler = compiler_path(compiler)
    producer_hash = digest(compiler)
    work = scratch / "fe"
    driver = scratch / "driver.c"
    fe.regenerate(ouro1=compiler, fuel="16000", out_c=driver, work=work,
                  cache_root=scratch / "cache", cache_enabled=False,
                  report_path=scratch / "regen.json", jobs=1)
    entry = scratch / "source/compiler/file_elab.ouro"
    args = [compiler.as_posix(), "--module", "_fc", entry.as_posix(), "16000"]
    for unit in fe.collect_units(entry.as_posix()):
        args.extend(["--unit", unit])
    with (work / "fc.c").open("w", encoding="utf-8", newline="\n") as output:
        subprocess.run(args, cwd=ROOT, stdout=output, check=True)
    fe.run_pack([(tag, work / filename) for tag, _suffix, _entry, filename in fe.FRONTEND_TUS], driver)
    build_cfg = sl.OB.load_config(argparse.Namespace(build_dir=str(scratch / "build"),
        c_build_dir=str(scratch / "c"), cache_dir=str(scratch / "cache"),
        cache_enabled=False, ccache="disabled", jobs=1))
    cfg = replace(sl.build_config(argparse.Namespace(promote=False)), work=scratch / "build",
                  cache_root=scratch / "cache", cache_enabled=False, fuel="16000", build_cfg=build_cfg)
    backend = scratch / "backend.c"
    sl.emit_backend(compiler, backend, scratch / "backend.err", cfg, 1)
    sl.build_stage_binary(driver, backend, scratch / "ouro1.exe", 1, cfg)
    if digest(compiler) != producer_hash:
        raise ValueError("selected compiler changed while building the frontend mutant")


def build_mutant(fault, scratch, compiler):
    from ourosmith.faults import apply_fault, read_text, write_text

    if fault.target == "analyzer":
        for entry in ("std/io.ouro", "std/format.ouro", *("tools/analyze/" + name + ".ouro"
                       for name in ("ast", "expr_adapt", "minimal", "bounds", "duplication", "dataflow"))):
            copy_cone(entry, scratch)
        target = scratch / "source" / fault.file
        write_text(target, apply_fault(read_text(target), fault))
        return {"source-root": scratch / "source"}
    if fault.target in {"fmt", "lint", "fix", "doc", "lsp", "test", "frontend"}:
        entry = "compiler/file_elab.ouro" if fault.target == "frontend" else tool_entry(fault.target)
        copied_entry, _units = copy_cone(entry, scratch)
        target = scratch / "source" / fault.file
        if not target.is_file():
            raise RuntimeError(f"fault source is outside the compiled import cone: {fault.file}")
        write_text(target, apply_fault(read_text(target), fault))
        if fault.target == "frontend":
            code = "import sys; sys.path.insert(0,sys.argv[1]); from ourosmith.surface_faults import build_frontend; build_frontend(sys.argv[2], sys.argv[3])"
            argv = [sys.executable, "-c", code, str(ROOT / "scripts"), str(scratch), str(compiler)]
            key, output = "ouro1", scratch / "ouro1.exe"
        else:
            key, output = "ouro-" + fault.target, scratch / ("ouro-" + fault.target + ".exe")
            argv = [sys.executable, "-B", str(ROOT / "scripts/native_tool_build.py"),
                    copied_entry.as_posix(), output.as_posix(), "--compiler", str(compiler),
                    "--jobs", "1", "--ccache", "disabled", "--build-dir", str(scratch / "build"),
                    "--cache-dir", str(scratch / "cache")]
        reason = build_command(argv, scratch / "build.log", timeout_s=900)
        if reason or not output.is_file():
            raise RuntimeError(reason or f"mutant executable missing: {output}")
        return {key: output}
    target = scratch / "source" / fault.file
    write_text(target, apply_fault(read_text(ROOT / fault.file), fault))
    if fault.target == "cache":
        shutil.copy2(ROOT / "scripts/repo_support.py", target.with_name("repo_support.py"))
        return {"module-cache": target}
    if fault.target == "runtime":
        return {"runtime-printer": target}
    if fault.target == "wrapper":
        return {"ouro-wrapper": target}
    raise ValueError(f"unknown surface fault target {fault.target}")


def run_surface_fault(fault, out, *, timeout_s, memory_mb, overrides):
    from ourosmith.faults import FaultResult, StaleFault, caught_by, detected, remove_scratch

    started = time.perf_counter()
    scratch = ROOT / "_build/smith/mutants" / fault.id
    remove_scratch(scratch)
    baseline = probe(fault, scratch / "baseline", timeout_s=timeout_s, memory_mb=memory_mb, overrides=overrides)
    baseline.write(out / "surface-baseline" / fault.id / "report.json")
    if not baseline.passed:
        return FaultResult(fault, "baseline-dirty", detail="unmutated surface property fails", seconds=time.perf_counter() - started)
    try:
        mutated = build_mutant(fault, scratch, overrides["ouro1"])
    except StaleFault as exc:
        return FaultResult(fault, "stale", detail=str(exc), seconds=time.perf_counter() - started)
    except (OSError, ValueError, RuntimeError) as exc:
        return FaultResult(fault, "unbuildable", detail=str(exc), seconds=time.perf_counter() - started)
    report = probe(fault, scratch / "run", timeout_s=timeout_s, memory_mb=memory_mb,
                   overrides={**overrides, **mutated})
    report.write(out / "surface" / fault.id / "report.json")
    # An unrelated crash or malformed protocol is not evidence that the
    # intended semantic fault was detected by its independent property.
    killed = detected(fault, report)
    status = "killed" if killed else "survived"
    return FaultResult(fault, status, findings=len(report.findings), caught_by=caught_by(report),
                       detail="" if killed else "expected property did not detect the source mutant",
                       seconds=time.perf_counter() - started)
