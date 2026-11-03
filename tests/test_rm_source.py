# -*- coding: utf-8 -*-

import time
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import requests
from bs4 import BeautifulSoup

from quasarr.constants import SEARCH_CAT_MOVIES, SEARCH_CAT_SHOWS
from quasarr.downloads.sources.rm import (
    Source as DownloadSource,
)
from quasarr.downloads.sources.rm import (
    _extract_download_links,
    _extract_imdb_id,
    _extract_release_slug,
    _get_base_url,
)
from quasarr.search.sources.rm import (
    Source as SearchSource,
)
from quasarr.search.sources.rm import (
    _build_phrase_query,
    _clean_title,
    _parse_feed,
    _parse_production_page,
    _parse_release_results,
    _relative_date,
)


def shared_state(host="source.invalid"):
    values = {
        "user_agent": "UA/1.0",
        "internal_address": "http://localhost:8080",
        "config": lambda section: {"rm": host} if section == "Hostnames" else {},
    }
    return SimpleNamespace(values=values)


def soup(html):
    return BeautifulSoup(html, "html.parser")


FEED_HTML = """
<div class="blog-post clear">
  <div class="bloglist-date"><p class="month-day">11/02</p><p class="year">2026</p></div>
  <h3><a href="/release/synthetic-movie-2026-1080p-web-dl-x264-grp">Synthetic Movie 2026 1080p WEB-DL x264-GRP </a><br/>
    <span>[RR/NF]<br/><span>FILE SIZE: <span>1.4GB</span></span></span></h3>
  <div class="blog-desc"><a href="https://www.imdb.com/title/tt0000001/">IMDb</a></div>
</div>
<div class="blog-post clear">
  <div class="bloglist-date"><p class="month-day">10/31</p><p class="year">2026</p></div>
  <h3><a href="/release/synthetic-show-s01e02-720p-web-dl-x264-grp">Synthetic Show S01E02 720p WEB-DL x264-GRP</a>
    <span>FILE SIZE: <span>463MB</span></span></h3>
</div>
<div class="blog-post clear"><h3><a href="/elsewhere">Not a release</a></h3></div>
"""

PRODUCTION_HTML = """<div class="blog-details">
<ul class="allrls" id="packs">
  <li><a href="/release/synthetic-show-s01-1080p-web-dl-grp">[RR/NF] Synthetic Show S01 1080p WEB-DL-GRP (7.4GB)</a>
      <span class="DIS_time">2&nbsp;years</span></li>
</ul>
<ul class="allrls" id="episodes">
  <li>1080p <a href="/release/synthetic-show-s01e02-1080p-web-dl-grp">[RR/NF/CU] Synthetic Show S01E02 1080p WEB-DL-GRP (527MB)</a>
      <span class="DIS_time">3&nbsp;hours</span></li>
  <li><a href="/not-a-release">skipped</a></li>
</ul>
</div>
"""

RESULTS_HTML = """<div class="lists-list">
<div class="list"><h3>Titles (1)</h3><div class="list_items"><ul>
  <li><a class="title" href="/synthetic-show"><b>Synthetic Show</b> (2026)</a></li></ul></div></div>
<div class="list"><h3>Releases (2)</h3><div class="list_items"><ul>
  <li><a class="title" href="/release/synthetic-show-s01e02-1080p-web-dl-grp"><b>[RR/NF] Synthetic Show S01E02 1080p WEB-DL-GRP (527MB)</b></a></li>
  <li><a class="title" href="/release/synthetic-show-s01e03-1080p-web-dl-grp"><b>[RR] Synthetic Show S01E03 1080p WEB-DL-GRP (500MB)</b></a></li>
</ul></div></div>
</div>
"""

RELEASE_HTML = """
<a href="https://www.imdb.com/title/tt0000001/">imdb</a>
<a name="links0"></a><h4 class="links">HosterA:</h4>
<pre class="links" id="l0"><!--sse-->https://rapidrar.invalid/abc123<!--/sse--></pre>
<pre class="links" id="l1">https://rapidrar.example.invalid/abc123</pre>
<pre class="links" id="l2">https://nitroflare.invalid/view/ABC/file.mkv
https://nitroflare.invalid/view/DEF/file2.mkv</pre>
<pre class="links" id="l3">https://unknownhost.invalid/zzz</pre>
"""


