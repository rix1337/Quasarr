---
title: Errors are only broken integrations and bugs; unreachable sites are warnings
author: Quasarr
date: 2026-11-03
touches:
  - quasarr/providers/statistics.py
  - quasarr/providers/hostname_issues.py
  - quasarr/api/statistics/chart.py
  - quasarr/providers/cloudflare.py
  - quasarr/search/sources/helpers/custom_source.py
  - quasarr/downloads/__init__.py
  - quasarr/downloads/sources/helpers/redirect.py
---

## Decided

ERROR, and with it the error log, the site error report and the red statistics line, is only for what Quasarr has to fix: a site integration that broke (changed layout, parser failure, 401/403, rejected login) or an unexpected exception. Everything the web does on its own is a warning: timeouts, dropped or refused connections, names that no longer resolve, HTTP 429/502/503/504 and Cloudflare's 520-524, rate limits, IP bans, FlareSolverr not answering or not solving, offline releases, and failed downloads. A missing Radarr/Sonarr or a misconfigured FlareSolverr is the user's setting, also a warning.

Sites that could not be reached go to `timeout:` rows (orange line, "Sites unreachable"), broken integrations to `issue:` rows (red line). A host with both on one day counts as an error only. The `timeout:` key predates the wider meaning and stays for stored history.

A failed download is an outcome, not a bug, so `fail()` always warns. A broken site is logged where its getter marks the issue; an unexpected exception in `download()` is logged as an error where it is caught.

filecrypt answers a banned IP with HTTP 200 on its 404 page; that is an IP ban, not an offline release. Only filecrypt does this: on any other crypter or site a 404 page means the page is gone. The ban comes and goes: in a live check on 2026-11-18 one release resolved again minutes later while another still hit the page.

Why: The error log and the report button exist to find bugs. Web failures there drowned them and sent users to report what nobody can fix; a dead domain is a hostname the user has to change.

The classification reads exception types, not message text: callers pass the exception itself to `mark_hostname_issue`, and a plain string is an issue Quasarr detected itself, always an error. Conditions without an exception pass `SiteUnreachableError`, or an `HTTPError` carrying the response. FlareSolverr failures raise `FlareSolverrError`, which stays a `RuntimeError` and `RequestException` for existing handlers. The template engine keeps the failed request's exception as the cause of its fetch result. Matching "timed out" in `str(e)` was replaced because it missed 52x, 503 and dropped connections.

## Watch out

`mark_hostname_issue` must never raise because failure handlers call it; the statistics write is wrapped. Never pass `str(e)` to it: the text loses the type and an unreachable site becomes an error. An `error()` log right before `mark_hostname_issue` writes the error log twice; log a warning there. The red line counts distinct sources with at least one integration issue that day, not events and not current state. Rows written before the split are all errors. The chart is native inline SVG; do not add external scripts.

In the code: `is_site_unreachable` in quasarr/providers/hostname_issues.py, `get_history` in quasarr/providers/statistics.py.
