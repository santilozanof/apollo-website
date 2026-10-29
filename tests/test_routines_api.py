import ast
import sys
from types import SimpleNamespace
import io
import json
import re
import sqlite3
import tempfile
import unittest
import urllib.parse
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import routines


SERVER = Path(__file__).resolve().parents[1] / "server.py"


def load_function(name, namespace):
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    node = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == name
    )
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SERVER), "exec"), namespace)
    return namespace[name]


def load_class(name, namespace):
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    node = next(
        item for item in tree.body
        if isinstance(item, ast.ClassDef) and item.name == name
    )
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SERVER), "exec"), namespace)
    return namespace[name]


class RoutinesApiRegressionTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        routines.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_proxy_stripped_and_public_routine_routes_share_one_contract(self):
        canonical = load_function(
            "canonical_api_request_path",
            {"urllib": urllib},
        )
        cases = {
            "/api/routines?date=2026-10-13": "/api/routines?date=2026-10-13",
            "/routines?date=2026-10-13": "/api/routines?date=2026-10-13",
            "/api/routines/action": "/api/routines/action",
            "/routines/action": "/api/routines/action",
            "/routines/history?timezone=Europe%2FZurich": "/api/routines/history?timezone=Europe%2FZurich",
        }
        for incoming, expected in cases.items():
            self.assertEqual(canonical(incoming), expected)

    def test_actual_http_handler_accepts_proxy_stripped_routine_routes(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as database:
            initial = sqlite3.connect(database.name)
            initial.row_factory = sqlite3.Row
            routines.init_schema(initial)
            initial.commit()
            initial.close()

            def database_connection():
                connection = sqlite3.connect(database.name)
                connection.row_factory = sqlite3.Row
                return connection

            def json_response(handler, payload, status=200):
                body = json.dumps(payload).encode("utf-8")
                handler.send_response(status)
                handler.send_header("Content-Type", "application/json")
                handler.send_header("Content-Length", str(len(body)))
                handler.end_headers()
                handler.wfile.write(body)

            def read_json(handler):
                size = int(handler.headers.get("Content-Length", "0"))
                return json.loads(handler.rfile.read(size) or b"{}")

            namespace = {
                "__name__": __name__,
                "sys": sys,
                "apollo_intelligence": SimpleNamespace(handle_api=lambda *_: False),
                "apollo_security": SimpleNamespace(handle=lambda *_: False),
                "BaseHTTPRequestHandler": BaseHTTPRequestHandler,
                "urllib": urllib,
                "re": re,
                "datetime": datetime,
                "timedelta": timedelta,
                "routines": routines,
                "db": database_connection,
                "json_response": json_response,
                "read_json": read_json,
            }
            namespace["canonical_api_request_path"] = load_function(
                "canonical_api_request_path", namespace
            )
            handler = load_class("ApolloHandler", namespace)

            def request(method, path, payload=None):
                instance = object.__new__(handler)
                body = json.dumps(payload).encode("utf-8") if payload is not None else b""
                instance.path = path
                instance.headers = {"Content-Length": str(len(body))}
                instance.rfile = io.BytesIO(body)
                instance.wfile = io.BytesIO()
                instance.status = None
                instance.send_response = lambda status: setattr(instance, "status", status)
                instance.send_header = lambda *_args: None
                instance.end_headers = lambda: None
                getattr(instance, f"do_{method}")()
                return instance.status, json.loads(instance.wfile.getvalue())

            status, created = request("POST", "/routines/action", {
                "action": "create_routine",
                "title": "HTTP contract",
                "schedule_days": list(range(7)),
                "steps": [{"title": "Round trip"}],
                "timezone": "Europe/Zurich",
            })
            self.assertEqual(status, 201)

            current_day = routines.local_day("Europe/Zurich")
            status, state = request(
                "GET",
                "/routines?date=" + current_day + "&timezone=Europe%2FZurich",
            )
            self.assertEqual(status, 200)
            self.assertEqual(state["routines"][0]["id"], created["id"])
            self.assertEqual(state["routines"][0]["steps"][0]["title"], "Round trip")

    def test_create_retrieve_edit_schedule_toggle_and_delete_via_api_contract(self):
        today = datetime.fromisoformat(routines.local_day("Europe/Zurich")).date()
        scheduled_day = next(
            today + timedelta(days=offset)
            for offset in range(7)
            if (today + timedelta(days=offset)).weekday() in {0, 2, 4}
        ).isoformat()
        unscheduled_day = next(
            today + timedelta(days=offset)
            for offset in range(7)
            if (today + timedelta(days=offset)).weekday() not in {0, 2, 4}
        ).isoformat()
        created = routines.api_action(self.conn, {
            "action": "create_routine",
            "title": "API verification",
            "schedule_days": list(range(7)),
            "steps": [{"title": "First"}, {"title": "Second"}],
        }, "Europe/Zurich")
        routine_id = created["id"]
        step_id = created["steps"][0]["id"]

        retrieved = routines.get_state(
            self.conn, today.isoformat(), "Europe/Zurich"
        )["routines"][0]
        self.assertEqual(retrieved["title"], "API verification")

        edited = routines.api_action(self.conn, {
            "action": "update_routine",
            "routine_id": routine_id,
            "changes": {"title": "API verified", "schedule_days": [0, 2, 4]},
        }, "Europe/Zurich")
        self.assertEqual(edited["title"], "API verified")
        self.assertEqual(edited["schedule_days"], [0, 2, 4])

        # Tuesday is no longer scheduled, while Wednesday remains writable.
        tuesday = routines.get_state(
            self.conn, unscheduled_day, "Europe/Zurich"
        )["routines"][0]
        self.assertEqual(tuesday["status"], "not_scheduled")

        checked = routines.api_action(self.conn, {
            "action": "set_step",
            "routine_id": routine_id,
            "step_id": step_id,
            "date": scheduled_day,
            "completed": True,
            "idempotency_key": "check-once",
        }, "Europe/Zurich")
        self.assertTrue(checked["steps"][0]["complete"])
        unchecked = routines.api_action(self.conn, {
            "action": "set_step",
            "routine_id": routine_id,
            "step_id": step_id,
            "date": scheduled_day,
            "completed": False,
            "idempotency_key": "uncheck-once",
        }, "Europe/Zurich")
        self.assertFalse(unchecked["steps"][0]["complete"])

        row = self.conn.execute(
            "SELECT value,completed_at FROM routine_step_daily "
            "WHERE instance_id=? AND step_id=?",
            (unchecked["instance_id"], step_id),
        ).fetchone()
        self.assertEqual(row["value"], 0)
        self.assertIsNone(row["completed_at"])
        refreshed = routines.get_state(
            self.conn, scheduled_day, "Europe/Zurich"
        )["routines"][0]
        self.assertFalse(refreshed["steps"][0]["complete"])

        deleted = routines.api_action(self.conn, {
            "action": "delete_routine",
            "routine_id": routine_id,
            "delete_history": False,
        }, "Europe/Zurich")
        self.assertTrue(deleted["archived"])
        self.assertEqual(
            routines.get_state(self.conn, scheduled_day, "Europe/Zurich")["routines"],
            [],
        )

    def test_toggle_is_idempotent_per_request_but_allows_later_reverse(self):
        routine = routines.create_routine(self.conn, {
            "title": "Toggle",
            "steps": [{"title": "Checkbox"}],
        }, today="2026-10-13")
        step_id = routine["steps"][0]["id"]
        payload = {
            "action": "set_step",
            "routine_id": routine["id"],
            "step_id": step_id,
            "date": "2026-10-13",
            "completed": True,
            "idempotency_key": "same-check-request",
        }
        routines.api_action(self.conn, payload, "Europe/Zurich")
        routines.api_action(self.conn, payload, "Europe/Zurich")
        events = self.conn.execute(
            "SELECT count(*) FROM routine_completion_events"
        ).fetchone()[0]
        self.assertEqual(events, 1)

        payload.update({
            "completed": False,
            "idempotency_key": "later-uncheck-request",
        })
        result = routines.api_action(self.conn, payload, "Europe/Zurich")
        self.assertFalse(result["steps"][0]["complete"])
        self.assertEqual(
            self.conn.execute(
                "SELECT count(*) FROM routine_completion_events"
            ).fetchone()[0],
            2,
        )


if __name__ == "__main__":
    unittest.main()
