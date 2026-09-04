"""Apollo's persistent automation and notification subsystem.

This module deliberately contains the lifecycle, persistence, scheduling and
condition semantics in one place.  It accepts small provider callbacks from
the existing Apollo server rather than importing the server (which keeps it
testable and avoids a second backend).
"""

import json
import sqlite3
import threading
import time
import uuid

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


AUTOMATION_TYPES = {
    "one_time",
    "recurring_schedule",
    "condition_once",
    "condition_recurring",
    "relative_event",
}

AUTOMATION_STATUSES = {"active", "paused", "completed", "failed"}

CONDITION_SOURCES = {
    "whoop",
    "calendar",
    "tasks",
    "travel",
    "canvas",
    "email",
}

SOURCE_INTERVAL_SECONDS = {
    "whoop": 30 * 60,
    "calendar": 5 * 60,
    "tasks": 10 * 60,
    "travel": 10 * 60,
    "canvas": 20 * 60,
    "email": 15 * 60,
}


def utc_now():
    return datetime.now(timezone.utc)


def iso(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def parse_iso(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def json_value(value, fallback):
    if not value:
        return fallback
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return fallback
    return parsed


def valid_deep_link(value):
    value = str(value or "/").strip()
    if not value.startswith("/") or value.startswith("//") or "\x00" in value:
        return "/"
    return value[:500]


def row_to_automation(row):
    result = dict(row)
    for key in ("trigger", "schedule", "condition", "action", "recurrence", "context"):
        result[key] = json_value(result.get(key), {})
    result["enabled"] = result["status"] == "active"
    return result


def init_automation_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS automations (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            instruction TEXT NOT NULL,
            type TEXT NOT NULL,
            trigger TEXT NOT NULL DEFAULT '{}',
            schedule TEXT NOT NULL DEFAULT '{}',
            condition TEXT NOT NULL DEFAULT '{}',
            action TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            next_run_at TEXT,
            last_checked_at TEXT,
            last_triggered_at TEXT,
            completed_at TEXT,
            recurrence TEXT NOT NULL DEFAULT '{}',
            timezone TEXT NOT NULL DEFAULT 'UTC',
            source TEXT,
            context TEXT NOT NULL DEFAULT '{}',
            notification_destination TEXT NOT NULL DEFAULT '/',
            failure_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            condition_active INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS automations_due_idx
        ON automations(status, next_run_at)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id TEXT PRIMARY KEY,
            endpoint TEXT NOT NULL UNIQUE,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            user_agent TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_success_at TEXT,
            last_error TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            category TEXT NOT NULL,
            deep_link TEXT NOT NULL DEFAULT '/',
            automation_id TEXT,
            payload TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            read_at TEXT,
            delivery_state TEXT NOT NULL DEFAULT 'pending',
            FOREIGN KEY(automation_id) REFERENCES automations(id)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS notifications_created_idx
        ON notifications(created_at DESC)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notification_preferences (
            category TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS automation_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    now = iso(utc_now())
    for category in ("master", "calendar", "tasks", "debrief", "whoop", "travel", "automations", "sound"):
        conn.execute("""
            INSERT OR IGNORE INTO notification_preferences(category, enabled, updated_at)
            VALUES (?, ?, ?)
        """, (category, 1 if category in {"master", "automations"} else 0, now))


def validate_condition(condition):
    if not isinstance(condition, dict):
        raise ValueError("Automation conditions must be structured data")
    source = str(condition.get("source", "")).strip().lower()
    if source not in CONDITION_SOURCES:
        raise ValueError("Unsupported automation condition source")
    kind = str(condition.get("kind", "")).strip().lower()
    allowed = {
        "whoop": {"threshold"},
        "calendar": {"event_approaching", "event_match", "event_changed"},
        "tasks": {"due_soon", "overdue", "completed", "status_changed"},
        "travel": {"flight_changed", "departure_approaching"},
        "canvas": {"grade_posted", "teacher_comment", "assignment_changed"},
        "email": {"message_match"},
    }
    if kind not in allowed[source]:
        raise ValueError("Unsupported automation condition type")
    return {**condition, "source": source, "kind": kind}


def next_weekly_run(schedule, tz_name, now=None):
    now = now or utc_now()
    tz = ZoneInfo(tz_name)
    local_now = now.astimezone(tz)
    weekday = int(schedule.get("weekday", 0))
    hour = int(schedule.get("hour", 9))
    minute = int(schedule.get("minute", 0))
    if not 0 <= weekday <= 6 or not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("Invalid recurring schedule")
    days = (weekday - local_now.weekday()) % 7
    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=days)
    if candidate <= local_now:
        candidate += timedelta(days=7)
    return candidate.astimezone(timezone.utc)


class AutomationEngine:
    """One durable worker loop for every persisted Apollo automation."""

    def __init__(self, db_path, *, condition_provider, push_sender, timezone_provider, default_provider=None):
        self.db_path = db_path
        self.condition_provider = condition_provider
        self.push_sender = push_sender
        self.timezone_provider = timezone_provider
        self.default_provider = default_provider
        self._stop = threading.Event()
        self._thread = None

    def connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self):
        conn = self.connection()
        init_automation_schema(conn)
        conn.commit()
        conn.close()

    def start(self):
        self.initialize()
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_forever, name="apollo-automation-worker", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run_forever(self):
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception as error:
                print(f"[Apollo Automations] scheduler error: {error}")
            self._stop.wait(30)

    def preferences(self):
        conn = self.connection()
        rows = conn.execute("SELECT category, enabled FROM notification_preferences").fetchall()
        conn.close()
        return {row["category"]: bool(row["enabled"]) for row in rows}

    def update_preferences(self, values):
        allowed = {"master", "calendar", "tasks", "debrief", "whoop", "travel", "automations", "sound"}
        now = iso(utc_now())
        conn = self.connection()
        for category, enabled in values.items():
            if category in allowed:
                conn.execute("""
                    INSERT INTO notification_preferences(category, enabled, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(category) DO UPDATE SET enabled = excluded.enabled, updated_at = excluded.updated_at
                """, (category, 1 if bool(enabled) else 0, now))
        conn.commit()
        conn.close()
        return self.preferences()

    def create(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("Invalid automation")
        kind = str(payload.get("type", "")).strip()
        if kind not in AUTOMATION_TYPES:
            raise ValueError("Unsupported automation type")
        title = str(payload.get("title", "")).strip()[:240]
        instruction = str(payload.get("instruction", title)).strip()[:2000]
        if not title or not instruction:
            raise ValueError("Automation title and instruction are required")
        tz_name = str(payload.get("timezone") or self.timezone_provider() or "UTC").strip()
        try:
            ZoneInfo(tz_name)
        except Exception:
            raise ValueError("Invalid automation timezone")
        schedule = payload.get("schedule") if isinstance(payload.get("schedule"), dict) else {}
        condition = payload.get("condition") if isinstance(payload.get("condition"), dict) else {}
        if kind in {"condition_once", "condition_recurring", "relative_event"}:
            condition = validate_condition(condition)
        now = utc_now()
        if kind == "one_time":
            next_run = parse_iso(schedule.get("at"))
            if not next_run:
                raise ValueError("One-time automations need a scheduled time")
        elif kind == "recurring_schedule":
            next_run = next_weekly_run(schedule, tz_name, now)
        else:
            next_run = now
        action = payload.get("action") if isinstance(payload.get("action"), dict) else {}
        action = {
            "title": str(action.get("title") or title)[:240],
            "body": str(action.get("body") or instruction)[:500],
            "category": str(action.get("category") or "automations")[:40],
            "deep_link": valid_deep_link(action.get("deep_link") or payload.get("notification_destination") or "/"),
        }
        automation_id = str(uuid.uuid4())
        created_at = iso(now)
        conn = self.connection()
        conn.execute("""
            INSERT INTO automations (
                id, title, instruction, type, trigger, schedule, condition, action, status,
                created_at, next_run_at, recurrence, timezone, source, context,
                notification_destination, failure_count, condition_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, 0, 0)
        """, (
            automation_id, title, instruction, kind,
            json.dumps(payload.get("trigger") or {}, ensure_ascii=False),
            json.dumps(schedule, ensure_ascii=False), json.dumps(condition, ensure_ascii=False),
            json.dumps(action, ensure_ascii=False), created_at, iso(next_run),
            json.dumps(payload.get("recurrence") or {}, ensure_ascii=False), tz_name,
            condition.get("source") or payload.get("source"),
            json.dumps(payload.get("context") or {}, ensure_ascii=False), action["deep_link"],
        ))
        row = conn.execute("SELECT * FROM automations WHERE id = ?", (automation_id,)).fetchone()
        conn.commit()
        conn.close()
        return row_to_automation(row)

    def list(self, status=None, limit=100):
        conn = self.connection()
        if status in AUTOMATION_STATUSES:
            rows = conn.execute("SELECT * FROM automations WHERE status = ? ORDER BY created_at DESC LIMIT ?", (status, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM automations ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END, created_at DESC LIMIT ?", (limit,)).fetchall()
        conn.close()
        return [row_to_automation(row) for row in rows]

    def set_status(self, automation_id, status):
        if status not in AUTOMATION_STATUSES:
            raise ValueError("Invalid automation status")
        conn = self.connection()
        if status == "active":
            next_run = iso(utc_now())
            conn.execute("UPDATE automations SET status = ?, next_run_at = ?, last_error = NULL WHERE id = ?", (status, next_run, automation_id))
        else:
            completed_at = iso(utc_now()) if status == "completed" else None
            conn.execute("UPDATE automations SET status = ?, completed_at = COALESCE(?, completed_at) WHERE id = ?", (status, completed_at, automation_id))
        row = conn.execute("SELECT * FROM automations WHERE id = ?", (automation_id,)).fetchone()
        conn.commit()
        conn.close()
        if not row:
            raise ValueError("Automation not found")
        return row_to_automation(row)

    def delete(self, automation_id):
        conn = self.connection()
        cursor = conn.execute("DELETE FROM automations WHERE id = ?", (automation_id,))
        conn.commit()
        conn.close()
        if not cursor.rowcount:
            raise ValueError("Automation not found")
        return {"deleted": automation_id}

    def update(self, automation_id, changes):
        allowed = {"title", "instruction", "schedule", "action"}
        if not isinstance(changes, dict) or not set(changes).issubset(allowed):
            raise ValueError("Unsupported automation update")
        conn = self.connection()
        row = conn.execute("SELECT * FROM automations WHERE id = ?", (automation_id,)).fetchone()
        if not row:
            conn.close()
            raise ValueError("Automation not found")
        automation = row_to_automation(row)
        title = str(changes.get("title", automation["title"])).strip()[:240]
        instruction = str(changes.get("instruction", automation["instruction"])).strip()[:2000]
        schedule = changes.get("schedule", automation["schedule"])
        if not isinstance(schedule, dict):
            conn.close()
            raise ValueError("Invalid automation schedule")
        next_run = parse_iso(row["next_run_at"]) or utc_now()
        if automation["type"] == "one_time" and "schedule" in changes:
            next_run = parse_iso(schedule.get("at"))
            if not next_run:
                conn.close()
                raise ValueError("One-time automations need a scheduled time")
        if automation["type"] == "recurring_schedule" and "schedule" in changes:
            next_run = next_weekly_run(schedule, automation["timezone"])
        action = changes.get("action", automation["action"])
        if not isinstance(action, dict):
            conn.close()
            raise ValueError("Invalid automation action")
        conn.execute("""
            UPDATE automations SET title = ?, instruction = ?, schedule = ?, action = ?,
                notification_destination = ?, next_run_at = ?, last_error = NULL
            WHERE id = ?
        """, (title, instruction, json.dumps(schedule, ensure_ascii=False), json.dumps(action, ensure_ascii=False), valid_deep_link(action.get("deep_link") or automation["notification_destination"]), iso(next_run), automation_id))
        updated = conn.execute("SELECT * FROM automations WHERE id = ?", (automation_id,)).fetchone()
        conn.commit()
        conn.close()
        return row_to_automation(updated)

    def add_subscription(self, subscription, user_agent=""):
        if not isinstance(subscription, dict):
            raise ValueError("Invalid push subscription")
        endpoint = str(subscription.get("endpoint", "")).strip()
        keys = subscription.get("keys") if isinstance(subscription.get("keys"), dict) else {}
        p256dh = str(keys.get("p256dh", "")).strip()
        auth = str(keys.get("auth", "")).strip()
        if not endpoint.startswith("https://") or not p256dh or not auth:
            raise ValueError("Invalid push subscription")
        now = iso(utc_now())
        subscription_id = str(uuid.uuid4())
        conn = self.connection()
        conn.execute("""
            INSERT INTO push_subscriptions(id, endpoint, p256dh, auth, user_agent, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(endpoint) DO UPDATE SET p256dh = excluded.p256dh, auth = excluded.auth,
                user_agent = excluded.user_agent, updated_at = excluded.updated_at, last_error = NULL
        """, (subscription_id, endpoint, p256dh, auth, str(user_agent)[:500], now, now))
        conn.commit()
        conn.close()
        return {"ok": True}

    def remove_subscription(self, endpoint):
        conn = self.connection()
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (str(endpoint),))
        conn.commit()
        conn.close()
        return {"ok": True}

    def notification_history(self, limit=50):
        conn = self.connection()
        rows = conn.execute("SELECT * FROM notifications ORDER BY created_at DESC LIMIT ?", (max(1, min(int(limit), 200)),)).fetchall()
        conn.close()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = json_value(item.get("payload"), {})
            item["read"] = bool(item.get("read_at"))
            result.append(item)
        return result

    def mark_notification_read(self, notification_id):
        conn = self.connection()
        conn.execute("UPDATE notifications SET read_at = COALESCE(read_at, ?) WHERE id = ?", (iso(utc_now()), notification_id))
        conn.commit()
        conn.close()
        return {"ok": True}

    def clear_notifications(self):
        conn = self.connection()
        conn.execute("DELETE FROM notifications")
        conn.commit()
        conn.close()
        return {"ok": True}

    def due_rows(self, now):
        conn = self.connection()
        rows = conn.execute("""
            SELECT * FROM automations
            WHERE status = 'active' AND next_run_at IS NOT NULL AND next_run_at <= ?
            ORDER BY next_run_at ASC LIMIT 100
        """, (iso(now),)).fetchall()
        conn.close()
        return [row_to_automation(row) for row in rows]

    def run_once(self, now=None):
        now = now or utc_now()
        for automation in self.due_rows(now):
            try:
                self._run_automation(automation, now)
            except Exception as error:
                self._record_failure(automation["id"], error, now)
        self._run_default_rules(now)

    def _state_value(self, key):
        conn = self.connection()
        row = conn.execute("SELECT value FROM automation_state WHERE key = ?", (key,)).fetchone()
        conn.close()
        return row["value"] if row else None

    def _set_state(self, key, value, now):
        conn = self.connection()
        conn.execute("""
            INSERT INTO automation_state(key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """, (key, str(value), iso(now)))
        conn.commit()
        conn.close()

    def _run_default_rules(self, now):
        """Poll enabled built-in sources at a bounded cadence, with durable dedupe."""
        if not self.default_provider:
            return
        last_checked = parse_iso(self._state_value("default_rules_checked_at"))
        if last_checked and now - last_checked < timedelta(minutes=5):
            return
        self._set_state("default_rules_checked_at", iso(now), now)
        preferences = self.preferences()
        try:
            candidates = self.default_provider(now, preferences) or []
        except Exception as error:
            print(f"[Apollo Automations] default rule error: {error}")
            return
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            category = str(candidate.get("category") or "automations")
            if not (preferences.get("master", False) and preferences.get(category, False)):
                continue
            dedupe_key = str(candidate.get("dedupe_key") or "")[:500]
            if not dedupe_key or self._state_value("default_notice:" + dedupe_key):
                continue
            self._deliver_default(candidate, now)
            self._set_state("default_notice:" + dedupe_key, "sent", now)

    def _run_automation(self, automation, now):
        kind = automation["type"]
        if kind == "one_time":
            self._deliver(automation, now)
            self._complete(automation["id"], now)
            return
        if kind == "recurring_schedule":
            self._deliver(automation, now)
            self._reschedule(automation, now)
            return
        matched, detail = self._evaluate_condition(automation, now)
        if kind in {"condition_once", "relative_event"}:
            if matched:
                self._deliver(automation, now, detail)
                self._complete(automation["id"], now)
            else:
                self._check_later(automation, now, False)
            return
        if kind == "condition_recurring":
            was_active = bool(automation.get("condition_active"))
            if matched and not was_active:
                self._deliver(automation, now, detail)
            self._check_later(automation, now, matched)
            return
        raise ValueError("Unsupported automation type")

    def _evaluate_condition(self, automation, now):
        condition = automation["condition"]
        source = condition["source"]
        snapshot = self.condition_provider(source, condition, now)
        kind = condition["kind"]
        if kind == "threshold":
            metric = str(condition.get("metric", "recovery")).lower()
            operator = str(condition.get("operator", "gt")).lower()
            expected = float(condition["value"])
            value = snapshot.get(metric)
            if value is None:
                return False, {}
            actual = float(value)
            matches = {"gt": actual > expected, "gte": actual >= expected, "lt": actual < expected, "lte": actual <= expected}.get(operator)
            if matches is None:
                raise ValueError("Unsupported threshold operator")
            return matches, {"metric": metric, "value": actual}
        if kind in {"event_approaching", "event_match", "departure_approaching"}:
            return bool(snapshot.get("matched")), snapshot.get("detail") or {}
        if kind in {"due_soon", "overdue", "completed", "status_changed", "event_changed", "flight_changed", "grade_posted", "teacher_comment", "assignment_changed", "message_match"}:
            return bool(snapshot.get("matched")), snapshot.get("detail") or {}
        raise ValueError("Unsupported condition type")

    def _deliver(self, automation, now, detail=None):
        action = automation["action"]
        notification_id = str(uuid.uuid4())
        category = action.get("category") or "automations"
        payload = {"automation_id": automation["id"], "detail": detail or {}}
        conn = self.connection()
        conn.execute("""
            INSERT INTO notifications(id, title, body, category, deep_link, automation_id, payload, created_at, delivery_state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued')
        """, (notification_id, action["title"], action["body"], category, valid_deep_link(action.get("deep_link")), automation["id"], json.dumps(payload, ensure_ascii=False), iso(now)))
        conn.commit()
        conn.close()
        preferences = self.preferences()
        allowed = preferences.get("master", False) and preferences.get(category, category == "automations")
        state = "disabled"
        if allowed:
            state = self.push_sender({"id": notification_id, "title": action["title"], "body": action["body"], "category": category, "deep_link": valid_deep_link(action.get("deep_link")), "payload": payload})
        conn = self.connection()
        conn.execute("UPDATE notifications SET delivery_state = ? WHERE id = ?", (state, notification_id))
        conn.execute("UPDATE automations SET last_triggered_at = ?, failure_count = 0, last_error = NULL WHERE id = ?", (iso(now), automation["id"]))
        conn.commit()
        conn.close()

    def _deliver_default(self, candidate, now):
        """Persist a built-in notification before attempting Web Push."""
        notification_id = str(uuid.uuid4())
        title = str(candidate.get("title") or "Apollo")[:240]
        body = str(candidate.get("body") or "")[:500]
        category = str(candidate.get("category") or "automations")[:40]
        deep_link = valid_deep_link(candidate.get("deep_link"))
        payload = {"system_rule": True, "detail": candidate.get("detail") or {}}
        conn = self.connection()
        conn.execute("""
            INSERT INTO notifications(id, title, body, category, deep_link, payload, created_at, delivery_state)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'queued')
        """, (notification_id, title, body, category, deep_link, json.dumps(payload, ensure_ascii=False), iso(now)))
        conn.commit()
        conn.close()
        state = self.push_sender({"id": notification_id, "title": title, "body": body, "category": category, "deep_link": deep_link, "payload": payload})
        conn = self.connection()
        conn.execute("UPDATE notifications SET delivery_state = ? WHERE id = ?", (state, notification_id))
        conn.commit()
        conn.close()

    def _complete(self, automation_id, now):
        conn = self.connection()
        conn.execute("UPDATE automations SET status = 'completed', completed_at = ?, next_run_at = NULL, condition_active = 0 WHERE id = ?", (iso(now), automation_id))
        conn.commit()
        conn.close()

    def _reschedule(self, automation, now):
        next_run = next_weekly_run(automation["schedule"], automation["timezone"], now)
        conn = self.connection()
        conn.execute("UPDATE automations SET next_run_at = ?, last_checked_at = ? WHERE id = ?", (iso(next_run), iso(now), automation["id"]))
        conn.commit()
        conn.close()

    def _check_later(self, automation, now, condition_active):
        source = automation["condition"]["source"]
        interval = int(automation["condition"].get("check_interval_seconds") or SOURCE_INTERVAL_SECONDS[source])
        interval = max(60, min(interval, 24 * 60 * 60))
        conn = self.connection()
        conn.execute("UPDATE automations SET next_run_at = ?, last_checked_at = ?, condition_active = ? WHERE id = ?", (iso(now + timedelta(seconds=interval)), iso(now), 1 if condition_active else 0, automation["id"]))
        conn.commit()
        conn.close()

    def _record_failure(self, automation_id, error, now):
        conn = self.connection()
        row = conn.execute("SELECT failure_count FROM automations WHERE id = ?", (automation_id,)).fetchone()
        failures = int(row["failure_count"] or 0) + 1 if row else 1
        retry_seconds = min(6 * 60 * 60, 60 * (2 ** min(failures, 8)))
        status = "failed" if failures >= 8 else "active"
        conn.execute("UPDATE automations SET status = ?, failure_count = ?, last_error = ?, last_checked_at = ?, next_run_at = ? WHERE id = ?", (status, failures, str(error)[:1000], iso(now), iso(now + timedelta(seconds=retry_seconds)), automation_id))
        conn.commit()
        conn.close()
