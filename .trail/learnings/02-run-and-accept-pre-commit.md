---
title: Run pre-commit and accept all of its edits
date: 2026-10-19
author: Quasarr
touches:
  - AGENTS.md
  - pre-commit.py
  - pyproject.toml
  - uv.lock
  - quasarr/providers/version.py
---

## Decided

Before finalizing changes or pushing, run `uv run python -X utf8 pre-commit.py`. Accept and keep every edit it makes, including formatting, dependency upgrades, lockfile changes, and version bumps. Do not revert its edits as unrelated cleanup.

Why: The script upgrades dependencies before formatting and testing, so its resulting files are the validated submission. Reverting them discards that validation and leaves CI to restore them in separate automatic commits.

## Watch out

Use the uv version required by the project. Re-run pre-commit after history rewrites and keep its resulting edits before pushing. A failed run must be fixed and completed successfully; it is not permission to skip the gate. The no-source-hostnames rule still takes precedence.
