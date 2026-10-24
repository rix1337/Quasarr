import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bs4 import BeautifulSoup

from quasarr.constants import SEARCH_CAT_MOVIES
from quasarr.downloads.sources.al import _parse_info_from_download_item
from quasarr.search.sources.al import Source


def make_shared_state():
    def config(section):
        if section == "Hostnames":
            return {"al": "source.invalid"}
        return {}

    state = SimpleNamespace(
        values={
            "config": config,
            "internal_address": "http://127.0.0.1:8080",
            "user_agent": "TestAgent/1.0",
        }
    )
    state.update = lambda key, value: state.values.__setitem__(key, value)
    return state


def parse_tab(html):
    soup = BeautifulSoup(html, "html.parser")
    return _parse_info_from_download_item(soup.select_one("div[id^=download_]"), soup)


class AlDownloadMetadataTests(unittest.TestCase):
    def test_download_item_parses_metadata_rows(self):
        release = parse_tab(
            """
            <div id="download_1">
              <table>
                <tr><th><i class="fa fa-info"></i></th><td>Invented Title 2160p - GROUP</td></tr>
                <tr><th><i class="fa fa-desktop"></i></th><td>3840 x 2160</td></tr>
                <tr><th><i class="fa fa-volume-up"></i></th>
                    <td><i class="flag flag-de"></i><i class="flag flag-en"></i></td></tr>
                <tr><th><i class="fa fa-closed-captioning"></i></th>
                    <td><i class="flag flag-de"></i></td></tr>
                <tr><th><i class="fa fa-child"></i></th><td>Test - Group</td></tr>
              </table>
            </div>
            """
        )

        self.assertEqual(release.release_title, "Invented.Title.2160p.GerSub-GROUP")
        self.assertEqual(release.resolution, "2160p")
        self.assertEqual(release.audio_langs, ["German", "English"])
        self.assertEqual(release.subtitle_langs, ["German"])
        self.assertEqual(release.release_group, "TestGroup")

    def test_download_item_preserves_defaults_when_rows_missing(self):
        release = parse_tab('<div id="download_1"><table></table></div>')

        self.assertIsNone(release.release_title)
        self.assertEqual(release.resolution, "1080p")
        self.assertEqual(release.audio_langs, [])
        self.assertEqual(release.subtitle_langs, [])
        self.assertEqual(release.audio, "")
        self.assertEqual(release.video, "x264")
        self.assertEqual(release.source, "WEB-DL")
        self.assertEqual(release.release_group, "")

    def test_download_item_parses_audio_codec(self):
        release = parse_tab(
            """
            <div id="download_1"><table>
              <tr><th><i class="fa fa-info"></i></th><td>Invented.WEB-DL.AAC.HEVC-GROUP</td></tr>
            </table></div>
            """
        )
        self.assertEqual(release.audio, "AAC")
        self.assertEqual(release.video, "x265")


class AlSearchMetadataTests(unittest.TestCase):
    def test_search_emits_release_with_date_and_size(self):
        listing_html = """
        <div class="panel panel-default"><div class="panel-body">
          <h4 class="title-list"><a href="https://source.invalid/media/invented">Invented Feature</a></h4>
          <div class="label-group"><a href="/anime-movies">Movie</a></div>
        </div></div>
        """
        details_html = """
        <div id="download_1"><table>
          <tr><th><i class="fa fa-info"></i></th><td>Invented.Feature.WEB-DL.AAC.1080p-GROUP</td></tr>
          <tr><th><i class="fa fa-calendar-alt"></i></th><td class="modified">23.09.2025 14:15</td></tr>
          <tr><th><i class="fa fa-hdd"></i></th><td>1.5 GB</td></tr>
        </table></div>
        """

        class Response:
            history = []

            def __init__(self, text):
                self.text = text
                self.content = text.encode()

            def raise_for_status(self):
                return None

        state = make_shared_state()

        def fetch(_state, method, target_url, **_kwargs):
            if "/search?" in target_url:
                return Response(listing_html)
            if target_url == "https://source.invalid/media/invented":
                return Response(details_html)
            raise AssertionError(f"unexpected URL: {target_url}")

        with (
            patch("quasarr.search.sources.al.fetch_via_requests_session", fetch),
            patch(
                "quasarr.search.sources.al.generate_download_link",
                return_value="synthetic-link",
            ),
            patch("quasarr.search.sources.al.clear_hostname_issue"),
            patch("quasarr.search.sources.al.mark_hostname_issue"),
            patch("quasarr.search.sources.al.invalidate_session"),
        ):
            releases = Source().search(
                state, time.time(), SEARCH_CAT_MOVIES, search_string="Invented Feature"
            )

        self.assertEqual(len(releases), 1)
        details = releases[0]["details"]
        self.assertEqual(details["date"], "Tue, 23 Sep 2025 14:15:00 +0000")
        self.assertEqual(details["size"], int(1.5 * 1024 * 1024 * 1024))
        self.assertEqual(details["title"], "Invented.Feature.WEB-DL.AAC.1080p-GROUP")


if __name__ == "__main__":
    unittest.main()
