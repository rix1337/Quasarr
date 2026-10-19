---
title: Treat config persistence as encrypted atomic storage
date: 2026-10-19
author: Quasarr
touches:
  - quasarr/storage/config.py
  - tests/test_config_atomic_writes.py
  - tests/test_config_secret_decryption.py
---

## Decided

Encrypt sensitive config values at rest and write config through an atomic replacement path.

Why: Credentials must not appear as plain persistent values, and a process interruption during a direct write could destroy the only usable config. Read-time decryption keeps callers working with normal values while atomic replacement protects the file boundary. If the INI is restored without its matching database, undecryptable ciphertext is reported as unset but preserved so restoring the matching database can recover it. Startup treats storage maintenance as tri-state: healthy, repaired, or failed, so a transient lock or maintenance error cannot be mistaken for a clean database or silently kill startup.

## Watch out

Callers see decrypted settings in memory; disk format remains encrypted for secrets and complete-file replacement is the persistence operation. A failed decrypt never overwrites ciphertext, and only an explicit integrity failure blocks startup.
