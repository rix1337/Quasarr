---
title: Switch off each crypter separately while it is broken
author: Quasarr
date: 2026-11-03
touches:
  - quasarr/constants/__init__.py
  - quasarr/storage/setup/crypters.py
  - quasarr/downloads/__init__.py
  - quasarr/api/__init__.py
---

## Decided

Every crypter (FileCrypt, Hide, KeepLinks, ToLink) gets its own manual kill switch, replacing the FileCrypt-only switch. A switched-off crypter drops its links from new grabs only; if nothing usable remains, the grab fails with a reason naming the switched-off crypters so *arr picks another release.

Hostnames with their own protection (HE, AL, Junkies) get no switch: when one breaks, remove the hostname instead.

## Watch out

The settings table keeps its original `filecrypt_enabled` name so saved FileCrypt choices survive the upgrade. Packages already in the protected queue are not touched by the switches.
