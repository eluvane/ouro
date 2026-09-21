#!/usr/bin/env python3
"""Regression tests for selfhost bootstrap evidence reporting."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import selfhost_bootstrap_evidence as evidence  # noqa: E402


class SelfhostBootstrapEvidenceTests(unittest.TestCase):
    def test_defaults_follow_the_canonical_stage_loop_wrapper(self) -> None:
        self.assertEqual(evidence.DEFAULT_STAGE_LOOP_RESULT, Path("_build/stage_loop/result.json"))
        self.assertEqual(evidence.DEFAULT_STAGE_LOOP_COMMAND, "sh scripts/stage_loop.sh")

    def test_report_schema_has_required_top_level_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = evidence.empty_report(root)
            for key in ("schema_version", "repo", "environment", "commands", "stages", "artifacts", "comparisons", "tests", "summary"):
                self.assertIn(key, report)
            self.assertEqual(report["schema_version"], 1)

    def test_command_failure_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = evidence.run_command(
                "failure",
                [sys.executable, "-c", "import sys; print('nope'); sys.exit(7)"],
                root=root,
                log_dir=root / "logs",
                timeout_seconds=None,
                log_bytes=1024,
            )
            self.assertEqual(record["status"], "fail")
            self.assertEqual(record["exit_code"], 7)
            self.assertIn("nope", record["stdout_excerpt"])

    def test_missing_artifact_is_recorded_as_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = evidence.hash_artifact(root, "_build/selfhost/missing.c", group="generated", required=True)
            self.assertEqual(artifact["status"], "missing")
            self.assertTrue(artifact["required"])
            report = evidence.empty_report(root)
            report["artifacts"] = [artifact]
            evidence.finalize_report(
                report,
                stage_loop_result={"summary": {"status": "pass"}, "comparisons": [{"match": True}]},
                run_stage_loop=True,
                stage_loop_read_error=None,
                generated_changes={"available": True, "changed": False, "paths": []},
            )
            self.assertEqual(report["summary"]["status"], "fail")
            self.assertIn("_build/selfhost/missing.c", report["summary"]["missing_required_artifacts"])

    def test_hash_mismatch_is_detected(self) -> None:
        comparison = evidence.compare_hash_maps("stage1-stage2", {"a.c": "111"}, {"a.c": "222"})
        self.assertEqual(comparison["status"], "fail")
        self.assertEqual(comparison["mismatched_paths"][0]["path"], "a.c")

    def test_matching_artifacts_converge(self) -> None:
        comparison = evidence.compare_hash_maps("stage1-stage2", {"a.c": "111"}, {"a.c": "111"})
        self.assertEqual(comparison["status"], "pass")
        self.assertEqual(comparison["matched_count"], 1)

    def test_current_stage_loop_result_uses_authoritative_fixpoint_fields(self) -> None:
        result = {
            "pass": True,
            "fixpoint": True,
            "backend_eq": True,
            "frontend_eq": True,
            "stages": 2,
            "stage_reports": [
                {"stage": 1, "frontend": {"pass": True}},
                {"stage": 2, "frontend": {"pass": True}, "eq_prev": {"backend": True, "frontend": True}},
            ],
        }
        comparisons = evidence.normalize_existing_comparisons(result)
        self.assertEqual([item["name"] for item in comparisons], ["stage1-stage2-backend", "stage1-stage2-frontend"])
        self.assertTrue(all(item["status"] == "pass" for item in comparisons))
        stages = evidence.normalize_stages(result)
        self.assertEqual([item["number"] for item in stages], [1, 2])
        self.assertTrue(all(item["status"] == "pass" for item in stages))

    def test_current_stage_loop_mismatch_remains_fail_closed(self) -> None:
        comparisons = evidence.normalize_existing_comparisons({"backend_eq": False, "frontend_eq": True})
        self.assertEqual([item["status"] for item in comparisons], ["fail", "pass"])

    def test_partial_mode_does_not_report_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report, exit_code = evidence.build_report(
                root=root,
                out=root / "_build/bootstrap/evidence.json",
                work_dir=Path("_build/bootstrap"),
                stage_loop_result_path=Path("_build/selfhost/result.json"),
                run_stage_loop_flag=False,
                stage_loop_command=[sys.executable, "-c", "raise SystemExit(0)"],
                test_commands=[],
                timeout_seconds=None,
                log_bytes=512,
            )
            self.assertEqual(exit_code, 1)
            self.assertEqual(report["summary"]["status"], "partial")
            self.assertIsNone(report["summary"]["converged"])

    def test_stable_path_ordering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "_build/selfhost").mkdir(parents=True)
            (root / "_build/selfhost/b.c").write_text("b", encoding="utf-8")
            (root / "_build/selfhost/a.c").write_text("a", encoding="utf-8")
            result = {"artifact_hashes": {"_build/selfhost/b.c": "old", "_build/selfhost/a.c": "old"}}
            artifacts = evidence.discover_artifacts(root, result, Path("_build/selfhost/result.json"))
            paths = [item["path"] for item in artifacts]
            self.assertEqual(paths, sorted(paths))

    def test_read_json_fails_closed_on_missing_invalid_and_non_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing, missing_err = evidence.read_json(root / "absent.json")
            self.assertIsNone(missing)
            self.assertEqual(missing_err, "result JSON was not written")

            array_path = root / "array.json"
            array_path.write_text("[1]", encoding="utf-8")
            array_value, array_err = evidence.read_json(array_path)
            self.assertIsNone(array_value)
            self.assertEqual(array_err, "result JSON top-level value is not an object")

            bad_path = root / "bad.json"
            bad_path.write_bytes(b"\xff\xfe{")
            bad_value, bad_err = evidence.read_json(bad_path)
            self.assertIsNone(bad_value)
            self.assertIsNotNone(bad_err)
            self.assertTrue(str(bad_err).startswith("unable to read JSON:"))

    def test_bounded_log_capture_does_not_explode_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            limit = 128
            record = evidence.run_command(
                "large-log",
                [sys.executable, "-c", "print('x' * 10000)"],
                root=root,
                log_dir=root / "logs",
                timeout_seconds=None,
                log_bytes=limit,
            )
            self.assertEqual(record["status"], "pass")
            self.assertTrue(record["stdout_truncated"])
            self.assertLessEqual(len(record["stdout_excerpt"].encode("utf-8", errors="replace")), limit)


def run() -> None:
    result = unittest.TextTestRunner(verbosity=1).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(SelfhostBootstrapEvidenceTests)
    )
    if not result.wasSuccessful():
        raise AssertionError("selfhost bootstrap evidence contract tests failed")


if __name__ == "__main__":
    raise SystemExit(unittest.main())
