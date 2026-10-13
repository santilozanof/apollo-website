#!/usr/bin/env python3

import json
import re
import sys
import time as time_module
import urllib.parse
import urllib.request
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from server import (
    ask_hermes,
    db,
    init_db,
)
import debrief_personalization


def get_state(key):
    conn = db()

    row = conn.execute(
        """
        SELECT value
        FROM app_state
        WHERE key = ?
        """,
        (key,)
    ).fetchone()

    conn.close()

    return row["value"] if row else None


def weather_code_label(code):

    try:
        code = int(code)
    except Exception:
        return "Mixed conditions"

    labels = {
        0: "Clear",
        1: "Mostly clear",
        2: "Partly cloudy",
        3: "Cloudy",
        45: "Foggy",
        48: "Foggy",
        51: "Light drizzle",
        53: "Drizzle",
        55: "Heavy drizzle",
        56: "Freezing drizzle",
        57: "Freezing drizzle",
        61: "Light rain",
        63: "Rain",
        65: "Heavy rain",
        66: "Freezing rain",
        67: "Freezing rain",
        71: "Light snow",
        73: "Snow",
        75: "Heavy snow",
        77: "Snow grains",
        80: "Light showers",
        81: "Showers",
        82: "Heavy showers",
        85: "Snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorms",
        96: "Thunderstorms",
        99: "Severe thunderstorms"
    }

    return labels.get(
        code,
        "Mixed conditions"
    )


def get_weather(time_zone):

    raw_latitude = get_state(
        "device_latitude"
    )

    raw_longitude = get_state(
        "device_longitude"
    )

    if (
        raw_latitude is None
        or raw_longitude is None
    ):
        return None

    try:
        latitude = float(
            raw_latitude
        )

        longitude = float(
            raw_longitude
        )
    except Exception:
        return None

    params = {
        "latitude":
            latitude,

        "longitude":
            longitude,

        "timezone":
            time_zone,

        "forecast_days":
            1,

        "daily":
            ",".join([
                "weather_code",
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_probability_max"
            ]),

        "hourly":
            "precipitation_probability"
    }

    url = (
        "https://api.open-meteo.com/v1/forecast?"
        + urllib.parse.urlencode(
            params
        )
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
                "Apollo/1.0"
        }
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=20
        ) as response:

            data = json.loads(
                response.read().decode(
                    "utf-8"
                )
            )

    except Exception as error:

        print(
            "[Apollo Weather]",
            error
        )

        return None


    daily = (
        data.get("daily")
        or {}
    )

    hourly = (
        data.get("hourly")
        or {}
    )


    def first(name):

        values = daily.get(
            name
        )

        if (
            isinstance(values, list)
            and values
        ):
            return values[0]

        return None


    high = first(
        "temperature_2m_max"
    )

    low = first(
        "temperature_2m_min"
    )

    rain_max = first(
        "precipitation_probability_max"
    )

    code = first(
        "weather_code"
    )

    condition = weather_code_label(
        code
    )


    rain_time = None
    rain_probability = 0

    hourly_times = (
        hourly.get("time")
        or []
    )

    hourly_rain = (
        hourly.get(
            "precipitation_probability"
        )
        or []
    )

    for timestamp, probability in zip(
        hourly_times,
        hourly_rain
    ):

        try:

            probability = int(
                probability
                or 0
            )

            hour = datetime.fromisoformat(
                timestamp
            ).hour

        except Exception:
            continue

        # Morning briefing: care most about
        # daytime/evening rain.
        if (
            6 <= hour <= 22
            and probability
            > rain_probability
        ):

            rain_probability = (
                probability
            )

            rain_time = hour


    headline = condition

    if high is not None:

        try:
            high_value = float(
                high
            )

            if high_value >= 38:
                headline += " and extremely hot"

            elif high_value >= 34:
                headline += " and very hot"

            elif high_value <= 5:
                headline += " and very cold"

        except Exception:
            pass


    body_parts = []

    if (
        low is not None
        and high is not None
    ):

        body_parts.append(
            (
                f"{round(float(low))}–"
                f"{round(float(high))}°C today"
            )
        )


    if (
        rain_probability >= 35
        and rain_time is not None
    ):

        suffix = (
            "AM"
            if rain_time < 12
            else "PM"
        )

        display_hour = (
            rain_time
            if 1 <= rain_time <= 12
            else (
                rain_time - 12
                if rain_time > 12
                else 12
            )
        )

        body_parts.append(
            (
                f"Rain risk peaks around "
                f"{display_hour} {suffix} "
                f"at {rain_probability}%"
            )
        )

    elif rain_max is not None:

        body_parts.append(
            (
                f"Rain chance up to "
                f"{round(float(rain_max))}%"
            )
        )


    return {
        "headline":
            headline,

        "body":
            ". ".join(
                body_parts
            ) + (
                "."
                if body_parts
                else ""
            )
    }


