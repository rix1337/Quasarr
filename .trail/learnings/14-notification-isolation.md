---
title: Isolate notification providers behind one dispatcher
date: 2026-10-19
author: Quasarr
touches:
  - quasarr/providers/notifications/__init__.py
  - quasarr/providers/notifications/helpers/message_builder.py
  - quasarr/storage/setup/notifications.py
---

## Decided

Separate normalized notification meaning from independent provider delivery, case preferences, and silence settings.

Why: Notification delivery is optional and providers fail independently. Shared message construction keeps event meaning consistent, while isolated sends prevent one provider outage from suppressing the others. Tracked sends preserve provider references for later updates.

## Watch out

A notification succeeds when at least one enabled provider delivers; one provider exception does not abort the dispatch.
