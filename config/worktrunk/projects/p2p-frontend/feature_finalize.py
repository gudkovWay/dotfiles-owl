"""Feature-only plan/refactor/check/commit/push/MR orchestration outside Git hooks."""
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

from merge_readiness import Forge, required_jobs, validate_mr, wait_for_ci

HERE = Path(__file__).resolve().parent
PROJECTS = HERE.parent
GUARD = PROJECTS / 'guarded-run'
MODEL = 'openai-codex/gpt-6.1-sol'
MODEL_SECONDS = 480
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
            'target': target, 'merge_base': base, 'source_key': source_key(root),
            'paths': sorted(set(filter(None, names)))}


def feature_diff(root, current):
    return subprocess.check_output(['git', '-C', str(root), 'diff', '--binary', '--no-ext-diff',
                                    '--no-textconv', '--no-renames', current['merge_base'], current['head']])


def policy_key(root):
    paths = [Path(__file__), HERE / 'merge_readiness.py', HERE / 'finalize-prompt.md',
             HERE / 'typecheck', PROJECTS / 'project-environment', PROJECTS / 'ui-session',
             root / '.claude/commands/refactor.md']
    return hashlib.sha256(''.join(str(p) + '\0' + sha256(p) for p in paths).encode()).hexdigest()


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
        proof = Path(value['verification'])
        if not proof.is_relative_to(root / '.superpowers/finalize') or proof.is_symlink():
            return False
        return receipt_matches(value, current, policy_key(root), proof)
    except (OSError, ValueError, TypeError, KeyError):
        return False


def refresh(root):
    subprocess.run(['git', 'fetch', 'origin', '+refs/heads/dev:refs/remotes/origin/dev'], cwd=root, check=True)


def agent_command(root, inputs, plan):
    tools = 'read,glob,grep' if plan else 'read,glob,grep,edit,write,bash,todo,browser,python'
    return ['omp', '--print', '--model=' + MODEL, '--thinking=high', '--no-prewalk',
            '--no-extensions', '--no-title', '--no-lsp', '--auto-approve', '--max-time=' + str(MODEL_SECONDS),
            '--cwd=' + str(root), '--tools=' + tools, *('@' + str(path) for path in inputs)]


def run_agent(root, inputs, output, plan):
    command = [str(GUARD), '--need', '2G' if plan else '6G', '--wait', '60',
               '--exclusive-key', str(root), '--', *agent_command(root, inputs, plan)]
    with output.open('w') as log:
        result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f'Sol phase exited {result.returncode}; no automatic retry; evidence: {output}')
    if output.stat().st_size == 0:
        raise RuntimeError('Sol returned no output; no completion proof: ' + str(output))


def changed_paths(root):
    tracked = subprocess.check_output(['git', '-C', str(root), 'diff', '--name-only', '--no-renames', '-z', 'HEAD']).decode().split('\0')
    new = subprocess.check_output(['git', '-C', str(root), 'ls-files', '--others', '--exclude-standard', '-z']).decode().split('\0')
    return sorted(set(filter(None, tracked + new)))


def source_key(root):
    """Content identity remains stable when the same bytes are committed."""
    names = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z',
                                     '--cached', '--others', '--exclude-standard']).decode().split('\0')
    names += [str(path.relative_to(root)) for path in root.glob('apps/*/.env')]
    digest = hashlib.sha256()
    for name in sorted(set(filter(None, names))):
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
        variants = ['form:classic', 'form:exchange'] if layer == 'form' else [layer]
        for variant in variants:
            result.append((layer, ['npm', 'run', 'test:' + variant, '--', *resolved,
                                  '--maxWorkers=1', '--no-file-parallelism', '--maxConcurrency=1', '--retry=0']))
    return result


class CheckFailed(RuntimeError):
    def __init__(self, message, source=False):
        super().__init__(message)
        self.source = source


