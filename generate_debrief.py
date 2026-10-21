#!/usr/bin/env python3
"""Daily executive briefing. Existing 05:00 local schedule; bounded research cost."""
import fcntl
import json
import re
import sys
from datetime import datetime, time
from zoneinfo import ZoneInfo

import debrief_context
import debrief_personalization
from server import (ask_hermes, db, init_db, DB_PATH, app_state_get, app_state_set,
                    apollo_calendar_events, get_tasks, apollo_connections_registry,
                    apollo_spotify_tool_command, whoop_current_summary)


def get_state(key):
    return app_state_get(key)


RESEARCH_PROMPT = """Research Apollo's concise executive briefing using web_search and web_extract.
Gather 8–12 significant candidates, mostly from the past 96 hours. Return fewer
when evidence is weak. This is an intelligence briefing, not a music discovery feed.
Priority: major world events; economics/business; consequential AI, technology and
science; developments in Mexico, Switzerland, France and the supplied location;
meaningful culture and an optional fascinating discovery. Existing feedback is a
preference signal, never evidence that an event occurred.
Music: at most ONE significant release, artist update, concert, or music-production
technology development. Match an explicitly supplied artist or a major production
advance. No genre-based discoveries, obscure recommendations or music fallback.
Use connected Spotify artists before static favorites. Skip music if nothing matters.
Each candidate explains what happened, why it matters and concrete relevance.
Do not infer private plans or personal facts. No generic motivation, clickbait,
minor celebrity gossip, speculation presented as fact, or football/soccer/FIFA.
Avoid previously covered stories; continuing news requires a substantive new event.
Open direct article URLs, verify publication metadata, and quote 6–20 consecutive
words as evidence. Never fabricate news, source URLs, dates or quotes. Prefer official
sources and reputable reporting. No homepages or search results. Distinguish confirmed
facts from attributed proposals or uncertainty. Use https direct URLs.
Return JSON only: {"candidates":[{"category":"World","topics":["world"],
"headline":"Concise factual headline","body":"What happened and why it matters.",
"why_care":"Specific practical or regional relevance without invented personalization.",
"details":"Optional short additional context, grounded in the same article.",
"source":"Publication","url":"https://...","published_at":"ISO-8601 timestamp",
"evidence_quote":"6–20 consecutive words from the article body",
"importance":0.8,"actionability":0.4,"meaningful_new_development":false}]}.
Topics: world, economics, business, ai, technology, science, local, culture, music.
Importance and actionability are 0–1. Return an empty pool when research is unavailable.
"""


def collect_personal(now):
    try: health = apollo_connections_registry(force=True, wait=True)
    except Exception: health = {'integrations': []}
    try:
        events, errors = apollo_calendar_events(days=1, start_date=now.date().isoformat(), time_zone=str(now.tzinfo))
    except Exception:
        events, errors = [], {'calendar': 'unavailable'}
    try: tasks, tasks_available = get_tasks(), True
    except Exception: tasks, tasks_available = [], False
    personal = debrief_context.personal_brief(now, events, tasks, health, errors, tasks_available)
    whoop = next((item for item in health.get('integrations', []) if item['id'] == 'whoop'), {})
    if whoop.get('status') == 'connected':
        try:
            observation = debrief_context.whoop_observation(whoop_current_summary(), now)
            if observation: personal['personal_intelligence'].append(observation)
            else: personal['availability'].append({'source': 'WHOOP', 'message': "Today's scored overnight measurements are not available yet."})
        except Exception:
            personal['availability'].append({'source': 'WHOOP', 'message': 'Current health measurements could not be loaded.'})
    return personal, health


def generate(force=False):
    init_db()
    # Nonblocking cross-process lock prevents overlapping scheduler/manual runs.
    with open(DB_PATH.parent / '.debrief-generation.lock', 'a') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return False
        return _generate(force)


