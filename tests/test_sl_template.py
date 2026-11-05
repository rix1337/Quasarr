# -*- coding: utf-8 -*-
"""SL runs on its bundled template; feed expectations were pinned from the old module."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from quasarr.search.sources import templates
from quasarr.search.sources.helpers import custom_source

FEED = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Site</title>
<item><title>Movie.A.2026.1080p.WEB.H264-GRP</title><link>https://source.invalid/movies/movie-a/</link>
<pubDate>Thu, 15 Jan 2026 08:15:24 +0000</pubDate>
<description><![CDATA[<p>Size: 5.25 GB</p><p><a href="https://www.imdb.com/title/tt1234567/">IMDb</a></p>]]></description></item>
<item><title>Small.Book.2026.ePub-GRP</title><link>https://source.invalid/ebooks/small-book/</link>
<pubDate>Thu, 15 Jan 2026 07:00:00 +0000</pubDate>
<description><![CDATA[<p>Size: 350 KB</p>]]></description></item>
<item><title>No.Size.2026.1080p.WEB.H264-GRP</title><link>https://source.invalid/movies/no-size/</link>
<pubDate>Thu, 15 Jan 2026 06:00:00 +0000</pubDate><description><![CDATA[<p>nothing</p>]]></description></item>
<item><title>Some.Magazine.04.2026.GERMAN.MAGAZINE.eBook-GRP</title><link>https://source.invalid/ebooks/mag/</link>
<pubDate>Wed, 14 Jan 2026 22:00:00 +0000</pubDate><description><![CDATA[Size: 40 MB]]></description></item>
</channel></rss>"""

SEARCH = """<html><body><ul>
<li class="row"><div class="row-body"><div class="title">
<a href="https://source.invalid/tv-shows/show-s01e02/"><span class="title-start">Show.S01E02.1080p.WEB.H264-GRP</span></a></div>
<div class="meta"><span class="m"><span class="date-short"><span class="localtime" data-lttime="2026-01-10T08:25:24+00:00">10 Jan 2026</span></span></span>
<span class="m size">1.02 GB</span><span class="m grp"><a href="https://source.invalid/group/GRP/">GRP</a></span></div></div></li>
<li class="row"><div class="row-body"><div class="title">
<a href="https://source.invalid/tv-shows/show-s01e03/"><span class="title-start">Show.S01E03.1080p.WEB.H264-GRP</span></a></div>
<div class="meta"><span class="m size">1.1 GB</span></div></div></li>
<li class="row"><div class="row-body"><div class="title">
<a href="https://source.invalid/tv-shows/other/"><span class="title-start">Other.S01E02.1080p.WEB.H264-GRP</span></a></div></div></li>
</ul></body></html>"""

RELEASE = """<html><body><a href="https://www.imdb.com/title/tt7654321/">IMDb</a>
<p class="postmetadata"><h2>Info</h2><p><a href="https://ddownload.com/early/info.rar">early</a></p>
<h2>Download</h2>
<p><a href="https://nitroflare.com/view/AAA/Show.rar">https://nitroflare.com/view/AAA/Show.rar</a></p>
<p><a href="https://ddownload.com/bbb/Show.rar">https://ddownload.com/bbb/Show.rar</a></p>
<p><a href="https://multiup.io/download/ccc/Show.rar">multiup</a></p>
<h2>Comments</h2><p><a href="https://ddownload.com/later/other.rar">later</a></p>
</p></body></html>"""

HOST = "source.invalid"


def link(_state, title, url, size_mb, password, imdb_id, key):
    return json.dumps([title, url, size_mb, password, imdb_id, key])


