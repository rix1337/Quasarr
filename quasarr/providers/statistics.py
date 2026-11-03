# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from datetime import date, timedelta
from typing import Any, Dict

from quasarr.providers.hostname_issues import record_configured_hostnames

HISTORY_DAYS = 30
# counter name -> chart series; each increment bumps today's row
HISTORY_METRICS = {
    "packages_downloaded": "packages",
    "failed_downloads": "failed",
    "captcha_decryptions_automatic": "auto",
    "captcha_decryptions_manual": "manual",
    "failed_decryptions_automatic": "decrypt_failed",
    "failed_decryptions_manual": "decrypt_failed",
}


ROW_KINDS = ("day", "issue", "timeout", "hosts", "pruned", "failedpkg")
ROW_PREFIXES = tuple(f"{kind}:" for kind in ROW_KINDS)

# lifetime counters from before the per-day history; dropped by the first prune
LEGACY_KEYS = (
    "packages_downloaded",
    "links_processed",
    "captcha_decryptions_automatic",
    "captcha_decryptions_manual",
    "failed_downloads",
    "failed_decryptions_automatic",
    "failed_decryptions_manual",
)


def prune_daily(db):
    """On the first call of each day, drop expired rows and pre-history lifetime counters"""
    today = date.today()
    marker = f"pruned:{today.isoformat()}"
    if db.retrieve(marker) is not None:
        return

    for key in LEGACY_KEYS:
        db.delete(key)

    cutoff = (today - timedelta(days=HISTORY_DAYS - 1)).isoformat()
    for key, value in db.retrieve_all_titles() or []:
        parts = key.split(":")
        # failedpkg rows are keyed by package id and carry their date as the value
        stamp = value if parts[0] == "failedpkg" else parts[1] if len(parts) > 1 else ""
        if parts[0] in ROW_KINDS and stamp and stamp < cutoff:
            db.delete(key)
    db.update_store(marker, "1")

    # one snapshot per day even when the hostname config never changes
    try:
        record_configured_hostnames()
    except Exception:
        pass


class StatsHelper:
    """
    Multiprocessing-safe stats helper using separate per-day rows.
    Uses shared_state for database access across processes.
    """

    def __init__(self, shared_state):
        self.shared_state = shared_state

    def _get_db(self):
        """Get database interface through shared_state"""
        return self.shared_state.values["database"]("statistics")

    def _increment_stat(self, key: str, count: int = 1):
        """Process-safe increment of today's row for a tracked counter"""
        metric = HISTORY_METRICS.get(key)
        if not metric:
            return
        db = self._get_db()
        prune_daily(db)
        day_key = f"day:{date.today().isoformat()}:{metric}"
        try:
            current = int(db.retrieve(day_key) or 0)
        except ValueError:
            current = 0
        db.update_store(day_key, str(current + count))

    def record_failed_package(self, package_id):
        """Count a package in an error state once, however often it is polled"""
        db = self._get_db()
        prune_daily(db)
        key = f"failedpkg:{package_id}"
        if db.retrieve(key) is not None:
            return
        db.store(key, date.today().isoformat())
        self._increment_stat("failed_downloads")

    def prune(self):
        prune_daily(self._get_db())

    def get_history(self) -> Dict[str, Any]:
        """Per-day counts for the last HISTORY_DAYS days"""
        today = date.today()
        days = [
            (today - timedelta(days=offset)).isoformat()
            for offset in range(HISTORY_DAYS - 1, -1, -1)
        ]

        self.prune()
        try:
            record_configured_hostnames()
        except Exception:
            pass

        db = self._get_db()
        counts = {}
        for key, value in db.retrieve_all_titles() or []:
            if not key.startswith(ROW_PREFIXES):
                continue
            try:
                kind, day, name = key.split(":")
                counts[(kind, day, name)] = int(value)
            except ValueError:
                continue

        # hostname count only changes on config edits: carry the last snapshot forward,
        # but leave days before the first snapshot empty rather than guessing
        hosts = []
        last = None
        for day in days:
            last = counts.get(("hosts", day, "n"), last)
            hosts.append(last)

        def hosts_with(kind, day):
            return {k[2].upper() for k in counts if k[0] == kind and k[1] == day}

        # a host with both errors and timeouts on one day counts as an error only
        issue_hosts = [sorted(hosts_with("issue", day)) for day in days]
        timeout_hosts = [
            sorted(hosts_with("timeout", day) - hosts_with("issue", day))
            for day in days
        ]

        return {
            "days": days,
            "series": {
                metric: [counts.get(("day", day, metric), 0) for day in days]
                for metric in set(HISTORY_METRICS.values())
            },
            "hosts": hosts,
            "issues": [len(names) for names in issue_hosts],
            "issue_hosts": issue_hosts,
            "timeouts": [len(names) for names in timeout_hosts],
            "timeout_hosts": timeout_hosts,
        }

    def increment_package_with_links(self, links):
        """Increment package downloaded for one package, or failed download if no links

        Args:
            links: Can be:
                - list/array: counts the length
                - int: uses the value directly
                - None/False/empty: treats as failed download
        """
        # Handle different input types
        if links is None or links is False:
            link_count = 0
        elif isinstance(links, (list, tuple)):
            link_count = len(links)
        elif isinstance(links, int):
            link_count = links
        else:
            # Handle other falsy values or unexpected types
            try:
                link_count = int(links) if links else 0
            except (ValueError, TypeError):
                link_count = 0

        # Now handle the actual increment logic
        if link_count == 0:
            self._increment_stat("failed_downloads", 1)
        else:
            self._increment_stat("packages_downloaded", 1)
            self._increment_stat("links_processed", link_count)

    def increment_captcha_decryptions_automatic(self):
        """Increment automatic captcha decryptions counter"""
        self._increment_stat("captcha_decryptions_automatic", 1)

    def increment_captcha_decryptions_manual(self):
        """Increment manual captcha decryptions counter"""
        self._increment_stat("captcha_decryptions_manual", 1)

    def increment_failed_downloads(self):
        """Increment failed downloads counter"""
        self._increment_stat("failed_downloads", 1)

    def increment_failed_decryptions_automatic(self):
        """Increment failed automatic decryptions counter"""
        self._increment_stat("failed_decryptions_automatic", 1)

    def increment_failed_decryptions_manual(self):
        """Increment failed manual decryptions counter"""
        self._increment_stat("failed_decryptions_manual", 1)
