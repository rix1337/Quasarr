# -*- coding: utf-8 -*-

import io
import json
import re
import tempfile
import threading
import unittest
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults

import requests
from bottle import Bottle

import quasarr.downloads as downloads
from quasarr.providers import shared_state
from quasarr.storage.config import Config
from quasarr.storage.sqlite_database import DataBase

TITLE = "Synthetic.Movie.2026.1080p.WEB.x264-GRP"
PACKAGE = "Quasarr_movies_" + "a" * 32


class BypassSubmitTests(unittest.TestCase):
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
        DataBase("protected").update_store(
            PACKAGE,
            json.dumps(
                {
                    "title": TITLE,
                    "links": [["https://crypter.invalid/Container/X.html", "x"]],
                    "password": "",
                }
            ),
        )
        from quasarr.api.captcha import setup_captcha_routes

        self.app = Bottle()
        setup_captcha_routes(self.app)

    def submit(self):
        prepared = requests.Request(
            "POST",
            "http://q.invalid/captcha/bypass-submit",
            files={
                "package_id": (None, PACKAGE),
                "title": (None, TITLE),
                "password": (None, ""),
                "links": (None, "https://hoster.invalid/file/1"),
            },
        ).prepare()
        environ = {}
        setup_testing_defaults(environ)
        environ.update(
            {
                "REQUEST_METHOD": "POST",
                "PATH_INFO": "/captcha/bypass-submit",
                "CONTENT_TYPE": prepared.headers["Content-Type"],
                "CONTENT_LENGTH": str(len(prepared.body)),
                "wsgi.input": io.BytesIO(prepared.body),
            }
        )
        status = {}
        body = b"".join(
            self.app(environ, lambda code, headers, exc=None: status.update(code=code))
        ).decode()
        text = re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", "", body)
        return status["code"], " ".join(re.sub(r"<[^>]+>", " ", text).split())

    def test_second_submit_explains_the_package_is_already_solved(self):
        with patch.object(downloads, "download_package", return_value=True):
            first_status, first = self.submit()
            second_status, second = self.submit()

        self.assertEqual("200 OK", first_status)
        self.assertIn("submitted to JDownloader", first)
        # an empty "Error:" used to hide this
        self.assertEqual("404 Not Found", second_status)
        self.assertIn("already solved", second)


if __name__ == "__main__":
    unittest.main()