class ParsingTests(unittest.TestCase):
    def test_clean_title_drops_tags_size_and_parentheses(self):
        self.assertEqual(
            "Synthetic.Movie.2026.1080p.WEBRip-GRP",
            _clean_title("[RR/NF/CU] Synthetic Movie (2026) 1080p WEBRip-GRP (1.4GB)"),
        )

    def test_feed_posts_carry_date_size_and_imdb(self):
        items = _parse_feed(soup(FEED_HTML))

        self.assertEqual(2, len(items))
        first = items[0]
        self.assertEqual("Synthetic.Movie.2026.1080p.WEB-DL.x264-GRP", first["title"])
        self.assertEqual(1433, first["size_mb"])
        self.assertEqual("tt0000001", first["imdb_id"])
        self.assertEqual("Mon, 02 Nov 2026 00:00:00 +0000", first["date"])
        self.assertIsNone(items[1]["imdb_id"])

    def test_production_page_lists_packs_and_episodes(self):
        items = _parse_production_page(soup(PRODUCTION_HTML))

        self.assertEqual(
            [
                "Synthetic.Show.S01.1080p.WEB-DL-GRP",
                "Synthetic.Show.S01E02.1080p.WEB-DL-GRP",
            ],
            [item["title"] for item in items],
        )
        self.assertEqual(527, items[1]["size_mb"])

    def test_result_lists_only_yield_releases(self):
        items = _parse_release_results(soup(RESULTS_HTML))

        self.assertEqual(2, len(items))
        self.assertEqual(
            "/release/synthetic-show-s01e02-1080p-web-dl-grp", items[0]["href"]
        )

    def test_relative_date_converts_age_units(self):
        now = datetime.now(timezone.utc)

        def age_days(text):
            parsed = datetime.strptime(_relative_date(text), "%a, %d %b %Y %H:%M:%S %z")
            return (now - parsed).days

        self.assertEqual(0, age_days("4\xa0minutes"))
        self.assertEqual(364, age_days("1\xa0year") - 1)
        self.assertEqual(0, age_days("not an age"))

    def test_phrase_query_appends_season_and_episode(self):
        self.assertEqual("Show", _build_phrase_query("Show", None, None))
        self.assertEqual("Show S02", _build_phrase_query("Show", 2, None))
        self.assertEqual("Show S02E06", _build_phrase_query("Show", 2, 6))

    def test_base_url_uses_the_configured_host_as_is(self):
        self.assertEqual("https://source.invalid", _get_base_url(shared_state()))
        self.assertEqual(
            "https://source.invalid",
            _get_base_url(shared_state("https://www.source.invalid/")),
        )


class DownloadTests(unittest.TestCase):
    def test_links_are_deduplicated_per_hoster_and_file(self):
        links = _extract_download_links(soup(RELEASE_HTML))

        self.assertEqual(
            [
                ["https://rapidrar.invalid/abc123", "rapidrar"],
                ["https://nitroflare.invalid/view/ABC/file.mkv", "nitroflare"],
                ["https://nitroflare.invalid/view/DEF/file2.mkv", "nitroflare"],
            ],
            links,
        )

    def test_mirror_whitelist_filters_hosters(self):
        links = _extract_download_links(soup(RELEASE_HTML), ["nitroflare"])

        self.assertEqual({"nitroflare"}, {mirror for _, mirror in links})

    def test_imdb_id_and_slug(self):
        self.assertEqual("tt0000001", _extract_imdb_id(soup(RELEASE_HTML)))
        self.assertEqual(
            "some-slug",
            _extract_release_slug("https://source.invalid/release/some-slug"),
        )
        self.assertIsNone(_extract_release_slug("https://source.invalid/other"))

    def test_download_reports_links_and_clears_issue(self):
        with (
            patch(
                "quasarr.downloads.sources.rm._fetch_release_page",
                return_value=soup(RELEASE_HTML),
            ),
            patch("quasarr.downloads.sources.rm.clear_hostname_issue") as clear,
        ):
            result = DownloadSource().get_download_links(
                shared_state(), "https://source.invalid/release/x", [], "t", ""
            )

        self.assertEqual("tt0000001", result["imdb_id"])
        self.assertEqual(3, len(result["links"]))
        clear.assert_called_once()

    def test_removed_release_is_not_a_host_issue(self):
        response = requests.Response()
        response.status_code = 404
        error = requests.HTTPError("404", response=response)

        with (
            patch(
                "quasarr.downloads.sources.rm._fetch_release_page", side_effect=error
            ),
            patch("quasarr.downloads.sources.rm.mark_hostname_issue") as mark,
        ):
            result = DownloadSource().get_download_links(
                shared_state(), "https://source.invalid/release/x", [], "t", ""
            )

        self.assertEqual([], result["links"])
        mark.assert_not_called()

    def test_server_error_marks_the_host(self):
        response = requests.Response()
        response.status_code = 503
        error = requests.HTTPError("503", response=response)

        with (
            patch(
                "quasarr.downloads.sources.rm._fetch_release_page", side_effect=error
            ),
            patch("quasarr.downloads.sources.rm.mark_hostname_issue") as mark,
        ):
            DownloadSource().get_download_links(
                shared_state(), "https://source.invalid/release/x", [], "t", ""
            )

        mark.assert_called_once()


