"""Small, allowlisted media resolver for explicit visual chat requests.

Only official Image-Line screenshots and Wikimedia Commons thumbnails are
requested. User text is never interpreted as a URL to fetch.
"""

from concurrent.futures import ThreadPoolExecutor
from html import unescape
from html.parser import HTMLParser
import json
import re
import urllib.parse
import urllib.request


IMAGE_LINE_ROOT = (
    "https://www.image-line.com/fl-studio-learning-content/"
    "fl-studio-online-manual/html/"
)
FL_IMAGES = (
    ("FL Studio workspace", "basics_interface.png", "main_windows.htm"),
    ("Channel Rack", "channelrack_main.png", "channelrack.htm"),
    ("Playlist", "playlist_main.png", "playlist.htm"),
    ("Piano Roll", "pianoroll_general.png", "pianoroll.htm"),
    ("Mixer", "mixer_main.png", "mixer.htm"),
    ("Browser", "browser.png", "browser.htm"),
)
ALLOWED_IMAGE_HOSTS = {"www.image-line.com", "thumb.wikimedia.org"}
ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def _plain(value):
    parser = _PlainText()
    parser.feed(str(value or ""))
    return re.sub(r"\s+", " ", unescape(" ".join(parser.parts))).strip()[:120]


def _ordinal_subject(text, history):
    match = re.search(r"\bshow me (?:the )?(first|second|third|1st|2nd|3rd) one\b", text, re.I)
    if not match:
        return None
    position = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3}[match.group(1).lower()]
    for item in reversed(history[-8:]):
        if not isinstance(item, dict) or item.get("role") != "assistant":
            continue
        content = str(item.get("content") or "")
        numbered = re.findall(r"(?m)^\s*([123])[.)]\s+\*{0,2}([^\n|]{3,80})", content)
        candidates = {int(number): re.sub(r"\*.*$", "", name).strip(" .:-") for number, name in numbered}
        if all(candidates.get(number) for number in range(1, position + 1)):
            return candidates[position][:80]
    return None


def visual_request(message, history=()):
    """Return a bounded subject for an explicit visual request, or None."""
    text = re.sub(r"\s+", " ", str(message or "")).strip()
    lower = text.lower()
    ordinal_subject = _ordinal_subject(str(message or ""), history)
    if ordinal_subject:
        return ordinal_subject
    if not re.search(
        r"\b(?:show|find|see|give|display)\b.{0,55}\b(?:images?|photos?|pictures?|screenshots?)\b"
        r"|\b(?:images?|photos?|pictures?|screenshots?)\s+of\b"
        r"|\bwhat\b.{0,45}\blooks? like\b"
        r"|\bshow me\b.{0,35}\b(?:piano roll|fl studio)\b",
        lower,
    ):
        return None
    recent = " ".join(
        str(item.get("content") or "")[:500]
        for item in history[-8:]
        if isinstance(item, dict) and item.get("role") in ("user", "assistant")
    ).lower()
    if "fl studio" in lower or ("fl studio" in recent and re.search(r"\b(it|this|that|piano roll|what it looks like)\b", lower)):
        return "fl-studio-piano-roll" if "piano roll" in lower else "fl-studio"
    if "piano roll" in lower or ("piano roll" in recent and re.search(r"\b(it|this|that)\b", lower)):
        return "fl-studio-piano-roll"
    if "espresso" in lower:
        return "vintage espresso machine" if "vintage" in lower else "espresso machine"
    if "espresso" in recent and re.search(r"\b(it|this|that)\b", lower):
        return "vintage espresso machine" if "vintage" in recent else "espresso machine"
    match = re.search(r"\b(?:of|for)\s+(.{3,100}?)(?:[?.!]|$)", text, re.I)
    if match:
        subject = re.sub(r"[^\w\s'-]", "", match.group(1)).strip()
        return subject[:80] or None
    return None


def _valid_image(url, timeout=5):
    parsed = urllib.parse.urlparse(str(url))
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_IMAGE_HOSTS:
        return False
    if any(key in parsed.query.lower() for key in ("token=", "apikey=", "api_key=", "signature=")):
        return False
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "ApolloMedia/2.4"})
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            final = urllib.parse.urlparse(response.geturl())
            mime = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
            length = int(response.headers.get("Content-Length") or 0)
            return (
                response.status == 200
                and final.scheme == "https"
                and final.hostname in ALLOWED_IMAGE_HOSTS
                and mime in ALLOWED_MIME
                and 0 <= length <= 8_000_000
            )
    except (OSError, ValueError):
        return False


