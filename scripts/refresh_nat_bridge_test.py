#!/usr/bin/env python3
"""Scoped source-copy and rejection laws for the Nat bridge refresh."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from bootstrap_inputs import archive_bytes, read_bundle
from repo_support import sha256_bytes
import refresh_nat_bridge as refresh


LEGACY_NAT = b"def lower_xvnat\n  (_lower_run : Nat -> LowerEnv -> Maybe Surface -> Maybe Nat -> List (Pair Nat Surface) -> LowerMode -> LowerVal)\n  (_fuel' : Nat)\n  (env : LowerEnv)\n  (_er : Maybe Surface)\n  (_fixSelf : Maybe Nat)\n  (_locals : List (Pair Nat Surface))\n  (n : Nat) : LowerVal :=\nVSurf (lower_nat_env env n);\n"


class NatBridgeRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = refresh.load_sources(refresh.ROOT)
        _manifest, installed = read_bundle()
        previous = installed[refresh.MEMBER]
        if sha256_bytes(previous) == refresh.NEW_MEMBER:
            replacement, _copies = refresh.source_copies(cls.sources)
            if previous.count(replacement) != 1:
                raise ValueError("installed Nat source copy not unique")
            previous = previous.replace(replacement, LEGACY_NAT)
        if sha256_bytes(previous) != refresh.OLD_MEMBER:
            raise ValueError("test predecessor member changed")
        cls.contents = {**installed, refresh.MEMBER: previous}

    def test_source_copy_changes_only_one_member_and_reproduces_exact_archive(self):
        updated, copies = refresh.refreshed_member(self.contents, self.sources)
        changed = {**self.contents, refresh.MEMBER: updated}
        self.assertEqual([name for name in changed if changed[name] != self.contents[name]], [refresh.MEMBER])
        self.assertEqual(len(changed), 68)
        self.assertEqual(sha256_bytes(updated), refresh.NEW_MEMBER)
        self.assertEqual(sha256_bytes(archive_bytes(changed)), refresh.NEW_ARCHIVE)
        self.assertEqual([row['name'] for row in copies], [row[0] for row in refresh.COPIES])
        replacement, _rows = refresh.source_copies(self.sources)
        self.assertEqual(updated.replace(replacement, LEGACY_NAT), self.contents[refresh.MEMBER])

    def test_modified_product_source_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="ouro-nat-bridge-sources-") as directory:
            root = Path(directory)
            for name, data in self.sources.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            target = root / "compiler/lower_nat.ouro"
            target.write_bytes(target.read_bytes() + b"\n-- changed source\n")
            with self.assertRaisesRegex(ValueError, "product source blob changed"):
                refresh.load_sources(root)

    def test_modified_source_function_is_rejected(self):
        sources = {**self.sources, "compiler/lower_nat.ouro": self.sources["compiler/lower_nat.ouro"].replace(b"value 255", b"value 254")}
        with self.assertRaisesRegex(ValueError, "source function bytes changed"):
            refresh.source_copies(sources)

    def test_modified_historical_member_is_rejected(self):
        contents = {**self.contents, refresh.MEMBER: self.contents[refresh.MEMBER] + b"\n"}
        with self.assertRaisesRegex(ValueError, "historical bridge lower changed"):
            refresh.refreshed_member(contents, self.sources)

    def test_existing_historical_helper_name_is_rejected(self):
        name = "bridge/compiler/base.ouro"
        contents = {**self.contents, name: self.contents[name] + b"\ndef literal_nat_family : Nat := 0;\n"}
        with self.assertRaisesRegex(ValueError, "Nat helper collides"):
            refresh.refreshed_member(contents, self.sources)

    def test_missing_duplicate_and_reordered_function_boundaries_are_rejected(self):
        for data in (b"begin only", b"begin begin end", b"end begin"):
            with self.subTest(data=data), self.assertRaisesRegex(ValueError, "source function"):
                refresh.section(data, b"begin", b"end")


if __name__ == "__main__":
    unittest.main()
