#!/usr/bin/env python3
"""Exercise source deletion against a private bare origin; substitute only forge state."""
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(HERE))
loader = importlib.machinery.SourceFileLoader('mr_remote_cleanup', str(HERE / 'mr-command'))
spec = importlib.util.spec_from_loader(loader.name, loader)
mr = importlib.util.module_from_spec(spec)
loader.exec_module(mr)


class RemoteCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'source'
        self.root.mkdir()
        self.origin = Path(self.tmp.name) / 'origin.git'
        env = patch.dict(os.environ, {'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull})
        env.start()
        self.addCleanup(env.stop)
        self.git('init', '-q', '--bare', str(self.origin))
        self.git('init', '-q', '-b', 'dev')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Test')
        self.git('remote', 'add', 'origin', str(self.origin))
        (self.root / 'feature.txt').write_text('merged feature\n')
        self.git('add', 'feature.txt')
        self.git('commit', '-qm', 'feature')
        self.sha = self.git('rev-parse', 'HEAD')
        self.branch = 'DEV-capitalism-slave-cleanup-fixture'
        self.git('branch', self.branch)
        self.git('push', '-q', 'origin', 'dev', self.branch)
        self.value = {'iid': 42, 'source_branch': self.branch, 'target_branch': 'dev',
                      'sha': self.sha, 'state': 'merged', 'merged_at': '2026-10-22',
                      'source_project_id': 1, 'target_project_id': 1, 'merge_commit_sha': self.sha}
        trees = patch.object(mr, 'worktrees', return_value=[{'worktree': str(self.root)}])
        trees.start()
        self.addCleanup(trees.stop)
        idle = patch.object(mr, 'assert_ref_idle')
        self.idle = idle.start()
        self.addCleanup(idle.stop)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True, stderr=subprocess.DEVNULL).strip()

    def remote(self):
        return self.git('ls-remote', '--heads', 'origin', 'refs/heads/' + self.branch)

    def test_deletes_only_remote_source_after_confirmed_merge_and_idle_consumers(self):
        self.assertEqual(mr.cleanup_remote(self.value)['state'], 'deleted')
        self.assertEqual(self.remote(), '')
        self.assertEqual(self.git('rev-parse', self.branch), self.sha)
        self.assertTrue((self.root / 'feature.txt').exists())
        self.idle.assert_called_once_with(self.root, self.branch)

    def test_active_pipeline_preserves_source(self):
        self.idle.side_effect = RuntimeError('active pipeline consumers')
        with self.assertRaisesRegex(RuntimeError, 'active pipeline'):
            mr.cleanup_remote(self.value)
        self.assertTrue(self.remote().startswith(self.sha))

    def test_advanced_remote_source_is_not_deleted(self):
        (self.root / 'feature.txt').write_text('new unpublished scope\n')
        self.git('commit', '-qam', 'new feature')
        self.git('push', '-q', 'origin', 'HEAD:refs/heads/' + self.branch)
        advanced = self.git('rev-parse', 'HEAD')
        with self.assertRaisesRegex(mr.Deferred, 'advanced'):
            mr.cleanup_remote(self.value)
        self.assertTrue(self.remote().startswith(advanced))
        self.idle.assert_not_called()

    def test_unconfirmed_merge_cannot_delete(self):
        for changed in ({'state': 'opened'}, {'merged_at': None}, {'target_branch': 'main'}):
            with self.assertRaisesRegex(ValueError, 'confirmed'):
                mr.cleanup_remote({**self.value, **changed})
        self.assertTrue(self.remote())

    def test_already_deleted_source_is_idempotent(self):
        mr.cleanup_remote(self.value)
        self.idle.reset_mock()
        self.assertEqual(mr.cleanup_remote(self.value)['state'], 'deleted')
        self.idle.assert_not_called()

    def test_fork_or_protected_branch_is_never_deleted(self):
        for changed in ({'source_project_id': 2}, {'source_branch': 'dev'}):
            with self.assertRaises(ValueError):
                mr.cleanup_remote({**self.value, **changed})
        self.assertTrue(self.remote())


if __name__ == '__main__':
    unittest.main()
