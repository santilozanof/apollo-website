"""Local Music UI fixture. Uses real Apollo SQLite and HTTP routes, no accounts."""
import json
import mimetypes
import os
from pathlib import Path
import sys
import tempfile
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix="apollo-music-fixture-")
os.environ["APOLLO_BASE_DIR"] = TEMP.name
import server
import music_history

server.init_db()
server.app_state_set("time_zone", "Europe/Zurich")
conn = server.db()
events = [
    {"ts": f"2026-09-{day:02d}T20:00:00Z", "ms_played": 180000,
     "master_metadata_track_name": title, "master_metadata_album_artist_name": artist,
     "master_metadata_album_album_name": album, "spotify_track_uri": None}
    for day, title, artist, album in [
        (2, "Afterglow", "Lowlight", "Open Window"),
        (5, "Surface", "Lowlight", "Open Window"),
        (8, "Signal", "Night Transit", "Fragments"),
        (12, "Afterglow", "Lowlight", "Open Window"),
        (18, "Drift", "Midnight Field", "Drift"),
    ]
]
music_history.insert_records(conn, events)
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
        if path == "/api/spotify/queue":
            server.json_response(self, {"items": []})
            return
        if path == "/api/connections":
            server.json_response(self, {"integrations": []})
            return
        if path in ("/api/music/insights", "/api/music/analytics", "/api/music/rankings",
                    "/api/music/history", "/api/music/detail", "/api/music/imports", "/api/music/recaps"):
            super().do_GET()
            return
        if path.startswith("/api/"):
            server.json_response(self, {})
            return
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
    httpd = ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("APOLLO_TEST_PORT", "8877"))), Handler)
    print(f"Music fixture ready at http://127.0.0.1:{httpd.server_address[1]}", flush=True)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
        TEMP.cleanup()
