"""Feature plan/refactor/check/push/open-MR; merge requires a separate explicit mode."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time
from urllib.parse import quote

from merge_readiness import Forge, TYPECHECK_APPS, required_jobs, validate_mr, wait_for_ci
from review_contract import context_path, load_context, store_context, validate_review

HERE = Path(__file__).resolve().parent
PROJECTS = HERE.parent
GUARD = PROJECTS / 'guarded-run'
MODEL = 'openai-codex/gpt-6.1-sol'
MAX_INPUT = 900_000  # Never silently omit the rest of a feature diff.


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def hotfix(branch):
    return branch.startswith('DEV-capitalism-slave-hotfix-')


def snapshot(root, allow_dirty=False):
    dirty = bool(git(root, 'status', '--porcelain', '--untracked-files=all'))
    if dirty and not allow_dirty:
        raise RuntimeError('finalization requires a clean worktree; preserve and commit existing work first')
    head = git(root, 'rev-parse', 'HEAD')
    target = git(root, 'rev-parse', 'refs/remotes/origin/dev')
    base = git(root, 'merge-base', target, head)
    names = subprocess.check_output(
        ['git', '-C', str(root), 'diff', '--name-only', '--no-renames', '-z', base, *([] if dirty else [head])]
    ).decode().split('\0')
    if dirty:
        names += subprocess.check_output(['git', '-C', str(root), 'ls-files', '--others',
                                          '--exclude-standard', '-z']).decode().split('\0')
    return {'branch': git(root, 'branch', '--show-current'), 'head': head,
            'tree': None if dirty else git(root, 'rev-parse', 'HEAD^{tree}'),
            'target': target, 'merge_base': base, 'source_key': source_key(root), 'runtime_key': runtime_key(root),
            'paths': sorted(set(filter(None, names)))}


def feature_diff(root, current):
    return subprocess.check_output(['git', '-C', str(root), 'diff', '--binary', '--no-ext-diff',
                                    '--no-textconv', '--no-renames', current['merge_base'], current['head']])


def documentation_only(root, current):
    paths = current['paths']
    if not paths or any(
        Path(name).suffix.lower() != '.md' or not (
            name.startswith(('docs/', '.agents/commands/', '.agents/rules/', '.agents/skills/', '.omp/commands/'))
            or name in {'README.md', 'CHANGELOG.md', '.agents/AGENTS.md', '.agents/component-map.md'}
        ) for name in paths
    ):
        return False
    for revision in (current['merge_base'], current['head']):
        entries = subprocess.check_output(
            ['git', '-C', str(root), 'ls-tree', '-r', '-z', revision, '--', *paths]
        ).split(b'\0')
        if any(entry and entry.split(b' ', 1)[0] != b'100644' for entry in entries):
            return False
    return True


def review_documentation(root, current, path):
    key = policy_key(root)
    run = path / (str(time.time_ns()) + '-' + current['head'][:12])
    run.mkdir(mode=0o700)
    inputs = feature_diff(root, current)
    if len(inputs) > MAX_INPUT:
        raise RuntimeError('full feature diff exceeds the reviewed input bound; never truncate')
    (run / 'feature.diff').write_bytes(inputs)
    save(run / 'source.json', current)
    (run / 'review-context.json').write_bytes(context_path(root).read_bytes())
    request = (HERE / 'review-contract.md').read_text() + (
        '\n\nPHASE: DOCUMENTATION REVIEW ONLY. Read tools only. Review the complete prose diff '
        'against every originating owner requirement and repository analog. Do not modify files, '
        'run application checks, start a preview, commit or publish. Return only the review JSON '
        'object defined above, with context_key and exact per-path coverage. Findings must be '
        'concrete; source inspection is not runtime verification.\n')
    (run / 'review-request.md').write_text(request)
    run_agent(root, [run / 'review-request.md', run / 'source.json',
                     run / 'feature.diff', run / 'review-context.json'], run / 'review.md', True)
    if snapshot(root) != current or policy_key(root) != key:
        raise RuntimeError('documentation review changed source/policy; no mixed-revision receipt')
    review = validate_review(root, json.loads((run / 'review.md').read_text()),
                             current['paths'], load_context(root))
    if any(scope['findings'] for scope in review['coverage']):
        raise RuntimeError('documentation review has findings; correct source before finalization: ' + str(run / 'review.md'))
    manifest = {'tests': [], 'commits': [], 'ui': {'required': False},
                'review': review, 'fixed': [], 'backend': [],
                'warnings': ['Documentation-only source review; application runtime is not applicable.']}
    save(run / 'implementation.json', manifest)
    proof = verify_local(root, current, manifest, run)
    proof.update(profile='documentation-only', sol={'model': MODEL, 'thinking': 'high',
                 'service_tier': 'priority', 'review_sha256': sha256(run / 'review.md')})
    if snapshot(root) != current or policy_key(root) != key:
        raise RuntimeError('documentation verification inputs changed; no stale receipt')
    (run / 'report.md').write_text(render_report(root, manifest, proof))
    save(run / 'verification.json', proof)
    save(path / 'receipt.json', receipt_for(current, key, run / 'verification.json'))
    save(run / 'state.json', {'phase': 'verified', 'source': current, 'policy': key})
    print('feature-finalize: documentation review report: ' + str(run / 'report.md'), flush=True)


def policy_key(root):
    paths = [Path(__file__), HERE / 'merge_readiness.py', HERE / 'finalize-prompt.md',
             HERE / 'finalize_agent.mjs', HERE / 'review-contract.md', HERE / 'review_contract.py',
             HERE / 'typecheck', PROJECTS / 'project-environment', PROJECTS / 'ui-session',
             *sorted((root / '.agents').rglob('*.md'))]
    context = context_path(root)
    context_key = sha256(context) if context.is_file() else 'missing-owner-context'
    return hashlib.sha256((''.join(str(p) + '\0' + sha256(p) for p in paths) + context_key).encode()).hexdigest()


def receipt_for(current, policy, verification):
    return {'schema': 1, **{key: current[key] for key in ('branch', 'head', 'tree', 'target', 'merge_base', 'source_key')},
            'policy': policy, 'verification': str(verification), 'verification_sha256': sha256(verification)}


def receipt_matches(receipt, current, policy, verification):
    try:
        return receipt == receipt_for(current, policy, verification)
    except (OSError, ValueError, KeyError):
        return False


def owned_root(root):
    root = Path(root).resolve()
    if any(os.environ.get(name) for name in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE')):
        raise RuntimeError('Git path/index overrides are outside the owned finalization scope')
    if (root / '.git').is_dir() or not (root / '.git').is_file():
        raise RuntimeError('use the owned linked feature worktree, not the primary checkout')
    remote = git(root, 'remote', 'get-url', 'origin').removesuffix('.git')
    if remote not in {'git@gitlab.psclp.org:common/frontend/frontend',
                      'https://gitlab.psclp.org/common/frontend/frontend',
                      'ssh://git@gitlab.psclp.org/common/frontend/frontend'}:
        raise RuntimeError('finalization is registered only for the p2p origin project')
    branch = git(root, 'branch', '--show-current')
    if not branch.startswith('DEV-capitalism-slave-'):
        raise RuntimeError('automatic finalization requires an owner-prefixed DEV task branch')
    if subprocess.run(['git', '-C', str(root), 'check-ignore', '-q', '.superpowers/finalize/probe']).returncode:
        raise RuntimeError('.superpowers must be locally ignored')
    return root


def directory(root):
    path = root / '.superpowers/finalize'
    for part in (root / '.superpowers', path):
        if part.is_symlink():
            raise RuntimeError('finalization state must not be a symlink')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


@contextmanager
def lock(path):
    fd = os.open(path / 'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('feature finalization already active; no recursive/nested finalizer') from exc
        yield
    finally:
        os.close(fd)


def current_receipt(root, current=None):
    current = snapshot(root) if current is None else current
    path = root / '.superpowers/finalize/receipt.json'
    try:
        if path.is_symlink():
            return False
        value = json.loads(path.read_text())
        load_context(root)
        proof = Path(value['verification'])
        if not proof.is_relative_to(root / '.superpowers/finalize') or proof.is_symlink():
            return False
        return receipt_matches(value, current, policy_key(root), proof)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return False


def refresh(root):
    subprocess.run(['git', 'fetch', 'origin', '+refs/heads/dev:refs/remotes/origin/dev'], cwd=root, check=True)


def remote_tip(root, branch):
    ref = 'refs/heads/' + branch
    rows = git(root, 'ls-remote', '--heads', 'origin', ref).splitlines()
    if not rows:
        return None
    if len(rows) != 1:
        raise RuntimeError('ambiguous remote source ref')
    fields = rows[0].split()
    if len(fields) != 2 or fields[1] != ref or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', fields[0]):
        raise RuntimeError('invalid remote source identity')
    return fields[0]


def publication_plan(root, current, expected_remote_sha=None):
    if expected_remote_sha is not None and not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', expected_remote_sha):
        raise RuntimeError('--expected-remote-sha requires the complete observed source SHA')
    remote = remote_tip(root, current['branch'])
    if expected_remote_sha is not None and remote != expected_remote_sha:
        raise RuntimeError('remote tip changed; inspect new commits instead of replacing the lease')
    if remote is None:
        return {'remote_sha': None, 'options': []}
    subprocess.run(['git', 'fetch', 'origin', 'refs/heads/' + current['branch']], cwd=root, check=True)
    if git(root, 'rev-parse', 'FETCH_HEAD') != remote:
        raise RuntimeError('remote tip changed during fetch; inspect before publication')
    ancestry = subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor', remote, current['head']])
    if ancestry.returncode not in (0, 1):
        ancestry.check_returncode()
    if ancestry.returncode == 0:
        return {'remote_sha': remote, 'options': []}
    if expected_remote_sha is None:
        raise RuntimeError('published history diverged; authorized rebase requires --expected-remote-sha')
    return {'remote_sha': remote, 'options': [
        '--force-with-lease=refs/heads/' + current['branch'] + ':' + remote]}


def agent_command(root, inputs, plan):
    output = inputs[0].parent / ('plan' if plan else 'source') if inputs else root / '.superpowers/finalize/inspection'
    return ['bun', str(HERE / 'finalize_agent.mjs'), str(root), 'plan' if plan else 'source',
            str(output), *(str(path) for path in inputs)]


def run_agent(root, inputs, output, plan):
    phase = 'plan' if plan else 'refactor'
    print(f'feature-finalize: Sol {phase} starting (high, priority); log: {output}', flush=True)
    command = [str(GUARD), '--need', '2G' if plan else '6G',
               '--tasks', '256', '--wait', '60', '--runtime', '0',
               '--exclusive-key', str(root), '--', *agent_command(root, inputs, plan)]
    events = output.with_suffix('.events.jsonl')
    with events.open('w') as log:
        result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f'Sol phase exited {result.returncode}; no automatic retry; evidence: {events}')
    terminal = None
    for line in events.read_text(errors='replace').splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get('type') == 'agent_end':
            assistants = [m for m in event.get('messages', []) if m.get('role') == 'assistant']
            terminal = assistants[-1] if assistants else None
    if not terminal or terminal.get('stopReason') != 'stop':
        raise RuntimeError('Sol has no successful terminal completion; no retry: ' + str(events))
    text = '\n'.join(p['text'] for p in terminal.get('content', [])
                     if p.get('type') == 'text' and isinstance(p.get('text'), str)).strip()
    if not text:
        raise RuntimeError('Sol returned no completion text: ' + str(events))
    output.write_text(text + '\n')
    if not plan:
        path = output.parent / 'implementation.json'
        try:
            manifest = json.loads(path.read_text())
            if manifest.get('source_key') != source_key(root):
                raise ValueError('source identity mismatch')
            validate_manifest(root, manifest, changed_paths(root))
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as error:
            raise RuntimeError(f'invalid implementation manifest: {path}: {error}') from error
    print(f'feature-finalize: Sol {phase} complete; log: {events}', flush=True)


def changed_paths(root):
    tracked = subprocess.check_output(['git', '-C', str(root), 'diff', '--name-only', '--no-renames', '-z', 'HEAD']).decode().split('\0')
    new = subprocess.check_output(['git', '-C', str(root), 'ls-files', '--others', '--exclude-standard', '-z']).decode().split('\0')
    return sorted(set(filter(None, tracked + new)))


def source_key(root):
    return content_key(root)


def runtime_key(root):
    return content_key(root, runtime=True)


def content_key(root, runtime=False):
    """Content identity remains stable when the same bytes are committed."""
    names = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z',
                                     '--cached', '--others', '--exclude-standard']).decode().split('\0')
    names += [str(path.relative_to(root)) for path in root.glob('apps/*/.env')]
    digest = hashlib.sha256()
    for name in sorted(set(filter(None, names))):
        if runtime and re.fullmatch(r'lib/(?:common|admin|form|merchant|provider)-layer/.*\.(?:test|spec)\.tsx?', name):
            continue
        path = root / name
        if not path.exists() and not path.is_symlink():
            continue
        digest.update(name.encode() + b'\0')
        digest.update(os.readlink(path).encode() if path.is_symlink() else path.read_bytes())
        digest.update(b'\0')
    return digest.hexdigest()


def validate_manifest(root, value, changed):
    if not isinstance(value, dict) or not all(key in value for key in ('commits', 'tests', 'fixed', 'backend', 'warnings', 'blockers', 'ui')):
        raise RuntimeError('implementation manifest is missing required report/verification fields')
    assigned = []
    for topic in value['commits']:
        if not re.fullmatch(r'(?:refactor|fix|test)\([a-z][a-z0-9-]*\): [^\n]+', topic['message']):
            raise RuntimeError('refactor commit needs a narrow conventional scope/message')
        if not topic['paths']:
            raise RuntimeError('empty atomic commit topic')
        scopes = set()
        for name in topic['paths']:
            path = Path(name)
            if not path.parts or path.is_absolute() or '..' in path.parts or path.parts[0] in {'.superpowers', 'docs'} or path.name.lower().startswith(('readme', 'changelog')):
                raise RuntimeError('agent artifacts/product docs may not enter refactor commits: ' + name)
            if name.startswith('lib/') and len(path.parts) > 1:
                scopes.add(path.parts[1])
        if len(scopes) > 1:
            raise RuntimeError('different layer topics must be separate atomic commits')
        assigned.extend(topic['paths'])
    if len(assigned) != len(set(assigned)) or set(assigned) != set(changed):
        raise RuntimeError('every changed path must belong to exactly one explicit atomic commit topic')
    if not all(isinstance(value[key], list) for key in ('fixed', 'backend', 'warnings', 'blockers', 'tests')):
        raise RuntimeError('invalid implementation report lists')
    if value['blockers']:
        raise RuntimeError('unresolved feature blockers prohibit automatic merge; see implementation manifest')


def test_commands(root, selections):
    result = []
    for selection in selections:
        layer, files = selection['layer'], selection['files']
        if layer not in {'common', 'admin', 'form', 'merchant', 'provider'} or not files or len(files) > 200:
            raise RuntimeError('tests require a finite nonempty native layer/file selection')
        resolved = []
        for name in files:
            path = Path(name)
            if path.is_absolute() or '..' in path.parts or not name.startswith('lib/' + layer + '-layer/') or not name.endswith(('.test.ts', '.spec.ts', '.test.tsx', '.spec.tsx')) or not (root / path).is_file() or (root / path).is_symlink():
                raise RuntimeError('test path is not an existing native test for the selected layer: ' + name)
            resolved.append(str(root / path))
        variants = ({'form:classic': [], 'form:exchange': []} if layer == 'form' else {layer: []})
        for name, resolved_path in zip(files, resolved):
            variant = ('form:exchange' if name.startswith('lib/form-layer/ui/exchange/')
                       else 'form:classic') if layer == 'form' else layer
            variants[variant].append(resolved_path)
        for variant, selected_files in variants.items():
            if selected_files:
                result.append((layer, ['npm', 'run', 'test:' + variant, '--', *selected_files,
                                      '--maxWorkers=1', '--no-file-parallelism', '--maxConcurrency=1', '--retry=0']))
    return result


class CheckFailed(RuntimeError):
    def __init__(self, message, source=False, kind=None):
        super().__init__(message)
        self.source = source
        self.kind = kind or ('source_failure' if source else 'infrastructure_failure')


def checked(root, command, log, env=None, report=None):
    names = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z', '--',
                                     '**/.nuxtrc', '.nuxtrc']).decode().split('\0')
    before = {name: (root / name).read_bytes() if (root / name).exists() else None
              for name in names if name}
    with log.open('w') as stream:
        result = subprocess.run(command, cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT)
    mutated = []
    for name, previous in before.items():
        path = root / name
        current = path.read_bytes() if path.exists() else None
        if current != previous:
            mutated.append(name)
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(previous)
    if mutated:
        raise CheckFailed('tracked .nuxtrc mutated; restored pre-command contents; environment attempt stopped: '
                          + ', '.join(mutated))
    text = log.read_text(errors='replace')
    data = None
    if report is not None and report.is_file():
        try:
            data = json.loads(report.read_text())
        except (ValueError, OSError):
            pass
    lifecycle = []
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get('event') in {'deferred', 'admitted', 'workload_start', 'completed'}:
            lifecycle.append(item)
    never_started = (len(lifecycle) == 1 and lifecycle[0].get('event') == 'deferred'
                     and lifecycle[0].get('phase') == 'admission'
                     and lifecycle[0].get('admitted') is False
                     and lifecycle[0].get('workload_started') is False)
    if result.returncode:
        resource = (result.returncode not in {1, 2, 75} or any(s in text.lower() for s in
                    ('out of memory', 'heap out of memory', 'killed process', 'timed out',
                     'guarded-run: refusing', 'prepare exited', 'environment not ready',
                     "['npm', 'ci'"))
                    or bool(re.search(r'"oom(?:_kill)?"\s*:\s*[1-9]', text)))
        source = not resource and result.returncode in {1, 2} and (
            bool(re.search(r'error TS\d+|FAIL |AssertionError|Failed to resolve import|Failed to load url|Cannot find module', text))
            or isinstance(data, dict) and (data.get('numFailedTests', 0) > 0
                                          or data.get('numFailedTestSuites', 0) > 0))
        kind = ('deferred' if result.returncode == 75 and never_started else
                'resource_failure' if resource else 'source_failure' if source else 'infrastructure_failure')
        raise CheckFailed(f'check exited {result.returncode} ({kind}): {log}; no resource retry',
                          source=source, kind=kind)
    if report is not None and (not isinstance(data, dict) or data.get('success') is not True
                               or data.get('numTotalTests', 0) <= 0 or data.get('numFailedTests') != 0):
        raise CheckFailed('native test report has no successful executed cases: ' + str(report),
                          kind='contract_failure')
    return {'command': command, 'exit': 0, 'log': str(log), 'sha256': sha256(log)}


def ci_requirements(root, current):
    source = (root / '.gitlab-ci.yml').read_text()
    base = git(root, 'show', current['merge_base'] + ':.gitlab-ci.yml') + '\n'
    return required_jobs(source, current['paths']) | required_jobs(base, current['paths'])


def verify_ui(root, current, manifest):
    if needs_ui(current, manifest):
        raise RuntimeError('changed UI requires actual owned runtime scenarios/screenshots on final runtime bytes')
    for name in manifest['ui'].get('screenshots', []):
        path = Path(name)
        if not path.is_absolute():
            path = root / path
        if not path.resolve().is_relative_to(root / '.superpowers') or path.is_symlink():
            raise RuntimeError('UI screenshot must be an owned local artifact')
        with path.open('rb') as stream:
            header = stream.read(24)
        if header[:8] != b'\x89PNG\r\n\x1a\n' or len(header) != 24 or not all(struct.unpack('>II', header[16:24])):
            raise RuntimeError('UI artifact is not a nonzero PNG frame')


def verify_local(root, current, manifest, run):
    required = ci_requirements(root, current)
    commands = test_commands(root, manifest['tests'])
    selected = {layer for layer, _ in commands}
    if not manifest['tests'] and required and not manifest.get('test_selection'):
        raise RuntimeError('empty local test selection needs an impact-based reason; server CI remains mandatory')
    proofs = []
    env = {**os.environ, 'TZ': 'Europe/Moscow', 'NODE_ENV': 'test', 'CONSOLA_LEVEL': '0'}
    identity = {'source_key': current['source_key'], 'policy': policy_key(root),
                'manifest_sha256': sha256(run / 'implementation.json'), 'required_ci': sorted(required),
                'environment_sha256': hashlib.sha256(json.dumps(dict(os.environ), sort_keys=True).encode()).hexdigest()}
    checkpoint = run / 'progress.json'
    if checkpoint.is_symlink():
        raise RuntimeError('check progress must not be a symlink')
    progress = json.loads(checkpoint.read_text()) if checkpoint.is_file() else {}
    if progress.get('identity') != identity:
        progress = {'identity': identity, 'checks': [], 'next': None}

    def perform(name, command, environment=None, test_report=False):
        selection = {'name': name, 'command': command}
        index = len(proofs)
        if index < len(progress['checks']):
            completed = progress['checks'][index]
            if completed['selection'] != selection:
                raise RuntimeError('checkpointed check selection changed; no stale reuse')
            validate_check_evidence(completed['proof'], run)
            proofs.append(completed['proof'])
            return
        pending = progress['next']
        if pending and (pending['selection'] != selection or pending['status'] != 'pending'):
            raise RuntimeError('previous check started or has unknown outcome; no automatic retry')
        progress['next'] = {'selection': selection, 'status': 'running'}
        save(checkpoint, progress)
        report = run / (name + '.json') if test_report else None
        actual = [*command, '--reporter=json', '--outputFile=' + str(report)] if test_report else command
        try:
            proof = checked(root, actual, run / (name + '.log'), environment, report=report)
        except CheckFailed as failure:
            progress['next']['status'] = 'pending' if failure.kind == 'deferred' else 'failed'
            save(checkpoint, progress)
            raise
        if test_report:
            data = json.loads(report.read_text())
            proof.update(report=str(report), report_sha256=sha256(report), tests=data['numTotalTests'])
        proofs.append(proof)
        progress['checks'].append({'selection': selection, 'proof': proof})
        progress['next'] = None
        save(checkpoint, progress)

    apps = {TYPECHECK_APPS[name] for name in required if name.startswith('Typecheck · ')}
    roles = {('form' if app == 'exchange-form' else app.removeprefix('payscrow-')) for app in apps}
    for role in sorted(roles | selected):
        perform('prepare-' + role, [str(PROJECTS / 'project-environment'), '--profile',
                                   role + '-tests', '--install', '--prepare'])
    for number, (_layer, command) in enumerate(commands):
        guarded = [str(GUARD), '--need', '3G', '--wait', '60', '--exclusive-key', str(root), '--', *command]
        perform(f'test-{number}', guarded, env, test_report=True)
    for app in sorted(apps):
        perform('typecheck-' + app, [sys.executable, str(HERE / 'typecheck'), app])
    if len(proofs) != len(progress['checks']) or progress['next']:
        raise RuntimeError('checkpoint contains an unexpected check; no stale reuse')
    return {'source': current, 'checks': proofs, 'ui': manifest['ui'], 'required_ci': sorted(required),
            'manifest_sha256': identity['manifest_sha256']}

def validate_check_evidence(check, run):
    for key, hash_key in (('log', 'sha256'), ('report', 'report_sha256')):
        if key not in check:
            continue
        artifact = Path(check[key])
        if not artifact.resolve().is_relative_to(run.resolve()) or artifact.is_symlink() or sha256(artifact) != check[hash_key]:
            raise RuntimeError('cached check evidence changed; no stale phase reuse')



def cached_checks(root, current, run):
    path = run / 'code-proof.json'
    if not path.is_file() or path.is_symlink():
        return None
    proof = json.loads(path.read_text())
    if proof['source']['source_key'] != current['source_key']:
        return None
    for check in proof['checks']:
        validate_check_evidence(check, run)
    return proof

def render_report(root, manifest, proof):
    lines = ['# Feature refactor report', '',
             'Source HEAD: `' + proof['source']['head'] + '`; content: `' + proof['source']['source_key'] + '`.', '']
    if 'review' in manifest:
        lines += ['## Область review и направление изменений', '']
        for scope in manifest['review']['coverage']:
            lines += ['- ' + scope['scenario'] + ': ' + ', '.join(scope['paths'])]
            for comparison in scope['comparisons']:
                lines += ['  - ' + comparison['direction'] + ': ' + comparison['decision']]
        lines.append('')
    for title, key in (('Исправлено', 'fixed'), ('Передать backend', 'backend'), ('Ограничения', 'warnings')):
        lines += ['## ' + title, '']
        for item in manifest[key]:
            text = '; '.join(str(k) + ': ' + str(v) for k, v in item.items()) if isinstance(item, dict) else str(item)
            lines.append('- ' + text)
        if not manifest[key]:
            lines.append('Нет.')
        lines.append('')
    lines += ['## Проверки', '']
    for check in proof['checks']:
        log = Path(check['log'])
        lines.append('- `' + ' '.join(check['command']) + '`: exit ' + str(check['exit'])
                     + ('; tests ' + str(check['tests']) if 'tests' in check else '')
                     + '; [' + str(log) + '](<' + log.as_uri() + '>).')
    ui = manifest['ui']
    lines += ['', 'UI: ' + str(ui.get('status', 'not applicable; no changed UI')) + '.']
    for scenario in ui.get('scenarios', []):
        lines.append('- ' + str(scenario))
    for name in ui.get('screenshots', []):
        image = Path(name)
        if not image.is_absolute():
            image = root / image
        lines.append('- [' + str(image) + '](<' + image.as_uri() + '>)')
    lines += ['', '## Доставка', '', 'Pending: требуется открытый MR и exact-SHA CI; merge отдельно не подразумевается.', '']
    return '\n'.join(lines)



def commit_topics(root, manifest):
    for topic in manifest['commits']:
        print('feature-finalize: commit topic: ' + topic['message'], flush=True)
        subprocess.run(['git', 'add', '--', *topic['paths']], cwd=root, check=True)
        staged = git(root, 'diff', '--cached', '--name-only', '--no-renames').splitlines()
        if set(staged) != set(topic['paths']):
            raise RuntimeError('unexpected staged paths; no blanket staging or commit')
        subprocess.run(['wt', 'commit', '--', '-m', topic['message']], cwd=root, check=True)


def find_mr(root, branch, iid=None):
    forge = Forge(root)
    if iid is not None:
        return forge.mr(iid)
    values = forge.pages('projects/:id/merge_requests?state=opened&target_branch=dev&source_branch=' + quote(branch, safe=''))
    if len(values) > 1:
        raise RuntimeError('multiple open MRs for feature; select one explicitly')
    return values[0] if values else None


def owner_opt_out(root, current, path, manifest_path, reason):
    if not reason or not reason.strip() or manifest_path is None:
        raise RuntimeError('--skip-sol requires the owner opt-out reason and --manifest with native test/UI selections')
    manifest = json.loads(Path(manifest_path).read_text())
    validate_manifest(root, manifest, [])
    run = path / ('owner-opt-out-' + str(time.time_ns()))
    run.mkdir(mode=0o700)
    save(run / 'implementation.json', manifest)
    key = policy_key(root)
    proof = verify_local(root, current, manifest, run)
    verify_ui(root, current, manifest)
    if snapshot(root) != current or policy_key(root) != key:
        raise RuntimeError('inputs changed during owner opt-out verification; no stale receipt')
    proof['sol'] = {'status': 'not-run', 'owner_opt_out': reason.strip()}
    (run / 'report.md').write_text(render_report(root, manifest, proof) +
                                  '\nSol: NOT RUN; explicit owner opt-out: ' + reason.strip() + '\n')
    save(run / 'verification.json', proof)
    save(path / 'receipt.json', receipt_for(current, key, run / 'verification.json'))


def ensure_manual_merge(root, mr):
    if mr.get('merge_when_pipeline_succeeds') is True or mr.get('auto_merge_enabled') is True:
        forge = Forge(root)
        subprocess.run([forge.binary, 'api', '--method', 'POST',
                        f'projects/:id/merge_requests/{mr["iid"]}/cancel_merge_when_pipeline_succeeds'],
                       cwd=root, check=True, stdout=subprocess.PIPE, timeout=60)
        mr = forge.mr(mr['iid'])
    if mr.get('merge_when_pipeline_succeeds') is not False or mr.get('auto_merge_enabled', False) is not False:
        raise RuntimeError('cannot confirm auto-merge disabled; no unattended delivery')
    return mr


def needs_ui(current, manifest):
    ui = manifest['ui']
    required = ui.get('required') is True or any(
        Path(name).suffix in {'.vue', '.css', '.scss', '.sass', '.less'} for name in current['paths'])
    return required and (ui.get('required') is not True or ui.get('status') != 'verified'
                         or ui.get('runtime_key') != current['runtime_key']
                         or not ui.get('scenarios') or not ui.get('screenshots'))


def await_ui(root, run, key, attempt, post_commit=False, phase='awaiting_ui', expected_remote_sha=None):
    artifacts = {name: sha256(run / name) for name in
                 ('source.json', 'feature.diff', 'code-rules.md', 'review-context.json', 'plan.md', 'implementation.json')}
    if (run / 'code-proof.json').is_file():
        artifacts['code-proof.json'] = sha256(run / 'code-proof.json')
    for checkpoint in run.glob('checks-*/progress.json'):
        artifacts[str(checkpoint.relative_to(run))] = sha256(checkpoint)
    state = {'schema': 1, 'phase': phase, 'root': str(root),
             'source': snapshot(root, allow_dirty=True), 'policy': key,
             'attempt': attempt, 'post_commit': post_commit, 'artifacts': artifacts,
             'expected_remote_sha': expected_remote_sha}
    save(run / 'state.json', state)
    command = ['wt', 'finalize', '--', '--resume', str(run)]
    if expected_remote_sha is not None:
        command += ['--expected-remote-sha', expected_remote_sha]
    if phase == 'awaiting_ui':
        command += ['--ui-proof', str(run / 'ui-proof.json')]
    print(json.dumps({'state': phase, 'run': str(run), 'resume': command,
                      'required': ('Owned UI scenarios/screenshots on this exact source.'
                                   if phase == 'awaiting_ui' else 'Resource admission; workload never started.'),
                      'delivery': 'pending; no delivery yet'}), flush=True)
    return 0


def load_resume(root, path, requested, current, key, expected_remote_sha=None):
    run = Path(requested).absolute()
    if run.parent != path or any(p.is_symlink() for p in (run, *run.parents)):
        raise RuntimeError('resume requires an owned direct run directory, without symlinks')
    state = json.loads((run / 'state.json').read_text())
    if (state.get('schema') != 1 or state.get('phase') not in {'awaiting_ui', 'awaiting_checks'}
            or state.get('root') != str(root) or state.get('source') != current or state.get('policy') != key
            or state.get('attempt') not in (0, 1) or not isinstance(state.get('post_commit'), bool)
            or state.get('expected_remote_sha') != expected_remote_sha):
        raise RuntimeError('resume source/policy/state drift; failed or running attempts cannot be replayed')
    expected = {'source.json', 'feature.diff', 'code-rules.md', 'review-context.json', 'plan.md', 'implementation.json'}
    if 'code-proof.json' in state.get('artifacts', {}):
        expected.add('code-proof.json')
    expected.update(str(checkpoint.relative_to(run)) for checkpoint in run.glob('checks-*/progress.json'))
    if set(state.get('artifacts', {})) != expected or any(
            (run / name).is_symlink() or sha256(run / name) != digest
            for name, digest in state['artifacts'].items()):
        raise RuntimeError('resume artifact drift; no stale phase reuse')
    return run, state


def finish(root, iid=None, dry_run=False, keep_source=False, skip_sol=False, manifest=None, reason=None,
           merge=False, sessions=None, resume=None, ui_proof=None, expected_remote_sha=None):
    if (resume and skip_sol) or (ui_proof and not resume):
        raise RuntimeError('--ui-proof requires --resume; --resume cannot change the Sol opt-out contract')
    root = owned_root(root)
    initial = snapshot(root, allow_dirty=bool(resume))
    if dry_run:
        print(json.dumps({'branch': initial['branch'], 'source': initial, 'hotfix': hotfix(initial['branch']),
                          'model': MODEL, 'thinking': 'high', 'service_tier': 'priority',
                          'skip_sol': skip_sol, 'keep_source_branch': keep_source,
                          'expected_remote_sha': expected_remote_sha,
                          'current_receipt': current_receipt(root, initial),
                          'required_ci': sorted(ci_requirements(root, initial)),
                          'plan_command': agent_command(root, [], True),
                          'merge': merge, 'owner_context': str(context_path(root)),
                          'delivery': 'wt push -> open MR -> exact-SHA CI -> ' +
                                      ('explicit merge -> safe cleanup' if merge else 'STOP; no merge, auto-merge disabled, source preserved')}, ensure_ascii=False))
        return 0
    if sessions:
        store_context(root, sessions)
    load_context(root)
    path = directory(root)
    with lock(path):
        refresh(root)
        initial = snapshot(root, allow_dirty=bool(resume))
        if not initial['paths']:
            raise RuntimeError('feature diff is empty; no new feature to finalize')
        mr = find_mr(root, initial['branch'], iid)
        publication = publication_plan(root, initial, expected_remote_sha)
        if mr:
            validate_mr(mr, initial['branch'], publication['remote_sha'], require_mergeable=False)
            mr = ensure_manual_merge(root, mr)
        if skip_sol:
            owner_opt_out(root, initial, path, manifest, reason)
        elif not resume and documentation_only(root, initial) and not current_receipt(root, initial):
            review_documentation(root, initial, path)
        if not current_receipt(root, initial):
            key = policy_key(root)
            prompt = (HERE / 'finalize-prompt.md').read_text() + '\n\n' + (HERE / 'review-contract.md').read_text()
            resumed, post_commit, start_attempt = bool(resume), False, 0
            if resumed:
                run, saved = load_resume(root, path, resume, initial, key, expected_remote_sha)
                start_attempt, post_commit = saved['attempt'], saved['post_commit']
                manifest = json.loads((run / 'implementation.json').read_text())
                if ui_proof:
                    proof_path = Path(ui_proof).absolute()
                    if not proof_path.resolve().is_relative_to(root / '.superpowers') or proof_path.is_symlink():
                        raise RuntimeError('UI proof must be an owned local artifact')
                    supplied = json.loads(proof_path.read_text())
                    if set(supplied) - {'ui', 'review'} or 'ui' not in supplied:
                        raise RuntimeError('UI proof may update only ui and its source-bound review')
                    manifest.update(supplied)
            else:
                run = path / (str(time.time_ns()) + '-' + initial['head'][:12])
                run.mkdir(mode=0o700)
                inputs = feature_diff(root, initial)
                if len(inputs) > MAX_INPUT:
                    raise RuntimeError('full feature diff exceeds the reviewed input bound; never truncate')
                (run / 'feature.diff').write_bytes(inputs)
                save(run / 'source.json', initial)
                (run / 'code-rules.md').write_bytes((root / '.agents/rules/p2p-code.md').read_bytes())
                (run / 'review-context.json').write_bytes(context_path(root).read_bytes())
                (run / 'plan-request.md').write_text(prompt + '\n\nPHASE: PLAN ONLY. Read tools only. Return a concrete refactor plan, findings, backend handoffs and exact native test selections. Do not modify code.\n')
                save(run / 'state.json', {'phase': 'plan_running'})
                run_agent(root, [run / 'plan-request.md', run / 'source.json', run / 'feature.diff', run / 'code-rules.md',
                                 run / 'review-context.json'], run / 'plan.md', True)
                if snapshot(root) != initial or policy_key(root) != key:
                    raise RuntimeError('plan phase changed source/policy; stop rather than review mixed revisions')
            for attempt in range(start_attempt, 2):
                if not resumed:
                    (run / 'implementation.json').unlink(missing_ok=True)
                    save(run / 'state.json', {'phase': 'source_running', 'attempt': attempt})
                    (run / 'implement-request.md').write_text(prompt + '\n\nPHASE: IMPLEMENT SOURCE ONLY. Apply the saved plan. Do not start browsers, unit tests/typecheck, commit, push or merge. Controller/main owns subsequent checks and UI. Never edit .gitlab-ci.yml or workflow helpers. Save the complete JSON manifest at ' + str(run / 'implementation.json') + '. Include source_key from feature-finalize --source-key after all edits. UI evidence not already valid for these bytes must be pending, not verified. Leave edits unstaged. Prior diagnostics are in ' + str(run) + '.\n')
                    phase_head = git(root, 'rev-parse', 'HEAD')
                    run_agent(root, [run / 'implement-request.md', run / 'source.json', run / 'feature.diff', run / 'code-rules.md',
                                     run / 'review-context.json', run / 'plan.md'], run / f'implementation-{attempt}.log', False)
                    if git(root, 'rev-parse', 'HEAD') != phase_head:
                        raise RuntimeError('implementation must not create commits; source identity changed')
                    manifest = json.loads((run / 'implementation.json').read_text())
                    post_commit = False
                resumed = False
                if policy_key(root) != key or git(root, 'diff', '--cached', '--name-only'):
                    raise RuntimeError('implementation changed policy or staged paths outside controller')
                if not post_commit:
                    validate_manifest(root, manifest, changed_paths(root))
                if '.gitlab-ci.yml' in changed_paths(root):
                    raise RuntimeError('refactor must not change server-side CI')
                pending = snapshot(root, allow_dirty=True)
                save(run / 'implementation.json', manifest)
                save(run / 'state.json', {'phase': 'checks_running', 'attempt': attempt})
                try:
                    proof = cached_checks(root, pending, run)
                    if proof is None:
                        checks = run / (f'checks-{attempt}' + ('-after-hooks' if post_commit else ''))
                        checks.mkdir(exist_ok=True)
                        save(checks / 'implementation.json', manifest)
                        proof = verify_local(root, pending, manifest, checks)
                        save(run / 'code-proof.json', proof)
                    if snapshot(root, allow_dirty=True) != pending or policy_key(root) != key:
                        raise RuntimeError('checked inputs changed during verification; no stale receipt')
                    if not post_commit:
                        commit_topics(root, manifest)
                    post_commit = True
                    # Existing explicit batches retain their cumulative hook gate.
                    state = root / '.superpowers/batch/state.json'
                    if state.exists():
                        result = subprocess.run(['wt', 'batch', '--', 'verify'], cwd=root)
                        if result.returncode == 2:
                            fixes = changed_paths(root)
                            if fixes:
                                subprocess.run(['git', 'restore', '--staged', '--', *fixes], cwd=root, check=True)
                            raise CheckFailed('successful batch autofix needs atomic commits and refreshed UI proof', source=True)
                        if result.returncode:
                            raise RuntimeError('batch verification failed; inspect evidence, no resource retry or hook bypass')
                    current = snapshot(root)
                    if current['source_key'] != pending['source_key']:
                        checks = run / f'checks-{attempt}-after-hooks'
                        checks.mkdir(exist_ok=True)
                        save(checks / 'implementation.json', manifest)
                        proof = verify_local(root, current, manifest, checks)
                        save(run / 'code-proof.json', proof)
                    if needs_ui(current, manifest):
                        return await_ui(root, run, key, attempt, post_commit=True, expected_remote_sha=expected_remote_sha)
                    verify_ui(root, current, manifest)
                    try:
                        validate_review(root, manifest.get('review'), current['paths'], load_context(root))
                    except RuntimeError as error:
                        raise CheckFailed(str(error), source=True) from error
                    proof.update(source=current, ui=manifest['ui'])
                except CheckFailed as failure:
                    if failure.kind == 'deferred':
                        return await_ui(root, run, key, attempt, post_commit, phase='awaiting_checks', expected_remote_sha=expected_remote_sha)
                    save(run / 'state.json', {'phase': 'failed', 'kind': failure.kind, 'attempt': attempt})
                    if not failure.source or attempt == 1:
                        raise
                    (run / 'source-failure.txt').write_text(str(failure))
                    print('feature-finalize: source check failed; one bounded correction pass, no resource retry', flush=True)
                    post_commit = False
                    continue
                if snapshot(root) != current or policy_key(root) != key:
                    raise RuntimeError('checked inputs changed during final hooks; no stale receipt')
                (run / 'report.md').write_text(render_report(root, manifest, proof))
                save(run / 'verification.json', proof)
                save(path / 'receipt.json', receipt_for(current, key, run / 'verification.json'))
                save(run / 'state.json', {'phase': 'verified', 'source': current, 'policy': key})
                print('feature-finalize: refactor report: ' + str(run / 'report.md'), flush=True)
                break
        current = snapshot(root)
        if not current_receipt(root, current):
            raise RuntimeError('no current feature review receipt; merge is blocked')
        if remote_tip(root, current['branch']) != publication['remote_sha']:
            raise RuntimeError('remote tip changed during review; inspect new commits before publishing')
        subprocess.run(['wt', 'push', '--', *publication['options'], 'origin', current['branch']], cwd=root, check=True)
        remote = git(root, 'ls-remote', '--heads', 'origin', 'refs/heads/' + current['branch']).split()
        if not remote or remote[0] != current['head']:
            raise RuntimeError('published source SHA is not the reviewed HEAD')
        mr = find_mr(root, current['branch'], iid)
        if mr is None:
            subprocess.run(['wt', 'mr', '--', 'create', '--target-branch', 'dev', '--source-branch', current['branch'],
                            '--title', current['branch'], '--fill', '--yes'], cwd=root, check=True)
            mr = find_mr(root, current['branch'])
        if mr is None:
            raise RuntimeError('MR creation did not yield an unambiguous open MR')
        validate_mr(mr, current['branch'], current['head'], require_mergeable=merge)
        mr = ensure_manual_merge(root, mr)
        ci = wait_for_ci(root, mr['iid'], current['branch'], current['head'], ci_requirements(root, current), require_mergeable=merge)
        save(path / 'ci.json', ci)
        if snapshot(root) != current or not current_receipt(root, current):
            raise RuntimeError('source/target/owner context changed before delivery; review again')
        if not merge:
            mr = ensure_manual_merge(root, Forge(root).mr(mr['iid']))
            validate_mr(mr, current['branch'], current['head'], require_mergeable=False)
            delivery = {'state': 'mr-ready', 'mr': mr['iid'], 'sha': current['head'],
                        'target': 'dev', 'url': mr.get('web_url'), 'source_preserved': True,
                        'auto_merge': False, 'ci': ci, 'review_receipt': str(path / 'receipt.json')}
            save(path / 'delivery.json', delivery)
            receipt = json.loads((path / 'receipt.json').read_text())
            report = Path(receipt['verification']).parent / 'report.md'
            report.write_text(report.read_text().rsplit('## Доставка', 1)[0] +
                              '## Доставка\n\nMR !' + str(mr['iid']) +
                              ' открыт; merge не выполнялся. Auto-merge выключен, source сохранён. SHA `' +
                              current['head'] + '`, exact-SHA CI подтверждён.\n')
            print(json.dumps(delivery, ensure_ascii=False))
            return 0
        subprocess.run(['wt', 'mr', '--', 'merge', str(mr['iid']), '--sha=' + current['head'], '--yes',
                        *(['--keep-source-branch'] if keep_source else [])], cwd=root, check=True)
        merged = Forge(root).mr(mr['iid'])
        if merged.get('state') != 'merged' or merged.get('sha') != current['head']:
            raise RuntimeError('merge not confirmed for the reviewed MR SHA; source preserved')
        refresh(root)
        result_sha = merged.get('squash_commit_sha') or merged.get('merge_commit_sha') or current['head']
        subprocess.run(['git', 'merge-base', '--is-ancestor', result_sha, 'refs/remotes/origin/dev'], cwd=root, check=True)
        remote_preserved = bool(git(root, 'ls-remote', '--heads', 'origin', 'refs/heads/' + current['branch']))
        save(path / 'delivery.json', {'state': 'merged', 'mr': merged['iid'], 'sha': current['head'],
                                     'target': 'dev', 'result_sha': result_sha, 'source_preserved': True,
                                     'remote_source_preserved': remote_preserved,
                                     'ci': ci, 'review_receipt': str(path / 'receipt.json')})
        if current_receipt(root, current):
            receipt = json.loads((path / 'receipt.json').read_text())
            report = Path(receipt['verification']).parent / 'report.md'
            text = report.read_text().rsplit('## Доставка', 1)[0]
            report.write_text(text + '## Доставка\n\nMerged в `dev`: MR !' + str(merged['iid'])
                              + ', source SHA `' + current['head'] + '`, result `' + result_sha
                              + '`. Exact-SHA CI подтверждён; local worktree сохранён. Remote source '
                              + ('сохранён (opt-out или cleanup deferred).' if remote_preserved else 'удалён после проверки ref-consumers.') + '\n')
        print(json.dumps({'state': 'merged', 'target': 'dev', 'mr': merged['iid'], 'sha': current['head'],
                          'report': str(path / 'delivery.json'), 'local_source_preserved': True,
                          'remote_source_preserved': remote_preserved}, ensure_ascii=False))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mr', type=int)
    parser.add_argument('--merge', action='store_true', help='only after a separate explicit owner instruction to merge')
    parser.add_argument('--session', type=Path, action='append', help='originating owner transcript; repeat for explicit parent lineage')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--source-key', action='store_true', help='read-only complete source content fingerprint')
    parser.add_argument('--runtime-key', action='store_true', help='UI fingerprint excluding only native test source files')
    parser.add_argument('--keep-source-branch', action='store_true', help='preserve remote source after merge')
    parser.add_argument('--skip-sol', action='store_true', help='only for an explicit owner opt-out; native checks still required')
    parser.add_argument('--manifest', type=Path, help='native test/UI selections for --skip-sol')
    parser.add_argument('--reason', help='verbatim owner reason/request to skip Sol')
    parser.add_argument('--resume', type=Path, help='continue an unchanged awaiting_ui run; never replay failed workloads')
    parser.add_argument('--ui-proof', type=Path, help='owned JSON with source-bound ui and optional refreshed review')
    parser.add_argument('--expected-remote-sha', help='exact observed remote task SHA for a separately authorized published rebase')
    args = parser.parse_args()
    root = Path(git(Path.cwd(), 'rev-parse', '--show-toplevel'))
    if args.source_key or args.runtime_key:
        print((runtime_key if args.runtime_key else source_key)(owned_root(root)))
        return 0
    return finish(root, args.mr, args.dry_run, args.keep_source_branch, args.skip_sol,
                  args.manifest, args.reason, merge=args.merge, sessions=args.session,
                  resume=args.resume, ui_proof=args.ui_proof, expected_remote_sha=args.expected_remote_sha)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        print('feature-finalize: blocked: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
