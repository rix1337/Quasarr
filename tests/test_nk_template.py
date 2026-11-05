# -*- coding: utf-8 -*-
"""NK runs on its bundled template: feed and search are one POST form."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from quasarr.search.sources import templates
from quasarr.search.sources.helpers import custom_source

HOST = "source.invalid"


def result(name, slug, imdb="", size="21,6 GB", password="source.invalid"):
    imdb_link = (
        f'<a class="imdb" href="https://www.imdb.com/title/{imdb}/">IMDb</a>'
        if imdb
        else ""
    )
    return f"""<div class="article-right">
      <h2><a class="release-details" href="/release/1/{slug}">Name (2026)</a></h2>
      <span class="subtitle uk-visible-large">{name}</span>
      <p class="meta"><span>02.11.2026</span> <span>13:05 Uhr</span></p>
      <ul class="release-infos"><li><span>Größe</span> {size}</li><li><span>Format</span> MKV</li></ul>
      <p class="mirrors"><strong>Passwort:</strong> {password} <a href="#">copy</a></p>
      {imdb_link}</div>"""


PAGE = (
    "<html><body>"
    + "".join(
        [
            result(
                "Movie.A.1987.German.DL.2160p.UHD.BluRay.HEVC-GRP", "a", "tt0093058"
            ),
            result("Movie.B.1987.German.DL.1080p.BluRay.x264-GRP", "b", "tt7777777"),
            result("Show.S01E02.German.DL.1080p.WEB.h264-GRP", "c", password=""),
        ]
    )
    + "</body></html>"
)


def link(_state, title, url, size_mb, password, imdb_id, key):
    return json.dumps([title, url, size_mb, password, imdb_id, key])


class NKTemplateTests(unittest.TestCase):
    def setUp(self):
        self.state = SimpleNamespace(
            values={"user_agent": "UA/1.0", "config": lambda _s: {"nk": HOST}}
        )
        self.posts = []

        def fetch(_state, url, _timeout, _solver, data=None):
            self.posts.append((url, data))
            return custom_source.FetchResult(PAGE, None, 200)

        for patcher in (
            patch("quasarr.providers.shared_state.values", self.state.values),
            patch("quasarr.providers.utils.generate_download_link", side_effect=link),
            patch(
                "quasarr.providers.imdb_metadata.get_localized_title",
                return_value="Name",
            ),
            patch("quasarr.providers.imdb_metadata.get_year", return_value="1987"),
            patch.object(custom_source, "fetch_markup", side_effect=fetch),
            patch.object(custom_source, "mark_hostname_issue"),
            patch.object(custom_source, "clear_hostname_issue"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.source = templates._load("nk")

    def test_capabilities_match_the_old_module(self):
        self.assertEqual("de", self.source.language)
        self.assertEqual([2000, 5000], self.source.supported_categories)
        self.assertTrue(self.source.supports_imdb)
        self.assertFalse(self.source.supports_phrase)

    def test_feed_is_an_empty_search_validated_per_category(self):
        movies = self.source.feed(self.state, 0, 2000)
        self.assertEqual([(f"https://{HOST}/search", {"search": ""})], self.posts)
        self.assertEqual(
            [
                (
                    "Movie.A.1987.German.DL.2160p.UHD.BluRay.HEVC-GRP",
                    22118,
                    "tt0093058",
                    HOST,
                ),
                (
                    "Movie.B.1987.German.DL.1080p.BluRay.x264-GRP",
                    22118,
                    "tt7777777",
                    HOST,
                ),
            ],
            [
                (
                    r["details"]["title"],
                    r["details"]["size"] // (1024 * 1024),
                    r["details"]["imdb_id"],
                    json.loads(r["details"]["link"])[3],
                )
                for r in movies
            ],
        )
        self.assertEqual(
            "Mon, 02 Nov 2026 13:05:00 +0000", movies[0]["details"]["date"]
        )
        shows = self.source.feed(self.state, 0, 5000)
        self.assertEqual(
            ["Show.S01E02.German.DL.1080p.WEB.h264-GRP"],
            [r["details"]["title"] for r in shows],
        )
        # an empty password label means no password
        self.assertEqual("", json.loads(shows[0]["details"]["link"])[3])

    def test_movie_search_names_the_year_and_drops_other_titles(self):
        releases = self.source.search(self.state, 0, 2000, "tt0093058")
        self.assertEqual(
            [(f"https://{HOST}/search", {"search": "Name 1987"})], self.posts
        )
        self.assertEqual(
            ["Movie.A.1987.German.DL.2160p.UHD.BluRay.HEVC-GRP"],
            [r["details"]["title"] for r in releases],
        )

    def test_episode_search_names_season_and_episode(self):
        releases = self.source.search(self.state, 0, 5000, "tt0000001", 1, 2)
        self.assertEqual(
            [(f"https://{HOST}/search", {"search": "Name S01E02"})], self.posts
        )
        self.assertEqual("tt0000001", releases[0]["details"]["imdb_id"])


if __name__ == "__main__":
    unittest.main()
