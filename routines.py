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
    return item


def _save_version(conn, routine_id, increment=True):
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
        (routine_id, date.today().isoformat()),
    ).fetchall()
    for row in live_rows:
        conn.execute(
            "UPDATE routine_daily_instances SET routine_version=?,snapshot_json=?,updated_at=? WHERE id=?",
            (item["version"], json.dumps(item), _now(), row["id"]),
        )
        _recalculate(conn, row["id"])
    return item


def _freeze_past(conn, routine_id):
    """Materialize old scheduled days before a structural edit.

    This makes historical missed/partial days use the schedule and step
    snapshot that was actually active then, rather than today's definition.
    """
    snapshot = _snapshot(conn, routine_id)
    cursor = date.fromisoformat(snapshot["created_local_date"])
    end = date.today() - timedelta(days=1)
    while cursor <= end:
        key = cursor.isoformat()
        if _scheduled(snapshot, key):
            _instance(conn, routine_id, key, "UTC", create=True)
        cursor += timedelta(days=1)


def create_routine(conn, payload, today=None):
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
    conn.execute("""
        INSERT INTO routine_steps
        (id,routine_id,title,step_type,target,unit,required,linked_hydration,position,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        step_id, routine_id, title, kind, target, str(payload.get("unit") or "")[:30],
        int(payload.get("required", True) is not False), int(bool(payload.get("linked_hydration"))),
        int(position), now, now,
    ))
    return step_id


def update_routine(conn, routine_id, changes):
    _freeze_past(conn, routine_id)
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
    return _save_version(conn, routine_id)


def add_step(conn, routine_id, payload):
    _freeze_past(conn, routine_id)
    _insert_step(conn, routine_id, payload)
    return _save_version(conn, routine_id)


def update_step(conn, step_id, changes):
    row = conn.execute("SELECT routine_id FROM routine_steps WHERE id=?", (step_id,)).fetchone()
    if not row:
        raise ValueError("Step not found")
    _freeze_past(conn, row["routine_id"])
    allowed = {"title", "step_type", "target", "unit", "required", "linked_hydration", "position"}
    fields, values = [], []
    for key in allowed:
        if key not in changes:
            continue
        value = changes[key]
        if key == "step_type" and value not in STEP_TYPES:
            raise ValueError("Invalid step type")
        if key == "target":
            value = float(value)
            if value <= 0:
                raise ValueError("Step target must be greater than zero")
        if key in {"required", "linked_hydration"}:
            value = int(bool(value))
        fields.append(f"{key}=?")
        values.append(value)
    if fields:
        values.extend([_now(), step_id])
        conn.execute(f"UPDATE routine_steps SET {', '.join(fields)}, updated_at=? WHERE id=?", values)
    return _save_version(conn, row["routine_id"])


def delete_step(conn, step_id):
    row = conn.execute("SELECT routine_id FROM routine_steps WHERE id=?", (step_id,)).fetchone()
    if not row:
        raise ValueError("Step not found")
    _freeze_past(conn, row["routine_id"])
    conn.execute("DELETE FROM routine_steps WHERE id=?", (step_id,))
    return _save_version(conn, row["routine_id"])


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
    for step in snapshot.get("steps", []):
        progress = progress_rows.get(step["id"], {})
        value = float(progress.get("value") or 0)
        complete = value >= float(step.get("target") or 1)
        if step.get("required", 1):
            required += 1
            completed_required += int(complete)
        steps.append({**step, "value": value, "complete": complete, "completed_at": progress.get("completed_at")})
    status = "completed" if required == completed_required else ("partial" if any(s["value"] > 0 for s in steps) else "incomplete")
    return {
        **snapshot, "instance_id": instance["id"], "local_date": instance["local_date"],
        "status": status, "completed_at": instance.get("completed_at"), "steps": steps,
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
    for step in snapshot.get("steps", []):
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
            items.append({**snapshot, "status": "not_scheduled", "progress": 0, "completed_steps": 0, "required_steps": len([s for s in snapshot["steps"] if s["required"]]), "steps": [{**s, "value": 0, "complete": False, "completed_at": None} for s in snapshot["steps"]]})
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
    compact = {"local_date": state["local_date"], "routines": [], "hydration": {k: state["hydration"][k] for k in ("total_ml", "goal_ml", "progress")}}
    for item in state["routines"]:
        stats = routine_statistics(conn, item["id"], state["local_date"], 35)
        compact["routines"].append({"id": item["id"], "title": item["title"], "status": item["status"], "completed_steps": item["completed_steps"], "required_steps": item["required_steps"], "schedule_days": item["schedule_days"], "current_streak": stats["current_streak"], "longest_streak": stats["longest_streak"], "recent_completion_rate": stats["completion_rate"], "recent_daily": stats["daily"], "steps": [{"id": s["id"], "title": s["title"], "value": s["value"], "target": s["target"], "complete": s["complete"]} for s in item["steps"]]})
    return compact


def chat_action(conn, text, time_zone="UTC"):
    """Deterministic high-confidence actions; ambiguous requests fall through."""
    raw, lower = str(text or "").strip(), str(text or "").lower()
    water = re.search(r"(?:drank|drink|log(?:ged)?|add)\s+(\d+(?:\.\d+)?)\s*(ml|millilit(?:er|re)s?|l|lit(?:er|re)s?)\b", lower)
    if water and ("water" in lower or "drank" in lower):
        amount = float(water.group(1)) * (1000 if water.group(2) in {"l", "liter", "litre", "liters", "litres"} else 1)
        status = log_water(conn, amount, time_zone=time_zone, idempotency_key=f"chat:{uuid.uuid5(uuid.NAMESPACE_URL, raw + local_day(time_zone)).hex}")
        return f"Logged {amount:g} mL. You're at {status['total_ml']:g} of {status['goal_ml']:g} mL today."
    state = get_state(conn, time_zone=time_zone)
    if "how much water" in lower or "water do i have left" in lower:
        h = state["hydration"]
        return f"You've logged {h['total_ml']:g} mL today. You have {max(0, h['goal_ml'] - h['total_ml']):g} mL left to reach your {h['goal_ml']:g} mL goal."
    create = re.search(r"\bcreate\s+(?:a\s+)?(.+?)\s+routine\s+(?:for|on)\s+(.+?)(?:[.!?]|$)", raw, re.I)
    if create:
        day_names = {name: index for index, name in enumerate(("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"))}
        selected = [index for name, index in day_names.items() if name in create.group(2).lower()]
        if selected:
            name = create.group(1).strip().title()
            item = create_routine(conn, {"title": name, "schedule_days": selected, "timezone": time_zone})
            labels = ", ".join(WEEKDAYS[index].title() for index in selected)
            return f"Created {item['title']} for {labels}. It has no steps yet, so you can add exactly what you want."
    add = re.search(r"\badd\s+(.+?)\s+after\s+(.+?)\s+in\s+(?:my\s+)?(.+?)\s+routine\b", raw, re.I)
    if add:
        new_title, after_title, routine_hint = (part.strip() for part in add.groups())
        groups = [_snapshot(conn, row["id"]) for row in conn.execute("SELECT id FROM routine_groups WHERE archived=0").fetchall()]
        hint_tokens = set(re.findall(r"[a-z]+", routine_hint.lower()))
        matches = [group for group in groups if hint_tokens & set(re.findall(r"[a-z]+", group["title"].lower()))]
        if len(matches) == 1:
            group = matches[0]
            def action_tokens(value):
                tokens = set()
                for token in re.findall(r"[a-z]+", value.lower()):
                    if token in {"my", "the", "a", "an"}:
                        continue
                    if token.endswith("ing") and len(token) > 5:
                        token = token[:-3]
                    tokens.add(token)
                return tokens
            wanted = action_tokens(after_title)
            after = next((step for step in group["steps"] if wanted and wanted <= action_tokens(step["title"])), None)
            if after:
                _freeze_past(conn, group["id"])
                conn.execute("UPDATE routine_steps SET position=position+1 WHERE routine_id=? AND position>?", (group["id"], after["position"]))
                _insert_step(conn, group["id"], {"title": new_title}, after["position"] + 1)
                _save_version(conn, group["id"])
                return f"Added {new_title} after {after['title']} in {group['title']}."
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
    if action == "update_routine": return update_routine(conn, payload["routine_id"], payload.get("changes") or {})
    if action == "duplicate_routine": return duplicate_routine(conn, payload["routine_id"])
    if action == "delete_routine": return delete_routine(conn, payload["routine_id"], bool(payload.get("delete_history")))
    if action == "add_step": return add_step(conn, payload["routine_id"], payload)
    if action == "update_step": return update_step(conn, payload["step_id"], payload.get("changes") or {})
    if action == "delete_step": return delete_step(conn, payload["step_id"])
    if action == "set_step": return set_step(conn, payload["routine_id"], payload["step_id"], payload.get("value"), payload.get("completed"), payload.get("date"), time_zone, payload.get("idempotency_key"))
    if action == "set_routine": return set_routine(conn, payload["routine_id"], bool(payload.get("completed")), payload.get("date"), time_zone, payload.get("idempotency_key"))
    if action == "log_water": return log_water(conn, payload["amount_ml"], time_zone, payload.get("logged_at"), payload.get("beverage", "water"), payload.get("idempotency_key"))
    if action == "update_hydration": return update_hydration(conn, payload)
    if action in {"update_hydration_entry", "delete_hydration_entry"}: return hydration_entry_action(conn, payload["entry_id"], "update" if action.startswith("update") else "delete", payload)
    raise ValueError("Unknown routine action")
