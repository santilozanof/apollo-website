import io
import json
import time
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


_workspace = tempfile.TemporaryDirectory(prefix="apollo-live-research-")
_old_base = os.environ.get("APOLLO_BASE_DIR")
os.environ["APOLLO_BASE_DIR"] = _workspace.name
import server  # noqa: E402
import apollo_live_research as live  # noqa: E402
if _old_base is None:
    os.environ.pop("APOLLO_BASE_DIR", None)
else:
    os.environ["APOLLO_BASE_DIR"] = _old_base


def request(method, path, payload=None):
    handler = object.__new__(server.ApolloHandler)
    body = json.dumps(payload).encode() if payload is not None else b""
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


def events(raw):
    return [json.loads(line[5:].strip()) for line in raw.decode().splitlines()
            if line.startswith("data:")]


def response(answer="As of 2026-10-19 in Europe/Zurich: Early prelims: not published. Prelims: not published. Main card: [[UTC:2026-10-25T00:00:00Z]]. [UFC](https://www.ufc.com/events)",
             output="Upcoming UFC card: https://www.ufc.com/events"):
    return {"status": "completed", "output": [
        {"type": "function_call", "name": "web_search", "call_id": "c1", "status": "completed"},
        {"type": "function_call_output", "call_id": "c1", "status": "completed", "output": output},
        {"type": "message", "role": "assistant", "content": [
            {"type": "output_text", "text": answer}]},
    ]}


class FakeHTTP:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def read(self):
        return json.dumps(self.payload).encode()


