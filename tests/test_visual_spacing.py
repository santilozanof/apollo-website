import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class VisualSpacingRegressionTests(unittest.TestCase):
    def test_canonical_polish_layer_uses_four_pixel_scale(self):
        source = (ROOT / "apollo_polish_v1.css").read_text()
        for token, value in (
            ("--apollo-space-1", "4px"),
            ("--apollo-space-2", "8px"),
            ("--apollo-space-3", "12px"),
            ("--apollo-space-4", "16px"),
            ("--apollo-space-5", "20px"),
            ("--apollo-space-6", "24px"),
            ("--apollo-space-8", "32px"),
            ("--apollo-space-10", "40px"),
        ):
            self.assertIn(f"{token}: {value}", source)

    def test_polish_layer_is_loaded_after_legacy_page_styles(self):
        source = (ROOT / "index.html").read_text()
        polish = source.index('href="/apollo_polish_v1.css')
        routines = source.index('href="/routines.css')
        mobile = source.rindex('href="/apollo_mobile_v1.css')
        self.assertGreater(polish, routines)
        self.assertLess(polish, mobile)

    def test_checklist_header_does_not_repeat_progress_summary(self):
        source = (ROOT / "apollo_genui.js").read_text()
        self.assertIn("apollo-ui-checklist-title-row", source)
        self.assertIn("subtitleHasProgress", source)
        self.assertIn("!subtitleHasProgress", source)

    def test_mobile_routines_prioritize_primary_content(self):
        source = (ROOT / "routines.css").read_text()
        self.assertIn(".routine-list { order: 1; }", source)
        self.assertIn(".routine-side { position: static; order: 2;", source)

    def test_mobile_contract_reserves_safe_area(self):
        source = (ROOT / "apollo_mobile_v1.css").read_text()
        self.assertIn("--apollo-page-bottom: calc(88px + env(safe-area-inset-bottom))", source)
        self.assertIn("max-height: calc(100dvh - 24px - env(safe-area-inset-bottom))", source)


if __name__ == "__main__":
    unittest.main()
