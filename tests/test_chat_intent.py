import ast
import json
import re
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


class ChatIntentPlannerTests(unittest.TestCase):
    def test_semantic_plan_normalizes_domain_action_and_sources(self):
        captured = []
        planner = load_function("apollo_context_planner", {
            "ask_hermes": lambda messages: captured.append(messages) or json.dumps({
                "intent": "personal_query",
                "primary_domain": "spotify",
                "action_authorized": False,
                "clarification": "",
                "calendar": False,
                "tasks": False,
                "whoop": False,
                "spotify": True,
                "calendar_days": 7,
                "reason": "current playback question",
            }),
            "json": json,
        })
        plan = planner(
            [{"role": "user", "content": "What's playing?"}],
            "What's playing?",
            {"surface": "chat"},
        )
        self.assertEqual(plan["intent"], "personal_query")
        self.assertEqual(plan["primary_domain"], "spotify")
        self.assertTrue(plan["spotify"])
        self.assertFalse(plan["action_authorized"])
        prompt = captured[0][0]["content"]
        self.assertIn("How much water is in ramen?", prompt)
        self.assertIn("topic switch", prompt)

    def test_action_authority_cannot_be_enabled_for_a_question(self):
        planner = load_function("apollo_context_planner", {
            "ask_hermes": lambda _messages: json.dumps({
                "intent": "personal_query", "primary_domain": "tasks",
                "action_authorized": True, "tasks": True,
            }),
            "json": json,
        })
        plan = planner([], "What tasks do I have?", {})
        self.assertFalse(plan["action_authorized"])
        self.assertEqual(plan["intent"], "personal_query")

        unsafe = load_function("apollo_context_planner", {
            "ask_hermes": lambda _messages: json.dumps({
                "intent": "explicit_action", "primary_domain": "tasks",
                "action_authorized": False, "tasks": False,
            }),
            "json": json,
        })([], "Delete a task", {})
        self.assertEqual(unsafe["intent"], "ambiguous_action")
        self.assertTrue(unsafe["clarification"])

    def test_planner_preserves_structured_reference_resolution(self):
        planner = load_function("apollo_context_planner", {
            "ask_hermes": lambda _messages: json.dumps({
                "intent": "explicit_action",
                "primary_domain": "routines",
                "action_authorized": True,
                "clarification": "",
                "calendar": False,
                "tasks": False,
                "whoop": False,
                "spotify": False,
                "calendar_days": 7,
                "reason": "resolved from the prior skincare discussion",
                "reference_resolution": {
                    "status": "resolved",
                    "operation": "add_step",
                    "entity_type": "ingredient",
                    "names": ["Azelaic acid 10%"],
                    "target_name": "Morning",
                    "relation": "after",
                    "anchor_name": "Niacinamide serum",
                },
            }),
            "json": json,
        })
        plan = planner([
            {"role": "user", "content": "Can I pair azelaic acid 10% with niacinamide?"},
            {"role": "assistant", "content": "Yes. Use niacinamide, then azelaic acid 10%."},
            {"role": "user", "content": "Ok add it to my morning routine."},
        ], "Ok add it to my morning routine.", {})
        self.assertEqual(plan["reference_resolution"]["names"], ["Azelaic acid 10%"])
        self.assertEqual(plan["reference_resolution"]["anchor_name"], "Niacinamide serum")

    def test_planner_preserves_compound_replacement_with_quoted_literal(self):
        planner = load_function("apollo_context_planner", {
            "ask_hermes": lambda _messages: json.dumps({
                "intent": "explicit_action",
                "primary_domain": "routines",
                "action_authorized": True,
                "clarification": "",
                "calendar": False,
                "tasks": False,
                "whoop": False,
                "spotify": False,
                "calendar_days": 7,
                "reference_resolution": {
                    "status": "resolved",
                    "operation": "replace_step",
                    "entity_type": "routine_step",
                    "names": ["it", "Azelaic acid 10%"],
                    "target_name": "Morning",
                    "relation": "",
                    "anchor_name": "",
                    "clarification": "",
                },
                "reason": "quoted literal and explicit replacement",
            }),
            "json": json,
        })
        plan = planner([
            {"role": "user", "content": "I use azelaic acid 10%."},
            {"role": "assistant", "content": "That fits after niacinamide."},
        ], "remove 'it' from my morning routine and add azelaic acid instead", {})
        self.assertEqual(plan["intent"], "explicit_action")
        self.assertTrue(plan["action_authorized"])
        self.assertEqual(plan["reference_resolution"]["operation"], "replace_step")
        self.assertEqual(
            plan["reference_resolution"]["names"],
            ["it", "Azelaic acid 10%"],
        )

    def test_planner_fails_closed_when_reference_is_ambiguous(self):
        planner = load_function("apollo_context_planner", {
            "ask_hermes": lambda _messages: json.dumps({
                "intent": "explicit_action",
                "primary_domain": "routines",
                "action_authorized": True,
                "clarification": "",
                "reference_resolution": {
                    "status": "ambiguous",
                    "clarification": "Do you mean niacinamide or azelaic acid 10%?",
                },
            }),
            "json": json,
        })
        plan = planner([], "Add that.", {})
        self.assertEqual(plan["intent"], "ambiguous_action")
        self.assertFalse(plan["action_authorized"])
        self.assertEqual(
            plan["clarification"],
            "Do you mean niacinamide or azelaic acid 10%?",
        )

    def test_conservative_fallback_does_not_route_generic_water_topic(self):
        fallback = load_function("apollo_conservative_intent_fallback", {"re": re})
        general = fallback("How much water does a large ramen bowl have?")
        personal = fallback("How much water intake do I have today?")
        action = fallback("Add 500 ml to my water intake")
        self.assertEqual(general["primary_domain"], "general")
        self.assertEqual(general["intent"], "general_knowledge")
        self.assertEqual(personal["intent"], "personal_query")
        self.assertEqual(action["intent"], "explicit_action")
        self.assertTrue(action["action_authorized"])

    def test_router_rejects_general_knowledge_even_if_domain_is_present(self):
        route = load_function("apollo_intent_routes_to", {})
        self.assertFalse(route({
            "intent": "general_knowledge", "primary_domain": "whoop"
        }, "whoop"))
        self.assertTrue(route({
            "intent": "personal_query", "primary_domain": "whoop"
        }, "whoop"))

    def test_fast_plan_skips_model_only_for_confident_turns(self):
        fast = load_function("apollo_fast_context_plan", {"re": re})
        coffee = fast([], "How much coffee should I use for a V60?")
        calculus = fast([], "Teach me limits with an adjustable example.")
        whoop = fast([], "Show me my recovery trend.")
        mutation = fast([], "Delete my afternoon task.")
        follow_up = fast([], "What about tomorrow?")
        referenced_follow_up = fast([], "Can you explain that more simply?")
        implied_action = fast([], "Turn this into tasks.")

        self.assertEqual(coffee["intent"], "general_knowledge")
        self.assertEqual(calculus["planning_mode"], "local")
        self.assertEqual(whoop["primary_domain"], "whoop")
        self.assertTrue(whoop["whoop"])
        self.assertIsNone(mutation)
        self.assertIsNone(follow_up)
        self.assertIsNone(referenced_follow_up)
        self.assertIsNone(implied_action)

    def test_real_world_implicit_sources_and_old_references_keep_semantic_planning(self):
        fast = load_function("apollo_fast_context_plan", {"re": re})
        for prompt in (
            "Which unfinished tasks are due soon?",
            "Which of my connected services can you access right now?",
            "What colour did we choose for the packaging of that Cedar Atlas project months ago?",
            "What beverage did I say I enjoy with breakfast in that old validation conversation?",
            "What did I tell you about the fictional Zorblax-947 underwater bakery?",
            "Show my calendar and unfinished assignments.",
        ):
            with self.subTest(prompt=prompt):
                self.assertIsNone(fast([], prompt))


if __name__ == "__main__":
    unittest.main()
