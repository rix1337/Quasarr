---
title: Retain Filecrypt solver failures for manual CAPTCHA solving
author: Quasarr
date: 2026-10-31
touches:
  - quasarr/api/sponsors_helper/__init__.py
  - tests/test_sponsors_helper_api.py
---

## Decided

Treat SponsorsHelper failure callbacks for protected Filecrypt packages as manual CAPTCHA work. Preserve the protected record and disable automatic helper selection. Paid solver exhaustion does not prove that a container is unavailable; retaining its links lets the browser userscript complete the download and keeps clients from blocklisting it.

## Tried and ruled out

The existing helper failure endpoint marks packages failed and deletes their protected records. The supplied logs show this causes clients to remove and reacquire downloads when providers cannot solve the upgraded CAPTCHA. Changing only the helper would leave older helper versions able to trigger that destructive path.

## Watch out

Apply the fallback to both explicit helper failure callbacks and empty or invalid helper download payloads. Preserve other crypters' terminal failures, including native episode-selection errors. The disabled flag stops helper retries while protected records remain available for manual solving. Persist notification references after updating the manual-fallback notification.
