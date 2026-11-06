# -*- coding: utf-8 -*-

import unittest

from quasarr.providers.log import _contexts_to_str


def label(module):
    return _contexts_to_str(module.split("."))


class TemplateLogLabelTests(unittest.TestCase):
    def test_template_package_modules_log_like_their_site_modules(self):
        self.assertEqual(
            label("quasarr.search.sources.xy"),
            label("quasarr.search.sources.templates.xy.search"),
        )
        self.assertEqual(
            label("quasarr.downloads.sources.xy"),
            label("quasarr.search.sources.templates.xy.download"),
        )
        self.assertEqual(("🔍🧲", "XY"), label("quasarr.search.sources.templates.xy"))

    def test_other_modules_keep_their_labels(self):
        self.assertEqual(("🔍🧲", "XY"), label("quasarr.search.sources.xy"))
        self.assertEqual(("🌌", ""), label("quasarr"))
        self.assertEqual(("🔌🧰", ""), label("quasarr.providers.utils"))


if __name__ == "__main__":
    unittest.main()
