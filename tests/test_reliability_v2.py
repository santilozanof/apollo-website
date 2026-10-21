import io
import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import apollo_media
import connection_health
import debrief_context
import debrief_personalization as ranking
import routines


class HealthTests(unittest.TestCase):
    def item(self, status, **kwargs):
        return {'integrations': [{'id': 'google_calendar', 'status': status, 'connected': status == 'connected', **kwargs}]}

    def test_outage_never_becomes_disconnect_and_confirmed_issue_sticks_until_success(self):
        healthy = connection_health.merge_snapshot(self.item('connected'), {})
        outage = connection_health.merge_snapshot(self.item('temporary_error'), healthy)
        self.assertFalse(outage['integrations'][0]['needs_attention'])
        failed = connection_health.merge_snapshot(self.item('reconnection_required'), outage)
        retry = connection_health.merge_snapshot(self.item('temporary_error'), failed)
        self.assertTrue(retry['integrations'][0]['needs_attention'])
        restored = connection_health.merge_snapshot(self.item('connected'), retry)
        self.assertFalse(restored['integrations'][0]['needs_attention'])

    def test_unconfigured_services_and_previously_connected_services_differ(self):
        first = connection_health.merge_snapshot(self.item('disconnected'), {})
        self.assertEqual(first['integrations'][0]['status'], 'not_configured')
        old = connection_health.merge_snapshot(self.item('connected'), {})
        lost = connection_health.merge_snapshot(self.item('disconnected'), old)
        self.assertTrue(lost['integrations'][0]['needs_attention'])

    def test_monitor_singleflight_cache_and_restart(self):
        store = {}; calls = []
        gate = threading.Event()
        def probe():
            calls.append(1); gate.wait(2); return self.item('reconnection_required')
        monitor = connection_health.HealthMonitor(lambda: store.get('value'), lambda value: store.update(value=value), probe)
        for _ in range(10): monitor.snapshot()
        gate.set()
        with monitor.lock: pass
        self.assertEqual(len(calls), 1)
        self.assertTrue(monitor.snapshot()['integrations'][0]['needs_attention'])
        restored = connection_health.HealthMonitor(lambda: store['value'], lambda v: None, lambda: self.item('temporary_error'))
        restored.snapshot(wait=True)
        self.assertTrue(restored.value['integrations'][0]['needs_attention'])


class PersonalBriefTests(unittest.TestCase):
    def test_conflicts_overdue_date_only_and_unavailable_sources(self):
        now = datetime(2026, 10, 19, 9, tzinfo=ZoneInfo('Europe/Zurich'))
        events = [
            {'summary': 'Class', 'start': {'dateTime': '2026-10-19T10:00:00+02:00'}, 'end': {'dateTime': '2026-10-19T11:00:00+02:00'}},
            {'summary': 'Appointment', 'start': {'dateTime': '2026-10-19T10:30:00+02:00'}, 'end': {'dateTime': '2026-10-19T11:30:00+02:00'}},
        ]
        tasks = [{'title': 'Essay', 'due_at': '2026-10-18', 'completed': False},
                 {'title': 'Reading', 'due_at': '2026-10-19', 'completed': False},
                 {'title': 'Done', 'due_at': '2026-10-18', 'completed': True}]
        result = debrief_context.personal_brief(now, events, tasks, {'integrations': []})
        self.assertEqual(len(result['my_day']), 2)
        self.assertIn('1 overdue', result['personal_intelligence'][1]['headline'])
        self.assertIn('overlaps', result['personal_intelligence'][0]['body'])
        self.assertNotIn('Done', json.dumps(result))
        self.assertTrue(result['availability'])
        empty = debrief_context.personal_brief(now, [], [], {'integrations': []}, {'google': 'offline'}, False)
        self.assertEqual(empty['my_day'], [])
        self.assertEqual(empty['personal_intelligence'], [])

    def test_whoop_never_treats_yesterday_or_unscored_data_as_today(self):
        now = datetime(2026, 10, 19, 9, tzinfo=ZoneInfo('Europe/Zurich'))
        summary = {'sleep': {'id': 's1', 'end': '2026-10-19T07:00:00+02:00', 'score_state': 'SCORED', 'total_sleep_hours': 7.5},
                   'recovery': {'sleep_id': 's1', 'score_state': 'SCORED', 'score': 62}}
        result = debrief_context.whoop_observation(summary, now)
        self.assertIn('7.5 hours', result['body'])
        summary['sleep']['end'] = '2026-10-18T07:00:00+02:00'
        self.assertIsNone(debrief_context.whoop_observation(summary, now))
        summary['sleep']['end'] = '2026-10-19T07:00:00+02:00'
        summary['recovery']['score_state'] = 'PENDING_SCORE'
        self.assertIsNone(debrief_context.whoop_observation(summary, now))


