# quasarr/downloads/linkcrypters/ — Crypter Decryption

## Purpose

Self-contained decryption logic for link-crypter containers, with three distinct consumers: the download orchestrator (auto-decrypt), the `/captcha` UI, and the AL source.

## Ownership

- `hide.py` — the only crypter auto-decrypted inside `process_links` (no CAPTCHA): resolves redirects, decrypts containers via the crypter's JSON API in thread batches, resolves `/fc/` "foreign" filecrypt-twin IDs to canonical container IDs. Returns `{"status": "success"|"none"|"error", "results": [urls]}`.
- `filecrypt.py` — protected-crypter toolkit consumed exclusively by `quasarr/api/captcha`: captcha-type detection (none/pow/circle/cutcaptcha/password/unknown), Cloudflare bypass via the shared FlareSolverr helper (`providers/cloudflare.py`), proof-of-work via flaresolverr-next `executeJs` + trusted CDP click, then CNL → DLC → single-link-button → Go-URL-resolution fallbacks, including season/episode-filtered CNL. Every FileCrypt browser navigation installs the userscript's page-world clickjacking blocker at document start and requires the solver's installation acknowledgement before interacting. Returns `False` on failure, `{"status": "success", "links": [...]}`, or handoff dicts (`captcha_required`/`circle_required`/`single_link_circle_required`).
- `al.py` — AL-source-only helpers: CNL AES-CBC decrypt (jk hex chars 15/16 swapped), mirror-filtered `decrypt_content`, and a pixel-difference image-captcha solver (requires FlareSolverr). AL binds a solved CAPTCHA to the `requests.Session` that solved it: FlareSolverr only arms the challenge (the `nocaptcha` `/ajax/captcha` request), while the icon fetch + selection submit (`/files/captcha`) and the final `/ajax/captcha` validation must run on that same session — validating from the FlareSolverr browser instead is rejected with `The captcha ID was invalid`.

## Local Contracts

- Callers depend on the exact return shapes above; changing them means updating `downloads/__init__.py` (hide) and `api/captcha` (filecrypt) in the same change.
- Crypter brand hostnames committed in this folder (filecrypt/hide families, the JD dlcrypt service) are the accepted exception to the no-hostname rule — they are link-crypter services, not sources. Never add source hostnames here.

## Work Guidance

- Keep crypter-detection substrings in sync with `constants.AUTO_DECRYPT_PATTERNS`/`PROTECTED_PATTERNS` and the routing in `api/captcha`.

## Verification

- Targeted tests: `test_filecrypt_pow.py`; full suite: `uv run python -X utf8 -m unittest discover -s tests`

## Child DOX Index

None.
