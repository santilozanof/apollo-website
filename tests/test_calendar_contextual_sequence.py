import ast
import hashlib
import json
import unittest
from pathlib import Path
from apollo_media import generation_request


SERVER = Path(__file__).resolve().parents[1] / "server.py"


def load_function(name, namespace):
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    node = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == name
    )
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SERVER), "exec"), namespace)
    return namespace[name]


class CalendarContextualSequenceTests(unittest.TestCase):
    def test_exact_four_request_sequence_stays_on_calendar_pipeline(self):
        last_event = {}
        routed = []
        requests = [
            "Create Math classes on Mondays and Wednesdays from 10 to 11.",
            "Create Physics classes on the same days from 12 to 1.",
            "Create Yo y el Tec classes on the other days at the same time.",
            "Create Psychology classes on the same days and at the same time.",
        ]

        namespace = {
            "calendar_pending_clear": lambda _chat_id: None,
            "calendar_pending_get": lambda _chat_id: None,
            "calendar_last_event_get": lambda _chat_id: last_event.get("value"),
            "calendar_handle_pending": lambda *_args: None,
            "calendar_server_batch_action": lambda *_args, **_kwargs: None,
            "calendar_interpret_message": lambda message, *_args, **_kwargs: {
                "intent": "create",
                "action": {"summary": message.split(" classes", 1)[0].replace("Create ", "")},
            },
            "calendar_prepare_action": lambda _chat_id, interpreted, **_kwargs: (
                routed.append(interpreted["action"]["summary"])
                or last_event.update({"value": {"id": str(len(routed)), "summary": routed[-1]}})
                or f"Done — added {routed[-1]}."
            ),
        }
        namespace["calendar_maybe_related"] = load_function(
            "calendar_maybe_related", namespace
        )
        chat = load_function("apollo_calendar_chat", namespace)

        for message in requests:
            reply = chat(
                42,
                message,
                {"time_zone": "Europe/Zurich"},
                conversation_context="\n".join(requests[: len(routed)]),
            )
            self.assertTrue(reply.startswith("Done — added"), message)

        self.assertEqual(routed, ["Math", "Physics", "Yo y el Tec", "Psychology"])

    def test_contextual_tool_routing_keeps_calendar_registered(self):
        choose = load_function(
            "_apollo_choose_hermes_toolsets",
            {
                "_apollo_latest_user_text": lambda messages: messages[-1]["content"],
                "_apollo_turn_has_image": lambda _messages: False,
                "generation_request": generation_request,
            },
        )
        messages = [
            {"role": "user", "content": "Create Math classes on Monday."},
            {"role": "assistant", "content": "Done — added Math to your calendar."},
            {"role": "user", "content": "Psychology on the same days at the same time."},
        ]
        self.assertEqual(choose(messages), ["calendar"])

    def test_create_retry_reads_existing_google_event_instead_of_duplicating(self):
        stored = {
            "id": None,
            "summary": "Psychology",
            "start": {"dateTime": "2026-10-19T10:00:00+02:00", "timeZone": "Europe/Zurich"},
            "end": {"dateTime": "2026-10-19T11:00:00+02:00", "timeZone": "Europe/Zurich"},
            "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO,WE"],
        }
        posts = []

        def api(method, event_id=None, body=None, calendar_id="primary"):
            if method == "POST":
                posts.append((body, calendar_id))
                stored.update(body)
                if len(posts) == 2:
                    raise RuntimeError("Google Calendar POST failed: 409 duplicate")
                return dict(stored)
            raise AssertionError(method)

        namespace = {
            "hashlib": hashlib,
            "google_calendar_api_request": api,
            "google_calendar_get_event": lambda event_id, calendar_id="primary": {
                **stored, "id": event_id,
            },
            "build_google_event_body": lambda data, partial=False: {
                key: data[key] for key in ("summary", "start", "end", "recurrence")
            },
            "clean_google_event": lambda event, calendar_id="primary": {
                **event, "calendarId": calendar_id,
            },
        }
        create = load_function("google_calendar_create_event", namespace)
        action = {
            "summary": "Psychology",
            "calendar_id": "school@example.com",
            "start": stored["start"],
            "end": stored["end"],
            "recurrence": stored["recurrence"],
            "_idempotency_key": "chat-42-psychology",
        }

        first = create(action)
        second = create(action)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["calendarId"], "school@example.com")
        self.assertEqual(len({item[0]["id"] for item in posts}), 1)

    def test_create_idempotency_key_is_stable_and_scoped_to_chat(self):
        key = load_function(
            "calendar_create_idempotency_key",
            {"json": json, "hashlib": hashlib},
        )
        action = {
            "summary": "Psychology",
            "calendar_id": "school@example.com",
            "start": "2026-10-19T10:00",
            "end": "2026-10-19T11:00",
            "time_zone": "Europe/Zurich",
            "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO,WE"],
        }
        self.assertEqual(key(42, action), key(42, dict(action)))
        self.assertNotEqual(key(42, action), key(43, action))


if __name__ == "__main__":
    unittest.main()
