#!/usr/bin/env python3
"""p2p checklist drafts and exact MCP payloads; no credentials or Linear API client."""
import argparse
import copy
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid

from review_contract import SECRET

HOME = Path(__file__).resolve().parent
GUARD = HOME.parent / 'guarded-run'
TEAM = 'b53538a0-3a86-47b8-a5b8-14dd5af97428'
MODEL = 'openai-codex/gpt-6-luna'
REMOTES = {'git@gitlab.psclp.org:common/frontend/frontend',
           'https://gitlab.psclp.org/common/frontend/frontend',
           'ssh://git@gitlab.psclp.org/common/frontend/frontend'}
STATES = {'Todo', 'In Progress', 'In Review', 'Deployment'}
CHECKBOX = re.compile(r'^[-*] \[([ xX])\] (.+)$')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def line_text(value, maximum=400):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or '\n' in value or '\r' in value:
        raise ValueError('expected one short nonempty line')
    if value != value.strip() or value.startswith(('-', '*', '#', '[')) or SECRET.search(value):
        raise ValueError('checklist text contains markup, surrounding whitespace or a likely secret')
    return value


def outcome_rows(rows):
    if not isinstance(rows, list) or not rows or len(rows) > 100:
        raise ValueError('accepted outcomes are required')
    result = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'id', 'text'} or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}', row.get('id', '')):
            raise ValueError('outcome needs a stable id and text')
        result.append({'id': row['id'], 'text': line_text(row['text'])})
    if len({row['id'] for row in result}) != len(result):
        raise ValueError('duplicate outcome id')
    return result


def empty_registry():
    return {'schema': 1, 'branches': {}, 'tasks': {}}


def enter(state, branch, value):
    if not isinstance(value, dict) or not isinstance(value.get('owner_requests'), list) or not value['owner_requests']:
        raise ValueError('accepted owner requests are required; questions do not enter this workflow')
    for request in value['owner_requests']:
        if not isinstance(request, str) or not request.strip() or SECRET.search(request):
            raise ValueError('invalid or secret-bearing owner request')
    request = {'owner_requests': value['owner_requests'], 'outcomes': outcome_rows(value.get('outcomes'))}
    if len(json.dumps(request).encode()) > 32_000:
        raise ValueError('supply a bounded accepted request, not the full session')
    work_id = value.get('work_id') or state['branches'].get(branch) or uuid.uuid4().hex
    if not isinstance(work_id, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,119}', work_id):
        raise ValueError('invalid work id')
    task = state['tasks'].get(work_id)
    if task and task['pending']:
        raise ValueError('pending publication must be reconciled before changing the request')
    if task is None:
        task = {'work_id': work_id, 'branch': branch, 'revision': 0, 'request_key': None,
                'request': None, 'issue': None, 'snapshot': None, 'approval': None,
                'pending': None, 'ready': {}, 'delivered': {}, 'mrs': []}
        state['tasks'][work_id] = task
    if task['request'] != request:
        task.update(request=request, request_key=digest(request), revision=task['revision'] + 1, approval=None)
    task['branch'] = branch
    state['branches'][branch] = work_id
    return task


def validate_draft(task, value):
    if not isinstance(value, dict) or set(value) != {'request_key', 'title', 'outcomes'} or value['request_key'] != task['request_key']:
        raise ValueError('draft does not match the current request')
    line_text(value['title'], 140)
    rows = outcome_rows(value['outcomes'])
    if {row['id'] for row in rows} != {row['id'] for row in task['request']['outcomes']}:
        raise ValueError('draft must cover exactly the accepted outcome ids, without auxiliary outcomes')
    return value


def checklist(body):
    if not isinstance(body, str) or not body.strip():
        raise ValueError('existing description is not a managed checklist; main must reconcile it')
    rows = []
    for line in body.splitlines():
        if not line.strip():
            continue
        match = CHECKBOX.fullmatch(line)
        if not match:
            raise ValueError('manual description is not replaced by a generated checklist')
        rows.append((match[1].lower() == 'x', match[2]))
    return rows


def normalize_issue(value):
    if not isinstance(value, dict):
        raise ValueError('actual issue read-back is required')
    team = value.get('teamId') or (value.get('team', {}).get('id') if isinstance(value.get('team'), dict) else None)
    if team != TEAM:
        raise ValueError('issue belongs to another team or team identity is missing')
    status = value.get('status', value.get('state'))
    if isinstance(status, dict):
        status = status.get('name')
    identity = value.get('uuid') or value.get('id')
    if not identity or not status or not isinstance(value.get('title'), str):
        raise ValueError('issue identity, title and status are required')
    description = value.get('description')
    if description is None:
        description = ''
    if not isinstance(description, str):
        raise ValueError('issue description must be text or null')
    return {'id': identity, 'title': value['title'], 'description': description, 'state': status, 'teamId': team}