class RankingTests(unittest.TestCase):
    def story(self, title, topic='world', url=None):
        return {'headline': title, 'body': 'Verified reporting explains what happened and its significant practical consequences.',
                'source': 'Reuters', 'url': url or 'https://reuters.com/' + title.replace(' ', '-'),
                'published_at': '2026-10-19T07:00:00Z', 'topics': [topic], 'importance': .9}

    def test_music_cap_actual_taste_and_no_music_fallback(self):
        now = datetime(2026, 10, 19, 10, tzinfo=timezone.utc)
        pool = [self.story('Trade agreement changes import rules'), self.story('Scientific breakthrough enables new measurements', 'science')]
        pool += [self.story(name + ' announces album release', 'music') for name in ['Sade', 'Frank Ocean', 'Unknown Artist']]
        result = ranking.select_stories(pool, now=now)['stories']
        self.assertLessEqual(sum('music' in row['topics'] for row in result), 1)
        self.assertFalse(any('Unknown' in row['headline'] for row in result))
        actual = ranking.select_stories(pool, now=now, preferred_artists=['Unknown Artist'])['stories']
        self.assertTrue(any('Unknown' in row['headline'] for row in actual))
        self.assertFalse(any('Sade' in row['headline'] for row in actual))
        self.assertEqual(ranking.select_stories(pool[2:], now=now)['stories'], [])

    def test_feedback_migration_and_not_interested(self):
        conn = sqlite3.connect(':memory:'); conn.row_factory = sqlite3.Row
        conn.executescript('''CREATE TABLE debrief_story_feedback (story_id TEXT PRIMARY KEY, feedback INTEGER CHECK(feedback IN (-1,1)), topics_json TEXT, source_domain TEXT, headline TEXT, created_at TEXT, updated_at TEXT);
        INSERT INTO debrief_story_feedback VALUES ('old', 1, '[]', 'example.com', 'Old preference', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);''')
        ranking.init_schema(conn)
        story = self.story('Trade agreement changes import rules')
        ranking.save_feedback(conn, {**story, 'feedback': 'not_interested'})
        rows = ranking.feedback_rows(conn)
        self.assertEqual(len(rows), 2)
        selected = ranking.select_stories([story], feedback_rows=rows, now=datetime(2026, 10, 19, 10, tzinfo=timezone.utc))
        self.assertEqual(selected['stories'], [])
        ranking.init_schema(conn)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM debrief_story_feedback').fetchone()[0], 2)

    def test_article_checks_evidence_date_and_network_errors(self):
        story = self.story('Trade agreement changes import rules')
        story['evidence_quote'] = 'The trade agreement changes import rules for manufacturers'
        html = b'<html><meta property="article:published_time" content="2026-10-19T07:00:00Z"><p>The trade agreement changes import rules for manufacturers worldwide.</p></html>'
        class Response(io.BytesIO):
            status = 200
            headers = {'Content-Type': 'text/html'}
        class Opener:
            def open(self, *args, **kwargs): return Response(html)
        with patch('socket.getaddrinfo', return_value=[(2,1,6,'',('93.184.216.34',443))]), patch('urllib.request.build_opener', return_value=Opener()):
            self.assertTrue(ranking.verify_article(story))
            self.assertFalse(ranking.verify_article({**story, 'published_at': '2025-01-01T00:00:00Z'}))
            self.assertFalse(ranking.verify_article({**story, 'evidence_quote': 'These invented words do not appear in the article'}))
        with patch('socket.getaddrinfo', return_value=[(2,1,6,'',('127.0.0.1',443))]):
            self.assertFalse(ranking.verify_article(story))


