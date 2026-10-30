"""Structural multi-turn checks; answer-quality evaluation needs a live model."""

import io
import json
import unittest
from unittest import mock

import server


FOLLOWUPS = [
    ("Venus is hotter than Mercury because of its thick atmosphere.", "Wait, but Mercury is closer, right?"),
    ("A deductible is what you pay before coverage begins.", "So I still pay the premium too? Wild."),
    ("The album came out in 2012.", "Nah, that timeline sounds off."),
    ("The first train left at 08:10.", "So I missed it? Damn."),
    ("A black hole has an event horizon.", "Okay and what happens past that?"),
    ("That ingredient contains caffeine.", "Bruh I thought it was decaf."),
    ("The exam is on Thursday.", "Oh, that's sooner than I thought."),
    ("This code retries a failed read twice.", "But what if the first one times out?"),
    ("She won the award in 1998.", "Really? I thought it was later."),
    ("The route is 12 kilometers.", "That is a long walk lol."),
    ("The painting is from his blue period.", "So that's why it looks sad?"),
    ("Your summary includes only verified minutes.", "Then why are yesterday's minutes missing?"),
    ("The device uses a local passkey.", "So Face ID is doing the signing?"),
    ("The recipe takes about 40 minutes.", "Okay, what if I skip the oven?"),
    ("The documentary used archival footage.", "That clip looked staged though."),
    ("The concert starts at 19:00.", "Bet, and doors?"),
    ("The assignment is due next Monday.", "I already submitted that one."),
    ("This phone has an OLED screen.", "Why does black look so different then?"),
    ("The treaty was signed after the war.", "So they were allies before?"),
    ("The artist first collaborated in 2011.", "No way, what about that earlier track?"),
]


class ConversationContinuityTests(unittest.TestCase):
    def test_stateless_hermes_call_does_not_replace_submitted_history(self):
        captured = []
        def open_request(request, timeout):
            captured.append(request)
            return io.BytesIO(b'{"choices":[{"message":{"content":"I said vermilion orange."}}]}')
        messages = [
            {'role': 'user', 'content': 'What color was the bridge?'},
            {'role': 'assistant', 'content': 'The bridge was vermilion orange.'},
            {'role': 'user', 'content': 'What color did you say it was?'},
        ]
        with mock.patch.object(server, 'get_api_key', return_value='test-only'), \
                mock.patch.object(server.urllib.request, 'urlopen', side_effect=open_request):
            self.assertEqual(server.ask_hermes(messages), 'I said vermilion orange.')
        self.assertNotIn('X-hermes-session-id', captured[0].headers)
        body = json.loads(captured[0].data)
        self.assertEqual(body['messages'][-2], messages[-2])

    def test_short_followups_keep_prior_answer_on_fast_path(self):
        for prior_answer, followup in FOLLOWUPS:
            with self.subTest(followup=followup):
                messages = [
                    {'role': 'system', 'content': server.APOLLO_PERSONALITY_PROMPT},
                    {'role': 'user', 'content': 'Tell me about that.'},
                    {'role': 'assistant', 'content': prior_answer},
                    {'role': 'user', 'content': followup},
                ]
                payload = server._apollo_build_hermes_payload(messages, enabled_toolsets=[])
                self.assertEqual(payload['model'], 'gpt-5.6-luna')
                self.assertEqual(payload['model_options']['reasoning_effort'], 'low')
                self.assertTrue(payload['model_options']['disable_tools'])
                self.assertEqual(payload['messages'][-2]['content'], prior_answer)
                self.assertEqual(payload['messages'][-1]['content'], followup)

    def test_regression_reaction_is_not_stripped_from_context(self):
        messages = [
            {'role': 'user', 'content': 'Why did Amy Winehouse die?'},
            {'role': 'assistant', 'content': 'The reported cause was alcohol poisoning.'},
            {'role': 'user', 'content': 'Bruh so cause of a fun party.'},
        ]
        payload = server._apollo_build_hermes_payload(messages, enabled_toolsets=[])
        self.assertEqual(payload['messages'][-2]['role'], 'assistant')
        self.assertIn('alcohol poisoning', payload['messages'][-2]['content'])
        self.assertEqual(payload['model'], 'gpt-5.6-luna')


if __name__ == '__main__':
    unittest.main()
