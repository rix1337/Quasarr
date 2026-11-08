# -*- coding: utf-8 -*-
"""BY runs as a bundled template package around its site code."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bs4 import BeautifulSoup

from quasarr.search.sources import templates
from quasarr.search.sources.templates.by import search as by_search

FEED = """<table class="AUDIO_ITEMLIST"><tr><td><table class="AUDIO_ITEM"><tr><th>
<h1><a href="/category/HD/Movie-A-2026.html" title="Movie A 2026 German DL 1080p BluRay x264-GRP">Movie A 2026 German DL 1080p BluRay x264-GRP</a></h1></th></tr>
<tr height="25"><td><p>Erstellt am:</p></td><td><p>05.11.26 13:05</p></td></tr>
<tr height="25"><td><p>Größe:</p></td><td><p>4,59 GB</p></td></tr>
</table></td></tr></table>"""


class BYTemplateTests(unittest.TestCase):
    def test_template_keeps_the_capabilities(self):
        with patch(
            "quasarr.providers.shared_state.values",
            {"config": lambda _s: {"by": "source.invalid"}},
        ):
            source = templates._load("by")
        self.assertEqual([2000, 3000, 5000, 7000], source.supported_categories)
        self.assertTrue(source.supports_phrase)
        self.assertTrue(source.supports_date_numbering)

    def test_feed_sizes_respect_their_unit(self):
        state = SimpleNamespace(values={})
        with patch.object(by_search, "generate_download_link", return_value="x"):
            releases = by_search.Source()._parse_posts(
                BeautifulSoup(FEED, "html.parser"),
                state,
                "https://source.invalid",
                "source.invalid",
                search_category=2000,
            )
        self.assertEqual(
            "Movie.A.2026.German.DL.1080p.BluRay.x264-GRP",
            releases[0]["details"]["title"],
        )
        # 4,59 GB used to be reported as 4.59 MB
        self.assertEqual(4700 * 1024 * 1024, releases[0]["details"]["size"])


if __name__ == "__main__":
    unittest.main()
