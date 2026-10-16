# quasarr/downloads/ - Download Side

## Purpose

Receives a grab request from the SABnzbd-emulating API, picks the matching source module, extracts hoster/crypter links, classifies them, and either pushes plain links to JDownloader's linkgrabber, auto-decrypts hide-crypter containers, or parks protected links for the userscript-based CAPTCHA UI. Also renders the merged JDownloader + DB package state back as a SABnzbd queue/history.

## Ownership

- `__init__.py` - orchestrator: source selection, link classification, package IDs, the `submit_final_download_urls()` funnel, `fail()` bookkeeping
- `mirror_filters.py` - canonical mirror-token normalization and the final pre-JDownloader whitelist filter
- `packages/` - SABnzbd-shaped queue/history aggregation, archive/extraction tracking, auto-start, deletion
- `sources/` and `linkcrypters/` - see Child DOX Index

## Local Contracts

- `download()` candidate order: (1) the `source_key` from the search payload (trusted), (2) every registered source whose configured hostname is a substring of the URL, (3) raw-crypter fallback when the URL itself matches a crypter pattern. The first source returning non-empty links wins.
- Link classification priority is direct > auto > protected (`AUTO_DECRYPT_PATTERNS`/`PROTECTED_PATTERNS` in constants, the magic mirror label `junkies`, or a source result explicitly marked `protected: true`). If any direct links exist, crypted fallbacks are ignored. Nonterminal auto-decrypt failures are demoted into the protected bucket.
- A terminal grab failure logs its reason at ERROR and its successful failed-package persistence at WARN; failure to persist that state logs at ERROR.
- `process_links()` honors the filecrypt kill switch right after `classify_links()`: `_drop_filecrypt_if_disabled()` reads the cached `shared_state.values["filecrypt_enabled"]` (default `True`, set by `storage/setup/filecrypt.py`) and, when `False`, strips filecrypt links out of the protected bucket so the package fails cleanly if nothing else remains. `classify_links()` itself stays pure/shared_state-free; only the orchestrator applies the flag.
- Package IDs are deterministic: `Quasarr_{category}_{32-hex-hash}` validated by `PACKAGE_ID_PATTERN`; `package_id_exists()` checks the protected DB, failed DB, and JDownloader before any download. Sources may provide an optional stable identity for a URL; it extends the hash only when present, preserving legacy IDs.
- `submit_final_download_urls()` is the ONLY path that hands direct links to JDownloader (also imported by `api/captcha` and `api/sponsors_helper`). It applies the download-category mirror whitelist; if a whitelist drops everything, the package is persisted as failed.
- Protected-package JSON owns the tracked notification references for that release; no separate notification table exists. `submit_final_download_urls(..., remove_protected=True)` captures this context before deletion, edits the original notification on solved/failed outcomes, and accepts `notification_details` so manual and SponsorsHelper solutions render accurately.
- `fail()` deliberately returns `{"success": True, "failed": True}` so the *arr client records the grab and can blocklist it.
- Terminal source errors and terminal Hide selection failures persist through `fail()` into failed history with their original error. Missing requested episodes remain visible as `Episode not present in link container` so Sonarr can blacklist the release; they never silently disappear or fall back to an unfiltered container.
- `packages/` auto-start moves exactly ONE Quasarr package per call from linkgrabber to the download list; archive packages are only "finished" when extraction completed; `nzo_id` is the Quasarr package ID read from the JD `comment` field (JD uuid fallback for foreign packages).
- Sources call `mark_hostname_issue(initials, "download", msg)` on errors; the orchestrator clears the issue when a source returns usable links.

### Mirror-Selection Policy

Product-wide policy - do not redesign it; per-source specifics live in the Per-Source Notes of `quasarr/downloads/sources/AGENTS.md`.

- HARD RULE: Quasarr never verifies whether a direct hoster link is online and never fetches a hoster URL to probe liveness. Resolving and verifying hoster links is JDownloader's job (paid, hoster-specific handling Quasarr cannot and should not replicate). Never add a tier that fetches a direct hoster URL to test it.
- Selection picks the best link set from the source's own signals only. Tier 1: online-certified crypted container, cheapest crypter first - a green hide container (auto-resolves, no CAPTCHA) before a green filecrypt container (may cost a CAPTCHA). Tier 2: direct links carrying a green signal - best effort only, because the signal really certifies the container. Tier 3 (last resort): the first offline-flagged mirror, so the release still fails cleanly into the blacklist-and-retry path.
- If a source exposes no online signal at all: newest mirror first (when recency is known), then first/arbitrary mirror.
- A link that turns out dead is not a selection bug; it is absorbed by the *arr blacklist-and-retry flow. Rationale (measured on WX): direct links agree with their container ~95% of the time; the trade is deliberate - an online download that costs a CAPTCHA beats a fast download that is dead.
- A human manually clicking a still-online link will always beat the automated choice for a single release; that is not a signal Quasarr can generalize from and not a reason to start probing links.

## Work Guidance

- Link entries are lists, not tuples: `[url, mirror]` with an optional third `state_url` element (a missing `state_url` counts as online).
- Per-source mirror-name normalization is duplicated on purpose (each site labels hosters differently); the canonical global mapping lives in `mirror_filters.py` + `constants.MIRROR_TOKEN_ALIASES`.
- Episode selection must reach the crypter as an explicit filter (URL parameter or equivalent native selection). Do not implement Quasarr-side filename filtering; archive filenames may be randomized. If the requested native selection is unavailable or unconfirmed, fail the grab rather than downloading the whole container, including through protected fallback.

## Verification

- Targeted tests: `test_mirror_filters.py`, `test_protected_redirect_resolution.py`, `test_wx_direct_links.py`
- Full unit suite: `uv run python -X utf8 -m unittest discover -s tests`

## Child DOX Index

- `quasarr/downloads/sources/AGENTS.md` - per-source download plug-in contract (`Source` class, `initials`, `get_download_links`, `DownloadRelease` shape) and shared helpers
- `quasarr/downloads/linkcrypters/AGENTS.md` - crypter decryption toolkits (hide auto-decrypt, AL solver)
