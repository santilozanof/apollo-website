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
            name TEXT NOT NULL
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
        CREATE TABLE IF NOT EXISTS music_sync_state (
            provider TEXT PRIMARY KEY,
            cursor_ms INTEGER,
            last_success_at TEXT,
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
    if "coverage_warning" not in {row["name"] for row in conn.execute("PRAGMA table_info(music_sync_state)")}:
        conn.execute("ALTER TABLE music_sync_state ADD COLUMN coverage_warning TEXT")


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
    elif "endTime" in item and "msPlayed" in item:
        source = "spotify_account"
        timestamp = _utc(item["endTime"], minute_precision=True)
        ended = timestamp
        ms_played = item["msPlayed"]
        name = str(item.get("trackName") or "").strip()
        artist = str(item.get("artistName") or "").strip()
        album_name = None
        spotify_id = artist_id = album_id = artwork = duration = None
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
    }


def insert_records(conn, records):
    inserted = duplicates = skipped = 0
    for raw in records:
        event = normalize_record(raw)
        if event is None:
            skipped += 1
            continue
        if conn.execute("SELECT 1 FROM music_event_sources WHERE source_key = ?", (event["source_key"],)).fetchone():
            duplicates += 1
            continue
        artist_key = _key(event["artist_name"], "", None)
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
            duplicates += 1
            continue
        columns = tuple(event)
        sql = "INSERT OR IGNORE INTO music_listens (" + ",".join(columns) + ") VALUES (" + ",".join("?" for _ in columns) + ")"
        if conn.execute(sql, tuple(event.values())).rowcount:
            listen_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute("INSERT OR IGNORE INTO music_event_sources(source_key, listen_id) VALUES (?, ?)",
                         (event["source_key"], listen_id))
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
    prior = conn.execute("SELECT id FROM music_import_jobs WHERE content_sha256 = ?", (sha,)).fetchone()
    if prior:
        return {"imported": 0, "duplicates": len(records), "skipped": 0, "already_imported": True}
    result = insert_records(conn, records)
    conn.execute("""
        INSERT INTO music_import_jobs(file_name, content_sha256, format, imported_count, duplicate_count)
        VALUES (?, ?, ?, ?, ?)
    """, (re.sub(r"[^A-Za-z0-9._ -]", "_", file_name)[:120], sha, format_name,
          result["imported"], result["duplicates"]))
    return {**result, "format": format_name, "already_imported": False}


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


def monthly_summary(conn, month, tz_name="UTC"):
    start, end = month_bounds(month, tz_name)
    rows = conn.execute("""
        SELECT * FROM music_listens WHERE event_at >= ? AND event_at < ? ORDER BY event_at DESC, id DESC
    """, (start, end)).fetchall()
    data = [dict(row) for row in rows]
    track_counts = Counter(row["track_key"] for row in data)
    artist_counts = Counter(row["artist_name"] for row in data)
    album_counts = Counter(row["album_name"] for row in data if row["album_name"])
    def ranked(counts, field, limit=5, label_field=None):
        result = []
        for name, count in counts.most_common(limit):
            matches = [row for row in data if row[field] == name]
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
                "name": item[label_field] if label_field else name,
                "plays": count,
                "artwork_url": next((row["artwork_url"] for row in matches if row["artwork_url"]), None),
                "spotify_url": f"https://open.spotify.com/{spotify_kind}/{spotify_id}" if spotify_id and re.fullmatch(r"[A-Za-z0-9]+", spotify_id) else None,
            })
        return result
    verified = sum(row["ms_played"] for row in data if row["ms_played"] is not None)
    known = sum(row["ms_played"] is not None for row in data)
    days = Counter(datetime.fromisoformat(row["event_at"]).astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d") for row in data)
    hours = Counter(datetime.fromisoformat(row["event_at"]).astimezone(ZoneInfo(tz_name)).hour for row in data)
    state = conn.execute("SELECT * FROM music_sync_state WHERE provider = 'spotify'").fetchone()
    earlier_artists = {row[0] for row in conn.execute(
        "SELECT DISTINCT artist_name FROM music_listens WHERE event_at < ?", (start,)
    ).fetchall()}
    first_seen = [name for name, _ in artist_counts.most_common() if name not in earlier_artists]
    return {
        "month": month, "timezone": tz_name, "events": len(data),
        "verified_ms": verified, "duration_known_events": known,
        "duration_unknown_events": len(data) - known,
        "unique_artists": len(artist_counts),
        "first_seen_artists": first_seen[:10],
        "top_tracks": ranked(track_counts, "track_key", label_field="track_name"),
        "top_artists": ranked(artist_counts, "artist_name"),
        "top_albums": ranked(album_counts, "album_name"),
        "days": dict(sorted(days.items())), "hours": {str(hour): hours[hour] for hour in range(24)},
        "recent": [{key: row[key] for key in ("track_name", "artist_name", "album_name", "artwork_url", "event_at", "ms_played")} for row in data[:12]],
        "last_sync_at": state["last_success_at"] if state else None,
        "sync_error": state["last_error"] if state else None,
        "coverage_warning": state["coverage_warning"] if state else None,
        "methodology": "Play counts are distinct Spotify recent-play events or export rows. Listening time sums only export milliseconds; Spotify's recent-play API does not report duration. Coverage before the first sync may be incomplete. Indistinguishable repeats in older minute-precision exports may be merged.",
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
