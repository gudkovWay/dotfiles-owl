"""Shared review context and evidence validation; never grants delivery authority."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

MAX_CONTEXT = 120_000
SECRET = re.compile(r'(?i)(?:password|пароль|access[_-]?token|api[_-]?key)\s*[:=]\s*\S+|-----BEGIN .*PRIVATE KEY-----|\bBearer\s+\S+')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def text_content(content):
    if isinstance(content, str):
        return content
    return '\n'.join(part.get('text', '') for part in content if isinstance(part, dict) and part.get('type') == 'text')


def capture_context(sessions):
    requirements, sources = [], []
    for filename in sessions:
        path = Path(filename).resolve(strict=True)
        users, cards, header = [], [], {}
        for line_number, raw in enumerate(path.read_text().splitlines(), 1):
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if entry.get('type') == 'session':
                header = entry
            message = entry.get('message', {})
            if entry.get('type') == 'message' and message.get('role') == 'user' and message.get('attribution', 'user') == 'user':
                users.append((line_number, raw, text_content(message.get('content', []))))
            if entry.get('type') == 'custom' and entry.get('customType') == 'q.prompt-card.submitted':
                cards.append((line_number, raw, entry.get('data', {}).get('text', '')))
        if not header.get('id'):
            raise RuntimeError('review context needs a header-valid originating session')
        sources.append({'path': str(path), 'session': header['id'], 'parentSession': header.get('parentSession'), 'cwd': header.get('cwd')})
        existing = {text for _line, _raw, text in users}
        rows = sorted(users + [row for row in cards if row[2] not in existing])
        for number, raw, text in rows:
            text = re.sub(r'<system-reminder>.*?</system-reminder>', '', text, flags=re.S).strip()
            if not text:
                continue
            if SECRET.search(text):
                raise RuntimeError('likely secret in owner request; create a bounded redacted context explicitly before model review')
            requirements.append({'id': 'r' + str(len(requirements) + 1), 'text': text,
                                 'source': {'path': str(path), 'line': number,
                                            'line_sha256': hashlib.sha256(raw.encode()).hexdigest()}})
    if not requirements:
        raise RuntimeError('original owner requests are missing from review context')
    body = {'schema': 1, 'authority': False, 'sources': sources, 'requirements': requirements}
    if len(json.dumps(body, ensure_ascii=False).encode()) > MAX_CONTEXT:
        raise RuntimeError('owner review context exceeds bounded input; do not silently truncate')
    return {**body, 'context_key': digest(body)}


def validate_context(context):
    if not isinstance(context, dict) or context.get('authority') is not False or context.get('schema') != 1:
        raise RuntimeError('invalid owner review context')
    current = capture_context([source['path'] for source in context['sources']])
    if current != context:
        raise RuntimeError('originating owner context changed; recapture and review the new requirements')
    return context


def validate_reference(root, reference):
    name = reference.get('path', '')
    path = Path(name)
    if not name or path.is_absolute() or '..' in path.parts or any(part == '.secrets' or part.startswith('.env') for part in path.parts):
        raise RuntimeError('review reference is outside source scope or names a secret file')
    root = Path(root).resolve()
    revision = reference.get('revision', 'worktree')
    if revision == 'worktree':
        target = root / path
        if not target.resolve().is_relative_to(root):
            raise RuntimeError('review reference escapes repository')
        data = target.read_bytes()
    else:
        if not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}', revision):
            raise RuntimeError('historical reference needs an exact commit')
        data = subprocess.check_output(['git', '-C', str(root), 'show', revision + ':' + name])
    if hashlib.sha256(data).hexdigest() != reference.get('sha256'):
        raise RuntimeError('review reference bytes changed: ' + name)


def validate_review(root, report, paths, context):
    validate_context(context)
    if not isinstance(report, dict) or report.get('context_key') != context['context_key']:
        raise RuntimeError('review does not match the originating owner context')
    coverage = report.get('coverage')
    if not isinstance(coverage, list) or not coverage:
        raise RuntimeError('review scope coverage is missing')
    covered = []
    identifiers = {item['id'] for item in context['requirements']}
    for scope in coverage:
        if not scope.get('scenario') or not scope.get('verification') or not isinstance(scope.get('findings'), list):
            raise RuntimeError('review scope needs scenario, findings and actual verification status')
        if not scope.get('paths') or not scope.get('inspected'):
            raise RuntimeError('review scope coverage needs paths and inspected source evidence')
        covered.extend(scope['paths'])
        for reference in scope['inspected']:
            validate_reference(root, reference)
        comparisons = scope.get('comparisons')
        if not isinstance(comparisons, list) or (not comparisons and not scope.get('no_analog')):
            raise RuntimeError('review analog comparison or concrete no_analog search result is required')
        for comparison in comparisons:
            validate_reference(root, comparison['candidate'])
            validate_reference(root, comparison['reference'])
            direction = comparison.get('direction')
            if direction not in {'preserve-reference', 'adopt-new-flow', 'keep-local'} or not comparison.get('decision'):
                raise RuntimeError('review needs an explicit old/new comparison direction and reason')
            basis = comparison.get('basis', [])
            if not isinstance(basis, list) or not set(basis).issubset(identifiers):
                raise RuntimeError('comparison cites an unknown owner requirement')
            if direction == 'adopt-new-flow' and not basis:
                raise RuntimeError('new flow needs an originating owner requirement, not chronology alone')
            rollout = comparison.get('rollout', [])
            if not isinstance(rollout, list):
                raise RuntimeError('invalid rollout path list')
            if set(rollout) - set(paths) and not basis:
                raise RuntimeError('rollout outside the MR needs exact owner requirement evidence')
    if len(covered) != len(set(covered)) or set(covered) != set(paths):
        raise RuntimeError('review coverage must account for each cumulative MR path exactly once')
    return report


def context_path(root):
    return Path(root) / '.superpowers/review/context.json'


def load_context(root):
    path = context_path(root)
    if not path.is_file() or path.is_symlink():
        raise RuntimeError('capture originating owner session first with review_contract.py capture --session PATH --root WORKTREE')
    return validate_context(json.loads(path.read_text()))


def store_context(root, sessions):
    context = capture_context(sessions)
    path = context_path(root)
    for directory in (Path(root) / '.superpowers', path.parent):
        if directory.is_symlink():
            raise RuntimeError('review artifact directory must not be a symlink')
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise RuntimeError('review context artifact must not be a symlink')
    path.write_text(json.dumps(context, ensure_ascii=False, indent=2) + '\n')
    path.chmod(0o600)
    return context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['capture', 'validate'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--session', type=Path, action='append')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--paths', type=Path, help='JSON array of cumulative changed paths')
    args = parser.parse_args()
    if args.operation == 'capture':
        if not args.session:
            parser.error('capture requires --session for the originating owner transcript')
        context = store_context(args.root, args.session)
        print(json.dumps({'context': str(context_path(args.root)), 'context_key': context['context_key'], 'authority': False}))
    else:
        if not args.report or not args.paths:
            parser.error('validate requires --report and --paths')
        validate_review(args.root, json.loads(args.report.read_text()), json.loads(args.paths.read_text()), load_context(args.root))
        print('review provenance and scope coverage verified; semantic/runtime quality is separate')


if __name__ == '__main__':
    main()
