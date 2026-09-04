import tempfile
import unittest

from datetime import timedelta
from pathlib import Path

from automation_engine import AutomationEngine, iso, utc_now


class AutomationEngineTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "apollo.db"
        self.condition_value = {"recovery": 81}
        self.sent = []
        self.engine = AutomationEngine(
            self.db_path,
            condition_provider=lambda source, condition, now: self.condition_value,
            push_sender=lambda notification: self.sent.append(notification) or "sent",
            timezone_provider=lambda: "America/Monterrey",
        )
        self.engine.initialize()

    def tearDown(self):
        self.tempdir.cleanup()

    def create(self, **overrides):
        payload = {
            "title": "Pack passport",
            "instruction": "Remind me to pack my passport",
            "type": "one_time",
            "timezone": "America/Monterrey",
            "schedule": {"at": iso(utc_now() - timedelta(minutes=1))},
            "action": {"title": "Pack passport", "body": "Pack your passport", "deep_link": "/?tab=apollo"},
        }
        payload.update(overrides)
        return self.engine.create(payload)

    def force_due(self, automation_id):
        conn = self.engine.connection()
        conn.execute("UPDATE automations SET next_run_at = ? WHERE id = ?", (iso(utc_now() - timedelta(seconds=1)), automation_id))
        conn.commit()
        conn.close()

    def test_one_shot_completes_and_never_repeats(self):
        automation = self.create()
        self.engine.run_once()
        result = self.engine.list()[0]
        self.assertEqual("completed", result["status"])
        self.assertIsNone(result["next_run_at"])
        self.assertEqual(1, len(self.sent))
        self.engine.run_once()
        self.assertEqual(1, len(self.sent))

    def test_condition_once_resolves_and_recurring_deduplicates(self):
        one_shot = self.create(
            title="Recovery above 80",
            type="condition_once",
            schedule={},
            condition={"source": "whoop", "kind": "threshold", "metric": "recovery", "operator": "gt", "value": 80},
        )
        self.engine.run_once()
        self.assertEqual("completed", next(item for item in self.engine.list() if item["id"] == one_shot["id"])["status"])
        self.assertEqual(1, len(self.sent))

        recurring = self.create(
            title="Low recovery",
            type="condition_recurring",
            schedule={},
            condition={"source": "whoop", "kind": "threshold", "metric": "recovery", "operator": "gt", "value": 80, "check_interval_seconds": 60},
        )
        self.engine.run_once()
        self.assertEqual(2, len(self.sent))
        self.force_due(recurring["id"])
        self.engine.run_once()
        self.assertEqual(2, len(self.sent), "true condition must not spam")
        self.condition_value["recovery"] = 40
        self.force_due(recurring["id"])
        self.engine.run_once()
        self.condition_value["recovery"] = 81
        self.force_due(recurring["id"])
        self.engine.run_once()
        self.assertEqual(3, len(self.sent), "false then true may notify again")

    def test_recurring_reschedules_and_restart_recovers_due_work(self):
        recurring = self.create(
            title="Plan week",
            type="recurring_schedule",
            schedule={"weekday": 0, "hour": 19, "minute": 0},
        )
        self.force_due(recurring["id"])
        self.engine.run_once()
        current = next(item for item in self.engine.list() if item["id"] == recurring["id"])
        self.assertEqual("active", current["status"])
        self.assertGreater(current["next_run_at"], iso(utc_now()))

        due = self.create(title="Restart recovery")
        restarted = AutomationEngine(self.db_path, condition_provider=lambda *_: {}, push_sender=lambda notification: self.sent.append(notification) or "sent", timezone_provider=lambda: "UTC")
        restarted.initialize()
        restarted.run_once()
        result = next(item for item in restarted.list() if item["id"] == due["id"])
        self.assertEqual("completed", result["status"])

    def test_rejects_unstructured_or_unknown_conditions(self):
        with self.assertRaises(ValueError):
            self.create(type="condition_once", schedule={}, condition={"source": "shell", "kind": "run"})

    def test_default_rules_are_persistently_deduplicated(self):
        self.engine.default_provider = lambda now, preferences: [{
            "title": "Calendar soon",
            "body": "Planning starts soon",
            "category": "calendar",
            "deep_link": "/?tab=calendar",
            "dedupe_key": "event-1",
        }]
        self.engine.update_preferences({"calendar": True})
        self.engine.run_once()
        self.assertEqual(1, len(self.sent))
        self.engine._set_state("default_rules_checked_at", iso(utc_now() - timedelta(minutes=6)), utc_now())
        self.engine.run_once()
        self.assertEqual(1, len(self.sent), "a built-in rule must not repeat after restart/poll")
