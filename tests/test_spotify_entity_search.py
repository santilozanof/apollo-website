"""Spotify title lookup must keep punctuation and reject unrelated artwork."""
import unittest
from unittest import mock

import spotify_curator_tool


class SpotifyEntitySearchTests(unittest.TestCase):
    def test_hash_title_uses_exact_match_after_broad_fallback(self):
        calls = []
        class Spotify:
            def search(self, q, type, limit):
                calls.append(q)
                if q.startswith('track:'):
                    return {'tracks': {'items': []}}
                return {'tracks': {'items': [
                    {'id': 'unrelated', 'name': 'Tetas remix',
                     'artists': [{'name': 'Someone else'}]},
                    {'id': 'verified', 'name': '#TETAS',
                     'artists': [{'name': 'CA7RIEL & Paco Amoroso'}],
                     'album': {'name': 'Album', 'images': [
                         {'url': 'https://i.scdn.co/image/verified', 'width': 640, 'height': 640}]},
                     'external_urls': {'spotify': 'https://open.spotify.com/track/verified'}},
                ]}}
        with mock.patch.object(spotify_curator_tool, 'spotify_read', side_effect=lambda call, **_kwargs: call()):
            result = spotify_curator_tool.entity_search(Spotify(), 'song', '#tetas')
        self.assertEqual(calls, ['track:"#tetas"', '#tetas'])
        self.assertEqual(result['name'], '#TETAS')
        self.assertEqual(result['image_url'], 'https://i.scdn.co/image/verified')

    def test_no_exact_title_never_returns_an_image(self):
        class Spotify:
            def search(self, q, type, limit):
                return {'tracks': {'items': [{'name': 'Tetas remix'}]}}
        with mock.patch.object(spotify_curator_tool, 'spotify_read', side_effect=lambda call, **_kwargs: call()):
            self.assertIsNone(spotify_curator_tool.entity_search(Spotify(), 'song', '#tetas'))


if __name__ == '__main__':
    unittest.main()
