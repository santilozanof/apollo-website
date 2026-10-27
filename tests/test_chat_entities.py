import json
import unittest

import apollo_entity
from spotify_curator_tool import entity_search, entity_title_matches


class EntityResolutionTests(unittest.TestCase):
    def test_public_page_requires_exact_title_and_safe_source(self):
        page = {"query": {"pages": [{"title": "A Public Book", "pageid": 123,
                 "fullurl": "https://en.wikipedia.org/wiki/A_Public_Book",
                 "extract": "A documented public work.",
                 "thumbnail": {"source": "https://upload.wikimedia.org/example.jpg"}}]}}
        found = apollo_entity.resolve("book", "A Public Book", public_fetch=lambda _url: page,
                                      image_check=lambda _url: True)
        self.assertEqual(found["provider_id"], "123")
        self.assertEqual(found["provider"], "Wikipedia")
        self.assertEqual(found["image_url"], "https://upload.wikimedia.org/example.jpg")
        missing_image = apollo_entity.resolve("book", "A Public Book", public_fetch=lambda _url: page,
                                              image_check=lambda _url: False)
        self.assertIsNone(missing_image["image_url"])
        self.assertIsNone(apollo_entity.resolve("book", "Another Book", public_fetch=lambda _url: page))
        unsafe = json.loads(json.dumps(page))
        unsafe["query"]["pages"][0]["fullurl"] = "https://evil.example/book"
        self.assertIsNone(apollo_entity.resolve("book", "A Public Book", public_fetch=lambda _url: unsafe))

    def test_music_entity_uses_verified_spotify_metadata_only(self):
        class Spotify:
            def search(self, **kwargs):
                self.query = kwargs
                return {"albums": {"items": [{"id": "spotify-id", "name": "A Public Album",
                    "artists": [{"name": "Example Artist"}],
                    "images": [{"url": "https://i.scdn.co/image/abc", "width": 300}],
                    "external_urls": {"spotify": "https://open.spotify.com/album/spotify-id"}}]}}
        spotify = Spotify()
        found = entity_search(spotify, "album", "A Public Album", "Example Artist")
        self.assertEqual(found["provider"], "Spotify")
        self.assertEqual(found["image_url"], "https://i.scdn.co/image/abc")
        self.assertEqual(spotify.query["type"], "album")
        self.assertIsNone(entity_search(spotify, "album", "A Public Album", "Different Artist"))
        self.assertIsNone(apollo_entity.resolve("album", "A Different Album",
            spotify_lookup=lambda *_args: found))

    def test_invalid_entity_queries_are_rejected(self):
        with self.assertRaises(ValueError):
            apollo_entity.resolve("unknown", "A Person")
        with self.assertRaises(ValueError):
            apollo_entity.resolve("person", "<script>")

    def test_official_release_suffix_resolves_without_accepting_unrelated_versions(self):
        self.assertTrue(entity_title_matches("House of Balloons", "House Of Balloons (Original)"))
        self.assertFalse(entity_title_matches("House of Balloons", "House Of Balloons (Instrumental)"))
        self.assertFalse(entity_title_matches("House of Balloons", "House Of Balloons x Another Song"))

        class Spotify:
            def search(self, **_kwargs):
                return {"albums": {"items": [
                    {"id": "cover", "name": "House Of Balloons (Instrumental)",
                     "artists": [{"name": "Another Artist"}]},
                    {"id": "original", "name": "House Of Balloons (Original)",
                     "artists": [{"name": "The Weeknd"}],
                     "images": [{"url": "https://i.scdn.co/image/official", "width": 300}],
                     "external_urls": {"spotify": "https://open.spotify.com/album/original"}},
                ]}}
        found = entity_search(Spotify(), "album", "House of Balloons", "The Weeknd")
        self.assertEqual(found["provider_id"], "original")
        resolved = apollo_entity.resolve("album", "House of Balloons", "The Weeknd",
            spotify_lookup=lambda *_args: found, image_check=lambda _url: True)
        self.assertEqual(resolved["name"], "House Of Balloons (Original)")


if __name__ == "__main__":
    unittest.main()
