import ast
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server.py"


def load_server_items(*names):
    tree = ast.parse(SERVER.read_text())
    wanted = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.Assign)):
            defined = {node.name} if isinstance(node, ast.FunctionDef) else {
                target.id for target in node.targets if isinstance(target, ast.Name)
            }
            if defined & set(names):
                wanted.append(node)
    namespace = {"json": json}
    exec(compile(ast.Module(body=wanted, type_ignores=[]), str(SERVER), "exec"), namespace)
    return namespace


def blocks(value):
    match = re.search(r"```apollo-ui\n([\s\S]+?)\n```", value)
    assert match
    return json.loads(match.group(1))["blocks"]


class GenerativeUITests(unittest.TestCase):
    def setUp(self):
        self.items = load_server_items(
            "APOLLO_GENERATIVE_UI_PROMPT", "apollo_routine_genui"
        )

    def test_routine_ui_uses_authoritative_ids_and_state(self):
        value = self.items["apollo_routine_genui"]({
            "local_date": "2026-10-14",
            "routines": [{
                "id": 9, "title": "Morning", "status": "incomplete",
                "completed_steps": 1, "required_steps": 2,
                "steps": [
                    {"id": 31, "title": "Water", "complete": True},
                    {"id": 32, "title": "Stretch", "complete": False},
                ],
            }],
        })
        block = blocks(value)[0]
        self.assertEqual(block["type"], "checklist")
        self.assertTrue(block["persisted"])
        self.assertTrue(block["items"][0]["completed"])
        self.assertEqual(block["items"][1]["action"]["payload"], {
            "action": "set_step", "routine_id": 9,
            "step_id": 32, "date": "2026-10-14",
        })

    def test_routine_ui_omits_unscheduled_routines(self):
        value = self.items["apollo_routine_genui"]({
            "local_date": "2026-10-14",
            "routines": [{"id": 1, "status": "not_scheduled", "steps": [{"id": 2}]}],
        })
        self.assertEqual(value, "")

    def test_client_has_allowlists_and_no_dynamic_execution(self):
        source = (ROOT / "apollo_genui.js").read_text()
        self.assertIn("const TYPES = new Set", source)
        self.assertIn("const ACTIONS = new Set", source)
        self.assertNotIn("eval(", source)
        self.assertNotIn("new Function", source)
        self.assertNotIn(".innerHTML", source)
        self.assertIn('credentials:"same-origin"', source)
        self.assertIn("reconcileChecklist", source)

    def test_index_masks_partial_structured_streams(self):
        source = (ROOT / "index.html").read_text()
        self.assertIn('href="/apollo_genui.css"', source)
        self.assertIn('src="/apollo_genui.js"', source)
        self.assertEqual(source.count("? window.apolloGenUIStreamingText("), 2)

    def test_prompt_requires_real_data_and_simple_fallback(self):
        prompt = self.items["APOLLO_GENERATIVE_UI_PROMPT"]
        self.assertIn("Simple questions must stay simple text", prompt)
        self.assertIn("Never invent data", prompt)
        self.assertIn("```apollo-ui", prompt)


if __name__ == "__main__":
    unittest.main()
