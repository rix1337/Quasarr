# -*- coding: utf-8 -*-

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from quasarr.constants import SEARCH_CAT_MOVIES, SEARCH_CAT_SHOWS
from quasarr.providers import shared_state
from quasarr.search.sources.helpers import custom_source
from quasarr.search.sources.helpers.custom_source import (
    CustomSource,
    DefinitionError,
    FetchResult,
    compile_definition,
    describe_report,
    parse_date,
    parse_download_links,
    parse_imdb_id,
    parse_listing,
    parse_size,
)
from quasarr.storage import custom_sources

HOST = "source.invalid"
NOW = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


def make_definition(**overrides):
    definition = {
        "key": "c1",
        "name": "Synthetic",
        "hostname": HOST,
        "language": "de",
        "feeds": [{"category": SEARCH_CAT_MOVIES, "url": "https://{host}/movies/"}],
        "search": {
            "mode": "imdb",
            "url": "https://{host}/?s={q}",
            "categories": [SEARCH_CAT_MOVIES, SEARCH_CAT_SHOWS],
        },
        "list": {
            "item": "article.post",
            "title": {"selector": "h2 a"},
            "link": {"selector": "h2 a"},
            "size": {"selector": ".info", "label": "Size"},
            "date": {"selector": "time", "attr": "datetime"},
        },
        "download": {"links": {"selector": ".downloads a", "mirror": "text"}},
    }
    definition.update(overrides)
    return definition


def post(title, href, size="1,4 GB", date="2026-01-10T08:30:00", extra=""):
    return f"""
    <article class="post">
      <h2><a href="{href}">{title}</a></h2>
      <p class="info"><b>Size:</b> {size} | Genre: Drama</p>
      <time datetime="{date}">10.01.2026</time>
      {extra}
    </article>"""


def page(*posts):
    return f"<html><body><nav><a href='/'>Home</a></nav>{''.join(posts)}</body></html>"


def fake_shared_state():
    return SimpleNamespace(values={"user_agent": "UA/1.0"})


class ParserTests(unittest.TestCase):
    def test_sizes_in_common_notations(self):
        self.assertEqual(1433, parse_size("Size: 1,4 GB"))
        self.assertEqual(1433, parse_size("1.4GiB"))
        self.assertEqual(700, parse_size("700 MB"))
        self.assertEqual(1536, parse_size("1.536,0 MB"))
        self.assertEqual(2048, parse_size("2", unit="GB"))
        self.assertIsNone(parse_size("no size here"))
        self.assertEqual(0, parse_size("350 KB"))

    def test_dates_in_common_notations(self):
        self.assertEqual(
            "Sat, 10 Jan 2026 08:30:00 +0000", parse_date("2026-01-10T08:30:00")
        )
        self.assertEqual(
            "Sat, 10 Jan 2026 08:30:00 +0000", parse_date("10.01.2026 08:30")
        )
        self.assertEqual(
            "Sat, 10 Jan 2026 00:00:00 +0000", parse_date("Samstag, 10. Januar 2026")
        )
        self.assertEqual(
            "Sat, 10 Jan 2026 00:00:00 +0000", parse_date("January 10, 2026")
        )
        self.assertEqual(
            "Sat, 10 Jan 2026 08:30:00 +0000",
            parse_date("10/01/2026 08:30", fmt="%d/%m/%Y %H:%M"),
        )
        self.assertIsNone(parse_date("yesterday"))

    def test_future_dates_are_clamped_to_now(self):
        self.assertEqual(
            "Thu, 15 Jan 2026 12:00:00 +0000", parse_date("2030-01-01", now=NOW)
        )

    def test_imdb_ids_from_links_and_text(self):
        self.assertEqual(
            "tt1234567", parse_imdb_id("https://imdb.invalid/imdb.com/title/tt1234567/")
        )
        self.assertEqual("tt7654321", parse_imdb_id("IMDb: tt7654321"))
        self.assertIsNone(parse_imdb_id("tt12"))


class DefinitionTests(unittest.TestCase):
    def test_valid_definition_compiles(self):
        spec = compile_definition(make_definition())
        self.assertEqual(HOST, spec["hostname"])
        self.assertIn(SEARCH_CAT_MOVIES, spec["feeds"])

    def test_invalid_definitions_name_the_field(self):
        cases = {
            "key": make_definition(key="mb"),
            "hostname": make_definition(hostname="localhost"),
            "feeds[0].url": make_definition(
                feeds=[{"category": SEARCH_CAT_MOVIES, "url": "https://other.invalid/"}]
            ),
            "search.url": make_definition(
                search={"mode": "imdb", "url": "https://{host}/", "categories": [2000]}
            ),
            "list.item": make_definition(
                list={"item": "article[", "title": {}, "link": {}}
            ),
            "list.title": make_definition(list={"item": "article", "link": {}}),
        }
        for field, definition in cases.items():
            with self.subTest(field=field):
                with self.assertRaises(DefinitionError) as raised:
                    compile_definition(definition)
                self.assertIn(field, str(raised.exception))

    def test_host_template_cannot_be_extended_to_another_host(self):
        with self.assertRaises(DefinitionError):
            compile_definition(
                make_definition(
                    feeds=[{"category": 2000, "url": "https://{host}.other.invalid/"}]
                )
            )

    def test_file_hoster_cannot_be_a_source(self):
        with self.assertRaises(DefinitionError):
            compile_definition(make_definition(hostname="rapidgator.net"))