class LiveResearchPipelineTests(unittest.TestCase):
    def test_wrapped_gateway_results_and_weather_citation_grounding(self):
        tool_data = {'success': True, 'data': {'web': [
            {'url': 'https://example.com/forecast', 'title': 'Tomorrow', 'description': 'Lausanne: 7°C/14°C, light rain.'},
            {'url': 'https://example.com/home', 'title': 'Weather office', 'description': 'Official homepage'},
        ]}}
        wrapped = '<untrusted_tool_result source="web_search">\nExternal data\n' + json.dumps(tool_data) + '\n</untrusted_tool_result>'
        result = response(output=wrapped)
        self.assertFalse(live._weather_numbers_supported(result, '7–14°C. [Weather](https://example.com/home)'))
        self.assertTrue(live._weather_numbers_supported(result, '7–14°C. [Forecast](https://example.com/forecast)'))
        self.assertEqual(live._tool_payload(wrapped), tool_data)

    def test_sourced_followup_uses_context_planner_before_researching_again(self):
        recent = [{'role': 'user', 'content': 'What is the latest stable Python release?'},
                  {'role': 'assistant', 'content': 'Python X, released October 9. [Source](https://python.org)'}]
        self.assertIsNone(live.live_query_kind('When was that version released?', recent))

    def test_connected_personal_sources_never_become_public_google_research(self):
        prompt = "Check my Google Calendar, Canvas assignments, and WHOOP data. Make me a realistic plan for tomorrow based on my commitments and recovery."
        self.assertIsNone(live.live_query_kind(prompt))

    @classmethod
    def setUpClass(cls):
        cls._previous_base_dir = server.BASE_DIR
        cls._previous_db_path = server.DB_PATH
        server.BASE_DIR = Path(_workspace.name)
        server.DB_PATH = server.BASE_DIR / "live-research.db"
        server.init_db()

    @classmethod
    def tearDownClass(cls):
        server.BASE_DIR = cls._previous_base_dir
        server.DB_PATH = cls._previous_db_path

    def setUp(self):
        conn = server.db()
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM chats")
        conn.commit()
        conn.close()

    def chat(self, content, fake_opener):
        status, raw = request("POST", "/api/chats", {})
        self.assertEqual(status, 201)
        chat_id = json.loads(raw)["id"]
        patches = {
            "apollo_plan_turn": lambda *_a, **_k: {"intent": "general_knowledge", "primary_domain": "none"},
            "get_api_key": lambda: "test-key",
            "stream_hermes": lambda *_a: self.fail("live turn bypassed web research"),
            "generate_chat_title": lambda *_a: "Live research",
        }
        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 10, 19, 10, tzinfo=timezone.utc).astimezone(tz)

        with mock.patch.multiple(server, **patches), mock.patch.object(live.urllib.request, "urlopen", fake_opener), mock.patch.object(live, "datetime", FixedDateTime):
            status, raw = request("POST", f"/api/chats/{chat_id}/messages", {
                "content": content,
                "client_context": {"local_time": "2026-10-19T12:00:00+02:00",
                                   "time_zone": "Europe/Zurich", "utc_offset_minutes": 120},
            })
        self.assertEqual(status, 200)
        output = events(raw)
        self.assertEqual(output[-1]["type"], "done")
        self.assertEqual(request("GET", f"/api/chats/{chat_id}")[0], 200)
        return output[-1]["message"]["content"]

    def test_reproduction_and_live_question_matrix_route_through_hermes_web(self):
        questions = [
            "when are the next good ufc fights? lausanne time",
            "bro search them up what?",
            "What's happening in AI today?",
            "What concerts are coming to Lausanne?",
            "Who won the latest UFC event?",
            "What are the next Formula 1 races?",
            "What's the weather tomorrow?",
        ]
        for question in questions:
            with self.subTest(question=question):
                captured = []

                def opener(req, timeout):
                    captured.append((req.full_url, json.loads(req.data)))
                    return FakeHTTP(response())

                answer = self.chat(question, opener)
                self.assertEqual(len(captured), 1)
                self.assertTrue(captured[0][0].endswith("/v1/responses"))
                self.assertEqual(captured[0][1]["model_options"]["enabled_toolsets"], ["web"])
                self.assertIn("Call web_search", captured[0][1]["instructions"])
                self.assertIn("Europe/Zurich", captured[0][1]["instructions"])
                self.assertIn("Sun 25 Oct 2026, 02:00 CEST", answer)
                self.assertIn("https://www.ufc.com/events", answer)

    def test_failed_or_missing_tool_does_not_become_generic_answer(self):
        cases = [
            ({"status": "completed", "output": [{"type": "message", "role": "assistant", "content": [
                {"type": "output_text", "text": "I have no live web access."}]}]}, "did not run web search"),
            (response(output="web_search unavailable: not configured"), "unavailable"),
            (response(output="401 unauthorized"), "authentication"),
            (response(answer="The event is tomorrow.", output="https://www.ufc.com/events"), "verifiable evidence"),
            (response(answer="I don't have live web access. [UFC](https://www.ufc.com/events)"), "verifiable evidence"),
            (response(answer="See [other](https://example.com/card)."), "verifiable evidence"),
        ]
        for payload, expected in cases:
            with self.subTest(expected=expected):
                calls = []

                def opener(req, timeout):
                    calls.append(req)
                    return FakeHTTP(payload)

                answer = self.chat("Who won the latest UFC event?", opener)
                self.assertIn(expected, answer)
                self.assertNotIn("I have no live web access", answer)
                self.assertEqual(len(calls), 1)

    def test_zurich_dst_and_local_date_are_calculated_from_utc(self):
        self.assertEqual(live.localize_utc_markers("[[UTC:2026-10-24T23:00:00Z]]", "Europe/Zurich"),
                         "Sun 25 Oct 2026, 01:00 CEST")
        self.assertEqual(live.localize_utc_markers("[[UTC:2026-10-25T02:00:00Z]]", "Europe/Zurich"),
                         "Sun 25 Oct 2026, 03:00 CET")
        self.assertEqual(live.localize_utc_markers("[[UTC:2026-03-29T01:00:00Z]]", "Europe/Zurich"),
                         "Sun 29 Mar 2026, 03:00 CEST")

    def test_search_transport_failure_reports_request_failure_without_repeating(self):
        calls = []

        def opener(req, timeout):
            calls.append(req)
            raise live.urllib.error.URLError("offline")

        answer = self.chat("What's the weather tomorrow?", opener)
        self.assertIn("request failed", answer)
        self.assertEqual(len(calls), 1)

    def test_gateway_down_has_distinct_explanation(self):
        def opener(req, timeout):
            raise live.urllib.error.URLError(ConnectionRefusedError("refused"))

        answer = self.chat("What's the weather tomorrow?", opener)
        self.assertIn("gateway is not reachable", answer)

    def test_successful_search_survives_optional_extract_failure(self):
        payload = response()
        payload["output"].insert(2, {"type": "function_call", "name": "web_extract", "call_id": "c2"})
        payload["output"].insert(3, {"type": "function_call_output", "call_id": "c2",
                                      "output": '{"results": [{"url": "https://example.com/failed", "content": "", "error": "extraction failed"}]}'})
        status, answer, sources = live._inspect_response(payload)
        self.assertEqual(status, "succeeded")
        self.assertIn("https://www.ufc.com/events", sources)
        self.assertNotIn("https://example.com/failed", sources)

    def test_successful_extract_adds_only_pages_with_content_as_evidence(self):
        payload = response(answer="[Official card](https://www.ufc.com/event/ufc-333)")
        payload["output"].insert(2, {"type": "function_call", "name": "web_extract", "call_id": "c2"})
        payload["output"].insert(3, {"type": "function_call_output", "call_id": "c2",
                                      "output": json.dumps({"results": [
                                          {"url": "https://www.ufc.com/event/ufc-333", "content": "UFC 333 card details", "error": None},
                                          {"url": "https://example.com/failed", "content": "", "error": "blocked"}]})})
        status, _answer, sources = live._inspect_response(payload)
        self.assertEqual(status, "succeeded")
        self.assertIn("https://www.ufc.com/event/ufc-333", sources)
        self.assertNotIn("https://example.com/failed", sources)

    def test_static_conversation_keeps_normal_chat_path(self):
        self.assertIsNone(live.live_query_kind("Explain how a bicycle works"))
        self.assertIsNone(live.live_query_kind("Add my UFC viewing party to my calendar"))
        self.assertIsNone(live.live_query_kind("Play my music"))
        self.assertIsNone(live.live_query_kind("What is my calendar showing for the UFC?"))
        self.assertEqual(live.live_query_kind("What's happening in AI today?"), "current")
        self.assertEqual(live.live_query_kind("What's happening in Lausanne today?"), "events")
        self.assertEqual(live.live_query_kind("Is the cafe open tonight?"), "local")
        self.assertEqual(live.live_query_kind("What's the breaking news in AI?"), "current")
        self.assertEqual(live.live_query_kind("What are the specs of the new phone?"), "current")

    def test_collaboration_origin_uses_dated_source_research(self):
        question = "When did Mike Dean start working with The Weeknd and why?"
        self.assertEqual(live.live_query_kind(question), "research")
        calls = []
        cited = "https://www.grammy.com/artists/mike-dean/2701/"
        source = {"status": "completed", "output": [
            {"type": "function_call", "name": "web_search", "call_id": "search"},
            {"type": "function_call_output", "call_id": "search", "output": json.dumps({
                "success": True, "data": {"web": [{"url": cited,
                    "title": "Mike Dean | GRAMMY.com", "description": "2016 Album of the Year nominee: The Weeknd, Beauty Behind the Madness"}]}})},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text",
                "text": "Their documented collaboration reaches back to 2015's *Beauty Behind the Madness*. "
                "The available credit does not establish why they first connected. "
                f"[Recording Academy]({cited})"}]}
        ]}
        def opener(req, timeout):
            calls.append(json.loads(req.data))
            return FakeHTTP(source)
        answer = self.chat(question, opener)
        self.assertIn("2015", answer)
        self.assertNotIn("2018", answer)
        self.assertIn(cited, answer)
        self.assertEqual(len(calls), 1)
        self.assertIn("dated credits", calls[0]["instructions"])

    def test_gateway_deadline_covers_the_whole_response(self):
        def opener(req, timeout):
            time.sleep(.1)
            return FakeHTTP(response())
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            live._gateway_json(object(), opener, .02)
        self.assertLess(time.monotonic() - started, .08)

    def test_upcoming_sports_requires_a_utc_time_to_localize(self):
        calls = []

        def opener(req, timeout):
            calls.append(req)
            return FakeHTTP(response(answer="Next card [UFC](https://www.ufc.com/events) starts at 8 PM."))

        answer = self.chat("when are the next good ufc fights? lausanne time", opener)
        self.assertIn("verifiable evidence", answer)
        self.assertEqual(len(calls), 1)

    def test_today_news_requires_explicit_as_of_date(self):
        calls = []

        def opener(req, timeout):
            calls.append(req)
            return FakeHTTP(response(answer="AI news [source](https://www.ufc.com/events)."))

        answer = self.chat("What's happening in AI today?", opener)
        self.assertIn("verifiable evidence", answer)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
