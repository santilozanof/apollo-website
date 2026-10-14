import io
import json
import os
import tempfile
import unittest
from unittest import mock


_workspace = tempfile.TemporaryDirectory(prefix="apollo-genui-live-")
_previous_base = os.environ.get("APOLLO_BASE_DIR")
os.environ["APOLLO_BASE_DIR"] = _workspace.name
import server  # noqa: E402
if _previous_base is None:
    os.environ.pop("APOLLO_BASE_DIR", None)
else:
    os.environ["APOLLO_BASE_DIR"] = _previous_base


def request(method, path, payload=None):
    handler = object.__new__(server.ApolloHandler)
    body = json.dumps(payload).encode("utf-8") if payload is not None else b""
    handler.path = path
    handler.headers = {"Content-Length": str(len(body))}
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    handler.status = None
    handler.send_response = lambda status: setattr(handler, "status", status)
    handler.send_header = lambda *_args: None
    handler.end_headers = lambda: None
    getattr(handler, "do_" + method)()
    return handler.status, handler.wfile.getvalue()


def sse_events(raw):
    events = []
    for line in raw.decode("utf-8").splitlines():
        if line.startswith("data:"):
            events.append(json.loads(line[5:].strip()))
    return events


class GenerativeUILivePipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.DB_PATH = server.BASE_DIR / "test.db"
        server.init_db()

    def setUp(self):
        connection = server.db()
        connection.execute("DELETE FROM message_attachments")
        connection.execute("DELETE FROM message_attachment_contexts")
        connection.execute("DELETE FROM messages")
        connection.execute("DELETE FROM chats")
        connection.execute("DELETE FROM routine_completion_events")
        connection.execute("DELETE FROM routine_step_daily")
        connection.execute("DELETE FROM routine_daily_instances")
        connection.execute("DELETE FROM routine_versions")
        connection.execute("DELETE FROM routine_step_exceptions")
        connection.execute("DELETE FROM routine_steps")
        connection.execute("DELETE FROM routine_groups")
        connection.execute("DELETE FROM tasks")
        connection.commit()
        connection.close()

    def run_turn(self, response):
        status, raw = request("POST", "/api/chats", {})
        self.assertEqual(status, 201)
        chat_id = json.loads(raw)["id"]

        patches = {
            "apollo_music_action_requested": lambda *_a, **_k: False,
            "apollo_automation_chat_reply": lambda *_a, **_k: None,
            "apollo_task_chat": lambda *_a, **_k: None,
            "apollo_calendar_chat": lambda *_a, **_k: None,
            "apollo_context_planner": lambda *_a, **_k: {},
            "apollo_fetch_planned_context": lambda *_a, **_k: {},
            "apollo_should_reply_semantically": lambda *_a, **_k: True,
            "stream_hermes": lambda _messages: iter(
                [response[: len(response) // 2], response[len(response) // 2 :]]
            ),
            "generate_chat_title": lambda _history: "Generative UI test",
        }
        with mock.patch.multiple(server, **patches):
            status, raw = request("POST", f"/api/chats/{chat_id}/messages", {
                "content": "Show the appropriate response",
                "client_context": {
                    "local_time": "2026-10-14T12:00:00+02:00",
                    "time_zone": "Europe/Zurich",
                    "utc_offset_minutes": 120,
                },
            })

        self.assertEqual(status, 200)
        events = sse_events(raw)
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["message"]["content"], response)

        status, raw = request("GET", f"/api/chats/{chat_id}")
        self.assertEqual(status, 200)
        history = json.loads(raw)
        self.assertEqual(history["messages"][-1]["content"], response)
        return events

    def test_quiz_checklist_cards_and_chart_survive_stream_and_history(self):
        payload = {
            "blocks": [
                {"type": "quiz", "id": "q1", "question": "2 + 2?", "options": [
                    {"id": "a", "label": "4", "correct": True},
                    {"id": "b", "label": "5", "correct": False},
                ]},
                {"type": "checklist", "id": "list", "persisted": False,
                 "items": [{"id": "one", "label": "Review", "completed": False}]},
                {"type": "carousel", "id": "cards", "items": [
                    {"title": "Album", "text": "Artist", "url": "https://example.com/cover.jpg"}
                ]},
                {"type": "chart", "id": "trend", "kind": "line",
                 "items": [{"label": "Mon", "value": 2}, {"label": "Tue", "value": 4}]},
            ]
        }
        response = "Here you go.\n\n```apollo-ui\n" + json.dumps(payload) + "\n```"
        events = self.run_turn(response)
        self.assertGreaterEqual(sum(event["type"] == "content" for event in events), 2)

    def test_ordinary_text_response_remains_plain(self):
        events = self.run_turn("The derivative of x³ is 3x².")
        self.assertNotIn("apollo-ui", events[-1]["message"]["content"])

    def test_task_and_routine_actions_persist_through_real_handlers(self):
        status, raw = request("POST", "/api/tasks/create", {
            "title": "Generative UI temporary task",
        })
        self.assertEqual(status, 201)
        task_id = json.loads(raw)["task"]["id"]
        status, raw = request("POST", "/api/tasks/update", {
            "task_id": task_id, "completed": True,
        })
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(raw)["task"]["completed"])
        status, raw = request("GET", "/api/tasks")
        saved = next(item for item in json.loads(raw)["tasks"] if item["id"] == task_id)
        self.assertTrue(saved["completed"])

        status, raw = request("POST", "/api/routines/action", {
            "action": "create_routine", "title": "Generative UI temporary routine",
            "schedule_days": list(range(7)), "steps": [{"title": "Temporary step"}],
            "timezone": "Europe/Zurich",
        })
        self.assertEqual(status, 201)
        routine = json.loads(raw)
        day = server.routines.local_day("Europe/Zurich")
        status, raw = request("POST", "/api/routines/action", {
            "action": "set_step", "routine_id": routine["id"],
            "step_id": routine["steps"][0]["id"], "date": day,
            "completed": True, "timezone": "Europe/Zurich",
        })
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(raw)["steps"][0]["complete"])
        status, raw = request(
            "GET", f"/api/routines?date={day}&timezone=Europe%2FZurich"
        )
        persisted = json.loads(raw)["routines"][0]
        self.assertTrue(persisted["steps"][0]["complete"])


def tearDownModule():
    _workspace.cleanup()
