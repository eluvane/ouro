"""Coverage and native-report laws for bounded manifest batches."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
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
        with patch.object(native_inputs, "write", side_effect=lambda path, text: writes.append((path, text))):
            native_inputs.prepare_manifest(native_inputs.ROOT / "_build/manifest-batch-plan-test", 1)
        masters = [text for path, text in writes if path.name == "manifest.tsv"]
        self.assertEqual(len(masters), 1)
        master = masters[0]
        ids = [line.split("\t", 1)[0] for line in master.splitlines()]
        self.assertEqual(len(ids), 536)
        self.assertEqual(len(set(ids)), len(ids))
        for prefix, count in (("ERGO.,REC.", 448), ("IMP.", 37), ("CHECK.", 51),
                              ("ERGO.,REC.,IMP.,CHECK.", 536), ("ERGO.,REC.,IMP.", 485)):
            with self.subTest(prefix=prefix):
                expected = {name for name in ids if name.startswith(tuple(prefix.split(",")))}
                self.assertEqual(len(expected), count)
                batches = native_inputs.manifest_batches(master, prefix)
                selected = [name for _prefixes, names in batches for name in names]
                self.assertEqual(set(selected), expected)
                self.assertEqual(len(selected), count)
                self.assertTrue(all(0 < len(names) <= 29 for _prefixes, names in batches))
                self.assertEqual(batches, native_inputs.manifest_batches("\n".join(reversed(master.splitlines())), prefix))
                for prefixes, names in batches:
                    self.assertEqual({name for name in ids if name.startswith(tuple(prefixes))}, set(names))
        self.assertEqual(native_inputs.manifest_batches(master, "ERGO.,REC.,IMP."),
                         native_inputs.manifest_batches(master, "IMP.,ERGO.,REC."))

    def test_letter_prefix_cannot_capture_expansions(self):
        with self.assertRaisesRegex(ValueError, "unexpected rows"):
            native_inputs.manifest_batches("ERGO.e\tkeep\nERGO.expansion-entry\tkeep\n", "ERGO.")

    def test_full_id_prefix_collision_between_chunks_is_rejected(self):
        ids = ["ERGO.case", *[f"ERGO.case-{index:03d}" for index in range(51)]]
        with self.assertRaisesRegex(ValueError, "overlap"):
            native_inputs.manifest_batches("\n".join(ids), "ERGO.")

    def test_empty_selection_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no rows"):
            native_inputs.manifest_batches("IMP.only\tkeep\n", "ERGO.,REC.")

    def test_duplicate_ids_remain_in_the_same_native_selection(self):
        text = "ERGO.same\tfirst\nERGO.same\tsecond\nERGO.other\tkeep\n"
        batches = native_inputs.manifest_batches(text, "ERGO.")
        self.assertEqual(len(batches), 1)
        prefixes, _names = batches[0]
        self.assertEqual(sum(line.startswith(tuple(prefixes)) for line in text.splitlines()), 3)

    def run_mock(self, change=None):
        from ourosmith import host, limits

        ids = [f"ERGO.expansion-marked-{index:03d}" for index in range(52)]
        ids += ["ERGO.effectful", "REC.record-negative"]
        calls = []
        with tempfile.TemporaryDirectory(prefix="ouro-manifest-batches-") as temporary:
            root = Path(temporary)
            fixtures = root / "manifest-fixtures"
            fixtures.mkdir()
            manifest = fixtures / "manifest.tsv"
            original = "".join(name + "\t" + name + "/main.ouro\tcheck\tfail\t0\tCErr\n" for name in ids)
            manifest.write_text(original, encoding="utf-8", newline="")
            args = SimpleNamespace(out=str(root / "out"), seed=0, prefix="ERGO.,REC.", label="ERGONOMICS_SUITE")

            def execute(argv, **options):
                calls.append((argv, options))
                values = dict(arg[2:].split("=", 1) for arg in argv[1:])
                self.assertEqual(values["manifest"], manifest.as_posix())
                self.assertEqual(options["timeout_s"], 300)
                self.assertEqual(options["memory_mb"], 3072)
                prefixes = values["prefix"].split(",")
                selected = [name for name in ids if name.startswith(tuple(prefixes))]
                directory = Path(values["out"])
                directory.mkdir(parents=True)
                report = {"kind": "ouro.test-manifest-report.v1", "version": "1", "pass": True,
                          "suite": args.label, "manifest": manifest.as_posix(), "root": fixtures.as_posix(),
                          "out": directory.as_posix(), "prefixes": prefixes, "rows": len(selected), "failures": 0,
                          "results": [{"id": name, "status": "pass", "exit_code": 1,
                                       "log": (directory / (name + ".out")).as_posix(), "issue": ""}
                                      for name in selected]}
                result = RunResult("ok", 0, "native report\n", "", 1.0, 1.0)
                if change:
                    result = change(len(calls), report, result, manifest)
                if not report.pop("omit_report", False):
                    (directory / "manifest-report.json").write_text(json.dumps(report), encoding="utf-8")
                    (directory / "rows.tsv").write_text("".join(name + "|fields\n" for name in selected), encoding="utf-8")
                return result

            with patch.object(native_inputs, "prepare", return_value=fixtures), \
                    patch.object(host, "ensure_tools", return_value=None), \
                    patch.object(host, "binary", return_value=root / "ouro-test"), \
                    patch.object(host, "environment", return_value={}), \
                    patch.object(limits, "run_limited", side_effect=execute), contextlib.redirect_stdout(io.StringIO()):
                status = native_inputs.run_manifest(args)
            summary = json.loads((root / "out/manifest-batches.json").read_text(encoding="utf-8"))
            return status, summary, calls, original == manifest.read_text(encoding="utf-8")

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
