import time
import unittest
from contextlib import ExitStack
from threading import Thread
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from quasarr.constants import SEARCH_CAT_MOVIES, SEARCH_CAT_SHOWS
from quasarr.search.sources.templates.mx.download import Source as DownloadSource
from quasarr.search.sources.templates.mx.search import (
    FeedBudgetSpent,
    _normalize_quality,
    _remaining_feed_timeout,
    _sanitize,
)
from quasarr.search.sources.templates.mx.search import (
    Source as SearchSource,
)


def make_shared_state(host="source.invalid", radarr=False, sonarr=False):
    def config(section):
        if section == "Hostnames":
            return {"mx": host}
        return {}

    values = {
        "user_agent": "UA/1.0",
        "internal_address": "http://localhost:8080",
        "config": config,
    }
    # Feed paths look up the cached *arr client by these keys; a truthy sentinel
    # is enough (the wanted-list calls themselves are patched in feed tests).
    if radarr:
        values["radarr_client"] = object()
    if sonarr:
        values["sonarr_client"] = object()
    return SimpleNamespace(values=values)


class FakeResponse:
    def __init__(self, json_data=None, status_code=200):
        self._json = json_data if json_data is not None else {}
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


# A wrong first entry (imdb_id None) must be skipped in favour of the IMDb match.
MOVIE_RESULTS = {
    "results": [
        {"id": 111, "name": "Wrong Match", "imdb_id": None, "is_series": False},
        {
            "id": 222,
            "name": "Some Movie",
            "imdb_id": "tt0000001",
            "tmdb_id": 27205,
            "is_series": False,
            "release_date": "2010-07-14T22:00:00.000000Z",
        },
    ]
}

MOVIE_LINKS = {
    "success": True,
    "all": [
        {
            "id": 900001,
            "quality": "HDLight 1080p (x265)",
            "host_name": "1Fichier",
            "language": "TrueFrench",
            "size": 4827965566,
            "upload_date": "2024-09-05T11:57:38.000000Z",
        }
    ],
}

DECODED_URL = "https://1fichier.com/?abc123&af=42"

SHOW_RESULTS = {
    "results": [
        {
            "id": 333,
            "name": "Some Show",
            "imdb_id": "tt0000002",
            "tmdb_id": 1396,
            "is_series": True,
        }
    ]
}

SHOW_LINKS = {
    "success": True,
    "all": [
        {
            "id": 900002,
            "quality": "WEB 1080p",
            "host_name": "1Fichier",
            "language": "TrueFrench",
            "size": 1000000000,
            "saison": 1,
            "episode": 1,
            "upload_date": "2025-10-23T09:17:50.000000Z",
        }
    ],
}


def build_fake_get(responses):
    """Return a fake requests.get dispatching by URL fragment.

    Also records the calls so tests can assert request shapes.
    """
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append((url, params or {}))
        if "/search" in url:
            return FakeResponse(responses.get("search", {"results": []}))
        if "/darkiworld/download/" in url:
            return FakeResponse(responses.get("links", {"success": False}))
        raise AssertionError(f"Unexpected URL: {url}")

    fake_get.calls = calls
    return fake_get


def wanted_returning(items):
    """Stand in for a wanted helper whose paging completed.

    The real helpers report completeness through ``status``; a mock that only
    returns a list looks like a partial acquisition, which suppresses the resume
    offset write.
    """

    def _wanted(_shared_state, limit=50, deadline=None, status=None):
        if status is not None:
            status["complete"] = True
        return list(items)

    return _wanted


def patch_issue_tracking(stack):
    """Silence the DB-backed hostname-issue helpers for hermetic tests."""
    stack.enter_context(
        patch("quasarr.search.sources.templates.mx.search.clear_hostname_issue")
    )
    stack.enter_context(
        patch("quasarr.search.sources.templates.mx.search.mark_hostname_issue")
    )


