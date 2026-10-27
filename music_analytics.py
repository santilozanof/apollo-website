"""Period-aware, server-side exploration of Apollo's recorded music history.

The period model is deliberately independent of recap design, so a future
recap renderer can consume any of the five period kinds.
"""

import calendar
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import music_history


KINDS = {"daily", "weekly", "monthly", "yearly", "lifetime"}
ENTITIES = {"artists", "tracks", "albums"}
METRICS = {"plays", "verified", "estimated"}


def period(kind, anchor=None, tz_name="UTC"):
    if kind not in KINDS:
        raise ValueError("Unknown listening time frame")
    try:
        zone = ZoneInfo(tz_name)
    except Exception as error:
        raise ValueError("Unknown time zone") from error
    today = datetime.now(zone).date()
    try:
        selected = date.fromisoformat(anchor) if anchor else today
    except (TypeError, ValueError) as error:
        raise ValueError("Date must be YYYY-MM-DD") from error
    if selected > today:
        raise ValueError("Future listening periods are unavailable")
    if kind == "daily":
        first, last = selected, selected + timedelta(days=1)
        label = first.strftime("%B %-d, %Y")
    elif kind == "weekly":
        first = selected - timedelta(days=selected.weekday())
        last = first + timedelta(days=7)
        label = f"{first.strftime('%b %-d')} – { (last - timedelta(days=1)).strftime('%b %-d, %Y')}"
    elif kind == "monthly":
        first = selected.replace(day=1)
        last = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
        label = first.strftime("%B %Y")
    elif kind == "yearly":
        first, last = date(selected.year, 1, 1), date(selected.year + 1, 1, 1)
        label = str(selected.year)
    else:
        first, last, label = None, None, "Available history"
    start = datetime.combine(first, datetime.min.time(), zone).astimezone(timezone.utc).isoformat() if first else None
    end = datetime.combine(last, datetime.min.time(), zone).astimezone(timezone.utc).isoformat() if last else None
    return {"kind": kind, "anchor": selected.isoformat(), "timezone": tz_name,
            "start": start, "end": end, "label": label,
            "can_next": bool(last and last <= today),
            "first_date": first.isoformat() if first else None,
            "end_date": last.isoformat() if last else None}


def _where(p):
    conditions, values = [], []
    if p["start"]:
        conditions.append("l.event_at >= ?")
        values.append(p["start"])
    if p["end"]:
        conditions.append("l.event_at < ?")
        values.append(p["end"])
    return (" WHERE " + " AND ".join(conditions)) if conditions else "", values


def _spotify(kind, identifier):
    return f"https://open.spotify.com/{kind}/{identifier}" if music_history._valid_id(identifier) else None


