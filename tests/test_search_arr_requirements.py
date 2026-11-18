import unittest
from types import SimpleNamespace
from unittest.mock import patch

from quasarr.constants import SEARCH_CAT_BOOKS, SEARCH_CAT_MOVIES, SEARCH_CAT_SHOWS
from quasarr.providers.utils import is_site_usable
from quasarr.search import get_search_results
from quasarr.storage.setup.arr import (
    _arr_client_selection_form_html,
    missing_arr_client_requirement,
    split_arr_required_sites,
)
from quasarr.storage.setup.radarr import (
    _configured_required_sites as radarr_required_sites,
)
from quasarr.storage.setup.radarr import _radarr_setup_form_html, is_radarr_skipped
from quasarr.storage.setup.sonarr import (
    _configured_required_sites as sonarr_required_sites,
)
from quasarr.storage.setup.sonarr import _sonarr_setup_form_html, is_sonarr_skipped


class SearchArrRequirementTests(unittest.TestCase):
    @staticmethod
    def _state(**clients):
        return SimpleNamespace(
            values={
                "config": lambda _section: {},
                **clients,
            }
        )

    def test_movie_search_stops_without_radarr(self):
        with patch("quasarr.search.warn") as log_warn:
            results = get_search_results(
                self._state(),
                "radarr",
                SEARCH_CAT_MOVIES,
                imdb_id="tt0000010",
            )

        self.assertEqual([], results)
        log_warn.assert_called_once_with(
            "Movie search unavailable: Radarr is not configured"
        )

    def test_tv_feed_stops_without_sonarr(self):
        with patch("quasarr.search.warn") as log_warn:
            results = get_search_results(self._state(), "sonarr", SEARCH_CAT_SHOWS)

        self.assertEqual([], results)
        log_warn.assert_called_once_with(
            "TV search unavailable: Sonarr is not configured"
        )

    def test_book_phrase_search_does_not_require_arr_client(self):
        with (
            patch("quasarr.search.get_sources", return_value={}),
            patch("quasarr.search.get_search_category_sources", return_value=[]),
            patch("quasarr.search.warn") as log_warn,
        ):
            results = get_search_results(
                self._state(),
                "magazarr",
                SEARCH_CAT_BOOKS,
                search_phrase="Synthetic Author",
            )

        self.assertEqual([], results)
        log_warn.assert_not_called()

    def test_movie_search_warms_metadata_from_radarr(self):
        state = self._state(radarr_client=object())
        with (
            patch("quasarr.search.get_sources", return_value={}),
            patch("quasarr.search.get_search_category_sources", return_value=[]),
            patch("quasarr.search.get_imdb_metadata") as metadata_lookup,
        ):
            get_search_results(
                state,
                "radarr",
                SEARCH_CAT_MOVIES,
                imdb_id="tt0000011",
            )

        metadata_lookup.assert_called_once_with(state, "tt0000011", SEARCH_CAT_MOVIES)

    def test_setup_forms_do_not_offer_arr_skip_loopholes(self):
        with (
            patch("quasarr.storage.setup.radarr.Config", return_value={}),
            patch("quasarr.storage.setup.sonarr.Config", return_value={}),
            patch("quasarr.storage.setup.radarr.DataBase") as radarr_database,
            patch("quasarr.storage.setup.sonarr.DataBase") as sonarr_database,
        ):
            radarr_html = _radarr_setup_form_html(["aa"])
            sonarr_html = _sonarr_setup_form_html(["bb"])
            radarr_database.return_value.retrieve.return_value = None
            sonarr_database.return_value.retrieve.return_value = None

            self.assertNotIn("skip", radarr_html.lower())
            self.assertNotIn("skip", sonarr_html.lower())
            self.assertEqual(2, radarr_html.count(" required"))
            self.assertEqual(2, sonarr_html.count(" required"))
            self.assertFalse(is_radarr_skipped())
            self.assertFalse(is_sonarr_skipped())

    def test_arr_skip_preferences_are_preserved(self):
        with (
            patch("quasarr.storage.setup.radarr.DataBase") as radarr_database,
            patch("quasarr.storage.setup.sonarr.DataBase") as sonarr_database,
        ):
            radarr_database.return_value.retrieve.return_value = "true"
            sonarr_database.return_value.retrieve.return_value = "true"

            self.assertTrue(is_radarr_skipped())
            self.assertTrue(is_sonarr_skipped())

    def test_dual_category_setup_lets_user_choose_one_arr_client(self):
        html = _arr_client_selection_form_html(["aa"], ["bb"])

        self.assertIn('value="radarr"', html)
        self.assertIn('value="sonarr"', html)
        self.assertIn("does not require both", html)

    def test_arr_setup_keeps_exclusive_and_dual_source_requirements_separate(self):
        radarr_only, sonarr_only, dual_category = split_arr_required_sites(
            ["movie", "both"], ["tv", "both"]
        )

        self.assertEqual({"movie"}, radarr_only)
        self.assertEqual({"tv"}, sonarr_only)
        self.assertEqual({"both"}, dual_category)

    def test_dual_category_source_accepts_either_arr_client(self):
        radarr_required = {"movie", "both"}
        sonarr_required = {"tv", "both"}

        self.assertIsNone(
            missing_arr_client_requirement(
                "both", radarr_required, sonarr_required, True, False
            )
        )
        self.assertIsNone(
            missing_arr_client_requirement(
                "both", radarr_required, sonarr_required, False, True
            )
        )
        self.assertEqual(
            "Sonarr",
            missing_arr_client_requirement(
                "tv", radarr_required, sonarr_required, True, False
            ),
        )

    def test_dual_category_source_is_usable_with_either_arr_client(self):
        state = SimpleNamespace(
            values={
                "config": lambda section: (
                    {"both": "both.invalid"} if section == "Hostnames" else {}
                ),
            }
        )
        with (
            patch(
                "quasarr.providers.utils.get_radarr_required_hostnames",
                return_value=["both"],
            ),
            patch(
                "quasarr.providers.utils.get_sonarr_required_hostnames",
                return_value=["both"],
            ),
            patch(
                "quasarr.providers.utils.get_login_required_hostnames",
                return_value=[],
            ),
        ):
            state.values["radarr_client"] = object()
            self.assertTrue(is_site_usable(state, "both"))

            state.values.pop("radarr_client")
            state.values["sonarr_client"] = object()
            self.assertTrue(is_site_usable(state, "both"))

            state.values.pop("sonarr_client")
            self.assertFalse(is_site_usable(state, "both"))

    def test_dual_category_source_does_not_block_clearing_other_arr_client(self):
        state = self._state(radarr_client=object(), sonarr_client=object())
        with (
            patch(
                "quasarr.storage.setup.radarr.Config",
                return_value={"both": "both.invalid"},
            ),
            patch(
                "quasarr.storage.setup.sonarr.Config",
                return_value={"both": "both.invalid"},
            ),
            patch(
                "quasarr.search.sources.helpers.get_radarr_required_hostnames",
                return_value=["both"],
            ),
            patch(
                "quasarr.search.sources.helpers.get_sonarr_required_hostnames",
                return_value=["both"],
            ),
        ):
            self.assertEqual(set(), radarr_required_sites(state))
            self.assertEqual(set(), sonarr_required_sites(state))


if __name__ == "__main__":
    unittest.main()
