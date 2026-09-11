import ast
import importlib.util
import json
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


SERVER = Path(__file__).resolve().parents[1] / "server.py"


def load_function(name, namespace):
    tree = ast.parse(SERVER.read_text())
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SERVER), "exec"), namespace)
    return namespace[name]


class CalendarSubscriptionParsingTests(unittest.TestCase):
    def parser(self):
        namespace = {
            "datetime": datetime,
            "timedelta": timedelta,
            "timezone": timezone,
            "ZoneInfo": ZoneInfo,
            "json": json,
            "re": re,
        }
        for name in ("_ical_unescape", "_ical_properties", "_ical_value", "_ical_datetime", "_ical_end", "_ical_completion_state", "_ical_event_records"):
            load_function(name, namespace)
        return namespace["_ical_event_records"]

    def merger(self):
        namespace = {"json": json, "re": re, "datetime": datetime, "timezone": timezone}
        load_function("_calendar_event_equivalence_key", namespace)
        return load_function("merge_calendar_event_sources", namespace)

    def test_preserves_canvas_fields_and_all_day_dates(self):
        feed = b"""BEGIN:VCALENDAR\r
BEGIN:VEVENT\r
UID:course-42-assignment-7\r
SUMMARY:Essay due\r
DTSTART;VALUE=DATE:20260915\r
DUE;VALUE=DATE:20260915\r
DESCRIPTION:Submit the final essay\\nhttps://canvas.example/courses/42/assignments/7\r
X-CANVAS-CALENDAR-NAME:History 101\r
END:VEVENT\r
END:VCALENDAR\r
"""
        records = self.parser()(feed, "Europe/Paris")
        self.assertEqual(len(records), 1)
        event = records[0]
        self.assertEqual(event["event_key"], "course-42-assignment-7")
        self.assertEqual(event["start"], {"date": "2026-09-15"})
        self.assertEqual(event["end"], {"date": "2026-09-16"})
        self.assertEqual(event["due"], {"date": "2026-09-15"})
        self.assertEqual(event["calendar_name"], "History 101")
        self.assertEqual(event["html_link"], "https://canvas.example/courses/42/assignments/7")

    def test_converts_tzid_events_to_an_absolute_time(self):
        feed = b"""BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:lecture-1\nSUMMARY:Lecture\nDTSTART;TZID=America/New_York:20261103T090000\nDTEND;TZID=America/New_York:20261103T100000\nEND:VEVENT\nEND:VCALENDAR\n"""
        event = self.parser()(feed, "Europe/Paris")[0]
        self.assertEqual(event["start"]["timeZone"], "America/New_York")
        self.assertEqual(event["start"]["dateTime"], "2026-11-03T09:00:00-05:00")
        self.assertEqual(event["end"]["dateTime"], "2026-11-03T10:00:00-05:00")

    def test_google_import_of_canvas_is_excluded_without_hiding_google_events(self):
        start, end = {"dateTime": "2026-09-10T06:59:00Z"}, {"dateTime": "2026-09-10T06:59:00Z"}
        google_import = {
            "id": "google-copy", "calendarId": "feed@import.calendar.google.com",
            "summary": "Assignment", "start": start, "end": end,
        }
        normal_google = {
            "id": "class", "calendarId": "primary",
            "summary": "Class", "start": start, "end": end,
        }
        namespace = {"json": json, "re": re, "datetime": datetime, "timezone": timezone}
        load_function("_calendar_event_equivalence_key", namespace)
        canvas_key = namespace["_calendar_event_equivalence_key"](google_import)
        merged = self.merger()([normal_google, google_import], [], {canvas_key})
        self.assertEqual(merged, [normal_google])

    def test_google_import_with_canvas_uid_is_excluded_even_after_due_date_changes(self):
        google_import = {
            "id": "google-copy", "calendarId": "feed@import.calendar.google.com",
            "iCalUID": "assignment-42", "summary": "Essay",
            "start": {"dateTime": "2026-09-16T21:59:00Z"},
            "end": {"dateTime": "2026-09-16T21:59:00Z"},
        }
        normal_google = {
            "id": "class", "calendarId": "primary", "summary": "Class",
            "start": {"dateTime": "2026-09-14T09:00:00Z"},
            "end": {"dateTime": "2026-09-14T10:00:00Z"},
        }
        self.assertEqual(
            self.merger()([normal_google, google_import], [], set(), {"assignment-42"}),
            [normal_google],
        )

    def test_canvas_dedupe_never_removes_normal_google_events(self):
        """Only the imported Google Canvas feed may yield to Apollo's copy."""
        start = {"dateTime": "2026-09-10T06:59:00Z"}
        end = {"dateTime": "2026-09-10T07:59:00Z"}
        canvas = {
            "id": "ical:1:assignment", "source": "canvas",
            "summary": "Assignment", "start": start, "end": end,
        }
        normal_google_event = {
            "id": "lecture", "calendarId": "primary", "summary": "Lecture",
            "start": start, "end": end,
        }
        same_named_normal_event = {
            "id": "personal-assignment", "calendarId": "primary",
            "summary": "Assignment", "start": start, "end": end,
        }
        imported_canvas_copy = {
            "id": "import-copy", "calendarId": "canvas@import.calendar.google.com",
            "summary": "Assignment", "start": start, "end": end,
        }

        self.assertEqual(
            self.merger()(
                [normal_google_event, same_named_normal_event, imported_canvas_copy],
                [canvas],
            ),
            [normal_google_event, same_named_normal_event, canvas],
        )

    def test_google_event_visible_through_primary_and_account_is_returned_once(self):
        event = {
            "id": "same-google-event", "summary": "Class",
            "start": {"dateTime": "2026-09-10T09:00:00+02:00"},
            "end": {"dateTime": "2026-09-10T10:00:00+02:00"},
        }
        duplicate = {**event, "calendarId": "account@example.com"}
        original = {**event, "calendarId": "primary"}
        self.assertEqual(self.merger()([original, duplicate], []), [original])

    def test_completion_requires_an_explicit_canvas_property(self):
        parser = self.parser()
        no_completion = parser(b"""BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:a\nSUMMARY:Assignment\nSTATUS:CONFIRMED\nDTSTART;VALUE=DATE:20260915\nEND:VEVENT\nEND:VCALENDAR\n""")[0]
        completed = parser(b"""BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:b\nSUMMARY:Submitted assignment\nX-CANVAS-SUBMISSION-STATUS:submitted\nDTSTART;VALUE=DATE:20260915\nEND:VEVENT\nEND:VCALENDAR\n""")[0]
        self.assertEqual(no_completion["completion_state"], "unknown")
        self.assertEqual(completed["completion_state"], "completed")
        self.assertEqual(completed["completion_source"], "X-CANVAS-SUBMISSION-STATUS")

    def test_repeated_sync_upserts_then_removes_and_reactivates_one_uid(self):
        with tempfile.TemporaryDirectory() as directory:
            source = SERVER.read_text().replace(
                'BASE_DIR = Path("/root/Apollo")',
                f'BASE_DIR = Path({directory!r})',
                1,
            )
            module_path = Path(directory) / "isolated_server.py"
            module_path.write_text(source)
            spec = importlib.util.spec_from_file_location("isolated_apollo_server", module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.init_db()

            feed = [b"""BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:assignment-42\nSUMMARY:Essay\nDTSTART;VALUE=DATE:20260915\nDUE;VALUE=DATE:20260915\nDESCRIPTION:Submit it\\nhttps://canvas.example/courses/42/assignments/42\nX-CANVAS-CALENDAR-NAME:History 101\nEND:VEVENT\nEND:VCALENDAR\n"""]

            class Response:
                def __init__(self, payload):
                    self.payload = payload
                def read(self, _size=None):
                    return self.payload
                def __enter__(self):
                    return self
                def __exit__(self, *_args):
                    return False

            original_open = module.urllib.request.urlopen
            module.urllib.request.urlopen = lambda *_args, **_kwargs: Response(feed[0])
            try:
                status = module.calendar_subscription_connect("https://canvas.example/calendar.ics")
                self.assertTrue(status["connected"])
                for _ in range(3):
                    module.calendar_subscription_sync(1, force=True)
                connection = module.db()
                rows = connection.execute("SELECT id, active FROM calendar_subscription_events WHERE uid = ?", ("assignment-42",)).fetchall()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["active"], 1)
                record_id = rows[0]["id"]
                task = connection.execute("SELECT * FROM tasks WHERE external_id = ?", ("canvas:assignment-42",)).fetchone()
                self.assertEqual(task["title"], "Essay")
                self.assertEqual(task["due_at"], "2026-09-15")
                self.assertEqual(task["source"], "canvas")
                self.assertEqual(task["active"], 1)
                task_id = task["id"]
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM tasks WHERE external_id = ?", ("canvas:assignment-42",)).fetchone()[0], 1)
                canvas_task = next(item for item in module.get_tasks() if item["id"] == task_id)
                self.assertEqual(canvas_task["sourceLabel"], "Canvas")
                self.assertEqual(canvas_task["courseName"], "History 101")
                self.assertEqual(canvas_task["htmlLink"], "https://canvas.example/courses/42/assignments/42")

                self.assertEqual(
                    module._canvas_task_course_name({"calendar_name": None, "summary": "Essay [PM5010.605]"}),
                    "PM5010.605",
                )

                calendar_events = module.calendar_subscription_events(
                    datetime(2026, 9, 14, tzinfo=timezone.utc),
                    datetime(2026, 9, 17, tzinfo=timezone.utc),
                    "UTC",
                )
                self.assertEqual(calendar_events, [])
                _canvas_keys, canvas_uids = module.canvas_subscription_event_keys(
                    datetime(2026, 9, 14, tzinfo=timezone.utc),
                    datetime(2026, 9, 17, tzinfo=timezone.utc),
                    "UTC",
                )
                self.assertEqual(canvas_uids, {"assignment-42"})

                feed[0] = b"""BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:assignment-42\nSUMMARY:Essay revised\nDTSTART;VALUE=DATE:20260916\nDUE;VALUE=DATE:20260916\nX-CANVAS-SUBMISSION-STATUS:submitted\nEND:VEVENT\nEND:VCALENDAR\n"""
                module.calendar_subscription_sync(1, force=True)
                updated_task = connection.execute("SELECT * FROM tasks WHERE external_id = ?", ("canvas:assignment-42",)).fetchone()
                self.assertEqual(updated_task["id"], task_id)
                self.assertEqual(updated_task["title"], "Essay revised")
                self.assertEqual(updated_task["due_at"], "2026-09-16")
                self.assertEqual(updated_task["completed"], 1)

                feed[0] = b"BEGIN:VCALENDAR\nEND:VCALENDAR\n"
                module.calendar_subscription_sync(1, force=True)
                self.assertEqual(connection.execute("SELECT active FROM calendar_subscription_events WHERE id = ?", (record_id,)).fetchone()["active"], 0)
                self.assertEqual(connection.execute("SELECT active FROM tasks WHERE id = ?", (task_id,)).fetchone()["active"], 0)

                feed[0] = b"""BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:assignment-42\nSUMMARY:Essay revised\nDTSTART;VALUE=DATE:20260916\nDUE;VALUE=DATE:20260916\nEND:VEVENT\nEND:VCALENDAR\n"""
                module.calendar_subscription_sync(1, force=True)
                restored = connection.execute("SELECT id, active, summary FROM calendar_subscription_events WHERE uid = ?", ("assignment-42",)).fetchone()
                self.assertEqual(restored["id"], record_id)
                self.assertEqual(restored["active"], 1)
                self.assertEqual(restored["summary"], "Essay revised")
                self.assertEqual(connection.execute("SELECT id, active FROM tasks WHERE external_id = ?", ("canvas:assignment-42",)).fetchone()["id"], task_id)
                self.assertEqual(connection.execute("SELECT active FROM tasks WHERE external_id = ?", ("canvas:assignment-42",)).fetchone()["active"], 1)
                connection.close()
            finally:
                module.urllib.request.urlopen = original_open
