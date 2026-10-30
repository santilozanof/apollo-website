"""Trusted Chat presentation of the same recorded rankings as Music Insights."""

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import music_analytics


_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_RANKING = re.compile(
    r"\b(?:top|most\s+(?:played|listened(?:\s+to)?))\s+"
    r"(?:(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\s+)?"
    r"(albums?|tracks?|songs?|artists?|playlists?)\b", re.I,
)
_ART_FOLLOWUP = re.compile(
    r"^\s*(?:(?:but|and|okay|ok|please)\s+)*(?:show\s+(?:me\s+)?)?"
    r"(?:it|them|those|the\s+same\s+(?:ranking|list))?\s*"
    r"(?:with\s+)?(?:images?|artwork|covers?|photos?)\s*[.!?]*\s*$", re.I,
)
_FENCE = re.compile(r"```apollo-ui\s*\n([\s\S]*?)\n```", re.I)
_SPOTIFY_URL = re.compile(r"https://open\.spotify\.com/(album|track|artist)/[A-Za-z0-9]{22}$")


def _previous_block(messages):
    for message in reversed(messages[:-1]):
        if message.get("role") != "assistant":
            continue
        for match in reversed(list(_FENCE.finditer(str(message.get("content") or "")))):
            try:
                payload = json.loads(match.group(1))
            except (TypeError, ValueError):
                continue
            for block in reversed(payload.get("blocks", [])) if isinstance(payload, dict) else ():
                if isinstance(block, dict) and block.get("type") == "media_ranking" \
                        and block.get("data_source") == "apollo.music.rankings":
                    return block
    return None


def intent(message, messages=()):
    """Return a bounded read request, or None for ordinary conversation."""
    if not isinstance(message, str):
        return None
    if _ART_FOLLOWUP.fullmatch(message):
        block = _previous_block(messages)
        if block:
            return {"followup": block}
    match = _RANKING.search(message)
    if not match:
        return None
    # The direct renderer can answer one ranking (or its adjacent-period
    # comparison). Compound requests need the ordinary tool coordinator so
    # no recommendation, explanation or action is silently discarded.
    if re.search(r"\b(?:recommend|suggest|explain|summarize|analy[sz]e|plan|create|add|play|why|how|based\s+on)\b", message, re.I):
        return None
    if re.search(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December|20\d{2})\b", message, re.I):
        return None
    entity = {"album": "albums", "albums": "albums", "song": "tracks",
              "songs": "tracks", "track": "tracks", "tracks": "tracks",
              "artist": "artists", "artists": "artists",
              "playlist": "playlists", "playlists": "playlists"}[match.group(2).lower()]
    count = _NUMBERS.get(match.group(1).lower(), 5) if match.group(1) and not match.group(1).isdigit() \
        else int(match.group(1) or 5)
    metric = ("verified" if re.search(r"\bverified\b", message, re.I)
              else "estimated" if re.search(r"\bestimated\b", message, re.I)
              else "plays" if re.search(r"\b(?:plays?|streams?|play\s+count)\b", message, re.I)
              else "listening")
    return {"entity": entity, "count": max(1, min(count, 20)), "metric": metric,
            "compare": bool(re.search(r"\bcompar(?:e|ison|ing)\b", message, re.I)),
            "message": message}


def _scope(message, timezone):
    try:
        today = datetime.now(ZoneInfo(timezone)).date()
    except (KeyError, ValueError):
        timezone = "UTC"
        today = datetime.now(ZoneInfo("UTC")).date()
    lower = message.casefold()
    if "all time" in lower or "lifetime" in lower or "ever" in lower:
        return "lifetime", today, timezone
    if "yesterday" in lower:
        return "daily", today - timedelta(days=1), timezone
    if re.search(r"\btoday\b", lower):
        return "daily", today, timezone
    if "this week" in lower:
        return "weekly", today, timezone
    if "last week" in lower:
        return "weekly", today - timedelta(days=7), timezone
    if "weekly" in lower:
        return "weekly", today, timezone
    if "this month" in lower:
        return "monthly", today, timezone
    if "last month" in lower:
        return "monthly", today.replace(day=1) - timedelta(days=1), timezone
    if "this year" in lower:
        return "yearly", today, timezone
    if "last year" in lower:
        return "yearly", date(today.year - 1, 1, 1), timezone
    if "yearly" in lower:
        return "yearly", today, timezone
    return "monthly", today, timezone


def _minutes(value):
    return f"{(max(0, int(value or 0)) + 30000) // 60000:,}"


