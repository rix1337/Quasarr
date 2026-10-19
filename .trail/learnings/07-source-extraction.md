---
title: Keep download extraction source-specific
date: 2026-10-19
author: Quasarr
touches:
  - quasarr/downloads/sources/helpers/abstract_source.py
  - quasarr/downloads/sources/helpers/download_release.py
  - quasarr/downloads/sources/__init__.py
---

## Decided

Let each download source implement its own release-link extraction behind the shared source helper contract.

Why: Protected pages, redirects, mirrors, and release layouts differ by source. The orchestrator needs a common result shape, while extraction rules must stay close to the source that owns them so a change in one parser cannot widen or corrupt another source's links.

## Watch out

Shared download flow classifies and schedules extracted links; it does not infer source payloads or HTML structure.
