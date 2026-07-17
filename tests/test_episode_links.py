import unittest
from unittest.mock import MagicMock

from quasarr.downloads import episode_links


def link(uuid, name):
    return {"uuid": uuid, "name": name, "packageUUID": 1000}


# A single-episode grab that carried the whole season: the package is named
# after episode 2, but the links cover episodes 1 to 3. Multipart archives per
# episode are the shape this exists for. Synthetic titles only.
SEASON_LINKS = [
    link(1, "synthetic.show.s01e01.german.web-grp.part01.rar"),
    link(2, "synthetic.show.s01e01.german.web-grp.part02.rar"),
    link(3, "synthetic.show.s01e02.german.web-grp.part01.rar"),
    link(4, "synthetic.show.s01e02.german.web-grp.part02.rar"),
    link(5, "synthetic.show.s01e03.german.web-grp.part01.rar"),
]

EPISODE_PACKAGE = "Synthetic.Show.S01E02.German.DL.1080p.WEB.h264-GRP"
SEASON_PACKAGE = "Synthetic.Show.S01.German.DL.1080p.WEB.h264-GRP"


class ParseSeasonEpisodesTests(unittest.TestCase):
    def test_parses_titles_and_filenames(self):
        cases = [
            # Season pack: season token, no episode component.
            ("Synthetic.Show.S01.German.1080p.WEB-GRP", (1, set())),
            # Single episode, as release title and as archive file name.
            ("Synthetic.Show.S01E05.German.1080p.WEB-GRP", (1, {5})),
            ("synthetic.show.s01e05.german.web-grp.part03.rar", (1, {5})),
            # Repack markers after the token do not disturb parsing.
            ("synthetic.show.s01e06.german.web.repack-grp.part01.rar", (1, {6})),
            # Ranges expand to every contained episode.
            ("Synthetic.Show.S01E01-E03.German.1080p.WEB-GRP", (1, {1, 2, 3})),
            ("Synthetic.Show.S01E01-03.German.1080p.WEB-GRP", (1, {1, 2, 3})),
            # Multi-episode files without a range dash keep both numbers.
            ("Synthetic.Show.S01E01E02.German.1080p.WEB-GRP", (1, {1, 2})),
            # No season token at all (a movie).
            ("Synthetic.Movie.2024.German.1080p.BluRay-GRP", None),
            # "part11" must not be mistaken for an episode marker.
            ("synthetic.show.s02.german.web-grp.part11.rar", (2, set())),
        ]
        for name, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(episode_links.parse_season_episodes(name), expected)


class PlanLinkRemovalsTests(unittest.TestCase):
    def test_keeps_only_the_requested_episode(self):
        plan = episode_links.plan_link_removals(EPISODE_PACKAGE, SEASON_LINKS)

        self.assertEqual(plan, ([3, 4], [1, 2, 5]))

    def test_season_pack_is_left_untouched(self):
        # Every episode belongs to a season-pack grab; nothing to trim.
        self.assertIsNone(
            episode_links.plan_link_removals(SEASON_PACKAGE, SEASON_LINKS)
        )

    def test_already_matching_package_is_left_untouched(self):
        # All links are the requested episode -> nothing to remove.
        matching = [link_ for link_ in SEASON_LINKS if "s01e02" in link_["name"]]

        self.assertIsNone(episode_links.plan_link_removals(EPISODE_PACKAGE, matching))

    def test_unparseable_link_keeps_the_package(self):
        # A single unmappable link poisons the mapping: keep everything rather
        # than risk removing a file that belongs to the wanted episode.
        links = SEASON_LINKS + [link(6, "synthetic.show.sample.mkv")]

        self.assertIsNone(episode_links.plan_link_removals(EPISODE_PACKAGE, links))

    def test_season_mismatch_keeps_the_package(self):
        links = SEASON_LINKS + [link(6, "synthetic.show.s02e02.german.web-grp.rar")]

        self.assertIsNone(episode_links.plan_link_removals(EPISODE_PACKAGE, links))

    def test_link_without_uuid_keeps_the_package(self):
        links = [dict(SEASON_LINKS[0]), dict(SEASON_LINKS[2])]
        links[0].pop("uuid")

        self.assertIsNone(episode_links.plan_link_removals(EPISODE_PACKAGE, links))

    def test_nothing_of_the_requested_episode_present_keeps_the_package(self):
        # Requested episode is absent -> keeping nothing would empty the
        # package, so leave it alone and let the normal flow deal with it.
        self.assertIsNone(
            episode_links.plan_link_removals(
                "Synthetic.Show.S01E09.German.DL.1080p.WEB.h264-GRP", SEASON_LINKS
            )
        )

    def test_episode_range_package_keeps_every_contained_episode(self):
        plan = episode_links.plan_link_removals(
            "Synthetic.Show.S01E01-E02.German.DL.1080p.WEB.h264-GRP", SEASON_LINKS
        )

        self.assertEqual(plan, ([1, 2, 3, 4], [5]))


def shared_state_with(device):
    return MagicMock(get_device=MagicMock(return_value=device))


class TrimToRequestedEpisodesTests(unittest.TestCase):
    def test_removes_other_episodes_and_reports_removal(self):
        device = MagicMock()

        removed = episode_links.trim_to_requested_episodes(
            shared_state_with(device), EPISODE_PACKAGE, SEASON_LINKS
        )

        self.assertTrue(removed)
        # package_ids must stay empty; passing the package id would remove the
        # whole package instead of only the filtered links.
        device.linkgrabber.remove_links.assert_called_once_with([1, 2, 5], [])

    def test_season_pack_is_a_noop(self):
        device = MagicMock()

        removed = episode_links.trim_to_requested_episodes(
            shared_state_with(device), SEASON_PACKAGE, SEASON_LINKS
        )

        self.assertFalse(removed)
        device.linkgrabber.remove_links.assert_not_called()

    def test_device_error_keeps_the_package(self):
        device = MagicMock()
        device.linkgrabber.remove_links.side_effect = RuntimeError("jd gone")

        removed = episode_links.trim_to_requested_episodes(
            shared_state_with(device), EPISODE_PACKAGE, SEASON_LINKS
        )

        # Reported as "not removed" so the caller starts the package as before.
        self.assertFalse(removed)


if __name__ == "__main__":
    unittest.main()
