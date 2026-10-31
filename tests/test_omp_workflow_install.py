"""Install authored OMP defaults without accessing the owner's live profile."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
METHODS = ('systematic-debugging', 'test-driven-development',
           'receiving-code-review', 'verification-before-completion')


class WorkflowInstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='omp-workflow-install-')
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name) / 'home'
        self.agent = self.home / '.omp/agent'
        self.agent.mkdir(parents=True)
        self.commands = Path(temporary.name) / 'bin'
        self.commands.mkdir()
        for name in ('systemctl', 'herdr'):
            command = self.commands / name
            command.write_text('#!/bin/sh\nexit 0\n')
            command.chmod(0o700)
        self.environment = {**os.environ, 'HOME': str(self.home),
                            'XDG_CONFIG_HOME': str(self.home / '.config'),
                            'PATH': str(self.commands) + os.pathsep + os.environ['PATH']}
        self.protected = {
            'AGENTS.md': b'original Choirboy startup\n',
            'mcp.json': b'{"mcpServers":{"linear":{"url":"https://fixture.invalid"}}}',
            'agent.db': b'private native authentication sentinel',
        }
        for name, content in self.protected.items():
            (self.agent / name).write_bytes(content)

    def install(self):
        result = subprocess.run(['bash', str(ROOT / 'install.sh')],
                                env=self.environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        for name, content in self.protected.items():
            path = self.agent / name
            self.assertFalse(path.is_symlink(), name)
            self.assertEqual(path.read_bytes(), content, name)
        self.assertFalse((self.agent / 'mcp-profiles').exists())

    def test_fresh_install_exposes_only_curated_superpowers_methods(self):
        self.install()
        for name in ('config.yml', 'lsp.json', 'SYSTEM_TEMPLATE.md',
                     'skills/ponytail/SKILL.md', 'skills/write-a-skill/SKILL.md'):
            path = self.agent / name
            self.assertTrue(path.is_symlink(), name)
            self.assertEqual(path.resolve(), (ROOT / 'omp' / name).resolve())
        bundle = self.agent / 'skill-bundles/superpowers'
        self.assertEqual(sorted(path.name for path in bundle.iterdir()), sorted(METHODS))
        for name in METHODS:
            path = bundle / name
            self.assertTrue(path.is_symlink(), name)
            self.assertEqual(str(path.resolve()), '/home/q/.agents/shared/superpowers/skills/' + name)
        self.install()

    def test_existing_local_settings_lsp_template_and_skills_are_not_overwritten(self):
        originals = {
            'config.yml': b'modelRoles:\n  default: owner/model\nskills:\n  customDirectories: [owner-directory]\n',
            'lsp.json': b'{"servers":{"owner":{"command":"owner-lsp"}}}',
            'SYSTEM_TEMPLATE.md': b'owner-specific instructions\n',
            'skills/ponytail/SKILL.md': b'owner-specific Ponytail\n',
        }
        for name, content in originals.items():
            path = self.agent / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.install()
        for name, content in originals.items():
            path = self.agent / name
            self.assertFalse(path.is_symlink(), name)
            self.assertEqual(path.read_bytes(), content, name)


if __name__ == '__main__':
    unittest.main()
