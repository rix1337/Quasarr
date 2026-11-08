# -*- coding: utf-8 -*-

import os
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from quasarr.providers import shared_state
from quasarr.search.sources import templates
from quasarr.search.sources.helpers.custom_source import (
    DefinitionError,
    _compile_urls,
)
from quasarr.storage import template_overrides
from quasarr.storage.setup import site_editor, sites


class UrlTemplateTests(unittest.TestCase):
    def test_accepts_site_and_api_subdomain_addresses(self):
        urls = _compile_urls(
            {
                "release": "https://{host}/release/{slug}",
                "api": "https://api.{host}/start/d/{uid}",
            }
        )
        self.assertEqual("https://api.{host}/start/d/{uid}", urls["api"])

    def test_refuses_addresses_off_the_site(self):
        for template in (
            "https://other.invalid/{host}",
            "ftp://{host}/x",
            "https://{host}/{0}",
            "https://{host}/{a.b}",
        ):
            with self.assertRaises(DefinitionError, msg=template):
                _compile_urls({"x": template})

    def test_site_url_fills_the_configured_host(self):
        state = MagicMock()
        state.values = {"config": lambda _section: {"nx": "site.invalid"}}
        self.assertEqual(
            "https://site.invalid/release/abc",
            templates.site_url(state, "nx", "release", slug="abc"),
        )


class OverrideTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        values = dict(shared_state.values)
        lock = shared_state.lock
        self.addCleanup(lambda: setattr(shared_state, "values", values))
        self.addCleanup(lambda: setattr(shared_state, "lock", lock))
        shared_state.values = {}
        shared_state.lock = threading.Lock()
        shared_state.values["dbfile"] = os.path.join(self.folder.name, "Quasarr.db")
        templates._state.update(revision=None, templates={}, modified=set())
        self.addCleanup(
            templates._state.update, revision=None, templates={}, modified=set()
        )

    def test_changes_lay_over_the_shipped_template_and_reset_restores_it(self):
        shipped = templates.shipped_definition("nx")["urls"]["release"]
        changed = {"urls": {**templates.shipped_definition("nx")["urls"]}}
        changed["urls"]["release"] = "https://{host}/r/{slug}"

        template_overrides.save_override("nx", changed)

        self.assertTrue(templates.is_modified("nx"))
        source = templates.get_templates()["nx"]
        self.assertEqual("https://{host}/r/{slug}", source.spec["urls"]["release"])
        # the code hooks always stay the shipped ones
        self.assertIn("search", source.hooks)

        self.assertTrue(template_overrides.delete_override("nx"))
        self.assertFalse(templates.is_modified("nx"))
        self.assertEqual(
            shipped, templates.get_templates()["nx"].spec["urls"]["release"]
        )

    def test_refuses_parts_that_cannot_change_and_invalid_templates(self):
        with self.assertRaises(ValueError):
            template_overrides.save_override("mb", {"hooks": {}})
        with self.assertRaises(DefinitionError):
            template_overrides.save_override("mb", {"list": {"item": ""}})
        with self.assertRaises(ValueError):
            template_overrides.save_override("zz", {})
        self.assertEqual({}, template_overrides.load_overrides())

    def test_only_parts_that_differ_count_as_changes(self):
        shipped = templates.shipped_definition("mb")
        unchanged = {"feeds": shipped["feeds"], "list": shipped["list"]}
        self.assertEqual({}, site_editor._changed_parts("mb", unchanged))
        moved = {**unchanged, "feeds": [{"category": 2000, "url": "https://{host}/x/"}]}
        self.assertEqual(["feeds"], list(site_editor._changed_parts("mb", moved)))

    def test_removing_a_changed_site_resets_it_and_keeps_the_address(self):
        template_overrides.save_override("mb", {"flaresolverr": True})
        with patch.object(sites, "Config") as config:
            self.assertTrue(sites.remove_site("mb"))
            config.return_value.save.assert_not_called()
        self.assertFalse(templates.is_modified("mb"))


if __name__ == "__main__":
    unittest.main()
