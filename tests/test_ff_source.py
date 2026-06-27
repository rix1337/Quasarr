# -*- coding: utf-8 -*-

import time
import unittest
from unittest.mock import MagicMock, patch

from quasarr.downloads.sources.ff import Source as FfDownloadSource
from quasarr.search.sources.ff import Source as FfSearchSource


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


if __name__ == "__main__":
    unittest.main()
