#!/usr/bin/env python3
"""OuroSmith: generate, replay, judge, shrink, and report.

Single entry point for the automatic test infrastructure documented in
``docs/ouro_smith.md``.  Every subcommand is deterministic for a given seed set and
generator hash, and every problem it reports carries a replay command.

    python scripts/ouro_smith.py run --profile pr
    python scripts/ouro_smith.py run --profile nightly --layer kernel
    python scripts/ouro_smith.py replay --layer kernel --seed 17 --case core-17
    python scripts/ouro_smith.py inventory
    python scripts/ouro_smith.py faults --profile pr
    python scripts/ouro_smith.py corpus --check
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from ourosmith import SMITH_VERSION, generator_hash  # noqa: E402
from ourosmith.core.run import CoreConfig, CoreRunner, read_recipe  # noqa: E402
from ourosmith.corpus import CORPUS_DIR, RETAINED_LAWS, check_case, load_cases, promote_finding, run_corpus, write_case  # noqa: E402
from ourosmith.faults import FAULTS, check_catalogue, run_faults  # noqa: E402
from ourosmith.inventory import STRATEGIES_PATH, code_strategies, compare, load_strategies, source_inventory, stale, write_strategies  # noqa: E402
from ourosmith.report import Report, load_report, summarize_line  # noqa: E402
from ourosmith.host import prepare_tools  # noqa: E402
from ourosmith.native import SMITH_ENTRY, RETAINED_ENTRY, bind, prepare  # noqa: E402

PREFIX = "OURO_SMITH"

PROFILES = json.loads((ROOT / "quality/smith/seeds.json").read_text(encoding="utf-8"))["profiles"]
LAYERS = ("kernel", "surface")
# Fault profiles retain their surface seed budgets; checker mutations run the
# complete independent canonical law executable against each isolated copy.
FAULT_SEEDS = {"pr": 16, "nightly": 100, "kernel": 40}


def compiler_for(args):
    from ourosmith.host import compiler_path
    from ourosmith.native import digest

    selected = compiler_path(args.compiler)
    current = digest(selected)
    if getattr(args, "_compiler_sha256", current) != current:
        raise ValueError("selected native compiler changed during this command")
    args.compiler, args._compiler_sha256 = selected, current
    return selected


def seeds_for(args: argparse.Namespace) -> list[int]:
    profile = PROFILES[args.profile]
    count = args.seeds if args.seeds is not None else profile["seeds"]
    base = args.seed_base if args.seed_base is not None else profile["seed_base"]
    if args.seed_list:
        return [int(s) for s in args.seed_list.split(",") if s.strip()]
    return list(range(base, base + count))


def native_program(args, out, entry):
    selected = args.kernel_runner if entry == SMITH_ENTRY else args.corpus_runner
    return prepare(entry, out / ("kernel" if entry == SMITH_ENTRY else "retained"), compiler_for(args),
                   memory_mb=args.memory_mb, executable=selected)


def new_report(args, seeds, command):
    from ourosmith import provenance

    args.compiler = compiler_for(args)
    report = Report(profile=args.profile, generator_hash=generator_hash(), seeds=seeds, command=command)
    report.sections["smith_version"] = SMITH_VERSION
    report.sections["provenance"] = provenance.begin()
    report.sections["configuration"] = {key: getattr(args, key, None) for key in
                                         ("depth", "max_defs", "timeout", "memory_mb", "shrink_budget", "layer")}
    return report


def surface_tools(args, out, report):
    from ourosmith.provenance import binary_state

    try:
        overrides, evidence = prepare_tools(out / "build", compiler_for(args))
        report.sections["surface_toolchain"] = evidence
        report.sections["provenance"]["binaries"].update(binary_state(overrides.values()))
        return overrides
    except (OSError, ValueError) as error:
        report.skip("surface:tools", str(error))
        return None


def cmd_run(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    out = Path(args.out) if args.out else ROOT / "_build/smith" / args.profile
    out.mkdir(parents=True, exist_ok=True)
    seeds = seeds_for(args)
    profile = PROFILES[args.profile]
    report = new_report(args, seeds, f"python scripts/ouro_smith.py run --profile {args.profile}")
    complete = seeds == list(range(profile["seed_base"], profile["seed_base"] + profile["seeds"]))
    layers = args.layer.split(",") if args.layer else ["kernel"] if args.profile == "kernel" else list(LAYERS)
    if "kernel" in layers:
        try:
            program = native_program(args, out / "native", SMITH_ENTRY)
            bind(report, program)
            config = CoreConfig(seeds, args.profile,
                                args.depth if args.depth is not None else profile["depth"],
                                args.max_defs if args.max_defs is not None else profile["max_defs"],
                                args.shrink_budget if args.shrink_budget is not None else profile["shrink_budget"])
            CoreRunner(config, report, program, timeout_s=args.timeout).run()
            if not args.no_corpus:
                retained = native_program(args, out / "native", RETAINED_ENTRY)
                bind(report, retained)
                run_corpus(report, retained, timeout_s=args.timeout, smith_program=program)
            if not args.no_inventory:
                check_completeness(report, layer="kernel", full_seed_set=complete)
        except (OSError, ValueError) as error:
            report.skip("kernel:native-driver", str(error))
    if "surface" in layers:
        from ourosmith.surface.run import SurfaceRunner

        overrides = surface_tools(args, out, report)
        if overrides is not None:
            SurfaceRunner(report, out / "surface", seeds,
                          depth=args.depth if args.depth is not None else profile["depth"],
                          timeout=args.timeout, memory_mb=args.memory_mb,
                          shrink_budget=args.shrink_budget if args.shrink_budget is not None else profile["shrink_budget"],
                          overrides=overrides).run()
            if not args.no_inventory:
                check_completeness(report, layer="surface", full_seed_set=complete)
    return finish_report(report, out, started, show=args.show)


def check_completeness(report: Report, *, layer: str, full_seed_set: bool) -> None:
    """Completeness gate: every kernel surface item must map to a declared strategy,
    the committed strategies file must match the code, and (on a full profile seed
    set) every declared strategy must actually have been exercised by this run."""
    committed = load_strategies()
    problems: list[str] = []
    if committed is None:
        problems.append(f"{STRATEGIES_PATH.relative_to(ROOT)} is missing (run inventory --write)")
        committed = code_strategies()
    else:
        problems.extend(stale(committed))
    coverage = report.layer(layer).coverage if full_seed_set else None
    source = source_inventory()
    problems.extend(compare(source, committed, coverage=coverage if layer == "kernel" else None))
    if layer == "surface" and coverage is not None:
        from ourosmith.surface.inventory import compare as compare_surface

        problems.extend(compare_surface(source["surface"], committed["layers"]["surface"], coverage))
    for problem in problems:
        report.gap(layer, "completeness", problem, blocking=True)
    if not full_seed_set:
        report.gap(layer, "completeness", "custom seed selection: exercised-strategy check not applied", blocking=False)
    report.sections.setdefault("completeness", {})[layer] = {"checked_exercised": full_seed_set, "problems": problems}


def finish_report(report: Report, out: Path, started: float, *, show: int) -> int:
    """Write the report and per-finding files, print findings and skips, return the exit code."""
    from ourosmith.provenance import finish

    finish(report)
    report.timing["total_s"] = time.perf_counter() - started
    data = report.write(out / "report.json")
    findings_dir = out / "findings"
    if findings_dir.exists():
        shutil.rmtree(findings_dir)
    for finding in report.findings:
        findings_dir.mkdir(parents=True, exist_ok=True)
        (findings_dir / f"{finding.finding_id}.json").write_text(json.dumps(finding.to_json(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for finding in report.findings[:show]:
        print(f"{PREFIX}: FINDING {finding.layer} {finding.prop} {finding.classification} seed={finding.seed} case={finding.case_id} replay=`{finding.replay}`")
        for note in finding.notes:
            print(f"{PREFIX}:   {note}")
    if len(report.findings) > show:
        print(f"{PREFIX}: ... {len(report.findings) - show} more finding(s) under {findings_dir}")
    for skip in report.skips:
        print(f"{PREFIX}: SKIP {skip['what']}: {skip['why']} (not a pass)")
    for gap in report.gaps:
        print(f"{PREFIX}: {'INCOMPLETE' if gap.get('blocking') else 'GAP'} {gap['layer']} {gap['what']}: {gap['why']}")
    print(f"{PREFIX}: report={out / 'report.json'} fingerprint={data['fingerprint'][:16]} time={report.timing['total_s']:.1f}s")
    print(summarize_line(report))
    return 0 if report.passed else 1


def cmd_inventory(args: argparse.Namespace) -> int:
    inv = source_inventory()
    current = code_strategies()
    if args.write:
        write_strategies(current)
        print(f"{PREFIX}: wrote {STRATEGIES_PATH.relative_to(ROOT)}")
    committed = load_strategies()
    problems: list[str] = []
    if committed is None:
        problems.append(f"{STRATEGIES_PATH.relative_to(ROOT)} is missing (run inventory --write)")
        committed = current
    else:
        problems.extend(stale(committed))
    coverage = None
    if args.report:
        data = load_report(Path(args.report))
        if data is None:
            problems.append(f"{args.report} is not a smith report")
        else:
            coverage = data.get("summary", {}).get("layers", {}).get("kernel", {}).get("coverage")
            if coverage is None:
                problems.append(f"{args.report} has no kernel coverage section")
    problems.extend(compare(inv, committed, coverage=coverage))
    out = Path(args.out) if args.out else ROOT / "_build/smith/inventory"
    out.mkdir(parents=True, exist_ok=True)
    (out / "inventory.json").write_text(json.dumps({"kind": "ouro.smith-inventory.v1", "sources": inv, "problems": problems}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    if args.verbose:
        print(json.dumps(inv, indent=1, sort_keys=True))
    for p in problems:
        print(f"{PREFIX}: INCOMPLETE {p}")
    kernel = committed["layers"]["kernel"]
    print(
        f"{PREFIX}: inventory {'PASS' if not problems else 'FAIL'} terms={len(inv['term_constructors'])} faults={len(inv['type_faults']) + len(inv['core_faults'])} prims={len(inv['primitives'])} "
        f"features={len(kernel['generator_features'])} negatives={len(kernel['negative_strategies'])} problems={len(problems)}"
    )
    return 1 if problems else 0


def cmd_faults(args: argparse.Namespace) -> int:
    out = Path(args.out) if args.out else ROOT / "_build/smith/faults"
    out.mkdir(parents=True, exist_ok=True)
    if args.check:
        problems = check_catalogue()
        for p in problems:
            print(f"{PREFIX}: STALE {p}")
        print(f"{PREFIX}: faults catalogue {'PASS' if not problems else 'FAIL'} faults={len(FAULTS)} problems={len(problems)}")
        return 1 if problems else 0
    profile = PROFILES[args.profile]
    count = args.seeds if args.seeds is not None else FAULT_SEEDS[args.profile]
    config = CoreConfig(
        seeds=list(range(profile["seed_base"], profile["seed_base"] + count)),
        profile=args.profile,
        depth=args.depth if args.depth is not None else profile["depth"],
        max_defs=args.max_defs if args.max_defs is not None else profile["max_defs"],
        shrink_budget=0,
    )
    data = run_faults(
        config=config,
        out=out,
        compiler=compiler_for(args),
        timeout_s=args.timeout,
        memory_mb=args.memory_mb,
        only=set(args.only.split(",")) if args.only else None,
        targets=set(args.target.split(",")) if args.target else None,
    )
    data["command"] = "python scripts/ouro_smith.py " + " ".join(sys.argv[1:])
    (out / "faults.json").write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for p in data["catalogue_problems"]:
        print(f"{PREFIX}: STALE {p}")
    s = data["summary"]
    print(
        f"{PREFIX}: faults {'PASS' if data['pass'] else 'FAIL'} faults={s['faults']} killed={s['killed']} survived={s['survived']} "
        f"stale={s['stale']} unbuildable={s['unbuildable']} baseline={'clean' if data['baseline']['clean'] else 'dirty'} "
        f"seeds={len(config.seeds)} time={data['timing_s']['total']:.1f}s report={out / 'faults.json'}"
    )
    return 0 if data["pass"] else 1


def cmd_corpus(args: argparse.Namespace) -> int:
    directory = Path(args.dir) if args.dir else CORPUS_DIR
    if args.promote:
        finding = json.loads(Path(args.promote).read_text(encoding="utf-8"))
        if not args.name:
            print(f"{PREFIX}: --promote needs --name")
            return 2
        if finding.get("layer") == "surface":
            from ourosmith.surface.corpus import DIRECTORY, promote

            path = promote(finding, args.name, directory=Path(args.dir) if args.dir else DIRECTORY, note=args.note or "")
        else:
            path = promote_finding(finding, args.name, directory=directory, note=args.note or "")
        print(f"{PREFIX}: wrote corpus case {path}")
        return 0

    cases = load_cases(directory)
    if args.dir and not cases:
        raise ValueError("no native recipe cases under " + str(directory))
    if args.only and args.only not in RETAINED_LAWS and args.only not in {case.name for case in cases}:
        raise ValueError("unknown typed retained law or native recipe: " + args.only)
    issues = [(case, issue) for case in cases for issue in check_case(case, check_format=not args.format)]
    for case, issue in issues:
        print(f"{PREFIX}: FORMAT {case.path}: {issue}")
    if issues:
        return 1
    if args.format:
        for case in cases:
            write_case(case.path, case.data)
    if args.check or args.format:
        print(f"{PREFIX}: corpus inventory PASS typed_laws={len(RETAINED_LAWS)} recipes={len(cases)}; execution not requested")
        return 0
    started = time.perf_counter()
    out = Path(args.out) if args.out else ROOT / "_build/smith/corpus"
    out.mkdir(parents=True, exist_ok=True)
    report = new_report(args, [], "python scripts/ouro_smith.py corpus")
    try:
        retained = native_program(args, out / "native", RETAINED_ENTRY)
        bind(report, retained)
        smith = native_program(args, out / "native", SMITH_ENTRY) if cases else None
        if smith is not None:
            bind(report, smith)
        run_corpus(report, retained, timeout_s=args.timeout, directory=directory, only=args.only, smith_program=smith)
    except (OSError, ValueError) as error:
        report.skip("kernel-corpus:native-driver", str(error))
    return finish_report(report, out, started, show=args.show)


def cmd_replay(args: argparse.Namespace) -> int:
    out = Path(args.out) if args.out else ROOT / "_build/smith/replay"
    out.mkdir(parents=True, exist_ok=True)
    profile = PROFILES[args.profile]
    finding = json.loads(Path(args.finding).read_text(encoding="utf-8")) if args.finding else None
    if finding is not None:
        args.layer = finding["layer"]
        args.seed = finding["seed"]
        if args.layer not in {"kernel", "surface"}:
            raise ValueError("finding replay requires a kernel or surface input")
    if args.layer == "surface":
        from ourosmith.surface.run import SurfaceRunner

        started = time.perf_counter()
        report = new_report(args, [args.seed], "surface replay")
        overrides = surface_tools(args, out, report)
        if overrides is not None:
            runner = SurfaceRunner(report, out / "surface", [args.seed], depth=args.depth or profile["depth"],
                                   timeout=args.timeout, memory_mb=args.memory_mb, shrink_budget=0, overrides=overrides)
            if finding is None and args.case is None:
                runner.run()
            else:
                from ourosmith.surface import gen
                from ourosmith.surface.forms import FEATURES
                from ourosmith.surface.mutate import mutations
                from ourosmith.surface.tools import PROPERTIES

                runner.seed, runner.case_id = args.seed, args.case or finding["case_id"]
                if finding is not None:
                    runner.replay_input(finding["minimal_input"])
                elif args.case == f"surface-{args.seed}":
                    runner.replay_input({"ast": gen.generate(args.seed, runner.depth).json()})
                else:
                    suffix = args.case.removeprefix(f"surface-{args.seed}-")
                    mutation = next((m for m in mutations(args.seed) if m.name == suffix), None)
                    if mutation is not None:
                        from dataclasses import asdict

                        runner.replay_input({**asdict(mutation), "mutation": mutation.name})
                    elif suffix in {"form-" + name for name in FEATURES} | {prop.__name__ for prop in PROPERTIES}:
                        runner.replay_input({"recipe": suffix})
                    else:
                        raise ValueError(f"unknown surface case {args.case}")
        return finish_report(report, out, started, show=20)

    if finding is None:
        config = CoreConfig([args.seed], args.profile,
                            args.depth if args.depth is not None else profile["depth"],
                            args.max_defs if args.max_defs is not None else profile["max_defs"], 0)
    else:
        config = read_recipe(finding.get("minimal_input"))
        if finding.get("seed") != config.seeds[0] or finding.get("generator_hash") != finding["minimal_input"]["generator_hash"]:
            raise ValueError("saved native finding identity disagrees with its recipe")
        args.profile, args.depth, args.max_defs = config.profile, config.depth, config.max_defs
    if args.case not in (None, f"core-{config.seeds[0]}"):
        raise ValueError("native kernel replay selects the whole seed; unknown case: " + args.case)
    started = time.perf_counter()
    report = new_report(args, config.seeds, "python scripts/ouro_smith.py replay --layer kernel")
    try:
        program = native_program(args, out / "native", SMITH_ENTRY)
        bind(report, program)
        CoreRunner(config, report, program, timeout_s=args.timeout).run()
    except (OSError, ValueError) as error:
        report.skip("kernel:native-driver", str(error))
    return finish_report(report, out, started, show=20)


def add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--profile", choices=sorted(PROFILES), default="pr")
    p.add_argument("--out", default=None)
    p.add_argument("--depth", type=int, default=None)
    p.add_argument("--max-defs", type=int, default=None)
    p.add_argument("--timeout", type=float, default=float(os.environ.get("OURO_SMITH_TIMEOUT", "20")))
    p.add_argument("--memory-mb", type=int, default=int(os.environ.get("OURO_SMITH_MEMORY_MB", "2048")))
    p.add_argument("--compiler", default=None, help="native Ouro producer for every selected layer (default: configured ouro1)")


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("--"):
        command = "run"
        for flag, verb in (("--self-test", "self-test"), ("--faults", "faults"), ("--list", "inventory"), ("--replay", "replay"), ("--update-corpus", "corpus")):
            if flag in argv:
                position = argv.index(flag)
                argv.pop(position)
                command = verb
                if flag == "--update-corpus":
                    argv.insert(position, "--promote")
                break
        argv.insert(0, command)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    selftest = sub.add_parser("self-test", help="exercise the harness, its oracles, CLI, and process limits")
    selftest.set_defaults(func=cmd_selftest)

    prepare = sub.add_parser("prepare", help="materialize generated inputs for native tool selftests")
    from ourosmith.native_inputs import GROUPS

    prepare.add_argument("--group", required=True, choices=GROUPS)
    prepare.add_argument("--seed", type=int, default=1)
    prepare.add_argument("--out", default=str(ROOT / "_build/smith/fixtures"))
    from ourosmith.native_inputs import run as prepare_run

    prepare.set_defaults(func=prepare_run)
    manifest = sub.add_parser("manifest", help="run a native manifest batch on generated inputs")
    manifest.add_argument("--prefix", required=True)
    manifest.add_argument("--label", default="SMITH_MANIFEST")
    manifest.add_argument("--seed", type=int, default=1)
    manifest.add_argument("--out", default=str(ROOT / "_build/smith/manifest"))
    from ourosmith.native_inputs import run_manifest

    manifest.set_defaults(func=run_manifest)

    validation = sub.add_parser("validate", help="execute the full migration validation and deterministic profile pair")
    validation.add_argument("--out", default=None)
    from ourosmith.validation import run as validation_run

    validation.set_defaults(func=validation_run)

    migration = sub.add_parser("migration", help="audit legacy evidence against executed strategies; block incomplete retirement")
    migration.add_argument("--report", required=True)
    migration.add_argument("--out", default=None)
    migration.add_argument("--validation", default=None, help="directory produced by the validate command")
    migration.add_argument("--write", action="store_true", help="write quality/smith/migration_matrix.json")
    from ourosmith.migration import run as migration_run

    migration.set_defaults(func=migration_run)

    run = sub.add_parser("run", help="generate and check the selected layers")
    add_common(run)
    run.add_argument("--kernel-runner", default=None, help="reuse a native Smith binary with a complete current build receipt")
    run.add_argument("--corpus-runner", default=None, help="reuse a typed retained-law binary with a complete current build receipt")
    run.add_argument("--layer", default=None, help="comma-separated layers (default: all)")
    run.add_argument("--seeds", type=int, default=None, help="number of seeds (default from profile)")
    run.add_argument("--seed-base", "--seed", type=int, default=None)
    run.add_argument("--seed-list", default=None, help="explicit comma-separated seeds")
    run.add_argument("--shrink-budget", type=int, default=None)
    run.add_argument("--show", type=int, default=20, help="findings to print")
    run.add_argument("--no-corpus", action="store_true", help="do not replay the persistent corpus")
    run.add_argument("--no-inventory", action="store_true", help="skip the strategy completeness gate")
    run.set_defaults(func=cmd_run)

    inventory = sub.add_parser("inventory", help="extract the testable surface from the sources and check strategy completeness")
    inventory.add_argument("--write", action="store_true", help="rewrite quality/smith strategy and diagnostic registries from source contracts")
    inventory.add_argument("--report", default=None, help="smith report whose coverage must exercise every declared strategy")
    inventory.add_argument("--out", default=None)
    inventory.add_argument("--verbose", action="store_true")
    inventory.set_defaults(func=cmd_inventory)

    faults = sub.add_parser("faults", help="inject source bugs into kernel and surface tool copies and require detection")
    add_common(faults)
    faults.add_argument("--seeds", type=int, default=None, help="seeds per fault run (default from profile)")
    faults.add_argument("--only", default=None, help="comma-separated fault ids")
    faults.add_argument("--target", default=None, help="comma-separated targets: " + ", ".join(sorted({f.target for f in FAULTS})))
    faults.add_argument("--check", action="store_true", help="only verify that every fault still applies to the current sources")
    faults.set_defaults(func=cmd_faults)

    corpus = sub.add_parser("corpus", help="replay, check, format, or extend the persistent regression corpus")
    add_common(corpus)
    corpus.add_argument("--kernel-runner", default=None, help="reuse a native Smith binary with a complete current build receipt")
    corpus.add_argument("--corpus-runner", default=None, help="reuse a typed retained-law binary with a complete current build receipt")
    corpus.add_argument("--dir", default=None, help=f"corpus directory (default {CORPUS_DIR.relative_to(ROOT)})")
    corpus.add_argument("--check", action="store_true", help="validate the corpus files only (no oracle)")
    corpus.add_argument("--format", action="store_true", help="rewrite the corpus files in canonical form")
    corpus.add_argument("--only", default=None, help="replay a single case by name")
    corpus.add_argument("--promote", default=None, help="finding JSON to turn into a corpus case")
    corpus.add_argument("--name", default=None, help="corpus case name for --promote")
    corpus.add_argument("--note", default=None, help="origin note for --promote")
    corpus.add_argument("--show", type=int, default=20)
    corpus.set_defaults(func=cmd_corpus)

    replay = sub.add_parser("replay", help="replay one seed or an exact hash-bound saved native recipe")
    add_common(replay)
    replay.add_argument("--kernel-runner", default=None, help="reuse a native Smith binary with a complete current build receipt")
    replay.add_argument("--corpus-runner", default=None, help="reuse a typed retained-law binary with a complete current build receipt")
    replay.add_argument("--layer", default="kernel")
    replay.add_argument("--seed", type=int)
    replay.add_argument("--case", default=None)
    replay.add_argument("--finding", default=None, help="replay a saved minimal finding input")
    replay.set_defaults(func=cmd_replay)

    args = ap.parse_args(argv)
    if args.command == "replay" and args.seed is None and args.finding is None:
        ap.error("replay needs --seed or --finding")
    if args.command == "replay" and args.layer not in {"kernel", "surface"}:
        ap.error("replay requires a single kernel or surface layer")
    if args.command in {"run", "replay", "faults", "corpus"}:
        import math

        if not math.isfinite(args.timeout) or args.timeout <= 0 or args.memory_mb <= 0:
            ap.error("timeout and memory limit must be positive and finite")
        for key in ("max_defs", "seeds"):
            value = getattr(args, key, None)
            if value is not None and value <= 0:
                ap.error(f"--{key.replace('_', '-')} must be positive")
        if args.depth is not None and not 0 <= args.depth <= 8:
            ap.error("--depth must be in 0..8")
        if args.max_defs is not None and args.max_defs > 16:
            ap.error("--max-defs must be in 1..16")
        for key in ("seed", "seed_base"):
            seed = getattr(args, key, None)
            if seed is not None and not 0 <= seed < 2**32:
                ap.error("seed must be in 0..4294967295")
        layer = getattr(args, "layer", None)
        if layer is not None and (set(layer.split(",")) - set(LAYERS) or len(set(layer.split(","))) != len(layer.split(","))):
            ap.error(f"layers must be unique names from {', '.join(LAYERS)}")
        if getattr(args, "seed_list", None) is not None:
            try:
                seeds = [int(seed) for seed in args.seed_list.split(",")]
            except ValueError:
                ap.error("--seed-list needs comma-separated integers")
            if not seeds or len(set(seeds)) != len(seeds) or any(not 0 <= seed < 2**32 for seed in seeds):
                ap.error("--seed-list must be nonempty and contain no duplicates")
        if getattr(args, "shrink_budget", None) is not None and args.shrink_budget < 0:
            ap.error("--shrink-budget cannot be negative")
    try:
        return int(args.func(args))
    except (OSError, ValueError, KeyError) as exc:
        print(f"{PREFIX}: FAIL {exc}", file=sys.stderr)
        return 1


def cmd_selftest(_args) -> int:
    from ourosmith.selftest import run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