class ListingTests(unittest.TestCase):
    def setUp(self):
        self.listing = compile_definition(make_definition())["list"]

    def parse(self, markup):
        return parse_listing(markup, f"https://{HOST}/movies/", self.listing, HOST, NOW)

    def test_bad_items_are_skipped_and_good_items_survive(self):
        markup = page(
            post("Movie.One.2026.1080p.WEB.x264-GRP", "/one/"),
            '<article class="post"><p>no title here</p></article>',
            post("Movie.Two.2026.1080p.WEB.x264-GRP", "javascript:void(0)"),
            post("Movie.Three.2026.1080p.WEB.x264-GRP", "https://other.invalid/x"),
            post("Movie.Four.2026.1080p.WEB.x264-GRP", "/four/"),
            post("Movie.Four.Again.2026.1080p.WEB.x264-GRP", "/four/"),
        )
        report = self.parse(markup)

        self.assertEqual(6, report["items"])
        self.assertEqual(
            ["Movie.One.2026.1080p.WEB.x264-GRP", "Movie.Four.2026.1080p.WEB.x264-GRP"],
            [row["title"] for row in report["rows"]],
        )
        self.assertEqual(f"https://{HOST}/one/", report["rows"][0]["link"])
        self.assertEqual(1, report["skipped"]["title not found"])
        self.assertEqual(
            2, report["skipped"]["link is not an http(s) link on this site"]
        )
        self.assertEqual(1, report["skipped"]["duplicate link"])
        self.assertIsNone(describe_report(report))

    def test_label_reads_the_value_after_it(self):
        row = self.parse(page(post("Movie.2026.1080p.WEB.x264-GRP", "/m/")))["rows"][0]
        self.assertEqual(1433, row["size_mb"])
        self.assertEqual("Sat, 10 Jan 2026 08:30:00 +0000", row["date"])

    def test_missing_optional_fields_fall_back(self):
        markup = page(
            post("Movie.2026.1080p.WEB.x264-GRP", "/m/", size="unknown", date="soon")
        )
        report = self.parse(markup)
        row = report["rows"][0]
        self.assertEqual(0, row["size_mb"])
        self.assertEqual("Thu, 15 Jan 2026 12:00:00 +0000", row["date"])
        self.assertEqual(
            {"size not parsed": 1, "date not parsed": 1}, report["warnings"]
        )

    def test_imdb_id_is_found_in_item_links(self):
        extra = '<a href="https://www.imdb.com/title/tt1234567/">IMDb</a>'
        row = self.parse(page(post("Movie.2026.1080p.WEB-GRP", "/m/", extra=extra)))[
            "rows"
        ][0]
        self.assertEqual("tt1234567", row["imdb_id"])

    def test_unclosed_comment_in_one_item_spares_the_others(self):
        from quasarr.providers.utils import escape_unclosed_openers

        markup = page(
            post("Movie.One.2026.1080p.WEB-GRP", "/one/", extra="<!-- stray"),
            post("Movie.Two.2026.1080p.WEB-GRP", "/two/"),
        )
        report = self.parse(escape_unclosed_openers(markup))
        self.assertEqual(2, len(report["rows"]))

    def test_layout_change_and_all_skipped_are_issues(self):
        self.assertIn("no items matched", describe_report(self.parse(page())))
        report = self.parse(page('<article class="post"><p>x</p></article>'))
        self.assertIn("title not found", describe_report(report))


class DownloadParsingTests(unittest.TestCase):
    def test_known_filter_keeps_crypters_and_hosters(self):
        download = compile_definition(make_definition())["download"]
        markup = """<div class="downloads">
            <a href="https://filecrypt.cc/Container/ABC.html">Rapidgator</a>
            <a href="https://rapidgator.net/file/xyz">RG direct</a>
            <a href="/comments/">Comments</a>
            <a href="https://filecrypt.cc/Container/ABC.html">Duplicate</a>
        </div>"""
        links = parse_download_links(markup, f"https://{HOST}/r/", download)
        self.assertEqual(
            [
                ["https://filecrypt.cc/Container/ABC.html", "rapidgator"],
                ["https://rapidgator.net/file/xyz", "rg direct"],
            ],
            links,
        )


