# -*- coding: utf-8 -*-

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bs4 import BeautifulSoup

from quasarr.search.sources.helpers import custom_source
from quasarr.search.sources.helpers.custom_source import (
    CustomSource,
    FetchResult,
    compile_definition,
    parse_listing,
)
from quasarr.search.sources.helpers.custom_suggest import (
    build_selector,
    discover_search,
    listing_from_suggestion,
    pick_query,
    search_quality,
    suggest_download,
    suggest_listing,
)

HOST = "source.invalid"
URL = f"https://{HOST}/movies/"


def release(index, extra_class=""):
    return f"""
    <article class="post post-{40000 + index} {extra_class} genre-{index}">
      <h2 class="entry-title">
        <a href="/r/{index}/">Movie.Number{index}.2026.German.1080p.WEB.x264-GRP</a>
      </h2>
      <p class="meta"><b>Größe:</b> {index},5 GB</p>
      <p class="when"><span>Datum:</span> 0{index}.01.2026 10:00</p>
      <a href="https://www.imdb.com/title/tt100000{index}/">IMDb</a>
    </article>"""


def blog_page(count=5):
    posts = "".join(release(i, "alt" if i % 2 else "") for i in range(1, count + 1))
    return f"""<html><body>
      <nav><a href="/">Home</a><a href="/movies/">Movies</a></nav>
      <form action="/" method="get"><input type="text" name="s"></form>
      <main>{posts}</main>
      <footer><a href="/imprint/">Imprint</a></footer>
    </body></html>"""


def listing_for(markup, **kwargs):
    suggestion = suggest_listing(markup, URL, HOST, **kwargs)
    return suggestion, listing_from_suggestion(suggestion["best"])


def parse(markup, listing):
    definition = {
        "key": "c1",
        "name": "Synthetic",
        "hostname": HOST,
        "language": "de",
        "feeds": [{"category": 2000, "url": "https://{host}/movies/"}],
        "list": listing,
    }
    return parse_listing(markup, URL, compile_definition(definition)["list"], HOST)


class ListingSuggestionTests(unittest.TestCase):
    def test_posts_with_per_post_classes_are_one_item_each(self):
        suggestion, listing = listing_for(blog_page())

        self.assertEqual("article.post", listing["item"])
        report = parse(blog_page(), listing)
        self.assertEqual(5, len(report["rows"]))
        row = report["rows"][0]
        self.assertEqual("Movie.Number1.2026.German.1080p.WEB.x264-GRP", row["title"])
        self.assertEqual(f"https://{HOST}/r/1/", row["link"])
        self.assertEqual(1536, row["size_mb"])
        self.assertEqual("Thu, 01 Jan 2026 10:00:00 +0000", row["date"])
        self.assertEqual("tt1000001", row["imdb_id"])

    def test_labels_are_suggested_for_mixed_text(self):
        suggestion, listing = listing_for(blog_page())
        self.assertEqual({"label": "Größe"}, listing["size"])
        self.assertEqual({"label": "Datum"}, listing["date"])

    def test_navigation_links_are_never_items(self):
        suggestion, _ = listing_for(blog_page())
        self.assertFalse(
            any("nav" in c["selector"] for c in suggestion["items"]), suggestion
        )

    def test_one_post_with_several_releases_splits_per_release(self):
        tables = "".join(
            f"""<table><tr><td>
              <strong>Datum:</strong> 0{i}.02.2026<br>
              <strong>Release: <a href="https://filecrypt.cc/Container/ABC{i}.html">
                »Show.S0{i}.German.720p.WEB.x264-GRP«</a></strong><br>
              <strong>Size:</strong> {i} GB
            </td></tr></table>"""
            for i in range(1, 5)
        )
        markup = f"""<html><body><article class="post">
            <h2 class="entry-title"><a href="/show/">Show</a></h2>
            <div class="entry-content">{tables}</div></article></body></html>"""

        _, listing = listing_for(markup)
        report = parse(markup, listing)

        self.assertEqual(
            [f"Show.S0{i}.German.720p.WEB.x264-GRP" for i in range(1, 5)],
            [row["title"] for row in report["rows"]],
        )
        self.assertTrue(report["rows"][0]["link"].startswith("https://filecrypt.cc/"))
        self.assertEqual(2048, report["rows"][1]["size_mb"])

    def test_single_result_search_page(self):
        markup = blog_page(count=1)
        self.assertIsNone(suggest_listing(markup, URL, HOST)["best"])
        _, listing = listing_for(markup, min_items=1)
        self.assertEqual(1, len(parse(markup, listing)["rows"]))

    def test_search_templates_come_from_forms_and_the_feed_path(self):
        suggestion, _ = listing_for(blog_page())
        self.assertEqual(
            {"url": "https://{host}/?s={q}", "method": "get"}, suggestion["search"][0]
        )
        self.assertIn(
            {"url": "https://{host}/movies/?s={q}", "method": "get"},
            suggestion["search"],
        )

    def test_post_search_forms_keep_their_hidden_fields(self):
        markup = blog_page().replace(
            '<form action="/" method="get"><input type="text" name="s"></form>',
            '<form action="/login" method="post"><input type="text" name="login_name">'
            '<input type="password" name="pw"></form>'
            '<form action="/search" method="post"><input type="search" name="q">'
            '<input type="hidden" name="mode" value="all"></form>',
        )
        suggestion, _ = listing_for(markup)
        self.assertEqual(
            {
                "url": "https://{host}/search",
                "method": "post",
                "body": "q={q}&mode=all",
            },
            suggestion["search"][0],
        )


