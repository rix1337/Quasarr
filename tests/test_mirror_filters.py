# -*- coding: utf-8 -*-

import json
import unittest
from unittest.mock import MagicMock, patch

from quasarr.downloads import submit_final_download_urls
from quasarr.downloads.mirror_filters import (
    filter_final_download_urls,
    normalize_mirror_token,
)


class NormalizeMirrorTokenTests(unittest.TestCase):
    def test_normalizes_whitelist_names(self):
        self.assertEqual(normalize_mirror_token("DDownload"), "ddownload")
        self.assertEqual(normalize_mirror_token("Keep2Share"), "keep2share")

    def test_normalizes_alias_domains_and_subdomains(self):
        cases = {
            "https://api.ddl.to/container": "ddownload",
            "https://s42.rg.to/file/abc": "rapidgator",
            "https://subdomain.nitroflare.com/view/test": "nitroflare",
            "https://download.ifolder.com.ua/file/123": "turbobit",
            "https://mega.co.nz/file/test": "mega",
            "https://clickndownload.space/abcdef": "clicknupload",
        }

        for raw_value, expected in cases.items():
            with self.subTest(raw_value=raw_value):
                self.assertEqual(normalize_mirror_token(raw_value), expected)


class FilterFinalDownloadUrlsTests(unittest.TestCase):
    def test_keeps_only_allowed_final_urls(self):
        result = filter_final_download_urls(
            [
                "https://rapidgator.net/file/abc",
                "https://cdn.ddownload.com/xyz",
                "https://nitroflare.com/view/test",
            ],
            ["DDownload"],
        )

        self.assertEqual(result["urls"], ["https://cdn.ddownload.com/xyz"])
        self.assertEqual(
            {item["token"] for item in result["dropped"]},
            {"rapidgator", "nitroflare"},
        )


class SubmitFinalDownloadUrlsTests(unittest.TestCase):
    @patch("quasarr.downloads.download_package", return_value=True)
    @patch(
        "quasarr.downloads.get_download_category_mirrors", return_value=["DDownload"]
    )
    @patch("quasarr.downloads.get_download_category_from_package_id", return_value="tv")
    def test_submit_uses_filtered_urls(
        self,
        mock_get_category,
        mock_get_mirrors,
        mock_download_package,
    ):
        shared_state = MagicMock()

        result = submit_final_download_urls(
            shared_state,
            [
                "https://rapidgator.net/file/abc",
                "https://mirror.ddownload.com/file/def",
            ],
            "Example.Release",
            "",
            "Quasarr_tv_deadbeefdeadbeefdeadbeefdeadbeef",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["links"], ["https://mirror.ddownload.com/file/def"])
        mock_download_package.assert_called_once_with(
            ["https://mirror.ddownload.com/file/def"],
            "Example.Release",
            "",
            "Quasarr_tv_deadbeefdeadbeefdeadbeefdeadbeef",
            shared_state,
        )

    @patch("quasarr.downloads.download_package")
    @patch("quasarr.downloads.fail", return_value={"success": True, "failed": True})
    @patch(
        "quasarr.downloads.get_download_category_mirrors", return_value=["DDownload"]
    )
    @patch("quasarr.downloads.get_download_category_from_package_id", return_value="tv")
    def test_submit_persists_failure_when_no_allowed_links_remain(
        self,
        mock_get_category,
        mock_get_mirrors,
        mock_fail,
        mock_download_package,
    ):
        protected_db = MagicMock()
        protected_db.retrieve.return_value = json.dumps(
            {
                "title": "Example.Release",
                "notifications": {"discord": {"message_id": "123"}},
            }
        )
        shared_state = MagicMock()
        shared_state.get_db.return_value = protected_db

        with patch("quasarr.downloads.update_release_notification") as mock_update:
            result = submit_final_download_urls(
                shared_state,
                ["https://rapidgator.net/file/abc"],
                "Example.Release",
                "",
                "Quasarr_tv_deadbeefdeadbeefdeadbeefdeadbeef",
                remove_protected=True,
            )

        self.assertFalse(result["success"])
        self.assertTrue(result["persisted_failure"])
        protected_db.delete.assert_called_once_with(
            "Quasarr_tv_deadbeefdeadbeefdeadbeefdeadbeef"
        )
        mock_fail.assert_called_once()
        mock_download_package.assert_not_called()
        self.assertEqual("failed", mock_update.call_args.args[2].value)
        self.assertIn("reason", mock_update.call_args.kwargs["details"])

    @patch("quasarr.downloads.download_package", return_value=True)
    @patch(
        "quasarr.downloads.get_download_category_mirrors", return_value=["DDownload"]
    )
    @patch("quasarr.downloads.get_download_category_from_package_id", return_value="tv")
    def test_submit_removes_protected_package_after_success_when_requested(
        self,
        mock_get_category,
        mock_get_mirrors,
        mock_download_package,
    ):
        protected_db = MagicMock()
        protected_db.retrieve.return_value = json.dumps(
            {
                "title": "Example.Release",
                "notifications": {"discord": {"message_id": "123"}},
            }
        )
        shared_state = MagicMock()
        shared_state.get_db.return_value = protected_db

        with patch("quasarr.downloads.update_release_notification") as mock_update:
            result = submit_final_download_urls(
                shared_state,
                ["https://mirror.ddownload.com/file/def"],
                "Example.Release",
                "",
                "Quasarr_tv_deadbeefdeadbeefdeadbeefdeadbeef",
                remove_protected=True,
                notification_details={"method": "manual"},
            )

        self.assertTrue(result["success"])
        protected_db.delete.assert_called_once_with(
            "Quasarr_tv_deadbeefdeadbeefdeadbeefdeadbeef"
        )
        mock_download_package.assert_called_once()
        self.assertEqual("solved", mock_update.call_args.args[2].value)
        self.assertEqual(
            {"method": "manual"},
            mock_update.call_args.kwargs["details"],
        )


if __name__ == "__main__":
    unittest.main()