def _generate(force=False):
    time_zone = get_state('time_zone') or 'America/Chicago'
    try: zone = ZoneInfo(time_zone)
    except Exception: return False
    now = datetime.now(zone)
    local_date = now.date().isoformat()
    if not force and now.time() < time(5, 0): return False
    conn = db()
    try:
        row = conn.execute('SELECT content FROM daily_debriefs WHERE local_date=?', (local_date,)).fetchone()
        try: existing = json.loads(row['content']) if row else {}
        except (ValueError, TypeError): existing = {}
        prior = debrief_personalization.previous_stories(conn)
        feedback = [dict(row) for row in debrief_personalization.feedback_rows(conn)]
    finally: conn.close()
    if existing.get('version') == 2 and existing.get('news_status') == 'ready' and not force: return False
    attempt_key = 'debrief_attempt:' + local_date
    try: attempts = json.loads(get_state(attempt_key) or '{}')
    except (TypeError, ValueError): attempts = {}
    elapsed = now.timestamp() - float(attempts.get('at') or 0)
    if elapsed < (900 if force else 7200) or (not force and attempts.get('count', 0) >= 3): return False
    app_state_set(attempt_key, json.dumps({'at': now.timestamp(), 'count': attempts.get('count', 0) + 1}))
    personal, health = collect_personal(now)
    artists = debrief_context.FAVORITE_ARTISTS
    spotify = next((item for item in health.get('integrations', []) if item['id'] == 'spotify'), {})
    if spotify.get('status') == 'connected':
        try:
            context = apollo_spotify_tool_command('context', timeout=12)
            actual = list(context.get('top_artists') or [])
            for track in context.get('recent_tracks') or []: actual.extend(track.get('artists') or [])
            if actual: artists = list(dict.fromkeys(actual))[:30]
            else: personal['availability'].append({'source': 'Spotify', 'message': 'Listening preferences unavailable; using your saved artist preferences.'})
        except Exception:
            personal['availability'].append({'source': 'Spotify', 'message': 'Listening preferences unavailable; music will not replace missing news.'})
    messages = [
        {'role': 'system', 'content': RESEARCH_PROMPT},
        {'role': 'user', 'content': json.dumps({
            'instruction': 'Search the web for current news and verified direct sources.',
            'local_date': local_date, 'local_time': now.isoformat(), 'timezone': time_zone,
            'location_hint': time_zone.rsplit('/', 1)[-1].replace('_', ' '),
            'relevant_regions': ['Mexico', 'Switzerland', 'France'],
            'preferred_artists': artists,
            'previous_headlines': [item['headline'] for item in prior][-60:],
            'feedback': [{'headline': item['headline'], 'preference': item['feedback'], 'topics': item['topics_json']} for item in feedback[:30]],
        }, ensure_ascii=False)},
    ]
    stories = []
    # Retry only a malformed/failed research response, not a small valid pool.
    for attempt in range(2):
        try:
            raw = ask_hermes(messages, enabled_toolsets=("web",)).strip()
            raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.I)
            candidates = json.loads(raw).get('candidates', [])
            if not isinstance(candidates, list): raise ValueError('Invalid candidates')
            selected = debrief_personalization.select_stories(candidates[:16], prior, feedback, now, artists)
            stories = debrief_personalization.verify_selected_links(selected)['stories']
            break
        except Exception:
            continue
    # Strict verification can remove all non-music articles; never backfill with music.
    if stories and all('music' in item['topics'] for item in stories): stories = []
    status = 'ready' if stories else 'unavailable'
    if not stories and existing.get('version') == 2 and existing.get('news_status') == 'ready':
        stories = existing.get('stories', [])
        status = 'ready'
        personal['availability'].append({'source': 'News', 'message': 'News could not be refreshed; showing earlier verified coverage from today.'})
    if status == 'unavailable':
        personal['availability'].append({'source': 'News', 'message': 'Current news could not be verified. No unverified stories or music filler have been added.'})
    brief = {**personal, 'version': 2, 'as_of': now.isoformat(), 'stories': stories, 'news_status': status}
    conn = db()
    try:
        conn.execute('''INSERT INTO daily_debriefs (local_date, timezone, content) VALUES (?, ?, ?)
            ON CONFLICT(local_date) DO UPDATE SET timezone=excluded.timezone, content=excluded.content,
            generated_at=CURRENT_TIMESTAMP''', (local_date, time_zone, json.dumps(brief, ensure_ascii=False)))
        conn.commit()
    finally: conn.close()
    print(f'[Apollo Debrief] Saved {local_date}: {len(stories)} verified stories; news {status}')
    return True


if __name__ == '__main__':
    generate(force='--force' in sys.argv)
