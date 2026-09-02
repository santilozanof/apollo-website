#!/usr/bin/env python3
"""Serve the current Apollo checkout for reliable, cache-free UI review."""

from __future__ import annotations

import argparse
import json
import subprocess
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def git_value(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True
    ).strip()


class PreviewHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
    }

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("X-Apollo-Preview-Commit", self.server.commit)  # type: ignore[attr-defined]
        super().end_headers()

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == "/__preview_meta__":
            payload = json.dumps(
                {
                    "branch": self.server.branch,  # type: ignore[attr-defined]
                    "commit": self.server.commit,  # type: ignore[attr-defined]
                    "root": str(ROOT),
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        super().do_GET()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    branch = git_value("branch", "--show-current")
    if branch != "dev":
        raise SystemExit(f"Preview refused: expected dev, found {branch!r}")

    commit = git_value("rev-parse", "HEAD")
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        lambda *handler_args, **handler_kwargs: PreviewHandler(
            *handler_args, directory=str(ROOT), **handler_kwargs
        ),
    )
    server.branch = branch
    server.commit = commit
    print(
        f"Apollo preview: http://127.0.0.1:{args.port}/?preview={commit[:12]} "
        f"({branch}@{commit[:12]})",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
