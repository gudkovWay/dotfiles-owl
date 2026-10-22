"""Owner-policy capabilities. No command execution or credential handling."""
import copy
import hashlib
import hmac
import json
import posixpath
import re
import secrets
import time
import unicodedata


class ApprovalError(ValueError):
    pass


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ApprovalError('Duplicate request field')
        result[key] = value
    return result


def _text(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ApprovalError('Missing or oversized scope text')
    if value != value.strip() or any(
        unicodedata.category(c).startswith('C') or (c.isspace() and c != ' ') for c in value
    ):
        raise ApprovalError('Control characters and ambiguous whitespace are forbidden')
    return value


def validate_request(raw):
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > 12000:
        raise ApprovalError('Request exceeds the size limit')
    try:
        request = json.loads(raw, object_pairs_hook=_object)
    except (TypeError, json.JSONDecodeError) as error:
        raise ApprovalError('Invalid JSON request') from error
    if not isinstance(request, dict) or set(request) != {'session', 'cwd', 'action', 'exceptions'}:
        raise ApprovalError('Only session, cwd, action and exceptions are accepted')
    session = _text(request['session'], 128)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', session):
        raise ApprovalError('Invalid session identifier')
    cwd = _text(request['cwd'], 1024)
    if not cwd.startswith('/') or posixpath.normpath(cwd) != cwd:
        raise ApprovalError('Project path must be absolute and normalized')
    _text(request['action'], 500)
    exceptions = request['exceptions']
    if not isinstance(exceptions, list) or not 1 <= len(exceptions) <= 8:
        raise ApprovalError('Specify between one and eight exact owner-policy exceptions')
    for exception in exceptions:
        _text(exception, 800)
    if len(set(exceptions)) != len(exceptions) or sum(map(len, exceptions)) > 1600:
        raise ApprovalError('Duplicate or oversized exceptions')
    return request


def canonical(request):
    return json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def format_prompt(request):
    exceptions = '\n'.join(f'{i + 1}. {text}' for i, text in enumerate(request['exceptions']))
    return (
        'Разовое исключение из ВАШИХ правил OMP\n\n'
        f"Сессия: {request['session']}\nПроект: {request['cwd']}\n"
        f"Действие: {request['action']}\n\nИсключения:\n{exceptions}\n\n"
        'Только для одного запуска агента, максимум 1 час. Не изменяет постоянные правила. '
        'Не выдаёт root и не отменяет системные ограничения провайдера. '
        'Введите пароль только если подтверждаете ВСЁ показанное выше.'
    )


class GrantStore:
    def __init__(self, owner_uid, clock=time.monotonic):
        self.owner_uid = owner_uid
        self.clock = clock
        self.grants = {}

    def _owner(self, uid):
        if uid != self.owner_uid:
            raise ApprovalError('Only the configured owner may use this service')

    def _prune(self):
        now = self.clock()
        for key in list(self.grants):
            if self.grants[key]['expires'] <= now:
                del self.grants[key]

    def count(self):
        self._prune()
        return len(self.grants)

    def issue(self, uid, actor, request, *, authenticated):
        self._owner(uid)
        if authenticated is not True:
            raise ApprovalError('Fresh owner authentication is required')
        request = validate_request(canonical(request))
        self._prune()
        if len(self.grants) >= 32:
            raise ApprovalError('Approval capacity reached')
        if any(g['actor'] == actor and g['request']['session'] == request['session'] for g in self.grants.values()):
            raise ApprovalError('An approval for this run is already open; revoke it first')
        grant_id, secret = secrets.token_hex(16), secrets.token_hex(32)
        self.grants[grant_id] = {
            'actor': actor,
            'request': copy.deepcopy(request),
            'secret': secret,
            'status': 'pending',
            'expires': self.clock() + 60,
        }
        return {'id': grant_id, 'secret': secret}

    def _get(self, uid, actor, grant_id, secret):
        self._owner(uid)
        self._prune()
        grant = self.grants.get(grant_id)
        if not grant or grant['actor'] != actor or not isinstance(secret, str) or not hmac.compare_digest(grant['secret'], secret):
            raise ApprovalError('Unknown, expired or wrong-process approval')
        return grant

    def _bound(self, uid, actor, grant_id, secret, session, cwd):
        grant = self._get(uid, actor, grant_id, secret)
        if grant['request']['session'] != session or grant['request']['cwd'] != cwd:
            raise ApprovalError('Approval belongs to another session or project')
        return grant

    def _public(self, grant_id, grant):
        return {
            'id': grant_id,
            'request': copy.deepcopy(grant['request']),
            'request_hash': hashlib.sha256(canonical(grant['request']).encode()).hexdigest(),
            'remaining_seconds': max(0, int(grant['expires'] - self.clock())),
        }

    def activate(self, uid, actor, grant_id, secret, session, cwd):
        grant = self._bound(uid, actor, grant_id, secret, session, cwd)
        if grant['status'] != 'pending':
            raise ApprovalError('Approval has already been claimed')
        grant['status'] = 'active'
        grant['expires'] = self.clock() + 3600
        return self._public(grant_id, grant)

    def check(self, uid, actor, grant_id, secret, session, cwd):
        grant = self._bound(uid, actor, grant_id, secret, session, cwd)
        if grant['status'] != 'active':
            raise ApprovalError('Approval is not active')
        return self._public(grant_id, grant)

    def revoke(self, uid, actor, grant_id, secret):
        self._get(uid, actor, grant_id, secret)
        del self.grants[grant_id]
        return {'revoked': True}
