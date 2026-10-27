"""Optional offline model smoke test. Uses only synthetic statements.

APOLLO_TEST_EMBEDDING_MODEL=/local/model python -m unittest discover -s tests -p test_real_semantic_memory.py
"""
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from apollo_memory import LocalEmbeddings, MemoryStore, init_schema


@unittest.skipUnless(os.environ.get('APOLLO_TEST_EMBEDDING_MODEL'), 'optional local embedding model not provisioned')
class RealSemanticMemoryTests(unittest.TestCase):
    def test_real_model_recovers_paraphrased_episode_and_saved_fact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'memory.db'
            def connect():
                conn = sqlite3.connect(path); conn.row_factory = sqlite3.Row; return conn
            with connect() as conn:
                conn.executescript('CREATE TABLE chats(id INTEGER PRIMARY KEY); CREATE TABLE messages(id INTEGER PRIMARY KEY,chat_id INTEGER,role TEXT,content TEXT,created_at TEXT);')
                init_schema(conn)
                conn.execute('INSERT INTO chats VALUES (1)')
                conn.execute("INSERT INTO memory_chat_scope VALUES (1,'fixture',0)")
                conn.execute("INSERT INTO messages VALUES (1,1,'user',?, '2026-01-01')", ('I loved the little bistro Le Comptoir on our trip to Paris.',))
                conn.execute("INSERT INTO messages VALUES (2,1,'user',?, '2026-01-01')", ('The software project uses a relational database and Python.',))
            memory = MemoryStore(connect, 'fixture', LocalEmbeddings(os.environ['APOLLO_TEST_EMBEDDING_MODEL']))
            memory.save('I enjoy going for long walks in the mountains on weekends.', memory_key='weekend_activity')
            started = time.perf_counter()
            memory.process_pending(lambda *_: [])
            indexed = time.perf_counter()
            result = memory.search('Where did we enjoy French dining?')
            self.assertEqual(result['mode'], 'hybrid')
            self.assertEqual(result['results'][0]['id'], 1)
            self.assertIn('Le Comptoir', result['results'][0]['content'])
            facts = memory.search_memories('Favorite hiking hobby?', semantic=True)
            self.assertTrue(facts)
            self.assertIn('mountains', facts[0]['content'])
            print(f'Real embeddings: index/load={indexed-started:.3f}s retrieval={time.perf_counter()-indexed:.3f}s')


if __name__ == '__main__': unittest.main()
