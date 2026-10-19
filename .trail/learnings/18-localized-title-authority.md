---
title: Use authoritative localized titles once at the metadata boundary
date: 2026-10-19
author: Quasarr
touches:
  - quasarr/providers/imdb_metadata.py
  - quasarr/search/sources/mx.py
  - quasarr/search/sources/wx.py
---

## Decided

Resolve a source-language title only from evidence that proves the requested locale, then apply shared transliteration once before source queries.

Why: Original titles and instance-localized display names can look plausible while naming a different spelling. Unproven fallbacks create silent misses or wrong matches. Central normalization gives every source the same German transliteration behavior and avoids source-specific spelling retries.

## Watch out

A source receives one canonical localized form or no title; individual source modules must not invent locale fallbacks or alternate transliteration rules.
