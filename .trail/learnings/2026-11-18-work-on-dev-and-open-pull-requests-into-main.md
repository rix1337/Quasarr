---
title: Work on dev and open pull requests from dev into main
author: Quasarr
date: 2026-11-18
touches:
  - AGENTS.md
---

## Decided

Changes are made and pushed on `dev`. When the work is done and every check passes, a pull request goes from `dev` into `main`; nothing is committed to `main` directly, and no feature branch is made unless asked.

Why: `main` is the release branch. Its version is what the pre-commit script compares against before bumping, so changes reach it only through a reviewed pull request from `dev`.

## Watch out

Run the pre-commit script before pushing `dev` and keep its version bump. Before opening the pull request, run the content privacy gate and `trail check` against `main`.
