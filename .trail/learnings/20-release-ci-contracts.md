---
title: Keep release and CI safety constraints explicit
date: 2026-10-19
author: Quasarr
touches:
  - .github/workflows/PullRequests.yml
  - .github/workflows/Release.yml
  - pre-commit.py
  - .github/scripts/notify_simplex.py
  - pyproject.toml
---

## Decided

Treat release generation, CI auto-fix, and stable notification as one set of guarded contracts.

Why: Changelog generation must compare the checked-out commit: beta uses the PR head and stable uses the release commit, never a temporary merge SHA. Generated changelog text crosses into shell through an environment variable. Auto-fix dispatches one read-only follow-up with `--check`, which must not upgrade dependencies, push fixes, or dispatch another run. Stable notification waits for release artifacts and container manifests, beta sends none; delivery uses the Quasarr User-Agent, deduplicates by release tag, skips with a warning when secrets are absent, and fails when configured delivery fails. One pinned uv version across workflows and `pyproject.toml` keeps lock revisions stable.

## Watch out

CI and release jobs preserve these gates when action versions or workflow wiring change; notification never precedes published artifacts.
