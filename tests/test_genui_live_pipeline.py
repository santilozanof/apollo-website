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
        connection.execute("DELETE FROM hydration_entries")
        connection.execute("DELETE FROM tasks")
        connection.commit()
        connection.close()

    def run_turn(self, response, prompt="Show the appropriate response", recovery=""):
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
            "ask_hermes": lambda *_a, **_k: recovery,
            "generate_chat_title": lambda _history: "Generative UI test",
        }
        with mock.patch.multiple(server, **patches):
            status, raw = request("POST", f"/api/chats/{chat_id}/messages", {
                "content": prompt,
                "client_context": {
                    "local_time": "2026-10-14T12:00:00+02:00",
                    "time_zone": "Europe/Zurich",
                    "utc_offset_minutes": 120,
                },
            })

        self.assertEqual(status, 200)
        events = sse_events(raw)
        self.assertEqual(events[-1]["type"], "done")
        self.assertIn("backend_to_done_ms", events[-1]["timings"])
        self.assertIn("model_ttft_ms", events[-1]["timings"])
        requirements = server._apollo_extract_ui_requirements(prompt)
        expected = server._apollo_prune_misaligned_ui(
            server.apollo_sanitize_genui_content(response), requirements
        )
        if recovery:
            recovered = server._apollo_prune_misaligned_ui(
                server.apollo_sanitize_genui_content(recovery), requirements
            )
            candidate = (expected + "\n\n" + recovered).strip()
            if len(server._apollo_validate_ui_requirements(candidate, requirements)) < len(
                server._apollo_validate_ui_requirements(expected, requirements)
            ):
                expected = candidate
        self.assertEqual(events[-1]["message"]["content"], expected)

        status, raw = request("GET", f"/api/chats/{chat_id}")
        self.assertEqual(status, 200)
        history = json.loads(raw)
        self.assertEqual(history["messages"][-1]["content"], expected)
        return events

    def create_chat(self):
        status, raw = request("POST", "/api/chats", {})
        self.assertEqual(status, 201)
        return json.loads(raw)["id"]

    def planned_turn(self, chat_id, content, plan, response="Normal answer."):
        patches = {
            "apollo_context_planner": lambda *_a, **_k: plan,
            "apollo_music_action_requested": lambda *_a, **_k: False,
            "apollo_automation_chat_reply": lambda *_a, **_k: None,
            "apollo_fetch_planned_context": lambda *_a, **_k: {},
            "apollo_should_reply_semantically": lambda *_a, **_k: True,
            "stream_hermes": lambda _messages: iter([response[:8], response[8:]]),
            "generate_chat_title": lambda _history: "Intent test",
        }
        with mock.patch.multiple(server, **patches):
            status, raw = request("POST", f"/api/chats/{chat_id}/messages", {
                "content": content,
                "client_context": {
                    "local_time": "2026-10-14T12:00:00+02:00",
                    "time_zone": "Europe/Zurich",
                    "utc_offset_minutes": 120,
                },
            })
        self.assertEqual(status, 200)
        return sse_events(raw)

    def test_quiz_checklist_cards_and_chart_survive_stream_and_history(self):
        payload = {
            "blocks": [
                {"type": "quiz", "id": "q1", "allow_retry": True,
                 "questions": [{"id": "math-1", "question": "2 + 2?", "options": [
                    {"id": "a", "label": "4"},
                    {"id": "b", "label": "5"},
                 ], "correct_answer_id": "a"}]},
                {"type": "checklist", "id": "list", "persisted": False,
                 "items": [{"id": "one", "label": "Review", "completed": False}]},
                {"type": "carousel", "id": "cards", "items": [
                    {"title": "Album", "text": "Artist", "url": "https://example.com/cover.jpg"}
                ]},
                {"type": "chart", "id": "trend", "kind": "line",
                 "x_label": "Day", "y_label": "Sessions", "unit": "sessions",
                 "data_kind": "measured",
                 "items": [{"label": "Mon", "value": 2}, {"label": "Tue", "value": 4}]},
            ]
        }
        response = "Here you go.\n\n```apollo-ui\n" + json.dumps(payload) + "\n```"
        events = self.run_turn(response)
        self.assertGreaterEqual(sum(event["type"] == "content" for event in events), 2)

    def test_ordinary_text_response_remains_plain(self):
        events = self.run_turn("The derivative of x³ is 3x².")
        self.assertNotIn("apollo-ui", events[-1]["message"]["content"])

    def test_missing_explicit_quiz_is_recovered_once(self):
        comparison = {"blocks": [{
            "type": "table", "id": "chords",
            "columns": [{"key": "name", "label": "Progression"}],
            "rows": [{"name": "ii–V–I"}],
        }]}
        quiz = {"blocks": [{
            "type": "quiz", "id": "jazz-check", "allow_retry": True,
            "questions": [{
                "id": "q1", "question": "Which chord is the dominant in C?",
                "options": [{"id": "g7", "label": "G7"},
                            {"id": "dm7", "label": "Dm7"}],
                "correct_answer_id": "g7",
                "explanation": "G is scale degree five in C.",
            }],
        }]}
        events = self.run_turn(
            "Jazz uses voice-leading.\n\n```apollo-ui\n"
            + json.dumps(comparison) + "\n```",
            "Teach me jazz harmony with a chord comparison and a short quiz.",
            "```apollo-ui\n" + json.dumps(quiz) + "\n```",
        )
        final = events[-1]
        self.assertTrue(final["timings"]["ui_recovery_used"])
        self.assertEqual(
            server._apollo_validate_ui_requirements(
                final["message"]["content"],
                server._apollo_extract_ui_requirements(
                    "Teach me jazz harmony with a chord comparison and a short quiz."
                ),
            ),
            [],
        )

    def test_unsupported_compound_calculator_is_recovered_with_safe_ast(self):
        prompt = (
            "Build me an interactive compound-interest calculator with a "
            "principal slider, annual interest-rate slider, and time-period "
            "selector. Show the final balance updating immediately."
        )
        calculator = {"blocks": [{
            "type": "calculator", "id": "compound-interest",
            "title": "Compound-interest calculator",
            "fields": [
                {"id": "principal", "label": "Principal", "type": "slider",
                 "value": 10000, "min": 100, "max": 100000, "step": 100},
                {"id": "rate", "label": "Annual rate", "type": "slider",
                 "value": 5, "min": 0, "max": 20, "step": 0.1},
                {"id": "years", "label": "Years", "type": "segmented",
                 "value": 10, "min": 1, "max": 30, "step": 1,
                 "options": [
                     {"label": "5", "value": 5},
                     {"label": "10", "value": 10},
                     {"label": "20", "value": 20},
                 ]},
            ],
            "expression": {
                "op": "multiply", "args": [
                    {"field": "principal"},
                    {"op": "power", "args": [
                        {"op": "add", "args": [
                            1, {"op": "divide", "args": [
                                {"op": "divide", "args": [
                                    {"field": "rate"}, 100,
                                ]}, 12,
                            ]},
                        ]},
                        {"op": "multiply", "args": [12, {"field": "years"}]},
                    ]},
                ],
            },
            "output": {"label": "Final balance", "format": "currency",
                       "currency": "USD", "decimals": 2},
        }]}
        events = self.run_turn(
            "A compound-interest calculator needs more than basic arithmetic.",
            prompt,
            "```apollo-ui\n" + json.dumps(calculator) + "\n```",
        )
        final = events[-1]
        self.assertTrue(final["timings"]["ui_recovery_used"])
        self.assertEqual(
            server._apollo_validate_ui_requirements(
                final["message"]["content"],
                server._apollo_extract_ui_requirements(prompt),
            ),
            [],
        )
        self.assertIn('"op":"power"', final["message"]["content"])

    def test_empty_selector_is_replaced_by_functional_local_selector(self):
        empty = {"blocks": [{
            "type": "button_group", "id": "recipes", "title": "Pick a recipe",
            "actions": [],
        }]}
        selector = {"blocks": [{
            "type": "selector", "id": "recipes", "title": "Pick a recipe",
            "options": [
                {"id": "espresso", "label": "Espresso", "description": "18 g in, 36 g out."},
                {"id": "v60", "label": "V60", "description": "15 g coffee, 250 g water."},
                {"id": "aeropress", "label": "AeroPress", "description": "15 g coffee, 220 g water."},
            ],
        }]}
        prompt = (
            "Compare espresso, V60, and AeroPress with a small selector "
            "that changes the recipe details."
        )
        events = self.run_turn(
            "Comparison.\n\n```apollo-ui\n" + json.dumps(empty) + "\n```",
            prompt,
            "```apollo-ui\n" + json.dumps(selector) + "\n```",
        )
        final = events[-1]["message"]["content"]
        self.assertNotIn('"type":"button_group"', final)
        self.assertIn('"type":"selector"', final)
        self.assertEqual(
            server._apollo_validate_ui_requirements(
                final, server._apollo_extract_ui_requirements(prompt)
            ),
            [],
        )

    def test_off_topic_demo_and_quiz_are_pruned_then_recovered(self):
        prompt = (
            "Teach me kinetic energy with an interactive demonstration that "
            "lets me adjust mass and velocity, plus a short quiz."
        )
        wrong = {"blocks": [
            {"type": "function_explorer", "id": "limit-explorer",
             "preset": "removable_hole", "target": 1, "value": 0.5,
             "min": -1, "max": 3, "step": 0.1},
            {"type": "quiz", "id": "limit-check", "questions": [{
                "id": "q1", "question": "What is the limit?",
                "options": [{"id": "a", "label": "1"},
                            {"id": "b", "label": "2"}],
                "correct_answer_id": "b",
            }]},
        ]}
        correct = {"blocks": [
            {"type": "calculator", "id": "kinetic-energy-demo", "fields": [
                {"id": "mass", "label": "Mass", "type": "slider",
                 "value": 10, "min": 1, "max": 100, "step": 1},
                {"id": "velocity", "label": "Velocity", "type": "slider",
                 "value": 5, "min": 1, "max": 50, "step": 1},
            ], "expression": {"op": "multiply", "args": [0.5, {
                "op": "multiply", "args": [
                    {"field": "mass"},
                    {"op": "power", "args": [{"field": "velocity"}, 2]},
                ],
            }]}},
            {"type": "quiz", "id": "kinetic-energy-check", "questions": [{
                "id": "q1", "question": "What makes kinetic energy quadruple?",
                "options": [{"id": "a", "label": "Doubling mass"},
                            {"id": "b", "label": "Doubling velocity"}],
                "correct_answer_id": "b",
            }]},
        ]}
        events = self.run_turn(
            "Kinetic energy is proportional to mass and velocity squared.\n\n"
            "```apollo-ui\n" + json.dumps(wrong) + "\n```",
            prompt,
            "```apollo-ui\n" + json.dumps(correct) + "\n```",
        )
        final = events[-1]["message"]["content"]
        self.assertNotIn("limit-explorer", final)
        self.assertNotIn("limit-check", final)
        self.assertIn("kinetic-energy-demo", final)
        self.assertIn("kinetic-energy-check", final)
        self.assertTrue(events[-1]["timings"]["ui_recovery_used"])

    def test_general_water_question_never_activates_personal_hydration(self):
        chat_id = self.create_chat()
        plan = {
            "intent": "general_knowledge", "primary_domain": "general",
            "action_authorized": False,
        }
        with mock.patch.object(
            server.routines, "chat_action",
            side_effect=AssertionError("hydration tool must stay inactive"),
        ), mock.patch.object(
            server, "apollo_task_chat",
            side_effect=AssertionError("task tool must stay inactive"),
        ), mock.patch.object(
            server, "apollo_calendar_chat",
            side_effect=AssertionError("calendar tool must stay inactive"),
        ):
            events = self.planned_turn(
                chat_id,
                "How much water does a big bowl of ramen have?",
                plan,
                "A large ramen bowl usually holds roughly 700–1,000 mL of broth.",
            )
        answer = events[-1]["message"]["content"]
        self.assertIn("ramen", answer.lower())
        self.assertIn("broth", answer.lower())
        self.assertNotIn("logged", answer.lower())

    def test_personal_hydration_query_reads_authoritative_state(self):
        chat_id = self.create_chat()
        events = self.planned_turn(chat_id, "How much water have I logged today?", {
            "intent": "personal_query", "primary_domain": "hydration",
            "action_authorized": False,
        })
        response = events[-1]["message"]["content"]
        self.assertIn("You've logged 0 mL today", response)
        self.assertNotIn("```apollo-ui", response)

    def test_explicit_hydration_action_persists_but_ambiguous_action_does_not(self):
        chat_id = self.create_chat()
        events = self.planned_turn(chat_id, "Add 500 mL to my water intake.", {
            "intent": "explicit_action", "primary_domain": "hydration",
            "action_authorized": True,
        })
        self.assertIn("Logged 500 mL", events[-1]["message"]["content"])

        events = self.planned_turn(chat_id, "Change my water.", {
            "intent": "ambiguous_action", "primary_domain": "hydration",
            "action_authorized": False,
            "clarification": "How much water would you like me to log?",
        })
        self.assertEqual(
            events[-1]["message"]["content"],
            "How much water would you like me to log?",
        )
        connection = server.db()
        status = server.routines.hydration_status(
            connection, time_zone="Europe/Zurich"
        )
        connection.close()
        self.assertEqual(status["total_ml"], 500)

    def test_topic_switch_does_not_inherit_previous_personal_tool(self):
        chat_id = self.create_chat()
        self.planned_turn(chat_id, "How much water have I logged?", {
            "intent": "personal_query", "primary_domain": "hydration",
            "action_authorized": False,
        })
        with mock.patch.object(
            server.routines, "chat_action",
            side_effect=AssertionError("previous hydration topic leaked"),
        ):
            events = self.planned_turn(
                chat_id,
                "How much water does ramen have?",
                {"intent": "general_knowledge", "primary_domain": "general",
                 "action_authorized": False},
                "Usually around 700–1,000 mL of broth for a large bowl.",
            )
        self.assertIn("broth", events[-1]["message"]["content"].lower())

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
