# -*- coding: utf-8 -*-
"""MB runs on its bundled template; expectations were pinned from the old module."""

import json
import unittest
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from types import SimpleNamespace
from unittest.mock import patch

from quasarr.search.sources import templates
from quasarr.search.sources.helpers import custom_source

FEED = """<html><body>
<div class="post"><h1 id="post-1"><a href="https://source.invalid/movie-a/" title="Permanent Link to Movie.A.2026.German.DL.1080p.WEB.x264-GRP">Movie.A.2026.German.DL.1080p.WEB.x264-GRP</a></h1>
<p class="date_x">Donnerstag, 15. Januar 2026 17:06</p>
<div class="entry_x"><p>Plot.</p><div class="alt2"><div>[Size]……………..: 2.04 GB<br/>[Duration]: 01:48:14</div></div>
<a href="https://www.imdb.com/title/tt1234567/">IMDb</a></div></div>
<div class="post"><h1 id="post-2"><a href="https://source.invalid/show-b/">Show.B.S01.German.720p.WEB.x264-GRP</a></h1>
<p class="date_x">Mittwoch, 14. Januar 2026 09:30</p>
<div class="entry_x"><p>Größe: 700 MB</p><p>IMDb: tt7654321</p></div></div>
<div class="post"><h1 id="post-3"><a href="https://source.invalid/movie-c/">Movie C 2026 German 1080p</a></h1>
<p class="date_x">unbekannt</p><div class="entry_x"><p>no size</p></div></div>
<div class="post"><h1 id="post-4"><a href="https://source.invalid/movie-d/">Movie.D.2026.German.DVDRip-GRP</a></h1>
<p class="date_x">Dienstag, 13. Januar 2026 22:15</p><div class="entry_x"><p>Size: 1.4 GB</p></div></div>
<div class="post"><h1 id="post-5"><a href="https://source.invalid/movie-e/">Movie.E.2026.German.XXX.1080p.WEB.x264-GRP</a></h1>
<p class="date_x">Dienstag, 13. Januar 2026 21:15</p><div class="entry_x"><p>Size: 3 GB</p></div></div>
</body></html>"""
RELEASE = """<html><body><div class="entry_x">
<a href="https://filecrypt.cc/Container/ABC123.html">Rapidgator.net</a>
<a href="https://www.filecrypt.cc/Container/DEF456.html">DDownload.com</a>
<a href="https://source.invalid/proload">Premium</a>
<a href="https://filecrypt.cc/Folder/XYZ.html">Folder</a>
</div></body></html>"""


HOST = "source.invalid"


def link(_state, title, url, size_mb, password, imdb_id, key):
    return json.dumps([title, url, size_mb, password, imdb_id, key])


