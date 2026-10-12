from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RoutinesFrontendIntegrationTests(unittest.TestCase):
    def test_routines_uses_the_canonical_route_manager(self):
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('routines: "openRoutines"', index)
        self.assertIn('routines: document.getElementById("routinesView")', index)
        self.assertIn('destination !== "routines"', index)
        self.assertLess(index.index("apollo-routines-js"), index.index("apollo-route-state-v2"))

        script = (ROOT / "routines.js").read_text(encoding="utf-8")
        self.assertIn("studioButton?.nextSibling", script)

    def test_routines_has_no_home_widget_or_native_dialogs(self):
        script = (ROOT / "routines.js").read_text(encoding="utf-8")
        self.assertNotIn("renderHome", script)
        self.assertNotIn("apolloHomeRoutines", script)
        self.assertNotIn("confirm(", script)
        self.assertNotIn("prompt(", script)
        self.assertNotIn("alert(", script)


if __name__ == "__main__":
    unittest.main()
