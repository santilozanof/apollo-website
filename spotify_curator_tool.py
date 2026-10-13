"""Resolve AI music suggestions against Spotify and optionally play them.

The AI supplies names, never IDs. This adapter is the sole source of Spotify
URIs and validates every selection before any playback mutation occurs.
"""

import json
import os
import re
import sys
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
            response = spotify.search(q=query, type="track", limit=8)
            for item in (response.get("tracks") or {}).get("items") or []:
                if item.get("id") and item.get("id") not in excluded:
                    found[item["id"]] = item
        # Most suggestions resolve with one strict request. Only spend a
        # second request when Spotify's field search cannot find a close match.
        best_strict = max(
            [candidate_score(item, title, artist) for item in found.values()] or [0]
        )
        if best_strict < 0.82:
            response = spotify.search(q=f"{title} {artist}", type="track", limit=8)
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
    return normalize_curated_tracks(resolved, excluded, maximum)


def existing_queue_ids(spotify):
    try:
        data = spotify.queue() or {}
    except Exception:
        return [], 0
    items = [item for item in data.get("queue") or [] if isinstance(item, dict)]
    return [item.get("id") for item in items if item.get("id")], len(items)


def play_resolved_queue(spotify, tracks, devices):
    """Start the opener, then append the verified tracks in their plan order."""
    active = next(
        (item for item in devices or [] if item.get("is_active") and not item.get("is_restricted")),
        None,
    )
    if not active:
        raise RuntimeError("No active, controllable Spotify device is available")
    spotify.start_playback(device_id=active.get("id"), uris=[tracks[0]["uri"]], position_ms=0)
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
    ))


def listening_context(spotify):
    """Return compact permitted listening signals, never private token data."""
    recent = spotify.current_user_recently_played(limit=15) or {}
    top = spotify.current_user_top_artists(limit=10, time_range="short_term") or {}
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
    queued_ids, existing_count = existing_queue_ids(spotify)
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
        devices = (spotify.devices() or {}).get("devices") or []
        queued = play_resolved_queue(spotify, tracks, devices)
        playback_started = True
    return {
        "ok": True, "tracks": tracks, "playback_started": playback_started,
        "queued": queued, "existing_queue_count": existing_count,
        "queue_preserved": True,
    }


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command not in {"context", "resolve", "play-queue"} or len(sys.argv) < 3:
        raise SystemExit("Usage: spotify_curator_tool.py context|resolve|play-queue JSON")
    payload = json.loads(sys.argv[2])
    try:
        result = listening_context(spotify_client()) if command == "context" else run(payload, play=command == "play-queue")
        print(json.dumps(result))
    except Exception as error:
        status = getattr(error, "http_status", None)
        retry_after = getattr(error, "headers", {}).get("Retry-After") if getattr(error, "headers", None) else None
        print(json.dumps({"ok": False, "error": str(error), "status": status, "retry_after": retry_after}), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
