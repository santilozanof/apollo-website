import ast
import json
import threading
import time
import unittest
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace


SERVER = Path(__file__).resolve().parents[1] / "server.py"


def load_function(name, namespace):
    node = next(item for item in ast.parse(SERVER.read_text()).body
                if isinstance(item, ast.FunctionDef) and item.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SERVER), "exec"), namespace)
    return namespace[name]


class WhoopRefreshReliabilityTests(unittest.TestCase):
    def test_rotating_refresh_token_is_used_once_by_concurrent_readers(self):
        state = {"whoop_refresh_token": "first"}
        requests = []

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): return None
            def read(self):
                time.sleep(0.04)
                return json.dumps({"access_token": "new-access", "refresh_token": "second"}).encode()

        def urlopen(request, timeout):
            requests.append(urllib.parse.parse_qs(request.data.decode())["refresh_token"][0])
            return Response()

        namespace = {
            "WHOOP_TOKEN_REFRESH_LOCK": threading.RLock(),
            "WHOOP_TOKEN_URI": "https://whoop.example/token",
            "time": time, "urllib": SimpleNamespace(
                parse=urllib.parse, request=SimpleNamespace(Request=lambda *a, **k: SimpleNamespace(data=k["data"]), urlopen=urlopen),
            ),
            "json": json,
            "app_state_get": lambda key, default=None: state.get(key, default),
            "get_whoop_oauth_config": lambda: {"client_id": "id", "client_secret": "secret"},
            "whoop_save_token_data": lambda data: state.update({
                "whoop_access_token": data["access_token"],
                "whoop_access_token_expires_at": str(int(time.time()) + 3600),
                "whoop_refresh_token": data["refresh_token"],
            }),
        }
        load_function("_whoop_get_access_token_locked", namespace)
        get_token = load_function("whoop_get_access_token", namespace)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: get_token(), range(2)))
        self.assertEqual(results, ["new-access", "new-access"])
        self.assertEqual(requests, ["first"])
        self.assertEqual(state["whoop_refresh_token"], "second")

    def test_unscored_sleep_is_missing_not_zero(self):
        namespace = {
            "whoop_api_get": lambda endpoint: {
                "records": [{"score_state": "PENDING_SCORE", "score": {}}]
            } if "sleep" in endpoint else {"records": []},
            "whoop_millis_hours": lambda value: None if value is None else round(float(value) / 3600000, 2),
            "app_state_set": lambda *_: None,
            "datetime": datetime, "timezone": timezone,
        }
        summary = load_function("whoop_current_summary", namespace)()
        self.assertIsNone(summary["sleep"]["total_sleep_hours"])
        self.assertIsNone(summary["sleep"]["sleep_need_hours"])
        self.assertIsNone(summary["sleep"]["performance_percentage"])


if __name__ == "__main__":
    unittest.main()
