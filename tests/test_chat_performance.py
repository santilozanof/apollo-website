import ast
import threading
import time
import unittest
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1] / "server.py"


def load_function(name, namespace):
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    node = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == name
    )
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SERVER), "exec"), namespace)
    return namespace[name]


class ChatPerformanceTests(unittest.TestCase):
    def test_independent_personal_context_reads_run_concurrently(self):
        def slow(value):
            time.sleep(0.12)
            return value

        fetch = load_function("apollo_fetch_planned_context", {
            "ThreadPoolExecutor": ThreadPoolExecutor,
            "as_completed": as_completed,
            "apollo_context_calendar": lambda _days, **_kwargs: slow({"events": [{"title": "Class"}], "source_errors": {}}),
            "apollo_context_tasks": lambda: slow([{"title": "Homework"}]),
            "apollo_context_whoop": lambda: {},
            "apollo_context_spotify": lambda: {},
        })
        started = time.perf_counter()
        result = fetch({"calendar": True, "tasks": True, "calendar_days": 3})
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 0.21)
        self.assertEqual(result["calendar"]["events"][0]["title"], "Class")
        self.assertEqual(result["tasks"][0]["title"], "Homework")

    def test_whoop_recovery_history_paginates_once_then_uses_cache(self):
        calls = []

        def record(index):
            return {
                "created_at": f"2026-09-{index + 1:02d}T08:00:00Z",
                "score_state": "SCORED",
                "score": {"recovery_score": 40 + index},
            }

        def api_get(endpoint):
            calls.append(endpoint)
            if "nextToken" in endpoint:
                return {"records": [record(index) for index in range(25, 30)]}
            return {
                "records": [record(index) for index in range(25)],
                "next_token": "page-two",
            }

        namespace = {
            "time": time,
            "datetime": datetime,
            "timedelta": timedelta,
            "timezone": timezone,
            "urllib": __import__("urllib"),
            "threading": threading,
            "WHOOP_RECOVERY_HISTORY_CACHE": {"value": None, "at": 0.0},
            "WHOOP_RECOVERY_HISTORY_CACHE_LOCK": threading.Lock(),
            "whoop_api_get": api_get,
            "_apollo_ui_number": lambda value: isinstance(value, (int, float)),
        }
        history = load_function("whoop_recovery_history", namespace)
        first = history(30)
        second = history(7)

        self.assertEqual(len(first), 30)
        self.assertEqual(len(second), 7)
        self.assertEqual(len(calls), 2)
        self.assertIn("nextToken=page-two", calls[1])


if __name__ == "__main__":
    unittest.main()
