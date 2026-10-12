from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RoutinesFrontendIntegrationTests(unittest.TestCase):
    def test_routines_uses_the_canonical_route_manager(self):
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('routines: "openRoutines"', index)
        self.assertIn('routines: document.getElementById("routinesView")', index)
        self.assertIn('destination !== "routines"', index)
        self.assertLess(
            index.index('<script id="apollo-routines-js"'),
            index.index('<script id="apollo-route-state-v2"'),
        )

        script = (ROOT / "routines.js").read_text(encoding="utf-8")
        self.assertIn("studioButton?.nextSibling", script)

    def test_routines_has_no_home_widget_or_native_dialogs(self):
        script = (ROOT / "routines.js").read_text(encoding="utf-8")
        self.assertNotIn("renderHome", script)
        self.assertNotIn("apolloHomeRoutines", script)
        self.assertNotIn("confirm(", script)
        self.assertNotIn("prompt(", script)
        self.assertNotIn("alert(", script)

    def test_step_schedule_editor_stays_progressive_and_supports_week_view(self):
        script = (ROOT / "routines.js").read_text(encoding="utf-8")
        self.assertIn("Schedule this step differently", script)
        self.assertIn("routine-advanced-fields", script)
        self.assertIn("Weekly schedule", script)
        self.assertIn('action: "set_step_exception"', script)
        self.assertIn("alternative_group", script)

    def test_step_toggle_uses_hydrated_progress_before_schedule_metadata(self):
        script = (ROOT / "routines.js").read_text(encoding="utf-8")
        hydrated = "routine.steps.find(item => item.id === stepElement.dataset.step)"
        metadata = "(routine.all_steps || []).find(item => item.id === stepElement.dataset.step)"
        self.assertIn("completed: !step.complete", script)
        self.assertLess(script.index(hydrated), script.index(metadata))
        self.assertIn('target.closest("[data-step-toggle]").disabled = true', script)

    def test_routines_reuses_the_canonical_apollo_eyebrow(self):
        script = (ROOT / "routines.js").read_text(encoding="utf-8")
        self.assertIn('<div class="apollo-page-eyebrow">APOLLO</div>', script)
        self.assertNotIn("routine-kicker", script)


if __name__ == "__main__":
    unittest.main()
