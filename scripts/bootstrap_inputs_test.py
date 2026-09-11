#!/usr/bin/env python3
"""Negative archive fixtures and exact reproduction for C-bootstrap inputs."""
from __future__ import annotations

import copy
import gzip
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

import bootstrap_inputs as inputs


class BootstrapInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.contents = inputs.read_bundle()
        cls.archive = (inputs.ROOT / inputs.ARCHIVE).read_bytes()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ouro-bootstrap-inputs-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "fixture"
        (self.root / "compiler/bootstrap").mkdir(parents=True)

    def write_fixture(self, entries, *, manifest=None):
        buffer = io.BytesIO()
        with gzip.GzipFile(filename="", fileobj=buffer, mode="wb", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as package:
                for entry, data in entries:
                    package.addfile(entry, io.BytesIO(data) if entry.isfile() else None)
        archive = buffer.getvalue()
        data = copy.deepcopy(self.manifest if manifest is None else manifest)
        # Repin only the outer archive to exercise the inner inventory guards.
        data.update(archive_sha256=inputs.digest(archive), archive_bytes=len(archive))
        (self.root / inputs.ARCHIVE).write_bytes(archive)
        (self.root / inputs.MANIFEST).write_text(json.dumps(data), encoding="utf-8")

    def entries(self):
        rows = []
        for name, data in sorted(self.contents.items()):
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            rows.append((entry, data))
        return rows

    def rejected_before_extraction(self, entries, message):
        self.write_fixture(entries)
        output = self.root / "unpacked"
        with self.assertRaisesRegex(ValueError, message):
            inputs.unpack(output, self.root)
        self.assertFalse(output.exists(), "invalid input must fail before writing any member")

    def test_exact_inventory_unpacks_and_reproduces_archive(self):
        output = self.root / "unpacked"
        actual = inputs.unpack(output)
        self.assertEqual(actual, self.manifest)
        self.assertEqual({path.relative_to(output).as_posix(): path.read_bytes()
                          for path in output.rglob("*") if path.is_file()}, self.contents)
        reproduced = self.root / "reproduced.tar.gz"
        inputs.repack(output, reproduced)
        self.assertEqual(reproduced.read_bytes(), self.archive)
        with self.assertRaises(FileExistsError):
            inputs.unpack(output)
        self.assertEqual((output / next(iter(self.contents))).read_bytes(), next(iter(self.contents.values())))

    def test_symlink_member_rejected_before_any_write(self):
        rows = self.entries()
        rows[0][0].type = tarfile.SYMTYPE
        rows[0][0].size = 0
        rows[0][0].linkname = "../../outside"
        self.rejected_before_extraction(rows, "non-file archive member")

    def test_hardlink_member_rejected_before_any_write(self):
        rows = self.entries()
        rows[0][0].type = tarfile.LNKTYPE
        rows[0][0].size = 0
        rows[0][0].linkname = rows[1][0].name
        self.rejected_before_extraction(rows, "non-file archive member")

    def test_traversal_absolute_and_windows_paths_rejected(self):
        for name in ("bridge/../../outside", "/outside", "C:/outside", "bridge\\compiler\\outside", "bridge/./compiler/outside"):
            with self.subTest(member=name):
                rows = self.entries()
                rows[0][0].name = name
                self.rejected_before_extraction(rows, "unsafe member path")

    def test_duplicate_member_rejected_even_if_bytes_match(self):
        rows = self.entries()
        self.rejected_before_extraction([*rows, rows[0]], "duplicate archive member")

    def test_missing_member_rejected(self):
        self.rejected_before_extraction(self.entries()[1:], "missing archive members")

    def test_unexpected_member_rejected(self):
        rows = self.entries()
        extra = tarfile.TarInfo("bridge/compiler/undeclared.ouro")
        extra.size = 1
        self.rejected_before_extraction([*rows, (extra, b"x")], "unexpected archive member")

    def test_member_hash_mismatch_rejected(self):
        rows = self.entries()
        entry, data = rows[0]
        rows[0] = (entry, bytes([data[0] ^ 1]) + data[1:])
        self.rejected_before_extraction(rows, "member hash or size mismatch")

    def test_member_size_mismatch_rejected(self):
        rows = self.entries()
        entry, data = rows[0]
        entry.size += 1
        rows[0] = (entry, data + b"x")
        self.rejected_before_extraction(rows, "member size mismatch")

    def test_archive_hash_mismatch_rejected(self):
        self.write_fixture(self.entries())
        path = self.root / inputs.ARCHIVE
        path.write_bytes(path.read_bytes() + b"foreign")
        with self.assertRaisesRegex(ValueError, "archive hash or size mismatch"):
            inputs.read_bundle(self.root)

    def test_incomplete_declared_closure_rejected(self):
        manifest = copy.deepcopy(self.manifest)
        del manifest["ordered_unit_graph"][manifest["ordered_roots"][-1]]
        self.write_fixture(self.entries(), manifest=manifest)
        with self.assertRaisesRegex(ValueError, "incomplete bridge root graph"):
            inputs.read_bundle(self.root)

    def test_historical_stage0_pair_must_match_both_hashes(self):
        manifest = {"stage0": {}}
        for name in inputs.STAGE0:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            data = name.encode()
            path.write_bytes(data)
            manifest["stage0"][name] = {"bytes": len(data), "sha256": inputs.digest(data)}
        inputs.verify_stage0(self.root, manifest)
        path.write_bytes(b"foreign" + data[7:])
        with self.assertRaisesRegex(ValueError, "historical stage0 mismatch"):
            inputs.verify_stage0(self.root, manifest)

    def test_reviewed_patch_texts_and_final_origins_are_hash_bound(self):
        provenance = self.manifest["provenance"]
        for row in provenance["reviewed_source_changes"]:
            self.assertEqual(inputs.digest(row["reviewed_patch"].encode()), row["reviewed_patch_sha256"])
            for name, change in row["files"].items():
                self.assertEqual(inputs.digest(self.contents["bridge/" + name]), change["b6_sha256"])
        projection = provenance["historical_projection"]
        self.assertEqual(sum(len(row["blank_declarations"]) for row in projection), 4)
        self.assertTrue(provenance["transformations_are_provenance_only"])


def run() -> None:
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(BootstrapInputTests))
    if not result.wasSuccessful():
        raise AssertionError("bootstrap input contract tests failed")


if __name__ == "__main__":
    unittest.main()
