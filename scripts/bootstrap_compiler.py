#!/usr/bin/env python3
"""Build a current C-hosted compiler from separately pinned historical inputs.

This host driver freezes bytes, invokes Ouro, compares complete generated C and
publishes the checked successor. It does not interpret or accept Ouro programs.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
from pathlib import Path
import shutil
import sys
import sysconfig
import tempfile

import bootstrap_inputs
import frontend_regen as frontend
from ourosmith.limits import clean_env, run_limited
from repo_support import configure_native_stack, hash_json, read_json_object_or_none, sha256_file, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
KIND = "ouro.current-c-bootstrap.v1"
FUEL = "999999"
MEMORY_MIB = 3072
TIMEOUT_S = 900
HELPERS = (
    "scripts/bootstrap_compiler.py", "scripts/bootstrap_inputs.py", "scripts/ouro_build.py",
    "scripts/generated_c_shards.py", "scripts/frontend_regen.py", "scripts/selfhost_module_cache.py",
    "scripts/pack_frontend.py", "scripts/emit_frontend.sh", "scripts/stage_loop.py", "scripts/stage_loop.sh",
    "scripts/repo_support.py", "scripts/ouro_seal.py", "scripts/native_tool_build.py", "scripts/build_tool.sh",
    "scripts/python.sh", "scripts/ourosmith/__init__.py", "scripts/ourosmith/limits.py",
    "scripts/ourosmith/windows_job.py", "scripts/ourosmith/exec_child.py", "Ouro.seal",
)
RUNTIME = (
    "runtime/bootstrap.c", "runtime/frontend_link.c", "runtime/ouro_rt.c", "runtime/ouro_rt.h",
    "runtime/ouro_host_values.h", "runtime/ouro_io.c", "runtime/ouro_io.h", "runtime/ouro_prog_main.c",
)
ACCEPTANCE_ROOTS = ("std/prelude.ouro", "std/data.ouro", "tools/collect.ouro", "tests/compiler_abi_tests.ouro")
ABI_STDOUT = """PASS lexer/parser/resolver share declarations and intern state
PASS lexer malformed result crosses parser callback
PASS lexer exhaustion crosses parser callback
PASS parser error crosses unit callback
PASS resolver error retains code and missing path
PASS compiler result retains named core
PASS compiler error retains code and detail
PASS lower environment preserves constructor and hint fields
PASS import preprocessing retains registry values
PASS record callback retains nested record model values
PASS preprocessors share successful source value
PASS preprocessor error crosses pipeline callback
COMPILER_ABI: PASS
"""
PROBE = '''import "std/data.ouro";
intrinsic String : Type := "ouro.string";
intrinsic prim_string_index : String -> String -> Maybe Nat := "ouro.string.index";
inductive IndexTag (value : Maybe Nat) : Type :=
  | IndexProof : IndexTag value;

def exact_index : IndexTag (prim_string_index "abc" "b") := IndexProof (Just Nat INDEX);
'''


def fail(message: str):
    raise RuntimeError("BOOTSTRAP: FAIL " + message)


def current_inputs(root: Path, cfg, build) -> dict:
    roots = [source for _tag, _module, source, _file in frontend.FRONTEND_TUS] + ["compiler/backend.ouro"]
    graph = {source: frontend.collect_units(source) for source in [*roots, *ACCEPTANCE_ROOTS]}
    if len(roots) != 15 or any(not units or units[-1] != source for source, units in graph.items()):
        fail("incomplete current source graph")
    paths = {*HELPERS, *RUNTIME, *(name for units in graph.values() for name in units),
             *(path.relative_to(root).as_posix() for path in (root / "runtime").glob("*.h"))}
    cc = build.choose_cc(cfg)
    cc_path = Path(shutil.which(cc) or cc).resolve()
    sources = {name: sha256_file(root / name) for name in sorted(paths)}
    return {"kind": KIND, "roots": roots, "unit_graph": graph, "sources": sources,
        "archive_sha256": sha256_file(root / bootstrap_inputs.ARCHIVE),
        "manifest_sha256": sha256_file(root / bootstrap_inputs.MANIFEST),
        "stage0": {name: sha256_file(root / name) for name in bootstrap_inputs.STAGE0},
        "cc": cc, "cc_executable": str(cc_path), "cc_id": build.compiler_id(cc), "cc_sha256": sha256_file(cc_path),
        "platform": sys.platform, "machine": sysconfig.get_platform(),
        "cflags": build.profile_cflags(cfg), "link_flags": build.host_link_flags(),
        "environment": {name: os.environ.get(name, "") for name in
                        ("CPATH", "C_INCLUDE_PATH", "LIBRARY_PATH", "SDKROOT", "MACOSX_DEPLOYMENT_TARGET", "SOURCE_DATE_EPOCH")}}


def copy_input(source: Path, destination: Path, expected: str) -> None:
    data = source.read_bytes()
    if bootstrap_inputs.digest(data) != expected or sha256_file(source) != expected:
        fail("source changed while freezing " + str(source))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as stream:
        stream.write(data)


def changed_inputs(work: Path, snapshot: dict) -> list[str]:
    return [name for name, digest in snapshot["inputs"].items()
            if not (work / name).is_file() or sha256_file(work / name) != digest]


def current_unchanged(root: Path, selected: dict) -> bool:
    names = {**selected["sources"], **selected["stage0"],
             bootstrap_inputs.ARCHIVE: selected["archive_sha256"], bootstrap_inputs.MANIFEST: selected["manifest_sha256"]}
    return all((root / name).is_file() and sha256_file(root / name) == digest for name, digest in names.items())


def freeze(root: Path, work: Path, selected: dict, cfg) -> dict:
    manifest = bootstrap_inputs.unpack(work / "historical", root)
    original = work / "o"
    for name, digest in selected["sources"].items():
        copy_input(root / name, original / name, digest)
    for role in ("c0", "bridge"):
        destination = work / "historical" / role
        for name in HELPERS:
            copy_input(root / name, destination / name, selected["sources"][name])
    for name, digest in selected["stage0"].items():
        copy_input(root / name, work / "historical/c0" / name, digest)
    # The historical source archive is never copied over the current sources.
    if (original / "compiler/stage0").exists() or not current_unchanged(root, selected):
        fail("current source changed or historical stage0 entered current O")
    for name, value in (("good", "1"), ("bad", "2")):
        (original / ("bootstrap-" + name + ".ouro")).write_text(PROBE.replace("INDEX", value), encoding="utf-8", newline="\n")
    files = {path.relative_to(work).as_posix(): sha256_file(path)
             for directory in (work / "historical", original) for path in sorted(directory.rglob("*")) if path.is_file()}
    snapshot = {"kind": KIND + ".inputs", "key": hash_json(selected), "selected": selected,
        "inputs": files, "config": cfg.values, "bridge_graph": manifest["ordered_unit_graph"],
        "roots": {"c0": "historical/c0", "bridge": "historical/bridge", "p1": "o", "p2": "o"},
        "current_o_projection": "None; every current source is copied byte for byte."}
    write_json_atomic(work / "inputs.json", snapshot)
    return snapshot


def strict_roots(producer: Path, root: Path, roots: list[str], graph: dict, run) -> None:
    for index, source in enumerate(roots):
        units = [part for unit in graph[source] for part in ("--unit", unit)]
        result = run(f"check-{index:02}", [str(producer), "check", source, FUEL, *units], root)
        if result.stdout != "CHECK_OK\n" or result.stderr:
            fail("strict check did not return clean CHECK_OK for " + source)


def compare_generated(first: Path, second: Path) -> dict:
    result = {name: {"p1_sha256": sha256_file(first / name), "p2_sha256": sha256_file(second / name)}
              for name in ("driver_u.c", "backend_u.c")}
    if any(row["p1_sha256"] != row["p2_sha256"] for row in result.values()):
        fail("complete generated frontend/backend C differs between current P1 and P2")
    return result


def chain(work: Path, snapshot: dict, build) -> dict:
    report = {"kind": KIND, "key": snapshot["key"], "inputs_sha256": sha256_file(work / "inputs.json"),
        "workers": 1, "memory_mib": MEMORY_MIB, "timeout_s": TIMEOUT_S, "phases": [], "pass": False}
    selected, producers = snapshot["selected"], {}
    phase, out = "prepare", work

    def save():
        write_json_atomic(work / "report.json", report)

    def run(label, argv, root, *, negative=False):
        if changed_inputs(work, snapshot):
            fail("frozen bootstrap inputs changed before " + label)
        if sha256_file(Path(selected["cc_executable"])) != selected["cc_sha256"]:
            fail("selected C compiler changed before " + label)
        env = clean_env()
        for name in ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", *selected["environment"]):
            if name in os.environ:
                env[name] = os.environ[name]
        values = {**snapshot["config"], "cc": selected["cc_executable"], "jobs": 1, "cache_enabled": False, "ccache": "disabled",
                  "build_dir": str(out / "b"), "c_build_dir": str(out / "c"), "cache_dir": str(out / "k")}
        for key, name in build.ENV_MAP.items():
            value = values[key]
            env[name] = ("1" if value else "0") if isinstance(value, bool) else str(value)
        env.update(PYTHONDONTWRITEBYTECODE="1", OURO_FRONTEND_JOBS="1", OURO1_CHECK_FUEL=FUEL)
        if snapshot["config"]["verbosity"] != "quiet":
            print(f"BOOTSTRAP: {phase}/{label}", flush=True)
        result = run_limited(argv, cwd=root, env=env, timeout_s=TIMEOUT_S, memory_mb=MEMORY_MIB)
        row = {"label": label, "cwd": str(root), **dataclasses.asdict(result)}
        for stream in ("stdout", "stderr"):
            path = out / (label + "." + stream)
            path.write_text(getattr(result, stream), encoding="utf-8", newline="\n")
            row[stream], row[stream + "_sha256"] = path.relative_to(work).as_posix(), sha256_file(path)
        report["phases"][-1]["commands"].append(row)
        save()
        if not result.ok and not (negative and result.status == "ok" and result.returncode == 1):
            fail(f"{phase}/{label}: {result.classify()} exit={result.returncode}; see {out}")
        return result

    def worker(action, root, producer=None):
        argv = [sys.executable, "-B", str(root / "scripts/bootstrap_compiler.py"), "worker",
                "--snapshot", str(work / "inputs.json"), "--phase", phase, "--action", action]
        if producer is not None:
            argv.extend(["--producer", str(producer)])
        return run(action, argv, root)

    try:
        configure_native_stack()
        for phase in ("c0", "bridge", "p1", "p2"):
            out = work / "out" / phase
            out.mkdir(parents=True, exist_ok=False)
            root = work / snapshot["roots"][phase]
            row = {"phase": phase, "source_root": snapshot["roots"][phase], "commands": [], "pass": False}
            report["phases"].append(row)
            if phase == "c0":
                worker("c0", root)
                binary = out / "c/ouro1"
            else:
                producer = producers[{"bridge": "c0", "p1": "bridge", "p2": "p1"}[phase]]
                producer_hash = sha256_file(producer)
                row.update(producer=str(producer), producer_sha256=producer_hash)
                graph = snapshot["bridge_graph"] if phase == "bridge" else selected["unit_graph"]
                if phase in {"p1", "p2"}:
                    strict_roots(producer, root, selected["roots"], graph, run)
                    row["all_current_roots_strictly_checked_before_emission"] = True
                if phase == "p2":
                    # The current P1 must also check the stdlib/tool/law inputs.
                    for source in ACCEPTANCE_ROOTS:
                        units = [part for unit in graph[source] for part in ("--unit", unit)]
                        result = run("accept-" + Path(source).stem, [str(producer), "check", source, FUEL, *units], root)
                        if result.stdout != "CHECK_OK\n" or result.stderr:
                            fail("current P1 acceptance source did not return clean CHECK_OK: " + source)
                    worker("abi-build", root, producer)
                    law = out / ("abi.exe" if os.name == "nt" else "abi")
                    result = run("abi-laws", [str(law)], root)
                    if result.stderr or result.stdout != ABI_STDOUT:
                        fail("current P1 compiler ABI laws did not return the exact expected protocol")
                worker("frontend", root, producer)
                args = [part for unit in graph["compiler/backend.ouro"] for part in ("--unit", unit)]
                result = run("backend", [str(producer), "--module", "_be", "compiler/backend.ouro", FUEL, *args], root)
                if not result.stdout.startswith('#include "ouro_rt.h"') or "ouro_export_count_be" not in result.stdout:
                    fail("backend emission lacks its declared export table")
                (out / "backend_u.c").write_text(result.stdout, encoding="utf-8", newline="\n")
                worker("link", root)
                binary = out / "ouro1"
                if sha256_file(producer) != producer_hash:
                    fail("producer changed during " + phase)
                row.update(frontend_sha256=sha256_file(out / "driver_u.c"), backend_sha256=sha256_file(out / "backend_u.c"))
            if not binary.is_file() or binary.stat().st_size <= 4096:
                fail("missing complete compiler output for " + phase)
            producers[phase] = binary
            row.update(binary=binary.relative_to(work).as_posix(), binary_sha256=sha256_file(binary), **{"pass": True})
            save()
        report["complete_generated_c_comparison"] = compare_generated(work / "out/p1", work / "out/p2")
        producer = producers["p2"]
        root = work / "o"
        for variant in ("good", "bad"):
            source = "bootstrap-" + variant + ".ouro"
            units = [*selected["unit_graph"]["std/data.ouro"], source]
            argv = [str(producer), "check", source, FUEL, *[part for unit in units for part in ("--unit", unit)]]
            result = run("behavior-" + variant, argv, root, negative=variant == "bad")
            if variant == "good" and (result.stdout != "CHECK_OK\n" or result.stderr):
                fail("current P2 positive behavior was not accepted")
            expected = ("bootstrap-bad.ouro: type mismatch in exact_index\nCHECK_FAIL: front end rejected the input\n"
                        "ouro1: CErr tag=0 n=1\nouro1: CErr code=41 det=78\n")
            if variant == "bad" and (result.returncode != 1 or result.stdout or result.stderr != expected):
                fail("current P2 negative behavior did not preserve the exact rejection")
        report.update(binary=producer.relative_to(work).as_posix(), binary_sha256=sha256_file(producer), **{"pass": True})
    except (OSError, RuntimeError, ValueError) as error:
        report["failure"] = str(error)
        raise
    finally:
        report["changed_inputs"] = changed_inputs(work, snapshot)
        report["pass"] = bool(report["pass"] and not report["changed_inputs"])
        save()
    if not report["pass"]:
        fail("frozen inputs changed during bootstrap")
    return report


def installed_current(binary: Path, receipt: Path, selected: dict) -> bool:
    data = read_json_object_or_none(receipt)
    if data is None or data.get("kind") != KIND or data.get("key") != hash_json(selected) or data.get("selected") != selected:
        return False
    try:
        work = Path(data["work"])
        report = read_json_object_or_none(work / "report.json")
        return bool(binary.is_file() and binary.stat().st_size > 4096 and sha256_file(binary) == data["binary_sha256"]
                    and report and report.get("kind") == KIND and report.get("pass") and report.get("key") == data["key"]
                    and report.get("binary_sha256") == data["binary_sha256"]
                    and sha256_file(work / "report.json") == data["report_sha256"]
                    and sha256_file(work / "inputs.json") == report["inputs_sha256"]
                    and all(sha256_file(work / "out/p1" / name) == row["p1_sha256"] == row["p2_sha256"] == sha256_file(work / "out/p2" / name)
                            for name, row in report["complete_generated_c_comparison"].items())
                    and set(report["complete_generated_c_comparison"]) == {"driver_u.c", "backend_u.c"})
    except (OSError, KeyError, TypeError, ValueError):
        return False


def ensure_current_compiler(cfg, build, root: Path = ROOT) -> dict:
    manifest, _contents = bootstrap_inputs.read_bundle(root)
    bootstrap_inputs.verify_stage0(root, manifest)
    selected = current_inputs(root, cfg, build)
    output = cfg.path("c_build_dir") / "ouro1"
    receipt = output.with_name("ouro1.bootstrap.json")
    if cfg.get_bool("cache_enabled") and installed_current(output, receipt, selected):
        build.log(cfg, "BOOTSTRAP: current compiler unchanged; checked successor reused")
        return {"cache": "hit", "binary": str(output), "binary_sha256": sha256_file(output)}
    directory = cfg.path("build_dir") / "bootstrap"
    directory.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=hash_json(selected)[:12] + "-", dir=directory))
    snapshot = freeze(root, work, selected, cfg)
    report = chain(work, snapshot, build)
    if not current_unchanged(root, selected) or sha256_file(Path(selected["cc_executable"])) != selected["cc_sha256"]:
        fail("current source changed before publication; preserving the existing compiler")
    binary = work / report["binary"]
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + f".tmp.{os.getpid()}")
    shutil.copy2(binary, temporary)
    if sha256_file(temporary) != report["binary_sha256"]:
        fail("successor changed before publication")
    os.replace(temporary, output)
    result = {"kind": KIND, "key": hash_json(selected), "selected": selected, "work": str(work),
        "report_sha256": sha256_file(work / "report.json"), "binary_sha256": report["binary_sha256"]}
    write_json_atomic(receipt, result)
    build.log(cfg, "BOOTSTRAP: current P2 published after strict source checks, behavior checks and complete C equality")
    return result


def worker(args) -> None:
    work = args.snapshot.resolve().parent
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    if ROOT != work / snapshot["roots"][args.phase] or changed_inputs(work, snapshot):
        fail("worker source root or frozen input mismatch")
    import ouro_build as build
    import stage_loop
    out = work / "out" / args.phase
    values = {**snapshot["config"], "cc": snapshot["selected"]["cc_executable"], "jobs": 1, "cache_enabled": False, "ccache": "disabled",
              "build_dir": str(out / "b"), "c_build_dir": str(out / "c"), "cache_dir": str(out / "k")}
    cfg = build.ResolvedConfig(values, {key: "frozen bootstrap invocation" for key in values})
    graph = snapshot["bridge_graph"] if args.phase == "bridge" else snapshot["selected"]["unit_graph"]
    if args.action == "c0":
        if args.phase != "c0":
            fail("historical C build requested for a current stage")
        build.build_c(cfg)
    elif args.action == "frontend":
        if any(frontend.collect_units(source) != graph[source] for source in snapshot["selected"]["roots"]):
            fail("worker ordered source closure changed")
        frontend.regenerate(ouro1=args.producer, fuel=FUEL, out_c=out / "driver_u.c", work=out / "fe",
            cache_root=out / "k", cache_enabled=False, report_path=out / "frontend.json", jobs=1)
    elif args.action == "link":
        config = stage_loop.build_config(argparse.Namespace(promote=False))
        config.build_cfg = cfg
        config.work, config.cache_enabled = out / "b/stage_loop", False
        result = stage_loop.build_stage_binary(out / "driver_u.c", out / "backend_u.c", out / "ouro1", 1, config)
        write_json_atomic(out / "link.json", result)
    elif args.action == "abi-build":
        import native_tool_build
        law_args = argparse.Namespace(entry="tests/compiler_abi_tests.ouro", output=out / "abi", compiler=args.producer,
            fuel=int(FUEL), check=False, config=None, profile=None, opt_level="O0", jobs=1, cc=values["cc"],
            ccache="disabled", cache_enabled=False, build_dir=str(out / "ab"), c_build_dir=str(out / "ac"),
            cache_dir=str(out / "ak"), reproducible=values["reproducible"], verbosity=values["verbosity"])
        result = native_tool_build.build_tool(law_args)
        write_json_atomic(out / "abi-build.json", result)
    else:
        fail("unknown bootstrap worker action")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    internal = sub.add_parser("worker", help=argparse.SUPPRESS)
    internal.add_argument("--snapshot", type=Path, required=True)
    internal.add_argument("--phase", choices=("c0", "bridge", "p1", "p2"), required=True)
    internal.add_argument("--action", choices=("c0", "frontend", "link", "abi-build"), required=True)
    internal.add_argument("--producer", type=Path)
    args = parser.parse_args()
    try:
        worker(args)
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, str(error) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
