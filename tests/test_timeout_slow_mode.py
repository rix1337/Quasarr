# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import unittest

from quasarr import constants
from quasarr.constants import (
    FLARESOLVERR_REQUEST_TIMEOUT_SECONDS,
    TIMEOUT_SLOW_MODE_DEFINITIONS,
    apply_timeout_slow_mode_settings,
)
from quasarr.search.sources.templates.rm import download as rm_downloads


class TimeoutSlowModeTests(unittest.TestCase):
    def tearDown(self):
        apply_timeout_slow_mode_settings({"flaresolverr": False})

    def test_flaresolverr_timeout_definition_defaults(self):
        self.assertIn("flaresolverr", TIMEOUT_SLOW_MODE_DEFINITIONS)
        definition = TIMEOUT_SLOW_MODE_DEFINITIONS["flaresolverr"]
        self.assertEqual(definition["base_seconds"], 90)
        self.assertEqual(definition["slow_seconds"], 180)
        self.assertEqual(FLARESOLVERR_REQUEST_TIMEOUT_SECONDS, 90)

    def test_apply_timeout_slow_mode_toggles_flaresolverr_value(self):
        # Enable slow mode
        resolved = apply_timeout_slow_mode_settings({"flaresolverr": True})
        self.assertEqual(resolved["FLARESOLVERR_REQUEST_TIMEOUT_SECONDS"], 180)
        self.assertEqual(constants.FLARESOLVERR_REQUEST_TIMEOUT_SECONDS, 180)
        self.assertEqual(rm_downloads.FLARESOLVERR_REQUEST_TIMEOUT_SECONDS, 180)

        # Disable slow mode
        resolved = apply_timeout_slow_mode_settings({"flaresolverr": False})
        self.assertEqual(resolved["FLARESOLVERR_REQUEST_TIMEOUT_SECONDS"], 90)
        self.assertEqual(constants.FLARESOLVERR_REQUEST_TIMEOUT_SECONDS, 90)
        self.assertEqual(rm_downloads.FLARESOLVERR_REQUEST_TIMEOUT_SECONDS, 90)
