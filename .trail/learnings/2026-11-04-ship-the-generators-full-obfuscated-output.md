---
title: Ship the userscript generator's full output unchanged
date: 2026-11-04
author: Quasarr
touches:
  - quasarr/providers/obfuscated.py
---

## Decided

Commit the complete obfuscated module that the companion userscript generator writes. Do not keep only the changed helper's function and revert the others.

Why: obfuscation is not deterministic, so each regeneration rewrites every helper anyway. Splicing out one helper can ship helpers that no longer match the companion sources.

## Tried and ruled out

Earlier sessions kept only one helper's generated function to shrink the diff. The user rejected this approach.

## Watch out

Never edit the obfuscated module by hand. Make helper changes in the companion userscript sources, then regenerate.
