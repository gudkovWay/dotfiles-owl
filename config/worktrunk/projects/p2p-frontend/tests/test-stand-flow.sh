#!/bin/sh
# Native temporary Git histories and the real CLI; no product install or live forge mutation.
set -eu
scripts=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export WT_STAND_SCRIPT="$scripts/stand"
export PYTHONDONTWRITEBYTECODE=1
exec python3 - "$@" <<'PY'
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

loader = importlib.machinery.SourceFileLoader('wt_stand', os.environ['WT_STAND_SCRIPT'])
spec = importlib.util.spec_from_loader(loader.name, loader)
stand = importlib.util.module_from_spec(spec)
loader.exec_module(stand)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


class Impact(unittest.TestCase):
    def test_multiple_roles_and_common_runtime(self):
        selected = stand.impact(['lib/admin-layer/a.vue', 'apps/payscrow-form/src/a.vue'])
        self.assertEqual(selected['roles'], ['admin', 'form'])
        self.assertEqual(stand.impact(['lib/common-layer/shared/a.ts'])['roles'], list(stand.ROLES))
        self.assertEqual(stand.impact(['package-lock.json', 'Dockerfile'])['roles'], list(stand.ROLES))

    def test_test_docs_and_ci_only_do_not_provision(self):
        selected = stand.impact(['docs/tech/a.md', 'README.md', '.gitlab-ci.yml',
                                 'lib/admin-layer/a.test.ts', 'lib/common-layer/vitest.setup.ts',
                                 'scripts/typecheck-app.sh'])
        self.assertEqual(selected['roles'], [])
        self.assertEqual(selected['unsupported'], [])

    def test_exchange_and_brand_specific_changes_are_not_disguised_as_psc(self):
        selected = stand.impact(['lib/form-layer/ui/exchange/a.vue',
                                 'apps/exchange-form/src/a.vue', 'apps/lucky-admin/src/a.vue'])
        self.assertEqual(selected['roles'], [])
        self.assertEqual(len(selected['unsupported']), 3)
        self.assertEqual(stand.impact(['lib/form-layer/ui/classic/a.vue'])['roles'], ['form'])

    def test_only_corresponding_helm_role_is_selected(self):
        self.assertEqual(stand.impact(['.kubernetes/values-template-provider.yaml'])['roles'], ['provider'])

    def test_payload_selects_one_wl_without_any_all_alias(self):
        flags = stand.deploy_variables(['admin', 'form', 'merchant', 'provider'])
        enabled = {item['key'] for item in flags if item['value'] == 'true'}
        self.assertEqual(enabled, {'GLA_DEPLOY_PSC_ADMIN', 'GLA_DEPLOY_PSC_FORM',
                                   'GLA_DEPLOY_PSC_MERCHANT', 'GLA_DEPLOY_PSC_PROVIDER'})
        self.assertTrue(all(item['value'] == 'false' for item in flags
                            if item['key'].startswith(('GLA_DEPLOY_ALL', 'GLA_DEPLOY_LP', 'GLA_DEPLOY_OCK'))))
        with self.assertRaises(stand.Refused):
            stand.deploy_variables(['lucky-admin'])

    def test_trace_unknown_is_not_an_empty_subscription(self):
        self.assertEqual(stand.trace_state('INFO Нет активных подписок slug=x'), 'none')
        self.assertEqual(stand.trace_state('INFO Повторное развёртывание подписанных whitelabel labels=psc'), 'psc')
        self.assertEqual(stand.trace_state('INFO Повторное развёртывание подписанных whitelabel labels="psc,lp"'), 'other')
        self.assertEqual(stand.trace_state('INFO Развёртывание целевых whitelabel labels=lp'), 'other')
        self.assertEqual(stand.trace_state('Job succeeded\n'), 'unknown')


