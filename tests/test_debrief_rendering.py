import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DebriefRenderingTests(unittest.TestCase):
    def test_original_visual_contract_is_the_only_render_target(self):
        source = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="section-label home-section-title">\n                    Today', source)
        self.assertIn('class="debrief-title">\n                        Your personal debrief', source)
        self.assertIn('items.className = "apollo-debrief-items";', source)
        self.assertIn('row.className = "apollo-debrief-item";', source)
        self.assertIn('category.className = "apollo-debrief-category";', source)
        self.assertIn('contentWrap.className = "apollo-debrief-item-content";', source)
        self.assertIn('headline.className = "apollo-debrief-headline";', source)
        self.assertIn('body.className = "apollo-debrief-body";', source)
        self.assertNotIn(".apollo-debrief-editorial {", source)
        self.assertNotIn('className = "apollo-debrief-editorial', source)

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

    def test_saved_football_and_fifa_stories_are_filtered_before_rendering(self):
        source = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("function apolloDebriefStoryIsExcluded(item)", source)
        self.assertIn("football|soccer|fifa|uefa|world cup", source)
        self.assertIn("const news = stories.filter(item => !apolloDebriefStoryIsExcluded(item))", source)
        self.assertIn("apolloRenderOriginalDebrief(element, visibleStories);", source)

    def test_failed_news_is_not_saved_as_a_complete_debrief(self):
        source = (ROOT / "generate_debrief.py").read_text(encoding="utf-8")
        self.assertIn("existing.get('news_status') == 'ready'", source)
        self.assertIn("status = 'ready' if stories else 'unavailable'", source)
        self.assertIn("personal, health = collect_personal(now)", source)
        self.assertIn("attempts.get('count', 0) >= 3", source)


if __name__ == "__main__":
    unittest.main()
