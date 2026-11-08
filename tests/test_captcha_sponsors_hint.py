# -*- coding: utf-8 -*-

import json
import tempfile
import threading
import unittest
from base64 import urlsafe_b64encode
from datetime import date, timedelta
from wsgiref.util import setup_testing_defaults

from bottle import Bottle

from quasarr.providers import shared_state
from quasarr.storage.config import Config
from quasarr.storage.sqlite_database import DataBase

PACKAGE = "Quasarr_movies_" + "b" * 32


class SponsorsHintTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        values, lock = shared_state.values, shared_state.lock
        self.addCleanup(lambda: setattr(shared_state, "values", values))
        self.addCleanup(lambda: setattr(shared_state, "lock", lock))
        shared_state.lock = threading.Lock()
        shared_state.values = {}
        shared_state.set_files(folder.name)
        shared_state.values.update(
            {"config": Config, "database": DataBase, "user_agent": "test-agent"}
        )
        links = [["https://release.invalid/page", "he"]]
        DataBase("protected").update_store(
            PACKAGE,
            json.dumps({"title": "Synthetic.Title", "links": links, "password": ""}),
        )
        self.payload = urlsafe_b64encode(
            json.dumps(
                {
                    "package_id": PACKAGE,
                    "title": "Synthetic.Title",
                    "password": "",
                    "links": links,
                }
            ).encode()
        ).decode()
        from quasarr.api.captcha import setup_captcha_routes

        self.app = Bottle()
        setup_captcha_routes(self.app)

    def solved(self, today, earlier):
        stats = DataBase("statistics")
        stats.update_store(f"day:{date.today().isoformat()}:manual", str(today))
        before = (date.today() - timedelta(days=3)).isoformat()
        stats.update_store(f"day:{before}:manual", str(earlier))

    def page(self):
        environ = {}
        setup_testing_defaults(environ)
        environ.update(
            {"PATH_INFO": "/captcha/he", "QUERY_STRING": f"data={self.payload}"}
        )
        return b"".join(self.app(environ, lambda *args: None)).decode()

    def test_hint_shows_above_the_daily_or_monthly_count(self):
        self.solved(11, 0)
        page = self.page()
        self.assertIn('id="sponsors-hint"', page)
        # 11 CAPTCHAs at 30 seconds each
        self.assertIn("roughly 6 minutes", page)
        self.assertIn("#sponsorshelper", page)

        self.solved(2, 49)
        self.assertIn('id="sponsors-hint"', self.page())

    def test_no_hint_below_both_counts_or_with_sponsorshelper_running(self):
        self.solved(10, 40)
        self.assertNotIn('id="sponsors-hint"', self.page())

        self.solved(20, 100)
        shared_state.values["helper_active"] = True
        self.assertNotIn('id="sponsors-hint"', self.page())


if __name__ == "__main__":
    unittest.main()