class SearchDiscoveryTests(unittest.TestCase):
    LISTING = {
        "item": "article.post",
        "title": {"selector": "h2 a"},
        "link": {"selector": "h2 a"},
    }

    def test_query_is_the_release_name(self):
        rows = [
            {"title": "Some.Movie.2026.German.1080p.WEB.x264-GRP"},
            {"title": "Other.Film.S01E02.German.720p.WEB.x264-GRP"},
        ]
        self.assertEqual("Some Movie", pick_query(rows)[0])
        self.assertEqual(
            ["Other", "Film"], pick_query(rows[1:])[1]["title"].split(".")[:2]
        )

    def test_first_template_that_searches_wins_and_imdb_is_probed(self):
        feed = blog_page()
        hit = blog_page(count=1)
        pages = {
            f"https://{HOST}/movies/": feed,
            f"https://{HOST}/?s=Movie+Number1": feed,  # ignores the query
            f"https://{HOST}/movies/?s=Movie+Number1": hit,
            f"https://{HOST}/movies/?s=tt1000001": hit,
        }

        def fetch(_state, url, _timeout, _solver, data=None):
            if url in pages:
                return FetchResult(pages[url], None, 200)
            return FetchResult(None, "Page not found (404)", 404)

        result = discover_search(None, HOST, URL, self.LISTING, fetch=fetch)

        self.assertTrue(result["success"], result)
        self.assertEqual("Movie Number1", result["query"])
        self.assertEqual(
            {"url": "https://{host}/movies/?s={q}", "method": "get"}, result["search"]
        )
        self.assertEqual("imdb", result["mode"])
        self.assertFalse(result["attempts"][0]["works"])

    def test_post_searches_send_the_query_in_the_body(self):
        definition = {
            "key": "c1",
            "name": "Synthetic",
            "hostname": HOST,
            "language": "de",
            "search": {
                "mode": "title",
                "method": "post",
                "url": "https://{host}/search",
                "body": "q={q}&mode=all",
                "categories": [2000],
            },
            "list": self.LISTING,
        }
        url, data = CustomSource(definition).search_request("Some Movie")
        self.assertEqual(f"https://{HOST}/search", url)
        self.assertEqual({"q": "Some Movie", "mode": "all"}, data)


class FeedTests(unittest.TestCase):
    RSS = """<?xml version="1.0"?><rss><channel><title>Site</title>
        <item><title>Movie.One.2026.1080p.WEB.x264-GRP</title>
          <link>https://source.invalid/one/</link>
          <pubDate>Sat, 10 Jan 2026 08:30:00 +0000</pubDate></item>
        <item><title><![CDATA[Movie.Two.2026.1080p.WEB.x264-GRP]]></title>
          <link>https://source.invalid/two/</link>
          <pubDate>Sat, 10 Jan 2026 09:30:00 +0000</pubDate></item>
        </channel></rss>"""

    def test_rss_links_survive_the_html_parser(self):
        suggestion, listing = listing_for(self.RSS)
        self.assertEqual("item", listing["item"])
        report = parse(self.RSS, listing)
        self.assertEqual(
            [f"https://{HOST}/one/", f"https://{HOST}/two/"],
            [row["link"] for row in report["rows"]],
        )
        self.assertEqual(
            "Movie.Two.2026.1080p.WEB.x264-GRP", report["rows"][1]["title"]
        )
        self.assertEqual("Sat, 10 Jan 2026 08:30:00 +0000", report["rows"][0]["date"])


