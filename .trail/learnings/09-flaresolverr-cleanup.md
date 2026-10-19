---
title: Clean uncertain solver sessions asynchronously
date: 2026-10-19
author: Quasarr
touches:
  - quasarr/providers/cloudflare.py
---

## Decided

When solver session creation times out after a session may exist, queue bounded asynchronous cleanup instead of blocking the request indefinitely.

Why: A create timeout leaves ownership uncertain. Listing sessions before destruction handles delayed visibility, while exponential retry, a hard cleanup deadline, and endpoint round-robin prevent one backlog from starving another endpoint.

## Watch out

Cleanup is best-effort but bounded; pending session IDs cannot consume unbounded threads, retries, or request time.
