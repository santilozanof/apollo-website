import ast
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

import music_curator
import spotify_curator_tool


SERVER = Path(__file__).resolve().parents[1] / "server.py"


def load_function(name, namespace):
    tree = ast.parse(SERVER.read_text())
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SERVER), "exec"), namespace)
    return namespace[name]


def track(number, artist="Artist"):
    track_id = str(number).zfill(22)
    return {
        "id": track_id,
        "uri": "spotify:track:" + track_id,
        "title": f"Track {number}",
        "artists": [artist],
        "spotify_url": "https://open.spotify.com/track/" + track_id,
    }


class MusicIntentTests(unittest.TestCase):
    def test_direct_artist_is_distinct_from_artist_style(self):
        self.assertFalse(music_curator.wants_music_curation("Play Jeff Buckley", {"mode": "direct", "type": "artist"}))
        self.assertTrue(music_curator.wants_music_curation("Jeff Buckley type shit", {"type": "artist"}))
        self.assertTrue(music_curator.wants_music_curation("Jeff Buckley-style songs", {"mode": "direct", "type": "artist"}))

    def test_mood_and_production_prompts_are_curated(self):
        self.assertTrue(music_curator.wants_music_curation("Dark Portishead-style beats with samples and DJ scratches"))
        self.assertTrue(music_curator.wants_music_curation("Something that sounds like a rainy night in London"))

    def test_followup_refinements_require_and_use_context(self):
        self.assertTrue(music_curator.wants_music_curation("more atmospheric", has_context=True))
        self.assertTrue(music_curator.wants_music_curation("more like the third song", has_context=True))
        self.assertFalse(music_curator.wants_music_curation("more", has_context=False))


class TrackValidationTests(unittest.TestCase):
    def test_uri_validation_and_duplicate_suppression(self):
        first = track(1)
        values = [first, first, {**track(2), "uri": "spotify:album:not-a-track"}, track(3)]
        result = music_curator.normalize_curated_tracks(values, excluded_ids=[track(3)["id"]])
        self.assertEqual([item["id"] for item in result], [first["id"]])
        self.assertIsNone(music_curator.spotify_track_id("spotify:track:invented"))

    def test_excessive_artist_repetition_is_removed(self):
        result = music_curator.normalize_curated_tracks([track(1, "A"), track(2, "A"), track(3, "A"), track(4, "B")])
        self.assertEqual([item["title"] for item in result], ["Track 1", "Track 2", "Track 4"])


class QueueExecutionTests(unittest.TestCase):
    def test_opener_and_queue_order_are_preserved(self):
        calls = []

        class Spotify:
            def start_playback(self, **kwargs):
                calls.append(("play", kwargs["uris"][0]))

            def add_to_queue(self, uri, device_id=None):
                calls.append(("queue", uri))

        tracks = [track(1), track(2), track(3)]
        count = spotify_curator_tool.play_resolved_queue(
            Spotify(), tracks, [{"id": "device", "is_active": True, "is_restricted": False}]
        )
        self.assertEqual(count, 2)
        self.assertEqual(calls, [("play", tracks[0]["uri"]), ("queue", tracks[1]["uri"]), ("queue", tracks[2]["uri"])])

    def test_missing_device_fails_before_playback(self):
        with self.assertRaisesRegex(RuntimeError, "No active"):
            spotify_curator_tool.play_resolved_queue(object(), [track(1)], [])


class CuratorFailureTests(unittest.TestCase):
    def function(self, result):
        return load_function("apollo_music_curate", {
            "json": json,
            "datetime": datetime,
            "timezone": timezone,
            "ask_hermes": lambda _messages: json.dumps({
                "summary": "dark and textural", "why": "A precise opener",
                "candidates": [{"title": f"Song {i}", "artist": f"Artist {i}", "reason": "fit"} for i in range(10)],
            }),
            "apollo_music_json": json.loads,
            "get_now_playing": lambda: {"track_id": "current"},
            "subprocess": type("Subprocess", (), {"run": staticmethod(lambda *args, **kwargs: result)}),
            "SPOTIFY_PYTHON": "python", "SPOTIFY_CURATOR_TOOL": "tool",
            "music_curator": music_curator,
            "apollo_music_save_curator_context": lambda *_args: None,
        })

    def test_rate_limit_is_reported_accurately(self):
        result = type("Result", (), {
            "returncode": 2, "stdout": "",
            "stderr": json.dumps({"error": "rate", "status": 429, "retry_after": "7"}),
        })()
        with self.assertRaisesRegex(RuntimeError, "rate-limited.*7 seconds"):
            self.function(result)("keep this vibe going", 1, {})

    def test_api_and_device_failure_is_not_reported_as_success(self):
        result = type("Result", (), {
            "returncode": 2, "stdout": "",
            "stderr": json.dumps({"error": "No active, controllable Spotify device is available"}),
        })()
        with self.assertRaisesRegex(RuntimeError, "No active"):
            self.function(result)("late-night underground R&B", 1, {})


if __name__ == "__main__":
    unittest.main()
