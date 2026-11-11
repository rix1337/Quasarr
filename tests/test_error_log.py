# -*- coding: utf-8 -*-

import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from quasarr.providers import log
from quasarr.providers.hostname_issues import mark_hostname_issue


class ErrorLogTests(unittest.TestCase):
    def setUp(self):
        config_dir = self.enterContext(tempfile.TemporaryDirectory())
        self.log_path = Path(config_dir) / "Quasarr.error.log"

    def test_file_keeps_only_errors_and_appends_after_reconfiguration(self):
        source_log = log.get_logger("quasarr.search.sources.xx")
        with patch.object(source_log, "level", 20), redirect_stdout(io.StringIO()):
            handler_id = log.configure_error_log(self.log_path.parent)
            try:
                source_log.info("Synthetic info")
                source_log.warn("Synthetic warning")
                source_log.error("<red>Synthetic error</red>")
            finally:
                log.logger.remove(handler_id)

            handler_id = log.configure_error_log(self.log_path.parent)
            try:
                source_log.crit("Synthetic critical failure")
            finally:
                log.logger.remove(handler_id)

        contents = self.log_path.read_text(encoding="utf-8")
        self.assertRegex(contents, r"ERROR.*XX.*Synthetic error")
        self.assertIn("Synthetic critical failure", contents)
        self.assertNotIn("Synthetic info", contents)
        self.assertNotIn("Synthetic warning", contents)
        self.assertNotIn("\x1b", contents)
        self.assertNotIn("<red>", contents)

    def test_worker_rotates_shared_log_and_keeps_console_filtered_errors(self):
        handler_id = log.configure_error_log(self.log_path.parent)
        self.addCleanup(log.logger.remove, handler_id)
        source_log = log.get_logger("quasarr.search.sources.xx")
        with redirect_stdout(io.StringIO()):
            source_log.crit("Synthetic error before rotation")

        worker = subprocess.run(
            [
                sys.executable,
                "-c",
                """
import sys
from quasarr.providers import log

log._error_log_max_bytes = int(sys.argv[2])
log.configure_error_log(sys.argv[1])
source_log = log.get_logger("quasarr.search.sources.xx")
source_log.level = 50
source_log.error("Synthetic worker error")
""",
                str(self.log_path.parent),
                str(self.log_path.stat().st_size),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        with redirect_stdout(io.StringIO()):
            source_log.crit("Synthetic error after rotation")

        backup = self.log_path.with_suffix(".log.1").read_text(encoding="utf-8")
        current = self.log_path.read_text(encoding="utf-8")
        self.assertIn("Synthetic error before rotation", backup)
        self.assertIn("Synthetic worker error", current)
        self.assertIn("Synthetic error after rotation", current)
        self.assertNotIn("Synthetic worker error", worker.stdout)

    def test_records_reason_for_statistics_error_in_file(self):
        handler_id = log.configure_error_log(self.log_path.parent)
        self.addCleanup(log.logger.remove, handler_id)

        stdout = io.StringIO()
        with (
            redirect_stdout(stdout),
            patch(
                "quasarr.providers.hostname_issues._get_db", return_value=MagicMock()
            ),
            patch("quasarr.providers.hostname_issues.record_configured_hostnames"),
        ):
            mark_hostname_issue("xx", "search", "Unexpected response format")
            mark_hostname_issue("xx", "feed", "Read timed out")

        contents = self.log_path.read_text(encoding="utf-8")
        self.assertRegex(contents, r"XX.*search.*Unexpected response format")
        self.assertNotIn("Read timed out", contents)
        self.assertNotIn("Unexpected response format", stdout.getvalue())
