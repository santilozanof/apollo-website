import ast
import json
import subprocess
import threading
import time
import unittest
from pathlib import Path

import spotify_curator_tool


SERVER = Path(__file__).resolve().parents[1] / "server.py"


def load_function(name, namespace):
    tree = ast.parse(SERVER.read_text())
    node = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == name
    )
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SERVER), "exec"), namespace)
    return namespace[name]


class SpotifyPlaybackStateTests(unittest.TestCase):
    def state(self):
        return load_function("spotify_playback_state", {"json": json})

    def test_current_track_is_playing(self):
        response = self.state()({"playing": True, "title": "Song", "artists": "Artist"})
        self.assertEqual(response["playback_state"], "playing")
        self.assertEqual(response["connection_state"], "connected")

    def test_current_track_paused_is_not_reported_as_nothing_playing(self):
        response = self.state()({"is_playing": False, "item": {"name": "Song", "artists": [{"name": "Artist"}]}})
        self.assertEqual(response["title"], "Song")
        self.assertEqual(response["artists"], "Artist")
        self.assertEqual(response["playback_state"], "paused")

    def test_empty_currently_playing_response_is_idle(self):
        response = self.state()({})
        self.assertEqual(response["playback_state"], "idle")
        self.assertEqual(response["connection_state"], "connected")

    def test_invalid_refresh_token_requires_reconnect(self):
        response = self.state()(error="Spotify token refresh failed: invalid_grant")
        self.assertEqual(response["playback_state"], "disconnected")
        self.assertEqual(response["connection_state"], "disconnected")

    def test_other_spotify_request_failure_is_not_an_idle_state(self):
        response = self.state()(error="Spotify request failed: 503")
        self.assertEqual(response["playback_state"], "error")
        self.assertEqual(response["connection_state"], "error")

    def test_current_command_uses_the_bounded_shared_adapter(self):
        calls = []
        current = load_function("_get_now_playing_uncached", {
            "apollo_spotify_tool_command": lambda command, timeout: (
                calls.append((command, timeout)) or {
                    "playing": False,
                    "title": "Song",
                    "playback_state": "paused",
                }
            ),
        })

        response = current()
        self.assertEqual(calls, [("playback-state", 10)])
        self.assertEqual(response["playback_state"], "paused")

    def test_player_endpoint_overrides_an_empty_currently_playing_result(self):
        player = load_function("spotify_player_result", {})
        state = self.state()
        response = state(player({
            "player": {
                "status": 200,
                "is_playing": True,
                "progress_ms": 45678,
                "sampled_at_ms": 1234567890,
                "device": {"name": "Kitchen", "type": "Speaker", "key": "device-key"},
                "item": {
                    "id": "track", "name": "Live track", "duration_ms": 123,
                    "artists": [{"name": "Artist"}],
                    "album": {"name": "Album", "images": [{"url": "art"}]},
                },
            },
        }))
        self.assertEqual(response["title"], "Live track")
        self.assertTrue(response["playing"])
        self.assertEqual(response["playback_state"], "playing")
        self.assertEqual(response["progress_ms"], 45678)
        self.assertEqual(response["sampled_at_ms"], 1234567890)
        self.assertEqual(response["device_key"], "device-key")

    def test_concurrent_polling_uses_one_spotify_refresh(self):
        calls = []
        cache = {"value": None, "at": 0.0}

        def refresh():
            calls.append(1)
            time.sleep(.03)
            return {"title": "One read"}

        def refresh_cache(release_lock=False):
            value = refresh()
            with cache_lock:
                cache.update(value=value, at=time.monotonic())
            if release_lock:
                refresh_lock.release()
            return value

        cache_lock = threading.Lock()
        refresh_lock = threading.Lock()

        current = load_function("get_now_playing", {
            "time": time,
            "threading": threading,
            "SPOTIFY_PLAYBACK_CACHE": cache,
            "SPOTIFY_PLAYBACK_CACHE_LOCK": cache_lock,
            "SPOTIFY_PLAYBACK_REFRESH_LOCK": refresh_lock,
            "_get_now_playing_uncached": refresh,
            "_refresh_now_playing_cache": refresh_cache,
        })
        results = []
        threads = [threading.Thread(target=lambda: results.append(current())) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(calls), 1)
        self.assertEqual([item["title"] for item in results], ["One read"] * 4)

    def test_rate_limit_starts_shared_cooldown_and_prevents_repeat_call(self):
        calls = []
        cooldown = {"remaining": 0.0}

        class Runner:
            TimeoutExpired = subprocess.TimeoutExpired

            @staticmethod
            def run(*_args, **_kwargs):
                calls.append(1)
                return type("Result", (), {
                    "returncode": 1,
                    "stdout": "",
                    "stderr": json.dumps({"status": 429, "retry_after": "7"}),
                })()

        def set_cooldown(value):
            cooldown["remaining"] = float(value)
            return float(value)

        command = load_function("apollo_spotify_tool_command", {
            "json": json,
            "subprocess": Runner,
            "SPOTIFY_PYTHON": "python",
            "SPOTIFY_CURATOR_TOOL": Path("spotify_curator_tool.py"),
            "apollo_spotify_rate_limit_remaining": lambda: cooldown["remaining"],
            "apollo_spotify_set_rate_limit": set_cooldown,
        })
        with self.assertRaisesRegex(RuntimeError, "Retry in 7 seconds"):
            command("queue")
        with self.assertRaisesRegex(RuntimeError, "Retry in 7 seconds"):
            command("queue")
        self.assertEqual(calls, [1])

    def test_supported_controls_target_the_active_device_and_return_state(self):
        calls = []

        class Spotify:
            def current_playback(self):
                return {
                    "is_playing": True,
                    "progress_ms": 1000,
                    "device": {"id": "active", "name": "Mac", "is_active": True},
                    "item": {
                        "id": "track", "uri": "spotify:track:track", "name": "Song",
                        "duration_ms": 120000, "artists": [{"name": "Artist"}],
                        "album": {"name": "Album", "images": []},
                    },
                }

            def pause_playback(self, device_id=None):
                calls.append(("pause", device_id))

            def start_playback(self, device_id=None):
                calls.append(("play", device_id))

            def next_track(self, device_id=None):
                calls.append(("next", device_id))

            def previous_track(self, device_id=None):
                calls.append(("previous", device_id))

            def seek_track(self, position_ms, device_id=None):
                calls.append(("seek", position_ms, device_id))

        spotify = Spotify()
        paused = spotify_curator_tool.playback_control(spotify, "pause")
        spotify_curator_tool.playback_control(spotify, "play")
        spotify_curator_tool.playback_control(spotify, "next")
        spotify_curator_tool.playback_control(spotify, "previous")
        sought = spotify_curator_tool.playback_control(spotify, "seek", 42000)
        self.assertEqual(calls, [
            ("pause", "active"), ("play", "active"), ("next", "active"),
            ("previous", "active"), ("seek", 42000, "active"),
        ])
        self.assertTrue(paused["ok"])
        self.assertEqual(sought["playback"]["track_id"], "track")

    def test_play_control_waits_for_spotify_readback_to_converge(self):
        reads = 0

        class Spotify:
            def current_playback(self):
                nonlocal reads
                reads += 1
                return {
                    "is_playing": reads >= 5,
                    "progress_ms": 1000,
                    "device": {"id": "active", "name": "Mac", "is_active": True},
                    "item": {
                        "id": "track", "name": "Song", "duration_ms": 120000,
                        "artists": [{"name": "Artist"}],
                        "album": {"name": "Album", "images": []},
                    },
                }

            def start_playback(self, device_id=None):
                self.device_id = device_id

        original_sleep = spotify_curator_tool.time.sleep
        spotify_curator_tool.time.sleep = lambda _delay: None
        try:
            result = spotify_curator_tool.playback_control(Spotify(), "play")
        finally:
            spotify_curator_tool.time.sleep = original_sleep

        self.assertEqual(reads, 5)
        self.assertTrue(result["playback"]["playing"])

    def test_missing_active_device_returns_actionable_error(self):
        class Runner:
            TimeoutExpired = subprocess.TimeoutExpired

            @staticmethod
            def run(*_args, **_kwargs):
                return type("Result", (), {
                    "returncode": 2,
                    "stdout": "",
                    "stderr": json.dumps({
                        "status": None,
                        "error": "No active, controllable Spotify device is available",
                    }),
                })()

        command = load_function("apollo_spotify_tool_command", {
            "json": json,
            "subprocess": Runner,
            "SPOTIFY_PYTHON": "python",
            "SPOTIFY_CURATOR_TOOL": Path("spotify_curator_tool.py"),
            "apollo_spotify_rate_limit_remaining": lambda: 0,
            "apollo_spotify_set_rate_limit": lambda value: value,
        })
        with self.assertRaisesRegex(RuntimeError, "Open Spotify on an active device"):
            command("playback-control", "{}")

    def test_control_requires_an_active_controllable_device(self):
        class Spotify:
            def current_playback(self):
                return {}

            def devices(self):
                return {"devices": [{"id": "restricted", "is_active": True, "is_restricted": True}]}

        with self.assertRaisesRegex(RuntimeError, "No active, controllable Spotify device"):
            spotify_curator_tool.playback_control(Spotify(), "next")

    def test_control_backend_uses_the_shared_supported_adapter(self):
        source = SERVER.read_text(encoding="utf-8")
        start = source.index("def spotify_playback_command")
        end = source.index("# APOLLO MUSIC — PERSONAL PLAYLIST ALIASES", start)
        function = source[start:end]
        self.assertIn('"playback-control"', function)
        self.assertNotIn("SPOTIFY_TOOL", function)
        self.assertNotIn("subprocess.run", function)
