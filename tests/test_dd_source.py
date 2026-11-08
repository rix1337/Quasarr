# -*- coding: utf-8 -*-

import time
import unittest
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, patch

from quasarr.constants import SEARCH_CAT_SHOWS
from quasarr.providers.sessions.dd import create_and_persist_session
from quasarr.search.sources.templates.dd.download import Source as DownloadSource
from quasarr.search.sources.templates.dd.search import Source as SearchSource


class FakeResponse:
    def __init__(self, json_data=None, status_code=200):
        self._json = json_data if json_data is not None else {}
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


class FakeDDConfigSection:
    """Mimics the Config callable for the DD section: dict get + save bookkeeping."""

    def __init__(self, data):
        self.data = dict(data)
        self.saved = []

    def get(self, key):
        return self.data.get(key)

    def save(self, key, value):
        self.saved.append((key, value))


def make_shared_state(host="dd.invalid", **dd):
    dd_values = dd or {"user": "unituser", "password": "unitpass"}
    dd_section = FakeDDConfigSection(dd_values)
    sessions_db = MagicMock()

    def config(section):
        if section == "Hostnames":
            return {"dd": host}
        if section == "DD":
            return dd_section
        return {}

    def database(table):
        return sessions_db

    return SimpleNamespace(
        values={
            "config": config,
            "user_agent": "UnitTestAgent/1.0",
            "database": database,
        }
    )


class DdSessionTests(unittest.TestCase):
    def test_login_persists_session_and_sends_csrf(self):
        state = make_shared_state()
        csrf = FakeResponse({"csrfToken": "tok123"})
        login = FakeResponse({"user": {"id": 1}})
        session = MagicMock()
        session.get.return_value = csrf
        session.post.return_value = login

        with (
            patch(
                "quasarr.providers.sessions.dd.requests.Session", return_value=session
            ),
            patch(
                "quasarr.providers.sessions.dd.pickle.dumps", return_value=b"serialized"
            ),
            patch("quasarr.providers.sessions.dd.clear_hostname_issue") as clear,
            patch("quasarr.providers.sessions.dd.mark_hostname_issue"),
        ):
            result = create_and_persist_session(state)

        self.assertIs(result, session)
        session.get.assert_called_once_with(
            "https://dd.invalid/api/csrf-token",
            headers={"User-Agent": "UnitTestAgent/1.0"},
            timeout=ANY,
        )
        self.assertEqual(
            session.post.call_args.kwargs["json"],
            {"login": "unituser", "password": "unitpass"},
        )
        self.assertEqual(
            session.post.call_args.kwargs["headers"]["x-csrf-token"], "tok123"
        )
        session_db = state.values["database"]("sessions")
        session_db.update_store.assert_called_once_with("dd", ANY)
        clear.assert_called_once_with("dd")

    def test_login_rejected_blanks_credentials(self):
        state = make_shared_state()
        session = MagicMock()
        session.get.return_value = FakeResponse({"csrfToken": "tok123"})
        session.post.return_value = FakeResponse(
            {"error": {"code": "INVALID_CREDENTIALS"}}, status_code=401
        )

        with (
            patch(
                "quasarr.providers.sessions.dd.requests.Session", return_value=session
            ),
            patch("quasarr.providers.sessions.dd.clear_hostname_issue"),
            patch("quasarr.providers.sessions.dd.mark_hostname_issue") as mark,
        ):
            result = create_and_persist_session(state)

        self.assertIsNone(result)
        self.assertEqual(
            [("user", ""), ("password", "")], state.values["config"]("DD").saved
        )
        mark.assert_called_once_with("dd", "session", "Login rejected")

    def test_login_missing_csrf_token_fails_cleanly(self):
        state = make_shared_state()
        session = MagicMock()
        session.get.return_value = FakeResponse({})

        with (
            patch(
                "quasarr.providers.sessions.dd.requests.Session", return_value=session
            ),
            patch("quasarr.providers.sessions.dd.clear_hostname_issue"),
            patch("quasarr.providers.sessions.dd.mark_hostname_issue") as mark,
        ):
            result = create_and_persist_session(state)

        self.assertIsNone(result)
        self.assertEqual([], state.values["config"]("DD").saved)
        session.post.assert_not_called()
        mark.assert_called_once_with("dd", "session", "Missing CSRF token")


