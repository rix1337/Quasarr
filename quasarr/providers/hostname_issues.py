# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""
Hostname Issues Tracker - Uses lazy imports to avoid circular dependency
"""

import json
from datetime import datetime


def _get_db(table_name):
    """Lazy import to avoid circular dependency."""
    from quasarr.storage.sqlite_database import DataBase

    return DataBase(table_name)


def mark_hostname_issue(shorthand, operation, error_message):
    shorthand = shorthand.lower()
    db = _get_db("hostname_issues")

    issue_data = {
        "operation": operation,
        "error": str(error_message)[:500],
        "timestamp": datetime.now().isoformat(),
    }

    db.update_store(shorthand, json.dumps(issue_data))


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
