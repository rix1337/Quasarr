# -*- coding: utf-8 -*-

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from quasarr.providers import hostname_issues
from quasarr.search.sources.helpers import custom_suggest


class TrialStateTests(unittest.TestCase):
    def setUp(self):
        self.saved = MagicMock()
        self.sessions = MagicMock()
        self.real = SimpleNamespace(
            values={
                "config": lambda _section: self.saved,
                "database": lambda _table: self.sessions,
                "user_agent": "UA/1.0",
            },
            get_db=lambda table: f"db:{table}",
        )
        self.trial = custom_suggest._TrialState(self.real, "xx", "site.invalid")

    def test_the_pasted_hostname_stands_in_for_its_site_only(self):
        self.saved.get.return_value = "other.invalid"
        hostnames = self.trial.values["config"]("Hostnames")
        self.assertEqual("site.invalid", hostnames.get("xx"))
        self.assertEqual("other.invalid", hostnames.get("yy"))
        # any other section only reads the saved settings, as a saved login
        self.assertEqual("other.invalid", self.trial.values["config"]("XX").get("xx"))

    def test_a_failed_trial_login_never_changes_the_saved_one(self):
        login = self.trial.values["config"]("XX")
        login.save("user", "")
        login.delete("password")
        self.saved.save.assert_not_called()
        self.saved.delete.assert_not_called()

    def test_sessions_stay_in_memory(self):
        sessions = self.trial.values["database"]("sessions")
        sessions.update_store("xx", "token")
        self.assertEqual("token", sessions.retrieve("xx"))
        self.sessions.update_store.assert_not_called()
        self.assertEqual("db:other", self.trial.get_db("other"))

    def test_trials_record_no_hostname_issues(self):
        with (
            patch.object(hostname_issues, "_get_db") as db,
            hostname_issues.quiet_hostname_issues(),
        ):
            hostname_issues.mark_hostname_issue("xx", "feed", "Synthetic")
            hostname_issues.clear_hostname_issue("xx")
        db.assert_not_called()


class DetectionOrderTests(unittest.TestCase):
    def _templates(self):
        def source(name, login):
            return SimpleNamespace(name=name, requires_login=login, spec={"feeds": {}})

        return {"ab": source("AB", False), "ba": source("BA", True)}

    def _detect(self, read):
        tried = []

        def trial(_state, key, _hostname):
            tried.append(key)
            return read.get(key, 0)

        with (
            patch(
                "quasarr.search.sources.templates.get_templates",
                return_value=self._templates(),
            ),
            patch.object(custom_suggest, "_template_rows", return_value=0),
            patch.object(custom_suggest, "trial_feed_rows", side_effect=trial),
        ):
            found = custom_suggest.detect_templates(
                None, "", "https://ab.invalid/", "ab.invalid"
            )
        return [match["key"] for match in found], tried

    def test_a_site_without_login_spares_the_saved_logins(self):
        found, tried = self._detect({"ab": 5, "ba": 5})
        self.assertEqual(["AB"], found)
        self.assertEqual(["ab"], tried)

    def test_login_sites_are_tried_when_nothing_else_reads_it(self):
        found, tried = self._detect({"ba": 2})
        self.assertEqual(["BA"], found)
        self.assertEqual(["ab", "ba"], sorted(tried))


if __name__ == "__main__":
    unittest.main()
