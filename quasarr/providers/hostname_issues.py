# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""
Hostname Issues Tracker - Uses lazy imports to avoid circular dependency
"""

import json
from datetime import date, datetime

from quasarr.providers.log import log_source_issue


def _get_db(table_name):
    """Lazy import to avoid circular dependency."""
    from quasarr.storage.sqlite_database import DataBase

    return DataBase(table_name)


def is_timeout_message(error_message):
    """Timeouts are slow hosts, not broken ones; the statistics chart keeps them apart."""
    message = str(error_message).lower()
    return "timed out" in message or "timeout" in message


def mark_hostname_issue(shorthand, operation, error_message):
    shorthand = shorthand.lower()
    message = str(error_message)
    is_timeout = is_timeout_message(message)
    if not is_timeout:
        log_source_issue(shorthand, operation, message)

    db = _get_db("hostname_issues")

    issue_data = {
        "operation": operation,
        "error": message[:500],
        "timestamp": datetime.now().isoformat(),
    }

    db.update_store(shorthand, json.dumps(issue_data))

    # marks the day as affected for the statistics chart; must never break callers
    try:
        from quasarr.providers.statistics import prune_daily

        stats_db = _get_db("statistics")
        prune_daily(stats_db)
        kind = "timeout" if is_timeout else "issue"
        stats_db.update_store(f"{kind}:{date.today().isoformat()}:{shorthand}", "1")
        record_configured_hostnames(refresh=False)
    except Exception:
        pass


def record_configured_hostnames(refresh=True):
    """Snapshot today's configured hostname count for the statistics chart.

    refresh=False keeps an existing snapshot so frequent issue marks stay cheap.
    """
    from quasarr.search.sources.helpers import get_hostnames
    from quasarr.storage.config import Config

    stats_db = _get_db("statistics")
    day_key = f"hosts:{date.today().isoformat()}:n"
    if not refresh and stats_db.retrieve(day_key) is not None:
        return

    config = Config("Hostnames")
    count = sum(1 for name in get_hostnames() if config.get(name))
    stats_db.update_store(f"hosts:{date.today().isoformat()}:n", str(count))


def clear_hostname_issue(shorthand):
    shorthand = shorthand.lower()
    db = _get_db("hostname_issues")
    db.delete(shorthand)


def get_hostname_issue(shorthand):
    shorthand = shorthand.lower()
    db = _get_db("hostname_issues")
    data = db.retrieve(shorthand)

    if data:
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return None
    return None


def get_all_hostname_issues():
    db = _get_db("hostname_issues")
    all_data = db.retrieve_all_titles()

    issues = {}
    if all_data:
        for shorthand, data in all_data:
            try:
                issues[shorthand] = json.loads(data)
            except json.JSONDecodeError:
                continue

    return issues


def clear_all_hostname_issues():
    db = _get_db("hostname_issues")
    all_data = db.retrieve_all_titles() or []
    for shorthand, _data in all_data:
        db.delete(shorthand)
    return len(all_data)
