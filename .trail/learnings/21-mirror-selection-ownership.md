---
title: Let source signals choose mirrors and JDownloader test liveness
date: 2026-10-19
author: Quasarr
touches:
  - quasarr/downloads/sources/wx.py
  - quasarr/downloads/__init__.py
  - quasarr/downloads/mirror_filters.py
---

## Decided

Prefer source-provided green container signals, pass the chosen link set to JDownloader, and let JDownloader own premium hoster verification.

Why: Direct probing cannot reliably distinguish a live premium link from a deleted file that still answers successfully. A green container signal remains the strongest available source evidence, even when resolving it may require CAPTCHA. Dead selections are deliberately reported through JDownloader failure so the *arr client can blacklist and retry. When source signals provide no usable recency or liveness evidence, the fallback may choose the first eligible option without pretending it was verified.

## Watch out

WX selection never merges unrelated mirror uploads or invents direct-link liveness; it preserves source evidence and hands terminal failures back to the *arr retry path.
