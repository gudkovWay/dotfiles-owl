#!/usr/bin/env python3
"""Checklist lifecycle, durable identity and exact-payload publication."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TEAM = 'b53538a0-3a86-47b8-a5b8-14dd5af97428'
HEAD = 'a' * 40
SOURCE = {'head': HEAD, 'key': 'source-one', 'clean': True}


def intake():
    return {'work_id': 'cascade', 'owner_requests': ['Убрать старый вид и прыжок поиска'],
            'outcomes': [{'id': 'legacy', 'text': 'Убрать старый вид в двух вкладках'},
                         {'id': 'search', 'text': 'Исправить прыжок поиска при смене вкладок'}]}


def draft(task):
    return {'request_key': task['request_key'], 'title': 'Каскад: вид и поиск',
            'outcomes': copy.deepcopy(task['request']['outcomes'])}


def issue(description, state='In Progress'):
    return {'id': 'FRONT-99999', 'uuid': 'test-issue', 'title': 'Каскад: вид и поиск',
            'description': description, 'status': state, 'teamId': TEAM,
            'priority': 2, 'assignee': 'human'}


class LinearWorkflowTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('linear_workflow'), 'p2p Linear workflow is not implemented')
        import linear_workflow
        return linear_workflow

    def task(self):
        module = self.module()
        state = module.empty_registry()
        task = module.enter(state, 'DEV-capitalism-slave-cascade', intake())
        return module, state, task

    def test_enter_restores_same_work_item_without_revision_churn(self):
        module, state, task = self.task()
        again = module.enter(state, 'DEV-capitalism-slave-cascade', intake())
        self.assertEqual(again, task)
        self.assertEqual(len(state['tasks']), 1)
        self.assertEqual(again['revision'], 1)

    def test_changed_scope_invalidates_draft_approval_but_preserves_issue_binding(self):
        module, state, task = self.task()
        task['issue'] = 'test-issue'
        task['approval'] = 'old-approval'
        updated = intake()
        updated['outcomes'][1]['text'] = 'Исправить поиск и очистку'
        revised = module.enter(state, 'DEV-capitalism-slave-cascade', updated)
        self.assertEqual(revised['revision'], 2)
        self.assertEqual(revised['issue'], 'test-issue')
        self.assertIsNone(revised['approval'])

    def test_question_and_empty_scope_do_not_create_work_items(self):
        module = self.module()
        for value in ({'owner_requests': ['Что такое cron?'], 'outcomes': []},
                      {'owner_requests': [], 'outcomes': intake()['outcomes']}):
            with self.assertRaises(ValueError):
                module.enter(module.empty_registry(), 'DEV-capitalism-slave-task', value)

    def test_editor_cannot_invent_preservation_or_test_outcomes(self):
        module, _, task = self.task()
        value = draft(task)
        value['outcomes'].append({'id': 'preserve', 'text': 'Сохранить поведение модалки'})
        with self.assertRaisesRegex(ValueError, 'outcome'):
            module.validate_draft(task, value)

    def test_description_cannot_smuggle_reports_or_extra_lines(self):
        module, _, task = self.task()
        for text in ('Поиск\nПроверено 34 теста', '- [ ] Поиск', 'Поиск\n\nКомментарий'):
            value = draft(task)
            value['outcomes'][0]['text'] = text
            with self.assertRaises(ValueError):
                module.validate_draft(task, value)

    def test_new_issue_payload_assigns_authenticated_owner(self):
        module, _, task = self.task()
        plan = module.make_plan(task, draft(task), None, SOURCE)
        module.approve(task, plan, SOURCE)
        publication = module.prepare_send(task, plan, None, SOURCE)
        self.assertEqual(publication['operation'], 'create')
        self.assertEqual(publication['arguments']['assignee'], 'me')

    def test_legacy_unassigned_create_plan_cannot_be_sent(self):
        module, _, task = self.task()
        plan = module.make_plan(task, draft(task), None, SOURCE)
        plan['arguments'].pop('assignee', None)
        plan['plan_key'] = module.digest({key: value for key, value in plan.items() if key != 'plan_key'})
        with self.assertRaisesRegex(ValueError, 'assignee'):
            module.approve(task, plan, SOURCE)

    def test_update_plan_cannot_reassign_existing_issue(self):
        module, _, task = self.task()
        current = issue('- [ ] Старый текст')
        task['issue'] = 'test-issue'
        task['snapshot'] = module.normalize_issue(current)
        plan = module.make_plan(task, draft(task), current, SOURCE)
        plan['arguments']['assignee'] = 'me'
        plan['plan_key'] = module.digest({key: value for key, value in plan.items() if key != 'plan_key'})
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            module.approve(task, plan, SOURCE)

    def test_local_ready_and_open_mr_do_not_tick_checkboxes(self):
        module, _, task = self.task()
        module.mark_ready(task, ['legacy', 'search'], SOURCE)
        module.bind_mr(task, {'iid': 12, 'sha': HEAD, 'source_branch': task['branch'], 'target_branch': 'dev'}, ['legacy', 'search'])
        plan = module.make_plan(task, draft(task), None, SOURCE)
        self.assertNotIn('[x]', plan['desired']['description'])
        self.assertEqual(plan['desired']['state'], 'In Progress')
        self.assertNotIn('comments', plan['arguments'])

    def test_wrong_target_and_wrong_source_cannot_prove_delivery(self):
        module, _, task = self.task()
        module.mark_ready(task, ['legacy', 'search'], SOURCE)
        module.bind_mr(task, {'iid': 12, 'sha': HEAD, 'source_branch': task['branch'], 'target_branch': 'dev'}, ['legacy', 'search'])
        for patch in ({'target_branch': 'feature'}, {'sha': 'b' * 40}, {'source_branch': 'another'}):
            mr = {'iid': 12, 'state': 'merged', 'merged_at': '2026-11-02', 'sha': HEAD,
                  'source_branch': task['branch'], 'target_branch': 'dev'}
            mr.update(patch)
            with self.assertRaises(ValueError):
                module.record_merge(task, mr, True)

    def test_merge_without_readiness_never_ticks(self):
        module, _, task = self.task()
        mr = {'iid': 12, 'sha': HEAD, 'source_branch': task['branch'], 'target_branch': 'dev'}
        module.bind_mr(task, mr, ['legacy', 'search'])
        module.record_merge(task, {**mr, 'state': 'merged', 'merged_at': '2026-11-02'}, True)
        self.assertNotIn('[x]', module.make_plan(task, draft(task), None, SOURCE)['desired']['description'])

    def test_partial_delivery_uses_ids_not_display_order(self):
        module, _, task = self.task()
        module.mark_ready(task, ['legacy'], SOURCE)
        mr = {'iid': 12, 'sha': HEAD, 'source_branch': task['branch'], 'target_branch': 'dev'}
        module.bind_mr(task, mr, ['legacy'])
        module.record_merge(task, {**mr, 'state': 'merged', 'merged_at': '2026-11-02'}, True)
        value = draft(task)
        value['outcomes'].reverse()
        plan = module.make_plan(task, value, None, SOURCE)
        self.assertEqual(plan['desired']['description'].splitlines(),
                         ['- [ ] Исправить прыжок поиска при смене вкладок', '- [x] Убрать старый вид в двух вкладках'])
        self.assertEqual(plan['desired']['state'], 'In Progress')

    def test_all_ready_results_in_dev_mean_deployment_not_done(self):
        module, _, task = self.task()
        module.mark_ready(task, ['legacy', 'search'], SOURCE)
        mr = {'iid': 12, 'sha': HEAD, 'source_branch': task['branch'], 'target_branch': 'dev'}
        module.bind_mr(task, mr, ['legacy', 'search'])
        with self.assertRaisesRegex(ValueError, 'dev'):
            module.record_merge(task, {**mr, 'state': 'merged', 'merged_at': '2026-11-02'}, False)
        module.record_merge(task, {**mr, 'state': 'merged', 'merged_at': '2026-11-02'}, True)
        plan = module.make_plan(task, draft(task), None, SOURCE)
        self.assertEqual(plan['desired']['state'], 'Deployment')
        self.assertEqual(plan['desired']['description'].count('[x]'), 2)

    def test_unchanged_remote_is_noop_and_metadata_is_not_published(self):
        module, _, task = self.task()
        body = '\n'.join('- [ ] ' + row['text'] for row in intake()['outcomes'])
        current = issue(body)
        task['issue'] = 'test-issue'
        task['snapshot'] = module.normalize_issue(current)
        plan = module.make_plan(task, draft(task), current, SOURCE)
        self.assertEqual(plan['operation'], 'no_op')
        self.assertEqual(plan['arguments'], {})

    def test_update_is_anchored_patch_not_description_overwrite(self):
        module, _, task = self.task()
        current = issue('- [ ] Старый текст')
        task['issue'] = 'test-issue'
        task['snapshot'] = module.normalize_issue(current)
        plan = module.make_plan(task, draft(task), current, SOURCE)
        self.assertNotIn('description', plan['arguments'])
        self.assertEqual(plan['arguments']['patch'][0]['old_string'], current['description'])
        self.assertNotIn('priority', plan['arguments'])
        self.assertNotIn('assignee', plan['arguments'])

    def test_foreign_team_cannot_be_adopted(self):
        module, _, task = self.task()
        with self.assertRaises(ValueError):
            module.make_plan(task, draft(task), {**issue('- [ ] Поиск'), 'teamId': 'other'}, SOURCE)

    def test_manual_issue_is_adopted_without_rewriting_title_or_description(self):
        for body in ('Ручное пояснение владельца\n\n- важный контекст', '', '- [ ] Поиск\n\nПояснение'):
            with self.subTest(body=body):
                module, _, task = self.task()
                current = {**issue(body), 'title': 'Заголовок владельца'}
                before = copy.deepcopy(current)
                plan = module.make_plan(task, draft(task), current, SOURCE)
                self.assertEqual(plan['operation'], 'no_op')
                self.assertEqual(plan['arguments'], {})
                self.assertEqual(plan['desired']['description'], body)
                self.assertEqual(plan['desired']['title'], current['title'])
                module.approve(task, plan, SOURCE)
                self.assertEqual(module.prepare_send(task, plan, current, SOURCE)['operation'], 'no_op')
                self.assertEqual(task['issue'], 'test-issue')
                self.assertEqual(task['snapshot'], module.normalize_issue(current))
                self.assertEqual(current, before)

    def test_manual_issue_delivery_updates_only_state_and_checks_exact_readback(self):
        module, _, task = self.task()
        current = {**issue('Контекст владельца\n\nНе заменять чеклистом.'), 'title': 'Ручная задача'}
        module.mark_ready(task, ['legacy', 'search'], SOURCE)
        mr = {'iid': 12, 'sha': HEAD, 'source_branch': task['branch'], 'target_branch': 'dev'}
        module.bind_mr(task, mr, ['legacy', 'search'])
        module.record_merge(task, {**mr, 'state': 'merged', 'merged_at': '2026-11-02'}, True)
        plan = module.make_plan(task, draft(task), current, SOURCE)
        self.assertEqual(plan['arguments'], {'id': 'test-issue', 'state': 'Deployment'})
        module.approve(task, plan, SOURCE)
        module.prepare_send(task, plan, current, SOURCE)
        with self.assertRaises(ValueError):
            module.confirm(task, {**current, 'status': 'Deployment', 'description': 'Чужая замена'})
        module.confirm(task, {**current, 'status': 'Deployment'})
        self.assertEqual(task['snapshot']['description'], current['description'])

    def test_manual_later_state_is_preserved_after_delivery(self):
        for status in ('QA', 'Done'):
            with self.subTest(status=status):
                module, _, task = self.task()
                current = issue('Ручное описание', status)
                module.mark_ready(task, ['legacy', 'search'], SOURCE)
                mr = {'iid': 12, 'sha': HEAD, 'source_branch': task['branch'], 'target_branch': 'dev'}
                module.bind_mr(task, mr, ['legacy', 'search'])
                module.record_merge(task, {**mr, 'state': 'merged', 'merged_at': '2026-11-02'}, True)
                plan = module.make_plan(task, draft(task), current, SOURCE)
                self.assertEqual(plan['operation'], 'no_op')
                self.assertEqual(plan['desired']['state'], status)

    def test_non_string_description_is_rejected(self):
        module, _, task = self.task()
        for body in ([], {}, 5):
            with self.subTest(body=body), self.assertRaises(ValueError):
                module.make_plan(task, draft(task), issue(body), SOURCE)

    def test_manual_status_and_checkbox_changes_block_local_overwrite(self):
        body = '- [ ] Убрать старый вид в двух вкладках\n- [ ] Исправить прыжок поиска при смене вкладок'
        for change in ({'status': 'Todo'}, {'status': 'In Review'}, {'status': 'Done'},
                       {'description': body.replace('[ ]', '[x]', 1)}):
            with self.subTest(change=change):
                module, _, task = self.task()
                original = issue(body)
                task['issue'] = 'test-issue'
                task['snapshot'] = module.normalize_issue(original)
                before = copy.deepcopy(task)
                current = {**original, **change}
                with self.assertRaisesRegex(ValueError, 'human'):
                    module.make_plan(task, draft(task), current, SOURCE, 'In Progress')
                self.assertEqual(task, before)
                self.assertEqual(current, {**original, **change})

    def test_manual_uncheck_blocks_verified_local_completion(self):
        module, _, task = self.task()
        module.mark_ready(task, ['legacy', 'search'], SOURCE)
        mr = {'iid': 12, 'sha': HEAD, 'source_branch': task['branch'], 'target_branch': 'dev'}
        module.bind_mr(task, mr, ['legacy', 'search'])
        module.record_merge(task, {**mr, 'state': 'merged', 'merged_at': '2026-11-02'}, True)
        body = '- [x] Убрать старый вид в двух вкладках\n- [x] Исправить прыжок поиска при смене вкладок'
        task['issue'] = 'test-issue'
        task['snapshot'] = module.normalize_issue(issue(body, 'Deployment'))
        current = issue(body.replace('[x]', '[ ]', 1), 'Deployment')
        with self.assertRaisesRegex(ValueError, 'human'):
            module.make_plan(task, draft(task), current, SOURCE)
        self.assertIsNone(task['pending'])

    def test_manual_change_after_approval_cannot_be_sent(self):
        for change in ({'status': 'Done'}, {'description': '- [x] Старый текст'}):
            with self.subTest(change=change):
                module, _, task = self.task()
                original = issue('- [ ] Старый текст')
                task['issue'] = 'test-issue'
                task['snapshot'] = module.normalize_issue(original)
                plan = module.make_plan(task, draft(task), original, SOURCE)
                module.approve(task, plan, SOURCE)
                with self.assertRaisesRegex(ValueError, 'remote issue changed'):
                    module.prepare_send(task, plan, {**original, **change}, SOURCE)
                self.assertIsNone(task['pending'])

    def test_late_human_change_rejects_previously_approved_payload(self):
        module, _, task = self.task()
        current = issue('- [ ] Старый текст')
        task['issue'] = 'test-issue'
        task['snapshot'] = module.normalize_issue(current)
        plan = module.make_plan(task, draft(task), current, SOURCE)
        module.approve(task, plan, SOURCE)
        changed = {**current, 'description': '- [ ] Вручную изменённый текст'}
        with self.assertRaisesRegex(ValueError, 'changed'):
            module.prepare_send(task, plan, changed, SOURCE)

    def test_unknown_write_outcome_cannot_create_a_duplicate(self):
        module, _, task = self.task()
        plan = module.make_plan(task, draft(task), None, SOURCE)
        module.approve(task, plan, SOURCE)
        module.prepare_send(task, plan, None, SOURCE)
        with self.assertRaisesRegex(ValueError, 'pending'):
            module.prepare_send(task, plan, None, SOURCE)
        self.assertIsNotNone(task['pending'])

    def test_confirmation_requires_actual_expected_readback(self):
        module, _, task = self.task()
        plan = module.make_plan(task, draft(task), None, SOURCE)
        module.approve(task, plan, SOURCE)
        module.prepare_send(task, plan, None, SOURCE)
        wrong = issue('- [ ] Не тот текст')
        with self.assertRaises(ValueError):
            module.confirm(task, wrong)
        readback = issue(plan['desired']['description'], plan['desired']['state'])
        module.confirm(task, readback)
        self.assertEqual(task['issue'], 'test-issue')
        self.assertIsNone(task['pending'])
        self.assertEqual(module.make_plan(task, draft(task), readback, SOURCE)['operation'], 'no_op')

    def test_source_or_request_changes_invalidate_approval(self):
        module, state, task = self.task()
        plan = module.make_plan(task, draft(task), None, SOURCE)
        module.approve(task, plan, SOURCE)
        with self.assertRaises(ValueError):
            module.prepare_send(task, plan, None, {**SOURCE, 'key': 'new-source'})
        value = intake()
        value['outcomes'][0]['text'] += ', оставить новый'
        module.enter(state, task['branch'], value)
        with self.assertRaises(ValueError):
            module.prepare_send(task, plan, None, SOURCE)

    def test_registry_survives_reopen_and_rejects_symlinks(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'linear.json'
            first = module.Registry(path)
            first.update(lambda state: module.enter(state, 'DEV-capitalism-slave-cascade', intake()))
            again = module.Registry(path).update(lambda state: state['tasks']['cascade'])
            self.assertEqual(again['work_id'], 'cascade')
            target = Path(directory) / 'other.json'
            target.write_text('{}')
            path.unlink()
            path.symlink_to(target)
            with self.assertRaises(ValueError):
                first.update(lambda state: state)

    def test_editor_receipt_rejects_tools_and_provider_fallback(self):
        module, _, task = self.task()
        message = {'role': 'assistant', 'provider': 'openai-codex', 'model': 'gpt-6-luna',
                   'stopReason': 'stop', 'content': [{'type': 'text', 'text': json.dumps(draft(task))}]}
        event = {'type': 'agent_end', 'messages': [message]}
        capability = {'type': 'editor_capabilities', 'tools': [], 'mcp': False}
        prefix = json.dumps(capability) + '\n'
        self.assertEqual(module.parse_editor_events(prefix + json.dumps(event), task), draft(task))
        for change in ({'model': 'another-model'}, {'provider': 'another-provider'},
                       {'stopReason': 'error'}, {'content': [{'type': 'toolCall', 'name': 'write'}]}):
            broken = copy.deepcopy(event)
            broken['messages'][0].update(change)
            with self.assertRaises(RuntimeError):
                module.parse_editor_events(prefix + json.dumps(broken), task)
        for capabilities in (None, {**capability, 'tools': ['mcp__linear_save_issue']},
                             {**capability, 'mcp': True}):
            bad_prefix = json.dumps(capabilities) + '\n' if capabilities else ''
            with self.assertRaises(RuntimeError):
                module.parse_editor_events(bad_prefix + json.dumps(event), task)

    def test_uncommitted_readiness_cannot_be_claimed_as_merged_result(self):
        module, _, task = self.task()
        module.mark_ready(task, ['legacy', 'search'], {**SOURCE, 'clean': False})
        mr = {'iid': 12, 'sha': HEAD, 'source_branch': task['branch'], 'target_branch': 'dev'}
        module.bind_mr(task, mr, ['legacy', 'search'])
        module.record_merge(task, {**mr, 'state': 'merged', 'merged_at': '2026-11-02'}, True)
        self.assertNotIn('[x]', module.make_plan(task, draft(task), None, SOURCE)['desired']['description'])

    def test_adopting_manual_completion_cannot_silently_uncheck_it(self):
        module, _, task = self.task()
        with self.assertRaisesRegex(ValueError, 'manual'):
            module.make_plan(task, draft(task), issue('- [x] Вручную завершённый результат'), SOURCE)

    def test_explicit_work_id_resumes_after_branch_replacement(self):
        module, state, task = self.task()
        task['issue'] = 'test-issue'
        resumed = module.enter(state, 'DEV-capitalism-slave-resumed-cascade', intake())
        self.assertEqual(resumed['branch'], 'DEV-capitalism-slave-resumed-cascade')
        self.assertEqual(resumed['issue'], 'test-issue')
        self.assertEqual(len(state['tasks']), 1)


    def fixture_worktree(self, directory, remote='git@gitlab.psclp.org:common/frontend/frontend.git', production_hooks=False):
        base = Path(directory)
        repo = base / 'main'
        subprocess.run(['git', 'init', '-q', '-b', 'dev', str(repo)], check=True)
        subprocess.run(['git', '-C', str(repo), 'remote', 'add', 'origin', remote], check=True)
        (repo / 'source.txt').write_text('fixture')
        subprocess.run(['git', '-C', str(repo), 'add', 'source.txt'], check=True)
        subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                        'commit', '-qm', 'fixture'], check=True)
        (repo / '.git' / 'info' / 'exclude').write_text('.superpowers/\n')
        config = base / 'wt.toml'
        body = 'worktree-path = \"' + str(base / 'trees') + '/{{ branch }}\"\n'
        if production_hooks:
            installed = tomllib.loads((Path(__file__).resolve().parents[3] / 'config.toml').read_text())
            hooks = [('pre-start', installed.get('pre-start', {}))]
            hooks.extend(('projects.' + json.dumps(name) + '.pre-start', project.get('pre-start', {}))
                         for name, project in installed.get('projects', {}).items())
            for section, commands in hooks:
                self.assertIsInstance(commands, dict)
                if commands:
                    body += '\n[' + section + ']\n'
                    body += ''.join(json.dumps(name) + ' = ' + json.dumps(command) + '\n'
                                    for name, command in commands.items())
        config.write_text(body)
        result = subprocess.run(['wt', '--config', str(config), 'switch', '--create',
                                 'DEV-capitalism-slave-linear-test', '--base', 'dev', '--format', 'json'],
                                cwd=repo, check=True, text=True, capture_output=True)
        return repo, Path(json.loads(result.stdout)['path'])

    def test_native_cli_restores_binding_in_a_new_process(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            repo, root = self.fixture_worktree(directory)
            local = root / '.superpowers' / 'linear'
            local.mkdir(parents=True)
            request = local / 'intake.json'
            request.write_text(json.dumps(intake()))
            command = [sys.executable, module.__file__, '--root', str(root)]
            entered = subprocess.run([*command, 'enter', '--input', str(request)], text=True, capture_output=True, check=True)
            restored = subprocess.run([*command, 'status'], text=True, capture_output=True, check=True)
            self.assertEqual(json.loads(entered.stdout), json.loads(restored.stdout))
            self.assertTrue((root / '.omp/skills/p2p-linear/SKILL.md').is_file())
            self.assertTrue((repo / '.git/wt/linear.json').is_file())
            subprocess.run(['git', '-C', str(root), 'check-ignore', '-q', '.omp/skills/p2p-linear/SKILL.md'], check=True)

    def test_native_cli_refuses_ecom_without_installing_or_creating_state(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            repo, root = self.fixture_worktree(directory, 'git@gitlab.psclp.org:ecom/frontend/frontend.git')
            result = subprocess.run([sys.executable, module.__file__, '--root', str(root), 'ensure'],
                                    text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('p2p-only', result.stderr)
            self.assertFalse((root / '.omp').exists())
            self.assertFalse((repo / '.git/wt/linear.json').exists())

    def test_adopting_unchanged_issue_persists_binding_without_a_write(self):
        module, _, task = self.task()
        body = '\n'.join('- [ ] ' + row['text'] for row in intake()['outcomes'])
        current = issue(body)
        plan = module.make_plan(task, draft(task), current, SOURCE)
        self.assertEqual(plan['operation'], 'no_op')
        module.approve(task, plan, SOURCE)
        result = module.prepare_send(task, plan, current, SOURCE)
        self.assertEqual(result['operation'], 'no_op')
        self.assertEqual(task['issue'], 'test-issue')
        self.assertEqual(task['snapshot'], module.normalize_issue(current))

    def test_real_creation_hooks_install_only_for_p2p_without_creating_a_task(self):
        for remote, expected_skill in (
                ('git@gitlab.psclp.org:common/frontend/frontend.git', True),
                ('git@gitlab.psclp.org:ecom/frontend/frontend.git', False)):
            with self.subTest(remote=remote), tempfile.TemporaryDirectory() as directory:
                repo, root = self.fixture_worktree(directory, remote, production_hooks=True)
                self.assertEqual((root / '.omp/skills/p2p-linear/SKILL.md').is_file(), expected_skill)
                self.assertFalse((repo / '.git/wt/linear.json').exists())

    def test_new_delivery_facts_invalidate_old_approval_but_repeats_do_not(self):
        for late in ('merge', 'ready', 'binding'):
            with self.subTest(late=late):
                module, _, task = self.task()
                identifiers = ['legacy', 'search']
                mr = {'iid': 12, 'sha': HEAD, 'source_branch': task['branch'], 'target_branch': 'dev'}
                merged = {**mr, 'state': 'merged', 'merged_at': '2026-11-02'}
                module.bind_mr(task, mr, identifiers if late != 'binding' else ['legacy'])
                if late == 'merge':
                    module.mark_ready(task, identifiers, SOURCE)
                elif late == 'ready':
                    module.record_merge(task, merged, True)
                old = module.make_plan(task, draft(task), None, SOURCE)
                module.approve(task, old, SOURCE)

                def observe():
                    if late == 'merge':
                        module.record_merge(task, merged, True)
                    elif late == 'ready':
                        module.mark_ready(task, identifiers, SOURCE)
                    else:
                        module.bind_mr(task, mr, identifiers)

                observe()
                if late != 'binding':
                    self.assertEqual(module.make_plan(task, draft(task), None, SOURCE)['desired']['state'], 'Deployment')
                with self.assertRaises(ValueError):
                    module.prepare_send(task, old, None, SOURCE)
                current = module.make_plan(task, draft(task), None, SOURCE)
                module.approve(task, current, SOURCE)
                observe()
                self.assertEqual(module.prepare_send(task, current, None, SOURCE)['operation'], 'create')

if __name__ == '__main__':
    unittest.main()
