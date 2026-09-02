#!/usr/bin/env python3

import json
import re
import sys
import time as time_module
import urllib.parse
import urllib.request
from datetime import datetime, time
from zoneinfo import ZoneInfo

from server import (
    ask_hermes,
    db,
    init_db,
)


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


def get_recent_context():

    conn = db()

    rows = conn.execute("""
        SELECT
            m.role,
            m.content,
            m.created_at,
            c.title
        FROM messages m
        JOIN chats c
            ON c.id = m.chat_id
        ORDER BY m.id DESC
        LIMIT 40
    """).fetchall()

    conn.close()

    rows = list(reversed(rows))

    return [
        {
            "chat": row["title"],
            "role": row["role"],
            "content": row["content"],
            "created_at": row["created_at"]
        }
        for row in rows
    ]


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
        SELECT id
        FROM daily_debriefs
        WHERE local_date = ?
          AND timezone = ?
    """, (
        local_date,
        time_zone
    )).fetchone()

    conn.close()

    if existing and not force:
        return False

    recent = get_recent_context()

    weather = get_weather(
        time_zone
    )

    messages = [
        {
            "role": "system",
            "content": """You are Apollo preparing Santiago's daily personal intelligence brief.

BEFORE writing the brief, actively research the current web using your available
web_search and web_extract tools.

Research developments from roughly the last 24 hours and select only things
that are genuinely relevant, useful, surprising, or important for Santiago.

Prioritize:
- AI and technology
- music, especially R&B, hip-hop, artists, releases, production and music tech
- gaming and entertainment
- major world news worth knowing
- subjects connected to Santiago's current interests

Do not dump headlines.
Research first, compare sources, filter aggressively, and keep only the strongest
few items.

Personal Apollo conversation history is supporting context only.
Do not surface Apollo UI debugging, coding minutiae, button fixes, tests, or
development chatter unless it is genuinely important.

Calendar, Tasks, Whoop, Spotify, weather, and other personal data may be added
to this briefing later. If a source is not supplied, simply omit it. Never invent it.

The final response MUST be valid JSON and NOTHING ELSE.

Use exactly this structure:

{
  "summary": "One short sentence describing today's overall signal.",

  "items": [
    {
      "category": "AI / Tech",
      "headline": "A short useful headline",
      "body": "One or two concise sentences explaining what happened and why it matters.",
      "source": "OpenAI"
    }
  ],

  "personal_signal": {
    "headline": "A concise observation from Santiago's recent Apollo context",
    "body": "One useful sentence explaining the signal."
  },

  "worth_knowing": {
    "headline": "One important or interesting development outside Santiago's normal interests",
    "body": "One or two concise sentences explaining why it is worth knowing.",
    "source": "Publication or organization"
  }
}

RULES:
- items are the "Your World" section
- maximum 3 items
- minimum 2 items when enough worthwhile news exists
- personal_signal is OPTIONAL
- include personal_signal only when recent Apollo context contains a genuinely useful pattern, unfinished thread, recurring concern, project, or decision worth surfacing today
- if there is no strong personal signal, use null
- never manufacture a personal signal just to fill the section
- personal_signal must not expose trivial Apollo UI debugging or coding minutiae
- worth_knowing should contain exactly one strong development outside Santiago's usual interests when something genuinely worthwhile exists
- if nothing clears that bar, use null
- each headline should be short
- each body should be no more than 2 concise sentences
- source should be only the publication or organization name
- no URLs
- no markdown
- no bullet characters inside strings
- no greeting
- no filler
- no motivational advice
- no generic productivity coaching
- never fabricate current information
- if something cannot be verified, leave it out
- prioritize signal over completeness

Research first. Then return only the JSON object."""
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "local_date": local_date,
                    "local_time": now.isoformat(),
                    "timezone": time_zone,
                    "recent_apollo_context": recent
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

        summary = str(
            brief.get("summary", "")
        ).strip()

        items = brief.get("items", [])

        if not summary or not isinstance(items, list):
            continue

        clean_items = []

        for item in items[:3]:

            if not isinstance(item, dict):
                continue

            category = str(
                item.get("category", "")
            ).strip()

            headline = str(
                item.get("headline", "")
            ).strip()

            body = str(
                item.get("body", "")
            ).strip()

            source = str(
                item.get("source", "")
            ).strip()

            if not headline or not body:
                continue

            clean_items.append({
                "category": category or "Briefing",
                "headline": headline,
                "body": body,
                "source": source
            })

        if not clean_items:
            print(
                f"[Apollo Debrief] Attempt {attempt} contained no usable items."
            )
            continue


        def clean_signal(
            value,
            allow_source=False
        ):

            if not isinstance(
                value,
                dict
            ):
                return None

            headline = str(
                value.get(
                    "headline",
                    ""
                )
            ).strip()

            body = str(
                value.get(
                    "body",
                    ""
                )
            ).strip()

            if (
                not headline
                or not body
            ):
                return None

            result = {
                "headline":
                    headline,

                "body":
                    body
            }

            if allow_source:

                source = str(
                    value.get(
                        "source",
                        ""
                    )
                ).strip()

                if source:
                    result[
                        "source"
                    ] = source

            return result


        personal_signal = clean_signal(
            brief.get(
                "personal_signal"
            )
        )

        worth_knowing = clean_signal(
            brief.get(
                "worth_knowing"
            ),
            allow_source=True
        )


        final_brief = {
            "summary":
                summary,

            "items":
                clean_items
        }

        if weather:
            final_brief[
                "weather"
            ] = weather

        if personal_signal:
            final_brief[
                "personal_signal"
            ] = personal_signal

        if worth_knowing:
            final_brief[
                "worth_knowing"
            ] = worth_knowing

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