def generate(force=False):

    init_db()

    time_zone = (
        get_state("time_zone")
        or "America/Chicago"
    )

    try:
        zone = ZoneInfo(time_zone)
    except Exception:
        print(
            "[Apollo Debrief] Invalid timezone:",
            time_zone
        )
        return False

    now = datetime.now(zone)
    local_date = now.date().isoformat()

    # Normal scheduled runs wait until 5 AM.
    if not force and now.time() < time(5, 0):
        return False

    conn = db()

    existing = conn.execute("""
        SELECT id, content
        FROM daily_debriefs
        WHERE local_date = ?
          AND timezone = ?
    """, (
        local_date,
        time_zone
    )).fetchone()

    conn.close()

    if existing and not force:
        try:
            existing_content = json.loads(existing["content"] or "{}")
        except (TypeError, json.JSONDecodeError):
            existing_content = {}
        if existing_content.get("news_status") != "unavailable":
            return False

    conn = db()
    try:
        prior_stories = debrief_personalization.previous_stories(conn)
        feedback = debrief_personalization.feedback_rows(conn)
    finally:
        conn.close()

    location_hint = time_zone.rsplit("/", 1)[-1].replace("_", " ")

    messages = [
        {
            "role": "system",
            "content": """You research a small candidate pool for Apollo's Daily Debrief.

Actively research the current web using your available
web_search and web_extract tools.

Find 10-14 verified candidates, normally from the last 96 hours. This is a
candidate-gathering step: a deterministic ranker will make the final selection.

Interest priorities, not daily quotas:
- HIGH: alternative R&B, soul, trip-hop, jazz, house, underground music,
  sampling, production, new albums and artist releases; meaningful world news
- MEDIUM: men's fashion and culture; boxing and UFC; worthwhile
  music shows, exhibitions and opportunities near the supplied location hint
- LOW: AI/technology only when genuinely consequential; gaming only for a major
  noteworthy announcement

Do not infer interests from repeated prior coverage. Do not include routine
product updates, rumors, listicles, generic explainers, engagement bait, or
minor GTA/AI stories. Categories are never mandatory; return fewer candidates
if quality is weak.

Every fact must be supported by the direct source URL you provide. Open and
check the source. Never invent a story, publication, URL, date, quote, event,
or fact. Prefer primary sources and established reporting. Use the article or
official event page URL, never a search-results or publication-home URL.

Return valid JSON and nothing else, using exactly this structure:

{"candidates": [
    {
      "category": "Music",
      "topics": ["music"],
      "headline": "Short factual headline",
      "body": "One to three concise factual sentences explaining what happened and why it matters.",
      "source": "Publication or organization",
      "url": "https://direct-source.example/article",
      "published_at": "ISO-8601 timestamp",
      "importance": 0.0,
      "meaningful_new_development": false
    }
  ]}

RULES:
- topics must use only: music, local, fashion, boxing, ufc, culture,
  world, ai, technology, gaming
- Exclude football, soccer, FIFA, UEFA and World Cup coverage entirely
- Use topic "world" for internationally consequential developments
- Use topic "local" only for a verified event near the location hint
- importance is 0 to 1 and reflects real-world consequence, not popularity
- meaningful_new_development is true only when a continuing story has a
  substantive new event, decision, release, result, or consequence
- each headline is short; each body is one to three concise sentences
- no markdown
- if a required field cannot be verified, omit that candidate
- never include personal data in candidates
- prioritize quality over quantity"""
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "instruction": "Search the web for current news and verified direct sources.",
                    "local_date": local_date,
                    "local_time": now.isoformat(),
                    "timezone": time_zone,
                    "location_hint": location_hint
                },
                ensure_ascii=False
            )
        }
    ]

    content = ""

    retry_delays = [
        0,
        3,
        8,
        15
    ]

    for attempt, delay in enumerate(
        retry_delays,
        start=1
    ):

        if delay:
            print(
                f"[Apollo Debrief] Retrying in {delay}s..."
            )

            time_module.sleep(
                delay
            )

        try:
            candidate = ask_hermes(messages).strip()

        except Exception as error:
            print(
                f"[Apollo Debrief] Attempt {attempt} failed:",
                error
            )
            continue

        candidate_lower = candidate.lower()

        bad_response = (
            not candidate
            or "operation interrupted" in candidate_lower
            or "agent run did not produce" in candidate_lower
            or "internal server error" in candidate_lower
            or "timed out" in candidate_lower
        )

        if bad_response:
            print(
                f"[Apollo Debrief] Attempt {attempt} returned "
                "an invalid agent response."
            )
            continue

        # Remove accidental markdown fences if the model added them.
        cleaned = candidate.strip()

        if cleaned.startswith("```"):
            cleaned = re.sub(
                r"^```(?:json)?\s*",
                "",
                cleaned,
                flags=re.I
            )
            cleaned = re.sub(
                r"\s*```$",
                "",
                cleaned
            )

        try:
            brief = json.loads(cleaned)
        except json.JSONDecodeError:
            print(
                f"[Apollo Debrief] Attempt {attempt} returned invalid JSON."
            )
            continue

        if not isinstance(brief, dict):
            continue

        candidates = brief.get("candidates", [])
        if not isinstance(candidates, list):
            continue

        selected = debrief_personalization.select_stories(
            candidates,
            previous_stories=prior_stories,
            feedback_rows=feedback,
            now=now,
        )
        selected = debrief_personalization.verify_selected_links(selected)

        stories = selected["stories"]
        if len(stories) < 4:
            print(f"[Apollo Debrief] Attempt {attempt} contained fewer than four verified stories.")
            continue

        final_brief = {
            "stories": stories,
            "news_status": "ready",
        }

        content = json.dumps(
            final_brief,
            ensure_ascii=False
        )

        break

    if not content:
        print(
            "[Apollo Debrief] No valid debrief generated. "
            "Existing saved debrief was not overwritten."
        )
        return False

    conn = db()

    if force:

        conn.execute("""
            INSERT INTO daily_debriefs (
                local_date,
                timezone,
                content
            )
            VALUES (?, ?, ?)
            ON CONFLICT(local_date)
            DO UPDATE SET
                timezone = excluded.timezone,
                content = excluded.content,
                generated_at = CURRENT_TIMESTAMP
        """, (
            local_date,
            time_zone,
            content
        ))

    else:

        conn.execute("""
            INSERT INTO daily_debriefs (
                local_date,
                timezone,
                content
            )
            VALUES (?, ?, ?)
            ON CONFLICT(local_date)
            DO UPDATE SET
                timezone = excluded.timezone,
                content = excluded.content,
                generated_at = CURRENT_TIMESTAMP
        """, (
            local_date,
            time_zone,
            content
        ))

    conn.commit()
    conn.close()

    print(
        f"[Apollo Debrief] Generated for "
        f"{local_date} ({time_zone})"
    )

    return True


if __name__ == "__main__":
    generate(
        force="--force" in sys.argv
    )
