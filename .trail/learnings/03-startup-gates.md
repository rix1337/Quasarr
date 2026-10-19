---
title: Gate application startup through ordered setup
date: 2026-10-19
author: Quasarr
touches:
  - quasarr/__init__.py
  - quasarr/storage/setup/__init__.py
---

## Decided

Keep prerequisite setup blocking and separate from the main API.

Why: Later checks depend on persisted configuration and verified services. Temporary setup servers collect prerequisites without exposing a partially initialized application. Required JDownloader setup cannot be skipped because Quasarr cannot fulfill grabs without it.

## Watch out

API serving starts only after required gates finish; skippable prerequisites record explicit skip state and required JDownloader setup cannot be skipped.
