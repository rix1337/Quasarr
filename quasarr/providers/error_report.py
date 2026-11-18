# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""A prefilled GitHub issue with this version's site errors, hostnames anonymized."""

import configparser
import os
import platform
import re
import sys
from urllib.parse import urlencode

from quasarr.providers.log import error_log_path
from quasarr.providers.version import __version__

ISSUE_URL = "https://github.com/rix1337/Quasarr/issues/new"
# GitHub answered 500 from about 7,100 characters in Nov 2026; keep a margin
MAX_ISSUE_URL_LENGTH = 6000

_URL_HOST = re.compile(r"(https?://)(?!\[)[^/\s'\"?#]+")
_HOST_ARGUMENT = re.compile(r"host='(?!\[)[^']*'")
_IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


def _site_error_line(version):
    # written by log_source_issue: no context, the site's key right after the level
    return re.compile(rf"^\S+ v{re.escape(version)} ERROR/[A-Z0-9]+ ")


def read_site_errors(config_path, version=__version__):
    """This version's site error lines, oldest first, across the rotated log."""
    path = error_log_path(config_path)
    is_site_error = _site_error_line(version)
    lines = []
    for log_file in (path.with_suffix(".log.1"), path):
        try:
            text = log_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines += [line for line in text.splitlines() if is_site_error.match(line)]
    return lines


def anonymize(line, hostnames):
    """Replace configured hostnames by their key, any other host and IP by a placeholder."""
    for key, hostname in sorted(hostnames.items(), key=lambda item: -len(item[1])):
        # subdomains such as www. belong to the site
        pattern = r"(?:[\w-]+\.)*" + re.escape(hostname)
        line = re.sub(pattern, f"[{key.upper()}]", line, flags=re.I)
    line = _URL_HOST.sub(r"\1<host>", line)
    line = _HOST_ARGUMENT.sub("host='<host>'", line)
    return _IPV4.sub("<ip>", line)


def _environment(version):
    if os.environ.get("DOCKER"):
        kind, system = "Docker", "Docker"
    else:
        kind = "Windows-Exe" if getattr(sys, "frozen", False) else "Manual"
        system = {"Darwin": "macOS"}.get(platform.system(), platform.system())
    return (
        f"- Quasarr version: {version}\n- Last working version:\n"
        f"- Type: {kind}\n- OS: {system}"
    )


def redacted_ini(configfile):
    """Quasarr.ini's sections and keys, values only marked as set."""
    config = configparser.RawConfigParser()
    try:
        config.read(configfile, encoding="utf-8")
    except (OSError, configparser.Error):
        return ""
    sections = []
    for section in config.sections():
        keys = [
            f"{key} = {'<set>' if value else ''}".rstrip()
            for key, value in config.items(section)
        ]
        sections.append("\n".join([f"[{section}]", *keys]))
    return "\n\n".join(sections)


def _issue_url(lines, omitted, version, ini):
    note = f" {omitted} earlier lines did not fit into the link." if omitted else ""
    fields = {
        # blank issues are disabled; the form's field ids take the prefill
        "template": "bug_report.yml",
        "title": f"Site errors in v{version}",
        "environment": _environment(version),
        "description": (
            f"Quasarr v{version} logged these site errors. "
            f"Hostnames are replaced by their site key.{note}"
        ),
        "logs": "\n".join(lines),
        "ini": ini,
    }
    return f"{ISSUE_URL}?{urlencode(fields)}"


def site_error_issue_url(config_path, hostnames, configfile, version=__version__):
    """The issue URL with as many whole lines as fit, newest kept; None without errors."""
    lines = [
        anonymize(line, hostnames) for line in read_site_errors(config_path, version)
    ]
    if not lines:
        return None
    ini = anonymize(redacted_ini(configfile), hostnames)
    kept = []
    for line in reversed(lines):
        candidate = [line] + kept
        omitted = len(lines) - len(candidate)
        if len(_issue_url(candidate, omitted, version, ini)) > MAX_ISSUE_URL_LENGTH:
            break
        kept = candidate
    return _issue_url(kept, len(lines) - len(kept), version, ini)
