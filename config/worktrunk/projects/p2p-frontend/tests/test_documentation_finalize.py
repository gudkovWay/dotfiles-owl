import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import feature_finalize as f
import review_contract as rc


class DocumentationFinalizeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        environment = patch.dict(os.environ, {'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull})
        environment.start()
        self.addCleanup(environment.stop)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.command = self.root / '.agents/rules/p2p-code.md'
        self.command.parent.mkdir(parents=True)
        self.command.write_text('Review the accepted task.\n')
        self.git('add', '.agents/rules/p2p-code.md')
        self.git('commit', '-qm', 'base')
        self.git('update-ref', 'refs/remotes/origin/dev', self.git('rev-parse', 'HEAD'))
        self.git('checkout', '-qb', 'DEV-capitalism-slave-doc-fixture')
        self.command.write_text('Review every accepted task requirement.\n')
        self.git('commit', '-qam', 'docs')
        (self.root / '.git/info/exclude').write_text('.superpowers/\n')
        self.owner = self.root / '.superpowers/owner.jsonl'
        self.owner.parent.mkdir()
        self.owner.write_text(json.dumps({'type': 'session', 'id': 'doc-owner'}) + '\n' +
                              json.dumps({'type': 'message', 'message': {'role': 'user',
                                  'content': 'Update .agents/rules/p2p-code.md; open MR, do not merge.'}}) + '\n')
        rc.store_context(self.root, [self.owner])

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True).strip()

    def review(self, root, inputs, output, plan):
        self.assertTrue(plan, 'documentation must never enter the application implementation phase')
        self.assertIn(b'Review every accepted task requirement.', (output.parent / 'feature.diff').read_bytes())
        relative = str(self.command.relative_to(self.root))
        report = {'context_key': rc.load_context(root)['context_key'], 'coverage': [{
            'paths': [relative], 'scenario': 'command contract', 'findings': [],
            'verification': 'source-only fixture, not runtime',
            'inspected': [{'path': relative, 'revision': 'worktree', 'sha256': hashlib.sha256(self.command.read_bytes()).hexdigest()}],
            'comparisons': [], 'no_analog': 'Fixture contains only this prose command.'}]}
        output.write_text(json.dumps(report))

    def test_prose_command_uses_one_read_only_review_without_application_checks(self):
        current = f.snapshot(self.root)
        self.assertTrue(f.documentation_only(self.root, current))
        directory = f.directory(self.root)
        with patch.object(f, 'run_agent', side_effect=self.review) as agent, \
                patch.object(f, 'ci_requirements', return_value=set()), patch.object(f, 'checked') as checks:
            f.review_documentation(self.root, current, directory)
        self.assertEqual(agent.call_count, 1)
        checks.assert_not_called()
        self.assertTrue(f.current_receipt(self.root, current))
        receipt = json.loads((directory / 'receipt.json').read_text())
        proof = json.loads(Path(receipt['verification']).read_text())
        self.assertEqual(proof['profile'], 'documentation-only')
        self.assertEqual(proof['checks'], [])
        self.assertFalse(proof['ui']['required'])

    def test_executable_or_mixed_changes_do_not_get_the_prose_profile(self):
        self.command.chmod(0o755)
        self.git('add', '.agents/rules/p2p-code.md')
        self.git('commit', '-qm', 'executable')
        self.assertFalse(f.documentation_only(self.root, f.snapshot(self.root)))
        self.command.chmod(0o644)
        (self.root / 'helper.py').write_text('print("behavior")\n')
        self.git('add', 'helper.py', '.agents/rules/p2p-code.md')
        self.git('commit', '-qm', 'runtime helper')
        self.assertFalse(f.documentation_only(self.root, f.snapshot(self.root)))

    def test_operational_append_keeps_finalizer_policy_bytes_but_returns_latest_intent(self):
        original = rc.context_path(self.root).read_bytes()
        key = f.policy_key(self.root)
        with self.owner.open('a') as file:
            file.write(json.dumps({'type': 'message', 'message': {'role': 'user', 'content': 'Останови превью'}}) + '\n')
        rc.store_context(self.root, [self.owner])
        self.assertEqual(rc.context_path(self.root).read_bytes(), original)
        self.assertEqual(f.policy_key(self.root), key)
        self.assertEqual(rc.load_context(self.root)['operations'][0]['text'], 'Останови превью')


if __name__ == '__main__':
    unittest.main()
