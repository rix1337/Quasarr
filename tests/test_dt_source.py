# -*- coding: utf-8 -*-

import unittest
from unittest.mock import MagicMock, patch

from bs4 import BeautifulSoup

from quasarr.constants import SEARCH_CAT_BOOKS
from quasarr.downloads.sources import dt
from quasarr.search.sources.dt import Source as DtSearchSource
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

    def test_parses_feed_listing_date_without_zero_padding(self):
        self.assertEqual(
            "2026-11-02T12:49:00+01:00",
            self._parse(
                """
                <article>
                    <span>Today, 12:49</span>
                    <span>2.11.2026 12:49</span>
                </article>
                """
            ),
        )

    def test_returns_none_without_any_date(self):
        self.assertIsNone(self._parse("<article><span>Promo</span></article>"))

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


class DtBooksSearchTests(unittest.TestCase):
    def test_books_search_queries_subcategories_and_skips_rules_article(self):
        shared_state = MagicMock()
        config = MagicMock()
        config.get.return_value = "source.invalid"
        shared_state.values = {
            "config": MagicMock(return_value=config),
            "user_agent": "test-agent",
            "internal_address": "http://127.0.0.1:8080",
            "api_key": "secret",
        }
        response = MagicMock()
        response.content = b"""
        <article>
            <h1 class="font-weight-bold"><a href="https://source.invalid/rules.html">Article Posting Rules</a></h1>
            <div class="static-content-body">Pinned rules</div>
        </article>
        <article>
            <h1 class="font-weight-bold"><a href="https://source.invalid/book1.html">Example Magazine - November 2026</a></h1>
            <div class="dt-text-clamp">English | 100 pages | 45 MB</div>
            <span>29.10.2026 07:47</span>
        </article>
        """
        with (
            patch(
                "quasarr.search.sources.dt.requests.get", return_value=response
            ) as get_mock,
            patch(
                "quasarr.search.sources.dt.generate_download_link",
                return_value="http://127.0.0.1:8080/download/?payload=stub",
            ),
            patch("quasarr.search.sources.dt.clear_hostname_issue"),
            patch("quasarr.search.sources.dt.mark_hostname_issue") as mark_mock,
        ):
            releases = DtSearchSource().search(
                shared_state, 0.0, SEARCH_CAT_BOOKS, "Example Magazine"
            )

        called_url = get_mock.call_args[0][0]
        for cid in ("100", "4", "35", "109"):
            self.assertIn(f"catlist%5B%5D={cid}", called_url)
        mark_mock.assert_not_called()
        self.assertEqual(1, len(releases))
        self.assertEqual(
            "https://source.invalid/book1.html", releases[0]["details"]["source"]
        )


if __name__ == "__main__":
    unittest.main()
