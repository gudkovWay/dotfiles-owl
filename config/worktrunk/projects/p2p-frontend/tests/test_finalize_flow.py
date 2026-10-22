#!/usr/bin/env python3
"""Real temporary Git trees through finalization; only model/check/forge boundaries substituted."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import feature_finalize as f


class FinalizationFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.git('init', '-q')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Test')
        (self.root / '.claude/commands').mkdir(parents=True)
        (self.root / '.claude/commands/refactor.md').write_text('fixture architecture')
        (self.root / 'a.ts').write_text('base\n')
        self.git('add', 'a.ts', '.claude/commands/refactor.md')
        self.git('commit', '-qm', 'base')
        self.base = self.git('rev-parse', 'HEAD')
        self.git('update-ref', 'refs/remotes/origin/dev', self.base)
        self.branch = 'DEV-capitalism-slave-finalizer-fixture'
        self.git('checkout', '-qb', self.branch)
        (self.root / 'a.ts').write_text('feature\n')
        self.git('commit', '-qam', 'feature')
        (self.root / '.git/info/exclude').write_text('.superpowers/\n')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True).strip()

    def test_plan_refactor_verify_atomic_commit_push_ci_merge_and_report(self):
        trace, remote, state = [], [], {'opened': False, 'merged': False}
        original_run = subprocess.run
        root = self.root
        branch = self.branch
        def source_mr():
            return {'iid': 42, 'source_branch': branch, 'target_branch': 'dev', 'sha': self.git('rev-parse', 'HEAD'),
                    'state': 'merged' if state['merged'] else 'opened', 'source_project_id': 1, 'target_project_id': 1}
        class FakeForge:
            def __init__(self, _root):
                pass
            def pages(self, _path):
                return [source_mr()] if state['opened'] else []
            def mr(self, _iid):
                return source_mr()
        def agent(_root, inputs, output, plan):
            trace.append('plan' if plan else 'refactor')
            output.write_text('actual test boundary output')
            if not plan:
                (root / 'a.ts').write_text('refactored\n')
                (output.parent / 'implementation.json').write_text(json.dumps({
                    'commits': [{'message': 'refactor(admin): improve feature', 'paths': ['a.ts']}],
                    'tests': [], 'fixed': ['fixture change'], 'backend': ['fixture handoff'],
                    'warnings': [], 'blockers': [], 'ui': {'required': False}}))
        def verify(_root, current, manifest, _run):
            trace.append('verify')
            self.assertEqual((root / 'a.ts').read_text(), 'refactored\n')
            self.assertIsNone(current['tree'])  # Verification precedes staging/commit.
            return {'source': current, 'checks': [], 'ui': manifest['ui']}
        def run(command, **kwargs):
            if command[:2] == ['wt', 'commit']:
                self.assertEqual(trace[-1], 'verify')
                trace.append('commit')
                return original_run(['git', 'commit', '-qm', command[-1]], **kwargs)
            if command[:2] == ['wt', 'push']:
                trace.append('push')
                remote[:] = [self.git('rev-parse', 'HEAD')]
                return subprocess.CompletedProcess(command, 0)
            if command[:3] == ['wt', 'mr', '--']:
                if command[3] == 'create':
                    trace.append('create')
                    state['opened'] = True
                elif command[3] == 'merge':
                    trace.append('merge')
                    self.assertTrue(f.current_receipt(root))
                    state['merged'] = True
                    original_run(['git', 'update-ref', 'refs/remotes/origin/dev', self.git('rev-parse', 'HEAD')], cwd=root, check=True)
                return subprocess.CompletedProcess(command, 0)
            if command[0] == 'git' and 'ls-remote' in command:
                return subprocess.CompletedProcess(command, 0, stdout=remote[0] + '\trefs/heads/' + branch)
            return original_run(command, **kwargs)
        def ci(*args):
            trace.append('ci')
            return {'sha': self.git('rev-parse', 'HEAD')}
        with patch.object(f, 'owned_root', return_value=root), patch.object(f, 'refresh'), patch.object(f, 'ci_requirements', return_value=set()), patch.object(f, 'Forge', FakeForge), patch.object(f, 'run_agent', side_effect=agent), patch.object(f, 'verify_local', side_effect=verify), patch.object(f, 'wait_for_ci', side_effect=ci), patch.object(f.subprocess, 'run', side_effect=run):
            self.assertEqual(f.finish(root), 0)
        self.assertEqual(trace, ['plan', 'refactor', 'verify', 'commit', 'push', 'create', 'ci', 'merge'])
        self.assertEqual(self.git('log', '-1', '--format=%s'), 'refactor(admin): improve feature')
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertTrue(root.exists())
        self.assertEqual(self.git('branch', '--show-current'), branch)
        report = json.loads((root / '.superpowers/finalize/delivery.json').read_text())
        self.assertEqual(report['state'], 'merged')
        self.assertTrue(report['source_preserved'])
        self.assertEqual(report['sha'], remote[0])
        human = next((root / '.superpowers/finalize').glob('*/report.md')).read_text()
        self.assertIn('fixture handoff', human)
        self.assertIn('Merged в `dev`: MR !42', human)
        self.assertNotIn('Pending:', human)

    def test_failed_sol_phase_does_not_retry_push_or_create_receipt(self):
        with patch.object(f, 'owned_root', return_value=self.root), patch.object(f, 'refresh'), patch.object(f, 'find_mr', return_value=None), patch.object(f, 'run_agent', side_effect=RuntimeError('resource timeout; no retry')) as agent:
            with self.assertRaisesRegex(RuntimeError, 'timeout'):
                f.finish(self.root)
        self.assertEqual(agent.call_count, 1)
        self.assertFalse((self.root / '.superpowers/finalize/receipt.json').exists())
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_owner_opt_out_still_requires_native_proof_and_records_no_sol(self):
        current = f.snapshot(self.root)
        path = f.directory(self.root)
        manifest = path / 'owner-manifest.json'
        manifest.write_text(json.dumps({'commits': [], 'tests': [], 'fixed': [], 'backend': [],
                                        'warnings': [], 'blockers': [], 'ui': {'required': False}}))
        with patch.object(f, 'verify_local', return_value={'source': current, 'checks': []}) as verify:
            f.owner_opt_out(self.root, current, path, manifest, 'owner: skip Sol for this task')
            verify.assert_called_once()
        receipt = json.loads((path / 'receipt.json').read_text())
        proof = json.loads(Path(receipt['verification']).read_text())
        self.assertEqual(proof['sol']['status'], 'not-run')
        self.assertTrue(f.current_receipt(self.root))
        (self.root / 'a.ts').write_text('new source')
        self.assertFalse(f.current_receipt(self.root, f.snapshot(self.root, allow_dirty=True)))

    def test_skip_sol_without_explicit_reason_or_manifest_is_refused(self):
        for reason, manifest in ((None, None), (' ', None), ('skip', None)):
            with self.assertRaisesRegex(RuntimeError, 'requires'):
                f.owner_opt_out(self.root, f.snapshot(self.root), f.directory(self.root), manifest, reason)

    def test_failed_opt_out_verification_does_not_create_receipt(self):
        path = f.directory(self.root)
        manifest = path / 'owner-manifest.json'
        manifest.write_text(json.dumps({'commits': [], 'tests': [], 'fixed': [], 'backend': [],
                                        'warnings': [], 'blockers': [], 'ui': {'required': False}}))
        with patch.object(f, 'verify_local', side_effect=RuntimeError('native checks failed')):
            with self.assertRaisesRegex(RuntimeError, 'native checks failed'):
                f.owner_opt_out(self.root, f.snapshot(self.root), path, manifest, 'skip Sol')
        self.assertFalse((path / 'receipt.json').exists())


if __name__ == '__main__':
    unittest.main()
