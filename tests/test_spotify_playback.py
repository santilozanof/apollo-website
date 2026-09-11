import ast
import json
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

    def test_current_command_preserves_the_helper_refresh_and_api_result(self):
        calls = []

        class Result:
            returncode = 0
            stdout = json.dumps({"is_playing": False, "item": {"name": "Song"}})
            stderr = ""

        class Subprocess:
            @staticmethod
            def run(args, **kwargs):
                calls.append((args, kwargs))
                return Result()

        state = self.state()
        current = load_function("get_now_playing", {
            "json": json,
            "subprocess": Subprocess,
            "SPOTIFY_PYTHON": "spotify-python",
            "SPOTIFY_TOOL": "spotify-tool",
            "spotify_playback_state": state,
        })

        response = current()
        self.assertEqual(calls[0][0], ["spotify-python", "spotify-tool", "current"])
        self.assertEqual(calls[0][1]["timeout"], 15)
        self.assertEqual(response["playback_state"], "paused")
