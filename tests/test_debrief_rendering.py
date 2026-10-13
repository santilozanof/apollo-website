import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DebriefRenderingTests(unittest.TestCase):
    def test_structured_content_parser_accepts_object_string_and_double_encoded_json(self):
        if not shutil.which("node"):
            self.skipTest("Node.js is unavailable")
        source = (ROOT / "index.html").read_text(encoding="utf-8")
        start = source.index("// APOLLO_DEBRIEF_CONTENT_PARSER_START")
        end = source.index("// APOLLO_DEBRIEF_CONTENT_PARSER_END")
        parser = source[start:end]
        payload = {"stories": [{"headline": "Music"}]}
        legacy = {"summary": "Legacy", "items": [{"headline": "Older story"}]}
        script = parser + "\n" + f"""
const value = {json.dumps(payload)};
const legacy = {json.dumps(legacy)};
const results = [value, JSON.stringify(value), JSON.stringify(JSON.stringify(value)), JSON.stringify(legacy)]
  .map(apolloParseDebriefContent);
console.log(JSON.stringify(results));
"""
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), [payload, payload, payload, legacy])

    def test_failed_news_is_not_saved_as_a_complete_debrief(self):
        source = (ROOT / "generate_debrief.py").read_text(encoding="utf-8")
        self.assertIn('existing_content.get("news_status") != "unavailable"', source)
        self.assertNotIn('"news_status": "unavailable"', source)
        self.assertIn("if len(stories) < 4:", source)
        self.assertNotIn("get_personal_today", source)


if __name__ == "__main__":
    unittest.main()
