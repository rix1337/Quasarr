---
title: Bound search fan-out by one absolute deadline
date: 2026-10-19
author: Quasarr
touches:
  - quasarr/search/__init__.py
  - quasarr/constants/__init__.py
---

## Decided

Anchor one absolute deadline before metadata warming and give each eligible source its own worker in the fan-out.

Why: *arr clients disable indexers that exceed their request budget. A relative timeout per source lets slow work accumulate, while a CPU-sized pool can queue sources that never get started. One worker per submitted source plus a shared wall-clock deadline preserves response bounds and source fairness.

## Watch out

No source gets a fresh full timeout after another source consumes the budget; pending work is abandoned when the shared deadline expires.
