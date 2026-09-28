#!/usr/bin/env python3
"""Source equality, reproducibility, and refusal laws for the composed lower bridge."""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from bootstrap_inputs import ARCHIVE, MANIFEST, archive_bytes, read_bundle
from repo_support import sha256_bytes
import refresh_lower_bridge as refresh


PREVIOUS_LOWER_COPIES = {'lower_xvnat': {'name': 'lower_xvnat',
                 'source': 'compiler/lower.ouro',
                 'source_blob': 'bd40cebe82608c5a23042f1349aea9b5964d17c1',
                 'source_sha256': '57b4891a493f01435a28ce8ea8a217e3269b8f2dafc92b7fafe97b68853daa83',
                 'first_line': 79,
                 'bytes': 329,
                 'sha256': '80d20f220b11359ed1b2b47318d8a7ae4f5713de4d9fdb6889a9afa702ebf89d'},
 'lower_xvascribe': {'name': 'lower_xvascribe',
                     'source': 'compiler/lower.ouro',
                     'source_blob': 'bd40cebe82608c5a23042f1349aea9b5964d17c1',
                     'source_sha256': '57b4891a493f01435a28ce8ea8a217e3269b8f2dafc92b7fafe97b68853daa83',
                     'first_line': 353,
                     'bytes': 627,
                     'sha256': 'c4a2be662f3835813576b4f2d9a34bd6c21cb8ef7917bf494e42d35bf2d0f0f7'}}


class LowerBridgeRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = refresh.load_sources(refresh.ROOT)
        encoded = (refresh.ROOT / MANIFEST).read_bytes()
        manifest, contents = read_bundle()
        cls.original, cls.contents = refresh.predecessor(encoded, manifest, contents, cls.sources)
        cls.generated, cls.changed, cls.archive, cls.encoded = refresh.compose(cls.original, cls.contents, cls.sources)

    def pinned_installed_packages(self):
        for identity, blob in (
            (refresh.PREVIOUS_MANIFEST, '602bbe08c9c7446cbec9f056682aad7e62ca0b2c'),
            (refresh.INTERMEDIATE_MANIFEST, 'c4fe78b32e212903d6616133651fcf4c36ab463d'),
            (refresh.INSTALLED_MANIFEST, '01883061244d802a36b88c5e2e9e468890ed0bfb'),
        ):
            installed = copy.deepcopy(self.generated)
            provenance = installed['provenance']['lowering_refresh']
            provenance['source_blobs']['compiler/lower.ouro'] = 'bd40cebe82608c5a23042f1349aea9b5964d17c1'
            provenance['source_blobs']['compiler/pipeline_support.ouro'] = blob
            provenance['source_copies'] = [
                copy.deepcopy(PREVIOUS_LOWER_COPIES[row['name']])
                if row['source'] == 'compiler/lower.ouro' else row
                for row in provenance['source_copies']
            ]
            self.assertEqual(sha256_bytes(refresh.encoded_manifest(installed)), identity)
            yield identity, installed
        yield refresh.NEW_MANIFEST, copy.deepcopy(self.generated)

    def test_source_operations_commute_and_preserve_all_other_members(self):
        previous = self.contents[refresh.MEMBER]
        nat_source, typed_source, rows = refresh.source_copies(self.sources)
        nat_first = previous.replace(refresh.LEGACY_NAT, nat_source, 1).replace(refresh.LEGACY_ASCRIPTION, typed_source, 1)
        ascription_first = previous.replace(refresh.LEGACY_ASCRIPTION, typed_source, 1).replace(refresh.LEGACY_NAT, nat_source, 1)
        self.assertEqual(nat_first, ascription_first)
        self.assertEqual(self.changed[refresh.MEMBER], nat_first)
        self.assertEqual([name for name in self.changed if self.changed[name] != self.contents[name]], [refresh.MEMBER])
        self.assertEqual(len(self.changed), 68)
        self.assertEqual(self.generated['stage0'], self.original['stage0'])
        self.assertEqual(self.generated['ordered_unit_graph'], self.original['ordered_unit_graph'])
        self.assertEqual(self.generated['ordered_roots'], self.original['ordered_roots'])
        self.assertEqual([row['name'] for row in rows], [row[0] for row in refresh.nat.COPIES] + ['lower_xvascribe'])
        for row in rows:
            data = self.sources[row['source']]
            self.assertEqual(row['source_blob'], refresh.nat.git_blob(data))
            self.assertEqual(row['source_sha256'], sha256_bytes(data))
        self.assertEqual(sha256_bytes(nat_first), refresh.NEW_MEMBER)
        self.assertEqual(sha256_bytes(archive_bytes(self.changed)), refresh.NEW_ARCHIVE)
        self.assertEqual(sha256_bytes(self.encoded), refresh.NEW_MANIFEST)

    def test_pinned_installed_packages_derive_only_new_source_metadata(self):
        for identity, installed in self.pinned_installed_packages():
            with self.subTest(identity=identity):
                encoded = refresh.encoded_manifest(installed)
                self.assertEqual(sha256_bytes(encoded), identity)
                original, previous = refresh.predecessor(encoded, installed, self.changed, self.sources)
                result = refresh.compose(original, previous, self.sources)
                self.assertEqual(result, (self.generated, self.changed, self.archive, self.encoded))
                with tempfile.TemporaryDirectory(prefix='ouro-lower-bridge-previous-') as directory:
                    root = Path(directory)
                    files = {**self.sources, MANIFEST: encoded, ARCHIVE: self.archive}
                    files.update({name: (refresh.ROOT / name).read_bytes() for name in refresh.nat.SEED})
                    for name, data in files.items():
                        target = root / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(data)
                    self.assertEqual(refresh.candidate(root), result)
                expected = copy.deepcopy(installed)
                expected['provenance']['lowering_refresh']['source_blobs'] = refresh.SOURCE_BLOBS
                expected['provenance']['lowering_refresh']['source_copies'] = self.generated['provenance']['lowering_refresh']['source_copies']
                self.assertEqual(self.generated, expected)
                self.assertEqual(self.generated['stage0'], installed['stage0'])
                for old_row, new_row in zip(installed['provenance']['lowering_refresh']['source_copies'],
                        self.generated['provenance']['lowering_refresh']['source_copies'], strict=True):
                    self.assertEqual({key: old_row[key] for key in ('name', 'first_line', 'bytes', 'sha256')},
                        {key: new_row[key] for key in ('name', 'first_line', 'bytes', 'sha256')})
                self.assertEqual(len(self.changed), 68)
        self.assertEqual(len({refresh.PREVIOUS_MANIFEST, refresh.INTERMEDIATE_MANIFEST, refresh.INSTALLED_MANIFEST, refresh.NEW_MANIFEST}), 4)
        self.assertEqual(sha256_bytes(self.encoded), refresh.NEW_MANIFEST)
        self.assertEqual((refresh.ROOT / ARCHIVE).read_bytes(), self.archive)

    def test_pinned_installed_unknown_metadata_or_member_are_rejected(self):
        for identity, installed in self.pinned_installed_packages():
            self.assertEqual(sha256_bytes(refresh.encoded_manifest(installed)), identity)
            contents = self.changed
            with self.subTest(identity=identity):
                unknown = copy.deepcopy(installed)
                unknown['provenance']['lowering_refresh']['source_blobs']['compiler/pipeline_support.ouro'] = '0' * 40
                with self.assertRaisesRegex(ValueError, 'use the pinned predecessor'):
                    refresh.predecessor(refresh.encoded_manifest(unknown), unknown, contents, self.sources)
                changed = {**contents, refresh.MEMBER: contents[refresh.MEMBER] + b'\n'}
                with self.assertRaisesRegex(ValueError, 'installed bridge lower changed'):
                    refresh.predecessor(refresh.encoded_manifest(installed), installed, changed, self.sources)
                name = 'bridge/compiler/pipeline_support.ouro'
                changed = {**contents, name: contents[name] + b'\n'}
                with self.assertRaisesRegex(ValueError, 'reconstructed predecessor package differs'):
                    refresh.predecessor(refresh.encoded_manifest(installed), installed, changed, self.sources)

    def test_exact_installed_package_regenerates_identical_bytes(self):
        with tempfile.TemporaryDirectory(prefix='ouro-lower-bridge-repeat-') as directory:
            root = Path(directory)
            files = {**self.sources, MANIFEST: self.encoded, ARCHIVE: self.archive}
            files.update({name: (refresh.ROOT / name).read_bytes() for name in refresh.nat.SEED})
            for name, data in files.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            original, contents = refresh.predecessor(self.encoded, self.generated, self.changed, self.sources)
            self.assertEqual(original, self.original)
            self.assertEqual(contents, self.contents)
            self.assertEqual(sha256_bytes(archive_bytes(contents)), refresh.nat.OLD_ARCHIVE)
            self.assertEqual(refresh.candidate(root), (self.generated, self.changed, self.archive, self.encoded))
            self.assertEqual((root / MANIFEST).read_bytes(), self.encoded)
            self.assertEqual((root / ARCHIVE).read_bytes(), self.archive)
            package = root / ARCHIVE
            package.write_bytes(self.archive[:-1] + bytes([self.archive[-1] ^ 1]))
            with self.assertRaisesRegex(ValueError, 'archive hash or size mismatch'):
                refresh.candidate(root)

    def test_each_changed_source_owner_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='ouro-lower-bridge-sources-') as directory:
            root = Path(directory)
            for name, data in self.sources.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            self.assertEqual(refresh.load_sources(root), self.sources)
            for name, data in self.sources.items():
                with self.subTest(source=name):
                    target = root / name
                    target.write_bytes(data + b'\n')
                    with self.assertRaisesRegex(ValueError, 'product source blob changed: ' + name):
                        refresh.load_sources(root)
                    target.write_bytes(data)

    def test_changed_nat_and_ascription_fragments_are_rejected(self):
        name = 'compiler/lower_nat.ouro'
        changed = self.sources[name].replace(b'value 255', b'value 254')
        self.assertNotEqual(changed, self.sources[name])
        with self.assertRaisesRegex(ValueError, 'source function bytes changed'):
            refresh.source_copies({**self.sources, name: changed})
        name = 'compiler/lower.ouro'
        changed = self.sources[name].replace(b'VSurf (SLet Z tmS tyS (SVar Z));', b'VSurf tmS;')
        self.assertNotEqual(changed, self.sources[name])
        with self.assertRaisesRegex(ValueError, 'ascription source function bytes changed'):
            refresh.source_copies({**self.sources, name: changed})

    def test_altered_predecessor_and_helper_collision_are_rejected(self):
        changed = {**self.contents, refresh.MEMBER: self.contents[refresh.MEMBER] + b'\n'}
        with self.assertRaisesRegex(ValueError, 'historical bridge lower changed'):
            refresh.compose(self.original, changed, self.sources)
        name = 'bridge/compiler/base.ouro'
        changed = {**self.contents, name: self.contents[name] + b'\ndef literal_nat_family : Nat := 0;\n'}
        with self.assertRaisesRegex(ValueError, 'Nat helper collides'):
            refresh.compose(self.original, changed, self.sources)

    def test_wrong_manifest_inventory_seed_and_installed_member_are_rejected(self):
        unknown = copy.deepcopy(self.original)
        unknown['provenance']['unexpected_refresh'] = True
        with self.assertRaisesRegex(ValueError, 'use the pinned predecessor'):
            refresh.predecessor(refresh.encoded_manifest(unknown), unknown, self.contents, self.sources)
        with self.assertRaisesRegex(ValueError, 'manifest encoding changed'):
            refresh.predecessor(self.encoded + b'\n', self.generated, self.changed, self.sources)
        with self.assertRaisesRegex(ValueError, 'inventory or seed changed'):
            refresh.predecessor(self.encoded, self.generated, {}, self.sources)
        unknown = copy.deepcopy(self.generated)
        unknown['stage0'] = {}
        with self.assertRaisesRegex(ValueError, 'inventory or seed changed'):
            refresh.predecessor(refresh.encoded_manifest(unknown), unknown, self.changed, self.sources)
        changed = {**self.changed, refresh.MEMBER: self.changed[refresh.MEMBER] + b'\n'}
        with self.assertRaisesRegex(ValueError, 'installed bridge lower changed'):
            refresh.predecessor(self.encoded, self.generated, changed, self.sources)

    def test_missing_duplicate_and_reordered_ascription_boundaries_are_rejected(self):
        start, end = refresh.ascribe.START, refresh.ascribe.END
        for data in (start, start + start + end, end + start):
            with self.subTest(data=data), self.assertRaisesRegex(ValueError, 'ascription function'):
                refresh.ascribe.function(data)

    def test_failed_candidate_guard_cannot_install_pair(self):
        with patch.object(sys, 'argv', ['refresh_lower_bridge.py', '--write']), \
                patch.object(refresh, 'candidate', side_effect=ValueError('source guard failure')), \
                patch.object(refresh.nat, 'write_once') as writer:
            with self.assertRaisesRegex(ValueError, 'source guard failure'):
                refresh.main()
            writer.assert_not_called()


if __name__ == '__main__':
    unittest.main()
