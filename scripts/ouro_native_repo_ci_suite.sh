#!/usr/bin/env sh
# Ouro runs the repository fixtures. This launcher also tests shell delegation,
# report validation, and stale binary rejection after failed rebuilds.
set -eu
ulimit -s unlimited 2>/dev/null || true
ROOT=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
# shellcheck source=scripts/python.sh
. "$ROOT/scripts/python.sh"
if [ -z "${PYTHON:-}" ]; then
	echo "OURO_NATIVE_REPO_CI_SUITE: FAIL no working Python" >&2
	exit 127
fi

OUT="${OURO_NATIVE_REPO_CI_SUITE_OUT:-$ROOT/_build/ouro_native_repo_ci_suite}"
rm -rf "$OUT"
mkdir -p "$OUT"

BIN="$OUT/ouro-ci-selftest"
if ! OURO_BUILD_TOOL_MODE=native sh "$ROOT/scripts/build_tool.sh" \
	tools/ci_gate/native_repo_selftest_main.ouro "$BIN" >"$OUT/build.log" 2>&1; then
	echo "OURO_NATIVE_REPO_CI_SUITE: FAIL native suite build" >&2
	tail -n 20 "$OUT/build.log" >&2
	exit 1
fi

NATIVE_OUT=$OUT
case "$NATIVE_OUT" in
	"$ROOT"/*) NATIVE_OUT=${NATIVE_OUT#"$ROOT"/} ;;
esac
OURO_NATIVE_REPO_CI_DISPLAY_OUT="$OUT"
MSYS2_ENV_CONV_EXCL="${MSYS2_ENV_CONV_EXCL:+$MSYS2_ENV_CONV_EXCL;}OURO_NATIVE_REPO_CI_DISPLAY_OUT"
export PYTHON OURO_NATIVE_REPO_CI_DISPLAY_OUT MSYS2_ENV_CONV_EXCL

FIXTURES=$("$PYTHON" scripts/ouro_smith.py prepare --group manifest --out "$OUT/inputs")
# Each process releases its arena before the next required section starts.
for section in fixtures docs project ci wrappers policy manifest; do
	"$BIN" "--root=$ROOT" "--out=$NATIVE_OUT" "--fixtures=$FIXTURES" "$@" "--section=$section"
done

"$PYTHON" - <<'PY_NATIVE_GATE_COMPAT'
"""Focused fail-closed tests for legacy native-gate compatibility wrappers."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path.cwd() / "scripts"))
import repo_support as compat


class NativeGateCompatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="ouro-native-gate-compat-")
        self.root = Path(self.tmp.name).resolve()
        self.scan_root = self.root / "fixture"
        self.scan_root.mkdir(parents=True)
        self.native_out = self.root / "out" / "native"
        self.report = self.native_out / "repo-gate.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def valid_report(self, *, profile: str = "docs-native", passed: bool = True) -> dict:
        return {
            "kind": compat.NATIVE_REPO_GATE_REPORT_KIND,
            "version": "1",
            "profile": profile,
            "execution_backend": "ouro-native-repo-gate",
            "execution_mode": "native",
            "pass": passed,
            "gates": [
                {
                    "name": "fixture",
                    "status": "pass" if passed else "fail",
                    "blocking": True,
                    "metrics": [],
                    "issues": [] if passed else [{"reason": "fixture failed", "path": "fixture"}],
                }
            ],
            "issues": [] if passed else [{"reason": "fixture failed", "path": "fixture"}],
        }

    def write_report(self, data: object) -> None:
        self.report.parent.mkdir(parents=True, exist_ok=True)
        self.report.write_text(json.dumps(data) + "\n", encoding="utf-8")

    def run_gate(self, fake_run):
        with patch.object(compat.subprocess, "run", side_effect=fake_run):
            return compat.run_native_repo_gate(
                checkout_root=self.root,
                scan_root=self.scan_root,
                profile="docs-native",
                native_out=self.native_out,
            )

    def run_report(self, data: object, *, native_returncode: int = 0):
        def fake_run(*_args, **_kwargs):
            self.write_report(data)
            return SimpleNamespace(returncode=native_returncode)

        return self.run_gate(fake_run)

    def run_report_text(self, text: str, *, native_returncode: int = 0):
        def fake_run(*_args, **_kwargs):
            self.report.parent.mkdir(parents=True, exist_ok=True)
            self.report.write_text(text + "\n", encoding="utf-8")
            return SimpleNamespace(returncode=native_returncode)

        return self.run_gate(fake_run)

    def assert_rejected_report(self, data: object, *, native_returncode: int = 0):
        outcome = self.run_report(data, native_returncode=native_returncode)
        self.assertEqual(outcome.returncode, native_returncode if native_returncode else 1)
        self.assertEqual(outcome.native_returncode, native_returncode)
        self.assertFalse(outcome.report_valid)
        self.assertFalse(outcome.report["pass"])
        self.assertIsNotNone(outcome.error)
        return outcome

    def test_valid_native_report_passes(self) -> None:
        def fake_run(*_args, **_kwargs):
            self.write_report(self.valid_report())
            return SimpleNamespace(returncode=0)

        outcome = self.run_gate(fake_run)
        self.assertEqual(outcome.returncode, 0)
        self.assertTrue(outcome.report_valid)
        self.assertIsNone(outcome.error)

    def test_native_failure_with_matching_report_propagates(self) -> None:
        def fake_run(*_args, **_kwargs):
            self.write_report(self.valid_report(passed=False))
            return SimpleNamespace(returncode=1)

        outcome = self.run_gate(fake_run)
        self.assertEqual(outcome.returncode, 1)
        self.assertTrue(outcome.report_valid)
        self.assertFalse(outcome.report["pass"])

    def test_metrics_nonblocking_and_extra_fields_remain_valid(self) -> None:
        report = self.valid_report()
        report["gates"][0]["name"] = ""
        report["gates"][0]["blocking"] = False
        report["gates"][0]["metrics"] = [
            {"name": "rows", "value": "2", "unit": "files"},
            {"name": "", "value": ""},
        ]
        report["gates"][0]["extension"] = {"source": "fixture"}
        report["extension"] = "metadata"
        outcome = self.run_report(report)
        self.assertEqual(outcome.returncode, 0)
        self.assertTrue(outcome.report_valid)
        self.assertEqual(outcome.report, report)
        self.assertIsNone(outcome.error)

    def test_mixed_failed_report_preserves_nonzero_status_and_issue_order(self) -> None:
        report = self.valid_report(passed=False)
        issues = [{"reason": "first failure", "path": "first"},
                  {"reason": "second failure", "path": "second"}]
        report["gates"][0]["blocking"] = False
        report["gates"][0]["issues"] = issues
        report["gates"].insert(0, self.valid_report()["gates"][0])
        report["issues"] = issues
        outcome = self.run_report(report, native_returncode=259)
        self.assertEqual(outcome.returncode, 259)
        self.assertEqual(outcome.native_returncode, 259)
        self.assertTrue(outcome.report_valid)
        self.assertEqual(outcome.report, report)
        self.assertIsNone(outcome.error)

    def test_nonobject_gate_rows_are_rejected(self) -> None:
        for gate in (None, True, 1, "gate", [], {}):
            with self.subTest(gate=gate):
                report = self.valid_report()
                report["gates"] = [gate]
                self.assert_rejected_report(report)

    def test_missing_gate_fields_are_rejected(self) -> None:
        for field in ("name", "status", "blocking", "metrics", "issues"):
            with self.subTest(field=field):
                report = self.valid_report()
                del report["gates"][0][field]
                self.assert_rejected_report(report)

    def test_untyped_gate_fields_are_rejected(self) -> None:
        cases = {
            "name": (None, True, 1, [], {}),
            "status": (None, True, 1, [], {}),
            "blocking": (None, 0, 1, "true", [], {}),
            "metrics": (None, True, 1, "metrics", {}),
            "issues": (None, True, 1, "issues", {}),
        }
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    report = self.valid_report()
                    report["gates"][0][field] = value
                    self.assert_rejected_report(report)

    def test_nonpassing_gate_status_cannot_hide_under_success(self) -> None:
        for status in ("fail", "skip", "unavailable", "PASS"):
            with self.subTest(status=status):
                report = self.valid_report()
                report["gates"][0]["status"] = status
                self.assert_rejected_report(report)

    def test_later_failed_or_null_gate_cannot_hide_under_success(self) -> None:
        for gate in (None, self.valid_report(passed=False)["gates"][0]):
            with self.subTest(gate=gate):
                report = self.valid_report()
                report["gates"].append(gate)
                self.assert_rejected_report(report)

    def test_gate_status_must_match_its_issues(self) -> None:
        for passed, status, native_returncode in ((True, "pass", 0), (False, "pass", 9)):
            with self.subTest(passed=passed):
                report = self.valid_report(passed=passed)
                report["gates"][0]["status"] = status
                if passed:
                    report["gates"][0]["issues"] = self.valid_report(passed=False)["issues"]
                outcome = self.assert_rejected_report(report, native_returncode=native_returncode)
                self.assertIn("status does not match", outcome.error or "")

    def test_failed_summary_requires_a_failed_gate(self) -> None:
        report = self.valid_report()
        report["pass"] = False
        outcome = self.assert_rejected_report(report, native_returncode=9)
        self.assertIn("pass field does not match", outcome.error or "")

    def test_summary_issues_must_match_gate_issues(self) -> None:
        for issues in ([], [{"reason": "different failure", "path": "fixture"}]):
            with self.subTest(issues=issues):
                report = self.valid_report(passed=False)
                report["issues"] = issues
                outcome = self.assert_rejected_report(report, native_returncode=9)
                self.assertIn("issues do not match", outcome.error or "")
        report = self.valid_report(passed=False)
        report["gates"][0]["issues"].append({"reason": "second failure", "path": "second"})
        report["issues"] = list(reversed(report["gates"][0]["issues"]))
        self.assert_rejected_report(report, native_returncode=9)
        report = self.valid_report()
        report["issues"] = self.valid_report(passed=False)["issues"]
        self.assert_rejected_report(report)

    def test_malformed_metric_rows_are_rejected(self) -> None:
        metrics = (None, True, 1, "metric", [], {}, {"name": "rows"},
                   {"value": "1"}, {"name": None, "value": "1"},
                   {"name": "rows", "value": 1})
        for metric in metrics:
            with self.subTest(metric=metric):
                report = self.valid_report()
                report["gates"][0]["metrics"] = [metric]
                self.assert_rejected_report(report)

    def test_malformed_issue_rows_are_rejected(self) -> None:
        issues = (None, True, 1, "issue", [], {}, {"reason": "failure"},
                  {"path": "fixture"}, {"reason": False, "path": "fixture"},
                  {"reason": "failure", "path": 1})
        for issue in issues:
            with self.subTest(issue=issue):
                report = self.valid_report(passed=False)
                report["gates"][0]["issues"] = [issue]
                report["issues"] = [issue]
                self.assert_rejected_report(report, native_returncode=9)

    def test_contract_markers_and_boolean_pass_remain_required(self) -> None:
        fields = {"kind": "ouro.ci-gate-report.v1", "version": "2", "profile": "docs",
                  "execution_backend": "python", "execution_mode": "subprocess", "pass": 1}
        for field, value in fields.items():
            with self.subTest(field=field):
                report = self.valid_report()
                report[field] = value
                self.assert_rejected_report(report)

    def test_duplicate_json_keys_are_rejected(self) -> None:
        report = self.valid_report()
        report["gates"][0]["metrics"] = [{"name": "rows", "value": "1"}]
        success = json.dumps(report)
        failure = json.dumps(self.valid_report(passed=False))
        cases = ((0, success.replace('"pass": true', '"pass": false, "pass": true')),
                 (0, success.replace('"status": "pass"', '"status": "fail", "status": "pass"')),
                 (0, success.replace('"value": "1"', '"value": 1, "value": "1"')),
                 (9, failure.replace('"reason": "fixture failed"',
                                     '"reason": null, "reason": "fixture failed"')))
        for native_returncode, text in cases:
            with self.subTest(native_returncode=native_returncode, text=text):
                outcome = self.run_report_text(text, native_returncode=native_returncode)
                self.assertEqual(outcome.returncode, native_returncode if native_returncode else 1)
                self.assertEqual(outcome.native_returncode, native_returncode)
                self.assertFalse(outcome.report_valid)
                self.assertFalse(outcome.report["pass"])
                self.assertIn("duplicate native report key", outcome.error or "")

    def test_missing_report_after_success_is_blocking(self) -> None:
        outcome = self.run_gate(lambda *_args, **_kwargs: SimpleNamespace(returncode=0))
        self.assertEqual(outcome.returncode, 1)
        self.assertFalse(outcome.report_valid)
        self.assertIn("unavailable or malformed", outcome.error or "")

    def test_malformed_report_after_success_is_blocking(self) -> None:
        def fake_run(*_args, **_kwargs):
            self.report.parent.mkdir(parents=True, exist_ok=True)
            self.report.write_text("{broken\n", encoding="utf-8")
            return SimpleNamespace(returncode=0)

        outcome = self.run_gate(fake_run)
        self.assertEqual(outcome.returncode, 1)
        self.assertFalse(outcome.report_valid)
        self.assertFalse(outcome.report["pass"])

    def test_stale_report_is_removed_before_delegation(self) -> None:
        self.write_report(self.valid_report())
        outcome = self.run_gate(lambda *_args, **_kwargs: SimpleNamespace(returncode=0))
        self.assertEqual(outcome.returncode, 1)
        self.assertFalse(outcome.report_valid)
        self.assertFalse(self.report.exists())

    def test_success_code_cannot_override_failed_report(self) -> None:
        def fake_run(*_args, **_kwargs):
            self.write_report(self.valid_report(passed=False))
            return SimpleNamespace(returncode=0)

        outcome = self.run_gate(fake_run)
        self.assertEqual(outcome.returncode, 1)
        self.assertFalse(outcome.report_valid)
        self.assertIn("returned 0", outcome.error or "")

    def test_failure_code_cannot_coexist_with_pass_report(self) -> None:
        def fake_run(*_args, **_kwargs):
            self.write_report(self.valid_report(passed=True))
            return SimpleNamespace(returncode=9)

        outcome = self.run_gate(fake_run)
        self.assertEqual(outcome.returncode, 9)
        self.assertFalse(outcome.report_valid)
        self.assertIn("claims pass", outcome.error or "")

    def test_subprocess_start_failure_is_distinct(self) -> None:
        def fake_run(*_args, **_kwargs):
            raise FileNotFoundError("sh missing")

        outcome = self.run_gate(fake_run)
        self.assertEqual(outcome.returncode, 127)
        self.assertIsNone(outcome.native_returncode)
        self.assertFalse(outcome.report_valid)
        self.assertIn("could not start", outcome.error or "")

    def test_empty_gate_list_is_rejected(self) -> None:
        def fake_run(*_args, **_kwargs):
            report = self.valid_report()
            report["gates"] = []
            self.write_report(report)
            return SimpleNamespace(returncode=0)

        outcome = self.run_gate(fake_run)
        self.assertEqual(outcome.returncode, 1)
        self.assertIn("no selected gates", outcome.error or "")

    def test_repo_local_path_positive_and_escape_negative(self) -> None:
        inside = compat.resolve_repo_local_path(
            self.root, "_build/report.json", label="--report"
        )
        self.assertEqual(inside, self.root / "_build" / "report.json")
        with self.assertRaisesRegex(ValueError, "escapes repository"):
            compat.resolve_repo_local_path(
                self.root, "../outside.json", label="--report"
            )

    @unittest.skipIf(os.name == "nt", "non-Windows spelling guard")
    def test_windows_drive_path_rejected_on_non_windows(self) -> None:
        with self.assertRaisesRegex(ValueError, "Windows absolute path"):
            compat.resolve_repo_local_path(
                self.root, r"C:\outside\report.json", label="--report"
            )

    def test_compact_atomic_report_keeps_legacy_shape(self) -> None:
        path = self.root / "compact.json"
        compat.write_json_atomic_compact(path, {"profile": "workflow-native", "pass": True})
        text = path.read_text(encoding="utf-8")
        self.assertIn('"profile":"workflow-native"', text)
        self.assertTrue(text.endswith("\n"))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(NativeGateCompatTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print(f"NATIVE_GATE_COMPAT_SUITE: OK tests={result.testsRun}")
        raise SystemExit(0)
    print(
        "NATIVE_GATE_COMPAT_SUITE: FAIL "
        f"tests={result.testsRun} failures={len(result.failures)} errors={len(result.errors)}"
    )
    raise SystemExit(1)
PY_NATIVE_GATE_COMPAT

NATIVE_SUITE_OUT=$OUT
OUT="$NATIVE_SUITE_OUT/silent-fallback"
rm -rf "$OUT"
mkdir -p "$OUT"
ROWS=0

ok() {
	ROWS=$((ROWS + 1))
	echo "SILENT_FALLBACK_OK $1"
}

fail() {
	echo "SILENT_FALLBACK_FAIL $1" >&2
	exit 1
}

expect_status() {
	expected_status=$1
	status_label=$2
	shift 2
	set +e
	"$@"
	actual_status=$?
	set -e
	[ "$actual_status" -eq "$expected_status" ] ||
		fail "$status_label expected=$expected_status actual=$actual_status"
	ok "$status_label"
}

assert_contains() {
	contains_label=$1
	contains_path=$2
	contains_text=$3
	grep -F "$contains_text" "$contains_path" >/dev/null 2>&1 ||
		fail "$contains_label missing=$contains_text"
	ok "$contains_label"
}

assert_not_contains() {
	not_label=$1
	not_path=$2
	not_text=$3
	if grep -F "$not_text" "$not_path" >/dev/null 2>&1; then
		fail "$not_label unexpected=$not_text"
	fi
	ok "$not_label"
}

make_fake_wrapper_repo() {
	fake_root=$1
	wrapper_name=$2
	binary_name=$3
	mkdir -p "$fake_root/scripts" "$fake_root/bin"
	cp "$ROOT/scripts/$wrapper_name" "$fake_root/scripts/$wrapper_name"
	cp "$ROOT/scripts/native_gate_launcher.sh" "$fake_root/scripts/native_gate_launcher.sh"
	cat >"$fake_root/scripts/build_tool.sh" <<'EOF'
#!/usr/bin/env sh
set -eu
[ "${OURO_BUILD_TOOL_MODE:-}" = "native" ] || exit 42
echo "FAKE_BUILD_TOOL: intentional rebuild failure" >&2
exit 41
EOF
	chmod +x "$fake_root/scripts/build_tool.sh"
	printf '%s\n' source >"$fake_root/marker.source"
	cat >"$fake_root/bin/$binary_name" <<'EOF'
#!/usr/bin/env sh
echo "FAKE_NATIVE_EXECUTED"
exit 0
EOF
	chmod +x "$fake_root/bin/$binary_name"
	# Deterministic ordering: source older than the complete fake binary.
	touch -t 202001010000 "$fake_root/marker.source"
	touch -t 202101010000 "$fake_root/bin/$binary_name"
	printf '%s\n' marker.source >"$fake_root/bin/$binary_name.sources"
}

probe_wrapper_manifest() {
	probe_label=$1
	wrapper_name=$2
	binary_name=$3
	backend_marker=$4
	fake_root="$OUT/fake-$probe_label"
	make_fake_wrapper_repo "$fake_root" "$wrapper_name" "$binary_name"
	positive_log="$OUT/$probe_label-positive.log"
	OURO_C_BUILD_DIR="$fake_root/bin" \
		/bin/sh "$fake_root/scripts/$wrapper_name" --probe >"$positive_log" 2>&1 ||
		fail "$probe_label-valid-manifest"
	assert_contains "$probe_label-valid-exec" "$positive_log" "FAKE_NATIVE_EXECUTED"
	assert_contains "$probe_label-backend-visible" "$positive_log" "$backend_marker"

	touch -t 202201010000 "$fake_root/marker.source"
	newer_log="$OUT/$probe_label-newer-source.log"
	expect_status 1 "$probe_label-newer-source-fails" \
		env OURO_C_BUILD_DIR="$fake_root/bin" \
		/bin/sh "$fake_root/scripts/$wrapper_name" --probe >"$newer_log" 2>&1
	assert_contains "$probe_label-newer-source-reason" "$newer_log" "reason=source_newer:marker.source"
	assert_not_contains "$probe_label-newer-source-not-executed" "$newer_log" "FAKE_NATIVE_EXECUTED"
	touch -t 202001010000 "$fake_root/marker.source"
	stat_log="$OUT/$probe_label-stat-failed.log"
	mkdir -p "$fake_root/stat-failure"
	printf '#!/bin/sh\nexit 2\n' >"$fake_root/stat-failure/find"
	chmod +x "$fake_root/stat-failure/find"
	# A Windows drive colon would split this directory in the shell's PATH.
	stat_path="$fake_root/stat-failure"
	if command -v cygpath >/dev/null 2>&1; then
		stat_path=$(cygpath -u "$stat_path")
	fi
	expect_status 1 "$probe_label-stat-failure-fails" \
		env OURO_C_BUILD_DIR="$fake_root/bin" PATH="$stat_path:$PATH" \
		/bin/sh "$fake_root/scripts/$wrapper_name" --probe >"$stat_log" 2>&1
	assert_contains "$probe_label-stat-failure-reason" "$stat_log" "reason=source_stat_failed:marker.source"
	assert_not_contains "$probe_label-stat-failure-not-executed" "$stat_log" "FAKE_NATIVE_EXECUTED"

	rm -f "$fake_root/bin/$binary_name.sources"
	negative_log="$OUT/$probe_label-missing-manifest.log"
	expect_status 1 "$probe_label-missing-manifest-fails" \
		env OURO_C_BUILD_DIR="$fake_root/bin" \
		/bin/sh "$fake_root/scripts/$wrapper_name" --probe \
		>"$negative_log" 2>&1
	assert_contains "$probe_label-manifest-reason" "$negative_log" "reason=manifest_missing"
	assert_contains "$probe_label-stale-rejected" "$negative_log" "STALE_BINARY_REJECTED"
	assert_not_contains "$probe_label-stale-not-executed" "$negative_log" "FAKE_NATIVE_EXECUTED"
}

probe_wrapper_manifest repo ouro_repo_gate.sh ouro-repo-gate \
	"EXECUTION_BACKEND=ouro-native-repo-gate"
probe_wrapper_manifest ci ouro_ci_gate.sh ouro-ci-gate \
	"EXECUTION_BACKEND=ouro-native-ci-gate"

expect_status 2 build-tool-unknown-mode \
	env OURO_BUILD_TOOL_MODE=definitely-unknown \
	/bin/sh "$ROOT/scripts/build_tool.sh" tools/collect.ouro "$OUT/invalid-mode" \
	>"$OUT/build-tool-unknown-mode.log" 2>&1
assert_contains build-tool-unknown-mode-diagnostic "$OUT/build-tool-unknown-mode.log" \
	"unknown OURO_BUILD_TOOL_MODE"

HOST_WRAPPER="$OUT/host-wrapper/ouro-collect"
mkdir -p "$(dirname "$HOST_WRAPPER")"
OURO_BUILD_TOOL_MODE=host-wrapper \
	/bin/sh "$ROOT/scripts/build_tool.sh" tools/collect.ouro "$HOST_WRAPPER" \
	>"$OUT/host-wrapper.log" 2>&1 || fail host-wrapper-explicit-positive
[ -x "$HOST_WRAPPER" ] || fail host-wrapper-executable
[ -s "$HOST_WRAPPER.sources" ] || fail host-wrapper-manifest
assert_contains host-wrapper-backend-visible "$OUT/host-wrapper.log" \
	"BUILD_TOOL_BACKEND: host-wrapper mode=host-wrapper"

expect_status 2 host-wrapper-unsupported-fails \
	env OURO_BUILD_TOOL_MODE=host-wrapper \
	/bin/sh "$ROOT/scripts/build_tool.sh" tools/repo_gate/main.ouro "$OUT/unsupported-wrapper" \
	>"$OUT/host-wrapper-unsupported.log" 2>&1
assert_contains host-wrapper-unsupported-diagnostic "$OUT/host-wrapper-unsupported.log" \
	"host-wrapper backend does not support"

/bin/sh "$ROOT/scripts/ouro_repo_gate.sh" --profile docs-native --list \
	>"$OUT/repo-list.log" 2>&1 || fail repo-list-positive
assert_contains repo-list-backend "$OUT/repo-list.log" \
	"EXECUTION_BACKEND=ouro-native-repo-gate"

expect_status 2 repo-unknown-profile \
	/bin/sh "$ROOT/scripts/ouro_repo_gate.sh" --profile definitely-unknown \
	--out "$OUT/repo-unknown" >"$OUT/repo-unknown.log" 2>&1
expect_status 2 repo-unknown-option \
	/bin/sh "$ROOT/scripts/ouro_repo_gate.sh" --profle docs-native \
	>"$OUT/repo-unknown-option.log" 2>&1
expect_status 2 repo-missing-option-value \
	/bin/sh "$ROOT/scripts/ouro_repo_gate.sh" --profile \
	>"$OUT/repo-missing-option-value.log" 2>&1

/bin/sh "$ROOT/scripts/ouro_ci_gate.sh" --profile pr-native --list \
	>"$OUT/ci-list.log" 2>&1 || fail ci-list-positive
assert_contains ci-list-backend "$OUT/ci-list.log" \
	"EXECUTION_BACKEND=ouro-native-ci-gate"

expect_status 2 ci-unknown-profile \
	/bin/sh "$ROOT/scripts/ouro_ci_gate.sh" --profile definitely-unknown \
	--out "$OUT/ci-unknown" >"$OUT/ci-unknown.log" 2>&1
expect_status 2 ci-unknown-gate \
	/bin/sh "$ROOT/scripts/ouro_ci_gate.sh" --profile pr-native \
	--gate definitely-unknown --out "$OUT/ci-unknown-gate" \
	>"$OUT/ci-unknown-gate.log" 2>&1
expect_status 2 ci-unknown-option \
	/bin/sh "$ROOT/scripts/ouro_ci_gate.sh" --profle pr-native \
	>"$OUT/ci-unknown-option.log" 2>&1
expect_status 2 ci-host-bound-gate-rejected \
	/bin/sh "$ROOT/scripts/ouro_ci_gate.sh" --profile host-bound \
	--gate host-bound-report >"$OUT/ci-host-bound-gate.log" 2>&1

# The validation command returns success but deliberately emits no required
# native repo report. On Windows, the runtime prefers an absolute Git shell
# over PATH, so more.com is the explicit no-op interpreter: it reads the
# generated script without executing it and returns success. POSIX ignores
# OURO_POSIX_SH and continues to use the PATH fixture.
mkdir -p "$OUT/fake-path"
cat >"$OUT/fake-path/sh" <<'EOF'
#!/bin/sh
exit 0
EOF
chmod +x "$OUT/fake-path/sh"
expect_status 1 ci-host-bound-missing-report \
	env OURO_POSIX_SH=C:/Windows/System32/more.com PATH="$OUT/fake-path:$PATH" \
	/bin/sh "$ROOT/scripts/ouro_ci_gate.sh" --profile host-bound \
	--root "$ROOT" --out "$OUT/host-bound-missing-report" \
	>"$OUT/host-bound-missing-report.log" 2>&1
assert_contains ci-host-bound-missing-report-diagnostic \
	"$OUT/host-bound-missing-report/host-bound-report.json" \
	"required native validation report missing, malformed, or non-passing"

DOCS_OUT="$OUT/docs-native"
/bin/sh "$ROOT/scripts/ouro_repo_gate.sh" --profile docs-native --out "$DOCS_OUT" \
	>"$OUT/docs-native.log" 2>&1 || fail docs-native-positive
"$PYTHON" - "$DOCS_OUT/repo-gate.json" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
assert data["kind"] == "ouro.repo-gate-report.v1"
assert data["execution_backend"] == "ouro-native-repo-gate"
assert data["execution_mode"] == "native"
assert data["pass"] is True
assert isinstance(data["gates"], list) and data["gates"]
PY
ok docs-native-report-backend


echo "SILENT_FALLBACK_SUITE: OK rows=$ROWS out=$OUT"
echo "OURO_NATIVE_REPO_CI_SUITE: HARDENING_OK backend-and-report-fallbacks=closed out=$NATIVE_SUITE_OUT"
