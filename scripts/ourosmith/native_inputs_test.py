"""Coverage and native-report laws for bounded manifest batches."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ourosmith import native_inputs
from ourosmith.limits import RunResult


class ManifestBatchesTests(unittest.TestCase):
    def test_expansions_and_originals_cover_once(self):
        ids = [f"ERGO.expansion-marked-{index:03d}" for index in range(52)]
        ids += ["ERGO.effectful", "ERGO.if-expression", "REC.record-negative", "IMP.ignored"]
        text = "".join(name + "\tunchanged native fields\n" for name in ids)
        batches = native_inputs.manifest_batches(text, "ERGO.,REC.")
        selected = [name for _prefixes, names in batches for name in names]
        self.assertEqual(set(selected), set(ids[:-1]))
        self.assertEqual(len(selected), len(set(selected)))
        self.assertTrue(all(0 < len(names) <= 50 for _prefixes, names in batches))
        for prefixes, names in batches:
            self.assertEqual({name for name in ids if name.startswith(tuple(prefixes))}, set(names))

    def test_current_generated_manifest_choices_cover_once(self):
        writes = []
        row_costs: dict[str, int] = {}
        with patch.object(native_inputs, "write", side_effect=lambda path, text: writes.append((path, text))):
            native_inputs.prepare_manifest(native_inputs.ROOT / "_build/manifest-batch-plan-test", 1,
                                           row_costs=row_costs)
        masters = [text for path, text in writes if path.name == "manifest.tsv"]
        self.assertEqual(len(masters), 1)
        master = masters[0]
        ids = [line.split("\t", 1)[0] for line in master.splitlines()]
        self.assertEqual(len(ids), 545)
        self.assertEqual(len(set(ids)), len(ids))
        self.assertTrue(row_costs)
        self.assertLessEqual(row_costs.keys(), set(ids))
        for prefix, count in (("ERGO.,REC.", 457), ("IMP.", 37), ("CHECK.", 51),
                              ("ERGO.,REC.,IMP.,CHECK.", 545), ("ERGO.,REC.,IMP.", 494)):
            with self.subTest(prefix=prefix):
                expected = {name for name in ids if name.startswith(tuple(prefix.split(",")))}
                self.assertEqual(len(expected), count)
                batches = native_inputs.manifest_batches(master, prefix, row_costs=row_costs)
                selected = [name for _prefixes, names in batches for name in names]
                self.assertEqual(set(selected), expected)
                self.assertEqual(len(selected), count)
                self.assertTrue(all(0 < len(names) <= 29 for _prefixes, names in batches))
                self.assertEqual(batches, native_inputs.manifest_batches("\n".join(reversed(master.splitlines())),
                                                                        prefix, row_costs=row_costs))
                for prefixes, names in batches:
                    self.assertEqual({name for name in ids if name.startswith(tuple(prefixes))}, set(names))
        self.assertEqual(native_inputs.manifest_batches(master, "ERGO.,REC.,IMP.", row_costs=row_costs),
                         native_inputs.manifest_batches(master, "IMP.,ERGO.,REC.", row_costs=row_costs))

    def test_selected_manifest_writes_only_matching_fixture_files(self):
        root = native_inputs.ROOT / "_build/manifest-batch-plan-test"

        def generated(prefixes=None):
            files: dict[Path, bytes] = {}
            costs: dict[str, int] = {}

            def record(path, text):
                files[path.relative_to(root)] = text.encode("utf-8")

            with patch.object(native_inputs, "write", side_effect=record):
                native_inputs.prepare_manifest(root, 1, row_costs=costs, prefixes=prefixes)
            return files, costs

        master_path = Path("manifest.tsv")
        complete, complete_costs = generated()
        master = complete.pop(master_path)
        for prefixes, count in ((("ERGO.", "REC."), 457), (("IMP.",), 37), ((), 0)):
            with self.subTest(prefixes=prefixes):
                files, costs = generated(prefixes)
                self.assertEqual(files.pop(master_path), master)
                self.assertEqual(sum(path.name == "main.ouro" and len(path.parts) == 2 for path in files), count)
                self.assertEqual(files, {
                    path: text for path, text in complete.items()
                    if len(path.parts) == 1 or path.parts[0].startswith(prefixes)
                })
                self.assertEqual(costs, {name: cost for name, cost in complete_costs.items() if name.startswith(prefixes)})

    def test_only_batches_over_the_cost_limit_are_split(self):
        heavy = [f"ERGO.expansion-heavy-{index:02d}" for index in range(5)]
        light = [f"ERGO.expansion-light-{index:02d}" for index in range(12)]
        text = "\n".join([*heavy, *light])
        costs = dict.fromkeys(heavy, 8)
        batches = native_inputs.manifest_batches(text, "ERGO.", row_costs=costs)
        self.assertEqual(batches, [(heavy[:3], heavy[:3]), (heavy[3:], heavy[3:]),
                                   (["ERGO.expansion-l"], light)])

    def test_weighted_split_keeps_exact_prefix_collisions_in_one_batch(self):
        exact = "ERGO.expansion-case"
        longer = exact + "-more"
        text = f"{exact}\n{longer}\n{exact}"
        costs = dict.fromkeys([exact, longer], 16)
        batches = native_inputs.manifest_batches(text, "ERGO.", row_costs=costs)
        self.assertEqual(batches, [(["ERGO.expansion-c"], [exact, longer])])
        self.assertEqual(sum(line.startswith(tuple(batches[0][0])) for line in text.splitlines()), 3)

    def test_weighted_split_keeps_ids_that_do_not_round_trip_as_selectors(self):
        for delimiter in (",", "\0"):
            with self.subTest(delimiter=delimiter):
                ids = [f"ERGO.expansion-a{delimiter}bc", "ERGO.expansion-another"]
                text = "\n".join(ids)
                self.assertEqual(native_inputs.manifest_batches(text, "ERGO.", row_costs=dict.fromkeys(ids, 16)),
                                 [(["ERGO.expansion-a"], ids)])

    def test_letter_prefix_cannot_capture_expansions(self):
        with self.assertRaisesRegex(ValueError, "unexpected rows"):
            native_inputs.manifest_batches("ERGO.e\tkeep\nERGO.expansion-entry\tkeep\n", "ERGO.")

    def test_batch_prefix_cannot_capture_a_row_outside_the_requested_selection(self):
        text = "ERGO.expansion-small\tkeep\nERGO.expansion-sibling\tkeep\n"
        with self.assertRaisesRegex(ValueError, "unexpected rows"):
            native_inputs.manifest_batches(text, "ERGO.expansion-small")

    def test_full_id_prefix_collision_between_chunks_is_rejected(self):
        ids = ["ERGO.case", *[f"ERGO.case-{index:03d}" for index in range(51)]]
        with self.assertRaisesRegex(ValueError, "overlap"):
            native_inputs.manifest_batches("\n".join(ids), "ERGO.")

    def test_empty_selection_is_rejected(self):
        for prefix in ("ERGO.,REC.", " , "):
            with self.subTest(prefix=prefix), self.assertRaisesRegex(ValueError, "no rows"):
                native_inputs.manifest_batches("IMP.only\tkeep\n", prefix)

    def test_duplicate_ids_remain_in_the_same_native_selection(self):
        text = "ERGO.same\tfirst\nERGO.same\tsecond\nERGO.other\tkeep\n"
        batches = native_inputs.manifest_batches(text, "ERGO.")
        self.assertEqual(len(batches), 1)
        prefixes, _names = batches[0]
        self.assertEqual(sum(line.startswith(tuple(prefixes)) for line in text.splitlines()), 3)

    def run_mock(self, change=None, *, jobs=1, memory_mib=6144, out_of_order=False, change_toolchain=False,
                 row_costs=None, toolchain_collection_error=None):
        import local_scheduler
        from ourosmith import host, limits, native

        ids = [f"ERGO.expansion-marked-{index:03d}" for index in range(52)]
        ids += ["ERGO.effectful", "REC.record-negative"]
        calls = []
        completed = []
        parsers = []
        second_complete = Event()
        read_report = native_inputs.manifest_batch_report
        verify_receipt = native.receipt_for
        with tempfile.TemporaryDirectory(prefix="ouro-manifest-batches-") as temporary:
            root = Path(temporary)
            fixtures = root / "manifest-fixtures"
            fixtures.mkdir()
            manifest = fixtures / "manifest.tsv"
            original = "".join(name + "\t" + name + "/main.ouro\tcheck\tfail\t0\tCErr\n" for name in ids)
            manifest.write_text(original, encoding="utf-8", newline="")
            args = SimpleNamespace(out=str(root / "out"), seed=0, prefix=" ERGO., , REC. ", label="ERGONOMICS_SUITE")

            def execute(argv, **options):
                calls.append((argv, options))
                values = dict(arg[2:].split("=", 1) for arg in argv[1:])
                self.assertEqual(values["manifest"], manifest.as_posix())
                self.assertEqual(options["timeout_s"], 300)
                self.assertEqual(options["memory_mb"], 3072)
                prefixes = values["prefix"].split(",")
                selected = [name for name in ids if name.startswith(tuple(prefixes))]
                directory = Path(values["out"])
                index = int(directory.name.removeprefix("batch-"))
                if out_of_order and index == 1:
                    self.assertTrue(second_complete.wait(2), "second batch did not run alongside the first")
                directory.mkdir(parents=True)
                report = {"kind": "ouro.test-manifest-report.v1", "version": "1", "pass": True,
                          "suite": args.label, "manifest": manifest.as_posix(), "root": fixtures.as_posix(),
                          "out": directory.as_posix(), "prefixes": prefixes, "rows": len(selected), "failures": 0,
                          "results": [{"id": name, "status": "pass", "exit_code": 1,
                                       "log": (directory / (name + ".out")).as_posix(), "issue": ""}
                                      for name in selected]}
                result = RunResult("ok", 0, f"native report {index}\n", "", 1.0, 1.0)
                if change:
                    result = change(index, report, result, manifest)
                if not report.pop("omit_report", False):
                    (directory / "manifest-report.json").write_text(json.dumps(report), encoding="utf-8")
                    (directory / "rows.tsv").write_text("".join(name + "|fields\n" for name in selected), encoding="utf-8")
                return result

            def record_report(directory, *args):
                row = read_report(directory, *args)
                index = int(directory.name.removeprefix("batch-"))
                completed.append(index)
                if index == 2:
                    second_complete.set()
                return row

            def receipt(executable, entry, compiler, *, parse_bytes):
                self.assertEqual(compiler, root / "ouro1")
                parsers.append(parse_bytes)
                if toolchain_collection_error and calls:
                    with (patch.object(native, "ROOT", root.resolve()),
                          patch("frontend_regen.capture_unit_inputs", side_effect=SystemExit(toolchain_collection_error))):
                        return verify_receipt(executable, entry, compiler, parse_bytes=parse_bytes)
                digest = "changed" if change_toolchain and calls else executable.name
                return {"key": executable.name, "binary_sha256": digest}, None, None

            def prepare_fixtures(_group, _out, _seed, *, manifest_costs, manifest_prefixes):
                self.assertEqual(manifest_prefixes, ("ERGO.", "REC."))
                if row_costs:
                    manifest_costs.update(row_costs)
                return fixtures

            with patch.object(local_scheduler, "available_memory_mib", return_value=memory_mib), \
                    patch.object(host, "job_count", return_value=jobs), \
                    patch.object(native_inputs, "prepare", side_effect=prepare_fixtures), \
                    patch.object(host, "ensure_tools", return_value=None), \
                    patch.object(host, "binary", side_effect=lambda name: root / name), \
                    patch.object(host, "environment", return_value={}), \
                    patch.object(native, "receipt_for", side_effect=receipt), \
                    patch.object(native_inputs, "manifest_batch_report", side_effect=record_report), \
                    patch.object(limits, "run_limited", side_effect=execute), \
                    contextlib.redirect_stdout(io.StringIO()) as stdout:
                status = native_inputs.run_manifest(args)
            self.assertEqual(len(parsers), 3 if toolchain_collection_error else 4)
            self.assertIsNotNone(parsers[0])
            self.assertTrue(all(parser is parsers[0] for parser in parsers))
            summary = json.loads((root / "out/manifest-batches.json").read_text(encoding="utf-8"))
            ordered = [f"native report {index}" for index in range(1, len(calls) + 1)]
            self.assertEqual([line for line in stdout.getvalue().splitlines() if line.startswith("native report")], ordered)
            self.assertEqual((root / "out/gate.log").read_text(encoding="utf-8").splitlines(), ordered)
            if out_of_order:
                self.assertLess(completed.index(2), completed.index(1))
            return status, summary, calls, original == manifest.read_text(encoding="utf-8")

    def test_parallel_preserves_order_and_uses_only_the_allocated_memory(self):
        def fail_first(index, report, result, _manifest):
            if index == 1:
                report["results"][0].update(status="fail", issue="expected diagnostic was absent")
                report["failures"], report["pass"] = 1, False
                result.returncode = 1
            return result

        for change in (None, fail_first):
            with self.subTest(failure=change is not None):
                serial_status, serial, _calls, unchanged = self.run_mock(change)
                parallel_status, parallel, calls, parallel_unchanged = self.run_mock(change, jobs=20, out_of_order=True)
                self.assertEqual(serial_status, parallel_status)
                self.assertEqual(unchanged, parallel_unchanged)
                for field in ("pass", "selected_ids", "reported_ids"):
                    self.assertEqual(serial[field], parallel[field])
                for left, right in zip(serial["batches"], parallel["batches"], strict=True):
                    self.assertEqual({key: value for key, value in left.items() if key != "report"},
                                     {key: value for key, value in right.items() if key != "report"})
                self.assertEqual(serial["scheduler"]["peak_jobs"], 1)
                self.assertEqual(parallel["scheduler"]["peak_jobs"], 2)
                self.assertEqual(parallel["scheduler"]["peak_memory_mib"], 6144)
                self.assertEqual(len(calls), 3)
                for argv, options in calls:
                    self.assertEqual(options["env"]["OURO_SCHEDULER_JOBS"], "1")
                    self.assertEqual(options["env"]["OURO_SCHEDULER_MEMORY_MIB"], "3072")
                    self.assertEqual(options["env"]["OURO_PREPARED_COLLECTOR"],
                                     Path(argv[0]).with_name("ouro-collect").as_posix())
                    self.assertEqual(options["env"]["OURO1_COMPILER"], Path(argv[0]).with_name("ouro1").as_posix())

    def test_unavailable_toolchain_replaces_previous_success_without_dispatch(self):
        from ouro_smith import main
        from ourosmith import host, limits, native

        missing_binary = FileNotFoundError("native binary unavailable: ouro-test")
        for preparation_error, preparation_exception in (("tool preparation failed", None),
                                                         (None, missing_binary), (None, None)):
            with (self.subTest(preparation_error=preparation_error, preparation_exception=preparation_exception),
                  tempfile.TemporaryDirectory() as temporary):
                out = Path(temporary)
                report = out / "manifest-batches.json"
                report.write_text('{"kind": "ouro.smith-manifest-batches.v1", "pass": true}\n', encoding="utf-8")
                with (patch.object(host, "ensure_tools", return_value=preparation_error,
                                   side_effect=preparation_exception),
                      patch.object(host, "binary", side_effect=Path),
                      patch.object(native, "receipt_for", side_effect=ValueError("stale receipt")) as verify,
                      patch.object(limits, "run_limited") as run,
                      contextlib.redirect_stdout(io.StringIO()) as stdout,
                      contextlib.redirect_stderr(io.StringIO()) as stderr):
                    self.assertEqual(main(["manifest", "--out", str(out), "--prefix=ERGO."]), 1)
                    run.assert_not_called()
                    self.assertEqual(verify.call_count, 0 if preparation_error or preparation_exception else 1)
                if preparation_exception is None:
                    reason = preparation_error or "stale receipt"
                    self.assertEqual(stdout.getvalue(), f"OURO_SMITH: manifest unavailable: {reason}\n")
                    self.assertEqual(stderr.getvalue(), "")
                else:
                    reason = str(preparation_exception)
                    self.assertEqual(stdout.getvalue(), "")
                    self.assertEqual(stderr.getvalue(), f"OURO_SMITH: FAIL {reason}\n")
                self.assertEqual(json.loads(report.read_text(encoding="utf-8")), {
                    "kind": "ouro.smith-manifest-batches.v1", "pass": False, "selected_ids": [],
                    "reported_ids": [], "batches": [], "scheduler": {}, "toolchain_error": reason,
                })

    def test_insufficient_manifest_budget_replaces_previous_success_without_dispatch(self):
        import local_scheduler
        from ouro_smith import main
        from ourosmith import host, limits, native

        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            report = out / "manifest-batches.json"
            report.write_text('{"kind": "ouro.smith-manifest-batches.v1", "pass": true}\n', encoding="utf-8")
            (out / "manifest.tsv").write_text("ERGO.selected\tselected.ouro\tcheck\tfail\t0\tCErr\n"
                                              "IMP.ignored\tignored.ouro\tcheck\tfail\t0\tCErr\n", encoding="utf-8")
            receipt = {"key": "fixture", "binary_sha256": "fixture"}
            with (patch.object(host, "ensure_tools", return_value=None),
                  patch.object(host, "binary", side_effect=Path),
                  patch.object(native, "receipt_for", return_value=(receipt, [], {})),
                  patch.object(native_inputs, "prepare", return_value=out),
                  patch.object(host, "environment", return_value={}),
                  patch.object(host, "job_count", return_value=1),
                  patch.object(local_scheduler, "available_memory_mib", return_value=2048),
                  patch.object(limits, "run_limited") as run,
                  contextlib.redirect_stdout(io.StringIO()) as stdout,
                  contextlib.redirect_stderr(io.StringIO()) as stderr):
                self.assertEqual(main(["manifest", "--out", str(out), "--prefix=ERGO."]), 1)
                run.assert_not_called()
            reason = "0: needs at least 3072 MiB, budget is 2048 MiB"
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), f"OURO_SMITH: FAIL {reason}\n")
            self.assertEqual(json.loads(report.read_text(encoding="utf-8")), {
                "kind": "ouro.smith-manifest-batches.v1", "pass": False, "selected_ids": ["ERGO.selected"],
                "reported_ids": [], "batches": [], "toolchain_error": "",
                "scheduler": {"jobs": 1, "memory_mib": 2048, "peak_tasks": 0, "peak_jobs": 0,
                              "peak_memory_mib": 0, "error": reason},
            })

    def test_changed_prepared_toolchain_fails_even_with_successful_batches(self):
        status, summary, calls, unchanged = self.run_mock(change_toolchain=True)
        self.assertEqual(status, 1)
        self.assertFalse(summary["pass"])
        self.assertTrue(unchanged)
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(batch["pass"] for batch in summary["batches"]))
        self.assertEqual(summary["toolchain_error"], "verified toolchain differs from preparation")

    def test_missing_toolchain_import_fails_after_successful_batches(self):
        error = "FRONTEND_REGEN: FAIL missing tools/removed.ouro"
        status, summary, calls, unchanged = self.run_mock(toolchain_collection_error=error)
        self.assertEqual(status, 1)
        self.assertFalse(summary["pass"])
        self.assertTrue(unchanged)
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(batch["pass"] for batch in summary["batches"]))
        self.assertEqual(summary["toolchain_error"], error)

    def test_full_master_and_native_negative_results_are_preserved(self):
        status, summary, calls, unchanged = self.run_mock()
        self.assertEqual(status, 0)
        self.assertTrue(summary["pass"])
        self.assertTrue(unchanged)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(summary["reported_ids"]), 54)
        self.assertEqual(set(summary["reported_ids"]), set(summary["selected_ids"]))

    def test_native_semantic_failure_does_not_skip_other_batches(self):
        def fail_first(index, report, result, _manifest):
            if index == 1:
                report["results"][0]["status"] = "fail"
                report["results"][0]["issue"] = "expected diagnostic was absent"
                report["failures"], report["pass"] = 1, False
                result.returncode = 1
            return result

        status, summary, calls, _unchanged = self.run_mock(fail_first)
        self.assertEqual(status, 1)
        self.assertFalse(summary["pass"])
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(summary["reported_ids"]), 54)

    def test_heavier_batches_launch_first_without_reordering_the_report(self):
        costs = {f"ERGO.expansion-marked-{index:03d}": 8 for index in range(22, 26)}

        def fail_rec(_index, report, result, _manifest):
            for row in report["results"]:
                if row["id"].startswith("REC."):
                    row.update(status="fail", issue="expected diagnostic was absent")
                    report["failures"], report["pass"] = 1, False
                    result.returncode = 1
            return result

        status, summary, calls, unchanged = self.run_mock(fail_rec, row_costs=costs)
        order = [Path(next(arg.removeprefix("--out=") for arg in argv if arg.startswith("--out="))).name
                 for argv, _options in calls]
        self.assertEqual(order, ["batch-02", "batch-03", "batch-01", "batch-04", "batch-05"])
        self.assertEqual(status, 1)
        self.assertFalse(summary["pass"])
        self.assertFalse(summary["batches"][-1]["native_pass"])
        self.assertTrue(unchanged)
        self.assertEqual(len(summary["reported_ids"]), 54)
        self.assertEqual(set(summary["reported_ids"]), set(summary["selected_ids"]))

    def test_false_report_cannot_pass_even_with_zero_process_exit(self):
        def false_report(_index, report, result, _manifest):
            report["results"][0]["status"] = "fail"
            report["failures"], report["pass"] = 1, False
            return result

        self.assertEqual(self.run_mock(false_report)[0], 1)

    def test_timeout_keeps_failure_with_a_complete_looking_report(self):
        def timeout(_index, _report, result, _manifest):
            result.status, result.returncode = "timeout", -9
            return result

        status, summary, calls, _unchanged = self.run_mock(timeout)
        self.assertEqual(status, 1)
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(batch["status"] == "timeout" for batch in summary["batches"]))

    def test_report_provenance_coverage_and_counts_are_strict(self):
        changes = [lambda report: report.update(manifest="different-master.tsv"),
                   lambda report: report.update(rows=999),
                   lambda report: report["results"].pop(),
                   lambda report: report["results"][0].update(id="ERGO.unknown"),
                   lambda report: report["results"][1].update(id=report["results"][0]["id"]),
                   lambda report: report.update(failures=1),
                   lambda report: report["results"][0].update(status="skip")]
        for change in changes:
            with self.subTest(change=change):
                def alter(_index, report, result, _manifest, mutate=change):
                    mutate(report)
                    return result

                self.assertEqual(self.run_mock(alter)[0], 1)

    def test_missing_report_cannot_pass_with_zero_process_exit(self):
        def omit(_index, report, result, _manifest):
            report["omit_report"] = True
            return result

        status, summary, calls, _unchanged = self.run_mock(omit)
        self.assertEqual(status, 1)
        self.assertFalse(summary["pass"])
        self.assertEqual(len(calls), 3)
        self.assertEqual(summary["reported_ids"], [])

    def test_non_object_report_fails_only_its_batch(self):
        def write_array(index, report, result, _manifest):
            if index == 1:
                (Path(report["out"]) / "manifest-report.json").write_text("[]\n", encoding="utf-8")
                report["omit_report"] = True
            return result

        status, summary, calls, _unchanged = self.run_mock(write_array)
        self.assertEqual(status, 1)
        self.assertFalse(summary["pass"])
        self.assertEqual(len(calls), 3)
        self.assertEqual([batch["pass"] for batch in summary["batches"]], [False, True, True])
        failed, *passed = summary["batches"]
        self.assertEqual(failed["returncode"], 0)
        self.assertEqual(failed["error"], "native manifest report must be a JSON object")
        self.assertEqual(summary["reported_ids"], [name for batch in passed for name in batch["ids"]])

    def test_master_expected_fields_cannot_change(self):
        def alter(_index, _report, result, manifest):
            manifest.write_text(manifest.read_text(encoding="utf-8").replace("\tfail\t", "\tpass\t"), encoding="utf-8")
            return result

        status, summary, _calls, unchanged = self.run_mock(alter)
        self.assertEqual(status, 1)
        self.assertFalse(unchanged)
        self.assertTrue(all(batch["error"] for batch in summary["batches"]))


if __name__ == "__main__":
    unittest.main()
