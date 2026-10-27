"""Exercise actual generation, SQLite upserts, throttling and failure behavior without APIs."""
import importlib.util
import json
import sqlite3
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import debrief_personalization

ROOT = Path(__file__).resolve().parents[1]


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.db'
        self.state = {'time_zone': 'UTC'}
        def db():
            conn = sqlite3.connect(self.path); conn.row_factory = sqlite3.Row; return conn
        self.db = db
        conn = db()
        conn.executescript('CREATE TABLE daily_debriefs(id INTEGER PRIMARY KEY, local_date TEXT UNIQUE, timezone TEXT, content TEXT, generated_at TEXT DEFAULT CURRENT_TIMESTAMP);')
        debrief_personalization.init_schema(conn); conn.commit(); conn.close()
        self.now = datetime.now(timezone.utc)
        self.story = {'category': 'Science', 'topics': ['science'], 'headline': 'Researchers demonstrate a reproducible scientific advance',
                      'body': 'Researchers report a measured advance with concrete consequences for future scientific instruments.',
                      'source': 'Nature', 'url': 'https://nature.com/articles/verified-fixture', 'published_at': self.now.isoformat(), 'importance': .95}
        self.model = Mock(return_value=json.dumps({'candidates': [self.story]}))
        self.spotify = Mock(side_effect=RuntimeError('Spotify temporarily unavailable'))
        source = types.SimpleNamespace(
            ask_hermes=self.model, db=db, init_db=lambda: None, DB_PATH=self.path,
            app_state_get=lambda key, default=None: self.state.get(key, default),
            app_state_set=lambda key, value: self.state.update({key: value}),
            apollo_calendar_events=lambda **kwargs: ([], {}),
            get_tasks=lambda: [{'title': 'Essay', 'due_at': self.now.date().isoformat(), 'completed': False}],
            apollo_connections_registry=lambda **kwargs: {'integrations': [
                {'id': 'google_calendar', 'status': 'connected'}, {'id': 'spotify', 'status': 'connected'}]},
            apollo_spotify_tool_command=self.spotify, whoop_current_summary=lambda: {},
        )
        spec = importlib.util.spec_from_file_location('isolated_generation', ROOT / 'generate_debrief.py')
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'server': source}): spec.loader.exec_module(self.module)

    def tearDown(self): self.temp.cleanup()

    def saved(self):
        conn = self.db(); rows = conn.execute('SELECT content FROM daily_debriefs').fetchall(); conn.close()
        self.assertEqual(len(rows), 1)
        return json.loads(rows[0]['content'])

    def test_spotify_failure_keeps_non_music_briefing_and_repeated_run_costs_nothing(self):
        with patch.object(debrief_personalization, 'verify_article', return_value=True):
            self.assertTrue(self.module.generate(force=True))
            self.assertFalse(self.module.generate(force=True))
        self.assertEqual(self.model.call_count, 1)
        brief = self.saved()
        self.assertEqual(brief['news_status'], 'ready')
        self.assertEqual(brief['stories'][0]['topics'], ['science'])
        self.assertTrue(any('deadline' in row['headline'] for row in brief['my_day']))
        self.assertTrue(any(row['source'] == 'Spotify' for row in brief['availability']))

    def test_failed_research_saves_useful_partial_and_throttles_retry(self):
        self.model.side_effect = RuntimeError('Research offline')
        self.assertTrue(self.module.generate(force=True))
        brief = self.saved()
        self.assertEqual(brief['stories'], [])
        self.assertEqual(brief['news_status'], 'unavailable')
        self.assertTrue(brief['my_day'])
        self.assertEqual(self.model.call_count, 2)
        self.assertFalse(self.module.generate(force=True))
        self.assertEqual(self.model.call_count, 2)

    def test_unverified_articles_are_not_published_and_existing_ready_news_survives_failure(self):
        with patch.object(debrief_personalization, 'verify_article', return_value=True): self.module.generate(force=True)
        self.state.pop('debrief_attempt:' + self.now.date().isoformat())
        self.model.side_effect = RuntimeError('Research offline')
        self.module.generate(force=True)
        brief = self.saved()
        self.assertEqual(brief['news_status'], 'ready')
        self.assertEqual(len(brief['stories']), 1)
        self.assertTrue(any('earlier verified' in item['message'] for item in brief['availability']))

    def test_parallel_run_does_not_call_model(self):
        import fcntl
        with open(self.path.parent / '.debrief-generation.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertFalse(self.module.generate(force=True))
        self.model.assert_not_called()


if __name__ == '__main__': unittest.main()
