# -*- coding: utf-8 -*-

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from quasarr.downloads.linkcrypters import hide

CONTAINER_URL = "https://hide.cx/container/synthetic"
EPISODE_URL = CONTAINER_URL + "?season=2&episode=7"
SYNTHETIC_LINKS = [
    "https://hoster.invalid/file/random-a",
    "https://hoster.invalid/file/random-b",
]


class Response:
    def __init__(self, url, payload=None, execute_js_result=None):
        self.url = url
        self._payload = payload or {}
        self.execute_js_result = execute_js_result

    def json(self):
        return self._payload


class HideEpisodeSelectionTests(unittest.TestCase):
    def test_native_selection_returns_exact_ids_from_native_json_and_destroys_session(
        self,
    ):
        response = Response(
            CONTAINER_URL,
            execute_js_result=json.dumps(
                {"selected": "S02E07", "ids": ["random-id-b", "random-id-a"]}
            ),
        )
        shared_state = SimpleNamespace()

        with (
            patch.object(hide, "is_flaresolverr_available", return_value=True),
            patch.object(hide, "flaresolverr_create_session", return_value="session"),
            patch.object(hide, "flaresolverr_get", return_value=response) as get,
            patch.object(hide, "flaresolverr_destroy_session") as destroy,
        ):
            result = hide._native_episode_link_ids(shared_state, "synthetic", (2, 7))

        self.assertEqual(["random-id-b", "random-id-a"], result)
        request_url = get.call_args.args[1]
        self.assertIn("season=2", request_url)
        self.assertIn("episode=7", request_url)
        self.assertIn("selectedEpisode", get.call_args.kwargs["execute_js"])
        destroy.assert_called_once_with(shared_state, "session")

    def test_native_missing_episode_is_terminal_and_destroys_session(self):
        response = Response(
            CONTAINER_URL,
            execute_js_result=json.dumps(
                {"error": "Episode not present in link container"}
            ),
        )

        with (
            patch.object(hide, "is_flaresolverr_available", return_value=True),
            patch.object(hide, "flaresolverr_create_session", return_value="session"),
            patch.object(hide, "flaresolverr_get", return_value=response),
            patch.object(hide, "flaresolverr_destroy_session") as destroy,
        ):
            with self.assertRaisesRegex(
                hide.HideEpisodeError, "Episode not present in link container"
            ):
                hide._native_episode_link_ids(SimpleNamespace(), "synthetic", (2, 7))

        destroy.assert_called_once()

    def test_native_empty_ids_report_episode_missing(self):
        response = Response(
            CONTAINER_URL,
            execute_js_result=json.dumps({"selected": "S02E07", "ids": []}),
        )

        with (
            patch.object(hide, "is_flaresolverr_available", return_value=True),
            patch.object(hide, "flaresolverr_create_session", return_value="session"),
            patch.object(hide, "flaresolverr_get", return_value=response),
            patch.object(hide, "flaresolverr_destroy_session"),
        ):
            with self.assertRaisesRegex(
                hide.HideEpisodeError, "Episode not present in link container"
            ):
                hide._native_episode_link_ids(SimpleNamespace(), "synthetic", (2, 7))

    def test_native_response_error_still_destroys_session(self):
        with (
            patch.object(hide, "is_flaresolverr_available", return_value=True),
            patch.object(hide, "flaresolverr_create_session", return_value="session"),
            patch.object(
                hide, "flaresolverr_get", side_effect=RuntimeError("synthetic")
            ),
            patch.object(hide, "flaresolverr_destroy_session") as destroy,
        ):
            with self.assertRaisesRegex(hide.HideEpisodeError, "synthetic"):
                hide._native_episode_link_ids(SimpleNamespace(), "synthetic", (2, 7))

        destroy.assert_called_once_with(unittest.mock.ANY, "session")

    def test_redirect_without_query_retains_episode_selection(self):
        session = Mock()
        session.head.return_value = Response(CONTAINER_URL)
        selected_url = {}

        def decrypt(_shared_state, url, _session):
            selected_url["value"] = url
            return SYNTHETIC_LINKS

        with (
            patch.object(hide.requests, "Session", return_value=session),
            patch.object(hide, "unhide_links", side_effect=decrypt),
        ):
            result = hide.decrypt_links_if_hide(
                SimpleNamespace(), [[EPISODE_URL, "hide"]]
            )

        self.assertEqual({"status": "success", "results": SYNTHETIC_LINKS}, result)
        self.assertIn("season=2", selected_url["value"])
        self.assertIn("episode=7", selected_url["value"])

    def test_unhide_uses_exact_native_ids(self):
        session = Mock()
        session.get.side_effect = lambda url, **_: (
            Response(
                url,
                payload={
                    "links": [
                        {"id": "random-id-a"},
                        {"id": "random-id-b"},
                        {"id": "unused-id"},
                    ]
                },
            )
            if "/links/" not in url
            else Response(
                url,
                payload={
                    "url": SYNTHETIC_LINKS[0]
                    if url.endswith("random-id-b")
                    else SYNTHETIC_LINKS[1]
                },
            )
        )

        with (
            patch.object(
                hide,
                "_native_episode_link_ids",
                return_value=["random-id-b", "random-id-a"],
            ),
            patch.object(hide, "StatsHelper"),
        ):
            result = hide.unhide_links(
                SimpleNamespace(values={"user_agent": "synthetic"}),
                EPISODE_URL,
                session,
            )

        self.assertCountEqual(SYNTHETIC_LINKS, result)
        requested_ids = {
            call.args[0].rsplit("/", 1)[-1]
            for call in session.get.call_args_list
            if "/links/" in call.args[0]
        }
        self.assertEqual({"random-id-a", "random-id-b"}, requested_ids)

    def test_partial_episode_resolution_is_terminal(self):
        session = Mock()
        session.head.return_value = Response(EPISODE_URL)
        stats = Mock()

        with (
            patch.object(hide.requests, "Session", return_value=session),
            patch.object(
                hide,
                "unhide_links",
                side_effect=hide.HideEpisodeError(
                    "Could not resolve all links for requested episode"
                ),
            ),
            patch.object(hide, "StatsHelper", return_value=stats),
        ):
            result = hide.decrypt_links_if_hide(
                SimpleNamespace(), [[EPISODE_URL, "hide"]]
            )

        self.assertEqual(
            {
                "status": "error",
                "results": [],
                "reason": "Could not resolve all links for requested episode",
                "terminal": True,
            },
            result,
        )
        stats.increment_failed_decryptions_automatic.assert_called_once_with()

    def test_native_unhide_episode_error_is_counted_by_outer_operation(self):
        session = Mock()
        session.head.return_value = Response(EPISODE_URL)
        session.get.return_value = Response(
            CONTAINER_URL, payload={"links": [{"id": "synthetic-link"}]}
        )
        stats = Mock()

        with (
            patch.object(hide.requests, "Session", return_value=session),
            patch.object(
                hide,
                "_native_episode_link_ids",
                side_effect=hide.HideEpisodeError(
                    "Episode not present in link container"
                ),
            ),
            patch.object(hide, "StatsHelper", return_value=stats),
        ):
            result = hide.decrypt_links_if_hide(
                SimpleNamespace(values={"user_agent": "synthetic"}),
                [[EPISODE_URL, "hide"]],
            )

        self.assertEqual("Episode not present in link container", result["reason"])
        self.assertTrue(result["terminal"])
        stats.increment_failed_decryptions_automatic.assert_called_once_with()

    def test_multiple_terminal_episode_failures_count_once(self):
        session = Mock()
        session.head.side_effect = [Response(EPISODE_URL), Response(EPISODE_URL)]
        stats = Mock()
        error = hide.HideEpisodeError(
            "Could not resolve all links for requested episode"
        )

        with (
            patch.object(hide.requests, "Session", return_value=session),
            patch.object(hide, "unhide_links", side_effect=[error, error]),
            patch.object(hide, "StatsHelper", return_value=stats),
        ):
            result = hide.decrypt_links_if_hide(
                SimpleNamespace(), [[EPISODE_URL, "hide"], [EPISODE_URL, "hide"]]
            )

        self.assertEqual("error", result["status"])
        self.assertTrue(result["terminal"])
        stats.increment_failed_decryptions_automatic.assert_called_once_with()

    def test_terminal_episode_failure_followed_by_success_is_not_counted(self):
        session = Mock()
        session.head.side_effect = [Response(EPISODE_URL), Response(EPISODE_URL)]
        stats = Mock()

        with (
            patch.object(hide.requests, "Session", return_value=session),
            patch.object(
                hide,
                "unhide_links",
                side_effect=[
                    hide.HideEpisodeError(
                        "Could not resolve all links for requested episode"
                    ),
                    SYNTHETIC_LINKS,
                ],
            ),
            patch.object(hide, "StatsHelper", return_value=stats),
        ):
            result = hide.decrypt_links_if_hide(
                SimpleNamespace(), [[EPISODE_URL, "hide"], [EPISODE_URL, "hide"]]
            )

        self.assertEqual({"status": "success", "results": SYNTHETIC_LINKS}, result)
        stats.increment_failed_decryptions_automatic.assert_not_called()

    def test_missing_flaresolverr_keeps_episode_failure_nonterminal(self):
        session = Mock()
        session.head.return_value = Response(EPISODE_URL)
        stats = Mock()

        with (
            patch.object(hide.requests, "Session", return_value=session),
            patch.object(
                hide,
                "unhide_links",
                side_effect=hide.HideEpisodeBrowserUnavailable(
                    "Hide episode selection requires FlareSolverr"
                ),
            ),
            patch.object(hide, "StatsHelper", return_value=stats),
        ):
            result = hide.decrypt_links_if_hide(
                SimpleNamespace(), [[EPISODE_URL, "hide"]]
            )

        self.assertEqual(
            {
                "status": "error",
                "results": [],
                "reason": "Hide episode selection requires FlareSolverr",
                "terminal": False,
            },
            result,
        )
        stats.increment_failed_decryptions_automatic.assert_not_called()

    def test_legacy_container_without_episode_selection_keeps_all_links(self):
        session = Mock()
        session.head.return_value = Response(CONTAINER_URL)
        stats = Mock()

        with (
            patch.object(hide.requests, "Session", return_value=session),
            patch.object(hide, "unhide_links", return_value=SYNTHETIC_LINKS),
            patch.object(hide, "StatsHelper", return_value=stats),
        ):
            result = hide.decrypt_links_if_hide(
                SimpleNamespace(), [[CONTAINER_URL, "hide"]]
            )

        self.assertEqual({"status": "success", "results": SYNTHETIC_LINKS}, result)
        stats.increment_failed_decryptions_automatic.assert_not_called()

    def test_mixed_selected_and_unfiltered_urls_fail_closed_before_requests(self):
        session = Mock()
        stats = Mock()
        selected_url = EPISODE_URL
        unfiltered_url = CONTAINER_URL + "?mirror=preferred"

        with (
            patch.object(hide.requests, "Session", return_value=session),
            patch.object(hide, "unhide_links") as unhide,
            patch.object(hide, "StatsHelper", return_value=stats),
        ):
            result = hide.decrypt_links_if_hide(
                SimpleNamespace(),
                [[selected_url, "hide"], [unfiltered_url, "hide"]],
            )

        self.assertEqual(
            {
                "status": "error",
                "results": [],
                "reason": "Inconsistent Hide episode selection",
                "terminal": True,
            },
            result,
        )
        session.head.assert_not_called()
        session.get.assert_not_called()
        unhide.assert_not_called()

    def test_malformed_or_duplicate_episode_query_is_terminal(self):
        for query in ("season=2&episode=0", "season=2&season=3&episode=7"):
            with self.subTest(query=query):
                with (
                    patch.object(hide.requests, "Session"),
                    patch.object(hide, "StatsHelper") as stats_helper,
                ):
                    result = hide.decrypt_links_if_hide(
                        SimpleNamespace(), [[CONTAINER_URL + "?" + query, "hide"]]
                    )

                self.assertEqual("error", result["status"])
                self.assertTrue(result["terminal"])
                self.assertEqual("Invalid Hide episode selection", result["reason"])
                stats_helper.return_value.increment_failed_decryptions_automatic.assert_called_once_with()

    def test_unconfirmed_native_response_is_terminal(self):
        session = Mock()
        session.head.return_value = Response(EPISODE_URL)
        stats = Mock()

        with (
            patch.object(hide.requests, "Session", return_value=session),
            patch.object(
                hide,
                "unhide_links",
                side_effect=hide.HideEpisodeError(
                    "Hide episode selection was not confirmed"
                ),
            ),
            patch.object(hide, "StatsHelper", return_value=stats),
        ):
            result = hide.decrypt_links_if_hide(
                SimpleNamespace(), [[EPISODE_URL, "hide"]]
            )

        self.assertEqual("error", result["status"])
        self.assertTrue(result["terminal"])
        self.assertEqual("Hide episode selection was not confirmed", result["reason"])
        stats.increment_failed_decryptions_automatic.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