class Forge:
    def __init__(self, fixture, current='none'):
        self.fixture = fixture
        self.current = current
        self.creates = []
        self.pipelines = []
        self.posts_fail = False
        self.remote_sha = None
        self.push_status = 'success'
        self.push_trace = None
        self.subscription_status = 'created'
        self.subscription_trace = 'INFO Развёртывание целевых whitelabel labels=psc'

    @property
    def sha(self):
        return self.remote_sha or git(self.fixture.tree, 'rev-parse', 'HEAD')

    def api(self, endpoint, method='GET', payload=None, raw=False):
        path = urlsplit(endpoint).path
        query = parse_qs(urlsplit(endpoint).query)
        if path.startswith('projects/40/repository/branches/'):
            return {'name': self.fixture.branch, 'commit': {'id': self.sha}}
        if path == 'projects/40/pipelines':
            source = query.get('source', [None])[0]
            sha = query.get('sha', [None])[0]
            native = {'id': 1, 'ref': self.fixture.branch, 'sha': self.sha, 'source': 'push',
                      'status': self.push_status, 'web_url': stand.WEB + '/-/pipelines/1'}
            rows = [native, *self.pipelines]
            return [row for row in rows if (not source or row['source'] == source)
                    and (not sha or row['sha'] == sha)]
        if path == 'projects/40/pipeline' and method == 'POST':
            self.creates.append(payload)
            if self.posts_fail:
                raise stand.Refused('request outcome unknown')
            pipeline = {'id': 2, 'ref': self.fixture.branch, 'sha': self.sha, 'source': 'api',
                        'status': 'pending', 'web_url': stand.WEB + '/-/pipelines/2'}
            self.pipelines.append(pipeline)
            return pipeline
        if path == 'projects/40/pipelines/1/jobs':
            return [{'id': 11, 'name': 'dyn-env state-check', 'status': self.push_status,
                     'finished_at': '2026-10-14T00:00:00Z' if self.push_status == 'success' else None}]
        if path == 'projects/40/pipelines/2/jobs':
            return [{'id': 22, 'name': 'dyn-env subscribe-and-deploy',
                     'status': self.subscription_status,
                     'finished_at': '2026-10-14T00:01:00Z' if self.subscription_status == 'success' else None},
                    {'id': 23, 'name': 'dyn-env stop', 'status': 'manual', 'finished_at': None}]
        if path == 'projects/40/pipelines/2/variables':
            return self.creates[-1]['variables']
        if path == 'projects/40/jobs/11/trace':
            if self.push_trace is not None:
                return self.push_trace
            return {'none': 'INFO Нет активных подписок slug=x',
                    'psc': 'INFO Повторное развёртывание подписанных whitelabel labels=psc',
                    'other': 'INFO Повторное развёртывание подписанных whitelabel labels="psc,lp"'}[self.current]
        if path == 'projects/40/jobs/22/trace':
            return self.subscription_trace
        raise AssertionError((endpoint, method))


class StandFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='wt-stand-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.environment = patch.dict(os.environ, {'HOME': str(self.home),
            'XDG_CONFIG_HOME': str(self.home / '.config'), 'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_CONFIG_GLOBAL': os.devnull, 'PYTHONDONTWRITEBYTECODE': '1'})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.repo = self.root / 'repo'
        self.tree = self.root / 'task'
        self.repo.mkdir()
        git(self.repo, 'init', '-q', '-b', 'dev')
        git(self.repo, 'config', 'user.name', 'Stand Test')
        git(self.repo, 'config', 'user.email', 'stand@example.invalid')
        git(self.repo, 'remote', 'add', 'origin', 'git@gitlab.psclp.org:common/frontend/frontend.git')
        (self.repo / 'package.json').write_text(json.dumps({'lint-staged': stand.batch.REVIEWED_TASKS}))
        git(self.repo, 'add', 'package.json')
        git(self.repo, 'commit', '-qm', 'base')
        git(self.repo, 'update-ref', 'refs/remotes/origin/dev', 'HEAD')
        self.branch = 'DEV-capitalism-slave-stand-fixture'
        git(self.repo, 'worktree', 'add', '-qb', self.branch, str(self.tree), 'dev')
        exclude = Path(git(self.repo, 'rev-parse', '--path-format=absolute', '--git-path', 'info/exclude'))
        with exclude.open('a') as file:
            file.write('\n.superpowers/\n')
        self.commit('lib/admin-layer/features/a.vue', '<template><p>fixture</p></template>\n')
        self.forge = Forge(self)
        self.subject = stand.Stand(self.tree, forge=self.forge, wait_seconds=0)

    def commit(self, path, content):
        target = self.tree / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        git(self.tree, 'add', path)
        git(self.tree, 'commit', '-qm', 'fixture ' + path)

    def test_plan_is_read_only_and_accumulates_commits(self):
        self.commit('lib/form-layer/ui/classic/a.vue', '<template><p>form</p></template>\n')
        result = self.subject.plan()
        self.assertEqual(result['roles'], ['admin', 'form'])
        self.assertFalse((self.tree / '.superpowers').exists())
        self.assertEqual(self.forge.creates, [])

    def test_rename_between_layers_and_deleted_files_select_both_roles(self):
        old = 'lib/admin-layer/features/a.vue'
        new = 'lib/merchant-layer/features/a.vue'
        (self.tree / new).parent.mkdir(parents=True)
        git(self.tree, 'mv', old, new)
        git(self.tree, 'commit', '-qm', 'move admin to merchant')
        self.assertEqual(self.subject.plan()['roles'], ['merchant'])
        # A deletion of a base file still selects the layer that lost it.
        self.commit('lib/admin-layer/features/base.vue', '<template><p>base</p></template>\n')
        git(self.repo, 'update-ref', 'refs/remotes/origin/dev', git(self.tree, 'rev-parse', 'HEAD'))
        git(self.tree, 'rm', '-q', 'lib/admin-layer/features/base.vue')
        git(self.tree, 'commit', '-qm', 'remove base component')
        self.assertEqual(self.subject.plan()['roles'], ['admin'])

    def test_empty_current_state_bootstraps_once_then_pending_is_reused(self):
        first = self.subject.ensure()
        self.assertEqual(first['status'], 'subscription-requested')
        self.assertEqual(len(self.forge.creates), 1)
        second = self.subject.ensure()
        self.assertEqual(second['status'], 'subscription-pending')
        self.assertEqual(len(self.forge.creates), 1)
        self.assertNotIn('CI_PIPELINE_SOURCE', {v['key'] for v in self.forge.creates[0]['variables']})

    def test_psc_native_push_redeploy_needs_no_api(self):
        self.forge.current = 'psc'
        result = self.subject.ensure()
        self.assertEqual(result['status'], 'psc-reused')
        self.assertEqual(self.forge.creates, [])

    def test_other_wl_is_never_replaced(self):
        self.forge.current = 'other'
        with self.assertRaises(stand.Refused):
            self.subject.ensure()
        self.assertEqual(self.forge.creates, [])

    def test_unknown_or_failed_state_check_does_not_create(self):
        self.forge.push_trace = 'Job succeeded'
        with self.assertRaises(stand.Refused):
            self.subject.ensure()
        self.forge.push_trace = None
        self.forge.push_status = 'failed'
        with self.assertRaises(stand.Refused):
            self.subject.ensure()
        self.assertEqual(self.forge.creates, [])

    def test_native_pipeline_not_ready_is_not_treated_as_no_subscription(self):
        self.forge.push_status = 'running'
        with self.assertRaises(stand.Refused):
            self.subject.ensure()
        self.assertEqual(self.forge.creates, [])

    def test_remote_sha_mismatch_refuses_mutation(self):
        self.forge.remote_sha = '0' * 40
        with self.assertRaises(stand.Refused):
            self.subject.ensure()
        self.assertEqual(self.forge.creates, [])

    def test_indeterminate_post_is_not_retried(self):
        self.forge.posts_fail = True
        with self.assertRaises(stand.Refused):
            self.subject.ensure()
        self.forge.posts_fail = False
        with self.assertRaises(stand.Refused):
            self.subject.ensure()
        self.assertEqual(len(self.forge.creates), 1)

    def test_failed_subscription_is_not_retried(self):
        self.subject.ensure()
        self.forge.subscription_status = 'failed'
        with self.assertRaises(stand.Refused):
            self.subject.ensure()
        self.assertEqual(len(self.forge.creates), 1)

    def test_failed_checks_do_not_leave_subscription_permanently_pending(self):
        self.subject.ensure()
        self.forge.pipelines[0]['status'] = 'failed'
        self.forge.subscription_status = 'skipped'
        with self.assertRaises(stand.Refused):
            self.subject.ensure()
        self.assertEqual(len(self.forge.creates), 1)

    def test_successful_subscription_is_reused_despite_manual_stop(self):
        self.subject.ensure()
        self.forge.subscription_status = 'success'
        result = self.subject.ensure()
        self.assertEqual(result['status'], 'psc-reused')
        self.assertFalse(result['stand_health_verified'])
        self.assertEqual(len(self.forge.creates), 1)

    def test_dirty_worktree_and_symlink_receipt_refuse(self):
        (self.tree / 'untracked.vue').write_text('x')
        with self.assertRaises((stand.Refused, stand.batch.Refused)):
            self.subject.ensure()
        (self.tree / 'untracked.vue').unlink()
        directory = self.tree / '.superpowers/stand'
        directory.mkdir(parents=True)
        (directory / 'state.json').symlink_to(self.root / 'outside')
        with self.assertRaises(stand.Refused):
            self.subject.ensure()
        self.assertEqual(self.forge.creates, [])

    def test_docs_only_and_unsupported_only_do_not_create(self):
        git(self.tree, 'rm', '-q', 'lib/admin-layer/features/a.vue')
        git(self.tree, 'commit', '-qm', 'revert runtime fixture')
        self.commit('docs/a.md', 'fixture documentation\n')
        self.assertEqual(self.subject.ensure()['status'], 'not-needed')
        self.commit('apps/lucky-admin/src/a.vue', '<template><p>brand</p></template>\n')
        self.assertEqual(self.subject.ensure()['status'], 'not-needed')
        self.assertEqual(self.forge.creates, [])

    def test_primary_integration_and_other_project_refuse(self):
        with self.assertRaises((stand.Refused, stand.batch.Refused)):
            stand.Stand(self.repo, forge=self.forge)
        git(self.repo, 'remote', 'set-url', 'origin', 'git@gitlab.psclp.org:ecom/frontend/frontend.git')
        with self.assertRaises((stand.Refused, stand.batch.Refused)):
            stand.Stand(self.tree, forge=self.forge)

    def test_wrong_gitlab_host_cannot_operate_on_the_real_psc_project(self):
        git(self.repo, 'remote', 'set-url', 'origin', 'git@example.invalid:common/frontend/frontend.git')
        with self.assertRaises(stand.Refused):
            stand.Stand(self.tree, forge=self.forge)

    def test_rename_of_a_base_file_selects_source_and_destination_layers(self):
        base = git(self.tree, 'rev-parse', 'HEAD')
        git(self.repo, 'update-ref', 'refs/remotes/origin/dev', base)
        new = 'lib/merchant-layer/features/a.vue'
        (self.tree / new).parent.mkdir(parents=True)
        git(self.tree, 'mv', 'lib/admin-layer/features/a.vue', new)
        git(self.tree, 'commit', '-qm', 'move base component')
        self.assertEqual(self.subject.plan()['roles'], ['admin', 'merchant'])

    def test_force_and_other_branch_publication_are_refused_before_git_push(self):
        for args in (['--force', 'origin', self.branch], ['origin', 'dev']):
            result = subprocess.run(['sh', str(stand.HERE / 'push'), *args],
                                    cwd=self.tree, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(json.loads(result.stdout)['push_succeeded'])
        self.assertFalse((self.tree / '.superpowers/stand/state.json').exists())

    def test_actual_plan_cli_and_worktrunk_alias_are_read_only(self):
        config = self.home / '.config/worktrunk/config.toml'
        config.parent.mkdir(parents=True)
        config.write_text('[projects."gitlab.psclp.org/common/frontend/frontend".aliases]\n'
                          'stand = ' + json.dumps('python3 ' + str(stand.HERE / 'stand') + ' {{ args }}') + '\n')
        result = subprocess.run(['wt', 'stand', '--', '--plan'], cwd=self.tree,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output['roles'], ['admin'])
        self.assertFalse((self.tree / '.superpowers').exists())

    def test_native_ordinary_publication_and_failed_push_preserve_scope(self):
        remote = self.root / 'remote.git'
        subprocess.run(['git', 'init', '--bare', '-q', str(remote)], check=True)
        git(self.repo, 'remote', 'add', 'fixture', str(remote))
        # Non-origin remotes use native publication but never PSC automation.
        result = subprocess.run(['sh', str(stand.HERE / 'push'), 'fixture', self.branch],
                                cwd=self.tree, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(git(remote, 'rev-parse', 'refs/heads/' + self.branch), git(self.tree, 'rev-parse', 'HEAD'))
        self.assertEqual(json.loads(result.stdout)['status'], 'publication-only')
        self.commit('lib/admin-layer/features/b.vue', '<template><p>b</p></template>\n')
        rejection = remote / 'hooks/pre-receive'
        rejection.write_text('#!/bin/sh\nexit 9\n')
        rejection.chmod(0o755)
        before = git(remote, 'rev-parse', 'refs/heads/' + self.branch)
        result = subprocess.run(['sh', str(stand.HERE / 'push'), 'fixture', self.branch],
                                cwd=self.tree, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(git(remote, 'rev-parse', 'refs/heads/' + self.branch), before)
        self.assertFalse((self.tree / '.superpowers/stand/state.json').exists())

    def test_registered_batch_cannot_fall_back_to_ordinary_push(self):
        remote = self.root / 'remote.git'
        subprocess.run(['git', 'init', '--bare', '-q', str(remote)], check=True)
        git(self.repo, 'remote', 'add', 'fixture', str(remote))
        self.subject.worktree.marker.parent.mkdir(parents=True)
        self.subject.worktree.marker.write_text(json.dumps({'schema': 1, 'branch': self.branch,
                                                          'root': str(self.tree)}))
        result = subprocess.run(['sh', str(stand.HERE / 'push'), 'fixture', self.branch],
                                cwd=self.tree, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(git(remote, 'for-each-ref', '--format=%(refname)'), '')

    def configure_live_cli_fixture(self):
        import shutil
        real_git = shutil.which('git')
        remote = self.root / 'forge.git'
        subprocess.run([real_git, 'init', '--bare', '-q', str(remote)], check=True)
        tools = self.root / 'bin'
        tools.mkdir()
        shim = tools / 'git'
        shim.write_text('#!/usr/bin/env python3\nimport os,sys\n'
                        'args=sys.argv[1:]\n'
                        'if args[:2]==["push","origin"]:\n'
                        '    args=["-c",' + repr('remote.origin.pushurl=' + str(remote)) + ',*args]\n'
                        'os.execv(' + repr(real_git) + ',["git",*args])\n')
        shim.chmod(0o755)
        state_path = self.root / 'forge-state.json'
        state_path.write_text(json.dumps({'creates': [], 'label': 'none',
            'native_finished': '2026-10-14T00:00:00Z', 'subscription_status': 'created'}))
        cli = tools / 'glab-fixture'
        code = r'''#!/usr/bin/env python3
import json,sys,subprocess
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
state_path=Path(STATE_PATH)
state=json.loads(state_path.read_text())
args=sys.argv[1:]
assert args[:3]==['api','--hostname','gitlab.psclp.org'],args
endpoint=args[3]
method=args[args.index('--method')+1]
path=urlsplit(endpoint).path
query=parse_qs(urlsplit(endpoint).query)
sha=subprocess.check_output([REAL_GIT,'-C',REMOTE,'rev-parse','refs/heads/'+BRANCH],text=True).strip()
native={'id':1,'ref':BRANCH,'sha':sha,'source':'push','status':'success',
        'web_url':WEB+'/-/pipelines/1'}
if path.startswith('projects/40/repository/branches/'):
    output={'name':BRANCH,'commit':{'id':sha}}
elif path=='projects/40/pipelines':
    rows=[native]+([state['pipeline']] if 'pipeline' in state else [])
    output=[row for row in rows if row['source']==query['source'][0]
            and ('sha' not in query or row['sha']==query['sha'][0])]
elif path=='projects/40/pipelines/1/jobs':
    output=[{'id':11,'name':'dyn-env state-check','status':'success',
             'finished_at':state['native_finished']}]
elif path=='projects/40/jobs/11/trace':
    print('INFO Нет активных подписок slug=fixture' if state['label']=='none' else
          'INFO Повторное развёртывание подписанных whitelabel labels=psc')
    sys.exit(0)
elif path=='projects/40/pipeline' and method=='POST':
    request=json.load(sys.stdin)
    assert request['ref']==BRANCH
    state['creates'].append(request)
    output={'id':2,'ref':BRANCH,'sha':sha,'source':'api','status':'pending',
            'web_url':WEB+'/-/pipelines/2'}
    state['pipeline']=output
    state_path.write_text(json.dumps(state))
    if state.get('post_fails'):
        sys.exit(2)
elif path=='projects/40/pipelines/2/jobs':
    output=[{'id':22,'name':'dyn-env subscribe-and-deploy','status':state['subscription_status'],
             'finished_at':'2026-10-14T00:01:00Z' if state['subscription_status']=='success' else None},
            {'id':23,'name':'dyn-env stop','status':'manual','finished_at':None}]
elif path=='projects/40/pipelines/2/variables':
    output=state['creates'][-1]['variables']
elif path=='projects/40/jobs/22/trace':
    print('INFO Развёртывание целевых whitelabel labels=psc')
    sys.exit(0)
else:
    raise AssertionError((path,method))
print(json.dumps(output))
'''
        constants = {'STATE_PATH': str(state_path), 'REAL_GIT': real_git,
                     'REMOTE': str(remote), 'BRANCH': self.branch, 'WEB': stand.WEB}
        code = code.replace('state_path=Path(STATE_PATH)',
                            '\n'.join(name + '=' + repr(value) for name, value in constants.items())
                            + '\nstate_path=Path(STATE_PATH)')
        cli.write_text(code)
        cli.chmod(0o755)
        config = self.home / '.config/worktrunk/config.toml'
        config.parent.mkdir(parents=True)
        config.write_text('[projects."gitlab.psclp.org/common/frontend/frontend".aliases]\n'
                          'push = ' + json.dumps('sh ' + str(stand.HERE / 'push') + ' {{ args }}') + '\n')
        environment = {**os.environ, 'PATH': str(tools) + os.pathsep + os.environ['PATH'],
                       'GLAB_BIN': str(cli)}
        return remote, state_path, environment

    def test_actual_wt_push_bootstraps_then_reuses_native_psc_deploy(self):
        remote, state_path, environment = self.configure_live_cli_fixture()
        def publish():
            return subprocess.run(['wt', 'push', '--', 'origin', self.branch], cwd=self.tree,
                                  env=environment, capture_output=True, text=True)
        first = publish()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        result = json.loads(first.stdout)
        self.assertTrue(result['push_succeeded'])
        self.assertEqual(result['status'], 'subscription-requested')
        self.assertEqual(git(remote, 'rev-parse', 'refs/heads/' + self.branch), result['sha'])
        state = json.loads(state_path.read_text())
        self.assertEqual(len(state['creates']), 1)
        enabled = {item['key'] for item in state['creates'][0]['variables'] if item['value']=='true'}
        self.assertEqual(enabled, {'GLA_DEPLOY_PSC_ADMIN'})
        duplicate = publish()
        self.assertEqual(duplicate.returncode, 0, duplicate.stdout + duplicate.stderr)
        self.assertEqual(json.loads(duplicate.stdout)['status'], 'subscription-pending')
        state.update(label='psc', subscription_status='success',
                     native_finished='2026-10-14T00:02:00Z')
        state_path.write_text(json.dumps(state))
        self.commit('lib/admin-layer/features/b.vue', '<template><p>next push</p></template>\n')
        updated = publish()
        self.assertEqual(updated.returncode, 0, updated.stdout + updated.stderr)
        self.assertEqual(json.loads(updated.stdout)['status'], 'psc-reused')
        self.assertEqual(len(json.loads(state_path.read_text())['creates']), 1)
        self.assertEqual(git(remote, 'rev-parse', 'refs/heads/' + self.branch),
                         git(self.tree, 'rev-parse', 'HEAD'))

    def test_actual_wt_push_reports_publication_even_when_api_outcome_is_unknown(self):
        remote, state_path, environment = self.configure_live_cli_fixture()
        state = json.loads(state_path.read_text())
        state['post_fails'] = True
        state_path.write_text(json.dumps(state))
        result = subprocess.run(['wt', 'push', '--', 'origin', self.branch], cwd=self.tree,
                                env=environment, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(json.loads(result.stdout)['push_succeeded'])
        self.assertEqual(git(remote, 'rev-parse', 'refs/heads/' + self.branch),
                         git(self.tree, 'rev-parse', 'HEAD'))
        self.assertEqual(json.loads((self.tree / '.superpowers/stand/state.json').read_text())['phase'],
                         'creating')


unittest.main(verbosity=2)
PY
