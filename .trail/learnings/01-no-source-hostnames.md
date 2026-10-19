---
title: Never name or commit real source hostnames
date: 2026-10-19
author: Quasarr
touches:
  - AGENTS.md
  - check_trail.py
  - quasarr/storage/config.py
---

## Decided

Never name, hardcode, or commit real source hostnames. Never put them in any file that is not gitignored, including code, tests, comments, learnings, captures, temporary scripts, and generated assets. Refer to sources only by their two-letter uppercase identifiers. Hostnames belong in encrypted runtime configuration outside the versioned repository.

Why: Source identity is runtime configuration, not public repository content. Architectural knowledge and reproducible tests must preserve behavior without publishing configured sources or user information.

## Watch out

Use synthetic titles and reserved `.invalid` domains in examples and tests. Keep real traffic evidence gitignored and extract only sanitized conclusions. Never force-add ignored captures or configuration. A pre-commit edit does not override this prohibition.
