---
title: Match releases by authoritative identity and pinned location
date: 2026-10-19
author: Quasarr
touches:
  - quasarr/search/sources/mx.py
  - quasarr/search/sources/wx.py
  - quasarr/downloads/sources/dl.py
---

## Decided

Require the strongest identity available at each source boundary: explicit IMDb equality for MX, episode-specific links before season packs for WX, and fragment-pinned posts for DL.

Why: Search order is not identity. The first API result may be a different title, a season pack can satisfy a broad query while missing the requested episode, and a thread can contain several unrelated posts. Matching the carried identifier or pinned fragment prevents false positives and prevents a fallback from widening scope.

## Watch out

Candidate order may optimize selection, but it cannot replace explicit identity or a requested post/episode constraint.