def checked(root, command, log, env=None):
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
    if result.returncode:
        resource = (result.returncode not in {1, 2} or any(s in text.lower() for s in
                    ('out of memory', 'heap out of memory', 'killed process', 'timed out',
                     'guarded-run: refusing', 'guarded-run: deferred', 'prepare exited', 'environment not ready',
                     "['npm', 'ci'"))
                    or bool(re.search(r'"oom(?:_kill)?"\s*:\s*[1-9]', text)))
        source = not resource and bool(re.search(r'error TS\d+|FAIL |AssertionError|AssertionError:|Failed to resolve import|Failed to load url|Cannot find module', text))
        raise CheckFailed(f'check exited {result.returncode}: {log}; resource/unknown failures are not retried', source=source)
    return {'command': command, 'exit': 0, 'log': str(log), 'sha256': sha256(log)}


def ci_requirements(root, current):
    source = (root / '.gitlab-ci.yml').read_text()
    base = git(root, 'show', current['merge_base'] + ':.gitlab-ci.yml') + '\n'
    return required_jobs(source, current['paths']) | required_jobs(base, current['paths'])


def verify_local(root, current, manifest, run):
    ui_required = any(Path(path).suffix in {'.vue', '.css', '.scss', '.sass', '.less'} for path in current['paths'])
    ui = manifest['ui']
    if ui_required and (ui.get('required') is not True or ui.get('status') != 'verified' or not ui.get('scenarios') or not ui.get('screenshots')):
        raise RuntimeError('changed UI requires actual owned runtime scenarios/screenshots; static review is not proof')
    if ui_required and ui.get('source_key') != source_key(root):
        raise CheckFailed('UI source bytes changed since capture; re-exercise the screen on final content', source=True)
    for name in ui.get('screenshots', []):
        path = Path(name)
        if not path.is_absolute():
            path = root / path
        if not path.resolve().is_relative_to(root / '.superpowers') or path.is_symlink():
            raise RuntimeError('UI screenshot must be an owned local artifact')
        with path.open('rb') as stream:
            header = stream.read(24)
        if header[:8] != b'\x89PNG\r\n\x1a\n' or len(header) != 24 or not all(struct.unpack('>II', header[16:24])):
            raise RuntimeError('UI artifact is not a nonzero PNG frame')
    required = ci_requirements(root, current)
    commands = test_commands(root, manifest['tests'])
    selected = {layer for layer, _ in commands}
    missing = {name.removeprefix('Tests · ').lower() for name in required if name.startswith('Tests · ')} - selected
    if missing:
        raise RuntimeError('plan must select directly affected native tests for CI layers: ' + ', '.join(sorted(missing)))
    proofs = []
    env = {**os.environ, 'TZ': 'Europe/Moscow', 'NODE_ENV': 'test', 'CONSOLA_LEVEL': '0'}
    roles = {name.removeprefix('Typecheck · ').lower() for name in required if name.startswith('Typecheck · ')}
    for role in sorted(roles | selected):
        profile = role + '-tests'
        proofs.append(checked(root, [str(PROJECTS / 'project-environment'), '--profile', profile, '--install', '--prepare'],
                              run / ('prepare-' + role + '.log')))
    for number, (layer, command) in enumerate(commands):
        report = run / f'test-{number}.json'
        command = [*command, '--reporter=json', '--outputFile=' + str(report)]
        guarded = [str(GUARD), '--need', '3G', '--wait', '60', '--exclusive-key', str(root), '--', *command]
        proofs.append(checked(root, guarded, run / f'test-{number}.log', env))
        data = json.loads(report.read_text())
        if data.get('success') is not True or data.get('numTotalTests', 0) <= 0 or data.get('numFailedTests') != 0:
            raise RuntimeError('native test report has no successful executed cases: ' + str(report))
        proofs[-1].update(report=str(report), report_sha256=sha256(report), tests=data['numTotalTests'])
    for role in sorted(roles):
        proofs.append(checked(root, [sys.executable, str(HERE / 'typecheck'), 'payscrow-' + role],
                              run / ('typecheck-' + role + '.log')))
    return {'source': current, 'checks': proofs, 'ui': ui, 'required_ci': sorted(required),
            'manifest_sha256': sha256(run / 'implementation.json')}

