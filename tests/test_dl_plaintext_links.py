# -*- coding: utf-8 -*-

import unittest

from bs4 import BeautifulSoup

from quasarr.downloads.sources.dl import (
    _extract_links_and_password_from_post,
    _extract_mirror_name_from_link,
)


class DlPlaintextLinksTests(unittest.TestCase):
    def test_extracts_hoster_from_domain_label_with_download_prefix(self):
        soup = BeautifulSoup(
            """
            <div>
                <a href="https://filecrypt.invalid/Container/one">Download via Rapidgator.net</a>
                <a href="https://filecrypt.invalid/Container/two">Download via DDownload.com</a>
                <a href="https://filecrypt.invalid/Container/three">rapidgator.net</a>
                <a href="https://filecrypt.invalid/Container/four">ddownload.com</a>
            </div>
            """,
            "html.parser",
        )

        self.assertEqual(
            [
                "rapidgator",
                "ddownload",
                "rapidgator",
                "ddownload",
            ],
            [_extract_mirror_name_from_link(link) for link in soup.select("a")],
        )

    def test_domain_labels_survive_requested_mirror_filter(self):
        links, _ = _extract_links_and_password_from_post(
            """
            <div>
                <a href="https://filecrypt.invalid/Container/one">Download via Rapidgator.net</a>
                <a href="https://filecrypt.invalid/Container/two">Download via DDownload.com</a>
            </div>
            """,
            "source.invalid",
            {"rapidgator", "ddownload"},
        )

        self.assertEqual(
            [
                ["https://filecrypt.invalid/Container/one", "rapidgator", None],
                ["https://filecrypt.invalid/Container/two", "ddownload", None],
            ],
            links,
        )

        selected_links, _ = _extract_links_and_password_from_post(
            """
            <div>
                <a href="https://filecrypt.invalid/Container/one">Download via Rapidgator.net</a>
                <a href="https://filecrypt.invalid/Container/two">Download via DDownload.com</a>
            </div>
            """,
            "source.invalid",
            {"rapidgator"},
        )
        self.assertEqual(
            [["https://filecrypt.invalid/Container/one", "rapidgator", None]],
            selected_links,
        )

    def test_url_label_keeps_nearby_hoster_detection(self):
        soup = BeautifulSoup(
            """
            <div>
                <b>Rapidgator</b>
                <a href="https://filecrypt.invalid/Container/one">
                    https://filecrypt.invalid/Container/one
                </a>
            </div>
            """,
            "html.parser",
        )

        self.assertEqual(
            "rapidgator", _extract_mirror_name_from_link(soup.select_one("a"))
        )

    def test_extracts_plaintext_crypter_urls_under_mirror_heading(self):
        post_html = """
            <div class="bbWrapper">
                <h3>RapidGator</h3>
                <div class="bbCodeBlock">
                    <div class="bbCodeBlock-title">Code:</div>
                    <code>https://keeplinks.invalid/p/example-token</code>
                </div>
                <div class="bbCodeBlock">
                    <div class="bbCodeBlock-title">Code:</div>
                    <code>https://filecrypt.invalid/Container/ABC123.html</code>
                </div>
                <h3>NitroFlare</h3>
                <div class="bbCodeBlock">
                    <div class="bbCodeBlock-title">Code:</div>
                    <code>https://keeplinks.invalid/p/other-token</code>
                </div>
            </div>
        """

        links, password = _extract_links_and_password_from_post(
            post_html,
            "source.invalid",
            {"rapidgator"},
        )

        self.assertEqual(
            [
                ["https://keeplinks.invalid/p/example-token", "rapidgator", None],
                [
                    "https://filecrypt.invalid/Container/ABC123.html",
                    "rapidgator",
                    None,
                ],
            ],
            links,
        )
        self.assertEqual("www.source.invalid", password)

    def test_extracts_plaintext_crypter_urls_without_mirror_filter(self):
        post_html = """
            <div class="bbWrapper">
                <b>RapidGator</b>
                <pre>https://keeplinks.invalid/p/example-token</pre>
                <b>NitroFlare</b>
                <pre>https://filecrypt.invalid/Container/DEF456.html</pre>
            </div>
        """

        links, _ = _extract_links_and_password_from_post(
            post_html,
            "source.invalid",
            set(),
        )

        self.assertEqual(
            [
                ["https://keeplinks.invalid/p/example-token", "rapidgator", None],
                [
                    "https://filecrypt.invalid/Container/DEF456.html",
                    "nitroflare",
                    None,
                ],
            ],
            links,
        )

    def test_skips_anchor_text_when_scanning_plaintext_crypter_urls(self):
        post_html = """
            <div class="bbWrapper">
                <b>RapidGator</b>
                <a href="https://filecrypt.invalid/Container/ABC123.html">
                    https://filecrypt.invalid/Container/ABC123.html
                </a>
            </div>
        """

        links, _ = _extract_links_and_password_from_post(
            post_html,
            "source.invalid",
            set(),
        )

        self.assertEqual(
            [["https://filecrypt.invalid/Container/ABC123.html", "rapidgator", None]],
            links,
        )

    def test_extracts_direct_hoster_urls(self):
        post_html = """
            <div class="bbWrapper">
                <a href="https://rapidgator.invalid/file/abc">Download</a>
                <a href="https://ddownload.invalid/example.pdf">Download</a>
                <a href="https://ddlto.invalid/example.pdf">Download</a>
                <a href="https://unknown.invalid/example.pdf">Unknown</a>
            </div>
        """

        links, password = _extract_links_and_password_from_post(
            post_html,
            "source.invalid",
            set(),
        )

        self.assertEqual(
            [
                ["https://rapidgator.invalid/file/abc", "rapidgator", None],
                ["https://ddownload.invalid/example.pdf", "ddownload", None],
                ["https://ddlto.invalid/example.pdf", "ddownload", None],
            ],
            links,
        )
        self.assertEqual("www.source.invalid", password)

    def test_extracts_plaintext_direct_hoster_urls(self):
        post_html = """
            <div class="bbWrapper">
                <b>DDownload</b>
                <pre>https://ddownload.invalid/example.pdf</pre>
                <b>Rapidgator</b>
                <pre>https://rapidgator.invalid/file/abc</pre>
            </div>
        """

        links, _ = _extract_links_and_password_from_post(
            post_html,
            "source.invalid",
            set(),
        )

        self.assertEqual(
            [
                ["https://ddownload.invalid/example.pdf", "ddownload", None],
                ["https://rapidgator.invalid/file/abc", "rapidgator", None],
            ],
            links,
        )


if __name__ == "__main__":
    unittest.main()
