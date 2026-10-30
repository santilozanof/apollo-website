"""Private Chat and History policies fail closed before personal data access."""
import json
import sqlite3
import time
import unittest
from types import SimpleNamespace
from unittest import mock

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

    def test_public_followup_reads_only_explicitly_public_turns(self):
        self.conn.execute('CREATE TABLE messages(id INTEGER PRIMARY KEY,chat_id INTEGER,role TEXT,content TEXT)')
        self.conn.executemany('INSERT INTO messages(id,chat_id,role,content) VALUES(?,?,?,?)', [
            (1, 7, 'user', 'My private university application'),
            (2, 7, 'assistant', 'Private admission details'),
            (3, 7, 'user', 'Why did the singer die?'),
            (4, 7, 'assistant', 'The reported cause was alcohol poisoning.'),
            (5, 7, 'user', 'Bruh so cause of a fun party.'),
            (6, 8, 'assistant', 'Another chat'),
        ])
        apollo_security.mark_public_pair(self.conn, 7, 3, 4)
        history = apollo_security.public_conversation(self.conn, 7, 5)
        self.assertEqual([turn['content'] for turn in history], [
            'Why did the singer die?', 'The reported cause was alcohol poisoning.'])
        with self.assertRaises(ValueError):
            apollo_security.mark_public_pair(self.conn, 7, 5, 6)
        captured = {}
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, *_): return b'{"choices":[{"message":{"content":"That is not what happened."}}]}'
        def urlopen(request, timeout):
            captured.update(json.loads(request.data))
            return Response()
        server = SimpleNamespace(HERMES_URL='http://localhost/test', get_api_key=lambda: 'test-key')
        with mock.patch.object(apollo_security.urllib.request, 'urlopen', side_effect=urlopen):
            apollo_security.public_answer_text(server, 'Bruh so cause of a fun party.', history)
        self.assertEqual([turn['role'] for turn in captured['messages']],
                         ['system', 'user', 'assistant', 'user'])
        self.assertNotIn('private university', json.dumps(captured).lower())
        self.assertEqual(captured['model'], 'gpt-5.6-terra')

    def test_legacy_public_job_backfill_requires_unique_exact_answer(self):
        self.conn.execute('CREATE TABLE messages(id INTEGER PRIMARY KEY,chat_id INTEGER,role TEXT,content TEXT)')
        self.conn.execute('CREATE TABLE chat_generation_jobs(chat_id INTEGER,public_only INTEGER,state TEXT,message_json TEXT)')
        self.conn.executemany('INSERT INTO messages VALUES(?,?,?,?)', [
            (1, 7, 'user', 'Private question'),
            (2, 7, 'assistant', 'Private answer'),
            (3, 7, 'user', 'Why did the singer die?'),
            (4, 7, 'assistant', 'Alcohol poisoning.'),
            (5, 7, 'user', 'Bruh so cause of a fun party.'),
            (6, 7, 'assistant', 'No, that was a tragedy.'),
            (7, 8, 'user', 'First public question'),
            (8, 8, 'assistant', 'Repeated answer'),
            (9, 8, 'user', 'Second public question'),
            (10, 8, 'assistant', 'Repeated answer'),
        ])
        self.conn.executemany('INSERT INTO chat_generation_jobs VALUES(?,?,?,?)', [
            (7, 0, 'complete', json.dumps({'role': 'assistant', 'content': 'Private answer'})),
            (7, 1, 'complete', json.dumps({'role': 'assistant', 'content': 'Alcohol poisoning.'})),
            (7, 1, 'complete', json.dumps({'role': 'assistant', 'content': 'No, that was a tragedy.'})),
            (8, 1, 'complete', json.dumps({'role': 'assistant', 'content': 'Repeated answer'})),
        ])
        self.assertEqual(apollo_security.backfill_public_pairs(self.conn), 2)
        self.assertEqual(apollo_security.backfill_public_pairs(self.conn), 2)
        tagged = [row[0] for row in self.conn.execute(
            'SELECT message_id FROM apollo_public_messages ORDER BY message_id')]
        self.assertEqual(tagged, [3, 4, 5, 6])
        self.assertEqual([turn['content'] for turn in apollo_security.public_conversation(self.conn, 7, 6)],
                         ['Why did the singer die?', 'Alcohol poisoning.', 'Bruh so cause of a fun party.'])

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
