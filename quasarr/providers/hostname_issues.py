# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""
Hostname Issues Tracker

Tracks exceptions/errors for each hostname source during operations.
Used to display traffic light indicators in the hostnames UI.

Traffic Light Logic:
- 🟢 Green: Hostname is set and no recent issues
- 🟡 Yellow: Hostname is unset OR login was skipped
- 🔴 Red: Hostname is set but has a recent exception

Operation Types:
- 'feed'     - RSS/feed loading errors in search sources
- 'search'   - Search query errors in search sources
- 'download' - Download link retrieval errors
- 'session'  - Login/session creation failures (credentials invalid, session expired)

The module stores issues in the database with the operation type
so users can understand what went wrong.
"""

import json
from datetime import datetime

from quasarr.providers.log import debug
from quasarr.storage.sqlite_database import DataBase


def mark_hostname_issue(shorthand, operation, error_message):
    """
    Mark a hostname as having an issue during an operation.

    Args:
        shorthand: Two-letter hostname code (e.g., 'al', 'dd')
        operation: Type of operation ('feed', 'search', 'download')
        error_message: The exception message
    """
    shorthand = shorthand.lower()
    db = DataBase("hostname_issues")

    issue_data = {
        "operation": operation,
        "error": str(error_message)[:500],  # Truncate long errors
        "timestamp": datetime.now().isoformat()
    }

    db.update_store(shorthand, json.dumps(issue_data))
    debug(f"Marked {shorthand.upper()} with issue during {operation}: {error_message}")


def clear_hostname_issue(shorthand):
    """
    Clear any issue for a hostname (called on successful operation).

    Args:
        shorthand: Two-letter hostname code (e.g., 'al', 'dd')
    """
    shorthand = shorthand.lower()
    db = DataBase("hostname_issues")
    db.delete(shorthand)
    debug(f"Cleared issue for {shorthand.upper()}")


def get_hostname_issue(shorthand):
    """
    Get the current issue for a hostname, if any.

    Args:
        shorthand: Two-letter hostname code (e.g., 'al', 'dd')

    Returns:
        dict with 'operation', 'error', 'timestamp' or None if no issue
    """
    shorthand = shorthand.lower()
    db = DataBase("hostname_issues")
    data = db.retrieve(shorthand)

    if data:
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return None
    return None


def get_all_hostname_issues():
    """
    Get all current hostname issues.

    Returns:
        dict mapping shorthand to issue data
    """
    db = DataBase("hostname_issues")
    all_data = db.retrieve_all_titles()

    issues = {}
    if all_data:
        for shorthand, data in all_data:
            try:
                issues[shorthand] = json.loads(data)
            except json.JSONDecodeError:
                continue

    return issues
