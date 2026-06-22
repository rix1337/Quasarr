import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from quasarr.constants import SEARCH_CAT_MOVIES, SEARCH_CAT_SHOWS
from quasarr.downloads.sources.mx import Source as DownloadSource
from quasarr.search.sources.mx import (
    Source as SearchSource,
)
from quasarr.search.sources.mx import (
    _normalize_quality,
    _sanitize,
)


def make_shared_state(host="source.invalid"):
    def config(section):
        if section == "Hostnames":
            return {"mx": host}
        return {}

    return SimpleNamespace(
        values={
            "user_agent": "UA/1.0",
            "internal_address": "http://localhost:8080",
            "config": config,
        }
    )


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
        if "/darkiworld/decode/" in url:
            return FakeResponse(
                responses.get("decode", {"embed_url": {"lien": DECODED_URL}})
            )
        raise AssertionError(f"Unexpected URL: {url}")

    fake_get.calls = calls
    return fake_get


def patch_issue_tracking(stack):
    """Silence the DB-backed hostname-issue helpers for hermetic tests."""
    stack.enter_context(patch("quasarr.search.sources.mx.clear_hostname_issue"))
    stack.enter_context(patch("quasarr.search.sources.mx.mark_hostname_issue"))


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
                patch("quasarr.search.sources.mx.requests.get", fake_get)
            )
            patch_issue_tracking(stack)
            stack.enter_context(
                patch(
                    "quasarr.search.sources.mx.get_localized_title",
                    return_value=title,
                )
            )
            stack.enter_context(
                patch("quasarr.search.sources.mx.generate_download_link", fake_gen_link)
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
        # The decoded hoster URL (not the source link id) is what gets downloaded.
        self.assertEqual(captured["url"], DECODED_URL)
        self.assertEqual(captured["key"], "mx")
        # Download endpoint must target the IMDb-matched id (222), not the first.
        download_calls = [c for c in fake_get.calls if "/download/movie/" in c[0]]
        self.assertEqual(len(download_calls), 1)
        self.assertIn("/download/movie/222", download_calls[0][0])

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
                patch("quasarr.search.sources.mx.requests.get", fake_get)
            )
            patch_issue_tracking(stack)
            stack.enter_context(
                patch(
                    "quasarr.search.sources.mx.get_localized_title",
                    return_value="Some Show",
                )
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.mx.generate_download_link",
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
                patch("quasarr.search.sources.mx.requests.get", fake_get)
            )
            patch_issue_tracking(stack)
            stack.enter_context(
                patch(
                    "quasarr.search.sources.mx.get_localized_title",
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
        ss = make_shared_state()
        with ExitStack() as stack:
            fake_get = build_fake_get({"search": MOVIE_RESULTS, "links": MOVIE_LINKS})
            stack.enter_context(
                patch("quasarr.search.sources.mx.requests.get", fake_get)
            )
            patch_issue_tracking(stack)
            stack.enter_context(
                patch(
                    "quasarr.search.sources.mx.get_localized_title",
                    return_value="Some Movie",
                )
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.mx.generate_download_link",
                    lambda *a, **k: "http://dl",
                )
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.mx.radarr_api.get_wanted_imdb_ids",
                    return_value=["tt0000001"],
                )
            )
            releases = SearchSource().feed(ss, 0.0, SEARCH_CAT_MOVIES)
        self.assertEqual(len(releases), 1)
        self.assertEqual(releases[0]["details"]["imdb_id"], "tt0000001")

    def test_show_feed_seeds_from_sonarr_wanted(self):
        ss = make_shared_state()
        with ExitStack() as stack:
            fake_get = build_fake_get({"search": SHOW_RESULTS, "links": SHOW_LINKS})
            stack.enter_context(
                patch("quasarr.search.sources.mx.requests.get", fake_get)
            )
            patch_issue_tracking(stack)
            stack.enter_context(
                patch(
                    "quasarr.search.sources.mx.get_localized_title",
                    return_value="Some Show",
                )
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.mx.generate_download_link",
                    lambda *a, **k: "http://dl",
                )
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.mx.sonarr_api.get_wanted_episodes",
                    return_value=[{"imdb_id": "tt0000002", "season": 1, "episode": 1}],
                )
            )
            releases = SearchSource().feed(ss, 0.0, SEARCH_CAT_SHOWS)
        self.assertEqual(len(releases), 1)
        self.assertIn("S01E01", releases[0]["details"]["title"])
        # Sonarr's season+episode reached the source download endpoint.
        dl = [c for c in fake_get.calls if "/download/tv/" in c[0]][0]
        self.assertEqual(dl[1].get("season"), 1)
        self.assertEqual(dl[1].get("episode"), 1)

    def test_show_feed_empty_without_sonarr(self):
        ss = make_shared_state()
        with ExitStack() as stack:
            get = stack.enter_context(patch("quasarr.search.sources.mx.requests.get"))
            # No Sonarr client configured -> no episodes -> no source calls.
            stack.enter_context(
                patch(
                    "quasarr.search.sources.mx.sonarr_api.get_wanted_episodes",
                    return_value=[],
                )
            )
            releases = SearchSource().feed(ss, 0.0, SEARCH_CAT_SHOWS)
        self.assertEqual(releases, [])
        get.assert_not_called()

    def test_feed_marks_issue_when_all_lookups_fail(self):
        ss = make_shared_state()

        def boom(*a, **k):
            raise RuntimeError("mx down")

        with ExitStack() as stack:
            stack.enter_context(patch("quasarr.search.sources.mx.requests.get", boom))
            stack.enter_context(
                patch(
                    "quasarr.search.sources.mx.get_localized_title",
                    return_value="Some Movie",
                )
            )
            clear = stack.enter_context(
                patch("quasarr.search.sources.mx.clear_hostname_issue")
            )
            mark = stack.enter_context(
                patch("quasarr.search.sources.mx.mark_hostname_issue")
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.mx.radarr_api.get_wanted_imdb_ids",
                    return_value=["tt0000001"],
                )
            )
            releases = SearchSource().feed(ss, 0.0, SEARCH_CAT_MOVIES)
        self.assertEqual(releases, [])
        mark.assert_called_once()
        clear.assert_not_called()

    def test_feed_silent_when_nothing_available(self):
        # Seeds exist but no entry matches at the source: empty (no error) must not
        # mark or clear the source health.
        ss = make_shared_state()
        with ExitStack() as stack:
            fake_get = build_fake_get({"search": {"results": []}})
            stack.enter_context(
                patch("quasarr.search.sources.mx.requests.get", fake_get)
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.mx.get_localized_title",
                    return_value="Some Movie",
                )
            )
            clear = stack.enter_context(
                patch("quasarr.search.sources.mx.clear_hostname_issue")
            )
            mark = stack.enter_context(
                patch("quasarr.search.sources.mx.mark_hostname_issue")
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.mx.radarr_api.get_wanted_imdb_ids",
                    return_value=["tt0000001"],
                )
            )
            releases = SearchSource().feed(ss, 0.0, SEARCH_CAT_MOVIES)
        self.assertEqual(releases, [])
        mark.assert_not_called()
        clear.assert_not_called()


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
                patch("quasarr.search.sources.mx.requests.get", fake_get)
            )
            patch_issue_tracking(stack)
            stack.enter_context(
                patch(
                    "quasarr.search.sources.mx.get_localized_title",
                    return_value="Some Show",
                )
            )
            stack.enter_context(
                patch(
                    "quasarr.search.sources.mx.generate_download_link",
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
    @patch("quasarr.downloads.sources.mx.clear_hostname_issue")
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
