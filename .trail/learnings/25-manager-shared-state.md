---
title: Keep process state behind one manager-backed module
date: 2026-10-19
author: Quasarr
touches:
  - quasarr/__init__.py
  - quasarr/providers/shared_state.py
---

## Decided

Put cross-process runtime values in the manager-backed `shared_state` module, while storing the `Config` and `DataBase` classes there as service handles.

Why: Search, downloads, setup, and background workers need one state contract, but each worker has its own interpreter. A module-level registry gives callers a stable access point while the manager provides shared values and locking.

## Watch out

Consumers use the shared registry; they do not create parallel process-local copies of shared configuration or database handles.
