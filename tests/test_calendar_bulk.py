import ast
import json
import re
import unittest
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


SERVER = Path(__file__).resolve().parents[1] / "server.py"


class GoogleCalendarReadOnlyError(RuntimeError):
    pass


def load_function(name, namespace):
    tree = ast.parse(SERVER.read_text())
    node = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == name
    )
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SERVER), "exec"), namespace)
    return namespace[name]


def event(event_id, title, start, end, zone="America/Monterrey"):
    return {
        "id": event_id,
        "summary": title,
        "start": {"dateTime": start, "timeZone": zone},
        "end": {"dateTime": end, "timeZone": zone},
        "location": "Campus",
        "description": "School schedule",
    }


class CalendarBulkTests(unittest.TestCase):
    def base_namespace(self, **extra):
        namespace = {
            "datetime": datetime,
            "timedelta": timedelta,
            "timezone": timezone,
            "ZoneInfo": ZoneInfo,
            "GoogleCalendarReadOnlyError": GoogleCalendarReadOnlyError,
        }
        namespace.update(extra)
        return namespace

    def load_resolver(self, namespace):
        for name in (
            "calendar_event_datetime_in_timezone",
            "calendar_event_date_in_timezone",
            "calendar_event_matches_terms",
            "calendar_batch_terms",
            "calendar_resolve_batch_events",
        ):
            load_function(name, namespace)
        return namespace["calendar_resolve_batch_events"]

    def test_paginates_calendar_search(self):
        first_page = [
            event(
                f"event-{index}",
                "Class",
                "2026-09-07T01:00:00-06:00",
                "2026-09-07T02:00:00-06:00",
            )
            for index in range(100)
        ]
        second_page = [
            event(
                f"event-{index}",
                "Class",
                "2026-09-08T01:00:00-06:00",
                "2026-09-08T02:00:00-06:00",
            )
            for index in range(100, 135)
        ]
        pages = {
            None: {
                "items": first_page,
                "nextPageToken": "page-2",
            },
            "page-2": {
                "items": second_page,
            },
        }

        def request_raw(factory, _operation):
            request = factory("token")
            query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
            page = query.get("pageToken", [None])[0]
            return json.dumps(pages[page]).encode()

        namespace = self.base_namespace(
            urllib=__import__("urllib"),
            json=json,
            google_calendar_request_raw=request_raw,
            GoogleCalendarAuthError=RuntimeError,
            google_calendar_visible_ids=lambda: ["primary"],
        )
        load_function("normalize_google_calendar_event", namespace)
        load_function("fetch_calendar_events", namespace)
        search = load_function("google_calendar_events", namespace)
        found = search(
            start_date="2026-09-07",
            end_date="2026-10-03",
            time_zone="America/Monterrey",
        )

        self.assertEqual(len(found), 135)
        self.assertEqual(found[0]["id"], "event-0")
        self.assertEqual(found[-1]["id"], "event-134")

    def test_searches_the_complete_requested_range(self):
        calls = []
        events = [event("a", "Math", "2026-10-02T01:00:00-06:00", "2026-10-02T02:00:00-06:00")]

        def search(**kwargs):
            calls.append(kwargs)
            return events

        namespace = self.base_namespace(google_calendar_events=search)
        resolve = self.load_resolver(namespace)
        found = resolve(
            {
                "range_start": "2026-09-07",
                "range_end_exclusive": "2026-10-03",
                "event_ids": ["a"],
            },
            time_zone="America/Monterrey",
        )

        self.assertEqual(found, events)
        self.assertEqual(calls[0]["start_date"], "2026-09-07")
        self.assertEqual(calls[0]["end_date"], "2026-10-03")

    def test_fetches_each_page_for_each_visible_calendar(self):
        pages = {
            ("primary", None): {"items": [event("home-1", "Math", "2026-09-07T01:00:00-06:00", "2026-09-07T02:00:00-06:00")], "nextPageToken": "next"},
            ("primary", "next"): {"items": [event("home-2", "History", "2026-09-08T01:00:00-06:00", "2026-09-08T02:00:00-06:00")]},
            ("school@example.com", None): {"items": [event("school-1", "Physics", "2026-09-09T01:00:00-06:00", "2026-09-09T02:00:00-06:00")], "nextPageToken": "next"},
            ("school@example.com", "next"): {"items": [event("school-2", "Chemistry", "2026-09-10T01:00:00-06:00", "2026-09-10T02:00:00-06:00")]},
        }

        def request_raw(factory, _operation):
            request = factory("token")
            parsed = urllib.parse.urlparse(request.full_url)
            calendar_id = urllib.parse.unquote(parsed.path.split("/")[4])
            query = urllib.parse.parse_qs(parsed.query)
            page = query.get("pageToken", [None])[0]
            return json.dumps(pages[(calendar_id, page)]).encode()

        namespace = self.base_namespace(
            urllib=__import__("urllib"),
            json=json,
            google_calendar_request_raw=request_raw,
            GoogleCalendarAuthError=RuntimeError,
        )
        load_function("normalize_google_calendar_event", namespace)
        fetch = load_function("fetch_calendar_events", namespace)
        found = fetch(
            ["primary", "school@example.com"],
            "2026-09-07T06:00:00Z",
            "2026-10-03T06:00:00Z",
        )

        self.assertEqual(len(found), 4)
        self.assertEqual(
            {(item["calendarId"], item["id"]) for item in found},
            {("primary", "home-1"), ("primary", "home-2"), ("school@example.com", "school-1"), ("school@example.com", "school-2")},
        )

    def test_calendar_wrapper_uses_all_visible_calendars(self):
        captured = {}
        namespace = self.base_namespace(
            google_calendar_visible_ids=lambda: ["primary", "school@example.com"],
            fetch_calendar_events=lambda calendar_ids, *args, **kwargs: captured.setdefault("calendar_ids", calendar_ids) or [],
        )
        search = load_function("google_calendar_events", namespace)
        search(
            start_date="2026-09-07",
            end_date="2026-10-03",
            time_zone="America/Monterrey",
        )
        self.assertEqual(captured["calendar_ids"], ["primary", "school@example.com"])

    def test_second_page_failure_reports_retrieval_error(self):
        def request_raw(factory, _operation):
            request = factory("token")
            query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
            if query.get("pageToken"):
                raise RuntimeError("503 upstream unavailable")
            return json.dumps({"items": [], "nextPageToken": "page-2"}).encode()

        namespace = self.base_namespace(
            urllib=__import__("urllib"),
            json=json,
            google_calendar_request_raw=request_raw,
            GoogleCalendarAuthError=type("AuthError", (RuntimeError,), {}),
        )
        load_function("normalize_google_calendar_event", namespace)
        fetch = load_function("fetch_calendar_events", namespace)
        with self.assertRaisesRegex(RuntimeError, "Google Calendar retrieval failed.*503"):
            fetch(["primary"], "2026-09-07T06:00:00Z", "2026-10-03T06:00:00Z")

    def test_calendar_context_does_not_truncate_at_one_hundred_events(self):
        events = [
            event(
                f"event-{index}",
                "Class",
                "2026-09-07T01:00:00-06:00",
                "2026-09-07T02:00:00-06:00",
            )
            for index in range(135)
        ]
        namespace = self.base_namespace(google_calendar_events=lambda **_kwargs: events)
        context = load_function("apollo_context_calendar", namespace)
        self.assertEqual(len(context(30)), 135)

    def test_before_october_third_excludes_october_third(self):
        events = [
            event("sep", "Math", "2026-09-07T01:00:00-06:00", "2026-09-07T02:00:00-06:00"),
            event("oct2", "Math", "2026-10-02T01:00:00-06:00", "2026-10-02T02:00:00-06:00"),
            event("oct3", "Math", "2026-10-03T01:00:00-06:00", "2026-10-03T02:00:00-06:00"),
        ]
        namespace = self.base_namespace(google_calendar_events=lambda **_kwargs: events)
        resolve = self.load_resolver(namespace)
        found = resolve(
            {
                "range_start": "2026-09-07",
                "range_end_exclusive": "2026-10-03",
                "match_terms": ["math"],
            },
            time_zone="America/Monterrey",
        )

        self.assertEqual([item["id"] for item in found], ["sep", "oct2"])

    def test_event_time_is_converted_from_its_google_timezone_to_user_timezone(self):
        namespace = self.base_namespace()
        convert = load_function("calendar_event_datetime_in_timezone", namespace)
        source_event = event(
            "math", "Math class",
            "2026-09-07T01:00:00", "2026-09-07T02:00:00",
            "America/Monterrey",
        )

        converted = convert(source_event, "Europe/Paris")

        self.assertEqual(converted.isoformat(), "2026-09-07T09:00:00+02:00")

    def test_event_time_with_offset_is_converted_to_user_timezone(self):
        namespace = self.base_namespace()
        convert = load_function("calendar_event_datetime_in_timezone", namespace)
        converted = convert(
            event(
                "math", "Math class",
                "2026-09-07T01:00:00-06:00", "2026-09-07T02:00:00-06:00",
                "America/Monterrey",
            ),
            "Europe/Paris",
        )

        self.assertEqual(converted.isoformat(), "2026-09-07T09:00:00+02:00")

    def test_non_class_events_are_untouched(self):
        namespace = self.base_namespace()
        matches = load_function("calendar_event_matches_terms", namespace)
        self.assertTrue(matches(event("class", "Math class", "2026-09-07T01:00:00-06:00", "2026-09-07T02:00:00-06:00"), ["class"]))
        dinner = event("dinner", "Dinner", "2026-09-07T19:00:00-06:00", "2026-09-07T20:00:00-06:00")
        dinner["description"] = "With friends"
        self.assertFalse(matches(dinner, ["class", "school"]))

    def test_multiple_independent_events_update_in_one_batch(self):
        updates = []

        def update(event_id, payload, scope, calendar_id=None):
            updates.append((event_id, payload, scope))
            return {"id": event_id, "summary": event_id}

        namespace = self.base_namespace(google_calendar_update_event=update)
        load_function("calendar_shift_event_payload", namespace)
        batch = load_function("batch_update_calendar_events", namespace)
        result = batch(
            [
                event("math", "Math", "2026-09-07T01:00:00-06:00", "2026-09-07T02:00:00-06:00"),
                event("history", "History", "2026-09-08T05:00:00-06:00", "2026-09-08T06:00:00-06:00"),
            ],
            {"type": "shift_hours", "hours": 8},
        )

        self.assertEqual(len(result["updated"]), 2)
        self.assertEqual([row[0] for row in updates], ["math", "history"])

    def test_batch_uses_single_scope_not_recurring_series(self):
        scopes = []
        namespace = self.base_namespace(
            google_calendar_update_event=lambda _id, _payload, scope, calendar_id=None: scopes.append(scope) or {"id": _id},
        )
        load_function("calendar_shift_event_payload", namespace)
        batch = load_function("batch_update_calendar_events", namespace)
        batch(
            [event("one", "Math", "2026-09-07T01:00:00-06:00", "2026-09-07T02:00:00-06:00")],
            {"type": "shift_hours", "hours": 8},
        )
        self.assertEqual(scopes, ["single"])

    def test_batch_update_keeps_the_event_calendar_id(self):
        calendar_ids = []
        namespace = self.base_namespace(
            google_calendar_update_event=lambda _id, _payload, scope, calendar_id=None: calendar_ids.append(calendar_id) or {"id": _id, "scope": scope},
        )
        load_function("calendar_shift_event_payload", namespace)
        batch = load_function("batch_update_calendar_events", namespace)
        school_event = event("chemistry", "Chemistry", "2026-09-07T01:00:00-06:00", "2026-09-07T02:00:00-06:00")
        school_event["calendarId"] = "school@example.com"
        batch([school_event], {"type": "shift_hours", "hours": 8})
        self.assertEqual(calendar_ids, ["school@example.com"])

    def test_shift_moves_start_eight_hours(self):
        namespace = self.base_namespace()
        payload = load_function("calendar_shift_event_payload", namespace)(
            event("one", "Math", "2026-09-07T01:00:00-06:00", "2026-09-07T02:00:00-06:00"),
            8,
        )
        self.assertEqual(payload["start"], "2026-09-07T09:00:00-06:00")

    def test_shift_moves_end_and_preserves_duration(self):
        namespace = self.base_namespace()
        shift = load_function("calendar_shift_event_payload", namespace)
        original = event("one", "Math", "2026-09-07T01:00:00-06:00", "2026-09-07T02:30:00-06:00")
        payload = shift(original, 8)
        original_duration = datetime.fromisoformat(original["end"]["dateTime"]) - datetime.fromisoformat(original["start"]["dateTime"])
        shifted_duration = datetime.fromisoformat(payload["end"]) - datetime.fromisoformat(payload["start"])
        self.assertEqual(payload["end"], "2026-09-07T10:30:00-06:00")
        self.assertEqual(shifted_duration, original_duration)

    def test_shift_is_timezone_aware_across_dst(self):
        namespace = self.base_namespace()
        shift = load_function("calendar_shift_event_payload", namespace)
        payload = shift(
            event(
                "dst",
                "Math",
                "2026-03-29T00:30:00+01:00",
                "2026-03-29T01:30:00+01:00",
                "Europe/Paris",
            ),
            8,
        )
        start = datetime.fromisoformat(payload["start"])
        end = datetime.fromisoformat(payload["end"])
        self.assertEqual(end.astimezone(timezone.utc) - start.astimezone(timezone.utc), timedelta(hours=1))
        self.assertEqual(start.hour, 9)

    def test_partial_batch_failure_continues_remaining_updates(self):
        def update(event_id, _payload, scope, calendar_id=None):
            if event_id == "broken":
                raise RuntimeError("authorization error")
            return {"id": event_id, "summary": event_id, "scope": scope}

        namespace = self.base_namespace(google_calendar_update_event=update)
        load_function("calendar_shift_event_payload", namespace)
        batch = load_function("batch_update_calendar_events", namespace)
        result = batch(
            [
                event("first", "Math", "2026-09-07T01:00:00-06:00", "2026-09-07T02:00:00-06:00"),
                event("broken", "History", "2026-09-08T01:00:00-06:00", "2026-09-08T02:00:00-06:00"),
                event("last", "Science", "2026-09-09T01:00:00-06:00", "2026-09-09T02:00:00-06:00"),
            ],
            {"type": "shift_hours", "hours": 8},
        )
        self.assertEqual([item["id"] for item in result["updated"]], ["first", "last"])
        self.assertEqual(result["failed"][0]["id"], "broken")

    def test_batch_updates_all_matches_across_a_pagination_boundary(self):
        events = [
            event(
                f"class-{index}",
                "Math class",
                "2026-09-28T01:00:00-06:00",
                "2026-09-28T02:00:00-06:00",
            )
            if index >= 95 else event(
                f"other-{index}",
                "Unrelated event",
                "2026-09-15T01:00:00-06:00",
                "2026-09-15T02:00:00-06:00",
            )
            for index in range(120)
        ]
        updates = []
        namespace = self.base_namespace(
            google_calendar_events=lambda **_kwargs: events,
            google_calendar_update_event=lambda event_id, _payload, scope, calendar_id=None: updates.append(event_id) or {"id": event_id},
        )
        resolve = self.load_resolver(namespace)
        load_function("calendar_shift_event_payload", namespace)
        batch = load_function("batch_update_calendar_events", namespace)
        matches = resolve(
            {
                "range_start": "2026-09-07",
                "range_end_exclusive": "2026-10-03",
                "match_terms": ["class"],
            },
            time_zone="America/Monterrey",
        )
        result = batch(matches, {"type": "shift_hours", "hours": 8})

        self.assertEqual(len(matches), 25)
        self.assertEqual(len(result["updated"]), 25)
        self.assertEqual(updates, [f"class-{index}" for index in range(95, 120)])

    def test_exact_paris_class_correction_fetches_page_two_and_updates_every_match(self):
        """Reproduces the reported September 28–October 2 failure end-to-end."""
        first_page = []
        for index in range(100):
            item = event(
                f"personal-{index}", "Personal event",
                "2026-09-15T01:00:00-06:00", "2026-09-15T02:00:00-06:00",
            )
            item["description"] = "Personal calendar item"
            item["location"] = "Home"
            first_page.append(item)

        dates = ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02"]
        second_page = [
            event(
                f"class-{index}", "Math class",
                f"{dates[index % len(dates)]}T01:00:00-06:00",
                f"{dates[index % len(dates)]}T02:00:00-06:00",
            )
            for index in range(27)
        ]
        pages = {
            None: {"items": first_page, "nextPageToken": "page-2"},
            "page-2": {"items": second_page},
        }
        updates = []

        def request_raw(factory, _operation):
            request = factory("token")
            query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
            return json.dumps(pages[query.get("pageToken", [None])[0]]).encode()

        namespace = self.base_namespace(
            urllib=__import__("urllib"),
            json=json,
            re=re,
            google_calendar_request_raw=request_raw,
            GoogleCalendarAuthError=RuntimeError,
            google_calendar_visible_ids=lambda: ["primary"],
            calendar_context_now=lambda _context: ("2026-09-07T09:00:00+02:00", "Europe/Paris"),
            google_calendar_update_event=lambda event_id, _payload, scope, calendar_id=None: updates.append(event_id) or {"id": event_id},
        )
        for name in (
            "normalize_google_calendar_event",
            "fetch_calendar_events",
            "google_calendar_events",
            "calendar_server_request_date",
            "calendar_server_dates_in_text",
            "calendar_server_batch_action",
            "calendar_event_datetime_in_timezone",
            "calendar_event_date_in_timezone",
            "calendar_event_matches_terms",
            "calendar_batch_terms",
            "calendar_resolve_batch_events",
            "calendar_shift_event_payload",
            "batch_update_calendar_events",
        ):
            load_function(name, namespace)

        action = namespace["calendar_server_batch_action"](
            "change all my classes before leaving for Paris +8 hours to Europe time",
            conversation_context=(
                "I leave for Paris on October 3, 2026. I already confirmed this."
            ),
            client_context={"time_zone": "Europe/Paris"},
        )
        self.assertTrue(action["approved"])
        self.assertEqual(action["range_start"], "2026-09-07")
        self.assertEqual(action["range_end_exclusive"], "2026-10-03")

        matches = namespace["calendar_resolve_batch_events"](
            action, time_zone="Europe/Paris"
        )
        result = namespace["batch_update_calendar_events"](
            matches, action["transformation"], "Europe/Paris"
        )

        self.assertEqual(len(matches), 27)
        self.assertEqual(len(result["updated"]), 27)
        self.assertEqual(set(updates), {f"class-{index}" for index in range(27)})
        self.assertTrue(any("2026-10-02" in item["start"]["dateTime"] for item in matches))

    def test_preapproved_server_batch_does_not_request_confirmation_again(self):
        saved = []
        namespace = self.base_namespace(
            calendar_is_batch_action=lambda _action: True,
            calendar_context_now=lambda _context: ("now", "Europe/Paris"),
            calendar_resolve_batch_events=lambda *_args, **_kwargs: [
                event("math", "Math class", "2026-09-28T01:00:00-06:00", "2026-09-28T02:00:00-06:00")
            ],
            calendar_pending_set=lambda *args: saved.append(args),
            calendar_execute_pending=lambda pending, chat_id=None: "Done — shifted 1 class event before 2026-10-03 8 hours later.",
            GoogleCalendarAuthError=RuntimeError,
        )
        prepare = load_function("calendar_prepare_action", namespace)
        reply = prepare(
            3,
            {
                "intent": "update",
                "action": {
                    "event_filter": {"type": "class", "terms": ["class"]},
                    "transformation": {"type": "shift_hours", "hours": 8},
                    "range_start": "2026-09-07",
                    "range_end_exclusive": "2026-10-03",
                    "approved": True,
                },
                "_events": [],
            },
            client_context={"time_zone": "Europe/Paris"},
        )
        self.assertTrue(reply.startswith("Done"))
        self.assertEqual(saved, [])

    def test_exact_class_correction_bypasses_hermes_capability_guess(self):
        namespace = self.base_namespace(
            re=re,
            calendar_context_now=lambda _context: ("2026-09-07T09:00:00+02:00", "Europe/Paris"),
            calendar_last_event_get=lambda _chat_id: None,
            calendar_pending_get=lambda _chat_id: None,
            calendar_handle_pending=lambda *_args: None,
            calendar_is_batch_action=lambda _action: True,
            calendar_resolve_batch_events=lambda *_args, **_kwargs: [
                event("math", "Math class", "2026-09-28T01:00:00-06:00", "2026-09-28T02:00:00-06:00")
            ],
            calendar_execute_pending=lambda _pending, chat_id=None: "Done — shifted 1 class event before 2026-10-03 8 hours later.",
            calendar_pending_set=lambda *_args: self.fail("should not ask again"),
            GoogleCalendarAuthError=RuntimeError,
        )
        for name in (
            "calendar_server_request_date",
            "calendar_server_dates_in_text",
            "calendar_server_batch_action",
            "calendar_prepare_action",
            "apollo_calendar_chat",
        ):
            load_function(name, namespace)

        reply = namespace["apollo_calendar_chat"](
            11,
            "change all my classes before leaving to paris +8 hours to be in europe time",
            {"surface": "calendar", "time_zone": "Europe/Paris"},
            conversation_context="Paris departure: October 3, 2026. I approved it.",
        )

        self.assertTrue(reply.startswith("Done"))

    def test_timezone_phrase_alone_never_creates_a_shift_action(self):
        namespace = self.base_namespace(
            re=re,
            calendar_context_now=lambda _context: ("2026-09-07T09:00:00+02:00", "Europe/Paris"),
        )
        for name in (
            "calendar_server_request_date",
            "calendar_server_dates_in_text",
            "calendar_server_batch_action",
        ):
            load_function(name, namespace)

        action = namespace["calendar_server_batch_action"](
            "change all my classes before leaving for Paris to Europe time",
            conversation_context="Paris departure: October 3, 2026.",
            client_context={"time_zone": "Europe/Paris"},
        )

        self.assertIsNone(action)

    def test_partial_batch_summary_is_accurate(self):
        namespace = self.base_namespace()
        summary = load_function("calendar_batch_result_summary", namespace)(
            {"updated": [{"id": "one"}], "failed": [{"title": "History", "error": "authorization error"}]},
            {"type": "shift_hours", "hours": 8},
            "2026-10-03",
        )
        self.assertIn("shifted 1 class event before 2026-10-03 8 hours later", summary)
        self.assertIn("1 event could not be changed", summary)
        self.assertIn("History", summary)

    def test_read_only_subscribed_calendar_is_not_reported_as_disconnected(self):
        namespace = self.base_namespace()
        summary = load_function("calendar_batch_result_summary", namespace)(
            {
                "updated": [],
                "failed": [{
                    "title": "Canvas course",
                    "error": "This subscribed calendar is read-only",
                    "read_only": True,
                }],
            },
            {"type": "shift_hours", "hours": 8},
            "2026-10-03",
        )

        self.assertIn("read-only subscribed calendar", summary)
        self.assertIn("connection remains active", summary)

    def test_bulk_prepare_stores_one_confirmation_without_series_scope(self):
        saved = []
        namespace = self.base_namespace(
            calendar_is_batch_action=lambda _action: True,
            calendar_context_now=lambda _context: ("now", "Europe/Paris"),
            calendar_resolve_batch_events=lambda *_args, **_kwargs: [event("math", "Math", "2026-09-07T01:00:00-06:00", "2026-09-07T02:00:00-06:00")],
            calendar_pending_set=lambda *args: saved.append(args),
        )
        prepare = load_function("calendar_prepare_action", namespace)
        reply = prepare(
            3,
            {"intent": "update", "action": {"event_ids": ["math"], "transformation": {"type": "shift_hours", "hours": 8}, "range_start": "2026-09-07", "range_end_exclusive": "2026-10-03"}, "_events": []},
            client_context={"time_zone": "Europe/Paris"},
        )
        self.assertIn("Shift 1", reply)
        self.assertEqual(saved[0][1]["stage"], "confirm")
        self.assertNotIn("scope", saved[0][1]["action"])

    def test_confirmation_executes_the_pending_batch(self):
        cleared = []
        executed = []
        pending = {"stage": "confirm", "intent": "update", "action": {"batch_events": []}}
        namespace = self.base_namespace(
            calendar_pending_get=lambda _chat_id: pending,
            calendar_interpret_pending_reply=lambda *_args: {"decision": "confirm"},
            calendar_execute_pending=lambda action, chat_id: executed.append((action, chat_id)) or "Done",
            calendar_pending_clear=lambda chat_id: cleared.append(chat_id),
        )
        handle = load_function("calendar_handle_pending", namespace)
        self.assertEqual(handle(9, "yes, do it"), "Done")
        self.assertEqual(executed[0][1], 9)
        self.assertEqual(cleared, [9])

    def test_clarification_retains_resolved_conversation_facts(self):
        pending = {}
        seen = []

        def interpret(message, *_args, **_kwargs):
            seen.append(message)
            if len(seen) == 1:
                return {"intent": "clarify", "reply": "How many hours?"}
            return {"intent": "update", "action": {"event_id": "math"}}

        namespace = self.base_namespace(
            calendar_last_event_get=lambda _chat_id: None,
            calendar_pending_get=lambda _chat_id: pending or None,
            calendar_handle_pending=lambda *_args: None,
            calendar_maybe_related=lambda *_args, **_kwargs: True,
            calendar_interpret_message=interpret,
            calendar_pending_set=lambda _chat_id, value: pending.update(value),
            calendar_pending_clear=lambda _chat_id: pending.clear(),
            calendar_prepare_action=lambda *_args, **_kwargs: "ready",
        )
        chat = load_function("apollo_calendar_chat", namespace)
        chat(
            4,
            "Change all my classes before leaving for Paris",
            {"surface": "calendar"},
            conversation_context="Paris begins October 3. The class times need Europe time.",
        )
        reply = chat(4, "shift them eight hours later", {"surface": "calendar"})

        self.assertEqual(reply, "ready")
        self.assertIn("Paris begins October 3", seen[1])
        self.assertIn("shift them eight hours later", seen[1])

    def test_mobile_and_desktop_share_confirmed_calendar_execution(self):
        for surface in ("mobile", "desktop"):
            namespace = self.base_namespace(
                calendar_last_event_get=lambda _chat_id: None,
                calendar_pending_get=lambda _chat_id: {"stage": "confirm"},
                calendar_handle_pending=lambda _chat_id, _message: f"Done on {surface}",
            )
            chat = load_function("apollo_calendar_chat", namespace)
            self.assertEqual(chat(4, "yes", {"surface": surface}), f"Done on {surface}")

    def test_existing_single_event_update_execution_remains_supported(self):
        namespace = self.base_namespace(
            google_calendar_update_event=lambda event_id, payload, scope, series_id, calendar_id=None: {"id": event_id, "summary": "Math", "payload": payload, "scope": scope, "series": series_id, "calendar_id": calendar_id},
            calendar_last_event_set=lambda *_args: None,
        )
        execute = load_function("calendar_execute_pending", namespace)
        reply = execute({"intent": "update", "action": {"event_id": "math", "scope": "single", "start": "2026-09-07T09:00"}})
        self.assertEqual(reply, 'Done — updated “Math”.')
