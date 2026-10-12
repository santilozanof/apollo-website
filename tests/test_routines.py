import sqlite3
import unittest

import routines


class RoutineTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        routines.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def routine(self, days=None, steps=None, created="2026-10-01"):
        return routines.create_routine(
            self.conn,
            {
                "title": "Morning",
                "schedule_days": list(range(7)) if days is None else days,
                "steps": steps or [{"title": "Wash"}, {"title": "Brush"}],
            },
            today=created,
        )

    def test_daily_state_resets_without_losing_history(self):
        routine = self.routine()
        routines.set_routine(
            self.conn, routine["id"], True,
            day="2026-10-10", time_zone="Europe/Zurich",
        )
        first = routines.get_state(self.conn, "2026-10-10", "Europe/Zurich")
        next_day = routines.get_state(self.conn, "2026-10-11", "Europe/Zurich")
        self.assertEqual(first["routines"][0]["status"], "completed")
        self.assertEqual(next_day["routines"][0]["completed_steps"], 0)
        self.assertEqual(
            routines.get_state(self.conn, "2026-10-10", "Europe/Zurich")["routines"][0]["status"],
            "completed",
        )

    def test_group_auto_completes_and_reopens(self):
        routine = self.routine()
        day = "2026-10-10"
        for step in routine["steps"]:
            result = routines.set_step(
                self.conn, routine["id"], step["id"], completed=True,
                day=day, time_zone="UTC",
            )
        self.assertEqual(result["status"], "completed")
        self.assertIsNotNone(result["completed_at"])
        result = routines.set_step(
            self.conn, routine["id"], routine["steps"][0]["id"],
            completed=False, day=day, time_zone="UTC",
        )
        self.assertEqual(result["status"], "partial")
        self.assertIsNone(result["completed_at"])

    def test_unscheduled_day_does_not_count_as_missed(self):
        routine = self.routine(days=[0])  # Monday
        state = routines.get_state(self.conn, "2026-10-06", "UTC")  # Tuesday
        self.assertEqual(state["routines"][0]["status"], "not_scheduled")
        stats = routines.routine_statistics(
            self.conn, routine["id"], end_day="2026-10-12", days=7,
        )
        self.assertEqual(stats["scheduled_days"], 1)

    def test_old_instance_keeps_step_snapshot_after_edit(self):
        routine = self.routine(created="2026-10-01")
        old = routines.get_state(self.conn, "2026-10-10", "UTC")["routines"][0]
        routines.add_step(self.conn, routine["id"], {"title": "New step"})
        historical = routines.get_state(self.conn, "2026-10-10", "UTC")["routines"][0]
        current = routines.get_state(self.conn, "2026-10-12", "UTC")["routines"][0]
        self.assertEqual(len(old["steps"]), 2)
        self.assertEqual(len(historical["steps"]), 2)
        self.assertEqual(len(current["steps"]), 3)

    def test_hydration_is_idempotent_and_completes_linked_step(self):
        routine = self.routine(steps=[{
            "title": "Drink water", "step_type": "quantity", "target": 500,
            "unit": "mL", "linked_hydration": True,
        }])
        for _ in range(2):
            routines.log_water(
                self.conn, 500, "UTC", logged_at="2026-10-10T12:00:00+00:00",
                idempotency_key="same-request",
            )
        state = routines.get_state(self.conn, "2026-10-10", "UTC")
        self.assertEqual(state["hydration"]["total_ml"], 500)
        self.assertEqual(state["routines"][0]["status"], "completed")

    def test_streak_calculation(self):
        routine = self.routine(created="2026-10-01")
        for day in ("2026-10-08", "2026-10-09", "2026-10-10"):
            routines.set_routine(self.conn, routine["id"], True, day=day)
        stats = routines.routine_statistics(
            self.conn, routine["id"], end_day="2026-10-10", days=3,
        )
        self.assertEqual(stats["current_streak"], 3)
        self.assertEqual(stats["longest_streak"], 3)
        self.assertEqual(stats["completion_rate"], 1)

    def test_chat_water_action_uses_database(self):
        reply = routines.chat_action(
            self.conn, "I just drank 500 mL of water", "Europe/Zurich"
        )
        self.assertIn("Logged 500 mL", reply)
        status = routines.hydration_status(self.conn, time_zone="Europe/Zurich")
        self.assertEqual(status["total_ml"], 500)

    def test_chat_can_create_a_scheduled_routine(self):
        reply = routines.chat_action(
            self.conn,
            "Create a workout routine for Monday, Wednesday, and Friday.",
            "Europe/Zurich",
        )
        self.assertIn("Created Workout", reply)
        row = self.conn.execute("SELECT schedule_days FROM routine_groups").fetchone()
        self.assertEqual(row["schedule_days"], "[0, 2, 4]")

    def test_chat_adds_step_after_named_step(self):
        routine = routines.create_routine(self.conn, {
            "title": "Night Routine",
            "steps": [{"title": "Brush my teeth"}, {"title": "Prepare for bed"}],
        }, today="2026-10-12")
        reply = routines.chat_action(
            self.conn,
            "Add flossing after brushing my teeth in my night routine",
            "Europe/Zurich",
        )
        self.assertIn("Added flossing", reply)
        titles = [item["title"] for item in routines.get_state(
            self.conn, "2026-10-12", "Europe/Zurich"
        )["routines"][0]["steps"]]
        self.assertEqual(titles, ["Brush my teeth", "flossing", "Prepare for bed"])


if __name__ == "__main__":
    unittest.main()