def _source(conn, p, only=None):
    """One bounded SQL aggregate per entity; no lifetime event list reaches JS."""
    where, values = _where(p)
    rows = {}
    if only in (None, "artists"):
        rows["artists"] = [dict(row) for row in conn.execute(f"""
        SELECT c.artist_key AS entity_key, MAX(c.artist_name) AS name,
               MAX(c.artist_id) AS spotify_id, MAX(a.image_url) AS image_url,
               COUNT(*) AS plays, SUM(CASE WHEN l.ms_played IS NOT NULL THEN l.ms_played ELSE 0 END) AS verified_ms,
               SUM(l.ms_played IS NOT NULL) AS verified_events,
               MIN(l.event_at) AS first_at, MAX(l.event_at) AS last_at
        FROM music_listen_artists c JOIN music_listens l ON l.id=c.listen_id
        LEFT JOIN music_artists a ON a.artist_key=c.artist_key
        {where} GROUP BY c.artist_key
        """, values)]
    if only in (None, "tracks"):
        rows["tracks"] = [dict(row) for row in conn.execute(f"""
        SELECT l.track_key AS entity_key, MAX(l.track_name) AS name,
               MAX(l.artist_name) AS artist_name, MAX(l.album_name) AS album_name,
               MAX(l.track_id) AS spotify_id,
               COALESCE(MAX(l.artwork_url), MAX(t.artwork_url), MAX(a.artwork_url)) AS image_url,
               COUNT(*) AS plays, SUM(CASE WHEN l.ms_played IS NOT NULL THEN l.ms_played ELSE 0 END) AS verified_ms,
               SUM(l.ms_played IS NOT NULL) AS verified_events,
               MIN(l.event_at) AS first_at, MAX(l.event_at) AS last_at
        FROM music_listens l LEFT JOIN music_tracks t ON t.track_key=l.track_key
        LEFT JOIN music_albums a ON a.album_key=t.album_key
        {where} GROUP BY l.track_key
        """, values)]
    if only in (None, "albums"):
        rows["albums"] = [dict(row) for row in conn.execute(f"""
        SELECT COALESCE('spotify:' || l.album_id, 'name:' || lower(l.album_name) || '|' || lower(l.artist_name)) AS entity_key,
               MAX(l.album_name) AS name, MAX(l.artist_name) AS artist_name, MAX(l.album_id) AS spotify_id,
               COALESCE(MAX(a.artwork_url), MAX(l.artwork_url), MAX(t.artwork_url)) AS image_url,
               COUNT(*) AS plays, SUM(CASE WHEN l.ms_played IS NOT NULL THEN l.ms_played ELSE 0 END) AS verified_ms,
               SUM(l.ms_played IS NOT NULL) AS verified_events,
               MIN(l.event_at) AS first_at, MAX(l.event_at) AS last_at
        FROM music_listens l LEFT JOIN music_tracks t ON t.track_key=l.track_key
        LEFT JOIN music_albums a ON a.album_key=t.album_key
        {where + (' AND ' if where else ' WHERE ')}l.album_name IS NOT NULL
        GROUP BY entity_key
        """, values)]
    estimates = music_history.estimated_by_track(conn, p["start"] or "0001-01-01T00:00:00+00:00",
                                                  p["end"] or "9999-12-31T00:00:00+00:00")
    # Exact IDs only. Name-only exports cannot safely be matched to observed playback.
    for row in rows.get("tracks", ()):
        row["estimated_ms"] = estimates.get(row["spotify_id"], 0) if row["spotify_id"] else 0
    estimate_by_album = Counter()
    estimate_by_artist = Counter()
    if estimates and only != "tracks":
        for item in conn.execute(f"""SELECT DISTINCT l.track_id, l.album_id, l.album_name, l.artist_name,
                                   c.artist_key FROM music_listens l LEFT JOIN music_listen_artists c ON c.listen_id=l.id
                                   {where + (' AND ' if where else ' WHERE ')} l.track_id IS NOT NULL""", values):
            amount = estimates.get(item["track_id"], 0)
            if amount:
                if item["album_name"]:
                    key = "spotify:" + item["album_id"] if item["album_id"] else "name:" + item["album_name"].lower() + "|" + item["artist_name"].lower()
                    estimate_by_album[(key, item["track_id"])] = amount
                if item["artist_key"]:
                    estimate_by_artist[(item["artist_key"], item["track_id"])] = amount
    for row in rows.get("albums", ()):
        row["estimated_ms"] = sum(amount for (key, _), amount in estimate_by_album.items() if key == row["entity_key"])
    for row in rows.get("artists", ()):
        row["estimated_ms"] = sum(amount for (key, _), amount in estimate_by_artist.items() if key == row["entity_key"])
    for entity, records in rows.items():
        spotify_kind = {"artists": "artist", "tracks": "track", "albums": "album"}[entity]
        for row in records:
            row["spotify_url"] = _spotify(spotify_kind, row.pop("spotify_id"))
            row["image_url"] = music_history._safe_art(row["image_url"])
            row["image_kind"] = "artist" if entity == "artists" and row["image_url"] else "album" if row["image_url"] else None
            row["verified_ms"] = row["verified_ms"] or 0
            row["verified_events"] = row["verified_events"] or 0
    return rows


def _rank(rows, metric):
    return sorted(rows, key=lambda row: (-row[{"plays": "plays", "verified": "verified_ms", "estimated": "estimated_ms"}[metric]],
                                         -row["plays"], row["name"].casefold(), row["entity_key"]))


