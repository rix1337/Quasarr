# -*- coding: utf-8 -*-

import json
import time
import unittest
from unittest.mock import ANY, MagicMock, patch

from quasarr.downloads.sources.ff import Source as FfDownloadSource
from quasarr.downloads.sources.sf import Source as SfDownloadSource
from quasarr.providers.cloudflare import (
    FlareSolverrResponse,
    LazyFlareSolverrSession,
    _clear_cloudflare_gate_cache,
)
from quasarr.search.sources.ff import Source as FfSearchSource
from quasarr.search.sources.sf import Source as SfSearchSource


class FakeResponse:
    def __init__(self, url, text="", status_code=200, headers=None, json_data=None):
        self.url = url
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}
        self._json_data = json_data

    def json(self):
        return self._json_data or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"{self.status_code} error for url: {self.url}")


def _build_shared_state(hostnames):
    shared_state = MagicMock()
    stored = {}

    def _config(section):
        if section == "Hostnames":
            return hostnames
        return {}

    def _update(key, value):
        stored[key] = value

    shared_state.values = {
        "config": _config,
        "user_agent": "UnitTestAgent/1.0",
        "internal_address": "http://localhost:1234",
    }
    shared_state.update = _update
    return shared_state


class FfSourceTests(unittest.TestCase):
    def test_search_uses_single_canonical_localized_query(self):
        host = "host-ff.invalid"
        ascii_url = f"https://{host}/api/v2/search?q=Synthetic+Uemlaut&ql=DE"
        movie_url = f"https://{host}/synthetic-movie"
        api_url = f"https://{host}/api/v1/synthetic-token?filter="
        requested_urls = []

        movie_html = """
        <a href="https://www.imdb.invalid/title/tt0000001/">IMDB</a>
        <script>initMovie('synthetic-token')</script>
        """
        api_html = """
        <div class="entry">
          <span class="morespec">Synthetic.Uemlaut.2030.1080p.WEB-GROUP</span>
          <span class="audiotag"><small>Größe:</small> 1 GB</span>
        </div>
        """

        def fake_get(url, headers=None, timeout=None):
            requested_urls.append(url)
            if url == ascii_url:
                return FakeResponse(
                    url,
                    json_data={
                        "result": [
                            {
                                "title": "Synthetic Uemlaut",
                                "url_id": "synthetic-movie",
                            }
                        ]
                    },
                )
            if url == movie_url:
                return FakeResponse(url, text=movie_html)
            if url == api_url:
                return FakeResponse(url, json_data={"html": api_html})
            raise AssertionError(f"Unexpected URL requested: {url}")

        with (
            patch("quasarr.search.sources.ff.requests.get", side_effect=fake_get),
            patch(
                "quasarr.search.sources.ff.get_localized_title",
                return_value="Synthetic Uemlaut",
            ),
            patch("quasarr.search.sources.ff.get_recently_searched", return_value={}),
            patch(
                "quasarr.search.sources.ff.generate_download_link",
                return_value="download://synthetic",
            ),
            patch("quasarr.search.sources.ff.clear_hostname_issue"),
        ):
            result = FfSearchSource().search(
                _build_shared_state({"ff": host}),
                time.time(),
                2000,
                "tt0000001",
            )

        self.assertEqual([ascii_url, movie_url, api_url], requested_urls)
        self.assertEqual(1, len(result))
        self.assertEqual(
            "Synthetic.Uemlaut.2030.1080p.WEB-GROUP",
            result[0]["details"]["title"],
        )

    def test_feed_cross_references_movie_api(self):
        host = "host-ff.invalid"
        feed_url = f"https://{host}/updates/2026-06-24#list"
        empty_feed_url = f"https://{host}/updates/2026-06-23#list"
        movie_url = f"https://{host}/example-movie"
        api_url = f"https://{host}/api/v1/token123?filter="
        release_url = f"{movie_url}/Example.Movie.2026.1080p.WEB-GROUP"
        requested_urls = []

        feed_html = """
        <div class="sra">
          <span class="lsf-icon timed">10:15</span>
          <a href="/example-movie"></a>
          <h2>Example Movie<i>(2026)</i><span>
            <a href="/example-movie/Example.Movie.2026.1080p.WEB-GROUP">
              Example.Movie.2026.1080p.WEB-GROUP
            </a>
          </span></h2>
        </div>
        """
        movie_html = """
        <a href="https://www.imdb.com/title/tt1234567/">IMDB</a>
        <script>initMovie('token123', '', '', '', '', '');</script>
        """
        api_html = """
        <div class="entry">
          <span class="morespec">Example.Movie.2026.1080p.WEB-GROUP</span>
          <span class="audiotag"><small>Größe:</small> 1.5 GB</span>
        </div>
        """

        def fake_get(url, headers=None, timeout=None):
            requested_urls.append(url)
            if url == feed_url:
                return FakeResponse(url, text=feed_html)
            if url == empty_feed_url:
                return FakeResponse(url, text="")
            if url == movie_url:
                return FakeResponse(url, text=movie_html)
            if url == api_url:
                return FakeResponse(url, json_data={"html": api_html})
            raise AssertionError(f"Unexpected URL requested: {url}")

        with (
            patch("quasarr.search.sources.ff.requests.get", side_effect=fake_get),
            patch(
                "quasarr.search.sources.ff.generate_download_link",
                side_effect=lambda *args: f"download://{args[1]}",
            ),
            patch("quasarr.search.sources.ff.clear_hostname_issue"),
            patch("quasarr.search.sources.ff.datetime") as fake_datetime,
        ):
            fake_datetime.now.return_value.strftime.return_value = "2026-06-24"
            fake_datetime.now.return_value = __import__("datetime").datetime(
                2026, 6, 24, 12, 0, 0
            )
            fake_datetime.strptime = __import__("datetime").datetime.strptime
            result = FfSearchSource().feed(
                _build_shared_state({"ff": host}), time.time(), 2000
            )

        self.assertEqual([feed_url, movie_url, api_url, empty_feed_url], requested_urls)
        self.assertEqual(1, len(result))
        details = result[0]["details"]
        self.assertEqual("Example.Movie.2026.1080p.WEB-GROUP", details["title"])
        self.assertEqual("tt1234567", details["imdb_id"])
        self.assertEqual(release_url, details["source"])
        self.assertEqual(1536 * 1024 * 1024, details["size"])

    def test_feed_stops_cross_reference_when_timeout_budget_expires(self):
        host = "host-ff.invalid"
        feed_url = f"https://{host}/updates/2026-06-24#list"
        requested_urls = []
        feed_html = """
        <div class="sra">
          <span class="lsf-icon timed">10:15</span>
          <a href="/example-movie"></a>
          <h2>Example Movie<i>(2026)</i><span>
            <a href="/example-movie/Example.Movie.2026.1080p.WEB-GROUP">
              Example.Movie.2026.1080p.WEB-GROUP
            </a>
          </span></h2>
        </div>
        """

        def fake_get(url, headers=None, timeout=None):
            requested_urls.append(url)
            if url == feed_url:
                return FakeResponse(url, text=feed_html)
            raise AssertionError(f"Unexpected URL requested: {url}")

        with (
            patch("quasarr.search.sources.ff.requests.get", side_effect=fake_get),
            patch("quasarr.search.sources.ff.FEED_REQUEST_TIMEOUT_SECONDS", 1),
            patch(
                "quasarr.search.sources.ff.time.time",
                side_effect=[0, 0, 1.1, 1.1, 1.1],
            ),
            patch("quasarr.search.sources.ff.datetime") as fake_datetime,
        ):
            fake_datetime.now.return_value.strftime.return_value = "2026-06-24"
            fake_datetime.now.return_value = __import__("datetime").datetime(
                2026, 6, 24, 12, 0, 0
            )
            result = FfSearchSource().feed(_build_shared_state({"ff": host}), 0, 2000)

        self.assertEqual([feed_url], requested_urls)
        self.assertEqual([], result)

    def test_download_resolves_external_without_requesting_final_destination(self):
        host = "host-ff.invalid"
        external_url = f"https://{host}/external/abc123"
        direct_url = "https://hoster.invalid/file/example"
        requested_urls = []

        class FakeSession:
            def get(self, url, allow_redirects=False, timeout=None, headers=None):
                requested_urls.append((url, allow_redirects))
                if url == external_url:
                    return FakeResponse(
                        url,
                        status_code=302,
                        headers={"Location": direct_url},
                    )
                raise AssertionError(f"Unexpected URL requested: {url}")

        with (
            patch(
                "quasarr.downloads.sources.ff.requests.Session",
                return_value=FakeSession(),
            ),
            patch(
                "quasarr.providers.cloudflare.is_flaresolverr_available"
            ) as is_available,
            patch(
                "quasarr.providers.cloudflare.flaresolverr_create_session"
            ) as create_session,
            patch("quasarr.providers.cloudflare.flaresolverr_get") as flaresolverr_get,
            patch(
                "quasarr.downloads.sources.ff.detect_crypter_type", return_value=None
            ),
        ):
            result = FfDownloadSource().get_download_links(
                _build_shared_state({"ff": host}),
                external_url,
                [],
                "Example.Movie.2026.1080p.WEB-GROUP",
                None,
            )

        self.assertEqual(
            {"links": [[direct_url, "hoster"]], "imdb_id": None},
            result,
        )
        self.assertEqual([(external_url, False)], requested_urls)
        is_available.assert_not_called()
        create_session.assert_not_called()
        flaresolverr_get.assert_not_called()

    def test_download_re_resolves_when_ad_hijacks_the_redirect(self):
        # First resolution is hijacked to an aliexpress affiliate page; the retry
        # reaches the real hoster and that is what gets returned (Quasarr#419).
        host = "host-ff.invalid"
        external_url = f"https://{host}/external/abc123"
        ad_url = "https://www.aliexpress.com/p/popular-landing/aliexpress.html?x=1"
        direct_url = "https://rapidgator.net/file/example"
        locations = [ad_url, direct_url]

        class FakeSession:
            def get(self, url, allow_redirects=False, timeout=None, headers=None):
                if url == external_url:
                    return FakeResponse(
                        url, status_code=302, headers={"Location": locations.pop(0)}
                    )
                raise AssertionError(f"Unexpected URL requested: {url}")

        with (
            patch(
                "quasarr.downloads.sources.ff.requests.Session",
                return_value=FakeSession(),
            ),
            patch("quasarr.providers.cloudflare.is_flaresolverr_available"),
            patch("quasarr.providers.cloudflare.flaresolverr_create_session"),
            patch("quasarr.providers.cloudflare.flaresolverr_get"),
            patch(
                "quasarr.downloads.sources.ff.detect_crypter_type", return_value=None
            ),
        ):
            result = FfDownloadSource().get_download_links(
                _build_shared_state({"ff": host}),
                external_url,
                [],
                "Example.Movie.2026.1080p.WEB-GROUP",
                None,
            )

        self.assertEqual(
            {"links": [[direct_url, "rapidgator"]], "imdb_id": None},
            result,
        )

    def test_download_never_returns_ad_domain_when_hijack_persists(self):
        # Every attempt is hijacked to the ad host: no link is returned (the ad URL
        # must never reach the mirror whitelist / JDownloader).
        host = "host-ff.invalid"
        external_url = f"https://{host}/external/abc123"
        ad_url = "https://www.aliexpress.com/p/popular-landing/aliexpress.html"

        class FakeSession:
            def get(self, url, allow_redirects=False, timeout=None, headers=None):
                if url == external_url:
                    return FakeResponse(
                        url, status_code=302, headers={"Location": ad_url}
                    )
                raise AssertionError(f"Unexpected URL requested: {url}")

        with (
            patch(
                "quasarr.downloads.sources.ff.requests.Session",
                return_value=FakeSession(),
            ),
            patch("quasarr.providers.cloudflare.is_flaresolverr_available"),
            patch("quasarr.providers.cloudflare.flaresolverr_create_session"),
            patch("quasarr.providers.cloudflare.flaresolverr_get"),
            patch(
                "quasarr.downloads.sources.ff.detect_crypter_type", return_value=None
            ),
        ):
            result = FfDownloadSource().get_download_links(
                _build_shared_state({"ff": host}),
                external_url,
                [],
                "Example.Movie.2026.1080p.WEB-GROUP",
                None,
            )

        self.assertEqual({"links": [], "imdb_id": None}, result)


