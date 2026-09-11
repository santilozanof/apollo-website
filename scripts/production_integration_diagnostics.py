#!/usr/bin/env python3
"""Read-only, redacted production diagnostics for Apollo integrations.

Run on the production host only. It never prints or writes OAuth tokens,
client secrets, authorization headers, or raw credential files. The Spotify
probe uses the helper's in-memory token solely for same-process read requests.
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


BASE_DIR = Path("/root/Apollo")
DB_PATH = BASE_DIR / "apollo.db"
SPOTIFY_PYTHON = "/usr/local/lib/hermes-agent/venv/bin/python"
SPOTIFY_TOOL = "/root/spotify_tool.py"


SPOTIFY_HOOK = r'''
import atexit, json, os, urllib.error, urllib.request

trace_path = os.environ["APOLLO_SPOTIFY_DIAGNOSTIC_TRACE"]
original_load = json.load
original_loads = json.loads
latest_access_token = None
metadata = {"access_token_present": False, "refresh_token_present": False,
            "expiry": None, "granted_scopes": []}
responses = {}

def observe(value):
    global latest_access_token
    if isinstance(value, dict) and value.get("access_token"):
        latest_access_token = str(value["access_token"])
        metadata["access_token_present"] = True
        metadata["refresh_token_present"] = bool(value.get("refresh_token"))
        metadata["expiry"] = value.get("expires_at") or value.get("expires") or value.get("expiry")
        scope = value.get("scope") or value.get("scopes") or []
        metadata["granted_scopes"] = sorted(scope.split()) if isinstance(scope, str) else sorted(scope)
    return value

def watched_load(*args, **kwargs):
    return observe(original_load(*args, **kwargs))

def watched_loads(*args, **kwargs):
    return observe(original_loads(*args, **kwargs))

json.load = watched_load
json.loads = watched_loads

def summarize_item(item):
    if not isinstance(item, dict):
        return None
    artists = item.get("artists") or []
    return {"type": item.get("type"), "title": item.get("name"),
            "artists": [artist.get("name") for artist in artists if isinstance(artist, dict)]}

def request(path):
    if not latest_access_token:
        return {"error": "No access token observed in Spotify helper"}
    req = urllib.request.Request("https://api.spotify.com/v1" + path,
        headers={"Authorization": "Bearer " + latest_access_token})
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            status = getattr(response, "status", None) or response.getcode()
            raw = response.read().decode("utf-8", errors="replace")
            data = original_loads(raw) if raw else {}
            result = {"status": status}
            if path == "/me":
                result["account"] = {"id": data.get("id"), "display_name": data.get("display_name")}
            elif path == "/me/player/devices":
                result["devices"] = [{"name": device.get("name"), "type": device.get("type"),
                    "is_active": device.get("is_active"), "is_private_session": device.get("is_private_session"),
                    "is_restricted": device.get("is_restricted")}
                    for device in data.get("devices", []) if isinstance(device, dict)]
            else:
                result["is_playing"] = data.get("is_playing")
                result["item"] = summarize_item(data.get("item"))
                device = data.get("device") or {}
                result["device"] = {"name": device.get("name"), "type": device.get("type"),
                    "is_active": device.get("is_active")} if isinstance(device, dict) else None
            return result
    except urllib.error.HTTPError as error:
        # Spotify error bodies are not needed for this audit and can contain
        # implementation details that should not be published in a workflow log.
        return {"status": error.code, "error": "Spotify HTTP error"}
    except Exception as error:
        return {"error": str(error)}

def write_trace():
    responses["me"] = request("/me")
    responses["player"] = request("/me/player")
    responses["currently_playing"] = request("/me/player/currently-playing")
    responses["devices"] = request("/me/player/devices")
    with open(trace_path, "w", encoding="utf-8") as stream:
        json.dump({"token": metadata, "responses": responses}, stream)

atexit.register(write_trace)
'''


def app_state():
    if not DB_PATH.exists():
        return {}, {"error": f"Database not found: {DB_PATH}"}
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT key, value FROM app_state").fetchall()
    finally:
        conn.close()
    return dict(rows), {}


def google_summary(state):
    return {
        "access_token_present": bool(state.get("google_access_token")),
        "refresh_token_present": bool(state.get("google_refresh_token")),
        "access_token_expiry": state.get("google_access_token_expires_at"),
        # Apollo requests this scope in source; Google does not return a scope
        # list on refresh, so it is intentionally labelled requested here.
        "requested_scopes": ["https://www.googleapis.com/auth/calendar"],
        "oauth_state_present": bool(state.get("google_oauth_state")),
        "oauth_state_created_at": state.get("google_oauth_state_created_at"),
        "last_oauth_or_token_update": "not durably recorded in app_state",
        "last_calendar_api_success": "not durably recorded",
        "last_invalid_grant": "see journal matches",
        "last_calendar_401": "see journal matches",
        "refresh_token_deletion_executed": "not durably recorded",
        "refresh_token_deletion_reason": "not durably recorded",
    }


def journal_matches():
    patterns = {
        "invalid_grant": "invalid_grant",
        "refresh_failure": "Google token refresh failed",
        "calendar_401": "Google Calendar authorization was rejected",
        "token_deletion": "google_clear_oauth_tokens",
        "oauth_callback": "calendar=connected",
    }
    try:
        output = subprocess.run(
            ["journalctl", "--no-pager", "-u", "apollo-backend", "-n", "5000"],
            capture_output=True, text=True, timeout=30, check=False,
        ).stdout.splitlines()
    except Exception as error:
        return {name: {"error": str(error)} for name in patterns}
    def redact(line):
        if not line:
            return None
        line = __import__("re").sub(r"(?i)(bearer\s+)[^\s]+", r"\1[REDACTED]", line)
        return __import__("re").sub(r"(?i)(access|refresh|id)_token[=:][^\s,]+", r"\1_token=[REDACTED]", line)
    return {
        name: redact(next((line for line in reversed(output) if needle.casefold() in line.casefold()), None))
        for name, needle in patterns.items()
    }


def spotify_summary():
    if not Path(SPOTIFY_TOOL).exists():
        return {"error": "Spotify helper not found"}
    with tempfile.TemporaryDirectory(prefix="apollo-spotify-diagnostics-") as directory:
        temp = Path(directory)
        trace_path = temp / "trace.json"
        (temp / "sitecustomize.py").write_text(SPOTIFY_HOOK, encoding="utf-8")
        environment = dict(os.environ)
        environment["PYTHONPATH"] = directory + os.pathsep + environment.get("PYTHONPATH", "")
        environment["APOLLO_SPOTIFY_DIAGNOSTIC_TRACE"] = str(trace_path)
        helper = subprocess.run(
            [SPOTIFY_PYTHON, SPOTIFY_TOOL, "current"],
            capture_output=True, text=True, timeout=40, env=environment,
        )
        try:
            report = json.loads(trace_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            report = {"error": "Spotify helper did not write diagnostics"}
    report["helper_exit_code"] = helper.returncode
    return report


def main():
    state, database_error = app_state()
    report = {
        "read_only": True,
        "spotify": spotify_summary(),
        "google": google_summary(state),
        "google_journal": journal_matches(),
    }
    if database_error:
        report["database_error"] = database_error
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
