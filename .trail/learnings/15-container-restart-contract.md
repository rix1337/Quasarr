---
title: Reserve container exit codes for restart policy
date: 2026-10-19
author: Quasarr
touches:
  - docker/Dockerfile
  - quasarr/__init__.py
---

## Decided

Let the Docker entrypoint restart Quasarr after exit code zero and stop the container on any nonzero exit.

Why: A clean process exit can follow a recoverable restart condition, while integrity or configuration failures must remain visible and stop retry churn. The application therefore uses its exit status as the boundary between recovery and failure.

## Watch out

Changes to startup failure handling must preserve the zero-restart/nonzero-stop contract unless the container policy changes with it.
