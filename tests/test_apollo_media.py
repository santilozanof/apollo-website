import json
import re
import unittest
from unittest.mock import patch

from apollo_media import visual_request, visual_response


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


if __name__ == "__main__":
    unittest.main()