def rankings(conn, kind, anchor, tz_name, entity, metric="plays", search="", limit=30, offset=0):
    if entity not in ENTITIES or metric not in METRICS:
        raise ValueError("Unknown ranking or metric")
    if len(search) > 120 or limit < 1 or limit > 50 or offset < 0 or offset > 1000000:
        raise ValueError("Invalid search or page")
    p = period(kind, anchor, tz_name)
    rows = _source(conn, p, entity)[entity]
    if search:
        needle = search.casefold().strip()
        rows = [row for row in rows if any(needle in str(row.get(field) or "").casefold()
                                            for field in ("name", "artist_name", "album_name"))]
    # Keep zero-measurement entries visible below measured entries, clearly marked unavailable.
    ordered = _rank(rows, metric)
    for i, row in enumerate(ordered):
        row["rank"] = i + 1
    return {"period": p, "entity": entity, "metric": metric, "total": len(ordered),
            "offset": offset, "limit": limit, "items": ordered[offset:offset + limit],
            "metric_available": any(row["verified_events"] if metric == "verified" else row["estimated_ms"] if metric == "estimated" else row["plays"] for row in ordered)}


def range_rankings(conn, start_date, end_date, tz_name, entity="artists", metric="plays", limit=10):
    """Inclusive local-date range, using the same aggregate as Music Insights."""
    if entity not in ENTITIES or metric not in METRICS or not 1 <= limit <= 50:
        raise ValueError("Unknown ranking or metric")
    try:
        zone = ZoneInfo(tz_name)
        first, last = date.fromisoformat(start_date), date.fromisoformat(end_date)
    except (TypeError, ValueError, KeyError) as error:
        raise ValueError("Invalid listening date range or time zone") from error
    if first > last or (last - first).days > 366 or last > datetime.now(zone).date():
        raise ValueError("Listening date range must be past dates within one year")
    start = datetime.combine(first, datetime.min.time(), zone).astimezone(timezone.utc).isoformat()
    end = datetime.combine(last + timedelta(days=1), datetime.min.time(), zone).astimezone(timezone.utc).isoformat()
    p = {"kind": "range", "first_date": first.isoformat(), "end_date": (last + timedelta(days=1)).isoformat(),
         "start": start, "end": end, "timezone": tz_name,
         "label": f"{first.isoformat()} through {last.isoformat()}"}
    rows = _rank(_source(conn, p, entity)[entity], metric)
    for index, row in enumerate(rows, 1):
        row["rank"] = index
    basic = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(ms_played),0), "
        "COALESCE(SUM(ms_played IS NOT NULL),0) FROM music_listens "
        "WHERE event_at >= ? AND event_at < ?", (start, end)
    ).fetchone()
    return {"period": p, "entity": entity, "metric": metric, "total": len(rows),
            "items": rows[:limit], "events": basic[0], "verified_ms": basic[1],
            "verified_events": basic[2], "duration_unknown_events": basic[0] - basic[2]}


