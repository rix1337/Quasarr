# -*- coding: utf-8 -*-

import unittest
from datetime import datetime
from unittest.mock import patch

from bs4 import BeautifulSoup

from quasarr.constants import SEARCH_CAT_BOOKS
from quasarr.downloads.sources.dl import Source as DownloadSource
from quasarr.search.sources.dl import (
    Source as SearchSource,
)
from quasarr.search.sources.dl import (
    _date_release_from_thread,
    _expand_jahresthema_thread_releases,
    _is_current_year_jahresthema_thread,
    _post_contains_supported_download,
    _release_from_jahresthema_post,
    _should_check_thread_for_date_release,
)


class FakeResponse:
    def __init__(self, text, url="https://www.source.invalid/", status_code=200):
        self.text = text
        self.content = text.encode("utf-8")
        self.url = url
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")


class FakeSharedState:
    def __init__(self):
        self.values = {
            "internal_address": "http://internal.invalid",
            "config": self.config,
        }

    def config(self, section):
        if section == "Hostnames":
            return {"dl": "source.invalid"}
        return {}


class DlJahresthemaSearchTests(unittest.TestCase):
    def test_date_thread_candidate_uses_search_tokens_without_release_group_lock(self):
        self.assertTrue(
            _should_check_thread_for_date_release(
                "Sample Show 2026 Collection",
                "Sample Show",
                2026,
            )
        )

    def test_date_thread_candidate_rejects_unrelated_series(self):
        self.assertFalse(
            _should_check_thread_for_date_release(
                "Other Show 2026 Collection",
                "Sample Show",
                2026,
            )
        )

    def test_date_release_from_thread_uses_post_url_only_for_downloadable_post(self):
        html = """
        <article class="message--post" id="post-1">
          <div class="bbWrapper">
            <p>Title: Sample.Show.2026.06.19.1080p.WEB.h264-GRP</p>
            <p>Metadata only.</p>
          </div>
        </article>
        <article class="message--post" id="post-2">
          <div class="bbWrapper">
            <p>Title: Sample.Show.2026.06.19.1080p.WEB.h264-GRP</p>
            <p>https://ddownload.com/example</p>
          </div>
        </article>
        """

        with patch(
            "quasarr.search.sources.dl._fetch_thread_page",
            return_value=FakeResponse(html, "https://www.source.invalid/thread.1/"),
        ):
            release = _date_release_from_thread(
                FakeSharedState(),
                "https://www.source.invalid/thread.1/",
                "Sample Show",
                2026,
                6,
                19,
            )

        self.assertEqual(
            "https://www.source.invalid/thread.1/",
            release["source"],
        )

    def test_date_release_from_thread_pins_downloadable_post(self):
        html = """
        <article class="message--post" id="post-2">
          <div class="bbWrapper">
            <p>Title: Sample.Show.2026.06.19.1080p.WEB.h264-GRP</p>
            <p>https://ddownload.com/example</p>
          </div>
        </article>
        """

        with patch(
            "quasarr.search.sources.dl._fetch_thread_page",
            return_value=FakeResponse(html, "https://www.source.invalid/thread.1/"),
        ):
            release = _date_release_from_thread(
                FakeSharedState(),
                "https://www.source.invalid/thread.1/",
                "Sample Show",
                2026,
                6,
                19,
            )

        self.assertEqual(
            "https://www.source.invalid/thread.1/#post-2",
            release["source"],
        )

    def test_date_release_from_thread_scans_recent_thread_pages(self):
        first_page_html = """
        <html>
          <a class="pageNav-page" href="/threads/sample-show-2026.1/page-2">2</a>
          <article class="message--post" id="post-1">
            <div class="bbWrapper">
              <p>Title: Sample.Show.2026.06.12.1080p.WEB.h264-GRP</p>
              <p>https://ddownload.com/old-example</p>
            </div>
          </article>
        </html>
        """
        second_page_html = """
        <article class="message--post" id="post-2">
          <div class="bbWrapper">
            <p>Title: Sample.Show.2026.06.19.1080p.WEB.h264-GRP</p>
            <p>https://ddownload.com/example</p>
          </div>
        </article>
        """
        fetched_thread_urls = []

        def fake_fetch(_shared_state, page_url):
            fetched_thread_urls.append(page_url)
            if page_url.endswith("/thread.1/"):
                return FakeResponse(first_page_html, page_url)
            if page_url.endswith("/thread.1/page-2"):
                return FakeResponse(second_page_html, page_url)
            raise AssertionError(f"unexpected fetch: {page_url}")

        with patch("quasarr.search.sources.dl._fetch_thread_page", fake_fetch):
            release = _date_release_from_thread(
                FakeSharedState(),
                "https://www.source.invalid/thread.1/",
                "Sample Show",
                2026,
                6,
                19,
            )

        self.assertEqual(
            [
                "https://www.source.invalid/thread.1/",
                "https://www.source.invalid/thread.1/page-2",
            ],
            fetched_thread_urls,
        )
        self.assertEqual(
            "https://www.source.invalid/thread.1/page-2#post-2",
            release["source"],
        )

    def test_matches_compact_ct_style_spelling(self):
        current_year = datetime.now().year

        self.assertTrue(
            _is_current_year_jahresthema_thread(
                f"C T Sample Jahresthema {current_year}",
                "ct",
                SEARCH_CAT_BOOKS,
            )
        )

    def test_matches_common_magazine_title_shapes(self):
        current_year = datetime.now().year

        cases = [
            (
                f"The Sample News Magazine Jahresthema {current_year}",
                "Sample News",
            ),
            (
                f"Singleword Magazine Jahresthema {current_year}",
                "Singleword",
            ),
            (
                f"PC Sample Magazine Jahresthema {current_year}",
                "PC Sample",
            ),
        ]

        for thread_title, search_string in cases:
            with self.subTest(search_string=search_string):
                self.assertTrue(
                    _is_current_year_jahresthema_thread(
                        thread_title,
                        search_string,
                        SEARCH_CAT_BOOKS,
                    )
                )

    def test_does_not_match_partial_magazine_title(self):
        current_year = datetime.now().year

        self.assertFalse(
            _is_current_year_jahresthema_thread(
                f"PC Different Magazine Jahresthema {current_year}",
                "PC Sample",
                SEARCH_CAT_BOOKS,
            )
        )

    def test_expands_only_current_year_jahresthema_last_five_pages(self):
        current_year = datetime.now().year
        previous_year = current_year - 1
        fetched_thread_urls = []

        search_html = f"""
            <html>
                <li class="block-row">
                    <h3 class="contentRow-title">
                        <a href="/threads/sample-magazine-issue-001.1/">Sample Magazine Issue 001</a>
                    </h3>
                    <time class="u-dt" datetime="{current_year}-01-01T10:00:00+0100"></time>
                </li>
                <li class="block-row">
                    <h3 class="contentRow-title">
                        <a href="/threads/sample-magazine-jahresthema-{current_year}.2/">Sample Magazine Jahresthema {current_year}</a>
                    </h3>
                    <time class="u-dt" datetime="{current_year}-01-02T10:00:00+0100"></time>
                </li>
                <li class="block-row">
                    <h3 class="contentRow-title">
                        <a href="/threads/sample-magazine-jahresthema-{previous_year}.3/">Sample Magazine Jahresthema {previous_year}</a>
                    </h3>
                    <time class="u-dt" datetime="{current_year}-01-03T10:00:00+0100"></time>
                </li>
                <li class="block-row">
                    <h3 class="contentRow-title">
                        <a href="/threads/other-title-jahresthema-{current_year}.4/">Other Title Jahresthema {current_year}</a>
                    </h3>
                    <time class="u-dt" datetime="{current_year}-01-04T10:00:00+0100"></time>
                </li>
            </html>
        """

        first_thread_page = """
            <html>
                <a class="pageNav-page" href="/threads/sample-magazine-jahresthema/page-6">6</a>
                <a class="pageNav-page" href="/threads/sample-magazine-jahresthema/page-7">7</a>
            </html>
        """

        def thread_page(page_num):
            return f"""
                <html>
                    <article class="message--post" data-content="post-{page_num}">
                        <div class="bbWrapper">
                            <h3>Sample Magazine Issue {page_num}</h3>
                            <b>RapidGator</b>
                            <a href="https://filecrypt.invalid/Container/{page_num}.html">Download</a>
                        </div>
                        <time class="u-dt" datetime="{current_year}-02-{page_num:02d}T10:00:00+0100"></time>
                    </article>
                </html>
            """

        def fake_fetch(
            _shared_state, method, target_url, get_params=None, timeout=None
        ):
            if target_url.endswith("/search/search"):
                return FakeResponse(
                    search_html,
                    url="https://www.source.invalid/search/123/",
                )
            if target_url.endswith("/search/123/"):
                return FakeResponse("<html></html>", url=target_url)

            fetched_thread_urls.append(target_url)
            if target_url.endswith(f"jahresthema-{current_year}.2/"):
                return FakeResponse(first_thread_page, url=target_url)

            for page_num in range(3, 8):
                if target_url.endswith(f"jahresthema-{current_year}.2/page-{page_num}"):
                    return FakeResponse(thread_page(page_num), url=target_url)

            raise AssertionError(f"unexpected fetch: {target_url}")

        with (
            patch(
                "quasarr.search.sources.dl.retrieve_and_validate_session",
                return_value=object(),
            ),
            patch("quasarr.search.sources.dl.fetch_via_requests_session", fake_fetch),
            patch(
                "quasarr.search.sources.dl.generate_download_link",
                side_effect=lambda _state, title, url, *_args: (
                    f"download:{title}:{url}"
                ),
            ),
            patch("quasarr.search.sources.dl.clear_hostname_issue"),
        ):
            releases = SearchSource().search(
                FakeSharedState(),
                0,
                SEARCH_CAT_BOOKS,
                "Sample Magazine",
            )

        titles = [release["details"]["title"] for release in releases]

        self.assertIn(f"Sample.Magazine.Issue.3.{current_year}", titles)
        self.assertIn(f"Sample.Magazine.Issue.7.{current_year}", titles)
        self.assertNotIn(f"Sample.Magazine.Issue.2.{current_year}", titles)
        self.assertEqual(
            [
                f"https://www.source.invalid/threads/sample-magazine-jahresthema-{current_year}.2/",
                f"https://www.source.invalid/threads/sample-magazine-jahresthema-{current_year}.2/page-3",
                f"https://www.source.invalid/threads/sample-magazine-jahresthema-{current_year}.2/page-4",
                f"https://www.source.invalid/threads/sample-magazine-jahresthema-{current_year}.2/page-5",
                f"https://www.source.invalid/threads/sample-magazine-jahresthema-{current_year}.2/page-6",
                f"https://www.source.invalid/threads/sample-magazine-jahresthema-{current_year}.2/page-7",
            ],
            fetched_thread_urls,
        )

    def test_rejects_metadata_lines_as_issue_titles(self):
        current_year = datetime.now().year
        post_html = """
            <article class="message--post" data-content="post-1">
                <div class="bbWrapper">
                    <b>RapidGator</b>
                    <p>Groesse: 120 MB</p>
                    <p>Passwort: source.invalid</p>
                    <a href="https://filecrypt.invalid/Container/1.html">Download</a>
                </div>
            </article>
        """

        with patch(
            "quasarr.search.sources.dl.generate_download_link",
            side_effect=lambda _state, title, url, *_args: f"download:{title}:{url}",
        ):
            release = _release_from_jahresthema_post(
                FakeSharedState(),
                "source.invalid",
                BeautifulSoup(post_html, "html.parser").select_one(
                    "article.message--post"
                ),
                "https://www.source.invalid/threads/sample.1/page-2",
                "Sample Magazine",
                None,
                "dl",
                SEARCH_CAT_BOOKS,
            )

        self.assertIsNone(release)

        year_note_post_html = f"""
            <article class="message--post" data-content="post-1">
                <div class="bbWrapper">
                    <p>Updated mirrors for {current_year}</p>
                    <p>Mirror 1</p>
                    <a href="https://rapidgator.invalid/file/abc">Download</a>
                </div>
            </article>
        """

        with patch(
            "quasarr.search.sources.dl.generate_download_link",
            side_effect=lambda _state, title, url, *_args: f"download:{title}:{url}",
        ):
            year_note_release = _release_from_jahresthema_post(
                FakeSharedState(),
                "source.invalid",
                BeautifulSoup(year_note_post_html, "html.parser").select_one(
                    "article.message--post"
                ),
                "https://www.source.invalid/threads/sample.1/page-2",
                "Sample Magazine",
                None,
                "dl",
                SEARCH_CAT_BOOKS,
            )

        self.assertIsNone(year_note_release)

        quoted_issue_post_html = f"""
            <article class="message--post" data-content="post-1">
                <div class="bbWrapper">
                    <blockquote class="bbCodeBlock bbCodeBlock--quote">
                        <p>Sample Magazine Issue 12 {current_year}</p>
                        <a href="https://rapidgator.invalid/file/quoted">Download</a>
                    </blockquote>
                    <p>Updated mirrors only.</p>
                </div>
            </article>
        """

        with patch(
            "quasarr.search.sources.dl.generate_download_link",
            side_effect=lambda _state, title, url, *_args: f"download:{title}:{url}",
        ):
            quoted_issue_release = _release_from_jahresthema_post(
                FakeSharedState(),
                "source.invalid",
                BeautifulSoup(quoted_issue_post_html, "html.parser").select_one(
                    "article.message--post"
                ),
                "https://www.source.invalid/threads/sample.1/page-2",
                "Sample Magazine",
                None,
                "dl",
                SEARCH_CAT_BOOKS,
            )

        self.assertIsNone(quoted_issue_release)

        magazine_year_note_post_html = f"""
            <article class="message--post" data-content="post-1">
                <div class="bbWrapper">
                    <p>Sample Magazine updated mirrors for {current_year}</p>
                    <a href="https://rapidgator.invalid/file/abc">Download</a>
                </div>
            </article>
        """

        with patch(
            "quasarr.search.sources.dl.generate_download_link",
            side_effect=lambda _state, title, url, *_args: f"download:{title}:{url}",
        ):
            magazine_year_note_release = _release_from_jahresthema_post(
                FakeSharedState(),
                "source.invalid",
                BeautifulSoup(magazine_year_note_post_html, "html.parser").select_one(
                    "article.message--post"
                ),
                "https://www.source.invalid/threads/sample.1/page-2",
                "Sample Magazine",
                None,
                "dl",
                SEARCH_CAT_BOOKS,
            )

        self.assertIsNone(magazine_year_note_release)

        valid_post_html = f"""
            <article class="message--post" data-content="post-2">
                <div class="bbWrapper">
                    <p>Sample Magazine 12 {current_year}</p>
                    <b>RapidGator</b>
                    <a href="https://filecrypt.invalid/Container/2.html">Download</a>
                </div>
            </article>
        """

        with patch(
            "quasarr.search.sources.dl.generate_download_link",
            side_effect=lambda _state, title, url, *_args: f"download:{title}:{url}",
        ):
            valid_release = _release_from_jahresthema_post(
                FakeSharedState(),
                "source.invalid",
                BeautifulSoup(valid_post_html, "html.parser").select_one(
                    "article.message--post"
                ),
                "https://www.source.invalid/threads/sample.1/page-2",
                "Sample Magazine",
                None,
                "dl",
                SEARCH_CAT_BOOKS,
            )

        self.assertEqual(
            f"Sample.Magazine.12.{current_year}",
            valid_release["details"]["title"],
        )

    def test_does_not_append_current_year_to_title_with_existing_year(self):
        previous_year = datetime.now().year - 1
        post_html = f"""
            <article class="message--post" data-content="post-1">
                <div class="bbWrapper">
                    <p>Issue 01 {previous_year}</p>
                    <a href="https://rapidgator.invalid/file/abc">Download</a>
                </div>
            </article>
        """

        with patch(
            "quasarr.search.sources.dl.generate_download_link",
            side_effect=lambda _state, title, url, *_args: f"download:{title}:{url}",
        ):
            release = _release_from_jahresthema_post(
                FakeSharedState(),
                "source.invalid",
                BeautifulSoup(post_html, "html.parser").select_one(
                    "article.message--post"
                ),
                "https://www.source.invalid/threads/sample.1/page-2",
                "Sample Magazine",
                None,
                "dl",
                SEARCH_CAT_BOOKS,
            )

        self.assertEqual(
            f"Sample.Magazine.Issue.01.{previous_year}",
            release["details"]["title"],
        )

    def test_expanded_jahresthema_deduplicates_by_title(self):
        current_year = datetime.now().year
        thread_html = f"""
            <html>
                <article class="message--post" data-content="post-1">
                    <div class="bbWrapper">
                        <h3>Sample Magazine Issue 01 {current_year}</h3>
                        <a href="https://rapidgator.invalid/file/abc">Download</a>
                    </div>
                    <time class="u-dt" datetime="{current_year}-01-01T10:00:00+0100"></time>
                </article>
                <article class="message--post" data-content="post-2">
                    <div class="bbWrapper">
                        <h3>Sample Magazine Issue 01 {current_year}</h3>
                        <a href="https://ddownload.invalid/file/abc">Download</a>
                    </div>
                    <time class="u-dt" datetime="{current_year}-01-01T11:00:00+0100"></time>
                </article>
            </html>
        """

        with (
            patch(
                "quasarr.search.sources.dl.fetch_via_requests_session",
                return_value=FakeResponse(thread_html),
            ),
            patch(
                "quasarr.search.sources.dl.generate_download_link",
                side_effect=lambda _state, title, url, *_args: (
                    f"download:{title}:{url}"
                ),
            ),
        ):
            releases = _expand_jahresthema_thread_releases(
                FakeSharedState(),
                "source.invalid",
                "https://www.source.invalid/threads/sample-magazine.1/",
                "Sample Magazine",
                None,
                "dl",
                SEARCH_CAT_BOOKS,
            )

        self.assertEqual(1, len(releases))
        self.assertEqual(
            f"Sample.Magazine.Issue.01.{current_year}",
            releases[0]["details"]["title"],
        )
        self.assertTrue(releases[0]["details"]["source"].endswith("#post-1"))

    def test_jahresthema_prefilter_accepts_hoster_aliases(self):
        current_year = datetime.now().year

        for host in ("rg.invalid", "ddl.invalid", "ddlto.invalid"):
            with self.subTest(host=host):
                post_html = f"""
                    <article class="message--post" data-content="post-1">
                        <div class="bbWrapper">
                            <p>Sample Magazine Issue 01 {current_year}</p>
                            <a href="https://{host}/file/abc">Download</a>
                        </div>
                    </article>
                """
                post = BeautifulSoup(post_html, "html.parser").select_one(
                    "article.message--post"
                )

                self.assertTrue(_post_contains_supported_download(post))

                with patch(
                    "quasarr.search.sources.dl.generate_download_link",
                    side_effect=lambda _state, title, url, *_args: (
                        f"download:{title}:{url}"
                    ),
                ):
                    release = _release_from_jahresthema_post(
                        FakeSharedState(),
                        "source.invalid",
                        post,
                        "https://www.source.invalid/threads/sample.1/page-2",
                        "Sample Magazine",
                        None,
                        "dl",
                        SEARCH_CAT_BOOKS,
                    )

                self.assertIsNotNone(release)

    def test_jahresthema_prefilter_keeps_spoiler_download_links(self):
        current_year = datetime.now().year
        post_html = f"""
            <article class="message--post" data-content="post-1">
                <div class="bbWrapper">
                    <p>Sample Magazine Issue 01 {current_year}</p>
                    <div class="bbCodeSpoiler">
                        <a href="https://rapidgator.invalid/file/abc">Download</a>
                    </div>
                </div>
            </article>
        """
        post = BeautifulSoup(post_html, "html.parser").select_one(
            "article.message--post"
        )

        self.assertTrue(_post_contains_supported_download(post))

        with patch(
            "quasarr.search.sources.dl.generate_download_link",
            side_effect=lambda _state, title, url, *_args: f"download:{title}:{url}",
        ):
            release = _release_from_jahresthema_post(
                FakeSharedState(),
                "source.invalid",
                post,
                "https://www.source.invalid/threads/sample.1/page-2",
                "Sample Magazine",
                None,
                "dl",
                SEARCH_CAT_BOOKS,
            )

        self.assertIsNotNone(release)


