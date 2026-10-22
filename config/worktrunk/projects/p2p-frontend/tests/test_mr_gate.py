#!/usr/bin/env python3
"""Native MR gate regressions at the forge/process boundary; never a real merge."""
import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
loader = importlib.machinery.SourceFileLoader('mr_command_gate', str(ROOT / 'mr-command'))
spec = importlib.util.spec_from_loader(loader.name, loader)
mr = importlib.util.module_from_spec(spec)
loader.exec_module(mr)


class MergeGateTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('/owned/p2p-task')
        self.branch = 'DEV-capitalism-slave-feature'
        self.sha = 'a' * 40
        self.current = {'branch': self.branch, 'head': self.sha, 'tree': 'b' * 40, 'target': 'c' * 40,
                        'merge_base': 'd' * 40, 'paths': ['lib/admin-layer/a.ts']}
        self.opened = {'iid': 42, 'source_branch': self.branch, 'target_branch': 'dev', 'sha': self.sha,
                       'state': 'opened', 'source_project_id': 1, 'target_project_id': 1}
        self.delivered = {**self.opened, 'state': 'merged', 'merge_commit_sha': 'e' * 40}
        for target, replacement in ((mr.finalizer, {'owned_root': self.root, 'refresh': None,
                                                    'snapshot': self.current, 'current_receipt': True,
                                                    'ci_requirements': {'Typecheck · Admin'}}),
                                    (mr, {'git': str(self.root), 'view': self.delivered,
                                          'require_batch_proof': None, 'wait_for_ci': {'sha': self.sha},
                                          'cleanup_remote': {'state': 'deleted'}})):
            for name, result in replacement.items():
                mocked = patch.object(target, name, return_value=result)
                setattr(self, name + '_mock', mocked.start())
                self.addCleanup(mocked.stop)
        self.call_patch = patch.object(mr.subprocess, 'call', return_value=0)
        self.call = self.call_patch.start()
        self.addCleanup(self.call_patch.stop)

    def test_missing_receipt_runs_finalizer_without_merging(self):
        self.current_receipt_mock.return_value = False
        self.assertEqual(mr.merge_feature(self.opened, ['42']), 0)
        self.assertEqual(self.call.call_args.args[0], [str(ROOT / 'feature-finalize'), '--mr', '42'])
        self.wait_for_ci_mock.assert_not_called()
        self.require_batch_proof_mock.assert_not_called()

    def test_valid_receipt_waits_ci_pins_merge_then_cleans_remote(self):
        self.assertEqual(mr.merge_feature(self.opened, ['42']), 0)
        self.wait_for_ci_mock.assert_called_once()
        args = self.call.call_args.args[0]
        self.assertIn('--sha=' + self.sha, args)
        self.assertIn('--remove-source-branch=false', args)
        self.assertIn('--auto-merge=false', args)
        self.assertEqual(self.call.call_count, 1)
        self.cleanup_remote_mock.assert_called_once_with(self.delivered)

    def test_keep_source_branch_does_not_clean_remote(self):
        self.assertEqual(mr.merge_feature(self.opened, ['42', '--keep-source-branch']), 0)
        self.cleanup_remote_mock.assert_not_called()

    def test_pending_cleanup_does_not_turn_confirmed_merge_into_failure(self):
        self.cleanup_remote_mock.side_effect = RuntimeError('source ref still has active pipeline consumers')
        self.assertEqual(mr.merge_feature(self.opened, ['42']), 0)
        self.assertEqual(self.call.call_count, 1)

    def test_hotfix_requires_review_unless_owner_explicitly_opts_out(self):
        self.current['branch'] = 'DEV-capitalism-slave-hotfix-one'
        self.opened['source_branch'] = self.current['branch']
        self.current_receipt_mock.return_value = False
        mr.merge_feature(self.opened, ['42'])
        self.current_receipt_mock.assert_called_once()
        self.wait_for_ci_mock.assert_not_called()
        self.assertEqual(self.call.call_args.args[0][0], str(ROOT / 'feature-finalize'))

    def test_failed_ci_never_calls_merge(self):
        self.wait_for_ci_mock.side_effect = RuntimeError('mandatory typecheck failed')
        with self.assertRaisesRegex(RuntimeError, 'typecheck'):
            mr.merge_feature(self.opened, ['42'])
        self.call.assert_not_called()

    def test_changed_target_after_ci_invalidates_merge(self):
        self.snapshot_mock.side_effect = [self.current, {**self.current, 'target': 'f' * 40}]
        with self.assertRaisesRegex(ValueError, 'moved'):
            mr.merge_feature(self.opened, ['42'])
        self.call.assert_not_called()

    def test_wrong_sha_or_rewrite_flag_refused_before_delivery(self):
        for args in (['42', '--sha=' + 'f' * 40], ['42', '--rebase'], ['42', '--squash']):
            with self.assertRaises(ValueError):
                mr.merge_feature(self.opened, args)
        self.call.assert_not_called()

    def test_successful_process_without_confirmed_merge_is_not_delivery(self):
        self.view_mock.return_value = self.opened
        with self.assertRaisesRegex(ValueError, 'not confirmed'):
            mr.merge_feature(self.opened, ['42'])

    def test_explicit_cross_project_flag_cannot_bypass_local_merge_gate(self):
        with self.assertRaisesRegex(ValueError, 'cross-project'):
            mr.main(['merge', '42', '--repo=common/frontend/frontend'])
        self.call.assert_not_called()

    def test_creation_preserves_source_even_if_old_default_requested_delete(self):
        self.assertEqual(mr.remove_source_args(['--remove-source-branch=true', '--title', 'feature']),
                         ['--title', 'feature', '--remove-source-branch=false'])


if __name__ == '__main__':
    unittest.main()
