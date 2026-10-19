---
title: Separate category identity from search behavior
date: 2026-10-19
author: Quasarr
touches:
  - quasarr/constants/__init__.py
  - quasarr/search/__init__.py
  - quasarr/storage/categories.py
---

## Decided

Keep category definitions, base-category semantics, behavior categories, cache-family ownership, and source whitelists as separate concepts.

Why: Radarr/Sonarr-facing categories can be stricter views of one content family. Search needs the base category for metadata and capability checks, the behavior category for query rules, and the cache owner for safe result reuse. Combining them makes subcategory filtering leak across requests.

## Watch out

Static category metadata comes from constants; mutable source lists and custom category settings come from storage.
