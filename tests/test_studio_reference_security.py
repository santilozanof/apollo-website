import ast
import unittest
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]


def load_function(name, namespace):
    tree = ast.parse((ROOT / "studio_backend.py").read_text())
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(ROOT / "studio_backend.py"), "exec"), namespace)
    return namespace[name]


class StudioReferenceSecurityTests(unittest.TestCase):
    def test_web_reference_rejects_script_file_and_embedded_credentials(self):
        namespace = {"_clean": lambda value: str(value or "").strip(), "urlsplit": urlsplit}
        safe = load_function("_safe_reference_url", namespace)
        self.assertEqual(safe("https://example.com/inspiration"), "https://example.com/inspiration")
        for value in ("javascript:alert(1)", "file:///Users/me/song.flp", "data:text/html,x",
                      "https://user:password@example.com", "//example.com/reference"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                safe(value)

    def test_fl_studio_project_is_distinct_from_generic_media(self):
        namespace = {"Path": Path, "_clean": lambda value: str(value or "").strip()}
        media_type = load_function("_media_type", namespace)
        self.assertEqual(media_type("application/octet-stream", "Song.FLP"), "fl_studio_project")
        self.assertEqual(media_type("audio/wav", "mix.wav"), "audio")


if __name__ == "__main__":
    unittest.main()
