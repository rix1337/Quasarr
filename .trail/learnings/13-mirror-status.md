---
title: Evaluate mirrors as one package decision
date: 2026-10-19
author: Quasarr
touches:
  - quasarr/downloads/packages/__init__.py
  - quasarr/downloads/mirror_filters.py
---

## Decided

Group links by mirror domain before deciding package status and cleanup.

Why: A failed or offline mirror is recoverable when a sibling mirror remains usable. Per-link decisions would delete useful alternatives or report a package failed while a valid mirror exists.

## Watch out

Cleanup removes unusable sibling links only when package-level evidence shows an online alternative; extraction activity can override a naive archive-only status.
