# -*- coding: utf-8 -*-

import json
import sys
import unittest
import zlib
from base64 import urlsafe_b64encode
from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.parse import quote

from bottle import Bottle

from quasarr.api.captcha import setup_captcha_routes
from quasarr.providers import shared_state


class FakeProtectedDb:
    def __init__(self, packages):
        self.packages = packages

    def retrieve_all_titles(self):
        return list(self.packages)

    def retrieve(self, package_id):
        for pkg_id, payload in self.packages:
            if pkg_id == package_id:
                return payload
        return None

    def delete(self, package_id):
        self.packages[:] = [pkg for pkg in self.packages if pkg[0] != package_id]


def build_package(pkg_id, url, mirror, password=""):
    return (
        pkg_id,
        json.dumps(
            {
                "title": "Synthetic.Release.2024.German.1080p.WEB.H264-GRP",
                "links": [[url, mirror]],
                "password": password,
            }
        ),
    )


def encode_data_param(package):
    pkg_id, payload = package
    data = json.loads(payload)
    page_payload = {
        "package_id": pkg_id,
        "title": data["title"],
        "password": data["password"],
        "mirror": None,
        "links": data["links"],
        "original_url": None,
    }
    return quote(urlsafe_b64encode(json.dumps(page_payload).encode()).decode())


