"""Native protocol, receipt and replay regressions; no compiler is required."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ourosmith import ROOT
from ourosmith.core.run import CONTROLS, NEGATIVES, OPERATIONS, RELATIONS, CoreConfig, Failure, inspect_result, read_recipe, recipe, shrink
from ourosmith.limits import RunResult


def success_stdout(seed=1, depth=1):
    """One-definition wire fixture, independent of the parser's regex builder."""
    prefix = f"ok smith seed={seed} "
    rows = [prefix + "domain=" + str(family) for family in range(18)]
    rows += [prefix + "generated=400 family=0 references=", prefix + "delta=400",
             f"forms seed={seed} selected=" + ",".join("0" for _ in range(depth))]
    rows += [prefix + name for name in OPERATIONS + RELATIONS + CONTROLS]
    rows += [prefix + "negative=" + name for name in NEGATIVES]
    rows += [prefix + "negative=rel-out-of-scope target=1", prefix + "cold-delta=400",
             f"ok compiler-smith seed={seed} definitions=1 depth={depth} max-defs=1 domains=18 operations=27 relations=12 negatives=32 controls=3",
             "ok compiler-smith complete"]
    return "\n".join(rows) + "\n"


def wire(stdout=None, *, stderr="", status="ok", code=0):
    return RunResult(status, code, success_stdout() if stdout is None else stdout, stderr, 0, 0)


