import sqlite3
import unittest
from datetime import datetime, timezone

import music_analytics
import music_history


TRACK_A = "A" * 22
TRACK_B = "B" * 22
ARTIST_A = "C" * 22
ARTIST_B = "D" * 22
ALBUM_A = "E" * 22


def play(at, track=TRACK_A, name="Blue Hour", artists=None):
    return {"played_at": at, "track": {
        "id": track, "name": name, "duration_ms": 180000,
        "artists": artists or [{"id": ARTIST_A, "name": "Aster"}],
        "album": {"id": ALBUM_A, "name": "Night", "images": [{"url": "https://i.scdn.co/image/test"}]},
    }}


class MusicAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        music_history.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_timezone_week_and_year_bounds(self):
        p = music_analytics.period("daily", "2026-03-29", "Europe/Zurich")
        self.assertEqual(p["start"], "2026-03-28T23:00:00+00:00")
        self.assertEqual(p["end"], "2026-03-29T22:00:00+00:00")
        self.assertEqual(music_analytics.period("weekly", "2026-10-27")["first_date"], "2026-10-26")
        self.assertEqual(music_analytics.period("yearly", "2026-10-27")["end_date"], "2027-01-01")
        with self.assertRaises(ValueError):
            music_analytics.period("daily", "2099-01-01")

    def test_rankings_period_search_pagination_and_detail(self):
        artists = [{"id": ARTIST_A, "name": "Aster"}, {"id": ARTIST_B, "name": "Beryl"}]
        music_history.insert_records(self.conn, [
            play("2026-10-27T12:00:00Z", artists=artists),
            play("2026-10-27T13:00:00Z", TRACK_B, "Night Drive"),
            play("2026-10-26T13:00:00Z", TRACK_B, "Night Drive"),
        ])
        daily = music_analytics.summary(self.conn, "daily", "2026-10-27", "UTC")
        self.assertEqual(daily["events"], 2)
        self.assertEqual(daily["unique_artists"], 2)
        self.assertEqual(daily["duration_unknown_events"], 2)
        self.assertEqual(daily["top"]["artists"][0]["plays"], 2)
        week = music_analytics.summary(self.conn, "weekly", "2026-10-27", "UTC")
        self.assertEqual(week["events"], 3)
        page = music_analytics.rankings(self.conn, "daily", "2026-10-27", "UTC", "tracks", limit=1)
        self.assertEqual(page["total"], 2)
        self.assertEqual(len(page["items"]), 1)
        second = music_analytics.rankings(self.conn, "daily", "2026-10-27", "UTC", "tracks", limit=1, offset=1)
        self.assertEqual(second["items"][0]["rank"], 2)
        match = music_analytics.rankings(self.conn, "daily", "2026-10-27", "UTC", "tracks", search="drive")
        self.assertEqual(match["total"], 1)
        recent = music_analytics.history(self.conn, "daily", "2026-10-27", "UTC", limit=1)
        self.assertEqual(recent["total"], 2)
        self.assertEqual(len(recent["items"]), 1)
        detail = music_analytics.detail(self.conn, "daily", "2026-10-27", "UTC", "artists", "spotify:" + ARTIST_A)
        self.assertEqual(detail["item"]["plays"], 2)
        self.assertEqual(detail["lifetime"]["plays"], 3)
        self.assertEqual(len(detail["songs"]), 2)

    def test_observed_estimate_never_becomes_verified_time(self):
        music_history.insert_records(self.conn, [play("2026-10-27T12:00:00Z")])
        first = {"track_id": TRACK_A, "state_timestamp_ms": 1000, "progress_ms": 1000,
                 "duration_ms": 180000, "playing": True}
        next_sample = dict(first, progress_ms=61000)
        music_history.record_playback_observation(self.conn, first, datetime(2026, 10, 27, 12, 1, tzinfo=timezone.utc))
        music_history.record_playback_observation(self.conn, next_sample, datetime(2026, 10, 27, 12, 2, tzinfo=timezone.utc))
        report = music_analytics.summary(self.conn, "daily", "2026-10-27", "UTC")
        self.assertEqual(report["verified_ms"], 0)
        self.assertEqual(report["estimated_ms"], 60000)
        self.assertEqual(sum(row["listening_ms"] for row in report["chart"]), 60000)
        self.assertEqual(next(row for row in report["chart"] if row["label"] == "12:00")["listening_ms"], 60000)
        self.assertEqual(music_analytics.rankings(self.conn, "daily", "2026-10-27", "UTC", "tracks", "estimated")["items"][0]["estimated_ms"], 60000)

    def test_chart_splits_estimated_minutes_at_period_boundary(self):
        music_history.insert_records(self.conn, [play("2026-10-27T00:01:00Z")])
        self.conn.execute("""INSERT INTO music_observed_intervals(track_id,start_at,end_at,estimated_ms)
            VALUES(?,?,?,?)""", (TRACK_A, "2026-10-26T23:59:00+00:00",
                              "2026-10-27T00:01:00+00:00", 120000))
        self.conn.commit()
        today = music_analytics.summary(self.conn, "daily", "2026-10-27", "UTC")
        self.assertEqual(today["estimated_ms"], 60000)
        self.assertEqual(sum(row["listening_ms"] for row in today["chart"]), 60000)
        self.assertEqual(today["chart"][0]["listening_ms"], 60000)

    def test_custom_range_reuses_real_listening_rankings(self):
        music_history.insert_records(self.conn, [
            play("2026-10-25T12:00:00Z"),
            play("2026-10-26T12:00:00Z"),
            play("2026-10-27T12:00:00Z"),
        ])
        result = music_analytics.range_rankings(self.conn, "2026-10-26", "2026-10-27", "UTC")
        self.assertEqual(result["events"], 2)
        self.assertEqual(result["items"][0]["plays"], 2)
        self.assertEqual(result["duration_unknown_events"], 2)
        with self.assertRaises(ValueError):
            music_analytics.range_rankings(self.conn, "2026-10-28", "2026-10-27", "UTC")

    def test_recap_uses_only_unambiguous_matching_spotify_art(self):
        music_history.insert_records(self.conn, [
            play("2026-10-20T12:00:00Z"),
            {"ts": "2026-10-22T12:00:00Z", "ms_played": 120000,
             "master_metadata_track_name": "Blue Hour",
             "master_metadata_album_artist_name": "Aster",
             "master_metadata_album_album_name": "Night"},
        ])
        self.conn.execute("UPDATE music_artists SET image_url=? WHERE spotify_id=?",
                          ("https://i.scdn.co/image/portrait", ARTIST_A))
        report = music_analytics.recap_art(self.conn, music_analytics.summary(self.conn, "monthly", "2026-10-22"))
        name_only_track = next(row for row in report["top"]["tracks"] if not row["spotify_url"])
        merged_artist = next(row for row in report["top"]["artists"] if row["spotify_url"])
        self.assertEqual(name_only_track["image_url"], "https://i.scdn.co/image/test")
        self.assertEqual(merged_artist["image_url"], "https://i.scdn.co/image/portrait")
        self.assertEqual(merged_artist["plays"], 2)
        self.assertEqual(report["unique_artists"], 1)
        self.assertEqual(report["events"], 2)
        self.assertEqual(sum(row["plays"] for row in report["top"]["tracks"]), 2)

        music_history.insert_records(self.conn, [play("2026-10-24T12:00:00Z", TRACK_B,
                                                     artists=[{"id": ARTIST_B, "name": "Aster"}])])
        ambiguous = music_analytics.recap_art(self.conn, music_analytics.summary(self.conn, "monthly", "2026-10-22"))
        name_only_track = next(row for row in ambiguous["top"]["tracks"] if not row["spotify_url"])
        name_only_artist = next(row for row in ambiguous["top"]["artists"] if not row["spotify_url"])
        self.assertIsNone(name_only_track["image_url"])
        self.assertIsNone(name_only_artist["image_url"])


if __name__ == "__main__":
    unittest.main()
