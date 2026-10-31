# -*- coding: utf-8 -*-

import json
import unittest
from unittest import mock

from bottle import Bottle, HTTPError

from quasarr.api.sponsors_helper import (
    normalize_helper_supported_urls,
    select_helper_package,
    setup_sponsors_helper_routes,
)


class SponsorsHelperApiTests(unittest.TestCase):
    @staticmethod
    def _filecrypt_package():
        return {
            "title": "Synthetic.Filecrypt.Release",
            "links": [["https://filecrypt.invalid/container/synthetic", "filecrypt"]],
            "password": "synthetic-password",
            "metadata": {"source": "synthetic"},
        }

    def test_filecrypt_fail_callback_disables_package_by_id(self):
        app = Bottle()
        setup_sponsors_helper_routes(app)
        route = next(
            route for route in app.routes if route.rule == "/sponsors_helper/api/fail/"
        )
        package_id = "Quasarr_movies_" + "c" * 32
        package_data = self._filecrypt_package()
        protected_db = mock.Mock()
        protected_db.retrieve.return_value = json.dumps(package_data)
        protected_db.retrieve_all_titles.return_value = [
            (package_id, json.dumps(package_data))
        ]
        payload = {"package_id": package_id, "reason": "Synthetic failure"}
        stats = mock.Mock()

        with (
            mock.patch(
                "quasarr.api.sponsors_helper.shared_state.values",
                {"helper_active": True, "helper_last_seen": 0},
            ),
            mock.patch(
                "quasarr.api.sponsors_helper.shared_state.get_db",
                return_value=protected_db,
            ),
            mock.patch("quasarr.api.sponsors_helper.request", mock.Mock(json=payload)),
            mock.patch("quasarr.api.sponsors_helper.StatsHelper", return_value=stats),
            mock.patch("quasarr.api.sponsors_helper.fail") as fail,
            mock.patch(
                "quasarr.api.sponsors_helper.update_release_notification"
            ) as notification,
        ):
            result = route.callback()

        stored_data = json.loads(protected_db.update_store.call_args.args[1])
        self.assertTrue(stored_data["disabled"])
        self.assertEqual(package_data["links"], stored_data["links"])
        self.assertEqual(package_data["password"], stored_data["password"])
        self.assertEqual(package_data["metadata"], stored_data["metadata"])
        protected_db.delete.assert_not_called()
        fail.assert_not_called()
        stats.increment_failed_decryptions_automatic.assert_called_once_with()
        stats.increment_captcha_decryptions_automatic.assert_not_called()
        notification.assert_called_once()
        self.assertEqual("DISABLED", notification.call_args.args[2].name)
        self.assertEqual(
            {
                "success": False,
                "failed": False,
                "manual_required": True,
                "reason": "Synthetic failure",
            },
            result,
        )

    def test_filecrypt_fail_callback_resolves_package_by_title(self):
        app = Bottle()
        setup_sponsors_helper_routes(app)
        route = next(
            route for route in app.routes if route.rule == "/sponsors_helper/api/fail/"
        )
        package_id = "Quasarr_movies_" + "d" * 32
        package_data = self._filecrypt_package()
        protected_db = mock.Mock()
        protected_db.retrieve_all_titles.return_value = [
            (package_id, json.dumps(package_data))
        ]
        protected_db.retrieve.return_value = json.dumps(package_data)
        stats = mock.Mock()
        with (
            mock.patch(
                "quasarr.api.sponsors_helper.shared_state.values",
                {"helper_active": True, "helper_last_seen": 0},
            ),
            mock.patch(
                "quasarr.api.sponsors_helper.shared_state.get_db",
                return_value=protected_db,
            ),
            mock.patch(
                "quasarr.api.sponsors_helper.request",
                mock.Mock(
                    json={"title": package_data["title"], "reason": "Synthetic failure"}
                ),
            ),
            mock.patch("quasarr.api.sponsors_helper.StatsHelper", return_value=stats),
            mock.patch("quasarr.api.sponsors_helper.fail") as fail,
            mock.patch(
                "quasarr.api.sponsors_helper.update_release_notification"
            ) as notification,
        ):
            route.callback()

        self.assertTrue(
            json.loads(protected_db.update_store.call_args.args[1])["disabled"]
        )
        protected_db.delete.assert_not_called()
        fail.assert_not_called()
        stats.increment_failed_decryptions_automatic.assert_called_once_with()
        stats.increment_captcha_decryptions_automatic.assert_not_called()
        notification.assert_called_once()

    def test_filecrypt_download_without_usable_urls_disables_package(self):
        app = Bottle()
        setup_sponsors_helper_routes(app)
        route = next(
            route
            for route in app.routes
            if route.rule == "/sponsors_helper/api/download/"
        )
        package_id = "Quasarr_movies_" + "e" * 32
        package_data = self._filecrypt_package()
        for urls in ([], "not-a-url"):
            with self.subTest(urls=urls):
                protected_db = mock.Mock()
                protected_db.retrieve.return_value = json.dumps(package_data)
                payload = {
                    "name": package_data["title"],
                    "package_id": package_id,
                    "urls": urls,
                    "password": "",
                    "notification": {"solvers": []},
                }
                stats = mock.Mock()
                with (
                    mock.patch(
                        "quasarr.api.sponsors_helper.shared_state.values",
                        {"helper_active": True, "helper_last_seen": 0},
                    ),
                    mock.patch(
                        "quasarr.api.sponsors_helper.shared_state.get_db",
                        return_value=protected_db,
                    ),
                    mock.patch(
                        "quasarr.api.sponsors_helper.request", mock.Mock(json=payload)
                    ),
                    mock.patch(
                        "quasarr.api.sponsors_helper.StatsHelper", return_value=stats
                    ),
                    mock.patch("quasarr.api.sponsors_helper.fail") as fail,
                    mock.patch(
                        "quasarr.api.sponsors_helper.update_release_notification"
                    ) as notification,
                    mock.patch(
                        "quasarr.api.sponsors_helper.submit_final_download_urls"
                    ) as submit,
                ):
                    result = route.callback()

                reason = (
                    "SponsorsHelper returned no final download links."
                    if isinstance(urls, list)
                    else "SponsorsHelper returned an invalid download payload."
                )
                self.assertEqual(
                    {
                        "success": False,
                        "failed": False,
                        "manual_required": True,
                        "reason": reason,
                    },
                    result,
                )
                self.assertTrue(
                    json.loads(protected_db.update_store.call_args.args[1])["disabled"]
                )
                protected_db.delete.assert_not_called()
                fail.assert_not_called()
                stats.increment_failed_decryptions_automatic.assert_called_once_with()
                stats.increment_captcha_decryptions_automatic.assert_not_called()
                notification.assert_called_once()
                self.assertEqual("DISABLED", notification.call_args.args[2].name)
                submit.assert_not_called()

    def test_select_helper_package_skips_disabled_package(self):
        packages = [
            (
                "pkg-disabled",
                json.dumps(
                    {
                        "title": "Synthetic.Disabled",
                        "disabled": True,
                        "links": [["https://x.invalid/file", "x"]],
                    }
                ),
            ),
            (
                "pkg-ready",
                json.dumps(
                    {
                        "title": "Synthetic.Ready",
                        "links": [["https://x.invalid/file", "x"]],
                    }
                ),
            ),
        ]
        package_id, data, _ = select_helper_package(packages, [])
        self.assertEqual("pkg-ready", package_id)
        self.assertEqual("Synthetic.Ready", data["title"])

    def test_nonfilecrypt_fail_callback_keeps_legacy_failure_behavior(self):
        app = Bottle()
        setup_sponsors_helper_routes(app)
        route = next(
            route for route in app.routes if route.rule == "/sponsors_helper/api/fail/"
        )
        package_id = "Quasarr_movies_" + "f" * 32
        package_data = {
            "title": "Synthetic.Legacy.Release",
            "links": [["https://source.invalid/container/synthetic", "source"]],
            "password": "synthetic-password",
        }
        protected_db = mock.Mock()
        protected_db.retrieve.return_value = json.dumps(package_data)
        stats = mock.Mock()
        with (
            mock.patch(
                "quasarr.api.sponsors_helper.shared_state.values",
                {"helper_active": True, "helper_last_seen": 0},
            ),
            mock.patch(
                "quasarr.api.sponsors_helper.shared_state.get_db",
                return_value=protected_db,
            ),
            mock.patch(
                "quasarr.api.sponsors_helper.request",
                mock.Mock(
                    json={"package_id": package_id, "reason": "Synthetic failure"}
                ),
            ),
            mock.patch("quasarr.api.sponsors_helper.StatsHelper", return_value=stats),
            mock.patch(
                "quasarr.api.sponsors_helper.fail", return_value={"success": True}
            ) as fail,
            mock.patch(
                "quasarr.api.sponsors_helper.update_release_notification"
            ) as notification,
        ):
            result = route.callback()

        fail.assert_called_once_with(
            package_data["title"], package_id, mock.ANY, reason="Synthetic failure"
        )
        protected_db.delete.assert_called_once_with(package_id)
        notification.assert_called_once()
        self.assertEqual("FAILED", notification.call_args.args[2].name)
        self.assertIn("marked as failed", result)

    def test_to_decrypt_route_accepts_only_post(self):
        app = Bottle()
        setup_sponsors_helper_routes(app)

        methods = {
            route.method
            for route in app.routes
            if route.rule == "/sponsors_helper/api/to_decrypt/"
        }

        self.assertEqual({"POST"}, methods)

    def test_to_decrypt_route_preserves_invalid_payload_status(self):
        app = Bottle()
        setup_sponsors_helper_routes(app)
        route = next(
            route
            for route in app.routes
            if route.rule == "/sponsors_helper/api/to_decrypt/"
        )
        protected_db = mock.Mock()
        protected_db.retrieve_all_titles.return_value = [("pkg-1", "{}")]

        with (
            mock.patch("quasarr.api.sponsors_helper.shared_state.update"),
            mock.patch(
                "quasarr.api.sponsors_helper.shared_state.get_db",
                return_value=protected_db,
            ),
            mock.patch(
                "quasarr.api.sponsors_helper.request",
                mock.Mock(json={}),
            ),
            self.assertRaises(HTTPError) as context,
        ):
            route.callback()

        self.assertEqual(400, context.exception.status_code)

    def test_normalize_helper_supported_urls_deduplicates_and_lowercases(self):
        self.assertEqual(
            ["container.", "alpha.", "beta."],
            normalize_helper_supported_urls(
                [" Container. ", "ALPHA.", "", None, "beta.", "container."]
            ),
        )

    def test_select_helper_package_moves_supported_url_to_front(self):
        protected_packages = [
            (
                "pkg-1",
                json.dumps(
                    {
                        "title": "Example.Release",
                        "links": [
                            ["https://unsupported.invalid/path", "other"],
                            ["https://container.invalid/Container/abc", "container"],
                        ],
                        "password": "",
                    }
                ),
            )
        ]

        package_id, data, prioritized_links = select_helper_package(
            protected_packages,
            ["container."],
        )

        self.assertEqual("pkg-1", package_id)
        self.assertEqual("Example.Release", data["title"])
        self.assertEqual(
            "https://container.invalid/Container/abc",
            prioritized_links[0][0],
        )

    def test_select_helper_package_skips_unsupported_packages_until_match(self):
        protected_packages = [
            (
                "pkg-1",
                json.dumps(
                    {
                        "title": "Unsupported.First",
                        "links": [["https://unknown.invalid/path", "other"]],
                        "password": "",
                    }
                ),
            ),
            (
                "pkg-2",
                json.dumps(
                    {
                        "title": "Supported.Second",
                        "links": [["https://alpha.invalid/f/abc", "alpha"]],
                        "password": "",
                    }
                ),
            ),
        ]

        package_id, data, prioritized_links = select_helper_package(
            protected_packages,
            ["container.", "alpha."],
        )

        self.assertEqual("pkg-2", package_id)
        self.assertEqual("Supported.Second", data["title"])
        self.assertEqual("https://alpha.invalid/f/abc", prioritized_links[0][0])

    def test_select_helper_package_accepts_advertised_mirror(self):
        protected_packages = [
            (
                "pkg-1",
                json.dumps(
                    {
                        "title": "Example.Release",
                        "links": [["https://source.invalid/release", "he"]],
                        "password": "",
                    }
                ),
            )
        ]

        package_id, _, links = select_helper_package(
            protected_packages, ["container."], ["he"]
        )

        self.assertEqual("pkg-1", package_id)
        self.assertEqual("he", links[0][1])

    def test_select_helper_package_returns_none_when_nothing_matches(self):
        protected_packages = [
            (
                "pkg-1",
                json.dumps(
                    {
                        "title": "Unsupported.Only",
                        "links": [["https://unknown.invalid/path", "other"]],
                        "password": "",
                    }
                ),
            )
        ]

        self.assertIsNone(select_helper_package(protected_packages, ["container."]))

    def test_select_helper_package_orders_links_by_mirror_whitelist(self):
        protected_packages = [
            (
                "Quasarr_movies_hash",
                json.dumps(
                    {
                        "title": "Example.Release",
                        "links": [
                            ["https://a.invalid/1", "ddownload"],
                            ["https://b.invalid/2", "rapidgator"],
                            ["https://c.invalid/3", "turbobit"],
                        ],
                        "password": "",
                    }
                ),
            )
        ]

        with (
            mock.patch(
                "quasarr.api.sponsors_helper.get_download_category_from_package_id",
                return_value="movies",
            ),
            mock.patch(
                "quasarr.api.sponsors_helper.get_download_category_mirrors",
                return_value=["turbobit", "rapidgator"],
            ),
        ):
            _, _, prioritized_links = select_helper_package(protected_packages, [])

        # Whitelist order is the ranking; unlisted mirrors keep their order last.
        self.assertEqual(
            ["turbobit", "rapidgator", "ddownload"],
            [link[1] for link in prioritized_links],
        )

    def test_select_helper_package_falls_back_to_rapidgator_first(self):
        protected_packages = [
            (
                "Quasarr_movies_hash",
                json.dumps(
                    {
                        "title": "Example.Release",
                        "links": [
                            ["https://a.invalid/1", "ddownload"],
                            ["https://b.invalid/2", "rapidgator"],
                        ],
                        "password": "",
                    }
                ),
            )
        ]

        with (
            mock.patch(
                "quasarr.api.sponsors_helper.get_download_category_from_package_id",
                return_value="movies",
            ),
            mock.patch(
                "quasarr.api.sponsors_helper.get_download_category_mirrors",
                return_value=[],
            ),
        ):
            _, _, prioritized_links = select_helper_package(protected_packages, [])

        # No whitelist configured: legacy rapidgator-first default is preserved.
        self.assertEqual(
            ["rapidgator", "ddownload"],
            [link[1] for link in prioritized_links],
        )

    def test_download_rejects_missing_or_invalid_protected_row(self):
        app = Bottle()
        setup_sponsors_helper_routes(app)
        route = next(
            route
            for route in app.routes
            if route.rule == "/sponsors_helper/api/download/"
        )
        payload = {
            "name": "Synthetic.Release",
            "package_id": "Quasarr_movies_" + "a" * 32,
            "urls": ["https://hoster.invalid/file/synthetic"],
            "password": "",
            "notification": {"solvers": []},
        }
        invalid_rows = {
            "missing": None,
            "unreadable": mock.Mock(side_effect=ValueError("invalid JSON")),
            "invalid-json": "{",
            "non-dict": json.dumps(["not a package"]),
            "invalid-links": json.dumps({"links": "invalid"}),
            "empty": json.dumps({}),
            "empty-links": json.dumps({"links": []}),
        }

        for case, stored_row in invalid_rows.items():
            with self.subTest(case=case):
                protected_db = mock.Mock()
                if isinstance(stored_row, mock.Mock):
                    protected_db.retrieve = stored_row
                else:
                    protected_db.retrieve.return_value = stored_row
                stats = mock.Mock()
                with (
                    mock.patch(
                        "quasarr.api.sponsors_helper.shared_state.values",
                        {"helper_active": True, "helper_last_seen": 0},
                    ),
                    mock.patch(
                        "quasarr.api.sponsors_helper.shared_state.get_db",
                        return_value=protected_db,
                    ),
                    mock.patch(
                        "quasarr.api.sponsors_helper.request",
                        mock.Mock(json=payload),
                    ),
                    mock.patch(
                        "quasarr.api.sponsors_helper.StatsHelper",
                        return_value=stats,
                    ) as stats_helper,
                    mock.patch("quasarr.api.sponsors_helper.fail") as fail,
                    mock.patch(
                        "quasarr.api.sponsors_helper.update_release_notification"
                    ) as update_notification,
                    mock.patch(
                        "quasarr.api.sponsors_helper.submit_final_download_urls"
                    ) as submit,
                    self.assertRaises(HTTPError) as context,
                ):
                    route.callback()

                self.assertEqual(404, context.exception.status_code)
                stats_helper.assert_not_called()
                fail.assert_not_called()
                update_notification.assert_not_called()
                submit.assert_not_called()
                protected_db.delete.assert_not_called()

    def test_download_accepts_valid_legacy_protected_callback(self):
        app = Bottle()
        setup_sponsors_helper_routes(app)
        route = next(
            route
            for route in app.routes
            if route.rule == "/sponsors_helper/api/download/"
        )
        package_id = "Quasarr_movies_" + "b" * 32
        protected_db = mock.Mock()
        protected_db.retrieve.return_value = json.dumps(
            {
                "title": "Synthetic.Release",
                "links": [["https://source.invalid/container/synthetic", "source"]],
                "password": "",
            }
        )
        payload = {
            "name": "Synthetic.Release",
            "package_id": package_id,
            "urls": ["https://hoster.invalid/file/synthetic"],
            "password": "",
            "notification": {"solvers": []},
        }
        stats = mock.Mock()
        stats_result = {"success": True, "links": payload["urls"]}

        with (
            mock.patch(
                "quasarr.api.sponsors_helper.shared_state.values",
                {"helper_active": True, "helper_last_seen": 0},
            ),
            mock.patch(
                "quasarr.api.sponsors_helper.shared_state.get_db",
                return_value=protected_db,
            ),
            mock.patch("quasarr.api.sponsors_helper.request", mock.Mock(json=payload)),
            mock.patch("quasarr.api.sponsors_helper.StatsHelper", return_value=stats),
            mock.patch(
                "quasarr.api.sponsors_helper.submit_final_download_urls",
                return_value=stats_result,
            ) as submit,
        ):
            result = route.callback()

        self.assertIn("Downloaded 1 download links", result)
        submit.assert_called_once()
        stats.increment_captcha_decryptions_automatic.assert_called_once_with()

    def test_download_rejects_selected_hide_without_episode_confirmation(self):
        app = Bottle()
        setup_sponsors_helper_routes(app)
        route = next(
            route
            for route in app.routes
            if route.rule == "/sponsors_helper/api/download/"
        )
        package_id = "Quasarr_tv_" + "a" * 32
        package_data = {
            "title": "Synthetic.Release",
            "links": [
                [
                    "https://hide.cx/container/synthetic?season=2&episode=7",
                    "hide",
                ]
            ],
            "password": "",
        }
        protected_db = mock.Mock()
        protected_db.retrieve.return_value = json.dumps(package_data)
        payload = {
            "name": "Synthetic.Release",
            "package_id": package_id,
            "urls": ["https://hoster.invalid/file/synthetic"],
            "password": "",
            "notification": {"solvers": []},
        }
        stats = mock.Mock()

        with (
            mock.patch(
                "quasarr.api.sponsors_helper.shared_state.values",
                {"helper_active": True, "helper_last_seen": 0},
            ),
            mock.patch(
                "quasarr.api.sponsors_helper.shared_state.get_db",
                return_value=protected_db,
            ),
            mock.patch("quasarr.api.sponsors_helper.request", mock.Mock(json=payload)),
            mock.patch("quasarr.api.sponsors_helper.fail") as fail,
            mock.patch("quasarr.api.sponsors_helper.update_release_notification"),
            mock.patch("quasarr.api.sponsors_helper.StatsHelper", return_value=stats),
            mock.patch(
                "quasarr.api.sponsors_helper.submit_final_download_urls"
            ) as submit,
        ):
            result = route.callback()

        self.assertEqual(
            {
                "success": False,
                "failed": True,
                "reason": "Hide episode selection was not confirmed",
            },
            result,
        )
        fail.assert_called_once()
        submit.assert_not_called()
        protected_db.delete.assert_called_once_with(package_id)
        stats.increment_failed_decryptions_automatic.assert_called_once_with()

    def test_download_accepts_matching_hide_episode_confirmation(self):
        app = Bottle()
        setup_sponsors_helper_routes(app)
        route = next(
            route
            for route in app.routes
            if route.rule == "/sponsors_helper/api/download/"
        )
        package_id = "Quasarr_tv_" + "b" * 32
        protected_db = mock.Mock()
        protected_db.retrieve.return_value = json.dumps(
            {
                "title": "Synthetic.Release",
                "links": [
                    [
                        "https://hide.cx/container/synthetic?season=2&episode=7",
                        "hide",
                    ]
                ],
                "password": "",
            }
        )
        payload = {
            "name": "Synthetic.Release",
            "package_id": package_id,
            "urls": ["https://hoster.invalid/file/synthetic"],
            "password": "",
            "episode_selection": {"season": 2, "episode": 7},
            "notification": {"solvers": []},
        }
        stats = mock.Mock()
        stats_result = {"success": True, "links": payload["urls"]}

        with (
            mock.patch(
                "quasarr.api.sponsors_helper.shared_state.values",
                {"helper_active": True, "helper_last_seen": 0},
            ),
            mock.patch(
                "quasarr.api.sponsors_helper.shared_state.get_db",
                return_value=protected_db,
            ),
            mock.patch("quasarr.api.sponsors_helper.request", mock.Mock(json=payload)),
            mock.patch("quasarr.api.sponsors_helper.StatsHelper", return_value=stats),
            mock.patch(
                "quasarr.api.sponsors_helper.submit_final_download_urls",
                return_value=stats_result,
            ) as submit,
        ):
            result = route.callback()

        self.assertIn("Downloaded 1 download links", result)
        submit.assert_called_once()
        stats.increment_captcha_decryptions_automatic.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
