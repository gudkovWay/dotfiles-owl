import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from install import ASSETS
from setup import build_payload, run


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name)
        for name in ASSETS:
            (self.source / name).write_bytes(('reviewed payload: ' + name).encode())

    def test_payload_is_frozen_before_the_password_dialog(self):
        bodies, manifest = build_payload(self.source, 1000)
        (self.source / 'broker.py').write_bytes(b'changed while authenticating')
        self.assertEqual(bodies['broker.py'], b'reviewed payload: broker.py')
        self.assertEqual(json.loads(manifest)['owner_uid'], 1000)

    def test_runtime_state_and_private_files_do_not_enter_the_installation_payload(self):
        (self.source / 'owner.json').write_text('owner runtime state')
        (self.source / 'credentials.json').write_text('private runtime marker')
        bodies, manifest = build_payload(self.source, 1000)
        self.assertNotIn('owner.json', bodies)
        self.assertNotIn('credentials.json', bodies)
        self.assertNotIn(b'private runtime marker', manifest)

    def test_root_cannot_be_misidentified_as_the_owner(self):
        with self.assertRaises(ValueError):
            build_payload(self.source, 0)

    def test_dry_run_never_opens_authentication_or_changes_system_files(self):
        output = io.StringIO()
        with patch('setup.subprocess.run', side_effect=AssertionError('unexpected authentication')), contextlib.redirect_stdout(output):
            result = run(self.source, dry_run=True)
        self.assertEqual(result, 0)
        self.assertTrue(json.loads(output.getvalue())['requires_authentication'])
        self.assertFalse((self.source / 'manifest.json').exists())


if __name__ == '__main__':
    unittest.main()
