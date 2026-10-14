import ast
import json
import re
import unittest
import urllib.parse
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
    namespace = {"json": json, "re": re, "urllib": __import__("urllib")}
    exec(compile(ast.Module(body=wanted, type_ignores=[]), str(SERVER), "exec"), namespace)
    return namespace


def blocks(value):
    match = re.search(r"```apollo-ui\n([\s\S]+?)\n```", value)
    assert match
    return json.loads(match.group(1))["blocks"]


class GenerativeUITests(unittest.TestCase):
    def setUp(self):
        self.items = load_server_items(
            "APOLLO_GENERATIVE_UI_PROMPT", "apollo_routine_genui",
            "_APOLLO_UI_TYPES", "_APOLLO_UI_ACTIONS", "_apollo_safe_ui_url",
            "_apollo_ui_number", "_apollo_clean_ui_actions",
            "_apollo_normalize_quiz", "_apollo_normalize_ui_block",
            "apollo_sanitize_genui_content",
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
        self.assertIn('credentials: "same-origin"', source)
        self.assertIn("reconcileChecklist", source)
        self.assertIn("correct_answer_id", source)
        self.assertIn("allow_retry", source)
        self.assertIn("apolloGetActiveChatId", source)
        self.assertIn("state.current += 1", source)
        self.assertIn('block.type === "sources"', source)
        self.assertIn('block.type === "calculator"', source)
        self.assertIn('block.type === "function_explorer"', source)
        self.assertIn('block.type === "metric_trend"', source)
        self.assertIn("function renderFunctionExplorer", source)
        self.assertIn("function renderMetricTrend", source)
        self.assertNotIn('"Image unavailable"', source)
        self.assertIn("apollo-ui-card-text-only", source)
        self.assertIn("container.remove()", source)
        self.assertIn("dataset.quizTransition", source)
        self.assertIn("prefers-reduced-motion: reduce", source)

    def test_index_masks_partial_structured_streams(self):
        source = (ROOT / "index.html").read_text()
        self.assertIn('href="/apollo_genui.css?v=', source)
        self.assertIn('src="/apollo_genui.js?v=', source)
        self.assertEqual(source.count("createStreamRenderer?.("), 2)
        self.assertEqual(source.count("apolloStreamRenderer.update(assistantContent)"), 2)
        self.assertEqual(source.count("apolloStreamRenderer?.finish(assistantContent)"), 2)
        self.assertIn("window.ApolloGenUI?.copyText?.(content)", source)
        self.assertIn("message.appendChild(\n                assistantActions", source)
        client = (ROOT / "apollo_genui.js").read_text()
        self.assertIn("function completeStreamSegments", client)
        self.assertIn("const fence = tail.match", client)
        self.assertIn("if (!closing)", client)

    def test_prompt_requires_real_data_and_simple_fallback(self):
        prompt = self.items["APOLLO_GENERATIVE_UI_PROMPT"]
        self.assertIn("Simple questions must stay simple text", prompt)
        self.assertIn("Never invent data", prompt)
        self.assertIn("```apollo-ui", prompt)
        self.assertIn("correct_answer_id", prompt)
        self.assertIn("never create submit_message actions for quiz navigation", prompt)
        self.assertIn("data_kind", prompt)
        self.assertIn("Sources:", prompt)
        self.assertIn("one useful, complete sentence", prompt)
        self.assertIn("Function explorer:", prompt)
        self.assertIn("Metric trend:", prompt)
        self.assertIn('type?:"number"|"slider"|"segmented"', prompt)
        self.assertIn("V60 dose question must include", prompt)
        self.assertIn("safe removable_hole function_explorer", prompt)
        self.assertIn('metric_trend with unit "%"', prompt)
        self.assertIn('"id":"limit-explorer"', prompt)
        self.assertIn("explorer and quiz are both required", prompt)

    def test_interactive_widget_schemas_are_bounded(self):
        sanitize = self.items["apollo_sanitize_genui_content"]
        payload = {"blocks": [
            {
                "type": "calculator", "id": "brew", "operation": "multiply",
                "fields": [
                    {"id": "dose", "label": "Coffee", "type": "slider",
                     "value": 15, "min": 5, "max": 30, "step": 1, "unit": "g"},
                    {"id": "ratio", "label": "Ratio", "type": "segmented",
                     "value": 16, "min": 14, "max": 18, "step": 1,
                     "options": [{"label": "1:15", "value": 15},
                                 {"label": "1:16", "value": 16}]},
                ],
                "operands": ["dose", "ratio"],
                "output": {"label": "Water", "unit": "g", "decimals": 0},
            },
            {"type": "function_explorer", "id": "limit", "preset": "removable_hole",
             "target": 2, "value": 1.5, "min": 0, "max": 4, "step": 0.1},
            {"type": "metric_trend", "id": "recovery", "unit": "%",
             "data_kind": "measured", "ranges": [2],
             "items": [{"label": "Mon", "value": 61},
                       {"label": "Tue", "value": 73}]},
        ]}
        cleaned = blocks(sanitize("```apollo-ui\n" + json.dumps(payload) + "\n```"))
        self.assertEqual([item["type"] for item in cleaned], [
            "calculator", "function_explorer", "metric_trend",
        ])

        payload["blocks"][1]["preset"] = "eval_user_code"
        cleaned = blocks(sanitize("```apollo-ui\n" + json.dumps(payload) + "\n```"))
        self.assertNotIn("function_explorer", [item["type"] for item in cleaned])

    def test_sanitizer_normalizes_legacy_quiz_and_rejects_bad_key(self):
        sanitize = self.items["apollo_sanitize_genui_content"]
        legacy = {
            "blocks": [{"type": "quiz", "id": "facts", "question": "2 + 2?",
                        "options": [{"id": "four", "label": "4", "correct": True},
                                    {"id": "five", "label": "5", "correct": False}]}]
        }
        output = sanitize("Intro\n```apollo-ui\n" + json.dumps(legacy) + "\n```")
        quiz = blocks(output)[0]
        self.assertEqual(quiz["questions"][0]["correct_answer_id"], "four")
        self.assertNotIn("correct", quiz["questions"][0]["options"][0])

        malformed = {"blocks": [{
            "type": "quiz", "id": "bad", "question": "Pick one",
            "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "correct_answer_id": "missing",
        }]}
        self.assertEqual(
            sanitize("Safe text.\n```apollo-ui\n" + json.dumps(malformed) + "\n```"),
            "Safe text.",
        )
        self.assertEqual(
            sanitize('Readable lesson.\n```apollo-ui\n{"blocks":[{"type":"table"'),
            "Readable lesson.",
        )
        self.assertEqual(sanitize("Readable lesson.\n```apol"), "Readable lesson.")
        self.assertIn(
            "incomplete",
            sanitize('```apollo-ui\n{"blocks":[{"type":"quiz"'),
        )

    def test_sanitizer_deduplicates_sources_and_labels_charts(self):
        sanitize = self.items["apollo_sanitize_genui_content"]
        payload = {"blocks": [
            {"type": "sources", "id": "s", "items": [
                {"url": "https://example.com/a", "title": "Example"},
                {"url": "https://example.com/a", "title": "Duplicate"},
                {"url": "javascript:alert(1)", "title": "Unsafe"},
            ]},
            {"type": "chart", "id": "c", "kind": "bar",
             "items": [{"label": "A", "value": 2}]},
        ]}
        cleaned = blocks(sanitize("```apollo-ui\n" + json.dumps(payload) + "\n```"))
        self.assertEqual(len(cleaned[0]["items"]), 1)
        self.assertEqual(cleaned[1]["x_label"], "Category")
        self.assertEqual(cleaned[1]["data_kind"], "reported")


if __name__ == "__main__":
    unittest.main()
