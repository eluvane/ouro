"""Generated host/direct/stage and eval contracts."""
from __future__ import annotations

import hashlib
import json

from ourosmith import ROOT
from ourosmith.host import environment, shell
from ourosmith.surface.gen import PRELUDE, evaluate, generate, nat_output, program
from ourosmith.surface.forms import programs as form_programs
from ourosmith.surface.mutate import mutations
from ourosmith.surface.run import checked_program_snapshot


def programs(seed):
    expr = generate(seed, 3)
    yield {"name": "expression", "source": program(expr), "expected": evaluate(expr), "dependencies": []}
    text = "x" * (seed % 5) + "a\nb"
    yield {"name": "string-primitive", "source": PRELUDE + f"def result : Nat := prim_string_length {json.dumps(text)};\n",
           "expected": len(text.encode("utf-8")), "dependencies": []}
    n, m = seed % 7, (seed // 7) % 5
    yield {"name": "imports", "source": f'import "leaf.ouro" as L;\ndef result : L.Nat := L.add L.value {m};\n',
           "expected": n + m, "dependencies": [["leaf.ouro", PRELUDE + f"def value : Nat := {n};\n"]]}
    for name, imports, declarations in (
        ("imports-open-decl", 'import "leaf.ouro" as L;\nopen L;\n', f"def result : Nat := add value {m};\n"),
        ("imports-open-local", 'import "leaf.ouro" as L;\n', f"def result : Nat := open L in add value {m};\n"),
        ("imports-plain-alias", 'import "leaf.ouro" as L;\nimport "leaf.ouro";\n', f"def result : Nat := L.add value {m};\n"),
        ("imports-selective", 'import "leaf.ouro" as L exposing (Nat, Z, S, add, value as chosen);\n',
         f"def result : L.Nat := L.add chosen {m};\n"),
        ("imports-record", 'import "leaf.ouro" as L;\n', f"record Point : Type where x : L.Nat; y : L.Nat; end;\ndef point : Point := {{x := L.value, y := {m}}};\ndef result : L.Nat := L.add (point.x) (point.y);\n"),
    ):
        yield {"name": name, "source": imports + declarations, "expected": n + m,
               "dependencies": [["leaf.ouro", PRELUDE + f"def value : Nat := {n};\n"]]}
    yield {"name": "imports-selective-transitive",
           "source": f'import "middle.ouro";\ndef result : Number := plus chosen {m};\n',
           "expected": n + m, "type_name": "Number", "successor": "S",
           "dependencies": [["leaf.ouro", PRELUDE + f"def value : Nat := {n};\n"],
                            ["middle.ouro", 'import "leaf.ouro" exposing (Nat as Number, S, add as plus, value as chosen);\n']]}
    for name, source, expected, units in form_programs(seed):
        if name in {"record", "list", "do-case-binding", "handler"}:
            yield {"name": name, "source": source, "expected": expected, "dependencies": [], "units_needed": units}
    for mutation in mutations(seed):
        if mutation.name in {"pipe-missing-rhs", "list-context", "import-unknown"}:
            yield {"name": mutation.name, "source": mutation.source, "diagnostics": list(mutation.diagnostics),
                   "dependencies": list(mutation.dependencies)}


def inputs(seed):
    for case in programs(seed):
        if "expected" in case:
            case.setdefault("type_name", "L.Nat" if case["name"].startswith("imports") else "Nat")
            case.setdefault("successor", "L.S" if case["name"].startswith("imports") else "S")
        yield case


def stage(run):
    proof = ROOT / "_build/stage_loop/result.json"
    if not proof.is_file():
        run.report.sections["stage_parity"] = {"status": "unavailable", "reason": "no recorded stage fixpoint"}
        run.require(run.report.profile != "nightly", "stage-fixpoint-required", "recorded nightly fixpoint", "unavailable")
        return None
    record = json.loads(proof.read_text(encoding="utf-8"))
    number = record.get("stages")
    run.require(type(number) is int and 1 <= number <= 32, "stage-fixpoint-proof", "valid recorded stage number", number)
    path = ROOT / f"_build/stage_loop/ouro1_stage{number}"
    valid = all(record.get(key) is True for key in ("pass", "frontend_eq", "backend_eq"))
    valid = valid and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == record.get("artifacts", {}).get("binary_sha256")
    run.require(valid, "stage-fixpoint-proof", "binary matches recorded FE+BE fixpoint", str(path))
    run.report.sections["stage_parity"] = {"status": "exercised", "binary": path.relative_to(ROOT).as_posix(),
                                          "sha256": record["artifacts"]["binary_sha256"]}
    return path


def run_checks(run, directory, saved=None):
    cases = saved["cases"] if saved is not None else list(inputs(run.seed))
    run.input = {"recipe": "compiler_parity", "cases": cases}
    wrapper = [shell(), run.overrides.get("ouro-wrapper", ROOT / "scripts/ouro1.sh")]
    staged = stage(run)
    for case in cases:
        work = directory / case["name"]
        work.mkdir(parents=True, exist_ok=True)
        path = work / "main.ouro"
        path.write_text(case["source"], encoding="utf-8", newline="\n")
        units = []
        for name, source in case["dependencies"]:
            dep = work / name
            dep.write_text(source, encoding="utf-8", newline="\n")
            units.append(dep)
        if units or case.get("units_needed", False):
            units.append(path)
        if "diagnostics" in case:
            for compiler, direct in ((wrapper, False), ([run.compiler], True), *([([staged], True)] if staged is not None else [])):
                args = [*compiler, "check", path, "999999"]
                if direct:
                    for unit in units:
                        args += ["--unit", unit]
                result = run.command(args, work, "parity-reject")
                run.require(result.returncode == 1 and any(code in result.stdout + result.stderr for code in case["diagnostics"]),
                            "parity-reject", case["diagnostics"], run.output(result))
            continue
        core = run.accepts(path, units=units)
        artifact = work / "host.checked"
        artifact.unlink(missing_ok=True)
        host = run.command([*wrapper, "check", path, "999999", "--emit-checked-program", artifact], work, "parity-host")
        run.require(host.ok and "CHECK_OK" in host.stdout and artifact.is_file(), "parity-host-accept", "CHECK_OK and artifact", run.output(host))
        run.require(checked_program_snapshot(artifact) == core, "parity-host-core", core, checked_program_snapshot(artifact))
        if staged is not None:
            artifact = work / "stage.checked"
            artifact.unlink(missing_ok=True)
            args = [staged, "check", path, "999999", "--emit-checked-program", artifact]
            for unit in units:
                args += ["--unit", unit]
            result = run.command(args, work, "parity-stage")
            run.require(result.ok and "CHECK_OK" in result.stdout and artifact.is_file(), "parity-stage-accept", "CHECK_OK and artifact", run.output(result))
            run.require(checked_program_snapshot(artifact) == core, "parity-stage-core", core, checked_program_snapshot(artifact))
        expected = nat_output(case["expected"])
        native = run.native(path, units=units)
        run.require(native.ok and native.stdout == expected, "parity-native-reference", expected, run.output(native))
        for mode, expression, value in (("--print", "result", case["expected"]),
                                         ("--eval", case["successor"] + " result", case["expected"] + 1)):
            result = run.command([*wrapper, "eval", path, mode, expression, "--type", case["type_name"], "--fuel", "999999"],
                                 work, "eval-reference", env=environment(build=True), timeout=60)
            run.require(result.ok and result.stdout == nat_output(value), "eval-reference", nat_output(value), run.output(result))
        run.count("features", "parity:" + case["name"])
    path = directory / next(case["name"] for case in cases if "expected" in case) / "main.ouro"
    failures = [([path], 2, "EVAL_FAIL: require exactly one of --eval / --print"),
                ([path, "--print", "result", "--eval", "result"], 2, "EVAL_FAIL: require exactly one of --eval / --print"),
                ([directory / "missing.ouro", "--print", "result"], 2, "EVAL_FAIL: missing"),
                # The emit-C frontend reports its generic elaboration code;
                # detailed check-mode diagnostics use the separate 41+ range.
                ([path, "--eval", "missing_symbol", "--fuel", "999999"], 1, "CErr code=2")]
    for args, code, diagnostic in failures:
        result = run.command([*wrapper, "eval", *args], directory, "eval-negative", env=environment(build=True), timeout=60)
        run.require(result.returncode == code and diagnostic in result.stderr and not result.stdout,
                    "eval-negative", {"exit_code": code, "diagnostic": diagnostic}, run.output(result))
