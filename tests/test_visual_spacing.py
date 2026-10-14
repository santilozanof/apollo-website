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

    def test_chat_actions_wrap_below_the_complete_response(self):
        source = (ROOT / "apollo_polish_v1.css").read_text()
        self.assertIn(".apollo-message.assistant {", source)
        self.assertIn("grid-template-columns: var(--apollo-assistant-mark-size) minmax(0, 1fr) !important", source)
        self.assertIn("grid-column: 2 !important", source)
        self.assertIn("padding-left: 0 !important", source)
        self.assertIn("align-self: flex-start !important", source)

    def test_genui_polish_uses_systemic_heading_media_and_source_rules(self):
        source = (ROOT / "apollo_genui.css").read_text()
        self.assertIn(".apollo-rich-text > :first-child { margin-top: 0; }", source)
        self.assertIn("margin: 0 0 10px", source)
        self.assertIn(".apollo-ui-gallery", source)
        self.assertIn("border: 0; background: transparent", source)
        self.assertIn("counter(apollo-source, decimal-leading-zero)", source)
        self.assertIn("@keyframes apolloQuizForward", source)

    def test_mobile_routines_prioritize_primary_content(self):
        source = (ROOT / "routines.css").read_text()
        self.assertIn(".routine-list { order: 1; }", source)
        self.assertIn(".routine-side { position: static; order: 2;", source)

    def test_mobile_contract_reserves_safe_area(self):
        source = (ROOT / "apollo_mobile_v1.css").read_text()
        self.assertIn("--apollo-page-bottom: calc(88px + env(safe-area-inset-bottom))", source)
        self.assertIn("max-height: calc(100dvh - 24px - env(safe-area-inset-bottom))", source)

    def test_whoop_and_weekly_schedule_reuse_shared_spacing_tokens(self):
        polish = (ROOT / "apollo_polish_v1.css").read_text()
        routines = (ROOT / "routines.css").read_text()
        self.assertIn(".home > .apollo-home-whoop", polish)
        self.assertIn("margin-top: var(--apollo-section-gap) !important", polish)
        self.assertIn("margin-bottom: var(--apollo-space-2) !important", polish)
        self.assertIn("scrollbar-gutter: stable", routines)
        self.assertIn("margin: 0 0 var(--apollo-space-3, 12px)", routines)


if __name__ == "__main__":
    unittest.main()