class SearchFlowTests(unittest.TestCase):
    def setUp(self):
        link = patch(
            "quasarr.search.sources.rm.generate_download_link",
            return_value="http://localhost:8080/download/?payload=x",
        )
        link.start()
        self.addCleanup(link.stop)
        clear = patch("quasarr.search.sources.rm.clear_hostname_issue")
        clear.start()
        self.addCleanup(clear.stop)

    def pages(self, mapping):
        def fake(_state, path, _timeout):
            return soup(mapping[path])

        return patch("quasarr.search.sources.rm._get_page", side_effect=fake)

    def test_feed_keeps_only_the_requested_category(self):
        with self.pages({"/": FEED_HTML}):
            movies = SearchSource().feed(shared_state(), time.time(), SEARCH_CAT_MOVIES)
            shows = SearchSource().feed(shared_state(), time.time(), SEARCH_CAT_SHOWS)

        self.assertEqual(
            ["Synthetic.Movie.2026.1080p.WEB-DL.x264-GRP"],
            [r["details"]["title"] for r in movies],
        )
        self.assertEqual(
            ["Synthetic.Show.S01E02.720p.WEB-DL.x264-GRP"],
            [r["details"]["title"] for r in shows],
        )
        self.assertEqual("tt0000001", movies[0]["details"]["imdb_id"])

    def test_imdb_search_reads_the_title_page_and_filters_the_episode(self):
        with self.pages(
            {"/search/tt0000009": RESULTS_HTML, "/synthetic-show": PRODUCTION_HTML}
        ):
            releases = SearchSource().search(
                shared_state(), time.time(), SEARCH_CAT_SHOWS, "tt0000009", 1, 2
            )

        self.assertEqual(
            ["Synthetic.Show.S01E02.1080p.WEB-DL-GRP"],
            [r["details"]["title"] for r in releases],
        )
        self.assertEqual("tt0000009", releases[0]["details"]["imdb_id"])
        self.assertEqual(
            "https://source.invalid/release/synthetic-show-s01e02-1080p-web-dl-grp",
            releases[0]["details"]["source"],
        )

    def test_phrase_search_filters_by_title(self):
        with self.pages({"/search/Synthetic+Show+S01E03/releases/query": RESULTS_HTML}):
            releases = SearchSource().search(
                shared_state(), time.time(), SEARCH_CAT_SHOWS, "Synthetic Show", 1, 3
            )

        self.assertEqual(
            ["Synthetic.Show.S01E03.1080p.WEB-DL-GRP"],
            [r["details"]["title"] for r in releases],
        )

    def test_unexpected_layout_marks_the_host(self):
        with (
            self.pages({"/": "<html><body>some other site</body></html>"}),
            patch("quasarr.search.sources.rm.mark_hostname_issue") as mark,
        ):
            releases = SearchSource().feed(
                shared_state(), time.time(), SEARCH_CAT_MOVIES
            )

        self.assertEqual([], releases)
        mark.assert_called_once()
        self.assertIn("Unexpected page layout", mark.call_args.args[2])

    def test_unparsable_post_is_skipped_without_marking_the_host(self):
        with (
            self.pages({"/": FEED_HTML}),
            patch(
                "quasarr.search.sources.rm._feed_date",
                side_effect=[ValueError("odd post"), "Sat, 31 Oct 2026 00:00:00 +0000"],
            ),
            patch("quasarr.search.sources.rm.mark_hostname_issue") as mark,
        ):
            releases = SearchSource().feed(
                shared_state(), time.time(), SEARCH_CAT_SHOWS
            )

        self.assertEqual(
            ["Synthetic.Show.S01E02.720p.WEB-DL.x264-GRP"],
            [r["details"]["title"] for r in releases],
        )
        mark.assert_not_called()

    def test_feed_without_category_matches_is_not_an_issue(self):
        movie_only = FEED_HTML.split('<div class="blog-post clear">')[1]
        with (
            self.pages({"/": f'<div class="blog-post clear">{movie_only}'}),
            patch("quasarr.search.sources.rm.mark_hostname_issue") as mark,
        ):
            releases = SearchSource().feed(
                shared_state(), time.time(), SEARCH_CAT_SHOWS
            )

        self.assertEqual([], releases)
        mark.assert_not_called()

    def test_failed_request_marks_the_host(self):
        with (
            patch(
                "quasarr.search.sources.rm._get_page", side_effect=RuntimeError("503")
            ),
            patch("quasarr.search.sources.rm.mark_hostname_issue") as mark,
        ):
            releases = SearchSource().feed(
                shared_state(), time.time(), SEARCH_CAT_MOVIES
            )

        self.assertEqual([], releases)
        mark.assert_called_once()


if __name__ == "__main__":
    unittest.main()
