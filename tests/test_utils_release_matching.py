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

    def test_wwe_raw_uses_generic_schedule_alias_and_canonical_title(self):
        episode_date = date(2031, 2, 3)
        search_strings = date_numbering_search_strings(
            "WWE Monday Night RAW", episode_date
        )

        self.assertIn("WWE RAW 2031.02.03", search_strings)
        self.assertEqual(
            "WWE.Monday.Night.RAW.2031.02.03.1080p-GRP",
            canonicalize_date_numbered_title(
                "WWE.RAW.2031.02.03.1080p-GRP",
                "WWE Monday Night RAW",
                episode_date,
            ),
        )

    def test_wwe_smackdown_uses_generic_schedule_and_case_variants(self):
        episode_date = date(2031, 2, 3)
        search_strings = date_numbering_search_strings(
            "WWE Friday Night SmackDown", episode_date
        )

        self.assertIn("WWE SmackDown 2031.02.03", search_strings)
        self.assertIn("WWE Smackdown 2031.02.03", search_strings)
        self.assertEqual(
            "WWE.Friday.Night.SmackDown.2031.02.03.1080p-GRP",
            canonicalize_date_numbered_title(
                "WWE.SmackDown.2031.02.03.1080p-GRP",
                "WWE Friday Night SmackDown",
                episode_date,
            ),
        )


if __name__ == "__main__":
    unittest.main()
