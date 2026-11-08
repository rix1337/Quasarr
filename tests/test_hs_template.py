# -*- coding: utf-8 -*-
"""HS runs on its bundled template: an RSS feed plus search and download hooks."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from quasarr.search.sources import templates
from quasarr.search.sources.helpers import custom_source
from quasarr.search.sources.templates import hs

HOST = "source.invalid"
FEED = f"""<?xml version="1.0"?><rss><channel>
<item><title>Movie A 2026 German DL 1080p BluRay x264-GRP</title><link>https://{HOST}/filme/movie-a/</link>
<pubDate>Mon, 26 Jan 2026 18:53:59 +0000</pubDate></item>
<item><title>Show.S01.German.DL.1080p.WEB.x264-GRP</title><link>https://{HOST}/serien/show/</link>
<pubDate>Sun, 25 Jan 2026 10:00:00 +0000</pubDate></item>
</channel></rss>"""
SEARCH = f"""<html><body><article class="post-1">
<a href="https://{HOST}/serien/show/">Show S01 German DL 1080p WEB x264-GRP</a>
<p>05.07.25, 17:23</p><p>Größe: 40883 MB</p>
<a href="https://www.imdb.com/title/tt7654321/">IMDb</a></article></body></html>"""
RELEASE = """<html><body>
<a href="https://aff.invalid/af.php?v=ddlto">aff</a><a href="https://filecrypt.cc/Container/AAA.html">Download</a>
<a href="https://filecrypt.cc/Container/BBB.html">Rapidgator Mirror</a>
<a href="https://filecrypt.cc/Container/CCC.html">Download</a>
</body></html>"""


def link(_state, title, url, size_mb, password, imdb_id, key):
    return json.dumps([title, url, size_mb, password, imdb_id, key])


class HSTemplateTests(unittest.TestCase):
    def setUp(self):
        self.state = SimpleNamespace(
            values={"user_agent": "UA/1.0", "config": lambda _s: {"hs": HOST}}
        )
        for patcher in (
            patch("quasarr.providers.shared_state.values", self.state.values),
            patch("quasarr.providers.utils.generate_download_link", side_effect=link),
            patch.object(hs, "generate_download_link", side_effect=link),
            patch.object(custom_source, "mark_hostname_issue"),
            patch.object(custom_source, "clear_hostname_issue"),
            patch.object(hs, "mark_hostname_issue"),
            patch.object(hs, "clear_hostname_issue"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.source = templates._load("hs")

    def test_capabilities_match_the_old_module(self):
        self.assertEqual("de", self.source.language)
        self.assertEqual([2000, 5000], self.source.supported_categories)
        self.assertTrue(self.source.supports_imdb)
        self.assertFalse(self.source.supports_phrase)

    def test_feed_reads_the_rss_titles_with_dots(self):
        with patch.object(
            custom_source,
            "fetch_markup",
            return_value=custom_source.FetchResult(FEED, None, 200),
        ) as fetch:
            releases = self.source.feed(self.state, 0, 2000)
        self.assertEqual(f"https://{HOST}/feed/", fetch.call_args.args[1])
        self.assertEqual(
            [
                (
                    "Movie.A.2026.German.DL.1080p.BluRay.x264-GRP",
                    f"https://{HOST}/filme/movie-a/",
                    0,
                    "Mon, 26 Jan 2026 18:53:59 +0000",
                ),
                (
                    "Show.S01.German.DL.1080p.WEB.x264-GRP",
                    f"https://{HOST}/serien/show/",
                    0,
                    "Sun, 25 Jan 2026 10:00:00 +0000",
                ),
            ],
            [
                (
                    r["details"]["title"],
                    r["details"]["source"],
                    r["details"]["size"],
                    r["details"]["date"],
                )
                for r in releases
            ],
        )

    def test_search_hook_reads_season_packs(self):
        response = MagicMock(content=SEARCH.encode(), status_code=200)
        with patch.object(hs.requests, "get", return_value=response) as get:
            releases = self.source.search(self.state, 0, 5000, "tt7654321", 1)
        self.assertIn("?s=tt7654321&asp_active=1", get.call_args.args[0])
        self.assertEqual(
            [
                (
                    "Show.S01.German.DL.1080p.WEB.x264-GRP",
                    40883,
                    "tt7654321",
                    "Sat, 05 Jul 2025 17:23:00 +0000",
                )
            ],
            [
                (
                    r["details"]["title"],
                    r["details"]["size"] // (1024 * 1024),
                    r["details"]["imdb_id"],
                    r["details"]["date"],
                )
                for r in releases
            ],
        )

    def test_download_hook_names_mirrors_from_labels_and_affiliates(self):
        response = MagicMock(text=RELEASE, status_code=200)
        with patch.object(hs.requests, "get", return_value=response):
            result = self.source.get_download_links(
                self.state, f"https://{HOST}/r/", [], "t", ""
            )
        self.assertEqual(
            {
                "links": [
                    ["https://filecrypt.cc/Container/AAA.html", "ddownload"],
                    ["https://filecrypt.cc/Container/BBB.html", "rapidgator"],
                    ["https://filecrypt.cc/Container/CCC.html", "filecrypt"],
                ]
            },
            result,
        )


if __name__ == "__main__":
    unittest.main()
