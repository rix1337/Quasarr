# -*- coding: utf-8 -*-

import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from quasarr.downloads import _drop_disabled_crypters, process_links

FILECRYPT_URL = "https://filecrypt.invalid/Container/ABC123"
TOLINK_URL = "https://tolink.invalid/f/example-token"
HIDE_URL = "https://hide.invalid/container/example-token"
PACKAGE_ID = "Quasarr_tv_" + "a" * 32


def _build_shared_state(filecrypt_enabled=True, **enabled):
    shared_state = MagicMock()
    shared_state.values = {
        "crypters_enabled": {"filecrypt": filecrypt_enabled, **enabled},
        "external_address": "http://localhost:5678",
    }
    return shared_state


class DropDisabledCryptersTests(unittest.TestCase):
    def test_drops_filecrypt_only_link_when_disabled(self):
        shared_state = _build_shared_state(filecrypt_enabled=False)
        classified = {
            "direct": [],
            "auto": [],
            "protected": [[FILECRYPT_URL, "filecrypt"]],
        }

        result, _ = _drop_disabled_crypters(shared_state, classified, "Example.Title")

        self.assertEqual([], result["protected"])

    def test_keeps_other_protected_link_when_disabled(self):
        shared_state = _build_shared_state(filecrypt_enabled=False)
        classified = {
            "direct": [],
            "auto": [],
            "protected": [
                [FILECRYPT_URL, "filecrypt"],
                [TOLINK_URL, "rapidgator"],
            ],
        }

        result, _ = _drop_disabled_crypters(shared_state, classified, "Example.Title")

        self.assertEqual([[TOLINK_URL, "rapidgator"]], result["protected"])

    def test_keeps_filecrypt_link_when_enabled(self):
        shared_state = _build_shared_state(filecrypt_enabled=True)
        classified = {
            "direct": [],
            "auto": [],
            "protected": [[FILECRYPT_URL, "filecrypt"]],
        }

        result, _ = _drop_disabled_crypters(shared_state, classified, "Example.Title")

        self.assertEqual([[FILECRYPT_URL, "filecrypt"]], result["protected"])

    def test_drops_hide_and_keeps_hostname_links_when_disabled(self):
        shared_state = _build_shared_state(hide=False)
        classified = {
            "direct": [],
            "auto": [[HIDE_URL, "rapidgator"]],
            "protected": [
                ["https://source.invalid/release-1.html", "he"],
                [TOLINK_URL, "rapidgator"],
            ],
        }

        result, skipped = _drop_disabled_crypters(
            shared_state, classified, "Example.Title"
        )

        self.assertEqual([], result["auto"])
        self.assertEqual(
            [
                ["https://source.invalid/release-1.html", "he"],
                [TOLINK_URL, "rapidgator"],
            ],
            result["protected"],
        )
        self.assertEqual(["Hide"], skipped)


class ProcessLinksCrypterKillSwitchTests(unittest.TestCase):
    def _run_process_links(self, shared_state, links):
        source_result = {"links": links}

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "quasarr.downloads.filter_offline_links",
                    side_effect=lambda links, **_: links,
                )
            )
            mock_fail = stack.enter_context(
                patch(
                    "quasarr.downloads.fail",
                    return_value={"success": True, "failed": True},
                )
            )
            mock_send_tracked = stack.enter_context(
                patch(
                    "quasarr.downloads.send_tracked_notification",
                    return_value={},
                )
            )
            mock_store_protected = stack.enter_context(
                patch(
                    "quasarr.downloads.store_protected_links",
                    return_value={"success": True},
                )
            )

            result = process_links(
                shared_state,
                source_result,
                "Example.Title.S01E01-GRP",
                None,
                PACKAGE_ID,
                None,
                "https://source.invalid/release-1.html",
                1024,
                "XX",
            )

        return result, mock_fail, mock_send_tracked, mock_store_protected

    def test_disabled_and_only_filecrypt_link_fails_package(self):
        shared_state = _build_shared_state(filecrypt_enabled=False)
        links = [[FILECRYPT_URL, "filecrypt"]]

        result, mock_fail, mock_send_tracked, mock_store_protected = (
            self._run_process_links(shared_state, links)
        )

        mock_fail.assert_called_once()
        self.assertIn(
            "FileCrypt turned off in settings", mock_fail.call_args.kwargs["reason"]
        )
        mock_send_tracked.assert_not_called()
        mock_store_protected.assert_not_called()
        self.assertTrue(result.get("failed"))

    def test_disabled_with_mirror_keeps_other_protected_link(self):
        shared_state = _build_shared_state(filecrypt_enabled=False)
        links = [
            [FILECRYPT_URL, "filecrypt"],
            [TOLINK_URL, "rapidgator"],
        ]

        result, mock_fail, mock_send_tracked, mock_store_protected = (
            self._run_process_links(shared_state, links)
        )

        mock_fail.assert_not_called()
        mock_store_protected.assert_called_once()
        stored_links = mock_store_protected.call_args.args[1]
        self.assertEqual([[TOLINK_URL, "rapidgator"]], stored_links)
        self.assertTrue(result["success"])

    def test_enabled_by_default_stores_filecrypt_link(self):
        shared_state = _build_shared_state(filecrypt_enabled=True)
        links = [[FILECRYPT_URL, "filecrypt"]]

        result, mock_fail, mock_send_tracked, mock_store_protected = (
            self._run_process_links(shared_state, links)
        )

        mock_fail.assert_not_called()
        mock_store_protected.assert_called_once()
        stored_links = mock_store_protected.call_args.args[1]
        self.assertEqual([[FILECRYPT_URL, "filecrypt"]], stored_links)
        self.assertTrue(result["success"])


if __name__ == "__main__":
    unittest.main()
