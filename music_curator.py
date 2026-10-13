"""Pure helpers for Apollo's Spotify music curator."""

import re


TRACK_URI_RE = re.compile(r"^spotify:track:([A-Za-z0-9]{22})$")


def spotify_track_id(uri):
    """Return the track id only for a valid Spotify track URI."""
    match = TRACK_URI_RE.fullmatch(str(uri or "").strip())
    return match.group(1) if match else None


def wants_music_curation(request, intent=None, has_context=False):
    """Keep literal playback requests direct; route descriptive/refining ones."""
    text = " ".join(str(request or "").casefold().split())
    parsed = intent if isinstance(intent, dict) else {}
    mode = str(parsed.get("mode") or "").casefold()
    if mode in {"curate", "refine", "continue"}:
        return True

    style_markers = (
        "type shit", "-style", " style", "sounds like", "sound like",
        "vibe", "mood", "atmospheric", "underground", "obscure",
        "mainstream", "instrumental", "no rap", "production", "beats",
        "samples", "scratches", "rainy", "late-night", "late night",
        "sexy", "smooth", "darker", "lighter", "less depressing",
    )
    followups = (
        "keep this", "keep it", "more like", "less ", "more ",
        "another ", "third song", "second song", "first song",
    )
    if any(marker in text for marker in style_markers):
        return True
    if has_context and any(text.startswith(marker) for marker in followups):
        return True
    if mode == "direct":
        return False
    return str(parsed.get("type") or "").casefold() == "curation"


def normalize_curated_tracks(tracks, excluded_ids=(), maximum=10):
    """Validate Spotify data and preserve the planned order without duplicates."""
    excluded = {str(value) for value in excluded_ids if value}
    seen_ids = set(excluded)
    seen_artists = {}
    result = []
    for raw in tracks or []:
        if not isinstance(raw, dict):
            continue
        uri = str(raw.get("uri") or "").strip()
        track_id = spotify_track_id(uri)
        if not track_id or track_id in seen_ids:
            continue
        artists = raw.get("artists") or []
        if isinstance(artists, str):
            artists = [artists]
        artists = [str(value).strip() for value in artists if str(value).strip()]
        primary = artists[0].casefold() if artists else ""
        # A coherent queue can revisit an artist once, but must not become an
        # artist radio dump.
        if primary and seen_artists.get(primary, 0) >= 2:
            continue
        seen_ids.add(track_id)
        if primary:
            seen_artists[primary] = seen_artists.get(primary, 0) + 1
        result.append({
            "id": track_id,
            "uri": uri,
            "title": str(raw.get("title") or raw.get("name") or "").strip(),
            "artists": artists,
            "album": str(raw.get("album") or "").strip(),
            "spotify_url": str(raw.get("spotify_url") or "").strip(),
            "artwork": str(raw.get("artwork") or "").strip(),
            "popularity": raw.get("popularity"),
            "reason": str(raw.get("reason") or "").strip(),
        })
        if len(result) >= max(1, int(maximum)):
            break
    return result
