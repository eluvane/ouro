"""Compile each surface sample with verified reusable runtime objects."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[3]


def build_native(args: argparse.Namespace) -> dict:
    import ouro_build as build
    from repo_support import sha256_file, write_json_atomic

    cfg = build.load_config(argparse.Namespace(
        cc=args.cc, profile="dev", opt_level="O1", reproducible=False,
        cache_enabled=args.cache, ccache="disabled", verbosity="quiet", jobs=1))
    cc = build.choose_cc(cfg)
    identity = json.loads(build.compiler_id(cc))
    compiler_path = Path(identity["path"]).resolve()
    identity["executable_sha256"] = sha256_file(compiler_path)
    sources = [ROOT / "runtime/ouro_rt.c", ROOT / "runtime/ouro_io.c", args.main.resolve()]
    tracked = {*sources, compiler_path, args.generated.resolve(), *(ROOT / "runtime").glob("*.h")}
    before = {str(path): sha256_file(path) for path in sorted(tracked)}
    if before[str(compiler_path)] != identity["executable_sha256"]:
        raise ValueError("surface C compiler changed during preparation")
    cc_id = json.dumps(identity, sort_keys=True)
    object_dir = args.object_dir if args.cache else args.object_dir / uuid.uuid4().hex
    objects = []
    reports = []
    for source in sources:
        obj, report = build.compile_c_object(
            cfg, cc, cc_id, "smith-surface-runtime", source, build.path_key(source),
            [ROOT / "runtime"], ["-Werror=implicit-function-declaration"], object_dir)
        objects.append(obj)
        reports.append(report)
    stack = ["-Wl,--stack,134217728"] if os.name == "nt" else []
    command = [*build.cc_invocation(cc), *build.profile_cflags(cfg),
               "-Werror=implicit-function-declaration", *stack,
               "-I", str(ROOT / "runtime"), "-o", str(args.output),
               str(args.generated), *map(str, objects)]
    compiled = subprocess.run(command, check=False)
    if compiled.returncode != 0:
        raise SystemExit(compiled.returncode)
    after = {str(path): sha256_file(path) for path in sorted(tracked)}
    if before != after:
        raise ValueError("surface native input changed during compilation")
    if any(sha256_file(obj) != report["object_sha256"] for obj, report in zip(objects, reports, strict=True)):
        raise ValueError("surface runtime object changed during linking")
    result = {"kind": "ouro.smith-native-build.v1", "compiler_id": identity,
              "command": command, "inputs": before, "runtime": reports,
              "output_sha256": sha256_file(args.output)}
    write_json_atomic(args.report, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("generated", type=Path)
    for name in ("main", "output", "object-dir", "report"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--cc", required=True)
    parser.add_argument("--no-cache", dest="cache", action="store_false", default=True)
    args = parser.parse_args()
    try:
        build_native(args)
    except (OSError, ValueError) as error:
        print(f"SURFACE_NATIVE_COMPILE: FAIL {args.generated}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    raise SystemExit(main())
