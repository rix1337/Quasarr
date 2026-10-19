---
title: Use source keys as stable cross-layer identity
date: 2026-10-19
author: Quasarr
touches:
  - quasarr/search/sources/__init__.py
  - quasarr/downloads/sources/__init__.py
  - quasarr/constants/__init__.py
---

## Decided

Represent each source with one two-letter key shared by its search module, hostname config entry, logs, and any source-specific download extractor.

Why: The key is the join between configuration, discovery, capability metadata, logs, and extraction. Keeping source-specific behavior in source modules prevents shared orchestration from accumulating hostname rules. Search-only sources may omit a download module and use generic crypter detection.

## Watch out

Source-specific hostname logic stays at the source boundary; shared code consumes source metadata and keys.
