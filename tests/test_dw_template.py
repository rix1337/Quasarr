# -*- coding: utf-8 -*-
"""DW runs on its bundled template; links are resolved by the download hook."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from quasarr.search.sources import templates
from quasarr.search.sources.helpers import custom_source

HOST = "source.invalid"


def post(name, size, imdb="", date="5. November 2026 / 06:48"):
    return f"""<article class="post"><div class="blogpage_content"><div class="title-area">
      <h4><a href="https://{HOST}/video/filme/{name.lower()}/" title="{name}">{name}</a>
      <div class="thumbnfo"><div class="thumb_s"><span>{size}</span><span> | </span><span>102 Min</span></div>
      <a href="https://{HOST}/video/filme/{name.lower()}/"></a></div>{imdb}</h4>
      <div><ul class="search-meta"><li><span class="date updated">{date}</span></li></ul></div>
    </div></div></article>"""


FEED = (
    "<html><body>"
    + "".join(
        [
            post(
                "Movie.A.2026.GERMAN.1080p.WEB.x265-GRP",
                "1258 MB",
                '<i data-id="tt1234567"></i>',
            ),
            post("Movie.B.2026.GERMAN.1080p.WEB.x265-GRP", "MB"),
            post("Movie.C.2026.GERMAN.1080p.WEB.x265-GRP", "1.5 GB", date="kaputt"),
        ]
    )
    + "</body></html>"
)

RELEASE = """<html><body>
<button class="show_link" value="11"></button><span><img src="/img/fichier.png"></span>
<button class="show_link" value="22"></button><span><img src="/img/rapidgator.png"></span>
</body></html>"""


def link(_state, title, url, size_mb, password, imdb_id, key):
    return json.dumps([title, url, size_mb, password, imdb_id, key])


class DWTemplateTests(unittest.TestCase):
    def setUp(self):
        self.state = SimpleNamespace(
            values={"user_agent": "UA/1.0", "config": lambda _s: {"dw": HOST}}
        )
        self.urls = []

        def fetch(_state, url, *args, **kwargs):
            self.urls.append(url)
            return custom_source.FetchResult(FEED, None, 200)

        for patcher in (
            patch("quasarr.providers.shared_state.values", self.state.values),
            patch("quasarr.providers.utils.generate_download_link", side_effect=link),
            patch.object(custom_source, "fetch_markup", side_effect=fetch),
            patch.object(custom_source, "mark_hostname_issue"),
            patch.object(custom_source, "clear_hostname_issue"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.source = templates._load("dw")

    def test_capabilities_match_the_old_module(self):
        self.assertEqual("de", self.source.language)
        self.assertEqual([2000, 5000], self.source.supported_categories)
        self.assertTrue(self.source.supports_imdb)
        self.assertFalse(self.source.supports_phrase)

    def test_feed_reads_heading_posts(self):
        releases = self.source.feed(self.state, 0, 2000)
        self.assertEqual([f"https://{HOST}/videos/filme/"], self.urls)
        self.assertEqual(
            [
                (
                    "Movie.A.2026.GERMAN.1080p.WEB.x265-GRP",
                    1258,
                    "tt1234567",
                    "Thu, 05 Nov 2026 06:48:00 +0000",
                ),
                # a size without its number is unknown, not a broken post
                (
                    "Movie.B.2026.GERMAN.1080p.WEB.x265-GRP",
                    0,
                    None,
                    "Thu, 05 Nov 2026 06:48:00 +0000",
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

    def test_search_per_category_section(self):
        self.source.search(self.state, 0, 5000, "tt1234567")
        self.assertEqual(
            [f"https://{HOST}/?s=tt1234567&videocategory=serien"], self.urls
        )

    def test_download_resolves_the_link_buttons(self):
        session = MagicMock()
        session.get.return_value = MagicMock(text=RELEASE)
        session.post.side_effect = [
            MagicMock(
                json=lambda: {"data": f"https://{HOST}/azn/af.php?v=ABC123#m1,x"}
            ),
            MagicMock(json=lambda: {"data": f"https://{HOST}/azn/af.php?v=DEF456,x"}),
        ]
        with (
            patch("requests.Session", return_value=session),
            patch("quasarr.search.sources.templates.dw.clear_hostname_issue"),
        ):
            result = self.source.get_download_links(
                self.state,
                f"https://{HOST}/video/filme/a/",
                ["rapidgator", "1fichier"],
                "t",
                "",
            )
        self.assertEqual(
            {
                "links": [
                    ["https://filecrypt.cc/Container/ABC123.html#m1", "1fichier"],
                    ["https://filecrypt.cc/Container/DEF456.html", "rapidgator"],
                ]
            },
            result,
        )
        self.assertEqual(
            f"https://{HOST}/wp-admin/admin-ajax.php", session.post.call_args.args[0]
        )


if __name__ == "__main__":
    unittest.main()