class SLTemplateTests(unittest.TestCase):
    def setUp(self):
        self.state = SimpleNamespace(
            values={"user_agent": "UA/1.0", "config": lambda _s: {"sl": HOST}}
        )
        self.urls = []

        def fetch(_state, url, *args, **kwargs):
            self.urls.append(url)
            if url.endswith("/feed/"):
                page = FEED
            elif "?s=" in url:
                page = SEARCH
            else:
                page = RELEASE
            return custom_source.FetchResult(page, None, 200)

        patches = [
            patch("quasarr.providers.shared_state.values", self.state.values),
            patch("quasarr.providers.utils.generate_download_link", side_effect=link),
            patch(
                "quasarr.providers.imdb_metadata.get_localized_title",
                return_value="Show &amp; Co",
            ),
            patch.object(custom_source, "fetch_markup", side_effect=fetch),
            patch.object(custom_source, "mark_hostname_issue"),
            patch.object(custom_source, "clear_hostname_issue"),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.source = templates._load("sl")

    def test_capabilities_match_the_old_module(self):
        self.assertEqual("en", self.source.language)
        self.assertEqual(
            [2000, 3000, 5000, 5070, 7000], self.source.supported_categories
        )
        self.assertTrue(self.source.requires_flaresolverr)
        self.assertTrue(self.source.supports_imdb)
        self.assertTrue(self.source.supports_phrase)
        self.assertTrue(self.source.supports_date_numbering)

    def test_feed_reads_size_date_and_imdb_from_rss(self):
        releases = self.source.feed(self.state, 0, 2000)
        self.assertEqual([f"https://{HOST}/movies/feed/"], self.urls)
        self.assertEqual(
            [
                (
                    "Movie.A.2026.1080p.WEB.H264-GRP",
                    5376,
                    "tt1234567",
                    "Thu, 15 Jan 2026 08:15:24 +0000",
                ),
                (
                    "Small.Book.2026.ePub-GRP",
                    0,
                    None,
                    "Thu, 15 Jan 2026 07:00:00 +0000",
                ),
                (
                    "Some.Magazine.04.2026.GERMAN.MAGAZINE.eBook-GRP",
                    40,
                    None,
                    "Wed, 14 Jan 2026 22:00:00 +0000",
                ),
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
        payload = json.loads(releases[0]["details"]["link"])
        self.assertEqual(HOST, payload[3])

    def test_feed_paths_per_category(self):
        for category in (7000, 3000, 5000):
            self.source.feed(self.state, 0, category)
        self.assertEqual(
            [
                f"https://{HOST}/ebooks/feed/",
                f"https://{HOST}/music/feed/",
                f"https://{HOST}/tv-shows/feed/",
            ],
            self.urls,
        )

    def test_series_search_covers_the_foreign_section_and_matches_the_title(self):
        with patch(
            "quasarr.providers.imdb_metadata.get_localized_title", return_value="Show"
        ):
            releases = self.source.search(self.state, 0, 5000, "tt7654321", 1, 2)
        self.assertEqual(
            {f"https://{HOST}/tv-shows/?s=Show", f"https://{HOST}/foreign/?s=Show"},
            set(self.urls),
        )
        # both sections list the episode once; other titles and episodes drop
        self.assertEqual(
            [
                (
                    "Show.S01E02.1080p.WEB.H264-GRP",
                    1044,
                    "tt7654321",
                    "Sat, 10 Jan 2026 08:25:24 +0000",
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

    def test_localized_titles_are_unescaped(self):
        self.source.search(self.state, 0, 2000, "tt7654321")
        self.assertEqual([f"https://{HOST}/movies/?s=Show+%26+Co"], self.urls)

    def test_download_takes_supported_hosters_of_the_download_section(self):
        result = self.source.get_download_links(
            self.state, f"https://{HOST}/r/", [], "t", ""
        )
        self.assertEqual(
            {
                "links": [
                    ["https://nitroflare.com/view/AAA/Show.rar", "nitroflare"],
                    ["https://ddownload.com/bbb/Show.rar", "ddownload"],
                ],
                "imdb_id": "tt7654321",
            },
            result,
        )
        only = self.source.get_download_links(
            self.state, f"https://{HOST}/r/", ["ddownload"], "t", ""
        )
        self.assertEqual(
            [["https://ddownload.com/bbb/Show.rar", "ddownload"]], only["links"]
        )


if __name__ == "__main__":
    unittest.main()
