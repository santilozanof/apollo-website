import ast
import json
import sqlite3
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
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

    def test_music_and_culture_beat_repetitive_minor_ai_and_gta(self):
        pool = [
            candidate("Underground soul artist releases a sample-built album", "music", 0.72, "Bandcamp", "https://daily.bandcamp.com/album/release"),
            candidate("Menswear exhibition opens in Zurich", "fashion", 0.68, "Vogue", "https://vogue.com/article/zurich-exhibition"),
            candidate("AI app adds another chat button", "ai", 0.35),
            candidate("GTA fans discuss another unconfirmed screenshot", "gaming", 0.3),
            candidate("Ceasefire agreement changes access to humanitarian aid", "world", 0.96),
        ]
        selected = personalization.select_stories(pool, now=self.now)
        headlines = [item["headline"] for item in selected["for_you"]]
        self.assertIn(pool[0]["headline"], headlines)
        self.assertIn(pool[1]["headline"], headlines)
        self.assertFalse(any("AI app" in headline or "GTA" in headline for headline in headlines))
        self.assertEqual(selected["worth_knowing"][0]["headline"], pool[4]["headline"])

    def test_duplicate_story_is_suppressed_without_meaningful_update(self):
        story = candidate("Artist announces new soul album and tour", "music")
        previous = [{"headline": "Soul artist announces a new album and tour"}]
        self.assertEqual(
            personalization.select_stories([story], previous_stories=previous, now=self.now)["for_you"],
            [],
        )
        story["meaningful_new_development"] = True
        self.assertEqual(len(personalization.select_stories([story], previous_stories=previous, now=self.now)["for_you"]), 1)

    def test_clickbait_stale_and_unlinked_stories_are_filtered(self):
        bad = [
            candidate("You won't believe this shocking album", "music"),
            candidate("A legitimate but outdated music article", "music", published="2025-01-01T00:00:00Z"),
            candidate("A story without a direct source", "music", url=""),
        ]
        bad[2]["url"] = ""
        self.assertEqual(personalization.select_stories(bad, now=self.now)["for_you"], [])

    def test_feedback_persists_and_changes_future_ranking_with_decay(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        personalization.init_schema(conn)
        liked = candidate("Jazz producer shares a new sampling project", "music", url="https://pitchfork.com/a")
        disliked = candidate("House producer shares a new club project", "music", url="https://pitchfork.com/b")
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
        self.assertEqual(selected, {"for_you": [], "worth_knowing": []})
        source = (ROOT / "generate_debrief.py").read_text(encoding="utf-8")
        self.assertIn('if not content and any(today.values()):', source)
        self.assertIn('"for_you": []', source)
        self.assertIn('"instruction": "Search the web for current news and verified direct sources."', source)

    def test_unreachable_source_links_are_removed_before_display(self):
        good = personalization.normalize_candidate(candidate("Verified jazz release", "music", url="https://pitchfork.com/good"))
        bad = personalization.normalize_candidate(candidate("Unverifiable jazz release", "music", url="https://pitchfork.com/missing"))
        selected = {"for_you": [good, bad], "worth_knowing": []}
        verified = personalization.verify_selected_links(
            selected,
            checker=lambda url: url.endswith("/good"),
        )
        self.assertEqual([item["headline"] for item in verified["for_you"]], ["Verified jazz release"])


class DebriefPersonalContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / "generate_debrief.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {"_event_time", "get_personal_today"}]
        cls.code = compile(ast.Module(body=nodes, type_ignores=[]), "generate_debrief.py", "exec")

    def load(self, calendar=None, tasks=None, routine_state=None, calendar_error=None):
        class Connection:
            def close(self):
                pass

        def events(**_kwargs):
            if calendar_error:
                raise calendar_error
            return calendar or [], {}

        namespace = {
            "datetime": datetime,
            "timedelta": timedelta,
            "apollo_calendar_events": events,
            "get_tasks": lambda: tasks or [],
            "db": lambda: Connection(),
            "routines": SimpleNamespace(get_state=lambda *_args: routine_state or {"routines": []}),
        }
        exec(self.code, namespace)
        return namespace["get_personal_today"]

    def test_calendar_assignments_tasks_and_routines_are_integrated(self):
        now = datetime(2026, 10, 13, 8, tzinfo=ZoneInfo("Europe/Zurich"))
        function = self.load(
            calendar=[{"summary": "Jazz ensemble", "start": {"dateTime": "2026-10-13T18:00:00+02:00"}, "location": "Zurich"}],
            tasks=[
                {"title": "Physics assignment", "due_at": "2026-10-14T12:00:00+02:00", "completed": False, "source": "canvas", "sourceLabel": "Canvas", "htmlLink": "https://canvas.example/1"},
                {"title": "Completed task", "completed": True},
            ],
            routine_state={"routines": [{"title": "Morning", "status": "incomplete", "steps": [{"title": "Journal", "complete": False}]}]},
        )
        result = function(now, "Europe/Zurich")
        self.assertEqual(result["calendar"][0]["headline"], "Jazz ensemble")
        self.assertEqual(result["tasks"][0]["kind"], "assignment")
        self.assertEqual(result["routines"][0]["body"], "1 step remaining")

    def test_unavailable_calendar_is_omitted_without_losing_tasks(self):
        now = datetime(2026, 10, 13, 8, tzinfo=ZoneInfo("Europe/Zurich"))
        function = self.load(
            calendar_error=RuntimeError("offline"),
            tasks=[{"title": "Submit essay", "completed": False, "source": "apollo"}],
        )
        result = function(now, "Europe/Zurich")
        self.assertEqual(result["calendar"], [])
        self.assertEqual(result["tasks"][0]["headline"], "Submit essay")


if __name__ == "__main__":
    unittest.main()
