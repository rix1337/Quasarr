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

BY_AUTHOR = (
    "<html><body>"
    + "".join(
        f'<div class="post"><h2><a href="/r/{i}">Movie.{i}.2026.1080p.WEB.x264-GRP</a></h2>'
        f'<a class="author" href="/user/uploader/">uploader</a>'
        f'<p class="meta">Size: {i} GB</p></div>'
        for i in range(1, 6)
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

    def test_suggestions_skip_repeated_and_duplicate_values(self):
        from quasarr.search.sources.helpers.custom_suggest import suggest_listing

        fields = suggest_listing(
            BY_AUTHOR, "https://source.invalid/", "source.invalid"
        )["best"]["fields"]
        links = [c["samples"][0] for c in fields["link"]]
        # the author page repeats in every release, so it is no release link
        self.assertNotIn("https://source.invalid/user/uploader/", links)
        self.assertIn("https://source.invalid/r/1", links)
        # one choice per distinct set of values
        values = [tuple(c["samples"]) for c in fields["title"]]
        self.assertEqual(len(values), len(set(values)))

    def test_a_missed_click_takes_the_nearest_matching_element(self):
        soup = annotate_page(BY_AUTHOR)
        size_line = soup.select("div.post p.meta")[1]
        picked = pick_field(
            soup,
            size_line["data-q"],
            "div.post",
            "link",
            "https://source.invalid/",
            "source.invalid",
        )
        self.assertEqual("https://source.invalid/r/2", picked["value"])
        self.assertEqual(1.0, picked["result"]["coverage"])

    def test_menu_links_suggest_a_page_per_kind(self):
        from bs4 import BeautifulSoup

        from quasarr.search.sources.helpers.custom_suggest import suggest_feeds

        menu = BeautifulSoup(
            '<nav><a href="/">Home</a><a href="/filme/">Filme</a>'
            '<a href="/serien/">Serien</a><a href="/ebooks/">E-Books</a>'
            '<a href="/all/">Music</a><a href="/all/">Movies HD</a></nav>'
            '<a href="/r/1">Some.Film.2026.1080p.WEB.x264-GRP</a>',
            "html.parser",
        )
        self.assertEqual(
            {2000: "/filme/", 5000: "/serien/", 7000: "/ebooks/"},
            suggest_feeds(menu, "https://source.invalid/", "source.invalid"),
        )
        # menus split by language: the site's own wins
        split = BeautifulSoup(
            '<a href="/en/">English Movies</a><a href="/de/">German Movies</a>'
            '<a href="/int/">International Movies</a>',
            "html.parser",
        )
        self.assertEqual(
            {2000: "/de/"},
            suggest_feeds(split, "https://source.invalid/", "source.invalid", "de"),
        )

    def test_genres_and_post_titles_are_no_kind_pages(self):
        from bs4 import BeautifulSoup

        from quasarr.search.sources.helpers.custom_suggest import suggest_feeds

        page = BeautifulSoup(
            '<nav><ul><li><a href="/c/filme/">Filme</a><ul>'
            '<li><a href="/c/filme/film-noir/">Film-Noir</a></li>'
            '<li><a href="/c/filme/music/">Music</a></li></ul></li>'
            '<li><a href="/c/serien/">Serien</a></li>'
            '<li><a href="/c/new/">+++ Neuerscheinungen +++</a></li></ul></nav>'
            '<article><a href="/2026/01/01/x/">Der Film (2026)</a>'
            '<a href="/c/musik/">Musik</a></article>',
            "html.parser",
        )
        self.assertEqual(
            {2000: "/c/filme/", 5000: "/c/serien/"},
            suggest_feeds(page, "https://source.invalid/", "source.invalid", "de"),
        )
        # without a movie page, the newest releases carry the movies
        generic = BeautifulSoup(
            '<nav><a href="/c/serie/">Serie</a><a href="/c/new/">Neuerscheinungen</a></nav>',
            "html.parser",
        )
        self.assertEqual(
            {5000: "/c/serie/", 2000: "/c/new/"},
            suggest_feeds(generic, "https://source.invalid/", "source.invalid", "de"),
        )

    def test_login_and_script_pages_are_explained(self):
        from bs4 import BeautifulSoup

        from quasarr.search.sources.helpers.custom_suggest import unreadable_reason

        login = BeautifulSoup(
            '<form><input name="u"><input type="password"></form>', "html.parser"
        )
        app = BeautifulSoup(
            '<body><div id="app"></div><script></script></body>', "html.parser"
        )
        page = BeautifulSoup(
            "<body><p>" + "Some text " * 50 + "</p></body>", "html.parser"
        )
        self.assertEqual("login", unreadable_reason(login))
        self.assertEqual("javascript", unreadable_reason(app))
        self.assertIsNone(unreadable_reason(page))

    def test_a_page_offers_its_own_feed_and_language(self):
        from bs4 import BeautifulSoup

        from quasarr.search.sources.helpers.custom_suggest import (
            page_language,
            page_rss,
        )

        page = BeautifulSoup(
            '<html lang="en-US"><head><link rel="alternate" type="application/rss+xml" '
            'href="/feed/"></head><body><a class="rss-btn" href="/music/feed/">x</a>'
            '<a href="/music/comments/feed/" title="RSS">c</a></body></html>',
            "html.parser",
        )
        url = "https://source.invalid/music/"
        self.assertEqual("/music/feed/", page_rss(page, url, "source.invalid"))
        self.assertEqual("en", page_language(page))
        german = BeautifulSoup(
            "<p>" + "Der Film und die Serie mit dem Ton ist neu. " * 5 + "</p>",
            "html.parser",
        )
        self.assertEqual("de", page_language(german))

    def test_release_names_inside_post_texts_are_found_and_headlines_flagged(self):
        from quasarr.search.sources.helpers.custom_source import find_release_name

        self.assertEqual(
            "Synthetic Movie 2026 1080p WEB-DL x265-GRP",
            find_release_name(
                "Synthetic Movie 2026 1080p WEB-DL x265-GRP A story about it."
            ),
        )
        self.assertEqual(
            "Synthetic.Movie.2026.1080p.WEB.x264-GRP",
            find_release_name("Download Synthetic.Movie.2026.1080p.WEB.x264-GRP now"),
        )
        self.assertIsNone(find_release_name("Synthetic Movie (2026)"))
        # without a group the name ends with its last release word
        self.assertEqual(
            "Synthetic Movie 2004 1080p WEBRip x264 AAC",
            find_release_name(
                'Synthetic Movie 2004 1080p WEBRip x264 AAC- "Synthetic Movie" tells'
            ),
        )

        page = annotate_page(
            "<html><body>"
            + "".join(
                f'<div class="post"><h2><a href="/r/{i}">Synthetic Movie {i} (2026)</a></h2>'
                f'<p class="text">Synthetic Movie {i} 2026 1080p WEB-DL x265-GRP A story.</p></div>'
                for i in range(1, 4)
            )
            + "</body></html>"
        )
        # a post without a release name in its text keeps its headline
        mixed = str(page).replace(
            "Synthetic Movie 3 2026 1080p WEB-DL x265-GRP A story.", "A story."
        )
        from quasarr.search.sources.helpers.custom_suggest import suggest_listing

        titles = suggest_listing(
            mixed, "https://source.invalid/", "source.invalid", min_items=1
        )["best"]["fields"]["title"]
        self.assertIsInstance(titles[0]["spec"], list)
        self.assertEqual(1.0, titles[0]["coverage"])
        headline = page.select("div.post h2 a")[1]
        picked = pick_field(
            page,
            headline["data-q"],
            "div.post",
            "title",
            "https://source.invalid/",
            "source.invalid",
        )
        # the headline gives way to the release name in the post text
        self.assertEqual("release", picked["spec"]["find"])
        self.assertEqual(
            "Synthetic Movie 2 2026 1080p WEB-DL x265-GRP", picked["value"]
        )
        self.assertIn("headline", picked["note"])

    def test_embedded_json_cannot_close_its_script(self):
        text = json_for_script({"name": "</script><script>alert(1)</script>"})
        self.assertNotIn("<", text)
        self.assertNotIn(">", text)


if __name__ == "__main__":
    unittest.main()
