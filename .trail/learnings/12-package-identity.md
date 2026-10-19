---
title: Use package UUIDs to preserve download ownership
date: 2026-10-19
author: Quasarr
touches:
  - quasarr/downloads/packages/__init__.py
  - quasarr/storage/categories.py
  - tests/test_package_identity.py
---

## Decided

Encode Quasarr package identity in the package ID and use JDownloader's package UUID to join package and link state.

Why: Names and comments can be changed by JDownloader or collide across jobs. The package UUID gives status, comments, cleanup, and category recovery one stable join key, while the strict ID pattern prevents unrelated packages from entering Quasarr lifecycle logic.

## Watch out

Package operations filter links by package UUID and recognize only IDs matching the project pattern.