class ImageAndWaterTests(unittest.TestCase):
    def test_preview_mime_orientation_and_without_pillow(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'wrong.dat'
            Image.new('RGB', (320, 120), 'blue').save(path, 'PNG')
            self.assertEqual(apollo_media.image_mime(path.read_bytes()[:64]), 'image/png')
            preview = apollo_media.image_preview(path)
            with Image.open(preview) as image:
                self.assertEqual(image.size, (320, 120))
            preview.unlink()
            with patch.dict('sys.modules', {'PIL': None}):
                self.assertEqual(apollo_media.image_preview(path), path)

    def test_iphone_heic_preview_is_browser_readable(self):
        try:
            import pillow_heif
        except ImportError:
            self.skipTest("Install requirements.txt to test HEIC conversion")
        from PIL import Image
        pillow_heif.register_heif_opener()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'iphone.heic'
            Image.new('RGB', (320, 160), 'blue').save(source, 'HEIF')
            self.assertEqual(apollo_media.image_mime(source.read_bytes()[:64]), 'image/heic')
            preview = apollo_media.image_preview(source)
            self.assertNotEqual(preview, source)
            with Image.open(preview) as image:
                self.assertEqual(image.format, 'WEBP')
                self.assertEqual(image.size, (320, 160))

    def test_standard_commons_thumbnail_host_is_supported(self):
        url = 'https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Example.jpg/640px-Example.jpg'
        class Response:
            status = 200
            headers = {'Content-Type': 'image/jpeg', 'Content-Length': '100'}
            def geturl(self): return url
            def __enter__(self): return self
            def __exit__(self, *args): pass
        with patch.object(apollo_media._OPENER, 'open', return_value=Response()):
            self.assertTrue(apollo_media._valid_image(url))
            self.assertFalse(apollo_media._valid_image('https://evil.example/image.jpg'))

    def test_supported_remote_asset_is_durable_and_deduplicated(self):
        from PIL import Image
        data = io.BytesIO(); Image.new('RGB', (20,20)).save(data, 'PNG')
        url = 'https://www.image-line.com/test.png'
        with tempfile.TemporaryDirectory() as directory, patch.object(apollo_media._OPENER, 'open', return_value=io.BytesIO(data.getvalue())) as opened:
            text = apollo_media.persist_supported_images('![Screenshot](' + url + ')', Path(directory))
            second = apollo_media.persist_supported_images('![Screenshot](' + url + ')', Path(directory))
            self.assertEqual(text, second)
            self.assertIn('/api/chat-media/', text)
            self.assertEqual(opened.call_count, 1)
            self.assertEqual(len(list(Path(directory).glob('*.media'))), 1)

    def test_710_exactly_once_and_history(self):
        conn = sqlite3.connect(':memory:'); conn.row_factory = sqlite3.Row
        routines.init_schema(conn)
        stamp = '2026-10-19T09:00:00+02:00'
        for _ in range(2):
            result = routines.log_water(conn, 710, 'Europe/Zurich', stamp, idempotency_key='same-intent')
        self.assertEqual(result['total_ml'], 710)
        self.assertEqual(len(result['entries']), 1)
        self.assertAlmostEqual(result['progress'], 710 / 2500)
        history = routines.history(conn, '2026-10-19', '2026-10-19', 'Europe/Zurich')
        self.assertEqual(history['days'][0]['hydration']['total_ml'], 710)


if __name__ == '__main__': unittest.main()