@patch("quasarr.providers.utils.generate_download_link", return_value="payload")
@patch.object(custom_source, "clear_hostname_issue")
@patch.object(custom_source, "mark_hostname_issue")
class SourceTests(unittest.TestCase):
    def setUp(self):
        self.source = CustomSource(make_definition())

    def test_feed_returns_releases(self, mark, clear, _link):
        markup = page(post("Movie.2026.1080p.WEB.x264-GRP", "/m/"))
        with patch.object(
            custom_source, "fetch_markup", return_value=FetchResult(markup, None, 200)
        ) as fetch:
            releases = self.source.feed(fake_shared_state(), 0, SEARCH_CAT_MOVIES)

        fetch.assert_called_once()
        self.assertEqual(f"https://{HOST}/movies/", fetch.call_args.args[1])
        self.assertEqual(
            "Movie.2026.1080p.WEB.x264-GRP", releases[0]["details"]["title"]
        )
        self.assertEqual("c1", releases[0]["details"]["hostname"])
        self.assertEqual(1433 * 1024 * 1024, releases[0]["details"]["size"])
        clear.assert_called_once_with("c1")
        mark.assert_not_called()

    def test_feed_without_items_marks_a_hostname_issue(self, mark, clear, _link):
        with patch.object(
            custom_source, "fetch_markup", return_value=FetchResult(page(), None, 200)
        ):
            self.assertEqual([], self.source.feed(fake_shared_state(), 0, 2000))
        self.assertIn("no items matched", mark.call_args.args[2])

    def test_feed_ignores_categories_without_a_feed(self, mark, clear, _link):
        with patch.object(custom_source, "fetch_markup") as fetch:
            self.assertEqual([], self.source.feed(fake_shared_state(), 0, 5000))
        fetch.assert_not_called()

    def test_imdb_search_drops_releases_of_another_title(self, mark, clear, _link):
        other = '<a href="https://www.imdb.com/title/tt7654321/">IMDb</a>'
        markup = page(
            post("Movie.2026.1080p.WEB.x264-GRP", "/a/"),
            post("Other.2026.1080p.WEB.x264-GRP", "/b/", extra=other),
        )
        with patch.object(
            custom_source, "fetch_markup", return_value=FetchResult(markup, None, 200)
        ) as fetch:
            releases = self.source.search(
                fake_shared_state(), 0, SEARCH_CAT_MOVIES, "tt1234567"
            )

        self.assertEqual(f"https://{HOST}/?s=tt1234567", fetch.call_args.args[1])
        self.assertEqual(["/a/"], [r["details"]["source"][-3:] for r in releases])
        self.assertEqual("tt1234567", releases[0]["details"]["imdb_id"])

    def test_empty_search_is_not_an_issue(self, mark, clear, _link):
        with patch.object(
            custom_source, "fetch_markup", return_value=FetchResult(page(), None, 200)
        ):
            self.source.search(fake_shared_state(), 0, 2000, "tt1234567")
        mark.assert_not_called()

    def test_removed_release_page_is_not_an_issue(self, mark, clear, _link):
        with patch.object(
            custom_source,
            "fetch_markup",
            return_value=FetchResult(None, "Page not found (404)", 404),
        ):
            result = self.source.get_download_links(
                fake_shared_state(), f"https://{HOST}/r/", [], "t", ""
            )
        self.assertEqual({"links": []}, result)
        mark.assert_not_called()

    def test_download_off_site_is_never_fetched(self, mark, clear, _link):
        with patch.object(custom_source, "fetch_markup") as fetch:
            result = self.source.get_download_links(
                fake_shared_state(), "https://other.invalid/r/", [], "t", ""
            )
        self.assertEqual({"links": []}, result)
        fetch.assert_not_called()

    def test_unexpected_errors_never_escape(self, mark, clear, _link):
        with patch.object(custom_source, "fetch_markup", side_effect=RuntimeError("x")):
            self.assertEqual([], self.source.feed(fake_shared_state(), 0, 2000))
            self.assertEqual([], self.source.search(fake_shared_state(), 0, 2000, "q"))
        mark.assert_called()


