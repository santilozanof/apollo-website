"""Read-only, provider-backed metadata for contextual Chat entity panels."""

import json
import re
import urllib.parse
import urllib.request
from apollo_media import _valid_image


MUSIC_KINDS = {"artist", "album", "song"}
PUBLIC_KINDS = {"book", "movie", "person", "place"}
KINDS = MUSIC_KINDS | PUBLIC_KINDS
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _normal(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _music_title_matches(requested, actual):
    if _normal(requested) == _normal(actual):
        return True
    base = re.sub(
        r"\s*[\(\[](?:(?:original|deluxe|expanded|special|anniversary|remastered)"
        r"(?:\s+(?:edition|version|release|\d{4}))?)[\)\]]\s*$",
        "", str(actual or ""), flags=re.I,
    )
    return base != str(actual or "") and _normal(requested) == _normal(base)


def _safe_image(value):
    parsed = urllib.parse.urlparse(str(value or ""))
    return (parsed.scheme == "https" and parsed.hostname in {
        "upload.wikimedia.org", "thumb.wikimedia.org", "i.scdn.co"
    } and not parsed.username and not parsed.password and not parsed.query)


def _public_entity(kind, name, fetch=None):
    query = urllib.parse.urlencode({
        "action": "query", "generator": "search", "gsrsearch": name,
        "gsrlimit": 5, "prop": "extracts|pageimages|info", "exintro": 1,
        "explaintext": 1, "exsentences": 3, "pithumbsize": 640,
        "inprop": "url", "format": "json", "formatversion": 2,
    })
    url = WIKIPEDIA_API + "?" + query
    if fetch is None:
        request = urllib.request.Request(url, headers={"User-Agent": "ApolloEntity/3.0 (private assistant)"})
        with _OPENER.open(request, timeout=6) as response:
            if response.status != 200 or response.geturl() != url:
                return None
            body = response.read(1_000_001)
            if len(body) > 1_000_000:
                return None
            data = json.loads(body)
    else:
        data = fetch(url)
    pages = data.get("query", {}).get("pages", []) if isinstance(data, dict) else []
    if not isinstance(pages, list):
        return None
    wanted = _normal(name)
    page = next((item for item in pages if _normal(item.get("title")) == wanted), None)
    if not page:
        return None
    page_url = page.get("fullurl")
    parsed = urllib.parse.urlparse(str(page_url or ""))
    if parsed.scheme != "https" or parsed.hostname != "en.wikipedia.org":
        return None
    thumbnail = (page.get("thumbnail") or {}).get("source")
    return {
        "kind": kind, "name": str(page.get("title") or name)[:160],
        "provider": "Wikipedia", "provider_id": str(page.get("pageid") or ""),
        "description": str(page.get("extract") or "")[:800],
        "image_url": thumbnail if _safe_image(thumbnail) else None,
        "source_url": page_url, "source_title": str(page.get("title") or name)[:160],
    }


def resolve(kind, name, artist=None, spotify_lookup=None, public_fetch=None,
            image_check=None):
    """Resolve a bounded exact-name reference; never trust model metadata."""
    kind = str(kind or "").strip().lower()
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    if kind not in KINDS or not 2 <= len(name) <= 120 or any(c in name for c in "<>\r\n"):
        raise ValueError("Unsupported entity reference")
    if kind in MUSIC_KINDS:
        if spotify_lookup is None:
            return None
        result = spotify_lookup(kind, name, artist)
        if not isinstance(result, dict) or not _music_title_matches(name, result.get("name")):
            return None
        entity = result
    else:
        try:
            entity = _public_entity(kind, name, public_fetch)
        except (OSError, ValueError, KeyError, TypeError):
            return None
    if entity and entity.get("image_url"):
        image_url = entity["image_url"]
        if not _safe_image(image_url) or not (image_check or _valid_image)(image_url):
            entity = {**entity, "image_url": None}
    return entity
