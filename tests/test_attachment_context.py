import ast
import base64
import io
import json
import mimetypes
import os
import tempfile
import types
import urllib.error
import urllib.parse
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


class AttachmentContextTests(unittest.TestCase):
    def test_later_turn_keeps_facts_without_reembedding_image_bytes(self):
        namespace = {
            "base64": base64,
            "mimetypes": mimetypes,
            "os": os,
        }
        prepare = load_function("_apollo_prepare_hermes_messages", namespace)

        with tempfile.NamedTemporaryFile(suffix=".png") as image:
            image.write(b"not-a-real-png-but-valid-base64-input")
            image.flush()
            messages = [
                {
                    "role": "user",
                    "content": "FILES ATTACHED\nlocal path: " + image.name,
                },
                {"role": "assistant", "content": "What time should I use?"},
                {
                    "role": "user",
                    "content": (
                        "Add them at the start of each day.\n\n"
                        "PERSISTED ATTACHMENT FACTS:\n"
                        "2026-09-03 Monterrey to Mexico City"
                    ),
                },
            ]

            prepared = prepare(messages)

        self.assertIsInstance(prepared[0]["content"], str)
        self.assertIn("2026-09-03", prepared[2]["content"])
        self.assertNotIn("image_url", str(prepared))

    def test_travel_calendar_follow_up_keeps_every_attachment_fact(self):
        seen = {}
        facts = (
            "Travel itinerary: 2026-09-03 — Monterrey to Mexico City; "
            "2026-09-07 — Mexico City to Oaxaca; "
            "2026-09-12 — Oaxaca to Monterrey. Times are not shown."
        )

        def interpret(message, *_args, **_kwargs):
            seen["message"] = message
            return {"intent": "create", "events": []}

        namespace = {
            "calendar_last_event_get": lambda _chat_id: None,
            "calendar_pending_get": lambda _chat_id: None,
            "calendar_handle_pending": lambda *_args: None,
            "calendar_maybe_related": lambda *_args, **_kwargs: False,
            "calendar_interpret_message": interpret,
            "calendar_prepare_action": lambda *_args, **_kwargs: "ready",
            "calendar_pending_clear": lambda _chat_id: None,
            "calendar_pending_set": lambda *_args: None,
        }
        calendar_chat = load_function("apollo_calendar_chat", namespace)

        reply = calendar_chat(
            7,
            "just add them like at the start of each day",
            {},
            attachment_context=facts,
        )

        self.assertEqual(reply, "ready")
        self.assertIn("2026-09-03", seen["message"])
        self.assertIn("Monterrey to Mexico City", seen["message"])
        self.assertIn("2026-09-07", seen["message"])
        self.assertIn("Mexico City to Oaxaca", seen["message"])
        self.assertIn("2026-09-12", seen["message"])
        self.assertIn("Oaxaca to Monterrey", seen["message"])

    def test_calendar_hermes_prompts_keep_itinerary_facts_across_three_turns(self):
        """Calendar clarification prompts retain the original itinerary."""
        facts = (
            "Travel itinerary:\n"
            "- 2026-09-03: Monterrey to Mexico City\n"
            "- 2026-09-07: Mexico City to Oaxaca\n"
            "- 2026-09-12: Oaxaca to Monterrey"
        )
        pending = {}
        hermes_prompts = []
        hermes_results = [
            {
                "intent": "clarify",
                "reply": "What time should I use?",
                "confirmation": None,
                "action": None,
            },
            {
                "intent": "clarify",
                "reply": "Include arrival dates too?",
                "confirmation": None,
                "action": None,
            },
            {
                "intent": "create",
                "reply": None,
                "confirmation": None,
                "action": {"summary": "Itinerary marker"},
            },
        ]

        def ask_hermes(prompt):
            hermes_prompts.append(prompt)
            return json.dumps(hermes_results.pop(0))

        def pending_get(_chat_id):
            return pending.get("value")

        def pending_set(_chat_id, value):
            pending["value"] = value

        def pending_clear(_chat_id):
            pending.pop("value", None)

        namespace = {
            "json": json,
            "ask_hermes": ask_hermes,
            "calendar_clean_json": json.loads,
            "calendar_context_now": lambda _context: (
                "2026-09-01T09:00:00", "America/Monterrey"
            ),
            "calendar_chat_events": lambda _timezone: [],
            "calendar_last_event_get": lambda _chat_id: None,
            "calendar_pending_get": pending_get,
            "calendar_pending_set": pending_set,
            "calendar_pending_clear": pending_clear,
            "calendar_handle_pending": lambda *_args: None,
            "calendar_maybe_related": lambda *_args, **_kwargs: True,
            "calendar_prepare_action": lambda *_args, **_kwargs: "ready",
        }
        namespace["calendar_interpret_message"] = load_function(
            "calendar_interpret_message", namespace
        )
        calendar_chat = load_function("apollo_calendar_chat", namespace)

        self.assertEqual(
            calendar_chat(7, "add these to my calendar", {}, facts),
            "What time should I use?",
        )
        self.assertEqual(
            calendar_chat(
                7,
                "just add them like at the beginning of the day",
                {},
                facts,
            ),
            "Include arrival dates too?",
        )
        self.assertEqual(
            calendar_chat(7, "all the dates listed there", {}, facts),
            "ready",
        )

        self.assertEqual(len(hermes_prompts), 3)

        for prompt in hermes_prompts:
            sent_message = json.loads(prompt[1]["content"])["message"]
            self.assertIn("2026-09-03", sent_message)
            self.assertIn("Monterrey to Mexico City", sent_message)
            self.assertIn("2026-09-07", sent_message)
            self.assertIn("Mexico City to Oaxaca", sent_message)
            self.assertIn("2026-09-12", sent_message)
            self.assertIn("Oaxaca to Monterrey", sent_message)

    def test_real_three_turn_attachment_reference_stays_next_to_current_user(self):
        """Normal chat retains exact itinerary facts after every follow-up."""
        facts = (
            "APOLLO ATTACHMENT FACTS V2\n"
            "Salida de México: 04 de septiembre.\n"
            "Llegada a Antibes: 05 de septiembre.\n"
            "Salida a París: 03 de octubre.\n"
            "Salida a Lausana: 06 de octubre.\n"
            "Salida a Milán: 06 de noviembre.\n"
            "Salida a Florencia: 08 de noviembre.\n"
            "Salida a Roma: 28 de noviembre.\n"
            "Salida a México: 01 de diciembre."
        )
        reference = load_function(
            "apollo_attachment_reference_message", {}
        )
        prepare = load_function(
            "_apollo_prepare_hermes_messages",
            {"base64": base64, "mimetypes": mimetypes, "os": os},
        )

        history = [
            {"role": "user", "content": "add these to my calendar"},
            {"role": "assistant", "content": "What time should I use?"},
        ]

        for follow_up in (
            "just add them like at the beginning of the day",
            "all the dates listed there",
            "add them",
        ):
            messages = history + [
                reference(facts),
                {"role": "user", "content": follow_up},
            ]
            prepared = prepare(messages)
            durable = prepared[-2]["content"]

            self.assertIn("04 de septiembre", durable)
            self.assertIn("Antibes", durable)
            self.assertIn("03 de octubre", durable)
            self.assertIn("París", durable)
            self.assertIn("06 de noviembre", durable)
            self.assertIn("Milán", durable)
            self.assertIn("01 de diciembre", durable)

            history.extend([
                {"role": "user", "content": follow_up},
                {"role": "assistant", "content": "Acknowledged."},
            ])

    def test_google_refresh_persists_rotated_refresh_token(self):
        state = {
            "google_access_token": "expired",
            "google_access_token_expires_at": "0",
            "google_refresh_token": "old-refresh",
        }

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({
                    "access_token": "fresh-access",
                    "refresh_token": "rotated-refresh",
                    "expires_in": 3600,
                }).encode("utf-8")

        fake_urllib = types.SimpleNamespace(
            parse=urllib.parse,
            error=types.SimpleNamespace(HTTPError=urllib.error.HTTPError),
            request=types.SimpleNamespace(
                Request=lambda *args, **kwargs: (args, kwargs),
                urlopen=lambda *_args, **_kwargs: Response(),
            ),
        )
        namespace = {
            "json": json,
            "time": types.SimpleNamespace(time=lambda: 1000),
            "urllib": fake_urllib,
            "GoogleCalendarAuthError": RuntimeError,
            "app_state_get": lambda key, default=None: state.get(key, default),
            "app_state_set": lambda key, value: state.__setitem__(key, str(value)),
            "get_google_oauth_config": lambda: {
                "client_id": "id",
                "client_secret": "secret",
                "token_uri": "https://example.test/token",
            },
        }
        token = load_function("google_get_access_token", namespace)

        self.assertEqual(token(), "fresh-access")
        self.assertEqual(state["google_access_token"], "fresh-access")
        self.assertEqual(state["google_refresh_token"], "rotated-refresh")

    def test_google_status_requires_reconnect_when_refresh_is_invalid(self):
        class AuthError(RuntimeError):
            pass

        namespace = {
            "GoogleCalendarAuthError": AuthError,
            "app_state_get": lambda key, default=None: (
                "saved-refresh" if key == "google_refresh_token" else default
            ),
            "google_get_access_token": lambda: (_ for _ in ()).throw(
                AuthError("authorization expired")
            ),
        }
        status = load_function("google_calendar_connection_status", namespace)

        self.assertEqual(
            status(),
            {
                "connected": False,
                "reconnect": True,
                "error": "authorization expired",
            },
        )

    def test_google_calendar_request_retries_once_after_unauthorized(self):
        calls = []
        cleared = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"items": []}'

        def urlopen(request, **_kwargs):
            calls.append(request)
            if len(calls) == 1:
                raise urllib.error.HTTPError(
                    "https://example.test/calendar",
                    401,
                    "Unauthorized",
                    {},
                    io.BytesIO(b'{"error":"invalidCredentials"}'),
                )
            return Response()

        fake_urllib = types.SimpleNamespace(
            error=types.SimpleNamespace(HTTPError=urllib.error.HTTPError),
            request=types.SimpleNamespace(urlopen=urlopen),
        )
        namespace = {
            "urllib": fake_urllib,
            "GoogleCalendarAuthError": RuntimeError,
            "google_get_access_token": lambda: (
                "stale" if not cleared else "fresh"
            ),
            "google_clear_access_token": lambda: cleared.append(True),
            "google_clear_oauth_tokens": lambda: None,
        }
        request_raw = load_function("google_calendar_request_raw", namespace)

        self.assertEqual(
            request_raw(lambda token: token, "request"),
            b'{"items": []}',
        )
        self.assertEqual(calls, ["stale", "fresh"])
        self.assertEqual(cleared, [True])


if __name__ == "__main__":
    unittest.main()
