# -*- coding: utf-8 -*-

import os
import unittest
from unittest.mock import patch

from quasarr.providers.utils import _quasarr_destination_folder


class DestinationFolderTests(unittest.TestCase):
    def _folder(self, package_id="Quasarr_movies_deadbeef", **env):
        # Isolate the two variables this function reads so the host environment
        # cannot leak into the assertions; patch.dict restores os.environ after.
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DOWNLOAD_FOLDER", None)
            os.environ.pop("CATEGORY_SUBFOLDERS", None)
            os.environ.update(env)
            return _quasarr_destination_folder(package_id)

    def test_default_is_unchanged(self):
        self.assertEqual("Quasarr/<jd:packagename>", self._folder())

    def test_empty_base_drops_the_quasarr_level(self):
        self.assertEqual("<jd:packagename>", self._folder(DOWNLOAD_FOLDER=""))

    def test_absolute_base_is_preserved_and_trimmed(self):
        self.assertEqual(
            "/data/dl/<jd:packagename>",
            self._folder(DOWNLOAD_FOLDER="/data/dl/"),  # trailing slash trimmed
        )

    def test_category_subfolder_when_enabled(self):
        with patch(
            "quasarr.storage.categories.get_download_category_from_package_id",
            return_value="movies",
        ):
            self.assertEqual(
                "Quasarr/movies/<jd:packagename>",
                self._folder(CATEGORY_SUBFOLDERS="true"),
            )

    def test_category_and_base_are_independent(self):
        with patch(
            "quasarr.storage.categories.get_download_category_from_package_id",
            return_value="tv",
        ):
            self.assertEqual(
                "tv/<jd:packagename>",
                self._folder(DOWNLOAD_FOLDER="", CATEGORY_SUBFOLDERS="true"),
            )

    def test_non_quasarr_package_stays_base_only(self):
        with patch(
            "quasarr.storage.categories.get_download_category_from_package_id",
            return_value="not_quasarr",
        ):
            self.assertEqual(
                "Quasarr/<jd:packagename>",
                self._folder(package_id="external-id", CATEGORY_SUBFOLDERS="true"),
            )

    def test_category_flag_off_never_resolves_category(self):
        with patch(
            "quasarr.storage.categories.get_download_category_from_package_id",
        ) as resolver:
            self.assertEqual("Quasarr/<jd:packagename>", self._folder())
            resolver.assert_not_called()


if __name__ == "__main__":
    unittest.main()