class MBTemplateTests(unittest.TestCase):
    def setUp(self):
        self.state = SimpleNamespace(
            values={"user_agent": "UA/1.0", "config": lambda _s: {"mb": HOST}}
        )
        self.urls = []

        def fetch(_state, url, *args, **kwargs):
            self.urls.append(url)
            page = RELEASE if "/release/" in url else FEED
            return custom_source.FetchResult(page, None, 200)

        for target, kwargs in (
            ("quasarr.providers.shared_state.values", {"new": self.state.values}),
            ("quasarr.providers.utils.generate_download_link", {"side_effect": link}),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, kwargs in (
            ("fetch_markup", {"side_effect": fetch}),
            ("mark_hostname_issue", {}),
            ("clear_hostname_issue", {}),
        ):
            patcher = patch.object(custom_source, name, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.source = templates._load("mb")

    def details(self, releases):
        return [
            (
                r["details"]["title"],
                r["details"]["size"] // (1024 * 1024),
                r["details"]["imdb_id"],
                r["details"]["source"],
                r["details"]["date"],
            )
            for r in releases
        ]

    def test_capabilities_match_the_old_module(self):
        self.assertEqual("de", self.source.language)
        self.assertEqual([2000, 5000], self.source.supported_categories)
        self.assertTrue(self.source.supports_imdb)
        self.assertFalse(self.source.supports_phrase)
        self.assertFalse(self.source.supports_date_numbering)
        self.assertFalse(self.source.requires_login)

    def test_feed_paths_per_category(self):
        self.source.feed(self.state, 0, 2000)
        self.source.feed(self.state, 0, 5000)
        self.assertEqual(
            [
                f"https://{HOST}/category/neuerscheinungen/",
                f"https://{HOST}/category/serie/",
            ],
            self.urls,
        )

    def test_feed_keeps_every_post_as_published(self):
        rows = self.details(self.source.feed(self.state, 0, 2000))
        self.assertEqual(
            [
                (
                    "Movie.A.2026.German.DL.1080p.WEB.x264-GRP",
                    2088,
                    "tt1234567",
                    f"https://{HOST}/movie-a/",
                    "Thu, 15 Jan 2026 17:06:00 +0000",
                ),
                (
                    "Show.B.S01.German.720p.WEB.x264-GRP",
                    700,
                    # a bare ID in the text is no IMDb link, as before
                    None,
                    f"https://{HOST}/show-b/",
                    "Wed, 14 Jan 2026 09:30:00 +0000",
                ),
            ],
            rows[:2],
        )
        # raw titles: spaces and missing quality tags stay in the feed
        self.assertEqual("Movie C 2026 German 1080p", rows[2][0])
        self.assertEqual(0, rows[2][1])
        self.assertEqual(5, len(rows))

    def test_undated_posts_are_an_hour_old(self):
        date = parsedate_to_datetime(
            self.details(self.source.feed(self.state, 0, 2000))[2][4]
        )
        age = datetime.now(timezone.utc) - date
        self.assertAlmostEqual(3600, age.total_seconds(), delta=60)

    def test_payload_carries_the_hostname_as_password(self):
        payload = json.loads(
            self.source.feed(self.state, 0, 2000)[0]["details"]["link"]
        )
        self.assertEqual(
            [
                "Movie.A.2026.German.DL.1080p.WEB.x264-GRP",
                f"https://{HOST}/movie-a/",
                2088,
                HOST,
                "tt1234567",
                "mb",
            ],
            payload,
        )

    def test_search_uses_the_imdb_id_and_filters_releases(self):
        releases = self.source.search(self.state, 0, 2000, "tt1234567")
        self.assertEqual(
            f"https://{HOST}/?s=tt1234567&id=20&post_type=post", self.urls[0]
        )
        # spaces, missing quality tags and unrequested XXX releases are dropped
        self.assertEqual(
            ["Movie.A.2026.German.DL.1080p.WEB.x264-GRP"],
            [r["details"]["title"] for r in releases],
        )
        tv = self.source.search(self.state, 0, 5000, "tt7654321")
        self.assertEqual(
            ["Show.B.S01.German.720p.WEB.x264-GRP"], [r["details"]["title"] for r in tv]
        )

    def test_download_collects_filecrypt_containers(self):
        url = f"https://{HOST}/release/"
        self.assertEqual(
            {
                "links": [
                    ["https://filecrypt.cc/Container/ABC123.html", "rapidgator.net"],
                    ["https://www.filecrypt.cc/Container/DEF456.html", "ddownload.com"],
                ]
            },
            self.source.get_download_links(self.state, url, [], "t", ""),
        )
        self.assertEqual(
            {
                "links": [
                    ["https://filecrypt.cc/Container/ABC123.html", "rapidgator.net"]
                ]
            },
            self.source.get_download_links(self.state, url, ["rapidgator"], "t", ""),
        )
        self.assertEqual(
            {"links": []},
            self.source.get_download_links(self.state, url, ["katfile"], "t", ""),
        )


if __name__ == "__main__":
    unittest.main()