class TitleCleanupTests(unittest.TestCase):
    def test_listing_date_and_size_around_the_name_are_dropped(self):
        markup = "".join(
            f'<div class="row"><a href="/r/{i}">0{i}.11.2026 - 13:04 '
            f"Movie.{i}.2026.1080p.WEB.x264-GRP – 14.6 GB</a></div>"
            for i in range(1, 4)
        )
        listing = {
            "item": "div.row",
            "title": {"selector": "a"},
            "link": {"selector": "a"},
        }
        titles = [row["title"] for row in parse(markup, listing)["rows"]]
        self.assertEqual("Movie.1.2026.1080p.WEB.x264-GRP", titles[0])


class SelectorTests(unittest.TestCase):
    def test_generated_classes_are_skipped(self):
        soup = BeautifulSoup(
            '<div><span class="css-1x2y3z a8f93kd02jd83k">x</span>'
            '<span class="size">1 GB</span></div>',
            "html.parser",
        )
        root = soup.div
        self.assertEqual("span.size", build_selector(soup.select("span")[1], root))
        self.assertNotIn("css-", build_selector(soup.select("span")[0], root))


class SearchQualityTests(unittest.TestCase):
    def rows(self, *titles):
        return [{"title": t, "link": f"https://{HOST}/{t}"} for t in titles]

    def test_matching_results_work(self):
        result = search_quality("Movie Two", self.rows("Movie.Two.2026-GRP"))
        self.assertTrue(result["works"])

    def test_front_page_answer_does_not_work(self):
        feed = self.rows("A.2026-GRP", "B.2026-GRP", "Movie.Two.2026-GRP")
        result = search_quality("Movie Two", feed, feed)
        self.assertTrue(result["same_as_feed"])
        self.assertFalse(result["works"])

    def test_one_match_among_hundreds_does_not_work(self):
        rows = self.rows("Movie.Two.2026-GRP", *[f"X{i}.2026-GRP" for i in range(200)])
        self.assertFalse(search_quality("Movie Two", rows)["works"])


class DownloadSuggestionTests(unittest.TestCase):
    def test_crypter_links_are_found(self):
        markup = """<div class="downloads">
            <a href="https://filecrypt.cc/Container/A.html">Rapidgator</a>
            <a href="https://filecrypt.cc/Container/B.html">DDownload</a></div>
            <a href="/comments/">Comments</a>"""
        best = suggest_download(markup, f"https://{HOST}/r/", HOST)[0]
        self.assertEqual("text", best["spec"]["mirror"])
        self.assertEqual(2, best["known"])
        self.assertNotIn("redirects", best["spec"])

    def test_hoster_buttons_on_the_site_resolve_redirects(self):
        markup = """<div class="mirrors">
            <a class="btn background-rapidgator" href="/go/1">Rapidgator</a>
            <a class="btn background-ddownload" href="/go/2">DDownload</a></div>"""
        best = suggest_download(markup, f"https://{HOST}/r/", HOST)[0]
        self.assertTrue(best["spec"]["redirects"])

    def test_redirect_links_are_resolved_at_grab_time(self):
        definition = {
            "key": "c1",
            "name": "Synthetic",
            "hostname": HOST,
            "language": "de",
            "feeds": [{"category": 2000, "url": "https://{host}/"}],
            "list": {"item": "div", "title": {}, "link": {}},
            "download": {
                "links": {"selector": "div.mirrors a", "mirror": "text"},
                "redirects": True,
            },
        }
        markup = """<div class="mirrors">
            <a href="/go/1">Rapidgator</a><a href="/go/2">Dead</a></div>"""
        source = CustomSource(definition)
        targets = {
            f"https://{HOST}/go/1": "https://filecrypt.cc/Container/A.html",
            f"https://{HOST}/go/2": None,
        }
        with (
            patch.object(
                custom_source,
                "fetch_markup",
                return_value=FetchResult(markup, None, 200),
            ),
            patch(
                "quasarr.downloads.sources.helpers.redirect.resolve_crypter_redirect",
                side_effect=lambda url, *a, **k: targets[url],
            ),
        ):
            links, error, _, _ = source.load_download_links(
                SimpleNamespace(values={"user_agent": "UA/1.0"}), f"https://{HOST}/r/"
            )
        self.assertIsNone(error)
        self.assertEqual(
            [["https://filecrypt.cc/Container/A.html", "rapidgator"]], links
        )


if __name__ == "__main__":
    unittest.main()
