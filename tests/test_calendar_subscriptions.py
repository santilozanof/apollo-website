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

    def test_google_import_of_canvas_is_replaced_by_canonical_canvas_event(self):
        start, end = {"dateTime": "2026-09-10T06:59:00Z"}, {"dateTime": "2026-09-10T06:59:00Z"}
        google_import = {
            "id": "google-copy", "calendarId": "feed@import.calendar.google.com",
            "summary": "Assignment", "start": start, "end": end,
        }
        canvas = {
            "id": "ical:1:abc", "source": "canvas", "sourceEventUid": "assignment-1",
            "summary": "Assignment", "start": {"dateTime": "2026-09-10T06:59:00+00:00"}, "end": {"dateTime": "2026-09-10T06:59:00+00:00"},
        }
        merged = self.merger()([google_import], [canvas])
        self.assertEqual(merged, [canvas])

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

            feed = [b"""BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:assignment-42\nSUMMARY:Essay\nDTSTART;VALUE=DATE:20260915\nEND:VEVENT\nEND:VCALENDAR\n"""]

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

                feed[0] = b"BEGIN:VCALENDAR\nEND:VCALENDAR\n"
                module.calendar_subscription_sync(1, force=True)
                self.assertEqual(connection.execute("SELECT active FROM calendar_subscription_events WHERE id = ?", (record_id,)).fetchone()["active"], 0)

                feed[0] = b"""BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:assignment-42\nSUMMARY:Essay revised\nDTSTART;VALUE=DATE:20260915\nEND:VEVENT\nEND:VCALENDAR\n"""
                module.calendar_subscription_sync(1, force=True)
                restored = connection.execute("SELECT id, active, summary FROM calendar_subscription_events WHERE uid = ?", ("assignment-42",)).fetchone()
                self.assertEqual(restored["id"], record_id)
                self.assertEqual(restored["active"], 1)
                self.assertEqual(restored["summary"], "Essay revised")
                connection.close()
            finally:
                module.urllib.request.urlopen = original_open
