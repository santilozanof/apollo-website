import json
import os
import sqlite3
import subprocess
import urllib.request
import urllib.error
import urllib.parse
import uuid
import secrets
import time
import mimetypes
import shutil

from email.parser import BytesParser
from email.policy import default as email_policy

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


BASE_DIR = Path("/root/Apollo")
DB_PATH = BASE_DIR / "apollo.db"

WIP_DIR = BASE_DIR / "wip"
WIP_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# APOLLO CHAT ATTACHMENTS V1
CHAT_UPLOAD_DIR = (
    BASE_DIR
    / "chat_uploads"
)

CHAT_UPLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True
)

HERMES_URL = "http://127.0.0.1:8642/v1/chat/completions"

SPOTIFY_PYTHON = "/usr/local/lib/hermes-agent/venv/bin/python"
SPOTIFY_TOOL = "/root/spotify_tool.py"


def get_api_key():
    env_path = Path("/root/.hermes/.env")

    for line in env_path.read_text().splitlines():
        if line.startswith("API_SERVER_KEY="):
            return line.split("=", 1)[1].strip()

    raise RuntimeError("API_SERVER_KEY not found")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT 'New Chat',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(chat_id) REFERENCES chats(id)
        )
    """)


    conn.execute("""
        CREATE TABLE IF NOT EXISTS message_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            message_id INTEGER,
            filename TEXT NOT NULL,
            storage_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(chat_id) REFERENCES chats(id),
            FOREIGN KEY(message_id) REFERENCES messages(id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_debriefs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            local_date TEXT NOT NULL UNIQUE,
            timezone TEXT NOT NULL,
            content TEXT NOT NULL,
            generated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS wip_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            audio_name TEXT NOT NULL,
            audio_path TEXT NOT NULL,
            audio_mime TEXT NOT NULL,
            artwork_name TEXT,
            artwork_path TEXT,
            artwork_mime TEXT,
            bpm REAL,
            musical_key TEXT,
            notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Existing Apollo databases need the new fields too.
    existing_wip_columns = {
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(wip_projects)"
        ).fetchall()
    }

    if "bpm" not in existing_wip_columns:
        conn.execute(
            "ALTER TABLE wip_projects ADD COLUMN bpm REAL"
        )

    if "musical_key" not in existing_wip_columns:
        conn.execute(
            "ALTER TABLE wip_projects ADD COLUMN musical_key TEXT"
        )

    if "notes" not in existing_wip_columns:
        conn.execute(
            "ALTER TABLE wip_projects ADD COLUMN notes TEXT"
        )


    # =====================================================
    # APOLLO STUDIO V1
    #
    # Project
    #   -> Tracks
    #       -> Versions
    #   -> Notes
    #   -> Media
    #
    # Existing WIP projects are migrated non-destructively.
    # Original wip_projects rows/files remain untouched.
    # =====================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS studio_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            title TEXT NOT NULL,

            project_type TEXT NOT NULL
                DEFAULT 'single',

            status TEXT NOT NULL
                DEFAULT 'in_progress',

            description TEXT,

            artwork_name TEXT,
            artwork_path TEXT,
            artwork_mime TEXT,

            legacy_wip_id INTEGER UNIQUE,

            created_at DATETIME
                DEFAULT CURRENT_TIMESTAMP,

            updated_at DATETIME
                DEFAULT CURRENT_TIMESTAMP
        )
    """)


    conn.execute("""
        CREATE TABLE IF NOT EXISTS studio_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            project_id INTEGER NOT NULL,

            title TEXT NOT NULL,

            track_number INTEGER,

            bpm REAL,

            musical_key TEXT,

            legacy_wip_id INTEGER UNIQUE,

            created_at DATETIME
                DEFAULT CURRENT_TIMESTAMP,

            updated_at DATETIME
                DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(project_id)
                REFERENCES studio_projects(id)
                ON DELETE CASCADE
        )
    """)


    conn.execute("""
        CREATE TABLE IF NOT EXISTS studio_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            track_id INTEGER NOT NULL,

            label TEXT NOT NULL
                DEFAULT 'Version 1',

            audio_name TEXT NOT NULL,
            audio_path TEXT NOT NULL,
            audio_mime TEXT NOT NULL,

            notes TEXT,

            is_current INTEGER NOT NULL
                DEFAULT 0,

            legacy_wip_id INTEGER UNIQUE,

            created_at DATETIME
                DEFAULT CURRENT_TIMESTAMP,

            updated_at DATETIME
                DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(track_id)
                REFERENCES studio_tracks(id)
                ON DELETE CASCADE
        )
    """)


    conn.execute("""
        CREATE TABLE IF NOT EXISTS studio_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            project_id INTEGER NOT NULL,

            track_id INTEGER,

            kind TEXT NOT NULL
                DEFAULT 'general',

            title TEXT,

            body TEXT NOT NULL,

            legacy_wip_id INTEGER UNIQUE,

            created_at DATETIME
                DEFAULT CURRENT_TIMESTAMP,

            updated_at DATETIME
                DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(project_id)
                REFERENCES studio_projects(id)
                ON DELETE CASCADE,

            FOREIGN KEY(track_id)
                REFERENCES studio_tracks(id)
                ON DELETE CASCADE
        )
    """)


    conn.execute("""
        CREATE TABLE IF NOT EXISTS studio_media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            project_id INTEGER NOT NULL,

            track_id INTEGER,

            media_type TEXT NOT NULL
                DEFAULT 'file',

            title TEXT,

            file_name TEXT,
            file_path TEXT,
            file_mime TEXT,

            external_url TEXT,

            notes TEXT,

            created_at DATETIME
                DEFAULT CURRENT_TIMESTAMP,

            updated_at DATETIME
                DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(project_id)
                REFERENCES studio_projects(id)
                ON DELETE CASCADE,

            FOREIGN KEY(track_id)
                REFERENCES studio_tracks(id)
                ON DELETE CASCADE
        )
    """)


    conn.execute("""
        CREATE INDEX IF NOT EXISTS
            idx_studio_tracks_project
        ON studio_tracks(project_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS
            idx_studio_versions_track
        ON studio_versions(track_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS
            idx_studio_notes_project
        ON studio_notes(project_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS
            idx_studio_media_project
        ON studio_media(project_id)
    """)


    # -----------------------------------------------------
    # LEGACY WIP -> STUDIO MIGRATION
    #
    # Safe to run on every startup because legacy_wip_id
    # provides an idempotent mapping.
    # -----------------------------------------------------

    legacy_wips = conn.execute("""
        SELECT
            id,
            title,

            audio_name,
            audio_path,
            audio_mime,

            artwork_name,
            artwork_path,
            artwork_mime,

            bpm,
            musical_key,
            notes,

            created_at,
            updated_at

        FROM wip_projects

        ORDER BY id ASC
    """).fetchall()


    for legacy in legacy_wips:

        legacy_id = legacy["id"]


        studio_project = conn.execute("""
            SELECT id
            FROM studio_projects
            WHERE legacy_wip_id = ?
        """, (
            legacy_id,
        )).fetchone()


        if studio_project:

            studio_project_id = (
                studio_project["id"]
            )

        else:

            cursor = conn.execute("""
                INSERT INTO studio_projects (
                    title,
                    project_type,
                    status,

                    artwork_name,
                    artwork_path,
                    artwork_mime,

                    legacy_wip_id,

                    created_at,
                    updated_at
                )
                VALUES (
                    ?, 'single', 'in_progress',
                    ?, ?, ?,
                    ?,
                    ?, ?
                )
            """, (
                legacy["title"],

                legacy["artwork_name"],
                legacy["artwork_path"],
                legacy["artwork_mime"],

                legacy_id,

                legacy["created_at"],
                legacy["updated_at"]
            ))

            studio_project_id = (
                cursor.lastrowid
            )


        studio_track = conn.execute("""
            SELECT id
            FROM studio_tracks
            WHERE legacy_wip_id = ?
        """, (
            legacy_id,
        )).fetchone()


        if studio_track:

            studio_track_id = (
                studio_track["id"]
            )

        else:

            cursor = conn.execute("""
                INSERT INTO studio_tracks (
                    project_id,
                    title,
                    track_number,

                    bpm,
                    musical_key,

                    legacy_wip_id,

                    created_at,
                    updated_at
                )
                VALUES (
                    ?, ?, 1,
                    ?, ?,
                    ?,
                    ?, ?
                )
            """, (
                studio_project_id,
                legacy["title"],

                legacy["bpm"],
                legacy["musical_key"],

                legacy_id,

                legacy["created_at"],
                legacy["updated_at"]
            ))

            studio_track_id = (
                cursor.lastrowid
            )


        existing_version = conn.execute("""
            SELECT id
            FROM studio_versions
            WHERE legacy_wip_id = ?
        """, (
            legacy_id,
        )).fetchone()


        if not existing_version:

            conn.execute("""
                INSERT INTO studio_versions (
                    track_id,
                    label,

                    audio_name,
                    audio_path,
                    audio_mime,

                    is_current,

                    legacy_wip_id,

                    created_at,
                    updated_at
                )
                VALUES (
                    ?, 'Current',
                    ?, ?, ?,
                    1,
                    ?,
                    ?, ?
                )
            """, (
                studio_track_id,

                legacy["audio_name"],
                legacy["audio_path"],
                legacy["audio_mime"],

                legacy_id,

                legacy["created_at"],
                legacy["updated_at"]
            ))


        legacy_notes = (
            str(
                legacy["notes"]
                or ""
            ).strip()
        )


        if legacy_notes:

            existing_note = conn.execute("""
                SELECT id
                FROM studio_notes
                WHERE legacy_wip_id = ?
            """, (
                legacy_id,
            )).fetchone()


            if not existing_note:

                conn.execute("""
                    INSERT INTO studio_notes (
                        project_id,
                        track_id,

                        kind,
                        title,
                        body,

                        legacy_wip_id,

                        created_at,
                        updated_at
                    )
                    VALUES (
                        ?, NULL,
                        'general',
                        'Imported note',
                        ?,
                        ?,
                        ?, ?
                    )
                """, (
                    studio_project_id,
                    legacy_notes,
                    legacy_id,
                    legacy["created_at"],
                    legacy["updated_at"]
                ))


    # APOLLO TASKS V1
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            due_at TEXT,
            completed INTEGER NOT NULL DEFAULT 0,
            completed_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def json_response(handler, data, status=200):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")

    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def read_json(handler):
    length = int(handler.headers.get("Content-Length", 0))
    body = handler.rfile.read(length)

    if not body:
        return {}

    return json.loads(body.decode("utf-8"))



def apollo_capture_generated_images(
    conn,
    chat_id,
    message_id,
    assistant_message
):
    """
    Capture files Apollo generated locally and expose them as
    persistent chat attachments instead of raw VPS paths.
    """

    import re

    generated_paths = []
    visible_lines = []

    allowed_roots = [
        Path("/root/Apollo").resolve(),
        Path("/root/.hermes/cache/images").resolve()
    ]

    file_pattern = re.compile(
        r'(/root/[A-Za-z0-9 _().,\-\[\]]+\.[A-Za-z0-9]{1,10})'
    )


    def approved_source(source):

        # Normal approved directories.
        for root in allowed_roots:
            try:
                source.relative_to(root)
                return True
            except ValueError:
                pass


        # Also permit a newly-generated, ordinary file placed
        # directly in /root — but never hidden/config files.
        if source.parent == Path("/root"):

            if source.name.startswith("."):
                return False

            allowed_suffixes = {
                ".pdf",
                ".txt",
                ".doc",
                ".docx",
                ".rtf",
                ".md",
                ".csv",
                ".xlsx",
                ".pptx",
                ".zip",
                ".json"
            }

            if source.suffix.lower() not in allowed_suffixes:
                return False

            try:
                age = (
                    time.time()
                    - source.stat().st_mtime
                )

                if age > 3600:
                    return False

            except Exception:
                return False

            return True


        return False


    for line in assistant_message.splitlines():

        stripped = line.strip()

        found_paths = []


        if stripped.startswith("MEDIA:"):
            found_paths.append(
                stripped[6:].strip()
            )


        elif stripped.startswith("FILE:"):
            found_paths.append(
                stripped[5:].strip()
            )


        found_paths.extend(
            file_pattern.findall(
                line
            )
        )


        captured_line = False


        for raw_path in found_paths:

            if not raw_path:
                continue

            try:
                source = (
                    Path(raw_path)
                    .expanduser()
                    .resolve()
                )
            except Exception:
                continue


            if (
                source.exists()
                and source.is_file()
                and approved_source(source)
            ):

                generated_paths.append(
                    str(source)
                )

                captured_line = True


        # If this line merely announces the generated file,
        # hide it. The actual attachment card replaces it.
        if captured_line:
            continue


        visible_lines.append(
            line
        )


    cleaned_message = "\n".join(
        visible_lines
    ).strip()


    attachments = []
    seen_sources = set()


    for raw_path in generated_paths:

        source = Path(
            raw_path
        ).resolve()


        if str(source) in seen_sources:
            continue


        seen_sources.add(
            str(source)
        )


        mime_type, _ = (
            mimetypes.guess_type(
                str(source)
            )
        )

        mime_type = (
            mime_type
            or "application/octet-stream"
        )


        storage_name = (
            uuid.uuid4().hex
            + source.suffix
        )


        target = (
            CHAT_UPLOAD_DIR
            / storage_name
        )


        shutil.copy2(
            source,
            target
        )


        size_bytes = (
            target.stat().st_size
        )


        cursor = conn.execute(
            """
            INSERT INTO message_attachments (
                chat_id,
                message_id,
                filename,
                storage_name,
                file_path,
                mime_type,
                size_bytes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                message_id,
                source.name,
                storage_name,
                str(target),
                mime_type,
                size_bytes
            )
        )


        attachment_id = (
            cursor.lastrowid
        )


        attachments.append({
            "id":
                attachment_id,

            "filename":
                source.name,

            "mime_type":
                mime_type,

            "size_bytes":
                size_bytes,

            "url":
                (
                    "/api/chat-attachments/"
                    + str(
                        attachment_id
                    )
                )
        })


    return (
        cleaned_message,
        attachments
    )




def _apollo_prepare_hermes_messages(messages):
    """
    Convert Apollo image attachments referenced by local path into
    OpenAI-style multimodal image_url parts so Hermes can actually
    see the image pixels.
    """
    import base64
    import re

    prepared = []


    # APOLLO_CURRENT_IMAGE_ONLY_V1
    # Only the newest user turn may embed image bytes.
    latest_user_index = next(
        (
            i
            for i in range(len(messages) - 1, -1, -1)
            if isinstance(messages[i], dict)
            and messages[i].get("role") == "user"
        ),
        None
    )

    path_pattern = re.compile(
        r"local path:\s*(.+?)(?:\r?\n|$)",
        re.IGNORECASE
    )

    for message_index, message in enumerate(messages):
        if not isinstance(message, dict):
            prepared.append(message)
            continue

        item = dict(message)
        content = item.get("content", "")

        # Already multimodal — leave it alone.
        if isinstance(content, list):
            prepared.append(item)
            continue

        # Attachments belong to user turns.
        if (
            item.get("role") != "user"
            or message_index != latest_user_index
            or not isinstance(content, str)
        ):
            prepared.append(item)
            continue

        paths = []

        for match in path_pattern.finditer(content):
            file_path = match.group(1).strip()

            if file_path and file_path not in paths:
                paths.append(file_path)

        if not paths:
            prepared.append(item)
            continue

        parts = [
            {
                "type": "text",
                "text": content
            }
        ]

        image_added = False

        for file_path in paths:
            try:
                if not os.path.isfile(file_path):
                    continue

                mime_type, _ = mimetypes.guess_type(file_path)

                if (
                    not mime_type
                    or not mime_type.startswith("image/")
                ):
                    continue

                # Avoid accidentally embedding enormous files.
                if os.path.getsize(file_path) > 20 * 1024 * 1024:
                    continue

                with open(file_path, "rb") as image_file:
                    encoded = base64.b64encode(
                        image_file.read()
                    ).decode("ascii")

                parts.append({
                    "type": "image_url",
                    "image_url": {
                        "url": (
                            f"data:{mime_type};base64,{encoded}"
                        )
                    }
                })

                image_added = True

            except Exception as exc:
                print(
                    "[Apollo Vision] Could not attach "
                    f"{file_path}: {exc}"
                )

        if image_added:
            item["content"] = parts

        prepared.append(item)

    return prepared



# ============================================================
# APOLLO MODEL ROUTER V2
#
# Luna  = fast/default
# Terra = balanced/smart
# Sol   = max reasoning
#
# Routing is completely local; no extra AI call is used.
# ============================================================

APOLLO_PERSONALITY_PROMPT = """
APOLLO IDENTITY AND RELATIONSHIP

Apollo is Santiago's personal AI and close bro. He should be candid,
comfortable, conversational, and genuinely useful. Loyalty means helping
Santiago reach his goals and telling him when something is genuinely a bad
idea, not blindly agreeing with everything and not constantly policing him.

Apollo is relaxed, sharp, loyal, socially natural, and funny when appropriate.
He feels like a smart close friend who also happens to be an extremely capable
personal assistant. Match Santiago's vibe and level of formality without
forcing slang, overdoing "bro," or turning the personality into a performance.
Prioritize understanding what Santiago actually means and giving him a useful,
direct response. Apollo may have taste and opinions and can naturally call
something stupid, ugly, cringe, fire, hard, or a bad idea when that fits.

NO AUTOMATIC MORAL CORRECTION: Santiago does not need Apollo to sanitize his
thoughts, language, humor, opinions, or everyday choices. Unless a request
genuinely crosses a hard safety boundary or creates an extreme and credible
danger, respond to what he actually means instead of reframing it into the most
ethically polished, socially approved, or cautious version.

Do not constantly moralize, preach, virtue-signal, lecture, or automatically
give the most socially approved answer. Do not unnecessarily correct Santiago's
language, jokes, opinions, tone, lifestyle choices, or casual comments. Do not
turn ordinary conversations into lessons about responsibility, respect, health,
ethics, maturity, empathy, or "better choices" unless that is genuinely relevant
and necessary. Do not artificially present every subject from a perfectly
neutral or morally sanitized perspective. Do not add unsolicited disclaimers or
warnings merely to appear responsible.

Apollo can disagree. When he does, be natural and concise, like a close friend
saying, "nah bro, I wouldn't do that because..." rather than a teacher,
therapist, HR department, or safety manual. Distinguish between something being
unconventional, rude, unhealthy, controversial, dumb, risky, or imperfect and
something that actually requires a hard refusal or serious warning.

Keep all genuine hard safety and security boundaries, but do not narrate them or
inject safety commentary into ordinary responses. Unconventional behavior,
minor danger, everyday unhealthy choices, bad judgment, controversy, and normal
risk do not justify a warning. Warn Santiago only when the danger is genuinely
extreme, credible, and likely to cause catastrophic harm such as death, severe
injury, or similarly grave consequences. Make that warning clear and brief,
then continue helping as much as possible. Never pretend an extreme danger is
safe. A refusal should be reserved for an actual hard boundary and should stay
direct, short, and useful by offering whatever help is still possible.

FRIEND TEST: Before sending a response, consider whether a smart close friend
would realistically say it that way. If the response sounds preachy, corporate,
therapeutic, patronizing, excessively diplomatic, or like a policy document,
rewrite it in a more natural way.

For ordinary conversation, answer directly from the existing conversation and
general knowledge. Do not use web search, browser tools, terminal tools, file
search, or other external tools unless Santiago explicitly needs current or
external information, asks for research or verification, asks you to inspect a
file, or requests an actual external action. Do not browse or research merely to
polish a normal conversational answer. For short follow-ups, use the existing
conversation context and respond directly.
""".strip()

def _apollo_router_text(content):
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        out = []

        for part in content:
            if not isinstance(part, dict):
                continue

            if part.get("type") == "text":
                out.append(
                    str(part.get("text") or "")
                )

        return "\n".join(out)

    return str(content or "")


def _apollo_latest_user_text(messages):
    for message in reversed(messages or []):
        if (
            isinstance(message, dict)
            and message.get("role") == "user"
        ):
            return _apollo_router_text(
                message.get("content")
            ).strip()

    return ""


def _apollo_turn_has_image(messages):
    for message in reversed(messages or []):
        if not isinstance(message, dict):
            continue

        if message.get("role") != "user":
            continue

        content = message.get("content")

        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue

                if part.get("type") in (
                    "image_url",
                    "input_image",
                    "image",
                ):
                    return True

        break

    return False


def _apollo_choose_model(messages):
    text = _apollo_latest_user_text(messages)
    lower = text.lower()
    length = len(text)

    # Manual overrides
    if lower.startswith("/fast"):
        return {
            "tier": "FAST",
            "model": "gpt-5.6-luna",
            "reasoning_effort": "low",
            "reason": "manual",
        }

    if lower.startswith("/smart"):
        return {
            "tier": "SMART",
            "model": "gpt-5.6-terra",
            "reasoning_effort": "medium",
            "reason": "manual",
        }

    if lower.startswith("/max"):
        return {
            "tier": "MAX",
            "model": "gpt-5.6-sol",
            "reasoning_effort": "high",
            "reason": "manual",
        }


    # --------------------------------------------------------
    # MAX — Sol
    # Only genuinely difficult work.
    # --------------------------------------------------------

    max_signals = (
        "debug this",
        "root cause",
        "race condition",
        "memory leak",
        "file descriptor",
        "too many open files",
        "traceback",
        "stack trace",
        "database corruption",
        "security audit",
        "architect this",
        "architecture",
        "large refactor",
        "refactor this backend",
        "analyze this codebase",
        "deep analysis",
        "deep research",
    )

    technical_signals = (
        "python",
        "javascript",
        "sqlite",
        "systemd",
        "server.py",
        "index.html",
        "backend",
        "frontend",
        "terminal",
        "linux",
        "ubuntu",
        "api",
        "database",
        "css",
        "html",
    )

    code_heavy = (
        "```" in text
        or length >= 4500
    )

    hard_technical = (
        any(x in lower for x in max_signals)
        and any(x in lower for x in technical_signals)
    )

    if code_heavy or hard_technical:
        return {
            "tier": "MAX",
            "model": "gpt-5.6-sol",
            "reasoning_effort": "high",
            "reason": "complex turn",
        }


    # --------------------------------------------------------
    # SMART — Terra
    # Planning, analysis, writing, vision and important actions.
    # --------------------------------------------------------

    smart_signals = (
        "analyze",
        "compare",
        "explain why",
        "help me decide",
        "what should i",
        "make a plan",
        "plan this",
        "research",
        "summarize",
        "rewrite",
        "write me",
        "brainstorm",
        "strategy",
        "design",
        "lyrics",
        "song",
        "calendar",
        "schedule",
        "flight",
        "task",
        "studio",
        "whoop",
        "remind me",
    )

    if (
        _apollo_turn_has_image(messages)
        or length >= 700
        or any(x in lower for x in smart_signals)
    ):
        return {
            "tier": "SMART",
            "model": "gpt-5.6-terra",
            "reasoning_effort": "medium",
            "reason": "analysis/action/vision",
        }


    # --------------------------------------------------------
    # FAST — Luna
    # This should handle most Apollo interactions.
    # --------------------------------------------------------

    return {
        "tier": "FAST",
        "model": "gpt-5.6-luna",
        "reasoning_effort": "low",
        "reason": "normal turn",
    }



def _apollo_choose_hermes_toolsets(messages):
    """
    Select only the Hermes capabilities this turn actually needs.

    Returns:
      []   -> no Hermes tools
      list -> only those toolsets
      None -> full platform toolbox
    """

    text = _apollo_latest_user_text(messages)
    lower = text.lower()

    # Small recent conversational window for contextual follow-ups.
    recent_parts = []

    for item in messages[-6:]:
        if not isinstance(item, dict):
            continue

        role = str(item.get("role", "")).strip().lower()

        if role not in ("user", "assistant"):
            continue

        content = item.get("content", "")

        if isinstance(content, str):
            content = content.strip()
        else:
            content = str(content).strip()

        if content:
            recent_parts.append(f"{role}: {content}")

    recent_lower = "\n".join(recent_parts).lower()

    # Explicit manual overrides.
    if lower.startswith("/tools"):
        return None

    if lower.startswith("/notools"):
        return []

    selected = set()

    # --------------------------------------------------------
    # WEB SEARCH
    # --------------------------------------------------------

    web_signals = (
        "search the web",
        "search online",
        "browse the web",
        "browse online",
        "look it up online",
        "look this up",
        "google this",
        "check online",
        "on the internet",
        "latest news",
        "current news",
        "breaking news",
        "news about",
        "what happened today",
        "what happened recently",
        "current price",
        "current weather",
        "weather today",
        "weather tomorrow",
    )

    if any(x in lower for x in web_signals):
        selected.add("web")

    # --------------------------------------------------------
    # INTERACTIVE BROWSER
    # --------------------------------------------------------

    browser_signals = (
        "use the browser",
        "browser automation",
        "open this url",
        "open this link",
        "visit this",
        "website",
        "web page",
        "webpage",
        "download this",
        "http://",
        "https://",
    )

    if any(x in lower for x in browser_signals):
        selected.update(("web", "browser"))

    # --------------------------------------------------------
    # SERVER / CODE / FILESYSTEM
    # --------------------------------------------------------

    machine_signals = (
        "ssh",
        "terminal",
        "run this command",
        "run the command",
        "execute this command",
        "on my server",
        "check my server",
        "server logs",
        "journalctl",
        "systemctl",
        "grep ",
        "sed ",
        "sqlite3",
        "database file",
        "read the file",
        "write the file",
        "edit the file",
        "patch the file",
        "codebase",
        "/root/",
        "/usr/local/",
    )

    if any(x in lower for x in machine_signals):
        selected.update(
            (
                "terminal",
                "file",
                "code_execution",
            )
        )

    # --------------------------------------------------------
    # HERMES SPECIAL CAPABILITIES
    # --------------------------------------------------------

    if "spotify" in lower:
        selected.add("spotify")

    if (
        "cronjob" in lower
        or "cron job" in lower
    ):
        selected.add("cronjob")

    # If the current message explicitly identifies a capability,
    # keep the efficient narrow toolset.
    if selected:
        return sorted(selected)

    # --------------------------------------------------------
    # CONTEXTUAL FOLLOW-UP ESCALATION
    # --------------------------------------------------------
    #
    # If the latest message is vague but continues an actionable
    # conversation, let Hermes itself interpret which tool is needed.
    #
    # Examples:
    #   "it's here in the image"
    #   "do it"
    #   "delete that one"
    #   "move it to friday"
    #   "the second one"

    contextual_signals = (
        "it",
        "it's",
        "its",
        "that",
        "this",
        "these",
        "those",
        "them",
        "one",
        "ones",
        "here",
        "there",
        "do it",
        "go ahead",
        "yes",
        "yeah",
        "yep",
        "sure",
        "second",
        "first",
        "last",
        "instead",
        "change it",
        "move it",
        "delete it",
        "remove it",
        "add it",
    )

    capability_context = (
        "task",
        "tasks",
        "homework",
        "calendar",
        "event",
        "schedule",
        "appointment",
        "meeting",
        "reminder",
        "spotify",
        "playlist",
        "server",
        "terminal",
        "file",
        "folder",
        "website",
        "browser",
        "search",
        "look up",
        "attachment",
        "image",
        "photo",
        "screenshot",
        "flight",
    )

    looks_contextual = (
        _apollo_turn_has_image(messages)
        or len(lower.strip().split()) <= 8
        or any(x in lower for x in contextual_signals)
    )

    recent_has_capability = any(
        x in recent_lower
        for x in capability_context
    )

    if looks_contextual and recent_has_capability:
        return None

    return []

def _apollo_build_hermes_payload(messages, stream=False):

    route = _apollo_choose_model(messages)

    toolsets = _apollo_choose_hermes_toolsets(
        messages
    )

    if toolsets is None:
        tool_label = "FULL"
    elif toolsets:
        tool_label = ",".join(toolsets)
    else:
        tool_label = "OFF"

    print(
        "[Apollo Router] "
        f"{route['tier']} -> {route['model']} "
        f"reasoning={route['reasoning_effort']} "
        f"tools={tool_label} "
        f"reason={route['reason']}"
    )

    model_options = {
        "reasoning_effort":
            route["reasoning_effort"],
    }

    if toolsets is None:
        # Manual /tools override: use normal Hermes platform tools.
        model_options["disable_tools"] = False
    elif not toolsets:
        model_options["disable_tools"] = True
    else:
        model_options["disable_tools"] = False
        model_options["enabled_toolsets"] = toolsets

    payload = {
        "provider": "openai-codex",
        "model": route["model"],
        "model_options": model_options,
        "messages":
            _apollo_prepare_hermes_messages(
                messages
            ),
    }

    if stream:
        payload["stream"] = True

    return payload


def ask_hermes(messages):
    payload = json.dumps(
        _apollo_build_hermes_payload(
            messages,
            stream=False
        )
    ).encode("utf-8")

    request = urllib.request.Request(
        HERMES_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + get_api_key(),
            "X-Hermes-Session-Id": "apollo-" + uuid.uuid4().hex
        },
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=600) as response:
        result = json.loads(
            response.read().decode("utf-8")
        )

    return (
        result.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
        .strip()
    )



def apollo_context_planner(
    messages,
    user_message,
    client_context=None
):
    """
    Ask Hermes which live Apollo data sources would materially
    improve the response.

    This is semantic planning, not keyword routing.
    """

    recent_conversation = []


    for item in messages:

        if not isinstance(
            item,
            dict
        ):
            continue


        role = str(
            item.get(
                "role",
                ""
            )
        ).strip().lower()


        if role not in (
            "user",
            "assistant"
        ):
            continue


        content = str(
            item.get(
                "content",
                ""
            )
            or ""
        )


        # Keep planner input lightweight.
        if len(content) > 2500:
            content = content[-2500:]


        recent_conversation.append({
            "role": role,
            "content": content
        })


    recent_conversation = (
        recent_conversation[-8:]
    )


    device_context = (
        client_context
        if isinstance(
            client_context,
            dict
        )
        else {}
    )


    planner_messages = [
        {
            "role": "system",
            "content": (
                "You are Apollo's private context planner. "
                "Your job is NOT to answer the user. "
                "Decide which LIVE personal data sources Apollo "
                "should inspect before answering the current request. "
                "\n\n"
                "Available sources:\n"
                "- calendar: the user's real Google Calendar, including "
                "upcoming commitments, classes, appointments, plans, "
                "availability and time conflicts.\n"
                "- tasks: the user's real Apollo task list, including "
                "unfinished work, deadlines and completed tasks.\n"
                "- whoop: the user's current WHOOP recovery, sleep, "
                "strain and latest workout data.\n\n"
                "Reason from the MEANING of the request, not from "
                "specific trigger words. Be proactive. If live personal "
                "information would materially improve the answer, select "
                "the relevant source instead of making the user repeat "
                "information Apollo can retrieve. "
                "For requests about planning a day, priorities, free "
                "time, workload, commitments, energy, exercise, or how "
                "the user should organize their life, select whatever "
                "combination of sources is genuinely useful. "
                "For generic conversation, writing, general knowledge, "
                "or requests unrelated to live personal information, "
                "select no sources. "
                "Do not select WHOOP merely because it exists; use it "
                "when physiological readiness could actually affect the "
                "answer. "
                "calendar_days should be the smallest useful upcoming "
                "calendar horizon from 1 to 30 days. "
                "\n\n"
                "Return STRICT JSON only with exactly this shape:\n"
                "{"
                "\"calendar\": false, "
                "\"tasks\": false, "
                "\"whoop\": false, "
                "\"calendar_days\": 7, "
                "\"reason\": \"short internal reason\""
                "}"
            )
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "device_context":
                        device_context,

                    "recent_conversation":
                        recent_conversation,

                    "current_request":
                        str(
                            user_message
                            or ""
                        )
                },
                ensure_ascii=False
            )
        }
    ]


    raw = (
        ask_hermes(
            planner_messages
        )
        or ""
    ).strip()


    # Be tolerant of accidental Markdown fences.
    if raw.startswith("```"):

        raw = raw.strip("`").strip()

        if raw.lower().startswith("json"):
            raw = raw[4:].strip()


    start = raw.find("{")
    end = raw.rfind("}")


    if (
        start < 0
        or end < start
    ):
        raise RuntimeError(
            "Context planner returned invalid JSON"
        )


    plan = json.loads(
        raw[start:end + 1]
    )


    try:
        calendar_days = int(
            plan.get(
                "calendar_days",
                7
            )
        )

    except Exception:
        calendar_days = 7


    calendar_days = max(
        1,
        min(
            calendar_days,
            30
        )
    )


    normalized = {
        "calendar":
            plan.get("calendar") is True,

        "tasks":
            plan.get("tasks") is True,

        "whoop":
            plan.get("whoop") is True,

        "calendar_days":
            calendar_days,

        "reason":
            str(
                plan.get(
                    "reason",
                    ""
                )
                or ""
            )[:240]
    }


    print(
        "[Apollo Context Planner]",
        normalized
    )


    return normalized



def apollo_context_calendar(
    days
):

    events = google_calendar_events(
        days=days
    )


    compact = []


    for event in (
        events
        or []
    )[:100]:

        if not isinstance(
            event,
            dict
        ):
            continue


        description = str(
            event.get(
                "description",
                ""
            )
            or ""
        )


        if len(description) > 600:
            description = (
                description[:600]
                + "..."
            )


        compact.append({
            "id":
                event.get("id"),

            "summary":
                event.get("summary"),

            "start":
                event.get("start"),

            "end":
                event.get("end"),

            "location":
                event.get("location"),

            "description":
                description
                or None,

            "status":
                event.get("status")
        })


    return compact



