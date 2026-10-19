---
title: Serialize config and database writes with fixed lock order
date: 2026-10-19
author: Quasarr
touches:
  - quasarr/storage/config.py
  - quasarr/storage/sqlite_database.py
  - quasarr/storage/lock.py
---

## Decided

Protect INI and SQLite writes with the shared multiprocess lock, and allow lock acquisition only in config-then-database order.

Why: Setup and API workers can write concurrently, while forked or spawned processes may otherwise interleave file replacement and database updates. A fixed order prevents the two storage layers from deadlocking each other.

## Watch out

Database methods never call into config storage while holding the database lock; storage mutations remain serialized across processes.