def content_key(task, identifier):
    return digest(next(row for row in task['request']['outcomes'] if row['id'] == identifier))


def mark_ready(task, identifiers, source):
    known = {row['id'] for row in task['request']['outcomes']}
    if not set(identifiers).issubset(known):
        raise ValueError('readiness names an unknown outcome')
    for identifier in identifiers:
        ready = {**source, 'content': content_key(task, identifier)}
        if task['ready'].get(identifier) != ready:
            task['approval'] = None
            task['ready'][identifier] = ready


def bind_mr(task, mr, identifiers):
    known = {row['id'] for row in task['request']['outcomes']}
    if not identifiers or not set(identifiers).issubset(known):
        raise ValueError('MR binding needs the exact delivered outcome ids')
    if mr.get('target_branch') != 'dev' or mr.get('source_branch') != task['branch'] or not re.fullmatch('[a-f0-9]{40}|[a-f0-9]{64}', mr.get('sha', '')):
        raise ValueError('MR does not match this task source and dev target')
    binding = {'iid': int(mr['iid']), 'sha': mr['sha'], 'source_branch': task['branch'],
               'outcomes': {identifier: content_key(task, identifier) for identifier in identifiers}}
    if next((row for row in task['mrs'] if row['iid'] == binding['iid']), None) != binding:
        task['approval'] = None
    task['mrs'] = [row for row in task['mrs'] if row['iid'] != binding['iid']] + [binding]


def record_merge(task, mr, in_dev):
    binding = next((row for row in task['mrs'] if row['iid'] == mr.get('iid')), None)
    if not binding or mr.get('state') != 'merged' or not mr.get('merged_at') or mr.get('target_branch') != 'dev' or not in_dev:
        raise ValueError('a confirmed matching merge present in dev is required')
    if mr.get('sha') != binding['sha'] or mr.get('source_branch') != binding['source_branch']:
        raise ValueError('merged source changed since the outcome binding')
    for identifier, content in binding['outcomes'].items():
        delivered = {'head': binding['sha'], 'content': content, 'iid': binding['iid']}
        if task['delivered'].get(identifier) != delivered:
            task['approval'] = None
            task['delivered'][identifier] = delivered


def checked(task, identifier):
    ready, delivered = task['ready'].get(identifier), task['delivered'].get(identifier)
    return bool(ready and delivered and ready.get('clean') is True
                and ready['content'] == delivered['content'] == content_key(task, identifier)
                and ready['head'] == delivered['head'])


def make_plan(task, value, current, source, state=None):
    validate_draft(task, value)
    if task['pending']:
        raise ValueError('pending publication needs read-back reconciliation')
    if state is not None and state not in STATES - {'Deployment'}:
        raise ValueError('main may choose Todo/In Progress/In Review; Deployment is derived')
    actual = normalize_issue(current) if current is not None else None
    if task['issue'] and (actual is None or actual['id'] != task['issue']):
        raise ValueError('read the bound issue before preparing an update')
    actual_rows = None
    if actual:
        if task['snapshot'] is not None and actual != task['snapshot']:
            raise ValueError('human issue content or state changed; main reconciliation required')
        try:
            actual_rows = checklist(actual['description'])
        except ValueError:
            pass
    rows = [(checked(task, row['id']), row['text']) for row in value['outcomes']]
    if actual_rows and task['snapshot'] is None and any(done for done, _text in actual_rows):
        if actual_rows != rows:
            raise ValueError('manual completion needs main reconciliation, not automatic unchecking')
    active_state = state or (actual['state'] if actual else 'In Progress')
    body = '\n'.join('- [x] ' + text if done else '- [ ] ' + text for done, text in rows)
    manual = actual is not None and actual_rows is None
    desired = {'title': actual['title'] if manual else value['title'],
               'description': actual['description'] if manual or actual_rows == rows else body,
               'state': ('Deployment' if all(done for done, _text in rows) else active_state)}
    if manual and actual['state'] not in STATES:
        desired['state'] = actual['state']
    arguments = {}
    if actual is None:
        operation = 'create'
        arguments = {'team': TEAM, 'assignee': 'me', **desired}
    else:
        operation = 'update'
        if actual['title'] != desired['title']:
            arguments['title'] = desired['title']
        if not manual and actual_rows != rows:
            arguments['patch'] = [{'op': 'replace', 'old_string': actual['description'], 'new_string': body}]
        if actual['state'] != desired['state']:
            if actual['state'] not in STATES:
                raise ValueError('preserve a later/manual state; main must reconcile it')
            arguments['state'] = desired['state']
        if arguments:
            arguments['id'] = actual['id']
        else:
            operation = 'no_op'
    plan = {'work_id': task['work_id'], 'revision': task['revision'], 'request_key': task['request_key'],
            'source': source, 'expected': actual, 'desired': desired, 'operation': operation, 'arguments': arguments}
    return {**plan, 'plan_key': digest(plan)}