class MxSearchTests(unittest.TestCase):
    def _run_search(self, responses, title, **kwargs):
        ss = make_shared_state()
        captured = {}

        def fake_gen_link(shared_state, title, url, size_mb, password, imdb, key):
            captured.update(
                {
                    "title": title,
                    "url": url,
                    "size_mb": size_mb,
                    "imdb": imdb,
                    "key": key,
                }
            )
            return f"http://dl/{url}"

        with ExitStack() as stack:
            fake_get = build_fake_get(responses)
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.requests.get", fake_get
                )
            )
            patch_issue_tracking(stack)
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.get_localized_title",
                    return_value=title,
                )
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.generate_download_link",
                    fake_gen_link,
                )
            )
            releases = SearchSource().search(ss, 0.0, SEARCH_CAT_MOVIES, **kwargs)
        return releases, captured, fake_get

    def test_movie_search_matches_imdb_and_builds_release(self):
        releases, captured, fake_get = self._run_search(
            {"search": MOVIE_RESULTS, "links": MOVIE_LINKS},
            "Some Movie",
            search_string="tt0000001",
        )
        self.assertEqual(len(releases), 1)
        details = releases[0]["details"]
        # Year from release_date, normalized quality, source tag and hoster.
        self.assertEqual(
            details["title"],
            "Some.Movie.2010.1080p.WEBRip.x265.MX.1Fichier.TrueFrench",
        )
        self.assertEqual(details["hostname"], "mx")
        self.assertEqual(details["imdb_id"], "tt0000001")
        self.assertEqual(details["size"], 4827965566)
        self.assertEqual(releases[0]["type"], "protected")
        # Turnstile-gated decode is deferred to the download twin so search/feed
        # never touch /darkiworld/decode/.
        self.assertEqual(
            captured["url"],
            "https://api.source.invalid/api/darkiworld/decode/900001?title_id=222&host=1Fichier",
        )
        self.assertEqual(captured["key"], "mx")
        # Download endpoint must target the IMDb-matched id (222), not the first.
        download_calls = [c for c in fake_get.calls if "/download/movie/" in c[0]]
        self.assertEqual(len(download_calls), 1)
        self.assertIn("/download/movie/222", download_calls[0][0])

    def test_search_uses_direct_lien_when_present(self):
        links = {
            "success": True,
            "all": [
                {
                    "id": 900009,
                    "lien": DECODED_URL,
                    "quality": "1080p",
                    "host_name": "1fichier",
                    "language": "MULTi",
                    "size": 1000000000,
                    "upload_date": "2026-05-16T16:21:06.000000Z",
                    "source": "hydracker-live",
                }
            ],
        }
        releases, captured, _ = self._run_search(
            {"search": MOVIE_RESULTS, "links": links},
            "Some Movie",
            search_string="tt0000001",
        )
        self.assertEqual(len(releases), 1)
        self.assertEqual(captured["url"], DECODED_URL)

    def test_non_imdb_query_returns_empty(self):
        releases, _, fake_get = self._run_search(
            {"search": MOVIE_RESULTS, "links": MOVIE_LINKS},
            "Some Movie",
            search_string="not an id",
        )
        self.assertEqual(releases, [])
        self.assertEqual(fake_get.calls, [])

    def test_show_search_with_season_episode(self):
        ss = make_shared_state()
        with ExitStack() as stack:
            fake_get = build_fake_get({"search": SHOW_RESULTS, "links": SHOW_LINKS})
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.requests.get", fake_get
                )
            )
            patch_issue_tracking(stack)
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.get_localized_title",
                    return_value="Some Show",
                )
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.generate_download_link",
                    lambda *a, **k: "http://dl",
                )
            )
            releases = SearchSource().search(
                ss,
                0.0,
                SEARCH_CAT_SHOWS,
                search_string="tt0000002",
                season=1,
                episode=1,
            )
        self.assertEqual(len(releases), 1)
        self.assertIn("S01E01", releases[0]["details"]["title"])
        # season+episode must be forwarded to the download endpoint.
        dl = [c for c in fake_get.calls if "/download/tv/" in c[0]][0]
        self.assertEqual(dl[1].get("season"), 1)
        self.assertEqual(dl[1].get("episode"), 1)

    def test_show_search_without_season_episode_returns_empty(self):
        ss = make_shared_state()
        with ExitStack() as stack:
            fake_get = build_fake_get({"search": SHOW_RESULTS, "links": SHOW_LINKS})
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.requests.get", fake_get
                )
            )
            patch_issue_tracking(stack)
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.get_localized_title",
                    return_value="Some Show",
                )
            )
            releases = SearchSource().search(
                ss, 0.0, SEARCH_CAT_SHOWS, search_string="tt0000002"
            )
        self.assertEqual(releases, [])
        # The source is never asked for links without season+episode.
        self.assertFalse(any("/download/tv/" in c[0] for c in fake_get.calls))