def _official_fl_images(subject):
    wanted = FL_IMAGES[3:4] if subject == "fl-studio-piano-roll" else FL_IMAGES[:4]
    candidates = [
        {
            "url": IMAGE_LINE_ROOT + "img_shot/" + filename,
            "alt": "Official FL Studio " + title + " screenshot",
            "caption": title + " · Image-Line official manual",
            "source_url": IMAGE_LINE_ROOT + page,
            "source_title": "FL Studio manual: " + title,
            "publisher": "Image-Line",
        }
        for title, filename, page in wanted
    ]
    with ThreadPoolExecutor(max_workers=4) as pool:
        valid = list(pool.map(lambda item: _valid_image(item["url"]), candidates))
    return [item for item, passed in zip(candidates, valid) if passed]


def _commons_images(subject):
    query = urllib.parse.urlencode({
        "action": "query", "generator": "search", "gsrsearch": subject,
        "gsrnamespace": 6, "gsrlimit": 12, "prop": "imageinfo",
        "iiprop": "url|mime|extmetadata", "iiurlwidth": 640, "format": "json",
    })
    request = urllib.request.Request(
        "https://commons.wikimedia.org/w/api.php?" + query,
        headers={"User-Agent": "ApolloMedia/2.4 (private assistant)"},
    )
    try:
        with _OPENER.open(request, timeout=7) as response:
            if response.status != 200 or response.geturl() != request.full_url:
                return []
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            return []
        pages = json.loads(raw).get("query", {}).get("pages", {}).values()
    except (OSError, ValueError, AttributeError):
        return []
    candidates = []
    for page in sorted(pages, key=lambda item: item.get("index", 999)):
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("thumburl")
        mime = info.get("mime")
        title = str(page.get("title") or "").removeprefix("File:")
        if mime not in ALLOWED_MIME or not url or not title:
            continue
        if "vintage" in subject and "vintage" not in title.lower():
            continue
        metadata = info.get("extmetadata") or {}
        artist = _plain((metadata.get("Artist") or {}).get("value"))
        license_name = _plain((metadata.get("LicenseShortName") or {}).get("value"))
        source_url = info.get("descriptionurl") or (
            "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(page["title"].replace(" ", "_"))
        )
        candidates.append({
            "url": url, "alt": title.rsplit(".", 1)[0].replace("_", " "),
            "caption": " · ".join(piece for piece in (artist or "Wikimedia Commons", license_name) if piece),
            "source_url": source_url, "source_title": title,
            "publisher": "Wikimedia Commons",
        })
        if len(candidates) == 6:
            break
    with ThreadPoolExecutor(max_workers=4) as pool:
        valid = list(pool.map(lambda item: _valid_image(item["url"]), candidates))
    return [item for item, passed in zip(candidates, valid) if passed][:4]


def visual_response(subject):
    if subject.startswith("fl-studio"):
        images = _official_fl_images(subject)
        label = "FL Studio’s Piano Roll" if subject.endswith("piano-roll") else "FL Studio"
        fallback = IMAGE_LINE_ROOT + ("pianoroll.htm" if subject.endswith("piano-roll") else "main_windows.htm")
        publisher = "Image-Line’s official manual"
    else:
        images = _commons_images(subject)
        label = subject
        fallback = "https://commons.wikimedia.org/wiki/Special:MediaSearch?" + urllib.parse.urlencode({"type": "image", "search": subject})
        publisher = "Wikimedia Commons"
    if not images:
        return (
            f"I couldn’t verify loadable images of {label} right now. "
            f"You can browse [{publisher}]({fallback}) directly."
        )
    gallery = {
        "blocks": [
            {"type": "image_gallery", "id": "verified-images", "items": [
                {key: item[key] for key in ("url", "alt", "caption")} for item in images
            ]},
            {"type": "sources", "id": "image-sources", "title": "Image sources", "items": [
                {"url": item["source_url"], "title": item["source_title"], "publisher": item["publisher"]}
                for item in images
            ]},
        ]
    }
    return f"I found these direct image assets of {label}.\n\n```apollo-ui\n{json.dumps(gallery, ensure_ascii=False)}\n```"