def summary(conn, kind, anchor=None, tz_name="UTC"):
    p = period(kind, anchor, tz_name)
    where, values = _where(p)
    basic = conn.execute(f"""SELECT COUNT(*) AS events, COALESCE(SUM(ms_played),0) AS verified_ms,
                         SUM(ms_played IS NOT NULL) AS verified_events,
                         MIN(event_at) AS first_at, MAX(event_at) AS last_at
                         FROM music_listens l {where}""", values).fetchone()
    entities = _source(conn, p)
    zone = ZoneInfo(tz_name)
    bins = Counter()
    hours = Counter()
    for row in conn.execute(f"SELECT l.event_at FROM music_listens l {where}", values):
        instant = datetime.fromisoformat(row[0]).astimezone(zone)
        hours[instant.hour] += 1
        label = (f"{instant.hour:02d}:00" if kind == "daily" else
                 instant.strftime("%a") if kind == "weekly" else
                 instant.strftime("%d") if kind == "monthly" else
                 instant.strftime("%b") if kind == "yearly" else instant.strftime("%Y-%m"))
        bins[label] += 1
    if kind == "daily":
        labels = [f"{h:02d}:00" for h in range(24)]
    elif kind == "weekly":
        labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    elif kind == "monthly":
        labels = [f"{day:02d}" for day in range(1, calendar.monthrange(int(p["first_date"][:4]), int(p["first_date"][5:7]))[1] + 1)]
    elif kind == "yearly":
        labels = [date(2000, month, 1).strftime("%b") for month in range(1, 13)]
    else:
        labels = sorted(bins)
    state = conn.execute("SELECT * FROM music_sync_state WHERE provider='spotify'").fetchone()
    coverage = conn.execute("SELECT MIN(event_at), MAX(event_at) FROM music_listens").fetchone()
    imports = conn.execute("SELECT COUNT(*), MIN(first_event_at), MAX(last_event_at) FROM music_import_jobs").fetchone()
    insights = []
    if basic["events"]:
        if top_artist := _rank(entities["artists"], "plays")[:1]:
            insights.append(f"{top_artist[0]['name']} leads this period with {top_artist[0]['plays']} recorded plays.")
        if hours:
            insights.append(f"Most active hour: {hours.most_common(1)[0][0]:02d}:00 ({hours.most_common(1)[0][1]} plays).")
        new_artist_count = conn.execute(f"""
            SELECT COUNT(*) FROM (
              SELECT c.artist_key FROM music_listen_artists c JOIN music_listens l ON l.id=c.listen_id
              GROUP BY c.artist_key HAVING MIN(l.event_at) >= ? AND MIN(l.event_at) < ?
            )
        """, (p["start"] or "0001-01-01T00:00:00+00:00",
              p["end"] or "9999-12-31T00:00:00+00:00")).fetchone()[0]
        if new_artist_count and kind != "lifetime":
            insights.append(f"{new_artist_count} artist{'s' if new_artist_count != 1 else ''} first recorded in Apollo's available history this period.")
    else:
        new_artist_count = 0
    previous_events = None
    if kind != "lifetime" and p["first_date"]:
        previous = period(kind, (date.fromisoformat(p["first_date"]) - timedelta(days=1)).isoformat(), tz_name)
        previous_where, previous_values = _where(previous)
        previous_events = conn.execute(f"SELECT COUNT(*) FROM music_listens l {previous_where}", previous_values).fetchone()[0]
        if previous_events:
            difference = basic["events"] - previous_events
            insights.append(f"{abs(difference)} {'more' if difference >= 0 else 'fewer'} recorded plays than the previous {kind} period. Coverage may differ.")
    top = {entity: _rank(records, "plays")[:5] for entity, records in entities.items()}
    for records in top.values():
        for rank, row in enumerate(records, 1):
            row["rank"] = rank
    return {"period": p, "events": basic["events"], "verified_ms": basic["verified_ms"],
            "estimated_ms": sum(row["estimated_ms"] for row in entities["tracks"]),
            "verified_events": basic["verified_events"] or 0,
            "duration_unknown_events": basic["events"] - (basic["verified_events"] or 0),
            "unique_artists": len(entities["artists"]), "top": top,
            "insights": insights, "newly_recorded_artists": new_artist_count,
            "previous_events": previous_events,
            "chart": [{"label": label, "plays": bins[label]} for label in labels],
            "favorite_hour": hours.most_common(1)[0][0] if hours else None,
            "first_at": basic["first_at"], "last_at": basic["last_at"],
            "coverage": {"earliest_event": coverage[0], "latest_event": coverage[1],
                         "last_sync_at": state["last_success_at"] if state else None,
                         "latest_synced_event": datetime.fromtimestamp(state["cursor_ms"] / 1000, timezone.utc).isoformat() if state and state["cursor_ms"] else None,
                         "sync_error": state["last_error"] if state else None,
                         "coverage_warning": state["coverage_warning"] if state else None,
                         "syncing": bool(state and state["sync_started_at"] and
                                         datetime.now(timezone.utc) - datetime.fromisoformat(state["sync_started_at"]) < timedelta(minutes=3)),
                         "import_files": imports[0], "import_first": imports[1], "import_last": imports[2]},
            "methodology": "Plays are recorded events. Verified time comes from official history exports. Estimated time is observed playback progress after overlap with verified time is removed. Missing coverage and unknown duration are excluded."}


