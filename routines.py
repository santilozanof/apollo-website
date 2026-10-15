"""Persistent routines, daily snapshots, hydration, statistics, and chat tools.

The module is deliberately framework-free so it can share Apollo's SQLite
connection factory and be exercised independently in tests.
"""

import json
import re
import sqlite3
import uuid
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo


WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
STEP_TYPES = {"checkbox", "counter", "quantity"}
STEP_SCHEDULE_TYPES = {"daily", "weekdays", "recurrence"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _id():
    return uuid.uuid4().hex


def _json(value, fallback):
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
        return parsed if parsed is not None else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


def _zone(name):
    try:
        return ZoneInfo(str(name or "UTC"))
    except Exception:
        return ZoneInfo("UTC")


def local_day(time_zone="UTC", value=None):
    if value:
        return date.fromisoformat(str(value)[:10]).isoformat()
    return datetime.now(_zone(time_zone)).date().isoformat()


def init_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS routine_groups (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            schedule_days TEXT NOT NULL DEFAULT '[0,1,2,3,4,5,6]',
            window_start TEXT,
            window_end TEXT,
            reminder_start INTEGER NOT NULL DEFAULT 0,
            reminder_end INTEGER NOT NULL DEFAULT 0,
            position INTEGER NOT NULL DEFAULT 0,
            archived INTEGER NOT NULL DEFAULT 0,
            version INTEGER NOT NULL DEFAULT 1,
            created_local_date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS routine_steps (
            id TEXT PRIMARY KEY,
            routine_id TEXT NOT NULL,
            title TEXT NOT NULL,
            step_type TEXT NOT NULL DEFAULT 'checkbox',
            target REAL NOT NULL DEFAULT 1,
            unit TEXT NOT NULL DEFAULT '',
            required INTEGER NOT NULL DEFAULT 1,
            linked_hydration INTEGER NOT NULL DEFAULT 0,
            position INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(routine_id) REFERENCES routine_groups(id)
        );
        CREATE INDEX IF NOT EXISTS idx_routine_steps_group
            ON routine_steps(routine_id, position);
        CREATE TABLE IF NOT EXISTS routine_step_exceptions (
            id TEXT PRIMARY KEY,
            routine_id TEXT NOT NULL,
            step_id TEXT NOT NULL,
            local_date TEXT NOT NULL,
            action TEXT NOT NULL,
            substitute_title TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(step_id, local_date),
            FOREIGN KEY(routine_id) REFERENCES routine_groups(id),
            FOREIGN KEY(step_id) REFERENCES routine_steps(id)
        );
        CREATE INDEX IF NOT EXISTS idx_routine_step_exceptions_date
            ON routine_step_exceptions(routine_id, local_date);
        CREATE TABLE IF NOT EXISTS routine_versions (
            routine_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            snapshot_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(routine_id, version)
        );
        CREATE TABLE IF NOT EXISTS routine_daily_instances (
            id TEXT PRIMARY KEY,
            routine_id TEXT NOT NULL,
            local_date TEXT NOT NULL,
            timezone TEXT NOT NULL,
            routine_version INTEGER NOT NULL,
            snapshot_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'incomplete',
            completed_at TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(routine_id, local_date)
        );
        CREATE INDEX IF NOT EXISTS idx_routine_instances_date
            ON routine_daily_instances(local_date, routine_id);
        CREATE TABLE IF NOT EXISTS routine_step_daily (
            instance_id TEXT NOT NULL,
            step_id TEXT NOT NULL,
            value REAL NOT NULL DEFAULT 0,
            completed_at TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(instance_id, step_id)
        );
        CREATE TABLE IF NOT EXISTS routine_completion_events (
            id TEXT PRIMARY KEY,
            instance_id TEXT NOT NULL,
            step_id TEXT,
            value REAL NOT NULL,
            completed INTEGER NOT NULL,
            occurred_at TEXT NOT NULL,
            idempotency_key TEXT UNIQUE
        );
        CREATE TABLE IF NOT EXISTS hydration_preferences (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            goal_ml REAL NOT NULL DEFAULT 2500,
            display_unit TEXT NOT NULL DEFAULT 'ml',
            timezone TEXT NOT NULL DEFAULT 'UTC',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS hydration_entries (
            id TEXT PRIMARY KEY,
            local_date TEXT NOT NULL,
            amount_ml REAL NOT NULL,
            beverage TEXT NOT NULL DEFAULT 'water',
            logged_at TEXT NOT NULL,
            idempotency_key TEXT UNIQUE,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_hydration_entries_date
            ON hydration_entries(local_date, logged_at);
    """)
    conn.execute(
        "INSERT OR IGNORE INTO hydration_preferences "
        "(id, goal_ml, display_unit, timezone, updated_at) VALUES (1,2500,'ml','UTC',?)",
        (_now(),),
    )
    # Additive migrations keep existing production data and old snapshots valid.
    columns = {row[1] for row in conn.execute("PRAGMA table_info(routine_steps)").fetchall()}
    migrations = {
        "schedule_type": "TEXT NOT NULL DEFAULT 'daily'",
        "schedule_days": "TEXT NOT NULL DEFAULT '[0,1,2,3,4,5,6]'",
        "recurrence_rule": "TEXT NOT NULL DEFAULT '{}'",
        "alternative_group": "TEXT NOT NULL DEFAULT ''",
    }
    for column, definition in migrations.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE routine_steps ADD COLUMN {column} {definition}")


def _days(value):
    if value is None:
        return list(range(7))
    result = sorted({int(item) for item in value if str(item).isdigit() and 0 <= int(item) <= 6})
    return result


def _snapshot(conn, routine_id):
    group = conn.execute("SELECT * FROM routine_groups WHERE id = ?", (routine_id,)).fetchone()
    if not group:
        raise ValueError("Routine not found")
    item = dict(group)
    item["schedule_days"] = _json(item["schedule_days"], list(range(7)))
    item["steps"] = [dict(row) for row in conn.execute(
        "SELECT * FROM routine_steps WHERE routine_id = ? ORDER BY position, created_at", (routine_id,)
    ).fetchall()]
    for step in item["steps"]:
        step["schedule_type"] = step.get("schedule_type") or "daily"
        step["schedule_days"] = _json(step.get("schedule_days"), list(range(7)))
        step["recurrence_rule"] = _json(step.get("recurrence_rule"), {})
        step["alternative_group"] = step.get("alternative_group") or ""
    return item


def _step_scheduled(step, day):
    current = date.fromisoformat(day)
    kind = step.get("schedule_type") or "daily"
    if kind == "daily":
        return True
    if kind == "weekdays":
        return current.weekday() in _days(step.get("schedule_days"))
    rule = step.get("recurrence_rule") or {}
    if isinstance(rule, str):
        rule = _json(rule, {})
    start_text = str(rule.get("start_date") or day)[:10]
    try:
        start = date.fromisoformat(start_text)
    except ValueError:
        start = current
    if current < start:
        return False
    interval = max(1, int(rule.get("interval") or 1))
    frequency = str(rule.get("frequency") or "weekly").lower()
    delta = (current - start).days
    if frequency == "daily":
        return delta % interval == 0
    weekdays = _days(rule.get("weekdays") or step.get("schedule_days"))
    return current.weekday() in weekdays and (delta // 7) % interval == 0


def _daily_snapshot(conn, routine_id, day):
    snapshot = _snapshot(conn, routine_id)
    exceptions = {row["step_id"]: dict(row) for row in conn.execute(
        "SELECT * FROM routine_step_exceptions WHERE routine_id=? AND local_date=?",
        (routine_id, day),
    ).fetchall()}
    scheduled = []
    for original in snapshot.get("steps", []):
        step = dict(original)
        exception = exceptions.get(step["id"])
        if exception and exception["action"] == "skip":
            continue
        if not _step_scheduled(step, day) and not exception:
            continue
        if exception and exception["action"] == "substitute":
            step["original_title"] = step["title"]
            step["title"] = exception["substitute_title"]
            step["is_substitution"] = True
        scheduled.append(step)
    snapshot["all_steps"] = snapshot.get("steps", [])
    snapshot["steps"] = scheduled
    return snapshot


def _save_version(conn, routine_id, increment=True, effective_day=None):
    if increment:
        conn.execute(
            "UPDATE routine_groups SET version = version + 1, updated_at = ? WHERE id = ?",
            (_now(), routine_id),
        )
    item = _snapshot(conn, routine_id)
    conn.execute(
        "INSERT OR REPLACE INTO routine_versions (routine_id,version,snapshot_json,created_at) VALUES (?,?,?,?)",
        (routine_id, item["version"], json.dumps(item, separators=(",", ":")), _now()),
    )
    # Structural edits should be visible immediately in today's checklist,
    # while past instances remain immutable historical snapshots.
    live_rows = conn.execute(
        "SELECT id FROM routine_daily_instances WHERE routine_id=? AND local_date>=?",
        (routine_id, effective_day or date.today().isoformat()),
    ).fetchall()
    for row in live_rows:
        instance_day = conn.execute(
            "SELECT local_date FROM routine_daily_instances WHERE id=?", (row["id"],)
        ).fetchone()[0]
        daily_item = _daily_snapshot(conn, routine_id, instance_day)
        conn.execute(
            "UPDATE routine_daily_instances SET routine_version=?,snapshot_json=?,updated_at=? WHERE id=?",
            (item["version"], json.dumps(daily_item), _now(), row["id"]),
        )
        _recalculate(conn, row["id"])
    return item


def _freeze_past(conn, routine_id, time_zone="UTC"):
    """Materialize old scheduled days before a structural edit.

    This makes historical missed/partial days use the schedule and step
    snapshot that was actually active then, rather than today's definition.
    """
    snapshot = _snapshot(conn, routine_id)
    cursor = date.fromisoformat(snapshot["created_local_date"])
    end = date.fromisoformat(local_day(time_zone)) - timedelta(days=1)
    while cursor <= end:
        key = cursor.isoformat()
        if _scheduled(snapshot, key):
            _instance(conn, routine_id, key, time_zone, create=True)
        cursor += timedelta(days=1)


def create_routine(conn, payload, today=None):
    """Create a routine and all supplied ordered steps as one transaction unit."""
    title = str(payload.get("title") or "").strip()[:120]
    if not title:
        raise ValueError("A routine name is required")
    routine_id, now = _id(), _now()
    day = local_day(payload.get("timezone"), today)
    position = conn.execute("SELECT COALESCE(MAX(position),-1)+1 FROM routine_groups").fetchone()[0]
    conn.execute("""
        INSERT INTO routine_groups
        (id,title,description,schedule_days,window_start,window_end,reminder_start,
         reminder_end,position,archived,version,created_local_date,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,0,1,?,?,?)
    """, (
        routine_id, title, str(payload.get("description") or "").strip()[:500],
        json.dumps(_days(payload.get("schedule_days"))), payload.get("window_start") or None,
        payload.get("window_end") or None, int(bool(payload.get("reminder_start"))),
        int(bool(payload.get("reminder_end"))), position, day, now, now,
    ))
    for index, step in enumerate(payload.get("steps") or []):
        _insert_step(conn, routine_id, step, index)
    _save_version(conn, routine_id, increment=False)
    return _snapshot(conn, routine_id)


def create_or_populate_routine(conn, payload, today=None):
    """Create a complete routine, or atomically add missing steps to its namesake."""
    title = str(payload.get("title") or "").strip()[:120]
    requested_steps = payload.get("steps") or []
    existing = conn.execute(
        "SELECT id FROM routine_groups WHERE archived=0 AND lower(title)=lower(?) ORDER BY created_at LIMIT 1",
        (title,),
    ).fetchone()
    if not existing:
        item = create_routine(conn, payload, today=today)
    else:
        routine_id = existing["id"]
        current = _snapshot(conn, routine_id)
        known = {step["title"].strip().casefold() for step in current["steps"]}
        missing = [
            step for step in requested_steps
            if str(step.get("title") or "").strip().casefold() not in known
        ]
        if missing:
            _freeze_past(conn, routine_id, payload.get("timezone") or "UTC")
            for step in missing:
                _insert_step(conn, routine_id, step)
            item = _save_version(
                conn, routine_id,
                effective_day=local_day(payload.get("timezone") or "UTC", today),
            )
        else:
            item = current
    saved = {step["title"].strip().casefold() for step in item["steps"]}
    absent = [
        str(step.get("title") or "").strip()
        for step in requested_steps
        if str(step.get("title") or "").strip().casefold() not in saved
    ]
    if absent:
        raise RuntimeError("Routine saved without requested steps: " + ", ".join(absent))
    return item, bool(existing)


def _insert_step(conn, routine_id, payload, position=None):
    title = str(payload.get("title") or "").strip()[:160]
    if not title:
        raise ValueError("A step name is required")
    kind = str(payload.get("step_type") or "checkbox").lower()
    if kind not in STEP_TYPES:
        raise ValueError("Invalid step type")
    target = float(payload.get("target") or 1)
    if target <= 0:
        raise ValueError("Step target must be greater than zero")
    if position is None:
        position = conn.execute(
            "SELECT COALESCE(MAX(position),-1)+1 FROM routine_steps WHERE routine_id=?", (routine_id,)
        ).fetchone()[0]
    step_id, now = _id(), _now()
    schedule_type = str(payload.get("schedule_type") or "daily").lower()
    if schedule_type not in STEP_SCHEDULE_TYPES:
        raise ValueError("Invalid step schedule")
    schedule_days = _days(payload.get("schedule_days"))
    recurrence_rule = payload.get("recurrence_rule") or {}
    if not isinstance(recurrence_rule, dict):
        raise ValueError("Invalid recurrence rule")
    conn.execute("""
        INSERT INTO routine_steps
        (id,routine_id,title,step_type,target,unit,required,linked_hydration,position,
         schedule_type,schedule_days,recurrence_rule,alternative_group,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        step_id, routine_id, title, kind, target, str(payload.get("unit") or "")[:30],
        int(payload.get("required", True) is not False), int(bool(payload.get("linked_hydration"))),
        int(position), schedule_type, json.dumps(schedule_days),
        json.dumps(recurrence_rule, separators=(",", ":")),
        str(payload.get("alternative_group") or "").strip()[:80], now, now,
    ))
    return step_id


def update_routine(conn, routine_id, changes, time_zone="UTC"):
    _freeze_past(conn, routine_id, time_zone)
    allowed = {
        "title": lambda v: str(v).strip()[:120],
        "description": lambda v: str(v or "").strip()[:500],
        "schedule_days": lambda v: json.dumps(_days(v)),
        "window_start": lambda v: v or None,
        "window_end": lambda v: v or None,
        "reminder_start": lambda v: int(bool(v)),
        "reminder_end": lambda v: int(bool(v)),
        "position": int,
        "archived": lambda v: int(bool(v)),
    }
    fields, values = [], []
    for key, convert in allowed.items():
        if key in changes:
            value = convert(changes[key])
            if key == "title" and not value:
                raise ValueError("A routine name is required")
            fields.append(f"{key} = ?")
            values.append(value)
    if fields:
        values.extend([_now(), routine_id])
        conn.execute(f"UPDATE routine_groups SET {', '.join(fields)}, updated_at=? WHERE id=?", values)
    if not conn.execute("SELECT 1 FROM routine_groups WHERE id=?", (routine_id,)).fetchone():
        raise ValueError("Routine not found")
    return _save_version(conn, routine_id, effective_day=local_day(time_zone))


def add_step(conn, routine_id, payload, time_zone="UTC"):
    _freeze_past(conn, routine_id, time_zone)
    _insert_step(conn, routine_id, payload)
    return _save_version(conn, routine_id, effective_day=local_day(time_zone))


def update_step(conn, step_id, changes, time_zone="UTC"):
    row = conn.execute("SELECT routine_id FROM routine_steps WHERE id=?", (step_id,)).fetchone()
    if not row:
        raise ValueError("Step not found")
    _freeze_past(conn, row["routine_id"], time_zone)
    allowed = {"title", "step_type", "target", "unit", "required", "linked_hydration", "position",
               "schedule_type", "schedule_days", "recurrence_rule", "alternative_group"}
    fields, values = [], []
    for key in allowed:
        if key not in changes:
            continue
        value = changes[key]
        if key == "step_type" and value not in STEP_TYPES:
            raise ValueError("Invalid step type")
        if key == "schedule_type" and value not in STEP_SCHEDULE_TYPES:
            raise ValueError("Invalid step schedule")
        if key == "target":
            value = float(value)
            if value <= 0:
                raise ValueError("Step target must be greater than zero")
        if key in {"required", "linked_hydration"}:
            value = int(bool(value))
        if key == "schedule_days":
            value = json.dumps(_days(value))
        if key == "recurrence_rule":
            if not isinstance(value, dict):
                raise ValueError("Invalid recurrence rule")
            value = json.dumps(value, separators=(",", ":"))
        if key == "alternative_group":
            value = str(value or "").strip()[:80]
        fields.append(f"{key}=?")
        values.append(value)
    if fields:
        values.extend([_now(), step_id])
        conn.execute(f"UPDATE routine_steps SET {', '.join(fields)}, updated_at=? WHERE id=?", values)
    return _save_version(conn, row["routine_id"], effective_day=local_day(time_zone))


def delete_step(conn, step_id, time_zone="UTC"):
    row = conn.execute("SELECT routine_id FROM routine_steps WHERE id=?", (step_id,)).fetchone()
    if not row:
        raise ValueError("Step not found")
    _freeze_past(conn, row["routine_id"], time_zone)
    conn.execute("DELETE FROM routine_step_exceptions WHERE step_id=?", (step_id,))
    conn.execute("DELETE FROM routine_steps WHERE id=?", (step_id,))
    return _save_version(conn, row["routine_id"], effective_day=local_day(time_zone))


def duplicate_routine(conn, routine_id, today=None):
    source = _snapshot(conn, routine_id)
    source["title"] = f"{source['title']} Copy"
    source["timezone"] = "UTC"
    return create_routine(conn, source, today=today)


def delete_routine(conn, routine_id, delete_history=False):
    if delete_history:
        ids = [row[0] for row in conn.execute(
            "SELECT id FROM routine_daily_instances WHERE routine_id=?", (routine_id,)
        ).fetchall()]
        for instance_id in ids:
            conn.execute("DELETE FROM routine_step_daily WHERE instance_id=?", (instance_id,))
            conn.execute("DELETE FROM routine_completion_events WHERE instance_id=?", (instance_id,))
        conn.execute("DELETE FROM routine_daily_instances WHERE routine_id=?", (routine_id,))
        conn.execute("DELETE FROM routine_versions WHERE routine_id=?", (routine_id,))
        conn.execute("DELETE FROM routine_step_exceptions WHERE routine_id=?", (routine_id,))
        conn.execute("DELETE FROM routine_steps WHERE routine_id=?", (routine_id,))
        conn.execute("DELETE FROM routine_groups WHERE id=?", (routine_id,))
    else:
        conn.execute("UPDATE routine_groups SET archived=1, updated_at=? WHERE id=?", (_now(), routine_id))
    return {"deleted": bool(delete_history), "archived": not delete_history, "id": routine_id}


def _scheduled(snapshot, day):
    return date.fromisoformat(day).weekday() in snapshot.get("schedule_days", list(range(7)))


def _instance(conn, routine_id, day, time_zone, create=True):
    row = conn.execute(
        "SELECT * FROM routine_daily_instances WHERE routine_id=? AND local_date=?", (routine_id, day)
    ).fetchone()
    if row or not create:
        return dict(row) if row else None
    snapshot = _snapshot(conn, routine_id)
    if not _scheduled(snapshot, day) or day < snapshot["created_local_date"]:
        return None
    snapshot = _daily_snapshot(conn, routine_id, day)
    instance_id = _id()
    conn.execute("""
        INSERT INTO routine_daily_instances
        (id,routine_id,local_date,timezone,routine_version,snapshot_json,status,updated_at)
        VALUES (?,?,?,?,?,?,'incomplete',?)
    """, (instance_id, routine_id, day, time_zone, snapshot["version"], json.dumps(snapshot), _now()))
    return dict(conn.execute("SELECT * FROM routine_daily_instances WHERE id=?", (instance_id,)).fetchone())


def _hydrate_instance(conn, instance):
    snapshot = _json(instance["snapshot_json"], {})
    progress_rows = {
        row["step_id"]: dict(row) for row in conn.execute(
            "SELECT * FROM routine_step_daily WHERE instance_id=?", (instance["id"],)
        ).fetchall()
    }
    steps, completed_required, required = [], 0, 0
    alternative_progress = {}
    for step in snapshot.get("steps", []):
        progress = progress_rows.get(step["id"], {})
        value = float(progress.get("value") or 0)
        complete = value >= float(step.get("target") or 1)
        alternative = str(step.get("alternative_group") or "")
        if step.get("required", 1) and alternative:
            alternative_progress.setdefault(alternative, []).append(complete)
        elif step.get("required", 1):
            required += 1
            completed_required += int(complete)
        steps.append({**step, "value": value, "complete": complete, "completed_at": progress.get("completed_at")})
    for values in alternative_progress.values():
        required += 1
        completed_required += int(any(values))
    status = "completed" if required == completed_required else ("partial" if any(s["value"] > 0 for s in steps) else "incomplete")
    return {
        **snapshot, "instance_id": instance["id"], "local_date": instance["local_date"],
        "status": status, "completed_at": instance.get("completed_at"), "steps": steps,
        "all_steps": snapshot.get("all_steps", snapshot.get("steps", [])),
        "completed_steps": completed_required, "required_steps": required,
        "progress": 1 if required == 0 else completed_required / required,
    }


def _recalculate(conn, instance_id, occurred_at=None):
    instance = dict(conn.execute("SELECT * FROM routine_daily_instances WHERE id=?", (instance_id,)).fetchone())
    item = _hydrate_instance(conn, instance)
    old = instance["status"]
    completed_at = instance.get("completed_at")
    if item["status"] == "completed" and old != "completed":
        completed_at = occurred_at or _now()
    elif item["status"] != "completed":
        completed_at = None
    conn.execute(
        "UPDATE routine_daily_instances SET status=?, completed_at=?, updated_at=? WHERE id=?",
        (item["status"], completed_at, _now(), instance_id),
    )
    item["completed_at"] = completed_at
    return item


def set_step(conn, routine_id, step_id, value=None, completed=None, day=None, time_zone="UTC", idempotency_key=None):
    day = local_day(time_zone, day)
    instance = _instance(conn, routine_id, day, time_zone)
    if not instance:
        raise ValueError("Routine is not scheduled for this day")
    snapshot = _json(instance["snapshot_json"], {})
    step = next((item for item in snapshot.get("steps", []) if item["id"] == step_id), None)
    if not step:
        raise ValueError("Step not found in this day's routine")
    if idempotency_key:
        duplicate = conn.execute(
            "SELECT 1 FROM routine_completion_events WHERE idempotency_key=?", (idempotency_key,)
        ).fetchone()
        if duplicate:
            return _recalculate(conn, instance["id"])
    current = conn.execute(
        "SELECT value FROM routine_step_daily WHERE instance_id=? AND step_id=?", (instance["id"], step_id)
    ).fetchone()
    current_value = float(current[0]) if current else 0
    target = float(step.get("target") or 1)
    new_value = target if completed is True else (0 if completed is False else float(value if value is not None else current_value))
    new_value = max(0, new_value)
    occurred_at = _now()
    completed_at = occurred_at if new_value >= target else None
    conn.execute("""
        INSERT INTO routine_step_daily (instance_id,step_id,value,completed_at,updated_at)
        VALUES (?,?,?,?,?) ON CONFLICT(instance_id,step_id) DO UPDATE SET
        value=excluded.value, completed_at=excluded.completed_at, updated_at=excluded.updated_at
    """, (instance["id"], step_id, new_value, completed_at, occurred_at))
    conn.execute("""
        INSERT INTO routine_completion_events
        (id,instance_id,step_id,value,completed,occurred_at,idempotency_key) VALUES (?,?,?,?,?,?,?)
    """, (_id(), instance["id"], step_id, new_value, int(new_value >= target), occurred_at, idempotency_key))
    return _recalculate(conn, instance["id"], occurred_at)


def set_routine(conn, routine_id, completed, day=None, time_zone="UTC", idempotency_key=None):
    day = local_day(time_zone, day)
    instance = _instance(conn, routine_id, day, time_zone)
    if not instance:
        raise ValueError("Routine is not scheduled for this day")
    if idempotency_key and conn.execute(
        "SELECT 1 FROM routine_completion_events WHERE idempotency_key=?", (idempotency_key,)
    ).fetchone():
        return _recalculate(conn, instance["id"])
    snapshot = _json(instance["snapshot_json"], {})
    now = _now()
    seen_alternatives = set()
    for step in snapshot.get("steps", []):
        alternative = str(step.get("alternative_group") or "")
        if completed and alternative and alternative in seen_alternatives:
            continue
        if alternative:
            seen_alternatives.add(alternative)
        value = float(step.get("target") or 1) if completed else 0
        conn.execute("""
            INSERT INTO routine_step_daily (instance_id,step_id,value,completed_at,updated_at)
            VALUES (?,?,?,?,?) ON CONFLICT(instance_id,step_id) DO UPDATE SET
            value=excluded.value,completed_at=excluded.completed_at,updated_at=excluded.updated_at
        """, (instance["id"], step["id"], value, now if completed else None, now))
    conn.execute("""
        INSERT INTO routine_completion_events
        (id,instance_id,step_id,value,completed,occurred_at,idempotency_key)
        VALUES (?,?,NULL,?,?,?,?)
    """, (_id(), instance["id"], 1 if completed else 0, int(completed), now, idempotency_key))
    return _recalculate(conn, instance["id"], now)


def set_step_exception(conn, routine_id, step_id, day, action, substitute_title="", time_zone="UTC"):
    if action not in {"skip", "substitute", "clear"}:
        raise ValueError("Invalid exception action")
    date.fromisoformat(str(day)[:10])
    row = conn.execute(
        "SELECT 1 FROM routine_steps WHERE id=? AND routine_id=?", (step_id, routine_id)
    ).fetchone()
    if not row:
        raise ValueError("Step not found")
    _freeze_past(conn, routine_id, time_zone)
    if action == "clear":
        conn.execute("DELETE FROM routine_step_exceptions WHERE step_id=? AND local_date=?", (step_id, day))
    else:
        title = str(substitute_title or "").strip()[:160]
        if action == "substitute" and not title:
            raise ValueError("A substitute step name is required")
        now = _now()
        conn.execute("""
            INSERT INTO routine_step_exceptions
            (id,routine_id,step_id,local_date,action,substitute_title,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(step_id,local_date) DO UPDATE SET
            action=excluded.action,substitute_title=excluded.substitute_title,updated_at=excluded.updated_at
        """, (_id(), routine_id, step_id, day, action, title, now, now))
    return _save_version(conn, routine_id, effective_day=local_day(time_zone))


def hydration_status(conn, day=None, time_zone="UTC"):
    day = local_day(time_zone, day)
    pref = dict(conn.execute("SELECT * FROM hydration_preferences WHERE id=1").fetchone())
    entries = [dict(row) for row in conn.execute(
        "SELECT * FROM hydration_entries WHERE local_date=? ORDER BY logged_at", (day,)
    ).fetchall()]
    total = sum(float(item["amount_ml"]) for item in entries)
    goal = float(pref["goal_ml"])
    return {"local_date": day, "total_ml": total, "goal_ml": goal, "progress": min(1, total / goal) if goal else 0, "entries": entries, "display_unit": pref["display_unit"]}


def log_water(conn, amount_ml, time_zone="UTC", logged_at=None, beverage="water", idempotency_key=None):
    amount = float(amount_ml)
    if amount <= 0 or amount > 20000:
        raise ValueError("Water amount must be between 0 and 20,000 mL")
    stamp = logged_at or _now()
    try:
        day = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(_zone(time_zone)).date().isoformat()
    except ValueError:
        raise ValueError("Invalid hydration timestamp")
    entry_id = _id()
    try:
        conn.execute("""
            INSERT INTO hydration_entries (id,local_date,amount_ml,beverage,logged_at,idempotency_key,updated_at)
            VALUES (?,?,?,?,?,?,?)
        """, (entry_id, day, amount, str(beverage or "water")[:50], stamp, idempotency_key, _now()))
    except sqlite3.IntegrityError:
        if not idempotency_key or not conn.execute(
            "SELECT 1 FROM hydration_entries WHERE idempotency_key=?", (idempotency_key,)
        ).fetchone():
            raise
    status = hydration_status(conn, day, time_zone)
    # Hydration-linked steps mirror the authoritative hydration total.
    groups = conn.execute("SELECT id FROM routine_groups WHERE archived=0").fetchall()
    for group in groups:
        instance = _instance(conn, group["id"], day, time_zone)
        if not instance:
            continue
        snap = _json(instance["snapshot_json"], {})
        for step in snap.get("steps", []):
            if step.get("linked_hydration"):
                target_ml = float(step.get("target") or status["goal_ml"])
                value = min(status["total_ml"], target_ml)
                set_step(conn, group["id"], step["id"], value=value, day=day, time_zone=time_zone)
    return status


def update_hydration(conn, payload):
    fields, values = [], []
    if "goal_ml" in payload:
        goal = float(payload["goal_ml"])
        if goal <= 0 or goal > 20000:
            raise ValueError("Hydration goal must be between 0 and 20,000 mL")
        fields.append("goal_ml=?"); values.append(goal)
    if "display_unit" in payload:
        unit = str(payload["display_unit"])
        if unit not in {"ml", "l", "oz"}:
            raise ValueError("Unsupported hydration unit")
        fields.append("display_unit=?"); values.append(unit)
    if "timezone" in payload:
        _zone(payload["timezone"])
        fields.append("timezone=?"); values.append(str(payload["timezone"]))
    if fields:
        values.append(_now())
        conn.execute(f"UPDATE hydration_preferences SET {', '.join(fields)},updated_at=? WHERE id=1", values)
    return dict(conn.execute("SELECT * FROM hydration_preferences WHERE id=1").fetchone())


def hydration_entry_action(conn, entry_id, action, payload=None):
    payload = payload or {}
    if action == "delete":
        conn.execute("DELETE FROM hydration_entries WHERE id=?", (entry_id,))
    elif action == "update":
        amount = float(payload.get("amount_ml") or 0)
        if amount <= 0:
            raise ValueError("Amount must be greater than zero")
        conn.execute("UPDATE hydration_entries SET amount_ml=?,updated_at=? WHERE id=?", (amount, _now(), entry_id))
    else:
        raise ValueError("Unknown hydration action")
    return {"ok": True}


def routine_statistics(conn, routine_id, end_day=None, days=365):
    end = date.fromisoformat(end_day or date.today().isoformat())
    group = _snapshot(conn, routine_id)
    start = max(date.fromisoformat(group["created_local_date"]), end - timedelta(days=max(1, int(days)) - 1))
    rows = {row["local_date"]: dict(row) for row in conn.execute(
        "SELECT * FROM routine_daily_instances WHERE routine_id=? AND local_date BETWEEN ? AND ?",
        (routine_id, start.isoformat(), end.isoformat()),
    ).fetchall()}
    scheduled, completed, streak, longest = 0, 0, 0, 0
    cursor = start
    daily = []
    while cursor <= end:
        key = cursor.isoformat()
        is_scheduled = _scheduled(group, key)
        status = rows.get(key, {}).get("status") if is_scheduled else "not_scheduled"
        if is_scheduled:
            scheduled += 1
            if status == "completed":
                completed += 1; streak += 1; longest = max(longest, streak)
            else:
                streak = 0
                if cursor < end and status in {None, "incomplete"}:
                    status = "missed"
                elif not status:
                    status = "incomplete"
        daily.append({"date": key, "status": status})
        cursor += timedelta(days=1)
    current = 0
    for item in reversed(daily):
        if item["status"] == "not_scheduled":
            continue
        if item["status"] == "completed":
            current += 1
        else:
            break
    return {"routine_id": routine_id, "scheduled_days": scheduled, "total_completions": completed, "completion_rate": completed / scheduled if scheduled else 0, "current_streak": current, "longest_streak": longest, "daily": daily}


def get_state(conn, day=None, time_zone="UTC", include_archived=False):
    day = local_day(time_zone, day)
    groups = conn.execute(
        "SELECT * FROM routine_groups " + ("" if include_archived else "WHERE archived=0 ") + "ORDER BY position, created_at"
    ).fetchall()
    items = []
    for row in groups:
        snapshot = _snapshot(conn, row["id"])
        if day < snapshot["created_local_date"] or not _scheduled(snapshot, day):
            items.append({**snapshot, "status": "not_scheduled", "progress": 0, "completed_steps": 0,
                          "required_steps": 0, "all_steps": snapshot["steps"], "steps": []})
            continue
        instance = _instance(conn, row["id"], day, time_zone)
        hydrated = _hydrate_instance(conn, instance)
        if day < local_day(time_zone) and hydrated["status"] == "incomplete":
            hydrated["status"] = "missed"
        items.append(hydrated)
    hydration = hydration_status(conn, day, time_zone)
    total_required = sum(item["required_steps"] for item in items if item["status"] != "not_scheduled")
    total_done = sum(item["completed_steps"] for item in items if item["status"] != "not_scheduled")
    return {"local_date": day, "timezone": time_zone, "routines": items, "hydration": hydration, "progress": total_done / total_required if total_required else 0}


def history(conn, start_day, end_day, time_zone="UTC"):
    start, end = date.fromisoformat(start_day), date.fromisoformat(end_day)
    if end < start or (end - start).days > 370:
        raise ValueError("History range must be 370 days or less")
    days, cursor = [], start
    while cursor <= end:
        state = get_state(conn, cursor.isoformat(), time_zone)
        days.append({"date": cursor.isoformat(), "progress": state["progress"], "routines": state["routines"], "hydration": state["hydration"]})
        cursor += timedelta(days=1)
    return {"start": start_day, "end": end_day, "days": days}


def chat_context(conn, time_zone="UTC"):
    state = get_state(conn, time_zone=time_zone)
    today_value = date.fromisoformat(state["local_date"])
    week = []
    for offset in range(7):
        key = (today_value + timedelta(days=offset)).isoformat()
        day_state = state if offset == 0 else get_state(conn, key, time_zone)
        week.append({
            "date": key,
            "label": "today" if offset == 0 else "tomorrow" if offset == 1 else WEEKDAYS[(today_value.weekday() + offset) % 7],
            "routines": [{
                "title": routine["title"],
                "steps": [step["title"] for step in routine["steps"]],
            } for routine in day_state["routines"] if routine["status"] != "not_scheduled"],
        })
    compact = {"local_date": state["local_date"], "week_schedule": week, "routines": [], "hydration": {k: state["hydration"][k] for k in ("total_ml", "goal_ml", "progress")}}
    for item in state["routines"]:
        stats = routine_statistics(conn, item["id"], state["local_date"], 35)
        compact["routines"].append({"id": item["id"], "title": item["title"], "status": item["status"], "completed_steps": item["completed_steps"], "required_steps": item["required_steps"], "schedule_days": item["schedule_days"], "current_streak": stats["current_streak"], "longest_streak": stats["longest_streak"], "recent_completion_rate": stats["completion_rate"], "recent_daily": stats["daily"], "steps": [{"id": s["id"], "title": s["title"], "value": s["value"], "target": s["target"], "complete": s["complete"], "schedule_type": s.get("schedule_type"), "schedule_days": s.get("schedule_days"), "alternative_group": s.get("alternative_group")} for s in item["steps"]], "all_steps": [{"id": s["id"], "title": s["title"], "schedule_type": s.get("schedule_type"), "schedule_days": s.get("schedule_days"), "recurrence_rule": s.get("recurrence_rule"), "alternative_group": s.get("alternative_group")} for s in item.get("all_steps", [])]})
    return compact


def _chat_tokens(value, ignored=()):
    stop = {"my", "the", "a", "an", "routine", "step"} | set(ignored)
    tokens = set()
    for token in re.findall(r"[a-z0-9]+", str(value).lower()):
        if token in stop:
            continue
        if token.endswith("ing") and len(token) > 5:
            token = token[:-3]
        tokens.add(token)
    return tokens


def _chat_routine(conn, hint):
    wanted = _chat_tokens(hint)
    groups = [_snapshot(conn, row["id"]) for row in conn.execute(
        "SELECT id FROM routine_groups WHERE archived=0 ORDER BY position, created_at"
    ).fetchall()]
    matches = [group for group in groups if wanted and wanted <= _chat_tokens(group["title"])]
    return matches[0] if len(matches) == 1 else None


def _chat_step(group, hint):
    wanted = _chat_tokens(hint)
    matches = [step for step in group["steps"] if wanted and wanted <= _chat_tokens(step["title"])]
    return matches[0] if len(matches) == 1 else None


def _reorder_step(conn, group, step_id, anchor_id, place, time_zone):
    _freeze_past(conn, group["id"], time_zone)
    ordered = [step["id"] for step in sorted(group["steps"], key=lambda step: step["position"])]
    ordered.remove(step_id)
    anchor_index = ordered.index(anchor_id)
    ordered.insert(anchor_index + (1 if place == "after" else 0), step_id)
    for position, item_id in enumerate(ordered):
        conn.execute("UPDATE routine_steps SET position=?,updated_at=? WHERE id=?", (position, _now(), item_id))
    return _save_version(conn, group["id"], effective_day=local_day(time_zone))


_CHAT_REFERENCE_PHRASES = {
    "it", "that", "this", "those", "these", "one", "the one",
    "the one we just added", "the one just added", "the last one",
    "the second one", "the task", "the item", "the step",
}


def _chat_reference_placeholder(value):
    normalized = re.sub(r"\s+", " ", str(value or "").strip(" .!?\"'").lower())
    return normalized in _CHAT_REFERENCE_PHRASES or bool(re.fullmatch(
        r"(?:the\s+)?(?:one|item|step)\s+(?:we\s+)?(?:just\s+)?(?:added|created|discussed)",
        normalized,
    ))


def _chat_explicit_literal(raw, value):
    """Allow a placeholder-looking name only when the user explicitly quotes it."""
    wanted = re.escape(str(value or "").strip(" \"'"))
    return bool(wanted and re.search(rf"[\"']{wanted}[\"']", str(raw or ""), re.I))


def _chat_clarification(resolution, default="Which item do you mean?"):
    if isinstance(resolution, dict):
        value = str(resolution.get("clarification") or "").strip()
        if value:
            return value[:240]
    return default


def _chat_contextual_action(conn, raw, time_zone, resolution):
    """Execute a validated reference-aware routine action.

    Reference semantics are produced by the existing turn planner from recent
    user/assistant history. This adapter resolves those semantics exclusively
    against persisted routine IDs and names, then reads the result back before
    returning a success confirmation.
    """
    if not isinstance(resolution, dict):
        return None
    status = str(resolution.get("status") or "none").lower()
    if status == "ambiguous":
        return _chat_clarification(resolution, "Which item do you want me to change?")
    if status != "resolved":
        return None

    operation = str(resolution.get("operation") or "").lower()
    if operation not in {
        "add_step", "move_step", "delete_step", "rename_step", "rename_routine",
    }:
        return None
    names = resolution.get("names")
    if not isinstance(names, list):
        names = [resolution.get("name")]
    names = [str(name or "").strip()[:160] for name in names if str(name or "").strip()]
    if not names or len(names) > 10 or any(_chat_reference_placeholder(name) for name in names):
        return _chat_clarification(resolution, "Which item do you want me to change?")

    target_name = str(resolution.get("target_name") or "").strip()
    group = _chat_routine(conn, target_name) if target_name else None
    if group is None:
        return _chat_clarification(resolution, "Which routine do you mean?")

    before = _snapshot(conn, group["id"])
    before_ids = {step["id"] for step in before["steps"]}

    if operation == "add_step":
        if any(_chat_step(before, name) for name in names):
            duplicate = next(name for name in names if _chat_step(before, name))
            return f"{_chat_step(before, duplicate)['title']} is already in {before['title']}."
        relation = str(resolution.get("relation") or "").lower()
        anchor_name = str(resolution.get("anchor_name") or "").strip()
        anchor = _chat_step(before, anchor_name) if anchor_name else None
        if relation in {"before", "after"} and anchor is None:
            return _chat_clarification(
                resolution, f"Which step should {names[0]} go {relation}?"
            )
        item = before
        added_ids = []
        current_anchor = anchor
        for name in names:
            item = add_step(conn, group["id"], {"title": name}, time_zone)
            added = next(
                (step for step in item["steps"] if step["title"].casefold() == name.casefold()),
                None,
            )
            if added is None:
                raise RuntimeError("Routine step addition was not saved")
            added_ids.append(added["id"])
            if current_anchor is not None:
                item = _reorder_step(
                    conn, item, added["id"], current_anchor["id"], relation, time_zone
                )
                if relation == "after":
                    current_anchor = added

        saved = _snapshot(conn, group["id"])
        saved_ids = {step["id"] for step in saved["steps"]}
        if not before_ids.issubset(saved_ids):
            raise RuntimeError("Routine step addition changed existing steps")
        for name, step_id in zip(names, added_ids):
            matches = [
                step for step in saved["steps"]
                if step["title"].casefold() == name.casefold()
            ]
            if len(matches) != 1 or matches[0]["id"] != step_id:
                raise RuntimeError("Routine step addition failed semantic verification")
        if anchor is not None:
            ordered = [step["id"] for step in saved["steps"]]
            first_added = ordered.index(added_ids[0])
            last_added = ordered.index(added_ids[-1])
            anchor_index = ordered.index(anchor["id"])
            valid = first_added > anchor_index if relation == "after" else last_added < anchor_index
            if not valid:
                raise RuntimeError("Routine step position failed semantic verification")
        joined = ", ".join(names)
        position = f", {relation} {anchor['title']}" if anchor is not None else ""
        return f"Added {joined} to {saved['title']}{position}."

    if operation == "rename_routine":
        new_name = str(resolution.get("new_name") or "").strip()[:160]
        if not new_name or _chat_reference_placeholder(new_name):
            return _chat_clarification(resolution, "What should I rename it to?")
        saved = update_routine(conn, group["id"], {"title": new_name}, time_zone)
        if saved["title"] != new_name:
            raise RuntimeError("Routine rename failed semantic verification")
        return f"Renamed {before['title']} to {saved['title']}."

    step = _chat_step(before, names[0])
    if step is None:
        return _chat_clarification(resolution, f"I couldn't find {names[0]} in {before['title']}.")

    if operation == "move_step":
        relation = str(resolution.get("relation") or "").lower()
        anchor_name = str(resolution.get("anchor_name") or "").strip()
        anchor = _chat_step(before, anchor_name)
        if relation not in {"before", "after"} or anchor is None or anchor["id"] == step["id"]:
            return _chat_clarification(resolution, "Where should I move it?")
        saved = _reorder_step(conn, before, step["id"], anchor["id"], relation, time_zone)
        ordered = [item["id"] for item in saved["steps"]]
        expected_delta = 1 if relation == "after" else -1
        if ordered.index(step["id"]) - ordered.index(anchor["id"]) != expected_delta:
            raise RuntimeError("Routine step order failed semantic verification")
        if {item["id"] for item in saved["steps"]} != before_ids:
            raise RuntimeError("Routine reorder changed the routine's steps")
        return f"Moved {step['title']} {relation} {anchor['title']} in {saved['title']}."

    if operation == "delete_step":
        saved = delete_step(conn, step["id"], time_zone)
        if any(item["id"] == step["id"] for item in saved["steps"]):
            raise RuntimeError("Routine step deletion failed semantic verification")
        if {item["id"] for item in saved["steps"]} != before_ids - {step["id"]}:
            raise RuntimeError("Routine step deletion changed unrelated steps")
        return f"Removed {step['title']} from {saved['title']}."

    new_name = str(resolution.get("new_name") or "").strip()[:160]
    if not new_name or _chat_reference_placeholder(new_name):
        return _chat_clarification(resolution, "What should I rename it to?")
    if operation == "rename_step":
        saved = update_step(conn, step["id"], {"title": new_name}, time_zone)
        renamed = next((item for item in saved["steps"] if item["id"] == step["id"]), None)
        if renamed is None or renamed["title"] != new_name:
            raise RuntimeError("Routine step rename failed semantic verification")
        return f"Renamed {step['title']} to {new_name} in {saved['title']}."
    raise RuntimeError("Unsupported contextual routine operation")


def chat_action(conn, text, time_zone="UTC", conversation=None, reference_resolution=None):
    """Deterministic high-confidence actions; ambiguous requests fall through."""
    raw = re.sub(r"[*_`]", "", str(text or "").strip())
    lower = raw.lower()
    contextual_reply = _chat_contextual_action(
        conn, raw, time_zone, reference_resolution
    )
    if contextual_reply is not None:
        return contextual_reply
    water = re.search(r"(?:drank|drink|log(?:ged)?|add)\s+(\d+(?:\.\d+)?)\s*(ml|millilit(?:er|re)s?|l|lit(?:er|re)s?)\b", lower)
    if water and ("water" in lower or "drank" in lower):
        amount = float(water.group(1)) * (1000 if water.group(2) in {"l", "liter", "litre", "liters", "litres"} else 1)
        status = log_water(conn, amount, time_zone=time_zone, idempotency_key=f"chat:{uuid.uuid5(uuid.NAMESPACE_URL, raw + local_day(time_zone)).hex}")
        return f"Logged {amount:g} mL. You're at {status['total_ml']:g} of {status['goal_ml']:g} mL today."
    state = get_state(conn, time_zone=time_zone)
    if "how much water" in lower or "water do i have left" in lower:
        h = state["hydration"]
        return f"You've logged {h['total_ml']:g} mL today. You have {max(0, h['goal_ml'] - h['total_ml']):g} mL left to reach your {h['goal_ml']:g} mL goal."
    move = re.search(
        r"\bmove\s+(?:my\s+)?(.+?)(?:\s+night)?\s+from\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+to\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        raw, re.I | re.S,
    )
    if move:
        step_hint, old_name, new_name = move.groups()
        names = {name: index for index, name in enumerate(("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"))}
        candidates = []
        for row in conn.execute("SELECT id FROM routine_groups WHERE archived=0").fetchall():
            group = _snapshot(conn, row["id"])
            for step in group["steps"]:
                if step_hint.lower().strip() in step["title"].lower():
                    candidates.append((group, step))
        if len(candidates) == 1:
            group, step = candidates[0]
            days = _days(step.get("schedule_days"))
            old_day, new_day = names[old_name.lower()], names[new_name.lower()]
            if old_day not in days:
                return f"{step['title']} is not currently scheduled for {old_name.title()}."
            days = sorted({new_day if value == old_day else value for value in days})
            update_step(conn, step["id"], {"schedule_type": "weekdays", "schedule_days": days}, time_zone)
            return f"Moved {step['title']} from {old_name.title()} to {new_name.title()} in {group['title']}."
    # An explicit "routine named X" wins over descriptive words before
    # "routine" (for example, "create a daily routine named Morning").
    create = re.search(
        r"\broutine\s+(?:named|called)\s+[\"']?([^\"'\n,]+?)[\"']?"
        r"(?=\s+(?:in\b|with\b|repeating\b|that\b)|[,\n.]|$)(.*)$",
        raw, re.I | re.S,
    )
    if not create:
        create = re.search(
            r"\b(?:create|make|set\s+up)\s+(?:(?:a|my)\s+)?(.+?)\s+routine\b(.*)$",
            raw, re.I | re.S,
        )
    if create:
        day_names = {name: index for index, name in enumerate(("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"))}
        tail = create.group(2).strip(" .!?:")
        schedule_text = tail.lower()
        selected = [index for name, index in day_names.items() if name in schedule_text]
        if "every day" in schedule_text or "every morning" in schedule_text or "daily" in lower or "monday through sunday" in schedule_text:
            selected = list(range(7))
        elif "weekday" in schedule_text and not selected:
            selected = list(range(5))
        if not selected:
            selected = list(range(7))
        steps_text = ""
        steps_match = re.search(
            r"(?:^|\b)(?:with|including|containing)\s+(?:(?:the|these)\s+)?"
            r"(?:(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+)?"
            r"(?:steps?\s*)?(?:in\s+(?:this\s+exact\s+)?order\s*)?:?\s*(.+)$",
            tail, re.I | re.S,
        )
        if steps_match:
            steps_text = steps_match.group(1)
            steps_text = re.split(
                r"\.\s+(?=(?:schedule|if|verify|make|each|use|do\s+not|the\s+routine)\b)",
                steps_text, maxsplit=1, flags=re.I,
            )[0]
            steps_text = re.sub(
                r"\s+(?:every\s+day|daily|on\s+weekdays?|on\s+(?:(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s*,?\s*(?:and\s+)?|$))+)[.!?]*$",
                "", steps_text, flags=re.I,
            ).strip()
        step_titles = []
        if steps_text:
            numbered = re.findall(r"(?m)^\s*\d+[.)]\s*(.+?)\s*$", steps_text)
            values = numbered or re.split(r"\s*(?:,|;|\band\b)\s*", steps_text, flags=re.I)
            for value in values:
                title = re.sub(r"^\s*(?:\d+[.)]|[-•])\s*", "", value).strip(" .")
                if title:
                    step_titles.append(title[:160])
        name = create.group(1).strip().title()
        item, existed = create_or_populate_routine(conn, {
            "title": name,
            "schedule_days": selected,
            "timezone": time_zone,
            "steps": [{"title": title} for title in step_titles],
        })
        labels = "every day" if len(selected) == 7 else ", ".join(WEEKDAYS[index].title() for index in selected)
        if step_titles:
            verb = "Updated" if existed else "Created"
            return f"{verb} {item['title']} for {labels} with {len(step_titles)} steps: " + ", ".join(step_titles) + "."
        if existed:
            return f"{item['title']} already exists. Tell me which steps to add."
        return f"Created {item['title']} for {labels}. It has no steps yet, so you can add exactly what you want."
    rename_routine = re.search(r"\brename\s+(?:my\s+)?(.+?)\s+routine\s+to\s+(.+?)[.!]?$", raw, re.I)
    if rename_routine:
        old_hint, new_title = (part.strip(" \"'") for part in rename_routine.groups())
        group = _chat_routine(conn, old_hint)
        if group:
            item = update_routine(conn, group["id"], {"title": new_title}, time_zone)
            if item["title"] != new_title:
                raise RuntimeError("Routine rename was not saved")
            return f"Renamed {group['title']} to {item['title']}."
    schedule_routine = re.search(
        r"\b(?:change|set|schedule)\s+(?:my\s+)?(.+?)\s+routine(?:'s)?\s+schedule\s+(?:to|for)\s+(.+?)[.!]?$",
        raw, re.I,
    )
    if schedule_routine:
        routine_hint, schedule_hint = schedule_routine.groups()
        group = _chat_routine(conn, routine_hint)
        if group:
            names = {name: index for index, name in enumerate(("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"))}
            schedule_lower = schedule_hint.lower()
            if any(value in schedule_lower for value in ("daily", "every day", "monday through sunday")):
                days = list(range(7))
            elif "weekday" in schedule_lower:
                days = list(range(5))
            else:
                days = [index for name, index in names.items() if name in schedule_lower]
            if days:
                item = update_routine(conn, group["id"], {"schedule_days": days}, time_zone)
                if item["schedule_days"] != days:
                    raise RuntimeError("Routine schedule was not saved")
                return f"Updated {item['title']} to run on " + ", ".join(WEEKDAYS[index].title() for index in days) + "."
    remove = re.search(r"\b(?:remove|delete)\s+(?:the\s+)?(.+?)\s+from\s+(?:my\s+)?(.+?)\s+routine\b", raw, re.I)
    if remove:
        step_hint, routine_hint = (part.strip() for part in remove.groups())
        if _chat_reference_placeholder(step_hint) and not _chat_explicit_literal(raw, step_hint):
            return "Which item do you want me to remove?"
        group = _chat_routine(conn, routine_hint)
        step = _chat_step(group, step_hint) if group else None
        if group and step:
            item = delete_step(conn, step["id"], time_zone)
            if any(saved["id"] == step["id"] for saved in item["steps"]):
                raise RuntimeError("Routine step deletion was not saved")
            return f"Removed {step['title']} from {item['title']}."
    rename_step = re.search(
        r"\brename\s+(?:the\s+)?(.+?)\s+(?:step\s+)?to\s+(.+?)\s+in\s+(?:my\s+)?(.+?)\s+routine\b",
        raw, re.I,
    )
    if rename_step:
        step_hint, new_title, routine_hint = (part.strip(" \"'") for part in rename_step.groups())
        if _chat_reference_placeholder(step_hint) and not _chat_explicit_literal(raw, step_hint):
            return "Which item do you want me to rename?"
        group = _chat_routine(conn, routine_hint)
        step = _chat_step(group, step_hint) if group else None
        if group and step:
            item = update_step(conn, step["id"], {"title": new_title}, time_zone)
            saved = next((saved for saved in item["steps"] if saved["id"] == step["id"]), None)
            if not saved or saved["title"] != new_title:
                raise RuntimeError("Routine step rename was not saved")
            return f"Renamed {step['title']} to {new_title} in {item['title']}."
    reorder = re.search(
        r"\bmove\s+(.+?)\s+(before|after)\s+(.+?)\s+in\s+(?:my\s+)?(.+?)\s+routine\b",
        raw, re.I,
    )
    if reorder:
        step_hint, place, anchor_hint, routine_hint = (part.strip() for part in reorder.groups())
        if (
            _chat_reference_placeholder(step_hint)
            or _chat_reference_placeholder(anchor_hint)
        ) and not _chat_explicit_literal(raw, step_hint):
            return "Which item do you want me to move, and where should it go?"
        group = _chat_routine(conn, routine_hint)
        step = _chat_step(group, step_hint) if group else None
        anchor = _chat_step(group, anchor_hint) if group else None
        if group and step and anchor and step["id"] != anchor["id"]:
            item = _reorder_step(conn, group, step["id"], anchor["id"], place.lower(), time_zone)
            ids = [saved["id"] for saved in sorted(item["steps"], key=lambda saved: saved["position"])]
            expected = ids.index(anchor["id"]) + (1 if place.lower() == "after" else -1)
            if ids.index(step["id"]) != expected:
                raise RuntimeError("Routine step order was not saved")
            return f"Moved {step['title']} {place.lower()} {anchor['title']} in {item['title']}."
    add = re.search(
        r"\badd\s+(.+?)(?:\s+(after|before)\s+(.+?))?\s+(?:to|in)\s+(?:my\s+)?(.+?)\s+routine\b",
        raw, re.I,
    )
    if add:
        new_title, place, anchor_hint, routine_hint = add.groups()
        new_title, routine_hint = new_title.strip(), routine_hint.strip()
        if _chat_reference_placeholder(new_title) and not _chat_explicit_literal(raw, new_title):
            return "Which item do you want me to add?"
        new_title = new_title.strip(" \"'")
        group = _chat_routine(conn, routine_hint)
        if group:
            existing = _chat_step(group, new_title)
            if existing:
                return f"{existing['title']} is already in {group['title']}."
            item = add_step(conn, group["id"], {"title": new_title}, time_zone)
            added = next((step for step in item["steps"] if step["title"].casefold() == new_title.casefold()), None)
            if not added:
                raise RuntimeError("Routine step addition was not saved")
            if place and anchor_hint:
                anchor = _chat_step(item, anchor_hint)
                if anchor:
                    item = _reorder_step(conn, item, added["id"], anchor["id"], place.lower(), time_zone)
            return f"Added {new_title} to {item['title']}."
    if "routine" in lower and any(word in lower for word in ("show", "list", "what", "which")):
        groups = [_snapshot(conn, row["id"]) for row in conn.execute(
            "SELECT id FROM routine_groups WHERE archived=0 ORDER BY position, created_at"
        ).fetchall()]
        hint_tokens = set(re.findall(r"[a-z]+", lower)) - {
            "show", "list", "what", "which", "is", "are", "in", "my", "the", "routine", "steps", "scheduled", "for", "of",
        }
        matches = [
            group for group in groups
            if set(re.findall(r"[a-z]+", group["title"].lower())) <= hint_tokens
        ]
        if len(matches) == 1:
            group = matches[0]
            steps = ", ".join(step["title"] for step in group["steps"]) or "no steps yet"
            return f"{group['title']} has {steps}."
    # Complete a specifically named unfinished step.
    if any(word in lower for word in ("did my", "done my", "just did", "completed")):
        matches = []
        for routine in state["routines"]:
            for step in routine["steps"]:
                if not step["complete"] and step["title"].lower() in lower:
                    matches.append((routine, step))
        if len(matches) == 1:
            routine, step = matches[0]
            item = set_step(conn, routine["id"], step["id"], completed=True, time_zone=time_zone)
            suffix = " The whole routine is complete." if item["status"] == "completed" else ""
            return f"Done — marked {step['title']} complete in {routine['title']}.{suffix}"
    return None


def api_action(conn, payload, time_zone="UTC"):
    action = payload.get("action")
    if action == "create_routine": return create_routine(conn, payload)
    if action == "update_routine": return update_routine(conn, payload["routine_id"], payload.get("changes") or {}, time_zone)
    if action == "duplicate_routine": return duplicate_routine(conn, payload["routine_id"])
    if action == "delete_routine": return delete_routine(conn, payload["routine_id"], bool(payload.get("delete_history")))
    if action in {"add_step", "add_routine_step"}: return add_step(conn, payload["routine_id"], payload, time_zone)
    if action == "update_step": return update_step(conn, payload["step_id"], payload.get("changes") or {}, time_zone)
    if action == "delete_step": return delete_step(conn, payload["step_id"], time_zone)
    if action == "set_step_exception": return set_step_exception(conn, payload["routine_id"], payload["step_id"], payload["date"], payload["exception_action"], payload.get("substitute_title", ""), time_zone)
    if action == "set_step": return set_step(conn, payload["routine_id"], payload["step_id"], payload.get("value"), payload.get("completed"), payload.get("date"), time_zone, payload.get("idempotency_key"))
    if action == "set_routine": return set_routine(conn, payload["routine_id"], bool(payload.get("completed")), payload.get("date"), time_zone, payload.get("idempotency_key"))
    if action == "log_water": return log_water(conn, payload["amount_ml"], time_zone, payload.get("logged_at"), payload.get("beverage", "water"), payload.get("idempotency_key"))
    if action == "update_hydration": return update_hydration(conn, payload)
    if action in {"update_hydration_entry", "delete_hydration_entry"}: return hydration_entry_action(conn, payload["entry_id"], "update" if action.startswith("update") else "delete", payload)
    raise ValueError("Unknown routine action")
