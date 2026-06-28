# -*- coding: utf-8 -*-

import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from quasarr.downloads import download
from quasarr.downloads.sources.by import Source as BySource
from quasarr.downloads.sources.nk import Source as NkSource
from quasarr.downloads.sources.sf import Source as SfSource
from quasarr.downloads.sources.wd import Source as WdSource


class FakeResponse:
    def __init__(self, url, text="", status_code=200, headers=None):
        self.url = url
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}
        self.history = []

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(
                f"{self.status_code} Client Error: Forbidden for url: {self.url}"
            )


def _build_shared_state(hostnames):
    shared_state = MagicMock()

    def _config(section):
        if section == "Hostnames":
            return hostnames
        return {}

    shared_state.values = {
        "config": _config,
        "user_agent": "UnitTestAgent/1.0",
        "external_address": "http://localhost:5678",
    }
    return shared_state


class ProtectedRedirectSourceTests(unittest.TestCase):
    def test_by_yields_protected_url_without_requesting_it(self):
        release_url = "https://host-by.invalid/release-1.html"
        iframe_url = "https://host-by.invalid/frame-1.html"
        go_url = "https://host-by.invalid/go.php?id=123"
        cookie_url = "https://host-by.invalid/step/needs-cookie"
        protected_url = "https://protected.invalid/container/by-123"
        requested_urls = []
        redirect_requests = []

        release_html = f'<html><iframe src="{iframe_url}"></iframe></html>'
        iframe_html = f'<html><a href="{go_url}">DDownload</a></html>'

        def fake_get(url, headers=None, timeout=None, allow_redirects=True):
            requested_urls.append((url, allow_redirects))
            if url == release_url:
                return FakeResponse(url=release_url, text=release_html)
            if url == iframe_url:
                return FakeResponse(url=iframe_url, text=iframe_html)
            raise AssertionError(f"Unexpected URL requested: {url}")

        class FakeSession:
            def __init__(self):
                self._saw_first_hop = False

            def get(self, url, headers=None, timeout=None, allow_redirects=True):
                redirect_requests.append((url, allow_redirects))
                if url == go_url:
                    self._saw_first_hop = True
                    return FakeResponse(
                        url=go_url,
                        status_code=302,
                        headers={"Location": cookie_url},
                    )
                if url == cookie_url:
                    if not self._saw_first_hop:
                        return FakeResponse(url=url, status_code=200, text="blocked")
                    return FakeResponse(
                        url=cookie_url,
                        status_code=302,
                        headers={"Location": protected_url},
                    )
                raise AssertionError(f"Unexpected URL requested: {url}")

        with (
            patch("quasarr.downloads.sources.by.requests.get", side_effect=fake_get),
            patch(
                "quasarr.downloads.sources.by.requests.Session",
                return_value=FakeSession(),
            ),
            patch(
                "quasarr.downloads.sources.by.detect_crypter_type",
                side_effect=lambda url: "filecrypt" if url == protected_url else None,
            ),
        ):
            result = BySource().get_download_links(
                _build_shared_state({"by": "host-by.invalid"}),
                release_url,
                ["ddownload"],
                "Example.Title",
                None,
            )

        self.assertEqual({"links": [[protected_url, "filecrypt"]]}, result)
        self.assertEqual(
            [
                (release_url, True),
                (iframe_url, True),
            ],
            requested_urls,
        )
        self.assertEqual(
            [
                (go_url, False),
                (cookie_url, False),
            ],
            redirect_requests,
        )

    def test_by_matches_requested_mirror_from_icon_only_iframe_link(self):
        release_url = "https://host-by.invalid/release-icons.html"
        iframe_url = "https://host-by.invalid/frame-icons.html"
        go_url = "https://host-by.invalid/go.php?hash=icons"
        protected_url = "https://protected.invalid/container/by-icons"

        release_html = f'<html><iframe src="{iframe_url}"></iframe></html>'
        iframe_html = f"""
            <html>
                <a href="{go_url}" target="_blank" class="loadbutton">
                    <span class="green-dot" title="Online"></span>
                    <img src="/widgets/favicons/turbobit.net.ico" title="turbobit.net">
                    <img src="/widgets/favicons/rapidgator.net.ico" title="rapidgator.net">
                    <img src="/widgets/favicons/nitroflare.com.ico" title="nitroflare.com">
                </a>
            </html>
        """

        def fake_get(url, headers=None, timeout=None, allow_redirects=True):
            if url == release_url:
                return FakeResponse(url=release_url, text=release_html)
            if url == iframe_url:
                return FakeResponse(url=iframe_url, text=iframe_html)
            raise AssertionError(f"Unexpected URL requested: {url}")

        class FakeSession:
            def get(self, url, headers=None, timeout=None, allow_redirects=True):
                if url == go_url:
                    return FakeResponse(
                        url=go_url,
                        status_code=302,
                        headers={"Location": protected_url},
                    )
                raise AssertionError(f"Unexpected URL requested: {url}")

        with (
            patch("quasarr.downloads.sources.by.requests.get", side_effect=fake_get),
            patch(
                "quasarr.downloads.sources.by.requests.Session",
                return_value=FakeSession(),
            ),
            patch(
                "quasarr.downloads.sources.by.detect_crypter_type",
                side_effect=lambda url: "filecrypt" if url == protected_url else None,
            ),
        ):
            result = BySource().get_download_links(
                _build_shared_state({"by": "host-by.invalid"}),
                release_url,
                ["rapidgator"],
                "GameStar - 2026 05",
                None,
            )

        self.assertEqual({"links": [[protected_url, "filecrypt"]]}, result)

    def test_by_uses_resolved_hostname_for_icon_only_direct_link(self):
        release_url = "https://host-by.invalid/release-direct-icons.html"
        iframe_url = "https://host-by.invalid/frame-direct-icons.html"
        go_url = "https://host-by.invalid/go.php?hash=direct-icons"
        direct_url = "https://rapidgator.net/file/abc123/GameStar.rar.html"

        release_html = f'<html><iframe src="{iframe_url}"></iframe></html>'
        iframe_html = f"""
            <html>
                <a href="{go_url}" target="_blank" class="loadbutton">
                    <span class="green-dot" title="Online"></span>
                    <img src="/widgets/favicons/turbobit.net.ico" title="turbobit.net">
                    <img src="/widgets/favicons/rapidgator.net.ico" title="rapidgator.net">
                    <img src="/widgets/favicons/nitroflare.com.ico" title="nitroflare.com">
                </a>
            </html>
        """

        def fake_get(url, headers=None, timeout=None, allow_redirects=True):
            if url == release_url:
                return FakeResponse(url=release_url, text=release_html)
            if url == iframe_url:
                return FakeResponse(url=iframe_url, text=iframe_html)
            raise AssertionError(f"Unexpected URL requested: {url}")

        class FakeSession:
            def get(self, url, headers=None, timeout=None, allow_redirects=True):
                if url == go_url:
                    return FakeResponse(
                        url=go_url,
                        status_code=302,
                        headers={"Location": direct_url},
                    )
                if url == direct_url:
                    return FakeResponse(url=direct_url)
                raise AssertionError(f"Unexpected URL requested: {url}")

        with (
            patch("quasarr.downloads.sources.by.requests.get", side_effect=fake_get),
            patch(
                "quasarr.downloads.sources.by.requests.Session",
                return_value=FakeSession(),
            ),
            patch(
                "quasarr.downloads.sources.by.detect_crypter_type",
                return_value=None,
            ),
        ):
            result = BySource().get_download_links(
                _build_shared_state({"by": "host-by.invalid"}),
                release_url,
                ["rapidgator"],
                "GameStar - 2026 05",
                None,
            )

        self.assertEqual({"links": [[direct_url, "rapidgator.net"]]}, result)

    def test_nk_yields_protected_url_without_requesting_it(self):
        release_url = "https://host-nk.invalid/release-1.html"
        go_url = "https://host-nk.invalid/go/4696/ddl.to"
        protected_url = "https://protected.invalid/container/nk-123"
        requested_urls = []

        release_html = (
            '<html><a class="btn-orange" href="/go/4696/ddl.to">DDownload</a></html>'
        )

        class FakeSession:
            def get(self, url, headers=None, timeout=None, allow_redirects=True):
                requested_urls.append((url, allow_redirects))
                if url == release_url:
                    return FakeResponse(url=release_url, text=release_html)
                if url == go_url:
                    return FakeResponse(
                        url=go_url,
                        status_code=302,
                        headers={"Location": protected_url},
                    )
                raise AssertionError(f"Unexpected URL requested: {url}")

        with (
            patch(
                "quasarr.downloads.sources.nk.requests.Session",
                return_value=FakeSession(),
            ),
            patch(
                "quasarr.downloads.sources.nk.detect_crypter_type",
                side_effect=lambda url: "filecrypt" if url == protected_url else None,
            ),
        ):
            result = NkSource().get_download_links(
                _build_shared_state({"nk": "host-nk.invalid"}),
                release_url,
                ["ddownload"],
                "Example.Title",
                None,
            )

        self.assertEqual({"links": [[protected_url, "ddownload"]]}, result)
        self.assertEqual(
            [
                (release_url, True),
                (go_url, False),
            ],
            requested_urls,
        )

    def test_sf_yields_protected_url_without_requesting_it(self):
        external_url = "https://host-sf.invalid/external/2/abc123"
        cookie_url = "https://host-sf.invalid/step/needs-cookie"
        protected_url = "https://protected.invalid/container/sf-123"
        requested_urls = []

        class FakeSession:
            def __init__(self):
                self._saw_first_hop = False

            def get(self, url, allow_redirects=False, timeout=None, headers=None):
                requested_urls.append((url, allow_redirects))
                if url == external_url:
                    self._saw_first_hop = True
                    return FakeResponse(
                        url=external_url,
                        status_code=302,
                        headers={"Location": cookie_url},
                    )
                if url == cookie_url:
                    if not self._saw_first_hop:
                        return FakeResponse(url=url, status_code=200, text="blocked")
                    return FakeResponse(
                        url=cookie_url,
                        status_code=302,
                        headers={"Location": protected_url},
                    )
                raise AssertionError(f"Unexpected URL requested: {url}")

        with (
            patch(
                "quasarr.downloads.sources.sf.requests.Session",
                return_value=FakeSession(),
            ),
            patch(
                "quasarr.downloads.sources.sf.detect_crypter_type",
                side_effect=lambda url: "filecrypt" if url == protected_url else None,
            ),
        ):
            result = SfSource().get_download_links(
                _build_shared_state({"sf": "host-sf.invalid"}),
                external_url,
                ["ddownload"],
                "Example.Release",
                None,
            )

        self.assertEqual(
            {"links": [[protected_url, "filecrypt"]], "imdb_id": None},
            result,
        )
        self.assertEqual(
            [
                (external_url, False),
                (cookie_url, False),
            ],
            requested_urls,
        )

    def test_sf_rejects_non_redirect_success_page(self):
        external_url = "https://host-sf.invalid/external/2/blocked"

        class FakeSession:
            def get(self, url, allow_redirects=False, timeout=None, headers=None):
                if url == external_url:
                    return FakeResponse(
                        url=external_url,
                        status_code=200,
                        text="<html><title>Blocked</title></html>",
                    )
                raise AssertionError(f"Unexpected URL requested: {url}")

        with (
            patch(
                "quasarr.downloads.sources.sf.requests.Session",
                return_value=FakeSession(),
            ),
            patch(
                "quasarr.downloads.sources.sf.detect_crypter_type",
                return_value=None,
            ),
        ):
            result = SfSource().get_download_links(
                _build_shared_state({"sf": "host-sf.invalid"}),
                external_url,
                ["ddownload"],
                "Example.Release",
                None,
            )

        self.assertEqual({"links": [], "imdb_id": None}, result)

    def test_wd_yields_protected_url_without_requesting_it(self):
        release_url = "https://host-wd.invalid/release-1.html"
        redirect_url = "https://host-wd.invalid/redirect/abc123"
        cookie_url = "https://host-wd.invalid/step/needs-cookie"
        protected_url = "https://protected.invalid/container/wd-123"
        requested_urls = []
        redirect_requests = []

        page_html = (
            '<div class="card">'
            '<div class="card-header">Downloads</div>'
            '<div class="card-body">'
            '<a href="/redirect/abc123" class="background-ddownload">DDownload</a>'
            "</div>"
            "</div>"
        )

        def fake_get(url, headers=None, timeout=None, allow_redirects=True):
            requested_urls.append((url, allow_redirects))
            if url == release_url:
                return FakeResponse(url=release_url, text=page_html)
            raise AssertionError(f"Unexpected URL requested: {url}")

        class FakeSession:
            def __init__(self):
                self._saw_first_hop = False

            def get(self, url, headers=None, timeout=None, allow_redirects=True):
                redirect_requests.append((url, allow_redirects))
                if url == redirect_url:
                    self._saw_first_hop = True
                    return FakeResponse(
                        url=redirect_url,
                        status_code=302,
                        headers={"Location": cookie_url},
                    )
                if url == cookie_url:
                    if not self._saw_first_hop:
                        return FakeResponse(url=url, status_code=200, text="blocked")
                    return FakeResponse(
                        url=cookie_url,
                        status_code=302,
                        headers={"Location": protected_url},
                    )
                raise AssertionError(f"Unexpected URL requested: {url}")

        with (
            patch("quasarr.downloads.sources.wd.requests.get", side_effect=fake_get),
            patch(
                "quasarr.downloads.sources.wd.requests.Session",
                return_value=FakeSession(),
            ),
            patch(
                "quasarr.downloads.sources.wd.detect_crypter_type",
                side_effect=lambda url: "filecrypt" if url == protected_url else None,
            ),
        ):
            result = WdSource().get_download_links(
                _build_shared_state({"wd": "host-wd.invalid"}),
                release_url,
                ["ddownload"],
                "Example.Release",
                None,
            )

        self.assertEqual(
            {"links": [[protected_url, "DDownload"]], "imdb_id": None},
            result,
        )
        self.assertEqual(
            [
                (release_url, True),
            ],
            requested_urls,
        )
        self.assertEqual(
            [
                (redirect_url, False),
                (cookie_url, False),
            ],
            redirect_requests,
        )

    def test_wd_rejects_non_redirect_success_page(self):
        release_url = "https://host-wd.invalid/release-blocked.html"
        redirect_url = "https://host-wd.invalid/redirect/blocked"

        page_html = (
            '<div class="card">'
            '<div class="card-header">Downloads</div>'
            '<div class="card-body">'
            '<a href="/redirect/blocked" class="background-ddownload">DDownload</a>'
            "</div>"
            "</div>"
        )

        def fake_get(url, headers=None, timeout=None, allow_redirects=True):
            if url == release_url:
                return FakeResponse(url=release_url, text=page_html)
            raise AssertionError(f"Unexpected URL requested: {url}")

        class FakeSession:
            def get(self, url, headers=None, timeout=None, allow_redirects=True):
                if url == redirect_url:
                    return FakeResponse(
                        url=redirect_url,
                        status_code=200,
                        text="<html><title>Blocked</title></html>",
                    )
                raise AssertionError(f"Unexpected URL requested: {url}")

        with (
            patch("quasarr.downloads.sources.wd.requests.get", side_effect=fake_get),
            patch(
                "quasarr.downloads.sources.wd.requests.Session",
                return_value=FakeSession(),
            ),
            patch(
                "quasarr.downloads.sources.wd.detect_crypter_type",
                return_value=None,
            ),
        ):
            result = WdSource().get_download_links(
                _build_shared_state({"wd": "host-wd.invalid"}),
                release_url,
                ["ddownload"],
                "Example.Release",
                None,
            )

        self.assertEqual({"links": [], "imdb_id": None}, result)


