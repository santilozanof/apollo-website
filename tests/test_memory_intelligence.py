import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from apollo_memory import MemoryStore, init_schema


class FakeEmbeddings:
    name = 'deterministic-semantic-fixture'

    def encode(self, texts):
        return [[1., 0.] if any(word in text.lower() for word in ('restaurant', 'bistro', 'paris', 'dining')) else [0., 1.] for text in texts]


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'memory.db'
        self.addCleanup(self.tmp.cleanup)
        conn = self.db()
        conn.executescript('''CREATE TABLE chats(id INTEGER PRIMARY KEY,title TEXT);
            CREATE TABLE messages(id INTEGER PRIMARY KEY,chat_id INTEGER,role TEXT,content TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);''')
        init_schema(conn)
        conn.commit(); conn.close()
        self.store = MemoryStore(self.db, 'alice', FakeEmbeddings())
        self.chat(1)

    def db(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def chat(self, chat_id, owner='alice'):
        with self.db() as conn:
            conn.execute('INSERT INTO chats VALUES (?,?)', (chat_id, 'Test'))
            conn.execute('INSERT INTO memory_chat_scope VALUES (?,?,0)', (chat_id, owner))

    def message(self, text, role='user', chat=1, date='2026-10-20T12:00:00Z'):
        with self.db() as conn:
            return conn.execute('INSERT INTO messages(chat_id,role,content,created_at) VALUES (?,?,?,?)', (chat, role, text, date)).lastrowid

    def test_explicit_preference_persists_across_store_instances(self):
        self.store.save('I prefer concise answers', memory_key='answer_length')
        reopened = MemoryStore(self.db, 'alice')
        self.assertEqual(reopened.search_memories('concise answers')[0]['content'], 'I prefer concise answers')

    def test_unsaved_fact_months_earlier_and_context(self):
        first = self.message('I visited Paris.', date='2026-02-01T12:00:00Z')
        hit = self.message('The restaurant was Le Comptoir.', date='2026-02-01T12:01:00Z')
        self.message('It has a seasonal menu.', role='assistant', date='2026-02-01T12:02:00Z')
        result = self.store.search('restaurant', after='2026-01-01', before='2026-03-01')
        self.assertEqual(result['results'][0]['id'], hit)
        self.assertEqual(result['results'][0]['context'][0]['id'], first)
        self.assertEqual(self.store.search('restaurant', after='2026-04-01')['status'], 'not_found')

    def test_real_hybrid_path_can_retrieve_zero_keyword_overlap(self):
        self.message('A little bistro near the Seine was our favorite.', date='2026-01-04')
        self.store.process_pending(lambda *_: [])
        result = self.store.search('Paris dining')
        self.assertEqual(result['mode'], 'hybrid')
        self.assertIn('Seine', result['results'][0]['content'])

    def test_exact_phrase_and_search_syntax_are_safe(self):
        self.message('Project Aurora is a music project.')
        self.message('Aurora Project has the words reversed.')
        result = self.store.search('Project Aurora', exact=True)
        self.assertEqual(len(result['results']), 1)
        self.store.search('" OR * NEAR(')

    def test_new_chat_project_continuity(self):
        self.message('Music project Aurora: finish drums next, release in December.')
        self.chat(2)
        result = self.store.search('music project Aurora')
        self.assertEqual(result['results'][0]['chat_id'], 1)
        self.assertIn('finish drums', result['results'][0]['content'])

    def test_automatic_memory_is_grounded_and_skips_sensitive_data(self):
        mid = self.message('I prefer oat milk in coffee.')
        self.store.process_pending(lambda row, existing: [{
            'content': 'Prefers oat milk', 'key': 'coffee_milk', 'quote': 'I prefer oat milk',
            'category': 'preference', 'confidence': .96, 'durable': True, 'sensitive': False}])
        facts = self.store.list_memories()
        self.assertEqual(facts[0]['source_message_id'], mid)
        self.assertEqual(facts[0]['source_quote'], 'I prefer oat milk')
        with self.assertRaises(ValueError):
            self.store.save('Owns a Ferrari', source_message_id=mid, source_quote='Ferrari', automatic=True)
        mid = self.message('My password is secret-123')
        self.assertIsNone(self.store.save('My password is secret-123', source_message_id=mid, source_quote='My password is secret-123', automatic=True))

    def test_corrections_supersede_older_facts_and_backfill_cannot_reverse_them(self):
        old = self.message('I prefer dairy milk', date='2026-01-01')
        new = self.message('Correction: I prefer oat milk now', date='2026-10-20')
        self.store.save('Prefers dairy milk', memory_key='milk', source_message_id=old, source_quote='I prefer dairy milk')
        self.store.save('Prefers oat milk', memory_key='milk', source_message_id=new, source_quote='I prefer oat milk now')
        self.store.save('Prefers dairy milk', memory_key='milk', source_message_id=old, source_quote='I prefer dairy milk')
        self.assertEqual([r['content'] for r in self.store.list_memories()], ['Prefers oat milk'])
        self.assertEqual(len(self.store.search('milk')['results']), 2)
        self.store.save('Prefers almond milk', memory_key='milk')
        self.store.save('Prefers oat milk', memory_key='milk', source_message_id=new, source_quote='I prefer oat milk now')
        self.assertEqual(self.store.list_memories()[0]['content'], 'Prefers almond milk')

    def test_unresolved_contradictions_preserve_sources(self):
        a = self.message('Project deadline is November 1')
        b = self.message('Project deadline might be November 7')
        self.store.save('Deadline November 1', memory_key='deadline', source_message_id=a, source_quote='deadline is November 1')
        self.store.save('Possible deadline November 7', memory_key='tentative_deadline', source_message_id=b, source_quote='deadline might be November 7')
        self.assertEqual(len(self.store.search_memories('deadline')), 2)

    def test_deleted_chat_removes_memory_index_and_originals(self):
        mid = self.message('I love jazz')
        self.store.save('Loves jazz', source_message_id=mid, source_quote='I love jazz')
        self.store.process_pending(lambda *_: [])
        with self.db() as conn:
            conn.execute('DELETE FROM chats WHERE id=1')
        self.assertEqual(self.store.search('jazz')['status'], 'not_found')
        self.assertEqual(self.store.list_memories(), [])
        with self.db() as conn:
            for table in ('messages','message_search','message_embeddings','memory_jobs'):
                self.assertEqual(conn.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)

    def test_forgetting_prevents_history_neighbor_and_queue_resurrection(self):
        mid = self.message('I like restaurant Le Comptoir')
        self.message('Paris was beautiful')
        memory_id = self.store.save('Likes Le Comptoir', memory_key='restaurant', source_message_id=mid, source_quote='I like restaurant Le Comptoir')
        self.store.forget(memory_id)
        result = self.store.search('Paris')
        self.assertNotIn('Comptoir', json.dumps(result))
        self.assertIsNone(self.store.save('Likes Le Comptoir', source_message_id=mid, source_quote='I like restaurant Le Comptoir', automatic=True))
        self.assertEqual(self.store.list_memories(), [])

    def test_excluded_chat_is_not_searchable_or_consolidated(self):
        mid = self.message('My favorite restaurant is private')
        self.store.exclude_chat(1)
        self.assertEqual(self.store.search('restaurant')['status'], 'not_found')
        self.assertEqual(self.store.process_pending(lambda *_: self.fail('excluded chat reached model')), 0)
        with self.assertRaises(ValueError):
            self.store.save('Private', source_message_id=mid, source_quote='private')

    def test_owner_isolation_applies_to_results_neighbors_and_facts(self):
        self.chat(2, 'bob')
        mid = self.message('Private restaurant Le Secret', chat=2)
        bob = MemoryStore(self.db, 'bob', FakeEmbeddings())
        bob.save('Likes private restaurant', source_message_id=mid, source_quote='Private restaurant')
        bob.process_pending(lambda *_: [])
        self.assertEqual(self.store.search('private restaurant')['status'], 'not_found')
        self.assertEqual(self.store.list_memories(), [])
        with self.assertRaises(ValueError):
            self.store.exclude_chat(2)

    def test_disabled_search_and_retention(self):
        old = self.message('Old project', date='2000-01-01')
        self.store.save('Old project', source_message_id=old, source_quote='Old project')
        self.store.configure({'history_search': False})
        self.assertEqual(self.store.search('project')['status'], 'disabled')
        self.store.configure({'history_search': True, 'retention_days': 30})
        self.assertEqual(self.store.search('project')['status'], 'not_found')
        self.assertEqual(self.store.list_memories(), [])

    def test_failed_search_admits_not_found_and_embedding_failure_falls_back(self):
        self.store.embeddings.encode = lambda *_: (_ for _ in ()).throw(RuntimeError('offline'))
        self.message('Project Aurora')
        result = self.store.search('Aurora')
        self.assertEqual(result['mode'], 'keyword')
        self.assertEqual(result['semantic_status'], 'unavailable')
        self.assertEqual(self.store.search('unknown restaurant')['status'], 'not_found')

    def test_deleted_during_consolidation_cannot_reappear(self):
        self.message('I prefer jazz')
        def extract(*_):
            with self.db() as conn:
                conn.execute('DELETE FROM messages')
            return [{'content':'Prefers jazz','quote':'I prefer jazz','key':'music','category':'preference','confidence':.99,'durable':True,'sensitive':False}]
        self.store.process_pending(extract)
        self.assertEqual(self.store.list_memories(), [])
        self.assertEqual(self.store.search('jazz')['status'], 'not_found')

    def test_optional_embedding_failure_does_not_disable_automatic_memory(self):
        self.message('I prefer jazz')
        self.store.embeddings.encode = lambda *_: (_ for _ in ()).throw(RuntimeError('model missing'))
        self.store.process_pending(lambda *_:[{'content':'Prefers jazz','quote':'I prefer jazz','key':'music','category':'preference','confidence':.99,'durable':True,'sensitive':False}])
        self.assertEqual(self.store.list_memories()[0]['content'],'Prefers jazz')

    def test_late_import_of_older_fact_does_not_reverse_correction(self):
        recent = self.message('I prefer oat milk', date='2026-10-20')
        imported = self.message('I prefer dairy milk', date='2026-01-01')
        self.store.save('Oat milk',memory_key='milk',source_message_id=recent,source_quote='oat milk')
        self.store.save('Dairy milk',memory_key='milk',source_message_id=imported,source_quote='dairy milk')
        self.assertEqual(self.store.list_memories()[0]['content'],'Oat milk')

    def test_long_messages_index_all_chunks_and_excerpt_matched_region(self):
        self.message(('Software code. '*1000)+'The restaurant in Paris was Le Comptoir.')
        self.store.process_pending(lambda *_:[])
        with self.db() as conn:
            self.assertGreater(conn.execute('SELECT count(*) FROM message_embeddings').fetchone()[0],10)
        result = self.store.search('Comptoir')
        self.assertIn('Le Comptoir',result['results'][0]['content'])
        self.assertTrue(result['results'][0]['content_truncated'])

    def test_explicit_do_not_remember_instruction_blocks_auto_save(self):
        mid = self.message("I prefer jazz but don't remember this.")
        self.assertIsNone(self.store.save('Prefers jazz', source_message_id=mid,source_quote='I prefer jazz',automatic=True))

    def test_migration_backfills_preexisting_history_idempotently(self):
        self.message('Ancient plan')
        with self.db() as conn:
            conn.execute('DELETE FROM message_search')
            init_schema(conn)
            init_schema(conn)
        self.assertEqual(len(self.store.search('Ancient')['results']), 1)


if __name__ == '__main__':
    unittest.main()
