import ast
import json
import re
import subprocess
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


def spotify_api_track(number, artist="Artist"):
    value = track(number, artist)
    return {
        "id": value["id"], "uri": value["uri"], "type": "track",
        "name": value["title"], "artists": [{"name": artist}],
        "album": {"name": "Album", "images": []},
        "external_urls": {"spotify": value["spotify_url"]},
    }


class MusicIntentTests(unittest.TestCase):
    def test_direct_artist_is_distinct_from_artist_style(self):
        self.assertFalse(music_curator.wants_music_curation("Play Jeff Buckley", {"mode": "direct", "type": "artist"}))
        self.assertTrue(music_curator.wants_music_curation("Jeff Buckley type shit", {"type": "artist"}))
        self.assertTrue(music_curator.wants_music_curation("Jeff Buckley-style songs", {"mode": "direct", "type": "artist"}))

    def test_mood_and_production_prompts_are_curated(self):
        self.assertTrue(music_curator.wants_music_curation("Dark Portishead-style beats with samples and DJ scratches"))
        self.assertTrue(music_curator.wants_music_curation("Something that sounds like a rainy night in London"))
        self.assertTrue(music_curator.wants_music_curation(
            "Play some Jeff Buckley type shit, black coffee and cigarettes"
        ))
        self.assertTrue(music_curator.wants_music_curation(
            "Play dark Portishead-style trip-hop"
        ))

    def test_followup_refinements_require_and_use_context(self):
        self.assertTrue(music_curator.wants_music_curation("more atmospheric", has_context=True))
        self.assertTrue(music_curator.wants_music_curation("more like the third song", has_context=True))
        self.assertFalse(music_curator.wants_music_curation("more", has_context=False))

    def test_playlist_lookup_is_gated_to_playlist_requests(self):
        alias_candidate = load_function("apollo_music_alias_candidate", {})
        lookup = load_function("apollo_music_playlist_lookup_requested", {
            "re": re,
            "apollo_music_alias_candidate": alias_candidate,
        })
        self.assertFalse(lookup(
            "Play some Jeff Buckley type shit, black coffee and cigarettes"
        ))
        self.assertFalse(lookup("Play dark Portishead-style trip-hop"))
        self.assertTrue(lookup("Play my Night Bus playlist"))
        self.assertFalse(lookup("Play Grace by Jeff Buckley"))

    def test_playlist_lookup_timeout_is_bounded_and_recovers_cleanly(self):
        calls = []

        class Runner:
            TimeoutExpired = subprocess.TimeoutExpired

            @staticmethod
            def run(*_args, **kwargs):
                calls.append(kwargs["timeout"])
                raise subprocess.TimeoutExpired("list-playlists", kwargs["timeout"])

        playlists = load_function("apollo_spotify_personal_playlists", {
            "subprocess": Runner,
            "SPOTIFY_PYTHON": "python",
            "SPOTIFY_TOOL": "spotify_tool.py",
            "time": type("Clock", (), {"sleep": staticmethod(lambda _delay: None)}),
            "json": json,
        })
        self.assertEqual(playlists(), [])
        self.assertEqual(calls, [8, 8])

    def test_descriptive_prompt_overrides_a_legacy_direct_intent(self):
        called = []
        play = load_function("apollo_music_play_request", {
            "json": json,
            "ask_hermes": lambda _messages: json.dumps({
                "mode": "direct", "type": "artist", "query": "Jeff Buckley",
                "title": "", "artist": "Jeff Buckley",
            }),
            "apollo_music_curator_context": lambda _chat_id: {},
            "music_curator": music_curator,
            "apollo_music_curate": lambda request, **kwargs: called.append(request) or {"ok": True},
        })
        request = "Play some Jeff Buckley type shit, black coffee and cigarettes"
        self.assertTrue(play(request, chat_id=7)["ok"])
        self.assertEqual(called, [request])

    def test_direct_playlist_and_specific_track_commands_stay_direct(self):
        intents = iter([
            {"mode": "direct", "type": "playlist", "query": "Night Bus", "title": "", "artist": ""},
            {"mode": "direct", "type": "track", "query": "Grace Jeff Buckley", "title": "Grace", "artist": "Jeff Buckley"},
        ])
        payloads = []

        class Runner:
            TimeoutExpired = subprocess.TimeoutExpired

            @staticmethod
            def run(args, **_kwargs):
                payloads.append(json.loads(args[-1]))
                return type("Result", (), {
                    "returncode": 0,
                    "stdout": json.dumps({"ok": True, "type": payloads[-1]["type"]}),
                    "stderr": "",
                })()

        play = load_function("apollo_music_play_request", {
            "json": json,
            "ask_hermes": lambda _messages: json.dumps(next(intents)),
            "apollo_music_curator_context": lambda _chat_id: {},
            "music_curator": music_curator,
            "apollo_music_curate": lambda *_args, **_kwargs: self.fail("curator should not run"),
            "subprocess": Runner,
            "SPOTIFY_PYTHON": "python",
            "SPOTIFY_TOOL": "spotify_tool.py",
            "get_now_playing": lambda: {"title": "Confirmed"},
        })
        play("Play my Night Bus playlist")
        play("Play Grace by Jeff Buckley")
        self.assertEqual([item["type"] for item in payloads], ["playlist", "track"])
        self.assertEqual(payloads[0]["query"], "Night Bus")
        self.assertEqual(payloads[1]["title"], "Grace")


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
    def test_retry_excludes_tracks_already_present_in_spotify_queue(self):
        queued = spotify_api_track(2)
        fresh = spotify_api_track(3)

        class Spotify:
            def queue(self):
                return {"queue": [queued]}

            def search(self, q, **_kwargs):
                item = queued if "Track 2" in q else fresh
                return {"tracks": {"items": [item]}}

        original_client = spotify_curator_tool.spotify_client
        spotify_curator_tool.spotify_client = lambda: Spotify()
        try:
            result = spotify_curator_tool.run({
                "candidates": [
                    {"title": "Track 2", "artist": "Artist"},
                    {"title": "Track 3", "artist": "Artist"},
                ],
                "minimum": 1,
                "maximum": 10,
            })
        finally:
            spotify_curator_tool.spotify_client = original_client
        self.assertEqual([item["id"] for item in result["tracks"]], [fresh["id"]])

    def test_temporary_reads_retry_with_a_strict_bound(self):
        calls = []

        class TemporaryError(Exception):
            http_status = 503
            headers = {}

        def operation():
            calls.append(1)
            if len(calls) < 3:
                raise TemporaryError("temporarily unavailable")
            return {"ok": True}

        original_sleep = spotify_curator_tool.time.sleep
        spotify_curator_tool.time.sleep = lambda _delay: None
        try:
            self.assertEqual(
                spotify_curator_tool.spotify_read(operation),
                {"ok": True},
            )
        finally:
            spotify_curator_tool.time.sleep = original_sleep
        self.assertEqual(len(calls), 3)

    def test_spotify_queue_snapshot_preserves_returned_order(self):
        first = {
            "id": "first", "uri": "spotify:track:first", "type": "track",
            "name": "First", "artists": [{"name": "One"}],
            "album": {"images": [], "uri": "spotify:album:one"},
        }
        second = {
            "id": "second", "uri": "spotify:track:second", "type": "track",
            "name": "Second", "artists": [{"name": "Two"}],
            "album": {"images": [], "uri": "spotify:album:two"},
        }
        snapshot = spotify_curator_tool.queue_snapshot({
            "currently_playing": first,
            "queue": [second, first],
        })
        self.assertEqual(snapshot["current"]["name"], "First")
        self.assertEqual(
            [item["uri"] for item in snapshot["queue"]],
            ["spotify:track:second", "spotify:track:first"],
        )

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

    def test_existing_queue_is_restored_before_curated_followups(self):
        calls = []

        class Spotify:
            def start_playback(self, **kwargs):
                calls.append(("play", kwargs["uris"][0]))

            def add_to_queue(self, uri, device_id=None):
                calls.append(("queue", uri))

        tracks = [track(1), track(2), track(3)]
        existing = [track(8)["uri"], track(9)["uri"]]
        spotify_curator_tool.play_resolved_queue(
            Spotify(), tracks,
            [{"id": "device", "is_active": True, "is_restricted": False}],
            existing_queue_uris=existing,
        )
        self.assertEqual(calls, [
            ("play", tracks[0]["uri"]),
            ("queue", existing[0]),
            ("queue", existing[1]),
            ("queue", tracks[1]["uri"]),
            ("queue", tracks[2]["uri"]),
        ])

    def test_missing_device_fails_before_playback(self):
        with self.assertRaisesRegex(RuntimeError, "No active"):
            spotify_curator_tool.play_resolved_queue(object(), [track(1)], [])

    def test_playback_mutations_are_not_retried_after_an_ambiguous_timeout(self):
        calls = []

        class Spotify:
            def start_playback(self, **_kwargs):
                calls.append("play")

            def add_to_queue(self, _uri, device_id=None):
                calls.append("queue")
                raise TimeoutError("timed out")

        with self.assertRaises(TimeoutError):
            spotify_curator_tool.play_resolved_queue(
                Spotify(), [track(1), track(2)],
                [{"id": "device", "is_active": True, "is_restricted": False}],
            )
        self.assertEqual(calls, ["play", "queue"])


