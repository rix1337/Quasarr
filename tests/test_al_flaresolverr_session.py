import unittest
from unittest.mock import patch

import requests

from quasarr.providers.sessions import al as al_sessions
from quasarr.search.sources.templates.al.download import Source


class SharedState:
    def __init__(self):
        self.values = {"config": self.config}

    def config(self, section):
        if section == "FlareSolverr":
            return {"url": "http://solver.invalid/v1"}
        if section == "Hostnames":
            return {"al": "source.invalid"}
        return {}


class FlareSolverrResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class Stats:
    def increment_captcha_decryptions_automatic(self):
        pass

    def increment_failed_decryptions_automatic(self):
        pass


class AlFlareSolverrSessionTests(unittest.TestCase):
    def test_fetch_via_flaresolverr_reuses_browser_session_forwards_headers_and_updates_user_agent(
        self,
    ):
        shared_state = SharedState()
        session = requests.Session()
        payload = {
            "status": "ok",
            "solution": {
                "status": 200,
                "headers": {},
                "response": '{"code":"success","content":[]}',
                "cookies": [],
                "userAgent": "browser-agent",
            },
        }

        with (
            patch.object(al_sessions, "is_flaresolverr_available", return_value=True),
            patch.object(
                al_sessions, "retrieve_and_validate_session", return_value=session
            ),
            patch.object(al_sessions, "_persist_session_to_db"),
            patch.object(
                al_sessions.requests,
                "post",
                return_value=FlareSolverrResponse(payload),
            ) as post,
        ):
            result = al_sessions.fetch_via_flaresolverr(
                shared_state,
                "POST",
                "https://www.source.invalid/ajax/captcha",
                post_data={"response": "nocaptcha"},
                timeout=10,
                session_id="browser-session",
                request_headers={"X-Requested-With": "XMLHttpRequest"},
            )

        self.assertEqual(200, result["status_code"])
        self.assertEqual("browser-agent", session.headers["User-Agent"])
        self.assertEqual("browser-session", post.call_args.kwargs["json"]["session"])
        self.assertEqual(
            {"X-Requested-With": "XMLHttpRequest"},
            post.call_args.kwargs["json"]["headers"],
        )

    def test_al_download_reuses_flaresolverr_session_and_ajax_headers_for_captcha_flow(
        self,
    ):
        shared_state = SharedState()
        fetch_session_ids = []
        request_headers = []
        post_payloads = []
        validate_calls = []

        def fake_fetch(_shared_state, method, target_url, **kwargs):
            fetch_session_ids.append(kwargs.get("session_id"))
            request_headers.append(kwargs.get("request_headers"))
            post_data = kwargs.get("post_data") or {}
            post_payloads.append(post_data)
            if method == "GET":
                return {"status_code": 200, "text": "<html></html>", "json": None}
            # Only the "nocaptcha" start request stays on the FlareSolverr browser.
            return {
                "status_code": 200,
                "text": "{}",
                "json": {
                    "code": "error",
                    "message": ["captcha_required"],
                    "content": [],
                },
            }

        def fake_requests_fetch(_shared_state, method, target_url, **kwargs):
            # The CAPTCHA validation must run on the same requests.Session that
            # solved the CAPTCHA, not the FlareSolverr browser.
            validate_calls.append(
                {
                    "post_data": kwargs.get("post_data") or {},
                    "request_headers": kwargs.get("request_headers"),
                }
            )
            return FlareSolverrResponse(
                {
                    "code": "success",
                    "message": "",
                    "content": [{"hoster": "Mirror", "cnl": {}}],
                }
            )

        with (
            patch(
                "quasarr.search.sources.templates.al.download.is_flaresolverr_available",
                return_value=True,
            ),
            patch(
                "quasarr.search.sources.templates.al.download.retrieve_and_validate_session",
                return_value=requests.Session(),
            ),
            patch(
                "quasarr.search.sources.templates.al.download.flaresolverr_create_session",
                return_value="browser-session",
            ),
            patch(
                "quasarr.search.sources.templates.al.download.flaresolverr_destroy_session"
            ) as destroy_session,
            patch(
                "quasarr.search.sources.templates.al.download.fetch_via_flaresolverr",
                fake_fetch,
            ),
            patch(
                "quasarr.search.sources.templates.al.download.fetch_via_requests_session",
                fake_requests_fetch,
            ),
            patch(
                "quasarr.search.sources.templates.al.download._check_release",
                return_value=("Example.Release", 1),
            ),
            patch(
                "quasarr.search.sources.templates.al.download._extract_episode",
                return_value=None,
            ),
            patch(
                "quasarr.search.sources.templates.al.download.solve_captcha",
                return_value={"response": "1", "captcha_id": "captcha-id"},
            ) as solve_captcha,
            patch(
                "quasarr.search.sources.templates.al.download.decrypt_content",
                return_value=["https://files.invalid/download"],
            ),
            patch(
                "quasarr.search.sources.templates.al.download.StatsHelper",
                return_value=Stats(),
            ),
        ):
            result = Source().get_download_links(
                shared_state,
                "https://www.source.invalid/media/example",
                [],
                "Example.Release",
                "1",
            )

        self.assertEqual(
            {
                "links": [["https://files.invalid/download", "files"]],
                "password": "www.source.invalid",
                "title": "Example.Release",
            },
            result,
        )
        self.assertEqual(
            ["browser-session", "browser-session"],
            fetch_session_ids,
        )
        self.assertIsNone(request_headers[0])
        for headers in request_headers[1:]:
            self.assertEqual(
                "XMLHttpRequest",
                headers.get("X-Requested-With"),
            )
            self.assertEqual(
                "application/x-www-form-urlencoded; charset=UTF-8",
                headers.get("Content-Type"),
            )
            self.assertNotIn("Origin", headers)
            self.assertNotIn("Referer", headers)
        self.assertEqual(
            "XMLHttpRequest",
            solve_captcha.call_args.kwargs["request_headers"].get("X-Requested-With"),
        )
        self.assertEqual(
            "https://www.source.invalid",
            solve_captcha.call_args.kwargs["request_headers"].get("Origin"),
        )
        self.assertEqual(
            "https://www.source.invalid/media/example",
            solve_captcha.call_args.kwargs["request_headers"].get("Referer"),
        )
        self.assertEqual(
            "browser-session", solve_captcha.call_args.kwargs["session_id"]
        )
        # The validation runs once, on the requests.Session, carrying the solved
        # CAPTCHA fields and the AJAX headers (not the FlareSolverr browser).
        self.assertEqual(1, len(validate_calls))
        validate_payload = validate_calls[0]["post_data"]
        self.assertEqual("captcha", validate_payload["response"])
        self.assertEqual(0, validate_payload["captcha-idhf"])
        self.assertEqual("captcha-id", validate_payload["captcha-hf"])
        self.assertEqual(
            "XMLHttpRequest",
            validate_calls[0]["request_headers"].get("X-Requested-With"),
        )
        destroy_session.assert_called_once_with(shared_state, "browser-session")


if __name__ == "__main__":
    unittest.main()
