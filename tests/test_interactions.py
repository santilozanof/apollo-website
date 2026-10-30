import json
import sqlite3
import unittest
import uuid

import apollo_interactions as interactions


class QuizPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE chats (id INTEGER PRIMARY KEY)")
        self.conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, chat_id INTEGER)")
        self.conn.execute("INSERT INTO chats VALUES (7)")
        self.conn.execute("INSERT INTO messages VALUES (11, 7)")
        interactions.init_schema(self.conn)
        block = {
            "type": "quiz", "id": "model-id", "title": "Understanding",
            "allow_retry": True,
            "questions": [
                {"id": "one", "question": "Pick C", "correct_answer_id": "c",
                 "options": [{"id": "b", "label": "B"}, {"id": "c", "label": "C"}]},
                {"id": "two", "question": "Pick A", "correct_answer_id": "a",
                 "options": [{"id": "a", "label": "A"}, {"id": "d", "label": "D"}]},
            ],
        }
        content = interactions.FENCE + "apollo-ui\n" + json.dumps({"blocks": [block]}) + "\n" + interactions.FENCE
        self.saved = interactions.register_quizzes(self.conn, 7, 11, content)
        self.conn.commit()
        self.quiz_id = "quiz-7-11-1"

    def tearDown(self):
        self.conn.close()

    def answer(self, question, option, event_id=None):
        return interactions.submit_answer(self.conn, self.quiz_id, {
            "event_id": event_id or str(uuid.uuid4()),
            "session_no": interactions.snapshot(self.conn, self.quiz_id)["current_session"],
            "question_id": question, "option_id": option,
        })

    def test_wrong_then_correct_preserves_original_grade_and_context(self):
        self.assertIn(self.quiz_id, self.saved)
        first = self.answer("one", "b")
        self.assertEqual(first["current"]["summary"]["first_attempt_score"], 0)
        fixed = self.answer("one", "c")
        self.assertEqual(fixed["current"]["summary"]["first_attempt_score"], 0)
        self.assertEqual(fixed["current"]["summary"]["corrected_after_mistake"], 1)
        final = self.answer("two", "a")
        self.assertEqual(final["current"]["summary"]["first_attempt_score"], 1)
        self.assertEqual(final["current"]["summary"]["eventually_correct"], 2)
        self.assertEqual(final["current"]["summary"]["total_attempts"], 3)
        self.assertTrue(final["current"]["summary"]["completed"])
        context = interactions.context_for_query(self.conn, 7, "Which questions did I get wrong?")
        self.assertIn("first-attempt 1/2", context)
        self.assertIn("Pick C", context)

    def test_retry_event_is_idempotent_and_restart_preserves_session(self):
        event_id = str(uuid.uuid4())
        one = self.answer("one", "b", event_id)
        two = self.answer("one", "b", event_id)
        self.assertEqual(one["current"]["summary"], two["current"]["summary"])
        with self.assertRaises(interactions.InteractionError):
            self.answer("one", "b")
        restarted = interactions.restart(self.conn, self.quiz_id, {
            "event_id": str(uuid.uuid4())
        })
        self.assertEqual(restarted["current_session"], 2)
        self.assertEqual(restarted["sessions"][0]["summary"]["total_attempts"], 1)
        self.assertEqual(restarted["current"]["summary"]["total_attempts"], 0)
        self.answer("one", "c")
        self.assertIn("session 1: 0/2", interactions.context_for_query(
            self.conn, 7, "Have I improved on the quiz?"
        ))

    def test_invalid_and_deleted_state(self):
        with self.assertRaises(interactions.InteractionError):
            self.answer("one", "invented")
        with self.assertRaises(interactions.InteractionError):
            interactions.submit_answer(self.conn, self.quiz_id, {
                "event_id": str(uuid.uuid4()), "session_no": 999,
                "question_id": "one", "option_id": "c",
            })
        self.conn.execute("DELETE FROM messages WHERE id=11")
        interactions.purge_orphans(self.conn)
        self.assertEqual(interactions.list_quizzes(self.conn, 7), [])
        self.assertEqual(self.conn.execute(
            "SELECT count(*) FROM interaction_events"
        ).fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
