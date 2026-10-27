"""Deterministic personalization and quality controls for Daily Debrief stories."""

import hashlib
import json
import math
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlparse


TOPIC_PRIORITIES = {
    "world": 3.5, "economics": 3.2, "business": 3.0, "science": 3.1,
    "ai": 3.0, "technology": 3.0, "local": 3.0, "culture": 2.0,
    "music": 0.1, "fashion": 1.0, "boxing": 1.0, "ufc": 1.0, "gaming": 0.5,
}

EXCLUDED_TOPICS = {"football", "fifa"}
EXCLUDED_STORY_PATTERN = re.compile(
    r"\b(?:football|soccer|fifa|uefa|world cup)\b",
    re.IGNORECASE,
)

HIGH_CREDIBILITY_DOMAINS = {
    "apnews.com", "bbc.com", "bbc.co.uk", "reuters.com", "theguardian.com",
    "ft.com", "nytimes.com", "npr.org", "aljazeera.com", "swissinfo.ch",
    "admin.ch", "who.int", "un.org", "europa.eu", "nature.com", "science.org",
    "cern.ch", "ethz.ch", "epfl.ch", "france24.com", "lemonde.fr", "banxico.org.mx",
    "bandcamp.com", "daily.bandcamp.com", "pitchfork.com", "ra.co",
    "residentadvisor.net", "billboard.com", "rollingstone.com", "jazzwise.com",
    "thefader.com", "stereogum.com", "officialcharts.com",
    "vogue.com", "gq.com", "highsnobiety.com", "ufc.com", "espn.com",
}

LOW_QUALITY_PHRASES = {
    "you won't believe", "what happened next", "breaks the internet",
    "shocking", "mind-blowing", "must see", "game changer", "everything we know",
    "fans are losing it", "internet reacts", "rumor roundup",
}

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "in", "into", "is", "it", "its", "of", "on", "or", "that", "the", "this",
    "to", "was", "will", "with", "new", "latest", "today",
}


