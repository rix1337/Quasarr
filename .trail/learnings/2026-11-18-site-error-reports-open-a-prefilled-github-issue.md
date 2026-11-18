---
title: Site error reports open a prefilled GitHub issue
author: Quasarr
date: 2026-11-18
touches:
  - quasarr/providers/error_report.py
  - quasarr/providers/log.py
  - quasarr/api/statistics/__init__.py
  - .github/ISSUE_TEMPLATE/bug_report.yml
---

## Decided

The statistics page reports site errors through a link to the bug report form, prefilled by query parameters. The user's browser opens it and the user reviews and submits it, so Quasarr needs no GitHub token and sends nothing by itself. The button only shows when the error log holds site errors of the running version.

Every error log line names the version after the time, so a report sends only the running version's errors. The file has no colors, so level, context and site are joined by slashes, as `ERROR/WD`. A site error is a line written by `log_source_issue`: no context, only the site key after the level.

The report keeps the newest whole lines that fit and names how many earlier ones did not. Configured hostnames and their subdomains become the site key (`[WD]`), any other URL host `<host>`, IPv4 addresses `<ip>`. The ini file is sent as sections and keys only, values marked `<set>`, which shows the setup without sending encrypted secrets.

Why: Blank issues are disabled, so the link must name the bug report template, and issue forms only prefill fields that have an `id`. The required checkboxes and the site-kind dropdown stay for the user, since they are the user's own confirmations.

## Watch out

GitHub answered HTTP 500 for issue links from about 7,100 characters in November 2026, so the link stays under 6,000. Form field ids only take effect once the template is on the default branch. Changing the error log line shape breaks `read_site_errors`; change both together.
