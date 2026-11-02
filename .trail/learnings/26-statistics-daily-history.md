---
title: Statistics keep only 30 days of per-day rows
date: 2026-11-02
author: Quasarr
touches:
  - quasarr/providers/statistics.py
  - quasarr/providers/hostname_issues.py
  - quasarr/api/statistics/chart.py
---

## Decided

The statistics page plots daily history instead of lifetime counters. Each event writes a per-day row (`day:`, `issue:`, `hosts:`) into the `statistics` table, and the lifetime counters are deleted by the first daily prune after upgrade.

Why: A line chart needs timestamps the old totals never had. Per-day rows keep increments cheap and bound storage; a daily marker row (`pruned:`) makes the first write of each day drop rows older than 30 days, so retention does not depend on anyone opening the page.

## Watch out

`mark_hostname_issue` must never raise because failure handlers call it; the statistics write is wrapped. The red hostname line counts distinct sources with at least one recorded issue that day, not events and not current state. The chart is native inline SVG; do not add external scripts.
