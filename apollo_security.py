"""Single-owner step-up authentication for Apollo's private Tailscale origin.

The Tailscale proxy remains the account boundary. This module adds a separate,
short-lived proof of possession for protected resources; a browser session or
model assertion never creates that proof.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import time
import urllib.parse
import urllib.request
import urllib.error
from http.cookies import SimpleCookie
from pathlib import Path


TABS = frozenset({'chat', 'music', 'calendar', 'tasks', 'routines', 'debrief', 'studio', 'settings'})
PRIVATE_SCOPES = frozenset({'private', 'history'})
POLICIES = frozenset({'leave', '5m', '15m'})
LEVELS = frozenset({'standard', 'enhanced', 'maximum'})
LEAVE_LEASE_SECONDS = 3600  # Crash/network fallback; active pages renew, navigation revokes.
SETTINGS_MUTATION_FRESH_SECONDS = 90
LOGGER = logging.getLogger(__name__)
ORIGIN = os.environ.get('APOLLO_SECURITY_ORIGIN', 'https://ubuntu-2gb-hel1-1.tailc5eaaa.ts.net').rstrip('/')
RP_ID = urllib.parse.urlparse(ORIGIN).hostname
COOKIE = '__Host-apollo-stepup'
TAB_HEADER = 'X-Apollo-Security-Tab'


def init_schema(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS apollo_security_policy (
            id INTEGER PRIMARY KEY CHECK(id=1), policy_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS apollo_security_password (
            id INTEGER PRIMARY KEY CHECK(id=1), salt BLOB NOT NULL, digest BLOB NOT NULL
        );
        CREATE TABLE IF NOT EXISTS apollo_security_recovery (
            digest BLOB PRIMARY KEY, used_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS apollo_security_webauthn (
            credential_id BLOB PRIMARY KEY, public_key BLOB NOT NULL,
            sign_count INTEGER NOT NULL, created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS apollo_security_challenges (
            id TEXT PRIMARY KEY, challenge BLOB NOT NULL, purpose TEXT NOT NULL,
            resource TEXT NOT NULL, expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS apollo_security_grants (
            token_digest BLOB NOT NULL, resource TEXT NOT NULL,
            verified_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
            PRIMARY KEY(token_digest, resource)
        );
        CREATE TABLE IF NOT EXISTS apollo_security_attempts (
            id INTEGER PRIMARY KEY CHECK(id=1), failures INTEGER NOT NULL,
            window_started INTEGER NOT NULL, blocked_until INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS apollo_public_messages (
            message_id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_apollo_public_messages_chat
            ON apollo_public_messages(chat_id, message_id);
    ''')
    conn.execute('INSERT OR IGNORE INTO apollo_security_policy(id,policy_json) VALUES(1,?)',
                 (json.dumps({'tabs': {}, 'privacy': 'standard', 'protect_spotify': False,
                              'protect_sensitive_chat': False, 'protect_history': False,
                              'private_relock': '5m', 'history_relock': '5m'}),))


def policy(conn):
    row = conn.execute('SELECT policy_json FROM apollo_security_policy WHERE id=1').fetchone()
    defaults = {'tabs': {}, 'privacy': 'standard', 'protect_spotify': False,
                'protect_sensitive_chat': False, 'protect_history': False,
                'private_relock': '5m', 'history_relock': '5m'}
    return {**defaults, **json.loads(row[0])} if row else defaults


def _digest(token):
    return hashlib.sha256(token.encode('utf-8')).digest()


def _grant_resource(handler, resource):
    if resource != 'settings':
        return resource
    tab = handler.headers.get(TAB_HEADER, '')
    if not re.fullmatch(r'[0-9a-f]{32}', tab):
        return None
    return 'settings:' + tab


def _cookie(handler):
    try:
        cookies = SimpleCookie(handler.headers.get('Cookie', ''))
        return cookies[COOKIE].value if COOKIE in cookies else ''
    except Exception:
        return ''


def _grant(conn, handler, resource):
    return bool(_grant_details(conn, handler, resource))


def _grant_details(conn, handler, resource):
    token = _cookie(handler)
    grant_resource = _grant_resource(handler, resource)
    if not token or not grant_resource:
        return None
    row = conn.execute('SELECT expires_at FROM apollo_security_grants WHERE token_digest=? AND resource=?',
                       (_digest(token), grant_resource)).fetchone()
    return (_digest(token), row[0], grant_resource) if row and row[0] > int(time.time()) else None


def generation_grant_active(job):
    details = job.get('_security_grant')
    import server
    conn = server.db()
    try:
        config = policy(conn)
        if not details and _requires(config, 'chat'):
            return False
        for grant in (details, job.get('_private_grant')):
            if not grant:
                continue
            if grant[1] <= int(time.time()):
                return False
            row = conn.execute('SELECT 1 FROM apollo_security_grants WHERE token_digest=? AND resource=? AND expires_at>?',
                               (grant[0], grant[2], int(time.time()))).fetchone()
            if not row:
                return False
        if job.get('_private_required') and _requires(config, 'private') and not job.get('_private_grant'):
            return False
        return True
    finally:
        conn.close()


def _resource(path, method='GET'):
    if re.fullmatch(r'/api/chats(?:/search|/\d+)?', path) and method != 'POST':
        return 'history'
    for prefix, resource in (
        ('/api/chat', 'chat'), ('/api/chats', 'chat'), ('/api/memory', 'chat'),
        ('/api/interactive', 'chat'),
        ('/api/music', 'music'), ('/api/spotify', 'music'), ('/api/now-playing', 'music'),
        ('/api/calendar', 'calendar'), ('/api/google', 'calendar'),
        ('/api/gmail', 'connections'),
        ('/api/tasks', 'tasks'), ('/api/routines', 'routines'),
        ('/api/debrief', 'debrief'), ('/api/studio', 'studio'), ('/api/wip', 'studio'),
        ('/api/whoop', 'whoop'), ('/api/notifications', 'notifications'),
        ('/api/connections', 'connections'), ('/api/client-context', 'chat'),
        ('/api/developer/diagnostics', 'settings'),
        ('/api/automations', 'tasks'),
        ('/api/agent/traces', 'chat'),
    ):
        if path == prefix or path.startswith(prefix + '/') or (prefix == '/api/chat' and path.startswith('/api/chat-')):
            return resource
    return None


def _requires(config, resource):
    if resource == 'history':
        return bool(config.get('protect_history'))
    if resource == 'private':
        return bool(config.get('protect_sensitive_chat'))
    if resource in config.get('tabs', {}):
        return True
    level = config.get('privacy', 'standard')
    if level == 'maximum':
        return resource is not None
    if level == 'enhanced':
        if resource == 'music':
            return bool(config.get('protect_spotify'))
        return resource in {'chat', 'calendar', 'tasks', 'routines', 'debrief',
                            'studio', 'whoop', 'notifications', 'connections'}
    return False


_PERSONAL_REQUEST = re.compile(
    r'\b(?:my|mine|our|ours|myself|mi|mis|mío|mía|mios|mias|nuestro|nuestra|'
    r'me\s+(?:about|what\s+i|who\s+i)|remember|recuerdas?|recuérdame|'
    r'personal\s+(?:history|memory|data)|private|privado|privada|'
    r'family|familia|relationship|relación|relaciones|'
    r'admission|admisión|university\s+application|solicitud\s+universitaria|'
    r'inbox|bandeja\s+de\s+entrada|gmail|whoop|canvas\s+assignment|'
    r'calendar\s+event|my\s+spotify|listening\s+history|'
    r'where\s+(?:do|did)\s+i\s+live|where\s+am\s+i\s+from|'
    r'what\s+do\s+you\s+know\s+about\s+me|'
    r'(?:d[oó]nde\s+vivo|qui[eé]n\s+soy|qu[eé]\s+sabes\s+de\s+m[ií]))\b', re.I
)


def private_access_mode(conn, handler, content, allow_public=False):
    """Return allow, public, or locked before private retrieval or model execution."""
    config = policy(conn)
    if not _requires(config, 'private'):
        return 'allow', None
    grant = _grant_details(conn, handler, 'private')
    if grant:
        return 'allow', grant
    if allow_public and isinstance(content, str) and content.strip() and not _PERSONAL_REQUEST.search(content):
        return 'public', None
    return 'locked', None


def public_conversation(conn, chat_id, before_id, limit=8):
    """Only prior turns explicitly completed in public mode may be read here."""
    rows = conn.execute('''
        SELECT m.role, m.content FROM apollo_public_messages p
        JOIN messages m ON m.id=p.message_id AND m.chat_id=p.chat_id
        WHERE p.chat_id=? AND m.id<? AND m.role IN ('user','assistant')
        ORDER BY m.id DESC LIMIT ?
    ''', (chat_id, before_id, limit)).fetchall()
    return [{'role': row['role'], 'content': str(row['content'] or '')[:1200]}
            for row in reversed(rows)]


def mark_public_pair(conn, chat_id, user_id, assistant_id):
    """Tag both sides atomically after a successful public answer."""
    for message_id, role in ((user_id, 'user'), (assistant_id, 'assistant')):
        if not conn.execute('SELECT 1 FROM messages WHERE id=? AND chat_id=? AND role=?',
                            (message_id, chat_id, role)).fetchone():
            raise ValueError('Public response provenance is invalid')
        conn.execute('INSERT OR IGNORE INTO apollo_public_messages(message_id,chat_id) VALUES(?,?)',
                     (message_id, chat_id))


def backfill_public_pairs(conn):
    """Recover old public-only turns only when saved job provenance is exact."""
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('messages','chat_generation_jobs')")}
    if tables != {'messages', 'chat_generation_jobs'}:
        return 0
    if 'public_only' not in {row[1] for row in conn.execute('PRAGMA table_info(chat_generation_jobs)')}:
        return 0
    recovered = 0
    for job in conn.execute('''
        SELECT chat_id, message_json FROM chat_generation_jobs
        WHERE public_only=1 AND state='complete' AND message_json IS NOT NULL
    ''').fetchall():
        try:
            saved = json.loads(job['message_json'])
            answer = saved['content'] if saved['role'] == 'assistant' else None
        except (TypeError, ValueError, KeyError):
            continue
        if not isinstance(answer, str) or not answer:
            continue
        # An answer can occur in several chats or be repeated in one chat.
        # Only a unique exact match with an adjacent user turn is safe to tag.
        matches = conn.execute('''
            SELECT id FROM messages WHERE chat_id=? AND role='assistant' AND content=? LIMIT 2
        ''', (job['chat_id'], answer)).fetchall()
        if len(matches) != 1:
            continue
        assistant_id = matches[0][0]
        prior = conn.execute('''
            SELECT id,role FROM messages WHERE chat_id=? AND id<? ORDER BY id DESC LIMIT 1
        ''', (job['chat_id'], assistant_id)).fetchone()
        if not prior or prior['role'] != 'user':
            continue
        mark_public_pair(conn, job['chat_id'], prior['id'], assistant_id)
        recovered += 1
    return recovered


def public_answer_text(server, question, conversation=()):
    """Public answer with only explicitly tagged public turns and no private data."""
    if not isinstance(question, str) or not question.strip() or len(question) > 1200:
        raise ValueError('Enter a short public question')
    model = 'gpt-5.6-terra' if conversation and 2 <= len(question.split()) <= 18 else 'gpt-5.6-luna'
    request = urllib.request.Request(server.HERMES_URL,
        data=json.dumps({'provider': 'openai-codex', 'model': model,
            'model_options': {'reasoning_effort': 'low', 'disable_tools': True},
            'messages': [
                {'role': 'system', 'content': 'Answer public, general questions only. You have no access to Apollo personal data, private conversations, accounts or connected services. The supplied prior turns were also answered in public mode. Resolve short reactions, jokes, corrections and pronouns from those turns before treating them as a new request. If asked for personal details, say verification is required. Do not imply you checked sources.'},
                *[{'role': item['role'], 'content': item['content']} for item in conversation[-8:]
                  if isinstance(item, dict) and item.get('role') in ('user', 'assistant')],
                {'role': 'user', 'content': question}]}).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + server.get_api_key()},
        method='POST')
    with urllib.request.urlopen(request, timeout=18) as response:
        result = json.loads(response.read(262144))
    answer = str(result.get('choices', [{}])[0].get('message', {}).get('content') or '').strip()
    return answer[:8000] or 'I could not answer that public question.'


def _reply(handler, data, status=200, token=None, clear=False):
    body = json.dumps(data, ensure_ascii=False).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(body)))
    handler.send_header('Cache-Control', 'no-store')
    if token:
        handler.send_header('Set-Cookie', f'{COOKIE}={token}; Path=/; Secure; HttpOnly; SameSite=Strict')
    if clear:
        handler.send_header('Set-Cookie', f'{COOKIE}=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0')
    handler.end_headers()
    handler.wfile.write(body)


def _read(handler):
    size = int(handler.headers.get('Content-Length', '0'))
    if size < 0 or size > 16384:
        raise ValueError('Security request is too large')
    value = json.loads(handler.rfile.read(size) or b'{}')
    if not isinstance(value, dict):
        raise ValueError('Invalid security request')
    return value


def _same_origin(handler):
    return (handler.headers.get('Origin', '').rstrip('/') == ORIGIN
            and handler.headers.get('X-Apollo-Request') == 'security')


def _password_hash(secret, salt):
    return hashlib.scrypt(secret.encode('utf-8'), salt=salt, n=2**14, r=8, p=1, dklen=32)


def _check_password(conn, secret):
    row = conn.execute('SELECT salt,digest FROM apollo_security_password WHERE id=1').fetchone()
    if not row or not isinstance(secret, str):
        return False
    return hmac.compare_digest(_password_hash(secret, row[0]), row[1])


def _check_rate(conn):
    now = int(time.time())
    row = conn.execute('SELECT failures,window_started,blocked_until FROM apollo_security_attempts WHERE id=1').fetchone()
    if row and row[2] > now:
        raise PermissionError('Too many attempts. Try again later.')
    if not row or now - row[1] > 900:
        conn.execute('INSERT INTO apollo_security_attempts(id,failures,window_started,blocked_until) VALUES(1,0,?,0) '
                     'ON CONFLICT(id) DO UPDATE SET failures=0,window_started=excluded.window_started,blocked_until=0', (now,))


def _failed(conn):
    now = int(time.time())
    conn.execute('UPDATE apollo_security_attempts SET failures=failures+1, '
                 'blocked_until=CASE WHEN failures+1>=5 THEN ? ELSE blocked_until END WHERE id=1', (now + 900,))


def _verified(conn):
    conn.execute('UPDATE apollo_security_attempts SET failures=0,blocked_until=0 WHERE id=1')


def _issue(conn, handler, resource, config):
    now = int(time.time())
    grant_resource = _grant_resource(handler, resource)
    if not grant_resource:
        raise ValueError('A secure browser tab identifier is required')
    duration = (config.get(resource + '_relock', '5m') if resource in PRIVATE_SCOPES
                else config.get('tabs', {}).get(resource, '5m'))
    ttl = LEAVE_LEASE_SECONDS if duration == 'leave' else 900 if duration == '15m' else 300
    existing = _cookie(handler)
    known = bool(existing and conn.execute(
        'SELECT 1 FROM apollo_security_grants WHERE token_digest=? AND expires_at>? LIMIT 1',
        (_digest(existing), now)).fetchone())
    token = existing if known else secrets.token_urlsafe(48)
    conn.execute('DELETE FROM apollo_security_grants WHERE expires_at<?', (now,))
    conn.execute('INSERT INTO apollo_security_grants(token_digest,resource,verified_at,expires_at) VALUES(?,?,?,?) '
                 'ON CONFLICT(token_digest,resource) DO UPDATE SET verified_at=excluded.verified_at,expires_at=excluded.expires_at',
                 (_digest(token), grant_resource, now, now + ttl))
    return token, now + ttl


def _recent_settings_grant(conn, handler):
    token = _cookie(handler)
    grant_resource = _grant_resource(handler, 'settings')
    if not token or not grant_resource:
        return False
    now = int(time.time())
    return bool(conn.execute(
        'SELECT 1 FROM apollo_security_grants WHERE token_digest=? AND resource=? '
        'AND expires_at>? AND verified_at>=?',
        (_digest(token), grant_resource, now, now - SETTINGS_MUTATION_FRESH_SECONDS)).fetchone())


def _valid_resource(resource):
    return resource in TABS | PRIVATE_SCOPES or resource in {'whoop', 'notifications', 'connections'}


def _challenge(conn, purpose, resource):
    ident = secrets.token_urlsafe(24)
    challenge = secrets.token_bytes(32)
    conn.execute('DELETE FROM apollo_security_challenges WHERE expires_at<?', (int(time.time()),))
    conn.execute('INSERT INTO apollo_security_challenges(id,challenge,purpose,resource,expires_at) VALUES(?,?,?,?,?)',
                 (ident, challenge, purpose, resource, int(time.time()) + 120))
    return ident, challenge


def _consume(conn, ident, purpose):
    row = conn.execute('SELECT challenge,resource,expires_at FROM apollo_security_challenges WHERE id=? AND purpose=?',
                       (ident, purpose)).fetchone()
    conn.execute('DELETE FROM apollo_security_challenges WHERE id=?', (ident,))
    if not row or row[2] <= int(time.time()):
        raise ValueError('Verification expired; try again')
    return row[0], row[1]


def _recovery_codes(conn):
    codes = [secrets.token_urlsafe(18) for _ in range(8)]
    conn.execute('DELETE FROM apollo_security_recovery')
    conn.executemany('INSERT INTO apollo_security_recovery(digest) VALUES(?)', [(_digest(code),) for code in codes])
    return codes


def _setup_token():
    value = os.environ.get('APOLLO_SECURITY_SETUP_TOKEN', '')
    if value:
        return value
    try:
        return Path('/root/apollo-security-setup-token').read_text().strip()
    except OSError:
        return ''


def _authenticate(conn, method, payload):
    _check_rate(conn)
    if method == 'passphrase':
        valid = _check_password(conn, payload.get('passphrase'))
    elif method == 'recovery':
        code = str(payload.get('code') or '')
        row = conn.execute('SELECT used_at FROM apollo_security_recovery WHERE digest=?', (_digest(code),)).fetchone()
        valid = bool(row and row[0] is None)
        if valid:
            conn.execute('UPDATE apollo_security_recovery SET used_at=? WHERE digest=?', (int(time.time()), _digest(code)))
    else:
        raise ValueError('Unsupported authentication method')
    if not valid:
        _failed(conn)
        raise PermissionError('Verification failed')
    _verified(conn)


def handle(server, handler, method):
    """Handle security API and deny protected resource APIs before any adapter runs."""
    path = urllib.parse.urlparse(server.canonical_api_request_path(handler.path)).path
    if not path.startswith('/api/'):
        return False
    if path.startswith('/api/security/'):
        return _security_api(server, handler, method, path)
    if method == 'GET' and path in {'/api/google/callback', '/api/whoop/callback'}:
        # OAuth callbacks validate their own one-time state and disclose no data.
        return False
    if getattr(handler, '_apollo_security_internal', False):
        return False
    resource = _resource(path, method)
    if not resource:
        return False
    conn = server.db()
    try:
        config = policy(conn)
        if resource == 'history' and not config.get('protect_history'):
            resource = 'chat'
        if config.get('protect_history') and path.startswith('/api/memory'):
            resource = 'history'
        if config.get('protect_sensitive_chat') and path.startswith((
                '/api/memory', '/api/interactive', '/api/chat-attachments',
                '/api/chat-media', '/api/client-context', '/api/agent/traces')):
            resource = 'private'
        if _requires(config, resource):
            grant = _grant_details(conn, handler, resource)
            if not grant:
                _reply(handler, {'error': 'verification_required', 'resource': resource}, 423)
                return True
            handler._apollo_security_grant = grant
    finally:
        conn.close()
    return False


def _security_api(server, handler, method, path):
    conn = server.db()
    try:
        config = policy(conn)
        enrolled = bool(conn.execute('SELECT 1 FROM apollo_security_password WHERE id=1').fetchone())
        if method == 'GET' and path == '/api/security/state':
            unlocked = {resource: _grant(conn, handler, resource)
                        for resource in TABS | PRIVATE_SCOPES | {'whoop', 'notifications', 'connections', 'settings'}}
            scope_expires = {}
            for scope in PRIVATE_SCOPES:
                details = _grant_details(conn, handler, scope)
                scope_expires[scope] = details[1] if details else None
            _reply(handler, {'tabs': config.get('tabs', {}), 'privacy': config.get('privacy', 'standard'),
                             'protect_spotify': bool(config.get('protect_spotify')),
                             'protect_sensitive_chat': bool(config.get('protect_sensitive_chat')),
                             'protect_history': bool(config.get('protect_history')),
                             'private_relock': config.get('private_relock', '5m'),
                             'history_relock': config.get('history_relock', '5m'),
                             'scope_expires': scope_expires,
                             'enrolled': enrolled,
                             'passkeys': conn.execute('SELECT COUNT(*) FROM apollo_security_webauthn').fetchone()[0],
                             'recovery_available': conn.execute('SELECT COUNT(*) FROM apollo_security_recovery WHERE used_at IS NULL').fetchone()[0]
                                 if _grant(conn, handler, 'settings') else None,
                             'unlocked': unlocked})
            return True
        if method == 'GET' and path == '/api/security/passkeys':
            if not _grant(conn, handler, 'settings'):
                _reply(handler, {'error': 'verification_required', 'resource': 'settings'}, 423)
                return True
            _reply(handler, {'passkeys': [
                {'id': base64.urlsafe_b64encode(row[0]).decode().rstrip('='), 'created_at': row[1]}
                for row in conn.execute('SELECT credential_id,created_at FROM apollo_security_webauthn ORDER BY created_at')]})
            return True
        if method != 'POST' or not _same_origin(handler):
            _reply(handler, {'error': 'Request origin could not be verified'}, 403)
            return True
        payload = _read(handler)
        if path == '/api/security/public-answer':
            question = str(payload.get('question') or '').strip()
            try:
                answer = public_answer_text(server, question)
            except (TimeoutError, OSError, urllib.error.URLError, json.JSONDecodeError):
                _reply(handler, {'error': 'Public answer temporarily unavailable'}, 503)
                return True
            _reply(handler, {'answer': answer})
            return True
        if path == '/api/security/setup':
            setup = _setup_token()
            if enrolled or not setup or not hmac.compare_digest(str(payload.get('setup_token') or ''), setup):
                _reply(handler, {'error': 'Setup requires the operator token'}, 403)
                return True
            passphrase = payload.get('passphrase')
            if not isinstance(passphrase, str) or len(passphrase) < 16 or len(passphrase) > 256:
                raise ValueError('Use a passphrase of at least 16 characters')
            salt = secrets.token_bytes(24)
            conn.execute('INSERT INTO apollo_security_password(id,salt,digest) VALUES(1,?,?)',
                         (salt, _password_hash(passphrase, salt)))
            codes = _recovery_codes(conn)
            token, expiry = _issue(conn, handler, 'settings', config)
            conn.commit()
            _reply(handler, {'recovery_codes': codes, 'expires_at': expiry}, token=token)
            return True
        if not enrolled:
            _reply(handler, {'error': 'Security enrollment is required'}, 409)
            return True
        if path == '/api/security/authenticate':
            resource = str(payload.get('resource') or '')
            if not _valid_resource(resource):
                raise ValueError('Unknown protected resource')
            try:
                _authenticate(conn, str(payload.get('method') or 'passphrase'), payload)
            except PermissionError as error:
                conn.commit()
                _reply(handler, {'error': str(error)}, 429 if 'Too many' in str(error) else 403)
                return True
            token, expiry = _issue(conn, handler, resource, config)
            conn.commit()
            _reply(handler, {'resource': resource, 'expires_at': expiry}, token=token)
            return True
        if path == '/api/security/revoke':
            resource = str(payload.get('resource') or '')
            if resource and not _valid_resource(resource):
                raise ValueError('Unknown protected resource')
            if resource:
                grant_resource = _grant_resource(handler, resource)
                if not grant_resource:
                    raise ValueError('A secure browser tab identifier is required')
                conn.execute('DELETE FROM apollo_security_grants WHERE token_digest=? AND resource=?',
                             (_digest(_cookie(handler)), grant_resource))
            else:
                conn.execute('DELETE FROM apollo_security_grants WHERE token_digest=?', (_digest(_cookie(handler)),))
            conn.commit()
            LOGGER.info('Apollo security grant revoked: resource=%s', resource or 'all')
            _reply(handler, {'revoked': True}, clear=not resource)
            return True
        if path == '/api/security/heartbeat':
            resource = str(payload.get('resource') or '')
            if resource not in TABS or config.get('tabs', {}).get(resource) != 'leave':
                _reply(handler, {'error': 'No leave-policy grant to renew'}, 400)
                return True
            if not _grant(conn, handler, resource):
                LOGGER.info('Apollo security lease renewal denied: resource=%s', resource)
                _reply(handler, {'error': 'verification_required', 'resource': resource}, 423)
                return True
            expiry = int(time.time()) + LEAVE_LEASE_SECONDS
            grant_resource = _grant_resource(handler, resource)
            conn.execute('UPDATE apollo_security_grants SET expires_at=? WHERE token_digest=? AND resource=?',
                         (expiry, _digest(_cookie(handler)), grant_resource))
            conn.commit()
            _reply(handler, {'resource': resource, 'expires_at': expiry})
            return True
        if path == '/api/security/policy':
            if not _recent_settings_grant(conn, handler):
                _reply(handler, {'error': 'recent_verification_required', 'resource': 'settings'}, 423)
                return True
            tabs = payload.get('tabs')
            level = payload.get('privacy')
            if not isinstance(tabs, dict) or any(key not in TABS or value not in POLICIES for key, value in tabs.items()):
                raise ValueError('Invalid tab-lock policy')
            if level not in LEVELS or not isinstance(payload.get('protect_spotify'), bool):
                raise ValueError('Invalid privacy policy')
            protect_sensitive_chat = payload.get('protect_sensitive_chat', config.get('protect_sensitive_chat', False))
            protect_history = payload.get('protect_history', config.get('protect_history', False))
            private_relock = payload.get('private_relock', config.get('private_relock', '5m'))
            history_relock = payload.get('history_relock', config.get('history_relock', '5m'))
            if (type(protect_sensitive_chat) is not bool or type(protect_history) is not bool
                    or private_relock not in POLICIES or history_relock not in POLICIES):
                raise ValueError('Invalid private-information policy')
            next_config = {'tabs': tabs, 'privacy': level, 'protect_spotify': payload['protect_spotify'],
                           'protect_sensitive_chat': protect_sensitive_chat,
                           'protect_history': protect_history,
                           'private_relock': private_relock, 'history_relock': history_relock}
            conn.execute('UPDATE apollo_security_policy SET policy_json=? WHERE id=1', (json.dumps(next_config),))
            conn.execute("DELETE FROM apollo_security_grants WHERE resource NOT LIKE 'settings:%'")
            conn.commit()
            _reply(handler, next_config)
            return True
        if path in {'/api/security/passphrase/change', '/api/security/recovery/regenerate',
                    '/api/security/passkey/delete'}:
            if not _recent_settings_grant(conn, handler):
                _reply(handler, {'error': 'recent_verification_required', 'resource': 'settings'}, 423)
                return True
            if path == '/api/security/passkey/delete':
                from webauthn import base64url_to_bytes
                credential_id = base64url_to_bytes(str(payload.get('id') or ''))
                conn.execute('DELETE FROM apollo_security_webauthn WHERE credential_id=?', (credential_id,))
                conn.commit()
                _reply(handler, {'deleted': True})
                return True
            _check_rate(conn)
            if not _check_password(conn, payload.get('current_passphrase')):
                _failed(conn)
                conn.commit()
                raise PermissionError('Current passphrase is incorrect')
            _verified(conn)
            if path == '/api/security/passphrase/change':
                next_secret = payload.get('new_passphrase')
                if not isinstance(next_secret, str) or not 16 <= len(next_secret) <= 256:
                    raise ValueError('Use a passphrase of at least 16 characters')
                salt = secrets.token_bytes(24)
                conn.execute('UPDATE apollo_security_password SET salt=?,digest=? WHERE id=1',
                             (salt, _password_hash(next_secret, salt)))
                conn.execute("DELETE FROM apollo_security_grants WHERE resource NOT LIKE 'settings:%'")
                conn.commit()
                _reply(handler, {'changed': True})
            else:
                codes = _recovery_codes(conn)
                conn.commit()
                _reply(handler, {'recovery_codes': codes})
            return True
        if path == '/api/security/passkey/register/options':
            if not _recent_settings_grant(conn, handler):
                _reply(handler, {'error': 'recent_verification_required', 'resource': 'settings'}, 423)
                return True
            from webauthn import generate_registration_options, options_to_json
            from webauthn.helpers.structs import AuthenticatorSelectionCriteria, UserVerificationRequirement
            ident, challenge = _challenge(conn, 'register', 'settings')
            options = generate_registration_options(rp_id=RP_ID, rp_name='Apollo', user_name='Apollo owner',
                user_id=b'apollo-single-owner', challenge=challenge,
                authenticator_selection=AuthenticatorSelectionCriteria(user_verification=UserVerificationRequirement.REQUIRED))
            conn.commit()
            _reply(handler, {'challenge_id': ident, 'options': json.loads(options_to_json(options))})
            return True
        if path == '/api/security/passkey/register/finish':
            if not _recent_settings_grant(conn, handler):
                _reply(handler, {'error': 'recent_verification_required', 'resource': 'settings'}, 423)
                return True
            from webauthn import verify_registration_response
            challenge, _ = _consume(conn, str(payload.get('challenge_id') or ''), 'register')
            conn.commit()  # A failed signature must not make the challenge reusable.
            try:
                verification = verify_registration_response(credential=payload.get('credential'),
                    expected_challenge=challenge, expected_origin=ORIGIN, expected_rp_id=RP_ID,
                    require_user_verification=True)
            except Exception:
                raise PermissionError('Passkey registration failed') from None
            conn.execute('INSERT INTO apollo_security_webauthn(credential_id,public_key,sign_count,created_at) VALUES(?,?,?,?)',
                         (verification.credential_id, verification.credential_public_key,
                          verification.sign_count, int(time.time())))
            conn.commit()
            _reply(handler, {'registered': True})
            return True
        if path == '/api/security/passkey/authenticate/options':
            resource = str(payload.get('resource') or '')
            if not _valid_resource(resource):
                raise ValueError('Unknown protected resource')
            from webauthn import generate_authentication_options, options_to_json
            from webauthn.helpers.structs import PublicKeyCredentialDescriptor, UserVerificationRequirement
            ids = [row[0] for row in conn.execute('SELECT credential_id FROM apollo_security_webauthn')]
            if not ids:
                _reply(handler, {'error': 'No passkey enrolled'}, 409)
                return True
            ident, challenge = _challenge(conn, 'authenticate', resource)
            options = generate_authentication_options(rp_id=RP_ID, challenge=challenge,
                allow_credentials=[PublicKeyCredentialDescriptor(id=value) for value in ids],
                user_verification=UserVerificationRequirement.REQUIRED)
            conn.commit()
            _reply(handler, {'challenge_id': ident, 'options': json.loads(options_to_json(options))})
            return True
        if path == '/api/security/passkey/authenticate/finish':
            from webauthn import verify_authentication_response, base64url_to_bytes
            _check_rate(conn)
            challenge, resource = _consume(conn, str(payload.get('challenge_id') or ''), 'authenticate')
            conn.commit()  # Consume even if credential verification fails.
            credential = payload.get('credential') or {}
            credential_id = base64url_to_bytes(str(credential.get('id') or ''))
            row = conn.execute('SELECT public_key,sign_count FROM apollo_security_webauthn WHERE credential_id=?',
                               (credential_id,)).fetchone()
            if not row:
                _failed(conn)
                conn.commit()
                raise PermissionError('Unknown passkey')
            try:
                verified = verify_authentication_response(credential=credential,
                    expected_challenge=challenge, expected_origin=ORIGIN, expected_rp_id=RP_ID,
                    credential_public_key=row[0], credential_current_sign_count=row[1],
                    require_user_verification=True)
            except Exception:
                _failed(conn)
                conn.commit()
                raise PermissionError('Passkey verification failed') from None
            conn.execute('UPDATE apollo_security_webauthn SET sign_count=? WHERE credential_id=?',
                         (verified.new_sign_count, credential_id))
            _verified(conn)
            token, expiry = _issue(conn, handler, resource, config)
            conn.commit()
            _reply(handler, {'resource': resource, 'expires_at': expiry}, token=token)
            return True
        _reply(handler, {'error': 'Not found'}, 404)
        return True
    except (ValueError, TypeError, KeyError, sqlite3.IntegrityError, PermissionError) as error:
        conn.rollback()
        _reply(handler, {'error': str(error)[:180]}, 403 if isinstance(error, PermissionError) else 400)
        return True
    finally:
        conn.close()