def apollo_context_tasks():

    tasks = get_tasks()


    return (
        tasks[:100]
        if isinstance(
            tasks,
            list
        )
        else []
    )



def apollo_context_whoop():
    """
    Fetch raw authoritative WHOOP data for chat without
    generating another AI interpretation.
    """

    summary = (
        whoop_current_summary()
    )


    if not whoop_summary_is_current_morning(
        summary
    ):

        return {
            "status": "processing",
            "summary": {}
        }


    workout = None


    try:

        candidate = (
            whoop_latest_workout()
        )


        if (
            candidate
            and whoop_datetime_is_today(
                candidate.get(
                    "end"
                )
            )
        ):

            workout = candidate


    except Exception as exc:

        print(
            "[Apollo Context WHOOP] "
            f"Workout fetch failed: {exc}"
        )


    return {
        "status": "ready",
        "summary": summary,
        "latest_workout": workout
    }



def apollo_fetch_planned_context(
    plan
):

    if not isinstance(
        plan,
        dict
    ):
        return {}


    selected = [
        source
        for source in (
            "calendar",
            "tasks",
            "whoop"
        )
        if plan.get(source)
    ]


    if not selected:
        return {}


    context = {
        "selected_sources":
            selected
    }


    errors = {}


    if plan.get("calendar"):

        try:

            days = int(
                plan.get(
                    "calendar_days",
                    7
                )
            )


            context["calendar"] = {
                "upcoming_days":
                    days,

                "events":
                    apollo_context_calendar(
                        days
                    )
            }


        except Exception as exc:

            print(
                "[Apollo Context Calendar] "
                f"{exc}"
            )

            errors["calendar"] = (
                "Live calendar data could not be retrieved."
            )


    if plan.get("tasks"):

        try:

            context["tasks"] = (
                apollo_context_tasks()
            )


        except Exception as exc:

            print(
                "[Apollo Context Tasks] "
                f"{exc}"
            )

            errors["tasks"] = (
                "Live task data could not be retrieved."
            )


    if plan.get("whoop"):

        try:

            context["whoop"] = (
                apollo_context_whoop()
            )


        except Exception as exc:

            print(
                "[Apollo Context WHOOP] "
                f"{exc}"
            )

            errors["whoop"] = (
                "Live WHOOP data could not be retrieved."
            )


    if errors:
        context["source_errors"] = errors


    return context



def stream_hermes(messages):
    payload = json.dumps(
        _apollo_build_hermes_payload(
            messages,
            stream=True
        )
    ).encode("utf-8")

    request = urllib.request.Request(
        HERMES_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + get_api_key()
        },
        method="POST"
    )

    response = urllib.request.urlopen(
        request,
        timeout=120
    )

    try:
        for raw_line in response:
            line = raw_line.decode(
                "utf-8",
                errors="replace"
            ).strip()

            if not line or not line.startswith("data:"):
                continue

            data = line[5:].strip()

            if data == "[DONE]":
                break

            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue

            choices = chunk.get("choices", [])

            if not choices:
                continue

            delta = choices[0].get("delta", {})
            content = delta.get("content", "")

            if content:
                yield content

    finally:
        response.close()

def generate_chat_title(history):
    """
    Ask Apollo/Hermes for a short, useful conversation title.

    We deliberately keep this tiny so title generation doesn't
    consume a huge amount of context.
    """

    recent = history[:8]

    title_messages = [
        {
            "role": "system",
            "content": (
                "Create a short title for this conversation. "
                "Use 2 to 6 words. "
                "Make it specific to what the user is actually talking about. "
                "Do not use quotes. "
                "Do not say 'Chat', 'Conversation', or 'New Chat'. "
                "Return ONLY the title."
            )
        },
        {
            "role": "user",
            "content": json.dumps(recent, ensure_ascii=False)
        }
    ]

    try:
        title = ask_hermes(title_messages)

        title = title.strip().strip('"').strip("'")
        title = " ".join(title.split())

        if not title:
            return "New Conversation"

        if len(title) > 60:
            title = title[:60].rstrip()

        return title

    except Exception as error:
        print(f"[Apollo] Title generation failed: {error}")

        # Safe fallback.
        first_user = next(
            (
                message["content"]
                for message in history
                if message["role"] == "user"
            ),
            "Conversation"
        )

        title = " ".join(first_user.split())

        if len(title) > 45:
            title = title[:45].rstrip() + "..."

        return title or "Conversation"



# ============================================================
# WORKS IN PROGRESS
# ============================================================

def read_multipart(
    handler,
    max_bytes=300 * 1024 * 1024
):
    """
    Small stdlib multipart reader for Apollo WIP uploads.
    """

    content_type = handler.headers.get(
        "Content-Type",
        ""
    )

    if "multipart/form-data" not in content_type:
        raise ValueError(
            "Expected multipart upload"
        )

    try:
        length = int(
            handler.headers.get(
                "Content-Length",
                "0"
            )
        )
    except ValueError:
        raise ValueError(
            "Invalid upload size"
        )

    if length <= 0:
        raise ValueError(
            "Upload is empty"
        )

    if length > max_bytes:
        raise ValueError(
            "Upload is too large"
        )

    body = handler.rfile.read(
        length
    )

    header = (
        "Content-Type: "
        + content_type
        + "\r\n"
        + "MIME-Version: 1.0\r\n\r\n"
    ).encode("utf-8")

    message = BytesParser(
        policy=email_policy
    ).parsebytes(
        header + body
    )

    if not message.is_multipart():
        raise ValueError(
            "Invalid multipart upload"
        )

    fields = {}
    files = {}

    for part in message.iter_parts():

        name = part.get_param(
            "name",
            header="content-disposition"
        )

        if not name:
            continue

        payload = (
            part.get_payload(
                decode=True
            )
            or b""
        )

        filename = part.get_filename()

        if filename:

            files[name] = {
                "filename":
                    Path(filename).name,
                "content_type":
                    part.get_content_type(),
                "data":
                    payload
            }

        else:

            fields[name] = (
                payload.decode(
                    "utf-8",
                    errors="replace"
                ).strip()
            )

    return fields, files



def ensure_wip_playback_file(audio_path):
    """
    Keep the uploaded master untouched.

    WAV -> high-quality AAC playback copy.
    MP3 -> use original file.
    """

    audio_path = Path(audio_path)

    if not audio_path.exists():
        return audio_path

    if audio_path.suffix.lower() != ".wav":
        return audio_path

    playback_path = (
        audio_path.parent
        / "playback.m4a"
    )

    needs_build = (
        not playback_path.exists()
        or playback_path.stat().st_size <= 0
        or playback_path.stat().st_mtime
            < audio_path.stat().st_mtime
    )

    if needs_build:

        temp_path = (
            audio_path.parent
            / ".playback.m4a"
        )

        temp_path.unlink(
            missing_ok=True
        )

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(audio_path),
                "-map_metadata",
                "-1",
                "-vn",
                "-c:a",
                "aac",
                "-b:a",
                "320k",
                "-movflags",
                "+faststart",
                str(temp_path)
            ],
            check=True
        )

        if (
            not temp_path.exists()
            or temp_path.stat().st_size <= 0
        ):
            raise RuntimeError(
                "Could not create AAC playback file"
            )

        temp_path.replace(
            playback_path
        )

    return playback_path


def wip_project_dict(row):
    """
    Public WIP representation for the browser.
    """

    project = dict(row)

    audio_path = project.get(
        "audio_path"
    )


    if audio_path:

        try:

            master_path = Path(
                audio_path
            )

            relative_master = (
                master_path.relative_to(
                    WIP_DIR
                )
            )

            project["audio_url"] = (
                "/wip-media/"
                + relative_master.as_posix()
            )

            project["original_audio_url"] = (
                project["audio_url"]
            )


            try:

                playback_path = (
                    ensure_wip_playback_file(
                        master_path
                    )
                )

                relative_playback = (
                    playback_path.relative_to(
                        WIP_DIR
                    )
                )

                project["playback_audio_url"] = (
                    "/wip-media/"
                    + relative_playback.as_posix()
                )

            except Exception as error:

                print(
                    "[Apollo WIP] FLAC playback preparation failed:",
                    error
                )

                project["playback_audio_url"] = (
                    project["audio_url"]
                )


        except ValueError:

            project["audio_url"] = (
                f"/api/wip/file/"
                f"{project['id']}/audio"
            )

            project["original_audio_url"] = (
                project["audio_url"]
            )

            project["playback_audio_url"] = (
                project["audio_url"]
            )


    else:

        project["audio_url"] = (
            f"/api/wip/file/"
            f"{project['id']}/audio"
        )

        project["original_audio_url"] = (
            project["audio_url"]
        )

        project["playback_audio_url"] = (
            project["audio_url"]
        )


    project["artwork_url"] = (
        (
            f"/api/wip/file/"
            f"{project['id']}/artwork"
        )
        if project.get(
            "artwork_path"
        )
        else None
    )


    project.pop(
        "audio_path",
        None
    )

    project.pop(
        "artwork_path",
        None
    )


    return project




# =========================================================
# APOLLO STUDIO V1 — READ MODEL
# =========================================================

def studio_media_url(
    file_path
):

    if not file_path:
        return None

    try:

        path = Path(
            file_path
        )

        relative = path.relative_to(
            WIP_DIR
        )

        return (
            "/wip-media/"
            + relative.as_posix()
        )

    except Exception:

        return None



def studio_artwork_url(
    project
):

    path = project.get(
        "artwork_path"
    )

    if path:

        url = studio_media_url(
            path
        )

        if url:
            return url


    legacy_id = project.get(
        "legacy_wip_id"
    )

    if legacy_id:

        return (
            f"/api/wip/file/"
            f"{legacy_id}/artwork"
        )


    return None



def studio_version_dict(
    row
):

    version = dict(
        row
    )


    audio_path = version.get(
        "audio_path"
    )


    audio_url = studio_media_url(
        audio_path
    )


    if not audio_url:

        legacy_id = version.get(
            "legacy_wip_id"
        )

        if legacy_id:

            audio_url = (
                f"/api/wip/file/"
                f"{legacy_id}/audio"
            )


    version[
        "original_audio_url"
    ] = audio_url


    version[
        "audio_url"
    ] = audio_url


    version[
        "playback_audio_url"
    ] = audio_url


    if audio_path:

        try:

            playback_path = (
                ensure_wip_playback_file(
                    Path(
                        audio_path
                    )
                )
            )

            playback_url = (
                studio_media_url(
                    playback_path
                )
            )

            if playback_url:

                version[
                    "playback_audio_url"
                ] = playback_url

        except Exception as error:

            print(
                "[Apollo Studio] "
                "playback preparation:",
                error
            )


    version.pop(
        "audio_path",
        None
    )


    version[
        "is_current"
    ] = bool(
        version.get(
            "is_current"
        )
    )


    return version



def get_studio_projects():

    conn = db()


    rows = conn.execute("""
        SELECT
            p.*,

            (
                SELECT COUNT(*)
                FROM studio_tracks t
                WHERE t.project_id = p.id
            ) AS track_count,

            (
                SELECT COUNT(*)
                FROM studio_versions v
                JOIN studio_tracks t
                    ON t.id = v.track_id
                WHERE t.project_id = p.id
            ) AS version_count,

            (
                SELECT COUNT(*)
                FROM studio_notes n
                WHERE n.project_id = p.id
            ) AS note_count,

            (
                SELECT COUNT(*)
                FROM studio_media m
                WHERE m.project_id = p.id
            ) AS media_count

        FROM studio_projects p

        ORDER BY
            p.updated_at DESC,
            p.id DESC
    """).fetchall()


    conn.close()


    projects = []


    for row in rows:

        project = dict(
            row
        )

        project[
            "artwork_url"
        ] = studio_artwork_url(
            project
        )

        project.pop(
            "artwork_path",
            None
        )

        projects.append(
            project
        )


    return projects



def get_studio_project(
    project_id
):

    conn = db()


    row = conn.execute("""
        SELECT *
        FROM studio_projects
        WHERE id = ?
    """, (
        int(project_id),
    )).fetchone()


    if not row:

        conn.close()

        raise ValueError(
            "Studio project not found"
        )


    project = dict(
        row
    )


    project[
        "artwork_url"
    ] = studio_artwork_url(
        project
    )


    project.pop(
        "artwork_path",
        None
    )


    track_rows = conn.execute("""
        SELECT *
        FROM studio_tracks

        WHERE project_id = ?

        ORDER BY
            CASE
                WHEN track_number IS NULL
                THEN 1
                ELSE 0
            END,

            track_number ASC,
            id ASC
    """, (
        int(project_id),
    )).fetchall()


    tracks = []


    for track_row in track_rows:

        track = dict(
            track_row
        )


        version_rows = conn.execute("""
            SELECT *
            FROM studio_versions

            WHERE track_id = ?

            ORDER BY
                is_current DESC,
                updated_at DESC,
                id DESC
        """, (
            track["id"],
        )).fetchall()


        track[
            "versions"
        ] = [
            studio_version_dict(
                version
            )
            for version
            in version_rows
        ]


        tracks.append(
            track
        )


    project[
        "tracks"
    ] = tracks


    note_rows = conn.execute("""
        SELECT
            id,
            project_id,
            track_id,
            kind,
            title,
            body,
            created_at,
            updated_at

        FROM studio_notes

        WHERE project_id = ?

        ORDER BY
            updated_at DESC,
            id DESC
    """, (
        int(project_id),
    )).fetchall()


    project[
        "notes"
    ] = [
        dict(row)
        for row
        in note_rows
    ]


    media_rows = conn.execute("""
        SELECT
            id,
            project_id,
            track_id,
            media_type,
            title,
            file_name,
            file_path,
            file_mime,
            external_url,
            notes,
            created_at,
            updated_at

        FROM studio_media

        WHERE project_id = ?

        ORDER BY
            updated_at DESC,
            id DESC
    """, (
        int(project_id),
    )).fetchall()


    media = []


    for media_row in media_rows:

        item = dict(
            media_row
        )

        item[
            "file_url"
        ] = studio_media_url(
            item.get(
                "file_path"
            )
        )

        item.pop(
            "file_path",
            None
        )

        media.append(
            item
        )


    project[
        "media"
    ] = media


    conn.close()


    return project




def get_wip_projects():

    conn = db()

    rows = conn.execute("""
        SELECT
            id,
            title,
            audio_name,
            audio_path,
            audio_mime,
            artwork_name,
            artwork_path,
            artwork_mime,
            bpm,
            musical_key,
            notes,
            created_at,
            updated_at
        FROM wip_projects
        ORDER BY
            updated_at DESC,
            id DESC
    """).fetchall()

    conn.close()

    return [
        wip_project_dict(row)
        for row in rows
    ]


def create_wip_project(
    handler
):

    fields, files = read_multipart(
        handler
    )

    audio = files.get(
        "audio"
    )

    artwork = files.get(
        "artwork"
    )

    if not audio:
        raise ValueError(
            "Choose a WAV or MP3 file"
        )

    audio_name = (
        audio["filename"]
    )

    audio_ext = (
        Path(audio_name)
        .suffix
        .lower()
    )

    allowed_audio = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg"
    }

    if audio_ext not in allowed_audio:
        raise ValueError(
            "Audio must be WAV or MP3"
        )

    title = str(
        fields.get(
            "title",
            ""
        )
    ).strip()

    if not title:

        title = (
            Path(audio_name)
            .stem
            .strip()
            or "Untitled"
        )

    project_folder = (
        WIP_DIR
        / uuid.uuid4().hex
    )

    project_folder.mkdir(
        parents=True,
        exist_ok=False
    )

    audio_path = (
        project_folder
        / (
            "audio"
            + audio_ext
        )
    )

    audio_path.write_bytes(
        audio["data"]
    )

    artwork_name = None
    artwork_path = None
    artwork_mime = None

    if artwork:

        artwork_name = (
            artwork["filename"]
        )

        artwork_ext = (
            Path(artwork_name)
            .suffix
            .lower()
        )

        allowed_artwork = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp"
        }

        if artwork_ext not in allowed_artwork:

            try:
                audio_path.unlink(
                    missing_ok=True
                )

                project_folder.rmdir()

            except Exception:
                pass

            raise ValueError(
                "Artwork must be JPG, PNG, or WebP"
            )

        artwork_path = (
            project_folder
            / (
                "artwork"
                + artwork_ext
            )
        )

        artwork_path.write_bytes(
            artwork["data"]
        )

        artwork_mime = (
            allowed_artwork[
                artwork_ext
            ]
        )

    conn = db()

    cursor = conn.execute("""
        INSERT INTO wip_projects (
            title,
            audio_name,
            audio_path,
            audio_mime,
            artwork_name,
            artwork_path,
            artwork_mime
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        title,
        audio_name,
        str(audio_path),
        allowed_audio[audio_ext],
        artwork_name,
        (
            str(artwork_path)
            if artwork_path
            else None
        ),
        artwork_mime
    ))

    project_id = (
        cursor.lastrowid
    )

    conn.commit()

    row = conn.execute("""
        SELECT *
        FROM wip_projects
        WHERE id = ?
    """, (
        project_id,
    )).fetchone()

    conn.close()

    return wip_project_dict(
        row
    )



def get_wip_project(
    project_id
):

    conn = db()

    row = conn.execute("""
        SELECT *
        FROM wip_projects
        WHERE id = ?
    """, (
        int(project_id),
    )).fetchone()

    conn.close()

    return row


def update_wip_project(
    data
):

    try:
        project_id = int(
            data.get(
                "project_id"
            )
        )
    except (
        TypeError,
        ValueError
    ):
        raise ValueError(
            "Invalid project"
        )


    existing = get_wip_project(
        project_id
    )

    if not existing:
        raise ValueError(
            "Project not found"
        )


    title = str(
        data.get(
            "title",
            existing["title"]
        )
    ).strip()

    if not title:
        raise ValueError(
            "Project name can't be empty"
        )

    if len(title) > 160:
        raise ValueError(
            "Project name is too long"
        )


    musical_key = str(
        data.get(
            "musical_key",
            existing["musical_key"]
            or ""
        )
    ).strip()

    if len(musical_key) > 30:
        raise ValueError(
            "Key is too long"
        )

    musical_key = (
        musical_key
        or None
    )


    bpm_value = data.get(
        "bpm",
        existing["bpm"]
    )

    if (
        bpm_value is None
        or str(
            bpm_value
        ).strip() == ""
    ):

        bpm = None

    else:

        try:
            bpm = float(
                bpm_value
            )
        except (
            TypeError,
            ValueError
        ):
            raise ValueError(
                "BPM must be a number"
            )

        if not (
            20 <= bpm <= 300
        ):
            raise ValueError(
                "BPM must be between 20 and 300"
            )


    notes = str(
        data.get(
            "notes",
            existing["notes"]
            or ""
        )
    ).strip()

    if len(notes) > 20000:
        raise ValueError(
            "Notes are too long"
        )

    notes = (
        notes
        or None
    )


    conn = db()

    conn.execute("""
        UPDATE wip_projects
        SET
            title = ?,
            bpm = ?,
            musical_key = ?,
            notes = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        title,
        bpm,
        musical_key,
        notes,
        project_id
    ))

    conn.commit()

    row = conn.execute("""
        SELECT *
        FROM wip_projects
        WHERE id = ?
    """, (
        project_id,
    )).fetchone()

    conn.close()

    return wip_project_dict(
        row
    )


def delete_wip_project(
    project_id
):

    try:
        project_id = int(
            project_id
        )
    except (
        TypeError,
        ValueError
    ):
        raise ValueError(
            "Invalid project"
        )


    existing = get_wip_project(
        project_id
    )

    if not existing:
        raise ValueError(
            "Project not found"
        )


    paths = []

    for field in (
        "audio_path",
        "artwork_path"
    ):

        value = existing[
            field
        ]

        if value:

            try:
                paths.append(
                    Path(value)
                )
            except Exception:
                pass


    conn = db()

    conn.execute(
        """
        DELETE FROM wip_projects
        WHERE id = ?
        """,
        (
            project_id,
        )
    )

    conn.commit()
    conn.close()


    project_folder = None

    audio_path = existing[
        "audio_path"
    ]

    if audio_path:

        try:
            project_folder = (
                Path(audio_path)
                .parent
            )
        except Exception:
            project_folder = None


    # Only remove files inside Apollo's WIP directory.
    if project_folder:

        try:

            project_folder.relative_to(
                WIP_DIR
            )

            for child in (
                project_folder.iterdir()
                if project_folder.exists()
                else []
            ):

                if child.is_file():
                    child.unlink(
                        missing_ok=True
                    )

            project_folder.rmdir()

        except Exception as error:

            print(
                "[Apollo WIP] "
                "Could not remove project folder:",
                error
            )


    return {
        "ok": True,
        "deleted": project_id
    }


def wip_replace_start(
    data
):

    try:
        project_id = int(
            data.get(
                "project_id"
            )
        )

        size = int(
            data.get(
                "size"
            )
        )

    except (
        TypeError,
        ValueError
    ):
        raise ValueError(
            "Invalid replacement upload"
        )


    project = get_wip_project(
        project_id
    )

    if not project:
        raise ValueError(
            "Project not found"
        )


    filename = (
        Path(
            str(
                data.get(
                    "filename",
                    ""
                )
            )
        )
        .name
    )

    extension = (
        Path(filename)
        .suffix
        .lower()
    )

    allowed = {
        ".wav":
            "audio/wav",

        ".mp3":
            "audio/mpeg"
    }

    if extension not in allowed:
        raise ValueError(
            "Audio must be WAV or MP3"
        )

    if size <= 0:
        raise ValueError(
            "Audio file is empty"
        )

    if size > (
        300
        * 1024
        * 1024
    ):
        raise ValueError(
            "Audio file is too large"
        )


    upload_id = (
        uuid.uuid4().hex
    )

    folder = (
        WIP_UPLOAD_DIR
        / upload_id
    )

    folder.mkdir(
        parents=True,
        exist_ok=False
    )


    metadata = {
        "mode":
            "replace_audio",

        "project_id":
            project_id,

        "filename":
            filename,

        "extension":
            extension,

        "mime":
            allowed[
                extension
            ],

        "size":
            size
    }


    (
        folder
        / "meta.json"
    ).write_text(
        json.dumps(
            metadata
        ),
        encoding="utf-8"
    )

    (
        folder
        / "audio.part"
    ).touch()


    return {
        "upload_id":
            upload_id
    }


def wip_replace_chunk(
    handler,
    upload_id,
    offset
):

    upload_id = str(
        upload_id
    ).strip()

    if (
        not upload_id
        or not all(
            char in
            "0123456789abcdef"
            for char in upload_id.lower()
        )
    ):
        raise ValueError(
            "Invalid upload"
        )


    folder = (
        WIP_UPLOAD_DIR
        / upload_id
    )

    metadata_path = (
        folder
        / "meta.json"
    )

    part_path = (
        folder
        / "audio.part"
    )


    if (
        not metadata_path.exists()
        or not part_path.exists()
    ):
        raise ValueError(
            "Upload not found"
        )


    metadata = json.loads(
        metadata_path.read_text(
            encoding="utf-8"
        )
    )


    expected_size = int(
        metadata[
            "size"
        ]
    )

    current_size = (
        part_path.stat().st_size
    )

    if int(
        offset
    ) != current_size:
        raise ValueError(
            "Unexpected upload offset"
        )


    length = int(
        handler.headers.get(
            "Content-Length",
            "0"
        )
    )

    if (
        length <= 0
        or length > (
            8
            * 1024
            * 1024
        )
    ):
        raise ValueError(
            "Invalid chunk size"
        )


    if (
        current_size
        + length
        > expected_size
    ):
        raise ValueError(
            "Chunk exceeds file size"
        )


    remaining = length

    with part_path.open(
        "ab"
    ) as output:

        while remaining > 0:

            chunk = (
                handler.rfile.read(
                    min(
                        1024 * 1024,
                        remaining
                    )
                )
            )

            if not chunk:
                raise ValueError(
                    "Upload ended early"
                )

            output.write(
                chunk
            )

            remaining -= len(
                chunk
            )


    return {
        "received":
            part_path.stat().st_size,

        "total":
            expected_size
    }


def wip_replace_finish(
    upload_id
):

    upload_id = str(
        upload_id
    ).strip()

    folder = (
        WIP_UPLOAD_DIR
        / upload_id
    )

    metadata_path = (
        folder
        / "meta.json"
    )

    part_path = (
        folder
        / "audio.part"
    )

    if (
        not metadata_path.exists()
        or not part_path.exists()
    ):
        raise ValueError(
            "Upload not found"
        )


    metadata = json.loads(
        metadata_path.read_text(
            encoding="utf-8"
        )
    )

    expected_size = int(
        metadata[
            "size"
        ]
    )

    actual_size = (
        part_path.stat().st_size
    )

    if (
        actual_size
        != expected_size
    ):
        raise ValueError(
            "Replacement upload is incomplete"
        )


    project_id = int(
        metadata[
            "project_id"
        ]
    )

    existing = get_wip_project(
        project_id
    )

    if not existing:
        raise ValueError(
            "Project not found"
        )


    old_audio = Path(
        existing[
            "audio_path"
        ]
    )

    project_folder = (
        old_audio.parent
    )

    project_folder.relative_to(
        WIP_DIR
    )


    extension = metadata[
        "extension"
    ]

    new_audio = (
        project_folder
        / (
            "audio"
            + extension
        )
    )


    temp_target = (
        project_folder
        / (
            ".replacement"
            + extension
        )
    )


    if temp_target.exists():
        temp_target.unlink()


    part_path.replace(
        temp_target
    )


    if (
        old_audio.exists()
        and old_audio
        != temp_target
    ):
        old_audio.unlink(
            missing_ok=True
        )


    if (
        new_audio.exists()
        and new_audio
        != temp_target
    ):
        new_audio.unlink(
            missing_ok=True
        )


    temp_target.replace(
        new_audio
    )


    conn = db()

    conn.execute("""
        UPDATE wip_projects
        SET
            audio_name = ?,
            audio_path = ?,
            audio_mime = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        metadata[
            "filename"
        ],
        str(
            new_audio
        ),
        metadata[
            "mime"
        ],
        project_id
    ))

    conn.commit()

    row = conn.execute("""
        SELECT *
        FROM wip_projects
        WHERE id = ?
    """, (
        project_id,
    )).fetchone()

    conn.close()


    try:

        metadata_path.unlink(
            missing_ok=True
        )

        folder.rmdir()

    except Exception:
        pass


    return wip_project_dict(
        row
    )



def update_wip_artwork(
    handler
):

    fields, files = read_multipart(
        handler,
        max_bytes=25 * 1024 * 1024
    )


    try:

        project_id = int(
            fields.get(
                "project_id",
                ""
            )
        )

    except ValueError:

        raise ValueError(
            "Invalid project"
        )


    project = get_wip_project(
        project_id
    )

    if not project:

        raise ValueError(
            "Project not found"
        )


    remove_artwork = (
        str(
            fields.get(
                "remove_artwork",
                ""
            )
        ).lower()
        in {
            "1",
            "true",
            "yes"
        }
    )


    artwork = files.get(
        "artwork"
    )


    old_path = (
        Path(
            project["artwork_path"]
        )
        if project["artwork_path"]
        else None
    )


    # --------------------------------------------------------
    # REMOVE ART
    # --------------------------------------------------------

    if remove_artwork:

        if old_path:

            try:

                old_path.relative_to(
                    WIP_DIR
                )

                old_path.unlink(
                    missing_ok=True
                )

            except Exception as error:

                print(
                    "[Apollo WIP] "
                    "Could not remove artwork:",
                    error
                )


        conn = db()

        conn.execute("""
            UPDATE wip_projects
            SET
                artwork_name = NULL,
                artwork_path = NULL,
                artwork_mime = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            project_id,
        ))

        conn.commit()

        row = conn.execute("""
            SELECT *
            FROM wip_projects
            WHERE id = ?
        """, (
            project_id,
        )).fetchone()

        conn.close()

        return wip_project_dict(
            row
        )


    # --------------------------------------------------------
    # KEEP EXISTING ART
    # --------------------------------------------------------

    if not artwork:

        return wip_project_dict(
            project
        )


    artwork_name = (
        Path(
            artwork["filename"]
        )
        .name
    )


    extension = (
        Path(
            artwork_name
        )
        .suffix
        .lower()
    )


    allowed = {
        ".jpg":
            "image/jpeg",

        ".jpeg":
            "image/jpeg",

        ".png":
            "image/png",

        ".webp":
            "image/webp"
    }


    if extension not in allowed:

        raise ValueError(
            "Artwork must be JPG, PNG, or WebP"
        )


    audio_path = Path(
        project["audio_path"]
    )

    project_folder = (
        audio_path.parent
    )

    project_folder.relative_to(
        WIP_DIR
    )


    new_path = (
        project_folder
        / (
            "artwork"
            + extension
        )
    )


    temp_path = (
        project_folder
        / (
            ".artwork-replacement"
            + extension
        )
    )


    temp_path.write_bytes(
        artwork["data"]
    )


    if old_path:

        try:

            old_path.relative_to(
                WIP_DIR
            )

            old_path.unlink(
                missing_ok=True
            )

        except Exception as error:

            print(
                "[Apollo WIP] "
                "Could not remove old artwork:",
                error
            )


    if new_path.exists():

        new_path.unlink(
            missing_ok=True
        )


    temp_path.replace(
        new_path
    )


    conn = db()

    conn.execute("""
        UPDATE wip_projects
        SET
            artwork_name = ?,
            artwork_path = ?,
            artwork_mime = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        artwork_name,
        str(
            new_path
        ),
        allowed[
            extension
        ],
        project_id
    ))

    conn.commit()

    row = conn.execute("""
        SELECT *
        FROM wip_projects
        WHERE id = ?
    """, (
        project_id,
    )).fetchone()

    conn.close()


    return wip_project_dict(
        row
    )


def send_wip_file(
    handler,
    project_id,
    kind
):
    """
    Stream WIP audio/artwork with Range support so the
    browser audio player can seek normally.
    """

    if kind not in {
        "audio",
        "artwork"
    }:
        json_response(
            handler,
            {"error": "Invalid file type"},
            400
        )
        return

    conn = db()

    row = conn.execute("""
        SELECT
            audio_path,
            audio_mime,
            artwork_path,
            artwork_mime
        FROM wip_projects
        WHERE id = ?
    """, (
        project_id,
    )).fetchone()

    conn.close()

    if not row:

        json_response(
            handler,
            {"error": "Project not found"},
            404
        )

        return

    if kind == "audio":

        file_path = row[
            "audio_path"
        ]

        mime = row[
            "audio_mime"
        ]

    else:

        file_path = row[
            "artwork_path"
        ]

        mime = row[
            "artwork_mime"
        ]

    if not file_path:

        json_response(
            handler,
            {"error": "File not found"},
            404
        )

        return

    file_path = Path(
        file_path
    )

    if not file_path.exists():

        json_response(
            handler,
            {"error": "File missing"},
            404
        )

        return

    total_size = (
        file_path.stat().st_size
    )

    range_header = (
        handler.headers.get(
            "Range"
        )
    )

    start = 0
    end = total_size - 1

    status = 200

    if (
        range_header
        and range_header.startswith(
            "bytes="
        )
    ):

        try:

            range_value = (
                range_header[6:]
                .split(",", 1)[0]
            )

            start_text, end_text = (
                range_value.split(
                    "-",
                    1
                )
            )

            if start_text:
                start = int(
                    start_text
                )

            if end_text:
                end = int(
                    end_text
                )

            end = min(
                end,
                total_size - 1
            )

            if (
                start < 0
                or start >= total_size
                or end < start
            ):
                raise ValueError

            status = 206

        except Exception:

            handler.send_response(
                416
            )

            handler.send_header(
                "Content-Range",
                f"bytes */{total_size}"
            )

            handler.end_headers()

            return

    length = (
        end
        - start
        + 1
    )

    handler.send_response(
        status
    )

    handler.send_header(
        "Content-Type",
        mime
        or "application/octet-stream"
    )

    handler.send_header(
        "Accept-Ranges",
        "bytes"
    )

    handler.send_header(
        "Content-Length",
        str(length)
    )

    handler.send_header(
        "Cache-Control",
        "private, max-age=3600"
    )

    if status == 206:

        handler.send_header(
            "Content-Range",
            (
                f"bytes "
                f"{start}-{end}/"
                f"{total_size}"
            )
        )

    handler.end_headers()

    with file_path.open(
        "rb"
    ) as file:

        file.seek(
            start
        )

        remaining = (
            length
        )

        while remaining > 0:

            chunk = file.read(
                min(
                    1024 * 256,
                    remaining
                )
            )

            if not chunk:
                break

            try:

                handler.wfile.write(
                    chunk
                )

            except (
                BrokenPipeError,
                ConnectionResetError
            ):

                break

            remaining -= (
                len(chunk)
            )



# ============================================================
# WIP CHUNKED UPLOAD V2
# ============================================================

WIP_UPLOAD_DIR = WIP_DIR / ".uploads"

WIP_UPLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True
)


def wip_upload_start(data):

    title = str(
        data.get("title", "")
    ).strip()

    audio_name = (
        Path(
            str(
                data.get(
                    "audio_name",
                    ""
                )
            )
        ).name
    )

    artwork_name = (
        Path(
            str(
                data.get(
                    "artwork_name",
                    ""
                )
            )
        ).name
        if data.get("artwork_name")
        else None
    )

    audio_size = int(
        data.get(
            "audio_size",
            0
        )
        or 0
    )

    artwork_size = int(
        data.get(
            "artwork_size",
            0
        )
        or 0
    )


    if not audio_name:
        raise ValueError(
            "Audio filename missing"
        )

    if audio_size <= 0:
        raise ValueError(
            "Audio file is empty"
        )

    audio_ext = (
        Path(audio_name)
        .suffix
        .lower()
    )

    allowed_audio = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg"
    }

    if audio_ext not in allowed_audio:
        raise ValueError(
            "Audio must be WAV or MP3"
        )


    artwork_ext = None
    artwork_mime = None

    if artwork_name:

        artwork_ext = (
            Path(artwork_name)
            .suffix
            .lower()
        )

        allowed_artwork = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp"
        }

        if artwork_ext not in allowed_artwork:
            raise ValueError(
                "Artwork must be JPG, PNG, or WebP"
            )

        artwork_mime = (
            allowed_artwork[
                artwork_ext
            ]
        )


    if not title:

        title = (
            Path(audio_name)
            .stem
            .strip()
            or "Untitled"
        )


    upload_id = (
        uuid.uuid4().hex
    )

    upload_dir = (
        WIP_UPLOAD_DIR
        / upload_id
    )

    upload_dir.mkdir(
        parents=True,
        exist_ok=False
    )


    meta = {
        "upload_id":
            upload_id,

        "title":
            title,

        "audio_name":
            audio_name,

        "audio_ext":
            audio_ext,

        "audio_mime":
            allowed_audio[
                audio_ext
            ],

        "audio_size":
            audio_size,

        "artwork_name":
            artwork_name,

        "artwork_ext":
            artwork_ext,

        "artwork_mime":
            artwork_mime,

        "artwork_size":
            artwork_size
    }


    (
        upload_dir
        / "meta.json"
    ).write_text(
        json.dumps(
            meta,
            ensure_ascii=False
        )
    )


    (
        upload_dir
        / "audio.part"
    ).touch()


    if artwork_name:

        (
            upload_dir
            / "artwork.part"
        ).touch()


    return {
        "upload_id":
            upload_id
    }


def wip_upload_meta(
    upload_id
):

    if (
        not upload_id
        or not upload_id.isalnum()
    ):
        raise ValueError(
            "Invalid upload ID"
        )

    upload_dir = (
        WIP_UPLOAD_DIR
        / upload_id
    )

    meta_path = (
        upload_dir
        / "meta.json"
    )

    if not meta_path.exists():
        raise ValueError(
            "Upload session not found"
        )

    return (
        upload_dir,
        json.loads(
            meta_path.read_text()
        )
    )


def wip_upload_chunk(
    handler,
    upload_id,
    kind,
    offset
):

    upload_dir, meta = (
        wip_upload_meta(
            upload_id
        )
    )


    if kind not in {
        "audio",
        "artwork"
    }:
        raise ValueError(
            "Invalid upload type"
        )


    if (
        kind == "artwork"
        and not meta.get(
            "artwork_name"
        )
    ):
        raise ValueError(
            "No artwork expected"
        )


    expected_size = int(
        meta[
            f"{kind}_size"
        ]
    )


    try:

        length = int(
            handler.headers.get(
                "Content-Length",
                "0"
            )
        )

    except ValueError:

        raise ValueError(
            "Invalid chunk size"
        )


    if length <= 0:
        raise ValueError(
            "Empty upload chunk"
        )


    # 8 MB max per browser request.
    if length > (
        8 * 1024 * 1024
    ):
        raise ValueError(
            "Upload chunk too large"
        )


    part_path = (
        upload_dir
        / f"{kind}.part"
    )


    if not part_path.exists():
        raise ValueError(
            "Upload file missing"
        )


    current_size = (
        part_path.stat().st_size
    )


    if int(offset) != current_size:

        raise ValueError(
            (
                "Upload offset mismatch: "
                f"expected {current_size}, "
                f"got {offset}"
            )
        )


    body = handler.rfile.read(
        length
    )


    if len(body) != length:

        raise ValueError(
            (
                "Incomplete upload chunk: "
                f"expected {length} bytes, "
                f"received {len(body)}"
            )
        )


    if (
        current_size
        + len(body)
        > expected_size
    ):
        raise ValueError(
            "Upload exceeds expected size"
        )


    with part_path.open(
        "ab"
    ) as file:

        file.write(
            body
        )


    received = (
        part_path.stat().st_size
    )


    return {
        "received":
            received,

        "total":
            expected_size
    }


def wip_upload_finish(
    upload_id
):

    upload_dir, meta = (
        wip_upload_meta(
            upload_id
        )
    )


    audio_part = (
        upload_dir
        / "audio.part"
    )


    expected_audio = int(
        meta.get(
            "audio_size",
            0
        )
    )


    actual_audio = (
        audio_part.stat().st_size
        if audio_part.exists()
        else 0
    )


    if (
        actual_audio <= 0
        or actual_audio
        != expected_audio
    ):

        raise ValueError(
            (
                "Audio upload incomplete: "
                f"{actual_audio} of "
                f"{expected_audio} bytes"
            )
        )


    artwork_part = None

    if meta.get(
        "artwork_name"
    ):

        artwork_part = (
            upload_dir
            / "artwork.part"
        )

        expected_artwork = int(
            meta.get(
                "artwork_size",
                0
            )
        )

        actual_artwork = (
            artwork_part.stat().st_size
            if artwork_part.exists()
            else 0
        )

        if (
            expected_artwork <= 0
            or actual_artwork
            != expected_artwork
        ):

            raise ValueError(
                (
                    "Artwork upload incomplete: "
                    f"{actual_artwork} of "
                    f"{expected_artwork} bytes"
                )
            )


    project_dir = (
        WIP_DIR
        / uuid.uuid4().hex
    )

    project_dir.mkdir(
        parents=True,
        exist_ok=False
    )


    audio_path = (
        project_dir
        / (
            "audio"
            + meta["audio_ext"]
        )
    )

    audio_part.replace(
        audio_path
    )


    artwork_path = None

    if artwork_part:

        artwork_path = (
            project_dir
            / (
                "artwork"
                + meta[
                    "artwork_ext"
                ]
            )
        )

        artwork_part.replace(
            artwork_path
        )


    conn = db()

    cursor = conn.execute("""
        INSERT INTO wip_projects (
            title,
            audio_name,
            audio_path,
            audio_mime,
            artwork_name,
            artwork_path,
            artwork_mime
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        meta["title"],
        meta["audio_name"],
        str(audio_path),
        meta["audio_mime"],
        meta.get(
            "artwork_name"
        ),
        (
            str(artwork_path)
            if artwork_path
            else None
        ),
        meta.get(
            "artwork_mime"
        )
    ))

    project_id = (
        cursor.lastrowid
    )

    conn.commit()

    row = conn.execute("""
        SELECT *
        FROM wip_projects
        WHERE id = ?
    """, (
        project_id,
    )).fetchone()

    conn.close()


    # Remove staging metadata.
    try:

        (
            upload_dir
            / "meta.json"
        ).unlink(
            missing_ok=True
        )

        upload_dir.rmdir()

    except Exception:

        pass


    return wip_project_dict(
        row
    )