class DlJahresthemaDownloadTests(unittest.TestCase):
    def test_download_prefers_requested_post_fragment(self):
        thread_html = """
            <html>
                <article class="message--post" data-content="post-1">
                    <div class="bbWrapper">
                        <h3>Sample Magazine Issue 1</h3>
                        <a href="#post-2">quoted post reference</a>
                        <b>RapidGator</b>
                        <a href="https://keeplinks.invalid/p/first">Download</a>
                    </div>
                </article>
                <article class="message--post" data-content="post-2">
                    <div class="bbWrapper">
                        <h3>Sample Magazine Issue 2</h3>
                        <b>RapidGator</b>
                        <a href="https://keeplinks.invalid/p/second">Download</a>
                    </div>
                </article>
            </html>
        """

        with (
            patch(
                "quasarr.downloads.sources.dl.retrieve_and_validate_session",
                return_value=object(),
            ),
            patch(
                "quasarr.downloads.sources.dl.fetch_via_requests_session",
                return_value=FakeResponse(thread_html),
            ),
        ):
            result = DownloadSource().get_download_links(
                FakeSharedState(),
                "https://www.source.invalid/threads/sample-magazine.1/page-2#post-2",
                [],
                "Sample Magazine Issue 2",
                "",
            )

        self.assertEqual(
            [["https://keeplinks.invalid/p/second", "rapidgator"]],
            result["links"],
        )


if __name__ == "__main__":
    unittest.main()
