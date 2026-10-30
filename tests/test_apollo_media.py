import json
import re
import unittest
from unittest.mock import patch

from apollo_media import visual_request, visual_response, public_subject_image, generation_request


class ApolloMediaTests(unittest.TestCase):
    def test_explicit_visual_request_and_context(self):
        history = [{"role": "user", "content": "Give me an FL Studio masterclass."}]
        self.assertEqual(visual_request("Show me images of FL Studio.", history), "fl-studio")
        self.assertEqual(visual_request("Show me FL Studio's Piano Roll.", history), "fl-studio-piano-roll")
        self.assertEqual(visual_request("Show me images of it.", history), "fl-studio")
        self.assertEqual(visual_request("Show me photos of vintage espresso machines.", []), "vintage espresso machine")
        products = [{"role": "assistant", "content": "1. La Marzocco Linea Mini\n2. Rancilio Silvia\n3. Gaggia Classic Pro"}]
        self.assertEqual(visual_request("Show me the second one.", products), "Rancilio Silvia")
        self.assertIsNone(visual_request("What does MIDI stand for?", history))

    def test_spanish_music_followup_keeps_the_original_subject(self):
        history = [
            {"role": "user", "content": "#tetas"},
            {"role": "assistant", "content": "¿Te refieres a una canción?"},
            {"role": "user", "content": "es una canción"},
            {"role": "user", "content": "búscala"},
        ]
        self.assertEqual(visual_request("enséñame una foto", history), "#tetas")
        self.assertFalse(generation_request("enséñame una foto"))
        self.assertTrue(generation_request("haz una imagen de un sigma looksmaxxer con toda la huzz"))

    def test_gallery_contains_direct_images_and_attribution(self):
        image = {
            "url": "https://www.image-line.com/example.png", "alt": "Piano Roll",
            "caption": "Image-Line", "source_url": "https://www.image-line.com/manual",
            "source_title": "Manual", "publisher": "Image-Line",
        }
        with patch("apollo_media._official_fl_images", return_value=[image]):
            content = visual_response("fl-studio-piano-roll")
        payload = json.loads(re.search(r"```apollo-ui\n(.*?)\n```", content, re.S).group(1))
        self.assertEqual([item["type"] for item in payload["blocks"]], ["image_gallery", "sources"])
        self.assertEqual(payload["blocks"][0]["items"][0]["url"], image["url"])
        self.assertEqual(payload["blocks"][1]["items"][0]["publisher"], "Image-Line")

    def test_failed_retrieval_is_honest(self):
        with patch("apollo_media._official_fl_images", return_value=[]):
            content = visual_response("fl-studio")
        self.assertIn("couldn’t verify loadable images", content)
        self.assertNotIn("image_gallery", content)

    def test_story_portrait_requires_matching_public_file_title(self):
        images = [
            {"source_title": "Another Performer.jpg", "url": "https://thumb.wikimedia.org/wrong.jpg"},
            {"source_title": "The Weeknd portrait.jpg", "url": "https://thumb.wikimedia.org/right.jpg"},
        ]
        with patch("apollo_media._commons_images", return_value=images) as find:
            self.assertEqual(public_subject_image("The Weeknd"), images[1])
            find.assert_called_once_with("The Weeknd")
        self.assertIsNone(public_subject_image("https://private.example/name"))


if __name__ == "__main__":
    unittest.main()