def validate_plan(task, plan, source):
    body = {key: value for key, value in plan.items() if key != 'plan_key'}
    if plan.get('plan_key') != digest(body) or plan.get('work_id') != task['work_id'] or plan.get('request_key') != task['request_key'] or plan.get('revision') != task['revision'] or plan.get('source') != source:
        raise ValueError('request, approved payload or source changed')
    arguments = plan.get('arguments', {})
    allowed = {'id', 'team', 'title', 'description', 'patch', 'state'}
    if plan.get('operation') == 'create':
        if arguments.get('assignee') != 'me':
            raise ValueError('new issue assignee must be the authenticated owner (me)')
        allowed.add('assignee')
    if set(arguments) - allowed:
        raise ValueError('unsupported publication fields')


def approve(task, plan, source):
    validate_plan(task, plan, source)
    task['approval'] = plan['plan_key']


def prepare_send(task, plan, current, source):
    if task['pending']:
        raise ValueError('pending write has an unknown outcome; reconcile it instead of repeating')
    validate_plan(task, plan, source)
    if task['approval'] != plan['plan_key']:
        raise ValueError('main must approve the exact payload first')
    actual = normalize_issue(current) if current is not None else None
    if actual != plan['expected']:
        raise ValueError('remote issue changed after approval')
    if plan['operation'] == 'no_op':
        if actual is not None:
            task.update(issue=actual['id'], snapshot=actual, approval=None)
        return {'operation': 'no_op', 'arguments': {}}
    task['pending'] = copy.deepcopy(plan)
    return {'operation': plan['operation'], 'tool': 'mcp__linear_save_issue', 'arguments': plan['arguments'], 'plan_key': plan['plan_key']}


def confirm(task, value):
    if not task['pending']:
        raise ValueError('no pending publication to confirm')
    actual = normalize_issue(value)
    plan = task['pending']
    desired = plan['desired']
    if (plan['expected'] and actual['id'] != plan['expected']['id']) or actual['title'] != desired['title'] or actual['state'] != desired['state'] or actual['description'] != desired['description']:
        raise ValueError('actual read-back does not match the approved publication')
    task.update(issue=actual['id'], snapshot=actual, pending=None, approval=None)
    return actual


