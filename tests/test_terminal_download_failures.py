# -*- coding: utf-8 -*-

import json
import unittest
from unittest.mock import MagicMock, patch

from quasarr.downloads import download, process_links
from quasarr.downloads.packages import get_packages

SOURCE_URL = "https://source.invalid/releases/synthetic"
PACKAGE_ID = "Quasarr_tv_" + "a" * 32
TERMINAL_REASON = "Episode not present in link container"


def _shared_state():
    shared_state = MagicMock()
    shared_state.values = {
        "config": lambda section: {"xx": "source.invalid"},
        "external_address": "http://localhost:5678",
    }
    return shared_state


class TerminalDownloadFailureTests(unittest.TestCase):
    def test_terminal_source_error_is_persisted_without_protected_fallback(self):
        shared_state = _shared_state()
        failed_db = MagicMock()
        shared_state.get_db.return_value = failed_db
        source = MagicMock()
        source.get_download_links.return_value = {
            "links": [],
            "error": TERMINAL_REASON,
            "terminal": True,
        }

        with (
            patch(
                "quasarr.downloads.get_download_sources", return_value={"xx": source}
            ),
            patch("quasarr.downloads.get_download_category_mirrors", return_value=[]),
            patch("quasarr.downloads.download_category_exists", return_value=True),
            patch("quasarr.downloads.clear_hostname_issue"),
            patch("quasarr.downloads.mark_hostname_issue"),
            patch("quasarr.downloads.package_id_exists", return_value=False),
            patch("quasarr.downloads.store_protected_links") as store_protected,
            patch("quasarr.downloads.download_package") as download_package,
            patch("quasarr.downloads.StatsHelper"),
        ):
            result = download(
                shared_state,
                "Radarr/1.0",
                "tv",
                "Synthetic.Release",
                SOURCE_URL,
                1,
                None,
                None,
                "xx",
            )

        self.assertTrue(result["failed"])
        stored = failed_db.store.call_args.args[1]
        self.assertEqual(
            {"title": "Synthetic.Release", "error": TERMINAL_REASON},
            json.loads(json.loads(stored)),
        )
        store_protected.assert_not_called()
        download_package.assert_not_called()
        source.get_download_links.assert_called_once()

    def test_terminal_auto_decrypt_failure_fails_without_protected_fallback(self):
        shared_state = _shared_state()
        failed_db = MagicMock()
        shared_state.get_db.return_value = failed_db

        with (
            patch(
                "quasarr.downloads.filter_offline_links",
                side_effect=lambda links, **_: links,
            ),
            patch(
                "quasarr.downloads.decrypt_links_if_hide",
                return_value={
                    "status": "error",
                    "results": [],
                    "reason": TERMINAL_REASON,
                    "terminal": True,
                },
            ),
            patch("quasarr.downloads.store_protected_links") as store_protected,
            patch("quasarr.downloads.send_tracked_notification") as notify,
            patch("quasarr.downloads.download_package") as download_package,
            patch("quasarr.downloads.StatsHelper"),
        ):
            result = process_links(
                shared_state,
                {"links": [["https://hide.cx/container/synthetic", "hide"]]},
                "Synthetic.Release",
                None,
                PACKAGE_ID,
                None,
                SOURCE_URL,
                1,
                "XX",
            )

        self.assertTrue(result["failed"])
        stored = failed_db.store.call_args.args[1]
        self.assertEqual(
            {"title": "Synthetic.Release", "error": TERMINAL_REASON},
            json.loads(json.loads(stored)),
        )
        store_protected.assert_not_called()
        notify.assert_not_called()
        download_package.assert_not_called()

    def test_legacy_auto_decrypt_failure_keeps_protected_fallback(self):
        shared_state = _shared_state()

        with (
            patch(
                "quasarr.downloads.filter_offline_links",
                side_effect=lambda links, **_: links,
            ),
            patch(
                "quasarr.downloads.decrypt_links_if_hide",
                return_value={
                    "status": "error",
                    "results": [],
                },
            ),
            patch(
                "quasarr.downloads.store_protected_links",
                return_value={"success": True},
            ) as store_protected,
            patch("quasarr.downloads.send_tracked_notification", return_value={}),
            patch("quasarr.downloads.StatsHelper"),
        ):
            result = process_links(
                shared_state,
                {"links": [["https://hide.cx/container/synthetic", "hide"]]},
                "Synthetic.Release",
                None,
                PACKAGE_ID,
                None,
                SOURCE_URL,
                1,
                "XX",
            )

        self.assertTrue(result["success"])
        self.assertEqual(
            [["https://hide.cx/container/synthetic", "hide"]],
            store_protected.call_args.args[1],
        )

    def test_browser_unavailable_keeps_selected_hide_url_protected(self):
        shared_state = _shared_state()
        selected_url = "https://hide.cx/container/synthetic?season=2&episode=7"

        with (
            patch(
                "quasarr.downloads.filter_offline_links",
                side_effect=lambda links, **_: links,
            ),
            patch(
                "quasarr.downloads.decrypt_links_if_hide",
                return_value={
                    "status": "error",
                    "results": [],
                    "reason": "Hide episode selection requires FlareSolverr",
                    "terminal": False,
                },
            ),
            patch(
                "quasarr.downloads.store_protected_links",
                return_value={"success": True},
            ) as store_protected,
            patch("quasarr.downloads.send_tracked_notification", return_value={}),
            patch("quasarr.downloads.StatsHelper"),
        ):
            result = process_links(
                shared_state,
                {"links": [[selected_url, "hide"]]},
                "Synthetic.Release",
                None,
                PACKAGE_ID,
                None,
                SOURCE_URL,
                1,
                "XX",
            )

        self.assertTrue(result["success"])
        self.assertEqual([[selected_url, "hide"]], store_protected.call_args.args[1])

    def test_failed_history_surfaces_exact_terminal_error(self):
        shared_state = _shared_state()
        failed_db = MagicMock()
        failed_db.retrieve_all_titles.return_value = [
            (
                PACKAGE_ID,
                json.dumps(
                    json.dumps(
                        {
                            "title": "Synthetic.Release",
                            "error": TERMINAL_REASON,
                        }
                    )
                ),
            )
        ]
        protected_db = MagicMock()
        protected_db.retrieve_all_titles.return_value = []
        shared_state.get_db.side_effect = lambda table: (
            failed_db if table == "failed" else protected_db
        )
        cache = MagicMock()
        cache.linkgrabber_packages = []
        cache.linkgrabber_links = []
        cache.downloader_packages = []
        cache.downloader_links = []
        cache.is_collecting = False

        with (
            patch("quasarr.downloads.packages.JDPackageCache", return_value=cache),
            patch(
                "quasarr.downloads.packages.get_download_category_from_package_id",
                return_value="tv",
            ),
        ):
            result = get_packages(shared_state)

        self.assertEqual(1, len(result["history"]))
        self.assertEqual(TERMINAL_REASON, result["history"][0]["fail_message"])


if __name__ == "__main__":
    unittest.main()