class FetchTests(unittest.TestCase):
    URL = f"https://{HOST}/movies/"
    BLOCKED = FetchResult(None, custom_source.BLOCKED_ERROR, 403, blocked=True)
    PAGE = FetchResult("<html></html>", None, 200)

    def setUp(self):
        custom_source._host_sessions.clear()
        self.addCleanup(custom_source._host_sessions.clear)

    def fetch(self, fetches, solver=True, clearance=True):
        with (
            patch.object(custom_source, "_fetch_once", side_effect=fetches) as once,
            patch(
                "quasarr.providers.utils.is_flaresolverr_available",
                return_value=solver,
            ),
            patch(
                "quasarr.providers.cloudflare.update_session_via_flaresolverr",
                return_value={"session": object(), "user_agent": "Solver/1.0"}
                if clearance
                else False,
            ) as solve,
        ):
            result = custom_source.fetch_markup(fake_shared_state(), self.URL, 5, False)
        return result, [c.args[3] for c in once.call_args_list], solve

    def test_clearance_cookies_are_kept_for_the_host(self):
        result, via_solver, solve = self.fetch([self.BLOCKED, self.PAGE])

        self.assertEqual("<html></html>", result.markup)
        self.assertTrue(result.blocked)
        self.assertEqual([False, False], via_solver)
        solve.assert_called_once()
        self.assertEqual("Solver/1.0", custom_source._host_session(self.URL).user_agent)

    def test_page_is_rendered_by_the_solver_when_cookies_do_not_pass(self):
        result, via_solver, _ = self.fetch([self.BLOCKED, self.BLOCKED, self.PAGE])
        self.assertEqual("<html></html>", result.markup)
        self.assertEqual([False, False, True], via_solver)

    def test_failed_clearance_falls_back_to_the_solver(self):
        result, via_solver, _ = self.fetch([self.BLOCKED, self.PAGE], clearance=False)
        self.assertEqual([False, True], via_solver)

    def test_security_check_without_flaresolverr_is_reported(self):
        result, via_solver, solve = self.fetch([self.BLOCKED], solver=False)
        self.assertEqual(custom_source.BLOCKED_ERROR, result.error)
        self.assertTrue(result.blocked)
        solve.assert_not_called()


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.dbfile = os.path.join(self.tmpdir.name, "Quasarr.db")
        self._values, self._lock = shared_state.values, shared_state.lock
        shared_state.values = {
            "dbfile": self.dbfile,
            "configfile": os.path.join(self.tmpdir.name, "Quasarr.ini"),
        }
        shared_state.lock = None
        custom_sources._cache.update({"revision": None, "sources": {}})
        issues = patch.object(custom_sources, "mark_hostname_issue")
        self.mark = issues.start()
        self.addCleanup(issues.stop)

    def tearDown(self):
        shared_state.values, shared_state.lock = self._values, self._lock
        custom_sources._cache.update({"revision": None, "sources": {}})
        self.tmpdir.cleanup()

    def raw_rows(self):
        with sqlite3.connect(self.dbfile) as conn:
            return dict(conn.execute("SELECT key, value FROM custom_sources"))

    def test_keys_are_assigned_and_never_reused(self):
        first = custom_sources.save_definition(make_definition(key=None))
        second = custom_sources.save_definition(make_definition(key=None))
        custom_sources.delete_definition(second["key"])
        third = custom_sources.save_definition(make_definition(key=None))

        self.assertEqual(
            ["c1", "c2", "c3"], [first["key"], second["key"], third["key"]]
        )

    def test_definitions_are_encrypted_at_rest(self):
        custom_sources.save_definition(make_definition(key=None))
        self.assertNotIn(HOST, self.raw_rows()["c1"])
        self.assertEqual(HOST, custom_sources.load_definitions()["c1"]["hostname"])

    def test_invalid_definition_is_not_stored(self):
        with self.assertRaises(DefinitionError):
            custom_sources.save_definition(make_definition(key=None, hostname=""))
        self.assertNotIn("c1", self.raw_rows())

    def test_cache_reloads_only_after_a_save(self):
        custom_sources.save_definition(make_definition(key=None))
        self.assertEqual(["c1"], list(custom_sources.get_custom_sources()))

        with patch.object(custom_sources, "_read_rows") as read_rows:
            custom_sources.get_custom_sources()
        read_rows.assert_not_called()

        custom_sources.save_definition(make_definition(key=None))
        self.assertEqual(["c1", "c2"], sorted(custom_sources.get_custom_sources()))

    def test_unreadable_row_is_skipped_and_kept(self):
        custom_sources.save_definition(make_definition(key=None))
        custom_sources.save_definition(make_definition(key=None))
        with sqlite3.connect(self.dbfile) as conn:
            conn.execute("UPDATE custom_sources SET value='broken' WHERE key='c1'")
        custom_sources.bump_revision()

        self.assertEqual(["c2"], list(custom_sources.get_custom_sources()))
        self.assertEqual("broken", self.raw_rows()["c1"])
        self.assertEqual("c1", self.mark.call_args.args[0])

    def test_registries_merge_custom_sources(self):
        from quasarr.downloads.sources import get_sources as get_download_sources
        from quasarr.search.sources import get_sources

        custom_sources.save_definition(make_definition(key=None))
        self.assertIn("c1", get_sources())
        self.assertIn("mb", get_sources())
        self.assertIs(get_sources()["c1"], get_download_sources()["c1"])


if __name__ == "__main__":
    unittest.main()
