---
title: Preserve source identity through the emulated download payload
date: 2026-10-19
author: Quasarr
touches:
  - quasarr/providers/utils.py
  - quasarr/api/arr/__init__.py
  - quasarr/downloads/__init__.py
---

## Decided

Carry source identity in the generated download payload, preserving the shared encoding contract between search and grab.

Why: The *arr round-trip separates discovery from download submission. Source key, media metadata, and URL must survive encoding without ambiguity so dispatch can try the intended source first. Filename or hostname guesses cannot replace the original identity.

## Watch out

Payload generation and parsing change together; fallback dispatch does not erase the source key carried by search.