class DdSearchTests(unittest.TestCase):
    def test_search_maps_new_release_fields(self):
        state = make_shared_state()
        item = {
            "releaseName": "Synthetic.Show.S01E01.1080p.WEB.h264-GRP",
            "size": 1048576,
            "when": 0,
        }
        session = MagicMock()
        session.get.return_value = FakeResponse({"results": [item], "nextCursor": None})

        with (
            patch(
                "quasarr.search.sources.templates.dd.search.retrieve_and_validate_session",
                return_value=session,
            ),
            patch(
                "quasarr.search.sources.templates.dd.search.generate_download_link",
                return_value="dl",
            ),
            patch("quasarr.search.sources.templates.dd.search.clear_hostname_issue"),
        ):
            releases = SearchSource().search(
                state,
                time.time(),
                SEARCH_CAT_SHOWS,
                "Synthetic Show",
                season=1,
                episode=1,
            )

        self.assertEqual(1, len(releases))
        details = releases[0]["details"]
        self.assertEqual("Synthetic.Show.S01E01.1080p.WEB.h264-GRP", details["title"])
        self.assertEqual(1048576, details["size"])
        self.assertEqual("Thu, 01 Jan 1970 00:00:00 +0000", details["date"])
        self.assertEqual("https://dd.invalid/", details["source"])
        self.assertEqual("dd", details["hostname"])
        self.assertEqual("protected", releases[0]["type"])


class DdDownloadTests(unittest.TestCase):
    def test_download_extracts_matching_release_links(self):
        state = make_shared_state()
        item = {
            "releaseName": "Synthetic.Show.S01E01.1080p.WEB.h264-GRP",
            "fake": False,
            "links": [
                {"url": "https://ironfiles.invalid/file/1", "hostname": "ironfiles"},
                {
                    "url": "https://rapidgator.invalid/file/2.html",
                    "hostname": "rapidgator",
                },
            ],
        }
        session = MagicMock()
        session.get.return_value = FakeResponse({"results": [item], "nextCursor": None})

        with patch(
            "quasarr.search.sources.templates.dd.download.retrieve_and_validate_session",
            return_value=session,
        ):
            result = DownloadSource().get_download_links(
                state,
                "https://dd.invalid/",
                [],
                "Synthetic.Show.S01E01.1080p.WEB.h264-GRP",
                "dd.invalid",
            )

        self.assertEqual(
            {
                "links": [
                    ["https://ironfiles.invalid/file/1", "ironfiles"],
                    ["https://rapidgator.invalid/file/2.html", "rapidgator"],
                ]
            },
            result,
        )
        self.assertEqual(
            "https://dd.invalid/api/releases/search",
            session.get.call_args[0][0],
        )

    def test_download_honors_mirror_whitelist(self):
        state = make_shared_state()
        item = {
            "releaseName": "Synthetic.Show.S01E01.1080p.WEB.h264-GRP",
            "fake": False,
            "links": [
                {"url": "https://ironfiles.invalid/file/1", "hostname": "ironfiles"},
                {
                    "url": "https://rapidgator.invalid/file/2.html",
                    "hostname": "rapidgator",
                },
            ],
        }
        session = MagicMock()
        session.get.return_value = FakeResponse({"results": [item], "nextCursor": None})

        with patch(
            "quasarr.search.sources.templates.dd.download.retrieve_and_validate_session",
            return_value=session,
        ):
            result = DownloadSource().get_download_links(
                state,
                "https://dd.invalid/",
                ["rapidgator"],
                "Synthetic.Show.S01E01.1080p.WEB.h264-GRP",
                "dd.invalid",
            )

        self.assertEqual(
            {"links": [["https://rapidgator.invalid/file/2.html", "rapidgator"]]},
            result,
        )

    def test_download_fake_release_invalidates_session(self):
        state = make_shared_state()
        item = {"releaseName": "Synthetic.Show.S01E01", "fake": True, "links": []}
        session = MagicMock()
        session.get.return_value = FakeResponse({"results": [item], "nextCursor": None})

        with (
            patch(
                "quasarr.search.sources.templates.dd.download.retrieve_and_validate_session",
                return_value=session,
            ),
            patch(
                "quasarr.search.sources.templates.dd.download.create_and_persist_session"
            ) as recreate,
        ):
            result = DownloadSource().get_download_links(
                state,
                "https://dd.invalid/",
                [],
                "Synthetic.Show.S01E01",
                "dd.invalid",
            )

        self.assertEqual({"links": []}, result)
        recreate.assert_called_once_with(state)


if __name__ == "__main__":
    unittest.main()
