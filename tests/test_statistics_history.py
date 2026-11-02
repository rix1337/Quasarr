# -*- coding: utf-8 -*-

import unittest
from datetime import date, timedelta
from unittest.mock import patch

from quasarr.providers.statistics import HISTORY_DAYS, StatsHelper


class FakeDb:
    def __init__(self, rows):
        self.rows = rows

    def retrieve(self, key):
        return self.rows.get(key)

    def store(self, key, value):
        self.rows[key] = value

    update_store = store

    def delete(self, key):
        self.rows.pop(key, None)

    def retrieve_all_titles(self):
        return [[k, v] for k, v in self.rows.items()] or None


class StatsHistoryTests(unittest.TestCase):
    def make_helper(self):
        rows = {}
        shared_state = type("S", (), {"values": {"database": lambda _t: FakeDb(rows)}})
        return StatsHelper(shared_state), rows

    def test_increment_bumps_today(self):
        helper, rows = self.make_helper()
        helper.increment_package_with_links(["a", "b"])
        helper.increment_failed_downloads()
        helper.increment_captcha_decryptions_manual()
        helper.increment_failed_decryptions_automatic()
        helper.increment_failed_decryptions_manual()
        with patch("quasarr.providers.statistics.record_configured_hostnames"):
            history = helper.get_history()

        self.assertEqual(len(history["days"]), HISTORY_DAYS)
        self.assertEqual(history["series"]["packages"][-1], 1)
        self.assertEqual(history["series"]["failed"][-1], 1)
        self.assertEqual(history["series"]["manual"][-1], 1)
        self.assertEqual(history["series"]["auto"][-1], 0)
        self.assertEqual(history["series"]["decrypt_failed"][-1], 2)

    def test_hostname_availability_series(self):
        helper, rows = self.make_helper()
        today = date.today().isoformat()
        rows[f"issue:{today}:xx"] = "1"
        rows[f"issue:{today}:yy"] = "1"
        with patch("quasarr.providers.statistics.record_configured_hostnames"):
            history = helper.get_history()

        self.assertEqual(history["issues"][-1], 2)
        self.assertEqual(history["issue_hosts"][-1], ["XX", "YY"])
        self.assertEqual(history["issue_hosts"][0], [])
        self.assertEqual(history["issues"][0], 0)
        self.assertEqual(history["hosts"], [0] * HISTORY_DAYS)

    def test_hostname_count_carries_forward(self):
        helper, rows = self.make_helper()
        start = (date.today() - timedelta(days=10)).isoformat()
        rows[f"hosts:{start}:n"] = "7"
        with patch("quasarr.providers.statistics.record_configured_hostnames"):
            history = helper.get_history()

        self.assertEqual(history["hosts"], [7] * HISTORY_DAYS)

    def test_old_rows_are_pruned(self):
        helper, rows = self.make_helper()
        old = (date.today() - timedelta(days=HISTORY_DAYS)).isoformat()
        rows[f"day:{old}:packages"] = "5"
        helper.increment_package_with_links(["a"])

        # first write of the day pruned it
        self.assertNotIn(f"day:{old}:packages", rows)
        self.assertIn(f"pruned:{date.today().isoformat()}", rows)

    def test_prune_runs_once_per_day(self):
        helper, rows = self.make_helper()
        helper.increment_failed_downloads()
        old = (date.today() - timedelta(days=HISTORY_DAYS)).isoformat()
        rows[f"day:{old}:packages"] = "5"
        helper.increment_failed_downloads()

        self.assertIn(f"day:{old}:packages", rows)

    def test_legacy_lifetime_counters_are_removed(self):
        rows = {"packages_downloaded": "9", "links_processed": "4"}
        shared_state = type("S", (), {"values": {"database": lambda _t: FakeDb(rows)}})
        StatsHelper(shared_state).prune()

        self.assertNotIn("packages_downloaded", rows)
        self.assertNotIn("links_processed", rows)


if __name__ == "__main__":
    unittest.main()
