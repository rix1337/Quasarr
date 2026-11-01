---
title: Resolve Filecrypt Go links by navigating the solving browser tab
author: Quasarr
date: 2026-10-31
touches:
  - quasarr/providers/obfuscated.py
---

## Decided

Filecrypt serves Go links behind a Cloudflare managed challenge. The same Go request passes with the browser's cookies and receives HTTP 403 with `cf-mitigated: challenge` without them. The clearance cookie is HttpOnly, and userscript background requests do not carry the tab's session, so the Filecrypt helper never requests Go links in the background. It stores a short-lived handoff in userscript storage and navigates its own tab to the Go URL. The browser passes the challenge and follows the redirect, the helper on the hoster page writes that URL into the handoff and returns to the Link page, which shows the link and transfers it. SponsorsHelper follows Go links through its existing FlareSolverr session, which shares Filecrypt session cookies with its request session.

## Tried and ruled out

Retrying the background request after loading the Go URL in a hidden same-origin frame. The browser already holds clearance, but the background request never sends it, so every retry stays challenged.

## Watch out

Go links are bound to the Filecrypt session that unlocked the container; another browser session receives a session-expired page. The helper must not run on Go pages, because its script blocker would break the Cloudflare challenge. Hoster domains need `@match` entries for the handoff; the helper reports only from the top frame and only for a fresh, unconsumed handoff.
