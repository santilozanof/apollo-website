"""Isolated local fixture: real SQLite/HTTP handlers; no external accounts or model calls."""
import io
import json
import mimetypes
import os
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlparse, parse_qs
from http.server import ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix='apollo-browser-')
os.environ['APOLLO_BASE_DIR'] = TEMP.name
import server
import debrief_context
from PIL import Image

server.init_db()
server.app_state_set('time_zone', 'Europe/Zurich')
health_status = 'reconnection_required'
def probe():
    return {'integrations': [
        {'id': 'google_calendar', 'name': 'Google Calendar', 'status': health_status, 'connected': health_status == 'connected',
         'description': 'Calendar syncing', 'actions': [{'id': 'reconnect', 'method': 'GET', 'url': '/api/google/connect', 'label': 'Reconnect'}]},
        {'id': 'canvas_calendar', 'name': 'Canvas Calendar', 'status': 'not_configured', 'connected': False, 'description': 'Assignments', 'actions': []},
        {'id': 'spotify', 'name': 'Spotify', 'status': 'not_configured', 'connected': False, 'description': 'Music', 'actions': []},
        {'id': 'whoop', 'name': 'WHOOP', 'status': 'not_configured', 'connected': False, 'description': 'Recovery', 'actions': []},
    ]}
server._apollo_connections_probe = probe
server.apollo_connections_registry(force=True, wait=True)
server.get_now_playing = lambda **kwargs: {'playing': False, 'connection_state': 'connected', 'playback_state': 'idle'}
server.apollo_calendar_events = lambda *args, **kwargs: ([], {})
server.ask_hermes = lambda *args, **kwargs: 'Attached photographs show a blue test rectangle.'
server.stream_hermes = lambda *args, **kwargs: iter(['Here is the supported image.\n\n![Saved test image](/fixture-image.png)'])
server.generate_chat_title = lambda *args: 'Image persistence test'
server.apollo_extract_attachment_context = lambda attachments: 'The image is a blue rectangle.'
now = datetime.now(ZoneInfo('Europe/Zurich'))
conn = server.db()
conn.execute("INSERT INTO chats(title) VALUES ('Image persistence test')")
conn.execute("INSERT INTO chats(title) VALUES ('Second conversation')")
news = {'id': 'fixture-news', 'category': 'Science', 'topics': ['science'], 'headline': 'Verified science fixture',
        'body': 'A research team reports a measurable advance. Independent replication will determine its broader use.',
        'details': 'Extra context appears only after expanding this story.', 'why_care': 'The result informs future technology development.',
        'source': 'Fixture source', 'url': 'https://example.com/verified-science', 'published_at': now.isoformat()}
brief = {'version': 2, 'as_of': now.isoformat(), 'news_status': 'ready', 'my_day': [
    {'category': 'My day', 'headline': 'Class and an upcoming deadline', 'body': '10:00 · Physics. Essay due today.', 'source': 'Fixture calendar and tasks'}],
    'stories': [news], 'personal_intelligence': [{'category': 'Personal intelligence', 'headline': 'Prepare for your class', 'body': 'Review your saved class notes.', 'source': 'Fixture data'}],
    'availability': [{'source': 'Calendar', 'message': 'Google Calendar needs reconnection.', 'action': 'connections'}]}
conn.execute('INSERT INTO daily_debriefs(local_date,timezone,content) VALUES (?,?,?)', (now.date().isoformat(), 'Europe/Zurich', json.dumps(brief)))
conn.commit(); conn.close()
image_data = io.BytesIO(); Image.new('RGB', (640, 320), '#526c9f').save(image_data, 'PNG')

class Handler(server.ApolloHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        global health_status
        path = urlparse(self.path).path
        if path == '/__test/health':
            health_status = parse_qs(urlparse(self.path).query)['status'][0]
            server.CONNECTION_HEALTH.at = 0
            server.json_response(self, server.apollo_connections_registry(force=True, wait=True)); return
        if path == '/api/google/connect':
            health_status = 'connected'; server.CONNECTION_HEALTH.at = 0
            server.apollo_connections_registry(force=True, wait=True)
            self.send_response(302); self.send_header('Location', '/'); self.end_headers(); return
        if path == '/fixture-image.png':
            data = image_data.getvalue(); self.send_response(200); self.send_header('Content-Type', 'image/png'); self.end_headers(); self.wfile.write(data); return
        if path == '/api/whoop/summary':
            server.json_response(self, {'error': 'Not configured'}, 503); return
        if path == '/api/notifications':
            server.json_response(self, {'notifications': []}); return
        if path == '/api/notifications/status':
            server.json_response(self, {'preferences': {}, 'push_configured': False, 'subscription_count': 0}); return
        if path.startswith('/api/spotify/'):
            server.json_response(self, {'items': [], 'tracks': []}); return
        if path.startswith('/api/'):
            return super().do_GET()
        file = (ROOT / ('index.html' if path == '/' else path.lstrip('/'))).resolve()
        if not file.is_relative_to(ROOT) or not file.is_file(): self.send_error(404); return
        self.send_response(200); self.send_header('Content-Type', mimetypes.guess_type(file)[0] or 'application/octet-stream'); self.end_headers(); self.wfile.write(file.read_bytes())

if __name__ == '__main__':
    httpd = ThreadingHTTPServer(('127.0.0.1', int(os.environ.get('APOLLO_TEST_PORT', '8876'))), Handler)
    print('Fixture ready at http://127.0.0.1:8876', flush=True)
    try: httpd.serve_forever()
    finally: httpd.server_close(); TEMP.cleanup()
