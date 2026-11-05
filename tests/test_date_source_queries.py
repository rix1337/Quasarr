import time
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from quasarr.constants import SEARCH_CAT_SHOWS
from quasarr.search.sources import dd, dl, he, sj, templates
from quasarr.search.sources.helpers import custom_source
from quasarr.search.sources.templates.by import search as by


class EmptyResponse:
    status_code = 200
    content = b""
    text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return []


class DlSearchResponse(EmptyResponse):
    url = "https://www.dl.invalid/search/123/"
    text = """
    <ol>
      <li class="block-row">
        <h3 class="contentRow-title">
          <a href="/threads/other-series.1/">
            QZX.OtherSeries.2031.02.03.1080p.WEB.h264-GRP
          </a>
        </h3>
      </li>
    </ol>
    """


def shared_state_for(source):
    return SimpleNamespace(
        values={
            "config": lambda _section: {source: f"{source}.invalid"},
            "user_agent": "test-agent",
        }
    )


class DateSourceQueryTests(unittest.TestCase):
    def test_by_default_search_preserves_duplicate_results(self):
        duplicate = {"details": {"source": "https://by.invalid/release/1"}}
        source = by.Source()

        with (
            patch.object(by.requests, "get", return_value=EmptyResponse()),
            patch.object(source, "_parse_posts", return_value=[duplicate, duplicate]),
            patch.object(by, "clear_hostname_issue"),
        ):
            releases = source.search(
                shared_state_for("by"),
                time.time(),
                SEARCH_CAT_SHOWS,
                "Synthetic Show",
                season=1,
                episode=1,
            )

        self.assertEqual([duplicate, duplicate], releases)

    def test_dd_default_search_preserves_duplicate_results(self):
        item = {
            "releaseName": "Synthetic.Show.S01E01.1080p.WEB.h264-GRP",
            "size": 1024,
            "when": 0,
        }

        class Page(EmptyResponse):
            def __init__(self, items, next_cursor):
                self.items = items
                self.next_cursor = next_cursor

            def json(self):
                return {"results": self.items, "nextCursor": self.next_cursor}

        class Session:
            def get(self, url, params=None, **_kwargs):
                if not (params or {}).get("cursor"):
                    return Page([item], "next")
                return Page([item], None)

        with (
            patch.object(dd, "retrieve_and_validate_session", return_value=Session()),
            patch.object(dd, "generate_download_link", return_value="download"),
            patch.object(dd, "clear_hostname_issue"),
        ):
            releases = dd.Source().search(
                shared_state_for("dd"),
                time.time(),
                SEARCH_CAT_SHOWS,
                "Synthetic Show",
                season=1,
                episode=1,
            )

        self.assertEqual(2, len(releases))

    def test_dl_default_search_preserves_duplicate_results(self):
        first = {"details": {"title": "Synthetic.Show.S01E01.1080p-GRP"}}
        second = {"details": {"title": "Other.Show.S01E01.1080p-GRP"}}
        source = dl.Source()

        def search_page(*args):
            page_num = args[5]
            if page_num == 1:
                return [first], "123", ("raw-page-1",)
            if page_num == 2:
                return [first, second], None, ("raw-page-2",)
            return [], None, ()

        with (
            patch.object(dl, "retrieve_and_validate_session", return_value=object()),
            patch.object(source, "_search_single_page", side_effect=search_page),
            patch.object(dl, "clear_hostname_issue"),
        ):
            releases = source.search(
                shared_state_for("dl"),
                time.time(),
                SEARCH_CAT_SHOWS,
                "Synthetic Show",
                season=1,
                episode=1,
            )

        self.assertEqual([first, first, second], releases)

    def test_dl_default_search_stops_on_fully_filtered_page(self):
        source = dl.Source()
        pages = []

        def search_page(*args):
            page_num = args[5]
            pages.append(page_num)
            return [], "123" if page_num == 1 else None, ("filtered-page",)

        with (
            patch.object(dl, "retrieve_and_validate_session", return_value=object()),
            patch.object(source, "_search_single_page", side_effect=search_page),
        ):
            releases = source.search(
                shared_state_for("dl"),
                time.time(),
                SEARCH_CAT_SHOWS,
                "Synthetic Show",
                season=1,
                episode=1,
            )

        self.assertEqual([1], pages)
        self.assertEqual([], releases)

    def test_by_date_search_uses_acronym_root(self):
        urls = []

        def get(url, **_kwargs):
            urls.append(url)
            return EmptyResponse()

        with (
            patch.object(
                by, "get_localized_title", return_value="QZX Friday Night BetaDown"
            ),
            patch.object(by.requests, "get", side_effect=get),
        ):
            releases = by.Source().search(
                shared_state_for("by"),
                time.time(),
                SEARCH_CAT_SHOWS,
                "tt0000001",
                episode_date=date(2031, 2, 3),
            )

        self.assertEqual([], releases)
        self.assertEqual(["https://by.invalid/?q=QZX"], urls)

    def test_dd_date_search_uses_acronym_root(self):
        calls = []

        class Response(EmptyResponse):
            def json(self):
                return {"results": [], "nextCursor": None}

        class Session:
            def get(self, url, params=None, **_kwargs):
                calls.append((url, params or {}))
                return Response()

        with (
            patch.object(
                dd, "get_localized_title", return_value="QZX Friday Night BetaDown"
            ),
            patch.object(dd, "retrieve_and_validate_session", return_value=Session()),
        ):
            releases = dd.Source().search(
                shared_state_for("dd"),
                time.time(),
                SEARCH_CAT_SHOWS,
                "tt0000001",
                episode_date=date(2031, 2, 3),
            )

        self.assertEqual([], releases)
        self.assertEqual(1, len(calls))
        self.assertEqual("https://dd.invalid/api/releases/search", calls[0][0])
        self.assertEqual("QZX", calls[0][1]["keyword"])

    def test_he_searches_with_proven_space_date_query(self):
        requests = []

        def get(_url, **kwargs):
            requests.append(kwargs.get("params"))
            return EmptyResponse()

        with (
            patch.object(he, "get_localized_title", return_value="Synthetic Show"),
            patch.object(he, "get_year", return_value=1999),
            patch.object(he.requests, "get", side_effect=get),
        ):
            releases = he.Source().search(
                shared_state_for("he"),
                time.time(),
                SEARCH_CAT_SHOWS,
                "tt0000001",
                episode_date=date(2031, 2, 3),
            )

        self.assertEqual([], releases)
        self.assertEqual([{"s": "Synthetic Show 2031 02 03"}], requests)

    def test_he_date_search_validates_against_localized_title(self):
        class Response(EmptyResponse):
            content = b"""
            <div class="item">
              <div class="data">
                <h5>
                  <a href="https://release.invalid/item">
                    Other.Show.2031.02.03.1080p-GRP - 1 GB
                  </a>
                </h5>
              </div>
            </div>
            """

        with (
            patch.object(he, "get_localized_title", return_value="Synthetic Show"),
            patch.object(he.requests, "get", return_value=Response()),
            patch.object(he, "is_valid_release", return_value=False) as validator,
        ):
            releases = he.Source().search(
                shared_state_for("he"),
                time.time(),
                SEARCH_CAT_SHOWS,
                "tt0000001",
                episode_date=date(2031, 2, 3),
            )

        self.assertEqual([], releases)
        self.assertEqual("Synthetic Show", validator.call_args.args[2])

    def test_he_default_search_preserves_imdb_release_validation(self):
        class Response(EmptyResponse):
            content = b"""
            <div class="item">
              <div class="data">
                <h5>
                  <a href="https://release.invalid/item">
                    Alias.S01E01.1080p-GRP - 1 GB
                  </a>
                </h5>
              </div>
            </div>
            """

        with (
            patch.object(he, "get_localized_title", return_value="Synthetic Show"),
            patch.object(he.requests, "get", return_value=Response()),
            patch.object(he, "is_valid_release", return_value=False) as validator,
        ):
            releases = he.Source().search(
                shared_state_for("he"),
                time.time(),
                SEARCH_CAT_SHOWS,
                "tt0000001",
                season=1,
                episode=1,
            )

        self.assertEqual([], releases)
        self.assertEqual("tt0000001", validator.call_args.args[2])

    def test_dl_date_queries_do_not_include_premiere_year(self):
        queries = []
        source = dl.Source()

        def search_page(*args):
            queries.append((args[2], args[3]))
            return [], None, ()

        with (
            patch.object(dl, "get_localized_title", return_value="Synthetic Show"),
            patch.object(dl, "get_year", return_value=1999),
            patch.object(dl, "retrieve_and_validate_session", return_value=object()),
            patch.object(source, "_search_single_page", side_effect=search_page),
        ):
            releases = source.search(
                shared_state_for("dl"),
                time.time(),
                SEARCH_CAT_SHOWS,
                "tt0000001",
                episode_date=date(2031, 2, 3),
            )

        self.assertEqual([], releases)
        self.assertTrue(queries)
        self.assertTrue(any("2031 02 03" in query for query, _match in queries))
        self.assertTrue(all("1999" not in query for query, _match in queries))
        self.assertTrue(all(match == "Synthetic Show" for _query, match in queries))

    def test_dl_date_search_prioritizes_exact_query_before_broad_pagination(self):
        matched = {
            "details": {"title": "QZX.Friday.Night.BetaDown.2031.02.03.1080p-GRP"}
        }
        source = dl.Source()
        queries = []
        clock = iter((0, 0, 16, 16, 16))

        def search_page(*args):
            query = args[2]
            queries.append(query)
            if query.endswith("2031.02.03"):
                return [matched], "123", ("exact-page",)
            return [], "123", ("broad-page",)

        with (
            patch.object(
                dl,
                "date_numbering_search_strings",
                return_value=[
                    "QZX",
                    "QZX Friday Night BetaDown 2031.02.03",
                ],
            ),
            patch.object(dl, "retrieve_and_validate_session", return_value=object()),
            patch.object(source, "_search_single_page", side_effect=search_page),
            patch.object(dl.time, "time", side_effect=lambda: next(clock)),
            patch.object(dl, "clear_hostname_issue"),
        ):
            releases = source.search(
                shared_state_for("dl"),
                0,
                SEARCH_CAT_SHOWS,
                "QZX Friday Night BetaDown",
                episode_date=date(2031, 2, 3),
            )

        self.assertEqual(
            ["QZX Friday Night BetaDown 2031.02.03"],
            queries,
        )
        self.assertEqual([matched], releases)

    def test_dl_date_search_validates_broad_results_against_full_title(self):
        with patch.object(
            dl,
            "fetch_via_requests_session",
            return_value=DlSearchResponse(),
        ):
            releases, search_id, raw_page_signature = dl.Source()._search_single_page(
                shared_state_for("dl"),
                "dl.invalid",
                "QZX",
                "QZX Friday Night BetaDown",
                None,
                1,
                "tt0000001",
                SEARCH_CAT_SHOWS,
                None,
                None,
                date(2031, 2, 3),
            )

        self.assertEqual([], releases)
        self.assertEqual("123", search_id)
        self.assertTrue(raw_page_signature)

    def test_dl_date_search_continues_past_fully_filtered_page(self):
        matched = {"details": {"title": "QZX.BetaDown.2031.02.03.1080p.WEB.h264-GRP"}}
        source = dl.Source()
        pages = []

        def search_page(*args):
            page_num = args[5]
            pages.append(page_num)
            if page_num == 1:
                return [], "123", ("unrelated-page",)
            if page_num == 2:
                return [matched], None, ("matching-page",)
            return [], None, ()

        with (
            patch.object(dl, "get_localized_title", return_value="QZX BetaDown"),
            patch.object(dl, "date_numbering_search_strings", return_value=["QZX"]),
            patch.object(dl, "retrieve_and_validate_session", return_value=object()),
            patch.object(source, "_search_single_page", side_effect=search_page),
            patch.object(dl, "clear_hostname_issue"),
        ):
            releases = source.search(
                shared_state_for("dl"),
                time.time(),
                SEARCH_CAT_SHOWS,
                "tt0000001",
                episode_date=date(2031, 2, 3),
            )

        self.assertEqual([1, 2, 3], pages)
        self.assertEqual([matched], releases)

    def test_dl_date_search_stops_on_duplicate_raw_page(self):
        source = dl.Source()
        pages = []

        def search_page(*args):
            page_num = args[5]
            pages.append(page_num)
            return [], "123" if page_num == 1 else None, ("same-page",)

        with (
            patch.object(dl, "get_localized_title", return_value="QZX BetaDown"),
            patch.object(dl, "date_numbering_search_strings", return_value=["QZX"]),
            patch.object(dl, "retrieve_and_validate_session", return_value=object()),
            patch.object(source, "_search_single_page", side_effect=search_page),
        ):
            releases = source.search(
                shared_state_for("dl"),
                time.time(),
                SEARCH_CAT_SHOWS,
                "tt0000001",
                episode_date=date(2031, 2, 3),
            )

        self.assertEqual([1, 2], pages)
        self.assertEqual([], releases)

    def test_wd_date_search_does_not_include_premiere_year(self):
        urls = []
        state = shared_state_for("wd")

        def fetch(_state, url, *_args, **_kwargs):
            urls.append(url)
            return custom_source.FetchResult("", None, 200)

        with (
            patch("quasarr.providers.shared_state.values", state.values),
            patch(
                "quasarr.providers.imdb_metadata.get_localized_title",
                return_value="Synthetic Show",
            ),
            patch("quasarr.providers.imdb_metadata.get_year", return_value=1999),
            patch.object(custom_source, "fetch_markup", side_effect=fetch),
            patch.object(custom_source, "mark_hostname_issue"),
            patch.object(custom_source, "clear_hostname_issue"),
        ):
            releases = templates._load("wd").search(
                state,
                time.time(),
                SEARCH_CAT_SHOWS,
                "tt0000001",
                episode_date=date(2031, 2, 3),
            )

        self.assertEqual([], releases)
        self.assertEqual(["https://wd.invalid/search?q=Synthetic+Show"], urls)

    def test_sj_date_search_uses_all_shared_title_variants(self):
        params = []

        def get(_url, **kwargs):
            params.append(kwargs.get("params"))
            return EmptyResponse()

        with (
            patch.object(
                sj, "get_localized_title", return_value="QZX Friday Night BetaDown"
            ),
            patch.object(sj.requests, "get", side_effect=get),
        ):
            releases = sj.Source().search(
                shared_state_for("sj"),
                time.time(),
                SEARCH_CAT_SHOWS,
                "tt0000001",
                episode_date=date(2031, 2, 3),
            )

        self.assertEqual([], releases)
        self.assertIn({"q": "QZX"}, params)
        self.assertIn({"q": "QZX BetaDown"}, params)

    def test_sj_date_search_discovers_compact_schedule_title(self):
        class Response(EmptyResponse):
            def __init__(self, text):
                self.text = text
                self.content = text.encode("utf-8")

        queries = []

        def get(url, **kwargs):
            if url.endswith("/serie/search"):
                query = kwargs["params"]["q"]
                queries.append(query)
                if query == "Sample Showcase":
                    return Response('<a href="/serie/sample">Sample Showcase</a>')
                return EmptyResponse()
            if url.endswith("/serie/sample"):
                return Response('<div data-mediaid="123"></div>')
            if url.endswith("/api/media/123/releases"):
                return Response(
                    '{"season":{"items":[{"name":'
                    '"Sample.Showcase.2031.02.03.1080p.WEB.h264-GRP"}]}}'
                )
            raise AssertionError(f"unexpected URL: {url}")

        with (
            patch.object(
                sj,
                "get_localized_title",
                return_value="Sample Monday Night Showcase",
            ),
            patch.object(sj.requests, "get", side_effect=get),
            patch.object(sj, "generate_download_link", return_value="download"),
            patch.object(sj, "clear_hostname_issue"),
        ):
            releases = sj.Source().search(
                shared_state_for("sj"),
                time.time(),
                SEARCH_CAT_SHOWS,
                "tt0000001",
                episode_date=date(2031, 2, 3),
            )

        self.assertIn("Sample Showcase", queries)
        self.assertEqual(1, len(releases))
        self.assertEqual(
            "Sample.Showcase.2031.02.03.1080p.WEB.h264-GRP",
            releases[0]["details"]["title"],
        )

    def test_sj_default_search_preserves_imdb_release_validation(self):
        class Response(EmptyResponse):
            def __init__(self, text):
                self.text = text
                self.content = text.encode("utf-8")

        responses = iter(
            [
                Response('<a href="/serie/synthetic">Synthetic Show</a>'),
                Response('<div data-mediaid="123"></div>'),
                Response('{"season":{"items":[{"name":"Alias.S01E01.1080p-GRP"}]}}'),
            ]
        )

        with (
            patch.object(sj, "get_localized_title", return_value="Synthetic Show"),
            patch.object(
                sj.requests, "get", side_effect=lambda *_a, **_k: next(responses)
            ),
            patch.object(sj, "is_valid_release", return_value=False) as validator,
        ):
            releases = sj.Source().search(
                shared_state_for("sj"),
                time.time(),
                SEARCH_CAT_SHOWS,
                "tt0000001",
                season=1,
                episode=1,
            )

        self.assertEqual([], releases)
        self.assertEqual("tt0000001", validator.call_args.args[2])

    def test_sl_date_search_uses_acronym_root(self):
        urls = []
        state = shared_state_for("sl")

        def fetch(_state, url, *_args, **_kwargs):
            urls.append(url)
            return custom_source.FetchResult("", None, 200)

        with (
            patch("quasarr.providers.shared_state.values", state.values),
            patch(
                "quasarr.providers.imdb_metadata.get_localized_title",
                return_value="QZX Friday Night BetaDown",
            ),
            patch.object(custom_source, "fetch_markup", side_effect=fetch),
            patch.object(custom_source, "mark_hostname_issue"),
            patch.object(custom_source, "clear_hostname_issue"),
        ):
            releases = templates._load("sl").search(
                state,
                time.time(),
                SEARCH_CAT_SHOWS,
                "tt0000001",
                episode_date=date(2031, 2, 3),
            )

        self.assertEqual([], releases)
        self.assertCountEqual(
            ["https://sl.invalid/tv-shows/?s=QZX", "https://sl.invalid/foreign/?s=QZX"],
            urls,
        )


if __name__ == "__main__":
    unittest.main()
