---
title: Statistics split hostname timeouts from errors
author: Quasarr
date: 2026-11-03
touches:
  - quasarr/providers/statistics.py
  - quasarr/providers/hostname_issues.py
  - quasarr/api/statistics/chart.py
---

## Decided

The statistics page plots daily history instead of lifetime counters. Each event writes a per-day row (`day:`, `issue:`, `timeout:`, `hosts:`) into the `statistics` table, and the lifetime counters are deleted by the first daily prune after upgrade.

Hostname problems are split: timeouts go to `timeout:` rows (orange line), everything else to `issue:` rows (red line). A host with both on one day counts as an error only.

Why: A line chart needs timestamps the old totals never had. Per-day rows keep increments cheap and bound storage; a daily marker row (`pruned:`) makes the first write of each day drop rows older than 30 days, so retention does not depend on anyone opening the page. A slow host is not a broken one, so timeouts should not inflate the error line. The classification lives in `mark_hostname_issue` and reads the error text ("timed out"/"timeout") because its ~80 callers pass `str(e)`; classifying once there avoids changing every source.

## Watch out

`mark_hostname_issue` must never raise because failure handlers call it; the statistics write is wrapped. The red line counts distinct sources with at least one non-timeout issue that day, not events and not current state. Rows written before the split are all errors. The chart is native inline SVG; do not add external scripts.

In the code: `is_timeout_message` in quasarr/providers/hostname_issues.py, `get_history` in quasarr/providers/statistics.py.
