"""Generation ownership survives client polling and repeats only on explicit Retry."""
import io
import json
import os
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

_workspace = tempfile.TemporaryDirectory(prefix="apollo-generation-test-")
os.environ.setdefault("APOLLO_BASE_DIR", _workspace.name)
import server  # noqa: E402


def request(method, path, payload=None, headers=None):
    handler = object.__new__(server.ApolloHandler)
    body = json.dumps(payload).encode() if payload is not None else b""
    handler.path = path
    handler.headers = {"Content-Length": str(len(body)), **(headers or {})}
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    handler.status = None
    handler.send_response = lambda status, *_args: setattr(handler, "status", status)
    handler.send_header = lambda *_args: None
    handler.end_headers = lambda: None
    getattr(handler, "do_" + method)()
    return handler.status, json.loads(handler.wfile.getvalue() or b"{}")


class ChatGenerationJobTests(unittest.TestCase):
    def setUp(self):
        self.old_path = server.DB_PATH
        self.temp = tempfile.TemporaryDirectory(prefix="apollo-generation-db-")
        server.DB_PATH = Path(self.temp.name) / "test.db"
        server.init_db()
        conn = server.db()
        conn.execute("INSERT INTO chats(title) VALUES('Test')")
        self.chat_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit(); conn.close()
        server.CHAT_GENERATIONS.clear()

    def tearDown(self):
        server.CHAT_GENERATIONS.clear()
        server.DB_PATH = self.old_path
        self.temp.cleanup()

    def test_disconnect_and_duplicate_start_keep_one_server_job(self):
        started = threading.Event()
        release = threading.Event()
        calls = []
        original = server.ApolloHandler.do_POST

        def fake_post(handler):
            if handler.path.endswith("/messages"):
                calls.append(1)
                handler.wfile.write(b'data: {"type":"content","content":"First sentence."}\n\n')
                started.set()
                release.wait(3)
                handler.wfile.write(b'data: {"type":"done","message":{"content":"First sentence. Complete answer.","attachments":[]}}\n\n')
                return
            return original(handler)

        payload = {"request_id": str(uuid.uuid4()), "content": "Explain something"}
        path = f"/api/chats/{self.chat_id}/generations"
        headers = {"X-Apollo-Request": "chat-generation"}
        with mock.patch.object(server.ApolloHandler, "do_POST", fake_post):
            status, job = request("POST", path, payload, headers)
            self.assertEqual(status, 202)
            self.assertTrue(started.wait(2))
            # The first browser connection has ended; another caller resumes
            # progress without resending the model request.
            second_status, duplicate = request("POST", path, payload, headers)
            self.assertEqual(second_status, 200)
            self.assertEqual(duplicate["id"], job["id"])
            status, progress = request("GET", f"{path}/{job['id']}")
            self.assertEqual(status, 200)
            self.assertEqual(progress["content"], "First sentence.")
            release.set()
            for _ in range(100):
                _, progress = request("GET", f"{path}/{job['id']}")
                if progress["state"] == "complete": break
                time.sleep(.01)
            self.assertEqual(progress["message"]["content"], "First sentence. Complete answer.")
            self.assertEqual(len(calls), 1)

    def test_only_stop_endpoint_cancels_job(self):
        started = threading.Event()
        release = threading.Event()
        original = server.ApolloHandler.do_POST

        def fake_post(handler):
            if handler.path.endswith("/messages"):
                started.set()
                release.wait(3)
                handler.wfile.write(b'data: {"type":"content","content":"Too late"}\n\n')
                return
            return original(handler)

        path = f"/api/chats/{self.chat_id}/generations"
        headers = {"X-Apollo-Request": "chat-generation"}
        with mock.patch.object(server.ApolloHandler, "do_POST", fake_post):
            status, job = request("POST", path, {"request_id": str(uuid.uuid4()), "content": "A question"}, headers)
            self.assertEqual(status, 202)
            self.assertTrue(started.wait(2))
            status, stopped = request("POST", f"{path}/{job['id']}/stop", headers=headers)
            self.assertEqual(status, 200)
            self.assertEqual(stopped["state"], "stopped")
            release.set()
            time.sleep(.02)
            _, final = request("GET", f"{path}/{job['id']}")
            self.assertEqual(final["state"], "stopped")
            self.assertEqual(final["content"], "")

    def test_real_chat_pipeline_saves_answer_without_client_stream(self):
        path = f"/api/chats/{self.chat_id}/generations"
        patches = {
            "apollo_music_action_requested": lambda *_a, **_k: False,
            "apollo_automation_chat_reply": lambda *_a, **_k: None,
            "apollo_task_chat": lambda *_a, **_k: None,
            "apollo_calendar_chat": lambda *_a, **_k: None,
            "apollo_plan_turn": lambda *_a, **_k: {"intent": "general_knowledge", "primary_domain": "general", "planning_mode": "local"},
            "apollo_fetch_planned_context": lambda *_a, **_k: {},
            "apollo_should_reply_semantically": lambda *_a, **_k: True,
            "stream_hermes": lambda _messages: iter(["A real ", "answer."]),
            "generate_chat_title": lambda _history: "Test chat",
        }
        with mock.patch.multiple(server, **patches):
            status, started = request("POST", path, {
                "request_id": str(uuid.uuid4()), "content": "What is a simple fact?",
            }, {"X-Apollo-Request": "chat-generation"})
            self.assertEqual(status, 202)
            for _ in range(200):
                _, job = request("GET", f"{path}/{started['id']}")
                if job["state"] != "running": break
                time.sleep(.01)
        self.assertEqual(job["state"], "complete", job.get("error"))
        self.assertEqual(job["message"]["content"], "A real answer.")
        conn = server.db()
        try:
            rows = conn.execute("SELECT role,content FROM messages WHERE chat_id=? ORDER BY id", (self.chat_id,)).fetchall()
            self.assertEqual([(row["role"], row["content"]) for row in rows],
                             [("user", "What is a simple fact?"), ("assistant", "A real answer.")])
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
