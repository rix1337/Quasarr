# -*- coding: utf-8 -*-

import unittest
from unittest.mock import MagicMock, patch

from quasarr.downloads import download, generate_deterministic_package_id
from quasarr.downloads.sources.wx import Source as WxSource


class PackageIdentityTests(unittest.TestCase):
    def test_legacy_package_id_is_unchanged_without_identity(self):
        with patch("quasarr.downloads.download_category_exists", return_value=True):
            self.assertEqual(
                "Quasarr_tv_cd9ac0e0a48e49efa5cff207c8b5806d",
                generate_deterministic_package_id(
                    "Synthetic.Release", "wx", "sonarr", "tv"
                ),
            )

    def test_wx_identity_is_stable_and_rejects_ambiguous_selection(self):
        source = WxSource()
        first = source.get_package_identity(
            "https://wx.invalid/detail/show?episode=3&release=PACK-A&season=2&auth=one"
        )
        second = source.get_package_identity(
            "https://wx.invalid/detail/show?auth=two&season=2&release=PACK-A&episode=3"
        )

        self.assertEqual("PACK-A:S02E03", first)
        self.assertEqual(first, second)
        self.assertIsNone(
            source.get_package_identity(
                "https://wx.invalid/detail/show?release=PACK-A&release=PACK-B&season=2&episode=3"
            )
        )
        self.assertIsNone(
            source.get_package_identity(
                "https://wx.invalid/detail/show?release=PACK-A&season=bad&episode=3"
            )
        )

    def test_distinct_wx_uids_do_not_hit_failed_history_collision(self):
        class FakeDatabase:
            def __init__(self):
                self.entries = {}

            def retrieve(self, package_id):
                return self.entries.get(package_id)

            def store(self, package_id, value):
                self.entries[package_id] = value

        shared_state = MagicMock()
        failed_db = FakeDatabase()
        shared_state.values = {
            "config": lambda section: {"wx": "wx.invalid"},
            "external_address": "http://localhost:5678",
        }
        protected_db = FakeDatabase()
        shared_state.get_db.side_effect = lambda name: (
            failed_db if name == "failed" else protected_db
        )
        packages = {"queue": [], "history": []}
        shared_state.run_device_request.return_value = packages
        source = WxSource()

        def process(_state, source_result, _title, _password, package_id, *_args):
            if source_result.get("terminal"):
                failed_db.store(package_id, "failed")
                return {"success": True, "failed": True}
            packages["queue"].append({"nzo_id": package_id})
            return {"success": True}

        with (
            patch(
                "quasarr.downloads.get_download_sources", return_value={"wx": source}
            ),
            patch("quasarr.downloads.get_download_category_mirrors", return_value=[]),
            patch("quasarr.downloads.download_category_exists", return_value=True),
            patch("quasarr.downloads.clear_hostname_issue"),
            patch.object(
                source,
                "get_download_links",
                side_effect=[
                    {"links": [], "error": "synthetic failure", "terminal": True},
                    {"links": [["https://direct.invalid/file", "hoster"]]},
                    {"links": [["https://direct.invalid/file", "hoster"]]},
                ],
            ) as get_links,
            patch(
                "quasarr.downloads.process_links", side_effect=process
            ) as process_links_mock,
        ):
            first = download(
                shared_state,
                "Sonarr/1.0",
                "tv",
                "Synthetic.Show.S02E03",
                "https://wx.invalid/detail/show?release=PACK-A&season=2&episode=3",
                1,
                None,
                None,
                None,
            )
            second = download(
                shared_state,
                "Sonarr/1.0",
                "tv",
                "Synthetic.Show.S02E03",
                "https://wx.invalid/detail/show?release=PACK-B&season=2&episode=3",
                1,
                None,
                None,
                None,
            )
            retry = download(
                shared_state,
                "Sonarr/1.0",
                "tv",
                "Synthetic.Show.S02E03",
                "https://wx.invalid/detail/show?episode=3&season=2&release=PACK-B&auth=changed",
                1,
                None,
                None,
                None,
            )

        self.assertTrue(first["failed"])
        self.assertTrue(second["success"])
        self.assertTrue(retry["success"])
        self.assertNotIn("failed", retry)
        self.assertNotEqual(first["package_id"], second["package_id"])
        self.assertEqual(second["package_id"], retry["package_id"])
        self.assertEqual(1, len(packages["queue"]))
        self.assertEqual(3, get_links.call_count)
        self.assertEqual(2, process_links_mock.call_count)

    def test_wx_identity_survives_resolution_failure_with_or_without_source_key(self):
        shared_state = MagicMock()
        shared_state.values = {"config": lambda section: {"wx": "wx.invalid"}}
        source = WxSource()
        with (
            patch(
                "quasarr.downloads.get_download_sources", return_value={"wx": source}
            ),
            patch("quasarr.downloads.get_download_category_mirrors", return_value=[]),
            patch("quasarr.downloads.download_category_exists", return_value=True),
            patch("quasarr.downloads.clear_hostname_issue"),
            patch("quasarr.downloads.mark_hostname_issue"),
            patch("quasarr.downloads.package_id_exists", return_value=False),
            patch(
                "quasarr.downloads.fail", return_value={"success": True, "failed": True}
            ),
            patch("quasarr.downloads.process_links", return_value={"success": True}),
            patch.object(source, "get_download_links") as get_links,
        ):
            ids = []
            for source_key in (None, "wx"):
                for outcome in (
                    {"links": []},
                    RuntimeError("synthetic"),
                    {"links": [["https://direct.invalid/file", "hoster"]]},
                ):
                    with self.subTest(source_key=source_key, outcome=outcome):
                        get_links.side_effect = [outcome]
                        result = download(
                            shared_state,
                            "Sonarr/1.0",
                            "tv",
                            "Synthetic.Show.S02E03",
                            "https://wx.invalid/detail/show?release=PACK-A&season=2&episode=3",
                            1,
                            None,
                            None,
                            source_key,
                        )
                        ids.append(result["package_id"])
            self.assertEqual(1, len(set(ids)))

    def test_identity_hook_failure_keeps_source_and_legacy_hash(self):
        shared_state = MagicMock()
        shared_state.values = {
            "config": lambda section: {"wx": "wx.invalid"},
            "external_address": "http://localhost:5678",
        }
        source = WxSource()
        with (
            patch(
                "quasarr.downloads.get_download_sources", return_value={"wx": source}
            ),
            patch("quasarr.downloads.get_download_category_mirrors", return_value=[]),
            patch("quasarr.downloads.download_category_exists", return_value=True),
            patch("quasarr.downloads.clear_hostname_issue"),
            patch.object(
                source, "get_package_identity", side_effect=RuntimeError("synthetic")
            ),
            patch.object(
                source,
                "get_download_links",
                return_value={"links": [], "error": "synthetic", "terminal": True},
            ) as get_links,
            patch("quasarr.downloads.package_id_exists", return_value=False),
            patch(
                "quasarr.downloads.fail", return_value={"success": True, "failed": True}
            ),
        ):
            result = download(
                shared_state,
                "Sonarr/1.0",
                "tv",
                "Synthetic.Release",
                "https://wx.invalid/detail/show",
                1,
                None,
                None,
                None,
            )

        self.assertTrue(result["failed"])
        self.assertEqual(
            "Quasarr_tv_cd9ac0e0a48e49efa5cff207c8b5806d", result["package_id"]
        )
        get_links.assert_called_once()


if __name__ == "__main__":
    unittest.main()
