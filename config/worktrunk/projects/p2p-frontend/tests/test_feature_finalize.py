#!/usr/bin/env python3
"""Finite native unittest: branch review and forge gates, no live LLM/forge."""
import importlib
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


class BranchTests(unittest.TestCase):
    def setUp(self):
        self.f = importlib.import_module('feature_finalize')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        environment = patch.dict(os.environ, {'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull})
        environment.start()
        self.addCleanup(environment.stop)
        self.git('init', '-q')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Test')
        (self.root / 'a.ts').write_text('base\n')
        self.git('add', 'a.ts')
        self.git('commit', '-qm', 'base')
        self.base = self.git('rev-parse', 'HEAD')
        self.git('update-ref', 'refs/remotes/origin/dev', self.base)
        self.git('checkout', '-qb', 'DEV-capitalism-slave-example')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True).strip()

    def test_full_feature_diff_contains_all_commits_not_just_unpushed_tail(self):
        (self.root / 'a.ts').write_text('first\n')
        self.git('commit', '-qam', 'first')
        self.git('update-ref', 'refs/remotes/origin/DEV-capitalism-slave-example', self.git('rev-parse', 'HEAD'))
        (self.root / 'b.ts').write_text('second\n')
        self.git('add', 'b.ts')
        self.git('commit', '-qm', 'second')
        value = self.f.snapshot(self.root)
        self.assertEqual(set(value['paths']), {'a.ts', 'b.ts'})
        diff = self.f.feature_diff(self.root, value)
        self.assertIn(b'first', diff)
        self.assertIn(b'second', diff)
        self.assertEqual(value['merge_base'], self.base)

    def test_hotfix_is_precise_not_a_substring_escape(self):
        self.assertTrue(self.f.hotfix('DEV-capitalism-slave-hotfix-dialog'))
        self.assertFalse(self.f.hotfix('DEV-capitalism-slave-not-hotfix-dialog'))
        self.assertFalse(self.f.hotfix('DEV-capitalism-slave-fix-dialog'))

    def test_dirty_worktree_blocks_review(self):
        (self.root / 'a.ts').write_text('dirty\n')
        with self.assertRaisesRegex(RuntimeError, 'clean'):
            self.f.snapshot(self.root)

    def test_receipt_requires_head_base_policy_and_verification_content(self):
        current = self.f.snapshot(self.root)
        report = self.root / 'verification.json'
        report.write_text('{}')
        receipt = self.f.receipt_for(current, 'policy', report)
        self.assertTrue(self.f.receipt_matches(receipt, current, 'policy', report))
        for key in ('head', 'tree', 'target', 'merge_base', 'source_key'):
            changed = {**current, key: '0' * 40}
            self.assertFalse(self.f.receipt_matches(receipt, changed, 'policy', report))
        self.assertFalse(self.f.receipt_matches(receipt, current, 'new-policy', report))
        report.write_text('{"changed":true}')
        self.assertFalse(self.f.receipt_matches(receipt, current, 'policy', report))

    def test_agent_uses_exact_model_high_and_no_tool_delegation(self):
        command = self.f.agent_command(self.root, [self.root / 'input.md'], plan=True)
        self.assertIn('--model=openai-codex/gpt-6.1-sol', command)
        self.assertIn('--thinking=high', command)
        self.assertIn('--no-prewalk', command)
        self.assertIn('--no-extensions', command)
        tools = next(arg for arg in command if arg.startswith('--tools='))
        self.assertEqual(tools, '--tools=read,glob,grep')
        command = self.f.agent_command(self.root, [], plan=False)
        tools = next(arg for arg in command if arg.startswith('--tools='))
        self.assertNotIn('task', tools)
        self.assertNotIn('ask', tools)

    def test_manifest_requires_every_refactor_file_in_one_atomic_topic(self):
        manifest = {'commits': [{'message': 'refactor(admin): simplify dialog', 'paths': ['lib/admin-layer/x.ts']}],
                    'tests': [], 'fixed': [], 'backend': [], 'warnings': [], 'blockers': [], 'ui': {'required': False}}
        self.f.validate_manifest(self.root, manifest, ['lib/admin-layer/x.ts'])
        for paths in ([], ['lib/admin-layer/x.ts', 'other.ts']):
            with self.assertRaises(RuntimeError):
                self.f.validate_manifest(self.root, manifest, paths)
        manifest['blockers'] = ['unresolved frontend correctness issue']
        with self.assertRaisesRegex(RuntimeError, 'blockers'):
            self.f.validate_manifest(self.root, manifest, ['lib/admin-layer/x.ts'])
        manifest['blockers'] = []
        manifest['commits'][0]['paths'].append('.superpowers/private.json')
        with self.assertRaises(RuntimeError):
            self.f.validate_manifest(self.root, manifest, ['lib/admin-layer/x.ts', '.superpowers/private.json'])

    def test_test_selection_cannot_be_an_arbitrary_command_or_whole_suite(self):
        for value in ({'layer': 'admin', 'files': []},
                      {'layer': 'admin', 'files': ['../../secret.test.ts']},
                      {'layer': 'admin', 'files': ['lib/admin-layer/a.ts']},
                      {'layer': 'admin', 'files': ['lib/common-layer/a.test.ts']}):
            with self.assertRaises(RuntimeError):
                self.f.test_commands(self.root, [value])

    def test_primary_checkout_is_not_an_automatic_delivery_target(self):
        with self.assertRaisesRegex(RuntimeError, 'linked'):
            self.f.owned_root(self.root)

    def test_foreign_origin_is_refused_even_in_a_linked_tree(self):
        self.git('remote', 'add', 'origin', 'https://example.invalid/foreign/repository.git')
        tree = self.root / 'linked'
        self.git('worktree', 'add', '--detach', '-q', str(tree), 'HEAD')
        with self.assertRaisesRegex(RuntimeError, 'p2p origin'):
            self.f.owned_root(tree)

    def test_integration_branch_is_refused_in_a_linked_tree(self):
        self.git('remote', 'add', 'origin', 'git@gitlab.psclp.org:common/frontend/frontend.git')
        self.git('branch', 'dev', self.base)
        tree = self.root / 'linked'
        self.git('worktree', 'add', '-q', str(tree), 'dev')
        with self.assertRaisesRegex(RuntimeError, 'DEV task branch'):
            self.f.owned_root(tree)

    def test_source_key_survives_commit_but_not_changed_runtime_bytes(self):
        (self.root / 'new.ts').write_text('new bytes\n')
        before = self.f.source_key(self.root)
        self.git('add', 'new.ts')
        self.git('commit', '-qm', 'new')
        self.assertEqual(self.f.source_key(self.root), before)
        (self.root / 'new.ts').write_text('different\n')
        self.assertNotEqual(self.f.source_key(self.root), before)

    def test_zero_oom_metrics_do_not_misclassify_actual_type_errors(self):
        command = [sys.executable, '-c', 'import json; print("error TS2304: broken symbol"); print(json.dumps({"oom_kill": 0})); raise SystemExit(1)']
        with self.assertRaises(self.f.CheckFailed) as failure:
            self.f.checked(self.root, command, self.root / 'check.log')
        self.assertTrue(failure.exception.source)

    def test_resource_kill_never_qualifies_for_source_correction(self):
        command = [sys.executable, '-c', 'print(\"error TS2304: old diagnostic\"); print(\"heap out of memory\"); raise SystemExit(137)']
        with self.assertRaises(self.f.CheckFailed) as failure:
            self.f.checked(self.root, command, self.root / 'check.log')
        self.assertFalse(failure.exception.source)

    def test_check_restores_only_its_tracked_nuxtrc_mutation_and_stops(self):
        (self.root / '.nuxtrc').write_text('original config\n')
        self.git('add', '.nuxtrc')
        self.git('commit', '-qm', 'config')
        command = [sys.executable, '-c', 'from pathlib import Path; Path(\".nuxtrc\").write_text(\"mutated\")']
        with self.assertRaisesRegex(self.f.CheckFailed, 'nuxtrc') as failure:
            self.f.checked(self.root, command, self.root / 'check.log')
        self.assertEqual((self.root / '.nuxtrc').read_text(), 'original config\n')
        self.assertFalse(failure.exception.source)


CI = '''Tests · Admin:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes: &changes-admin
        - lib/admin-layer/**/*
        - lib/common-layer/**/*
  script:
    - npm run test:admin
Typecheck · Admin:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes: &changes-typecheck-admin
        - lib/admin-layer/**/*
        - apps/*-admin/**/*
  script:
    - ./scripts/typecheck-app.sh payscrow-admin 0
'''


class CIGateTests(unittest.TestCase):
    def setUp(self):
        self.c = importlib.import_module('merge_readiness')

    def test_ci_selection_matches_direct_and_nested_files(self):
        for path in ('lib/admin-layer/a.ts', 'lib/admin-layer/features/x/a.vue'):
            self.assertEqual(self.c.required_jobs(CI, [path]), {'Tests · Admin', 'Typecheck · Admin'})
        self.assertEqual(self.c.required_jobs(CI, ['apps/lucky-admin/src/a.vue']), {'Typecheck · Admin'})
        self.assertEqual(self.c.required_jobs(CI, ['README.md']), set())

    def test_changed_ci_selector_format_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, 'changes'):
            self.c.required_jobs(CI.replace('changes: &changes-admin', 'changes: *unknown'), ['lib/admin-layer/a.ts'])

    def test_pipeline_sha_and_success_are_required(self):
        good = {'sha': 'a' * 40, 'status': 'success'}
        jobs = [{'name': 'Tests · Admin', 'status': 'success', 'allow_failure': False}]
        self.c.check_pipeline(good, jobs, 'a' * 40, {'Tests · Admin'})
        for pipeline in ({**good, 'sha': 'b' * 40}, {**good, 'status': 'running'}, {**good, 'status': 'failed'}):
            with self.assertRaises(RuntimeError):
                self.c.check_pipeline(pipeline, jobs, 'a' * 40, {'Tests · Admin'})

    def test_missing_skipped_canceled_and_allow_failure_jobs_never_pass(self):
        pipeline = {'sha': 'a' * 40, 'status': 'success'}
        for status in ('skipped', 'canceled', 'manual', 'failed', 'running'):
            with self.assertRaises(RuntimeError):
                self.c.check_pipeline(pipeline, [{'name': 'Typecheck · Admin', 'status': status, 'allow_failure': False}], 'a' * 40, {'Typecheck · Admin'})
        for jobs in ([], [{'name': 'Typecheck · Admin', 'status': 'success', 'allow_failure': True}]):
            with self.assertRaises(RuntimeError):
                self.c.check_pipeline(pipeline, jobs, 'a' * 40, {'Typecheck · Admin'})

    def test_empty_job_pipeline_is_not_green_proof(self):
        with self.assertRaisesRegex(RuntimeError, 'empty'):
            self.c.check_pipeline({'sha': 'a' * 40, 'status': 'success'}, [], 'a' * 40, set())

    def test_automatic_merge_preserves_source_and_pins_sha(self):
        args = self.c.merge_args('42', 'a' * 40)
        self.assertIn('--sha=' + 'a' * 40, args)
        self.assertIn('--remove-source-branch=false', args)
        self.assertNotIn('--auto-merge', args)


if __name__ == '__main__':
    unittest.main()