class MxFeedTests(unittest.TestCase):
    def test_movie_feed_seeds_from_radarr_wanted(self):
        ss = make_shared_state(radarr=True)
        with ExitStack() as stack:
            fake_get = build_fake_get({"search": MOVIE_RESULTS, "links": MOVIE_LINKS})
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.requests.get", fake_get
                )
            )
            patch_issue_tracking(stack)
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.get_localized_title",
                    return_value="Some Movie",
                )
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.generate_download_link",
                    lambda *a, **k: "http://dl",
                )
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.radarr_api.get_wanted_imdb_ids",
                    return_value=["tt0000001"],
                )
            )
            releases = SearchSource().feed(ss, time.time(), SEARCH_CAT_MOVIES)
        self.assertEqual(len(releases), 1)
        self.assertEqual(releases[0]["details"]["imdb_id"], "tt0000001")

    def test_show_feed_seeds_from_sonarr_wanted(self):
        ss = make_shared_state(sonarr=True)
        with ExitStack() as stack:
            fake_get = build_fake_get({"search": SHOW_RESULTS, "links": SHOW_LINKS})
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.requests.get", fake_get
                )
            )
            patch_issue_tracking(stack)
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.get_localized_title",
                    return_value="Some Show",
                )
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.generate_download_link",
                    lambda *a, **k: "http://dl",
                )
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.sonarr_api.get_wanted_episodes",
                    return_value=[{"imdb_id": "tt0000002", "season": 1, "episode": 1}],
                )
            )
            releases = SearchSource().feed(ss, time.time(), SEARCH_CAT_SHOWS)
        self.assertEqual(len(releases), 1)
        self.assertIn("S01E01", releases[0]["details"]["title"])
        # Sonarr's season+episode reached the source download endpoint.
        dl = [c for c in fake_get.calls if "/download/tv/" in c[0]][0]
        self.assertEqual(dl[1].get("season"), 1)
        self.assertEqual(dl[1].get("episode"), 1)

    def test_show_feed_warns_and_skips_without_sonarr(self):
        # Movie-only setup (no Sonarr client): show feed warns and yields
        # nothing, without touching Sonarr or the source.
        ss = make_shared_state(radarr=True)  # Sonarr intentionally absent
        with ExitStack() as stack:
            get = stack.enter_context(
                patch("quasarr.search.sources.templates.mx.search.requests.get")
            )
            warn = stack.enter_context(
                patch("quasarr.search.sources.templates.mx.search.warn")
            )
            episodes = stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.sonarr_api.get_wanted_episodes"
                )
            )
            releases = SearchSource().feed(ss, time.time(), SEARCH_CAT_SHOWS)
        self.assertEqual(releases, [])
        get.assert_not_called()
        episodes.assert_not_called()
        warn.assert_called_once()

    def test_movie_feed_warns_and_skips_without_radarr(self):
        # TV-only setup (no Radarr client): movie feed warns and yields nothing.
        ss = make_shared_state(sonarr=True)  # Radarr intentionally absent
        with ExitStack() as stack:
            get = stack.enter_context(
                patch("quasarr.search.sources.templates.mx.search.requests.get")
            )
            warn = stack.enter_context(
                patch("quasarr.search.sources.templates.mx.search.warn")
            )
            ids = stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.radarr_api.get_wanted_imdb_ids"
                )
            )
            releases = SearchSource().feed(ss, time.time(), SEARCH_CAT_MOVIES)
        self.assertEqual(releases, [])
        get.assert_not_called()
        ids.assert_not_called()
        warn.assert_called_once()

    def test_feed_marks_issue_when_all_lookups_fail(self):
        ss = make_shared_state(radarr=True)

        def boom(*a, **k):
            raise RuntimeError("mx down")

        with ExitStack() as stack:
            stack.enter_context(
                patch("quasarr.search.sources.templates.mx.search.requests.get", boom)
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.get_localized_title",
                    return_value="Some Movie",
                )
            )
            clear = stack.enter_context(
                patch("quasarr.search.sources.templates.mx.search.clear_hostname_issue")
            )
            mark = stack.enter_context(
                patch("quasarr.search.sources.templates.mx.search.mark_hostname_issue")
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.radarr_api.get_wanted_imdb_ids",
                    return_value=["tt0000001"],
                )
            )
            releases = SearchSource().feed(ss, time.time(), SEARCH_CAT_MOVIES)
        self.assertEqual(releases, [])
        mark.assert_called_once()
        clear.assert_not_called()

    def test_feed_silent_when_nothing_available(self):
        # Seeds exist but no entry matches at the source: empty (no error) must not
        # mark or clear the source health.
        ss = make_shared_state(radarr=True)
        with ExitStack() as stack:
            fake_get = build_fake_get({"search": {"results": []}})
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.requests.get", fake_get
                )
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.get_localized_title",
                    return_value="Some Movie",
                )
            )
            clear = stack.enter_context(
                patch("quasarr.search.sources.templates.mx.search.clear_hostname_issue")
            )
            mark = stack.enter_context(
                patch("quasarr.search.sources.templates.mx.search.mark_hostname_issue")
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.radarr_api.get_wanted_imdb_ids",
                    return_value=["tt0000001"],
                )
            )
            releases = SearchSource().feed(ss, time.time(), SEARCH_CAT_MOVIES)
        self.assertEqual(releases, [])
        mark.assert_not_called()
        clear.assert_not_called()

    def test_feed_stops_at_budget_and_resumes_where_it_left_off(self):
        # Each seed costs several round trips, so a full wanted list can outlast
        # the *arr client's request timeout. The run must stop at the feed budget
        # and the next run must continue with the seeds it did not reach.
        ss = make_shared_state(radarr=True)
        source = SearchSource()
        wanted = ["tt0000001", "tt0000002", "tt0000003", "tt0000004"]
        queried = []

        def fake_lookup(_self, _api_base, _host, imdb_id, *args, **kwargs):
            queried.append(imdb_id)
            return []

        def run():
            with ExitStack() as stack:
                stack.enter_context(
                    patch.object(SearchSource, "_releases_for_imdb", fake_lookup)
                )
                patch_issue_tracking(stack)
                stack.enter_context(
                    patch(
                        "quasarr.search.sources.templates.mx.search.radarr_api.get_wanted_imdb_ids",
                        wanted_returning(wanted),
                    )
                )
                stack.enter_context(
                    patch(
                        "quasarr.search.sources.templates.mx.search.FEED_REQUEST_TIMEOUT_SECONDS",
                        30,
                    )
                )
                # Two seeds fit in the budget, the third finds it spent.
                stack.enter_context(
                    patch(
                        "quasarr.search.sources.templates.mx.search.time.time",
                        side_effect=[0.0, 1.0, 31.0, 31.0],
                    )
                )
                source.feed(ss, 0.0, SEARCH_CAT_MOVIES)

        run()
        self.assertEqual(["tt0000001", "tt0000002"], queried)

        queried.clear()
        run()
        self.assertEqual(["tt0000003", "tt0000004"], queried)

    def test_budget_spent_mid_seed_leaves_that_seed_for_the_next_run(self):
        # A seed whose own round trips ran into the budget produced nothing, so
        # it must be retried rather than skipped - and a spent budget is not a
        # source outage.
        ss = make_shared_state(radarr=True)
        source = SearchSource()
        queried = []

        def fake_lookup(_self, _api_base, _host, imdb_id, *args, **kwargs):
            queried.append(imdb_id)
            raise FeedBudgetSpent()

        def run(mark):
            with ExitStack() as stack:
                stack.enter_context(
                    patch.object(SearchSource, "_releases_for_imdb", fake_lookup)
                )
                stack.enter_context(
                    patch(
                        "quasarr.search.sources.templates.mx.search.clear_hostname_issue"
                    )
                )
                stack.enter_context(
                    patch(
                        "quasarr.search.sources.templates.mx.search.mark_hostname_issue",
                        mark,
                    )
                )
                stack.enter_context(
                    patch(
                        "quasarr.search.sources.templates.mx.search.radarr_api.get_wanted_imdb_ids",
                        return_value=["tt0000001", "tt0000002"],
                    )
                )
                source.feed(ss, time.time(), SEARCH_CAT_MOVIES)

        mark = MagicMock()
        run(mark)
        run(mark)
        self.assertEqual(["tt0000001", "tt0000001"], queried)
        mark.assert_not_called()

    def test_concurrent_feed_runs_leave_a_consistent_resume_offset(self):
        # The registry hands out one shared Source, so feed runs for the same
        # category can overlap on the offset. Whatever interleaving happens, the
        # stored offset has to be a value a run actually reached.
        ss = make_shared_state(radarr=True)
        source = SearchSource()
        wanted = ["tt1", "tt2", "tt3", "tt4"]

        def fake_lookup(*_args, **_kwargs):
            return []

        def run():
            with ExitStack() as stack:
                stack.enter_context(
                    patch.object(SearchSource, "_releases_for_imdb", fake_lookup)
                )
                patch_issue_tracking(stack)
                stack.enter_context(
                    patch(
                        "quasarr.search.sources.templates.mx.search.radarr_api.get_wanted_imdb_ids",
                        wanted_returning(wanted),
                    )
                )
                source.feed(ss, time.time(), SEARCH_CAT_MOVIES)

        threads = [Thread(target=run) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(20)

        self.assertIn(source._feed_offsets[SEARCH_CAT_MOVIES], range(len(wanted) + 1))

    def test_a_title_lookup_that_ran_out_of_time_keeps_its_seed(self):
        # No title because the budget went during the lookup, not because none
        # exists. The seed was never answered, so it keeps its place instead of
        # being rotated past: the clock is inside the budget at the loop check
        # and past it by the time the title comes back empty.
        ss = make_shared_state(radarr=True)
        source = SearchSource()

        with ExitStack() as stack:
            patch_issue_tracking(stack)
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.get_localized_title",
                    return_value=None,
                )
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.radarr_api.get_wanted_imdb_ids",
                    wanted_returning(["tt0000001", "tt0000002"]),
                )
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.time.time",
                    side_effect=[0, 100, 100],
                )
            )
            source.feed(ss, 0.0, SEARCH_CAT_MOVIES)

        self.assertEqual(0, source._feed_offsets[SEARCH_CAT_MOVIES])

    def test_partial_seed_acquisition_keeps_the_resume_offset(self):
        # Wanted paging stops at the same deadline, so a short list can be a
        # partial view. Normalizing the stored cursor against it (40 % 10 = 0)
        # and writing that back would drag the rotation to the head.
        ss = make_shared_state(radarr=True)
        source = SearchSource()
        source._feed_offsets[SEARCH_CAT_MOVIES] = 40

        with ExitStack() as stack:
            patch_issue_tracking(stack)
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.radarr_api.get_wanted_imdb_ids",
                    return_value=[f"tt{i}" for i in range(10)],
                )
            )
            # The helper reported no completion, the mark of an acquisition that
            # was cut short by a spent budget or a failed page.
            source.feed(ss, time.time(), SEARCH_CAT_MOVIES)

        self.assertEqual(40, source._feed_offsets[SEARCH_CAT_MOVIES])

    def test_a_failed_seed_lookup_keeps_the_resume_offset(self):
        # A transient Radarr failure reads as an empty page, so the wanted helper
        # returns no seeds. That says nothing about where to resume, and writing
        # an offset for it would send the next healthy pull back to the head.
        ss = make_shared_state(radarr=True)
        source = SearchSource()
        source._feed_offsets[SEARCH_CAT_MOVIES] = 3

        with ExitStack() as stack:
            patch_issue_tracking(stack)
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.radarr_api.get_wanted_imdb_ids",
                    return_value=[],
                )
            )
            source.feed(ss, time.time(), SEARCH_CAT_MOVIES)

        self.assertEqual(3, source._feed_offsets[SEARCH_CAT_MOVIES])

    def test_feed_budget_never_outlives_the_fan_out_deadline(self):
        # Slow mode triples the feed timeout, but the window the response is
        # answered in does not grow with it. A run past that window is discarded
        # while still having advanced the resume offset, so its seeds would not
        # come round again until the next full rotation.
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.FEED_REQUEST_TIMEOUT_SECONDS",
                    90,
                )
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.SEARCH_FANOUT_DEADLINE_SECONDS",
                    60,
                )
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.time.time",
                    return_value=61.0,
                )
            )
            self.assertIsNone(_remaining_feed_timeout(0.0))

    def test_get_raises_once_the_budget_callable_reports_it_is_spent(self):
        # The per-seed budget is re-read before every round trip, so a seed with
        # many links cannot outrun it by reusing the value it started with.
        with self.assertRaises(FeedBudgetSpent):
            SearchSource()._get(
                "https://api.source.invalid/api",
                "source.invalid",
                "/search",
                {},
                make_shared_state(),
                lambda: None,
            )