class FfSfCloudflareTests(unittest.TestCase):
    source_cases = (
        ("ff", FfSearchSource),
        ("sf", SfSearchSource),
    )

    def setUp(self):
        _clear_cloudflare_gate_cache()

    def tearDown(self):
        _clear_cloudflare_gate_cache()

    def test_flaresolverr_response_supports_json_api_payloads(self):
        payload = '{"result": [{"url_id": "synthetic-id"}]}'
        for body in (payload, f"<html><body><pre>{payload}</pre></body></html>"):
            with self.subTest(wrapped=body.startswith("<html>")):
                response = FlareSolverrResponse(
                    "https://source.invalid/api",
                    200,
                    {"Content-Type": "application/json"},
                    body,
                )

                self.assertEqual(
                    {"result": [{"url_id": "synthetic-id"}]},
                    response.json(),
                )

    def test_sf_api_error_is_logged_as_warning(self):
        host = "host-sf.invalid"
        search_url = f"https://{host}/api/v2/search?q=Synthetic Title&ql=DE"
        series_url = f"https://{host}/synthetic-id"

        def fake_get(url, headers=None, timeout=None):
            if url == search_url:
                return FakeResponse(
                    url,
                    json_data={
                        "result": [
                            {"title": "Synthetic Title", "url_id": "synthetic-id"}
                        ]
                    },
                )
            if url == series_url:
                return FakeResponse(
                    url, text="<script>initSeason('synthetic-token', '')</script>"
                )
            if f"https://{host}/api/v1/synthetic-token/season/ALL" in url:
                return FakeResponse(
                    url,
                    json_data={"error": True, "message": "synthetic API failure"},
                )
            raise AssertionError(f"Unexpected URL requested: {url}")

        with (
            patch("quasarr.search.sources.sf.requests.get", side_effect=fake_get),
            patch("quasarr.search.sources.sf.get_recently_searched", return_value={}),
            patch("quasarr.search.sources.sf.warn") as warn_log,
        ):
            result = SfSearchSource().search(
                _build_shared_state({"sf": host}),
                time.time(),
                5000,
                "Synthetic Title",
            )

        self.assertEqual([], result)
        warn_log.assert_called_once()
        self.assertIn(
            "SF API error for series 'synthetic-id'", warn_log.call_args.args[0]
        )

    def test_search_keeps_plain_response_without_flaresolverr(self):
        for initials, source_class in self.source_cases:
            with self.subTest(source=initials):
                host = f"host-{initials}.invalid"
                response = FakeResponse(
                    f"https://{host}/api/v2/search",
                    json_data={"result": []},
                )
                with (
                    patch(
                        f"quasarr.search.sources.{initials}.requests.get",
                        return_value=response,
                    ) as plain_get,
                    patch(
                        "quasarr.providers.cloudflare.is_flaresolverr_available"
                    ) as is_available,
                    patch(
                        "quasarr.providers.cloudflare.flaresolverr_create_session"
                    ) as create_session,
                    patch(
                        "quasarr.providers.cloudflare.flaresolverr_get"
                    ) as flaresolverr_get,
                    patch(
                        "quasarr.providers.cloudflare.flaresolverr_destroy_session"
                    ) as destroy_session,
                ):
                    result = source_class().search(
                        _build_shared_state({initials: host}),
                        time.time(),
                        2000 if initials == "ff" else 5000,
                        "Synthetic Title",
                    )

                self.assertEqual([], result)
                plain_get.assert_called_once()
                is_available.assert_not_called()
                create_session.assert_not_called()
                flaresolverr_get.assert_not_called()
                destroy_session.assert_not_called()

    def test_search_retries_cloudflare_challenge_with_flaresolverr(self):
        challenge_html = """
        <html>
          <title>Just a moment...</title>
          <form id="challenge-form"></form>
        </html>
        """
        for initials, source_class in self.source_cases:
            with self.subTest(source=initials):
                host = f"host-{initials}.invalid"
                request_url = f"https://{host}/api/v2/search"
                challenged = FakeResponse(
                    request_url,
                    text=challenge_html,
                    status_code=403,
                )
                solved = FakeResponse(request_url, json_data={"result": []})
                with (
                    patch(
                        f"quasarr.search.sources.{initials}.requests.get",
                        return_value=challenged,
                    ) as plain_get,
                    patch(
                        "quasarr.providers.cloudflare.is_flaresolverr_available",
                        return_value=True,
                    ),
                    patch(
                        "quasarr.providers.cloudflare.flaresolverr_create_session",
                        return_value="test-session",
                    ) as create_session,
                    patch(
                        "quasarr.providers.cloudflare.flaresolverr_get",
                        return_value=solved,
                    ) as flaresolverr_get,
                    patch(
                        "quasarr.providers.cloudflare.flaresolverr_destroy_session"
                    ) as destroy_session,
                ):
                    result = source_class().search(
                        _build_shared_state({initials: host}),
                        time.time(),
                        2000 if initials == "ff" else 5000,
                        "Synthetic Title",
                    )

                self.assertEqual([], result)
                plain_get.assert_called_once()
                flaresolverr_get.assert_called_once()
                create_session.assert_called_once()
                self.assertEqual(
                    "test-session", flaresolverr_get.call_args.kwargs["session_id"]
                )
                destroy_session.assert_called_once_with(ANY, "test-session")

    def test_blocked_search_without_flaresolverr_reports_normal_failure(self):
        challenge_html = "<title>Just a moment...</title>"
        for initials, source_class in self.source_cases:
            with self.subTest(source=initials):
                host = f"host-{initials}.invalid"
                challenged = FakeResponse(
                    f"https://{host}/api/v2/search",
                    text=challenge_html,
                    status_code=403,
                )
                with (
                    patch(
                        f"quasarr.search.sources.{initials}.requests.get",
                        return_value=challenged,
                    ),
                    patch(
                        "quasarr.providers.cloudflare.is_flaresolverr_available",
                        return_value=False,
                    ),
                    patch(
                        "quasarr.providers.cloudflare.flaresolverr_create_session"
                    ) as create_session,
                    patch(
                        "quasarr.providers.cloudflare.flaresolverr_get"
                    ) as flaresolverr_get,
                    patch(
                        "quasarr.providers.cloudflare.flaresolverr_destroy_session"
                    ) as destroy_session,
                    patch(
                        f"quasarr.search.sources.{initials}.mark_hostname_issue"
                    ) as mark_issue,
                ):
                    result = source_class().search(
                        _build_shared_state({initials: host}),
                        time.time(),
                        2000 if initials == "ff" else 5000,
                        "Synthetic Title",
                    )

                self.assertEqual([], result)
                mark_issue.assert_called_once()
                create_session.assert_not_called()
                flaresolverr_get.assert_not_called()
                destroy_session.assert_not_called()

    def test_lazy_session_reuses_one_flaresolverr_session(self):
        shared_state = _build_shared_state({})
        headers = {"User-Agent": "UnitTestAgent/1.0"}
        challenged = FakeResponse(
            "https://source.invalid/page",
            text="<title>Just a moment...</title>",
            status_code=403,
        )
        solved = FakeResponse("https://source.invalid/page", text="<html>ok</html>")
        plain_get = MagicMock(return_value=challenged)

        with (
            patch(
                "quasarr.providers.cloudflare.is_flaresolverr_available",
                return_value=True,
            ),
            patch(
                "quasarr.providers.cloudflare.flaresolverr_create_session",
                return_value="reused-session",
            ) as create_session,
            patch(
                "quasarr.providers.cloudflare.flaresolverr_get",
                return_value=solved,
            ) as flaresolverr_get,
            patch(
                "quasarr.providers.cloudflare.flaresolverr_destroy_session"
            ) as destroy_session,
        ):
            session = LazyFlareSolverrSession(shared_state)
            try:
                session.get(
                    "https://source.invalid/first",
                    headers,
                    10,
                    request_get=plain_get,
                )
                session.get(
                    "https://source.invalid/second",
                    headers,
                    10,
                    request_get=plain_get,
                )
            finally:
                session.close()

        create_session.assert_called_once()
        self.assertEqual(2, flaresolverr_get.call_count)
        self.assertEqual(
            ["reused-session", "reused-session"],
            [call.kwargs["session_id"] for call in flaresolverr_get.call_args_list],
        )
        destroy_session.assert_called_once_with(shared_state, "reused-session")

    def test_download_early_return_destroys_lazy_session(self):
        host = "host-ff.invalid"
        release_url = f"https://{host}/synthetic-release"
        challenged = FakeResponse(
            release_url,
            text="<title>Just a moment...</title>",
            status_code=403,
        )
        solved = FakeResponse(release_url, text="<html>no movie token</html>")

        with (
            patch(
                "quasarr.downloads.sources.ff.requests.get",
                return_value=challenged,
            ),
            patch(
                "quasarr.providers.cloudflare.is_flaresolverr_available",
                return_value=True,
            ),
            patch(
                "quasarr.providers.cloudflare.flaresolverr_create_session",
                return_value="download-session",
            ),
            patch(
                "quasarr.providers.cloudflare.flaresolverr_get",
                return_value=solved,
            ),
            patch(
                "quasarr.providers.cloudflare.flaresolverr_destroy_session"
            ) as destroy_session,
        ):
            result = FfDownloadSource().get_download_links(
                _build_shared_state({"ff": host}),
                release_url,
                [],
                "Synthetic.Release.1080p-GROUP",
                None,
            )

        self.assertEqual({"links": [], "imdb_id": None}, result)
        destroy_session.assert_called_once_with(ANY, "download-session")

    def test_ff_download_reuses_page_session_for_protected_redirect(self):
        host = "host-ff.invalid"
        release_url = f"https://{host}/synthetic-movie"
        api_url = f"https://{host}/api/v1/synthetic-token?filter="
        external_url = f"https://{host}/external/synthetic-link"
        protected_url = "https://protected.invalid/container/ff-synthetic"
        title = "Synthetic.Movie.2026.1080p.WEB-GROUP"
        challenge = "<title>Just a moment...</title>"
        release_html = "<script>initMovie('synthetic-token')</script>"
        api_html = f"""
            <div class="entry">
              <span class="morespec">{title}</span>
              <a class="dlb row" href="/external/synthetic-link">
                <div class="col"><span>DDownload</span></div>
              </a>
            </div>
        """
        plain_urls = []
        redirect_urls = []

        def plain_get(url, headers=None, timeout=None):
            plain_urls.append(url)
            return FakeResponse(url, text=challenge, status_code=403)

        class FakeSession:
            def get(self, url, allow_redirects=False, timeout=None, headers=None):
                redirect_urls.append((url, allow_redirects))
                return FakeResponse(url, text=challenge, status_code=403)

        def solved_get(shared_state, url, timeout=None, session_id=None):
            if url == release_url:
                body = release_html
                final_url = url
            elif url == api_url:
                body = json.dumps({"html": api_html})
                final_url = url
            elif url == external_url:
                body = ""
                final_url = protected_url
            else:
                raise AssertionError(f"Unexpected FlareSolverr URL: {url}")
            return FlareSolverrResponse(final_url, 200, {}, body)

        with (
            patch("quasarr.downloads.sources.ff.requests.get", side_effect=plain_get),
            patch(
                "quasarr.downloads.sources.ff.requests.Session",
                return_value=FakeSession(),
            ),
            patch(
                "quasarr.providers.cloudflare.is_flaresolverr_available",
                return_value=True,
            ),
            patch(
                "quasarr.providers.cloudflare.flaresolverr_create_session",
                return_value="shared-download-session",
            ) as create_session,
            patch(
                "quasarr.providers.cloudflare.flaresolverr_get",
                side_effect=solved_get,
            ) as flaresolverr_get,
            patch(
                "quasarr.providers.cloudflare.flaresolverr_destroy_session"
            ) as destroy_session,
            patch(
                "quasarr.downloads.sources.ff.detect_crypter_type",
                side_effect=lambda url: "filecrypt" if url == protected_url else None,
            ),
        ):
            result = FfDownloadSource().get_download_links(
                _build_shared_state({"ff": host}), release_url, [], title, None
            )

        self.assertEqual(
            {"links": [[protected_url, "ddownload"]], "imdb_id": None}, result
        )
        self.assertEqual([release_url], plain_urls)
        self.assertEqual([], redirect_urls)
        create_session.assert_called_once()
        self.assertEqual(
            ["shared-download-session"] * 3,
            [call.kwargs["session_id"] for call in flaresolverr_get.call_args_list],
        )
        destroy_session.assert_called_once_with(ANY, "shared-download-session")

    def test_sf_download_reuses_page_session_for_protected_redirect(self):
        host = "host-sf.invalid"
        release_url = f"https://{host}/synthetic-show/1"
        external_url = f"https://{host}/external/synthetic-link"
        protected_url = "https://protected.invalid/container/sf-synthetic"
        title = "Synthetic.Show.S01.LANGUAGE.1080p.WEB-GROUP"
        challenge = "<title>Just a moment...</title>"
        release_html = "<script>initSeason('synthetic-token', '')</script>"
        api_html = f"""
            <div class="details">
              <div><div><h3>Release</h3></div></div>
              <small>{title}</small>
              <a class="dlb row" href="/external/synthetic-link">DDownload</a>
            </div>
        """
        plain_urls = []
        redirect_urls = []

        def plain_get(url, headers=None, timeout=None):
            plain_urls.append(url)
            return FakeResponse(url, text=challenge, status_code=403)

        class FakeSession:
            def get(self, url, allow_redirects=False, timeout=None, headers=None):
                redirect_urls.append((url, allow_redirects))
                return FakeResponse(url, text=challenge, status_code=403)

        def solved_get(shared_state, url, timeout=None, session_id=None):
            if url == release_url:
                body = release_html
                final_url = url
            elif "/api/v1/synthetic-token/season/1" in url:
                body = json.dumps({"html": api_html})
                final_url = url
            elif url == external_url:
                body = ""
                final_url = protected_url
            else:
                raise AssertionError(f"Unexpected FlareSolverr URL: {url}")
            return FlareSolverrResponse(final_url, 200, {}, body)

        with (
            patch("quasarr.downloads.sources.sf.requests.get", side_effect=plain_get),
            patch(
                "quasarr.downloads.sources.sf.requests.Session",
                return_value=FakeSession(),
            ),
            patch(
                "quasarr.providers.cloudflare.is_flaresolverr_available",
                return_value=True,
            ),
            patch(
                "quasarr.providers.cloudflare.flaresolverr_create_session",
                return_value="shared-download-session",
            ) as create_session,
            patch(
                "quasarr.providers.cloudflare.flaresolverr_get",
                side_effect=solved_get,
            ) as flaresolverr_get,
            patch(
                "quasarr.providers.cloudflare.flaresolverr_destroy_session"
            ) as destroy_session,
            patch(
                "quasarr.downloads.sources.sf.detect_crypter_type",
                side_effect=lambda url: "filecrypt" if url == protected_url else None,
            ),
        ):
            result = SfDownloadSource().get_download_links(
                _build_shared_state({"sf": host}), release_url, [], title, None
            )

        self.assertEqual(
            {"links": [[protected_url, "filecrypt"]], "imdb_id": None}, result
        )
        self.assertEqual([release_url], plain_urls)
        self.assertEqual([], redirect_urls)
        create_session.assert_called_once()
        self.assertEqual(
            ["shared-download-session"] * 3,
            [call.kwargs["session_id"] for call in flaresolverr_get.call_args_list],
        )
        destroy_session.assert_called_once_with(ANY, "shared-download-session")

    def test_search_exception_destroys_lazy_session(self):
        host = "host-sf.invalid"
        challenged = FakeResponse(
            f"https://{host}/api/v2/search",
            text="<title>Just a moment...</title>",
            status_code=403,
        )

        with (
            patch(
                "quasarr.search.sources.sf.requests.get",
                return_value=challenged,
            ),
            patch(
                "quasarr.providers.cloudflare.is_flaresolverr_available",
                return_value=True,
            ),
            patch(
                "quasarr.providers.cloudflare.flaresolverr_create_session",
                return_value="failed-session",
            ),
            patch(
                "quasarr.providers.cloudflare.flaresolverr_get",
                side_effect=RuntimeError("synthetic solver failure"),
            ),
            patch(
                "quasarr.providers.cloudflare.flaresolverr_destroy_session"
            ) as destroy_session,
            patch("quasarr.search.sources.sf.mark_hostname_issue"),
        ):
            result = SfSearchSource().search(
                _build_shared_state({"sf": host}),
                time.time(),
                5000,
                "Synthetic Title",
            )

        self.assertEqual([], result)
        destroy_session.assert_called_once_with(ANY, "failed-session")


if __name__ == "__main__":
    unittest.main()
