# -*- coding: utf-8 -*-

import unittest
from unittest.mock import MagicMock, call, patch

from quasarr.downloads import fail, process_links


class DownloadFailureLoggingTests(unittest.TestCase):
    def test_failed_download_is_a_warning_not_an_error(self):
        shared_state = MagicMock()
        stats = MagicMock()

        with (
            patch("quasarr.downloads.StatsHelper", return_value=stats),
            patch("quasarr.downloads.error") as error_log,
            patch("quasarr.downloads.warn") as warn_log,
        ):
            result = fail(
                "Synthetic.Release",
                "synthetic-package-id",
                shared_state,
                reason="Synthetic redirect failure",
            )

        self.assertEqual(
            {"success": True, "title": "Synthetic.Release", "failed": True}, result
        )
        error_log.assert_not_called()
        self.assertEqual(
            [
                call("Reason for failure: Synthetic redirect failure"),
                call('Package "Synthetic.Release" marked as failed!'),
            ],
            warn_log.call_args_list,
        )
        stats.increment_failed_downloads.assert_called_once_with()
        shared_state.get_db.return_value.store.assert_called_once()

    def test_failure_persistence_exception_logs_error(self):
        shared_state = MagicMock()
        shared_state.get_db.side_effect = RuntimeError("synthetic database failure")

        with (
            patch("quasarr.downloads.StatsHelper"),
            patch("quasarr.downloads.error") as error_log,
            patch("quasarr.downloads.warn") as warn_log,
        ):
            fail(
                "Synthetic.Release",
                "synthetic-package-id",
                shared_state,
                reason="Synthetic redirect failure",
            )

        error_log.assert_called_once_with(
            'Error marking package "synthetic-package-id" as failed: '
            "synthetic database failure"
        )
        warn_log.assert_called_once_with(
            "Reason for failure: Synthetic redirect failure"
        )

    def test_only_filecrypt_404_page_is_an_ip_ban(self):
        reasons = {}
        for url in (
            "https://filecrypt.cc/404.html",
            "https://crypter.invalid/404.html",
        ):
            with patch("quasarr.downloads.fail") as failed:
                process_links(
                    MagicMock(),
                    {"links": [[url, "rapidgator"]]},
                    "Synthetic.Release",
                    "",
                    "synthetic-package-id",
                    None,
                    "https://source.invalid/release",
                    0,
                    "XX",
                )
            reasons[url] = failed.call_args.kwargs["reason"]

        self.assertIn(
            "filecrypt banned the IP", reasons["https://filecrypt.cc/404.html"]
        )
        self.assertIn("lead to a 404 page", reasons["https://crypter.invalid/404.html"])


if __name__ == "__main__":
    unittest.main()