class MxSpecialsTests(unittest.TestCase):
    def test_season_zero_special_is_tagged(self):
        # Sonarr can want specials (season 0); the release title must still
        # carry S00E## so it parses back as that episode.
        ss = make_shared_state()
        show_results = {
            "results": [
                {
                    "id": 333,
                    "name": "Some Show",
                    "imdb_id": "tt0000003",
                    "is_series": True,
                }
            ]
        }
        # Link omits saison/episode -> must fall back to the requested 0/5.
        show_links = {
            "success": True,
            "all": [
                {
                    "id": 900003,
                    "quality": "WEB 1080p",
                    "host_name": "1Fichier",
                    "language": "TrueFrench",
                    "size": 1,
                    "upload_date": "",
                }
            ],
        }
        with ExitStack() as stack:
            fake_get = build_fake_get({"search": show_results, "links": show_links})
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.requests.get", fake_get
                )
            )
            patch_issue_tracking(stack)
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.get_localized_title",
                    return_value="Some Show",
                )
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.search.generate_download_link",
                    lambda *a, **k: "http://dl",
                )
            )
            releases = SearchSource().search(
                ss,
                0.0,
                SEARCH_CAT_SHOWS,
                search_string="tt0000003",
                season=0,
                episode=5,
            )
        self.assertEqual(len(releases), 1)
        self.assertIn("S00E05", releases[0]["details"]["title"])


