# -*- coding: utf-8 -*-

import json
import unittest
from unittest.mock import patch

from quasarr.api.captcha.custom_userscript import custom_user_js
from quasarr.search.sources.helpers import custom_source
from quasarr.search.sources.helpers.custom_source import (
    USERSCRIPT_MIRROR,
    CustomSource,
    DefinitionError,
)
from quasarr.search.sources.helpers.custom_suggest import import_template

DEFINITION = {
    "name": "Example",
    "language": "de",
    "feeds": [{"category": 2000, "url": "https://{host}/new/"}],
    "list": {"item": "article", "title": {"selector": "h2"}, "link": {"selector": "a"}},
}


class ImportTemplateTests(unittest.TestCase):
    def test_reads_json_and_exported_modules_without_their_identity(self):
        shared = {**DEFINITION, "key": "c4", "hostname": "site.invalid"}
        self.assertEqual(DEFINITION, import_template(json.dumps(shared)))
        module = "# exported\nTEMPLATE = " + repr(DEFINITION) + "\n"
        self.assertEqual(DEFINITION, import_template(module))

    def test_refuses_code_hooks_and_invalid_templates(self):
        for text in (
            "TEMPLATE = __import__('os').system('true')",
            json.dumps({**DEFINITION, "hooks": {"feed": "run"}}),
            json.dumps({**DEFINITION, "list": {"item": ""}}),
            "print('no template')",
        ):
            with self.assertRaises(DefinitionError, msg=text):
                import_template(text)


class UserscriptDownloadTests(unittest.TestCase):
    def source(self):
        return CustomSource(
            {
                **DEFINITION,
                "key": "c4",
                "hostname": "site.invalid",
                "download": {"userscript": True},
            }
        )

    def test_release_pages_go_to_the_users_own_userscript_unfetched(self):
        with patch.object(custom_source, "fetch_markup") as fetch:
            result = self.source().get_download_links(
                None, "https://site.invalid/release/1", [], "Title", ""
            )
        fetch.assert_not_called()
        self.assertEqual(
            {
                "links": [["https://site.invalid/release/1", USERSCRIPT_MIRROR]],
                "protected": True,
            },
            result,
        )

    def test_template_matches_the_users_sites_and_never_updates(self):
        script = custom_user_js(["site.invalid"])
        self.assertIn("// @match        *://site.invalid/*", script)
        self.assertNotIn("@updateURL", script)
        self.assertNotIn("@downloadURL", script)
        self.assertIn("do not modify", script)
        self.assertIn("*://example.invalid/*", custom_user_js([]))


if __name__ == "__main__":
    unittest.main()
