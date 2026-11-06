# -*- coding: utf-8 -*-
"""FX runs on its bundled template; one post lists several releases."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from quasarr.search.sources import templates
from quasarr.search.sources.helpers import custom_source

HOST = "source.invalid"


def release(name, size, container, imdb=None):
    imdb_link = (
        f'<a href="https://www.imdb.com/title/{imdb}/">»7.7«</a> | ' if imdb else ""
    )
    return f"""<table><tbody><tr><td>
      <strong>Datum: </strong>06.11.2021<br/>
      <strong>Release: <a href="https://filecrypt.cc/Container/{container}.html">»{name}«</a></strong><br/>
      <strong>IMDB:</strong> {imdb_link}<strong>Size:</strong> {size}<br/>
    </td></tr></tbody></table>"""


POST = f"""<article id="post-1"><header><h2 class="entry-title">
  <a href="https://{HOST}/2026/01/05/show/">Show (1990–)</a></h2></header>
  <div class="entry-content">
  {release("Show.S01.German.AC3.DL 720p HDTVRip x265-GRP", "1 GB", "AAA", "tt0098844")}
  {release("Show.S02.German.AC3.DL 720p HDTVRip x265-GRP", "11,5 GB", "BBB")}
  {release("Show.S03.German.AC3.DL 720p HDTVRip x265-GRP", "14GL", "CCC")}
  </div>
  <footer><time class="entry-date published" datetime="2026-01-05T08:00:00+01:00"></time>
  <time class="updated" datetime="2026-01-05T08:55:17+01:00"></time></footer>
</article>"""
FRONT = f"<html><body>{POST}</body></html>"
SEARCH = f"""<html><body><article><h2 class="entry-title">
  <a href="https://{HOST}/2026/01/05/show/">Show</a></h2></article>
  <article><h2 class="entry-title"><a href="https://{HOST}/other/">Other</a></h2></article>
</body></html>"""
POST_PAGE = FRONT.replace(
    '<a href="https://source.invalid/2026/01/05/show/">Show (1990–)</a>', "Show (1990–)"
)


def link(_state, title, url, size_mb, password, imdb_id, key):
    return json.dumps([title, url, size_mb, password, imdb_id, key])


class FXTemplateTests(unittest.TestCase):
    def setUp(self):
        self.state = SimpleNamespace(
            values={"user_agent": "UA/1.0", "config": lambda _s: {"fx": HOST}}
        )
        self.urls = []

        def fetch(_state, url, *args, **kwargs):
            self.urls.append(url)
            page = {f"https://{HOST}/": FRONT, f"https://{HOST}/?s=tt0098844": SEARCH}
            return custom_source.FetchResult(page.get(url, POST_PAGE), None, 200)

        for patcher in (
            patch("quasarr.providers.shared_state.values", self.state.values),
            patch("quasarr.providers.utils.generate_download_link", side_effect=link),
            patch.object(custom_source, "fetch_markup", side_effect=fetch),
            patch.object(custom_source, "mark_hostname_issue"),
            patch.object(custom_source, "clear_hostname_issue"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.source = templates._load("fx")

    def rows(self, releases):
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

    def test_every_crypter_link_of_a_post_is_a_release(self):
        post = f"https://{HOST}/2026/01/05/show/"
        date = "Mon, 05 Jan 2026 07:55:17 +0000"
        self.assertEqual(
            [
                (
                    "Show.S01.German.AC3.DL.720p.HDTVRip.x265-GRP",
                    1024,
                    "tt0098844",
                    post,
                    date,
                ),
                # each release keeps its own size and falls back to the size and IMDb
                # link of its post, as the old module did
                (
                    "Show.S02.German.AC3.DL.720p.HDTVRip.x265-GRP",
                    11776,
                    "tt0098844",
                    post,
                    date,
                ),
                (
                    "Show.S03.German.AC3.DL.720p.HDTVRip.x265-GRP",
                    1024,
                    "tt0098844",
                    post,
                    date,
                ),
            ],
            self.rows(self.source.feed(self.state, 0, 5000)),
        )

    def test_payload_links_the_crypter_and_the_site_name(self):
        payload = json.loads(
            self.source.feed(self.state, 0, 2000)[0]["details"]["link"]
        )
        self.assertEqual("https://filecrypt.cc/Container/AAA.html", payload[1])
        self.assertEqual("source", payload[3])

    def test_search_opens_the_first_post_and_stamps_the_imdb_id(self):
        releases = self.source.search(self.state, 0, 5000, "tt0098844", 2)
        self.assertEqual(
            [f"https://{HOST}/?s=tt0098844", f"https://{HOST}/2026/01/05/show/"],
            self.urls,
        )
        self.assertEqual(
            [("Show.S02.German.AC3.DL.720p.HDTVRip.x265-GRP", 11776, "tt0098844")],
            [row[:3] for row in self.rows(releases)],
        )
        self.assertEqual(
            f"https://{HOST}/2026/01/05/show/", releases[0]["details"]["source"]
        )

    def test_grabs_go_straight_to_the_crypter(self):
        result = self.source.get_download_links(
            self.state, "https://filecrypt.cc/Container/AAA.html", [], "t", ""
        )
        self.assertEqual({"links": []}, result)
        self.assertEqual([], self.urls)


if __name__ == "__main__":
    unittest.main()
