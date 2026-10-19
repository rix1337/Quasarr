---
title: Pin worker creation to spawn
date: 2026-10-19
author: Quasarr
touches:
  - quasarr/__init__.py
  - quasarr/storage/lock.py
---

## Decided

Start multiprocessing workers with `spawn` from `run()`.

Why: Forking copies parent-bound locks and open handles into workers. The application starts workers after shared state and storage are initialized, so inheriting that state can leave child processes attached to unsafe resources. The entrypoint owns this choice because both the console entrypoint and Docker start there.

## Watch out

Worker startup must not depend on parent process memory or inherited storage locks.