class NativeHarnessTests(unittest.TestCase):
    def test_profile_evidence_rejects_rehashed_partial_counts_and_native_domains(self):
        from ourosmith.corpus import RETAINED_LAWS, RETAINED_REJECTIONS
        from ourosmith.core.run import FORMS
        from ourosmith.evidence import profile_problems
        from ourosmith.native import SMITH_ENTRY, RETAINED_ENTRY
        from ourosmith.report import Report

        report = Report(profile="kernel", generator_hash="current", seeds=list(range(1, 101)), command="selftest")
        kernel = report.layer("kernel")
        kernel.cases, kernel.positive_checks, kernel.negative_checks, kernel.property_checks = 100, 5098, 3200, 10094
        kernel.coverage = {"definitions": 298, "nonfirst_rel": 79, "earlier_references": 190,
            "domains": {str(number): 100 for number in range(18)},
            "forms": {name: 1 for name in FORMS},
            "negative_kinds": {name: 100 for name in NEGATIVES + ["rel-out-of-scope"]},
            "properties": {**{name: 100 for name in OPERATIONS + RELATIONS + CONTROLS},
                           **{name: 298 for name in ("generated-independent", "delta-independent", "cold-independent")}}}
        retained = report.layer("kernel-corpus")
        retained.cases = retained.property_checks = len(RETAINED_LAWS)
        retained.positive_checks = len(RETAINED_LAWS) - len(RETAINED_REJECTIONS)
        retained.negative_checks = len(RETAINED_REJECTIONS)
        retained.coverage = {"case_ids": {name: 1 for name in RETAINED_LAWS}, "recipes": {}}
        report.sections = {"native_drivers": {SMITH_ENTRY: {}, RETAINED_ENTRY: {}}, "provenance": {},
                           "completeness": {"kernel": {"checked_exercised": True, "problems": []}}, "configuration": {}}
        value = report.body()
        def rehash(data):
            data["fingerprint"] = hashlib.sha256(json.dumps(
                {key: item for key, item in data.items() if key != "fingerprint"}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            return data
        with patch("ourosmith.evidence.generator_hash", return_value="current"), \
             patch("ourosmith.evidence.provenance_problems", return_value=[]), \
             patch("ourosmith.native.evidence_problems", return_value=[]), \
             patch("ourosmith.corpus.load_cases", return_value=[]):
            self.assertEqual(profile_problems(rehash(value), "kernel", {}), [])
            changes = [(("seeds",), list(range(1, 100))),
                       (("summary", "layers", "kernel", "property_checks"), 10093),
                       (("summary", "layers", "kernel", "coverage", "domains", "17"), 99),
                       (("summary", "layers", "kernel", "coverage", "forms"), {}),
                       (("summary", "layers", "kernel", "coverage", "nonfirst_rel"), 0),
                       (("summary", "layers", "kernel", "coverage", "earlier_references"), 0),
                       (("summary", "layers", "kernel-corpus", "property_checks"), 0),
                       (("summary", "layers", "kernel-corpus", "negative_checks"), 0),
                       (("sections", "native_drivers"), {SMITH_ENTRY: {}}),
                       (("sections", "configuration", "depth"), 4),
                       (("sections", "completeness", "kernel"), None),
                       (("summary", "layers", "kernel", "coverage"), None),
                       (("sections",), None), (("skips",), [{"what": "unavailable"}])]
            for keys, replacement in changes:
                changed = copy.deepcopy(value)
                target = changed
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = replacement
                with self.subTest(keys=keys):
                    self.assertTrue(profile_problems(rehash(changed), "kernel", {}))

    def test_native_migration_keeps_distinct_retirement_and_resource_obligations(self):
        from ourosmith import migration_contracts as mapping

        for name in mapping.JSON_ONLY:
            strategies, note, metadata = mapping.kernel_case(name, True)
            self.assertEqual(strategies, [mapping.RETIRED_CORE])
            self.assertTrue(note)
            self.assertEqual(metadata, {"retired_owner": "legacy-json-transport"})
        for name in (*mapping.HOTPATH_LAWS[2:], "depth: fail-closed on million-node terms"):
            self.assertEqual(mapping.LAW_OWNERS[name], ["external/law/" + name])
        string, note, _ = mapping.kernel_case("string_literal_axiom", False)
        self.assertIn("kernel-corpus/case_ids/string_literal_intrinsic", string)
        self.assertIn("kernel-corpus/case_ids/string_literal_axiom", string)
        self.assertIn("superseded", note)
        self.assertEqual(len(mapping.LEGACY_CORE_OWNER_PATHS), 41)
        self.assertEqual(len(set(mapping.LEGACY_CORE_OWNER_PATHS)), 41)
        self.assertNotIn("scripts/ourosmith/core/run.py", mapping.LEGACY_CORE_OWNER_PATHS)

    def test_pinned_archive_rebuilds_current_categories_without_old_coverage(self):
        from ourosmith import migration
        from ourosmith.selftest import migration_archive

        archived, snapshot, manifest, report, _external = migration_archive()
        archived.pop("contracts")
        archived["categories"][0]["strategies"] = ["external/old-owner/example"]
        historical_hash = migration.archive_hash(archived)
        with patch.object(migration, "LEGACY_ARCHIVE_SHA256", historical_hash), \
             patch.object(migration, "legacy_snapshot", return_value=(snapshot, manifest)), \
             patch.object(migration, "tracked_legacy", return_value=[]), \
             patch.object(migration, "MATRIX", SimpleNamespace(is_file=lambda: True, read_text=lambda **_: json.dumps(archived))), \
             patch.object(migration, "references", return_value=([], [])), \
             patch.object(migration, "external_evidence", return_value=set()):
            migration.validate_archive(archived)
            for keys, value in ((("categories", 0, "strategies"), []),
                                (("categories", 0, "status"), "gap"),
                                (("categories", 0, "missing_strategies"), ["missing"]),
                                (("recoverability", "files_sha256", archived["legacy_files"][0]), "0" * 64)):
                changed = copy.deepcopy(archived)
                target = changed
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = value
                with self.subTest(keys=keys), self.assertRaises(ValueError):
                    migration.validate_archive(changed)
            current = migration.build_matrix({"fingerprint": "new", "summary": {"layers": {}}})
            self.assertEqual(current["contracts"], migration.contracts.CONTRACT_KIND)
            self.assertFalse(current["deletion_ready"])
            self.assertGreater(current["summary"]["gaps"], 0)
            self.assertEqual(current["previous_contracts"]["archive_sha256"], historical_hash)
            self.assertEqual(current["pre_retirement_source"], archived["pre_retirement_source"])
            self.assertEqual(current["categories"][0]["strategies"], ["surface/negative_kinds/lambda-argument-domain"])
            self.assertNotEqual(current["evidence_fingerprint"], archived["evidence_fingerprint"])

    def config(self):
        return CoreConfig([1], "pr", 1, 1, 0)

    def test_complete_native_protocol_and_empty_form_depth(self):
        coverage, failure = inspect_result(wire(), 1, self.config())
        self.assertIsNone(failure)
        self.assertEqual(coverage, {"definitions": 1, "families": [0], "references": [], "forms": [0], "rel_target": 1})
        coverage, failure = inspect_result(wire(success_stdout(depth=0)), 1, CoreConfig([1], "pr", 0, 1, 0))
        self.assertIsNone(failure)
        self.assertEqual(coverage["forms"], [])

    def test_native_protocol_rejects_missing_duplicate_reordered_and_unknown_rows(self):
        rows = success_stdout().splitlines()
        invalid = [rows[:-1], rows + rows[-1:], rows[:1] + rows, [rows[1], rows[0], *rows[2:]],
                   [rows[0].replace("seed=1", "seed=2"), *rows[1:]],
                   [*rows[:-2], rows[-2].replace("negatives=32", "negatives=31"), rows[-1]]]
        for values in invalid:
            with self.subTest(values=values[:2]):
                _, failure = inspect_result(wire("\n".join(values) + "\n"), 1, self.config())
                self.assertEqual(failure.prop, "native-protocol")

    def test_native_protocol_rejects_false_generation_metadata(self):
        value = success_stdout()
        invalid = [value.replace("family=0", "family=18"), value.replace("references=", "references=400"),
                   value.replace("references=", "references=399"), value.replace("references=", "references=,"),
                   value.replace("selected=0", "selected="), value.replace("generated=400", "generated=401")]
        for stdout in invalid:
            with self.subTest(stdout=stdout[400:470]):
                _, failure = inspect_result(wire(stdout), 1, self.config())
                self.assertEqual(failure.prop, "native-protocol")

    def test_native_process_failure_never_satisfies_a_semantic_expectation(self):
        for status, code, classification in (("timeout", None, "timeout"), ("memory", None, "memory"),
                                              ("ok", 0xC0000005, "crash"), ("spawn-error", None, "oracle-unavailable")):
            _, failure = inspect_result(wire(status=status, code=code), 1, self.config())
            self.assertEqual(failure.classification, classification)
        for result in (wire(stderr="unexpected"), wire(code=1), wire(code=2)):
            self.assertIsNotNone(inspect_result(result, 1, self.config())[1])

    def test_semantic_failure_requires_the_exact_next_property_and_reason(self):
        value = success_stdout()
        prefix = value.split("ok smith seed=1 negative=coverage\n", 1)[0]
        for detail, category in (("coverage accepted input=bad", "wrong-accept"),
                                 ("coverage expected=900:body:case-metadata actual=900:body:resource-limit input=bad", "wrong-class")):
            _, failure = inspect_result(wire(prefix, stderr="not ok compiler-smith seed=1 negative=coverage " + detail + "\n", code=1), 1, self.config())
            self.assertEqual((failure.prop, failure.classification, failure.detail), ("negative=coverage", category, detail))
        _, failure = inspect_result(wire(prefix, stderr="not ok compiler-smith seed=1 negative=ctor-index wrong\n", code=1), 1, self.config())
        self.assertEqual(failure.prop, "native-protocol")

    def test_native_failures_cover_generator_and_cold_environment_paths(self):
        for stdout, payload, prop in (("", "generator missing earlier definition", "generator"),
                                      ("", "environment 1:plan:duplicate-name:1", "environment"),
                                      (success_stdout().split("ok smith seed=1 negative=rel-out-of-scope", 1)[0], "generator-rel no variable", "generator-rel"),
                                      (success_stdout().split("ok smith seed=1 cold-delta=400", 1)[0], "cold-environment 1:body:resource-limit", "cold-environment")):
            _, failure = inspect_result(wire(stdout, stderr="not ok compiler-smith seed=1 " + payload + "\n", code=1), 1, self.config())
            self.assertEqual(failure.prop, prop)

    def test_recipe_is_exact_and_hash_bound(self):
        good = recipe(CoreConfig([17], "kernel", 2, 3), 17, "frozen")
        self.assertEqual(read_recipe(good, "frozen"), CoreConfig([17], "kernel", 2, 3, 0))
        invalid = [{**good, key: value} for key, value in (("seed", True), ("seed", -1), ("seed", 2**32),
                    ("depth", -1), ("depth", 9), ("max_defs", 0), ("max_defs", 17), ("profile", "unknown"), ("generator_hash", "stale"))]
        invalid += [{**good, "decls": []}, {key: value for key, value in good.items() if key != "depth"}, {"decls": []}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                read_recipe(value, "frozen")

    def test_shrink_preserves_property_diagnostic_and_budget(self):
        config = CoreConfig([17], "pr", 4, 4, 4)
        wanted = Failure("negative=coverage", "wrong-class", "coverage expected=case-metadata actual=type-mismatch input=original")
        attempts = []
        def evaluate(candidate, seed):
            attempts.append((candidate.depth, candidate.max_defs, seed))
            if candidate.max_defs == 1:
                return Failure(wanted.prop, wanted.classification, "coverage expected=case-metadata actual=resource-limit")
            return Failure(wanted.prop, wanted.classification, "coverage expected=case-metadata actual=type-mismatch input=minimal")
        smallest = shrink(config, 17, wanted, evaluate)
        self.assertEqual((smallest.depth, smallest.max_defs), (0, 2))
        self.assertLessEqual(len(attempts), 4)
        self.assertTrue(all(seed == 17 for _, _, seed in attempts))
        calls = []
        unchanged = shrink(CoreConfig([17], "pr", 4, 4, 1), 17, wanted,
                           lambda cfg, seed: calls.append(seed) or Failure("other-property", "wrong-class", wanted.detail))
        self.assertEqual((unchanged.depth, unchanged.max_defs), (4, 4))
        self.assertEqual(len(calls), 1)

    def test_native_profile_seed_and_size_budgets_are_retained(self):
        profiles = json.loads((ROOT / "quality/smith/seeds.json").read_text(encoding="utf-8"))["profiles"]
        expected = {"pr": (1, 40, 4, 4), "kernel": (1, 100, 5, 5), "nightly": (100000, 400, 6, 6)}
        self.assertEqual({name: tuple(profiles[name][key] for key in ("seed_base", "seeds", "depth", "max_defs")) for name in expected}, expected)

    def test_native_inventory_retains_new_source_items_and_separate_owners(self):
        from ourosmith.inventory import code_strategies, compare, source_inventory

        value, strategies = source_inventory(), code_strategies()
        with patch("ourosmith.inventory.surface_inventory.compare", return_value=[]):
            self.assertEqual(compare(value, strategies), [])
            grown = copy.deepcopy(value)
            grown["term_constructors"].append("CNewConstructor")
            self.assertTrue(any("CNewConstructor" in message for message in compare(grown, strategies)))
            grown = copy.deepcopy(value)
            grown["primitives"].append("PrimitiveNewOperation")
            self.assertTrue(any("PrimitiveNewOperation" in message for message in compare(grown, strategies)))
            self.assertTrue(any("was not exercised" in message for message in compare(value, strategies, coverage={})))
        kernel = strategies["layers"]["kernel"]
        self.assertIn("PrimitiveRawLoad", kernel["external_owners"])
        self.assertNotIn("PrimitiveRawLoad", kernel["primitives"])

    def test_retained_protocol_preserves_exact_inventory_and_nonzero_semantics(self):
        from ourosmith.corpus import RETAINED_LAWS, inspect_retained

        good = "\n".join("PASS " + name for name in RETAINED_LAWS) + "\nCOMPILER_RETAINED: PASS\n"
        self.assertEqual(inspect_retained(wire(good)), [])
        failed = good.replace("PASS wrong_body_type", "FAIL wrong_body_type: accepted; expected decl=90/body/type-mismatch").replace("COMPILER_RETAINED: PASS", "COMPILER_RETAINED: FAIL")
        self.assertEqual(inspect_retained(wire(failed, code=1)), [("wrong_body_type", "property-violation", "accepted; expected decl=90/body/type-mismatch")])
        for result in (wire(good, code=1), wire(failed), wire(good + "PASS stale\n"), wire(good.replace("PASS nat_id\n", "")), wire(good, status="memory")):
            self.assertTrue(inspect_retained(result))

    def test_legacy_corpus_and_stale_native_recipes_are_rejected(self):
        from ourosmith.corpus import CorpusCase, check_case, finding_case

        self.assertTrue(check_case(CorpusCase(Path("old.json"), {"kind": "ouro.kernel-core-artifact.v1", "decls": []})))
        finding = {"layer": "kernel", "seed": 1, "generator_hash": "frozen", "prop": "negative=coverage",
                   "classification": "wrong-accept", "minimal_input": recipe(self.config(), 1, "frozen"), "actual": "accepted input=bad"}
        with patch("ourosmith.core.run.generator_hash", return_value="frozen"):
            good = finding_case(finding, "coverage")
            self.assertEqual(check_case(CorpusCase(Path("coverage.json"), good), check_format=False), [])
            self.assertTrue(check_case(CorpusCase(Path("coverage.json"), {**good, "expect": "any-rejection"}), check_format=False))
            for name in ("../escape", "C:/escape", "nested/name", ""):
                with self.assertRaises(ValueError):
                    finding_case(finding, name)
        self.assertTrue(check_case(CorpusCase(Path("coverage.json"), good), check_format=False))

    def test_empty_explicit_recipe_corpus_does_not_execute_a_driver(self):
        from ourosmith.corpus import run_corpus
        from ourosmith.report import Report

        value = Report(profile="pr", generator_hash="test", seeds=[], command="test")
        with patch("ourosmith.corpus.load_cases", return_value=[]):
            run_corpus(value, None, directory=ROOT / "_build/empty-native-corpus")
        self.assertFalse(value.passed)
        self.assertTrue(value.blocking_gaps)

    @contextlib.contextmanager
    def receipt_fixture(self):
        from ourosmith.native import digest
        from repo_support import hash_json

        work = ROOT / "_build/smith/selftest"
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as directory:
            directory = Path(directory)
            executable, compiler = directory / "driver.exe", directory / "producer.exe"
            executable.write_bytes(b"binary fixture")
            compiler.write_bytes(b"producer fixture")
            entry = "tests/fixture.ouro"
            sources = {entry: "a" * 64, "runtime/fixture.c": "b" * 64, "scripts/fixture.py": "c" * 64}
            inputs = {"kind": "ouro.native-tool-build.v1", "entry": entry, "fuel": 16000, "sources": sources,
                      "compiler_sha256": digest(compiler), "cc": "fixture", "cc_sha256": "d" * 64,
                      "platform": "fixture", "machine": "fixture", "cflags": [], "link_flags": [], "environment": {}}
            data = {"kind": "ouro.native-tool-build.v1", "cache": "miss", "inputs": inputs,
                    "key": hash_json(inputs), "binary_sha256": digest(executable)}
            path = Path(str(executable) + ".build.json")
            def save(value):
                path.write_text(json.dumps(value), encoding="utf-8")
            save(data)
            with patch("ourosmith.native.source_inputs", return_value=([entry], sources)):
                yield SimpleNamespace(directory=directory, executable=executable, compiler=compiler, entry=entry,
                                      sources=sources, data=data, save=save)

    def test_native_receipt_binds_every_source_entry_producer_and_binary(self):
        from ourosmith.native import receipt_for
        from repo_support import hash_json

        with self.receipt_fixture() as fixture:
            self.assertEqual(receipt_for(fixture.executable, fixture.entry, fixture.compiler)[0], fixture.data)
            for cache in ("hit", "installed-hit"):
                fixture.save({**fixture.data, "cache": cache})
                self.assertEqual(receipt_for(fixture.executable, fixture.entry, fixture.compiler)[0]["cache"], cache)
            invalid = []
            for missing in ("runtime/fixture.c", "scripts/fixture.py", fixture.entry):
                changed = copy.deepcopy(fixture.data)
                del changed["inputs"]["sources"][missing]
                invalid.append(changed)
            for key, value in (("entry", "tests/wrong.ouro"), ("compiler_sha256", "0" * 64), ("fuel", True)):
                changed = copy.deepcopy(fixture.data)
                changed["inputs"][key] = value
                invalid.append(changed)
            changed = copy.deepcopy(fixture.data)
            del changed["inputs"]["cc"]
            invalid.append(changed)
            for changed in invalid:
                changed["key"] = hash_json(changed["inputs"])
                fixture.save(changed)
                with self.assertRaises(ValueError):
                    receipt_for(fixture.executable, fixture.entry, fixture.compiler)
            fixture.save(fixture.data)
            fixture.executable.write_bytes(b"changed binary")
            with self.assertRaises(ValueError):
                receipt_for(fixture.executable, fixture.entry, fixture.compiler)

    def test_native_evidence_requires_strict_check_and_complete_current_receipt(self):
        from ourosmith.native import NativeProgram, evidence_problems

        with self.receipt_fixture() as fixture:
            program = NativeProgram(fixture.entry, fixture.executable, fixture.compiler, fixture.data,
                                    [fixture.entry], fixture.sources, fixture.directory, 100, hashlib.sha256(b"CHECK_OK\n").hexdigest())
            value = program.evidence()
            self.assertEqual(evidence_problems(value, entry=fixture.entry), [])
            for bad in ({**value, "entry": "tests/wrong.ouro"}, {**value, "sources": {}},
                        {**value, "strict_check": {"exit_code": False, "stdout_sha256": value["strict_check"]["stdout_sha256"]}},
                        {**value, "strict_check": {}}, {**value, "binary": "../escape"}):
                self.assertTrue(evidence_problems(bad, entry=fixture.entry))

    def test_reused_native_driver_is_strict_checked_and_stale_output_is_replaced(self):
        from ourosmith.native import prepare

        with self.receipt_fixture() as fixture:
            with patch("ourosmith.native.environment", return_value={}), \
                 patch("ourosmith.native.run_limited", return_value=wire("CHECK_OK\n")) as execute:
                program = prepare(fixture.entry, fixture.directory / "run", fixture.compiler,
                                  memory_mb=100, executable=fixture.executable, log=lambda _line: None)
                self.assertEqual(execute.call_count, 1)
                self.assertEqual(execute.call_args.args[0][1:4], ["check", fixture.entry, "999999"])
                (program.work / "seed.stdout").write_text("stale success", encoding="utf-8")
                execute.return_value = wire("actual failure", code=2)
                result = program.run([], "seed", 1)
                self.assertFalse(result.ok)
                self.assertEqual((program.work / "seed.stdout").read_text(), "actual failure")

    def test_failed_strict_source_check_cannot_reuse_a_binary(self):
        from ourosmith.native import prepare

        with self.receipt_fixture() as fixture:
            for result in (wire("CHECK_OK\n", code=1), wire("CHECK_OK\n", stderr="error"), wire("CHECK_OK\nCHECK_OK\n"), wire("CHECK_OK\n", status="memory")):
                with patch("ourosmith.native.environment", return_value={}), patch("ourosmith.native.run_limited", return_value=result), self.assertRaises(ValueError):
                    prepare(fixture.entry, fixture.directory / "run", fixture.compiler, memory_mb=100, executable=fixture.executable, log=lambda _line: None)

    def test_kernel_finding_cli_uses_exact_saved_bounds_and_refuses_a_stale_hash(self):
        import ouro_smith

        finding = {"layer": "kernel", "seed": 17, "generator_hash": "frozen", "profile": "kernel", "prop": "law",
                   "minimal_input": recipe(CoreConfig([17], "kernel", 2, 1), 17, "frozen")}
        work = ROOT / "_build/smith/selftest"
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as directory:
            directory = Path(directory)
            path = directory / "finding.json"
            path.write_text(json.dumps(finding), encoding="utf-8")
            with patch("ourosmith.core.run.generator_hash", return_value="frozen"), \
                 patch.object(ouro_smith, "compiler_for", return_value=directory / "fixture-producer"), \
                 patch.object(ouro_smith, "native_program", return_value=object()) as program, \
                 patch.object(ouro_smith, "bind"), patch.object(ouro_smith, "CoreRunner") as runner, \
                 patch.object(ouro_smith, "finish_report", return_value=0), contextlib.redirect_stdout(io.StringIO()):
                result = ouro_smith.main(["replay", "--finding", str(path), "--seed", "999", "--depth", "8", "--out", str(directory / "replay")])
                self.assertEqual(result, 0)
                self.assertEqual(runner.call_args.args[0], CoreConfig([17], "kernel", 2, 1, 0))
                program.assert_called_once()
            with patch("ourosmith.core.run.generator_hash", return_value="different"), \
                 patch.object(ouro_smith, "native_program") as program, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(ouro_smith.main(["replay", "--finding", str(path), "--out", str(directory / "stale")]), 1)
                program.assert_not_called()

    def test_malformed_checker_campaign_never_authorizes_retirement(self):
        from ourosmith.evidence import checker_evidence_problems

        self.assertTrue(checker_evidence_problems({}, [], compiler=ROOT / "_build/nonexistent"))
