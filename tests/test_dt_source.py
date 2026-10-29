# -*- coding: utf-8 -*-

import unittest
from unittest.mock import MagicMock, patch

from bs4 import BeautifulSoup

from quasarr.downloads.sources import dt
from quasarr.search.sources.dt import _parse_published_datetime


def _response(html):
    response = MagicMock()
    response.text = html
    return response


class DtDownloadLinksTests(unittest.TestCase):
    def _get_links(self, html):
        shared_state = MagicMock()
        shared_state.values = {"user_agent": "test-agent"}
        session = MagicMock()
        session.get.return_value = _response(html)
        with (
            patch.object(dt.requests, "Session", return_value=session),
            patch.object(dt, "clear_hostname_issue"),
            patch.object(dt, "mark_hostname_issue"),
        ):
            return dt.Source().get_download_links(
                shared_state,
                "https://source.invalid/post.html",
                None,
                "Example.Show.S01E01.1080p.WEB.h264-GROUP",
                "source.invalid",
            )

    def test_finds_story_body_outside_article(self):
        result = self._get_links(
            """
            <article><div class="h1 dt-flexible-title">Example</div></article>
            <section><div class="card-body"><div class="full-story-body">
                <a href="https://rapidgator.invalid/file/one">one</a>
                <a href="https://www.imdb.com/title/tt0000001/">imdb</a>
            </div></div></section>
            """
        )

        self.assertEqual(
            {"links": [["https://rapidgator.invalid/file/one", "rapidgator"]]},
            result,
        )

    def test_finds_story_body_inside_article(self):
        result = self._get_links(
            """
            <article><div class="full-story-body">
                <a href="https://ddownload.invalid/file/two">two</a>
            </div></article>
            """
        )

        self.assertEqual(
            {"links": [["https://ddownload.invalid/file/two", "ddownload"]]},
            result,
        )


class DtPublishedDateTests(unittest.TestCase):
    def _parse(self, html):
        article = BeautifulSoup(html, "html.parser").find("article")
        return _parse_published_datetime(article)

    def test_parses_feed_listing_date(self):
        self.assertEqual(
            "2026-10-29T07:47:00+01:00",
            self._parse(
                """
                <article>
                    <span>Today, 07:47</span>
                    <span>29.10.2026 07:47</span>
                </article>
                """
            ),
        )

    def test_parses_search_calendar_block(self):
        self.assertEqual(
            "2026-10-24T14:39:00+01:00",
            self._parse(
                """
                <article>
                    <small class="dt-fs-11">Oct</small>
                    <h4 class="m-0">24</h4>
                    <h6 class="m-0">2026</h6>
                    <span><i class="bi bi-clock"></i>14:39</span>
                </article>
                """
            ),
        )


if __name__ == "__main__":
    unittest.main()
