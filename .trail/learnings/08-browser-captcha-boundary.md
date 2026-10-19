---
title: Solve protected crypters in the user browser
date: 2026-10-19
author: Quasarr
touches:
  - quasarr/downloads/linkcrypters/__init__.py
  - quasarr/api/captcha/__init__.py
  - quasarr/providers/web_server.py
---

## Decided

Keep CAPTCHA-protected crypter solving in the browser userscript flow and have Quasarr coordinate links, status, and callbacks.

Why: CAPTCHA challenges bind to browser context and user interaction. Server-side solving would duplicate browser state and turn source-specific challenge handling into a fragile backend service. The web API can expose the standardized flow while the browser performs the challenge.

## Watch out

Protected-queue callbacks preserve browser ownership; do not turn the browser crypter flow into a backend CAPTCHA service.