def _safe_cell(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")[:140]


def _block(report, count):
    entity, metric = report["entity"], report["metric"]
    period = report["period"]
    label = {"listening": "Verified listening minutes", "verified": "Verified minutes",
             "estimated": "Estimated minutes", "plays": "Plays"}[metric]
    available = metric == "plays" or bool(report.get("metric_available"))
    items = []
    for row in report["items"][:count] if available else []:
        key = str(row.get("entity_key") or row["name"])
        verified_ms, estimated_ms = int(row.get("verified_ms") or 0), int(row.get("estimated_ms") or 0)
        measurement = ("count" if metric == "plays" else
                       "estimated" if metric == "estimated" and estimated_ms else
                       "verified" if verified_ms and metric != "estimated" else "unavailable")
        url = str(row.get("spotify_url") or "")
        items.append({
            "id": hashlib.sha256(key.encode()).hexdigest()[:16],
            "rank": int(row["rank"]),
            "title": str(row["name"])[:160],
            "secondary": str(row.get("artist_name") or ("Artist" if entity == "artists" else ""))[:160],
            "album": str(row.get("album_name") or "")[:160] if entity == "tracks" else "",
            "artwork_url": str(row.get("image_url") or ""),
            "artwork_kind": str(row.get("image_kind") or ""),
            "spotify_url": url if _SPOTIFY_URL.fullmatch(url) else "",
            "plays": int(row.get("plays") or 0),
            "verified_ms": verified_ms,
            "estimated_ms": estimated_ms,
            "metric_value": int(row.get({"plays": "plays", "listening": "listening_ms",
                                         "verified": "verified_ms", "estimated": "estimated_ms"}[metric]) or 0),
            "measurement": measurement,
        })
    subtitle = f"{period['label']} · {label}" if available else (
        f"{period['label']} · No {'verified' if metric in ('listening', 'verified') else 'observed'} minutes are available for this period")
    return {"type": "media_ranking", "id": f"ranking-{entity}-{metric}-{period['kind']}-{period['anchor']}",
            "data_source": "apollo.music.rankings", "state": ("ready" if items else "empty" if available else "unavailable"),
            "entity": entity, "metric": metric, "title": f"Top {count} {entity}",
            "subtitle": subtitle, "items": items}


def _envelope(blocks):
    return "```apollo-ui\n" + json.dumps({"schema": "apollo.rich", "version": 3,
                                         "blocks": blocks}, ensure_ascii=False, separators=(",", ":")) + "\n```"


def response(conn, request, messages, timezone="UTC"):
    """Build a persisted component from authoritative aggregate rows."""
    if "followup" in request:
        return _envelope([request["followup"]])
    entity, metric, count = request["entity"], request["metric"], request["count"]
    if entity == "playlists":
        return "Apollo does not have a verified listening-history ranking for playlists yet."
    kind, anchor, zone = _scope(request["message"], timezone)
    if request["compare"]:
        current = music_analytics.rankings(conn, kind, anchor.isoformat(), zone, entity, metric,
                                           limit=count)
        previous_anchor = (anchor.replace(day=1) - timedelta(days=1) if kind == "monthly"
                           else anchor - timedelta(days=7) if kind == "weekly"
                           else date(anchor.year - 1, 1, 1) if kind == "yearly"
                           else anchor - timedelta(days=1))
        previous = music_analytics.rankings(conn, kind, previous_anchor.isoformat(), zone,
                                            entity, metric, limit=count)
        by_key = {row["entity_key"]: row for row in previous["items"]}
        value_key = {"plays": "plays", "listening": "listening_ms", "verified": "verified_ms",
                     "estimated": "estimated_ms"}[metric]
        unit = "plays" if metric == "plays" else "minutes"
        lines = [f"## {current['period']['label']} vs {previous['period']['label']}",
                 f"Ranked by {unit}. Verified minutes come from imported Spotify history; recent API plays without duration are excluded.",
                 "", f"| Rank | {entity.title()} | Current {unit} | Previous {unit} |", "|---:|---|---:|---:|"]
        for row in current["items"][:count]:
            prior = by_key.get(row["entity_key"])
            current_value = f"{int(row[value_key]):,}" if metric == "plays" else _minutes(row[value_key])
            previous_value = (f"{int(prior[value_key]):,}" if metric == "plays" else _minutes(prior[value_key])) if prior else "—"
            lines.append(f"| {row['rank']} | {_safe_cell(row['name'])} | {current_value} | {previous_value} |")
        if not current["items"]:
            lines.append("| — | No recorded plays | — | — |")
        return "\n".join(lines)
    report = music_analytics.rankings(conn, kind, anchor.isoformat(), zone, entity, metric,
                                       limit=count)
    return _envelope([_block(report, count)])
