"""Isolated full Chat ranking fixture. All account and artwork data is synthetic."""

import hashlib
import mimetypes
import os
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix="apollo-media-ranking-fixture-")
os.environ["APOLLO_BASE_DIR"] = TEMP.name
os.environ["APOLLO_SECURITY_ORIGIN"] = "http://localhost:8910"
import server
import music_history

server.init_db()
conn = server.db()
today = datetime.now(timezone.utc).date()
days = [(today.replace(day=1) + timedelta(days=index)) for index in range(5)]
records = []
for index, day in enumerate(days):
    records.append({"played_at": f"{day.isoformat()}T12:00:00Z", "track": {
        "id": chr(65 + index) * 22, "name": f"Fixture Track {index + 1}", "duration_ms": 180000,
        "artists": [{"id": "Z" * 22, "name": "Fixture Artist"}],
        "album": {"id": chr(70 + index) * 22, "name": f"Fixture Album {index + 1}",
                  "images": [{"url": f"https://i.scdn.co/image/apolloFixture{index}"}]},
    }})
music_history.insert_records(conn, records)
for index in range(5):
    conn.execute("UPDATE music_listens SET ms_played=? WHERE track_id=?",
                 ((10 - index) * 60000, chr(65 + index) * 22))
conn.commit()
conn.close()


class Handler(server.ApolloHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/now-playing":
            server.json_response(self, {"playing": False, "connection_state": "not_configured"})
            return
        if path == "/api/connections":
            server.json_response(self, {"integrations": []})
            return
        if path.startswith("/api/"):
            return super().do_GET()
        file = (ROOT / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
        if not file.is_relative_to(ROOT) or not file.is_file():
            self.send_error(404)
            return
        body = file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(file)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    httpd = ThreadingHTTPServer(("127.0.0.1", 8910), Handler)
    print("Media ranking fixture ready on 8910", flush=True)
    httpd.serve_forever()
