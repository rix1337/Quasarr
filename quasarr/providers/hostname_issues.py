# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""
Hostname Issues Tracker - Uses lazy imports to avoid circular dependency
"""

import json
from datetime import date, datetime

import requests
from urllib3.exceptions import NameResolutionError

from quasarr.providers.log import log_source_issue

# Overloaded or rate-limiting sites, including Cloudflare's origin errors (52x).
# 401 and 403 are not here: a rejected login or blocked request is a broken integration.
UNREACHABLE_HTTP_STATUSES = frozenset({429, 502, 503, 504, 520, 521, 522, 523, 524})


class SiteUnreachableError(Exception):
    """The site could not be reached or served: an IP ban, a rate limit, or
    FlareSolverr not solving in time. Not something Quasarr can fix."""


def _get_db(table_name):
    """Lazy import to avoid circular dependency."""
    from quasarr.storage.sqlite_database import DataBase

    return DataBase(table_name)


def is_site_unreachable(error):
    """Whether a failure is the web's, not a broken integration or a bug.

    Classifies by type, never by message text. A plain string describes an
    issue Quasarr detected itself, which is always an error.
    """
    if isinstance(error, (SiteUnreachableError, requests.Timeout)):
        return True
    if isinstance(error, requests.HTTPError):
        response = error.response
        return (
            response is not None and response.status_code in UNREACHABLE_HTTP_STATUSES
        )
    # includes names that no longer resolve: a dead domain is the user's setting
    return isinstance(error, requests.ConnectionError)


def is_unresolved_name(error):
    """Whether a connection failed because the hostname does not resolve."""
    reason = error.args[0] if error.args else None
    return isinstance(getattr(reason, "reason", reason), NameResolutionError)


def mark_hostname_issue(shorthand, operation, error):
    """Record a source failure; ``error`` is the exception or a description."""
    shorthand = shorthand.lower()
    message = str(error) or type(error).__name__
    unreachable = is_site_unreachable(error)
    if not unreachable:
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
        # "timeout" rows predate the wider meaning; the key stays for stored history
        kind = "timeout" if unreachable else "issue"
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
