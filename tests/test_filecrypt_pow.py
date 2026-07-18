import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from quasarr.downloads.linkcrypters import filecrypt


class SharedState:
    def __init__(self):
        self.values = {
            "config": lambda section: {"url": "http://solver.invalid/v1"},
            "user_agent": "old-agent",
        }

    def update(self, key, value):
        self.values[key] = value


class Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FilecryptPowTests(unittest.TestCase):
    def test_detect_filecrypt_captcha_type(self):
        cases = [
            ('<form class="cnlform"></form>', "none"),
            ('<div id="pow-captcha" class="pow-captcha"></div>', "pow"),
            ('<div class="circle_captcha"></div>', "circle"),
            (
                "<h1>Security Check</h1>"
                "<p>To continue, please click inside the open circle.</p>",
                "circle",
            ),
            ('<input name="cap_token">', "cutcaptcha"),
            ('<button class="download" data-link="abc"></button>', "none"),
            ('<input id="p4assw0rt">', "password"),
            ("<html></html>", "unknown"),
        ]

        for html, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(
                    expected,
                    filecrypt.detect_filecrypt_captcha_type(html),
                )

    def test_execute_js_get_uses_stateless_flaresolverr_request(self):
        shared_state = SharedState()
        session = requests.Session()
        session.cookies.set("sessionid", "abc", domain="target.invalid", path="/")

        payload = {
            "status": "ok",
            "solution": {
                "url": "https://target.invalid/after",
                "response": "<html></html>",
                "executeJsResult": "clicked",
                "documentStartJsResult": "installed",
                "userAgent": "new-agent",
                "cookies": [
                    {
                        "name": "solved",
                        "value": "yes",
                        "domain": "target.invalid",
                        "path": "/",
                    }
                ],
            },
        }

        with patch.object(
            filecrypt.requests, "post", return_value=Response(payload)
        ) as post:
            result = filecrypt._flaresolverr_execute_js_get(
                shared_state,
                session,
                "https://target.invalid/page",
                "return 'clicked';",
            )

        self.assertEqual("clicked", result["execute_js_result"])
        self.assertEqual("new-agent", shared_state.values["user_agent"])
        self.assertEqual("yes", session.cookies.get("solved"))

        request_payload = post.call_args.kwargs["json"]
        self.assertNotIn("session", request_payload)
        self.assertEqual("request.get", request_payload["cmd"])
        self.assertEqual("return 'clicked';", request_payload["executeJs"])
        self.assertEqual("sessionid", request_payload["cookies"][0]["name"])
        self.assertEqual(
            filecrypt._FILECRYPT_DOCUMENT_START_JS,
            request_payload["documentStartJs"],
        )
        self.assertNotIn("window.open = function", request_payload["documentStartJs"])
        self.assertTrue(request_payload["trustedClick"])

    def test_solve_pow_returns_refreshed_page_after_click(self):
        shared_state = SharedState()
        session = requests.Session()
        initial = SimpleNamespace(
            url="https://target.invalid/page",
            text='<div id="pow-captcha" class="pow-captcha"></div>',
        )
        refreshed = SimpleNamespace(
            url="https://target.invalid/page",
            text='<form class="cnlform"></form>',
        )
        session.get = Mock(return_value=refreshed)

        with patch.object(
            filecrypt,
            "_flaresolverr_execute_js_get",
            return_value={
                "url": "https://target.invalid/page",
                "html": "",
                "execute_js_result": "clicked",
            },
        ) as execute_js_get:
            result = filecrypt._solve_filecrypt_pow_if_present(
                shared_state,
                session,
                initial,
                {"User-Agent": "agent"},
            )

        self.assertIs(refreshed, result)
        self.assertIn("}, 90000);", execute_js_get.call_args.args[3])

    def test_no_token_returns_captcha_required_after_pow_reveals_cutcaptcha(self):
        shared_state = SharedState()
        initial = SimpleNamespace(
            url="https://target.invalid/page",
            text='<div id="pow-captcha" class="pow-captcha"></div>',
            status_code=200,
        )
        cutcaptcha = SimpleNamespace(
            url="https://target.invalid/page",
            text='<input name="cap_token">',
            status_code=200,
        )

        with (
            patch.object(
                filecrypt,
                "ensure_session_cf_bypassed",
                return_value=(requests.Session(), {"User-Agent": "agent"}, initial),
            ),
            patch.object(
                filecrypt,
                "_solve_filecrypt_pow_if_present",
                return_value=cutcaptcha,
            ),
        ):
            result = filecrypt.get_filecrypt_links(
                shared_state,
                "",
                "Example.Release",
                "https://target.invalid/page",
            )

        self.assertEqual(
            {
                "status": "captcha_required",
                "url": "https://target.invalid/page",
                "cookies": [],
            },
            result,
        )

    def test_circle_challenge_returns_separate_required_action(self):
        shared_state = SharedState()
        initial = SimpleNamespace(
            url="https://target.invalid/page",
            text='<div class="circle_captcha"></div>',
            status_code=200,
        )

        with patch.object(
            filecrypt,
            "ensure_session_cf_bypassed",
            return_value=(requests.Session(), {"User-Agent": "agent"}, initial),
        ):
            result = filecrypt.get_filecrypt_links(
                shared_state,
                "",
                "Example.Release",
                "https://target.invalid/page",
            )

        self.assertEqual(
            {
                "status": "circle_required",
                "url": "https://target.invalid/page",
                "cookies": [],
            },
            result,
        )

    def test_prepare_circle_captcha_posts_password_and_returns_image_payload(self):
        shared_state = SharedState()
        session = requests.Session()
        session.cookies.set("sessionid", "abc", domain="target.invalid", path="/")
        password_page = SimpleNamespace(
            url="https://target.invalid/page",
            text='<input type="password" name="pw">',
            status_code=200,
        )
        circle_page = SimpleNamespace(
            url="https://target.invalid/page",
            text='<div class="circle_captcha"></div>',
            status_code=200,
        )
        session.post = Mock(return_value=circle_page)
        image_response = Mock(
            content=b"image",
            headers={"Content-Type": "image/png"},
        )
        image_response.raise_for_status = Mock()

        with (
            patch.object(
                filecrypt,
                "ensure_session_cf_bypassed",
                return_value=(session, {"User-Agent": "agent"}, password_page),
            ),
            patch.object(
                filecrypt.requests, "get", return_value=image_response
            ) as image_get,
        ):
            result = filecrypt.prepare_filecrypt_circle_captcha(
                shared_state,
                "https://target.invalid/page",
                password="secret",
            )

        session.post.assert_called_once()
        self.assertEqual({"pw": "secret"}, session.post.call_args.kwargs["data"])
        self.assertEqual(b"image", result["image"])
        self.assertEqual("image/png", result["content_type"])
        self.assertEqual("sessionid", result["cookies"][0]["name"])
        self.assertIn("a", [cookie["name"] for cookie in result["cookies"]])
        self.assertEqual(
            "https://target.invalid/page",
            image_get.call_args.kwargs["headers"]["Referer"],
        )

    def test_circle_solution_posts_filecrypt_button_coordinates(self):
        shared_state = SharedState()
        session = requests.Session()
        initial = SimpleNamespace(
            url="https://target.invalid/page",
            text='<div class="circle_captcha"></div>',
            status_code=200,
        )
        rejected = SimpleNamespace(
            url="https://target.invalid/page",
            text='<div class="circle_captcha"></div>',
            status_code=200,
        )
        session.post = Mock(return_value=rejected)

        with patch.object(
            filecrypt,
            "ensure_session_cf_bypassed",
            return_value=(session, {"User-Agent": "agent"}, initial),
        ):
            result = filecrypt.get_filecrypt_links(
                shared_state,
                "",
                "Example.Release",
                "https://target.invalid/page",
                circle_solution=("36", "54"),
            )

        self.assertFalse(result)
        post_call = session.post.call_args
        self.assertEqual({"button.x": "36", "button.y": "54"}, post_call.kwargs["data"])
        self.assertEqual(
            "https://target.invalid", post_call.kwargs["headers"]["Origin"]
        )
        self.assertEqual(
            "https://target.invalid/page", post_call.kwargs["headers"]["Referer"]
        )

    def test_single_link_button_circle_returns_stateless_handoff(self):
        shared_state = SharedState()
        session = requests.Session()
        session.cookies.set("PHPSESSID", "session", domain="target.invalid", path="/")
        container = SimpleNamespace(
            url="https://target.invalid/container",
            text=(
                '<div class="container"></div>'
                '<button class="download" data-target="ABC123"></button>'
            ),
            status_code=200,
        )
        single_link_circle = SimpleNamespace(
            url="https://target.invalid/Link/ABC123.html",
            text='<div class="circle_captcha"></div>',
            status_code=200,
        )
        session.get = Mock(return_value=single_link_circle)

        with patch.object(
            filecrypt,
            "ensure_session_cf_bypassed",
            return_value=(session, {"User-Agent": "agent"}, container),
        ):
            result = filecrypt.get_filecrypt_links(
                shared_state,
                "",
                "Example.Release",
                "https://target.invalid/container",
            )

        self.assertEqual("single_link_circle_required", result["status"])
        self.assertEqual("https://target.invalid/Link/ABC123.html", result["url"])
        self.assertEqual("PHPSESSID", result["cookies"][0]["name"])

    def test_circle_solution_resolves_go_redirect(self):
        shared_state = SharedState()
        session = requests.Session()
        circle = SimpleNamespace(
            url="https://target.invalid/Link/ABC123.html",
            text='<div class="circle_captcha"></div>',
            status_code=200,
        )
        go_page = SimpleNamespace(
            url="https://target.invalid/Link/ABC123.html",
            text=(
                "<script>top.location.href="
                "'https://target.invalid/Go/deadbeef.html';</script>"
            ),
            status_code=200,
        )
        redirect = SimpleNamespace(
            url="https://target.invalid/Go/deadbeef.html",
            text="",
            status_code=302,
            headers={"Location": "https://download.invalid/file.bin"},
        )
        session.post = Mock(return_value=go_page)
        session.get = Mock(return_value=redirect)

        with patch.object(
            filecrypt,
            "ensure_session_cf_bypassed",
            return_value=(session, {"User-Agent": "agent"}, circle),
        ):
            result = filecrypt.get_filecrypt_links(
                shared_state,
                "",
                "Example.Release",
                "https://target.invalid/Link/ABC123.html",
                circle_solution=("180", "229"),
            )

        self.assertEqual(
            {"status": "success", "links": ["https://download.invalid/file.bin"]},
            result,
        )

    def test_go_resolver_ignores_internal_filecrypt_terminal_url(self):
        session = requests.Session()
        response = SimpleNamespace(
            url="https://filecrypt.invalid/Go/deadbeef.html",
            headers={},
        )
        session.get = Mock(return_value=response)

        result = filecrypt._resolve_filecrypt_go_urls(
            session,
            {"User-Agent": "agent"},
            ["https://filecrypt.invalid/Go/deadbeef.html"],
        )

        self.assertEqual([], result)


if __name__ == "__main__":
    unittest.main()
