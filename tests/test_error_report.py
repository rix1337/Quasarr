# -*- coding: utf-8 -*-

import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from quasarr.providers import error_report
from quasarr.providers.error_report import (
    MAX_ISSUE_URL_LENGTH,
    read_site_errors,
    site_error_issue_url,
)

HOSTNAMES = {"xx": "source.invalid"}


def _site_line(version, index):
    return (
        f"2026-01-01T00:00:{index % 60:02d} v{version} ERROR/XX search: "
        f"403 Client Error: Forbidden for url: https://www.source.invalid/?q={index}"
    )


class ErrorReportTests(unittest.TestCase):
    def setUp(self):
        self.config_dir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.configfile = self.config_dir / "Quasarr.ini"
        self.configfile.write_text(
            "[Hostnames]\nxx = encrypted\nyy =\n\n[FlareSolverr]\nurl = encrypted\n",
            encoding="utf-8",
        )

    def _write_log(self, lines):
        (self.config_dir / "Quasarr.error.log").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

    def _fields(self, url):
        return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}

    def test_reports_only_this_versions_site_errors_anonymized(self):
        self._write_log(
            [
                _site_line("0.0.1", 1),
                "2026-01-01T00:00:02 v9.9.9 ERROR/📥 Reason for failure: Synthetic",
                "2026-01-01T00:00:03 v9.9.9 ERROR/YY feed: Request failed: "
                "HTTPSConnectionPool(host='other.invalid', port=443) via 10.0.0.1",
                _site_line("9.9.9", 4),
            ]
        )

        fields = self._fields(
            site_error_issue_url(self.config_dir, HOSTNAMES, self.configfile, "9.9.9")
        )

        self.assertEqual("bug_report.yml", fields["template"])
        self.assertIn("Quasarr version: 9.9.9", fields["environment"])
        self.assertEqual(
            "2026-01-01T00:00:03 v9.9.9 ERROR/YY feed: Request failed: "
            "HTTPSConnectionPool(host='<host>', port=443) via <ip>\n"
            "2026-01-01T00:00:04 v9.9.9 ERROR/XX search: 403 Client Error: "
            "Forbidden for url: https://[XX]/?q=4",
            fields["logs"],
        )
        self.assertEqual(
            "[Hostnames]\nxx = <set>\nyy =\n\n[FlareSolverr]\nurl = <set>",
            fields["ini"],
        )
        self.assertNotIn("source.invalid", fields["logs"] + fields["ini"])

    def test_keeps_newest_whole_lines_within_url_limit(self):
        lines = [_site_line("9.9.9", index) for index in range(500)]
        self._write_log(lines)

        url = site_error_issue_url(self.config_dir, HOSTNAMES, self.configfile, "9.9.9")

        self.assertLessEqual(len(url), MAX_ISSUE_URL_LENGTH)
        logged = self._fields(url)["logs"].split("\n")
        anonymized = [error_report.anonymize(line, HOSTNAMES) for line in lines]
        self.assertEqual(anonymized[-len(logged) :], logged)
        self.assertIn(
            f"{500 - len(logged)} earlier lines", self._fields(url)["description"]
        )

    def test_no_report_without_errors_of_this_version(self):
        self._write_log([_site_line("0.0.1", 1)])

        self.assertEqual([], read_site_errors(self.config_dir, "9.9.9"))
        self.assertIsNone(
            site_error_issue_url(self.config_dir, HOSTNAMES, self.configfile, "9.9.9")
        )


if __name__ == "__main__":
    unittest.main()
