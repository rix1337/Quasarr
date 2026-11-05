# -*- coding: utf-8 -*-
"""The wizard never lets site or user content run as code."""

import unittest

from quasarr.providers.html_templates import json_for_script
from quasarr.search.sources.helpers.custom_suggest import (
    annotate_page,
    pick_field,
    pick_item,
    preview_html,
)

HOSTILE = (
    """<html><head><base href="https://evil.invalid/"><meta http-equiv="refresh" content="0;url=https://evil.invalid/">
<script>alert(1)</script><link rel="stylesheet" href="https://evil.invalid/x.css"></head>
<body onload="alert(2)"><iframe src="https://evil.invalid/"></iframe>
<form action="https://evil.invalid/"><input name="x"></form><svg><script>alert(3)</script></svg>
"""
    + "".join(
        f'<div class="post"><h2><a href="javascript:alert({i})" onclick="alert(4)">Movie.{i}.2026.1080p.WEB.x264-GRP</a></h2>'
        f'<img src="https://evil.invalid/{i}.png" onerror="alert(5)"><p style="background:url(https://evil.invalid/)">Size: {i} GB</p></div>'
        for i in range(1, 4)
    )
    + "</body></html>"
)


class PreviewSafetyTests(unittest.TestCase):
    def test_preview_runs_only_the_picker_and_keeps_images_and_styles(self):
        page = preview_html(
            annotate_page(HOSTILE), "https://source.invalid/list/"
        ).lower()
        # the picker script is the only one, and only it may run
        self.assertEqual(1, page.count("<script"))
        nonce = page.split('<script nonce="', 1)[1].split('"', 1)[0]
        self.assertIn(f"script-src 'nonce-{nonce}'", page)
        for needle in (
            "alert(",
            "onload",
            "onclick",
            "onerror",
            "javascript:",
            "<iframe",
            "<form",
            "<input",
            "refresh",
            "<svg",
        ):
            self.assertNotIn(needle, page)
        # the page's own base is replaced, so links resolve against the page
        self.assertEqual(1, page.count("<base"))
        self.assertIn('<base href="https://source.invalid/list/">', page)
        self.assertIn('href="https://evil.invalid/x.css"', page)
        self.assertIn('src="https://evil.invalid/1.png"', page)
        self.assertIn("data-q=", page)

    def test_clicks_become_selectors_on_the_same_parse(self):
        soup = annotate_page(HOSTILE.replace("javascript:alert", "/r/"))
        anchor = soup.select("div.post h2 a")[1]
        self.assertEqual(
            "div.post",
            pick_item(
                soup, anchor["data-q"], "https://source.invalid/", "source.invalid"
            )["selector"],
        )
        picked = pick_field(
            soup,
            anchor["data-q"],
            "div.post",
            "title",
            "https://source.invalid/",
            "source.invalid",
        )
        self.assertEqual({"selector": "a"}, picked["spec"])
        self.assertEqual(1.0, picked["result"]["coverage"])

    def test_highlight_counts_only_values_that_read(self):
        from quasarr.search.sources.helpers.custom_suggest import highlight

        soup = annotate_page(HOSTILE)
        marked = highlight(
            soup,
            "div.post",
            {"size": {"selector": "p"}, "date": {"selector": "p"}},
            "https://source.invalid/",
            "source.invalid",
        )
        self.assertEqual(3, len(marked["items"]))
        self.assertEqual(3, len(marked["fields"]["size"]))
        # a size line is no date, so it does not count as one
        self.assertEqual([], marked["fields"]["date"])

    def test_clicks_outside_a_release_are_refused(self):
        soup = annotate_page(HOSTILE)
        body_q = soup.body["data-q"]
        self.assertIn(
            "error",
            pick_field(
                soup,
                body_q,
                "div.post",
                "title",
                "https://source.invalid/",
                "source.invalid",
            ),
        )

    def test_embedded_json_cannot_close_its_script(self):
        text = json_for_script({"name": "</script><script>alert(1)</script>"})
        self.assertNotIn("<", text)
        self.assertNotIn(">", text)


if __name__ == "__main__":
    unittest.main()