def get_now_playing():
    """
    Return rich Spotify playback state for Apollo Music.
    """

    try:
        result = subprocess.run(
            [
                SPOTIFY_PYTHON,
                SPOTIFY_TOOL,
                "current"
            ],
            capture_output=True,
            text=True,
            timeout=15
        )

        if result.returncode != 0:
            error = result.stderr.strip()

            return {
                "playing": False,
                "title": None,
                "artists": None,
                "error": error or "Spotify unavailable"
            }

        output = result.stdout.strip()

        if not output:
            return {
                "playing": False,
                "title": None,
                "artists": None
            }

        data = json.loads(output)

        if not isinstance(data, dict):
            raise ValueError("Invalid Spotify response")

        return data

    except Exception as error:
        print(f"[Apollo] Spotify error: {error}")

        return {
            "playing": False,
            "title": None,
            "artists": None,
            "error": str(error)
        }


def get_spotify_recent_contexts():
    """
    Return Apollo's recent Spotify albums/playlists.

    Individual songs are intentionally excluded by spotify_tool.py.
    """

    try:

        result = subprocess.run(
            [
                SPOTIFY_PYTHON,
                SPOTIFY_TOOL,
                "recent-contexts"
            ],
            capture_output=True,
            text=True,
            timeout=25
        )


        if result.returncode != 0:

            raise RuntimeError(
                result.stderr.strip()
                or result.stdout.strip()
                or "Spotify recent history failed"
            )


        output = (
            result.stdout.strip()
        )


        data = (
            json.loads(output)
            if output
            else {"items": []}
        )


        if not isinstance(
            data,
            dict
        ):
            raise ValueError(
                "Invalid Spotify recent response"
            )


        items = (
            data.get("items")
            or []
        )


        # Defensive filtering:
        # only albums/playlists may reach the frontend.
        items = [
            item
            for item in items
            if (
                isinstance(item, dict)
                and item.get("type")
                in {
                    "album",
                    "playlist"
                }
            )
        ]


        return {
            "items":
                items[:12]
        }


    except Exception as error:

        print(
            "[Apollo Spotify Recent] "
            f"{error}"
        )

        return {
            "items": [],
            "error": str(error)
        }


def spotify_play_recent_context(
    kind,
    uri
):
    """
    Play an exact recent Spotify album/playlist in shuffle.
    """

    kind = str(
        kind or ""
    ).strip().lower()

    uri = str(
        uri or ""
    ).strip()


    if kind not in {
        "album",
        "playlist"
    }:
        raise ValueError(
            "Invalid Spotify context type"
        )


    if not uri.startswith(
        f"spotify:{kind}:"
    ):
        raise ValueError(
            "Invalid Spotify context URI"
        )


    payload = {
        "type": kind,
        "uri": uri
    }


    result = subprocess.run(
        [
            SPOTIFY_PYTHON,
            SPOTIFY_TOOL,
            "play-context",
            json.dumps(
                payload,
                ensure_ascii=False
            )
        ],
        capture_output=True,
        text=True,
        timeout=20
    )


    if result.returncode != 0:

        raise RuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
            or "Spotify playback failed"
        )


    output = (
        result.stdout.strip()
    )


    return (
        json.loads(output)
        if output
        else {
            "ok": True,
            "shuffle": True
        }
    )


def spotify_playback_command(action, position_ms=None):
    allowed = {
        "pause": "pause",
        "play": "resume",
        "resume": "resume",
        "next": "next",
        "previous": "previous",
        "seek": "seek"
    }

    command = allowed.get(
        str(action).strip().lower()
    )

    if not command:
        raise ValueError("Invalid Spotify action")

    args = [
        SPOTIFY_PYTHON,
        SPOTIFY_TOOL,
        command
    ]

    if command == "seek":
        try:
            position_ms = max(
                0,
                int(position_ms)
            )
        except (TypeError, ValueError):
            raise ValueError("Invalid seek position")

        args.append(
            str(position_ms)
        )

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=15
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or "Spotify command failed"
        )

    return {
        "ok": True,
        "action": action,
        "playback": get_now_playing()
    }



# ============================================================
# APOLLO MUSIC — PERSONAL PLAYLIST ALIASES
# ============================================================

def apollo_spotify_personal_playlists():

    result = subprocess.run(
        [
            SPOTIFY_PYTHON,
            SPOTIFY_TOOL,
            "list-playlists"
        ],
        capture_output=True,
        text=True,
        timeout=20
    )


    if result.returncode != 0:

        print(
            "[Apollo Music Alias] "
            "Could not load Spotify playlists: "
            + (
                result.stderr.strip()
                or result.stdout.strip()
            )
        )

        return []


    try:

        data = json.loads(
            result.stdout.strip()
            or "{}"
        )

    except Exception:

        return []


    return [
        item
        for item in (
            data.get("playlists")
            or []
        )
        if isinstance(item, dict)
        and item.get("name")
    ]




def apollo_music_action_requested(
    user_message,
    surface=""
):
    """
    Decide whether Apollo should use the real Spotify action
    system instead of answering conversationally.

    Music surface is action-first.

    Everywhere else, require clear playback intent so normal
    conversations about music are not hijacked.
    """

    value = str(
        user_message or ""
    ).strip().lower()


    if not value:
        return False


    if str(
        surface or ""
    ).strip().lower() == "music":

        return True


    # Strong explicit playback commands.
    starts = (
        "play ",
        "play my ",
        "put on ",
        "put my ",
        "start playing ",
        "start my ",
        "shuffle ",
        "shuffle my ",
        "resume ",
    )


    if value.startswith(
        starts
    ):
        return True


    # Natural direct commands Apollo should understand.
    direct_phrases = (
        "play something",
        "play some music",
        "put something on",
        "put some music on",
        "play my jams",
        "play my shit",
        "play my usual",
        "play the usual",
        "play the main one",
        "play my main",
    )


    if any(
        phrase in value
        for phrase in direct_phrases
    ):
        return True


    return False


def apollo_music_match_personal_playlist(
    user_request
):

    import re
    from difflib import SequenceMatcher


    raw = str(
        user_request or ""
    ).strip()


    if not raw:
        return None


    # Remove obvious command framing but preserve the actual
    # playlist name exactly enough for matching.
    candidate = raw


    candidate = re.sub(
        r"^\s*(?:please\s+)?(?:play|put on|start)\s+",
        "",
        candidate,
        flags=re.I
    )


    candidate = re.sub(
        r"^\s*my\s+",
        "",
        candidate,
        flags=re.I
    )


    candidate = re.sub(
        r"\s+playlist\s*$",
        "",
        candidate,
        flags=re.I
    )


    candidate = candidate.strip()


    if not candidate:
        return None


    playlists = (
        apollo_spotify_personal_playlists()
    )


    if not playlists:
        return None


    def normalize(value):

        return re.sub(
            r"[^a-z0-9]+",
            "",
            str(
                value or ""
            ).lower()
        )


    # =====================================================
    # EXACT LITERAL MATCH FIRST
    # =====================================================

    literal = (
        candidate
        .strip()
        .casefold()
    )


    for item in playlists:

        name = str(
            item.get(
                "name"
            )
            or ""
        ).strip()


        if (
            name
            and name.casefold()
            == literal
        ):

            return name


    # =====================================================
    # NORMALIZED EXACT MATCH
    #
    # "Topo Chico III" == "topo chico iii"
    # punctuation / spacing differences are ignored.
    # =====================================================

    wanted = normalize(
        candidate
    )


    if not wanted:
        return None


    for item in playlists:

        name = str(
            item.get(
                "name"
            )
            or ""
        ).strip()


        if (
            name
            and normalize(name)
            == wanted
        ):

            return name


    # =====================================================
    # NEAR-EXACT PERSONAL MATCH
    #
    # Conservative threshold so we don't randomly turn
    # ordinary song requests into playlists.
    # =====================================================

    scored = []


    for item in playlists:

        name = str(
            item.get(
                "name"
            )
            or ""
        ).strip()


        normalized_name = (
            normalize(name)
        )


        if (
            not name
            or not normalized_name
        ):
            continue


        score = (
            SequenceMatcher(
                None,
                wanted,
                normalized_name
            ).ratio()
        )


        scored.append(
            (
                score,
                name
            )
        )


    if not scored:
        return None


    scored.sort(
        reverse=True
    )


    best_score, best_name = (
        scored[0]
    )


    if best_score >= .90:

        return best_name


    return None


def apollo_music_alias_candidate(
    user_request
):

    value = str(
        user_request or ""
    ).strip().lower()


    if not value:
        return False


    # These phrases depend on personal meaning rather than
    # being literal Spotify playlist names.
    aliases = (
        "my main playlist",
        "main playlist",
        "my usual playlist",
        "usual playlist",
        "my regular playlist",
        "regular playlist",
        "my default playlist",
        "default playlist",
        "my go to playlist",
        "my go-to playlist",
        "go to playlist",
        "go-to playlist",
        "the playlist i always play",
        "the playlist i usually play",
        "my playlist",
    )


    return any(
        alias in value
        for alias in aliases
    )


def apollo_music_recent_personal_context(
    limit=120
):

    conn = db()

    rows = conn.execute(
        """
        SELECT
            role,
            content,
            created_at
        FROM messages
        WHERE content IS NOT NULL
          AND TRIM(content) != ''
        ORDER BY id DESC
        LIMIT ?
        """,
        (
            int(limit),
        )
    ).fetchall()

    conn.close()


    # Put them back into chronological order.
    rows = list(
        reversed(rows)
    )


    return [
        {
            "role":
                row["role"],

            "content":
                row["content"]
        }
        for row in rows
    ]


def apollo_music_resolve_personal_alias(
    user_request
):

    value = str(
        user_request or ""
    ).strip()


    if not value:
        return None


    # Only use semantic personal-alias resolution for short,
    # ambiguous Music-surface language.
    #
    # Literal playlist names are checked before this function.
    # Long / clearly specific music requests should continue
    # into the normal track / album / artist interpreter.
    if len(
        value.split()
    ) > 10:
        return None


    playlists = (
        apollo_spotify_personal_playlists()
    )


    if not playlists:
        return None


    history = (
        apollo_music_recent_personal_context()
    )


    playlist_names = [
        str(
            item.get("name")
        ).strip()
        for item in playlists
        if str(
            item.get("name")
            or ""
        ).strip()
    ]


    # Keep only compact history relevant to music / playlists
    # so the resolver gets signal instead of the entire life story.
    relevant_history = []

    music_terms = (
        "playlist",
        "spotify",
        "music",
        "play ",
        "songs",
        "album",
        "artist",
        "main",
        "usual",
        "favorite",
        "favourite",
    )


    for item in history:

        content = str(
            item.get(
                "content",
                ""
            )
        ).strip()


        lower = content.lower()


        if any(
            term in lower
            for term in music_terms
        ):

            relevant_history.append({
                "role":
                    item.get("role"),

                "content":
                    content[:1000]
            })


    # Only the most recent useful pieces.
    relevant_history = (
        relevant_history[-35:]
    )


    resolver_prompt = [
        {
            "role": "system",
            "content": (
                "You resolve the user's personal Spotify playlist references "
                "and informal personal music language. "
                "The user may refer to a playlist indirectly, casually, or with slang. "
                "Examples include 'my main playlist', 'my usual', 'play my jams', "
                "'put on my shit', 'you know what to play', 'the main one', "
                "'my playlist', or stretched / playful wording like "
                "'play my jaaammmssss'. "
                "\n\n"
                "You receive:\n"
                "1. The user's REAL Spotify playlist names.\n"
                "2. Relevant prior Apollo conversation history.\n"
                "3. The new request.\n\n"
                "Interpret the user's wording semantically, not literally. "
                "Informal words like 'jams', 'my shit', 'usual', 'main one', "
                "or stretched spelling can refer to a known personal playlist. "
                "Use prior history to determine the user's established default / main "
                "playlist or other known personal references. "
                "You MUST choose an exact playlist name from the supplied "
                "Spotify playlist list. "
                "NEVER invent a playlist name. "
                "Do NOT resolve if the message clearly names a song, artist, album, "
                "genre, mood, or another specific non-personal music request. "
                "If the personal reference is genuinely ambiguous, return resolved=false. "
                "\n\n"
                "Return VALID JSON ONLY:\n"
                "{"
                "\"resolved\":true|false,"
                "\"playlist_name\":null|\"EXACT REAL PLAYLIST NAME\","
                "\"confidence\":0.0"
                "}"
            )
        },
        {
            "role": "user",
            "content": (
                "REAL SPOTIFY PLAYLISTS:\n"
                + json.dumps(
                    playlist_names,
                    ensure_ascii=False
                )
                + "\n\n"
                + "RELEVANT APOLLO HISTORY:\n"
                + json.dumps(
                    relevant_history,
                    ensure_ascii=False
                )
                + "\n\n"
                + "CURRENT REQUEST:\n"
                + str(user_request)
            )
        }
    ]


    try:

        raw = ask_hermes(
            resolver_prompt
        ).strip()


        if raw.startswith("```"):

            raw = raw.strip("`")

            if raw.lower().startswith(
                "json"
            ):
                raw = raw[4:].strip()


        result = json.loads(
            raw
        )

    except Exception as error:

        print(
            "[Apollo Music Alias] "
            f"Resolver failed: {error}"
        )

        return None


    if not bool(
        result.get("resolved")
    ):
        return None


    resolved_name = str(
        result.get(
            "playlist_name"
        )
        or ""
    ).strip()


    if not resolved_name:
        return None


    # Final deterministic guard:
    # Hermes can only select a playlist that really exists.
    exact_lookup = {
        name.lower():
            name
        for name in playlist_names
    }


    real_name = (
        exact_lookup.get(
            resolved_name.lower()
        )
    )


    if not real_name:
        return None


    return real_name


def apollo_music_play_request(user_request):
    """
    Interpret a natural-language Music-tab request and start
    Spotify using a real album / artist / playlist context.
    """

    user_request = str(
        user_request or ""
    ).strip()

    if not user_request:
        raise ValueError(
            "Music request is empty"
        )


    interpreter_messages = [
        {
            "role": "system",
            "content": (
                "You are the intent parser for Apollo's Spotify player. "
                "Convert the user's request into JSON ONLY. "
                "Never answer conversationally. "
                "\n\n"
                "Allowed types: track, album, artist, playlist, liked."
                "\n\n"
                "Rules:\n"
                "- An exact song request => track.\n"
                "- An album/project request => album.\n"
                "- Relative album requests like 'newest album', 'latest album', "
                "'most recent album' are album requests.\n"
                "- For relative album requests, put the ARTIST NAME in artist, "
                "and set query to newest/latest/most recent rather than inventing "
                "an album title.\n"
                "- Understand common artist nicknames/short forms from context "
                "when confidence is high, e.g. 'party' may mean PARTYNEXTDOOR.\n"
                "- 'play [artist]' or music by one artist => artist.\n"
                "- Mood, genre, vibe, activity, or general listening "
                "request => playlist.\n"
                "- Personal playlist references like 'my main playlist', "
                "'my gym playlist', 'my ug rnb playlist', or 'my chill playlist' "
                "are playlist requests. Preserve the identifying words in query.\n"
                "- For 'my main playlist', query MUST be 'main'.\n"
                "- For 'my ug rnb playlist', query MUST be 'ug rnb'.\n"
                "- For 'my gym playlist', query MUST be 'gym'.\n"
                "- NEVER return type=playlist with an empty query when the user "
                "provided any identifying playlist words.\n"
                "- Remove helper words like 'play', 'my', and 'playlist' from "
                "playlist query when possible, but preserve the meaningful name.\n"
                "- 'liked songs', 'my liked', 'my likes', 'saved songs', "
                "'my saved tracks' => liked. NEVER treat these as playlists.\n"
                "- If the user says shuffle, set shuffle=true.\n"
                "- For track requests, separate title and artist when known.\n"
                "- query should contain useful Spotify search text.\n"
                "\n"
                "Return exactly this shape:\n"
                "{"
                "\"type\":\"track|album|artist|playlist\","
                "\"query\":\"...\","
                "\"title\":\"...\","
                "\"artist\":\"...\""
                "}"
            )
        },
        {
            "role": "user",
            "content": user_request
        }
    ]


    raw = ask_hermes(
        interpreter_messages
    ).strip()


    # tolerate accidental markdown fences
    if raw.startswith("```"):
        raw = raw.strip("`")

        if raw.lower().startswith("json"):
            raw = raw[4:].strip()


    try:
        intent = json.loads(raw)

    except Exception:
        raise RuntimeError(
            "Apollo could not understand the music request"
        )


    kind = str(
        intent.get("type", "")
    ).strip().lower()


    if kind not in {
        "track",
        "album",
        "artist",
        "playlist",
        "liked"
    }:
        raise RuntimeError(
            "Apollo returned an invalid music request type"
        )


    query_value = str(
        intent.get(
            "query",
            ""
        )
    ).strip()


    if (
        kind == "playlist"
        and not query_value
    ):

        import re


        fallback_query = (
            user_request
            .strip()
            .lower()
        )


        # Remove obvious command framing while preserving
        # the actual identifying playlist words.
        fallback_query = re.sub(
            r"^\\s*(?:please\\s+)?(?:play|put on|start)\\s+",
            "",
            fallback_query
        )


        fallback_query = re.sub(
            r"^\\s*my\\s+",
            "",
            fallback_query
        )


        fallback_query = re.sub(
            r"\\s+playlist\\s*$",
            "",
            fallback_query
        )


        fallback_query = re.sub(
            r"\\s+",
            " ",
            fallback_query
        ).strip()


        if fallback_query:

            query_value = (
                fallback_query
            )


    payload = {
        "type": kind,
        "query":
            query_value,
        "title": str(
            intent.get("title", "")
        ).strip(),
        "artist": str(
            intent.get("artist", "")
        ).strip(),
        "shuffle": bool(
            intent.get("shuffle", False)
        )
    }


    result = subprocess.run(
        [
            SPOTIFY_PYTHON,
            SPOTIFY_TOOL,
            "play-request",
            json.dumps(
                payload,
                ensure_ascii=False
            )
        ],
        capture_output=True,
        text=True,
        timeout=30
    )


    if result.returncode != 0:

        raise RuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
            or "Spotify could not start playback"
        )


    output = result.stdout.strip()


    try:
        spotify_result = (
            json.loads(output)
            if output
            else {}
        )

    except Exception:
        spotify_result = {
            "ok": True
        }


    return {
        "ok": True,
        "intent": payload,
        "spotify": spotify_result,
        "playback": get_now_playing()
    }



# ─────────────────────────────
# WHOOP
# ─────────────────────────────

WHOOP_OAUTH_FILE = BASE_DIR / "whoop_oauth.json"

WHOOP_REDIRECT_URI = (
    "https://ubuntu-2gb-hel1-1.tailc5eaaa.ts.net"
    "/api/whoop/callback"
)

WHOOP_AUTH_URI = (
    "https://api.prod.whoop.com/oauth/oauth2/auth"
)

WHOOP_TOKEN_URI = (
    "https://api.prod.whoop.com/oauth/oauth2/token"
)

WHOOP_SCOPES = " ".join([
    "read:recovery",
    "read:cycles",
    "read:workout",
    "read:sleep",
    "read:profile",
    "read:body_measurement",
    "offline",
])


def get_whoop_oauth_config():

    if not WHOOP_OAUTH_FILE.exists():
        raise RuntimeError(
            "WHOOP OAuth credentials file not found"
        )

    data = json.loads(
        WHOOP_OAUTH_FILE.read_text()
    )

    client_id = str(
        data.get(
            "client_id",
            ""
        )
    ).strip()

    client_secret = str(
        data.get(
            "client_secret",
            ""
        )
    ).strip()

    if not client_id or not client_secret:
        raise RuntimeError(
            "WHOOP client ID or secret missing"
        )

    return {
        "client_id": client_id,
        "client_secret": client_secret,
    }


def whoop_authorization_url():

    config = get_whoop_oauth_config()

    state = secrets.token_urlsafe(32)

    app_state_set(
        "whoop_oauth_state",
        state
    )

    app_state_set(
        "whoop_oauth_state_created_at",
        str(int(time.time()))
    )

    params = {
        "client_id":
            config["client_id"],

        "redirect_uri":
            WHOOP_REDIRECT_URI,

        "response_type":
            "code",

        "scope":
            WHOOP_SCOPES,

        "state":
            state,
    }

    return (
        WHOOP_AUTH_URI
        + "?"
        + urllib.parse.urlencode(
            params
        )
    )


def whoop_save_token_data(
    token_data
):

    access_token = str(
        token_data.get(
            "access_token",
            ""
        )
    ).strip()

    refresh_token = str(
        token_data.get(
            "refresh_token",
            ""
        )
    ).strip()

    expires_in = int(
        token_data.get(
            "expires_in",
            3600
        )
    )

    if not access_token:
        raise RuntimeError(
            "WHOOP did not return an access token"
        )

    app_state_set(
        "whoop_access_token",
        access_token
    )

    app_state_set(
        "whoop_access_token_expires_at",
        str(
            int(time.time())
            + expires_in
            - 60
        )
    )

    # WHOOP refresh tokens rotate.
    # Save a newly returned token whenever present.
    if refresh_token:
        app_state_set(
            "whoop_refresh_token",
            refresh_token
        )

    if not app_state_get(
        "whoop_refresh_token"
    ):
        raise RuntimeError(
            "WHOOP did not provide a refresh token"
        )


