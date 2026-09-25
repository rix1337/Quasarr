# -*- coding: utf-8 -*-

import unittest
from datetime import date

from quasarr.constants import SEARCH_CAT_SHOWS
from quasarr.providers.utils import (
    canonicalize_date_numbered_title,
    date_numbering_search_strings,
    is_valid_release,
    normalize_optional_int,
    parse_episode_date,
    sanitize_string,
)


class ReleaseMatchingUtilsTests(unittest.TestCase):
    def test_normalize_optional_int_returns_none_for_empty_string(self):
        self.assertIsNone(normalize_optional_int(""))

    def test_normalize_optional_int_parses_numbers(self):
        self.assertEqual(4, normalize_optional_int("4"))

    def test_date_numbered_tv_release_matches_date_components(self):
        episode_date = date(2031, 6, 19)
        self.assertTrue(
            is_valid_release(
                "Sample.Show.2031.06.19.1080p.WEB.h264-GRP",
                SEARCH_CAT_SHOWS,
                "Sample Show",
                season=2031,
                episode="06/19",
                episode_date=episode_date,
            )
        )

    def test_date_numbered_tv_release_rejects_wrong_date(self):
        episode_date = date(2031, 6, 19)
        self.assertFalse(
            is_valid_release(
                "Sample.Show.2031.06.18.1080p.WEB.h264-GRP",
                SEARCH_CAT_SHOWS,
                "Sample Show",
                season=2031,
                episode="06/19",
                episode_date=episode_date,
            )
        )

    def test_date_numbered_tv_release_preserves_numeric_title_tokens(self):
        episode_date = date(2031, 2, 3)
        self.assertTrue(
            is_valid_release(
                "42.42.2031.02.03.1080p.WEB.h264-GRP",
                SEARCH_CAT_SHOWS,
                "42/42",
                episode_date=episode_date,
            )
        )

    def test_date_numbered_tv_release_rejects_wrong_numeric_title(self):
        episode_date = date(2031, 2, 3)
        self.assertFalse(
            is_valid_release(
                "43.43.2031.02.03.1080p.WEB.h264-GRP",
                SEARCH_CAT_SHOWS,
                "42/42",
                episode_date=episode_date,
            )
        )

    def test_date_numbered_tv_release_preserves_repeated_numeric_tokens(self):
        episode_date = date(2031, 2, 3)
        self.assertFalse(
            is_valid_release(
                "42.2031.02.03.1080p.WEB.h264-GRP",
                SEARCH_CAT_SHOWS,
                "42/42",
                episode_date=episode_date,
            )
        )

    def test_date_numbered_tv_release_does_not_use_date_as_numeric_title(self):
        episode_date = date(2031, 2, 3)
        self.assertFalse(
            is_valid_release(
                "Other.Show.2031.02.03.1080p.WEB.h264-GRP",
                SEARCH_CAT_SHOWS,
                "2031",
                episode_date=episode_date,
            )
        )

    def test_date_numbered_tv_release_accepts_title_matching_episode_year(self):
        episode_date = date(2031, 2, 3)
        self.assertTrue(
            is_valid_release(
                "2031.2031.02.03.1080p.WEB.h264-GRP",
                SEARCH_CAT_SHOWS,
                "2031",
                episode_date=episode_date,
            )
        )

    def test_date_numbered_tv_release_matches_all_ignored_word_title(self):
        episode_date = date(2031, 2, 3)
        self.assertTrue(
            is_valid_release(
                "Night.2031.02.03.1080p.WEB.h264-GRP",
                SEARCH_CAT_SHOWS,
                "Night",
                episode_date=episode_date,
            )
        )

    def test_date_numbered_tv_release_accepts_verified_imdb_search(self):
        episode_date = date(2031, 6, 19)
        self.assertTrue(
            is_valid_release(
                "Sample.Show.2031.06.19.1080p.WEB.h264-GRP",
                SEARCH_CAT_SHOWS,
                "tt0000001",
                season=2031,
                episode="06/19",
                episode_date=episode_date,
            )
        )

    def test_parse_episode_date_validates_calendar_date(self):
        self.assertEqual(date(2031, 2, 3), parse_episode_date(2031, "02/03"))
        self.assertIsNone(parse_episode_date(2031, "02/30"))
        self.assertIsNone(parse_episode_date(2031, "2"))
        self.assertIsNone(parse_episode_date(2, "07/08"))

    def test_date_numbering_canonicalizes_generic_scheduled_title(self):
        episode_date = date(2031, 2, 3)
        self.assertEqual(
            "Sample.Monday.Night.Showcase.2031.02.03.1080p-GRP",
            canonicalize_date_numbered_title(
                "Sample.Showcase.2031.02.03.1080p-GRP",
                "Sample Monday Night Showcase",
                episode_date,
            ),
        )

    def test_acronym_title_uses_generic_schedule_alias_and_canonical_title(self):
        episode_date = date(2031, 2, 3)
        search_strings = date_numbering_search_strings(
            "QZX Monday Night AlphaShow", episode_date
        )
        self.assertEqual("QZX", search_strings[0])

        self.assertIn("QZX AlphaShow 2031.02.03", search_strings)
        self.assertEqual(
            "QZX.Monday.Night.AlphaShow.2031.02.03.1080p-GRP",
            canonicalize_date_numbered_title(
                "QZX.AlphaShow.2031.02.03.1080p-GRP",
                "QZX Monday Night AlphaShow",
                episode_date,
            ),
        )

    def test_acronym_title_uses_generic_schedule_and_case_variants(self):
        episode_date = date(2031, 2, 3)
        search_strings = date_numbering_search_strings(
            "QZX Friday Night BetaDown", episode_date
        )

        self.assertIn("QZX BetaDown 2031.02.03", search_strings)
        self.assertIn("QZX Betadown 2031.02.03", search_strings)
        self.assertEqual(
            "QZX.Friday.Night.BetaDown.2031.02.03.1080p-GRP",
            canonicalize_date_numbered_title(
                "QZX.BetaDown.2031.02.03.1080p-GRP",
                "QZX Friday Night BetaDown",
                episode_date,
            ),
        )

    def test_sanitize_string_maps_multiplication_sign_to_x(self):
        # Sources style titles as "Foo × Bar" while Arr/IMDb titles use a plain
        # "x"; stripping the sign would drop the token and break matching.
        self.assertEqual(sanitize_string("Foo \u00d7 Bar"), "foo x bar")
        self.assertIn(
            sanitize_string("Foo x Bar"), sanitize_string("Foo \u00d7 Bar: S3")
        )

    def test_sanitize_string_keeps_plain_x_and_strips_other_symbols(self):
        # Legacy path: a plain "x" is untouched and other symbols are still removed.
        self.assertEqual(sanitize_string("Foo x Bar"), "foo x bar")
        self.assertEqual(sanitize_string("Foo * Bar!"), "foo bar")


if __name__ == "__main__":
    unittest.main()
