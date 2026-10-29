# -*- coding: utf-8 -*-

import time
import unittest
from unittest.mock import MagicMock, patch

from quasarr.search.sources import he

POST_URL = "https://source.invalid/synthetic-show-s01e01/"

SEARCH_HTML = f"""
<div class="item"><div class="data">
  <h5><a href="{POST_URL}">Synthetic.Show.S01E01.1080p.WEB.h264-GRP – 1.2 GB</a></h5>
  <span class="post-time">Posted 2 days ago</span>
</div></div>
"""


def _response(html):
    response = MagicMock()
    response.content = html.encode("utf-8")
    return response


class HePublishedDateTests(unittest.TestCase):
    def _search(self, post_html):
        shared_state = MagicMock()
        shared_state.values = {
            "user_agent": "test-agent",
            "config": lambda section: {"he": "source.invalid"},
        }

        def get(url, **kwargs):
            return _response(post_html if url == POST_URL else SEARCH_HTML)

        with (
            patch.object(he.requests, "get", side_effect=get),
            patch.object(he, "generate_download_link", return_value="link"),
            patch.object(he, "clear_hostname_issue"),
            patch.object(he, "mark_hostname_issue"),
        ):
            releases = he.Source().search(shared_state, time.time(), 5000)
        return [release["details"]["date"] for release in releases]

    def test_uses_absolute_published_date_from_post(self):
        self.assertEqual(
            ["Thu, 23 Oct 2031 10:11:40 +0000"],
            self._search(
                '<meta itemprop="datePublished" content="2031-10-23T13:41:40+03:30"/>'
            ),
        )

    def test_falls_back_to_relative_post_time(self):
        with patch.object(he, "_parse_posted_ago", return_value="relative"):
            self.assertEqual(["relative"], self._search("<div></div>"))


if __name__ == "__main__":
    unittest.main()
