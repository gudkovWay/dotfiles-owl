#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MachineStdoutTests(unittest.TestCase):
    def test_view_json_survives_real_guard_and_wrapper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            (root / 'README').write_text('fixture\n')
            subprocess.run(['git', 'add', 'README'], cwd=root, check=True)
            subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                            'commit', '-qm', 'fixture'], cwd=root, check=True)
            subprocess.run(['git', 'branch', '-m', 'dev'], cwd=root, check=True)
            glab = root / 'glab'
            glab.write_text('#!/bin/sh\nprintf \'{"iid":42,"state":"opened"}\\n\'\n')
            glab.chmod(0o700)
            result = subprocess.run(['sh', str(ROOT / 'mr'), 'view', '42', '--output', 'json'],
                                    cwd=root, env={**os.environ, 'WT_MR_BASE': 'dev', 'GLAB_BIN': str(glab)},
                                    text=True, capture_output=True, check=True)
            self.assertEqual(json.loads(result.stdout), {'iid': 42, 'state': 'opened'})
            self.assertIn('mr-guard: OK', result.stderr)


if __name__ == '__main__':
    unittest.main()