class CaptchaUserscriptRoutingTests(unittest.TestCase):
    def _request(self, app, path, query=""):
        environ = {
            "REQUEST_METHOD": "GET",
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "SERVER_NAME": "localhost",
            "SERVER_PORT": "8080",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "HTTP_HOST": "localhost:8080",
            "wsgi.url_scheme": "http",
            "wsgi.input": BytesIO(b""),
            "wsgi.errors": sys.stderr,
        }
        captured = {}

        def start_response(status, headers, exc_info=None):
            captured["status"] = status
            captured["headers"] = dict(headers)

        body = b"".join(app(environ, start_response))
        return captured["status"], captured["headers"], body.decode("utf-8", "replace")

    def _post_form(self, app, path, form):
        encoded = "&".join(f"{key}={quote(str(value))}" for key, value in form.items())
        environ = {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": path,
            "QUERY_STRING": "",
            "CONTENT_TYPE": "application/x-www-form-urlencoded",
            "CONTENT_LENGTH": str(len(encoded.encode())),
            "SERVER_NAME": "localhost",
            "SERVER_PORT": "8080",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "HTTP_HOST": "localhost:8080",
            "wsgi.url_scheme": "http",
            "wsgi.input": BytesIO(encoded.encode()),
            "wsgi.errors": sys.stderr,
        }
        captured = {}

        def start_response(status, headers, exc_info=None):
            captured["status"] = status
            captured["headers"] = dict(headers)

        body = b"".join(app(environ, start_response))
        return captured["status"], captured["headers"], body.decode("utf-8", "replace")

    def _serve(self, packages):
        app = Bottle()
        fake_values = {
            "device": object(),
            # Sections are plain dicts; only .get() is used by the routes under test
            "config": lambda section: (
                {"he": "source.invalid"} if section == "Hostnames" else {}
            ),
        }
        stack = patch.multiple(
            shared_state,
            values=fake_values,
            get_db=lambda name: FakeProtectedDb(packages),
        )
        stack.start()
        self.addCleanup(stack.stop)
        setup_captcha_routes(app)
        return app

    def test_filecrypt_package_redirects_to_filecrypt_userscript_page(self):
        package = build_package(
            "pkg-fc",
            "https://filecrypt.example.invalid/Container/abc.html",
            "filecrypt",
        )
        app = self._serve([package])

        status, headers, _ = self._request(app, "/captcha")

        self.assertTrue(status.startswith("30"))
        self.assertIn("/captcha/filecrypt?data=", headers["Location"])

    def test_keeplinks_package_still_redirects_to_keeplinks_page(self):
        package = build_package(
            "pkg-kl", "https://keeplinks.example.invalid/p/abc", "keeplinks"
        )
        app = self._serve([package])

        status, headers, _ = self._request(app, "/captcha")

        self.assertTrue(status.startswith("30"))
        self.assertIn("/captcha/keeplinks?data=", headers["Location"])

    def test_he_package_redirects_to_he_userscript_page(self):
        package = build_package(
            "pkg-he", "https://source.invalid/releases/synthetic", "he"
        )
        app = self._serve([package])

        status, headers, _ = self._request(app, "/captcha")

        self.assertTrue(status.startswith("30"))
        self.assertIn("/captcha/he?data=", headers["Location"])

    def test_filecrypt_page_renders_standard_userscript_section(self):
        package = build_package(
            "pkg-fc",
            "https://filecrypt.example.invalid/Container/abc.html",
            "filecrypt",
        )
        app = self._serve([package])

        status, _, body = self._request(
            app, "/captcha/filecrypt", f"data={encode_data_param(package)}"
        )

        self.assertEqual("200 OK", status)
        self.assertIn("Open FileCrypt & Get Download Links", body)
        self.assertIn("/captcha/filecrypt.user.js", body)
        self.assertIn("abc.html?transfer_url=", body)

    def test_filecrypt_page_appends_transfer_params_to_existing_query(self):
        package = build_package(
            "pkg-fc",
            "https://filecrypt.example.invalid/Container/abc.html?mirror=2",
            "filecrypt",
        )
        app = self._serve([package])

        status, _, body = self._request(
            app, "/captcha/filecrypt", f"data={encode_data_param(package)}"
        )

        self.assertEqual("200 OK", status)
        self.assertIn("abc.html?mirror=2&transfer_url=", body)
        self.assertNotIn("mirror=2?transfer_url=", body)

    def test_keeplinks_page_still_renders_standard_userscript_section(self):
        package = build_package(
            "pkg-kl", "https://keeplinks.example.invalid/p/abc", "keeplinks"
        )
        app = self._serve([package])

        status, _, body = self._request(
            app, "/captcha/keeplinks", f"data={encode_data_param(package)}"
        )

        self.assertEqual("200 OK", status)
        self.assertIn("Open KeepLinks & Get Download Links", body)
        self.assertIn("/captcha/keeplinks.user.js", body)
        self.assertIn("quick-transfer", body)

    def test_he_page_renders_standard_userscript_section(self):
        package = build_package(
            "pkg-he", "https://source.invalid/releases/synthetic", "he"
        )
        app = self._serve([package])

        status, _, body = self._request(
            app, "/captcha/he", f"data={encode_data_param(package)}"
        )

        self.assertEqual("200 OK", status)
        self.assertIn("Open HE & Get Download Links", body)
        self.assertIn("/captcha/he.user.js", body)
        self.assertIn("quick-transfer", body)

    def test_he_page_accepts_missing_password(self):
        package = build_package(
            "pkg-he", "https://source.invalid/releases/synthetic", "he", None
        )
        app = self._serve([package])

        status, _, body = self._request(
            app, "/captcha/he", f"data={encode_data_param(package)}"
        )

        self.assertEqual("200 OK", status)
        self.assertIn("Open HE & Get Download Links", body)

    def test_he_userscript_uses_configured_hostname(self):
        package = build_package(
            "pkg-he", "https://source.invalid/releases/synthetic", "he"
        )
        app = self._serve([package])

        status, headers, body = self._request(app, "/captcha/he.user.js")

        self.assertEqual("200 OK", status)
        self.assertEqual("application/javascript", headers["Content-Type"])
        self.assertIn("*://source.invalid/*", body)
        self.assertNotIn("{he}", body)

    def test_removed_server_side_filecrypt_routes_are_gone(self):
        package = build_package(
            "pkg-fc",
            "https://filecrypt.example.invalid/Container/abc.html",
            "filecrypt",
        )
        app = self._serve([package])

        for path in (
            "/captcha/cutcaptcha",
            "/captcha/circle",
            "/captcha/filecrypt/manual",
        ):
            with self.subTest(path=path):
                status, _, _ = self._request(app, path)
                self.assertTrue(status.startswith("404"))

    def test_quick_transfer_error_marks_package_failed_and_removes_protected(self):
        package = build_package(
            "pkg-hide",
            "https://hide.cx/container/synthetic?season=2&episode=7",
            "hide",
        )
        app = self._serve([package])
        stats = MagicMock()

        with (
            patch("quasarr.api.captcha.fail") as fail,
            patch("quasarr.api.captcha.update_release_notification") as notify,
            patch("quasarr.api.captcha.StatsHelper", return_value=stats),
        ):
            status, _, body = self._request(
                app,
                "/captcha/quick-transfer",
                "pkg_id=pkg-hide&season=2&episode=7&error=Episode%20not%20present%20in%20link%20container",
            )

        self.assertEqual("200 OK", status)
        self.assertIn("Package marked as failed", body)
        self.assertIn("Episode not present in link container", body)
        fail.assert_called_once_with(
            "Synthetic.Release.2024.German.1080p.WEB.H264-GRP",
            "pkg-hide",
            shared_state,
            reason="Episode not present in link container",
        )
        notify.assert_called_once()
        stats.increment_failed_decryptions_manual.assert_called_once_with()

    def test_quick_transfer_stale_error_does_not_create_failed_package(self):
        app = self._serve([])

        with (
            patch("quasarr.api.captcha.fail") as fail,
            patch("quasarr.api.captcha.StatsHelper") as stats,
        ):
            status, _, body = self._request(
                app,
                "/captcha/quick-transfer",
                "pkg_id=missing&error=late%20userscript%20error",
            )

        self.assertTrue(status.startswith("404"))
        self.assertIn("Package not found", body)
        fail.assert_not_called()
        stats.assert_not_called()

    def test_quick_transfer_escapes_displayed_error_but_persists_raw_reason(self):
        package = build_package(
            "pkg-hide",
            "https://hide.cx/container/synthetic?season=2&episode=7",
            "hide",
        )
        app = self._serve([package])
        reason = "<script>alert('x')</script>"

        with (
            patch("quasarr.api.captcha.fail") as fail,
            patch("quasarr.api.captcha.update_release_notification"),
            patch("quasarr.api.captcha.StatsHelper"),
        ):
            status, _, body = self._request(
                app,
                "/captcha/quick-transfer",
                "pkg_id=pkg-hide&season=2&episode=7&error=%3Cscript%3Ealert%28%27x%27%29%3C%2Fscript%3E",
            )

        self.assertEqual("200 OK", status)
        self.assertIn("&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;", body)
        self.assertNotIn(reason, body)
        self.assertEqual(reason, fail.call_args.kwargs["reason"])

    def test_quick_transfer_error_does_not_fail_legacy_hide_package(self):
        package = build_package(
            "pkg-hide",
            "https://hide.cx/container/synthetic",
            "hide",
        )
        app = self._serve([package])

        with (
            patch("quasarr.api.captcha.fail") as fail,
            patch("quasarr.api.captcha.StatsHelper") as stats,
        ):
            status, _, body = self._request(
                app,
                "/captcha/quick-transfer",
                "pkg_id=pkg-hide&error=legacy%20error",
            )

        self.assertEqual("200 OK", status)
        self.assertIn("legacy error", body)
        self.assertNotIn("Package marked as failed", body)
        fail.assert_not_called()
        stats.assert_not_called()

    def test_quick_transfer_error_does_not_fail_on_mismatched_selection(self):
        package = build_package(
            "pkg-hide",
            "https://hide.cx/container/synthetic?season=2&episode=7",
            "hide",
        )
        app = self._serve([package])

        with patch("quasarr.api.captcha.fail") as fail:
            status, _, body = self._request(
                app,
                "/captcha/quick-transfer",
                "pkg_id=pkg-hide&season=2&episode=8&error=wrong%20selection",
            )

        self.assertEqual("200 OK", status)
        self.assertIn("Hide episode selection was not confirmed", body)
        self.assertNotIn("Package marked as failed", body)
        fail.assert_not_called()

    def test_quick_transfer_selected_hide_requires_matching_confirmation(self):
        package = build_package(
            "pkg-hide",
            "https://hide.cx/container/synthetic?season=2&episode=7",
            "hide",
        )
        app = self._serve([package])
        compressor = zlib.compressobj(wbits=-15)
        encoded = urlsafe_b64encode(
            compressor.compress(b"https://hoster.invalid/file/synthetic")
            + compressor.flush()
        ).decode()
        stats = MagicMock()

        with (
            patch("quasarr.api.captcha.fail") as fail,
            patch("quasarr.api.captcha.update_release_notification"),
            patch("quasarr.api.captcha.StatsHelper", return_value=stats),
            patch("quasarr.api.captcha.submit_final_download_urls") as submit,
        ):
            status, _, body = self._request(
                app,
                "/captcha/quick-transfer",
                f"pkg_id=pkg-hide&links={encoded}",
            )

        self.assertEqual("200 OK", status)
        self.assertIn("Package marked as failed", body)
        self.assertIn("Hide episode selection was not confirmed", body)
        fail.assert_called_once()
        submit.assert_not_called()
        stats.increment_failed_decryptions_manual.assert_called_once_with()

    def test_quick_transfer_duplicate_episode_confirmation_keys_fail(self):
        package = build_package(
            "pkg-hide",
            "https://hide.cx/container/synthetic?season=2&episode=7",
            "hide",
        )
        app = self._serve([package])
        compressor = zlib.compressobj(wbits=-15)
        encoded = urlsafe_b64encode(
            compressor.compress(b"https://hoster.invalid/file/synthetic")
            + compressor.flush()
        ).decode()

        with (
            patch("quasarr.api.captcha.fail"),
            patch("quasarr.api.captcha.update_release_notification"),
            patch("quasarr.api.captcha.StatsHelper"),
            patch("quasarr.api.captcha.submit_final_download_urls") as submit,
        ):
            status, _, body = self._request(
                app,
                "/captcha/quick-transfer",
                f"pkg_id=pkg-hide&links={encoded}&season=2&season=2&episode=7",
            )

        self.assertEqual("200 OK", status)
        self.assertIn("Hide episode selection was not confirmed", body)
        submit.assert_not_called()

    def test_bypass_submit_selected_hide_fails_closed_without_confirmation(self):
        package = build_package(
            "pkg-hide",
            "https://hide.cx/container/synthetic?season=2&episode=7",
            "hide",
        )
        app = self._serve([package])

        with (
            patch("quasarr.api.captcha.fail") as fail,
            patch("quasarr.api.captcha.update_release_notification"),
            patch("quasarr.api.captcha.StatsHelper") as stats,
            patch("quasarr.api.captcha.submit_final_download_urls") as submit,
        ):
            status, _, body = self._post_form(
                app,
                "/captcha/bypass-submit",
                {
                    "package_id": "pkg-hide",
                    "title": "Synthetic.Release.2024.German.1080p.WEB.H264-GRP",
                    "links": "https://hoster.invalid/file/synthetic",
                },
            )

        self.assertEqual("200 OK", status)
        self.assertIn("Hide episode selection was not confirmed", body)
        fail.assert_called_once()
        submit.assert_not_called()
        stats.return_value.increment_failed_decryptions_manual.assert_called_once_with()

    def test_quick_transfer_selected_hide_accepts_matching_confirmation(self):
        package = build_package(
            "pkg-hide",
            "https://hide.cx/container/synthetic?season=2&episode=7",
            "hide",
        )
        app = self._serve([package])
        compressor = zlib.compressobj(wbits=-15)
        encoded = urlsafe_b64encode(
            compressor.compress(b"https://hoster.invalid/file/synthetic")
            + compressor.flush()
        ).decode()
        stats = MagicMock()

        with (
            patch("quasarr.api.captcha.StatsHelper", return_value=stats),
            patch(
                "quasarr.api.captcha.submit_final_download_urls",
                return_value={
                    "success": True,
                    "links": ["https://hoster.invalid/file/synthetic"],
                },
            ) as submit,
        ):
            status, _, body = self._request(
                app,
                "/captcha/quick-transfer",
                f"pkg_id=pkg-hide&links={encoded}&season=2&episode=7",
            )

        self.assertEqual("200 OK", status)
        self.assertIn("CAPTCHA solved and submitted", body)
        submit.assert_called_once()
        stats.increment_captcha_decryptions_manual.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
