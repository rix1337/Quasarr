# -*- coding: utf-8 -*-

import unittest

from quasarr.constants import SEARCH_CAT_SHOWS
from quasarr.providers.utils import is_valid_release, normalize_optional_int


class ReleaseMatchingUtilsTests(unittest.TestCase):
    def test_normalize_optional_int_returns_none_for_empty_string(self):
        self.assertIsNone(normalize_optional_int(""))

    def test_normalize_optional_int_parses_numbers(self):
        self.assertEqual(4, normalize_optional_int("4"))

    def test_date_numbered_tv_release_matches_date_components(self):
        self.assertTrue(
            is_valid_release(
                "Sample.Show.2026.06.19.1080p.WEB.h264-GRP",
                SEARCH_CAT_SHOWS,
                "Sample Show",
                season=2026,
                episode="06/19",
                episode_year=2026,
                episode_month=6,
                episode_day=19,
            )
        )

    def test_date_numbered_tv_release_rejects_wrong_date(self):
        self.assertFalse(
            is_valid_release(
                "Sample.Show.2026.06.18.1080p.WEB.h264-GRP",
                SEARCH_CAT_SHOWS,
                "Sample Show",
                season=2026,
                episode="06/19",
                episode_year=2026,
                episode_month=6,
                episode_day=19,
            )
        )


if __name__ == "__main__":
    unittest.main()
