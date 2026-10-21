#!/bin/sh
# Native temporary Git histories; no real forge, install or product build.
set -eu
scripts=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export WT_BATCH_SCRIPT="$scripts/batch"
export PYTHONDONTWRITEBYTECODE=1
exec python3 - "$@" <<'PY'
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

loader = importlib.machinery.SourceFileLoader('wt_batch', os.environ['WT_BATCH_SCRIPT'])
spec = importlib.util.spec_from_loader(loader.name, loader)
batch = importlib.util.module_from_spec(spec)
loader.exec_module(batch)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


class BatchFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='wt-batch-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        # No personal Git hooks, signing, aliases or Husky init in fixtures.
        self.home = self.root / 'home'
        self.home.mkdir()
        self.environment = patch.dict(os.environ, {
            'HOME': str(self.home), 'XDG_CONFIG_HOME': str(self.home / '.config'),
            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.repo = self.root / 'repo'
        self.tree = self.root / 'task'
        self.repo.mkdir()
        git(self.repo, 'init', '-q', '-b', 'dev')
        git(self.repo, 'config', 'user.name', 'Batch Test')
        git(self.repo, 'config', 'user.email', 'batch@example.invalid')
        git(self.repo, 'remote', 'add', 'origin', 'git@gitlab.psclp.org:common/frontend/frontend.git')
        self.hooks = self.repo / 'reviewed-hooks'
        self.hooks.mkdir()
        hook = self.hooks / 'pre-commit'
        hook.write_text('#!/bin/sh\nnpx lint-staged --allow-empty\n')
        hook.chmod(0o755)
        (self.repo / 'package.json').write_text(json.dumps({'lint-staged': batch.REVIEWED_TASKS}))
        (self.repo / 'package-lock.json').write_text('{"lockfileVersion":3,"packages":{}}')
        (self.repo / 'eslint.config.mjs').write_text('export default []\n')
        git(self.repo, 'add', 'package.json', 'package-lock.json', 'eslint.config.mjs')
        git(self.repo, 'commit', '-qm', 'base')
        # Ephemeral linked fixture only; permanent user worktrees use Worktrunk.
        git(self.repo, 'worktree', 'add', '-qb', 'DEV-capitalism-slave-batch-fixture', str(self.tree), 'dev')
        git(self.repo, 'config', 'core.hooksPath', str(self.hooks))
        exclude = Path(git(self.repo, 'rev-parse', '--path-format=absolute', '--git-path', 'info/exclude'))
        with exclude.open('a') as file:
            file.write('\n.superpowers/\nreviewed-hooks/\n')
        self.b = batch.Batch(self.tree)

    def begin(self):
        with self.b.lock():
            self.b.begin('dev')

    def commit(self, name='first file.js', text='const first = 1;\n'):
        (self.tree / name).write_text(text)
        git(self.tree, 'add', '--', name)
        with self.b.lock():
            self.assertEqual(self.b.commit(['-qm', 'fix(admin): fixture']), 0)

    def verify(self, fix=False, fail=False):
        selected = []
        def lint(revision):
            selected.extend(git(self.tree, 'diff', '--name-only', '--diff-filter=ACMR', revision).splitlines())
            if fix:
                (self.tree / 'first file.js').write_text('const first = 2;\n')
                git(self.tree, 'add', '--', 'first file.js')
            if fail:
                raise batch.Refused('lint failure')
        # Substitute only external guard/environment/linter boundaries; state,
        # Git tree evidence and delivery transitions are the real implementation.
        with patch.object(self.b, 'prepare_environment'), patch.object(self.b, 'environment_key', return_value='ready'), patch.object(self.b, 'run_lint', side_effect=lint):
            with self.b.lock():
                result = self.b.verify_inside()
        return result, selected

    def check(self):
        with patch.object(self.b, 'environment_key', return_value='ready'):
            with self.b.lock():
                return self.b.check()

    def test_multiple_atomic_commits_and_cumulative_selection(self):
        self.begin()
        self.commit()
        self.commit('second.js', 'const second = 2;\n')
        self.assertEqual(git(self.tree, 'rev-list', '--count', 'dev..HEAD'), '2')
        result, selected = self.verify()
        self.assertEqual(result, 0)
        self.assertEqual(set(selected), {'first file.js', 'second.js'})
        self.check()
        self.assertEqual(git(self.repo, 'config', 'core.hooksPath'), str(self.hooks))

    def test_non_precommit_hook_still_blocks(self):
        self.begin()
        hook = self.hooks / 'commit-msg'
        observed = self.root / 'commit-msg-ran'
        hook.write_text('#!/bin/sh\nprintf ran > ' + shlex.quote(str(observed)) + '\nexit 9\n')
        hook.chmod(0o755)
        # Explicit refresh reviews the new forward-only hook, not a new pre-commit.
        with self.b.lock():
            self.b.begin('dev', refresh=True)
        before = git(self.tree, 'rev-parse', 'HEAD')
        (self.tree / 'first file.js').write_text('const first = 1;\n')
        git(self.tree, 'add', '--', 'first file.js')
        with self.b.lock():
            self.assertNotEqual(self.b.commit(['-qm', 'blocked']), 0)
        self.assertEqual(git(self.tree, 'rev-parse', 'HEAD'), before)
        self.assertEqual(observed.read_text(), 'ran')

    def test_unknown_precommit_is_not_deferred(self):
        (self.hooks / 'pre-commit').write_text('#!/bin/sh\nsecurity-check\nnpx lint-staged --allow-empty\n')
        with self.b.lock(), self.assertRaises(batch.Refused):
            self.b.begin('dev')
        self.assertFalse(self.b.state_path.exists())

    def test_ordinary_commit_keeps_failing_precommit(self):
        # Real wrapper and Git hooks; only preparation is fixture-ready. The
        # guard remains the installed executor inside this test's capped scope.
        tools = self.root / 'tools'
        scripts = tools / 'p2p-frontend'
        scripts.mkdir(parents=True)
        for name in ('batch', 'commit'):
            (scripts / name).write_bytes((batch.HERE / name).read_bytes())
        environment = tools / 'project-environment'
        environment.write_text('#!/bin/sh\nexit 0\n')
        environment.chmod(0o755)
        guard = tools / 'guarded-run'
        guard.write_text('#!/bin/sh\nexec ' + shlex.quote(str(batch.GUARD)) + ' "$@"\n')
        guard.chmod(0o755)
        observed = self.root / 'ordinary-precommit-ran'
        (self.hooks / 'pre-commit').write_text('#!/bin/sh\nprintf ran > ' + shlex.quote(str(observed)) + '\nexit 9\n')
        before = self.b.head()
        (self.tree / 'ordinary.js').write_text('const ordinary = 1;\n')
        git(self.tree, 'add', 'ordinary.js')
        result = subprocess.run(['sh', str(scripts / 'commit'), '-qm', 'ordinary'], cwd=self.tree)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(observed.read_text(), 'ran')
        self.assertEqual(self.b.head(), before)
        self.assertFalse(self.b.marker.exists())

    def test_additional_lint_staged_configuration_requires_review(self):
        self.begin()
        nested = self.tree / 'nested'
        nested.mkdir()
        config = nested / '.lintstagedrc.json'
        config.write_text('{}\n')
        git(self.tree, 'add', str(config))
        with self.b.lock(), self.assertRaises(batch.Refused):
            self.b.commit(['-qm', 'unreviewed lint config'])
        git(self.tree, 'reset', '-q', '--', str(config))
        config.unlink()
        package = nested / 'package.json'
        package.write_text(json.dumps({'lint-staged': {'*.js': 'extra-check'}}))
        git(self.tree, 'add', str(package))
        with self.b.lock(), self.assertRaises(batch.Refused):
            self.b.commit(['-qm', 'unreviewed nested tasks'])

    def test_dirty_begin_and_integration_branch_are_refused(self):
        (self.tree / 'untracked.js').write_text('x\n')
        with self.b.lock(), self.assertRaises(batch.Refused):
            self.b.begin('dev')
        (self.tree / 'untracked.js').unlink()
        with self.assertRaises(batch.Refused):
            batch.Batch(self.repo)

    def test_missing_failed_and_dirty_proof_cannot_pass(self):
        self.begin()
        self.commit()
        with self.assertRaises(batch.Refused):
            self.check()
        with self.assertRaises(batch.Refused):
            self.verify(fail=True)
        with self.assertRaises(batch.Refused):
            self.check()
        self.verify()
        (self.tree / 'first file.js').write_text('const first = 99;\n')
        with self.assertRaises(batch.Refused):
            self.check()

    def test_autofix_needs_commit_but_exact_tree_packaging_reuses_proof(self):
        self.begin()
        self.commit()
        result, selected = self.verify(fix=True)
        self.assertEqual(result, batch.NEEDS_COMMIT)
        with self.assertRaises(batch.Refused):
            self.check()
        with self.b.lock():
            self.assertEqual(self.b.commit(['-qm', 'style(admin): checked fixes']), 0)
        self.check()
        self.assertEqual((self.tree / 'first file.js').read_text(), 'const first = 2;\n')
        self.assertEqual(self.b.load()['receipt']['head'], git(self.tree, 'rev-parse', 'HEAD'))

    def test_different_correction_or_amend_cannot_reuse_proof(self):
        self.begin()
        self.commit()
        self.verify(fix=True)
        self.commit(text='const first = 3;\n')
        with self.assertRaises(batch.Refused):
            self.check()
        self.verify()
        with self.b.lock():
            self.assertEqual(self.b.commit(['--amend', '--no-edit']), 0)
        with self.assertRaises(batch.Refused):
            self.check()

    def test_changed_base_and_deleted_state_cannot_pass(self):
        self.begin()
        self.commit()
        self.verify()
        git(self.repo, 'update-ref', 'refs/heads/dev', git(self.tree, 'rev-parse', 'HEAD'))
        with self.assertRaises(batch.Refused):
            self.check()
        self.b.state_path.unlink()
        with self.assertRaises(batch.Refused):
            batch.check_source(self.repo, self.b.branch)

    def test_rename_delete_empty_diff_and_malformed_state(self):
        self.begin()
        result, selected = self.verify()
        self.assertEqual((result, selected), (0, []))
        self.commit('old.js', 'const old = 1;\n')
        git(self.tree, 'mv', 'old.js', 'new name.js')
        with self.b.lock():
            self.assertEqual(self.b.commit(['-qm', 'rename']), 0)
        result, selected = self.verify()
        self.assertEqual(selected, ['new name.js'])
        git(self.tree, 'rm', '-q', 'new name.js')
        with self.b.lock():
            self.assertEqual(self.b.commit(['-qm', 'delete']), 0)
        result, selected = self.verify()
        self.assertEqual(selected, [])
        self.b.state_path.write_text('{}')
        with self.assertRaises(batch.Refused):
            self.check()

    def test_verified_push_only_updates_explicit_local_remote_ref(self):
        self.begin()
        self.commit()
        remote = self.root / 'remote.git'
        subprocess.run(['git', 'init', '--bare', '-q', str(remote)], check=True)
        git(self.repo, 'remote', 'add', 'fixture', str(remote))
        with self.assertRaises(batch.Refused):
            with self.b.lock():
                self.b.push(['fixture', self.b.branch])
        self.assertEqual(git(remote, 'for-each-ref', '--format=%(refname)'), '')
        self.verify()
        rejection = remote / 'hooks/pre-receive'
        observed = self.root / 'push-rejected'
        rejection.write_text('#!/bin/sh\nprintf ran > ' + shlex.quote(str(observed)) + '\nexit 9\n')
        rejection.chmod(0o755)
        with patch.object(self.b, 'environment_key', return_value='ready'):
            with self.b.lock():
                self.assertNotEqual(self.b.push(['fixture', self.b.branch]), 0)
        self.assertEqual(observed.read_text(), 'ran')
        self.assertTrue(self.b.load()['active'])
        self.assertEqual(git(remote, 'for-each-ref', '--format=%(refname)'), '')
        rejection.unlink()
        with patch.object(self.b, 'environment_key', return_value='ready'):
            with self.b.lock():
                self.assertEqual(self.b.push(['fixture', self.b.branch]), 0)
        self.assertEqual(git(remote, 'rev-parse', 'refs/heads/' + self.b.branch), git(self.tree, 'rev-parse', 'HEAD'))
        with self.assertRaises(batch.Refused):
            with self.b.lock():
                self.b.push(['--all'])


    def test_commit_cli_keeps_message_values_and_does_not_prepare(self):
        self.begin()
        (self.tree / 'cli.js').write_text('const cli = 1;\n')
        git(self.tree, 'add', 'cli.js')
        message = '--no-verify is message text, not a Git option'
        result = subprocess.run(['sh', str(batch.HERE / 'commit'), '-m', message], cwd=self.tree)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(git(self.tree, 'log', '-1', '--format=%s'), message)
        self.assertFalse((self.tree / 'node_modules').exists())

    def test_mr_source_sha_and_missing_source_worktree_are_refused(self):
        self.begin()
        self.commit()
        self.verify()
        with patch.object(batch.Batch, 'environment_key', return_value='ready'):
            batch.check_source(self.repo, self.b.branch, self.b.head())
            with self.assertRaises(batch.Refused):
                batch.check_source(self.repo, self.b.branch, '0' * 40)
            self.b.marker.write_text(json.dumps({'schema': batch.SCHEMA, 'branch': self.b.branch, 'root': str(self.root / 'missing')}))
            with self.assertRaises((batch.Refused, subprocess.SubprocessError)):
                batch.check_source(self.repo, self.b.branch)

    @unittest.skipUnless(os.environ.get('WT_BATCH_RUNTIME') == '1', 'real linter CLI scenario is explicitly selected')
    def test_actual_batch_cli_and_installed_formatters(self):
        # Read-only installed tool code; fixture node_modules/.nuxt are owned,
        # not linked writable trees. No install and no Nuxt/app build.
        installed = Path('/home/q/dev/work/p2p-frontend/node_modules')
        node_modules = self.tree / 'node_modules'
        bin_dir = node_modules / '.bin'
        bin_dir.mkdir(parents=True)
        for name in ('lint-staged', 'prettier', 'eslint', 'stylelint'):
            metadata = json.loads((installed / name / 'package.json').read_text())
            target = node_modules / name
            target.mkdir()
            (target / 'package.json').write_text(json.dumps(metadata))
            if name == 'lint-staged':
                (target / 'bin').mkdir()
                real_cli = installed / name / 'bin/lint-staged.js'
                trace = self.tree / '.superpowers/batch/lint-runs'
                (target / 'bin/lint-staged.js').write_text(
                    "import { appendFileSync } from 'node:fs';\n"
                    + 'appendFileSync(' + json.dumps(str(trace)) + ', ' + json.dumps('run\n') + ');\n'
                    + 'await import(' + json.dumps(str(real_cli)) + ');\n')
            else:
                entry = metadata['bin']
                if isinstance(entry, dict):
                    entry = entry[name]
                proxy = bin_dir / name
                proxy.write_text('#!/bin/sh\nexec node ' + shlex.quote(str(installed / name / entry)) + ' \"$@\"\n')
                proxy.chmod(0o755)
        generated = self.tree / 'apps/payscrow-admin/.nuxt'
        generated.mkdir(parents=True)
        (generated / 'eslint.config.mjs').write_text('export default [];\n')
        (node_modules / '.omp-environment.json').write_text('{\"fixture\":\"owned-ready-environment\"}\n')
        with Path(git(self.repo, 'rev-parse', '--path-format=absolute', '--git-path', 'info/exclude')).open('a') as file:
            file.write('node_modules/\napps/payscrow-admin/.nuxt/\n')
        projects = self.home / '.config/worktrunk/projects'
        projects.mkdir(parents=True)
        # Only the environment bootstrap is a fixture. The guard proxy calls
        # the real shared executor; resource membership is never mocked here.
        guard = projects / 'guarded-run'
        guard.write_text('#!/bin/sh\nexec ' + shlex.quote(str(batch.GUARD)) + ' \"$@\"\n')
        guard.chmod(0o755)
        environment = projects / 'project-environment'
        environment.write_text('#!/usr/bin/env python3\nimport json\nprint(json.dumps(' + repr({
            'dependencies': 'ready', 'generated': 'ready',
            'required_generated': ['apps/payscrow-admin/.nuxt/eslint.config.mjs'],
        }) + '))\n')
        environment.chmod(0o755)
        config = self.home / '.config/worktrunk/config.toml'
        config.write_text('[projects.\"gitlab.psclp.org/common/frontend/frontend\".aliases]\n'
                          'batch = ' + json.dumps(shlex.quote(str(batch.HERE / 'batch')) + ' {{ args }}') + '\n'
                          'commit = ' + json.dumps('sh ' + shlex.quote(str(batch.HERE / 'commit')) + ' {{ args }}') + '\n')
        git(self.repo, 'config', 'worktrunk.default-branch', 'dev')
        def wt(*args):
            return subprocess.run(['wt', *args], cwd=self.tree, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        result = wt('batch', '--', 'begin', '--base', 'dev')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name in ('early.js', 'later.js'):
            (self.tree / name).write_text('const item={answer:1}\n')
            git(self.tree, 'add', name)
            result = wt('commit', '--', '-m', 'fix(admin): ' + name)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = wt('batch', '--', 'verify')
        self.assertEqual(result.returncode, batch.NEEDS_COMMIT, result.stdout + result.stderr)
        for name in ('early.js', 'later.js'):
            self.assertEqual((self.tree / name).read_text(), 'const item = { answer: 1 };\n')
        result = wt('batch', '--', 'check')
        self.assertNotEqual(result.returncode, 0)
        result = wt('commit', '--', '-m', 'style(admin): checked formatting')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = wt('batch', '--', 'check')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('prettier', result.stdout + result.stderr)
        self.assertEqual(self.b.load()['receipt']['head'], git(self.tree, 'rev-parse', 'HEAD'))
        self.assertEqual((self.tree / '.superpowers/batch/lint-runs').read_text(), 'run\n')


    def test_fresh_husky_worktree_needs_no_install_and_accepts_reviewed_dispatchers(self):
        husky = self.tree / '.husky'
        husky.mkdir()
        (husky / 'pre-commit').write_text('npx lint-staged --allow-empty\n')
        git(self.tree, 'add', '.husky/pre-commit')
        git(self.tree, '-c', 'core.hooksPath=' + str(self.root / 'seed-hooks'), 'commit', '-qm', 'tracked hook')
        git(self.repo, 'config', 'core.hooksPath', '.husky/_')
        with Path(git(self.repo, 'rev-parse', '--path-format=absolute', '--git-path', 'info/exclude')).open('a') as file:
            file.write('.husky/_/\n')
        self.begin()
        self.commit()
        self.assertFalse((self.tree / 'node_modules').exists())
        generated = husky / '_'
        generated.mkdir()
        (generated / 'h').write_text(batch.HUSKY_DISPATCH)
        (generated / 'pre-commit').write_text(batch.HUSKY_ENTRY.removesuffix('\n'))
        (generated / 'pre-commit').chmod(0o755)
        self.verify()
        self.check()
        (generated / 'pre-commit').write_text(batch.HUSKY_ENTRY)
        self.check()
        (generated / 'pre-commit').write_text(batch.HUSKY_ENTRY + 'exit 0\n')
        with self.assertRaises(batch.Refused):
            self.check()
        (generated / 'pre-commit').write_text(batch.HUSKY_ENTRY)
        (generated / 'h').write_text('unreviewed dispatcher\n')
        with self.assertRaises(batch.Refused):
            self.check()

    def test_pending_git_operation_init_and_concurrent_command_are_refused(self):
        (self.b.gitdir / 'MERGE_HEAD').write_text(self.b.head() + '\n')
        with self.b.lock(), self.assertRaises(batch.Refused):
            self.b.begin('dev')
        (self.b.gitdir / 'MERGE_HEAD').unlink()
        init = self.home / '.config/husky/init.sh'
        init.parent.mkdir(parents=True)
        init.write_text('exit 0\n')
        with self.b.lock(), self.assertRaises(batch.Refused):
            self.b.begin('dev')
        init.unlink()
        self.begin()
        with self.b.lock(), self.assertRaises(batch.Refused):
            with batch.Batch(self.tree).lock():
                pass

    def test_retirement_preserves_existing_source_and_allows_completed_cleanup(self):
        self.begin()
        self.commit()
        with self.assertRaises(batch.Refused):
            batch.retire_registration(self.repo, self.b.branch)
        self.assertTrue(self.b.marker.exists())
        remote = self.root / 'common/frontend/frontend.git'
        remote.parent.mkdir(parents=True)
        subprocess.run(['git', 'init', '--bare', '-q', str(remote)], check=True)
        git(self.repo, 'remote', 'set-url', 'origin', str(remote))
        git(self.repo, 'worktree', 'remove', str(self.tree))
        git(self.repo, 'branch', '-D', self.b.branch)
        batch.retire_registration(self.repo, self.b.branch)
        self.assertFalse(self.b.marker.exists())

    def test_mr_command_refuses_unverified_batch_before_forge_mutation(self):
        self.begin()
        self.commit()
        forge = self.root / 'forge'
        mutation = self.root / 'forge-mutation'
        metadata = {'source_branch': self.b.branch, 'sha': self.b.head(),
                    'target_branch': 'dev', 'source_project_id': 1, 'target_project_id': 1}
        forge.write_text('#!/usr/bin/env python3\nimport json,sys\nfrom pathlib import Path\n'
                         'if sys.argv[1:3] == [\"mr\", \"view\"]:\n'
                         '    print(json.dumps(' + repr(metadata) + '))\n'
                         'elif sys.argv[1:3] in ([\"mr\", \"create\"], [\"mr\", \"merge\"]):\n'
                         '    Path(' + repr(str(mutation)) + ').write_text(\"remote mutation\")\n')
        forge.chmod(0o755)
        for args in (['create', '--target-branch', 'dev', '--source-branch', self.b.branch], ['merge', '1']):
            result = subprocess.run(['python3', str(batch.HERE / 'mr-command'), *args], cwd=self.tree,
                                    env={**os.environ, 'GLAB_BIN': str(forge)}, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('no successful cumulative hook proof', result.stdout + result.stderr)
            self.assertFalse(mutation.exists())


unittest.main(verbosity=2)
PY
