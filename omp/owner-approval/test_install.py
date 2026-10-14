import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from install import ASSETS, load_snapshot, read_regular


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        files = {}
        for name in ASSETS:
            body = ('payload ' + name).encode()
            (self.root / name).write_bytes(body)
            files[name] = hashlib.sha256(body).hexdigest()
        self.manifest = {'owner_uid': os.getuid(), 'files': files}
        self.freeze()

    def freeze(self):
        body = json.dumps(self.manifest).encode()
        (self.root / 'manifest.json').write_bytes(body)
        self.hash = hashlib.sha256(body).hexdigest()

    def test_altered_source_cannot_be_installed_under_an_old_approval(self):
        (self.root / 'broker.py').write_text('unauthorized executable')
        with self.assertRaisesRegex(ValueError, 'payload changed'):
            load_snapshot(self.root, self.hash)

    def test_an_expanded_manifest_cannot_be_installed_under_an_old_approval(self):
        old_hash = self.hash
        self.manifest['files']['arbitrary-root-shell'] = '0' * 64
        self.freeze()
        with self.assertRaisesRegex(ValueError, 'manifest changed'):
            load_snapshot(self.root, old_hash)
        with self.assertRaisesRegex(ValueError, 'unexpected scope'):
            load_snapshot(self.root, self.hash)

    def test_symlink_payload_is_rejected_even_if_the_target_has_matching_bytes(self):
        path = self.root / 'broker.py'
        path.rename(self.root / 'target')
        path.symlink_to(self.root / 'target')
        with self.assertRaises(OSError):
            load_snapshot(self.root, self.hash)

    def test_directory_and_oversized_payload_are_not_executable_installation_inputs(self):
        with self.assertRaises(ValueError):
            read_regular(self.root)
        (self.root / 'too-large').write_bytes(b'x' * 101)
        with self.assertRaises(ValueError):
            read_regular(self.root / 'too-large', maximum=100)


if __name__ == '__main__':
    unittest.main()