class MusicQueueFrontendTests(unittest.TestCase):
    def test_curated_card_is_removed_and_spotify_drawer_is_used(self):
        source = (SERVER.parent / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("apolloCurationCard", source)
        self.assertNotIn("Apollo Queue", source)
        self.assertIn('id="apolloQueuePanel"', source)
        self.assertIn('fetch(\n                `/api/spotify/queue', source)
        self.assertIn("loadQueue(true)", source)

    def test_added_tracks_are_refreshed_from_spotify_not_injected(self):
        source = (SERVER.parent / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("queueData.queue.push(item)", source)
        self.assertIn("await loadQueue(true);", source)

    def test_drawer_reuses_apollo_motion_and_now_playing_bounds(self):
        source = (SERVER.parent / "index.html").read_text(encoding="utf-8")
        self.assertIn("transition: opacity 220ms ease, transform 320ms var(--ease);", source)
        self.assertIn("const bounds = nowPlaying.getBoundingClientRect();", source)
        self.assertIn('--apollo-queue-top", `${Math.max(12, bounds.top)}px`', source)
        self.assertIn('--apollo-queue-bottom", `${Math.max(12, window.innerHeight - bounds.bottom)}px`', source)

    def test_existing_music_prompt_is_docked_without_duplication(self):
        source = (SERVER.parent / "index.html").read_text(encoding="utf-8")
        self.assertEqual(source.count('id="apolloPresence"'), 1)
        self.assertIn('id="apolloQueuePrompt"', source)
        self.assertIn('presence.classList.add("apollo-presence-queue")', source)
        self.assertIn("queuePrompt.appendChild(presence);", source)
        self.assertIn("restoreMusicPrompt();", source)


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

    def test_user_error_hides_internal_command_and_path(self):
        safe = load_function("apollo_music_user_error", {})
        raw = subprocess.TimeoutExpired(
            ["/usr/local/lib/hermes-agent/venv/bin/python", "/root/spotify_tool.py"],
            20,
        )
        message = safe(raw)
        self.assertEqual(
            message,
            "Spotify is temporarily unavailable. Please try again in a moment.",
        )
        self.assertNotIn("/root/", message)


if __name__ == "__main__":
    unittest.main()
