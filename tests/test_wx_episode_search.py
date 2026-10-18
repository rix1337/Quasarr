import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from quasarr.constants import SEARCH_CAT_SHOWS
from quasarr.downloads.sources import wx as download_wx
from quasarr.search.sources import wx as search_wx

PACK_TITLE = "Synthetic.Show.S02.German.DL.1080p.WEB.H264-GRP"
EPISODE_TITLE = "Synthetic.Show.S02E03.German.DL.1080p.WEB.H264-GRP"


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def shared_state():
    return SimpleNamespace(
        values={
            "user_agent": "UA",
            "config": lambda section: {"wx": "wx.invalid"},
        }
    )


def release(**overrides):
    value = {
        "uid": "PACK-A",
        "fulltitle": PACK_TITLE,
        "size": 4550002042,
        "user_id": 4,
        "options": {"episode_count_in_season": 5},
        "crypted_links": {"hoster": "https://filecrypt.cc/Container/PACK.html"},
        "links": {"hoster": ["https://hoster.invalid/all-episodes"]},
    }
    value.update(overrides)
    return value


class WxEpisodeSearchTests(unittest.TestCase):
    def search(self, releases, season=2, episode=3):
        responses = [
            FakeResponse({"items": {"data": [{"uid": "SHOW"}]}}),
            FakeResponse({"item": {"releases": releases}}),
        ]
        with (
            patch("quasarr.search.sources.wx.requests.get", side_effect=responses),
            patch(
                "quasarr.search.sources.wx.generate_download_link",
                return_value="download",
            ) as generate_download_link,
            patch("quasarr.search.sources.wx.clear_hostname_issue"),
            patch("quasarr.search.sources.wx.get_year", return_value=None),
        ):
            results = search_wx.Source().search(
                shared_state(),
                time.time(),
                SEARCH_CAT_SHOWS,
                "Synthetic Show",
                season,
                episode,
            )
            self.generate_download_link_mock = generate_download_link
            return results

    def test_episode_candidate_keeps_uid_and_explicit_selection(self):
        results = self.search([release()])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["details"]["title"], EPISODE_TITLE)
        self.assertEqual(results[0]["details"]["size"], 910000408)
        self.assertEqual(self.generate_download_link_mock.call_args.args[3], 867)
        self.assertEqual(
            parse_qs(urlsplit(results[0]["details"]["source"]).query),
            {"release": ["PACK-A"], "season": ["2"], "episode": ["3"]},
        )

    def test_only_counted_matching_season_hide_packs_offer_episodes(self):
        cases = [
            release(options={}),
            release(options={"episode_count_in_season": 2}),
            release(options={"episode_count_in_season": "invalid"}),
            release(fulltitle=PACK_TITLE.replace("S02", "S01")),
            release(user_id=8),
            release(uid=None),
            release(crypted_links={}),
        ]
        for candidate in cases:
            with self.subTest(candidate=candidate):
                self.assertEqual(self.search([candidate]), [])

    def test_native_hide_candidate_does_not_require_twin_uploader(self):
        results = self.search(
            [
                release(
                    user_id=8,
                    crypted_links={"hoster": "https://hide.cx/container/PACK"},
                )
            ]
        )
        self.assertEqual(results[0]["details"]["title"], EPISODE_TITLE)

    def test_legacy_season_search_retains_pack_title_and_url(self):
        results = self.search([release()], episode=None)
        self.assertEqual(results[0]["details"]["title"], PACK_TITLE)
        self.assertEqual(results[0]["details"]["size"], 4550002042)
        self.assertEqual(self.generate_download_link_mock.call_args.args[3], 4339)
        self.assertEqual(
            results[0]["details"]["source"],
            "https://wx.invalid/detail/SHOW?release=PACK-A",
        )

    def test_explicit_episode_release_keeps_legacy_path(self):
        results = self.search([release(fulltitle=EPISODE_TITLE, user_id=8)])
        self.assertEqual(results[0]["details"]["title"], EPISODE_TITLE)
        self.assertEqual(results[0]["details"]["size"], 4550002042)
        self.assertEqual(self.generate_download_link_mock.call_args.args[3], 4339)
        self.assertEqual(
            parse_qs(urlsplit(results[0]["details"]["source"]).query),
            {"release": ["PACK-A"]},
        )

    def test_missing_size_keeps_zero_fallback(self):
        candidate = release()
        del candidate["size"]
        results = self.search([candidate])

        self.assertEqual(results[0]["details"]["size"], 0)
        self.assertEqual(self.generate_download_link_mock.call_args.args[3], 0)

    def test_exact_episode_beats_pack_when_pack_was_returned_first(self):
        results = self.search(
            [
                release(),
                release(uid="EPISODE-B", fulltitle=EPISODE_TITLE, user_id=8),
            ]
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["details"]["title"], EPISODE_TITLE)
        self.assertEqual(
            parse_qs(urlsplit(results[0]["details"]["source"]).query),
            {"release": ["EPISODE-B"]},
        )

    def test_duplicate_exact_episode_releases_still_deduplicate(self):
        results = self.search(
            [
                release(uid="EPISODE-A", fulltitle=EPISODE_TITLE, user_id=8),
                release(uid="EPISODE-B", fulltitle=EPISODE_TITLE, user_id=8),
            ]
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(
            parse_qs(urlsplit(results[0]["details"]["source"]).query),
            {"release": ["EPISODE-A"]},
        )

    def test_same_title_synthesized_packs_keep_distinct_uids(self):
        results = self.search([release(uid="PACK-A"), release(uid="PACK-B")])

        self.assertEqual(len(results), 2)
        self.assertEqual(
            [
                parse_qs(urlsplit(result["details"]["source"]).query)
                for result in results
            ],
            [
                {"release": ["PACK-A"], "season": ["2"], "episode": ["3"]},
                {"release": ["PACK-B"], "season": ["2"], "episode": ["3"]},
            ],
        )
        self.assertEqual(
            [call.args[2] for call in self.generate_download_link_mock.call_args_list],
            [result["details"]["source"] for result in results],
        )

    def test_same_uid_synthesized_pack_still_deduplicates(self):
        results = self.search([release(uid="PACK-A"), release(uid="PACK-A")])

        self.assertEqual(len(results), 1)
        self.assertEqual(
            parse_qs(urlsplit(results[0]["details"]["source"]).query),
            {"release": ["PACK-A"], "season": ["2"], "episode": ["3"]},
        )

    def test_malformed_candidate_does_not_abort_later_exact_episode(self):
        results = self.search(
            [
                None,
                release(uid="EPISODE-B", fulltitle=EPISODE_TITLE, user_id=8),
            ]
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(
            parse_qs(urlsplit(results[0]["details"]["source"]).query),
            {"release": ["EPISODE-B"]},
        )


class WxEpisodeDownloadTests(unittest.TestCase):
    def download(
        self, releases, selection="release=PACK-A&season=2&episode=3", mirrors=None
    ):
        with (
            patch("quasarr.downloads.sources.wx.requests.Session") as session,
            patch(
                "quasarr.downloads.sources.wx.check_links_online_status",
                side_effect=lambda links, state: [
                    [url, hoster] for url, hoster, status in links
                ],
            ),
        ):
            session.return_value.get.side_effect = [
                FakeResponse({}),
                FakeResponse({"item": {"releases": releases}}),
            ]
            result = download_wx.Source().get_download_links(
                shared_state(),
                f"https://wx.invalid/detail/SHOW?{selection}",
                mirrors or [],
                EPISODE_TITLE,
                "",
            )
            for call in session.return_value.get.call_args_list:
                params = parse_qs(urlsplit(call.args[0]).query)
                self.assertNotIn("season", params)
                self.assertNotIn("episode", params)
            return result

    def test_twin_url_carries_native_selection_and_preserves_existing_query(self):
        result = self.download(
            [
                release(
                    crypted_links={
                        "hoster": "https://filecrypt.cc/Container/PACK.html?mirror=1",
                    }
                )
            ]
        )
        self.assertEqual(
            result,
            {
                "links": [
                    [
                        "https://hide.cx/fc/Container/PACK.html?mirror=1&season=2&episode=3",
                        "hoster",
                    ]
                ]
            },
        )

    def test_uid_identity_prevents_matching_other_mirror(self):
        result = self.download([release(uid="OTHER")])
        self.assertEqual(
            result,
            {
                "links": [],
                "error": "Episode not present in link container",
                "terminal": True,
            },
        )

    def test_uid_with_changed_pack_title_fails(self):
        result = self.download([release(fulltitle=PACK_TITLE.replace("S02", "S01"))])
        self.assertEqual(
            result,
            {
                "links": [],
                "error": "Episode not present in link container",
                "terminal": True,
            },
        )

    def test_unbadged_hide_fallback_keeps_selection(self):
        result = self.download([release()])
        self.assertEqual(
            result,
            {
                "links": [
                    [
                        "https://hide.cx/fc/Container/PACK.html?season=2&episode=3",
                        "hoster",
                    ]
                ]
            },
        )

    def test_no_filecrypt_or_direct_fallback_for_episode_selection(self):
        result = self.download([release(user_id=8)])
        self.assertEqual(
            result,
            {
                "links": [],
                "error": "Episode not present in link container",
                "terminal": True,
            },
        )

    def test_missing_or_invalid_selection_fails(self):
        for selection in [
            "season=2&episode=3",
            "release=PACK-A&season=2",
            "release=PACK-A&season=2&episode=0",
        ]:
            with self.subTest(selection=selection):
                self.assertEqual(
                    self.download([release()], selection),
                    {
                        "links": [],
                        "error": "Episode not present in link container",
                        "terminal": True,
                    },
                )

    def test_duplicate_selection_parameters_fail(self):
        for suffix in ["&season=1", "&episode=4", "&release=OTHER"]:
            with self.subTest(suffix=suffix):
                self.assertEqual(
                    self.download(
                        [release()], "release=PACK-A&season=2&episode=3" + suffix
                    ),
                    {
                        "links": [],
                        "error": "Episode not present in link container",
                        "terminal": True,
                    },
                )

    def test_mirror_whitelist_cannot_fall_back_to_unfiltered_links(self):
        self.assertEqual(
            self.download([release()], mirrors=["another"]),
            {
                "links": [],
                "error": "Episode not present in link container",
                "terminal": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