def init_schema(conn):
    # The existing schema initializer already commits before running DDL. Keep
    # migration itself atomic so web and scheduled processes cannot race it.
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        table = conn.execute("SELECT sql FROM sqlite_master WHERE name='debrief_story_feedback'").fetchone()
        migrate = table and '-2' not in table[0]
        if migrate:
            conn.execute("ALTER TABLE debrief_story_feedback RENAME TO debrief_feedback_legacy")
            conn.execute("DROP INDEX IF EXISTS idx_debrief_feedback_updated")
        conn.execute("""CREATE TABLE IF NOT EXISTS debrief_story_feedback (
            story_id TEXT PRIMARY KEY,
            feedback INTEGER NOT NULL CHECK(feedback IN (-2, -1, 1)),
            topics_json TEXT NOT NULL DEFAULT '[]', source_domain TEXT,
            headline TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_debrief_feedback_updated ON debrief_story_feedback(updated_at DESC)")
        if migrate:
            conn.execute("INSERT INTO debrief_story_feedback SELECT * FROM debrief_feedback_legacy")
            conn.execute("DROP TABLE debrief_feedback_legacy")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _tokens(value):
    return {
        token for token in re.findall(r"[a-z0-9]+", _text(value).lower())
        if len(token) > 2 and token not in STOP_WORDS
    }


def story_id(story):
    key = _text(story.get("url")) or (
        _text(story.get("source")).lower() + "|" + _text(story.get("headline")).lower()
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def source_domain(url):
    try:
        host = (urlparse(_text(url)).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _domain_matches(domain, expected):
    return domain == expected or domain.endswith("." + expected)


def credibility_score(url):
    domain = source_domain(url)
    if not domain:
        return 0.0
    if any(_domain_matches(domain, trusted) for trusted in HIGH_CREDIBILITY_DOMAINS):
        return 1.0
    return 0.55


def similarity(left, right):
    a = _tokens(left)
    b = _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _parse_date(value):
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def freshness_score(published_at, now):
    published = _parse_date(published_at)
    if not published:
        return 0.0
    age_hours = (now.astimezone(timezone.utc) - published.astimezone(timezone.utc)).total_seconds() / 3600
    if age_hours < -6:
        return 0.0
    age_hours = max(0.0, age_hours)
    if age_hours <= 36:
        return 1.0
    if age_hours <= 96:
        return 0.75
    if age_hours <= 168:
        return 0.4
    return 0.1 if age_hours <= 720 else 0.0


def _topics(value):
    raw = value if isinstance(value, list) else [value]
    result = []
    for topic in raw:
        normalized = re.sub(r"[^a-z0-9_]+", "_", _text(topic).lower()).strip("_")
        if normalized and normalized not in result:
            result.append(normalized)
    return result[:5]


def normalize_candidate(candidate):
    if not isinstance(candidate, dict):
        return None
    try:
        importance = float(candidate.get("importance") or 0)
    except (TypeError, ValueError):
        importance = 0.0
    item = {
        "category": _text(candidate.get("category")) or "For You",
        "headline": _text(candidate.get("headline")),
        "body": _text(candidate.get("body")),
        "source": _text(candidate.get("source")),
        "url": _text(candidate.get("url")),
        "published_at": _text(candidate.get("published_at")),
        "topics": _topics(candidate.get("topics") or candidate.get("topic")),
        "details": _text(candidate.get("details")),
        "why_care": _text(candidate.get("why_care")),
        "evidence_quote": _text(candidate.get("evidence_quote"))[:300],
        "actionability": max(0, min(1, float(candidate.get("actionability") or 0))) if str(candidate.get("actionability") or "0").replace('.', '', 1).isdigit() else 0,
        "importance": max(0.0, min(1.0, importance)),
        "meaningful_new_development": bool(candidate.get("meaningful_new_development")),
    }
    if not item["headline"] or not item["body"] or not item["source"]:
        return None
    # Do not let an article evade the music cap through a different category.
    combined = (item['headline'] + ' ' + item['body']).casefold()
    if 'music' in item['category'].casefold() or re.search(r"\b(album|singer|musician|concert|music production|song release|record label)\b", combined):
        if 'music' not in item['topics']: item['topics'].append('music')
    item["id"] = story_id(item)
    item["source_domain"] = source_domain(item["url"])
    return item


def feedback_affinity(feedback_rows, candidate, now):
    score = 0.0
    candidate_topics = set(candidate.get("topics") or [])
    domain = candidate.get("source_domain") or ""
    for row in feedback_rows:
        row = dict(row)
        try:
            row_topics = set(json.loads(row.get("topics_json") or "[]"))
        except (TypeError, json.JSONDecodeError):
            row_topics = set()
        updated = _parse_date(row.get("updated_at")) or now
        age_days = max(0.0, (now.astimezone(timezone.utc) - updated.astimezone(timezone.utc)).total_seconds() / 86400)
        decay = math.exp(-age_days / 90.0)
        value = int(row.get("feedback") or 0)
        if row.get("story_id") == candidate.get("id"):
            score += value * 4.0 * decay
        overlap = len(candidate_topics & row_topics)
        if overlap:
            score += value * min(2, overlap) * 0.8 * decay
        if domain and domain == row.get("source_domain"):
            score += value * 0.35 * decay
    return max(-5.0, min(3.0, score))


def score_candidate(candidate, previous_stories, feedback_rows, now, preferred_artists=None):
    headline_lower = candidate["headline"].lower()
    if (
        set(candidate.get("topics") or []) & EXCLUDED_TOPICS
        or EXCLUDED_STORY_PATTERN.search(
            " ".join((candidate["headline"], candidate["body"], candidate["source"]))
        )
    ):
        return None
    if any(phrase in headline_lower for phrase in LOW_QUALITY_PHRASES):
        return None
    if len(candidate["headline"]) > 180 or len(candidate["body"]) < 35:
        return None
    if not candidate["url"].startswith(("https://", "http://")):
        return None
    credibility = credibility_score(candidate["url"])
    freshness = freshness_score(candidate["published_at"], now)
    if credibility <= 0 or freshness <= 0:
        return None

    if re.search(r"\byour (?:trip|flight|meeting|appointment|assignment|doctor|class)\b", candidate['body'] + ' ' + candidate.get('why_care', ''), re.I):
        return None  # Research candidates have no verified private-plan evidence.
    topic_score = max((TOPIC_PRIORITIES.get(topic, 1.0) for topic in candidate["topics"]), default=1.0)
    text = (candidate["headline"] + " " + candidate["body"]).casefold()
    is_music = "music" in candidate["topics"] or candidate["category"].casefold() == "music"
    if is_music:
        from debrief_context import FAVORITE_ARTISTS
        artists = FAVORITE_ARTISTS if preferred_artists is None else preferred_artists
        relevant_artist = any(re.search(r"(?<!\w)" + re.escape(artist.casefold()) + r"(?!\w)", text) for artist in artists if artist)
        production = bool(re.search(r"\b(daw|music production|audio plugin|synthesizer)\b", text)) and candidate['importance'] >= .85
        meaningful = bool(re.search(r"\b(release[sd]?|announc\w*|album|tour|concert|died|premiere|launch\w*)\b", text))
        if not ((relevant_artist and meaningful) or production): return None
    elif candidate['importance'] < .45:
        return None
    for row in feedback_rows:
        row = dict(row)
        if row.get('story_id') == candidate['id'] and int(row.get('feedback') or 0) == -2:
            return None
    for prior in previous_stories:
        if prior.get('id') == candidate['id'] or prior.get('url') == candidate['url']:
            return None

    prior_similarity = max(
        (similarity(candidate["headline"], prior.get("headline", "")) for prior in previous_stories),
        default=0.0,
    )
    if prior_similarity >= 0.72 and not candidate["meaningful_new_development"]:
        return None

    novelty = 1.0 - prior_similarity
    feedback = feedback_affinity(feedback_rows, candidate, now)
    # Region evidence and explicit feedback supply relevance; never model-invented private facts.
    regional_relevance = 1.0 if re.search(r"\b(mexico|mexican|switzerland|swiss|france|french|zurich|zürich)\b", text) else 0.0
    score = (
        topic_score * 2.2
        + candidate["importance"] * 3.0
        + freshness * 2.0
        + novelty * 2.2
        + credibility * 1.6
        + regional_relevance * 1.5
        + candidate["actionability"] * 1.5
        + feedback
    )
    candidate = dict(candidate)
    candidate["relevance_score"] = round(score, 3)
    return candidate


def select_stories(candidates, previous_stories=None, feedback_rows=None, now=None, preferred_artists=None):
    now = now or datetime.now(timezone.utc)
    previous_stories = previous_stories or []
    feedback_rows = feedback_rows or []
    ranked = []
    seen_ids = set()
    for raw in candidates or []:
        candidate = normalize_candidate(raw)
        if not candidate or candidate["id"] in seen_ids:
            continue
        scored = score_candidate(candidate, previous_stories, feedback_rows, now, preferred_artists)
        if scored:
            ranked.append(scored)
            seen_ids.add(candidate["id"])
    ranked.sort(key=lambda item: item["relevance_score"], reverse=True)

    stories = []
    music_count = 0
    for item in ranked:
        music = "music" in item["topics"] or item['category'].casefold() == 'music'
        if music and music_count >= 1: continue
        if any(similarity(item['headline'], chosen['headline']) >= .65 for chosen in stories): continue
        stories.append(item)
        music_count += int(music)
        if len(stories) == 6: break
    # Never publish a music-only fallback when news sources fail.
    if stories and all('music' in item['topics'] or item['category'].casefold() == 'music' for item in stories): stories = []
    worth = [item for item in stories if "world" in item["topics"] and item["importance"] >= 0.72][:2]
    worth_ids = {item["id"] for item in worth}
    for_you = [item for item in stories if item["id"] not in worth_ids][:3]
    # Keep the overall editorial package small even if two world stories qualify.
    remaining = max(0, 5 - len(for_you))
    worth = worth[:remaining]
    return {"stories": stories, "for_you": for_you, "worth_knowing": worth}


def source_url_is_reachable(url, timeout=8):
    request = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": "Apollo-Daily-Debrief/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= int(response.status) < 400
    except urllib.error.HTTPError as error:
        # Authentication/rate-limit/method blocks still prove the direct URL
        # exists; missing and gone pages do not.
        return False
    except Exception:
        return False


def verify_selected_links(selection, checker=None):
    check = (lambda item: checker(item["url"])) if checker else verify_article
    stories = list(selection.get("stories") or [])
    if not stories:
        stories = list(selection.get("for_you") or []) + list(selection.get("worth_knowing") or [])
    if not stories:
        return {"stories": [], "for_you": [], "worth_knowing": []}
    with ThreadPoolExecutor(max_workers=min(5, len(stories))) as pool:
        reachable = dict(zip((item["id"] for item in stories), pool.map(check, stories)))
    result = {
        key: [item for item in selection.get(key) or [] if reachable.get(item["id"])]
        for key in ("for_you", "worth_knowing")
    }
    result["stories"] = [item for item in selection.get("stories") or [] if reachable.get(item["id"])]
    return result


def previous_stories(conn, limit_days=14):
    rows = conn.execute("""
        SELECT content FROM daily_debriefs
        WHERE local_date >= date('now', ?)
        ORDER BY local_date DESC, id DESC
    """, (f"-{int(limit_days)} days",)).fetchall()
    result = []
    for row in rows:
        try:
            content = json.loads(row["content"])
        except (TypeError, json.JSONDecodeError):
            continue
        for key in ("stories", "for_you", "worth_knowing", "items"):
            value = content.get(key) or []
            if isinstance(value, dict):
                value = [value]
            for item in value:
                if isinstance(item, dict) and item.get("headline"):
                    result.append(item)
    return result


def feedback_rows(conn):
    return conn.execute("""
        SELECT story_id, feedback, topics_json, source_domain, headline, updated_at
        FROM debrief_story_feedback
        WHERE updated_at >= datetime('now', '-180 days')
        ORDER BY updated_at DESC
    """).fetchall()


def save_feedback(conn, payload):
    value = str(payload.get("feedback") or "").strip().lower()
    if value not in {"more", "less", "not_interested"}:
        raise ValueError("Feedback must be more, less, or not_interested")
    headline = _text(payload.get("headline"))[:240]
    if not headline:
        raise ValueError("Story headline is required")
    story = {
        "url": _text(payload.get("url")),
        "source": _text(payload.get("source")),
        "headline": headline,
    }
    identifier = _text(payload.get("story_id")) or story_id(story)
    topics = _topics(payload.get("topics"))
    domain = source_domain(story["url"])
    conn.execute("""
        INSERT INTO debrief_story_feedback
            (story_id, feedback, topics_json, source_domain, headline, updated_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(story_id) DO UPDATE SET
            feedback=excluded.feedback,
            topics_json=excluded.topics_json,
            source_domain=excluded.source_domain,
            headline=excluded.headline,
            updated_at=CURRENT_TIMESTAMP
    """, (identifier, {"more": 1, "less": -1, "not_interested": -2}[value], json.dumps(topics), domain, headline))
    return {"ok": True, "story_id": identifier, "feedback": value}


def verify_article(story, timeout=8):
    """Check actual article evidence and publication metadata, not just HEAD status."""
    import ipaddress
    import socket
    from html.parser import HTMLParser

    class Article(HTMLParser):
        def __init__(self):
            super().__init__(); self.text = []; self.dates = []; self.skip = 0
        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if tag in {'script', 'style'}: self.skip += 1
            if tag == 'meta' and (values.get('property') or values.get('name') or values.get('itemprop') or '').lower() in {
                'article:published_time', 'datepublished', 'date', 'pubdate', 'parsely-pub-date', 'dc.date.issued'}:
                self.dates.append(values.get('content', ''))
            if tag == 'time' and values.get('datetime'): self.dates.append(values['datetime'])
        def handle_endtag(self, tag):
            if tag in {'script', 'style'}: self.skip = max(0, self.skip - 1)
        def handle_data(self, data):
            if not self.skip: self.text.append(data)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs): return None

    url = story.get('url', '')
    parsed = urlparse(url)
    try:
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443): return False
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses): return False
        request = urllib.request.Request(url, headers={'User-Agent': 'Apollo-Debrief/2.0', 'Accept': 'text/html'})
        with urllib.request.build_opener(NoRedirect).open(request, timeout=timeout) as response:
            if response.status != 200 or 'text/html' not in response.headers.get('Content-Type', ''): return False
            raw = response.read(1_500_001)
        if len(raw) > 1_500_000: return False
        html = raw.decode('utf-8', errors='replace')
        article = Article(); article.feed(html)
        article.dates.extend(re.findall(r'"datePublished"\s*:\s*"([^"]+)"', html))
        claimed = _parse_date(story.get('published_at'))
        dates = [_parse_date(value) for value in article.dates]
        if not claimed or not any(value and abs((value - claimed).total_seconds()) < 86400 for value in dates): return False
        text = _text(' '.join(article.text)).casefold()
        evidence = _text(story.get('evidence_quote')).casefold()
        if len(evidence.split()) < 6 or evidence not in text: return False
        headline_tokens = _tokens(story.get('headline'))
        return len(headline_tokens & _tokens(text)) >= min(3, len(headline_tokens))
    except (OSError, ValueError):
        return False
