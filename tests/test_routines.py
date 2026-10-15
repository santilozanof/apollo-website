import sqlite3
import unittest
from datetime import date, timedelta

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

    def test_schema_upgrade_adds_step_scheduling_without_data_loss(self):
        legacy = sqlite3.connect(":memory:")
        legacy.execute("""CREATE TABLE routine_steps (
            id TEXT PRIMARY KEY, routine_id TEXT NOT NULL, title TEXT NOT NULL,
            step_type TEXT NOT NULL DEFAULT 'checkbox', target REAL NOT NULL DEFAULT 1,
            unit TEXT NOT NULL DEFAULT '', required INTEGER NOT NULL DEFAULT 1,
            linked_hydration INTEGER NOT NULL DEFAULT 0, position INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        legacy.execute("INSERT INTO routine_steps VALUES ('s','r','Cleanse','checkbox',1,'',1,0,0,'now','now')")
        routines.init_schema(legacy)
        columns = {row[1] for row in legacy.execute("PRAGMA table_info(routine_steps)")}
        self.assertTrue({"schedule_type", "schedule_days", "recurrence_rule", "alternative_group"} <= columns)
        self.assertEqual(legacy.execute("SELECT title FROM routine_steps WHERE id='s'").fetchone()[0], "Cleanse")
        legacy.close()

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
        current = routines.get_state(
            self.conn, routines.local_day("UTC"), "UTC"
        )["routines"][0]
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

    def test_chat_creates_daily_routine_with_multiple_steps(self):
        reply = routines.chat_action(
            self.conn,
            "Create a QA morning routine with steps Cleanse, Serum, Moisturize, and Sunscreen every day",
            "Europe/Zurich",
        )
        self.assertIn("with 4 steps", reply)
        state = routines.get_state(
            self.conn, routines.local_day("Europe/Zurich"), "Europe/Zurich"
        )
        item = state["routines"][0]
        self.assertEqual(item["title"], "Qa Morning")
        self.assertEqual([step["title"] for step in item["steps"]], ["Cleanse", "Serum", "Moisturize", "Sunscreen"])

    def test_chat_creates_four_explicitly_counted_ordered_steps(self):
        request = (
            "Create a Morning Skincare routine with four steps: Cleanser, "
            "Niacinamide serum, Hydrating cream, and SPF sunscreen."
        )
        reply = routines.chat_action(self.conn, request, "Europe/Zurich")
        self.assertIn("with 4 steps", reply)
        item = routines.get_state(
            self.conn, routines.local_day("Europe/Zurich"), "Europe/Zurich"
        )["routines"][0]
        self.assertEqual(
            [step["title"] for step in item["steps"]],
            ["Cleanser", "Niacinamide serum", "Hydrating cream", "SPF sunscreen"],
        )
        routines.chat_action(self.conn, request, "Europe/Zurich")
        self.assertEqual(self.conn.execute("SELECT count(*) FROM routine_groups").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM routine_steps").fetchone()[0], 4)

    def test_chat_retrieves_created_routine(self):
        routines.chat_action(
            self.conn,
            "Create a QA verification routine with steps One, Two, Three, and Four every day",
            "UTC",
        )
        reply = routines.chat_action(self.conn, "Show my QA verification routine steps", "UTC")
        self.assertIn("Qa Verification has One, Two, Three, Four", reply)

    def test_chat_distinguishes_morning_from_nighttime_skincare(self):
        routines.create_routine(self.conn, {
            "title": "Nighttime Skincare",
            "steps": [{"title": "Retinol"}],
        })
        routines.chat_action(
            self.conn,
            "Create a Morning Skincare routine with four steps: Cleanser, Niacinamide serum, Hydrating cream, and SPF sunscreen.",
            "Europe/Zurich",
        )
        reply = routines.chat_action(
            self.conn, "What are the steps in my Morning Skincare routine?", "Europe/Zurich"
        )
        self.assertEqual(
            reply,
            "Morning Skincare has Cleanser, Niacinamide serum, Hydrating cream, SPF sunscreen.",
        )

    def test_chat_executes_markdown_numbered_routine_request(self):
        reply = routines.chat_action(self.conn, """Apollo, create my **Morning Skincare** routine in the Routines tab, repeating every day, Monday through Sunday, with these four steps in this exact order:

1. **Cleanser**
2. **Niacinamide serum**
3. **Hydrating cream**
4. **SPF sunscreen**

Make each step individually checkable and verify that all four steps were saved correctly.""", "Europe/Zurich")
        self.assertIn("Created Morning Skincare for every day with 4 steps", reply)
        saved = routines._snapshot(
            self.conn,
            self.conn.execute("SELECT id FROM routine_groups WHERE title=?", ("Morning Skincare",)).fetchone()[0],
        )
        self.assertEqual(
            [step["title"] for step in saved["steps"]],
            ["Cleanser", "Niacinamide serum", "Hydrating cream", "SPF sunscreen"],
        )

    def test_chat_parses_explicit_name_and_stops_steps_at_instructions(self):
        request = (
            "Create a daily routine named Morning Skincare in the Routines tab with these four "
            "steps in order: Cleanser, Niacinamide serum, Hydrating cream, SPF sunscreen. "
            "Schedule it every morning, Monday through Sunday. If it already exists, update it "
            "instead of creating a duplicate. Verify that all four steps were saved correctly."
        )
        reply = routines.chat_action(self.conn, request, "Europe/Zurich")
        self.assertIn("Created Morning Skincare for every day with 4 steps", reply)
        groups = self.conn.execute(
            "SELECT id,schedule_days FROM routine_groups WHERE title=?", ("Morning Skincare",)
        ).fetchall()
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["schedule_days"], "[0, 1, 2, 3, 4, 5, 6]")
        saved = routines._snapshot(self.conn, groups[0]["id"])
        self.assertEqual(
            [step["title"] for step in saved["steps"]],
            ["Cleanser", "Niacinamide serum", "Hydrating cream", "SPF sunscreen"],
        )

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
            self.conn, routines.local_day("Europe/Zurich"), "Europe/Zurich"
        )["routines"][0]["steps"]]
        self.assertEqual(titles, ["Brush my teeth", "flossing", "Prepare for bed"])

    def test_contextual_add_uses_resolved_entity_and_verified_position(self):
        routine = routines.create_routine(self.conn, {
            "title": "Morning",
            "steps": [
                {"title": "Cleanser"},
                {"title": "Niacinamide serum"},
                {"title": "Hydrating cream"},
                {"title": "SPF sunscreen"},
            ],
        }, today="2026-10-12")
        reply = routines.chat_action(
            self.conn,
            "Ok add it to my morning routine.",
            "Europe/Zurich",
            reference_resolution={
                "status": "resolved",
                "operation": "add_step",
                "entity_type": "ingredient",
                "names": ["Azelaic acid 10%"],
                "target_name": "Morning",
                "relation": "after",
                "anchor_name": "Niacinamide serum",
            },
        )
        saved = routines._snapshot(self.conn, routine["id"])
        self.assertEqual(
            [step["title"] for step in saved["steps"]],
            [
                "Cleanser", "Niacinamide serum", "Azelaic acid 10%",
                "Hydrating cream", "SPF sunscreen",
            ],
        )
        self.assertNotIn("it", [step["title"].lower() for step in saved["steps"]])
        self.assertEqual(
            reply,
            "Added Azelaic acid 10% to Morning, after Niacinamide serum.",
        )

    def test_unresolved_or_ambiguous_reference_never_writes_placeholder(self):
        self.routine(steps=[{"title": "Cleanser"}])
        before = self.conn.execute("SELECT count(*) FROM routine_steps").fetchone()[0]
        unresolved = routines.chat_action(
            self.conn, "Add it to my morning routine", "UTC"
        )
        ambiguous = routines.chat_action(
            self.conn,
            "Add that to my morning routine",
            "UTC",
            reference_resolution={
                "status": "ambiguous",
                "clarification": "Which item do you want me to add?",
            },
        )
        after = self.conn.execute("SELECT count(*) FROM routine_steps").fetchone()[0]
        self.assertEqual(before, after)
        self.assertEqual(unresolved, "Which item do you want me to add?")
        self.assertEqual(ambiguous, "Which item do you want me to add?")

    def test_quoted_placeholder_is_a_legitimate_literal_name(self):
        self.routine(steps=[{"title": "Cleanser"}])
        reply = routines.chat_action(
            self.conn, 'Add "it" to my morning routine', "UTC"
        )
        self.assertIn("Added it", reply)
        saved = self.conn.execute(
            "SELECT title FROM routine_steps WHERE lower(title)='it'"
        ).fetchone()
        self.assertIsNotNone(saved)

    def test_compound_edit_replaces_quoted_literal_and_preserves_position(self):
        routine = self.routine(steps=[
            {"title": "Cleanser"},
            {"title": "it"},
            {"title": "Moisturizer"},
            {"title": "SPF"},
        ])
        unrelated = {
            step["title"]: (step["id"], step["position"])
            for step in routine["steps"] if step["title"] != "it"
        }
        reply = routines.chat_action(
            self.conn,
            "remove 'it' from my morning routine and add azelaic acid instead "
            "but in the correct order or the order you think it would fit in",
            "Europe/Zurich",
            conversation=[
                {"role": "user", "content": "I use azelaic acid 10%."},
                {"role": "assistant", "content": "Use it after niacinamide if present."},
            ],
            reference_resolution={
                "status": "resolved",
                "operation": "replace_step",
                "entity_type": "routine_step",
                "names": ["it", "Azelaic acid 10%"],
                "target_name": "Morning",
                "relation": "",
                "anchor_name": "",
            },
        )
        saved = routines._snapshot(self.conn, routine["id"])
        self.assertEqual(
            [step["title"] for step in saved["steps"]],
            ["Cleanser", "Azelaic acid 10%", "Moisturizer", "SPF"],
        )
        self.assertEqual(
            {
                step["title"]: (step["id"], step["position"])
                for step in saved["steps"] if step["title"] != "Azelaic acid 10%"
            },
            unrelated,
        )
        self.assertEqual(
            reply, "Replaced it with Azelaic acid 10% in Morning."
        )

    def test_compound_edit_prevents_duplicate_without_partial_delete(self):
        routine = self.routine(steps=[
            {"title": "Cleanser"},
            {"title": "it"},
            {"title": "Azelaic acid 10%"},
            {"title": "SPF"},
        ])
        before = [(step["id"], step["title"]) for step in routine["steps"]]
        reply = routines.chat_action(
            self.conn,
            "remove 'it' from my morning routine and add azelaic acid instead",
            "UTC",
            reference_resolution={
                "status": "resolved",
                "operation": "replace_step",
                "names": ["it", "Azelaic acid 10%"],
                "target_name": "Morning",
            },
        )
        saved = routines._snapshot(self.conn, routine["id"])
        self.assertEqual([(step["id"], step["title"]) for step in saved["steps"]], before)
        self.assertEqual(reply, "Azelaic acid 10% is already in Morning.")

    def test_unquoted_placeholder_in_compound_edit_stays_ambiguous(self):
        self.routine(steps=[{"title": "it"}, {"title": "SPF"}])
        reply = routines.chat_action(
            self.conn,
            "remove it from my morning routine and add azelaic acid instead",
            "UTC",
            reference_resolution={
                "status": "resolved",
                "operation": "replace_step",
                "names": ["it", "Azelaic acid 10%"],
                "target_name": "Morning",
            },
        )
        self.assertEqual(reply, "Which item do you want me to change?")
        self.assertEqual(
            [row[0] for row in self.conn.execute(
                "SELECT title FROM routine_steps ORDER BY position"
            )],
            ["it", "SPF"],
        )

    def test_contextual_follow_up_moves_recent_step_without_recreating_it(self):
        routine = routines.create_routine(self.conn, {
            "title": "Morning",
            "steps": [
                {"title": "Cleanser"},
                {"title": "Moisturizer"},
                {"title": "SPF"},
                {"title": "Azelaic acid 10%"},
            ],
        }, today="2026-10-12")
        ids_before = {
            step["title"]: step["id"] for step in routine["steps"]
        }
        reply = routines.chat_action(
            self.conn,
            "Move the one we just added before the last step.",
            "UTC",
            reference_resolution={
                "status": "resolved",
                "operation": "move_step",
                "entity_type": "routine_step",
                "names": ["Azelaic acid 10%"],
                "target_name": "Morning",
                "relation": "before",
                "anchor_name": "SPF",
            },
        )
        saved = routines._snapshot(self.conn, routine["id"])
        self.assertEqual(
            [step["title"] for step in saved["steps"]],
            ["Cleanser", "Moisturizer", "Azelaic acid 10%", "SPF"],
        )
        self.assertEqual(
            {step["title"]: step["id"] for step in saved["steps"]}, ids_before
        )
        self.assertEqual(
            reply,
            "Moved Azelaic acid 10% before SPF in Morning.",
        )

    def test_chat_edits_steps_and_routine_without_name_confusion(self):
        routines.create_routine(self.conn, {
            "title": "Morning Skincare", "steps": [{"title": "Cleanser"}],
        }, today="2026-10-12")
        routine = routines.create_routine(self.conn, {
            "title": "Nighttime Skincare",
            "steps": [{"title": "Cleanser"}, {"title": "Under-eye patches"}, {"title": "Retinol"}],
        }, today="2026-10-12")
        self.assertIn("Removed Under-eye patches", routines.chat_action(
            self.conn, "Remove the under-eye patches from my nighttime routine", "Europe/Zurich"
        ))
        routines.chat_action(self.conn, "Add Hydrating cream after Cleanser to my nighttime routine", "Europe/Zurich")
        routines.chat_action(self.conn, "Rename Retinol to Night treatment in my nighttime routine", "Europe/Zurich")
        routines.chat_action(self.conn, "Move Night treatment before Cleanser in my nighttime routine", "Europe/Zurich")
        routines.chat_action(self.conn, "Set my nighttime routine schedule to Monday, Wednesday, and Friday", "Europe/Zurich")
        routines.chat_action(self.conn, "Rename my nighttime routine to Evening Skincare", "Europe/Zurich")
        saved = routines._snapshot(self.conn, routine["id"])
        self.assertEqual(saved["title"], "Evening Skincare")
        self.assertEqual(saved["schedule_days"], [0, 2, 4])
        self.assertEqual([step["title"] for step in saved["steps"]], ["Night treatment", "Cleanser", "Hydrating cream"])
        morning = self.conn.execute("SELECT title FROM routine_groups WHERE title='Morning Skincare'").fetchone()
        self.assertIsNotNone(morning)

    def test_only_steps_scheduled_for_day_are_required(self):
        routine = self.routine(steps=[
            {"title": "Cleanse"},
            {"title": "Retinol", "schedule_type": "weekdays", "schedule_days": [0]},
            {"title": "Azelaic acid", "schedule_type": "weekdays", "schedule_days": [2]},
        ])
        monday = routines.get_state(self.conn, "2026-10-05", "UTC")["routines"][0]
        self.assertEqual([step["title"] for step in monday["steps"]], ["Cleanse", "Retinol"])
        self.assertEqual(monday["required_steps"], 2)
        routines.set_step(self.conn, routine["id"], monday["steps"][0]["id"], completed=True, day="2026-10-05")
        partial = routines.get_state(self.conn, "2026-10-05", "UTC")["routines"][0]
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(partial["progress"], .5)

    def test_alternative_steps_count_as_one_requirement(self):
        routine = self.routine(steps=[
            {"title": "Retinol", "alternative_group": "treatment"},
            {"title": "Azelaic acid", "alternative_group": "treatment"},
            {"title": "Moisturize"},
        ])
        state = routines.get_state(self.conn, "2026-10-10", "UTC")["routines"][0]
        self.assertEqual(state["required_steps"], 2)
        routines.set_step(self.conn, routine["id"], state["steps"][0]["id"], completed=True, day="2026-10-10")
        routines.set_step(self.conn, routine["id"], state["steps"][2]["id"], completed=True, day="2026-10-10")
        self.assertEqual(routines.get_state(self.conn, "2026-10-10", "UTC")["routines"][0]["status"], "completed")

    def test_custom_recurrence_rule(self):
        self.routine(steps=[{
            "title": "Exfoliate", "schedule_type": "recurrence", "schedule_days": [0],
            "recurrence_rule": {"frequency": "weekly", "interval": 2, "start_date": "2026-10-05", "weekdays": [0]},
        }])
        first = routines.get_state(self.conn, "2026-10-05", "UTC")["routines"][0]
        off_week = routines.get_state(self.conn, "2026-10-12", "UTC")["routines"][0]
        next_week = routines.get_state(self.conn, "2026-10-19", "UTC")["routines"][0]
        self.assertEqual(len(first["steps"]), 1)
        self.assertEqual(len(off_week["steps"]), 0)
        self.assertEqual(len(next_week["steps"]), 1)

    def test_date_exception_skips_and_substitutes_without_rewriting_history(self):
        routine = self.routine(steps=[{"title": "Retinol"}])
        historical = routines.get_state(self.conn, "2026-10-08", "UTC")["routines"][0]
        step_id = routine["steps"][0]["id"]
        today = date.fromisoformat(routines.local_day("UTC"))
        substitute_day = today.isoformat()
        skip_day = (today + timedelta(days=1)).isoformat()
        routines.set_step_exception(self.conn, routine["id"], step_id, substitute_day, "substitute", "Azelaic acid")
        substituted = routines.get_state(self.conn, substitute_day, "UTC")["routines"][0]
        self.assertEqual(substituted["steps"][0]["title"], "Azelaic acid")
        self.assertEqual(substituted["steps"][0]["original_title"], "Retinol")
        self.assertEqual(routines.get_state(self.conn, "2026-10-08", "UTC")["routines"][0]["steps"][0]["title"], historical["steps"][0]["title"])
        routines.set_step_exception(self.conn, routine["id"], step_id, skip_day, "skip")
        self.assertEqual(routines.get_state(self.conn, skip_day, "UTC")["routines"][0]["steps"], [])

    def test_chat_moves_step_between_weekdays_and_context_has_week(self):
        routine = self.routine(steps=[{
            "title": "Retinol", "schedule_type": "weekdays", "schedule_days": [0],
        }])
        reply = routines.chat_action(self.conn, "Move my retinol night from Monday to Wednesday", "UTC")
        self.assertIn("Moved Retinol", reply)
        updated = routines._snapshot(self.conn, routine["id"])["steps"][0]
        self.assertEqual(updated["schedule_days"], [2])
        context = routines.chat_context(self.conn, "UTC")
        self.assertEqual(len(context["week_schedule"]), 7)
        self.assertIn("all_steps", context["routines"][0])


if __name__ == "__main__":
    unittest.main()
