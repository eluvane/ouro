"""Surface/tool differential properties, executed through bounded native tools."""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ourosmith import ROOT
from ourosmith.host import binary, environment, job_count
from ourosmith.limits import RunResult, run_limited
from ourosmith.report import Finding, Report, finding_size
from ourosmith.surface import gen
from ourosmith.surface.mutate import Mutation, mutations


def checked_program_snapshot(path: Path) -> str:
    """Read the compiler's complete, alpha-stable diagnostic snapshot.

    Ouro serializes checked declarations and resolves global IDs to names.
    This host checks framing only; there is no JSON replay or host type synthesis.
    """
    text = path.read_text(encoding="ascii")
    header, separator, payload = text.partition("\n")
    if header != "ouro.checked-program.v1" or separator != "\n" or not re.fullmatch(r"(?:(?:0|[1-9][0-9]*) )+\n", payload):
        raise ValueError("invalid checked-program snapshot")
    return text


class StepFailure(Exception):
    def __init__(self, prop, expected, actual, classification="property-violation"):
        self.prop, self.expected, self.actual, self.classification = prop, expected, actual, classification
        super().__init__(prop)


class SurfaceRunner:
    def __init__(self, report: Report, work: Path, seeds: list[int], *, depth=4, timeout=20, memory_mb=1024, shrink_budget=40, overrides=None):
        self.report, self.work, self.seeds = report, work.resolve(), seeds
        self.depth, self.timeout, self.memory_mb = depth, timeout, memory_mb
        self.shrink_budget = shrink_budget
        self.summary = report.layer("surface")
        self.coverage = {"features": {}, "negative_kinds": {}, "properties": {}}
        self.summary.coverage = self.coverage
        self.env = environment()
        self.overrides = overrides or {}
        self.compiler = self.tool("ouro1")
        self.runtime_printer = self.overrides.get("runtime-printer", ROOT / "runtime/ouro_eval_main.c")
        self.module_cache = self.overrides.get("module-cache", ROOT / "scripts/selfhost_module_cache.py")
        self.cc = shutil.which("gcc") or shutil.which("cc")
        self.sequence = 0
        self.seed = 0
        self.case_id = ""
        self.input = None

    def tool(self, name):
        return self.overrides[name] if name in self.overrides else binary(name)

    def count(self, group, name):
        counts = self.coverage[group]
        counts[name] = counts.get(name, 0) + 1

    def command(self, argv, directory: Path, prop: str, *, env=None, stdin=None, timeout=None) -> RunResult:
        argv = [arg.as_posix() if isinstance(arg, Path) else str(arg) for arg in argv]
        timeout = self.timeout if timeout is None else timeout
        result = run_limited(argv, cwd=directory, env=env or self.env,
                             stdin_text=stdin, timeout_s=timeout, memory_mb=self.memory_mb)
        self.sequence += 1
        logs = self.work / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / f"{self.sequence:05}-{prop}.log").write_text(
            json.dumps({"argv": list(map(str, argv)), "status": result.classify(), "exit_code": result.returncode,
                        "timeout_s": timeout, "elapsed_s": result.elapsed_s, "peak_rss_mb": result.peak_rss_mb})
            + "\n" + result.stdout + result.stderr, encoding="utf-8")
        if result.classify() not in {"ok", "nonzero"}:
            raise StepFailure(prop, "normal process termination", self.output(result), result.classify())
        return result

    def output(self, result: RunResult):
        return {"status": result.classify(), "exit_code": result.returncode,
                "stdout": result.stdout.replace(str(self.work), "$WORK").replace(self.work.as_posix(), "$WORK"),
                "stderr": result.stderr.replace(str(self.work), "$WORK").replace(self.work.as_posix(), "$WORK")}

    def require(self, condition, prop, expected, actual, classification="property-violation"):
        self.summary.property_checks += 1
        self.count("properties", prop)
        if not condition:
            raise StepFailure(prop, expected, actual, classification)

    def record(self, failure: StepFailure, expr=None):
        original_size = finding_size(self.input)
        attempts = 0
        if expr is not None and self.shrink_budget:
            probe_report = Report(profile=self.report.profile, generator_hash=self.report.generator_hash, seeds=[self.seed], command="shrink")
            probe = SurfaceRunner(probe_report, self.work / "shrink", [self.seed], depth=self.depth,
                                  timeout=self.timeout, memory_mb=self.memory_mb, shrink_budget=0, overrides=self.overrides)
            probe.seed, probe.case_id = self.seed, self.case_id

            def still_fails(candidate):
                try:
                    probe.positive(candidate)
                except StepFailure as result:
                    return (result.prop, result.classification) == (failure.prop, failure.classification)
                return False

            expr, attempts = gen.shrink(expr, still_fails, self.shrink_budget)
            self.input = {"ast": expr.json(), "source": gen.program(expr), "expected": gen.evaluate(expr)}
        self.report.add(Finding("surface", failure.prop, failure.classification, self.seed,
                                self.report.profile, self.report.generator_hash, self.case_id,
                                failure.prop, failure.expected, failure.actual, self.input,
                                f"python scripts/ouro_smith.py replay --layer surface --seed {self.seed} --profile {self.report.profile} --depth {self.depth}",
                                original_size=original_size, shrunk_size=finding_size(self.input),
                                notes=[f"shrink attempts={attempts}"] if expr is not None else []))

    def check(self, path: Path, *, artifact=True, units=(), fuel=999999, env=None, timeout=None):
        target = path.with_suffix(".checked")
        target.unlink(missing_ok=True)
        args = [self.compiler.as_posix(), "check", path.as_posix(), str(fuel)]
        for unit in units:
            args += ["--unit", Path(unit).as_posix()]
        if artifact:
            args += ["--emit-checked-program", target.as_posix()]
        result = self.command(args, path.parent, "check", env=env, timeout=timeout)
        if not artifact or not result.ok:
            return result, None
        self.require(target.is_file(), "core-emitted", "fresh artifact", self.output(result))
        try:
            self.summary.property_checks += 1
            self.count("properties", "core-protocol")
            return result, checked_program_snapshot(target)
        except (OSError, UnicodeError, ValueError) as exc:
            raise StepFailure("core-protocol", "complete checked-program snapshot", str(exc)) from exc

    def accepts(self, path: Path, **kwargs):
        result, core = self.check(path, **kwargs)
        self.require(result.ok and "CHECK_OK" in result.stdout, "accepts-typed-source", "CHECK_OK and exit 0", self.output(result), "wrong-reject")
        return core

    def native(self, path: Path, *, units=(), io=False, arguments=(), env=None, stdin=None, compile_timeout=None):
        if self.cc is None:
            raise StepFailure("native-compile", "installed C compiler", "unavailable", "oracle-unavailable")
        emitted = path.with_suffix(".c")
        args = [self.compiler, path, "999999"]
        for unit in units:
            args += ["--unit", unit]
        result = self.command(args, path.parent, "emit-c", env={**self.env, "OURO_EMIT_IO_SHIMS": "1"}, timeout=compile_timeout)
        self.require(result.ok, "emit-c", "exit 0", self.output(result))
        emitted.write_text(result.stdout, encoding="utf-8")
        exe = path.with_suffix(".exe")
        main = ROOT / "runtime/ouro_prog_main.c" if io else self.runtime_printer
        stack = ["-Wl,--stack,134217728"] if os.name == "nt" else []
        result = self.command([self.cc, "-O1", "-std=c99", "-D_POSIX_C_SOURCE=200809L", "-Werror=implicit-function-declaration", *stack,
                               "-I", ROOT / "runtime", "-o", exe, emitted, ROOT / "runtime/ouro_rt.c",
                               ROOT / "runtime/ouro_io.c", main], path.parent, "native-compile", timeout=compile_timeout)
        self.require(result.ok, "native-compile", "exit 0", self.output(result))
        return self.command([exe, *arguments], path.parent, "native-run", env=env, stdin=stdin)

    def positive(self, expr: gen.Expr):
        directory = self.work / "cases" / self.case_id
        directory.mkdir(parents=True, exist_ok=True)
        source = gen.program(expr)
        path = directory / "main.ouro"
        path.write_text(source, encoding="utf-8", newline="\n")
        core = self.accepts(path)
        self.summary.positive_checks += 1
        self.count("features", "prelude")
        for feature in gen.features(expr):
            self.count("features", feature)
        lint = self.command([self.tool("ouro-lint"), path], directory, "lint-clean")
        self.require(lint.ok and not lint.stdout.strip() and not lint.stderr.strip(), "lint-clean", "no diagnostics", self.output(lint))
        # Printer bytes are an independent layout oracle for this subset.
        fmt = self.command([self.tool("ouro-fmt"), path], directory, "fmt-layout")
        self.require(fmt.ok and fmt.stdout == source, "fmt-layout", source, self.output(fmt))
        result = self.command([self.tool("ouro-fmt"), "--check", path], directory, "fmt-check-clean")
        self.require(result.ok, "fmt-check-clean", "exit 0", self.output(result))
        messy = directory / "messy.ouro"
        messy.write_bytes((source.rstrip() + "  \n\n\n").replace("\n", "\r\n").encode())
        result = self.command([self.tool("ouro-fmt"), "--check", messy], directory, "fmt-check-dirty")
        self.require(result.returncode == 1, "fmt-check-dirty", "exit 1", self.output(result))
        result = self.command([self.tool("ouro-fmt"), messy], directory, "fmt-roundtrip")
        self.require(result.ok and result.stdout == source, "fmt-roundtrip", source, self.output(result))
        messy.write_text(result.stdout, encoding="utf-8", newline="\n")
        again = self.command([self.tool("ouro-fmt"), messy], directory, "fmt-idempotent")
        self.require(again.ok and again.stdout == result.stdout, "fmt-idempotent", result.stdout, self.output(again))
        self.require(self.accepts(messy) == core, "fmt-core-equality", core, "core differs")
        commented = directory / "commented.ouro"
        commented.write_text("-- leading generated trivia\n\n" + source + "-- trailing generated trivia\n", encoding="utf-8", newline="\n")
        self.require(self.accepts(commented) == core, "comment-core-equality", core, "core differs")
        renamed = directory / "renamed.ouro"
        renamed.write_text(gen.program(gen.alpha_rename(expr)), encoding="utf-8", newline="\n")
        self.require(self.accepts(renamed) == core, "alpha-core-equality", core, "core differs")
        actual = self.native(path)
        expected = gen.nat_output(gen.evaluate(expr))
        self.require(actual.ok and actual.stdout == expected, "runtime-reference", expected, self.output(actual))

    def negative(self, mutation):
        self.case_id = f"surface-{self.seed}-{mutation.name}"
        self.input = {"source": mutation.source, "mutation": mutation.name, "diagnostics": mutation.diagnostics,
                      "tool": mutation.tool, "fuel": mutation.fuel, "dependencies": mutation.dependencies}
        directory = self.work / "cases" / self.case_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "bad.ouro"
        path.write_text(mutation.source, encoding="utf-8", newline="\n")
        units = []
        for name, source in mutation.dependencies:
            dep = directory / name
            dep.write_text(source, encoding="utf-8", newline="\n")
            units.append(dep)
        if units:
            units.append(path)
        if mutation.tool == "lint":
            result = self.command([self.tool("ouro-lint"), path], directory, "lint-negative")
        else:
            result, _ = self.check(path, units=units, fuel=mutation.fuel)
        self.summary.negative_checks += 1
        self.count("negative_kinds", mutation.name)
        output = result.stderr + result.stdout
        # Token boundaries keep code=1 from accidentally matching code=11.
        found = any(re.search(re.escape(code) + r"(?![0-9A-Za-z_-])", output) for code in mutation.diagnostics)
        if result.returncode == 0:
            raise StepFailure(mutation.name, list(mutation.diagnostics), self.output(result), "wrong-accept")
        self.require(found, mutation.name, list(mutation.diagnostics), self.output(result))
        if mutation.tool == "check":
            self.require(not path.with_suffix(".checked").exists(), "negative-no-artifact", "no accepted artifact", "artifact emitted")

    def replay_input(self, value):
        from ourosmith.surface.corpus import validate_input
        from ourosmith.surface.forms import run_forms
        from ourosmith.surface.tools import run_tools

        validate_input(value)
        self.summary.cases += 1
        self.input = value
        try:
            if "ast" in value:
                self.positive(gen.Expr.from_json(value["ast"]))
            elif "mutation" in value:
                original = next((m for m in mutations(self.seed) if m.name == value["mutation"]), None)
                self.negative(Mutation(value["mutation"], value["source"], tuple(value["diagnostics"]),
                                       value.get("tool", original.tool if original else "check"),
                                       value.get("fuel", original.fuel if original else 999999),
                                       tuple(tuple(dep) for dep in value.get("dependencies", ()))))
            elif value["recipe"].startswith("form-"):
                run_forms(self, only=value["recipe"][5:], saved=value)
            else:
                run_tools(self, only=value["recipe"], saved=value)
        except StepFailure as failure:
            self.record(failure)

    def run_seed(self, index, seed):
        self.seed, self.case_id = seed, f"surface-{seed}"
        expr = gen.generate(seed, self.depth)
        self.input = {"ast": expr.json(), "source": gen.program(expr), "expected": gen.evaluate(expr)}
        self.summary.cases += 1
        try:
            self.positive(expr)
        except StepFailure as failure:
            self.record(failure, expr)
        if index < 2 or (self.report.profile == "nightly" and index % 20 == 0):
            for mutation in mutations(seed):
                try:
                    self.negative(mutation)
                except StepFailure as failure:
                    self.record(failure)

    def seed_report(self, item):
        index, seed = item
        report = Report(profile=self.report.profile, generator_hash=self.report.generator_hash,
                        seeds=[seed], command=self.report.command)
        worker = SurfaceRunner(report, self.work / "seeds" / f"{index}-{seed}", [seed], depth=self.depth,
                               timeout=self.timeout, memory_mb=self.memory_mb, shrink_budget=self.shrink_budget,
                               overrides=self.overrides)
        worker.run_seed(index, seed)
        return report

    def recipe_report(self, item):
        from ourosmith.surface.tools import run_tools

        index, name = item
        report = Report(profile=self.report.profile, generator_hash=self.report.generator_hash,
                        seeds=[self.seed], command=self.report.command)
        worker = SurfaceRunner(report, self.work / "recipes" / str(index), [self.seed], depth=self.depth,
                               timeout=self.timeout, memory_mb=self.memory_mb, shrink_budget=self.shrink_budget,
                               overrides=self.overrides)
        worker.seed = self.seed
        started = time.perf_counter()
        run_tools(worker, only=name)
        report.timing["surface.recipe." + name + "_s"] = time.perf_counter() - started
        return report

    def merge_seed(self, report):
        layer = report.layer("surface")
        for key in ("cases", "positive_checks", "negative_checks", "property_checks"):
            setattr(self.summary, key, getattr(self.summary, key) + getattr(layer, key))
        for group, counts in layer.coverage.items():
            for name, count in counts.items():
                self.coverage[group][name] = self.coverage[group].get(name, 0) + count
        for reason, count in layer.abstentions.items():
            self.summary.abstain(reason, count)
        self.summary.notes.extend(layer.notes)
        for finding in report.findings:
            self.report.add(finding)
        self.report.gaps.extend(report.gaps)
        self.report.skips.extend(report.skips)
        for name, value in report.sections.items():
            if name in self.report.sections and self.report.sections[name] != value:
                raise ValueError(f"conflicting surface report section: {name}")
            self.report.sections[name] = value
        self.report.timing.update(report.timing)

    def run_recipes(self):
        from ourosmith.surface.tools import PROPERTIES

        # These wrappers may own shared compiler/build outputs. Keep them
        # outside the direct-tool pool, including missing-golden error paths.
        # The line scanner compiles the full frontend dependency graph.
        serial = {"user_test_runner", "compiler_parity", "selftest_missing_golden", "analyzer_lines", "parser_contract"}
        items = [(index, test.__name__) for index, test in enumerate(PROPERTIES)]
        independent = [item for item in items if item[1] not in serial]
        with ThreadPoolExecutor(max_workers=job_count()) as pool:
            reports = dict(zip((name for _, name in independent), pool.map(self.recipe_report, independent), strict=True))
        # Execution order can vary; report order follows the recipe registry.
        for item in items:
            report = self.recipe_report(item) if item[1] in serial else reports[item[1]]
            self.merge_seed(report)

    def run(self):
        started = time.perf_counter()
        if self.seeds:
            self.run_seed(0, self.seeds[0])
            from ourosmith.surface.forms import run_forms

            run_forms(self)
            self.run_recipes()
        # Recipe and expression pools never overlap. Generated samples own
        # independent files, limits, and reports, merged in seed order.
        with ThreadPoolExecutor(max_workers=job_count()) as pool:
            for report in pool.map(self.seed_report, enumerate(self.seeds[1:], 1)):
                self.merge_seed(report)
        from ourosmith.surface.corpus import load

        for record in load():
            self.seed, self.case_id = record["seed"], "regression-" + record["name"]
            self.replay_input(record["input"])
        self.report.timing["surface.total_s"] = time.perf_counter() - started