class MxDownloadTests(unittest.TestCase):
    @patch("quasarr.search.sources.templates.mx.download.clear_hostname_issue")
    def test_returns_decoded_link_with_derived_mirror(self, _clear):
        ss = make_shared_state()
        result = DownloadSource().get_download_links(
            ss, DECODED_URL, [], "Some.Movie", None
        )
        self.assertEqual(result, {"links": [[DECODED_URL, "1fichier"]]})

    def test_mirror_filter_excludes_unrequested_hoster(self):
        ss = make_shared_state()
        result = DownloadSource().get_download_links(
            ss, DECODED_URL, ["rapidgator"], "Some.Movie", None
        )
        self.assertEqual(result, {"links": []})

    def test_empty_url_returns_no_links(self):
        ss = make_shared_state()
        self.assertEqual(
            DownloadSource().get_download_links(ss, "", [], "x", None),
            {"links": []},
        )

    def test_deferred_decode_url_solves_turnstile_and_posts_token(self):
        ss = make_shared_state()
        decode_url = "https://api.source.invalid/api/darkiworld/decode/900001?title_id=222&host=1Fichier"
        fs_response = SimpleNamespace(
            status_code=200,
            execute_js_result='{"token": "ts-tok-123", "error": null}',
        )
        post_calls = []

        def fake_post(url, params=None, json=None, headers=None, timeout=None):
            post_calls.append((url, params, json, headers))
            return FakeResponse(
                {"success": True, "embed_url": {"lien": DECODED_URL}}, status_code=200
            )

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.download.is_flaresolverr_available",
                    return_value=True,
                )
            )
            create = stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.download.flaresolverr_create_session",
                    return_value="sid-1",
                )
            )
            destroy = stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.download.flaresolverr_destroy_session"
                )
            )
            fs_get = stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.download.flaresolverr_get",
                    return_value=fs_response,
                )
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.download.requests.post",
                    fake_post,
                )
            )
            clear = stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.download.clear_hostname_issue"
                )
            )
            result = DownloadSource().get_download_links(
                ss, decode_url, ["1fichier"], "Some.Movie", None
            )

        self.assertEqual(result, {"links": [[DECODED_URL, "1fichier"]]})
        create.assert_called_once_with(ss)
        destroy.assert_called_once_with(ss, "sid-1")
        self.assertEqual(fs_get.call_args.args[1], "https://source.invalid/")
        self.assertEqual(len(post_calls), 1)
        self.assertEqual(
            post_calls[0][0],
            "https://api.source.invalid/api/darkiworld/decode/900001",
        )
        self.assertEqual(post_calls[0][1], {"title_id": "222"})
        self.assertEqual(post_calls[0][2], {"turnstileToken": "ts-tok-123"})
        clear.assert_called_once_with("mx")

    def test_deferred_decode_skips_flaresolverr_when_host_hint_not_in_mirrors(self):
        ss = make_shared_state()
        decode_url = "https://api.source.invalid/api/darkiworld/decode/900001?title_id=222&host=1Fichier"
        with patch(
            "quasarr.search.sources.templates.mx.download.flaresolverr_create_session"
        ) as create:
            result = DownloadSource().get_download_links(
                ss, decode_url, ["rapidgator"], "Some.Movie", None
            )
        self.assertEqual(result, {"links": []})
        create.assert_not_called()

    def test_deferred_decode_destroys_session_when_flaresolverr_raises(self):
        ss = make_shared_state()
        decode_url = "https://api.source.invalid/api/darkiworld/decode/900001?title_id=222&host=1Fichier"
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.download.is_flaresolverr_available",
                    return_value=True,
                )
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.download.flaresolverr_create_session",
                    return_value="sid-err",
                )
            )
            destroy = stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.download.flaresolverr_destroy_session"
                )
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.download.flaresolverr_get",
                    side_effect=RuntimeError("browser crash"),
                )
            )
            mark = stack.enter_context(
                patch(
                    "quasarr.search.sources.templates.mx.download.mark_hostname_issue"
                )
            )
            result = DownloadSource().get_download_links(
                ss, decode_url, [], "Some.Movie", None
            )
        self.assertEqual(result, {"links": []})
        destroy.assert_called_once_with(ss, "sid-err")
        mark.assert_called_once()


class MxHelperTests(unittest.TestCase):
    def test_sanitize_preserves_accents_collapses_punctuation(self):
        self.assertEqual(
            _sanitize("Amélie: l'histoire (2001)"), "Amélie.l.histoire.2001"
        )

    def test_normalize_quality_maps_scene_tokens(self):
        self.assertEqual(
            _normalize_quality("HDLight 1080p (x265)"), "1080p.WEBRip.x265"
        )
        self.assertEqual(_normalize_quality("REMUX BLURAY"), "BluRay.REMUX")
        self.assertEqual(_normalize_quality("WEB 1080p"), "1080p.WEBDL")
        # UHD maps to 2160p and the codec is never doubled on the raw fallback.
        self.assertEqual(_normalize_quality("Ultra HD x265"), "2160p.x265")
        # Unrecognized labels fall back to the cleaned raw string.
        self.assertEqual(_normalize_quality("DVDRIP MKV"), "DVDRIP.MKV")


if __name__ == "__main__":
    unittest.main()
