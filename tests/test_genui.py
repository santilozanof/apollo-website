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
            "_apollo_normalize_expression", "_apollo_extract_ui_requirements",
            "_apollo_ui_block_matches_topic", "_apollo_ui_demo_control_count",
            "_apollo_expression_facts", "_apollo_calculator_field_matches",
            "_apollo_calculator_meets_requirements",
            "_apollo_validate_ui_requirements", "apollo_sanitize_genui_content",
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
        self.assertIn('type:"number"|"slider"|"segmented"|"select"', prompt)
        self.assertIn('expression:<safe expression>', prompt)
        self.assertIn('Selector: {type:"selector"', prompt)
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

    def test_safe_expression_calculator_supports_compound_interest(self):
        sanitize = self.items["apollo_sanitize_genui_content"]
        payload = {"blocks": [{
            "type": "calculator", "id": "compound-interest",
            "fields": [
                {"id": "principal", "label": "Principal", "type": "slider",
                 "value": 10000, "min": 100, "max": 100000, "step": 100,
                 "unit": "$"},
                {"id": "rate", "label": "Annual rate", "type": "slider",
                 "value": 5, "min": 0, "max": 20, "step": 0.1, "unit": "%"},
                {"id": "years", "label": "Years", "type": "segmented",
                 "value": 10, "min": 1, "max": 30, "step": 1,
                 "options": [{"label": "5", "value": 5},
                             {"label": "10", "value": 10},
                             {"label": "20", "value": 20}]},
                {"id": "periods", "label": "Compounding", "type": "segmented",
                 "value": 12, "min": 1, "max": 365, "step": 1,
                 "options": [{"label": "Monthly", "value": 12},
                             {"label": "Quarterly", "value": 4}]},
            ],
            "expression": {"op": "multiply", "args": [
                {"field": "principal"},
                {"op": "power", "args": [
                    {"op": "add", "args": [1, {"op": "divide", "args": [
                        {"op": "divide", "args": [{"field": "rate"}, 100]},
                        {"field": "periods"}
                    ]}]},
                    {"op": "multiply", "args": [
                        {"field": "periods"}, {"field": "years"}
                    ]}
                ]}
            ]},
            "output": {"label": "Final balance", "format": "currency",
                       "currency": "USD", "decimals": 2},
        }]}
        cleaned = blocks(sanitize("```apollo-ui\n" + json.dumps(payload) + "\n```"))
        calculator = cleaned[0]
        self.assertEqual(calculator["expression"]["op"], "multiply")
        self.assertEqual(calculator["output"]["format"], "currency")

    def test_selector_requires_visible_options_and_local_details(self):
        sanitize = self.items["apollo_sanitize_genui_content"]
        payload = {"blocks": [{
            "type": "selector", "id": "recipes", "title": "Pick a recipe",
            "options": [
                {"id": "espresso", "label": "Espresso", "title": "Espresso",
                 "description": "18 g in, 36 g out.",
                 "details": [{"label": "Ratio", "value": "1:2"}]},
                {"id": "v60", "label": "V60", "title": "V60",
                 "description": "15 g coffee, 250 g water.",
                 "details": [{"label": "Grind", "value": "Medium-fine"}]},
                {"id": "aeropress", "label": "AeroPress", "title": "AeroPress",
                 "description": "15 g coffee, 220 g water.",
                 "details": [{"label": "Time", "value": "2 min"}]},
            ],
            "selected": "espresso", "control": "segmented",
        }]}
        selector = blocks(sanitize(
            "```apollo-ui\n" + json.dumps(payload) + "\n```"
        ))[0]
        self.assertEqual([option["label"] for option in selector["options"]], [
            "Espresso", "V60", "AeroPress",
        ])

        empty = {"blocks": [{"type": "button_group", "id": "empty",
                              "title": "Pick one", "actions": []}]}
        self.assertNotIn(
            "apollo-ui",
            sanitize("```apollo-ui\n" + json.dumps(empty) + "\n```"),
        )

    def test_explicit_requirement_contract_tracks_mixed_deliverables(self):
        extract = self.items["_apollo_extract_ui_requirements"]
        validate = self.items["_apollo_validate_ui_requirements"]
        contract = extract(
            "Teach me jazz harmony with an interactive mini-lesson, "
            "a chord progression comparison, and a short quiz."
        )
        self.assertTrue(contract["quiz"])
        self.assertTrue(contract["comparison"])
        lesson_only = "Lesson.\n\n| Chord | Notes |\n|---|---|\n| Cmaj7 | C E G B |"
        self.assertTrue(any(
            "quiz" in item for item in validate(lesson_only, contract)
        ))

        selector_contract = extract(
            "Compare soup, salad, and pasta with a selector that changes details."
        )
        self.assertTrue(selector_contract["selector"])
        self.assertGreaterEqual(selector_contract["option_count"], 3)

    def test_requirement_contract_rejects_off_topic_demo_and_quiz(self):
        extract = self.items["_apollo_extract_ui_requirements"]
        validate = self.items["_apollo_validate_ui_requirements"]
        prompt = (
            "Teach me kinetic energy with an interactive demonstration that "
            "lets me adjust mass and velocity, plus a short quiz."
        )
        requirements = extract(prompt)
        self.assertEqual(requirements["interactive_control_count"], 2)
        self.assertIn("kinetic", requirements["topic_terms"])
        self.assertIn("velocity", requirements["topic_terms"])

        wrong = {"blocks": [
            {"type": "function_explorer", "id": "limit",
             "preset": "removable_hole", "target": 1, "value": 0.5,
             "min": -1, "max": 3, "step": 0.1},
            {"type": "quiz", "id": "limit-check", "questions": [{
                "id": "q1", "question": "What is the limit as x approaches 1?",
                "options": [{"id": "a", "label": "1"},
                            {"id": "b", "label": "2"}],
                "correct_answer_id": "b",
            }]},
        ]}
        wrong_content = "```apollo-ui\n" + json.dumps(wrong) + "\n```"
        self.assertEqual(
            validate(wrong_content, requirements),
            ["topic-aligned quiz", "interactive demonstration"],
        )

        correct = {"blocks": [
            {"type": "calculator", "id": "ke-demo", "fields": [
                {"id": "mass", "label": "Mass"},
                {"id": "velocity", "label": "Velocity"},
            ], "expression": {"op": "multiply", "args": [0.5, {
                "op": "multiply", "args": [
                    {"field": "mass"},
                    {"op": "power", "args": [{"field": "velocity"}, 2]},
                ],
            }]}},
            {"type": "quiz", "id": "ke-check", "questions": [{
                "id": "q1", "question": "How does kinetic energy change with velocity?",
                "options": [{"id": "a", "label": "Linearly"},
                            {"id": "b", "label": "With velocity squared"}],
                "correct_answer_id": "b",
            }]},
        ]}
        correct_content = "```apollo-ui\n" + json.dumps(correct) + "\n```"
        self.assertEqual(validate(correct_content, requirements), [])

    def test_compound_contract_rejects_generic_three_field_sum(self):
        extract = self.items["_apollo_extract_ui_requirements"]
        validate = self.items["_apollo_validate_ui_requirements"]
        prompt = (
            "Build me an interactive compound-interest calculator with a "
            "principal slider, annual interest-rate slider, and time-period "
            "selector. Show the final balance updating immediately."
        )
        requirements = extract(prompt)
        self.assertEqual(
            requirements["calculator_control_types"],
            ["slider", "slider", "selector"],
        )
        self.assertEqual(requirements["required_operations"], ["power"])

        generic = {"blocks": [{
            "type": "calculator", "id": "generic", "operation": "sum",
            "fields": [
                {"id": "value-1", "label": "Value 1", "type": "number",
                 "value": 0, "min": 0, "max": 100, "step": 1},
                {"id": "value-2", "label": "Value 2", "type": "number",
                 "value": 0, "min": 0, "max": 100, "step": 1},
                {"id": "value-3", "label": "Value 3", "type": "number",
                 "value": 0, "min": 0, "max": 100, "step": 1},
            ],
            "operands": ["value-1", "value-2", "value-3"],
            "output": {"label": "Total", "decimals": 2},
        }]}
        generic_content = "```apollo-ui\n" + json.dumps(generic) + "\n```"
        sanitized_generic = self.items["apollo_sanitize_genui_content"](
            generic_content
        )
        self.assertEqual(validate(sanitized_generic, requirements), ["calculator"])


if __name__ == "__main__":
    unittest.main()
