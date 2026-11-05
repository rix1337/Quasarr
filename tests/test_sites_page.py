# -*- coding: utf-8 -*-

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from quasarr.search.sources.helpers.custom_source import FetchResult
from quasarr.storage.setup import sites


class _Config:
    store = {}

    def __init__(self, section):
        self.section = section

    def get(self, key):
        return self.store.get((self.section, key))

    def save(self, key, value):
        self.store[(self.section, key)] = value


def _template():
    return SimpleNamespace(
        language="de",
        supported_categories=[2000],
        requires_login=False,
        requires_account=False,
        invite_only=False,
        requires_flaresolverr=False,
    )


class ParseHostnameListTests(unittest.TestCase):
    def test_reads_lines_urls_and_community_pairs(self):
        entries = sites.parse_hostname_list(
            "https://www.one.invalid/path\n two.invalid, three.invalid\nab = four.invalid\none.invalid"
        )

        self.assertEqual(
            [
                {"hostname": "one.invalid", "key": None},
                {"hostname": "two.invalid", "key": None},
                {"hostname": "three.invalid", "key": None},
                {"hostname": "four.invalid", "key": "ab"},
            ],
            entries,
        )

    def test_caps_the_number_of_hostnames(self):
        text = "\n".join(f"site{i}.invalid" for i in range(sites.MAX_HOSTNAMES + 5))
        self.assertEqual(sites.MAX_HOSTNAMES, len(sites.parse_hostname_list(text)))


class CheckHostnameTests(unittest.TestCase):
    def setUp(self):
        _Config.store = {}
        templates = {"ab": _template(), "xy": _template()}
        patches = [
            patch.object(sites, "Config", _Config),
            patch(
                "quasarr.search.sources.templates.get_templates",
                return_value=templates,
            ),
            patch("quasarr.storage.custom_sources.load_definitions", return_value={}),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def _check(self, hostname, detected=(), named_key=None):
        fetch = lambda *_args, **_kwargs: FetchResult("<html></html>", None, 200)  # noqa: E731
        with patch(
            "quasarr.search.sources.helpers.custom_suggest.detect_templates",
            return_value=list(detected),
        ):
            return sites.check_hostname(None, hostname, named_key, fetch=fetch)

    def test_blocks_link_protection_services(self):
        result = self._check("filecrypt.invalid")
        self.assertIn("blocked", result)
        self.assertEqual([], result["verified"])

    def test_reports_a_hostname_that_is_already_added(self):
        _Config.store[("Hostnames", "ab")] = "www.ab-site.invalid"
        self.assertEqual("AB", self._check("ab-site.invalid")["added_as"])

    def test_verified_template_comes_first_and_letter_fits_follow(self):
        result = self._check("abxy.invalid", detected=[{"key": "XY", "rows": 12}])

        self.assertEqual(
            [("XY", 12)], [(c["key"], c["rows"]) for c in result["verified"]]
        )
        self.assertEqual(["AB"], [c["key"] for c in result["possible"]])

    def test_unreachable_site_gets_a_short_reason(self):
        fetch = lambda *_args, **_kwargs: FetchResult(  # noqa: E731
            None, "Failed to resolve 'site.invalid'", None
        )
        with patch(
            "quasarr.search.sources.helpers.custom_suggest.detect_templates",
            return_value=[],
        ):
            result = sites.check_hostname(None, "site.invalid", fetch=fetch)
        self.assertEqual("the name does not resolve", result["unreachable"])

    def test_named_key_must_fit_the_hostname(self):
        self.assertEqual("AB", self._check("ab.invalid", named_key="ab")["named"])
        self.assertIn("named_error", self._check("ab.invalid", named_key="xy"))


class AddBuiltinSiteTests(unittest.TestCase):
    def setUp(self):
        _Config.store = {}

    def _add(self, key, hostname):
        with (
            patch.object(sites, "Config", _Config),
            patch(
                "quasarr.search.sources.templates.get_templates",
                return_value={"ab": _template()},
            ),
            patch.object(sites, "clear_hostname_issue"),
            patch.object(sites, "record_configured_hostnames"),
        ):
            return sites.add_builtin_site(key, hostname)

    def test_saves_a_fitting_hostname(self):
        self.assertIsNone(self._add("AB", "https://ab.invalid/"))
        self.assertEqual("ab.invalid", _Config.store[("Hostnames", "ab")])

    def test_refuses_a_hostname_outside_the_letter_rule(self):
        self.assertIn("does not contain", self._add("ab", "other.invalid"))
        self.assertNotIn(("Hostnames", "ab"), _Config.store)

    def test_refuses_an_unknown_site(self):
        self.assertEqual("Unknown built-in site", self._add("zz", "zz.invalid"))


if __name__ == "__main__":
    unittest.main()
