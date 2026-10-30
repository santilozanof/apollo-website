"""Application awareness uses real route contracts and bounded UI hints."""
import unittest
from types import SimpleNamespace
from unittest import mock

import apollo_capabilities
import server


class CapabilityTests(unittest.TestCase):
    def test_registry_only_advertises_implemented_routes(self):
        entries = apollo_capabilities.registry(server)
        indexed = {item['id']: item for item in entries}
        self.assertIn('music', indexed)
        self.assertIn('calendar', indexed)
        self.assertIn('canvas', indexed)
        self.assertIn('studio', indexed)
        self.assertEqual(indexed['canvas']['endpoints'], ['/api/calendar/subscriptions/canvas/status'])
        self.assertEqual(indexed['gmail']['availability'], 'registered')
        self.assertTrue(all(item['endpoints'] and item['operations'] for item in entries))

    def test_unsupported_backend_is_not_advertised(self):
        fake = SimpleNamespace(__file__='/nonexistent/server.py', ApolloHandler=SimpleNamespace())
        self.assertEqual(apollo_capabilities.registry(fake), [])

    def test_ui_state_is_a_validated_hint(self):
        self.assertEqual(apollo_capabilities.ui_state({
            'ui_state': {'view': 'Music', 'panel': 'history', 'secret': 'never include me'}
        }), {'view': 'music', 'panel': 'history'})
        self.assertEqual(apollo_capabilities.ui_state({
            'ui_state': {'view': 'filesystem', 'panel': 'terminal'}
        }), {})
        self.assertEqual(apollo_capabilities.ui_state({'ui_state': {
            'view': 'music', 'music_section': 'insights',
            'music_period': 'monthly', 'music_anchor': '2026-09-01',
            'provider_token': 'do not include',
        }}), {'view': 'music', 'music_section': 'insights',
               'music_period': 'monthly', 'music_anchor': '2026-09-01'})

    def test_app_question_receives_relevant_registry_without_private_data(self):
        value = apollo_capabilities.context_for_query(
            server, 'What does this setting do?', {'ui_state': {'view': 'settings'}}
        )
        self.assertIn('"id":"settings"', value)
        self.assertNotIn('"id":"music"', value)
        self.assertIsNone(apollo_capabilities.context_for_query(
            server, 'Explain photosynthesis', {'ui_state': {'view': 'settings'}}
        ))
        music = apollo_capabilities.context_for_query(
            server, 'Show me my Spotify stats from September', {'ui_state': {'view': 'apollo'}}
        )
        self.assertIn('"id":"music"', music)
        unsupported = apollo_capabilities.context_for_query(
            server, 'Open my university applications', {}
        )
        self.assertIn('"unregistered_feature":"university"', unsupported)


if __name__ == '__main__':
    unittest.main()
