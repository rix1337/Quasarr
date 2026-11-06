# -*- coding: utf-8 -*-
"""WD runs on its bundled template; links resolve through the download hook."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from quasarr.search.sources import templates
from quasarr.search.sources.helpers import custom_source

HOST = "source.invalid"


def row(name, size="4 GB", date="05.11.2026 - 13:04"):
    return f"""<tr class="lh-sm font-size-sm"><td>
      <a class="upload-link" href="/download/1/{name}"><div class="preview-text">{date}</div>
      <style>.x{{}}</style>{name}</a></td><td><span class="element-size">{size}</span></td></tr>"""


PAGE = (
    '<table class="table"><tbody>'
    + row("Some.Movie.2026.German.DL.1080p.BluRay.x264-GRP")
    + row("Some Magazine - November 2026", "40 MB")
    + row("Some.Movie.2026.German.DVDRip-GRP")
    + row("Broken.Row-GRP", size="")
    + "</tbody></table>"
)


class WDTemplateTests(unittest.TestCase):
    def setUp(self):
        self.state = SimpleNamespace(
            values={"user_agent": "UA/1.0", "config": lambda _s: {"wd": HOST}}
        )
        for patcher in (
            patch("quasarr.providers.shared_state.values", self.state.values),
            patch("quasarr.providers.utils.generate_download_link", return_value="x"),
            patch.object(
                custom_source,
                "fetch_markup",
                return_value=custom_source.FetchResult(PAGE, None, 200),
            ),
            patch.object(custom_source, "mark_hostname_issue"),
            patch.object(custom_source, "clear_hostname_issue"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.source = templates._load("wd")

    def test_capabilities_match_the_old_module(self):
        self.assertEqual([2000, 3000, 5000, 7000], self.source.supported_categories)
        self.assertTrue(self.source.requires_flaresolverr)
        self.assertTrue(self.source.supports_phrase)
        self.assertTrue(self.source.supports_date_numbering)

    def test_feed_names_exclude_the_upload_date(self):
        releases = self.source.feed(self.state, 0, 7000)
        self.assertEqual(
            [
                (
                    "Some.Movie.2026.German.DL.1080p.BluRay.x264-GRP",
                    "Thu, 05 Nov 2026 13:04:00 +0000",
                ),
                # the feed keeps magazine names as published
                ("Some Magazine - November 2026", "Thu, 05 Nov 2026 13:04:00 +0000"),
                (
                    "Some.Movie.2026.German.DVDRip-GRP",
                    "Thu, 05 Nov 2026 13:04:00 +0000",
                ),
            ],
            [(r["details"]["title"], r["details"]["date"]) for r in releases],
        )

    def test_book_search_skips_release_filters(self):
        movies = self.source.search(self.state, 0, 2000, "Some Movie")
        self.assertEqual(
            ["Some.Movie.2026.German.DL.1080p.BluRay.x264-GRP"],
            [r["details"]["title"] for r in movies],
        )
        books = self.source.search(self.state, 0, 7000, "Some Magazine")
        self.assertIn("Some Magazine - 2026 11", [r["details"]["title"] for r in books])


if __name__ == "__main__":
    unittest.main()
