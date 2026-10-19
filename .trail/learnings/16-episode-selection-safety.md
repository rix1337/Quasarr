---
title: Preserve native episode selection and raw season evidence
date: 2026-10-19
author: Quasarr
touches:
  - quasarr/downloads/sources/al.py
  - quasarr/downloads/sources/wx.py
  - quasarr/downloads/linkcrypters/hide.py
  - quasarr/downloads/__init__.py
---

## Decided

Carry requested season and episode identity to the source or crypter's native selector, preserve raw season signals until matching is complete, and fail closed when native confirmation is unavailable.

Why: Source rows can represent merged episodes, and container filenames can be randomized. Row position, guessed season text, or filename filtering can select the wrong content. Native selection plus explicit confirmation protects AL and Hide grabs; raw signals and precise fallbacks keep WX episode requests from widening into season packs.

## Watch out

An episode-specific grab never downloads an unconfirmed whole container, and fallback candidates retain enough source identity to be checked against the original request.
