---
title: Use source keys as stable cross-layer identity
date: 2026-10-19
author: Quasarr
touches:
  - quasarr/search/sources/__init__.py
  - quasarr/search/sources/templates/__init__.py
  - quasarr/downloads/sources/__init__.py
  - quasarr/constants/__init__.py
---

## Decided

Represent each source with one key shared by its bundled template, hostname config entry, logs, and its download step. Built-in sites use two letters; user-defined sites use a letter and a digit.

Why: The key is the join between configuration, discovery, capability metadata, logs, and extraction. Keeping source-specific behavior in the site's template (and the code it links) prevents shared orchestration from accumulating hostname rules. A template without download links leaves grabs to the generic crypter detection.

## Watch out

Source-specific hostname logic stays at the source boundary; shared code consumes source metadata and keys.