def read_json(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('JSON input/state must not be a symlink: ' + str(path))
    return json.loads(path.read_text())


def atomic_text(path, text):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('refusing symlink output: ' + str(path))
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Registry:
    def __init__(self, path):
        self.path = Path(path)

    def update(self, callback):
        if self.path.parent.is_symlink() or self.path.is_symlink():
            raise ValueError('registry must not be a symlink')
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = self.path.with_suffix('.lock')
        with os.fdopen(os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), 'a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            state = read_json(self.path) if self.path.exists() else empty_registry()
            if not isinstance(state, dict) or set(state) != {'schema', 'branches', 'tasks'} or state['schema'] != 1:
                raise ValueError('invalid registry; preserve it for recovery')
            before = digest(state)
            result = callback(state)
            if digest(state) != before:
                atomic_text(self.path, json.dumps(state, ensure_ascii=False, indent=2) + '\n')
            return copy.deepcopy(result)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def workspace(root):
    root = Path(git(root, 'rev-parse', '--show-toplevel')).resolve()
    common = Path(git(root, 'rev-parse', '--path-format=absolute', '--git-common-dir')).resolve()
    branch = git(root, 'branch', '--show-current')
    if git(root, 'remote', 'get-url', 'origin').removesuffix('.git') not in REMOTES:
        raise ValueError('Linear protocol is p2p-only')
    if not (root / '.git').is_file() or not branch or branch in {'dev', 'main', 'master'} or branch.startswith('release'):
        raise ValueError('use an owned linked task worktree')
    return root, common, branch


def source_identity(root):
    changed = git(root, 'diff', '--binary', 'HEAD', '--', '.')
    untracked = git(root, 'ls-files', '--others', '--exclude-standard', '-z')
    files = {}
    for name in filter(None, untracked.split('\0')):
        path = root / name
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() and not path.is_symlink() else 'non-regular'
    head = git(root, 'rev-parse', 'HEAD')
    return {'head': head, 'key': digest({'head': head, 'diff': changed, 'untracked': files}),
            'clean': not changed and not files}


def ensure(root, common):
    directory = root / '.omp' / 'skills' / 'p2p-linear'
    for part in (root / '.omp', root / '.omp' / 'skills', directory):
        if part.is_symlink():
            raise ValueError('project skill path must not be a symlink')
        part.mkdir(exist_ok=True, mode=0o700)
    template = (HOME / 'linear-skill.md').read_text()
    target, stamp = directory / 'SKILL.md', directory / '.installed-sha256'
    if target.exists() and target.read_text() != template:
        if not stamp.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != stamp.read_text().strip():
            raise ValueError('project skill was manually changed; preserve it')
    exclude = common / 'info' / 'exclude'
    if exclude.is_symlink():
        raise ValueError('shared Git exclude must not be a symlink')
    text = exclude.read_text() if exclude.exists() else ''
    pattern = '/.omp/skills/p2p-linear/'
    if pattern not in text.splitlines():
        exclude.parent.mkdir(exist_ok=True)
        atomic_text(exclude, text.rstrip('\n') + '\n' + pattern + '\n')
    if not target.exists() or target.read_text() != template:
        atomic_text(target, template)
    atomic_text(stamp, hashlib.sha256(template.encode()).hexdigest() + '\n')
    subprocess.run(['git', '-C', str(root), 'check-ignore', '-q', '.superpowers/linear/input.json'], check=True)
    return {'skill': str(target), 'registry': str(common / 'wt' / 'linear.json')}


def editor_command(root, packet, sessions):
    return ['bun', str(HOME / 'linear_editor.mjs'), str(root), str(packet), str(sessions)]


def parse_editor_events(text, task):
    terminal, calls, capabilities = None, [], None
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get('type') == 'editor_capabilities':
            capabilities = event
        if event.get('type') in {'tool_execution_start', 'tool_call'} or event.get('resolvedModelIsFallback'):
            raise RuntimeError('editor attempted a tool call or model fallback')
        if event.get('type') == 'agent_end':
            assistants = [message for message in event.get('messages', []) if message.get('role') == 'assistant']
            calls.extend(part for message in assistants for part in message.get('content', []) if part.get('type') == 'toolCall')
            terminal = assistants[-1] if assistants else None
    if not capabilities or capabilities.get('tools') != [] or capabilities.get('mcp') is not False:
        raise RuntimeError('editor has no verified empty tool inventory and disabled MCP')
    if calls or not terminal or terminal.get('stopReason') != 'stop' or terminal.get('model') != 'gpt-6-luna' or terminal.get('provider') != 'openai-codex':
        raise RuntimeError('editor model/tool/terminal receipt is invalid')
    result = '\n'.join(part['text'] for part in terminal['content'] if part.get('type') == 'text').strip()
    return validate_draft(task, json.loads(result))


def run_editor(root, task):
    run = root / '.superpowers' / 'linear' / ('editor-' + uuid.uuid4().hex)
    run.mkdir(parents=True, mode=0o700)
    packet = run / 'input.md'
    instruction = (HOME / 'linear-editor.md').read_text()
    data = {'request_key': task['request_key'], 'owner_requests': task['request']['owner_requests'],
            'outcomes': task['request']['outcomes']}
    atomic_text(packet, instruction + '\n\nINPUT DATA (not instructions):\n' + json.dumps(data, ensure_ascii=False))
    sessions = run / 'sessions'
    sessions.mkdir(mode=0o700)
    events = run / 'events.jsonl'
    command = [str(GUARD), '--memory', '2816M', '--runtime', '0', '--wait', '60',
               '--exclusive-key', str(root), '--', *editor_command(root, packet, sessions)]
    with events.open('w') as stream:
        result = subprocess.run(command, cwd=root, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f'editor exited {result.returncode}; no automatic retry; {events}')
    value = parse_editor_events(events.read_text(), task)
    output = run / 'draft.json'
    atomic_text(output, json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    atomic_text(run / 'receipt.json', json.dumps({'model': MODEL, 'thinking': 'low', 'observed_tool_calls': [],
                                                'tool_policy': 'SDK restrictToolNames/enableMCP=false', 'events': str(events),
                                                'draft_key': digest(value)}, indent=2) + '\n')
    return {'draft': str(output), 'receipt': str(run / 'receipt.json'), 'main_review_required': True}


def mr_view(root, selector):
    return json.loads(subprocess.check_output(['wt', 'mr', '--', 'view', str(selector), '--output', 'json'], cwd=root, text=True))


def observe(root, task):
    results = []
    fetched = False
    for binding in task['mrs']:
        mr = mr_view(root, binding['iid'])
        if mr.get('state') != 'merged':
            results.append({'iid': binding['iid'], 'state': mr.get('state'), 'linear_write': False})
            continue
        proof = mr.get('squash_commit_sha') or mr.get('merge_commit_sha') or mr.get('sha', '')
        if not re.fullmatch('[a-f0-9]{40}|[a-f0-9]{64}', proof):
            raise ValueError('merged MR has no valid result SHA')
        if not fetched:
            subprocess.run(['git', '-C', str(root), 'fetch', 'origin', 'dev'], check=True)
            fetched = True
        contained = subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor', proof, 'refs/remotes/origin/dev']).returncode
        if contained not in {0, 1}:
            raise RuntimeError('could not establish dev ancestry')
        record_merge(task, mr, contained == 0)
        results.append({'iid': binding['iid'], 'state': 'merged', 'target': 'dev', 'linear_write': False})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['ensure', 'enter', 'status', 'editor', 'plan', 'approve', 'send', 'confirm', 'mr', 'observe'])
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--input', type=Path)
    parser.add_argument('--draft', type=Path)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--current', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--work-id')
    parser.add_argument('--ready', action='append', default=[])
    parser.add_argument('--outcome', action='append', default=[])
    parser.add_argument('--state')
    parser.add_argument('--mr', type=int)
    parser.add_argument('--pending', action='store_true', help='List known pending task/MR bindings without backlog search')
    args = parser.parse_args()
    root, common, branch = workspace(args.root)
    installation = ensure(root, common)
    registry = Registry(common / 'wt' / 'linear.json')
    if args.operation == 'ensure':
        print(json.dumps(installation))
        return
    def operation(state):
        if args.operation == 'status' and args.pending:
            return [{'work_id': item['work_id'], 'branch': item['branch'], 'issue': item['issue'],
                     'pending_write': bool(item['pending']), 'mrs': item['mrs']}
                    for item in state['tasks'].values() if item['pending'] or item['mrs']]
        if args.operation == 'enter':
            if not args.input:
                raise ValueError('enter requires --input with accepted owner outcomes')
            return enter(state, branch, read_json(args.input))
        work_id = args.work_id or state['branches'].get(branch)
        if work_id not in state['tasks']:
            raise ValueError('no task binding; enter the accepted work item first')
        task = state['tasks'][work_id]
        if args.operation == 'status':
            return task
        if args.operation == 'editor':
            return {'editor_input': copy.deepcopy(task)}
        if args.operation == 'mr':
            if args.mr is None:
                raise ValueError('mr requires --mr and --outcome for delivered results')
            bind_mr(task, mr_view(root, args.mr), args.outcome)
            return task['mrs']
        if args.operation == 'observe':
            return observe(root, task)
        source = source_identity(root)
        if args.operation == 'confirm':
            if not args.current:
                raise ValueError('confirm requires actual MCP get_issue read-back')
            return confirm(task, read_json(args.current))
        if args.operation == 'plan':
            if not args.draft:
                raise ValueError('plan requires --draft')
            mark_ready(task, args.ready, source)
            return make_plan(task, read_json(args.draft), read_json(args.current) if args.current else None, source, args.state)
        if not args.plan:
            raise ValueError('approve/send require --plan')
        plan = read_json(args.plan)
        if args.operation == 'approve':
            approve(task, plan, source)
            return {'approved': plan['plan_key'], 'publication': False}
        return prepare_send(task, plan, read_json(args.current) if args.current else None, source)
    result = registry.update(operation)
    if args.operation == 'editor':
        result = run_editor(root, result['editor_input'])
    body = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        output = args.output.resolve()
        artifact = root / '.superpowers'
        if not output.is_relative_to(artifact):
            raise ValueError('working outputs belong in this worktree .superpowers')
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_text(output, body)
    else:
        print(body, end='')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        print('p2p-linear: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
