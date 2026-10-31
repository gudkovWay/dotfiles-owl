"""Project toolchain contracts; no package install, Nuxt prepare or backend."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def environment_module():
    loader = importlib.machinery.SourceFileLoader('toolchain_environment', str(ROOT / 'project-environment'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class ToolchainTests(unittest.TestCase):
    def test_dependency_identity_changes_with_npm_and_node(self):
        module = environment_module()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'package.json').write_text('{}')
            (root / 'package-lock.json').write_text('{}')
            with patch.object(module.subprocess, 'check_output', side_effect=['node24', '11']):
                first = module.dependencies_key(root)
            with patch.object(module.subprocess, 'check_output', side_effect=['node24', '12']):
                self.assertNotEqual(module.dependencies_key(root), first)
            with patch.object(module.subprocess, 'check_output', side_effect=['node26', '11']):
                self.assertNotEqual(module.dependencies_key(root), first)

    def test_native_wrapper_selects_node24_without_mutating_parent(self):
        before = os.environ['PATH']
        result = subprocess.run([str(ROOT / 'p2p-frontend/toolchain'), 'node', '--print',
                                 'JSON.stringify({version:process.version,path:process.execPath})'],
                                capture_output=True, text=True, check=True, timeout=10)
        data = json.loads(result.stdout)
        self.assertTrue(data['version'].startswith('v24.'))
        self.assertIn('node-v24.11.0-linux-x64/bin/node', data['path'])
        self.assertEqual(os.environ['PATH'], before)
        result = subprocess.run([str(ROOT / 'p2p-frontend/toolchain'), 'npm', '--version'],
                                capture_output=True, text=True, check=True, timeout=10)
        self.assertRegex(result.stdout, r'^\d+\.\d+\.\d+')

    def test_only_p2p_aliases_select_the_project_toolchain(self):
        config = ROOT.parent / 'worktrunk-config.toml'
        if not config.is_file():
            config = ROOT.parent / 'config.toml'
        data = tomllib.loads(config.read_text())
        p2p = data['projects']['gitlab.psclp.org/common/frontend/frontend']['aliases']
        ecom = data['projects']['gitlab.psclp.org/ecom/frontend/frontend']['aliases']
        for name in ('env', 'ui', 'dev', 'typecheck', 'finalize', 'commit'):
            self.assertTrue(p2p[name].startswith('/home/q/.config/worktrunk/projects/p2p-frontend/toolchain '), name)
        self.assertTrue(all('/toolchain ' not in value for value in ecom.values()))


if __name__ == '__main__':
    unittest.main()
