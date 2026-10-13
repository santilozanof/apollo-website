import ast
from collections import Counter
import json
import re
import subprocess
import threading
import time
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
            "get_now_playing": lambda **_kwargs: {"title": "Confirmed"},
            "apollo_spotify_invalidate_caches": lambda: None,
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
    def test_retry_after_is_respected_instead_of_capped_to_one_second(self):
        calls = []
        sleeps = []

        class RateLimit(Exception):
            http_status = 429
            headers = {"retry-after": "3"}

        def operation():
            calls.append(1)
            if len(calls) == 1:
                raise RateLimit("rate limited")
            return {"ok": True}

        original_sleep = spotify_curator_tool.time.sleep
        spotify_curator_tool.time.sleep = sleeps.append
        try:
            self.assertEqual(spotify_curator_tool.spotify_read(operation), {"ok": True})
        finally:
            spotify_curator_tool.time.sleep = original_sleep
        self.assertEqual(sleeps, [3.0])

    def test_opener_is_verified_and_playing_before_phase_one_returns(self):
        calls = []
        opener = spotify_api_track(1)

        class Spotify:
            def queue(self):
                calls.append("queue")
                return {"queue": [spotify_api_track(8)]}

            def search(self, **_kwargs):
                calls.append("search")
                return {"tracks": {"items": [opener]}}

            def devices(self):
                calls.append("devices")
                return {"devices": [{"id": "device", "is_active": True, "is_restricted": False}]}

            def start_playback(self, **_kwargs):
                calls.append("play")

            def current_playback(self):
                calls.append("confirm")
                return {"is_playing": True, "item": opener}

        result = spotify_curator_tool.start_curated_playback(Spotify(), {
            "candidates": [
                {"title": "Track 1", "artist": "Artist"},
                {"title": "Track 2", "artist": "Artist"},
            ],
        })
        self.assertTrue(result["playback_started"])
        self.assertEqual(result["opener"]["id"], opener["id"])
        self.assertEqual(calls, ["queue", "search", "devices", "play", "confirm"])

    def test_background_builder_preserves_queue_and_adds_progressively_in_order(self):
        calls = []
        events = []
        lookup = {f'Track {number}': spotify_api_track(number, f"Artist {number}") for number in (2, 3)}

        class Spotify:
            def devices(self):
                return {"devices": [{"id": "device", "is_active": True, "is_restricted": False}]}

            def queue(self):
                return {"queue": []}

            def search(self, q, **_kwargs):
                return {"tracks": {"items": [item for title, item in lookup.items() if title in q]}}

            def add_to_queue(self, uri, device_id=None):
                calls.append(uri)

        existing = [track(8)["uri"], track(9)["uri"]]
        built = spotify_curator_tool.build_curated_queue(Spotify(), {
            "existing_queue_uris": existing,
            "opener_id": track(1)["id"],
            "maximum": 2,
            "candidates": [
                {"title": "Track 2", "artist": "Artist 2"},
                {"title": "Track 3", "artist": "Artist 3"},
            ],
        }, emit=events.append)
        self.assertEqual(calls, existing + [track(2)["uri"], track(3)["uri"]])
        self.assertEqual([item["id"] for item in built], [track(2)["id"], track(3)["id"]])
        self.assertEqual([event["event"] for event in events], [
            "preserved", "preserved", "added", "added", "complete",
        ])

    def test_queue_restore_does_not_duplicate_tracks_already_present(self):
        existing = [track(8)["uri"], track(9)["uri"]]
        added = []

        class Spotify:
            def devices(self):
                return {"devices": [{"id": "device", "is_active": True, "is_restricted": False}]}

            def queue(self):
                return {"queue": [spotify_api_track(8), spotify_api_track(9)]}

            def add_to_queue(self, uri, device_id=None):
                added.append(uri)

        result = spotify_curator_tool.restore_existing_queue(Spotify(), existing)
        self.assertEqual(result["preserved"], 2)
        self.assertEqual(added, [])

    def test_ambiguous_add_timeout_checks_queue_before_retrying(self):
        uri = track(4)["uri"]
        calls = []

        class Spotify:
            def add_to_queue(self, value, device_id=None):
                calls.append(value)
                raise TimeoutError("timed out after Spotify accepted it")

            def queue(self):
                return {"queue": [spotify_api_track(4)]}

        counts = Counter()
        spotify_curator_tool.add_to_queue_safely(Spotify(), uri, "device", counts)
        self.assertEqual(calls, [uri])
        self.assertEqual(counts[uri], 1)

    def test_partial_queue_failure_keeps_confirmed_progress_for_recovery(self):
        events = []
        added = []

        class Spotify:
            def devices(self):
                return {"devices": [{"id": "device", "is_active": True, "is_restricted": False}]}

            def queue(self):
                return {"queue": []}

            def search(self, q, **_kwargs):
                if "Track 2" in q:
                    return {"tracks": {"items": [spotify_api_track(2, "Artist 2")]}}
                raise RuntimeError("permanent search failure")

            def add_to_queue(self, uri, device_id=None):
                added.append(uri)

        with self.assertRaisesRegex(RuntimeError, "permanent"):
            spotify_curator_tool.build_curated_queue(Spotify(), {
                "opener_id": track(1)["id"],
                "maximum": 2,
                "candidates": [
                    {"title": "Track 2", "artist": "Artist 2"},
                    {"title": "Track 3", "artist": "Artist 3"},
                ],
            }, emit=events.append)
        self.assertEqual(added, [track(2)["uri"]])
        self.assertEqual(events[-1]["event"], "added")
        self.assertEqual(events[-1]["added"], 1)

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
        self.assertIn('window.apolloSpotifyRequest(\n                `/api/spotify/queue', source)
        self.assertIn("loadQueue(true)", source)

    def test_added_tracks_are_refreshed_from_spotify_not_injected(self):
        source = (SERVER.parent / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("queueData.queue.push(item)", source)
        self.assertIn("await loadQueue(true);", source)

    def test_drawer_reuses_apollo_motion_and_resizes_the_player_grid(self):
        source = (SERVER.parent / "index.html").read_text(encoding="utf-8")
        self.assertIn("transition: opacity 220ms ease, transform 320ms var(--ease);", source)
        self.assertIn(".apollo-music-stage {", source)
        self.assertIn("grid-template-columns:minmax(0,1fr) clamp(278px,25vw,318px); gap:16px;", source)
        self.assertIn('musicStage.append(musicPlayer, musicQueuePanel);', source)
        self.assertNotIn("const bounds = nowPlaying.getBoundingClientRect();", source)
        self.assertIn("padding-bottom:calc(12px + var(--apollo-mobile-nav-h, 64px)", source)
        self.assertIn("@media (prefers-reduced-motion: reduce)", source)

    def test_spotify_loaders_have_timeouts_terminal_errors_and_recovery(self):
        source = (SERVER.parent / "index.html").read_text(encoding="utf-8")
        self.assertIn("const controller = new AbortController();", source)
        self.assertIn("Spotify took too long to respond.", source)
        self.assertIn('id="apolloNowRetry"', source)
        self.assertIn("data-retry-recent", source)
        self.assertIn("queueRefreshError", source)

    def test_existing_music_prompt_is_docked_without_duplication(self):
        source = (SERVER.parent / "index.html").read_text(encoding="utf-8")
        self.assertEqual(source.count('id="apolloPresence"'), 1)
        self.assertIn('id="apolloQueuePrompt"', source)
        self.assertIn('presence.classList.add("apollo-presence-queue")', source)
        self.assertIn("queuePrompt.appendChild(presence);", source)
        self.assertIn("restoreMusicPrompt();", source)

    def test_progressive_worker_status_uses_existing_drawer(self):
        source = (SERVER.parent / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="apolloQueueBuildStatus"', source)
        self.assertIn('fetch("/api/spotify/curation-job"', source)
        self.assertIn("Building your queue…", source)
        self.assertIn("window.setInterval(pollQueueJob, 1200)", source)


class TwoPhaseCuratorTests(unittest.TestCase):
    def test_background_worker_restores_existing_queue_before_full_planning(self):
        source = SERVER.read_text(encoding="utf-8")
        start = source.index("def apollo_music_queue_worker")
        end = source.index("def apollo_music_start_queue_job", start)
        worker = source[start:end]
        self.assertLess(worker.index('"restore-queue"'), worker.index("apollo_music_plan_background_queue"))

    def test_first_track_returns_before_slow_background_queue(self):
        events = []
        background_done = threading.Event()
        full_finished = []
        opener = track(1, "Opening Artist")

        class Runner:
            TimeoutExpired = subprocess.TimeoutExpired

            @staticmethod
            def run(args, **_kwargs):
                self.assertEqual(args[2], "start-curation")
                time.sleep(.025)
                events.append("playback_confirmed")
                return type("Result", (), {
                    "returncode": 0,
                    "stdout": json.dumps({
                        "ok": True,
                        "opener": opener,
                        "playback_started": True,
                        "existing_queue_uris": [track(8)["uri"]],
                        "existing_queue_count": 1,
                    }),
                    "stderr": "",
                })()

        def start_job(payload, *_args):
            events.append("background_started")

            def finish():
                time.sleep(.16)
                full_finished.append(time.monotonic())
                background_done.set()

            threading.Thread(target=finish, daemon=True).start()
            return {"id": "job", "status": "queued", "target": 9}

        failure = load_function("apollo_music_curator_failure", {"json": json})
        curate = load_function("apollo_music_curate", {
            "json": json,
            "time": time,
            "ask_hermes": lambda _messages, **_kwargs: json.dumps({
                "summary": "coffeehouse melancholy",
                "why": "A precise opener",
                "opener_candidates": [
                    {"title": "Track 1", "artist": "Opening Artist", "reason": "fit"},
                    {"title": "Track 2", "artist": "Fallback", "reason": "fallback"},
                ],
            }),
            "apollo_music_json": json.loads,
            "get_now_playing": lambda: {"track_id": "current"},
            "subprocess": Runner,
            "SPOTIFY_PYTHON": "python",
            "SPOTIFY_CURATOR_TOOL": "tool",
            "music_curator": music_curator,
            "SPOTIFY_CURATOR_START_LOCK": threading.Lock(),
            "apollo_music_cancel_active_job": lambda: None,
            "apollo_music_curator_failure": failure,
            "apollo_music_save_curator_context": lambda *_args: None,
            "apollo_spotify_invalidate_caches": lambda: None,
            "apollo_music_start_queue_job": start_job,
        })
        started = time.monotonic()
        result = curate("black coffee and cigarettes", chat_id=7)
        returned = time.monotonic()
        self.assertEqual(events, ["playback_confirmed", "background_started"])
        self.assertTrue(result["spotify"]["queue_building"])
        self.assertEqual(result["curation"]["tracks"][0]["id"], opener["id"])
        self.assertFalse(background_done.is_set())
        self.assertTrue(background_done.wait(1))
        self.assertLess(returned - started, full_finished[0] - started)

    def test_new_curator_request_terminates_the_prior_background_worker(self):
        terminated = []
        updates = []

        class Process:
            def poll(self):
                return None

            def terminate(self):
                terminated.append(True)

        jobs = {"old": {"status": "building", "process": Process()}}
        cancel = load_function("apollo_music_cancel_active_job", {
            "SPOTIFY_CURATOR_JOB_LOCK": threading.RLock(),
            "SPOTIFY_CURATOR_ACTIVE_JOB_ID": "old",
            "SPOTIFY_CURATOR_JOBS": jobs,
            "apollo_music_update_job": lambda job_id, **values: updates.append((job_id, values)),
        })
        cancel()
        self.assertTrue(jobs["old"]["cancelled"])
        self.assertEqual(terminated, [True])
        self.assertEqual(updates[-1][1]["status"], "superseded")


class CuratorFailureTests(unittest.TestCase):
    def function(self, result):
        failure = load_function("apollo_music_curator_failure", {"json": json})
        return load_function("apollo_music_curate", {
            "json": json,
            "datetime": datetime,
            "timezone": timezone,
            "time": time,
            "ask_hermes": lambda _messages, **_kwargs: json.dumps({
                "summary": "dark and textural", "why": "A precise opener",
                "opener_candidates": [{"title": f"Song {i}", "artist": f"Artist {i}", "reason": "fit"} for i in range(3)],
            }),
            "apollo_music_json": json.loads,
            "get_now_playing": lambda: {"track_id": "current"},
            "subprocess": type("Subprocess", (), {"run": staticmethod(lambda *args, **kwargs: result)}),
            "SPOTIFY_PYTHON": "python", "SPOTIFY_CURATOR_TOOL": "tool",
            "music_curator": music_curator,
            "apollo_music_save_curator_context": lambda *_args: None,
            "SPOTIFY_CURATOR_START_LOCK": threading.Lock(),
            "apollo_music_cancel_active_job": lambda: None,
            "apollo_music_curator_failure": failure,
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