def render_report(root, manifest, proof):
    lines = ['# Feature refactor report', '',
             'Source HEAD: `' + proof['source']['head'] + '`; content: `' + proof['source']['source_key'] + '`.', '']
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
    lines += ['', '## Доставка', '', 'Pending: требуется exact-SHA MR CI и подтверждённый merge в dev.', '']
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


def finish(root, iid=None, dry_run=False):
    root = owned_root(root)
    initial = snapshot(root)
    if dry_run:
        print(json.dumps({'branch': initial['branch'], 'source': initial, 'hotfix': hotfix(initial['branch']),
                          'model': MODEL, 'thinking': 'high', 'current_receipt': current_receipt(root, initial),
                          'required_ci': sorted(ci_requirements(root, initial)),
                          'plan_command': agent_command(root, [], True),
                          'delivery': 'wt push -> exact-SHA MR CI -> wt mr merge; source preserved'}, ensure_ascii=False))
        return 0
    path = directory(root)
    with lock(path):
        refresh(root)
        initial = snapshot(root)
        if not initial['paths']:
            raise RuntimeError('feature diff is empty; no new feature to finalize')
        mr = find_mr(root, initial['branch'], iid)
        if mr:
            validate_mr(mr, initial['branch'], mr['sha'])
            subprocess.run(['git', 'fetch', 'origin', 'refs/heads/' + initial['branch']], cwd=root, check=True)
            subprocess.run(['git', 'merge-base', '--is-ancestor', mr['sha'], initial['head']], cwd=root, check=True)
        # Hotfixes skip Sol only; their author already owns local native proof.
        # Exact-SHA CI and apiBase/batch gates still run through wt mr.
        if not hotfix(initial['branch']) and not current_receipt(root, initial):
            run = path / (str(time.time_ns()) + '-' + initial['head'][:12])
            run.mkdir(mode=0o700)
            inputs = feature_diff(root, initial)
            if len(inputs) > MAX_INPUT:
                raise RuntimeError('full feature diff exceeds the reviewed input bound; split/review explicitly, never truncate')
            (run / 'feature.diff').write_bytes(inputs)
            (run / 'source.json').write_text(json.dumps(initial, indent=2))
            (run / 'refactor.md').write_bytes((root / '.claude/commands/refactor.md').read_bytes())
            prompt = (HERE / 'finalize-prompt.md').read_text()
            (run / 'plan-request.md').write_text(prompt + '\n\nPHASE: PLAN ONLY. Read tools only. Return a concrete refactor plan, findings, backend handoffs and exact native test selections. Do not ask for approval: the owner approved this feature finalization scope. Do not modify code.\n')
            key = policy_key(root)
            run_agent(root, [run / 'plan-request.md', run / 'source.json', run / 'feature.diff', run / 'refactor.md'], run / 'plan.md', True)
            if snapshot(root) != initial or policy_key(root) != key:
                raise RuntimeError('plan phase changed source/policy; stop rather than review mixed revisions')
            for attempt in range(2):
                (run / 'implement-request.md').write_text(prompt + '\n\nPHASE: IMPLEMENT. Apply the saved plan and exercise any changed UI through owned wt ui. Do not run unit tests/typecheck, commit, push or merge: the controller does these after you exit. Never edit .gitlab-ci.yml or workflow helpers. Save the complete JSON manifest at ' + str(run / 'implementation.json') + '. All code edits must be unstaged. Prior attempt diagnostics, if any, are in ' + str(run) + '.\n')
                phase_head = git(root, 'rev-parse', 'HEAD')
                run_agent(root, [run / 'implement-request.md', run / 'source.json', run / 'feature.diff', run / 'refactor.md', run / 'plan.md'], run / f'implementation-{attempt}.log', False)
                if git(root, 'rev-parse', 'HEAD') != phase_head:
                    raise RuntimeError('implementation must not create commits; source identity changed')
                if policy_key(root) != key or git(root, 'diff', '--cached', '--name-only'):
                    raise RuntimeError('implementation changed policy or staged paths outside controller')
                manifest = json.loads((run / 'implementation.json').read_text())
                validate_manifest(root, manifest, changed_paths(root))
                if '.gitlab-ci.yml' in changed_paths(root):
                    raise RuntimeError('refactor must not change server-side CI')
                pending = snapshot(root, allow_dirty=True)
                try:
                    checks = run / f'checks-{attempt}-before-commit'
                    checks.mkdir()
                    save(checks / 'implementation.json', manifest)
                    proof = verify_local(root, pending, manifest, checks)
                    if snapshot(root, allow_dirty=True) != pending or policy_key(root) != key:
                        raise RuntimeError('checked inputs changed during verification; no stale receipt')
                    commit_topics(root, manifest)
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
                        checks.mkdir()
                        save(checks / 'implementation.json', manifest)
                        proof = verify_local(root, current, manifest, checks)
                    proof['source'] = current
                except CheckFailed as failure:
                    if not failure.source or attempt == 1:
                        raise
                    (run / 'source-failure.txt').write_text(str(failure))
                    print('feature-finalize: source check failed; one bounded correction pass, no resource retry', flush=True)
                    continue
                if snapshot(root) != current or policy_key(root) != key:
                    raise RuntimeError('checked inputs changed during final hooks; no stale receipt')
                (run / 'report.md').write_text(render_report(root, manifest, proof))
                save(run / 'verification.json', proof)
                save(path / 'receipt.json', receipt_for(current, key, run / 'verification.json'))
                print('feature-finalize: refactor report: ' + str(run / 'report.md'), flush=True)
                break
        current = snapshot(root)
        if not hotfix(current['branch']) and not current_receipt(root, current):
            raise RuntimeError('no current feature review receipt; merge is blocked')
        subprocess.run(['wt', 'push', '--', 'origin', current['branch']], cwd=root, check=True)
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
        validate_mr(mr, current['branch'], current['head'])
        ci = wait_for_ci(root, mr['iid'], current['branch'], current['head'], ci_requirements(root, current))
        save(path / 'ci.json', ci)
        if snapshot(root) != current:
            raise RuntimeError('source/target changed before merge; review again')
        subprocess.run(['wt', 'mr', '--', 'merge', str(mr['iid']), '--sha=' + current['head'], '--yes'], cwd=root, check=True)
        merged = Forge(root).mr(mr['iid'])
        if merged.get('state') != 'merged' or merged.get('sha') != current['head']:
            raise RuntimeError('merge not confirmed for the reviewed MR SHA; source preserved')
        refresh(root)
        result_sha = merged.get('squash_commit_sha') or merged.get('merge_commit_sha') or current['head']
        subprocess.run(['git', 'merge-base', '--is-ancestor', result_sha, 'refs/remotes/origin/dev'], cwd=root, check=True)
        save(path / 'delivery.json', {'state': 'merged', 'mr': merged['iid'], 'sha': current['head'],
                                     'target': 'dev', 'result_sha': result_sha, 'source_preserved': True,
                                     'ci': ci, 'review_receipt': str(path / 'receipt.json') if not hotfix(current['branch']) else None})
        if not hotfix(current['branch']):
            receipt = json.loads((path / 'receipt.json').read_text())
            report = Path(receipt['verification']).parent / 'report.md'
            text = report.read_text().rsplit('## Доставка', 1)[0]
            report.write_text(text + '## Доставка\n\nMerged в `dev`: MR !' + str(merged['iid'])
                              + ', source SHA `' + current['head'] + '`, result `' + result_sha
                              + '`. Exact-SHA CI подтверждён; source branch/worktree сохранены.\n')
        print(json.dumps({'state': 'merged', 'target': 'dev', 'mr': merged['iid'], 'sha': current['head'],
                          'report': str(path / 'delivery.json'), 'source_preserved': True}, ensure_ascii=False))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mr', type=int)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--source-key', action='store_true', help='read-only runtime source content fingerprint')
    args = parser.parse_args()
    root = Path(git(Path.cwd(), 'rev-parse', '--show-toplevel'))
    if args.source_key:
        print(source_key(owned_root(root)))
        return 0
    return finish(root, args.mr, args.dry_run)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        print('feature-finalize: blocked: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
