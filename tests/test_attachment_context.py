import ast
import base64
import mimetypes
import os
import tempfile
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


if __name__ == "__main__":
    unittest.main()
