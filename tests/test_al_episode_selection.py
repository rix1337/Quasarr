# -*- coding: utf-8 -*-

import unittest

from quasarr.downloads.sources.al import _resolve_episode_selection


def _details_html(release_id, labels):
    rows = "".join(
        f'<a href="#downloads_episodes_{release_id}_{i}" data-loop="{i}" '
        f'class="list-group-item"><span><strong>{i + 1:03d}</strong> {label}</span></a>'
        for i, label in enumerate(labels)
    )
    cnl = (
        f'<a href="#downloads_episodes_{release_id}_cnl" data-loop="cnl">'
        "<span><strong>Click'n'Load alle Folgen!</strong></span></a>"
    )
    return (
        f'<div class="tab-pane" id="download_{release_id}">'
        f'<div id="downloads_episodes_{release_id}" class="episodes">'
        f'<div class="list-group panel">{cnl}{rows}</div></div></div>'
    )


class ResolveEpisodeSelectionTests(unittest.TestCase):
    def test_one_row_per_episode_keeps_legacy_index(self):
        html = _details_html(1, [f"Episode {n:03d}: Title" for n in range(1, 11)])
        self.assertEqual(_resolve_episode_selection(html, 1, 1), 0)
        self.assertEqual(_resolve_episode_selection(html, 1, 7), 6)

    def test_merged_double_episode_shifts_following_rows(self):
        labels = [
            "Episode 001-002: Doppelfolge: A, B",
            "Episode 003: C",
            "Episode 004: D",
        ]
        html = _details_html(14, labels)
        self.assertEqual(_resolve_episode_selection(html, 14, 1), 0)
        self.assertEqual(_resolve_episode_selection(html, 14, 2), 0)
        self.assertEqual(_resolve_episode_selection(html, 14, 3), 1)
        self.assertEqual(_resolve_episode_selection(html, 14, 4), 2)

    def test_release_starting_after_episode_one(self):
        html = _details_html(5, [f"Episode {n:03d}: Title" for n in range(13, 26)])
        self.assertEqual(_resolve_episode_selection(html, 5, 13), 0)
        self.assertEqual(_resolve_episode_selection(html, 5, 25), 12)

    def test_only_the_requested_release_is_used(self):
        html = _details_html(1, ["Episode 001-002: A", "Episode 003: B"])
        html += _details_html(2, ["Episode 001: A", "Episode 002: A", "Episode 003: B"])
        self.assertEqual(_resolve_episode_selection(html, 2, 3), 2)
        self.assertEqual(_resolve_episode_selection(html, 1, 3), 1)

    def test_unlabeled_or_unmatched_rows_fall_back_to_index(self):
        unlabeled = _details_html(1, ["Title A", "Title B", "Title C"])
        self.assertEqual(_resolve_episode_selection(unlabeled, 1, 2), 1)
        titled = _details_html(1, ["Die Heimkehr", "Chikara – Episode 1", "C"])
        self.assertEqual(_resolve_episode_selection(titled, 1, 1), 0)
        absolute = _details_html(1, [f"Episode {n:03d}: T" for n in range(26, 38)])
        self.assertEqual(_resolve_episode_selection(absolute, 1, 5), 4)
        self.assertEqual(_resolve_episode_selection("<html></html>", 1, 4), 3)


if __name__ == "__main__":
    unittest.main()
