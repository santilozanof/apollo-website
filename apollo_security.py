"""Single-owner step-up authentication for Apollo's private Tailscale origin.

The Tailscale proxy remains the account boundary. This module adds a separate,
short-lived proof of possession for protected resources; a browser session or
model assertion never creates that proof.
"""

import base64
import hashlib
import hmac
import json
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


TABS = frozenset({'chat', 'music', 'calendar', 'tasks', 'routines', 'debrief', 'studio'})
POLICIES = frozenset({'leave', '5m', '15m'})
LEVELS = frozenset({'standard', 'enhanced', 'maximum'})
ORIGIN = os.environ.get('APOLLO_SECURITY_ORIGIN', 'https://ubuntu-2gb-hel1-1.tailc5eaaa.ts.net').rstrip('/')
RP_ID = urllib.parse.urlparse(ORIGIN).hostname
COOKIE = '__Host-apollo-stepup'


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
    ''')
    conn.execute('INSERT OR IGNORE INTO apollo_security_policy(id,policy_json) VALUES(1,?)',
                 (json.dumps({'tabs': {}, 'privacy': 'standard', 'protect_spotify': False}),))


def policy(conn):
    row = conn.execute('SELECT policy_json FROM apollo_security_policy WHERE id=1').fetchone()
    return json.loads(row[0]) if row else {'tabs': {}, 'privacy': 'standard', 'protect_spotify': False}


def _digest(token):
    return hashlib.sha256(token.encode('utf-8')).digest()


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
    if not token:
        return None
    row = conn.execute('SELECT expires_at FROM apollo_security_grants WHERE token_digest=? AND resource=?',
                       (_digest(token), resource)).fetchone()
    return (_digest(token), row[0], resource) if row and row[0] > int(time.time()) else None


def generation_grant_active(job):
    details = job.get('_security_grant')
    import server
    conn = server.db()
    try:
        if not details:
            return not _requires(policy(conn), 'chat')
        if details[1] <= int(time.time()):
            return False
        row = conn.execute('SELECT 1 FROM apollo_security_grants WHERE token_digest=? AND resource=? AND expires_at>?',
                           (details[0], details[2], int(time.time()))).fetchone()
        return bool(row)
    finally:
        conn.close()


def _resource(path):
    for prefix, resource in (
        ('/api/chat', 'chat'), ('/api/chats', 'chat'), ('/api/memory', 'chat'),
        ('/api/music', 'music'), ('/api/spotify', 'music'), ('/api/now-playing', 'music'),
        ('/api/calendar', 'calendar'), ('/api/google', 'calendar'),
        ('/api/gmail', 'connections'),
        ('/api/tasks', 'tasks'), ('/api/routines', 'routines'),
        ('/api/debrief', 'debrief'), ('/api/studio', 'studio'), ('/api/wip', 'studio'),
        ('/api/whoop', 'whoop'), ('/api/notifications', 'notifications'),
        ('/api/connections', 'connections'), ('/api/client-context', 'chat'),
        ('/api/automations', 'tasks'),
        ('/api/agent/traces', 'chat'),
    ):
        if path == prefix or path.startswith(prefix + '/') or (prefix == '/api/chat' and path.startswith('/api/chat-')):
            return resource
    return None


def _requires(config, resource):
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
    duration = config.get('tabs', {}).get(resource, '5m')
    ttl = 30 if duration == 'leave' else 900 if duration == '15m' else 300
    existing = _cookie(handler)
    known = bool(existing and conn.execute(
        'SELECT 1 FROM apollo_security_grants WHERE token_digest=? AND expires_at>? LIMIT 1',
        (_digest(existing), now)).fetchone())
    token = existing if known else secrets.token_urlsafe(48)
    conn.execute('DELETE FROM apollo_security_grants WHERE expires_at<?', (now,))
    conn.execute('INSERT INTO apollo_security_grants(token_digest,resource,verified_at,expires_at) VALUES(?,?,?,?) '
                 'ON CONFLICT(token_digest,resource) DO UPDATE SET verified_at=excluded.verified_at,expires_at=excluded.expires_at',
                 (_digest(token), resource, now, now + ttl))
    return token, now + ttl


def _valid_resource(resource):
    return resource in TABS or resource in {'whoop', 'notifications', 'connections', 'settings'}


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
    resource = _resource(path)
    if not resource:
        return False
    conn = server.db()
    try:
        config = policy(conn)
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
                        for resource in TABS | {'whoop', 'notifications', 'connections', 'settings'}}
            _reply(handler, {'tabs': config.get('tabs', {}), 'privacy': config.get('privacy', 'standard'),
                             'protect_spotify': bool(config.get('protect_spotify')),
                             'enrolled': enrolled,
                             'passkeys': conn.execute('SELECT COUNT(*) FROM apollo_security_webauthn').fetchone()[0],
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
            if not question or len(question) > 1200:
                raise ValueError('Enter a short public question')
            # This path receives no chat history, account data, tools, or private
            # system context. It is deliberately separate from personal chat.
            request = urllib.request.Request(server.HERMES_URL,
                data=json.dumps({'provider': 'openai-codex', 'model': 'gpt-5.6-luna',
                    'model_options': {'reasoning_effort': 'low', 'disable_tools': True},
                    'messages': [
                        {'role': 'system', 'content': 'Answer public, general questions only. You have no access to Apollo personal data, saved conversations, accounts or connected services. If asked for personal details, say verification is required. Do not imply you checked sources.'},
                        {'role': 'user', 'content': question}]}).encode('utf-8'),
                headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + server.get_api_key()},
                method='POST')
            try:
                with urllib.request.urlopen(request, timeout=18) as response:
                    result = json.loads(response.read(262144))
            except (TimeoutError, OSError, urllib.error.URLError, json.JSONDecodeError):
                _reply(handler, {'error': 'Public answer temporarily unavailable'}, 503)
                return True
            answer = str(result.get('choices', [{}])[0].get('message', {}).get('content') or '').strip()
            _reply(handler, {'answer': answer[:8000] or 'I could not answer that public question.'})
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
                conn.execute('DELETE FROM apollo_security_grants WHERE token_digest=? AND resource=?',
                             (_digest(_cookie(handler)), resource))
            else:
                conn.execute('DELETE FROM apollo_security_grants WHERE token_digest=?', (_digest(_cookie(handler)),))
            conn.commit()
            _reply(handler, {'revoked': True}, clear=not resource)
            return True
        if path == '/api/security/policy':
            if not _grant(conn, handler, 'settings'):
                _reply(handler, {'error': 'verification_required', 'resource': 'settings'}, 423)
                return True
            tabs = payload.get('tabs')
            level = payload.get('privacy')
            if not isinstance(tabs, dict) or any(key not in TABS or value not in POLICIES for key, value in tabs.items()):
                raise ValueError('Invalid tab-lock policy')
            if level not in LEVELS or not isinstance(payload.get('protect_spotify'), bool):
                raise ValueError('Invalid privacy policy')
            next_config = {'tabs': tabs, 'privacy': level, 'protect_spotify': payload['protect_spotify']}
            conn.execute('UPDATE apollo_security_policy SET policy_json=? WHERE id=1', (json.dumps(next_config),))
            conn.execute('DELETE FROM apollo_security_grants WHERE resource!=?', ('settings',))
            conn.commit()
            _reply(handler, next_config)
            return True
        if path in {'/api/security/passphrase/change', '/api/security/recovery/regenerate',
                    '/api/security/passkey/delete'}:
            if not _grant(conn, handler, 'settings'):
                _reply(handler, {'error': 'verification_required', 'resource': 'settings'}, 423)
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
                conn.execute('DELETE FROM apollo_security_grants WHERE resource!=?', ('settings',))
                conn.commit()
                _reply(handler, {'changed': True})
            else:
                codes = _recovery_codes(conn)
                conn.commit()
                _reply(handler, {'recovery_codes': codes})
            return True
        if path == '/api/security/passkey/register/options':
            if not _grant(conn, handler, 'settings'):
                _reply(handler, {'error': 'verification_required', 'resource': 'settings'}, 423)
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
            if not _grant(conn, handler, 'settings'):
                _reply(handler, {'error': 'verification_required', 'resource': 'settings'}, 423)
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
