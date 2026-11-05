# -*- coding: utf-8 -*-

import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from quasarr.search.sources import templates
from quasarr.search.sources.helpers import custom_source
from quasarr.search.sources.helpers.custom_source import (
    CustomSource,
    DefinitionError,
    FetchResult,
)
from quasarr.search.sources.helpers.custom_suggest import (
    detect_templates,
    export_template,
)

HOST = "source.invalid"
LISTING = {"item": "article", "title": {"selector": "a"}, "link": {"selector": "a"}}


def page(count=4):
    return "".join(
        f'<article><a href="/r/{i}">Movie.{i}.2026.1080p.WEB.x264-GRP</a></article>'
        for i in range(count)
    )


def bundled(**overrides):
    definition = {
        "key": "zz",
        "name": "Bundled",
        "language": "de",
        "feeds": [{"category": 2000, "url": "https://{host}/movies/"}],
        "list": LISTING,
        **overrides,
    }
    return definition


def state(hostname=HOST):
    return SimpleNamespace(
        values={
            "user_agent": "UA/1.0",
            "config": lambda section: (
                {"zz": hostname} if section == "Hostnames" else {}
            ),
        }
    )


class BundledSourceTests(unittest.TestCase):
    def test_hostname_comes_from_the_hostname_settings(self):
        source = CustomSource(bundled(), bundled=True)
        with patch("quasarr.providers.shared_state.values", state().values):
            self.assertEqual(HOST, source.hostname)
        self.assertIsNone(source.custom_hostname)

    def test_user_definitions_cannot_link_code(self):
        with self.assertRaises(DefinitionError):
            CustomSource({**bundled(key="c1", hostname=HOST), "hooks": {"feed": "x"}})

    def test_capabilities_override_the_defaults(self):
        source = CustomSource(
            bundled(
                capabilities={"requires_login": True, "supports_date_numbering": True}
            ),
            bundled=True,
        )
        self.assertTrue(source.requires_login)
        self.assertTrue(source.supports_date_numbering)
        self.assertFalse(source.supports_absolute_numbering)

    def test_hooks_replace_their_step(self):
        calls = []

        def search(
            source, shared_state, start_time, category, query, season, episode, **kwargs
        ):
            calls.append((query, season, episode, kwargs))
            return ["hooked"]

        source = CustomSource(
            bundled(hooks={"search": "search"}, categories=[5000]),
            bundled=True,
            hooks={"search": search},
        )
        result = source.search(None, 0, 5000, "tt1234567", 1, 2, episode_date="d")
        self.assertEqual(["hooked"], result)
        self.assertEqual([("tt1234567", 1, 2, {"episode_date": "d"})], calls)
        self.assertIn(5000, source.supported_categories)

    def test_missing_hook_function_is_an_error(self):
        with self.assertRaises(DefinitionError):
            CustomSource(bundled(hooks={"feed": "feed"}), bundled=True, hooks={})

    def test_template_modules_load_with_their_hooks(self):
        module = types.ModuleType("zz")
        module.TEMPLATE = bundled(hooks={"download": "download"})
        module.download = lambda source, *args: {"links": [["u", "m"]]}
        with patch("importlib.import_module", return_value=module):
            source = templates._load("zz")
        self.assertEqual(
            {"links": [["u", "m"]]}, source.get_download_links(None, "", [], "", "")
        )


class RegistryTests(unittest.TestCase):
    def test_templates_replace_modules_of_the_same_key(self):
        from quasarr.search import sources as search_sources

        template = CustomSource(bundled(key="mb"), bundled=True)
        with (
            patch.object(templates, "get_templates", return_value={"mb": template}),
            patch.object(search_sources, "_sources", {}),
            patch("quasarr.storage.custom_sources.get_custom_sources", return_value={}),
        ):
            sources = search_sources.get_sources()
        self.assertIs(template, sources["mb"])
        self.assertIn("rm", sources)


class DetectionTests(unittest.TestCase):
    def test_template_reading_the_page_is_reported(self):
        match = CustomSource(bundled(), bundled=True)
        other = CustomSource(
            bundled(key="yy", list={**LISTING, "item": "li.release"}), bundled=True
        )
        with patch.object(
            templates, "get_templates", return_value={"zz": match, "yy": other}
        ):
            found = detect_templates(None, page(), f"https://{HOST}/", HOST, fetch=None)
        self.assertEqual(["ZZ"], [m["key"] for m in found])


class ExportTests(unittest.TestCase):
    def definition(self):
        return {
            "key": "c1",
            "name": "Shared",
            "hostname": HOST,
            "language": "de",
            "enabled": True,
            "schema": 1,
            "feeds": [{"category": 2000, "url": "https://{host}/movies/"}],
            "search": {
                "mode": "title",
                "url": "https://{host}/?s={q}",
                "categories": [2000],
            },
            "list": LISTING,
        }

    def export(self, pages):
        def fetch(_state, url, *args, **kwargs):
            return FetchResult(pages.get(url), None if url in pages else "missing", 200)

        with patch.object(custom_source, "fetch_markup", side_effect=fetch):
            return export_template(state(), self.definition())

    def test_export_needs_a_working_search(self):
        result = self.export({f"https://{HOST}/movies/": page()})
        self.assertFalse(result["success"])
        self.assertIn("Search", result["problems"][0])

    def test_export_strips_the_hostname(self):
        hit = '<article><a href="/r/0">Movie.0.2026.1080p.WEB.x264-GRP</a></article>'
        result = self.export(
            {f"https://{HOST}/movies/": page(), f"https://{HOST}/?s=Movie": hit}
        )
        self.assertTrue(result["success"], result)
        self.assertNotIn(HOST, result["module"])
        self.assertNotIn("'key'", result["module"])
        namespace = {}
        exec(result["module"], namespace)
        self.assertEqual(
            "https://{host}/movies/", namespace["TEMPLATE"]["feeds"][0]["url"]
        )


if __name__ == "__main__":
    unittest.main()
