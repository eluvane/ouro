"""Offline checks for hosted historical bootstrap provenance."""
from __future__ import annotations

import contextlib
from copy import deepcopy
import hashlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ci_historical_cache as cache


class HistoricalCacheTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        key = "c" * 64
        self.archive = root / "runner/bootstrap-historical" / (key + ".zip")
        self.archive.parent.mkdir(parents=True)
        self.archive.write_bytes(b"historical archive fixture")
        self.digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.name = f"bootstrap-history-{key}-{self.digest}"
        self.repo = "owner/repo"
        self.env = {"HISTORICAL_KEY": key, "RUNNER_TEMP": str(root / "runner"), "GITHUB_WORKSPACE": str(root / "checkout"),
                    "GITHUB_REPOSITORY": self.repo, "GITHUB_REPOSITORY_ID": "100", "GITHUB_API_URL": "https://api.github.com",
                    "BUILT_HISTORICAL_SHA256": self.digest, "GITHUB_REF": "refs/heads/main",
                    "GITHUB_EVENT_NAME": "push", "GITHUB_RUN_ATTEMPT": "1",
                    "GITHUB_WORKFLOW_REF": f"{self.repo}/{cache.WORKFLOW}@refs/heads/main"}
        self.origin = {"id": 11, "repository_id": 100, "head_repository_id": 100, "head_branch": "main", "head_sha": "b" * 40}
        self.artifact = {"name": self.name, "expired": False, "created_at": "2026-05-05T11:00:00Z", "workflow_run": self.origin}
        repo = {"id": 100, "full_name": self.repo}
        self.run_data = {"id": 11, "event": "push", "status": "completed", "conclusion": "success", "run_attempt": 1,
                         "head_branch": "main", "head_sha": self.origin["head_sha"], "path": cache.WORKFLOW,
                         "repository": repo, "head_repository": repo, "run_started_at": "2026-05-05T10:00:00Z",
                         "updated_at": "2026-05-05T12:00:00Z"}

    def invoke(self, action, replies=(), **env):
        output = io.StringIO()
        with patch.dict(os.environ, {**self.env, **env}, clear=True), patch.object(cache, "github_json", side_effect=replies) as reads, \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cache.main([action]), 0)
        return output.getvalue(), [call.args[0] for call in reads.call_args_list]

    def test_same_digest_requires_the_successful_original_protected_run(self):
        for branch in ("main", "master"):
            for path in (cache.WORKFLOW, f"{cache.WORKFLOW}@{branch}", f"{cache.WORKFLOW}@refs/heads/{branch}"):
                with self.subTest(branch=branch, path=path):
                    origin = {**self.origin, "head_branch": branch}
                    result, reads = self.invoke("verify", [{"artifacts": [{**self.artifact, "workflow_run": origin}]},
                                                   {**self.run_data, "head_branch": branch, "path": path}])
                    self.assertEqual(result, f"verified_sha256={self.digest}\n")
                    self.assertEqual(reads, [f"/repos/{self.repo}/actions/artifacts?name={self.name}&per_page=100",
                                             f"/repos/{self.repo}/actions/runs/11/attempts/1"])

    def test_foreign_or_failed_producers_cannot_confirm_the_cache(self):
        for field, value in (
                ("id", 22), ("event", "pull_request"), ("event", "workflow_dispatch"), ("run_attempt", 2),
                ("status", "in_progress"), ("conclusion", "failure"), ("head_branch", "feature"), ("head_sha", "d" * 40),
                ("repository", {"id": 99, "full_name": self.repo}), ("head_repository", {"id": 100, "full_name": "fork/repo"}),
                ("path", ".github/workflows/other.yml"), ("path", cache.WORKFLOW + "@refs/heads/feature"),
                ("updated_at", "2026-05-05T10:30:00Z"), ("run_started_at", "2026-05-05T11:30:00Z")):
            with self.subTest(field=field, value=value):
                result, _ = self.invoke("verify", [{"artifacts": [self.artifact]}, {**self.run_data, field: value}])
                self.assertEqual(result, "verified_sha256=\n")

    def test_miss_corruption_or_unavailable_evidence_leads_to_a_cold_build(self):
        for artifact in ({**self.artifact, "name": self.name + "extra"}, {**self.artifact, "expired": True},
                         {**self.artifact, "workflow_run": {**self.origin, "head_repository_id": 101}},
                         {**self.artifact, "workflow_run": {**self.origin, "head_branch": "feature"}}, {}, None):
            with self.subTest(artifact=artifact):
                self.assertEqual(self.invoke("verify", [{"artifacts": [artifact]}])[0], "verified_sha256=\n")
        self.assertEqual(self.invoke("verify", [None])[0], "verified_sha256=\n")
        self.archive.write_bytes(b"changed archive")
        result, reads = self.invoke("verify", [{"artifacts": [self.artifact]}])
        self.assertEqual(result, "verified_sha256=\n")
        self.assertNotIn(self.name, reads[0])
        self.archive.unlink()
        self.assertEqual(self.invoke("verify"), ("verified_sha256=\n", []))

    def test_untrusted_candidate_cannot_hide_a_valid_same_name_within_the_lookup_budget(self):
        bad = deepcopy(self.artifact)
        bad["workflow_run"]["id"] = 20
        result, calls = self.invoke("verify", [{"artifacts": [bad, bad, self.artifact]},
                                   {**self.run_data, "id": 20, "event": "pull_request"}, self.run_data])
        self.assertEqual(result, f"verified_sha256={self.digest}\n")
        self.assertEqual(len(calls), 3)
        rows = [{**self.artifact, "workflow_run": {**self.origin, "id": index + 1}} for index in range(cache.MAX_RUN_LOOKUPS + 5)]
        result, calls = self.invoke("verify", [{"artifacts": rows}, *([None] * cache.MAX_RUN_LOOKUPS)])
        self.assertEqual(result, "verified_sha256=\n")
        self.assertEqual(len(calls), 1 + cache.MAX_RUN_LOOKUPS)

    def test_writer_requires_the_protected_workflow_and_first_push_attempt(self):
        for change in ({"GITHUB_EVENT_NAME": "pull_request"}, {"GITHUB_REF": "refs/heads/other"},
                       {"GITHUB_RUN_ATTEMPT": "2"}, {"GITHUB_WORKFLOW_REF": "other/workflow"},
                       {"BUILT_HISTORICAL_SHA256": ""}, {"BUILT_HISTORICAL_SHA256": "0" * 64}):
            with self.subTest(change=change):
                self.assertEqual(self.invoke("attest", **change), ("name=\nsha256=\n", []))
                self.assertFalse(self.archive.with_name("attestation.txt").exists())
        self.assertEqual(self.invoke("attest"), (f"name={self.name}\nsha256={self.digest}\n", []))
        self.assertEqual(self.archive.with_name("attestation.txt").read_text(encoding="ascii"), self.name + "\n")

    def test_untrusted_paths_and_api_urls_never_read_metadata(self):
        for change in ({"HISTORICAL_KEY": "../wrong"}, {"RUNNER_TEMP": self.env["GITHUB_WORKSPACE"]},
                       {"GITHUB_API_URL": "https://example.invalid"}, {"GITHUB_REPOSITORY": "owner/.."}):
            with self.subTest(change=change):
                self.assertEqual(self.invoke("verify", **change), ("verified_sha256=\n", []))

    def test_public_metadata_reads_are_bounded_and_send_no_credentials(self):
        path = "/repos/owner/repo/actions/runs/11/attempts/1"
        for status, body, expected in ((200, b'{"id":11}', {"id": 11}), (200, b"[]", None), (200, b"broken", None),
                                       (200, b" " * (cache.MAX_METADATA_BYTES + 1), None), (302, b"", None), (403, b"", None)):
            with self.subTest(status=status, size=len(body)), patch.object(cache.http.client, "HTTPSConnection") as connect:
                response = connect.return_value.getresponse.return_value
                response.status = status
                response.read.return_value = body
                self.assertEqual(cache.github_json(path), expected)
                self.assertEqual(connect.call_args.args, ("api.github.com",))
                self.assertGreater(connect.call_args.kwargs["timeout"], 0)
                request = connect.return_value.request.call_args
                self.assertEqual(request.args, ("GET", path))
                self.assertEqual(set(request.kwargs["headers"]), {"Accept", "User-Agent", "X-GitHub-Api-Version"})
                if status == 200:
                    response.read.assert_called_once_with(cache.MAX_METADATA_BYTES + 1)


def run() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(HistoricalCacheTest)
    if not unittest.TextTestRunner().run(suite).wasSuccessful():
        raise AssertionError("hosted historical cache provenance checks failed")


if __name__ == "__main__":
    run()
