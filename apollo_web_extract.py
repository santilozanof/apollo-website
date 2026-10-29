"""Public-page extraction using Trafilatura, with pinned public DNS destinations.

No cookies, account credentials, proxy environment, or JavaScript execution.
Redirects are independently validated. Blocked/unsupported pages remain errors.
"""
import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin

MAX_BYTES = 2 * 1024 * 1024


def collection_links(raw, url):
    """Follow real on-page collection links to check whether an article is stale."""
    found = set()
    class Links(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag != 'a':
                return
            href = dict(attrs).get('href', '')
            target = urljoin(url, href)
            parsed = urlsplit(target)
            if (parsed.scheme in {'http', 'https'} and parsed.netloc == urlsplit(url).netloc
                    and not parsed.query and not parsed.fragment
                    and parsed.path.rstrip('/').rsplit('/', 1)[-1].lower() in
                    {'downloads', 'releases', 'news', 'blog', 'versions', 'changelog'}):
                found.add(target)
    Links().feed(raw.decode('utf-8', errors='replace') if isinstance(raw, bytes) else raw)
    return sorted(found, key=lambda value: (urlsplit(value).path.count('/'), value))[:4]


def destination(url):
    parsed = urlsplit(url)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
            or parsed.username or parsed.password
            or parsed.port not in (None, 80 if parsed.scheme == 'http' else 443)):
        raise ValueError('unsupported_url')
    host = parsed.hostname.encode('idna').decode('ascii')
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('non_public_destination')
    address = next((a[4][0] for a in addresses if a[0] == socket.AF_INET), addresses[0][4][0])
    return parsed, host, port, address


def extract_page(url):
    import urllib3
    import trafilatura
    original, current = url, url
    try:
        for _ in range(4):
            parsed, host, port, address = destination(current)
            options = {'timeout': urllib3.Timeout(connect=5, read=10), 'retries': False}
            if parsed.scheme == 'https':
                pool = urllib3.HTTPSConnectionPool(address, port, assert_hostname=host,
                    server_hostname=host, cert_reqs='CERT_REQUIRED', **options)
            else:
                pool = urllib3.HTTPConnectionPool(address, port, **options)
            try:
                response = pool.request('GET', (parsed.path or '/') + ('?' + parsed.query if parsed.query else ''),
                    headers={'Host': host, 'User-Agent': 'ApolloResearch/1.0', 'Accept': 'text/html,text/plain',
                             'Accept-Encoding': 'identity'}, redirect=False, preload_content=False)
                try:
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.headers.get('Location')
                        if not location:
                            raise ValueError('redirect_without_location')
                        current = urljoin(current, location)
                        continue
                    if response.status != 200:
                        raise ValueError('http_' + str(response.status))
                    media = response.headers.get('Content-Type', '').split(';', 1)[0].lower()
                    if media not in {'text/html', 'application/xhtml+xml', 'text/plain'}:
                        raise ValueError('unsupported_content_type')
                    raw = response.read(MAX_BYTES + 1)
                    if len(raw) > MAX_BYTES:
                        raise ValueError('page_too_large')
                finally:
                    response.close()
            finally:
                pool.close()
            content = (raw.decode('utf-8', errors='replace') if media == 'text/plain' else
                trafilatura.extract(raw, url=current, include_comments=False, include_tables=True))
            if not content or len(content.strip()) < 120:
                raise ValueError('insufficient_page_text')
            return {'url': original, 'resolved_url': current, 'content': content[:18000],
                    'backend': 'trafilatura', 'truncated': len(content) > 18000,
                    'index_links': collection_links(raw, current) if media != 'text/plain' else []}
        raise ValueError('too_many_redirects')
    except Exception as exc:
        # No exception text: network libraries may include URL query credentials.
        return {'url': original, 'error': str(exc) if isinstance(exc, ValueError) and
                str(exc).replace('_', '').isalnum() else type(exc).__name__, 'backend': 'trafilatura'}
