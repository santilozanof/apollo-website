import ast
import json
import re
import unittest
import apollo_entity
from types import SimpleNamespace
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
    def test_full_historical_story_uses_smart_model_without_upgrading_casual_chat(self):
        namespace = {}
        namespace["_apollo_router_text"] = load_function("_apollo_router_text", {})
        namespace["_apollo_latest_user_text"] = load_function("_apollo_latest_user_text", namespace)
        namespace["_apollo_turn_has_image"] = load_function("_apollo_turn_has_image", namespace)
        choose = load_function("_apollo_choose_model", namespace)
        self.assertEqual(choose([{"role": "user", "content":
            "Tell me the whole story of the project before and during its launch."}])["tier"], "SMART")
        self.assertEqual(choose([{"role": "user", "content": "Hey, how's it going?"}])["tier"], "FAST")

    def test_public_history_enables_read_only_research_without_searching_personal_history(self):
        namespace = {"re": re}
        namespace["_apollo_router_text"] = load_function("_apollo_router_text", namespace)
        namespace["_apollo_latest_user_text"] = load_function("_apollo_latest_user_text", namespace)
        namespace["_apollo_turn_has_image"] = load_function("_apollo_turn_has_image", namespace)
        namespace["apollo_story_visual_candidate"] = load_function("apollo_story_visual_candidate", namespace)
        choose = load_function("_apollo_choose_hermes_toolsets", namespace)
        self.assertEqual(choose([{"role": "user", "content":
            "Tell me the whole story of an artist before the first album."}]), ["web"])
        self.assertEqual(choose([{"role": "user", "content":
            "Tell me the whole story of my family."}]), [])

    def test_stream_passes_only_selected_read_only_web_capability(self):
        routed = []
        class Response:
            def __iter__(self):
                return iter([b'data: {"choices":[{"delta":{"content":"Ready."}}]}\n', b'data: [DONE]\n'])
            def close(self):
                pass
        namespace = {
            "json": json, "HERMES_URL": "http://local.invalid", "get_api_key": lambda: "test",
            "_apollo_choose_hermes_toolsets": lambda _messages: ["web"],
            "_apollo_build_hermes_payload": lambda _messages, **kwargs: routed.append(kwargs) or {},
            "urllib": SimpleNamespace(request=SimpleNamespace(
                Request=lambda *_a, **_k: object(), urlopen=lambda *_a, **_k: Response())),
        }
        stream = load_function("stream_hermes", namespace)
        self.assertEqual("".join(stream([{"role": "user", "content": "Public history"}])), "Ready.")
        self.assertEqual(routed[0]["enabled_toolsets"], ["web"])

    def test_long_unstructured_reply_gets_headings_without_rewriting_prose(self):
        structure = load_function("apollo_structure_long_response", {"re": re, "json": json})
        paragraphs = [f"Paragraph {i}. " + ("A factual sentence. " * 35) for i in range(14)]
        original = "\n\n".join(paragraphs)
        planning = lambda *_a, **_k: json.dumps({"sections": [
            {"before": 1, "title": "The beginning"},
            {"before": 6, "title": "The middle"},
            {"before": 10, "title": "The outcome"},
        ]})
        changed, used = structure(original, planning)
        self.assertTrue(used)
        self.assertEqual(re.sub(r"(?m)^## .+\n\n", "", changed), "\n\n".join(part.strip() for part in paragraphs))
        already_structured, used = structure("## Existing section\n\n" + original, planning)
        self.assertFalse(used)
        self.assertIn("## Existing section", already_structured)

    def test_public_story_visual_requires_verified_image_and_preserves_text(self):
        namespace = {"re": re, "json": json}
        candidate = load_function("apollo_story_visual_candidate", namespace)
        namespace["apollo_story_visual_candidate"] = candidate
        resolve = load_function("apollo_verified_story_visual", namespace)
        insert = load_function("apollo_insert_story_visual", namespace)
        image = {"url": "https://thumb.wikimedia.org/example.jpg", "alt": "Public figure portrait",
                 "source_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
                 "source_title": "Example.jpg", "publisher": "Wikimedia Commons"}
        prompt = "Tell me the whole story of a public figure before their first major release."
        seen = []
        found = resolve(prompt,
            lambda *_a, **_k: json.dumps({"public": True, "subject": "Public Figure"}),
            lambda subject: seen.append(subject) or image)
        self.assertEqual(seen, ["Public Figure"])
        answer, added = insert("A direct opening.\n\n## Background\n\nThe facts remain intact.", found)
        self.assertTrue(added)
        self.assertIn("## Background\n\nThe facts remain intact.", answer)
        self.assertIn('"type":"image"', answer)
        self.assertIn('"type":"sources"', answer)
        self.assertFalse(candidate("Tell me the whole story of my family"))

    def test_substantial_story_gets_bounded_editorial_title(self):
        namespace = {"re": re, "json": json}
        namespace["apollo_story_visual_candidate"] = load_function("apollo_story_visual_candidate", namespace)
        title = load_function("apollo_story_title", namespace)
        answer = "A public artist made a notable album. " * 75
        question = "Tell me the full story of this public artist and album"
        self.assertEqual(title(answer, question, lambda *_a, **_k:
            json.dumps({"title": "The Artist Before the Album"})),
            "The Artist Before the Album")
        self.assertIsNone(title("# Existing Title\n\n" + answer, question,
            lambda *_a, **_k: json.dumps({"title": "An Unneeded New Title"})))
        self.assertIsNone(title(answer, "Tell me the full story of my family",
            lambda *_a, **_k: json.dumps({"title": "A Private Family History"})))

    def test_story_timeline_uses_only_sentences_already_in_answer(self):
        namespace = {"re": re, "json": json}
        namespace["apollo_story_visual_candidate"] = load_function("apollo_story_visual_candidate", namespace)
        namespace["apollo_insert_story_timeline"] = load_function("apollo_insert_story_timeline", namespace)
        timeline = load_function("apollo_add_story_timeline", namespace)
        facts = [
            "In 2008, the group started working together.",
            "By 2010, the project had adopted a new direction.",
            "In 2012, the finished work reached a wider audience.",
        ]
        content = ("A chronological account can be divided into phases.\n\n## Early work\n\n"
                   + facts[0] + " " + "Background detail. " * 80
                   + "\n\n## Later work\n\n" + facts[1] + " " + "More context. " * 80
                   + "\n\n" + facts[2] + " " + "The outcome followed. " * 80)
        events = {"events": [{"time": year, "evidence": fact}
                             for year, fact in zip(("2008", "2010", "2012"), facts)]}
        changed, added = timeline(content, "Tell me the whole story of this project",
                                  lambda *_a, **_k: json.dumps(events))
        self.assertTrue(added)
        self.assertIn('"type":"timeline"', changed)
        self.assertTrue(all(fact in changed for fact in facts))
        events["events"][0]["evidence"] = "In 2008, a different event happened."
        unchanged, added = timeline(content, "Tell me the whole story of this project",
                                    lambda *_a, **_k: json.dumps(events))
        self.assertFalse(added)
        self.assertEqual(unchanged, content.strip())

    def test_story_entity_card_requires_exact_mention_and_provider_kind(self):
        namespace = {"re": re, "json": json, "apollo_entity": apollo_entity}
        namespace["apollo_story_visual_candidate"] = load_function("apollo_story_visual_candidate", namespace)
        namespace["apollo_story_entity_refs"] = load_function("apollo_story_entity_refs", namespace)
        select = load_function("apollo_select_story_entities", namespace)
        insert = load_function("apollo_insert_story_entities", namespace)
        source = ("A public artist made A Public Album. " * 65).strip()
        selected = select(source, "Tell me the whole story of this album",
            lambda *_a, **_k: json.dumps({"entities": [
                {"kind": "album", "name": "A Public Album", "artist": "A public artist"},
                {"kind": "movie", "name": "A nonexistent movie"},
            ]}))
        self.assertEqual(selected, [{"kind": "album", "name": "A Public Album", "artist": "A public artist"}])
        rendered, added = insert(source, selected)
        self.assertTrue(added)
        self.assertIn('"schema":"apollo.rich","version":3', rendered)
        self.assertIn('"name":"A Public Album"', rendered)

        # An existing artist card must not suppress a central album reference.
        source_with_artist = (source + "\n\n```apollo-ui\n" + json.dumps({
            "schema": "apollo.rich", "version": 3, "blocks": [
                {"type": "entity", "id": "artist", "kind": "artist", "name": "A public artist"}
            ]}) + "\n```")
        selected = select(source_with_artist, "Tell me the whole story of this album",
            lambda *_a, **_k: json.dumps({"entities": [
                {"kind": "artist", "name": "A public artist"},
                {"kind": "album", "name": "A Public Album", "artist": "A public artist"},
            ]}))
        self.assertEqual([item["kind"] for item in selected], ["album"])
        rendered, added = insert(source_with_artist, selected)
        self.assertTrue(added)
        self.assertEqual(rendered.count('"type":"entity"'), 1)
        self.assertEqual(len(namespace["apollo_story_entity_refs"](rendered)), 2)

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