class ProtectedRedirectDownloadTests(unittest.TestCase):
    def _assert_download_stores_protected(
        self,
        source_key,
        source_obj,
        request_from,
        title,
        release_url,
        hostnames,
        patchers,
    ):
        shared_state = _build_shared_state(hostnames)
        notification_references = {
            "discord": {
                "message_id": "message-1",
                "webhook_fingerprint": "fingerprint",
                "case": "captcha",
                "silent": True,
            }
        }

        with ExitStack() as stack:
            stack.enter_context(patch("quasarr.downloads.mark_hostname_issue"))
            stack.enter_context(patch("quasarr.downloads.clear_hostname_issue"))
            stack.enter_context(
                patch("quasarr.downloads.download_category_exists", return_value=True)
            )
            mock_handle_direct = stack.enter_context(
                patch("quasarr.downloads.handle_direct_links")
            )
            stack.enter_context(
                patch(
                    "quasarr.downloads.send_tracked_notification",
                    return_value=notification_references,
                )
            )
            mock_store_protected = stack.enter_context(
                patch(
                    "quasarr.downloads.store_protected_links",
                    return_value={"success": True},
                )
            )
            stack.enter_context(
                patch(
                    "quasarr.downloads.filter_offline_links",
                    side_effect=lambda links, **_: links,
                )
            )
            stack.enter_context(
                patch(
                    "quasarr.downloads.get_download_category_mirrors", return_value=[]
                )
            )
            stack.enter_context(
                patch("quasarr.downloads.package_id_exists", return_value=False)
            )
            stack.enter_context(
                patch(
                    "quasarr.downloads.get_download_sources",
                    return_value={source_key: source_obj},
                )
            )

            for patcher in patchers:
                stack.enter_context(patcher)

            result = download(
                shared_state=shared_state,
                request_from=request_from,
                download_category="tv",
                title=title,
                url=release_url,
                size_mb=1024,
                password=None,
                imdb_id=None,
                source_key=source_key,
            )

        self.assertTrue(result["success"])
        self.assertNotIn("failed", result)
        mock_handle_direct.assert_not_called()
        mock_store_protected.assert_called_once()
        self.assertEqual(
            notification_references,
            mock_store_protected.call_args.kwargs["notifications"],
        )
        return mock_store_protected.call_args.args[1]

    def test_download_stores_by_protected_url(self):
        release_url = "https://host-by.invalid/release-2.html"
        iframe_url = "https://host-by.invalid/frame-2.html"
        go_url = "https://host-by.invalid/go.php?id=999"
        cookie_url = "https://host-by.invalid/step/needs-cookie-999"
        protected_url = "https://protected.invalid/container/by-999"

        release_html = f'<html><iframe src="{iframe_url}"></iframe></html>'
        iframe_html = f'<html><a href="{go_url}">DDownload</a></html>'

        def fake_get(url, headers=None, timeout=None, allow_redirects=True):
            if url == release_url:
                return FakeResponse(url=release_url, text=release_html)
            if url == iframe_url:
                return FakeResponse(url=iframe_url, text=iframe_html)
            raise AssertionError(f"Unexpected URL requested: {url}")

        class FakeSession:
            def __init__(self):
                self._saw_first_hop = False

            def get(self, url, headers=None, timeout=None, allow_redirects=True):
                if url == go_url:
                    self._saw_first_hop = True
                    return FakeResponse(
                        url=go_url,
                        status_code=302,
                        headers={"Location": cookie_url},
                    )
                if url == cookie_url:
                    if not self._saw_first_hop:
                        return FakeResponse(url=url, status_code=200, text="blocked")
                    return FakeResponse(
                        url=cookie_url,
                        status_code=302,
                        headers={"Location": protected_url},
                    )
                raise AssertionError(f"Unexpected URL requested: {url}")

        links = self._assert_download_stores_protected(
            source_key="by",
            source_obj=BySource(),
            request_from="Sonarr/4.0.0",
            title="Example.Release.S01.1080p-GRP",
            release_url=release_url,
            hostnames={"by": "host-by.invalid"},
            patchers=[
                patch(
                    "quasarr.downloads.sources.by.requests.get", side_effect=fake_get
                ),
                patch(
                    "quasarr.downloads.sources.by.requests.Session",
                    return_value=FakeSession(),
                ),
                patch(
                    "quasarr.downloads.sources.by.detect_crypter_type",
                    side_effect=lambda url: (
                        "filecrypt" if url == protected_url else None
                    ),
                ),
                patch(
                    "quasarr.downloads.detect_crypter",
                    side_effect=lambda url: (
                        ("filecrypt", "protected")
                        if url == protected_url
                        else (None, None)
                    ),
                ),
            ],
        )

        self.assertEqual([[protected_url, "filecrypt"]], links)

    def test_download_stores_nk_protected_url(self):
        release_url = "https://host-nk.invalid/release-2.html"
        go_url = "https://host-nk.invalid/go/4696/ddl.to"
        protected_url = "https://protected.invalid/container/nk-999"

        release_html = (
            '<html><a class="btn-orange" href="/go/4696/ddl.to">DDownload</a></html>'
        )

        class FakeSession:
            def get(self, url, headers=None, timeout=None, allow_redirects=True):
                if url == release_url:
                    return FakeResponse(url=release_url, text=release_html)
                if url == go_url:
                    return FakeResponse(
                        url=go_url,
                        status_code=302,
                        headers={"Location": protected_url},
                    )
                raise AssertionError(f"Unexpected URL requested: {url}")

        links = self._assert_download_stores_protected(
            source_key="nk",
            source_obj=NkSource(),
            request_from="Sonarr/4.0.0",
            title="Example.Release.S01.1080p-GRP",
            release_url=release_url,
            hostnames={"nk": "host-nk.invalid"},
            patchers=[
                patch(
                    "quasarr.downloads.sources.nk.requests.Session",
                    return_value=FakeSession(),
                ),
                patch(
                    "quasarr.downloads.sources.nk.detect_crypter_type",
                    side_effect=lambda url: (
                        "filecrypt" if url == protected_url else None
                    ),
                ),
                patch(
                    "quasarr.downloads.detect_crypter",
                    side_effect=lambda url: (
                        ("filecrypt", "protected")
                        if url == protected_url
                        else (None, None)
                    ),
                ),
            ],
        )

        self.assertEqual([[protected_url, "ddownload"]], links)

    def test_download_stores_sf_protected_url(self):
        release_url = "https://host-sf.invalid/external/2/abc123"
        cookie_url = "https://host-sf.invalid/step/needs-cookie-999"
        protected_url = "https://protected.invalid/container/sf-999"

        class FakeSession:
            def __init__(self):
                self._saw_first_hop = False

            def get(self, url, allow_redirects=False, timeout=None, headers=None):
                if url == release_url:
                    self._saw_first_hop = True
                    return FakeResponse(
                        url=release_url,
                        status_code=302,
                        headers={"Location": cookie_url},
                    )
                if url == cookie_url:
                    if not self._saw_first_hop:
                        return FakeResponse(url=url, status_code=200, text="blocked")
                    return FakeResponse(
                        url=cookie_url,
                        status_code=302,
                        headers={"Location": protected_url},
                    )
                raise AssertionError(f"Unexpected URL requested: {url}")

        links = self._assert_download_stores_protected(
            source_key="sf",
            source_obj=SfSource(),
            request_from="Sonarr/4.0.0",
            title="Example.Release.S01.1080p-GRP",
            release_url=release_url,
            hostnames={"sf": "host-sf.invalid"},
            patchers=[
                patch(
                    "quasarr.downloads.sources.sf.requests.Session",
                    return_value=FakeSession(),
                ),
                patch(
                    "quasarr.downloads.sources.sf.detect_crypter_type",
                    side_effect=lambda url: (
                        "filecrypt" if url == protected_url else None
                    ),
                ),
                patch(
                    "quasarr.downloads.detect_crypter",
                    side_effect=lambda url: (
                        ("filecrypt", "protected")
                        if url == protected_url
                        else (None, None)
                    ),
                ),
            ],
        )

        self.assertEqual([[protected_url, "filecrypt"]], links)

    def test_download_stores_wd_protected_url(self):
        release_url = "https://host-wd.invalid/release-2.html"
        redirect_url = "https://host-wd.invalid/redirect/xyz999"
        cookie_url = "https://host-wd.invalid/step/needs-cookie-999"
        protected_url = "https://protected.invalid/container/wd-999"

        page_html = (
            '<div class="card">'
            '<div class="card-header">Downloads</div>'
            '<div class="card-body">'
            '<a href="/redirect/xyz999" class="background-ddownload">DDownload</a>'
            "</div>"
            "</div>"
        )

        def fake_get(url, headers=None, timeout=None, allow_redirects=True):
            if url == release_url:
                return FakeResponse(url=release_url, text=page_html)
            raise AssertionError(f"Unexpected URL requested: {url}")

        class FakeSession:
            def __init__(self):
                self._saw_first_hop = False

            def get(self, url, headers=None, timeout=None, allow_redirects=True):
                if url == redirect_url:
                    self._saw_first_hop = True
                    return FakeResponse(
                        url=redirect_url,
                        status_code=302,
                        headers={"Location": cookie_url},
                    )
                if url == cookie_url:
                    if not self._saw_first_hop:
                        return FakeResponse(url=url, status_code=200, text="blocked")
                    return FakeResponse(
                        url=cookie_url,
                        status_code=302,
                        headers={"Location": protected_url},
                    )
                raise AssertionError(f"Unexpected URL requested: {url}")

        links = self._assert_download_stores_protected(
            source_key="wd",
            source_obj=WdSource(),
            request_from="Sonarr/4.0.0",
            title="Example.Release.S01.1080p-GRP",
            release_url=release_url,
            hostnames={"wd": "host-wd.invalid"},
            patchers=[
                patch(
                    "quasarr.downloads.sources.wd.requests.get", side_effect=fake_get
                ),
                patch(
                    "quasarr.downloads.sources.wd.requests.Session",
                    return_value=FakeSession(),
                ),
                patch(
                    "quasarr.downloads.sources.wd.detect_crypter_type",
                    side_effect=lambda url: (
                        "filecrypt" if url == protected_url else None
                    ),
                ),
                patch(
                    "quasarr.downloads.detect_crypter",
                    side_effect=lambda url: (
                        ("filecrypt", "protected")
                        if url == protected_url
                        else (None, None)
                    ),
                ),
            ],
        )

        self.assertEqual([[protected_url, "DDownload"]], links)


if __name__ == "__main__":
    unittest.main()
