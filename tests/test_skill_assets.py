#!/usr/bin/env python3
"""Verify the vendored installed snapshots, without running upstream helpers/models."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SkillSnapshotTests(unittest.TestCase):
    def test_taste_dependency_closure_matches_pinned_upstream_bytes(self):
        root = ROOT / 'omp/skills/design-taste-frontend'
        manifest = json.loads((root / 'INSTALLATION.json').read_text())
        self.assertEqual(manifest['version'], '2.1.4')
        self.assertFalse(manifest['local_upstream_modifications'])
        for name, digest in manifest['upstream_files_sha256'].items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), digest)
        self.assertEqual(hashlib.sha256((root / 'LICENSE').read_bytes()).hexdigest(), manifest['license_sha256'])

    def test_anti_slop_modules_match_the_owner_installed_release(self):
        root = ROOT / 'agents/skills'
        manifest = json.loads((root / 'antislop/INSTALLATION.json').read_text())
        self.assertEqual((root / 'antislop/VERSION').read_text().strip(), manifest['version'])
        for name, digest in manifest['files_sha256'].items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), digest)


if __name__ == '__main__':
    unittest.main()
