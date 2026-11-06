# -*- coding: utf-8 -*-

import os
import tempfile
import unittest
import unittest.mock

from quasarr.providers import shared_state
from quasarr.storage import config
from quasarr.storage.config import Config
from quasarr.storage.sqlite_database import DataBase


class ConfigSecretDecryptionTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.dbfile = os.path.join(self.tmpdir.name, "Quasarr.db")
        self.configfile = os.path.join(self.tmpdir.name, "Quasarr.ini")
        shared_state.values = {"dbfile": self.dbfile, "configfile": self.configfile}
        shared_state.lock = None

    def tearDown(self):
        self.tmpdir.cleanup()

    def _drop_encryption_key(self):
        """Simulate a Quasarr.ini restored without its matching Quasarr.db."""
        secrets = DataBase("secrets")
        secrets.delete("key")
        secrets.delete("iv")
        secrets._conn.close()
        # a restored ini meets a freshly started Quasarr, which has no key cached
        config._encryption_params.clear()

    def test_secret_roundtrips_with_its_own_database(self):
        Config("API").save("key", "synthetic-api-key")

        self.assertEqual("synthetic-api-key", Config("API").get("key"))

    def test_undecryptable_secret_reports_unset_instead_of_raising(self):
        # Regression: the AES key lives in Quasarr.db, so an ini restored on its
        # own used to raise UnicodeDecodeError out of get() and, under the Docker
        # restart-loop ENTRYPOINT, crash-loop the container with a raw traceback.
        Config("API").save("key", "synthetic-api-key")
        self._drop_encryption_key()

        self.assertEqual("", Config("API").get("key"))

    def test_undecryptable_secret_keeps_the_stored_value(self):
        # Reporting the value as unset must not destroy it: restoring the
        # matching Quasarr.db has to bring the credential back.
        Config("API").save("key", "synthetic-api-key")
        with open(self.configfile, encoding="utf-8") as f:
            before = f.read()
        self._drop_encryption_key()

        Config("API").get("key")

        with open(self.configfile, encoding="utf-8") as f:
            self.assertEqual(before, f.read())

    def test_plain_value_still_reads_and_is_encrypted_on_access(self):
        Config("API")  # write defaults
        with open(self.configfile, encoding="utf-8") as f:
            content = f.read()
        with open(self.configfile, "w", encoding="utf-8") as f:
            f.write(content.replace("key = ", "key = plain-value"))

        self.assertEqual("plain-value", Config("API").get("key"))
        with open(self.configfile, encoding="utf-8") as f:
            self.assertIn("secret|", f.read())


class ConfigCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.configfile = os.path.join(self.tmpdir.name, "Quasarr.ini")
        shared_state.values = {
            "dbfile": os.path.join(self.tmpdir.name, "Quasarr.db"),
            "configfile": self.configfile,
        }
        shared_state.lock = None
        Config("Settings").save("hostnames_url", "")
        Config("Settings").get("hostnames_url")  # the latest file is now cached

    def test_reads_the_file_only_after_it_changed(self):
        reads = []
        original = config.configparser.RawConfigParser.read

        def counted(parser, *args, **kwargs):
            reads.append(1)
            return original(parser, *args, **kwargs)

        with unittest.mock.patch.object(
            config.configparser.RawConfigParser, "read", counted
        ):
            for _ in range(5):
                Config("Settings").get("hostnames_url")
            self.assertEqual([], reads)
            # another process rewrites the file
            Config("Settings").save("hostnames_url", "https://lists.invalid/a")
            reads.clear()
            self.assertEqual(
                "https://lists.invalid/a", Config("Settings").get("hostnames_url")
            )
            Config("Settings").get("hostnames_url")
        self.assertEqual(1, len(reads))


if __name__ == "__main__":
    unittest.main()
