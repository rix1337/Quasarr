---
title: RM reads the server-rendered site, not a JSON API
date: 2026-11-02
author: Quasarr
touches:
  - quasarr/search/sources/rm.py
  - quasarr/downloads/sources/rm.py
---

## Decided

RM talks to whichever mirror is configured, as configured, and reads its HTML pages: the front page for the feed, a title page (all releases of one production) for IMDb searches, the paged release search for phrase searches, and the release page for plain-text download links.

Why: The earlier JSON API only existed on one mirror and forced a host prefix onto the configured domain, so every other mirror broke. The working mirrors are server-rendered and answer IMDb IDs in their search box, which makes a title lookup unnecessary.

## Watch out

Search lists carry no date, so searches report the current time; feed posts carry a calendar date without a time, title pages an approximate age. One upload is mirrored on several domains of a hoster, so a file counts once per hoster and path. A 404 release page is a removed release, not a hostname issue. A mirror whose pages lack the expected markup is reported as a hostname issue instead of passing as an empty site.
