import ast
import json
import subprocess
import threading
import time
import unittest
from pathlib import Path


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
