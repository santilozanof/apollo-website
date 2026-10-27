"""Persistent Spotify listening history. A playback snapshot is never a listen."""

import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def init_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS music_artists (
            artist_key TEXT PRIMARY KEY,
            spotify_id TEXT,
            name TEXT NOT NULL,
            image_url TEXT,
            metadata_checked_at TEXT
        );
        CREATE TABLE IF NOT EXISTS music_albums (
            album_key TEXT PRIMARY KEY,
            spotify_id TEXT,
            name TEXT NOT NULL,
            artist_key TEXT,
            artwork_url TEXT
        );
        CREATE TABLE IF NOT EXISTS music_tracks (
            track_key TEXT PRIMARY KEY,
            spotify_id TEXT,
            name TEXT NOT NULL,
            artist_key TEXT NOT NULL,
            album_key TEXT,
            artwork_url TEXT
        );
        CREATE TABLE IF NOT EXISTS music_listens (
            id INTEGER PRIMARY KEY,
            source TEXT NOT NULL,
            source_key TEXT NOT NULL UNIQUE,
            source_timestamp TEXT NOT NULL,
            event_at TEXT NOT NULL,
            track_key TEXT NOT NULL,
            track_id TEXT,
            track_name TEXT NOT NULL,
            artist_name TEXT NOT NULL,
            artist_id TEXT,
            album_name TEXT,
            album_id TEXT,
            artwork_url TEXT,
            ms_played INTEGER,
            duration_ms INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_music_listens_ended ON music_listens(event_at);
        CREATE INDEX IF NOT EXISTS idx_music_listens_source_time ON music_listens(source_timestamp);
        CREATE TABLE IF NOT EXISTS music_event_sources (
            source_key TEXT PRIMARY KEY,
            listen_id INTEGER NOT NULL REFERENCES music_listens(id)
        );
        CREATE INDEX IF NOT EXISTS idx_music_listens_track ON music_listens(track_key, event_at);
        CREATE INDEX IF NOT EXISTS idx_music_listens_spotify_track_time ON music_listens(track_id, event_at);
        CREATE TABLE IF NOT EXISTS music_listen_artists (
            listen_id INTEGER NOT NULL REFERENCES music_listens(id),
            artist_key TEXT NOT NULL,
            artist_name TEXT NOT NULL,
            artist_id TEXT,
            credit_position INTEGER NOT NULL,
            PRIMARY KEY(listen_id, artist_key)
        );
        CREATE INDEX IF NOT EXISTS idx_music_listen_artists_key ON music_listen_artists(artist_key);
        CREATE TABLE IF NOT EXISTS music_playback_sample (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            observed_at TEXT NOT NULL,
            track_id TEXT,
            state_timestamp_ms INTEGER,
            progress_ms INTEGER,
            duration_ms INTEGER,
            playing INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS music_observed_intervals (
            id INTEGER PRIMARY KEY,
            track_id TEXT NOT NULL,
            start_at TEXT NOT NULL,
            end_at TEXT NOT NULL,
            estimated_ms INTEGER NOT NULL,
            UNIQUE(track_id, start_at, end_at)
        );
        CREATE INDEX IF NOT EXISTS idx_music_observed_intervals_time ON music_observed_intervals(start_at, end_at);
        CREATE TABLE IF NOT EXISTS music_sync_state (
            provider TEXT PRIMARY KEY,
            cursor_ms INTEGER,
            last_success_at TEXT,
            last_attempt_at TEXT,
            sync_started_at TEXT,
            last_error TEXT,
            retry_after_at TEXT,
            coverage_warning TEXT
        );
        CREATE TABLE IF NOT EXISTS music_import_jobs (
            id INTEGER PRIMARY KEY,
            file_name TEXT NOT NULL,
            content_sha256 TEXT NOT NULL UNIQUE,
            format TEXT NOT NULL,
            imported_count INTEGER NOT NULL,
            duplicate_count INTEGER NOT NULL,
            first_event_at TEXT,
            last_event_at TEXT,
            verified_ms INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS music_metadata_attempts (
            track_id TEXT PRIMARY KEY,
            last_attempt_at TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS music_recaps (
            month TEXT NOT NULL,
            timezone TEXT NOT NULL,
            design_version INTEGER NOT NULL,
            data_fingerprint TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(month, timezone)
        );
    """)
    conn.execute("INSERT OR IGNORE INTO music_sync_state(provider) VALUES ('spotify')")
    conn.execute("INSERT OR IGNORE INTO music_sync_state(provider) VALUES ('spotify_artists')")
    conn.execute("INSERT OR IGNORE INTO music_sync_state(provider) VALUES ('spotify_tracks')")
    conn.execute("INSERT OR IGNORE INTO music_sync_state(provider) VALUES ('spotify_playback')")
    for table, columns in {
        "music_sync_state": {"coverage_warning": "TEXT", "last_attempt_at": "TEXT", "sync_started_at": "TEXT"},
        "music_artists": {"image_url": "TEXT", "metadata_checked_at": "TEXT"},
        "music_import_jobs": {"first_event_at": "TEXT", "last_event_at": "TEXT", "verified_ms": "INTEGER NOT NULL DEFAULT 0"},
    }.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, definition in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    # Existing listening history predates credited-artist rows. Backfill only
    # rows that are missing credits, never rewrite original listening events.
    for row in conn.execute("""
        SELECT l.id, l.artist_name, l.artist_id FROM music_listens l
        WHERE NOT EXISTS (SELECT 1 FROM music_listen_artists a WHERE a.listen_id=l.id)
    """).fetchall():
        artist_id = row["artist_id"] if _valid_id(row["artist_id"]) else None
        artist_key = "spotify:" + artist_id if artist_id else _key(row["artist_name"], "", None)
        conn.execute("INSERT OR IGNORE INTO music_artists(artist_key,spotify_id,name) VALUES (?,?,?)",
                     (artist_key, artist_id, row["artist_name"]))
        conn.execute("INSERT OR IGNORE INTO music_listen_artists VALUES (?, ?, ?, ?, 0)",
                     (row["id"], artist_key, row["artist_name"], artist_id))


def _utc(value, minute_precision=False):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Listening event is missing a timestamp")
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as error:
        raise ValueError("Invalid listening timestamp") from error
    if parsed.tzinfo is None:
        # Spotify's older endTime export is UTC and has minute precision.
        if not minute_precision:
            raise ValueError("Listening timestamp needs a time zone")
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _key(name, artist, spotify_id):
    if spotify_id:
        return "spotify:" + spotify_id
    slug = re.sub(r"\s+", " ", (name + "|" + artist).casefold()).strip()
    return "name:" + hashlib.sha256(slug.encode()).hexdigest()[:24]


def _valid_id(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9]{22}", value))


def _safe_art(value):
    return value if isinstance(value, str) and value.startswith("https://i.scdn.co/image/") else None


def normalize_record(item):
    if not isinstance(item, dict):
        raise ValueError("Each listening entry must be an object")
    if "played_at" in item and isinstance(item.get("track"), dict):
        track = item["track"]
        artists = track.get("artists") or []
        first_artist = artists[0] if isinstance(artists, list) and artists and isinstance(artists[0], dict) else {}
        album = track.get("album") or {}
        if not isinstance(album, dict):
            album = {}
        source = "spotify_api"
        timestamp = _utc(item["played_at"])
        duration = track.get("duration_ms")
        duration = duration if isinstance(duration, int) and not isinstance(duration, bool) and 0 < duration < 3600000 else None
        ended = timestamp
        ms_played = None  # The API does not report listening duration.
        name = str(track.get("name") or "").strip()
        artist = str(first_artist.get("name") or "").strip()
        spotify_id = str(track.get("id") or "").strip() or None
        artist_id = str(first_artist.get("id") or "").strip() or None
        credits = [(str(a.get("name") or "").strip(), str(a.get("id") or "").strip() or None)
                   for a in artists if isinstance(a, dict) and str(a.get("name") or "").strip()]
        album_id = str(album.get("id") or "").strip() or None
        album_name = str(album.get("name") or "").strip() or None
        images = album.get("images") or []
        artwork = images[0].get("url") if isinstance(images, list) and images and isinstance(images[0], dict) else None
    elif "ts" in item and "ms_played" in item:
        source = "spotify_extended"
        timestamp = _utc(item["ts"])
        ended = timestamp
        ms_played = item["ms_played"]
        name = str(item.get("master_metadata_track_name") or "").strip()
        artist = str(item.get("master_metadata_album_artist_name") or "").strip()
        album_name = str(item.get("master_metadata_album_album_name") or "").strip() or None
        uri = str(item.get("spotify_track_uri") or "")
        spotify_id = uri.split(":", 2)[2] if re.fullmatch(r"spotify:track:[A-Za-z0-9]+", uri) else None
        artist_id = album_id = artwork = duration = None
        credits = [(artist, None)]
    elif "endTime" in item and "msPlayed" in item:
        source = "spotify_account"
        timestamp = _utc(item["endTime"], minute_precision=True)
        ended = timestamp
        ms_played = item["msPlayed"]
        name = str(item.get("trackName") or "").strip()
        artist = str(item.get("artistName") or "").strip()
        album_name = None
        spotify_id = artist_id = album_id = artwork = duration = None
        credits = [(artist, None)]
    else:
        raise ValueError("Unsupported Spotify listening export format")
    if not name or not artist:
        # Exclude podcast/video rows and entries without a music identity.
        return None
    if len(name) > 500 or len(artist) > 500:
        raise ValueError("Track metadata is too long")
    if ms_played is not None:
        if isinstance(ms_played, bool) or not isinstance(ms_played, int) or not 0 <= ms_played <= 86400000:
            raise ValueError("Invalid milliseconds played")
    track_key = _key(name, artist, spotify_id)
    basis = timestamp.isoformat(timespec="milliseconds")
    identity = json.dumps([source, basis, track_key, ms_played], separators=(",", ":"))
    return {
        "source": source, "source_key": hashlib.sha256(identity.encode()).hexdigest(),
        "source_timestamp": basis, "event_at": ended.isoformat(timespec="milliseconds"),
        "track_key": track_key, "track_id": spotify_id, "track_name": name,
        "artist_name": artist, "artist_id": artist_id, "album_name": album_name,
        "album_id": album_id, "artwork_url": artwork if isinstance(artwork, str) and artwork.startswith("https://i.scdn.co/") else None,
        "ms_played": ms_played, "duration_ms": duration,
        "artist_credits": credits,
    }


def _store_credits(conn, listen_id, credits, replace_unidentified=False):
    if replace_unidentified and any(_valid_id(artist_id) for _, artist_id in credits):
        conn.execute("DELETE FROM music_listen_artists WHERE listen_id=? AND artist_id IS NULL", (listen_id,))
    for position, (name, raw_id) in enumerate(credits):
        artist_id = raw_id if _valid_id(raw_id) else None
        artist_key = "spotify:" + artist_id if artist_id else _key(name, "", None)
        conn.execute("""
            INSERT INTO music_artists(artist_key, spotify_id, name) VALUES (?, ?, ?)
            ON CONFLICT(artist_key) DO UPDATE SET spotify_id=COALESCE(music_artists.spotify_id, excluded.spotify_id)
        """, (artist_key, artist_id, name))
        conn.execute("""
            INSERT OR IGNORE INTO music_listen_artists(listen_id, artist_key, artist_name, artist_id, credit_position)
            VALUES (?, ?, ?, ?, ?)
        """, (listen_id, artist_key, name, artist_id, position))


def insert_records(conn, records):
    inserted = duplicates = skipped = 0
    for raw in records:
        event = normalize_record(raw)
        if event is None:
            skipped += 1
            continue
        credits = event.pop("artist_credits")
        prior_source = conn.execute("SELECT listen_id FROM music_event_sources WHERE source_key = ?", (event["source_key"],)).fetchone()
        if prior_source:
            if event["source"] == "spotify_api":
                _store_credits(conn, prior_source["listen_id"], credits, replace_unidentified=True)
            duplicates += 1
            continue
        artist_key = "spotify:" + event["artist_id"] if _valid_id(event["artist_id"]) else _key(event["artist_name"], "", None)
        album_key = None
        if event["album_name"]:
            album_key = ("spotify:" + event["album_id"] if event["album_id"] else
                         _key(event["album_name"], event["artist_name"], None))
        conn.execute("""INSERT INTO music_artists(artist_key, spotify_id, name) VALUES (?, ?, ?)
                     ON CONFLICT(artist_key) DO UPDATE SET spotify_id=COALESCE(music_artists.spotify_id, excluded.spotify_id)""",
                     (artist_key, event["artist_id"], event["artist_name"]))
        if album_key:
            conn.execute("""
                INSERT INTO music_albums(album_key, spotify_id, name, artist_key, artwork_url)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(album_key) DO UPDATE SET artwork_url=COALESCE(music_albums.artwork_url, excluded.artwork_url)
            """, (album_key, event["album_id"], event["album_name"], artist_key, event["artwork_url"]))
        conn.execute("""
            INSERT INTO music_tracks(track_key, spotify_id, name, artist_key, album_key, artwork_url)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(track_key) DO UPDATE SET artwork_url=COALESCE(music_tracks.artwork_url, excluded.artwork_url)
        """, (event["track_key"], event["track_id"], event["track_name"], artist_key, album_key, event["artwork_url"]))
        # Extended exports have precise end times. Match API plays to their
        # expected end, but never collapse two separate plays merely because
        # they share a title and a minute in the coarse account export.
        match = None
        instant = datetime.fromisoformat(event["event_at"])
        lower = (instant - timedelta(hours=1)).isoformat(timespec="milliseconds")
        upper = (instant + timedelta(hours=1)).isoformat(timespec="milliseconds")
        candidates = conn.execute("""
            SELECT id, source, ms_played, track_key, track_name, artist_name,
                   track_id, album_name, artwork_url, duration_ms, event_at, source_timestamp
            FROM music_listens
            WHERE event_at BETWEEN ? AND ?
        """, (lower, upper)).fetchall()
        for row in candidates:
            same_track = row["track_key"] == event["track_key"] or (
                row["track_name"].casefold() == event["track_name"].casefold()
                and row["artist_name"].casefold() == event["artist_name"].casefold()
            )
            if not same_track or row["source"] == event["source"]:
                continue
            if row["source"] == "spotify_api" or event["source"] == "spotify_api":
                api_start = datetime.fromisoformat(row["source_timestamp"] if row["source"] == "spotify_api" else event["source_timestamp"])
                duration = row["duration_ms"] if row["source"] == "spotify_api" else event["duration_ms"]
                export_end = instant if row["source"] == "spotify_api" else datetime.fromisoformat(row["event_at"])
                tolerance = 60 if "spotify_account" in (row["source"], event["source"]) else 5
                aligned = abs((api_start - export_end).total_seconds()) <= tolerance
                if duration is not None:
                    aligned = aligned or abs((api_start + timedelta(milliseconds=duration) - export_end).total_seconds()) <= tolerance
            else:
                tolerance = 60 if "spotify_account" in (row["source"], event["source"]) else 5
                aligned = abs((datetime.fromisoformat(row["event_at"]) - instant).total_seconds()) <= tolerance
            if aligned:
                match = row
                break
        if match:
            conn.execute("""
                UPDATE music_listens SET
                    ms_played = COALESCE(ms_played, ?),
                    track_id = COALESCE(track_id, ?),
                    artist_id = COALESCE(artist_id, ?),
                    album_name = COALESCE(album_name, ?),
                    album_id = COALESCE(album_id, ?),
                    artwork_url = COALESCE(artwork_url, ?),
                    duration_ms = COALESCE(duration_ms, ?),
                    track_key = CASE WHEN ? IS NOT NULL THEN 'spotify:' || ? ELSE track_key END,
                    event_at = CASE WHEN ? IS NOT NULL THEN ? ELSE event_at END
                WHERE id = ?
            """, (event["ms_played"], event["track_id"], event["artist_id"], event["album_name"],
                  event["album_id"], event["artwork_url"], event["duration_ms"], event["track_id"], event["track_id"], event["ms_played"],
                  event["event_at"], match["id"]))
            conn.execute("INSERT OR IGNORE INTO music_event_sources(source_key, listen_id) VALUES (?, ?)",
                         (event["source_key"], match["id"]))
            if event["source"] == "spotify_api":
                _store_credits(conn, match["id"], credits, replace_unidentified=True)
            duplicates += 1
            continue
        columns = tuple(event)
        sql = "INSERT OR IGNORE INTO music_listens (" + ",".join(columns) + ") VALUES (" + ",".join("?" for _ in columns) + ")"
        if conn.execute(sql, tuple(event.values())).rowcount:
            listen_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute("INSERT OR IGNORE INTO music_event_sources(source_key, listen_id) VALUES (?, ?)",
                         (event["source_key"], listen_id))
            _store_credits(conn, listen_id, credits)
            inserted += 1
        else:
            duplicates += 1
    return {"imported": inserted, "duplicates": duplicates, "skipped": skipped}


def import_export(conn, file_name, raw_bytes):
    if not isinstance(raw_bytes, bytes) or len(raw_bytes) > 16 * 1024 * 1024:
        raise ValueError("Spotify export must be at most 16 MB")
    try:
        records = json.loads(raw_bytes.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Spotify export must be valid UTF-8 JSON") from error
    if not isinstance(records, list) or len(records) > 200000:
        raise ValueError("Expected a Spotify listening-history JSON array")
    if not records:
        raise ValueError("The listening-history file is empty")
    format_name = "extended" if "ts" in records[0] else "account" if "endTime" in records[0] else None
    if not format_name:
        raise ValueError("Unsupported Spotify listening export format")
    sha = hashlib.sha256(raw_bytes).hexdigest()
    prior = conn.execute("SELECT * FROM music_import_jobs WHERE content_sha256 = ?", (sha,)).fetchone()
    if prior:
        return {"imported": 0, "duplicates": len(records), "skipped": 0, "already_imported": True,
                "first_event_at": prior["first_event_at"], "last_event_at": prior["last_event_at"],
                "verified_ms": prior["verified_ms"]}
    normalized = [normalize_record(item) for item in records]
    valid = [item for item in normalized if item is not None]
    first = min((item["event_at"] for item in valid), default=None)
    last = max((item["event_at"] for item in valid), default=None)
    verified_ms = sum(item["ms_played"] or 0 for item in valid)
    result = insert_records(conn, records)
    conn.execute("""
        INSERT INTO music_import_jobs(file_name, content_sha256, format, imported_count, duplicate_count,
                                      first_event_at, last_event_at, verified_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (re.sub(r"[^A-Za-z0-9._ -]", "_", file_name)[:120], sha, format_name,
          result["imported"], result["duplicates"], first, last, verified_ms))
    return {**result, "format": format_name, "already_imported": False,
            "first_event_at": first, "last_event_at": last, "verified_ms": verified_ms}


def month_bounds(month, tz_name):
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(month)):
        raise ValueError("Month must be YYYY-MM")
    try:
        zone = ZoneInfo(tz_name)
    except Exception as error:
        raise ValueError("Unknown time zone") from error
    year, number = map(int, month.split("-"))
    start = datetime(year, number, 1, tzinfo=zone)
    end = datetime(year + (number == 12), number % 12 + 1, 1, tzinfo=zone)
    return start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()


def record_playback_observation(conn, snapshot, observed_at=None):
    """Count only progress confirmed by two nearby, uninterrupted snapshots."""
    observed = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    now = observed.isoformat(timespec="milliseconds")
    track_id = snapshot.get("track_id") if _valid_id(snapshot.get("track_id")) else None
    playing = bool(snapshot.get("playing")) and not bool(snapshot.get("private_session")) and bool(track_id)
    progress = snapshot.get("progress_ms")
    duration = snapshot.get("duration_ms")
    stamp = snapshot.get("state_timestamp_ms")
    if not isinstance(progress, int) or isinstance(progress, bool) or progress < 0:
        progress = None
    if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
        duration = None
    if not isinstance(stamp, int) or isinstance(stamp, bool) or stamp <= 0:
        stamp = None
    if duration is not None and progress is not None and progress > duration:
        progress = None
    previous = conn.execute("SELECT * FROM music_playback_sample WHERE id=1").fetchone()
    estimated = 0
    if previous and previous["playing"] and playing and previous["track_id"] == track_id:
        elapsed = int((observed - datetime.fromisoformat(previous["observed_at"])).total_seconds() * 1000)
        before = previous["progress_ms"]
        if (30000 <= elapsed <= 180000 and stamp is not None and stamp == previous["state_timestamp_ms"]
                and before is not None and progress is not None):
            advanced = progress - before
            if advanced > 0 and abs(advanced - elapsed) <= max(6000, int(elapsed * .12)):
                estimated = min(elapsed, advanced)
                conn.execute("""
                    INSERT OR IGNORE INTO music_observed_intervals(track_id, start_at, end_at, estimated_ms)
                    VALUES (?, ?, ?, ?)
                """, (track_id, previous["observed_at"], now, estimated))
    conn.execute("""
        INSERT INTO music_playback_sample(id, observed_at, track_id, state_timestamp_ms, progress_ms, duration_ms, playing)
        VALUES (1, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET observed_at=excluded.observed_at, track_id=excluded.track_id,
          state_timestamp_ms=excluded.state_timestamp_ms, progress_ms=excluded.progress_ms,
          duration_ms=excluded.duration_ms, playing=excluded.playing
    """, (now, track_id, stamp, progress, duration, int(playing)))
    return estimated


def estimated_by_track(conn, start, end):
    """Subtract verified export windows from observed intervals, including imports later on."""
    start_dt, end_dt = datetime.fromisoformat(start), datetime.fromisoformat(end)
    intervals = conn.execute("""
        SELECT * FROM music_observed_intervals WHERE start_at < ? AND end_at > ?
    """, (end, start)).fetchall()
    totals = Counter()
    for item in intervals:
        left = max(start_dt, datetime.fromisoformat(item["start_at"]))
        right = min(end_dt, datetime.fromisoformat(item["end_at"]))
        if left >= right:
            continue
        segments = [(left, right)]
        # An export row's end time and actual milliseconds describe a verified
        # window. Remove only overlaps for the same exact Spotify track ID.
        for record in conn.execute("""
            SELECT event_at, ms_played FROM music_listens
            WHERE track_id=? AND ms_played IS NOT NULL AND event_at >= ? AND event_at <= ?
        """, (item["track_id"], (left - timedelta(days=1)).isoformat(), (right + timedelta(days=1)).isoformat())):
            verified_end = datetime.fromisoformat(record["event_at"])
            verified_start = verified_end - timedelta(milliseconds=record["ms_played"])
            next_segments = []
            for a, b in segments:
                if verified_end <= a or verified_start >= b:
                    next_segments.append((a, b))
                else:
                    if a < verified_start:
                        next_segments.append((a, verified_start))
                    if verified_end < b:
                        next_segments.append((verified_end, b))
            segments = next_segments
        totals[item["track_id"]] += sum(int((b - a).total_seconds() * 1000) for a, b in segments)
    return dict(totals)


def _estimated_month_ms(conn, start, end):
    return sum(estimated_by_track(conn, start, end).values())


def monthly_summary(conn, month, tz_name="UTC"):
    start, end = month_bounds(month, tz_name)
    rows = conn.execute("""
        SELECT l.*, COALESCE(l.artwork_url, t.artwork_url, a.artwork_url) AS resolved_artwork_url
        FROM music_listens l
        LEFT JOIN music_tracks t ON t.track_key=l.track_key
        LEFT JOIN music_albums a ON a.album_key=t.album_key
        WHERE l.event_at >= ? AND l.event_at < ? ORDER BY l.event_at DESC, l.id DESC
    """, (start, end)).fetchall()
    data = [dict(row) for row in rows]
    track_counts = Counter(row["track_key"] for row in data)
    credits = [dict(row) for row in conn.execute("""
        SELECT c.artist_key, c.artist_name, c.artist_id, a.image_url
        FROM music_listen_artists c JOIN music_listens l ON l.id=c.listen_id
        LEFT JOIN music_artists a ON a.artist_key=c.artist_key
        WHERE l.event_at >= ? AND l.event_at < ?
    """, (start, end)).fetchall()]
    artist_counts = Counter(row["artist_key"] for row in credits)
    album_counts = Counter((row["album_id"] or (row["album_name"], row["artist_name"])) for row in data if row["album_name"])
    def ranked(counts, field, limit=5, label_field=None):
        result = []
        for name, count in counts.most_common(limit):
            matches = [row for row in data if (row[field] if field != "album_name" else
                       (row["album_id"] or (row["album_name"], row["artist_name"]))) == name]
            item = matches[0]
            artist_id = next((row["artist_id"] for row in matches if row["artist_id"]), None)
            album_id = next((row["album_id"] for row in matches if row["album_id"]), None)
            track_id = next((row["track_id"] for row in matches if row["track_id"]), None)
            if field == "artist_name":
                spotify_kind, spotify_id = "artist", artist_id
            elif field == "album_name":
                spotify_kind, spotify_id = "album", album_id
            else:
                spotify_kind, spotify_id = "track", track_id
            result.append({
                "name": item[label_field or field] if field == "album_name" or label_field else name,
                "plays": count,
                "artwork_url": next((row["resolved_artwork_url"] for row in matches if row["resolved_artwork_url"]), None),
                "spotify_url": f"https://open.spotify.com/{spotify_kind}/{spotify_id}" if spotify_id and re.fullmatch(r"[A-Za-z0-9]+", spotify_id) else None,
            })
        return result
    verified = sum(row["ms_played"] for row in data if row["ms_played"] is not None)
    estimated = _estimated_month_ms(conn, start, end)
    known = sum(row["ms_played"] is not None for row in data)
    days = Counter(datetime.fromisoformat(row["event_at"]).astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d") for row in data)
    hours = Counter(datetime.fromisoformat(row["event_at"]).astimezone(ZoneInfo(tz_name)).hour for row in data)
    state = conn.execute("SELECT * FROM music_sync_state WHERE provider = 'spotify'").fetchone()
    earlier_artists = {row[0] for row in conn.execute(
        "SELECT DISTINCT artist_name FROM music_listens WHERE event_at < ?", (start,)
    ).fetchall()}
    first_seen = [row["artist_name"] for key, _ in artist_counts.most_common()
                  for row in credits if row["artist_key"] == key and row["artist_name"] not in earlier_artists][:10]
    top_artists = []
    for artist_key, count in artist_counts.most_common(5):
        credit = next(row for row in credits if row["artist_key"] == artist_key)
        artist_id = credit["artist_id"] if _valid_id(credit["artist_id"]) else None
        top_artists.append({"name": credit["artist_name"], "plays": count,
                            "artwork_url": _safe_art(credit["image_url"]),
                            "image_kind": "artist" if _safe_art(credit["image_url"]) else None,
                            "spotify_url": f"https://open.spotify.com/artist/{artist_id}" if artist_id else None})
    sync_started = state["sync_started_at"] if state and "sync_started_at" in state.keys() else None
    syncing = bool(sync_started and datetime.now(timezone.utc) - datetime.fromisoformat(sync_started) < timedelta(minutes=2))
    return {
        "month": month, "timezone": tz_name, "events": len(data),
        "verified_ms": verified, "estimated_ms": estimated, "duration_known_events": known,
        "duration_unknown_events": len(data) - known,
        "unique_artists": len(artist_counts),
        "first_seen_artists": first_seen[:10],
        "top_tracks": ranked(track_counts, "track_key", label_field="track_name"),
        "top_artists": top_artists,
        "top_albums": ranked(album_counts, "album_name"),
        "days": dict(sorted(days.items())), "hours": {str(hour): hours[hour] for hour in range(24)},
        "recent": [{"track_name": row["track_name"], "artist_name": row["artist_name"],
                    "album_name": row["album_name"], "artwork_url": row["resolved_artwork_url"],
                    "event_at": row["event_at"], "ms_played": row["ms_played"],
                    "spotify_url": f"https://open.spotify.com/track/{row['track_id']}" if _valid_id(row["track_id"]) else None}
                   for row in data[:12]],
        "last_sync_at": state["last_success_at"] if state else None,
        "sync_error": state["last_error"] if state else None,
        "syncing": syncing,
        "coverage_warning": state["coverage_warning"] if state else None,
        "methodology": "Verified time is from official Spotify history exports. Estimated time counts only progress observed by Apollo in two nearby uninterrupted playback checks; unknown gaps are excluded and overlapping export time is removed. Recent-play track lengths are never counted as listening time. Coverage before the first sync or during outages may be incomplete.",
    }


def archive_recap(conn, month, tz_name="UTC", regenerate=False):
    summary = monthly_summary(conn, month, tz_name)
    dataset = {key: value for key, value in summary.items()
               if key not in ("last_sync_at", "sync_error", "coverage_warning", "methodology")}
    fingerprint = hashlib.sha256(json.dumps(dataset, sort_keys=True).encode()).hexdigest()
    old = conn.execute("SELECT * FROM music_recaps WHERE month = ? AND timezone = ?", (month, tz_name)).fetchone()
    if old and not regenerate and old["data_fingerprint"] == fingerprint:
        return json.loads(old["summary_json"])
    conn.execute("""
        INSERT INTO music_recaps(month, timezone, design_version, data_fingerprint, summary_json)
        VALUES (?, ?, 1, ?, ?)
        ON CONFLICT(month, timezone) DO UPDATE SET
        design_version=1, data_fingerprint=excluded.data_fingerprint,
        summary_json=excluded.summary_json, generated_at=CURRENT_TIMESTAMP
    """, (month, tz_name, fingerprint, json.dumps(summary)))
    return summary
