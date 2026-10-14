"""Resolve AI music suggestions against Spotify and optionally play them.

The AI supplies names, never IDs. This adapter is the sole source of Spotify
URIs and validates every selection before any playback mutation occurs.
"""

import json
import hashlib
from collections import Counter
import os
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

from music_curator import normalize_curated_tracks


ENV_FILE = Path("/root/.hermes/.env")
SCOPES = " ".join([
    "user-read-playback-state", "user-modify-playback-state",
    "user-read-currently-playing", "user-library-read",
    "playlist-read-private", "user-top-read", "user-read-recently-played",
])


def normalized(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def candidate_score(track, wanted_title, wanted_artist):
    title_score = SequenceMatcher(None, normalized(wanted_title), normalized(track.get("name"))).ratio()
    artist_names = [normalized(item.get("name")) for item in track.get("artists") or []]
    artist_score = max(
        [SequenceMatcher(None, normalized(wanted_artist), name).ratio() for name in artist_names] or [0]
    ) if wanted_artist else 1.0
    return title_score * 0.72 + artist_score * 0.28


def spotify_retry_after(error):
    headers = getattr(error, "headers", None) or {}
    for key, value in headers.items():
        if str(key).casefold() == "retry-after":
            return value
    return None


def spotify_read(operation, attempts=3):
    """Retry only idempotent Spotify reads; playback mutations run once."""
    last_error = None
    for attempt in range(max(1, int(attempts))):
        try:
            return operation()
        except Exception as error:
            last_error = error
            status = getattr(error, "http_status", None)
            detail = str(error).casefold()
            temporary = status in {429, 500, 502, 503, 504} or isinstance(
                error, (TimeoutError, ConnectionError)
            ) or any(
                marker in detail
                for marker in ("timed out", "timeout", "temporarily unavailable", "connection reset")
            )
            if not temporary or attempt + 1 >= attempts:
                raise
            retry_after = spotify_retry_after(error)
            try:
                # Spotify's 429 recovery contract is the Retry-After value.
                # Keep it bounded, but never shorten ordinary retry windows to
                # the old one-second cap (which immediately caused another 429).
                retry_delay = float(retry_after)
                if retry_delay > 10.0:
                    raise last_error
                delay = max(.2, retry_delay)
            except (TypeError, ValueError):
                delay = min(2.0, .25 * (2 ** attempt))
            time.sleep(delay)
    raise last_error


def resolve_candidates(spotify, candidates, excluded_ids=(), maximum=10):
    resolved = []
    excluded = {str(value) for value in excluded_ids if value}
    for suggestion in candidates or []:
        if not isinstance(suggestion, dict):
            continue
        title = str(suggestion.get("title") or "").strip()
        artist = str(suggestion.get("artist") or "").strip()
        if not title or not artist:
            continue
        searches = [f'track:"{title}" artist:"{artist}"']
        found = {}
        for query in searches:
            response = spotify_read(
                lambda query=query: spotify.search(q=query, type="track", limit=8)
            )
            for item in (response.get("tracks") or {}).get("items") or []:
                if item.get("id") and item.get("id") not in excluded:
                    found[item["id"]] = item
        # Most suggestions resolve with one strict request. Only spend a
        # second request when Spotify's field search cannot find a close match.
        best_strict = max(
            [candidate_score(item, title, artist) for item in found.values()] or [0]
        )
        if best_strict < 0.82:
            response = spotify_read(
                lambda: spotify.search(q=f"{title} {artist}", type="track", limit=8)
            )
            for item in (response.get("tracks") or {}).get("items") or []:
                if item.get("id") and item.get("id") not in excluded:
                    found[item["id"]] = item
        if not found:
            continue
        best = max(found.values(), key=lambda item: candidate_score(item, title, artist))
        if candidate_score(best, title, artist) < 0.72:
            continue
        album = best.get("album") or {}
        images = album.get("images") or []
        resolved.append({
            "id": best.get("id"), "uri": best.get("uri"),
            "title": best.get("name"),
            "artists": [item.get("name") for item in best.get("artists") or [] if item.get("name")],
            "album": album.get("name"),
            "spotify_url": (best.get("external_urls") or {}).get("spotify"),
            "artwork": images[0].get("url") if images else None,
            "popularity": best.get("popularity"),
            "reason": suggestion.get("reason"),
        })
        if len(normalize_curated_tracks(resolved, excluded, maximum)) >= max(1, int(maximum)):
            break
    return normalize_curated_tracks(resolved, excluded, maximum)


def active_device(spotify):
    devices = (spotify_read(spotify.devices) or {}).get("devices") or []
    device = next(
        (item for item in devices if item.get("is_active") and not item.get("is_restricted")),
        None,
    )
    if not device:
        raise RuntimeError("No active, controllable Spotify device is available")
    return device


def confirm_track_playback(spotify, track_id, attempts=4):
    """Confirm Spotify reports the requested opener as actively playing."""
    for attempt in range(max(1, int(attempts))):
        state = spotify_read(spotify.current_playback, attempts=2) or {}
        item = state.get("item") if isinstance(state.get("item"), dict) else {}
        if item.get("id") == track_id and state.get("is_playing") is True:
            return state
        if attempt + 1 < attempts:
            time.sleep(.18 * (attempt + 1))
    raise RuntimeError("Spotify did not confirm playback of the opening track")


def start_curated_playback(spotify, payload):
    """Resolve one opener, start it, and confirm it before returning."""
    queued_ids, existing_queue_uris = existing_queue_state(spotify)
    excluded = list(payload.get("exclude_track_ids") or []) + queued_ids
    current_id = str(payload.get("current_track_id") or "").strip()
    if current_id:
        excluded.append(current_id)
    opener = None
    opener_index = None
    candidates = payload.get("candidates") or []
    for index, suggestion in enumerate(candidates):
        tracks = resolve_candidates(
            spotify,
            [suggestion],
            excluded_ids=excluded,
            maximum=1,
        )
        if tracks:
            opener = tracks[0]
            opener_index = index
            break
    if opener is None:
        raise RuntimeError("No verified Spotify track matched the requested direction")
    device = active_device(spotify)
    spotify.start_playback(
        device_id=device.get("id"),
        uris=[opener["uri"]],
        position_ms=0,
    )
    confirm_track_playback(spotify, opener["id"])
    return {
        "ok": True,
        "opener": opener,
        "remaining_candidates": candidates[(opener_index or 0) + 1:],
        "playback_started": True,
        "existing_queue_uris": existing_queue_uris,
        "existing_queue_count": len(existing_queue_uris),
        "queue_preserved": True,
    }


def _temporary_spotify_error(error):
    status = getattr(error, "http_status", None)
    detail = str(error).casefold()
    return status in {429, 500, 502, 503, 504} or isinstance(
        error, (TimeoutError, ConnectionError)
    ) or any(marker in detail for marker in (
        "timed out", "timeout", "temporarily unavailable", "connection reset",
    ))


def add_to_queue_safely(spotify, uri, device_id, known_counts, attempts=3):
    """Retry an ambiguous queue mutation only after proving it did not land."""
    target_count = known_counts.get(uri, 0) + 1
    last_error = None
    for attempt in range(max(1, int(attempts))):
        try:
            spotify.add_to_queue(uri, device_id=device_id)
            known_counts[uri] = target_count
            return
        except Exception as error:
            last_error = error
            if not _temporary_spotify_error(error):
                raise
            # A timeout may happen after Spotify accepted the mutation. Read
            # the queue before retrying so recovery cannot create duplicates.
            _ids, observed_uris = existing_queue_state(spotify)
            observed = Counter(observed_uris)
            if observed.get(uri, 0) >= target_count:
                known_counts.update(observed)
                return
            if attempt + 1 >= attempts:
                raise
            retry_after = spotify_retry_after(error)
            try:
                retry_delay = float(retry_after)
                if retry_delay > 10.0:
                    raise last_error
                delay = max(.2, retry_delay)
            except (TypeError, ValueError):
                delay = min(2.0, .25 * (2 ** attempt))
            time.sleep(delay)
    raise last_error


def emit_event(event):
    print(json.dumps(event, ensure_ascii=False), flush=True)


def build_curated_queue(spotify, payload, emit=emit_event):
    """Restore the existing queue, then verify and append curated tracks in order."""
    device = active_device(spotify)
    _current_ids, current_uris = existing_queue_state(spotify)
    known_counts = Counter(current_uris)
    desired_counts = Counter()
    preserved = 0
    for uri in payload.get("existing_queue_uris") or []:
        desired_counts[uri] += 1
        if known_counts.get(uri, 0) < desired_counts[uri]:
            add_to_queue_safely(spotify, uri, device.get("id"), known_counts)
        preserved += 1
        emit({"event": "preserved", "preserved": preserved})

    excluded = {
        str(value) for value in (payload.get("exclude_track_ids") or []) if value
    }
    opener_id = str(payload.get("opener_id") or "")
    if opener_id:
        excluded.add(opener_id)
    accepted = []
    maximum = max(1, min(10, int(payload.get("maximum", 9))))
    candidates = payload.get("candidates") or []
    for suggestion in candidates:
        if len(accepted) >= maximum:
            break
        resolved = resolve_candidates(
            spotify,
            [suggestion],
            excluded_ids=excluded | {track["id"] for track in accepted},
            maximum=1,
        )
        if not resolved:
            continue
        proposed = normalize_curated_tracks(
            accepted + resolved,
            excluded_ids=excluded,
            maximum=maximum,
        )
        if len(proposed) == len(accepted):
            continue
        track = proposed[-1]
        add_to_queue_safely(spotify, track["uri"], device.get("id"), known_counts)
        accepted = proposed
        emit({
            "event": "added",
            "added": len(accepted),
            "target": maximum,
            "track": track,
        })
    emit({
        "event": "complete",
        "added": len(accepted),
        "preserved": preserved,
        "tracks": accepted,
    })
    return accepted


def restore_existing_queue(spotify, uris):
    """Restore the pre-play queue before complementary curation can fail."""
    device = active_device(spotify)
    _current_ids, current_uris = existing_queue_state(spotify)
    known_counts = Counter(current_uris)
    desired_counts = Counter()
    restored = 0
    for uri in uris or []:
        if not str(uri).startswith("spotify:track:"):
            continue
        desired_counts[uri] += 1
        if known_counts.get(uri, 0) < desired_counts[uri]:
            add_to_queue_safely(spotify, uri, device.get("id"), known_counts)
        restored += 1
    return {"ok": True, "preserved": restored}


def existing_queue_state(spotify):
    data = spotify_read(spotify.queue) or {}
    items = [item for item in data.get("queue") or [] if isinstance(item, dict)]
    ids = [item.get("id") for item in items if item.get("id")]
    uris = [
        item.get("uri") for item in items
        if str(item.get("uri") or "").startswith("spotify:track:")
    ]
    return ids, uris


def compact_queue_item(item):
    if not isinstance(item, dict):
        return None
    album = item.get("album") if isinstance(item.get("album"), dict) else {}
    images = album.get("images") if isinstance(album.get("images"), list) else []
    artists = item.get("artists") if isinstance(item.get("artists"), list) else []
    return {
        "id": item.get("id"),
        "uri": item.get("uri"),
        "type": item.get("type"),
        "name": item.get("name"),
        "artists": ", ".join(
            artist.get("name", "") for artist in artists
            if isinstance(artist, dict) and artist.get("name")
        ),
        "artwork": images[0].get("url") if images and isinstance(images[0], dict) else None,
        "duration_ms": item.get("duration_ms") or 0,
        "album_uri": album.get("uri"),
        "artist_uri": artists[0].get("uri") if artists and isinstance(artists[0], dict) else None,
        "spotify_url": (item.get("external_urls") or {}).get("spotify"),
    }


def playback_snapshot(data):
    """Normalize Spotify's player response for every Apollo music surface."""
    data = data if isinstance(data, dict) else {}
    item = data.get("item") if isinstance(data.get("item"), dict) else {}
    compact = compact_queue_item(item) if item else None
    device = data.get("device") if isinstance(data.get("device"), dict) else {}
    actions = data.get("actions") if isinstance(data.get("actions"), dict) else {}
    disallows = actions.get("disallows") if isinstance(actions.get("disallows"), dict) else {}
    if not compact:
        return {
            "playing": False,
            "title": None,
            "artists": None,
            "playback_state": "idle",
            "connection_state": "connected",
            "progress_ms": 0,
            "duration_ms": 0,
            "sampled_at_ms": int(time.time() * 1000),
        }
    return {
        "playing": bool(data.get("is_playing")),
        "title": compact.get("name"),
        "artists": compact.get("artists"),
        "album": (item.get("album") or {}).get("name"),
        "artwork": compact.get("artwork"),
        "progress_ms": data.get("progress_ms") or 0,
        "duration_ms": compact.get("duration_ms") or 0,
        "sampled_at_ms": int(time.time() * 1000),
        "device": device.get("name"),
        "device_type": device.get("type"),
        "device_key": hashlib.sha256(
            str(device.get("id") or "").encode("utf-8")
        ).hexdigest()[:16] if device.get("id") else None,
        "track_id": compact.get("id"),
        "spotify_url": compact.get("spotify_url"),
        "disallows": disallows,
        "playback_state": "playing" if data.get("is_playing") else "paused",
        "connection_state": "connected",
    }


def playback_control(spotify, action, position_ms=None):
    """Run one supported Spotify Connect transport operation.

    Spotify controls the active device. Apollo never transfers playback or
    rebuilds a context as a substitute for a transport command.
    """
    action = str(action or "").strip().lower()
    if action not in {"play", "pause", "next", "previous", "seek"}:
        raise ValueError("Invalid Spotify action")

    state = spotify_read(spotify.current_playback, attempts=1) or {}
    device = state.get("device") if isinstance(state.get("device"), dict) else {}
    if not device.get("id") or device.get("is_restricted"):
        device = active_device(spotify)
    device_id = device.get("id")

    if action == "play":
        spotify.start_playback(device_id=device_id)
    elif action == "pause":
        spotify.pause_playback(device_id=device_id)
    elif action == "next":
        spotify.next_track(device_id=device_id)
    elif action == "previous":
        spotify.previous_track(device_id=device_id)
    else:
        try:
            position_ms = max(0, int(position_ms))
        except (TypeError, ValueError) as error:
            raise ValueError("Invalid seek position") from error
        spotify.seek_track(position_ms, device_id=device_id)

    # Mutations are intentionally never retried: a timeout can occur after
    # Spotify accepted the command. Only the idempotent state read is repeated
    # briefly so the UI receives Spotify's authoritative post-command state.
    before_item = state.get("item") if isinstance(state.get("item"), dict) else {}
    before_track = before_item.get("id")
    before_progress = int(state.get("progress_ms") or 0)
    confirmed = {}
    # Spotify Connect can acknowledge a command before the player endpoint
    # reflects it. Give the authoritative read model a little longer to
    # converge, especially when resuming a paused remote device.
    readback_delays = (.2, .35, .55, .8)
    for attempt in range(len(readback_delays) + 1):
        confirmed = spotify_read(spotify.current_playback, attempts=1) or {}
        confirmed_item = (
            confirmed.get("item")
            if isinstance(confirmed.get("item"), dict)
            else {}
        )
        confirmed_progress = int(confirmed.get("progress_ms") or 0)
        settled = (
            (action == "play" and confirmed.get("is_playing") is True)
            or (action == "pause" and confirmed.get("is_playing") is False)
            or (action == "next" and confirmed_item.get("id") != before_track)
            or (
                action == "previous"
                and (
                    confirmed_item.get("id") != before_track
                    or confirmed_progress + 1000 < before_progress
                )
            )
            or (
                action == "seek"
                and abs(confirmed_progress - position_ms) <= 2500
            )
        )
        if settled or attempt == len(readback_delays):
            break
        time.sleep(readback_delays[attempt])
    return {
        "ok": True,
        "action": action,
        "playback": playback_snapshot(confirmed),
    }


def set_playback_shuffle(spotify, enabled):
    """Set Spotify context shuffle and verify the server-reported state."""
    player = spotify_read(spotify.current_playback, attempts=1) or {}
    context = player.get("context") if isinstance(player.get("context"), dict) else None
    device = player.get("device") if isinstance(player.get("device"), dict) else {}
    if not context:
        return {
            "ok": False,
            "supported": False,
            "error": "Shuffle is not available for this playback context.",
        }
    device_id = device.get("id")
    spotify.shuffle(bool(enabled), device_id=device_id)
    for attempt in range(3):
        confirmed = spotify_read(spotify.current_playback, attempts=1) or {}
        if confirmed.get("shuffle_state") == bool(enabled):
            return {
                "ok": True,
                "supported": True,
                "shuffle_state": bool(enabled),
            }
        if attempt < 2:
            time.sleep(.18 * (attempt + 1))
    raise RuntimeError("Spotify did not confirm the shuffle setting")


def recent_contexts_snapshot(spotify, limit=12):
    """Fetch recent albums with only a bounded number of playlist lookups."""
    recent = spotify_read(
        lambda: spotify.current_user_recently_played(limit=30),
        attempts=1,
    ) or {}
    results = []
    seen = set()
    playlist_lookups = 0
    for play in recent.get("items") or []:
        if not isinstance(play, dict):
            continue
        track = play.get("track") if isinstance(play.get("track"), dict) else {}
        context = play.get("context") if isinstance(play.get("context"), dict) else {}
        if context.get("type") == "playlist" and playlist_lookups < 2:
            playlist_id = str(context.get("uri") or "").split(":")[-1]
            key = ("playlist", playlist_id)
            if playlist_id and key not in seen:
                playlist_lookups += 1
                try:
                    playlist = spotify_read(
                        lambda playlist_id=playlist_id: spotify.playlist(
                            playlist_id,
                            fields="id,name,uri,external_urls,images",
                        ),
                        attempts=1,
                    ) or {}
                    images = playlist.get("images") or []
                    results.append({
                        "type": "playlist",
                        "id": playlist.get("id"),
                        "name": playlist.get("name"),
                        "subtitle": "Playlist",
                        "artwork": images[0].get("url") if images else None,
                        "spotify_url": (playlist.get("external_urls") or {}).get("spotify"),
                        "uri": playlist.get("uri"),
                        "played_at": play.get("played_at"),
                    })
                    seen.add(key)
                except Exception:
                    # Recent albums are still useful if optional playlist
                    # metadata is temporarily throttled.
                    pass
        album = track.get("album") if isinstance(track.get("album"), dict) else {}
        album_id = album.get("id")
        key = ("album", album_id)
        if album_id and key not in seen:
            images = album.get("images") or []
            artists = album.get("artists") or []
            results.append({
                "type": "album",
                "id": album_id,
                "name": album.get("name"),
                "subtitle": ", ".join(
                    artist.get("name", "") for artist in artists
                    if isinstance(artist, dict) and artist.get("name")
                ) or "Album",
                "artwork": images[0].get("url") if images else None,
                "spotify_url": (album.get("external_urls") or {}).get("spotify"),
                "uri": album.get("uri"),
                "played_at": play.get("played_at"),
            })
            seen.add(key)
        if len(results) >= limit:
            break
    return {"items": results[:limit]}


def queue_snapshot(data):
    current = compact_queue_item((data or {}).get("currently_playing"))
    queued = [
        compact for compact in (
            compact_queue_item(item) for item in ((data or {}).get("queue") or [])
        ) if compact and compact.get("uri")
    ]
    signature = "\n".join(
        [current.get("uri", "") if current else ""]
        + [item.get("uri", "") for item in queued]
    )
    return {
        "current": current,
        "queue": queued,
        "revision": hashlib.sha256(signature.encode("utf-8")).hexdigest()[:20],
    }


def play_resolved_queue(spotify, tracks, devices, existing_queue_uris=()):
    """Start the opener, restore the prior queue, then append the curated tracks."""
    active = next(
        (item for item in devices or [] if item.get("is_active") and not item.get("is_restricted")),
        None,
    )
    if not active:
        raise RuntimeError("No active, controllable Spotify device is available")
    spotify.start_playback(device_id=active.get("id"), uris=[tracks[0]["uri"]], position_ms=0)
    for uri in existing_queue_uris or []:
        spotify.add_to_queue(uri, device_id=active.get("id"))
    for track in tracks[1:]:
        spotify.add_to_queue(track["uri"], device_id=active.get("id"))
    return len(tracks) - 1


def spotify_client():
    for line in ENV_FILE.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip()
    from spotipy import Spotify
    from spotipy.oauth2 import SpotifyOAuth
    return Spotify(auth_manager=SpotifyOAuth(
        client_id=os.environ["SPOTIFY_CLIENT_ID"],
        client_secret=os.environ["SPOTIFY_CLIENT_SECRET"],
        redirect_uri="http://127.0.0.1:8888/callback", scope=SCOPES,
        open_browser=False, cache_path="/root/.spotify-apollo-cache",
    ), requests_timeout=8, retries=0, status_retries=0, backoff_factor=0)


def listening_context(spotify):
    """Return compact permitted listening signals, never private token data."""
    recent = spotify_read(lambda: spotify.current_user_recently_played(limit=15)) or {}
    top = spotify_read(
        lambda: spotify.current_user_top_artists(limit=10, time_range="short_term")
    ) or {}
    return {
        "recent_tracks": [
            {
                "title": (item.get("track") or {}).get("name"),
                "artists": [artist.get("name") for artist in (item.get("track") or {}).get("artists") or []],
            }
            for item in recent.get("items") or []
            if isinstance(item, dict) and isinstance(item.get("track"), dict)
        ],
        "top_artists": [item.get("name") for item in top.get("items") or [] if item.get("name")],
    }


def run(payload, play=False):
    spotify = spotify_client()
    queued_ids, existing_queue_uris = existing_queue_state(spotify)
    excluded = list(payload.get("exclude_track_ids") or []) + queued_ids
    current_id = str(payload.get("current_track_id") or "").strip()
    if current_id:
        excluded.append(current_id)
    tracks = resolve_candidates(spotify, payload.get("candidates"), excluded, payload.get("maximum", 10))
    minimum = max(1, int(payload.get("minimum", 4)))
    if len(tracks) < minimum:
        raise RuntimeError(f"Only {len(tracks)} verified Spotify tracks matched; need {minimum}")
    playback_started = False
    queued = 0
    if play:
        devices = (spotify_read(spotify.devices) or {}).get("devices") or []
        queued = play_resolved_queue(
            spotify, tracks, devices,
            existing_queue_uris=existing_queue_uris,
        )
        playback_started = True
    return {
        "ok": True, "tracks": tracks, "playback_started": playback_started,
        "queued": queued, "existing_queue_count": len(existing_queue_uris),
        "queue_preserved": True,
    }


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command not in {
        "context", "resolve", "play-queue", "start-curation", "restore-queue", "build-curation",
        "playback-state", "playback-control", "recent-contexts", "queue",
        "queue-add", "track-search", "shuffle",
    }:
        raise SystemExit(
            "Usage: spotify_curator_tool.py "
            "context|resolve|play-queue|start-curation|restore-queue|build-curation|"
            "playback-state|playback-control|recent-contexts|queue|"
            "queue-add|track-search|shuffle [JSON]"
        )
    try:
        if command == "context":
            result = listening_context(spotify_client())
        elif command in {"resolve", "play-queue"}:
            if len(sys.argv) < 3:
                raise ValueError("Missing music request")
            result = run(json.loads(sys.argv[2]), play=command == "play-queue")
        elif command == "start-curation":
            if len(sys.argv) < 3:
                raise ValueError("Missing music request")
            result = start_curated_playback(spotify_client(), json.loads(sys.argv[2]))
        elif command == "restore-queue":
            payload = json.loads(sys.argv[2] if len(sys.argv) > 2 else "{}")
            result = restore_existing_queue(
                spotify_client(), payload.get("existing_queue_uris") or []
            )
        elif command == "build-curation":
            if len(sys.argv) < 3:
                raise ValueError("Missing queue request")
            # Progress is newline-delimited JSON. The server consumes it as a
            # managed background job and updates the existing queue drawer.
            build_curated_queue(spotify_client(), json.loads(sys.argv[2]))
            return
        elif command == "playback-state":
            result = playback_snapshot(
                spotify_read(spotify_client().current_playback, attempts=1)
            )
        elif command == "playback-control":
            payload = json.loads(sys.argv[2] if len(sys.argv) > 2 else "{}")
            result = playback_control(
                spotify_client(),
                payload.get("action"),
                payload.get("position_ms"),
            )
        elif command == "recent-contexts":
            result = recent_contexts_snapshot(spotify_client())
        elif command == "queue":
            spotify = spotify_client()
            result = queue_snapshot(spotify_read(spotify.queue))
        elif command == "queue-add":
            uri = str(sys.argv[2] if len(sys.argv) > 2 else "")
            if not uri.startswith("spotify:track:"):
                raise ValueError("Invalid track")
            spotify_client().add_to_queue(uri)
            result = {"ok": True}
        elif command == "shuffle":
            payload = json.loads(sys.argv[2] if len(sys.argv) > 2 else "{}")
            result = set_playback_shuffle(
                spotify_client(),
                bool(payload.get("state", True)),
            )
        else:
            query = str(sys.argv[2] if len(sys.argv) > 2 else "").strip()
            if not query:
                result = {"tracks": []}
            else:
                spotify = spotify_client()
                response = spotify_read(
                    lambda: spotify.search(q=query, type="track", limit=8)
                )
                tracks = [
                    compact for compact in (
                        compact_queue_item(item)
                        for item in ((response.get("tracks") or {}).get("items") or [])
                    ) if compact and compact.get("uri")
                ]
                result = {"tracks": tracks}
        print(json.dumps(result))
    except Exception as error:
        status = getattr(error, "http_status", None)
        retry_after = spotify_retry_after(error)
        print(json.dumps({"ok": False, "error": str(error), "status": status, "retry_after": retry_after}), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
