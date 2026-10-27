import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import music_history
import spotify_curator_tool


def api_play(at="2026-03-12T12:00:00Z", track_id="abc"):
    return {"played_at": at, "track": {
        "id": track_id, "name": "Blue Hour", "duration_ms": 180000,
        "artists": [{"id": "artist-1", "name": "Aster"}],
        "album": {"id": "album-1", "name": "Night", "images": [{"url": "https://i.scdn.co/image/test"}]},
    }}


def extended_play(at="2026-03-12T12:03:00Z", ms=155000):
    return {"ts": at, "ms_played": ms, "spotify_track_uri": "spotify:track:abc",
            "master_metadata_track_name": "Blue Hour",
            "master_metadata_album_artist_name": "Aster",
            "master_metadata_album_album_name": "Night"}


class MusicHistoryTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        music_history.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_api_listen_has_no_fabricated_duration_and_export_enriches_once(self):
        result = music_history.insert_records(self.conn, [api_play()])
        self.assertEqual(result["imported"], 1)
        first = music_history.monthly_summary(self.conn, "2026-03", "UTC")
        self.assertEqual(first["duration_unknown_events"], 1)
        self.assertEqual(first["verified_ms"], 0)
        result = music_history.insert_records(self.conn, [extended_play(), extended_play()])
        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["duplicates"], 2)
        summary = music_history.monthly_summary(self.conn, "2026-03", "UTC")
        self.assertEqual(summary["events"], 1)
        self.assertEqual(summary["verified_ms"], 155000)
        self.assertEqual(summary["top_tracks"][0]["plays"], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM music_tracks").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM music_artists").fetchone()[0], 1)

    def test_account_and_extended_export_formats_and_idempotency(self):
        old = [{"endTime": "2026-03-12 12:03", "artistName": "Aster",
                "trackName": "Blue Hour", "msPlayed": 155000}]
        raw = json.dumps(old).encode()
        result = music_history.import_export(self.conn, "StreamingHistory_music_0.json", raw)
        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["format"], "account")
        self.assertTrue(music_history.import_export(self.conn, "same.json", raw)["already_imported"])
        extended = json.dumps([extended_play()]).encode()
        merged = music_history.import_export(self.conn, "endsong_0.json", extended)
        self.assertEqual(merged["imported"], 0)
        self.assertEqual(music_history.monthly_summary(self.conn, "2026-03")["events"], 1)

    def test_separate_plays_of_same_song_remain_separate(self):
        rows = [api_play("2026-03-12T12:00:00Z"), api_play("2026-03-12T12:03:10Z")]
        result = music_history.insert_records(self.conn, rows)
        self.assertEqual(result["imported"], 2)
        self.assertEqual(music_history.monthly_summary(self.conn, "2026-03")["events"], 2)

    def test_export_does_not_link_artist_or_album_to_track(self):
        music_history.insert_records(self.conn, [extended_play()])
        summary = music_history.monthly_summary(self.conn, "2026-03")
        self.assertEqual(summary["top_tracks"][0]["spotify_url"], "https://open.spotify.com/track/abc")
        self.assertIsNone(summary["top_artists"][0]["spotify_url"])
        self.assertIsNone(summary["top_albums"][0]["spotify_url"])

    def test_dst_month_boundary_uses_selected_timezone(self):
        start, end = music_history.month_bounds("2026-03", "Europe/Zurich")
        self.assertEqual(start, "2026-02-28T23:00:00+00:00")
        self.assertEqual(end, "2026-03-31T22:00:00+00:00")
        music_history.insert_records(self.conn, [extended_play("2026-02-28T23:30:00Z")])
        self.assertEqual(music_history.monthly_summary(self.conn, "2026-03", "Europe/Zurich")["events"], 1)
        self.assertEqual(music_history.monthly_summary(self.conn, "2026-02", "Europe/Zurich")["events"], 0)

    def test_recap_archive_is_stable_for_same_dataset(self):
        music_history.insert_records(self.conn, [extended_play()])
        first = music_history.archive_recap(self.conn, "2026-03")
        row = self.conn.execute("SELECT data_fingerprint, generated_at FROM music_recaps").fetchone()
        self.conn.execute("UPDATE music_sync_state SET last_success_at = '2026-03-13T00:00:00+00:00' WHERE provider = 'spotify'")
        second = music_history.archive_recap(self.conn, "2026-03")
        row2 = self.conn.execute("SELECT data_fingerprint, generated_at FROM music_recaps").fetchone()
        self.assertEqual(first, second)
        self.assertEqual(tuple(row), tuple(row2))

    def test_invalid_export_is_rejected_without_writes(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            music_history.import_export(self.conn, "wrong.json", b'[{"hello": 1}]')
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM music_listens").fetchone()[0], 0)

    def test_recent_api_cursor_is_bounded_and_duration_remains_unknown(self):
        class Spotify:
            def current_user_recently_played(self, **kwargs):
                self.kwargs = kwargs
                return {"items": [api_play()]}
        spotify = Spotify()
        response = spotify_curator_tool.recent_history(spotify, 1000)
        self.assertEqual(spotify.kwargs, {"limit": 50, "after": 999})
        self.assertEqual(len(response["items"]), 1)
        self.assertFalse(response["window_full"])
        self.assertIsNone(music_history.normalize_record(response["items"][0])["ms_played"])

    def test_background_sync_commits_cursor_with_events_and_records_backoff(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"APOLLO_BASE_DIR": directory}):
                import server
            database = Path(directory) / "apollo.db"
            tool = Path(directory) / "spotify_curator_tool.py"
            tool.touch()
            conn = sqlite3.connect(database)
            conn.row_factory = sqlite3.Row
            music_history.init_schema(conn)
            conn.commit()
            conn.close()
            success = type("Result", (), {"returncode": 0, "stdout": json.dumps({
                "items": [api_play()], "cursor_ms": 1773316800000, "window_full": True,
            }), "stderr": ""})()
            limited = type("Result", (), {"returncode": 2, "stdout": "", "stderr": json.dumps({
                "status": 429, "retry_after": 30,
            })})()
            with mock.patch.object(server, "DB_PATH", database), mock.patch.object(server, "SPOTIFY_CURATOR_TOOL", tool), mock.patch.object(server.subprocess, "run", side_effect=[success, limited]):
                self.assertTrue(server.music_history_sync_once())
                check = sqlite3.connect(database)
                check.row_factory = sqlite3.Row
                self.assertEqual(check.execute("SELECT COUNT(*) FROM music_listens").fetchone()[0], 1)
                self.assertEqual(check.execute("SELECT cursor_ms FROM music_sync_state").fetchone()[0], 1773316800000)
                self.assertIn("window was full", check.execute("SELECT coverage_warning FROM music_sync_state").fetchone()[0])
                check.close()
                self.assertFalse(server.music_history_sync_once())
                check = sqlite3.connect(database)
                check.row_factory = sqlite3.Row
                state = check.execute("SELECT cursor_ms, retry_after_at FROM music_sync_state").fetchone()
                self.assertEqual(state["cursor_ms"], 1773316800000)
                self.assertIsNotNone(state["retry_after_at"])
                check.close()


if __name__ == "__main__":
    unittest.main()