def whoop_exchange_code(
    code
):

    config = get_whoop_oauth_config()

    payload = urllib.parse.urlencode({
        "grant_type":
            "authorization_code",

        "code":
            code,

        "client_id":
            config["client_id"],

        "client_secret":
            config["client_secret"],

        "redirect_uri":
            WHOOP_REDIRECT_URI,
    }).encode(
        "utf-8"
    )

    request = urllib.request.Request(
        WHOOP_TOKEN_URI,
        data=payload,
        headers={
            "Content-Type":
                "application/x-www-form-urlencoded",
            "User-Agent":
                "Apollo/1.0"
        },
        method="POST"
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:

            token_data = json.loads(
                response.read().decode(
                    "utf-8"
                )
            )

    except urllib.error.HTTPError as exc:

        body = exc.read().decode(
            "utf-8",
            errors="replace"
        )

        raise RuntimeError(
            "WHOOP token exchange failed: "
            + str(exc.code)
            + " "
            + body
        )

    whoop_save_token_data(
        token_data
    )


def whoop_get_access_token():

    access_token = app_state_get(
        "whoop_access_token"
    )

    expires_at = int(
        app_state_get(
            "whoop_access_token_expires_at",
            "0"
        )
    )

    if (
        access_token
        and time.time() < expires_at
    ):
        return access_token


    refresh_token = app_state_get(
        "whoop_refresh_token"
    )

    if not refresh_token:
        raise RuntimeError(
            "WHOOP is not connected"
        )


    config = get_whoop_oauth_config()

    payload = urllib.parse.urlencode({
        "grant_type":
            "refresh_token",

        "refresh_token":
            refresh_token,

        "client_id":
            config["client_id"],

        "client_secret":
            config["client_secret"],

        "scope":
            "offline",
    }).encode(
        "utf-8"
    )

    request = urllib.request.Request(
        WHOOP_TOKEN_URI,
        data=payload,
        headers={
            "Content-Type":
                "application/x-www-form-urlencoded",
            "User-Agent":
                "Apollo/1.0"
        },
        method="POST"
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:

            token_data = json.loads(
                response.read().decode(
                    "utf-8"
                )
            )

    except urllib.error.HTTPError as exc:

        body = exc.read().decode(
            "utf-8",
            errors="replace"
        )

        raise RuntimeError(
            "WHOOP token refresh failed: "
            + str(exc.code)
            + " "
            + body
        )

    whoop_save_token_data(
        token_data
    )

    return app_state_get(
        "whoop_access_token"
    )



WHOOP_API_BASE = (
    "https://api.prod.whoop.com/developer/v2"
)


def whoop_api_get(
    endpoint
):

    token = whoop_get_access_token()

    request = urllib.request.Request(
        WHOOP_API_BASE + endpoint,
        headers={
            "Authorization":
                f"Bearer {token}",

            "Accept":
                "application/json",

            "User-Agent":
                "Apollo/1.0",
        }
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:

            return json.loads(
                response.read().decode(
                    "utf-8"
                )
            )

    except urllib.error.HTTPError as exc:

        body = exc.read().decode(
            "utf-8",
            errors="replace"
        )

        raise RuntimeError(
            "WHOOP API request failed: "
            + str(exc.code)
            + " "
            + body
        )


def whoop_millis_hours(
    value
):

    try:
        return round(
            float(value) / 3600000,
            2
        )

    except (
        TypeError,
        ValueError
    ):
        return None


def whoop_current_summary():

    recovery_data = whoop_api_get(
        "/recovery?limit=1"
    )

    cycle_data = whoop_api_get(
        "/cycle?limit=1"
    )

    sleep_data = whoop_api_get(
        "/activity/sleep?limit=1"
    )


    recovery_records = (
        recovery_data.get(
            "records"
        )
        or []
    )

    cycle_records = (
        cycle_data.get(
            "records"
        )
        or []
    )

    sleep_records = (
        sleep_data.get(
            "records"
        )
        or []
    )


    recovery = (
        recovery_records[0]
        if recovery_records
        else {}
    )

    cycle = (
        cycle_records[0]
        if cycle_records
        else {}
    )

    sleep = (
        sleep_records[0]
        if sleep_records
        else {}
    )


    recovery_score = (
        recovery.get(
            "score"
        )
        or {}
    )

    cycle_score = (
        cycle.get(
            "score"
        )
        or {}
    )

    sleep_score = (
        sleep.get(
            "score"
        )
        or {}
    )

    stage_summary = (
        sleep_score.get(
            "stage_summary"
        )
        or {}
    )

    sleep_needed = (
        sleep_score.get(
            "sleep_needed"
        )
        or {}
    )


    total_sleep_milli = (
        float(
            stage_summary.get(
                "total_light_sleep_time_milli",
                0
            )
            or 0
        )
        + float(
            stage_summary.get(
                "total_slow_wave_sleep_time_milli",
                0
            )
            or 0
        )
        + float(
            stage_summary.get(
                "total_rem_sleep_time_milli",
                0
            )
            or 0
        )
    )


    total_sleep_need_milli = (
        float(
            sleep_needed.get(
                "baseline_milli",
                0
            )
            or 0
        )
        + float(
            sleep_needed.get(
                "need_from_sleep_debt_milli",
                0
            )
            or 0
        )
        + float(
            sleep_needed.get(
                "need_from_recent_strain_milli",
                0
            )
            or 0
        )
        + float(
            sleep_needed.get(
                "need_from_recent_nap_milli",
                0
            )
            or 0
        )
    )


    return {
        "recovery": {
            "cycle_id":
                recovery.get(
                    "cycle_id"
                ),

            "sleep_id":
                recovery.get(
                    "sleep_id"
                ),

            "score":
                recovery_score.get(
                    "recovery_score"
                ),

            "hrv_ms":
                recovery_score.get(
                    "hrv_rmssd_milli"
                ),

            "resting_heart_rate":
                recovery_score.get(
                    "resting_heart_rate"
                ),

            "spo2_percentage":
                recovery_score.get(
                    "spo2_percentage"
                ),

            "skin_temp_celsius":
                recovery_score.get(
                    "skin_temp_celsius"
                ),

            "score_state":
                recovery.get(
                    "score_state"
                ),

            "updated_at":
                recovery.get(
                    "updated_at"
                ),
        },

        "cycle": {
            "strain":
                cycle_score.get(
                    "strain"
                ),

            "kilojoule":
                cycle_score.get(
                    "kilojoule"
                ),

            "average_heart_rate":
                cycle_score.get(
                    "average_heart_rate"
                ),

            "max_heart_rate":
                cycle_score.get(
                    "max_heart_rate"
                ),

            "start":
                cycle.get(
                    "start"
                ),

            "end":
                cycle.get(
                    "end"
                ),

            "updated_at":
                cycle.get(
                    "updated_at"
                ),
        },

        "sleep": {
            "id":
                sleep.get(
                    "id"
                ),

            "cycle_id":
                sleep.get(
                    "cycle_id"
                ),

            "nap":
                bool(
                    sleep.get(
                        "nap",
                        False
                    )
                ),

            "score_state":
                sleep.get(
                    "score_state"
                ),

            "performance_percentage":
                sleep_score.get(
                    "sleep_performance_percentage"
                ),

            "efficiency_percentage":
                sleep_score.get(
                    "sleep_efficiency_percentage"
                ),

            "consistency_percentage":
                sleep_score.get(
                    "sleep_consistency_percentage"
                ),

            "respiratory_rate":
                sleep_score.get(
                    "respiratory_rate"
                ),

            "total_sleep_hours":
                whoop_millis_hours(
                    total_sleep_milli
                ),

            "sleep_need_hours":
                whoop_millis_hours(
                    total_sleep_need_milli
                ),

            "time_in_bed_hours":
                whoop_millis_hours(
                    stage_summary.get(
                        "total_in_bed_time_milli"
                    )
                ),

            "awake_hours":
                whoop_millis_hours(
                    stage_summary.get(
                        "total_awake_time_milli"
                    )
                ),

            "light_sleep_hours":
                whoop_millis_hours(
                    stage_summary.get(
                        "total_light_sleep_time_milli"
                    )
                ),

            "deep_sleep_hours":
                whoop_millis_hours(
                    stage_summary.get(
                        "total_slow_wave_sleep_time_milli"
                    )
                ),

            "rem_sleep_hours":
                whoop_millis_hours(
                    stage_summary.get(
                        "total_rem_sleep_time_milli"
                    )
                ),

            "disturbance_count":
                stage_summary.get(
                    "disturbance_count"
                ),

            "sleep_cycle_count":
                stage_summary.get(
                    "sleep_cycle_count"
                ),

            "start":
                sleep.get(
                    "start"
                ),

            "end":
                sleep.get(
                    "end"
                ),

            "updated_at":
                sleep.get(
                    "updated_at"
                ),
        },
    }




def whoop_format_hours(
    value
):

    if value is None:
        return None

    total_minutes = round(
        float(value) * 60
    )

    hours = (
        total_minutes // 60
    )

    minutes = (
        total_minutes % 60
    )

    if hours and minutes:
        return f"{hours}h {minutes}m"

    if hours:
        return f"{hours}h"

    return f"{minutes}m"


def whoop_summary_is_current_morning(
    summary
):

    recovery = (
        summary.get("recovery")
        or {}
    )

    sleep = (
        summary.get("sleep")
        or {}
    )


    # Main overnight sleep only.
    if sleep.get("nap"):
        return False


    sleep_end = (
        sleep.get("end")
    )

    if not sleep_end:
        return False


    time_zone = (
        app_state_get(
            "time_zone"
        )
        or "America/Chicago"
    )


    try:

        zone = ZoneInfo(
            time_zone
        )


        value = str(
            sleep_end
        ).strip()


        if value.endswith("Z"):
            value = (
                value[:-1]
                + "+00:00"
            )


        ended_at = (
            datetime.fromisoformat(
                value
            )
        )


        if ended_at.tzinfo is None:
            return False


        local_end = (
            ended_at.astimezone(
                zone
            )
        )


        local_now = (
            datetime.now(
                zone
            )
        )


    except Exception:
        return False


    # This sleep must have ended during the user's
    # current local calendar day.
    if (
        local_end.date()
        != local_now.date()
    ):
        return False


    # Recovery must belong to this exact sleep.
    recovery_sleep_id = str(
        recovery.get(
            "sleep_id"
        )
        or ""
    )

    sleep_id = str(
        sleep.get(
            "id"
        )
        or ""
    )


    if (
        not recovery_sleep_id
        or not sleep_id
        or recovery_sleep_id
            != sleep_id
    ):
        return False


    # Both records must actually be scored.
    if (
        recovery.get(
            "score_state"
        )
        != "SCORED"
    ):
        return False


    if (
        sleep.get(
            "score_state"
        )
        != "SCORED"
    ):
        return False


    return True


def whoop_latest_workout():

    data = whoop_api_get(
        "/activity/workout?limit=1"
    )

    records = (
        data.get("records")
        or []
    )

    if not records:
        return {}


    workout = records[0]

    score = (
        workout.get("score")
        or {}
    )


    return {
        "id":
            workout.get("id"),

        "sport_name":
            workout.get(
                "sport_name"
            ),

        "score_state":
            workout.get(
                "score_state"
            ),

        "strain":
            score.get(
                "strain"
            ),

        "average_heart_rate":
            score.get(
                "average_heart_rate"
            ),

        "max_heart_rate":
            score.get(
                "max_heart_rate"
            ),

        "kilojoule":
            score.get(
                "kilojoule"
            ),

        "start":
            workout.get(
                "start"
            ),

        "end":
            workout.get(
                "end"
            ),

        "updated_at":
            workout.get(
                "updated_at"
            ),
    }


def whoop_datetime_is_today(
    value
):

    if not value:
        return False


    try:

        time_zone = (
            app_state_get(
                "time_zone"
            )
            or "America/Chicago"
        )

        zone = ZoneInfo(
            time_zone
        )


        raw = str(
            value
        ).strip()


        if raw.endswith("Z"):
            raw = (
                raw[:-1]
                + "+00:00"
            )


        parsed = (
            datetime.fromisoformat(
                raw
            )
        )


        if parsed.tzinfo is None:
            return False


        return (
            parsed.astimezone(
                zone
            ).date()
            == datetime.now(
                zone
            ).date()
        )


    except Exception:
        return False


def whoop_rule_based_interpretation(
    summary
):

    recovery = (
        summary.get("recovery")
        or {}
    )

    cycle = (
        summary.get("cycle")
        or {}
    )

    sleep = (
        summary.get("sleep")
        or {}
    )


    recovery_score = (
        recovery.get("score")
    )

    strain = (
        cycle.get("strain")
    )

    sleep_hours = (
        sleep.get(
            "total_sleep_hours"
        )
    )

    sleep_need = (
        sleep.get(
            "sleep_need_hours"
        )
    )


    sentences = []


    if recovery_score is not None:

        if recovery_score >= 67:

            sentences.append(
                f"You're in a good spot today with "
                f"{round(recovery_score)}% recovery."
            )

        elif recovery_score >= 34:

            sentences.append(
                f"Recovery is moderate today at "
                f"{round(recovery_score)}%, so you have "
                f"some capacity but you're not fully topped off."
            )

        else:

            sentences.append(
                f"Recovery is low today at "
                f"{round(recovery_score)}%, so your body "
                f"looks like it could use an easier day."
            )


    if (
        sleep_hours is not None
        and sleep_need is not None
    ):

        difference = (
            sleep_need
            - sleep_hours
        )

        if difference > 0.25:

            sentences.append(
                f"You slept "
                f"{whoop_format_hours(sleep_hours)}, about "
                f"{whoop_format_hours(difference)} short of "
                f"your WHOOP sleep need."
            )

        else:

            sentences.append(
                f"You got about "
                f"{whoop_format_hours(sleep_hours)} of sleep "
                f"and were close to your sleep need."
            )


    if strain is not None:

        if strain < 4:

            sentences.append(
                "Your strain is still low so far, leaving "
                "plenty of room for activity later today."
            )

        elif strain < 10:

            sentences.append(
                "You've built some strain already, but the day "
                "is still relatively manageable."
            )

        else:

            sentences.append(
                "You've already accumulated meaningful strain, "
                "so factor that into anything intense later."
            )


    return " ".join(
        sentences[:3]
    )


def whoop_calendar_context():
    """
    Compact upcoming calendar context for WHOOP guidance.

    This is intentionally limited to the next 24 hours so
    Apollo can help pace the rest of the day without dumping
    the user's entire calendar into the interpretation.
    """

    try:
        events = google_calendar_events(
            days=1
        )
    except Exception as exc:
        print(
            "[Apollo WHOOP] Calendar context unavailable:",
            exc
        )
        return []


    compact = []

    for event in (events or [])[:8]:

        if not isinstance(event, dict):
            continue


        start = (
            event.get("start")
            or {}
        )


        compact.append({
            "id":
                event.get("id"),

            "summary":
                event.get("summary")
                or "(No title)",

            "start":
                start,

            "location":
                event.get("location"),

            "description":
                (
                    str(
                        event.get("description")
                        or ""
                    )[:240]
                    or None
                )
        })


    return compact


def whoop_calendar_signature(
    events
):

    try:
        return json.dumps(
            [
                {
                    "id":
                        event.get("id"),

                    "summary":
                        event.get("summary"),

                    "start":
                        event.get("start")
                }
                for event in (
                    events
                    or []
                )
                if isinstance(
                    event,
                    dict
                )
            ],
            sort_keys=True,
            ensure_ascii=False
        )

    except Exception:
        return ""


def whoop_generate_interpretation(
    summary,
    workout,
    calendar_events=None
):

    context = {
        "recovery":
            summary.get(
                "recovery"
            ),

        "cycle":
            summary.get(
                "cycle"
            ),

        "sleep":
            summary.get(
                "sleep"
            ),

        "latest_workout_today":
            workout
            if (
                workout
                and whoop_datetime_is_today(
                    workout.get(
                        "end"
                    )
                )
            )
            else None,

        "time_zone":
            app_state_get(
                "time_zone",
                "UTC"
            ),

        "upcoming_calendar_events_next_24h":
            calendar_events
            or [],
    }


    messages = [
        {
            "role": "system",
            "content": (
                "You are writing one short WHOOP insight for "
                "Apollo's personal home dashboard. "
                "Use ONLY the physiological data and upcoming "
                "calendar context supplied below. "
                "Do not browse, search, use tools, inspect files, "
                "or look anything up. "
                "Write 2 or 3 concise natural sentences. "
                "Interpret what matters right now and help the user "
                "decide how to handle the rest of the day. "
                "Use upcoming calendar events when they are relevant "
                "to pacing, activity, recovery, meals, hydration, "
                "or conserving energy. "
                "For example, if an active event such as a hike, run, "
                "boxing session, soccer game, or workout is coming up, "
                "factor current recovery, sleep and strain into how "
                "the user should approach the hours beforehand. "
                "Do not assume an event is physically demanding unless "
                "its title or description reasonably suggests that. "
                "If there is a completed workout from today, "
                "acknowledge it naturally and explain what it did "
                "to the day's strain when useful. "
                "Do not mechanically list calendar events; only mention "
                "them when they make the WHOOP guidance more useful. "
                "Sound calm, personal and practical, not clinical "
                "or motivational-speaker-like. "
                "Do not diagnose medical conditions. "
                "Do not mention that you are an AI. "
                "Return only the interpretation text."
            )
        },
        {
            "role": "user",
            "content": json.dumps(
                context,
                ensure_ascii=False
            )
        }
    ]


    result = ask_hermes(
        messages
    ).strip()


    if not result:
        raise RuntimeError(
            "Hermes returned no WHOOP interpretation"
        )


    return result


def whoop_smart_interpretation(
    summary,
    workout,
    calendar_events=None
):

    now_epoch = int(
        time.time()
    )


    cached_text = (
        app_state_get(
            "whoop_interpretation_text"
        )
        or ""
    ).strip()


    try:
        cached_at = int(
            app_state_get(
                "whoop_interpretation_generated_at",
                "0"
            )
        )
    except ValueError:
        cached_at = 0


    cached_workout_id = (
        app_state_get(
            "whoop_interpretation_workout_id"
        )
        or ""
    )


    try:
        cached_strain = float(
            app_state_get(
                "whoop_interpretation_strain",
                "0"
            )
        )
    except ValueError:
        cached_strain = 0.0


    cycle = (
        summary.get("cycle")
        or {}
    )


    try:
        current_strain = float(
            cycle.get(
                "strain"
            )
            or 0
        )
    except (
        TypeError,
        ValueError
    ):
        current_strain = 0.0


    workout_today = (
        workout
        if (
            workout
            and workout.get(
                "score_state"
            )
            == "SCORED"
            and whoop_datetime_is_today(
                workout.get(
                    "end"
                )
            )
        )
        else {}
    )


    current_workout_id = str(
        workout_today.get(
            "id"
        )
        or ""
    )


    expired = (
        not cached_text
        or (
            now_epoch
            - cached_at
            >= 7200
        )
    )


    new_workout = (
        bool(
            current_workout_id
        )
        and (
            current_workout_id
            != cached_workout_id
        )
    )


    meaningful_strain_change = (
        bool(
            cached_text
        )
        and abs(
            current_strain
            - cached_strain
        )
        >= 3.0
    )


    if calendar_events is None:
        calendar_events = (
            whoop_calendar_context()
        )


    current_calendar_signature = (
        whoop_calendar_signature(
            calendar_events
        )
    )


    cached_calendar_signature = (
        app_state_get(
            "whoop_interpretation_calendar_signature"
        )
        or ""
    )


    calendar_changed = (
        current_calendar_signature
        != cached_calendar_signature
    )


    should_refresh = (
        expired
        or new_workout
        or meaningful_strain_change
        or calendar_changed
    )


    if not should_refresh:
        return cached_text


    try:

        interpretation = (
            whoop_generate_interpretation(
                summary,
                workout_today,
                calendar_events
            )
        )

    except Exception as exc:

        print(
            "[Apollo WHOOP] Interpretation fallback:",
            exc
        )

        interpretation = (
            whoop_rule_based_interpretation(
                summary
            )
        )


    app_state_set(
        "whoop_interpretation_text",
        interpretation
    )

    app_state_set(
        "whoop_interpretation_generated_at",
        str(
            now_epoch
        )
    )

    app_state_set(
        "whoop_interpretation_workout_id",
        current_workout_id
    )

    app_state_set(
        "whoop_interpretation_strain",
        str(
            current_strain
        )
    )


    app_state_set(
        "whoop_interpretation_calendar_signature",
        current_calendar_signature
    )


    return interpretation


def whoop_card_payload():

    summary = (
        whoop_current_summary()
    )


    # Never present yesterday's latest record as today's.
    if not whoop_summary_is_current_morning(
        summary
    ):

        return {
            "status":
                "processing",

            "interpretation": (
                "WHOOP is still processing today's recovery. "
                "Apollo will update this automatically as soon "
                "as your new sleep and recovery are ready."
            ),

            "summary":
                {},
        }


    workout = {}


    try:

        workout = (
            whoop_latest_workout()
        )

    except Exception as exc:

        print(
            "[Apollo WHOOP] Workout fetch failed:",
            exc
        )


    calendar_events = (
        whoop_calendar_context()
    )


    interpretation = (
        whoop_smart_interpretation(
            summary,
            workout,
            calendar_events
        )
    )


    return {
        "status":
            "ready",

        "interpretation":
            interpretation,

        "summary":
            summary,

        "latest_workout":
            workout
            if (
                workout
                and whoop_datetime_is_today(
                    workout.get(
                        "end"
                    )
                )
            )
            else None,
    }


# ─────────────────────────────
# GOOGLE CALENDAR
# ─────────────────────────────

GOOGLE_OAUTH_FILE = BASE_DIR / "google_oauth.json"
GOOGLE_REDIRECT_URI = (
    "https://ubuntu-2gb-hel1-1.tailc5eaaa.ts.net"
    "/api/google/callback"
)

GOOGLE_CALENDAR_SCOPE = (
    "https://www.googleapis.com/auth/calendar"
)


def app_state_get(key, default=None):
    conn = db()

    row = conn.execute(
        "SELECT value FROM app_state WHERE key = ?",
        (key,)
    ).fetchone()

    conn.close()

    if not row:
        return default

    return row["value"]


def app_state_set(key, value):
    conn = db()

    conn.execute("""
        INSERT INTO app_state (
            key,
            value
        )
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET
            value = excluded.value
    """, (key, str(value)))

    conn.commit()
    conn.close()


def app_state_delete(key):
    conn = db()

    conn.execute(
        "DELETE FROM app_state WHERE key = ?",
        (key,)
    )

    conn.commit()
    conn.close()


def get_google_oauth_config():
    if not GOOGLE_OAUTH_FILE.exists():
        raise RuntimeError(
            "Google OAuth credentials file not found"
        )

    data = json.loads(
        GOOGLE_OAUTH_FILE.read_text()
    )

    config = (
        data.get("web")
        or data.get("installed")
    )

    if not config:
        raise RuntimeError(
            "Invalid Google OAuth credentials file"
        )

    client_id = config.get("client_id")
    client_secret = config.get("client_secret")

    if not client_id or not client_secret:
        raise RuntimeError(
            "Google OAuth client ID or secret missing"
        )

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "auth_uri": config.get(
            "auth_uri",
            "https://accounts.google.com/o/oauth2/v2/auth"
        ),
        "token_uri": config.get(
            "token_uri",
            "https://oauth2.googleapis.com/token"
        ),
    }


def google_authorization_url():
    config = get_google_oauth_config()

    state = secrets.token_urlsafe(32)

    app_state_set(
        "google_oauth_state",
        state
    )

    app_state_set(
        "google_oauth_state_created_at",
        str(int(time.time()))
    )

    params = {
        "client_id": config["client_id"],
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": GOOGLE_CALENDAR_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }

    return (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        + urllib.parse.urlencode(params)
    )


def google_exchange_code(code):
    config = get_google_oauth_config()

    payload = urllib.parse.urlencode({
        "code": code,
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode("utf-8")

    request = urllib.request.Request(
        config["token_uri"],
        data=payload,
        headers={
            "Content-Type":
                "application/x-www-form-urlencoded"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:
            token_data = json.loads(
                response.read().decode("utf-8")
            )

    except urllib.error.HTTPError as exc:
        body = exc.read().decode(
            "utf-8",
            errors="replace"
        )

        raise RuntimeError(
            f"Google token exchange failed: "
            f"{exc.code} {body}"
        )

    access_token = token_data.get(
        "access_token"
    )

    refresh_token = token_data.get(
        "refresh_token"
    )

    expires_in = int(
        token_data.get(
            "expires_in",
            3600
        )
    )

    if not access_token:
        raise RuntimeError(
            "Google did not return an access token"
        )

    app_state_set(
        "google_access_token",
        access_token
    )

    app_state_set(
        "google_access_token_expires_at",
        str(
            int(time.time())
            + expires_in
            - 60
        )
    )

    if refresh_token:
        app_state_set(
            "google_refresh_token",
            refresh_token
        )

    if not app_state_get(
        "google_refresh_token"
    ):
        raise RuntimeError(
            "Google did not provide a refresh token"
        )


def google_get_access_token():
    access_token = app_state_get(
        "google_access_token"
    )

    expires_at = int(
        app_state_get(
            "google_access_token_expires_at",
            "0"
        )
    )

    if (
        access_token
        and time.time() < expires_at
    ):
        return access_token

    refresh_token = app_state_get(
        "google_refresh_token"
    )

    if not refresh_token:
        raise RuntimeError(
            "Google Calendar is not connected"
        )

    config = get_google_oauth_config()

    payload = urllib.parse.urlencode({
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode("utf-8")

    request = urllib.request.Request(
        config["token_uri"],
        data=payload,
        headers={
            "Content-Type":
                "application/x-www-form-urlencoded"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:
            token_data = json.loads(
                response.read().decode("utf-8")
            )

    except urllib.error.HTTPError as exc:
        body = exc.read().decode(
            "utf-8",
            errors="replace"
        )

        raise RuntimeError(
            f"Google token refresh failed: "
            f"{exc.code} {body}"
        )

    access_token = token_data.get(
        "access_token"
    )

    if not access_token:
        raise RuntimeError(
            "Google did not return a refreshed access token"
        )

    expires_in = int(
        token_data.get(
            "expires_in",
            3600
        )
    )

    app_state_set(
        "google_access_token",
        access_token
    )

    app_state_set(
        "google_access_token_expires_at",
        str(
            int(time.time())
            + expires_in
            - 60
        )
    )

    return access_token


def google_calendar_events(days=7, start_date=None):
    token = google_get_access_token()

    if start_date:
        try:
            tz_name = app_state_get(
                "time_zone",
                "UTC"
            )

            tz = ZoneInfo(tz_name)

            local_start = datetime.strptime(
                start_date,
                "%Y-%m-%d"
            ).replace(
                tzinfo=tz
            )

            range_start = local_start.astimezone(
                timezone.utc
            )

        except Exception:
            raise RuntimeError(
                "Invalid calendar start date"
            )

    else:
        range_start = datetime.now(
            timezone.utc
        )

    time_min = (
        range_start.isoformat()
        .replace("+00:00", "Z")
    )

    time_max = (
        (range_start + timedelta(days=days))
        .isoformat()
        .replace("+00:00", "Z")
    )

    params = urllib.parse.urlencode({
        "timeMin": time_min,
        "timeMax": time_max,
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": "100",
    })

    url = (
        "https://www.googleapis.com/calendar/v3/"
        "calendars/primary/events?"
        + params
    )

    request = urllib.request.Request(
        url,
        headers={
            "Authorization":
                f"Bearer {token}"
        }
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:
            data = json.loads(
                response.read().decode("utf-8")
            )

    except urllib.error.HTTPError as exc:
        body = exc.read().decode(
            "utf-8",
            errors="replace"
        )

        raise RuntimeError(
            f"Google Calendar request failed: "
            f"{exc.code} {body}"
        )

    events = []

    for item in data.get("items", []):
        events.append({
            "id": item.get("id"),
            "summary": item.get(
                "summary",
                "(No title)"
            ),
            "start": item.get("start"),
            "end": item.get("end"),
            "location": item.get("location"),
            "description": item.get(
                "description"
            ),
            "status": item.get("status"),
            "htmlLink": item.get(
                "htmlLink"
            ),
            "recurringEventId":
                item.get(
                    "recurringEventId"
                ),
            "originalStartTime":
                item.get(
                    "originalStartTime"
                ),
            "recurrence":
                item.get(
                    "recurrence"
                ),
        })

    return events




# APOLLO GOOGLE CALENDAR CRUD V1

def google_calendar_api_request(
    method,
    event_id=None,
    body=None
):
    token = google_get_access_token()

    base = (
        "https://www.googleapis.com/calendar/v3/"
        "calendars/primary/events"
    )

    if event_id:
        url = (
            base
            + "/"
            + urllib.parse.quote(
                str(event_id),
                safe=""
            )
        )
    else:
        url = base

    data = None

    headers = {
        "Authorization":
            f"Bearer {token}"
    }

    if body is not None:
        data = json.dumps(
            body,
            ensure_ascii=False
        ).encode("utf-8")

        headers["Content-Type"] = (
            "application/json; charset=utf-8"
        )

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:

            raw = response.read()

            if not raw:
                return None

            return json.loads(
                raw.decode("utf-8")
            )

    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode(
            "utf-8",
            errors="replace"
        )

        raise RuntimeError(
            f"Google Calendar {method} failed: "
            f"{exc.code} {error_body}"
        )


def google_calendar_datetime(
    value,
    tz_name
):
    raw = str(value or "").strip()

    if not raw:
        raise ValueError(
            "Date/time is required"
        )

    try:
        parsed = datetime.fromisoformat(
            raw.replace(
                "Z",
                "+00:00"
            )
        )

    except ValueError:
        raise ValueError(
            f"Invalid date/time: {raw}"
        )

    try:
        tz = ZoneInfo(tz_name)

    except Exception:
        raise ValueError(
            f"Invalid timezone: {tz_name}"
        )

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=tz
        )
    else:
        parsed = parsed.astimezone(
            tz
        )

    return parsed.isoformat()


def validate_google_event_time_range(body):
    """Reject complete event ranges whose end is not after their start."""
    start = body.get("start")
    end = body.get("end")

    if not isinstance(start, dict) or not isinstance(end, dict):
        return

    start_datetime = start.get("dateTime")
    end_datetime = end.get("dateTime")

    if start_datetime or end_datetime:
        if not start_datetime or not end_datetime:
            raise ValueError(
                "Start and end must both be timed or all-day"
            )

        start_value = datetime.fromisoformat(
            str(start_datetime).replace("Z", "+00:00")
        )
        end_value = datetime.fromisoformat(
            str(end_datetime).replace("Z", "+00:00")
        )
    else:
        start_date = start.get("date")
        end_date = end.get("date")

        if not start_date or not end_date:
            raise ValueError(
                "Start and end must both be timed or all-day"
            )

        start_value = datetime.strptime(
            str(start_date), "%Y-%m-%d"
        )
        end_value = datetime.strptime(
            str(end_date), "%Y-%m-%d"
        )

    if end_value <= start_value:
        raise ValueError(
            "Event end must be after event start"
        )


def build_google_event_body(
    data,
    partial=False
):
    if not isinstance(data, dict):
        raise ValueError(
            "Invalid event data"
        )

    body = {}

    for key in (
        "summary",
        "description",
        "location"
    ):
        if key in data:
            value = data.get(key)

            if value is None:
                body[key] = None
            else:
                body[key] = str(value).strip()

    tz_name = str(
        data.get(
            "time_zone"
        )
        or app_state_get(
            "time_zone",
            "UTC"
        )
    ).strip()

    all_day = bool(
        data.get(
            "all_day",
            False
        )
    )

    if "recurrence" in data:
        recurrence = data.get(
            "recurrence"
        )

        if recurrence is None:
            body["recurrence"] = []

        elif isinstance(
            recurrence,
            list
        ):
            body["recurrence"] = [
                str(rule).strip()
                for rule in recurrence
                if str(rule).strip()
            ]

        else:
            raise ValueError(
                "Recurrence must be a list"
            )

    if all_day:
        if "start_date" in data:
            start_date = str(
                data.get("start_date", "")
            ).strip()

            datetime.strptime(
                start_date,
                "%Y-%m-%d"
            )

            body["start"] = {
                "date": start_date
            }

        if "end_date" in data:
            end_date = str(
                data.get("end_date", "")
            ).strip()

            datetime.strptime(
                end_date,
                "%Y-%m-%d"
            )

            body["end"] = {
                "date": end_date
            }

    else:
        if "start" in data:
            body["start"] = {
                "dateTime":
                    google_calendar_datetime(
                        data.get("start"),
                        tz_name
                    ),
                "timeZone":
                    tz_name
            }

        if "end" in data:
            body["end"] = {
                "dateTime":
                    google_calendar_datetime(
                        data.get("end"),
                        tz_name
                    ),
                "timeZone":
                    tz_name
            }

    if not partial:
        if not str(
            body.get(
                "summary",
                ""
            )
        ).strip():
            raise ValueError(
                "Event title is required"
            )

        if "start" not in body:
            raise ValueError(
                "Event start is required"
            )

        if "end" not in body:
            raise ValueError(
                "Event end is required"
            )

    validate_google_event_time_range(body)

    return body


def clean_google_event(event):
    if not event:
        return None

    return {
        "id":
            event.get("id"),
        "summary":
            event.get(
                "summary",
                "(No title)"
            ),
        "start":
            event.get("start"),
        "end":
            event.get("end"),
        "location":
            event.get("location"),
        "description":
            event.get("description"),
        "status":
            event.get("status"),
        "htmlLink":
            event.get("htmlLink"),
        "recurringEventId":
            event.get(
                "recurringEventId"
            ),
        "originalStartTime":
            event.get(
                "originalStartTime"
            ),
        "recurrence":
            event.get(
                "recurrence"
            ),
    }



# APOLLO CALENDAR RECURRENCE V1

def google_calendar_get_event(
    event_id
):
    if not event_id:
        raise ValueError(
            "Event ID is required"
        )

    return google_calendar_api_request(
        "GET",
        event_id=event_id
    )


def replace_google_event_time(
    existing,
    requested,
    tz_name
):
    """
    For an entire recurring series, preserve the
    parent's original date but replace its wall-clock time.
    """

    existing_dt = (
        existing.get("dateTime")
        if isinstance(existing, dict)
        else None
    )

    if not existing_dt:
        return None

    requested_dt = (
        google_calendar_datetime(
            requested,
            tz_name
        )
    )

    current = datetime.fromisoformat(
        existing_dt.replace(
            "Z",
            "+00:00"
        )
    )

    proposed = datetime.fromisoformat(
        requested_dt.replace(
            "Z",
            "+00:00"
        )
    )

    try:
        tz = ZoneInfo(tz_name)
        current = current.astimezone(tz)
        proposed = proposed.astimezone(tz)
    except Exception:
        pass

    combined = current.replace(
        hour=proposed.hour,
        minute=proposed.minute,
        second=0,
        microsecond=0
    )

    return {
        "dateTime":
            combined.isoformat(),
        "timeZone":
            tz_name
    }


def google_calendar_create_event(data):
    body = build_google_event_body(
        data,
        partial=False
    )

    event = google_calendar_api_request(
        "POST",
        body=body
    )

    return clean_google_event(
        event
    )


def google_calendar_update_event(
    event_id,
    data,
    scope="single",
    series_id=None
):
    if not event_id:
        raise ValueError(
            "Event ID is required"
        )

    if scope == "series":

        target_id = (
            series_id
            or event_id
        )

        parent = (
            google_calendar_get_event(
                target_id
            )
        )

        tz_name = str(
            data.get("time_zone")
            or app_state_get(
                "time_zone",
                "UTC"
            )
        ).strip()

        body = {}

        for key in (
            "summary",
            "description",
            "location",
            "recurrence"
        ):
            if key in data:
                body[key] = data[key]

        if "start" in data:
            updated_start = (
                replace_google_event_time(
                    parent.get(
                        "start",
                        {}
                    ),
                    data.get("start"),
                    tz_name
                )
            )

            if updated_start:
                body["start"] = (
                    updated_start
                )

        if "end" in data:
            updated_end = (
                replace_google_event_time(
                    parent.get(
                        "end",
                        {}
                    ),
                    data.get("end"),
                    tz_name
                )
            )

            if updated_end:
                body["end"] = (
                    updated_end
                )

    else:

        target_id = event_id

        body = build_google_event_body(
            data,
            partial=True
        )

    if not body:
        raise ValueError(
            "No event changes provided"
        )

    if (
        "start" in body
        and "end" not in body
    ) or (
        "end" in body
        and "start" not in body
    ):
        existing = (
            parent
            if scope == "series"
            else google_calendar_get_event(
                target_id
            )
        )

        validate_google_event_time_range({
            "start": body.get(
                "start",
                existing.get("start")
            ),
            "end": body.get(
                "end",
                existing.get("end")
            )
        })
    else:
        validate_google_event_time_range(body)

    event = google_calendar_api_request(
        "PATCH",
        event_id=target_id,
        body=body
    )

    return clean_google_event(
        event
    )


def google_calendar_delete_event(
    event_id,
    scope="single",
    series_id=None
):
    if not event_id:
        raise ValueError(
            "Event ID is required"
        )

    target_id = (
        series_id
        if (
            scope == "series"
            and series_id
        )
        else event_id
    )

    google_calendar_api_request(
        "DELETE",
        event_id=target_id
    )

    return True





# =========================================================
# APOLLO ATTACHMENT CALENDAR V1
# =========================================================

def apollo_extract_calendar_events_from_attachments(
    user_message,
    attachments,
    client_context=None
):
    """
    Read image attachments with Hermes vision and convert an
    explicit calendar-create request into one or more events.

    Returns:
        {
            "calendar_request": bool,
            "events": [...],
            "reply": str | None
        }
    """

    if not attachments:
        return {
            "calendar_request": False,
            "events": [],
            "reply": None
        }

    local_time, time_zone = (
        calendar_context_now(
            client_context or {}
        )
    )

    try:
        default_duration_minutes = int(
            (client_context or {}).get(
                "calendar_duration_minutes",
                60
            )
            or 60
        )
    except Exception:
        default_duration_minutes = 60

    default_duration_minutes = max(
        5,
        min(
            default_duration_minutes,
            1440
        )
    )

    attachment_lines = []

    for attachment in attachments:

        filename = str(
            attachment["filename"]
            or "attachment"
        )

        mime_type = str(
            attachment["mime_type"]
            or ""
        )

        file_path = str(
            attachment["file_path"]
            or ""
        )

        if not file_path:
            continue

        attachment_lines.append(
            "- "
            + filename
            + " | "
            + mime_type
            + " | local path: "
            + file_path
        )

    if not attachment_lines:
        return {
            "calendar_request": False,
            "events": [],
            "reply": None
        }

    system_prompt = """
You are Apollo's attachment-to-calendar interpreter.

You are given:
1. the user's request
2. the user's current device date/time and timezone
3. one or more attached images/files

The images are actually available to you. READ THEM.

Your job is to decide whether the user is explicitly asking to CREATE
Google Calendar events from the attachments.

Return VALID JSON ONLY. No markdown.

Schema:

{
  "calendar_request": true,
  "events": [
    {
      "summary": "Event title",
      "start": "YYYY-MM-DDTHH:MM",
      "end": "YYYY-MM-DDTHH:MM",
      "time_zone": "IANA timezone",
      "location": "",
      "description": "",
      "recurrence": []
    }
  ],
  "reply": null
}

If this is NOT a request to create calendar events:

{
  "calendar_request": false,
  "events": [],
  "reply": null
}

If it IS a calendar-create request but the attachments do not provide
enough information to create the event safely:

{
  "calendar_request": true,
  "events": [],
  "reply": "Concise question asking only for the missing information."
}

RULES:

1. Never invent a date, time, route, flight number, seat number,
   reservation number, address, or other specific detail.

2. Read ALL attached images. Information for one event may be split
   across multiple screenshots.

3. If the user asks to create multiple events, return ALL of them in
   the events array. Do not collapse two flights into one event.

4. For airline flights:
   - create one event per flight
   - event start = scheduled departure date/time
   - event end = scheduled arrival date/time
   - summary should be useful and concise, preferably:
     "Flight <number> · <origin> → <destination>"
     when those details are visible
   - location should contain the route/airports when available
   - description should contain useful booking details shown in the
     attachment
   - if a seat number is shown, include it exactly as:
     "Seat: <seat>"
   - if the user specifically asks for the seat number in the
     description, this is REQUIRED for every flight where a seat
     number is visible

5. Preserve airport codes exactly when visible.

6. Preserve flight numbers exactly when visible.

7. Use the date shown in the attachment, including the year.

8. Do not substitute today's date for a flight date.

9. Use an appropriate IANA timezone if it is clear from the event
   location. If the event timezone cannot safely be determined, use
   the supplied user device timezone.

10. Overnight flights may have an end date later than the start date.

11. Do not create an event if its required date or start time cannot
    be read confidently.

12. If two screenshots belong to the same flight, combine their
    information. If they show two distinct flights, create two events.

13. Only CREATE requests belong here. Calendar queries, updates,
    deletes, and unrelated attachment questions must return
    calendar_request=false.
"""

    user_prompt = (
        "CURRENT DEVICE CONTEXT\n"
        "Local date/time: "
        + str(local_time)
        + "\nTimezone: "
        + str(time_zone)
        + "\nDEFAULT_EVENT_DURATION_MINUTES: "
        + str(default_duration_minutes)
        + "\n\nUSER REQUEST\n"
        + str(user_message or "")
        + "\n\nATTACHMENTS\n"
        + "\n".join(
            attachment_lines
        )
    )

    raw = ask_hermes([
        {
            "role": "system",
            "content": system_prompt
        },
        {
            "role": "user",
            "content": user_prompt
        }
    ])

    result = calendar_clean_json(
        raw
    )

    if not isinstance(
        result,
        dict
    ):
        raise ValueError(
            "Attachment calendar interpreter "
            "did not return an object"
        )

    calendar_request = bool(
        result.get(
            "calendar_request",
            False
        )
    )

    raw_events = result.get(
        "events",
        []
    )

    if not isinstance(
        raw_events,
        list
    ):
        raw_events = []

    clean_events = []

    for event in raw_events:

        if not isinstance(
            event,
            dict
        ):
            continue

        summary = str(
            event.get(
                "summary",
                ""
            )
            or ""
        ).strip()

        start = str(
            event.get(
                "start",
                ""
            )
            or ""
        ).strip()

        end = str(
            event.get(
                "end",
                ""
            )
            or ""
        ).strip()

        if not summary or not start:
            continue

        if not end:
            try:
                start_dt = datetime.fromisoformat(
                    start.replace(
                        "Z",
                        "+00:00"
                    )
                )

                end_dt = (
                    start_dt
                    + timedelta(
                        minutes=
                            default_duration_minutes
                    )
                )

                end = end_dt.isoformat(
                    timespec="minutes"
                )

            except Exception:
                continue

        event_time_zone = str(
            event.get(
                "time_zone",
                ""
            )
            or time_zone
            or "UTC"
        ).strip()

        clean_events.append({
            "summary":
                summary,

            "start":
                start,

            "end":
                end,

            "time_zone":
                event_time_zone,

            "location":
                str(
                    event.get(
                        "location",
                        ""
                    )
                    or ""
                ).strip(),

            "description":
                str(
                    event.get(
                        "description",
                        ""
                    )
                    or ""
                ).strip(),

            "recurrence":
                event.get(
                    "recurrence",
                    []
                )
                if isinstance(
                    event.get(
                        "recurrence",
                        []
                    ),
                    list
                )
                else []
        })

    return {
        "calendar_request":
            calendar_request,

        "events":
            clean_events,

        "reply":
            (
                str(
                    result.get(
                        "reply",
                        ""
                    )
                    or ""
                ).strip()
                or None
            )
    }


def apollo_attachment_calendar_reply(
    created_events,
    extracted_events
):
    if len(created_events) == 1:

        event = extracted_events[0]

        reply = (
            "Added "
            + event["summary"]
            + " to your calendar."
        )

        description = (
            event.get(
                "description",
                ""
            )
            or ""
        )

        seat_line = None

        for line in description.splitlines():

            if (
                line.strip()
                .lower()
                .startswith("seat:")
            ):
                seat_line = (
                    line.strip()
                )
                break

        if seat_line:
            reply += (
                " "
                + seat_line
                + "."
            )

        return reply

    lines = [
        (
            "Added "
            + str(
                len(created_events)
            )
            + " events to your calendar:"
        )
    ]

    for event in extracted_events:

        line = (
            "• "
            + event["summary"]
        )

        description = (
            event.get(
                "description",
                ""
            )
            or ""
        )

        seat_line = None

        for desc_line in description.splitlines():

            if (
                desc_line.strip()
                .lower()
                .startswith("seat:")
            ):
                seat_line = (
                    desc_line.strip()
                )
                break

        if seat_line:
            line += (
                " — "
                + seat_line
            )

        lines.append(
            line
        )

    return "\n".join(
        lines
    )



# =========================================================
# APOLLO CALENDAR CHAT V1
# =========================================================


# =========================================================
# APOLLO CALENDAR CONTEXT V2
# =========================================================

def calendar_last_event_table():
    conn = db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS calendar_last_events (
            chat_id INTEGER PRIMARY KEY,
            data TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def calendar_last_event_get(chat_id):
    calendar_last_event_table()

    conn = db()

    row = conn.execute("""
        SELECT data
        FROM calendar_last_events
        WHERE chat_id = ?
    """, (chat_id,)).fetchone()

    conn.close()

    if not row:
        return None

    try:
        return json.loads(
            row["data"]
        )
    except Exception:
        return None


def calendar_last_event_set(
    chat_id,
    event
):
    if not event:
        return

    calendar_last_event_table()

    conn = db()

    conn.execute("""
        INSERT INTO calendar_last_events (
            chat_id,
            data,
            updated_at
        )
        VALUES (?, ?, CURRENT_TIMESTAMP)

        ON CONFLICT(chat_id)
        DO UPDATE SET
            data = excluded.data,
            updated_at = CURRENT_TIMESTAMP
    """, (
        chat_id,
        json.dumps(
            event,
            ensure_ascii=False
        )
    ))

    conn.commit()
    conn.close()


def calendar_last_event_clear(chat_id):
    calendar_last_event_table()

    conn = db()

    conn.execute("""
        DELETE FROM calendar_last_events
        WHERE chat_id = ?
    """, (chat_id,))

    conn.commit()
    conn.close()


def calendar_pending_table():
    conn = db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS calendar_pending_actions (
            chat_id INTEGER PRIMARY KEY,
            data TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def calendar_pending_get(chat_id):
    calendar_pending_table()

    conn = db()

    row = conn.execute("""
        SELECT data
        FROM calendar_pending_actions
        WHERE chat_id = ?
    """, (chat_id,)).fetchone()

    conn.close()

    if not row:
        return None

    try:
        return json.loads(
            row["data"]
        )
    except Exception:
        return None


def calendar_pending_set(
    chat_id,
    value
):
    calendar_pending_table()

    conn = db()

    conn.execute("""
        INSERT INTO calendar_pending_actions (
            chat_id,
            data,
            updated_at
        )
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(chat_id)
        DO UPDATE SET
            data = excluded.data,
            updated_at = CURRENT_TIMESTAMP
    """, (
        chat_id,
        json.dumps(
            value,
            ensure_ascii=False
        )
    ))

    conn.commit()
    conn.close()


def calendar_pending_clear(chat_id):
    calendar_pending_table()

    conn = db()

    conn.execute("""
        DELETE FROM calendar_pending_actions
        WHERE chat_id = ?
    """, (chat_id,))

    conn.commit()
    conn.close()


def calendar_clean_json(text):
    value = str(
        text or ""
    ).strip()

    if value.startswith("```"):
        lines = value.splitlines()

        if lines:
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        value = "\n".join(
            lines
        ).strip()

    return json.loads(value)


def calendar_yes(text):
    value = (
        str(text or "")
        .strip()
        .lower()
    )

    return value in {
        "yes",
        "y",
        "yeah",
        "yep",
        "yup",
        "sure",
        "ok",
        "okay",
        "confirm",
        "confirmed",
        "do it",
        "go ahead",
        "please do",
        "yes do it",
    }


def calendar_no(text):
    value = (
        str(text or "")
        .strip()
        .lower()
    )

    return value in {
        "no",
        "n",
        "nope",
        "cancel",
        "stop",
        "nevermind",
        "never mind",
        "don't",
        "dont",
    }


def calendar_scope_answer(text):
    value = (
        str(text or "")
        .strip()
        .lower()
    )

    single_words = (
        "this event",
        "this one",
        "just this",
        "only this",
        "single",
        "one event",
    )

    series_words = (
        "all",
        "all events",
        "every event",
        "whole series",
        "entire series",
        "series",
        "all of them",
    )

    if any(
        phrase in value
        for phrase in single_words
    ):
        return "single"

    if any(
        phrase in value
        for phrase in series_words
    ):
        return "series"

    return None


def calendar_maybe_related(
    text,
    has_calendar_context=False
):
    value = (
        " "
        + str(text or "")
        .strip()
        .lower()
        + " "
    )

    direct = (
        " calendar ",
        " schedule ",
        " event ",
        " appointment ",
        " what do i have ",
        " what have i got ",
        " am i free ",
        " when am i free ",
        " what's on my ",
        " whats on my ",
    )

    if any(
        term in value
        for term in direct
    ):
        return True

    verbs = (
        " add ",
        " schedule ",
        " create ",
        " put ",
        " move ",
        " reschedule ",
        " change ",
        " delete ",
        " remove ",
        " cancel ",
    )

    time_terms = (
        " today",
        " tomorrow",
        " monday",
        " tuesday",
        " wednesday",
        " thursday",
        " friday",
        " saturday",
        " sunday",
        " next week",
        " this week",
        " am",
        " pm",
        ":",
    )

    if (
        any(
            verb in value
            for verb in verbs
        )
        and
        any(
            term in value
            for term in time_terms
        )
    ):
        return True

    if has_calendar_context:

        # A real calendar event was just created or edited in this chat.
        # Let the semantic calendar interpreter resolve natural follow-ups
        # instead of requiring literal pronouns like "it" or "that".
        #
        # Examples:
        #   change the name to Corte de pelo
        #   move it to 5
        #   rename it
        #   make it weekly
        #   update the location
        #
        # This is only a cheap plausibility gate. The AI calendar
        # interpreter still decides whether the message is actually
        # a calendar request.

        context_verbs = (
            " remove ",
            " delete ",
            " cancel ",
            " move ",
            " change ",
            " reschedule ",
            " rename ",
            " make ",
            " undo ",
            " edit ",
            " update ",
        )

        if any(
            verb in value
            for verb in context_verbs
        ):
            return True

    return False


def calendar_context_now(
    client_context
):
    client_context = (
        client_context
        if isinstance(
            client_context,
            dict
        )
        else {}
    )

    time_zone = str(
        client_context.get(
            "time_zone",
            ""
        )
    ).strip()

    if not time_zone:
        try:
            time_zone = app_state_get(
                "time_zone",
                "UTC"
            )
        except Exception:
            time_zone = "UTC"

    local_time = str(
        client_context.get(
            "local_time",
            ""
        )
    ).strip()

    return (
        local_time,
        time_zone
    )


def calendar_chat_events(
    time_zone
):
    try:
        tz = ZoneInfo(
            time_zone
        )

        today = datetime.now(
            tz
        ).date().isoformat()

    except Exception:
        today = datetime.now(
            timezone.utc
        ).date().isoformat()

    try:
        events = google_calendar_events(
            days=90,
            start_date=today
        )
    except Exception as error:
        print(
            "[Apollo Calendar Chat] "
            f"Event lookup failed: {error}"
        )
        return []

    compact = []

    for event in events:
        compact.append({
            "id":
                event.get("id"),
            "summary":
                event.get("summary"),
            "start":
                event.get("start"),
            "end":
                event.get("end"),
            "location":
                event.get("location"),
            "recurringEventId":
                event.get(
                    "recurringEventId"
                ),
            "recurrence":
                event.get(
                    "recurrence"
                ),
        })

    return compact


def calendar_interpret_message(
    user_message,
    client_context,
    last_calendar_event=None
):
    local_time, time_zone = (
        calendar_context_now(
            client_context
        )
    )

    try:
        default_duration_minutes = int(
            (client_context or {}).get(
                "calendar_duration_minutes",
                60
            )
            or 60
        )
    except Exception:
        default_duration_minutes = 60

    default_duration_minutes = max(
        5,
        min(
            default_duration_minutes,
            1440
        )
    )

    events = calendar_chat_events(
        time_zone
    )

    prompt = [
        {
            "role": "system",
            "content": """
You are the Calendar command interpreter for Apollo.

Your job is ONLY to determine whether the user's message is a Google Calendar request and, if so, convert it into safe structured JSON.

The user's current device date/time and timezone are authoritative.

You receive a list of REAL upcoming Google Calendar events. For update/delete requests, you MUST use an event ID from that list. NEVER invent an event ID.

Return VALID JSON ONLY. No markdown.

Schema:

{
  "intent": "none|query|create|update|delete|clarify",
  "reply": null,
  "confirmation": null,
  "action": null
}

For a QUERY:
{
  "intent": "query",
  "reply": "Natural concise answer based ONLY on supplied calendar events.",
  "confirmation": null,
  "action": null
}

For CREATE:
{
  "intent": "create",
  "reply": null,
  "confirmation": "Add “Title” on Wednesday from 6:30–7:30 PM?",
  "action": {
    "summary": "Title",
    "start": "YYYY-MM-DDTHH:MM",
    "end": "YYYY-MM-DDTHH:MM",
    "location": "",
    "description": "",
    "recurrence": []
  }
}

For UPDATE:
{
  "intent": "update",
  "reply": null,
  "confirmation": "Move “Guitarra” on Tuesday to 6:00–7:00 PM?",
  "action": {
    "event_id": "REAL EVENT ID",
    "series_id": null,
    "scope": null,
    "summary": null,
    "start": null,
    "end": null,
    "location": null,
    "description": null,
    "recurrence": null
  }
}

For DELETE:
{
  "intent": "delete",
  "reply": null,
  "confirmation": "Delete “Gym” on Thursday at 6:30 PM?",
  "action": {
    "event_id": "REAL EVENT ID",
    "series_id": null,
    "scope": null,
    "summary": "Gym"
  }
}

Rules:

1. If it is not a Calendar request, intent = "none".

2. For create/update/delete, NEVER execute anything. Only describe the requested action.

3. Resolve relative dates like today, tomorrow, next Wednesday using the supplied current device date/time.

4. If the user gives a start time but no duration/end time, use the supplied default_event_duration_minutes. Do NOT ask the user for an end time when this default is available.

5. For repeating events, recurrence must use Google RRULE strings, e.g.
   ["RRULE:FREQ=WEEKLY;BYDAY=MO,WE"].

6. If the user wants to update/delete an occurrence whose supplied event has recurringEventId:
   - if they explicitly said this occurrence/just this one, scope = "single"
   - if they explicitly said all/every/the series, scope = "series" and series_id = recurringEventId
   - otherwise scope = null and series_id = recurringEventId

7. If multiple supplied events plausibly match an update/delete request, do NOT guess. Return:
{
  "intent": "clarify",
  "reply": "Which Gym event do you mean — Tuesday or Thursday?",
  "confirmation": null,
  "action": null
}

8. If no supplied event matches an update/delete request, return clarify instead of inventing one.

9. For query answers, only state events actually present in the supplied data.

10. Keep confirmation/reply concise and natural.

11. You may receive last_calendar_event. This is the REAL Google Calendar
event most recently created or edited by Apollo in this chat.

If the user says things like:
- "remove it"
- "delete that"
- "move it to 5"
- "change that to 6"
- "make it weekly"
- "rename it"

and the reference reasonably points to last_calendar_event, use that real
event as the target. Do not claim the event was not created if
last_calendar_event says it exists.

12. Never infer Google Calendar state merely from assistant conversation
text. The supplied event objects are authoritative.
"""
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "current_local_time":
                        local_time,
                    "timezone":
                        time_zone,
                    "default_event_duration_minutes":
                        default_duration_minutes,
                    "message":
                        user_message,
                    "last_calendar_event":
                        last_calendar_event,
                    "upcoming_calendar_events":
                        events
                },
                ensure_ascii=False
            )
        }
    ]

    last_error = None

    for _ in range(2):
        try:
            raw = ask_hermes(
                prompt
            )

            result = calendar_clean_json(
                raw
            )

            if isinstance(
                result,
                dict
            ):
                result["_events"] = events
                return result

        except Exception as error:
            last_error = error

    print(
        "[Apollo Calendar Chat] "
        f"Interpreter failed: {last_error}"
    )

    return {
        "intent": "clarify",
        "reply": (
            "I couldn't safely interpret that "
            "calendar request. Try saying exactly "
            "what you want changed and when."
        ),
        "confirmation": None,
        "action": None,
        "_events": events,
    }


def calendar_find_event(
    events,
    event_id
):
    for event in events:
        if event.get("id") == event_id:
            return event

    return None


# =========================================================
# APOLLO RECURRING CONTEXT FIX V5
# =========================================================

def calendar_prepare_action(
    chat_id,
    interpreted,
    last_calendar_event=None
):
    intent = interpreted.get(
        "intent"
    )

    action = interpreted.get(
        "action"
    )

    if not isinstance(
        action,
        dict
    ):
        return (
            interpreted.get("reply")
            or "I need a little more detail."
        )

    events = interpreted.get(
        "_events",
        []
    )

    if intent in (
        "update",
        "delete"
    ):
        event_id = str(
            action.get(
                "event_id",
                ""
            )
            or ""
        ).strip()

        existing = calendar_find_event(
            events,
            event_id
        )

        # The event Apollo just created/edited may be a recurring
        # parent event. Google's expanded event list contains its
        # occurrences instead of that parent ID, so also trust our
        # stored REAL Google API result.
        if (
            not existing
            and isinstance(
                last_calendar_event,
                dict
            )
            and last_calendar_event.get("id")
                == event_id
        ):
            existing = last_calendar_event

        if not existing:
            return (
                "I couldn't safely match that to a real "
                "calendar event. Which event do you mean?"
            )

        recurring_id = existing.get(
            "recurringEventId"
        )

        parent_recurrence = existing.get(
            "recurrence"
        )

        # If this is the recurring parent itself, then its own ID
        # is the series ID.
        if (
            not recurring_id
            and parent_recurrence
        ):
            recurring_id = existing.get(
                "id"
            )

            action["series_id"] = recurring_id

            # A reference like "remove it" after Apollo JUST created
            # a recurring series naturally refers to that series,
            # not one arbitrary occurrence.
            if (
                isinstance(
                    last_calendar_event,
                    dict
                )
                and last_calendar_event.get("id")
                    == existing.get("id")
            ):
                action["scope"] = (
                    action.get("scope")
                    or "series"
                )

        if recurring_id:
            action["series_id"] = (
                action.get(
                    "series_id"
                )
                or recurring_id
            )

            scope = action.get(
                "scope"
            )

            if scope not in (
                "single",
                "series"
            ):
                calendar_pending_set(
                    chat_id,
                    {
                        "stage": "scope",
                        "intent": intent,
                        "action": action,
                        "confirmation":
                            interpreted.get(
                                "confirmation"
                            ),
                    }
                )

                return (
                    "This is part of a repeating event. "
                    "Do you want to change just this event "
                    "or all events in the series?"
                )

        else:
            action["scope"] = "single"

    # Deletes remain destructive and always require confirmation.
    if intent == "delete":

        calendar_pending_set(
            chat_id,
            {
                "stage": "confirm",
                "intent": intent,
                "action": action,
                "confirmation":
                    interpreted.get(
                        "confirmation"
                    ),
            }
        )

        return (
            interpreted.get(
                "confirmation"
            )
            or "Do you want me to delete that event?"
        )


    # Creates and fully specified updates should happen immediately.
    if intent in (
        "create",
        "update"
    ):

        try:

            return calendar_execute_pending(
                {
                    "intent": intent,
                    "action": action
                },
                chat_id=chat_id
            )

        except Exception as error:

            print(
                "[Apollo Calendar Chat] "
                f"Immediate execution failed: {error}"
            )

            return (
                "I couldn't complete that calendar "
                "change, so I didn't apply it."
            )


    return (
        interpreted.get("reply")
        or "I need a little more detail."
    )


def calendar_execute_pending(
    pending,
    chat_id=None
):
    intent = pending.get(
        "intent"
    )

    action = dict(
        pending.get(
            "action",
            {}
        )
    )

    if intent == "create":
        event = google_calendar_create_event(
            action
        )

        if chat_id is not None:
            calendar_last_event_set(
                chat_id,
                event
            )

        title = (
            event.get("summary")
            if event
            else action.get("summary")
        )

        return (
            f'Done — added “{title}” '
            "to your calendar."
        )

    if intent == "update":
        event_id = action.pop(
            "event_id",
            ""
        )

        scope = action.pop(
            "scope",
            "single"
        )

        series_id = action.pop(
            "series_id",
            None
        )

        # Remove fields that mean "unchanged".
        action = {
            key: value
            for key, value in action.items()
            if value is not None
        }

        event = google_calendar_update_event(
            event_id,
            action,
            scope=scope,
            series_id=series_id
        )

        if chat_id is not None:
            calendar_last_event_set(
                chat_id,
                event
            )

        title = (
            event.get("summary")
            if event
            else "event"
        )

        if scope == "series":
            return (
                f'Done — updated all “{title}” '
                "events in the series."
            )

        return (
            f'Done — updated “{title}”.'
        )

    if intent == "delete":
        event_id = action.get(
            "event_id",
            ""
        )

        scope = action.get(
            "scope",
            "single"
        )

        series_id = action.get(
            "series_id"
        )

        title = (
            action.get("summary")
            or "event"
        )

        google_calendar_delete_event(
            event_id,
            scope=scope,
            series_id=series_id
        )

        if chat_id is not None:
            calendar_last_event_clear(
                chat_id
            )

        if scope == "series":
            return (
                f'Done — deleted all “{title}” '
                "events in the series."
            )

        return (
            f'Done — deleted “{title}”.'
        )

    raise RuntimeError(
        "Unknown pending calendar action"
    )



# =========================================================
# APOLLO AI CONFIRMATIONS V4
# =========================================================

def calendar_interpret_pending_reply(
    user_message,
    pending
):
    prompt = [
        {
            "role": "system",
            "content": """
You interpret a user's reply to a pending Google Calendar action.

Understand natural conversational language. Do NOT require exact words like yes or no.

Return VALID JSON ONLY:

{
  "decision": "confirm|cancel|single|series|unclear",
  "reply": null
}

Meanings:

confirm:
The user clearly agrees to perform the pending action.
Examples:
- yeah sure
- yep go ahead
- sounds good
- do it bro
- alright
- that's fine
- why not
- yeah

cancel:
The user clearly does NOT want the pending action.
Examples:
- nah
- nvm
- never mind
- don't do it
- actually leave it
- cancel that
- no thanks

single:
For a repeating event, the user means only this occurrence.
Examples:
- just this one
- only that event
- this occurrence

series:
For a repeating event, the user means the entire repeating series.
Examples:
- all of them
- every one
- the whole series
- all events

unclear:
The reply does not clearly answer the pending question, or asks something else.

Important:
- Interpret intent semantically, not by exact phrase matching.
- Casual wording, slang, filler, and politeness should not matter.
- Never choose confirm if the user sounds uncertain.
- If decision is unclear, set reply to a brief natural question asking what they want.
"""
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "pending_action": pending,
                    "user_reply": user_message
                },
                ensure_ascii=False
            )
        }
    ]

    try:
        raw = ask_hermes(prompt)
        result = calendar_clean_json(raw)

        if not isinstance(result, dict):
            raise ValueError(
                "Invalid confirmation result"
            )

        decision = result.get(
            "decision",
            "unclear"
        )

        if decision not in (
            "confirm",
            "cancel",
            "single",
            "series",
            "unclear"
        ):
            decision = "unclear"

        return {
            "decision": decision,
            "reply": result.get("reply")
        }

    except Exception as error:
        print(
            "[Apollo Calendar Chat] "
            f"Confirmation interpretation failed: {error}"
        )

        return {
            "decision": "unclear",
            "reply": (
                "I’m not completely sure what you want me "
                "to do with that calendar change."
            )
        }


def calendar_handle_pending(
    chat_id,
    user_message
):
    pending = calendar_pending_get(
        chat_id
    )

    if not pending:
        return None


    interpreted = (
        calendar_interpret_pending_reply(
            user_message,
            pending
        )
    )

    decision = interpreted.get(
        "decision",
        "unclear"
    )

    stage = pending.get(
        "stage"
    )


    # ─────────────────────────────
    # CANCEL
    # ─────────────────────────────

    if decision == "cancel":

        calendar_pending_clear(
            chat_id
        )

        return (
            "Okay — I left your calendar unchanged."
        )


    # ─────────────────────────────
    # RECURRING EVENT SCOPE
    # ─────────────────────────────

    if stage == "scope":

        if decision not in (
            "single",
            "series"
        ):

            return (
                interpreted.get("reply")
                or (
                    "Do you want me to change just "
                    "this event or the whole series?"
                )
            )


        pending["action"]["scope"] = (
            decision
        )


        # Delete remains destructive even after scope is known.
        if (
            pending.get("intent")
            == "delete"
        ):

            pending["stage"] = "confirm"

            calendar_pending_set(
                chat_id,
                pending
            )


            if decision == "single":

                return (
                    pending.get(
                        "confirmation"
                    )
                    or (
                        "Delete just this occurrence?"
                    )
                )


            return (
                pending.get(
                    "confirmation"
                )
                or (
                    "Delete the whole repeating series?"
                )
            )


        # For updates, choosing the recurring scope supplied
        # the final missing piece of information, so execute now.
        try:

            response = (
                calendar_execute_pending(
                    pending,
                    chat_id=chat_id
                )
            )

            calendar_pending_clear(
                chat_id
            )

            return response

        except Exception as error:

            calendar_pending_clear(
                chat_id
            )

            print(
                "[Apollo Calendar Chat] "
                f"Recurring execution failed: {error}"
            )

            return (
                "I couldn't complete that calendar "
                "change, so I didn't apply it."
            )


    # ─────────────────────────────
    # FINAL CONFIRMATION
    # ─────────────────────────────

    if stage == "confirm":

        if decision == "confirm":

            try:

                response = (
                    calendar_execute_pending(
                        pending,
                        chat_id=chat_id
                    )
                )

                calendar_pending_clear(
                    chat_id
                )

                return response

            except Exception as error:

                calendar_pending_clear(
                    chat_id
                )

                print(
                    "[Apollo Calendar Chat] "
                    f"Execution failed: {error}"
                )

                return (
                    "I couldn't complete that calendar "
                    "change, so I didn't apply anything else."
                )


        if decision == "cancel":

            calendar_pending_clear(
                chat_id
            )

            return (
                "Okay — I left your calendar unchanged."
            )


        return (
            interpreted.get("reply")
            or (
                "I’m not sure whether you want me "
                "to go ahead with that."
            )
        )


    calendar_pending_clear(
        chat_id
    )

    return None



def apollo_save_assistant_message(
    chat_id,
    assistant_message
):
    conn = db()

    conn.execute("""
        INSERT INTO messages (
            chat_id,
            role,
            content
        )
        VALUES (?, 'assistant', ?)
    """, (
        chat_id,
        assistant_message
    ))

    conn.execute("""
        UPDATE chats
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (chat_id,))

    history_rows = conn.execute("""
        SELECT role, content
        FROM messages
        WHERE chat_id = ?
        ORDER BY id ASC
    """, (chat_id,)).fetchall()

    history = [
        {
            "role":
                row["role"],
            "content":
                row["content"]
        }
        for row in history_rows
    ]

    if len(history) == 2:
        title = generate_chat_title(
            history
        )

        conn.execute("""
            UPDATE chats
            SET title = ?
            WHERE id = ?
        """, (
            title,
            chat_id
        ))

    conn.commit()
    conn.close()


def apollo_open_sse(
    handler
):
    handler.send_response(200)

    handler.send_header(
        "Content-Type",
        "text/event-stream; charset=utf-8"
    )

    handler.send_header(
        "Cache-Control",
        "no-cache, no-store"
    )

    handler.send_header(
        "Connection",
        "close"
    )

    handler.end_headers()


def apollo_finish_direct_sse(
    handler,
    chat_id,
    assistant_message
):
    content_event = json.dumps({
        "type": "content",
        "content":
            assistant_message
    })

    handler.wfile.write(
        f"data: {content_event}\n\n"
        .encode("utf-8")
    )

    handler.wfile.flush()

    apollo_save_assistant_message(
        chat_id,
        assistant_message
    )

    done_event = json.dumps({
        "type": "done",
        "message": {
            "role": "assistant",
            "content":
                assistant_message
        }
    })

    handler.wfile.write(
        f"data: {done_event}\n\n"
        .encode("utf-8")
    )

    handler.wfile.flush()


def apollo_send_status_sse(
    handler,
    status
):
    """
    Send a short live Apollo activity status through
    an SSE response that has already been opened.
    """

    event = json.dumps({
        "type": "status",
        "status": str(status or "").strip()
    })

    handler.wfile.write(
        f"data: {event}\n\n".encode("utf-8")
    )

    handler.wfile.flush()


def apollo_send_direct_sse(
    handler,
    chat_id,
    assistant_message
):
    apollo_open_sse(
        handler
    )

    apollo_finish_direct_sse(
        handler,
        chat_id,
        assistant_message
    )



def apollo_calendar_chat(
    chat_id,
    user_message,
    client_context
):
    last_calendar_event = (
        calendar_last_event_get(
            chat_id
        )
    )


    # =====================================================
    # CALENDAR CLARIFICATION MEMORY
    # =====================================================
    #
    # Example:
    #
    # User: add goon sesh tomorrow
    # Apollo: what time?
    # User: 4:27 am
    #
    # The second message must be interpreted together with
    # the unfinished original request.

    pending = calendar_pending_get(
        chat_id
    )


    if (
        isinstance(pending, dict)
        and pending.get("stage") == "clarify"
    ):

        original_message = str(
            pending.get(
                "original_message",
                ""
            )
        ).strip()


        combined_message = (
            original_message
            + "\n\n"
            + "USER FOLLOW-UP TO THE MISSING INFORMATION:\n"
            + str(user_message).strip()
        )


        interpreted = calendar_interpret_message(
            combined_message,
            client_context,
            last_calendar_event=
                last_calendar_event
        )


        intent = interpreted.get(
            "intent",
            "none"
        )


        # Still missing something.
        if intent == "clarify":

            calendar_pending_set(
                chat_id,
                {
                    "stage": "clarify",
                    "original_message":
                        combined_message
                }
            )

            return (
                interpreted.get("reply")
                or "I still need one more detail."
            )


        # The follow-up supplied enough information.
        if intent in (
            "create",
            "update",
            "delete"
        ):

            calendar_pending_clear(
                chat_id
            )

            return calendar_prepare_action(
                chat_id,
                interpreted,
                last_calendar_event=
                    last_calendar_event
            )


        # A direct calendar query can also resolve naturally.
        if intent == "query":

            calendar_pending_clear(
                chat_id
            )

            return (
                interpreted.get("reply")
                or "I couldn't find anything for that."
            )


        # The user changed subjects instead of answering.
        calendar_pending_clear(
            chat_id
        )


    # =====================================================
    # EXISTING CONFIRMATION / RECURRING-SCOPE STATE
    # =====================================================

    pending_reply = calendar_handle_pending(
        chat_id,
        user_message
    )

    if pending_reply is not None:
        return pending_reply


    # Avoid slowing every normal Apollo message.
    # Inside Calendar, however, the surface itself is context.
    surface = (
        str(
            client_context.get(
                "surface",
                ""
            )
        ).strip().lower()
        if isinstance(
            client_context,
            dict
        )
        else ""
    )


    if (
        surface != "calendar"
        and not calendar_maybe_related(
            user_message,
            has_calendar_context=bool(
                last_calendar_event
            )
        )
    ):
        return None


    interpreted = calendar_interpret_message(
        user_message,
        client_context,
        last_calendar_event=
            last_calendar_event
    )


    intent = interpreted.get(
        "intent",
        "none"
    )


    if intent == "none":
        return None


    if intent == "query":

        return (
            interpreted.get("reply")
            or "I couldn't find anything for that."
        )


    # =====================================================
    # SAVE UNFINISHED CALENDAR REQUEST
    # =====================================================

    if intent == "clarify":

        calendar_pending_set(
            chat_id,
            {
                "stage": "clarify",
                "original_message":
                    user_message
            }
        )

        return (
            interpreted.get("reply")
            or "I need a little more detail."
        )


    if intent in (
        "create",
        "update",
        "delete"
    ):

        return calendar_prepare_action(
            chat_id,
            interpreted,
            last_calendar_event=
                last_calendar_event
        )


    return None



# =========================================================
# APOLLO TASKS V1
# =========================================================

def task_dict(row):

    task = dict(row)

    task["completed"] = bool(
        task.get("completed")
    )

    return task


def get_tasks():

    conn = db()

    rows = conn.execute("""
        SELECT
            id,
            title,
            due_at,
            completed,
            completed_at,
            created_at,
            updated_at
        FROM tasks
        ORDER BY
            completed ASC,
            CASE
                WHEN due_at IS NULL
                OR due_at = ''
                THEN 1
                ELSE 0
            END ASC,
            due_at ASC,
            created_at DESC,
            id DESC
    """).fetchall()

    conn.close()

    return [
        task_dict(row)
        for row in rows
    ]


def get_task(task_id):

    try:
        task_id = int(
            task_id
        )
    except (
        TypeError,
        ValueError
    ):
        return None

    conn = db()

    row = conn.execute("""
        SELECT *
        FROM tasks
        WHERE id = ?
    """, (
        task_id,
    )).fetchone()

    conn.close()

    return row


def create_task(data):

    title = str(
        data.get(
            "title",
            ""
        )
    ).strip()

    if not title:
        raise ValueError(
            "Task title is required"
        )

    if len(title) > 240:
        raise ValueError(
            "Task title is too long"
        )

    due_at = data.get(
        "due_at"
    )

    if due_at is not None:

        due_at = str(
            due_at
        ).strip()

        if not due_at:
            due_at = None

    if (
        due_at
        and len(due_at) > 40
    ):
        raise ValueError(
            "Invalid due date"
        )

    conn = db()

    cursor = conn.execute("""
        INSERT INTO tasks (
            title,
            due_at
        )
        VALUES (?, ?)
    """, (
        title,
        due_at
    ))

    task_id = cursor.lastrowid

    conn.commit()

    row = conn.execute("""
        SELECT *
        FROM tasks
        WHERE id = ?
    """, (
        task_id,
    )).fetchone()

    conn.close()

    return task_dict(
        row
    )



# =========================================================
# APOLLO ATTACHMENT TASK ACTIONS V1
# =========================================================

def apollo_attachment_task_request(
    user_message
):

    value = str(
        user_message
        or ""
    ).strip().lower()


    if not value:
        return False


    phrases = (
        "add these to my tasks",
        "add these to tasks",
        "add this to my tasks",
        "add this to tasks",
        "make these tasks",
        "make this a task",
        "make tasks from",
        "create tasks from",
        "turn these into tasks",
        "turn this into a task",
        "put these in my tasks",
        "put this in my tasks",
        "save these as tasks",
        "save this as a task",
    )


    return any(
        phrase in value
        for phrase in phrases
    )


def apollo_parse_json_object(
    value
):

    raw = str(
        value
        or ""
    ).strip()


    if not raw:
        return None


    # Hermes may occasionally wrap JSON in markdown fences.
    if raw.startswith("```"):

        lines = raw.splitlines()

        if (
            lines
            and lines[0].startswith("```")
        ):
            lines = lines[1:]


        if (
            lines
            and lines[-1].strip() == "```"
        ):
            lines = lines[:-1]


        raw = "\n".join(
            lines
        ).strip()


    try:
        return json.loads(
            raw
        )

    except Exception:
        pass


    # Conservative fallback: extract the outermost JSON object.
    start = raw.find("{")
    end = raw.rfind("}")


    if (
        start != -1
        and end != -1
        and end > start
    ):

        try:
            return json.loads(
                raw[
                    start:
                    end + 1
                ]
            )

        except Exception:
            pass


    return None


def apollo_extract_tasks_from_attachments(
    user_message,
    attachments,
    client_context
):

    if not attachments:
        return []


    file_lines = []


    for attachment in attachments:

        file_lines.append(
            "- "
            + str(
                attachment["filename"]
            )
            + " | "
            + str(
                attachment["mime_type"]
            )
            + " | local path: "
            + str(
                attachment["file_path"]
            )
        )


    local_time = ""
    time_zone = ""


    if isinstance(
        client_context,
        dict
    ):

        local_time = str(
            client_context.get(
                "local_time",
                ""
            )
        ).strip()

        time_zone = str(
            client_context.get(
                "time_zone",
                ""
            )
        ).strip()


    prompt = (
        "The user wants Apollo to create Tasks from attached files.\n\n"
        "USER REQUEST:\n"
        + str(user_message).strip()
        + "\n\n"
        + "ATTACHED FILES:\n"
        + "\n".join(file_lines)
        + "\n\n"
        + "CURRENT USER TIME CONTEXT:\n"
        + "Local date/time: "
        + local_time
        + "\nTimezone: "
        + time_zone
        + "\n\n"
        + """
Inspect the attached files directly.

Extract ONLY clear actionable tasks, assignments, homework,
deliverables, or deadlines that are actually visible in the files.

Do not create tasks from:
- page headings
- course titles
- explanatory text
- topic names
- decorative text
- things that are not clearly an action the user needs to do

If multiple assignments are visible, return every distinct task.

Use concise task titles that will make sense later in a task list.

For due_at:
- preserve a clearly visible due date/time when present
- resolve relative dates using the supplied current user time
- use YYYY-MM-DD when only a date is known
- use YYYY-MM-DDTHH:MM when a specific time is known
- use null if no deadline is visible
- NEVER invent a deadline

Return STRICT JSON only in exactly this shape:

{
  "tasks": [
    {
      "title": "Example assignment",
      "due_at": "2026-08-14"
    }
  ]
}

If there are no clearly identifiable actionable tasks, return:

{"tasks":[]}
"""
    )


    result = ask_hermes([
        {
            "role": "system",
            "content": (
                "You are Apollo's attachment-to-task extractor. "
                "Inspect local attached files when paths are provided. "
                "Return only the requested JSON."
            )
        },
        {
            "role": "user",
            "content": prompt
        }
    ])


    parsed = apollo_parse_json_object(
        result
    )


    if not isinstance(
        parsed,
        dict
    ):
        return []


    raw_tasks = parsed.get(
        "tasks"
    )


    if not isinstance(
        raw_tasks,
        list
    ):
        return []


    cleaned = []


    for item in raw_tasks:

        if not isinstance(
            item,
            dict
        ):
            continue


        title = str(
            item.get(
                "title",
                ""
            )
            or ""
        ).strip()


        if not title:
            continue


        due_at = item.get(
            "due_at"
        )


        if due_at is not None:

            due_at = str(
                due_at
            ).strip()

            if not due_at:
                due_at = None


        cleaned.append({
            "title":
                title,

            "due_at":
                due_at
        })


    return cleaned


def update_task(data):

    try:
        task_id = int(
            data.get(
                "task_id"
            )
        )
    except (
        TypeError,
        ValueError
    ):
        raise ValueError(
            "Invalid task ID"
        )

    existing = get_task(
        task_id
    )

    if not existing:
        raise ValueError(
            "Task not found"
        )

    title = (
        str(
            data.get(
                "title"
            )
        ).strip()
        if "title" in data
        else existing["title"]
    )

    if not title:
        raise ValueError(
            "Task title is required"
        )

    if len(title) > 240:
        raise ValueError(
            "Task title is too long"
        )

    due_at = existing[
        "due_at"
    ]

    if "due_at" in data:

        raw_due = data.get(
            "due_at"
        )

        if raw_due is None:
            due_at = None
        else:
            due_at = str(
                raw_due
            ).strip() or None

    if (
        due_at
        and len(due_at) > 40
    ):
        raise ValueError(
            "Invalid due date"
        )

    completed = int(
        existing[
            "completed"
        ]
    )

    completed_at = existing[
        "completed_at"
    ]

    if "completed" in data:

        completed = (
            1
            if bool(
                data.get(
                    "completed"
                )
            )
            else 0
        )

        if completed:
            completed_at = (
                datetime.now(
                    timezone.utc
                ).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            )
        else:
            completed_at = None

    conn = db()

    conn.execute("""
        UPDATE tasks
        SET
            title = ?,
            due_at = ?,
            completed = ?,
            completed_at = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        title,
        due_at,
        completed,
        completed_at,
        task_id
    ))

    conn.commit()

    row = conn.execute("""
        SELECT *
        FROM tasks
        WHERE id = ?
    """, (
        task_id,
    )).fetchone()

    conn.close()

    return task_dict(
        row
    )


def delete_task(task_id):

    try:
        task_id = int(
            task_id
        )
    except (
        TypeError,
        ValueError
    ):
        raise ValueError(
            "Invalid task ID"
        )

    existing = get_task(
        task_id
    )

    if not existing:
        raise ValueError(
            "Task not found"
        )

    conn = db()

    conn.execute("""
        DELETE FROM tasks
        WHERE id = ?
    """, (
        task_id,
    ))

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "deleted": task_id
    }



# =========================================================
# APOLLO TASKS CHAT V1
# =========================================================


def task_chat_state_table():

    conn = db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_chat_state (
            chat_id INTEGER PRIMARY KEY,
            last_task_id INTEGER,
            pending_action TEXT,
            pending_data TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def task_chat_state_get(
    chat_id
):

    task_chat_state_table()

    conn = db()

    row = conn.execute("""
        SELECT
            last_task_id,
            pending_action,
            pending_data
        FROM task_chat_state
        WHERE chat_id = ?
    """, (
        chat_id,
    )).fetchone()

    conn.close()

    if not row:

        return {
            "last_task_id": None,
            "pending_action": None,
            "pending_data": None
        }


    pending_data = None

    if row["pending_data"]:

        try:

            pending_data = json.loads(
                row["pending_data"]
            )

        except Exception:

            pending_data = None


    return {
        "last_task_id":
            row["last_task_id"],

        "pending_action":
            row["pending_action"],

        "pending_data":
            pending_data
    }


def task_chat_state_set(
    chat_id,
    *,
    last_task_id=None,
    pending_action=None,
    pending_data=None,
    preserve_last=True
):

    task_chat_state_table()

    existing = task_chat_state_get(
        chat_id
    )

    if (
        preserve_last
        and last_task_id is None
    ):

        last_task_id = (
            existing.get(
                "last_task_id"
            )
        )


    conn = db()

    conn.execute("""
        INSERT INTO task_chat_state (
            chat_id,
            last_task_id,
            pending_action,
            pending_data,
            updated_at
        )
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)

        ON CONFLICT(chat_id)
        DO UPDATE SET
            last_task_id =
                excluded.last_task_id,
            pending_action =
                excluded.pending_action,
            pending_data =
                excluded.pending_data,
            updated_at =
                CURRENT_TIMESTAMP
    """, (
        chat_id,
        last_task_id,
        pending_action,
        (
            json.dumps(
                pending_data,
                ensure_ascii=False
            )
            if pending_data is not None
            else None
        )
    ))

    conn.commit()
    conn.close()


def task_chat_clear_pending(
    chat_id
):

    state = task_chat_state_get(
        chat_id
    )

    task_chat_state_set(
        chat_id,
        last_task_id=
            state.get(
                "last_task_id"
            ),
        pending_action=None,
        pending_data=None,
        preserve_last=False
    )


def task_chat_yes(
    text
):

    value = (
        str(
            text or ""
        )
        .strip()
        .lower()
    )

    return value in {
        "yes",
        "y",
        "yeah",
        "yep",
        "yup",
        "sure",
        "ok",
        "okay",
        "confirm",
        "confirmed",
        "do it",
        "go ahead",
        "please do",
        "yes do it",
        "delete it",
    }


def task_chat_no(
    text
):

    value = (
        str(
            text or ""
        )
        .strip()
        .lower()
    )

    return value in {
        "no",
        "n",
        "nope",
        "cancel",
        "stop",
        "nevermind",
        "never mind",
        "don't",
        "dont",
    }


def task_chat_clean_json(
    text
):

    value = str(
        text or ""
    ).strip()

    if value.startswith(
        "```"
    ):

        lines = (
            value.splitlines()
        )

        if lines:
            lines = lines[1:]

        if (
            lines
            and lines[-1].strip()
            == "```"
        ):
            lines = lines[:-1]

        value = "\n".join(
            lines
        ).strip()


    return json.loads(
        value
    )


def task_chat_maybe_related(
    text,
    has_task_context=False,
    has_pending=False
):

    if has_pending:
        return True


    value = (
        str(
            text or ""
        )
        .strip()
        .lower()
    )


    if not value:
        return False


    phrases = (
        "task",
        "tasks",
        "to do",
        "todo",
        "remind me",
        "homework",
        "assignment",
        "due tomorrow",
        "due today",
        "due friday",
        "mark it complete",
        "mark that complete",
        "mark complete",
        "complete it",
        "finish task",
        "delete it",
        "delete that task",
        "reschedule",
        "move it to",
        "move that to",
        "change the due",
        "rename it",
        "rename that",
    )


    if any(
        phrase in value
        for phrase in phrases
    ):

        return True


    action_starts = (
        "add ",
        "create ",
        "make ",
        "finish ",
        "complete ",
        "delete ",
        "remove ",
        "rename ",
        "move ",
        "change ",
        "reschedule ",
    )


    if (
        has_task_context
        and value.startswith(
            action_starts
        )
    ):

        return True


    if (
        has_task_context
        and value in {
            "done",
            "finished",
            "complete",
            "completed",
            "yes",
            "no",
        }
    ):

        return True


    return False


def task_chat_format_due(
    due_at
):

    if not due_at:
        return ""


    value = str(
        due_at
    )


    if "T" in value:

        date_part, time_part = (
            value.split(
                "T",
                1
            )
        )

        time_part = (
            time_part[:5]
        )

        try:

            hour, minute = (
                map(
                    int,
                    time_part.split(
                        ":"
                    )
                )
            )

            period = (
                "AM"
                if hour < 12
                else "PM"
            )

            display_hour = (
                hour % 12
            ) or 12

            return (
                f"{date_part} at "
                f"{display_hour}:"
                f"{minute:02d} "
                f"{period}"
            )

        except Exception:

            return value


    return value


def task_chat_task_summary(
    task
):

    if not task:
        return "that task"


    title = str(
        task.get(
            "title",
            "Task"
        )
    ).strip()


    due_at = task.get(
        "due_at"
    )


    if due_at:

        return (
            f"{title} — "
            f"{task_chat_format_due(due_at)}"
        )


    return title


def task_chat_find_task(
    task_id=None,
    title_hint=None,
    last_task_id=None
):

    tasks = get_tasks()


    if task_id is not None:

        try:
            task_id = int(
                task_id
            )
        except (
            TypeError,
            ValueError
        ):
            task_id = None


        if task_id is not None:

            for task in tasks:

                if (
                    int(
                        task["id"]
                    )
                    == task_id
                ):

                    return task


    hint = (
        str(
            title_hint or ""
        )
        .strip()
        .lower()
    )


    if hint:

        exact = [
            task
            for task in tasks
            if str(
                task.get(
                    "title",
                    ""
                )
            ).strip().lower()
            == hint
        ]


        if len(
            exact
        ) == 1:

            return exact[0]


        contains = [
            task
            for task in tasks
            if (
                hint
                in str(
                    task.get(
                        "title",
                        ""
                    )
                ).lower()
                or
                str(
                    task.get(
                        "title",
                        ""
                    )
                ).lower()
                in hint
            )
        ]


        if len(
            contains
        ) == 1:

            return contains[0]


    if last_task_id is not None:

        try:

            last_task_id = int(
                last_task_id
            )

            for task in tasks:

                if (
                    int(
                        task["id"]
                    )
                    == last_task_id
                ):

                    return task

        except (
            TypeError,
            ValueError
        ):

            pass


    return None


def task_chat_interpret_message(
    user_message,
    client_context,
    tasks,
    last_task=None
):

    local_time = ""

    time_zone = ""

    utc_offset = None


    if isinstance(
        client_context,
        dict
    ):

        local_time = str(
            client_context.get(
                "local_time",
                ""
            )
        ).strip()

        time_zone = str(
            client_context.get(
                "time_zone",
                ""
            )
        ).strip()

        utc_offset = (
            client_context.get(
                "utc_offset_minutes"
            )
        )


    compact_tasks = []

    for task in tasks[:80]:

        compact_tasks.append({
            "id":
                task.get(
                    "id"
                ),

            "title":
                task.get(
                    "title"
                ),

            "due_at":
                task.get(
                    "due_at"
                ),

            "completed":
                bool(
                    task.get(
                        "completed"
                    )
                )
        })


    prompt = f"""
You are the task-action interpreter inside Apollo.

The user's current device context is authoritative:
Local date/time: {local_time}
Timezone: {time_zone}
UTC offset minutes: {utc_offset}

Existing Apollo tasks:
{json.dumps(compact_tasks, ensure_ascii=False)}

Most recently referenced task:
{json.dumps(last_task, ensure_ascii=False)}

User message:
{user_message}

Determine whether this message is asking Apollo to work with TASKS.

Return ONLY valid JSON. No markdown.

Allowed intents:
- "none"
- "create"
- "query"
- "complete"
- "reopen"
- "update"
- "delete"
- "clarify"

Schema:
{{
  "intent": "none|create|query|complete|reopen|update|delete|clarify",
  "task_id": integer or null,
  "title": string or null,
  "title_hint": string or null,
  "new_title": string or null,
  "due_at": string or null,
  "due_at_present": true or false,
  "query_scope": "all|today|tomorrow|upcoming|completed" or null,
  "reply": string or null
}}

Rules:

1. For create:
   - "title" is the task itself without filler such as
     "remind me to", "add a task to", etc.
   - Resolve relative dates using the CURRENT DEVICE CONTEXT.
   - due_at format:
       YYYY-MM-DD
       or YYYY-MM-DDTHH:MM
   - If the user gives a date but no time, do NOT invent a time.
   - If no date is given, due_at must be null.

2. For update:
   - Use task_id when you can confidently match an existing task.
   - Use title_hint if the user refers to a task by name.
   - new_title only when renaming.
   - Set due_at_present=true only when the user is actually
     changing/removing the due date.
   - If the user says remove the due date, set
     due_at_present=true and due_at=null.

3. For complete/reopen/delete:
   - Match an existing task when possible.
   - Prefer the most recently referenced task when the user says
     "it", "that", "this task", etc.
   - Never fabricate a task ID.

4. For query:
   - Use today/tomorrow/upcoming/completed when obvious.
   - Otherwise use all.

5. If the user is asking about CALENDAR EVENTS rather than Tasks,
   return intent "none".

6. If it is ordinary conversation unrelated to tasks,
   return intent "none".

7. If task intent is clear but the target task cannot be identified,
   use "clarify" with a short natural question.

8. Do not claim an action succeeded. This interpreter does not execute it.
""".strip()


    messages = [
        {
            "role":
                "system",

            "content":
                (
                    "Return only valid JSON for "
                    "Apollo's task interpreter."
                )
        },
        {
            "role":
                "user",

            "content":
                prompt
        }
    ]


    result = ask_hermes(
        messages
    )


    try:

        parsed = (
            task_chat_clean_json(
                result
            )
        )

    except Exception as error:

        print(
            "[Apollo Tasks Chat] "
            f"Interpreter JSON failed: {error}"
        )

        return {
            "intent": "none"
        }


    if not isinstance(
        parsed,
        dict
    ):

        return {
            "intent": "none"
        }


    return parsed


def task_chat_query_reply(
    scope,
    client_context=None
):

    tasks = get_tasks()

    local_now = None

    if isinstance(
        client_context,
        dict
    ):

        raw_local_time = str(
            client_context.get(
                "local_time",
                ""
            )
            or ""
        ).strip()

        if raw_local_time:

            try:
                local_now = datetime.strptime(
                    raw_local_time.rsplit(
                        " ",
                        1
                    )[0],
                    "%A, %B %d, %Y at %I:%M:%S %p"
                )

            except Exception:
                local_now = None


    if local_now is None:

        offset_minutes = 0

        if isinstance(
            client_context,
            dict
        ):

            try:
                offset_minutes = int(
                    client_context.get(
                        "utc_offset_minutes",
                        0
                    )
                    or 0
                )
            except Exception:
                offset_minutes = 0

        local_now = (
            datetime.utcnow()
            + timedelta(
                minutes=offset_minutes
            )
        )


    today = local_now.strftime(
        "%Y-%m-%d"
    )

    tomorrow = (
        local_now
        + timedelta(
            days=1
        )
    ).strftime(
        "%Y-%m-%d"
    )


    def due_date(
        task
    ):

        value = str(
            task.get(
                "due_at"
            )
            or ""
        )

        return (
            value.split(
                "T",
                1
            )[0]
            if value
            else ""
        )


    scope = (
        str(
            scope
            or "all"
        )
        .strip()
        .lower()
    )


    if scope == "today":

        chosen = [
            task
            for task in tasks
            if (
                not task.get(
                    "completed"
                )
                and (
                    not due_date(
                        task
                    )
                    or due_date(
                        task
                    ) <= today
                )
            )
        ]

        heading = "Today"


    elif scope == "tomorrow":

        chosen = [
            task
            for task in tasks
            if (
                not task.get(
                    "completed"
                )
                and due_date(
                    task
                ) == tomorrow
            )
        ]

        heading = "Tomorrow"


    elif scope == "upcoming":

        chosen = [
            task
            for task in tasks
            if (
                not task.get(
                    "completed"
                )
                and due_date(
                    task
                ) > today
            )
        ]

        heading = "Upcoming"


    elif scope == "completed":

        chosen = [
            task
            for task in tasks
            if task.get(
                "completed"
            )
        ]

        heading = "Completed"


    else:

        chosen = [
            task
            for task in tasks
            if not task.get(
                "completed"
            )
        ]

        heading = "Your tasks"


    if not chosen:

        if scope == "today":
            return "You’re clear for today."

        if scope == "tomorrow":
            return "You don’t have anything due tomorrow."

        if scope == "completed":
            return "You don’t have any completed tasks yet."

        return "You don’t have any tasks there right now."


    lines = []


    for task in chosen[:12]:

        summary = task_chat_task_summary(
            task
        )

        lines.append(
            f"• {summary}"
        )


    extra = (
        len(chosen)
        - len(lines)
    )


    reply = (
        heading
        + ":\n"
        + "\n".join(
            lines
        )
    )


    if extra > 0:

        reply += (
            f"\n• +{extra} more"
        )


    return reply


# =========================================================
# APOLLO TASK BULK DELETE V1
# =========================================================

def task_chat_bulk_delete_requested(
    user_message
):
    value = (
        str(user_message or "")
        .strip()
        .lower()
    )

    delete_words = (
        "delete",
        "remove",
        "clear"
    )

    all_phrases = (
        "all my tasks",
        "all tasks",
        "every task",
        "every one of my tasks",
        "all of the tasks",
        "my entire task list",
        "entire task list",
        "clear my tasks",
        "clear all tasks"
    )

    return (
        any(
            word in value
            for word in delete_words
        )
        and any(
            phrase in value
            for phrase in all_phrases
        )
    )


# =========================================================
# APOLLO TASK PENDING INTERPRETER V1
# =========================================================

def task_chat_interpret_pending_reply(
    user_message,
    pending_action,
    pending_data
):
    """
    Interpret a reply while Apollo is waiting on a task action.

    Returns:
        confirm
        cancel
        unclear
    """

    prompt = [
        {
            "role": "system",
            "content": """
You interpret short replies to a pending Apollo task action.

Return VALID JSON ONLY:

{
  "decision": "confirm"
}

or

{
  "decision": "cancel"
}

or

{
  "decision": "unclear"
}

Interpret meaning naturally.

Examples that usually mean confirm:
- yes
- ye
- yea
- yeah
- yeahh
- yessir
- yup
- sure
- sure bro
- do it
- go ahead
- all of them
- delete them
- that's fine
- okay
- ok

Examples that usually mean cancel:
- no
- nah
- nope
- don't
- dont
- cancel
- never mind
- actually no
- leave them
- keep them

Use unclear when:
- the reply changes the request
- the user asks a new question
- the meaning is genuinely ambiguous

Important:
You are NOT executing anything.
You are only classifying the user's reply to the pending task action.
"""
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "pending_action":
                        pending_action,

                    "pending_data":
                        pending_data,

                    "reply":
                        str(
                            user_message or ""
                        )
                },
                ensure_ascii=False
            )
        }
    ]


    try:

        raw = ask_hermes(
            prompt
        )

        parsed = task_chat_clean_json(
            raw
        )

        if isinstance(
            parsed,
            dict
        ):

            decision = str(
                parsed.get(
                    "decision",
                    "unclear"
                )
            ).strip().lower()

            if decision in {
                "confirm",
                "cancel",
                "unclear"
            }:
                return decision

    except Exception as error:

        print(
            "[Apollo Tasks Chat] "
            f"Pending interpreter failed: {error}"
        )


    # Safe deterministic fallback.
    if task_chat_yes(
        user_message
    ):
        return "confirm"

    if task_chat_no(
        user_message
    ):
        return "cancel"

    return "unclear"


def task_chat_handle_pending(
    chat_id,
    user_message
):

    state = task_chat_state_get(
        chat_id
    )

    pending_action = (
        state.get(
            "pending_action"
        )
    )

    pending_data = (
        state.get(
            "pending_data"
        )
        or {}
    )


    if not pending_action:
        return None


    decision = (
        task_chat_interpret_pending_reply(
            user_message,
            pending_action,
            pending_data
        )
    )


    if decision == "confirm":

        if (
            pending_action
            == "delete_all"
        ):

            task_ids = (
                pending_data.get(
                    "task_ids"
                )
                or []
            )

            deleted = 0

            for task_id in task_ids:

                try:

                    delete_task(
                        task_id
                    )

                    deleted += 1

                except Exception:

                    # A task may have disappeared since confirmation.
                    pass


            task_chat_state_set(
                chat_id,
                last_task_id=None,
                pending_action=None,
                pending_data=None,
                preserve_last=False
            )


            if deleted == 0:

                return (
                    "There weren’t any tasks left to delete."
                )


            return (
                f"Done — deleted all {deleted} "
                + (
                    "task."
                    if deleted == 1
                    else "tasks."
                )
            )


        if (
            pending_action
            == "delete"
        ):

            task_id = (
                pending_data.get(
                    "task_id"
                )
            )

            task = task_chat_find_task(
                task_id=task_id
            )


            if not task:

                task_chat_clear_pending(
                    chat_id
                )

                return (
                    "That task no longer exists, "
                    "so there was nothing to delete."
                )


            title = (
                task.get(
                    "title"
                )
            )


            delete_task(
                task_id
            )


            task_chat_state_set(
                chat_id,
                last_task_id=None,
                pending_action=None,
                pending_data=None,
                preserve_last=False
            )


            return (
                f"Deleted — {title}."
            )


    if decision == "cancel":

        task_chat_clear_pending(
            chat_id
        )

        if pending_action == "delete_all":

            return (
                "Okay — I left your tasks alone."
            )

        return (
            "Okay — I left the task alone."
        )


    if pending_action == "delete_all":

        count = len(
            pending_data.get(
                "task_ids"
            )
            or []
        )

        return (
            f"Delete all {count} tasks?"
        )


    return (
        "Do you want me to delete that task?"
    )


def apollo_task_chat(
    chat_id,
    user_message,
    client_context,
    status_callback=None
):

    state = task_chat_state_get(
        chat_id
    )


    pending_reply = (
        task_chat_handle_pending(
            chat_id,
            user_message
        )
    )


    if pending_reply is not None:
        return pending_reply


    last_task = None

    last_task_id = (
        state.get(
            "last_task_id"
        )
    )


    if last_task_id is not None:

        row = get_task(
            last_task_id
        )

        if row:

            last_task = (
                task_dict(
                    row
                )
            )


    surface = (
        str(
            client_context.get(
                "surface",
                ""
            )
        ).strip().lower()
        if isinstance(
            client_context,
            dict
        )
        else ""
    )


    if (
        surface != "tasks"
        and not task_chat_maybe_related(
            user_message,
            has_task_context=bool(
                last_task
            ),
            has_pending=False
        )
    ):

        return None


    tasks = get_tasks()


    # =====================================================
    # BULK DELETE
    # =====================================================

    if task_chat_bulk_delete_requested(
        user_message
    ):

        if not tasks:

            return (
                "Your task list is already empty."
            )


        task_ids = [
            task["id"]
            for task in tasks
        ]


        task_chat_state_set(
            chat_id,
            last_task_id=None,
            pending_action="delete_all",
            pending_data={
                "task_ids":
                    task_ids
            },
            preserve_last=False
        )


        count = len(
            task_ids
        )


        return (
            f"Delete all {count} "
            + (
                "task? "
                if count == 1
                else "tasks? "
            )
            + "Say yes to confirm."
        )


    interpreted = (
        task_chat_interpret_message(
            user_message,
            client_context,
            tasks,
            last_task=
                last_task
        )
    )


    intent = (
        interpreted.get(
            "intent",
            "none"
        )
    )


    if intent == "none":
        return None


    if status_callback is not None:

        status_map = {
            "query":
                "Checking tasks…",

            "create":
                "Creating task…",

            "complete":
                "Completing task…",

            "update":
                "Updating task…",

            "delete":
                "Preparing deletion…",

            "clarify":
                "Checking tasks…"
        }

        status = status_map.get(
            intent,
            "Working with tasks…"
        )

        try:
            status_callback(
                status
            )
        except Exception as error:
            print(
                "[Apollo Task Status] "
                f"{error}"
            )


    if intent == "clarify":

        return (
            interpreted.get(
                "reply"
            )
            or (
                "Which task do you mean?"
            )
        )


    if intent == "query":

        return task_chat_query_reply(
            interpreted.get(
                "query_scope"
            ),
            client_context
        )


    if intent == "create":

        title = str(
            interpreted.get(
                "title"
            )
            or ""
        ).strip()


        if not title:

            return (
                "What should I call the task?"
            )


        task = create_task({
            "title":
                title,

            "due_at":
                interpreted.get(
                    "due_at"
                )
        })


        task_chat_state_set(
            chat_id,
            last_task_id=
                task["id"],
            pending_action=None,
            pending_data=None,
            preserve_last=False
        )


        summary = (
            task_chat_task_summary(
                task
            )
        )


        return (
            f"Added — {summary}."
        )


    task = task_chat_find_task(
        task_id=
            interpreted.get(
                "task_id"
            ),

        title_hint=
            interpreted.get(
                "title_hint"
            ),

        last_task_id=
            last_task_id
    )


    if not task:

        return (
            interpreted.get(
                "reply"
            )
            or (
                "Which task do you mean?"
            )
        )


    task_id = (
        task["id"]
    )


    if intent == "complete":

        updated = update_task({
            "task_id":
                task_id,

            "completed":
                True
        })


        task_chat_state_set(
            chat_id,
            last_task_id=
                task_id,
            pending_action=None,
            pending_data=None,
            preserve_last=False
        )


        return (
            f"Done — "
            f"{updated['title']}."
        )


    if intent == "reopen":

        updated = update_task({
            "task_id":
                task_id,

            "completed":
                False
        })


        task_chat_state_set(
            chat_id,
            last_task_id=
                task_id,
            pending_action=None,
            pending_data=None,
            preserve_last=False
        )


        return (
            f"Reopened — "
            f"{updated['title']}."
        )


    if intent == "update":

        payload = {
            "task_id":
                task_id
        }


        new_title = (
            interpreted.get(
                "new_title"
            )
        )


        if new_title is not None:

            new_title = str(
                new_title
            ).strip()

            if new_title:

                payload[
                    "title"
                ] = new_title


        if interpreted.get(
            "due_at_present"
        ):

            payload[
                "due_at"
            ] = (
                interpreted.get(
                    "due_at"
                )
            )


        if len(
            payload
        ) == 1:

            return (
                "What would you like me "
                "to change about that task?"
            )


        updated = update_task(
            payload
        )


        task_chat_state_set(
            chat_id,
            last_task_id=
                task_id,
            pending_action=None,
            pending_data=None,
            preserve_last=False
        )


        return (
            "Updated — "
            + task_chat_task_summary(
                updated
            )
            + "."
        )


    if intent == "delete":

        task_chat_state_set(
            chat_id,
            last_task_id=
                task_id,
            pending_action=
                "delete",
            pending_data={
                "task_id":
                    task_id
            },
            preserve_last=False
        )


        return (
            f'Delete "{task["title"]}"? '
            "Say yes to confirm."
        )


    return None




# =========================================================
# APOLLO NATURAL SILENCE V1
# =========================================================

def apollo_silence_candidate(
    user_message
):
    """
    Fast gate.

    We only ask Hermes whether to stay silent for
    short, conversational messages that could naturally
    be acknowledgements / laughter / endings.

    Substantive messages go straight through normally.
    """

    value = str(
        user_message or ""
    ).strip()


    if not value:
        return False


    # Questions should virtually always receive a response.
    if "?" in value:
        return False


    words = value.split()


    # Don't add an extra classifier call to substantive messages.
    if len(words) > 14:
        return False


    lower = value.lower()


    # Things that strongly imply a continuing request.
    continuation_signals = (
        "but ",
        "what ",
        "why ",
        "how ",
        "when ",
        "where ",
        "who ",
        "which ",
        "can you",
        "could you",
        "would you",
        "tell me",
        "show me",
        "help me",
        "make ",
        "add ",
        "create ",
        "change ",
        "move ",
        "delete ",
        "remove ",
        "play ",
        "pause ",
        "remind ",
        "schedule ",
        "look up",
        "search ",
        "explain ",
    )


    if any(
        lower.startswith(
            signal
        )
        for signal in continuation_signals
    ):
        return False


    return True


def apollo_should_reply_semantically(
    messages,
    user_message
):
    """
    Decide whether Apollo should actually send a reply.

    Safety/default behavior:
    if interpretation fails or is uncertain, REPLY.
    """

    if not apollo_silence_candidate(
        user_message
    ):
        return True


    # Give the classifier enough conversation to understand
    # whether this really feels like a natural stopping point.
    recent = []

    for message in messages[-10:]:

        if not isinstance(
            message,
            dict
        ):
            continue


        role = message.get(
            "role"
        )

        content = str(
            message.get(
                "content",
                ""
            )
        ).strip()


        if (
            role in (
                "user",
                "assistant"
            )
            and content
        ):
            recent.append({
                "role": role,
                "content": content
            })


    prompt = [
        {
            "role": "system",
            "content": """
You decide whether Apollo, a personal AI assistant, should reply to the user's latest conversational message.

Apollo is allowed to say NOTHING when the conversation has naturally ended.

Return VALID JSON ONLY:

{
  "reply": true
}

or

{
  "reply": false
}

Choose reply=false when:
- the user is merely acknowledging the previous response
- the user says something like "ok", "okay", "yeah", "nice", "cool", "bet", "thanks", "haha", "hahaha", "lol", "lmao", etc.
- the user's message does not ask for anything new
- the previous assistant message already completed the topic
- replying would only create unnecessary conversational filler
- a normal human could comfortably leave the message unanswered

Choose reply=true when:
- the user asks a question
- the user gives a new request or instruction
- the user introduces new substantive information that naturally deserves engagement
- the user seems emotionally significant, concerned, confused, upset, excited in a way that merits a response
- the user is continuing the topic rather than closing it
- silence could feel dismissive
- you are uncertain

Important:
Do NOT keep conversations alive just for politeness.
Apollo does not need the last word.
Silence is a valid and desirable response when the interaction is clearly complete.
"""
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "conversation":
                        recent,

                    "latest_user_message":
                        user_message
                },
                ensure_ascii=False
            )
        }
    ]


    try:

        raw = ask_hermes(
            prompt
        )

        value = str(
            raw or ""
        ).strip()


        if value.startswith(
            "```"
        ):

            lines = value.splitlines()

            if lines:
                lines = lines[1:]

            if (
                lines
                and lines[-1].strip()
                == "```"
            ):
                lines = lines[:-1]

            value = "\n".join(
                lines
            ).strip()


        result = json.loads(
            value
        )


        if not isinstance(
            result,
            dict
        ):
            return True


        decision = result.get(
            "reply"
        )


        # Only an explicit boolean false causes silence.
        return decision is not False


    except Exception as error:

        print(
            "[Apollo Natural Silence] "
            f"Decision failed: {error}"
        )

        # Failure should never accidentally suppress a useful reply.
        return True



class ApolloHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        print(f"[Apollo] {format % args}")

    def do_GET(self):

        # Tailscale Serve mounted at /api strips that prefix.
        # Restore it so existing Apollo routes continue to work.
        if not self.path.startswith("/api"):
            self.path = "/api" + self.path

        # ─────────────────────────────
        # GOOGLE CALENDAR
        # ─────────────────────────────

        parsed_url = urllib.parse.urlparse(
            self.path
        )

        route = parsed_url.path

        # ─────────────────────────────
        # TASKS
        # ─────────────────────────────

        if route == "/api/tasks":

            json_response(
                self,
                {
                    "tasks":
                        get_tasks()
                }
            )

            return


        if route == "/api/google/status":

            json_response(
                self,
                {
                    "connected": bool(
                        app_state_get(
                            "google_refresh_token"
                        )
                    )
                }
            )
            return

        if route == "/api/google/connect":

            try:
                url = google_authorization_url()

            except Exception as exc:
                json_response(
                    self,
                    {
                        "error": str(exc)
                    },
                    500
                )
                return

            self.send_response(302)
            self.send_header(
                "Location",
                url
            )
            self.send_header(
                "Cache-Control",
                "no-store"
            )
            self.end_headers()
            return

        if route == "/api/google/callback":

            query = urllib.parse.parse_qs(
                parsed_url.query
            )

            if query.get("error"):
                json_response(
                    self,
                    {
                        "error":
                            query["error"][0]
                    },
                    400
                )
                return

            code = (
                query.get(
                    "code",
                    [None]
                )[0]
            )

            state = (
                query.get(
                    "state",
                    [None]
                )[0]
            )

            expected_state = app_state_get(
                "google_oauth_state"
            )

            created_at = int(
                app_state_get(
                    "google_oauth_state_created_at",
                    "0"
                )
            )

            valid_state = (
                state
                and expected_state
                and secrets.compare_digest(
                    state,
                    expected_state
                )
                and (
                    time.time()
                    - created_at
                    < 900
                )
            )

            if not valid_state:
                json_response(
                    self,
                    {
                        "error":
                            "Invalid or expired OAuth state"
                    },
                    400
                )
                return

            if not code:
                json_response(
                    self,
                    {
                        "error":
                            "Authorization code missing"
                    },
                    400
                )
                return

            try:
                google_exchange_code(
                    code
                )

            except Exception as exc:
                json_response(
                    self,
                    {
                        "error": str(exc)
                    },
                    500
                )
                return

            app_state_delete(
                "google_oauth_state"
            )

            app_state_delete(
                "google_oauth_state_created_at"
            )

            self.send_response(302)
            self.send_header(
                "Location",
                "/?calendar=connected"
            )
            self.send_header(
                "Cache-Control",
                "no-store"
            )
            self.end_headers()
            return

        # ─────────────────────────────
        # WHOOP
        # ─────────────────────────────

        if route == "/api/whoop/status":

            json_response(
                self,
                {
                    "connected": bool(
                        app_state_get(
                            "whoop_refresh_token"
                        )
                    )
                }
            )

            return


        if route == "/api/whoop/connect":

            try:

                url = (
                    whoop_authorization_url()
                )

            except Exception as exc:

                json_response(
                    self,
                    {
                        "error":
                            str(exc)
                    },
                    500
                )

                return


            self.send_response(
                302
            )

            self.send_header(
                "Location",
                url
            )

            self.send_header(
                "Cache-Control",
                "no-store"
            )

            self.end_headers()

            return


        if route == "/api/whoop/callback":

            query = (
                urllib.parse.parse_qs(
                    parsed_url.query
                )
            )


            if query.get(
                "error"
            ):

                json_response(
                    self,
                    {
                        "error":
                            query["error"][0]
                    },
                    400
                )

                return


            code = (
                query.get(
                    "code",
                    [None]
                )[0]
            )


            state = (
                query.get(
                    "state",
                    [None]
                )[0]
            )


            expected_state = (
                app_state_get(
                    "whoop_oauth_state"
                )
            )


            created_at = int(
                app_state_get(
                    "whoop_oauth_state_created_at",
                    "0"
                )
            )


            valid_state = (
                state
                and expected_state
                and secrets.compare_digest(
                    state,
                    expected_state
                )
                and (
                    time.time()
                    - created_at
                    < 900
                )
            )


            if not valid_state:

                json_response(
                    self,
                    {
                        "error":
                            "Invalid or expired OAuth state"
                    },
                    400
                )

                return


            if not code:

                json_response(
                    self,
                    {
                        "error":
                            "Authorization code missing"
                    },
                    400
                )

                return


            try:

                whoop_exchange_code(
                    code
                )

            except Exception as exc:

                json_response(
                    self,
                    {
                        "error":
                            str(exc)
                    },
                    500
                )

                return


            app_state_delete(
                "whoop_oauth_state"
            )

            app_state_delete(
                "whoop_oauth_state_created_at"
            )


            self.send_response(
                302
            )

            self.send_header(
                "Location",
                "/?whoop=connected"
            )

            self.send_header(
                "Cache-Control",
                "no-store"
            )

            self.end_headers()

            return


        if route == "/api/whoop/summary":

            try:

                payload = (
                    whoop_card_payload()
                )

                json_response(
                    self,
                    payload
                )

            except Exception as exc:

                json_response(
                    self,
                    {
                        "status":
                            "unavailable",

                        "error":
                            str(exc)
                    },
                    503
                )

            return


        if route == "/api/calendar/events":

            query = urllib.parse.parse_qs(
                parsed_url.query
            )

            try:
                days = int(
                    query.get(
                        "days",
                        ["7"]
                    )[0]
                )

            except ValueError:
                days = 7

            days = max(
                1,
                min(days, 30)
            )

            start_date = (
                query.get(
                    "start",
                    [None]
                )[0]
            )

            try:
                events = (
                    google_calendar_events(
                        days,
                        start_date=start_date
                    )
                )

            except RuntimeError as exc:

                status = (
                    401
                    if "not connected"
                    in str(exc).lower()
                    else 500
                )

                json_response(
                    self,
                    {
                        "error": str(exc)
                    },
                    status
                )
                return

            json_response(
                self,
                {
                    "events": events,
                    "days": days
                }
            )
            return

        # ─────────────────────────────
        # NOW PLAYING
        # ─────────────────────────────

        if self.path == "/api/now-playing":
            json_response(
                self,
                get_now_playing()
            )
            return


        # ─────────────────────────────
        # SPOTIFY RECENTLY PLAYED
        # Albums + playlists only.
        # ─────────────────────────────

        if route == "/api/spotify/recent-contexts":

            json_response(
                self,
                get_spotify_recent_contexts()
            )

            return


        # ─────────────────────────────
        # APOLLO STUDIO V1
        # ─────────────────────────────

        if route in (
            "/api/studio/projects",
            "/studio/projects"
        ):

            json_response(
                self,
                {
                    "projects":
                        get_studio_projects()
                }
            )

            return


        if (
            route.startswith(
                "/api/studio/projects/"
            )
            or route.startswith(
                "/studio/projects/"
            )
        ):

            try:

                project_id = int(
                    route
                        .rstrip("/")
                        .split("/")[-1]
                )


                json_response(
                    self,
                    {
                        "project":
                            get_studio_project(
                                project_id
                            )
                    }
                )


            except ValueError as exc:

                json_response(
                    self,
                    {
                        "error":
                            str(exc)
                    },
                    404
                )


            except Exception as exc:

                print(
                    "[Apollo Studio] GET:",
                    exc
                )


                json_response(
                    self,
                    {
                        "error":
                            "Could not load Studio project"
                    },
                    500
                )


            return


        # ─────────────────────────────
        # WORKS IN PROGRESS
        # ─────────────────────────────

        if route == "/api/wip/projects":

            json_response(
                self,
                {
                    "projects":
                        get_wip_projects()
                }
            )

            return


        if route.startswith(
            "/api/wip/file/"
        ):

            parts = (
                route.strip("/")
                .split("/")
            )

            try:

                project_id = int(
                    parts[3]
                )

                kind = parts[4]

            except (
                ValueError,
                IndexError
            ):

                json_response(
                    self,
                    {
                        "error":
                            "Invalid WIP file"
                    },
                    400
                )

                return

            send_wip_file(
                self,
                project_id,
                kind
            )

            return


        # ─────────────────────────────
        # ─────────────────────────────
        # DAILY DEBRIEF
        # ─────────────────────────────

        if (
            urllib.parse.urlparse(
                self.path
            ).path
            == "/api/debrief"
        ):

            parsed = urllib.parse.urlparse(
                self.path
            )

            query = urllib.parse.parse_qs(
                parsed.query
            )

            requested_zone = (
                query.get(
                    "time_zone",
                    [""]
                )[0].strip()
            )

            time_zone = requested_zone

            if not time_zone:

                conn = db()

                state = conn.execute("""
                    SELECT value
                    FROM app_state
                    WHERE key = 'time_zone'
                """).fetchone()

                conn.close()

                time_zone = (
                    state["value"]
                    if state
                    else "UTC"
                )

            try:

                zone = ZoneInfo(
                    time_zone
                )

            except Exception:

                zone = timezone.utc
                time_zone = "UTC"

            local_date = (
                datetime.now(
                    zone
                )
                .date()
                .isoformat()
            )

            conn = db()

            row = conn.execute("""
                SELECT
                    local_date,
                    timezone,
                    content,
                    generated_at
                FROM daily_debriefs
                WHERE local_date <= ?
                ORDER BY
                    local_date DESC,
                    id DESC
                LIMIT 1
            """, (
                local_date,
            )).fetchone()

            conn.close()

            json_response(
                self,
                {
                    "debrief":
                        dict(row)
                        if row
                        else None,

                    "device_time_zone":
                        time_zone,

                    "device_local_date":
                        local_date
                }
            )
            return

        # ─────────────────────────────
        # APOLLO CHAT ATTACHMENT FILE
        # ─────────────────────────────

        if route.startswith(
            "/api/chat-attachments/"
        ):

            is_preview = route.endswith("/preview")

            try:

                parts = route.strip("/").split("/")

                attachment_id = int(
                    parts[2]
                )

            except Exception:

                json_response(
                    self,
                    {
                        "error":
                            "Invalid attachment"
                    },
                    400
                )

                return


            conn = db()

            attachment = conn.execute(
                """
                SELECT
                    filename,
                    file_path,
                    mime_type
                FROM message_attachments
                WHERE id = ?
                """,
                (
                    attachment_id,
                )
            ).fetchone()

            conn.close()


            if not attachment:

                json_response(
                    self,
                    {
                        "error":
                            "Attachment not found"
                    },
                    404
                )

                return


            file_path = Path(
                attachment[
                    "file_path"
                ]
            )


            if (
                is_preview
                and str(
                    attachment["mime_type"]
                    or ""
                ).startswith("image/")
            ):

                from PIL import Image

                preview_path = file_path.with_suffix(
                    ".preview.webp"
                )

                if not preview_path.exists():

                    try:

                        with Image.open(
                            file_path
                        ) as image:

                            image.thumbnail(
                                (
                                    1280,
                                    1280
                                ),
                                Image.Resampling.LANCZOS
                            )

                            if image.mode not in (
                                "RGB",
                                "RGBA"
                            ):
                                image = image.convert(
                                    "RGB"
                                )

                            image.save(
                                preview_path,
                                "WEBP",
                                quality=84,
                                method=4
                            )

                    except Exception as exc:

                        print(
                            "[Apollo Attachment Preview]",
                            exc
                        )

                        preview_path = file_path


                if preview_path.exists():

                    file_path = preview_path


            if not file_path.exists():

                json_response(
                    self,
                    {
                        "error":
                            "Attachment file missing"
                    },
                    404
                )

                return


            payload = (
                file_path.read_bytes()
            )


            self.send_response(200)

            self.send_header(
                "Content-Type",
                (
                    "image/webp"
                    if (
                        is_preview
                        and file_path.suffix
                        == ".webp"
                    )
                    else (
                        attachment["mime_type"]
                        or "application/octet-stream"
                    )
                )
            )

            self.send_header(
                "Content-Length",
                str(
                    len(payload)
                )
            )

            self.send_header(
                "Content-Disposition",
                "inline"
            )

            self.send_header(
                "Cache-Control",
                "private, max-age=3600"
            )

            self.end_headers()

            self.wfile.write(
                payload
            )

            return


        # CHAT SEARCH
        # ─────────────────────────────

        if self.path.startswith("/api/chats/search"):

            from urllib.parse import urlparse, parse_qs

            parsed = urlparse(self.path)

            query = parse_qs(
                parsed.query
            ).get(
                "q",
                [""]
            )[0].strip()

            if not query:
                json_response(
                    self,
                    {
                        "query": "",
                        "results": []
                    }
                )
                return

            conn = db()

            rows = conn.execute("""
                SELECT
                    c.id,
                    c.title,
                    c.created_at,
                    c.updated_at,

                    (
                        SELECT m.id
                        FROM messages m
                        WHERE
                            m.chat_id = c.id
                            AND instr(
                                lower(coalesce(m.content, '')),
                                lower(?)
                            ) > 0
                        ORDER BY m.id DESC
                        LIMIT 1
                    ) AS matched_message_id,

                    (
                        SELECT m.content
                        FROM messages m
                        WHERE
                            m.chat_id = c.id
                            AND instr(
                                lower(coalesce(m.content, '')),
                                lower(?)
                            ) > 0
                        ORDER BY m.id DESC
                        LIMIT 1
                    ) AS matched_content

                FROM chats c

                WHERE
                    instr(
                        lower(coalesce(c.title, '')),
                        lower(?)
                    ) > 0

                    OR EXISTS (
                        SELECT 1
                        FROM messages m
                        WHERE
                            m.chat_id = c.id
                            AND instr(
                                lower(coalesce(m.content, '')),
                                lower(?)
                            ) > 0
                    )

                ORDER BY c.updated_at DESC
                LIMIT 50
            """, (
                query,
                query,
                query,
                query
            )).fetchall()

            conn.close()

            results = []

            for row in rows:
                item = dict(row)

                matched_content = (
                    item.pop(
                        "matched_content",
                        None
                    )
                    or ""
                ).strip()

                if len(matched_content) > 180:
                    matched_content = (
                        matched_content[:177].rstrip()
                        + "…"
                    )

                item["snippet"] = matched_content

                item["title_match"] = (
                    query.lower()
                    in (
                        item.get("title")
                        or ""
                    ).lower()
                )

                results.append(item)

            json_response(
                self,
                {
                    "query": query,
                    "results": results
                }
            )
            return


        # CHAT LIST
        # ─────────────────────────────

        if self.path == "/api/chats":

            conn = db()

            chats = conn.execute("""
                SELECT id, title, created_at, updated_at
                FROM chats
                ORDER BY updated_at DESC
            """).fetchall()

            conn.close()

            json_response(
                self,
                {
                    "chats": [
                        dict(chat)
                        for chat in chats
                    ]
                }
            )
            return

        # ─────────────────────────────
        # SINGLE CHAT
        # ─────────────────────────────

        if self.path.startswith("/api/chats/"):

            try:
                chat_id = int(
                    self.path.split("/")[-1]
                )
            except ValueError:
                json_response(
                    self,
                    {"error": "Invalid chat ID"},
                    400
                )
                return

            conn = db()

            chat = conn.execute(
                "SELECT * FROM chats WHERE id = ?",
                (chat_id,)
            ).fetchone()

            messages = conn.execute("""
                SELECT id, role, content, created_at
                FROM messages
                WHERE chat_id = ?
                ORDER BY id ASC
            """, (chat_id,)).fetchall()


            attachment_rows = conn.execute("""
                SELECT
                    id,
                    message_id,
                    filename,
                    mime_type,
                    size_bytes
                FROM message_attachments
                WHERE chat_id = ?
                  AND message_id IS NOT NULL
                ORDER BY id ASC
            """, (
                chat_id,
            )).fetchall()


            attachments_by_message = {}


            for attachment in attachment_rows:

                attachments_by_message.setdefault(
                    attachment[
                        "message_id"
                    ],
                    []
                ).append({
                    "id":
                        attachment["id"],

                    "filename":
                        attachment[
                            "filename"
                        ],

                    "mime_type":
                        attachment[
                            "mime_type"
                        ],

                    "size_bytes":
                        attachment[
                            "size_bytes"
                        ],

                    "url":
                        (
                            "/api/chat-attachments/"
                            + str(
                                attachment["id"]
                            )
                        )
                })


            conn.close()

            if not chat:
                json_response(
                    self,
                    {"error": "Chat not found"},
                    404
                )
                return

            json_response(
                self,
                {
                    "chat": dict(chat),
                    "messages": [
                        {
                            **dict(message),

                            "attachments":
                                attachments_by_message.get(
                                    message["id"],
                                    []
                                )
                        }
                        for message in messages
                    ]
                }
            )
            return

        json_response(
            self,
            {"error": "Not found"},
            404
        )

    def do_POST(self):

        # =====================================================
        # APOLLO STUDIO WRITE ROUTES V1
        # =====================================================

        studio_route = (
            urllib.parse.urlparse(
                self.path
            ).path
        )

        # Tailscale Serve mounts the backend at /api and may
        # forward the remainder as /studio/... .
        # Normalize both forms to Apollo's canonical route.
        if studio_route.startswith(
            "/studio/"
        ):
            studio_route = (
                "/api"
                + studio_route
            )

        if studio_route.startswith(
            "/api/studio/"
        ):

            try:

                import studio_backend

                studio_backend.configure(
                    db,
                    WIP_DIR,
                    ensure_wip_playback_file,
                    read_multipart,
                )


                json_routes = {
                    "/api/studio/projects/create":
                        studio_backend.create_project,

                    "/api/studio/projects/update":
                        studio_backend.update_project,

                    "/api/studio/projects/delete":
                        studio_backend.delete_project,

                    "/api/studio/tracks/create":
                        studio_backend.create_track,

                    "/api/studio/tracks/update":
                        studio_backend.update_track,

                    "/api/studio/tracks/delete":
                        studio_backend.delete_track,

                    "/api/studio/versions/update":
                        studio_backend.update_version,

                    "/api/studio/versions/current":
                        studio_backend.set_current_version,

                    "/api/studio/versions/delete":
                        studio_backend.delete_version,

                    "/api/studio/versions/upload/start":
                        studio_backend.studio_version_upload_start,

                    "/api/studio/versions/upload/finish":
                        studio_backend.studio_version_upload_finish,

                    "/api/studio/versions/upload/abort":
                        studio_backend.studio_version_upload_abort,

                    "/api/studio/notes/create":
                        studio_backend.create_note,

                    "/api/studio/notes/update":
                        studio_backend.update_note,

                    "/api/studio/notes/delete":
                        studio_backend.delete_note,

                    "/api/studio/media/link":
                        studio_backend.create_media_link,

                    "/api/studio/media/update":
                        studio_backend.update_media,

                    "/api/studio/media/delete":
                        studio_backend.delete_media,
                }


                multipart_routes = {
                    "/api/studio/projects/artwork":
                        studio_backend.upload_artwork,

                    "/api/studio/versions/upload":
                        studio_backend.upload_version,

                    "/api/studio/versions/upload/chunk":
                        studio_backend.studio_version_upload_chunk,

                    "/api/studio/media/upload":
                        studio_backend.upload_media,
                }


                if studio_route in json_routes:

                    data = read_json(
                        self
                    )

                    result = json_routes[
                        studio_route
                    ](
                        data
                    )


                elif studio_route in multipart_routes:

                    result = multipart_routes[
                        studio_route
                    ](
                        self
                    )


                else:

                    json_response(
                        self,
                        {
                            "error":
                                "Unknown Studio action"
                        },
                        404
                    )

                    return


                json_response(
                    self,
                    result
                )


            except ValueError as exc:

                json_response(
                    self,
                    {
                        "error":
                            str(exc)
                    },
                    400
                )


            except Exception as exc:

                print(
                    "[Apollo Studio] POST:",
                    repr(exc)
                )

                json_response(
                    self,
                    {
                        "error":
                            "Studio action failed"
                    },
                    500
                )


            return



        # Tailscale Serve mounted at /api strips that prefix.
        # Restore it so existing Apollo routes continue to work.
        if not self.path.startswith("/api"):
            self.path = "/api" + self.path

        # ─────────────────────────────
        # APOLLO CHAT ATTACHMENT UPLOAD
        # ─────────────────────────────

        if (
            self.path
            == "/api/chat-attachments/upload"
        ):

            try:

                fields, files = (
                    read_multipart(
                        self,
                        max_bytes=(
                            50
                            * 1024
                            * 1024
                        )
                    )
                )


                try:

                    chat_id = int(
                        fields.get(
                            "chat_id",
                            "0"
                        )
                    )

                except Exception:

                    raise ValueError(
                        "Invalid chat ID"
                    )


                upload = files.get(
                    "file"
                )


                if chat_id <= 0:

                    raise ValueError(
                        "Missing chat ID"
                    )


                if not upload:

                    raise ValueError(
                        "Missing file"
                    )


                conn = db()

                chat = conn.execute(
                    """
                    SELECT id
                    FROM chats
                    WHERE id = ?
                    """,
                    (
                        chat_id,
                    )
                ).fetchone()


                if not chat:

                    conn.close()

                    json_response(
                        self,
                        {
                            "error":
                                "Chat not found"
                        },
                        404
                    )

                    return


                original_name = (
                    Path(
                        upload.get(
                            "filename"
                        )
                        or "attachment"
                    ).name
                )


                suffix = (
                    Path(
                        original_name
                    ).suffix
                )


                storage_name = (
                    uuid.uuid4().hex
                    + suffix
                )


                file_path = (
                    CHAT_UPLOAD_DIR
                    / storage_name
                )


                payload = (
                    upload.get(
                        "data"
                    )
                    or b""
                )


                file_path.write_bytes(
                    payload
                )


                mime_type = str(
                    upload.get(
                        "content_type"
                    )
                    or (
                        "application/"
                        "octet-stream"
                    )
                )


                cursor = conn.execute(
                    """
                    INSERT INTO message_attachments (
                        chat_id,
                        message_id,
                        filename,
                        storage_name,
                        file_path,
                        mime_type,
                        size_bytes
                    )
                    VALUES (
                        ?,
                        NULL,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?
                    )
                    """,
                    (
                        chat_id,
                        original_name,
                        storage_name,
                        str(file_path),
                        mime_type,
                        len(payload)
                    )
                )


                attachment_id = (
                    cursor.lastrowid
                )


                conn.commit()
                conn.close()


                json_response(
                    self,
                    {
                        "ok": True,

                        "attachment": {
                            "id":
                                attachment_id,

                            "filename":
                                original_name,

                            "mime_type":
                                mime_type,

                            "size_bytes":
                                len(payload),

                            "url":
                                (
                                    "/api/chat-attachments/"
                                    + str(
                                        attachment_id
                                    )
                                )
                        }
                    },
                    201
                )


            except ValueError as exc:

                json_response(
                    self,
                    {
                        "error":
                            str(exc)
                    },
                    400
                )


            except Exception as exc:

                print(
                    "[Apollo Attachment Upload]",
                    exc
                )

                json_response(
                    self,
                    {
                        "error":
                            str(exc)
                    },
                    500
                )


            return


        # ─────────────────────────────
        # GOOGLE CALENDAR WRITE
        # ─────────────────────────────

        # ─────────────────────────────
        # TASKS
        # ─────────────────────────────

        if self.path == "/api/tasks/create":

            try:

                task = create_task(
                    read_json(
                        self
                    )
                )

                json_response(
                    self,
                    {
                        "ok": True,
                        "task": task
                    },
                    201
                )

            except ValueError as exc:

                json_response(
                    self,
                    {
                        "error":
                            str(exc)
                    },
                    400
                )

            return


        if self.path == "/api/tasks/update":

            try:

                task = update_task(
                    read_json(
                        self
                    )
                )

                json_response(
                    self,
                    {
                        "ok": True,
                        "task": task
                    }
                )

            except ValueError as exc:

                json_response(
                    self,
                    {
                        "error":
                            str(exc)
                    },
                    400
                )

            return


        if self.path == "/api/tasks/delete":

            try:

                data = read_json(
                    self
                )

                result = delete_task(
                    data.get(
                        "task_id"
                    )
                )

                json_response(
                    self,
                    result
                )

            except ValueError as exc:

                json_response(
                    self,
                    {
                        "error":
                            str(exc)
                    },
                    400
                )

            return


        if self.path == "/api/calendar/events/create":

            try:
                data = read_json(self)

                event = (
                    google_calendar_create_event(
                        data
                    )
                )

                json_response(
                    self,
                    {
                        "ok": True,
                        "event": event
                    },
                    201
                )

            except ValueError as exc:
                json_response(
                    self,
                    {
                        "error": str(exc)
                    },
                    400
                )

            except RuntimeError as exc:
                json_response(
                    self,
                    {
                        "error": str(exc)
                    },
                    500
                )

            return


        if self.path == "/api/calendar/events/update":

            try:
                data = read_json(self)

                event_id = str(
                    data.pop(
                        "event_id",
                        ""
                    )
                ).strip()

                scope = str(
                    data.pop(
                        "scope",
                        "single"
                    )
                ).strip()

                series_id = str(
                    data.pop(
                        "series_id",
                        ""
                    )
                ).strip() or None

                event = (
                    google_calendar_update_event(
                        event_id,
                        data,
                        scope=scope,
                        series_id=series_id
                    )
                )

                json_response(
                    self,
                    {
                        "ok": True,
                        "event": event
                    }
                )

            except ValueError as exc:
                json_response(
                    self,
                    {
                        "error": str(exc)
                    },
                    400
                )

            except RuntimeError as exc:
                json_response(
                    self,
                    {
                        "error": str(exc)
                    },
                    500
                )

            return


        if self.path == "/api/calendar/events/delete":

            try:
                data = read_json(self)

                event_id = str(
                    data.get(
                        "event_id",
                        ""
                    )
                ).strip()

                scope = str(
                    data.get(
                        "scope",
                        "single"
                    )
                ).strip()

                series_id = str(
                    data.get(
                        "series_id",
                        ""
                    )
                ).strip() or None

                google_calendar_delete_event(
                    event_id,
                    scope=scope,
                    series_id=series_id
                )

                json_response(
                    self,
                    {
                        "ok": True,
                        "deleted":
                            event_id
                    }
                )

            except ValueError as exc:
                json_response(
                    self,
                    {
                        "error": str(exc)
                    },
                    400
                )

            except RuntimeError as exc:
                json_response(
                    self,
                    {
                        "error": str(exc)
                    },
                    500
                )

            return


        # ─────────────────────────────
        # WORKS IN PROGRESS — EDIT PROJECT
        # ─────────────────────────────

        if self.path == "/api/wip/projects/artwork":

            try:

                project = (
                    update_wip_artwork(
                        self
                    )
                )

                json_response(
                    self,
                    {
                        "ok": True,
                        "project":
                            project
                    }
                )

            except Exception as exc:

                json_response(
                    self,
                    {
                        "error":
                            str(exc)
                    },
                    400
                )

            return



        if self.path == "/api/wip/projects/update":

            try:

                project = (
                    update_wip_project(
                        read_json(
                            self
                        )
                    )
                )

                json_response(
                    self,
                    {
                        "ok": True,
                        "project":
                            project
                    }
                )

            except Exception as exc:

                json_response(
                    self,
                    {
                        "error":
                            str(exc)
                    },
                    400
                )

            return


        if self.path == "/api/wip/projects/delete":

            try:

                data = read_json(
                    self
                )

                result = (
                    delete_wip_project(
                        data.get(
                            "project_id"
                        )
                    )
                )

                json_response(
                    self,
                    result
                )

            except Exception as exc:

                json_response(
                    self,
                    {
                        "error":
                            str(exc)
                    },
                    400
                )

            return


        # ─────────────────────────────
        # WIP — REPLACE AUDIO
        # ─────────────────────────────

        if self.path == "/api/wip/replace/start":

            try:

                result = (
                    wip_replace_start(
                        read_json(
                            self
                        )
                    )
                )

                json_response(
                    self,
                    result,
                    201
                )

            except Exception as exc:

                json_response(
                    self,
                    {
                        "error":
                            str(exc)
                    },
                    400
                )

            return


        parsed_replace = (
            urllib.parse.urlparse(
                self.path
            )
        )

        if (
            parsed_replace.path
            == "/api/wip/replace/chunk"
        ):

            try:

                query = (
                    urllib.parse.parse_qs(
                        parsed_replace.query
                    )
                )

                upload_id = (
                    query.get(
                        "upload_id",
                        [""]
                    )[0]
                )

                offset = int(
                    query.get(
                        "offset",
                        ["0"]
                    )[0]
                )

                result = (
                    wip_replace_chunk(
                        self,
                        upload_id,
                        offset
                    )
                )

                json_response(
                    self,
                    result
                )

            except Exception as exc:

                json_response(
                    self,
                    {
                        "error":
                            str(exc)
                    },
                    400
                )

            return


        if self.path == "/api/wip/replace/finish":

            try:

                data = read_json(
                    self
                )

                project = (
                    wip_replace_finish(
                        data.get(
                            "upload_id"
                        )
                    )
                )

                json_response(
                    self,
                    {
                        "ok": True,
                        "project":
                            project
                    }
                )

            except Exception as exc:

                json_response(
                    self,
                    {
                        "error":
                            str(exc)
                    },
                    400
                )

            return


        # ─────────────────────────────
        # WORKS IN PROGRESS — CHUNKED UPLOAD
        # ─────────────────────────────

        parsed_wip = (
            urllib.parse.urlparse(
                self.path
            )
        )

        wip_route = (
            parsed_wip.path
        )


        if wip_route == "/api/wip/upload/start":

            try:

                data = read_json(
                    self
                )

                result = (
                    wip_upload_start(
                        data
                    )
                )

                json_response(
                    self,
                    result,
                    201
                )

            except Exception as exc:

                json_response(
                    self,
                    {
                        "error":
                            str(exc)
                    },
                    400
                )

            return


        if wip_route == "/api/wip/upload/chunk":

            try:

                query = (
                    urllib.parse.parse_qs(
                        parsed_wip.query
                    )
                )

                upload_id = (
                    query.get(
                        "upload_id",
                        [""]
                    )[0]
                )

                kind = (
                    query.get(
                        "kind",
                        [""]
                    )[0]
                )

                offset = int(
                    query.get(
                        "offset",
                        ["0"]
                    )[0]
                )

                result = (
                    wip_upload_chunk(
                        self,
                        upload_id,
                        kind,
                        offset
                    )
                )

                json_response(
                    self,
                    result
                )

            except Exception as exc:

                json_response(
                    self,
                    {
                        "error":
                            str(exc)
                    },
                    400
                )

            return


        if wip_route == "/api/wip/upload/finish":

            try:

                data = read_json(
                    self
                )

                project = (
                    wip_upload_finish(
                        str(
                            data.get(
                                "upload_id",
                                ""
                            )
                        )
                    )
                )

                json_response(
                    self,
                    {
                        "ok": True,
                        "project":
                            project
                    },
                    201
                )

            except Exception as exc:

                json_response(
                    self,
                    {
                        "error":
                            str(exc)
                    },
                    400
                )

            return


        # ─────────────────────────────
        # WORKS IN PROGRESS — LEGACY UPLOAD
        # ─────────────────────────────

        if self.path == "/api/wip/projects":

            try:

                project = (
                    create_wip_project(
                        self
                    )
                )

                json_response(
                    self,
                    {
                        "ok": True,
                        "project": project
                    },
                    201
                )

            except ValueError as exc:

                json_response(
                    self,
                    {
                        "error":
                            str(exc)
                    },
                    400
                )

            except Exception as exc:

                print(
                    "[Apollo WIP] "
                    f"{exc}"
                )

                json_response(
                    self,
                    {
                        "error":
                            "Could not save project"
                    },
                    500
                )

            return


        # ─────────────────────────────
        # ─────────────────────────────
        # SPOTIFY PLAYBACK CONTROL
        # ─────────────────────────────

        if self.path == "/api/spotify/recent-play":

            try:

                data = read_json(
                    self
                )

                result = (
                    spotify_play_recent_context(
                        data.get(
                            "type"
                        ),
                        data.get(
                            "uri"
                        )
                    )
                )

                json_response(
                    self,
                    result
                )


            except ValueError as exc:

                json_response(
                    self,
                    {
                        "error":
                            str(exc)
                    },
                    400
                )


            except Exception as exc:

                print(
                    "[Apollo Spotify Recent Play] "
                    f"{exc}"
                )

                json_response(
                    self,
                    {
                        "error":
                            str(exc)
                    },
                    500
                )


            return


        if self.path == "/api/spotify/control":

            try:
                data = read_json(self)

                result = spotify_playback_command(
                    data.get("action", ""),
                    data.get("position_ms")
                )

                json_response(
                    self,
                    result
                )

            except ValueError as exc:
                json_response(
                    self,
                    {"error": str(exc)},
                    400
                )

            except Exception as exc:
                json_response(
                    self,
                    {"error": str(exc)},
                    500
                )

            return


        # ─────────────────────────────
        # MUSIC — NATURAL LANGUAGE PLAYBACK
        # ─────────────────────────────

        if self.path == "/api/music/play":

            try:

                data = read_json(self)

                result = (
                    apollo_music_play_request(
                        data.get(
                            "request",
                            ""
                        )
                    )
                )

                json_response(
                    self,
                    result
                )

            except ValueError as exc:

                json_response(
                    self,
                    {
                        "error": str(exc)
                    },
                    400
                )

            except Exception as exc:

                print(
                    "[Apollo Music] "
                    f"{exc}"
                )

                json_response(
                    self,
                    {
                        "error": str(exc)
                    },
                    500
                )

            return


        # ─────────────────────────────
        # CLIENT CONTEXT
        # ─────────────────────────────

        if self.path == "/api/client-context":

            try:
                data = read_json(self)

            except Exception:
                json_response(
                    self,
                    {"error": "Invalid JSON"},
                    400
                )
                return

            time_zone = str(
                data.get("time_zone", "")
            ).strip()

            utc_offset = data.get(
                "utc_offset_minutes"
            )

            if not time_zone:

                json_response(
                    self,
                    {
                        "error":
                            "Missing device timezone"
                    },
                    400
                )
                return

            try:

                zone = ZoneInfo(
                    time_zone
                )

                utc_offset = int(
                    utc_offset
                )

                expected_offset = int(
                    datetime.now(
                        zone
                    ).utcoffset().total_seconds()
                    // 60
                )

            except Exception:

                json_response(
                    self,
                    {
                        "error":
                            "Invalid device timezone"
                    },
                    400
                )
                return

            if (
                utc_offset < -840
                or utc_offset > 840
                or utc_offset != expected_offset
            ):

                json_response(
                    self,
                    {
                        "error":
                            "Device timezone and UTC offset do not match"
                    },
                    400
                )
                return

            conn = db()

            values = {
                "time_zone":
                    time_zone,

                "utc_offset_minutes":
                    str(
                        utc_offset
                    ),

                "client_context_updated_at":
                    datetime.now(
                        timezone.utc
                    ).isoformat()
            }

            latitude = data.get(
                "latitude"
            )

            longitude = data.get(
                "longitude"
            )

            if (
                latitude is not None
                and longitude is not None
            ):

                try:

                    latitude = float(
                        latitude
                    )

                    longitude = float(
                        longitude
                    )

                    if not (
                        -90.0
                        <= latitude
                        <= 90.0
                        and -180.0
                        <= longitude
                        <= 180.0
                    ):
                        raise ValueError(
                            "Coordinates out of range"
                        )

                    values[
                        "device_latitude"
                    ] = (
                        f"{latitude:.5f}"
                    )

                    values[
                        "device_longitude"
                    ] = (
                        f"{longitude:.5f}"
                    )

                    values[
                        "device_location_updated_at"
                    ] = (
                        datetime.now(
                            timezone.utc
                        ).isoformat()
                    )

                except (
                    TypeError,
                    ValueError
                ):
                    pass

            for key, value in values.items():

                conn.execute("""
                    INSERT INTO app_state (
                        key,
                        value
                    )
                    VALUES (?, ?)
                    ON CONFLICT(key)
                    DO UPDATE SET
                        value = excluded.value
                """, (
                    key,
                    value
                ))

            conn.commit()
            conn.close()

            json_response(
                self,
                {
                    "ok": True,
                    "time_zone":
                        time_zone,
                    "utc_offset_minutes":
                        utc_offset
                }
            )
            return

        # CREATE CHAT
        # ─────────────────────────────

        if self.path == "/api/chats":

            conn = db()

            cursor = conn.execute(
                "INSERT INTO chats (title) VALUES (?)",
                ("New Chat",)
            )

            chat_id = cursor.lastrowid

            conn.commit()
            conn.close()

            json_response(
                self,
                {
                    "id": chat_id,
                    "title": "New Chat"
                },
                201
            )
            return

        # ─────────────────────────────
        # SEND MESSAGE
        # ─────────────────────────────

        if (
            self.path.startswith("/api/chats/")
            and self.path.endswith("/messages")
        ):

            try:
                parts = self.path.strip("/").split("/")
                chat_id = int(parts[2])

            except (ValueError, IndexError):
                json_response(
                    self,
                    {"error": "Invalid chat ID"},
                    400
                )
                return

            try:
                data = read_json(self)

            except Exception:
                json_response(
                    self,
                    {"error": "Invalid JSON"},
                    400
                )
                return

            user_message = data.get(
                "content",
                ""
            ).strip()

            retry_message = bool(
                data.get("retry", False)
            )


            attachment_ids = (
                data.get(
                    "attachment_ids",
                    []
                )
            )


            if not isinstance(
                attachment_ids,
                list
            ):

                attachment_ids = []


            clean_attachment_ids = []


            for item in attachment_ids:

                try:

                    clean_attachment_ids.append(
                        int(item)
                    )

                except Exception:

                    pass


            attachment_ids = (
                clean_attachment_ids
            )

            if not user_message:
                json_response(
                    self,
                    {"error": "Message is empty"},
                    400
                )
                return

            conn = db()

            chat = conn.execute(
                "SELECT id FROM chats WHERE id = ?",
                (chat_id,)
            ).fetchone()

            if not chat:
                conn.close()

                json_response(
                    self,
                    {"error": "Chat not found"},
                    404
                )
                return

            # Save user message.

            # APOLLO_RETRY_MESSAGE
            # Retry keeps the existing user message and removes
            # the previous assistant response.

            if retry_message:

                # Rewind conversation to the user message being retried.
                # Delete that response and everything after it.

                conn.execute("""
                    DELETE FROM messages
                    WHERE chat_id = ?
                      AND id > (
                          SELECT id
                          FROM messages
                          WHERE chat_id = ?
                            AND role = 'user'
                            AND content = ?
                          ORDER BY id DESC
                          LIMIT 1
                      )
                """, (
                    chat_id,
                    chat_id,
                    user_message
                ))

            else:

                cursor = conn.execute("""
                    INSERT INTO messages (
                        chat_id,
                        role,
                        content
                    )
                    VALUES (?, 'user', ?)
                """, (
                    chat_id,
                    user_message
                ))


                user_message_id = (
                    cursor.lastrowid
                )


                if attachment_ids:

                    placeholders = ",".join(
                        "?"
                        for _ in attachment_ids
                    )


                    conn.execute(
                        f"""
                        UPDATE message_attachments
                        SET message_id = ?
                        WHERE chat_id = ?
                          AND message_id IS NULL
                          AND id IN (
                              {placeholders}
                          )
                        """,
                        (
                            user_message_id,
                            chat_id,
                            *attachment_ids
                        )
                    )

            # Retrieve conversation history,
            # including attachments from earlier turns.

            history_rows = conn.execute("""
                SELECT id, role, content
                FROM messages
                WHERE chat_id = ?
                ORDER BY id ASC
            """, (
                chat_id,
            )).fetchall()


            attachment_rows = conn.execute("""
                SELECT
                    message_id,
                    filename,
                    file_path,
                    mime_type
                FROM message_attachments
                WHERE chat_id = ?
                  AND message_id IS NOT NULL
                ORDER BY id ASC
            """, (
                chat_id,
            )).fetchall()


            attachments_by_message = {}


            for attachment in attachment_rows:

                attachments_by_message.setdefault(
                    attachment["message_id"],
                    []
                ).append(
                    attachment
                )


            # Keep the existing attachment-action routers working
            # with attachments from the message just sent.
            current_attachments = (
                attachments_by_message.get(
                    user_message_id,
                    []
                )
            )


            conn.commit()
            conn.close()


            # APOLLO_CONTEXT_WINDOW_V1
            # Keep full chat history in the database/UI, but only send a
            # bounded recent window upstream so requests never grow forever.
            MAX_HISTORY_MESSAGES = 30
            MAX_HISTORY_CHARS = 100000

            bounded_history = []
            history_chars = 0

            for _row in reversed(history_rows):
                _content = (_row["content"] or "")
                _size = len(_content)

                if bounded_history and (
                    len(bounded_history) >= MAX_HISTORY_MESSAGES
                    or history_chars + _size > MAX_HISTORY_CHARS
                ):
                    break

                bounded_history.append(_row)
                history_chars += _size

            history_rows = list(reversed(bounded_history))

            messages = []


            for row in history_rows:

                content = (
                    row["content"]
                    or ""
                )


                attachments = (
                    attachments_by_message.get(
                        row["id"],
                        []
                    )
                )


                if attachments:

                    attachment_context = [
                        "",
                        "",
                        (
                            "FILES ATTACHED TO THIS "
                            "MESSAGE IN THIS CONVERSATION:"
                        )
                    ]


                    for attachment in attachments:

                        attachment_context.append(
                            (
                                "- "
                                + attachment["filename"]
                                + " | "
                                + attachment["mime_type"]
                                + " | local path: "
                                + attachment["file_path"]
                            )
                        )


                    attachment_context.append(
                        (
                            "These files remain available "
                            "throughout this chat. Inspect them "
                            "when the user's current request "
                            "refers back to them or when they "
                            "are otherwise relevant."
                        )
                    )


                    content += (
                        "\n".join(
                            attachment_context
                        )
                    )


                messages.append({
                    "role":
                        row["role"],

                    "content":
                        content
                })


            # APOLLO_CLIENT_TIME
            # The browser is authoritative for the user's
            # current local time and timezone.
            client_context = data.get(
                "client_context",
                {}
            )

            if isinstance(client_context, dict):

                local_time = str(
                    client_context.get(
                        "local_time",
                        ""
                    )
                ).strip()

                time_zone = str(
                    client_context.get(
                        "time_zone",
                        ""
                    )
                ).strip()

                utc_offset = client_context.get(
                    "utc_offset_minutes"
                )

                if local_time or time_zone:

                    time_context = (
                        "CURRENT USER DEVICE CONTEXT:\n"
                        f"Local date/time: {local_time}\n"
                        f"Timezone: {time_zone}\n"
                        f"UTC offset in minutes: {utc_offset}\n\n"
                        "Treat the user's device time as the "
                        "authoritative current local time for "
                        "this request. Do not infer the user's "
                        "current location or timezone from old "
                        "profile information. If the user asks "
                        "what time/day it is or asks for a "
                        "time-sensitive plan, use this context."
                    )

                    messages.insert(
                        0,
                        {
                            "role": "system",
                            "content": time_context
                        }
                    )


            # =====================================================
            # APOLLO WHOOP QUESTION CONTEXT V1
            # =====================================================
            #
            # The Home WHOOP card may attach its current snapshot
            # to one user question. Keep this separate from the
            # visible user message so chat history stays clean.
            #

            if isinstance(client_context, dict):

                whoop_context = (
                    client_context.get(
                        "whoop_context"
                    )
                )

                if isinstance(
                    whoop_context,
                    dict
                ):

                    whoop_system_context = (
                        "CURRENT WHOOP CONTEXT:\n"
                        + json.dumps(
                            whoop_context,
                            ensure_ascii=False,
                            indent=2
                        )
                        + "\n\n"
                        "Use these live WHOOP values when they are "
                        "relevant to the user's current question. "
                        "Do not invent missing measurements. "
                        "Interpret the data practically and in context. "
                        "For training questions, consider recovery, "
                        "sleep, strain, HRV, resting heart rate, and "
                        "the supplied WHOOP interpretation together."
                    )

                    messages.insert(
                        0,
                        {
                            "role":
                                "system",

                            "content":
                                whoop_system_context
                        }
                    )


            # ─────────────────────────────
            # APOLLO NORMAL CHAT BEHAVIOR
            # ─────────────────────────────

            messages.insert(
                0,
                {
                    "role": "system",
                    "content": APOLLO_PERSONALITY_PROMPT
                }
            )


            # ─────────────────────────────
            # APOLLO SURFACE CONTEXT
            # ─────────────────────────────

            surface = (
                str(
                    client_context.get(
                        "surface",
                        ""
                    )
                ).strip().lower()
                if isinstance(
                    client_context,
                    dict
                )
                else ""
            )


            # Music Presence is intentionally action-first.
            #
            # Example:
            #   "my ug rnb playlist"
            #
            # means:
            #   play my ug rnb playlist
            #
            # because the user said it from the Music surface.
            if apollo_music_action_requested(
                user_message,
                surface=surface
            ):

                try:

                    music_request = (
                        user_message
                    )


                    # First: literal / near-literal names from
                    # the user's REAL Spotify playlists.
                    resolved_playlist = (
                        apollo_music_match_personal_playlist(
                            user_message
                        )
                    )


                    # Second: personal semantic aliases such as
                    # "my main playlist" -> "₄".
                    if not resolved_playlist:

                        resolved_playlist = (
                            apollo_music_resolve_personal_alias(
                                user_message
                            )
                        )


                    if resolved_playlist:

                        # Alias is already resolved to an EXACT real
                        # Spotify playlist name. Do not send it through
                        # the natural-language parser a second time.
                        payload = {
                            "type": "playlist",
                            "query":
                                resolved_playlist,
                            "title": "",
                            "artist": "",
                            "shuffle": False
                        }


                        result = subprocess.run(
                            [
                                SPOTIFY_PYTHON,
                                SPOTIFY_TOOL,
                                "play-request",
                                json.dumps(
                                    payload,
                                    ensure_ascii=False
                                )
                            ],
                            capture_output=True,
                            text=True,
                            timeout=30
                        )


                        if result.returncode != 0:

                            raise RuntimeError(
                                result.stderr.strip()
                                or result.stdout.strip()
                                or "Spotify could not start playback"
                            )


                        try:

                            spotify_result = json.loads(
                                result.stdout.strip()
                                or "{}"
                            )

                        except Exception:

                            spotify_result = {
                                "ok": True,
                                "type": "playlist",
                                "name":
                                    resolved_playlist
                            }


                        music_result = {
                            "ok": True,
                            "intent": payload,
                            "spotify":
                                spotify_result,
                            "playback":
                                get_now_playing()
                        }


                    else:

                        music_result = (
                            apollo_music_play_request(
                                music_request
                            )
                        )


                    spotify_result = (
                        music_result.get(
                            "spotify"
                        )
                        or {}
                    )

                    playback = (
                        music_result.get(
                            "playback"
                        )
                        or {}
                    )


                    result_type = str(
                        spotify_result.get(
                            "type"
                        )
                        or ""
                    ).strip().lower()


                    context_name = str(
                        spotify_result.get(
                            "name"
                        )
                        or ""
                    ).strip()


                    # For playlists / albums / artists, confirm
                    # the actual Spotify context Apollo selected.
                    if (
                        result_type
                        in {
                            "playlist",
                            "album",
                            "artist"
                        }
                        and context_name
                    ):

                        music_reply = (
                            f"Playing — {context_name}."
                        )


                    elif result_type == "liked":

                        music_reply = (
                            "Playing your Liked Songs."
                        )


                    else:

                        title = str(
                            playback.get(
                                "title"
                            )
                            or ""
                        ).strip()


                        artist_text = str(
                            playback.get(
                                "artists"
                            )
                            or ""
                        ).strip()


                        if title:

                            music_reply = (
                                f"Playing — {title}"
                            )

                            if artist_text:

                                music_reply += (
                                    f" by {artist_text}."
                                )

                            else:

                                music_reply += "."

                        else:

                            music_reply = (
                                "Playing it now."
                            )


                    apollo_send_direct_sse(
                        self,
                        chat_id,
                        music_reply
                    )

                    return


                except Exception as error:

                    print(
                        "[Apollo Music Surface] "
                        f"{error}"
                    )


                    apollo_send_direct_sse(
                        self,
                        chat_id,
                        (
                            "I couldn't play that. "
                            + str(error)
                        )
                    )

                    return


            # =====================================================
            # APOLLO ATTACHMENT TASK ACTIONS V1
            # =====================================================
            #
            # Attachment-based task requests need vision/file
            # understanding BEFORE the normal text-only Task router.
            #

            if (
                current_attachments
                and apollo_attachment_task_request(
                    user_message
                )
            ):

                apollo_open_sse(
                    self
                )

                try:

                    apollo_send_status_sse(
                        self,
                        "Reading attachment…"
                    )

                    extracted_tasks = (
                        apollo_extract_tasks_from_attachments(
                            user_message,
                            current_attachments,
                            client_context
                        )
                    )


                    if extracted_tasks:

                        apollo_send_status_sse(
                            self,
                            "Creating tasks…"
                        )

                        created_tasks = []


                        for task_data in extracted_tasks:

                            created_tasks.append(
                                create_task(
                                    task_data
                                )
                            )


                        last_created = (
                            created_tasks[-1]
                        )


                        task_chat_state_set(
                            chat_id,
                            last_task_id=
                                last_created["id"],
                            pending_action=None,
                            pending_data=None,
                            preserve_last=False
                        )


                        if len(
                            created_tasks
                        ) == 1:

                            attachment_task_reply = (
                                "Added — "
                                + task_chat_task_summary(
                                    created_tasks[0]
                                )
                                + "."
                            )

                        else:

                            lines = [
                                (
                                    "Added "
                                    + str(
                                        len(created_tasks)
                                    )
                                    + " tasks:"
                                )
                            ]


                            for task in created_tasks:

                                lines.append(
                                    "• "
                                    + task_chat_task_summary(
                                        task
                                    )
                                )


                            attachment_task_reply = (
                                "\n".join(
                                    lines
                                )
                            )


                        apollo_finish_direct_sse(
                            self,
                            chat_id,
                            attachment_task_reply
                        )

                        return


                    apollo_finish_direct_sse(
                        self,
                        chat_id,
                        (
                            "I can see the attachments, "
                            "but I couldn't confidently identify "
                            "any clear tasks to add."
                        )
                    )

                    return


                except Exception as error:

                    print(
                        "[Apollo Attachment Tasks] "
                        f"{error}"
                    )


                    apollo_finish_direct_sse(
                        self,
                        chat_id,
                        (
                            "I could read the attachments, "
                            "but I couldn't turn them into tasks. "
                            "Try sending them again."
                        )
                    )

                    return


            # =====================================================
            # APOLLO ATTACHMENT CALENDAR ACTIONS V1
            # =====================================================
            #
            # Read image/file content BEFORE the old text-only
            # Calendar router. Supports multiple events, such as
            # outbound + return flights in separate screenshots.
            #

            if current_attachments:

                try:

                    attachment_calendar = (
                        apollo_extract_calendar_events_from_attachments(
                            user_message,
                            current_attachments,
                            client_context
                        )
                    )

                except Exception as error:

                    print(
                        "[Apollo Attachment Calendar] "
                        f"{error}"
                    )

                    attachment_calendar = {
                        "calendar_request":
                            False,

                        "events":
                            [],

                        "reply":
                            None
                    }


                if attachment_calendar.get(
                    "calendar_request"
                ):

                    apollo_open_sse(
                        self
                    )


                    extracted_events = (
                        attachment_calendar.get(
                            "events",
                            []
                        )
                    )


                    if not extracted_events:

                        apollo_finish_direct_sse(
                            self,
                            chat_id,
                            (
                                attachment_calendar.get(
                                    "reply"
                                )
                                or (
                                    "I can see the attachment, "
                                    "but I couldn't read enough "
                                    "event details to add it safely."
                                )
                            )
                        )

                        return


                    try:

                        apollo_send_status_sse(
                            self,
                            "Reading attachment…"
                        )

                        created_events = []


                        for event_data in extracted_events:

                            apollo_send_status_sse(
                                self,
                                "Adding to calendar…"
                            )

                            created_events.append(
                                google_calendar_create_event(
                                    event_data
                                )
                            )


                        if created_events:

                            try:

                                calendar_last_event_set(
                                    chat_id,
                                    created_events[-1]
                                )

                            except Exception as error:

                                print(
                                    "[Apollo Attachment Calendar] "
                                    "Could not save last event: "
                                    f"{error}"
                                )


                        attachment_calendar_reply = (
                            apollo_attachment_calendar_reply(
                                created_events,
                                extracted_events
                            )
                        )


                        apollo_finish_direct_sse(
                            self,
                            chat_id,
                            attachment_calendar_reply
                        )

                        return


                    except Exception as error:

                        print(
                            "[Apollo Attachment Calendar] "
                            f"Create failed: {error}"
                        )


                        apollo_finish_direct_sse(
                            self,
                            chat_id,
                            (
                                "I could read the attachment, "
                                "but I couldn't add the event "
                                "to Google Calendar. "
                                + str(error)
                            )
                        )

                        return


            # ─────────────────────────────
            # APOLLO ACTION ROUTER V1
            # Tasks first for homework / reminders / todos.
            # Calendar second for events / meetings / schedule.
            # ─────────────────────────────

            task_stream_open = False


            def task_status(
                status
            ):
                nonlocal task_stream_open

                if not task_stream_open:

                    apollo_open_sse(
                        self
                    )

                    task_stream_open = True

                apollo_send_status_sse(
                    self,
                    status
                )


            try:

                task_reply = (
                    apollo_task_chat(
                        chat_id,
                        user_message,
                        client_context,
                        status_callback=
                            task_status
                    )
                )

            except Exception as error:

                print(
                    "[Apollo Tasks Chat] "
                    f"Handler failed: {error}"
                )

                task_reply = None


            if task_reply is not None:

                if task_stream_open:

                    apollo_finish_direct_sse(
                        self,
                        chat_id,
                        task_reply
                    )

                else:

                    apollo_send_direct_sse(
                        self,
                        chat_id,
                        task_reply
                    )

                return


            if task_stream_open:

                # Defensive fallback:
                # a stream should only open after a confirmed
                # Task intent, which should always produce a reply.
                apollo_finish_direct_sse(
                    self,
                    chat_id,
                    "I couldn't finish that task action."
                )

                return


            try:

                calendar_reply = (
                    apollo_calendar_chat(
                        chat_id,
                        user_message,
                        client_context
                    )
                )

            except Exception as error:

                print(
                    "[Apollo Calendar Chat] "
                    f"Handler failed: {error}"
                )

                calendar_reply = None


            if calendar_reply is not None:

                apollo_send_direct_sse(
                    self,
                    chat_id,
                    calendar_reply
                )

                return


            # ─────────────────────────────
            # APOLLO PERSONAL CONTEXT PLANNER V1
            # ─────────────────────────────
            #
            # Explicit Task / Calendar actions have already been
            # handled above. For ordinary conversation, Apollo now
            # decides semantically which live personal sources would
            # improve the answer.

            try:

                context_plan = (
                    apollo_context_planner(
                        messages,
                        user_message,
                        client_context
                    )
                )


                live_context = (
                    apollo_fetch_planned_context(
                        context_plan
                    )
                )


                if live_context:

                    personal_context_prompt = (
                        "APOLLO LIVE PERSONAL CONTEXT:\n"
                        + json.dumps(
                            live_context,
                            ensure_ascii=False,
                            indent=2
                        )
                        + "\n\n"
                        "Apollo selected these live personal sources "
                        "because they are relevant to the user's current "
                        "request. Treat successfully retrieved data as "
                        "authoritative current personal context. "
                        "Reason across sources when useful instead of "
                        "treating Calendar, Tasks and WHOOP as isolated "
                        "features. "
                        "Do not ask the user to repeat schedule, task, "
                        "or WHOOP information that is already present "
                        "here. "
                        "Use only the parts that actually improve the "
                        "answer; do not mechanically list everything. "
                        "If a selected source has an error, do not invent "
                        "its contents. "
                        "Do not mention the internal context planner, "
                        "routing, source selection, JSON, or backend "
                        "implementation to the user."
                    )


                    messages.insert(
                        0,
                        {
                            "role": "system",
                            "content":
                                personal_context_prompt
                        }
                    )


            except Exception as error:

                # Context planning must never break ordinary chat.
                print(
                    "[Apollo Context Planner] "
                    f"Failed safely: {error}"
                )


            # ─────────────────────────────
            # APOLLO NATURAL SILENCE V1
            # ─────────────────────────────
            #
            # Task / Calendar actions already had first priority.
            # Only ordinary conversation reaches this point.

            if not apollo_should_reply_semantically(
                messages,
                user_message
            ):

                conn = db()

                conn.execute("""
                    UPDATE chats
                    SET updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (
                    chat_id,
                ))

                conn.commit()
                conn.close()


                self.send_response(
                    204
                )

                self.send_header(
                    "Cache-Control",
                    "no-cache, no-store"
                )

                self.end_headers()

                return


            # Stream Hermes response.

            try:
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "text/event-stream; charset=utf-8"
                )
                self.send_header(
                    "Cache-Control",
                    "no-cache, no-store"
                )
                self.send_header(
                    "Connection",
                    "close"
                )
                self.end_headers()

                assistant_parts = []

                for content in stream_hermes(messages):

                    assistant_parts.append(content)

                    event = json.dumps({
                        "type": "content",
                        "content": content
                    })

                    self.wfile.write(
                        f"data: {event}\n\n".encode("utf-8")
                    )
                    self.wfile.flush()

                assistant_message = "".join(
                    assistant_parts
                ).strip()

            except urllib.error.HTTPError as error:

                error_body = error.read().decode(
                    "utf-8",
                    errors="replace"
                )

                try:
                    event = json.dumps({
                        "type": "error",
                        "error": error_body
                    })

                    self.wfile.write(
                        f"data: {event}\n\n".encode("utf-8")
                    )
                    self.wfile.flush()

                except Exception:
                    pass

                return

            except Exception as error:

                print(f"[Apollo] Streaming error: {error}")

                try:
                    event = json.dumps({
                        "type": "error",
                        "error": str(error)
                    })

                    self.wfile.write(
                        f"data: {event}\n\n".encode("utf-8")
                    )
                    self.wfile.flush()

                except Exception:
                    pass

                return

            # Save Apollo response.

            conn = db()

            cursor = conn.execute("""
                INSERT INTO messages (
                    chat_id,
                    role,
                    content
                )
                VALUES (?, 'assistant', ?)
            """, (
                chat_id,
                assistant_message
            ))

            assistant_message_id = (
                cursor.lastrowid
            )

            (
                assistant_message,
                assistant_attachments
            ) = apollo_capture_generated_images(
                conn,
                chat_id,
                assistant_message_id,
                assistant_message
            )

            conn.execute("""
                UPDATE messages
                SET content = ?
                WHERE id = ?
            """, (
                assistant_message,
                assistant_message_id
            ))

            conn.execute("""
                UPDATE chats
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (chat_id,))

            # Get the complete conversation.

            history_rows = conn.execute("""
                SELECT role, content
                FROM messages
                WHERE chat_id = ?
                ORDER BY id ASC
            """, (chat_id,)).fetchall()

            history = [
                {
                    "role": row["role"],
                    "content": row["content"]
                }
                for row in history_rows
            ]

            # Generate a proper title after the first exchange.

            message_count = len(history)

            if message_count == 2:

                title = generate_chat_title(history)

                conn.execute("""
                    UPDATE chats
                    SET title = ?
                    WHERE id = ?
                """, (
                    title,
                    chat_id
                ))

            conn.commit()
            conn.close()

            event = json.dumps({
                "type": "done",
                "message": {
                    "role": "assistant",
                    "content": assistant_message,
                    "attachments": assistant_attachments
                }
            })

            self.wfile.write(
                f"data: {event}\n\n".encode("utf-8")
            )
            self.wfile.flush()

            return

        json_response(
            self,
            {"error": "Not found"},
            404
        )



    def do_PATCH(self):

        # Tailscale Serve mounted at /api strips that prefix.
        if not self.path.startswith("/api"):
            self.path = "/api" + self.path

        if self.path.startswith("/api/chats/"):

            try:
                parts = self.path.strip("/").split("/")

                if len(parts) != 3:
                    raise ValueError

                chat_id = int(parts[2])

            except (ValueError, IndexError):
                json_response(
                    self,
                    {"error": "Invalid chat ID"},
                    400
                )
                return

            try:
                data = read_json(self)

            except Exception:
                json_response(
                    self,
                    {"error": "Invalid JSON"},
                    400
                )
                return

            title = str(
                data.get("title", "")
            ).strip()

            if not title:
                json_response(
                    self,
                    {"error": "Title is empty"},
                    400
                )
                return

            # Keep titles reasonable.
            title = title[:120]

            conn = db()

            chat = conn.execute(
                "SELECT id FROM chats WHERE id = ?",
                (chat_id,)
            ).fetchone()

            if not chat:
                conn.close()

                json_response(
                    self,
                    {"error": "Chat not found"},
                    404
                )
                return

            conn.execute("""
                UPDATE chats
                SET title = ?
                WHERE id = ?
            """, (
                title,
                chat_id
            ))

            conn.commit()
            conn.close()

            json_response(
                self,
                {
                    "id": chat_id,
                    "title": title
                }
            )
            return

        json_response(
            self,
            {"error": "Not found"},
            404
        )

    def do_DELETE(self):

        # Tailscale Serve mounted at /api strips that prefix.
        if not self.path.startswith("/api"):
            self.path = "/api" + self.path

        if self.path.startswith("/api/chats/"):

            try:
                parts = self.path.strip("/").split("/")

                if len(parts) != 3:
                    raise ValueError

                chat_id = int(parts[2])

            except (ValueError, IndexError):
                json_response(
                    self,
                    {"error": "Invalid chat ID"},
                    400
                )
                return

            conn = db()

            chat = conn.execute(
                "SELECT id FROM chats WHERE id = ?",
                (chat_id,)
            ).fetchone()

            if not chat:
                conn.close()

                json_response(
                    self,
                    {"error": "Chat not found"},
                    404
                )
                return

            # Explicitly remove messages first so this works
            # even if SQLite foreign-key cascading is disabled.
            conn.execute(
                "DELETE FROM messages WHERE chat_id = ?",
                (chat_id,)
            )

            conn.execute(
                "DELETE FROM chats WHERE id = ?",
                (chat_id,)
            )

            conn.commit()
            conn.close()

            json_response(
                self,
                {
                    "deleted": True,
                    "id": chat_id
                }
            )
            return

        json_response(
            self,
            {"error": "Not found"},
            404
        )


if __name__ == "__main__":

    init_db()

    server = ThreadingHTTPServer(
        ("127.0.0.1", 8765),
        ApolloHandler
    )

    print(
        "Apollo backend running on "
        "127.0.0.1:8765"
    )

    server.serve_forever()
