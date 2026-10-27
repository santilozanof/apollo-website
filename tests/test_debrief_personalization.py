import json
import sqlite3
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import debrief_personalization as personalization


ROOT = Path(__file__).resolve().parents[1]


def candidate(headline, topic, importance=0.75, source="Reuters", url=None, published="2026-10-13T06:00:00Z", body=None):
    slug = "-".join(personalization._tokens(headline)) or "story"
    return {
        "category": topic.title(),
        "topics": [topic],
        "headline": headline,
        "body": body or "Verified reporting explains the development and why it has meaningful consequences.",
        "source": source,
        "url": url or f"https://reuters.com/{slug}",
        "published_at": published,
        "importance": importance,
        "meaningful_new_development": False,
    }


class DebriefRankingTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 13, 10, tzinfo=ZoneInfo("Europe/Zurich"))

    def test_significant_news_beats_obscure_music_and_minor_ai(self):
        pool = [
            candidate("Underground soul artist releases a sample-built album", "music", 0.72, "Bandcamp", "https://daily.bandcamp.com/album/release"),
            candidate("Menswear exhibition opens in Zurich", "fashion", 0.68, "Vogue", "https://vogue.com/article/zurich-exhibition"),
            candidate("AI app adds another chat button", "ai", 0.35),
            candidate("GTA fans discuss another unconfirmed screenshot", "gaming", 0.3),
            candidate("Ceasefire agreement changes access to humanitarian aid", "world", 0.96),
        ]
        selected = personalization.select_stories(pool, now=self.now)
        headlines = [item["headline"] for item in selected["stories"]]
        self.assertNotIn(pool[0]["headline"], headlines)
        self.assertIn(pool[1]["headline"], headlines)
        self.assertFalse(any("AI app" in headline or "GTA" in headline for headline in headlines))
        self.assertIn(pool[4]["headline"], headlines)

    def test_duplicate_story_is_suppressed_without_meaningful_update(self):
        story = candidate("Peace agreement restores humanitarian aid access", "world")
        previous = [{"headline": "Peace agreement restores humanitarian aid access"}]
        self.assertEqual(
            personalization.select_stories([story], previous_stories=previous, now=self.now)["stories"],
            [],
        )
        story["meaningful_new_development"] = True
        self.assertEqual(len(personalization.select_stories([story], previous_stories=previous, now=self.now)["stories"]), 1)

    def test_clickbait_stale_and_unlinked_stories_are_filtered(self):
        bad = [
            candidate("You won't believe this shocking album", "music"),
            candidate("A legitimate but outdated music article", "music", published="2025-01-01T00:00:00Z"),
            candidate("A story without a direct source", "music", url=""),
        ]
        bad[2]["url"] = ""
        self.assertEqual(personalization.select_stories(bad, now=self.now)["stories"], [])

    def test_football_and_fifa_stories_are_excluded(self):
        football = candidate("Club football transfer window opens", "football")
        fifa = candidate(
            "FIFA confirms its next tournament schedule",
            "world",
            source="FIFA",
            url="https://fifa.com/tournament/schedule",
        )
        ufc = candidate("UFC confirms a new title fight", "ufc")
        headlines = [
            item["headline"]
            for item in personalization.select_stories(
                [football, fifa, ufc],
                now=self.now,
            )["stories"]
        ]
        self.assertEqual(headlines, [ufc["headline"]])

    def test_feedback_persists_and_changes_future_ranking_with_decay(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        personalization.init_schema(conn)
        liked = candidate("Frank Ocean announces a new album release", "music", url="https://pitchfork.com/a")
        disliked = candidate("Sade announces a new album release", "music", url="https://pitchfork.com/b")
        personalization.save_feedback(conn, {**liked, "feedback": "more"})
        personalization.save_feedback(conn, {**disliked, "feedback": "less"})
        conn.commit()
        rows = personalization.feedback_rows(conn)
        self.assertEqual(len(rows), 2)
        liked_score = personalization.score_candidate(personalization.normalize_candidate(liked), [], rows, self.now)["relevance_score"]
        disliked_score = personalization.score_candidate(personalization.normalize_candidate(disliked), [], rows, self.now)["relevance_score"]
        self.assertGreater(liked_score, disliked_score)
        conn.close()

    def test_missing_external_data_produces_no_fabricated_news(self):
        selected = personalization.select_stories([], now=self.now)
        self.assertEqual(selected["stories"], [])
        source = (ROOT / "generate_debrief.py").read_text(encoding="utf-8")
        self.assertNotIn("get_personal_today", source)
        self.assertIn("status = 'ready' if stories else 'unavailable'", source)
        self.assertIn("personal, health = collect_personal(now)", source)
        self.assertIn("Search the web for current news and verified direct sources.", source)

    def test_unreachable_source_links_are_removed_before_display(self):
        good = personalization.normalize_candidate(candidate("Verified jazz release", "music", url="https://pitchfork.com/good"))
        bad = personalization.normalize_candidate(candidate("Unverifiable jazz release", "music", url="https://pitchfork.com/missing"))
        selected = {"stories": [good, bad], "for_you": [], "worth_knowing": []}
        verified = personalization.verify_selected_links(
            selected,
            checker=lambda url: url.endswith("/good"),
        )
        self.assertEqual([item["headline"] for item in verified["stories"]], ["Verified jazz release"])


if __name__ == "__main__":
    unittest.main()
