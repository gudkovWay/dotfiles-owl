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
import review_contract as rc


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
        (self.root / '.agents/rules').mkdir(parents=True)
        (self.root / '.agents/rules/p2p-code.md').write_text('fixture architecture')
        (self.root / 'a.ts').write_text('base\n')
        self.git('add', 'a.ts', '.agents/rules/p2p-code.md')
        self.git('commit', '-qm', 'base')
        self.base = self.git('rev-parse', 'HEAD')
        self.git('update-ref', 'refs/remotes/origin/dev', self.base)
        self.branch = 'DEV-capitalism-slave-finalizer-fixture'
        self.git('checkout', '-qb', self.branch)
        (self.root / 'a.ts').write_text('feature\n')
        self.git('commit', '-qam', 'feature')
        (self.root / '.git/info/exclude').write_text('.superpowers/\n')
        (self.root / '.superpowers').mkdir()
        session = self.root / '.superpowers/owner.jsonl'
        session.write_text(json.dumps({'type': 'session', 'id': 'fixture-owner'}) + '\n' +
                           json.dumps({'type': 'message', 'message': {'role': 'user', 'content': 'Improve this feature; open MR, no merge by default.'}}) + '\n')
        rc.store_context(self.root, [session])

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True).strip()

    def test_default_finalization_stops_at_open_mr_without_merge(self):
        self.run_flow(False)

    def test_explicit_merge_keeps_the_existing_ci_and_receipt_gates(self):
        self.run_flow(True)

    def test_owner_correction_during_ci_invalidates_delivery_receipt(self):
        self.run_flow(False, owner_changes=True)

    def test_ui_handoff_resumes_without_repeating_model_phases(self):
        self.run_flow(False, ui=True)

    def test_hook_mutation_requires_fresh_ui_without_repeating_commit_or_model(self):
        self.run_flow(False, ui=True, hook_change=True)

    def test_never_started_checks_resume_without_repeating_model_or_completed_checks(self):
        self.run_flow(False, deferred=True)

    def test_source_assertion_gets_one_bounded_correction(self):
        self.run_flow(False, source_failure=True)

    def test_rebased_published_conflicting_draft_is_reviewed_before_exact_lease_push(self):
        self.run_flow(False, published=True, rebased=True)

    def run_flow(self, merge, owner_changes=False, ui=False, hook_change=False, deferred=False, source_failure=False, published=False, rebased=False, remote_changes=False):
        trace, remote, state = [], [], {'opened': published, 'merged': False, 'hook_changed': False, 'checks_failed': False}
        if published:
            remote.append(self.git('rev-parse', 'HEAD'))
        expected_remote = remote[0] if rebased else None
        if rebased:
            self.git('checkout', '--detach', '-q', self.base)
            (self.root / 'base.ts').write_text('dev advanced\n')
            self.git('add', 'base.ts')
            self.git('commit', '-qm', 'dev advanced')
            self.git('update-ref', 'refs/remotes/origin/dev', self.git('rev-parse', 'HEAD'))
            self.git('checkout', '-q', self.branch)
            self.git('rebase', 'origin/dev')
        original_run, native_verify = subprocess.run, f.verify_local
        check_steps = []
        root = self.root
        branch = self.branch
        def source_mr():
            return {'iid': 42, 'source_branch': branch, 'target_branch': 'dev', 'sha': remote[0] if remote else self.git('rev-parse', 'HEAD'),
                    'state': 'merged' if state['merged'] else 'opened', 'source_project_id': 1, 'target_project_id': 1,
                    'draft': published, 'has_conflicts': published and remote[0] != self.git('rev-parse', 'HEAD'),
                    'merge_when_pipeline_succeeds': False, 'web_url': 'https://forge.invalid/mr/42'}
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
                    'warnings': [], 'blockers': [], 'ui': {'required': ui, 'status': 'pending'},
                    'test_selection': 'Fixture changes have no affected native application tests.',
                    'review': {'context_key': rc.load_context(root)['context_key'], 'coverage': [{
                        'paths': ['a.ts'], 'scenario': 'feature value', 'inspected': [{
                            'path': 'a.ts', 'revision': 'worktree', 'sha256': f.sha256(root / 'a.ts')}],
                        'comparisons': [], 'no_analog': 'Fixture has only one source file; no analogous flow.',
                        'findings': [], 'verification': 'Native tests selected; no UI change.'}]}}))
        def verify(_root, current, manifest, _run):
            trace.append('verify')
            expected = 'hook-refactored\n' if state['hook_changed'] else 'refactored\n'
            self.assertEqual((root / 'a.ts').read_text(), expected)
            if 'commit' not in trace:
                self.assertIsNone(current['tree'])
            if deferred:
                return native_verify(_root, current, manifest, _run)
            if source_failure and not state['checks_failed']:
                state['checks_failed'] = True
                raise f.CheckFailed('fixture native source assertion', source=True)
            return {'source': current, 'checks': [], 'ui': manifest['ui']}
        def checked(_root, command, log, env=None, report=None):
            step = 'prepare' if 'project-environment' in command[0] else 'typecheck'
            check_steps.append(step)
            if step == 'typecheck' and not state['checks_failed']:
                state['checks_failed'] = True
                raise f.CheckFailed('fixture admission refused before workload', kind='deferred')
            log.write_text('completed ' + step)
            return {'command': command, 'exit': 0, 'log': str(log), 'sha256': f.sha256(log)}
        def run(command, **kwargs):
            if command[:2] == ['wt', 'commit']:
                self.assertEqual(trace[-1], 'verify')
                trace.append('commit')
                if hook_change:
                    (root / 'a.ts').write_text('hook-refactored\n')
                    original_run(['git', 'add', 'a.ts'], cwd=root, check=True)
                    state['hook_changed'] = True
                return original_run(['git', 'commit', '-qm', command[-1]], **kwargs)
            if command[:2] == ['wt', 'push']:
                trace.append('push')
                if rebased:
                    self.assertEqual(command, ['wt', 'push', '--',
                        '--force-with-lease=refs/heads/' + branch + ':' + expected_remote, 'origin', branch])
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
                return subprocess.CompletedProcess(command, 0, stdout=(remote[0] + '\trefs/heads/' + branch) if remote else '')
            if command[:3] == ['git', 'fetch', 'origin']:
                (root / '.git/FETCH_HEAD').write_text(remote[0] + '\n')
                return subprocess.CompletedProcess(command, 0)
            return original_run(command, **kwargs)
        def ci(*args, **kwargs):
            self.assertEqual(kwargs, {'require_mergeable': merge})
            trace.append('ci')
            if owner_changes:
                with (root / '.superpowers/owner.jsonl').open('a') as journal:
                    journal.write(json.dumps({'type': 'message', 'message': {
                        'role': 'user', 'content': 'Preserve the established reference; do not replace the ID presentation.'}}) + '\n')
            return {'sha': self.git('rev-parse', 'HEAD')}
        def tip(*args):
            if remote_changes and 'verify' in trace:
                return 'f' * 40
            return remote[0] if remote else None
        with patch.object(f, 'owned_root', return_value=root), patch.object(f, 'refresh'), patch.object(f, 'ci_requirements', return_value={'Typecheck · Admin'} if deferred else set()), patch.object(f, 'Forge', FakeForge), patch.object(f, 'run_agent', side_effect=agent), patch.object(f, 'verify_local', side_effect=verify), patch.object(f, 'checked', side_effect=checked), patch.object(f, 'wait_for_ci', side_effect=ci), patch.object(f, 'remote_tip', side_effect=tip), patch.object(f.subprocess, 'run', side_effect=run):
            if remote_changes:
                with self.assertRaisesRegex(RuntimeError, 'remote tip changed during review'):
                    f.finish(root, expected_remote_sha=expected_remote)
                self.assertNotIn('push', trace)
                self.assertFalse((root / '.superpowers/finalize/delivery.json').exists())
                return
            if owner_changes:
                with self.assertRaisesRegex(RuntimeError, 'owner context changed'):
                    f.finish(root)
                self.assertNotIn('merge', trace)
                self.assertFalse((root / '.superpowers/finalize/delivery.json').exists())
                self.assertEqual(self.git('branch', '--show-current'), branch)
                return
            if ui:
                self.assertEqual(f.finish(root), 0)
                self.assertEqual(trace, ['plan', 'refactor', 'verify', 'commit'] + (['verify'] if hook_change else []))
                self.assertFalse((root / '.superpowers/finalize/receipt.json').exists())
                run_dir = next((root / '.superpowers/finalize').glob('*-????????????'))
                proof_path = run_dir / 'ui-proof.json'
                screenshot = root / '.superpowers/owned-fixture.png'
                screenshot.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\0' * 8 + b'\0\0\0\x01' * 2)
                refreshed = json.loads((run_dir / 'implementation.json').read_text())['review']
                refreshed['coverage'][0]['inspected'][0]['sha256'] = f.sha256(root / 'a.ts')
                proof_path.write_text(json.dumps({'ui': {'required': True, 'status': 'verified',
                    'runtime_key': f.runtime_key(root), 'scenarios': ['owned fixture interaction'],
                    'screenshots': [str(screenshot)]}, 'review': refreshed}))
                self.assertEqual(f.finish(root, resume=run_dir, ui_proof=proof_path), 0)
            elif deferred:
                self.assertEqual(f.finish(root), 0)
                self.assertEqual(trace, ['plan', 'refactor', 'verify'])
                run_dir = next((root / '.superpowers/finalize').glob('*-????????????'))
                self.assertEqual(json.loads((run_dir / 'state.json').read_text())['phase'], 'awaiting_checks')
                self.assertEqual(f.finish(root, resume=run_dir), 0)
                self.assertEqual(check_steps, ['prepare', 'typecheck', 'typecheck'])
            else:
                self.assertEqual(f.finish(root, merge=merge, expected_remote_sha=expected_remote), 0)
        expected = ['plan', 'refactor']
        if source_failure:
            expected += ['verify', 'refactor']
        elif deferred:
            expected += ['verify']
        expected += ['verify', 'commit']
        if hook_change:
            expected += ['verify']
        expected += ['push'] + ([] if published else ['create']) + ['ci'] + (['merge'] if merge else [])
        self.assertEqual(trace, expected)
        self.assertEqual(self.git('log', '-1', '--format=%s'), 'refactor(admin): improve feature')
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertTrue(root.exists())
        self.assertEqual(self.git('branch', '--show-current'), branch)
        report = json.loads((root / '.superpowers/finalize/delivery.json').read_text())
        self.assertEqual(report['state'], 'merged' if merge else 'mr-ready')
        self.assertTrue(report['source_preserved'])
        self.assertEqual(report['sha'], remote[0])
        human = next((root / '.superpowers/finalize').glob('*/report.md')).read_text()
        self.assertIn('fixture handoff', human)
        self.assertIn('Merged в `dev`: MR !42' if merge else 'MR !42 открыт; merge не выполнялся', human)
        self.assertNotIn('Pending:', human)

    def test_failed_sol_phase_does_not_retry_push_or_create_receipt(self):
        with patch.object(f, 'owned_root', return_value=self.root), patch.object(f, 'refresh'), patch.object(f, 'find_mr', return_value=None), patch.object(f, 'remote_tip', return_value=None), patch.object(f, 'run_agent', side_effect=RuntimeError('resource timeout; no retry')) as agent:
            with self.assertRaisesRegex(RuntimeError, 'timeout'):
                f.finish(self.root)
        self.assertEqual(agent.call_count, 1)
        self.assertFalse((self.root / '.superpowers/finalize/receipt.json').exists())
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_remote_movement_during_review_blocks_publication(self):
        self.run_flow(False, published=True, rebased=True, remote_changes=True)

    def test_resume_preserves_exact_lease_and_rejects_omission_or_replacement(self):
        run = self.root / '.superpowers/finalize/run'
        run.mkdir(parents=True)
        for name in ('source.json', 'feature.diff', 'code-rules.md', 'review-context.json', 'plan.md', 'implementation.json'):
            (run / name).write_text('{}')
        expected = 'a' * 40
        f.await_ui(self.root, run, 'policy', 0, expected_remote_sha=expected)
        current = f.snapshot(self.root, allow_dirty=True)
        self.assertEqual(f.load_resume(self.root, run.parent, run, current, 'policy', expected)[0], run)
        for replacement in (None, 'b' * 40):
            with self.assertRaisesRegex(RuntimeError, 'drift'):
                f.load_resume(self.root, run.parent, run, current, 'policy', replacement)

    def test_resume_rejects_source_policy_artifact_and_failed_state_drift(self):
        run = self.root / '.superpowers/finalize/run'
        run.mkdir(parents=True)
        for name in ('source.json', 'feature.diff', 'code-rules.md', 'review-context.json', 'plan.md', 'implementation.json'):
            (run / name).write_text('{}')
        f.await_ui(self.root, run, 'policy', 0)
        current = f.snapshot(self.root, allow_dirty=True)
        self.assertEqual(f.load_resume(self.root, run.parent, run, current, 'policy')[0], run)
        for source, policy in (({**current, 'source_key': 'changed'}, 'policy'), (current, 'new-policy')):
            with self.assertRaisesRegex(RuntimeError, 'drift'):
                f.load_resume(self.root, run.parent, run, source, policy)
        (run / 'plan.md').write_text('changed')
        with self.assertRaisesRegex(RuntimeError, 'artifact drift'):
            f.load_resume(self.root, run.parent, run, current, 'policy')
        state = json.loads((run / 'state.json').read_text())
        state['phase'] = 'failed'
        f.save(run / 'state.json', state)
        with self.assertRaisesRegex(RuntimeError, 'cannot be replayed'):
            f.load_resume(self.root, run.parent, run, current, 'policy')

    def test_resume_rejects_symlink_and_foreign_directory(self):
        parent = self.root / '.superpowers/finalize'
        parent.mkdir()
        foreign = self.root / '.superpowers/foreign'
        foreign.mkdir()
        link = parent / 'linked'
        link.symlink_to(foreign, target_is_directory=True)
        for run in (foreign, link):
            with self.assertRaisesRegex(RuntimeError, 'owned direct run'):
                f.load_resume(self.root, parent, run, {}, 'policy')


if __name__ == '__main__':
    unittest.main()
