# -*- coding: utf-8 -*-

import unittest
from unittest.mock import MagicMock, patch

from bs4 import BeautifulSoup

from quasarr.constants import SEARCH_CAT_BOOKS
from quasarr.search.sources import templates
from quasarr.search.sources.helpers import custom_source


def _template():
    return templates._load("dt")


def _parse_published_datetime(article):
    listing = _template().spec["list"]
    return custom_source._typed_value(
        article,
        listing["date"],
        lambda raw, f: custom_source.parse_date(
            raw, f["format"], None, f["utc_offset"], f["require_time"]
        ),
    )


def _response(html):
    response = MagicMock()
    response.text = html
    return response


class DtDownloadLinksTests(unittest.TestCase):
    def _get_links(self, html):
        shared_state = MagicMock()
        shared_state.values = {
            "user_agent": "test-agent",
            "config": lambda _section: {"dt": "source.invalid"},
        }
        with (
            patch("quasarr.providers.shared_state.values", shared_state.values),
            patch.object(
                custom_source,
                "fetch_markup",
                return_value=custom_source.FetchResult(html, None, 200),
            ),
            patch.object(custom_source, "clear_hostname_issue"),
            patch.object(custom_source, "mark_hostname_issue"),
        ):
            return _template().get_download_links(
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
            "Thu, 29 Oct 2026 06:47:00 +0000",
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
            "Mon, 02 Nov 2026 11:49:00 +0000",
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
            "Sat, 24 Oct 2026 13:39:00 +0000",
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
        shared_state.values = {
            "config": lambda _section: {"dt": "source.invalid"},
            "user_agent": "test-agent",
        }
        page = """
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
            patch("quasarr.providers.shared_state.values", shared_state.values),
            patch.object(
                custom_source,
                "fetch_markup",
                return_value=custom_source.FetchResult(page, None, 200),
            ) as get_mock,
            patch(
                "quasarr.providers.utils.generate_download_link",
                return_value="http://127.0.0.1:8080/download/?payload=stub",
            ),
            patch.object(custom_source, "clear_hostname_issue"),
            patch.object(custom_source, "mark_hostname_issue") as mark_mock,
        ):
            releases = _template().search(
                shared_state, 0.0, SEARCH_CAT_BOOKS, "Example Magazine"
            )

        called_url = get_mock.call_args[0][1]
        for cid in ("100", "4", "35", "109"):
            self.assertIn(f"catlist%5B%5D={cid}", called_url)
        mark_mock.assert_not_called()
        self.assertEqual(1, len(releases))
        self.assertEqual(
            "https://source.invalid/book1.html", releases[0]["details"]["source"]
        )


class DtFeedTests(unittest.TestCase):
    def test_feed_titles_sizes_and_imdb(self):
        page = """
        <article><div class="h1 dt-flexible-title"><a href="https://source.invalid/a.html">Course - Name (2026)</a></div>
            <div class="dt-text-clamp">Video: 1080p | Size: 1,40 GB <a href="https://www.imdb.com/title/tt1234567/">x</a></div>
            <span><i class="bi bi-clock"></i> 5.11.2026 11:01</span></article>
        <article><div class="h1">LinkSnappy promo</div></article>
        """
        shared_state = MagicMock()
        shared_state.values = {
            "config": lambda _section: {"dt": "source.invalid"},
            "user_agent": "test-agent",
        }
        with (
            patch("quasarr.providers.shared_state.values", shared_state.values),
            patch.object(
                custom_source,
                "fetch_markup",
                return_value=custom_source.FetchResult(page, None, 200),
            ) as get_mock,
            patch("quasarr.providers.utils.generate_download_link", return_value="x"),
            patch.object(custom_source, "clear_hostname_issue"),
            patch.object(custom_source, "mark_hostname_issue"),
        ):
            releases = _template().feed(shared_state, 0.0, 2000)

        self.assertEqual(
            "https://source.invalid/media/videos/", get_mock.call_args[0][1]
        )
        details = releases[0]["details"]
        self.assertEqual("Course-Name.2026", details["title"])
        # "1,40 GB" is 1.4 GB, not 40 GB
        self.assertEqual(1433 * 1024 * 1024, details["size"])
        self.assertEqual("tt1234567", details["imdb_id"])
        self.assertEqual("Thu, 05 Nov 2026 10:01:00 +0000", details["date"])
        self.assertEqual(1, len(releases))


if __name__ == "__main__":
    unittest.main()
