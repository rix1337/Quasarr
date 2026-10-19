---
title: Audit API keys separately from optional browser authentication
date: 2026-10-19
author: Quasarr
touches:
  - quasarr/providers/auth.py
  - quasarr/api/__init__.py
---

## Decided

Keep API-key protection explicit and audit protected route groups at startup, independently of optional browser authentication.

Why: Browser auth mode does not establish whether browser protection is enabled; that requires both configured credentials. API routes still need their generated API key when browser credentials are absent. A startup audit catches newly registered API routes that silently inherit the browser default.

## Watch out

API groups carry explicit API-key guards; browser routes follow effective credential state and public exceptions remain explicit.
