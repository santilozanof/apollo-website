import ast
import unittest
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1] / "server.py"


def load_function(name, namespace):
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    node = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == name
    )
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SERVER), "exec"), namespace)
    return namespace[name]


class ConnectionRegistryTests(unittest.TestCase):
    def registry(self, *, google=None, canvas=None, spotify=None, whoop=None):
        return load_function("apollo_connections_registry", {
            "google_calendar_connection_status": lambda: google or {
                "connected": True, "reconnect": False, "error": None,
            },
            "calendar_subscription_status": lambda _provider: canvas or {
                "connected": True, "last_synced_at": "2026-10-14T12:00:00Z",
                "last_error": None,
            },
            "get_now_playing": lambda: spotify or {
                "connection_state": "connected", "device": None,
            },
            "whoop_connection_status": lambda: whoop or {
                "status": "connected", "connected": True,
                "last_successful_sync": "2026-10-14T11:00:00Z", "error": None,
            },
        })()

    def test_registry_contains_only_real_user_integrations(self):
        integrations = self.registry()["integrations"]
        self.assertEqual(
            [item["id"] for item in integrations],
            ["google_calendar", "canvas_calendar", "spotify", "whoop"],
        )
        self.assertTrue(all("description" in item for item in integrations))
        self.assertNotIn("credentials", str(integrations).lower())
        self.assertNotIn("token", str(integrations).lower())

    def test_spotify_connection_is_distinct_from_device_availability(self):
        spotify = next(
            item for item in self.registry(spotify={
                "connection_state": "connected", "device": None,
            })["integrations"] if item["id"] == "spotify"
        )
        self.assertEqual(spotify["status"], "connected")
        self.assertTrue(spotify["connected"])
        self.assertFalse(spotify["device_available"])

    def test_registry_exposes_only_supported_management_actions(self):
        integrations = {
            item["id"]: item for item in self.registry(
                google={"connected": False, "reconnect": True, "error": "expired"},
                canvas={"connected": True, "last_synced_at": None, "last_error": None},
                whoop={"status": "reconnection_required", "connected": False,
                       "last_successful_sync": None, "error": "expired"},
            )["integrations"]
        }
        self.assertEqual(
            [action["id"] for action in integrations["google_calendar"]["actions"]],
            ["reconnect"],
        )
        self.assertEqual(
            [action["id"] for action in integrations["canvas_calendar"]["actions"]],
            ["refresh", "disconnect"],
        )
        self.assertEqual(integrations["spotify"]["actions"], [])
        self.assertEqual(
            [action["id"] for action in integrations["whoop"]["actions"]],
            ["reconnect"],
        )
        disconnect = integrations["canvas_calendar"]["actions"][1]
        self.assertIn("removes imported Canvas events", disconnect["confirm"])

    def test_settings_renders_registry_and_confirms_disconnects(self):
        source = (SERVER.parent / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="apolloConnectionsPanel"', source)
        self.assertIn('fetch("/api/connections"', source)
        self.assertIn('data-connection-action', source)
        self.assertIn('confirmLabel: "Disconnect"', source)
        self.assertNotIn('id="apolloGoogleStatus"', source)
        self.assertNotIn('id="apolloCanvasStatus"', source)

    def test_connections_endpoint_uses_central_registry(self):
        source = SERVER.read_text(encoding="utf-8")
        route = source.index('if route == "/api/connections"')
        registry = source.index("apollo_connections_registry()", route)
        self.assertGreater(registry, route)


if __name__ == "__main__":
    unittest.main()