def history(conn, kind, anchor, tz_name, search="", limit=30, offset=0):
    if len(search) > 120 or limit < 1 or limit > 50 or offset < 0 or offset > 1000000:
        raise ValueError("Invalid search or page")
    p = period(kind, anchor, tz_name)
    where, values = _where(p)
    if search.strip():
        where += (" AND " if where else " WHERE ") + "(lower(l.track_name) LIKE ? OR lower(l.artist_name) LIKE ? OR lower(l.album_name) LIKE ?)"
        pattern = "%" + search.casefold() + "%"
        values += [pattern] * 3
    total = conn.execute(f"SELECT COUNT(*) FROM music_listens l {where}", values).fetchone()[0]
    rows = conn.execute(f"""SELECT l.id, l.track_key, l.track_name, l.artist_name, l.album_name, l.event_at,
                         l.ms_played, COALESCE(l.artwork_url,t.artwork_url,a.artwork_url) AS image_url,
                         l.track_id FROM music_listens l LEFT JOIN music_tracks t ON t.track_key=l.track_key
                         LEFT JOIN music_albums a ON a.album_key=t.album_key
                         {where} ORDER BY l.event_at DESC,l.id DESC LIMIT ? OFFSET ?""", (*values, limit, offset)).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["image_url"] = music_history._safe_art(item["image_url"])
        item["spotify_url"] = _spotify("track", item.pop("track_id"))
        items.append(item)
    return {"period": p, "total": total, "offset": offset, "limit": limit, "items": items}


def detail(conn, kind, anchor, tz_name, entity, key):
    if entity not in ENTITIES or not isinstance(key, str) or len(key) > 220:
        raise ValueError("Invalid music detail")
    p = period(kind, anchor, tz_name)
    rows = _source(conn, p, entity)
    chosen = next((row for row in _rank(rows[entity], "plays") if row["entity_key"] == key), None)
    if chosen is None:
        raise LookupError("No listening data for this item in the selected period")
    chosen = dict(chosen)
    chosen["rank"] = next(i for i, row in enumerate(_rank(rows[entity], "plays"), 1) if row["entity_key"] == key)
    lifetime = next((row for row in _source(conn, period("lifetime", None, tz_name), entity)[entity] if row["entity_key"] == key), None)
    where, values = _where(p)
    clause = ("c.artist_key=?" if entity == "artists" else "l.track_key=?" if entity == "tracks" else
              "COALESCE('spotify:' || l.album_id, 'name:' || lower(l.album_name) || '|' || lower(l.artist_name))=?")
    if entity == "artists":
        join = " JOIN music_listen_artists c ON c.listen_id=l.id"
    else:
        join = ""
    where += (" AND " if where else " WHERE ") + clause
    events = conn.execute(f"""SELECT l.track_key,l.track_name,l.album_name,l.event_at
                             FROM music_listens l {join} {where} ORDER BY l.event_at""", (*values, key)).fetchall()
    activity = Counter(datetime.fromisoformat(row["event_at"]).astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d") for row in events)
    songs = Counter((row["track_key"], row["track_name"]) for row in events)
    albums = Counter(row["album_name"] for row in events if row["album_name"])
    return {"period": p, "entity": entity, "item": chosen,
            "lifetime": {"plays": lifetime["plays"], "verified_ms": lifetime["verified_ms"],
                         "estimated_ms": lifetime["estimated_ms"]} if lifetime else None,
            "songs": [{"key": item[0], "name": item[1], "plays": count} for item, count in songs.most_common(10)],
            "albums": [{"name": name, "plays": count} for name, count in albums.most_common(10)],
            "activity": [{"day": day, "plays": activity[day]} for day in sorted(activity)]}
