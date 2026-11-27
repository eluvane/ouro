#!/usr/bin/env python3
"""Host-only ordering, source ownership, publication and cache regressions."""
from __future__ import annotations

import copy
import concurrent.futures
import io
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tarfile
import threading
import unittest
from unittest.mock import patch
import zipfile

import bootstrap_compiler as bootstrap
import bootstrap_historical
import bootstrap_inputs as inputs
import compact_source
import ci_gate
import generated_artifact_drift_check as drift
import ouro_build as build
from local_scheduler import JOBS_ENV, MEMORY_ENV, Allocation
from ourosmith.limits import RunResult
from repo_support import hash_json, sha256_file, write_json_atomic


class BootstrapCompilerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ouro-bootstrap-contract-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.work = self.root / "work"
        self.work.mkdir()
        self.events = []
        self.expected_workers = 1
        self.rejected_root = None
        self.rejected_source_form = None
        self.different_c = False
        self.abi_stdout = bootstrap.ABI_STDOUT
        self.bad_stdout = ""
        self.bad_stderr = ("bootstrap-bad.ouro: type mismatch in exact_index\nCHECK_FAIL: front end rejected the input\n"
                           "ouro1: CErr tag=0 n=1\nouro1: CErr code=41 det=82\n")
        self.bad_returncode = 1
        self.bad_status = "ok"
        memory_patch = patch("repo_support.available_memory_mb", return_value=None)
        memory_patch.start()
        self.addCleanup(memory_patch.stop)
        # The fixtures set their own budgets independently of the CI runner.
        scheduler_env = patch.dict(os.environ)
        scheduler_env.start()
        self.addCleanup(scheduler_env.stop)
        for name in (JOBS_ENV, MEMORY_ENV, *bootstrap.C_TOOLCHAIN_ENV_KEYS):
            os.environ.pop(name, None)

    def fixture(self, *, compact_sources=False):
        roots = [f"compiler/source-{index}.ouro" for index in range(14)] + ["compiler/backend.ouro"]
        graph = {name: [name] for name in [*roots, *bootstrap.ACCEPTANCE_ROOTS]}
        roles = ["historical/c0", "historical/bridge", "o"] + (["compact"] if compact_sources else [])
        for role in roles:
            for name in {*graph, "scripts/bootstrap_compiler.py"}:
                path = self.work / role / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("owned " + role + "/" + name, encoding="utf-8")
        cc = self.root / "host-compiler-fixture"
        cc.write_bytes(b"fixed host compiler fixture")
        selected = {"roots": roots, "unit_graph": graph, "environment": bootstrap.c_toolchain_environment(), "sources": {},
                    "source_form": compact_source.KIND if compact_sources else "original",
                    "cc_executable": str(cc), "cc_sha256": sha256_file(cc)}
        snapshot = {"kind": bootstrap.KIND + ".inputs", "key": hash_json(selected), "selected": selected,
            "config": {**build.DEFAULTS, "jobs": 1, "verbosity": "quiet"}, "bridge_graph": graph,
            "roots": {"c0": "historical/c0", "bridge": "historical/bridge", "p1": "o", "p2": "compact" if compact_sources else "o"},
            "inputs": {path.relative_to(self.work).as_posix(): sha256_file(path)
                       for path in self.work.rglob("*") if path.is_file()}}
        write_json_atomic(self.work / "inputs.json", snapshot)
        return snapshot

    def fake_run(self, argv, *, cwd, env, timeout_s, memory_mb, shared_job=None):
        self.assertEqual(timeout_s, bootstrap.TIMEOUT_S)
        workers = int(argv[argv.index("--jobs") + 1]) if "worker" in argv else 1
        self.assertGreaterEqual(workers, 1)
        self.assertLessEqual(workers, self.expected_workers)
        self.assertEqual(env["OURO_JOBS"], str(workers))
        self.assertEqual(env["OURO_FRONTEND_JOBS"], str(workers))
        self.assertEqual(env[JOBS_ENV], str(workers))
        reserved_memory = bootstrap.MEMORY_MIB
        if "worker" in argv:
            action = argv[argv.index("--action") + 1]
            estimate = bootstrap.WORKER_MEMORY_MIB if action == "frontend" else bootstrap.COMPILE_WORKER_MEMORY_MIB
            reserved_memory += (workers - 1) * estimate
        self.assertEqual(env[MEMORY_ENV], str(reserved_memory))
        self.assertEqual(memory_mb, reserved_memory if os.name == "nt" else bootstrap.MEMORY_MIB)
        self.assertEqual(env["OURO_CACHE"], "0")
        self.assertEqual(env["OURO_CCACHE"], "disabled")
        if shared_job is not None:
            self.assertTrue(shared_job.startswith("Local\\OuroSmith-"))
        self.events.append((list(argv), cwd))
        stdout, stderr, code, status = "", "", 0, "ok"
        if "worker" in argv:
            phase = argv[argv.index("--phase") + 1]
            action = argv[argv.index("--action") + 1]
            out = self.work / "out" / phase
            if action in {"c0", "link"}:
                binary = out / ("c/ouro1" if action == "c0" else "ouro1")
                binary.parent.mkdir(parents=True, exist_ok=True)
                binary.write_bytes(b"MZ" + phase.encode() + b"host fixture only; not a real compiler\n" * 150)
                binary.chmod(0o755)
            elif action == "frontend":
                data = "current generated frontend\n"
                if self.different_c and phase == "p2":
                    data += "different output\n"
                (out / "driver_u.c").write_text(data)
            elif action == "abi-build":
                (out / ("abi.exe" if os.name == "nt" else "abi")).write_bytes(b"host law fixture")
        elif "--module" in argv:
            stdout = '#include "ouro_rt.h"\nint ouro_export_count_be(void) { return 0; }\n'
        elif len(argv) == 1:
            stdout = self.abi_stdout
        elif argv[1] == "check":
            source = argv[2]
            if source == "bootstrap-bad.ouro":
                stdout, stderr = self.bad_stdout, self.bad_stderr
                code, status = self.bad_returncode, self.bad_status
            elif source == self.rejected_root and (self.rejected_source_form is None or cwd.name == self.rejected_source_form):
                code, stderr = 1, "current root rejected\n"
            else:
                stdout = "CHECK_OK\n"
        else:
            self.fail(f"unexpected host fixture command: {argv}")
        return RunResult(status, code, stdout, stderr, 0.01, 1.0, list(argv))

    def historical_fixture(self, attempt, *, current="original", abi_helper_source="original ABI build helper",
                           enabled=True, bridge2=False):
        self.work = self.root / attempt
        self.work.mkdir()
        self.events = []
        snapshot = self.fixture()
        selected = snapshot["selected"]
        original = self.work / "o"
        (original / selected["roots"][0]).write_text(current, encoding="utf-8")
        for name in bootstrap.HISTORICAL_HELPERS:
            for role in ("o", "historical/c0", "historical/bridge"):
                path = self.work / role / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture helper " + name, encoding="utf-8")
        (original / "scripts/native_tool_build.py").write_text(abi_helper_source, encoding="utf-8")
        stage0 = {}
        for name in inputs.STAGE0:
            path = self.work / "historical/c0" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("stage0 " + name, encoding="utf-8")
            stage0[name] = sha256_file(path)
        selected.update(kind=bootstrap.KIND, cc=selected["cc_executable"], cc_id="fixture cc version",
                        platform="fixture", machine="fixture", cflags=["-O1"], link_flags=[], stage0=stage0,
                        archive_sha256=inputs.digest(b"fixture archive"), manifest_sha256=inputs.digest(b"fixture manifest"),
                        sources={p.relative_to(original).as_posix(): sha256_file(p) for p in original.rglob("*") if p.is_file()})
        if bridge2:
            from shutil import copytree

            selected["bridge2"] = {inputs.BRIDGE2_ARCHIVE: "1" * 64, inputs.BRIDGE2_MANIFEST: "2" * 64}
            snapshot["bridge2_graph"] = {name: selected["unit_graph"][name] for name in selected["roots"]}
            snapshot["roots"]["bridge2"] = "historical/next/bridge2"
            copytree(self.work / "historical/bridge", self.work / snapshot["roots"]["bridge2"])
        snapshot["config"]["cache_enabled"] = enabled
        if enabled:
            snapshot["historical_host"] = bootstrap_historical.host_identity()
        snapshot["key"] = hash_json(selected)
        snapshot["inputs"] = {p.relative_to(self.work).as_posix(): sha256_file(p)
                              for directory in (original, self.work / "historical") for p in directory.rglob("*") if p.is_file()}
        write_json_atomic(self.work / "inputs.json", snapshot)
        return snapshot

    def test_historical_key_covers_producers_and_leaves_current_sources_to_the_current_key(self):
        from functools import partial

        snapshot = self.historical_fixture("key-inputs")
        selected = snapshot["selected"]
        host = snapshot["historical_host"]
        key_for = partial(bootstrap.historical_key, host=host)
        key = key_for(selected, 1)
        self.assertRegex(key, r"^[a-f0-9]{64}$")
        self.assertEqual(bootstrap.historical_key(selected, 1), key)
        self.assertNotEqual(key_for(selected, 2), key)
        for field, changed in (
            ("archive_sha256", "a" * 64), ("manifest_sha256", "b" * 64),
            ("cc", "other-cc"), ("cc_executable", "/new-fixture-cc"), ("cc_sha256", "c" * 64), ("cc_id", "other version"),
            ("platform", "other host"), ("machine", "other ABI"), ("cflags", ["-O2"]), ("link_flags", ["-g"]),
            ("environment", {"CPATH": "changed"}), ("roots", list(reversed(selected["roots"]))),
        ):
            with self.subTest(field=field):
                self.assertNotEqual(key_for({**selected, field: changed}, 1), key)
        for field, names in (("sources", bootstrap.HISTORICAL_HELPERS), ("stage0", inputs.STAGE0)):
            for name in names:
                with self.subTest(input=name):
                    changed = {**selected, field: {**selected[field], name: "d" * 64}}
                    self.assertNotEqual(key_for(changed, 1), key)
        for field in ("python", "image", "image_os"):
            with self.subTest(host=field):
                self.assertNotEqual(bootstrap.historical_key(selected, 1, host={**host, field: "changed"}), key)
        for name in ("as", "ld"):
            with self.subTest(tool=name):
                changed = {**host, "tools": {**host["tools"], name: "f" * 64}}
                self.assertNotEqual(bootstrap.historical_key(selected, 1, host=changed), key)
        current = selected["roots"][0]
        changed = {**selected, "sources": {**selected["sources"], current: "e" * 64}, "source_form": compact_source.KIND}
        self.assertEqual(key_for(changed, 1), key)
        self.assertNotEqual(hash_json(changed), hash_json(selected))

    def test_historical_hit_after_current_edit_preserves_complete_successor_work(self):
        cache = self.root / "historical-cache"
        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            first = self.historical_fixture("cold")
            cold = bootstrap.chain(self.work, first, build, historical_cache=cache)
        self.assertTrue(cold["pass"])
        packet = cache / (bootstrap.historical_key(first["selected"], 1) + ".zip")
        digest = sha256_file(packet)
        self.assertEqual(cold["historical_cache"]["key"], packet.stem)
        self.assertEqual(cold["historical_cache"]["sha256"], digest)
        for attempt, edit in (("edited-source", {"current": "edited current source"}),
                              ("edited-abi-helper", {"abi_helper_source": "edited ABI build helper"})):
            with self.subTest(attempt=attempt), patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
                changed = self.historical_fixture(attempt, **edit)
                warm = bootstrap.chain(self.work, changed, build, historical_cache=cache, historical_sha256=digest)
                self.assertNotEqual(first["key"], changed["key"])
                self.assertTrue(warm["pass"])
                self.assertEqual(warm["historical_cache"]["key"], packet.stem)
                self.assertEqual(warm["historical_cache"]["sha256"], digest)
                self.assertEqual([row["phase"] for row in warm["phases"]], ["c0", "bridge", "p1", "p2"])
                for old, reused in zip(cold["phases"][:2], warm["phases"][:2], strict=True):
                    self.assertTrue(old["commands"])
                    self.assertEqual(reused["cache"], "hit")
                    self.assertEqual(reused["commands"], [])
                    self.assertEqual(reused["binary_sha256"], old["binary_sha256"])
                self.assertEqual(warm["phases"][1]["producer_sha256"], warm["phases"][0]["binary_sha256"])
                self.assertEqual(warm["phases"][2]["producer_sha256"], warm["phases"][1]["binary_sha256"])
                for old, fresh in zip(cold["phases"][2:], warm["phases"][2:], strict=True):
                    cold_labels = [command["label"] for command in old["commands"]]
                    self.assertEqual([command["label"] for command in fresh["commands"]], cold_labels)
                    self.assertTrue(fresh["all_current_roots_strictly_checked_before_use"])
                self.assertEqual(len(self.events), sum(len(row["commands"]) for row in warm["phases"][2:]))
                for phase, expected in (("bridge", changed["selected"]["roots"]),
                                        ("p1", [*changed["selected"]["roots"], *bootstrap.ACCEPTANCE_ROOTS]),
                                        ("p2", ["bootstrap-good.ouro", "bootstrap-bad.ouro"])):
                    producer = str(self.work / "out" / phase / "ouro1")
                    checks = [argv[2] for argv, _ in self.events if len(argv) > 2 and argv[:2] == [producer, "check"]]
                    self.assertEqual(checks, expected)
                self.assertEqual(set(warm["complete_generated_c_comparison"]), {"driver_u.c", "backend_u.c"})
                p2_labels = {command["label"] for command in warm["phases"][3]["commands"]}
                self.assertTrue({"abi-build", "abi-laws", "behavior-good", "behavior-bad"} <= p2_labels)

    def test_second_bridge_checks_its_roots_and_preserves_the_chain_on_cache_hit(self):
        cache = self.root / "history-two-bridges"
        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            first = self.historical_fixture("cold-bridge2", bridge2=True)
            cold = bootstrap.chain(self.work, first, build, historical_cache=cache)
            key = bootstrap.historical_key(first["selected"], 1)
            packet = cache / (key + ".zip")
            digest = sha256_file(packet)
            second = self.historical_fixture("warm-bridge2", current="changed", bridge2=True)
            warm = bootstrap.chain(self.work, second, build, historical_cache=cache, historical_sha256=digest)

        self.assertEqual([row["phase"] for row in warm["phases"]], ["c0", "bridge", "bridge2", "p1", "p2"])
        self.assertEqual([row["cache"] for row in warm["phases"][:3]], ["hit"] * 3)
        bridge2 = cold["phases"][2]
        self.assertTrue(bridge2["all_current_roots_strictly_checked_before_use"])
        self.assertEqual([command["label"] for command in bridge2["commands"]],
                         [*(f"check-{index:02}" for index in range(15)), "frontend", "backend", "link"])
        self.assertEqual(warm["phases"][3]["producer_sha256"], bridge2["binary_sha256"])
        self.assertTrue(all(row["all_current_roots_strictly_checked_before_use"] for row in warm["phases"][-2:]))
        changed = {**second["selected"], "bridge2": {**second["selected"]["bridge2"], inputs.BRIDGE2_ARCHIVE: "3" * 64}}
        self.assertNotEqual(bootstrap.historical_key(changed, 1), key)

        bridge2["commands"].pop(0)
        receipt = {"kind": bootstrap_historical.KIND, "key": key, "report_sha256": "unused"}
        with self.assertRaisesRegex(ValueError, "second historical bridge phase mismatch"):
            bootstrap_historical.verified_origin(receipt, first, cold, second, key, bootstrap.historical_key)

    def test_second_bridge_rejection_stops_before_current_p1(self):
        snapshot = self.historical_fixture("rejected-bridge2", enabled=False, bridge2=True)
        self.rejected_root = snapshot["selected"]["roots"][0]
        self.rejected_source_form = "bridge2"
        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            with self.assertRaisesRegex(RuntimeError, "bridge2/check-00"):
                bootstrap.chain(self.work, snapshot, build)
        report = json.loads((self.work / "report.json").read_text(encoding="utf-8"))
        self.assertEqual([row["phase"] for row in report["phases"]], ["c0", "bridge", "bridge2"])
        self.assertFalse(report["pass"])
        self.assertFalse((self.work / "out/p1").exists())

    def test_disabled_historical_cache_rebuilds_and_preserves_the_cached_entry(self):
        cache = self.root / "historical-cache"
        fresh = self.historical_fixture("uncached", enabled=False)
        packet = cache / (bootstrap.historical_key(fresh["selected"], 1) + ".zip")
        cache.mkdir()
        original = b"preexisting cache entry"
        packet.write_bytes(original)
        os.utime(packet, (1_700_000_000, 1_700_000_000))
        modified = packet.stat().st_mtime_ns
        with (patch.object(bootstrap, "run_limited", side_effect=self.fake_run),
              patch.object(bootstrap_historical, "restore", side_effect=AssertionError("read a disabled cache")),
              patch.object(bootstrap_historical, "publish", side_effect=AssertionError("wrote a disabled cache"))):
            result = bootstrap.chain(self.work, fresh, build, historical_cache=cache)
        self.assertTrue(result["pass"])
        self.assertTrue(all(phase["commands"] for phase in result["phases"]))
        self.assertEqual(packet.stat().st_mtime_ns, modified)
        self.assertEqual(packet.read_bytes(), original)

    def test_failed_historical_publication_cannot_attest_a_preexisting_packet(self):
        cache = self.root / "historical-cache"
        cache.mkdir()
        snapshot = self.historical_fixture("publication-failure")
        packet = cache / (bootstrap.historical_key(snapshot["selected"], 1) + ".zip")
        packet.write_bytes(b"stale historical cache")
        with (patch.object(bootstrap, "run_limited", side_effect=self.fake_run),
              patch.object(bootstrap_historical, "publish", side_effect=OSError("cache unavailable")) as publish):
            result = bootstrap.chain(self.work, snapshot, build, historical_cache=cache)
        publish.assert_called_once()
        self.assertTrue(result["pass"])
        self.assertTrue(all(row["commands"] for row in result["phases"]))
        self.assertNotIn("sha256", result.get("historical_cache", {}))
        self.assertEqual(json.loads((self.work / "report.json").read_text()), result)
        self.assertEqual(packet.read_bytes(), b"stale historical cache")

    def test_changed_c_environment_stops_historical_publication(self):
        with patch.dict(os.environ, {"CPATH": ""}):
            snapshot = self.historical_fixture("changed-c-environment")

            def run_then_change_environment(argv, **options):
                self.assertEqual(options["env"]["CPATH"], "")
                result = self.fake_run(argv, **options)
                if argv[1:3] == ["check", "bootstrap-bad.ouro"]:
                    os.environ.pop("CPATH")
                return result

            with (patch.object(bootstrap, "run_limited", side_effect=run_then_change_environment),
                  patch.object(bootstrap_historical, "publish") as publish):
                with self.assertRaisesRegex(RuntimeError, "historical C toolchain changed before publication"):
                    bootstrap.chain(self.work, snapshot, build, historical_cache=self.root / "historical-cache")
        publish.assert_not_called()
        self.assertFalse(json.loads((self.work / "report.json").read_text())["pass"])

    def test_untrusted_historical_checksum_stops_before_opening_the_archive(self):
        packet = self.root / ("a" * 64 + ".zip")
        packet.write_bytes(b"untrusted contents")
        with patch.object(zipfile, "ZipFile", side_effect=AssertionError("parsed an unverified archive")):
            for digest in ("", "bad checksum", "f" * 64):
                with self.subTest(digest=digest):
                    self.assertIsNone(bootstrap_historical.restore(packet, self.work, {}, bootstrap.historical_key,
                                                                  expected_sha256=digest))
        self.assertFalse((self.work / "out").exists())

    def test_ensure_current_compiler_selects_local_or_verified_runner_historical_cache(self):
        checkout, directory, runner = (self.root / name for name in ("checkout", "build", "runner"))
        digest = "e" * 64
        cfg = build.ResolvedConfig({**build.DEFAULTS, "build_dir": str(directory), "c_build_dir": str(directory / "c")}, {})
        with (patch.object(inputs, "read_bundle", return_value=({}, {})), patch.object(inputs, "verify_stage0"),
              patch.object(bootstrap, "current_inputs", return_value={}), patch.object(bootstrap, "freeze", return_value={}),
              patch.object(bootstrap, "chain", side_effect=RuntimeError("stop before compilation")) as chain):
            for action, temp, pin, expected in (
                ("", "", "", directory / "bootstrap-historical"), ("true", str(runner), digest, runner / "bootstrap-historical"),
                ("true", str(runner), "", runner / "bootstrap-historical"), ("true", "", "", None),
                ("true", "relative", digest, None), ("true", str(checkout / "tracked"), digest, None),
            ):
                env = {"GITHUB_ACTIONS": action, "RUNNER_TEMP": temp, "OURO_BOOTSTRAP_HISTORY_SHA256": pin}
                with self.subTest(env=env), patch.dict(os.environ, env):
                    with self.assertRaisesRegex(RuntimeError, "before compilation"):
                        bootstrap.ensure_current_compiler(cfg, build, checkout)
                    self.assertEqual(chain.call_args.kwargs.get("historical_cache"), expected)
                    if expected:
                        self.assertEqual(chain.call_args.kwargs.get("historical_sha256"), pin if action else None)

    def test_local_ci_reuses_verified_compiler_after_unrelated_edit(self):
        shared = self.root / "_build/ci-bootstrap"
        cc = self.root / "fake-cc"
        cc.write_bytes(b"C compiler fixture")

        def selected(root, _cfg, _build, *, compact_sources):
            self.assertFalse(compact_sources)
            return {"sources": {"compiler.ouro": sha256_file(root / "compiler.ouro")},
                    "cc_executable": str(cc), "cc_sha256": sha256_file(cc), "stage0": {},
                    "archive_sha256": sha256_file(root / inputs.ARCHIVE),
                     "manifest_sha256": sha256_file(root / inputs.MANIFEST),
                     "environment": bootstrap.c_toolchain_environment()}

        histories = []

        def chain(work, snapshot, _build, *, historical_cache, historical_sha256):
            histories.append(historical_cache)
            self.assertIsNone(historical_sha256)
            write_json_atomic(work / "inputs.json", snapshot)
            comparison = {}
            for name in ("driver_u.c", "backend_u.c"):
                for phase in ("p1", "p2"):
                    path = work / "out" / phase / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(name, encoding="utf-8")
                digest = sha256_file(path)
                comparison[name] = {"p1_sha256": digest, "p2_sha256": digest}
            binary = work / "out/p2/ouro1"
            binary.write_bytes(f"fake compiler #{len(histories)}".encode() * 300)
            report = {"kind": bootstrap.KIND, "key": hash_json(snapshot), "pass": True,
                      "binary": "out/p2/ouro1", "binary_sha256": sha256_file(binary),
                      "inputs_sha256": sha256_file(work / "inputs.json"),
                      "complete_generated_c_comparison": comparison}
            write_json_atomic(work / "report.json", report)
            return report

        def prepare(attempt, source, readme, *, cache_enabled=True):
            checkout = self.root / "_build" / f"ci-{attempt}" / "source"
            checkout.mkdir(parents=True)
            (checkout / "compiler.ouro").write_text(source, encoding="utf-8")
            (checkout / "README.md").write_text(readme, encoding="utf-8")
            for name in (inputs.ARCHIVE, inputs.MANIFEST):
                path = checkout / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name, encoding="utf-8")
            directory = checkout / "_build"
            cfg = build.ResolvedConfig({**build.DEFAULTS, "build_dir": str(directory),
                                       "c_build_dir": str(directory / "c"), "cache_enabled": cache_enabled}, {})
            result = bootstrap.ensure_current_compiler(cfg, build, checkout)
            output = directory / "c/ouro1"
            receipt = output.with_name("ouro1.bootstrap.json")
            expected = selected(checkout, cfg, build, compact_sources=False)
            self.assertTrue(bootstrap.installed_current(output, receipt, expected))
            self.assertEqual(Path(json.loads(receipt.read_text(encoding="utf-8"))["work"]).parent,
                             directory / "bootstrap")
            return result

        with (patch.dict(os.environ, {bootstrap.LOCAL_CACHE_ENV: "1", "GITHUB_ACTIONS": ""}),
              patch.object(inputs, "read_bundle", return_value=({}, {})), patch.object(inputs, "verify_stage0"),
              patch.object(bootstrap, "current_inputs", side_effect=selected),
              patch.object(bootstrap, "freeze", side_effect=lambda _root, _work, snapshot, _cfg: snapshot),
              patch.object(bootstrap, "chain", side_effect=chain)):
            cold = prepare("first", "one", "old")
            warm = prepare("readme", "one", "new")
            self.assertEqual(warm["cache"], "hit")
            self.assertEqual(warm["binary_sha256"], cold["binary_sha256"])
            self.assertEqual(len(histories), 1)
            changed = prepare("source", "two", "new")
            self.assertNotEqual(changed["binary_sha256"], cold["binary_sha256"])
            self.assertEqual(len(histories), 2)
            cached = shared / "current" / changed["key"][:16] / "c/ouro1"
            cache_receipt = cached.with_name("ouro1.bootstrap.json")
            stored = json.loads(cache_receipt.read_text(encoding="utf-8"))
            self.assertEqual(stored["key"], changed["key"])
            self.assertEqual(stored["selected"], changed["selected"])
            work = Path(stored["work"])
            (work / "out/p1/driver_u.c").write_bytes(b"tampered C evidence")
            rebuilt = prepare("tampered", "two", "new")
            self.assertNotEqual(rebuilt["binary_sha256"], changed["binary_sha256"])
            self.assertTrue(bootstrap.installed_current(cached, cache_receipt, rebuilt["selected"]))
            uncached = prepare("disabled", "two", "new", cache_enabled=False)
            self.assertNotEqual(uncached["binary_sha256"], rebuilt["binary_sha256"])
            self.assertEqual(sha256_file(cached), rebuilt["binary_sha256"])
            self.assertEqual(histories, [shared / "bootstrap-historical"] * 3 + [None])

    def test_incomplete_or_corrupt_historical_entries_rebuild_before_current_rejection(self):
        cache = self.root / "historical-cache"
        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            seed = self.historical_fixture("seed")
            bootstrap.chain(self.work, seed, build, historical_cache=cache)
            packet = cache / (bootstrap.historical_key(seed["selected"], 1) + ".zip")
            with zipfile.ZipFile(packet) as archive:
                comment = archive.comment
                members = [(info, archive.read(info)) for info in archive.infolist()]
            original = {info.filename: content for info, content in members}
            for mutation in ("truncated", "missing-backend", "changed-backend", "changed-c0", "bad-receipt",
                             "foreign-inputs", "broken-link", "unchecked-p1", "missing-p2-checks"):
                with self.subTest(mutation=mutation):
                    files = original.copy()
                    if mutation == "missing-backend":
                        del files["out/bridge/backend_u.c"]
                    if mutation in {"changed-backend", "changed-c0"}:
                        name = "out/bridge/backend_u.c" if mutation == "changed-backend" else "out/c0/c/ouro1"
                        files[name] = bytes([files[name][0] ^ 1]) + files[name][1:]
                    if mutation == "bad-receipt":
                        files["receipt.json"] = b"{"
                    if mutation in {"foreign-inputs", "broken-link", "unchecked-p1", "missing-p2-checks"}:
                        report = json.loads(files["report.json"])
                        if mutation == "broken-link":
                            report["phases"][1]["producer_sha256"] = report["phases"][1]["binary_sha256"]
                        elif mutation == "unchecked-p1":
                            report["phases"][2]["all_current_roots_strictly_checked_before_use"] = False
                        elif mutation == "missing-p2-checks":
                            del report["phases"][3]["all_current_roots_strictly_checked_before_use"]
                        else:
                            recorded = json.loads(files["inputs.json"])
                            recorded["inputs"]["historical/c0/scripts/bootstrap_compiler.py"] = "a" * 64
                            files["inputs.json"] = json.dumps(recorded).encode()
                            report["inputs_sha256"] = inputs.digest(files["inputs.json"])
                        files["report.json"] = json.dumps(report).encode()
                        receipt = json.loads(files["receipt.json"])
                        receipt["report_sha256"] = inputs.digest(files["report.json"])
                        files["receipt.json"] = json.dumps(receipt).encode()
                    stream = io.BytesIO()
                    with zipfile.ZipFile(stream, "w") as archive:
                        archive.comment = comment
                        for info, _ in members:
                            if info.filename in files:
                                archive.writestr(copy.copy(info), files[info.filename])
                    damaged = stream.getvalue()[:-20] if mutation == "truncated" else stream.getvalue()
                    packet.write_bytes(damaged)
                    candidate = self.root / mutation
                    candidate.mkdir()
                    self.assertIsNone(bootstrap_historical.restore(packet, candidate, seed, bootstrap.historical_key))
                    self.assertFalse((candidate / "out").exists())
            damaged = packet.read_bytes()
            snapshot = self.historical_fixture("rebuild")
            self.rejected_root = snapshot["selected"]["roots"][0]
            with self.assertRaisesRegex(RuntimeError, "p1/check-00"), patch("sys.stderr", new_callable=io.StringIO):
                bootstrap.chain(self.work, snapshot, build, historical_cache=cache)
            report = json.loads((self.work / "report.json").read_text())
            self.assertFalse(report["pass"])
            self.assertTrue(all(row["commands"] and row["pass"] for row in report["phases"][:2]))
            if packet.exists():
                self.assertEqual(packet.read_bytes(), damaged)

    def test_concurrent_historical_publishers_expose_a_complete_entry(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier, local

        snapshot = self.historical_fixture("source")
        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            report = bootstrap.chain(self.work, snapshot, build)
        packet = self.root / "shared" / (bootstrap.historical_key(snapshot["selected"], 1) + ".zip")
        ready = Barrier(2, timeout=10)
        writer = local()
        replace = os.replace

        def publish_ready(temporary, target):
            self.assertEqual(target, packet)
            if not getattr(writer, "ready", False):
                self.assertFalse(packet.exists())
                with zipfile.ZipFile(temporary) as archive:
                    self.assertIsNone(archive.testzip())
                ready.wait()
                writer.ready = True
            replace(temporary, target)

        with patch.object(os, "replace", side_effect=publish_ready) as publish, ThreadPoolExecutor(max_workers=2) as pool:
            writers = [pool.submit(bootstrap_historical.publish, packet, self.work, report) for _ in range(2)]
            for result in writers:
                result.result(timeout=20)
        self.assertGreaterEqual(publish.call_count, 2)
        self.assertEqual(list(packet.parent.iterdir()), [packet])
        reader = self.root / "reader"
        reader.mkdir()
        self.assertIsNotNone(bootstrap_historical.restore(packet, reader, snapshot, bootstrap.historical_key))
        for name in bootstrap_historical.PAYLOADS:
            self.assertEqual(sha256_file(reader / name), sha256_file(self.work / name))
            if os.name != "nt" and name.endswith("/ouro1"):
                self.assertTrue(os.access(reader / name, os.X_OK))

        replacement = self.root / "other-packet.zip"
        with zipfile.ZipFile(replacement, "w") as archive:
            archive.writestr("other", b"another writer")
        prepared = []

        def replace_twice(temporary, target):
            prepared.append(sha256_file(Path(temporary)))
            replace(temporary, target)
            replace(replacement, target)

        with patch.object(os, "replace", side_effect=replace_twice):
            digest = bootstrap_historical.publish(packet, self.work, report)
        self.assertEqual(prepared, [digest])
        self.assertNotEqual(digest, sha256_file(packet))

    def test_bootstrap_workers_respect_positive_configuration(self):
        for requested, expected in ((1, 1), (2, 2), (10, 10), (19, 19)):
            with self.subTest(jobs=requested):
                self.assertEqual(bootstrap.bootstrap_workers({"jobs": requested}, build), expected)
        for cpus, expected in ((None, 1), (1, 1), (8, 8), (20, 20)):
            with self.subTest(cpus=cpus), patch.object(build.os, "cpu_count", return_value=cpus):
                self.assertEqual(bootstrap.bootstrap_workers({"jobs": "auto"}, build), expected)
        with patch.dict(os.environ, {JOBS_ENV: "1"}), patch.object(build.os, "cpu_count", return_value=20):
            self.assertEqual(bootstrap.bootstrap_workers({"jobs": 20}, build), 1)
            self.assertEqual(bootstrap.bootstrap_workers({"jobs": "auto"}, build), 1)
        for invalid in (0, -1, True, False, 1.5, "2", None):
            with self.subTest(jobs=invalid), self.assertRaisesRegex(RuntimeError, "positive integer"):
                bootstrap.bootstrap_workers({"jobs": invalid}, build)

    def test_bootstrap_worker_budget_preserves_complete_command_order(self):
        reference = None
        for requested, expected in ((1, 1), (2, 2), (10, 10), (19, 19), (20, 20), ("auto", 8)):
            with self.subTest(jobs=requested):
                self.work = self.root / ("workers-" + str(requested))
                self.work.mkdir()
                self.events = []
                self.expected_workers = expected
                snapshot = self.fixture()
                snapshot["config"]["jobs"] = requested
                write_json_atomic(self.work / "inputs.json", snapshot)
                with patch.object(build.os, "cpu_count", return_value=8), \
                     patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
                    report = bootstrap.chain(self.work, snapshot, build)
                self.assertTrue(report["pass"])
                self.assertEqual(report["workers"], expected)
                self.assertEqual(report["phases"][0]["commands"][0]["workers"], expected)
                self.assertLessEqual(report["peak_allocated_workers"], expected)
                self.assertGreater(report["elapsed_s"], 0)
                self.assertEqual(report["memory_mib"], 3072)
                self.assertEqual(report["parallel_memory_mib"],
                                 3072 + (expected - 1) * 1024 if os.name == "nt" else 3072)
                self.assertEqual([phase["phase"] for phase in report["phases"]], ["c0", "bridge", "p1", "p2"])
                commands = []
                for phase in report["phases"]:
                    for command in phase["commands"]:
                        argv = list(command["argv"])
                        if "worker" in argv:
                            position = argv.index("--jobs")
                            del argv[position:position + 2]
                        commands.append(([arg.replace(str(self.work), "WORK") for arg in argv],
                                         Path(command["cwd"]).relative_to(self.work).as_posix()))
                self.assertEqual(len(commands), 48)
                if reference is None:
                    reference = commands
                else:
                    self.assertEqual(commands, reference)

    def test_source_checks_overlap_and_report_in_source_order(self):
        snapshot = self.fixture()
        roots = snapshot["selected"]["roots"][:2]
        tasks = bootstrap.source_checks(self.root / "producer", self.work / "o", roots,
                                        snapshot["selected"]["unit_graph"])
        (self.work / "o" / roots[1]).write_text("large input " * 1000)
        ready = threading.Barrier(2, timeout=5)
        started, submitted, recorded = [], [], []
        lock = threading.Lock()

        def invoke(label, argv, _root, **options):
            self.assertEqual(options["allocation"], Allocation(1, bootstrap.MEMORY_MIB))
            with lock:
                started.append(label)
            ready.wait()
            return RunResult("ok", 0, "CHECK_OK\n", "", 0.01, 1.0, argv), {"label": label}

        original_submit = concurrent.futures.ThreadPoolExecutor.submit

        def submit(pool, function, *args, **options):
            submitted.append(args[0])
            return original_submit(pool, function, *args, **options)

        main_thread = threading.get_ident()

        def record(_result, row):
            self.assertEqual(threading.get_ident(), main_thread)
            recorded.append(row["label"])

        with patch.object(concurrent.futures.ThreadPoolExecutor, "submit", new=submit):
            bootstrap.strict_roots(tasks, 2, 4096, invoke, record)
        self.assertEqual(submitted[0], "check-01")
        self.assertEqual(set(started), {"check-00", "check-01"})
        self.assertEqual(recorded, ["check-00", "check-01"])

    def test_source_checks_reject_extra_output_before_recording_later_results(self):
        snapshot = self.fixture()
        tasks = bootstrap.source_checks(self.root / "producer", self.work / "o",
            snapshot["selected"]["roots"][:2], snapshot["selected"]["unit_graph"])
        recorded = []

        def invoke(label, argv, _root, **_options):
            stdout = "CHECK_OK\nextra\n" if label == "check-00" else "CHECK_OK\n"
            return RunResult("ok", 0, stdout, "", 0.01, 1.0, argv), {"label": label}

        with self.assertRaisesRegex(RuntimeError, "compiler/source-0.ouro"):
            bootstrap.strict_roots(tasks, 2, 4096, invoke,
                                   lambda _result, row: recorded.append(row["label"]))
        self.assertEqual(recorded, ["check-00"])

    def test_bootstrap_resources_recover_parallelism_when_memory_returns(self):
        with patch("repo_support.available_memory_mb", side_effect=(8192, 32768)):
            limited = bootstrap.bootstrap_resources(19)
            recovered = bootstrap.bootstrap_resources(19)
        self.assertEqual(limited[0], 5)
        self.assertEqual(recovered[0], 19)
        self.assertIsNotNone(limited[2])
        self.assertIsNone(recovered[2])

    def test_compile_budget_uses_all_cpus_when_memory_allows(self):
        with patch("repo_support.available_memory_mb", return_value=16384):
            workers, memory, note = bootstrap.bootstrap_resources(20, worker_memory_mib=512)
        self.assertEqual(workers, 20)
        self.assertEqual(memory, 12800)
        self.assertIsNone(note)

    def test_parallel_bootstrap_preserves_failure_barriers(self):
        failures = {}
        for jobs, mode in itertools.product((1, 20), ("root", "generated-c", "abi", "negative", "timeout", "tampered-input")):
            with self.subTest(jobs=jobs, mode=mode):
                self.work = self.root / (str(jobs) + "-" + mode)
                self.work.mkdir()
                self.events = []
                self.expected_workers = jobs
                self.rejected_root = None
                self.different_c = mode == "generated-c"
                self.abi_stdout = "" if mode == "abi" else bootstrap.ABI_STDOUT
                self.bad_stdout = "unexpected\n" if mode == "negative" else ""
                self.bad_status = "timeout" if mode == "timeout" else "ok"
                snapshot = self.fixture()
                snapshot["config"]["jobs"] = jobs
                write_json_atomic(self.work / "inputs.json", snapshot)
                if mode == "root":
                    self.rejected_root = snapshot["selected"]["roots"][-1]
                if mode == "tampered-input":
                    (self.work / "o/compiler/backend.ouro").write_text("changed after freeze")
                with patch.object(bootstrap, "run_limited", side_effect=self.fake_run), self.assertRaises(RuntimeError):
                    bootstrap.chain(self.work, snapshot, build)
                report = json.loads((self.work / "report.json").read_text())
                failure = report["failure"].replace(str(self.work), "WORK")
                if jobs == 1:
                    failures[mode] = failure
                else:
                    self.assertEqual(failure, failures[mode])
                self.assertFalse(report["pass"])
                if mode in {"root", "abi"}:
                    stage = "p1" if mode == "root" else "p2"
                    self.assertEqual(report["phases"][-1]["phase"], stage)
                    binary = str(self.work / "out" / stage / "ouro1")
                    self.assertFalse(any(binary in argv for argv, _root in self.events))
                if mode == "tampered-input":
                    self.assertEqual(self.events, [])

    def overlapped_fixture(self):
        self.expected_workers = 2
        snapshot = self.fixture()
        snapshot["config"]["jobs"] = 2
        write_json_atomic(self.work / "inputs.json", snapshot)
        return snapshot

    def test_stages_generate_after_checks_and_share_budget_with_abi(self):
        snapshot = self.overlapped_fixture()
        binaries = {phase: str(self.work / "out" / phase / "ouro1") for phase in ("bridge", "p1", "p2")}
        binaries["c0"] = str(self.work / "out/c0/c/ouro1")
        law = str(self.work / "out/p2" / ("abi.exe" if os.name == "nt" else "abi"))
        paired_builds = threading.Barrier(2, timeout=5)
        clock, lock, spans = itertools.count(), threading.Lock(), []

        def observed(argv, **options):
            with lock:
                begin = next(clock)
            if "worker" in argv:
                name = argv[argv.index("--phase") + 1] + "/" + argv[argv.index("--action") + 1]
                if name in {"p2/frontend", "p2/abi-build"}:
                    self.assertEqual(options["env"]["OURO_JOBS"], "1")
                    paired_builds.wait()
            result = self.fake_run(argv, **options)
            with lock:
                spans.append((list(argv), begin, next(clock)))
            return result

        with patch.object(bootstrap, "run_limited", side_effect=observed):
            report = bootstrap.chain(self.work, snapshot, build)
        self.assertTrue(report["pass"])
        self.assertEqual(report["peak_commands"], 2)
        self.assertEqual(report["peak_allocated_workers"], 2)
        self.assertEqual([phase.get("overlap") for phase in report["phases"]], [None, False, False, True])

        def begins(selected):
            return [begin for argv, begin, _end in spans if selected(argv)]

        def ends(selected):
            return [end for argv, _begin, end in spans if selected(argv)]

        def stage_command(stage, producer):
            return lambda argv: (producer in argv or (argv == [law] and stage == "p2")
                                 or ("worker" in argv and argv[argv.index("--phase") + 1] == stage))

        for stage, producer in (("bridge", "c0"), ("p1", "bridge"), ("p2", "p1")):
            with self.subTest(stage=stage):
                used = begins(lambda argv, binary=binaries[stage]: binary in argv)
                self.assertTrue(used)
                self.assertGreater(min(used), max(ends(stage_command(stage, binaries[producer]))))
        for stage, producer in (("p1", "bridge"), ("p2", "p1")):
            with self.subTest(stage=stage):
                generated = begins(lambda argv, stage=stage:
                                   "worker" in argv and argv[argv.index("--phase") + 1] == stage)
                checked = ends(lambda argv, binary=binaries[producer]: argv[0] == binary and argv[1] == "check")
                self.assertGreater(min(generated), max(checked))
        self.assertGreater(min(begins(lambda argv: argv == [law])),
                           max(ends(lambda argv: argv[0] == binaries["p1"] and argv[1] == "check")
                               + ends(lambda argv: "abi-build" in argv)))

    def test_check_failure_does_not_start_generation(self):
        snapshot = self.overlapped_fixture()
        self.rejected_root = snapshot["selected"]["roots"][-1]
        def observed(argv, **options):
            if "worker" in argv and argv[argv.index("--phase") + 1] == "p1" and "frontend" in argv:
                self.fail("P1 generation started before the strict checks passed")
            return self.fake_run(argv, **options)

        with patch.object(bootstrap, "run_limited", side_effect=observed):
            with self.assertRaisesRegex(RuntimeError, "p1/check-14"):
                bootstrap.chain(self.work, snapshot, build)
        report = json.loads((self.work / "report.json").read_text())
        stage = report["phases"][-1]
        self.assertFalse(report["pass"])
        self.assertEqual(stage["phase"], "p1")
        self.assertEqual([row["label"] for row in stage["commands"]], [f"check-{index:02}" for index in range(15)])
        self.assertFalse((self.work / "out/p1/ouro1").exists())
        p1 = str(self.work / "out/p1/ouro1")
        self.assertFalse(any(p1 in argv for argv, _root in self.events))

    def test_stage_lanes_share_the_allocated_cpu_and_memory(self):
        with patch("repo_support.available_memory_mb", return_value=17000):
            self.assertIsNone(bootstrap.stage_lanes(1, 8192))
            self.assertIsNone(bootstrap.stage_lanes(20, 4096))
            allocations = bootstrap.stage_lanes(20, 8192)
            self.assertIsNotNone(allocations)
            self.assertEqual(sum(lease.jobs for lease in allocations), 20)
            self.assertEqual(sum(lease.memory_mib for lease in allocations), 8192)
            for lease, estimate, expected in zip(allocations, (512, 1024), (3, 2), strict=True):
                count, planned, _note = bootstrap.bootstrap_resources(lease.jobs, worker_memory_mib=estimate,
                                                                      memory_budget_mib=lease.memory_mib)
                self.assertEqual(count, expected)
                self.assertLessEqual(planned, lease.memory_mib)
        for invalid in ("0", "409", "bad"):
            with self.subTest(memory=invalid), patch.dict(os.environ, {MEMORY_ENV: invalid}):
                with self.assertRaisesRegex((RuntimeError, ValueError), MEMORY_ENV):
                    bootstrap.allocated_memory()

    def test_worker_actions_receive_the_same_bounded_budget(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        for index, (requested, expected, cpus) in enumerate(((1, 1, 8), (2, 2, 8), (10, 10, 8),
                                                           (19, 19, 20), ("auto", 20, 20), ("auto", 1, 1))):
            self.work = self.root / ("dispatch-" + str(index))
            self.work.mkdir()
            snapshot = self.fixture()
            with patch.object(build.os, "cpu_count", return_value=cpus):
                snapshot["config"]["jobs"] = bootstrap.bootstrap_workers({"jobs": requested}, build)
            write_json_atomic(self.work / "inputs.json", snapshot)
            for action, phase in (("c0", "c0"), ("frontend", "bridge"), ("frontend", "p1"),
                                  ("frontend", "p2"), ("link", "p1"), ("abi-build", "p2")):
                with self.subTest(jobs=requested, action=action):
                    (self.work / "out" / phase).mkdir(parents=True, exist_ok=True)
                    worker_root = (self.work / snapshot["roots"][phase]).resolve()
                    stage = SimpleNamespace(build_config=Mock(return_value=SimpleNamespace()),
                                            build_stage_binary=Mock(return_value={}))
                    native = SimpleNamespace(build_tool=Mock(return_value={}))
                    args = SimpleNamespace(snapshot=self.work / "inputs.json", phase=phase, action=action,
                                           producer=self.root / "producer")
                    with patch.object(build.os, "cpu_count", side_effect=AssertionError("worker re-resolved auto jobs")), \
                         patch.dict("sys.modules", {"ouro_build": build, "stage_loop": stage, "native_tool_build": native}), \
                         patch.object(bootstrap, "ROOT", worker_root), \
                         patch.object(bootstrap.threading, "stack_size"), \
                         patch.object(build, "build_c") as compile_c, \
                         patch.object(bootstrap.frontend, "ROOT", worker_root), \
                         patch.object(bootstrap.frontend, "regenerate") as emit:
                        bootstrap.worker(args)
                    if action == "c0":
                        values = compile_c.call_args.args[0].values
                    elif action == "frontend":
                        self.assertEqual(emit.call_args.kwargs["jobs"], expected)
                        self.assertFalse(emit.call_args.kwargs["cache_enabled"])
                        self.assertEqual(emit.call_args.kwargs["historical_bridge"], phase == "bridge")
                        continue
                    elif action == "link":
                        self.assertEqual(stage.build_stage_binary.call_args.args[3], 1)
                        config = stage.build_stage_binary.call_args.args[4]
                        self.assertFalse(config.cache_enabled)
                        values = config.build_cfg.values
                    else:
                        values = vars(native.build_tool.call_args.args[0])
                    self.assertEqual(values["jobs"], expected)
                    self.assertFalse(values["cache_enabled"])
                    self.assertEqual(values["ccache"], "disabled")

    def test_c0_worker_sets_stack_before_parallel_linux_build(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        snapshot = self.fixture()
        snapshot["requested_workers"] = 20
        snapshot_path = self.work / "inputs.json"
        write_json_atomic(snapshot_path, snapshot)
        worker_root = (self.work / snapshot["roots"]["c0"]).resolve()
        cases = (("linux", 20, 8 * 1024 * 1024), ("linux", 1, None),
                 ("win32", 20, None), ("darwin", 20, None))

        for platform, jobs, stack_size in cases:
            dispatch = Mock()
            with (self.subTest(platform=platform, jobs=jobs),
                  patch.object(bootstrap, "ROOT", worker_root),
                  patch.object(bootstrap.sys, "platform", platform),
                  patch.dict(os.environ, {JOBS_ENV: str(jobs)}),
                  patch.object(bootstrap.threading, "stack_size", dispatch.stack_size),
                  patch.object(build, "build_c", dispatch.build_c)):
                bootstrap.worker(SimpleNamespace(snapshot=snapshot_path, phase="c0", action="c0",
                                                 producer=None, jobs=jobs))
                expected_calls = ["build_c"] if stack_size is None else ["stack_size", "build_c"]
                self.assertEqual([call[0] for call in dispatch.mock_calls], expected_calls)
                if stack_size is not None:
                    dispatch.stack_size.assert_called_once_with(stack_size)
                self.assertEqual(dispatch.build_c.call_args.args[0].values["jobs"], jobs)

    def test_worker_rejects_foreign_root_and_changed_frozen_inputs(self):
        from types import SimpleNamespace

        snapshot = self.fixture()
        args = SimpleNamespace(snapshot=self.work / "inputs.json", phase="c0", action="c0", producer=None)
        expected_root = (self.work / snapshot["roots"]["c0"]).resolve()
        for mismatch in ("root", "input"):
            with self.subTest(mismatch=mismatch):
                if mismatch == "input":
                    (self.work / "o/compiler/backend.ouro").write_text("changed after freeze")
                worker_root = self.root / "foreign" if mismatch == "root" else expected_root
                with patch.object(bootstrap, "ROOT", worker_root), \
                     patch.object(build, "build_c") as compile_c, \
                     self.assertRaisesRegex(RuntimeError, "worker source root or frozen input mismatch"):
                    bootstrap.worker(args)
                compile_c.assert_not_called()

    def test_abi_build_worker_requires_current_p2(self):
        from types import SimpleNamespace

        snapshot = self.fixture()
        args = SimpleNamespace(snapshot=self.work / "inputs.json", phase="bridge", action="abi-build")
        root = (self.work / snapshot["roots"]["bridge"]).resolve()
        with (patch.object(bootstrap, "ROOT", root), patch.dict("sys.modules", {"native_tool_build": None}),
              self.assertRaisesRegex(RuntimeError, "ABI build requires current P2")):
            bootstrap.worker(args)

    def test_frontend_worker_reads_shared_imports_once(self):
        from types import SimpleNamespace

        snapshot = self.fixture()
        first, second = snapshot["selected"]["roots"][:2]
        snapshot["selected"]["roots"] = [first, second]
        snapshot["selected"]["unit_graph"][second] = [first, second]
        root = self.work / snapshot["roots"]["p1"]
        source = root / second
        source.write_text(f'import "{Path(first).name}";\n', encoding="utf-8")
        snapshot["inputs"][source.relative_to(self.work).as_posix()] = sha256_file(source)
        args = SimpleNamespace(snapshot=self.work / "inputs.json", phase="p1",
                               action="frontend", producer=self.root / "producer")
        write_json_atomic(args.snapshot, snapshot)
        with patch.object(bootstrap, "ROOT", root.resolve()), \
             patch.object(bootstrap.frontend, "ROOT", root), \
             patch.object(bootstrap.frontend, "import_targets", wraps=bootstrap.frontend.import_targets) as imports, \
             patch.object(bootstrap.frontend, "regenerate") as emit:
            bootstrap.worker(args)

        self.assertEqual([call.args[0] for call in imports.call_args_list], [first, second])
        emit.assert_called_once()

    def test_frontend_worker_checks_closure_order_before_later_import_errors(self):
        from types import SimpleNamespace

        snapshot = self.fixture()
        first, second, left, right = snapshot["selected"]["roots"][:4]
        snapshot["selected"]["roots"] = [first, second]
        snapshot["selected"]["unit_graph"][first] = [left, right, first]
        snapshot["bridge_graph"] = {first: [right, left, first], second: [second]}
        root = self.work / snapshot["roots"]["bridge"]
        for name, imports in ((first, (Path(left).name, Path(right).name)),
                              (second, ("absent.ouro",))):
            source = root / name
            source.write_text("".join(f'import "{path}";\n' for path in imports), encoding="utf-8")
            snapshot["inputs"][source.relative_to(self.work).as_posix()] = sha256_file(source)
        args = SimpleNamespace(snapshot=self.work / "inputs.json", phase="bridge",
                               action="frontend", producer=self.root / "producer")
        write_json_atomic(args.snapshot, snapshot)
        with patch.object(bootstrap, "ROOT", root.resolve()), \
             patch.object(bootstrap.frontend, "ROOT", root), \
             patch.object(bootstrap.frontend, "regenerate") as emit, \
             self.assertRaisesRegex(RuntimeError, "worker ordered source closure changed"):
            bootstrap.worker(args)

        emit.assert_not_called()

    def test_compaction_preserves_literal_bytes_directives_and_line_boundaries(self):
        literal = '"  -- @entry other\\n\\\"\\\\\t\r\nЮник\u043eд  "'.encode()
        source = (b'  -- ordinary comment with "\r\n\r\n  -- @entry main\r\n'
                  b"def foo'   :  String := " + literal + b'; -- trailing comment\r\n'
                  b"  -- \t@export foo'; @doc docs/build.md\n\n  def main : Nat :=  1;\n")
        expected = (b"-- @entry main\r\ndef foo' : String := " + literal + b";\n"
                    b"-- \t@export foo'; @doc docs/build.md\ndef main : Nat := 1;\n")
        result = compact_source.compact_source(source)
        self.assertEqual(result, expected)
        self.assertEqual(compact_source.compact_source(result), result)
        self.assertLess(len(result), len(source))

    def test_compaction_keeps_token_separators_and_does_not_repair_invalid_bytes(self):
        source = b"  f' -  - g'  : =  x; -- removed\n\tfoo\vbar\xc2\xa0baz\n"
        self.assertEqual(compact_source.compact_source(source), b"f' - - g' : = x;\nfoo\vbar\xc2\xa0baz\n")
        self.assertEqual(compact_source.compact_source(b' -- comment "\n\t'), b"")
        for invalid in (b'"missing', b'"trailing\\', b'"escaped\\"'):
            with self.subTest(source=invalid), self.assertRaisesRegex(ValueError, "unterminated string"):
                compact_source.compact_source(invalid)

    def test_compaction_preserves_grouped_and_aliased_imports(self):
        from selfhost_module_cache import quoted_import_targets
        source = (b'import  "../std/data.ouro", -- first import\n "../std/list.ouro", ;\n'
                  b'import "../std/text.ouro" as Text;\n'
                  b'def fake : String := "import \\\"not-a-module.ouro\\\";";\n')
        original = quoted_import_targets(source.decode(), "compiler/probe.ouro")
        self.assertEqual(original, ["std/data.ouro", "std/list.ouro", "std/text.ouro"])
        self.assertEqual(quoted_import_targets(compact_source.compact_source(source).decode(), "compiler/probe.ouro"), original)

    def test_compaction_preserves_raw_multiline_bytes_and_real_directives(self):
        from selfhost_module_cache import quoted_import_targets

        literal = b'r#"  -- @export fake\nimport "fake.ouro";\\n\n"#'
        source = (b'def text : String := ' + literal + b'; -- trailing\n'
                  b'-- @export real\nimport r#"real.ouro"#;\n')
        compacted = compact_source.compact_source(source)
        self.assertIn(literal, compacted)
        self.assertIn(b'-- @export real\n', compacted)
        self.assertEqual(quoted_import_targets(compacted.decode(), "compiler/probe.ouro"),
                         ["compiler/real.ouro"])
        self.assertEqual(compact_source.compact_source(compacted), compacted)

    def test_compaction_preserves_dedented_multiline_bytes_and_real_directives(self):
        literal = b'"""\r\n  -- @export fake\r\n\r\n  import "fake.ouro"; \\n\r\n  """'
        source = (b'def text : String := ' + literal + b'; -- trailing\n'
                  b'-- @export real\nimport "real.ouro";\n')
        compacted = compact_source.compact_source(source)
        self.assertIn(literal, compacted)
        self.assertIn(b'-- @export real\n', compacted)
        self.assertEqual(compact_source.compact_source(compacted), compacted)

    def test_compaction_rejects_malformed_multiline_delimiters(self):
        for source in (b'"""inline', b'"""\nunfinished'):
            with self.subTest(source=source), self.assertRaisesRegex(
                    ValueError, "multiline string"):
                compact_source.compact_source(source)

    def test_compaction_preserves_byte_literal_and_import_closure(self):
        from selfhost_module_cache import quoted_import_targets

        literal = b'b"-- import \\"fake.ouro\\"; \\x00\\xFF"'
        source = (b'def bytes : List Nat :=  ' + literal + b'; -- trailing\n'
                  b'import "real.ouro";\n')
        compacted = compact_source.compact_source(source)
        self.assertIn(literal, compacted)
        self.assertEqual(quoted_import_targets(compacted.decode(), "compiler/probe.ouro"),
                         ["compiler/real.ouro"])
        self.assertEqual(compact_source.compact_source(compacted), compacted)

    def test_compaction_and_import_scan_preserve_scalar_literals_and_primes(self):
        from selfhost_module_cache import quoted_import_targets

        literals = [b"' '", b"'\\n'", b"'\\''", b"'\"'", b"'\\u{1F600}'",
                    "'é'".encode(), "'€'".encode(), "'😀'".encode()]
        source = (b"def name' : Nat := 1; def sample : Nat := f " + b" ".join(literals)
                  + b"; def primes : Nat := name'; import \"real.ouro\";\n")
        compacted = compact_source.compact_source(source)
        for literal in literals:
            self.assertIn(literal, compacted)
        self.assertIn(b"name'", compacted)
        self.assertEqual(quoted_import_targets(source.decode(), "compiler/probe.ouro"),
                         ["compiler/real.ouro"])
        self.assertEqual(quoted_import_targets(compacted.decode(), "compiler/probe.ouro"),
                         ["compiler/real.ouro"])
        self.assertEqual(compact_source.compact_source(compacted), compacted)

    def test_compaction_rejects_unclosed_raw_literal(self):
        with self.assertRaisesRegex(ValueError, "unterminated raw string"):
            compact_source.compact_source(b'def text : String := r#"unfinished";')

    def test_current_o_snapshot_is_independent_of_historical_projection(self):
        root = self.root / "repo"
        (root / "compiler/bootstrap").mkdir(parents=True)
        for name in (inputs.MANIFEST, inputs.ARCHIVE):
            shutil.copyfile(inputs.ROOT / name, root / name)
        names = {*bootstrap.HELPERS, "std/prelude.ouro"}
        for name in names:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('representation Nat := "ouro.nat";\n-- current ' + name + "\n")
        stage0 = {}
        for name in inputs.STAGE0:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixed historical stage0 fixture")
            stage0[name] = sha256_file(path)
        selected = {"sources": {name: sha256_file(root / name) for name in names}, "stage0": stage0,
            "archive_sha256": sha256_file(root / inputs.ARCHIVE), "manifest_sha256": sha256_file(root / inputs.MANIFEST)}
        cfg = build.ResolvedConfig({**build.DEFAULTS, "jobs": "auto"}, {})
        before = (root / "std/prelude.ouro").read_bytes()
        cases = (("original", "auto", 1, 1024, 1),
                 (compact_source.KIND, "auto", 20, 32768, 20),
                 ("original", 19, 20, 32768, 19),
                 ("original", 19, 20, 8192, 5),
                 ("original", "auto", 20, 8192, 5),
                 ("original", 19, 20, 1024, 1),
                 ("original", 19, 20, None, 19))
        for index, (form, requested, cpus, available, expected_workers) in enumerate(cases):
            with self.subTest(source_form=form, jobs=requested, available_mib=available):
                selected["source_form"] = form
                cfg.values["jobs"] = requested
                work = self.work / (form + "-" + str(index))
                work.mkdir()
                with patch.object(build.os, "cpu_count", return_value=cpus), \
                     patch("repo_support.available_memory_mb", return_value=available):
                    snapshot = bootstrap.freeze(root, work, selected, cfg)
                self.assertEqual(snapshot["config"]["jobs"], expected_workers)
                self.assertEqual(snapshot["requested_workers"], cpus if requested == "auto" else requested)
                self.assertEqual(json.loads((work / "inputs.json").read_text())["config"]["jobs"], expected_workers)
                self.assertEqual(cfg.values["jobs"], requested)
                self.assertEqual((work / "o/std/prelude.ouro").read_bytes(), before)
                self.assertEqual((root / "std/prelude.ouro").read_bytes(), before)
                self.assertNotEqual((work / "historical/bridge/std/prelude.ouro").read_bytes(), before)
                abi_helper = "scripts/native_tool_build.py"
                self.assertEqual((work / "o" / abi_helper).read_bytes(), (root / abi_helper).read_bytes())
                for role in ("historical/c0", "historical/bridge"):
                    self.assertFalse((work / role / abi_helper).exists())
                self.assertFalse((work / "o/compiler/stage0").exists())
                self.assertEqual(bootstrap.changed_inputs(work, snapshot), [])
                self.assertEqual(snapshot["roots"]["p1"], "o")
                if form == "original":
                    self.assertEqual(snapshot["roots"]["p2"], "o")
                    self.assertIsNone(snapshot["compaction"])
                else:
                    self.assertEqual(snapshot["roots"]["p2"], "compact")
                    compact = work / "compact/std/prelude.ouro"
                    self.assertEqual(compact.read_bytes(), compact_source.compact_source(before))
                    self.assertEqual(snapshot["compaction"]["files"]["std/prelude.ouro"]["compact_sha256"], sha256_file(compact))
                    self.assertEqual(snapshot["inputs"]["compact/std/prelude.ouro"], sha256_file(compact))
                    self.assertFalse((work / "compact/compiler/stage0").exists())
                    for name in bootstrap.HELPERS:
                        self.assertEqual((work / "compact" / name).read_bytes(), (root / name).read_bytes())

    def test_current_key_tracks_content_and_host_inputs_without_using_timestamps(self):
        root = self.root / "key-fixture"
        roots = [source for _tag, _module, source, _file in bootstrap.frontend.FRONTEND_TUS] + ["compiler/backend.ouro"]
        graph = {name: ([name] if name == "std/prelude.ouro" else ["std/prelude.ouro", name])
                 for name in [*roots, *bootstrap.ACCEPTANCE_ROOTS]}
        names = {*bootstrap.HELPERS, *bootstrap.RUNTIME, *inputs.STAGE0, inputs.MANIFEST, inputs.ARCHIVE,
                 "runtime/host-key-extra.h", *(name for units in graph.values() for name in units)}
        for name in names:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("owned key fixture " + name, encoding="utf-8")
        for name in graph:
            if name != "std/prelude.ouro":
                path = root / name
                spelling = Path(os.path.relpath(root / "std/prelude.ouro", path.parent)).as_posix()
                path.write_bytes(f'-- key fixture\rimport "{spelling}";\r\n'.encode())
        compiler = self.root / "selected-host-cc"
        compiler.write_bytes(b"fixed host C compiler")
        cfg = build.ResolvedConfig(dict(build.DEFAULTS), {})
        with patch.object(build, "locate_cc", return_value=(str(compiler), None)), \
             patch.object(build, "compiler_id", return_value="fixed fixture version"):
            with patch.object(Path, "open", autospec=True, side_effect=Path.open) as reads:
                selected = bootstrap.current_inputs(root, cfg, build)
            self.assertEqual(selected["unit_graph"], graph)
            paths = {root / name for name in graph}
            self.assertCountEqual([call.args[0] for call in reads.call_args_list if call.args[0] in paths],
                                  paths)
            self.assertEqual(selected["sources"]["std/data.ouro"], sha256_file(root / "std/data.ouro"))
            key = hash_json(selected)
            compact = bootstrap.current_inputs(root, cfg, build, compact_sources=True)
            self.assertNotEqual(hash_json(compact), key)
            for name in ("std/prelude.ouro", "std/data.ouro", "runtime/host-key-extra.h", "scripts/bootstrap_compiler.py",
                         "scripts/compact_source.py", "scripts/native_tool_build.py",
                         inputs.STAGE0[0], inputs.MANIFEST, inputs.ARCHIVE):
                with self.subTest(input=name):
                    path = root / name
                    original, timestamp = path.read_bytes(), path.stat()
                    path.write_bytes(original + b" changed without a new timestamp")
                    os.utime(path, ns=(timestamp.st_atime_ns, timestamp.st_mtime_ns))
                    self.assertFalse(bootstrap.current_unchanged(root, selected))
                    self.assertNotEqual(hash_json(bootstrap.current_inputs(root, cfg, build)), key)
                    path.write_bytes(original)
                    self.assertEqual(hash_json(bootstrap.current_inputs(root, cfg, build)), key)
            with patch.dict(os.environ):
                os.environ.pop("CPATH", None)
                absent = bootstrap.current_inputs(root, cfg, build)
                self.assertNotIn("CPATH", absent["environment"])
                os.environ["CPATH"] = ""
                empty = bootstrap.current_inputs(root, cfg, build)
                self.assertEqual(empty["environment"]["CPATH"], "")
                self.assertNotEqual(hash_json(absent), hash_json(empty))
                self.assertNotEqual(bootstrap.historical_key(absent, 1), bootstrap.historical_key(empty, 1))
                with self.assertRaisesRegex(RuntimeError, "selected C toolchain environment changed before publication"):
                    bootstrap.verify_current_inputs(root, absent)
                os.environ["CPATH"] = "bootstrap fixture include environment"
                self.assertNotEqual(hash_json(bootstrap.current_inputs(root, cfg, build)), hash_json(empty))
            compiler.write_bytes(b"changed compiler with identical version output")
            self.assertNotEqual(hash_json(bootstrap.current_inputs(root, cfg, build)), key)

    def test_compact_stage_checks_both_forms_before_emitting_from_compact_sources(self):
        snapshot = self.fixture(compact_sources=True)
        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            report = bootstrap.chain(self.work, snapshot, build)
        expected = set(snapshot["selected"]["roots"]) | set(bootstrap.ACCEPTANCE_ROOTS)
        for form in ("o", "compact"):
            checked = {argv[2] for argv, root in self.events if len(argv) > 2 and argv[1] == "check"
                       and argv[0] == str(self.work / "out/p1/ouro1") and root == self.work / form}
            self.assertEqual(checked, expected)
        emitted = [(argv, root) for argv, root in self.events if "worker" in argv and "p2" in argv
                   and any(action in argv for action in ("frontend", "abi-build", "link"))]
        self.assertEqual(len(emitted), 3)
        self.assertTrue(all(root == self.work / "compact" for _argv, root in emitted))
        self.assertTrue(report["phases"][-1]["all_compact_roots_strictly_checked_before_use"])
        self.assertEqual(set(report["complete_generated_c_comparison"]), {"driver_u.c", "backend_u.c"})
        self.assertTrue(report["pass"])

    def test_compact_source_rejection_stops_before_p2_emission(self):
        snapshot = self.fixture(compact_sources=True)
        self.rejected_root = snapshot["selected"]["roots"][-1]
        self.rejected_source_form = "compact"
        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            with self.assertRaisesRegex(RuntimeError, "p2/check-compact-14"):
                bootstrap.chain(self.work, snapshot, build)
        self.assertTrue((self.work / "out/p1/driver_u.c").exists())
        self.assertFalse((self.work / "out/p2/driver_u.c").exists())

    def test_compact_generated_c_mismatch_rejects_successor(self):
        snapshot = self.fixture(compact_sources=True)
        self.different_c = True
        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            with self.assertRaisesRegex(RuntimeError, "complete generated frontend/backend C differs"):
                bootstrap.chain(self.work, snapshot, build)
        self.assertFalse(json.loads((self.work / "report.json").read_text())["pass"])

    def test_equal_generated_c_replacement_rejects_successor(self):
        snapshot = self.fixture()
        compare_generated = bootstrap.compare_generated

        def compare_replacement(first, second):
            for directory in (first, second):
                (directory / "driver_u.c").write_bytes(b"replacement generated frontend\n")
            return compare_generated(first, second)

        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run), \
             patch.object(bootstrap, "compare_generated", side_effect=compare_replacement):
            with self.assertRaisesRegex(RuntimeError, r"complete generated C changed after p1: driver_u\.c"):
                bootstrap.chain(self.work, snapshot, build)
        self.assertFalse(json.loads((self.work / "report.json").read_text())["pass"])
        self.assertFalse(any("bootstrap-good.ouro" in argv or "bootstrap-bad.ouro" in argv
                             for argv, _root in self.events))

    def test_compact_input_tampering_stops_before_any_subprocess(self):
        snapshot = self.fixture(compact_sources=True)
        (self.work / "compact/compiler/backend.ouro").write_text("changed after freeze")
        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            with self.assertRaisesRegex(RuntimeError, "frozen bootstrap inputs changed"):
                bootstrap.chain(self.work, snapshot, build)
        self.assertEqual(self.events, [])

    def test_build_flag_selects_compact_bootstrap(self):
        with patch.object(bootstrap, "ensure_current_compiler") as ensure, patch.object(build, "trim_cache"):
            build.main(["build", "--compact-sources", "--verbosity", "quiet"])
        self.assertEqual(ensure.call_args.kwargs, {"compact_sources": True})

    def test_last_current_root_rejection_stops_before_p1_emission(self):
        snapshot = self.fixture()
        self.rejected_root = snapshot["selected"]["roots"][-1]
        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            with self.assertRaisesRegex(RuntimeError, "p1/check-14"):
                bootstrap.chain(self.work, snapshot, build)
        p1_frontend = [argv for argv, _root in self.events if "worker" in argv and "p1" in argv and "frontend" in argv]
        self.assertEqual(p1_frontend, [])
        self.assertFalse((self.work / "out/p1/driver_u.c").exists())
        self.assertFalse(json.loads((self.work / "report.json").read_text())["pass"])

    def test_behavior_probes_use_the_complete_frozen_data_closure(self):
        snapshot = self.fixture()
        units = ["std/types.ouro", "std/prelude.ouro", "std/data.ouro"]
        snapshot["selected"]["unit_graph"]["std/data.ouro"] = units
        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            bootstrap.chain(self.work, snapshot, build)
        probes = [argv for argv, _root in self.events
                  if len(argv) > 2 and argv[1] == "check" and argv[2].startswith("bootstrap-")]
        self.assertEqual(len(probes), 2)
        for argv in probes:
            self.assertEqual(argv[4:], [part for unit in [*units, argv[2]] for part in ("--unit", unit)])

    def test_behavior_probes_reject_changes_to_the_current_compiler(self):
        for variant in ("good", "bad"):
            with self.subTest(variant=variant):
                self.work = self.root / ("changed-after-" + variant)
                self.work.mkdir()
                self.events = []
                snapshot = self.fixture()

                def run_then_change_compiler(argv, *, source=f"bootstrap-{variant}.ouro", **options):
                    result = self.fake_run(argv, **options)
                    if argv[1:3] == ["check", source]:
                        binary = Path(argv[0])
                        binary.write_bytes(binary.read_bytes() + b"changed after probe\n")
                    return result

                with patch.object(bootstrap, "run_limited", side_effect=run_then_change_compiler):
                    with self.assertRaisesRegex(RuntimeError, f"current P2 compiler changed after behavior-{variant}"):
                        bootstrap.chain(self.work, snapshot, build)
                report = json.loads((self.work / "report.json").read_text())
                self.assertFalse(report["pass"])
                self.assertNotIn("binary_sha256", report)
                self.assertEqual(report["phases"][-1]["commands"][-1]["label"], f"behavior-{variant}")

    def test_negative_behavior_requires_exact_current_rejection_and_successful_execution(self):
        expected = self.bad_stderr
        protocols = {
            "old-index": ("", expected.replace("det=82", "det=78"), 1, "ok"),
            "maybe-only-index": ("", expected.replace("det=82", "det=80"), 1, "ok"),
            "wrong-index": ("", expected.replace("det=82", "det=83"), 1, "ok"),
            "wrong-declaration": ("", expected.replace("exact_index", "other_index"), 1, "ok"),
            "wrong-code": ("", expected.replace("code=41", "code=40"), 1, "ok"),
            "missing-line": ("", "".join(expected.splitlines(keepends=True)[1:]), 1, "ok"),
            "extra-line": ("", expected + "unexpected diagnostic\n", 1, "ok"),
            "stdout": ("CHECK_FAIL\n", expected, 1, "ok"),
            "accepted": ("", expected, 0, "ok"),
            "other-exit": ("", expected, 2, "ok"),
            "timeout": ("", expected, 1, "timeout"),
        }
        for name, protocol in protocols.items():
            with self.subTest(protocol=name):
                self.work = self.root / ("negative-" + name)
                self.work.mkdir()
                self.bad_stdout, self.bad_stderr, self.bad_returncode, self.bad_status = protocol
                snapshot = self.fixture()
                with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
                    with self.assertRaises(RuntimeError):
                        bootstrap.chain(self.work, snapshot, build)
                report = json.loads((self.work / "report.json").read_text())
                self.assertFalse(report["pass"])
                self.assertEqual(report["phases"][-1]["commands"][-1]["label"], "behavior-bad")

    def test_complete_frontend_mismatch_rejects_successor(self):
        snapshot = self.fixture()
        self.different_c = True
        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            with self.assertRaisesRegex(RuntimeError, "complete generated frontend/backend C differs"):
                bootstrap.chain(self.work, snapshot, build)
        self.assertTrue((self.work / "out/p1/driver_u.c").exists())
        self.assertTrue((self.work / "out/p2/driver_u.c").exists())
        self.assertFalse(json.loads((self.work / "report.json").read_text())["pass"])

    def test_abi_protocol_rejects_missing_extra_duplicate_and_reordered_laws(self):
        lines = bootstrap.ABI_STDOUT.splitlines(keepends=True)
        protocols = {
            "marker-only": lines[-1],
            "missing": "".join(lines[1:]),
            "extra": "".join([*lines[:-1], "PASS unexpected law\n", lines[-1]]),
            "duplicate": "".join([lines[0], *lines]),
            "reordered": "".join([lines[1], lines[0], *lines[2:]]),
        }
        for name, stdout in protocols.items():
            with self.subTest(protocol=name):
                self.work = self.root / ("abi-" + name)
                self.work.mkdir()
                self.abi_stdout = stdout
                snapshot = self.fixture()
                with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
                    with self.assertRaisesRegex(RuntimeError, "ABI laws did not return the exact expected protocol"):
                        bootstrap.chain(self.work, snapshot, build)
                self.assertFalse((self.work / "out/p2/driver_u.c").exists())
                self.assertFalse(json.loads((self.work / "report.json").read_text())["pass"])

    def test_frozen_input_change_stops_before_any_subprocess(self):
        snapshot = self.fixture()
        (self.work / "o/compiler/backend.ouro").write_text("changed after freeze")
        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            with self.assertRaisesRegex(RuntimeError, "frozen bootstrap inputs changed"):
                bootstrap.chain(self.work, snapshot, build)
        self.assertEqual(self.events, [])

    def test_changed_c_environment_stops_the_next_subprocess(self):
        with patch.dict(os.environ):
            os.environ.pop("CPATH", None)
            snapshot = self.fixture()

            def run_then_change_environment(argv, **options):
                self.assertNotIn("CPATH", options["env"])
                result = self.fake_run(argv, **options)
                os.environ["CPATH"] = ""
                return result

            with (patch.object(bootstrap, "clean_env", return_value={"CPATH": "ambient include environment"}),
                  patch.object(bootstrap, "run_limited", side_effect=run_then_change_environment)):
                with self.assertRaisesRegex(RuntimeError, "selected C toolchain environment changed before frontend"):
                    bootstrap.chain(self.work, snapshot, build)
        self.assertEqual(len(self.events), 1)

    def test_unavailable_native_stack_reserve_stops_before_any_subprocess(self):
        snapshot = self.fixture()
        with patch.object(bootstrap, "configure_native_stack", side_effect=OSError("native stack reserve unavailable")), \
             patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            with self.assertRaisesRegex(OSError, "native stack reserve unavailable"):
                bootstrap.chain(self.work, snapshot, build)
        self.assertEqual(self.events, [])
        self.assertFalse(json.loads((self.work / "report.json").read_text())["pass"])

    def test_failed_chain_preserves_installed_compiler(self):
        output = self.root / "installed/ouro1"
        output.parent.mkdir()
        output.write_bytes(b"existing compiler must survive failed bootstrap")
        cfg = build.ResolvedConfig({**build.DEFAULTS, "build_dir": str(self.root / "b"),
                                   "c_build_dir": str(output.parent), "cache_enabled": False}, {})
        before = output.read_bytes()
        with patch.object(inputs, "read_bundle", return_value=({}, {})), \
             patch.object(inputs, "verify_stage0"), \
             patch.object(bootstrap, "current_inputs", return_value={"owned": "current inputs"}), \
             patch.object(bootstrap, "freeze", return_value={}), \
             patch.object(bootstrap, "chain", side_effect=RuntimeError("strict source rejected")):
            with self.assertRaisesRegex(RuntimeError, "strict source rejected"):
                bootstrap.ensure_current_compiler(cfg, build, self.root)
        self.assertEqual(output.read_bytes(), before)
        self.assertFalse(output.with_name("ouro1.bootstrap.json").exists())

    def test_changed_report_before_publication_preserves_installed_compiler(self):
        output = self.root / "installed/ouro1"
        output.parent.mkdir()
        receipt = output.with_name("ouro1.bootstrap.json")
        output.write_bytes(b"existing compiler")
        receipt.write_bytes(b"existing compiler receipt")
        cfg = build.ResolvedConfig({**build.DEFAULTS, "build_dir": str(self.root / "b"),
                                   "c_build_dir": str(output.parent), "cache_enabled": False}, {})
        selected = {"owned": "current inputs"}

        def chain_with_stale_report(work, _snapshot, _build, **_options):
            binary = work / "out/p2/ouro1"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"successor compiler")
            report = {"binary": "out/p2/ouro1", "binary_sha256": sha256_file(binary), "pass": True}
            write_json_atomic(work / "report.json", {**report, "pass": 1})
            return report

        with (patch.object(bootstrap, "freeze", return_value={}),
              patch.object(bootstrap, "chain", side_effect=chain_with_stale_report),
              patch.object(bootstrap, "verify_current_inputs")):
            with self.assertRaisesRegex(RuntimeError, "current bootstrap report changed before publication"):
                bootstrap.build_current_compiler(cfg, build, self.root, selected,
                                                 historical_cache=None, historical_sha256=None)
        self.assertEqual(output.read_bytes(), b"existing compiler")
        self.assertEqual(receipt.read_bytes(), b"existing compiler receipt")
        self.assertEqual(set(output.parent.iterdir()), {output, receipt})

    def test_cache_rejects_changed_binary_foreign_producer_and_partial_c_comparison(self):
        snapshot = self.fixture()
        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            report = bootstrap.chain(self.work, snapshot, build)
        output = self.root / "installed-compiler"
        shutil.copyfile(self.work / report["binary"], output)
        receipt = self.root / "receipt.json"
        data = {"kind": bootstrap.KIND, "key": snapshot["key"], "selected": snapshot["selected"],
                "work": str(self.work), "binary_sha256": sha256_file(output), "report_sha256": sha256_file(self.work / "report.json")}
        write_json_atomic(receipt, data)
        self.assertTrue(bootstrap.installed_current(output, receipt, snapshot["selected"]))
        valid_binary = output.read_bytes()
        output.write_bytes(b"foreign compiler" * 400)
        forged = {**data, "binary_sha256": sha256_file(output)}
        write_json_atomic(receipt, forged)
        self.assertFalse(bootstrap.installed_current(output, receipt, snapshot["selected"]))
        output.write_bytes(valid_binary)
        partial = copy.deepcopy(report)
        del partial["complete_generated_c_comparison"]["backend_u.c"]
        write_json_atomic(self.work / "report.json", partial)
        write_json_atomic(receipt, {**data, "report_sha256": sha256_file(self.work / "report.json")})
        self.assertFalse(bootstrap.installed_current(output, receipt, snapshot["selected"]))

    def test_cache_requires_boolean_true_report_pass(self):
        output, selected, _archive = self.compiler_artifact_fixture()
        receipt = output.with_name("ouro1.bootstrap.json")
        data = json.loads(receipt.read_text(encoding="utf-8"))
        report_path = Path(data["work"]) / "report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertTrue(bootstrap.installed_current(output, receipt, selected))
        for name, fields in (
                ("true", {"pass": True}), ("false", {"pass": False}),
                ("zero", {"pass": 0}), ("one", {"pass": 1}),
                ("string", {"pass": "false"}), ("list", {"pass": [False]}),
                ("object", {"pass": {"pass": False}}), ("null", {"pass": None}),
                ("missing", {})):
            with self.subTest(pass_field=name):
                changed_report = copy.deepcopy(report)
                changed_report.pop("pass")
                changed_report.update(fields)
                write_json_atomic(report_path, changed_report)
                write_json_atomic(receipt, {**data, "report_sha256": sha256_file(report_path)})
                self.assertEqual(bootstrap.installed_current(output, receipt, selected),
                                 fields.get("pass") is True)

    def test_installed_cache_hit_reuses_checked_digest_and_reads_all_evidence(self):
        output, selected, _archive = self.compiler_artifact_fixture()
        receipt = json.loads(output.with_name("ouro1.bootstrap.json").read_bytes())
        work = Path(receipt["work"])
        checked = [work / "report.json", output, work / "inputs.json"]
        checked.extend(work / "out" / phase / name for name in ("backend_u.c", "driver_u.c")
                       for phase in ("p1", "p2"))
        cfg = build.ResolvedConfig({**build.DEFAULTS, "build_dir": str(output.parent.parent),
                                   "c_build_dir": str(output.parent), "cache_enabled": True}, {})

        with (patch.object(inputs, "read_bundle", return_value=({}, {})),
              patch.object(inputs, "verify_stage0"),
              patch.object(bootstrap, "current_inputs", return_value=selected),
              patch.object(bootstrap, "local_bootstrap_cache", return_value=None),
              patch.object(bootstrap, "build_current_compiler", side_effect=RuntimeError("fixture requires rebuild")) as rebuild,
              patch.object(Path, "open", autospec=True, side_effect=Path.open) as reads):
            result = bootstrap.ensure_current_compiler(cfg, build, self.root)
            self.assertEqual(result, {"cache": "hit", "binary": str(output),
                                      "binary_sha256": receipt["binary_sha256"]})
            self.assertEqual([call.args[0] for call in reads.call_args_list if call.args[0] in checked], checked)
            rebuild.assert_not_called()
            report = work / "report.json"
            original = report.read_bytes()
            report.write_bytes(original.replace(b"\n", b"\r", 1))
            self.assertEqual(json.loads(report.read_bytes()), json.loads(original))
            with self.assertRaisesRegex(RuntimeError, "fixture requires rebuild"):
                bootstrap.ensure_current_compiler(cfg, build, self.root)
            rebuild.assert_called_once()
            report.write_bytes(original)
            rebuild.reset_mock()
            evidence = work / "out/p2/backend_u.c"
            saved = evidence.stat()
            data = evidence.read_bytes()
            evidence.write_bytes(bytes([data[0] ^ 1]) + data[1:])
            os.utime(evidence, ns=(saved.st_atime_ns, saved.st_mtime_ns))
            with self.assertRaisesRegex(RuntimeError, "fixture requires rebuild"):
                bootstrap.ensure_current_compiler(cfg, build, self.root)
            rebuild.assert_called_once()

    def test_frontend_flag_is_rejected_without_touching_stage0_or_entering_build(self):
        before = {name: (build.ROOT / name).read_bytes() for name in inputs.STAGE0}
        with patch.object(build, "run_build", side_effect=AssertionError("build entered before argument rejection")):
            for operation in ("build", "rebuild"):
                with self.subTest(operation=operation), self.assertRaises(SystemExit) as error:
                    build.main([operation, "--frontend"])
                self.assertEqual(error.exception.code, 2)
        self.assertEqual({name: (build.ROOT / name).read_bytes() for name in inputs.STAGE0}, before)

    def compiler_artifact_fixture(self):
        self.work = self.root / "_build/bootstrap/artifact-contract"
        self.work.mkdir(parents=True)
        snapshot = self.fixture()
        with patch.object(bootstrap, "run_limited", side_effect=self.fake_run):
            report = bootstrap.chain(self.work, snapshot, build)
        output = self.root / "_build/c/ouro1"
        output.parent.mkdir(parents=True)
        shutil.copyfile(self.work / report["binary"], output)
        output.chmod(0o755)
        receipt = {"kind": bootstrap.KIND, "key": snapshot["key"], "selected": snapshot["selected"],
                   "work": str(self.work), "binary_sha256": sha256_file(output), "report_sha256": sha256_file(self.work / "report.json")}
        write_json_atomic(output.with_name("ouro1.bootstrap.json"), receipt)
        archive = self.root / "compiler.tar.gz"
        ci_gate.export_compiler(self.root, output, snapshot["selected"], archive)
        return output, snapshot["selected"], archive

    def test_compiler_artifact_key_and_export_use_memory_limited_workers(self):
        snapshot = self.historical_fixture("hosted-cache-key")
        selected = snapshot["selected"]
        cfg = build.ResolvedConfig({**snapshot["config"], "jobs": 2}, {})
        archive = self.root / "host-compiler.tar.gz"
        archive.write_bytes(b"compiler archive fixture")
        digest = "a" * 64
        for budget, workers in ((bootstrap.MEMORY_MIB, 1), (bootstrap.MEMORY_MIB + bootstrap.WORKER_MEMORY_MIB, 2)):
            historical_key = bootstrap.historical_key(selected, workers)
            with (self.subTest(budget=budget), patch.dict(os.environ, {MEMORY_ENV: str(budget)}),
                  patch.object(build, "load_config", return_value=cfg),
                  patch.object(bootstrap, "current_inputs", return_value=selected),
                  patch.object(ci_gate, "export_compiler", return_value=digest) as export,
                  patch("sys.stdout", new_callable=io.StringIO) as output):
                self.assertEqual(ci_gate.main(["--compiler-artifact", "key"]), 0)
                self.assertEqual(ci_gate.main(["--compiler-artifact", "export", "--artifact", str(archive)]), 0)
                self.assertEqual(output.getvalue().splitlines(), [
                    "key=" + hash_json(selected),
                    "historical_key=" + historical_key,
                    "sha256=" + sha256_file(archive),
                    "historical_sha256=" + digest,
                ])
                export.assert_called_once_with(ci_gate.ROOT, cfg.path("c_build_dir") / "ouro1", selected, archive,
                                               historical_key=historical_key)

    def test_historical_cache_transport_has_one_protected_writer(self):
        directory = ci_gate.ROOT / ".github/workflows"
        path = "path: ${{ runner.temp }}/bootstrap-historical/${{ steps.inputs.outputs.historical_key }}.zip"
        prefix = "ouro-bootstrap-historical-v1-${{ runner.os }}-${{ runner.arch }}-${{ steps.inputs.outputs.historical_key }}-"
        key = "key: " + prefix + "${{ github.run_id }}-${{ github.run_attempt }}"
        public = "github.event.repository.visibility == 'public'"
        miss = "steps.compiler-cache.outputs.cache-hit != 'true'"
        matched = "steps.historical-cache.outputs.cache-matched-key != ''"
        restored = "steps.historical-cache.outcome == 'success'"
        protected = "github.event_name == 'push' && (github.ref == 'refs/heads/main' || github.ref == 'refs/heads/master')"
        for workflow, job, restore_condition, verify_condition, count in (
            ("ouro-pr", "host-compiler", miss, restored + " && " + matched, 2),
            ("dependency-review", "dependency-review", "steps.changes.outputs.dependency != 'false' && " + miss, matched, 1),
        ):
            content = (directory / (workflow + ".yml")).read_text(encoding="utf-8")
            steps = ci_gate.workflow_job(content, job).split("      - name: ")
            historical = [step for step in steps if "bootstrap-historical" in step and "uses: actions/cache/" in step]
            with self.subTest(workflow=workflow):
                self.assertEqual(len(historical), count)
                restore = historical[0]
                self.assertIn("uses: actions/cache/restore@", restore)
                restore_if = "if: ${{ " + public + " && " + restore_condition + " }}"
                self.assertTrue({path, key, restore_if} <= {line.strip() for line in restore.splitlines()})
                self.assertEqual(restore.split("restore-keys: |", 1)[1].strip(), prefix)
                verify = next(step for step in steps if "scripts/ci_historical_cache.py verify" in step)
                build_step = next(step for step in steps if "scripts/ouro_build.py build" in step)
                self.assertIn("if: ${{ " + verify_condition + " }}", {line.strip() for line in verify.splitlines()})
                self.assertIn("OURO_BOOTSTRAP_HISTORY_SHA256: ${{ steps.historical-origin.outputs.verified_sha256 }}", build_step)
                self.assertLess(steps.index(restore), steps.index(verify))
                self.assertLess(steps.index(verify), steps.index(build_step))
                if count == 2:
                    save = historical[1]
                    self.assertIn("uses: actions/cache/save@", save)
                    self.assertIn(path, save)
                    self.assertIn("key: ${{ steps.historical-cache.outputs.cache-primary-key }}", save)
                    attest = next(step for step in steps if "scripts/ci_historical_cache.py attest" in step)
                    publish = next(step for step in steps if "bootstrap-historical/attestation.txt" in step)
                    self.assertIn("if: ${{ " + protected + " && github.run_attempt == '1' && " + restored + " }}", attest)
                    self.assertIn("BUILT_HISTORICAL_SHA256: ${{ steps.bundle.outputs.historical_sha256 }}", attest)
                    publish_if = "if: ${{ " + protected + " && steps.historical-evidence.outputs.name != ''"
                    self.assertIn(publish_if + " && steps.historical-evidence.outputs.sha256 != "
                                  "steps.historical-origin.outputs.verified_sha256 }}", save)
                    self.assertIn(publish_if + " }}", publish)
                    self.assertIn("name: ${{ steps.historical-evidence.outputs.name }}", publish)
                    export = next(index for index, step in enumerate(steps) if "--compiler-artifact export" in step)
                    self.assertLess(export, steps.index(attest))
                    self.assertLess(steps.index(attest), steps.index(publish))

    def test_pr_verified_caches_save_after_their_gates(self):
        workflow = (ci_gate.ROOT / ".github/workflows/ouro-pr.yml").read_text(encoding="utf-8")
        for job, gate, save in (
            ("host-compiler", "Export compiler with bootstrap evidence", "Save compiler and bootstrap evidence"),
            ("quick-firewall", "Run checks", "Save cache"),
            ("kernel-validation", "Run additional compiler checks", "Save cache"),
            ("portable-kernel-smoke", "Run checks", "Save portable cache and bootstrap evidence"),
        ):
            with self.subTest(job=job):
                section = ci_gate.workflow_job(workflow, job)
                self.assertLess(section.index(f"- name: {gate}\n"), section.index(f"- name: {save}\n"))
                step = section.split(f"- name: {save}\n", 1)[1].split("\n      - name: ", 1)[0]
                self.assertIn("github.event_name == 'pull_request'", step)
                self.assertIn("uses: actions/cache/save@", step)
                self.assertIn("outputs.cache-hit != 'true'", step)
                self.assertNotIn("always()", step)

    def test_compiler_export_pins_history_only_from_the_checked_report(self):
        output, selected, archive = self.compiler_artifact_fixture()
        receipt_path = output.with_name("ouro1.bootstrap.json")
        receipt = json.loads(receipt_path.read_bytes())
        report_path = Path(receipt["work"]) / "report.json"
        report = json.loads(report_path.read_bytes())
        key, digest = "a" * 64, "b" * 64
        for history, expected in (
            (None, ""), ({"error": "unavailable"}, ""), ({"key": "c" * 64, "sha256": digest}, ""),
            ({"key": key, "sha256": "invalid"}, ""), ({"key": key, "sha256": digest}, digest),
        ):
            with self.subTest(history=history):
                report["historical_cache"] = history
                write_json_atomic(report_path, report)
                receipt["report_sha256"] = sha256_file(report_path)
                write_json_atomic(receipt_path, receipt)
                self.assertEqual(ci_gate.export_compiler(self.root, output, selected, archive, historical_key=key), expected)
        report["historical_cache"]["sha256"] = "c" * 64
        write_json_atomic(report_path, report)
        with self.assertRaisesRegex(ValueError, "does not match"):
            ci_gate.export_compiler(self.root, output, selected, archive, historical_key=key)

    def test_compiler_artifact_roundtrip_preserves_complete_verification(self):
        output, selected, archive = self.compiler_artifact_fixture()
        with tarfile.open(archive) as bundle:
            paths = [self.root / member.name for member in bundle.getmembers()]
        self.assertEqual(len(paths), 8)
        before = {path: path.read_bytes() for path in paths}
        for path in paths:
            path.unlink()
        ci_gate.import_compiler(self.root, output, selected, archive, sha256_file(archive))
        self.assertEqual({path: path.read_bytes() for path in paths}, before)
        self.assertTrue(bootstrap.installed_current(output, output.with_name("ouro1.bootstrap.json"), selected))
        if os.name != "nt":
            self.assertEqual(output.stat().st_mode & 0o777, 0o755)
        for path in paths:
            with self.subTest(missing=path):
                path.unlink()
                with self.assertRaisesRegex(ValueError, "does not match"):
                    ci_gate.export_compiler(self.root, output, selected, self.root / "invalid.tar.gz")
                path.write_bytes(before[path])

    def test_compiler_artifact_import_reads_the_verified_snapshot(self):
        output, selected, archive = self.compiler_artifact_fixture()
        archive_data = archive.read_bytes()
        digest = sha256_file(archive)
        receipt = output.with_name("ouro1.bootstrap.json")
        receipt_name = receipt.relative_to(self.root).as_posix()
        payloads = {path: path.read_bytes() for path in (output, receipt)}
        open_archive, extract_member = tarfile.open, tarfile.TarFile.extractfile
        replacement = archive.with_suffix(".replacement")
        replacement_data = b"archive replaced after verification"

        def replace_archive(*args, **kwargs):
            if replacement.is_file():
                replacement.replace(archive)
            return open_archive(*args, **kwargs)

        capture_limit = len(payloads[receipt])
        receipt_modes = ((capture_limit, False, [True]), (0, False, [False, True]),
                         (capture_limit, True, [True, False, True]))
        spool_modes = ((len(archive_data), 0), (1, 1))
        rollover = tempfile.SpooledTemporaryFile.rollover
        for spool_mode, receipt_mode in itertools.product(spool_modes, receipt_modes):
            spool_limit, expected_rollovers = spool_mode
            receipt_limit, fail_capture, expected_reads = receipt_mode
            with self.subTest(spool_limit=spool_limit, receipt_limit=receipt_limit, fail_capture=fail_capture):
                receipt_reads = []

                def count_receipt_read(bundle, member, receipt_reads=receipt_reads, fail_capture=fail_capture):
                    if member.name == receipt_name:
                        receipt_reads.append(bundle.fileobj.tell() <= member.offset_data)
                        if fail_capture and len(receipt_reads) == 1:
                            raise OSError("fixture receipt capture failed")
                    return extract_member(bundle, member)

                archive.write_bytes(archive_data)
                replacement.write_bytes(replacement_data)
                for path in payloads:
                    path.unlink()
                with (patch.object(ci_gate, "_COMPILER_ARCHIVE_SPOOL_LIMIT", spool_limit),
                      patch.object(ci_gate, "_COMPILER_RECEIPT_CAPTURE_LIMIT", receipt_limit),
                      patch.object(tempfile.SpooledTemporaryFile, "rollover", autospec=True, side_effect=rollover) as roll,
                      patch.object(tarfile, "open", side_effect=replace_archive),
                      patch.object(tarfile.TarFile, "extractfile", count_receipt_read)):
                    ci_gate.import_compiler(self.root, output, selected, archive, digest)
                self.assertEqual(roll.call_count, expected_rollovers)
                self.assertEqual(receipt_reads, expected_reads)
                self.assertEqual(archive.read_bytes(), replacement_data)
                self.assertEqual({path: path.read_bytes() for path in payloads}, payloads)

    def test_compiler_artifact_checks_last_duplicate_receipt_before_inventory(self):
        output, selected, archive = self.compiler_artifact_fixture()
        receipt_name = output.with_name("ouro1.bootstrap.json").relative_to(self.root).as_posix()
        with tarfile.open(archive) as bundle:
            members = [(member, bundle.extractfile(member).read()) for member in bundle.getmembers()]
        receipt = next(member for member, _ in members if member.name == receipt_name)
        invalid_data = b"invalid JSON"
        invalid = copy.copy(receipt)
        invalid.size = len(invalid_data)
        link = copy.copy(receipt)
        link.type, link.size, link.linkname = tarfile.SYMTYPE, 0, "ouro1"
        stale = b"previous compiler"
        output.write_bytes(stale)
        for changed, error in (([(invalid, invalid_data), *members], "missing, duplicate or unexpected files"),
                               ([*members, (invalid, invalid_data)], "Expecting value"),
                               ([*members, (link, b"")], "receipt is not a regular file")):
            with self.subTest(error=error):
                with tarfile.open(archive, "w:gz") as bundle:
                    for member, data in changed:
                        bundle.addfile(member, io.BytesIO(data))
                with self.assertRaisesRegex(ValueError, error):
                    ci_gate.import_compiler(self.root, output, selected, archive, sha256_file(archive))
                self.assertEqual(output.read_bytes(), stale)

    def test_compiler_artifact_rejects_wrong_digest_inputs_and_binary(self):
        output, selected, archive = self.compiler_artifact_fixture()
        before = output.read_bytes()
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            ci_gate.import_compiler(self.root, output, selected, archive, "0" * 64)
        self.assertEqual(output.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, "does not match"):
            ci_gate.import_compiler(self.root, output, {**selected, "changed": True}, archive, sha256_file(archive))
        output.write_bytes(b"foreign binary" * 400)
        with self.assertRaisesRegex(ValueError, "does not match"):
            ci_gate.export_compiler(self.root, output, selected, self.root / "invalid.tar.gz")

    def test_compiler_artifact_rejects_missing_extra_duplicate_links_and_corruption(self):
        output, selected, archive = self.compiler_artifact_fixture()
        with tarfile.open(archive) as bundle:
            members = [(member, bundle.extractfile(member).read()) for member in bundle.getmembers()]
        for mutation in ("missing", "extra", "duplicate", "link", "binary", "outside"):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(members)
                if mutation == "missing":
                    changed.pop()
                elif mutation == "extra":
                    changed.append((tarfile.TarInfo("../outside"), b""))
                elif mutation == "duplicate":
                    changed.append(changed[0])
                elif mutation == "link":
                    changed[0][0].type = tarfile.SYMTYPE
                    changed[0][0].linkname = "../outside"
                    changed[0][0].size = 0
                    changed[0] = (changed[0][0], b"")
                elif mutation == "binary":
                    member, data = changed[0]
                    changed[0] = (member, b"x" * len(data))
                else:
                    member, data = changed[1]
                    receipt = json.loads(data)
                    receipt["work"] = str(self.root.parent / "outside")
                    data = json.dumps(receipt).encode()
                    member.size = len(data)
                    changed[1] = (member, data)
                invalid = self.root / "invalid.tar.gz"
                with tarfile.open(invalid, "w:gz") as bundle:
                    for member, data in changed:
                        bundle.addfile(member, io.BytesIO(data))
                with self.assertRaises(ValueError):
                    ci_gate.import_compiler(self.root, output, selected, invalid, sha256_file(invalid))

    def drift_fixture(self):
        output, selected, _archive = self.compiler_artifact_fixture()
        cfg = build.ResolvedConfig({**build.DEFAULTS, "build_dir": str(self.root / "_build"),
                                   "c_build_dir": str(output.parent)}, {})
        return output, selected, cfg

    def test_stage_loop_reuses_the_checkout_build_module(self):
        import stage_loop

        self.assertIs(stage_loop.OB, build)

    def test_generated_drift_uses_verified_current_pair_and_preserves_historical_seed(self):
        output, selected, cfg = self.drift_fixture()
        references = {name: self.work / "out/p2" / name for name in ("driver_u.c", "backend_u.c")}
        stage0 = tuple(self.root / "compiler/stage0" / name for name in references)
        for path in stage0:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"/* Do not hand-edit; ouro_export_count: historical pinned seed */\n")
        manifest = self.root / "hashes.sha256"
        manifest.write_text("".join(f"{sha256_file(path)} {path.relative_to(self.root).as_posix()}\n" for path in stage0),
                            encoding="utf-8")
        historical = {path: path.read_bytes() for path in stage0}
        work = self.root / "drift"
        stage_work = cfg.path("build_dir") / "stage_loop"

        def regenerate(argv, *, env, log):
            self.assertIn("OURO_REPRODUCIBLE", env)
            self.assertEqual(log.parent, work)
            if "--out" in argv:
                self.assertEqual(Path(argv[argv.index("--ouro1") + 1]), output)
                self.assertIn("--no-cache", argv)
                out = Path(argv[argv.index("--out") + 1])
                out.parent.mkdir(parents=True, exist_ok=True)
                text = references["driver_u.c"].read_text(encoding="utf-8")
                out.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
            else:
                self.assertEqual(argv, ["sh", "scripts/stage_loop.sh"])
                for name, reference in references.items():
                    out = stage_work / "stage2" / name
                    out.parent.mkdir(parents=True, exist_ok=True)
                    text = reference.read_text(encoding="utf-8")
                    out.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
                write_json_atomic(stage_work / "result.json", {"pass": True, "frontend_eq": True,
                                                               "backend_eq": True, "stages": 2})
            return 0

        with patch.object(drift, "ROOT", self.root), patch.object(drift, "STAGE0", stage0), \
             patch.object(drift, "rel", side_effect=lambda path: path.relative_to(self.root).as_posix()), \
             patch.object(drift, "MANIFEST", manifest), patch.object(build, "load_config", return_value=cfg), \
             patch.object(inputs, "read_bundle", return_value=({}, {})), patch.object(inputs, "verify_stage0") as pinned, \
             patch.object(bootstrap, "current_inputs", return_value=selected), patch.object(drift, "run", side_effect=regenerate):
            self.assertEqual(drift.main(["--mode", "stage-loop", "--work", str(work)]), 0)
        report = json.loads((work / "generated-artifact-drift.json").read_text())
        self.assertTrue(report["pass"])
        self.assertTrue(all(row["pass"] for row in report["details"]["manifest_artifacts"]))
        comparisons = report["details"]["stage_loop"]["reference_artifact_comparisons"]
        self.assertEqual({row["artifact"] for row in comparisons}, set(references))
        self.assertTrue(all(row["pass"] for row in comparisons))
        self.assertEqual(report["details"]["current_reference"]["sha256"],
                         {name: sha256_file(path) for name, path in references.items()})
        pinned.assert_called_with(self.root, {})
        self.assertEqual({path: path.read_bytes() for path in stage0}, historical)

    def test_generated_drift_reads_one_byte_snapshot_per_comparison(self):
        work = self.root / "drift"
        stage_work = self.root / "stage-loop"
        frontend = work / "frontend-regenerated/driver_u.c"
        references = {name: self.root / name for name in ("driver_u.c", "backend_u.c")}
        stage_artifacts = [stage_work / "stage2" / name for name in references]
        raw = b"a\r\nb\rc\0\xff\r"
        normalized = b"a\nb\nc\0\xff\n"
        observed = set(references.values()) | {frontend, *stage_artifacts}
        for path in observed:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(normalized if path in references.values() else raw)
        write_json_atomic(stage_work / "result.json", {"pass": True, "frontend_eq": True,
                                                       "backend_eq": True, "stages": 2})
        raw_hash, normalized_hash = sha256_file(frontend), sha256_file(references["driver_u.c"])
        opened = []

        def open_path(path, *args, _open=Path.open, **kwargs):
            if path in observed:
                opened.append(path)
            return _open(path, *args, **kwargs)

        with patch.object(drift, "run", return_value=0), patch.object(Path, "open", open_path):
            issues, frontend_result = drift.frontend_regen_check({}, work, 1, self.root / "ouro1", references)
            self.assertEqual(issues, [])
            self.assertEqual(opened, [frontend, references["driver_u.c"]])
            opened.clear()
            issues, stage_result = drift.stage_loop_check({}, work, stage_work, references)
            self.assertEqual(issues, [])
            self.assertEqual(opened, [stage_artifacts[0], references["driver_u.c"],
                                      stage_artifacts[1], references["backend_u.c"]])
        for record in [frontend_result, *stage_result["reference_artifact_comparisons"]]:
            self.assertEqual(record["regenerated_sha256"], raw_hash)
            self.assertEqual(record["promotion_normalized_sha256"], normalized_hash)
            self.assertEqual(record["reference_sha256"], normalized_hash)
            self.assertEqual(record["reference_promotion_normalized_sha256"], normalized_hash)
        self.assertEqual((frontend_result["bytes"], frontend_result["promotion_normalized_bytes"]),
                         (len(raw), len(normalized)))

    def test_generated_drift_rejects_stale_missing_or_tampered_bootstrap_evidence(self):
        output, selected, cfg = self.drift_fixture()
        receipt = output.with_name("ouro1.bootstrap.json")
        report = self.work / "report.json"
        paths = [output, receipt, report, self.work / "inputs.json",
                 *(self.work / "out" / phase / name for phase in ("p1", "p2") for name in ("driver_u.c", "backend_u.c"))]
        before = {path: path.read_bytes() for path in paths}
        with patch.object(drift, "ROOT", self.root), patch.object(inputs, "read_bundle", return_value=({}, {})), \
             patch.object(inputs, "verify_stage0"), patch.object(bootstrap, "current_inputs", return_value=selected) as current:
            references, actual, digests, identity = drift.current_reference(output, cfg)
            self.assertEqual(actual, selected)
            self.assertEqual(set(references), {"driver_u.c", "backend_u.c"})
            self.assertEqual(digests, {name: sha256_file(path) for name, path in references.items()})
            self.assertEqual(identity, {"binary": sha256_file(output), "receipt": sha256_file(receipt),
                                        "report": sha256_file(report), "inputs": sha256_file(self.work / "inputs.json")})
            for mutation in ("receipt", "stale", "report", "inputs", "missing-p1", "missing-p2", "changed-p2", "partial"):
                with self.subTest(mutation=mutation):
                    if mutation == "stale":
                        current.return_value = {**selected, "foreign": "source identity"}
                    elif mutation == "receipt":
                        receipt.unlink()
                    elif mutation == "report":
                        report.write_bytes(b"unverified report")
                    elif mutation == "inputs":
                        (self.work / "inputs.json").write_bytes(b"changed frozen inputs")
                    elif mutation.startswith("missing-"):
                        (self.work / "out" / mutation.removeprefix("missing-") / "backend_u.c").unlink()
                    elif mutation == "changed-p2":
                        (self.work / "out/p2/driver_u.c").write_bytes(b"changed generated reference")
                    else:
                        data = json.loads(before[report])
                        del data["complete_generated_c_comparison"]["backend_u.c"]
                        write_json_atomic(report, data)
                        evidence = json.loads(before[receipt])
                        evidence["report_sha256"] = sha256_file(report)
                        write_json_atomic(receipt, evidence)
                    with self.assertRaisesRegex(ValueError, "does not match current inputs"):
                        drift.current_reference(output, cfg)
                    for path in paths:
                        path.write_bytes(before[path])
                    current.return_value = selected
            outside = self.root / "outside"
            shutil.copytree(self.work, outside)
            evidence = json.loads(before[receipt])
            evidence["work"] = str(outside)
            write_json_atomic(receipt, evidence)
            self.assertTrue(bootstrap.installed_current(output, receipt, selected))
            with self.assertRaisesRegex(ValueError, "configured bootstrap directory"):
                drift.current_reference(output, cfg)

    def test_generated_drift_rejects_regeneration_or_fixpoint_differences(self):
        output, _selected, cfg = self.drift_fixture()
        references = {name: self.work / "out/p2" / name for name in ("driver_u.c", "backend_u.c")}
        stage_work = cfg.path("build_dir") / "stage_loop"
        work = self.root / "drift"
        for name, reference in references.items():
            path = stage_work / "stage2" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(reference.read_bytes())
        result = stage_work / "result.json"
        complete = {"pass": True, "frontend_eq": True, "backend_eq": True, "stages": 2}
        write_json_atomic(result, complete)
        with patch.object(drift, "run", return_value=0):
            out = work / "frontend-regenerated/driver_u.c"
            out.parent.mkdir(parents=True)
            out.write_bytes(b"different current frontend\n")
            issues, _details = drift.frontend_regen_check({}, work, 1, output, references)
            self.assertEqual([row["reason"] for row in issues], ["frontend generated artifact drift"])
            for name, reference in references.items():
                with self.subTest(artifact=name):
                    path = stage_work / "stage2" / name
                    path.write_bytes(b"different current stage artifact\n")
                    issues, _details = drift.stage_loop_check({}, work, stage_work, references)
                    self.assertEqual([row["artifact"] for row in issues], [name])
                    path.write_bytes(reference.read_bytes())
            write_json_atomic(result, {**complete, "backend_eq": False})
            issues, _details = drift.stage_loop_check({}, work, stage_work, references)
            self.assertEqual([row["reason"] for row in issues], ["stage-loop did not prove frontend/backend fixpoint"])

    def test_generated_drift_rechecks_reference_after_regeneration(self):
        output, selected, cfg = self.drift_fixture()
        work = self.root / "drift"
        receipt = output.with_name("ouro1.bootstrap.json")
        report_path = self.work / "report.json"
        paths = [receipt, report_path, self.work / "out/p1/backend_u.c", self.work / "out/p2/backend_u.c"]
        before = {path: path.read_bytes() for path in paths}
        for replacement in ("tampered", "generated-c", "metadata-only"):
            with self.subTest(replaced_evidence=replacement):
                def change_reference(*_args, replaced_evidence=replacement):
                    backend = self.work / "out/p2/backend_u.c"
                    if replaced_evidence != "metadata-only":
                        backend.write_bytes(b"reference changed during regeneration")
                    if replaced_evidence != "tampered":
                        evidence = json.loads(before[report_path])
                        if replaced_evidence == "generated-c":
                            (self.work / "out/p1/backend_u.c").write_bytes(backend.read_bytes())
                            evidence["complete_generated_c_comparison"]["backend_u.c"] = {
                                "p1_sha256": sha256_file(backend), "p2_sha256": sha256_file(backend)}
                        else:
                            evidence["fixture_metadata"] = "report replaced during regeneration"
                            self.assertEqual(backend.read_bytes(), before[backend])
                        write_json_atomic(report_path, evidence)
                        installed = json.loads(before[receipt])
                        installed["report_sha256"] = sha256_file(report_path)
                        write_json_atomic(receipt, installed)
                        self.assertTrue(bootstrap.installed_current(output, receipt, selected))
                    return [], {}

                with patch.object(drift, "ROOT", self.root), patch.object(drift, "manifest_checks", return_value=([], [])), \
                     patch.object(build, "load_config", return_value=cfg), patch.object(inputs, "read_bundle", return_value=({}, {})), \
                     patch.object(inputs, "verify_stage0"), patch.object(bootstrap, "current_inputs", return_value=selected), \
                     patch.object(drift, "frontend_regen_check", side_effect=change_reference):
                    self.assertEqual(drift.main(["--mode", "frontend", "--work", str(work)]), 1)
                report = json.loads((work / "generated-artifact-drift.json").read_text())
                self.assertFalse(report["pass"])
                self.assertEqual(report["issues"][0]["reason"], "unverified current generated-artifact reference")
                if replacement != "tampered":
                    self.assertIn("evidence changed during regeneration", report["issues"][0]["error"])
                for path in paths:
                    path.write_bytes(before[path])

    def test_missing_python_stops_shell_bootstrap_before_compilation(self):
        shell = shutil.which("sh")
        if shell is None:
            self.skipTest("POSIX shell unavailable for the no-Python bootstrap fixture")
        root = self.root / "shell-fixture"
        (root / "scripts").mkdir(parents=True)
        shutil.copyfile(build.ROOT / "scripts/bootstrap.sh", root / "scripts/bootstrap.sh")
        (root / "scripts/python.sh").write_text('PYTHON=""\n', encoding="utf-8")
        process = subprocess.run([shell, str(root / "scripts/bootstrap.sh")], cwd=root,
                                 text=True, capture_output=True, check=False)
        self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
        self.assertIn("Python 3 is required for the verified current-source bootstrap", process.stderr)
        self.assertFalse((root / "_build").exists())


def run() -> None:
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(BootstrapCompilerTests))
    if not result.wasSuccessful():
        raise AssertionError("bootstrap compiler contract tests failed")


if __name__ == "__main__":
    unittest.main()
