"""Durable, server-graded quiz state associated with Apollo conversations."""

import json
import re
import uuid


FENCE = chr(96) * 3
QUIZ_FENCE = re.compile(re.escape(FENCE) + r"apollo-ui\s*\n([\s\S]*?)\n" + re.escape(FENCE), re.I)
QUIZ_QUERY = re.compile(
    r"\b(quiz|quizzes|knowledge check|grade|score|attempts?|(?:got|get) wrong|corrected|improv(?:e|ed|ement))\b", re.I
)


class InteractionError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def init_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS interaction_quizzes (
            id TEXT PRIMARY KEY,
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            definition_json TEXT NOT NULL,
            current_session INTEGER NOT NULL DEFAULT 1,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS interaction_quiz_chat
            ON interaction_quizzes(chat_id, message_id DESC);
        CREATE TABLE IF NOT EXISTS interaction_quiz_sessions (
            quiz_id TEXT NOT NULL,
            session_no INTEGER NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (quiz_id, session_no)
        );
        CREATE TABLE IF NOT EXISTS interaction_events (
            id TEXT PRIMARY KEY,
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            component_id TEXT NOT NULL,
            component_type TEXT NOT NULL,
            event_type TEXT NOT NULL,
            session_no INTEGER,
            question_id TEXT,
            option_id TEXT,
            is_correct INTEGER,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS interaction_events_component
            ON interaction_events(component_id, session_no, created_at);
        CREATE INDEX IF NOT EXISTS interaction_events_chat
            ON interaction_events(chat_id, created_at);
    """)
    purge_orphans(conn)


def purge_orphans(conn):
    """Respect chat deletion and retention even when SQLite FK checks are disabled."""
    conn.execute("""DELETE FROM interaction_events
        WHERE NOT EXISTS (SELECT 1 FROM messages m WHERE m.id=interaction_events.message_id)
           OR NOT EXISTS (SELECT 1 FROM chats c WHERE c.id=interaction_events.chat_id)""")
    conn.execute("""DELETE FROM interaction_quizzes
        WHERE NOT EXISTS (SELECT 1 FROM messages m WHERE m.id=interaction_quizzes.message_id)
           OR NOT EXISTS (SELECT 1 FROM chats c WHERE c.id=interaction_quizzes.chat_id)""")
    conn.execute("""DELETE FROM interaction_quiz_sessions
        WHERE NOT EXISTS (SELECT 1 FROM interaction_quizzes q WHERE q.id=interaction_quiz_sessions.quiz_id)""")


def register_quizzes(conn, chat_id, message_id, content):
    """Replace model-provided IDs with IDs bound to the saved message."""
    quiz_index = 0

    def replace(match):
        nonlocal quiz_index
        try:
            envelope = json.loads(match.group(1))
        except (TypeError, ValueError):
            return match.group(0)
        if not isinstance(envelope, dict) or not isinstance(envelope.get("blocks"), list):
            return match.group(0)
        changed = False
        for block in envelope["blocks"]:
            if not isinstance(block, dict) or block.get("type") != "quiz":
                continue
            quiz_index += 1
            quiz_id = "quiz-%d-%d-%d" % (chat_id, message_id, quiz_index)
            block["id"] = quiz_id
            conn.execute("""INSERT OR IGNORE INTO interaction_quizzes
                (id, chat_id, message_id, title, definition_json)
                VALUES (?, ?, ?, ?, ?)""", (
                quiz_id, chat_id, message_id,
                str(block.get("title") or "Knowledge check")[:500],
                json.dumps(block, ensure_ascii=False, separators=(",", ":"))
            ))
            conn.execute("""INSERT OR IGNORE INTO interaction_quiz_sessions
                (quiz_id, session_no) VALUES (?, 1)""", (quiz_id,))
            changed = True
        if not changed:
            return match.group(0)
        return FENCE + "apollo-ui\n" + json.dumps(envelope, ensure_ascii=False, separators=(",", ":")) + "\n" + FENCE

    return QUIZ_FENCE.sub(replace, str(content or ""))


def _quiz(conn, quiz_id):
    row = conn.execute("SELECT * FROM interaction_quizzes WHERE id=?", (quiz_id,)).fetchone()
    if row is None:
        raise InteractionError("Quiz not found", 404)
    return row


def _events(conn, quiz_id, session_no):
    return conn.execute("""SELECT id, question_id, option_id, is_correct, created_at
        FROM interaction_events
        WHERE component_id=? AND component_type='quiz' AND event_type='quiz_answer'
          AND session_no=?
        ORDER BY rowid ASC""", (quiz_id, session_no)).fetchall()


def _session(conn, quiz, session_no):
    definition = json.loads(quiz["definition_json"])
    events = _events(conn, quiz["id"], session_no)
    by_question = {}
    for event in events:
        by_question.setdefault(event["question_id"], []).append(dict(event))
    questions = []
    first_correct = eventually_correct = corrected = 0
    single_attempt = definition.get("allow_retry") is False
    for question in definition["questions"]:
        attempts = by_question.get(question["id"], [])
        first = attempts[0] if attempts else None
        solved = any(event["is_correct"] for event in attempts)
        if first and first["is_correct"]:
            first_correct += 1
        if solved:
            eventually_correct += 1
            if first and not first["is_correct"]:
                corrected += 1
        questions.append({
            "id": question["id"], "question": question["question"],
            "correct_answer_id": question["correct_answer_id"],
            "correct_answer": next((o["label"] for o in question["options"]
                                    if o["id"] == question["correct_answer_id"]), ""),
            "explanation": question.get("explanation", ""),
            "first_answer_id": first["option_id"] if first else None,
            "first_correct": bool(first["is_correct"]) if first else None,
            "eventually_correct": solved, "attempts": attempts,
        })
    summary = {
        "first_attempt_score": first_correct,
        "eventually_correct": eventually_correct,
        "corrected_after_mistake": corrected,
        "total_questions": len(questions),
        "total_attempts": len(events),
        "answered_questions": sum(bool(q["attempts"]) for q in questions),
        "completed": all(q["eventually_correct"] or (single_attempt and q["attempts"])
                         for q in questions),
    }
    return {"session_no": session_no, "questions": questions, "summary": summary}


def snapshot(conn, quiz_id):
    quiz = _quiz(conn, quiz_id)
    sessions = [
        _session(conn, quiz, row["session_no"])
        for row in conn.execute("""SELECT session_no FROM interaction_quiz_sessions
            WHERE quiz_id=? ORDER BY session_no""", (quiz_id,))
    ]
    return {
        "id": quiz["id"], "chat_id": quiz["chat_id"],
        "message_id": quiz["message_id"], "title": quiz["title"],
        "definition": json.loads(quiz["definition_json"]),
        "current_session": quiz["current_session"], "current": sessions[-1],
        "sessions": sessions, "created_at": quiz["created_at"],
        "updated_at": quiz["updated_at"],
    }


def _event_id(value):
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        raise InteractionError("A valid event ID is required")


def submit_answer(conn, quiz_id, payload):
    event_id = _event_id(payload.get("event_id"))
    conn.execute("BEGIN IMMEDIATE")
    try:
        quiz = _quiz(conn, quiz_id)
        existing = conn.execute(
            "SELECT component_id, event_type FROM interaction_events WHERE id=?", (event_id,)
        ).fetchone()
        if existing:
            if existing["component_id"] != quiz_id or existing["event_type"] != "quiz_answer":
                raise InteractionError("Event ID already used", 409)
            result = snapshot(conn, quiz_id)
            conn.commit()
            return result
        try:
            session_no = int(payload.get("session_no", 0))
        except (TypeError, ValueError):
            raise InteractionError("Quiz session is invalid")
        if session_no != quiz["current_session"]:
            raise InteractionError("Quiz session changed; refresh its results", 409)
        definition = json.loads(quiz["definition_json"])
        question_id = str(payload.get("question_id") or "")
        option_id = str(payload.get("option_id") or "")
        question = next((q for q in definition["questions"] if q["id"] == question_id), None)
        if question is None or option_id not in {o["id"] for o in question["options"]}:
            raise InteractionError("Question or answer is invalid")
        attempts = [e for e in _events(conn, quiz_id, session_no) if e["question_id"] == question_id]
        if any(e["is_correct"] for e in attempts) or (attempts and definition.get("allow_retry") is False):
            raise InteractionError("This question is already finished", 409)
        if any(e["option_id"] == option_id for e in attempts):
            raise InteractionError("This answer was already submitted", 409)
        correct = int(option_id == question["correct_answer_id"])
        conn.execute("""INSERT INTO interaction_events
            (id, chat_id, message_id, component_id, component_type, event_type,
             session_no, question_id, option_id, is_correct)
            VALUES (?, ?, ?, ?, 'quiz', 'quiz_answer', ?, ?, ?, ?)""", (
                event_id, quiz["chat_id"], quiz["message_id"], quiz_id,
                session_no, question_id, option_id, correct
            ))
        conn.execute("UPDATE interaction_quizzes SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (quiz_id,))
        result = snapshot(conn, quiz_id)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


def restart(conn, quiz_id, payload):
    event_id = _event_id(payload.get("event_id"))
    conn.execute("BEGIN IMMEDIATE")
    try:
        quiz = _quiz(conn, quiz_id)
        existing = conn.execute(
            "SELECT component_id, event_type FROM interaction_events WHERE id=?", (event_id,)
        ).fetchone()
        if existing:
            if existing["component_id"] != quiz_id or existing["event_type"] != "quiz_restart":
                raise InteractionError("Event ID already used", 409)
            result = snapshot(conn, quiz_id)
            conn.commit()
            return result
        session_no = quiz["current_session"] + 1
        conn.execute(
            "UPDATE interaction_quizzes SET current_session=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (session_no, quiz_id)
        )
        conn.execute(
            "INSERT INTO interaction_quiz_sessions (quiz_id, session_no) VALUES (?, ?)",
            (quiz_id, session_no)
        )
        conn.execute("""INSERT INTO interaction_events
            (id, chat_id, message_id, component_id, component_type, event_type, session_no)
            VALUES (?, ?, ?, ?, 'quiz', 'quiz_restart', ?)""", (
                event_id, quiz["chat_id"], quiz["message_id"], quiz_id, session_no
            ))
        result = snapshot(conn, quiz_id)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


def list_quizzes(conn, chat_id=None, limit=20):
    if chat_id is None:
        rows = conn.execute(
            "SELECT id FROM interaction_quizzes ORDER BY message_id DESC LIMIT ?", (limit,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id FROM interaction_quizzes WHERE chat_id=? ORDER BY message_id DESC LIMIT ?",
            (chat_id, limit)
        ).fetchall()
    return [snapshot(conn, row["id"]) for row in rows]


def context_for_query(conn, chat_id, prompt):
    if not QUIZ_QUERY.search(str(prompt or "")):
        return None
    quizzes = list_quizzes(conn, chat_id, 3)
    if not quizzes and re.search(r"\b(previous|past|older|another|earlier)\b", prompt, re.I):
        quizzes = list_quizzes(conn, None, 3)
    if not quizzes:
        return ("Verified interactive state: No durable quiz results are recorded "
                "for this conversation. Older browser-only attempts cannot be "
                "reconstructed reliably. Do not invent a score.")
    parts = ["Verified Apollo quiz records. Use these exact results; first-attempt scores never change."]
    for quiz in quizzes:
        current = quiz["current"]
        score = current["summary"]
        parts.append(
            "%s (%s), session %d: first-attempt %d/%d; eventually correct %d/%d; "
            "corrected after mistakes %d; attempts %d; completed %s." % (
                quiz["title"], quiz["id"], current["session_no"],
                score["first_attempt_score"], score["total_questions"],
                score["eventually_correct"], score["total_questions"],
                score["corrected_after_mistake"], score["total_attempts"],
                "yes" if score["completed"] else "no"
            )
        )
        for question in current["questions"]:
            if question["first_correct"] is False:
                parts.append(
                    "First-attempt mistake: %s. Correct answer: %s. %s" % (
                        question["question"], question["correct_answer"],
                        question["explanation"]
                    )
                )
        if len(quiz["sessions"]) > 1:
            parts.append("Previous first-attempt scores: " + ", ".join(
                "session %d: %d/%d" % (
                    session["session_no"], session["summary"]["first_attempt_score"],
                    session["summary"]["total_questions"]
                ) for session in quiz["sessions"][:-1]
            ))
    return "\n".join(parts)[:6000]
