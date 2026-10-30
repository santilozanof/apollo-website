"""Private Chat and History policies fail closed before personal data access."""
import json
import sqlite3
import time
import unittest
from types import SimpleNamespace

import apollo_security


class PrivateAccessTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        apollo_security.init_schema(self.conn)
        self.handler = SimpleNamespace(headers={})

    def tearDown(self):
        self.conn.close()

    def policy(self, **changes):
        config = {**apollo_security.policy(self.conn), **changes}
        self.conn.execute(
            'UPDATE apollo_security_policy SET policy_json=? WHERE id=1',
            (json.dumps(config),),
        )

    def test_private_prompt_requires_grant_but_public_prompt_is_isolated(self):
        self.policy(protect_sensitive_chat=True)
        self.assertEqual(
            apollo_security.private_access_mode(self.conn, self.handler, 'What is my university status?', True)[0],
            'locked',
        )
        self.assertEqual(
            apollo_security.private_access_mode(self.conn, self.handler, 'When was the Moon landing?', True)[0],
            'public',
        )
        self.assertEqual(
            apollo_security.private_access_mode(self.conn, self.handler, 'When was the Moon landing?', False)[0],
            'locked',
        )
        token = 'test-only-token'
        self.handler.headers['Cookie'] = f'{apollo_security.COOKIE}={token}'
        self.conn.execute(
            'INSERT INTO apollo_security_grants(token_digest,resource,verified_at,expires_at) VALUES(?,?,?,?)',
            (apollo_security._digest(token), 'private', int(time.time()), int(time.time()) + 300),
        )
        self.assertEqual(
            apollo_security.private_access_mode(self.conn, self.handler, 'Tell me about my family', True)[0],
            'allow',
        )

    def test_expired_grant_does_not_authorize_private_context(self):
        self.policy(protect_sensitive_chat=True)
        token = 'expired-test-token'
        self.handler.headers['Cookie'] = f'{apollo_security.COOKIE}={token}'
        self.conn.execute(
            'INSERT INTO apollo_security_grants(token_digest,resource,verified_at,expires_at) VALUES(?,?,?,?)',
            (apollo_security._digest(token), 'private', int(time.time()) - 400, int(time.time()) - 1),
        )
        self.assertEqual(
            apollo_security.private_access_mode(self.conn, self.handler, 'What are my memories?', True)[0],
            'locked',
        )

    def test_history_and_interactive_routes_have_explicit_scopes(self):
        self.assertEqual(apollo_security._resource('/api/chats/search', 'GET'), 'history')
        self.assertEqual(apollo_security._resource('/api/chats/42', 'GET'), 'history')
        self.assertEqual(apollo_security._resource('/api/chats/42/messages', 'POST'), 'chat')
        self.assertEqual(apollo_security._resource('/api/interactive/quizzes', 'GET'), 'chat')
        self.policy(protect_history=True)
        self.assertTrue(apollo_security._requires(apollo_security.policy(self.conn), 'history'))
        self.assertFalse(apollo_security._requires(apollo_security.policy(self.conn), 'private'))


if __name__ == '__main__':
    unittest.main()
