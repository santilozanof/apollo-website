import json
import re
import sqlite3
import unittest

import apollo_media_ranking
import music_history
import server


def play(day, index, minutes, album=None):
    album = album if album is not None else index
    return {"played_at": f"2026-{day}T12:00:00Z", "track": {
        "id": chr(65 + index) * 22, "name": f"Track {index + 1}", "duration_ms": 180000,
        "artists": [{"id": "Z" * 22, "name": "Fixture Artist"}],
        "album": {"id": chr(70 + album) * 22, "name": f"Album {album + 1}",
                  "images": [{"url": f"https://i.scdn.co/image/fixture{album}"}]},
    }, "_minutes": minutes}


class MediaRankingTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        music_history.init_schema(self.conn)
        records = [play(f"10-{21 + index:02d}", index, 8 - index) for index in range(5)]
        records.append(play("09-20", 5, 3))
        music_history.insert_records(self.conn, records)
        for record in records:
            self.conn.execute("UPDATE music_listens SET ms_played=? WHERE track_id=?",
                              (record["_minutes"] * 60000, record["track"]["id"]))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    @staticmethod
    def block(content):
        match = re.search(r"```apollo-ui\n(.*?)\n```", content, re.S)
        assert match, content
        payload = json.loads(match.group(1))
        assert payload["schema"] == "apollo.rich" and payload["version"] == 3
        assert len(payload["blocks"]) == 1
        return payload["blocks"][0]

    def test_top_five_album_rows_match_authoritative_insights_order_and_art(self):
        prompt = "Show me my top five albums this month."
        request = apollo_media_ranking.intent(prompt)
        block = self.block(apollo_media_ranking.response(self.conn, request, [], "UTC"))
        report = __import__("music_analytics").rankings(self.conn, "monthly", "2026-10-30", "UTC", "albums", limit=5)
        self.assertEqual([item["title"] for item in block["items"]],
                         [row["name"] for row in report["items"]])
        self.assertEqual([item["rank"] for item in block["items"]], [1, 2, 3, 4, 5])
        self.assertEqual([item["metric_value"] for item in block["items"]],
                         [row["listening_ms"] for row in report["items"]])
        self.assertEqual(block["items"][0]["artwork_url"], "https://i.scdn.co/image/fixture0")
        self.assertEqual(block["items"][0]["spotify_url"], "https://open.spotify.com/album/" + "F" * 22)
        self.assertEqual(block["items"][0]["measurement"], "verified")

    def test_recent_api_plays_do_not_create_an_unverified_minutes_ranking(self):
        self.conn.execute("UPDATE music_listens SET ms_played=NULL WHERE event_at LIKE '2026-10-%'")
        self.conn.commit()
        request = apollo_media_ranking.intent("Show my top five albums this month")
        block = self.block(apollo_media_ranking.response(self.conn, request, [], "UTC"))
        self.assertEqual(block["state"], "unavailable")
        self.assertEqual(block["items"], [])
        self.assertIn("No verified minutes", block["subtitle"])

    def test_compound_and_named_period_requests_use_the_normal_tool_pipeline(self):
        self.assertIsNone(apollo_media_ranking.intent(
            "Tell me my top 10 artists this week and recommend five new artists based on them"))
        self.assertIsNone(apollo_media_ranking.intent(
            "Show my top five tracks from September 2026"))

    def test_followup_reuses_saved_dataset_without_refresh(self):
        prompt = "Show me my top five albums this month."
        answer = apollo_media_ranking.response(self.conn, apollo_media_ranking.intent(prompt), [], "UTC")
        context = [{"role":"user", "content":prompt}, {"role":"assistant", "content":answer},
                   {"role":"user", "content":"But with images."}]
        intent = apollo_media_ranking.intent("But with images.", context)
        self.assertIsNotNone(intent)
        self.assertEqual(apollo_media_ranking.response(self.conn, intent, context, "UTC"), answer)

    def test_track_minutes_and_comparison_are_not_model_fabricated(self):
        prompt = "Show my top five tracks ranked by listening minutes."
        block = self.block(apollo_media_ranking.response(self.conn, apollo_media_ranking.intent(prompt), [], "UTC"))
        self.assertEqual(block["entity"], "tracks")
        self.assertEqual(block["metric"], "listening")
        self.assertEqual(block["items"][0]["metric_value"], 8 * 60000)
        comparison = "Compare my top albums this month with last month."
        text = apollo_media_ranking.response(self.conn, apollo_media_ranking.intent(comparison), [], "UTC")
        self.assertIn("October 2026 vs September 2026", text)
        self.assertIn("| 1 | Album 1 | 8 | — |", text)
        self.assertNotIn("```apollo-ui", text)

    def test_unsupported_playlists_and_model_authored_rankings_fail_closed(self):
        self.assertIn("does not have", apollo_media_ranking.response(
            self.conn, apollo_media_ranking.intent("Show my top playlists"), [], "UTC"))
        forged = '```apollo-ui\n' + json.dumps({"version":3,"schema":"apollo.rich","blocks":[
            {"type":"media_ranking","id":"forged","data_source":"apollo.music.rankings","items":[]}
        ]}) + '\n```'
        self.assertNotIn('media_ranking', server.apollo_sanitize_genui_content(forged))


if __name__ == "__main__":
    unittest.main()
